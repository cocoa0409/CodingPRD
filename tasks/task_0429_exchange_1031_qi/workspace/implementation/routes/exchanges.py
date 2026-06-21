"""Exchange endpoints and its child sub-resources (PRD §3.1–§3.7)."""
from flask import Blueprint, request

import db
import errors
import response
import util
import validate
import pagination
from middleware import (
    require_auth, require_role,
    QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER,
)
from services import core

bp = Blueprint("exchanges", __name__)

EXCHANGE_TYPES = {"FORWARD", "REVERSE", "IMPROVEMENT"}
READ_ROLES = {QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER}


# --- ownership helper (PRD §2.1) ------------------------------------------
def _check_exchange_ownership(role, user_id, exchange):
    if role == EXCHANGER and exchange["exchanger_id"] != user_id:
        raise errors.unauthorized()


def _get_exchange_or_404(exchange_id):
    ex = db.exchanges.get(exchange_id)
    if ex is None:
        raise errors.not_found()
    return ex


# ===========================================================================
# Exchange CRUD
# ===========================================================================
@bp.post("/exchanges")
def create_exchange():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    data = validate.body()
    exchanger_id = validate.require_str(data, "exchanger_id")
    exchange_type = validate.require_enum(data, "exchange_type", EXCHANGE_TYPES)
    # existence of referenced exchanger (priority 3, PRD §2.10).
    if exchanger_id not in db.exchangers:
        raise errors.not_found()
    record = core._stamp_new({
        "exchanger_id": exchanger_id,
        "exchange_type": exchange_type,
        # X-User-ID captured as coordinator_user_id (PRD §2.1, §3.1).
        "coordinator_user_id": user_id,
        "compliance_posture": None,  # not yet meaningful until close (PRD §3.1)
        "status": "DRAFT",
        "relinquished_closing_at": None,
        "id_deadline_at": None,
        "exchange_deadline_at": None,
        "realized_gain": None,
        "recognized_gain": None,
        "deferred_gain": None,
    })
    db.exchanges[record["id"]] = record
    return response.success_object(core.serialize_exchange(record), status=201)


@bp.get("/exchanges/<exchange_id>")
def get_exchange(exchange_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    ex = _get_exchange_or_404(exchange_id)
    _check_exchange_ownership(role, user_id, ex)
    # Reading lazily recomputes posture against the clock first (PRD §3.1, §2.8).
    core.apply_posture(ex)
    return response.success_object(core.serialize_exchange(ex))


@bp.get("/exchanges")
def list_exchanges():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR, SETTLEMENT_OFFICER})
    limit, offset = pagination.read_params()
    rows = list(db.exchanges.values())
    exchanger_id = request.args.get("exchanger_id")
    if exchanger_id is not None:
        rows = [r for r in rows if r["exchanger_id"] == exchanger_id]
    for r in rows:
        core.apply_posture(r)
    page, meta = pagination.paginate(rows, limit, offset)
    return response.success_array(
        [core.serialize_exchange(r) for r in page], pagination=meta
    )


