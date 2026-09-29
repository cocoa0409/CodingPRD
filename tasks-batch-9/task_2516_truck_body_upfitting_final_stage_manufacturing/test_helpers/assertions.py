"""Domain-specific assertion helpers.

These sit on top of the generic envelope validators and express the recurring
invariants of the PRD: the three-dimensional order state of §2.7, the twice-
rounded axle arithmetic of §2.8, the derived-field discipline of §2.10 and the
immutability of a compliance label declared in §2.4.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CLOCK_ORIGIN


# --------------------------------------------------------------------------
# Common field discipline (§2.4)
# --------------------------------------------------------------------------
def assert_common_fields(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every versioned entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID, got {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int) and record["version"] >= 1
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_immutable_label_shape(label: Dict[str, Any]) -> None:
    """A ComplianceLabel carries id and created_at but never updated_at/version."""
    assert is_valid_uuid(label["id"]), f"id must be a UUID, got {label['id']!r}"
    assert is_iso8601_timestamp(label["created_at"]), label["created_at"]
    assert "version" not in label, "a compliance label must not carry a version"
    assert "updated_at" not in label, "a compliance label must not carry updated_at"


def assert_clock_origin_timestamp(value: str) -> None:
    """A logical-clock stamp taken before any clock advance."""
    assert value is not None, "expected a logical-clock stamp, got null"
    assert value.startswith("2026-08-01T00:00:00"), (
        f"expected the pinned logical clock {CLOCK_ORIGIN}, got {value}"
    )


# --------------------------------------------------------------------------
# Order state (§2.7)
# --------------------------------------------------------------------------
def assert_order_dimensions(
    order: Dict[str, Any],
    build_status: Optional[str] = None,
    compliance_status: Optional[str] = None,
    body_install_status: Optional[str] = None,
) -> None:
    if build_status is not None:
        assert order["build_status"] == build_status, (
            f"build_status {order['build_status']} != {build_status}"
        )
    if compliance_status is not None:
        assert order["compliance_status"] == compliance_status, (
            f"compliance_status {order['compliance_status']} != {compliance_status}"
        )
    if body_install_status is not None:
        assert order["body_install_status"] == body_install_status, (
            f"body_install_status {order['body_install_status']} != {body_install_status}"
        )


def assert_order_ledger(
    order: Dict[str, Any],
    chassis_cents: int,
    upfitter_cents: int,
    goodwill_cents: int,
) -> None:
    """The three order-level liability totals recomputed at adjudication (§3.9)."""
    assert order["chassis_liability_cents"] == chassis_cents, order["chassis_liability_cents"]
    assert order["upfitter_liability_cents"] == upfitter_cents, order["upfitter_liability_cents"]
    assert order["customer_goodwill_cents"] == goodwill_cents, order["customer_goodwill_cents"]


def assert_order_commitments(
    order: Dict[str, Any],
    flow_gpm: Optional[int] = None,
    aux_amps: Optional[int] = None,
    warranty_status: Optional[str] = None,
    invoice_cents: Optional[int] = None,
) -> None:
    if flow_gpm is not None:
        assert order["committed_pto_flow_gpm"] == flow_gpm, order["committed_pto_flow_gpm"]
    if aux_amps is not None:
        assert order["committed_aux_amp_draw"] == aux_amps, order["committed_aux_amp_draw"]
    if warranty_status is not None:
        assert order["chassis_warranty_status"] == warranty_status, (
            order["chassis_warranty_status"]
        )
    if invoice_cents is not None:
        assert order["invoice_total_cents"] == invoice_cents, order["invoice_total_cents"]


# --------------------------------------------------------------------------
# Weight arithmetic (§2.8 / §3.6)
# --------------------------------------------------------------------------
def assert_axle_numbers(
    record: Dict[str, Any],
    front_lb: int,
    rear_lb: int,
    gvw_lb: int,
    payload_lb: int,
    component_count: Optional[int] = None,
) -> None:
    """Pin all five stamped weight figures of a certification or projection."""
    assert record["front_axle_load_lb"] == front_lb, (
        f"front_axle_load_lb {record['front_axle_load_lb']} != {front_lb}"
    )
    assert record["rear_axle_load_lb"] == rear_lb, (
        f"rear_axle_load_lb {record['rear_axle_load_lb']} != {rear_lb}"
    )
    assert record["gvw_lb"] == gvw_lb, f"gvw_lb {record['gvw_lb']} != {gvw_lb}"
    assert record["gvw_lb"] == record["front_axle_load_lb"] + record["rear_axle_load_lb"], (
        "gvw_lb must be the sum of the two already-rounded axle integers"
    )
    assert record["payload_capacity_lb"] == payload_lb, (
        f"payload_capacity_lb {record['payload_capacity_lb']} != {payload_lb}"
    )
    assert record["payload_capacity_lb"] >= 0, "payload capacity is floored at zero"
    if component_count is not None:
        assert record["included_component_count"] == component_count, (
            f"included_component_count {record['included_component_count']} "
            f"!= {component_count}"
        )


def assert_projection_ratings(
    projection: Dict[str, Any], gvwr_lb: int, front_gawr_lb: int, rear_gawr_lb: int
) -> None:
    assert projection["gvwr_lb"] == gvwr_lb, projection["gvwr_lb"]
    assert projection["front_gawr_lb"] == front_gawr_lb, projection["front_gawr_lb"]
    assert projection["rear_gawr_lb"] == rear_gawr_lb, projection["rear_gawr_lb"]


# --------------------------------------------------------------------------
# Hydraulics (§3.4)
# --------------------------------------------------------------------------
def assert_installation_hydraulics(
    installation: Dict[str, Any], allocated_flow_gpm: int, hydraulic_status: str
) -> None:
    assert installation["allocated_flow_gpm"] == allocated_flow_gpm, (
        f"allocated_flow_gpm {installation['allocated_flow_gpm']} != {allocated_flow_gpm}"
    )
    assert installation["hydraulic_status"] == hydraulic_status, (
        f"hydraulic_status {installation['hydraulic_status']} != {hydraulic_status}"
    )


# --------------------------------------------------------------------------
# Warranty split (§3.9)
# --------------------------------------------------------------------------
def assert_claim_split(
    claim: Dict[str, Any],
    chassis_pct: int,
    upfitter_pct: int,
    goodwill_pct: int,
    chassis_cents: int,
    upfitter_cents: int,
    goodwill_cents: int,
    split_basis: Optional[str] = None,
) -> None:
    assert claim["chassis_pct"] == chassis_pct, claim["chassis_pct"]
    assert claim["upfitter_pct"] == upfitter_pct, claim["upfitter_pct"]
    assert claim["goodwill_pct"] == goodwill_pct, claim["goodwill_pct"]
    assert claim["chassis_liability_cents"] == chassis_cents, claim["chassis_liability_cents"]
    assert claim["upfitter_liability_cents"] == upfitter_cents, (
        claim["upfitter_liability_cents"]
    )
    assert claim["customer_goodwill_cents"] == goodwill_cents, claim["customer_goodwill_cents"]
    assert (
        claim["chassis_liability_cents"]
        + claim["upfitter_liability_cents"]
        + claim["customer_goodwill_cents"]
        == claim["claim_cost_cents"]
    ), "the three cent components must sum exactly to claim_cost_cents"
    assert claim["chassis_pct"] + claim["upfitter_pct"] + claim["goodwill_pct"] == 100
    if split_basis is not None:
        assert claim["split_basis"] == split_basis, claim["split_basis"]


# --------------------------------------------------------------------------
# Miscellaneous
# --------------------------------------------------------------------------
def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, meta
    assert meta["offset"] == offset, meta
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta


def assert_sorted_by_created_at(records: Iterable[Dict[str, Any]]) -> None:
    stamps = [r["created_at"] for r in records]
    assert stamps == sorted(stamps), f"list results must ascend by created_at: {stamps}"


def assert_fields_equal(left: Dict[str, Any], right: Dict[str, Any], *, ignore=()) -> None:
    """Field-for-field equality between a write response and a subsequent read."""
    skipped = set(ignore)
    for key, value in left.items():
        if key in skipped:
            continue
        assert key in right, f"read-back is missing {key}"
        assert right[key] == value, f"{key}: write said {value!r}, read said {right[key]!r}"
