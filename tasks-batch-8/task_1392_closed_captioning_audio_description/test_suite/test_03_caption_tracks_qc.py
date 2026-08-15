"""Caption tracks and accuracy QC: dual review modes, rounding boundaries, the
cyclic rework loop with its iteration cap, version supersede cardinality, OCC,
and the review single-shot / state gates (PRD §2.5, §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_caption_track,
    assert_qc_review,
    confirm_order,
    conform_track,
    create_cleared_media,
    create_client,
    create_track,
    create_work_order,
    deliver_order,
    file_complaint,
    finalize_qc,
    get_success_data,
    make_client_headers,
    make_editor_headers,
    make_ops_headers,
    make_qc_headers,
    quote_order,
    set_clock,
    setup_conformed_caption_track,
    setup_in_production_order,
    setup_track_in_qc_queue,
    start_production,
    track_submit_and_enqueue,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import EDITOR, INTAKE, OPS

MONDAY = "2026-08-03T10:00:00Z"


class TestAccuracyDualVariant:
    """Difficulty: twin INTERNAL tracks, identical weighted-error profile per
    thousand words, scored under FULL_REVIEW vs SAMPLED_REVIEW."""

    def _two_queued_tracks(self, api):
        set_clock(MONDAY)
        ctx_a = setup_track_in_qc_queue(compliance_standard="INTERNAL",
                                        turnaround_tier="STANDARD",
                                        client_name="Internal Client")
        client = ctx_a["client"]
        m_b = create_cleared_media(client["id"], title="Prog B", duration_seconds=3600)
        wo_b = create_work_order(client["id"], m_b["id"], turnaround_tier="STANDARD")
        quote_order(wo_b["id"])
        confirm_order(wo_b["id"], client["id"])
        start_production(wo_b["id"])
        t_b = create_track(wo_b["id"], author="editor-1")
        track_submit_and_enqueue(t_b["id"], author="editor-1")
        return ctx_a["track"]["id"], t_b["id"]

    def test_full_review_passes_at_internal_threshold(self, api):
        """PRD §3.4: "The accuracy denominator is `total_words` under
        `FULL_REVIEW` and `sampled_words` under `SAMPLED_REVIEW`".
        PRD §3.4: "The `outcome` is `PASS` when `accuracy_pct` is at least
        `threshold_pct` — the comparison is inclusive — and `FAIL` otherwise."

        Design: Difficulty/dual_variant_calc/accuracy_mode_full_vs_sampled
        """
        t_a, _ = self._two_queued_tracks(api)
        review = validate_success(api.create_qc_review(
            t_a, {"review_mode": "FULL_REVIEW", "total_words": 10000,
                  "minor_errors": 450, "major_errors": 10, "critical_errors": 1},
            make_qc_headers("qc-1")), expected_status=201)
        assert_qc_review(review)
        # weighted 450 + 30 + 10 = 490; (1 - 490/10000) * 100 = 95.10 >= 95.00.
        assert float(review["accuracy_pct"]) == pytest.approx(95.10, abs=1e-9)
        assert review["outcome"] == "PASS"
        track = validate_success(api.get_caption_track(t_a, EDITOR))
        assert track["track_status"] == "QC_PASSED"

    def test_sampled_review_flips_outcome(self, api):
        """PRD §3.4: "identical error counts and `total_words` therefore yield
        different accuracies across the two modes whenever the sample is smaller
        than the whole track."
        PRD §3.3: "a `FAIL` moves `QC_QUEUED` → `QC_FAILED`, increments
        `qc_attempts` by one, records `last_accuracy_pct` the same way".

        Design: Difficulty/dual_variant_calc/accuracy_mode_full_vs_sampled
        """
        _, t_b = self._two_queued_tracks(api)
        review = validate_success(api.create_qc_review(
            t_b, {"review_mode": "SAMPLED_REVIEW", "total_words": 10000,
                  "sampled_words": 2000, "minor_errors": 110, "major_errors": 3,
                  "critical_errors": 1},
            make_qc_headers("qc-1")), expected_status=201)
        # sampled denominator 2000: weighted 110 + 9 + 10 = 129 -> 93.55 < 95.00.
        assert float(review["accuracy_pct"]) == pytest.approx(93.55, abs=1e-9)
        assert review["outcome"] == "FAIL"
        track = validate_success(api.get_caption_track(t_b, EDITOR))
        assert track["track_status"] == "QC_FAILED"
        assert track["qc_attempts"] == 1


class TestAccuracyRoundingBoundary:
    """Difficulty: raw 98.995 rounds HALF_UP to 99.00 (PASS at the inclusive FCC
    threshold); raw 98.994 rounds to 98.99 (FAIL)."""

    def _fcc_queued_pair(self, api):
        set_clock(MONDAY)
        ctx_a = setup_track_in_qc_queue(compliance_standard="FCC_BROADCAST",
                                        client_name="FCC Client")
        client = ctx_a["client"]
        m_b = create_cleared_media(client["id"], title="B", duration_seconds=3600)
        wo_b = create_work_order(client["id"], m_b["id"], turnaround_tier="STANDARD")
        quote_order(wo_b["id"])
        confirm_order(wo_b["id"], client["id"])
        start_production(wo_b["id"])
        t_b = create_track(wo_b["id"], author="editor-1")
        track_submit_and_enqueue(t_b["id"], author="editor-1")
        return ctx_a["track"]["id"], t_b["id"]

    def test_raw_98995_rounds_half_up_and_passes(self, api):
        """PRD §3.4: "Because rounding happens once before comparison, a raw
        value of 98.995 rounds to 99.00 and passes the `FCC_BROADCAST`
        threshold."
        PRD §3.4: "The `threshold_pct` comes from the owning client's
        `compliance_standard`: 99.00 for `FCC_BROADCAST`, 98.50 for
        `SECTION_508`, 95.00 for `INTERNAL`."

        Design: Difficulty/boundary_precision_check/accuracy_rounding_boundary_straddle
        """
        t_a, _ = self._fcc_queued_pair(api)
        review = validate_success(api.create_qc_review(
            t_a, {"review_mode": "FULL_REVIEW", "total_words": 20000,
                  "minor_errors": 201, "major_errors": 0, "critical_errors": 0},
            make_qc_headers("qc-1")), expected_status=201)
        assert float(review["accuracy_pct"]) == pytest.approx(99.00, abs=1e-9)
        assert review["outcome"] == "PASS"
        track = validate_success(api.get_caption_track(t_a, EDITOR))
        assert track["track_status"] == "QC_PASSED"

    def test_raw_98994_rounds_down_and_fails(self, api):
        """PRD §3.4: "The review's `accuracy_pct` is one minus the weighted
        errors divided by the denominator, the result multiplied by one hundred,
        computed in exact decimal arithmetic and rounded half-up to two decimal
        places in a single final rounding step."
        PRD §3.4: "The `outcome` is `PASS` when `accuracy_pct` is at least
        `threshold_pct` — the comparison is inclusive — and `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/accuracy_rounding_boundary_straddle
        """
        _, t_b = self._fcc_queued_pair(api)
        review = validate_success(api.create_qc_review(
            t_b, {"review_mode": "FULL_REVIEW", "total_words": 50000,
                  "minor_errors": 503, "major_errors": 0, "critical_errors": 0},
            make_qc_headers("qc-1")), expected_status=201)
        assert float(review["accuracy_pct"]) == pytest.approx(98.99, abs=1e-9)
        assert review["outcome"] == "FAIL"
        track = validate_success(api.get_caption_track(t_b, EDITOR))
        assert track["track_status"] == "QC_FAILED"
        assert float(track["last_accuracy_pct"]) == pytest.approx(98.99, abs=1e-9)


class TestQcReworkCycle:
    """Difficulty: the AUTHORING -> QC_FAILED -> AUTHORING loop re-enters twice
    and the third FAIL lands in terminal QC_FAILED_PERMANENT."""

    def _drive_fail(self, api, track_id, minor_errors):
        track_submit_and_enqueue(track_id, author="editor-1")
        finalize_qc(track_id, reviewer="qc-1", minor_errors=minor_errors)

    def test_two_rework_cycles_succeed(self, api):
        """PRD §3.3: "a `FAIL` moves `QC_QUEUED` → `QC_FAILED`, increments
        `qc_attempts` by one, records `last_accuracy_pct` the same way".
        PRD §3.3: "Rework moves `QC_FAILED` → `AUTHORING`, but only while
        `qc_attempts` is below three".

        Design: Difficulty/non_linear_state_machine/caption_track_qc_rework_cycle
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="INTERNAL")
        t = ctx["track"]["id"]
        # FAIL #1: 600/10000 -> 94.00 < 95.00.
        finalize_qc(t, reviewer="qc-1", minor_errors=600)
        track = validate_success(api.get_caption_track(t, EDITOR))
        assert track["track_status"] == "QC_FAILED"
        assert track["qc_attempts"] == 1
        reworked = validate_success(api.begin_rework(t, make_editor_headers("editor-1")))
        assert reworked["track_status"] == "AUTHORING"
        # FAIL #2: 550/10000 -> 94.50 < 95.00.
        self._drive_fail(api, t, 550)
        track = validate_success(api.get_caption_track(t, EDITOR))
        assert track["track_status"] == "QC_FAILED"
        assert track["qc_attempts"] == 2
        reworked = validate_success(api.begin_rework(t, make_editor_headers("editor-1")))
        assert reworked["track_status"] == "AUTHORING"

    def test_third_fail_is_terminal_and_rework_rejected(self, api):
        """PRD §3.3: "once the third failure lands the track is already
        `QC_FAILED_PERMANENT` and terminal, so a rework attempt there is
        rejected as an invalid transition with `ERR_INVALID_TRANSITION`
        (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/caption_track_qc_rework_cycle
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="INTERNAL")
        t = ctx["track"]["id"]
        # The fixture already left the track QC_QUEUED, so FAIL #1 finalizes
        # directly; only post-rework cycles need submit+enqueue (_drive_fail).
        finalize_qc(t, reviewer="qc-1", minor_errors=600)   # FAIL #1 (94.00)
        get_success_data(api.begin_rework(t, make_editor_headers("editor-1")))
        self._drive_fail(api, t, 550)   # FAIL #2 (94.50)
        get_success_data(api.begin_rework(t, make_editor_headers("editor-1")))
        self._drive_fail(api, t, 520)   # FAIL #3 (94.80) -> terminal
        track = validate_success(api.get_caption_track(t, EDITOR))
        assert track["track_status"] == "QC_FAILED_PERMANENT"
        assert track["qc_attempts"] == 3
        resp = api.begin_rework(t, make_editor_headers("editor-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


class TestVersionCardinality:
    """Difficulty: exactly one current (non-terminal) caption version per work
    order across a direct supersede and a remediation round."""

    def test_direct_supersede_supersedes_prior(self, api):
        """PRD §3.3: "Creation stamps `author_user_id` with the acting editor's
        `X-User-ID`, increments the work order's `version` by one, moves any
        prior current track to `SUPERSEDED`, and assigns the new track a
        `version_no` one greater than the prior current version (or one for the
        first)."

        Design: Difficulty/compensating_invariant/current_version_cardinality_invariant
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL")
        wo_id = ctx["work_order"]["id"]
        t_1 = create_track(wo_id, author="editor-1")
        t_2 = create_track(wo_id, author="editor-1", speaker_id_style="CHEVRON",
                           supersedes_track_id=t_1["id"])
        assert t_2["version_no"] == 2
        old = validate_success(api.get_caption_track(t_1["id"], EDITOR))
        assert old["track_status"] == "SUPERSEDED"
        listing = get_success_data(
            api.list_caption_tracks(OPS, params={"work_order_id": wo_id}))
        assert len(listing) == 2
        live = [t for t in listing
                if t["track_status"] not in ("SUPERSEDED", "ARCHIVED", "QC_FAILED_PERMANENT")]
        assert len(live) == 1 and live[0]["id"] == t_2["id"], (
            "exactly one current version must exist after the supersede"
        )

    def test_remediation_round_extends_version_chain(self, api):
        """PRD §3.8: "For a caption subject, the system creates a new remediation
        caption track: its `version_no` is the disputed track's plus one, it
        lands in `AUTHORING`, its `supersedes_track_id` points at the disputed
        track, its `author_user_id` is the acting user, and the complaint's
        `remediation_track_id` is set to it while the disputed track moves
        `DISPUTED` → `SUPERSEDED`."
        PRD §3.2: "When remediation begins the order returns `REMEDIATION` →
        `IN_PRODUCTION`".

        Design: Difficulty/compensating_invariant/current_version_cardinality_invariant
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL")
        wo_id = ctx["work_order"]["id"]
        t_1 = create_track(wo_id, author="editor-1")
        t_2 = create_track(wo_id, author="editor-1", speaker_id_style="CHEVRON",
                           supersedes_track_id=t_1["id"])
        track_submit_and_enqueue(t_2["id"], author="editor-1")
        finalize_qc(t_2["id"], minor_errors=100)
        conform_track(t_2["id"], author="editor-1")
        deliver_order(wo_id)

        comp = file_complaint(ctx["client"]["id"], description="timing drift",
                              caption_track_id=t_2["id"])
        get_success_data(api.triage_complaint(comp["id"], OPS))
        comp = get_success_data(
            api.begin_remediation(comp["id"], make_ops_headers("ops-1")))
        t_3_id = comp["remediation_track_id"]
        assert t_3_id, "remediation_track_id must be set"
        t_3 = validate_success(api.get_caption_track(t_3_id, EDITOR))
        assert t_3["track_status"] == "AUTHORING"
        assert t_3["version_no"] == 3
        assert t_3["supersedes_track_id"] == t_2["id"]
        assert t_3["author_user_id"] == "ops-1"
        old = validate_success(api.get_caption_track(t_2["id"], EDITOR))
        assert old["track_status"] == "SUPERSEDED"
        listing = get_success_data(
            api.list_caption_tracks(OPS, params={"work_order_id": wo_id}))
        assert len(listing) == 3
        live = [t for t in listing
                if t["track_status"] not in ("SUPERSEDED", "ARCHIVED", "QC_FAILED_PERMANENT")]
        assert len(live) == 1 and live[0]["id"] == t_3_id
        wo = validate_success(api.get_work_order(wo_id, OPS))
        assert wo["order_status"] == "IN_PRODUCTION"


class TestQcShapeAndGates:
    def test_qc_review_immutable_shape(self, api):
        """PRD §2.4: "The single exception is `QCReview`: a finalized review is
        an immutable measurement record and carries only `id` and `created_at` —
        both `updated_at` and `version` are absent from it."
        PRD §3.4: "The `threshold_pct` comes from the owning client's
        `compliance_standard`: 99.00 for `FCC_BROADCAST`, 98.50 for
        `SECTION_508`, 95.00 for `INTERNAL`."

        Design: Corner/entities/qc_review_immutable_shape
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="INTERNAL")
        review = validate_success(api.create_qc_review(
            ctx["track"]["id"],
            {"review_mode": "FULL_REVIEW", "total_words": 10000,
             "minor_errors": 100, "major_errors": 0, "critical_errors": 0},
            make_qc_headers("qc-1")), expected_status=201)
        assert_qc_review(review)
        assert "version" not in review and "updated_at" not in review
        assert float(review["accuracy_pct"]) == pytest.approx(99.00, abs=1e-9)
        assert review["outcome"] == "PASS"

    def test_sampled_review_below_minimum_ratio_rejected(self, api):
        """PRD §3.4: "`sampled_words` is required when the mode is
        `SAMPLED_REVIEW` and must be at least the value of `total_words`
        multiplied by 0.20 and rounded up; it is the denominator for sampled
        accuracy."
        PRD §2.4: "then request shape and field constraints (`ERR_VALIDATION`)".

        Design: Corner/validations/sampled_review_below_minimum_ratio_rejected
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="INTERNAL")
        resp = api.create_qc_review(
            ctx["track"]["id"],
            {"review_mode": "SAMPLED_REVIEW", "total_words": 10000,
             "sampled_words": 1999, "minor_errors": 0, "major_errors": 0,
             "critical_errors": 0},
            make_qc_headers("qc-1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        track = validate_success(api.get_caption_track(ctx["track"]["id"], EDITOR))
        assert track["track_status"] == "QC_QUEUED"

    def test_sampled_review_on_fcc_rejected(self, api):
        """PRD §3.4: "For an `FCC_BROADCAST` client only `FULL_REVIEW` is
        permitted — a sampled review there is rejected with
        `ERR_REVIEW_MODE_NOT_PERMITTED`; `SECTION_508` and `INTERNAL` clients
        may use either mode."

        Design: Corner/validations/sampled_review_on_fcc_rejected
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="FCC_BROADCAST",
                                      client_name="FCC Co")
        resp = api.create_qc_review(
            ctx["track"]["id"],
            {"review_mode": "SAMPLED_REVIEW", "total_words": 10000,
             "sampled_words": 5000, "minor_errors": 0, "major_errors": 0,
             "critical_errors": 0},
            make_qc_headers("qc-1"))
        validate_error(resp, ApiErrorId.ERR_REVIEW_MODE_NOT_PERMITTED)

    def test_qc_second_review_rejected(self, api):
        """PRD §3.3: "A finalized QC review (§3.4) drives the outcome: a `PASS`
        moves `QC_QUEUED` → `QC_PASSED`".
        PRD §2.4: "then state-machine admissibility (`ERR_INVALID_TRANSITION`)".

        Design: Corner/state_machines/qc_second_review_rejected
        """
        set_clock(MONDAY)
        ctx = setup_track_in_qc_queue(compliance_standard="INTERNAL")
        t = ctx["track"]["id"]
        first = validate_success(api.create_qc_review(
            t, {"review_mode": "FULL_REVIEW", "total_words": 10000,
                "minor_errors": 100, "major_errors": 0, "critical_errors": 0},
            make_qc_headers("qc-1")), expected_status=201)
        assert float(first["accuracy_pct"]) == pytest.approx(99.00, abs=1e-9)
        track = validate_success(api.get_caption_track(t, EDITOR))
        assert track["track_status"] == "QC_PASSED"
        resp = api.create_qc_review(
            t, {"review_mode": "FULL_REVIEW", "total_words": 10000,
                "minor_errors": 0, "major_errors": 0, "critical_errors": 0},
            make_qc_headers("qc-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

    def test_track_submit_after_conformed_invalid(self, api):
        """PRD §3.3: "Submitting moves `AUTHORING` → `INTERNAL_REVIEW`".
        PRD §2.4: "then state-machine admissibility (`ERR_INVALID_TRANSITION`)".

        Design: Corner/state_machines/track_submit_after_conformed_invalid
        """
        set_clock(MONDAY)
        ctx = setup_conformed_caption_track(compliance_standard="INTERNAL")
        t = ctx["track"]["id"]
        resp = api.submit_review(t, make_editor_headers("editor-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        track = validate_success(api.get_caption_track(t, EDITOR))
        assert track["track_status"] == "CONFORMED"

    def test_submit_review_unknown_track_not_found(self, api):
        """PRD §2.4: "Requests are validated in a fixed order, and the first
        failing check determines the rejection: authentication of the two
        headers comes first, then role authorization, then resolution of path
        identifiers and body foreign keys from left to right (a dangling
        reference yields `ERR_NOT_FOUND`), then entity-backed ownership
        (`ERR_FORBIDDEN_OWNERSHIP`), then request shape and field constraints
        (`ERR_VALIDATION`), then optimistic concurrency, then state-machine
        admissibility (`ERR_INVALID_TRANSITION`), then segregation-of-duties and
        compliance rules, then temporal windows, then capacity and geometry
        constraints, and finally linked-entity state preconditions."

        Design: Corner/validations/submit_review_unknown_track_not_found
        """
        resp = api.submit_review(NON_EXISTENT_UUID, EDITOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCaptionTrackOcc:
    def test_first_create_with_observed_version_succeeds(self, api):
        """PRD §2.5: "Creating a new caption track version requires the request
        to carry `expected_work_order_version` equal to the target work order's
        current `version`."
        PRD §3.3: "increments the work order's `version` by one".

        Design: Corner/cross_cutting_layers/occ_caption_track_create_stale
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL")
        wo = ctx["work_order"]
        before = wo["version"]
        t_1 = create_track(wo["id"], author="editor-1")
        assert_caption_track(t_1)
        after = validate_success(api.get_work_order(wo["id"], OPS))
        assert after["version"] == before + 1

    def test_second_create_with_stale_version_rejected(self, api):
        """PRD §2.5: "If another writer has advanced the work order's version
        since the client last read it, the create is rejected with
        `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), preventing a stale client
        from silently superseding a track version it never observed."

        Design: Corner/cross_cutting_layers/occ_caption_track_create_stale
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL")
        wo = ctx["work_order"]
        stale_v = wo["version"]
        t_1 = create_track(wo["id"], author="editor-1")
        resp = api.create_caption_track(
            wo["id"],
            {"language": "en-US", "caption_format": "SCC",
             "speaker_id_style": "CHEVRON", "expected_work_order_version": stale_v},
            make_editor_headers("editor-2"))
        validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION)
        listing = get_success_data(
            api.list_caption_tracks(OPS, params={"work_order_id": wo["id"]}))
        assert len(listing) == 1 and listing[0]["id"] == t_1["id"], (
            "the rejected create must not supersede the observed track"
        )
        track = validate_success(api.get_caption_track(t_1["id"], EDITOR))
        assert track["track_status"] == "AUTHORING"
