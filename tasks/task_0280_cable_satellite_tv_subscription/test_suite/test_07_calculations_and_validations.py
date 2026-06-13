"""Calculation breadth (regional sports fee, visit fee, ETF tiers, combined cancel
statement) and validation-error breadth (visit window, promo conflicts, tier,
proration, duplicate cycle).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_field_technician_headers,
    create_package,
    create_technician,
    create_equipment_model,
    create_rsf_rule,
    create_promotion_offer,
    create_active_account,
    create_prospect_account,
    activate_first_subscription,
    assign_equipment,
    apply_promotion,
    advance_cycles,
    account_version,
    get_account,
    set_clock,
    schedule_and_dispatch_visit,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ─── Calculations ──────────────────────────────────────────────────────────
def test_regional_sports_fee_premier_surcharge_applied(api):
    """PRD §3.8: "Otherwise the fee is the rule's `base_fee_cents` plus, when the current package
    rank is at least the top rank of 3 (`PREMIER`), the rule's `premier_surcharge_cents`; below
    rank 3 no surcharge is added."

    Design: Corner/calculations/regional_sports_fee_premier_surcharge_applied
    """
    premier = create_package(tier_code="PREMIER", monthly_fee_cents=9000, rank=3, channel_count=200)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, _ = create_active_account(premier, service_state_code="CA")
    rsf = get_account(account["id"])["regional_sports_fee_cents"]
    assert rsf == 1300, f"PREMIER rsf expected 1300, got {rsf}"


def test_regional_sports_fee_no_rule_is_zero(api):
    """PRD §3.8: "The system finds the single active `RegionalSportsFeeRule` whose `state_code`
    matches the account's `service_state_code`; if no active rule matches, the regional sports
    fee is 0."

    Design: Corner/calculations/regional_sports_fee_no_rule_is_zero
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="WY")
    rsf = get_account(account["id"])["regional_sports_fee_cents"]
    assert rsf == 0, f"no-rule rsf expected 0, got {rsf}"


