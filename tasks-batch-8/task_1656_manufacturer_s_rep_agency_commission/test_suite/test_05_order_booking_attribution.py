"""Order booking gates and split attribution (PRD §3.4, §2.8).

Covers the computed line-field initialization at booking, the linked-entity and
shape gates on order creation, the attribution waterfall's HOUSE fallback, the
registration-state dependency of attribution, and the split override contract.
"""
from test_helpers import (
    ApiErrorId,
    approve_registration,
    cancel_order,
    create_customer,
    create_order,
    create_order_payload,
    create_rep,
    get_order,
    invoice_order,
    list_splits,
    make_order_line,
    put_splits_payload,
    setup_base_scenario,
    ship_order,
    splits_for_line,
    submit_registration,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = None  # populated lazily inside tests via TEST_USERS


def _admin():
    return TEST_USERS["agency_admin_headers"]


class TestBookingInitialization:
    def test_order_creation_initializes_computed_line_fields(self, api):
        """PRD §3.4: "At creation the system initializes each line's `shipped_qty`
        and `returned_qty` to zero and its `applied_rate_bp`, `commission_cents`, and
        `protected_registration_id` to null — the rate and commission stay unknown
        until invoice. The fulfillment timestamps `shipped_at`, `invoiced_at`, and
        `paid_at` likewise remain null until the corresponding event occurs."
        PRD §3.4: "A fresh order is `PLACED` and `ATTRIBUTED`."

        Design: Corner/entities/order_creation_initializes_computed_line_fields
        """
        base = setup_base_scenario()
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=5, unit_price_cents=5000)],
        )
        assert order["fulfillment_status"] == "PLACED"
        assert order["commission_status"] == "ATTRIBUTED"
        line = order_line(order, "L1")
        assert line["shipped_qty"] == 0
        assert line["returned_qty"] == 0
        assert line["applied_rate_bp"] is None
        assert line["commission_cents"] is None
        assert line["protected_registration_id"] is None
        assert order["shipped_at"] is None
        assert order["invoiced_at"] is None
        assert order["paid_at"] is None


