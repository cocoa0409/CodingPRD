"""Logical clock, cycles, disciplines, slate lock and the funder outcome report."""

from decimal import Decimal

import calc
import domain as D
import store as K
from auth import authorize
from envelope import object_response, paged, query_str
from errors import ApiError
from flask import Blueprint
from store import COLLECTION_NAMES, create_row, iso_ms, store, touch
from validate import (bad, body, opt_decimal, opt_instant, opt_int, opt_int_list,
                      opt_bool, opt_enum, opt_enum_list, path_row, req_decimal,
                      req_enum, req_instant, req_int, req_int_list, req_str,
                      req_enum_list, fk, ds)

bp = Blueprint("cycles", __name__)

READ_CYCLE_ROLES = ["ProgramAdmin", "PanelChair", "FinanceOfficer", "Funder",
                    "VisaCoordinator", "FacilitiesManager"]
READ_DISCIPLINE_ROLES = ["ProgramAdmin", "PanelChair", "Panelist", "Applicant",
                         "FacilitiesManager", "Funder"]

CYCLE_STAGE_EDGES = {
    ("DRAFT", "OPEN"),
    ("OPEN", "SCREENING"),
    ("SCREENING", "PANEL_REVIEW"),
    ("SLATE_LOCKED", "CLOSED"),
}


# ---------------------------------------------------------------- logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(["ProgramAdmin"])
    b = body()
    instant = req_instant(b, "current_utc")
    store.clock = instant
    return object_response({"current_utc": iso_ms(instant)}, 200)


# ---------------------------------------------------------------- cycles
def _validate_cycle_payload(b, existing=None):
    """Shape/range checks shared by create and the DRAFT-only edit."""
    out = {}
    required = existing is None

    def pick(name, value):
        if value is not None:
            out[name] = value

    open_at = req_instant(b, "open_at") if required else opt_instant(b, "open_at")
    close_at = req_instant(b, "close_at") if required else opt_instant(b, "close_at")
    pick("open_at", open_at)
    pick("close_at", close_at)

    fee = req_int(b, "application_fee_cents", minimum=0) if required \
        else opt_int(b, "application_fee_cents", minimum=0)
    pick("application_fee_cents", fee)

    quorum = req_int(b, "panel_quorum", minimum=2) if required \
        else opt_int(b, "panel_quorum", minimum=2)
    pick("panel_quorum", quorum)

    target = req_int(b, "cohort_target_size", minimum=1) if required \
        else opt_int(b, "cohort_target_size", minimum=1)
    pick("cohort_target_size", target)

    reserve = req_decimal(b, "alumni_reserve_pct", minimum=0, maximum=1, places=2) if required \
        else opt_decimal(b, "alumni_reserve_pct", minimum=0, maximum=1, places=2)
    pick("alumni_reserve_pct", reserve)

    pool = req_int(b, "stipend_pool_cents", minimum=0) if required \
        else opt_int(b, "stipend_pool_cents", minimum=0)
    pick("stipend_pool_cents", pool)

    floor_score = req_decimal(b, "slate_min_score", minimum=0, maximum=100, places=2) if required \
        else opt_decimal(b, "slate_min_score", minimum=0, maximum=100, places=2)
    pick("slate_min_score", floor_score)

    rate = req_int(b, "stipend_weekly_rate_cents", minimum=0) if required \
        else opt_int(b, "stipend_weekly_rate_cents", minimum=0)
    pick("stipend_weekly_rate_cents", rate)

    options = req_int_list(b, "session_length_options_weeks", minimum=K.MIN_SESSION_WEEKS,
                           maximum=K.MAX_SESSION_WEEKS, allow_empty=False) if required \
        else opt_int_list(b, "session_length_options_weeks", minimum=K.MIN_SESSION_WEEKS,
                          maximum=K.MAX_SESSION_WEEKS, allow_empty=False)
    pick("session_length_options_weeks", options)

    effective_open = out.get("open_at", existing["_open_at"] if existing else None)
    effective_close = out.get("close_at", existing["_close_at"] if existing else None)
    if effective_open is not None and effective_close is not None \
            and not effective_close > effective_open:
        bad("close_at must fall strictly later than open_at")
    return out


