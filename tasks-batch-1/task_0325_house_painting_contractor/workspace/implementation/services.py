"""Business logic: entity construction, common-field management, validation
helpers, serialization, and state transitions.

All structural names (fields, enums, error ids) trace to PRD.md / SCAFFOLD.yaml.
"""
from datetime import datetime, timezone

import calc
from db import store, new_id
from errors import err

# ---------------------------------------------------------------------------
# Enum value sets (SCAFFOLD §1.1)
# ---------------------------------------------------------------------------
PRODUCT_SURFACE_KINDS = {"INTERIOR", "EXTERIOR", "BOTH"}
FINISH_TYPES = {"FLAT", "EGGSHELL", "SATIN", "SEMI_GLOSS", "GLOSS"}
SKILL_LEVELS = {"APPRENTICE", "JOURNEYMAN", "MASTER"}
EQUIPMENT_KINDS = {"SPRAYER", "SCAFFOLD", "LIFT"}
PROJECT_SCOPES = {"INTERIOR", "EXTERIOR", "BOTH"}
SURFACE_KINDS = {"INTERIOR", "EXTERIOR"}
PREP_LEVELS = {"LIGHT", "STANDARD", "HEAVY", "RESTORATION"}
CHANGE_ORDER_ACTIONS = {"ADD_SURFACE", "REMOVE_SURFACE", "REVISE_SURFACE"}
PAYMENT_KINDS = {"DEPOSIT", "FINAL"}


# ---------------------------------------------------------------------------
# Timestamps & common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def iso_now():
    now = store.clock.now()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def add_common(entity, with_version=True):
    ts = iso_now()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["_seq"] = store.next_seq()
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.5)."""
    if "version" in entity:
        entity["updated_at"] = iso_now()
        entity["version"] += 1


# ---------------------------------------------------------------------------
# Request body validation helpers (priority 4, ERR_INVALID_REQUEST 422)
# ---------------------------------------------------------------------------
def require_body(body):
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def need(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    return body[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


# ---------------------------------------------------------------------------
# Existence resolution (priority 3, 404). Returns the entity dict.
# ---------------------------------------------------------------------------
def get_project(pid):
    p = store.projects.get(pid)
    if p is None:
        raise err("ERR_PROJECT_NOT_FOUND", "Project not found.")
    return p


def get_surface(sid):
    s = store.surfaces.get(sid)
    if s is None:
        raise err("ERR_SURFACE_NOT_FOUND", "Surface not found.")
    return s


def get_line_item(lid):
    li = store.line_items.get(lid)
    if li is None:
        raise err("ERR_LINE_ITEM_NOT_FOUND", "Line item not found.")
    return li


def get_color_selection(cid):
    c = store.color_selections.get(cid)
    if c is None:
        raise err("ERR_COLOR_SELECTION_NOT_FOUND", "Color selection not found.")
    return c


def get_change_order(coid):
    c = store.change_orders.get(coid)
    if c is None:
        raise err("ERR_CHANGE_ORDER_NOT_FOUND", "Change order not found.")
    return c


def get_assignment(aid):
    a = store.crew_assignments.get(aid)
    if a is None:
        raise err("ERR_CREW_ASSIGNMENT_NOT_FOUND", "Crew assignment not found.")
    return a


def get_payment(pid):
    p = store.payments.get(pid)
    if p is None:
        raise err("ERR_PAYMENT_NOT_FOUND", "Payment not found.")
    return p


def get_walkthrough(wid):
    w = store.walkthroughs.get(wid)
    if w is None:
        raise err("ERR_WALKTHROUGH_NOT_FOUND", "Walkthrough not found.")
    return w


def get_warranty_claim(cid):
    c = store.warranty_claims.get(cid)
    if c is None:
        raise err("ERR_WARRANTY_CLAIM_NOT_FOUND", "Warranty claim not found.")
    return c


def get_crew_member(cid):
    c = store.crew_members.get(cid)
    if c is None:
        raise err("ERR_CREW_MEMBER_NOT_FOUND", "Crew member not found.")
    return c


def get_equipment(eid):
    e = store.equipment.get(eid)
    if e is None:
        raise err("ERR_EQUIPMENT_NOT_FOUND", "Equipment not found.")
    return e


def get_paint_product(pid):
    p = store.paint_products.get(pid)
    if p is None:
        raise err("ERR_PAINT_PRODUCT_NOT_FOUND", "Paint product not found.")
    return p


def get_weather_window(wid):
    w = store.weather_windows.get(wid)
    if w is None:
        raise err("ERR_WEATHER_WINDOW_NOT_FOUND", "Weather window not found.")
    return w


# ---------------------------------------------------------------------------
# Line-item recompute (calc material_estimate + labor_estimate)
# ---------------------------------------------------------------------------
def compute_line_item_costs(surface):
    product = store.paint_products[surface["paint_product_id"]]
    gallons, material = calc.material_estimate(
        surface["area_sqft"], surface["coats"],
        product["coverage_sqft_per_gallon_per_coat"], product["price_per_gallon_cents"])
    labor_hours, labor_cost = calc.labor_estimate(
        surface["area_sqft"], surface["coats"], surface["prep_level"])
    return gallons, material, labor_hours, labor_cost


def build_line_item(project_id, surface):
    gallons, material, labor_hours, labor_cost = compute_line_item_costs(surface)
    li = {
        "project_id": project_id,
        "surface_id": surface["id"],
        "gallons_required": gallons,
        "material_cost_cents": material,
        "labor_hours": calc.labor_hours_float(labor_hours),
        "labor_cost_cents": labor_cost,
        "executed": False,
    }
    add_common(li)
    store.line_items[li["id"]] = li
    return li


def recompute_line_item(li, surface):
    gallons, material, labor_hours, labor_cost = compute_line_item_costs(surface)
    li["gallons_required"] = gallons
    li["material_cost_cents"] = material
    li["labor_hours"] = calc.labor_hours_float(labor_hours)
    li["labor_cost_cents"] = labor_cost
    touch(li)


def line_item_for_surface(surface_id):
    for li in store.line_items.values():
        if li["surface_id"] == surface_id:
            return li
    return None


# ---------------------------------------------------------------------------
# Project total recompute (calc project_totals)
# ---------------------------------------------------------------------------
def project_surfaces(project_id):
    return [s for s in store.surfaces.values() if s["project_id"] == project_id]


def recompute_revised_total(project):
    """LIVE revised total = sum over non-REMOVED line items of material+labor."""
    total = 0
    for s in project_surfaces(project["id"]):
        if s["status"] == "REMOVED":
            continue
        li = line_item_for_surface(s["id"])
        if li is not None:
            total += li["material_cost_cents"] + li["labor_cost_cents"]
    project["revised_total_cents"] = total


def recompute_balance(project):
    project["balance_due_cents"] = project["revised_total_cents"] - project["amount_paid_cents"]


def recompute_amount_paid(project):
    total = 0
    for p in store.payments.values():
        if p["project_id"] == project["id"] and p["status"] == "CAPTURED":
            total += p["amount_cents"]
    project["amount_paid_cents"] = total


# ---------------------------------------------------------------------------
# Resource utilization accounting (PRD §2.9)
# ---------------------------------------------------------------------------
def parse_date(value):
    """Parse an ISO date 'YYYY-MM-DD' into a date object."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def assignment_days(a):
    """Set of date ordinals covered by an assignment [start_date, end_date]."""
    start = parse_date(a["start_date"]).toordinal()
    end = parse_date(a["end_date"]).toordinal()
    return set(range(start, end + 1))


