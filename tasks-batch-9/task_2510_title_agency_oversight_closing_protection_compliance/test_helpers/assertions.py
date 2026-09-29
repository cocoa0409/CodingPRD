"""Domain assertions for the Title Agency Oversight API.

These wrap the repeated shape checks the PRD states once and expects everywhere:
the four common fields of §2.4, the version-increments-on-every-mutation rule,
half-up money rounding of §2.5, the posture ladder of §2.6, and the two
conserved ledgers of §2.7.
"""

import math
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    DEFALCATION_RISK_THRESHOLD,
    UNREMITTED_TOLERANCE_CENTS,
    UNREPORTED_POLICY_RESTRICT_THRESHOLD,
    WATCH_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any], label: str = "row") -> None:
    """Every resource carries `id`, `created_at`, `updated_at` and `version`."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row, f"{label} is missing the common field '{field}': {row}"
    assert is_valid_uuid(row["id"]), f"{label}.id is not a UUID: {row['id']}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"{label}.created_at is not ISO 8601: {row['created_at']}"
    assert is_iso8601_timestamp(
        row["updated_at"]
    ), f"{label}.updated_at is not ISO 8601: {row['updated_at']}"
    assert isinstance(row["version"], int) and not isinstance(
        row["version"], bool
    ), f"{label}.version must be an integer, got {row['version']!r}"
    assert row["version"] >= 1, f"{label}.version must start at 1, got {row['version']}"


def assert_fresh_row(row: Dict[str, Any], label: str = "row") -> None:
    """A row that has never been mutated: `version` is exactly 1."""
    assert_common_fields(row, label)
    assert (
        row["version"] == 1
    ), f"{label}.version must be 1 on creation, got {row['version']}"


def assert_version_bumped_by(
    before: Dict[str, Any], after: Dict[str, Any], expected_delta: int, label: str = "row"
) -> None:
    """`version` moves by exactly `expected_delta` across a mutation."""
    actual = after["version"] - before["version"]
    assert actual == expected_delta, (
        f"{label}.version should have advanced by {expected_delta} "
        f"({before['version']} -> {before['version'] + expected_delta}), "
        f"but it moved to {after['version']}"
    )


def assert_version_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], label: str = "row"
) -> None:
    """A rejected call leaves `version` alone."""
    assert after["version"] == before["version"], (
        f"{label}.version must not change on a rejected call, but it moved "
        f"{before['version']} -> {after['version']}"
    )


def assert_fields_equal(
    row: Dict[str, Any], expected: Dict[str, Any], label: str = "row"
) -> None:
    """Every key of `expected` is present in `row` with exactly that value."""
    for key, value in expected.items():
        assert key in row, f"{label} is missing field '{key}': {row}"
        assert row[key] == value, (
            f"{label}.{key} should be {value!r} but is {row[key]!r}"
        )


def assert_echoes_input(
    row: Dict[str, Any], payload: Dict[str, Any], label: str = "row"
) -> None:
    """A created row echoes every client-supplied field it persists."""
    for key, value in payload.items():
        if key == "expected_agency_version":
            continue
        assert key in row, f"{label} did not persist input field '{key}': {row}"
        assert row[key] == value, (
            f"{label}.{key} should echo the submitted {value!r} but is {row[key]!r}"
        )


def assert_nulls(row: Dict[str, Any], fields: Iterable[str], label: str = "row") -> None:
    for field in fields:
        assert row.get(field) is None, (
            f"{label}.{field} should still be null but is {row.get(field)!r}"
        )


# ---------------------------------------------------------------------------
# Money (PRD §2.5)
# ---------------------------------------------------------------------------


def half_up(value: float) -> int:
    """Round half away from zero, the PRD's "round half up" rule."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def expected_agency_share(gross_cents: int, agency_pct: float) -> int:
    """Half-up agency retention on one line (PRD §2.5)."""
    return half_up(gross_cents * agency_pct)


def assert_money_equal(actual: Any, expected: int, label: str) -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer cent amount, got {actual!r}"
    )
    assert actual == expected, f"{label} should be {expected} cents but is {actual}"


def assert_split_conserves(
    gross_cents: int, agency_cents: int, underwriter_cents: int, label: str = "split"
) -> None:
    """Retention plus underwriter share reconstitutes the gross exactly."""
    assert agency_cents + underwriter_cents == gross_cents, (
        f"{label}: {agency_cents} + {underwriter_cents} = "
        f"{agency_cents + underwriter_cents}, which does not equal the gross "
        f"{gross_cents}"
    )


