"""Assessment disputes: the review cycle, the adjustment cascade, ledger conservation,
error precedence, and the cross-entity CERTIFIED precondition."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, new_bid, add_parcel, activate, new_fiscal_year, new_budget,
    add_line, propose, find_assessment,
    setup_single_parcel_certified, setup_dispute_under_review,
    make_property_owner_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]
BOARD = TEST_USERS["board_member_headers"]


def _file_dispute(api, ctx):
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    dispute = get_success_data(api.create_dispute(
        ctx["assessment"]["id"], {"claimed_value_cents": 60000000, "requested_amount_cents": 3000000,
                                  "reason": "over-assessed"}, owner))
    return dispute, owner


def test_dispute_review_cycle_returns_to_under_review(api):
    """PRD §3.5: "The owning PropertyOwner responds to such a request (INFO_REQUESTED →
    UNDER_REVIEW), and this review cycle may repeat between UNDER_REVIEW and INFO_REQUESTED
    any number of times."

    Design: Difficulty/non_linear_state_machine/dispute_info_request_review_cycle
    """
    ctx = setup_dispute_under_review()
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    d_id = ctx["dispute"]["id"]
    get_success_data(api.transition_dispute(d_id, {"action": "REQUEST_INFO"}, ADMIN))
    get_success_data(api.transition_dispute(d_id, {"action": "RESPOND"}, owner))
    get_success_data(api.transition_dispute(d_id, {"action": "REQUEST_INFO"}, ADMIN))
    final = validate_success(api.transition_dispute(d_id, {"action": "RESPOND"}, owner))
    assert final["status"] == "UNDER_REVIEW"


def test_dispute_request_info_then_respond_toggles_state(api):
    """PRD §3.5: "A DistrictAdministrator moves a submitted dispute into review
    (SUBMITTED → UNDER_REVIEW) and may request more information (UNDER_REVIEW →
    INFO_REQUESTED). The owning PropertyOwner responds to such a request (INFO_REQUESTED →
    UNDER_REVIEW)".

    Design: Difficulty/non_linear_state_machine/dispute_info_request_review_cycle
    """
    ctx = setup_dispute_under_review()
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    d_id = ctx["dispute"]["id"]
    requested = validate_success(api.transition_dispute(d_id, {"action": "REQUEST_INFO"}, ADMIN))
    assert requested["status"] == "INFO_REQUESTED"
    responded = validate_success(api.transition_dispute(d_id, {"action": "RESPOND"}, owner))
    assert responded["status"] == "UNDER_REVIEW"


def test_dispute_adjust_transitions_assessment_to_adjusted(api):
    """PRD §3.5: "First, the linked assessment transitions CERTIFIED → ADJUSTED and its
    certified_amount_cents is set to the resolved amount."

    Design: Difficulty/transitive_cascade/dispute_adjust_deep_refund_cascade
    """
    ctx = setup_dispute_under_review(paid_in_full=True)
    get_success_data(api.transition_dispute(
        ctx["dispute"]["id"], {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 3000000}, ADMIN))
    a = validate_success(api.get_assessment(ctx["assessment"]["id"], ADMIN))
    assert a["status"] == "ADJUSTED"
    assert a["certified_amount_cents"] == 3000000


def test_dispute_adjust_credits_account_and_reduces_levy(api):
    """PRD §3.5: "the child collection account's billed_amount_cents is re-synced to the new
    certified amount and its balance_due_cents recomputed; if the account has now been
    overpaid relative to the reduced principal it moves to CREDIT, the overpayment is
    recorded in credit_balance_cents, and a refund is recorded. Third, the fiscal year's
    total_certified_levy_cents and collected_to_date_cents are adjusted by the resulting
    deltas so the ledger stays exact."

    Design: Difficulty/transitive_cascade/dispute_adjust_deep_refund_cascade
    """
    ctx = setup_dispute_under_review(paid_in_full=True)
    get_success_data(api.transition_dispute(
        ctx["dispute"]["id"], {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 3000000}, ADMIN))
    account = validate_success(api.get_collection_account(ctx["account"]["id"], TEST_USERS["tax_collector_headers"]))
    assert account["status"] == "CREDIT"
    assert account["billed_amount_cents"] == 3000000
    fy = validate_success(api.get_fiscal_year(ctx["fy"]["id"], ADMIN))
    assert fy["total_certified_levy_cents"] == 3000000


def test_collected_cash_conserved_after_refund(api):
    """PRD §3.4: "On any payment the fiscal year's collected_to_date_cents accumulates the
    net cash (payments less refunds)".
    PRD §3.5: "the fiscal year's total_certified_levy_cents and collected_to_date_cents are
    adjusted by the resulting deltas so the ledger stays exact."

    Design: Difficulty/compensating_invariant/collected_cash_conserved_on_refund
    """
    ctx = setup_dispute_under_review(paid_in_full=True)
    get_success_data(api.transition_dispute(
        ctx["dispute"]["id"], {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 3000000}, ADMIN))
    fy = validate_success(api.get_fiscal_year(ctx["fy"]["id"], ADMIN))
    # 4025000 paid - 1025000 refunded = 3000000, no drift
    assert fy["collected_to_date_cents"] == 3000000


def test_refund_recorded_as_credit_balance(api):
    """PRD §3.5: "if the account has now been overpaid relative to the reduced principal it
    moves to CREDIT, the overpayment is recorded in credit_balance_cents, and a refund is
    recorded."

    Design: Difficulty/compensating_invariant/collected_cash_conserved_on_refund
    """
    ctx = setup_dispute_under_review(paid_in_full=True)
    get_success_data(api.transition_dispute(
        ctx["dispute"]["id"], {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 3000000}, ADMIN))
    account = validate_success(api.get_collection_account(ctx["account"]["id"], TEST_USERS["tax_collector_headers"]))
    assert account["credit_balance_cents"] == 1025000


def _build_denied_dispute(api):
    ctx = setup_single_parcel_certified()
    dispute, _ = _file_dispute(api, ctx)
    get_success_data(api.transition_dispute(dispute["id"], {"action": "REVIEW"}, ADMIN))
    get_success_data(api.transition_dispute(dispute["id"], {"action": "RESOLVE", "decision": "DENIED"}, ADMIN))
    ctx["dispute"] = dispute
    return ctx


def test_resolve_terminal_dispute_returns_state_error_over_fiscal(api):
    """PRD §3.5: "a transition against a dispute that has already reached a terminal outcome
    is rejected with ERR_DISPUTE_NOT_OPEN".
    PRD §2.6: state (5) is evaluated before fiscal constraints (10), so the closed-dispute
    check pre-empts the adjustment-bound check.

    Design: Difficulty/priority_pair_validation_conflict/dispute_resolve_state_beats_fiscal
    """
    ctx = _build_denied_dispute(api)
    resp = api.transition_dispute(
        ctx["dispute"]["id"],
        {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 9999999}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_OPEN.value)


def test_terminal_dispute_status_unchanged_after_rejected_resolve(api):
    """PRD §3.5: "a transition against a dispute that has already reached a terminal outcome
    is rejected with ERR_DISPUTE_NOT_OPEN".

    Design: Difficulty/priority_pair_validation_conflict/dispute_resolve_state_beats_fiscal
    """
    ctx = _build_denied_dispute(api)
    api.transition_dispute(
        ctx["dispute"]["id"],
        {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 9999999}, ADMIN)
    d = validate_success(api.get_dispute(ctx["dispute"]["id"], ADMIN))
    assert d["status"] == "RESOLVED_DENIED"


def _build_open_dispute_past_window(api):
    ctx = setup_single_parcel_certified()  # certified_at ~ 2027-06-01
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    get_success_data(api.create_dispute(
        ctx["assessment"]["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, owner))
    set_clock("2027-08-01T00:00:00Z")  # > 45 days after certification
    ctx["owner"] = owner
    return ctx


def test_second_dispute_returns_referential_error_over_temporal(api):
    """PRD §3.5: "At most one non-terminal dispute may exist per assessment; a second is
    rejected with ERR_DISPUTE_ALREADY_OPEN."
    PRD §2.6: referential uniqueness (7) is evaluated before temporal windows (8), so the
    already-open check pre-empts the window check.

    Design: Difficulty/priority_pair_validation_conflict/dispute_file_referential_beats_temporal
    """
    ctx = _build_open_dispute_past_window(api)
    resp = api.create_dispute(
        ctx["assessment"]["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, ctx["owner"])
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN.value)


def test_rejected_second_dispute_leaves_single_dispute(api):
    """PRD §3.5: "At most one non-terminal dispute may exist per assessment; a second is
    rejected with ERR_DISPUTE_ALREADY_OPEN."

    Design: Difficulty/priority_pair_validation_conflict/dispute_file_referential_beats_temporal
    """
    ctx = _build_open_dispute_past_window(api)
    api.create_dispute(
        ctx["assessment"]["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, ctx["owner"])
    listing = api.list_disputes(ctx["assessment"]["id"], ADMIN)
    assert len(listing.json()["data"]) == 1


def _build_estimated_only(api):
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="CE2 BID")
    parcel = add_parcel(bid["id"], apn="PX-1")
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=4025000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 4025000)
    propose(budget["id"])
    assessment = find_assessment(parcel["id"], fy["id"])
    return parcel, assessment


def test_dispute_on_estimated_assessment_rejected(api):
    """PRD §3.5: "only against their own parcel's assessment while that assessment is
    CERTIFIED — a dispute against an assessment in any other status is rejected with
    ERR_ASSESSMENT_NOT_CERTIFIED."

    Design: Difficulty/cross_entity_state_dependency/dispute_requires_certified_assessment
    """
    parcel, assessment = _build_estimated_only(api)
    owner = make_property_owner_headers(parcel["id"])
    resp = api.create_dispute(
        assessment["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, owner)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_CERTIFIED.value)


def test_estimated_assessment_unchanged_after_rejected_dispute(api):
    """PRD §3.5: "only against their own parcel's assessment while that assessment is
    CERTIFIED — a dispute against an assessment in any other status is rejected with
    ERR_ASSESSMENT_NOT_CERTIFIED."

    Design: Difficulty/cross_entity_state_dependency/dispute_requires_certified_assessment
    """
    parcel, assessment = _build_estimated_only(api)
    owner = make_property_owner_headers(parcel["id"])
    api.create_dispute(
        assessment["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, owner)
    a = validate_success(api.get_assessment(assessment["id"], ADMIN))
    assert a["status"] == "ESTIMATED"


def test_dispute_after_window_with_no_prior_rejected(api):
    """PRD §3.5: "Filing must fall within the dispute window: strictly within 45 days after
    the assessment's certified_at instant; once that window has passed the filing is
    rejected with ERR_DISPUTE_WINDOW_CLOSED."

    Design: Corner/validations/dispute_window_closed_clean_rejected
    """
    ctx = setup_single_parcel_certified()  # certified_at ~ 2027-06-01
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    set_clock("2027-08-01T00:00:00Z")  # > 45 days later, no prior dispute
    resp = api.create_dispute(
        ctx["assessment"]["id"], {"claimed_value_cents": 40000000, "requested_amount_cents": 3000000}, owner)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value)


def test_adjustment_exceeding_assessment_rejected(api):
    """PRD §3.5: "An adjustment (UNDER_REVIEW → RESOLVED_ADJUSTED) requires a
    resolved_amount_cents that lies between zero and the assessment's current
    certified_amount_cents inclusive; a value outside that range is rejected with
    ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT."

    Design: Corner/validations/adjustment_exceeds_assessment_clean_rejected
    """
    ctx = setup_dispute_under_review()
    resp = api.transition_dispute(
        ctx["dispute"]["id"],
        {"action": "RESOLVE", "decision": "ADJUSTED", "resolved_amount_cents": 9999999}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT.value)