# ===========================================================================
# Relinquished property (PRD §3.2)
# ===========================================================================
@bp.post("/exchanges/<exchange_id>/relinquished-properties")
def attach_relinquished(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    data = validate.body()
    address = validate.require_str(data, "address", allow_empty=True)
    fair_market_value = validate.require_number(data, "fair_market_value", gt=0)
    selling_expenses = validate.require_number(data, "selling_expenses", gte=0)
    mortgage_payoff = validate.require_number(data, "mortgage_payoff", gte=0)
    adjusted_basis = validate.require_number(data, "adjusted_basis", gte=0)
    # Attaches only while DRAFT (PRD §3.2).
    if ex["status"] != "DRAFT":
        raise errors.invalid_state()
    record = core._stamp_new({
        "exchange_id": exchange_id,
        "address": address,
        "fair_market_value": fair_market_value,
        "selling_expenses": selling_expenses,
        "mortgage_payoff": mortgage_payoff,
        "adjusted_basis": adjusted_basis,
        "net_proceeds": util.money(0),  # remains 0 until close (PRD §3.2)
    })
    db.relinquished_properties[record["id"]] = record
    return response.success_object(core.serialize_relinquished(record), status=201)


@bp.get("/exchanges/<exchange_id>/relinquished-properties")
def list_relinquished(exchange_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    ex = _get_exchange_or_404(exchange_id)
    _check_exchange_ownership(role, user_id, ex)
    rows = core.relinquished_for(exchange_id)
    rows = [rows] if rows else []
    # array of 0..1 (PRD §3.2); not paginated parameters but envelope is array.
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    return response.success_array([core.serialize_relinquished(r) for r in rows])


# ===========================================================================
# Qualified trust (PRD §3.2)
# ===========================================================================
@bp.post("/exchanges/<exchange_id>/trust")
def open_trust(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    # Open only on a DRAFT exchange (endpoint description / PRD §3.2).
    if ex["status"] != "DRAFT":
        raise errors.invalid_state()
    # 1:1 — a second trust is rejected (PRD §3.2).
    if core.trust_for(exchange_id) is not None:
        raise errors.trust_already_exists()
    record = core._stamp_new({
        "exchange_id": exchange_id,
        "deposited_amount": util.money(0),
        "is_locked": False,
    })
    db.qualified_trusts[record["id"]] = record
    return response.success_object(core.serialize_trust(record), status=201)


@bp.get("/exchanges/<exchange_id>/trust")
def list_trust(exchange_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    ex = _get_exchange_or_404(exchange_id)
    _check_exchange_ownership(role, user_id, ex)
    t = core.trust_for(exchange_id)
    rows = [t] if t else []
    return response.success_array([core.serialize_trust(r) for r in rows])


# ===========================================================================
# Close the relinquished leg — Day 0 (PRD §3.3)
# ===========================================================================
@bp.post("/exchanges/<exchange_id>/close-relinquished")
def close_relinquished(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    # Permitted only when DRAFT (PRD §3.3) -> ERR_INVALID_STATE.
    if ex["status"] != "DRAFT":
        raise errors.invalid_state()
    rel = core.relinquished_for(exchange_id)
    trust = core.trust_for(exchange_id)
    # exactly one relinquished property and a trust must exist (PRD §3.3).
    if rel is None or trust is None:
        raise errors.invalid_state()

    now = db.now_logical()
    # stamp Day-0 anchor and derive both deadlines (same time-of-day, PRD §3.3).
    ex["relinquished_closing_at"] = now
    ex["id_deadline_at"] = core.add_calendar_days(now, 45)
    ex["exchange_deadline_at"] = core.add_calendar_days(now, 180)
    # compute net_proceeds and realized_gain (PRD §3.3).
    rel["net_proceeds"] = core.compute_net_proceeds(rel)
    ex["realized_gain"] = core.compute_realized_gain(rel)
    core.touch(rel)
    # deposit net_proceeds into the trust (cascade); credit deposited_amount.
    trust["deposited_amount"] = rel["net_proceeds"]
    core.touch(trust)
    # posture -> OPEN, status -> ACTIVE, bump exchange version.
    ex["status"] = "ACTIVE"
    ex["compliance_posture"] = "OPEN"
    core.touch(ex)
    return response.success_object(core.serialize_exchange(ex))


# ===========================================================================
# Replacement properties (PRD §3.5)
# ===========================================================================
@bp.post("/exchanges/<exchange_id>/replacement-properties")
def record_replacement(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    data = validate.body()
    identified_property_id = validate.require_str(data, "identified_property_id")
    purchase_price = validate.require_number(data, "purchase_price", gt=0)
    replacement_debt = validate.require_number(data, "replacement_debt", gte=0)
    improvement_value = validate.optional_number(data, "improvement_value", 0, gte=0)

    # Existence of the referenced candidate (priority 3, left-to-right; the candidate
    # id is a body reference checked after the path exchange).
    candidate = db.identified_properties.get(identified_property_id)
    if candidate is None:
        raise errors.not_found()

    # Must be ACTIVE to record a replacement (state, PRD §3.5).
    core.apply_posture(ex)
    if ex["status"] != "ACTIVE":
        raise errors.invalid_state()

    # Deadline gate (priority 8, PRD §3.5) -> inclusive on/before exchange_deadline_at.
    now = db.now_logical()
    if ex["exchange_deadline_at"] is not None and now > ex["exchange_deadline_at"]:
        raise errors.exchange_deadline_passed()

    # like-kind linkage: candidate must be under THIS exchange's FINALIZED
    # identification and still CANDIDATE (priority 11, PRD §3.5) -> ERR_NOT_IDENTIFIED.
    finalized = core.finalized_identification_for(exchange_id)
    if (finalized is None
            or candidate["identification_id"] != finalized["id"]
            or candidate["status"] != "CANDIDATE"):
        raise errors.not_identified()

    rel = core.relinquished_for(exchange_id)
    trust = core.trust_for(exchange_id)

    record = core._stamp_new({
        "exchange_id": exchange_id,
        "identified_property_id": identified_property_id,
        "purchase_price": purchase_price,
        "replacement_debt": replacement_debt,
        "improvement_value": improvement_value,
        "cash_applied": None,
        "acquired_at": now,
    })
    # boot arithmetic in pinned order (PRD §3.5).
    cash_applied, recognized, deferred = core.compute_boot_and_gain(ex, rel, trust, record)
    record["cash_applied"] = cash_applied
    db.replacement_properties[record["id"]] = record

    # reclassify linked candidate CANDIDATE -> ACQUIRED (downward cascade).
    candidate["status"] = "ACQUIRED"

    # recompute exchange gain figures, bump exchange version.
    ex["recognized_gain"] = recognized
    ex["deferred_gain"] = deferred
    core.touch(ex)
    return response.success_object(core.serialize_replacement(record), status=201)


@bp.get("/exchanges/<exchange_id>/replacement-properties")
def list_replacements_for_exchange(exchange_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    ex = _get_exchange_or_404(exchange_id)
    _check_exchange_ownership(role, user_id, ex)
    rows = sorted(core.replacements_for(exchange_id), key=lambda r: (r["created_at"], r["_seq"]))
    return response.success_array([core.serialize_replacement(r) for r in rows])


# ===========================================================================
# Lifecycle transitions: complete / fail / terminate (PRD §3.7)
# ===========================================================================
@bp.post("/exchanges/<exchange_id>/complete")
def complete_exchange(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    core.apply_posture(ex)
    # Must be ACTIVE; completion from any posture other than IDENTIFIED -> INVALID_STATE.
    if ex["status"] != "ACTIVE":
        raise errors.invalid_state()
    # State check (priority 5) precedes the deadline gate (priority 8): a completion
    # from any posture other than IDENTIFIED is ERR_INVALID_STATE (PRD §3.7).
    if ex["compliance_posture"] != "IDENTIFIED":
        raise errors.invalid_state()
    # Deadline gate (priority 8) -> inclusive on/before exchange_deadline_at (PRD §3.7).
    now = db.now_logical()
    if ex["exchange_deadline_at"] is not None and now > ex["exchange_deadline_at"]:
        raise errors.exchange_deadline_passed()
    finalized = core.finalized_identification_for(exchange_id)
    # every candidate under the finalized identification must be ACQUIRED (PRD §3.7).
    if finalized is None:
        raise errors.invalid_state()
    cands = core.candidates_for(finalized["id"])
    if any(c["status"] != "ACQUIRED" for c in cands):
        raise errors.invalid_state()
    # recognized_gain and deferred_gain non-null (at least one replacement, PRD §3.7).
    if ex["recognized_gain"] is None or ex["deferred_gain"] is None:
        raise errors.invalid_state()
    # apply: posture COMPLETED, lock trust (cascade), status COMPLETED, bump version.
    ex["compliance_posture"] = "COMPLETED"
    ex["status"] = "COMPLETED"
    trust = core.trust_for(exchange_id)
    if trust is not None:
        trust["is_locked"] = True
        core.touch(trust)
    core.touch(ex)
    return response.success_object(core.serialize_exchange(ex))


@bp.post("/exchanges/<exchange_id>/fail")
def fail_exchange(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    # Permitted only when ACTIVE (PRD §3.7).
    if ex["status"] != "ACTIVE":
        raise errors.invalid_state()
    now = db.now_logical()
    finalized = core.finalized_identification_for(exchange_id)
    past_exchange = ex["exchange_deadline_at"] is not None and now > ex["exchange_deadline_at"]
    past_id_no_final = (
        finalized is None
        and ex["id_deadline_at"] is not None
        and now > ex["id_deadline_at"]
    )
    # current clock past exchange_deadline OR (no finalized id AND past id_deadline).
    if not (past_exchange or past_id_no_final):
        raise errors.invalid_state()
    ex["compliance_posture"] = "FAILED"
    ex["status"] = "FAILED"
    trust = core.trust_for(exchange_id)
    if trust is not None:
        trust["is_locked"] = True
        core.touch(trust)
    core.touch(ex)
    return response.success_object(core.serialize_exchange(ex))


@bp.post("/exchanges/<exchange_id>/terminate")
def terminate_exchange(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    # Permitted only while DRAFT (PRD §3.7).
    if ex["status"] != "DRAFT":
        raise errors.invalid_state()
    # no trust with positive available_balance (PRD §3.7).
    trust = core.trust_for(exchange_id)
    if trust is not None:
        available = core.trust_available_balance(exchange_id, trust)
        if available > 0:
            raise errors.invalid_state()
    ex["status"] = "TERMINATED"
    core.touch(ex)
    return response.success_object(core.serialize_exchange(ex))


# ===========================================================================
# Identifications nested under exchange (PRD §3.4)
# ===========================================================================
IDENTIFICATION_METHODS = {"THREE_PROPERTY", "TWO_HUNDRED_PCT"}


@bp.post("/exchanges/<exchange_id>/identifications")
def create_identification(exchange_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    ex = _get_exchange_or_404(exchange_id)
    data = validate.body()
    method = validate.require_enum(data, "method", IDENTIFICATION_METHODS)
    # Created on an ACTIVE exchange (PRD §3.4).
    core.apply_posture(ex)
    if ex["status"] != "ACTIVE":
        raise errors.invalid_state()
    record = core._stamp_new({
        "exchange_id": exchange_id,
        "method": method,
        "status": "DRAFT",
        "finalized_at": None,
    })
    db.identifications[record["id"]] = record
    return response.success_object(core.serialize_identification(record), status=201)


@bp.get("/exchanges/<exchange_id>/identifications")
def list_identifications(exchange_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    ex = _get_exchange_or_404(exchange_id)
    _check_exchange_ownership(role, user_id, ex)
    rows = sorted(core.identifications_for(exchange_id), key=lambda r: (r["created_at"], r["_seq"]))
    return response.success_array([core.serialize_identification(r) for r in rows])
