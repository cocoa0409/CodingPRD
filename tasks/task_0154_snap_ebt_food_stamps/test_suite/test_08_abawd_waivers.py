"""ABAWD work-training waiver lifecycle.

Covers PRD §3.8 (ABAWD ladder, waiver create/approve/reject, half-open
interval semantics).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE, ERR_VALIDATION,
    ERR_WAIVER_PERIOD_INVALID, ERR_WAIVER_OVERLAP,
    ERR_ABAWD_NOT_ELIGIBLE,
    TEST_USERS,
    assert_abawd_waiver,
    create_abawd_waiver_payload,
    setup_basic_household, dob_for_age,
    request_abawd_waiver, setup_approved_abawd_waiver,
    add_member,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


class TestWaiverCreation:
    def test_create_waiver_starts_requested(self, api):
        """PRD §3.8: "The waiver itself is requested by a `HouseholdHead` or a
        `Caseworker`, who supplies `waiver_kind` (one of the four enumerated
        kinds), `effective_from`, and `effective_to`."

        Claim: a new waiver is created in REQUESTED state.
        """
        hh, members = setup_basic_household(size=1, age=30)
        waiver = request_abawd_waiver(hh["id"], members[0]["id"])
        assert_abawd_waiver(waiver)
        assert waiver["state"] == "REQUESTED"

    def test_create_waiver_with_effective_to_before_from_rejected(self, api):
        """PRD §3.8: "the period must be valid: `effective_to` must be
        **strictly greater than** `effective_from`."

        Claim: effective_to <= effective_from yields ERR_WAIVER_PERIOD_INVALID.
        """
        hh, members = setup_basic_household(size=1, age=30)
        resp = api.create_abawd_waiver(
            hh["id"], members[0]["id"],
            create_abawd_waiver_payload(
                effective_from="2026-04-01T00:00:00.000Z",
                effective_to="2026-04-01T00:00:00.000Z",  # equal, not greater
            ),
            CASEWORKER,
        )
        validate_error(resp, ERR_WAIVER_PERIOD_INVALID)

    def test_create_waiver_over_12_months_rejected(self, api):
        """PRD §3.8: "the duration must be **at most 12 months exact** —
        anything longer is rejected with `ERR_WAIVER_PERIOD_INVALID`."

        Claim: a 13-month window yields ERR_WAIVER_PERIOD_INVALID.
        """
        hh, members = setup_basic_household(size=1, age=30)
        resp = api.create_abawd_waiver(
            hh["id"], members[0]["id"],
            create_abawd_waiver_payload(
                effective_from="2026-01-01T00:00:00.000Z",
                effective_to="2027-02-01T00:00:00.000Z",  # 13 months
            ),
            CASEWORKER,
        )
        validate_error(resp, ERR_WAIVER_PERIOD_INVALID)


class TestWaiverOverlap:
    def test_adjacency_allowed_half_open(self, api):
        """PRD §3.8: "overlap detection uses **half-open** interval semantics,
        so `effective_to` of an existing waiver may equal `effective_from` of
        the new waiver (adjacency is allowed)."

        Claim: a new waiver whose effective_from equals an existing waiver's
        effective_to is accepted (REQUESTED state created).
        """
        # difficulty: resource_temporal_overlap/abawd_waiver_half_open_interval_overlap
        hh, members = setup_basic_household(size=1, age=30)
        member_id = members[0]["id"]
        # First waiver Jan-Apr 2026 — approve it
        setup_approved_abawd_waiver(
            hh["id"], member_id,
            effective_from="2026-01-01T00:00:00.000Z",
            effective_to="2026-04-01T00:00:00.000Z",
        )
        # Second waiver adjacent: Apr-Jul 2026 (effective_from == prior effective_to)
        resp = api.create_abawd_waiver(
            hh["id"], member_id,
            create_abawd_waiver_payload(
                effective_from="2026-04-01T00:00:00.000Z",
                effective_to="2026-07-01T00:00:00.000Z",
            ),
            CASEWORKER,
        )
        data = validate_success(resp, expected_status=201)
        assert data["state"] == "REQUESTED"

    def test_open_overlap_rejected(self, api):
        """PRD §3.8: "any open-interval overlap is rejected with
        `ERR_WAIVER_OVERLAP`."

        Claim: a new waiver whose interval overlaps an existing APPROVED one
        on the same Member yields ERR_WAIVER_OVERLAP.
        """
        # difficulty: resource_temporal_overlap/abawd_waiver_half_open_interval_overlap
        hh, members = setup_basic_household(size=1, age=30)
        member_id = members[0]["id"]
        setup_approved_abawd_waiver(
            hh["id"], member_id,
            effective_from="2026-01-01T00:00:00.000Z",
            effective_to="2026-04-01T00:00:00.000Z",
        )
        resp = api.create_abawd_waiver(
            hh["id"], member_id,
            create_abawd_waiver_payload(
                effective_from="2026-03-15T00:00:00.000Z",
                effective_to="2026-06-15T00:00:00.000Z",
            ),
            CASEWORKER,
        )
        validate_error(resp, ERR_WAIVER_OVERLAP)


class TestWaiverApproval:
    def test_approve_waiver_eligible_member(self, api):
        """PRD §3.8: "A `Caseworker` approves a `REQUESTED` waiver — transitioning
        it to `APPROVED` — only when all four eligibility checks pass at the
        **`effective_from`** instant: the member's age is between 18 and 49
        inclusive, the member is not disabled, the member is not pregnant, and
        the household contains no other member under age 18."

        Claim: approve on an eligible member yields APPROVED.
        """
        hh, members = setup_basic_household(size=1, age=30)
        member_id = members[0]["id"]
        waiver = request_abawd_waiver(hh["id"], member_id)
        resp = api.approve_abawd_waiver(hh["id"], member_id, waiver["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["state"] == "APPROVED"

    def test_approve_waiver_member_disabled_rejected(self, api):
        """PRD §3.8: "the member is not disabled."

        Claim: approving a waiver for a disabled member yields ERR_ABAWD_NOT_ELIGIBLE.
        """
        hh, members = setup_basic_household(size=1, age=30, is_disabled=True)
        member_id = members[0]["id"]
        waiver = request_abawd_waiver(hh["id"], member_id)
        resp = api.approve_abawd_waiver(hh["id"], member_id, waiver["id"], CASEWORKER)
        validate_error(resp, ERR_ABAWD_NOT_ELIGIBLE)

    def test_approve_waiver_household_has_minor_rejected(self, api):
        """PRD §3.8: "the household contains no other member under age 18."

        Claim: approving a waiver when household has an under-18 member yields
        ERR_ABAWD_NOT_ELIGIBLE.
        """
        hh, members = setup_basic_household(size=1, age=30)
        # Add an under-18 child
        add_member(hh["id"], full_name="Child", date_of_birth=dob_for_age(10))
        member_id = members[0]["id"]
        waiver = request_abawd_waiver(hh["id"], member_id)
        resp = api.approve_abawd_waiver(hh["id"], member_id, waiver["id"], CASEWORKER)
        validate_error(resp, ERR_ABAWD_NOT_ELIGIBLE)


class TestWaiverRejection:
    def test_reject_waiver_requires_decision_reason(self, api):
        """PRD §3.8: "Rejection moves the waiver from `REQUESTED` to `REJECTED`
        and requires `decision_reason` to be set."

        Claim: reject without decision_reason yields ERR_VALIDATION.
        """
        hh, members = setup_basic_household(size=1, age=30)
        waiver = request_abawd_waiver(hh["id"], members[0]["id"])
        resp = api.reject_abawd_waiver(hh["id"], members[0]["id"], waiver["id"], {}, CASEWORKER)
        validate_error(resp, ERR_VALIDATION)

    def test_reject_waiver_with_reason_succeeds(self, api):
        """PRD §3.8: "Rejection moves the waiver from `REQUESTED` to `REJECTED`
        and requires `decision_reason` to be set."

        Claim: reject with decision_reason moves to REJECTED state.
        """
        hh, members = setup_basic_household(size=1, age=30)
        waiver = request_abawd_waiver(hh["id"], members[0]["id"])
        resp = api.reject_abawd_waiver(
            hh["id"], members[0]["id"], waiver["id"],
            {"decision_reason": "INSUFFICIENT_DOCS"}, CASEWORKER,
        )
        data = validate_success(resp)
        assert data["state"] == "REJECTED"
        assert data["decision_reason"] == "INSUFFICIENT_DOCS"


class TestAbawdStatusLadder:
    def test_member_under_18_is_not_abawd(self, api):
        """PRD §3.8: "If the member's age (computed as `Clock.now` minus
        `date_of_birth`, truncated to whole years using 365.25 days per year)
        is outside the range 18 through 49 inclusive, the status is `NOT_ABAWD`."

        Claim: a 10-year-old member has abawd_status == NOT_ABAWD.
        """
        hh, members = setup_basic_household(size=1, age=30)
        # Add a 10-year-old child
        child = add_member(hh["id"], full_name="Child", date_of_birth=dob_for_age(10))
        # Refresh
        re = validate_success(api.get_member(hh["id"], child["id"], CASEWORKER))
        assert re["abawd_status"] == "NOT_ABAWD"

    def test_disabled_adult_in_range_is_abawd_exempt(self, api):
        """PRD §3.8: "if `is_disabled` or `is_pregnant` is true, the status is
        `ABAWD_EXEMPT`."

        Claim: an able-aged disabled member has abawd_status == ABAWD_EXEMPT.
        """
        hh, members = setup_basic_household(size=1, age=30, is_disabled=True)
        re = validate_success(api.get_member(hh["id"], members[0]["id"], CASEWORKER))
        assert re["abawd_status"] == "ABAWD_EXEMPT"

    def test_standard_adult_no_waiver_is_subject(self, api):
        """PRD §3.8: "Otherwise, the status is `ABAWD_SUBJECT`."

        Claim: an 18-49 non-disabled non-pregnant adult with no waiver and
        no minor siblings has abawd_status == ABAWD_SUBJECT.
        """
        hh, members = setup_basic_household(size=1, age=30)
        re = validate_success(api.get_member(hh["id"], members[0]["id"], CASEWORKER))
        assert re["abawd_status"] == "ABAWD_SUBJECT"
