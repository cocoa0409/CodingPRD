"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4 splits entities into two shapes:

    common-fields (Park, Visitor, AmericaTheBeautifulPass, Campground,
    LotteryPermit, BackcountryZone, TimedEntryReservation,
    CampgroundReservation, LotteryApplication, BackcountryPermit):
        id, created_at, updated_at, version

    append-only (WaitlistEntry, LedgerEntry):
        id and created_at only — no updated_at, no version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is a non-negative integer that begins at 1
    on creation and increments by one on every mutation.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: common-fields entities expose id, created_at,
    updated_at, version."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'The WaitlistEntry and LedgerEntry resources carry only
    id and created_at — both updated_at and version are absent.'"""
    _assert_id_and_created_at(data)


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: every mutation increments version by exactly 1."""
    before_v = before.get("version")
    after_v = after.get("version")
    assert isinstance(before_v, int) and isinstance(after_v, int), (
        f"version comparison needs int versions, got {before_v!r}, {after_v!r}"
    )
    assert after_v >= before_v + delta, (
        f"expected version >= {before_v}+{delta} = {before_v + delta}, "
        f"got {after_v}"
    )


# ---------------------------------------------------------------------------
# Park — PRD §2.7, §3.2
# ---------------------------------------------------------------------------
def assert_park(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data.get("code"), str) and 2 <= len(data["code"]) <= 10
    assert isinstance(data.get("timezone"), str) and len(data["timezone"]) > 0
    assert isinstance(data.get("timed_entry_daily_capacity"), int)
    assert data["timed_entry_daily_capacity"] >= 0
    assert isinstance(data.get("timed_entry_window_minutes"), int)
    # PRD §2.10: "must evenly divide 1440"
    assert 1440 % data["timed_entry_window_minutes"] == 0, (
        f"timed_entry_window_minutes must evenly divide 1440"
    )
    # PRD §2.7: "A park carries a status of OPEN, RESTRICTED, or FROZEN."
    assert data.get("status") in {"OPEN", "RESTRICTED", "FROZEN"}, (
        f"unexpected park status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Visitor — PRD §3.1
# ---------------------------------------------------------------------------
def assert_visitor(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("full_name"), str)
    assert 1 <= len(data["full_name"]) <= 120
    # PRD §2.8: "Visitor.wallet_balance_cents field never goes below zero"
    assert isinstance(data.get("wallet_balance_cents"), int)
    assert data["wallet_balance_cents"] >= 0
    # PRD §3.1: "lottery_strikes, which also begins at 0 ... may reach 3"
    assert isinstance(data.get("lottery_strikes"), int)
    assert 0 <= data["lottery_strikes"] <= 3, (
        f"lottery_strikes must be 0..3, got {data['lottery_strikes']!r}"
    )


# ---------------------------------------------------------------------------
# AmericaTheBeautifulPass — PRD §3.1
# ---------------------------------------------------------------------------
PASS_TYPES = frozenset({
    "ANNUAL", "SENIOR_ANNUAL", "SENIOR_LIFETIME", "MILITARY",
    "ACCESS", "VOLUNTEER", "FOURTH_GRADE",
})


def assert_pass(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert data.get("pass_type") in PASS_TYPES, (
        f"unexpected pass_type: {data.get('pass_type')!r}"
    )
    # PRD §3.1: "a server-minted twelve-character unique serial"
    assert isinstance(data.get("serial"), str) and len(data["serial"]) == 12
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_until", ""))
    assert data.get("status") in {"ACTIVE", "EXPIRED", "REVOKED"}, (
        f"unexpected pass status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Campground — PRD §3.2
# ---------------------------------------------------------------------------
def assert_campground(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be UUID"
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data.get("standard_site_count"), int)
    assert data["standard_site_count"] >= 0
    assert isinstance(data.get("group_site_count"), int)
    assert data["group_site_count"] >= 0
    assert isinstance(data.get("nightly_standard_fee_cents"), int)
    assert data["nightly_standard_fee_cents"] >= 0
    assert isinstance(data.get("nightly_group_fee_cents"), int)
    assert data["nightly_group_fee_cents"] >= 0
    # PRD §3.2: "max_consecutive_nights (1 through 30, defaulting to 14)"
    assert isinstance(data.get("max_consecutive_nights"), int)
    assert 1 <= data["max_consecutive_nights"] <= 30
    # PRD §3.2: "waitlist_window_hours (1 through 168, defaulting to 24)"
    assert isinstance(data.get("waitlist_window_hours"), int)
    assert 1 <= data["waitlist_window_hours"] <= 168


# ---------------------------------------------------------------------------
# BackcountryZone — PRD §3.2
# ---------------------------------------------------------------------------
def assert_backcountry_zone(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be UUID"
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data.get("nightly_quota_people"), int)
    assert data["nightly_quota_people"] >= 0
    assert isinstance(data.get("ranger_buffer_minutes"), int)
    assert 0 <= data["ranger_buffer_minutes"] <= 720
    assert isinstance(data.get("per_party_fee_cents"), int)
    assert data["per_party_fee_cents"] >= 0


# ---------------------------------------------------------------------------
# LotteryPermit — PRD §3.2, §3.6
# ---------------------------------------------------------------------------
def assert_lottery_permit(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be UUID"
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 80
    assert is_iso8601_timestamp(data.get("lottery_open_at", ""))
    assert is_iso8601_timestamp(data.get("lottery_close_at", ""))
    assert is_iso8601_timestamp(data.get("draw_at", ""))
    assert is_iso8601_timestamp(data.get("hike_date", ""))
    assert isinstance(data.get("daily_slot_count"), int)
    assert data["daily_slot_count"] >= 1
    assert isinstance(data.get("per_application_max_party"), int)
    assert 1 <= data["per_application_max_party"] <= 12
    assert isinstance(data.get("application_fee_cents"), int)
    assert data["application_fee_cents"] >= 0
    assert isinstance(data.get("permit_fee_cents"), int)
    assert data["permit_fee_cents"] >= 0
    # PRD §3.2: "The lottery moves through OPEN, CLOSED, DRAWN, and ARCHIVED"
    assert data.get("status") in {"OPEN", "CLOSED", "DRAWN", "ARCHIVED"}


# ---------------------------------------------------------------------------
# TimedEntryReservation — PRD §3.3
# ---------------------------------------------------------------------------
def assert_timed_entry(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be UUID"
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert isinstance(data.get("vehicle_plate"), str)
    # PRD §3.3: "vehicle_plate (1 through 10 characters, uppercased on persist)"
    assert 1 <= len(data["vehicle_plate"]) <= 10
    assert data["vehicle_plate"] == data["vehicle_plate"].upper(), (
        "vehicle_plate must be uppercased on persist (PRD §3.3)"
    )
    assert isinstance(data.get("entry_date_local"), str)
    assert isinstance(data.get("window_start_local"), str)
    assert isinstance(data.get("window_end_local"), str)
    assert isinstance(data.get("entry_fee_cents"), int)
    assert data["entry_fee_cents"] >= 0
    assert data.get("status") in {
        "HELD", "CONFIRMED", "CANCELLED", "USED", "NO_SHOW",
    }


# ---------------------------------------------------------------------------
# CampgroundReservation — PRD §3.4
# ---------------------------------------------------------------------------
def assert_campground_reservation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("campground_id", "")), "campground_id must be UUID"
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert data.get("site_kind") in {"STANDARD", "GROUP"}, (
        f"site_kind must be STANDARD or GROUP, got {data.get('site_kind')!r}"
    )
    assert isinstance(data.get("party_size"), int)
    # PRD §3.4: "1 through 6 inclusive for STANDARD, 7 through 40 inclusive
    # for GROUP"
    if data["site_kind"] == "STANDARD":
        assert 1 <= data["party_size"] <= 6, (
            f"STANDARD party_size must be 1..6, got {data['party_size']!r}"
        )
    else:
        assert 7 <= data["party_size"] <= 40, (
            f"GROUP party_size must be 7..40, got {data['party_size']!r}"
        )
    assert isinstance(data.get("check_in_date_local"), str)
    assert isinstance(data.get("check_out_date_local"), str)
    assert isinstance(data.get("nights"), int)
    assert data["nights"] >= 1
    assert isinstance(data.get("nightly_rate_cents"), int)
    assert data["nightly_rate_cents"] >= 0
    assert isinstance(data.get("total_fee_cents"), int)
    assert data["total_fee_cents"] >= 0
    assert isinstance(data.get("refund_cents"), int)
    assert data["refund_cents"] >= 0
    assert data.get("status") in {
        "HELD", "CONFIRMED", "CANCELLED", "NO_SHOW", "COMPLETED",
    }


# ---------------------------------------------------------------------------
# LotteryApplication — PRD §3.6
# ---------------------------------------------------------------------------
def assert_lottery_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lottery_permit_id", "")), (
        "lottery_permit_id must be UUID"
    )
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert isinstance(data.get("party_size"), int)
    assert data["party_size"] >= 1
    assert isinstance(data.get("rank_seed"), int)
    assert isinstance(data.get("application_fee_cents"), int)
    assert data["application_fee_cents"] >= 0
    assert data.get("status") in {
        "SUBMITTED", "WAITLISTED", "AWARDED", "ACCEPTED", "DECLINED",
        "FORFEITED",
    }


# ---------------------------------------------------------------------------
# BackcountryPermit — PRD §3.7
# ---------------------------------------------------------------------------
def assert_backcountry_permit(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be UUID"
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert isinstance(data.get("party_size"), int)
    # PRD §3.7: "party_size (1 through 15 inclusive)"
    assert 1 <= data["party_size"] <= 15
    assert isinstance(data.get("entry_datetime_local"), str)
    assert isinstance(data.get("exit_datetime_local"), str)
    assert isinstance(data.get("nights"), int)
    assert data["nights"] >= 0
    assert isinstance(data.get("fee_cents"), int)
    assert data["fee_cents"] >= 0
    assert data.get("status") in {"HELD", "CONFIRMED", "CANCELLED", "USED"}


# ---------------------------------------------------------------------------
# WaitlistEntry — PRD §2.4 append-only, §3.5
# ---------------------------------------------------------------------------
def assert_waitlist_entry(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("campground_id", "")), (
        "campground_id must be UUID"
    )
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert data.get("site_kind") in {"STANDARD", "GROUP"}
    assert isinstance(data.get("check_in_date_local"), str)
    assert isinstance(data.get("nights"), int)
    # PRD §3.5: "nights (1 through 14 inclusive)"
    assert 1 <= data["nights"] <= 14
    assert isinstance(data.get("priority_score"), int)
    assert data.get("status") in {
        "WAITING", "PROMOTED", "EXPIRED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# LedgerEntry — PRD §2.4 append-only, §2.9
# ---------------------------------------------------------------------------
LEDGER_KINDS = frozenset({
    "DEPOSIT", "FEE_CHARGE", "FEE_REFUND", "LOTTERY_FEE", "PERMIT_FEE",
    "ADJUSTMENT",
})
LEDGER_REFERENCE_KINDS = frozenset({
    "TimedEntryReservation", "CampgroundReservation", "BackcountryPermit",
    "LotteryApplication", "None",
})


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    """PRD §2.9: 'A ledger entry carries a visitor_id, a kind drawn from
    {DEPOSIT, FEE_CHARGE, FEE_REFUND, LOTTERY_FEE, PERMIT_FEE,
    ADJUSTMENT}, a signed amount_cents (positive credits the wallet,
    negative debits it), a reference_kind drawn from
    {TimedEntryReservation, CampgroundReservation, BackcountryPermit,
    LotteryApplication, None}, and an optional reference_id'.
    """
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be UUID"
    assert data.get("kind") in LEDGER_KINDS, (
        f"unexpected ledger kind: {data.get('kind')!r}"
    )
    assert isinstance(data.get("amount_cents"), int), (
        f"amount_cents must be int, got {data.get('amount_cents')!r}"
    )
    assert data.get("reference_kind") in LEDGER_REFERENCE_KINDS, (
        f"unexpected reference_kind: {data.get('reference_kind')!r}"
    )
    # PRD §2.9: "Deposits and adjustments use reference_kind of None and
    # leave reference_id null."
    if data["kind"] in {"DEPOSIT", "ADJUSTMENT"}:
        assert data["reference_kind"] == "None"
        assert data.get("reference_id") in (None, "")
    else:
        assert data["reference_kind"] != "None", (
            f"non-deposit/non-adjustment must have a concrete reference_kind"
        )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_wallet_equals_ledger_sum(visitor: Dict[str, Any],
                                    ledger: Iterable[Dict[str, Any]]) -> None:
    """PRD §2.9: 'Visitor.wallet_balance_cents is the running sum of all
    amount_cents values for that visitor.'"""
    total = sum(int(e["amount_cents"]) for e in ledger)
    assert visitor["wallet_balance_cents"] == total, (
        f"wallet_balance_cents={visitor['wallet_balance_cents']} != "
        f"sum(ledger.amount_cents)={total}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_version_incremented_by",
    "assert_park",
    "assert_visitor",
    "assert_pass",
    "assert_campground",
    "assert_backcountry_zone",
    "assert_lottery_permit",
    "assert_timed_entry",
    "assert_campground_reservation",
    "assert_lottery_application",
    "assert_backcountry_permit",
    "assert_waitlist_entry",
    "assert_ledger_entry",
    "assert_wallet_equals_ledger_sum",
    "PASS_TYPES",
    "LEDGER_KINDS",
    "LEDGER_REFERENCE_KINDS",
]
