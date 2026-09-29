"""Endorsements and the depth-4 premium/tax cascade (PRD 3.8)."""

from flask import Blueprint

import auth
import ledger
import serialize
import store
import validation
from calc import endorsement_adj
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("endorsements", __name__)

ENDORSEMENT_TYPES = ("PREMIUM_INCREASE", "PREMIUM_DECREASE", "EXPOSURE_CHANGE",
                     "ADMINISTRATIVE")


def _check_delta_sign(endorsement_type, delta):
    if endorsement_type == "ADMINISTRATIVE" and delta != 0:
        validation.bad("premium_delta_cents must be 0 for an ADMINISTRATIVE "
                       "endorsement.")
    if endorsement_type == "PREMIUM_INCREASE" and delta <= 0:
        validation.bad("premium_delta_cents must be > 0 for a PREMIUM_INCREASE "
                       "endorsement.")
    if endorsement_type == "PREMIUM_DECREASE" and delta >= 0:
        validation.bad("premium_delta_cents must be < 0 for a PREMIUM_DECREASE "
                       "endorsement.")


@bp.post("/policies/<rec_id>/endorsements")
def create_endorsement(rec_id):
    auth.require("PlacementBroker")
    policy = auth.path_entity("policies", "policy", rec_id)
    data = validation.body()
    # Rung 5: an unresolvable supersedes_endorsement_id is a 404.
    superseded = auth.body_fk(data, "supersedes_endorsement_id", "endorsements",
                              "endorsement")

    endorsement_type = validation.req_enum(data, "endorsement_type",
                                           ENDORSEMENT_TYPES)
    delta = validation.req_int(data, "premium_delta_cents")
    _check_delta_sign(endorsement_type, delta)
    effective_at, effective_raw = validation.req_datetime(data, "effective_date")
    if policy.get("_effective_at") is not None and \
            not (policy["_effective_at"] <= effective_at <= policy["_expiration_at"]):
        validation.bad("effective_date must fall within the policy term.")
    expected = validation.req_int(data, "expected_policy_version")

    auth.check_owner(policy.get("broker_id"))
    auth.check_version(expected, policy, "ERR_STALE_POLICY_VERSION")

    existing = store.endorsements_of(policy["id"])
    next_seq = max([int(e.get("sequence_number") or 0) for e in existing] or [0]) + 1

    rec = db.insert("endorsements", {
        "policy_id": policy["id"],
        "supersedes_endorsement_id": superseded["id"] if superseded else None,
        "sequence_number": next_seq,
        "endorsement_type": endorsement_type,
        "premium_delta_cents": delta,
        "effective_date": effective_raw,
        "status": "DRAFT",
        "tax_adjustment_cents": 0,
        "stamping_fee_adjustment_cents": 0,
        "_effective_at": effective_at,
    })
    return created(serialize.public(rec))