def assert_floored(actual: int, raw: float, label: str) -> None:
    """A cap the PRD floors to whole cents."""
    assert actual == math.floor(raw), (
        f"{label} should be the floor of {raw} = {math.floor(raw)} but is {actual}"
    )


# ---------------------------------------------------------------------------
# Oversight posture (PRD §2.6)
# ---------------------------------------------------------------------------


def expected_posture(agency: Dict[str, Any]) -> str:
    """Recompute the posture ladder from the agency's own stored fields."""
    if agency["appointment_status"] in ("SUSPENDED", "TERMINATED"):
        return "FROZEN"
    if agency["escrow_standing"] == "DEFALCATION_RISK":
        return "FROZEN"
    if agency["appointment_status"] == "PENDING_REVIEW":
        return "RESTRICTED"
    if agency["financial_review_status"] != "ACCEPTED":
        return "RESTRICTED"
    if agency["escrow_standing"] == "WATCH":
        return "RESTRICTED"
    if agency["open_critical_finding_count"] >= 1:
        return "RESTRICTED"
    if agency["unreported_policy_count"] >= UNREPORTED_POLICY_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    if agency["unremitted_premium_cents"] > UNREMITTED_TOLERANCE_CENTS:
        return "RESTRICTED"
    return "OPEN"


def assert_posture(agency: Dict[str, Any], expected: str) -> None:
    """The stored posture is `expected` and agrees with the ladder inputs."""
    actual = agency.get("oversight_posture")
    assert actual == expected, (
        f"oversight_posture should be {expected} but is {actual}; inputs were "
        f"appointment_status={agency.get('appointment_status')}, "
        f"financial_review_status={agency.get('financial_review_status')}, "
        f"escrow_standing={agency.get('escrow_standing')}, "
        f"open_critical_finding_count={agency.get('open_critical_finding_count')}, "
        f"unreported_policy_count={agency.get('unreported_policy_count')}, "
        f"unremitted_premium_cents={agency.get('unremitted_premium_cents')}"
    )
    recomputed = expected_posture(agency)
    assert recomputed == expected, (
        f"the agency's own ladder inputs derive {recomputed}, not the asserted "
        f"{expected}; the fixture state is wrong"
    )


def assert_escrow_standing(agency: Dict[str, Any], expected: str) -> None:
    actual = agency.get("escrow_standing")
    assert actual == expected, (
        f"escrow_standing should be {expected} but is {actual} "
        f"(defalcation_score={agency.get('defalcation_score')})"
    )


def expected_standing_for_score(score: int) -> str:
    """`DEFALCATION_RISK` at 60 or more, `WATCH` at 30 or more, else COMPLIANT."""
    if score >= DEFALCATION_RISK_THRESHOLD:
        return "DEFALCATION_RISK"
    if score >= WATCH_THRESHOLD:
        return "WATCH"
    return "COMPLIANT"


def assert_defalcation_score(agency: Dict[str, Any], expected: int) -> None:
    actual = agency.get("defalcation_score")
    assert actual == expected, (
        f"defalcation_score should be {expected} but is {actual}"
    )
    assert 0 <= actual <= 100, f"defalcation_score out of range: {actual}"


# ---------------------------------------------------------------------------
# Conserved ledgers (PRD §2.7)
# ---------------------------------------------------------------------------


def assert_exposure_ledger(agency: Dict[str, Any], expected_cents: int) -> None:
    assert_money_equal(
        agency.get("cpl_outstanding_exposure_cents"),
        expected_cents,
        "cpl_outstanding_exposure_cents",
    )


def assert_unremitted_ledger(agency: Dict[str, Any], expected_cents: int) -> None:
    assert_money_equal(
        agency.get("unremitted_premium_cents"),
        expected_cents,
        "unremitted_premium_cents",
    )


def assert_exposure_matches_issued_letters(
    agency: Dict[str, Any], letters: List[Dict[str, Any]]
) -> None:
    """The ledger equals the sum of `approved_coverage_cents` over ISSUED letters."""
    expected = sum(
        letter["approved_coverage_cents"]
        for letter in letters
        if letter["status"] == "ISSUED"
    )
    assert_exposure_ledger(agency, expected)


