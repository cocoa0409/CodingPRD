"""Merchant validations and the discount calculation: the three-way min, the
free-hours clamp, budget conservation under redemption, budget exhaustion at
issue, and non-redeemability across garages.

PRD §3.7 governs the discount; §3.5 the redeemability check at exit.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_transient_session_with_validation,
    setup_transient_facility,
    create_garage,
    create_merchant,
    issue_validation,
    set_clock,
    open_session,
    close_session,
    get_merchant,
    get_validation,
    make_merchant_headers,
    create_validation_payload,
)

ADMIN = TEST_USERS["facility_admin_headers"]


def test_validation_discount_three_way_min_budget_clip(api):
    """PRD §3.7: "The applied discount is then the smallest of three quantities:
    the raw discount, the gross charge, and the merchant's remaining
    `validation_budget_cents` — a merchant can never grant more than its budget,
    and the discount can never exceed the charge."
    PRD §3.7: "The session's `net_charge_cents` is the gross charge minus the
    applied discount, which is at least zero by construction."

    FLAT_CENTS 800 raw, gross 1500, budget 500 → applied=500, net=1000, budget→0.

    Design: Difficulty/combinatorial_formula/validation_discount_three_way_min_budget_clip
    """
    ctx = setup_transient_session_with_validation(
        discount_kind="FLAT_CENTS", discount_value=800, merchant_budget=500,
        plate="VAL555", entry_at_utc="2026-06-01T10:00:00Z",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15,
    )
    exited = close_session(ctx["session"]["id"], "2026-06-01T12:30:00Z",
                           validation_id=ctx["validation"]["id"])
    assert exited["gross_charge_cents"] == 1500
    assert exited["net_charge_cents"] == 1000
    assert get_merchant(ctx["merchant"]["id"])["validation_budget_cents"] == 0
    assert get_validation(ctx["validation"]["id"])["status"] == "REDEEMED"


def test_free_hours_validation_capped_at_gross(api):
    """PRD §3.7: "a `FREE_HOURS` validation yields `discount_value` multiplied by
    the zone rate plan's `hourly_cents`."
    PRD §3.7: "The applied discount is then the smallest of three quantities: the
    raw discount, the gross charge, and the merchant's remaining
    `validation_budget_cents`".

    FREE_HOURS=10 → raw 10*500=5000, clamped to gross 1500 → net 0, budget 10000→8500.

    Design: Corner/calculations/free_hours_validation_capped_at_gross
    """
    ctx = setup_transient_session_with_validation(
        discount_kind="FREE_HOURS", discount_value=10, merchant_budget=10000,
        plate="FRH111", entry_at_utc="2026-06-01T10:00:00Z",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15,
    )
    exited = close_session(ctx["session"]["id"], "2026-06-01T12:30:00Z",
                           validation_id=ctx["validation"]["id"])
    assert exited["gross_charge_cents"] == 1500
    assert exited["net_charge_cents"] == 0
    assert get_merchant(ctx["merchant"]["id"])["validation_budget_cents"] == 8500


def test_merchant_budget_conserved_under_percent_redemption(api):
    """PRD §3.7: "a `PERCENT` validation yields the gross multiplied by
    `discount_value` divided by one hundred, rounded down to the nearest whole cent".
    PRD §3.7: "When the applied discount is greater than zero, the validation's
    `status` is set to `REDEEMED` and the merchant's `validation_budget_cents` is
    debited by exactly the applied amount".

    PERCENT-20 on gross 1500 → applied 300, net 1200, budget 10000→9700.

    Design: Difficulty/compensating_invariant/merchant_budget_conserved_under_validation_redemption
    """
    ctx = setup_transient_session_with_validation(
        discount_kind="PERCENT", discount_value=20, merchant_budget=10000,
        plate="CON111", entry_at_utc="2026-06-01T10:00:00Z",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15,
    )
    exited = close_session(ctx["session"]["id"], "2026-06-01T12:30:00Z",
                           validation_id=ctx["validation"]["id"])
    assert exited["net_charge_cents"] == 1200
    assert get_merchant(ctx["merchant"]["id"])["validation_budget_cents"] == 9700
    assert get_validation(ctx["validation"]["id"])["status"] == "REDEEMED"


def test_issue_validation_with_zero_budget_rejected(api):
    """PRD §3.7: "Issuing a validation when the merchant's `validation_budget_cents`
    is zero is rejected with `ERR_MERCHANT_BUDGET_EXHAUSTED`."

    Design: Corner/errors/merchant_budget_exhausted_on_issue_validation
    """
    facility = setup_transient_facility(num_spaces=0)
    garage = facility["garage"]
    merchant = create_merchant(garage["id"], validation_budget_cents=0)
    resp = api.create_validation(
        create_validation_payload(garage["id"], merchant["id"], "FLAT_CENTS", 500,
                                  "2026-06-02T00:00:00Z"),
        make_merchant_headers(merchant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MERCHANT_BUDGET_EXHAUSTED.value)


def test_validation_for_different_garage_not_redeemable(api):
    """PRD §3.5: "If a `validation_id` is supplied, the validation must be
    redeemable: its `status` must be `ISSUED`, the `exit_at_utc` must fall strictly
    before the validation's `expires_at_utc`, and the validation's `garage_id` must
    match the session's garage; any failure rejects the exit with
    `ERR_VALIDATION_NOT_REDEEMABLE`."

    Design: Corner/errors/validation_not_redeemable_wrong_garage
    """
    # Garage G1 with a session; Garage G2 with a still-valid validation.
    facility = setup_transient_facility(num_spaces=1)
    g1 = facility["garage"]

    g2 = create_garage(name="G2")
    merchant = create_merchant(g2["id"], validation_budget_cents=10000)
    validation = issue_validation(g2["id"], merchant["id"], "FLAT_CENTS", 300)

    set_clock("2026-06-01T10:00:00Z")
    sess = open_session(g1["id"], "VNR111", "2026-06-01T10:00:00Z")
    resp = api.exit_session(
        sess["id"], {"exit_at_utc": "2026-06-01T11:00:00Z", "validation_id": validation["id"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_NOT_REDEEMABLE.value)
