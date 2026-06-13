"""Summons endpoints: get, qualification, check-in, release, mark-fta, and the
summons-scoped collections (qualification, check-ins, pay-vouchers, dispositions,
assignments, strikes).

The Summons state machine (scaffold §1.2) forks at qualification and branches
through disposition decisions, panel seating, release, and FTA.
"""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import serializers
from middleware import get_identity, require_roles
from response import success
from services import core

bp = Blueprint("summonses", __name__)


def _require_summons(summons_id):
    s = core.get_summons(summons_id)
    if s is None:
        raise errors.err("ERR_NOT_FOUND", "Summons not found")
    return s


def _term_report_date_dt(term):
    return helpers.parse_iso8601(term["report_date"], "report_date")


# ---------------------------------------------------------------------------
# GET /summonses/{id}
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>", methods=["GET"])
def get_summons(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})
    s = _require_summons(summons_id)
    return success(serializers.summons(s), status=200)


# ---------------------------------------------------------------------------
# POST /summonses/{id}/qualification  (Juror, own summons)
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/qualification", methods=["POST"])
def submit_qualification(summons_id):
    user_id, role = get_identity()
    require_roles(role, {"Juror"})

    s = _require_summons(summons_id)

    # Ownership (priority 11): juror acting on a summons must own it.
    if s["juror_id"] != user_id:
        raise errors.err("ERR_FORBIDDEN", "Juror does not own this summons")

    # State (priority 21): only from SUMMONED; a second submission is invalid.
    if s["status"] != "SUMMONED":
        raise errors.err("ERR_INVALID_STATE", "Qualification is only allowed from SUMMONED")

    body = helpers.get_body()
    is_citizen = helpers.require_bool(body, "is_citizen")
    is_resident = helpers.require_bool(body, "is_resident")
    felony_conviction = helpers.require_bool(body, "felony_conviction")
    english_proficient = helpers.require_bool(body, "english_proficient")

    juror = db.jurors[s["juror_id"]]
    evaluated = core.evaluate_qualification(
        juror, is_citizen, is_resident, felony_conviction, english_proficient
    )

    q = core.create_qualification_response(
        summons_id, is_citizen, is_resident, felony_conviction, english_proficient, evaluated
    )

    if evaluated == "QUALIFIED":
        if juror["qualification_status"] != "QUALIFIED":
            juror["qualification_status"] = "QUALIFIED"
            core.touch(juror)
            term = db.service_terms.get(juror["service_term_id"])
            if term is not None:
                core.touch(term)  # pool_size recompute (PRD §2.5)
        s["status"] = "QUALIFIED_PENDING"
        core.touch(s)
    else:
        # INELIGIBLE: juror -> INELIGIBLE, summons short-circuits to EXCUSED.
        if juror["qualification_status"] != "INELIGIBLE":
            was_qualified = juror["qualification_status"] == "QUALIFIED"
            juror["qualification_status"] = "INELIGIBLE"
            core.touch(juror)
            if was_qualified:
                term = db.service_terms.get(juror["service_term_id"])
                if term is not None:
                    core.touch(term)  # pool_size shrinks (PRD §2.5)
        s["status"] = "EXCUSED"
        core.touch(s)

    return success(serializers.qualification_response(q), status=201)


# ---------------------------------------------------------------------------
# GET /summonses/{id}/qualification
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/qualification", methods=["GET"])
def list_qualification(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})
    _require_summons(summons_id)

    rows = [q for q in db.qualification_responses.values() if q["summons_id"] == summons_id]
    data, meta = helpers.paginate(rows, serializers.qualification_response)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /summonses/{id}/check-in  (CourtClerk)
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/check-in", methods=["POST"])
def check_in(summons_id):
    _, role = get_identity()
    require_roles(role, {"CourtClerk"})

    s = _require_summons(summons_id)
    term = db.service_terms[s["service_term_id"]]

    # State (priority 21): the first check-in advances QUALIFIED_PENDING ->
    # REPORTING; subsequent days hold in REPORTING. A juror who has been seated
    # (SERVING) keeps accruing service days too — the FINAL voucher re-counts all
    # check-ins through release, so post-seating days must record while SERVING.
    if s["status"] not in ("QUALIFIED_PENDING", "REPORTING", "SERVING"):
        raise errors.err("ERR_INVALID_STATE", "Check-in is only allowed from QUALIFIED_PENDING, REPORTING, or SERVING")

    # Term open (priority 30).
    if term["status"] != "OPEN":
        raise errors.err("ERR_TERM_NOT_OPEN", "Term must be OPEN to check in")

    body = helpers.get_body()
    service_date_raw = helpers.require_string(body, "service_date")
    service_date_dt = helpers.parse_iso8601(service_date_raw, "service_date")
    on_floor_hours = helpers.require_number(body, "on_floor_hours", minimum=0)

    # Temporal (priority 22): service_date >= report_date (closed lower bound,
    # by calendar date).
    report_dt = _term_report_date_dt(term)
    if helpers.calendar_date(service_date_dt) < helpers.calendar_date(report_dt):
        raise errors.err("ERR_BEFORE_REPORT_DATE", "Check-in service_date is before the term report_date")

    # Duplicate service_date (priority 41): no two check-ins share a calendar day.
    new_date = helpers.calendar_date(service_date_dt)
    for c in db.check_ins.values():
        if c["summons_id"] == summons_id:
            existing_dt = helpers.parse_iso8601(c["service_date"], "service_date")
            if helpers.calendar_date(existing_dt) == new_date:
                raise errors.err("ERR_DUPLICATE_SERVICE_DATE", "A check-in already exists on this service_date")

    day_kind = "FULL" if on_floor_hours >= term["full_day_hours"] else "HALF"
    rec = core.create_check_in(summons_id, service_date_raw, on_floor_hours, day_kind)

    if s["status"] == "QUALIFIED_PENDING":
        s["status"] = "REPORTING"
    core.touch(s)  # service_days counter changed (PRD §2.5)

    return success(serializers.check_in(rec), status=201)


