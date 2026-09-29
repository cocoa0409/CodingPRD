"""Placement contracting: proposal, execution, activation and closure (3.3 / 3.9)."""
from flask import Blueprint

from calc import (
    CONTRACT_ACTIVATION_GRACE_DAYS,
    PROJECTION_VARIANTS,
    cost_projection,
    placement_encumbrance,
    recompute_placement_encumbrance,
)
from cascades import book_encumbrance, close_placement
from common import (
    LRE_SETTINGS,
    PLACEMENT_TYPES,
    account_or_404,
    collection,
    decision_or_404,
    placement_or_404,
    schedule_or_404,
    school_or_404,
    single,
    student_or_404,
)
from errors import fail
from middleware import (
    ALL_ROLES,
    FISCAL_OFFICER,
    PLACEMENT_COORDINATOR,
    check_scope,
    endpoint,
)
from response import created, ok
from store import add_days, clock_date, db, new_row, now_iso, parse_date, public, touch
from validation import (
    get_bool,
    get_date,
    get_enum,
    get_id,
    get_int,
    get_text,
    q_enum,
    q_str,
    read_body,
)

bp = Blueprint("placements", __name__)


# =========================================================================
# helpers
# =========================================================================

def schedule_covers(schedule, day):
    if schedule["approval_state"] != "STATE_APPROVED":
        return False
    start = parse_date(schedule["effective_from"])
    end = parse_date(schedule["effective_to"])
    if start is None or end is None:
        return False
    return start <= day <= end


def intervals_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def has_submitted_invoice(placement_id):
    for invoice in db.invoices.values():
        if (invoice["placement_id"] == placement_id
                and invoice["verification_status"] == "SUBMITTED"):
            return True
    return False


def active_plan(placement_id):
    for plan in db.plans.values():
        if plan["placement_id"] == placement_id and plan["status"] == "ACTIVE":
            return plan
    return None


# =========================================================================
# reads
# =========================================================================

