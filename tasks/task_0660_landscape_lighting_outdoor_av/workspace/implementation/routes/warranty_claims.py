"""WarrantyClaim endpoints (PRD 3.11).

Submitting a claim cascades the fixture INSTALLED->FAILED (dropping it from the
load set). Approval is gated on warranty age, computes a dual-variant credit
(FULL / DEPRECIATED), credits the customer wallet, and re-energizes the fixture
FAILED->INSTALLED. A claim may reference a fixture across the project boundary
and is NOT subject to the cross-project rule.
"""

from flask import Blueprint

from clock import clock
from common import (
    get_json_body,
    iso_format,
    paginate,
    parse_iso8601,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_fixture, get_project, get_warranty_claim
from middleware import get_auth, require_role
from response import success
from services.calc import age_months_30day, warranty_replacement_credit
from services.load import (
    recompute_project_loads,
    recompute_transformer,
    recompute_zone,
    transformer_for_zone,
)
from services.serialize import ser_warranty_claim

bp = Blueprint("warranty_claims", __name__)

READ_ROLES = {"Customer", "OperationsAdmin"}


def _recompute_fixture_loads(fixture):
    zone = db.zones.get(fixture.get("zone_id"))
    if zone is not None:
        recompute_zone(zone)
        transformer = transformer_for_zone(zone)
        if transformer is not None:
            recompute_transformer(transformer)
    project = db.projects.get(fixture["project_id"])
    if project is not None:
        recompute_project_loads(project)


@bp.post("/warranty-claims")
def submit_claim():
    _, role = get_auth()
    require_role(role, {"Customer"})
    body = get_json_body()
    require_fields(body, ["fixture_id", "project_id", "reason"])
    fixture_id = require_string(body, "fixture_id")
    project_id = require_string(body, "project_id")
    reason = require_string(body, "reason")
    # Existence of body FKs (priority 3).
    fixture = get_fixture(fixture_id)
    get_project(project_id)
    # State (6): fixture must be INSTALLED.
    if fixture["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Fixture is not INSTALLED.")

    record = stamp_new(
        {
            "fixture_id": fixture_id,
            "project_id": project_id,
            "reason": reason,
            "credit_variant": None,
            "credit_cents": 0,
            "status": "SUBMITTED",
        }
    )
    db.warranty_claims[record["id"]] = record

    # Cascade: fixture INSTALLED->FAILED; recompute loads downward.
    fixture["status"] = "FAILED"
    touch(fixture)
    _recompute_fixture_loads(fixture)

    return success(ser_warranty_claim(record), status=201)


@bp.get("/warranty-claims/<cid>")
def read_claim(cid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    c = get_warranty_claim(cid)
    return success(ser_warranty_claim(c), status=200)


@bp.get("/projects/<pid>/warranty-claims")
def list_project_claims(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [c for c in db.warranty_claims.values() if c["project_id"] == pid]
    data, pagination = paginate(items, ser_warranty_claim)
    return success(data, status=200, pagination=pagination)


@bp.get("/fixtures/<fid>/warranty-claims")
def list_fixture_claims(fid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_fixture(fid)
    items = [c for c in db.warranty_claims.values() if c["fixture_id"] == fid]
    data, pagination = paginate(items, ser_warranty_claim)
    return success(data, status=200, pagination=pagination)


@bp.post("/warranty-claims/<cid>/approve")
def approve_claim(cid):
    _, role = get_auth()
    require_role(role, {"OperationsAdmin"})
    c = get_warranty_claim(cid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED.")
    fixture = db.fixtures.get(c["fixture_id"])
    if fixture is None or fixture["status"] != "FAILED":
        raise err("ERR_INVALID_STATE", "Fixture is not FAILED.")

    # Warranty age gate (priority 13): age_months >= warranty_months is OUT.
    installed_dt = parse_iso8601(fixture.get("installed_at"))
    age = age_months_30day(clock.now(), installed_dt)
    if age >= fixture["warranty_months"]:
        raise err("ERR_OUT_OF_WARRANTY", "Fixture is out of warranty.")

    variant, credit = warranty_replacement_credit(
        fixture["purchase_price_cents"], fixture["warranty_months"], age
    )
    c["status"] = "APPROVED"
    c["credit_variant"] = variant
    c["credit_cents"] = credit
    touch(c)

    # Credit the customer's wallet.
    project = db.projects.get(c["project_id"])
    if project is not None:
        customer = db.customers.get(project["customer_id"])
        if customer is not None and credit != 0:
            customer["wallet_credit_cents"] += credit
            touch(customer)

    # Re-energize the fixture: FAILED->INSTALLED, re-stamp installed_at,
    # recompute loads upward.
    fixture["status"] = "INSTALLED"
    fixture["installed_at"] = iso_format(clock.now())
    touch(fixture)
    _recompute_fixture_loads(fixture)

    return success(ser_warranty_claim(c), status=200)


@bp.post("/warranty-claims/<cid>/deny")
def deny_claim(cid):
    _, role = get_auth()
    require_role(role, {"OperationsAdmin"})
    c = get_warranty_claim(cid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED.")
    c["status"] = "DENIED"
    touch(c)
    return success(ser_warranty_claim(c), status=200)
