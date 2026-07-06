"""Proofing revision cycle, weekly-run scheduling gates, and optimistic concurrency.

Difficulty queue A: proof-reject revision cycle; validation-priority conflicts
(state vs referential; temporal vs constraint); deadline-cutoff boundary; schedule
gated by newspaper qualification; edition-capacity overflow; consecutive-week adjacency.
Corner queue B: invalid publication day; blackout date; stale-version reschedule.
"""
from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data
from test_helpers import (
    ApiErrorId,
    make_advertiser_headers,
    FORECLOSURE_BODY_100,
    provision_reference, create_draft_notice, submit_notice, get_pending_proof,
    approve_proof, reject_proof, get_notice, schedule_run,
    setup_submitted_notice, setup_proof_approved_notice, setup_scheduled_notice,
    schedule_notice_payload, add_insertion_payload,
)


def _drive_to_proof_approved(api, ref, **notice_overrides):
    """Create + submit + approve one more notice against existing reference data."""
    account = ref["account"]
    notice = create_draft_notice(api, account, ref["newspaper"], **notice_overrides)
    submit_notice(api, notice, account)
    proof = get_pending_proof(api, notice, account)
    approve_proof(api, proof, account)
    return get_notice(api, notice["id"], account)


def _two_bid_edition_setup(api, y_deadline):
    """Newspaper (capacity 5) with BID notice X SCHEDULED (3 lines on 2026-03-01) and
    BID notice Y in PROOF_APPROVED with the given deadline."""
    ref = provision_reference(
        api,
        newspaper_overrides={"edition_line_capacity": 5},
        statutory_overrides={"notice_type": "BID", "county": "SPRINGFIELD",
                             "min_insertions": 1, "min_days_before_deadline": 10})
    x = _drive_to_proof_approved(api, ref, notice_type="BID", title="Bid X",
                                 body_text=FORECLOSURE_BODY_100, deadline_date="2026-04-01")
    schedule_run(api, x, ref["account"], "2026-03-01")
    y = _drive_to_proof_approved(api, ref, notice_type="BID", title="Bid Y",
                                 body_text=FORECLOSURE_BODY_100, deadline_date=y_deadline)
    ref.update({"x": x, "y": y})
    return ref


# ===========================================================================
# Difficulty rule 3 — proof-reject revision cycle
# ===========================================================================

class TestProofRejectRevisionCycle:
    def test_reject_returns_notice_to_draft(self, api):
        """PRD §3.3: "Rejection moves the proof from `PENDING` to `REJECTED` and, as a
        cascade, returns the parent notice from `SUBMITTED` back to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/notice_proof_reject_revision_cycle
        """
        ref = setup_submitted_notice(api)
        reject_proof(api, ref["proof"], ref["account"], reviewer_note="fix the parcel number")
        notice = get_notice(api, ref["notice"]["id"], ref["account"])
        assert notice["status"] == "DRAFT", notice["status"]

    def test_reject_sets_proof_rejected(self, api):
        """PRD §3.3: "Rejection moves the proof from `PENDING` to `REJECTED` and, as a
        cascade, returns the parent notice from `SUBMITTED` back to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/notice_proof_reject_revision_cycle
        """
        ref = setup_submitted_notice(api)
        proof = validate_success(
            api.reject_proof(ref["proof"]["id"], {"reviewer_note": "fix the parcel number"},
                            make_advertiser_headers(ref["account"]["id"])), 200)
        assert proof["status"] == "REJECTED", proof["status"]


# ===========================================================================
# Difficulty rule 5 — validation-priority conflicts
# ===========================================================================

