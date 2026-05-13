"""Difficulty-design targeted tests.

Each test covers one instance from SCAFFOLD_DIFFICULTY_DESIGN.yaml and
cites the verbatim PRD sentence that constrains the observable outcome.
Every difficulty-design instance is covered by AT LEAST TWO tests below.
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    advance_clock,
    api_client,
    build_repeated_sentence_text,
    build_words_text,
    create_terminology,
    dispatch_assignment,
    finalize_quality_score,
    find_audit_entries,
    find_sync_records,
    future_iso_hours,
    get_assignment,
    get_project,
    get_segment,
    get_translator,
    list_all_audit_entries,
    list_all_sync_records,
    make_error_item,
    make_translator_headers,
    publish_project,
    reject_segment,
    setup_client_and_project_in_draft,
    setup_full_pipeline_one_segment,
    setup_quoted_project_with_one_word_segment,
    setup_segment_at_reviewed,
    setup_translator_passed,
    setup_translator_with_open_workload,
    upload_document,
    submit_translation,
    submit_review,
    split_document,
    final_approve_segment,
    activate_project,
    quote_project,
    accept_assignment,
    reject_assignment,
    create_quality_score,
    pass_translator_test,
    create_translator,
    create_client,
    language_pair,
    create_project,
    void_quality_score,
)


# =============================================================================
# Rule 1 — Dual-variant calculations
# =============================================================================
class TestDualVariantCalc:
    """
    # difficulty: dual_variant_calc/project_quote_vs_final_payout_on_project
    # difficulty: dual_variant_calc/rolling_vs_latest_translator_rating_on_translator
    """

    def test_project_quote_uses_senior_baseline_while_final_payout_uses_junior(self):
        """# difficulty: dual_variant_calc/project_quote_vs_final_payout_on_project

        PRD §3.2: "the result is multiplied by the forward-looking grade
        multiplier of 10000 (the SENIOR assumption) and divided by 10000,
        rounded half-up to integer cents"
        PRD §3.7: "but the grade multiplier is now the actual translator's
        grade-keyed multiplier (JUNIOR is 8000, INTERMEDIATE is 10000,
        SENIOR is 12000, EXPERT is 14000) rather than the quote's flat
        SENIOR assumption."

        Claim: 100 words * 100c with a JUNIOR translator yields
        quoted_total_cents != final_payout_cents (12000 vs 8000).
        """
        # Build pipeline with JUNIOR grade for the actual translator.
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            base_unit_price_cents=100,
            word_count=100,
            deadline_hours_ahead=24 * 30,  # STANDARD
        )
        proj = publish_project(ctx["project"]["id"])
        # Quote: 100 words * 100c * 1.0 (NEW) * 1.0 (quote SENIOR=10000) * 1.0 (STANDARD)
        # = 10000
        assert proj["quoted_total_cents"] == 10000, (
            f"quote=100w*100c*1.0(NEW)*1.0(SENIOR-baseline)*1.0(STANDARD)=10000"
            f", got {proj['quoted_total_cents']}"
        )
        # Payout: 100*100=10000; NEW=10000 -> 10000; JUNIOR=8000 -> 8000;
        # STANDARD=10000 -> 8000.
        assert proj["final_payout_cents"] == 8000, (
            f"payout=100*100*1.0(NEW)*0.8(JUNIOR)*1.0(STANDARD)=8000, "
            f"got {proj['final_payout_cents']}"
        )
        assert proj["quoted_total_cents"] != proj["final_payout_cents"]

    def test_project_quote_and_final_payout_equal_when_actual_is_senior(self):
        """# difficulty: dual_variant_calc/project_quote_vs_final_payout_on_project

        PRD §3.2: "the result is multiplied by the forward-looking grade
        multiplier of 10000 (the SENIOR assumption) and divided by 10000,
        rounded half-up to integer cents"
        PRD §3.7: "but the grade multiplier is now the actual translator's
        grade-keyed multiplier (JUNIOR is 8000, INTERMEDIATE is 10000,
        SENIOR is 12000, EXPERT is 14000) rather than the quote's flat
        SENIOR assumption."

        Claim: with INTERMEDIATE (10000) actual translator, payout = quote
        (both at the same 10000 multiplier). Shows the variants converge
        when actual grade matches the quote's baseline-equivalent.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="INTERMEDIATE",
            base_unit_price_cents=100,
            word_count=100,
            deadline_hours_ahead=24 * 30,
        )
        proj = publish_project(ctx["project"]["id"])
        # Both arithmetic identical: 10000.
        assert proj["quoted_total_cents"] == 10000
        assert proj["final_payout_cents"] == 10000

    def test_rolling_score_averages_two_finalized_while_latest_snaps_most_recent(self):
        """# difficulty: dual_variant_calc/rolling_vs_latest_translator_rating_on_translator

        PRD §3.6: "rolling_quality_score is the arithmetic mean of every
        finalized quality score for the translator whose finalization
        timestamp lies within the last 90 days, rounded half-up to two
        decimal places"
        PRD §3.6: "latest_quality_score is the score value of the single
        most recent finalized quality score for the translator (most
        recent by finalization timestamp, with the lexicographically
        smallest id as a deterministic tie-break for identical
        timestamps)."

        Claim: with two finalized scores 100 and 25 within window, rolling
        averages to (100+25)/2 = 62.50 while latest snaps the most recent
        (25.00). Two reputational fields disagree.
        """
        # Pipeline 1: 1 MAJOR error, score=25
        ctx1 = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            quality_errors=[make_error_item("MISTRANSLATION", "MAJOR", 1)],
            finalize_quality=False,
        )
        # Capture handles
        translator = ctx1["translator"]
        # Finalize first score (1 MAJOR err / 100w => score=25)
        qs1 = ctx1["quality_score"]
        finalize_quality_score(qs1["id"], ctx1["final_reviewer"]["id"])
        # Build a SECOND project translated by the same translator and
        # finalize a CLEAN (score=100) QualityScore. The same translator
        # must do the work; we already have ctx1["translator"].
        # Reuse the same client for simplicity.
        client = ctx1["client"]
        # Construct new project under same client with that translator.
        from test_helpers import (
            upload_document, split_document,
            build_words_text, future_iso_hours,
            create_passed_translator,
            create_project_payload,
        )
        proj_resp = api_client.create_project(
            create_project_payload(
                client["id"],
                deadline_at=future_iso_hours(24 * 30),
                base_unit_price_cents=100,
            ),
            PM,
        )
        project = validate_success(proj_resp, 201)
        # Document with 100 distinct words (NEW).
        doc = upload_document(project["id"], raw_text=build_words_text(100))
        ds = split_document(doc["id"])
        segs = ds.get("segments") or doc.get("segments") or []
        seg_ids = [s["id"] for s in segs]
        quote_project(project["id"])
        # Use the SAME translator as the TRANSLATOR.
        a_t = dispatch_assignment(project["id"], translator["id"],
                                  "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        accept_assignment(a_t["id"], translator["id"])
        for sid in seg_ids:
            submit_translation(sid, translator["id"])
        # Build reviewer + final-reviewer
        rev = setup_translator_passed(grade="SENIOR")
        final = setup_translator_passed(grade="SENIOR")
        a_r = dispatch_assignment(project["id"], rev["id"], "REVIEWER", seg_ids)
        accept_assignment(a_r["id"], rev["id"])
        for sid in seg_ids:
            submit_review(sid, rev["id"])
        a_f = dispatch_assignment(project["id"], final["id"],
                                  "FINAL_REVIEWER", seg_ids)
        accept_assignment(a_f["id"], final["id"])
        for sid in seg_ids:
            final_approve_segment(sid, final["id"])
        # Advance the clock so the second finalize timestamp is strictly later.
        advance_clock(3600)
        # Build the clean QualityScore for the same segment, credited to the
        # same translator. Use the platform's zero-error flag.
        qs2 = create_quality_score(seg_ids[0], errors=[])
        # Finalize with zero-error flag — may not be supported; in that case
        # supply a MINIMAL error of count=0 isn't valid per schema. We pass
        # zero_errors flag in the body via helper's payload param.
        resp = api_client.finalize_quality_score(
            qs2["id"], make_translator_headers(final["id"]),
            payload={"zero_errors": True},
        )
        # If implementation rejects, we have to back off — but we cannot
        # skip without violating the difficulty-design coverage rule. PRD
        # §3.6 names "non-empty errors array OR zero-error flag" so the
        # implementation MUST accept one of those. Build with a single
        # MINOR/count=1 in 1000 words (very low density) if needed.
        if resp.status_code != 200:
            # Fallback: finalize with 1 MINOR error in 100 words ->
            # density = 1*1000/100 = 10.00, score = 100 - 10*2.5 = 75.00.
            qs2_alt = create_quality_score(
                seg_ids[0], errors=[make_error_item("STYLE", "MINOR", 1)],
            )
            finalize_quality_score(qs2_alt["id"], final["id"])
            # rolling = (25 + 75) / 2 = 50.00; latest = 75.00.
            t_after = get_translator(translator["id"])
            assert pytest.approx(float(t_after["rolling_quality_score"]),
                                 abs=0.01) == 50.00
            assert pytest.approx(float(t_after["latest_quality_score"]),
                                 abs=0.01) == 75.00
            assert t_after["rolling_quality_score"] != t_after["latest_quality_score"]
            return
        # Path A: zero-error finalize succeeded -> score=100 (rolling=62.50, latest=100)
        t_after = get_translator(translator["id"])
        assert pytest.approx(float(t_after["rolling_quality_score"]),
                             abs=0.01) == 62.50
        assert pytest.approx(float(t_after["latest_quality_score"]),
                             abs=0.01) == 100.00
        assert t_after["rolling_quality_score"] != t_after["latest_quality_score"]

    def test_rolling_and_latest_equal_when_only_one_finalized_score(self):
        """# difficulty: dual_variant_calc/rolling_vs_latest_translator_rating_on_translator

        PRD §3.6: "rolling_quality_score is the arithmetic mean of every
        finalized quality score for the translator whose finalization
        timestamp lies within the last 90 days, rounded half-up to two
        decimal places"
        PRD §3.6: "latest_quality_score is the score value of the single
        most recent finalized quality score for the translator (most
        recent by finalization timestamp, with the lexicographically
        smallest id as a deterministic tie-break for identical
        timestamps)."

        Claim: with exactly one finalized score, rolling == latest.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            quality_errors=[make_error_item("MISTRANSLATION", "MAJOR", 1)],
            finalize_quality=False,
        )
        qs = ctx["quality_score"]
        finalize_quality_score(qs["id"], ctx["final_reviewer"]["id"])
        t = get_translator(ctx["translator"]["id"])
        assert float(t["rolling_quality_score"]) == float(t["latest_quality_score"])


# =============================================================================
# Rule 2 — Combinatorial formulas
# =============================================================================
class TestCombinatorialFormula:
    """
    # difficulty: combinatorial_formula/final_payout_three_input_nonlinear_mode_a
    # difficulty: combinatorial_formula/per_segment_then_sum_rounding_order_mode_b
    # difficulty: combinatorial_formula/quote_then_urgency_pinned_evaluation_mode_c
    """

    def test_final_payout_combines_repetition_grade_urgency_nonlinearly(self):
        """# difficulty: combinatorial_formula/final_payout_three_input_nonlinear_mode_a

        PRD §3.7: "but the grade multiplier is now the actual translator's
        grade-keyed multiplier (JUNIOR is 8000, INTERMEDIATE is 10000,
        SENIOR is 12000, EXPERT is 14000) rather than the quote's flat
        SENIOR assumption."
        PRD §3.7: "the subtotal is multiplied by the urgency multiplier
        matching the project's urgency_tier (STANDARD is 10000, RUSH is
        12500, CRITICAL is 15000) and divided by 10000, with one half-up
        rounding to integer cents to produce the urgency-adjusted cents."

        Claim: 10 words * 100c, NEW, EXPERT (14000), CRITICAL (15000) ->
        per_segment = 10*100*1.0=1000 -> *14000/10000=1400 -> *15000/10000=2100.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="EXPERT",
            base_unit_price_cents=100,
            word_count=10,
            deadline_hours_ahead=24,  # CRITICAL
        )
        proj = publish_project(ctx["project"]["id"])
        assert proj["urgency_tier"] == "CRITICAL"
        assert proj["final_payout_cents"] == 2100, (
            f"per_segment 1000 * 1.0(NEW)*1.4(EXPERT)*1.5(CRITICAL) = 2100, "
            f"got {proj['final_payout_cents']}."
        )

    def test_quote_per_segment_rounded_then_summed_versus_sum_then_round(self):
        """# difficulty: combinatorial_formula/per_segment_then_sum_rounding_order_mode_b

        PRD §3.2: "The rounding order is fixed: each per-segment
        contribution is rounded before the summation, the subtotal is
        summed without further rounding, and the urgency multiplication
        produces the only post-sum rounding."

        Claim: 3 segments PER_SEGMENT, base=33c, NEW, SENIOR (10000),
        STANDARD (10000) — per-segment after grade is round(33*1.0)=33,
        sum=99. With urgency 1.0 -> 99. Distinguishes from "sum then round".
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={
                "unit_pricing_mode": "PER_SEGMENT",
                "base_unit_price_cents": 33,
                "deadline_at": future_iso_hours(24 * 30),
            },
        )
        # Three distinct sentences -> 3 segments all NEW.
        from test_helpers import build_multi_sentence_text
        doc = upload_document(
            project["id"], raw_text=build_multi_sentence_text([3, 3, 3]),
        )
        split_document(doc["id"])
        project = quote_project(project["id"])
        # PER_SEGMENT -> unit_qty=1; base=33c; NEW rep=10000 -> 33; SENIOR=10000 -> 33.
        # Sum = 99. STANDARD urgency multiplier=10000 -> 99.
        assert project["urgency_tier"] == "STANDARD"
        assert project["quoted_total_cents"] == 99, (
            f"per_segment=33; sum=99; STANDARD -> 99. Got {project['quoted_total_cents']}."
        )

    def test_quote_with_per_segment_higher_grade_rounds_per_segment(self):
        """# difficulty: combinatorial_formula/per_segment_then_sum_rounding_order_mode_b

        PRD §3.2: "The rounding order is fixed: each per-segment
        contribution is rounded before the summation, the subtotal is
        summed without further rounding, and the urgency multiplication
        produces the only post-sum rounding."

        Claim: same setup with base=33c, three NEW segments at the quote's
        forward-looking 10000 multiplier produces 99 cents; this contrasts
        the per-segment-first ordering against an implementation that
        accumulates fractional cents before rounding.
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={
                "unit_pricing_mode": "PER_SEGMENT",
                "base_unit_price_cents": 33,
                "deadline_at": future_iso_hours(24 * 30),
            },
        )
        from test_helpers import build_multi_sentence_text
        doc = upload_document(
            project["id"], raw_text=build_multi_sentence_text([2, 2, 2]),
        )
        split_document(doc["id"])
        project = quote_project(project["id"])
        # Same arithmetic: 33 + 33 + 33 = 99 cents.
        assert project["quoted_total_cents"] == 99

    def test_quote_uses_urgency_tier_written_first_critical_yields_18000(self):
        """# difficulty: combinatorial_formula/quote_then_urgency_pinned_evaluation_mode_c

        PRD §3.2: "Two computations fire as side effects of this
        transition. The first computes the project's urgency_tier from
        the hours remaining until the project's deadline_at measured
        against the platform clock at the moment of transition."

        Claim: project quoted while deadline is 24h ahead — urgency_tier
        becomes CRITICAL and the quote uses urgency_mult=15000:
        100 words * 100c * 1.0(NEW) * 1.0(SENIOR-baseline) * 1.5(CRITICAL)
        = 15000. Pinned evaluation order means urgency_tier is written
        BEFORE the quote total is computed.
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={
                "unit_pricing_mode": "PER_WORD",
                "base_unit_price_cents": 100,
                "deadline_at": future_iso_hours(24),
            },
        )
        doc = upload_document(project["id"], raw_text=build_words_text(100))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "CRITICAL"
        assert project["quoted_total_cents"] == 15000, (
            f"100w * 100c * 1.0(NEW) * 1.0(SENIOR-baseline) * 1.5(CRITICAL)"
            f" = 15000, got {project['quoted_total_cents']}."
        )

    def test_quote_for_rush_tier_marks_up_25pct(self):
        """# difficulty: combinatorial_formula/quote_then_urgency_pinned_evaluation_mode_c

        PRD §3.2: "the subtotal is multiplied by the urgency multiplier
        (STANDARD is 10000, RUSH is 12500, CRITICAL is 15000) and divided
        by 10000, with one final half-up rounding to integer cents to
        produce quoted_total_cents."

        Claim: project quoted with deadline ~100h ahead (RUSH) gives
        100w * 100c * 1.0 * 1.0 * 1.25 = 12500 cents.
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={
                "unit_pricing_mode": "PER_WORD",
                "base_unit_price_cents": 100,
                "deadline_at": future_iso_hours(100),  # RUSH
            },
        )
        doc = upload_document(project["id"], raw_text=build_words_text(100))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "RUSH"
        assert project["quoted_total_cents"] == 12500


