"""The CE course catalogue and the CE credit ledger (PRD 3.2)."""
from flask import Blueprint

import serializers
from db import create, db, sort_key, touch
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import created, ok, paginated
from routes.common import filters, get_or_404, get_referenced, listing, matches
from services import audit, authority, calc, ce
from validators import Body, STATE_RE, body_fk, raw_body

bp = Blueprint("ce", __name__)

CE_CATEGORIES = ("FEDERAL_LAW", "ETHICS", "NONTRADITIONAL", "STATE_SPECIFIC", "ELECTIVE")
CREDIT_LICENSE_STATUSES = ("PENDING", "ACTIVE", "RENEWAL_PENDING")


@bp.route("/ce-courses", methods=["POST"])
@endpoint("LicensingAnalyst")
def add_course():
    body = Body(raw_body())
    course_code = body.string("course_code", min_len=4, max_len=24)
    credit_hours = body.integer("credit_hours", minimum=1, maximum=12)
    category = body.enum("category", CE_CATEGORIES)
    # An empty approved_state_codes means the course is accepted in EVERY state.
    approved_state_codes = body.str_array("approved_state_codes", required=False,
                                          default=[], pattern=STATE_RE)
    successive_year_blocked = body.boolean("successive_year_blocked", required=False,
                                           default=True)
    for row in db.ce_courses.values():
        if row["course_code"] == course_code:
            raise ApiError("ERR_DUPLICATE_KEY")
    row = create(db.ce_courses, {
        "course_code": course_code,
        "credit_hours": credit_hours,
        "category": category,
        "approved_state_codes": list(approved_state_codes),
        "successive_year_blocked": successive_year_blocked,
        "provider_status": "APPROVED",
    })
    return created(serializers.ce_course(row))


@bp.route("/ce-courses/<row_id>/rescind", methods=["POST"])
@endpoint("LicensingAnalyst")
def rescind_course(row_id):
    course = get_or_404(db.ce_courses, row_id)
    course["provider_status"] = "RESCINDED"
    touch(course)

    affected = [c for c in db.ce_credits.values()
                if c["ce_course_id"] == course["id"] and c["credit_status"] == "APPLIED"]
    affected.sort(key=sort_key)
    for credit in affected:
        credit["credit_status"] = "VOIDED"
        credit["void_reason"] = "PROVIDER_RESCINDED"
        touch(credit)
    # Only once every voided row has left APPLIED can suppression be re-tested.
    for credit in affected:
        ce.restore_suppressed_by(credit)

    originator_ids = []
    for credit in affected:
        if credit["originator_id"] not in originator_ids:
            originator_ids.append(credit["originator_id"])
    for originator_id in originator_ids:
        ce.recompute_all_licenses(originator_id, calc.MAKEUP_ATTRIBUTION)
    return ok(serializers.ce_course(course))


@bp.route("/ce-credits", methods=["POST"])
@endpoint("LicensingAnalyst")
def file_credit():
    raw = raw_body()
    originator_ref = body_fk(raw, "originator_id")
    originator = None
    if originator_ref is not None:
        originator = get_referenced(db.originators, originator_ref)
    course_ref = body_fk(raw, "ce_course_id")
    course = None
    if course_ref is not None:
        course = get_referenced(db.ce_courses, course_ref)

    body = Body(raw)
    body.string("originator_id")
    body.string("ce_course_id")
    completion_date = body.datetime("completion_date")
    reporting_period_year = body.integer("reporting_period_year", minimum=2020, maximum=2100)
    is_makeup = body.boolean("is_makeup", required=False, default=False)

    # Priority 26 before 27 before 31.
    if course["provider_status"] == "RESCINDED":
        raise ApiError("ERR_COURSE_PROVIDER_RESCINDED")
    approved = course["approved_state_codes"] or []
    if approved:
        held = [lic for lic in authority.licenses_of(originator["id"])
                if lic["status"] in CREDIT_LICENSE_STATUSES
                and lic["state_code"] in approved]
        if not held:
            raise ApiError("ERR_COURSE_NOT_APPROVED_IN_STATE")
    if completion_date > db.clock:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    year = ce.attributed_year(completion_date, reporting_period_year, is_makeup)
    suppressed = ce.suppressed_at_creation(originator["id"], course, year)
    row = create(db.ce_credits, {
        "originator_id": originator["id"],
        "ce_course_id": course["id"],
        "completion_date": completion_date,
        "reporting_period_year": reporting_period_year,
        "is_makeup": is_makeup,
        # Server-computed: any client-supplied value is ignored.
        "credit_hours": course["credit_hours"],
        "category": course["category"],
        "attributed_year": year,
        "credit_status": "EXCLUDED_SUCCESSIVE_YEAR" if suppressed else "APPLIED",
        "void_reason": None,
    })
    ce.recompute_all_licenses(originator["id"], calc.MAKEUP_ATTRIBUTION)
    return created(serializers.ce_credit_record(row))


@bp.route("/ce-credits", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_credits():
    active = filters("originator_id", "ce_course_id", "credit_status", "attributed_year")
    rows = listing(db.ce_credits,
                   lambda r: matches(r, active, int_fields=("attributed_year",)))
    return paginated(rows, serializers.ce_credit_record)


@bp.route("/ce-credits/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_credit(row_id):
    row = get_or_404(db.ce_credits, row_id)
    return ok(serializers.ce_credit_record(row))


@bp.route("/ce-credits/<row_id>/void", methods=["POST"])
@endpoint("LicensingAnalyst")
def void_credit(row_id):
    row = get_or_404(db.ce_credits, row_id)
    row["credit_status"] = "VOIDED"
    row["void_reason"] = "ANALYST_VOID"
    touch(row)
    ce.restore_suppressed_by(row)
    # MAKEUP_ATTRIBUTION restores the CE-hours conserved quantity exactly.
    ce.recompute_all_licenses(row["originator_id"], calc.MAKEUP_ATTRIBUTION)
    audit.append("CeCreditRecord", row["id"], "CE_CREDIT_VOIDED",
                 {"void_reason": "ANALYST_VOID",
                  "originator_id": row["originator_id"],
                  "ce_course_id": row["ce_course_id"],
                  "attributed_year": row["attributed_year"]})
    return ok(serializers.ce_credit_record(row))
