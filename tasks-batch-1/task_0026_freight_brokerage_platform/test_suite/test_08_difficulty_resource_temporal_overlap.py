"""Difficulty Rule 8 — resource_temporal_overlap.

Temporal-overlap conflicts on different interval semantics: ContractRate's
half-open [from, until) windows reject overlap but tolerate adjacency, while
QuoteRequest's pickup windows are expanded by a 120-minute pre-pickup buffer
so adjacency at the buffered edge IS an overlap.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_shipper,
    get_success_data,
    set_clock,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    activate_contract_rate_payload,
    create_contract_rate_payload,
    create_quote_request_payload,
)


class TestContractRateHalfOpenOverlapRejected:
    def test_overlapping_contract_window_rejected_on_activate(self, api):
        """PRD §3.2: "The activate call also enforces a non-overlap rule on
        the broker's active book: no other `ContractRate` may already be
        `ACTIVE` for the same `(shipper_id, lane_origin, lane_destination)`
        tuple with a time window that overlaps this row's window, where
        each window is treated as the half-open interval starting at
        `effective_from_utc` and ending at `effective_until_utc`; adjacency
        (one contract's `effective_until_utc` exactly equal to another's
        `effective_from_utc`) is not an overlap. An overlap is rejected
        with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_rate_half_open_overlap_rejected
        """
        # Pin clock inside the intersection [2026-06-15, 2026-07-01) so both
        # windows bracket the current time at their respective activation calls.
        set_clock("2026-06-20T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        # Contract A: [2026-01-01, 2026-07-01), ACTIVE.
        cr_a = get_success_data(api.create_contract_rate(
            create_contract_rate_payload(
                shipper["id"],
                effective_from_utc="2026-01-01T00:00:00Z",
                effective_until_utc="2026-07-01T00:00:00Z",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        get_success_data(api.activate_contract_rate(
            cr_a["id"], activate_contract_rate_payload(cr_a["version"]),
            TEST_USERS["broker_ops_headers"],
        ))

        # Contract B: [2026-06-15, 2026-12-31) overlaps [2026-06-15, 2026-07-01).
        cr_b = get_success_data(api.create_contract_rate(
            create_contract_rate_payload(
                shipper["id"],
                rate_per_mile_cents=260, fuel_surcharge_per_mile_cents=65,
                effective_from_utc="2026-06-15T00:00:00Z",
                effective_until_utc="2026-12-31T00:00:00Z",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        res = api.activate_contract_rate(
            cr_b["id"], activate_contract_rate_payload(cr_b["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(res, "ERR_CONTRACT_WINDOW_OVERLAP")
        cr_b_after = get_success_data(api_client.get_contract_rate(
            cr_b["id"], TEST_USERS["broker_ops_headers"],
        ))
        assert cr_b_after["status"] == "DRAFT"

    def test_adjacent_contract_windows_do_not_overlap(self, api):
        """PRD §3.2: "adjacency (one contract's `effective_until_utc` exactly
        equal to another's `effective_from_utc`) is not an overlap."

        Adjacency at the half-open boundary is explicitly permitted.

        Design: Difficulty/resource_temporal_overlap/contract_rate_half_open_overlap_rejected
        """
        # Activate A while clock is inside A's window [2026-01-01, 2026-07-01).
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        cr_a = get_success_data(api.create_contract_rate(
            create_contract_rate_payload(
                shipper["id"],
                effective_from_utc="2026-01-01T00:00:00Z",
                effective_until_utc="2026-07-01T00:00:00Z",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        get_success_data(api.activate_contract_rate(
            cr_a["id"], activate_contract_rate_payload(cr_a["version"]),
            TEST_USERS["broker_ops_headers"],
        ))
        # Contract B starts exactly when A ends — adjacency, NOT overlap.
        cr_b = get_success_data(api.create_contract_rate(
            create_contract_rate_payload(
                shipper["id"],
                rate_per_mile_cents=260, fuel_surcharge_per_mile_cents=65,
                effective_from_utc="2026-07-01T00:00:00Z",
                effective_until_utc="2026-12-31T00:00:00Z",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        # Advance clock into B's window so its activation passes the
        # "window brackets current time" precondition before reaching the
        # overlap check (PRD §3.2).
        set_clock("2026-08-01T00:00:00Z")
        activated_b = get_success_data(api.activate_contract_rate(
            cr_b["id"], activate_contract_rate_payload(cr_b["version"]),
            TEST_USERS["broker_ops_headers"],
        ))
        assert activated_b["status"] == "ACTIVE"


class TestQuoteWindowBufferedOverlapRejected:
    def test_second_quote_inside_buffered_window_rejected(self, api):
        """PRD §3.3: "The platform additionally guards against duplicate
        open quotes on the same lane: a new `QuoteRequest` is rejected
        with `ERR_QUOTE_WINDOW_OVERLAP` if there already exists an `OPEN`
        quote for the same `(shipper_id, lane_origin, lane_destination)`
        whose pickup window — expanded on the left by a 120-minute
        pre-pickup buffer to form the effective interval starting at
        `pickup_window_start_utc` minus 120 minutes and ending at
        `pickup_window_end_utc` — overlaps the incoming request's
        similarly-buffered window. The left boundary is closed after the
        buffer expansion, meaning adjacency at the buffered edge counts
        as an overlap."

        Design: Difficulty/resource_temporal_overlap/quote_window_buffered_overlap_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        # First OPEN quote on lane, pickup [10:00, 20:00).
        get_success_data(api.create_quote_request(
            create_quote_request_payload(
                shipper["id"],
                lane_origin="10001", lane_destination="30303",
                distance_miles=400,
                pickup_window_start_utc="2026-06-15T10:00:00Z",
                pickup_window_end_utc="2026-06-15T20:00:00Z",
                requested_equipment="DRY_VAN",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        # Second quote on same lane with pickup starting at 11:00 — inside the
        # buffered window of the first quote.
        res = api.create_quote_request(
            create_quote_request_payload(
                shipper["id"],
                lane_origin="10001", lane_destination="30303",
                distance_miles=400,
                pickup_window_start_utc="2026-06-15T11:00:00Z",
                pickup_window_end_utc="2026-06-15T21:00:00Z",
                requested_equipment="DRY_VAN",
            ),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(res, "ERR_QUOTE_WINDOW_OVERLAP")

    def test_overlap_check_scoped_to_same_shipper_and_lane(self, api):
        """PRD §3.3: "The platform additionally guards against duplicate
        open quotes on the same lane: a new `QuoteRequest` is rejected
        with `ERR_QUOTE_WINDOW_OVERLAP` if there already exists an `OPEN`
        quote for the same `(shipper_id, lane_origin, lane_destination)`
        whose pickup window — expanded on the left by a 120-minute
        pre-pickup buffer to form the effective interval starting at
        `pickup_window_start_utc` minus 120 minutes and ending at
        `pickup_window_end_utc` — overlaps the incoming request's
        similarly-buffered window."

        The (shipper_id, lane_origin, lane_destination) scoping means a
        same-time quote on a DIFFERENT lane for the SAME shipper does not
        conflict — anchoring the overlap check's identity-equality clause.

        Design: Difficulty/resource_temporal_overlap/quote_window_buffered_overlap_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        # First OPEN quote on lane 10001→30303 with overlapping pickup window.
        get_success_data(api.create_quote_request(
            create_quote_request_payload(
                shipper["id"],
                lane_origin="10001", lane_destination="30303",
                distance_miles=400,
                pickup_window_start_utc="2026-06-15T10:00:00Z",
                pickup_window_end_utc="2026-06-15T20:00:00Z",
                requested_equipment="DRY_VAN",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        # Second quote on a DIFFERENT lane, same time — must succeed because
        # the overlap check is scoped to the lane triple.
        ok = get_success_data(api.create_quote_request(
            create_quote_request_payload(
                shipper["id"],
                lane_origin="94101", lane_destination="60601",
                distance_miles=400,
                pickup_window_start_utc="2026-06-15T11:00:00Z",
                pickup_window_end_utc="2026-06-15T21:00:00Z",
                requested_equipment="DRY_VAN",
            ),
            TEST_USERS["broker_ops_headers"],
        ))
        assert ok["status"] == "OPEN"
