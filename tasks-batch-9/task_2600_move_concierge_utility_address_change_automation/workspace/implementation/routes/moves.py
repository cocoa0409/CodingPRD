"""Move intake, reads, readiness and the move-scoped workflow operations."""

from datetime import timedelta

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    FEED_INTEGRATOR,
    MOVE_OPS_AGENT,
    RESIDENT,
    authenticate,
)
from services import cascades, derive, duplicates, enums, gates, mapping
from services.lookup import (
    filings_of_move,
    move_or_404,
    orders_of_move,
    ref_address,
    ref_feed_source,
    ref_move,
    ref_resident,
    verifications_of_move,
)

bp = Blueprint("moves", __name__)


# ------------------------------------------------------------------- intake
@bp.post("/moves")
def create_move():
    caller = authenticate(FEED_INTEGRATOR, MOVE_OPS_AGENT)
    body = v.body()

    # rung 4: body references resolve before anything else about the body.
    resident = ref_resident(v.id_field(body, "resident_id", required=False))
    feed_source = ref_feed_source(v.id_field(body, "feed_source_id", required=False))
    origin = ref_address(v.id_field(body, "origin_address_id", required=False))
    destination = ref_address(v.id_field(body, "destination_address_id", required=False))

    # rung 5: a FeedIntegrator may only ingest against its own feed.
    caller.own_if(
        FEED_INTEGRATOR, feed_source["id"] if feed_source else caller.user_id
    )

    # rung 6: shape.
    if resident is None:
        v.bad("Field 'resident_id' is required.")
    if feed_source is None:
        v.bad("Field 'feed_source_id' is required.")
    if origin is None:
        v.bad("Field 'origin_address_id' is required.")
    if destination is None:
        v.bad("Field 'destination_address_id' is required.")
    move_date_text, move_date = v.date_field(body, "move_date")
    external_reference = v.str_field(
        body, "external_reference", required=False, min_len=1, max_len=200, default=None
    )
    if origin["id"] == destination["id"]:
        v.bad("origin_address_id and destination_address_id must differ.")

    # rung 26 then rung 29.
    gates.require_feed_active(feed_source)
    gates.require_move_date_in_range(move_date)

    move = db.base_record()
    move.update(
        {
            "resident_id": resident["id"],
            "feed_source_id": feed_source["id"],
            "origin_address_id": origin["id"],
            "destination_address_id": destination["id"],
            "duplicate_of_move_id": None,
            "reactivation_candidate_move_id": None,
            "move_date": move_date_text,
            "external_reference": external_reference,
            "lifecycle_status": "INTAKE",
            "duplicate_flag": "NONE",
            "duplicate_match_score": db.round_money("0", 2),
            "duplicate_candidate_move_id": None,
            "consent_gate": "OPEN",
            "blocked_reason": "NONE",
            "readiness_score": 0,
            "verified_at": None,
            "identity_attempt_count": 0,
            "mapped_order_count": 0,
            "unmapped_utility_types": [],
            "cancellation_reason": None,
        }
    )
    db.db.moves[move["id"]] = move

    # Duplicate detection runs immediately after the row is written.
    duplicates.evaluate(move, feed_source)
    derive.recompute(move)
    return response.created(db.public(move))


@bp.get("/moves/<move_id>")
def read_move(move_id):
    caller = authenticate(FEED_INTEGRATOR, MOVE_OPS_AGENT, COMPLIANCE_OFFICER, RESIDENT)
    move = move_or_404(move_id)
    caller.own_if(FEED_INTEGRATOR, move["feed_source_id"])
    caller.own_if(RESIDENT, move["resident_id"])
    return response.ok(db.public(move))


