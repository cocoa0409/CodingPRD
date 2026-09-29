"""Two observable precedence pairs: safety over fiscal, referential over temporal."""
from test_helpers import (
    ApiErrorId,
    api_client,
    bootstrap_plan,
    create_applicant_with_vehicle,
    create_cancellation_payload,
    create_certification_payload,
    docket_complaint,
    file_market_rejection,
    make_compliance_examiner_headers,
    make_servicing_carrier_headers,
    read_application,
    read_assignment,
    read_carrier,
    read_plan_period,
    read_policy,
    record_deposit,
    set_clock,
    setup_policy_in_force,
    submit_application,
    validate_error,
    verify_mvr,
)

CANCELLATION_DATE = "2026-12-15T00:00:00Z"


def _application_short_on_declinations_and_short_on_money():
    """One documented declination where two are needed, and 10000 cents against 38939."""
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_market_rejection(application["id"], env["producer"]["id"],
                          rejecting_carrier_naic_code="11111",
                          document_reference="DEC-18-1")
    verify_mvr(application["id"], [])
    record_deposit(application["id"], env["producer"]["id"], 10000)
    application = read_application(application["id"])
    assert application["status"] == "SUBMITTED"
    assert application["distinct_rejection_count"] == 1
    assert application["required_deposit_cents"] == 38939
    return env, application


def _attempt_certification(application_id: str):
    return api_client.decide_certification(
        application_id, create_certification_payload("CERTIFY"),
        make_compliance_examiner_headers())


def test_certification_reports_the_documentation_gate_not_the_deposit_shortfall():
    """Both gates are broken, and the plan names the documentation one.

    The application has one declination where two are required and has paid 10000
    cents where 38939 is required, so two distinct gates would each refuse the
    certification. The documentation gate is business safety and the deposit gate
    is business fiscal, so the refusal names the declination shortfall and never
    mentions the money.

    PRD: "First, on an eligibility certification the documentation gates at
    priority 8 outrank the deposit gate at priority 12, so an applicant with an
    unverified motor-vehicle record or with too few documented declinations is
    refused before the plan looks at the money — the plan does not price an
    ineligible risk."
    Design: Difficulty/priority_pair_validation_conflict/certification_rejection_documentation_safety_outranks_deposit_shortfall_fiscal
    """
    _, application = _application_short_on_declinations_and_short_on_money()

    response = _attempt_certification(application["id"])

    error = validate_error(response, ApiErrorId.ERR_INSUFFICIENT_MARKET_REJECTIONS, 422)
    assert error["error_id"] != ApiErrorId.ERR_DEPOSIT_BELOW_REQUIRED
    assert error["error_id"] == "ERR_INSUFFICIENT_MARKET_REJECTIONS"


def test_the_refused_certification_leaves_the_application_and_the_period_untouched():
    """A refusal is total: no timestamp, no counter movement, no assignable unit.

    Because the decision never got past the documentation gate, the application is
    still submitted with no certification timestamp, its declination count and its
    deposit ledger read exactly as they did before, and the quota period has gained
    no assignable unit to apportion.

    PRD: "When all three pass, the application moves `SUBMITTED →
    CERTIFIED_AWAITING_ASSIGNMENT`, `certified_at` is stamped with the clock,
    `certified_by_user_id` records the examiner's `X-User-ID`, the premium estimate
    and `surcharge_points_estimated` are recomputed at a rating date equal to that
    clock, the containing period's `total_assignable_units` rises by 1, and —
    because the apportionment total just moved — every `ACTIVE` carrier's
    `quota_target_units` is recomputed."
    Design: Difficulty/priority_pair_validation_conflict/certification_rejection_documentation_safety_outranks_deposit_shortfall_fiscal
    """
    env, application = _application_short_on_declinations_and_short_on_money()

    response = _attempt_certification(application["id"])

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_MARKET_REJECTIONS, 422)
    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["certified_at"] is None
    assert unchanged["distinct_rejection_count"] == 1
    assert unchanged["deposit_paid_total_cents"] == 10000
    assert unchanged["required_deposit_cents"] == 38939
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 0


