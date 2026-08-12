"""Shared helpers: G4 scope resolvers, foreign-key resolution at G9A, and the
small state-gate factories used by the route modules."""

import calc
from core import ApiError, KIND_NOT_FOUND, db

# --------------------------------------------------------------------------
# Ownership chains (PRD 2.1)
# --------------------------------------------------------------------------


def account_of_property(prop):
    return prop["account_id"] if prop else None


def account_of_well(well):
    prop = db.get("Property", well["property_id"]) if well else None
    return prop["account_id"] if prop else None


def scope(customer=None, technician=None):
    """G4.  Ownership is checked only where PRD section 4 names the scope gate."""

    def check(ctx):
        if ctx.role == "CustomerContact" and customer is not None:
            if ctx.user_id != customer(ctx):
                raise ApiError("ERR_ACTOR_SCOPE_VIOLATION",
                               "This account does not own the addressed resource.")
        elif ctx.role == "Technician" and technician is not None:
            if ctx.user_id != technician(ctx):
                raise ApiError("ERR_ACTOR_SCOPE_VIOLATION",
                               "This technician is not assigned to the resource.")

    return check


# --------------------------------------------------------------------------
# G9A -- body foreign keys
# --------------------------------------------------------------------------

def resolve(kind, row_id, error_id=None):
    row = db.get(kind, row_id)
    if row is None:
        raise ApiError(error_id or KIND_NOT_FOUND[kind])
    return row


def resolve_opt(kind, row_id, error_id=None):
    if row_id is None:
        return None
    return resolve(kind, row_id, error_id)


# --------------------------------------------------------------------------
# G5 state gate factories
# --------------------------------------------------------------------------

def state_gate(param, field, allowed, error_id):
    def check(ctx):
        row = ctx.path[param]
        if row[field] not in allowed:
            raise ApiError(error_id, "The resource is not in a state that permits this.")
    return check


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------

def rows_where(kind, **criteria):
    out = []
    for row in db.all(kind):
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out


def active_plans_of_well(well_id):
    return rows_where("MaintenancePlan", well_profile_id=well_id, status="ACTIVE")


def active_quote_lines(quote_id):
    return rows_where("QuoteLine", quote_id=quote_id, status="ACTIVE")


def posted_entries(work_order_id):
    rows = rows_where("PartsConsumptionEntry", work_order_id=work_order_id,
                      status="POSTED")
    return sorted(rows, key=lambda r: (r["posted_at"], r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Cascade fragments reused from several endpoints
# --------------------------------------------------------------------------

def recompute_plans_for_well(ctx, well):
    """The duty-cycle cascade tail: every ACTIVE plan on the well recomputes
    interval_days_as_operated and then next_due_at.  compliance_state and the
    overdue latch are deliberately untouched."""
    for plan in active_plans_of_well(well["id"]):
        calc.recompute_operated_interval(plan, well)
        ctx.touch(plan)


def quote_permit_fee(quote_id):
    """Quote pricing takes the earliest permit on the quote that is FILED,
    APPROVED or APPROVED_WITH_CONDITIONS."""
    candidates = [p for p in db.all("Permit")
                  if p["quote_id"] == quote_id
                  and p["status"] in ("FILED", "APPROVED", "APPROVED_WITH_CONDITIONS")]
    return candidates[0]["fee_cents"] if candidates else 0


def work_order_permit_fee(work_order_id):
    """Invoice construction takes the earliest permit on the work order that is
    APPROVED or APPROVED_WITH_CONDITIONS -- FILED does not count here."""
    candidates = [p for p in db.all("Permit")
                  if p["work_order_id"] == work_order_id
                  and p["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS")]
    return candidates[0]["fee_cents"] if candidates else 0


def reprice_quote(ctx, quote):
    """Recompute the quote's four money fields over the surviving ACTIVE lines.

    An un-pinned line (a freshly minted permit-mandated alternate) is valued at
    the catalog's current unit_cost_cents.
    """
    parts = 0
    for line in active_quote_lines(quote["id"]):
        pinned = line["unit_cost_cents_pinned"]
        if pinned is None:
            part = db.get("PartCatalogItem", line["part_catalog_item_id"])
            cost = part["unit_cost_cents"] if part else 0
        else:
            cost = pinned
        _, unit_price = calc.parts_unit_price_cents(cost)
        parts += unit_price * int(line["quantity"])
    band = calc.labor_time_band(quote["estimated_start_at"])
    rate = calc.labor_rate_cents_per_hour(quote["quoted_technician_tier"], band)
    minutes = calc.billable_minutes(quote["estimated_labor_minutes"])
    labor = calc.labor_charge_cents(rate, minutes)
    permit = quote_permit_fee(quote["id"])
    tax = calc.cents(calc.d(parts) * calc.TAX_RATE_PCT / calc.d(100))
    quote["parts_subtotal_cents"] = parts
    quote["labor_subtotal_cents"] = labor
    quote["permit_fee_cents"] = permit
    quote["tax_cents"] = tax
    quote["total_cents"] = parts + labor + permit + tax
    ctx.touch(quote)


def pump_yield_check(part, well):
    """PRD 3.6 -- the three pump outcomes, in the order the section gives them.
    Returns an error id or None."""
    if part["category"] != "PUMP":
        return None
    rated = part.get("rated_gpm")
    if rated is None or calc.d(rated) < calc.MIN_PUMP_GPM:
        return "ERR_YIELD_INSUFFICIENT_FOR_PUMP"
    measured = well.get("measured_yield_gpm")
    if measured is None:
        return "ERR_INSPECTION_REQUIRED"
    ceiling = calc.d(measured) * calc.YIELD_SAFETY_FACTOR
    if calc.d(rated) > ceiling:
        return "ERR_YIELD_INSUFFICIENT_FOR_PUMP"
    return None
