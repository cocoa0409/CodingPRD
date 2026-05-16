"""Standby pool, priority selector, and capacity reconciliation tests.

Covers PRD §3.4 (auto-promotion, priority selector, partition into
accommodation vs general, spill), §2.8 (materialised ledger), and §3.8
(cancellation freeing seats).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    admin_cancel,
    advance_clock_by,
    advance_clock_to,
    api_client,
    assert_capacity_invariant,
    assert_registration,
    create_candidate,
    create_capacity,
    create_event_with_capacity,
    create_registration_payload,
    create_test_center,
    create_test_event,
    force_confirmed_registration,
    make_candidate_headers,
    reset_clock_to,
    submit_and_approve_accommodation,
    validate_error,
    validate_success,
)
from test_helpers.constants import TEST_DEFAULTS


# ===========================================================================
# Capacity-exhausted nuance — accommodation pool exhausted
# ===========================================================================
class TestAccommodationCapacityExhausted:
    def test_accommodation_pool_exhausted_force_confirmed_rejected(self, api):
        """PRD §3.4: "If the `TestCenterCapacity` row for the chosen
        center has `available_seats` greater than zero — and, when the
        candidate already has an `APPROVED` `AccommodationRequest` on
        this event, the accommodation pool also has free capacity —
        the row is then auto-promoted to `CONFIRMED` in the same
        operation. When `force_confirmed` is true and capacity is
        insufficient (either the general pool, or the accommodation
        pool when accommodation is required), the request is rejected
        with `ERR_CAPACITY_EXHAUSTED`".

        Claim: a candidate with APPROVED accommodation can't force-
        confirm when accommodation_capacity is full, even if total
        seats are free.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=5, accommodation_capacity=1,
        )
        # Fill the one accommodation slot with candidate A.
        a = create_candidate(has_iep_or_504=True)
        force_confirmed_registration(event["id"], a, center["id"])
        submit_and_approve_accommodation(a, event["id"])

        # Candidate B also has accommodation, but the accommodation pool is now full.
        b = create_candidate(has_iep_or_504=True)
        # Submit + approve B's request first so accommodation_required would be true.
        # PRD §3.6: approve cascades onto existing registrations; instead create
        # the registration after approval to test the create-with-accommodation path.
        # Approve B's request before any registration:
        from test_helpers import submit_accommodation_request, start_review, approve_accommodation
        b_req = submit_accommodation_request(b, event["id"])
        start_review(b_req["id"])
        approve_accommodation(b_req["id"])
        # Now try to register B with force_confirmed=true.
        res = api.create_registration(
            event["id"],
            create_registration_payload(
                candidate_id=b["id"], test_center_id=center["id"],
                force_confirmed=True,
            ),
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXHAUSTED.value)


