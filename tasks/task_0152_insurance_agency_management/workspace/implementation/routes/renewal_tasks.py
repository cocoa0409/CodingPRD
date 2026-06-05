"""RenewalTask endpoints (PRD §3.8) and the renewal pipeline state machine."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import serialize
from db import store, new_common, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_RENEWAL_WINDOW_CLOSED,
    ERR_DUPLICATE_RENEWAL_TASK,
    ERR_RENEWAL_TERM_NOT_ADJACENT,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST,
)
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from util import require_str, require_int, parse_dt
from routes.policies import _make_policy_record

bp = Blueprint("renewal_tasks", __name__)

READ_ROLES = {"AgencyAdmin", "AccountManager", "Producer"}

RENEWAL_WINDOW_DAYS = 60
_FORWARD = {"IDENTIFIED": "REVIEW", "REVIEW": "QUOTED", "QUOTED": "OFFERED"}


@bp.post("/renewal-tasks")
def create_renewal_task():
    auth({"AccountManager"})
    body = get_json_body()
    policy_id = require_str(body, "policy_id")
    with store.lock:
        policy = lookup(store.policies, policy_id)  # existence
        target = parse_dt(require_str(body, "target_effective_date"), "target_effective_date")

        # business: renewal window open (now >= expiration - 60 days).
        exp = parse_dt(policy["expiration_date"], "expiration_date")
        window_open = exp - timedelta(days=RENEWAL_WINDOW_DAYS)
        if not (clock.now() >= window_open):
            raise err(ERR_RENEWAL_WINDOW_CLOSED, "renewal window not yet open")

        # business: at most one non-terminal renewal task per policy (PRD §3.8).
        # This is checked BEFORE the ACTIVE/REINSTATED precondition: a policy that
        # already holds a non-terminal task is necessarily in PENDING_RENEWAL (the
        # first task moved it there), and the PRD names exactly that "second task"
        # scenario as ERR_DUPLICATE_RENEWAL_TASK, not a generic state error.
        for t in store.renewal_tasks.values():
            if t["policy_id"] == policy_id and t["stage"] not in ("COMPLETED", "LOST"):
                raise err(ERR_DUPLICATE_RENEWAL_TASK, "a non-terminal renewal task already exists")

        # eligibility: a renewal task only opens on an ACTIVE or REINSTATED policy.
        if policy["status"] not in ("ACTIVE", "REINSTATED"):
            raise err(ERR_INVALID_STATE, "renewal task only opens on ACTIVE/REINSTATED policy")

        rec = new_common()
        rec.update(
            policy_id=policy_id,
            stage="IDENTIFIED",
            target_effective_date=body["target_effective_date"],
            requote_count=0,
            successor_policy_id=None,
        )
        store.renewal_tasks[rec["id"]] = rec
        # cross-entity: linked policy -> PENDING_RENEWAL, bump its version.
        policy["status"] = "PENDING_RENEWAL"
        touch(policy)
        return object_response(serialize.renewal_task(rec), 201)


@bp.get("/renewal-tasks/<rid>")
def get_renewal_task(rid):
    auth(READ_ROLES)
    rec = lookup(store.renewal_tasks, rid)
    return object_response(serialize.renewal_task(rec))


@bp.get("/renewal-tasks")
def list_renewal_tasks():
    auth(READ_ROLES)
    policy_id = request.args.get("policy_id")
    successor_policy_id = request.args.get("successor_policy_id")
    stage = request.args.get("stage")
    recs = [
        t
        for t in store.renewal_tasks.values()
        if (policy_id is None or t["policy_id"] == policy_id)
        and (successor_policy_id is None or t["successor_policy_id"] == successor_policy_id)
        and (stage is None or t["stage"] == stage)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.renewal_task(t) for t in page], limit, offset, total)


@bp.post("/renewal-tasks/<rid>/advance")
def advance_renewal_task(rid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.renewal_tasks, rid)
        if rec["stage"] not in _FORWARD:
            raise err(ERR_INVALID_STATE, "renewal task cannot advance from its current stage")
        check_version(rec, body.get("expected_renewaltask_version"), "expected_renewaltask_version")
        # The first advance (IDENTIFIED -> REVIEW) requires policy PENDING_RENEWAL.
        if rec["stage"] == "IDENTIFIED":
            policy = store.policies[rec["policy_id"]]
            if policy["status"] != "PENDING_RENEWAL":
                raise err(ERR_INVALID_STATE, "linked policy must be PENDING_RENEWAL to advance")
        rec["stage"] = _FORWARD[rec["stage"]]
        touch(rec)
        return object_response(serialize.renewal_task(rec))


@bp.post("/renewal-tasks/<rid>/requote")
def requote_renewal_task(rid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.renewal_tasks, rid)
        if rec["stage"] != "OFFERED":
            raise err(ERR_INVALID_STATE, "only an OFFERED task may be re-quoted")
        check_version(rec, body.get("expected_renewaltask_version"), "expected_renewaltask_version")
        rec["stage"] = "REVIEW"
        rec["requote_count"] = rec["requote_count"] + 1
        touch(rec)
        return object_response(serialize.renewal_task(rec))


@bp.post("/renewal-tasks/<rid>/complete")
def complete_renewal_task(rid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.renewal_tasks, rid)
        if rec["stage"] != "OFFERED":
            raise err(ERR_INVALID_STATE, "only an OFFERED task may be completed")
        check_version(rec, body.get("expected_renewaltask_version"), "expected_renewaltask_version")

        policy = store.policies[rec["policy_id"]]
        # business: linked policy must still be PENDING_RENEWAL.
        if policy["status"] != "PENDING_RENEWAL":
            raise err(ERR_INVALID_STATE, "linked policy must be PENDING_RENEWAL to complete")

        annual = require_int(body, "annual_premium_cents")
        if annual <= 0:
            raise err(ERR_INVALID_REQUEST, "annual_premium_cents must be > 0")
        eff = parse_dt(require_str(body, "effective_date"), "effective_date")
        exp = parse_dt(require_str(body, "expiration_date"), "expiration_date")
        if not (eff < exp):
            raise err(ERR_INVALID_DATE_RANGE, "effective_date must be before expiration_date")

        # business: successor effective_date must EQUAL the expiring policy's
        # expiration_date exactly (adjacency, not non-overlap).
        prior_exp = parse_dt(policy["expiration_date"], "expiration_date")
        if eff != prior_exp:
            raise err(
                ERR_RENEWAL_TERM_NOT_ADJACENT,
                "successor effective_date must equal expiring policy's expiration_date",
            )

        # create successor Policy in BOUND, term_kind RENEWAL, chained.
        successor = _make_policy_record(
            account_id=policy["account_id"],
            product_id=policy["product_id"],
            writing_producer_id=policy["writing_producer_id"],
            state_code=policy["state_code"],
            annual_premium_cents=annual,
            effective_date=body["effective_date"],
            expiration_date=body["expiration_date"],
            renewed_from_policy_id=policy["id"],
            download_source="MANUAL",
            status="BOUND",
        )
        store.policies[successor["id"]] = successor

        rec["successor_policy_id"] = successor["id"]
        rec["stage"] = "COMPLETED"
        touch(rec)

        # cross-entity cascade: expiring policy PENDING_RENEWAL -> EXPIRED.
        policy["status"] = "EXPIRED"
        touch(policy)
        return object_response(serialize.renewal_task(rec))


@bp.post("/renewal-tasks/<rid>/lose")
def lose_renewal_task(rid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.renewal_tasks, rid)
        if rec["stage"] not in ("REVIEW", "OFFERED"):
            raise err(ERR_INVALID_STATE, "only a REVIEW/OFFERED task may be marked LOST")
        check_version(rec, body.get("expected_renewaltask_version"), "expected_renewaltask_version")
        rec["stage"] = "LOST"
        touch(rec)
        return object_response(serialize.renewal_task(rec))
