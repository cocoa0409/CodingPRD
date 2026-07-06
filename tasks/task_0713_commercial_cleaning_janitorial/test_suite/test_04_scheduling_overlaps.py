"""Temporal overlap rules: walkthrough closed-interval, crew-shift half-open + buffer."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_site_contact_payload, create_walkthrough_payload, create_crew_shift_payload,
    create_account, create_rfp,
    setup_crewed_plan, create_available_crew,
    SINGLE_LIGHT_AREA, TEST_USERS,
)

_SALES = TEST_USERS["sales_rep_headers"]
_OPS = TEST_USERS["operations_manager_headers"]


class TestWalkthroughOverlap:
    """Difficulty rule: resource_temporal_overlap /
    walkthrough_closed_interval_overlap_on_site_contact."""

    def test_touching_endpoint_counts_as_overlap(self, api):
        """PRD §3.2: "the new walkthrough must not overlap any other SCHEDULED
        walkthrough on the same site contact, treating both intervals as closed
        (touching endpoints count as an overlap); a collision is rejected with
        ERR_WALKTHROUGH_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/walkthrough_closed_interval_overlap_on_site_contact
        """
        acct = create_account(legal_name="WT Co")
        sc = validate_success(api.create_site_contact(
            acct["id"],
            create_site_contact_payload(avail_start_at="2026-03-02T08:00:00Z",
                                        avail_end_at="2026-03-02T18:00:00Z"), _SALES), 201)
        rfp_a = create_rfp(acct["id"], title="RFP A")
        validate_success(api.create_walkthrough(
            acct["id"], rfp_a["id"],
            create_walkthrough_payload(sc["id"], start_at="2026-03-02T09:00:00Z",
                                       end_at="2026-03-02T10:00:00Z"), _SALES), 201)
        rfp_b = create_rfp(acct["id"], title="RFP B")
        # Second walkthrough begins exactly when the first ends -> closed-interval overlap.
        res = api.create_walkthrough(
            acct["id"], rfp_b["id"],
            create_walkthrough_payload(sc["id"], start_at="2026-03-02T10:00:00Z",
                                       end_at="2026-03-02T11:00:00Z"), _SALES)
        validate_error(res, "ERR_WALKTHROUGH_OVERLAP")

    def test_overlapping_walkthrough_leaves_rfp_open(self, api):
        """PRD §3.2: "treating both intervals as closed (touching endpoints count as an
        overlap); a collision is rejected with ERR_WALKTHROUGH_OVERLAP."
        PRD §3.1: "A new RfpOpportunity records its account_id and starts in status OPEN."

        Design: Difficulty/resource_temporal_overlap/walkthrough_closed_interval_overlap_on_site_contact
        """
        acct = create_account(legal_name="WT Co 2")
        sc = validate_success(api.create_site_contact(
            acct["id"],
            create_site_contact_payload(avail_start_at="2026-03-02T08:00:00Z",
                                        avail_end_at="2026-03-02T18:00:00Z"), _SALES), 201)
        rfp_a = create_rfp(acct["id"], title="RFP A2")
        validate_success(api.create_walkthrough(
            acct["id"], rfp_a["id"],
            create_walkthrough_payload(sc["id"], start_at="2026-03-02T09:00:00Z",
                                       end_at="2026-03-02T10:00:00Z"), _SALES), 201)
        rfp_b = create_rfp(acct["id"], title="RFP B2")
        validate_error(api.create_walkthrough(
            acct["id"], rfp_b["id"],
            create_walkthrough_payload(sc["id"], start_at="2026-03-02T09:30:00Z",
                                       end_at="2026-03-02T10:30:00Z"), _SALES),
            "ERR_WALKTHROUGH_OVERLAP")
        rfp_b_after = validate_success(api.get_rfp(acct["id"], rfp_b["id"], _SALES), 200)
        assert rfp_b_after["status"] == "OPEN"


class TestCrewShiftOverlap:
    """Difficulty rule: resource_temporal_overlap / crew_shift_half_open_plus_buffer_overlap.

    The PRD states the comparison is half-open extended by a fixed travel buffer but
    does not pin the buffer's magnitude, so these tests use a directly-overlapping
    second shift, which collides under any faithful buffer value.
    """

    def test_directly_overlapping_shift_on_same_crew_rejected(self, api):
        """PRD §3.7: "the new shift must not overlap any existing ASSIGNED shift on the
        same crew under a half-open interval comparison extended by a fixed crew travel
        buffer, otherwise ERR_SHIFT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/crew_shift_half_open_plus_buffer_overlap
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Shift Co", crew_capacity=200,
            shift_start="2026-03-03T09:00:00Z", shift_end="2026-03-03T17:00:00Z")
        # A second shift squarely inside the first window overlaps under any reading.
        res = api.assign_crew_shift(
            acct["id"], plan["id"],
            create_crew_shift_payload(crew["id"], start_at="2026-03-03T12:00:00Z",
                                      end_at="2026-03-03T14:00:00Z"), _OPS)
        validate_error(res, "ERR_SHIFT_OVERLAP")

    def test_partial_overlap_on_same_crew_rejected(self, api):
        """PRD §3.7: "the new shift must not overlap any existing ASSIGNED shift on the
        same crew under a half-open interval comparison extended by a fixed crew travel
        buffer, otherwise ERR_SHIFT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/crew_shift_half_open_plus_buffer_overlap
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Shift Co 2", crew_capacity=200,
            shift_start="2026-03-03T09:00:00Z", shift_end="2026-03-03T17:00:00Z")
        # Second shift starts inside the first and ends after it -> partial overlap.
        res = api.assign_crew_shift(
            acct["id"], plan["id"],
            create_crew_shift_payload(crew["id"], start_at="2026-03-03T16:00:00Z",
                                      end_at="2026-03-03T19:00:00Z"), _OPS)
        validate_error(res, "ERR_SHIFT_OVERLAP")


class TestSchedulingCornerClaims:
    """Corner section: state_machines (precondition enforcement)."""

    def test_walkthrough_outside_availability_rejected(self, api):
        """PRD §3.2: "the walkthrough's closed interval from start_at to end_at must lie
        entirely within the chosen site contact's inclusive availability window from
        avail_start_at to avail_end_at; a walkthrough that begins before the contact's
        availability starts or ends after it ends is rejected with
        ERR_OUTSIDE_AVAILABILITY."

        Design: Corner/state_machines/walkthrough_outside_site_contact_availability
        """
        acct = create_account(legal_name="Avail Co")
        sc = validate_success(api.create_site_contact(
            acct["id"],
            create_site_contact_payload(avail_start_at="2026-03-02T08:00:00Z",
                                        avail_end_at="2026-03-02T18:00:00Z"), _SALES), 201)
        rfp = create_rfp(acct["id"], title="Av RFP")
        res = api.create_walkthrough(
            acct["id"], rfp["id"],
            create_walkthrough_payload(sc["id"], start_at="2026-03-02T19:00:00Z",
                                       end_at="2026-03-02T20:00:00Z"), _SALES)
        validate_error(res, "ERR_OUTSIDE_AVAILABILITY")
        rfp_after = validate_success(api.get_rfp(acct["id"], rfp["id"], _SALES), 200)
        assert rfp_after["status"] == "OPEN"

    def test_complete_already_completed_walkthrough_rejected(self, api):
        """PRD §3.2: "The walkthrough being completed must currently be SCHEDULED,
        otherwise ERR_INVALID_STATE is returned."

        Design: Corner/state_machines/complete_walkthrough_from_completed_returns_invalid_state
        """
        acct = create_account(legal_name="WtState Co")
        rfp = create_rfp(acct["id"], title="Wt RFP")
        sc = validate_success(api.create_site_contact(
            acct["id"],
            create_site_contact_payload(avail_start_at="2026-03-02T08:00:00Z",
                                        avail_end_at="2026-03-02T18:00:00Z"), _SALES), 201)
        wt = validate_success(api.create_walkthrough(
            acct["id"], rfp["id"],
            create_walkthrough_payload(sc["id"], start_at="2026-03-02T09:00:00Z",
                                       end_at="2026-03-02T10:00:00Z"), _SALES), 201)
        validate_success(api.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES), 200)
        res = api.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES)
        validate_error(res, "ERR_INVALID_STATE")
