"""Contract signing (PRD §3.6, §3.7) — pins rates, computes total/deposit, opens invoice."""
from flask import Blueprint, request

import errors
from db import store, LOCK
from middleware import get_identity, require_role, parse_pagination, get_json_body
from response import object_response, array_response
from services.common import base_fields, touch, paginate
from services import calc
from services.domain import confirmed_faces

bp = Blueprint("contracts", __name__)


def serialize_contract(c):
    return {
        "id": c["id"],
        "event_id": c["event_id"],
        "lead_artist_id": c["lead_artist_id"],
        "pinned_hair_rate_cents": c["pinned_hair_rate_cents"],
        "pinned_makeup_rate_cents": c["pinned_makeup_rate_cents"],
        "pinned_travel_rate_per_km_cents": c["pinned_travel_rate_per_km_cents"],
        "contracted_total_cents": c["contracted_total_cents"],
        "deposit_due_cents": c["deposit_due_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "event_id": inv["event_id"],
        "contract_id": inv["contract_id"],
        "deposit_amount_cents": inv["deposit_amount_cents"],
        "balance_amount_cents": inv["balance_amount_cents"],
        "amount_paid_cents": inv["amount_paid_cents"],
        "deposit_status": inv["deposit_status"],
        "balance_status": inv["balance_status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


@bp.route("/bridal-beauty/contracts", methods=["POST"])
def sign_contract():
    user_id, role = get_identity()
    require_role(role, {"Client"})
    body = get_json_body()

    with LOCK:
        # Body well-formedness + existence (PRD §2.5, §2.9).
        if "event_id" not in body or not isinstance(body["event_id"], str) or not body["event_id"]:
            raise errors.invalid_request("event_id is required")
        if ("lead_artist_id" not in body or not isinstance(body["lead_artist_id"], str)
                or not body["lead_artist_id"]):
            raise errors.invalid_request("lead_artist_id is required")
        if "expected_event_version" not in body:
            raise errors.invalid_request("expected_event_version is required")
        ev = body["expected_event_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise errors.invalid_request("expected_event_version must be an integer")

        event_id = body["event_id"]
        lead_artist_id = body["lead_artist_id"]

        event = store.events.get(event_id)
        if event is None:
            raise errors.not_found()
        artist = store.artists.get(lead_artist_id)
        if artist is None:
            raise errors.not_found()

        # Ownership (priority 4, before OCC and state).
        if user_id != event["client_id"]:
            raise errors.not_event_owner()

        # OCC (priority 5).
        if ev != event["version"]:
            raise errors.stale_event_version()

        # State (priority 6): event must be QUOTED.
        if event["status"] != "QUOTED":
            raise errors.invalid_state("Event is not QUOTED")

        # Trial completion (priority 7).
        if event["trial_required"]:
            has_completed = any(
                t for t in store.trials.values()
                if t["event_id"] == event_id and t["status"] == "COMPLETED"
            )
            if not has_completed:
                raise errors.trial_not_completed()

        # Artist active (priority 8).
        if artist["status"] != "ACTIVE":
            raise errors.artist_not_active()

        # At least one CONFIRMED face.
        confirmed = confirmed_faces(event_id)
        if len(confirmed) < 1:
            raise errors.invalid_state("Event has no CONFIRMED faces")

        # Create contract SIGNED, pinning rates.
        rec = base_fields()
        rec.update({
            "event_id": event_id,
            "lead_artist_id": lead_artist_id,
            "pinned_hair_rate_cents": artist["hair_rate_per_face_cents"],
            "pinned_makeup_rate_cents": artist["makeup_rate_per_face_cents"],
            "pinned_travel_rate_per_km_cents": artist["travel_rate_per_km_cents"],
            "status": "SIGNED",
            "contracted_total_cents": 0,
            "deposit_due_cents": 0,
        })
        total = calc.contract_total(confirmed, rec, event["venue_distance_km"])
        rec["contracted_total_cents"] = total
        rec["deposit_due_cents"] = calc.deposit_split(total)
        store.contracts[rec["id"]] = rec

        # Auto-open Invoice (cascade hop 1).
        inv = base_fields()
        inv.update({
            "event_id": event_id,
            "contract_id": rec["id"],
            "deposit_amount_cents": rec["deposit_due_cents"],
            "balance_amount_cents": 0,
            "amount_paid_cents": 0,
            "deposit_status": "DUE",
            "balance_status": "NOT_DUE",
            "_relief_written_off": 0,
        })
        # Initial balance reconcile: gross_due - paid - relief.
        inv["balance_amount_cents"] = total
        store.invoices[inv["id"]] = inv

        # Advance event QUOTED -> CONTRACTED, bump version.
        event["status"] = "CONTRACTED"
        touch(event)

        return object_response(serialize_contract(rec), 201)


@bp.route("/bridal-beauty/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    c = store.contracts.get(contract_id)
    if c is None:
        raise errors.not_found()
    return object_response(serialize_contract(c), 200)


@bp.route("/bridal-beauty/contracts", methods=["GET"])
def list_contracts():
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    limit, offset = parse_pagination()
    event_f = request.args.get("event_id")
    lead_f = request.args.get("lead_artist_id")
    items = list(store.contracts.values())
    if event_f is not None:
        items = [c for c in items if c["event_id"] == event_f]
    if lead_f is not None:
        items = [c for c in items if c["lead_artist_id"] == lead_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_contract(c) for c in page], limit, offset, total)
