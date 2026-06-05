"""TrademarkApplication core routes and lifecycle transitions
(PRD §3.1-§3.4). Validation order per §3.8: existence -> ownership -> state ->
business checks.
"""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services import models, calc
from services.body import (
    get_json_body,
    require_nonempty_string,
    require_enum,
    optional_string,
    optional_bool,
)
from services.pagination import parse_pagination, slice_sorted
from services.ownership import check_application_owner
from services.dateutil import add_days, add_years

bp = Blueprint("applications", __name__)

FILING_BASES = {"USE", "INTENT"}
FILING_TIERS = {"TEAS_PLUS", "TEAS_STANDARD"}


# ----- Create / read / list -------------------------------------------------

@bp.post("/applications")
@require_roles("Attorney", "Applicant")
def create_application(_user_id, _role):
    body = get_json_body()
    applicant_id = require_nonempty_string(body, "applicant_id")
    attorney_id = optional_string(body, "attorney_id")
    mark_text = require_nonempty_string(body, "mark_text", max_len=200)
    filing_basis = require_enum(body, "filing_basis", FILING_BASES)
    filing_tier = require_enum(body, "filing_tier", FILING_TIERS)

    # Existence of body FKs (left-to-right declared order).
    models.get_or_404(db.applicants, applicant_id, "Applicant")
    if attorney_id is not None:
        models.get_or_404(db.attorneys, attorney_id, "Attorney")

    rec = models.make_record({
        "applicant_id": applicant_id,
        "attorney_id": attorney_id,
        "mark_text": mark_text,
        "filing_basis": filing_basis,
        "filing_tier": filing_tier,
        "status": "DRAFT",
        "filing_fee_cents": 0,
        "office_action_round": 0,
        "filed_at": None,
        "published_at": None,
        "notice_of_allowance_at": None,
    })
    db.applications[rec["id"]] = rec
    return success(models.ser_application(rec), 201)


@bp.get("/applications/<rid>")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def get_application(rid, _user_id, _role):
    rec = models.get_or_404(db.applications, rid, "TrademarkApplication")
    return success(models.ser_application(rec), 200)


@bp.get("/applications")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def list_applications(_user_id, _role):
    limit, offset = parse_pagination()
    applicant_id = request.args.get("applicant_id")
    attorney_id = request.args.get("attorney_id")
    status = request.args.get("status")

    items = list(db.applications.values())
    if applicant_id is not None:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if attorney_id is not None:
        items = [a for a in items if a.get("attorney_id") == attorney_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]

    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_application(a) for a in page], limit, offset, total
    )


# ----- Goods/services -------------------------------------------------------

@bp.post("/applications/<rid>/goods-services")
@require_roles("Attorney", "Applicant")
def add_goods_services(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    check_application_owner(app, _role, _user_id)

    body = get_json_body()
    nice_class_id = require_nonempty_string(body, "nice_class_id")
    description = require_nonempty_string(body, "description", max_len=500)
    pre_approved = optional_bool(body, "pre_approved", False)

    models.get_or_404(db.nice_classes, nice_class_id, "NiceClass")

    rec = models.make_record({
        "application_id": rid,
        "nice_class_id": nice_class_id,
        "description": description,
        "pre_approved": pre_approved,
        "use_status": "NOT_IN_USE",
    })
    db.goods_services[rec["id"]] = rec
    # class_count is recomputed at serialization time (distinct nice_class_id).
    return success(models.ser_goods_services(rec), 201)


@bp.get("/applications/<rid>/goods-services")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def list_goods_services(rid, _user_id, _role):
    models.get_or_404(db.applications, rid, "TrademarkApplication")
    limit, offset = parse_pagination()
    items = [g for g in db.goods_services.values() if g["application_id"] == rid]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_goods_services(g) for g in page], limit, offset, total
    )


# ----- File (DRAFT -> FILED) ------------------------------------------------

