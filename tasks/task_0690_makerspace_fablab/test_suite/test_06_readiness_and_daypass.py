"""Readiness-gate boundary for unsupervised access, the rolling day-pass-count
threshold, and the wallet-funds guard on confirm.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_tier,
    create_active_member,
    create_active_member_on_tier,
    create_certification_for,
    create_machine,
    create_held_reservation,
    register_member,
    make_member_headers,
)

PRO_TIER = {
    "code": "PRO", "name": "Pro", "billing_mode": "MONTHLY", "monthly_fee_cents": 0,
    "discount_bps": 2000, "prepaid_machine_minutes": 0, "locker_free_liters": 100,
    "unsupervised_allowed": True,
}
LASER_MACHINE = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}
DAYPASS_TIER = {
    "code": "DAYPASS", "name": "Day Pass", "billing_mode": "DAYPASS",
    "daypass_fee_cents": 2500, "discount_bps": 0, "prepaid_machine_minutes": 0,
    "locker_free_liters": 0, "unsupervised_allowed": False,
}
MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}


# ===========================================================================
# boundary_precision_check / readiness_gate_exactly_080_allows_unsupervised
# ===========================================================================
def test_readiness_score_exactly_080(api):
    """PRD §3.4: "The first contributes 0.5 when the certification's `status` is
    `ACTIVE` and 0 otherwise. The second contributes 0.2 when `orientation_complete`
    is true and 0 otherwise. The third is 0.3 multiplied by the supervised ratio,
    where the supervised ratio is `supervised_minutes` divided by
    `required_supervised_minutes`, capped at 1 ... The three components are added and
    the total is rounded to four decimal places."

    ACTIVE (0.5) + orientation (0.2) + 0.3*(60/180=0.3333..)=0.1 -> readiness 0.8.

    Design: Difficulty/boundary_precision_check/readiness_gate_exactly_080_allows_unsupervised
    """
    member = create_active_member(tier_overrides=PRO_TIER, topup_cents=20000)
    cert = create_certification_for(
        member["id"], "LASER", supervised_minutes=60, required_supervised_minutes=180
    )
    assert cert["readiness_score"] == 0.8, cert["readiness_score"]


def test_unsupervised_confirm_passes_at_readiness_080(api):
    """PRD §3.6: "if the `supervision_mode` is `UNSUPERVISED`, the member's tier has
    `unsupervised_allowed` true and that certification's `readiness_score` is at
    least 0.8, or else `ERR_READINESS_NOT_MET` (HTTP 409)."
    PRD §3.4: "A certification is ready for unsupervised work when its
    `readiness_score` is at least 0.8."

    A readiness of exactly 0.8 satisfies the >= 0.8 gate, so the UNSUPERVISED confirm
    succeeds (occupancy CONFIRMED).

    Design: Difficulty/boundary_precision_check/readiness_gate_exactly_080_allows_unsupervised
    """
    member = create_active_member(tier_overrides=PRO_TIER, topup_cents=20000)
    machine = create_machine(**LASER_MACHINE)
    cert = create_certification_for(
        member["id"], "LASER", supervised_minutes=60, required_supervised_minutes=180
    )
    res = create_held_reservation(
        member, machine, cert, "2026-04-25T10:00:00Z", "2026-04-25T11:00:00Z",
        supervision_mode="UNSUPERVISED",
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    confirmed = validate_success(api.confirm_reservation(res["id"], v, mh))
    assert confirmed["occupancy_status"] == "CONFIRMED", confirmed["occupancy_status"]


# ===========================================================================
# boundary_precision_check / daypass_window_third_allowed_fourth_blocked
# ===========================================================================
def test_third_daypass_allowed_count_three(api):
    """PRD §3.3: "The space caps casual use at three day-passes within that window; a
    purchase that would be the fourth is blocked with `ERR_CONVERT_TO_MONTHLY` (HTTP
    409) ... The boundary is inclusive of the three already used: the first, second,
    and third are allowed; the fourth within the window is refused."
    PRD §3.3: "Each purchase increments `daypass_count_window`."

    The third day-pass succeeds and leaves daypass_count_window == 3.

    Design: Difficulty/boundary_precision_check/daypass_window_third_allowed_fourth_blocked
    """
    tier = create_tier(**DAYPASS_TIER)
    member = register_member(tier["id"])
    mh = make_member_headers(member["id"])
    validate_success(api.sign_waiver(member["id"], mh))
    validate_success(api.topup(member["id"], 20000, mh))
    validate_success(api.buy_daypass(member["id"], mh))
    validate_success(api.buy_daypass(member["id"], mh))
    third = validate_success(api.buy_daypass(member["id"], mh))
    assert third["daypass_count_window"] == 3, third["daypass_count_window"]


def test_fourth_daypass_blocked_convert_to_monthly(api):
    """PRD §3.3: "a purchase that would be the fourth is blocked with
    `ERR_CONVERT_TO_MONTHLY` (HTTP 409), nudging the member toward a monthly
    subscription. The boundary is inclusive of the three already used: the first,
    second, and third are allowed; the fourth within the window is refused."

    The fourth day-pass in the rolling window is rejected.

    Design: Difficulty/boundary_precision_check/daypass_window_third_allowed_fourth_blocked
    """
    tier = create_tier(**DAYPASS_TIER)
    member = register_member(tier["id"])
    mh = make_member_headers(member["id"])
    validate_success(api.sign_waiver(member["id"], mh))
    validate_success(api.topup(member["id"], 20000, mh))
    for _ in range(3):
        validate_success(api.buy_daypass(member["id"], mh))
    validate_error(api.buy_daypass(member["id"], mh), ApiErrorId.ERR_CONVERT_TO_MONTHLY.value)


# ===========================================================================
# Corner / calculations / certification_readiness_below_gate_blocks_unsupervised
# ===========================================================================
def test_readiness_below_gate_blocks_unsupervised(api):
    """PRD §3.4: "The first contributes 0.5 when the certification's `status` is
    `ACTIVE` and 0 otherwise. The second contributes 0.2 when `orientation_complete`
    is true and 0 otherwise. The third is 0.3 multiplied by the supervised ratio ...
    when `required_supervised_minutes` is 0 the supervised ratio is taken to be 0."
    PRD §3.6: "if the `supervision_mode` is `UNSUPERVISED`, the member's tier has
    `unsupervised_allowed` true and that certification's `readiness_score` is at
    least 0.8, or else `ERR_READINESS_NOT_MET` (HTTP 409)."

    ACTIVE (0.5) + orientation (0.2) + 0 supervised = 0.7 (< 0.8); an UNSUPERVISED
    confirm is rejected with ERR_READINESS_NOT_MET.

    Design: Corner/calculations/certification_readiness_below_gate_blocks_unsupervised
    """
    member = create_active_member(tier_overrides=PRO_TIER, topup_cents=20000)
    machine = create_machine(**LASER_MACHINE)
    cert = create_certification_for(
        member["id"], "LASER", supervised_minutes=0, required_supervised_minutes=180
    )
    assert cert["readiness_score"] == 0.7, cert["readiness_score"]
    res = create_held_reservation(
        member, machine, cert, "2026-05-18T10:00:00Z", "2026-05-18T11:00:00Z",
        supervision_mode="UNSUPERVISED",
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_READINESS_NOT_MET.value
    )


# ===========================================================================
# Corner / validations / confirm_insufficient_funds_returns_409
# ===========================================================================
def test_confirm_insufficient_funds_returns_409(api):
    """PRD §3.6: "and finally `wallet_credit_cents` covers the forward estimate
    computed in this transition, or else `ERR_INSUFFICIENT_FUNDS` (HTTP 409)."

    A member with wallet 100 confirming a reservation whose estimate is 4820 is
    rejected, and the wallet stays 100 (no debit).

    Design: Corner/validations/confirm_insufficient_funds_returns_409
    """
    tier = create_tier(**MAKER_TIER)
    member = create_active_member_on_tier(tier, topup_cents=100)
    machine = create_machine(**LASER_MACHINE)
    cert = create_certification_for(member["id"], "LASER")
    res = create_held_reservation(
        member, machine, cert, "2026-05-22T10:00:00Z", "2026-05-22T11:00:00Z"
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_INSUFFICIENT_FUNDS.value
    )
    after = validate_success(api.get_member(member["id"], mh))
    assert after["wallet_credit_cents"] == 100, after["wallet_credit_cents"]
