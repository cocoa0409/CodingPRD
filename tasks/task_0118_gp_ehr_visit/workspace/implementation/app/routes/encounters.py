"""Encounter endpoints: schedule, get, patch, check-in, complete, cancel, cpt-line-items."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint

from ..auth import (
    ROLE_BILLING_CLERK,
    ROLE_CLINIC_ADMIN,
    ROLE_NURSE,
    ROLE_PATIENT_PORTAL,
    ROLE_PROVIDER,
    ROLE_RECEPTIONIST,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_forbidden,
    err_invalid_billing_units,
    err_invalid_encounter_state,
    err_invalid_input,
    err_invalid_time_range,
    err_no_billable_lines,
    err_not_found,
    err_patient_time_conflict,
    err_portal_disabled,
    err_provider_time_conflict,
    err_reference_not_found,
)
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, no_content, ok
from ..services.audit import write_audit
from ..services.calculations import (
    compute_bmi,
    cpt_billing_allowed_for_encounter,
    cpt_billing_charge,
)
from ..services.hedis import recompute_partial_on_encounter_complete
from ..services.lookups import (
    get_cpt_fee,
    get_cpt_line_item,
    get_encounter,
    get_patient,
    get_provider,
)
from ..services.mutations import bump
from ..services.serialize import cpt_line_item_to_dict, encounter_to_dict
from ..store import store

bp = Blueprint("encounters", __name__)


ENCOUNTER_TYPES = ["CONSULTATION", "PHYSICAL", "VACCINATION"]
ENCOUNTER_TERMINAL = {"COMPLETED", "CANCELLED", "NO_SHOW"}
CPT_PATTERN = r"^[0-9]{5}$"


def _enforce_portal_self_for_encounter(enc: dict, caller_id: str, caller_role: str) -> None:
    if caller_role != ROLE_PATIENT_PORTAL:
        return
    s = store()
    patient = s.patients.get(enc["patient_id"])
    if patient is None or not patient.get("portal_enabled"):
        raise err_portal_disabled()
    if patient["id"] != caller_id:
        raise err_portal_disabled()


def _provider_has_overlap(provider_id: str, start: datetime, end: datetime) -> bool:
    """Closed-open intervals: existing [a,b) overlaps new [s,e) iff a < e AND s < b."""
    s = store()
    for enc in s.encounters.values():
        if enc["provider_id"] != provider_id:
            continue
        if enc["status"] in ENCOUNTER_TERMINAL:
            continue
        a, b = enc["scheduled_start"], enc["scheduled_end"]
        if a < end and start < b:
            return True
    return False


def _patient_has_overlap_buffered(patient_id: str, start: datetime, end: datetime) -> bool:
    """Closed-closed with 15-minute buffer on each side.

    The new window is rejected if any other non-terminal encounter for the patient
    ends within 15 minutes BEFORE the new scheduled_start OR begins within 15
    minutes AFTER the new scheduled_end. Equivalent to closed-closed overlap on
    [start - 15min, end + 15min] vs existing [a, b].
    """
    s = store()
    buf = timedelta(minutes=15)
    new_lo = start - buf
    new_hi = end + buf
    for enc in s.encounters.values():
        if enc["patient_id"] != patient_id:
            continue
        if enc["status"] in ENCOUNTER_TERMINAL:
            continue
        a, b = enc["scheduled_start"], enc["scheduled_end"]
        # closed-closed overlap: a <= new_hi AND new_lo <= b
        if a <= new_hi and new_lo <= b:
            return True
    return False


# ---------- Schedule encounter ----------

@bp.route("/patients/<patient_id>/encounters", methods=["POST"])
@require_roles(ROLE_RECEPTIONIST, ROLE_CLINIC_ADMIN)
def schedule_encounter(patient_id: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        # Path existence
        patient = get_patient(patient_id)
        # Body reference existence
        provider_id = assert_string(body.get("provider_id"), "provider_id")
        provider = get_provider(provider_id, source="body")
        encounter_type = assert_enum(body.get("encounter_type"), "encounter_type", ENCOUNTER_TYPES)
        start = parse_iso8601(body.get("scheduled_start"), "scheduled_start")
        end = parse_iso8601(body.get("scheduled_end"), "scheduled_end")
        chief_complaint = body.get("chief_complaint")
        if chief_complaint is not None and not isinstance(chief_complaint, str):
            raise err_invalid_input("chief_complaint must be a string")

        # Validations (priority order):
        # 12: ERR_INVALID_TIME_RANGE
        if not (end > start):
            raise err_invalid_time_range("scheduled_end must be after scheduled_start")
        if (end - start) > timedelta(minutes=120):
            raise err_invalid_time_range("scheduled duration must be <= 120 minutes")

        # 13: ERR_PROVIDER_TIME_CONFLICT
        if _provider_has_overlap(provider_id, start, end):
            raise err_provider_time_conflict()
        # 14: ERR_PATIENT_TIME_CONFLICT
        if _patient_has_overlap_buffered(patient_id, start, end):
            raise err_patient_time_conflict()

        ts = now()
        row = {
            "id": new_uuid(),
            "patient_id": patient_id,
            "provider_id": provider_id,
            "encounter_type": encounter_type,
            "scheduled_start": start,
            "scheduled_end": end,
            "actual_start": None,
            "actual_end": None,
            "chief_complaint": chief_complaint,
            "vital_signs": None,
            "bmi": None,
            "status": "SCHEDULED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.encounters[row["id"]] = row
    return created(encounter_to_dict(row))


# ---------- Get encounter ----------

@bp.route("/encounters/<eid>", methods=["GET"])
@require_roles(
    ROLE_RECEPTIONIST, ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN, ROLE_PATIENT_PORTAL
)
def get_encounter_route(eid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        row = get_encounter(eid)
        _enforce_portal_self_for_encounter(row, _caller_id, _caller_role)
    return ok(encounter_to_dict(row))


# ---------- Patch encounter (vital_signs, chief_complaint) ----------

@bp.route("/encounters/<eid>", methods=["PATCH"])
@require_roles(ROLE_NURSE, ROLE_PROVIDER)
def patch_encounter(eid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        enc = get_encounter(eid)
        if enc["status"] != "CHECKED_IN":
            raise err_invalid_encounter_state(
                "vital_signs/chief_complaint may only be updated on a CHECKED_IN encounter"
            )

        if "vital_signs" in body and body["vital_signs"] is not None:
            vs = body["vital_signs"]
            if not isinstance(vs, dict):
                raise err_invalid_input("vital_signs must be an object")
            enc["vital_signs"] = dict(vs)
        if "chief_complaint" in body and body["chief_complaint"] is not None:
            cc = assert_string(body["chief_complaint"], "chief_complaint")
            enc["chief_complaint"] = cc

        occ_check(body.get("version"), enc["version"])
        bump(enc)
    return ok(encounter_to_dict(enc))


# ---------- Check-in ----------

@bp.route("/encounters/<eid>/check-in", methods=["POST"])
@require_roles(ROLE_NURSE, ROLE_RECEPTIONIST)
def check_in(eid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        enc = get_encounter(eid)
        if enc["status"] != "SCHEDULED":
            raise err_invalid_encounter_state("check-in requires SCHEDULED status")
        patient = s.patients.get(enc["patient_id"])
        provider = s.providers.get(enc["provider_id"])
        if patient is None or patient.get("status") != "ACTIVE":
            raise err_invalid_encounter_state("patient must be ACTIVE for check-in")
        if provider is None or provider.get("status") != "ACTIVE":
            raise err_invalid_encounter_state("provider must be ACTIVE for check-in")
        threshold = enc["scheduled_start"] - timedelta(minutes=30)
        if now() < threshold:
            raise err_invalid_encounter_state(
                "check-in not yet permitted (earliest is scheduled_start - 30 min)"
            )
        occ_check(body.get("version"), enc["version"])
        enc["status"] = "CHECKED_IN"
        enc["actual_start"] = now()
        bump(enc)
    return ok(encounter_to_dict(enc))


# ---------- Complete ----------

@bp.route("/encounters/<eid>/complete", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def complete_encounter(eid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        enc = get_encounter(eid)
        if enc["status"] != "CHECKED_IN":
            raise err_invalid_encounter_state("complete requires CHECKED_IN status")

        # Business-safety / constraint validation in priority order:
        # ERR_NO_BILLABLE_LINES (priority 16)
        lines = [li for li in s.cpt_line_items.values() if li["encounter_id"] == eid]
        # Type-specific gating first (these are "if encounter_type ==" preconditions in §1.2)
        if enc["encounter_type"] == "PHYSICAL":
            vs = enc.get("vital_signs") or {}
            required = ["bp_systolic", "bp_diastolic", "pulse", "temp_c", "weight_kg", "height_cm"]
            for k in required:
                v = vs.get(k)
                if v is None:
                    raise err_invalid_encounter_state(
                        f"PHYSICAL completion requires all vital_signs fields populated (missing {k})"
                    )
        elif enc["encounter_type"] == "CONSULTATION":
            cc = enc.get("chief_complaint")
            if not isinstance(cc, str) or not cc.strip():
                raise err_invalid_encounter_state(
                    "CONSULTATION completion requires non-empty chief_complaint"
                )

        if not lines:
            raise err_no_billable_lines()

        occ_check(body.get("version"), enc["version"])

        # Cascade ordered per scaffold:
        enc["actual_end"] = now()
        enc["status"] = "COMPLETED"

        # BMI for PHYSICAL
        if enc["encounter_type"] == "PHYSICAL":
            vs = enc["vital_signs"]
            enc["bmi"] = compute_bmi(vs["weight_kg"], vs["height_cm"])

        # Snapshot is_preventive onto each CptLineItem from catalog
        for li in lines:
            cat = s.cpt_fee_catalog.get(li["cpt_code"])
            if cat is not None:
                li["is_preventive"] = bool(cat.get("is_preventive", False))

        # Recompute allowed_amount_cents on every line
        cpt_billing_allowed_for_encounter(eid)

        bump(enc)

        # Recompute HEDIS for current year (AWV and CBP only) — partial cascade
        year = now().year
        recompute_partial_on_encounter_complete(enc["patient_id"], year)
    return ok(encounter_to_dict(enc))


# ---------- Cancel encounter ----------

@bp.route("/encounters/<eid>/cancel", methods=["POST"])
@require_roles(ROLE_RECEPTIONIST, ROLE_PROVIDER)
def cancel_encounter(eid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        enc = get_encounter(eid)
        if enc["status"] == "SCHEDULED":
            if now() >= enc["scheduled_start"]:
                raise err_invalid_encounter_state(
                    "SCHEDULED encounters may only be cancelled before scheduled_start"
                )
        elif enc["status"] == "CHECKED_IN":
            # Only permitted if no CptLineItem exists
            has_line = any(li["encounter_id"] == eid for li in s.cpt_line_items.values())
            if has_line:
                raise err_invalid_encounter_state(
                    "CHECKED_IN encounter has CPT line items and cannot be cancelled"
                )
        else:
            raise err_invalid_encounter_state(
                f"encounter in status {enc['status']} cannot be cancelled"
            )

        occ_check(body.get("version"), enc["version"])
        enc["status"] = "CANCELLED"
        bump(enc)

        # Cascade DRAFT prescriptions on this encounter -> CANCELLED
        for rx in s.prescriptions.values():
            if rx.get("encounter_id") == eid and rx.get("status") == "DRAFT":
                rx["status"] = "CANCELLED"
                bump(rx)
    return ok(encounter_to_dict(enc))


# ---------- CPT line items ----------

@bp.route("/encounters/<eid>/cpt-line-items", methods=["POST"])
@require_roles(ROLE_PROVIDER, ROLE_BILLING_CLERK)
def add_cpt_line_item(eid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        enc = get_encounter(eid)
        if enc["status"] != "CHECKED_IN":
            raise err_invalid_encounter_state(
                "CPT line items may only be appended on a CHECKED_IN encounter"
            )
        cpt_code = assert_string(body.get("cpt_code"), "cpt_code", pattern=CPT_PATTERN)
        units = assert_integer(body.get("units"), "units")
        # ERR_INVALID_BILLING_UNITS — units between 1 and 50
        if units < 1 or units > 50:
            raise err_invalid_billing_units("units must be between 1 and 50 inclusive")
        modifier = body.get("modifier")
        if modifier is not None and not isinstance(modifier, str):
            raise err_invalid_input("modifier must be a string when supplied")

        # Reference: catalog lookup
        catalog = get_cpt_fee(cpt_code, source="body")

        ts = now()
        row = {
            "id": new_uuid(),
            "created_at": ts,
            "encounter_id": eid,
            "cpt_code": cpt_code,
            "units": units,
            "list_charge_cents": cpt_billing_charge(catalog, units),
            "allowed_amount_cents": None,
            "modifier": modifier,
            "is_preventive": False,
        }
        s.cpt_line_items[row["id"]] = row
    return created(cpt_line_item_to_dict(row))


@bp.route("/cpt-line-items/<lid>", methods=["DELETE"])
@require_roles(ROLE_BILLING_CLERK, ROLE_PROVIDER)
def delete_cpt_line_item(lid: str, **_kwargs):
    s = store()
    with s.lock:
        li = get_cpt_line_item(lid)
        enc = s.encounters.get(li["encounter_id"])
        if enc is None or enc["status"] != "CHECKED_IN":
            raise err_invalid_encounter_state(
                "CPT line items may only be removed while parent encounter is CHECKED_IN"
            )
        del s.cpt_line_items[lid]
    return no_content()
