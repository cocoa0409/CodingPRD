"""License application lifecycle: create, list, submit, begin-review,
open-protest-period, approve, issue, deny, withdraw, pay-fee, and the
reverse-reachable child collections (background-checks, zoning-reviews,
protests, hearings)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from auth import require_auth, ALL_READERS
from clock import clock, add_months
from db import db, new_id, common_fields, touch
from helpers import (
    body, paginate, sort_created, out, out_list, get_or_404,
    find_license_class_by_code,
)
import validate
from calculations import fee_quoted
from quota import quota_status, region_code_for_application
from response import ok, created, listed

bp = Blueprint("applications", __name__)


# --- Create / read -----------------------------------------------------------
@bp.route("/license-applications", methods=["POST"])
def create_application():
    require_auth(["Director", "LicensingExaminer", "Applicant"])
    data = body()
    applicant_id = validate.require_str(data, "applicant_id")
    premise_id = validate.require_str(data, "premise_id")
    license_class_code = validate.require_str(data, "license_class_code")
    if applicant_id not in db.applicants:
        raise errors.err(errors.ERR_NOT_FOUND, "Applicant not found")
    if premise_id not in db.premises:
        raise errors.err(errors.ERR_NOT_FOUND, "Premise not found")
    if find_license_class_by_code(license_class_code) is None:
        raise errors.err(errors.ERR_NOT_FOUND, "License class not found")

    ent = {
        "id": new_id(), "applicant_id": applicant_id, "premise_id": premise_id,
        "license_class_code": license_class_code, "status": "DRAFT",
        "submitted_at": None, "protest_period_ends_at": None,
        "fee_quoted_cents": None, "fee_paid_cents": 0, "quota_slot_held": False,
        "background_check_id": None, "zoning_review_id": None,
        "examiner_user_id": None,
    }
    ent.update(common_fields())
    db.license_applications[ent["id"]] = ent
    return created(out(ent))


@bp.route("/license-applications/<id>", methods=["GET"])
def get_application(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.license_applications, id)
    return ok(out(ent))


@bp.route("/license-applications", methods=["GET"])
def list_applications():
    require_auth(ALL_READERS)
    items = list(db.license_applications.values())
    for key in ("applicant_id", "premise_id", "license_class_code", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --- Submit ------------------------------------------------------------------
@bp.route("/license-applications/<id>/submit", methods=["POST"])
def submit_application(id):
    require_auth(["Applicant"])
    app = get_or_404(db.license_applications, id)
    if app["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not in DRAFT")

    applicant = db.applicants[app["applicant_id"]]
    lc = find_license_class_by_code(app["license_class_code"])
    premise = db.premises[app["premise_id"]]
    region = _region_for_code(premise["region_code"])

    data = body()

    # priority 6: disqualified applicant may not submit
    if applicant["disqualified"]:
        raise errors.err(errors.ERR_APPLICANT_DISQUALIFIED, "Applicant disqualified")

    quota_managed = lc["quota_managed"]
    if quota_managed:
        # priority 19: moratorium / quota exhaustion
        if region["moratorium"]:
            raise errors.err(errors.ERR_QUOTA_EXHAUSTED, "Region under moratorium")
        cap, used, available = quota_status(premise["region_code"], lc["code"], lc)
        if available <= 0:
            raise errors.err(errors.ERR_QUOTA_EXHAUSTED, "No quota slots available")
        # priority 23: OCC against region version (required for quota_managed)
        if "expected_region_version" not in data or data["expected_region_version"] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing expected_region_version")
        expected = data["expected_region_version"]
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise errors.err(errors.ERR_INVALID_REQUEST, "expected_region_version must be an integer")
        if expected != region["version"]:
            raise errors.err(errors.ERR_STALE_REGION_VERSION, "Stale region version")

    now = clock.now()
    app["status"] = "SUBMITTED"
    app["submitted_at"] = now
    app["protest_period_ends_at"] = now + timedelta(days=30)
    app["fee_quoted_cents"] = fee_quoted(lc)

    # Synthesize background check (PENDING)
    bc = {
        "id": new_id(), "application_id": app["id"], "applicant_id": app["applicant_id"],
        "result": "PENDING", "resolved_at": None, "status": "PENDING",
    }
    bc.update(common_fields())
    db.background_checks[bc["id"]] = bc
    app["background_check_id"] = bc["id"]

    # Synthesize zoning review when the class requires zoning
    if lc["requires_zoning"]:
        required = 0 if lc["premise_type"] == "MANUFACTURER" else 100
        buffer_satisfied = premise["distance_to_school_m"] >= required
        zr = {
            "id": new_id(), "application_id": app["id"], "premise_id": app["premise_id"],
            "result": "PENDING", "buffer_satisfied": buffer_satisfied,
            "resolved_at": None, "status": "PENDING",
        }
        zr.update(common_fields())
        db.zoning_reviews[zr["id"]] = zr
        app["zoning_review_id"] = zr["id"]

    if quota_managed:
        app["quota_slot_held"] = True
        touch(region)  # advance region version on slot reservation

    touch(app)
    return ok(out(app))


# --- Begin review ------------------------------------------------------------
@bp.route("/license-applications/<id>/begin-review", methods=["POST"])
def begin_review(id):
    caller = require_auth(["LicensingExaminer"])
    app = get_or_404(db.license_applications, id)
    if app["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not SUBMITTED")
    # priority 7 (zoning) precedes priority 8 (background) per validation table.
    if app["zoning_review_id"] is not None:
        zr = db.zoning_reviews[app["zoning_review_id"]]
        if zr["result"] not in ("CLEARED", "VARIANCE_GRANTED"):
            raise errors.err(errors.ERR_ZONING_NOT_CLEARED, "Zoning not cleared")
    bc = db.background_checks.get(app["background_check_id"])
    if bc is None or bc["result"] != "PASSED":
        raise errors.err(errors.ERR_BACKGROUND_NOT_PASSED, "Background not passed")

    app["status"] = "UNDER_REVIEW"
    app["examiner_user_id"] = caller.user_id
    touch(app)
    return ok(out(app))


# --- Open protest period -----------------------------------------------------
@bp.route("/license-applications/<id>/open-protest-period", methods=["POST"])
def open_protest_period(id):
    require_auth(["LicensingExaminer"])
    app = get_or_404(db.license_applications, id)
    if app["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not UNDER_REVIEW")
    app["status"] = "PROTEST_PERIOD"
    touch(app)
    return ok(out(app))


# --- Approve -----------------------------------------------------------------
@bp.route("/license-applications/<id>/approve", methods=["POST"])
def approve_application(id):
    caller = require_auth(["Director"])
    app = get_or_404(db.license_applications, id)
    if app["status"] != "PROTEST_PERIOD":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not in PROTEST_PERIOD")
    # priority 5: segregation of duties (issuer != examiner)
    if caller.user_id == app["examiner_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Issuer must differ from examiner")
    # priority 10: window must have elapsed
    if clock.now() < app["protest_period_ends_at"]:
        raise errors.err(errors.ERR_PROTEST_WINDOW_OPEN, "Protest window still open")
    # priority 11: no unresolved/sustained protest
    for p in db.protests.values():
        if p["application_id"] == app["id"] and p["status"] in ("FILED", "SCHEDULED", "SUSTAINED"):
            raise errors.err(errors.ERR_PROTEST_UNRESOLVED, "Protest unresolved")

    app["status"] = "APPROVED"
    touch(app)
    return ok(out(app))


# --- Issue -------------------------------------------------------------------
@bp.route("/license-applications/<id>/issue", methods=["POST"])
def issue_application(id):
    caller = require_auth(["Director"])
    app = get_or_404(db.license_applications, id)
    if app["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not APPROVED")
    # priority 5: segregation of duties
    if caller.user_id == app["examiner_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Issuer must differ from examiner")
    # priority 18: fee fully paid
    if app["fee_paid_cents"] < app["fee_quoted_cents"]:
        raise errors.err(errors.ERR_FEE_UNPAID, "Fee not fully paid")

    lc = find_license_class_by_code(app["license_class_code"])
    premise = db.premises[app["premise_id"]]
    now = clock.now()
    term_end = add_months(now, lc["renewal_cycle_months"])
    lic = {
        "id": new_id(), "application_id": app["id"],
        "license_class_code": app["license_class_code"],
        "region_code": premise["region_code"], "status": "ACTIVE",
        "term_start_at": now, "term_end_at": term_end,
        "renewal_window_opens_at": term_end - timedelta(days=60),
        "renewal_count": 0, "demerit_points": 0, "active_server_count": 0,
        "outstanding_fine_cents": 0,
        # denormalized current owner/premise for transfer relocation logic
        "applicant_id": app["applicant_id"], "premise_id": app["premise_id"],
    }
    lic.update(common_fields())
    db.licenses[lic["id"]] = lic

    app["status"] = "ISSUED"
    # quota_slot_held stays true (committed)
    touch(app)
    return ok(out(app))


# --- Deny --------------------------------------------------------------------
@bp.route("/license-applications/<id>/deny", methods=["POST"])
def deny_application(id):
    caller = require_auth(["Director"])
    app = get_or_404(db.license_applications, id)
    if app["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not UNDER_REVIEW")
    if caller.user_id == app["examiner_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Denier must differ from examiner")
    app["status"] = "DENIED"
    _release_slot(app)
    touch(app)
    return ok(out(app))


# --- Withdraw ----------------------------------------------------------------
@bp.route("/license-applications/<id>/withdraw", methods=["POST"])
def withdraw_application(id):
    require_auth(["Applicant"])
    app = get_or_404(db.license_applications, id)
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Application not in DRAFT or SUBMITTED")
    app["status"] = "WITHDRAWN"
    _release_slot(app)
    touch(app)
    return ok(out(app))


# --- Pay fee -----------------------------------------------------------------
@bp.route("/license-applications/<id>/pay-fee", methods=["POST"])
def pay_fee(id):
    require_auth(["Applicant"])
    app = get_or_404(db.license_applications, id)
    data = body()
    amount = validate.require_int(data, "amount_cents", minimum=0)
    app["fee_paid_cents"] = app["fee_paid_cents"] + amount
    touch(app)
    return ok(out(app))


# --- Reverse-reachable children ---------------------------------------------
@bp.route("/license-applications/<id>/background-checks", methods=["GET"])
def list_app_background_checks(id):
    require_auth(ALL_READERS)
    get_or_404(db.license_applications, id)
    items = [b for b in db.background_checks.values() if b["application_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/license-applications/<id>/zoning-reviews", methods=["GET"])
def list_app_zoning_reviews(id):
    require_auth(ALL_READERS)
    get_or_404(db.license_applications, id)
    items = [z for z in db.zoning_reviews.values() if z["application_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/license-applications/<id>/protests", methods=["GET"])
def list_app_protests(id):
    require_auth(ALL_READERS)
    get_or_404(db.license_applications, id)
    items = [p for p in db.protests.values() if p["application_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/license-applications/<id>/hearings", methods=["GET"])
def list_app_hearings(id):
    require_auth(ALL_READERS)
    get_or_404(db.license_applications, id)
    items = [h for h in db.hearings.values() if h["application_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --- internal helpers --------------------------------------------------------
def _region_for_code(region_code):
    for r in db.quota_regions.values():
        if r["region_code"] == region_code:
            return r
    return None


def _release_slot(app):
    if app.get("quota_slot_held"):
        app["quota_slot_held"] = False
