"""Subscribers and organizational vetting (PRD 3.2, 3.3)."""

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services.lookup import get_subscriber, get_vetting
from validation import (CHECK_DIMENSIONS, CHECK_OUTCOMES, REQUIRED_LEVELS, enum_value,
                        in_range, opt_int, opt_str, req_str)

bp = Blueprint("subscribers", __name__)

DEFAULT_CREDIT_LIMIT_CENTS = 500000
OPEN_VETTING_STATES = ("PENDING", "IN_PROGRESS", "AWAITING_APPROVAL")
DIMENSION_FIELD = {
    "REGISTRY": ("registry_check_status", "registry_checked_by_user_id"),
    "CALLBACK": ("callback_check_status", "callback_checked_by_user_id"),
    "AUTHORITY": ("authority_check_status", "authority_checked_by_user_id"),
}
REQUIRED_DIMENSIONS = {"OV": ("REGISTRY", "CALLBACK"), "EV": ("REGISTRY", "CALLBACK", "AUTHORITY")}


@bp.route("/ca/subscribers", methods=["POST"])
def create_subscriber():
    authenticate(("POLICY_ADMIN",))
    body = json_body()
    legal_name = req_str(body, "legal_name", 1, 160)
    jurisdiction_code = req_str(body, "jurisdiction_code", 2, 6)
    registry_id = req_str(body, "registry_id", 1, 40)
    contact_email = req_str(body, "contact_email", 1, None)
    callback_phone = req_str(body, "callback_phone", 5, 24)
    credit_limit_cents = opt_int(body, "credit_limit_cents", DEFAULT_CREDIT_LIMIT_CENTS)

    if jurisdiction_code != jurisdiction_code.upper():
        fail("ERR_INVALID_REQUEST", "Field 'jurisdiction_code' must be uppercase.")
    if "@" not in contact_email:
        fail("ERR_INVALID_REQUEST", "Field 'contact_email' must contain an at-sign.")
    in_range(credit_limit_cents, 0, 100000000, "credit_limit_cents")

    for existing in db.subscribers.values():
        if (existing["jurisdiction_code"] == jurisdiction_code
                and existing["registry_id"] == registry_id):
            fail(
                "ERR_SUBSCRIBER_REGISTRY_DUPLICATE",
                "A subscriber with this jurisdiction and registry id already exists.",
            )

    record = make_record({
        "legal_name": legal_name,
        "jurisdiction_code": jurisdiction_code,
        "registry_id": registry_id,
        "contact_email": contact_email,
        "callback_phone": callback_phone,
        "account_status": "ACTIVE",
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "issued_certificate_count": 0,
        "revocation_pending_count": 0,
        "risk_score_operational": 0,
        "risk_score_audit_final": None,
        "suspended_at": None,
    })
    db.subscribers[record["id"]] = record
    return created(public(record))


@bp.route("/ca/subscribers", methods=["GET"])
def list_subscribers():
    read_only(ALL_ROLES)
    records = apply_filters(
        db.subscribers.values(), {"account_status": "str", "jurisdiction_code": "str"}
    )
    return paginated(sort_records(records))


@bp.route("/ca/subscribers/<subscriber_id>", methods=["GET"])
def get_one_subscriber(subscriber_id):
    read_only(ALL_ROLES)
    return ok(public(get_subscriber(subscriber_id)))


@bp.route("/ca/subscribers/<subscriber_id>", methods=["PATCH"])
def update_subscriber(subscriber_id):
    authenticate(("POLICY_ADMIN",))
    body = json_body()
    credit_limit_cents = opt_int(body, "credit_limit_cents")
    contact_email = opt_str(body, "contact_email", 1, None)
    callback_phone = opt_str(body, "callback_phone", 5, 24)
    if contact_email is not None and "@" not in contact_email:
        fail("ERR_INVALID_REQUEST", "Field 'contact_email' must contain an at-sign.")

    subscriber = get_subscriber(subscriber_id)

    if credit_limit_cents is not None:
        in_range(credit_limit_cents, 0, 100000000, "credit_limit_cents")
        subscriber["credit_limit_cents"] = credit_limit_cents
    if contact_email is not None:
        subscriber["contact_email"] = contact_email
    if callback_phone is not None:
        subscriber["callback_phone"] = callback_phone
    touch(subscriber)
    return ok(public(subscriber))


