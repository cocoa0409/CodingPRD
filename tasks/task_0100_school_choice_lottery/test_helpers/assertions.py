"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Primary persisted entities (District, School,
Program, Family, Student, Application, TransferRequest) carry id,
created_at, updated_at, version per PRD §2.4. Audit-and-singleton
entities (LotteryRun, WaitlistEvent, Clock) carry only id and (where
applicable) created_at per PRD §2.4 — assertions on those entities must
NOT demand updated_at or version.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CHOICE_RANK_DECAY,
    LOTTERY_WEIGHT_BASE,
    LOTTERY_WEIGHT_PRECISION_DECIMALS,
    MAX_CHOICE_RANK,
    MAX_GRADE_LEVEL,
    MIN_CHOICE_RANK,
    MIN_GRADE_LEVEL,
    POVERTY_BOOST_PER_DECILE,
    PRIORITY_RANK,
)


# ---------------------------------------------------------------------------
# Generic utilities
# ---------------------------------------------------------------------------
def _assert_uuid(value: Any, label: str) -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_valid_uuid(value), f"{label} must be a valid UUID, got {value!r}"


def _assert_timestamp(value: Any, label: str) -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC, got {value!r}"


def _assert_common_versioned(entity: Dict[str, Any], name: str) -> None:
    """PRD §2.4: primary persisted entities carry id/created_at/
    updated_at/version."""
    _assert_uuid(entity.get("id"), f"{name}.id")
    _assert_timestamp(entity.get("created_at"), f"{name}.created_at")
    _assert_timestamp(entity.get("updated_at"), f"{name}.updated_at")
    assert isinstance(entity.get("version"), int), \
        f"{name}.version must be int, got {type(entity.get('version')).__name__}"
    assert entity["version"] >= 1, f"{name}.version must be >= 1"


# ---------------------------------------------------------------------------
# District (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_district(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "District")
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 120, \
        f"District.name must be 1..120 chars, got {data.get('name')!r}"
    sc = data.get("state_code")
    assert isinstance(sc, str) and len(sc) == 2 and sc.isupper() and sc.isalpha(), \
        f"District.state_code must match ^[A-Z]{{2}}$, got {sc!r}"
    assert isinstance(data.get("accepts_inter_district_transfers"), bool), \
        "District.accepts_inter_district_transfers must be bool"
    thr = data.get("poverty_index_threshold")
    assert isinstance(thr, (int, float)), \
        f"District.poverty_index_threshold must be number, got {type(thr).__name__}"
    assert 0.0 <= float(thr) <= 1.0, \
        f"District.poverty_index_threshold must be in [0, 1], got {thr}"


# ---------------------------------------------------------------------------
# School (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_school(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "School")
    _assert_uuid(data.get("district_id"), "School.district_id")
    assert isinstance(data.get("name"), str) and len(data["name"]) >= 1
    assert data.get("school_type") in ("NEIGHBORHOOD", "MAGNET", "CHARTER"), \
        f"School.school_type unexpected: {data.get('school_type')!r}"
    glo = data.get("grade_levels_offered")
    assert isinstance(glo, list) and len(glo) >= 1, \
        "School.grade_levels_offered must be a non-empty list"
    for g in glo:
        assert isinstance(g, int) and MIN_GRADE_LEVEL <= g <= MAX_GRADE_LEVEL, \
            f"School.grade_levels_offered entry out of range: {g}"
    assert glo == sorted(glo), \
        "School.grade_levels_offered must be sorted ascending per PRD §3.1"


