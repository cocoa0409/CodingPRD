"""Calculation: endorsement_tax_adjustment (PRD 3.8).

The evaluation order is pinned: taxable premium feeds the allocation, the
allocation feeds the per-state tax, and the per-state tax feeds the adjustment.
The premium base is ALWAYS recomputed from the full ISSUED endorsement set,
never by incrementally adding a delta — that is what makes a void exactly
reversible.
"""

import store
from moneyutil import dec, largest_remainder, normalised_weights, round_half_up


def issued_delta_sum(policy_id, exclude_ids=(), include_ids=()):
    total = 0
    for end in store.endorsements_of(policy_id):
        if end["id"] in exclude_ids:
            continue
        if end.get("status") == "ISSUED" or end["id"] in include_ids:
            total += int(end.get("premium_delta_cents") or 0)
    return total


def projected_gross(policy, extra_ids=(), excluded_ids=()):
    """gross_premium_cents as it would stand for a given ISSUED set."""
    return int(policy.get("original_gross_premium_cents") or 0) + issued_delta_sum(
        policy["id"], exclude_ids=set(excluded_ids), include_ids=set(extra_ids))


def _cap_for(state_code):
    program = store.state_program_by_code(state_code)
    if program is None:
        return None
    return program.get("stamping_fee_cap_cents")


def recompute(policy):
    """Re-derive premium, allocation rows and totals from the ISSUED set.

    Returns a dict describing the movement:
      tax_before / stamping_before / tax_after / stamping_after
      per_state: {state_code: {premium_delta, tax_delta, stamping_delta}}
    """
    from store import touch

    tax_before = int(policy.get("total_tax_cents") or 0)
    stamping_before = int(policy.get("total_stamping_fee_cents") or 0)

    # Step 1 - premium base from the full ISSUED endorsement set.
    gross = projected_gross(policy)
    # Step 2 - taxable base.
    taxable = gross + int(policy.get("policy_fee_cents") or 0)

    rows = store.allocations_of(policy["id"])
    # Step 3 - redistribute over the PINNED, normalised allocation percentages.
    weights = normalised_weights(rows)
    parts = largest_remainder(taxable, weights) if rows else {}

    per_state = {}
    for row in rows:
        code = row.get("state_code")
        old_tax = int(row.get("tax_cents") or 0)
        old_stamping = int(row.get("stamping_fee_cents") or 0)
        old_allocated = int(row.get("allocated_premium_cents") or 0)

        allocated = parts.get(code, old_allocated)
        tax_rate = row.get("premium_tax_rate_applied")
        fee_rate = row.get("stamping_fee_rate_applied")

        # Step 4 - per-state tax and fee from the row's OWN pinned rates.
        new_tax = round_half_up(dec(allocated) * dec(tax_rate))
        if old_stamping == 0 and dec(fee_rate) == 0:
            new_stamping = 0
        else:
            uncapped = round_half_up(dec(allocated) * dec(fee_rate))
            cap = _cap_for(code)
            new_stamping = uncapped if cap is None else min(uncapped, int(cap))

        changed = (allocated != old_allocated or new_tax != old_tax
                   or new_stamping != old_stamping)
        row["allocated_premium_cents"] = allocated
        row["tax_cents"] = new_tax
        row["stamping_fee_cents"] = new_stamping
        if changed:
            touch(row)

        per_state[code] = {
            "premium_delta": allocated - old_allocated,
            "tax_delta": new_tax - old_tax,
            "stamping_delta": new_stamping - old_stamping,
            "state_program_id": row.get("_state_program_id"),
        }

    policy["gross_premium_cents"] = gross
    policy["taxable_premium_cents"] = taxable
    policy["total_tax_cents"] = sum(int(r.get("tax_cents") or 0) for r in rows)
    policy["total_stamping_fee_cents"] = sum(
        int(r.get("stamping_fee_cents") or 0) for r in rows)

    return {
        "tax_before": tax_before,
        "stamping_before": stamping_before,
        "tax_after": int(policy["total_tax_cents"]),
        "stamping_after": int(policy["total_stamping_fee_cents"]),
        "per_state": per_state,
    }
