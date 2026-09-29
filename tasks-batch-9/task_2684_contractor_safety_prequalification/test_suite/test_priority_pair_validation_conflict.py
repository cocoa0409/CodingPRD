"""Difficulty rule: priority_pair_validation_conflict.

Two requests that violate several checks at once. Only the earliest check in
the network-wide precedence order may be reported.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_PREQUAL_NOT_ACTIVE,
    ERR_SUBCONTRACTOR_CYCLE,
)
from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_prequalification_state,
    assert_site_posture,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import grant_payload, link_payload  # noqa: E402


def _suspended_standing_locked_gate_expired_credential(build):
    """Three simultaneous grant failures: suspension, lock and stale badge."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(with_worker=False)

    worker = build.worker_with_qualifications(
        scenario["contractor_id"],
        ("OSHA10",),
        issued_date="2023-07-15T00:00:00Z",
        expiration_date="2026-07-15T00:00:00Z",
    )
    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="FATALITY",
        description="Trench collapse fatality during utility tie-in",
    )
    scenario["worker"] = worker
    scenario["worker_id"] = worker["id"]
    scenario["incident"] = incident
    return scenario


def test_suspended_prequalification_is_reported_before_the_locked_site_gate(build, api):
    """Priority 12 wins over priority 16 and priority 18.

    PRD Section 3.8: "The prequalification must be in `APPROVED` or
    `CONDITIONAL` — conditional standing is sufficient — else
    `ERR_PREQUAL_NOT_ACTIVE`. The site's freshly recomputed gate must not be
    locked, else `ERR_SITE_GATE_LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_prequalification_beats_locked_site_gate_and_expired_worker_qualification
    """
    scenario = _suspended_standing_locked_gate_expired_credential(build)

    # All three conditions really are violated at once.
    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]), status="SUSPENDED"
    )
    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, access_gate_status="LOCKED")
    credentials, _meta = validate_paginated(
        api.list_qualifications(
            scenario["worker_id"], scenario["contractor_headers"], {"qualification_code": "OSHA10"}
        )
    )
    assert credentials and credentials[0]["expiration_date"].startswith("2026-07-15"), (
        "the only OSHA10 row expired before the logical clock"
    )

    response = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            scenario["site_id"],
            scenario["prequalification_id"],
            "2026-12-31T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_PREQUAL_NOT_ACTIVE, 409)


def test_refused_grant_leaves_the_site_counter_and_grant_ledger_empty(build, api):
    """The refusal writes nothing at all on the site or the grant collection.

    PRD Section 2.10: "The first is a site's `granted_worker_count`, which must
    always equal the number of site access grants on that site whose `status` is
    exactly `GRANTED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_prequalification_beats_locked_site_gate_and_expired_worker_qualification
    """
    scenario = _suspended_standing_locked_gate_expired_credential(build)

    response = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            scenario["site_id"],
            scenario["prequalification_id"],
            "2026-12-31T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_PREQUAL_NOT_ACTIVE, 409)

    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=0)

    rows, meta = validate_paginated(
        api.list_grants(scenario["manager_headers"], {"site_id": scenario["site_id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no grant rows on the site, got {meta['total_count']}"
    )
    assert rows == []


def _prime_and_sub_with_lapsed_prime_coverage(build):
    """An ACTIVE prime-to-sub edge, then a clock advance that lapses the prime."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(with_worker=False)

    sub = build.create_contractor(
        legal_name="Bolt Rigging",
        scope_of_work=["SCAFFOLDING"],
        hazard_profile=["GENERAL"],
        employee_count=12,
    )
    build.verified_certificate(
        sub["id"],
        "GL",
        each_occurrence_limit=1000000,
        aggregate_limit=2000000,
        effective_date="2026-07-01T00:00:00Z",
        expiration_date="2028-07-01T00:00:00Z",
    )
    link = build.create_link(
        scenario["contractor_id"],
        sub["id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
        scope_of_work=["SCAFFOLDING"],
    )

    # A bare clock advance one day past the prime's own coverage expiry.
    build.set_clock("2027-07-02T00:00:00Z")

    scenario["sub"] = sub
    scenario["link"] = link
    return scenario


def test_cyclic_edge_is_reported_before_the_childs_lapsed_flow_down_coverage(build, api):
    """Priority 23 wins over priority 29 on the reversed edge.

    PRD Section 3.10: "Because acyclicity is checked before coverage, a proposed
    edge that is both cyclic and under-insured reports the cycle code, never the
    coverage code."

    Design: Difficulty/priority_pair_validation_conflict/cyclic_subcontractor_edge_beats_lapsed_flow_down_coverage_on_the_child
    """
    scenario = _prime_and_sub_with_lapsed_prime_coverage(build)

    # The proposed child — the prime itself — no longer carries live GL cover.
    rows, _meta = validate_paginated(
        api.list_certificates(
            scenario["contractor_id"],
            scenario["contractor_headers"],
            {"coverage_type": "GL"},
        )
    )
    assert len(rows) == 1
    assert_certificate_state(
        rows[0], verification_status="VERIFIED", lifecycle_status="LAPSED"
    )

    response = api.create_link(
        link_payload(
            scenario["sub"]["id"],
            scenario["contractor_id"],
            scenario["prequalification_id"],
            ["MECHANICAL_TRADE"],
        ),
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_SUBCONTRACTOR_CYCLE, 409)


def test_refused_cyclic_edge_leaves_exactly_one_active_edge_at_depth_one(build, api):
    """The graph is unchanged: the forward edge still stands alone at depth 1.

    PRD Section 3.10: "An edge whose parent is the prequalification's own
    contractor sits at `depth` 1."

    Design: Difficulty/priority_pair_validation_conflict/cyclic_subcontractor_edge_beats_lapsed_flow_down_coverage_on_the_child
    """
    scenario = _prime_and_sub_with_lapsed_prime_coverage(build)

    response = api.create_link(
        link_payload(
            scenario["sub"]["id"],
            scenario["contractor_id"],
            scenario["prequalification_id"],
            ["MECHANICAL_TRADE"],
        ),
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_SUBCONTRACTOR_CYCLE, 409)

    rows, meta = validate_paginated(
        api.list_links(
            scenario["contractor_headers"],
            {"prequalification_id": scenario["prequalification_id"], "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one ACTIVE edge, got {meta['total_count']}"
    )
    assert rows[0]["depth"] == 1
    assert rows[0]["parent_contractor_id"] == scenario["contractor_id"]
    assert rows[0]["child_contractor_id"] == scenario["sub"]["id"]