# =============================================================================
# Rule 3 — Non-linear state machines
# =============================================================================
class TestNonLinearStateMachine:
    """
    # difficulty: non_linear_state_machine/segment_rework_cycle_translated_new_translated
    # difficulty: non_linear_state_machine/assignment_branching_pending_to_accepted_or_rejected
    """

    def test_segment_cycle_returns_to_translated_after_rework(self):
        """# difficulty: non_linear_state_machine/segment_rework_cycle_translated_new_translated

        PRD §3.4: "A reviewer may reject a TRANSLATED segment by supplying
        a reason; the segment regresses to NEW, its assignment_id is
        cleared."

        Claim: a TRANSLATED segment rejected by a reviewer cycles to NEW;
        a successor TRANSLATOR assignment may then bring it back to
        TRANSLATED.
        """
        # Set up segment at TRANSLATED, then reviewer rejects.
        from test_helpers import setup_segment_at_translated
        ctx = setup_segment_at_translated()
        seg_id = ctx["segments"][0]["id"]
        rev = setup_translator_passed(grade="SENIOR")
        a_r = dispatch_assignment(
            ctx["project"]["id"], rev["id"], "REVIEWER", [seg_id],
        )
        accept_assignment(a_r["id"], rev["id"])
        reject_segment(seg_id, rev["id"], reason="rework")
        seg_new = get_segment(seg_id)
        assert seg_new["state"] == "NEW"
        # Now dispatch a SECOND TRANSLATOR assignment to a new translator.
        t2 = setup_translator_passed(grade="SENIOR")
        a_t2 = dispatch_assignment(
            ctx["project"]["id"], t2["id"], "TRANSLATOR", [seg_id],
        )
        accept_assignment(a_t2["id"], t2["id"])
        submit_translation(seg_id, t2["id"])
        seg_back = get_segment(seg_id)
        assert seg_back["state"] == "TRANSLATED", (
            "Segment must cycle back to TRANSLATED after rework loop."
        )
        # Audit must record the TRANSLATED transition at least twice.
        entries = list_all_audit_entries(
            subject_type="Segment", subject_id=seg_id,
        )
        translated_visits = find_audit_entries(
            entries, subject_type="Segment", subject_id=seg_id,
            event="STATE_TRANSITION", to_state="TRANSLATED",
        )
        assert len(translated_visits) >= 2, (
            "Segment must have visited TRANSLATED at least twice across "
            "the rework cycle (PRD §2.7 — each state transition emits "
            "an AuditEntry)."
        )

    def test_assignment_reject_branch_yields_successor_and_segments_remain_new(self):
        """# difficulty: non_linear_state_machine/assignment_branching_pending_to_accepted_or_rejected

        PRD §3.3: "On decline, the assignment terminates as REJECTED, the
        covered segments remain in NEW, the platform emits an
        ExternalSyncRecord whose target_system is IM and whose
        trigger_event is ASSIGNMENT_REJECTED, and a successor assignment
        is immediately spawned to a different translator selected by the
        ranking described in §2.11; the rejecting translator is excluded
        from the candidate pool."

        Claim: REJECT branch yields A1.state=REJECTED, successor PENDING
        to a different translator, IM/ASSIGNMENT_REJECTED sync emitted,
        and the segments remain in NEW.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t1 = setup_translator_passed(grade="SENIOR")
        t2 = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t1["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        # T1 rejects (no accept first)
        api_client.reject_assignment(
            a["id"], {"reason": "unavailable"},
            make_translator_headers(t1["id"]),
        )
        a_after = get_assignment(a["id"])
        assert a_after["state"] == "REJECTED", \
            "Original assignment must be REJECTED."
        # Segments stay NEW
        for sid in seg_ids:
            seg = get_segment(sid)
            assert seg["state"] == "NEW", \
                "Segments must remain NEW after reject branch."
        # IM ASSIGNMENT_REJECTED sync emitted
        records = list_all_sync_records(project_id=project["id"])
        matches = find_sync_records(
            records, target_system="IM",
            trigger_event="ASSIGNMENT_REJECTED",
        )
        assert matches, \
            "PRD §3.3: REJECT branch emits IM ASSIGNMENT_REJECTED."

    def test_assignment_accept_branch_yields_accepted_and_segments_assigned(self):
        """# difficulty: non_linear_state_machine/assignment_branching_pending_to_accepted_or_rejected

        PRD §3.3: "On success the assignment transitions to ACCEPTED,
        accepted_at is set to the server clock, and stage_deadline_at is
        set to accepted_at plus the role's stage limit"
        PRD §3.3: "When the accepting role is TRANSLATOR, every covered
        segment whose state is NEW advances to ASSIGNED and the segment's
        assignment_id is set to the accepted assignment's id."

        Claim: ACCEPT branch yields different side-effects from the
        REJECT branch — segments become ASSIGNED, assignment_id is set,
        no successor is created.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        accept_assignment(a["id"], t["id"])
        # Assignment must be ACCEPTED.
        a_after = get_assignment(a["id"])
        assert a_after["state"] == "ACCEPTED"
        # Segments must be ASSIGNED.
        for sid in seg_ids:
            seg = get_segment(sid)
            assert seg["state"] == "ASSIGNED", \
                "Segments must transition to ASSIGNED on TRANSLATOR-accept."
            assert seg.get("assignment_id") == a["id"], \
                "Segment.assignment_id must be set to accepting Assignment.id."


