"""Composition order inside two multi-input derived numbers of the fastener plant.

The plant prints a declared piece count on every weight-packed carton and scores every
lot for release risk, and in both cases the order of the operations inside the formula
is observable from the outside. A ``BY_WEIGHT`` pack's ``declared_count`` is rounded
half up per pack, and a lot's ``packed_count`` is the sum of those already-rounded
per-pack values rather than a re-derivation from aggregate mass (PRD §3.9). A lot's
release risk is scored in two passes: the four weighted pre-test terms are added and
rounded exactly once when the relief bake closes, and the sampling plan's severity is
frozen from that pass-one value before the second pass adds the per-failure penalty
(PRD §3.6, §3.7).
"""

import copy

import pytest

from test_helpers import (
    api_client,
    fixtures,
    make_clerk_headers,
    validate_success,
)

# ---------------------------------------------------------------------------
# One shared production route, spelled out so every number an assertion below
# depends on is explicit rather than inherited from a factory default.
#
# HX-M8-109: plated CLASS_10_9, AUTOMOTIVE_PPAP, blank_mass_g 20.0,
# max_decarb_depth_mm 0.150, packed BY_WEIGHT at 62.5 pieces per kilogram with a
# nominal pack of 500 and a count tolerance of 0.02.
# ---------------------------------------------------------------------------
PART_SPEC_OVERRIDES = {
    "part_number": "HX-M8-109",
    "thread_designation": "M8x1.25",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 20.0,
    "scrap_allowance_pct": 0.05,
    "station_count_required": 4,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL", "POINT"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.150,
    "plating_spec": "ZINC_CLEAR",
    "packaging_mode": "BY_WEIGHT",
    "nominal_pack_count": 500,
    "count_tolerance_pct": 0.02,
    "pieces_per_kg": 62.5,
    "proof_load_kn": 34.7,
}

ROUTE = {
    "clock": "2026-09-01T06:00:00Z",
    "spec_overrides": PART_SPEC_OVERRIDES,
    "heat_overrides": {"grade": "SAE_10B21", "gross_mass_kg": 500.0},
    "wire_overrides": {
        "inlet_diameter_mm": 8.00,
        "outlet_diameter_mm": 6.80,
        "lubricant_coating": "PHOSPHATE",
        "coating_weight_gsm": 4.5,
        "gross_mass_kg": 500.0,
    },
    "tool_overrides": {"station_count": 4, "rated_life_pieces": 120000},
    "furnace_overrides": {"max_charge_mass_kg": 400.0},
    "planned_pieces": 10000,
    "headed_count": 9800,
    "heading_scrap_count": 150,
    "ops": [
        {
            "op_type": "THREAD_ROLL",
            "sequence_no": 1,
            "pieces_out": 9750,
            "machine_code": "TR-1",
        },
        {
            "op_type": "POINT",
            "sequence_no": 2,
            "pieces_out": 9740,
            "machine_code": "PT-1",
        },
    ],
    "booking_overrides": {
        "window_start_at": "2026-09-01T18:00:00Z",
        "window_end_at": "2026-09-01T23:00:00Z",
        "carbon_potential_pct": 0.42,
    },
    "core_hardness_hv": 330.0,
    "surface_decarb_depth_mm": 0.100,
    "start_at": "2026-09-01T19:00:00Z",
    "results_at": "2026-09-01T22:00:00Z",
    "plated_at": "2026-09-02T02:00:00Z",
    "bake_started_at": "2026-09-02T05:00:00Z",
    "bake_completed_at": "2026-09-02T09:00:00Z",
    "bake_temp_c": 210.0,
    "bake_duration_min": 240,
}

# Counts the route produces, restated here so the assertions read as arithmetic.
HEADED_TOTAL = 9950                  # 9800 good + 150 heading scrap
AVAILABLE_AFTER_SECONDARY = 9740     # THREAD_ROLL 9750, then POINT 9740
SAMPLE_SIZE = 99                     # max(8, ceil(sqrt(9740)))
AVAILABLE_AFTER_TEST = 9641          # 9740 - 99 destructively consumed
TOOL_UTILIZATION_PCT = 8.29          # 100 * 9950 / 120000, half up to 2 dp
RISK_PRE_TEST = 28.33                # 0.30*0 + 0.20*8.29 + 0.25*40 + 0.25*66.67
RISK_FINAL = 40.83                   # 28.33 + 12.5 * 1 failure

