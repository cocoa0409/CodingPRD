"""Reporting to the funder: the degenerate scope that must not divide by zero,
and the certification that waits on the residencies it summarises."""
from test_helpers import (
    ApiErrorId,
    FISCAL_OFFICER_USER_ID,
    PROGRAM_DIRECTOR_USER_ID,
    api_client,
    certify_funder_report,
    compile_funder_report,
    complete_residency,
    create_certify_payload,
    create_delivered_session,
    make_fiscal_officer_headers,
    open_funder_report,
    read_funder_report,
    read_residency,
    set_clock_to_default,
    setup_active_residency,
    setup_approved_residency,
    validate_error,
)


# ==========================================================================
# A scope that delivered nothing at all
# ==========================================================================
def _report_over_a_residency_that_delivered_nothing() -> dict:
    """An approved residency that never scheduled a session, and a DRAFT funder
    report whose scope is exactly that residency."""
    set_clock_to_default()
    scenario = setup_approved_residency(
        residency_overrides={"required_strands": ["CREATING"]}
    )
    scenario["report"] = open_funder_report(
        [scenario["residency"]["id"]],
        grant_code="CAT-2026-11",
        period_start="2026-09-01",
        period_end="2026-09-30",
        headcount_basis="UNDUPLICATED",
    )
    return scenario


def test_a_scope_with_no_delivery_serves_no_students_at_all(api):
    """PRD §3.9: "Within the report's scope, a residency's *delivered-in-period*
    sessions are those whose status is `DELIVERED` and whose `session_date` falls
    inside the closed interval from `period_start` to `period_end`."
    PRD §3.9: "A residency **qualifies** when it has at least one such session."
    PRD §3.9: "Under `UNDUPLICATED` it is the sum of `enrolled_student_count`
    over the *qualifying* residencies — each residency's roll counted exactly
    once, so a child who attends six sessions counts once."
    PRD §3.9: "For each qualifying residency, that served figure is multiplied by
    the host school's `frl_pct`, `ell_pct`, and `iep_pct` in turn and each product
    is rounded half up to a whole student; the per-residency results are then
    summed into `frl_students_reached`, `ell_students_reached`, and
    `iep_students_reached`."

    Design: Difficulty/boundary_precision_check/funder_compile_with_zero_students_served_yields_zero_cost_per_student
    """
    scenario = _report_over_a_residency_that_delivered_nothing()
    assert scenario["report"]["status"] == "DRAFT"
    assert scenario["residency"]["enrolled_student_count"] == 48, (
        "the residency carries a full roll that must still not be counted"
    )

    compiled = compile_funder_report(
        scenario["report"]["id"], compiler_user_id=PROGRAM_DIRECTOR_USER_ID
    )
    assert compiled["status"] == "COMPILED"
    assert compiled["sessions_delivered_total"] == 0
    assert compiled["students_served"] == 0, (
        "an unqualified residency contributes none of its roll, got "
        f"{compiled['students_served']}"
    )
    assert compiled["frl_students_reached"] == 0
    assert compiled["ell_students_reached"] == 0
    assert compiled["iep_students_reached"] == 0
    assert compiled["compiled_by_user_id"] == PROGRAM_DIRECTOR_USER_ID
    assert compiled["invalidated_reason"] is None


def test_cost_per_student_is_zero_rather_than_a_division_failure(api):
    """PRD §3.9: "`direct_cost_cents` is the sum of `total_cents` over payment
    vouchers that are `APPROVED`, whose `residency_id` is in the report's scope,
    and whose own `period_end` falls inside the report's closed reporting period."
    PRD §3.9: "The indirect rate is then chosen from a bracket keyed on **direct
    cost alone**, never on total spend: 15 percent (a factor of 0.15) when direct
    cost is below 500,000 cents, 12 percent (0.12) when it is below 1,500,000
    cents, and 10 percent (0.10) at or above that."
    PRD §3.9: "And `cost_per_student_cents` is total spend divided by
    `students_served`, rounded half up — defined as zero when `students_served` is
    zero, so an empty scope yields zeros rather than a division failure."

    Design: Difficulty/boundary_precision_check/funder_compile_with_zero_students_served_yields_zero_cost_per_student
    """
    scenario = _report_over_a_residency_that_delivered_nothing()
    compile_funder_report(
        scenario["report"]["id"], compiler_user_id=PROGRAM_DIRECTOR_USER_ID
    )

    report = read_funder_report(scenario["report"]["id"])
    assert report["direct_cost_cents"] == 0, (
        f"no approved voucher exists in the scope, got {report['direct_cost_cents']}"
    )
    assert report["indirect_cost_cents"] == 0, (
        "fifteen percent of nothing is nothing, got "
        f"{report['indirect_cost_cents']}"
    )
    assert report["total_spend_cents"] == 0
    assert report["students_served"] == 0
    assert report["cost_per_student_cents"] == 0, (
        "a zero denominator is defined to yield zero, got "
        f"{report['cost_per_student_cents']}"
    )


