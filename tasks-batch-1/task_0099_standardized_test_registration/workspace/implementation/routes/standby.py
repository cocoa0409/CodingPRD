"""StandbyEntry routes: join, get, list, claim, decline."""
from flask import Blueprint, request

from db import store, stamp_create, touch
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_SESSION_VERSION, ERR_OFFER_NO_LONGER_VALID)
from middleware import require_roles
from response import object_response, array_response
from services import lookups, serializers
from services.common import (get_json_body, require_fields, require_enum,
                             parse_pagination, paginate, sort_by_created_at,
                             parse_iso_dt)
from services import calculations as calc
from services import engine

bp = Blueprint("standby", __name__)

PRIORITY_TIERS = {"FEE_WAIVER", "SCHOOL_DAY", "GENERAL"}


@bp.route("/standby-entries", methods=["POST"])
@require_roles("Candidate")
def create_standby():
    body = get_json_body()
    require_fields(body, ["test_session_id", "candidate_id", "priority_tier"])

    session = lookups.test_session(body["test_session_id"])
    candidate = lookups.candidate(body["candidate_id"])
    priority_tier = require_enum(body["priority_tier"], PRIORITY_TIERS, "priority_tier")

    entry = {
        "test_session_id": session["id"],
        "candidate_id": candidate["id"],
        "priority_tier": priority_tier,
        "promoted_from_entry_id": None,
        "promotion_score": 0,
        "offered_registration_id": None,
        "status": "WAITING",
    }
    stamp_create(entry)
    # Compute promotion_score on creation.
    clock_now = store.get_clock_now()
    created = parse_iso_dt(entry["created_at"])
    entry["promotion_score"] = calc.standby_promotion_score(
        priority_tier, created, clock_now)
    store.standby_entries[entry["id"]] = entry
    return object_response(serializers.standby_entry(entry), 201)


@bp.route("/standby-entries/<eid>", methods=["GET"])
@require_roles("Candidate", "TestCenterAdmin")
def get_standby(eid):
    entry = lookups.standby_entry(eid)
    return object_response(serializers.standby_entry(entry), 200)


@bp.route("/standby-entries", methods=["GET"])
@require_roles("Candidate", "TestCenterAdmin")
def list_standby():
    limit, offset = parse_pagination()
    test_session_id = request.args.get("test_session_id")
    candidate_id = request.args.get("candidate_id")
    promoted_from_entry_id = request.args.get("promoted_from_entry_id")
    offered_registration_id = request.args.get("offered_registration_id")
    status = request.args.get("status")

    items = list(store.standby_entries.values())
    if test_session_id is not None:
        items = [e for e in items if e["test_session_id"] == test_session_id]
    if candidate_id is not None:
        items = [e for e in items if e["candidate_id"] == candidate_id]
    if promoted_from_entry_id is not None:
        items = [e for e in items if e["promoted_from_entry_id"] == promoted_from_entry_id]
    if offered_registration_id is not None:
        items = [e for e in items if e["offered_registration_id"] == offered_registration_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]

    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.standby_entry(e) for e in page],
                          limit, offset, total, 200)


@bp.route("/standby-entries/<eid>/claim", methods=["POST"])
@require_roles("Candidate")
def claim_standby(eid):
    entry = lookups.standby_entry(eid)
    body = get_json_body()
    require_fields(body, ["expected_test_session_version"])
    expected_version = body["expected_test_session_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_test_session_version must be an integer")

    session = lookups.test_session(entry["test_session_id"])
    center = lookups.test_center(session["test_center_id"])

    # OCC (priority 5).
    if expected_version != session["version"]:
        raise err(ERR_STALE_SESSION_VERSION,
                  "expected_test_session_version does not match current session version")

    # State validity (priority 6): entry must be OFFERED.
    if entry["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Standby entry is not OFFERED")

    # Offer still valid (priority 16): offer-hold registration still RESERVED.
    offer_reg = store.registrations.get(entry["offered_registration_id"])
    if offer_reg is None or offer_reg["lifecycle_status"] != "RESERVED":
        raise err(ERR_OFFER_NO_LONGER_VALID,
                  "The offer-hold registration is no longer valid")

    # Settlement: entry CLAIMED; hold reg CONFIRMED; capture fee.
    entry["status"] = "CLAIMED"
    touch(entry)

    offer_reg["lifecycle_status"] = "CONFIRMED"
    offer_reg["amount_paid_cents"] = session["base_fee_cents"]
    touch(offer_reg)

    center["net_revenue_cents"] += session["base_fee_cents"]
    touch(center)

    # Bump version (settles the OCC token).
    engine.bump_session_version(session)

    return object_response(serializers.standby_entry(entry), 200)


@bp.route("/standby-entries/<eid>/decline", methods=["POST"])
@require_roles("Candidate")
def decline_standby(eid):
    entry = lookups.standby_entry(eid)
    session = lookups.test_session(entry["test_session_id"])

    # State validity: must be OFFERED.
    if entry["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Standby entry is not OFFERED")

    entry["status"] = "DECLINED"
    touch(entry)

    # Cancel the offer-hold registration (no refund, unpaid).
    offer_reg = store.registrations.get(entry["offered_registration_id"])
    if offer_reg is not None and offer_reg["lifecycle_status"] == "RESERVED":
        offer_reg["lifecycle_status"] = "CANCELLED"
        touch(offer_reg)
        # Release the held seat + version bump.
        engine.remove_standard_seat(session)

    # CASCADE: promote next top-ranked WAITING entry, recording this entry as the
    # promoted_from_entry_id of the next one.
    engine.promote_top_standby(session, promoted_from_entry_id=entry["id"])

    return object_response(serializers.standby_entry(entry), 200)
