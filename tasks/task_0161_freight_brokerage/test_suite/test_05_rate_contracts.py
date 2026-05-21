"""Rate contracts — PRD §3.4 (creation, overlap, termination)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    assert_rate_contract,
    create_rate_contract,
    create_rate_contract_payload,
    iso_utc,
    parse_iso,
    setup_brokerage_with_shipper,
    terminate_rate_contract,
    validate_error,
    validate_success,
)


def test_create_active_rate_contract(api, broker_ops_headers):
    """PRD §3.4: "A rate contract lands in `ACTIVE` status on creation."

    Claim: a freshly created contract has status == ACTIVE with the
    submitted flat_rate_cents.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"], flat_rate_cents=42_000,
        ),
        broker_ops_headers,
    )
    contract = validate_success(res, 201)
    assert_rate_contract(contract)
    assert contract["status"] == "ACTIVE"
    assert contract["flat_rate_cents"] == 42_000


def test_terminate_active_rate_contract(api, broker_ops_headers):
    """PRD §3.4: "Termination via the `BrokerOps`-only termination
    capability moves it to TERMINATED."

    Claim: terminate on an ACTIVE contract -> TERMINATED.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    contract = create_rate_contract(brokerage["id"], shipper["id"])
    res = api.terminate_rate_contract(
        brokerage["id"], contract["id"], broker_ops_headers,
    )
    after = validate_success(res, 200)
    assert after["status"] == "TERMINATED"


def test_overlapping_rate_contracts_rejected(api, broker_ops_headers):
    """PRD §3.4: "Before creation, the server checks that no other
    `ACTIVE` rate contract on the same shipper, lane (origin ZIP +
    destination ZIP), and equipment type already covers any instant in
    the new contract's [`effective_from`, `effective_to`) window. An overlap
    is rejected with `ERR_RATE_CONTRACT_OVERLAP`."

    Claim: two ACTIVE contracts on the same shipper+lane+equipment
    sharing any instant fail the second create with ERR_RATE_CONTRACT_OVERLAP.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    base_from = parse_iso(brokerage["clock_now_iso"])
    create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10000", lane_destination_zip="20000",
        equipment_type="DRY_VAN",
        effective_from=iso_utc(base_from),
        effective_to=iso_utc(add_days(base_from, 30)),
    )

    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"],
            lane_origin_zip="10000", lane_destination_zip="20000",
            equipment_type="DRY_VAN",
            effective_from=iso_utc(add_days(base_from, 29)),
            effective_to=iso_utc(add_days(base_from, 50)),
        ),
        broker_ops_headers,
    )
    validate_error(res, "ERR_RATE_CONTRACT_OVERLAP")


def test_boundary_touch_is_not_overlap(api, broker_ops_headers):
    """PRD §3.4: "Before creation, the server checks that no other
    `ACTIVE` rate contract on the same shipper, lane ... already covers
    any instant in the new contract's [`effective_from`, `effective_to`)
    window."

    The interval is half-open at the upper bound — exclusive — so a
    second contract starting at exactly the first's effective_to shares
    no instant.

    Claim: RC2.effective_from == RC1.effective_to succeeds (boundary
    touch, no overlap).
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    base_from = parse_iso(brokerage["clock_now_iso"])
    rc1_to = iso_utc(add_days(base_from, 30))
    create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10000", lane_destination_zip="20000",
        equipment_type="DRY_VAN",
        effective_from=iso_utc(base_from),
        effective_to=rc1_to,
    )
    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"],
            lane_origin_zip="10000", lane_destination_zip="20000",
            equipment_type="DRY_VAN",
            effective_from=rc1_to,
            effective_to=iso_utc(add_days(base_from, 60)),
        ),
        broker_ops_headers,
    )
    validate_success(res, 201)


def test_overlap_check_scoped_to_active_only(api, broker_ops_headers):
    """PRD §3.4: "no other `ACTIVE` rate contract" — TERMINATED rows are
    out of the overlap set.

    Claim: after terminating RC1, a fully-overlapping RC2 succeeds.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    base_from = parse_iso(brokerage["clock_now_iso"])
    rc1 = create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10000", lane_destination_zip="20000",
        equipment_type="DRY_VAN",
        effective_from=iso_utc(base_from),
        effective_to=iso_utc(add_days(base_from, 30)),
    )
    terminate_rate_contract(brokerage["id"], rc1["id"])

    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"],
            lane_origin_zip="10000", lane_destination_zip="20000",
            equipment_type="DRY_VAN",
            effective_from=iso_utc(base_from),
            effective_to=iso_utc(add_days(base_from, 30)),
        ),
        broker_ops_headers,
    )
    validate_success(res, 201)


def test_overlap_check_distinguishes_equipment_type(api, broker_ops_headers):
    """PRD §3.4: overlap is checked on "the same shipper, lane (origin
    ZIP + destination ZIP), and equipment type". A REEFER contract does
    not overlap a DRY_VAN contract on the same lane.

    Claim: a REEFER contract on the same shipper+lane window succeeds
    even when a DRY_VAN contract spans the same window.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    base_from = parse_iso(brokerage["clock_now_iso"])
    create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10000", lane_destination_zip="20000",
        equipment_type="DRY_VAN",
        effective_from=iso_utc(base_from),
        effective_to=iso_utc(add_days(base_from, 30)),
    )
    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"],
            lane_origin_zip="10000", lane_destination_zip="20000",
            equipment_type="REEFER",
            effective_from=iso_utc(base_from),
            effective_to=iso_utc(add_days(base_from, 30)),
        ),
        broker_ops_headers,
    )
    validate_success(res, 201)
