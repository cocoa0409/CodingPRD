"""Keg assets, the deposit ledger, and the taproom."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_keg_deposit_conservation,
    assert_liters,
    assert_money,
    build_active_account,
    build_filled_keg,
    build_released_lot,
    build_subscription,
    build_tapped_keg,
    lot_version,
    open_fill,
    read_account,
    read_keg,
    read_lot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
SALES = TEST_USERS["sales_rep_headers"]
TAPROOM = TEST_USERS["taproom_staff_headers"]
TAPROOM_ALT = TEST_USERS["taproom_staff_alt_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _keg_lot(api, *, run_code, vessel_code, batch_code, culture_label):
    return build_released_lot(
        api,
        fmt="KEG",
        max_units_requested=10,
        liters_drawn=100.0,
        run_code=run_code,
        vessel_code=vessel_code,
        batch_code=batch_code,
        culture_label=culture_label,
    )


def _issued_keg(api):
    built = _keg_lot(
        api, run_code="PR-16", vessel_code="FV-16", batch_code="B-16001",
        culture_label="Mother P",
    )
    account = build_active_account(
        api, account_name="Riverside Taps", credit_limit=5000.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )
    keg = build_filled_keg(api, built["lot"]["id"], asset_code="KEG-001", fill_liters=19.5)
    validate_success(api.issue_keg(keg["id"], {"account_id": account["id"]}, SALES))
    set_clock(api, "2026-08-11T00:00:00.000Z")
    return built, account, keg


def test_a_keg_returned_on_day_ninety_one_forfeits_forty_percent_of_the_deposit(api):
    """PRD 3.8: "**Late and undamaged.** `condition` is `GOOD` and the days out are at
    or above 91 — a return on day 90 exactly is still on time. Forty per cent of the
    deposit is forfeited, so `deposit_forfeit_amount` is 18.00 and
    `deposit_refund_amount` is 27.00, each rounded half up to 2 decimals.
    `deposit_state` becomes `FORFEITED` and the keg still moves to `RETURNED` and is
    still fillable."
    PRD 3.8: "`returned_at` is stamped with the logical clock, and the number of whole
    days out is the count of complete days from `issued_at` to `returned_at`."

    Design: Difficulty/compensating_invariant/a_late_keg_return_still_conserves_every_deposit_dollar
    """
    _, _, keg = _issued_keg(api)

    returned = validate_success(api.return_keg(keg["id"], {"condition": "GOOD"}, SALES))

    assert returned["status"] == "RETURNED"
    assert returned["deposit_state"] == "FORFEITED"
    assert_money(returned["deposit_refund_amount"], 27.00, "deposit_refund_amount")
    assert_money(returned["deposit_forfeit_amount"], 18.00, "deposit_forfeit_amount")


def test_the_late_return_leaves_every_deposit_dollar_accounted_for(api):
    """PRD 2.11: "For every account, `keg_deposit_balance` equals 45.00 dollars
    multiplied by the number of kegs currently held by that account with
    `deposit_state` `CHARGED`. A second, stronger condition also holds: 45.00
    multiplied by `kegs_charged_lifetime` equals `keg_deposit_balance` plus
    `deposit_refunded_total` plus `deposit_forfeited_total`."
    PRD 3.8: "In every case the account's `keg_deposit_balance` falls by 45.00, its
    `deposit_refunded_total` rises by the refund and its `deposit_forfeited_total`
    rises by the forfeit, the keg's `account_id` is cleared and `deposit_amount` is
    reset to 0, and both the keg's and the account's `version` increment."
    PRD 3.8: "On success the keg moves to `FILLED`, `finished_lot_id` and
    `fill_liters` are stored, the lot's `on_hand_units` drops by 1 while its
    `poured_units` rises by 1, and `deposit_state` is reset to `NONE` with
    `deposit_amount` reset to 0 for the new cycle."

    Design: Difficulty/compensating_invariant/a_late_keg_return_still_conserves_every_deposit_dollar
    """
    built, account, keg = _issued_keg(api)

    validate_success(api.return_keg(keg["id"], {"condition": "GOOD"}, SALES))

    after = read_account(api, account["id"])
    assert_money(after["keg_deposit_balance"], 0.00, "keg_deposit_balance after the return")
    assert_money(after["deposit_refunded_total"], 27.00, "deposit_refunded_total")
    assert_money(after["deposit_forfeited_total"], 18.00, "deposit_forfeited_total")
    assert after["kegs_charged_lifetime"] == 1
    assert_keg_deposit_conservation(after, charged_keg_count=0)

    lot = read_lot(api, built["lot"]["id"])
    assert lot["units_produced"] == 4
    assert lot["on_hand_units"] == 3
    assert lot["poured_units"] == 1


def test_the_pour_gates_run_inspection_then_charge_then_keg_volume(api):
    """PRD 3.8: "A `CUSTOMER_GROWLER` may not: it must first pass a sanitation
    inspection, which moves it `REQUESTED → INSPECTED` and stamps `inspected_at` and
    `inspected_by_user_id`, and it may only be poured from `INSPECTED` while the
    logical clock is at or before `inspected_at` plus 24 hours. Pouring a
    customer-owned growler that is still `REQUESTED`, or whose inspection has gone
    stale, answers `ERR_GROWLER_INSPECTION_REQUIRED`."
    PRD 3.8: "The scaffold's worked example: 1.20 liters gives a gross of 10.80 and a
    discount of 1.08, so a `CUSTOMER_GROWLER` costs 11.22, a `HOUSE_GROWLER` costs
    13.22, and a `GLASS_POUR` costs 9.72; a 0.50-liter `GLASS_POUR` costs 4.50 with no
    discount at all. That same 1.20-liter growler fill from a keg showing 19.00 liters
    leaves 17.80 liters behind."
    PRD 3.8: "`requested_liters` may not exceed the keg's `remaining_liters` — a pour
    of exactly the remainder is accepted, and one cent of a liter more is
    `ERR_INSUFFICIENT_KEG_VOLUME`."

    Design: Corner/errors/taproom_gates_reject_uninspected_growlers_oversized_pours_and_early_retaps
    """
    built = _keg_lot(
        api, run_code="PR-40", vessel_code="FV-40", batch_code="B-40001",
        culture_label="Mother AI",
    )
    keg = build_tapped_keg(api, built["lot"]["id"], asset_code="KEG-040", fill_liters=19.5)
    assert_liters(keg["remaining_liters"], 19.00, "remaining_liters after the blow-off allowance")

    growler = open_fill(api, keg["id"], container_type="CUSTOMER_GROWLER", requested_liters=1.2)
    uninspected = api.pour_taproom_fill(growler["id"], TAPROOM)
    validate_error(uninspected, ApiErrorId.ERR_GROWLER_INSPECTION_REQUIRED.value, 422)

    validate_success(api.inspect_taproom_fill(growler["id"], TAPROOM_ALT))
    poured = validate_success(api.pour_taproom_fill(growler["id"], TAPROOM))
    assert poured["fill_status"] == "POURED"
    assert_money(poured["charge_amount"], 11.22, "customer growler charge for 1.20 L")
    assert_liters(poured["poured_liters"], 1.2, "poured_liters")
    assert_liters(read_keg(api, keg["id"])["remaining_liters"], 17.80, "keg after the growler")

    glass = open_fill(api, keg["id"], container_type="GLASS_POUR", requested_liters=0.5)
    poured_glass = validate_success(api.pour_taproom_fill(glass["id"], TAPROOM))
    assert_money(poured_glass["charge_amount"], 4.50, "glass pour charge for 0.50 L")
    assert_liters(read_keg(api, keg["id"])["remaining_liters"], 17.30, "keg after the glass pour")

    oversized = open_fill(api, keg["id"], container_type="GLASS_POUR", requested_liters=30.0)
    refused = api.pour_taproom_fill(oversized["id"], TAPROOM)
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_KEG_VOLUME.value, 422)
    still_open, _ = validate_paginated(
        api.list_keg_fills(keg["id"], TAPROOM, params={"fill_status": "REQUESTED"})
    )
    assert [row["id"] for row in still_open] == [oversized["id"]], (
        "the refused pour leaves its fill in fill_status REQUESTED"
    )


def test_an_immediate_retap_and_an_oversubscribed_box_are_both_refused(api):
    """PRD 3.8: "If the keg has been on tap before, `last_untapped_at` will be set, and
    the re-tap is only allowed once the logical clock is **strictly after** that
    instant plus 15 minutes; a re-tap exactly on the buffer boundary is refused with
    `ERR_KEG_RETAP_BUFFER`."
    PRD 3.8: "Untapping returns the keg `ON_TAP → FILLED`, stamps `last_untapped_at`
    with the logical clock and clears `tapped_at` to null."
    PRD 2.8: "(11) the lot's `on_hand_units` minus its `reserved_units` is at or above
    6, else `ERR_INSUFFICIENT_LOT_UNITS`."

    Design: Corner/errors/taproom_gates_reject_uninspected_growlers_oversized_pours_and_early_retaps
    """
    built = _keg_lot(
        api, run_code="PR-40", vessel_code="FV-40", batch_code="B-40001",
        culture_label="Mother AI",
    )
    keg = build_tapped_keg(api, built["lot"]["id"], asset_code="KEG-040", fill_liters=19.5)
    subscription = build_subscription(
        api, built["recipe"]["id"], subscriber_email="taro@example.com",
        subscriber_birth_date="1985-06-06T00:00:00.000Z",
    )

    validate_success(api.untap_keg(keg["id"], TAPROOM))
    early_retap = api.tap_keg(keg["id"], TAPROOM)
    validate_error(early_retap, ApiErrorId.ERR_KEG_RETAP_BUFFER.value, 422)
    assert read_keg(api, keg["id"])["status"] == "FILLED"

    lot = read_lot(api, built["lot"]["id"])
    assert lot["on_hand_units"] == 3, "one of the four units went into the keg"
    assert lot["reserved_units"] == 0

    refused = api.create_subscription_allocation(
        {
            "subscription_id": subscription["id"],
            "cycle_index": 1,
            "finished_lot_id": lot["id"],
            "expected_finished_lot_version": lot_version(api, lot["id"], ADMIN),
        },
        ADMIN,
    )
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_LOT_UNITS.value, 422)
