"""Admin routes: clock, partner institutions, internal courses,
articulation agreements, course equivalencies, transfer guides."""
from flask import Blueprint, request

import db
from db import touch
from errors import (ApiError, ERR_AGREEMENT_NOT_EDITABLE,
                    ERR_AGREEMENT_WINDOW_OVERLAP, ERR_AMENDMENT_EXISTS,
                    ERR_COURSE_INACTIVE, ERR_EQUIVALENCY_WINDOW_OVERLAP,
                    ERR_GUIDE_NO_ACTIVE_AGREEMENT, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_STALE_VERSION)
from middleware import ANY, require_roles
from response import get_body, paginate, success_object
from services import (activate_agreement, expire_agreements, reactivate_agreement,
                      ser_agreement, ser_course, ser_equivalency, ser_guide,
                      ser_partner, suspend_agreement)
from util import (CREDIT_SYSTEMS, COURSE_LEVELS, EQUIVALENCY_TYPES, GENED_TAGS,
                  is_half_step, opt_str, parse_dt, req_date, req_enum, req_int,
                  req_number, req_present, req_str, to_decimal)

bp = Blueprint("admin", __name__)

ADMIN = ("RegistrarAdmin",)


def _get_or_404(store, rid, what):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what} not found: {rid}")
    return rec


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles(*ADMIN)
def set_clock():
    body = get_body()
    to_iso = req_date(body, "to_iso8601")
    db.set_clock(parse_dt(to_iso), to_iso)
    # Synchronously evaluate agreement expiry cascades
    expire_agreements()
    return success_object({"current_utc": db.clock_echo()})


# ---------------------------------------------------------------------------
# Partner institutions
# ---------------------------------------------------------------------------

@bp.route("/api/partner-institutions", methods=["POST"])
@require_roles(*ADMIN)
def create_partner():
    body = get_body()
    name = req_str(body, "name")
    code = req_str(body, "institution_code")
    credit_system = req_enum(body, "credit_system", CREDIT_SYSTEMS)
    state_code = opt_str(body, "state_code")
    for p in db.partners.values():
        if p["institution_code"] == code:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "institution_code must be unique")
    rec = db.create_rec(db.partners, {
        "name": name, "institution_code": code,
        "credit_system": credit_system, "state_code": state_code,
    })
    return success_object(ser_partner(rec), 201)


@bp.route("/api/partner-institutions", methods=["GET"])
@require_roles(*ANY)
def list_partners():
    credit_system = request.args.get("credit_system")
    recs = list(db.partners.values())
    if credit_system is not None:
        recs = [p for p in recs if p["credit_system"] == credit_system]
    return paginate(recs, ser_partner)


@bp.route("/api/partner-institutions/<pid>", methods=["GET"])
@require_roles(*ANY)
def get_partner(pid):
    return success_object(ser_partner(_get_or_404(db.partners, pid, "PartnerInstitution")))


# ---------------------------------------------------------------------------
# Internal courses
# ---------------------------------------------------------------------------

@bp.route("/api/internal-courses", methods=["POST"])
@require_roles(*ADMIN)
def create_course():
    body = get_body()
    course_code = req_str(body, "course_code")
    title = req_str(body, "title")
    credit_hours = req_number(body, "credit_hours")
    if credit_hours < to_decimal(0.5) or credit_hours > to_decimal(6.0) \
            or not is_half_step(credit_hours):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "credit_hours must be a multiple of 0.5 within [0.5, 6.0]")
    level = req_enum(body, "level", COURSE_LEVELS)
    department = req_str(body, "department")
    gened_tags = body.get("gened_tags")
    if gened_tags is None:
        gened_tags = []
    if not isinstance(gened_tags, list) or len(gened_tags) > 1 or \
            any(t not in GENED_TAGS for t in gened_tags):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "gened_tags must be a list of zero or one GenEd slot tags")
    for c in db.courses.values():
        if c["course_code"] == course_code:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "course_code must be unique")
    rec = db.create_rec(db.courses, {
        "course_code": course_code, "title": title,
        "credit_hours": credit_hours, "level": level,
        "department": department, "gened_tags": list(gened_tags),
        "is_active": True,
    })
    return success_object(ser_course(rec), 201)


