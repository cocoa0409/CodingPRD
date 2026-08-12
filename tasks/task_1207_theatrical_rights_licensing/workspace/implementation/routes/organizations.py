"""Organization routes."""
from flask import Blueprint, request

import db
from errors import err_not_found, err_invalid_request
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services.serializers import organization_out

bp = Blueprint("organizations", __name__)

ORG_KINDS = {"SCHOOL", "COMMUNITY", "SEMI_PRO", "PROFESSIONAL_COMPANY"}


@bp.post("/licensing/organizations")
def create_organization():
    require_roles("RightsAdmin")
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    if not isinstance(legal_name, str) or not legal_name:
        raise err_invalid_request("legal_name is required")
    org_kind = body.get("org_kind")
    if org_kind not in ORG_KINDS:
        raise err_invalid_request("org_kind must be SCHOOL, COMMUNITY, SEMI_PRO, or PROFESSIONAL_COMPANY")
    home_territory_code = body.get("home_territory_code")
    if not isinstance(home_territory_code, str) or not home_territory_code:
        raise err_invalid_request("home_territory_code is required")
    now = db.clock_now()
    o = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "org_kind": org_kind,
        "home_territory_code": home_territory_code,
        "standing": "GOOD",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.organizations[o["id"]] = o
    return ok_object(organization_out(o), 201)


@bp.get("/licensing/organizations/<organization_id>")
def get_organization(organization_id):
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer")
    o = db.organizations.get(organization_id)
    if not o:
        raise err_not_found("Organization not found")
    check_applicant_owner(user_id, role, o["id"])
    return ok_object(organization_out(o))


@bp.get("/licensing/organizations")
def list_organizations():
    require_roles("RightsAdmin", "LicensingOfficer", "FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    standing = request.args.get("standing")
    org_kind = request.args.get("org_kind")
    if standing is not None and standing not in ("GOOD", "SUSPENDED"):
        raise err_invalid_request("standing filter invalid")
    if org_kind is not None and org_kind not in ORG_KINDS:
        raise err_invalid_request("org_kind filter invalid")
    items = list(db.organizations.values())
    if standing is not None:
        items = [o for o in items if o["standing"] == standing]
    if org_kind is not None:
        items = [o for o in items if o["org_kind"] == org_kind]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([organization_out(o) for o in page], limit, offset, total)