# ---------------------------------------------------------------------------
# Program (PRD §3.1, §3.5)
# ---------------------------------------------------------------------------
def assert_program(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Program")
    _assert_uuid(data.get("school_id"), "Program.school_id")
    gl = data.get("grade_level")
    assert isinstance(gl, int) and MIN_GRADE_LEVEL <= gl <= MAX_GRADE_LEVEL, \
        f"Program.grade_level out of range: {gl!r}"
    ay = data.get("academic_year")
    assert isinstance(ay, int) and ay >= 2025, \
        f"Program.academic_year must be >= 2025, got {ay!r}"
    st = data.get("seats_total")
    assert isinstance(st, int) and st >= 1, \
        f"Program.seats_total must be >= 1, got {st!r}"
    so = data.get("seats_offered")
    assert isinstance(so, int) and so >= 0, \
        f"Program.seats_offered must be a non-negative int, got {so!r}"
    sa = data.get("seats_accepted")
    assert isinstance(sa, int) and sa >= 0, \
        f"Program.seats_accepted must be a non-negative int, got {sa!r}"
    _assert_timestamp(data.get("registration_open_at"), "Program.registration_open_at")
    _assert_timestamp(data.get("registration_close_at"), "Program.registration_close_at")
    assert data["registration_close_at"] > data["registration_open_at"], \
        "Program.registration_close_at must be strictly greater than open_at (PRD §3.1)"
    assert data.get("window_status") in (
        "SCHEDULED", "OPEN", "CLOSED", "LOTTERY_DRAWN", "BACKFILL",
    ), f"Program.window_status unexpected: {data.get('window_status')!r}"
    seed = data.get("lottery_seed")
    if seed is not None:
        assert isinstance(seed, str) and 1 <= len(seed) <= 64, \
            f"Program.lottery_seed must be 1..64 chars, got {seed!r}"


def assert_program_invariants(data: Dict[str, Any]) -> None:
    """Domain invariants on Program (PRD §2.11 / §3.5 / §3.6 / §3.7):
    seats_offered counts {OFFERED, ACCEPTED}; seats_accepted counts
    {ACCEPTED}; both are non-negative and bounded by seats_total."""
    so = data["seats_offered"]
    sa = data["seats_accepted"]
    st = data["seats_total"]
    assert 0 <= sa <= so, \
        f"Program invariant: 0 <= seats_accepted ({sa}) <= seats_offered ({so}) violated"
    assert so <= st, \
        f"Program invariant: seats_offered ({so}) <= seats_total ({st}) violated"


# ---------------------------------------------------------------------------
# Family (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_family(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Family")
    _assert_uuid(data.get("residency_district_id"), "Family.residency_district_id")
    pis = data.get("poverty_index_score")
    assert isinstance(pis, (int, float)) and 0.0 <= float(pis) <= 1.0, \
        f"Family.poverty_index_score must be in [0, 1], got {pis!r}"
    anchor = data.get("head_household_application_id", None)
    if anchor is not None:
        _assert_uuid(anchor, "Family.head_household_application_id")


# ---------------------------------------------------------------------------
# Student (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_student(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Student")
    _assert_uuid(data.get("family_id"), "Student.family_id")
    gln = data.get("grade_level_next_year")
    assert isinstance(gln, int) and MIN_GRADE_LEVEL <= gln <= MAX_GRADE_LEVEL, \
        f"Student.grade_level_next_year out of range: {gln!r}"
    assert isinstance(data.get("has_iep"), bool), \
        f"Student.has_iep must be bool, got {data.get('has_iep')!r}"


# ---------------------------------------------------------------------------
# Application (PRD §3.4, §3.5, §3.6)
# ---------------------------------------------------------------------------
def assert_application(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Application")
    _assert_uuid(data.get("student_id"), "Application.student_id")
    _assert_uuid(data.get("program_id"), "Application.program_id")
    cr = data.get("choice_rank")
    assert isinstance(cr, int) and MIN_CHOICE_RANK <= cr <= MAX_CHOICE_RANK, \
        f"Application.choice_rank must be 1..5, got {cr!r}"
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "OFFERED", "ACCEPTED", "DECLINED",
        "WAITLISTED", "EXPIRED", "WITHDRAWN",
    ), f"Application.status unexpected: {data.get('status')!r}"
    pc = data.get("priority_category", None)
    if pc is not None:
        assert pc in PRIORITY_RANK, \
            f"Application.priority_category unexpected: {pc!r}"
    lw = data.get("lottery_weight", None)
    if lw is not None:
        assert isinstance(lw, (int, float)) and lw >= 0
    ls = data.get("lottery_score", None)
    if ls is not None:
        assert isinstance(ls, (int, float)) and ls >= 0
    wp = data.get("waitlist_position", None)
    if wp is not None:
        assert isinstance(wp, int) and wp >= 1, \
            f"Application.waitlist_position is 1-based per PRD §3.5, got {wp!r}"
    oea = data.get("offer_expires_at", None)
    if oea is not None:
        _assert_timestamp(oea, "Application.offer_expires_at")


# ---------------------------------------------------------------------------
# TransferRequest (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_transfer_request(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "TransferRequest")
    _assert_uuid(data.get("application_id"), "TransferRequest.application_id")
    _assert_uuid(data.get("target_district_id"), "TransferRequest.target_district_id")
    assert data.get("status") in ("PENDING", "APPROVED", "DENIED", "REVOKED"), \
        f"TransferRequest.status unexpected: {data.get('status')!r}"
    cuh = data.get("capacity_units_held")
    assert isinstance(cuh, int) and cuh in (0, 1), \
        f"TransferRequest.capacity_units_held must be 0 or 1, got {cuh!r}"
    # PRD §3.3: capacity_units_held is 1 iff status == APPROVED.
    if data["status"] == "APPROVED":
        assert cuh == 1, \
            "TransferRequest.capacity_units_held must be 1 in APPROVED (PRD §3.3)"
    else:
        assert cuh == 0, \
            "TransferRequest.capacity_units_held must be 0 outside APPROVED (PRD §3.3)"


# ---------------------------------------------------------------------------
# LotteryRun, WaitlistEvent, Clock — audit / singleton entities
# (PRD §2.4) — no updated_at / version
# ---------------------------------------------------------------------------
def assert_lottery_run(data: Dict[str, Any]) -> None:
    _assert_uuid(data.get("id"), "LotteryRun.id")
    _assert_uuid(data.get("program_id"), "LotteryRun.program_id")
    assert isinstance(data.get("seed_used"), str) and len(data["seed_used"]) > 0
    _assert_timestamp(data.get("drawn_at"), "LotteryRun.drawn_at")
    ar = data.get("applications_ranked")
    assert isinstance(ar, list), \
        "LotteryRun.applications_ranked must be a list (PRD §3.5)"
    for item in ar:
        assert isinstance(item, dict)
        _assert_uuid(item.get("application_id"), "applications_ranked[].application_id")
        assert isinstance(item.get("lottery_score"), (int, float))
        assert isinstance(item.get("rank"), int) and item["rank"] >= 1
    # rank 1 is highest score per PRD §3.5
    ranks = [r["rank"] for r in ar]
    assert ranks == list(range(1, len(ar) + 1)), \
        "applications_ranked ranks must be 1..N (PRD §3.5)"
    oic = data.get("offers_issued_count")
    assert isinstance(oic, int) and oic >= 0, \
        f"LotteryRun.offers_issued_count must be a non-negative int, got {oic!r}"
    # PRD §2.4: LotteryRun is immutable — must NOT carry updated_at/version
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "LotteryRun must not carry updated_at (PRD §2.4 audit entity)"
    assert "version" not in data or data.get("version") is None, \
        "LotteryRun must not carry version (PRD §2.4 audit entity)"


def assert_waitlist_event(data: Dict[str, Any]) -> None:
    _assert_uuid(data.get("id"), "WaitlistEvent.id")
    _assert_uuid(data.get("program_id"), "WaitlistEvent.program_id")
    _assert_uuid(
        data.get("triggered_by_application_id"),
        "WaitlistEvent.triggered_by_application_id",
    )
    promoted = data.get("promoted_application_id")
    if promoted is not None:
        _assert_uuid(promoted, "WaitlistEvent.promoted_application_id")
    _assert_timestamp(data.get("occurred_at"), "WaitlistEvent.occurred_at")
    # PRD §2.4: WaitlistEvent immutable — must NOT carry updated_at/version
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "WaitlistEvent must not carry updated_at (PRD §2.4 audit entity)"
    assert "version" not in data or data.get("version") is None, \
        "WaitlistEvent must not carry version (PRD §2.4 audit entity)"


def assert_clock(data: Dict[str, Any]) -> None:
    assert data.get("id") == "clock", \
        f"Clock singleton id must be the literal 'clock' (PRD §2.10), got {data.get('id')!r}"
    _assert_timestamp(data.get("now"), "Clock.now")
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "Clock must not carry updated_at (PRD §2.4 singleton)"
    assert "version" not in data or data.get("version") is None, \
        "Clock must not carry version (PRD §2.4 singleton)"


# ---------------------------------------------------------------------------
# Calculation reference: lottery_weight (PRD §3.4)
# ---------------------------------------------------------------------------
def expected_lottery_weight(
    priority_category: str,
    poverty_index_score: float,
    poverty_index_threshold: float,
    choice_rank: int,
) -> float:
    """Compute expected lottery_weight per PRD §3.4 with the integer
    scaling rule from PRD §2.7 and ROUND_HALF_UP to 4 decimals.

    Returns the persisted value (post-rounding) for direct ==
    comparison against the server's stored value.
    """
    base = LOTTERY_WEIGHT_BASE[priority_category]
    pi_int = int(round(poverty_index_score * 100))
    thr_int = int(round(poverty_index_threshold * 100))
    if pi_int > thr_int:
        deciles = (pi_int - thr_int) // 10
        multiplier = 1.0 + POVERTY_BOOST_PER_DECILE * deciles
    else:
        multiplier = 1.0
    decay = CHOICE_RANK_DECAY ** (choice_rank - 1)
    raw = base * multiplier * decay
    # ROUND_HALF_UP to 4 decimal places via Decimal-equivalent.
    from decimal import ROUND_HALF_UP, Decimal
    quantized = Decimal(repr(raw)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP,
    )
    return float(quantized)


def assert_lottery_weight_matches_prd(
    app: Dict[str, Any],
    poverty_index_score: float,
    poverty_index_threshold: float,
) -> None:
    """Assert app['lottery_weight'] == PRD-derived value (PRD §3.4)."""
    expected = expected_lottery_weight(
        app["priority_category"],
        poverty_index_score,
        poverty_index_threshold,
        app["choice_rank"],
    )
    actual = app.get("lottery_weight")
    assert actual is not None, \
        "Application.lottery_weight must be set at SUBMITTED (PRD §3.4)"
    assert math.isclose(float(actual), expected, abs_tol=1e-9), (
        f"lottery_weight mismatch: expected {expected!r} per PRD §3.4, got {actual!r} "
        f"(category={app['priority_category']}, pis={poverty_index_score}, "
        f"thr={poverty_index_threshold}, rank={app['choice_rank']})"
    )


# ---------------------------------------------------------------------------
# Lottery ordering reference (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_lottery_ordering(applications_ranked: List[Dict[str, Any]],
                            apps_by_id: Dict[str, Dict[str, Any]]) -> None:
    """Verify applications_ranked obeys PRD §3.5 sort keys:
    (priority_category rank ASC, lottery_score DESC, created_at ASC,
    application.id ASC). apps_by_id maps application.id ->
    full Application dict (post-draw)."""
    last_key = None
    for entry in applications_ranked:
        app = apps_by_id[entry["application_id"]]
        key = (
            PRIORITY_RANK[app["priority_category"]],
            -float(entry["lottery_score"]),
            app["created_at"],
            app["id"],
        )
        if last_key is not None:
            assert key >= last_key, (
                f"applications_ranked violates PRD §3.5 ordering at rank {entry['rank']}"
            )
        last_key = key


# ---------------------------------------------------------------------------
# Convenience: find / filter helpers
# ---------------------------------------------------------------------------
def find_by_id(rows: Iterable[Dict[str, Any]], _id: str) -> Optional[Dict[str, Any]]:
    for r in rows:
        if r.get("id") == _id:
            return r
    return None


__all__ = [
    "assert_district",
    "assert_school",
    "assert_program",
    "assert_program_invariants",
    "assert_family",
    "assert_student",
    "assert_application",
    "assert_transfer_request",
    "assert_lottery_run",
    "assert_waitlist_event",
    "assert_clock",
    "expected_lottery_weight",
    "assert_lottery_weight_matches_prd",
    "assert_lottery_ordering",
    "find_by_id",
]
