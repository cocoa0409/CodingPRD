"""Wire lifecycle: initiate, submit, approve, reject, release, cancel,
repair, resubmit, approvals, summary (PRD §3.2-3.5, §2.6-2.7)."""

from datetime import timedelta

from flask import Blueprint

from db import STORE, base_entity, iso, now, pub, touch
from errors import (
    ERR_ACCOUNT_INACTIVE,
    ERR_BENEFICIARY_ACCOUNT_MISMATCH,
    ERR_BENEFICIARY_INACTIVE,
    ERR_CALLBACK_NOT_VERIFIED,
    ERR_CUSTOMER_FROZEN,
    ERR_CUTOFF_PASSED,
    ERR_DAILY_LIMIT_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REPAIR_LIMIT_EXCEEDED,
    ERR_SANCTIONS_NOT_CLEARED,
    ERR_SOD_APPROVER_MISMATCH,
    ERR_STALE_VERSION,
    ERR_WIRE_ON_HOLD,
    ApiError,
)
from listing import list_response
from middleware import (
    ALL_INTERNAL,
    get_body,
    require_fk,
    require_roles,
    validate_body,
)
from response import ok
from services import (
    CALLBACK_THRESHOLD_CENTS,
    audit,
    compute_fee,
    find_business_date,
    get_or_404,
    lazy_eval_wire,
    posted_deducted_from_principal_cents,
    release_reservation,
    run_screening,
)

bp = Blueprint("wires", __name__, url_prefix="/wire-ops")

_METHODS = {"Fedwire", "SWIFT", "CHIPS"}


def _get_wire(wire_id):
    wire = get_or_404(STORE.wires, wire_id, "wire")
    lazy_eval_wire(wire)
    return wire


def _check_occ(data, wire):
    """Priority 9: OCC evaluated after existence + schema, before state rules."""
    if data.get("expected_wire_version") != wire["version"]:
        raise ApiError(*ERR_STALE_VERSION,
                       "expected_wire_version does not match the wire's current version.")


