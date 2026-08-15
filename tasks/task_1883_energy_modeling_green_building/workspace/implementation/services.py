"""Domain services: lookups, serializers, derived-field reconciliation,
calculations, and cascades (PRD sections 2.4-2.10, 3.2-3.8)."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from db import DB, new_id, next_seq, now_iso
from errors import ApiError
from util import parse_dt

# --- attempt state sets (calculation: certification_level_of_points) ---
IN_REVIEW_FLIGHT = {"SUBMITTED", "UNDER_REVIEW", "CLARIFICATION_REQUESTED", "RESUBMITTED", "APPEALED"}
OPTIMISTIC_STATES = {"SUBMITTED", "UNDER_REVIEW", "RESUBMITTED"}
PRE_SUBMISSION_STATES = {"SELECTED", "DOCUMENTATION_IN_PROGRESS", "READY_FOR_SUBMITTAL", "DROPPED"}

LEVEL_RANK = {"CERTIFIED": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 4}

PHASE_BASE_CENTS = {"DESIGN": 250000, "CONSTRUCTION": 350000}
FEE_PER_1000_SQFT_CENTS = 5000
FEE_CAP_CENTS = 2000000

GAP_TOLERANCE_PCT = Decimal("15.00")
MIN_IMPROVEMENT_PCT = Decimal("5.00")


# ---------------------------------------------------------------------------
# generic record helpers
# ---------------------------------------------------------------------------

def stamp(rec):
    """Initialize common fields on a new record."""
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """A mutation: refresh updated_at, increment version (PRD 2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def sorted_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# lookups (existence stage; each type has its own not-found code, PRD 2.8)
# ---------------------------------------------------------------------------

def _get(store, rid, error_id, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError(error_id, 404, f"{label} does not exist")
    return rec


def get_member(rid):
    return _get("team_members", rid, "ERR_TEAM_MEMBER_NOT_FOUND", "Team member")


def get_project(rid):
    return _get("projects", rid, "ERR_PROJECT_NOT_FOUND", "Certification project")


def get_entry(rid):
    return _get("credit_library_entries", rid, "ERR_CREDIT_ENTRY_NOT_FOUND", "Credit library entry")


def get_model(rid):
    return _get("energy_models", rid, "ERR_ENERGY_MODEL_NOT_FOUND", "Energy model")


def get_attempt(rid):
    return _get("credit_attempts", rid, "ERR_CREDIT_ATTEMPT_NOT_FOUND", "Credit attempt")


def get_comment(rid):
    return _get("review_comments", rid, "ERR_REVIEW_COMMENT_NOT_FOUND", "Review comment")


def get_task(rid):
    return _get("commissioning_tasks", rid, "ERR_COMMISSIONING_TASK_NOT_FOUND", "Commissioning task")


def get_program(rid):
    return _get("incentive_programs", rid, "ERR_INCENTIVE_PROGRAM_NOT_FOUND", "Incentive program")


def get_project_incentive(rid):
    return _get("project_incentives", rid, "ERR_PROJECT_INCENTIVE_NOT_FOUND", "Project incentive")


def get_analysis(rid):
    return _get("cost_premium_analyses", rid, "ERR_ANALYSIS_NOT_FOUND", "Cost premium analysis")


def get_report(rid):
    return _get("performance_reports", rid, "ERR_PERFORMANCE_REPORT_NOT_FOUND", "Performance report")


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------

def attempts_of_project(project_id):
    return [a for a in DB["credit_attempts"].values() if a["project_id"] == project_id]


def comments_of_attempt(attempt_id):
    return sorted_created(
        [c for c in DB["review_comments"].values() if c["credit_attempt_id"] == attempt_id]
    )


def locked_model(project_id, model_type):
    """At most one LOCKED model per (project_id, model_type)."""
    for m in DB["energy_models"].values():
        if (
            m["project_id"] == project_id
            and m["model_type"] == model_type
            and m["status"] == "LOCKED"
        ):
            return m
    return None


# ---------------------------------------------------------------------------
# calculations (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

def level_of(points):
    """Threshold table, inclusive lower bounds (PRD 3.5)."""
    if points >= 80:
        return "PLATINUM"
    if points >= 60:
        return "GOLD"
    if points >= 50:
        return "SILVER"
    if points >= 40:
        return "CERTIFIED"
    return "NONE"


def certification_fee_cents(phase, gross_floor_area_sqft):
    """Tiered pricing: base + per-1000-sqft (ceil) capped at the fee cap."""
    units = -(-gross_floor_area_sqft // 1000)  # ceil for positive ints
    return min(PHASE_BASE_CENTS[phase] + FEE_PER_1000_SQFT_CENTS * units, FEE_CAP_CENTS)


def bucket_points_for_improvement(improvement_pct_final):
    """Energy credit points bucket table; inclusive boundaries (PRD 3.5)."""
    imp = Decimal(str(improvement_pct_final))
    for threshold, points in ((18, 10), (14, 8), (10, 6), (8, 4), (5, 2)):
        if imp >= Decimal(threshold):
            return points
    return 0


def incentive_total_cents(project_id, incremental_construction_cost_cents):
    """Stacking waterfall: combinable sum + per-type max of non-combinable,
    capped at floor(40% of the PRE-incentive incremental cost)."""
    eligible = [
        a
        for a in DB["project_incentives"].values()
        if a["project_id"] == project_id and a["status"] in ("APPROVED", "DISBURSED")
    ]
    combinable_sum = 0
    non_combinable_max = {}
    for app in eligible:
        program = DB["incentive_programs"][app["incentive_program_id"]]
        if program["is_combinable"]:
            combinable_sum += app["claimed_amount_cents"]
        else:
            t = program["incentive_type"]
            non_combinable_max[t] = max(
                non_combinable_max.get(t, 0), app["claimed_amount_cents"]
            )
    raw_total = combinable_sum + sum(non_combinable_max.values())
    cap = int(
        (Decimal("0.40") * Decimal(incremental_construction_cost_cents)).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    return min(raw_total, cap)


def compute_analysis_fields(analysis):
    """Pinned evaluation order (PRD 3.7): savings -> incentive total -> net ->
    payback, each step feeding the next with stored integer-cent operands."""
    project_id = analysis["project_id"]
    baseline = locked_model(project_id, "BASELINE")
    proposed = locked_model(project_id, "PROPOSED")
    if baseline is None or proposed is None:
        raise ApiError(
            "ERR_PROPOSED_MODEL_NOT_LOCKED",
            409,
            "Analysis requires the project's LOCKED baseline and proposed models",
        )
    savings = (
        baseline["annual_energy_cost_confirmed_only_cents"]
        - proposed["annual_energy_cost_confirmed_only_cents"]
    )
    total = incentive_total_cents(project_id, analysis["incremental_construction_cost_cents"])
    net = analysis["incremental_construction_cost_cents"] - total
    if savings == 0:
        payback = None
    else:
        payback = float(
            (Decimal(net) / Decimal(savings)).quantize(
                Decimal("0.1"), rounding="ROUND_HALF_UP"
            )
        )
    analysis["annual_energy_savings_cents"] = savings
    analysis["incentive_total_cents"] = total
    analysis["net_cost_premium_cents"] = net
    analysis["simple_payback_years"] = payback


# ---------------------------------------------------------------------------
# derived-field reconciliation + automatic transitions (PRD 2.9)
# ---------------------------------------------------------------------------

def sync_project_derived(project, explicit_bump=False):
    """Recompute the project's derived scoreboard immediately.

    A recomputation that changes a stored value is a real mutation (PRD 2.4):
    it refreshes updated_at and increments version. explicit_bump covers the
    operations PRD 2.5 lists as always incrementing the project version.
    """
    attempts = attempts_of_project(project["id"])
    pursued = sum(a["points_possible"] for a in attempts if a["status"] != "DROPPED")
    awarded_total = sum(
        a["points_awarded"] for a in attempts if a["status"] == "AWARDED"
    )
    optimistic = awarded_total + sum(
        a["points_possible"] for a in attempts if a["status"] in OPTIMISTIC_STATES
    )
    prereqs_ok = all(
        a["status"] == "AWARDED"
        for a in attempts
        if a["is_prerequisite"] and a["status"] != "DROPPED"
    )
    changed = False
    for field, value in (
        ("points_pursued_total", pursued),
        ("points_awarded_total", awarded_total),
        ("projected_level", level_of(optimistic)),
        ("conservative_level", level_of(awarded_total)),
        ("prerequisites_satisfied", prereqs_ok),
    ):
        if project[field] != value:
            project[field] = value
            changed = True
    if changed or explicit_bump:
        touch(project)


def bubble_up_phase(project, phase):
    """Automatic DESIGN/CONSTRUCTION_SUBMITTED -> *_REVIEWED bubble-up once no
    attempt of the phase remains in a review-flight state (PRD 3.5)."""
    submitted_state = "DESIGN_SUBMITTED" if phase == "DESIGN" else "CONSTRUCTION_SUBMITTED"
    if project["status"] != submitted_state:
        return
    for a in attempts_of_project(project["id"]):
        if a["phase"] == phase and a["status"] in IN_REVIEW_FLIGHT:
            return
    project["status"] = "DESIGN_REVIEWED" if phase == "DESIGN" else "CONSTRUCTION_REVIEWED"
    touch(project)  # each automatic phase bubble-up increments version (PRD 2.5)


# ---------------------------------------------------------------------------
# interval rules (calculations: commissioning_schedule_overlap, report_period_tiling)
# ---------------------------------------------------------------------------

def check_cx_overlap(project_id, new_start, new_end, exclude_id=None):
    """Half-open [start, end) overlap against SCHEDULED/IN_PROGRESS tasks."""
    for t in DB["commissioning_tasks"].values():
        if t["project_id"] != project_id or t["id"] == exclude_id:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if new_start < parse_dt(t["scheduled_end"]) and parse_dt(t["scheduled_start"]) < new_end:
            raise ApiError(
                "ERR_CX_SCHEDULE_OVERLAP",
                409,
                "Commissioning task window overlaps an existing scheduled task",
            )


def check_report_tiling(project, start_dt, end_dt):
    """Closed-day-interval tiling against the ACCEPTED anchor plus overlap
    against any DRAFT/SUBMITTED/ACCEPTED report (PRD 3.8)."""
    reports = [r for r in DB["performance_reports"].values() if r["project_id"] == project["id"]]
    accepted = [r for r in reports if r["status"] == "ACCEPTED"]
    if accepted:
        anchor = max(accepted, key=lambda r: parse_dt(r["period_end"]).date())
        required_start = parse_dt(anchor["period_end"]).date() + timedelta(days=1)
    else:
        required_start = parse_dt(project["certified_at"]).date()
    start_day = start_dt.date()
    end_day = end_dt.date()
    if start_day < required_start:
        raise ApiError(
            "ERR_REPORT_PERIOD_OVERLAP",
            409,
            "Report period shares a day with tiled history",
        )
    if start_day > required_start:
        raise ApiError(
            "ERR_REPORT_PERIOD_GAP",
            409,
            "Report period leaves untiled days between periods",
        )
    for r in reports:
        if r["status"] not in ("DRAFT", "SUBMITTED", "ACCEPTED"):
            continue
        r_start = parse_dt(r["period_start"]).date()
        r_end = parse_dt(r["period_end"]).date()
        if start_day <= r_end and r_start <= end_day:
            raise ApiError(
                "ERR_REPORT_PERIOD_OVERLAP",
                409,
                "Report period shares a day with an existing report",
            )


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

ser_member = public
ser_project = public
ser_entry = public
ser_model = public
ser_attempt = public
ser_comment = public
ser_task = public
ser_program = public
ser_project_incentive = public
ser_analysis = public
ser_report = public
