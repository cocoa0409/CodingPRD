"""Organizations (PRD 3.1)."""

import db
import serializers
from constants import ORG_TYPES
from middleware import endpoint
from routes.common import one
from services.derive import derive_standing
from validate import get_org, opt_dt, opt_int, opt_str, req_enum, req_str


@endpoint("POST", "/campus/organizations", roles=["Scheduler"], code=201)
def create_organization(ctx):
    body = ctx.body
    name = req_str(body, "name")
    org_type = req_enum(body, "org_type", ORG_TYPES)
    contact_email = req_str(body, "contact_email")
    insurance_raw, insurance_dt = opt_dt(body, "insurance_certificate_expiry")
    coverage = opt_int(body, "insurance_coverage_cents")
    row = db.new_row(
        db.organizations,
        name=name,
        org_type=org_type,
        contact_email=contact_email,
        insurance_certificate_expiry=insurance_raw,
        insurance_coverage_cents=coverage,
        no_show_count=0,
        _insurance_expiry=insurance_dt,
    )
    return one(serializers.organization(row), status=201)


@endpoint(
    "GET",
    "/campus/organizations/{id}",
    roles=["Scheduler", "FinanceAdmin", "OrgRequester"],
    code=200,
)
def get_organization(ctx):
    return one(serializers.organization(get_org(ctx.id)))


@endpoint("PATCH", "/campus/organizations/{id}", roles=["Scheduler"], code=200)
def patch_organization(ctx):
    org = get_org(ctx.id)
    body = ctx.body
    if "contact_email" in body:
        org["contact_email"] = opt_str(body, "contact_email")
    if "insurance_certificate_expiry" in body:
        raw, dt = opt_dt(body, "insurance_certificate_expiry")
        org["insurance_certificate_expiry"] = raw
        org["_insurance_expiry"] = dt
    if "insurance_coverage_cents" in body:
        org["insurance_coverage_cents"] = opt_int(body, "insurance_coverage_cents")
    db.touch(org)
    return one(serializers.organization(org))


@endpoint("POST", "/campus/organizations/{id}/reinstate", roles=["Scheduler"], code=200)
def reinstate_organization(ctx):
    org = get_org(ctx.id)
    if derive_standing(org) != "SUSPENDED":
        from errors import ApiError

        raise ApiError("ERR_INVALID_STATE", "Only a suspended organization can be reinstated.")
    org["no_show_count"] = 0
    db.touch(org)
    return one(serializers.organization(org))
