"""Coding record endpoints."""
from __future__ import annotations

from collections import Counter

from flask import Flask

from ..auth import require_auth
from ..calculations import charge_total_aggregation
from ..errors import ApiError
from ..services.serializers import serialize_coding
from ..services.validation import (
    get_encounter_or_404,
    require_bool,
    require_str,
    validate_cpt,
    validate_cpt_list,
    validate_icd10,
)
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import created, get_json_body, ok


def register(app: Flask) -> None:
    @app.route("/encounters/<encounter_id>/coding", methods=["POST"])
    @require_auth("Coder")
    def submit_coding(encounter_id):
        enc = get_encounter_or_404(encounter_id)
        body = get_json_body()
        # primary_icd10 is required; format validation (ERR_INVALID_ICD10)
        # is the PRD-declared rejection path for any value that fails the
        # ICD-10-CM pattern — including the empty string. Do not pre-empt
        # with a generic missing-field error.
        if "primary_icd10" not in body or not isinstance(
            body.get("primary_icd10"), str
        ):
            # Non-string (or absent) is also a format failure under the
            # ICD-10-CM rule — there is no ERR_INVALID_INPUT in the catalogue.
            raise ApiError(
                "ERR_INVALID_ICD10",
                f"Invalid ICD-10 code: {body.get('primary_icd10')!r}",
            )
        primary_icd10 = body["primary_icd10"]
        secondary_icd10 = body.get("secondary_icd10", []) or []
        if not isinstance(secondary_icd10, list):
            raise ApiError("ERR_INVALID_INPUT", "secondary_icd10 must be a list.")
        cpt_codes_raw = body.get("cpt_codes")
        if cpt_codes_raw is None or not isinstance(cpt_codes_raw, list):
            raise ApiError("ERR_INVALID_INPUT", "cpt_codes must be a list.")
        cpt_codes: list[str] = list(cpt_codes_raw)
        coder_id = require_str(body, "coder_id")
        finalize = require_bool(body, "finalize")

        store = get_store()
        existing_cr_id = store.coding_by_encounter.get(encounter_id)

        # State guard: encounter must be CHARGES_CAPTURED.
        if enc["status"] != "CHARGES_CAPTURED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be CHARGES_CAPTURED to submit coding; is {enc['status']}.",
            )

        # If a FINALIZED CodingRecord already exists, reject as duplicate.
        if existing_cr_id is not None:
            existing = store.coding_records.get(existing_cr_id)
            if existing is not None and existing["status"] == "FINALIZED":
                raise ApiError(
                    "ERR_DUPLICATE_CODING_RECORD",
                    "A finalized coding record already exists for this encounter.",
                )

        # Format checks: priority 8 (ICD-10) before 9 (CPT).
        validate_icd10(primary_icd10)
        for sec in secondary_icd10:
            validate_icd10(sec)
        validate_cpt_list(cpt_codes)

        # Cross-resource referential: cpt_codes multiset must match non-VOIDED charges.
        # Only relevant on finalize=true.
        if finalize:
            non_voided_cpts = [
                c["cpt_code"]
                for c in store.charges.values()
                if c["encounter_id"] == encounter_id and c["status"] != "VOIDED"
            ]
            if Counter(non_voided_cpts) != Counter(cpt_codes):
                raise ApiError(
                    "ERR_CODING_CPT_MISMATCH",
                    "CodingRecord.cpt_codes multiset does not match non-VOIDED ChargeItem.cpt_code multiset.",
                )

        with LOCK:
            # Re-check duplicate inside lock.
            existing_cr_id = store.coding_by_encounter.get(encounter_id)
            if existing_cr_id is not None:
                existing = store.coding_records.get(existing_cr_id)
                if existing is None:
                    pass
                else:
                    if existing["status"] == "FINALIZED":
                        raise ApiError(
                            "ERR_DUPLICATE_CODING_RECORD",
                            "A finalized coding record already exists for this encounter.",
                        )
                    # DRAFT path: update the existing record.
                    existing["primary_icd10"] = primary_icd10
                    existing["secondary_icd10"] = list(secondary_icd10)
                    existing["cpt_codes"] = list(cpt_codes)
                    existing["coder_id"] = coder_id
                    if finalize:
                        existing["status"] = "FINALIZED"
                    bump_version(existing)
                    if finalize:
                        # Transition encounter, refresh totals.
                        enc["status"] = "CODED"
                        bump_version(enc)
                        # Re-run charge_total_aggregation per scaffold side-effect.
                        enc["total_charges_cents"] = charge_total_aggregation(encounter_id)
                        bump_version(enc)
                    return created(serialize_coding(existing))

            # Create new coding record.
            base = common_fields_create()
            cr = {
                **base,
                "encounter_id": encounter_id,
                "primary_icd10": primary_icd10,
                "secondary_icd10": list(secondary_icd10),
                "cpt_codes": list(cpt_codes),
                "coder_id": coder_id,
                "status": "FINALIZED" if finalize else "DRAFT",
            }
            store.coding_records[cr["id"]] = cr
            store.coding_by_encounter[encounter_id] = cr["id"]

            if finalize:
                enc["status"] = "CODED"
                bump_version(enc)
                enc["total_charges_cents"] = charge_total_aggregation(encounter_id)
                bump_version(enc)

        return created(serialize_coding(cr))

    @app.route("/encounters/<encounter_id>/coding", methods=["GET"])
    @require_auth("Coder", "Biller")
    def get_coding(encounter_id):
        get_encounter_or_404(encounter_id)
        store = get_store()
        cr_id = store.coding_by_encounter.get(encounter_id)
        if cr_id is None:
            raise ApiError("ERR_NOT_FOUND", "No coding record for this encounter.")
        cr = store.coding_records.get(cr_id)
        if cr is None:
            raise ApiError("ERR_NOT_FOUND", "No coding record for this encounter.")
        return ok(serialize_coding(cr))