class TestBookingGates:
    def test_unknown_family_code_rejected(self, api):
        """PRD §3.4: "An `ACTIVE` rate schedule must exist
        (`ERR_NO_ACTIVE_RATE_SCHEDULE`), and every line's `family_code` must appear in
        that schedule's `family_rates` (`ERR_UNKNOWN_FAMILY_CODE`)."

        Design: Corner/validations/unknown_family_code_rejected
        """
        base = setup_base_scenario(reps=(("R1", ["CA", "OR"]),))
        resp = api.create_order(
            create_order_payload(
                base["customer"]["id"], base["principal"]["id"], "PO-X",
                lines=[make_order_line(family_code="WIDGETS", quantity=1,
                                       unit_price_cents=1000)],
            ),
            _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_FAMILY_CODE, expected_status=422)
        _data, meta = validate_paginated(
            api.list_orders(_admin(), params={"principal_id": base["principal"]["id"]})
        )
        assert meta["total_count"] == 0, "rejected order must not be persisted"

    def test_territory_not_covered_rejected(self, api):
        """PRD §3.4: "The principal's single `ACTIVE` agreement must exist
        (`ERR_AGREEMENT_NOT_ACTIVE`), and every line's specifying and ship-to
        territories must fall inside that agreement's `territory_codes`
        (`ERR_TERRITORY_NOT_COVERED`)."

        Design: Corner/validations/territory_not_covered_rejected
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"], reps=())
        cz = create_customer(name="CZ", spec_territory_code="ZZ", ship_to_territory_code="ZZ")
        resp = api.create_order(
            create_order_payload(
                cz["id"], base["principal"]["id"], "PO-Z",
                lines=[make_order_line(quantity=1, unit_price_cents=1000)],
            ),
            _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_COVERED)

    def test_future_dated_order_rejected(self, api):
        """PRD §3.4: "The `placed_at` timestamp may not lie in the future relative to
        the logical clock (`ERR_FUTURE_DATED`)."

        Design: Corner/validations/future_dated_order_rejected
        """
        base = setup_base_scenario(
            agreement_territories=["CA", "OR", "WA"], reps=(("R1", ["CA", "OR", "WA"]),),
        )
        future = api.create_order(
            create_order_payload(
                base["customer"]["id"], base["principal"]["id"], "PO-F",
                placed_at="2026-08-02T00:00:00Z",
                lines=[make_order_line(quantity=1, unit_price_cents=1000)],
            ),
            _admin(),
        )
        validate_error(future, ApiErrorId.ERR_FUTURE_DATED, expected_status=422)

        # Boundary is inclusive: placed_at exactly equal to the clock is accepted.
        at_clock = api.create_order(
            create_order_payload(
                base["customer"]["id"], base["principal"]["id"], "PO-EQ",
                placed_at="2026-08-01T00:00:00Z",
                lines=[make_order_line(quantity=1, unit_price_cents=1000)],
            ),
            _admin(),
        )
        data = validate_success(at_clock, expected_status=201)
        assert data["external_order_ref"] == "PO-EQ"

    def test_duplicate_external_ref_rejected_and_reusable_after_cancel(self, api):
        """PRD §3.4: "The `external_order_ref` must be unique among this principal's
        orders that are not `CANCELLED` (`ERR_DUPLICATE_EXTERNAL_REF`) — a cancelled
        order frees its reference for reuse."

        Design: Corner/validations/duplicate_external_ref_rejected_and_reusable_after_cancel
        """
        base = setup_base_scenario(
            agreement_territories=["CA", "OR", "WA"], reps=(("R1", ["CA", "OR", "WA"]),),
        )
        first = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-DUP",
            lines=[make_order_line(quantity=1, unit_price_cents=1000)],
        )
        dup = api.create_order(
            create_order_payload(
                base["customer"]["id"], base["principal"]["id"], "PO-DUP",
                lines=[make_order_line(quantity=2, unit_price_cents=1000)],
            ),
            _admin(),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF)

        cancel_order(first["id"])
        reused = api.create_order(
            create_order_payload(
                base["customer"]["id"], base["principal"]["id"], "PO-DUP",
                lines=[make_order_line(quantity=2, unit_price_cents=1000)],
            ),
            _admin(),
        )
        data = validate_success(reused, expected_status=201)
        assert data["external_order_ref"] == "PO-DUP"


class TestAttributionWaterfall:
    def test_house_residual_when_no_rep_covers(self, api):
        """PRD §3.4: "if neither resolves, a `HOUSE` row with a null `rep_id` takes
        the full share. House shares accrue to the house itself — no ledger entry is
        ever posted for a null-`rep_id` row."

        Design: Corner/calculations/house_residual_when_no_rep_covers
        """
        base = setup_base_scenario(
            agreement_territories=["CA", "OR", "WA", "FL"],
            customer_spec="FL", customer_ship="FL",
        )
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-H",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        splits = list_splits(order_id=order["id"])
        assert len(splits) == 1, f"expected a single HOUSE row, got {splits}"
        assert splits[0]["role"] == "HOUSE"
        assert splits[0]["rep_id"] is None
        assert splits[0]["share_bp"] == 10000

        ship_order(order["id"], base["principal"]["id"])
        invoiced = invoice_order(order["id"], base["principal"]["id"])
        line = order_line(invoiced, "L1")
        assert line["commission_cents"] == 5000, (
            "commission is computed (500,000c x 1000bp) even when unassigned"
        )
        _entries, meta = validate_paginated(
            api.list_commission_entries(_admin(), params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0, "no ledger entry is posted for a HOUSE row"

    def test_order_placed_before_approval_gets_no_registration(self, api):
        """PRD §3.4: "Booking immediately runs the attribution waterfall" and "When
        the line matches a protected registration per §3.3, a single `REGISTERED` row
        grants the registering rep the agreement's `registered_protection_share_bp`".
        PRD §3.3: "A line is considered protected for commission purposes when an
        `APPROVED` registration exists whose `principal_id`, `customer_id`, and
        `family_code` all match the order and line, and whose window contains the
        order's `placed_at`". A merely SUBMITTED registration is not APPROVED, so an
        order booked before approval attributes by territory instead.

        Design: Difficulty/cross_entity_state_dependency/order_attribution_requires_approved_registration
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1, r2 = base["reps"]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Gate")
        assert reg["status"] == "SUBMITTED"

        early = create_order(
            customer["id"], principal["id"], "PO-EARLY",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        rows = splits_for_line(list_splits(order_id=early["id"]), "L1")
        by_role = {row["role"]: row for row in rows}
        assert set(by_role) == {"SPECIFY", "SHIP_TO"}, (
            "a SUBMITTED registration must not drive attribution"
        )
        assert by_role["SPECIFY"]["rep_id"] == r1["id"]
        assert by_role["SPECIFY"]["share_bp"] == 6000
        assert by_role["SHIP_TO"]["rep_id"] == r2["id"]
        assert by_role["SHIP_TO"]["share_bp"] == 4000
        assert order_line(get_order(early["id"]), "L1")["protected_registration_id"] is None

    def test_order_placed_after_approval_gets_registered_split(self, api):
        """PRD §3.4: "When the line matches a protected registration per §3.3, a
        single `REGISTERED` row grants the registering rep the agreement's
        `registered_protection_share_bp`, and any residual share falls to a `HOUSE`
        row; the line's `protected_registration_id` records which registration
        matched." Approval after an earlier booking does not re-attribute that
        booking — the re-attribution paths of §3.3 run only when protection ends.

        Design: Difficulty/cross_entity_state_dependency/order_attribution_requires_approved_registration
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1, r2 = base["reps"]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Gate")
        early = create_order(
            customer["id"], principal["id"], "PO-EARLY",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        approve_registration(reg["id"], principal["id"])

        late = create_order(
            customer["id"], principal["id"], "PO-LATE",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        rows = splits_for_line(list_splits(order_id=late["id"]), "L1")
        assert len(rows) == 1 and rows[0]["role"] == "REGISTERED"
        assert rows[0]["rep_id"] == r1["id"]
        assert rows[0]["share_bp"] == 10000, (
            "registered_protection_share_bp 10000 leaves no residual HOUSE row"
        )
        assert order_line(get_order(late["id"]), "L1")["protected_registration_id"] == reg["id"]

        # No retroactivity: the pre-approval order keeps its territory splits.
        early_rows = splits_for_line(list_splits(order_id=early["id"]), "L1")
        assert {row["role"] for row in early_rows} == {"SPECIFY", "SHIP_TO"}
        assert order_line(get_order(early["id"]), "L1")["protected_registration_id"] is None


class TestSplitOverride:
    def test_put_splits_sum_invalid_rejected(self, api):
        """PRD §3.4: "The replacement rows must cover every line of the order, and
        each line's shares must sum to exactly 10,000 basis points — a shortfall, an
        overage, or an uncovered line fails with `ERR_SPLIT_SUM_INVALID`."

        Design: Corner/validations/put_splits_sum_invalid_rejected
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        r1 = base["reps"][0]
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[
                make_order_line("L1", quantity=10, unit_price_cents=5000),
                make_order_line("L2", quantity=4, unit_price_cents=5000),
            ],
        )
        before = get_order(order["id"])
        resp = api.put_order_splits(
            order["id"],
            put_splits_payload(
                [
                    {"line_id": "L1", "rep_id": r1["id"], "share_bp": 9000},
                    {"line_id": "L2", "rep_id": r1["id"], "share_bp": 10000},
                ],
                before["version"],
            ),
            _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_SPLIT_SUM_INVALID, expected_status=422)
        assert get_order(order["id"])["version"] == before["version"], (
            "a rejected override must not replace any split rows"
        )
        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        assert {row["role"] for row in rows} == {"SPECIFY", "SHIP_TO"}

    def test_put_splits_locked_after_invoice(self, api):
        """PRD §3.4: "The override is permitted only while the order's commission
        dimension is still `ATTRIBUTED`; once the order has been invoiced the attempt
        fails with `ERR_SPLITS_LOCKED`."

        Design: Corner/validations/put_splits_locked_after_invoice
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        r1, r2 = base["reps"]
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        ship_order(order["id"], base["principal"]["id"])
        invoice_order(order["id"], base["principal"]["id"])
        current = get_order(order["id"])

        resp = api.put_order_splits(
            order["id"],
            put_splits_payload(
                [{"line_id": "L1", "rep_id": r1["id"], "share_bp": 10000}],
                current["version"],
            ),
            _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_SPLITS_LOCKED)
        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        by_role = {row["role"]: row for row in rows}
        assert by_role["SPECIFY"]["rep_id"] == r1["id"]
        assert by_role["SPECIFY"]["share_bp"] == 6000
        assert by_role["SHIP_TO"]["rep_id"] == r2["id"]
        assert by_role["SHIP_TO"]["share_bp"] == 4000

    def test_occ_put_splits_stale_version(self, api):
        """PRD §2.8: "Overriding an order's splits with
        `PUT /rep-agency/orders/{orderId}/splits` requires the request to carry
        `expected_order_version`, the caller's last observed `version` of the order.
        If the order's current `version` no longer matches, the override is rejected
        with `ERR_STALE_ORDER_VERSION` (HTTP 412): the split rows the client
        negotiated against have since been replaced."
        PRD §3.4: "A successful override replaces all prior rows for the order with
        rows whose `role` is `OVERRIDE` and whose `is_override` is true, and
        increments the order's `version` by one."

        Design: Corner/cross_cutting_layers/occ_put_splits_stale_version
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        r1, r2 = base["reps"]
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        v0 = order["version"]

        first = api.put_order_splits(
            order["id"],
            put_splits_payload(
                [{"line_id": "L1", "rep_id": r1["id"], "share_bp": 10000}], v0,
            ),
            _admin(),
        )
        rows = validate_success(first)
        assert len(rows) == 1
        assert rows[0]["role"] == "OVERRIDE"
        assert rows[0]["is_override"] is True
        assert rows[0]["rep_id"] == r1["id"]
        assert rows[0]["share_bp"] == 10000
        assert get_order(order["id"])["version"] == v0 + 1

        stale = api.put_order_splits(
            order["id"],
            put_splits_payload(
                [{"line_id": "L1", "rep_id": r2["id"], "share_bp": 10000}], v0,
            ),
            _admin(),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION, expected_status=412)

        # The first override persists untouched after the stale rejection.
        persisted = splits_for_line(list_splits(order_id=order["id"]), "L1")
        assert len(persisted) == 1
        assert persisted[0]["role"] == "OVERRIDE"
        assert persisted[0]["rep_id"] == r1["id"]
        assert get_order(order["id"])["version"] == v0 + 1