@bp.get("/moves")
def list_moves():
    authenticate(FEED_INTEGRATOR, MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    rows = response.match_filters(
        db.db.moves.values(),
        {
            "resident_id": "resident_id",
            "feed_source_id": "feed_source_id",
            "origin_address_id": "origin_address_id",
            "destination_address_id": "destination_address_id",
            "duplicate_of_move_id": "duplicate_of_move_id",
            "reactivation_candidate_move_id": "reactivation_candidate_move_id",
            "duplicate_candidate_move_id": "duplicate_candidate_move_id",
            "lifecycle_status": "lifecycle_status",
            "duplicate_flag": "duplicate_flag",
        },
    )
    return response.paginated(rows)


@bp.get("/moves/<move_id>/readiness")
def read_readiness(move_id):
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    move = move_or_404(move_id)
    variant = v.query_enum("variant", ("pre_verification", "post_verification"))
    breakdown = derive.readiness_breakdown(move, variant)
    payload = {"move_id": move["id"]}
    payload.update(breakdown)
    return response.ok(payload)


# ------------------------------------------------------ identity verifications
@bp.post("/moves/<move_id>/identity-verifications")
def open_verification(move_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    raw = v.body()
    # rung 2: MANUAL_OVERRIDE is reserved to ComplianceOfficer and PlatformAdmin.
    if raw.get("method") == "MANUAL_OVERRIDE" and not caller.is_role(
        COMPLIANCE_OFFICER, "PlatformAdmin"
    ):
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "MANUAL_OVERRIDE identity verification is reserved to ComplianceOfficer.",
        )
    move = move_or_404(move_id)
    method = v.enum_field(raw, "method", enums.VERIFICATION_METHODS)
    override_reason = v.str_field(
        raw, "override_reason", required=False, min_len=1, max_len=500, default=None
    )
    if method == "MANUAL_OVERRIDE" and not override_reason:
        v.bad("Field 'override_reason' is required for a MANUAL_OVERRIDE.")

    gates.require_move_state(
        move, ("INTAKE", "IDENTITY_PENDING", "IDENTITY_FAILED")
    )
    gates.require_attempts_available(move)
    gates.require_duplicate_resolved(move)

    snap = derive.snapshot(move)

    # Opening a fresh attempt sweeps lapsed PENDING attempts to EXPIRED.
    for row in verifications_of_move(move["id"]):
        if row["status"] != "PENDING":
            continue
        expires_at = db.parse_ts(row["expires_at"])
        if expires_at is not None and expires_at < db.now():
            row["status"] = "EXPIRED"
            row["decided_at"] = db.now_iso()
            db.touch(row)

    rec = db.base_record()
    rec.update(
        {
            "move_id": move["id"],
            "resident_id": move["resident_id"],
            "method": method,
            "attempt_no": move["identity_attempt_count"] + 1,
            "status": "PENDING",
            "kba_score": None,
            "reviewer_user_id": None,
            "override_reason": override_reason,
            "expires_at": db.iso(db.now() + timedelta(hours=enums.PENDING_TTL_HOURS)),
            "decided_at": None,
        }
    )
    move["identity_attempt_count"] = move["identity_attempt_count"] + 1

    if method == "MANUAL_OVERRIDE":
        rec["status"] = "PASSED"
        rec["decided_at"] = db.now_iso()
        rec["reviewer_user_id"] = caller.user_id
        move["verified_at"] = db.now_iso()
        move["lifecycle_status"] = "VERIFIED"
    else:
        move["lifecycle_status"] = "IDENTITY_PENDING"

    db.db.verifications[rec["id"]] = rec
    derive.recompute(move)
    derive.commit(move, snap)
    return response.created(db.public(rec))


# ------------------------------------------------------------ provider mapping
@bp.post("/moves/<move_id>/provider-mapping")
def provider_mapping(move_id):
    authenticate(MOVE_OPS_AGENT)
    move = move_or_404(move_id)
    body = v.body()
    utility_types = v.list_field(
        body, "utility_types", min_len=1, allowed=enums.UTILITY_TYPES
    )
    include_stop = v.bool_field(body, "include_stop_orders", required=False, default=False)

    gates.require_move_state(move, ("VERIFIED", "SCHEDULING", "ATTENTION_REQUIRED"))
    gates.require_consent(move, "UTILITY_SETUP")
    gates.require_gate_open(move)

    destination = db.db.service_addresses[move["destination_address_id"]]
    origin = db.db.service_addresses[move["origin_address_id"]]
    move_date = db.parse_date(move["move_date"])

    requested = []
    for utility_type in utility_types:
        if utility_type not in requested:
            requested.append(utility_type)

    plan = []
    unmapped = []
    for utility_type in requested:
        start_pairs = mapping.eligible_pairs(utility_type, destination, move_date)
        winner = mapping.pick_winner(start_pairs)
        if winner is None:
            unmapped.append(utility_type)
        else:
            plan.append((utility_type, "START", winner, destination))
        if include_stop:
            stop_winner = mapping.pick_winner(
                mapping.eligible_pairs(utility_type, origin, move_date)
            )
            if stop_winner is not None:
                plan.append((utility_type, "STOP", stop_winner, origin))

    # rung 23: no requested type has any eligible row at all.
    if not plan:
        raise ApiError(
            "ERR_NO_PROVIDER_COVERAGE",
            "No requested utility type has an eligible provider territory.",
        )

    gates.require_duplicate_resolved(move)

    # rung 39: every requested pairing already has a live order.
    todo = [
        entry
        for entry in plan
        if not mapping.has_live_order(move["id"], entry[0], entry[1])
    ]
    if not todo:
        raise ApiError(
            "ERR_TYPE_ALREADY_MAPPED",
            "Every requested utility type already has a live service order.",
        )

    snap = derive.snapshot(move)
    for utility_type, order_kind, winner, address in todo:
        provider, territory = winner
        mapping.create_order(move, provider, territory, address, order_kind, utility_type)

    move["unmapped_utility_types"] = unmapped
    if move["lifecycle_status"] == "VERIFIED":
        move["lifecycle_status"] = "SCHEDULING"
    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(move))


