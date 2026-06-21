"""Attendant shift drawer reconciliation and shift-session constraints."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_attendant_headers,
    create_member,
    open_shift,
    setup_shift_with_coin_and_cash_reload,
    begin_reconcile,
    close_shift,
    create_shift_payload,
)

MANAGER = TEST_USERS["manager_headers"]


def test_shift_expected_vs_counted_drawer_variance(api):
    """PRD §3.6: "That expected figure is the `opening_float_cents` plus
    `coin_collected_cents` plus `cash_reload_cents` minus
    `cash_refund_paid_cents`."
    PRD §3.6: "Closing the shift requires it to be `RECONCILING` and the
    attendant to submit the physically `counted_drawer_cents`; this moves it
    `RECONCILING → CLOSED` and computes the signed `variance_cents` as the
    counted figure minus the expected figure".

    Design: Difficulty/dual_variant_calc/shift_expected_vs_counted_drawer_variance
    """
    # opening_float 5000 + coin 300 + cash_reload 2000 = expected 7300.
    shift, attendant_id, washer, vend, walk_member = setup_shift_with_coin_and_cash_reload(
        opening_float_cents=5000, wash_base_cents=300, reload_principal_cents=2000)
    begin_reconcile(shift["id"], attendant_id)
    resp = api.close_shift(
        shift["id"], {"counted_drawer_cents": 7250}, make_attendant_headers(attendant_id))
    closed = validate_success(resp, 200)
    assert closed["expected_drawer_cents"] == 7300
    assert closed["counted_drawer_cents"] == 7250
    assert closed["variance_cents"] == -50, "7250 - 7300 = -50"


def test_expected_drawer_aggregates_coin_and_cash_reload(api):
    """PRD §3.6: "`coin_collected_cents` is the sum of `charged_amount_cents`
    over the shift's `COIN` vends that remain `CAPTURED`; `cash_reload_cents` is
    the sum of `principal_cents` over the shift's `CASH` reloads that are
    `POSTED`".

    Design: Difficulty/dual_variant_calc/shift_expected_vs_counted_drawer_variance
    """
    shift, attendant_id, washer, vend, walk_member = setup_shift_with_coin_and_cash_reload(
        opening_float_cents=5000, wash_base_cents=300, reload_principal_cents=2000)
    reconciling = begin_reconcile(shift["id"], attendant_id)
    assert reconciling["coin_collected_cents"] == 300
    assert reconciling["cash_reload_cents"] == 2000
    assert reconciling["expected_drawer_cents"] == 7300


def test_second_open_shift_for_attendant_rejected(api):
    """PRD §3.6: "An attendant may hold only one open shift at a time — opening a
    second while one is already `OPEN` for the same attendant is rejected with
    `ERR_SHIFT_ALREADY_OPEN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/shift_open_session_overlap_per_attendant_reject
    """
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    attendant_id = attendant["id"]
    open_shift(attendant_id, opening_float_cents=5000)
    resp = api.create_shift(
        create_shift_payload(attendant_id, opening_float_cents=3000),
        make_attendant_headers(attendant_id))
    validate_error(resp, ApiErrorId.ERR_SHIFT_ALREADY_OPEN.value)
