"""Charge roll-ups on a moulding cycle (PRD.md sections 2.4, 3.2).

Three roll-ups are recomputed on every charge write: ``charged_mass_kg``,
``weighted_melt_index_g10min`` and the blended regrind percentage. Each one has a
declared scale and a declared *order* of rounding, and the interesting failures
are all arithmetic: dividing after rounding instead of before, rounding half-even
instead of half-up, averaging per-charge percentages instead of re-deriving the
blend from the two mass totals, or leaving a ``RELEASED`` row in the input set.
"""

from test_helpers import (
    assert_at_most_scale,
    assert_resin_ledger_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    release_charge_payload,
    reserve_charge,
    schedule_cycle,
    validate_success,
)


def _p5_exact(actual, expected, places, label):
    """Assert a derived decimal is stored at its declared scale and exact value.

    PRD.md section 2.4 fixes both the scale and the rounding mode of every derived
    decimal, so a value that is numerically close but stored unrounded is wrong.
    """
    assert_at_most_scale(actual, places, label)
    assert dec(actual) == dec(expected), f"{label}: expected {expected}, got {actual!r}"


def _p5_two_lot_plant():
    """A 40.000 kg single-cavity plant plus two lots differing only in melt index.

    The mould is single-cavity at the model's full nominal charge, so PRD.md
    section 3.4 gives a tool ``nominal_charge_kg`` of 40.000 and both lots qualify
    for the model on every clause of PRD.md section 3.2.
    """
    ctx = create_plant_baseline(
        model_overrides={"nominal_charge_kg": 40.0},
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": 40.0},
    )
    ctx["lot_a"] = create_resin_lot(melt_index_g10min=3.0, received_kg=100.0)
    ctx["lot_b"] = create_resin_lot(melt_index_g10min=4.05, received_kg=100.0)
    order = create_production_order(ctx, ordered_qty=1)
    ctx["production_order"] = order
    ctx["molding_cycle"] = schedule_cycle(ctx, order)
    return ctx


def test_weighted_melt_index_divides_then_rounds_once_to_two_decimals(api, admin_headers):
    """A blend of exactly 3.525 lands on 3.53, not on 3.52.

    PRD.md section 3.2 defines the roll-up: "`weighted_melt_index_g10min` is the
    mass-weighted mean melt index: the sum, over participating charges, of
    `charge_kg` multiplied by that charge's lot's `melt_index_g10min`, divided by
    `charged_mass_kg`, and rounded to two decimals *once* at the end — the
    per-charge products are never rounded individually, because doing so drifts."
    PRD.md section 2.4 pins the mode: "Unless a calculation says otherwise,
    rounding is half-up at the stated number of decimal places, and every
    intermediate result that a later step reads is rounded before that step runs."
    PRD.md section 3.2 also fixes the companion masses: "`charged_mass_kg` is the
    sum of `charge_kg` over the participating charges rounded to three decimals",
    and per charge "`virgin_kg` is `charge_kg` minus `regrind_kg` rounded to three
    decimals, and `charge_regrind_pct` is `regrind_kg` divided by `charge_kg` times
    100 rounded to two decimals."

    Design: Corner/calculations/calc_correct_result_cycle_charge_rollup_divide_then_round_melt_index
    """
    ctx = _p5_two_lot_plant()
    cycle = ctx["molding_cycle"]

    charge_a = reserve_charge(ctx, cycle, ctx["lot_a"], charge_kg=20.0, regrind_kg=2.0)
    charge_b = reserve_charge(ctx, cycle, ctx["lot_b"], charge_kg=20.0, regrind_kg=2.0)

    rolled = api.read_entity("get_molding_cycle", cycle["id"], ctx["operator_headers"])
    _p5_exact(rolled["charged_mass_kg"], "40.000", 3, "charged_mass_kg")
    # 20.000 * 3.00 + 20.000 * 4.05 = 141.00000, over 40.000 = 3.525 exactly.
    _p5_exact(rolled["weighted_melt_index_g10min"], "3.53", 2, "weighted_melt_index_g10min")
    # (2.000 + 2.000) / 40.000 * 100 = 10.000.
    _p5_exact(rolled["cycle_regrind_pct"], "10.00", 2, "cycle_regrind_pct")
    assert rolled["status"] == "SCHEDULED", (
        "the roll-ups are recomputed on charge create, so the cycle is still SCHEDULED"
    )

    for label, charge in (("charge_a", charge_a), ("charge_b", charge_b)):
        stored = api.read_entity("get_resin_charge", charge["id"], ctx["resin_tech_headers"])
        _p5_exact(stored["virgin_kg"], "18.000", 3, f"{label}.virgin_kg")
        _p5_exact(stored["charge_regrind_pct"], "10.00", 2, f"{label}.charge_regrind_pct")
        assert stored["status"] == "RESERVED", f"{label}: expected RESERVED, got {stored['status']}"

    for label, lot in (("lot_a", ctx["lot_a"]), ("lot_b", ctx["lot_b"])):
        stored = api.read_entity("get_resin_lot", lot["id"], admin_headers)
        _p5_exact(stored["available_kg"], "80.000", 3, f"{label}.available_kg")
        _p5_exact(stored["reserved_kg"], "20.000", 3, f"{label}.reserved_kg")
        _p5_exact(stored["consumed_kg"], "0.000", 3, f"{label}.consumed_kg")
        assert_resin_ledger_conserved(stored)