@bp.route("/cycles", methods=["POST"])
def create_cycle():
    authorize(["ProgramAdmin"])
    b = body()
    code = req_str(b, "code", min_len=1, max_len=32)
    fields = _validate_cycle_payload(b)
    for row in store.cycles.values():
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", "cycle code %s already exists" % code)
    row = create_row(store.cycles, {
        "code": code,
        "open_at": iso_ms(fields["open_at"]),
        "_open_at": fields["open_at"],
        "close_at": iso_ms(fields["close_at"]),
        "_close_at": fields["close_at"],
        "application_fee_cents": fields["application_fee_cents"],
        "panel_quorum": fields["panel_quorum"],
        "cohort_target_size": fields["cohort_target_size"],
        "alumni_reserve_pct": fields["alumni_reserve_pct"],
        "stipend_pool_cents": fields["stipend_pool_cents"],
        "slate_min_score": fields["slate_min_score"],
        "stipend_weekly_rate_cents": fields["stipend_weekly_rate_cents"],
        "session_length_options_weeks": fields["session_length_options_weeks"],
        "status": "DRAFT",
        "alumni_reserved_slots": 0,
    })
    return object_response(D.ser_cycle(row), 201)


@bp.route("/cycles", methods=["GET"])
def list_cycles():
    authorize(READ_CYCLE_ROLES)
    status = query_str("status")
    code = query_str("code")
    rows = D.by_seq(list(store.cycles.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    return paged(rows, D.ser_cycle)


@bp.route("/cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    authorize(READ_CYCLE_ROLES)
    row = path_row(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    return object_response(D.ser_cycle(row))


@bp.route("/cycles/<cycle_id>", methods=["PATCH"])
def patch_cycle(cycle_id):
    authorize(["ProgramAdmin"])
    row = path_row(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    b = body()
    fields = _validate_cycle_payload(b, existing=row)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_CYCLE_STAGE_INVALID", "a cycle may only be edited while DRAFT")
    for key, value in fields.items():
        if key == "open_at":
            row["open_at"] = iso_ms(value)
            row["_open_at"] = value
        elif key == "close_at":
            row["close_at"] = iso_ms(value)
            row["_close_at"] = value
        else:
            row[key] = value
    touch(row)
    return object_response(D.ser_cycle(row))


@bp.route("/cycles/<cycle_id>/stage", methods=["POST"])
def cycle_stage(cycle_id):
    authorize(["ProgramAdmin"])
    row = path_row(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    b = body()
    to_status = req_enum(b, "to_status", K.CYCLE_STATUSES)
    current = row["status"]
    if (current, to_status) not in CYCLE_STAGE_EDGES:
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "%s is not an edge from %s" % (to_status, current))
    apps = D.cycle_applications(cycle_id)
    if to_status == "OPEN":
        disciplines = D.cycle_disciplines(cycle_id)
        if not disciplines:
            raise ApiError("ERR_COHORT_MINIMUMS_EXCEED_TARGET",
                           "a cycle needs at least one discipline before it opens")
        if sum(x["cohort_min_slots"] for x in disciplines) > row["cohort_target_size"]:
            raise ApiError("ERR_COHORT_MINIMUMS_EXCEED_TARGET",
                           "discipline minimums together exceed the cohort target")
    elif to_status == "SCREENING":
        if any(a["status"] == "DRAFT" for a in apps):
            raise ApiError("ERR_CYCLE_STAGE_INVALID",
                           "an application of this cycle is still DRAFT")
    elif to_status == "PANEL_REVIEW":
        if any(a["status"] == "SUBMITTED" for a in apps):
            raise ApiError("ERR_CYCLE_STAGE_INVALID",
                           "an application of this cycle is still SUBMITTED")
    elif to_status == "CLOSED":
        if any(a["status"] == "OFFERED" for a in apps):
            raise ApiError("ERR_CYCLE_STAGE_INVALID",
                           "an application of this cycle is still OFFERED")

    row["status"] = to_status
    if to_status == "CLOSED":
        for app in apps:
            if app["status"] == "WAITLISTED":
                app["status"] = "REJECTED"
                app["waitlist_rank"] = None
                touch(app)
    touch(row)
    return object_response(D.ser_cycle(row))


# ---------------------------------------------------------------- slate lock
def _cycle_scored_or_conflicted_panelists(cycle_id):
    """Every panelist who reviewed or declared a conflict anywhere in the cycle."""
    app_ids = set(a["id"] for a in D.cycle_applications(cycle_id))
    out = set()
    for pa in store.panel_assignments.values():
        if pa["application_id"] in app_ids and pa["status"] in ("SCORED", "CONFLICT_DECLARED"):
            out.add(pa["panelist_id"])
    return out


def _allocate_slate(cycle):
    """The three-bucket waterfall of PRD 3.5.  Returns (selected, pool)."""
    target = int(cycle["cohort_target_size"])
    floor_score = cycle["slate_min_score"]
    scored = [a for a in D.cycle_applications(cycle["id"]) if a["status"] == "SCORED"]
    pool = [a for a in scored if a.get("final_panel_score") is not None
            and a["final_panel_score"] >= floor_score]

    reserved = calc.alumni_reserved_slots(cycle["alumni_reserve_pct"], target)
    if target - reserved < 0:
        raise ApiError("ERR_ALUMNI_RESERVE_EXCEEDS_COHORT",
                       "the rounded-up alumni reserve exceeds the cohort target")

    selected = []
    selected_ids = set()
    per_discipline = {}

    def take(app):
        selected.append(app)
        selected_ids.add(app["id"])
        per_discipline[app["discipline_id"]] = per_discipline.get(app["discipline_id"], 0) + 1

    def is_alumnus(app):
        return D.applicant_completed_residency_count(app["applicant_id"]) >= 1

    def at_max(discipline_id):
        discipline = store.disciplines.get(discipline_id)
        if discipline is None:
            return False
        return per_discipline.get(discipline_id, 0) >= int(discipline["cohort_max_slots"])

    # bucket 1 -- discipline minimums, walked in ascending discipline code order
    disciplines = sorted(D.cycle_disciplines(cycle["id"]), key=lambda x: x["code"])
    for discipline in disciplines:
        minimum = int(discipline["cohort_min_slots"])
        candidates = D.merit_order([a for a in pool
                                    if a["discipline_id"] == discipline["id"]
                                    and a["id"] not in selected_ids])
        taken = 0
        for app in candidates:
            if taken >= minimum or len(selected) >= target:
                break
            take(app)
            taken += 1
        if taken < minimum:
            raise ApiError("ERR_DISCIPLINE_MINIMUM_UNFILLABLE",
                           "discipline %s cannot fill its minimum of %d slots"
                           % (discipline["code"], minimum))

    # bucket 2 -- alumni reserve, pinned to the cohort target
    alumni_selected = len([a for a in selected if is_alumnus(a)])
    for app in D.merit_order([a for a in pool if a["id"] not in selected_ids]):
        if alumni_selected >= reserved or len(selected) >= target:
            break
        if not is_alumnus(app):
            continue
        if at_max(app["discipline_id"]):
            continue
        take(app)
        alumni_selected += 1

    # bucket 3 -- general merit
    for app in D.merit_order([a for a in pool if a["id"] not in selected_ids]):
        if len(selected) >= target:
            break
        if at_max(app["discipline_id"]):
            continue
        take(app)

    cycle["alumni_reserved_slots"] = reserved
    return selected, pool, scored, selected_ids


@bp.route("/cycles/<cycle_id>/lock-slate", methods=["POST"])
def lock_slate(cycle_id):
    actor = authorize(["PanelChair"], chair_eligibility=True)
    cycle = path_row(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    if cycle["status"] != "PANEL_REVIEW":
        raise ApiError("ERR_CYCLE_STAGE_INVALID",
                       "the slate may only be locked from PANEL_REVIEW")
    if actor.user_id in _cycle_scored_or_conflicted_panelists(cycle_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "a chair who reviewed in this cycle may not adjudicate its outcome")
    if not D.cycle_panel_review_complete(cycle_id):
        raise ApiError("ERR_PANEL_REVIEW_INCOMPLETE",
                       "panel review of this cycle is not complete")

    selected, pool, scored, selected_ids = _allocate_slate(cycle)
    pool_ids = set(a["id"] for a in pool)

    for app in selected:
        app["status"] = "OFFERED"
        app["waitlist_rank"] = None
        touch(app)
    for app in pool:
        if app["id"] in selected_ids:
            continue
        app["status"] = "WAITLISTED"
        touch(app)
    for app in scored:
        if app["id"] in pool_ids:
            continue
        app["status"] = "REJECTED"
        app["waitlist_rank"] = None
        touch(app)
    D.rerank_waitlist(cycle_id)

    cycle["status"] = "SLATE_LOCKED"
    touch(cycle)
    return object_response(D.ser_cycle(cycle))


# ---------------------------------------------------------------- funder outcome report
def _pct(numerator, denominator):
    if denominator == 0:
        return None
    return calc.pct2(Decimal(100) * Decimal(numerator) / Decimal(denominator))


@bp.route("/cycles/<cycle_id>/funder-outcome-report", methods=["GET"])
def funder_outcome_report(cycle_id):
    authorize(["ProgramAdmin", "Funder"])
    cycle = path_row(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    residencies = D.cycle_residencies(cycle["id"])
    awarded = [r for r in residencies if r["status"] in D.AWARDED_STATUSES]
    awarded_count = len(awarded)
    completed_count = len([r for r in residencies if r["status"] == "COMPLETED"])
    terminated_count = len([r for r in residencies if r["status"] == "TERMINATED"])
    withdrawn_count = len([r for r in residencies if r["status"] == "WITHDRAWN"])

    international = len([r for r in awarded if D.residency_visa_required(r)])
    alumni = len([r for r in awarded
                  if D.applicant_completed_residency_count(r["applicant_id"]) >= 1])
    follow_on = len([r for r in residencies if r.get("predecessor_residency_id") is not None])

    required_total = sum(int(r["obligations_required_total"]) for r in residencies)
    completed_total = sum(int(r["obligations_completed_total"]) for r in residencies)
    breached = sum(int(r["obligations_breached_count"]) for r in residencies)
    attendance = 0
    for res in residencies:
        for ob in D.residency_obligations(res["id"]):
            attendance += int(ob["total_attendance"])

    data = {
        "awarded_count": awarded_count,
        "completed_count": completed_count,
        "terminated_count": terminated_count,
        "withdrawn_count": withdrawn_count,
        "completion_rate_pct": _pct(completed_count, awarded_count),
        "international_share_pct": _pct(international, awarded_count),
        "alumni_share_pct": _pct(alumni, awarded_count),
        "follow_on_count": follow_on,
        "obligation_fulfilment_pct": _pct(completed_total, required_total),
        "breached_obligation_count": breached,
        "total_attendance": attendance,
        "stipend_paid_cents": sum(int(r["stipend_paid_gross_cents"]) for r in residencies),
        "withholding_cents": sum(int(r["withholding_to_date_cents"]) for r in residencies),
    }
    return object_response(data)


# ---------------------------------------------------------------- disciplines
DISCIPLINE_CODE_PATTERN = r"^[A-Z0-9_]{2,16}$"


@bp.route("/disciplines", methods=["POST"])
def create_discipline():
    authorize(["ProgramAdmin"])
    b = body()
    cycle = fk(b, "cycle_id", store.cycles, "ERR_CYCLE_NOT_FOUND")
    req_str(b, "cycle_id")
    code = req_str(b, "code", min_len=2, max_len=16, pattern=DISCIPLINE_CODE_PATTERN)
    name = req_str(b, "name", min_len=1, max_len=200)
    portfolio_min = req_int(b, "portfolio_min_items", minimum=1)
    portfolio_max = req_int(b, "portfolio_max_items", minimum=1)
    if portfolio_max < portfolio_min:
        bad("portfolio_max_items must be at least portfolio_min_items")
    required_media = req_enum_list(b, "required_media_types", K.MEDIA_TYPES)
    requires_hazmat = opt_bool(b, "requires_hazmat_review", default=False)
    cohort_min = req_int(b, "cohort_min_slots", minimum=0)
    cohort_max = req_int(b, "cohort_max_slots", minimum=0)
    if cohort_max < cohort_min:
        bad("cohort_max_slots must be at least cohort_min_slots")
    tags = req_enum_list(b, "required_capability_tags", K.CAPABILITY_TAGS)
    ventilation = opt_enum(b, "required_ventilation_class", K.VENTILATION_CLASSES,
                           default="NONE")

    if cycle["status"] != "DRAFT":
        raise ApiError("ERR_CYCLE_NOT_OPEN",
                       "disciplines may only be added while the cycle is DRAFT")
    if D.discipline_by_code(cycle["id"], code) is not None:
        raise ApiError("ERR_DUPLICATE_CODE",
                       "discipline code %s already exists in this cycle" % code)

    row = create_row(store.disciplines, {
        "cycle_id": cycle["id"],
        "code": code,
        "name": name,
        "portfolio_min_items": portfolio_min,
        "portfolio_max_items": portfolio_max,
        "required_media_types": required_media,
        "requires_hazmat_review": requires_hazmat,
        "cohort_min_slots": cohort_min,
        "cohort_max_slots": cohort_max,
        "required_capability_tags": tags,
        "required_ventilation_class": ventilation,
    }, versioned=False)
    return object_response(D.ser_discipline(row), 201)


@bp.route("/disciplines", methods=["GET"])
def list_disciplines():
    authorize(READ_DISCIPLINE_ROLES)
    cycle_id = query_str("cycle_id")
    code = query_str("code")
    rows = D.by_seq(list(store.disciplines.values()))
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    return paged(rows, D.ser_discipline)


@bp.route("/disciplines/<discipline_id>", methods=["GET"])
def get_discipline(discipline_id):
    authorize(READ_DISCIPLINE_ROLES)
    row = path_row(store.disciplines, discipline_id, "ERR_DISCIPLINE_NOT_FOUND")
    return object_response(D.ser_discipline(row))