def test_service_visit_complete_charges_full_truck_roll(api):
    """PRD §3.8: "On completion, an `INSTALL` visit is waived and charges 0, while a `SERVICE`
    visit charges the standard truck-roll fee of 99 dollars (9,900 cents)."

    Design: Corner/calculations/service_visit_complete_charges_full_truck_roll
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="T1", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_and_dispatch_visit(
        account["id"], tech["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="SERVICE"
    )
    completed = validate_success(
        api.complete_service_visit(
            account["id"], visit["id"], {"outcome_note": "fixed"}, make_field_technician_headers(tech["id"])
        ),
        200,
    )
    assert completed["truck_roll_fee_cents"] == 9900


def test_etf_zero_when_month_to_month(api):
    """PRD §3.8: "The fee is 0 in two cases: when `contract_term_months` is 0 (month-to-month,
    no contract), or when `tenure_months` is greater than or equal to `contract_term_months`
    (the contract is already satisfied)."

    Design: Corner/calculations/etf_zero_when_month_to_month
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA", contract_term_months=0)
    validate_success(api.cancel_account(account["id"], CSA), 200)
    stmt = validate_success(
        api.issue_billing_statement(
            account["id"], {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    assert stmt["etf_charge_cents"] == 0


def test_etf_mid_tier_remaining_six(api):
    """PRD §3.8: "If the remaining months are at least 6 but fewer than 12, the fee is the mid
    amount of 150 dollars (15,000 cents)."
    PRD §3.8: "exactly 6 remaining months lands in the mid tier (15,000 cents)".

    Design: Corner/calculations/etf_mid_tier_remaining_six
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA", contract_term_months=12)
    advance_cycles(account["id"], 6)   # tenure -> 6, remaining 12-6 = 6
    validate_success(api.cancel_account(account["id"], CSA), 200)
    stmt = validate_success(
        api.issue_billing_statement(
            account["id"], {"cycle_index": 6, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    assert stmt["etf_charge_cents"] == 15000


# NOTE: test_cancel_cycle_statement_combines_prorated_recurring_and_one_time was
# DELETED. PRD §3.7 explicitly defines "the account's single current subscription"
# as "the one in `ACTIVE` or `DOWNGRADED` status", and §3.10 sources the statement
# package amount from "the current subscription's `base_fee_cents`". After the §3.3
# cancellation cascade transitions the subscription to `TERMINATED`, no ACTIVE/
# DOWNGRADED subscription remains, so a PRD-faithful implementer applying §3.7's
# definition yields package_charge_cents == 0 on the cancel-cycle statement. The
# PRD prose does not uniquely determine that the terminated subscription's base
# fee is re-billed (prorated) on that statement; it admits both package==0 and
# package==3000 readings. DELETE per STEP 1b (DEFAULT-VALUE / COMPUTED-FIELD
# silence at the PRD-prose level).


# ─── Validations ───────────────────────────────────────────────────────────
def test_visit_window_start_in_past_rejected(api):
    """PRD §3.9: "The window must be well-formed and in the future: `window_start` must be
    strictly earlier than `window_end`, and `window_start` must be later than the current clock
    time. A window where the start is not before the end, or whose start is in the past, is
    rejected with `ERR_INVALID_VISIT_WINDOW` (HTTP 422)."

    Design: Corner/validations/visit_window_start_in_past_rejected
    """
    set_clock("2026-06-10T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="T1", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    res = api.schedule_service_visit(
        account["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-01T09:00:00Z",
            "window_end": "2026-06-01T10:00:00Z",
            "technician_id": tech["id"],
        },
        CSA,
    )
    validate_error(res, "ERR_INVALID_VISIT_WINDOW", expected_status=422)


def test_apply_promo_while_active_rejected(api):
    """PRD §3.6: "Applying while a promotion is already `PROMO_ACTIVE` is rejected with
    `ERR_PROMO_ALREADY_ACTIVE` (HTTP 409), because at most one promotion application may be
    `ACTIVE` at a time."

    Design: Corner/validations/promo_apply_when_active_rejected
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    p1 = create_promotion_offer(code="P1", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.1, promo_months=6, requires_min_rank=2)
    p2 = create_promotion_offer(code="P2", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.2, promo_months=6, requires_min_rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], p1["id"])
    v2 = account_version(account["id"])
    res = api.apply_promotion(
        account["id"], {"promotion_offer_id": p2["id"], "expected_account_version": v2}, CSA
    )
    validate_error(res, "ERR_PROMO_ALREADY_ACTIVE", expected_status=409)


def test_winback_nonprotected_offer_rejected(api):
    """PRD §3.6: "Re-applying after rollback with a non-protected offer is rejected with
    `ERR_PROMO_NOT_WINBACK_ELIGIBLE` (HTTP 422)".

    Design: Corner/validations/winback_nonprotected_offer_rejected
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    offer = create_promotion_offer(
        code="NPROT", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.1, promo_months=1,
        requires_min_rank=2, rollback_protected=False,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], offer["id"])
    validate_success(api.advance_cycle(account["id"], ADMIN), 200)   # rollback (promo_months 1)
    v2 = account_version(account["id"])
    res = api.apply_promotion(
        account["id"], {"promotion_offer_id": offer["id"], "expected_account_version": v2}, CSA
    )
    validate_error(res, "ERR_PROMO_NOT_WINBACK_ELIGIBLE", expected_status=422)


def test_downgrade_same_tier_rejected(api):
    """PRD §3.4: "A target whose rank equals the current rank, or that is inactive, is rejected
    with `ERR_SAME_OR_INVALID_TIER` (HTTP 422)."

    Design: Corner/validations/downgrade_same_tier_rejected
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, sub = create_active_account(package, service_state_code="CA")
    v = account_version(account["id"])
    res = api.downgrade_subscription(
        account["id"], sub["id"], {"package_id": package["id"], "expected_account_version": v}, CSA
    )
    validate_error(res, "ERR_SAME_OR_INVALID_TIER", expected_status=422)


def test_prorated_statement_active_days_out_of_range_rejected(api):
    """PRD §3.10: "A `PRORATED` statement whose `active_days` falls outside the range 0 through
    `days_in_cycle` is rejected with `ERR_INVALID_PRORATION` (HTTP 422)."

    Design: Corner/validations/prorated_statement_active_days_out_of_range_rejected
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    res = api.issue_billing_statement(
        account["id"],
        {"cycle_index": 0, "proration_mode": "PRORATED", "days_in_cycle": 30, "active_days": 40},
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_PRORATION", expected_status=422)


def test_duplicate_statement_cycle_rejected(api):
    """PRD §3.10: "Issuing a second statement for a `cycle_index` that already has an `ISSUED`
    statement on the account is rejected with `ERR_DUPLICATE_STATEMENT_CYCLE` (HTTP 409)."

    Design: Corner/validations/duplicate_statement_cycle_rejected
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA")
    validate_success(
        api.issue_billing_statement(
            account["id"], {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    res = api.issue_billing_statement(
        account["id"], {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
    )
    validate_error(res, "ERR_DUPLICATE_STATEMENT_CYCLE", expected_status=409)