PACK_NET_WEIGHT_KG = 8.008           # 8.008 * 62.5 = 500.5 pieces
PACK_DECLARED_COUNT = 501            # 500.5 rounded half up, per pack
PACK_TOLERANCE_PIECES = 10           # trunc(500 * 0.02)
TWO_PACKS_PER_PACK_SUM = 1002        # 501 + 501
TWO_PACKS_FROM_SUMMED_WEIGHT = 1001  # 16.016 * 62.5 = 1001.0, the wrong order


def _route_kwargs(**extra):
    """A fresh copy of the shared route so no test mutates another's payloads."""
    kwargs = copy.deepcopy(ROUTE)
    kwargs.update(extra)
    return kwargs


def _baked_lot():
    """Drive the route to ``BAKED``: the moment pass one of the risk score is written."""
    return fixtures.setup_baked_lot(**_route_kwargs())


def _certified_lot():
    """Drive the route through an accepted test to ``CERTIFIED`` behind an ISSUED cert."""
    env = fixtures.setup_certified_lot(
        proof_load_failures=0,
        tensile_failures=1,
        min_measured_core_hardness_hv=322.0,
        inspector_user_id="insp-1",
        manager_user_id="qm-1",
        cert_serial="CERT-0001",
        **_route_kwargs(),
    )
    fixtures.set_clock("2026-09-02T11:00:00Z")
    return env


def _open_weight_pack(env, label_serial, net_weight_kg=PACK_NET_WEIGHT_KG):
    """Open one BY_WEIGHT pack unit, which carries ``net_weight_kg`` and no count."""
    response = api_client.create_pack_unit(
        {
            "production_lot_id": env["lot"]["id"],
            "certification_document_id": env["certificate"]["id"],
            "label_serial": label_serial,
            "net_weight_kg": net_weight_kg,
            "label_fields_complete": True,
        },
        make_clerk_headers("ship-1"),
    )
    return validate_success(response, 201)