def test_released_charge_drops_out_of_the_cycle_rollups(api, admin_headers):
    """A third charge moves the blend, and releasing it restores the old blend exactly.

    PRD.md section 3.2 fixes the input set: "The **charge roll-ups** on a cycle read
    only charges in `RESERVED` or `CONSUMED`; a `RELEASED` charge drops out the
    instant it is released, which is why every release path recomputes them."  The
    release path itself is specified in the same section: "The optional
    `release_reason` supplies `released_reason`; when it is omitted,
    `released_reason` is set to `CYCLE_ABORTED`.  On release `charge_kg` moves from
    the lot's `reserved_kg` back to its `available_kg` ... and the cycle's charge
    roll-ups are recomputed over the surviving participating charges."

    Design: Corner/calculations/calc_input_set_filtering_cycle_rollup_excludes_released_charge
    """
    ctx = _p5_two_lot_plant()
    cycle = ctx["molding_cycle"]
    charge_a = reserve_charge(ctx, cycle, ctx["lot_a"], charge_kg=20.0, regrind_kg=2.0)
    charge_b = reserve_charge(ctx, cycle, ctx["lot_b"], charge_kg=20.0, regrind_kg=2.0)

    third = reserve_charge(ctx, cycle, ctx["lot_a"], charge_kg=6.0, regrind_kg=0.6)

    widened = api.read_entity("get_molding_cycle", cycle["id"], ctx["operator_headers"])
    _p5_exact(widened["charged_mass_kg"], "46.000", 3, "charged_mass_kg with three charges")
    # (20.000 * 3.00 + 20.000 * 4.05 + 6.000 * 3.00) = 159.00000, over 46.000 = 3.45652...
    _p5_exact(widened["weighted_melt_index_g10min"], "3.46", 2, "weighted index with three charges")
    # 4.600 / 46.000 * 100 = 10.000.
    _p5_exact(widened["cycle_regrind_pct"], "10.00", 2, "cycle_regrind_pct with three charges")

    validate_success(
        api.release_resin_charge(third["id"], release_charge_payload(), ctx["resin_tech_headers"])
    )

    released = api.read_entity("get_resin_charge", third["id"], ctx["resin_tech_headers"])
    assert released["status"] == "RELEASED", f"expected RELEASED, got {released['status']}"
    assert released["released_reason"] == "CYCLE_ABORTED", (
        "an omitted release_reason defaults released_reason to CYCLE_ABORTED, got "
        f"{released['released_reason']!r}"
    )

    restored = api.read_entity("get_molding_cycle", cycle["id"], ctx["operator_headers"])
    _p5_exact(restored["charged_mass_kg"], "40.000", 3, "charged_mass_kg after release")
    _p5_exact(restored["weighted_melt_index_g10min"], "3.53", 2, "weighted index after release")
    _p5_exact(restored["cycle_regrind_pct"], "10.00", 2, "cycle_regrind_pct after release")

    lot_a = api.read_entity("get_resin_lot", ctx["lot_a"]["id"], admin_headers)
    _p5_exact(lot_a["available_kg"], "80.000", 3, "lot_a.available_kg after release")
    _p5_exact(lot_a["reserved_kg"], "20.000", 3, "lot_a.reserved_kg after release")
    _p5_exact(lot_a["consumed_kg"], "0.000", 3, "lot_a.consumed_kg after release")
    assert_resin_ledger_conserved(lot_a)

    for label, charge in (("charge_a", charge_a), ("charge_b", charge_b)):
        survivor = api.read_entity("get_resin_charge", charge["id"], ctx["resin_tech_headers"])
        assert survivor["status"] == "RESERVED", (
            f"{label}: releasing a sibling charge must not touch it, got {survivor['status']}"
        )


