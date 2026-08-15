"""Magazine capacity, batch quantities, movement gates, quarantine (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_batch_unit_accountability,
    create_batch_payload,
    create_checkout_payload,
    create_display_payload,
    create_expend_payload,
    create_magazine_payload,
    create_return_payload,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
from test_helpers.fixtures import (
    add_site_plan,
    approve_permit,
    checkout_product,
    create_magazine_with_batch,
    create_operator,
    set_clock,
    setup_event_approved,
    setup_event_in_progress,
    setup_event_submitted,
    submit_permit_application,
)


class TestMagazineCapacity:
    def _setup_magazine_at_60(self, api):
        op, op_headers = create_operator()
        mag = get_success_data(api.create_magazine(create_magazine_payload(), op_headers))
        get_success_data(api.create_batch(
            mag["id"],
            create_batch_payload(product_name="Cake A", shell_diameter_in=2,
                                 quantity_units=60, new_per_unit_lbs=1.00, lot_number="LA"),
            op_headers,
        ))
        return op, op_headers, mag

    def test_magazine_capacity_exact_fit_accepted(self, api):
        """PRD §3.4: "the magazine's `current_new_lbs` plus the incoming
        `quantity_units` times `new_per_unit_lbs` must be less than or equal
        to `capacity_new_lbs`, with an exact fit allowed".

        Design: Difficulty/boundary_precision_check/magazine_capacity_exact_fit
        """
        op, op_headers, mag = self._setup_magazine_at_60(api)
        resp = api.create_batch(
            mag["id"],
            create_batch_payload(product_name="Cake B", shell_diameter_in=2,
                                 quantity_units=40, new_per_unit_lbs=1.00, lot_number="LB"),
            op_headers,
        )
        validate_success(resp, expected_status=201)
        fresh = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert fresh["current_new_lbs"] == 100.00

    def test_magazine_capacity_one_cent_over_rejected(self, api):
        """PRD §3.4: "overflow is rejected with
        `ERR_MAGAZINE_CAPACITY_EXCEEDED`" — 100.00 + 0.01 > 100.00 must fail.

        Design: Difficulty/boundary_precision_check/magazine_capacity_exact_fit
        """
        op, op_headers, mag = self._setup_magazine_at_60(api)
        get_success_data(api.create_batch(
            mag["id"],
            create_batch_payload(product_name="Cake B", shell_diameter_in=2,
                                 quantity_units=40, new_per_unit_lbs=1.00, lot_number="LB"),
            op_headers,
        ))
        resp = api.create_batch(
            mag["id"],
            create_batch_payload(product_name="Cake C", shell_diameter_in=2,
                                 quantity_units=1, new_per_unit_lbs=0.01, lot_number="LC"),
            op_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MAGAZINE_CAPACITY_EXCEEDED)
        assert resp.status_code == 422
        fresh = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert fresh["current_new_lbs"] == 100.00

    def test_magazine_lapsed_blocks_batch_intake(self, api):
        """PRD §2.5: "Receiving new product into a `LAPSED` magazine is
        rejected with `ERR_MAGAZINE_LAPSED`."

        Design: Corner/validations/magazine_lapsed_blocks_batch_intake
        """
        op, op_headers = create_operator()
        mag = get_success_data(api.create_magazine(
            create_magazine_payload(inspection_due_at="2026-09-01T00:00:00Z"),
            op_headers,
        ))
        set_clock("2026-09-02T00:00:00Z")
        resp = api.create_batch(
            mag["id"], create_batch_payload(quantity_units=10), op_headers
        )
        validate_error(resp, ApiErrorId.ERR_MAGAZINE_LAPSED)
        assert resp.status_code == 409


class TestMovementSchemaAndPermitGates:
    def test_movement_zero_quantity_rejected(self, api):
        """PRD §3.4: "Recording a movement on a batch supplies `movement_type` — one of `CHECK_OUT`, `RETURN`, or `EXPEND` — plus `quantity` (greater than zero, else `ERR_INVALID_QUANTITY`) and the `display_event_id` the movement serves."
        PRD §2.8: "Request-schema validation runs third" and "Fourth, existence: path identifiers are resolved left-to-right and body-referenced identifiers (`site_plan_id`, `product_batch_id`, `display_event_id`) must exist, otherwise `ERR_NOT_FOUND`."

        Design: Corner/validations/movement_zero_quantity_rejected
        """
        op, op_headers = create_operator()
        mag, batch = create_magazine_with_batch(op_headers)
        resp = api.create_movement(
            batch["id"],
            create_return_payload("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", 0),
            op_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)
        assert resp.status_code == 400

    def test_checkout_manifest_incomplete_rejected(self, api):
        """PRD §3.4: "`cdl_hazmat_endorsed` must be true — a false value is
        rejected with `ERR_MANIFEST_NOT_COMPLIANT`."

        Design: Corner/validations/checkout_manifest_incomplete_rejected
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        resp = api.create_movement(
            batch["id"],
            create_checkout_payload(ev["id"], 5, cdl_hazmat_endorsed=False),
            op_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_COMPLIANT)
        assert resp.status_code == 422
        fresh = get_success_data(api.get_batch(batch["id"], op_headers))
        assert fresh["qty_at_show"] == 0

    def test_movement_blocked_until_permit_approved_rejected(self, api):
        """PRD §3.4: "the event's permit must already be approved, failing as
        `ERR_PERMIT_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/movement_blocked_until_permit_approved
        """
        op, op_headers, ev, sp, app = setup_event_submitted()
        mag, batch = create_magazine_with_batch(op_headers)
        resp = api.create_movement(
            batch["id"], create_checkout_payload(ev["id"], 10), op_headers
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED)
        assert resp.status_code == 409

    def test_movement_succeeds_after_permit_approved(self, api):
        """PRD §3.4: "the event's permit must already be approved, failing as
        `ERR_PERMIT_NOT_APPROVED`" — after approval the same checkout is
        recorded: "A `CHECK_OUT` of q units ... subtracts q from
        `qty_at_magazine` and adds q to `qty_at_show`."

        Design: Difficulty/cross_entity_state_dependency/movement_blocked_until_permit_approved
        """
        op, op_headers, ev, sp, app = setup_event_submitted()
        mag, batch = create_magazine_with_batch(op_headers)
        approve_permit(app)
        resp = api.create_movement(
            batch["id"], create_checkout_payload(ev["id"], 10), op_headers
        )
        validate_success(resp, expected_status=201)
        fresh = get_success_data(api.get_batch(batch["id"], op_headers))
        assert fresh["qty_at_show"] == 10
        assert fresh["qty_at_magazine"] == 40


