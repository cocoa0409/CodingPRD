"""Tenant practices and their compliance-case history."""

import re

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import db, stamp_new
from errors import bad_request
from lookups import get_tenant, paged
from middleware import endpoint, require_tenant_scope
from response import object_response
from services import calc

bp = Blueprint("tenants", __name__)

_NPI_RE = re.compile(r"^\d{10}$")


@bp.post("/tenants")
@endpoint("PortfolioAdmin")
def create_tenant():
    body = v.json_body()
    legal_name = v.get_string(body, "legal_name")
    affiliation = v.get_enum(body, "affiliation", enums.AFFILIATIONS)
    specialty = v.get_enum(body, "primary_specialty", enums.SPECIALTIES)
    physician_owned = v.get_bool(body, "is_physician_owned")
    npi = v.get_string(body, "npi")
    if not _NPI_RE.match(npi):
        raise bad_request("Field 'npi' must be exactly 10 digits.")

    row = {
        "legal_name": legal_name,
        "affiliation": affiliation,
        "primary_specialty": specialty,
        "is_physician_owned": physician_owned,
        "npi": npi,
        "delinquency_event_count": 0,
        "referral_compliance_risk_score": 0,
        "strict_cumulative_risk_score": 0,
        "compliance_watch_status": "CLEAR",
    }
    stamp_new(row)
    db.tenants[row["id"]] = row
    return object_response(ser.tenant_out(row), 201)


@bp.get("/tenants/<tenant_id>")
@endpoint()
def read_tenant(tenant_id):
    tenant = get_tenant(tenant_id)
    require_tenant_scope(tenant["id"])
    return object_response(ser.tenant_out(tenant))


@bp.get("/tenants/<tenant_id>/compliance-cases")
@endpoint()
def list_tenant_cases(tenant_id):
    limit, offset = v.pagination()
    status = v.query_enum("status", enums.CASE_STATUSES)
    case_type = v.query_enum("case_type", enums.CASE_TYPES)
    tenant = get_tenant(tenant_id)
    require_tenant_scope(tenant["id"])
    rows = calc.cases_of_tenant(tenant["id"])
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if case_type is not None:
        rows = [c for c in rows if c["case_type"] == case_type]
    return paged(rows, ser.compliance_case_out, limit, offset)
