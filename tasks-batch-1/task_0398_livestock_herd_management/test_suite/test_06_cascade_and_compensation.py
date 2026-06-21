"""Sale cascade, mortality void, conservation invariants, and sale-time gating."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_pasture,
    create_animal,
    create_weighed_animal,
    create_sale_lot,
    add_ticket,
    setup_lot_with_one_ticket,
    setup_withheld_animal,
    plan_and_apply_movement,
    record_mortality,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
CLERK = TEST_USERS["sale_clerk_headers"]


class TestSellCascade:
    def test_sell_drives_animal_sold(self, api):
        """PRD §3.10: "Selling the lot then cascades to its animals: each linked animal
        transitions from `ACTIVE` to `SOLD`".

        Design: Difficulty/transitive_cascade/sell_cascade_animal_pasture_herd_depth3
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        lot, _ = setup_lot_with_one_ticket(herd["id"], animal["id"], 454.0,
                                           channel="AUCTION", commission_pct=0.05)
        validate_success(api.sell_lot(lot["id"], CLERK))
        animal_after = validate_success(api.get_animal(animal["id"], HM))
        assert animal_after["life_status"] == "SOLD"

    def test_sell_cascade_subtracts_pasture_and_herd_load(self, api):
        """PRD §3.10: "that per-animal transition itself does the inventory bookkeeping
        — setting the animal's `life_status` to `SOLD`, subtracting its AU from its
        `current_pasture_id` pasture's `current_au_load` if it had a location,
        decrementing the herd's `active_animal_count` by one and subtracting the
        animal's AU from the herd's `total_au_load`".

        Design: Difficulty/transitive_cascade/sell_cascade_animal_pasture_herd_depth3
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        lot, _ = setup_lot_with_one_ticket(herd["id"], animal["id"], 454.0,
                                           channel="AUCTION", commission_pct=0.05)
        validate_success(api.sell_lot(lot["id"], CLERK))
        pasture_after = validate_success(api.get_pasture(pen["id"], HM))
        herd_after = validate_success(api.get_herd(herd["id"], HM))
        assert pasture_after["current_au_load"] == 0.0
        assert herd_after["total_au_load"] == 0.0
        assert herd_after["active_animal_count"] == 0


class TestMortalityVoidCascade:
    def test_void_drives_animal_active(self, api):
        """PRD §3.11: "A herd manager may void a `RECORDED` mortality record, moving it
        to `VOIDED`, which cascades to drive the animal from `DEAD` back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/mortality_void_reactivation_depth2
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        mr = record_mortality(animal["id"], died_on="2026-03-30", cause="DISEASE")
        voided = validate_success(api.void_mortality_record(mr["id"], HM))
        assert voided["status"] == "VOIDED"
        animal_after = validate_success(api.get_animal(animal["id"], HM))
        assert animal_after["life_status"] == "ACTIVE"

    def test_void_restores_active_animal_count(self, api):
        """PRD §3.11: "The reactivation restores the animal's `life_status` to `ACTIVE`
        ... increments the herd's `active_animal_count` by one".

        Design: Difficulty/transitive_cascade/mortality_void_reactivation_depth2
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        mr = record_mortality(animal["id"], died_on="2026-03-30", cause="DISEASE")
        validate_success(api.void_mortality_record(mr["id"], HM))
        herd_after = validate_success(api.get_herd(herd["id"], HM))
        assert herd_after["active_animal_count"] == 1


class TestConservationInvariants:
    def test_pasture_au_conserved_apply_then_revert(self, api):
        """PRD §2.10: "reverting an applied movement restores the animal's prior
        location and undoes the AU attribution on both pastures ... the invariant is
        conservation: the herd's `active_animal_count` and `total_au_load`, and each
        pasture's `current_au_load`, must return to values consistent with the set of
        live animals and applied movements after the reversal".

        Design: Difficulty/compensating_invariant/pasture_au_conservation_apply_then_revert
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen_a = create_pasture(kind="PEN", capacity_au=10)
        pen_b = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], pen_a["id"], "2026-03-21T00:00:00Z")
        mv2 = plan_and_apply_movement(animal["id"], pen_b["id"], "2026-03-22T00:00:00Z")
        reverted = validate_success(api.revert_movement(mv2["id"], HM))
        assert reverted["status"] == "REVERTED"
        pen_b_after = validate_success(api.get_pasture(pen_b["id"], HM))
        pen_a_after = validate_success(api.get_pasture(pen_a["id"], HM))
        animal_after = validate_success(api.get_animal(animal["id"], HM))
        assert pen_b_after["current_au_load"] == 0.0
        assert pen_a_after["current_au_load"] == 1.0
        assert animal_after["current_pasture_id"] == pen_a["id"]

    def test_herd_total_au_load_unchanged_by_apply_revert(self, api):
        """PRD §2.10: "the invariant is conservation: the herd's `active_animal_count`
        and `total_au_load`, and each pasture's `current_au_load`, must return to values
        consistent with the set of live animals and applied movements after the
        reversal, exactly as if the reversed event had never occurred."

        Design: Difficulty/compensating_invariant/pasture_au_conservation_apply_then_revert
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen_a = create_pasture(kind="PEN", capacity_au=10)
        pen_b = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], pen_a["id"], "2026-03-21T00:00:00Z")
        herd_before = validate_success(api.get_herd(herd["id"], HM))
        mv2 = plan_and_apply_movement(animal["id"], pen_b["id"], "2026-03-22T00:00:00Z")
        validate_success(api.revert_movement(mv2["id"], HM))
        herd_after = validate_success(api.get_herd(herd["id"], HM))
        # The animal is still ACTIVE in the herd throughout; its AU never left the herd.
        assert herd_after["total_au_load"] == 1.0
        assert herd_after["total_au_load"] == herd_before["total_au_load"]

    def test_headcount_conserved_mortality_then_void(self, api):
        """PRD §2.10: "Voiding a mortality record reactivates the animal and restores
        the herd counters it had decremented ... the invariant is conservation: the
        herd's `active_animal_count` ... must return to values consistent with the set
        of live animals ... exactly as if the reversed event had never occurred."

        Design: Difficulty/compensating_invariant/herd_headcount_conservation_mortality_then_void
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        a1 = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        mr = record_mortality(a1["id"], died_on="2026-03-30", cause="ACCIDENT")
        voided = validate_success(api.void_mortality_record(mr["id"], HM))
        assert voided["status"] == "VOIDED"
        a1_after = validate_success(api.get_animal(a1["id"], HM))
        herd_after = validate_success(api.get_herd(herd["id"], HM))
        assert a1_after["life_status"] == "ACTIVE"
        assert herd_after["active_animal_count"] == 2

    def test_herd_total_au_load_restored_by_mortality_void(self, api):
        """PRD §3.11: "The reactivation restores the animal's `life_status` to `ACTIVE`
        ... increments the herd's `active_animal_count` by one, adds the animal's AU
        back to the herd's `total_au_load`".

        Design: Difficulty/compensating_invariant/herd_headcount_conservation_mortality_then_void
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        a1 = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        before = validate_success(api.get_herd(herd["id"], HM))
        assert before["total_au_load"] == 1.0
        mr = record_mortality(a1["id"], died_on="2026-03-30", cause="ACCIDENT")
        validate_success(api.void_mortality_record(mr["id"], HM))
        after = validate_success(api.get_herd(herd["id"], HM))
        assert after["total_au_load"] == 1.0


class TestEmptyLotBoundary:
    def test_sell_empty_lot_rejected(self, api):
        """PRD §3.10: "The sale requires at least one ticket — selling a lot whose
        `head_count` is 0 is rejected with `ERR_EMPTY_LOT`".

        Design: Difficulty/boundary_precision_check/sell_empty_lot_zero_head_count
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        lot = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        resp = api.sell_lot(lot["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_EMPTY_LOT.value)

    def test_sell_lot_with_one_ticket_succeeds_head_count_one(self, api):
        """PRD §3.10: "The sale requires at least one ticket — selling a lot whose
        `head_count` is 0 is rejected with `ERR_EMPTY_LOT`".

        Design: Difficulty/boundary_precision_check/sell_empty_lot_zero_head_count
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15")
        lot, _ = setup_lot_with_one_ticket(herd["id"], animal["id"], 500.0,
                                           channel="AUCTION", commission_pct=0.05)
        sold = validate_success(api.sell_lot(lot["id"], CLERK))
        assert sold["status"] == "SOLD"
        assert sold["head_count"] == 1


class TestTicketGating:
    def test_ticket_withheld_animal_rejected(self, api):
        """PRD §3.9: "The animal must be saleable: its `life_status` must be `ACTIVE`
        and its `meat_clearance_status` must be `CLEAR` at ticket time, so a withheld
        animal is rejected with `ERR_WITHDRAWAL_NOT_CLEARED`".

        Design: Difficulty/cross_entity_state_dependency/ticket_requires_animal_meat_clear
        """
        set_clock("2026-05-01T00:00:00Z")
        herd, animal, _, _ = setup_withheld_animal()
        lot = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        resp = api.add_ticket(
            lot["id"],
            {"animal_id": animal["id"], "gross_weight_kg": 500.0,
             "expected_sale_lot_version": lot["version"]},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_CLEARED.value)

    def test_ticket_clear_animal_succeeds(self, api):
        """PRD §3.9: "The animal must be saleable: its `life_status` must be `ACTIVE`
        and its `meat_clearance_status` must be `CLEAR` at ticket time, so a withheld
        animal is rejected with `ERR_WITHDRAWAL_NOT_CLEARED`".

        Design: Difficulty/cross_entity_state_dependency/ticket_requires_animal_meat_clear
        """
        set_clock("2026-05-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-04-20")
        lot = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        ticket = validate_success(
            api.add_ticket(
                lot["id"],
                {"animal_id": animal["id"], "gross_weight_kg": 500.0,
                 "expected_sale_lot_version": lot["version"]},
                CLERK,
            ),
            expected_status=201,
        )
        assert ticket["animal_id"] == animal["id"]

    def test_animal_on_two_open_lots_rejected(self, api):
        """PRD §3.9: "an animal may sit on at most one open lot at a time — attempting
        to ticket an animal that is already attached to another open lot is rejected
        with `ERR_ANIMAL_ALREADY_LISTED`."

        Design: Corner/validations/animal_on_two_open_lots_returns_already_listed
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15")
        lot1, _ = setup_lot_with_one_ticket(herd["id"], animal["id"], 500.0,
                                            channel="AUCTION", commission_pct=0.05)
        lot2 = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        resp = api.add_ticket(
            lot2["id"],
            {"animal_id": animal["id"], "gross_weight_kg": 500.0,
             "expected_sale_lot_version": lot2["version"]},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_ANIMAL_ALREADY_LISTED.value)

    def test_ticket_animal_wrong_herd_rejected(self, api):
        """PRD §3.9: "The ticketed animal must belong to the same herd as the lot's
        `herd_id`; a mismatch is rejected with `ERR_HERD_MISMATCH`."

        Design: Corner/validations/ticket_animal_wrong_herd_returns_herd_mismatch
        """
        set_clock("2026-04-01T00:00:00Z")
        herd_a = create_herd(species="CATTLE")
        herd_b = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd_a["id"], 500.0, weighed_at="2026-03-15")
        lot_b = create_sale_lot(herd_b["id"], channel="AUCTION", commission_pct=0.05)
        resp = api.add_ticket(
            lot_b["id"],
            {"animal_id": animal["id"], "gross_weight_kg": 500.0,
             "expected_sale_lot_version": lot_b["version"]},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_HERD_MISMATCH.value)


class TestSaleLotTerminalState:
    def test_sell_already_sold_lot_rejected(self, api):
        """PRD §3.10: "A sell or withdraw requested on a lot that is not `OPEN` fails
        the state check with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sell_already_sold_lot_returns_invalid_state
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15")
        lot, _ = setup_lot_with_one_ticket(herd["id"], animal["id"], 500.0,
                                           channel="AUCTION", commission_pct=0.05)
        validate_success(api.sell_lot(lot["id"], CLERK))
        resp = api.sell_lot(lot["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestTicketOptimisticConcurrency:
    def test_ticket_add_stale_lot_version_rejected(self, api):
        """PRD §2.6: "If the lot's current `version` has advanced beyond that value —
        because another writer has already attached a ticket (legitimately changing
        `head_count` and the lot's pricing basis) or withdrawn the lot — the client's
        view of the lot is stale and the create is rejected with `ERR_STALE_VERSION`".

        Design: Corner/cross_cutting_complexity_layers/occ_ticket_add_stale_lot_version_returns_412
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        a1 = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15")
        a2 = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15")
        lot = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        stale_version = lot["version"]
        add_ticket(lot["id"], a1["id"], 500.0, stale_version)
        resp = api.add_ticket(
            lot["id"],
            {"animal_id": a2["id"], "gross_weight_kg": 500.0,
             "expected_sale_lot_version": stale_version},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
