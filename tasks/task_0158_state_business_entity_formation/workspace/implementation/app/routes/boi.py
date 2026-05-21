"""Beneficial owner + BOI report routes."""
from __future__ import annotations

from datetime import datetime
from math import floor

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import (
    APIError,
    err_entity_not_active,
    err_invalid_input,
    err_invalid_state,
    err_not_found,
)
from ..store import store
from ..timeutil import is_at_least_years, now as clock_now, parse_iso
from ..util import get_json_body, new_uuid, require_enum, require_str
from ..services import serializers
from ..services.calculations import compute_boi_penalty
from ..services.engine import (
    active_ownerships_for,
    emit_event,
    has_existing_initial_or_active_report,
    latest_boi_report_for,
    latest_current_or_corrected_report,
    recompute_compliance_status,
    touch,
)


bp = Blueprint("boi", __name__, url_prefix="/business-registry")


# ---- Beneficial owners --------------------------------------------------------

@bp.post("/beneficial-owners")
@require_auth(["Filer"])
def create_beneficial_owner():
    body = get_json_body()
    full_legal_name = require_str(body, "full_legal_name", min_len=1, max_len=200)
    dob_raw = body.get("date_of_birth")
    if dob_raw is None:
        raise err_invalid_input("Missing required field: date_of_birth")
    dob = parse_iso(dob_raw)
    if dob is None:
        raise err_invalid_input("date_of_birth must be a valid ISO 8601 date or datetime")
    residential_address = require_str(body, "residential_address", min_len=1, max_len=500)
    doc_type = require_enum(body, "identifying_document_type",
                            {"US_PASSPORT", "STATE_DRIVERS_LICENSE", "STATE_ID", "FOREIGN_PASSPORT"})
    doc_number = require_str(body, "identifying_document_number", min_len=1, max_len=50)
    with store.lock:
        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "full_legal_name": full_legal_name,
            "date_of_birth": dob,
            "residential_address": residential_address,
            "identifying_document_type": doc_type,
            "identifying_document_number": doc_number,
        }
        store.beneficial_owners[row["id"]] = row
        return jsonify(object_response(serializers.beneficial_owner(row))), 201


# ---- BOI reports --------------------------------------------------------------

def _report_or_404(report_id):
    row = store.boi_reports.get(report_id)
    if row is None:
        raise err_not_found(f"BOI report {report_id!r} not found")
    return row


@bp.post("/boi-reports")
@require_auth(["Filer"])
def create_boi_report():
    caller = current_caller()
    body = get_json_body()
    business_entity_id = require_str(body, "business_entity_id")
    filing_type = require_enum(body, "filing_type", {"INITIAL", "UPDATE", "CORRECTION"})
    with store.lock:
        entity = store.business_entities.get(business_entity_id)
        if entity is None:
            raise err_not_found(f"business_entity_id {business_entity_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != business_entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        if filing_type == "INITIAL" and has_existing_initial_or_active_report(business_entity_id):
            raise err_invalid_state("An INITIAL BOI report cannot be filed when a prior FILED/CURRENT/STALE/CORRECTED report exists")
        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "business_entity_id": business_entity_id,
            "filing_type": filing_type,
            "status": "DRAFT",
            "filed_at": None,
            "stale_at": None,
            "penalty_cents": 0,
            "days_stale_at_filing": 0,
        }
        store.boi_reports[row["id"]] = row
        return jsonify(object_response(serializers.boi_report(row))), 201


@bp.post("/boi-reports/<report_id>/file")
@require_auth(["Filer"])
def file_boi_report(report_id):
    caller = current_caller()
    with store.lock:
        row = _report_or_404(report_id)
        if row.get("status") != "DRAFT":
            raise err_invalid_state("BOI report is not in DRAFT")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        now = clock_now()
        active = active_ownerships_for(row.get("business_entity_id"), at=now)
        # Owner age check on every active owner.
        for o in active:
            owner = store.beneficial_owners.get(o.get("beneficial_owner_id"))
            if owner is None:
                continue
            dob = owner.get("date_of_birth")
            if dob is None or not is_at_least_years(dob, now, 18):
                raise APIError("ERR_OWNER_UNDERAGE",
                               f"Beneficial owner {owner.get('id')} is < 18 years old", 422)
        # Ownership sum == 10000
        total_bps = sum(int(o.get("ownership_percent_basis_points", 0)) for o in active)
        if total_bps != 10000:
            raise APIError("ERR_OWNERSHIP_NOT_100",
                           f"Sum of active ownership basis points is {total_bps}, not 10000", 422)
        # Transition DRAFT -> FILED -> CURRENT atomically.
        row["status"] = "CURRENT"
        row["filed_at"] = now
        touch(row, ts=now)
        emit_event(row.get("business_entity_id"), "BOI_FILED",
                   {"report_id": row["id"], "filing_type": row.get("filing_type")},
                   occurred_at=now)
        # If filing_type is UPDATE or CORRECTION, mark the previous STALE/CURRENT report
        # CORRECTED (and finalize its penalty if it was STALE).
        prior_stale = None
        for r in store.boi_reports.values():
            if r is row:
                continue
            if r.get("business_entity_id") != row.get("business_entity_id"):
                continue
            if r.get("status") in ("STALE", "CURRENT"):
                # When filing_type is UPDATE/CORRECTION, supersede the latest non-corrected.
                if row.get("filing_type") in ("UPDATE", "CORRECTION"):
                    if prior_stale is None or (r.get("created_at") or now) > (prior_stale.get("created_at") or now):
                        prior_stale = r
        if prior_stale is not None:
            was_stale = prior_stale.get("status") == "STALE"
            if was_stale and prior_stale.get("stale_at") is not None:
                days = floor((now - prior_stale["stale_at"]).total_seconds() / 86400.0)
                if days < 0:
                    days = 0
                penalty = min(days * 59100, 1_000_000)
                prior_stale["days_stale_at_filing"] = days
                prior_stale["penalty_cents"] = penalty
            prior_stale["status"] = "CORRECTED"
            touch(prior_stale, ts=now)
            emit_event(row.get("business_entity_id"), "BOI_CORRECTED",
                       {"report_id": prior_stale["id"]}, occurred_at=now)
            # Clear any pending stale timer
            store.ownership_change_at.pop(row.get("business_entity_id"), None)
        recompute_compliance_status(row.get("business_entity_id"), at=now)
        return jsonify(object_response(serializers.boi_report(row))), 200