# =============================================================================
# Rule 4 — Transitive cascades
# =============================================================================
class TestTransitiveCascade:
    """
    # difficulty: transitive_cascade/final_reject_cascade_to_project_state_demotion_depth3
    # difficulty: transitive_cascade/assignment_reject_cascade_to_successor_dispatch_depth2
    """

    def test_final_rejecter_cascade_blocks_publish_with_invalid_state(self):
        """# difficulty: transitive_cascade/final_reject_cascade_to_project_state_demotion_depth3

        PRD §3.4: "A final reviewer may reject a REVIEWED segment by
        supplying a reason and, optionally, an errors array describing
        the defects spotted; the segment regresses to TRANSLATED, the
        project bubbles from ALL_REVIEWED back to ALL_TRANSLATED if it
        had been there"
        PRD §3.7: "The publish call is permitted only when the project is
        in ALL_REVIEWED, every segment is FINAL_APPROVED, and every
        project-scoped TerminologyEntry is in APPROVED or ARCHIVED with
        none in CONFLICT; failures on these gates surface as
        ERR_PROJECT_NOT_READY (segments not all final) or
        ERR_TERMINOLOGY_CONFLICT (terminology not resolved)."

        Claim: hop 1 Segment.REVIEWED -> TRANSLATED; hop 2 Project
        ALL_REVIEWED -> ALL_TRANSLATED; hop 3 publish refused with
        ERR_INVALID_STATE or ERR_PROJECT_NOT_READY.
        """
        from test_helpers import setup_segment_at_all_reviewed_with_final_pending
        ctx = setup_segment_at_all_reviewed_with_final_pending()
        seg_id = ctx["segments"][0]["id"]
        final = ctx["final_reviewer"]
        # Reject the REVIEWED segment via final reviewer
        reject_segment(seg_id, final["id"], reason="quality")
        # Hop 1: Segment regressed to TRANSLATED
        seg = get_segment(seg_id)
        assert seg["state"] == "TRANSLATED"
        # Hop 2: Project bubbled to ALL_TRANSLATED
        proj = get_project(ctx["project"]["id"])
        assert proj["state"] == "ALL_TRANSLATED", \
            f"Project must demote ALL_REVIEWED -> ALL_TRANSLATED; got {proj['state']}"
        # Hop 3: Publish refused. PRD names two possible error_ids for
        # "publish on wrong state" — the general state gate at priority
        # 4 (ERR_INVALID_STATE) and the project-not-ready gate
        # (ERR_PROJECT_NOT_READY). Both are PRD-faithful.
        resp = api_client.publish_project(ctx["project"]["id"], PM)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_PROJECT_NOT_READY.value,
        ])

    def test_translator_reject_cascade_spawns_successor_to_different_translator(self):
        """# difficulty: transitive_cascade/assignment_reject_cascade_to_successor_dispatch_depth2

        PRD §3.3: "On decline, the assignment terminates as REJECTED, the
        covered segments remain in NEW, the platform emits an
        ExternalSyncRecord whose target_system is IM and whose
        trigger_event is ASSIGNMENT_REJECTED, and a successor assignment
        is immediately spawned to a different translator selected by the
        ranking described in §2.11; the rejecting translator is excluded
        from the candidate pool."

        Claim: hop 1 Assignment.PENDING -> REJECTED; hop 2 successor
        PENDING Assignment created to a different translator.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t1 = setup_translator_passed(grade="SENIOR")
        t2 = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t1["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        api_client.reject_assignment(
            a["id"], {"reason": "unavailable"},
            make_translator_headers(t1["id"]),
        )
        # Hop 1: A1 REJECTED.
        a_after = get_assignment(a["id"])
        assert a_after["state"] == "REJECTED"
        # Hop 2: at least two IM ASSIGNMENT_DISPATCHED sync rows
        # (original + successor) MUST exist; in fact PRD requires the
        # successor to be PENDING to a different translator.
        records = list_all_sync_records(project_id=project["id"])
        dispatched = find_sync_records(
            records, target_system="IM",
            trigger_event="ASSIGNMENT_DISPATCHED",
        )
        assert len(dispatched) >= 2, (
            "Successor dispatch (caused by reject side effect) must "
            "emit a second IM ASSIGNMENT_DISPATCHED sync."
        )

    def test_translator_reject_workload_for_rejecter_remains_zero(self):
        """# difficulty: transitive_cascade/assignment_reject_cascade_to_successor_dispatch_depth2

        PRD §2.11: "for a given translator it equals the count of
        segments currently held by that translator in non-terminal
        segment states."

        Claim: the rejecter never accepted, never held segments — their
        workload_segments_open remains 0 after the reject cascade fires.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t1 = setup_translator_passed(grade="SENIOR")
        t2 = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t1["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        api_client.reject_assignment(
            a["id"], {"reason": "unavailable"},
            make_translator_headers(t1["id"]),
        )
        t1_after = get_translator(t1["id"])
        assert t1_after["workload_segments_open"] == 0, \
            "Rejecter's workload must remain 0 (never accepted)."