# ------------------------------------------------------- duplicate resolution
@bp.post("/moves/<move_id>/duplicate-resolution")
def duplicate_resolution(move_id):
    authenticate(MOVE_OPS_AGENT)
    move = move_or_404(move_id)
    body = v.body()
    survivor = ref_move(v.id_field(body, "survivor_move_id", required=False))
    resolution = v.enum_field(body, "resolution", ("DISMISS", "RESCORE", "MERGE_INTO"))
    expected = v.int_field(body, "expected_move_version")
    if resolution == "MERGE_INTO" and survivor is None:
        v.bad("Field 'survivor_move_id' is required for a MERGE_INTO resolution.")

    if resolution == "MERGE_INTO":
        gates.require_move_state(move, enums.MERGEABLE_LIFECYCLE)
    else:
        gates.require_move_live(move)

    gates.check_move_version(move, expected)

    # rung 43 then rung 44.
    if survivor is not None and survivor["id"] == move["id"]:
        raise ApiError(
            "ERR_SELF_MERGE_FORBIDDEN", "A move may not be merged into itself."
        )
    if resolution == "MERGE_INTO":
        _check_survivor(move, survivor)

    snap = derive.snapshot(move)
    if resolution == "DISMISS":
        move["duplicate_flag"] = "DISMISSED"
        if move["blocked_reason"] == "DUPLICATE_SUSPECTED":
            move["blocked_reason"] = "NONE"
    elif resolution == "RESCORE":
        duplicates.rescore(move, db.db.feed_sources[move["feed_source_id"]])
    else:
        move["duplicate_flag"] = "CONFIRMED_DUPLICATE"
        move["duplicate_of_move_id"] = survivor["id"]
        move["lifecycle_status"] = "DUPLICATE_MERGED"
        cascades.cancel_orders(move, "DUPLICATE_MERGED")
        cascades.cancel_filings(move)
        cascades.void_open_placements_of_move(move)

    derive.recompute(move)
    derive.commit(move, snap, force=True)
    return response.ok(db.public(move))


def _check_survivor(move, survivor):
    if survivor["lifecycle_status"] not in enums.OPEN_LIFECYCLE:
        raise ApiError(
            "ERR_SURVIVOR_MOVE_INVALID", "The nominated survivor move is terminal."
        )
    shares_resident = survivor["resident_id"] == move["resident_id"]
    a = db.db.service_addresses.get(move["destination_address_id"])
    b = db.db.service_addresses.get(survivor["destination_address_id"])
    shares_address = (
        a is not None and b is not None and a["address_hash"] == b["address_hash"]
    )
    if not (shares_resident or shares_address):
        raise ApiError(
            "ERR_SURVIVOR_MOVE_INVALID",
            "The survivor shares neither resident nor destination address.",
        )


