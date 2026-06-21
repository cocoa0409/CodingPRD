"""Corner breadth tests for calculations (surcharge, under-cap credit, no-show)
and standalone validations (duplicate email, swap target, work-share opt-in,
pagination bounds).

Covers corner sections: calculations, validations.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_open_season, setup_confirmed_subscription, setup_confirmed_working_share,
    register_member, set_clock, confirm_subscription, box_for_week,
    schedule_shift, make_member_headers,
    create_subscription_payload, create_work_share_shift_payload,
    create_vacation_hold_payload, create_member_payload,
    ApiErrorId, TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]


# ─── calculations ────────────────────────────────────────────────────────────

def test_home_delivery_surcharge_charged_full_season(api):
    """PRD §3.3: "If the assigned site is a `HOME_DELIVERY` zone, a `CHARGE_SURCHARGE` ledger entry is also posted, equal to the site's `delivery_surcharge_cents` multiplied by the season's `week_count`."

    Design: Corner/calculations/home_delivery_surcharge_charged_full_season
    """
    base = setup_open_season(week_count=10, total_share_capacity=50,
                             site_kind="HOME_DELIVERY", delivery_surcharge_cents=500,
                             base_price_cents=50000, signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    confirmed = confirm_subscription(base["season"]["id"], sub["id"])
    # 50000 season + (500 × 10) surcharge = 55000.
    assert confirmed["outstanding_balance_cents"] == 55000, (
        f"balance expected 55000 (50000 + 5000 surcharge), "
        f"got {confirmed['outstanding_balance_cents']}")


def test_workshare_credit_under_cap_full_hours(api):
    """PRD §3.9: "The credit is computed against a fixed hourly rate of 1500 cents per hour, subject to a daily cap of 6 creditable hours per calendar date."
    PRD §3.9: "Thus a shift whose hours fit entirely under the remaining daily room is credited in full".

    Design: Corner/calculations/workshare_credit_under_cap_full_hours
    """
    ctx = setup_confirmed_working_share(tier="BASELINE", base_price_cents=30000,
                                        share_size="SMALL", items_per_box=5, week_count=10)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift = schedule_shift(sub_id, mh, "2026-08-10T09:00:00Z", 3)
    done = validate_success(api_client.complete_work_share_shift(shift["id"], FM), 200)
    # 3h under the 6h cap → 3 × 1500 = 4500.
    assert done["credit_earned_cents"] == 4500, (
        f"credit expected 4500, got {done['credit_earned_cents']}")
    member = validate_success(api_client.get_member(ctx["member"]["id"], FM), 200)
    assert member["wallet_credit_cents"] == 4500


def test_no_show_shift_earns_zero_credit(api):
    """PRD §3.9: "Marking a no-show moves the shift from `SCHEDULED` to `NO_SHOW`; no credit accrues, `credit_earned_cents` stays 0, and no ledger entry is posted."

    Design: Corner/calculations/no_show_shift_earns_zero_credit
    """
    ctx = setup_confirmed_working_share(tier="BASELINE", base_price_cents=30000,
                                        share_size="SMALL", items_per_box=5, week_count=10)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift = schedule_shift(sub_id, mh, "2026-08-11T09:00:00Z", 5)
    done = validate_success(api_client.mark_no_show_work_share_shift(shift["id"], FM), 200)
    assert done["status"] == "NO_SHOW"
    assert done["credit_earned_cents"] == 0
    member = validate_success(api_client.get_member(ctx["member"]["id"], FM), 200)
    assert member["wallet_credit_cents"] == 0


# ─── validations ─────────────────────────────────────────────────────────────

def test_duplicate_member_email_case_insensitive_rejected(api):
    """PRD §3.2: "The email must be unique on a case-insensitive basis; registering an email that already exists (ignoring letter case) is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/validations/duplicate_member_email_rejected
    """
    get_success_data(api_client.create_member(
        {"email": "dup@example.com", "full_name": "Dup One", "sliding_scale_tier": "BASELINE"}))
    res = api_client.create_member(
        {"email": "DUP@example.com", "full_name": "Dup Two", "sliding_scale_tier": "BASELINE"})
    validate_error(res, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_swap_target_earlier_week_rejected(api):
    """PRD §3.7: "A supplied swap target must satisfy three conditions — it must belong to the same subscription, it must have a `week_index` strictly greater than the held box's `week_index`, and it must itself be `SCHEDULED`; a swap target failing any of these is rejected with `ERR_INVALID_SWAP_TARGET` (HTTP 422)."

    Design: Corner/validations/invalid_swap_target_earlier_week_rejected
    """
    # Clock strictly before the held box's delivery date (week 5 delivers
    # 2026-07-29 under default first_delivery_date 2026-07-01) so the hold-window
    # check (priority 8) passes and the swap-target check (priority 9) is reached.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=10, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_w5 = box_for_week(sub_id, mh, 5)
    box_w2 = box_for_week(sub_id, mh, 2)  # earlier than week 5
    res = api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w5["id"], swap_target_box_id=box_w2["id"]),
        mh)
    validate_error(res, ApiErrorId.ERR_INVALID_SWAP_TARGET.value)


def test_workshare_on_non_optin_subscription_rejected(api):
    """PRD §3.9: "Both scheduling and completing a shift require the subscription's `working_share_opt_in` to be true; an attempt against a subscription that did not opt in is rejected with `ERR_NOT_WORKING_SHARE` (HTTP 409)."

    Design: Corner/validations/workshare_on_non_optin_subscription_rejected
    """
    # working_share_opt_in defaults to false.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=10, signup_close_date="2026-12-25T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    res = api_client.create_work_share_shift(
        sub_id, create_work_share_shift_payload("2026-08-12T09:00:00Z", 2), mh)
    validate_error(res, ApiErrorId.ERR_NOT_WORKING_SHARE.value)


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A request with `limit` below 1 or above 100, or with a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422)."

    Design: Corner/validations/pagination_limit_over_max_rejected
    """
    res = api_client.list_seasons(FM, params={"limit": 101})
    validate_error(res, ApiErrorId.ERR_VALIDATION_PAGINATION.value)
