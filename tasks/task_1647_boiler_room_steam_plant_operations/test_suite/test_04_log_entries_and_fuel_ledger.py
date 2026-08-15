"""Boiler log entries: append-only shape, segregation of duties, draft
exclusion, double-verify rejection, immediate consistency, and the
compensating fuel ledger."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_fuel_ledger_invariant,
    assert_log_entry,
    create_and_verify_log_entry,
    create_boiler,
    create_draft_log_entry,
    create_plant,
    deliver_fuel,
    get_boiler,
    get_plant,
    make_operator_headers,
    setup_plant_with_operators,
    validate_error,
    validate_success,
)


class TestAppendOnlyShape:
    def test_boiler_log_entry_common_fields_false_immutable(
        self, api, plant_manager_headers
    ):
        """PRD §2.5: "Three record types are append-only journal entries and
        deliberately carry a reduced property set: BoilerLogEntry,
        ChemistryLog, and FuelDelivery each have `id` and `created_at` only.
        Both `updated_at` and `version` are absent on these three types."

        Design: Corner/entities/boiler_log_entry_common_fields_false_immutable
        """
        plant, ops = setup_plant_with_operators(name="Imm Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-IMM")
        resp = api.create_log_entry(
            plant["id"], boiler["id"],
            {
                "recorded_by_operator_id": ops[0]["id"],
                "recorded_at": "2026-08-05T10:00:00Z",
                "header_pressure_reading_psi": 150,
                "steam_generated_lb": 1000,
                "fuel_burned_gal": 8,
                "feedwater_intake_gal": 130,
                "blowdown_gal": 10,
            },
            make_operator_headers(ops[0]["id"]),
        )
        entry = validate_success(resp, expected_status=201)
        assert_log_entry(entry)
        assert entry["status"] == "DRAFT"


class TestSegregationOfDuties:
    def test_sod_verification_same_operator_rejected(
        self, api, plant_manager_headers
    ):
        """PRD §3.2: "Verification of a boiler log entry is reserved for the
        `Operator` role, and the verifying operator must not be the entry's
        recorder — a self-verification attempt is refused with
        `ERR_SOD_VERIFICATION`."

        Design: Corner/state_machines/sod_verification_same_operator_rejected
        """
        plant, ops = setup_plant_with_operators(name="SoD Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-SOD")
        op = ops[0]
        entry = create_draft_log_entry(plant["id"], boiler["id"], op["id"])

        current = get_boiler(plant["id"], boiler["id"])
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry["id"], current["version"],
            make_operator_headers(op["id"]),  # recorder == verifier
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VERIFICATION)


class TestDraftExclusion:
    def test_combustion_efficiency_excludes_draft_entries(
        self, api, plant_manager_headers
    ):
        """PRD §3.5: "A new entry is born `DRAFT` and has no ledger effect
        whatsoever". PRD §3.1: "`efficiency_pct` remains unset until the first
        efficiency calculation runs."

        Design: Corner/calculations/combustion_efficiency_excludes_draft_entries
        """
        plant, ops = setup_plant_with_operators(name="Filt Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-FILT")
        create_draft_log_entry(
            plant["id"], boiler["id"], ops[0]["id"],
            steam_generated_lb=10000, fuel_burned_gal=80,
            feedwater_intake_gal=1300, blowdown_gal=100,
        )

        boiler_state = get_boiler(plant["id"], boiler["id"])
        assert boiler_state["total_steam_lb"] == 0
        assert boiler_state["total_fuel_burned_gal"] == 0
        assert boiler_state["total_blowdown_gal"] == 0
        assert boiler_state["total_feedwater_gal"] == 0
        assert boiler_state["efficiency_pct"] is None
        assert get_plant(plant["id"])["total_fuel_consumed_gal"] == 0


class TestDoubleVerify:
    def test_log_entry_double_verify_returns_invalid_state(
        self, api, plant_manager_headers
    ):
        """PRD §3.5: "Both `VERIFIED` and `VOIDED` are terminal states for an
        entry." PRD §2.7: "State — the target resource is in a valid from-state
        for the requested transition; otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/log_entry_double_verify_returns_invalid_state
        """
        plant, ops = setup_plant_with_operators(name="DV Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-DV")
        deliver_fuel(plant["id"], 1000)
        entry = create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            steam_generated_lb=1000, fuel_burned_gal=8,
            feedwater_intake_gal=130, blowdown_gal=10,
        )
        assert entry["status"] == "VERIFIED"

        # Fresh OCC version so the state check is what fires.
        current = get_boiler(plant["id"], boiler["id"])
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry["id"], current["version"],
            make_operator_headers(ops[1]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        reread = validate_success(
            api.get_log_entry(
                plant["id"], boiler["id"], entry["id"], plant_manager_headers
            )
        )
        assert reread["status"] == "VERIFIED"
        # Not re-applied: boiler totals unchanged.
        after = get_boiler(plant["id"], boiler["id"])
        assert after["total_steam_lb"] == pytest.approx(1000)
        assert after["total_fuel_burned_gal"] == pytest.approx(8)


class TestImmediateConsistency:
    def test_immediate_visibility_of_verify_effects(
        self, api, plant_manager_headers
    ):
        """PRD §3.5: "On verification, the plant's `total_fuel_consumed_gal`
        grows by the entry's `fuel_burned_gal` and `fuel_inventory_gal` is
        recomputed; the boiler's `total_steam_lb`, `total_fuel_burned_gal`,
        `total_blowdown_gal`, and `total_feedwater_gal` each grow by the
        entry's corresponding figure". The very next read reflects these
        effects.

        Design: Corner/consistency_model/immediate_visibility_of_verify_effects
        """
        plant, ops = setup_plant_with_operators(name="Imm2 Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-I2")
        deliver_fuel(plant["id"], 1000)
        entry = create_draft_log_entry(
            plant["id"], boiler["id"], ops[0]["id"],
            steam_generated_lb=5000, fuel_burned_gal=40,
            feedwater_intake_gal=650, blowdown_gal=50,
        )
        current = get_boiler(plant["id"], boiler["id"])
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry["id"], current["version"],
            make_operator_headers(ops[1]["id"]),
        )
        validate_success(resp, expected_status=200)

        boiler_state = get_boiler(plant["id"], boiler["id"])
        assert boiler_state["total_steam_lb"] == pytest.approx(5000)
        assert boiler_state["total_fuel_burned_gal"] == pytest.approx(40)
        assert boiler_state["total_blowdown_gal"] == pytest.approx(50)
        assert boiler_state["total_feedwater_gal"] == pytest.approx(650)
        plant_state = get_plant(plant["id"])
        assert plant_state["total_fuel_consumed_gal"] == pytest.approx(40)
        assert plant_state["fuel_inventory_gal"] == pytest.approx(960)


class TestFuelInventoryBoundary:
    def test_verify_to_exactly_zero_inventory_succeeds(
        self, api, plant_manager_headers
    ):
        """PRD §2.10: "`fuel_inventory_gal` always equals
        `total_fuel_received_gal` minus `total_fuel_consumed_gal`, and it may
        never go negative." A verification landing exactly on zero is not
        negative, so it succeeds.

        Design: Difficulty/boundary_precision_check/fuel_inventory_zero_boundary
        """
        plant, ops = setup_plant_with_operators(name="Fuel Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-F")
        deliver_fuel(plant["id"], 100)
        entry = create_draft_log_entry(
            plant["id"], boiler["id"], ops[0]["id"],
            steam_generated_lb=10000, fuel_burned_gal=100,
            feedwater_intake_gal=1300, blowdown_gal=100,
        )
        current = get_boiler(plant["id"], boiler["id"])
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry["id"], current["version"],
            make_operator_headers(ops[1]["id"]),
        )
        verified = validate_success(resp, expected_status=200)
        assert verified["status"] == "VERIFIED"

        plant_state = get_plant(plant["id"])
        assert plant_state["fuel_inventory_gal"] == pytest.approx(0)
        assert plant_state["total_fuel_consumed_gal"] == pytest.approx(100)
        assert_fuel_ledger_invariant(plant_state)

    def test_verify_driving_inventory_negative_rejected(
        self, api, plant_manager_headers
    ):
        """PRD §2.10: "The plant's fuel oil is a compensating ledger with a
        hard invariant: `fuel_inventory_gal` always equals
        `total_fuel_received_gal` minus `total_fuel_consumed_gal`, and it may
        never go negative." The only catalogue error covering this invariant
        is `ERR_FUEL_INVENTORY_UNDERFLOW` (PRD §5: HTTP 422).

        Design: Difficulty/boundary_precision_check/fuel_inventory_zero_boundary
        """
        plant, ops = setup_plant_with_operators(name="Fuel2 Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-F2")
        deliver_fuel(plant["id"], 100)
        # First verify drains the tank to exactly zero.
        create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            steam_generated_lb=10000, fuel_burned_gal=100,
            feedwater_intake_gal=1300, blowdown_gal=100,
        )
        assert get_plant(plant["id"])["fuel_inventory_gal"] == pytest.approx(0)

        # Second verify would push the ledger to -1: rejected.
        entry2 = create_draft_log_entry(
            plant["id"], boiler["id"], ops[0]["id"],
            recorded_at="2026-08-05T11:00:00Z",
            steam_generated_lb=100, fuel_burned_gal=1,
            feedwater_intake_gal=13, blowdown_gal=1,
        )
        current = get_boiler(plant["id"], boiler["id"])
        resp = api.verify_log_entry(
            plant["id"], boiler["id"], entry2["id"], current["version"],
            make_operator_headers(ops[1]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FUEL_INVENTORY_UNDERFLOW)

        plant_state = get_plant(plant["id"])
        assert plant_state["fuel_inventory_gal"] == pytest.approx(0)
        reread = validate_success(
            api.get_log_entry(
                plant["id"], boiler["id"], entry2["id"], plant_manager_headers
            )
        )
        assert reread["status"] == "DRAFT", "rejected verify leaves entry DRAFT"


class TestFuelConservationUnderVoid:
    def test_fuel_inventory_conservation_under_void(
        self, api, plant_manager_headers
    ):
        """PRD §2.10: "Voiding a previously verified entry subtracts that same
        `fuel_burned_gal` back out — a compensating reversal rather than a
        deletion". The invariant "`fuel_inventory_gal` always equals
        `total_fuel_received_gal` minus `total_fuel_consumed_gal`" holds before
        and after the pair.

        Design: Difficulty/compensating_invariant/fuel_inventory_conservation_under_void
        """
        plant, ops = setup_plant_with_operators(name="Cons Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-CONS")
        deliver_fuel(plant["id"], 500)
        entry = create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            steam_generated_lb=5000, fuel_burned_gal=50,
            feedwater_intake_gal=650, blowdown_gal=50,
        )
        mid = get_plant(plant["id"])
        assert mid["fuel_inventory_gal"] == pytest.approx(450)
        assert mid["total_fuel_consumed_gal"] == pytest.approx(50)
        assert_fuel_ledger_invariant(mid)

        resp = api.void_log_entry(
            plant["id"], boiler["id"], entry["id"], plant_manager_headers
        )
        voided = validate_success(resp, expected_status=200)
        assert voided["status"] == "VOIDED"

        after = get_plant(plant["id"])
        assert after["fuel_inventory_gal"] == pytest.approx(500)
        assert after["total_fuel_consumed_gal"] == pytest.approx(0)
        assert after["total_fuel_received_gal"] == pytest.approx(500)
        assert_fuel_ledger_invariant(after)

    def test_fuel_invariant_across_multiple_verifies_and_void(
        self, api, plant_manager_headers
    ):
        """PRD §2.10: "`fuel_inventory_gal` always equals
        `total_fuel_received_gal` minus `total_fuel_consumed_gal`, and it may
        never go negative." Two verifications followed by one compensating
        void keep the invariant exact at every step.

        Design: Difficulty/compensating_invariant/fuel_inventory_conservation_under_void
        """
        plant, ops = setup_plant_with_operators(name="Cons2 Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-CN2")
        deliver_fuel(plant["id"], 500)
        e1 = create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            recorded_at="2026-08-05T10:00:00Z",
            steam_generated_lb=5000, fuel_burned_gal=50,
            feedwater_intake_gal=650, blowdown_gal=50,
        )
        e2 = create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            recorded_at="2026-08-05T11:00:00Z",
            steam_generated_lb=3000, fuel_burned_gal=30,
            feedwater_intake_gal=390, blowdown_gal=30,
        )
        mid = get_plant(plant["id"])
        assert mid["total_fuel_consumed_gal"] == pytest.approx(80)
        assert mid["fuel_inventory_gal"] == pytest.approx(420)
        assert_fuel_ledger_invariant(mid)

        validate_success(
            api.void_log_entry(
                plant["id"], boiler["id"], e1["id"], plant_manager_headers
            )
        )
        after = get_plant(plant["id"])
        assert after["total_fuel_consumed_gal"] == pytest.approx(30)
        assert after["fuel_inventory_gal"] == pytest.approx(470)
        assert_fuel_ledger_invariant(after)

        boiler_state = get_boiler(plant["id"], boiler["id"])
        assert boiler_state["total_fuel_burned_gal"] == pytest.approx(30)
        assert boiler_state["total_steam_lb"] == pytest.approx(3000)
