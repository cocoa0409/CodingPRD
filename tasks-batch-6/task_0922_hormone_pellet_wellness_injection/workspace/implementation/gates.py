"""Validation rungs 9 to 39 that more than one endpoint shares (PRD 2.8, 2.9)."""
from fractions import Fraction

import calc
import config
import store
import util
from errors import ApiError


# ------------------------------------------- rungs 10 and 11: state --------
def state_gate(row, axis_key, allowed_from, state_field="status"):
    """A terminal row reports ERR_ALREADY_TERMINAL; any other undeclared
    origin state reports ERR_INVALID_STATE."""
    current = row.get(state_field)
    if current in config.TERMINAL_STATES.get(axis_key, ()):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if current not in allowed_from:
        raise ApiError("ERR_INVALID_STATE")


def terminal_gate(row, axis_key, state_field="status"):
    if row.get(state_field) in config.TERMINAL_STATES.get(axis_key, ()):
        raise ApiError("ERR_ALREADY_TERMINAL")


# ------------------------- rung 9: the delegated-authority write gate ------
def standing_order_write_gate(ctx, order, hormone_type=None, injection_type=None,
                              planned_total_mg=None):
    """Fires only for a NurseInjector, and only on the three gated endpoints."""
    if ctx.role != config.ROLE_NURSE_INJECTOR:
        return
    if order is None:
        raise ApiError("ERR_STANDING_ORDER_INVALID")
    if order["status"] != "ACTIVE":
        raise ApiError("ERR_STANDING_ORDER_INVALID")
    now = store.now()
    if not (order["valid_from"] <= now <= order["valid_until"]):
        raise ApiError("ERR_STANDING_ORDER_INVALID")
    if hormone_type is not None and hormone_type not in (order.get("scope_hormone_types") or []):
        raise ApiError("ERR_STANDING_ORDER_INVALID")
    if injection_type is not None and injection_type not in (
        order.get("scope_injection_types") or []
    ):
        raise ApiError("ERR_STANDING_ORDER_INVALID")
    if planned_total_mg is not None:
        if util.frac(planned_total_mg) > util.frac(order["max_dose_mg"]):
            raise ApiError("ERR_STANDING_ORDER_INVALID")


# ---------------------------------------- rungs 14, 15, 39: patient holds --
def clinical_hold_gate(patient):
    if patient.get("clinical_hold"):
        raise ApiError("ERR_PATIENT_CLINICAL_HOLD")


def financial_hold_gate(patient):
    if patient.get("financial_hold"):
        raise ApiError("ERR_PATIENT_FINANCIAL_HOLD")


def critical_lab_gate(patient):
    for panel in store.where("LabPanel", patient_id=patient["id"]):
        if panel["status"] == "CRITICAL_FLAGGED":
            raise ApiError("ERR_CRITICAL_LAB_UNACKNOWLEDGED")


# --------------------------------------------- rung 16: consent currency ---
def consent_is_current(consent, patient_id, hormone_type):
    if consent is None:
        return False
    if consent["status"] != "ACTIVE":
        return False
    if consent["patient_id"] != patient_id:
        return False
    if consent["hormone_type"] != hormone_type:
        return False
    from cascades import highest_protocol_version

    return consent["protocol_version"] == highest_protocol_version(hormone_type)


def consent_gate(procedure):
    """At open-supply and perform the attached consent must still be current."""
    consent_id = procedure.get("consent_record_id")
    if consent_id is None:
        raise ApiError("ERR_CONSENT_REQUIRED")
    consent = store.get("ConsentRecord", consent_id)
    if not consent_is_current(consent, procedure["patient_id"], procedure["hormone_type"]):
        raise ApiError("ERR_CONSENT_REQUIRED")
    return consent


# ------------------------------------------ rung 18: hematocrit ceiling ----
def latest_hematocrit(patient_id):
    best = None
    for panel in store.where("LabPanel", patient_id=patient_id):
        if panel["analyte"] != "HEMATOCRIT" or panel["status"] == "SUPERSEDED":
            continue
        if best is None or (panel["created_at"], panel["_seq"]) > (
            best["created_at"], best["_seq"]
        ):
            best = panel
    return best


