"""Triage scoring variants and the three-way disposition fork."""
from test_helpers import (
    assert_module_status_matches_disposition,
    assert_triage_decision,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_PROCESS

# One pack whose worst cell is far below the pack mean, so the two scoring
# variants land in different grade bands.
_DIVERGENT_MODULE = {
    "mass_kg": 100.0,
    "min_cell_capacity_pct": 68.0,
    "mean_cell_capacity_pct": 82.0,
    "cycle_count": 1200,
}


def _divergent_pair(api):
    """A packaged shipment carrying two identical modules, one for each variant."""
    return fx.build_world(
        api,
        stop_after="package",
        intake={
            "intake": {"gross_mass_kg": 850.0, "packaging_tare_kg": 50.0},
            "modules": (
                dict(_DIVERGENT_MODULE, serial_code="M-C"),
                dict(_DIVERGENT_MODULE, serial_code="M-F"),
            ),
            "soc_pct": 15.0,
        },
    )


def test_conservative_variant_scores_the_worst_cell_into_grade_d(api):
    """The CONSERVATIVE variant reads the worst cell in the pack, which drops this
    module into grade D and routes it to material recovery.

    PRD §3.4: "the `CONSERVATIVE` variant — the warranty-grade assessment used when
    a module might be resold — takes the module's `min_cell_capacity_pct`, the worst
    cell in the pack"

    Design: Difficulty/dual_variant_calc/module_triage_score_conservative_vs_fleet_average_diverges_grade
    """
    ctx = _divergent_pair(api)
    module = ctx["modules"][0]

    decision = fx.triage_module(api, module["id"], scoring_variant="CONSERVATIVE")

    assert_triage_decision(decision)
    assert float(decision["score"]) == 50.80
    assert decision["grade"] == "D"
    assert decision["derived_disposition"] == "MATERIAL_RECOVERY"
    assert decision["disposition"] == "MATERIAL_RECOVERY"

    stored = validate_success(api.get_module(module["id"], fx.ENGINEER))
    assert stored["status"] == "RECOVERY_QUEUE"
    assert_module_status_matches_disposition(stored, decision)


def test_fleet_average_variant_scores_the_pack_mean_into_grade_c(api):
    """The FLEET_AVERAGE variant reads the pack mean instead, scoring the identical
    module fourteen points higher and routing it to second life.

    PRD §3.4: "Whenever the mean cell capacity exceeds the minimum, `FLEET_AVERAGE`
    produces a strictly higher score than `CONSERVATIVE`"

    Design: Difficulty/dual_variant_calc/module_triage_score_conservative_vs_fleet_average_diverges_grade
    """
    ctx = _divergent_pair(api)
    conservative = fx.triage_module(
        api, ctx["modules"][0]["id"], scoring_variant="CONSERVATIVE"
    )
    fleet = fx.triage_module(api, ctx["modules"][1]["id"], scoring_variant="FLEET_AVERAGE")

    assert_triage_decision(fleet)
    assert float(fleet["score"]) == 64.80
    assert fleet["grade"] == "C"
    assert fleet["derived_disposition"] == "SECOND_LIFE"
    assert fleet["disposition"] == "SECOND_LIFE"
    assert round(float(fleet["score"]) - float(conservative["score"]), 2) == 14.00

    stored = validate_success(api.get_module(ctx["modules"][1]["id"], fx.ENGINEER))
    assert stored["status"] == "SECOND_LIFE_QUEUE"
    assert_module_status_matches_disposition(stored, fleet)


# --------------------------------------------------------------------------
# The three-way fork
# --------------------------------------------------------------------------

_FORK_MODULES = (
    {
        "serial_code": "M-R",
        "mass_kg": 100.0,
        "min_cell_capacity_pct": 88.0,
        "mean_cell_capacity_pct": 90.0,
        "cycle_count": 200,
    },
    {
        "serial_code": "M-S",
        "mass_kg": 100.0,
        "min_cell_capacity_pct": 76.0,
        "mean_cell_capacity_pct": 78.0,
        "cycle_count": 400,
    },
    {
        "serial_code": "M-V",
        "mass_kg": 100.0,
        "min_cell_capacity_pct": 58.0,
        "mean_cell_capacity_pct": 62.0,
        "cycle_count": 1200,
    },
)


def _fork_world(api, stop_after="package"):
    """One shipment carrying a refurbishable, a second-life and a scrap module."""
    ctx = fx.build_world(
        api,
        stop_after=stop_after,
        intake={
            "intake": {"gross_mass_kg": 350.0, "packaging_tare_kg": 50.0},
            "modules": _FORK_MODULES,
        },
    )
    ctx["decisions"] = [
        fx.triage_module(api, module["id"], scoring_variant="CONSERVATIVE")
        for module in ctx["modules"]
    ]
    return ctx


def test_triage_fork_routes_three_grades_to_three_queues(api):
    """One scoring pass over three packs takes all three branches of the fork, each
    with its own module status.

    PRD §3.4: "The resolved disposition forks the module's lifecycle into three
    queues, and the three branches carry genuinely different downstream
    consequences."

    Design: Difficulty/non_linear_state_machine/module_triage_fork_three_branches_divergent_side_effects
    """
    ctx = _fork_world(api)

    expected = [
        (85.40, "A", "REFURBISH", "REFURB_QUEUE"),
        (72.40, "B", "SECOND_LIFE", "SECOND_LIFE_QUEUE"),
        (48.80, "D", "MATERIAL_RECOVERY", "RECOVERY_QUEUE"),
    ]
    for module, decision, (score, grade, disposition, status) in zip(
        ctx["modules"], ctx["decisions"], expected
    ):
        assert_triage_decision(decision)
        assert float(decision["score"]) == score
        assert decision["grade"] == grade
        assert decision["derived_disposition"] == disposition
        assert decision["disposition"] == disposition, (
            "with no override supplied the effective disposition is the derived one"
        )
        assert decision["status"] == "ACTIVE"
        stored = validate_success(api.get_module(module["id"], fx.ENGINEER))
        assert stored["status"] == status
        assert_module_status_matches_disposition(stored, decision)

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["module_mass_total_kg"]) == 300.0
    assert float(intake["unassigned_mass_kg"]) == 300.0, (
        "triage routes modules but moves no mass into the recovery ledger"
    )