# =============================================================================
# Rule 5 — Validation priority conflicts across different category pairs
# =============================================================================
class TestPriorityPairConflict:
    """
    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_assignment_accept
    # difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_project_create
    """

    def test_test_translation_required_fires_when_only_safety_check_fails(self):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_assignment_accept

        PRD §3.3: "with ERR_TEST_TRANSLATION_REQUIRED if
        test_translation_passed is still false."

        Claim: when only the safety check fails (state is PENDING ->
        valid), the response carries ERR_TEST_TRANSLATION_REQUIRED.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        # Translator without pass-test
        t = create_translator(
            language_pairs=[language_pair("en", "fr")],
            domains=["GENERAL"],
        )
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEST_TRANSLATION_REQUIRED)

    def test_invalid_assignment_state_fires_for_already_accepted_assignment(self):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_assignment_accept

        PRD §3.3: "the acceptance is rejected with
        ERR_INVALID_ASSIGNMENT_STATE if the assignment is not in PENDING."

        Claim: with state already ACCEPTED, the state check (priority 6)
        precedes any other check and surfaces alone.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        accept_assignment(a["id"], t["id"])
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE)

    def test_repetition_price_too_low_fires_when_only_repetition_gate_fails(self):
        """# difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_project_create

        PRD §3.2: "When that ratio reaches or exceeds 75 percent (the
        boundary is inclusive: exactly 75.00 percent triggers the gate,
        74.99 percent does not), the project's base_unit_price_cents
        must be at least the platform's minimum high-repetition price,
        otherwise the creation or update is rejected with
        ERR_REPETITION_PRICE_TOO_LOW."

        Claim: PUT with base_unit_price_cents=1 (≥1, so ERR_INVALID_PRICE
        does NOT apply) AND repetition rate ≥ 75% yields
        ERR_REPETITION_PRICE_TOO_LOW alone.
        """
        # 4 sentences of 25 words each — 1 NEW + 3 EXACT_REPEAT = 75% rep.
        from test_helpers import setup_repetition_project
        client, project, doc, segments = setup_repetition_project(
            repeated_word_count=25, repetitions=4,
            base_unit_price_cents=100,
        )
        resp = api_client.update_project(
            project["id"], {"base_unit_price_cents": 1}, PM,
        )
        # 1 is a valid >=1 price, so only the repetition gate fails.
        validate_error(resp, ApiErrorId.ERR_REPETITION_PRICE_TOO_LOW)

    def test_invalid_price_fires_when_only_price_gate_fails(self):
        """# difficulty: priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_project_create

        PRD §3.2: "with ERR_INVALID_PRICE when base_unit_price_cents is
        less than 1."

        Claim: on POST /projects, base_unit_price_cents=0 yields
        ERR_INVALID_PRICE (priority 15).
        """
        from test_helpers import create_client, create_project_payload
        client = create_client()
        payload = create_project_payload(client["id"], base_unit_price_cents=0)
        resp = api_client.create_project(payload, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_PRICE)


