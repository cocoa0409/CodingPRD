"""Plant onboarding, permit lifecycle, and the settlement calendar (PRD §3.1, §3.2, §3.9)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_batch,
    assert_odor_event,
    assert_permit,
    assert_plant,
    assert_sales_order,
    assert_settlement,
    close_settlement,
    confirm_odor_event,
    create_active_contract,
    create_active_permit,
    create_draft_agreement,
    create_odor_event,
    create_order,
    create_plant,
    create_supplier,
    create_vehicle,
    create_walkin_batch,
    get_settlement,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PM2 = TEST_USERS["plant_manager_2_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
REG = TEST_USERS["regulator_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
SH = TEST_USERS["scalehouse_operator_headers"]
SM = TEST_USERS["sales_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FA2 = TEST_USERS["finance_analyst_2_headers"]
ANY = TEST_USERS["any_headers"]


class TestPlantOnboarding:
    def test_plant_create_returns_defaults_and_auto_settlement(self, api):
        """PRD §3.1: "A new plant starts with `posture` `OPERATING`, an `odor_score` of 1000
        on its 0-to-1000 scale, and `current_period_index` 1."
        PRD §3.1: "Creation also opens the plant's first `PeriodSettlement`: `period_index`
        1, status `OPEN`, with `pickup_fees_accrued_cents`, `product_revenue_cents`,
        `energy_costs_cents`, `transport_costs_cents`, and `confirmed_odor_events` all zero."

        Design: Corner/entities/plant_create_returns_defaults_and_auto_settlement
        """
        from test_helpers import create_plant_payload

        res = api.create_plant(
            create_plant_payload(cooker_capacity=3, standard_cost_cents_per_lb=38), PM
        )
        plant = validate_success(res, 201)
        assert_plant(plant)
        assert plant["posture"] == "OPERATING"
        assert plant["odor_score"] == 1000
        assert plant["current_period_index"] == 1

        settlement = get_settlement(plant["id"], period_index=1)
        assert_settlement(settlement)
        assert settlement["period_index"] == 1
        assert settlement["status"] == "OPEN"
        assert settlement["pickup_fees_accrued_cents"] == 0
        assert settlement["product_revenue_cents"] == 0
        assert settlement["energy_costs_cents"] == 0
        assert settlement["transport_costs_cents"] == 0
        assert settlement["confirmed_odor_events"] == 0

    def test_plant_get_nonexistent_returns_not_found(self, api):
        """PRD §2.9: "Every identifier in the path must exist, then every foreign-key
        identifier in the body must exist, validated left-to-right — path first, then body
        fields in their declared order. The first missing resource yields its specific 404:
        `ERR_PLANT_NOT_FOUND`, ..."

        Design: Corner/entities/plant_get_nonexistent_returns_not_found
        """
        res = api.get_plant(NON_EXISTENT_UUID, ANY)
        validate_error(res, ApiErrorId.ERR_PLANT_NOT_FOUND, expected_status=404)

    def test_decommissioned_plant_blocks_mutation(self, api):
        """PRD §2.7: "A `DECOMMISSIONED` plant rejects every mutation with
        `ERR_PLANT_DECOMMISSIONED` (HTTP 409); decommissioning is terminal."
        PRD §3.1: "The plant's history remains readable."

        Design: Corner/errors/decommissioned_plant_blocks_mutation
        """
        plant = create_plant()
        decommissioned = validate_success(api.decommission_plant(plant["id"], PM), 200)
        assert decommissioned["posture"] == "DECOMMISSIONED"

        res = api.create_vehicle(
            {"plant_id": plant["id"], "vehicle_tag": "V1", "capacity_lbs": 40000,
             "duty_class": "DUAL"},
            RD,
        )
        validate_error(res, ApiErrorId.ERR_PLANT_DECOMMISSIONED, expected_status=409)

        fetched = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert fetched["posture"] == "DECOMMISSIONED"


class TestPermitLifecycle:
    def test_permit_reinstate_from_active_rejected(self, api):
        """PRD §3.2: "A `Regulator` may reinstate it provided it is `SUSPENDED` (otherwise
        `ERR_PERMIT_INVALID_STATE`) and its `expires_on` is still on or after the current
        logical date (otherwise `ERR_PERMIT_INVALID_STATE`)."

        Design: Corner/state_machines/permit_reinstate_from_active_rejected
        """
        plant = create_plant()
        permit = create_active_permit(plant["id"])
        assert permit["status"] == "ACTIVE"

        res = api.reinstate_permit(permit["id"], REG)
        validate_error(res, ApiErrorId.ERR_PERMIT_INVALID_STATE, expected_status=409)

        fetched = validate_success(api.get_permit(permit["id"], ANY), 200)
        assert fetched["status"] == "ACTIVE"

    def test_permit_expiry_at_advance_suspends_plant(self, api):
        """PRD §3.9: "Advancement is also when permit expiry is processed: any `ACTIVE`
        permit whose `expires_on` is now earlier than the current logical date becomes
        `EXPIRED`, dropping the plant to `SUSPENDED` with the route, stop, batch, and fee
        cascade of §2.7."

        Design: Corner/endpoints/permit_expiry_at_advance_suspends_plant
        """
        plant = create_plant()
        permit = create_active_permit(plant["id"], expires_on="2026-08-15")
        assert permit["status"] == "ACTIVE"

        # Advance the logical clock past the permit's expiry date (PRD §2.5).
        set_clock("2026-08-20T00:00:00Z")
        close_settlement(plant["id"], period_index=1)

        advanced = validate_success(api.advance_period(plant["id"], FA), 200)
        assert advanced["current_period_index"] == 2
        assert advanced["posture"] == "SUSPENDED"

        permit = validate_success(api.get_permit(permit["id"], ANY), 200)
        assert_permit(permit)
        assert permit["status"] == "EXPIRED"


class TestSettlementCalendar:
    def test_advance_period_full_checkpoint_effects(self, api):
        """PRD §3.9: "Advancement increments the plant's `current_period_index` by one,
        creates a fresh `OPEN` settlement for the new period with all accumulators at zero,
        and resets the plant's `ACTIVE` permit's `confirmed_violation_count` to zero."
        PRD §3.9: "if the just-closed settlement recorded zero `confirmed_odor_events`, the
        plant's `odor_score` increases by 50, never exceeding the 1000 cap"

        Design: Corner/endpoints/advance_period_full_checkpoint_effects
        """
        plant = create_plant()
        permit = create_active_permit(plant["id"], odor_event_threshold=5)
        # One confirmed MEDIUM event: score 1000 - 100 = 900, permit violation count 1.
        event = create_odor_event(plant["id"], severity="MEDIUM")
        confirm_odor_event(event["id"])

        permit_mid = validate_success(api.get_permit(permit["id"], ANY), 200)
        assert permit_mid["confirmed_violation_count"] == 1

        close_settlement(plant["id"], period_index=1)
        advanced = validate_success(api.advance_period(plant["id"], FA), 200)
        assert advanced["current_period_index"] == 2
        # Period 1 recorded one confirmed odor event, so no recovery applies.
        assert advanced["odor_score"] == 900
        assert advanced["posture"] == "OPERATING"

        permit_after = validate_success(api.get_permit(permit["id"], ANY), 200)
        assert permit_after["confirmed_violation_count"] == 0
        assert permit_after["status"] == "ACTIVE"

        settlement2 = get_settlement(plant["id"], period_index=2)
        assert settlement2["status"] == "OPEN"
        assert settlement2["pickup_fees_accrued_cents"] == 0
        assert settlement2["product_revenue_cents"] == 0
        assert settlement2["energy_costs_cents"] == 0
        assert settlement2["transport_costs_cents"] == 0
        assert settlement2["confirmed_odor_events"] == 0

        settlement1 = get_settlement(plant["id"], period_index=1)
        assert settlement1["status"] == "CLOSED"

    def test_ops_run_checkpoint_requires_closed_settlement(self, api):
        """PRD §3.9: "Advancing the settlement calendar is the plant's operational
        checkpoint, performed by a `FinanceAnalyst`, and it is gated: the settlement of the
        current period must be `CLOSED`, or advancement is rejected with
        `ERR_SETTLEMENT_NOT_CLOSED`."

        Design: Corner/complexity_layers/ops_run_checkpoint_requires_closed_settlement
        """
        plant = create_plant()
        # Period-1 settlement is still OPEN: advancement is refused.
        res = api.advance_period(plant["id"], FA)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_CLOSED, expected_status=409)
        plant_mid = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert plant_mid["current_period_index"] == 1

        close_settlement(plant["id"], period_index=1)
        advanced = validate_success(api.advance_period(plant["id"], FA), 200)
        assert advanced["current_period_index"] == 2

    def test_settlement_close_reopen_close_finalize_cycle(self, api):
        """PRD §3.9: "A `FinanceAnalyst` closes a settlement from `OPEN` or `REOPENED` (any
        other state: `ERR_SETTLEMENT_INVALID_STATE`), recording `closed_by` and moving it to
        `CLOSED`."
        PRD §3.9: "reopening clears `closed_by` and returns the settlement to `REOPENED`,
        from which it can be closed again under the same rule."
        PRD §3.9: "a `PlantManager` finalizes a `CLOSED` settlement, and the finalizer must
        differ from the recorded `closed_by` (`ERR_SOD_VIOLATION`). `FINALIZED` is terminal."

        Design: Corner/state_machines/settlement_close_reopen_close_finalize_cycle
        """
        plant = create_plant()
        settlement = get_settlement(plant["id"], period_index=1)

        closed = validate_success(api.close_settlement(settlement["id"], FA), 200)
        assert closed["status"] == "CLOSED"
        assert closed["closed_by"] == "fa-1"

        reopened = validate_success(api.reopen_settlement(settlement["id"], PM), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["closed_by"] is None

        closed2 = validate_success(api.close_settlement(settlement["id"], FA2), 200)
        assert closed2["status"] == "CLOSED"
        assert closed2["closed_by"] == "fa-2"

        finalized = validate_success(api.finalize_settlement(settlement["id"], PM), 200)
        assert finalized["status"] == "FINALIZED"

    def test_settlement_double_close_rejected(self, api):
        """PRD §3.9: "A `FinanceAnalyst` closes a settlement from `OPEN` or `REOPENED` (any
        other state: `ERR_SETTLEMENT_INVALID_STATE`), recording `closed_by` and moving it to
        `CLOSED`."

        Design: Corner/validations/settlement_double_close_rejected
        """
        plant = create_plant()
        settlement = get_settlement(plant["id"], period_index=1)
        closed = validate_success(api.close_settlement(settlement["id"], FA), 200)
        assert closed["status"] == "CLOSED"

        res = api.close_settlement(settlement["id"], FA)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE, expected_status=409)

        fetched = validate_success(api.get_period_settlement(settlement["id"], ANY), 200)
        assert fetched["status"] == "CLOSED"
        assert fetched["closed_by"] == "fa-1"


class TestInitialStates:
    def test_entities_boot_in_initial_states(self, api):
        """PRD §3.3: "A new agreement is `DRAFT`, and the server records the caller as
        `created_by`."
        PRD §3.5: "Every new batch starts `RECEIVED` with `screening_result` `PENDING`,
        `reserved_lbs` zero, `consumed_lbs` zero, `remaining_lbs` equal to its `weight_lbs`,
        and `screened_by` null until screening."
        PRD §3.8: "A new order is `DRAFT`, and its creation increments the contract's
        `version` by one."
        PRD §3.2: "the event starts `REPORTED` with the caller recorded as `reported_by`
        and `permit_id` null."

        Design: Corner/state_machines/entities_boot_in_initial_states
        """
        plant = create_plant()
        supplier = create_supplier(plant["id"])
        agreement = create_draft_agreement(plant["id"], supplier["id"])
        assert agreement["status"] == "DRAFT"

        contract = create_active_contract(plant["id"])
        order = create_order(contract["id"], plant["id"])
        assert_sales_order(order)
        assert order["status"] == "DRAFT"

        batch = create_walkin_batch(plant["id"], supplier["id"], agreement["id"])
        assert_batch(batch)
        assert batch["status"] == "RECEIVED"

        event = create_odor_event(plant["id"])
        assert_odor_event(event)
        assert event["status"] == "REPORTED"
        assert event["reported_by"] == "co-1"
        assert event["permit_id"] is None