def _frozen_policy_ninety_one_days_into_its_term():
    """A policy with one open complaint, cancelled at a date past the sixty-day mark."""
    env = setup_policy_in_force(policy_number="AR-100005")
    assert env["policy"]["total_annual_charge_cents"] == 155754
    assert env["policy"]["premium_credited_cents"] == 38939
    docket_complaint(env["policy"]["id"], env["carrier"]["id"],
                     complaint_type="CLAIM_HANDLING_DELAY",
                     narrative="Servicing carrier has not returned the insured's calls.")
    frozen = read_policy(env["policy"]["id"])
    assert frozen["open_complaint_count"] == 1
    assert frozen["complaint_freeze_active"] is True
    set_clock(CANCELLATION_DATE)
    return env


def _attempt_restricted_reason_cancellation(env):
    return api_client.cancel_policy(
        env["policy"]["id"],
        create_cancellation_payload("VEHICLE_NOT_GARAGED_IN_STATE", CANCELLATION_DATE),
        make_servicing_carrier_headers(env["carrier"]["id"]))


def test_cancellation_reports_the_complaint_freeze_not_the_impermissible_reason():
    """Ninety-one days in with an open complaint, the freeze is what the plan names.

    A first-sixty-day reason code used 91 days into the term would be refused on its
    own, and the open complaint would refuse the cancellation on its own too. The
    freeze is business referential and the reason window is business temporal, so
    the refusal names the freeze.

    PRD: "Second, on a policy cancellation the complaint freeze at priority 9
    outranks the permitted-reason check at priority 10, so a policy with an open
    complaint reports `ERR_COMPLAINT_FREEZE_ACTIVE` even when the submitted reason
    code would also have been impermissible for the elapsed term position."
    Design: Difficulty/priority_pair_validation_conflict/cancellation_complaint_freeze_referential_outranks_reason_window_temporal
    """
    env = _frozen_policy_ninety_one_days_into_its_term()

    response = _attempt_restricted_reason_cancellation(env)

    error = validate_error(response, ApiErrorId.ERR_COMPLAINT_FREEZE_ACTIVE, 409)
    assert error["error_id"] != ApiErrorId.ERR_CANCEL_REASON_NOT_PERMITTED
    assert error["error_id"] == "ERR_COMPLAINT_FREEZE_ACTIVE"


def test_the_refused_cancellation_settles_nothing_on_the_frozen_policy():
    """The freeze protects the insured, so no premium is earned and no refund paid.

    Nothing about the money moves: the earned premium and the refund are both zero,
    no refund basis has been chosen, and the credited deposit still stands at 38939.
    The coverage axis is untouched, the assignment still carries the issued policy,
    and the servicing carrier keeps the risk in its headcount.

    PRD: "While the freeze is on, the plan refuses both adverse actions against that
    insured: cancellation and the service of a non-renewal notice, each with
    `ERR_COMPLAINT_FREEZE_ACTIVE` and HTTP 409."
    Design: Difficulty/priority_pair_validation_conflict/cancellation_complaint_freeze_referential_outranks_reason_window_temporal
    """
    env = _frozen_policy_ninety_one_days_into_its_term()

    response = _attempt_restricted_reason_cancellation(env)

    validate_error(response, ApiErrorId.ERR_COMPLAINT_FREEZE_ACTIVE, 409)
    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "IN_FORCE"
    assert policy["complaint_freeze_active"] is True
    assert policy["earned_premium_cents"] == 0
    assert policy["refund_paid_cents"] == 0
    assert policy["refund_basis"] is None
    assert policy["premium_credited_cents"] == 38939
    assert read_assignment(env["assignment"]["id"])["status"] == "POLICY_ISSUED"
    assert read_carrier(env["carrier"]["id"])["assigned_risk_count"] == 1
