"""Corner section: calculations.

Materialization at creation time, the input set a conserved counter sums over,
and the declared tie-break of the audit draw.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_exact_int,
    assert_instant_equals,
    assert_prequalification_state,
    assert_rate_equals,
    assert_score_equals,
    assert_site_posture,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import statistic_payload  # noqa: E402


def test_statistic_creation_materializes_citation_points_trir_and_dart_rate(build, api):
    """The three derived metrics land on the row while it is still PENDING.

    PRD Section 3.3: "Citation history is collapsed into a single integer
    `citation_points` by weighting severity: each willful citation contributes 5
    points, each serious citation contributes 2 points, and each other-than-serious
    citation contributes 1 point; the three products are added and the result is an
    exact integer with no rounding step at all."

    Design: Corner/calculations/statistic_creation_materializes_citation_points_trir_and_dart_rate
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    prequalification = build.open_prequalification(contractor["id"], client["id"])

    filed = validate_success(
        api.create_statistic(
            prequalification["id"],
            statistic_payload(
                hours_worked=400000,
                recordable_incidents=4,
                dart_cases=2,
                emr=0.95,
                citation_count_willful=1,
                citation_count_serious=2,
                citation_count_other=3,
            ),
            build.contractor_headers(contractor["id"]),
        ),
        201,
    )

    assert filed["verification_status"] == "PENDING"
    assert filed["verified_at"] is None
    assert filed["verified_by_user_id"] is None

    # 5*1 + 2*2 + 1*3 = 12, an exact integer with no rounding step.
    assert_exact_int(filed["citation_points"], 12)
    # 4 * 200000 / 400000 = 2.0000 and 2 * 200000 / 400000 = 1.0000.
    assert_rate_equals(filed["trir"], 2.0000)
    assert_rate_equals(filed["dart_rate"], 1.0000)

    row = build.read_prequalification(prequalification["id"])
    assert_prequalification_state(
        row,
        status="DRAFT",
        statistics_verification_status="PENDING",
        provisional_composite_score=None,
    )


def test_open_deficiency_count_ignores_a_suspended_row_that_still_holds_its_codes(
    build, api
):
    """The counter sums CONDITIONAL rows only, not populated code arrays.

    PRD Section 2.10: "Rows in any other status contribute zero even when their
    `deficiency_codes` array is still populated — a suspended, expired or rejected
    row stops counting the moment it leaves `CONDITIONAL`."

    Design: Corner/calculations/open_deficiency_count_ignores_a_suspended_row_that_still_holds_its_codes
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides={"emr": 1.01})
    conditional = scenario["prequalification"]
    assert_prequalification_state(
        conditional, status="CONDITIONAL", grade="B", deficiency_codes=["EMR"]
    )
    assert_score_equals(conditional["final_composite_score"], 77.89)
    assert_instant_equals(
        conditional["conditional_expires_at"], "2026-10-30T00:00:00Z"
    )
    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]), open_deficiency_count=1
    )

    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="LOST_TIME",
        description="Laceration with lost workdays",
    )
    assert incident["review_status"] == "OPEN"

    frozen = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(
        frozen, status="SUSPENDED", grade="B", deficiency_codes=["EMR"]
    )
    assert_instant_equals(frozen["conditional_expires_at"], "2026-10-30T00:00:00Z")

    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]),
        open_deficiency_count=0,
        incident_review_flag=True,
        open_severe_incident_count=1,
    )

    reread = validate_success(
        api.get_incident(incident["id"], scenario["manager_headers"])
    )
    assert reread["triggered_suspension_count"] == 1, (
        f"expected the report to record one frozen standing, got "
        f"{reread['triggered_suspension_count']}"
    )
    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, access_gate_status="LOCKED")


def _approved_standing_under(build, client_id, legal_name, scope, document_suffix):
    """One APPROVED 2026 standing scoring exactly 80.51 for the given client."""
    contractor = build.create_contractor(
        legal_name=legal_name, scope_of_work=[scope], hazard_profile=["GENERAL"]
    )
    build.insure(contractor["id"], ("GL", "WC"))
    prequalification = build.open_prequalification(contractor["id"], client_id)
    build.verified_statistic(
        prequalification["id"],
        contractor["id"],
        source_document_ref=f"OSHA300A-2025-{document_suffix}",
    )
    build.accept_required_programs(
        prequalification["id"], contractor["id"], client_id, ["GENERAL"]
    )
    build.submit_prequalification(prequalification["id"], contractor["id"])
    return build.grade_prequalification(prequalification["id"], client_id)


def test_audit_sampling_tie_break_selects_the_earliest_created_row(build, api):
    """Two rows tie at 80.51, so created_at ascending alone decides the draw.

    PRD Section 3.11: "The pool is ranked by `final_composite_score` ascending, so
    the weakest scores are audited first, with `created_at` ascending as the
    tie-break — never the identifier, which is random."

    Design: Corner/calculations/audit_sampling_tie_break_selects_the_earliest_created_row
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client(audit_sample_rate_pct=50)
    manager = build.manager_headers(client["id"])

    first = _approved_standing_under(
        build, client["id"], "Acme Mechanical", "MECHANICAL_TRADE", "A"
    )
    # The clock advances so the two rows carry genuinely different created_at
    # instants; only the composite score is allowed to tie.
    build.set_clock("2026-08-02T00:00:00Z")
    second = _approved_standing_under(
        build, client["id"], "Bolt Rigging", "SCAFFOLDING", "B"
    )

    for row in (first, second):
        assert_prequalification_state(row, status="APPROVED", grade="B")
        assert_score_equals(row["final_composite_score"], 80.51)
    assert first["created_at"] < second["created_at"], (
        "the fixture must order the two rows by created_at"
    )

    result = validate_success(api.run_audit_sampling(client["id"], {}, manager))
    assert result["selected_count"] == 1, (
        f"ceil(50/100 * 2) is 1 draw, got {result['selected_count']}"
    )
    assert result["selected_prequalification_ids"] == [first["id"]], (
        "the earlier created_at must win the score tie"
    )

    drawn = build.read_prequalification(first["id"])
    assert_prequalification_state(drawn, audit_state="SELECTED")
    assert_instant_equals(drawn["audit_selected_at"], "2026-08-02T00:00:00Z")

    passed_over = build.read_prequalification(second["id"])
    assert_prequalification_state(passed_over, audit_state="NOT_SELECTED")
    assert passed_over["audit_selected_at"] is None

    # A second run at the same clock draws the one remaining eligible row and
    # never re-draws a row already SELECTED.
    again = validate_success(api.run_audit_sampling(client["id"], {}, manager))
    assert again["selected_count"] == 1
    assert again["selected_prequalification_ids"] == [second["id"]]
    assert_prequalification_state(
        build.read_prequalification(second["id"]), audit_state="SELECTED"
    )