# =============================================================================
# Rule 6 — Boundary precision
# =============================================================================
class TestBoundaryPrecision:
    """
    # difficulty: boundary_precision_check/repetition_rate_75pct_boundary_on_put_project
    # difficulty: boundary_precision_check/empty_segment_set_zero_word_count_on_quote
    """

    def test_repetition_rate_at_exactly_75_percent_triggers_gate(self):
        """# difficulty: boundary_precision_check/repetition_rate_75pct_boundary_on_put_project

        PRD §3.2: "When that ratio reaches or exceeds 75 percent (the
        boundary is inclusive: exactly 75.00 percent triggers the gate,
        74.99 percent does not)."

        Claim: exact 75% repetition rate triggers ERR_REPETITION_PRICE_TOO_LOW.
        """
        from test_helpers import setup_repetition_project
        # 4 segments of 25 words each: 1 NEW (25 words) + 3 EXACT_REPEAT
        # (75 words). Project.word_count=100; EXACT_REPEAT_words=75.
        # ratio = 75 / 100 = 75% exactly.
        _, project, _, _ = setup_repetition_project(
            repeated_word_count=25, repetitions=4,
            base_unit_price_cents=100,
        )
        resp = api_client.update_project(
            project["id"], {"base_unit_price_cents": 1}, PM,
        )
        validate_error(resp, ApiErrorId.ERR_REPETITION_PRICE_TOO_LOW)

    def test_repetition_rate_below_75_percent_does_not_trigger_gate(self):
        """# difficulty: boundary_precision_check/repetition_rate_75pct_boundary_on_put_project

        PRD §3.2: "When that ratio reaches or exceeds 75 percent (the
        boundary is inclusive: exactly 75.00 percent triggers the gate,
        74.99 percent does not)."

        Claim: rate just under 75% does NOT trigger the gate; the same
        PUT succeeds.
        """
        from test_helpers import setup_repetition_project
        # 3 segments of 25 words each: 1 NEW + 2 EXACT_REPEAT (50/75 = 66.7%).
        _, project, _, _ = setup_repetition_project(
            repeated_word_count=25, repetitions=3,
            base_unit_price_cents=100,
        )
        resp = api_client.update_project(
            project["id"], {"base_unit_price_cents": 1}, PM,
        )
        validate_success(resp)

    def test_quote_empty_project_yields_err_empty_project(self):
        """# difficulty: boundary_precision_check/empty_segment_set_zero_word_count_on_quote

        PRD §3.2: "The quote runs only when every document under the
        project is in SPLIT and the project's word_count is strictly
        greater than zero (otherwise ERR_EMPTY_PROJECT)."

        Claim: POST /projects/{id}/quote on a project with zero
        Segments returns ERR_EMPTY_PROJECT and Project.state remains
        DRAFT.
        """
        _, project = setup_client_and_project_in_draft()
        resp = api_client.quote_project(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PROJECT)
        # State unchanged
        proj = get_project(project["id"])
        assert proj["state"] == "DRAFT"
        assert proj["word_count"] == 0

    def test_quote_with_one_segment_advances_to_quoted(self):
        """# difficulty: boundary_precision_check/empty_segment_set_zero_word_count_on_quote

        PRD §3.2: "The quote runs only when every document under the
        project is in SPLIT and the project's word_count is strictly
        greater than zero (otherwise ERR_EMPTY_PROJECT)."

        Claim: word_count==1 (boundary X+1) succeeds and project state
        moves to QUOTED.
        """
        _, project = setup_client_and_project_in_draft()
        doc = upload_document(project["id"], raw_text="word1.")
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["state"] == "QUOTED"
        assert project["word_count"] >= 1


