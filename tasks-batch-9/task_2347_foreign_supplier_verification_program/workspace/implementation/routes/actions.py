"""CorrectiveAction: reads, branch decision and closure.

Corrective actions are never created directly — they are synthesized by the
suspension cascade (PRD section 3.6), so the list endpoint is their only
discovery channel.
"""
from flask import Blueprint

import cascades
import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import object_response
from routes._common import find, paged
from shapes import body, pagination, query_enum, query_str, req_enum, req_int, req_str

bp = Blueprint("actions", __name__)

DECISIONS = ("SUPPLIER_REMEDIATION", "IMPORT_SUSPENSION")
CLOSURE_ACTIONS = ("CLOSE_RESOLVED", "CLOSE_DISQUALIFY")


@bp.get("/fsvp/corrective-actions/<action_id>")
@endpoint([CO, QI, FDA])
def read_action(action_id):
    row = find("action", action_id, "ERR_CORRECTIVE_ACTION_NOT_FOUND")
    return object_response(serialize.action_out(row))


@bp.get("/fsvp/corrective-actions")
@endpoint([CO, QI, FDA])
def list_actions():
    supplier_id = query_str("supplier_id")
    pair_id = query_str("pair_id")
    status = query_enum("status", core.ACTION_STATUSES)
    trigger_reason = query_enum("trigger_reason", core.ACTION_TRIGGERS)
    limit, offset = pagination()

    rows = list(store.actions.values())
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if pair_id is not None:
        rows = [r for r in rows if r["pair_id"] == pair_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if trigger_reason is not None:
        rows = [r for r in rows if r["trigger_reason"] == trigger_reason]
    return paged(rows, serialize.action_out, limit, offset)


@bp.post("/fsvp/corrective-actions/<action_id>/decision")
@endpoint([CO])
def decide_action(action_id):
    b = body()
    decision = req_enum(b, "decision", DECISIONS)
    rationale = req_str(b, "rationale", minlen=1)
    expected_supplier_version = req_int(b, "expected_supplier_version", lo=0)

    action = find("action", action_id, "ERR_CORRECTIVE_ACTION_NOT_FOUND")
    supplier = store.suppliers.get(action["supplier_id"])

    # rung 18
    if supplier is None or expected_supplier_version != supplier["version"]:
        fail(
            "ERR_STALE_SUPPLIER_VERSION",
            "expected_supplier_version does not match the supplier's version",
        )

    # rung 19
    if action["status"] != "OPEN":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a %s corrective action has already been decided" % action["status"],
        )

    with write_txn():
        action["status"] = decision
        action["decision"] = decision
        action["rationale"] = rationale
        action["decided_at"] = core.clock()
        action["supplier_version_at_decision"] = expected_supplier_version
        store.touch(action)
        if decision == "SUPPLIER_REMEDIATION":
            cascades.remediation_branch(supplier)
        else:
            cascades.suspension_branch(supplier, action)
        # the supplier's posture is rewritten by every decision
        store.touch(supplier)
    return object_response(serialize.action_out(action))


@bp.post("/fsvp/corrective-actions/<action_id>/closure")
@endpoint([CO])
def close_action(action_id):
    b = body()
    action_name = req_enum(b, "action", CLOSURE_ACTIONS)
    req_str(b, "closure_note", minlen=1)

    action = find("action", action_id, "ERR_CORRECTIVE_ACTION_NOT_FOUND")

    # rung 19
    if action["status"] not in ("SUPPLIER_REMEDIATION", "IMPORT_SUSPENSION"):
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a %s corrective action cannot be closed" % action["status"],
        )

    # rung 47
    if action_name == "CLOSE_RESOLVED" and not _has_reverification(action):
        fail(
            "ERR_REVERIFICATION_MISSING",
            "a passing attested record performed after the decision is required",
        )

    supplier = store.suppliers.get(action["supplier_id"])

    with write_txn():
        action["closed_at"] = core.clock()
        if action_name == "CLOSE_RESOLVED":
            action["status"] = "CLOSED_RESOLVED"
            store.touch(action)
            if supplier is not None:
                cascades.resolved_closure(action, supplier)
        else:
            action["status"] = "CLOSED_SUPPLIER_DISQUALIFIED"
            store.touch(action)
            if supplier is not None:
                cascades.disqualification_closure(supplier)
    return object_response(serialize.action_out(action))


def _has_reverification(action):
    """Ladder rung 47 — a passing attested record strictly after decided_at."""
    decided_at = action["decided_at"]
    if decided_at is None or not action["pair_id"]:
        return False
    for record in core.records_of_pair(action["pair_id"]):
        if (
            record["record_status"] == "ATTESTED"
            and record["outcome"] == "PASS"
            and record["performed_end"] > decided_at
        ):
            return True
    return False
