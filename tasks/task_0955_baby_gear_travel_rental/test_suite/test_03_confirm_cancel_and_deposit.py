"""Confirmation, cancellation, the deposit hold, and payment-status dimension."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_deposit_conservation,
    create_and_activate_recall,
    create_catalog_item,
    create_customer,
    create_quoted_reservation,
    create_unit,
    confirm_reservation,
    get_availability,
    get_reservation,
    get_unit,
    list_deposit_transactions,
    list_lines,
    make_customer_headers,
    setup_confirmed_reservation,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestParallelPaymentDimension:
    def test_confirm_moves_rental_and_payment_dimensions_together(self, api):
        """PRD 3.4: "A `HOLD` ledger entry for the full `deposit_hold_cents` is
        appended with reason `HOLD_AT_CONFIRM`, `payment_status` moves from
        `DEPOSIT_PENDING` to `DEPOSIT_HELD`, and the reservation lands in
        `CONFIRMED` with its `version` bumped."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_dimension
        """
        ctx = setup_confirmed_reservation()
        reservation = ctx["reservation"]
        assert reservation["status"] == "CONFIRMED"
        assert reservation["payment_status"] == "DEPOSIT_HELD"
        assert reservation["deposit_hold_cents"] == 15000

    def test_cancel_moves_dimensions_to_different_terminal_pair(self, api):
        """PRD 3.4: "A cancellation fee of ten percent of `quoted_total_cents`,
        rounded half-up, is charged against the deposit waterfall: a `CAPTURE`
        entry with reason `CANCELLATION_FEE` for the lesser of the fee and the
        outstanding hold, then a `RELEASE` entry with reason `RELEASE_REMAINDER`
        for whatever is left, if anything."
        PRD 3.4: "`payment_status` moves to `SETTLED_PAID` when any amount was
        captured, otherwise to `REFUNDED`, and the reservation is terminally
        `CANCELLED`."

        Quoted 13000 -> fee 1300 captured, 13700 released of the 15000 hold.

        Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_dimension
        """
        ctx = setup_confirmed_reservation()
        reservation = ctx["reservation"]
        customer = ctx["customer"]
        cancelled = validate_success(
            api.cancel_reservation(
                reservation["id"], make_customer_headers(customer["id"])
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["payment_status"] == "SETTLED_PAID"
        assert cancelled["deposit_captured_cents"] == 1300
        assert cancelled["deposit_released_cents"] == 13700
        assert_deposit_conservation(cancelled)


class TestConfirmRequiresCustomerActive:
    def test_suspended_customer_confirm_rejected(self, api, ops_headers):
        """PRD 3.4: "The reservation must belong to the requesting customer,
        whose own record must be `ACTIVE` — a suspended customer is turned away
        with `ERR_CUSTOMER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
        """
        customer = create_customer()
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        reservation = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        validate_success(api.suspend_customer(customer["id"], ops_headers), 200)
        res = api.confirm_reservation(
            reservation["id"], make_customer_headers(customer["id"])
        )
        validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=403)
        after = get_reservation(reservation["id"])
        assert after["status"] == "QUOTED", "rejected confirm must not advance state"

    def test_reinstated_customer_confirm_succeeds(self, api, ops_headers):
        """PRD 3.2: "Reinstatement moves the customer back from `SUSPENDED` to
        `ACTIVE` and bumps the version again."
        PRD 3.2: "Suspension, however it happens, bumps the customer's
        `version` and bars the customer from confirming reservations: any
        confirm attempted while `SUSPENDED` fails with
        `ERR_CUSTOMER_SUSPENDED`."

        The confirm gate tracks the customer's live status: once reinstated,
        the same reservation confirms.

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
        """
        customer = create_customer()
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        reservation = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        validate_success(api.suspend_customer(customer["id"], ops_headers), 200)
        validate_success(api.reinstate_customer(customer["id"], ops_headers), 200)
        confirmed = validate_success(
            api.confirm_reservation(
                reservation["id"], make_customer_headers(customer["id"])
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "DEPOSIT_HELD"


class TestSafetyBeatsConstraintOnConfirm:
    def test_recall_blocked_wins_over_customer_suspended(self, api, ops_headers):
        """PRD 2.8: "When several checks could reject the same request, they
        are evaluated in a fixed order, and the first failing check determines
        the response."
        PRD 2.8: "Recall safety — confirmation and reallocation are refused
        when the catalog item sits under an `ACTIVE` `MANDATORY` recall
        (`ERR_RECALL_BLOCKED`, 409), and a quarantined unit may never be
        allocated (`ERR_UNIT_QUARANTINED`, 409)."
        PRD 2.8: "Structural constraints — zone matching
        (`ERR_ZONE_MISMATCH`, 422), partner standing (`ERR_PARTNER_SUSPENDED`,
        409), customer standing at confirmation (`ERR_CUSTOMER_SUSPENDED`,
        403), ..."

        Recall safety (check 8) precedes structural constraints (check 10): a
        SUSPENDED customer confirming a reservation under an ACTIVE MANDATORY
        recall sees ERR_RECALL_BLOCKED, not ERR_CUSTOMER_SUSPENDED.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_confirm
        """
        customer = create_customer()
        validate_success(api.suspend_customer(customer["id"], ops_headers), 200)
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        create_and_activate_recall(catalog["id"], severity="MANDATORY")
        reservation = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        res = api.confirm_reservation(
            reservation["id"], make_customer_headers(customer["id"])
        )
        validate_error(res, "ERR_RECALL_BLOCKED", expected_status=409)

    def test_recall_blocked_confirm_leaves_reservation_quoted(
        self, api, ops_headers
    ):
        """PRD 3.4: "No line may reference a catalog item that has been
        `DELISTED` (`ERR_CATALOG_ITEM_DELISTED`), nor one sitting under an
        `ACTIVE` recall of `MANDATORY` severity (`ERR_RECALL_BLOCKED`)."

        The rejected confirm is atomic: the reservation stays QUOTED with
        payment_status DEPOSIT_PENDING and no ledger entries are written.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_confirm
        """
        customer = create_customer()
        validate_success(api.suspend_customer(customer["id"], ops_headers), 200)
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        create_and_activate_recall(catalog["id"], severity="MANDATORY")
        reservation = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        res = api.confirm_reservation(
            reservation["id"], make_customer_headers(customer["id"])
        )
        validate_error(res, "ERR_RECALL_BLOCKED", expected_status=409)
        after = get_reservation(reservation["id"])
        assert after["status"] == "QUOTED"
        assert after["payment_status"] == "DEPOSIT_PENDING"
        assert list_deposit_transactions(reservation["id"]) == []


class TestUnitPoolConservation:
    def test_confirm_drains_bookable_pool(self, api):
        """PRD 3.4: "On success, each line moves `PENDING` to `ALLOCATED`: its
        `assigned_unit_id` is set, its `unit_rate_cents` snapshots the catalog
        item's `daily_rate_cents` at that moment — becoming the permanent basis
        for late and extension charges even if the catalog price later changes
        — and the chosen unit moves `AVAILABLE` to `RESERVED` with its
        `version` bumped."

        Two units, one two-line reservation: availability over the booked
        window goes 2 -> 0 at confirm.

        Design: Difficulty/compensating_invariant/unit_pool_conservation_across_confirm_cancel
        """
        customer = create_customer()
        catalog = create_catalog_item()
        unit1 = create_unit(catalog["id"])
        unit2 = create_unit(catalog["id"])
        assert get_availability(catalog["id"], "2026-06-10", "2026-06-13") == 2
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[
                {"catalog_item_id": catalog["id"]},
                {"catalog_item_id": catalog["id"]},
            ],
        )
        confirm_reservation(reservation["id"], customer["id"])
        assert get_availability(catalog["id"], "2026-06-10", "2026-06-13") == 0
        assert get_unit(unit1["id"])["status"] == "RESERVED"
        assert get_unit(unit2["id"])["status"] == "RESERVED"

    def test_cancel_restores_bookable_pool_exactly(self, api):
        """PRD 3.4: "Every `ALLOCATED` line moves to `CANCELLED` and each
        reserved unit returns to `AVAILABLE`, its `version` bumped, while the
        line keeps its `assigned_unit_id` for audit."

        The compensating cancel returns availability over the same window to
        exactly its pre-confirm value: 2 -> 0 -> 2 with no unit leaked.

        Design: Difficulty/compensating_invariant/unit_pool_conservation_across_confirm_cancel
        """
        customer = create_customer()
        catalog = create_catalog_item()
        unit1 = create_unit(catalog["id"])
        unit2 = create_unit(catalog["id"])
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[
                {"catalog_item_id": catalog["id"]},
                {"catalog_item_id": catalog["id"]},
            ],
        )
        confirm_reservation(reservation["id"], customer["id"])
        assert get_availability(catalog["id"], "2026-06-10", "2026-06-13") == 0
        validate_success(
            api.cancel_reservation(
                reservation["id"], make_customer_headers(customer["id"])
            ),
            200,
        )
        assert get_availability(catalog["id"], "2026-06-10", "2026-06-13") == 2
        assert get_unit(unit1["id"])["status"] == "AVAILABLE"
        assert get_unit(unit2["id"])["status"] == "AVAILABLE"


def test_confirm_with_no_eligible_unit_fails_atomically(api):
    """PRD 3.4: "A confirm that finds no eligible unit for any line fails with
    `ERR_NO_ELIGIBLE_UNIT`"
    PRD 3.4: "when no other reservation in `CONFIRMED` or `DELIVERED` holds a
    line assigned to that unit whose committed interval overlaps the request."

    The single unit is committed to a CONFIRMED reservation whose buffered
    interval covers the second reservation's window; the second confirm fails
    with ERR_NO_ELIGIBLE_UNIT and leaves its line PENDING with no unit
    assigned.

    Design: Corner/errors/error_unit_unavailable_on_confirm
    """
    customer = create_customer()
    catalog = create_catalog_item()
    unit = create_unit(catalog["id"])
    res1 = create_quoted_reservation(
        customer["id"],
        lines=[{"catalog_item_id": catalog["id"]}],
        start_date="2026-06-10",
        end_date="2026-06-13",
    )
    confirm_reservation(res1["id"], customer["id"])
    res2 = create_quoted_reservation(
        customer["id"],
        lines=[{"catalog_item_id": catalog["id"]}],
        start_date="2026-06-12",
        end_date="2026-06-15",
    )
    res = api.confirm_reservation(res2["id"], make_customer_headers(customer["id"]))
    # PRD names both outcomes for this scenario without fixing precedence:
    # "A confirm that finds no eligible unit for any line fails with
    # ERR_NO_ELIGIBLE_UNIT" (3.4) and "a unit whose committed interval collides
    # with the requested window yields ERR_UNIT_UNAVAILABLE under the
    # temporal-overlap rule" (3.4 + 2.8 priority 9). Both readings are
    # PRD-faithful, so accept either error_id (both are 409).
    assert res.status_code == 409
    validate_error_is_one_of(res, ["ERR_NO_ELIGIBLE_UNIT", "ERR_UNIT_UNAVAILABLE"])
    after = get_reservation(res2["id"])
    assert after["status"] == "QUOTED"
    line = list_lines(res2["id"])[0]
    assert line["status"] == "PENDING"
    assert line["assigned_unit_id"] is None
    assert get_unit(unit["id"])["status"] == "RESERVED"


def test_cancellation_fee_ten_percent(api):
    """PRD 3.4: "A cancellation fee of ten percent of `quoted_total_cents`,
    rounded half-up, is charged against the deposit waterfall: a `CAPTURE`
    entry with reason `CANCELLATION_FEE` for the lesser of the fee and the
    outstanding hold, then a `RELEASE` entry with reason `RELEASE_REMAINDER`
    for whatever is left, if anything."

    Quoted 13000 -> fee round_half_up(13000 x 0.10) = 1300 captured, and the
    remaining 13700 of the 15000 hold released.

    Design: Corner/calculations/cancellation_fee_ten_percent
    """
    ctx = setup_confirmed_reservation()
    reservation = ctx["reservation"]
    customer = ctx["customer"]
    cancelled = validate_success(
        api.cancel_reservation(
            reservation["id"], make_customer_headers(customer["id"])
        ),
        200,
    )
    assert cancelled["deposit_captured_cents"] == 1300
    assert cancelled["deposit_released_cents"] == 13700
    txns = list_deposit_transactions(reservation["id"])
    assert [(t["txn_type"], t["amount_cents"], t["reason"]) for t in txns] == [
        ("HOLD", 15000, "HOLD_AT_CONFIRM"),
        ("CAPTURE", 1300, "CANCELLATION_FEE"),
        ("RELEASE", 13700, "RELEASE_REMAINDER"),
    ]


def test_deposit_transaction_append_only_immutability(api):
    """PRD 2.4: "The exception is the DepositTransaction ledger entry: it is an
    append-only record carrying only `id` and `created_at`; it has no
    `updated_at` and no `version`, because a ledger entry, once written, is
    never modified."
    PRD 2.9: "Every movement against a reservation's deposit hold is recorded
    as an immutable DepositTransaction entry with a `txn_type` of `HOLD`,
    `CAPTURE`, or `RELEASE`, a signed-positive `amount_cents`, a `reason` drawn
    from `HOLD_AT_CONFIRM`, `DAMAGE_CLAIM`, `LATE_FEE`, `CANCELLATION_FEE`, or
    `RELEASE_REMAINDER`, and a `balance_after_cents` giving the outstanding
    held balance immediately after the entry is appended — a hold adds to the
    balance, a capture or release subtracts."

    After confirm exactly one entry exists: HOLD 15000 with balance 15000, and
    it exposes id/created_at but no version or updated_at.

    Design: Corner/entities/deposit_transaction_append_only_immutability
    """
    ctx = setup_confirmed_reservation()
    txns = list_deposit_transactions(ctx["reservation"]["id"])
    assert len(txns) == 1
    entry = txns[0]
    assert entry["txn_type"] == "HOLD"
    assert entry["amount_cents"] == 15000
    assert entry["reason"] == "HOLD_AT_CONFIRM"
    assert entry["balance_after_cents"] == 15000
    assert "version" not in entry
    assert "updated_at" not in entry


def test_immediate_consistency_confirm_response(api):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 3.4: "A `HOLD` ledger entry for the full `deposit_hold_cents` is
    appended with reason `HOLD_AT_CONFIRM`, `payment_status` moves from
    `DEPOSIT_PENDING` to `DEPOSIT_HELD`, and the reservation lands in
    `CONFIRMED` with its `version` bumped."

    The confirm response itself — no re-read — already shows status CONFIRMED,
    payment_status DEPOSIT_HELD, and deposit_hold_cents 15000.

    Design: Corner/consistency_model/immediate_consistency_confirm_response
    """
    customer = create_customer()
    catalog = create_catalog_item()
    create_unit(catalog["id"])
    reservation = create_quoted_reservation(
        customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
    )
    res = api.confirm_reservation(
        reservation["id"], make_customer_headers(customer["id"])
    )
    confirmed = validate_success(res, 200)
    assert confirmed["id"] == reservation["id"]
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_HELD"
    assert confirmed["deposit_hold_cents"] == 15000
