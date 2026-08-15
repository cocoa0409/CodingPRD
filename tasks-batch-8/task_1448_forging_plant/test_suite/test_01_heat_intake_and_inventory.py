"""Heat intake, billet cutting, and heat-weight inventory accounting (PRD §3.1-§3.2)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_heat_weight_invariant,
    assert_mill_heat,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    new_alloy,
    new_certified_heat,
    new_furnace,
    new_heat,
    new_ready_charge,
    set_logical_clock,
    cut_billets,
    setup_production_ctx,
    validate_error,
    validate_paginated,
    validate_success,
    verify_heat,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
SAW = TEST_USERS["saw_operator_headers"]
FURN = TEST_USERS["furnace_operator_headers"]
QE = TEST_USERS["quality_engineer_headers"]


class TestMillHeatCreation:
    def test_mill_heat_creation_applies_system_defaults(self, api):
        """PRD §3.1: "A new lot starts in `RECEIVED` status with its
        `remaining_weight_lbs` equal to `received_weight_lbs`, and its measured
        chemistry fields `carbon_pct` and `manganese_pct` remain null until
        verification."
        PRD §2.4: "`id` (string): a server-minted UUID with no type prefix,
        unique across the system."

        Design: Corner/entities/entity_create_applies_system_defaults
        """
        alloy = new_alloy()
        resp = api.create_mill_heat(
            {
                "heat_number": "H-7001",
                "alloy_spec_id": alloy["id"],
                "mill_name": "Ellwood Bar Mill",
                "received_weight_lbs": 20000.00,
                "bar_lbs_per_in": 2.50,
            },
            PM,
        )
        heat = validate_success(resp, 201)
        assert_mill_heat(heat)
        assert heat["status"] == "RECEIVED", f"new heat must start RECEIVED, got {heat['status']}"
        assert heat["remaining_weight_lbs"] == pytest.approx(20000.00, abs=1e-9), (
            f"remaining_weight_lbs must equal received_weight_lbs, got "
            f"{heat['remaining_weight_lbs']}"
        )
        assert heat["carbon_pct"] is None, "carbon_pct must be null until verification"
        assert heat["manganese_pct"] is None, "manganese_pct must be null until verification"
        assert is_valid_uuid(heat["id"])
        assert is_iso8601_timestamp(heat["created_at"])
        assert is_iso8601_timestamp(heat["updated_at"])

    def test_get_mill_heat_not_found_returns_404(self, api):
        """PRD §2.9: "Each path identifier is resolved in sequence, and the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing resource — a trim
        ticket under a non-existent run is never even looked up."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/entity_get_not_found_returns_404
        """
        resp = api.get_mill_heat(NON_EXISTENT_UUID, PM)
        body = resp.json()
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)

    def test_computed_field_input_ignored_on_heat_create(self, api):
        """PRD §3.1: "A new lot starts in `RECEIVED` status with its
        `remaining_weight_lbs` equal to `received_weight_lbs`, and its measured
        chemistry fields `carbon_pct` and `manganese_pct` remain null until
        verification." A client-supplied `remaining_weight_lbs` cannot override
        that derivation.

        Design: Corner/entities/computed_field_input_ignored_on_create
        """
        alloy = new_alloy()
        resp = api.create_mill_heat(
            {
                "heat_number": "H-7002",
                "alloy_spec_id": alloy["id"],
                "mill_name": "Ellwood Bar Mill",
                "received_weight_lbs": 20000.00,
                "bar_lbs_per_in": 2.50,
                "remaining_weight_lbs": 5.00,
            },
            PM,
        )
        heat = validate_success(resp, 201)
        assert heat["remaining_weight_lbs"] == pytest.approx(20000.00, abs=1e-9), (
            f"computed remaining_weight_lbs must derive from received weight, "
            f"got {heat['remaining_weight_lbs']}"
        )

    def test_mill_heat_missing_heat_number_rejected(self, api):
        """PRD §2.10: "Request-body well-formedness — required fields present,
        enum values valid, numeric ranges sane (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "A `PlantManager` registers each lot with its `heat_number` —
        unique across all heats, with duplicates refused via
        `ERR_DUPLICATE_HEAT_NUMBER` — the `alloy_spec_id` of its grade, the
        originating `mill_name` that anchors traceability, the scale
        `received_weight_lbs`, and the bar's linear density `bar_lbs_per_in`,
        which later drives billet cut weights."

        Design: Corner/entities/mill_heat_missing_required_field_rejected
        """
        alloy = new_alloy()
        resp = api.create_mill_heat(
            {
                "alloy_spec_id": alloy["id"],
                "mill_name": "Ellwood Bar Mill",
                "received_weight_lbs": 20000.00,
                "bar_lbs_per_in": 2.50,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestHeatCertificationGate:
    def test_cut_from_unverified_heat_rejected(self, api):
        """PRD §3.2: "Cutting, like charging, requires the heat to be
        `CERT_VERIFIED`: against a heat still in `RECEIVED` the request fails
        with `ERR_HEAT_NOT_CERTIFIED`, and against a `QUARANTINED` heat with
        `ERR_HEAT_QUARANTINED`."

        Design: Corner/entities/cut_from_unverified_heat_rejected
        """
        alloy = new_alloy()
        heat = new_heat(alloy["id"], "H-7004")
        assert heat["status"] == "RECEIVED"
        resp = api.cut_billets(
            heat["id"], {"cuts": [{"cut_length_in": 20.0, "quantity": 1}]}, SAW
        )
        validate_error(resp, ApiErrorId.ERR_HEAT_NOT_CERTIFIED, 409)
        after = get_success_data(api.get_mill_heat(heat["id"], PM))
        assert after["status"] == "RECEIVED", "heat must remain RECEIVED after failed cut"

    def test_verify_cert_twice_rejected(self, api):
        """PRD §3.1: "When both values are at or below the alloy's maxima, the
        heat moves from `RECEIVED` to `CERT_VERIFIED` and the chemistry is
        stored on the heat; when either value exceeds its maximum, verification
        is rejected with `ERR_CHEMISTRY_OUT_OF_SPEC`."
        PRD §2.10: "Source-state validity for the requested transition
        (`ERR_INVALID_STATE_TRANSITION`, alongside the dedicated state-flavored
        codes `ERR_CHARGE_NOT_READY`, `ERR_PART_NOT_INSPECTED`, and
        `ERR_RUN_NO_HEATS`)."

        Design: Corner/state_machines/verify_cert_twice_rejected
        """
        alloy = new_alloy()
        heat = new_heat(alloy["id"], "H-7108")
        verified = verify_heat(heat["id"])
        assert verified["status"] == "CERT_VERIFIED"
        resp = api.verify_heat_cert(
            heat["id"], {"carbon_pct": 0.40, "manganese_pct": 0.90}, QE
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_release_rejected_heat_rejected(self, api):
        """PRD §3.1: "The quarantine loop is cyclic: releasing a quarantined
        heat returns it to `CERT_VERIFIED` with the chemistry report from the
        original verification retained, while a quarantined heat may instead be
        rejected outright — again with a `reason` — to the terminal `REJECTED`
        state."

        Design: Corner/state_machines/release_rejected_heat_rejected
        """
        alloy = new_alloy()
        heat = new_heat(alloy["id"], "H-7104")
        verify_heat(heat["id"])
        get_success_data(api.quarantine_heat(heat["id"], {"reason": "cert mismatch"}, QE))
        rejected = get_success_data(
            api.reject_heat(heat["id"], {"reason": "confirmed off-chemistry"}, QE)
        )
        assert rejected["status"] == "REJECTED"
        resp = api.release_heat_quarantine(heat["id"], QE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_mill_heat(heat["id"], QE))
        assert after["status"] == "REJECTED", "REJECTED is terminal"


class TestBilletCutWeight:
    def test_billet_cut_weight_exact(self, api):
        """PRD §3.2: "Each resulting billet is stamped with its `cut_length_in`,
        and its `cut_weight_lbs` is that length multiplied by the parent heat's
        `bar_lbs_per_in`, rounded half-up to two decimal places. Within a heat,
        each billet receives a `cut_seq` — a per-heat sequence assigned in
        creation order starting at 1 — and its `mill_heat_id` ties it back to
        the parent heat taken from the creation path."
        PRD §3.2: "A heat's `remaining_weight_lbs` is its `received_weight_lbs`
        minus the sum of `cut_weight_lbs` over every billet ever cut from it,
        regardless of those billets' current status; kerf, scale, and scrap
        never return weight to the heat."

        Design: Corner/calculations/calc_billet_cut_weight_exact
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-7201")
        resp = api.cut_billets(
            heat["id"],
            {"cuts": [
                {"cut_length_in": 20.0, "quantity": 2},
                {"cut_length_in": 10.5, "quantity": 1},
            ]},
            SAW,
        )
        created = validate_success(resp, 201)
        assert len(created) == 3
        weights = [b["cut_weight_lbs"] for b in created]
        assert weights[0] == pytest.approx(50.00, abs=1e-9), f"20.0 in * 2.50 = 50.00, got {weights[0]}"
        assert weights[1] == pytest.approx(50.00, abs=1e-9)
        assert weights[2] == pytest.approx(26.25, abs=1e-9), f"10.5 in * 2.50 = 26.25, got {weights[2]}"
        seqs = [b["cut_seq"] for b in created]
        assert seqs == [1, 2, 3], f"cut_seq must be assigned in creation order from 1, got {seqs}"
        heat_after = get_success_data(api.get_mill_heat(heat["id"], PM))
        assert heat_after["remaining_weight_lbs"] == pytest.approx(19873.75, abs=1e-9), (
            f"20000.00 - 126.25 = 19873.75, got {heat_after['remaining_weight_lbs']}"
        )

    def test_heat_depleted_auto_transition(self, api):
        """PRD §3.2: "Depletion is re-evaluated on every billet creation and
        every billet status mutation: when `remaining_weight_lbs` reaches
        exactly zero and no billet of the heat remains in `CUT`, `CHARGED`, or
        `DISCHARGED` — that is, every cut billet is `CONSUMED` or `SCRAPPED` —
        the heat transitions itself to the terminal `DEPLETED` state."

        Design: Corner/state_machines/heat_depleted_auto_transition
        """
        # Four 10.0-in billets at 2.50 lbs/in draw the 100.00-lb heat to exactly
        # zero; the production line then consumes all four in one forge heat.
        ctx = setup_production_ctx(
            qty=4, cut_length_in=10.0, received_weight_lbs=100.00,
            record_trim_ticket=False,
        )
        heat_id = ctx["heat"]["id"]
        heat_end = get_success_data(api.get_mill_heat(heat_id, PM))
        assert heat_end["remaining_weight_lbs"] == pytest.approx(0.00, abs=1e-9)
        assert heat_end["status"] == "DEPLETED", (
            f"all billets CONSUMED with zero remaining must flip the heat to "
            f"DEPLETED, got {heat_end['status']}"
        )

    def test_heat_not_depleted_while_billets_cut(self, api):
        """PRD §3.2: "Depletion is re-evaluated on every billet creation and
        every billet status mutation: when `remaining_weight_lbs` reaches
        exactly zero and no billet of the heat remains in `CUT`, `CHARGED`, or
        `DISCHARGED` — that is, every cut billet is `CONSUMED` or `SCRAPPED` —
        the heat transitions itself to the terminal `DEPLETED` state."

        Zero remaining weight alone does not deplete: billets still in CUT
        block the transition.

        Design: Corner/state_machines/heat_depleted_auto_transition
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-7109", received_weight_lbs=100.00)
        cut_billets(heat["id"], 10.0, 4)
        heat_mid = get_success_data(api.get_mill_heat(heat["id"], PM))
        assert heat_mid["remaining_weight_lbs"] == pytest.approx(0.00, abs=1e-9)
        assert heat_mid["status"] == "CERT_VERIFIED", (
            f"billets still in CUT must block depletion, got {heat_mid['status']}"
        )


class TestHeatWeightConservation:
    def test_charge_discharge_cycle_leaves_remaining_weight_unchanged(self, api):
        """PRD §3.2: "A heat's `remaining_weight_lbs` is its `received_weight_lbs`
        minus the sum of `cut_weight_lbs` over every billet ever cut from it,
        regardless of those billets' current status; kerf, scale, and scrap
        never return weight to the heat."

        Charging and discharging move no mass: remaining_weight_lbs stays
        pinned at 100.00 across the whole cycle.

        Design: Difficulty/compensating_invariant/heat_weight_conservation_across_charge_cycles
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-5501", received_weight_lbs=200.00)
        billets = cut_billets(heat["id"], 10.0, 4)
        furnace = new_furnace()
        set_logical_clock("2026-08-02T08:00:00Z")
        charge = new_ready_charge(
            furnace["id"], [billets[0]["id"], billets[1]["id"]],
            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z",
        )
        after_charge = get_success_data(api.get_mill_heat(heat["id"], PM))
        assert after_charge["remaining_weight_lbs"] == pytest.approx(100.00, abs=1e-9), (
            f"charging moves no mass, got {after_charge['remaining_weight_lbs']}"
        )
        get_success_data(api.discharge_charge(charge["id"], FURN))
        after_discharge = get_success_data(api.get_mill_heat(heat["id"], PM))
        assert after_discharge["remaining_weight_lbs"] == pytest.approx(100.00, abs=1e-9), (
            f"discharge must compensate charge with zero drift, got "
            f"{after_discharge['remaining_weight_lbs']}"
        )
        all_billets, _meta = validate_paginated(api.list_heat_billets(heat["id"], PM))
        assert_heat_weight_invariant(after_discharge, all_billets)

    def test_scrap_does_not_return_weight_and_depletion_blocked(self, api):
        """PRD §3.2: "A `SawOperator` may scrap a billet in `CUT` or
        `DISCHARGED` by supplying a `reason`, moving it to the terminal
        `SCRAPPED` state — and scrapped weight does not return to the heat."
        PRD §3.2: "when `remaining_weight_lbs` reaches exactly zero and no
        billet of the heat remains in `CUT`, `CHARGED`, or `DISCHARGED` — that
        is, every cut billet is `CONSUMED` or `SCRAPPED` — the heat transitions
        itself to the terminal `DEPLETED` state."

        After scrapping b3, remaining stays 100.00 and the heat stays
        CERT_VERIFIED because b1/b2 are DISCHARGED and b4 is CUT.

        Design: Difficulty/compensating_invariant/heat_weight_conservation_across_charge_cycles
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-5501", received_weight_lbs=200.00)
        billets = cut_billets(heat["id"], 10.0, 4)
        furnace = new_furnace()
        charge = new_ready_charge(
            furnace["id"], [billets[0]["id"], billets[1]["id"]],
            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z",
        )
        get_success_data(api.discharge_charge(charge["id"], FURN))
        scrapped = get_success_data(
            api.scrap_billet(billets[2]["id"], {"reason": "dropped, dented"}, SAW)
        )
        assert scrapped["status"] == "SCRAPPED"
        after_scrap = get_success_data(api.get_mill_heat(heat["id"], PM))
        assert after_scrap["remaining_weight_lbs"] == pytest.approx(100.00, abs=1e-9), (
            f"scrapped weight must not return to the heat, got "
            f"{after_scrap['remaining_weight_lbs']}"
        )
        assert after_scrap["status"] == "CERT_VERIFIED", (
            f"heat must not deplete while billets remain CUT/DISCHARGED, got "
            f"{after_scrap['status']}"
        )
        all_billets, _meta = validate_paginated(api.list_heat_billets(heat["id"], PM))
        assert_heat_weight_invariant(after_scrap, all_billets)
