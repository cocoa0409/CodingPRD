"""Charge line endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..calculations import refresh_total_and_estimate
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.serializers import serialize_charge
from ..services.validation import (
    get_charge_or_404,
    get_encounter_or_404,
    require_int,
    require_str,
    validate_cpt,
)
from ..store import LOCK, bump_version, common_fields_create, get_store, now_iso
from ._helpers import created, get_json_body, list_ok, ok


def register(app: Flask) -> None:
    @app.route("/encounters/<encounter_id>/charges", methods=["POST"])
    @require_auth("ChargeCaptureClerk")
    def create_charge(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        # State guard: PRD §3.4 — charge capture begins only once the encounter
        # is in ELIGIBILITY_VERIFIED.
        if enc["status"] != "ELIGIBILITY_VERIFIED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be ELIGIBILITY_VERIFIED to create charges; is {enc['status']}.",
            )
        body = get_json_body()
        cpt_code = require_str(body, "cpt_code")
        description = require_str(body, "description")
        quantity = require_int(body, "quantity", minimum=1)
        unit_price_cents = require_int(body, "unit_price_cents", minimum=0)
        validate_cpt(cpt_code)

        store = get_store()
        with LOCK:
            base = common_fields_create()
            charge = {
                **base,
                "encounter_id": encounter_id,
                "cpt_code": cpt_code,
                "description": description,
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "amount_cents": quantity * unit_price_cents,
                "status": "PENDING",
                "posted_at": None,
            }
            store.charges[charge["id"]] = charge
        return created(serialize_charge(charge))

    @app.route(
        "/encounters/<encounter_id>/charges/<charge_id>/post", methods=["POST"]
    )
    @require_auth("ChargeCaptureClerk")
    def post_charge(encounter_id, charge_id):
        enc = get_encounter_or_404(encounter_id)
        charge = get_charge_or_404(charge_id)
        # Ownership: charge must belong to encounter.
        if charge["encounter_id"] != encounter_id:
            raise ApiError("ERR_NOT_FOUND", "Charge does not belong to encounter.")

        # State guards on encounter and charge.
        if charge["status"] != "PENDING":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Charge must be PENDING to post; is {charge['status']}.",
            )
        if enc["status"] != "ELIGIBILITY_VERIFIED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be ELIGIBILITY_VERIFIED to post charges; is {enc['status']}.",
            )
        if int(charge["amount_cents"]) <= 0:
            raise ApiError(
                "ERR_INVALID_STATE",
                "Charge amount_cents must be > 0 to post.",
            )

        charge["status"] = "POSTED"
        charge["posted_at"] = now_iso()
        bump_version(charge)
        refresh_total_and_estimate(enc)
        return ok(serialize_charge(charge))

    @app.route(
        "/encounters/<encounter_id>/charges/<charge_id>/void", methods=["POST"]
    )
    @require_auth("ChargeCaptureClerk")
    def void_charge(encounter_id, charge_id):
        enc = get_encounter_or_404(encounter_id)
        charge = get_charge_or_404(charge_id)
        if charge["encounter_id"] != encounter_id:
            raise ApiError("ERR_NOT_FOUND", "Charge does not belong to encounter.")

        if charge["status"] not in ("PENDING", "POSTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Charge cannot be voided from status {charge['status']}.",
            )
        if enc["status"] not in ("ELIGIBILITY_VERIFIED", "CHARGES_CAPTURED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be ELIGIBILITY_VERIFIED or CHARGES_CAPTURED to void charges; is {enc['status']}.",
            )
        # If voiding a POSTED line, require no FINALIZED coding record.
        was_posted = charge["status"] == "POSTED"
        if was_posted:
            store = get_store()
            cr_id = store.coding_by_encounter.get(encounter_id)
            if cr_id is not None:
                cr = store.coding_records.get(cr_id)
                if cr is not None and cr["status"] == "FINALIZED":
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        "Cannot void a posted charge after coding is FINALIZED.",
                    )

        prev_status = charge["status"]
        charge["status"] = "VOIDED"
        bump_version(charge)
        if prev_status == "POSTED":
            refresh_total_and_estimate(enc)
        return ok(serialize_charge(charge))

    @app.route("/encounters/<encounter_id>/charges", methods=["GET"])
    @require_auth("ChargeCaptureClerk", "Coder", "Biller")
    def list_charges(encounter_id):
        get_encounter_or_404(encounter_id)
        limit, offset = parse_limit_offset()
        status_filter = parse_optional_str("status")
        store = get_store()
        items = [c for c in store.charges.values() if c["encounter_id"] == encounter_id]
        if status_filter is not None:
            items = [c for c in items if c["status"] == status_filter]
        items.sort(key=lambda c: c["created_at"])
        sliced, pag = paginate(items, limit, offset)
        return list_ok([serialize_charge(c) for c in sliced], pag)
