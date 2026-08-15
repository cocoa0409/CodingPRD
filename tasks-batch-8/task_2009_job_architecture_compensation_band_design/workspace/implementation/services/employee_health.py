"""Employee standing health (compa ratio / range position) and payroll rollups (§3.6)."""
from decimal import Decimal
from db import store
from services.common import round4


def current_program():
    """The program currently in force: the single non-ARCHIVED program with the
    most advanced lifecycle; ties broken by latest created_at. Employees' bands
    resolve against this program."""
    best = None
    order = {"DRAFT": 0, "FRAMEWORK_LOCKED": 1, "PRICING": 2, "MAPPING_OPEN": 3,
             "PUBLISHED": 4, "ARCHIVED": 5}
    for p in store.programs.values():
        if best is None:
            best = p
            continue
        if (order[p["status"]], p["created_at"]) > (order[best["status"]], best["created_at"]):
            best = p
    return best


def resolve_published_band(employee: dict):
    """Unique PUBLISHED band for (current program, employee profile family+level, geo)."""
    profile = store.job_profiles.get(employee["job_profile_id"])
    if profile is None:
        return None
    prog = current_program()
    if prog is None:
        return None
    matches = []
    for band in store.pay_bands.values():
        if band["comp_program_id"] != prog["id"]:
            continue
        if band["job_family_id"] != profile["job_family_id"]:
            continue
        if band["job_level_id"] != profile["job_level_id"]:
            continue
        if band["geo_zone_id"] != employee["geo_zone_id"]:
            continue
        if band["status"] != "PUBLISHED":
            continue
        matches.append(band)
    if not matches:
        return None
    matches.sort(key=lambda b: (b["created_at"], b["id"]))
    return matches[-1]


def recompute_employee_health(employee: dict):
    """Recompute compa_ratio, range_position; red_circled left unchanged when UNBANDED."""
    band = resolve_published_band(employee)
    if band is None or not band.get("midpoint_cents"):
        employee["compa_ratio"] = None
        employee["range_position"] = "UNBANDED"
        return
    ratio = Decimal(employee["base_salary_cents"]) / Decimal(band["midpoint_cents"])
    employee["compa_ratio"] = float(round4(ratio))
    base = employee["base_salary_cents"]
    if base < band["min_cents"]:
        employee["range_position"] = "BELOW_MIN"
    elif base > band["max_cents"]:
        employee["range_position"] = "ABOVE_MAX"
    else:
        employee["range_position"] = "IN_RANGE"


def guidance_zone(employee: dict):
    """Reported, not stored."""
    r = employee.get("compa_ratio")
    if r is None:
        return None
    from services.common import GUIDANCE_LOW, GUIDANCE_HIGH
    rd = Decimal(str(r))
    if rd < GUIDANCE_LOW:
        return "BELOW_ZONE"
    if rd > GUIDANCE_HIGH:
        return "ABOVE_ZONE"
    return "IN_ZONE"


def recompute_department_payroll(dept: dict):
    total = 0
    for e in store.employees.values():
        if e["department_id"] == dept["id"] and e["status"] == "ACTIVE":
            total += e["base_salary_cents"]
    dept["projected_payroll_cents"] = total
    dept["updated_at"] = _touch_ts()


def recompute_program_payroll(program: dict):
    total = 0
    for d in store.departments.values():
        total += d.get("projected_payroll_cents", 0)
    program["total_payroll_projection_cents"] = total
    program["updated_at"] = _touch_ts()


def recompute_all_payroll():
    for d in store.departments.values():
        recompute_department_payroll(d)
    for p in store.programs.values():
        recompute_program_payroll(p)


def _touch_ts():
    from services.common import now_iso
    return now_iso()
