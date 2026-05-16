"""Candidate creation and basic registration tests.

Covers PRD §3.3 (Candidate fields) and §3.4 (Registration creation,
fee snapshot, duplication, candidate-session overlap).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    assert_candidate,
    assert_capacity_invariant,
    assert_money_invariant,
    assert_registration,
    create_candidate,
    create_event_with_capacity,
    create_test_event,
    create_test_center,
    create_capacity,
    create_capacity_payload,
    create_registration_payload,
    force_confirmed_registration,
    fmt_iso,
    make_candidate_headers,
    parse_iso,
    reset_clock_to,
    validate_error,
    validate_success,
)
from test_helpers.constants import THRESHOLDS


# ===========================================================================
# Candidate creation (PRD §3.3)
# ===========================================================================
class TestCandidateCreation:
    def test_create_candidate_with_iep_flag(self, api):
        """PRD §3.3: "an optional `has_iep_or_504` boolean (defaulting
        to false). Setting `has_iep_or_504` to true is the gating
        condition that makes the candidate eligible to file an
        `AccommodationRequest`".

        Claim: a candidate created with has_iep_or_504=true reports the
        flag verbatim.
        """
        cand = create_candidate(has_iep_or_504=True)
        assert_candidate(cand)
        assert cand["has_iep_or_504"] is True

    def test_create_candidate_default_iep_false(self, api):
        """PRD §3.3: "an optional `has_iep_or_504` boolean (defaulting
        to false)".

        Claim: omitting the flag yields has_iep_or_504=false.
        """
        # Use the Registrar role so we can omit the flag entirely.
        from test_helpers import create_candidate_payload
        payload = create_candidate_payload()
        payload.pop("has_iep_or_504", None)
        res = api.create_candidate(payload, TEST_USERS["registrar_headers"])
        data = validate_success(res, 201)
        assert data["has_iep_or_504"] is False


# ===========================================================================
# Basic registration creation (PRD §3.4)
# ===========================================================================
class TestRegistrationCreationBasic:
    def test_create_registration_open_event_auto_promotes_to_confirmed(self, api):
        """PRD §3.4: "Each new row is initially placed in `STANDBY`. If
        the `TestCenterCapacity` row for the chosen center has
        `available_seats` greater than zero ... the row is then
        auto-promoted to `CONFIRMED` in the same operation."

        Claim: creating a registration against an event with free seats
        returns the row in CONFIRMED status.
        """
        event, center, _ = create_event_with_capacity(total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        assert_registration(reg)
        assert reg["status"] == "CONFIRMED", (
            "PRD §3.4: an open event with available seats auto-promotes "
            "the new registration to CONFIRMED"
        )

    def test_registration_charges_base_fee_only_within_deadline(self, api):
        """PRD §3.4: "`base_fee_cents_charged` mirrors the event's
        `base_fee_cents`; `late_fee_cents_charged` equals the event's
        `late_fee_cents` when `registered_at` is strictly after
        `registration_deadline` (the late window) and is zero
        otherwise".

        Claim: a registration created before registration_deadline has
        late_fee_cents_charged=0 and amount_charged_cents=base_fee_cents.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=2000,
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        assert reg["base_fee_cents_charged"] == 6000
        assert reg["late_fee_cents_charged"] == 0, (
            "PRD §3.4: late_fee_cents_charged is zero before registration_deadline"
        )
        assert reg["accommodation_fee_cents_charged"] == 0
        assert reg["amount_charged_cents"] == 6000
        assert_money_invariant(reg)

    def test_registration_after_deadline_adds_late_fee(self, api):
        """PRD §3.4: "`late_fee_cents_charged` equals the event's
        `late_fee_cents` when `registered_at` is strictly after
        `registration_deadline`".

        Claim: a registration created after registration_deadline but
        before late_registration_deadline carries the full late fee.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=2000,
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        # Advance clock past registration_deadline.
        advance_clock_to("2026-05-30T00:00:00.000Z")
        cand = create_candidate()
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        assert reg["base_fee_cents_charged"] == 6000
        assert reg["late_fee_cents_charged"] == 2000, (
            "PRD §3.4: late fee applies for registrations strictly after registration_deadline"
        )
        assert reg["amount_charged_cents"] == 8000
        assert_money_invariant(reg)


# ===========================================================================
# Duplicate registration
# ===========================================================================
class TestDuplicateRegistration:
    def test_duplicate_registration_rejected(self, api):
        """PRD §3.4: "The pair `(candidate_id, test_event_id)` must be
        unique across all `Registration` rows that are not `CANCELLED`;
        a second non-cancelled registration on the same event by the
        same candidate is rejected with `ERR_DUPLICATE_REGISTRATION`."

        Claim: a second registration by the same candidate on the same
        event returns ERR_DUPLICATE_REGISTRATION.
        """
        event, center, _ = create_event_with_capacity(total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        force_confirmed_registration(event["id"], cand, center["id"])
        # Second call.
        res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=center["id"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value)


# ===========================================================================
# Registration closed
# ===========================================================================
class TestRegistrationClosed:
    def test_registration_after_late_deadline_rejected(self, api):
        """PRD §3.1 / §3.4: "From that moment, no new `Registration`
        row may be created on the event — attempts return
        `ERR_REGISTRATION_CLOSED`".

        Claim: POST /test-events/{closed_event}/registrations returns
        ERR_REGISTRATION_CLOSED.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        advance_clock_to("2026-06-05T00:00:00.000Z")
        cand = create_candidate()
        res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=center["id"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REGISTRATION_CLOSED.value)


