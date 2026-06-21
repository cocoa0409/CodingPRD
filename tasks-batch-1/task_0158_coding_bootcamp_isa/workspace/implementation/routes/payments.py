"""Payment collection lifecycle + ledger cascades (PRD §3.9)."""
from flask import Blueprint, request

import errors
from db import db, touch
from middleware import require_role
from response import success
from services import serialize
from services.common import parse_pagination, sort_by_created, paginate, lookup
from services.derive import recompute_isa_ledger

bp = Blueprint("payments", __name__)


@bp.get("/payments/<pid>")
def get_payment(pid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    p = lookup(db.payments, pid)
    return success(serialize.payment_view(p))


@bp.get("/payments")
def list_payments():
    require_role("ServicingOfficer", "ComplianceOfficer")
    limit, offset = parse_pagination()
    income_report_id = request.args.get("income_report_id")
    isa_contract_id = request.args.get("isa_contract_id")
    collection_status = request.args.get("collection_status")
    rows = list(db.payments.values())
    if income_report_id is not None:
        rows = [p for p in rows if p["income_report_id"] == income_report_id]
    if isa_contract_id is not None:
        rows = [p for p in rows if p["isa_contract_id"] == isa_contract_id]
    if collection_status is not None:
        rows = [p for p in rows if p["collection_status"] == collection_status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.payment_view(p) for p in window], pagination=pg)


def _contract_for(p):
    return db.isa_contracts.get(p["isa_contract_id"])


@bp.post("/payments/<pid>/settle")
def settle_payment(pid):
    require_role("ServicingOfficer")
    p = lookup(db.payments, pid)
    if p["collection_status"] != "PENDING":
        raise errors.invalid_state(f"Payment collection_status is {p['collection_status']}, expected PENDING")
    contract = _contract_for(p)
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.invalid_state("Linked ISA contract is not ACTIVE")

    p["collection_status"] = "SETTLED"
    touch(p)
    recompute_isa_ledger(contract)
    touch(contract)  # ledger fields advanced -> mutated resource

    # cascade on the post-settlement ledger; cap-reached takes precedence
    if contract["_amount_paid_cents"] >= contract["cap_cents"]:
        contract["status"] = "COMPLETED"
        recompute_isa_ledger(contract)  # remaining_cap_cents -> 0
        touch(contract)
        _mirror_isa_status(contract)
    elif contract["_payments_made_count"] >= contract["term_months"]:
        contract["status"] = "SETTLED_TERM"
        touch(contract)
        _mirror_isa_status(contract)

    return success(serialize.payment_view(p))


def _mirror_isa_status(contract):
    # Enrollment.isa_status is a read-time mirror of the contract status; bumping
    # the enrollment version keeps mutation semantics consistent (PRD §2.5).
    e = db.enrollments.get(contract["enrollment_id"])
    if e is not None:
        touch(e)


@bp.post("/payments/<pid>/fail")
def fail_payment(pid):
    require_role("ServicingOfficer")
    p = lookup(db.payments, pid)
    if p["collection_status"] != "PENDING":
        raise errors.invalid_state(f"Payment collection_status is {p['collection_status']}, expected PENDING")
    p["collection_status"] = "FAILED"
    touch(p)
    return success(serialize.payment_view(p))


@bp.post("/payments/<pid>/retry")
def retry_payment(pid):
    require_role("ServicingOfficer")
    p = lookup(db.payments, pid)
    if p["collection_status"] != "FAILED":
        raise errors.invalid_state(f"Payment collection_status is {p['collection_status']}, expected FAILED")
    contract = _contract_for(p)
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.invalid_state("Linked ISA contract is not ACTIVE")
    p["collection_status"] = "PENDING"
    touch(p)
    return success(serialize.payment_view(p))


@bp.post("/payments/<pid>/refund")
def refund_payment(pid):
    require_role("ServicingOfficer")
    p = lookup(db.payments, pid)
    if p["collection_status"] != "SETTLED" or p["refund_status"] != "NONE":
        raise errors.invalid_state("Payment must be SETTLED with refund_status NONE")
    contract = _contract_for(p)

    p["refund_status"] = "REFUNDED"
    touch(p)
    if contract is not None:
        recompute_isa_ledger(contract)  # excludes this now-reversed payment
        touch(contract)
        # a contract that had completed/settled-term reverts to ACTIVE
        if contract["status"] in ("COMPLETED", "SETTLED_TERM"):
            contract["status"] = "ACTIVE"
            recompute_isa_ledger(contract)
            touch(contract)
            _mirror_isa_status(contract)
    return success(serialize.payment_view(p))
