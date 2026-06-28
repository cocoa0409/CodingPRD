"""Mid-term endorsement routes (PRD §3.9, §2.7 OCC; scaffold §1.5)."""
from flask import Blueprint

from db import db, new_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_success
from serializers import public
from services.calculations import rated_coverage_premium, rider_premium
from services.lookups import (
    children_by_policy,
    get_endorsement,
    get_policy,
    total_attendance,
)
from services.policy_ops import append_ledger
from validators import (
    get_body,
    get_pagination,
    query_str,
    req_enum,
    req_int,
)

bp = Blueprint("endorsements", __name__)

ENDORSEMENT_TYPES = {"ADD_COVERAGE", "RAISE_ATTENDANCE", "ADD_RIDER"}
RIDER_TYPES = {"RINGS", "ATTIRE", "GIFTS", "SPECIAL_PROPERTY"}
COVERAGE_TYPES = {"CANCELLATION", "LIABILITY", "LIQUOR_LIABILITY"}


def _paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [public(x) for x in page], limit, offset, total


@bp.route("/policies/<policy_id>/endorsements", methods=["POST"])
def draft_endorsement(policy_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    get_policy(policy_id)
    body = get_body()

    endorsement_type = req_enum(body, "endorsement_type", ENDORSEMENT_TYPES)
    if "payload_json" not in body or not isinstance(body["payload_json"], dict):
        raise err("ERR_INVALID_REQUEST", "payload_json must be a JSON object")
    payload = body["payload_json"]

    endorsement = new_common()
    endorsement.update({
        "policy_id": policy_id,
        "endorsement_type": endorsement_type,
        "premium_delta_cents": 0,
        "payload_json": payload,
        "status": "DRAFT",
    })
    db.endorsements[endorsement["id"]] = endorsement
    return success(public(endorsement), status=201)


@bp.route("/policies/<policy_id>/endorsements", methods=["GET"])
def list_endorsements(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    f_status = query_str("status")
    items = children_by_policy(db.endorsements, policy_id)
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


@bp.route("/policies/<policy_id>/endorsements/<endorsement_id>/apply", methods=["POST"])
def apply_endorsement(policy_id, endorsement_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    policy = get_policy(policy_id)
    endorsement = get_endorsement(policy_id, endorsement_id)
    body = get_body()
    expected_policy_version = req_int(body, "expected_policy_version")

    # State precondition.
    if endorsement["status"] != "DRAFT":
        raise err("ERR_ENDORSEMENT_NOT_DRAFT", "endorsement is not DRAFT")
    if policy["lifecycle_status"] not in ("BOUND", "IN_FORCE"):
        raise err("ERR_POLICY_NOT_BOUND", "policy is not BOUND/IN_FORCE")

    # OCC check (PRD §2.7).
    if expected_policy_version != policy["version"]:
        raise err("ERR_STALE_POLICY_VERSION", "expected_policy_version does not match policy version")

    delta = _apply_payload(policy, endorsement)

    endorsement["premium_delta_cents"] = delta
    endorsement["status"] = "APPLIED"

    policy["total_premium_cents"] += delta

    append_ledger(policy_id, "ENDORSEMENT_CHARGE", delta)
    touch(policy)
    touch(endorsement)
    return success(public(endorsement), status=200)


def _apply_payload(policy, endorsement):
    """Carry out the payload change and return premium_delta_cents (PRD §3.9)."""
    policy_id = policy["id"]
    etype = endorsement["endorsement_type"]
    payload = endorsement["payload_json"]

    if etype == "ADD_COVERAGE":
        coverage_product_id = payload.get("coverage_product_id")
        if not isinstance(coverage_product_id, str):
            raise err("ERR_INVALID_REQUEST", "payload_json.coverage_product_id required")
        product = db.coverage_products.get(coverage_product_id)
        if product is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "coverage_product_id does not resolve")
        protected_vendor_id = payload.get("protected_vendor_id")
        attendance = total_attendance(policy_id)
        rated = rated_coverage_premium(product, attendance)
        coverage = new_common()
        coverage.update({
            "policy_id": policy_id,
            "coverage_product_id": coverage_product_id,
            "protected_vendor_id": protected_vendor_id if isinstance(protected_vendor_id, str) else None,
            "rated_premium_cents": rated,
            "consumed_limit_cents": 0,
            "status": "ACTIVE",
        })
        db.coverages[coverage["id"]] = coverage
        return rated

    if etype == "ADD_RIDER":
        rider_type = payload.get("rider_type")
        scheduled_value_cents = payload.get("scheduled_value_cents")
        if rider_type not in RIDER_TYPES:
            raise err("ERR_INVALID_REQUEST", "payload_json.rider_type invalid")
        if not isinstance(scheduled_value_cents, int) or isinstance(scheduled_value_cents, bool) or scheduled_value_cents <= 0:
            raise err("ERR_INVALID_REQUEST", "payload_json.scheduled_value_cents must be a positive integer")
        premium = rider_premium(scheduled_value_cents)
        rider = new_common()
        rider.update({
            "policy_id": policy_id,
            "rider_type": rider_type,
            "scheduled_value_cents": scheduled_value_cents,
            "rider_premium_cents": premium,
            "status": "ACTIVE",
        })
        db.riders[rider["id"]] = rider
        return premium

    # RAISE_ATTENDANCE
    event_profile_id = payload.get("event_profile_id")
    new_attendance = payload.get("new_attendance")
    if not isinstance(new_attendance, int) or isinstance(new_attendance, bool) or new_attendance < 1:
        raise err("ERR_INVALID_REQUEST", "payload_json.new_attendance must be a positive integer")
    profile = None
    policy_profiles = children_by_policy(db.event_profiles, policy_id)
    if isinstance(event_profile_id, str):
        # When the payload names an event profile, it must resolve to one on this policy.
        candidate = db.event_profiles.get(event_profile_id)
        if candidate is not None and candidate["policy_id"] == policy_id:
            profile = candidate
        if profile is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "event_profile_id does not resolve")
    elif len(policy_profiles) == 1:
        # The PRD declares the RAISE_ATTENDANCE payload as a bare attendance figure;
        # when the policy has a single event profile it is unambiguously "the named
        # event profile" whose attendance is raised.
        profile = policy_profiles[0]
    else:
        raise err("ERR_REFERENCE_NOT_FOUND", "event_profile_id does not resolve")

    old_total = total_attendance(policy_id)
    profile["expected_attendance"] = new_attendance
    touch(profile)
    new_total = total_attendance(policy_id)

    delta = 0
    for c in children_by_policy(db.coverages, policy_id):
        if c["status"] == "ACTIVE":
            product = db.coverage_products[c["coverage_product_id"]]
            delta += product["per_guest_premium_cents"] * (new_total - old_total)
    return delta


@bp.route("/policies/<policy_id>/endorsements/<endorsement_id>/reject", methods=["POST"])
def reject_endorsement(policy_id, endorsement_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    get_policy(policy_id)
    endorsement = get_endorsement(policy_id, endorsement_id)
    if endorsement["status"] != "DRAFT":
        raise err("ERR_ENDORSEMENT_NOT_DRAFT", "endorsement is not DRAFT")
    endorsement["status"] = "REJECTED"
    touch(endorsement)
    return success(public(endorsement), status=200)