# ===========================================================================
# Candidate session overlap (PRD §3.4)
# ===========================================================================
class TestCandidateSessionOverlap:
    def test_overlapping_session_with_cooldown_rejected(self, api):
        """PRD §3.4: "a candidate cannot register for two events whose
        test windows overlap when extended by a four-hour cooldown
        buffer on either side: the system computes the closed interval
        from `test_date - 4 hours` through `test_date + 4 hours + 4
        hours` ... and rejects the new one with
        `ERR_CANDIDATE_SESSION_OVERLAP` if it falls within any such
        interval."

        Claim: a second registration whose buffered window overlaps an
        existing registration's buffered window for the same candidate
        returns ERR_CANDIDATE_SESSION_OVERLAP.
        """
        # Event 1 at 09:00 — buffered window 05–17.
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        c1 = create_test_center()
        create_capacity(e1["id"], c1["id"], total_capacity=5, accommodation_capacity=0)
        # Event 2 at 16:00 — buffered window 12–24. Different center to avoid the no-buffer rule.
        e2 = create_test_event(
            test_date="2026-06-08T16:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        c2 = create_test_center()
        create_capacity(e2["id"], c2["id"], total_capacity=5, accommodation_capacity=0)

        cand = create_candidate()
        force_confirmed_registration(e1["id"], cand, c1["id"])

        res = api.create_registration(
            e2["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=c2["id"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CANDIDATE_SESSION_OVERLAP.value)


# ===========================================================================
# Capacity exhausted under force_confirmed
# ===========================================================================
class TestCapacityExhausted:
    def test_force_confirmed_on_full_capacity_rejected(self, api):
        """PRD §3.4: "When `force_confirmed` is true and capacity is
        insufficient ... the request is rejected with
        `ERR_CAPACITY_EXHAUSTED`".

        Claim: force_confirmed=true against a capacity row with no
        available seats returns ERR_CAPACITY_EXHAUSTED.
        """
        event, center, _ = create_event_with_capacity(total_capacity=1, accommodation_capacity=0)
        # Fill the only seat.
        first_cand = create_candidate()
        force_confirmed_registration(event["id"], first_cand, center["id"])
        # Now try to force-confirm a second candidate.
        second = create_candidate()
        res = api.create_registration(
            event["id"],
            create_registration_payload(
                candidate_id=second["id"], test_center_id=center["id"],
                force_confirmed=True,
            ),
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXHAUSTED.value)

    def test_no_force_confirmed_lands_in_standby_silently(self, api):
        """PRD §3.4: "with `force_confirmed` left at false, the row
        simply remains in `STANDBY` and the candidate joins the
        alternate queue with no error."

        Claim: omitting force_confirmed against a full event yields
        a STANDBY registration (no error).
        """
        event, center, _ = create_event_with_capacity(total_capacity=1, accommodation_capacity=0)
        first_cand = create_candidate()
        force_confirmed_registration(event["id"], first_cand, center["id"])
        second = create_candidate()
        res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=second["id"], test_center_id=center["id"]),
            make_candidate_headers(second["id"]),
        )
        data = validate_success(res, 201)
        assert data["status"] == "STANDBY", (
            "PRD §3.4: without force_confirmed, a candidate joins STANDBY silently"
        )