@bp.route("/api/internal-courses", methods=["GET"])
@require_roles(*ANY)
def list_courses():
    is_active_param = request.args.get("is_active")
    if is_active_param is None:
        active_filter = True
    elif is_active_param.lower() == "true":
        active_filter = True
    elif is_active_param.lower() == "false":
        active_filter = False
    else:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "is_active must be 'true' or 'false'")
    department = request.args.get("department")
    recs = [c for c in db.courses.values() if c["is_active"] == active_filter]
    if department is not None:
        recs = [c for c in recs if c["department"] == department]
    return paginate(recs, ser_course)


@bp.route("/api/internal-courses/<cid>", methods=["GET"])
@require_roles(*ANY)
def get_course(cid):
    return success_object(ser_course(_get_or_404(db.courses, cid, "InternalCourse")))


@bp.route("/api/internal-courses/<cid>/deactivate", methods=["POST"])
@require_roles(*ADMIN)
def deactivate_course(cid):
    rec = _get_or_404(db.courses, cid, "InternalCourse")
    if rec["is_active"]:
        rec["is_active"] = False
        touch(rec)
    return success_object(ser_course(rec))


# ---------------------------------------------------------------------------
# Articulation agreements
# ---------------------------------------------------------------------------

def _check_agreement_window_overlap(partner_id, scope, start, end, exclude_id=None):
    """Half-open window overlap against DRAFT/ACTIVE/SUSPENDED siblings."""
    for ag in db.agreements.values():
        if ag["id"] == exclude_id:
            continue
        if ag["partner_institution_id"] != partner_id:
            continue
        if ag["program_scope"] != scope:
            continue
        if ag["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
            continue
        ex_start, ex_end = parse_dt(ag["effective_start"]), parse_dt(ag["effective_end"])
        # Half-open overlap: new.start < existing.end AND new.end > existing.start
        if start < ex_end and end > ex_start:
            raise ApiError(ERR_AGREEMENT_WINDOW_OVERLAP, 409,
                           "Agreement window overlaps an existing agreement")


@bp.route("/api/articulation-agreements", methods=["POST"])
@require_roles(*ADMIN)
def create_agreement():
    body = get_body()
    partner_id = req_str(body, "partner_institution_id")
    scope = req_str(body, "program_scope")
    start_s = req_date(body, "effective_start")
    end_s = req_date(body, "effective_end")
    start, end = parse_dt(start_s), parse_dt(end_s)
    if not start < end:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "effective_end must be strictly after effective_start")
    _get_or_404(db.partners, partner_id, "PartnerInstitution")
    _check_agreement_window_overlap(partner_id, scope, start, end)
    rec = db.create_rec(db.agreements, {
        "partner_institution_id": partner_id, "program_scope": scope,
        "effective_start": start_s, "effective_end": end_s,
        "amends_agreement_id": None, "status": "DRAFT",
        "activated_at": None, "expired_at": None,
    })
    return success_object(ser_agreement(rec), 201)


@bp.route("/api/articulation-agreements", methods=["GET"])
@require_roles(*ANY)
def list_agreements():
    partner_id = request.args.get("partner_institution_id")
    status = request.args.get("status")
    amends = request.args.get("amends_agreement_id")
    recs = list(db.agreements.values())
    if partner_id is not None:
        recs = [a for a in recs if a["partner_institution_id"] == partner_id]
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    if amends is not None:
        recs = [a for a in recs if a.get("amends_agreement_id") == amends]
    return paginate(recs, ser_agreement)


