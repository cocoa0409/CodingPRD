"""Concurrency tests — only those explicitly defined by PRD §2.10.

We use race utilities for the cases PRD §2.10 commits to a winner-loser
shape; OCC failures (ERR_VERSION_CONFLICT) are covered in test_02.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    bind_transponder_payload,
    create_account,
    create_and_bind_transponder,
    create_transponder,
    create_vehicle,
    create_toll_event_payload,
    dispute_fine_payload,
    find_fine_for_account,
    ingest_insufficient_funds_event,
    make_account_holder_headers,
    pay_fine_payload,
    run_race,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    validate_error_is_one_of,
)


# ---------------------------------------------------------------------------
# Two bind attempts on same vehicle — PRD §2.10
# ---------------------------------------------------------------------------
def test_two_concurrent_binds_one_wins(api):
    """PRD §2.10: "Two simultaneous bind attempts targeting the same
    `Vehicle` from different `Transponder` resources serialize
    first-writer-wins on the vehicle's binding slot: the first attempt
    succeeds and the loser is rejected with `ERR_VEHICLE_ALREADY_BOUND`."

    Claim: exactly one of two concurrent bind requests succeeds; the
    other returns 409 ERR_VEHICLE_ALREADY_BOUND.
    """
    a, v = setup_account_with_vehicle()
    t1 = create_transponder(a["id"])
    t2 = create_transponder(a["id"])
    headers = make_account_holder_headers(a["id"])

    results = run_race(
        lambda: api.bind_transponder(
            a["id"], t1["id"],
            bind_transponder_payload(vehicle_id=v["id"]), headers,
        ),
        lambda: api.bind_transponder(
            a["id"], t2["id"],
            bind_transponder_payload(vehicle_id=v["id"]), headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    validate_error_is_one_of(loser, ["ERR_VEHICLE_ALREADY_BOUND"])


# ---------------------------------------------------------------------------
# Pay vs dispute on the same fine — PRD §2.10
# ---------------------------------------------------------------------------
def test_pay_vs_dispute_one_wins(api):
    """PRD §2.10: "A `Fine` racing between payment and dispute, or
    between void-via-toll-event and pay, serializes first-writer-wins
    on `Fine.settlement_status`, and the loser receives
    `ERR_INVALID_STATE`."

    Claim: exactly one of pay vs dispute succeeds; the other gets 409
    ERR_INVALID_STATE.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    headers = make_account_holder_headers(a["id"])

    results = run_race(
        lambda: api.pay_fine(
            fine["id"], pay_fine_payload(), headers,
        ),
        lambda: api.dispute_fine(
            fine["id"], dispute_fine_payload(reason="contest"), headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    validate_error_is_one_of(loser, ["ERR_INVALID_STATE"])


# ---------------------------------------------------------------------------
# Duplicate toll event ingest race — PRD §2.10
# ---------------------------------------------------------------------------
def test_two_duplicate_toll_event_ingests_one_wins(api):
    """PRD §2.10: "Two `TollEvent` ingests that share the same
    `gantry_id`, the same `read_at` minute (the `read_at` timestamp
    truncated to the minute), and the same `plate_number` +
    `plate_state` or `transponder_serial` tuple serialize
    first-writer-wins on that deduplication tuple; the second ingest
    is rejected with `ERR_DUPLICATE_TOLL_EVENT`."

    Claim: when two ingests of the dedup tuple race, exactly one
    succeeds; the loser gets ERR_DUPLICATE_TOLL_EVENT.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    p1 = create_toll_event_payload(
        gantry_id="RACE1", agency_code="NY_EZPASS", base_rate_cents=100,
        read_at="2026-05-20T13:00:00.000Z",
        transponder_serial=t["serial_number"],
    )
    p2 = create_toll_event_payload(
        gantry_id="RACE1", agency_code="NY_EZPASS", base_rate_cents=100,
        read_at="2026-05-20T13:00:30.000Z",  # same minute
        transponder_serial=t["serial_number"],
    )
    headers = TEST_USERS["gantry_operator_headers"]
    results = run_race(
        lambda: api.create_toll_event(p1, headers),
        lambda: api.create_toll_event(p2, headers),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    validate_error_is_one_of(loser, ["ERR_DUPLICATE_TOLL_EVENT"])
