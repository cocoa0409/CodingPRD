"""Disbursement endpoints (PRD §3.6) — create (OCC), approve, void, fetch, list."""
from flask import Blueprint, request

import db
import errors
import response
import validate
import pagination
from middleware import (
    require_auth, require_role,
    QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER,
)
from services import core

bp = Blueprint("disbursements", __name__)

READ_ROLES = {QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER}

PURPOSES = {"QI_FEE", "ACQUISITION", "IMPROVEMENT_DRAW", "BOOT_RETURN"}
# Waterfall priority bucket derived from purpose (PRD §3.6).
PRIORITY = {"QI_FEE": 1, "ACQUISITION": 2, "IMPROVEMENT_DRAW": 3, "BOOT_RETURN": 4}
# replacement_property_id is meaningful only for these purposes (PRD §3.6).
REPLACEMENT_PURPOSES = {"ACQUISITION", "IMPROVEMENT_DRAW"}


@bp.post("/disbursements")
def create_disbursement():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    data = validate.body()
    exchange_id = validate.require_str(data, "exchange_id")
    purpose = validate.require_enum(data, "purpose", PURPOSES)
    amount = validate.require_number(data, "amount", gt=0)
    # expected_qualified_trust_version is mandatory on create (PRD §2.11).
    expected_version = validate.require_int(data, "expected_qualified_trust_version")
    replacement_property_id = data.get("replacement_property_id")
    if replacement_property_id is not None and not isinstance(replacement_property_id, str):
        raise errors.invalid_request("replacement_property_id must be a string or null.")

    # existence (priority 3): exchange, then optional replacement reference.
    ex = db.exchanges.get(exchange_id)
    if ex is None:
        raise errors.not_found()
    if replacement_property_id is not None:
        if replacement_property_id not in db.replacement_properties:
            raise errors.not_found()

    trust = core.trust_for(exchange_id)
    if trust is None:
        # no custodial account to draw from -> not found of trust reference.
        raise errors.not_found()

    # trust must not be locked for a new create (priority 12, PRD §3.6).
    core.apply_posture(ex)
    if trust["is_locked"]:
        raise errors.trust_locked()

    # OCC (priority 14): expected version must equal current trust version (PRD §2.11).
    if expected_version != trust["version"]:
        raise errors.stale_trust_version()

    # replacement_property_id is null unless purpose is ACQUISITION/IMPROVEMENT_DRAW.
    stored_replacement_id = replacement_property_id if purpose in REPLACEMENT_PURPOSES else None

    record = core._stamp_new({
        "exchange_id": exchange_id,
        "replacement_property_id": stored_replacement_id,
        "purpose": purpose,
        "priority": PRIORITY[purpose],
        "amount": amount,
        "settlement_status": "REQUESTED",
        "settlement_officer_user_id": None,
    })
    db.disbursements[record["id"]] = record
    return response.success_object(core.serialize_disbursement(record), status=201)


@bp.get("/disbursements/<disbursement_id>")
def get_disbursement(disbursement_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    d = db.disbursements.get(disbursement_id)
    if d is None:
        raise errors.not_found()
    if role == EXCHANGER:
        ex = db.exchanges.get(d["exchange_id"])
        if ex is None or ex["exchanger_id"] != user_id:
            raise errors.unauthorized()
    return response.success_object(core.serialize_disbursement(d))


@bp.get("/disbursements")
def list_disbursements():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR, SETTLEMENT_OFFICER})
    limit, offset = pagination.read_params()
    rows = list(db.disbursements.values())
    exchange_id = request.args.get("exchange_id")
    replacement_property_id = request.args.get("replacement_property_id")
    if exchange_id is not None:
        rows = [r for r in rows if r["exchange_id"] == exchange_id]
    if replacement_property_id is not None:
        rows = [r for r in rows if r["replacement_property_id"] == replacement_property_id]
    page, meta = pagination.paginate(rows, limit, offset)
    return response.success_array([core.serialize_disbursement(r) for r in page], pagination=meta)


@bp.post("/disbursements/<disbursement_id>/approve")
def approve_disbursement(disbursement_id):
    user_id, role = require_auth()
    require_role(role, {SETTLEMENT_OFFICER})
    d = db.disbursements.get(disbursement_id)
    if d is None:
        raise errors.not_found()
    ex = db.exchanges.get(d["exchange_id"])
    trust = core.trust_for(d["exchange_id"])
    core.apply_posture(ex)

    # state (priority 5): must be REQUESTED; posture must be OPEN/IDENTIFIED.
    if d["settlement_status"] != "REQUESTED":
        raise errors.invalid_state()
    if ex["compliance_posture"] not in ("OPEN", "IDENTIFIED"):
        # AT_RISK / COMPLETED / FAILED are not approvable postures. When the trust is
        # locked the lock check (priority 12) is the canonical error; otherwise the
        # transition is simply not defined from this posture.
        if trust is not None and trust["is_locked"]:
            raise errors.trust_locked()
        raise errors.invalid_state()
    # BOOT_RETURN requires an existing replacement before approval (PRD §3.6) -> state.
    if d["purpose"] == "BOOT_RETURN":
        if len(core.replacements_for(d["exchange_id"])) == 0:
            raise errors.invalid_state()

    # segregation of duties (priority 6, PRD §3.6) -> ERR_SEGREGATION_OF_DUTIES.
    if user_id == ex["coordinator_user_id"]:
        raise errors.segregation_of_duties()

    # trust lock (priority 12).
    if trust is None or trust["is_locked"]:
        raise errors.trust_locked()

    # sufficient funds (priority 13): amount <= available_balance.
    available = core.trust_available_balance(d["exchange_id"], trust)
    if d["amount"] > available:
        raise errors.insufficient_trust_funds()

    # apply: stamp officer, SETTLED, debit trust (cascade), bump both versions.
    d["settlement_officer_user_id"] = user_id
    d["settlement_status"] = "SETTLED"
    core.touch(d)
    core.touch(trust)  # debit reflected by recomputed available_balance; bump version.
    return response.success_object(core.serialize_disbursement(d))


@bp.post("/disbursements/<disbursement_id>/void")
def void_disbursement(disbursement_id):
    user_id, role = require_auth()
    require_role(role, {SETTLEMENT_OFFICER})
    d = db.disbursements.get(disbursement_id)
    if d is None:
        raise errors.not_found()
    trust = core.trust_for(d["exchange_id"])
    status = d["settlement_status"]

    if status == "SETTLED":
        # voiding a SETTLED disbursement requires the trust unlocked (PRD §3.6).
        if trust is None or trust["is_locked"]:
            raise errors.trust_locked()
        d["settlement_status"] = "VOIDED"
        core.touch(d)
        # credit back (compensation); available_balance recomputes, bump trust version.
        core.touch(trust)
    elif status == "REQUESTED":
        # never debited -> no trust effect, bump only disbursement version (PRD §3.6).
        d["settlement_status"] = "VOIDED"
        core.touch(d)
    else:
        # not in a voidable state (already VOIDED) -> ERR_INVALID_STATE.
        raise errors.invalid_state()
    return response.success_object(core.serialize_disbursement(d))