# ---------------------------------------------------------------------------
# Initiation (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/wires")
def create_wire():
    uid, role = require_roles("WireOperator")
    data = get_body()
    # Priority 3: body-supplied foreign references resolve before schema (4).
    require_fk(data, "ordering_account_id", STORE.accounts, "account")
    require_fk(data, "beneficiary_id", STORE.beneficiaries, "beneficiary")
    validate_body(data, {
        "ordering_account_id": ("str", True, None),
        "beneficiary_id": ("str", True, None),
        "amount_cents": ("posint", True, None),
        "currency": ("str", False, None),
        "method": ("str", True, _METHODS),
        "priority": ("str", False, {"NORMAL", "SAME_DAY"}),
        "charge_mode": ("str", False, {"OUR", "BENEFICIARY_REMUNERATION"}),
        "purpose": ("str", True, None),
    })
    account = STORE.accounts[data["ordering_account_id"]]
    beneficiary = STORE.beneficiaries[data["beneficiary_id"]]
    # Priority 5: cross-aggregate consistency.
    if beneficiary["customer_id"] != account["customer_id"]:
        raise ApiError(*ERR_BENEFICIARY_ACCOUNT_MISMATCH,
                       "beneficiary.customer_id differs from the ordering account's customer_id.")
    # Priority 6: account and beneficiary active gates.
    if account["status"] != "ACTIVE":
        raise ApiError(*ERR_ACCOUNT_INACTIVE, "Ordering account is not ACTIVE.")
    if beneficiary["status"] != "ACTIVE":
        raise ApiError(*ERR_BENEFICIARY_INACTIVE, "Beneficiary is not ACTIVE.")
    # Priority 7: frozen-customer initiation gate.
    customer = STORE.customers[account["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError(*ERR_CUSTOMER_FROZEN, "A FROZEN or CLOSED customer cannot initiate wires.")

    wire = base_entity()
    amount = data["amount_cents"]
    requires_callback = amount >= CALLBACK_THRESHOLD_CENTS  # inclusive boundary
    wire.update({
        "ordering_account_id": account["id"],
        "beneficiary_id": beneficiary["id"],
        "amount_cents": amount,
        "currency": data.get("currency", "USD"),
        "method": data["method"],
        "priority": data.get("priority", "NORMAL"),
        "charge_mode": data.get("charge_mode", "OUR"),
        "purpose": data["purpose"],
        "requires_callback": requires_callback,
        "callback_status": "PENDING" if requires_callback else "NONE",
        "initiated_by": uid,
        "first_approved_by": None,
        "second_approved_by": None,
        "value_date": None,
        "status": "CALLBACK_PENDING" if requires_callback else "INITIATED",
        "screening_status": "NOT_SCREENED",
        "reservation_active": False,
        "risk_score": None,
        "fee_assessed_cents": None,
        "net_principal_cents": None,
        "executed_at": None,
        "hold_reason_code": None,
        "repair_attempts": 0,
        "_executed_dt": None,
    })
    STORE.wires[wire["id"]] = wire
    if requires_callback:
        opened = now()
        case = base_entity()
        case.update({
            "wire_id": wire["id"],
            "contact_name": None,
            "contact_phone": None,
            "outcome": None,
            "status": "OPEN",
            "opened_at": iso(opened),
            "expires_at": iso(opened + timedelta(hours=4)),
            "resolved_at": None,
        })
        STORE.callbacks[case["id"]] = case
    audit("wire.initiate", "WireTransfer", wire["id"], wire["id"],
          f"status: -> {wire['status']}", actor_user_id=uid, actor_role=role)
    return ok(pub(wire), 201)


@bp.get("/wires")
def list_wires():
    require_roles(*ALL_INTERNAL)
    for w in list(STORE.wires.values()):
        lazy_eval_wire(w)
    items = list(STORE.wires.values())
    from flask import request
    for field in ("ordering_account_id", "beneficiary_id", "status", "screening_status", "value_date"):
        v = request.args.get(field)
        if v is not None:
            items = [w for w in items if w[field] == v]
    return list_response(items)


@bp.get("/wires/<wid>")
def get_wire(wid):
    require_roles(*ALL_INTERNAL)
    wire = _get_wire(wid)
    return ok(pub(wire))


# ---------------------------------------------------------------------------
# Submission (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.post("/wires/<wid>/submit")
def submit_wire(wid):
    uid, role = require_roles("WireOperator")
    wire = _get_wire(wid)
    data = get_body()
    # Priority 3: the named business_date must identify an existing record.
    if "business_date" in data and isinstance(data["business_date"], str):
        bd = find_business_date(data["business_date"])
        if bd is None:
            raise ApiError("ERR_NOT_FOUND", 404, "The referenced business date does not exist.")
    validate_body(data, {
        "business_date": ("str", True, None),
        "waive_callback": ("bool", False, None),
    })
    bd = find_business_date(data["business_date"])
    account = STORE.accounts[wire["ordering_account_id"]]
    customer = STORE.customers[account["customer_id"]]
    # Waiver validity is classified as ERR_INVALID_REQUEST (priority 4).
    if data.get("waive_callback") is True and customer["risk_rating"] != "LOW":
        raise ApiError(*ERR_INVALID_REQUEST,
                       "waive_callback is honored only for LOW-risk customers.")
    # Priority 8: submit-time cutoff gate.
    if bd["status"] != "OPEN":
        raise ApiError(*ERR_CUTOFF_PASSED, "The named business date is not OPEN.")
    # Priority 10: state.
    if wire["status"] not in ("INITIATED", "CALLBACK_PENDING"):
        raise ApiError(*ERR_INVALID_STATE, "Only an INITIATED or CALLBACK_PENDING wire can be submitted.")
    # Honored waiver: LOW-risk customer; sets callback_status = WAIVED, audit-logged.
    if data.get("waive_callback") is True:
        if wire["callback_status"] != "WAIVED":
            wire["callback_status"] = "WAIVED"
            audit("callback.waived", "WireTransfer", wire["id"], wire["id"],
                  "callback_status -> WAIVED (LOW-risk customer waiver)",
                  actor_user_id=uid, actor_role=role)
    # Priority 11: callback-verification gate from CALLBACK_PENDING.
    if wire["status"] == "CALLBACK_PENDING" and wire["callback_status"] not in ("VERIFIED", "WAIVED"):
        raise ApiError(*ERR_CALLBACK_NOT_VERIFIED,
                       "callback_status must be VERIFIED or WAIVED before submission.")

    before = wire["status"]
    wire["status"] = "PENDING_APPROVAL"
    wire["value_date"] = data["business_date"]
    # Reservation (PRD §2.6).
    wire["reservation_active"] = True
    account["daily_reserved_cents"] += wire["amount_cents"]
    touch(account)
    # Screening + risk score.
    run_screening(wire)
    touch(wire)
    return ok(pub(wire))


# ---------------------------------------------------------------------------
# Dual approval (PRD §3.4)
# ---------------------------------------------------------------------------

def _current_round_records(wire_id):
    return [r for r in STORE.approvals.values()
            if r["wire_id"] == wire_id and not r["superseded"]]


@bp.post("/wires/<wid>/approve")
def approve_wire(wid):
    uid, role = require_roles("WireApprover")
    wire = _get_wire(wid)
    data = get_body()
    validate_body(data, {"expected_wire_version": ("int", True, None)})
    _check_occ(data, wire)
    if wire["status"] != "PENDING_APPROVAL":
        raise ApiError(*ERR_INVALID_STATE, "Only a PENDING_APPROVAL wire can be approved.")
    records = _current_round_records(wid)
    if uid == wire["initiated_by"]:
        raise ApiError(*ERR_SOD_APPROVER_MISMATCH, "The approver must not be the wire's initiator.")
    if any(r["approver_user_id"] == uid for r in records):
        raise ApiError(*ERR_SOD_APPROVER_MISMATCH,
                       "The approver already holds a non-superseded approval for the current round.")
    sequence = "FIRST" if not records else "SECOND"
    rec = base_entity()
    rec.update({
        "wire_id": wid,
        "sequence": sequence,
        "approver_user_id": uid,
        "decided_at": iso(now()),
        "superseded": False,
    })
    STORE.approvals[rec["id"]] = rec
    if sequence == "FIRST":
        wire["first_approved_by"] = uid
    else:
        wire["second_approved_by"] = uid
        wire["status"] = "APPROVED"
    touch(wire)
    audit("wire.approve", "WireTransfer", wid, wid,
          f"approval recorded (sequence {sequence})" +
          ("; status: PENDING_APPROVAL -> APPROVED" if sequence == "SECOND" else ""),
          actor_user_id=uid, actor_role=role)
    return ok(pub(wire))


@bp.post("/wires/<wid>/reject")
def reject_wire(wid):
    uid, role = require_roles("WireApprover")
    wire = _get_wire(wid)
    data = get_body()
    validate_body(data, {"reason": ("str", True, None)})
    if wire["status"] != "PENDING_APPROVAL":
        raise ApiError(*ERR_INVALID_STATE, "Only a PENDING_APPROVAL wire can be rejected.")
    wire["status"] = "REJECTED"
    release_reservation(wire)
    touch(wire)
    audit("wire.reject", "WireTransfer", wid, wid,
          "status: PENDING_APPROVAL -> REJECTED; reservation released",
          actor_user_id=uid, actor_role=role)
    return ok(pub(wire))


# ---------------------------------------------------------------------------
# Release + atomic execution (PRD §3.5)
# ---------------------------------------------------------------------------

@bp.post("/wires/<wid>/release")
def release_wire(wid):
    uid, role = require_roles("WireOperator")
    wire = _get_wire(wid)
    data = get_body()
    validate_body(data, {"expected_wire_version": ("int", True, None)})
    _check_occ(data, wire)
    if wire["status"] != "APPROVED":
        raise ApiError(*ERR_INVALID_STATE, "Only an APPROVED wire can be released.")
    if wire["hold_reason_code"] is not None:
        raise ApiError(*ERR_WIRE_ON_HOLD, "The wire carries a hold and cannot be released.")
    if wire["screening_status"] != "CLEAR":
        raise ApiError(*ERR_SANCTIONS_NOT_CLEARED, "screening_status is not CLEAR.")
    bd = find_business_date(wire["value_date"]) if wire["value_date"] else None
    if bd is None or bd["status"] != "OPEN":
        raise ApiError(*ERR_CUTOFF_PASSED, "The business date of the wire's value_date is not OPEN.")
    account = STORE.accounts[wire["ordering_account_id"]]
    # Daily-limit check at the dispatch boundary; failure aborts atomically
    # (wire stays APPROVED, reservation stays active, tallies unchanged).
    available = account["daily_outgoing_limit_cents"] - account["daily_released_cents"]
    if available < wire["amount_cents"]:
        raise ApiError(*ERR_DAILY_LIMIT_EXCEEDED, "Available daily headroom is below the wire principal.")

    # APPROVED -> RELEASING -> EXECUTED (dispatch immediate within this call).
    # Fee finalization: FINAL assessment on ACTUAL_ADVICE charges; prior OPEN
    # PROVISIONAL assessment and POSTED PROVISIONAL_ESTIMATE charges SUPERSEDED.
    for f in STORE.fees.values():
        if f["wire_id"] == wid and f["kind"] == "PROVISIONAL" and f["status"] == "OPEN":
            f["status"] = "SUPERSEDED"
            touch(f)
    for c in STORE.charges.values():
        if c["wire_id"] == wid and c["status"] == "POSTED" and c["source"] == "PROVISIONAL_ESTIMATE":
            c["status"] = "SUPERSEDED"
            touch(c)
    comp = compute_fee(wire, "FINAL")
    fee = base_entity()
    fee.update({
        "wire_id": wid,
        "base_fee_cents": comp["base_fee_cents"],
        "priority_fee_cents": comp["priority_fee_cents"],
        "beneficiary_share_cents": comp["beneficiary_share_cents"],
        "correspondent_share_cents": comp["correspondent_share_cents"],
        "total_fee_cents": comp["total_fee_cents"],
        "kind": "FINAL",
        "status": "OPEN",
    })
    STORE.fees[fee["id"]] = fee

    wire["fee_assessed_cents"] = comp["total_fee_cents"]
    wire["net_principal_cents"] = wire["amount_cents"] - posted_deducted_from_principal_cents(wid)
    wire["executed_at"] = iso(now())
    wire["_executed_dt"] = now()
    wire["status"] = "EXECUTED"
    # Reservation converts into the executed tally — principal counts exactly once.
    wire["reservation_active"] = False
    account["daily_reserved_cents"] -= wire["amount_cents"]
    account["daily_released_cents"] += wire["amount_cents"]
    if account["status"] == "DORMANT":
        account["status"] = "ACTIVE"
    touch(account)
    beneficiary = STORE.beneficiaries[wire["beneficiary_id"]]
    if beneficiary["first_used_at"] is None:
        beneficiary["first_used_at"] = iso(now())
        touch(beneficiary)
    touch(wire)
    audit("wire.execute", "WireTransfer", wid, wid,
          "status: APPROVED -> EXECUTED; reservation converted to released tally",
          actor_user_id=uid, actor_role=role)
    return ok(pub(wire))


# ---------------------------------------------------------------------------
# Cancellation (PRD §3.5)
# ---------------------------------------------------------------------------

@bp.post("/wires/<wid>/cancel")
def cancel_wire(wid):
    uid, role = require_roles("WireOperator")
    wire = _get_wire(wid)
    data = get_body()
    if data:
        raise ApiError(*ERR_INVALID_REQUEST, "This endpoint does not accept a request body.")
    if wire["status"] not in ("INITIATED", "CALLBACK_PENDING", "PENDING_APPROVAL", "REPAIR", "APPROVED"):
        raise ApiError(*ERR_INVALID_STATE, "The wire is not in a cancellable state.")
    if wire["status"] == "APPROVED" and wire["hold_reason_code"] is not None:
        raise ApiError(*ERR_WIRE_ON_HOLD, "A held wire cannot be cancelled directly.")
    before = wire["status"]
    if before == "CALLBACK_PENDING":
        for case in STORE.callbacks.values():
            if case["wire_id"] == wid and case["status"] == "OPEN":
                case["status"] = "SUPERSEDED"
                case["resolved_at"] = iso(now())
                touch(case)
        wire["callback_status"] = "NONE"
    if before in ("PENDING_APPROVAL", "REPAIR"):
        release_reservation(wire)
    wire["status"] = "CANCELLED"
    touch(wire)
    audit("wire.cancel", "WireTransfer", wid, wid,
          f"status: {before} -> CANCELLED", actor_user_id=uid, actor_role=role)
    return ok(pub(wire))


# ---------------------------------------------------------------------------
# Repair + resubmit (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.post("/wires/<wid>/repair")
def repair_wire(wid):
    uid, role = require_roles("RepairSpecialist")
    wire = _get_wire(wid)
    data = get_body()
    require_fk(data, "beneficiary_id", STORE.beneficiaries, "beneficiary")
    validate_body(data, {
        "expected_wire_version": ("int", True, None),
        "beneficiary_id": ("str", False, None),
        "amount_cents": ("posint", False, None),
        "method": ("str", False, _METHODS),
        "purpose": ("str", False, None),
    })
    _check_occ(data, wire)
    if wire["status"] != "PENDING_APPROVAL":
        raise ApiError(*ERR_INVALID_STATE, "Only a PENDING_APPROVAL wire can be repaired.")
    if wire["repair_attempts"] >= 2:
        raise ApiError(*ERR_REPAIR_LIMIT_EXCEEDED, "Repair attempt cap (2) reached.")

    old_amount = wire["amount_cents"]
    if "beneficiary_id" in data:
        wire["beneficiary_id"] = data["beneficiary_id"]
    if "amount_cents" in data:
        wire["amount_cents"] = data["amount_cents"]
    if "method" in data:
        wire["method"] = data["method"]
    if "purpose" in data:
        wire["purpose"] = data["purpose"]
    wire["repair_attempts"] += 1
    wire["requires_callback"] = wire["amount_cents"] >= CALLBACK_THRESHOLD_CENTS
    if wire["amount_cents"] != old_amount and wire["reservation_active"]:
        account = STORE.accounts[wire["ordering_account_id"]]
        account["daily_reserved_cents"] += wire["amount_cents"] - old_amount
        touch(account)
    wire["status"] = "REPAIR"
    # Re-screening: reset to NOT_SCREENED then re-evaluate; risk recomputed.
    wire["screening_status"] = "NOT_SCREENED"
    run_screening(wire)
    touch(wire)
    audit("wire.repair", "WireTransfer", wid, wid,
          "status: PENDING_APPROVAL -> REPAIR; screening re-run", actor_user_id=uid, actor_role=role)
    return ok(pub(wire))


@bp.post("/wires/<wid>/resubmit")
def resubmit_wire(wid):
    uid, role = require_roles("RepairSpecialist")
    wire = _get_wire(wid)
    data = get_body()
    if data:
        raise ApiError(*ERR_INVALID_REQUEST, "This endpoint does not accept a request body.")
    if wire["status"] != "REPAIR":
        raise ApiError(*ERR_INVALID_STATE, "Only a REPAIR wire can be resubmitted.")
    # Invalidate the prior round's approvals.
    for rec in STORE.approvals.values():
        if rec["wire_id"] == wid and not rec["superseded"]:
            rec["superseded"] = True
            touch(rec)
    wire["first_approved_by"] = None
    wire["second_approved_by"] = None
    wire["status"] = "PENDING_APPROVAL"
    touch(wire)
    audit("wire.resubmit", "WireTransfer", wid, wid,
          "status: REPAIR -> PENDING_APPROVAL; prior approvals superseded",
          actor_user_id=uid, actor_role=role)
    return ok(pub(wire))


# ---------------------------------------------------------------------------
# Approval history + computed summary
# ---------------------------------------------------------------------------

@bp.get("/wires/<wid>/approvals")
def list_approvals(wid):
    require_roles(*ALL_INTERNAL)
    _get_wire(wid)
    items = [r for r in STORE.approvals.values() if r["wire_id"] == wid]
    return list_response(items)


@bp.get("/wires/<wid>/summary")
def wire_summary(wid):
    require_roles(*ALL_INTERNAL)
    wire = _get_wire(wid)
    approvals = sum(1 for r in STORE.approvals.values()
                    if r["wire_id"] == wid and not r["superseded"])
    open_hits = sum(1 for h in STORE.sanctions_hits.values()
                    if h["wire_id"] == wid and h["status"] == "OPEN")
    open_holds = sum(1 for h in STORE.fraud_holds.values()
                     if h["wire_id"] == wid and h["status"] == "OPEN")
    recalls = sum(1 for r in STORE.recalls.values() if r["wire_id"] == wid)
    open_fees = sum(1 for f in STORE.fees.values()
                    if f["wire_id"] == wid and f["status"] == "OPEN")
    reserved = wire["amount_cents"] if wire["reservation_active"] else 0
    return ok({
        "wire": pub(wire),
        "approvals": approvals,
        "open_hits": open_hits,
        "open_holds": open_holds,
        "recalls": recalls,
        "open_fees": open_fees,
        "reserved_cents": reserved,
    })
