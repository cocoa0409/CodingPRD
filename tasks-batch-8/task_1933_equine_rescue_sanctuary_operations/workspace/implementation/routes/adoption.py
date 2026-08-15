from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_ADOPTION_OFFICER,
    ROLE_ADOPTER,
)
from errors import (
    raise_err,
    ERR_ADOPTER_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_HORSE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_HORSE_NOT_ADOPTABLE,
    ERR_ADOPTER_BLOCKED,
    ERR_DUTY_SEGREGATION,
    ERR_HOME_CHECK_EXPIRED,
    ERR_APPLICATION_PRECEDENCE_BLOCKED,
    ERR_BONDED_PAIR_VIOLATION,
    ERR_DUPLICATE_APPLICATION,
    ERR_HOME_CHECK_LIMIT_EXCEEDED,
    ERR_COOLING_OFF_ACTIVE,
    ERR_PICKUP_WINDOW_EXCEEDED,
    ERR_ADOPTION_FEE_UNPAID,
    ERR_FEE_AMOUNT_INVALID,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    body,
    get_path_or_404,
    minute_floor,
    opt_bool,
    opt_str,
    pagination_args,
    parse_dt,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("adoption", __name__)

EXPERIENCE_LEVELS = {"NOVICE", "INTERMEDIATE", "EXPERT"}
NON_TERMINAL_APP_STATES = {
    "SUBMITTED",
    "UNDER_REVIEW",
    "HOME_CHECK_SCHEDULED",
    "HOME_CHECK_PASSED",
    "APPROVED",
}
OFFICER_READ = [ROLE_ADOPTION_OFFICER, ROLE_SANCTUARY_DIRECTOR]


# --------------------------------------------------------------------------
# Adopters
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/adopters")
def create_adopter():
    authenticate([ROLE_ADOPTER])
    data = body()
    full_name = as_str(require_present(data, "full_name"), "full_name")
    email = as_str(require_present(data, "contact_email"), "contact_email")
    level = as_enum(require_present(data, "experience_level"), "experience_level", EXPERIENCE_LEVELS)
    has_stalls = as_bool(require_present(data, "has_stall_facility"), "has_stall_facility")
    rec = services.new_entity(
        {
            "full_name": full_name,
            "contact_email": email,
            "experience_level": level,
            "has_stall_facility": has_stalls,
            "status": "ACTIVE",
        }
    )
    db.adopters[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/adopters")
def list_adopters():
    authenticate(OFFICER_READ)
    limit, offset = pagination_args()
    filters = []
    value = query_str("status")
    if value is not None:
        filters.append(("status", value))
    rows, total = sorted_page(db.adopters.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/adopters/<adopter_id>")
def get_adopter(adopter_id):
    user_id, role = authenticate(OFFICER_READ + [ROLE_ADOPTER])
    rec = get_path_or_404(db.adopters, adopter_id)
    if role == ROLE_ADOPTER and user_id != adopter_id:
        raise_err(ERR_FORBIDDEN, "Adopters may read only their own record")
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/adopters/<adopter_id>/block")
def block_adopter(adopter_id):
    authenticate(OFFICER_READ)
    rec = get_path_or_404(db.adopters, adopter_id)
    data = body()
    require_present(data, "reason")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Adopter is not ACTIVE")
    rec["status"] = "BLOCKED"
    services.touch(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/adopters/<adopter_id>/unblock")
def unblock_adopter(adopter_id):
    authenticate(OFFICER_READ)
    rec = get_path_or_404(db.adopters, adopter_id)
    if rec["status"] != "BLOCKED":
        raise_err(ERR_INVALID_STATE, "Adopter is not BLOCKED")
    rec["status"] = "ACTIVE"
    services.touch(rec)
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Adoption applications
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/adoption-applications")
def create_application():
    user_id, _ = authenticate([ROLE_ADOPTER])
    data = body()
    adopter_id = data.get("adopter_id")
    if adopter_id is not None and adopter_id not in db.adopters:
        raise_err(ERR_ADOPTER_NOT_FOUND, "adopter_id does not reference an existing adopter")
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    adopter_id = require_present(data, "adopter_id")
    horse_id = require_present(data, "horse_id")
    pickup = parse_dt(require_present(data, "proposed_pickup_date"), "proposed_pickup_date")
    pair = opt_bool(data, "adopt_with_bonded_companion", False)

    if adopter_id != user_id:
        raise_err(ERR_FORBIDDEN, "Adopter may submit applications only under their own id")
    horse = db.horses[horse_id]
    adopter = db.adopters[adopter_id]
    if horse["status"] != "ADOPTABLE":
        raise_err(ERR_HORSE_NOT_ADOPTABLE, "Horse is not ADOPTABLE")
    if adopter["status"] != "ACTIVE":
        raise_err(ERR_ADOPTER_BLOCKED, "Adopter is BLOCKED")
    if any(
        a["adopter_id"] == adopter_id
        and a["horse_id"] == horse_id
        and a["status"] in NON_TERMINAL_APP_STATES
        for a in db.applications.values()
    ):
        raise_err(ERR_DUPLICATE_APPLICATION, "A non-terminal application already exists for this pair")
    if pair and not horse["bonded_companion_id"]:
        raise_err(ERR_BONDED_PAIR_VIOLATION, "Horse has no bonded companion")

    rec = services.new_entity(
        {
            "adopter_id": adopter_id,
            "horse_id": horse_id,
            "adopt_with_bonded_companion": pair,
            "proposed_pickup_date": pickup,
            "status": "SUBMITTED",
            "home_check_attempts": 0,
            "quoted_fee_cents": None,
            "final_fee_cents": None,
            "fee_paid_cents": 0,
            "refund_cents": 0,
            "submitted_at": clock.now(),
            "approved_at": None,
            "finalized_at": None,
            "decision_reason": None,
        }
    )
    db.applications[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/adoption-applications")
def list_applications():
    user_id, role = authenticate(OFFICER_READ + [ROLE_ADOPTER])
    limit, offset = pagination_args()
    filters = []
    for param in ("adopter_id", "horse_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    if role == ROLE_ADOPTER:
        filters.append(("adopter_id", user_id))
    rows, total = sorted_page(db.applications.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/adoption-applications/<app_id>")
def get_application(app_id):
    user_id, role = authenticate(OFFICER_READ + [ROLE_ADOPTER])
    rec = get_path_or_404(db.applications, app_id)
    if role == ROLE_ADOPTER and rec["adopter_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Adopters may read only their own applications")
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/adoption-applications/<app_id>/start-review")
def start_review(app_id):
    authenticate([ROLE_ADOPTION_OFFICER])
    rec = get_path_or_404(db.applications, app_id)
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Application is not SUBMITTED")
    rec["status"] = "UNDER_REVIEW"
    services.touch(rec)
    return ok_object(serialize(rec))


def _latest_completed_home_check(app_id):
    checks = [
        c
        for c in db.home_checks.values()
        if c["application_id"] == app_id and c["status"] == "COMPLETED"
    ]
    if not checks:
        return None
    checks.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return checks[-1]


@bp.post("/rescue-ops/adoption-applications/<app_id>/approve")
def approve_application(app_id):
    user_id, _ = authenticate([ROLE_ADOPTION_OFFICER])
    rec = get_path_or_404(db.applications, app_id)
    if rec["status"] != "HOME_CHECK_PASSED":
        raise_err(ERR_INVALID_STATE, "Application is not HOME_CHECK_PASSED")
    horse = db.horses[rec["horse_id"]]
    if horse["status"] != "ADOPTABLE":
        raise_err(ERR_HORSE_NOT_ADOPTABLE, "Horse is not ADOPTABLE")
    adopter = db.adopters[rec["adopter_id"]]
    if adopter["status"] != "ACTIVE":
        raise_err(ERR_ADOPTER_BLOCKED, "Adopter is BLOCKED")
    check = _latest_completed_home_check(app_id)
    if check is not None and check["completed_by_user_id"] == user_id:
        raise_err(ERR_DUTY_SEGREGATION, "Approver must differ from the home check completer")
    now = clock.now()
    if check is None or minute_floor(check["completed_at"]) < minute_floor(now - timedelta(days=180)):
        raise_err(ERR_HOME_CHECK_EXPIRED, "Passed home check is older than 180 days")
    for other in db.applications.values():
        if other["id"] == rec["id"] or other["horse_id"] != rec["horse_id"]:
            continue
        if other["status"] in ("UNDER_REVIEW", "HOME_CHECK_SCHEDULED", "HOME_CHECK_PASSED"):
            if other["submitted_at"] < rec["submitted_at"]:
                raise_err(
                    ERR_APPLICATION_PRECEDENCE_BLOCKED,
                    "An earlier-submitted application is further along the pipeline",
                )
    if rec["adopt_with_bonded_companion"]:
        companion = db.horses.get(horse["bonded_companion_id"])
        if companion is None or companion["status"] != "ADOPTABLE":
            raise_err(ERR_BONDED_PAIR_VIOLATION, "Bonded companion is not ADOPTABLE")

    rec["quoted_fee_cents"] = calc.adoption_fee(horse, rec["adopt_with_bonded_companion"])
    rec["approved_at"] = now
    rec["status"] = "APPROVED"
    services.touch(rec)
    horse["status"] = "ADOPTION_PENDING"
    horse["active_application_id"] = rec["id"]
    services.touch(horse)
    return ok_object(serialize(rec))


def _revert_horse_on_exit(app):
    horse = db.horses.get(app["horse_id"])
    if horse is not None and horse["active_application_id"] == app["id"]:
        horse["status"] = "ADOPTABLE"
        horse["active_application_id"] = None
        services.touch(horse)


@bp.post("/rescue-ops/adoption-applications/<app_id>/reject")
def reject_application(app_id):
    authenticate([ROLE_ADOPTION_OFFICER])
    rec = get_path_or_404(db.applications, app_id)
    data = body()
    reason = as_str(require_present(data, "reason"), "reason")
    if rec["status"] not in NON_TERMINAL_APP_STATES:
        raise_err(ERR_INVALID_STATE, "Application cannot be rejected from its current state")
    was_approved = rec["status"] == "APPROVED"
    rec["status"] = "REJECTED"
    rec["decision_reason"] = reason
    services.touch(rec)
    if was_approved:
        _revert_horse_on_exit(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/adoption-applications/<app_id>/withdraw")
def withdraw_application(app_id):
    user_id, _ = authenticate([ROLE_ADOPTER])
    rec = get_path_or_404(db.applications, app_id)
    data = body()
    reason = opt_str(data, "reason")
    if rec["adopter_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Adopter may withdraw only their own application")
    if rec["status"] not in NON_TERMINAL_APP_STATES:
        raise_err(ERR_INVALID_STATE, "Application cannot be withdrawn from its current state")
    was_approved = rec["status"] == "APPROVED"
    rec["status"] = "WITHDRAWN"
    if reason is not None:
        rec["decision_reason"] = reason
    services.touch(rec)
    if was_approved:
        _revert_horse_on_exit(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/adoption-applications/<app_id>/pay-fee")
def pay_fee(app_id):
    user_id, _ = authenticate([ROLE_ADOPTER])
    rec = get_path_or_404(db.applications, app_id)
    data = body()
    amount = require_present(data, "amount_cents")
    if rec["adopter_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Adopter may pay only on their own application")
    if rec["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Application is not APPROVED")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise_err(ERR_FEE_AMOUNT_INVALID, "amount_cents must be a positive integer")
    rec["fee_paid_cents"] += amount
    services.touch(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/adoption-applications/<app_id>/finalize")
def finalize_application(app_id):
    authenticate([ROLE_ADOPTION_OFFICER])
    rec = get_path_or_404(db.applications, app_id)
    if rec["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Application is not APPROVED")
    horse = db.horses[rec["horse_id"]]
    if horse["status"] != "ADOPTION_PENDING" or horse["active_application_id"] != rec["id"]:
        raise_err(ERR_INVALID_STATE, "Horse is not pending this application")
    now = clock.now()
    if minute_floor(now) < minute_floor(rec["approved_at"] + timedelta(hours=72)):
        raise_err(ERR_COOLING_OFF_ACTIVE, "72-hour cooling-off has not elapsed")
    if minute_floor(rec["proposed_pickup_date"]) > minute_floor(now + timedelta(days=14)):
        raise_err(ERR_PICKUP_WINDOW_EXCEEDED, "proposed_pickup_date is more than 14 days out")
    if rec["adopt_with_bonded_companion"]:
        companion = db.horses.get(horse["bonded_companion_id"])
        if companion is None or companion["status"] != "ADOPTABLE":
            raise_err(ERR_BONDED_PAIR_VIOLATION, "Bonded companion is not ADOPTABLE")
    final_fee = calc.adoption_fee(horse, rec["adopt_with_bonded_companion"])
    if rec["fee_paid_cents"] != final_fee:
        raise_err(ERR_ADOPTION_FEE_UNPAID, "fee_paid_cents does not equal the FINAL fee")

    rec["final_fee_cents"] = final_fee
    rec["finalized_at"] = now
    rec["status"] = "FINALIZED"
    services.touch(rec)
    services.adoption_finalize_cascade(rec)
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Home checks
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/home-checks")
def create_home_check():
    authenticate([ROLE_ADOPTION_OFFICER])
    data = body()
    app_id = data.get("application_id")
    if app_id is not None and app_id not in db.applications:
        raise_err(ERR_APPLICATION_NOT_FOUND, "application_id does not reference an existing application")
    app_id = require_present(data, "application_id")
    scheduled = parse_dt(require_present(data, "scheduled_date"), "scheduled_date")
    app = db.applications[app_id]
    if app["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Application is not UNDER_REVIEW")
    if app["home_check_attempts"] >= 2:
        raise_err(ERR_HOME_CHECK_LIMIT_EXCEEDED, "Home check attempt cap reached")
    rec = services.new_entity(
        {
            "application_id": app_id,
            "scheduled_date": scheduled,
            "status": "SCHEDULED",
            "outcome": None,
            "completed_by_user_id": None,
            "completed_at": None,
            "findings": None,
        }
    )
    db.home_checks[rec["id"]] = rec
    app["home_check_attempts"] += 1
    app["status"] = "HOME_CHECK_SCHEDULED"
    services.touch(app)
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/home-checks")
def list_home_checks():
    authenticate(OFFICER_READ)
    limit, offset = pagination_args()
    filters = []
    for param in ("application_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.home_checks.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/home-checks/<check_id>")
def get_home_check(check_id):
    authenticate(OFFICER_READ)
    return ok_object(serialize(get_path_or_404(db.home_checks, check_id)))


@bp.post("/rescue-ops/home-checks/<check_id>/complete")
def complete_home_check(check_id):
    user_id, _ = authenticate([ROLE_ADOPTION_OFFICER])
    rec = get_path_or_404(db.home_checks, check_id)
    data = body()
    outcome = as_enum(
        require_present(data, "outcome"), "outcome", {"PASSED", "FAILED", "CONDITIONAL"}
    )
    findings = opt_str(data, "findings")
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Home check is not SCHEDULED")
    app = db.applications[rec["application_id"]]
    latest = max(
        (c for c in db.home_checks.values() if c["application_id"] == app["id"]),
        key=lambda c: (c["created_at"], c["_seq"]),
        default=None,
    )
    if app["status"] != "HOME_CHECK_SCHEDULED" or latest is None or latest["id"] != rec["id"]:
        raise_err(ERR_INVALID_STATE, "Home check is not the application's latest scheduled check")
    rec["status"] = "COMPLETED"
    rec["outcome"] = outcome
    rec["completed_at"] = clock.now()
    rec["completed_by_user_id"] = user_id
    if findings is not None:
        rec["findings"] = findings
    services.touch(rec)

    if outcome == "PASSED":
        app["status"] = "HOME_CHECK_PASSED"
    elif outcome == "FAILED" and app["home_check_attempts"] >= 2:
        app["status"] = "REJECTED"
        app["decision_reason"] = "HOME_CHECK_LIMIT"
    else:
        app["status"] = "UNDER_REVIEW"
    services.touch(app)
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Follow-up visits
# --------------------------------------------------------------------------
@bp.get("/rescue-ops/follow-up-visits")
def list_follow_ups():
    authenticate(OFFICER_READ)
    limit, offset = pagination_args()
    filters = []
    for param in ("application_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.follow_ups.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/follow-up-visits/<visit_id>")
def get_follow_up(visit_id):
    authenticate(OFFICER_READ)
    return ok_object(serialize(get_path_or_404(db.follow_ups, visit_id)))


@bp.post("/rescue-ops/follow-up-visits/<visit_id>/complete")
def complete_follow_up(visit_id):
    authenticate([ROLE_ADOPTION_OFFICER])
    rec = get_path_or_404(db.follow_ups, visit_id)
    data = body()
    outcome = as_enum(require_present(data, "outcome"), "outcome", {"PASSED", "FAILED"})
    findings = opt_str(data, "findings")
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Follow-up visit is not SCHEDULED")
    app = db.applications[rec["application_id"]]
    if app["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "Owning application is not FINALIZED")
    rec["status"] = "COMPLETED"
    rec["outcome"] = outcome
    rec["completed_at"] = clock.now()
    if findings is not None:
        rec["findings"] = findings
    services.touch(rec)
    if outcome == "FAILED":
        services.return_cascade(app)
    return ok_object(serialize(rec))
