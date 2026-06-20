"""Chain-of-custody event endpoints (PRD §3.5)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role, parse_pagination
from response import object_response, array_response
from routes._helpers import get_json_body
from services import lookup
from services.common import touch
from services.custody import append_event, active_events_for, CUSTODY_STEPS
from services.serialize import public

bp = Blueprint("custody_events", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}


@bp.route("/clinic/custody-events", methods=["POST"])
def create_custody_event():
    caller = authenticate()
    require_role(caller, {"Collector"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        ds_id = body.get("drug_screen_id")
        ds = db.drug_screens.get(ds_id) if ds_id is not None else None
        if ds is None:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE, "drug screen missing or not found")

        # Priority 5: body well-formedness.
        step = body.get("step")
        if step not in CUSTODY_STEPS:
            raise err(errors.ERR_INVALID_REQUEST, "invalid custody step")
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            raise err(errors.ERR_INVALID_REQUEST, "note must be a string")

        recorded = [e["step"] for e in active_events_for(ds_id)]

        # PRD §3.5: "The very first custody step must be `COLLECT` ... a non-`COLLECT`
        # first step is rejected as an out-of-order custody step." When no custody
        # event has been recorded for the current collection cycle yet, any step
        # other than COLLECT is an out-of-order sequence violation — this ordering
        # check precedes the per-step screen-state precondition.
        if not recorded and step != "COLLECT":
            raise err(errors.ERR_CUSTODY_SEQUENCE_VIOLATION,
                      "The first custody step must be COLLECT")

        if step == "COLLECT":
            # First custody step must be COLLECT and screen must be AWAITING_COLLECTION.
            if ds["status"] != "AWAITING_COLLECTION":
                raise err(errors.ERR_DRUG_SCREEN_NOT_AWAITING_COLLECTION,
                          "Screen must be AWAITING_COLLECTION for COLLECT")
            if recorded:
                # COLLECT may only be the very first step in the cycle.
                raise err(errors.ERR_CUSTODY_SEQUENCE_VIOLATION,
                          "COLLECT must be the first custody step")
            evt = append_event(ds, step, caller.user_id, note)
            ds["status"] = "COLLECTED"
            touch(ds)
            return object_response(public(evt), 201)

        if step in ("SEAL", "SHIP"):
            # Optional steps recorded while COLLECTED; do not change status.
            if ds["status"] != "COLLECTED":
                raise err(errors.ERR_DRUG_SCREEN_NOT_COLLECTED,
                          "Screen must be COLLECTED for SEAL/SHIP")
            # Must not appear after LAB_RECEIVE; since status is COLLECTED, no
            # LAB_RECEIVE has advanced the screen, but guard the recorded prefix.
            if "LAB_RECEIVE" in recorded:
                raise err(errors.ERR_CUSTODY_SEQUENCE_VIOLATION,
                          "SEAL/SHIP cannot follow LAB_RECEIVE")
            evt = append_event(ds, step, caller.user_id, note)
            return object_response(public(evt), 201)

        if step == "LAB_RECEIVE":
            if ds["status"] != "COLLECTED":
                raise err(errors.ERR_DRUG_SCREEN_NOT_COLLECTED,
                          "Screen must be COLLECTED for LAB_RECEIVE")
            # Recorded steps must form a valid prefix of [COLLECT, SEAL, SHIP, LAB_RECEIVE].
            if not _valid_prefix(recorded):
                raise err(errors.ERR_CUSTODY_SEQUENCE_VIOLATION,
                          "Custody steps out of canonical order")
            evt = append_event(ds, step, caller.user_id, note)
            ds["status"] = "AT_LAB"
            touch(ds)
            return object_response(public(evt), 201)

        # LAB_REPORT and MRO_RECEIVE are produced by their own action endpoints,
        # not directly via POST /custody-events; reject as a sequence violation.
        raise err(errors.ERR_CUSTODY_SEQUENCE_VIOLATION,
                  "%s is not recorded via custody-events directly" % step)


def _valid_prefix(recorded):
    """True if recorded steps are a valid ordered subsequence of
    [COLLECT, SEAL, SHIP] (LAB_RECEIVE not yet present), with COLLECT first and
    SEAL before SHIP, and no duplicates of COLLECT/LAB_RECEIVE."""
    if "LAB_RECEIVE" in recorded:
        return False
    if not recorded or recorded[0] != "COLLECT":
        return False
    # After the mandatory leading COLLECT, the rest may be SEAL then SHIP in order.
    rest = recorded[1:]
    allowed_order = ["SEAL", "SHIP"]
    idx = 0
    for s in rest:
        if s == "COLLECT":
            return False
        # advance through allowed_order
        while idx < len(allowed_order) and allowed_order[idx] != s:
            idx += 1
        if idx >= len(allowed_order):
            return False
        idx += 1
    return True


@bp.route("/clinic/custody-events", methods=["GET"])
def list_custody_events():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    ds_id = request.args.get("drug_screen_id")
    items = list(db.custody_events.values())
    if ds_id is not None:
        items = [e for e in items if e["drug_screen_id"] == ds_id]
    # Custody events are ordered by per-screen seq (PRD §2.3 documented exception).
    items = sorted(items, key=lambda e: (e["drug_screen_id"], e["seq"]))
    if ds_id is not None:
        items = sorted(items, key=lambda e: e["seq"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return array_response([public(i) for i in page], limit, offset, total)


@bp.route("/clinic/custody-events/<ce_id>", methods=["GET"])
def get_custody_event(ce_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    evt = lookup.get_custody_event(ce_id)
    return object_response(public(evt), 200)
