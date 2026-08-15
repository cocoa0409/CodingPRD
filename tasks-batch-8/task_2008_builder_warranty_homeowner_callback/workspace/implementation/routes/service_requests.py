"""Service request intake, triage, follow-up, and the dispute cycle (PRD 3.2, 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import CLOCK
from db import db, new_entity, sorted_items
from errors import (
    raise_error,
    ERR_ALREADY_TERMINAL,
    ERR_DISPUTE_DEADLINE_PASSED,
    ERR_EDUCATION_PACKET_REQUIRED,
    ERR_HOME_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_COVERED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OUT_OF_WARRANTY,
    ERR_SERVICE_REQUEST_NOT_FOUND,
)
from middleware import get_caller, require_role
from response import success_list, success_object
from services.calc import (
    CATEGORY_TIER_MAP,
    COMPLETION_SLA_DAYS,
    DISPUTE_WINDOW_DAYS,
    EXCLUDED_CATEGORIES,
    RESPONSE_SLA_HOURS,
    coverage_check,
)
from services.reserve import touch
from util import serialize
from validate import (
    apply_page,
    get_body,
    pagination_params,
    req_bool,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("service_requests", __name__)

ITEM_CATEGORIES = {
    "DRYWALL_PAINT", "FLOORING", "PLUMBING", "ELECTRICAL", "HVAC",
    "FOUNDATION", "FRAMING", "LANDSCAPING", "APPLIANCE", "ROUTINE_MAINTENANCE",
}
SEVERITIES = {"EMERGENCY", "URGENT", "STANDARD"}
DENIAL_REASON_CODES = {"OUT_OF_TERM", "EXCLUDED_CATEGORY", "HOMEOWNER_CAUSED", "NORMAL_MAINTENANCE"}
DISPUTE_OUTCOMES = {"HOMEOWNER_PREVAILS", "BUILDER_UPHELD", "SETTLED"}

SR_TERMINAL = {"CLOSED"}
READ_ROLES = {"WarrantyManager", "WarrantyRep", "FinanceAdmin", "Homeowner"}


def _get_request_or_404(rid):
    sr = db["service_requests"].get(rid)
    if sr is None:
        raise_error(ERR_SERVICE_REQUEST_NOT_FOUND, f"service request id does not resolve: {rid}")
    return sr


def _evaluate_response_sla(sr, now):
    """Both assess branches evaluate the response SLA at the assessment instant;
    late means strictly later than response_due_at (assessing exactly AT it is met)."""
    if now > sr["response_due_at"]:
        sr["response_breached"] = True
        sr["escalation_level"] = max(sr["escalation_level"], 1)


@bp.post("/service-requests")
def create_service_request():
    uid, role = get_caller()
    require_role(role, {"Homeowner"})
    body = get_body()
    # Ownership (precedence 3): an existing home not owned by the caller is refused
    # before any remaining shape checks; a missing home 404s at precedence 4.
    home_ref = body.get("home_id")
    home = db["homes"].get(home_ref) if isinstance(home_ref, str) else None
    if home is not None and home["homeowner_id"] != uid:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "a homeowner may file only against their own home")
    if isinstance(home_ref, str) and home_ref.strip() != "" and home is None:
        raise_error(ERR_HOME_NOT_FOUND, f"home id does not resolve: {home_ref}")
    home_id = req_str(body, "home_id")
    item_category = req_enum(body, "item_category", ITEM_CATEGORIES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")

    now = CLOCK.now()
    sr = new_entity()
    sr.update({
        "home_id": home_id,
        "homeowner_id": uid,  # reporter copied from X-User-ID
        "item_category": item_category,
        "severity": severity,
        "description": description,
        "reported_at": now,  # coverage is judged on this instant, and only this instant
        "status": "RECEIVED",
        "determined_tier": None,
        "denied_at": None,
        "denial_reason_code": None,
        "education_packet_code": None,
        "dispute_reason": None,
        "dispute_outcome": None,
        "dispute_deadline_at": None,
        "approved_at": None,
        "response_due_at": now + timedelta(hours=RESPONSE_SLA_HOURS[severity]),
        "completion_due_at": None,
        "response_breached": False,
        "completion_breached": False,
        "escalation_level": 0,
        "actual_cost_cents": 0,
        "followup_entered_at": None,
        "satisfaction_score": None,
        "closed_at": None,
        "reopened_count": 0,
    })
    db["service_requests"][sr["id"]] = sr
    return success_object(serialize(sr), 201)


@bp.get("/service-requests/<rid>")
def fetch_service_request(rid):
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    return success_object(serialize(_get_request_or_404(rid)))


@bp.get("/service-requests")
def list_service_requests():
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    home_id = request.args.get("home_id")
    homeowner_id = request.args.get("homeowner_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    items = sorted_items("service_requests")
    if home_id is not None:
        items = [s for s in items if s["home_id"] == home_id]
    if homeowner_id is not None:
        items = [s for s in items if s["homeowner_id"] == homeowner_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if severity is not None:
        items = [s for s in items if s["severity"] == severity]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(s) for s in page], total, limit, offset)


@bp.post("/service-requests/<rid>/assess")
def assess_service_request(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    sr = _get_request_or_404(rid)
    body = get_body()
    # Shape (precedence 5): warrantable bool; the non-warrantable branch also
    # requires a valid denial_reason_code here (its absence is ERR_INVALID_REQUEST).
    warrantable = req_bool(body, "warrantable")
    denial_reason_code = None
    if not warrantable:
        denial_reason_code = req_enum(body, "denial_reason_code", DENIAL_REASON_CODES)
    # State legality (precedence 6): CLOSED is terminal; anything other than
    # RECEIVED/REOPENED is a non-terminal wrong state.
    if sr["status"] in SR_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, "service request is CLOSED")
    if sr["status"] not in ("RECEIVED", "REOPENED"):
        raise_error(ERR_INVALID_STATE,
                    f"assess is not defined from status {sr['status']}")

    now = CLOCK.now()
    if warrantable:
        # Category check precedes the temporal check (precedence 16 before 17).
        if sr["item_category"] in EXCLUDED_CATEGORIES:
            raise_error(ERR_ITEM_NOT_COVERED,
                        f"category {sr['item_category']} is excluded from coverage")
        tier = CATEGORY_TIER_MAP[sr["item_category"]]
        home = db["homes"][sr["home_id"]]
        # Coverage is judged on the ORIGINAL reported_at, end boundary exclusive.
        if not coverage_check(sr["reported_at"], home["closing_date"], tier):
            raise_error(ERR_OUT_OF_WARRANTY,
                        "reported_at is outside the tier's half-open coverage window")
        sr["determined_tier"] = tier
        sr["approved_at"] = now
        sr["completion_due_at"] = now + timedelta(days=COMPLETION_SLA_DAYS[sr["severity"]])
        sr["status"] = "APPROVED"
    else:
        # Denial completeness (precedence 18): education ships on every denial.
        packet = body.get("education_packet_code")
        if not isinstance(packet, str) or packet.strip() == "":
            raise_error(ERR_EDUCATION_PACKET_REQUIRED,
                        "a non-warrantable determination requires education_packet_code")
        sr["denial_reason_code"] = denial_reason_code
        sr["education_packet_code"] = packet
        sr["denied_at"] = now
        sr["dispute_deadline_at"] = now + timedelta(days=DISPUTE_WINDOW_DAYS)
        sr["dispute_outcome"] = None  # re-denial from REOPENED clears any recorded outcome
        sr["status"] = "DENIED"
    _evaluate_response_sla(sr, now)
    touch(sr)
    return success_object(serialize(sr))


@bp.post("/service-requests/<rid>/follow-up")
def follow_up_service_request(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    sr = _get_request_or_404(rid)
    body = get_body()
    satisfaction_score = req_int(body, "satisfaction_score", minimum=1, maximum=5)
    if sr["status"] in SR_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, "service request is CLOSED")
    if sr["status"] != "PENDING_FOLLOWUP":
        raise_error(ERR_INVALID_STATE,
                    f"follow-up is not defined from status {sr['status']}")
    sr["satisfaction_score"] = satisfaction_score
    sr["closed_at"] = CLOCK.now()
    sr["status"] = "CLOSED"
    touch(sr)
    return success_object(serialize(sr))


@bp.post("/service-requests/<rid>/dispute")
def dispute_service_request(rid):
    uid, role = get_caller()
    require_role(role, {"Homeowner"})
    sr = db["service_requests"].get(rid)
    # Ownership (precedence 3) when the target exists; else 404 at precedence 4.
    if sr is not None and sr["homeowner_id"] != uid:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "a homeowner may dispute only their own service request")
    if sr is None:
        raise_error(ERR_SERVICE_REQUEST_NOT_FOUND,
                    f"service request id does not resolve: {rid}")
    body = get_body()
    dispute_reason = req_str(body, "dispute_reason")
    if sr["status"] in SR_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, "service request is CLOSED")
    if sr["status"] != "DENIED":
        raise_error(ERR_INVALID_STATE,
                    f"dispute is not defined from status {sr['status']}")
    now = CLOCK.now()
    # The dispute deadline is INCLUSIVE: filed exactly at the deadline is accepted.
    if now > sr["dispute_deadline_at"]:
        raise_error(ERR_DISPUTE_DEADLINE_PASSED, "the 30-day dispute window has passed")
    sr["dispute_reason"] = dispute_reason
    sr["status"] = "DISPUTED"
    touch(sr)
    return success_object(serialize(sr))


@bp.post("/service-requests/<rid>/resolve-dispute")
def resolve_dispute(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    sr = _get_request_or_404(rid)
    body = get_body()
    outcome = req_enum(body, "outcome", DISPUTE_OUTCOMES)
    req_str(body, "resolution_notes")
    if sr["status"] in SR_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, "service request is CLOSED")
    if sr["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE,
                    f"resolve-dispute is not defined from status {sr['status']}")
    now = CLOCK.now()
    if outcome == "HOMEOWNER_PREVAILS":
        # Arbitration-overturn cycle: reopen, re-anchor the response SLA, wipe
        # the coverage fields so coverage is re-assessed against original reported_at.
        sr["dispute_outcome"] = "HOMEOWNER_PREVAILS"
        sr["status"] = "REOPENED"
        sr["reopened_count"] += 1
        sr["response_due_at"] = now + timedelta(hours=RESPONSE_SLA_HOURS[sr["severity"]])
        sr["response_breached"] = False
        sr["escalation_level"] = max(sr["escalation_level"], 1)
        sr["completion_due_at"] = None
        sr["approved_at"] = None
        sr["determined_tier"] = None
    elif outcome == "BUILDER_UPHELD":
        sr["dispute_outcome"] = "BUILDER_UPHELD"
        sr["status"] = "DENIED"
        sr["denied_at"] = now
        sr["dispute_deadline_at"] = now + timedelta(days=DISPUTE_WINDOW_DAYS)
    else:  # SETTLED
        sr["dispute_outcome"] = "SETTLED"
        sr["status"] = "CLOSED"
        sr["closed_at"] = now
    touch(sr)
    return success_object(serialize(sr))
