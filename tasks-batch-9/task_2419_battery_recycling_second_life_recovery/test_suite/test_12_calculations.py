"""Derived figures: the capacity projection, the fee tier table and the triage score."""
from test_helpers import (
    assert_settlement,
    assert_triage_decision,
    factories as f,
    fixtures as fx,
    validate_success,
)

_PROJECTION_CLOCK = "2026-08-01T00:00:00.000Z"
_THOUSAND_KG = {"gross_mass_kg": 1010.0, "packaging_tare_kg": 10.0}


def _campus_with_three_thousand_kilogrammes_received(api):
    """A campus whose mechanical ceiling is 105.0 kg a day carrying three
    thousand-kilogramme shipments received at the current clock position."""
    ctx = fx.bootstrap_network(
        api,
        clock=_PROJECTION_CLOCK,
        facility={"mech_capacity_kg_per_day": 105.0},
        quotes=None,
    )
    ctx["received"] = [
        fx.book_intake(api, ctx["supplier"]["id"], ctx["facility"]["id"], **_THOUSAND_KG)
        for _ in range(3)
    ]
    return ctx


def _projection(api, facility_id, horizon_days=20):
    return validate_success(
        api.get_capacity_projection(facility_id, fx.ADMIN, params={"horizon_days": horizon_days})
    )


def test_the_projection_ramps_the_baseline_and_names_the_first_deficit_day(api):
    """Three shipments inside the lookback set the baseline, each horizon day is
    rounded before the sum, and the first day strictly above the mechanical ceiling is
    reported with its shortfall.

    PRD §3.2: "For each day numbered 1 through `horizon_days`, the projected mass for
    that day is the baseline multiplied by one plus four thousandths of the day number —
    a growth rate of 0.4 percent per day compounding linearly on the day index —
    rounded half up to three decimals **for that day, before any summing**."

    Design: Corner/calculations/capacity_projection_growth_curve_and_first_deficit_day
    """
    ctx = _campus_with_three_thousand_kilogrammes_received(api)

    projection = _projection(api, ctx["facility"]["id"])

    assert float(projection["baseline_kg_per_day"]) == 100.000
    assert projection["horizon_days"] == 20
    assert float(projection["mech_capacity_kg_per_day"]) == 105.0
    assert float(projection["hydro_capacity_kg_per_day"]) == 2000.0
    assert float(projection["projected_input_kg"]) == 2084.000
    assert projection["first_deficit_day"] == 13, (
        "day 13 projects 105.200 while day 12 projects 104.800, and the comparison is strict"
    )
    assert projection["first_deficit_date"] == "2026-08-14T00:00:00.000Z"
    assert float(projection["deficit_kg"]) == 0.200

    for intake in ctx["received"]:
        assert fx.read_intake(api, intake["id"])["version"] == 1, (
            "the projection persists nothing"
        )


def test_quarantined_mass_leaves_the_projection_baseline(api):
    """Rejecting one shipment's manifest quarantines it, and the very next projection
    re-bases on the two survivors and loses its deficit day entirely.

    PRD §3.2: "counting only shipments whose `custody_state` is `RECEIVED`,
    `IDENTIFIED`, `DISCHARGED`, `PACKAGED` or `RELEASED`, so that quarantined mass is
    excluded from the return stream."

    Design: Corner/calculations/capacity_projection_excludes_quarantined_intake_mass
    """
    ctx = _campus_with_three_thousand_kilogrammes_received(api)
    facility_id = ctx["facility"]["id"]
    doomed = ctx["received"][2]["id"]

    before = _projection(api, facility_id)
    assert float(before["baseline_kg_per_day"]) == 100.000
    assert float(before["projected_input_kg"]) == 2084.000

    fx.identify_chemistry(api, doomed, "NMC622")
    fx.discharge(api, doomed, soc_pct=12.0)
    manifest = fx.submit_manifest(api, doomed)
    rejected = fx.reject_manifest(api, doomed, manifest["id"], "UN_NUMBER_MISMATCH")
    assert rejected["status"] == "REJECTED"

    quarantined = fx.read_intake(api, doomed)
    assert quarantined["custody_state"] == "QUARANTINED"
    assert quarantined["hold_reason"] == "MANIFEST_REJECTED"

    after = _projection(api, facility_id)
    assert float(after["baseline_kg_per_day"]) == 66.667
    assert float(after["projected_input_kg"]) == 1389.340
    assert after["first_deficit_day"] is None
    assert after["first_deficit_date"] is None
    assert float(after["deficit_kg"]) == 0.0


# --------------------------------------------------------------------------
# The processing-fee tier table is read on the gross, as an average rate
# --------------------------------------------------------------------------