class TestPackDeclaredCountRoundsPerPack:
    """The declared count of a weight-packed carton, and how a lot's total is built."""

    def test_by_weight_pack_rounds_its_own_weight_up_to_501_pieces(self, api):
        """A carton weighed at 8.008 kg of a 62.5 pcs/kg part declares 501, not 500.

        PRD: "`declared_count`, the number printed on the label, is `actual_count` verbatim for a `BY_COUNT` pack, and for a `BY_WEIGHT` pack it is the pack's own `net_weight_kg` multiplied by the part's `pieces_per_kg`, rounded half up to a whole piece."

        PRD: "A pack's `declared_count` derived from weight is rounded half up to a whole piece."

        PRD: "`count_tolerance_pieces` is the part's `nominal_pack_count` multiplied by its `count_tolerance_pct`, truncated downward to a whole number of pieces — so a nominal pack of 500 at a `count_tolerance_pct` of 0.02 tolerates 10 pieces of deviation, and a nominal pack of 40 at the same tolerance tolerates none at all, because 0.8 of a piece truncates downward to 0."

        Design: Difficulty/combinatorial_formula/pack_declared_count_rounds_per_pack_before_summing
        """
        env = _certified_lot()
        pack = _open_weight_pack(env, "PK-0001")

        assert pack["pack_mode"] == "BY_WEIGHT", (
            f"Expected pack_mode BY_WEIGHT copied from the part's packaging_mode, "
            f"got {pack['pack_mode']}"
        )
        assert pack["net_weight_kg"] == pytest.approx(PACK_NET_WEIGHT_KG, abs=0.001), (
            f"Expected the weighed net mass {PACK_NET_WEIGHT_KG} to be stored verbatim, "
            f"got {pack['net_weight_kg']}"
        )
        assert pack["declared_count"] == PACK_DECLARED_COUNT, (
            f"Expected declared_count {PACK_DECLARED_COUNT} from 8.008 kg x 62.5 pcs/kg "
            f"= 500.5 rounded half up, got {pack['declared_count']}"
        )
        assert pack["count_tolerance_pieces"] == PACK_TOLERANCE_PIECES, (
            f"Expected count_tolerance_pieces {PACK_TOLERANCE_PIECES} from "
            f"trunc(500 * 0.02), got {pack['count_tolerance_pieces']}"
        )
        assert pack["status"] == "OPEN", (
            f"Expected a new pack unit to start OPEN, got {pack['status']}"
        )

    def test_each_pack_rounds_alone_so_two_cartons_declare_501_each(self, api):
        """Two 8.008 kg cartons declare 501 apiece; 16.016 kg as one figure would give 1001.

        PRD: "`declared_count`, the number printed on the label, is `actual_count` verbatim for a `BY_COUNT` pack, and for a `BY_WEIGHT` pack it is the pack's own `net_weight_kg` multiplied by the part's `pieces_per_kg`, rounded half up to a whole piece."

        PRD: "That rounding happens per pack and never on a summed weight: a lot's declared total is the sum of the already-rounded per-pack values, so the plant accepts the small accumulation of per-pack rounding rather than re-deriving a total from aggregate mass."

        Design: Difficulty/combinatorial_formula/pack_declared_count_rounds_per_pack_before_summing
        """
        env = _certified_lot()
        pack_one = _open_weight_pack(env, "PK-0001")
        pack_two = _open_weight_pack(env, "PK-0002")

        for label, pack in (("PK-0001", pack_one), ("PK-0002", pack_two)):
            assert pack["declared_count"] == PACK_DECLARED_COUNT, (
                f"Expected {label} to round its own 8.008 kg to {PACK_DECLARED_COUNT} "
                f"pieces, got {pack['declared_count']}"
            )

        declared_total = pack_one["declared_count"] + pack_two["declared_count"]
        assert declared_total == TWO_PACKS_PER_PACK_SUM, (
            f"Expected the two already-rounded declared counts to sum to "
            f"{TWO_PACKS_PER_PACK_SUM}, got {declared_total}"
        )
        assert declared_total != TWO_PACKS_FROM_SUMMED_WEIGHT, (
            f"Rounding the combined 16.016 kg once would have declared "
            f"{TWO_PACKS_FROM_SUMMED_WEIGHT} pieces; the count must be rounded per pack"
        )

    def test_lot_packed_count_sums_the_already_rounded_per_pack_counts(self, api):
        """Sealing both 501-piece cartons packs 1002 pieces out of the lot, not 1001.

        PRD: "That rounding happens per pack and never on a summed weight: a lot's declared total is the sum of the already-rounded per-pack values, so the plant accepts the small accumulation of per-pack rounding rather than re-deriving a total from aggregate mass."

        PRD: "On success the pack moves `OPEN → SEALED`, `sealed_at` is stamped from the logical clock, the lot's `packed_count` grows by `declared_count` while its `available_count` shrinks by the same amount, the lot moves `CERTIFIED → PACKED`, and the pack's `version` and the lot's `version` each increment by 1."

        Design: Difficulty/combinatorial_formula/pack_declared_count_rounds_per_pack_before_summing
        """
        env = _certified_lot()
        lot_id = env["lot"]["id"]
        before = validate_success(api.get_production_lot(lot_id, make_clerk_headers("ship-1")))
        assert before["available_count"] == AVAILABLE_AFTER_TEST, (
            f"Expected {AVAILABLE_AFTER_TEST} available pieces before packing, "
            f"got {before['available_count']}"
        )
        assert before["packed_count"] == 0, (
            f"Expected packed_count 0 before any pack is sealed, got {before['packed_count']}"
        )

        pack_one = _open_weight_pack(env, "PK-0001")
        pack_two = _open_weight_pack(env, "PK-0002")
        before_sealing = validate_success(
            api.get_production_lot(lot_id, make_clerk_headers("ship-1"))
        )

        sealed_one = validate_success(api.seal_pack_unit(pack_one["id"], make_clerk_headers("ship-1")))
        assert sealed_one["status"] == "SEALED", (
            f"Expected PK-0001 to be SEALED, got {sealed_one['status']}"
        )
        after_first = validate_success(
            api.get_production_lot(lot_id, make_clerk_headers("ship-1"))
        )
        assert after_first["packed_count"] == PACK_DECLARED_COUNT, (
            f"Expected packed_count {PACK_DECLARED_COUNT} after the first seal, "
            f"got {after_first['packed_count']}"
        )
        assert after_first["available_count"] == AVAILABLE_AFTER_TEST - PACK_DECLARED_COUNT, (
            f"Expected available_count {AVAILABLE_AFTER_TEST - PACK_DECLARED_COUNT} after "
            f"the first seal, got {after_first['available_count']}"
        )

        sealed_two = validate_success(api.seal_pack_unit(pack_two["id"], make_clerk_headers("ship-1")))
        assert sealed_two["status"] == "SEALED", (
            f"Expected PK-0002 to be SEALED, got {sealed_two['status']}"
        )

        after = validate_success(api.get_production_lot(lot_id, make_clerk_headers("ship-1")))
        assert after["packed_count"] == TWO_PACKS_PER_PACK_SUM, (
            f"Expected packed_count {TWO_PACKS_PER_PACK_SUM} — the sum of two "
            f"already-rounded 501-piece declarations — got {after['packed_count']}"
        )
        assert after["packed_count"] != TWO_PACKS_FROM_SUMMED_WEIGHT, (
            f"Deriving the total from the summed 16.016 kg would have packed "
            f"{TWO_PACKS_FROM_SUMMED_WEIGHT} pieces; the PRD sums the per-pack values"
        )
        assert after["available_count"] == AVAILABLE_AFTER_TEST - TWO_PACKS_PER_PACK_SUM, (
            f"Expected available_count "
            f"{AVAILABLE_AFTER_TEST - TWO_PACKS_PER_PACK_SUM} after both seals, "
            f"got {after['available_count']}"
        )
        assert after["process_state"] == "PACKED", (
            f"Expected the lot to move CERTIFIED -> PACKED on the first seal, "
            f"got {after['process_state']}"
        )
        assert after["version"] == before_sealing["version"] + 2, (
            f"Expected the lot's version to advance once per seal to "
            f"{before_sealing['version'] + 2}, got {after['version']}"
        )
        left = after["headed_count"] + after["heading_scrap_count"]
        right = (
            after["available_count"]
            + after["scrap_count"]
            + after["destructive_test_count"]
            + after["packed_count"]
        )
        assert left == right, (
            f"Piece ledger broken after packing: {left} headed and scrapped against "
            f"{right} accounted for"
        )


