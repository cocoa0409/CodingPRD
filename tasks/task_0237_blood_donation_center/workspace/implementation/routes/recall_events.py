"""Recall / lookback events: open (runs cascade synchronously), reads."""
from flask import Blueprint, request

import db
import lookup
from common import get_json_body, paginate, require_enum, require_integer, require_string
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_recall
from timeutil import SECONDS_PER_DAY, iso_to_epoch

bp = Blueprint("recall_events", __name__)

REASONS = {"POSITIVE_RETEST", "POST_DONATION_ILLNESS", "TRAVEL_DISCLOSURE", "OTHER"}
NON_TERMINAL_UNIT_STATES = {"QUARANTINED", "AVAILABLE", "RESERVED"}


@bp.route("/blood-bank/recall-events", methods=["POST"])
@require_roles("InventoryManager")
def open_recall():
    body = get_json_body()
    with db.lock:
        center_id = require_string(body, "center_id")
        donor_id = require_string(body, "donor_id")
        reason = require_enum(body, "reason", REASONS)
        lookback_days = require_integer(body, "lookback_days", minimum=1)

        # existence: center then donor (declared order center_id, donor_id)
        center = lookup.center(center_id)
        donor = lookup.donor(donor_id)

        recall = {
            "center_id": center_id,
            "donor_id": donor_id,
            "reason": reason,
            "lookback_days": lookback_days,
            "units_recalled_count": 0,
            "donations_in_scope_count": 0,
            "status": "OPEN",
        }
        db.stamp_new(recall)
        db.recall_events[recall["id"]] = recall

        # Cascade hop 1: scope selection (collected_at >= window_start)
        window_start = iso_to_epoch(center["current_utc"]) - lookback_days * SECONDS_PER_DAY
        in_scope = [
            d for d in db.donations.values()
            if d["donor_id"] == donor_id
            and d.get("collected_at")
            and iso_to_epoch(d["collected_at"]) >= window_start
        ]
        in_scope.sort(key=lambda d: (d["collected_at"], d["created_at"]))
        recall["donations_in_scope_count"] = len(in_scope)

        units_recalled = 0
        for donation in in_scope:
            # hop 2: discard the donation unless already DISCARDED
            if donation["status"] != "DISCARDED":
                donation["status"] = "DISCARDED"
                db.touch(donation)
            # hop 3: recall non-terminal units, decrement buckets
            for unit in db.blood_units.values():
                if unit["donation_id"] == donation["id"] and \
                        unit["status"] in NON_TERMINAL_UNIT_STATES:
                    prev = unit["status"]
                    unit["status"] = "RECALLED"
                    db.touch(unit)
                    if prev == "AVAILABLE":
                        domain.adjust_bucket(unit["center_id"], unit["blood_type"],
                                             unit["component"], available_delta=-1)
                    elif prev == "RESERVED":
                        domain.adjust_bucket(unit["center_id"], unit["blood_type"],
                                             unit["component"], reserved_delta=-1)
                    units_recalled += 1
        recall["units_recalled_count"] = units_recalled

        # hop 4: POSITIVE_RETEST raises a permanent infectious deferral
        if reason == "POSITIVE_RETEST":
            domain.create_deferral(
                donor, center, "INFECTIOUS_RISK", "PERMANENT",
                "Auto-deferral from POSITIVE_RETEST recall",
            )

        recall["status"] = "CLOSED"
        db.touch(recall)
        return success(serialize_recall(recall), status=201)


@bp.route("/blood-bank/recall-events", methods=["GET"])
@require_roles("CenterAdmin", "InventoryManager")
def list_recalls():
    center_id = request.args.get("center_id")
    donor_id = request.args.get("donor_id")
    status = request.args.get("status")
    with db.lock:
        rows = list(db.recall_events.values())
        if center_id is not None:
            rows = [r for r in rows if r["center_id"] == center_id]
        if donor_id is not None:
            rows = [r for r in rows if r["donor_id"] == donor_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_recall(r) for r in page], limit, offset, total)


@bp.route("/blood-bank/recall-events/<recall_event_id>", methods=["GET"])
@require_roles("CenterAdmin", "InventoryManager")
def get_recall(recall_event_id):
    with db.lock:
        recall = lookup.recall_event(recall_event_id)
        return success(serialize_recall(recall))
