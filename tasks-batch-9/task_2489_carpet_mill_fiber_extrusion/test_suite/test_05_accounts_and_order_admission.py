"""Accounts and cut-order admission: the credit ledger, the credit posture, the
admission gate on order creation, cancellation compensation, the style backorder
alert, DealerBuyer account scoping and orderability by order type.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_account,
    assert_account_credit_conservation,
    assert_credit_hold_posture,
    assert_cut_order,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_dealer_buyer_headers,
    make_plant_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]

# The canonical style in this file lists at 4275 cents per yard, so 120.0 yards
# reserve exactly 513000 cents.
LIST_PRICE_CENTS_PER_YARD = 4275
RESERVATION_FOR_120_YARDS = 513000


def _order_codes(api, account_id):
    """The order codes currently on file for one account, plus meta.total_count."""
    orders, meta = validate_paginated(
        api.list_cut_orders(PLANNER, params={"account_id": account_id, "limit": 100})
    )
    return [order["order_code"] for order in orders], meta


def _account_on_credit_hold():
    """An ACTIVE style plus an account driven exactly onto its 513000-cent limit."""
    style = fixtures.create_active_style()
    account = fixtures.create_account(
        account_code="AC-01", credit_limit_cents=RESERVATION_FOR_120_YARDS
    )
    order = fixtures.create_cut_order(
        account["id"],
        style["id"],
        order_code="CO-01",
        requested_yards=120.0,
        shade_tolerance="ANY",
    )
    return style, account, order


class TestCreditHoldPostureBeatsTheCreditCeiling:
    """The state rung is evaluated before the fiscal rung on order creation."""

    def test_credit_hold_refuses_the_order_ahead_of_the_credit_ceiling(self, api):
        """A second order that breaks both the CREDIT_HOLD posture and the ceiling is
        refused with ERR_ACCOUNT_CREDIT_HOLD, never ERR_CREDIT_LIMIT_EXCEEDED.

        PRD: "A new cut order may only be submitted for an `Account` in status
        `ACTIVE`; an account in `CREDIT_HOLD` yields `ERR_ACCOUNT_CREDIT_HOLD` and one
        in `CLOSED` yields `ERR_ACCOUNT_CLOSED`, both 409." and "Evaluation stops at
        the first failing rung."

        Design: Difficulty/priority_pair_validation_conflict/account_credit_hold_state_beats_credit_limit_fiscal_on_order_create
        """
        style, account, _first = _account_on_credit_hold()

        before = fixtures.refresh_account(account["id"])
        assert before["credit_used_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected credit_used_cents {RESERVATION_FOR_120_YARDS}, got "
            f"{before['credit_used_cents']} after the first order"
        )
        assert before["status"] == "CREDIT_HOLD", (
            f"expected CREDIT_HOLD once usage lands on the limit, got {before['status']}"
        )

        response = api.create_cut_order(
            factories.create_cut_order_payload(
                account["id"],
                style["id"],
                order_code="CO-02",
                requested_yards=200.0,
                shade_tolerance="ANY",
            ),
            PLANNER,
        )
        error = validate_error(response, "ERR_ACCOUNT_CREDIT_HOLD")
        assert error["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED", (
            "the state rung must win even though 513000 + 855000 exceeds the "
            f"513000-cent limit, got {error['error_id']}"
        )

        codes, meta = _order_codes(api, account["id"])
        assert codes == ["CO-01"], f"expected only CO-01 on file, got {codes}"
        assert meta["total_count"] == 1, (
            f"expected total_count 1 after the refusal, got {meta['total_count']}"
        )

        after = fixtures.refresh_account(account["id"])
        assert after["credit_used_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected the ledger to stay at {RESERVATION_FOR_120_YARDS}, got "
            f"{after['credit_used_cents']} after the refused order"
        )
        assert after["status"] == "CREDIT_HOLD", (
            f"expected CREDIT_HOLD after the refusal, got {after['status']}"
        )

    def test_raising_the_limit_clears_the_state_gate_and_admits_the_same_order(
        self, api
    ):
        """Raising the limit flips the account back to ACTIVE, and the identical
        request then reserves 855000 cents.

        PRD: "raising the limit can flip an account `CREDIT_HOLD` to `ACTIVE`, and
        lowering it can flip an account `ACTIVE` to `CREDIT_HOLD`" and "The reservation
        is the order's `requested_yards` multiplied by the style's
        `list_price_cents_per_yard`, rounded half-up to whole cents, and stored as
        `reserved_credit_cents`."

        Design: Difficulty/priority_pair_validation_conflict/account_credit_hold_state_beats_credit_limit_fiscal_on_order_create
        """
        style, account, _first = _account_on_credit_hold()

        refused = api.create_cut_order(
            factories.create_cut_order_payload(
                account["id"],
                style["id"],
                order_code="CO-02",
                requested_yards=200.0,
                shade_tolerance="ANY",
            ),
            PLANNER,
        )
        validate_error(refused, "ERR_ACCOUNT_CREDIT_HOLD")

        patched = validate_success(
            api.update_account(
                account["id"],
                factories.update_account_payload(credit_limit_cents=2000000),
                PLANNER,
            ),
            expected_status=200,
        )
        assert patched["credit_limit_cents"] == 2000000, (
            f"expected the raised limit 2000000, got {patched['credit_limit_cents']}"
        )
        assert patched["status"] == "ACTIVE", (
            "raising the limit above the used credit must flip the account back to "
            f"ACTIVE, got {patched['status']}"
        )

        admitted = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-02",
                    requested_yards=200.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert_cut_order(admitted)
        assert admitted["status"] == "SUBMITTED", (
            f"expected SUBMITTED, got {admitted['status']} for the admitted order"
        )
        assert admitted["reserved_credit_cents"] == 855000, (
            "expected 855000 reserved for 200.0 yards at 4275 cents, got "
            f"{admitted['reserved_credit_cents']}"
        )

        after = fixtures.refresh_account(account["id"])
        assert after["credit_used_cents"] == 1368000, (
            f"expected credit_used_cents 1368000, got {after['credit_used_cents']} "
            "after the second order"
        )
        assert after["status"] == "ACTIVE", (
            f"expected ACTIVE below the raised limit, got {after['status']}"
        )
        assert_credit_hold_posture(after)


class TestCreditAdmissionBoundaryAtOneCent:
    """The admission comparison and the hold comparison meet on the same integer."""

    def test_reservation_exactly_on_the_limit_is_admitted_and_holds_the_account(
        self, api
    ):
        """A 513000-cent reservation against a 513000-cent limit is admitted and
        immediately puts the account on CREDIT_HOLD.

        PRD: "The gate is inclusive, so an order that lands the account exactly on its
        limit is admissible" and "Because the comparison is inclusive, an account whose
        usage lands exactly on its limit is held."

        Design: Difficulty/boundary_precision_check/credit_admission_inclusive_while_credit_hold_flip_is_also_inclusive
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-EXACT", credit_limit_cents=RESERVATION_FOR_120_YARDS
        )
        assert account["credit_used_cents"] == 0, (
            f"a new account starts at 0 used credit, got {account['credit_used_cents']}"
        )
        assert account["status"] == "ACTIVE", (
            f"a new account starts ACTIVE, got {account['status']}"
        )

        order = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-EXACT",
                    requested_yards=120.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert order["reserved_credit_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected {RESERVATION_FOR_120_YARDS} reserved for 120.0 yards at "
            f"{LIST_PRICE_CENTS_PER_YARD} cents, got {order['reserved_credit_cents']}"
        )

        after = fixtures.refresh_account(account["id"])
        assert after["credit_used_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected credit_used_cents {RESERVATION_FOR_120_YARDS}, got "
            f"{after['credit_used_cents']}"
        )
        assert after["status"] == "CREDIT_HOLD", (
            "usage landing exactly on the limit must hold the account, got "
            f"{after['status']}"
        )
        assert_credit_hold_posture(after)

    def test_account_one_cent_short_refuses_the_very_same_order(self, api):
        """A 512999-cent limit refuses the same 513000-cent reservation with
        ERR_CREDIT_LIMIT_EXCEEDED and writes nothing.

        PRD: "An order that would take the account strictly past its limit is refused
        with `ERR_CREDIT_LIMIT_EXCEEDED` and nothing is written."

        Design: Difficulty/boundary_precision_check/credit_admission_inclusive_while_credit_hold_flip_is_also_inclusive
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-SHORT", credit_limit_cents=512999
        )

        response = api.create_cut_order(
            factories.create_cut_order_payload(
                account["id"],
                style["id"],
                order_code="CO-SHORT",
                requested_yards=120.0,
                shade_tolerance="ANY",
            ),
            PLANNER,
        )
        validate_error(response, "ERR_CREDIT_LIMIT_EXCEEDED")

        codes, meta = _order_codes(api, account["id"])
        assert codes == [], f"expected no orders written, got {codes}"
        assert meta["total_count"] == 0, (
            f"expected total_count 0 after the refusal, got {meta['total_count']}"
        )

        after = fixtures.refresh_account(account["id"])
        assert after["credit_used_cents"] == 0, (
            f"expected the ledger untouched at 0, got {after['credit_used_cents']}"
        )
        assert after["status"] == "ACTIVE", (
            f"expected ACTIVE after the refusal, got {after['status']}"
        )
        assert after["credit_limit_cents"] == 512999, (
            f"expected the limit untouched at 512999, got {after['credit_limit_cents']}"
        )


class TestOrderCancellationCompensatesCreditExposure:
    """Cents of credit exposure are conserved across create/cancel round trips."""

    def test_submit_then_cancel_returns_the_account_to_zero_exposure(self, api):
        """Cancelling the order credits back exactly the reserved figure, zeroes the
        order's own hold and lifts the account off CREDIT_HOLD.

        PRD: "submitting an order debits credit and cancelling it credits the identical
        amount back, so a submit-then-cancel pair must return both `credit_used_cents`
        and the account's `status` to the values they held before the submission"

        Design: Difficulty/compensating_invariant/order_cancel_restores_account_credit_exposure_to_zero
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=RESERVATION_FOR_120_YARDS
        )
        buyer = make_dealer_buyer_headers(account["id"])

        order = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-01",
                    requested_yards=120.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert order["reserved_credit_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected {RESERVATION_FOR_120_YARDS} reserved, got "
            f"{order['reserved_credit_cents']}"
        )
        held = fixtures.refresh_account(account["id"])
        assert held["credit_used_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected credit_used_cents {RESERVATION_FOR_120_YARDS}, got "
            f"{held['credit_used_cents']}"
        )
        assert held["status"] == "CREDIT_HOLD", (
            f"expected CREDIT_HOLD on the debit, got {held['status']}"
        )

        cancelled = validate_success(
            api.cancel_cut_order(
                order["id"],
                factories.cancel_cut_order_payload(reason="buyer withdrew"),
                buyer,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled['status']}"
        )
        assert cancelled["reserved_credit_cents"] == 0, (
            "a cancelled order carries a reserved_credit_cents of 0, got "
            f"{cancelled['reserved_credit_cents']}"
        )

        released = fixtures.refresh_account(account["id"])
        assert released["credit_used_cents"] == 0, (
            f"expected the exposure back to 0, got {released['credit_used_cents']}"
        )
        assert released["status"] == "ACTIVE", (
            f"expected ACTIVE once usage falls below the limit, got {released['status']}"
        )
        assert_account_credit_conservation(
            released, fixtures.list_orders_for_account(account["id"])
        )

    def test_two_round_trips_each_return_the_ledger_bit_identically(self, api):
        """Two independent create/cancel round trips debit and credit the same 513000
        cents, so the exposure is 0 at every observation point.

        PRD: "An `Account`'s `credit_used_cents` must always equal the sum of
        `reserved_credit_cents` across its orders in status `SUBMITTED`, `ALLOCATED`,
        `BACKORDERED` or `CUT`, plus the sum of `net_invoice_cents` across its orders in
        status `SHIPPED`."

        Design: Difficulty/compensating_invariant/order_cancel_restores_account_credit_exposure_to_zero
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=RESERVATION_FOR_120_YARDS
        )
        buyer = make_dealer_buyer_headers(account["id"])

        for round_index, (order_code, reason) in enumerate(
            (("CO-01", "buyer withdrew"), ("CO-02", "buyer withdrew again")), start=1
        ):
            order = validate_success(
                api.create_cut_order(
                    factories.create_cut_order_payload(
                        account["id"],
                        style["id"],
                        order_code=order_code,
                        requested_yards=120.0,
                        shade_tolerance="ANY",
                    ),
                    PLANNER,
                ),
                expected_status=201,
            )
            assert order["reserved_credit_cents"] == RESERVATION_FOR_120_YARDS, (
                f"round {round_index}: expected {RESERVATION_FOR_120_YARDS} reserved, "
                f"got {order['reserved_credit_cents']}"
            )
            debited = fixtures.refresh_account(account["id"])
            assert debited["credit_used_cents"] == RESERVATION_FOR_120_YARDS, (
                f"round {round_index}: expected credit_used_cents "
                f"{RESERVATION_FOR_120_YARDS}, got {debited['credit_used_cents']}"
            )
            assert debited["status"] == "CREDIT_HOLD", (
                f"round {round_index}: expected CREDIT_HOLD, got {debited['status']}"
            )
            assert_account_credit_conservation(
                debited, fixtures.list_orders_for_account(account["id"])
            )

            validate_success(
                api.cancel_cut_order(
                    order["id"],
                    factories.cancel_cut_order_payload(reason=reason),
                    buyer,
                ),
                expected_status=200,
            )
            credited = fixtures.refresh_account(account["id"])
            assert credited["credit_used_cents"] == 0, (
                f"round {round_index}: expected the exposure back to 0, got "
                f"{credited['credit_used_cents']}"
            )
            assert credited["status"] == "ACTIVE", (
                f"round {round_index}: expected ACTIVE, got {credited['status']}"
            )
            assert credited["credit_limit_cents"] == RESERVATION_FOR_120_YARDS, (
                f"round {round_index}: the limit must not move, got "
                f"{credited['credit_limit_cents']}"
            )
            assert_account_credit_conservation(
                credited, fixtures.list_orders_for_account(account["id"])
            )


class TestAccountCreation:
    def test_account_system_fields_are_minted_by_the_server(self, api):
        """Opening an account returns a server-minted id, timestamps, version 1 and the
        two non-input fields at 0 and ACTIVE.

        PRD: "Every resource the API mints carries an `id` that is a server-generated
        UUID." and "A new account starts with `credit_used_cents` of 0 and `status` of
        `ACTIVE`."

        Design: Corner/entities/account_system_fields_are_generated_by_the_server
        """
        created = validate_success(
            api.create_account(
                factories.create_account_payload(
                    account_code="AC-01",
                    account_type="DEALER",
                    credit_limit_cents=5000000,
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert_account(created)

        assert isinstance(created["id"], str) and created["id"], (
            f"expected a non-empty id, got {created['id']!r}"
        )
        assert created["id"] != "AC-01", (
            "the human-facing account_code must never be the resource identifier, got "
            f"id {created['id']!r}"
        )
        assert is_valid_uuid(created["id"]), (
            f"expected a UUID id, got {created['id']!r}"
        )
        assert is_iso8601_timestamp(created["created_at"]), (
            f"expected an ISO 8601 created_at, got {created['created_at']!r}"
        )
        assert is_iso8601_timestamp(created["updated_at"]), (
            f"expected an ISO 8601 updated_at, got {created['updated_at']!r}"
        )
        assert created["version"] == 1, (
            f"version starts at 1 on creation, got {created['version']}"
        )
        assert created["credit_used_cents"] == 0, (
            f"expected credit_used_cents 0, got {created['credit_used_cents']}"
        )
        assert created["status"] == "ACTIVE", (
            f"expected ACTIVE, got {created['status']}"
        )
        assert created["credit_limit_cents"] == 5000000, (
            f"expected the supplied limit 5000000, got {created['credit_limit_cents']}"
        )
        assert created["account_code"] == "AC-01", (
            f"expected account_code AC-01, got {created['account_code']}"
        )

    def test_patching_the_credit_limit_persists_it_and_bumps_the_version(self, api):
        """A partial amendment moves credit_limit_cents and version only, and the
        re-read returns the persisted row.

        PRD: "An account may be amended, supplying a new `credit_limit_cents`, a new
        `status`, or both." and "Every amendment increments the account's `version` by
        1."

        Design: Corner/endpoints/patching_an_account_credit_limit_updates_it_and_bumps_the_version
        """
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=500000
        )

        patched = validate_success(
            api.update_account(
                account["id"],
                factories.update_account_payload(credit_limit_cents=900000),
                PLANNER,
            ),
            expected_status=200,
        )
        assert patched["credit_limit_cents"] == 900000, (
            f"expected the amended limit 900000, got {patched['credit_limit_cents']}"
        )
        assert patched["version"] == 2, (
            f"expected version 2 after one amendment, got {patched['version']}"
        )
        assert patched["account_code"] == "AC-01", (
            "an untouched key must keep its value, got account_code "
            f"{patched['account_code']}"
        )
        assert patched["credit_used_cents"] == 0, (
            f"the computed ledger must not move, got {patched['credit_used_cents']}"
        )
        assert patched["status"] == "ACTIVE", (
            f"the derived posture must stay ACTIVE, got {patched['status']}"
        )
        assert patched["created_at"] == account["created_at"], (
            f"created_at must not move: was {account['created_at']}, now "
            f"{patched['created_at']}"
        )
        assert patched["updated_at"] >= patched["created_at"], (
            f"updated_at {patched['updated_at']} must not precede created_at "
            f"{patched['created_at']}"
        )

        reread = validate_success(
            api.get_account(account["id"], PLANNER), expected_status=200
        )
        assert reread["credit_limit_cents"] == 900000, (
            f"expected the persisted limit 900000 on re-read, got "
            f"{reread['credit_limit_cents']}"
        )
        assert reread["version"] == 2, (
            f"expected version 2 on re-read, got {reread['version']}"
        )


class TestStyleBackorderPosture:
    def test_backorder_alert_is_inclusive_at_two_hundred_fifty_open_yards(self, api):
        """249.9 open yards leave replenishment_flag NONE while 250.0 raise
        REPLENISH_REQUIRED, and a cancelled order drops out of the sweep entirely.

        PRD: "the style's `replenishment_flag` becomes `REPLENISH_REQUIRED` when that
        figure reaches or exceeds 250 yards and `NONE` when it falls below"

        Design: Corner/calculations/style_backorder_alert_is_inclusive_at_two_hundred_fifty_yards
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=100000000
        )

        first = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-01",
                    requested_yards=249.9,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert first["reserved_credit_cents"] == 1068323, (
            "expected 1068323 reserved for 249.9 yards at 4275 cents, got "
            f"{first['reserved_credit_cents']}"
        )
        assert first["allocated_yards"] == pytest.approx(0, abs=0.01), (
            f"a fresh order starts at 0 allocated yards, got {first['allocated_yards']}"
        )

        below = fixtures.refresh_style(style["id"])
        assert below["open_backorder_yards"] == pytest.approx(249.9, abs=0.01), (
            f"expected open_backorder_yards 249.9, got {below['open_backorder_yards']}"
        )
        assert below["replenishment_flag"] == "NONE", (
            f"249.9 open yards stay below the alert, got {below['replenishment_flag']}"
        )

        cancelled = validate_success(
            api.cancel_cut_order(
                first["id"],
                factories.cancel_cut_order_payload(reason="reduced"),
                PLANNER,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled['status']}"
        )
        emptied = fixtures.refresh_style(style["id"])
        assert emptied["open_backorder_yards"] == pytest.approx(0, abs=0.01), (
            "a cancelled order contributes nothing to the sweep, got "
            f"open_backorder_yards {emptied['open_backorder_yards']}"
        )

        second = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-02",
                    requested_yards=250.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert second["reserved_credit_cents"] == 1068750, (
            "expected 1068750 reserved for 250.0 yards at 4275 cents, got "
            f"{second['reserved_credit_cents']}"
        )
        assert second["status"] == "SUBMITTED", (
            f"expected SUBMITTED, got {second['status']}"
        )

        alerted = fixtures.refresh_style(style["id"])
        assert alerted["open_backorder_yards"] == pytest.approx(250.0, abs=0.01), (
            f"expected open_backorder_yards 250.0, got {alerted['open_backorder_yards']}"
        )
        assert alerted["replenishment_flag"] == "REPLENISH_REQUIRED", (
            "250.0 open yards reach the alert, got "
            f"{alerted['replenishment_flag']}"
        )

        account_after = fixtures.refresh_account(account["id"])
        assert account_after["credit_used_cents"] == 1068750, (
            "only the live order counts in the ledger, got credit_used_cents "
            f"{account_after['credit_used_cents']}"
        )

    def test_credit_used_excludes_cancelled_orders(self, api):
        """A cancelled 513000-cent order leaves no residue, so a later 10.0-yard order
        sees only its own 42750 cents.

        PRD: "Cancelled orders contribute nothing and carry a `reserved_credit_cents` of
        0 after cancellation."

        Design: Corner/calculations/account_credit_used_excludes_cancelled_orders
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=600000
        )

        first = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-01",
                    requested_yards=120.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert first["reserved_credit_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected {RESERVATION_FOR_120_YARDS} reserved, got "
            f"{first['reserved_credit_cents']}"
        )

        first_read = validate_success(
            api.get_account(account["id"], PLANNER), expected_status=200
        )
        assert first_read["credit_used_cents"] == RESERVATION_FOR_120_YARDS, (
            f"expected credit_used_cents {RESERVATION_FOR_120_YARDS}, got "
            f"{first_read['credit_used_cents']}"
        )
        assert first_read["status"] == "ACTIVE", (
            f"513000 sits strictly below the 600000 limit, got {first_read['status']}"
        )

        cancelled = validate_success(
            api.cancel_cut_order(
                first["id"],
                factories.cancel_cut_order_payload(reason="dealer withdrew"),
                PLANNER,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled['status']}"
        )
        assert cancelled["reserved_credit_cents"] == 0, (
            "the cancelled order's own hold is zeroed, got "
            f"{cancelled['reserved_credit_cents']}"
        )

        second_read = validate_success(
            api.get_account(account["id"], PLANNER), expected_status=200
        )
        assert second_read["credit_used_cents"] == 0, (
            f"expected credit_used_cents 0, got {second_read['credit_used_cents']}"
        )

        second = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-02",
                    requested_yards=10.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert second["reserved_credit_cents"] == 42750, (
            "expected 42750 reserved for 10.0 yards at 4275 cents, got "
            f"{second['reserved_credit_cents']}"
        )

        third_read = validate_success(
            api.get_account(account["id"], PLANNER), expected_status=200
        )
        assert third_read["credit_used_cents"] == 42750, (
            f"expected credit_used_cents 42750, got {third_read['credit_used_cents']}"
        )
        assert third_read["status"] == "ACTIVE", (
            f"expected ACTIVE, got {third_read['status']}"
        )


class TestDealerBuyerAccountScope:
    def test_dealer_buyer_reading_a_neighbouring_account_is_scoped_out(self, api):
        """The same GET succeeds for the dealer's own account and is refused with
        ERR_ACCOUNT_SCOPE_VIOLATION for the neighbouring one.

        PRD: "a `DealerBuyer` may only read the account whose `account_id` path segment
        equals its own `X-User-ID`" and "A violation of that scope is rejected with
        `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403)"

        Design: Corner/validations/dealer_buyer_reading_another_account_returns_account_scope_violation
        """
        own = fixtures.create_account(
            account_code="AC-01", account_type="DEALER", credit_limit_cents=5000000
        )
        neighbour = fixtures.create_account(
            account_code="AC-02", account_type="BUILDER", credit_limit_cents=5000000
        )
        buyer = make_dealer_buyer_headers(own["id"])

        cross = api.get_account(neighbour["id"], buyer)
        validate_error(cross, "ERR_ACCOUNT_SCOPE_VIOLATION")

        mine = validate_success(
            api.get_account(own["id"], buyer), expected_status=200
        )
        assert mine["id"] == own["id"], (
            f"expected the dealer's own account {own['id']}, got {mine['id']}"
        )
        assert mine["account_code"] == "AC-01", (
            f"expected account_code AC-01, got {mine['account_code']}"
        )

    def test_dealer_buyer_may_submit_read_and_cancel_only_its_own_order(self, api):
        """The dealer submits, reads and cancels its own order, while a submit naming
        the neighbouring account is scoped out.

        PRD: "may only submit, read or cancel a `CutOrder` whose `account_id` equals its
        own `X-User-ID`"

        Design: Corner/rbac/dealer_buyer_may_submit_and_cancel_only_its_own_order
        """
        style = fixtures.create_active_style()
        own = fixtures.create_account(
            account_code="AC-01", account_type="DEALER", credit_limit_cents=100000000
        )
        neighbour = fixtures.create_account(
            account_code="AC-02", account_type="BUILDER", credit_limit_cents=100000000
        )
        buyer = make_dealer_buyer_headers(own["id"])

        order = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    own["id"],
                    style["id"],
                    order_code="CO-OWN",
                    requested_yards=20.0,
                    shade_tolerance="ANY",
                ),
                buyer,
            ),
            expected_status=201,
        )
        assert order["status"] == "SUBMITTED", (
            f"expected SUBMITTED, got {order['status']}"
        )
        assert order["reserved_credit_cents"] == 85500, (
            "expected 85500 reserved for 20.0 yards at 4275 cents, got "
            f"{order['reserved_credit_cents']}"
        )

        read = validate_success(
            api.get_cut_order(order["id"], buyer), expected_status=200
        )
        assert read["account_id"] == own["id"], (
            f"expected account_id {own['id']}, got {read['account_id']}"
        )

        cross = api.create_cut_order(
            factories.create_cut_order_payload(
                neighbour["id"],
                style["id"],
                order_code="CO-OTHER",
                requested_yards=20.0,
                shade_tolerance="ANY",
            ),
            buyer,
        )
        validate_error(cross, "ERR_ACCOUNT_SCOPE_VIOLATION")

        cancelled = validate_success(
            api.cancel_cut_order(
                order["id"],
                factories.cancel_cut_order_payload(reason="changed mind"),
                buyer,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled['status']}"
        )

        own_after = fixtures.refresh_account(own["id"])
        neighbour_after = fixtures.refresh_account(neighbour["id"])
        assert own_after["credit_used_cents"] == 0, (
            "the cancel releases the dealer's own hold, got credit_used_cents "
            f"{own_after['credit_used_cents']}"
        )
        assert neighbour_after["credit_used_cents"] == 0, (
            "the scoped-out submit never touched the neighbour, got credit_used_cents "
            f"{neighbour_after['credit_used_cents']}"
        )


class TestStyleOrderabilityByOrderType:
    def test_a_runout_style_takes_running_line_but_refuses_custom(self, api):
        """The identical payload differing only in order_type is refused for CUSTOM and
        accepted for RUNNING_LINE against a RUNOUT style.

        PRD: "The style must be in `ACTIVE` or `RUNOUT`, and a `RUNOUT` style refuses an
        `order_type` of `CUSTOM`."

        Design: Corner/validations/a_runout_style_still_takes_running_line_but_refuses_custom
        """
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=100000000
        )

        discontinued = validate_success(
            api.discontinue_style(
                style["id"],
                factories.discontinue_style_payload(reason="collection retired"),
                PLANNER,
            ),
            expected_status=200,
        )
        assert discontinued["status"] == "RUNOUT", (
            f"expected RUNOUT after the discontinue, got {discontinued['status']}"
        )

        custom = api.create_cut_order(
            factories.create_cut_order_payload(
                account["id"],
                style["id"],
                order_code="CO-CUSTOM",
                order_type="CUSTOM",
                requested_yards=40.0,
                shade_tolerance="ANY",
            ),
            PLANNER,
        )
        validate_error(custom, "ERR_STYLE_RUNOUT_NO_CUSTOM")

        running_line = validate_success(
            api.create_cut_order(
                factories.create_cut_order_payload(
                    account["id"],
                    style["id"],
                    order_code="CO-LINE",
                    order_type="RUNNING_LINE",
                    requested_yards=40.0,
                    shade_tolerance="ANY",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert running_line["status"] == "SUBMITTED", (
            f"expected SUBMITTED, got {running_line['status']}"
        )

        still_runout = fixtures.refresh_style(style["id"])
        assert still_runout["status"] == "RUNOUT", (
            "an accepted running-line order must not re-open the style, got "
            f"{still_runout['status']}"
        )


class TestAccountClosure:
    def test_closure_needs_no_open_orders_and_a_closed_account_cannot_order(self, api):
        """Closure is refused while a SUBMITTED order is live, permitted once it is
        cancelled, and the closed account then fails a fresh order with
        ERR_ACCOUNT_CLOSED.

        PRD: "Setting `status` to `CLOSED` is permitted from `ACTIVE` and from
        `CREDIT_HOLD`, and is terminal, but only when the account holds no cut order in
        status `SUBMITTED`, `ALLOCATED`, `BACKORDERED` or `CUT`; an attempt to close an
        account with live orders is refused with `ERR_ACCOUNT_HAS_OPEN_ORDERS`."

        Design: Corner/validations/account_closure_requires_no_open_orders_and_a_closed_account_cannot_order
        """
        admin = make_plant_admin_headers()
        style = fixtures.create_active_style()
        account = fixtures.create_account(
            account_code="AC-01", credit_limit_cents=100000000
        )
        order = fixtures.create_cut_order(
            account["id"],
            style["id"],
            order_code="CO-01",
            requested_yards=40.0,
            shade_tolerance="ANY",
        )

        blocked = api.update_account(
            account["id"], factories.update_account_payload(status="CLOSED"), admin
        )
        validate_error(blocked, "ERR_ACCOUNT_HAS_OPEN_ORDERS")
        still_open = fixtures.refresh_account(account["id"])
        assert still_open["status"] == "ACTIVE", (
            f"the refused closure must leave the account ACTIVE, got "
            f"{still_open['status']}"
        )

        validate_success(
            api.cancel_cut_order(
                order["id"],
                factories.cancel_cut_order_payload(reason="dealer withdrew"),
                PLANNER,
            ),
            expected_status=200,
        )
        released = fixtures.refresh_account(account["id"])
        assert released["credit_used_cents"] == 0, (
            f"expected the hold released to 0, got {released['credit_used_cents']}"
        )

        closed = validate_success(
            api.update_account(
                account["id"], factories.update_account_payload(status="CLOSED"), admin
            ),
            expected_status=200,
        )
        assert closed["status"] == "CLOSED", (
            f"expected CLOSED once no live order remains, got {closed['status']}"
        )

        refused = api.create_cut_order(
            factories.create_cut_order_payload(
                account["id"],
                style["id"],
                order_code="CO-02",
                requested_yards=40.0,
                shade_tolerance="ANY",
            ),
            PLANNER,
        )
        validate_error(refused, "ERR_ACCOUNT_CLOSED")

        codes, meta = _order_codes(api, account["id"])
        assert meta["total_count"] == 1, (
            f"expected only the cancelled CO-01 on file, got total_count "
            f"{meta['total_count']} with codes {codes}"
        )
