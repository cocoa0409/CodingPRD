"""Service sites and scope-of-project service definitions."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, state
from services import health_center as hc_svc
from validation import Field, pagination, parse_body

bp = Blueprint("sites", __name__)

SITE_FIELDS = [
    Field("health_center_id", "string"),
    Field("site_name", "string", required=True),
    Field(
        "site_type",
        "enum",
        required=True,
        enum=("SERVICE_DELIVERY", "INTERMITTENT", "ADMINISTRATIVE"),
    ),
    Field("address_line", "string", required=True),
    Field("weekly_service_hours", "integer", required=True, minimum=0),
    Field("in_initial_scope", "boolean"),
]

SERVICE_FIELDS = [
    Field("health_center_id", "string"),
    Field("service_code", "string", required=True),
    Field("service_category", "enum", required=True, enum=("REQUIRED_PRIMARY", "ADDITIONAL")),
    Field(
        "delivery_method",
        "enum",
        required=True,
        enum=("COLUMN_I_DIRECT", "COLUMN_II_CONTRACT", "COLUMN_III_REFERRAL"),
    ),
    Field("in_initial_scope", "boolean"),
]


# --------------------------------------------------------------------------- #
# service sites
# --------------------------------------------------------------------------- #


@bp.post("/health-centers/<hc_id>/service-sites")
def create_service_site(hc_id):
    authorize("PlatformAdmin")
    body = parse_body(SITE_FIELDS)
    hc = require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    baseline = bool(body.get("in_initial_scope", False))
    if baseline and hc["scope_baseline_locked"]:
        raise ApiError("ERR_SCOPE_BASELINE_LOCKED")

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "site_name": body["site_name"],
            "site_type": body["site_type"],
            "address_line": body["address_line"],
            "weekly_service_hours": body["weekly_service_hours"],
            "status": "IN_SCOPE" if baseline else "PROPOSED",
            "in_scope_since": db.now() if baseline else None,
            "hold_reason": None,
        }
    )
    db.db.service_sites[row["id"]] = row

    if baseline:
        hc_svc.bump(hc)
    return object_response(serializers.service_site(row), 201)


@bp.get("/service-sites/<site_id>")
def read_service_site(site_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.service_site(require("service_sites", site_id)))


@bp.get("/health-centers/<hc_id>/service-sites")
def list_service_sites(hc_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("health_centers", hc_id)
    rows = db.in_creation_order(hc_svc.sites_of(hc_id))
    return listing(
        rows,
        serializers.service_site,
        limit,
        offset,
        specs=[("status", "status", "string"), ("site_type", "site_type", "string")],
    )


@bp.post("/service-sites/<site_id>/suspend")
def suspend_service_site(site_id):
    authorize("ProjectOfficer")
    parse_body([])
    site = require("service_sites", site_id)
    state(site, "status", ("IN_SCOPE",))

    site["status"] = "SUSPENDED"
    db.touch(site)

    hc = db.db.health_centers.get(site["health_center_id"])
    if hc is not None:
        hc_svc.bump(hc)
    return object_response(serializers.service_site(site))


@bp.post("/service-sites/<site_id>/reinstate")
def reinstate_service_site(site_id):
    authorize("ProjectOfficer")
    parse_body([])
    site = require("service_sites", site_id)
    state(site, "status", ("SUSPENDED",))

    site["status"] = "IN_SCOPE"
    site["in_scope_since"] = db.now()
    db.touch(site)

    hc = db.db.health_centers.get(site["health_center_id"])
    if hc is not None:
        hc_svc.bump(hc)
    return object_response(serializers.service_site(site))


# --------------------------------------------------------------------------- #
# service definitions
# --------------------------------------------------------------------------- #


@bp.post("/health-centers/<hc_id>/service-definitions")
def create_service_definition(hc_id):
    authorize("PlatformAdmin")
    body = parse_body(SERVICE_FIELDS)
    hc = require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    # Rung 29 precedes rung 38.
    for existing in hc_svc.services_of(hc_id):
        if existing["service_code"] == body["service_code"]:
            raise ApiError("ERR_DUPLICATE_CHILD_KEY")

    baseline = bool(body.get("in_initial_scope", False))
    if baseline and hc["scope_baseline_locked"]:
        raise ApiError("ERR_SCOPE_BASELINE_LOCKED")

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "service_code": body["service_code"],
            "service_category": body["service_category"],
            "delivery_method": body["delivery_method"],
            "status": "IN_SCOPE" if baseline else "PENDING",
        }
    )
    db.db.service_definitions[row["id"]] = row

    if baseline:
        hc_svc.bump(hc)
    return object_response(serializers.service_definition(row), 201)


@bp.get("/service-definitions/<service_id>")
def read_service_definition(service_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.service_definition(require("service_definitions", service_id))
    )


@bp.get("/health-centers/<hc_id>/service-definitions")
def list_service_definitions(hc_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("health_centers", hc_id)
    rows = db.in_creation_order(hc_svc.services_of(hc_id))
    return listing(
        rows,
        serializers.service_definition,
        limit,
        offset,
        specs=[
            ("status", "status", "string"),
            ("service_category", "service_category", "string"),
        ],
    )
