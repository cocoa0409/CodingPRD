"""Boiler operations: invalid transitions, lead-bank restriction, emergency
posture gating, validation ordering, and the lead/lag selector."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_verify_log_entry,
    create_boiler,
    create_online_boiler,
    create_plant,
    deliver_fuel,
    get_boiler,
    get_plant,
    make_operator_headers,
    record_in_spec_chemistry,
    run_ops,
    setup_plant_with_operators,
    trip_boiler_via_incident,
    validate_error,
    validate_success,
)


class TestInvalidTransitions:
    def test_boiler_warm_from_online_returns_invalid_state(
        self, api, plant_manager_headers
    ):
        """PRD §3.4: "asking for a transition from any other state than a
        listed from-state is rejected with `ERR_INVALID_STATE`." Warm is only
        defined from STANDBY ("An `Operator` warms a boiler, moving it
        `STANDBY` to `WARMING`").

        Design: Corner/state_machines/boiler_warm_from_online_returns_invalid_state
        """
        plant, ops = setup_plant_with_operators(name="IT Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-IT")
        assert boiler["ops_status"] == "ONLINE"

        resp = api.warm_boiler(
            plant["id"], boiler["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_boiler(plant["id"], boiler["id"])["ops_status"] == "ONLINE"


class TestLeadBankRestriction:
    def test_lead_cannot_bank_returns_422(self, api, plant_manager_headers):
        """PRD §3.4: "The plant's current lead boiler may not bank while at
        least one other boiler is `ONLINE` — it must hand off first, and the
        attempt is refused with `ERR_LEAD_CANNOT_BANK`."

        Design: Corner/validations/lead_cannot_bank_returns_422
        """
        plant, ops = setup_plant_with_operators(name="Lead Plant", count=1)
        op = ops[0]
        b1 = create_online_boiler(
            plant["id"], op["id"], tag="B-L1", rated_capacity_lb_hr=60000
        )
        b2 = create_online_boiler(
            plant["id"], op["id"], tag="B-L2", rated_capacity_lb_hr=50000
        )
        assert get_plant(plant["id"])["lead_boiler_id"] == b1["id"]

        resp = api.bank_boiler(
            plant["id"], b1["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_CANNOT_BANK)
        assert get_boiler(plant["id"], b1["id"])["ops_status"] == "ONLINE"
        # The other ONLINE boiler is unaffected.
        assert get_boiler(plant["id"], b2["id"])["ops_status"] == "ONLINE"


class TestEmergencyPostureGate:
    def test_err_plant_emergency_blocks_warm(self, api, plant_manager_headers):
        """PRD §2.7: "Plant emergency gate — warming any boiler while the
        plant `posture` is `EMERGENCY` is rejected with `ERR_PLANT_EMERGENCY`
        (422)." PRD §3.9: "the plant `posture` becomes `DEGRADED` if at least
        one boiler remains `ONLINE`, otherwise `EMERGENCY`."

        Design: Corner/errors/err_plant_emergency_blocks_warm
        """
        plant, ops = setup_plant_with_operators(name="Em Plant", count=1)
        op = ops[0]
        b1 = create_online_boiler(plant["id"], op["id"], tag="B-E1")
        b2 = create_boiler(plant["id"], tag="B-E2")  # stays STANDBY
        trip_boiler_via_incident(plant["id"], b1["id"], op["id"])
        assert get_plant(plant["id"])["posture"] == "EMERGENCY"

        resp = api.warm_boiler(
            plant["id"], b2["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PLANT_EMERGENCY)


class TestValidationPriorityStateVsCert:
    def test_state_error_precedes_cert_gate_on_warm(
        self, api, plant_manager_headers
    ):
        """PRD §2.7: "Every request is validated in a fixed, global order, and
        a request that fails several checks surfaces the error from the
        earliest stage." Stage 4 is "State — the target resource is in a valid
        from-state for the requested transition; otherwise `ERR_INVALID_STATE`
        (409)", and stage 6 is "Certificate gate — warming or bringing online a
        boiler whose `cert_status` is not `VALID` is rejected with
        `ERR_CERT_NOT_VALID` (422)." A TRIPPED boiler with a LAPSED certificate
        therefore reports ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_warm
        """
        plant, ops = setup_plant_with_operators(name="PC Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-PC")
        trip_boiler_via_incident(plant["id"], boiler["id"], op["id"])
        # No PASSED inspection exists, so the checkpoint lapses the cert:
        # PRD §3.6 "if no `PASSED` inspection exists for the boiler ... the
        # status becomes `LAPSED`".
        run_ops(plant["id"])
        state = get_boiler(plant["id"], boiler["id"])
        assert state["ops_status"] == "TRIPPED"
        assert state["cert_status"] == "LAPSED"

        resp = api.warm_boiler(
            plant["id"], boiler["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_cert_gate_fires_in_isolation_on_warm(
        self, api, plant_manager_headers
    ):
        """PRD §3.4: "the boiler's `cert_status` must be `VALID` (else
        `ERR_CERT_NOT_VALID`)". With state, water, posture, license, and
        jurisdiction all satisfied, the certificate gate reports
        ERR_CERT_NOT_VALID.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_warm
        """
        plant, ops = setup_plant_with_operators(name="PC Cert Plant", count=1)
        op = ops[0]
        boiler = create_boiler(plant["id"], tag="B-PCC")  # STANDBY
        run_ops(plant["id"])  # no PASSED inspection -> cert LAPSED
        state = get_boiler(plant["id"], boiler["id"])
        assert state["cert_status"] == "LAPSED"
        assert state["ops_status"] == "STANDBY"

        resp = api.warm_boiler(
            plant["id"], boiler["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_VALID)


class TestLeadLagSelector:
    def test_incumbent_with_all_score_terms_holds_lead(
        self, api, plant_manager_headers
    ):
        """PRD §3.4: "Each eligible boiler is scored: start from its
        `rated_capacity_lb_hr`; multiply by one if its `efficiency_pct` has
        never been computed, otherwise by `efficiency_pct` divided by one
        hundred; multiply by one minus the product of 0.15 and the lesser of
        one and the ratio of the boiler's `cycles_of_concentration` to the 10.0
        maximum ... then add an incumbency bonus of 5,000.0 if the boiler
        currently holds `lead_boiler_id`."
        B1 (60000 lb/hr, no efficiency, cycles 5.0, incumbent) scores 60500;
        B2 (50000 lb/hr, efficiency 90.18, cycles 5.0) scores 41708.25, so B1
        remains lead.

        Design: Difficulty/combinatorial_formula/lead_lag_dispatch_selection_mode_a
        """
        plant, ops = setup_plant_with_operators(name="Sel Plant", count=2)
        op_a, op_b = ops
        deliver_fuel(plant["id"], 1000)
        b1 = create_online_boiler(
            plant["id"], op_a["id"], tag="B-1", rated_capacity_lb_hr=60000
        )
        b2 = create_online_boiler(
            plant["id"], op_a["id"], tag="B-2", rated_capacity_lb_hr=50000
        )
        # Verified entry on B2 gives it a computed efficiency (90.18 per the
        # input-output method) but not enough to outrank the incumbent.
        create_and_verify_log_entry(
            plant["id"], b2["id"], op_a["id"], op_b["id"],
            steam_generated_lb=10000, fuel_burned_gal=80,
            feedwater_intake_gal=1300, blowdown_gal=100,
        )
        b2_state = get_boiler(plant["id"], b2["id"])
        assert b2_state["efficiency_pct"] == pytest.approx(90.18, abs=0.005)

        plant_state = get_plant(plant["id"])
        assert plant_state["lead_boiler_id"] == b1["id"]

    def test_higher_scored_challenger_takes_lead(self, api, plant_manager_headers):
        """PRD §3.4: "Boilers rank by score descending; ties break by
        `rated_capacity_lb_hr` descending, then by `created_at` ascending."
        B1 (50000 lb/hr, no efficiency, cycles 1.0, incumbent) scores
        50000 * 0.985 + 5000 = 54250. B2 (62000 lb/hr, efficiency 90.18,
        cycles 1.0) scores 62000 * 0.9018 * 0.985 = 55072.93, so the selector
        moves the lead to B2 when B2 comes online.

        Design: Difficulty/combinatorial_formula/lead_lag_dispatch_selection_mode_a
        """
        plant, ops = setup_plant_with_operators(name="Sel2 Plant", count=2)
        op_a, op_b = ops
        deliver_fuel(plant["id"], 1000)
        b1 = create_boiler(plant["id"], tag="B-1", rated_capacity_lb_hr=50000)
        b2 = create_boiler(plant["id"], tag="B-2", rated_capacity_lb_hr=62000)
        # cycles 1.0 chemistry (1000/1000) for both boilers
        record_in_spec_chemistry(
            plant["id"], b1["id"], op_a["id"],
            conductivity_boiler_umho=1000, conductivity_feedwater_umho=1000,
        )
        record_in_spec_chemistry(
            plant["id"], b2["id"], op_a["id"],
            conductivity_boiler_umho=1000, conductivity_feedwater_umho=1000,
        )
        headers_a = make_operator_headers(op_a["id"])
        validate_success(api.warm_boiler(plant["id"], b1["id"], headers_a))
        validate_success(api.bring_boiler_online(plant["id"], b1["id"], headers_a))
        assert get_plant(plant["id"])["lead_boiler_id"] == b1["id"]

        # Verify a log entry on B2 while it is still STANDBY (a permitted
        # from-state per PRD §3.5) so its efficiency is computed pre-online.
        create_and_verify_log_entry(
            plant["id"], b2["id"], op_a["id"], op_b["id"],
            steam_generated_lb=10000, fuel_burned_gal=80,
            feedwater_intake_gal=1300, blowdown_gal=100,
        )
        validate_success(api.warm_boiler(plant["id"], b2["id"], headers_a))
        validate_success(api.bring_boiler_online(plant["id"], b2["id"], headers_a))

        assert get_plant(plant["id"])["lead_boiler_id"] == b2["id"]