# ------------------------------------------------------------- cancellation
@bp.post("/moves/<move_id>/cancellation")
def cancel_move(move_id):
    caller = authenticate(MOVE_OPS_AGENT, FEED_INTEGRATOR)
    move = move_or_404(move_id)
    caller.own_if(FEED_INTEGRATOR, move["feed_source_id"])
    body = v.body()
    reason = v.str_field(body, "cancellation_reason", min_len=1, max_len=500)

    gates.require_move_live(move)

    snap = derive.snapshot(move)
    move["lifecycle_status"] = "CANCELLED"
    move["cancellation_reason"] = reason
    cascades.cancel_orders(move, "MOVE_CANCELLED")
    cascades.cancel_filings(move)
    cascades.void_open_placements_of_move(move)
    move["blocked_reason"] = "NONE"
    derive.recompute(move)
    derive.commit(move, snap, force=True)
    return response.ok(db.public(move))


# ------------------------------------------------------- attention clearance
@bp.post("/moves/<move_id>/attention-clearances")
def clear_attention(move_id):
    authenticate(MOVE_OPS_AGENT)
    move = move_or_404(move_id)
    body = v.body()
    v.str_field(body, "clearance_note", required=False, min_len=1, max_len=500, default=None)

    gates.require_move_state(move, ("ATTENTION_REQUIRED",))
    gates.require_gate_open(move)
    for filing in filings_of_move(move["id"]):
        if filing["status"] == "REJECTED":
            raise ApiError(
                "ERR_FILING_NOT_SUBMITTABLE",
                "A rejected postal filing must be resubmitted or withdrawn first.",
            )
    orders = orders_of_move(move["id"])
    for order in orders:
        if order["provision_status"] != "PROVISION_FAILED" and order["credit_status"] != "DECLINED":
            continue
        replacement = any(
            other["id"] != order["id"]
            and other["utility_type"] == order["utility_type"]
            and other["order_kind"] == order["order_kind"]
            and other["provision_status"] in enums.REPLACEMENT_PROVISION
            for other in orders
        )
        if not replacement:
            raise ApiError(
                "ERR_UNRESOLVED_PROVISION_FAILURE",
                "A failed or declined service order still has no replacement.",
            )

    snap = derive.snapshot(move)
    move["lifecycle_status"] = "SCHEDULING"
    move["blocked_reason"] = "NONE"
    derive.recompute(move)
    derive.commit(move, snap, force=True)
    return response.ok(db.public(move))


# ---------------------------------------------------------------- completion
@bp.post("/moves/<move_id>/completion")
def complete_move(move_id):
    authenticate(MOVE_OPS_AGENT)
    move = move_or_404(move_id)
    v.body()

    gates.require_move_state(move, ("IN_SERVICE",))
    gates.require_gate_open(move)
    gates.require_move_date_reached(move)
    for order in orders_of_move(move["id"]):
        if order["provision_status"] not in enums.ORDER_SETTLED_PROVISION:
            raise ApiError(
                "ERR_MOVE_NOT_ACTIONABLE",
                "A service order is still outstanding.",
            )

    snap = derive.snapshot(move)
    move["lifecycle_status"] = "COMPLETED"
    derive.recompute(move)
    derive.commit(move, snap, force=True)
    return response.ok(db.public(move))


# ------------------------------------------------------- consent evaluations
@bp.post("/moves/<move_id>/consent-evaluations")
def consent_evaluation(move_id):
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    move = move_or_404(move_id)
    v.body()
    gates.require_move_live(move)

    resident = db.db.residents[move["resident_id"]]
    now = db.now()
    for consent in sorted(
        [c for c in db.db.consents.values() if c["resident_id"] == resident["id"]],
        key=db.order_key,
    ):
        if consent["state"] != "GRANTED":
            continue
        expires_at = db.parse_ts(consent["expires_at"])
        if expires_at is None or expires_at >= now:
            continue
        consent["state"] = "EXPIRED"
        db.touch(consent)
        cascades.apply_consent_termination(consent, resident)

    snap = derive.snapshot(move)
    for row in verifications_of_move(move["id"]):
        if row["status"] != "PENDING":
            continue
        expires_at = db.parse_ts(row["expires_at"])
        if expires_at is not None and expires_at < now:
            row["status"] = "EXPIRED"
            row["decided_at"] = db.now_iso()
            db.touch(row)

    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(move))
