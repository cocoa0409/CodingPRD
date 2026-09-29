"""The undivided-interest reallocation sweep of PRD 3.4.

Truncate-then-sweep, not round-and-patch: each included unit's raw share is
truncated to a whole basis point and the whole truncation residual is then
handed out one basis point at a time, so the INCLUDED set always totals
exactly 10000 basis points and a withdraw/reinstate pair restores every
individual unit's value byte for byte.
"""

from fractions import Fraction

import store

TOTAL_BP = 10000


def reallocate(package):
    units = store.package_units(package["id"])

    for unit in units:
        if unit["declaration_status"] == "WITHDRAWN":
            if unit["percentage_interest_bp"] != 0:
                unit["percentage_interest_bp"] = 0
                store.touch(unit)

    included = [u for u in units if u["declaration_status"] == "INCLUDED"]
    if not included:
        if package["allocated_bp_total"] != 0:
            package["allocated_bp_total"] = 0
            store.touch(package)
        return package

    base_sum = sum(u["base_percentage_interest_bp"] for u in included)
    rows = []
    for index, unit in enumerate(included):
        raw = Fraction(TOTAL_BP * unit["base_percentage_interest_bp"], base_sum)
        whole = raw.numerator // raw.denominator
        rows.append({
            "unit": unit,
            "whole": whole,
            "fraction": raw - whole,
            "index": index,
        })

    residual = TOTAL_BP - sum(row["whole"] for row in rows)
    ordered = sorted(
        rows,
        key=lambda row: (-row["fraction"],
                         -row["unit"]["base_percentage_interest_bp"],
                         store.sort_key(row["unit"])),
    )
    for row in ordered[:residual]:
        row["whole"] += 1

    for row in rows:
        unit = row["unit"]
        if unit["percentage_interest_bp"] != row["whole"]:
            unit["percentage_interest_bp"] = row["whole"]
            store.touch(unit)

    allocated = sum(row["whole"] for row in rows)
    if package["allocated_bp_total"] != allocated:
        package["allocated_bp_total"] = allocated
        store.touch(package)
    return package


def allocated_total(package):
    """`allocated_bp_total` recomputed over the current INCLUDED set, used by
    the balance precondition on certification and recording."""
    included = [u for u in store.package_units(package["id"])
                if u["declaration_status"] == "INCLUDED"]
    return sum(u["percentage_interest_bp"] for u in included)
