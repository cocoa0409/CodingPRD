"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally permissive on optional fields —
when PRD prose is silent on a specific projection, the assertion does
not pin it (see the SKILL Silence-pattern: computed-field).
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.5
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.5: "Every resource the API persists carries a server-
    minted id formatted as a UUID with no type prefix, and a created_at
    timestamp formatted as an ISO 8601 UTC string with three fractional
    digits."
    """
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.5: "The Patient, InsurancePolicy, Encounter, ChargeItem,
    and CodingRecord resources additionally carry an updated_at ISO
    8601 UTC timestamp that is refreshed on every mutation of the
    resource, and an integer version that begins at 1 on creation and
    is incremented by exactly one on each subsequent mutation."
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, "
        f"got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.1
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("mrn"), str) and data["mrn"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    # PRD §3.1: "A newly created patient record is in the ACTIVE status;
    # the only other terminal status the patient record may reach is
    # ARCHIVED."
    assert data.get("status") in {"ACTIVE", "ARCHIVED"}


# ---------------------------------------------------------------------------
# InsurancePolicy — PRD §3.1
# ---------------------------------------------------------------------------
def assert_insurance_policy(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert isinstance(data.get("payer_name"), str) and data["payer_name"]
    assert isinstance(data.get("policy_number"), str)
    assert isinstance(data.get("plan_year"), int)
    assert isinstance(data.get("deductible_cents"), int)
    # PRD §2.7: "The annual deductible deductible_cents must be at
    # least 0."
    assert data["deductible_cents"] >= 0
    assert isinstance(data.get("deductible_met_cents"), int)
    # PRD §2.7: "deductible_met_cents never exceeds deductible_cents".
    assert 0 <= data["deductible_met_cents"] <= data["deductible_cents"]
    assert isinstance(data.get("coinsurance_rate_bps"), int)
    # PRD §2.7: "coinsurance_rate_bps … constrained to lie between 0
    # and 10000 inclusive".
    assert 0 <= data["coinsurance_rate_bps"] <= 10000
    assert isinstance(data.get("oop_max_cents"), int)
    # PRD §2.7: "The annual out-of-pocket maximum oop_max_cents must be
    # at least as large as deductible_cents."
    assert data["oop_max_cents"] >= data["deductible_cents"]
    assert isinstance(data.get("oop_accumulated_cents"), int)
    # PRD §2.7: "oop_accumulated_cents never exceeds oop_max_cents".
    assert 0 <= data["oop_accumulated_cents"] <= data["oop_max_cents"]
    # PRD §3.1: "A newly attached policy is created in the UNVERIFIED
    # status … A policy may end up in either of two other statuses:
    # ELIGIBLE … or INELIGIBLE".
    assert data.get("status") in {"UNVERIFIED", "ELIGIBLE", "INELIGIBLE"}


# ---------------------------------------------------------------------------
# Encounter — PRD §3.2
# ---------------------------------------------------------------------------
ENCOUNTER_STATUSES = {
    "REGISTERED",
    "ELIGIBILITY_VERIFIED",
    "CHARGES_CAPTURED",
    "CODED",
    "CLEARED",
    "BILLED",
    "RESOLVED",
    "WRITTEN_OFF",
}


def assert_encounter(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("policy_id", ""))
    assert is_iso8601_timestamp(data.get("admission_at", ""))
    # PRD §3.2: "sets discharge_at to null" on creation; later set on
    # discharge. So discharge_at may be null OR ISO 8601.
    if data.get("discharge_at") is not None:
        assert is_iso8601_timestamp(data["discharge_at"])
    assert data.get("status") in ENCOUNTER_STATUSES, (
        f"unexpected encounter status {data.get('status')!r}; "
        f"expected one of {ENCOUNTER_STATUSES}"
    )
    # PRD §3.2: "initialises all five computed totals … to 0".
    for field in (
        "total_charges_cents",
        "payer_responsibility_cents",
        "patient_responsibility_cents",
        "estimated_patient_responsibility_cents",
        "write_off_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be an integer (cents), got {data.get(field)!r}"
        )
        assert data[field] >= 0, (
            f"{field} must be non-negative, got {data[field]}"
        )


# ---------------------------------------------------------------------------
# ChargeItem — PRD §3.4
# ---------------------------------------------------------------------------
def assert_charge_item(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("encounter_id", ""))
    # PRD §3.4: "5-digit CPT procedure code cpt_code".
    assert isinstance(data.get("cpt_code"), str)
    assert len(data["cpt_code"]) == 5 and data["cpt_code"].isdigit()
    assert isinstance(data.get("description"), str)
    # PRD §3.4: "a unit count quantity of at least 1".
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1
    # PRD §3.4: "per-unit unit_price_cents of at least 0".
    assert (
        isinstance(data.get("unit_price_cents"), int)
        and data["unit_price_cents"] >= 0
    )
    assert isinstance(data.get("amount_cents"), int)
    # PRD §3.4: "pins the line's amount_cents on creation as the product
    # of quantity and unit_price_cents".
    assert data["amount_cents"] == data["quantity"] * data["unit_price_cents"]
    # PRD §3.4: "The freshly created line begins in the PENDING status"
    # … other allowed statuses are POSTED and VOIDED.
    assert data.get("status") in {"PENDING", "POSTED", "VOIDED"}
    if data.get("status") == "POSTED":
        # PRD §3.4: "Posting … stamps the line's posted_at".
        assert is_iso8601_timestamp(data.get("posted_at", ""))


# ---------------------------------------------------------------------------
# CodingRecord — PRD §3.6
# ---------------------------------------------------------------------------
def assert_coding_record(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("encounter_id", ""))
    assert isinstance(data.get("primary_icd10"), str)
    # PRD §3.6: "secondary_icd10 (defaulting to an empty list if absent)".
    assert isinstance(data.get("secondary_icd10"), list)
    assert isinstance(data.get("cpt_codes"), list) and data["cpt_codes"]
    for cpt in data["cpt_codes"]:
        assert isinstance(cpt, str)
    assert isinstance(data.get("coder_id"), str)
    # PRD §3.6: "A new coding record is created in the DRAFT status;
    # finalizing it transitions it to FINALIZED".
    assert data.get("status") in {"DRAFT", "FINALIZED"}


# ---------------------------------------------------------------------------
# ClearanceDecision — PRD §2.5 (append-only — no updated_at/version)
# ---------------------------------------------------------------------------
def assert_clearance_decision(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.5: "The ClearanceDecision … resources are immutable audit
    # records once written. They carry id and created_at but they do
    # not carry updated_at and they do not carry version."
    assert "updated_at" not in data, (
        "ClearanceDecision is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "ClearanceDecision is append-only and must not carry version"
    )
    assert is_valid_uuid(data.get("encounter_id", ""))
    assert data.get("decision") in {"APPROVED", "PARTIAL", "DENIED"}
    assert isinstance(data.get("allowed_amount_cents"), int)
    assert data["allowed_amount_cents"] >= 0
    # PRD §2.5: "decided_at on a clearance decision … server-set on
    # creation".
    assert is_iso8601_timestamp(data.get("decided_at", ""))


# ---------------------------------------------------------------------------
# PatientPayment — PRD §2.5 (append-only)
# ---------------------------------------------------------------------------
def assert_patient_payment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert "updated_at" not in data, (
        "PatientPayment is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "PatientPayment is append-only and must not carry version"
    )
    assert is_valid_uuid(data.get("encounter_id", ""))
    assert isinstance(data.get("amount_cents"), int)
    # PRD §3.7: "amount_cents (which must be at least 1)".
    assert data["amount_cents"] >= 1
    assert data.get("method") in {"CASH", "CARD", "CHECK", "REFUND"}
    # PRD §2.5: "posted_at on a payment … server-set on creation".
    assert is_iso8601_timestamp(data.get("posted_at", ""))


# ---------------------------------------------------------------------------
# BadDebtRecord — PRD §2.5 (append-only)
# ---------------------------------------------------------------------------
def assert_bad_debt_record(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert "updated_at" not in data, (
        "BadDebtRecord is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "BadDebtRecord is append-only and must not carry version"
    )
    assert is_valid_uuid(data.get("encounter_id", ""))
    assert isinstance(data.get("write_off_cents"), int)
    assert data["write_off_cents"] >= 0
    assert isinstance(data.get("days_since_billed"), int)
    assert data["days_since_billed"] >= 90
    # PRD §2.5: "written_off_at on a bad-debt record … server-set on
    # creation".
    assert is_iso8601_timestamp(data.get("written_off_at", ""))


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.5 / §2.9
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.5: "an integer version that begins at 1 on creation and
    is incremented by exactly one on each subsequent mutation."
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, "
        f"got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Conservation invariant — PRD §3.6
# ---------------------------------------------------------------------------
def assert_allowed_amount_conservation(
    encounter: Dict[str, Any], allowed_amount_cents: int,
) -> None:
    """PRD §3.6: "payer_responsibility_cents plus patient_
    responsibility_cents equals allowed_amount_cents exactly."
    Holds for APPROVED / PARTIAL decisions; for DENIED with a PR-code
    bypass the invariant is on total_charges (different relation),
    not on this function — callers must not invoke this assertion in
    the DENIED case."""
    actual = (
        encounter["payer_responsibility_cents"]
        + encounter["patient_responsibility_cents"]
    )
    assert actual == allowed_amount_cents, (
        f"PRD §3.6 conservation: payer + patient must equal "
        f"allowed_amount_cents={allowed_amount_cents}, got {actual}"
    )


__all__ = [
    "assert_patient",
    "assert_insurance_policy",
    "assert_encounter",
    "assert_charge_item",
    "assert_coding_record",
    "assert_clearance_decision",
    "assert_patient_payment",
    "assert_bad_debt_record",
    "assert_version_incremented_by_one",
    "assert_allowed_amount_conservation",
    "ENCOUNTER_STATUSES",
]
