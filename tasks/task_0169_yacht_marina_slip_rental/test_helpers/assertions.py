"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3 /
§2.4 for that entity. Common-fields entities carry id + created_at +
updated_at + version. The three append-only entities (`WaitlistEntry`,
`UtilityReading`, `TowEvent`) carry only id + created_at — PRD §2.4:
"The `WaitlistEntry`, `UtilityReading`, and `TowEvent` records, however,
are immutable append-only artifacts: they carry only `id` and
`created_at`, and they have neither an `updated_at` nor a `version`
field."
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: every common-fields resource carries id, created_at,
    updated_at, version (integer starting at 1, incremented on each
    modification)."""
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: WaitlistEntry, UtilityReading, and TowEvent carry only
    id and created_at; neither updated_at nor version may be present."""
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.4: "`version` is an integer that starts at 1 on creation
    and increments by one on every mutation that changes the
    resource."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Marina — PRD §3.1
# ---------------------------------------------------------------------------
def assert_marina(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"], (
        "name must be non-empty string"
    )
    assert isinstance(data.get("timezone"), str), (
        f"timezone must be string, got {data.get('timezone')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("current_date", ""))), (
        f"current_date must be ISO 8601, got {data.get('current_date')!r}"
    )
    ori = data.get("ops_run_index")
    assert isinstance(ori, int) and ori >= 0, (
        f"ops_run_index must be non-negative int, got {ori!r}"
    )
    bdr = data.get("base_daily_rate_cents")
    assert isinstance(bdr, int) and bdr >= 0, (
        f"base_daily_rate_cents must be non-negative int, got {bdr!r}"
    )
    quota = data.get("liveaboard_quota")
    assert isinstance(quota, int) and quota >= 0, (
        f"liveaboard_quota must be non-negative int, got {quota!r}"
    )
    lac = data.get("liveaboard_active_count")
    assert isinstance(lac, int) and lac >= 0, (
        f"liveaboard_active_count must be non-negative int, got {lac!r}"
    )


