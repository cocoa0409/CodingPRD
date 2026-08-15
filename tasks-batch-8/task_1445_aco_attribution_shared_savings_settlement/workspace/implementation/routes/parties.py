"""Participants, beneficiaries, and data-sharing elections."""
from flask import Blueprint, request

import db
from errors import bad_request, not_found
from middleware import require_roles, ROLE_ACO_ADMIN, ALL_DOMAIN_ROLES
from response import success, list_success
from serializers import (participant_out, beneficiary_out, election_out)
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("parties", __name__)

PARTICIPANT_SPEC = {
    "agreement_period_id": {"type": "string", "required": True},
    "tin": {"type": "string", "required": True},
    "legal_name": {"type": "string", "required": True},
    "share_weight_bp": {"type": "int", "required": True, "min": 1},
}

BENEFICIARY_SPEC = {
    "medicare_id": {"type": "string", "required": True},
    "birth_year": {"type": "int", "required": True, "min": 1000, "max": 9999},
    "dual_eligible": {"type": "bool", "required": False},
    "disabled": {"type": "bool", "required": False},
    "esrd": {"type": "bool", "required": False},
}

ELECTION_SPEC = {
    "direction": {"type": "enum", "enum": ["OPT_OUT", "OPT_IN"], "required": True},
    "effective_date": {"type": "date", "required": True},
}


@bp.post("/aco/participants")
def create_participant():
    require_roles([ROLE_ACO_ADMIN])
    body = validate_body(get_json_body(), PARTICIPANT_SPEC)
    period = db.periods.get(body["agreement_period_id"])
    if period is None:
        raise not_found("Agreement period not found")
    for existing in db.participants.values():
        if (existing["agreement_period_id"] == period["id"]
                and existing["tin"] == body["tin"]):
            raise bad_request("tin must be unique within the agreement period")
    participant = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "tin": body["tin"],
        "legal_name": body["legal_name"],
        "share_weight_bp": body["share_weight_bp"],
    })
    db.participants[participant["id"]] = participant
    return success(participant_out(participant), 201)


@bp.get("/aco/participants/<participant_id>")
def get_participant(participant_id):
    require_roles(ALL_DOMAIN_ROLES)
    participant = db.participants.get(participant_id)
    if participant is None:
        raise not_found("Participant not found")
    return success(participant_out(participant))


@bp.get("/aco/participants")
def list_participants():
    require_roles(ALL_DOMAIN_ROLES)
    items = list(db.participants.values())
    period_filter = request.args.get("agreement_period_id")
    if period_filter is not None:
        items = [p for p in items if p["agreement_period_id"] == period_filter]
    items.sort(key=lambda p: p["created_at"])
    return list_success([participant_out(p) for p in items])


@bp.post("/aco/beneficiaries")
def create_beneficiary():
    require_roles([ROLE_ACO_ADMIN])
    body = validate_body(get_json_body(), BENEFICIARY_SPEC)
    for existing in db.beneficiaries.values():
        if existing["medicare_id"] == body["medicare_id"]:
            raise bad_request("medicare_id must be globally unique")
    beneficiary = db.stamp_new({
        "id": db.new_id(),
        "medicare_id": body["medicare_id"],
        "birth_year": body["birth_year"],
        "dual_eligible": body.get("dual_eligible", False),
        "disabled": body.get("disabled", False),
        "esrd": body.get("esrd", False),
    })
    db.beneficiaries[beneficiary["id"]] = beneficiary
    return success(beneficiary_out(beneficiary), 201)


@bp.get("/aco/beneficiaries/<beneficiary_id>")
def get_beneficiary(beneficiary_id):
    require_roles(ALL_DOMAIN_ROLES)
    beneficiary = db.beneficiaries.get(beneficiary_id)
    if beneficiary is None:
        raise not_found("Beneficiary not found")
    return success(beneficiary_out(beneficiary))


def _get_beneficiary_or_404(beneficiary_id):
    beneficiary = db.beneficiaries.get(beneficiary_id)
    if beneficiary is None:
        raise not_found("Beneficiary not found")
    return beneficiary


@bp.post("/aco/beneficiaries/<beneficiary_id>/data-sharing-elections")
def create_election(beneficiary_id):
    require_roles([ROLE_ACO_ADMIN])
    beneficiary = _get_beneficiary_or_404(beneficiary_id)
    body = validate_body(get_json_body(), ELECTION_SPEC)
    election = {
        "id": db.new_id(),
        "beneficiary_id": beneficiary["id"],
        "direction": body["direction"],
        "effective_date": body["effective_date"],
        "created_at": db.next_timestamp(),
    }
    db.elections[election["id"]] = election

    # Privacy cascade: an OPT_OUT effective on or before a period's end date
    # excludes the beneficiary's live attribution records in that period and
    # stales any PROPOSED settlement there. OPT_IN never resurrects records.
    if election["direction"] == "OPT_OUT":
        affected_periods = set()
        for rec in db.attribution_records.values():
            if rec["beneficiary_id"] != beneficiary["id"]:
                continue
            if rec["status"] not in ("PROVISIONAL", "FINAL", "UNDER_APPEAL"):
                continue
            period = db.periods.get(rec["agreement_period_id"])
            if period is None:
                continue
            if election["effective_date"] <= period["performance_end_date"]:
                rec["status"] = "EXCLUDED_OPT_OUT"
                db.bump(rec)
                affected_periods.add(period["id"])
        for period_id in affected_periods:
            calc.stale_proposed_settlements(period_id)
    return success(election_out(election), 201)


@bp.get("/aco/beneficiaries/<beneficiary_id>/data-sharing-elections")
def list_elections(beneficiary_id):
    require_roles(ALL_DOMAIN_ROLES)
    beneficiary = _get_beneficiary_or_404(beneficiary_id)
    items = [e for e in db.elections.values()
             if e["beneficiary_id"] == beneficiary["id"]]
    items.sort(key=lambda e: (e["effective_date"], e["created_at"]))
    return list_success([election_out(e) for e in items])
