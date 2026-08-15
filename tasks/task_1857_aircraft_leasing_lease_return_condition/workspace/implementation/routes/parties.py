"""Lessees and inspectors."""
from flask import Blueprint, g, request

from db import STORE, base_entity, touch
from errors import ERR_FORBIDDEN, ApiError, bad_request, invalid_state, not_found
from middleware import require_roles
from response import paginated, success
from validators import get_body, req_enum, req_str

bp = Blueprint("parties", __name__)

LESSEE_STATUSES = {"ACTIVE", "SUSPENDED"}
CREDIT_TIERS = {"A", "B", "C"}

ADMIN_READ = ("LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager")


# ---------------------------------------------------------------------------
# Lessees
# ---------------------------------------------------------------------------
@bp.post("/leasing/lessees")
@require_roles("LessorAdmin")
def create_lessee():
    b = get_body()
    legal_name = req_str(b, "legal_name")
    credit_tier = b.get("credit_tier", "B")
    if credit_tier is None:
        credit_tier = "B"
    if credit_tier not in CREDIT_TIERS:
        raise bad_request("credit_tier must be one of ['A', 'B', 'C']")
    l = base_entity()
    l.update({"legal_name": legal_name, "credit_tier": credit_tier, "status": "ACTIVE"})
    STORE["lessees"][l["id"]] = l
    return success(l, status=201)


@bp.get("/leasing/lessees")
@require_roles(*ADMIN_READ)
def list_lessees():
    status_f = request.args.get("status")
    if status_f is not None and status_f not in LESSEE_STATUSES:
        raise bad_request("status filter must be one of ['ACTIVE', 'SUSPENDED']")
    items = list(STORE["lessees"].values())
    if status_f is not None:
        items = [l for l in items if l["status"] == status_f]
    items.sort(key=lambda l: l["created_at"])
    return paginated(items)


@bp.get("/leasing/lessees/<lessee_id>")
@require_roles("LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager", "LesseeRep")
def get_lessee(lessee_id):
    l = STORE["lessees"].get(lessee_id)
    if l is None:
        raise not_found("Lessee not found")
    if g.role == "LesseeRep" and g.user_id != l["id"]:
        raise ApiError(ERR_FORBIDDEN, "LesseeRep may read only its own lessee record", 403)
    return success(l)


@bp.post("/leasing/lessees/<lessee_id>/status")
@require_roles("CreditOfficer")
def set_lessee_status(lessee_id):
    l = STORE["lessees"].get(lessee_id)
    if l is None:
        raise not_found("Lessee not found")
    b = get_body()
    to = req_enum(b, "to", LESSEE_STATUSES)
    if to == "SUSPENDED":
        if l["status"] != "ACTIVE":
            raise invalid_state("Only an ACTIVE lessee can be suspended")
        l["status"] = "SUSPENDED"
    else:
        if l["status"] != "SUSPENDED":
            raise invalid_state("Only a SUSPENDED lessee can be reinstated")
        l["status"] = "ACTIVE"
    touch(l)
    return success(l)


@bp.get("/leasing/lessees/<lessee_id>/novation-requests")
@require_roles("LessorAdmin", "CreditOfficer", "LegalApprover")
def list_lessee_novation_requests(lessee_id):
    l = STORE["lessees"].get(lessee_id)
    if l is None:
        raise not_found("Lessee not found")
    items = [
        n
        for n in STORE["novation_requests"].values()
        if n["proposed_lessee_id"] == l["id"]
    ]
    items.sort(key=lambda n: n["created_at"])
    return paginated(items)


# ---------------------------------------------------------------------------
# Inspectors
# ---------------------------------------------------------------------------
@bp.post("/leasing/inspectors")
@require_roles("LessorAdmin")
def create_inspector():
    b = get_body()
    full_name = req_str(b, "full_name")
    license_number = req_str(b, "license_number")
    if any(i["license_number"] == license_number for i in STORE["inspectors"].values()):
        raise bad_request("license_number must be unique across all inspectors")
    i = base_entity()
    i.update({"full_name": full_name, "license_number": license_number})
    STORE["inspectors"][i["id"]] = i
    return success(i, status=201)


@bp.get("/leasing/inspectors/<inspector_id>")
@require_roles(
    "LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager", "TechInspector"
)
def get_inspector(inspector_id):
    i = STORE["inspectors"].get(inspector_id)
    if i is None:
        raise not_found("Inspector not found")
    return success(i)


@bp.get("/leasing/inspectors/<inspector_id>/inspection-bookings")
@require_roles(
    "LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager", "TechInspector"
)
def list_inspector_bookings(inspector_id):
    i = STORE["inspectors"].get(inspector_id)
    if i is None:
        raise not_found("Inspector not found")
    items = [
        bk
        for bk in STORE["inspection_bookings"].values()
        if bk["inspector_id"] == i["id"]
    ]
    items.sort(key=lambda bk: (bk["booking_date"], bk["created_at"]))
    return paginated(items)
