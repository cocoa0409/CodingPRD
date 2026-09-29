"""Payload builders with domain-sensible defaults.

Every builder accepts ``**overrides`` so a test can vary exactly the one field
it cares about, and drops any key explicitly set to the sentinel ``OMIT`` so
that optional-input defaulting can be probed.
"""

from typing import Any

from .constants import CLOCK_START_UTC


class _Omit:
    """Sentinel meaning "leave this key out of the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def _clean(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if not isinstance(v, _Omit)}


# ---------------------------------------------------------------------------
# Clients and matters
# ---------------------------------------------------------------------------
def client_payload(**overrides: Any) -> dict:
    payload = {
        "legal_name": "Northwind Industries, Inc.",
        "primary_state": "NY",
    }
    payload.update(overrides)
    return _clean(payload)


def matter_payload(client_id: str, **overrides: Any) -> dict:
    payload: dict = {
        "client_id": client_id,
        "name": "Northwind v. Calder — Second Request",
        "document_count": 600,
        "deadline_utc": "2026-09-30T00:00:00Z",
        "complexity_tier": "COMPLEX",
        "required_languages": ["EN", "JA"],
        "required_bar_states": ["NY"],
        "subject_matter_tags": ["ANTITRUST"],
        "pricing_model": "PER_DOCUMENT",
        "per_document_rate_cents": 150,
        "hourly_rate_cents": 6500,
        "budget_cap_cents": 600000,
        "min_staffed_reviewers": 1,
        "onsite_seat_count": 2,
        "remote_work_permitted": True,
    }
    payload.update(overrides)
    # The pricing fork has a strict shape rule: a PER_DOCUMENT matter must not
    # carry `hourly_rate_cents` and an HOURLY matter must not carry
    # `per_document_rate_cents`. Drop whichever rate the chosen model forbids
    # unless the caller deliberately supplied it (shape-rule negative tests do).
    model = payload.get("pricing_model")
    if model == "PER_DOCUMENT" and "hourly_rate_cents" not in overrides:
        payload.pop("hourly_rate_cents", None)
    if model == "HOURLY" and "per_document_rate_cents" not in overrides:
        payload.pop("per_document_rate_cents", None)
    return _clean(payload)


def suspension_payload(suspended: bool, **overrides: Any) -> dict:
    payload: dict = {"suspended": suspended}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------
def protocol_payload(expected_matter_version: int, **overrides: Any) -> dict:
    payload: dict = {
        "expected_matter_version": expected_matter_version,
        "issue_codes": ["RESPONSIVE", "NOT_RESPONSIVE", "PRIVILEGED", "HOT"],
        "privilege_criteria": ["ATTORNEY_CLIENT", "WORK_PRODUCT"],
        "qc_sample_pct": 0.10,
        "privilege_sample_pct": 0.20,
        "max_discrepancy_pct": 0.05,
        "min_pace_dph": 55,
        "second_level_required": False,
    }
    payload.update(overrides)
    return _clean(payload)


def protocol_decision_payload(decision: str, **overrides: Any) -> dict:
    payload: dict = {"decision": decision}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Reviewers
# ---------------------------------------------------------------------------
def reviewer_payload(**overrides: Any) -> dict:
    payload: dict = {
        "full_name": "Ada Ishikawa",
        "bar_admissions": ["NY"],
        "languages": ["EN", "JA"],
        "subject_matter_tags": ["ANTITRUST"],
        "tier": "FIRST_PASS",
        "hourly_cost_cents": 5200,
        "max_concurrent_batches": 2,
        "remote_work_authorized": False,
    }
    payload.update(overrides)
    return _clean(payload)


def credential_status_payload(to_status: str, **overrides: Any) -> dict:
    payload: dict = {"to_status": to_status}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Screenings and agreements
# ---------------------------------------------------------------------------
def screening_payload(reviewer_id: str, matter_id: str, **overrides: Any) -> dict:
    payload: dict = {
        "reviewer_id": reviewer_id,
        "matter_id": matter_id,
        "declared_adverse_parties": [],
    }
    payload.update(overrides)
    return _clean(payload)


def screening_decision_payload(outcome: str, **overrides: Any) -> dict:
    payload: dict = {"outcome": outcome}
    payload.update(overrides)
    return _clean(payload)


def waiver_payload(granted: bool, **overrides: Any) -> dict:
    payload: dict = {"granted": granted}
    payload.update(overrides)
    return _clean(payload)


def agreement_payload(reviewer_id: str, matter_id: str, **overrides: Any) -> dict:
    payload: dict = {
        "reviewer_id": reviewer_id,
        "matter_id": matter_id,
        "coverage_start_utc": "2026-08-01T00:00:00Z",
        "coverage_end_utc": "2026-10-31T00:00:00Z",
        "remote_work_addendum": False,
    }
    payload.update(overrides)
    return _clean(payload)


def execute_payload(signature_name: str, **overrides: Any) -> dict:
    payload: dict = {"signature_name": signature_name}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def session_payload(reviewer_id: str, matter_id: str, **overrides: Any) -> dict:
    payload: dict = {
        "reviewer_id": reviewer_id,
        "matter_id": matter_id,
        "workstation_class": "ONSITE_SECURE",
        "starts_at_utc": CLOCK_START_UTC,
        "ends_at_utc": "2026-08-31T00:00:00Z",
    }
    payload.update(overrides)
    return _clean(payload)


def session_lifecycle_payload(to_status: str, **overrides: Any) -> dict:
    payload: dict = {"to_status": to_status}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Batches and assignments
# ---------------------------------------------------------------------------
def batch_payload(document_count: int, **overrides: Any) -> dict:
    payload: dict = {"document_count": document_count, "priority_rank": 5}
    payload.update(overrides)
    return _clean(payload)


def assignment_payload(
    expected_batch_version: int,
    reviewer_id: str,
    pass_type: str = "FIRST_PASS",
    **overrides: Any,
) -> dict:
    payload: dict = {
        "expected_batch_version": expected_batch_version,
        "reviewer_id": reviewer_id,
        "pass_type": pass_type,
    }
    payload.update(overrides)
    return _clean(payload)


def auto_assign_payload(
    expected_batch_version: int, pass_type: str = "FIRST_PASS", **overrides: Any
) -> dict:
    payload: dict = {
        "expected_batch_version": expected_batch_version,
        "pass_type": pass_type,
    }
    payload.update(overrides)
    return _clean(payload)


def progress_payload(
    documents_coded: int, minutes_logged: int, **overrides: Any
) -> dict:
    payload: dict = {
        "documents_coded": documents_coded,
        "minutes_logged": minutes_logged,
        "privilege_hits_logged": 0,
    }
    payload.update(overrides)
    return _clean(payload)


def void_payload(void_reason: str, **overrides: Any) -> dict:
    payload: dict = {"void_reason": void_reason}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Quality control and privilege log
# ---------------------------------------------------------------------------
def qc_sample_payload(validated_by_reviewer_id: str, **overrides: Any) -> dict:
    payload: dict = {"validated_by_reviewer_id": validated_by_reviewer_id}
    payload.update(overrides)
    return _clean(payload)


def qc_validate_payload(
    coding_error_count: int, privilege_error_count: int = 0, **overrides: Any
) -> dict:
    payload: dict = {
        "coding_error_count": coding_error_count,
        "privilege_error_count": privilege_error_count,
    }
    payload.update(overrides)
    return _clean(payload)


def privilege_entry_payload(
    document_ref: str,
    privilege_basis: str = "ATTORNEY_CLIENT",
    disposition: str = "WITHHELD",
    **overrides: Any,
) -> dict:
    payload: dict = {
        "document_ref": document_ref,
        "privilege_basis": privilege_basis,
        "disposition": disposition,
    }
    payload.update(overrides)
    return _clean(payload)


def privilege_validate_payload(accepted: bool, **overrides: Any) -> dict:
    payload: dict = {"accepted": accepted}
    payload.update(overrides)
    return _clean(payload)


def privilege_amend_payload(
    privilege_basis: str, disposition: str, **overrides: Any
) -> dict:
    payload: dict = {
        "privilege_basis": privilege_basis,
        "disposition": disposition,
    }
    payload.update(overrides)
    return _clean(payload)
