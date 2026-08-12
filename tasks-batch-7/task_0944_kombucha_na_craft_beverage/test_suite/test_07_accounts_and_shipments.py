"""Trade accounts, shipments, the invoice ledger and the confirmation gates."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_liters,
    assert_money,
    assert_utc_date,
    build_active_account,
    build_delivered_shipment,
    build_released_lot,
    build_subscription,
    lot_version,
    open_shipment,
    read_account,
    read_lot,
    read_shipment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
TAPROOM = TEST_USERS["taproom_staff_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _delivered_three_line_shipment(api):
    built = build_released_lot(
        api, run_code="PR-5", vessel_code="FV-4", batch_code="B-4001", culture_label="Mother D"
    )
    account = build_active_account(
        api, account_name="Bay Distributors", credit_limit=5000.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )
    delivered = build_delivered_shipment(
        api, account["id"], built["lot"]["id"], [(8, 5.45), (8, 5.45), (8, 5.45)]
    )
    return built, account, delivered


def test_the_three_shipment_totals_sum_the_already_rounded_line_values(api):
    """PRD 3.9: "Each accepted line is created with `line_status` `ACTIVE`, its
    `extended_price` computed as `units` multiplied by `unit_price` rounded half up to
    2 decimals and its `line_liters` as `units` multiplied by the lot's
    `container_liters` rounded the same way, and it immediately raises the lot's
    `reserved_units` by `units`."
    PRD 3.9: "`total_units` is the plain sum of `units`, `total_liters` is the sum of
    the already-rounded `line_liters` values, and `subtotal` is the sum of the
    already-rounded `extended_price` values, itself rounded half up to 2 decimals."

    Design: Difficulty/combinatorial_formula/late_fee_rounds_per_line_before_summing
    """
    _, _, delivered = _delivered_three_line_shipment(api)
    shipment = delivered["shipment"]

    assert_money(shipment["subtotal"], 130.80, "subtotal of three 43.60 lines")
    assert shipment["total_units"] == 24
    assert_liters(shipment["total_liters"], 9.00, "total_liters of three 3.00 L lines")
    for line in delivered["lines"]:
        assert_money(line["extended_price"], 43.60, "extended_price per line")
        assert_liters(line["line_liters"], 3.00, "line_liters per line")


def test_the_late_fee_rounds_per_line_before_summing(api):
    """PRD 3.9: "`late_fee` is then computed line by line: for each `ACTIVE` line,
    multiply its `extended_price` by 1.5, divide by 100, multiply by the number of
    late months, and round that half up to 2 decimals; the shipment's `late_fee` is
    the sum of those per-line amounts."
    PRD 3.9: "The scaffold's counter-example makes the difference visible: three
    `ACTIVE` lines each with an `extended_price` of 43.60 at 10 days past due, so one
    late month, give 0.65 per line and a `late_fee` of 1.95, whereas summing first and
    rounding once gives 1.96."
    PRD 3.9: "`aging_bucket` follows from the same day count: `CURRENT` when
    `days_past_due` is 0; `B1_1_30` when it is at least 1 and at most 30; `B2_31_60`
    when it is at least 31 and at most 60; and `B3_61_PLUS` when it is 61 or more."

    Design: Difficulty/combinatorial_formula/late_fee_rounds_per_line_before_summing
    """
    built, _, delivered = _delivered_three_line_shipment(api)
    set_clock(api, "2026-06-21T00:00:00.000Z")

    shipment = read_shipment(api, delivered["shipment"]["id"])

    assert shipment["days_past_due"] == 10
    assert shipment["aging_bucket"] == "B1_1_30"
    assert_money(shipment["late_fee"], 1.95, "late_fee rounded per line then summed")

    lot = read_lot(api, built["lot"]["id"])
    assert lot["shipped_units"] == 24
    assert lot["on_hand_units"] == 234


def test_an_account_on_credit_hold_answers_the_state_code_not_the_credit_code(api):
    """PRD 2.8: "| `ERR_INVALID_STATE` vs `ERR_CREDIT_LIMIT_EXCEEDED` |
    `ERR_INVALID_STATE` | confirming a shipment | The account's standing (rung 6) is a
    state precondition; the credit test (rung 9) is fiscal. |"
    PRD 2.8: "(6) the account's `status` is `ACTIVE` — both `ONBOARDING` and
    `CREDIT_HOLD` fail here — else `ERR_INVALID_STATE`"

    Design: Difficulty/priority_pair_validation_conflict/account_state_gate_beats_the_credit_limit_gate_on_confirm
    """
    built = build_released_lot(
        api, run_code="PR-9", vessel_code="FV-9", batch_code="B-9001", culture_label="Mother I"
    )
    account = build_active_account(
        api, account_name="Tight Credit Co", credit_limit=100.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )
    shipment = open_shipment(api, account["id"])
    add_line(api, shipment["id"], built["lot"]["id"], 30, 5.00)
    validate_success(
        api.credit_hold_account(account["id"], {"reason": "Aged receivable review"}, SALES)
    )

    response = api.confirm_shipment(shipment["id"], SALES)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert response.json()["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"


def test_the_refused_confirm_leaves_the_shipment_draft_and_the_reservation_standing(api):
    """PRD 3.9: "**Reservation happens at line-add time, not at confirmation.**"
    PRD 3.9: "Confirmation stamps `confirmed_at`, recomputes the three totals, and
    moves the shipment `DRAFT → CONFIRMED`."
    PRD 3.9: "A `SalesRep` may also place an account on `CREDIT_HOLD`, with an
    optional `reason`."

    Design: Difficulty/priority_pair_validation_conflict/account_state_gate_beats_the_credit_limit_gate_on_confirm
    """
    built = build_released_lot(
        api, run_code="PR-9", vessel_code="FV-9", batch_code="B-9001", culture_label="Mother I"
    )
    account = build_active_account(
        api, account_name="Tight Credit Co", credit_limit=100.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )
    shipment = open_shipment(api, account["id"])
    add_line(api, shipment["id"], built["lot"]["id"], 30, 5.00)
    validate_success(
        api.credit_hold_account(account["id"], {"reason": "Aged receivable review"}, SALES)
    )

    validate_error(
        api.confirm_shipment(shipment["id"], SALES), ApiErrorId.ERR_INVALID_STATE.value, 409
    )

    assert read_shipment(api, shipment["id"])["status"] == "DRAFT"
    assert read_account(api, account["id"])["status"] == "CREDIT_HOLD"
    assert read_lot(api, built["lot"]["id"])["reserved_units"] == 30


def test_cancelling_an_already_cancelled_shipment_is_refused(api):
    """PRD 3.9: "`PAID` and `CANCELLED` are the shipment's terminal statuses."
    PRD 2.9: "A `Shipment` has `status` exactly `DRAFT` for a line add and for a
    confirmation, exactly `CONFIRMED` for a delivery, exactly `DELIVERED` for a
    payment, and in `DRAFT`, `CONFIRMED` or `RECALL_HOLD` for a cancellation —
    otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancelling_an_already_cancelled_shipment_is_refused
    """
    account = build_active_account(
        api, account_name="Cancel Co", credit_limit=1000.0
    )
    shipment = open_shipment(api, account["id"])
    validate_success(
        api.cancel_shipment(shipment["id"], {"reason": "Customer withdrew"}, SALES)
    )

    response = api.cancel_shipment(shipment["id"], {"reason": "Duplicate request"}, SALES)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_shipment(api, shipment["id"])["status"] == "CANCELLED"


def test_taproom_staff_may_not_confirm_a_shipment(api):
    """PRD 2.1: "When the acting role is not listed among the roles authorised for the
    endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD 2.8: "(2) the acting role is `SalesRep`, else `ERR_UNAUTHORIZED`"

    Design: Corner/rbac/taproom_staff_cannot_confirm_a_shipment
    """
    account = build_active_account(api, account_name="Role Test Co", credit_limit=1000.0)
    shipment = open_shipment(api, account["id"])

    response = api.confirm_shipment(shipment["id"], TAPROOM)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_shipment(api, shipment["id"])["status"] == "DRAFT"


def test_the_self_distribution_ceiling_blocks_the_confirm_before_the_credit_test(api):
    """PRD 3.9: "For a `SELF_DISTRIBUTION` account, `ytd_self_dist_liters` plus this
    shipment's `total_liters` must be at or below the annual ceiling of 4000.0 liters
    — a projected total of exactly 4000.0 is accepted, and strictly more is
    `ERR_SELF_DIST_CEILING_EXCEEDED`."
    PRD 2.8: "| `ERR_SELF_DIST_CEILING_EXCEEDED` vs `ERR_CREDIT_LIMIT_EXCEEDED` |
    `ERR_SELF_DIST_CEILING_EXCEEDED` | confirming a shipment | The statutory
    self-distribution ceiling (rung 8) outranks the commercial credit limit (rung 9).
    |"

    Design: Corner/errors/self_distribution_annual_ceiling_blocks_the_confirm
    """
    built = build_released_lot(
        api,
        style="KOMBUCHA",
        fmt="KEG",
        max_units_requested=2500,
        liters_drawn=45000.0,
        pitched_liters=45000.0,
        vessel_capacity=50000.0,
        run_code="PR-41",
        vessel_code="FV-41",
        batch_code="B-41001",
        culture_label="Mother AJ",
    )
    assert_liters(built["run"]["net_liters"], 43650.0, "net_liters of the 45000 L draw")
    assert built["lot"]["units_produced"] == 2238

    # The credit limit is deliberately far below the 210.00 subtotal, so the
    # fiscal rung would also trip: the ceiling has to pre-empt it.
    account = build_active_account(
        api, account_name="Self Dist Co", channel="SELF_DISTRIBUTION", credit_limit=100.0,
        credit_terms_days=30, alcoholic_license_on_file=False,
    )
    shipment = open_shipment(api, account["id"])
    add_line(api, shipment["id"], built["lot"]["id"], 210, 1.00)

    response = api.confirm_shipment(shipment["id"], SALES)
    validate_error(response, ApiErrorId.ERR_SELF_DIST_CEILING_EXCEEDED.value, 422)
    assert response.json()["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"

    after = read_shipment(api, shipment["id"])
    assert after["status"] == "DRAFT"
    assert_liters(after["total_liters"], 4095.0, "210 keg units at 19.5 L each")
    assert_liters(
        read_account(api, account["id"])["ytd_self_dist_liters"], 0.0,
        "a refused confirm never moves the self-distribution ledger",
    )


def test_an_alcoholic_lot_is_gated_by_licence_then_age_then_remaining_shelf(api):
    """PRD 3.9: "Every `ACTIVE` line whose lot carries `abv_class` `ALCOHOLIC`
    requires `alcoholic_license_on_file` to be true, or
    `ERR_ALCOHOLIC_CHANNEL_RESTRICTED`."
    PRD 3.10: "when the lot carries `abv_class` `ALCOHOLIC` the subscriber must be at
    least 21 years old at the logical clock, measured from `subscriber_birth_date`,
    otherwise `ERR_AGE_VERIFICATION_REQUIRED`"
    PRD 3.10: "On the boundaries, a lot whose `best_by_date` is exactly the clock plus
    14 days is **not** eligible — the remaining shelf must be strictly more than 14
    days — while available units of exactly 6 **are** enough."

    Design: Corner/errors/an_alcoholic_lot_is_gated_by_licence_age_and_remaining_shelf_life
    """
    built = build_released_lot(
        api,
        intended_abv_class="ALCOHOLIC",
        style="JUN",
        f1_abvs=(0.10, 0.18, 0.26),
        f2_abv=0.40,
        packaging_abv=0.53,
        run_code="PR-42",
        vessel_code="FV-42",
        batch_code="B-42001",
        culture_label="Mother AK",
    )
    lot = built["lot"]
    assert lot["abv_class"] == "ALCOHOLIC"
    assert_utc_date(lot["best_by_date"], "2026-08-08", "best_by_date")

    account = build_active_account(
        api, account_name="No Licence Co", credit_limit=5000.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )
    shipment = open_shipment(api, account["id"])
    add_line(api, shipment["id"], lot["id"], 10, 6.00)
    validate_error(
        api.confirm_shipment(shipment["id"], SALES),
        ApiErrorId.ERR_ALCOHOLIC_CHANNEL_RESTRICTED.value,
        422,
    )
    assert read_shipment(api, shipment["id"])["status"] == "DRAFT"

    minor = build_subscription(
        api, built["recipe"]["id"], subscriber_email="minor@example.com",
        subscriber_birth_date="2010-01-01T00:00:00.000Z",
    )
    adult = build_subscription(
        api, built["recipe"]["id"], subscriber_email="adult@example.com",
        subscriber_birth_date="1990-03-11T00:00:00.000Z",
    )

    under_age = api.create_subscription_allocation(
        {
            "subscription_id": minor["id"],
            "cycle_index": 1,
            "finished_lot_id": lot["id"],
            "expected_finished_lot_version": lot_version(api, lot["id"], ADMIN),
        },
        ADMIN,
    )
    validate_error(under_age, ApiErrorId.ERR_AGE_VERIFICATION_REQUIRED.value, 403)

    set_clock(api, "2026-07-25T00:00:00.000Z")
    too_short = api.create_subscription_allocation(
        {
            "subscription_id": adult["id"],
            "cycle_index": 1,
            "finished_lot_id": lot["id"],
            "expected_finished_lot_version": lot_version(api, lot["id"], ADMIN),
        },
        ADMIN,
    )
    validate_error(too_short, ApiErrorId.ERR_SHELF_LIFE_TOO_SHORT.value, 422)

    for subscription in (minor, adult):
        rows, meta = validate_paginated(
            api.list_subscription_allocations(subscription["id"], ADMIN)
        )
        assert meta["total_count"] == 0 and rows == []
    assert read_lot(api, lot["id"])["reserved_units"] == 10