class TestRiskScoreTwoPassOrdering:
    """Pass one freezes the sampling severity; pass two adds the failure penalty."""

    def test_bake_close_writes_the_pre_test_score_as_one_rounded_weighted_sum(self, api):
        """Closing the relief bake scores the lot 28.33 from its four weighted terms.

        PRD: "The **decarburization term** is 100 multiplied by the governing run's `total_decarb_depth_mm`, divided by the part's `max_decarb_depth_mm`, rounded half up to two decimal places and then capped at 100."

        PRD: "The score is 0.30 multiplied by the heat term, plus 0.20 multiplied by the tool term, plus 0.25 multiplied by the bake term, plus 0.25 multiplied by the decarburization term, with the sum rounded half up to two decimal places exactly once at the end — the individual weighted terms are never rounded on their own."

        PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

        Design: Difficulty/combinatorial_formula/risk_score_two_pass_freezes_severity_before_failure_penalty
        """
        env = _baked_lot()
        lot = env["lot"]

        assert lot["process_state"] == "BAKED", (
            f"Expected the lot to reach BAKED when the relief bake closed, "
            f"got {lot['process_state']}"
        )
        assert lot["tool_utilization_pct"] == pytest.approx(TOOL_UTILIZATION_PCT, abs=0.001), (
            f"Expected tool_utilization_pct {TOOL_UTILIZATION_PCT} from "
            f"100 * {HEADED_TOTAL} / 120000, got {lot['tool_utilization_pct']}"
        )
        assert env["heat_treat_run"]["total_decarb_depth_mm"] == pytest.approx(0.100, abs=0.001), (
            f"Expected total_decarb_depth_mm 0.100 for a 0.42 carbon potential, "
            f"got {env['heat_treat_run']['total_decarb_depth_mm']}"
        )
        assert env["plating_run"]["bake_delay_hours"] == pytest.approx(3.0, abs=0.001), (
            f"Expected bake_delay_hours 3.0 between plating at 02:00 and the bake at "
            f"05:00, got {env['plating_run']['bake_delay_hours']}"
        )
        assert lot["risk_score_pre_test"] == pytest.approx(RISK_PRE_TEST, abs=0.001), (
            f"Expected risk_score_pre_test {RISK_PRE_TEST} from "
            f"0.30*0 + 0.20*8.29 + 0.25*40 + 0.25*66.67 rounded once, "
            f"got {lot['risk_score_pre_test']}"
        )
        assert lot["risk_score_pre_test"] < 40.0, (
            f"Pass one must land below the 40.0 tightening threshold, "
            f"got {lot['risk_score_pre_test']}"
        )

    def test_opening_the_test_freezes_normal_severity_from_the_pass_one_score(self, api):
        """The sampling plan reads the 28.33 pass-one score and freezes NORMAL on the lot.

        PRD: "Severity is `TIGHTENED` when either of two things is true: the lot's `risk_score_pre_test` is at least 40.0, or a rejected test already exists anywhere in the plant on a production lot sharing both the same `part_spec_id` and the same `traceability_heat_id` as this lot."

        PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

        PRD: "The chosen severity is copied onto the test as `severity` and simultaneously frozen onto the lot as `inspection_severity`; later movement in the lot's risk score never re-derives it, and it is always the pass-one score that feeds the decision."

        Design: Difficulty/combinatorial_formula/risk_score_two_pass_freezes_severity_before_failure_penalty
        """
        env = _baked_lot()
        lot_id = env["lot"]["id"]
        assert env["lot"]["available_count"] == AVAILABLE_AFTER_SECONDARY, (
            f"Expected {AVAILABLE_AFTER_SECONDARY} available pieces at test entry, "
            f"got {env['lot']['available_count']}"
        )

        test = fixtures.open_lot_test(lot_id, inspector_user_id="insp-1")

        assert test["severity"] == "NORMAL", (
            f"Expected severity NORMAL from a pass-one score of {RISK_PRE_TEST}, "
            f"got {test['severity']}"
        )
        assert test["sample_size"] == SAMPLE_SIZE, (
            f"Expected sample_size {SAMPLE_SIZE} from max(8, ceil(sqrt(9740))), "
            f"got {test['sample_size']}"
        )
        assert test["acceptance_number"] == 1, (
            f"Expected acceptance_number 1 for a normal-inspection sample of "
            f"{SAMPLE_SIZE} pieces, got {test['acceptance_number']}"
        )
        assert test["result"] == "PENDING", (
            f"Expected a new test to start PENDING, got {test['result']}"
        )

        lot = validate_success(api.get_production_lot(lot_id, fixtures.INSPECTOR))
        assert lot["inspection_severity"] == "NORMAL", (
            f"Expected NORMAL frozen onto the lot as inspection_severity, "
            f"got {lot['inspection_severity']}"
        )
        assert lot["risk_score_pre_test"] == pytest.approx(RISK_PRE_TEST, abs=0.001), (
            f"Expected the pass-one score to stay {RISK_PRE_TEST} when the plan was "
            f"derived, got {lot['risk_score_pre_test']}"
        )
        assert lot["process_state"] == "TESTING", (
            f"Expected the lot to move BAKED -> TESTING, got {lot['process_state']}"
        )
        assert lot["destructive_test_count"] == SAMPLE_SIZE, (
            f"Expected destructive_test_count {SAMPLE_SIZE}, "
            f"got {lot['destructive_test_count']}"
        )
        assert lot["available_count"] == AVAILABLE_AFTER_TEST, (
            f"Expected available_count {AVAILABLE_AFTER_TEST} after the sample was "
            f"consumed, got {lot['available_count']}"
        )

    def test_failure_penalty_lifts_the_final_score_past_40_without_retightening(self, api):
        """One failure takes the score to 40.83, yet the frozen NORMAL plan still accepts.

        PRD: "`risk_score_final` adds test evidence to the frozen pre-test value: it is `risk_score_pre_test` plus 12.5 points for each failure counted in `total_failures`, capped at 100, and rounded half up to two decimal places."

        PRD: "Once computed, `risk_score_pre_test` is frozen: the second scoring pass described in §3.7 never recomputes it."

        PRD: "The chosen severity is copied onto the test as `severity` and simultaneously frozen onto the lot as `inspection_severity`; later movement in the lot's risk score never re-derives it, and it is always the pass-one score that feeds the decision."

        PRD: "The verdict is a straight comparison against the frozen plan: `ACCEPT` when `total_failures` is at most `acceptance_number`, and `REJECT` when it is greater."

        Design: Difficulty/combinatorial_formula/risk_score_two_pass_freezes_severity_before_failure_penalty
        """
        env = _baked_lot()
        lot_id = env["lot"]["id"]
        test = fixtures.open_lot_test(lot_id, inspector_user_id="insp-1")

        closed = fixtures.record_lot_test_results(
            test["id"],
            inspector_user_id="insp-1",
            proof_load_failures=0,
            tensile_failures=1,
            min_measured_core_hardness_hv=322.0,
        )

        assert closed["total_failures"] == 1, (
            f"Expected total_failures 1 from 0 proof-load and 1 tensile failure, "
            f"got {closed['total_failures']}"
        )
        assert closed["severity"] == "NORMAL", (
            f"Expected the test's frozen severity to stay NORMAL, got {closed['severity']}"
        )
        assert closed["acceptance_number"] == 1, (
            f"Expected the frozen acceptance_number 1 to survive the second pass, "
            f"got {closed['acceptance_number']}"
        )
        assert closed["result"] == "ACCEPT", (
            f"Expected ACCEPT with 1 failure against acceptance_number 1, "
            f"got {closed['result']}"
        )

        lot = validate_success(api.get_production_lot(lot_id, fixtures.INSPECTOR))
        assert lot["risk_score_pre_test"] == pytest.approx(RISK_PRE_TEST, abs=0.001), (
            f"Expected the frozen pass-one score to stay {RISK_PRE_TEST}, "
            f"got {lot['risk_score_pre_test']}"
        )
        assert lot["risk_score_final"] == pytest.approx(RISK_FINAL, abs=0.001), (
            f"Expected risk_score_final {RISK_FINAL} from {RISK_PRE_TEST} + 12.5, "
            f"got {lot['risk_score_final']}"
        )
        assert lot["risk_score_final"] >= 40.0, (
            f"The second pass must carry the score to or past the 40.0 tightening "
            f"threshold for this case to be probative, got {lot['risk_score_final']}"
        )
        assert lot["inspection_severity"] == "NORMAL", (
            f"Expected inspection_severity to stay NORMAL even though the final score "
            f"{lot['risk_score_final']} is at or above 40.0, "
            f"got {lot['inspection_severity']}"
        )
        assert lot["process_state"] == "TESTED", (
            f"Expected the lot to move TESTING -> TESTED on ACCEPT, "
            f"got {lot['process_state']}"
        )
        assert lot["disposition"] == "IN_PROCESS", (
            f"Expected an accepted lot to stay IN_PROCESS, got {lot['disposition']}"
        )
        assert lot["achieved_strength_class"] == "CLASS_10_9", (
            f"Expected achieved_strength_class CLASS_10_9 for a weakest piece of "
            f"322.0 HV, got {lot['achieved_strength_class']}"
        )