# --- organizational vetting ---------------------------------------------
@bp.route("/ca/subscribers/<subscriber_id>/organization-vettings", methods=["POST"])
def open_vetting(subscriber_id):
    authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    required_level = req_str(body, "required_level")
    enum_value(required_level, REQUIRED_LEVELS, "required_level")

    subscriber = get_subscriber(subscriber_id)

    if subscriber["account_status"] != "ACTIVE":
        fail("ERR_SUBSCRIBER_NOT_ACTIVE", "The subscriber must be ACTIVE.")

    for existing in db.vettings.values():
        if (existing["subscriber_id"] == subscriber["id"]
                and existing["vetting_state"] in OPEN_VETTING_STATES):
            fail("ERR_VETTING_ALREADY_OPEN", "A vetting file is already in flight.")

    record = make_record({
        "subscriber_id": subscriber["id"],
        "required_level": required_level,
        "registry_check_status": "NOT_STARTED",
        "callback_check_status": "NOT_STARTED",
        "authority_check_status": "NOT_STARTED",
        "registry_checked_by_user_id": None,
        "callback_checked_by_user_id": None,
        "authority_checked_by_user_id": None,
        "vetting_state": "PENDING",
        "approved_at": None,
        "approved_by_user_id": None,
        "rejected_at": None,
    })
    db.vettings[record["id"]] = record
    return created(public(record))


@bp.route("/ca/subscribers/<subscriber_id>/organization-vettings", methods=["GET"])
def list_vettings(subscriber_id):
    read_only(ALL_ROLES)
    subscriber = get_subscriber(subscriber_id)
    records = [v for v in db.vettings.values() if v["subscriber_id"] == subscriber["id"]]
    records = apply_filters(records, {"vetting_state": "str"})
    return paginated(sort_records(records))


@bp.route("/ca/organization-vettings/<vetting_id>", methods=["GET"])
def get_one_vetting(vetting_id):
    read_only(ALL_ROLES)
    return ok(public(get_vetting(vetting_id)))


@bp.route("/ca/organization-vettings/<vetting_id>/checks", methods=["POST"])
def record_check(vetting_id):
    user_id, _role = authenticate(("VALIDATION_OFFICER",))
    body = json_body()
    dimension = req_str(body, "dimension")
    outcome = req_str(body, "outcome")
    opt_str(body, "evidence_ref")
    enum_value(dimension, CHECK_DIMENSIONS, "dimension")
    enum_value(outcome, CHECK_OUTCOMES, "outcome")

    vetting = get_vetting(vetting_id)

    if vetting["vetting_state"] not in OPEN_VETTING_STATES:
        fail("ERR_VETTING_ALREADY_DECIDED", "The vetting file has already been decided.")

    status_field, user_field = DIMENSION_FIELD[dimension]
    vetting[status_field] = outcome
    vetting[user_field] = user_id

    required = REQUIRED_DIMENSIONS[vetting["required_level"]]
    statuses = [vetting[DIMENSION_FIELD[d][0]] for d in required]
    if any(s == "FAILED" for s in statuses):
        if vetting["vetting_state"] != "REJECTED":
            vetting["vetting_state"] = "REJECTED"
            vetting["rejected_at"] = db.now()
    elif all(s == "PASSED" for s in statuses):
        vetting["vetting_state"] = "AWAITING_APPROVAL"
    elif any(s != "NOT_STARTED" for s in statuses):
        vetting["vetting_state"] = "IN_PROGRESS"
    touch(vetting)
    return ok(public(vetting))


@bp.route("/ca/organization-vettings/<vetting_id>/approve", methods=["POST"])
def approve_vetting(vetting_id):
    user_id, _role = authenticate(("VETTING_APPROVER",))
    vetting = get_vetting(vetting_id)

    if vetting["vetting_state"] != "AWAITING_APPROVAL":
        fail("ERR_VETTING_NOT_AWAITING_APPROVAL", "The file is not awaiting approval.")

    checkers = [
        vetting["registry_checked_by_user_id"],
        vetting["callback_checked_by_user_id"],
        vetting["authority_checked_by_user_id"],
    ]
    if any(c is not None and c == user_id for c in checkers):
        fail(
            "ERR_VETTING_SOD_VIOLATION",
            "The approver may not be one of the officers who recorded a check.",
        )

    vetting["vetting_state"] = "APPROVED"
    vetting["approved_at"] = db.now()
    vetting["approved_by_user_id"] = user_id
    touch(vetting)
    return ok(public(vetting))
