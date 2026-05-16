"""Cross-cutting validation helpers.

Format constraints:
  - ICD-10-CM: [A-Z]\\d{2}(\\.[A-Z0-9]{1,4})?
  - CPT: exactly 5 digits
  - MRN: 8-12 alphanumeric characters

Existence / ownership helpers and common assertions on bodies.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from ..errors import ApiError
from ..store import get_store


ICD10_RE = re.compile(r"^[A-Z]\d{2}(\.[A-Z0-9]{1,4})?$")
CPT_RE = re.compile(r"^\d{5}$")
MRN_RE = re.compile(r"^[A-Za-z0-9]{8,12}$")


# ---------------------------------------------------------------------------
# Existence checks
# ---------------------------------------------------------------------------
def get_patient_or_404(patient_id: str) -> dict[str, Any]:
    store = get_store()
    p = store.patients.get(patient_id)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", f"Patient {patient_id} not found.")
    return p


def get_policy_or_404(policy_id: str) -> dict[str, Any]:
    store = get_store()
    p = store.policies.get(policy_id)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", f"Policy {policy_id} not found.")
    return p


def get_encounter_or_404(encounter_id: str) -> dict[str, Any]:
    store = get_store()
    e = store.encounters.get(encounter_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", f"Encounter {encounter_id} not found.")
    return e


def get_charge_or_404(charge_id: str) -> dict[str, Any]:
    store = get_store()
    c = store.charges.get(charge_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", f"Charge {charge_id} not found.")
    return c


# ---------------------------------------------------------------------------
# Body field plumbing
# ---------------------------------------------------------------------------
def require_field(body: dict[str, Any], key: str) -> Any:
    if key not in body:
        raise ApiError("ERR_INVALID_INPUT", f"Missing required field: {key}")
    val = body[key]
    if val is None or (isinstance(val, str) and val == ""):
        raise ApiError("ERR_INVALID_INPUT", f"Field must not be empty: {key}")
    return val


def require_int(body: dict[str, Any], key: str, minimum: int | None = None) -> int:
    val = require_field(body, key)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_INPUT", f"Field {key} must be an integer.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_INPUT", f"Field {key} must be >= {minimum}, got {val}.")
    return val


def require_str(body: dict[str, Any], key: str) -> str:
    val = require_field(body, key)
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_INPUT", f"Field {key} must be a string.")
    return val


def require_bool(body: dict[str, Any], key: str) -> bool:
    if key not in body:
        raise ApiError("ERR_INVALID_INPUT", f"Missing required field: {key}")
    val = body[key]
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_INPUT", f"Field {key} must be a boolean.")
    return val


# ---------------------------------------------------------------------------
# Format validators (used at the appropriate priority point)
# ---------------------------------------------------------------------------
def validate_icd10(code: str) -> None:
    if not isinstance(code, str) or not ICD10_RE.match(code):
        raise ApiError("ERR_INVALID_ICD10", f"Invalid ICD-10 code: {code!r}")


def validate_cpt(code: str) -> None:
    if not isinstance(code, str) or not CPT_RE.match(code):
        raise ApiError("ERR_INVALID_CPT", f"Invalid CPT code: {code!r}")


def validate_cpt_list(codes: Iterable[Any]) -> None:
    for c in codes:
        validate_cpt(c)


def validate_mrn(mrn: str) -> None:
    if not isinstance(mrn, str) or not MRN_RE.match(mrn):
        raise ApiError(
            "ERR_INVALID_INPUT",
            "MRN must be 8-12 alphanumeric characters.",
        )
