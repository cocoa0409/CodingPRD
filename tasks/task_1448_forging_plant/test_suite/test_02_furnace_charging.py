"""Furnace charging: window adjacency, soak gating, re-heat ceiling, heat
usability, and validation ordering (PRD §2.10, §3.3)."""
from test_helpers import (
    ApiErrorId,
    cut_billets,
    factories,
    get_success_data,
    new_alloy,
    new_certified_heat,
    new_furnace,
    new_ready_charge,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
SAW = TEST_USERS["saw_operator_headers"]
FURN = TEST_USERS["furnace_operator_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def _charge_payload(furnace_id, billet_ids, start, end, temp=2200, soak=60):
    return factories.furnace_charge_payload(furnace_id, billet_ids, start, end, temp, soak)


class TestFurnaceWindowAdjacency:
    def test_furnace_window_back_to_back_adjacency_allowed(self, api):
        """PRD §3.3: "And because the planned window is a half-open interval,
        back-to-back charges whose `planned_load_start` equals the prior
        charge's `planned_unload` are permitted, while any true overlap with
        another non-terminal charge on the same furnace is rejected as
        `ERR_FURNACE_WINDOW_OVERLAP`."

        Charge A occupies [08:00,12:00); charge B starts exactly at 12:00 and
        must be accepted under half-open semantics.

        Design: Difficulty/resource_temporal_overlap/furnace_half_open_window_adjacency
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-5401")
        billets = cut_billets(heat["id"], 20.0, 6)
        furnace = new_furnace()
        resp_a = api.create_furnace_charge(
            _charge_payload(furnace["id"], [billets[0]["id"], billets[1]["id"]],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        )
        charge_a = validate_success(resp_a, 201)
        assert charge_a["status"] == "LOADING"
        resp_b = api.create_furnace_charge(
            _charge_payload(furnace["id"], [billets[2]["id"], billets[3]["id"]],
                            "2026-08-02T12:00:00Z", "2026-08-02T16:00:00Z"),
            FURN,
        )
        validate_success(resp_b, 201)

    def test_furnace_window_interior_overlap_rejected(self, api):
        """PRD §3.3: "And because the planned window is a half-open interval,
        back-to-back charges whose `planned_load_start` equals the prior
        charge's `planned_unload` are permitted, while any true overlap with
        another non-terminal charge on the same furnace is rejected as
        `ERR_FURNACE_WINDOW_OVERLAP`."

        Charge C [10:00,11:00) falls strictly inside charge A [08:00,12:00).

        Design: Difficulty/resource_temporal_overlap/furnace_half_open_window_adjacency
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-5401")
        billets = cut_billets(heat["id"], 20.0, 6)
        furnace = new_furnace()
        get_success_data(api.create_furnace_charge(
            _charge_payload(furnace["id"], [billets[0]["id"], billets[1]["id"]],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        ))
        resp_c = api.create_furnace_charge(
            _charge_payload(furnace["id"], [billets[4]["id"], billets[5]["id"]],
                            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"),
            FURN,
        )
        validate_error(resp_c, ApiErrorId.ERR_FURNACE_WINDOW_OVERLAP, 409)


class TestChargeHeatUsability:
    def test_charge_blocked_while_heat_quarantined(self, api):
        """PRD §3.1: "A heat may be quarantined from `RECEIVED` or from
        `CERT_VERIFIED`, an action that takes a `reason`; quarantining a
        certified heat blocks any new furnace charge containing its billets
        with `ERR_HEAT_QUARANTINED`."

        Design: Difficulty/cross_entity_state_dependency/charge_blocked_while_heat_quarantined
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-5201")
        billets = cut_billets(heat["id"], 20.0, 2)
        get_success_data(api.quarantine_heat(heat["id"], {"reason": "cert review"}, QE))
        furnace = new_furnace()
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [b["id"] for b in billets],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        )
        validate_error(resp, ApiErrorId.ERR_HEAT_QUARANTINED, 409)
        charges, meta = validate_paginated(
            api.list_furnace_charges(FURN, params={"furnace_id": furnace["id"]})
        )
        assert charges == [] and meta["total_count"] == 0, (
            "no charge may be created against a quarantined heat"
        )

    def test_charge_allowed_after_quarantine_release(self, api):
        """PRD §3.1: "The quarantine loop is cyclic: releasing a quarantined
        heat returns it to `CERT_VERIFIED` with the chemistry report from the
        original verification retained, while a quarantined heat may instead be
        rejected outright — again with a `reason` — to the terminal `REJECTED`
        state."

        Once released back to CERT_VERIFIED, the same billets charge cleanly.

        Design: Difficulty/cross_entity_state_dependency/charge_blocked_while_heat_quarantined
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-5201")
        billets = cut_billets(heat["id"], 20.0, 2)
        get_success_data(api.quarantine_heat(heat["id"], {"reason": "cert review"}, QE))
        released = get_success_data(api.release_heat_quarantine(heat["id"], QE))
        assert released["status"] == "CERT_VERIFIED"
        furnace = new_furnace()
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [b["id"] for b in billets],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        )
        charge = validate_success(resp, 201)
        assert charge["status"] == "LOADING"


class TestValidationOrdering:
    def test_temp_window_above_max_beats_quarantined_heat(self, api):
        """PRD §2.10: "Every request passes through an ordered gauntlet and
        fails at the first violated tier:" — with "7. Business-safety limits:
        the forge-temperature window, the re-heat ceiling, cert chemistry, the
        worn-die guard, trim mass balance, part-count accounting, and
        grain-flow acceptability." preceding "8. Referential usability: heat
        certification status, billet-charge membership, die installation,
        order progress, sample provenance, and heat-in-order membership."

        A charge at 2400F (above the 2300F window max) loading billets of a
        QUARANTINED heat fails on the temperature tier first.

        Design: Difficulty/priority_pair_validation_conflict/charge_temp_window_beats_quarantined_heat
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-4001")
        billets = cut_billets(heat["id"], 20.0, 2)
        get_success_data(api.quarantine_heat(
            heat["id"], {"reason": "suspected chemistry mix-up"}, QE))
        furnace = new_furnace()
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [b["id"] for b in billets],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z",
                            temp=2400),
            FURN,
        )
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_TEMP_OUTSIDE_FORGE_WINDOW, 422)

    def test_temp_window_below_min_beats_quarantined_heat(self, api):
        """PRD §3.3: "The `target_temp_f` must lie within the alloy's forge
        window from `forge_temp_min_f` through `forge_temp_max_f`, both bounds
        inclusive, else `ERR_TEMP_OUTSIDE_FORGE_WINDOW`."
        PRD §2.10: "Every request passes through an ordered gauntlet and fails
        at the first violated tier:"

        A charge at 2000F (below the 2100F window min) loading billets of a
        QUARANTINED heat fails on the temperature tier first.

        Design: Difficulty/priority_pair_validation_conflict/charge_temp_window_beats_quarantined_heat
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-4001")
        billets = cut_billets(heat["id"], 20.0, 2)
        get_success_data(api.quarantine_heat(
            heat["id"], {"reason": "suspected chemistry mix-up"}, QE))
        furnace = new_furnace()
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [b["id"] for b in billets],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z",
                            temp=2000),
            FURN,
        )
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_TEMP_OUTSIDE_FORGE_WINDOW, 422)


