"""TTABProceeding routes (PRD §3.6). Parallel claim_status / defense_status
dimensions, default/decide cascades, and the Madrid central-attack cascade.
"""

from flask import Blueprint, request

from db import db, parse_iso, iso_from_datetime
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services import models, calc
from services.body import get_json_body, require_nonempty_string, require_enum, optional_string
from services.pagination import parse_pagination, slice_sorted
from services.ownership import check_proceeding_owner
from services.dateutil import add_days

bp = Blueprint("ttab", __name__)

PROCEEDING_TYPES = {"OPPOSITION", "CANCELLATION"}
DECISIONS = {"SUSTAIN", "DISMISS"}


# ----- Institute ------------------------------------------------------------

@bp.post("/ttab-proceedings")
@require_roles("Attorney", "Applicant")
def institute_proceeding(_user_id, _role):
    body = get_json_body()
    proceeding_type = require_enum(body, "proceeding_type", PROCEEDING_TYPES)
    target_application_id = optional_string(body, "target_application_id")
    target_registration_id = optional_string(body, "target_registration_id")
    petitioner_applicant_id = require_nonempty_string(body, "petitioner_applicant_id")

    # Existence of body FKs (declared order): petitioner, then targets if present.
    models.get_or_404(db.applicants, petitioner_applicant_id, "Applicant")
    target_app = None
    target_reg = None
    if target_application_id is not None:
        target_app = models.get_or_404(
            db.applications, target_application_id, "TrademarkApplication"
        )
    if target_registration_id is not None:
        target_reg = models.get_or_404(
            db.registrations, target_registration_id, "Registration"
        )

    # Ownership (priority 4): Applicant acting role must be the petitioner.
    if _role == "Applicant" and petitioner_applicant_id != _user_id:
        raise_api(
            "ERR_NOT_RESOURCE_OWNER",
            "Applicant is not the petitioner of this proceeding",
        )

    # Business constraint (priority 12): target kind + challengeable state.
    if proceeding_type == "OPPOSITION":
        if target_app is None or target_app["status"] != "PUBLISHED":
            raise_api(
                "ERR_PROCEEDING_TARGET_INVALID",
                "OPPOSITION requires a PUBLISHED target application",
            )
        # Business temporal (priority 13): within the opposition window.
        now = db.current_utc_dt()
        window_close = add_days(
            parse_iso(target_app["published_at"]), calc.OPPOSITION_WINDOW_DAYS
        )
        if now > window_close:
            raise_api("ERR_OPPOSITION_WINDOW_CLOSED", "Opposition window has closed")
    else:  # CANCELLATION
        if target_reg is None or target_reg["status"] not in ("ACTIVE", "GRACE"):
            raise_api(
                "ERR_PROCEEDING_TARGET_INVALID",
                "CANCELLATION requires an ACTIVE/GRACE target registration",
            )

    now = db.current_utc_dt()
    filed_iso = db.current_utc_iso()
    answer_deadline = add_days(now, calc.ANSWER_PERIOD_DAYS)
    rec = models.make_record({
        "proceeding_type": proceeding_type,
        "target_application_id": target_application_id,
        "target_registration_id": target_registration_id,
        "petitioner_applicant_id": petitioner_applicant_id,
        "claim_status": "PLEADED",
        "defense_status": "AWAITING_ANSWER",
        "filed_at": filed_iso,
        "answer_deadline": iso_from_datetime(answer_deadline),
    })
    db.ttab_proceedings[rec["id"]] = rec

    # The OPPOSITION_ANSWER deadline rolls up to the opposed application (if any).
    models.create_docket_deadline(
        "OPPOSITION_ANSWER", rec["id"], iso_from_datetime(answer_deadline),
        application_id=target_application_id,
    )
    return success(models.ser_ttab(rec), 201)


@bp.get("/ttab-proceedings/<rid>")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def get_proceeding(rid, _user_id, _role):
    rec = models.get_or_404(db.ttab_proceedings, rid, "TTABProceeding")
    return success(models.ser_ttab(rec), 200)


@bp.get("/ttab-proceedings")
@require_roles("Attorney", "Applicant", "Examiner", "TTABClerk")
def list_proceedings(_user_id, _role):
    limit, offset = parse_pagination()
    target_application_id = request.args.get("target_application_id")
    target_registration_id = request.args.get("target_registration_id")
    petitioner_applicant_id = request.args.get("petitioner_applicant_id")

    items = list(db.ttab_proceedings.values())
    if target_application_id is not None:
        items = [p for p in items if p.get("target_application_id") == target_application_id]
    if target_registration_id is not None:
        items = [p for p in items if p.get("target_registration_id") == target_registration_id]
    if petitioner_applicant_id is not None:
        items = [p for p in items if p["petitioner_applicant_id"] == petitioner_applicant_id]

    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [models.ser_ttab(p) for p in page], limit, offset, total
    )


# ----- Answer (AWAITING_ANSWER -> ANSWERED) ---------------------------------

