"""Reman order lifecycle: creation defaults, kit reservation, assembly and
calibration gates, spec pinning / resync OCC, and cancellation."""
import pytest

from test_helpers import (
    ADMIN,
    ANY_H,
    CAL_A,
    CAL_B,
    PLANNER,
    TECH,
    ApiErrorId,
    assert_hard_part_availability,
    assert_reman_order,
    book_dyno_window,
    complete_assembly,
    create_full_pump_model,
    create_hard_part_record,
    create_mapping,
    create_min_model,
    create_order,
    create_resync_payload,
    draft_calibration,
    drive_order_to_calibration,
    drive_order_to_shipped,
    get_invoice_for_order,
    get_order,
    get_part,
    kit_reserve,
    record_dyno_run,
    set_clock,
    api_client,
    validate_error,
    validate_success,
)


class TestOrderCreation:

    def test_order_create_applies_system_defaults(self):
        """PRD §3.2: "A new order starts in `QUEUED` status with `core_settlement_status` `PENDING`, `cal_status` `NONE`, `cal_generation` at 0, `dyno_attempts_used` at 0, `surcharge_labor_minutes` at 0, and `shortage_parts` and `reserved_parts` both empty."
        PRD §2.10: "records the then-current `spec_version` as `model_spec_version_pin`."

        Design: Corner/entities/order_create_applies_system_defaults
        """
        model = create_min_model()
        resp = api_client.create_reman_order(
            {"transmission_model_id": model["id"], "buyer_ref": "BUYER-1"},
            PLANNER,
        )
        data = validate_success(resp, expected_status=201)
        assert_reman_order(data)
        assert data["status"] == "QUEUED"
        assert data["cal_status"] == "NONE"
        assert data["cal_generation"] == 0
        assert data["core_settlement_status"] == "PENDING"
        assert data["dyno_attempts_used"] == 0
        assert data["surcharge_labor_minutes"] == 0
        assert data["reserved_parts"] == []
        assert data["shortage_parts"] == []
        assert data["model_spec_version_pin"] == 1, \
            "pin must record the fresh model's spec_version (1)"