@bp.route("/api/articulation-agreements/<aid>", methods=["GET"])
@require_roles(*ANY)
def get_agreement(aid):
    return success_object(ser_agreement(_get_or_404(db.agreements, aid, "ArticulationAgreement")))


@bp.route("/api/articulation-agreements/<aid>/activate", methods=["POST"])
@require_roles(*ADMIN)
def activate_agreement_route(aid):
    ag = _get_or_404(db.agreements, aid, "ArticulationAgreement")
    if ag["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT agreement can be activated")
    activate_agreement(ag)
    return success_object(ser_agreement(ag))


@bp.route("/api/articulation-agreements/<aid>/suspend", methods=["POST"])
@require_roles(*ADMIN)
def suspend_agreement_route(aid):
    ag = _get_or_404(db.agreements, aid, "ArticulationAgreement")
    if ag["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE agreement can be suspended")
    suspend_agreement(ag)
    return success_object(ser_agreement(ag))


@bp.route("/api/articulation-agreements/<aid>/reactivate", methods=["POST"])
@require_roles(*ADMIN)
def reactivate_agreement_route(aid):
    ag = _get_or_404(db.agreements, aid, "ArticulationAgreement")
    if ag["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUSPENDED agreement can be reactivated")
    if not db.now() < parse_dt(ag["effective_end"]):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "An agreement whose window has ended cannot be reactivated")
    reactivate_agreement(ag)
    return success_object(ser_agreement(ag))


@bp.route("/api/articulation-agreements/<aid>/amendments", methods=["POST"])
@require_roles(*ADMIN)
def create_amendment(aid):
    body = get_body()
    start_s = req_date(body, "effective_start")
    end_s = req_date(body, "effective_end")
    start, end = parse_dt(start_s), parse_dt(end_s)
    if not start < end:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "effective_end must be strictly after effective_start")
    ag = _get_or_404(db.agreements, aid, "ArticulationAgreement")
    # Amendment uniqueness is evaluated before window overlap so that a second
    # DRAFT amendment attempt is always observable as ERR_AMENDMENT_EXISTS.
    for other in db.agreements.values():
        if other.get("amends_agreement_id") == aid and other["status"] == "DRAFT":
            raise ApiError(ERR_AMENDMENT_EXISTS, 409,
                           "A DRAFT amendment already exists for this agreement")
    _check_agreement_window_overlap(ag["partner_institution_id"],
                                    ag["program_scope"], start, end)
    rec = db.create_rec(db.agreements, {
        "partner_institution_id": ag["partner_institution_id"],
        "program_scope": ag["program_scope"],
        "effective_start": start_s, "effective_end": end_s,
        "amends_agreement_id": aid, "status": "DRAFT",
        "activated_at": None, "expired_at": None,
    })
    return success_object(ser_agreement(rec), 201)


# ---------------------------------------------------------------------------
# Course equivalencies
# ---------------------------------------------------------------------------

@bp.route("/api/articulation-agreements/<agreementId>/course-equivalencies",
          methods=["POST"])
