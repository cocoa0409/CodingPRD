"""CommissionSplit endpoints (PRD §3.5).

OCC here guards the *parent* Policy: the create carries expected_policy_version
matching Policy.version, and a successful create bumps Policy.version (§2.9).
"""
from flask import Blueprint, request

import serialize
from db import store, new_common, touch
from errors import err, ERR_PRODUCER_INACTIVE, ERR_SPLIT_OVER_ALLOCATED
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from util import require_str, require_enum, require_fraction

bp = Blueprint("commission_splits", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}
SPLIT_ROLE = {"WRITING", "SERVICING", "OVERRIDE"}


@bp.post("/commission-splits")
def create_split():
    auth({"AgencyAdmin", "Producer"})
    body = get_json_body()
    policy_id = require_str(body, "policy_id")
    producer_id = require_str(body, "producer_id")
    with store.lock:
        policy = lookup(store.policies, policy_id)  # existence
        producer = lookup(store.producers, producer_id)  # existence
        split_pct = require_fraction(body, "split_pct", lo_exclusive=True)
        role = require_enum(body, "role", SPLIT_ROLE)

        # OCC on parent Policy.version (§2.9) — before business rules.
        check_version(policy, body.get("expected_policy_version"), "expected_policy_version")

        # business: producer must be ACTIVE.
        if producer["status"] == "INACTIVE":
            raise err(ERR_PRODUCER_INACTIVE, "cannot assign split to an INACTIVE producer")

        # business: WRITING+SERVICING sum must not exceed 1.0 (OVERRIDE excluded).
        # Use Decimal to avoid float drift on the cap comparison.
        if role in ("WRITING", "SERVICING"):
            from decimal import Decimal
            total = Decimal(str(split_pct))
            for s in store.commission_splits.values():
                if s["policy_id"] == policy_id and s["role"] in ("WRITING", "SERVICING"):
                    total += Decimal(str(s["split_pct"]))
            if total > Decimal("1"):
                raise err(ERR_SPLIT_OVER_ALLOCATED, "WRITING+SERVICING split sum exceeds 1.0")

        rec = new_common()
        rec.update(
            policy_id=policy_id,
            producer_id=producer_id,
            split_pct=split_pct,
            role=role,
            status="DRAFT",
        )
        store.commission_splits[rec["id"]] = rec
        # parent Policy.version bumps (§2.9 / §3.5).
        touch(policy)
        return object_response(serialize.commission_split(rec), 201)


@bp.get("/commission-splits/<sid>")
def get_split(sid):
    auth(ALL_ROLES)
    rec = lookup(store.commission_splits, sid)
    return object_response(serialize.commission_split(rec))


@bp.get("/commission-splits")
def list_splits():
    auth(ALL_ROLES)
    policy_id = request.args.get("policy_id")
    producer_id = request.args.get("producer_id")
    recs = [
        s
        for s in store.commission_splits.values()
        if (policy_id is None or s["policy_id"] == policy_id)
        and (producer_id is None or s["producer_id"] == producer_id)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.commission_split(s) for s in page], limit, offset, total)
