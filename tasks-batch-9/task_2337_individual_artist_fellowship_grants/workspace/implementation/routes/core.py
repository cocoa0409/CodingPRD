"""Clock, FellowshipCycle, DisciplineCategory and Artist endpoints."""

from flask import Blueprint

import constants as C
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from routes import support as sup
from services import calc, cascade, derive

bp = Blueprint("core", __name__)

PO = (mw.PROGRAM_OFFICER,)
ALL = sup.ALL_ROLES
NO_PANELIST = sup.NO_PANELIST


# ============================================================== logical clock


@bp.post("/_clock/set_current_utc")
def set_clock():
    """The only endpoint outside the auth surface (see P10)."""
    data = v.body()
    raw = v.req_dt(data, "to_iso8601")
    db.set_now(db.parse_dt(raw))
    forfeited, delinquent, held = cascade.checkpoint()
    return response.obj(
        {
            "current_utc": db.iso3(db.now()),
            "forfeited_award_ids": forfeited,
            "delinquent_award_ids": delinquent,
            "held_installment_ids": held,
        }
    )


# =============================================================== cycles


@bp.post("/grants/cycles")
def create_cycle():
    mw.authorize(PO)
    data = v.body()
    name = v.req_str(data, "name")
    fiscal_year = v.req_int(data, "fiscal_year", minimum=1)
    open_at = v.req_dt(data, "application_open_at")
    deadline_at = v.req_dt(data, "application_deadline_at")
    period_start = v.req_dt(data, "grant_period_start")
    period_end = v.req_dt(data, "grant_period_end")
    total_budget = v.req_int(data, "total_budget_cents", minimum=1)
    base_award = v.req_int(data, "base_award_cents", minimum=1)
    min_prorated = v.req_int(data, "min_prorated_award_cents", minimum=1)
    residency_min = v.req_int(data, "residency_min_months", minimum=0)
    blackout_years = v.req_int(data, "award_blackout_years", minimum=0)
    policy = v.opt_enum(data, "proration_policy", C.PRORATION_POLICIES, "PRORATE")
    max_rounds = v.opt_int(data, "max_review_rounds", 2, minimum=1)
    acceptance_days = v.opt_int(data, "acceptance_window_days", 14, minimum=0)
    appeal_days = v.opt_int(data, "appeal_window_days", 30, minimum=0)
    report_offset = v.opt_int(data, "final_report_due_offset_days", 60, minimum=0)

    if min_prorated > base_award:
        v.bad("min_prorated_award_cents must be <= base_award_cents.")
    if db.parse_dt(deadline_at) <= db.parse_dt(open_at):
        v.bad("application_deadline_at must be after application_open_at.")
    if db.parse_dt(period_end) <= db.parse_dt(period_start):
        v.bad("grant_period_end must be after grant_period_start.")

    cycle = db.insert(
        "cycles",
        {
            "name": name,
            "fiscal_year": fiscal_year,
            "application_open_at": open_at,
            "application_deadline_at": deadline_at,
            "grant_period_start": period_start,
            "grant_period_end": period_end,
            "total_budget_cents": total_budget,
            "base_award_cents": base_award,
            "min_prorated_award_cents": min_prorated,
            "proration_policy": policy,
            "residency_min_months": residency_min,
            "award_blackout_years": blackout_years,
            "max_review_rounds": max_rounds,
            "acceptance_window_days": acceptance_days,
            "appeal_window_days": appeal_days,
            "final_report_due_offset_days": report_offset,
            "status": "DRAFT",
            "funded_total_cents": 0,
            "admin_assessment_rate": 0.0,
            "admin_assessment_cents": 0,
            "reserve_cents": 0,
            "committed_cents": 0,
            "available_cents": 0,
            "posture": "OPEN",
            "unresolved_breach_count": 0,
            "blocking_conflict_count": 0,
        },
    )
    derive.refresh_cycle(cycle)
    return response.obj(db.public(cycle), 201)


@bp.get("/grants/cycles/<cycle_id>")
def read_cycle(cycle_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("cycles", cycle_id)))


