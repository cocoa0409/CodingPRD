"""Closing packages, escrow accounts, disbursements (PRD §3.4, §3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
from cascade import (
    ESCROW_TERMINAL,
    PACKAGE_TERMINAL,
    escrow_for_case,
    package_for_case,
    release_cascade,
    rescind_cascade,
)
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_CASE_ON_COMPLIANCE_HOLD,
    ERR_CLOSING_DOCS_INCOMPLETE,
    ERR_ESCROW_FUNDS_MISMATCH,
    ERR_ESCROW_NOT_FUNDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LICENSE_EXPIRING_SOON,
    ERR_PORTFOLIO_NOT_ASSIGNED,
    ERR_RESCISSION_WINDOW_ACTIVE,
    ERR_RESCISSION_WINDOW_EXPIRED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STATE_LICENSE_NOT_ACTIVE,
)
from middleware import (
    READ_ALL,
    auth,
    get_body,
    lookup,
    opt,
    page_args,
    req,
    require_role,
    v_int,
    v_str,
    v_str_list,
)
from response import ok, ok_list
from serialize import ser_disbursement, ser_escrow, ser_package

bp = Blueprint("closing", __name__)


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _list(items, serializer):
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(e) for e in page], len(items), limit, offset)


def _pkg_not_terminal(pkg):
    if pkg["status"] in PACKAGE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Closing package is %s" % pkg["status"])


def _escrow_not_terminal(escrow):
    if escrow["status"] in ESCROW_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Escrow account is %s" % escrow["status"])


def _case_of_package(pkg):
    return store.cases[pkg["case_id"]]


# ---------------------------------------------------------------------------
# Closing packages
# ---------------------------------------------------------------------------


@bp.get("/api/cases/<cid>/closing-package")
def case_closing_package(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list([p for p in store.packages.values() if p["case_id"] == cid], ser_package)


@bp.get("/api/closing-packages")
def list_packages():
    uid, role = auth()
    require_role(role, READ_ALL)
    items = list(store.packages.values())
    offer_id = request.args.get("offer_id")
    if offer_id is not None:
        items = [p for p in items if p["offer_id"] == offer_id]
    return _list(items, ser_package)


@bp.get("/api/closing-packages/<pid>")
def get_package(pid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_package(lookup(store.packages, pid, "ClosingPackage")))


@bp.post("/api/closing-packages/<pid>/send-for-signature")
def send_for_signature(pid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] != "ASSEMBLED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not ASSEMBLED")
    pkg["status"] = "OUT_FOR_SIGNATURE"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/record-signature")
def record_signature(pid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    body = get_body()
    doc_type = v_str(req(body, "doc_type"), "doc_type")
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] != "OUT_FOR_SIGNATURE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not OUT_FOR_SIGNATURE")
    row = next((d for d in pkg["documents"] if d["doc_type"] == doc_type), None)
    if row is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Unknown doc_type: %s" % doc_type)
    if row["signed"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Document already signed: %s" % doc_type)
    row["signed"] = True
    row["signed_at"] = store.clock
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/submit-review")
def submit_review(pid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] != "OUT_FOR_SIGNATURE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not OUT_FOR_SIGNATURE")
    if not any(d["signed"] for d in pkg["documents"]):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "At least one document must be signed")
    pkg["status"] = "COMPLIANCE_REVIEW"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/return-deficiency")
def return_deficiency(pid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    body = get_body()
    deficient = v_str_list(req(body, "deficient_doc_types"), "deficient_doc_types")
    notes = opt(body, "deficiency_notes", None)
    if notes is not None:
        notes = v_str(notes, "deficiency_notes")
    pkg = lookup(store.packages, pid, "ClosingPackage")
    known = {d["doc_type"] for d in pkg["documents"]}
    for dt in deficient:
        if dt not in known:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Unknown doc_type: %s" % dt)
    _pkg_not_terminal(pkg)
    if pkg["status"] != "COMPLIANCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not COMPLIANCE_REVIEW")
    for d in pkg["documents"]:
        if d["doc_type"] in deficient:
            d["signed"] = False
            d["signed_at"] = None
    pkg["deficiency_notes"] = notes
    pkg["status"] = "OUT_FOR_SIGNATURE"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/approve")
def approve_package(pid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] != "COMPLIANCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not COMPLIANCE_REVIEW")
    case = _case_of_package(pkg)
    if case["hold_status"] != "CLEAR":
        raise ApiError(ERR_CASE_ON_COMPLIANCE_HOLD, 409, "Case is on compliance hold")
    policy = store.policies[case["policy_id"]]
    insured = store.insureds[policy["insured_id"]]
    today = store.clock.date()
    lic = calc.governing_license(insured["state_code"], today)
    if lic is None:
        raise ApiError(ERR_STATE_LICENSE_NOT_ACTIVE, 409, "No governing ACTIVE state license")
    if lic["expiry_date"] < today + timedelta(days=calc.APPROVE_LICENSE_HORIZON_DAYS):
        raise ApiError(ERR_LICENSE_EXPIRING_SOON, 409, "Governing license expires within 30 days")
    if not all(d["signed"] for d in pkg["documents"] if d["required"]):
        raise ApiError(ERR_CLOSING_DOCS_INCOMPLETE, 422, "Required documents are unsigned")
    pkg["approved_by_user_id"] = uid
    pkg["status"] = "APPROVED"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/submit-carrier")
def submit_carrier(pid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not APPROVED")
    escrow = escrow_for_case(pkg["case_id"])
    if escrow is None or escrow["status"] != "FUNDED":
        raise ApiError(ERR_ESCROW_NOT_FUNDED, 409, "Escrow is not FUNDED")
    pkg["status"] = "CARRIER_SUBMITTED"
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/confirm-ownership")
def confirm_ownership(pid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] != "CARRIER_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package is not CARRIER_SUBMITTED")
    pkg["status"] = "OWNERSHIP_CONFIRMED"
    pkg["ownership_confirmed_at"] = store.clock
    touch(pkg)
    return ok(ser_package(pkg))


@bp.post("/api/closing-packages/<pid>/cancel")
def cancel_package(pid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    pkg = lookup(store.packages, pid, "ClosingPackage")
    _pkg_not_terminal(pkg)
    if pkg["status"] not in ("ASSEMBLED", "OUT_FOR_SIGNATURE", "COMPLIANCE_REVIEW"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Package cannot be cancelled by hand")
    escrow = escrow_for_case(pkg["case_id"])
    if escrow is None or escrow["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Escrow is no longer OPEN")
    pkg["status"] = "CANCELLED"
    touch(pkg)
    case = store.cases[pkg["case_id"]]
    offer = store.offers.get(case["accepted_offer_id"]) if case["accepted_offer_id"] else None
    case["status"] = "MARKETED"
    case["accepted_offer_id"] = None
    case["purchase_price_cents"] = None
    touch(case)
    if offer and offer["status"] == "ACCEPTED":
        offer["status"] = "WITHDRAWN"
        touch(offer)
    escrow["status"] = "CLOSED"
    touch(escrow)
    return ok(ser_package(pkg))


# ---------------------------------------------------------------------------
# Escrow accounts
# ---------------------------------------------------------------------------


@bp.get("/api/cases/<cid>/escrow-account")
def case_escrow(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list([e for e in store.escrows.values() if e["case_id"] == cid], ser_escrow)


@bp.get("/api/escrow-accounts/<eid>")
def get_escrow(eid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_escrow(lookup(store.escrows, eid, "EscrowAccount")))


@bp.post("/api/escrow-accounts/<eid>/fund")
def fund_escrow(eid):
    uid, role = auth()
    require_role(role, ["FinanceOfficer"])
    body = get_body()
    amount = v_int(req(body, "amount_cents"), "amount_cents", min_v=1)
    escrow = lookup(store.escrows, eid, "EscrowAccount")
    _escrow_not_terminal(escrow)
    if escrow["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Escrow is not OPEN")
    case = store.cases[escrow["case_id"]]
    pkg = package_for_case(case["id"])
    if pkg is None or pkg["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Closing package is not APPROVED")
    if case["hold_status"] != "CLEAR":
        raise ApiError(ERR_CASE_ON_COMPLIANCE_HOLD, 409, "Case is on compliance hold")
    if case["portfolio_id"] is None:
        raise ApiError(ERR_PORTFOLIO_NOT_ASSIGNED, 422, "Case is not assigned to a portfolio")
    if amount != escrow["expected_funding_cents"]:
        raise ApiError(ERR_ESCROW_FUNDS_MISMATCH, 422, "Fund amount does not equal expected funding")
    now = store.clock
    escrow["funded_amount_cents"] = amount
    escrow["funded_at"] = now
    escrow["releasable_at"] = now + timedelta(days=calc.RESCISSION_WINDOW_DAYS)
    escrow["balance_cents"] = amount
    escrow["status"] = "FUNDED"
    touch(escrow)
    pf = store.portfolios[case["portfolio_id"]]
    pf["invested_capital_cents"] += case["purchase_price_cents"]
    pf["holding_count"] += 1
    pf["nav_stale"] = True
    touch(pf)
    return ok(ser_escrow(escrow))


@bp.post("/api/escrow-accounts/<eid>/release")
def release_escrow(eid):
    uid, role = auth()
    require_role(role, ["FinanceOfficer"])
    get_body()
    escrow = lookup(store.escrows, eid, "EscrowAccount")
    _escrow_not_terminal(escrow)
    if escrow["status"] != "FUNDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Escrow is not FUNDED")
    case = store.cases[escrow["case_id"]]
    pkg = package_for_case(case["id"])
    if pkg is None or pkg["status"] != "OWNERSHIP_CONFIRMED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Closing package is not OWNERSHIP_CONFIRMED")
    if case["hold_status"] != "CLEAR":
        raise ApiError(ERR_CASE_ON_COMPLIANCE_HOLD, 409, "Case is on compliance hold")
    policy = store.policies[case["policy_id"]]
    insured = store.insureds[policy["insured_id"]]
    if calc.governing_license(insured["state_code"], store.clock.date()) is None:
        raise ApiError(ERR_STATE_LICENSE_NOT_ACTIVE, 409, "No governing ACTIVE state license")
    if uid == pkg["approved_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Releaser must differ from the package approver")
    if store.clock < escrow["releasable_at"]:
        raise ApiError(ERR_RESCISSION_WINDOW_ACTIVE, 409, "Rescission window is still active")
    release_cascade(escrow, case, uid)
    return ok(ser_escrow(escrow))


@bp.post("/api/escrow-accounts/<eid>/rescind")
def rescind_escrow(eid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    get_body()
    escrow = lookup(store.escrows, eid, "EscrowAccount")
    _escrow_not_terminal(escrow)
    if escrow["status"] != "FUNDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Escrow is not FUNDED")
    if store.clock >= escrow["releasable_at"]:
        raise ApiError(ERR_RESCISSION_WINDOW_EXPIRED, 409, "Rescission window has expired")
    case = store.cases[escrow["case_id"]]
    rescind_cascade(escrow, case)
    return ok(ser_escrow(escrow))


# ---------------------------------------------------------------------------
# Disbursements
# ---------------------------------------------------------------------------


@bp.get("/api/escrow-accounts/<eid>/disbursements")
def list_disbursements(eid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.escrows, eid, "EscrowAccount")
    return _list([d for d in store.disbursements.values() if d["escrow_id"] == eid], ser_disbursement)


@bp.post("/api/disbursements/<did>/mark-paid")
def mark_paid(did):
    uid, role = auth()
    require_role(role, ["FinanceOfficer"])
    disb = lookup(store.disbursements, did, "Disbursement")
    if disb["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Disbursement already SETTLED")
    escrow = store.escrows[disb["escrow_id"]]
    if escrow["status"] != "RELEASED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Escrow is not RELEASED")
    disb["status"] = "SETTLED"
    touch(disb)
    remaining = any(
        d["escrow_id"] == escrow["id"] and d["status"] == "PENDING"
        for d in store.disbursements.values()
    )
    if not remaining:
        escrow["status"] = "CLOSED"
        touch(escrow)
    return ok(ser_disbursement(disb))
