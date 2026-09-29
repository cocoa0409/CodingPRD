"""Foreign organizations, designation and the ownership graph (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import RSO, SYSTEM_ADMIN, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("organizations", __name__)


def _designated_on(data, own_designation, required_when_designated=True):
    value = validate.opt_instant(data, "designated_on")
    if own_designation == "NONE":
        return None
    if value is None and required_when_designated:
        validate.bad("Field 'designated_on' is required when a designation is set.")
    return value


@bp.post("/foreign-organizations")
def create_organization():
    require(SYSTEM_ADMIN, RSO)
    data = validate.body()

    # step 5 — body foreign keys resolve in declaration order
    parent = None
    if data.get("parent_organization_id") is not None:
        parent = must_exist("organization", data.get("parent_organization_id"))

    legal_name = validate.req_string(data, "legal_name")
    country_code = validate.req_country_code(data, "country_code")
    org_type = validate.req_enum(data, "org_type", E.ORG_TYPES)
    ownership_pct = validate.opt_decimal(data, "parent_ownership_pct",
                                        minimum=0, maximum=100,
                                        default=Decimal("0"))
    own_designation = validate.opt_enum(data, "own_designation", E.DESIGNATIONS,
                                        default="NONE")
    designated_on = _designated_on(data, own_designation)

    record = db.base_record()
    record.update({
        "legal_name": legal_name,
        "country_code": country_code,
        "org_type": org_type,
        "parent_organization_id": parent["id"] if parent else None,
        "parent_ownership_pct": ownership_pct,
        "own_designation": own_designation,
        "designated_on": designated_on,
        "effective_designation": own_designation,
        "effective_designation_depth": 0,
    })

    # step 16 — ownership-graph sanity before the row is persisted
    derive.ownership_chain(record, strict=True)

    db.organizations[record["id"]] = record
    return response.object_response(present.organization(record), 201)


@bp.get("/foreign-organizations/<organization_id>")
def read_organization(organization_id):
    require_any()
    record = must_exist("organization", organization_id)
    return response.object_response(present.organization(record))


@bp.get("/foreign-organizations")
def list_organizations():
    require_any()
    country_code = validate.filter_value("country_code")
    own_designation = validate.filter_enum("own_designation", E.DESIGNATIONS)
    effective = validate.filter_enum("effective_designation", E.DESIGNATIONS)
    parent_id = validate.filter_value("parent_organization_id")

    rows = []
    for record in db.ordered(db.organizations.values()):
        designation, _depth = derive.effective_designation(record)
        if country_code and record["country_code"] != country_code:
            continue
        if own_designation and record["own_designation"] != own_designation:
            continue
        if effective and designation != effective:
            continue
        if parent_id and record["parent_organization_id"] != parent_id:
            continue
        rows.append(record)
    return render_list(rows, present.organization)


@bp.get("/foreign-organizations/<organization_id>/subsidiaries")
def list_subsidiaries(organization_id):
    require_any()
    must_exist("organization", organization_id)
    return render_list(derive.direct_children(organization_id),
                       present.organization)


@bp.post("/foreign-organizations/<organization_id>/designate")
def designate_organization(organization_id):
    require(RSO)
    data = validate.body()
    record = must_exist("organization", organization_id)

    own_designation = validate.req_enum(data, "own_designation", E.DESIGNATIONS)
    designated_on = _designated_on(data, own_designation)
    expected = data.get("expected_organization_version")
    if expected is None:
        validate.bad("Field 'expected_organization_version' is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        validate.bad("Field 'expected_organization_version' must be an integer.")

    # step 8 — parent version match
    if expected != record["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "Organization version is %d." % record["version"])

    record["own_designation"] = own_designation
    record["designated_on"] = designated_on
    db.touch(record)
    derive.effective_designation(record)
    cascade.designation_cascade(record)
    return response.object_response(present.organization(record))


@bp.post("/foreign-organizations/<organization_id>/ownership")
def set_ownership(organization_id):
    require(RSO)
    data = validate.body()
    record = must_exist("organization", organization_id)

    if "parent_organization_id" not in data:
        validate.bad("Field 'parent_organization_id' is required.")
    parent = None
    if data.get("parent_organization_id") is not None:
        parent = must_exist("organization", data.get("parent_organization_id"))
    ownership_pct = validate.req_decimal(data, "parent_ownership_pct",
                                         minimum=0, maximum=100)

    previous_parent = record["parent_organization_id"]
    previous_pct = record["parent_ownership_pct"]
    record["parent_organization_id"] = parent["id"] if parent else None
    record["parent_ownership_pct"] = ownership_pct
    try:
        derive.ownership_chain(record, strict=True)
    except ApiError:
        record["parent_organization_id"] = previous_parent
        record["parent_ownership_pct"] = previous_pct
        raise

    db.touch(record)
    derive.effective_designation(record)
    cascade.designation_cascade(record)
    return response.object_response(present.organization(record))