@bp.get("/grants/cycles")
def list_cycles():
    mw.authorize(ALL)
    status = v.query_str("status")
    fiscal_year = v.query_int("fiscal_year")
    posture = v.query_str("posture")
    rows = db.rows("cycles")
    rows.reverse()  # newest first, created_at DESC
    rows = sup.eq(rows, "status", status)
    rows = sup.eq(rows, "fiscal_year", fiscal_year)
    rows = sup.eq(rows, "posture", posture)
    return sup.listed(rows)


def _allocation_total(cycle_id):
    return sum(
        int(d["allocation_cents"])
        for d in db.rows("disciplines", lambda r: r["cycle_id"] == cycle_id)
    )


@bp.post("/grants/cycles/<cycle_id>/status")
def cycle_status(cycle_id):
    mw.authorize(PO)
    data = v.body()
    to_status = v.req_enum(data, "to_status", C.CYCLE_STATUSES)
    cycle = sup.resolve("cycles", cycle_id)

    # P65 target-entity state.
    if to_status not in C.CYCLE_TRANSITIONS[cycle["status"]]:
        raise ApiError(
            "ERR_CYCLE_STATE_INVALID",
            "A cycle in %s cannot move to %s." % (cycle["status"], to_status),
        )

    if to_status == "OPEN":
        if not db.rows("disciplines", lambda r: r["cycle_id"] == cycle["id"]):
            raise ApiError("ERR_CYCLE_HAS_NO_DISCIPLINES")
        ceiling = int(cycle["total_budget_cents"]) - int(cycle["reserve_cents"])
        if _allocation_total(cycle["id"]) > ceiling:
            raise ApiError("ERR_ALLOCATION_EXCEEDS_BUDGET")

    elif to_status == "CLOSED":
        if db.now() < db.dt_of(cycle, "application_deadline_at"):
            raise ApiError("ERR_DEADLINE_NOT_REACHED")

    elif to_status == "PANEL_REVIEW":
        pending = [
            a
            for a in derive.applications_of_cycle(cycle["id"])
            if a["status"] == "SUBMITTED"
        ]
        if pending:
            raise ApiError(
                "ERR_APPLICATION_STATE_INVALID",
                "Every submitted application needs an eligibility determination.",
            )

    elif to_status == "BOARD_REVIEW":
        panels = derive.panels_of_cycle(cycle["id"])
        for panel in panels:
            if panel["status"] not in ("DELIBERATING", "SLATE_SUBMITTED", "DISSOLVED"):
                raise ApiError("ERR_PANEL_STATE_INVALID")
        for panel in panels:
            if panel["reopen_required"]:
                raise ApiError("ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND")

    elif to_status == "AWARDED":
        proposed = [
            s
            for s in db.rows("slots", lambda r: r["cycle_id"] == cycle["id"])
            if s["status"] == "PROPOSED"
        ]
        if proposed:
            raise ApiError("ERR_SLOTS_PENDING_BOARD_ACTION")

    elif to_status == "CLOSED_OUT":
        for award in derive.awards_of_cycle(cycle["id"]):
            if award["status"] not in C.AWARD_TERMINAL_STATUSES:
                raise ApiError("ERR_CYCLE_HAS_OPEN_AWARDS")
        app_ids = {a["id"] for a in derive.applications_of_cycle(cycle["id"])}
        for appeal in db.rows("appeals", lambda r: r["application_id"] in app_ids):
            if appeal["status"] not in ("UPHELD", "DENIED"):
                raise ApiError("ERR_APPEAL_STATE_INVALID")

    derive.set_fields(cycle, status=to_status)

    if to_status == "AWARDED":
        cascade.cycle_awarded(cycle)
    elif to_status == "CANCELLED":
        cascade.cycle_cancelled(cycle)
    elif to_status == "CLOSED_OUT":
        cascade.cycle_closed_out(cycle)

    for discipline in db.rows("disciplines", lambda r: r["cycle_id"] == cycle["id"]):
        derive.refresh_discipline(discipline)
    derive.refresh_cycle(cycle)
    return response.obj(db.public(cycle))