@require_roles(*ADMIN)
def create_equivalency(agreementId):
    # Pipeline: body schema (priority 3) before path/body existence (priority 4)
    body = get_body()
    course_id = req_str(body, "internal_course_id")
    ext_code = req_str(body, "external_course_code")
    ext_title = req_str(body, "external_title")
    ext_hours = req_number(body, "external_credit_hours")
    if ext_hours <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "external_credit_hours must be greater than zero")
    from_s = req_date(body, "effective_from")
    until_s = req_date(body, "effective_until")
    w_from, w_until = parse_dt(from_s), parse_dt(until_s)
    if not w_from <= w_until:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "effective_until must be no earlier than effective_from")
    eq_type = body.get("equivalency_type")
    if eq_type is None:
        eq_type = "DIRECT"
    elif eq_type not in EQUIVALENCY_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "equivalency_type must be DIRECT, GENED_ONLY, or ELECTIVE")
    expected_version = req_int(body, "expected_agreement_version")
    # Path identifiers validated left to right, then body FK references
    ag = _get_or_404(db.agreements, agreementId, "ArticulationAgreement")
    course = _get_or_404(db.courses, course_id, "InternalCourse")
    # OCC (priority 5)
    if expected_version != ag["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_agreement_version does not match the agreement version")
    # Agreement editable (priority 12)
    if ag["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_AGREEMENT_NOT_EDITABLE, 409,
                       "Equivalencies may be added only while the agreement is DRAFT or ACTIVE")
    # Closed-window sibling overlap (priority 18); touching endpoints count
    for sib in db.equivalencies.values():
        if sib["agreement_id"] != agreementId:
            continue
        if sib["external_course_code"] != ext_code:
            continue
        s_from, s_until = parse_dt(sib["effective_from"]), parse_dt(sib["effective_until"])
        if w_from <= s_until and w_until >= s_from:
            raise ApiError(ERR_EQUIVALENCY_WINDOW_OVERLAP, 409,
                           "Equivalency window overlaps a sibling equivalency window")
    # Course must be active (priority 24)
    if not course["is_active"]:
        raise ApiError(ERR_COURSE_INACTIVE, 422,
                       "Referenced internal course is archived")
    rec = db.create_rec(db.equivalencies, {
        "agreement_id": agreementId, "internal_course_id": course_id,
        "external_course_code": ext_code, "external_title": ext_title,
        "external_credit_hours": ext_hours,
        "effective_from": from_s, "effective_until": until_s,
        "equivalency_type": eq_type,
        "status": "ACTIVE" if ag["status"] == "ACTIVE" else "INACTIVE",
    })
    # Each creation increments the parent agreement's version
    touch(ag)
    return success_object(ser_equivalency(rec), 201)


@bp.route("/api/articulation-agreements/<agreementId>/course-equivalencies",
          methods=["GET"])
@require_roles(*ANY)
def list_equivalencies_under_agreement(agreementId):
    _get_or_404(db.agreements, agreementId, "ArticulationAgreement")
    recs = [e for e in db.equivalencies.values()
            if e["agreement_id"] == agreementId]
    return paginate(recs, ser_equivalency)


@bp.route("/api/course-equivalencies", methods=["GET"])
@require_roles(*ANY)
def list_equivalencies():
    agreement_id = request.args.get("agreement_id")
    course_id = request.args.get("internal_course_id")
    ext_code = request.args.get("external_course_code")
    status = request.args.get("status")
    recs = list(db.equivalencies.values())
    if agreement_id is not None:
        recs = [e for e in recs if e["agreement_id"] == agreement_id]
    if course_id is not None:
        recs = [e for e in recs if e["internal_course_id"] == course_id]
    if ext_code is not None:
        recs = [e for e in recs if e["external_course_code"] == ext_code]
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    return paginate(recs, ser_equivalency)


@bp.route("/api/course-equivalencies/<eid>", methods=["GET"])
@require_roles(*ANY)
def get_equivalency(eid):
    return success_object(ser_equivalency(_get_or_404(db.equivalencies, eid, "CourseEquivalency")))


# ---------------------------------------------------------------------------
# Transfer guides
# ---------------------------------------------------------------------------

@bp.route("/api/transfer-guides", methods=["POST"])
@require_roles(*ADMIN)
def create_guide():
    body = get_body()
    partner_id = req_str(body, "partner_institution_id")
    catalog_year = req_int(body, "catalog_year")
    _get_or_404(db.partners, partner_id, "PartnerInstitution")
    rec = db.create_rec(db.guides, {
        "partner_institution_id": partner_id, "catalog_year": catalog_year,
        "status": "DRAFT", "pinned_agreement_id": None,
        "pinned_agreement_version": None, "published_at": None,
        "entries_snapshot": None,
    })
    return success_object(ser_guide(rec), 201)