def _settlement_for_a_pure_nickel_shipment(api, ctx, gross_mass_kg):
    """Release one shipment declaring a hundred percent nickel and no contamination,
    then read the settlement the release cut."""
    walked = fx.advance_intake(
        ctx,
        stop_after="manifest_closed",
        intake={
            "gross_mass_kg": gross_mass_kg,
            "packaging_tare_kg": 10.0,
            "declared_ni_pct": 100.0,
            "moisture_pct": 0.0,
            "foreign_material_pct": 0.0,
        },
        modules=(),
    )
    intake_id = walked["intake"]["id"]
    fx.release(api, intake_id)
    return fx.read_settlement(api, fx.settlement_for_intake(api, intake_id)["id"])


def test_one_cent_of_gross_re_rates_the_whole_settlement_at_the_next_fee_tier(api):
    """Three shipments land on the tier edges: a single cent of extra gross moves the
    rate from twelve to nine percent and the whole gross is re-rated, not just the
    excess.

    PRD §3.5: "**Step two** selects `processing_fee_pct` from a three-band tier table
    read on `gross_cents`: a gross below 500,000 cents attracts 12 percent, a gross of
    at least 500,000 cents and below 2,000,000 cents attracts 9 percent, and a gross of
    2,000,000 cents or more attracts 6 percent."

    Design: Corner/calculations/processing_fee_tier_boundaries_at_gross_499999_and_500000
    """
    ctx = fx.bootstrap_network(api)

    low = _settlement_for_a_pure_nickel_shipment(api, ctx, 479.924)
    assert_settlement(low)
    assert low["gross_cents"] == 499999
    assert float(low["processing_fee_pct"]) == 0.12
    assert low["processing_fee_cents"] == 60000
    assert low["quality_deduction_cents"] == 0
    assert low["pre_surcharge_net_cents"] == 439999
    assert low["hazmat_surcharge_cents"] == 5320
    assert low["net_payable_cents"] == 434679

    middle = _settlement_for_a_pure_nickel_shipment(api, ctx, 479.925)
    assert middle["gross_cents"] == 500000
    assert float(middle["processing_fee_pct"]) == 0.09
    assert middle["processing_fee_cents"] == 45000
    assert middle["pre_surcharge_net_cents"] == 455000
    assert middle["hazmat_surcharge_cents"] == 5320
    assert middle["net_payable_cents"] == 449680
    assert middle["net_payable_cents"] - low["net_payable_cents"] == 15001, (
        "the tier rate is an average rate applied to the whole gross, not a marginal one"
    )

    top = _settlement_for_a_pure_nickel_shipment(api, ctx, 2010.0)
    assert top["gross_cents"] == 2128000
    assert float(top["processing_fee_pct"]) == 0.06
    assert top["processing_fee_cents"] == 127680
    assert top["pre_surcharge_net_cents"] == 2000320
    assert top["hazmat_surcharge_cents"] == 14500
    assert top["net_payable_cents"] == 1985820

    ids = {low["id"], middle["id"], top["id"]}
    assert len(ids) == 3
    for settlement in (low, middle, top):
        assert settlement["variant"] == "PROVISIONAL"
        assert settlement["state"] == "DRAFT"


# --------------------------------------------------------------------------
# The triage score: the cycle cap, the band floors and the rounding step
# --------------------------------------------------------------------------

def _packaged_shipment_carrying(api, modules):
    """A thousand-kilogramme shipment walked to PACKAGED so its modules are
    triageable."""
    ctx = fx.bootstrap_network(api, quotes=None)
    walked = fx.advance_intake(
        ctx, stop_after="package", intake=dict(_THOUSAND_KG), modules=modules
    )
    return walked["modules"]


def test_the_cycle_penalty_is_capped_and_the_imbalance_term_still_bites(api):
    """A thousand extra cycles change nothing once the age penalty sits on its cap,
    while cell-to-cell spread costs eight tenths of a point per percentage point.

    PRD §3.4: "Second, a cycle penalty is computed as the module's `cycle_count`
    divided by 200, giving one penalty point for every two hundred lifetime equivalent
    full cycles, and then capped at 20.0 points, so a very heavily cycled module never
    loses more than twenty points to age."

    Design: Corner/calculations/cycle_penalty_cap_stops_the_score_from_drifting_below_the_band
    """
    modules = _packaged_shipment_carrying(
        api,
        (
            {
                "serial_code": "M-1",
                "min_cell_capacity_pct": 95.0,
                "mean_cell_capacity_pct": 95.0,
                "cycle_count": 4000,
            },
            {
                "serial_code": "M-2",
                "min_cell_capacity_pct": 95.0,
                "mean_cell_capacity_pct": 95.0,
                "cycle_count": 5000,
            },
            {
                "serial_code": "M-3",
                "min_cell_capacity_pct": 78.0,
                "mean_cell_capacity_pct": 80.0,
                "cycle_count": 1000,
            },
        ),
    )

    on_the_cap = fx.triage_module(api, modules[0]["id"], scoring_variant="CONSERVATIVE")
    over_the_cap = fx.triage_module(api, modules[1]["id"], scoring_variant="CONSERVATIVE")
    imbalanced = fx.triage_module(api, modules[2]["id"], scoring_variant="FLEET_AVERAGE")

    assert float(on_the_cap["score"]) == 75.00
    assert float(over_the_cap["score"]) == 75.00, (
        "the raw 25.0 points of age penalty are clamped, so the extra cycles are free"
    )
    assert on_the_cap["grade"] == "B"
    assert over_the_cap["grade"] == "B"
    assert on_the_cap["disposition"] == "SECOND_LIFE"

    assert float(imbalanced["score"]) == 73.40
    assert imbalanced["grade"] == "B"
    assert imbalanced["disposition"] == "SECOND_LIFE"

    for module, decision in zip(modules, (on_the_cap, over_the_cap, imbalanced)):
        stored = validate_success(api.get_module(module["id"], fx.OPERATOR))
        assert stored["status"] == "SECOND_LIFE_QUEUE"
        assert float(stored["second_life_score"]) == float(decision["score"])