@bp.get("/grants/cycles/<cycle_id>/evaluation")
def cycle_evaluation(cycle_id):
    mw.authorize((mw.PROGRAM_OFFICER, mw.BOARD, mw.APPEALS))
    cycle = sup.resolve("cycles", cycle_id)
    pool = [
        a
        for a in derive.applications_of_cycle(cycle["id"])
        if a["status"] not in C.DIVERSITY_EXCLUDED_STATUSES
    ]
    funded = [
        a
        for a in derive.awards_of_cycle(cycle["id"])
        if a["status"] not in ("DECLINED", "RESCINDED", "FORFEITED")
    ]
    disciplines = sorted(
        db.rows("disciplines", lambda r: r["cycle_id"] == cycle["id"]),
        key=lambda r: r["code"],
    )
    breakdown = [
        {
            "discipline_category_id": d["id"],
            "code": d["code"],
            "eligible_application_count": d["eligible_application_count"],
            "funded_application_count": d["funded_application_count"],
            "committed_cents": d["committed_cents"],
        }
        for d in disciplines
    ]
    payload = calc.diversity_evaluation(pool, len(funded), disciplines, breakdown)
    payload["cycle_id"] = cycle["id"]
    return response.obj(payload)


# ================================================== discipline categories


@bp.post("/grants/discipline-categories")
def create_discipline():
    mw.authorize(PO)
    data = v.body()
    cycle_id = v.req_id(data, "cycle_id")
    code = v.req_enum(data, "code", C.DISCIPLINE_CODES)
    alias_prefix = v.req_str(data, "alias_prefix")
    allocation = v.req_int(data, "allocation_cents", minimum=1)
    required_samples = v.req_int(data, "required_work_sample_count", minimum=1)
    allowed_media = v.req_code_list(data, "allowed_media", C.MEDIA)
    required_seats = v.req_int(data, "required_panel_seats", minimum=3)
    required_regions = v.req_code_list(data, "required_regions", C.REGIONS)
    max_duration = v.opt_int(data, "max_total_duration_seconds", 600, minimum=0)
    max_panels = v.opt_int(data, "max_concurrent_panels", 1, minimum=1)

    cycle = sup.resolve_fk("cycles", cycle_id)

    for existing in db.rows("disciplines", lambda r: r["cycle_id"] == cycle_id):
        if existing["code"] == code:
            v.bad("code %s already exists on this cycle." % code)

    ceiling = int(cycle["total_budget_cents"]) - int(cycle["reserve_cents"])
    if _allocation_total(cycle_id) + allocation > ceiling:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_BUDGET")

    discipline = db.insert(
        "disciplines",
        {
            "cycle_id": cycle_id,
            "code": code,
            "alias_prefix": alias_prefix,
            "allocation_cents": allocation,
            "required_work_sample_count": required_samples,
            "allowed_media": allowed_media,
            "max_total_duration_seconds": max_duration,
            "required_panel_seats": required_seats,
            "required_regions": required_regions,
            "max_concurrent_panels": max_panels,
            "committed_cents": 0,
            "eligible_application_count": 0,
            "funded_application_count": 0,
            "submitted_sequence_counter": 0,
        },
    )
    return response.obj(db.public(discipline), 201)


@bp.get("/grants/discipline-categories/<discipline_category_id>")
def read_discipline(discipline_category_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("disciplines", discipline_category_id)))


@bp.get("/grants/discipline-categories")
def list_disciplines():
    mw.authorize(ALL)
    rows = db.rows("disciplines")
    rows = sup.eq(rows, "cycle_id", v.query_str("cycle_id"))
    rows = sup.eq(rows, "code", v.query_str("code"))
    return sup.listed(rows)


# =============================================================== artists


def _email_taken(email, skip_id=None):
    for artist in db.rows("artists"):
        if artist["email"] == email and artist["id"] != skip_id:
            return True
    return False


