"""HEDIS measure evaluation — provisional (YTD) and final (year-end freeze)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ..clock import now
from ..helpers import new_uuid
from ..store import store

HEDIS_MEASURES = ("AWV", "CBP", "TSC", "CCS")


def _age_at_year_end(dob: str, measurement_year: int) -> int:
    """integer years; per scaffold: measurement_year - year(dob) - (1 if md(dob)>md(12,31) else 0)
    Since md(dob)>md(12,31) is impossible, this is simply measurement_year - birth_year."""
    birth_year = int(dob.split("-")[0])
    return measurement_year - birth_year


def _patient_completed_encounters_in_year(patient_id: str, year: int) -> list[dict]:
    s = store()
    out = []
    for enc in s.encounters.values():
        if enc.get("patient_id") != patient_id:
            continue
        if enc.get("status") != "COMPLETED":
            continue
        actual_end = enc.get("actual_end")
        if actual_end is None:
            continue
        if isinstance(actual_end, datetime):
            ae = actual_end
        else:
            continue
        if ae.tzinfo is None:
            ae = ae.replace(tzinfo=timezone.utc)
        if ae.year == year:
            out.append(enc)
    return out


def _patient_completed_encounters_ytd(patient_id: str, year: int) -> list[dict]:
    """For provisional: COMPLETED encounters with actual_end <= now() within the year."""
    s = store()
    cutoff = now()
    out = []
    for enc in s.encounters.values():
        if enc.get("patient_id") != patient_id:
            continue
        if enc.get("status") != "COMPLETED":
            continue
        actual_end = enc.get("actual_end")
        if actual_end is None:
            continue
        ae = actual_end
        if ae.tzinfo is None:
            ae = ae.replace(tzinfo=timezone.utc)
        if ae.year == year and ae <= cutoff:
            out.append(enc)
    return out


def _line_items_for_encounter(encounter_id: str) -> list[dict]:
    s = store()
    return [li for li in s.cpt_line_items.values() if li["encounter_id"] == encounter_id]


def _encounter_has_preventive_line(encounter_id: str) -> bool:
    for li in _line_items_for_encounter(encounter_id):
        if li.get("is_preventive") is True:
            return True
    return False


def _encounter_has_cpt(encounter_id: str, codes: set[str]) -> bool:
    for li in _line_items_for_encounter(encounter_id):
        if li.get("cpt_code") in codes:
            return True
    return False


def _evaluate_one(
    patient: dict,
    measure_id: str,
    measurement_year: int,
    *,
    encounters: list[dict],
    smoking_status: str,
    is_active_for_denominator: bool,
) -> tuple[bool, bool]:
    """Return (in_denominator, in_numerator) for one (patient, measure, year)."""
    dob = patient.get("date_of_birth", "1900-01-01")
    age = _age_at_year_end(dob, measurement_year)
    sex = patient.get("sex_at_birth", "UNKNOWN")
    chronic = patient.get("chronic_conditions") or []

    if measure_id == "AWV":
        denom = (age >= 18) and is_active_for_denominator
        if not denom:
            return (False, False)
        num = any(_encounter_has_preventive_line(enc["id"]) for enc in encounters)
        return (True, bool(num))

    if measure_id == "CBP":
        denom = (18 <= age <= 85) and ("I10" in chronic) and len(encounters) >= 1
        if not denom:
            return (False, False)
        # most-recent COMPLETED in year: by actual_end DESC, tie by id ASC
        ranked = sorted(
            encounters,
            key=lambda e: (-(e["actual_end"].timestamp() if hasattr(e["actual_end"], "timestamp") else 0), e["id"]),
        )
        # ascending id on tie: with negative timestamp first, ties break naturally by string asc.
        most_recent = ranked[0]
        vs = most_recent.get("vital_signs") or {}
        sys_ok = isinstance(vs.get("bp_systolic"), (int, float)) and vs["bp_systolic"] < 140
        dia_ok = isinstance(vs.get("bp_diastolic"), (int, float)) and vs["bp_diastolic"] < 90
        return (True, bool(sys_ok and dia_ok))

    if measure_id == "TSC":
        denom = (age >= 18) and len(encounters) >= 1
        if not denom:
            return (False, False)
        if smoking_status not in {"NEVER", "FORMER", "CURRENT"}:
            return (True, False)
        if smoking_status == "CURRENT":
            # Need at least one CONSULTATION encounter in year with CPT 99406 or 99407
            cessation_codes = {"99406", "99407"}
            has = any(
                e.get("encounter_type") == "CONSULTATION" and _encounter_has_cpt(e["id"], cessation_codes)
                for e in encounters
            )
            return (True, bool(has))
        return (True, True)

    if measure_id == "CCS":
        denom = (sex == "FEMALE") and (21 <= age <= 64)
        if not denom:
            return (False, False)
        codes = {"88141", "88142"}
        has = any(_encounter_has_cpt(e["id"], codes) for e in encounters)
        return (True, bool(has))

    return (False, False)


def _measurement_key(patient_id: str, measure_id: str, year: int) -> tuple[str, str, int]:
    return (patient_id, measure_id, year)


def _find_existing(patient_id: str, measure_id: str, year: int) -> dict | None:
    s = store()
    for row in s.hedis_measurements.values():
        if (
            row["patient_id"] == patient_id
            and row["measure_id"] == measure_id
            and row["measurement_year"] == year
        ):
            return row
    return None


def recompute_final(patient_id: str, year: int, measures: Iterable[str] | None = None) -> list[dict]:
    """Final, year-end freeze. Writes one row per measure (overwrites existing)."""
    s = store()
    patient = s.patients.get(patient_id)
    if patient is None:
        return []
    measures = list(measures) if measures else list(HEDIS_MEASURES)
    encounters = _patient_completed_encounters_in_year(patient_id, year)
    rows_written = []
    for m in measures:
        in_d, in_n = _evaluate_one(
            patient,
            m,
            year,
            encounters=encounters,
            smoking_status=patient.get("smoking_status", "UNKNOWN"),
            is_active_for_denominator=(patient.get("status") == "ACTIVE"),
        )
        existing = _find_existing(patient_id, m, year)
        if existing is None:
            row = {
                "id": new_uuid(),
                "patient_id": patient_id,
                "measure_id": m,
                "measurement_year": year,
                "in_denominator": in_d,
                "in_numerator": in_n,
                "computed_at": now(),
            }
            s.hedis_measurements[row["id"]] = row
        else:
            existing["in_denominator"] = in_d
            existing["in_numerator"] = in_n
            existing["computed_at"] = now()
            row = existing
        rows_written.append(row)
    return rows_written


def recompute_provisional_ytd(patient_id: str, year: int) -> list[dict]:
    """Provisional, year-to-date. Computes in memory; does NOT write rows.

    Returns ephemeral dicts shaped like HedisMeasurement.
    """
    s = store()
    patient = s.patients.get(patient_id)
    if patient is None:
        return []
    encounters = _patient_completed_encounters_ytd(patient_id, year)
    is_active_now = patient.get("status") == "ACTIVE"
    smoking_now = patient.get("smoking_status", "UNKNOWN")
    out = []
    for m in HEDIS_MEASURES:
        in_d, in_n = _evaluate_one(
            patient,
            m,
            year,
            encounters=encounters,
            smoking_status=smoking_now,
            is_active_for_denominator=is_active_now,
        )
        out.append({
            "id": "",  # provisional: no id assigned
            "patient_id": patient_id,
            "measure_id": m,
            "measurement_year": year,
            "in_denominator": in_d,
            "in_numerator": in_n,
            "computed_at": now(),
        })
    return out


def recompute_partial_on_encounter_complete(patient_id: str, year: int) -> None:
    """On encounter completion: refresh only AWV and CBP for the current year."""
    recompute_final(patient_id, year, measures=("AWV", "CBP"))