def test_every_grade_band_floor_is_an_inclusive_lower_bound(api):
    """Four modules sitting exactly on 80.00, 70.00, 60.00 and one hundredth below the
    C floor take all four bands and all three queues.

    PRD §3.4: "Fifth, the `grade` band is read off the **rounded** score against
    inclusive lower bounds: a score of at least 80.0 is grade `A`, otherwise at least
    70.0 is grade `B`, otherwise at least 60.0 is grade `C`, and anything below that is
    grade `D`."

    Design: Corner/calculations/grade_band_floors_are_inclusive_lower_bounds
    """
    modules = _packaged_shipment_carrying(
        api,
        tuple(
            {
                "serial_code": serial,
                "min_cell_capacity_pct": capacity,
                "mean_cell_capacity_pct": capacity,
                "cycle_count": f.OMIT,
            }
            for serial, capacity in (
                ("A-80", 80.0),
                ("B-70", 70.0),
                ("C-60", 60.0),
                ("D-5999", 59.99),
            )
        ),
    )
    assert modules[0]["cycle_count"] == 0, "an omitted cycle count defaults to zero"

    expected = (
        (80.00, "A", "REFURBISH", "REFURB_QUEUE"),
        (70.00, "B", "SECOND_LIFE", "SECOND_LIFE_QUEUE"),
        (60.00, "C", "SECOND_LIFE", "SECOND_LIFE_QUEUE"),
        (59.99, "D", "MATERIAL_RECOVERY", "RECOVERY_QUEUE"),
    )
    for module, (score, grade, disposition, status) in zip(modules, expected):
        decision = fx.triage_module(api, module["id"], scoring_variant="CONSERVATIVE")
        assert_triage_decision(decision)
        assert float(decision["score"]) == score
        assert decision["grade"] == grade
        assert decision["disposition"] == disposition
        assert validate_success(api.get_module(module["id"], fx.OPERATOR))["status"] == status


def test_the_score_is_rounded_half_up_before_the_band_is_chosen(api):
    """One lifetime cycle costs five thousandths of a point, so 79.995 rounds up into
    band A while two cycles land in band B.

    PRD §3.4: "Fourth, the `score` is the chosen state-of-health input less the cycle
    penalty and less the imbalance penalty, rounded half up to two decimal places."

    Design: Corner/calculations/score_rounds_half_up_before_the_grade_band_is_chosen
    """
    modules = _packaged_shipment_carrying(
        api,
        (
            {
                "serial_code": "ONE-CYCLE",
                "min_cell_capacity_pct": 80.0,
                "mean_cell_capacity_pct": 80.0,
                "cycle_count": 1,
            },
            {
                "serial_code": "TWO-CYCLE",
                "min_cell_capacity_pct": 80.0,
                "mean_cell_capacity_pct": 80.0,
                "cycle_count": 2,
            },
        ),
    )

    one_cycle = fx.triage_module(api, modules[0]["id"], scoring_variant="CONSERVATIVE")
    assert float(one_cycle["score"]) == 80.00, "79.995 rounds half up, never down"
    assert one_cycle["grade"] == "A"
    assert one_cycle["disposition"] == "REFURBISH"

    two_cycles = fx.triage_module(api, modules[1]["id"], scoring_variant="CONSERVATIVE")
    assert float(two_cycles["score"]) == 79.99
    assert two_cycles["grade"] == "B"
    assert two_cycles["disposition"] == "SECOND_LIFE"

    assert validate_success(api.get_module(modules[0]["id"], fx.OPERATOR))["status"] == (
        "REFURB_QUEUE"
    )
    assert validate_success(api.get_module(modules[1]["id"], fx.OPERATOR))["status"] == (
        "SECOND_LIFE_QUEUE"
    )