def recompute_crew_scheduled_days(crew_member):
    """scheduled_day_count = sum of day_count over SCHEDULED/IN_PROGRESS assignments."""
    total = 0
    for a in store.crew_assignments.values():
        if a["crew_member_id"] == crew_member["id"] and a["status"] in ("SCHEDULED", "IN_PROGRESS"):
            total += a["day_count"]
    crew_member["scheduled_day_count"] = total


def recompute_equipment_units_reserved(equipment):
    """units_reserved = peak count of date-overlapping SCHEDULED/IN_PROGRESS
    assignments holding this equipment."""
    active = [a for a in store.crew_assignments.values()
              if a.get("equipment_id") == equipment["id"] and a["status"] in ("SCHEDULED", "IN_PROGRESS")]
    if not active:
        equipment["units_reserved"] = 0
        return
    # Sweep over all covered days; peak simultaneous holders is the reservation.
    day_counts = {}
    for a in active:
        for d in assignment_days(a):
            day_counts[d] = day_counts.get(d, 0) + 1
    equipment["units_reserved"] = max(day_counts.values()) if day_counts else 0


# ---------------------------------------------------------------------------
# Warranty expiry: completion_time + warranty_months calendar months
# ---------------------------------------------------------------------------
def add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to the last valid day of the target month.
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def format_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value):
    """Parse an ISO 8601 UTC timestamp (with optional fractional seconds and Z)."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Product/surface compatibility (ERR_PRODUCT_SURFACE_MISMATCH 422)
# ---------------------------------------------------------------------------
def check_product_surface_compat(product, surface_kind, project_scope):
    # Product scope must admit the surface kind.
    pk = product["surface_kind"]
    if pk != "BOTH" and pk != surface_kind:
        raise err("ERR_PRODUCT_SURFACE_MISMATCH",
                  "Paint product surface_kind does not admit this surface.")
    # Surface kind must be compatible with project scope.
    if project_scope != "BOTH" and project_scope != surface_kind:
        raise err("ERR_PRODUCT_SURFACE_MISMATCH",
                  "Surface kind is not compatible with project scope.")


# ---------------------------------------------------------------------------
# Serialization (strip internal keys like _seq)
# ---------------------------------------------------------------------------
_INTERNAL_KEYS = {"_seq"}


def serialize(entity):
    return {k: v for k, v in entity.items() if k not in _INTERNAL_KEYS}


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])
