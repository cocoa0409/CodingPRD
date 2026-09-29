"""Request-body builders.

Each builder returns a valid payload for one endpoint and accepts keyword
overrides, so a test that cares about one field can state only that field. The
drug catalogue below gives every prescription payload a stable, realistic shape:
one tablet regimen per dose slot, a refrigerated pen, a non-packable inhaler and a
controlled tablet, which between them exercise all three fulfilment routes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "insurance_plan_payload",
    "patient_payload",
    "prescription_payload",
    "metformin_payload",
    "rivaroxaban_payload",
    "sitagliptin_payload",
    "insulin_payload",
    "albuterol_payload",
    "oxycodone_payload",
    "atorvastatin_payload",
    "synchronize_payload",
    "fill_cycle_payload",
    "adjudicate_payload",
    "roll_images_payload",
    "pouch_image_payload",
    "shipment_payload",
    "pouch_roll_shipment_payload",
    "cold_chain_shipment_payload",
    "loose_shipment_payload",
    "deliver_payload",
    "refill_authorization_payload",
    "authorization_response_payload",
    "vacation_exception_payload",
    "vacation_decision_payload",
    "dose_events_payload",
    "dose_event",
    "regimen_change_payload",
    "reissue_payload",
    "autoship_payload",
    "PRESCRIBER_NPI",
]

PRESCRIBER_NPI = "1487654321"

JsonDict = Dict[str, Any]


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    """Apply keyword overrides, dropping any key whose override value is ``None``."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ----------------------------------------------------------------------
# Payer plan and patient
# ----------------------------------------------------------------------
def insurance_plan_payload(**overrides: Any) -> JsonDict:
    """A payer plan with all three per-day rates and explicit edit thresholds."""
    return _merge(
        {
            "payer_name": "Northwind PBM",
            "bin_number": "610502",
            "generic_copay_cents_per_day": 34,
            "brand_copay_cents_per_day": 74,
            "specialty_copay_cents_per_day": 44,
            "refill_too_soon_threshold_pct": 75,
            "coinsurance_pct": 20,
        },
        overrides,
    )


def patient_payload(insurance_plan_id: str, **overrides: Any) -> JsonDict:
    """Enrolment body for the first canonical patient."""
    return _merge(
        {
            "full_name": "Rosa Klein",
            "date_of_birth": "1954-09-09",
            "email": "rosa.klein@example.com",
            "state_code": "WA",
            "insurance_plan_id": insurance_plan_id,
        },
        overrides,
    )


def second_patient_payload(insurance_plan_id: str, **overrides: Any) -> JsonDict:
    """Enrolment body for the second canonical patient."""
    return _merge(
        {
            "full_name": "Bram Osei",
            "date_of_birth": "1961-02-02",
            "email": "bram.osei@example.com",
            "state_code": "OR",
            "insurance_plan_id": insurance_plan_id,
        },
        overrides,
    )


def third_patient_payload(insurance_plan_id: str, **overrides: Any) -> JsonDict:
    """Enrolment body for the third canonical patient."""
    return _merge(
        {
            "full_name": "Nadia Farouk",
            "date_of_birth": "1949-04-04",
            "email": "nadia.farouk@example.com",
            "state_code": "WA",
            "insurance_plan_id": insurance_plan_id,
        },
        overrides,
    )


__all__ += ["second_patient_payload", "third_patient_payload"]


# ----------------------------------------------------------------------
# Prescriptions
# ----------------------------------------------------------------------
def prescription_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """A generic tablet prescription taken every morning."""
    return _merge(
        {
            "patient_id": patient_id,
            "prescriber_npi": PRESCRIBER_NPI,
            "drug_name": "Metformin ER",
            "ndc": "00093-1049-01",
            "strength": "500mg",
            "form": "TABLET",
            "copay_tier": "GENERIC",
            "dose_times": ["MORNING"],
            "quantity_per_dose": 1,
            "days_supply_written": 30,
            "refills_authorized": 3,
            "written_date": "2026-05-01",
            "expiration_date": "2027-05-01",
        },
        overrides,
    )


def metformin_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Generic morning tablet with a 28-day prior fill dispensed 2026-07-25."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Metformin ER",
                "ndc": "00093-1049-01",
                "strength": "500mg",
                "form": "TABLET",
                "copay_tier": "GENERIC",
                "dose_times": ["MORNING"],
                "days_supply_written": 30,
                "last_dispensed_date": "2026-07-25",
                "last_dispensed_days_supply": 28,
            },
            overrides,
        ),
    )


def rivaroxaban_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Preferred-brand morning tablet with a 30-day prior fill dispensed 2026-07-20."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Rivaroxaban",
                "ndc": "50458-0578-30",
                "strength": "20mg",
                "form": "TABLET",
                "copay_tier": "PREFERRED_BRAND",
                "dose_times": ["MORNING"],
                "days_supply_written": 30,
                "last_dispensed_date": "2026-07-20",
                "last_dispensed_days_supply": 30,
            },
            overrides,
        ),
    )