def test_only_the_material_recovery_branch_is_chargeable_into_a_lot(api):
    """The refurbishment branch is reserved for whole-module resale and a charge
    naming it is refused, while the scrap branch charges.

    PRD §3.7: "every module named must have `status` `RECOVERY_QUEUE`, otherwise
    `ERR_MODULE_NOT_IN_RECOVERY_QUEUE`"

    Design: Difficulty/non_linear_state_machine/module_triage_fork_three_branches_divergent_side_effects
    """
    # PRD §3.5 requires `compliance_state` `MANIFEST_CLOSED` before release, so the
    # shipment is walked through manifest submission and counter-signature first.
    ctx = _fork_world(api, stop_after="manifest_closed")
    refurb, second_life, scrap = ctx["modules"]

    fx.release(api, ctx["intake"]["id"])
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"])
    ctx["campaign"] = fx.create_campaign(api, ctx["line"]["id"])
    fx.move_clock(api, CLOCK_PROCESS)
    fx.start_campaign(api, ctx["campaign"]["id"])
    lot = fx.open_lot(api, ctx["campaign"]["id"])

    for blocked in (refurb, second_life):
        response = api.charge_lot(
            lot["id"], f.charge_lot_payload([blocked["id"]], lot["version"]), fx.OPERATOR
        )
        validate_error(response, "ERR_MODULE_NOT_IN_RECOVERY_QUEUE", 409)

    charged = fx.charge_lot(api, lot["id"], [scrap["id"]])
    assert charged["status"] == "CHARGED"
    assert float(charged["charged_mass_kg"]) == 100.000
