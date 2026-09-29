"""Rating, referral decisions, binding, declining, cancelling, endorsements."""

from datetime import timedelta

from flask import Blueprint

import calc
import services
from auth import AGENT, ALL_ROLES, SENIOR, UNDERWRITER, authenticate, guard_account, is_agent, user_id
from db import by_created, fmt_datetime, new_row, now_dt, parse_date, parse_datetime, store, today, touch
from errors import ApiError
from response import created, ok, ok_list, paginate
from validation import enum_filter, field, pagination, read_body, str_filter, validate

bp = Blueprint("underwriting", __name__)

TXN_TYPES = (
    "BASE_PROPERTY", "BASE_LIVESTOCK", "BASE_LIABILITY", "CAT_LOAD",
    "ENDORSEMENT_ADD", "ENDORSEMENT_REMOVE", "REVERSAL",
)
REASON_CODES = (
    "RATING", "RATING_REVERT", "ENDORSEMENT_APPROVAL", "ENDORSEMENT_RESCISSION",
    "COMPLIANCE_SUSPENSION", "COMPLIANCE_REINSTATEMENT", "POLICY_DECLINE",
    "POLICY_CANCELLATION",
)
ENDORSEMENT_STATUSES = ("REQUESTED", "APPROVED", "REJECTED", "SUSPENDED", "RESCINDED")
RESERVATION_STATUSES = ("RESERVED", "COMMITTED", "RELEASED")
PERILS = ("HAIL", "WIND", "WILDFIRE")
LIVE_UW_STATUSES = ("RATED", "REFERRED", "BOUND")


def _policy(policy_id):
    policy = services.require(store.policies, policy_id, "ERR_FARM_POLICY_NOT_FOUND")
    guard_account(services.account_of_policy(policy))
    return policy


def _check_policy_version(policy, expected):
    if expected != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION")


# ----------------------------------------------------------------------- rating

@bp.route("/farm-policies/<policy_id>/rate", methods=["POST"])
def rate_policy(policy_id):
    actor, _role = authenticate(UNDERWRITER, SENIOR)
    body = validate(read_body(), [field("expected_policy_version", "int", required=True, ge=1)])
    policy = _policy(policy_id)
    account = services.account_of_policy(policy)
    _check_policy_version(policy, body["expected_policy_version"])
    services.guard_policy_open(policy)
    if policy["uw_status"] != "DRAFT":
        raise ApiError("ERR_POLICY_NOT_IN_DRAFT")

    for sibling in services.policies_of_account(policy["account_id"]):
        if sibling["id"] == policy["id"] or sibling["uw_status"] not in LIVE_UW_STATUSES:
            continue
        if (
            policy["_term_start"] <= sibling["_term_end"]
            and policy["_term_end"] >= sibling["_term_start"]
        ):
            raise ApiError("ERR_OVERLAPPING_POLICY_TERM")

    pools = []
    for peril in calc.PERIL_ORDER:
        pool = services.pool_for(account["cat_zone_code"], peril)
        if pool is None:
            raise ApiError("ERR_CAT_POOL_NOT_CONFIGURED")
        pools.append(pool)

    if not services.active_items_of_policy(policy["id"]) and not services.livestock_of_policy(
        policy["id"]
    ):
        raise ApiError("ERR_NO_RATEABLE_EXPOSURE")

    for pool in pools:
        if pool["status"] != "OPEN":
            raise ApiError("ERR_POOL_FROZEN")

    plan = services.build_rating_plan(policy, account)
    services.commit_rating(policy, plan, actor)
    return ok(policy)


# ------------------------------------------------------------ referral decision