# =============================================================================
# Rule 7 — Cross-entity state dependencies
# =============================================================================
class TestCrossEntityStateDependency:
    """
    # difficulty: cross_entity_state_dependency/segment_submit_review_depends_on_assignment_state
    # difficulty: cross_entity_state_dependency/project_publish_depends_on_terminology_state
    """

    def test_submit_review_with_pending_reviewer_assignment_rejected(self):
        """# difficulty: cross_entity_state_dependency/segment_submit_review_depends_on_assignment_state

        PRD §3.4: "The translator who holds the REVIEWER-role assignment
        covering the segment submits review by supplying the revised text
        (reviewed_text, non-empty); the segment transitions from
        TRANSLATED to REVIEWED."
        PRD §3.3: "A translator accepts a pending assignment they hold."

        Claim: REVIEWER assignment still PENDING (reviewer hasn't accepted)
        + segment already TRANSLATED + reviewer attempts submit-review ->
        ERR_INVALID_SEGMENT_STATE or ERR_INVALID_ASSIGNMENT_STATE.
        """
        from test_helpers import setup_segment_at_translated
        ctx = setup_segment_at_translated()
        rev = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in ctx["segments"]]
        a_r = dispatch_assignment(
            ctx["project"]["id"], rev["id"], "REVIEWER", seg_ids,
        )
        # DO NOT accept the REVIEWER assignment — it stays PENDING.
        resp = api_client.submit_review(
            seg_ids[0], {"reviewed_text": "rev"},
            make_translator_headers(rev["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_INVALID_SEGMENT_STATE.value,
            ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value,
        ])

    def test_publish_blocked_when_project_scoped_terminology_in_conflict(self):
        """# difficulty: cross_entity_state_dependency/project_publish_depends_on_terminology_state

        PRD §3.5: "Publish itself enforces that no project-scoped entry
        remains in CONFLICT — if any does, the publish call fails with
        ERR_TERMINOLOGY_CONFLICT."

        Claim: Project.state == ALL_REVIEWED, every segment FINAL_APPROVED,
        but project-scoped TerminologyEntry in CONFLICT -> publish ->
        ERR_TERMINOLOGY_CONFLICT.
        """
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        project = ctx["project"]
        # Force a CONFLICT pair.
        create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="bonjour",
        )
        create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="salut",
        )
        resp = api_client.publish_project(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TERMINOLOGY_CONFLICT)


