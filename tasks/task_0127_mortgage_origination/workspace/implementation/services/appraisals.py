"""Appraisal service (PRD §3.4)."""

import db
from config import (
    APR_COMPLETED,
    APR_ORDERED,
    APR_REJECTED,
    PMI_THRESHOLD,
)
from errors import (
    ERR_APPRAISAL_OVERLAP,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    raise_error,
)
from services import calculations, lookups
from services.common import bump, init_common, occ_check
from services.validation import require_int, require_string
from utils import parse_iso, to_iso_millis


def create(application: dict, body: dict) -> dict:
    """Order an Appraisal in ORDERED."""
    report_date_text = require_string(body, "report_date")
    report_date = parse_iso(report_date_text)
    if report_date is None:
        from errors import ERR_VALIDATION
        raise_error(ERR_VALIDATION, "report_date must be a valid ISO 8601 datetime.")

    # Priority 15: appraisal-validity overlap.
    if lookups.any_completed_appraisal_unexpired(application["id"]):
        raise_error(
            ERR_APPRAISAL_OVERLAP,
            "An unexpired COMPLETED Appraisal already exists for this application.",
        )

    appraisal = init_common(
        {
            "application_id": application["id"],
            "appraised_value_cents": None,
            "report_date": to_iso_millis(report_date),
            "valid_until": None,
            "status": APR_ORDERED,
        }
    )
    db.appraisals[appraisal["id"]] = appraisal
    return appraisal


def get_or_404_by_app(application_id: str):
    """Return the most recent appraisal for the application (single-appraisal model)."""
    candidates = [a for a in db.appraisals.values() if a["application_id"] == application_id]
    if not candidates:
        raise_error(ERR_RESOURCE_NOT_FOUND, "Appraisal not found.")
    return max(candidates, key=lambda a: a["created_at"])


def complete(application: dict, body: dict) -> dict:
    appraisal = get_or_404_by_app(application["id"])
    occ_check(appraisal, body)
    if appraisal["status"] != APR_ORDERED:
        raise_error(ERR_INVALID_STATE, "Appraisal must be in ORDERED.")
    appraised_value_cents = require_int(body, "appraised_value_cents", min_value=1)

    appraisal["appraised_value_cents"] = int(appraised_value_cents)
    appraisal["status"] = APR_COMPLETED
    appraisal["valid_until"] = calculations.compute_appraisal_valid_until(
        parse_iso(appraisal["report_date"])
    )
    bump(appraisal)

    # Bubble: LTV recompute + PMI flag (PRD §2.6).
    if int(appraised_value_cents) < int(application["sale_price_cents"]):
        new_ltv = calculations.compute_ltv(application, appraisal)
        application["ltv_ratio"] = float(new_ltv) if new_ltv is not None else None
        if new_ltv is not None and new_ltv > PMI_THRESHOLD:
            application["pmi_required"] = True
        bump(application)
    return appraisal


def reject(application: dict, body: dict) -> dict:
    appraisal = get_or_404_by_app(application["id"])
    occ_check(appraisal, body)
    if appraisal["status"] != APR_ORDERED:
        raise_error(ERR_INVALID_STATE, "Appraisal must be in ORDERED.")
    appraisal["status"] = APR_REJECTED
    bump(appraisal)
    return appraisal
