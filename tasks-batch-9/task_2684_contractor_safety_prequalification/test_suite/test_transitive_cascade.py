"""Difficulty rule: transitive_cascade.

One filing reaches five levels down inside its own request: the incident row,
the contractor, the prequalification, the badge, the site counter, and the
sibling subcontractor edge hanging off the same standing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import validate_paginated, validate_success  # noqa: E402

from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_contractor_posture,
    assert_grant_state,
    assert_instant_equals,
    assert_prequalification_state,
    assert_site_posture,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402


def _prime_with_badge_and_subcontractor(build):
    """An approved prime holding a badge plus one ACTIVE edge to a sub."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()

    grant = build.grant_badge(
        scenario["worker_id"],
        scenario["site_id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
    )

    sub = build.create_contractor(
        legal_name="Bolt Rigging",
        scope_of_work=["SCAFFOLDING"],
        hazard_profile=["GENERAL"],
        employee_count=12,
    )
    build.insure(sub["id"], ("GL",))
    sub_prequalification = build.open_prequalification(sub["id"], scenario["client_id"])

    link = build.create_link(
        scenario["contractor_id"],
        sub["id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
        scope_of_work=["SCAFFOLDING"],
    )

    scenario["grant"] = grant
    scenario["sub"] = sub
    scenario["sub_prequalification"] = sub_prequalification
    scenario["link"] = link
    return scenario


def test_fatality_filing_suspends_the_standing_and_revokes_the_badge(build, api):
    """Levels one to four: incident, contractor, prequalification, grant, site.

    PRD Section 3.9: "Every prequalification of that contractor whose `status` is
    `APPROVED` or `CONDITIONAL` — across all clients, not merely the client that
    filed the report — is carried to `SUSPENDED`, processed in ascending
    `created_at` order."

    Design: Difficulty/transitive_cascade/fatality_incident_cascades_flag_suspension_revocation_site_count_and_flow_down
    """
    scenario = _prime_with_badge_and_subcontractor(build)

    # The edge opened at PENDING because the child holds a DRAFT application.
    assert scenario["link"]["flow_down_status"] == "PENDING"
    assert scenario["link"]["depth"] == 1

    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="FATALITY",
        description="Crane counterweight struck a rigger during a lift",
    )

    stored_incident = validate_success(
        api.get_incident(incident["id"], scenario["manager_headers"])
    )
    assert stored_incident["review_status"] == "OPEN"
    assert stored_incident["triggered_suspension_count"] == 1, (
        "the report records how many standings it froze"
    )

    contractor = build.read_contractor(scenario["contractor_id"])
    assert_contractor_posture(
        contractor,
        status="ACTIVE",
        incident_review_flag=True,
        open_severe_incident_count=1,
    )

    suspended = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(
        suspended, status="SUSPENDED", grade="B", final_composite_score=80.51
    )

    revoked = validate_success(
        api.get_grant(scenario["grant"]["id"], scenario["manager_headers"])
    )
    assert_grant_state(
        revoked, status="REVOKED", revocation_reason="PREQUAL_SUSPENDED"
    )
    assert_instant_equals(revoked["revoked_at"], INITIAL_CLOCK)

    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=0, access_gate_status="LOCKED")


def test_fatality_filing_reaches_the_sibling_edge_and_the_insurance_aggregate(build, api):
    """Level five plus the sibling branch: flow-down and depleted aggregate.

    PRD Section 3.10: "If the prime's own `status` is `REJECTED`, `EXPIRED` or
    `SUSPENDED`, the edge is `DEFICIENT` regardless of anything the child has
    done."

    Design: Difficulty/transitive_cascade/fatality_incident_cascades_flag_suspension_revocation_site_count_and_flow_down
    """
    scenario = _prime_with_badge_and_subcontractor(build)

    build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="FATALITY",
        description="Crane counterweight struck a rigger during a lift",
    )

    edge = validate_success(
        api.get_link(scenario["link"]["id"], scenario["contractor_headers"])
    )
    assert edge["status"] == "ACTIVE", "the freeze recomputes flow-down, it does not cut edges"
    assert edge["flow_down_status"] == "DEFICIENT", (
        f"expected flow_down_status DEFICIENT, got {edge['flow_down_status']}"
    )

    # Section 3.9: the open severe incident re-materializes available_aggregate
    # on every one of the prime's certificates.
    rows, _meta = validate_paginated(
        api.list_certificates(
            scenario["contractor_id"],
            scenario["contractor_headers"],
            {"coverage_type": "GL"},
        )
    )
    assert len(rows) == 1
    assert_certificate_state(
        rows[0], verification_status="VERIFIED", available_aggregate=1750000
    )

    # The child's own standing is untouched by the prime's freeze.
    child_row = build.read_prequalification(scenario["sub_prequalification"]["id"])
    assert_prequalification_state(child_row, status="DRAFT")