@bp.route("/farm-policies/<policy_id>/referral-decisions", methods=["POST"])
def decide_referral(policy_id):
    actor, _role = authenticate(SENIOR)
    body = validate(read_body(), [
        field("decision", "string", required=True, enum=("APPROVE", "RETURN", "DECLINE")),
        field("decision_note", "string", minlen=1),
    ])
    policy = _policy(policy_id)
    if policy.get("referred_by_user_id") is not None and policy["referred_by_user_id"] == actor:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    services.guard_policy_open(policy)
    if policy["uw_status"] != "REFERRED":
        raise ApiError("ERR_POLICY_NOT_REFERRED")

    decision = body["decision"]
    if decision == "APPROVE":
        rating_dt = parse_datetime(policy["rating_valuation_date"])
        policy["uw_status"] = "RATED"
        policy["quote_expires_at"] = fmt_datetime(
            rating_dt + timedelta(days=calc.QUOTE_VALID_DAYS)
        ) if rating_dt is not None else None
        policy["referred_at"] = None
        policy["referred_by_user_id"] = None
        policy["referral_reason_code"] = None
        touch(policy)
    elif decision == "RETURN":
        services.revert_to_draft(policy, "RATING_REVERT")
    else:
        services.decline_policy(policy, policy.get("closure_reason"))
    return ok(policy)


# -------------------------------------------------------------------- binding

@bp.route("/farm-policies/<policy_id>/bind", methods=["POST"])
def bind_policy(policy_id):
    actor, _role = authenticate(UNDERWRITER)
    body = validate(read_body(), [field("expected_policy_version", "int", required=True, ge=1)])
    policy = _policy(policy_id)
    account = services.account_of_policy(policy)
    _check_policy_version(policy, body["expected_policy_version"])
    services.guard_policy_open(policy)
    if policy["uw_status"] != "RATED":
        raise ApiError("ERR_POLICY_NOT_RATED")

    if policy["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED")
    for recommendation in services.recommendations_of_policy(policy["id"]):
        if recommendation["severity"] == "CRITICAL" and recommendation["status"] == "OVERDUE":
            raise ApiError("ERR_CRITICAL_REC_OVERDUE")

    agent = store.agents.get(account["agent_id"])
    if agent is None or agent["appointment_status"] != "ACTIVE":
        raise ApiError("ERR_AGENT_NOT_ACTIVE")

    profile = services.labor_profile_of_policy(policy["id"])
    if profile is not None and profile["coordination_status"] not in ("NOT_REQUIRED", "VERIFIED"):
        raise ApiError("ERR_WC_COORDINATION_UNVERIFIED")
    if profile is None:
        raise ApiError("ERR_WC_PROOF_MISSING")

    expires_at = parse_datetime(policy["quote_expires_at"])
    if expires_at is None or now_dt() > expires_at:
        raise ApiError("ERR_QUOTE_EXPIRED")
    if profile.get("wc_expiry_date"):
        expiry = parse_date(profile["wc_expiry_date"])
        if expiry is None or expiry < today():
            raise ApiError("ERR_WC_PROOF_EXPIRED")

    held_pools = []
    for reservation in services.reservations_of_policy(policy["id"]):
        if reservation["status"] != "RESERVED":
            continue
        pool = store.pools.get(reservation["pool_id"])
        if pool is not None and pool["id"] not in [p["id"] for p in held_pools]:
            held_pools.append(pool)
    for pool in held_pools:
        if pool["status"] != "OPEN":
            raise ApiError("ERR_POOL_FROZEN")
    for pool in held_pools:
        if pool["reserved_cents"] + pool["committed_cents"] > pool["total_capacity_cents"]:
            raise ApiError("ERR_CAT_CAPACITY_EXCEEDED")

    if policy["total_premium_cents"] > agent["authority_limit_cents"]:
        raise ApiError("ERR_AGENT_AUTHORITY_EXCEEDED")

    services.commit_bind(policy, actor)
    return ok(policy)


# ------------------------------------------------------- decline and cancel

@bp.route("/farm-policies/<policy_id>/decline", methods=["POST"])
def decline(policy_id):
    authenticate(UNDERWRITER, SENIOR)
    body = validate(read_body(), [field("closure_reason", "string", required=True, minlen=1)])
    policy = _policy(policy_id)
    services.guard_policy_open(policy)
    if policy["uw_status"] not in ("DRAFT", "RATED", "REFERRED"):
        raise ApiError("ERR_POLICY_NOT_BOUND")
    services.decline_policy(policy, body["closure_reason"])
    return ok(policy)


