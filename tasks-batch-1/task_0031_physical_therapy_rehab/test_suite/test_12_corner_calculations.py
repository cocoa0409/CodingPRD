"""Corner Coverage — calculations section.

CMS 8-minute rule (evaluation), MPPR single-unit edge, discharge outcome
midpoint, and SELF_PAY cap pinned at activation.
(The discharge zero-goals UNSUCCESSFUL boundary is owned by the boundary-precision
difficulty instance — its corner stub is excluded_because:.)
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_active_poc,
    setup_poc_with_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    record_initial_evaluation,
    record_discharge_assessment,
    create_therapist,
    create_patient,
    create_draft_poc,
    activate_poc,
    make_therapist_headers,
    TEST_USERS,
)


def test_evaluation_units_8_minute_rule_30_minutes_equals_2_units(api):
    """PRD §3.3: "from 23 through 37 inclusive it is 2"
    PRD §3.3: "On create, the system computes the `billable_units` field for the
    evaluation by applying CMS's eight-minute rule to `minutes_spent`"

    Design: Corner/calculations/evaluation_units_8_minute_rule_30_minutes_equals_2_units
    """
    set_clock("2026-06-01T00:00:00Z")
    th = create_therapist(license_state="CA")
    pt = create_patient(insurance_type="COMMERCIAL")
    poc = create_draft_poc(pt["id"], th["id"])
    ev = record_initial_evaluation(
        poc["id"], th["id"], performed_on="2026-06-01",
        functional_score=50, minutes_spent=30,
    )
    assert ev["billable_units"] == 2


def test_visit_billed_amount_single_unit_no_mppr_applied(api):
    """PRD §3.5: "When the visit has at most one `billable_unit`, `billed_cents` is
    simply the unit rate (or zero, if `billable_units` is zero)."
    PRD §3.5: "Each CPT code has a per-unit rate in cents — `CPT_97110_THER_EX` at
    3200"

    Design: Corner/calculations/visit_billed_amount_single_unit_no_mppr_applied
    """
    ctx = setup_poc_with_grant(
        insurance_type="MEDICARE", medicare_enrolled=True,
        total_units_granted=10,
    )
    v = schedule_visit(
        ctx["grant"]["id"], ctx["therapist"]["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T09:15:00Z",
        planned_minutes=15, cpt_code="CPT_97110_THER_EX",
    )
    complete_visit(v["id"], ctx["therapist"]["id"], actual_minutes=15)
    finalized = finalize_visit(v["id"], ctx["poc"]["id"])
    assert finalized["billable_units"] == 1
    assert finalized["billed_cents"] == 3200


def test_discharge_outcome_partial_at_50pct_goals_met(api):
    """PRD §3.8: "otherwise a ratio at least 0.40 yields `PARTIAL`; otherwise the
    outcome is `UNSUCCESSFUL`."

    Design: Corner/calculations/discharge_outcome_partial_at_50pct_goals_met
    """
    ctx = setup_active_poc(insurance_type="COMMERCIAL")
    da = record_discharge_assessment(
        ctx["poc"]["id"], ctx["therapist"]["id"],
        final_functional_score=55,
        goals_met_count=5,
        total_goals_count=10,
        assessed_on="2026-06-15",
    )
    assert da["discharge_outcome"] == "PARTIAL"


def test_capped_poc_limit_pinned_at_activation_self_pay(api):
    """PRD §2.7: "a `SELF_PAY` plan at one hundred thousand cents (one thousand
    dollars)"
    PRD §2.7: "the limit is denominated in integer cents on the field
    `capped_dollar_limit_cents`, and it is **pinned once** at the moment the plan
    moves out of draft."
    PRD §2.7: "A newly activated plan starts at `UNDER_CAP`."

    Design: Corner/calculations/capped_poc_limit_pinned_at_activation_self_pay
    """
    set_clock("2026-06-01T00:00:00Z")
    th = create_therapist(license_state="CA")
    pt = create_patient(insurance_type="SELF_PAY")
    poc = create_draft_poc(pt["id"], th["id"])
    record_initial_evaluation(poc["id"], th["id"], performed_on="2026-06-01")
    activated = activate_poc(poc["id"], th["id"])
    assert activated["capped_dollar_limit_cents"] == 100000
    assert activated["capped_status"] == "UNDER_CAP"
