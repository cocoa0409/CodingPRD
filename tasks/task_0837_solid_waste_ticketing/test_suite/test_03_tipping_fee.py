"""Provisional vs final tipping fee, the tiered/gas combinatorial fee, and the minimum floor."""
from test_helpers import (
    create_facility, create_hauler, create_manifest, create_gas_reading,
    create_ticket, weigh_out,
)


def test_provisional_estimate_uses_declared_weight(api):
    """PRD §3.3: "At creation the system computes `estimated_fee_cents`, a provisional
    tipping fee, using the declared weight rather than a measured net weight: it uses the
    linked manifest's `declared_weight_tons` when a manifest is referenced, and otherwise the
    ticket's own `gross_weight_tons`."

    Design: Difficulty/dual_variant_calc/ticket_fee_provisional_vs_final
    """
    facility = create_facility(1000)
    hauler = create_hauler(100_000_000)
    manifest = create_manifest(hauler["id"], declared_material="MSW", declared_weight_tons=7.0)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW",
                           gross_weight_tons=10.0, manifest_id=manifest["id"])
    assert ticket["estimated_fee_cents"] == 30100


def test_final_fee_uses_net_weight_and_diverges_from_estimate(api):
    """PRD §3.4: "On success the system sets `net_weight_tons` to gross minus tare,
    re-derives `is_diverted` from the material, and computes the final `tipping_fee_cents`."
    PRD §3.4: "`MSW` is charged at 4500 cents per ton for the portion of the weight up to 5
    tons and 3800 cents per ton for the portion above 5 tons."

    Design: Difficulty/dual_variant_calc/ticket_fee_provisional_vs_final
    """
    facility = create_facility(1000)
    hauler = create_hauler(100_000_000)
    manifest = create_manifest(hauler["id"], declared_material="MSW", declared_weight_tons=7.0)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW",
                           gross_weight_tons=10.0, manifest_id=manifest["id"])
    weighed = weigh_out(ticket["id"], 2.0)
    assert weighed["tipping_fee_cents"] == 33900
    assert weighed["tipping_fee_cents"] != weighed["estimated_fee_cents"]


def test_final_fee_msw_elevated_gas_applies_multiplier(api):
    """PRD §3.4: "the multiplier is 1.10 when — and only when — the facility's live
    `gas_status` is `ELEVATED`, and 1.00 otherwise; for the provisional estimate the
    multiplier is always 1.00. The weight fee multiplied by this gas multiplier is rounded
    half up to whole cents, after the multiplier is applied."

    Design: Difficulty/combinatorial_formula/tipping_fee_nonlinear_tier_gas_branch
    """
    facility = create_facility(1000)
    hauler = create_hauler(100_000_000)
    create_gas_reading(facility["id"], 300, "2026-03-01T08:00:00Z")
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW", gross_weight_tons=6.0)
    weighed = weigh_out(ticket["id"], 2.0)
    assert weighed["tipping_fee_cents"] == 19800


def test_final_fee_msw_normal_gas_no_multiplier(api):
    """PRD §3.4: "the multiplier is 1.10 when — and only when — the facility's live
    `gas_status` is `ELEVATED`, and 1.00 otherwise; for the provisional estimate the
    multiplier is always 1.00. The weight fee multiplied by this gas multiplier is rounded
    half up to whole cents, after the multiplier is applied."

    Design: Difficulty/combinatorial_formula/tipping_fee_nonlinear_tier_gas_branch
    """
    facility = create_facility(1000)
    hauler = create_hauler(100_000_000)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW", gross_weight_tons=6.0)
    weighed = weigh_out(ticket["id"], 2.0)
    assert weighed["tipping_fee_cents"] == 18000


def test_minimum_fee_floor_applies_to_clean_wood(api):
    """PRD §3.4: "The final fee is the greater of that subtotal and a floor of 2500 cents —
    the minimum tipping fee — which is applied last."
    PRD §3.3: "A ticket also derives `is_diverted` as true exactly when its `material` is
    `GREEN_WASTE` or `CLEAN_WOOD`; diverted materials are recycled and consume no airspace."

    Design: Corner/calculations/minimum_fee_floor_applies_clean_wood
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    ticket = create_ticket(facility["id"], hauler["id"], material="CLEAN_WOOD", gross_weight_tons=1.5)
    weighed = weigh_out(ticket["id"], 1.0)
    assert weighed["tipping_fee_cents"] == 2500
    assert weighed["is_diverted"] is True
