"""Requests that break two rules at once, to fix which error the client sees.

Checks are evaluated in one global ascending order, so a request breaking both an
option-load cap and a labour ceiling, or both a concurrency token and a lifecycle
state, or both a scope rule and a state rule, must report the earlier rule only.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    ApiErrorId,
    BuildSlotStatus,
    CancelReason,
    DeliveryCallStatus,
    ModelVariantStatus,
    SupplierStatus,
    approx2,
    base_plant,
    bom_line_payload,
    cancel_call,
    make_supplier_portal_headers,
    new_delivery_call,
    new_shift_plan,
    new_supplier,
    plain_variant,
    planned_slot,
    read_call,
    read_shift_plan,
    read_slot,
    read_station,
    read_supplier,
    read_variant,
    record_arrival_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOptionLoadOutranksLabourCapacity:
    """Rule 29 fires before rule 31 on the same sequencing request."""

    def _overloaded_line(self, api):
        """Two 700-minute variants against a two-operator plan.

        Staffing two operators against a baseline of twenty makes the cap
        floor(5 x 0.63 x 10 x 0.1000) = 3, while 700 gross minutes commit 784
        against the 480 the shift affords.
        """
        plant = base_plant(api)
        heavy = plain_variant(api, plant, "WM-H", 8, 700,
                              option_codes=["OPT-A", "OPT-B", "OPT-C"],
                              qty_per_unit=1)
        light = plain_variant(api, plant, "WM-G", 3, 700, option_codes=["OPT-A"],
                              qty_per_unit=1)
        plant.shift_plan = new_shift_plan(api, plant.line_id, planned_headcount=2)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z", heavy["id"])
        planned_slot(api, plant, 2, "2026-08-03T07:30:00Z", light["id"])
        return plant

    def test_a_candidate_breaching_both_reports_the_option_load_window(self, api):
        """Eight option points over a cap of three hide the labour overflow.

        "Every rolling five-slot window containing the candidate index must satisfy
        the option-load cap when a slot is sequenced — otherwise
        `ERR_OPTION_LOAD_WINDOW_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/option_load_window_outranks_labor_capacity
        """
        plant = self._overloaded_line(api)

        validate_error(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_OPTION_LOAD_WINDOW_EXCEEDED,
            expected_status=422,
        )

        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.PLANNED.value
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 0

    def test_a_candidate_inside_the_cap_finally_reports_the_labour_ceiling(self, api):
        """Three option points clear rule 29, so rule 31 becomes visible.

        "The covering shift plan's recomputed `committed_labor_minutes` must not
        exceed its `available_labor_minutes` when a slot is sequenced — otherwise
        `ERR_LABOR_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/option_load_window_outranks_labor_capacity
        """
        plant = self._overloaded_line(api)

        validate_error(
            api.sequence_build_slot(plant.slot_id(2), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_LABOR_CAPACITY_EXCEEDED,
            expected_status=422,
        )

        assert read_slot(api, plant.slot_id(2))["status"] == BuildSlotStatus.PLANNED.value
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 0


class TestStaleTokenOutranksVariantState:
    """Rule 7 fires before rule 14 when authoring a bill-of-materials line."""

    def _obsolete_variant_plant(self, api):
        plant = base_plant(api)
        validate_success(
            api.obsolete_model_variant(plant.variant_id, PLANT_ADMIN_HEADERS)
        )
        return plant

    def test_a_stale_version_wins_over_the_obsolete_variant(self, api):
        """The version the client still holds is checked first, at 412.

        "Second, because the ladder is global, a stale concurrency token (rule 7)
        always beats a business-rule violation such as a duplicate code (rule 32), and
        a role violation (rule 2) always beats a missing foreign key (rule 5)."

        Design: Difficulty/priority_pair_validation_conflict/stale_variant_version_outranks_obsolete_variant_state
        """
        plant = self._obsolete_variant_plant(api)
        version_from_create = plant.variant["version"]

        validate_error(
            api.create_bom_line(
                bom_line_payload(plant.variant_id, plant.part_id, plant.st20_id,
                                 version_from_create, "POS-TRIM", qty_per_unit=1,
                                 effective_from_sequence=1),
                ENGINEERING_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_STALE_MODEL_VARIANT_VERSION,
            expected_status=412,
        )

        variant = read_variant(api, plant.variant_id)
        assert variant["version"] == 4
        assert variant["status"] == ModelVariantStatus.OBSOLETE.value

    def test_the_current_version_then_reveals_the_obsolete_state(self, api):
        """With the fresh version the state rule is reached, at 409.

        "The governing model variant must be `RELEASED` for build-slot sequencing,
        build-slot release, unit certification and engineering-change cut-in; for
        bill-of-materials authoring it must merely not be `OBSOLETE`, because a
        `DRAFT` variant is precisely where its bill of materials is built up."

        Design: Difficulty/priority_pair_validation_conflict/stale_variant_version_outranks_obsolete_variant_state
        """
        plant = self._obsolete_variant_plant(api)
        current_version = read_variant(api, plant.variant_id)["version"]

        validate_error(
            api.create_bom_line(
                bom_line_payload(plant.variant_id, plant.part_id, plant.st20_id,
                                 current_version, "POS-TRIM", qty_per_unit=1,
                                 effective_from_sequence=1),
                ENGINEERING_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_MODEL_NOT_RELEASED,
            expected_status=409,
        )

        _rows, meta = validate_paginated(
            api.list_bom_lines(PLANT_ADMIN_HEADERS,
                               {"model_variant_id": plant.variant_id})
        )
        assert meta["total_count"] == 1


class TestSupplierScopeOutranksCallState:
    """Rule 6 fires before rule 9 on arrival recording."""

    def _cancelled_call(self, api):
        plant = base_plant(api)
        rival = new_supplier(api, "SUP2", "Rival Modules Ltd",
                             sync_window_minutes=45)
        plant.suppliers["SUP2"] = rival
        call = new_delivery_call(
            api, plant.supplier_id, plant.part_id, plant.st10_id,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z", sequenced_qty=4,
        )
        cancel_call(api, call["id"])
        return plant, rival, call

    def test_a_foreign_supplier_is_refused_for_scope_not_for_state(self, api):
        """The rival portal caller never learns the call was cancelled.

        "A `SupplierPortal` caller may act only on rows whose `supplier_id` equals
        `X-User-ID` — otherwise `ERR_SUPPLIER_SCOPE_VIOLATION`. This applies to
        arrival recording, the single-supplier read, the delivery-call list and the
        part list."

        Design: Difficulty/priority_pair_validation_conflict/supplier_scope_outranks_invalid_call_state
        """
        plant, rival, call = self._cancelled_call(api)

        validate_error(
            api.record_arrival(
                call["id"], record_arrival_payload("2026-08-03T09:15:00Z"),
                make_supplier_portal_headers(rival["id"]),
            ),
            ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION,
            expected_status=403,
        )

        assert float(read_supplier(api, rival["id"])["on_time_score"]) == approx2(100.00)
        assert read_supplier(api, rival["id"])["status"] == SupplierStatus.APPROVED.value

    def test_the_owning_supplier_gets_the_state_error_and_scores_nothing(self, api):
        """The owner passes the scope rule and lands on the state rule, at 409.

        "The target entity is in a state from which the requested transition exists,
        on every action endpoint, including cross-dimension guards such as shipping
        requiring a certified quality status — otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/supplier_scope_outranks_invalid_call_state
        """
        plant, _rival, call = self._cancelled_call(api)

        validate_error(
            api.record_arrival(
                call["id"], record_arrival_payload("2026-08-03T09:15:00Z"),
                make_supplier_portal_headers(plant.supplier_id),
            ),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        cancelled = read_call(api, call["id"])
        assert cancelled["status"] == DeliveryCallStatus.CANCELLED.value
        assert cancelled["cancel_reason"] == CancelReason.PLANNER.value
        assert cancelled["arrived_at"] is None
        assert cancelled["lateness_minutes"] is None
        assert float(read_supplier(api, plant.supplier_id)["on_time_score"]) == approx2(100.00)