@bp.route("/farm-policies/<policy_id>/cancel", methods=["POST"])
def cancel(policy_id):
    authenticate(UNDERWRITER)
    body = validate(read_body(), [
        field("expected_policy_version", "int", required=True, ge=1),
        field("closure_reason", "string", required=True, minlen=1),
    ])
    policy = _policy(policy_id)
    _check_policy_version(policy, body["expected_policy_version"])
    services.guard_policy_open(policy)
    if policy["uw_status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")
    services.cancel_policy(policy, body["closure_reason"])
    return ok(policy)


# --------------------------------------------------------------------- ledger

@bp.route("/farm-policies/<policy_id>/premium-transactions", methods=["GET"])
def list_ledger(policy_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    txn_type = enum_filter("txn_type", TXN_TYPES)
    reason_code = enum_filter("reason_code", REASON_CODES)
    policy = _policy(policy_id)
    rows = [
        r for r in services.ledger_of_policy(policy["id"])
        if (txn_type is None or r["txn_type"] == txn_type)
        and (reason_code is None or r["reason_code"] == reason_code)
    ]
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ---------------------------------------------------------------- endorsements

@bp.route("/farm-policies/<policy_id>/endorsements", methods=["POST"])
def request_endorsement(policy_id):
    authenticate(AGENT, UNDERWRITER)
    body = validate(read_body(), [
        field("expected_policy_version", "int", required=True, ge=1),
        field("form_code", "string", required=True, enum=calc.ENDORSEMENT_FORMS),
        field("sublimit_cents", "int", required=True, gt=0),
        field("requested_effective_date", "date", required=True),
    ])
    policy = _policy(policy_id)
    _check_policy_version(policy, body["expected_policy_version"])
    services.guard_policy_open(policy)
    if policy["uw_status"] not in ("RATED", "BOUND"):
        raise ApiError("ERR_POLICY_NOT_RATED")
    if policy["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED")

    row = new_row(
        policy_id=policy["id"],
        form_code=body["form_code"],
        sublimit_cents=body["sublimit_cents"],
        requested_effective_date=body["requested_effective_date"],
        requires_inspection=body["form_code"] in calc.INSPECTION_FORMS,
        status="REQUESTED",
        premium_cents=0,
        decision_note=None,
        decided_by_user_id=None,
    )
    store.endorsements[row["id"]] = row
    return created(row)


@bp.route("/farm-policies/<policy_id>/endorsements", methods=["GET"])
def list_endorsements(policy_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ENDORSEMENT_STATUSES)
    form_code = enum_filter("form_code", calc.ENDORSEMENT_FORMS)
    policy = _policy(policy_id)
    rows = [
        r for r in services.endorsements_of_policy(policy["id"])
        if (status is None or r["status"] == status)
        and (form_code is None or r["form_code"] == form_code)
    ]
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/endorsements/<endorsement_id>", methods=["GET"])
def get_endorsement(endorsement_id):
    authenticate(*ALL_ROLES)
    row = services.require(store.endorsements, endorsement_id, "ERR_ENDORSEMENT_NOT_FOUND")
    policy = store.policies.get(row["policy_id"])
    guard_account(services.account_of_policy(policy))
    return ok(row)


@bp.route("/endorsements/<endorsement_id>/decision", methods=["POST"])
def decide_endorsement(endorsement_id):
    actor, _role = authenticate(UNDERWRITER, SENIOR)
    body = validate(read_body(), [
        field("decision", "string", required=True, enum=("APPROVE", "REJECT")),
        field("decision_note", "string", minlen=1),
    ])
    endorsement = services.require(
        store.endorsements, endorsement_id, "ERR_ENDORSEMENT_NOT_FOUND"
    )
    policy = store.policies.get(endorsement["policy_id"])
    services.guard_policy_open(policy)
    if endorsement["status"] != "REQUESTED":
        raise ApiError("ERR_ENDORSEMENT_NOT_REQUESTED")

    note = body.get("decision_note")
    if body["decision"] == "REJECT":
        endorsement["status"] = "REJECTED"
        endorsement["decision_note"] = note
        endorsement["decided_by_user_id"] = actor
        touch(endorsement)
        return ok(endorsement)

    if policy["uw_status"] not in ("RATED", "BOUND"):
        raise ApiError("ERR_POLICY_NOT_RATED")
    if policy["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED")
    if endorsement["requires_inspection"]:
        latest = services.latest_completed_inspection(policy["id"])
        if latest is None:
            raise ApiError("ERR_BUYBACK_INSPECTION_REQUIRED")
        if latest["hazard_score"] > 35:
            raise ApiError("ERR_BUYBACK_HAZARD_TOO_HIGH")
    companion = calc.ENDORSEMENT_COMPANION.get(endorsement["form_code"])
    if companion is not None:
        present = any(
            e["exposure_type"] == companion
            for e in services.liability_of_policy(policy["id"])
        )
        if not present:
            raise ApiError("ERR_ENDORSEMENT_EXPOSURE_MISSING")

    premium = calc.endorsement_premium(endorsement["form_code"], endorsement["sublimit_cents"])
    endorsement["status"] = "APPROVED"
    endorsement["premium_cents"] = premium
    endorsement["decision_note"] = note
    endorsement["decided_by_user_id"] = actor
    touch(endorsement)
    services.append_txn(policy, "ENDORSEMENT_ADD", "ENDORSEMENT_APPROVAL", premium)
    services.shift_endorsement_premium(policy, premium)
    touch(policy)
    return ok(endorsement)


@bp.route("/endorsements/<endorsement_id>/rescind", methods=["POST"])
def rescind_endorsement(endorsement_id):
    authenticate(UNDERWRITER)
    body = validate(read_body(), [field("decision_note", "string", minlen=1)])
    endorsement = services.require(
        store.endorsements, endorsement_id, "ERR_ENDORSEMENT_NOT_FOUND"
    )
    policy = store.policies.get(endorsement["policy_id"])
    services.guard_policy_open(policy)
    if endorsement["status"] not in ("APPROVED", "SUSPENDED"):
        raise ApiError("ERR_ENDORSEMENT_NOT_APPROVED")
    if policy["uw_status"] not in ("RATED", "BOUND"):
        raise ApiError("ERR_POLICY_NOT_RATED")

    was_approved = endorsement["status"] == "APPROVED"
    amount = endorsement["premium_cents"]
    endorsement["status"] = "RESCINDED"
    endorsement["premium_cents"] = 0
    if "decision_note" in body:
        endorsement["decision_note"] = body["decision_note"]
    touch(endorsement)
    if was_approved:
        if amount:
            services.append_txn(policy, "ENDORSEMENT_REMOVE", "ENDORSEMENT_RESCISSION", -amount)
        services.shift_endorsement_premium(policy, -amount)
    touch(policy)
    return ok(endorsement)


# ------------------------------------------------------- catastrophe reservations

@bp.route("/cat-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    authenticate(*ALL_ROLES)
    return ok(
        services.require(store.reservations, reservation_id, "ERR_CAT_RESERVATION_NOT_FOUND")
    )


@bp.route("/cat-reservations", methods=["GET"])
def list_reservations():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    policy_id = str_filter("policy_id")
    pool_id = str_filter("pool_id")
    peril = enum_filter("peril", PERILS)
    status = enum_filter("status", RESERVATION_STATUSES)
    rows = []
    for reservation in store.reservations.values():
        if policy_id is not None and reservation["policy_id"] != policy_id:
            continue
        if pool_id is not None and reservation["pool_id"] != pool_id:
            continue
        if peril is not None and reservation["peril"] != peril:
            continue
        if status is not None and reservation["status"] != status:
            continue
        if is_agent():
            policy = store.policies.get(reservation["policy_id"])
            account = services.account_of_policy(policy) if policy else None
            if account is None or account["agent_id"] != user_id():
                continue
        rows.append(reservation)
    window, total = paginate(by_created(rows), limit, offset)
    return ok_list(window, limit, offset, total)
