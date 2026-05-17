"""Entity assertions and domain invariant checkers.

Each assertion checks the response shape and the PRD-stated domain
invariants. Optional/computed fields that PRD prose does not pin are
deliberately not asserted, so a PRD-faithful implementation cannot be
rejected on a free-design choice.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Every persistable resource carries a server-minted id
    field that is a plain UUID string with no type prefix."
    PRD §2.4: "created_at ... ISO 8601 UTC strings with three fractional
    digits."
    """
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 UTC, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "updated_at and version, a non-negative integer that
    starts at 1 on creation and increments by exactly 1 on every server-
    side mutation of that row."
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601 UTC, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, "
        f"got {data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: AuditEvent rows "are append-only: they carry an id and
    a created_at but have no updated_at field and no version field"."""
    assert "updated_at" not in data, (
        "append-only resource must not carry updated_at"
    )
    assert "version" not in data, (
        "append-only resource must not carry version"
    )


# ---------------------------------------------------------------------------
# Physician — PRD §3.1
# ---------------------------------------------------------------------------
def assert_physician(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    full_name = data.get("full_name")
    assert isinstance(full_name, str) and full_name, "full_name required"
    npi = data.get("npi_number")
    assert isinstance(npi, str) and len(npi) == 10 and npi.isdigit(), (
        f"npi_number must be exactly 10 digits, got {npi!r}"
    )
    # PRD §3.1: status defaults to ACTIVE; alternative is SUSPENDED.
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}, (
        f"physician.status must be ACTIVE or SUSPENDED, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# StateLicense — PRD §3.1
# ---------------------------------------------------------------------------
def assert_state_license(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    state = data.get("state_code")
    assert (
        isinstance(state, str) and len(state) == 2 and state.isupper()
    ), f"state_code must be two uppercase letters, got {state!r}"
    # PRD §3.1: license_type "either FULL for a traditional single-state
    # license or IMLC_EXPEDITED for one issued through the Compact".
    assert data.get("license_type") in {"FULL", "IMLC_EXPEDITED"}, (
        f"license_type must be FULL or IMLC_EXPEDITED, "
        f"got {data.get('license_type')!r}"
    )
    # PRD §2.9: status projection — one of ACTIVE | EXPIRED | REVOKED.
    assert data.get("status") in {"ACTIVE", "EXPIRED", "REVOKED"}, (
        f"license.status must be ACTIVE/EXPIRED/REVOKED, "
        f"got {data.get('status')!r}"
    )
    issued = data.get("issued_at")
    expires = data.get("expires_at")
    assert is_iso8601_timestamp(issued), "issued_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(expires), "expires_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Patient — PRD §3.2
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    name = data.get("full_name")
    assert isinstance(name, str) and name, "full_name required"
    state = data.get("home_state_code")
    assert (
        isinstance(state, str) and len(state) == 2 and state.isupper()
    ), f"home_state_code must be two uppercase letters, got {state!r}"


# ---------------------------------------------------------------------------
# Consult — PRD §3.3
# ---------------------------------------------------------------------------
def assert_consult(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    # PRD §3.3 — status enum.
    assert data.get("status") in {
        "REQUESTED", "ROUTED", "IN_PROGRESS",
        "COMPLETED", "CLOSED", "DECLINED",
    }, (
        f"consult.status must be a Consult status, "
        f"got {data.get('status')!r}"
    )
    # PRD §3.3 — billing_mode.
    assert data.get("billing_mode") in {"INSURANCE", "SELF_PAY"}, (
        f"billing_mode must be INSURANCE or SELF_PAY, "
        f"got {data.get('billing_mode')!r}"
    )
    # PRD §3.3 — visit_tier.
    assert data.get("visit_tier") in {"BRIEF", "STANDARD", "EXTENDED"}, (
        f"visit_tier must be BRIEF/STANDARD/EXTENDED, "
        f"got {data.get('visit_tier')!r}"
    )


# ---------------------------------------------------------------------------
# Prescription — PRD §3.4
# ---------------------------------------------------------------------------
def assert_prescription(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in {
        "DRAFT", "ISSUED", "TRANSMITTED", "DISPENSED", "VOIDED",
    }, (
        f"prescription.status must be a Prescription status, "
        f"got {data.get('status')!r}"
    )
    assert data.get("dea_schedule") in {"NONE", "II", "III", "IV", "V"}, (
        f"dea_schedule must be NONE/II/III/IV/V, "
        f"got {data.get('dea_schedule')!r}"
    )


# ---------------------------------------------------------------------------
# InsuranceClaim — PRD §3.7
# ---------------------------------------------------------------------------
def assert_insurance_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in {
        "SUBMITTED", "APPROVED", "DENIED", "APPEALED", "PAID",
    }, (
        f"claim.status must be a InsuranceClaim status, "
        f"got {data.get('status')!r}"
    )
    # PRD §3.7: monetary fields are integers in cents.
    for field in (
        "billed_cents", "deductible_applied_cents",
        "copay_applied_cents", "coinsurance_applied_cents",
        "patient_responsibility_cents",
    ):
        val = data.get(field)
        assert isinstance(val, int) and val >= 0, (
            f"claim.{field} must be non-negative int cents, got {val!r}"
        )


def assert_claim_waterfall_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.7: "The patient's patient_responsibility_cents is the sum
    of the three step amounts".
    """
    s = (
        data["deductible_applied_cents"]
        + data["copay_applied_cents"]
        + data["coinsurance_applied_cents"]
    )
    assert data["patient_responsibility_cents"] == s, (
        f"patient_responsibility_cents must equal sum of waterfall: "
        f"deductible+copay+coinsurance ({s}), "
        f"got {data['patient_responsibility_cents']}"
    )


def assert_claim_billed_conservation(data: Dict[str, Any]) -> None:
    """PRD §3.7: "marks an APPROVED claim as paid, which sets
    payer_paid_cents to billed_cents minus patient_responsibility_cents".

    Combined with the waterfall invariant, this implies:
       deductible + copay + coinsurance + payer_paid_cents == billed_cents
    """
    total = (
        data["deductible_applied_cents"]
        + data["copay_applied_cents"]
        + data["coinsurance_applied_cents"]
        + data["payer_paid_cents"]
    )
    assert total == data["billed_cents"], (
        f"billed_cents conservation broken: "
        f"deductible+copay+coinsurance+payer_paid_cents == "
        f"{total}, expected billed_cents={data['billed_cents']}"
    )


# ---------------------------------------------------------------------------
# SelfPayInvoice — PRD §3.7
# ---------------------------------------------------------------------------
def assert_self_pay_invoice(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in {"ISSUED", "PAID", "VOIDED"}, (
        f"invoice.status must be ISSUED/PAID/VOIDED, "
        f"got {data.get('status')!r}"
    )
    for field in ("subtotal_cents", "discount_cents", "amount_due_cents"):
        val = data.get(field)
        assert isinstance(val, int) and val >= 0, (
            f"invoice.{field} must be non-negative int cents, got {val!r}"
        )
    # PRD §3.7: "amount_due_cents equal to subtotal minus discount".
    assert data["amount_due_cents"] == (
        data["subtotal_cents"] - data["discount_cents"]
    ), (
        f"invoice.amount_due_cents must equal subtotal_cents - "
        f"discount_cents, got {data['amount_due_cents']}"
    )


# ---------------------------------------------------------------------------
# FollowUp — PRD §3.7
# ---------------------------------------------------------------------------
def assert_followup(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert data.get("status") in {
        "SCHEDULED", "COMPLETED", "MISSED", "CANCELLED",
    }, (
        f"followup.status must be a FollowUp status, "
        f"got {data.get('status')!r}"
    )
    due_by = data.get("due_by")
    assert is_iso8601_timestamp(due_by), (
        f"followup.due_by must be ISO 8601 UTC, got {due_by!r}"
    )


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.4 (append-only) + §2.10
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    """PRD §2.4: AuditEvent "carry an id and a created_at but have no
    updated_at field and no version field".
    PRD §2.10: event_type is one of the seven enumerated categories;
    subject_entity, subject_id, actor_role, and payload_json are
    captured.
    """
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert data.get("event_type") in {
        "CONSULT_ROUTED", "RX_ISSUED", "RX_VOIDED", "CLAIM_PAID",
        "LICENSE_REVOKED", "COMPLIANCE_FAILURE", "CLOCK_ADVANCED",
    }, (
        f"audit_event.event_type must be one of the seven types, "
        f"got {data.get('event_type')!r}"
    )
    assert isinstance(data.get("subject_entity"), str)
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_role"), str)


# ---------------------------------------------------------------------------
# Version invariants — PRD §2.4
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(
    *, before: Dict[str, Any], after: Dict[str, Any]
) -> None:
    """PRD §2.4: "version, a non-negative integer that starts at 1 on
    creation and increments by exactly 1 on every server-side mutation
    of that row."""
    assert after["version"] == before["version"] + 1, (
        f"version must increment by exactly 1 on mutation: "
        f"before={before['version']}, after={after['version']}"
    )


__all__ = [
    "assert_physician",
    "assert_state_license",
    "assert_patient",
    "assert_consult",
    "assert_prescription",
    "assert_insurance_claim",
    "assert_claim_waterfall_invariant",
    "assert_claim_billed_conservation",
    "assert_self_pay_invoice",
    "assert_followup",
    "assert_audit_event",
    "assert_version_incremented_by_one",
]
