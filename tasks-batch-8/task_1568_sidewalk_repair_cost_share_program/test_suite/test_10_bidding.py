"""Bidding: deadline inclusivity, supersede, withdraw, suspension, insurance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_batch_version,
    make_contractor,
    make_contractor_headers,
    set_clock,
    setup_bid,
    setup_delinquent_notice,
    setup_sealed_batch,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _sealed_notice_batch(parcel_number, segment_code, owner_name,
                         street_address, neighborhood_code):
    """Delinquent notice swept at 2026-09-16 + sealed batch (deadline
    2026-09-22). Clock stays at 2026-09-16 (inside the bid window)."""
    bundle = setup_delinquent_notice(
        sweep_clock="2026-09-16T00:00:00Z", parcel_number=parcel_number,
        segment_code=segment_code, owner_name=owner_name,
        street_address=street_address)
    setup_sealed_batch(bundle, neighborhood_code)
    return bundle


class TestBidDeadlineInclusiveBoundary:
    def test_bid_exactly_at_deadline_accepted(self, api):
        """PRD §3.7: "Bids are accepted only while the batch is
        `SEALED_FOR_BIDDING` (else `ERR_INVALID_BATCH_STATE`) and only while the
        logical clock has not passed the `bid_deadline`, with a bid landing
        exactly at the deadline still timely (else `ERR_BID_DEADLINE_PASSED`)"

        Design: Difficulty/boundary_precision_check/bid_deadline_inclusive_boundary
        """
        bundle = _sealed_notice_batch("P-1600", "S-1600-1", "Sam Spruce",
                                      "19 Spruce St", "NB-6")
        contractor = make_contractor("Acme Paving", "L-001", "2026-12-31")
        set_clock("2026-09-22T00:00:00Z")
        bid = validate_success(api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(contractor["id"])), 201)
        assert bid["status"] == "SUBMITTED", \
            "submitted_at exactly == bid_deadline is accepted"

    def test_one_second_past_deadline_rejected(self, api):
        """PRD §3.7: "Bids are accepted only while the batch is
        `SEALED_FOR_BIDDING` (else `ERR_INVALID_BATCH_STATE`) and only while the
        logical clock has not passed the `bid_deadline`, with a bid landing
        exactly at the deadline still timely (else `ERR_BID_DEADLINE_PASSED`)"

        Design: Difficulty/boundary_precision_check/bid_deadline_inclusive_boundary
        """
        bundle = _sealed_notice_batch("P-1600", "S-1600-1", "Sam Spruce",
                                      "19 Spruce St", "NB-6")
        c1 = make_contractor("Acme Paving", "L-001", "2026-12-31")
        c2 = make_contractor("Best Builders", "L-002", "2026-12-31")

        set_clock("2026-09-22T00:00:00Z")
        validate_success(api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(c1["id"])), 201)

        set_clock("2026-09-22T00:00:01Z")
        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": get_batch_version(
                 bundle["batch"]["id"])},
            make_contractor_headers(c2["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_DEADLINE_PASSED)


class TestBidLifecycle:
    def test_withdraw_twice_rejected(self, api):
        """PRD §3.7: "A bidder may also withdraw a `SUBMITTED` bid while the
        batch remains sealed, provided the bid is its own — `SUBMITTED →
        WITHDRAWN`, failing with `ERR_INVALID_BID_STATE`,
        `ERR_OWNERSHIP_MISMATCH`, or `ERR_INVALID_BATCH_STATE` otherwise."

        Design: Corner/state_machines/bid_withdraw_twice_rejected
        """
        bundle = _sealed_notice_batch("P-S4", "S-S4-1", "Cal Cotton",
                                      "54 Cotton St", "NB-S4")
        setup_bid(bundle, unit_rate_cents=1000)
        bid_id = bundle["bid"]["id"]
        headers = make_contractor_headers(bundle["contractor"]["id"])

        bid = validate_success(api.withdraw_bid(bid_id, headers))
        assert bid["status"] == "WITHDRAWN"

        resp = api.withdraw_bid(bid_id, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_BID_STATE)

    def test_second_bid_supersedes_prior(self, api):
        """PRD §3.7: "A contractor holds at most one live bid per batch: a
        second submission by the same contractor on the same batch moves the
        prior `SUBMITTED` bid to `SUPERSEDED`, leaving only the newest bid
        award-eligible."

        Design: Corner/state_machines/bid_supersede_marks_prior_superseded
        """
        bundle = _sealed_notice_batch("P-S15", "S-S15-1", "Nan Nandina",
                                      "65 Nandina St", "NB-S15")
        contractor = make_contractor("Acme Paving", "L-001", "2026-12-31")
        headers = make_contractor_headers(contractor["id"])

        bid1 = validate_success(api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]}, headers), 201)
        assert bid1["evaluated_total_cents"] == 50000, "1000 x 50 sqft"

        bid2 = validate_success(api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": get_batch_version(
                 bundle["batch"]["id"])}, headers), 201)
        assert bid2["status"] == "SUBMITTED"
        assert bid2["evaluated_total_cents"] == 45000, "900 x 50 sqft"

        prior = validate_success(api.get_bid(bid1["id"], COORD))
        assert prior["status"] == "SUPERSEDED"


class TestContractorEligibilityAtBidTime:
    def test_suspended_contractor_bid_rejected(self, api):
        """PRD §3.7: "A suspension flips that flag true, after which the
        contractor's bids are rejected with `ERR_CONTRACTOR_SUSPENDED` and it is
        excluded from award eligibility."

        Design: Corner/errors/suspended_contractor_bid_rejected
        """
        bundle = _sealed_notice_batch("P-T6", "S-T6-1", "Vic Vole",
                                      "103 Vole St", "NB-T6")
        contractor = make_contractor("Shady Pavers", "L-601", "2026-12-31")
        suspended = validate_success(
            api.suspend_contractor(contractor["id"], COORD))
        assert suspended["is_suspended"] is True

        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(contractor["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_SUSPENDED)

    def test_insurance_short_of_work_window_rejected(self, api):
        """PRD §3.7: "the bidder's insurance must also cover the entire work
        window at submission, failing as `ERR_INSURANCE_INVALID` when
        `insurance_valid_until` falls before `work_window_end`."

        Design: Corner/errors/insurance_short_of_work_window_rejected
        """
        bundle = _sealed_notice_batch("P-T7", "S-T7-1", "Wes Woad",
                                      "104 Woad St", "NB-T7")
        contractor = make_contractor("Short Coverage LLC", "L-701",
                                     "2026-10-01")
        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(contractor["id"]))
        # work_window_end 2026-10-15 > insurance_valid_until 2026-10-01
        validate_error(resp, ApiErrorId.ERR_INSURANCE_INVALID)