@bp.route("/api/transfer-guides", methods=["GET"])
@require_roles(*ANY)
def list_guides():
    partner_id = request.args.get("partner_institution_id")
    pinned = request.args.get("pinned_agreement_id")
    status = request.args.get("status")
    year = request.args.get("catalog_year")
    recs = list(db.guides.values())
    if partner_id is not None:
        recs = [g for g in recs if g["partner_institution_id"] == partner_id]
    if pinned is not None:
        recs = [g for g in recs if g.get("pinned_agreement_id") == pinned]
    if status is not None:
        recs = [g for g in recs if g["status"] == status]
    if year is not None:
        try:
            year_i = int(year)
            recs = [g for g in recs if g["catalog_year"] == year_i]
        except ValueError:
            recs = []
    return paginate(recs, ser_guide)


@bp.route("/api/transfer-guides/<gid>", methods=["GET"])
@require_roles(*ANY)
def get_guide(gid):
    return success_object(ser_guide(_get_or_404(db.guides, gid, "TransferGuide")))


@bp.route("/api/transfer-guides/<gid>/publish", methods=["POST"])
@require_roles(*ADMIN)
def publish_guide(gid):
    guide = _get_or_404(db.guides, gid, "TransferGuide")
    if guide["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT guide can be published")
    active = [a for a in db.agreements.values()
              if a["partner_institution_id"] == guide["partner_institution_id"]
              and a["status"] == "ACTIVE"]
    if not active:
        raise ApiError(ERR_GUIDE_NO_ACTIVE_AGREEMENT, 409,
                       "No ACTIVE agreement exists for the guide's partner")
    # Pin: latest effective_start wins; tie-break earliest created_at
    active.sort(key=lambda a: (-parse_dt(a["effective_start"]).timestamp(),
                               db.sort_key(a)))
    pinned = active[0]
    snapshot = []
    eqs = [e for e in db.equivalencies.values()
           if e["agreement_id"] == pinned["id"]]
    eqs.sort(key=db.sort_key)
    for e in eqs:
        snapshot.append({
            "external_course_code": e["external_course_code"],
            "external_title": e["external_title"],
            "external_credit_hours": e["external_credit_hours"],
            "internal_course_id": e["internal_course_id"],
            "equivalency_type": e["equivalency_type"],
            "effective_from": e["effective_from"],
            "effective_until": e["effective_until"],
        })
    # Supersede any other PUBLISHED guide for same partner + catalog year
    for other in db.guides.values():
        if other["id"] == guide["id"]:
            continue
        if (other["partner_institution_id"] == guide["partner_institution_id"]
                and other["catalog_year"] == guide["catalog_year"]
                and other["status"] == "PUBLISHED"):
            other["status"] = "ARCHIVED"
            touch(other)
    guide["status"] = "PUBLISHED"
    guide["pinned_agreement_id"] = pinned["id"]
    guide["pinned_agreement_version"] = pinned["version"]
    guide["published_at"] = db.now_iso()
    guide["entries_snapshot"] = snapshot
    touch(guide)
    return success_object(ser_guide(guide))


@bp.route("/api/transfer-guides/<gid>/archive", methods=["POST"])
@require_roles(*ADMIN)
def archive_guide(gid):
    guide = _get_or_404(db.guides, gid, "TransferGuide")
    if guide["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PUBLISHED guide can be archived")
    guide["status"] = "ARCHIVED"
    touch(guide)
    return success_object(ser_guide(guide))


@bp.route("/api/transfer-guides/<gid>/entries", methods=["GET"])
@require_roles(*ANY)
def guide_entries(gid):
    guide = _get_or_404(db.guides, gid, "TransferGuide")
    return success_object({
        "pinned_agreement_id": guide.get("pinned_agreement_id"),
        "pinned_agreement_version": guide.get("pinned_agreement_version"),
        "entries": guide.get("entries_snapshot"),
    })