@bp.post("/grants/artists")
def create_artist():
    mw.authorize(PO)
    data = v.body()
    legal_name = v.req_str(data, "legal_name")
    email = v.req_str(data, "email")
    residency_start = v.req_dt(data, "residency_start_date")
    county = v.req_str(data, "residency_county")
    region = v.req_enum(data, "region", C.REGIONS)
    is_student = v.opt_bool(data, "is_enrolled_student", False)
    tin_status = v.opt_enum(data, "tin_status", C.TIN_STATUSES, "MISSING")

    if _email_taken(email):
        v.bad("email is already registered.")

    artist = db.insert(
        "artists",
        {
            "legal_name": legal_name,
            "email": email,
            "residency_start_date": residency_start,
            "residency_county": county,
            "region": region,
            "is_enrolled_student": is_student,
            "tin_status": tin_status,
            "standing": "GOOD_STANDING",
            "last_award_fiscal_year": None,
            "last_award_period_end": None,
            "prior_award_count": 0,
            "active_award_count": 0,
            "delinquent_award_count": 0,
            "debar_reason_code": None,
        },
    )
    return response.obj(db.public(artist), 201)


@bp.get("/grants/artists/<artist_id>")
def read_artist(artist_id):
    mw.authorize(NO_PANELIST)
    return response.obj(db.public(sup.resolve("artists", artist_id)))


@bp.get("/grants/artists")
def list_artists():
    mw.authorize(NO_PANELIST)
    rows = db.rows("artists")
    rows = sup.eq(rows, "region", v.query_str("region"))
    rows = sup.eq(rows, "standing", v.query_str("standing"))
    rows = sup.eq(rows, "tin_status", v.query_str("tin_status"))
    return sup.listed(rows)


@bp.patch("/grants/artists/<artist_id>")
def patch_artist(artist_id):
    mw.authorize(PO)
    data = v.body()
    fields = {}
    if "legal_name" in data:
        fields["legal_name"] = v.req_str(data, "legal_name")
    if "email" in data:
        fields["email"] = v.req_str(data, "email")
    if "residency_start_date" in data:
        fields["residency_start_date"] = v.req_dt(data, "residency_start_date")
    if "residency_county" in data:
        fields["residency_county"] = v.req_str(data, "residency_county")
    if "region" in data:
        fields["region"] = v.req_enum(data, "region", C.REGIONS)
    if "is_enrolled_student" in data:
        fields["is_enrolled_student"] = v.req_bool(data, "is_enrolled_student")
    if "tin_status" in data:
        fields["tin_status"] = v.req_enum(data, "tin_status", C.TIN_STATUSES)

    artist = sup.resolve("artists", artist_id)
    if "email" in fields and _email_taken(fields["email"], artist["id"]):
        v.bad("email is already registered.")
    derive.set_fields(artist, **fields)
    return response.obj(db.public(artist))


@bp.post("/grants/artists/<artist_id>/award-history")
def award_history(artist_id):
    mw.authorize(PO)
    data = v.body()
    fiscal_year = v.req_int(data, "fiscal_year", minimum=1)
    period_end = v.req_dt(data, "grant_period_end")
    artist = sup.resolve("artists", artist_id)

    year = artist["last_award_fiscal_year"]
    new_year = fiscal_year if year is None else max(int(year), fiscal_year)
    current_end = artist["last_award_period_end"]
    if current_end is None or db.parse_dt(period_end) > db.parse_dt(current_end):
        new_end = period_end
    else:
        new_end = current_end
    derive.set_fields(
        artist,
        prior_award_count=int(artist["prior_award_count"]) + 1,
        last_award_fiscal_year=new_year,
        last_award_period_end=new_end,
    )
    return response.obj(db.public(artist))


@bp.post("/grants/artists/<artist_id>/debar")
def debar_artist(artist_id):
    mw.authorize(PO)
    data = v.body()
    reason = v.req_enum(data, "debar_reason_code", C.DEBAR_REASONS)
    artist = sup.resolve("artists", artist_id)
    derive.set_fields(artist, standing="DEBARRED", debar_reason_code=reason)
    cascade.hold_scheduled_installments(artist, "ARTIST_DEBARRED")
    return response.obj(db.public(artist))
