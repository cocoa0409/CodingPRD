"""Ration waterfall allocation (SCAFFOLD calculations.ration_waterfall_allocation,
PRD §3.7).

remaining = target_dmi_kg
for each ingredient in DECLARED order:
  if it is the last ingredient: dm_alloc = remaining (filler)
  else: dm_alloc = min(max_inclusion_pct * target_dmi_kg, remaining)
  remaining -= dm_alloc
  as_fed_kg = round(dm_alloc / dry_matter_pct, 3)
total_as_fed_kg = round(sum(as_fed_kg), 3)

dm_alloc kept at full precision before the division; as_fed rounded to 3 dp.
"""
from util import round_half_up


def compute_ration(ration):
    target = ration["target_dmi_kg"]
    ings = ration["ingredients"]
    n = len(ings)
    remaining = target
    allocations = []
    as_fed_values = []
    for idx, ing in enumerate(ings):
        if idx == n - 1:
            dm_alloc = remaining
        else:
            cap = ing["max_inclusion_pct"] * target
            dm_alloc = cap if cap < remaining else remaining
        if dm_alloc < 0:
            dm_alloc = 0
        remaining -= dm_alloc
        as_fed = round_half_up(dm_alloc / ing["dry_matter_pct"], 3)
        as_fed_values.append(as_fed)
        allocations.append({
            "feedstuff": ing["feedstuff"],
            "dm_alloc_kg": dm_alloc,
            "as_fed_kg": as_fed,
        })
    total_as_fed = round_half_up(sum(as_fed_values), 3)
    return {
        "total_as_fed_kg": total_as_fed,
        "allocations": allocations,
    }
