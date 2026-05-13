"""Tax event routes."""

from flask import Blueprint, request, g as flask_g
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_INSUFFICIENT_PERMISSIONS,
)
from services.common import (
    init_append_only, bump_version, get_body, get_or_404,
    get_pagination, paginate_list, sort_by_created_at_asc,
    require_enum,
)
from services.serializers import serialize_tax_event
from services.calculations import compute_tax_for_event
from services.audit import append_audit


bp = Blueprint("tax_events", __name__)


EVENT_TYPES = {"GRANT", "VEST", "EXERCISE", "SALE"}


@bp.post("/grants/<grant_id>/tax-events")
@auth_required(["PlanAdministrator"])
def create_tax_event(grant_id):
    grant = get_or_404("grants", grant_id)
    plan = DB["option_plans"].get(grant["plan_id"])
    grantee = DB["grantees"].get(grant["grantee_id"])
    body = get_body()
    event_type = require_enum(body, "event_type", EVENT_TYPES)

    kwargs = {}
    if event_type == "SALE":
        sale = body.get("sale_proceeds_cents")
        cost = body.get("cost_basis_cents")
        qty = body.get("sold_quantity")
        if (not isinstance(sale, int) or isinstance(sale, bool) or sale < 0
                or not isinstance(cost, int) or isinstance(cost, bool) or cost < 0
                or not isinstance(qty, int) or isinstance(qty, bool) or qty < 1):
            raise_error(ERR_INVALID_REQUEST, "sale fields must be non-negative integers with sold_quantity>=1")
        kwargs.update(dict(
            sale_proceeds_cents=sale,
            cost_basis_cents=cost,
            sold_quantity=qty,
        ))
    elif event_type == "VEST":
        tranche = body.get("tranche_quantity") or 0
        kwargs["tranche_quantity"] = int(tranche)

    taxable, withheld, deferred = compute_tax_for_event(
        plan, grant, grantee, event_type, **kwargs,
    )

    teid = new_id()
    te = {
        "id": teid,
        "grant_id": grant_id,
        "exercise_application_id": None,
        "event_type": event_type,
        "taxable_amount_cents": taxable,
        "withheld_amount_cents": withheld,
        "deferred": deferred,
        "jurisdiction_code": plan["jurisdiction_code"],
        "document_id": None,
        "event_ts": plan.get("current_clock_ts"),
        "payload_summary": {
            k: v for k, v in body.items()
            if k in ("deferral_approved", "sale_proceeds_cents", "cost_basis_cents", "sold_quantity", "tranche_quantity")
        },
    }
    init_append_only(te)
    DB["tax_events"][teid] = te
    return success_response(serialize_tax_event(te), http_status=201)


@bp.get("/grants/<grant_id>/tax-events")
@auth_required(["PlanAdministrator", "Grantee", "AuditViewer"])
def list_tax_events(grant_id):
    grant = get_or_404("grants", grant_id)
    if flask_g.user_role == "Grantee":
        grantee = DB["grantees"].get(grant["grantee_id"])
        if not grantee or grantee["hr_employee_id"] != flask_g.user_id:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "Grantee may only read own")
    limit, offset = get_pagination()
    items = [t for t in DB["tax_events"].values() if t["grant_id"] == grant_id]
    et = request.args.get("event_type")
    if et:
        items = [t for t in items if t["event_type"] == et]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_tax_event(t) for t in sliced], total, limit, offset)


@bp.post("/tax-events/<event_id>/issue-document")
@auth_required(["PlanAdministrator"])
def issue_document(event_id):
    te = get_or_404("tax_events", event_id)
    te["document_id"] = new_id()
    grant = DB["grants"].get(te["grant_id"])
    plan = DB["option_plans"].get(grant["plan_id"]) if grant else None
    if plan:
        append_audit(plan, "EXERCISE_SETTLED", "TaxEventRecord", event_id,
                     {"event": "DOCUMENT_ISSUED", "document_id": te["document_id"]})
    return success_response(serialize_tax_event(te))