@bp.get("/endorsements/<rec_id>")
def get_endorsement(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("endorsements", "endorsement", rec_id)
    return ok(serialize.public(rec))


@bp.get("/endorsements")
def list_endorsements():
    auth.require(auth.ANY)
    rows = filtered(db.all("endorsements"), policy_id=arg("policy_id"),
                    supersedes_endorsement_id=arg("supersedes_endorsement_id"),
                    status=arg("status"))
    return list_response(rows)


# --- issue / void ---------------------------------------------------------

def _record_deltas(endorsement, movement):
    """Remember the per-state movement so a later void can negate it exactly."""
    deltas = {}
    for code, entry in movement["per_state"].items():
        deltas[code] = {
            "premium": entry["premium_delta"],
            "tax": entry["tax_delta"],
            "stamping": entry["stamping_delta"],
            "state_program_id": entry["state_program_id"],
        }
    endorsement["_per_state_deltas"] = deltas
    return deltas


def _emit_movement_lines(policy, endorsement, movement):
    """One ENDORSEMENT line per state whose tax OR stamping fee actually moved."""
    for code in sorted(movement["per_state"].keys()):
        entry = movement["per_state"][code]
        if entry["tax_delta"] == 0 and entry["stamping_delta"] == 0:
            continue
        ledger.emit_line(policy, entry["state_program_id"], "ENDORSEMENT",
                         entry["premium_delta"], entry["tax_delta"],
                         entry["stamping_delta"],
                         source_endorsement_id=endorsement["id"])


def _emit_compensating_lines(policy, endorsement):
    """The exact negation of the voided endorsement's stored per-state deltas."""
    deltas = endorsement.get("_per_state_deltas") or {}
    for code in sorted(deltas.keys()):
        entry = deltas[code]
        if entry["tax"] == 0 and entry["stamping"] == 0:
            continue
        ledger.emit_line(policy, entry["state_program_id"], "ENDORSEMENT",
                         -entry["premium"], -entry["tax"], -entry["stamping"],
                         source_endorsement_id=endorsement["id"])


@bp.post("/endorsements/<rec_id>/issue")
def issue_endorsement(rec_id):
    auth.require("PlacementBroker")
    rec = auth.path_entity("endorsements", "endorsement", rec_id)
    policy = db.get("policies", rec.get("policy_id"))
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    auth.check_owner(policy.get("broker_id"))

    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT endorsement may be issued.")
    if policy.get("status") != "ISSUED":
        raise ApiError("ERR_POLICY_NOT_ISSUED",
                       "The policy's status is %s." % policy.get("status"))
    if policy.get("tax_status") == "UNCALCULATED":
        raise ApiError("ERR_TAX_NOT_CALCULATED",
                       "The policy's premium tax has not been calculated.")

    target_id = rec.get("supersedes_endorsement_id")
    target = db.get("endorsements", target_id) if target_id else None
    if target_id:
        if target is None or target.get("status") != "ISSUED" \
                or target.get("policy_id") != policy["id"]:
            raise ApiError("ERR_SUPERSEDE_TARGET_INVALID",
                           "The superseded endorsement must be an ISSUED "
                           "endorsement of the same policy.")

    projected = endorsement_adj.projected_gross(
        policy, extra_ids=[rec["id"]],
        excluded_ids=[target_id] if target_id else [])
    if projected <= 0:
        raise ApiError("ERR_PREMIUM_WOULD_BE_NON_POSITIVE",
                       "The resulting gross premium would not be strictly "
                       "positive.")

    # The superseded endorsement is voided first, and its compensating lines are
    # emitted before this endorsement's.
    if target is not None:
        target["status"] = "VOIDED"
        endorsement_adj.recompute(policy)
        _emit_compensating_lines(policy, target)
        touch(target)

    rec["status"] = "ISSUED"
    movement = endorsement_adj.recompute(policy)
    rec["tax_adjustment_cents"] = movement["tax_after"] - movement["tax_before"]
    rec["stamping_fee_adjustment_cents"] = (movement["stamping_after"]
                                            - movement["stamping_before"])
    _record_deltas(rec, movement)
    _emit_movement_lines(policy, rec, movement)

    has_delta = (rec["tax_adjustment_cents"] != 0
                 or rec["stamping_fee_adjustment_cents"] != 0)
    ledger.advance_to_adjusted(policy, has_delta)
    touch(policy)
    touch(rec)
    return ok(serialize.public(rec))


@bp.post("/endorsements/<rec_id>/void")
def void_endorsement(rec_id):
    auth.require("PlacementBroker")
    rec = auth.path_entity("endorsements", "endorsement", rec_id)
    policy = db.get("policies", rec.get("policy_id"))
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    auth.check_owner(policy.get("broker_id"))

    status = rec.get("status")
    if status not in ("DRAFT", "ISSUED"):
        raise ApiError("ERR_INVALID_STATE", "A VOIDED endorsement is terminal.")

    if status == "DRAFT":
        # A draft never entered the premium base: no ledger effect at all.
        rec["status"] = "VOIDED"
        touch(rec)
        return ok(serialize.public(rec))

    for line in store.lines_of_endorsement(rec["id"]):
        if line.get("status") == "REMITTED":
            raise ApiError("ERR_ENDORSEMENT_ALREADY_REMITTED",
                           "This endorsement's tax has already been remitted.")

    rec["status"] = "VOIDED"
    movement = endorsement_adj.recompute(policy)
    _emit_compensating_lines(policy, rec)

    deltas = rec.get("_per_state_deltas") or {}
    has_delta = any(entry["tax"] != 0 or entry["stamping"] != 0
                    for entry in deltas.values())
    if not has_delta:
        has_delta = (movement["tax_after"] != movement["tax_before"]
                     or movement["stamping_after"] != movement["stamping_before"])
    ledger.advance_to_adjusted(policy, has_delta)
    touch(policy)
    touch(rec)
    return ok(serialize.public(rec))