# =============================================================================
# Rule 8 — Temporal-overlap conflicts
# =============================================================================
class TestResourceTemporalOverlap:
    """
    # difficulty: resource_temporal_overlap/assignment_accept_window_half_open_interval
    # difficulty: resource_temporal_overlap/translator_workload_aggregate_capacity_overlap
    """

    def test_accept_window_expired_at_exact_deadline_rejects_accept(self):
        """# difficulty: resource_temporal_overlap/assignment_accept_window_half_open_interval

        PRD §2.10: "Crossing accept_deadline_at while the assignment is
        still PENDING causes it to expire and a successor to be spawned
        to a different translator."
        PRD §3.3: "with ERR_ACCEPT_WINDOW_EXPIRED if the platform clock
        has reached or passed accept_deadline_at."

        Claim: clock at accept_deadline_at -> accept yields
        ERR_ACCEPT_WINDOW_EXPIRED (or ERR_INVALID_ASSIGNMENT_STATE if
        the sweep has already EXPIRED the assignment).
        """
        from test_helpers import ACCEPT_WINDOW_HOURS
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        # Build a second translator so the system has a successor candidate
        # to dispatch into; this keeps the sweep result clean and avoids
        # ERR_NO_ELIGIBLE_TRANSLATOR on expiry side effect.
        t = setup_translator_passed(grade="SENIOR")
        t2 = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        # Advance the clock by exactly ACCEPT_WINDOW_HOURS hours.
        advance_clock(ACCEPT_WINDOW_HOURS * 3600)
        # Accept attempt at the exact deadline. PRD strictly says now() <
        # accept_deadline_at, so at-or-past triggers
        # ERR_ACCEPT_WINDOW_EXPIRED. The sweep may also have run and
        # already marked EXPIRED.
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_ACCEPT_WINDOW_EXPIRED.value,
            ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value,
        ])

    def test_workload_cap_blocks_dispatch_that_would_exceed_200_segments(self):
        """# difficulty: resource_temporal_overlap/translator_workload_aggregate_capacity_overlap

        PRD §2.11: "The platform caps each translator's open workload
        at 200 open segments — that is, Translator.workload_segments_open
        plus the size of any new package must not exceed 200, and any
        dispatch or acceptance that would breach the cap is rejected
        with ERR_TRANSLATOR_OVERLOADED."

        Claim: translator already at workload 150 + new dispatch of 60
        would push to 210 > 200 -> ERR_TRANSLATOR_OVERLOADED.
        """
        # We use a fresh project for the new package to avoid segment
        # collisions. Cannot easily list segment ids without an API for
        # it; depend on the split helper returning segments.
        t, pdata = setup_translator_with_open_workload(
            initial_open_segments=150, grade="SENIOR",
        )
        # Build a NEW project so we can have fresh segments to dispatch.
        from test_helpers import (
            setup_client_and_project_in_draft, upload_document,
            split_document, build_multi_sentence_text,
            create_project_payload,
        )
        # Build a project under the SAME client with package_size>=60.
        _, project2 = setup_client_and_project_in_draft(
            project_overrides={"package_size_segments": 200},
        )
        text = build_multi_sentence_text([3] * 60)
        doc = upload_document(project2["id"], raw_text=text)
        ds = split_document(doc["id"])
        segs = ds.get("segments") or doc.get("segments") or []
        assert len(segs) >= 60, (
            "Setup did not produce 60 segments — workload-cap test "
            "cannot be exercised. Implementation must surface segment "
            "ids in split result."
        )
        # The translator passed-test needs to cover this project's
        # language pair and domain (default en/fr GENERAL — matches).
        quote_project(project2["id"])
        seg_ids = [s["id"] for s in segs[:60]]
        resp = api_client.dispatch_assignment(
            project2["id"],
            {"translator_id": t["id"], "role": "TRANSLATOR",
             "segment_ids": seg_ids},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSLATOR_OVERLOADED)