# ---------------------------------------------------------------------------
# Boater — PRD §3.2
# ---------------------------------------------------------------------------
def assert_boater(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"], (
        "name must be non-empty string"
    )
    db = data.get("deposit_balance_cents")
    assert isinstance(db, int) and db >= 0, (
        f"deposit_balance_cents must be non-negative int, got {db!r}"
    )
    assert data.get("status") == "ACTIVE", (
        f"Boater.status must be ACTIVE, got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Vessel — PRD §3.2
# ---------------------------------------------------------------------------
def assert_vessel(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("boater_id"), str)
    assert isinstance(data.get("name"), str) and data["name"]
    loa = data.get("loa_feet")
    assert isinstance(loa, (int, float)) and loa > 0, (
        f"loa_feet must be > 0, got {loa!r}"
    )
    beam = data.get("beam_feet")
    assert isinstance(beam, (int, float)) and beam > 0, (
        f"beam_feet must be > 0, got {beam!r}"
    )
    draft = data.get("draft_feet")
    assert isinstance(draft, (int, float)) and draft > 0, (
        f"draft_feet must be > 0, got {draft!r}"
    )
    # holding_tank_gallons is optional per PRD §3.2.
    htg = data.get("holding_tank_gallons", None)
    assert htg is None or (isinstance(htg, int) and htg >= 0), (
        f"holding_tank_gallons must be non-negative int or null, "
        f"got {htg!r}"
    )


# ---------------------------------------------------------------------------
# Slip — PRD §3.3
# ---------------------------------------------------------------------------
def assert_slip(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("code"), str) and data["code"]
    for field in ("length_feet", "beam_feet", "depth_feet"):
        v = data.get(field)
        assert isinstance(v, (int, float)) and v > 0, (
            f"{field} must be > 0, got {v!r}"
        )
    flat = data.get("flat_daily_charge_cents")
    assert isinstance(flat, int) and flat >= 0, (
        f"flat_daily_charge_cents must be non-negative int, got {flat!r}"
    )
    la = data.get("liveaboard_allowed")
    assert isinstance(la, bool), (
        f"liveaboard_allowed must be bool, got {la!r}"
    )
    assert data.get("status") in {"AVAILABLE", "MAINTENANCE", "RETIRED"}, (
        f"Slip.status invalid: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Reservation — PRD §3.4
# ---------------------------------------------------------------------------
def assert_reservation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("boater_id"), str)
    assert isinstance(data.get("vessel_id"), str)
    assert isinstance(data.get("slip_id"), str)
    for field in ("check_in_date", "check_out_date"):
        v = data.get(field, "")
        assert is_iso8601_timestamp(str(v)), (
            f"{field} must be ISO 8601, got {v!r}"
        )
    assert isinstance(data.get("liveaboard"), bool), (
        f"liveaboard must be bool, got {data.get('liveaboard')!r}"
    )
    assert isinstance(data.get("insurance_policy_id"), str)
    assert data.get("status") in {
        "DRAFT", "APPROVED", "CHECKED_IN", "CHECKED_OUT",
        "CANCELLED", "EXPIRED",
    }, f"Reservation.status invalid: {data.get('status')!r}"
    # estimated_total_cents is set at APPROVE; null while DRAFT.
    et = data.get("estimated_total_cents", None)
    assert et is None or (isinstance(et, int) and et >= 0), (
        f"estimated_total_cents must be non-negative int or null, "
        f"got {et!r}"
    )
    # final_total_cents is set at CHECK_OUT; null otherwise.
    ft = data.get("final_total_cents", None)
    assert ft is None or (isinstance(ft, int) and ft >= 0), (
        f"final_total_cents must be non-negative int or null, "
        f"got {ft!r}"
    )
    n = data.get("nights")
    assert isinstance(n, int) and n > 0, (
        f"nights must be positive int (PRD §2.9: check_out must be "
        f"strictly after check_in), got {n!r}"
    )


# ---------------------------------------------------------------------------
# WaitlistEntry — PRD §3.7 (append-only)
# ---------------------------------------------------------------------------
def assert_waitlist_entry(data: Dict[str, Any]) -> None:
    """PRD §3.7: WaitlistEntry "carries only `id` and `created_at` from
    the common-fields set — no `updated_at` and no `version`"."""
    assert_append_only_fields(data)
    assert isinstance(data.get("boater_id"), str)
    assert isinstance(data.get("vessel_id"), str)
    for field in ("requested_check_in", "requested_check_out"):
        v = data.get(field, "")
        assert is_iso8601_timestamp(str(v)), (
            f"{field} must be ISO 8601, got {v!r}"
        )
    assert isinstance(data.get("liveaboard"), bool)
    seq = data.get("sequence_no")
    assert isinstance(seq, int) and seq >= 0, (
        f"sequence_no must be non-negative int, got {seq!r}"
    )
    assert data.get("status") in {
        "QUEUED", "PROMOTED", "CANCELLED", "EXPIRED",
    }, f"WaitlistEntry.status invalid: {data.get('status')!r}"
    pr = data.get("promoted_reservation_id", None)
    assert pr is None or isinstance(pr, str), (
        f"promoted_reservation_id must be string or null, got {pr!r}"
    )


# ---------------------------------------------------------------------------
# SlipTransferRequest — PRD §3.7
# ---------------------------------------------------------------------------
def assert_slip_transfer_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("reservation_id"), str)
    assert isinstance(data.get("desired_slip_id"), str)
    assert data.get("status") in {
        "REQUESTED", "OFFERED", "DECLINED", "ACCEPTED", "EXPIRED",
    }, f"SlipTransferRequest.status invalid: {data.get('status')!r}"
    # offer_expires_at is null until OFFERED.
    oe = data.get("offer_expires_at", None)
    assert oe is None or is_iso8601_timestamp(str(oe)), (
        f"offer_expires_at must be ISO 8601 or null, got {oe!r}"
    )


# ---------------------------------------------------------------------------
# PumpOutJob — PRD §3.8
# ---------------------------------------------------------------------------
def assert_pump_out_job(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("reservation_id"), str)
    for field in ("scheduled_start", "scheduled_end"):
        v = data.get(field, "")
        assert is_iso8601_timestamp(str(v)), (
            f"{field} must be ISO 8601, got {v!r}"
        )
    assert data.get("status") in {"SCHEDULED", "COMPLETED", "CANCELLED"}, (
        f"PumpOutJob.status invalid: {data.get('status')!r}"
    )
    # tank_gallons_drained is null while SCHEDULED.
    t = data.get("tank_gallons_drained", None)
    assert t is None or (isinstance(t, int) and t >= 0), (
        f"tank_gallons_drained must be non-negative int or null, "
        f"got {t!r}"
    )


# ---------------------------------------------------------------------------
# UtilityReading — PRD §3.6 (append-only)
# ---------------------------------------------------------------------------
def assert_utility_reading(data: Dict[str, Any]) -> None:
    """PRD §3.6: utility readings are "immutable once written"; PRD §2.4
    lists UtilityReading among the append-only entities."""
    assert_append_only_fields(data)
    assert isinstance(data.get("reservation_id"), str)
    assert is_iso8601_timestamp(str(data.get("read_at", "")))
    kw = data.get("kwh_delta")
    assert isinstance(kw, int) and kw >= 0, (
        f"kwh_delta must be non-negative int, got {kw!r}"
    )
    wg = data.get("water_gallons_delta")
    assert isinstance(wg, int) and wg >= 0, (
        f"water_gallons_delta must be non-negative int, got {wg!r}"
    )
    ais = data.get("applied_in_settlement")
    assert isinstance(ais, bool), (
        f"applied_in_settlement must be bool, got {ais!r}"
    )


