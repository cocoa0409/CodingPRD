"""The append-only distribution ledger (PRD section 3.7)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_retailer_scope
from services import domain

bp = Blueprint("snapshots", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "authorization_id": rec["authorization_id"],
        "entry_kind": rec["entry_kind"],
        "reverses_snapshot_id": rec["reverses_snapshot_id"],
        "period_index": rec["period_index"],
        "reported_store_count": rec["reported_store_count"],
        "distributed_store_count": rec["distributed_store_count"],
        "reported_case_volume": rec["reported_case_volume"],
        "amortized_amount_cents": rec["amortized_amount_cents"],
        "is_reversed": rec["is_reversed"],
        "posted_at": rec["posted_at"],
        "created_at": rec["created_at"],
    }


@bp.post("/distribution-snapshots")
def post_snapshot():
    user_id, role = authorize("RetailerBuyer")
    data = v.body()

    authorization_id = v.req_id(data, "authorization_id")
    expected_version = v.req_int(data, "expected_authorization_version", 0)
    period_index = v.req_int(data, "period_index", 1)
    reported = v.req_int(data, "reported_store_count", 0)
    distributed = v.req_int(data, "distributed_store_count", 0)
    volume = v.req_int(data, "reported_case_volume", 0)

    auth = db.get("authorizations", authorization_id)
    check_retailer_scope(role, user_id, auth["retailer_id"])

    if expected_version != auth["version"]:
        raise ApiError("ERR_STALE_AUTHORIZATION_VERSION")

    if auth["authorization_state"] not in ("AUTHORIZED", "AT_RISK"):
        raise ApiError("ERR_INVALID_STATE")

    for entry in domain.live_postings(auth["id"]):
        if entry["period_index"] == period_index:
            raise ApiError("ERR_PERIOD_ALREADY_POSTED")
    if period_index != auth["periods_reported"] + 1:
        raise ApiError("ERR_PERIOD_OUT_OF_SEQUENCE")
    if distributed > reported:
        raise ApiError("ERR_DISTRIBUTION_EXCEEDS_REPORTED")
    if reported > auth["authorized_store_count"]:
        raise ApiError("ERR_REPORTED_EXCEEDS_AUTHORIZED")

    # step 1 — the immutable ledger entry
    rec = db.base_record(versioned=False)
    rec.update({
        "authorization_id": auth["id"],
        "entry_kind": "POSTING",
        "reverses_snapshot_id": None,
        "period_index": period_index,
        "reported_store_count": reported,
        "distributed_store_count": distributed,
        "reported_case_volume": volume,
        "amortized_amount_cents": 0,
        "is_reversed": False,
        "posted_at": clock.iso_now(),
        "_amortized_to_deal": None,
    })
    db.insert("snapshots", rec)
    db.assign(auth, periods_reported=auth["periods_reported"] + 1)

    # step 2 — distribution counters
    domain.recompute_distribution(auth)

    # step 3 — amortization against the linked deal
    deal = db.find("deals", auth["slotting_deal_id"])
    domain.apply_amortization(deal, rec)

    # step 4 — the AUTHORIZED <-> AT_RISK decision, taken after amortization
    movement = domain.evaluate_at_risk(auth)

    # step 5 — the recovery hold follows the risk flag
    if movement == "ENTERED":
        if deal is not None and deal["state"] == "AMORTIZING" and deal["unamortized_balance_cents"] > 0:
            db.assign(deal, state="RECOVERY_HOLD")
    elif movement == "LEFT":
        domain.release_recovery_hold(deal)

    # step 6 — the principal is re-derived and the authorization's version advances
    db.touch(auth)
    domain.recompute_principal(domain.principal_of_authorization(auth))

    return response.created(serialize(rec))


@bp.get("/distribution-snapshots/<snapshot_id>")
def read_snapshot(snapshot_id):
    authorize(*ALL_ROLES)
    return response.ok(serialize(db.get("snapshots", snapshot_id)))


@bp.get("/distribution-snapshots")
def list_snapshots():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    authorization_id = v.filter_value("authorization_id")
    reverses_snapshot_id = v.filter_value("reverses_snapshot_id")
    entry_kind = v.filter_value("entry_kind")
    period_index = v.filter_int("period_index")
    rows = []
    for rec in db.ordered("snapshots"):
        if authorization_id is not None and rec["authorization_id"] != authorization_id:
            continue
        if reverses_snapshot_id is not None and rec["reverses_snapshot_id"] != reverses_snapshot_id:
            continue
        if entry_kind is not None and rec["entry_kind"] != entry_kind:
            continue
        if period_index is not None and rec["period_index"] != period_index:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/distribution-snapshots/<snapshot_id>/reverse")
def reverse_snapshot(snapshot_id):
    user_id, role = authorize("RetailerBuyer")
    original = db.get("snapshots", snapshot_id)

    auth = db.find("authorizations", original["authorization_id"])
    if auth is not None:
        check_retailer_scope(role, user_id, auth["retailer_id"])

    if original["entry_kind"] != "POSTING" or original["is_reversed"]:
        raise ApiError("ERR_SNAPSHOT_ALREADY_REVERSED")

    latest = domain.latest_live_posting(original["authorization_id"])
    if latest is None or latest["id"] != original["id"]:
        raise ApiError("ERR_SNAPSHOT_NOT_LATEST")

    amount = original["amortized_amount_cents"]

    rec = db.base_record(versioned=False)
    rec.update({
        "authorization_id": original["authorization_id"],
        "entry_kind": "REVERSAL",
        "reverses_snapshot_id": original["id"],
        "period_index": original["period_index"],
        "reported_store_count": original["reported_store_count"],
        "distributed_store_count": original["distributed_store_count"],
        "reported_case_volume": original["reported_case_volume"],
        "amortized_amount_cents": -amount,
        "is_reversed": False,
        "posted_at": clock.iso_now(),
        "_amortized_to_deal": None,
    })
    db.insert("snapshots", rec)
    original["is_reversed"] = True

    deal = db.find("deals", auth["slotting_deal_id"]) if auth is not None else None
    if auth is not None:
        db.assign(auth, periods_reported=max(auth["periods_reported"] - 1, 0))
        domain.rollback_amortization(deal, original)
        domain.recompute_distribution(auth)
        movement = domain.evaluate_at_risk(auth)
        if movement == "ENTERED":
            if deal is not None and deal["state"] == "AMORTIZING" and deal["unamortized_balance_cents"] > 0:
                db.assign(deal, state="RECOVERY_HOLD")
        elif movement == "LEFT":
            domain.release_recovery_hold(deal)
        db.touch(auth)
        domain.recompute_principal(domain.principal_of_authorization(auth))

    return response.created(serialize(rec))