def safety_ceiling_gate(patient_id):
    panel = latest_hematocrit(patient_id)
    if panel is not None and panel["value"] > config.HEMATOCRIT_SAFETY_CEILING:
        raise ApiError("ERR_SAFETY_CEILING_EXCEEDED")


# ---------------------------------------------- rungs 19 and 20: doses -----
def dose_cap_gate(hormone_type, planned_total_mg):
    if util.frac(planned_total_mg) > config.MAX_DOSE_PER_PROCEDURE_MG[hormone_type]:
        raise ApiError("ERR_DOSE_CAP_EXCEEDED")


def rolling_cap_gate(patient_id, hormone_type, variant, committing_mg):
    exposure = calc.rolling_mg_exposure(patient_id, hormone_type, variant, store.now())
    total = util.frac(exposure) + util.frac(committing_mg)
    if total > config.ROLLING_MG_CAP[hormone_type]:
        raise ApiError("ERR_ROLLING_MG_CAP_EXCEEDED")


# ------------------------------------- rungs 26 to 28: temporal occupancy --
def post_insertion_gate(patient, scheduled_start):
    anchor = patient.get("last_insertion_at")
    if anchor is None:
        return
    if scheduled_start < util.add_days(anchor, config.POST_INSERTION_RESTRICTION_DAYS):
        raise ApiError("ERR_POST_INSERTION_RESTRICTION")


def _occupying_intervals(provider_id=None, room_code=None):
    out = []
    for proc in store.all_rows("Procedure"):
        if proc["status"] not in config.OCCUPYING_PROCEDURE_STATUSES:
            continue
        if provider_id is not None and proc["provider_id"] != provider_id:
            continue
        if room_code is not None and proc["room_code"] != room_code:
            continue
        out.append((proc["scheduled_start"], proc["scheduled_end"]))
    for visit in store.all_rows("InjectionVisit"):
        if visit["status"] not in config.OCCUPYING_VISIT_STATUSES:
            continue
        if provider_id is not None and visit["provider_id"] != provider_id:
            continue
        if room_code is not None and visit["room_code"] != room_code:
            continue
        out.append((visit["scheduled_start"], visit["scheduled_end"]))
    return out


def provider_conflict_gate(provider_id, new_start, new_end):
    """Symmetric 20-minute buffer on the new booking, raw existing intervals."""
    lo = util.add_minutes(new_start, -config.PROVIDER_SLOT_BUFFER_MINUTES)
    hi = util.add_minutes(new_end, config.PROVIDER_SLOT_BUFFER_MINUTES)
    for start, end in _occupying_intervals(provider_id=provider_id):
        if lo < end and start < hi:
            raise ApiError("ERR_PROVIDER_SLOT_CONFLICT")


def room_conflict_gate(room_code, new_start, new_end):
    """No buffer, half-open overlap, so touching bookings are allowed."""
    for start, end in _occupying_intervals(room_code=room_code):
        if new_start < end and start < new_end:
            raise ApiError("ERR_ROOM_CONFLICT")


# ------------------------------------------ rung 31: pack transferability --
def series_ownership_gate(pack, patient_id):
    if pack is not None and pack["patient_id"] != patient_id:
        raise ApiError("ERR_SERIES_NOT_TRANSFERABLE")


# ----------------------------------- rungs 32 and 33: entitlement pools ----
def series_expiry_gate(pack):
    """Mutate-then-reject: an ACTIVE pack forfeits before the request fails."""
    if pack is None:
        return
    now = store.now()
    if now <= pack["expires_at"]:
        return
    if pack["status"] == "ACTIVE":
        pack["forfeited_visits"] += pack["remaining_visits"]
        pack["remaining_visits"] = 0
        pack["status"] = "EXPIRED"
        store.touch(pack)
    raise ApiError("ERR_SERIES_EXPIRED")


def series_exhaustion_gate(pack):
    if pack is not None and pack["remaining_visits"] < 1:
        raise ApiError("ERR_SERIES_EXHAUSTED")


def zero():
    return Fraction(0)
