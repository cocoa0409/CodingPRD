"""Change-in-scope requests and the depth-5 approval cascade (PRD 3.8)."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, seated_chair, segregation, state
from services import cascade
from services import fee_schedule as fs
from services import health_center as hc_svc
from validation import Field, pagination, parse_body

bp = Blueprint("scope", __name__)

MAX_SCOPE_REVISION_ROUNDS = 3

SITE_TYPES = ("ADD_SITE", "REMOVE_SITE")
SERVICE_TYPES = ("ADD_SERVICE", "REMOVE_SERVICE")

CREATE_FIELDS = [
    Field("health_center_id", "string"),
    Field(
        "request_type",
        "enum",
        required=True,
        enum=SITE_TYPES + SERVICE_TYPES,
    ),
    Field("target_site_id", "string", nullable=True),
    Field("target_service_definition_id", "string", nullable=True),
    Field("justification", "string", required=True),
]

DECIDE_FIELDS = [
    Field("decision", "enum", required=True, enum=("APPROVE", "REQUEST_REVISION", "DENY")),
    Field("decision_note", "string", nullable=True),
]


def _pairing(request_type, site_id, service_id):
    """Rung 9 — the polymorphic target pairing."""
    if request_type in SITE_TYPES:
        if site_id is None or service_id is not None:
            raise ApiError("ERR_SCOPE_TARGET_MISMATCH")
    else:
        if service_id is None or site_id is not None:
            raise ApiError("ERR_SCOPE_TARGET_MISMATCH")


def _scope_open(hc_id):
    """Rung 15."""
    if hc_svc.scope_posture(hc_id) != "OPEN":
        raise ApiError("ERR_SCOPE_CHANGE_FROZEN")


@bp.post("/health-centers/<hc_id>/scope-change-requests")
def create_request(hc_id):
    user_id = authorize("ComplianceOfficer")
    body = parse_body(CREATE_FIELDS)
    require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    site_id = body.get("target_site_id")
    service_id = body.get("target_service_definition_id")

    # Rung 7 — declared field order puts target_site_id before
    # target_service_definition_id.
    site = require("service_sites", site_id) if site_id is not None else None
    service = require("service_definitions", service_id) if service_id is not None else None

    # Rung 8 — the target must belong to the requesting grantee.
    if site is not None and site["health_center_id"] != hc_id:
        raise ApiError("ERR_CROSS_GRANTEE_REFERENCE")
    if service is not None and service["health_center_id"] != hc_id:
        raise ApiError("ERR_CROSS_GRANTEE_REFERENCE")

    # Rung 9 — pairing.
    _pairing(body["request_type"], site_id, service_id)

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "target_site_id": site_id,
            "target_service_definition_id": service_id,
            "request_type": body["request_type"],
            "justification": body["justification"],
            "status": "DRAFT",
            "revision_round": 0,
            "held_from_status": None,
            "prepared_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "decision_note": None,
        }
    )
    db.db.scope_change_requests[row["id"]] = row
    return object_response(serializers.scope_change_request(row), 201)


@bp.get("/scope-change-requests/<request_id>")
def read_request(request_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.scope_change_request(require("scope_change_requests", request_id))
    )


@bp.get("/scope-change-requests")
def list_requests():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    return listing(
        db.all_rows("scope_change_requests"),
        serializers.scope_change_request,
        limit,
        offset,
        specs=[
            ("health_center_id", "health_center_id", "string"),
            ("target_site_id", "target_site_id", "string"),
            ("target_service_definition_id", "target_service_definition_id", "string"),
            ("status", "status", "string"),
            ("request_type", "request_type", "string"),
        ],
    )


@bp.post("/scope-change-requests/<request_id>/submit")
def submit_request(request_id):
    authorize("ComplianceOfficer")
    parse_body([])
    req = require("scope_change_requests", request_id)

    # Rung 9 precedes rung 11.
    _pairing(
        req["request_type"], req.get("target_site_id"), req.get("target_service_definition_id")
    )
    state(req, "status", ("DRAFT", "REVISION_REQUESTED"))

    looping = req["status"] == "REVISION_REQUESTED"
    if looping and req["revision_round"] >= MAX_SCOPE_REVISION_ROUNDS:
        raise ApiError("ERR_LOOP_LIMIT_EXCEEDED")

    _scope_open(req["health_center_id"])

    if looping:
        req["revision_round"] += 1
    req["status"] = "SUBMITTED"
    req["reviewed_by_user_id"] = None
    db.touch(req)

    hc = db.db.health_centers.get(req["health_center_id"])
    if hc is not None:
        hc_svc.bump(hc)
    return object_response(serializers.scope_change_request(req))


@bp.post("/scope-change-requests/<request_id>/begin-review")
def begin_review(request_id):
    user_id = authorize("BoardChair")
    parse_body([])
    req = require("scope_change_requests", request_id)

    state(req, "status", ("SUBMITTED",))
    seated_chair(user_id, req["health_center_id"])
    _scope_open(req["health_center_id"])

    req["status"] = "UNDER_REVIEW"
    req["reviewed_by_user_id"] = user_id
    db.touch(req)
    return object_response(serializers.scope_change_request(req))


def _approve(req, note=None):
    hc_id = req["health_center_id"]
    hc = db.db.health_centers[hc_id]

    # Rungs 19 and 20 on the PRE-transition snapshot.
    if hc_svc.governance_posture(hc_id) != "GOVERNANCE_COMPLIANT":
        raise ApiError("ERR_GOVERNANCE_DEFICIENT")
    schedule = fs.select_schedule_for_health_center(hc_id, db.now())
    if schedule is not None and fs.review_status(schedule) == "OUT_OF_DATE":
        raise ApiError("ERR_FEE_SCHEDULE_OUT_OF_DATE")

    req["status"] = "APPROVED"
    req["decision_note"] = note
    db.touch(req)

    request_type = req["request_type"]
    voided_patients = set()

    # Hop 1 — the polymorphic target status change.
    if request_type == "ADD_SITE":
        site = db.db.service_sites.get(req["target_site_id"])
        if site is not None and site["status"] == "PROPOSED":
            site["status"] = "IN_SCOPE"
            site["in_scope_since"] = db.now()
            db.touch(site)
    elif request_type == "REMOVE_SITE":
        site = db.db.service_sites.get(req["target_site_id"])
        if site is not None and site["status"] == "IN_SCOPE":
            site["status"] = "REMOVED"
            db.touch(site)
            # Hop 3 — unbilled encounters at the departed site are voided.
            at_site = [
                e
                for e in db.db.encounters.values()
                if e["service_site_id"] == site["id"] and e["pps_claim_status"] == "UNBILLED"
            ]
            for enc in db.in_creation_order(at_site):
                cascade.void_encounter(
                    enc, "SITE_OUT_OF_SCOPE", adjustment_excludes_waiver=True
                )
                voided_patients.add(enc["patient_id"])
    elif request_type == "ADD_SERVICE":
        service = db.db.service_definitions.get(req["target_service_definition_id"])
        if service is not None and service["status"] == "PENDING":
            service["status"] = "IN_SCOPE"
            db.touch(service)
    else:  # REMOVE_SERVICE
        service = db.db.service_definitions.get(req["target_service_definition_id"])
        if service is not None and service["status"] == "IN_SCOPE":
            service["status"] = "OUT_OF_SCOPE"
            db.touch(service)

    # Hops 2 and 5 — the grantee's counters and receivable are derived, so the
    # single version increment records the whole recomputation.
    hc_svc.bump(hc)
    return voided_patients


@bp.post("/scope-change-requests/<request_id>/decide")
def decide_request(request_id):
    user_id = authorize("BoardChair")
    body = parse_body(DECIDE_FIELDS)
    req = require("scope_change_requests", request_id)

    state(req, "status", ("UNDER_REVIEW",))
    segregation(user_id, req["prepared_by_user_id"])
    seated_chair(user_id, req["health_center_id"])

    decision = body["decision"]
    note = body.get("decision_note")

    if decision == "APPROVE":
        _scope_open(req["health_center_id"])
        _approve(req, note)
    elif decision == "REQUEST_REVISION":
        req["status"] = "REVISION_REQUESTED"
        req["decision_note"] = note
        db.touch(req)
    else:
        req["status"] = "DENIED"
        req["decision_note"] = note
        db.touch(req)

    return object_response(serializers.scope_change_request(req))
