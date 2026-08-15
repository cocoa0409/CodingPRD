"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["affiliation"] in ("STUDENT", "FACULTY", "COMMUNITY")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["outstanding_fines_cents"] >= 0, (
        "outstanding fines never go negative (PRD §3.1)"
    )
    assert data["no_show_count"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert data["term"] in ("FALL_2026", "SPRING_2027", "SUMMER_2027")
    assert data["pricing_variant"] in ("FULL", "PRORATED")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "CANCELLED", "EXPIRED")


def assert_league(data: dict):
    _assert_common(data)
    assert data["sport"] in (
        "BASKETBALL", "SOCCER", "VOLLEYBALL", "FLAG_FOOTBALL", "DODGEBALL",
    )
    assert data["status"] in (
        "DRAFT", "REGISTRATION_OPEN", "SCHEDULING", "IN_SEASON",
        "PLAYOFFS", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["divisions"], list)
    assert isinstance(data["free_agent_pool"], list)


def assert_team(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REGISTERED", "PLACED", "ACTIVE", "SUSPENDED", "WITHDRAWN",
        "COMPLETED",
    )
    assert data["points"] == (
        data["wins"] * 3 + data["ties"] * 1 + data["losses"] * 0
    ), "standings points must equal win*3 + tie*1 (PRD §3.4)"
    for counter in (
        "wins", "losses", "ties", "forfeit_count",
        "sportsmanship_points_total", "sportsmanship_rating_count",
        "active_roster_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_roster_entry(data: dict):
    _assert_common(data)
    assert data["role"] in ("CAPTAIN", "PLAYER")
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_facility(data: dict):
    _assert_common(data)
    assert data["kind"] in ("COURT", "FIELD", "ROOM", "POOL")
    assert isinstance(data["operating_windows"], list)
    assert isinstance(data["closures"], list)


def assert_game(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "RESCHEDULE_REQUIRED", "PLAYED_PENDING_CONFIRM",
        "DISPUTED", "FINAL", "FORFEITED", "CANCELLED",
    )
    assert data["bracket_round"] in ("REGULAR", "SEMIFINAL", "CHAMPIONSHIP")


def assert_staff(data: dict):
    _assert_common(data)
    assert data["staff_role"] in ("OFFICIAL", "INSTRUCTOR")
    assert data["base_hourly_rate_cents"] > 0
    assert data["payroll_pending_cents"] >= 0
    assert data["payroll_paid_cents"] >= 0


def assert_officiating_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "ASSIGNED", "ACCEPTED", "DECLINED", "WORKED", "CANCELLED", "PAID",
    )
    assert isinstance(data["provisional_pay_cents"], int)


def assert_injury_report(data: dict):
    _assert_common(data)
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert data["status"] in ("REPORTED", "CLEARED")


def assert_equipment_pool(data: dict):
    _assert_common(data)
    assert data["total_qty"] >= 0
    assert data["available_qty"] >= 0


def assert_pool_invariants(pool: dict, out_quantity: int):
    """PRD §3.9: available_qty + sum(OUT quantity) == total_qty."""
    assert pool["available_qty"] + out_quantity == pool["total_qty"], (
        f"pool unit conservation violated: {pool['available_qty']} + "
        f"{out_quantity} != {pool['total_qty']}"
    )


def assert_equipment_checkout(data: dict):
    _assert_common(data)
    assert data["status"] in ("OUT", "RETURNED", "LOST")
    assert data["quantity"] >= 1


def assert_locker(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "RENTED")
    assert data["locker_number"] >= 1
    assert data["size"] in ("S", "M", "L")


def assert_fitness_class(data: dict):
    _assert_common(data)
    assert data["class_type"] in ("YOGA", "SPIN", "PILATES", "HIIT", "ZUMBA")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["capacity"] >= 1
    assert data["registered_count"] >= 0
    assert data["waitlist_count"] >= 0


def assert_class_registration(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REGISTERED", "WAITLISTED", "CANCELLED", "ATTENDED", "NO_SHOW",
    )