class TestCheckoutReturnLoop:
    def test_checkout_moves_quantities_to_show(self, api):
        """PRD §3.4: "A `CHECK_OUT` of q units requires q not to exceed the batch's `qty_at_magazine`, then subtracts q from `qty_at_magazine` and adds q to `qty_at_show`."
        PRD §3.4: "The batch's status is then recomputed — `DEPLETED` when `quantity_remaining` reaches zero, otherwise `CHECKED_OUT` while any units remain at shows, otherwise `IN_MAGAZINE` — unless the batch is `QUARANTINED`, which nothing overrides."

        Design: Difficulty/non_linear_state_machine/product_batch_checkout_return_loop
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 10)
        mid = get_success_data(api.get_batch(batch["id"], op_headers))
        assert mid["status"] == "CHECKED_OUT"
        assert mid["qty_at_show"] == 10
        assert mid["qty_at_magazine"] == 40
        assert_batch_unit_accountability(mid)

    def test_full_return_restores_in_magazine(self, api):
        """PRD §3.4: "A `RETURN` of q requires q not to exceed the batch's `qty_at_show` attributed to the named event, then subtracts q from `qty_at_show` and adds q back to `qty_at_magazine`."
        PRD §3.4: "The batch's status is then recomputed — `DEPLETED` when `quantity_remaining` reaches zero, otherwise `CHECKED_OUT` while any units remain at shows, otherwise `IN_MAGAZINE` — unless the batch is `QUARANTINED`, which nothing overrides."

        Design: Difficulty/non_linear_state_machine/product_batch_checkout_return_loop
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 10)
        get_success_data(api.create_movement(
            batch["id"], create_return_payload(ev["id"], 10), op_headers
        ))
        end = get_success_data(api.get_batch(batch["id"], op_headers))
        assert end["status"] == "IN_MAGAZINE"
        assert end["qty_at_show"] == 0
        assert end["qty_at_magazine"] == 50
        assert end["quantity_remaining"] == 50
        assert_batch_unit_accountability(end)


