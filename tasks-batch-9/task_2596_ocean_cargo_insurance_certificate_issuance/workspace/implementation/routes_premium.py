"""Premium declarations: the reporting sweep, the reconciliation and the audit fork."""
from decimal import Decimal

from flask import Blueprint

import clock
import serialize
import services
from errors import ApiError, require_state
from response import array_response, object_response
from store import db, new_row, ordered, touch
from validation import (D, authenticate, body, get_decimal, get_dt, get_str, pagination,
                        paginate, q2, query_enum, query_str)

bp = Blueprint("premium", __name__)

DECLARATION_STATUSES = ("OPEN", "SUBMITTED", "UNDER_AUDIT", "ACCEPTED", "ADJUSTED")
READ_ROLES = ("Assured", "PremiumAuditor", "Underwriter", "ComplianceOfficer", "PlatformAdmin")


@bp.post("/premium-declarations")
def create_declaration():
    user_id, _role = authenticate(("Assured",))
    payload = body()
    open_policy_id = get_str(payload, "open_policy_id")
    period_start = get_dt(payload, "period_start")
    period_end = get_dt(payload, "period_end")
    policy = services.find(db.open_policies, open_policy_id, "ERR_POLICY_NOT_FOUND")
    if user_id != policy["id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    if not (period_end > period_start):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'period_end' must be strictly later than 'period_start'.")
    for other in db.premium_declarations.values():
        if other["open_policy_id"] != policy["id"]:
            continue
        if period_start < other["period_end"] and period_end > other["period_start"]:
            raise ApiError("ERR_DECLARATION_PERIOD_OVERLAP")

    row = new_row()
    row.update({
        "open_policy_id": policy["id"],
        "period_start": period_start,
        "period_end": period_end,
        "declared_premium_total": None,
        "computed_premium_total": None,
        "certificate_count": 0,
        "variance_amount": None,
        "variance_pct": None,
        "audit_adjustment_amount": Decimal("0.00"),
        "submitted_by_user_id": None,
        "auditor_user_id": None,
        "submission_count": 0,
        "status": "OPEN",
        "audit_note": None,
    })
    db.premium_declarations[row["id"]] = row
    return object_response(serialize.premium_declaration(row), 201)


@bp.get("/premium-declarations/<declaration_id>")
def read_declaration(declaration_id):
    authenticate(READ_ROLES)
    declaration = services.find(db.premium_declarations, declaration_id,
                                "ERR_DECLARATION_NOT_FOUND")
    return object_response(serialize.premium_declaration(declaration))


@bp.get("/premium-declarations")
def list_declarations():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    open_policy_id = query_str("open_policy_id")
    status = query_enum("status", DECLARATION_STATUSES)
    rows = [r for r in db.premium_declarations.values()
            if (open_policy_id is None or r["open_policy_id"] == open_policy_id)
            and (status is None or r["status"] == status)]
    page, limit, offset, total = paginate(ordered(rows), limit, offset,
                                         serialize.premium_declaration)
    return array_response(page, limit, offset, total)


@bp.post("/premium-declarations/<declaration_id>/submit")
def submit_declaration(declaration_id):
    user_id, _role = authenticate(("Assured",))
    payload = body()
    declared_total = get_decimal(payload, "declared_premium_total", minimum=0)
    declaration = services.find(db.premium_declarations, declaration_id,
                                "ERR_DECLARATION_NOT_FOUND")
    if user_id != declaration["open_policy_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    require_state("PremiumDeclaration", "status", declaration["status"], ("OPEN", "ADJUSTED"))
    policy = db.open_policies[declaration["open_policy_id"]]
    if policy["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")

    # the reporting sweep: claim every unreported certificate issued inside the window
    for cert in services.certificates_of_policy(policy["id"]):
        if cert["premium_declaration_id"] is not None or cert["issued_at"] is None:
            continue
        if declaration["period_start"] <= cert["issued_at"] < declaration["period_end"]:
            cert["premium_declaration_id"] = declaration["id"]
            touch(cert)

    declaration["declared_premium_total"] = declared_total
    services.reconcile_declaration(declaration)
    declaration["status"] = "SUBMITTED"
    declaration["submitted_by_user_id"] = user_id
    declaration["submission_count"] += 1
    declaration["auditor_user_id"] = None
    touch(declaration)

    if (policy["status"] == "SUSPENDED"
            and D(declaration["variance_pct"]) <= services.DECLARATION_AUDIT_TOLERANCE_PCT):
        policy["status"] = "ACTIVE"
        touch(policy)
    return object_response(serialize.premium_declaration(declaration))


@bp.post("/premium-declarations/<declaration_id>/start-audit")
def start_audit(declaration_id):
    user_id, _role = authenticate(("PremiumAuditor",))
    declaration = services.find(db.premium_declarations, declaration_id,
                                "ERR_DECLARATION_NOT_FOUND")
    if user_id == declaration["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    require_state("PremiumDeclaration", "status", declaration["status"], ("SUBMITTED",))
    declaration["status"] = "UNDER_AUDIT"
    declaration["auditor_user_id"] = user_id
    touch(declaration)
    return object_response(serialize.premium_declaration(declaration))


@bp.post("/premium-declarations/<declaration_id>/finish-audit")
def finish_audit(declaration_id):
    user_id, _role = authenticate(("PremiumAuditor",))
    payload = body()
    audit_note = get_str(payload, "audit_note", required=False)
    declaration = services.find(db.premium_declarations, declaration_id,
                                "ERR_DECLARATION_NOT_FOUND")
    require_state("PremiumDeclaration", "status", declaration["status"], ("UNDER_AUDIT",))
    if user_id != declaration["auditor_user_id"]:
        raise ApiError("ERR_INVALID_STATE")

    if audit_note is not None:
        declaration["audit_note"] = audit_note
    variance_pct = D(declaration["variance_pct"] or 0)
    policy = db.open_policies[declaration["open_policy_id"]]
    if variance_pct <= services.DECLARATION_AUDIT_TOLERANCE_PCT:
        declaration["status"] = "ACCEPTED"
        declaration["audit_adjustment_amount"] = Decimal("0.00")
    else:
        declaration["status"] = "ADJUSTED"
        declaration["audit_adjustment_amount"] = q2(abs(D(declaration["variance_amount"])))
        if (variance_pct > services.DECLARATION_SUSPENSION_PCT
                and policy["status"] == "ACTIVE"):
            policy["status"] = "SUSPENDED"
            touch(policy)
    touch(declaration)
    return object_response(serialize.premium_declaration(declaration))