# ==========================================================================
# Certification waits on every residency in the scope
# ==========================================================================
def _compiled_report_over_a_live_residency() -> dict:
    """One delivered session inside the reporting period, summarised by a
    COMPILED report, while the residency itself is still `ACTIVE`."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=20.5,
        materials_spend_cents=3000,
    )
    report = open_funder_report(
        [scenario["residency"]["id"]],
        grant_code="CAT-2026-09",
        period_start="2026-09-01",
        period_end="2026-09-30",
        headcount_basis="UNDUPLICATED",
    )
    scenario["report"] = compile_funder_report(
        report["id"], compiler_user_id=PROGRAM_DIRECTOR_USER_ID
    )
    return scenario


def test_certifying_a_report_whose_residency_is_still_active_is_refused(api):
    """PRD §3.9: "Certification is the `FiscalOfficer`'s act and the last word on
    a report."
    PRD §3.9: "Three preconditions apply: every residency in
    `scope_residency_ids` must have a `status` of `COMPLETED` or `CLOSED`, or the
    request is refused with `ERR_RESIDENCY_NOT_FINALIZED`; the supplied
    `certifier_user_id` must differ from the report's `compiled_by_user_id`, or
    the refusal is `ERR_SEGREGATION_OF_DUTIES`; and `invalidated_reason` must be
    null, so a stale snapshot cannot be certified — that too is refused with
    `ERR_RESIDENCY_NOT_FINALIZED`."
    PRD §3.9: "Under `UNDUPLICATED` it is the sum of `enrolled_student_count`
    over the *qualifying* residencies — each residency's roll counted exactly
    once, so a child who attends six sessions counts once."

    Design: Difficulty/cross_entity_state_dependency/funder_certification_gated_by_residency_finalization
    """
    scenario = _compiled_report_over_a_live_residency()
    report = scenario["report"]
    assert report["status"] == "COMPILED"
    assert report["students_served"] == 48, (
        "the whole roll counts once under the unduplicated basis, got "
        f"{report['students_served']}"
    )
    assert read_residency(scenario["residency"]["id"])["status"] == "ACTIVE"

    res = api_client.certify_funder_report(
        report["id"],
        create_certify_payload(
            FISCAL_OFFICER_USER_ID, "Figures reviewed and attested."
        ),
        make_fiscal_officer_headers(FISCAL_OFFICER_USER_ID),
    )
    validate_error(
        res, ApiErrorId.ERR_RESIDENCY_NOT_FINALIZED.value, expected_status=409
    )

    after = read_funder_report(report["id"])
    assert after["status"] == "COMPILED", (
        f"the refusal must leave the report compiled, got {after['status']}"
    )
    assert after["certified_by_user_id"] is None
    assert after["attestation_text"] is None


def test_completing_the_residency_unlocks_the_same_certification(api):
    """PRD §3.4: "Completion runs a forfeiture sweep that writes off everything
    still owed: `sessions_forfeited_count` gains the sum of
    `sessions_unscheduled_count` and `makeup_credits_outstanding`; every
    unconsumed make-up credit is closed out by setting `makeup_consumed` to true
    on the cancelled origin session that issued it and driving
    `makeup_credits_outstanding` to zero; and `sessions_unscheduled_count` is set
    to zero."
    PRD §3.9: "Certification writes the supplied certifier into
    `certified_by_user_id` and persists `attestation_text`."
    PRD §3.9: "For each qualifying residency, that served figure is multiplied by
    the host school's `frl_pct`, `ell_pct`, and `iep_pct` in turn and each product
    is rounded half up to a whole student; the per-residency results are then
    summed into `frl_students_reached`, `ell_students_reached`, and
    `iep_students_reached`."
    PRD §3.9: "`CERTIFIED` is terminal."

    Design: Difficulty/cross_entity_state_dependency/funder_certification_gated_by_residency_finalization
    """
    scenario = _compiled_report_over_a_live_residency()
    report_id = scenario["report"]["id"]
    validate_error(
        api_client.certify_funder_report(
            report_id,
            create_certify_payload(
                FISCAL_OFFICER_USER_ID, "Figures reviewed and attested."
            ),
            make_fiscal_officer_headers(FISCAL_OFFICER_USER_ID),
        ),
        ApiErrorId.ERR_RESIDENCY_NOT_FINALIZED.value,
        expected_status=409,
    )

    residency = complete_residency(scenario["residency"]["id"])
    assert residency["status"] == "COMPLETED"
    assert residency["sessions_unscheduled_count"] == 0
    assert residency["sessions_forfeited_count"] == 9, (
        "the nine never-scheduled units are written off, got "
        f"{residency['sessions_forfeited_count']}"
    )

    certified = certify_funder_report(
        report_id,
        certifier_user_id=FISCAL_OFFICER_USER_ID,
        attestation_text="Figures reviewed and attested.",
    )
    assert certified["status"] == "CERTIFIED", (
        "the same request now succeeds on a finalized scope, got "
        f"{certified['status']}"
    )
    assert certified["certified_by_user_id"] == FISCAL_OFFICER_USER_ID
    assert certified["attestation_text"] == "Figures reviewed and attested."
    assert certified["sessions_delivered_total"] == 1
    assert certified["students_served"] == 48
    assert certified["frl_students_reached"] == 30, (
        f"expected 48 at 0.62 rounded half up, got {certified['frl_students_reached']}"
    )
    assert certified["ell_students_reached"] == 13
    assert certified["iep_students_reached"] == 7