def sitagliptin_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Specialty evening tablet with a 30-day prior fill dispensed 2026-07-18."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Sitagliptin",
                "ndc": "00006-0277-31",
                "strength": "100mg",
                "form": "TABLET",
                "copay_tier": "SPECIALTY",
                "dose_times": ["EVENING"],
                "days_supply_written": 30,
                "last_dispensed_date": "2026-07-18",
                "last_dispensed_days_supply": 30,
            },
            overrides,
        ),
    )


def insulin_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Refrigerated specialty pen, which can never enter a pouch."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Insulin glargine",
                "ndc": "00088-2220-33",
                "strength": "100units/mL",
                "form": "INJECTION_PEN",
                "copay_tier": "SPECIALTY",
                "dose_times": ["BEDTIME"],
                "days_supply_written": 28,
                "refrigerated": True,
                "last_dispensed_date": "2026-07-18",
                "last_dispensed_days_supply": 28,
            },
            overrides,
        ),
    )


def albuterol_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Non-refrigerated inhaler, which is not packable and ships loose."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Albuterol HFA",
                "ndc": "00173-0682-20",
                "strength": "90mcg",
                "form": "INHALER",
                "copay_tier": "GENERIC",
                "dose_times": ["MORNING"],
                "days_supply_written": 30,
            },
            overrides,
        ),
    )


def oxycodone_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Controlled generic tablet, which caps day supply and forbids travel overrides."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Oxycodone IR",
                "ndc": "00406-0552-01",
                "strength": "5mg",
                "form": "TABLET",
                "copay_tier": "GENERIC",
                "dose_times": ["EVENING"],
                "days_supply_written": 30,
                "is_controlled": True,
            },
            overrides,
        ),
    )


def atorvastatin_payload(patient_id: str, **overrides: Any) -> JsonDict:
    """Generic bedtime tablet."""
    return prescription_payload(
        patient_id,
        **_merge(
            {
                "drug_name": "Atorvastatin",
                "ndc": "00071-0155-23",
                "strength": "20mg",
                "form": "TABLET",
                "copay_tier": "GENERIC",
                "dose_times": ["BEDTIME"],
                "days_supply_written": 30,
            },
            overrides,
        ),
    )


# ----------------------------------------------------------------------
# Synchronization, cycles and adjudication
# ----------------------------------------------------------------------
def synchronize_payload(
    anchor_fill_day: int = 15, sync_mode: str = "BRIDGE_TO_START", **overrides: Any
) -> JsonDict:
    """Pin the anchor day and the alignment policy."""
    return _merge(
        {"anchor_fill_day": anchor_fill_day, "sync_mode": sync_mode}, overrides
    )


def fill_cycle_payload(
    patient_id: str,
    cycle_start_date: str = "2026-08-15",
    day_supply_days: int = 28,
    **overrides: Any,
) -> JsonDict:
    """Open a fill cycle for a synchronized patient."""
    return _merge(
        {
            "patient_id": patient_id,
            "cycle_start_date": cycle_start_date,
            "day_supply_days": day_supply_days,
        },
        overrides,
    )


def adjudicate_payload(
    force_pouch_prescription_ids: Optional[List[str]] = None,
    vacation_exception_id: Optional[str] = None,
) -> JsonDict:
    """Adjudication body; both fields are optional."""
    payload: JsonDict = {}
    if force_pouch_prescription_ids is not None:
        payload["force_pouch_prescription_ids"] = force_pouch_prescription_ids
    if vacation_exception_id is not None:
        payload["vacation_exception_id"] = vacation_exception_id
    return payload


# ----------------------------------------------------------------------
# Bench imaging
# ----------------------------------------------------------------------
def roll_images_payload(
    image_confidence_pct: int = 97, overrides: Optional[List[JsonDict]] = None
) -> JsonDict:
    """One whole-roll scanner pass, optionally overriding individual pouches."""
    payload: JsonDict = {"image_confidence_pct": image_confidence_pct}
    if overrides is not None:
        payload["overrides"] = overrides
    return payload


def pouch_image_payload(
    detected_pill_count: int, image_confidence_pct: int = 97
) -> JsonDict:
    """One single-pouch verification image."""
    return {
        "detected_pill_count": detected_pill_count,
        "image_confidence_pct": image_confidence_pct,
    }


# ----------------------------------------------------------------------
# Shipments
# ----------------------------------------------------------------------
def shipment_payload(
    shipment_kind: str, carrier_service: str = "GROUND", packaging: Optional[str] = None
) -> JsonDict:
    """Stage one parcel; ``packaging`` defaults to ``STANDARD`` when omitted."""
    payload: JsonDict = {
        "shipment_kind": shipment_kind,
        "carrier_service": carrier_service,
    }
    if packaging is not None:
        payload["packaging"] = packaging
    return payload


