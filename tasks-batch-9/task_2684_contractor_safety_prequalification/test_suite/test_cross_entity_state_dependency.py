"""Difficulty rule: cross_entity_state_dependency.

A gate on one entity is decided by the state of a different entity: a
certificate that lapsed without any write, and an incident filed against a
completely unrelated contractor at the same site.
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
    ERR_MISSING_VERIFIED_COVERAGE,
    ERR_SITE_GATE_LOCKED,
)
from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_contractor_posture,
    assert_grant_state,
    assert_prequalification_state,
    assert_site_posture,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import grant_payload  # noqa: E402


def _under_review_with_one_lapsing_certificate(build):
    """GL expires 2026-09-01, WC 2027-07-01; the clock then jumps to 2026-09-02."""
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()

    gl = build.verified_certificate(
        contractor["id"],
        "GL",
        each_occurrence_limit=1000000,
        aggregate_limit=2000000,
        effective_date="2026-07-01T00:00:00Z",
        expiration_date="2026-09-01T00:00:00Z",
    )
    wc = build.verified_certificate(contractor["id"], "WC")

    prequalification = build.open_prequalification(contractor["id"], client["id"])
    build.verified_statistic(prequalification["id"], contractor["id"])
    build.accept_required_programs(
        prequalification["id"], contractor["id"], client["id"], ["GENERAL"]
    )
    submitted = build.submit_prequalification(prequalification["id"], contractor["id"])
    assert_prequalification_state(submitted, status="UNDER_REVIEW")

    # A bare clock advance one day past the GL expiration date. Nothing else.
    build.set_clock("2026-09-02T00:00:00Z")

    return {
        "client_id": client["id"],
        "contractor_id": contractor["id"],
        "prequalification_id": prequalification["id"],
        "gl": gl,
        "wc": wc,
        "manager_headers": build.manager_headers(client["id"]),
        "contractor_headers": build.contractor_headers(contractor["id"]),
    }


def test_grading_is_blocked_by_coverage_that_lapsed_on_a_bare_clock_advance(build, api):
    """No write touched the certificate, yet grading refuses on coverage.

    PRD Section 3.6: "Every coverage type in the client's
    `required_coverage_types` must be backed by a certificate whose
    `verification_status` is `VERIFIED` and whose **freshly recomputed**
    lifecycle position is `CURRENT` or `EXPIRING_SOON`, otherwise
    `ERR_MISSING_VERIFIED_COVERAGE` — a certificate that has silently lapsed
    against the clock blocks grading even though its stored lifecycle field
    still reads `CURRENT`."

    Design: Difficulty/cross_entity_state_dependency/grading_blocked_by_silently_lapsed_coverage_after_a_bare_clock_advance
    """
    scenario = _under_review_with_one_lapsing_certificate(build)

    response = api.grade_prequalification(
        scenario["prequalification_id"], {}, scenario["manager_headers"]
    )
    validate_error(response, ERR_MISSING_VERIFIED_COVERAGE, 409)

    # The verification dimension is untouched by the clock.
    rows, _meta = validate_paginated(
        api.list_certificates(
            scenario["contractor_id"], scenario["contractor_headers"], {"coverage_type": "GL"}
        )
    )
    assert len(rows) == 1
    assert_certificate_state(rows[0], verification_status="VERIFIED")

    row = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(
        row, status="UNDER_REVIEW", grade=None, final_composite_score=None
    )
    assert row["graded_at"] is None
    assert row["effective_thresholds"] is None


def test_requalification_run_counts_the_certificate_the_clock_lapsed(build, api):
    """The run is the writer that reconciles the lapse, and it counts one.

    PRD Section 3.11: "The fourth step refreshes insurance: `lifecycle_status`
    and `available_aggregate` are re-materialized on every insurance certificate
    held by every contractor that holds a prequalification with this client, and
    each such contractor's `verified_coverage_types` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/grading_blocked_by_silently_lapsed_coverage_after_a_bare_clock_advance
    """
    scenario = _under_review_with_one_lapsing_certificate(build)

    result = validate_success(
        api.run_requalification(scenario["client_id"], {}, scenario["manager_headers"]),
        200,
    )
    assert result["lapsed_certificate_count"] == 1, (
        f"expected exactly one lapsed certificate, got {result['lapsed_certificate_count']}"
    )
    assert result["expired_count"] == 0
    assert result["conditional_rejected_count"] == 0

    rows, _meta = validate_paginated(
        api.list_certificates(
            scenario["contractor_id"], scenario["contractor_headers"], {"coverage_type": "GL"}
        )
    )
    assert_certificate_state(
        rows[0], verification_status="VERIFIED", lifecycle_status="LAPSED"
    )
    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]),
        verified_coverage_types=["WC"],
    )


def _site_locked_by_an_unrelated_contractor(build):
    """Acme is approved and clean; Summit's open lost-time report locks PLANT-7."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()

    unrelated = build.create_contractor(
        legal_name="Summit Steel Erectors",
        scope_of_work=["GENERAL_BUILDING"],
        hazard_profile=["GENERAL"],
        employee_count=120,
    )
    incident = build.file_incident(
        scenario["client_id"],
        unrelated["id"],
        scenario["site_id"],
        severity="LOST_TIME",
        description="Scaffold plank failure, two lost work days",
    )
    scenario["unrelated"] = unrelated
    scenario["incident"] = incident
    return scenario


def test_another_contractors_open_lost_time_report_locks_the_gate(build, api):
    """Acme is refused although its own standing and flag are clean.

    PRD Section 3.8: "A site's `access_gate_status` is a posture derived from the
    open incident record at that site, counting incidents filed against **every**
    contractor working there, not just the one being badged."

    Design: Difficulty/cross_entity_state_dependency/site_gate_locked_by_a_different_contractors_open_lost_time_incident
    """
    scenario = _site_locked_by_an_unrelated_contractor(build)

    response = api.create_grant(
        grant_payload(
            scenario["worker_id"],
            scenario["site_id"],
            scenario["prequalification_id"],
            "2026-12-31T00:00:00Z",
        ),
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_SITE_GATE_LOCKED, 409)

    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]),
        status="APPROVED",
        grade="B",
    )
    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]),
        incident_review_flag=False,
        open_severe_incident_count=0,
    )
    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=0, access_gate_status="LOCKED")


def test_closing_the_unrelated_review_reopens_the_gate_for_the_clean_contractor(build, api):
    """Once the report closes, the badge issues with its frozen snapshot.

    PRD Section 3.8: "When the grant is issued, the resolved demand set is frozen
    into the grant's `qualification_snapshot` array, sorted ascending by code
    name."

    Design: Difficulty/cross_entity_state_dependency/site_gate_locked_by_a_different_contractors_open_lost_time_incident
    """
    scenario = _site_locked_by_an_unrelated_contractor(build)

    closed = build.close_incident(scenario["incident"]["id"], scenario["client_id"])
    assert closed["review_status"] == "CLOSED"
    assert_contractor_posture(
        build.read_contractor(scenario["unrelated"]["id"]),
        incident_review_flag=False,
        open_severe_incident_count=0,
    )

    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, access_gate_status="OPEN")

    grant = validate_success(
        api.create_grant(
            grant_payload(
                scenario["worker_id"],
                scenario["site_id"],
                scenario["prequalification_id"],
                "2026-12-31T00:00:00Z",
            ),
            scenario["contractor_headers"],
        ),
        201,
    )
    assert_grant_state(grant, status="GRANTED", qualification_snapshot=["OSHA10"])

    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=1, access_gate_status="OPEN")
