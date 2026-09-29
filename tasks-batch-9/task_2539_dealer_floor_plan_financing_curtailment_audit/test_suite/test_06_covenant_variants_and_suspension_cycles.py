"""Covenant filings: the two coverage ratios, the second-breach suspension and the cycle back out."""
from test_helpers import (
    CRM,
    CRM2,
    ApiErrorId,
    api_client,
    assert_covenant_test,
    assert_dscr_precision,
    dscr_as_string,
    file_covenant_test,
    floor_unit,
    read_credit_line,
    read_dealer,
    read_unit,
    reconcile_audit,
    record_observation,
    reinstate_credit_line_payload,
    schedule_audit,
    set_clock,
    setup_active_line,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

FAILING_FILING = {
    "reported_tangible_net_worth_cents": 60000000,
    "reported_ebitda_cents": 1000000,
    "reported_interest_expense_cents": 400000,
    "reported_curtailment_paid_cents": 560000,
    "reported_unrestricted_cash_cents": 2000000,
}


def _file(dealer_id, period_end_date):
    """File the one certificate whose two variants straddle the two thresholds."""
    return file_covenant_test(
        dealer_id,
        period_end_date,
        FAILING_FILING["reported_tangible_net_worth_cents"],
        FAILING_FILING["reported_ebitda_cents"],
        FAILING_FILING["reported_interest_expense_cents"],
        FAILING_FILING["reported_curtailment_paid_cents"],
        FAILING_FILING["reported_unrestricted_cash_cents"],
    )


def _reinstate(credit_line_id):
    """Raw reinstatement call, so a refusal can be inspected."""
    return api_client.reinstate_credit_line(
        credit_line_id, CRM2, reinstate_credit_line_payload("COVENANT_CURE_PLAN")
    )


def test_one_filing_breaches_the_covenant_while_clearing_the_reinstatement_bar():
    """The lender-standard ratio is 1.0417 and fails; the dealer-adjusted ratio is 1.4583.

    PRD: "The two must not be conflated, because a single filing can simultaneously breach the covenant and satisfy the reinstatement test — with EBITDA of 1,000,000 cents against interest of 400,000 and curtailment paid of 560,000, the lender-standard ratio is 1.0417 and the filing `FAIL`s with `CASH_FLOW`, while the dealer-adjusted ratio on the same numbers is 1.4583 and clears the 1.4000 reinstatement bar."

    Design: Difficulty/dual_variant_calc/covenant_dscr_lender_standard_fails_while_dealer_adjusted_permits_reinstatement
    """
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Rainier Auto Group Inc", "state_code": "WA"}
    )
    dealer_id = ctx["dealer"]["id"]

    filing = _file(dealer_id, "2026-06-30")
    assert_covenant_test(filing)
    assert filing["required_tangible_net_worth_cents"] == 50000000
    assert_dscr_precision(filing["dscr_lender_standard"], "dscr_lender_standard")
    assert_dscr_precision(filing["dscr_dealer_adjusted"], "dscr_dealer_adjusted")
    assert dscr_as_string(filing["dscr_lender_standard"]) == "1.0417"
    assert dscr_as_string(filing["dscr_dealer_adjusted"]) == "1.4583"
    assert filing["result"] == "FAIL"
    assert filing["failure_reason_codes"] == ["CASH_FLOW"]
    assert filing["trailing_sot_incident_count"] == 0
    assert filing["submitted_by_user_id"] == CRM["X-User-ID"]

    dealer = read_dealer(dealer_id)
    assert dealer["last_covenant_result"] == "FAIL"
    assert dealer["covenant_breach_count"] == 1
    assert dealer["risk_score"] == 80
    assert dealer["risk_rating"] == "B"
    assert dealer["audit_frequency_days"] == 90
    assert dealer["status"] == "ACTIVE"
    assert read_credit_line(ctx["credit_line"]["id"])["status"] == "ACTIVE"


def test_the_second_failing_period_suspends_the_facility_and_the_dealership():
    """One failure suspends nothing; the second one does, on identical ratios.

    PRD: "A single `FAIL` suspends nothing; two do, and they need not be consecutive periods."

    Design: Difficulty/dual_variant_calc/covenant_dscr_lender_standard_fails_while_dealer_adjusted_permits_reinstatement
    """
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Rainier Auto Group Inc", "state_code": "WA"}
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    _file(dealer_id, "2026-06-30")
    assert read_credit_line(line_id)["status"] == "ACTIVE"

    second = _file(dealer_id, "2026-09-30")
    assert dscr_as_string(second["dscr_lender_standard"]) == "1.0417"
    assert dscr_as_string(second["dscr_dealer_adjusted"]) == "1.4583"
    assert second["result"] == "FAIL"

    line = read_credit_line(line_id)
    assert line["status"] == "SUSPENDED"
    assert line["suspension_reason_code"] == "COVENANT_BREACH_LIMIT"
    dealer = read_dealer(dealer_id)
    assert dealer["status"] == "SUSPENDED"
    assert dealer["covenant_breach_count"] == 2


def test_reinstatement_is_decided_on_the_add_back_ratio_of_a_failed_filing():
    """1.4583 clears the 1.4000 bar, so a breached line comes back and the tally resets.

    PRD: "A line whose covenant test `FAIL`ed on the lender-standard reading can therefore still be reinstated."

    PRD: "On success the line moves `SUSPENDED → ACTIVE` with `suspension_reason_code` cleared to null, the dealership moves `SUSPENDED → ACTIVE`, and its `covenant_breach_count` is reset to 0 — the count starts fresh, so the next suspension again requires two failures."

    Design: Difficulty/dual_variant_calc/covenant_dscr_lender_standard_fails_while_dealer_adjusted_permits_reinstatement
    """
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Rainier Auto Group Inc", "state_code": "WA"}
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    _file(dealer_id, "2026-06-30")
    _file(dealer_id, "2026-09-30")
    assert read_credit_line(line_id)["status"] == "SUSPENDED"

    reinstated = validate_success(_reinstate(line_id))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason_code"] is None

    dealer = read_dealer(dealer_id)
    assert dealer["status"] == "ACTIVE"
    assert dealer["covenant_breach_count"] == 0
    assert dealer["last_covenant_result"] == "FAIL"