@bp.post("/ttab-proceedings/<rid>/answer")
@require_roles("Attorney", "Applicant")
def answer_proceeding(rid, _user_id, _role):
    p = models.get_or_404(db.ttab_proceedings, rid, "TTABProceeding")

    # Already-closed guard (priority 6): defense must still be AWAITING_ANSWER.
    if p["defense_status"] != "AWAITING_ANSWER":
        raise_api("ERR_ACTION_ALREADY_CLOSED", "Proceeding is no longer awaiting answer")

    # State (priority 5): claim must be live (PLEADED or TRIAL) and timely.
    if p["claim_status"] not in ("PLEADED", "TRIAL"):
        raise_api("ERR_INVALID_STATE", "Proceeding claim is not live")
    now = db.current_utc_dt()
    if now > parse_iso(p["answer_deadline"]):
        raise_api("ERR_INVALID_STATE", "Answer deadline has passed")

    p["defense_status"] = "ANSWERED"
    models.set_docket_status("OPPOSITION_ANSWER", rid, "MET", only_pending=True)
    models.touch(p)
    return success(models.ser_ttab(p), 200)


# ----- Enter default (AWAITING_ANSWER -> DEFAULTED, claim SUSTAINED) ---------

@bp.post("/ttab-proceedings/<rid>/enter-default")
@require_roles("TTABClerk")
def enter_default(rid, _user_id, _role):
    p = models.get_or_404(db.ttab_proceedings, rid, "TTABProceeding")

    if p["defense_status"] != "AWAITING_ANSWER":
        raise_api("ERR_INVALID_STATE", "Proceeding is not awaiting answer")
    now = db.current_utc_dt()
    if now <= parse_iso(p["answer_deadline"]):
        raise_api("ERR_INVALID_STATE", "Answer deadline has not yet passed")

    p["defense_status"] = "DEFAULTED"
    models.set_docket_status("OPPOSITION_ANSWER", rid, "MISSED", only_pending=True)
    p["claim_status"] = "SUSTAINED"
    _cascade_sustained(p)
    models.touch(p)
    return success(models.ser_ttab(p), 200)


# ----- Set for trial (PLEADED -> TRIAL) -------------------------------------

@bp.post("/ttab-proceedings/<rid>/set-for-trial")
@require_roles("TTABClerk")
def set_for_trial(rid, _user_id, _role):
    p = models.get_or_404(db.ttab_proceedings, rid, "TTABProceeding")
    if p["claim_status"] != "PLEADED":
        raise_api("ERR_INVALID_STATE", "Claim is not PLEADED")
    if p["defense_status"] != "ANSWERED":
        raise_api("ERR_INVALID_STATE", "Defense has not been answered")
    p["claim_status"] = "TRIAL"
    models.touch(p)
    return success(models.ser_ttab(p), 200)


# ----- Decide (TRIAL -> SUSTAINED | DISMISSED) ------------------------------

@bp.post("/ttab-proceedings/<rid>/decide")
@require_roles("TTABClerk")
def decide_proceeding(rid, _user_id, _role):
    p = models.get_or_404(db.ttab_proceedings, rid, "TTABProceeding")
    body = get_json_body()
    decision = require_enum(body, "decision", DECISIONS)

    if p["claim_status"] != "TRIAL":
        raise_api("ERR_INVALID_STATE", "Claim is not in TRIAL")

    if decision == "SUSTAIN":
        p["claim_status"] = "SUSTAINED"
        _cascade_sustained(p)
    else:  # DISMISS
        p["claim_status"] = "DISMISSED"
    models.touch(p)
    return success(models.ser_ttab(p), 200)


# ----- Withdraw (PLEADED -> WITHDRAWN) --------------------------------------

@bp.post("/ttab-proceedings/<rid>/withdraw")
@require_roles("Attorney", "Applicant")
def withdraw_proceeding(rid, _user_id, _role):
    p = models.get_or_404(db.ttab_proceedings, rid, "TTABProceeding")
    check_proceeding_owner(p, _role, _user_id)
    if p["claim_status"] != "PLEADED":
        raise_api("ERR_INVALID_STATE", "Claim is not PLEADED")
    p["claim_status"] = "WITHDRAWN"
    models.set_docket_status("OPPOSITION_ANSWER", rid, "CANCELLED", only_pending=True)
    models.touch(p)
    return success(models.ser_ttab(p), 200)


# ----- Cascade --------------------------------------------------------------

def _cascade_sustained(p: dict):
    """Apply the attacked-mark cascade for a SUSTAINED claim (default or
    SUSTAIN decision). For a cancellation, additionally run the Madrid
    central-attack cascade."""
    if p["proceeding_type"] == "OPPOSITION":
        target_app = db.applications.get(p.get("target_application_id"))
        if target_app is not None and target_app["status"] != "ABANDONED":
            target_app["status"] = "ABANDONED"
            models.touch(target_app)
    else:  # CANCELLATION
        target_reg = db.registrations.get(p.get("target_registration_id"))
        if target_reg is not None and target_reg["status"] != "CANCELLED":
            target_reg["status"] = "CANCELLED"
            target_reg["next_maintenance_due_at"] = None
            models.touch(target_reg)
            _central_attack_madrid(target_reg)


def _central_attack_madrid(target_reg: dict):
    """For every MadridApplication whose basic application is the cancelled
    registration's underlying application, and which is still within its
    dependency period, set status = CEASED."""
    basic_app_id = target_reg["application_id"]
    now = db.current_utc_dt()
    for m in db.madrid_applications.values():
        if m["basic_application_id"] != basic_app_id:
            continue
        if m["status"] == "CEASED":
            continue
        if now < parse_iso(m["dependency_end_at"]):
            m["status"] = "CEASED"
            models.touch(m)