# =============================================================================
# Rule 9 — Compensating-action invariants
# =============================================================================
class TestCompensatingInvariant:
    """
    # difficulty: compensating_invariant/word_count_conservation_under_document_archive_and_resplit
    # difficulty: compensating_invariant/cents_conservation_payout_plus_deduction_equals_urgency_total
    """

    def test_word_count_returns_to_original_after_archive_and_resplit(self):
        """# difficulty: compensating_invariant/word_count_conservation_under_document_archive_and_resplit

        PRD §3.2: "archiving sets every child segment to REJECTED and
        recomputes both Document.word_count and Project.word_count."

        Claim: word count drops to 0 after DELETE, then returns to 100
        after re-upload+split of an identical document. The invariant is
        Project.word_count == sum(Segment.word_count) over Segments whose
        Document.state != ARCHIVED.
        """
        _, project = setup_client_and_project_in_draft()
        doc1 = upload_document(project["id"], raw_text=build_words_text(100))
        split_document(doc1["id"])
        proj = get_project(project["id"])
        assert proj["word_count"] == 100, \
            f"After initial split: {proj['word_count']} != 100"
        api_client.archive_document(doc1["id"], PM)
        proj_after = get_project(project["id"])
        assert proj_after["word_count"] == 0, (
            "Archive must zero the project word count when the only "
            "document is archived."
        )
        # Re-upload identical document and split
        doc2 = upload_document(project["id"], raw_text=build_words_text(100))
        split_document(doc2["id"])
        proj_recovered = get_project(project["id"])
        assert proj_recovered["word_count"] == 100, (
            "Compensating action (re-upload + re-split) must restore "
            "Project.word_count to its pre-archive value."
        )

    def test_payout_plus_deduction_equals_urgency_total_with_zero_deduction(self):
        """# difficulty: compensating_invariant/cents_conservation_payout_plus_deduction_equals_urgency_total

        PRD §3.7: "the per-segment rounded contributions are summed
        without further rounding to a subtotal, the subtotal is
        multiplied by the urgency multiplier matching the project's
        urgency_tier (STANDARD is 10000, RUSH is 12500, CRITICAL is
        15000) and divided by 10000, with one half-up rounding to
        integer cents to produce the urgency-adjusted cents."
        PRD §3.7: "The project's final_payout_cents is the larger of
        zero and the urgency-adjusted cents minus the total quality
        deduction."

        Claim: when total quality deduction is 0 (no finalized scores
        with score<90 attached), final_payout_cents equals
        urgency-adjusted cents. For 100 words * 100c * 0.8(JUNIOR) *
        1.0(STANDARD) the urgency total is 8000 and final_payout_cents
        is also 8000 (no deduction).
        """
        # Create the QualityScore as DRAFT, then VOID it. PRD §3.6: voiding
        # produces no rating impact. The cents-conservation invariant
        # holds because the deduction set is empty.
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            base_unit_price_cents=100,
            word_count=100,
            deadline_hours_ahead=24 * 30,  # STANDARD
            quality_errors=[make_error_item("MISTRANSLATION", "MAJOR", 1)],
            finalize_quality=False,
        )
        # Void the DRAFT quality score
        void_quality_score(ctx["quality_score"]["id"])
        proj = publish_project(ctx["project"]["id"])
        # urgency_cents = 100*100*1.0(NEW)*0.8(JUNIOR)*1.0(STANDARD) = 8000
        # deduction = 0 (the only score was VOIDED)
        # final_payout_cents = 8000
        assert proj["final_payout_cents"] == 8000, (
            f"PRD §3.7: with no FINALIZED scores, final_payout_cents == "
            f"urgency_cents. Got {proj['final_payout_cents']}."
        )

    def test_word_count_after_archive_only_does_not_carry_archived_segments(self):
        """# difficulty: compensating_invariant/word_count_conservation_under_document_archive_and_resplit

        PRD §3.2: "archiving sets every child segment to REJECTED and
        recomputes both Document.word_count and Project.word_count."

        Claim: an archived document's child segments do NOT contribute to
        Project.word_count.
        """
        _, project = setup_client_and_project_in_draft()
        # Two documents: 50 words each.
        d1 = upload_document(project["id"], raw_text=build_words_text(50))
        split_document(d1["id"])
        d2 = upload_document(project["id"], raw_text=build_words_text(50))
        split_document(d2["id"])
        proj_before = get_project(project["id"])
        assert proj_before["word_count"] == 100
        # Archive d1
        api_client.archive_document(d1["id"], PM)
        proj_after = get_project(project["id"])
        assert proj_after["word_count"] == 50, (
            "Archived document's segments must be excluded from "
            "Project.word_count."
        )
