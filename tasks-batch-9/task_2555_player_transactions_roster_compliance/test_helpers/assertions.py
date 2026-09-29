"""Domain assertion helpers.

These check shapes and invariants the PRD states directly. They never recompute
a business figure; every expected number is supplied by the calling test.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_valid_uuid

from .types import IMMUTABLE_IDENTITY_FIELDS, VERSIONED_IDENTITY_FIELDS

_MILLIS_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|\+00:00)$"
)


def assert_millisecond_instant(value: Any, field_name: str) -> None:
    """A stored instant is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert _MILLIS_INSTANT.match(value), (
        f"{field_name} must be an ISO 8601 UTC instant with exactly three "
        f"fractional digits, got {value!r}"
    )


def assert_versioned_identity(resource: Dict[str, Any], label: str) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    for field in VERSIONED_IDENTITY_FIELDS:
        assert field in resource, f"{label} must expose '{field}'"
    assert is_valid_uuid(resource["id"]), (
        f"{label}.id must be a UUID with no type prefix, got {resource['id']!r}"
    )
    assert_millisecond_instant(resource["created_at"], f"{label}.created_at")
    assert_millisecond_instant(resource["updated_at"], f"{label}.updated_at")
    assert isinstance(resource["version"], int), f"{label}.version must be an integer"
    assert resource["version"] >= 1, (
        f"{label}.version starts at 1, got {resource['version']}"
    )


def assert_immutable_identity(resource: Dict[str, Any], label: str) -> None:
    """An immutable event row carries only id and created_at, never a version."""
    for field in IMMUTABLE_IDENTITY_FIELDS:
        assert field in resource, f"{label} must expose '{field}'"
    assert is_valid_uuid(resource["id"]), f"{label}.id must be a UUID"
    assert_millisecond_instant(resource["created_at"], f"{label}.created_at")
    assert "updated_at" not in resource, (
        f"{label} is immutable and must not carry 'updated_at'"
    )
    assert "version" not in resource, (
        f"{label} is immutable and must not carry 'version'"
    )


def assert_version_is(resource: Dict[str, Any], expected: int, label: str) -> None:
    """The resource's version counter is exactly the expected value."""
    assert resource["version"] == expected, (
        f"{label}.version should be {expected}, got {resource['version']}"
    )


def assert_designation_counts(team: Dict[str, Any], active: int, reserve: int,
                              injured_reserve: int, practice_squad: int) -> None:
    """The four designation counters hold exactly the expected headcounts."""
    observed = (
        team["active_roster_count"],
        team["reserve_roster_count"],
        team["injured_reserve_count"],
        team["practice_squad_count"],
    )
    expected = (active, reserve, injured_reserve, practice_squad)
    assert observed == expected, (
        "designation counts (active, reserve, injured reserve, practice squad) "
        f"should be {expected}, got {observed}"
    )


def assert_cap_position(team: Dict[str, Any], provisional: int, final: int,
                        dead_money: int, cap_space: int) -> None:
    """Both cap variants, the dead money and the cap space hold their values."""
    assert team["provisional_cap_committed_cents"] == provisional, (
        "provisional commitment should be "
        f"{provisional}, got {team['provisional_cap_committed_cents']}"
    )
    assert team["final_cap_committed_cents"] == final, (
        f"final commitment should be {final}, got {team['final_cap_committed_cents']}"
    )
    assert team["dead_money_cents"] == dead_money, (
        f"dead money should be {dead_money}, got {team['dead_money_cents']}"
    )
    assert team["cap_space_cents"] == cap_space, (
        f"cap space should be {cap_space}, got {team['cap_space_cents']}"
    )


