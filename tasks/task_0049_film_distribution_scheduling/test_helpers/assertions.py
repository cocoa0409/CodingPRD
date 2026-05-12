"""Per-entity assertions for the Film Distribution Scheduling API.

Each assert_<entity>(data) helper checks the structural fields PRD §2.4
and §3 declare on that entity. They serve as the structural invariant
check that callers run after every successful mutation.

PRD §2.4: 'Most entities -- Distributor, Film, Cinema, Screen, Showtime,
Ticket -- also carry the full set of common audit fields: created_at and
updated_at ... and version.' / 'Five entities are append-only ledgers or
archives and therefore carry only id and created_at -- both updated_at
and version are absent on them: Settlement, ScheduleAdjustment,
AnomalyAlert, ExternalEvent, and AuditLog.'
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _check_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    """Common fields per PRD §2.4: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity_name} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 UTC, "
        f"got {data.get('created_at')!r}"
    )
    assert "updated_at" in data and is_iso8601_timestamp(data["updated_at"]), (
        f"{entity_name}.updated_at must be ISO 8601 UTC, "
        f"got {data.get('updated_at')!r}"
    )
    assert "version" in data, f"{entity_name} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity_name}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any],
                              entity_name: str) -> None:
    """PRD §2.4: append-only entities carry only id + created_at; no
    updated_at, no version."""
    assert "id" in data, f"{entity_name} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 UTC"
    )


# ---------------------------------------------------------------------------
# Distributor (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_distributor(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Distributor")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("contact_email"), str)
    assert isinstance(data.get("default_split_ratio_bps"), int)
    assert 0 <= data["default_split_ratio_bps"] <= 10000
    assert isinstance(data.get("min_show_count_per_week"), int)
    assert data["min_show_count_per_week"] >= 0
    # PRD §3.1: 'The created row starts at status ACTIVE'.
    assert data.get("status") in {"ACTIVE", "INACTIVE"}


# ---------------------------------------------------------------------------
# Film (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
def assert_film(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Film")
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("distributor_id"), str)
    assert isinstance(data.get("duration_minutes"), int)
    assert data["duration_minutes"] > 0
    assert data.get("rating") in {"G", "PG", "PG13", "R", "NC17"}
    assert data.get("format") in {"2D", "3D", "IMAX"}
    assert isinstance(data.get("release_date"), str)
    # PRD §3.1: 'The region_strategy object on each film names the set of
    # allowed_regions ... and a per-tier cap map tier_caps'.
    rs = data.get("region_strategy")
    assert isinstance(rs, dict), "Film.region_strategy must be an object"
    assert isinstance(rs.get("allowed_regions"), list)
    assert isinstance(rs.get("tier_caps"), dict)
    assert data.get("status") in {
        "PLANNED", "RELEASED", "SHELVED", "DELISTED",
    }


# ---------------------------------------------------------------------------
# Cinema (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_cinema(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Cinema")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("region_code"), str)
    assert data.get("tier") in {"TIER_1", "TIER_2", "TIER_3"}
    psm = data.get("peak_window_start_minute")
    pem = data.get("peak_window_end_minute")
    assert isinstance(psm, int) and 0 <= psm <= 1439
    assert isinstance(pem, int) and 0 <= pem <= 1439


# ---------------------------------------------------------------------------
# Screen (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_screen(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Screen")
    assert isinstance(data.get("cinema_id"), str)
    assert isinstance(data.get("label"), str)
    assert isinstance(data.get("supported_formats"), list)
    for fmt in data["supported_formats"]:
        assert fmt in {"2D", "3D", "IMAX"}, (
            f"Screen.supported_formats[{fmt!r}] not in {{2D,3D,IMAX}}"
        )
    osm = data.get("operating_start_minute")
    oem = data.get("operating_end_minute")
    assert isinstance(osm, int) and 0 <= osm <= 1439
    assert isinstance(oem, int) and 0 < oem <= 1440
    assert oem > osm, (
        "PRD §3.3: 'operating_end_minute must be strictly greater than "
        "operating_start_minute'"
    )
    assert isinstance(data.get("cleaning_interval_minutes"), int)
    assert data["cleaning_interval_minutes"] >= 0
    assert isinstance(data.get("trailer_minutes"), int)
    assert data["trailer_minutes"] >= 0
    assert isinstance(data.get("ad_minutes"), int)
    assert data["ad_minutes"] >= 0
    assert isinstance(data.get("seat_capacity"), int)
    assert data["seat_capacity"] > 0


