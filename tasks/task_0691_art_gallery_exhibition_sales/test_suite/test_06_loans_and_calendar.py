"""Loans: coverage adequacy boundary, the half-open booking-calendar overlap, the
coverage-beats-schedule precedence, and the overdue sweep."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_gallery_artist_artwork, setup_returned_loan,
    create_artwork, create_loan, set_clock,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestCoverageBoundary:
    def test_equal_coverage_accepted(self, api):
        """PRD §3.7: "the borrower's `coverage_value_cents` must be at least the
        artwork's `insured_value_cents`; equal coverage passes, and strictly-less
        coverage is rejected with `ERR_INSUFFICIENT_COVERAGE`."

        Design: Difficulty/boundary_precision_check/loan_coverage_equal_passes_strict_less_rejects
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000})
        resp = api.create_loan(f.create_loan_payload(
            artwork["id"], 1_000_000,  # exactly equal
            out_utc="2026-04-05T00:00:00Z", due_utc="2026-05-05T00:00:00Z",
            borrower_name="Eq Borrow"), REGISTRAR)
        loan = validate_success(resp, 201)
        assert loan["status"] == "OUTSTANDING", "equal coverage is accepted"

    def test_coverage_one_cent_short_rejected(self, api):
        """PRD §3.7: "equal coverage passes, and strictly-less coverage is rejected
        with `ERR_INSUFFICIENT_COVERAGE`."

        Design: Difficulty/boundary_precision_check/loan_coverage_equal_passes_strict_less_rejects
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000})
        resp = api.create_loan(f.create_loan_payload(
            artwork["id"], 999_999,  # one cent short
            out_utc="2026-04-05T00:00:00Z", due_utc="2026-05-05T00:00:00Z",
            borrower_name="Lt Borrow"), REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COVERAGE.value)


class TestLoanCalendarOverlap:
    def test_overlapping_window_against_returned_loan_rejected(self, api):
        """PRD §3.7: "the new loan's window, treated as the half-open interval from
        `out_utc` up to but not including `due_utc`, must not overlap the window of
        any prior loan ever recorded for the same artwork — regardless of whether
        that earlier loan is `OUTSTANDING`, `OVERDUE`, or already `RETURNED` — and
        an overlap is rejected with `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/loan_window_half_open_overlap_same_artwork
        """
        gallery, artist, artwork, loan = setup_returned_loan(
            out_utc="2026-04-05T00:00:00Z", due_utc="2026-05-05T00:00:00Z",
            insured_value=200_000)
        # New window [04-20, 05-20) starts before prior due 05-05 -> overlaps.
        resp = api.create_loan(f.create_loan_payload(
            artwork["id"], 200_000,
            out_utc="2026-04-20T00:00:00Z", due_utc="2026-05-20T00:00:00Z",
            borrower_name="B2"), REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value)

    def test_abutting_window_at_prior_due_allowed(self, api):
        """PRD §3.7: "Because the windows are half-open, two loans that merely abut
        at a shared boundary instant do not conflict, which is the opposite of the
        closed-interval rule for exhibitions in §3.3."

        Design: Difficulty/resource_temporal_overlap/loan_window_half_open_overlap_same_artwork
        """
        gallery, artist, artwork, loan = setup_returned_loan(
            out_utc="2026-04-05T00:00:00Z", due_utc="2026-05-05T00:00:00Z",
            insured_value=200_000)
        # New window starts exactly at the prior due 05-05: half-open, no overlap.
        resp = api.create_loan(f.create_loan_payload(
            artwork["id"], 200_000,
            out_utc="2026-05-05T00:00:00Z", due_utc="2026-06-05T00:00:00Z",
            borrower_name="B3"), REGISTRAR)
        loan2 = validate_success(resp, 201)
        assert loan2["status"] == "OUTSTANDING", \
            "abutting at the prior half-open upper bound is allowed"


class TestCoverageBeatsSchedule:
    def test_under_covered_and_overlapping_returns_coverage_error(self, api):
        """PRD §2.6: "the domain-specific business rules described throughout §3,
        in this relative order — the artist-suspension gate
        (`ERR_ARTIST_SUSPENDED`), loan coverage adequacy
        (`ERR_INSUFFICIENT_COVERAGE`), temporal-overlap conflicts
        (`ERR_SCHEDULE_CONFLICT`)".
        PRD §3.7: "Coverage adequacy is checked first".

        Design: Difficulty/priority_pair_validation_conflict/coverage_safety_beats_schedule_overlap_on_loan
        """
        gallery, artist, artwork, loan = setup_returned_loan(
            out_utc="2026-04-05T00:00:00Z", due_utc="2026-05-05T00:00:00Z",
            insured_value=1_000_000)
        # New loan both overlaps AND is under-covered (500000 < 1000000).
        resp = api.create_loan(f.create_loan_payload(
            artwork["id"], 500_000,
            out_utc="2026-04-20T00:00:00Z", due_utc="2026-05-20T00:00:00Z",
            borrower_name="Tate"), REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COVERAGE.value)

    def test_coverage_check_precedes_schedule_check(self, api):
        """PRD §3.7: "Two business guards apply. Coverage adequacy is checked first:
        the borrower's `coverage_value_cents` must be at least the artwork's
        `insured_value_cents`; equal coverage passes, and strictly-less coverage is
        rejected with `ERR_INSUFFICIENT_COVERAGE`. The schedule guard is checked
        against the artwork's full loan history".

        Design: Difficulty/priority_pair_validation_conflict/coverage_safety_beats_schedule_overlap_on_loan
        """
        # Same dual-violation scenario, asserting it is NOT the schedule error.
        gallery, artist, artwork, loan = setup_returned_loan(
            out_utc="2026-04-05T00:00:00Z", due_utc="2026-05-05T00:00:00Z",
            insured_value=1_000_000)
        resp = api.create_loan(f.create_loan_payload(
            artwork["id"], 500_000,
            out_utc="2026-04-20T00:00:00Z", due_utc="2026-05-20T00:00:00Z",
            borrower_name="Tate2"), REGISTRAR)
        body = resp.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INSUFFICIENT_COVERAGE.value, \
            "coverage (safety) error must mask the schedule-conflict error"


class TestLoanOverdueSweep:
    def test_sweep_overdue_flags_outstanding_loan(self, api):
        """PRD §3.7: "a `Registrar` or `GalleryAdmin` sweeps an outstanding loan for
        overdue status: the sweep requires the loan to be `OUTSTANDING` and the
        clock to have reached or passed `due_utc`, and it flags the loan
        `OUTSTANDING → OVERDUE` for reporting while the artwork stays `ON_LOAN`."

        Design: Corner/state_machines/loan_sweep_overdue_marks_overdue
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 200_000, "insured_value_cents": 200_000})
        loan = create_loan(artwork["id"], 200_000,
                           "2026-04-05T00:00:00Z", "2026-05-05T00:00:00Z")
        set_clock("2026-05-06T00:00:00Z")  # past due_utc.
        swept = validate_success(api.sweep_overdue_loan(loan["id"], REGISTRAR))
        assert swept["status"] == "OVERDUE", "loan flagged OVERDUE after due date"
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "ON_LOAN", "artwork stays ON_LOAN"