class TestMagazineMassInvariant:
    def test_checkout_drops_magazine_mass(self, api):
        """PRD §3.4: "Every magazine's `current_new_lbs` is a derived figure: the sum over all its batches — including `QUARANTINED` ones, since quarantined stock still physically occupies the magazine — of each batch's `qty_at_magazine` multiplied by its `new_per_unit_lbs`, rounded half-up to two decimal places."

        Design: Difficulty/compensating_invariant/checkout_return_restores_magazine_mass
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        before = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert before["current_new_lbs"] == 25.00  # 50 x 0.50
        checkout_product(batch, ev, op_headers, 20)
        after = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert after["current_new_lbs"] == 15.00  # 30 x 0.50

    def test_return_restores_magazine_mass_exactly(self, api):
        """PRD §3.4: "Mass conservation is an invariant: a checkout of some
        quantity followed by a return of the same quantity leaves
        `current_new_lbs` bit-identical to its value before the checkout."

        Design: Difficulty/compensating_invariant/checkout_return_restores_magazine_mass
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        checkout_product(batch, ev, op_headers, 20)
        get_success_data(api.create_movement(
            batch["id"], create_return_payload(ev["id"], 20), op_headers
        ))
        restored = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert restored["current_new_lbs"] == 25.00


class TestAllocationRsdGate:
    def _setup_two_batches(self, api):
        op, op_headers, ev, sp, app = setup_event_approved()
        mag = get_success_data(api.create_magazine(create_magazine_payload(), op_headers))
        b4 = get_success_data(api.create_batch(
            mag["id"], create_batch_payload(quantity_units=50, new_per_unit_lbs=0.50,
                                            shell_diameter_in=4, lot_number="L4"),
            op_headers,
        ))
        b5 = get_success_data(api.create_batch(
            mag["id"], create_batch_payload(product_name="Shell 5in", shell_diameter_in=5,
                                            quantity_units=20, new_per_unit_lbs=0.75,
                                            lot_number="L5"),
            op_headers,
        ))
        return op, op_headers, ev, b4, b5

    def test_oversize_candidate_rejected_and_leaves_set_unchanged(self, api):
        """PRD §3.4: "If that candidate distance exceeds the `CURRENT` site
        plan's `spectator_boundary_ft`, the movement is rejected with
        `ERR_FALLOUT_EXCEEDS_BOUNDARY`; otherwise the movement is recorded and
        the batch's `qty_at_show` increases — which may raise the gate for the
        next allocation."

        Design: Difficulty/combinatorial_formula/allocation_rsd_circular_gate
        """
        op, op_headers, ev, b4, b5 = self._setup_two_batches(api)
        ok = api.create_movement(b4["id"], create_checkout_payload(ev["id"], 10), op_headers)
        validate_success(ok, expected_status=201)  # 70 x 4 = 280 <= 300
        bad = api.create_movement(b5["id"], create_checkout_payload(ev["id"], 5), op_headers)
        validate_error(bad, ApiErrorId.ERR_FALLOUT_EXCEEDS_BOUNDARY)  # 70 x 5 = 350 > 300
        fresh5 = get_success_data(api.get_batch(b5["id"], op_headers))
        assert fresh5["qty_at_show"] == 0, "rejected allocation must leave the gating set unchanged"

    def test_gate_evaluated_against_unchanged_set_after_rejection(self, api):
        """PRD §3.4: "The server first forms the candidate maximum diameter:
        the larger of the greatest `shell_diameter_in` among batches currently
        holding net `qty_at_show` above zero for this event (zero if none) and
        the candidate batch's own `shell_diameter_in`."

        Design: Difficulty/combinatorial_formula/allocation_rsd_circular_gate
        """
        op, op_headers, ev, b4, b5 = self._setup_two_batches(api)
        validate_success(api.create_movement(b4["id"], create_checkout_payload(ev["id"], 10), op_headers), expected_status=201)
        validate_error(api.create_movement(b5["id"], create_checkout_payload(ev["id"], 5), op_headers),
                       ApiErrorId.ERR_FALLOUT_EXCEEDS_BOUNDARY)
        ok2 = api.create_movement(b4["id"], create_checkout_payload(ev["id"], 5), op_headers)
        validate_success(ok2, expected_status=201)
        fresh4 = get_success_data(api.get_batch(b4["id"], op_headers))
        assert fresh4["qty_at_show"] == 15