def pouch_roll_shipment_payload(**overrides: Any) -> JsonDict:
    """A ground pouch-roll parcel in standard packaging: freight 0 cents."""
    return _merge(
        {
            "shipment_kind": "POUCH_ROLL",
            "carrier_service": "GROUND",
            "packaging": "STANDARD",
        },
        overrides,
    )


def cold_chain_shipment_payload(**overrides: Any) -> JsonDict:
    """An overnight cold-chain parcel in gel packaging: freight 3445 cents."""
    return _merge(
        {
            "shipment_kind": "COLD_CHAIN",
            "carrier_service": "OVERNIGHT",
            "packaging": "INSULATED_GEL",
        },
        overrides,
    )


def loose_shipment_payload(**overrides: Any) -> JsonDict:
    """A two-day loose parcel in standard packaging: freight 1095 cents."""
    return _merge(
        {
            "shipment_kind": "NON_PACKABLE_LOOSE",
            "carrier_service": "TWO_DAY",
            "packaging": "STANDARD",
        },
        overrides,
    )


def deliver_payload(cold_chain_excursion_minutes: Optional[int] = None) -> JsonDict:
    """Record delivery; the excursion figure is optional and defaults to 0."""
    if cold_chain_excursion_minutes is None:
        return {}
    return {"cold_chain_excursion_minutes": cold_chain_excursion_minutes}


# ----------------------------------------------------------------------
# Refill authorization
# ----------------------------------------------------------------------
def refill_authorization_payload(
    prescription_id: str, requested_refills: int = 3, **overrides: Any
) -> JsonDict:
    """Open a chase against the prescriber."""
    return _merge(
        {"prescription_id": prescription_id, "requested_refills": requested_refills},
        overrides,
    )


def authorization_response_payload(
    decision: str,
    approved_refills: Optional[int] = None,
    denial_reason: Optional[str] = None,
) -> JsonDict:
    """The prescriber's answer to a chase."""
    payload: JsonDict = {"decision": decision}
    if approved_refills is not None:
        payload["approved_refills"] = approved_refills
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


# ----------------------------------------------------------------------
# Travel exceptions
# ----------------------------------------------------------------------
def vacation_exception_payload(
    patient_id: str,
    travel_start_date: str = "2026-08-20",
    travel_end_date: str = "2026-09-10",
    requested_extra_days: int = 14,
    **overrides: Any,
) -> JsonDict:
    """Request a travel early-supply exception for a future trip."""
    return _merge(
        {
            "patient_id": patient_id,
            "travel_start_date": travel_start_date,
            "travel_end_date": travel_end_date,
            "requested_extra_days": requested_extra_days,
        },
        overrides,
    )


def vacation_decision_payload(
    decision: str,
    approved_extra_days: Optional[int] = None,
    denial_reason: Optional[str] = None,
) -> JsonDict:
    """Decide a travel exception."""
    payload: JsonDict = {"decision": decision}
    if approved_extra_days is not None:
        payload["approved_extra_days"] = approved_extra_days
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


# ----------------------------------------------------------------------
# Adherence and auto-ship
# ----------------------------------------------------------------------
def dose_event(
    event_type: str, occurred_at: str, dose_slot: str = "MORNING", pouch_index: int = 1
) -> JsonDict:
    """One element of a dose-event batch."""
    return {
        "event_type": event_type,
        "occurred_at": occurred_at,
        "dose_slot": dose_slot,
        "pouch_index": pouch_index,
    }


def dose_events_payload(cycle_id: str, events: List[JsonDict]) -> JsonDict:
    """A non-empty batch of dose events attributed to one cycle."""
    return {"cycle_id": cycle_id, "events": events}


def autoship_payload(action: str) -> JsonDict:
    """Change auto-ship posture: ``PAUSE``, ``RESUME`` or ``CANCEL``."""
    return {"action": action}


# ----------------------------------------------------------------------
# Regimen change and partial reissue
# ----------------------------------------------------------------------
def regimen_change_payload(
    expected_prescription_version: int,
    new_drug_name: str = "Metformin IR",
    new_form: str = "TABLET",
    new_copay_tier: str = "GENERIC",
    new_dose_times: Optional[List[str]] = None,
    new_quantity_per_dose: int = 1,
    **overrides: Any,
) -> JsonDict:
    """Supersede a prescription and mint its successor."""
    return _merge(
        {
            "new_drug_name": new_drug_name,
            "new_form": new_form,
            "new_copay_tier": new_copay_tier,
            "new_dose_times": new_dose_times
            if new_dose_times is not None
            else ["MORNING"],
            "new_quantity_per_dose": new_quantity_per_dose,
            "expected_prescription_version": expected_prescription_version,
        },
        overrides,
    )


def reissue_payload(
    effective_date: str,
    replacement_prescription_ids: List[str],
    expected_cycle_version: int,
) -> JsonDict:
    """Reissue the untaken tail of a cycle as a new partial cycle."""
    return {
        "effective_date": effective_date,
        "replacement_prescription_ids": replacement_prescription_ids,
        "expected_cycle_version": expected_cycle_version,
    }