@bp.post("/applications/<rid>/file")
@require_roles("Attorney", "Applicant")
def file_application(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    check_application_owner(app, _role, _user_id)

    # State: must be DRAFT.
    if app["status"] != "DRAFT":
        raise_api("ERR_INVALID_STATE", "Application is not in DRAFT")

    # Business checks in PRD-pinned order.
    applicant = db.applicants[app["applicant_id"]]
    items = [g for g in db.goods_services.values() if g["application_id"] == rid]

    # 1) attorney-standing.
    if app.get("attorney_id") is not None:
        attorney = db.attorneys.get(app["attorney_id"])
        if attorney is None or attorney["status"] != "ACTIVE":
            raise_api("ERR_ATTORNEY_NOT_ACTIVE", "Attorney of record is not ACTIVE")

    # 2) foreign-representation.
    if applicant["country_code"] != "US" and app.get("attorney_id") is None:
        raise_api(
            "ERR_FOREIGN_REQUIRES_ATTORNEY",
            "Foreign-domiciled applicant must name an attorney to file",
        )

    # 3) tier-compliance (TEAS_PLUS requires every item pre_approved).
    if app["filing_tier"] == "TEAS_PLUS":
        if any(not g["pre_approved"] for g in items):
            raise_api(
                "ERR_TEAS_PLUS_REQUIRES_PREAPPROVED",
                "TEAS_PLUS requires every goods/services item to be pre-approved",
            )

    # 4) minimum-goods (class_count >= 1).
    class_count = len({g["nice_class_id"] for g in items})
    if class_count < 1:
        raise_api("ERR_NO_GOODS_SERVICES", "Application has no goods/services items")

    # Side effects.
    app["filed_at"] = db.current_utc_iso()
    app["filing_fee_cents"] = calc.application_filing_fee(
        app["filing_tier"], app["filing_basis"], class_count
    )
    app["status"] = "FILED"
    models.touch(app)
    return success(models.ser_application(app), 200)


# ----- Assign examination (FILED -> UNDER_EXAMINATION) ----------------------

@bp.post("/applications/<rid>/assign-examination")
@require_roles("Examiner")
def assign_examination(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    if app["status"] != "FILED":
        raise_api("ERR_INVALID_STATE", "Application is not in FILED")
    app["status"] = "UNDER_EXAMINATION"
    models.touch(app)
    return success(models.ser_application(app), 200)


# ----- Approve publication (UNDER_EXAMINATION -> PUBLISHED) ------------------

@bp.post("/applications/<rid>/approve-publication")
@require_roles("Examiner")
def approve_publication(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    if app["status"] != "UNDER_EXAMINATION":
        raise_api("ERR_INVALID_STATE", "Application is not UNDER_EXAMINATION")
    # No OfficeAction on this application may still be OUTSTANDING.
    if any(
        oa["application_id"] == rid and oa["status"] == "OUTSTANDING"
        for oa in db.office_actions.values()
    ):
        raise_api("ERR_INVALID_STATE", "An office action is still outstanding")

    now = db.current_utc_dt()
    app["published_at"] = db.current_utc_iso()
    app["status"] = "PUBLISHED"
    due = add_days(now, calc.OPPOSITION_WINDOW_DAYS)
    from db import iso_from_datetime
    models.create_docket_deadline(
        "OPPOSITION_WINDOW", rid, iso_from_datetime(due), application_id=rid
    )
    models.touch(app)
    return success(models.ser_application(app), 200)


# ----- Issue allowance (PUBLISHED -> ALLOWED, INTENT only) ------------------

@bp.post("/applications/<rid>/issue-allowance")
@require_roles("Examiner")
def issue_allowance(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    if app["status"] != "PUBLISHED":
        raise_api("ERR_INVALID_STATE", "Application is not PUBLISHED")
    if app["filing_basis"] != "INTENT":
        raise_api("ERR_INVALID_STATE", "Allowance is only for INTENT-basis applications")
    if _live_proceeding_targets(rid):
        raise_api("ERR_INVALID_STATE", "A board proceeding targeting this mark is live")

    now = db.current_utc_dt()
    app["notice_of_allowance_at"] = db.current_utc_iso()
    app["status"] = "ALLOWED"
    from db import iso_from_datetime
    due = add_days(now, calc.SOU_INITIAL_DAYS)
    models.create_docket_deadline(
        "SOU", rid, iso_from_datetime(due), application_id=rid
    )
    models.touch(app)
    return success(models.ser_application(app), 200)


# ----- Register (PUBLISHED -> REGISTERED, USE only) -------------------------

@bp.post("/applications/<rid>/register")
@require_roles("Examiner")
def register_application(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    if app["status"] != "PUBLISHED":
        raise_api("ERR_INVALID_STATE", "Application is not PUBLISHED")
    if app["filing_basis"] != "USE":
        raise_api("ERR_INVALID_STATE", "Direct registration is only for USE-basis applications")
    if _live_proceeding_targets(rid):
        raise_api("ERR_INVALID_STATE", "A board proceeding targeting this mark is live")

    reg = _mint_registration(app)
    # Cancel any still-PENDING OPPOSITION_WINDOW deadline for this application.
    models.set_docket_status("OPPOSITION_WINDOW", rid, "CANCELLED", only_pending=True)
    app["status"] = "REGISTERED"
    models.touch(app)
    return success(models.ser_registration(reg), 201)


# ----- Abandon SOU lapsed (ALLOWED -> ABANDONED, system) --------------------

@bp.post("/applications/<rid>/abandon-sou-lapsed")
@require_roles("Examiner")
def abandon_sou_lapsed(rid, _user_id, _role):
    app = models.get_or_404(db.applications, rid, "TrademarkApplication")
    if app["status"] != "ALLOWED":
        raise_api("ERR_INVALID_STATE", "Application is not ALLOWED")

    from db import parse_iso
    now = db.current_utc_dt()
    deadline = add_days(parse_iso(app["notice_of_allowance_at"]), calc.SOU_MAX_DAYS)
    if now < deadline:
        raise_api("ERR_INVALID_STATE", "SOU outer limit has not yet elapsed")
    # No StatementOfUse for this application has reached ACCEPTED.
    if any(
        s["application_id"] == rid and s["status"] == "ACCEPTED"
        for s in db.statements_of_use.values()
    ):
        raise_api("ERR_INVALID_STATE", "An accepted statement of use exists")

    models.set_docket_status("SOU", rid, "MISSED", only_pending=True)
    app["status"] = "ABANDONED"
    models.touch(app)
    return success(models.ser_application(app), 200)


# ----- Roll-up reverse-reachability lists -----------------------------------

@bp.get("/applications/<rid>/docket-deadlines")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def list_docket_deadlines(rid, _user_id, _role):
    models.get_or_404(db.applications, rid, "TrademarkApplication")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [
        d for d in db.docket_deadlines.values() if d.get("application_id") == rid
    ]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_docket_deadline(d) for d in page], limit, offset, total
    )


@bp.get("/applications/<rid>/office-actions")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def list_application_office_actions(rid, _user_id, _role):
    models.get_or_404(db.applications, rid, "TrademarkApplication")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [
        oa for oa in db.office_actions.values() if oa["application_id"] == rid
    ]
    if status is not None:
        items = [oa for oa in items if oa["status"] == status]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_office_action(oa) for oa in page], limit, offset, total
    )


@bp.get("/applications/<rid>/statements-of-use")
@require_roles("Attorney", "Applicant", "Examiner")
def list_application_sou(rid, _user_id, _role):
    models.get_or_404(db.applications, rid, "TrademarkApplication")
    limit, offset = parse_pagination()
    items = [
        s for s in db.statements_of_use.values() if s["application_id"] == rid
    ]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_statement_of_use(s) for s in page], limit, offset, total
    )


