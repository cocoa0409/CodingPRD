"""Territory assignment coverage windows, exclusivity, and release."""
from test_helpers import (
    ApiErrorId,
    assert_assignment,
    create_assignment,
    create_assignment_payload,
    setup_active_dealer,
    setup_active_dealer_with_assignment,
    validate_error,
    validate_success,
)


class TestHalfOpenIntervalSemantics:
    """Assignment windows are half-open: touching boundaries are adjacent."""

    def _setup_exclusive_first_half(self, api, oem_admin_headers):
        ctx = setup_active_dealer("DL-P1", name="Dealer P1")
        first = create_assignment(
            ctx["dealer"]["id"], ctx["agreement"]["id"], "T-400",
            coverage_type="EXCLUSIVE",
            starts_on="2026-01-01", ends_on="2026-07-01")
        return ctx, first

    def test_adjacent_half_open_windows_allowed(self, api, oem_admin_headers):
        """PRD section 3.2: "Overlap between assignments on the same `territory_code` is governed by the coverage types, using **half-open interval** semantics — two windows that merely touch at a boundary date (one ends on the day the other starts) are adjacent, not overlapping, and are always allowed."

        Design: Difficulty/resource_temporal_overlap/territory_assignment_half_open_adjacency
        """
        ctx, first = self._setup_exclusive_first_half(api, oem_admin_headers)

        resp = api.create_assignment(
            create_assignment_payload(
                ctx["dealer"]["id"], ctx["agreement"]["id"],
                territory_code="T-400", coverage_type="EXCLUSIVE",
                starts_on="2026-07-01", ends_on="2026-12-31",
            ),
            oem_admin_headers,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert_assignment(adjacent)
        assert adjacent["status"] == "ACTIVE"
        assert adjacent["starts_on"] == "2026-07-01"

    def test_overlapping_window_rejected(self, api, oem_admin_headers):
        """PRD section 3.2: "An `EXCLUSIVE` assignment rejects any overlapping `ACTIVE` assignment on the same territory code; `SHARED` assignments overlap other `SHARED` assignments freely, but neither an `EXCLUSIVE` nor a `SHARED` assignment may overlap an `EXCLUSIVE` one. A forbidden overlap is rejected with `ERR_TERRITORY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/territory_assignment_half_open_adjacency
        """
        ctx, first = self._setup_exclusive_first_half(api, oem_admin_headers)

        resp = api.create_assignment(
            create_assignment_payload(
                ctx["dealer"]["id"], ctx["agreement"]["id"],
                territory_code="T-400", coverage_type="EXCLUSIVE",
                starts_on="2026-06-15", ends_on="2026-08-01",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_OVERLAP)

        unchanged = validate_success(api.get_assignment(first["id"],
                                                        oem_admin_headers),
                                     200)
        assert unchanged["status"] == "ACTIVE"


class TestOverlapVersusReferentialPriority:
    """When an assignment both overlaps forbidden coverage and names another
    dealer's agreement, the overlap rule reports first (PRD 2.8 order)."""

    def _setup_two_dealers(self, api):
        first_ctx = setup_active_dealer_with_assignment(
            "DL-K1", "T-X", coverage_type="EXCLUSIVE")
        second_ctx = setup_active_dealer("DL-K2", name="Dealer K2")
        return first_ctx, second_ctx

    def test_exclusive_overlap_beats_agreement_mismatch(
            self, api, oem_admin_headers):
        """PRD section 2.8: "When several things are wrong with a single request, the server does not choose an error arbitrarily; validations run in a fixed priority order, and the first failing check determines the rejection."
        PRD section 2.8: "8. **Uniqueness and overlap.** Duplicate business keys and forbidden coverage overlaps (`ERR_DUPLICATE_DEALER_CODE`, `ERR_DUPLICATE_AGREEMENT_CODE`, `ERR_DUPLICATE_TARGET`, `ERR_DUPLICATE_UNIT_SERIAL`, `ERR_DUPLICATE_ADVANCE_SERIAL`, `ERR_TERRITORY_OVERLAP`, `ERR_AGREEMENT_OVERLAP`, `ERR_STOCKING_NONCOMPLIANT`)."
        PRD section 2.8: "10. **Cross-reference integrity.** Referential consistency between linked resources (`ERR_AGREEMENT_DEALER_MISMATCH`, `ERR_SALE_PAYOFF_LOCKED`, `ERR_REINSTATE_BLOCKED`)."

        Design: Difficulty/priority_pair_validation_conflict/territory_overlap_constraint_over_referential
        """
        first_ctx, second_ctx = self._setup_two_dealers(api)

        # Overlaps first dealer's ACTIVE EXCLUSIVE assignment on T-X AND
        # references an agreement belonging to the other dealer.
        resp = api.create_assignment(
            create_assignment_payload(
                second_ctx["dealer"]["id"], first_ctx["agreement"]["id"],
                territory_code="T-X", coverage_type="EXCLUSIVE",
                starts_on="2026-06-01", ends_on="2026-09-01",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_OVERLAP)
        assert resp.status_code == 409, (
            "overlap (priority 8) must beat the 422 referential mismatch "
            f"(priority 10), got HTTP {resp.status_code}"
        )

    def test_shared_overlap_still_beats_agreement_mismatch(
            self, api, oem_admin_headers):
        """PRD section 3.2: "`SHARED` assignments overlap other `SHARED` assignments freely, but neither an `EXCLUSIVE` nor a `SHARED` assignment may overlap an `EXCLUSIVE` one. A forbidden overlap is rejected with `ERR_TERRITORY_OVERLAP`."
        PRD section 2.8: "8. **Uniqueness and overlap.** Duplicate business keys and forbidden coverage overlaps (`ERR_DUPLICATE_DEALER_CODE`, `ERR_DUPLICATE_AGREEMENT_CODE`, `ERR_DUPLICATE_TARGET`, `ERR_DUPLICATE_UNIT_SERIAL`, `ERR_DUPLICATE_ADVANCE_SERIAL`, `ERR_TERRITORY_OVERLAP`, `ERR_AGREEMENT_OVERLAP`, `ERR_STOCKING_NONCOMPLIANT`)."

        Design: Difficulty/priority_pair_validation_conflict/territory_overlap_constraint_over_referential
        """
        first_ctx, second_ctx = self._setup_two_dealers(api)

        # A SHARED newcomer still may not overlap an EXCLUSIVE assignment,
        # and the cross-dealer agreement reference also fails — overlap wins.
        resp = api.create_assignment(
            create_assignment_payload(
                second_ctx["dealer"]["id"], first_ctx["agreement"]["id"],
                territory_code="T-X", coverage_type="SHARED",
                starts_on="2026-06-01", ends_on="2026-09-01",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_OVERLAP)
        assert resp.status_code == 409


class TestAssignmentWindowAndReferentialRules:

    def test_assignment_before_agreement_window_rejected(
            self, api, oem_admin_headers):
        """PRD section 3.2: "The coverage window must sit within the agreement's own window: `starts_on` on or after the agreement's `effective_date`, and `ends_on` on or before the agreement's `expiry_date`; a window outside those bounds is rejected with `ERR_ASSIGNMENT_OUTSIDE_AGREEMENT`."

        Design: Corner/validations/assignment_before_agreement_window_rejected
        """
        ctx = setup_active_dealer("DL-TW1", name="Dealer TW1")
        resp = api.create_assignment(
            create_assignment_payload(
                ctx["dealer"]["id"], ctx["agreement"]["id"],
                territory_code="T-TW", coverage_type="EXCLUSIVE",
                starts_on="2025-12-01", ends_on="2026-06-01",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_AGREEMENT)

    def test_pure_referential_mismatch_rejected(self, api, oem_admin_headers):
        """PRD section 3.2: "The assignment's agreement must belong to the same dealer as the assignment — a cross-dealer reference is rejected with `ERR_AGREEMENT_DEALER_MISMATCH` — and must be `ACTIVE` at creation time (`ERR_AGREEMENT_NOT_ACTIVE`)."

        Design: Corner/validations/pure_referential_mismatch_rejected
        """
        first_ctx = setup_active_dealer("DL-RF1", name="Dealer RF1")
        second_ctx = setup_active_dealer("DL-RF2", name="Dealer RF2")

        # No coverage exists on T-RF and the window sits inside the named
        # agreement's dates, so only the cross-dealer reference can fail.
        resp = api.create_assignment(
            create_assignment_payload(
                second_ctx["dealer"]["id"], first_ctx["agreement"]["id"],
                territory_code="T-RF", coverage_type="EXCLUSIVE",
                starts_on="2026-06-01", ends_on="2026-09-01",
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_DEALER_MISMATCH)
        assert resp.status_code == 422


class TestAssignmentRelease:

    def test_release_released_assignment_rejected(self, api,
                                                  oem_admin_headers):
        """PRD section 3.2: "An assignment is born `ACTIVE` and may later be released by an administrator — or by the agreement termination/expiration and dealer termination cascades — moving it to `RELEASED`; release requires the assignment to currently be `ACTIVE` (`ERR_ASSIGNMENT_NOT_ACTIVE`), and it re-queues every lead `ROUTED` through it back to `NEW`, clearing the lead's `routed_dealer_id`, `routed_assignment_id`, and `routed_at`."

        Design: Corner/validations/release_released_assignment_rejected
        """
        ctx = setup_active_dealer_with_assignment("DL-RL1", "T-RL")
        assignment = ctx["assignment"]
        released = validate_success(
            api.release_assignment(assignment["id"], oem_admin_headers), 200)
        assert released["status"] == "RELEASED"

        resp = api.release_assignment(assignment["id"], oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE)

        unchanged = validate_success(api.get_assignment(assignment["id"],
                                                        oem_admin_headers),
                                     200)
        assert unchanged["status"] == "RELEASED"