def _large_unit_with_a_booked_audit():
    """A 20,000,000 cent floored unit and a scheduled count ready to find it missing."""
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Chinook Cycle Motors LLC", "state_code": "ID"}
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    unit = floor_unit(
        dealer_id,
        line_id,
        "CYCLEUNIT0000010",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=20000000,
        document_reference="MSO-0008",
        disbursement_reference="WIRE-0008",
        invoice_amount_cents=20000000,
        odometer_miles=11,
    )["unit"]
    audit = schedule_audit(dealer_id, "2026-08-10", "2026-08-12")
    return {
        "dealer_id": dealer_id,
        "line_id": line_id,
        "unit": unit,
        "audit_id": audit["id"],
    }


def _drive_the_full_cycle(ctx):
    """Covenant suspension, reinstatement, then an out-of-trust finding on the same line."""
    _file(ctx["dealer_id"], "2026-06-30")
    after_first = read_credit_line(ctx["line_id"])
    _file(ctx["dealer_id"], "2026-09-30")
    after_second = read_credit_line(ctx["line_id"])
    validate_success(_reinstate(ctx["line_id"]))
    after_reinstate = read_credit_line(ctx["line_id"])
    set_clock("2026-08-10T00:00:00Z")
    start_audit(ctx["audit_id"])
    record_observation(ctx["audit_id"], ctx["unit"]["id"], "MISSING", False)
    signed = reconcile_audit(
        ctx["audit_id"], notes="Unit absent from lot and no payoff received"
    )
    return {
        "after_first": after_first,
        "after_second": after_second,
        "after_reinstate": after_reinstate,
        "audit": signed,
    }


def test_the_line_re_enters_suspension_under_a_different_reason_code():
    """One facility suspends for covenants, returns to ACTIVE, then suspends for exposure.

    PRD: "Because the whole cycle can repeat, both status dimensions are genuinely cyclic."

    PRD: "The assessment starts from a perfect 100 and deducts points for the three conditions the lender considers predictive: 15 points for each out-of-trust incident of that dealer currently in `OPEN`, 10 points for each of the dealer's units currently sitting in `DELINQUENT_CURTAILMENT`, and a flat 20 points when the dealer's most recent covenant test resulted in `FAIL`."

    Design: Difficulty/non_linear_state_machine/credit_line_reenters_suspended_twice_from_two_different_causes
    """
    ctx = _large_unit_with_a_booked_audit()
    stages = _drive_the_full_cycle(ctx)

    assert stages["after_first"]["status"] == "ACTIVE"
    assert stages["after_second"]["status"] == "SUSPENDED"
    assert stages["after_second"]["suspension_reason_code"] == "COVENANT_BREACH_LIMIT"
    assert stages["after_reinstate"]["status"] == "ACTIVE"
    assert stages["after_reinstate"]["suspension_reason_code"] is None

    line = read_credit_line(ctx["line_id"])
    assert line["status"] == "SUSPENDED"
    assert line["suspension_reason_code"] == "SOT_EXPOSURE_THRESHOLD"

    dealer = read_dealer(ctx["dealer_id"])
    assert dealer["status"] == "SUSPENDED"
    assert dealer["open_sot_incident_count"] == 1
    assert dealer["open_sot_exposure_cents"] == 20000000
    assert dealer["risk_score"] == 65
    assert dealer["risk_rating"] == "C"
    assert dealer["audit_frequency_days"] == 45
    assert str(dealer["next_audit_due_at"]).startswith("2026-09-24T00:00:00")

    assert read_unit(ctx["unit"]["id"])["funding_status"] == "SOT_OPEN"
    assert stages["audit"]["status"] == "RECONCILED_EXCEPTIONS"
    assert stages["audit"]["sot_exposure_cents"] == 20000000


def test_the_second_suspension_is_not_reversible_while_the_incident_stays_open():
    """The same reinstatement that worked for the covenant breach is refused for exposure.

    PRD: "Three substantive conditions must then all hold, and any of them failing yields `ERR_REINSTATEMENT_CRITERIA_NOT_MET`: the dealership must have no out-of-trust incident in `OPEN` and therefore `open_sot_exposure_cents` of 0; its `delinquent_unit_count` must be 0; and the dealership's most recent covenant test — the one with the greatest `period_end_date`, breaking a tie on the greatest `created_at` — must have `dscr_dealer_adjusted` at or above 1.4000."

    Design: Difficulty/non_linear_state_machine/credit_line_reenters_suspended_twice_from_two_different_causes
    """
    ctx = _large_unit_with_a_booked_audit()
    _drive_the_full_cycle(ctx)

    incidents, meta = validate_paginated(
        api_client.list_out_of_trust_incidents(
            CRM, params={"dealer_id": ctx["dealer_id"], "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1
    assert incidents[0]["exposure_cents"] == 20000000

    validate_error(
        _reinstate(ctx["line_id"]),
        ApiErrorId.ERR_REINSTATEMENT_CRITERIA_NOT_MET,
        422,
    )
    line = read_credit_line(ctx["line_id"])
    assert line["status"] == "SUSPENDED"
    assert line["suspension_reason_code"] == "SOT_EXPOSURE_THRESHOLD"
    assert read_dealer(ctx["dealer_id"])["status"] == "SUSPENDED"