def assert_service_profile(player: Dict[str, Any], pension_credit_days: int,
                           roster_service_days: int, service_years: int,
                           contract_rights_class: str,
                           practice_squad_eligible: bool) -> None:
    """The derived service and rights fields hold their expected values."""
    assert player["pension_credit_days"] == pension_credit_days, (
        f"pension credit days should be {pension_credit_days}, "
        f"got {player['pension_credit_days']}"
    )
    assert player["roster_service_days"] == roster_service_days, (
        f"roster service days should be {roster_service_days}, "
        f"got {player['roster_service_days']}"
    )
    assert player["service_years"] == service_years, (
        f"service years should be {service_years}, got {player['service_years']}"
    )
    assert player["contract_rights_class"] == contract_rights_class, (
        f"contract rights class should be {contract_rights_class}, "
        f"got {player['contract_rights_class']}"
    )
    assert player["practice_squad_eligible"] is practice_squad_eligible, (
        f"practice squad eligibility should be {practice_squad_eligible}, "
        f"got {player['practice_squad_eligible']}"
    )


def assert_posture(team: Dict[str, Any], compliance_status: str,
                   consecutive_noncompliant_checks: int,
                   grace_expires_at: Optional[str] = ...) -> None:
    """The posture, its counter and, when asked, the armed grace instant."""
    assert team["compliance_status"] == compliance_status, (
        f"compliance status should be {compliance_status}, "
        f"got {team['compliance_status']}"
    )
    assert team["consecutive_noncompliant_checks"] == consecutive_noncompliant_checks, (
        "consecutive non-compliant checks should be "
        f"{consecutive_noncompliant_checks}, "
        f"got {team['consecutive_noncompliant_checks']}"
    )
    if grace_expires_at is not ...:
        assert team["grace_expires_at"] == grace_expires_at, (
            f"grace expiry should be {grace_expires_at}, "
            f"got {team['grace_expires_at']}"
        )


def assert_violation_codes(check: Dict[str, Any],
                           expected: Sequence[str]) -> None:
    """The sweep row lists exactly these violation codes, in this order."""
    observed = check["violation_codes"]
    assert observed == list(expected), (
        f"violation codes should be {list(expected)} in catalogue order, "
        f"got {observed}"
    )


def assert_pagination_meta(meta: Dict[str, Any], total_count: int,
                           has_more: bool, limit: int, offset: int) -> None:
    """A list response reports all four pagination fields exactly."""
    assert meta["total_count"] == total_count, (
        f"total_count should be {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more should be {has_more}, got {meta['has_more']}"
    )
    assert meta["limit"] == limit, f"limit should be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset should be {offset}, got {meta['offset']}"


def assert_single_resource_meta(response: Any) -> None:
    """A single-resource envelope omits the four pagination fields."""
    meta = response.json()["meta"]
    for field in ("total_count", "has_more", "limit", "offset"):
        assert field not in meta, (
            f"a single-resource response must omit meta.{field}"
        )


def assert_request_envelope(response: Any, response_type: str) -> None:
    """The envelope carries a request id with the declared prefix and a type."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_millisecond_instant(
        meta["api_request_timestamp"], "meta.api_request_timestamp"
    )
    assert body["response_type"] == response_type, (
        f"response_type should be {response_type}, got {body['response_type']}"
    )


def assert_created_at_ascending(items: List[Dict[str, Any]]) -> None:
    """Collection ordering is oldest first by creation instant."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), (
        f"collection must be ordered by created_at ascending, got {stamps}"
    )


def assert_checked_at_descending(items: List[Dict[str, Any]]) -> None:
    """Sweep history is newest first by the instant of the check."""
    stamps = [item["checked_at"] for item in items]
    assert stamps == sorted(stamps, reverse=True), (
        f"sweep history must be ordered by checked_at descending, got {stamps}"
    )


def find_by_id(items: List[Dict[str, Any]], target_id: str) -> Dict[str, Any]:
    """Pull one record out of a collection by id, failing loudly if absent."""
    for item in items:
        if item["id"] == target_id:
            return item
    raise AssertionError(
        f"record {target_id} is absent from the collection of "
        f"{[item['id'] for item in items]}"
    )


def ids_of(items: List[Dict[str, Any]]) -> List[str]:
    """The ids of a collection, in the order the API returned them."""
    return [item["id"] for item in items]