@endpoint(bp, "GET", "/placements", ALL_ROLES)
def list_placements():
    return collection(db.placements.values(), [
        ("student_id", q_str("student_id")),
        ("school_id", q_str("school_id")),
        ("decision_id", q_str("decision_id")),
        ("rate_schedule_id", q_str("rate_schedule_id")),
        ("fiscal_account_id", q_str("fiscal_account_id")),
        ("prior_placement_id", q_str("prior_placement_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/placements/<placement_id>", ALL_ROLES)
def get_placement(placement_id):
    return single(placement_or_404(placement_id))


@endpoint(bp, "GET", "/placements/<placement_id>/cost-projection", ALL_ROLES)
def get_cost_projection(placement_id):
    placement = placement_or_404(placement_id)
    variant = q_enum("variant", PROJECTION_VARIANTS) or "CONTRACTED_ENCUMBRANCE"
    check_scope(placement)
    return ok(cost_projection(placement, variant))


# =========================================================================
# proposal
# =========================================================================

@endpoint(bp, "POST", "/placements", (PLACEMENT_COORDINATOR,))
def create_placement():
    body = read_body((
        "student_id", "school_id", "decision_id", "rate_schedule_id", "fiscal_account_id",
        "prior_placement_id", "placement_type", "start_date", "end_date",
        "contracted_instructional_days", "contracted_residential_nights",
        "transportation_required",
    ))
    student_id = get_id(body, "student_id")
    school_id = get_id(body, "school_id")
    decision_id = get_id(body, "decision_id")
    schedule_id = get_id(body, "rate_schedule_id")
    account_id = get_id(body, "fiscal_account_id")
    prior_id = get_id(body, "prior_placement_id", required=False, default=None, nullable=True)
    placement_type = get_enum(body, "placement_type", PLACEMENT_TYPES)
    start_date = get_date(body, "start_date")
    end_date = get_date(body, "end_date")
    days = get_int(body, "contracted_instructional_days", minimum=1, maximum=260)
    nights = get_int(body, "contracted_residential_nights", required=False, default=0,
                     minimum=0, maximum=366)
    transportation_required = get_bool(body, "transportation_required", default=False)

    student_or_404(student_id)
    school = school_or_404(school_id)
    decision = decision_or_404(decision_id)
    schedule = schedule_or_404(schedule_id)
    account_or_404(account_id)
    if prior_id is not None:
        placement_or_404(prior_id)

    if placement_type == "DAY" and nights != 0:
        fail("ERR_INVALID_REQUEST",
             "contracted_residential_nights must be exactly 0 on a DAY placement.")

    # rung 9 - linkage
    if decision["student_id"] != student_id or schedule["school_id"] != school_id:
        fail("ERR_PLACEMENT_LINKAGE_MISMATCH",
             "The decision must belong to the student and the rate schedule to the school.")

    # rung 10 - rate effectivity then window sanity
    if not schedule_covers(schedule, start_date):
        fail("ERR_RATE_SCHEDULE_NOT_EFFECTIVE",
             "The rate schedule is not state-approved or does not cover the start date.")
    if end_date <= start_date or start_date < clock_date():
        fail("ERR_INVALID_PLACEMENT_WINDOW",
             "end_date must be later than start_date and start_date may not be in the past.")

    # rung 11 - residential authorisation
    if placement_type == "RESIDENTIAL":
        if (decision["recommended_placement_type"] != "RESIDENTIAL"
                or not school["residential_capable"]):
            fail("ERR_RESIDENTIAL_NOT_AUTHORIZED",
                 "A residential placement requires a residential recommendation and a "
                 "residential-capable school.")

    # rung 12 - student exclusivity
    for other in db.placements.values():
        if other["student_id"] != student_id:
            continue
        if other["status"] not in ("PROPOSED", "CONTRACTED", "ACTIVE"):
            continue
        other_start = parse_date(other["start_date"])
        other_end = parse_date(other["end_date"])
        if other_start is None or other_end is None:
            continue
        if intervals_intersect(start_date, end_date, other_start, other_end):
            fail("ERR_PLACEMENT_DATE_OVERLAP",
                 "The window intersects another live placement for this student.")

    row = new_row("placement", {
        "student_id": student_id,
        "school_id": school_id,
        "decision_id": decision_id,
        "rate_schedule_id": schedule_id,
        "fiscal_account_id": account_id,
        "prior_placement_id": prior_id,
        "placement_type": placement_type,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "contracted_instructional_days": days,
        "contracted_residential_nights": nights,
        "transportation_required": transportation_required,
        "status": "PROPOSED",
        "transport_status": "NOT_REQUIRED",
        "contract_encumbrance_cents": 0,
        "addendum_encumbrance_cents": 0,
        "transport_encumbrance_cents": 0,
        "encumbrance_cents": 0,
        "released_encumbrance_cents": 0,
        "paid_total_ytd_cents": 0,
        "transition_reserve_cents": 0,
        "contract_executed_at": None,
        "activated_at": None,
        "terminated_at": None,
        "termination_reason": None,
    })
    db.placements[row["id"]] = row
    return created(public(row))


# =========================================================================
# execute contract
# =========================================================================

@endpoint(bp, "POST", "/placements/<placement_id>/execute-contract", (FISCAL_OFFICER,))
def execute_contract(placement_id):
    placement = placement_or_404(placement_id)
    read_body(())

    if placement["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a PROPOSED placement may have its contract executed.")

    decision = db.decisions.get(placement["decision_id"])
    if decision is None or decision["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The placement-team decision is not APPROVED.")

    school = db.schools.get(placement["school_id"])
    if school is None or school["approval_status"] not in ("APPROVED", "PROVISIONAL"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A REVOKED school cannot be contracted with.")

    schedule = db.rate_schedules.get(placement["rate_schedule_id"])
    start_date = parse_date(placement["start_date"])
    if (schedule is None
            or schedule["school_id"] != placement["school_id"]
            or not schedule_covers(schedule, start_date)):
        fail("ERR_RATE_SCHEDULE_NOT_EFFECTIVE",
             "The pinned rate schedule is no longer effective for this placement.")

    if placement["placement_type"] == "RESIDENTIAL":
        if not school["residential_capable"] or school["approval_status"] != "APPROVED":
            fail("ERR_RESIDENTIAL_NOT_AUTHORIZED",
                 "A residential contract requires a fully approved, residential-capable school.")

    amount = placement_encumbrance(placement, schedule)
    account = db.accounts.get(placement["fiscal_account_id"])
    if account is None or account["available_cents"] < amount:
        fail("ERR_INSUFFICIENT_FISCAL_AUTHORITY",
             "The appropriation cannot cover the contract encumbrance.")

    placement["contract_encumbrance_cents"] = amount
    placement["status"] = "CONTRACTED"
    placement["contract_executed_at"] = now_iso()
    if placement["transportation_required"]:
        placement["transport_status"] = "PENDING"
    recompute_placement_encumbrance(placement)
    touch(placement)
    book_encumbrance(account, amount)
    return ok(public(placement))


# =========================================================================
# activation
# =========================================================================

@endpoint(bp, "POST", "/placements/<placement_id>/activate", (PLACEMENT_COORDINATOR,))
def activate_placement(placement_id):
    placement = placement_or_404(placement_id)
    read_body(())

    if placement["status"] != "CONTRACTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a CONTRACTED placement may be activated.")

    start_date = parse_date(placement["start_date"])
    today = clock_date()
    if start_date is None or today < start_date:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A placement may not be activated before its start date.")
    if today > add_days(start_date, CONTRACT_ACTIVATION_GRACE_DAYS):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The contract activation grace window has closed.")

    if placement["transportation_required"]:
        has_active = any(
            a["placement_id"] == placement["id"] and a["status"] == "ACTIVE"
            for a in db.assignments.values()
        )
        if not has_active:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The IEP requires transportation and no assignment is ACTIVE.")

    school = db.schools.get(placement["school_id"])
    if school is None or school["approval_status"] != "APPROVED":
        fail("ERR_SCHOOL_NOT_APPROVED",
             "The receiving school must be APPROVED at the moment of activation.")

    placement["status"] = "ACTIVE"
    placement["activated_at"] = now_iso()
    touch(placement)

    student = db.students.get(placement["student_id"])
    if student is not None:
        student["placement_status"] = "OOD_ACTIVE"
        touch(student)
    return ok(public(placement))


# =========================================================================
# closure
# =========================================================================

@endpoint(bp, "POST", "/placements/<placement_id>/terminate", (PLACEMENT_COORDINATOR,))
def terminate_placement(placement_id):
    placement = placement_or_404(placement_id)
    body = read_body(("termination_reason",))
    reason = get_text(body, "termination_reason")

    if placement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE placement may be terminated.")
    if has_submitted_invoice(placement["id"]):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An invoice on this placement is still awaiting verification.")

    close_placement(placement, "TERMINATE", reason)
    return ok(public(placement))


@endpoint(bp, "POST", "/placements/<placement_id>/return-to-district", (PLACEMENT_COORDINATOR,))
def return_placement_to_district(placement_id):
    placement = placement_or_404(placement_id)
    body = read_body(("return_reason", "receiving_lre_setting"))
    reason = get_text(body, "return_reason")
    setting = get_enum(body, "receiving_lre_setting", LRE_SETTINGS)

    if placement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an ACTIVE placement may be returned to district.")
    if has_submitted_invoice(placement["id"]):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An invoice on this placement is still awaiting verification.")
    if active_plan(placement["id"]) is None:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A student may only be returned under an ACTIVE return transition plan.")

    close_placement(placement, "RETURN", reason, receiving_lre_setting=setting)
    return ok(public(placement))
