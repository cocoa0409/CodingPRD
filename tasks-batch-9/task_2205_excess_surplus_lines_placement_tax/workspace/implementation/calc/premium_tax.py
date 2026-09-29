"""Calculation: premium_tax_and_stamping_fee (PRD 3.7).

Two genuinely different regimes, selected by the policy's pinned
allocation_method_applied. Rounding order is normative: round PER ALLOCATION
ROW, then sum.
"""

from decimal import Decimal

import store
from errors import ApiError
from moneyutil import dec, largest_remainder, pct_out, round_half_up, round_half_up_4dp


def taxable_base(policy):
    """The policy fee is taxable consideration; the broker fee never is."""
    return int(policy.get("gross_premium_cents") or 0) + int(policy.get("policy_fee_cents") or 0)


def _program_or_fail(state_code):
    program = store.state_program_by_code(state_code)
    if program is None:
        raise ApiError("ERR_ALLOCATION_STATE_PROGRAM_MISSING",
                       "No state program is configured for %s." % state_code)
    return program


def positive_exposures(placement):
    rows = [r for r in (placement.get("state_exposures") or [])
            if int(r.get("insured_value_cents") or 0) > 0]
    return sorted(rows, key=lambda r: r["state_code"])


def plan_rows(policy, placement):
    """Which states receive premium, and in what exact proportion.

    Returns a list of {state_code, allocation_pct (Decimal), weight (Decimal)}
    in ascending state_code order.
    """
    method = policy.get("allocation_method_applied")
    if method == "HOME_STATE_SINGLE":
        return [{"state_code": policy.get("home_state"),
                 "allocation_pct": Decimal("1.0000"),
                 "weight": Decimal(1)}]

    rows = positive_exposures(placement)
    if not rows:
        # An ALLOCATED_MULTI policy always has at least one positive exposure,
        # because the home state waterfall required one at placement creation.
        return [{"state_code": policy.get("home_state"),
                 "allocation_pct": Decimal("1.0000"),
                 "weight": Decimal(1)}]
    total_iv = sum(int(r["insured_value_cents"]) for r in rows)
    out = []
    for row in rows:
        exact = dec(row["insured_value_cents"]) / dec(total_iv)
        out.append({"state_code": row["state_code"],
                    "allocation_pct": round_half_up_4dp(exact),
                    "weight": exact})
    return out


def stamping_fee_for(program, allocated_cents, rate):
    """Zero outright when the state requires no stamping office; otherwise the
    uncapped figure, capped when the state configures a cap."""
    if not program.get("stamping_office_required"):
        return 0
    uncapped = round_half_up(dec(allocated_cents) * dec(rate))
    cap = program.get("stamping_fee_cap_cents")
    if cap is None:
        return uncapped
    return min(uncapped, int(cap))


def calculate(policy, placement):
    """First calculation of a policy's tax. Returns (taxable, rows).

    Every row pins premium_tax_rate_applied and stamping_fee_rate_applied from
    the state's program at this instant.
    """
    taxable = taxable_base(policy)

    # The home state's program must exist, and so must one for every allocated
    # state (PRD 3.7).
    _program_or_fail(policy.get("home_state"))
    plan = plan_rows(policy, placement)
    programs = {}
    for entry in plan:
        programs[entry["state_code"]] = _program_or_fail(entry["state_code"])

    parts = largest_remainder(taxable, [(e["state_code"], e["weight"]) for e in plan])

    basis = policy.get("allocation_method_applied")
    rows = []
    for entry in plan:
        code = entry["state_code"]
        program = programs[code]
        allocated = parts[code]
        tax_rate = program.get("premium_tax_rate")
        fee_rate = program.get("stamping_fee_rate")
        rows.append({
            "state_code": code,
            "allocation_pct": pct_out(entry["allocation_pct"]),
            "allocated_premium_cents": allocated,
            "premium_tax_rate_applied": tax_rate,
            "stamping_fee_rate_applied": fee_rate,
            "tax_cents": round_half_up(dec(allocated) * dec(tax_rate)),
            "stamping_fee_cents": stamping_fee_for(program, allocated, fee_rate),
            "allocation_basis": basis,
            "_state_program_id": program["id"],
        })
    return taxable, rows
