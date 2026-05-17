"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally permissive on optional fields —
when PRD prose is silent on a specific projection, the assertion does
not pin it.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4.
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: "id is a server-minted UUID string, with no type
    prefix" and "created_at is an ISO 8601 UTC timestamp with three
    fractional digits, recording first-creation time."
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
    """PRD §2.4: "updated_at is an ISO 8601 UTC timestamp with three
    fractional digits, refreshed on every mutation." and "version is an
    integer that begins at 1 on creation and increments by exactly 1 on
    every server-side mutation".
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


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only resources "carry only id and created_at —
    they have no updated_at and no version field." Applies to
    ConsentVersion and Payment."""
    assert "updated_at" not in data, (
        "append-only resource must not carry updated_at"
    )
    assert "version" not in data, (
        "append-only resource must not carry version"
    )


# ---------------------------------------------------------------------------
# Trial — PRD §3.1 / §3.3.
# ---------------------------------------------------------------------------
TRIAL_STATUSES = {
    "DRAFT", "IRB_PENDING", "APPROVED", "OPEN_FOR_ENROLLMENT",
    "CLOSED_TO_ENROLLMENT", "COMPLETED", "TERMINATED",
}


def assert_trial(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("protocol_code"), str)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("sponsor_org"), str)
    assert data.get("status") in TRIAL_STATUSES, (
        f"unexpected trial status {data.get('status')!r}"
    )
    assert isinstance(data.get("inclusion_criteria"), list)
    assert isinstance(data.get("exclusion_criteria"), list)
    # PRD §3.1: "a freshly created trial begins life in DRAFT status
    # with active_consent_version of null".
    if "active_consent_version" in data:
        acv = data["active_consent_version"]
        assert acv is None or (isinstance(acv, int) and acv >= 1)
    # PRD §3.1: randomization_scheme in {SIMPLE_BERNOULLI,
    # PERMUTED_BLOCK, STRATIFIED_BLOCK}.
    assert data.get("randomization_scheme") in {
        "SIMPLE_BERNOULLI", "PERMUTED_BLOCK", "STRATIFIED_BLOCK",
    }
    # PRD §3.1: target_enrollment 1..10000; blood_draw_window_days 0..14.
    assert isinstance(data.get("target_enrollment"), int)
    assert 1 <= data["target_enrollment"] <= 10000
    assert isinstance(data.get("blood_draw_window_days"), int)
    assert 0 <= data["blood_draw_window_days"] <= 14
    ec = data.get("enrolled_count")
    assert isinstance(ec, int) and ec >= 0


# ---------------------------------------------------------------------------
# Arm — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_arm(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("trial_id", ""))
    code = data.get("code")
    assert isinstance(code, str) and 1 <= len(code) <= 8
    assert isinstance(data.get("label"), str)
    weight = data.get("weight")
    # PRD §3.1: "a weight integer between 1 and 10 inclusive."
    assert isinstance(weight, int) and 1 <= weight <= 10
    ac = data.get("assigned_count")
    assert isinstance(ac, int) and ac >= 0