@bp.get("/applications/<rid>/registration")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def find_application_registration(rid, _user_id, _role):
    models.get_or_404(db.applications, rid, "TrademarkApplication")
    limit, offset = parse_pagination()
    items = [
        r for r in db.registrations.values() if r["application_id"] == rid
    ]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_registration(r) for r in page], limit, offset, total
    )


@bp.get("/applications/<rid>/madrid-applications")
@require_roles("Attorney", "Applicant", "Examiner")
def list_application_madrid(rid, _user_id, _role):
    models.get_or_404(db.applications, rid, "TrademarkApplication")
    limit, offset = parse_pagination()
    items = [
        m for m in db.madrid_applications.values() if m["basic_application_id"] == rid
    ]
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_madrid(m) for m in page], limit, offset, total
    )


# ----- Shared helpers (used by this module and SOU acceptance) --------------

def _live_proceeding_targets(application_id: str) -> bool:
    """True iff a TTABProceeding targets this application with a live claim."""
    return any(
        p.get("target_application_id") == application_id
        and p["claim_status"] in ("PLEADED", "TRIAL")
        for p in db.ttab_proceedings.values()
    )


def _mint_registration(app: dict) -> dict:
    """Create a Registration (ACTIVE, cycle 0) and its first MAINTENANCE deadline."""
    from db import iso_from_datetime
    now = db.current_utc_dt()
    registered_iso = db.current_utc_iso()
    due = calc.maintenance_due_at(now, 0)
    reg = models.make_record({
        "application_id": app["id"],
        "registration_number": db.mint_registration_number(),
        "registered_at": registered_iso,
        "status": "ACTIVE",
        "maintenance_cycle": 0,
        "next_maintenance_due_at": iso_from_datetime(due),
    })
    db.registrations[reg["id"]] = reg
    models.create_docket_deadline(
        "MAINTENANCE", reg["id"], iso_from_datetime(due), application_id=None
    )
    return reg