# ---------------------------------------------------------------------------
# UtilitySettlement — PRD §3.6
# ---------------------------------------------------------------------------
def assert_utility_settlement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("reservation_id"), str)
    for field in ("window_start", "window_end"):
        v = data.get(field, "")
        assert is_iso8601_timestamp(str(v)), (
            f"{field} must be ISO 8601, got {v!r}"
        )
    for field in ("kwh_total", "water_gallons_total",
                  "sewage_charge_cents", "total_cents"):
        v = data.get(field)
        assert isinstance(v, int) and v >= 0, (
            f"{field} must be non-negative int, got {v!r}"
        )


# ---------------------------------------------------------------------------
# InsurancePolicy — PRD §3.2
# ---------------------------------------------------------------------------
def assert_insurance_policy(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("boater_id"), str)
    assert isinstance(data.get("carrier"), str) and data["carrier"]
    ll = data.get("liability_limit_cents")
    assert isinstance(ll, int) and ll >= 0, (
        f"liability_limit_cents must be non-negative int, got {ll!r}"
    )
    for field in ("effective_date", "expiration_date"):
        v = data.get(field, "")
        assert is_iso8601_timestamp(str(v)), (
            f"{field} must be ISO 8601, got {v!r}"
        )
    assert data.get("status") in {"ACTIVE", "EXPIRED", "CANCELLED"}, (
        f"InsurancePolicy.status invalid: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# TowAssistContract — PRD §3.2 / §3.8
# ---------------------------------------------------------------------------
def assert_tow_assist_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("boater_id"), str)
    assert data.get("tier") in {"BASIC", "PREMIUM"}, (
        f"tier invalid: {data.get('tier')!r}"
    )
    tr = data.get("tows_remaining")
    # PRD §3.2: BASIC=2, PREMIUM=-1 sentinel.
    assert isinstance(tr, int) and tr >= -1, (
        f"tows_remaining must be int >= -1, got {tr!r}"
    )
    assert data.get("status") == "ACTIVE", (
        f"TowAssistContract.status must be ACTIVE, got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# TowEvent — PRD §3.8 (append-only)
# ---------------------------------------------------------------------------
def assert_tow_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("contract_id"), str)
    assert is_iso8601_timestamp(str(data.get("occurred_at", "")))
    assert isinstance(data.get("from_position"), str)
    assert isinstance(data.get("to_slip_id"), str)
    cc = data.get("charge_cents")
    assert isinstance(cc, int) and cc >= 0, (
        f"charge_cents must be non-negative int, got {cc!r}"
    )


# ---------------------------------------------------------------------------
# Conservation / invariant checkers — PRD §2.10
# ---------------------------------------------------------------------------
def assert_liveaboard_count_matches(
    marina: Dict[str, Any],
    expected_count: int,
) -> None:
    """PRD §2.10: "The marina's `liveaboard_active_count` is a derived
    integer counter equal to the number of reservations on this marina
    with `liveaboard` set to true and `status` in `APPROVED` or
    `CHECKED_IN`."""
    actual = marina.get("liveaboard_active_count")
    assert actual == expected_count, (
        f"Marina.liveaboard_active_count expected {expected_count}, "
        f"got {actual!r}"
    )


def assert_tow_pool_conserved(
    contract: Dict[str, Any],
    free_tow_count: int,
    initial_tows: int = 2,
) -> None:
    """PRD §3.8: BASIC contract starts with `tows_remaining` of 2; each
    in-coverage tow decrements it by one, out-of-coverage tow leaves it
    at zero. Invariant: tows_remaining + free_tow_count == initial."""
    tr = contract.get("tows_remaining")
    assert isinstance(tr, int), (
        f"tows_remaining must be int, got {tr!r}"
    )
    assert tr + free_tow_count == initial_tows, (
        f"Tow pool invariant violated: tows_remaining={tr} + "
        f"free_count={free_tow_count} != initial={initial_tows}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    "assert_marina",
    "assert_boater",
    "assert_vessel",
    "assert_slip",
    "assert_reservation",
    "assert_waitlist_entry",
    "assert_slip_transfer_request",
    "assert_pump_out_job",
    "assert_utility_reading",
    "assert_utility_settlement",
    "assert_insurance_policy",
    "assert_tow_assist_contract",
    "assert_tow_event",
    "assert_liveaboard_count_matches",
    "assert_tow_pool_conserved",
]
