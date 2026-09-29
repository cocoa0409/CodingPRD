"""Domain assertion helpers.

Thin wrappers over the framework primitives that express the PRD's own
vocabulary: itemisation entries, conserved quantities, disclosure posture, and
the immutable-audit-event shape of a `LabelDisclosure`.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import REMEDIATION_AUDIT_THRESHOLD


# ---------------------------------------------------------------------------
# Envelope / identity
# ---------------------------------------------------------------------------


def assert_resource_identity(resource: Dict[str, Any]) -> None:
    """Every resource carries a UUID `id` and an ISO-8601 `created_at`."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert_timestamp_format(resource["created_at"])


def assert_mutable_resource(resource: Dict[str, Any]) -> None:
    """A mutable resource additionally carries `updated_at` and an integer
    `version`."""
    assert_resource_identity(resource)
    assert_timestamp_format(resource["updated_at"])
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"


def assert_immutable_audit_event(resource: Dict[str, Any]) -> None:
    """A `LabelDisclosure` carries `id` and `created_at` but neither
    `updated_at` nor `version`."""
    assert_resource_identity(resource)
    assert "updated_at" not in resource, "an immutable audit event has no updated_at"
    assert "version" not in resource, "an immutable audit event has no version"


# ---------------------------------------------------------------------------
# Fee itemisation
# ---------------------------------------------------------------------------


def itemization_entry(
    label: Dict[str, Any], fee_code: str, phase: str
) -> Dict[str, Any]:
    """The single `fee_itemization` entry for `fee_code` under `phase`."""
    matches = [
        entry
        for entry in label["fee_itemization"]
        if entry["fee_code"] == fee_code and entry["phase"] == phase
    ]
    assert len(matches) == 1, (
        f"expected exactly one itemisation entry for {fee_code} in phase {phase}, "
        f"found {len(matches)}"
    )
    return matches[0]


def itemization_amount(label: Dict[str, Any], fee_code: str, phase: str) -> int:
    return itemization_entry(label, fee_code, phase)["amount_cents"]


def assert_itemization_amount(
    label: Dict[str, Any], fee_code: str, phase: str, expected_cents: int
) -> None:
    actual = itemization_amount(label, fee_code, phase)
    assert actual == expected_cents, (
        f"{fee_code} in phase {phase}: expected {expected_cents} cents, got {actual}"
    )


def itemized_fee_codes(label: Dict[str, Any], phase: Optional[str] = None) -> List[str]:
    return [
        entry["fee_code"]
        for entry in label["fee_itemization"]
        if phase is None or entry["phase"] == phase
    ]


# ---------------------------------------------------------------------------
# Conserved quantities (PRD §2.12)
# ---------------------------------------------------------------------------


def assert_evidence_sample_total(plan: Dict[str, Any], expected_total: int) -> None:
    """`evidence_sample_total` is the sum of `sample_count` over the plan's
    `INCLUDED` runs."""
    assert plan["evidence_sample_total"] == expected_total, (
        f"evidence_sample_total: expected {expected_total}, "
        f"got {plan['evidence_sample_total']}"
    )


def assert_evidence_sample_total_matches_runs(
    plan: Dict[str, Any], runs: Iterable[Dict[str, Any]]
) -> None:
    expected = sum(
        run["sample_count"] for run in runs if run["status"] == "INCLUDED"
    )
    assert_evidence_sample_total(plan, expected)


def assert_account_ledger(
    account: Dict[str, Any],
    expected_balance_cents: int,
    expected_remediation_count: int,
) -> None:
    """`credit_balance_cents`, `remediation_count` and the derived `audit_flag`
    together, since the flag is a pure function of the count."""
    assert account["credit_balance_cents"] == expected_balance_cents, (
        f"credit_balance_cents: expected {expected_balance_cents}, "
        f"got {account['credit_balance_cents']}"
    )
    assert account["remediation_count"] == expected_remediation_count, (
        f"remediation_count: expected {expected_remediation_count}, "
        f"got {account['remediation_count']}"
    )
    assert account["audit_flag"] is (
        expected_remediation_count >= REMEDIATION_AUDIT_THRESHOLD
    ), (
        f"audit_flag must be true exactly while remediation_count is "
        f"{REMEDIATION_AUDIT_THRESHOLD} or more"
    )


def assert_account_ledger_matches_credits(
    account: Dict[str, Any], credits: Iterable[Dict[str, Any]]
) -> None:
    issued = [c for c in credits if c["status"] == "ISSUED"]
    assert_account_ledger(
        account, sum(c["amount_cents"] for c in issued), len(issued)
    )


# ---------------------------------------------------------------------------
# Label state, substantiation and posture
# ---------------------------------------------------------------------------


def assert_label_dimensions(
    label: Dict[str, Any],
    expected_publication_state: str,
    expected_substantiation_status: str,
) -> None:
    """The two state dimensions move independently on the same record."""
    assert label["publication_state"] == expected_publication_state, (
        f"publication_state: expected {expected_publication_state}, "
        f"got {label['publication_state']}"
    )
    assert label["substantiation_status"] == expected_substantiation_status, (
        f"substantiation_status: expected {expected_substantiation_status}, "
        f"got {label['substantiation_status']}"
    )


def assert_posture(plan: Dict[str, Any], expected_posture: str) -> None:
    assert plan["label_posture"] == expected_posture, (
        f"label_posture: expected {expected_posture}, got {plan['label_posture']}"
    )


def assert_pinned_typical_figures(
    label: Dict[str, Any],
    expected_download: float,
    expected_upload: float,
    expected_latency: int,
) -> None:
    assert float(label["typical_download_mbps"]) == expected_download, (
        f"typical_download_mbps: expected {expected_download}, "
        f"got {label['typical_download_mbps']}"
    )
    assert float(label["typical_upload_mbps"]) == expected_upload, (
        f"typical_upload_mbps: expected {expected_upload}, "
        f"got {label['typical_upload_mbps']}"
    )
    assert label["typical_latency_ms"] == expected_latency, (
        f"typical_latency_ms: expected {expected_latency}, "
        f"got {label['typical_latency_ms']}"
    )


def assert_margins(
    attestation: Dict[str, Any],
    expected_download_margin: float,
    expected_upload_margin: float,
) -> None:
    """Margins are rounded half up to four decimal places."""
    assert round(float(attestation["download_margin_pct"]), 4) == round(
        expected_download_margin, 4
    ), (
        f"download_margin_pct: expected {expected_download_margin}, "
        f"got {attestation['download_margin_pct']}"
    )
    assert round(float(attestation["upload_margin_pct"]), 4) == round(
        expected_upload_margin, 4
    ), (
        f"upload_margin_pct: expected {expected_upload_margin}, "
        f"got {attestation['upload_margin_pct']}"
    )


def assert_optional_timestamp_absent(resource: Dict[str, Any], field: str) -> None:
    assert resource.get(field) is None, f"{field} should still be null"


def assert_optional_timestamp_present(resource: Dict[str, Any], field: str) -> None:
    value = resource.get(field)
    assert value is not None, f"{field} should have been set"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO-8601 instant: {value!r}"
