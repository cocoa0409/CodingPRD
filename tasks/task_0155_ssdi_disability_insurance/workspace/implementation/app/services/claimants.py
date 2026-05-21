"""Claimant lifecycle: register, get, patch, recompute QC aggregates."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from app import clock, store
from app.calculations import compute_qc_aggregates, qc_requirement_lookup
from app.errors import aod_after_filing, bad_request, version_mismatch
from app.util import new_uuid, parse_iso_date


_SSN_RE = re.compile(r"^[0-9]{4}$")


def _validate_dob_and_filing(dob: date, filing: date) -> None:
    # No explicit validation required by scaffold beyond AOD <= filing.
    pass


def _parse_input_dates(body: dict, fields: list[str]) -> dict[str, date]:
    parsed = {}
    for field in fields:
        if field not in body or body[field] is None:
            raise bad_request(f"Missing required field: {field}")
        parsed[field] = parse_iso_date(body[field], field)
    return parsed


def register_claimant(body: dict) -> dict:
    # Required fields per scaffold §1.5
    required = ["full_name", "date_of_birth", "filing_date", "alleged_onset_date", "ssn_last4"]
    for f in required:
        if f not in body or body[f] is None:
            raise bad_request(f"Missing required field: {f}")

    full_name = body["full_name"]
    if not isinstance(full_name, str) or not full_name.strip():
        raise bad_request("full_name must be a non-empty string")

    ssn = body["ssn_last4"]
    if not isinstance(ssn, str) or not _SSN_RE.match(ssn):
        raise bad_request("ssn_last4 must be a 4-digit numeric string")

    dob = parse_iso_date(body["date_of_birth"], "date_of_birth")
    filing = parse_iso_date(body["filing_date"], "filing_date")
    aod = parse_iso_date(body["alleged_onset_date"], "alleged_onset_date")
    if aod > filing:
        raise aod_after_filing("alleged_onset_date must be on or before filing_date")

    qc_required, qc_recent_required, _ = qc_requirement_lookup(dob, aod)

    now = clock.now()
    new_id = new_uuid()
    record = {
        "id": new_id,
        "full_name": full_name.strip(),
        "date_of_birth": dob,
        "filing_date": filing,
        "alleged_onset_date": aod,
        "established_onset_date": None,
        "total_qc_earned": 0,
        "qc_required": qc_required,
        "qc_recent_window": 0,
        "qc_recent_required": qc_recent_required,
        "insured_status": "NOT_INSURED",
        "ssn_last4": ssn,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock():
        store.claimants[new_id] = record
    return record


def get_claimant(claimant_id: str) -> dict:
    from app.routes._helpers import fetch_claimant
    return fetch_claimant(claimant_id)


def patch_claimant(claimant_id: str, body: dict) -> dict:
    from app.routes._helpers import fetch_claimant
    with store.lock():
        c = fetch_claimant(claimant_id)
        # OCC check
        if "version" in body and body["version"] is not None:
            if not isinstance(body["version"], int) or isinstance(body["version"], bool):
                raise bad_request("version must be an integer")
            if body["version"] != c["version"]:
                raise version_mismatch(
                    f"Stored version {c['version']} does not match supplied {body['version']}"
                )

        changed_aod = False
        if "full_name" in body and body["full_name"] is not None:
            if not isinstance(body["full_name"], str) or not body["full_name"].strip():
                raise bad_request("full_name must be a non-empty string")
            c["full_name"] = body["full_name"].strip()
        if "alleged_onset_date" in body and body["alleged_onset_date"] is not None:
            new_aod = parse_iso_date(body["alleged_onset_date"], "alleged_onset_date")
            if new_aod > c["filing_date"]:
                raise aod_after_filing("alleged_onset_date must be on or before filing_date")
            if new_aod != c["alleged_onset_date"]:
                c["alleged_onset_date"] = new_aod
                changed_aod = True

        # Re-run QC requirement lookup if AOD changed.
        if changed_aod:
            recompute_claimant_qc(c)

        c["updated_at"] = clock.now()
        c["version"] += 1
    return c


def recompute_claimant_qc(claimant: dict) -> None:
    """Recompute qc_required/qc_recent_required from age, then aggregates."""
    qc_required, qc_recent_required, recent_window = qc_requirement_lookup(
        claimant["date_of_birth"], claimant["alleged_onset_date"]
    )
    claimant["qc_required"] = qc_required
    claimant["qc_recent_required"] = qc_recent_required

    rows = [
        q for q in store.quarter_credits.values()
        if q["claimant_id"] == claimant["id"]
    ]
    total, recent, updated = compute_qc_aggregates(
        rows, claimant["alleged_onset_date"], recent_window
    )
    claimant["total_qc_earned"] = total
    claimant["qc_recent_window"] = recent
    if total >= qc_required and recent >= qc_recent_required:
        claimant["insured_status"] = "INSURED"
    else:
        claimant["insured_status"] = "NOT_INSURED"
    # Persist updated QC rows
    for row in updated:
        store.quarter_credits[row["id"]] = row