class TestStateBeatsReferentialOnSchedule:
    def _draft_against_unqualified(self, api):
        ref = provision_reference(api, newspaper_overrides={"name": "Pennysaver",
                                                            "circulation_qualified": False})
        notice = create_draft_notice(api, ref["account"], ref["newspaper"])
        return ref, notice

    def test_state_check_wins_error_id(self, api):
        """PRD §2.9: "fourth, that the target resource is in a state permitting the
        requested transition (`ERR_INVALID_STATE`, HTTP 409); and only then the
        domain-specific business checks described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_schedule
        """
        ref, notice = self._draft_against_unqualified(api)
        resp = api.schedule_notice(
            notice["id"], schedule_notice_payload("2026-03-01", notice["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_notice_unchanged_still_draft(self, api):
        """PRD §2.9: "fourth, that the target resource is in a state permitting the
        requested transition (`ERR_INVALID_STATE`, HTTP 409); and only then the
        domain-specific business checks described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_schedule
        """
        ref, notice = self._draft_against_unqualified(api)
        api.schedule_notice(
            notice["id"], schedule_notice_payload("2026-03-01", notice["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        after = get_notice(api, notice["id"], ref["account"])
        assert after["status"] == "DRAFT", after["status"]


class TestTemporalBeatsConstraintOnSchedule:
    def test_deadline_error_precedes_capacity(self, api):
        """PRD §3.4: "the last of the generated dates must fall on or before the notice's
        `deadline_date` minus the statutory `min_days_before_deadline` days, or the
        request is rejected with `ERR_INSERTION_AFTER_DEADLINE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_schedule
        """
        ref = _two_bid_edition_setup(api, y_deadline="2026-03-05")  # cutoff 02-23 < 03-01
        resp = api.schedule_notice(
            ref["y"]["id"], schedule_notice_payload("2026-03-01", ref["y"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSERTION_AFTER_DEADLINE, expected_status=422)

    def test_losing_notice_stays_proof_approved(self, api):
        """PRD §3.4: "Finally, edition capacity is enforced per date: for each generated
        date, the sum of the `line_count` of the insertions already occupying that
        newspaper-and-date edition (those in `SCHEDULED` or `PUBLISHED` status) plus this
        notice's own `line_count` must be at most the newspaper's `edition_line_capacity`,
        or the request is rejected with `ERR_EDITION_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_schedule
        """
        ref = _two_bid_edition_setup(api, y_deadline="2026-03-05")
        api.schedule_notice(
            ref["y"]["id"], schedule_notice_payload("2026-03-01", ref["y"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        after = get_notice(api, ref["y"]["id"], ref["account"])
        assert after["status"] == "PROOF_APPROVED", after["status"]


# ===========================================================================
# Difficulty rule 6 — deadline-cutoff boundary
# ===========================================================================

class TestLastInsertionDeadlineCutoffBoundary:
    def _foreclosure_deadline_0321(self, api):
        ref = setup_proof_approved_notice(
            api, clock_iso=None,
            statutory_overrides={"notice_type": "FORECLOSURE", "county": "SPRINGFIELD",
                                 "min_insertions": 3, "min_days_before_deadline": 7},
            notice_overrides={"notice_type": "FORECLOSURE", "title": "Foreclosure Sale",
                              "body_text": FORECLOSURE_BODY_100, "deadline_date": "2026-03-21"})
        return ref

    def test_last_date_past_cutoff_rejected(self, api):
        """PRD §3.4: "the last of the generated dates must fall on or before the notice's
        `deadline_date` minus the statutory `min_days_before_deadline` days, or the
        request is rejected with `ERR_INSERTION_AFTER_DEADLINE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/last_insertion_date_deadline_cutoff_boundary
        """
        ref = self._foreclosure_deadline_0321(api)
        # insertions 03-01/03-08/03-15; cutoff 03-21 - 7 = 03-14; 03-15 > 03-14
        resp = api.schedule_notice(
            ref["notice"]["id"], schedule_notice_payload("2026-03-01", ref["notice"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSERTION_AFTER_DEADLINE, expected_status=422)

    def test_notice_stays_proof_approved_after_rejection(self, api):
        """PRD §3.4: "Once a notice is `PROOF_APPROVED`, the `Advertiser` schedules its
        consecutive-weekly run, transitioning the notice from `PROOF_APPROVED` to
        `SCHEDULED`."

        Design: Difficulty/boundary_precision_check/last_insertion_date_deadline_cutoff_boundary
        """
        ref = self._foreclosure_deadline_0321(api)
        api.schedule_notice(
            ref["notice"]["id"], schedule_notice_payload("2026-03-01", ref["notice"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        after = get_notice(api, ref["notice"]["id"], ref["account"])
        assert after["status"] == "PROOF_APPROVED", after["status"]


# ===========================================================================
# Difficulty rule 7 — schedule gated by newspaper qualification
# ===========================================================================

class TestScheduleGatedByNewspaperQualified:
    def _unqualified_proof_approved(self, api):
        return setup_proof_approved_notice(
            api, clock_iso=None,
            newspaper_overrides={"name": "Pennysaver", "circulation_qualified": False})

    def test_unqualified_newspaper_rejected(self, api):
        """PRD §3.4: "its `circulation_qualified` must be true and the notice's `county`
        must equal the newspaper's `county`; a failure of either yields
        `ERR_NEWSPAPER_NOT_QUALIFIED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/schedule_gated_by_newspaper_qualified_state
        """
        ref = self._unqualified_proof_approved(api)
        resp = api.schedule_notice(
            ref["notice"]["id"], schedule_notice_payload("2026-03-01", ref["notice"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NEWSPAPER_NOT_QUALIFIED, expected_status=422)

    def test_notice_remains_proof_approved(self, api):
        """PRD §3.4: "Once a notice is `PROOF_APPROVED`, the `Advertiser` schedules its
        consecutive-weekly run, transitioning the notice from `PROOF_APPROVED` to
        `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/schedule_gated_by_newspaper_qualified_state
        """
        ref = self._unqualified_proof_approved(api)
        api.schedule_notice(
            ref["notice"]["id"], schedule_notice_payload("2026-03-01", ref["notice"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        after = get_notice(api, ref["notice"]["id"], ref["account"])
        assert after["status"] == "PROOF_APPROVED", after["status"]


# ===========================================================================
# Difficulty rule 8 — edition capacity & consecutive-week adjacency
# ===========================================================================

class TestEditionCapacityOverflow:
    def test_capacity_overflow_rejected(self, api):
        """PRD §3.4: "Finally, edition capacity is enforced per date: for each generated
        date, the sum of the `line_count` of the insertions already occupying that
        newspaper-and-date edition (those in `SCHEDULED` or `PUBLISHED` status) plus this
        notice's own `line_count` must be at most the newspaper's `edition_line_capacity`,
        or the request is rejected with `ERR_EDITION_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/edition_aggregate_capacity_overflow
        """
        ref = _two_bid_edition_setup(api, y_deadline="2026-04-01")  # temporal passes
        resp = api.schedule_notice(
            ref["y"]["id"], schedule_notice_payload("2026-03-01", ref["y"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_EDITION_CAPACITY_EXCEEDED, expected_status=409)

    def test_overflowing_notice_stays_proof_approved(self, api):
        """PRD §3.4: "Once a notice is `PROOF_APPROVED`, the `Advertiser` schedules its
        consecutive-weekly run, transitioning the notice from `PROOF_APPROVED` to
        `SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/edition_aggregate_capacity_overflow
        """
        ref = _two_bid_edition_setup(api, y_deadline="2026-04-01")
        api.schedule_notice(
            ref["y"]["id"], schedule_notice_payload("2026-03-01", ref["y"]["version"]),
            make_advertiser_headers(ref["account"]["id"]))
        after = get_notice(api, ref["y"]["id"], ref["account"])
        assert after["status"] == "PROOF_APPROVED", after["status"]


class TestConsecutiveWeekAdjacency:
    def test_non_adjacent_manual_insertion_rejected(self, api):
        """PRD §3.4: "the added date must be exactly 7 days away from the nearest
        existing active (`SCHEDULED` or `PUBLISHED`) insertion of the same notice. A
        larger gap, or a same-day collision with an existing insertion, breaks adjacency
        and is rejected with `ERR_INSERTION_SPACING_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/insertion_consecutive_week_adjacency_violation
        """
        ref = setup_scheduled_notice(api, clock_iso=None)  # insertions 03-01, 03-08
        resp = api.add_insertion(
            ref["notice"]["id"], add_insertion_payload("2026-03-22"),  # 14 days from 03-08
            make_advertiser_headers(ref["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSERTION_SPACING_VIOLATION, expected_status=409)

    def test_insertion_set_unchanged_after_rejection(self, api):
        """PRD §3.4: "A single extra insertion may be added to a `SCHEDULED` notice by
        supplying its `scheduled_date`; the new insertion takes a `sequence_number` of
        one more than the highest existing sequence number on the notice."

        Design: Difficulty/resource_temporal_overlap/insertion_consecutive_week_adjacency_violation
        """
        ref = setup_scheduled_notice(api, clock_iso=None)
        api.add_insertion(
            ref["notice"]["id"], add_insertion_payload("2026-03-22"),
            make_advertiser_headers(ref["account"]["id"]))
        rows = get_success_data(
            api.list_notice_insertions(ref["notice"]["id"],
                                      make_advertiser_headers(ref["account"]["id"])))
        assert len(rows) == 2, f"expected 2 insertions, got {len(rows)}"


# ===========================================================================
# Corner queue B — publication-day / blackout / stale-version
# ===========================================================================

def test_schedule_invalid_publication_day_rejected(api):
    """PRD §3.4: "each date must fall on the newspaper's `publication_weekday`, or the
    request is rejected with `ERR_INVALID_PUBLICATION_DAY` (HTTP 422)."

    Design: Corner/validations/schedule_invalid_publication_day_rejected
    """
    ref = setup_proof_approved_notice(api, clock_iso=None)
    resp = api.schedule_notice(
        ref["notice"]["id"], schedule_notice_payload("2026-03-02", ref["notice"]["version"]),
        make_advertiser_headers(ref["account"]["id"]))  # 03-02 is Monday (weekday 0)
    validate_error(resp, ApiErrorId.ERR_INVALID_PUBLICATION_DAY, expected_status=422)


def test_schedule_blackout_date_rejected(api):
    """PRD §3.4: "no date may fall inside a blackout range, where a date is blacked out
    when it is on or after a range's start and strictly before that range's end, or the
    request is rejected with `ERR_BLACKOUT_DATE` (HTTP 422)."

    Design: Corner/validations/schedule_blackout_date_rejected
    """
    ref = setup_proof_approved_notice(
        api, clock_iso=None,
        newspaper_overrides={"blackout_dates": [["2026-03-08", "2026-03-09"]]})
    resp = api.schedule_notice(
        ref["notice"]["id"], schedule_notice_payload("2026-03-01", ref["notice"]["version"]),
        make_advertiser_headers(ref["account"]["id"]))  # second insertion 03-08 is blacked out
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_DATE, expected_status=422)


def test_occ_stale_reschedule_conflict(api):
    """PRD §2.5: "The server compares `expected_notice_version` against the notice's
    current `version`; if they do not match — because another writer has already
    superseded the schedule and advanced the notice's `version` since the client last
    read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_reschedule_conflict
    """
    ref = setup_scheduled_notice(api, clock_iso=None)
    headers = make_advertiser_headers(ref["account"]["id"])
    stale_version = ref["notice"]["version"]
    # First reschedule with the observed version succeeds and advances version.
    first = api.schedule_notice(
        ref["notice"]["id"], schedule_notice_payload("2026-03-01", stale_version), headers)
    validate_success(first, expected_status=201)
    # Second reschedule still quoting the pre-advance version is rejected.
    second = api.schedule_notice(
        ref["notice"]["id"], schedule_notice_payload("2026-03-01", stale_version), headers)
    validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
