"""Shared validation helpers used by routes.

These are the building blocks; per-endpoint orchestration lives in the
respective route handlers and service modules. The helpers honor the
priority order defined in the scaffold's `validations` table.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.errors import (
    err_audit_chain_broken,
    err_ban_the_box,
    err_candidate_not_found,
    err_consent_invalid,
    err_consent_timestamp_invalid,
    err_dispute_not_owned,
    err_order_not_found,
    err_package_set_invalid,
    err_resource_not_found,
    err_salary_history_ban,
    err_stale_version,
    err_validation_failed,
)
from core.store import store
from core.utils import parse_iso
from core.clock import logical_now


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------
def get_candidate_or_404(candidate_id: str) -> dict:
    row = store.candidates.get(candidate_id)
    if row is None or row.get("archived_at") is not None:
        raise err_candidate_not_found()
    return row


def get_order_or_404(order_id: str) -> dict:
    row = store.orders.get(order_id)
    if row is None:
        raise err_order_not_found()
    return row


def get_item_or_404(item_id: str) -> dict:
    row = store.verification_items.get(item_id)
    if row is None:
        raise err_resource_not_found()
    return row


def get_consent_or_404(consent_id: str) -> dict:
    row = store.consents.get(consent_id)
    if row is None:
        raise err_resource_not_found()
    return row


def get_dispute_or_404(dispute_id: str) -> dict:
    row = store.disputes.get(dispute_id)
    if row is None:
        raise err_resource_not_found()
    return row


def get_jurisdiction_or_404(code: str) -> dict:
    row = store.jurisdiction_policies.get(code)
    if row is None:
        raise err_resource_not_found()
    return row


# ---------------------------------------------------------------------------
# OCC
# ---------------------------------------------------------------------------
def check_version(supplied, current_version: int) -> None:
    if supplied is None:
        return
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise err_validation_failed("version must be an integer.")
    if supplied != current_version:
        raise err_stale_version()


# ---------------------------------------------------------------------------
# Required-field helpers
# ---------------------------------------------------------------------------
def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err_validation_failed(f"Field '{name}' is required.")
    return body[name]


def require_str(body: dict, name: str) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err_validation_failed(f"Field '{name}' must be a non-empty string.")
    return v


def require_int(body: dict, name: str) -> int:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation_failed(f"Field '{name}' must be an integer.")
    return v


# ---------------------------------------------------------------------------
# Salary-history ban (Priority 8)
# ---------------------------------------------------------------------------
def enforce_salary_history_ban(
    *,
    body: dict,
    candidate: Optional[dict],
    jurisdiction_code: Optional[str],
) -> None:
    """Reject any request body that names ``salary_history`` when:

    * the candidate's jurisdiction has salary_history_ban=True, OR
    * the candidate already has salary_history_disclosed=True.
    """
    has_salary_field = "salary_history" in body
    # Determine jurisdiction salary_history_ban setting.
    code = jurisdiction_code
    if code is None and candidate is not None:
        code = candidate.get("residence_jurisdiction")
    jp = store.jurisdiction_policies.get(code) if code else None
    jur_ban = bool(jp.get("salary_history_ban")) if jp is not None else False

    if has_salary_field:
        if jur_ban:
            raise err_salary_history_ban(
                "Jurisdiction prohibits salary_history."
            )
        if candidate is not None and bool(candidate.get("salary_history_disclosed")):
            raise err_salary_history_ban(
                "Candidate has already disclosed salary history; further submissions banned."
            )

    # Even if the body does not name salary_history, a candidate whose
    # salary_history_disclosed is true under a banned jurisdiction is in a
    # bad state. We only validate the *body*; nothing to do otherwise.


# ---------------------------------------------------------------------------
# Ban-the-Box gate (Priority 7)
# ---------------------------------------------------------------------------
# stages in INCREASING permissiveness for criminal screening.
# POST_OFFER is strictest, PRE_OFFER is loosest.
_STAGE_ORDER = {"POST_OFFER": 2, "POST_INTERVIEW": 1, "PRE_OFFER": 0}


def enforce_ban_the_box(*, stage_at_order: str, jurisdiction_code: str) -> None:
    jp = store.jurisdiction_policies.get(jurisdiction_code)
    if jp is None:
        # Should already be caught elsewhere, but defensively:
        raise err_ban_the_box(
            f"No jurisdiction policy configured for {jurisdiction_code}."
        )
    gate = jp.get("ban_the_box_stage")
    if stage_at_order not in _STAGE_ORDER:
        raise err_validation_failed(
            "stage_at_order must be one of PRE_OFFER, POST_INTERVIEW, POST_OFFER."
        )
    if gate not in _STAGE_ORDER:
        raise err_ban_the_box("Jurisdiction's ban_the_box_stage is invalid.")
    # The order's stage must be at or "more conservative than" the gate.
    # gate POST_OFFER -> only POST_OFFER allowed.
    # gate POST_INTERVIEW -> POST_INTERVIEW or POST_OFFER allowed.
    # gate PRE_OFFER -> all three allowed.
    if _STAGE_ORDER[stage_at_order] < _STAGE_ORDER[gate]:
        raise err_ban_the_box(
            f"stage_at_order={stage_at_order} violates jurisdiction gate {gate}."
        )


# ---------------------------------------------------------------------------
# requested_packages constraint (Priority 15)
# ---------------------------------------------------------------------------
_VALID_PACKAGES = {"CRIMINAL", "MVR", "EDUCATION"}


def enforce_requested_packages(value) -> list:
    if not isinstance(value, list) or len(value) == 0:
        raise err_package_set_invalid()
    if any((not isinstance(v, str)) or v not in _VALID_PACKAGES for v in value):
        raise err_package_set_invalid()
    if len(set(value)) != len(value):
        raise err_package_set_invalid()
    return list(value)


# ---------------------------------------------------------------------------
# Consent temporal contract (Priority 18)
# ---------------------------------------------------------------------------
def enforce_consent_timestamps(
    *, disclosure_presented_at: str, consent_timestamp: str
) -> tuple:
    try:
        presented = parse_iso(disclosure_presented_at)
        signed = parse_iso(consent_timestamp)
    except Exception:
        raise err_consent_timestamp_invalid("Timestamps must be ISO 8601 UTC.")
    now = logical_now()
    if signed > now:
        raise err_consent_timestamp_invalid("consent_timestamp is in the future.")
    if presented > signed:
        raise err_consent_timestamp_invalid(
            "disclosure_presented_at must be <= consent_timestamp."
        )
    return presented, signed


# ---------------------------------------------------------------------------
# Active consent lookup (Priority 9)
# ---------------------------------------------------------------------------
def get_active_consent_for_candidate(candidate_id: str) -> Optional[dict]:
    for c in store.consents.values():
        if c["candidate_id"] == candidate_id and c.get("status") == "ACTIVE":
            return c
    return None