def test_blended_regrind_percentage_rounds_half_up_from_the_two_mass_totals(api, admin_headers):
    """A blend of 8.805 percent lands on 8.81, not on 8.80 and not on the 9.08 average.

    PRD.md section 3.2 fixes both the inputs and the order of operations: "over the
    cycle's charges in `RESERVED` or `CONSUMED`, `total_regrind_kg` is the sum of
    `regrind_kg` rounded to three decimals and `total_charge_kg` is the sum of
    `charge_kg` rounded to three decimals; the cycle's regrind percentage is then
    `total_regrind_kg` divided by `total_charge_kg` times 100, rounded to two
    decimals — the two masses are rounded *before* the division, and when
    `total_charge_kg` is 0.000 the percentage is 0.00."  The same section gives the
    per-charge figure independently: "`charge_regrind_pct` is `regrind_kg` divided
    by `charge_kg` times 100 rounded to two decimals."  PRD.md section 3.2 also
    fixes the acceptance boundary: "A percentage strictly greater than the model's
    `max_regrind_pct` is refused with `ERR_REGRIND_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/calc_precision_cycle_regrind_pct_round_half_up_two_dp
    """
    ctx = _p5_two_lot_plant()
    cycle = ctx["molding_cycle"]

    heavy = reserve_charge(ctx, cycle, ctx["lot_a"], charge_kg=25.0, regrind_kg=2.0)
    fine = reserve_charge(ctx, cycle, ctx["lot_b"], charge_kg=15.0, regrind_kg=1.522)

    stored_heavy = api.read_entity("get_resin_charge", heavy["id"], ctx["resin_tech_headers"])
    _p5_exact(stored_heavy["charge_regrind_pct"], "8.00", 2, "heavy.charge_regrind_pct")
    _p5_exact(stored_heavy["virgin_kg"], "23.000", 3, "heavy.virgin_kg")

    stored_fine = api.read_entity("get_resin_charge", fine["id"], ctx["resin_tech_headers"])
    # 1.522 / 15.000 * 100 = 10.14666..., half-up at two decimals = 10.15.
    _p5_exact(stored_fine["charge_regrind_pct"], "10.15", 2, "fine.charge_regrind_pct")
    _p5_exact(stored_fine["virgin_kg"], "13.478", 3, "fine.virgin_kg")

    rolled = api.read_entity("get_molding_cycle", cycle["id"], ctx["operator_headers"])
    _p5_exact(rolled["charged_mass_kg"], "40.000", 3, "charged_mass_kg")
    # (2.000 + 1.522) / 40.000 * 100 = 8.80500 exactly; truncation gives 8.80 and
    # averaging the two per-charge percentages gives 9.08.
    _p5_exact(rolled["cycle_regrind_pct"], "8.81", 2, "cycle_regrind_pct")
    # (25.000 * 3.00 + 15.000 * 4.05) = 135.75000, over 40.000 = 3.39375.
    _p5_exact(rolled["weighted_melt_index_g10min"], "3.39", 2, "weighted_melt_index_g10min")

    lot_a = api.read_entity("get_resin_lot", ctx["lot_a"]["id"], admin_headers)
    _p5_exact(lot_a["available_kg"], "75.000", 3, "lot_a.available_kg")
    assert_resin_ledger_conserved(lot_a)
    lot_b = api.read_entity("get_resin_lot", ctx["lot_b"]["id"], admin_headers)
    _p5_exact(lot_b["available_kg"], "85.000", 3, "lot_b.available_kg")
    assert_resin_ledger_conserved(lot_b)
