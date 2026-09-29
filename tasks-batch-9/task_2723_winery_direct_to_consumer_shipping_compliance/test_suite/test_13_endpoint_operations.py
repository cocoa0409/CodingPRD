"""Endpoint-level operations of the Winery DTC Shipping Compliance API.

Every test here builds its own preconditions through the public API, because the
harness restarts the server and empties the database before each test.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_instant_equals,
    assert_liters,
    assert_order_dimensions,
    assert_tracking_number,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_SALES_TAX_CENTS,
    CANONICAL_ORDER_TOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
    CLOCK_DEFAULT_CANONICAL,
    STATE_RULE_TX,
)
from test_helpers.fixtures import (
    append_manual_adjustment,
    build_cleared_order,
    build_landscape,
    build_returned_order,
    create_verified_consumer,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    OFFICER_A,
    OFFICER_A_USER_ID,
    OFFICER_B,
    OFFICER_B_USER_ID,
)

TX_LIMIT_LITERS = STATE_RULE_TX["per_consumer_limit_liters"]
LITERS_TOLERANCE = 0.0005


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _per_state_numbers(summary, state_code):
    """Every numeric figure the volume summary reports for one state."""
    entry = summary["per_state"][state_code]
    return [
        value
        for value in entry.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def _assert_per_state(summary, state_code, rolling, limit):
    """The accumulated liters, the per-consumer limit and the headroom between."""
    values = _per_state_numbers(summary, state_code)
    for expected in (rolling, limit, limit - rolling):
        assert any(abs(value - expected) <= LITERS_TOLERANCE for value in values), (
            f"per_state.{state_code} must report {expected:.3f}; got {values}"
        )


def test_winery_suspension_gates_orders_and_club_runs_until_reinstatement(api):
    """Suspending an `ACTIVE` winery — an `ACTIVE` → `SUSPENDED` move — accepts an optional free-text `suspension_reason` which is recorded on the row; reinstating a `SUSPENDED` winery — `SUSPENDED` → `ACTIVE` — clears `suspension_reason` back to null.

    Neither move is available from the state it targets: reinstating a winery that is already `ACTIVE`, like suspending one that is already `SUSPENDED`, is refused with `ERR_INVALID_STATE_TRANSITION`.

    While a winery is `SUSPENDED`, five operations on its behalf are refused with `ERR_WINERY_SUSPENDED`: creating an order, producing a shipping label, opening a club subscription, filing a permit renewal, and running the wine-club scheduler. (PRD 3.1)

    Design: Corner/endpoints/winery_suspension_gates_orders_and_runs_until_it_is_reinstated
    """
    scape = build_landscape(api)
    subscription = scape.create_subscription(next_run_date="2026-08-01")
    consumer_v1 = scape.consumer_version()

    suspended = get_success_data(
        api.set_winery_status(
            scape.winery_id,
            f.winery_status_payload("SUSPENDED", "TTB report overdue"),
            ADMIN,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "TTB report overdue"

    order_body = f.order_payload(scape.winery_id, scape.consumer_id, consumer_v1)
    validate_error(
        api.create_order(order_body, scape.operator), "ERR_WINERY_SUSPENDED", 409
    )
    validate_error(
        api.create_club_run(
            f.club_run_payload(scape.winery_id, "2026-08-01"), scape.operator
        ),
        "ERR_WINERY_SUSPENDED",
        409,
    )
    held = scape.read_subscription(subscription["id"])
    assert held["next_run_date"] == "2026-08-01"
    assert held["consumed_shipments"] == 0

    reinstated = get_success_data(
        api.set_winery_status(
            scape.winery_id, f.winery_status_payload("ACTIVE"), ADMIN
        )
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None

    validate_error(
        api.set_winery_status(
            scape.winery_id, f.winery_status_payload("ACTIVE"), ADMIN
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    # The two refusals moved nothing, so the version captured before the
    # suspension is still the consumer's current version.
    order = get_success_data(api.create_order(order_body, scape.operator), 201)
    assert_order_dimensions(order, "DRAFT", "UNFULFILLED")
    assert_cents(order["total_cents"], CANONICAL_ORDER_TOTAL_CENTS, "total_cents")

    rows, meta = validate_paginated(
        api.list_orders(OFFICER_A, {"winery_id": scape.winery_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [order["id"]]


def test_club_run_generates_one_subscription_and_skips_two(api):
    """A subscription with no allotment left is **silently skipped**: it is reported in the response's `skipped_subscription_ids` and its `next_run_date` is left exactly where it was.

    A `WEATHER_HELD` candidate is handled in one of two ways depending on its hold: if its `hold_release_date` falls on or before the `run_date`, the hold has lapsed, so the system performs the `WEATHER_HELD` → `ACTIVE` release itself — with the same field clearing as a manual release, including copying `hold_release_date` into `last_hold_release_date` — and the subscription then participates in the very same run; if its `hold_release_date` is strictly after the `run_date`, the subscription is skipped and its `next_run_date` is set to its `hold_release_date` so the next run picks it up as soon as the hold ends.

    If the generated order landed in `CLEARED` or in `OVERRIDE_PENDING`, `next_run_date` is advanced by the subscription's `cadence`. (PRD 3.8)

    Design: Corner/endpoints/club_run_generates_one_subscription_and_skips_two_for_different_reasons
    """
    scape = build_landscape(api, clock="2026-07-01T00:00:00Z")
    ben = create_verified_consumer(
        api,
        full_name="Ben Buyer",
        email="ben@example.com",
        birthdate="1979-11-30",
        address_line="14 Vine St",
    )
    cleo = create_verified_consumer(
        api,
        full_name="Cleo Buyer",
        email="cleo@example.com",
        birthdate="1990-02-14",
        address_line="14 Vine St",
    )

    ada_sub = scape.create_subscription(next_run_date="2026-07-01", annual_allotment=1)
    ben_sub = scape.create_subscription(
        consumer_id=ben["id"],
        next_run_date="2026-08-01",
        sku="CLUB-BEN",
        bottles_per_shipment=3,
        unit_price_cents=3100,
    )
    cleo_sub = scape.create_subscription(
        consumer_id=cleo["id"],
        next_run_date="2026-08-01",
        sku="CLUB-CLEO",
        bottles_per_shipment=4,
        unit_price_cents=2900,
    )

    # The July run exhausts Ada's single-shipment allotment.
    scape.club_run("2026-07-01")
    get_success_data(
        api.place_weather_hold(
            cleo_sub["id"],
            f.weather_hold_payload("2026-07-28", "2026-08-10", "WEATHER_HEAT"),
            scape.operator,
        )
    )
    set_clock(api, "2026-08-01T00:00:00Z")

    run = scape.club_run("2026-08-01")
    assert run["generated_count"] == 1
    assert run["skipped_count"] == 2
    assert len(run["generated_order_ids"]) == 1
    assert sorted(run["skipped_subscription_ids"]) == sorted(
        [ada_sub["id"], cleo_sub["id"]]
    )

    exhausted = scape.read_subscription(ada_sub["id"])
    assert exhausted["consumed_shipments"] == 1
    assert exhausted["remaining_allotment"] == 0
    assert exhausted["status"] == "ACTIVE"
    assert exhausted["next_run_date"] == "2026-08-01"

    still_held = scape.read_subscription(cleo_sub["id"])
    assert still_held["status"] == "WEATHER_HELD"
    assert still_held["hold_release_date"] == "2026-08-10"
    assert still_held["next_run_date"] == "2026-08-10"

    advanced = scape.read_subscription(ben_sub["id"])
    assert advanced["consumed_shipments"] == 1
    assert advanced["remaining_allotment"] == 11
    assert advanced["next_run_date"] == "2026-09-01"

    generated = scape.read_order(run["generated_order_ids"][0])
    assert generated["club_subscription_id"] == ben_sub["id"]
    assert_order_dimensions(generated, "CLEARED", "UNFULFILLED")
    assert_liters(generated["total_liters"], 2.250, "total_liters")
    assert_cents(generated["subtotal_cents"], 9300, "subtotal_cents")
    assert_cents(generated["shipping_gross_cents"], 1995, "shipping_gross_cents")
    assert_cents(generated["shipping_discount_cents"], 499, "shipping_discount_cents")
    assert_cents(generated["shipping_cents"], 1496, "shipping_cents")
    assert_cents(generated["excise_tax_cents"], 105, "excise_tax_cents")
    assert_cents(generated["sales_tax_cents"], 891, "sales_tax_cents")
    assert_cents(
        generated["compliance_handling_fee_cents"], 900, "compliance_handling_fee_cents"
    )
    assert_cents(generated["total_cents"], 12692, "total_cents")

    _, meta = validate_paginated(
        api.list_orders(OFFICER_A, {"winery_id": scape.winery_id})
    )
    assert meta["total_count"] == 2

    for subscription_id in (ada_sub["id"], ben_sub["id"], cleo_sub["id"]):
        assert scape.read_subscription(subscription_id)["missed_run_count"] == 0


def test_replacement_shipment_must_name_an_existing_returned_shipment(api):
    """The order must be `CLEARED` on the compliance axis and either `UNFULFILLED` or — for a re-ship — `RETURNED` on the fulfillment axis; any other combination is refused with `ERR_ORDER_NOT_CLEARED` (HTTP 409). (PRD 3.7)

    Every one of `winery_id`, `state_rule_id`, `consumer_id`, `carrier_program_id`, `carrier_enrollment_id`, `order_id`, `shipment_id`, `club_subscription_id`, `replacement_of_shipment_id` and `supersedes_remittance_id` must resolve to a stored row when supplied, and a supplied `ship_to_state_code` or `state_code` must have a `StateRule` row governing it. (PRD 2.8)

    On success a new shipment row is created in `LABEL_CREATED` with `replacement_of_shipment_id` set, a `SHIPMENT_ACCEPTED` ledger entry is appended with `liters` equal to positive `total_liters`, `order_id` set and `shipment_id` null; the order's `excise_reversed_cents` and `sales_tax_reversed_cents` are both put back to 0 and the winery's `excise_reversed_cents` is reduced by the order's `excise_tax_cents`, undoing the reversal the return had recorded; and because the re-debit entry now exists, the consumer's rolling and risk fields are recomputed with `Consumer.version` incrementing by 1. (PRD 3.7)

    Design: Corner/endpoints/replacement_shipment_must_name_an_existing_returned_shipment
    """
    scape, order, first = build_returned_order(api)

    # A RETURNED order is shippable only as a re-ship, so a label that names no
    # returned predecessor is not a legal combination.
    validate_error(
        api.create_shipment(
            f.shipment_payload(order["id"], scape.enrollment_id), scape.operator
        ),
        "ERR_ORDER_NOT_CLEARED",
        409,
    )
    # Body foreign keys are resolved before state-transition legality.
    validate_error(
        api.create_shipment(
            f.shipment_payload(order["id"], scape.enrollment_id, NON_EXISTENT_UUID),
            scape.operator,
        ),
        "ERR_SHIPMENT_NOT_FOUND",
        404,
    )

    replacement = get_success_data(
        api.create_shipment(
            f.shipment_payload(order["id"], scape.enrollment_id, first["id"]),
            scape.operator,
        ),
        201,
    )
    assert replacement["status"] == "LABEL_CREATED"
    assert replacement["replacement_of_shipment_id"] == first["id"]
    assert replacement["id"] != first["id"]
    assert replacement["adult_signature_required"] is True
    assert_tracking_number(replacement["tracking_number"])
    assert_tracking_number(first["tracking_number"])

    rows, meta = validate_paginated(
        api.list_shipments(OFFICER_A, {"replacement_of_shipment_id": first["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [replacement["id"]]

    original = scape.read_shipment(first["id"])
    assert original["status"] == "RETURNED"
    assert original["returned_at"] is not None
    assert original["replacement_of_shipment_id"] is None

    reshipped = scape.read_order(order["id"])
    assert_order_dimensions(reshipped, "CLEARED", "LABELED")
    assert_cents(reshipped["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(
        reshipped["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents"
    )
    assert_cents(
        scape.read_winery()["excise_reversed_cents"], 0, "excise_reversed_cents"
    )

    entries = scape.ledger_rows(order_id=order["id"])
    assert [entry["event_type"] for entry in entries] == [
        "SHIPMENT_ACCEPTED",
        "RETURN_CREDIT",
        "SHIPMENT_ACCEPTED",
    ]
    for entry, expected in zip(
        entries,
        (
            CANONICAL_ORDER_TOTAL_LITERS,
            -CANONICAL_ORDER_TOTAL_LITERS,
            CANONICAL_ORDER_TOTAL_LITERS,
        ),
    ):
        assert_liters(entry["liters"], expected)
    assert entries[2]["shipment_id"] is None


def test_volume_summary_is_derived_on_read_and_moves_with_the_ledger(api):
    """A consumer's whole volume picture is available as a single computed read that reports the `consumer_id`, an `as_of` instant taken from the logical clock, a `per_state` map — keyed by state code, giving that state's accumulated rolling liters, the state's per-consumer limit, and the headroom remaining between them — and, side by side, `risk_score_screening`, `risk_score_audit`, `screening_tier`, `return_credit_count` and `denied_exception_count`. An optional `state_code` filter narrows the `per_state` map to one state. (PRD 3.4)

    `rolling_liters_settled_by_state` is the same sum over the same window, restricted to entries whose `order_id` is null or whose order's `fulfillment_status` is one of `IN_TRANSIT`, `DELIVERED` or `RETURNED`. (PRD 3.4)

    Recomputing a derived field counts as a mutation: when a ledger append forces the consumer's rolling volumes and risk scores to be recalculated, `Consumer.version` advances even though no client sent a field. (PRD 2.5)

    Design: Corner/endpoints/volume_summary_is_derived_on_read_and_moves_with_the_ledger
    """
    scape, order = build_cleared_order(api)
    version_after_clearance = scape.consumer_version()

    first = scape.volume_summary(state_code="TX")
    assert first["consumer_id"] == scape.consumer_id
    assert_instant_equals(first["as_of"], CLOCK_DEFAULT_CANONICAL)
    _assert_per_state(first, "TX", CANONICAL_ORDER_TOTAL_LITERS, TX_LIMIT_LITERS)

    entry = append_manual_adjustment(
        api,
        scape.consumer_id,
        scape.winery_id,
        2.000,
        occurred_at="2026-07-20T00:00:00Z",
    )
    assert entry["event_type"] == "MANUAL_ADJUSTMENT"
    assert entry["order_id"] is None
    assert_liters(entry["liters"], 2.000)

    second = scape.volume_summary(state_code="TX")
    _assert_per_state(second, "TX", 6.500, TX_LIMIT_LITERS)

    consumer = scape.read_consumer()
    assert_liters(consumer["rolling_liters_by_state"]["TX"], 6.500)
    # The cleared order is still UNFULFILLED, so only the manual entry settles.
    assert_liters(consumer["rolling_liters_settled_by_state"]["TX"], 2.000)
    assert consumer["version"] == version_after_clearance + 1

    for field in (
        "risk_score_screening",
        "risk_score_audit",
        "screening_tier",
        "return_credit_count",
        "denied_exception_count",
    ):
        assert second[field] == consumer[field], f"{field} must agree with the consumer"

    third = scape.volume_summary(state_code="TX")
    _assert_per_state(third, "TX", 6.500, TX_LIMIT_LITERS)
    assert scape.read_consumer()["version"] == version_after_clearance + 1


def test_release_hold_is_legal_only_from_the_held_state(api):
    """Releasing a `WEATHER_HELD` subscription early — a `WEATHER_HELD` → `ACTIVE` move available to a `WineryOperator` or a `ComplianceOfficer` — copies the current `hold_release_date` into `last_hold_release_date` and then clears `hold_start_date`, `hold_release_date` and `hold_reason` back to null; the optional `reset_missed_runs` flag, when true, additionally puts `missed_run_count` back to 0.

    Attempting to release a hold on a subscription that is already `ACTIVE` is refused with `ERR_INVALID_STATE_TRANSITION`.

    Placing a hold deliberately leaves `next_run_date` untouched — it is the run itself, not the hold, that defers the schedule. (PRD 3.8)

    Design: Corner/endpoints/release_hold_is_legal_only_from_the_held_state
    """
    scape = build_landscape(api)
    subscription = scape.create_subscription(next_run_date="2026-09-01")
    assert subscription["status"] == "ACTIVE"

    validate_error(
        api.release_hold(subscription["id"], f.release_hold_payload(), scape.operator),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    held = get_success_data(
        api.place_weather_hold(
            subscription["id"],
            f.weather_hold_payload("2026-08-05", "2026-08-20", "WEATHER_FREEZE"),
            scape.operator,
        )
    )
    assert held["status"] == "WEATHER_HELD"
    assert held["hold_start_date"] == "2026-08-05"
    assert held["hold_release_date"] == "2026-08-20"
    assert held["hold_reason"] == "WEATHER_FREEZE"
    assert held["next_run_date"] == "2026-09-01"
    assert held["last_hold_release_date"] is None

    released = get_success_data(
        api.release_hold(subscription["id"], f.release_hold_payload(), scape.operator)
    )
    assert released["status"] == "ACTIVE"
    assert released["hold_start_date"] is None
    assert released["hold_release_date"] is None
    assert released["hold_reason"] is None
    assert released["last_hold_release_date"] == "2026-08-20"
    assert released["next_run_date"] == "2026-09-01"

    validate_error(
        api.release_hold(subscription["id"], f.release_hold_payload(), scape.operator),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    final = scape.read_subscription(subscription["id"])
    assert final["status"] == "ACTIVE"
    assert final["last_hold_release_date"] == "2026-08-20"
    assert final["missed_run_count"] == 0
    assert final["consumed_shipments"] == 0


def test_remittance_file_then_remit_is_an_ordered_chain_that_ends_terminal(api):
    """Filing lodges the return with the state, moving the remittance `OPEN` → `FILED`, and is available only from `OPEN` — filing an already-`FILED` remittance, or one that has been superseded to `AMENDED`, is refused with `ERR_INVALID_STATE_TRANSITION`.

    On success, `filed_at` is stamped from the logical clock and `filed_by_user_id` records the filing officer's `X-User-ID`.

    Recording payment moves the remittance `FILED` → `REMITTED` and captures the state's confirmation reference in `payment_reference`, stamping `remitted_at` from the logical clock and `remitted_by_user_id` from the acting officer's `X-User-ID`. It is available only from `FILED`; a remittance still `OPEN`, or one already `AMENDED`, cannot be remitted and the attempt is refused with `ERR_INVALID_STATE_TRANSITION`.

    Both `REMITTED` and `AMENDED` are terminal — a remittance in either state never moves again. (PRD 3.9)

    Design: Corner/endpoints/remittance_file_then_remit_is_an_ordered_chain_that_ends_terminal
    """
    # The period must have closed on the logical clock before it can be opened,
    # so the order clears inside July and the clock then rolls to 2026-08-01.
    scape = build_landscape(api, clock="2026-07-15T00:00:00Z")
    order = scape.create_order()
    cleared = scape.screen(order["id"])
    assert_order_dimensions(cleared, "CLEARED", "UNFULFILLED")
    set_clock(api, "2026-08-01T00:00:00Z")

    remittance = scape.open_remittance(
        "TX", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )
    assert remittance["status"] == "OPEN"
    assert remittance["shipment_count"] == 1
    assert_liters(remittance["liters_total"], CANONICAL_ORDER_TOTAL_LITERS)
    assert_cents(
        remittance["excise_due_cents"], CANONICAL_ORDER_EXCISE_CENTS, "excise_due_cents"
    )
    assert_cents(
        remittance["sales_tax_due_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_due_cents",
    )

    # Payment cannot be recorded before the return has been lodged.
    validate_error(
        api.remit_remittance(remittance["id"], f.remit_payload("TX-PAY-1"), OFFICER_B),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )
    assert scape.read_remittance(remittance["id"])["status"] == "OPEN"

    filed = get_success_data(api.file_remittance(remittance["id"], {}, OFFICER_A))
    assert filed["status"] == "FILED"
    assert_instant_equals(filed["filed_at"], CLOCK_DEFAULT_CANONICAL)
    assert filed["filed_by_user_id"] == OFFICER_A_USER_ID

    remitted = get_success_data(
        api.remit_remittance(remittance["id"], f.remit_payload("TX-PAY-1"), OFFICER_B)
    )
    assert remitted["status"] == "REMITTED"
    assert_instant_equals(remitted["remitted_at"], CLOCK_DEFAULT_CANONICAL)
    assert remitted["remitted_by_user_id"] == OFFICER_B_USER_ID
    assert remitted["payment_reference"] == "TX-PAY-1"

    validate_error(
        api.remit_remittance(remittance["id"], f.remit_payload("TX-PAY-2"), OFFICER_B),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )
    validate_error(
        api.file_remittance(remittance["id"], {}, OFFICER_A),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    final = scape.read_remittance(remittance["id"])
    assert final["status"] == "REMITTED"
    assert final["payment_reference"] == "TX-PAY-1"
    assert_instant_equals(final["filed_at"], CLOCK_DEFAULT_CANONICAL)
    assert final["filed_by_user_id"] == OFFICER_A_USER_ID