class TestChargeLifecycle:
    def test_discharge_loading_charge_rejected(self, api):
        """PRD §3.3: "Discharging is defined for a `READY` charge: every billet
        still `CHARGED` in it returns to `DISCHARGED` with its
        `current_charge_id` cleared, `discharged_at` is stamped from the
        logical clock, and the furnace's `active_charge_id` is cleared."
        PRD §2.10: "Source-state validity for the requested transition
        (`ERR_INVALID_STATE_TRANSITION`, alongside the dedicated state-flavored
        codes `ERR_CHARGE_NOT_READY`, `ERR_PART_NOT_INSPECTED`, and
        `ERR_RUN_NO_HEATS`)."

        Design: Corner/state_machines/discharge_loading_charge_rejected
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-7102")
        billets = cut_billets(heat["id"], 20.0, 1)
        furnace = new_furnace()
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [billets[0]["id"]],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        )
        charge = validate_success(resp, 201)
        assert charge["status"] == "LOADING"
        resp = api.discharge_charge(charge["id"], FURN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_furnace_charge(charge["id"], FURN))
        assert after["status"] == "LOADING"

    def test_soak_gate_uses_logical_clock(self, api):
        """PRD §3.3: "Marking the charge ready requires the logical clock to
        have reached `closed_at` plus `soak_minutes`; attempting it earlier
        fails with `ERR_SOAK_TIME_NOT_ELAPSED`, while success moves the charge
        from `SOAKING` to `READY` and stamps `ready_at`."

        At closed_at + 59 minutes the gate fails; at exactly +60 minutes
        (inclusive boundary) it passes.

        Design: Corner/state_machines/soak_gate_uses_logical_clock
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-7111")
        billets = cut_billets(heat["id"], 20.0, 1)
        furnace = new_furnace()
        set_logical_clock("2026-08-02T08:00:00Z")
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [billets[0]["id"]],
                            "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        )
        charge = validate_success(resp, 201)
        get_success_data(api.close_charge_loading(charge["id"], FURN))
        set_logical_clock("2026-08-02T08:59:00Z")
        resp = api.mark_charge_ready(charge["id"], FURN)
        validate_error(resp, ApiErrorId.ERR_SOAK_TIME_NOT_ELAPSED, 409)
        set_logical_clock("2026-08-02T09:00:00Z")
        ready = get_success_data(api.mark_charge_ready(charge["id"], FURN))
        assert ready["status"] == "READY", (
            f"exactly closed_at + soak_minutes must satisfy the gate, got {ready['status']}"
        )


class TestReheatLimit:
    def test_reheat_limit_boundary(self, api):
        """PRD §3.3: "The re-heat ceiling applies per billet: a billet may
        undergo at most its alloy's `reheat_limit` charges beyond its initial
        one, so a billet whose `charge_count` has already reached that total
        triggers `ERR_REHEAT_LIMIT_EXCEEDED`."

        With reheat_limit 2 the same billet charges exactly three times across
        discharge cycles; the fourth charge is refused.

        Design: Corner/calculations/calc_reheat_limit_boundary
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-7202")
        billets = cut_billets(heat["id"], 20.0, 1)
        billet_id = billets[0]["id"]
        furnace = new_furnace()
        windows = [
            ("2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"),
            ("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"),
            ("2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z"),
        ]
        for start, end in windows:
            charge = new_ready_charge(
                furnace["id"], [billet_id], start, end, soak_minutes=30,
            )
            get_success_data(api.discharge_charge(charge["id"], FURN))
        billet = get_success_data(api.get_billet(billet_id, FURN))
        assert billet["charge_count"] == 3, (
            f"charge_count must reach reheat_limit + 1 = 3, got {billet['charge_count']}"
        )
        set_logical_clock("2026-08-02T14:00:00Z")
        resp = api.create_furnace_charge(
            _charge_payload(furnace["id"], [billet_id],
                            "2026-08-02T14:00:00Z", "2026-08-02T15:00:00Z",
                            temp=2200, soak=30),
            FURN,
        )
        validate_error(resp, ApiErrorId.ERR_REHEAT_LIMIT_EXCEEDED, 409)
