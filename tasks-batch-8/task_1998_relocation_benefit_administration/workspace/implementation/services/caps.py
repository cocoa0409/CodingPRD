"""Effective cap and headroom logic per PRD §2.7.

Effective cap for a component = policy cap + sum(APPROVED exception increases for
this case + component). Held amounts against each component:
  HHG          : MoveAssignment.estimated_cents in {ESTIMATE_APPROVED, DELIVERED, INVOICED}
  TEMP_HOUSING : ServiceBooking.total_cents in CONFIRMED with kind == TEMP_HOUSING
  TRAVEL       : ServiceBooking.total_cents in CONFIRMED with kind == TRAVEL
  MISC         : ExpenseClaim.amount_cents in APPROVED
  LOSS_ON_SALE : not held incrementally; evaluated once at record-sale.
"""

from db import DB


CAP_FIELD = {
    "HHG": "hhg_cap_cents",
    "TEMP_HOUSING": "temp_housing_cap_cents",
    "TRAVEL": "travel_cap_cents",
    "MISC": "misc_cap_cents",
    "LOSS_ON_SALE": "loss_on_sale_cap_cents",
}


def approved_increases(case_id, component):
    total = 0
    for x in DB.exception_requests.values():
        if (
            x["case_id"] == case_id
            and x["component"] == component
            and x["status"] == "APPROVED"
        ):
            total += x["requested_cap_increase_cents"]
    return total


def effective_cap(case, policy, component):
    base = policy[CAP_FIELD[component]]
    return base + approved_increases(case["id"], component)


def held_amount(case_id, component):
    total = 0
    if component == "HHG":
        for a in DB.move_assignments.values():
            if a["case_id"] == case_id and a["status"] in (
                "ESTIMATE_APPROVED",
                "DELIVERED",
                "INVOICED",
            ):
                total += a.get("estimated_cents") or 0
    elif component == "TEMP_HOUSING":
        for b in DB.service_bookings.values():
            if (
                b["case_id"] == case_id
                and b["kind"] == "TEMP_HOUSING"
                and b["status"] == "CONFIRMED"
            ):
                total += b.get("total_cents") or 0
    elif component == "TRAVEL":
        for b in DB.service_bookings.values():
            if (
                b["case_id"] == case_id
                and b["kind"] == "TRAVEL"
                and b["status"] == "CONFIRMED"
            ):
                total += b.get("total_cents") or 0
    elif component == "MISC":
        for c in DB.expense_claims.values():
            if c["case_id"] == case_id and c["status"] == "APPROVED":
                total += c.get("amount_cents") or 0
    elif component == "LOSS_ON_SALE":
        # not held incrementally
        total = 0
    return total


def remaining_headroom(case, policy, component):
    return effective_cap(case, policy, component) - held_amount(case["id"], component)