# ===========================================================================
# Standby promotion on cancellation
# ===========================================================================
class TestStandbyPromotionOnCancel:
    def test_admin_cancel_promotes_standby_candidate(self, api):
        """PRD §3.8: "If the cancelled row had been `CONFIRMED`, the
        relevant `TestCenterCapacity` has `confirmed_seats_used`
        decreased by one ... Either way, the standby promotion
        selector then fires on `(test_event_id, test_center_id)`, and
        a top-priority `STANDBY` row — if any exists with
        `standby_promotion_eligibility_at` satisfied — is promoted
        from `STANDBY` to `CONFIRMED`".

        Claim: cancelling a CONFIRMED registration on an otherwise-full
        capacity promotes the only STANDBY row to CONFIRMED.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=1, accommodation_capacity=0,
        )
        # X confirmed, occupies the only seat.
        x = create_candidate()
        x_reg = force_confirmed_registration(event["id"], x, center["id"])

        # Y registers (lands in STANDBY).
        y = create_candidate()
        y_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=y["id"], test_center_id=center["id"]),
            make_candidate_headers(y["id"]),
        )
        y_reg = validate_success(y_res, 201)
        assert y_reg["status"] == "STANDBY"

        # Cancel X.
        admin_cancel(event["id"], x_reg["id"])

        # Refresh Y; PRD §3.8 says the selector fires immediately.
        y_after = validate_success(
            api.get_registration(event["id"], y_reg["id"], TEST_USERS["registrar_headers"]),
            200,
        )
        assert y_after["status"] == "CONFIRMED", (
            "PRD §3.8: standby promotion selector fires after a cancellation "
            "and promotes the top-priority STANDBY row"
        )


# ===========================================================================
# Priority ordering — earliest registered_at wins
# ===========================================================================
class TestStandbyPriorityOrdering:
    def test_earliest_registered_at_wins_general_pool(self, api):
        """PRD §3.4: "The priority key sorts ascending: first by
        priority class ... then by `registered_at` ascending so
        earlier registrations win, and finally by `Candidate.id`
        ascending as a lexicographic deterministic tie-break."

        Claim: among three general (non-accommodation) standby rows on
        the same (event, center), when one seat frees, the
        earliest-registered row is promoted, not the latest.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=1, accommodation_capacity=0,
        )
        # Seat occupied by X.
        x = create_candidate()
        x_reg = force_confirmed_registration(event["id"], x, center["id"])

        # Three STANDBY rows in temporal order. PRD §3.4 pins
        # `registered_at` to the creation instant — the logical clock
        # (PRD §2.10) advances only on explicit admin advance, so we
        # advance it between registrations to give each row a distinct
        # `registered_at` value.
        base_clock = TEST_DEFAULTS["INITIAL_CLOCK"]
        a = create_candidate()
        a_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=a["id"], test_center_id=center["id"]),
            make_candidate_headers(a["id"]),
        )
        a_reg = validate_success(a_res, 201)
        advance_clock_by(timedelta(seconds=1), base_clock)
        b = create_candidate()
        b_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=b["id"], test_center_id=center["id"]),
            make_candidate_headers(b["id"]),
        )
        b_reg = validate_success(b_res, 201)
        advance_clock_by(timedelta(seconds=2), base_clock)
        c = create_candidate()
        c_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=c["id"], test_center_id=center["id"]),
            make_candidate_headers(c["id"]),
        )
        c_reg = validate_success(c_res, 201)
        for r in (a_reg, b_reg, c_reg):
            assert r["status"] == "STANDBY"

        # Free the seat — A (earliest registered_at) must be promoted.
        admin_cancel(event["id"], x_reg["id"])

        a_after = validate_success(
            api.get_registration(event["id"], a_reg["id"], TEST_USERS["registrar_headers"]),
            200,
        )
        b_after = validate_success(
            api.get_registration(event["id"], b_reg["id"], TEST_USERS["registrar_headers"]),
            200,
        )
        c_after = validate_success(
            api.get_registration(event["id"], c_reg["id"], TEST_USERS["registrar_headers"]),
            200,
        )
        assert a_after["status"] == "CONFIRMED", (
            "PRD §3.4: earliest registered_at wins in the general standby pool"
        )
        assert b_after["status"] == "STANDBY"
        assert c_after["status"] == "STANDBY"


# ===========================================================================
# Capacity ledger invariant (PRD §2.8)
# ===========================================================================
class TestCapacityLedgerInvariant:
    def test_ledger_invariant_after_cancel_and_promote(self, api):
        """PRD §2.8: "The compensating invariant — that
        `available_seats` plus `confirmed_seats_used` equals
        `total_capacity` at every observable instant — is the
        integrity contract this materialised view exists to enforce."

        Claim: after a cancel+promote cascade the capacity ledger row
        still satisfies total == used + available.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=1, accommodation_capacity=0,
        )
        x = create_candidate()
        x_reg = force_confirmed_registration(event["id"], x, center["id"])
        y = create_candidate()
        y_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=y["id"], test_center_id=center["id"]),
            make_candidate_headers(y["id"]),
        )
        validate_success(y_res, 201)

        admin_cancel(event["id"], x_reg["id"])

        from test_helpers import validate_paginated as vp
        cap_list = api.list_test_center_capacities(
            event["id"], TEST_USERS["registrar_headers"],
        )
        rows, _ = vp(cap_list)
        assert rows, "expected one capacity row"
        cap = rows[0]
        assert_capacity_invariant(cap)
        # Post-cascade: one cancelled, one promoted -> used==1, available==0.
        assert cap["confirmed_seats_used"] == 1
        assert cap["available_seats"] == 0