class TestBatchLifecycleAndAvailability:
    def test_expend_beyond_at_show_rejected(self, api):
        """PRD §3.4: "An `EXPEND` of q likewise requires q not to exceed the batch's `qty_at_show` for that event, then subtracts q from `qty_at_show` and adds q to `qty_expended`."
        PRD §3.4: "Availability shortfalls on any of the three are rejected with `ERR_INSUFFICIENT_PRODUCT`."

        Design: Corner/errors/expend_beyond_at_show_rejected
        """
        ctx = setup_event_in_progress(checkout_qty=10)
        resp = api.create_movement(
            ctx["batch"]["id"], create_expend_payload(ctx["ev"]["id"], 11),
            ctx["op_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PRODUCT)
        fresh = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert fresh["fired_count"] == 0

    def test_batch_depleted_terminal_movements_rejected(self, api):
        """PRD §3.4: "The batch's status is then recomputed — `DEPLETED` when
        `quantity_remaining` reaches zero" and "Availability shortfalls on any
        of the three are rejected with `ERR_INSUFFICIENT_PRODUCT`."

        Design: Corner/cross_cutting_layers/batch_depleted_terminal_movements_rejected
        """
        ctx = setup_event_in_progress(
            checkout_qty=10,
            batch_overrides={"quantity_units": 10},
        )
        get_success_data(api.create_movement(
            ctx["batch"]["id"], create_expend_payload(ctx["ev"]["id"], 10),
            ctx["op_headers"],
        ))
        batch = get_success_data(api.get_batch(ctx["batch"]["id"], ctx["op_headers"]))
        assert batch["status"] == "DEPLETED"
        resp = api.create_movement(
            batch["id"], create_expend_payload(ctx["ev"]["id"], 1), ctx["op_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PRODUCT)

    def test_quarantine_blocks_movement(self, api):
        """PRD §3.4: "a batch in `QUARANTINED` rejects every subsequent
        movement with `ERR_BATCH_QUARANTINED`."

        Design: Corner/errors/quarantine_blocks_movement
        """
        op, op_headers, ev, sp, app = setup_event_approved()
        mag, batch = create_magazine_with_batch(op_headers)
        validate_success(api.quarantine_batch(batch["id"], {"reason": "water damage"}, op_headers))
        resp = api.create_movement(
            batch["id"], create_checkout_payload(ev["id"], 5), op_headers
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_QUARANTINED)
        assert resp.status_code == 409

    def test_suspended_operator_blocked_from_writes(self, api):
        """PRD §2.5: "Any action attempted by a `SUSPENDED` operator is
        rejected with `ERR_OPERATOR_SUSPENDED`."

        Design: Corner/errors/suspended_operator_blocked_from_writes
        """
        op, op_headers = create_operator()
        validate_success(api.suspend_operator(op["id"], {"reason": "audit"}, ADMIN))
        resp = api.create_display(create_display_payload(), op_headers)
        validate_error(resp, ApiErrorId.ERR_OPERATOR_SUSPENDED)
        assert resp.status_code == 409


class TestBatchPartitionInvariant:
    def test_expend_partition_step(self, api):
        """PRD §3.4: "unit accountability holds at all times:
        `quantity_units` always equals the sum of `qty_at_magazine`,
        `qty_at_show`, and `qty_expended`."

        Design: Difficulty/compensating_invariant/batch_unit_accountability_partition
        """
        ctx = setup_event_in_progress(checkout_qty=20)
        get_success_data(api.create_movement(
            ctx["batch"]["id"], create_expend_payload(ctx["ev"]["id"], 12),
            ctx["op_headers"],
        ))
        batch = get_success_data(api.get_batch(ctx["batch"]["id"], ctx["op_headers"]))
        assert (batch["qty_at_magazine"], batch["qty_at_show"], batch["qty_expended"]) == (30, 8, 12)
        assert_batch_unit_accountability(batch)
        ev = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert ev["fired_count"] == 12

    def test_return_partition_step(self, api):
        """PRD §3.4: "After every movement, `quantity_remaining` is
        `quantity_units` minus `qty_expended`" and unit accountability holds.

        Design: Difficulty/compensating_invariant/batch_unit_accountability_partition
        """
        ctx = setup_event_in_progress(checkout_qty=20)
        get_success_data(api.create_movement(
            ctx["batch"]["id"], create_expend_payload(ctx["ev"]["id"], 12),
            ctx["op_headers"],
        ))
        get_success_data(api.create_movement(
            ctx["batch"]["id"], create_return_payload(ctx["ev"]["id"], 8),
            ctx["op_headers"],
        ))
        batch = get_success_data(api.get_batch(ctx["batch"]["id"], ctx["op_headers"]))
        assert (batch["qty_at_magazine"], batch["qty_at_show"], batch["qty_expended"]) == (38, 0, 12)
        assert batch["quantity_remaining"] == 38
        assert_batch_unit_accountability(batch)
