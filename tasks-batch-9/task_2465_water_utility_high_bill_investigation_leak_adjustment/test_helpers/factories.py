"""Request-payload builders.

Each builder returns a complete, valid payload for one write operation and
accepts keyword overrides so a test can bend exactly one field. Fields whose
uniqueness is enforced by the service (``code``, ``account_number``,
``meter_serial``) are suffixed from a monotonic counter unless overridden.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    METER_TEST_DEPOSIT_CENTS,
    STANDARD_RATE_SCHEDULE,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short, monotonically increasing suffix for unique-constrained fields."""
    return f"{next(_counter):05d}"


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides into a payload, dropping keys whose override is ``None``."""
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "remove this field from the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Reference data (PRD §3.1, §2.10)
# ---------------------------------------------------------------------------
def rate_schedule_payload(**overrides: Any) -> Dict[str, Any]:
    """A rate schedule matching the standard schedule, with a unique ``code``."""
    payload = dict(STANDARD_RATE_SCHEDULE)
    payload["code"] = f"RS-{unique_suffix()}"
    return _apply(payload, overrides)


def billing_period_payload(**overrides: Any) -> Dict[str, Any]:
    """A single-month SUMMER billing period."""
    payload = {
        "period_code": f"PC-{unique_suffix()}",
        "start_date": "2026-07-01",
        "end_date": "2026-07-31",
        "season": "SUMMER",
        "rebilling_deadline_date": "2027-01-31",
    }
    return _apply(payload, overrides)


def service_account_payload(rate_schedule_id: str, **overrides: Any) -> Dict[str, Any]:
    """A service account on the named rate schedule."""
    payload = {
        "account_number": f"ACC-{unique_suffix()}",
        "customer_name": "Alma Reyes",
        "service_address": "12 Cedar St",
        "rate_schedule_id": rate_schedule_id,
    }
    return _apply(payload, overrides)


def master_meter_payload(account_id: str, **overrides: Any) -> Dict[str, Any]:
    """A billable ``POTABLE_MASTER`` meter with no parentage."""
    payload = {
        "account_id": account_id,
        "meter_serial": f"MTR-{unique_suffix()}",
        "meter_type": "POTABLE_MASTER",
        "size_inches": 1.0,
        "initial_register_value": 100000,
    }
    return _apply(payload, overrides)


def submeter_payload(
    account_id: str,
    parent_meter_id: str,
    meter_type: str = "IRRIGATION_SUBMETER",
    **overrides: Any,
) -> Dict[str, Any]:
    """A submeter sitting behind a master meter on the same account."""
    payload = {
        "account_id": account_id,
        "meter_serial": f"SUB-{unique_suffix()}",
        "meter_type": meter_type,
        "size_inches": 0.75,
        "initial_register_value": 0,
        "parent_meter_id": parent_meter_id,
    }
    return _apply(payload, overrides)


def meter_reading_payload(
    meter_id: str, read_date: str, reading_value: int, **overrides: Any
) -> Dict[str, Any]:
    """An ``ACTUAL`` cumulative register read."""
    payload = {
        "meter_id": meter_id,
        "read_date": read_date,
        "read_type": "ACTUAL",
        "reading_value": reading_value,
    }
    return _apply(payload, overrides)


def corrected_reading_payload(
    meter_id: str,
    read_date: str,
    reading_value: int,
    corrects_reading_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A ``CORRECTED`` read restating an earlier row."""
    payload = {
        "meter_id": meter_id,
        "read_date": read_date,
        "read_type": "CORRECTED",
        "reading_value": reading_value,
        "corrects_reading_id": corrects_reading_id,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Billing (PRD §3.2)
# ---------------------------------------------------------------------------
def bill_payload(
    account_id: str, period_id: str, meter_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A bill-generation payload for one meter and one period."""
    payload = {
        "account_id": account_id,
        "period_id": period_id,
        "meter_id": meter_id,
        "read_type": "ACTUAL",
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Investigations and evidence (PRD §3.3, §3.6)
# ---------------------------------------------------------------------------
def investigation_payload(bill_id: str, **overrides: Any) -> Dict[str, Any]:
    """An investigation opening payload."""
    payload = {
        "bill_id": bill_id,
        "reported_cause": "bill quadrupled with no change in use",
    }
    return _apply(payload, overrides)


def evidence_request_payload(**overrides: Any) -> Dict[str, Any]:
    """An evidence request with an optional note."""
    payload = {"note": "please send the plumber invoice"}
    return _apply(payload, overrides)


def repair_proof_payload(
    investigation_id: str, leak_type: str = "SERVICE_LINE", **overrides: Any
) -> Dict[str, Any]:
    """A plumber repair proof answering an investigation."""
    payload = {
        "investigation_id": investigation_id,
        "plumber_license_no": "PL-88231",
        "repair_date": "2026-07-20",
        "leak_type": leak_type,
        "invoice_amount_cents": 185000,
        "description": "replaced 40 ft of copper service line",
    }
    return _apply(payload, overrides)


def proof_rejection_payload(**overrides: Any) -> Dict[str, Any]:
    """A repair-proof rejection with its mandatory reason."""
    payload = {"rejection_reason": "invoice does not name a licensed plumber"}
    return _apply(payload, overrides)


def determination_payload(
    leak_determination: str = "CUSTOMER_SIDE_LEAK", **overrides: Any
) -> Dict[str, Any]:
    """A determination payload."""
    payload = {"leak_determination": leak_determination}
    return _apply(payload, overrides)


def close_no_adjustment_payload(**overrides: Any) -> Dict[str, Any]:
    """A close-without-credit payload."""
    payload = {"note": "consumption confirmed, no leak evidence"}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Meter testing (PRD §3.4)
# ---------------------------------------------------------------------------
def meter_test_request_payload(
    investigation_id: str,
    meter_id: str,
    requested_test_type: str = "FIELD",
    requested_by_kind: str = "CUSTOMER",
    **overrides: Any,
) -> Dict[str, Any]:
    """A meter accuracy test request; the deposit matches who is paying."""
    payload = {
        "investigation_id": investigation_id,
        "meter_id": meter_id,
        "requested_test_type": requested_test_type,
        "requested_by_kind": requested_by_kind,
        "deposit_cents": (
            METER_TEST_DEPOSIT_CENTS if requested_by_kind == "CUSTOMER" else 0
        ),
    }
    return _apply(payload, overrides)


def field_test_window_payload(
    window_start: str = "2026-08-01T09:00:00Z",
    window_end: str = "2026-08-01T17:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A half-open field-test reservation window."""
    payload = {"window_start": window_start, "window_end": window_end}
    return _apply(payload, overrides)


def field_result_payload(
    field_result: str = "PASS", tested_at: str = "2026-08-01T10:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    """A field-test outcome recorded inside the reserved window."""
    payload = {"tested_at": tested_at, "field_result": field_result}
    return _apply(payload, overrides)


def bench_result_payload(
    low_flow_pct: float,
    mid_flow_pct: float,
    high_flow_pct: float,
    tested_at: str = "2026-08-01T10:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """The three bench flow points plus the instant they were taken."""
    payload = {
        "tested_at": tested_at,
        "low_flow_pct": low_flow_pct,
        "mid_flow_pct": mid_flow_pct,
        "high_flow_pct": high_flow_pct,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Leak adjustments (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
def leak_adjustment_payload(
    investigation_id: str,
    bill_id: str,
    leak_type: str,
    expected_investigation_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A leak-adjustment draft guarded by the investigation's version."""
    payload = {
        "investigation_id": investigation_id,
        "bill_id": bill_id,
        "leak_type": leak_type,
        "expected_investigation_version": expected_investigation_version,
    }
    return _apply(payload, overrides)


def return_payload(**overrides: Any) -> Dict[str, Any]:
    """A return-to-drafter payload."""
    payload = {"return_reason": "attach the plumber invoice scan"}
    return _apply(payload, overrides)


def denial_payload(**overrides: Any) -> Dict[str, Any]:
    """A denial payload."""
    payload = {"denial_reason": "leak predates the disputed period"}
    return _apply(payload, overrides)


def reversal_payload(**overrides: Any) -> Dict[str, Any]:
    """A reversal payload."""
    payload = {"reversal_reason": "credit granted against the wrong bill"}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Collections (PRD §3.8)
# ---------------------------------------------------------------------------
def account_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """An ad-hoc account payment."""
    payload = {"amount_cents": amount_cents, "memo": "web payment"}
    return _apply(payload, overrides)


def payment_arrangement_payload(
    account_id: str,
    bill_id: str,
    total_amount_cents: int,
    down_payment_cents: int,
    installment_count: int,
    expected_account_version: int,
    investigation_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An instalment-plan proposal guarded by the account's version."""
    payload = {
        "account_id": account_id,
        "bill_id": bill_id,
        "total_amount_cents": total_amount_cents,
        "down_payment_cents": down_payment_cents,
        "installment_count": installment_count,
        "expected_account_version": expected_account_version,
        "investigation_id": investigation_id,
    }
    return _apply(payload, overrides)


def installment_payment_payload(
    amount_cents: int, on_time: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """An instalment payment against an active plan."""
    payload = {"amount_cents": amount_cents, "on_time": on_time}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Appeals (PRD §3.9)
# ---------------------------------------------------------------------------
def board_appeal_payload(investigation_id: str, **overrides: Any) -> Dict[str, Any]:
    """An appeal filed against a determined investigation."""
    payload = {
        "investigation_id": investigation_id,
        "grounds": "the utility ignored the verified service-line repair",
    }
    return _apply(payload, overrides)


def hearing_schedule_payload(hearing_date: str, **overrides: Any) -> Dict[str, Any]:
    """A docketing payload naming the hearing date."""
    payload = {"hearing_date": hearing_date}
    return _apply(payload, overrides)


def board_decision_payload(
    decision: str = "UPHOLD", **overrides: Any
) -> Dict[str, Any]:
    """A board decision with its mandatory note."""
    payload = {
        "decision": decision,
        "decision_note": "the board reviewed the meter history and the repair proof",
    }
    return _apply(payload, overrides)