# ---------------------------------------------------------------------------
# GET /summonses/{id}/check-ins
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/check-ins", methods=["GET"])
def list_check_ins(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk"})
    _require_summons(summons_id)

    rows = [c for c in db.check_ins.values() if c["summons_id"] == summons_id]
    data, meta = helpers.paginate(rows, serializers.check_in)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /summonses/{id}/release  (CourtClerk)
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/release", methods=["POST"])
def release(summons_id):
    _, role = get_identity()
    require_roles(role, {"CourtClerk"})

    s = _require_summons(summons_id)

    # Release is defined from SERVING and from REPORTING (PRD §3.9); any other
    # state (SUMMONED, QUALIFIED_PENDING, DEFERRED, or a terminal state) is an
    # invalid-state condition. Both valid paths issue the FINAL voucher.
    if s["status"] not in ("SERVING", "REPORTING"):
        raise errors.err("ERR_INVALID_STATE", "Release is only allowed from SERVING or REPORTING")

    s["status"] = "RELEASED"
    core.touch(s)
    core.issue_final_voucher(s)
    return success(serializers.summons(s), status=200)


# ---------------------------------------------------------------------------
# POST /summonses/{id}/mark-fta  (CourtClerk)
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/mark-fta", methods=["POST"])
def mark_fta(summons_id):
    _, role = get_identity()
    require_roles(role, {"CourtClerk"})

    s = _require_summons(summons_id)
    term = db.service_terms[s["service_term_id"]]

    # State (priority 21): only from QUALIFIED_PENDING.
    if s["status"] != "QUALIFIED_PENDING":
        raise errors.err("ERR_INVALID_STATE", "Mark-FTA is only allowed from QUALIFIED_PENDING")

    # Temporal (priority 23): current clock must be at/after report_date.
    report_dt = _term_report_date_dt(term)
    if clock.now() < report_dt:
        raise errors.err("ERR_BEFORE_REPORT_DATE", "Cannot mark FTA before the report date")

    juror = db.jurors[s["juror_id"]]

    s["status"] = "FAILED_TO_APPEAR"
    core.touch(s)
    # Cascade: strike -> recompute fta_strike_count -> maybe disqualify.
    core.create_strike(juror["id"], summons_id)
    core.recompute_juror_disqualification(juror)

    return success(serializers.summons(s), status=200)


# ---------------------------------------------------------------------------
# GET /summonses/{id}/pay-vouchers
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/pay-vouchers", methods=["GET"])
def list_pay_vouchers(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})
    _require_summons(summons_id)

    variant = request.args.get("variant")
    rows = [v for v in db.pay_vouchers.values() if v["summons_id"] == summons_id]
    if variant is not None:
        rows = [v for v in rows if v["variant"] == variant]

    data, meta = helpers.paginate(rows, serializers.pay_voucher)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /summonses/{id}/dispositions  (Juror, own summons)
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/dispositions", methods=["POST"])
def create_disposition(summons_id):
    user_id, role = get_identity()
    require_roles(role, {"Juror"})

    s = _require_summons(summons_id)

    # Ownership (priority 11).
    if s["juror_id"] != user_id:
        raise errors.err("ERR_FORBIDDEN", "Juror does not own this summons")

    body = helpers.get_body()
    kind = helpers.require_enum(body, "kind", {"DEFER", "EXCUSE", "EXEMPT"})
    reason_code = helpers.require_enum(
        body, "reason_code",
        {"MEDICAL", "HARDSHIP", "STUDENT", "AGE", "PRIOR_SERVICE", "MILITARY", "CAREGIVER", "OTHER"},
    )
    requested_term_id = None
    if kind == "DEFER":
        requested_term_id = helpers.require_string(body, "requested_term_id")

    rec = core.create_disposition(summons_id, kind, reason_code, requested_term_id)
    return success(serializers.disposition(rec), status=201)


# ---------------------------------------------------------------------------
# GET /summonses/{id}/dispositions
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/dispositions", methods=["GET"])
def list_summons_dispositions(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Juror"})
    _require_summons(summons_id)

    decision = request.args.get("decision")
    rows = [d for d in db.dispositions.values() if d["summons_id"] == summons_id]
    if decision is not None:
        rows = [d for d in rows if d["decision"] == decision]

    data, meta = helpers.paginate(rows, serializers.disposition)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# GET /summonses/{id}/assignments
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/assignments", methods=["GET"])
def list_summons_assignments(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})
    _require_summons(summons_id)

    status = request.args.get("status")
    rows = [a for a in db.panel_assignments.values() if a["summons_id"] == summons_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]

    data, meta = helpers.paginate(rows, serializers.panel_assignment)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# GET /summonses/{id}/strikes
# ---------------------------------------------------------------------------
@bp.route("/summonses/<summons_id>/strikes", methods=["GET"])
def list_summons_strikes(summons_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk"})
    _require_summons(summons_id)

    rows = [st for st in db.strikes.values() if st["summons_id"] == summons_id]
    data, meta = helpers.paginate(rows, serializers.strike)
    return success(data, status=200, pagination=meta)