class TestTransitionGates:

    def test_complete_assembly_from_queued_rejected(self):
        """PRD §3.3: "a `RemanTechnician` marks assembly complete, moving the order from `ASSEMBLY` to `CALIBRATION`; against any other status the attempt fails with `ERR_ORDER_NOT_READY_FOR_ASSEMBLY`."

        Design: Corner/state_machines/complete_assembly_from_queued_rejected
        """
        model = create_min_model()
        order = create_order(model["id"], "BUYER-1")
        assert order["status"] == "QUEUED"
        resp = api_client.complete_assembly(order["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_READY_FOR_ASSEMBLY)
        after = get_order(order["id"])
        assert after["status"] == "QUEUED", "rejected transition must not move the order"

    def test_verify_without_draft_rejected(self):
        """PRD §3.3: "verification requires the order to be in one of those two statuses (`ERR_ORDER_NOT_READY_FOR_CALIBRATION`), a calibration currently in `DRAFT` (`ERR_CAL_NOT_DRAFT`)".

        Design: Corner/state_machines/verify_without_draft_rejected
        """
        model = create_min_model()
        order = drive_order_to_calibration(model["id"])
        assert order["status"] == "CALIBRATION"
        assert order["cal_status"] == "NONE"
        resp = api_client.verify_calibration(order["id"], CAL_B)
        validate_error(resp, ApiErrorId.ERR_CAL_NOT_DRAFT)
        after = get_order(order["id"])
        assert after["status"] == "CALIBRATION"
        assert after["cal_status"] == "NONE"

    def test_cancel_shipped_order_rejected(self):
        """PRD §3.3: "A `RemanPlanner` may cancel while the order is `QUEUED`, `PART_HOLD`, `ASSEMBLY`, or `CALIBRATION`; at any later stage the request is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_shipped_order_rejected
        """
        _model, order, _invoice = drive_order_to_shipped()
        assert order["status"] == "SHIPPED"
        resp = api_client.cancel_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        after = get_order(order["id"])
        assert after["status"] == "SHIPPED"


class TestSpecPinningAndResync:

    def test_resync_stale_version_rejected(self):
        """PRD §2.7: "Re-pinning an order to its model's current specification requires `expected_reman_order_version` matching the order's current `version`" and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §2.7: "Successful gated writes themselves advance `version` by 1, so a retry with the same expected version fails."

        Design: Corner/complexity_layers/occ_stale_version_on_spec_resync_rejected
        """
        model = create_min_model()
        order = create_order(model["id"], "BUYER-1")
        created_version = order["version"]
        upd = api_client.update_transmission_model(
            model["id"], {"required_parts": [{"part_family": "PUMP", "qty": 1}]},
            ADMIN)
        validate_success(upd)

        first = api_client.resync_spec(order["id"],
                                       create_resync_payload(created_version),
                                       PLANNER)
        data = validate_success(first)
        assert data["version"] == created_version + 1, \
            "a successful resync increments the order's version by 1"
        assert data["model_spec_version_pin"] == 2, \
            "resync must re-pin to the model's current spec_version (2 after one update)"

        replay = api_client.resync_spec(order["id"],
                                        create_resync_payload(created_version),
                                        PLANNER)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        after = get_order(order["id"])
        assert after["version"] == created_version + 1, \
            "the rejected replay must not advance the order version"

    def test_model_update_bumps_spec_order_keeps_pin(self):
        """PRD §2.10: "A model's `spec_version` starts at 1 on creation and increments by exactly 1 on every update; the update also increments the model's `version`."
        PRD §2.10: "Later model updates never rewrite an existing order's pin — deposits, labor guides, dyno targets, and kit contents are all judged against the snapshot."

        Design: Corner/complexity_layers/spec_update_bumps_version_and_order_keeps_pin
        """
        model = create_min_model()
        order = create_order(model["id"], "BUYER-1")
        resp = api_client.update_transmission_model(
            model["id"], {"required_parts": [{"part_family": "PUMP", "qty": 1}]},
            ADMIN)
        updated_model = validate_success(resp)
        assert updated_model["spec_version"] == 2

        after = get_order(order["id"])
        assert after["model_spec_version_pin"] == 1, \
            "the existing order's pin must stay at the creation-time spec_version"
        assert after["pinned_spec"]["required_parts"] == [], \
            "the pinned snapshot must not be rewritten by the model update"


class TestKitReserveImmediateConsistency:

    def test_kit_reserve_response_reflects_mutation_immediately(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.2: "the picks are recorded in `reserved_parts` as lines of `hard_part_id`, `part_family`, `qty`, and `tier`, `shortage_parts` clears to empty, and the order advances `QUEUED` → `ASSEMBLY` with its `version` incremented by 1."

        Design: Corner/consistency_model/kit_reserve_response_reflects_mutation_immediately
        """
        model = create_full_pump_model(required_qty=2)
        part = create_hard_part_record(qty_on_hand=5)
        create_mapping(part["id"], model["id"], "DIRECT")
        order = create_order(model["id"], "BUYER-1")

        resp = api_client.kit_reserve(order["id"], PLANNER)
        data = validate_success(resp)
        assert data["status"] == "ASSEMBLY"
        assert data["version"] == order["version"] + 1
        assert data["shortage_parts"] == []
        assert len(data["reserved_parts"]) == 1
        line = data["reserved_parts"][0]
        assert line["hard_part_id"] == part["id"]
        assert line["part_family"] == "PUMP"
        assert line["qty"] == 2
        assert line["tier"] == "DIRECT"
        assert data["surcharge_labor_minutes"] == 0, \
            "a DIRECT pick adds no surcharge (only ADAPTED picks add 30)"


class TestReserveCancelConservation:
    """Reserve then cancel: the paired actions net to zero availability drift."""

    def _kitted_order(self):
        model = create_full_pump_model(required_qty=2)
        part = create_hard_part_record(qty_on_hand=5)
        create_mapping(part["id"], model["id"], "DIRECT")
        order = create_order(model["id"], "BUYER-1")
        return model, part, order

    def test_reserve_drops_availability(self):
        """PRD §3.2: "When every line resolves, each pick increments its part's `qty_reserved` by the reserved quantity".
        PRD §2.9: "A hard part's `availability` — the read-only difference between `qty_on_hand` and `qty_reserved`".

        Design: Difficulty/compensating_invariant/part_reserve_cancel_release_conserves_availability
        """
        _model, part, order = self._kitted_order()
        before = get_part(part["id"])
        assert before["qty_on_hand"] == 5 and before["qty_reserved"] == 0
        assert_hard_part_availability(before)

        resp = api_client.kit_reserve(order["id"], PLANNER)
        validate_success(resp)
        mid = get_part(part["id"])
        assert mid["qty_on_hand"] == 5
        assert mid["qty_reserved"] == 2
        assert mid["availability"] == 3
        assert_hard_part_availability(mid)

    def test_cancel_restores_availability(self):
        """PRD §3.3: "Cancelling from `ASSEMBLY` releases every reserved line, decrementing each part's `qty_reserved`, and fires the promotion scan."
        PRD §2.9: "`qty_reserved` changes through kit reservation, promotion, release on cancellation or engineering review, and consumption at ship."

        Design: Difficulty/compensating_invariant/part_reserve_cancel_release_conserves_availability
        """
        _model, part, order = self._kitted_order()
        kit_reserve(order["id"])
        mid = get_part(part["id"])
        assert mid["qty_reserved"] == 2 and mid["availability"] == 3

        resp = api_client.cancel_order(order["id"], PLANNER)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

        after = get_part(part["id"])
        assert after["qty_on_hand"] == 5
        assert after["qty_reserved"] == 0, "cancel must release the reservation"
        assert after["availability"] == 5, \
            "reserve + release must net to zero availability drift"
        assert_hard_part_availability(after)


class TestVerifyPriorityPair:
    """Segregation of duties outranks draft staleness on verification."""

    def _stale_draft_order(self, hours=100):
        model = create_min_model()
        order = drive_order_to_calibration(model["id"])
        draft_calibration(order["id"])  # drafted by cal-a at the default clock
        # advance the logical clock past the 72-hour draft-age cap
        set_clock("2026-08-05T04:00:00Z" if hours == 100 else "2026-08-04T01:00:00Z")
        return order

    def test_sod_beats_staleness(self):
        """PRD §2.8: "On calibration verification, a missing header surfaces before the state gate, the state gate surfaces before the segregation-of-duties check, and segregation surfaces before draft staleness."
        PRD §3.3: "a verifier whose `X-User-ID` differs from `cal_created_by_id` (`ERR_SOD_VERIFICATION_FORBIDDEN`)".

        Design: Difficulty/priority_pair_validation_conflict/verify_cal_sod_beats_staleness
        """
        order = self._stale_draft_order(hours=100)
        resp = api_client.verify_calibration(order["id"], CAL_A)  # drafter == verifier
        validate_error(resp, ApiErrorId.ERR_SOD_VERIFICATION_FORBIDDEN)
        after = get_order(order["id"])
        assert after["cal_status"] == "DRAFT", \
            "the rejected verification must not move the calibration out of DRAFT"

    def test_staleness_fires_when_sod_satisfied(self):
        """PRD §3.3: "a draft whose age from `cal_created_at` to the current logical time is at most 72 hours (`ERR_CAL_STALE`)".

        Design: Difficulty/priority_pair_validation_conflict/verify_cal_sod_beats_staleness
        """
        order = self._stale_draft_order(hours=73)
        resp = api_client.verify_calibration(order["id"], CAL_B)  # different verifier
        validate_error(resp, ApiErrorId.ERR_CAL_STALE)
        after = get_order(order["id"])
        assert after["cal_status"] == "DRAFT"

    def test_calibration_stale_rejected(self):
        """PRD §3.3: "a draft whose age from `cal_created_at` to the current logical time is at most 72 hours (`ERR_CAL_STALE`)".
        PRD §2.8: "a calibration draft must be at most 72 hours old at verification (`ERR_CAL_STALE`)".

        Design: Corner/errors/calibration_stale_rejected
        """
        order = self._stale_draft_order(hours=100)
        resp = api_client.verify_calibration(order["id"], CAL_B)
        validate_error(resp, ApiErrorId.ERR_CAL_STALE)
        after = get_order(order["id"])
        assert after["cal_status"] == "DRAFT", \
            "a stale-draft rejection must leave the calibration untouched"