# ---------------------------------------------------------------------------
# Showtime (PRD §3.4, §3.5, §3.6, §3.7)
# ---------------------------------------------------------------------------
def assert_showtime(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Showtime")
    assert isinstance(data.get("screen_id"), str)
    assert isinstance(data.get("cinema_id"), str)
    assert isinstance(data.get("film_id"), str)
    # PRD §3.4: 'the film's distributor_id is denormalised at creation time'.
    assert isinstance(data.get("distributor_id"), str)
    sm = data.get("start_minute")
    assert isinstance(sm, int) and 0 <= sm <= 1439
    assert isinstance(data.get("business_date"), str)
    # PRD §3.4: block_minutes and end_minute are server-computed integers.
    assert isinstance(data.get("block_minutes"), int)
    assert data["block_minutes"] > 0
    assert isinstance(data.get("end_minute"), int)
    # PRD §3.4: 'end_minute is exactly start_minute plus block_minutes'.
    assert data["end_minute"] == sm + data["block_minutes"], (
        "PRD §3.4: 'end_minute is exactly start_minute plus block_minutes'"
    )
    assert isinstance(data.get("ticket_price_cents"), int)
    assert data["ticket_price_cents"] >= 0
    assert isinstance(data.get("presale_opens_at"), str)
    assert data.get("sale_status") in {"PRESALE", "ON_SALE", "CLOSED"}
    assert data.get("lifecycle_status") in {
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    }
    # PRD §3.4: 'tickets_sold_count, tickets_refunded_count,
    # gross_box_office_cents start at zero, and anomaly_flag starts false.'
    assert isinstance(data.get("tickets_sold_count"), int)
    assert isinstance(data.get("tickets_refunded_count"), int)
    assert isinstance(data.get("gross_box_office_cents"), int)
    assert isinstance(data.get("anomaly_flag"), bool)


# ---------------------------------------------------------------------------
# Ticket (PRD §3.5, §3.8)
# ---------------------------------------------------------------------------
def assert_ticket(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Ticket")
    assert isinstance(data.get("showtime_id"), str)
    assert isinstance(data.get("buyer_external_id"), str)
    assert isinstance(data.get("paid_amount_cents"), int)
    assert data["paid_amount_cents"] >= 0
    assert data.get("status") in {"VALID", "REFUNDED", "EXCHANGED"}
    # PRD §3.5: 'The server stamps purchased_at to the current clock'.
    assert isinstance(data.get("purchased_at"), str)
    assert is_iso8601_timestamp(data["purchased_at"])


# ---------------------------------------------------------------------------
# Settlement (PRD §2.4: append-only -- no updated_at / no version)
# ---------------------------------------------------------------------------
def assert_settlement(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "Settlement")
    assert isinstance(data.get("showtime_id"), str)
    assert isinstance(data.get("cycle_label"), str)
    assert data.get("kind") in {"POSTING", "REVERSAL"}
    assert data.get("status") in {"DRAFT", "POSTED", "REVERSED"}
    assert isinstance(data.get("gross_cents"), int)
    assert isinstance(data.get("platform_commission_cents"), int)
    assert isinstance(data.get("tax_cents"), int)
    assert isinstance(data.get("distributor_amount_cents"), int)
    assert isinstance(data.get("cinema_amount_cents"), int)
    # PRD §3.9 invariant: 'distributor_amount_cents plus cinema_amount_cents
    # plus tax_cents plus platform_commission_cents equals gross_cents
    # exactly, with no fractional residue.'
    invariant = (
        data["distributor_amount_cents"] + data["cinema_amount_cents"]
        + data["tax_cents"] + data["platform_commission_cents"]
    )
    assert invariant == data["gross_cents"], (
        "PRD §3.9: 'distributor_amount_cents plus cinema_amount_cents plus "
        "tax_cents plus platform_commission_cents equals gross_cents "
        f"exactly' -- got sum={invariant}, gross={data['gross_cents']}"
    )


# ---------------------------------------------------------------------------
# ScheduleAdjustment (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_schedule_adjustment(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "ScheduleAdjustment")
    assert isinstance(data.get("showtime_id"), str)
    assert data.get("adjustment_type") in {
        "CANCEL", "EXCHANGE_TARGET", "INSERTION",
    }
    assert data.get("reason") in {
        "LOW_ATTENDANCE", "NEW_FILM_INSERTION", "INCIDENT",
    }
    assert isinstance(data.get("affected_ticket_ids"), list)
    assert isinstance(data.get("notifications_dispatched"), int)
    assert isinstance(data.get("archived_at"), str)


# ---------------------------------------------------------------------------
# AnomalyAlert (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_anomaly_alert(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AnomalyAlert")
    assert isinstance(data.get("showtime_id"), str)
    assert isinstance(data.get("buyer_external_id"), str)
    assert data.get("rule") in {"ROLLING_WINDOW", "CUMULATIVE"}
    assert isinstance(data.get("triggering_count"), int)


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLog")
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert data.get("action") in {
        "FILM_RELEASE", "FILM_SHELVE", "FILM_DELIST",
        "SHOWTIME_CREATE", "SHOWTIME_CANCEL",
        "SETTLEMENT_POST", "SETTLEMENT_REVERSE",
        "TICKET_REFUND", "TICKET_EXCHANGE",
        "CLOCK_ADVANCE", "SWEEP_RUN",
    }
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)


# ---------------------------------------------------------------------------
# Helpers used by tests
# ---------------------------------------------------------------------------
def find_audit_entries(
    audit_rows: Iterable[Dict[str, Any]],
    *,
    action: Optional[str] = None,
    target_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter helper for audit log assertions."""
    results = []
    for row in audit_rows:
        if action is not None and row.get("action") != action:
            continue
        if target_id is not None and row.get("target_id") != target_id:
            continue
        results.append(row)
    return results


def assert_settlement_invariant(rows: Iterable[Dict[str, Any]],
                                expected_net_gross: Optional[int] = None) -> None:
    """PRD §3.9: After all POSTING+REVERSAL rows for a showtime, money is
    conserved -- the sum of (distributor+cinema+tax+platform_commission)
    equals the sum of gross_cents across the ledger.

    PRD §2.4 / §3.10 declare Settlement append-only; we sum rather than
    expect mutation in place.
    """
    sum_split = 0
    sum_gross = 0
    for row in rows:
        sum_gross += row["gross_cents"]
        sum_split += (
            row["distributor_amount_cents"] + row["cinema_amount_cents"]
            + row["tax_cents"] + row["platform_commission_cents"]
        )
    assert sum_split == sum_gross, (
        f"Money conservation broken: split-sum={sum_split}, "
        f"gross-sum={sum_gross}"
    )
    if expected_net_gross is not None:
        assert sum_gross == expected_net_gross, (
            f"Expected net gross {expected_net_gross}, got {sum_gross}"
        )


__all__ = [
    "assert_distributor",
    "assert_film",
    "assert_cinema",
    "assert_screen",
    "assert_showtime",
    "assert_ticket",
    "assert_settlement",
    "assert_schedule_adjustment",
    "assert_anomaly_alert",
    "assert_audit_log",
    "find_audit_entries",
    "assert_settlement_invariant",
]
