"""Partner institution certification lifecycle: suspend/reinstate/lapse/recert
cycle, decertification cascade, review-gap spacing, and OCC on review create."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    make_criteria_ratings,
    setup_effective_standard, create_institution, open_review, score_review,
    finalize_review, setup_certified_institution, setup_decertification_pending,
    suspend_institution, reinstate_institution, set_clock, run_ops_epoch,
    get_institution,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]


def _run_recertification_cycle(api):
    """Full CERTIFIED -> SUSPENDED -> CERTIFIED -> LAPSED -> UNDER_REVIEW ->
    CERTIFIED walk. Returns a dict of the status observed after each hop."""
    ctx = setup_certified_institution()  # CERTIFIED at startup clock 2026-05-01
    inst_id = ctx["institution"]["id"]

    out = {"ctx": ctx}
    out["after_suspend"] = suspend_institution(inst_id)["certification_status"]
    out["after_reinstate"] = reinstate_institution(inst_id)["certification_status"]

    set_clock("2028-05-02T00:00:00Z")  # past certified_at + 24 months
    run_ops_epoch()
    out["after_lapse"] = get_institution(inst_id)["certification_status"]

    rev2 = open_review(inst_id, ctx["standard"]["id"],
                       period_start="2026-04-01", period_end="2026-04-30")
    out["review2"] = rev2
    out["after_recert_open"] = get_institution(inst_id)["certification_status"]
    score_review(rev2["id"])
    finalize_review(rev2["id"])
    inst_final = get_institution(inst_id)
    out["after_finalize"] = inst_final["certification_status"]
    out["certified_at"] = inst_final["certified_at"]
    return out


class TestRecertificationCycle:
    def test_suspend_then_reinstate_before_expiry(self, api):
        """PRD §3.2: "A `CERTIFIED` institution can be suspended by a coalition administrator; attempting the transition from any other status is rejected with `ERR_INVALID_STATE`."
        PRD §3.2: "Suspension is reversible by reinstatement, but only while the certification has not yet lapsed: reinstatement requires the institution to be `SUSPENDED` (`ERR_INVALID_STATE` otherwise) and requires the current logical-clock reading to be strictly before `certification_expires_at`; a reinstatement attempted at or after expiry is rejected with `ERR_CERTIFICATION_LAPSED`."

        Design: Difficulty/non_linear_state_machine/institution_recertification_cycle
        """
        out = _run_recertification_cycle(api)
        assert out["after_suspend"] == "SUSPENDED"
        assert out["after_reinstate"] == "CERTIFIED", (
            "clock 2026-05-01 < expiry 2028-05-01, so reinstatement succeeds"
        )

    def test_lapse_then_recertification_review_recertifies(self, api):
        """PRD §3.2: "Lapse itself is not a manual act — when the ops epoch finds a `CERTIFIED` institution whose `certification_expires_at` has been reached by the logical clock, the institution moves to `LAPSED`."
        PRD §3.1: "a `LAPSED` institution likewise moves to `UNDER_REVIEW`"
        PRD §3.1: "On `PASS` or `CONDITIONAL`, an institution in `UNDER_REVIEW` moves to `CERTIFIED`: `certified_at` is set to the current logical-clock reading, `certification_expires_at` is computed as `certified_at` plus twenty-four months, and `certified_standard_id` becomes the review's pinned `standard_id`."

        Design: Difficulty/non_linear_state_machine/institution_recertification_cycle
        """
        out = _run_recertification_cycle(api)
        assert out["after_lapse"] == "LAPSED"
        assert out["after_recert_open"] == "UNDER_REVIEW", (
            "recertification review period 2026-04-01 satisfies the 30-day gap "
            "after prior period_end 2026-02-28"
        )
        assert out["after_finalize"] == "CERTIFIED"
        assert str(out["certified_at"]).startswith("2028-05-02"), (
            "certified_at is the logical-clock reading at finalize time"
        )


class TestDecertificationCascade:
    def test_fail_finalize_decertifies_institution(self, api):
        """PRD §3.1: "On `FAIL`, the institution moves from `UNDER_REVIEW` to `DECERTIFIED` and a four-link cascade runs: every `AccountOpeningEvent` of the institution still in `SCHEDULED` moves to `CANCELLED`; each cancelled event's referrals in `BOOKED` move back to `DOCS_COMPLETE` with their `booked_event_id` cleared; each affected participant's `pipeline_stage` is recomputed per §3.4; and the institution's `current_review_id` is cleared."

        Design: Difficulty/transitive_cascade/decert_finalize_fail_cascade
        """
        ctx = setup_decertification_pending()
        data = finalize_review(ctx["review2"]["id"])
        assert data["status"] == "FINALIZED_FAIL", (
            "FEE_COMPLIANCE rating 0 trips the mandatory floor"
        )
        inst = get_institution(ctx["institution"]["id"])
        assert inst["certification_status"] == "DECERTIFIED"  # cascade link 1

    def test_fail_finalize_cancels_event_releases_booking_recomputes_pipeline(self, api):
        """PRD §3.1: "every `AccountOpeningEvent` of the institution still in `SCHEDULED` moves to `CANCELLED`; each cancelled event's referrals in `BOOKED` move back to `DOCS_COMPLETE` with their `booked_event_id` cleared; each affected participant's `pipeline_stage` is recomputed per §3.4"
        PRD §3.4: "Otherwise, if `docs_complete` is true, the stage is `DOCS_READY`."

        Design: Difficulty/transitive_cascade/decert_finalize_fail_cascade
        """
        ctx = setup_decertification_pending()
        finalize_review(ctx["review2"]["id"])

        event = get_success_data(api.get_account_opening_event(ctx["event"]["id"], ADMIN))
        assert event["status"] == "CANCELLED"  # cascade link 2
        assert event["booked_count"] == 0

        referral = get_success_data(api.get_referral(ctx["referral"]["id"], NAV))
        assert referral["status"] == "DOCS_COMPLETE"  # cascade link 3
        assert referral.get("booked_event_id") is None

        participant = get_success_data(api.get_participant(ctx["participant"]["id"], NAV))
        assert participant["pipeline_stage"] == "DOCS_READY"  # cascade link 4


class TestReinstateAfterExpiry:
    def test_reinstate_at_or_after_expiry_rejected(self, api):
        """PRD §3.2: "reinstatement requires the institution to be `SUSPENDED` (`ERR_INVALID_STATE` otherwise) and requires the current logical-clock reading to be strictly before `certification_expires_at`; a reinstatement attempted at or after expiry is rejected with `ERR_CERTIFICATION_LAPSED`."
        PRD §3.2: "Lapse itself is not a manual act — when the ops epoch finds a `CERTIFIED` institution whose `certification_expires_at` has been reached by the logical clock, the institution moves to `LAPSED`."

        Design: Corner/validations/reinstate_after_expiry_rejected
        """
        ctx = setup_certified_institution()  # CERTIFIED 2026-05-01, expires 2028-05-01
        inst_id = ctx["institution"]["id"]
        suspend_institution(inst_id)
        set_clock("2028-06-01T00:00:00Z")

        resp = api.reinstate_partner_institution(inst_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_LAPSED)
        inst = get_institution(inst_id)
        assert inst["certification_status"] == "SUSPENDED", (
            "a SUSPENDED institution is not auto-lapsed; lapse fires only via the epoch"
        )


class TestCertificationLapseBoundary:
    def test_lapse_fires_exactly_at_expiry(self, api):
        """PRD §3.2: "when the ops epoch finds a `CERTIFIED` institution whose `certification_expires_at` has been reached by the logical clock, the institution moves to `LAPSED`."
        PRD §3.1: "`certified_at` is set to the current logical-clock reading, `certification_expires_at` is computed as `certified_at` plus twenty-four months"
        PRD §2.5: "The epoch returns a summary object with integer counts `checkpoints_evaluated`, `certifications_lapsed`, `events_completed`, and `follow_ups_due`."

        Design: Corner/cross_cutting_layers/certification_lapse_at_expiry_boundary
        """
        ctx = setup_certified_institution()  # certified at 2026-05-01 -> expires 2028-05-01
        inst_id = ctx["institution"]["id"]
        inst = get_institution(inst_id)
        assert str(inst["certification_expires_at"]).startswith("2028-05-01")

        set_clock("2028-04-30T00:00:00Z")
        run_ops_epoch()
        assert get_institution(inst_id)["certification_status"] == "CERTIFIED", (
            "one day before expiry the epoch leaves the institution CERTIFIED"
        )

        set_clock("2028-05-01T00:00:00Z")
        summary = run_ops_epoch()
        assert summary["certifications_lapsed"] == 1
        assert get_institution(inst_id)["certification_status"] == "LAPSED", (
            "at exactly expiry (reached) the epoch lapses the certification"
        )


class TestOccReviewCreate:
    def test_stale_institution_version_rejected_412(self, api):
        """PRD §2.6: "Because a successful review creation supersedes the institution's live review and advances the institution's `version`, a create that arrives carrying the previously observed version is acting on a stale view of the institution; if the supplied value does not match the institution's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_review_create_412
        """
        std = setup_effective_standard()
        inst = create_institution()
        stale_version = inst["version"]

        rev1 = open_review(inst, std["id"],
                           expected_institution_version=stale_version)

        resp = api.create_certification_review(
            {
                "institution_id": inst["id"],
                "standard_id": std["id"],
                "period_start": "2026-04-01",
                "period_end": "2026-04-30",
                "expected_institution_version": stale_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        review1 = get_success_data(api.get_certification_review(rev1["id"], ADMIN))
        assert review1["status"] == "DRAFT", "the failed create supersedes nothing"
        assert get_institution(inst["id"])["version"] == stale_version + 1, (
            "exactly one successful review create bumped the institution version"
        )


class TestReviewGapBuffer:
    def test_period_start_one_day_inside_buffer_rejected(self, api):
        """PRD §3.1: "Reviews for the same institution are spaced: excluding any review in `SUPERSEDED`, the new review's `period_start` must be at least thirty days after the latest prior review's `period_end`, with equality allowed; a tighter spacing is rejected with `ERR_REVIEW_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/review_window_min_gap_buffer
        """
        ctx = setup_certified_institution()  # prior review period_end 2026-02-28
        inst_id = ctx["institution"]["id"]
        current_version = get_institution(inst_id)["version"]

        resp = api.create_certification_review(
            {
                "institution_id": inst_id,
                "standard_id": ctx["standard"]["id"],
                "period_start": "2026-03-29",  # 29 days after 2026-02-28
                "period_end": "2026-04-15",
                "expected_institution_version": current_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_GAP_VIOLATION)

    def test_period_start_exactly_thirty_days_after_allowed(self, api):
        """PRD §3.1: "the new review's `period_start` must be at least thirty days after the latest prior review's `period_end`, with equality allowed; a tighter spacing is rejected with `ERR_REVIEW_GAP_VIOLATION`."
        PRD §2.6: "if the supplied value does not match the institution's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/resource_temporal_overlap/review_window_min_gap_buffer
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        current_version = get_institution(inst_id)["version"]

        # A gap-rejected create mutates nothing: the same version still passes OCC.
        api.create_certification_review(
            {
                "institution_id": inst_id,
                "standard_id": ctx["standard"]["id"],
                "period_start": "2026-03-29",
                "period_end": "2026-04-15",
                "expected_institution_version": current_version,
            },
            ADMIN,
        )
        resp = api.create_certification_review(
            {
                "institution_id": inst_id,
                "standard_id": ctx["standard"]["id"],
                "period_start": "2026-03-30",  # == period_end + 30 days, equality allowed
                "period_end": "2026-04-30",
                "expected_institution_version": current_version,
            },
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["period_start"] == "2026-03-30"
