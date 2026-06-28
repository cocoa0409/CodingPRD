"""Locker overage threshold, locker release billing, and the optimistic-concurrency
guards on locker assignment and reservation confirm.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_tier,
    register_member,
    create_active_member,
    create_active_member_on_tier,
    create_machine,
    create_certification_for,
    create_held_reservation,
    assign_locker,
    create_locker_payload,
    make_member_headers,
)

MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
LASER_MACHINE = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}


# ===========================================================================
# Corner / calculations / locker_overage_threshold_boundary_at_free_quota
# ===========================================================================
def test_locker_overage_zero_at_free_quota(api):
    """PRD §3.7: "The overage liters are the greater of 0 and `used_liters` minus the
    free volume, and the `overage_fee_cents` is the overage liters multiplied by a
    flat storage rate of 30 cents per liter. The boundary is exact: when `used_liters`
    equals the free quota the overage is 0, and when `used_liters` is one liter above
    the free quota exactly one liter is charged."

    A MAKER member (free 50L) with a locker at exactly 50L has overage_fee_cents 0.

    Design: Corner/calculations/locker_overage_threshold_boundary_at_free_quota
    """
    member = create_active_member(tier_overrides=MAKER_TIER, topup_cents=5000)
    locker = assign_locker(member, used_liters=50, capacity_liters=100)
    assert locker["overage_fee_cents"] == 0, locker["overage_fee_cents"]


def test_locker_overage_charged_above_quota(api):
    """PRD §3.7: "The overage liters are the greater of 0 and `used_liters` minus the
    free volume, and the `overage_fee_cents` is the overage liters multiplied by a
    flat storage rate of 30 cents per liter."
    PRD §3.7: "A member may update a locker's `used_liters`, which recomputes
    `overage_fee_cents`."

    PATCH from 50L to 80L (30 liters over * 30c) yields overage_fee_cents 900.

    Design: Corner/calculations/locker_overage_threshold_boundary_at_free_quota
    """
    member = create_active_member(tier_overrides=MAKER_TIER, topup_cents=5000)
    locker = assign_locker(member, used_liters=50, capacity_liters=100)
    mh = make_member_headers(member["id"])
    updated = validate_success(api.update_locker(locker["id"], {"used_liters": 80}, mh))
    assert updated["overage_fee_cents"] == 900, updated["overage_fee_cents"]


# ===========================================================================
# Corner / endpoints / locker_release_bills_overage_then_zeroes_volume
# ===========================================================================
def test_locker_release_bills_overage_and_zeroes_volume(api):
    """PRD §3.7: "Releasing a locker moves it from `ASSIGNED` to `RELEASED`. If
    `overage_fee_cents` is greater than 0 at release, the member's
    `wallet_credit_cents` is debited by `overage_fee_cents` and a `WalletEntry` of
    kind `OVERAGE` with a negative `amount_cents` is appended; release then sets
    `used_liters` to 0."

    Releasing a locker at 80L (MAKER free 50 -> 900 overage) debits 900 from the
    5000 wallet (-> 4100), sets status RELEASED and used_liters 0.

    Design: Corner/endpoints/locker_release_bills_overage_then_zeroes_volume
    """
    member = create_active_member(tier_overrides=MAKER_TIER, topup_cents=5000)
    locker = assign_locker(member, used_liters=80, capacity_liters=100)
    mh = make_member_headers(member["id"])
    released = validate_success(api.release_locker(locker["id"], mh))
    assert released["status"] == "RELEASED"
    assert released["used_liters"] == 0, released["used_liters"]
    after = validate_success(api.get_member(member["id"], mh))
    assert after["wallet_credit_cents"] == 4100, after["wallet_credit_cents"]


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_locker_create_stale_member_version
# ===========================================================================
def test_locker_create_stale_member_version_rejected(api):
    """PRD §2.5: "The first guarded write is **assigning a new locker**. ... A
    mismatch between `expected_member_version` and the member's present `version`
    yields `ERR_STALE_VERSION` (HTTP 412)."

    The client observes member.version, a top-up advances it, and a locker create
    carrying the stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_locker_create_stale_member_version
    """
    tier = create_tier(**MAKER_TIER)
    member = register_member(tier["id"])
    stale_version = member["version"]
    mh = make_member_headers(member["id"])
    validate_success(api.topup(member["id"], 5000, mh))  # advances Member.version
    payload = create_locker_payload(
        member["id"], stale_version, capacity_liters=100, used_liters=10
    )
    validate_error(api.create_locker(payload, mh), ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_reservation_confirm_correct_version_succeeds
# ===========================================================================
def test_confirm_with_current_version_bumps_member_version(api):
    """PRD §2.5: "The second guarded write is **confirming a reservation**. ... if
    `expected_member_version` no longer matches the member's current `version`, the
    client computed affordability against an outdated balance, and the confirm is
    rejected."
    PRD §3.6: "On a successful confirm the server computes `estimate_charge_cents` ...
    advances `Member.version` by 1."

    A confirm carrying the member's current version succeeds and advances
    Member.version by exactly 1.

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_confirm_correct_version_succeeds
    """
    tier = create_tier(**MAKER_TIER)
    member = create_active_member_on_tier(tier, topup_cents=5000)
    machine = create_machine(**LASER_MACHINE)
    cert = create_certification_for(member["id"], "LASER")
    res = create_held_reservation(
        member, machine, cert, "2026-05-30T10:00:00Z", "2026-05-30T11:00:00Z"
    )
    mh = make_member_headers(member["id"])
    v_before = validate_success(api.get_member(member["id"], mh))["version"]
    confirmed = validate_success(api.confirm_reservation(res["id"], v_before, mh))
    assert confirmed["occupancy_status"] == "CONFIRMED"
    after = validate_success(api.get_member(member["id"], mh))
    assert after["version"] == v_before + 1, after["version"]


# ===========================================================================
# Corner / consistency_model / confirm_response_reflects_debit_immediately
# ===========================================================================
def test_confirm_debit_visible_immediately(api):
    """PRD §3.6: "On a successful confirm the server computes `estimate_charge_cents`
    via the **forward** variant of the session-charge calculation ... debits
    `wallet_credit_cents` by `estimate_charge_cents`."
    PRD §2.4: "Time-dependent rules ... are all evaluated against a **logical
    clock**."

    A member topped to exactly 5000 confirming a 4820-estimate reservation shows the
    post-debit wallet of 180 on an immediately-following GET — the debit is visible
    with no read lag.

    Design: Corner/consistency_model/confirm_response_reflects_debit_immediately
    """
    tier = create_tier(**MAKER_TIER)
    member = create_active_member_on_tier(tier, topup_cents=5000)
    machine = create_machine(**LASER_MACHINE)
    cert = create_certification_for(member["id"], "LASER")
    res = create_held_reservation(
        member, machine, cert, "2026-05-31T10:00:00Z", "2026-05-31T11:00:00Z"
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    confirmed = validate_success(api.confirm_reservation(res["id"], v, mh))
    assert confirmed["occupancy_status"] == "CONFIRMED"
    member_after = validate_success(api.get_member(member["id"], mh))
    assert member_after["wallet_credit_cents"] == 180, member_after["wallet_credit_cents"]
