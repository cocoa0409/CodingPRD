"""SlipFallClaim endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import compute_claim_scores, _touch

bp = Blueprint("claims", __name__)

ALLOWED_CREATE_FIELDS = {"site_id", "incident_at", "severity", "description"}
VALID_SEVERITIES = {"INJURY_REPORTED", "PROPERTY_DAMAGE", "NEAR_MISS"}
DOCUMENTATION_MIN_SCORE = 60


@bp.route("/slip-fall-claims", methods=["POST"])
def create_claim():
    user_id, role = require_roles("ClientContact")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    site_id = body.get("site_id")
    incident_at = body.get("incident_at")
    severity = body.get("severity")
    description = body.get("description")

    if not site_id:
        raise ApiError(ERR_INVALID_REQUEST, "site_id is required", 400)
    site = db.sites.get(site_id)
    if not site:
        raise ApiError(ERR_NOT_FOUND, f"Site {site_id} not found", 404)
    if site.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your site", 403)

    if not incident_at:
        raise ApiError(ERR_INVALID_REQUEST, "incident_at is required", 400)
    if not severity or severity not in VALID_SEVERITIES:
        raise ApiError(ERR_INVALID_REQUEST, f"severity must be one of {', '.join(VALID_SEVERITIES)}", 400)
    if not description:
        raise ApiError(ERR_INVALID_REQUEST, "description is required", 400)

    claim = {
        "id": db._new_id(),
        "site_id": site_id,
        "incident_at": incident_at,
        "severity": severity,
        "description": description,
        "status": "FILED",
        "storm_event_id": None,
        "documentation_contract_id": None,
        "score_standard": None,
        "score_strict": None,
        "documentation_completeness_score": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.claims.create(claim)
    return success_created(claim)


def _get_claim_or_404(id):
    c = db.claims.get(id)
    if not c:
        raise ApiError(ERR_NOT_FOUND, f"Claim {id} not found", 404)
    return c


@bp.route("/slip-fall-claims/<id>", methods=["GET"])
def get_claim(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    claim = _get_claim_or_404(id)
    if role == "ClientContact":
        site = db.sites.get(claim.get("site_id"))
        if site and site.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your claim", 403)
    return success_object(claim)


@bp.route("/slip-fall-claims", methods=["GET"])
def list_claims():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    limit, offset = get_pagination()
    all_claims = db.claims.list_all()

    site_id = request.args.get("site_id")
    storm_event_id = request.args.get("storm_event_id")
    doc_contract_id = request.args.get("documentation_contract_id")
    status = request.args.get("status")
    if site_id:
        all_claims = [c for c in all_claims if c.get("site_id") == site_id]
    if storm_event_id:
        all_claims = [c for c in all_claims if c.get("storm_event_id") == storm_event_id]
    if doc_contract_id:
        all_claims = [c for c in all_claims if c.get("documentation_contract_id") == doc_contract_id]
    if status:
        all_claims = [c for c in all_claims if c.get("status") == status]
    if role == "ClientContact":
        all_claims = [c for c in all_claims if db.sites.get(c.get("site_id", ""), {}) and db.sites.get(c.get("site_id", "")).get("client_id") == user_id]

    all_claims = sorted(all_claims, key=lambda c: c.get("created_at", ""))
    total = len(all_claims)
    page = all_claims[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/slip-fall-claims/<id>/documentation-bundle", methods=["GET"])
def get_documentation_bundle(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClaimsAdjuster")
    claim = _get_claim_or_404(id)

    storm_event_id = claim.get("storm_event_id")
    site_id = claim.get("site_id")

    # Find matching visits
    matching_visits = []
    if storm_event_id:
        for v in db.visits.list_all():
            if v.get("site_id") == site_id and v.get("storm_event_id") == storm_event_id:
                matching_visits.append(v)

    visit_ids = [v["id"] for v in matching_visits]
    photo_ids = []
    material_ids = []
    for v in matching_visits:
        for p in db.photos.list_all():
            if p.get("visit_id") == v["id"]:
                photo_ids.append(p["id"])
        for m in db.materials.list_all():
            if m.get("visit_id") == v["id"]:
                material_ids.append(m["id"])

    # Weather observations
    obs_ids = []
    if storm_event_id:
        event = db.storm_events.get(storm_event_id)
        if event:
            obs_ids = event.get("verifying_observation_ids") or []

    return success_object({
        "claim_id": id,
        "documentation_contract_id": claim.get("documentation_contract_id"),
        "storm_event_id": storm_event_id,
        "matching_visit_ids": visit_ids,
        "photo_ids": photo_ids,
        "material_application_ids": material_ids,
        "weather_observation_ids": obs_ids,
        "score_standard": claim.get("score_standard"),
        "score_strict": claim.get("score_strict"),
    })


@bp.route("/slip-fall-claims/<id>/review", methods=["POST"])
def review_claim(id):
    user_id, role = require_roles("ClaimsAdjuster")
    claim = _get_claim_or_404(id)
    if claim["status"] in ("CLOSED", "WITHDRAWN"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Claim is {claim['status']} (terminal)", 409)
    if claim["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot review from {claim['status']}", 409)

    incident_at = db._parse_iso(claim.get("incident_at"))
    site_id = claim.get("site_id")

    # Find covering contract
    covering_contract = None
    for cs in db.contract_sites.list_all():
        if cs.get("site_id") != site_id:
            continue
        contract = db.contracts.get(cs.get("contract_id"))
        if not contract:
            continue
        if contract.get("status") not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
            continue
        ss = db._parse_iso(contract.get("season_start"))
        se = db._parse_iso(contract.get("season_end"))
        if ss and se and incident_at and ss <= incident_at <= se:
            covering_contract = contract
            break

    if not covering_contract:
        raise ApiError(ERR_CLAIM_WINDOW_EXPIRED, "No covering contract for this incident", 422)

    claim["documentation_contract_id"] = covering_contract["id"]

    # Link storm event containing incident_at
    linked_event = None
    for event in db.storm_events.list_all():
        ws = db._parse_iso(event.get("window_start"))
        we = db._parse_iso(event.get("window_end"))
        if ws and we and incident_at and ws <= incident_at <= we:
            # Check region match
            site = db.sites.get(site_id)
            if site and site.get("region_code") == event.get("region_code"):
                linked_event = event
                break

    claim["storm_event_id"] = linked_event["id"] if linked_event else None

    # Compute scores
    score_std, score_strict, _ = compute_claim_scores(claim)
    claim["score_standard"] = score_std
    claim["score_strict"] = score_strict
    claim["documentation_completeness_score"] = score_strict if claim.get("severity") == "INJURY_REPORTED" else score_std

    claim["status"] = "DOCUMENTATION_REVIEW"
    _touch(claim)
    db.claims.update(id, claim)
    return success_object(claim)


@bp.route("/slip-fall-claims/<id>/document", methods=["POST"])
def document_claim(id):
    user_id, role = require_roles("ClaimsAdjuster")
    claim = _get_claim_or_404(id)
    if claim["status"] in ("CLOSED", "WITHDRAWN"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Claim is {claim['status']} (terminal)", 409)
    if claim["status"] != "DOCUMENTATION_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot document from {claim['status']}", 409)

    score = claim.get("documentation_completeness_score") or 0
    if score < DOCUMENTATION_MIN_SCORE:
        raise ApiError(ERR_DOCUMENTATION_INCOMPLETE, f"Score {score} < {DOCUMENTATION_MIN_SCORE}", 422)

    claim["status"] = "DOCUMENTED"
    _touch(claim)
    db.claims.update(id, claim)
    return success_object(claim)


@bp.route("/slip-fall-claims/<id>/close", methods=["POST"])
def close_claim(id):
    user_id, role = require_roles("ClaimsAdjuster", "ClientContact")
    claim = _get_claim_or_404(id)
    if claim["status"] in ("CLOSED", "WITHDRAWN"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Claim is {claim['status']} (terminal)", 409)

    body = get_json_body()
    outcome = body.get("outcome")
    if not outcome or outcome not in ("CLOSED", "WITHDRAWN"):
        raise ApiError(ERR_INVALID_REQUEST, "outcome must be CLOSED or WITHDRAWN", 400)

    if outcome == "CLOSED":
        if role != "ClaimsAdjuster":
            raise ApiError(ERR_UNAUTHORIZED_ROLE, "Only ClaimsAdjuster can close", 403)
        if claim["status"] not in ("DOCUMENTATION_REVIEW", "DOCUMENTED"):
            raise ApiError(ERR_INVALID_STATE, f"Cannot close from {claim['status']}", 409)
        claim["status"] = "CLOSED"
    elif outcome == "WITHDRAWN":
        if role != "ClientContact":
            raise ApiError(ERR_UNAUTHORIZED_ROLE, "Only ClientContact can withdraw", 403)
        if claim["status"] not in ("FILED", "DOCUMENTATION_REVIEW"):
            raise ApiError(ERR_INVALID_STATE, f"Cannot withdraw from {claim['status']}", 409)
        # Ownership
        site = db.sites.get(claim.get("site_id"))
        if site and site.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your claim", 403)
        claim["status"] = "WITHDRAWN"

    _touch(claim)
    db.claims.update(id, claim)
    return success_object(claim)
