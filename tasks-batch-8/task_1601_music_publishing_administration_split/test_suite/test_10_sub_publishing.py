"""Sub-publishing agreements: half-open coverage overlap vs adjacency, the
suspended-sub-publisher gate's precedence over the overlap check, lazy
expiry via the logical clock, and date-range shape validation."""
from test_helpers import (
    ApiErrorId,
    activate_sub_publishing_agreement,
    create_sub_publisher,
    create_sub_publishing_agreement,
    create_sub_publishing_agreement_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def _sub_with_active_agreement(api):
    """SubPublisher SP plus an ACTIVE DE/PERFORMANCE agreement covering
    [2026-01-01, 2027-01-01)."""
    sub = create_sub_publisher()
    agreement = create_sub_publishing_agreement(
        sub["id"], territory_codes=["DE"], income_types=["PERFORMANCE"],
        retention_bp=2000,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z")
    activate_sub_publishing_agreement(agreement["id"])
    return sub, agreement


class TestCoverageOverlap:
    def test_interior_overlap_rejected(self, api):
        """PRD §3.4: "Second, a coverage-overlap check runs against every other `ACTIVE` agreement: activation is rejected with `ERR_COVERAGE_OVERLAP` if any other active agreement's `territory_codes` intersect this one's, and its `income_types` intersect this one's, and the two half-open windows genuinely overlap — the other's `effective_from` falls before this one's `effective_to`, and this one's `effective_from` falls before the other's `effective_to`."

        Design: Difficulty/resource_temporal_overlap/sub_publishing_coverage_half_open_overlap_vs_adjacency
        """
        sub, _a = _sub_with_active_agreement(api)
        overlapping = create_sub_publishing_agreement(
            sub["id"], territory_codes=["DE"], income_types=["PERFORMANCE"],
            retention_bp=1500,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z")
        resp = api.activate_sub_publishing_agreement(overlapping["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP)

    def test_adjacency_and_disjoint_income_type_allowed(self, api):
        """PRD §3.4: "Touching intervals are not overlap: a neighbor whose `effective_to` equals this agreement's `effective_from` coexists cleanly."
        PRD §3.4: "activation is rejected with `ERR_COVERAGE_OVERLAP` if any other active agreement's `territory_codes` intersect this one's, and its `income_types` intersect this one's, and the two half-open windows genuinely overlap"

        Design: Difficulty/resource_temporal_overlap/sub_publishing_coverage_half_open_overlap_vs_adjacency
        """
        sub, _a = _sub_with_active_agreement(api)
        adjacent = create_sub_publishing_agreement(
            sub["id"], territory_codes=["DE"], income_types=["PERFORMANCE"],
            retention_bp=1500,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z")
        activated = validate_success(
            api.activate_sub_publishing_agreement(adjacent["id"], ADMIN))
        assert activated["status"] == "ACTIVE", (
            "a touching interval (from == prior to) is not an overlap")

        other_income = create_sub_publishing_agreement(
            sub["id"], territory_codes=["DE"], income_types=["SYNC"],
            retention_bp=1500,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z")
        activated2 = validate_success(
            api.activate_sub_publishing_agreement(other_income["id"], ADMIN))
        assert activated2["status"] == "ACTIVE", (
            "disjoint income types never conflict even when dates overlap")


class TestActivateCheckOrdering:
    def test_suspended_sub_publisher_beats_coverage_overlap(self, api):
        """PRD §3.4: "Activating an agreement — a `PublisherAdmin` action from `DRAFT` only — runs two checks in a fixed order. First, the referenced sub-publisher must be `ACTIVE`; activating against a `SUSPENDED` sub-publisher is rejected with `ERR_SUB_PUBLISHER_NOT_ACTIVE`. Second, a coverage-overlap check runs against every other `ACTIVE` agreement: activation is rejected with `ERR_COVERAGE_OVERLAP` if any other active agreement's `territory_codes` intersect this one's, and its `income_types` intersect this one's, and the two half-open windows genuinely overlap"

        Design: Difficulty/priority_pair_validation_conflict/suspended_sub_publisher_referential_beats_coverage_overlap_temporal
        """
        sub, _a = _sub_with_active_agreement(api)
        overlapping = create_sub_publishing_agreement(
            sub["id"], territory_codes=["DE"], income_types=["PERFORMANCE"],
            retention_bp=2000,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z")
        validate_success(api.suspend_sub_publisher(sub["id"], ADMIN))

        # Violates BOTH the sub-publisher-status gate and the overlap rule;
        # the fixed check order returns the status error.
        resp = api.activate_sub_publishing_agreement(overlapping["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SUB_PUBLISHER_NOT_ACTIVE)

    def test_suspended_sub_publisher_rejected_without_overlap(self, api):
        """PRD §3.4: "First, the referenced sub-publisher must be `ACTIVE`; activating against a `SUSPENDED` sub-publisher is rejected with `ERR_SUB_PUBLISHER_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_sub_publisher_referential_beats_coverage_overlap_temporal
        """
        sub, _a = _sub_with_active_agreement(api)
        non_overlapping = create_sub_publishing_agreement(
            sub["id"], territory_codes=["DE"], income_types=["PERFORMANCE"],
            retention_bp=1500,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z")
        validate_success(api.suspend_sub_publisher(sub["id"], ADMIN))

        resp = api.activate_sub_publishing_agreement(non_overlapping["id"],
                                                     ADMIN)
        validate_error(resp, ApiErrorId.ERR_SUB_PUBLISHER_NOT_ACTIVE)


class TestLazyExpiry:
    def test_agreement_lazy_expiry_via_clock(self, api):
        """PRD §2.5: "A SubPublishingAgreement in `ACTIVE` behaves as `EXPIRED`, and reports `EXPIRED` on any read, once the logical clock reaches or passes its `effective_to`."
        PRD §2.5: "These derived statuses are re-evaluated on every read and before every action on the affected resource; whenever the clock is set to a new value, subsequent reads and actions reflect the new derivation."

        Design: Corner/state_machines/agreement_lazy_expiry_via_clock
        """
        sub, agreement = _sub_with_active_agreement(api)
        assert validate_success(
            api.get_sub_publishing_agreement(agreement["id"], ADMIN)
        )["status"] == "ACTIVE"

        set_clock("2027-01-01T00:00:00Z")
        after = validate_success(
            api.get_sub_publishing_agreement(agreement["id"], ADMIN))
        assert after["status"] == "EXPIRED", (
            "at now == effective_to exactly the end bound is exclusive")


class TestDateRangeShape:
    def test_agreement_invalid_date_range_rejected(self, api):
        """PRD §3.4: "a coverage window from `effective_from` (inclusive) to `effective_to` (exclusive), forming a half-open interval. `effective_from` must be strictly before `effective_to`, else `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/agreement_invalid_date_range_rejected
        """
        sub = create_sub_publisher()
        payload = create_sub_publishing_agreement_payload(
            sub["id"],
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z")
        resp = api.create_sub_publishing_agreement(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