# ---------------------------------------------------------------------------
# ConsentVersion — PRD §2.10 (append-only). PRD §2.10 names a domain
# `version` field on ConsentVersion (chain index 1, 2, 3, ...). PRD §2.4
# also says append-only resources have "no version field" — the only
# consistent reading is that §2.4's "version" refers to the OCC mutation
# version (which ConsentVersion lacks because it is immutable), while
# the §2.10 chain-index `version` is part of ConsentVersion's domain.
# `updated_at` is unambiguously absent.
# ---------------------------------------------------------------------------
def assert_consent_version(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert "updated_at" not in data, (
        "append-only resource must not carry updated_at"
    )
    assert is_valid_uuid(data.get("trial_id", ""))
    v = data.get("version")
    # PRD §2.10: "When a PrincipalInvestigator publishes the first
    # consent for a trial, it is assigned version 1 and the trial's
    # active_consent_version is set to 1."
    assert isinstance(v, int) and v >= 1
    assert isinstance(data.get("document_uri"), str)
    assert isinstance(data.get("requires_re_consent", False), bool)
    assert is_iso8601_timestamp(data.get("published_at", ""))


# ---------------------------------------------------------------------------
# Participant — PRD §3.4 / §3.5.
# ---------------------------------------------------------------------------
PARTICIPANT_STATUSES = {
    "SCREENING", "ELIGIBLE", "CONSENT_PENDING", "ENROLLED",
    "WITHDRAWN", "COMPLETED", "INELIGIBLE",
}


def assert_participant(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("trial_id", ""))
    arm_id = data.get("arm_id")
    if arm_id is not None:
        assert is_valid_uuid(arm_id)
    assert isinstance(data.get("profile"), dict)
    assert data.get("status") in PARTICIPANT_STATUSES, (
        f"unexpected participant status {data.get('status')!r}"
    )
    scv = data.get("signed_consent_version")
    if scv is not None:
        assert isinstance(scv, int) and scv >= 1
    es = data.get("eligibility_score")
    if es is not None:
        assert isinstance(es, (int, float))
        assert 0.0 <= float(es) <= 100.0
    oc = data.get("open_ae_count")
    assert isinstance(oc, int) and oc >= 0
    enr = data.get("enrolled_at")
    if enr is not None:
        assert is_iso8601_timestamp(enr)


# ---------------------------------------------------------------------------
# Visit — PRD §3.6.
# ---------------------------------------------------------------------------
VISIT_STATUSES = {"SCHEDULED", "COMPLETED", "MISSED", "CANCELLED"}


def assert_visit(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    sn = data.get("sequence_no")
    # PRD §3.6: "a 1-indexed sequence_no between 1 and 50".
    assert isinstance(sn, int) and 1 <= sn <= 50
    assert isinstance(data.get("target_date"), str)
    assert data.get("status") in VISIT_STATUSES
    ad = data.get("actual_draw_at")
    if ad is not None:
        assert isinstance(ad, str)
    cc = data.get("compensation_cents")
    # PRD §3.6: "compensation_cents at zero" until completion.
    assert isinstance(cc, int) and cc >= 0


# ---------------------------------------------------------------------------
# AdverseEvent — PRD §3.7.
# ---------------------------------------------------------------------------
AE_STATUSES = {"OPEN", "UNDER_REVIEW", "RESOLVED", "ESCALATED_HOLD"}
AE_SEVERITIES = {"MILD", "MODERATE", "SEVERE", "LIFE_THREATENING"}


def assert_adverse_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data.get("severity") in AE_SEVERITIES
    assert data.get("status") in AE_STATUSES
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert isinstance(data.get("narrative"), str)
    cvi = data.get("caused_visit_id")
    if cvi is not None:
        assert is_valid_uuid(cvi)


# ---------------------------------------------------------------------------
# IRBReview — PRD §3.2.
# ---------------------------------------------------------------------------
IRB_DECISIONS = {"APPROVED", "REVISIONS_REQUESTED", "REJECTED"}


def assert_irb_review(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("trial_id", ""))
    assert data.get("decision") in IRB_DECISIONS
    # PRD §3.2: "with the reviewer's X-User-ID stored as reviewer_id".
    assert isinstance(data.get("reviewer_id"), str)
    assert data["reviewer_id"]
    assert is_iso8601_timestamp(data.get("decided_at", ""))
    assert isinstance(data.get("notes"), str)


# ---------------------------------------------------------------------------
# Payment — PRD §3.8 (append-only).
# ---------------------------------------------------------------------------
PAYMENT_KINDS = {"PROVISIONAL", "FINAL", "REVERSAL"}


def assert_payment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("visit_id", ""))
    assert data.get("kind") in PAYMENT_KINDS
    ac = data.get("amount_cents")
    # PRD §3.8: amount_cents is "positive for PROVISIONAL and FINAL and
    # negative for REVERSAL".
    assert isinstance(ac, int)
    if data["kind"] in {"PROVISIONAL", "FINAL"}:
        assert ac >= 0
    elif data["kind"] == "REVERSAL":
        assert ac <= 0
    # PRD §3.8: "paid_at timestamp that is set only on FINAL rows."
    paid_at = data.get("paid_at")
    if data["kind"] == "FINAL":
        assert isinstance(paid_at, str) and is_iso8601_timestamp(paid_at)
    else:
        assert paid_at is None, (
            f"non-FINAL payment must have paid_at == null, "
            f"got {paid_at!r}"
        )


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4 / §2.6.
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "version is an integer that begins at 1 on creation
    and increments by exactly 1 on every server-side mutation".
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, "
        f"got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Eligibility-score precision — PRD §2.11.
# ---------------------------------------------------------------------------
def assert_eligibility_score_precision(score: float) -> None:
    """PRD §2.11: "The eligibility score is expressed with one decimal
    place. Multiplications, divisions, and other intermediate decimal
    operations that feed into the eligibility score are rounded using
    the half-up convention before the score is recorded."
    """
    assert 0.0 <= score <= 100.0, (
        f"eligibility_score must be in [0, 100], got {score}"
    )
    rounded = round(score + 1e-9, 1)
    assert abs(score - rounded) < 1e-6, (
        f"eligibility_score {score} must be at one decimal place"
    )


__all__ = [
    "TRIAL_STATUSES",
    "PARTICIPANT_STATUSES",
    "VISIT_STATUSES",
    "AE_STATUSES",
    "AE_SEVERITIES",
    "IRB_DECISIONS",
    "PAYMENT_KINDS",
    "assert_trial",
    "assert_arm",
    "assert_consent_version",
    "assert_participant",
    "assert_visit",
    "assert_adverse_event",
    "assert_irb_review",
    "assert_payment",
    "assert_version_incremented_by_one",
    "assert_eligibility_score_precision",
]
