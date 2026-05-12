"""Scholarship CRUD, state transitions, window-overlap, rubric-weights."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_scholarship,
    create_quota_allocation_payload,
    create_scholarship,
    create_scholarship_payload,
    create_scholarship_with_quota,
    iso_at,
    open_scholarship,
    scholarship_state_payload,
    transition_scholarship,
    validate_error,
    validate_success,
)


class TestScholarshipCreate:

    def test_create_returns_draft_scholarship_with_envelope(self):
        """PRD §3.1: "A new scholarship enters DRAFT status."
        PRD §2.4: every persisted versioned entity carries id +
        created_at + updated_at + version = 1.

        Claim: POST /scholarships -> 201, status=DRAFT, version=1.
        """
        resp = api_client.create_scholarship(
            create_scholarship_payload(), ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert_scholarship(data)

    def test_create_rejects_rubric_weights_not_summing_to_100(self):
        """PRD §3.1: "weights are non-negative integers that must sum to
        exactly 100; on creation and on subsequent edit, any other sum
        is rejected with ERR_RUBRIC_WEIGHT_INVALID."

        Claim: rubric_weights summing to 99 -> ERR_RUBRIC_WEIGHT_INVALID.
        """
        payload = create_scholarship_payload(
            rubric_weights={"a": 60, "b": 39},
        )
        resp = api_client.create_scholarship(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RUBRIC_WEIGHT_INVALID.value)

    def test_non_need_with_family_income_ceiling_returns_null_field(self):
        """PRD §3.1: "family_income_ceiling_cents is the annual
        household-income upper bound used only for NEED scholarships
        (it must be null for any non-NEED category)."

        Claim: a MERIT scholarship returns family_income_ceiling_cents
        as null.
        """
        sch = create_scholarship(category="MERIT")
        assert sch["family_income_ceiling_cents"] is None


class TestScholarshipWindowOverlap:
    """PRD §3.1: half-open application_window intervals with boundary
    touching permitted."""

    def test_overlapping_window_in_same_category_is_rejected(self):
        """PRD §3.1: "At the moment a scholarship is created the server
        checks the application window against every other scholarship of
        the same `category` whose `status` is not `DISBURSED`. For this
        check, intervals are half-open `[application_window_start,
        application_window_end)` — windows that touch exactly at a
        boundary (one scholarship's `application_window_end` equal to
        another's `application_window_start`) do not overlap and are
        accepted. Any non-empty overlap with such a peer scholarship is
        rejected with `ERR_SCHOLARSHIP_WINDOW_OVERLAP`."

        Claim: overlapping windows in same category -> 409
        ERR_SCHOLARSHIP_WINDOW_OVERLAP.
        """
        create_scholarship(
            category="MERIT",
            application_window_start=iso_at(2026, 6, 1),
            application_window_end=iso_at(2026, 6, 10),
            announcement_window_end=iso_at(2026, 6, 20),
        )
        resp = api_client.create_scholarship(
            create_scholarship_payload(
                category="MERIT",
                application_window_start=iso_at(2026, 6, 5),
                application_window_end=iso_at(2026, 6, 15),
                announcement_window_end=iso_at(2026, 6, 25),
            ),
            ADMIN,
        )
        validate_error(
            resp, ApiErrorId.ERR_SCHOLARSHIP_WINDOW_OVERLAP.value,
        )

    def test_boundary_touching_window_in_same_category_is_accepted(self):
        """PRD §3.1: "windows that touch exactly at a boundary (one
        scholarship's application_window_end equal to another's
        application_window_start) do not overlap and are accepted."

        Claim: a.end == b.start half-open touching is accepted (no
        error).
        """
        create_scholarship(
            category="MERIT",
            application_window_start=iso_at(2026, 6, 1),
            application_window_end=iso_at(2026, 6, 10),
            announcement_window_end=iso_at(2026, 6, 20),
        )
        resp = api_client.create_scholarship(
            create_scholarship_payload(
                category="MERIT",
                application_window_start=iso_at(2026, 6, 10),
                application_window_end=iso_at(2026, 6, 20),
                announcement_window_end=iso_at(2026, 7, 1),
            ),
            ADMIN,
        )
        validate_success(resp, expected_status=201)

    def test_overlap_across_different_categories_is_allowed(self):
        """PRD §3.1: "checks the application window against every other
        scholarship of the same `category`". Different categories do not
        collide.

        Claim: same-window in different categories is accepted.
        """
        create_scholarship(
            category="MERIT",
            application_window_start=iso_at(2026, 6, 1),
            application_window_end=iso_at(2026, 6, 10),
            announcement_window_end=iso_at(2026, 6, 20),
        )
        resp = api_client.create_scholarship(
            create_scholarship_payload(
                category="NEED",
                family_income_ceiling_cents=10_000_000,
                application_window_start=iso_at(2026, 6, 1),
                application_window_end=iso_at(2026, 6, 10),
                announcement_window_end=iso_at(2026, 6, 20),
            ),
            ADMIN,
        )
        validate_success(resp, expected_status=201)


class TestScholarshipOpenTransition:

    def test_open_requires_quota_sum_equals_total_quota(self):
        """PRD §3.2: "the sum of `initial_slots` across all
        `QuotaAllocation` rows for this scholarship must equal exactly
        the scholarship's `total_quota` (else `ERR_QUOTA_MISMATCH`)."

        Claim: DRAFT->OPEN with sum(initial_slots) != total_quota ->
        ERR_QUOTA_MISMATCH.
        """
        # total_quota=2 but only one slice with initial_slots=1.
        sch = create_scholarship(total_quota=2)
        validate_success(
            api_client.create_quota_allocation(
                sch["id"],
                create_quota_allocation_payload(initial_slots=1),
                ADMIN,
            ),
            expected_status=201,
        )
        advance_clock(sch["application_window_start"])
        resp = api_client.transition_scholarship(
            sch["id"], scholarship_state_payload("OPEN"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_QUOTA_MISMATCH.value)

    def test_open_requires_now_at_least_window_start(self):
        """PRD §3.2: "the logical "now" must be at least
        `application_window_start` (else `ERR_WINDOW_NOT_OPEN`)."

        Claim: transitioning DRAFT->OPEN before window_start ->
        ERR_WINDOW_NOT_OPEN.
        """
        sch, _ = create_scholarship_with_quota(
            total_quota=1,
            application_window_start=iso_at(2026, 6, 10),
            application_window_end=iso_at(2026, 6, 20),
            announcement_window_end=iso_at(2026, 7, 1),
        )
        # Set clock BEFORE the start.
        advance_clock(iso_at(2026, 6, 1))
        resp = api_client.transition_scholarship(
            sch["id"], scholarship_state_payload("OPEN"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN.value)

    def test_open_succeeds_when_preconditions_met(self):
        """PRD §3.2: "Before the transition is permitted, the server
        checks three preconditions ... The transition itself emits no
        event; the scholarship simply becomes available to students."

        Claim: with quota matched, rubric ok, and clock past start,
        DRAFT->OPEN succeeds.
        """
        sch, _ = create_scholarship_with_quota(total_quota=1)
        out = open_scholarship(sch)
        assert out["status"] == "OPEN"


class TestScholarshipReviewingTransition:

    def test_open_to_reviewing_requires_window_closed(self):
        """PRD §3.3: "a transition from OPEN to REVIEWING triggered by
        an admin call also requires that the logical "now" be at least
        application_window_end; otherwise ERR_WINDOW_NOT_CLOSED."

        Claim: admin OPEN->REVIEWING before application_window_end ->
        ERR_WINDOW_NOT_CLOSED.
        """
        sch, _ = create_scholarship_with_quota(total_quota=1)
        open_scholarship(sch)
        # Clock still inside the OPEN window.
        advance_clock(sch["application_window_start"])
        resp = api_client.transition_scholarship(
            sch["id"], scholarship_state_payload("REVIEWING"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CLOSED.value)


class TestPatchScholarship:
    """PRD §3.1: "Only while in DRAFT may a SchoolAdmin add quota slices,
    edit the scholarship, or otherwise restructure it." PRD §4 PATCH is
    permitted only while DRAFT."""

    def test_patch_rubric_weights_invalid_sum_rejected(self):
        """PRD §3.1: "on creation and on subsequent edit, any other sum
        is rejected with ERR_RUBRIC_WEIGHT_INVALID."

        Claim: PATCH /scholarships with rubric_weights summing to 50
        -> ERR_RUBRIC_WEIGHT_INVALID.
        """
        sch = create_scholarship()
        resp = api_client.patch_scholarship(
            sch["id"],
            {"rubric_weights": {"x": 50}, "version": sch["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RUBRIC_WEIGHT_INVALID.value)
