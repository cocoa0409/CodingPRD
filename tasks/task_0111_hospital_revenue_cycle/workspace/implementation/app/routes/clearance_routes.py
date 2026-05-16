"""Payer clearance endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..calculations import run_clearance_and_final
from ..errors import ApiError
from ..services.serializers import serialize_clearance
from ..services.validation import (
    get_encounter_or_404,
    require_int,
    require_str,
)
from ..store import LOCK, append_only_fields_create, bump_version, get_store, now_iso
from ._helpers import created, get_json_body


VALID_DECISIONS = {"APPROVED", "PARTIAL", "DENIED"}


def register(app: Flask) -> None:
    @app.route("/encounters/<encounter_id>/clearance", methods=["POST"])
    @require_auth("Biller")
    def submit_clearance(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        body = get_json_body()
        decision = require_str(body, "decision")
        # allowed_amount_cents required (must be present even if 0).
        if "allowed_amount_cents" not in body:
            raise ApiError("ERR_INVALID_INPUT", "Missing required field: allowed_amount_cents")
        allowed = body["allowed_amount_cents"]
        if isinstance(allowed, bool) or not isinstance(allowed, int) or allowed < 0:
            raise ApiError("ERR_INVALID_INPUT", "allowed_amount_cents must be a non-negative integer.")
        denial_reason_code = body.get("denial_reason_code")
        if denial_reason_code is not None and not isinstance(denial_reason_code, str):
            raise ApiError("ERR_INVALID_INPUT", "denial_reason_code must be a string.")

        if decision not in VALID_DECISIONS:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid decision: {decision!r}")

        # State guard: encounter must be CODED.
        if enc["status"] != "CODED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be CODED to record clearance; is {enc['status']}.",
            )

        # business_constraint priority 11: allowed <= total_charges_cents.
        total_charges = int(enc.get("total_charges_cents", 0))
        if allowed > total_charges:
            raise ApiError(
                "ERR_ALLOWED_EXCEEDS_CHARGES",
                f"allowed_amount_cents {allowed} exceeds total_charges_cents {total_charges}.",
            )

        # business_constraint priority 12: payload internal consistency.
        if decision == "DENIED":
            if allowed != 0:
                raise ApiError(
                    "ERR_INVALID_CLEARANCE_PAYLOAD",
                    "DENIED decision requires allowed_amount_cents == 0.",
                )
            if not denial_reason_code:
                raise ApiError(
                    "ERR_INVALID_CLEARANCE_PAYLOAD",
                    "DENIED decision requires denial_reason_code.",
                )
        elif decision == "PARTIAL":
            if not denial_reason_code:
                raise ApiError(
                    "ERR_INVALID_CLEARANCE_PAYLOAD",
                    "PARTIAL decision requires denial_reason_code.",
                )

        # Persist ClearanceDecision and run calcs.
        store = get_store()
        with LOCK:
            base = append_only_fields_create()
            cd = {
                **base,
                "encounter_id": encounter_id,
                "decision": decision,
                "allowed_amount_cents": allowed,
                "denial_reason_code": denial_reason_code,
                "decided_at": now_iso(),
            }
            store.clearance_decisions[cd["id"]] = cd
            # Run payer + final patient_responsibility calc.
            run_clearance_and_final(enc, cd)
            enc["status"] = "CLEARED"
            bump_version(enc)

        return created(serialize_clearance(cd))
