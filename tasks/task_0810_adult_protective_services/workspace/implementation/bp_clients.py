"""Clients: registration, capacity determination, risk assessment (PRD 3.1, 3.3)."""
from flask import Blueprint

from store import store
from errors import ApiError
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, require_int,
                     check_enum, resolve, base_fields, touch, serialize)
from calc import risk_score

bp = Blueprint("clients", __name__)

DETERMINATIONS = {"INTACT", "IMPAIRED"}
ASSESSMENT_TYPES = {"PRELIMINARY", "COMPREHENSIVE"}


@bp.post("/clients")
def create_client():
    uid, role = authenticate()
    authorize(role, {"IntakeWorker"})
    body = get_body()
    full_name = require_str(body, "full_name")
    date_of_birth = require_str(body, "date_of_birth")
    address = require_str(body, "address")

    client = base_fields()
    client.update({
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "address": address,
        "capacity_status": "UNKNOWN",
        "status": "INTAKE",
        "placement_status": "NONE",
        "risk_level": None,
        "preliminary_risk_score": None,
        "comprehensive_risk_score": None,
        "open_case_count": 0,
    })
    store.clients[client["id"]] = client
    return success(serialize(client, "client")), 201


@bp.get("/clients/<cid>")
def get_client(cid):
    uid, role = authenticate()
    authorize(role, {"IntakeWorker", "Supervisor", "Caseworker"})
    client = resolve("client", cid)
    return success(serialize(client, "client")), 200


@bp.post("/clients/<cid>/capacity-determination")
def capacity_determination(cid):
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    client = resolve("client", cid)
    body = get_body()
    determination = require_str(body, "determination")
    check_enum(determination, DETERMINATIONS)
    client["capacity_status"] = determination
    touch(client)  # increments version by one
    return success(serialize(client, "client")), 200


@bp.post("/clients/<cid>/risk-assessments")
def risk_assessment(cid):
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    client = resolve("client", cid)
    body = get_body()
    assessment_type = require_str(body, "assessment_type")
    isolation = require_int(body, "isolation_level")
    cognitive = require_int(body, "cognitive_impairment_level")
    financial = require_int(body, "financial_vulnerability_level")
    caregiver = require_int(body, "caregiver_dependency_level")
    prior = require_int(body, "prior_report_count")
    expected = require_int(body, "expected_client_version")
    check_enum(assessment_type, ASSESSMENT_TYPES)
    # Optimistic concurrency (PRD 2.7): the submitted expected_client_version must
    # equal the client's current version.
    if expected != client["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION", "Stale client version", 412)

    score, tier = risk_score(isolation, cognitive, financial, caregiver, prior)

    if assessment_type == "PRELIMINARY":
        client["preliminary_risk_score"] = score
        # Preliminary does not set risk_level, does not mirror, does not bump version.
        touch(client, bump_version=False)
    else:  # COMPREHENSIVE
        client["comprehensive_risk_score"] = score
        client["risk_level"] = tier
        touch(client)  # authoritative write; bumps version under OCC
        for case in store.cases.values():
            if case["client_id"] == client["id"] and case["status"] != "CLOSED":
                case["risk_level"] = tier
                touch(case)

    return success(serialize(client, "client")), 200
