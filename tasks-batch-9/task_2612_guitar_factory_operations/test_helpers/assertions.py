"""
Domain assertion helpers.

Each helper restates one invariant or one envelope rule the specification
declares, so a test can name that rule once instead of spelling out the
arithmetic. None of them computes an expected business figure from the response
under test: the conservation helpers compare buckets the API itself reports, and
everything else is a shape check.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import JsonDict


# ---------------------------------------------------------------------------
# Envelope and system fields
# ---------------------------------------------------------------------------
def assert_envelope_meta(body: JsonDict) -> None:
    """The request identifier is server-minted and prefixed, the stamp is ISO 8601."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp is not ISO 8601: {meta['api_request_timestamp']!r}"
    )


def assert_pagination_meta(meta: JsonDict, limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    """A list reply reports the window it applied and the size of the whole set."""
    assert meta["limit"] == limit, f"limit {meta['limit']} != {limit}"
    assert meta["offset"] == offset, f"offset {meta['offset']} != {offset}"
    assert meta["total_count"] == total_count, (
        f"total_count {meta['total_count']} != {total_count}"
    )
    assert meta["has_more"] is has_more, f"has_more {meta['has_more']} != {has_more}"


def assert_system_fields(row: JsonDict, versioned: bool = True) -> None:
    """An identifier that is an opaque UUID, plus the audit stamps."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"])
    if versioned:
        assert is_iso8601_timestamp(row["updated_at"])
        assert isinstance(row["version"], int)
        assert row["version"] >= 1


def assert_reference_data_shape(row: JsonDict) -> None:
    """Reference data carries an identifier and a creation stamp and nothing more."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"])
    assert "version" not in row, "reference data must expose no version"
    assert "updated_at" not in row, "reference data must expose no updated_at"


# ---------------------------------------------------------------------------
# Conservation invariants
# ---------------------------------------------------------------------------
def assert_wood_conserved(lot: JsonDict) -> None:
    """
    A lot's board_feet_received equals available plus unassigned plus reserved
    plus consumed plus scrapped plus kerf loss, with no tolerance whatsoever.
    """
    total = round(
        lot["board_feet_available"]
        + lot["board_feet_unassigned"]
        + lot["board_feet_reserved"]
        + lot["board_feet_consumed"]
        + lot["board_feet_scrapped"]
        + lot["board_feet_kerf_loss"],
        2,
    )
    assert total == lot["board_feet_received"], (
        f"wood identity broken: buckets sum to {total}, "
        f"received is {lot['board_feet_received']}"
    )


def assert_board_feet_cut_mirror(lot: JsonDict) -> None:
    """board_feet_cut mirrors unassigned plus reserved plus consumed plus scrapped."""
    mirror = round(
        lot["board_feet_unassigned"]
        + lot["board_feet_reserved"]
        + lot["board_feet_consumed"]
        + lot["board_feet_scrapped"],
        2,
    )
    assert mirror == lot["board_feet_cut"], (
        f"board_feet_cut {lot['board_feet_cut']} != mirror {mirror}"
    )


def assert_money_conserved(order: JsonDict) -> None:
    """
    An order's deposit_paid_cents equals applied plus refunded plus forfeited
    plus held.
    """
    total = (
        order["deposit_applied_cents"]
        + order["deposit_refunded_cents"]
        + order["deposit_forfeited_cents"]
        + order["deposit_held_cents"]
    )
    assert total == order["deposit_paid_cents"], (
        f"money identity broken: buckets sum to {total}, "
        f"paid is {order['deposit_paid_cents']}"
    )


def assert_minutes_conserved(station: JsonDict) -> None:
    """
    A station's total_scheduled_minutes equals held plus consumed plus released.
    """
    total = (
        station["held_minutes"]
        + station["consumed_minutes"]
        + station["released_minutes"]
    )
    assert total == station["total_scheduled_minutes"], (
        f"minute identity broken: buckets sum to {total}, "
        f"total_scheduled is {station['total_scheduled_minutes']}"
    )


def assert_station_minutes(station: JsonDict, total: int, held: int,
                           consumed: int, released: int) -> None:
    """All four minute buckets at once, plus the identity that binds them."""
    assert station["total_scheduled_minutes"] == total
    assert station["held_minutes"] == held
    assert station["consumed_minutes"] == consumed
    assert station["released_minutes"] == released
    assert_minutes_conserved(station)


def assert_lot_ledger(lot: JsonDict, available: float, unassigned: float,
                      reserved: float, consumed: float, scrapped: float,
                      kerf_loss: float) -> None:
    """All six wood buckets at once, plus the identity that binds them."""
    assert lot["board_feet_available"] == available, (
        f"available {lot['board_feet_available']} != {available}"
    )
    assert lot["board_feet_unassigned"] == unassigned, (
        f"unassigned {lot['board_feet_unassigned']} != {unassigned}"
    )
    assert lot["board_feet_reserved"] == reserved, (
        f"reserved {lot['board_feet_reserved']} != {reserved}"
    )
    assert lot["board_feet_consumed"] == consumed, (
        f"consumed {lot['board_feet_consumed']} != {consumed}"
    )
    assert lot["board_feet_scrapped"] == scrapped, (
        f"scrapped {lot['board_feet_scrapped']} != {scrapped}"
    )
    assert lot["board_feet_kerf_loss"] == kerf_loss, (
        f"kerf_loss {lot['board_feet_kerf_loss']} != {kerf_loss}"
    )
    assert_wood_conserved(lot)


def assert_deposit_ledger(order: JsonDict, paid: int, applied: int, refunded: int,
                          forfeited: int, held: int) -> None:
    """All five deposit figures at once, plus the identity that binds them."""
    assert order["deposit_paid_cents"] == paid
    assert order["deposit_applied_cents"] == applied
    assert order["deposit_refunded_cents"] == refunded
    assert order["deposit_forfeited_cents"] == forfeited
    assert order["deposit_held_cents"] == held
    assert_money_conserved(order)


# ---------------------------------------------------------------------------
# Two-dimensional order state
# ---------------------------------------------------------------------------
def assert_order_state(order: JsonDict, build_stage: str,
                       commercial_status: str) -> None:
    """The shop-floor dimension and the sales dimension, named together."""
    assert order["build_stage"] == build_stage, (
        f"build_stage {order['build_stage']} != {build_stage}"
    )
    assert order["commercial_status"] == commercial_status, (
        f"commercial_status {order['commercial_status']} != {commercial_status}"
    )


def assert_decimal_2dp(value, name: str = "value") -> None:
    """A figure carried to two decimal places, and never null."""
    assert value is not None, f"{name} must not be null"
    assert round(float(value), 2) == float(value), (
        f"{name} carries more than two decimal places: {value!r}"
    )