def assert_unremitted_matches_files(
    agency: Dict[str, Any], policy_files: List[Dict[str, Any]]
) -> None:
    """The ledger equals the gross premium of issued, not-yet-remitted files."""
    expected = sum(
        pf["gross_premium_cents"]
        for pf in policy_files
        if pf["issuance_status"] in ("ISSUED", "LATE_ISSUED")
        and pf["remittance_status"] in ("UNREPORTED", "REPORTED", "DISPUTED")
    )
    assert_unremitted_ledger(agency, expected)


# ---------------------------------------------------------------------------
# State dimensions
# ---------------------------------------------------------------------------


def assert_state(row: Dict[str, Any], field: str, expected: str) -> None:
    actual = row.get(field)
    assert actual == expected, f"{field} should be {expected} but is {actual}"


def assert_letter_status(letter: Dict[str, Any], expected: str) -> None:
    assert_state(letter, "status", expected)


def assert_issuance_status(policy_file: Dict[str, Any], expected: str) -> None:
    assert_state(policy_file, "issuance_status", expected)


def assert_remittance_status(policy_file: Dict[str, Any], expected: str) -> None:
    assert_state(policy_file, "remittance_status", expected)


def assert_transfer_status(policy_file: Dict[str, Any], expected: str) -> None:
    assert_state(policy_file, "transfer_status", expected)


def assert_statement_status(statement: Dict[str, Any], expected: str) -> None:
    assert_state(statement, "status", expected)


def assert_audit_status(audit: Dict[str, Any], expected: str) -> None:
    assert_state(audit, "status", expected)


def assert_finding_status(finding: Dict[str, Any], expected: str) -> None:
    assert_state(finding, "status", expected)


def assert_claim_status(claim: Dict[str, Any], expected: str) -> None:
    assert_state(claim, "status", expected)


def assert_appointment_status(agency: Dict[str, Any], expected: str) -> None:
    assert_state(agency, "appointment_status", expected)


def assert_policy_dimensions(
    policy_file: Dict[str, Any],
    issuance: str,
    remittance: str,
    transfer: str,
) -> None:
    """All three independent dimensions of a policy file at once (PRD §3.4)."""
    assert (
        policy_file.get("issuance_status"),
        policy_file.get("remittance_status"),
        policy_file.get("transfer_status"),
    ) == (issuance, remittance, transfer), (
        f"policy file dimensions should be ({issuance}, {remittance}, {transfer}) "
        f"but are ({policy_file.get('issuance_status')}, "
        f"{policy_file.get('remittance_status')}, "
        f"{policy_file.get('transfer_status')})"
    )


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------


def assert_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta.get("limit") == limit, f"meta.limit should be {limit}: {meta}"
    assert meta.get("offset") == offset, f"meta.offset should be {offset}: {meta}"
    assert meta.get("total_count") == total_count, (
        f"meta.total_count should be {total_count}: {meta}"
    )
    assert meta.get("has_more") is has_more, (
        f"meta.has_more should be {has_more}: {meta}"
    )


def assert_total_count(meta: Dict[str, Any], expected: int) -> None:
    assert meta.get("total_count") == expected, (
        f"meta.total_count should be {expected} but is {meta.get('total_count')}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """"Results are ordered by `created_at` ascending"."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"list results must be ordered by created_at ascending, got {stamps}"
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["id"] == row_id:
            return row
    return None


def assert_contains_id(
    rows: Iterable[Dict[str, Any]], row_id: str, context: str = "the listing"
) -> Dict[str, Any]:
    row = find_by_id(rows, row_id)
    assert row is not None, f"{row_id} is absent from {context} {ids_of(rows)}"
    return row


def assert_excludes_id(
    rows: Iterable[Dict[str, Any]], row_id: str, context: str = "the listing"
) -> None:
    assert find_by_id(rows, row_id) is None, (
        f"{row_id} should not appear in {context} {ids_of(rows)}"
    )


# ---------------------------------------------------------------------------
# Cascade attribution (PRD §3.3, §3.6, §3.7)
# ---------------------------------------------------------------------------


def assert_system_actor(row: Dict[str, Any], field: str) -> None:
    """A cascade-written actor field records the literal `SYSTEM`."""
    actual = row.get(field)
    assert actual == "SYSTEM", (
        f"{field} should record the cascade actor SYSTEM but is {actual!r}"
    )


def assert_actor(row: Dict[str, Any], field: str, user_id: str) -> None:
    actual = row.get(field)
    assert actual == user_id, f"{field} should record {user_id!r} but is {actual!r}"
