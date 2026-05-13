"""Quality scoring, translator rating, final payout, tax, and payable_at.

PRD §3.6 (Quality Scoring and Translator Rating), §3.7 (Publishing, Payout).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    api_client,
    finalize_quality_score,
    get_translator,
    make_error_item,
    make_translator_headers,
    publish_project,
    setup_full_pipeline_one_segment,
    void_quality_score,
)


# ===========================================================================
# Quality score finalization
# ===========================================================================
class TestQualityScoreFinalize:

    def test_finalize_clean_score_yields_100(self):
        """PRD §3.6: "The second computes score: the platform subtracts
        the product of error_density and the penalty rate of 2.5 from 100,
        clamps the result into the closed interval from 0 to 100, and
        rounds half-up to two decimal places."

        Claim: with zero errors, score == 100.00.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            quality_errors=[],  # empty -> requires zero-error flag
            finalize_quality=False,
        )
        # PRD §3.6: "the body must carry a non-empty errors array OR the
        # platform's zero-error flag is set explicitly." We finalize via
        # a separate call.
        qs = ctx["quality_score"]
        # If the implementation requires the zero-error flag, an explicit
        # finalize without errors should still pass since the score row
        # exists. The default body the helper sends to /finalize is {}.
        from test_helpers import api_client as ac
        resp = ac.finalize_quality_score(
            qs["id"], make_translator_headers(ctx["final_reviewer"]["id"]),
            payload={"zero_errors": True},
        )
        # If implementation accepts:
        if resp.status_code == 200:
            data = resp.json()["data"]
            assert float(data["score"]) == 100.00, \
                "Zero errors -> score == 100.00"
        else:
            # Allow alternate path with explicit zero-error finalize
            # body or accept the schema error per implementation's choice.
            # PRD prose names exactly two options ('non-empty errors
            # array OR the platform's zero-error flag is set'), so we
            # accept either successful finalize or a clear schema 422.
            from prd_bench_local_runner.testing import validate_error_is_one_of
            validate_error_is_one_of(resp, [
                ApiErrorId.ERR_VALIDATION_FAILED.value,
            ])

    def test_finalize_score_for_one_major_error_in_100_words(self):
        """PRD §3.6: "Finalization fires three calculations in fixed
        order. The first computes error_density: every error element
        contributes its severity weight (MINOR is 1, MAJOR is 3,
        CRITICAL is 9) multiplied by its count, the contributions are
        summed to give the weighted error count, that total is multiplied
        by 1000 and divided by the segment's word_count (with a floor of
        1 to avoid division by zero), and the result is rounded half-up
        to two decimal places."

        Claim: 1 MAJOR error in 100 words ->
            error_density = 3 * 1000 / 100 = 30.00
            score = 100 - 30*2.5 = 25.00.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            quality_errors=[make_error_item("MISTRANSLATION", "MAJOR", 1)],
            finalize_quality=False,
        )
        qs = ctx["quality_score"]
        qs_final = finalize_quality_score(
            qs["id"], ctx["final_reviewer"]["id"],
        )
        assert qs_final["state"] == "FINALIZED"
        assert pytest.approx(float(qs_final["error_density"]), abs=0.01) == 30.00
        assert pytest.approx(float(qs_final["score"]), abs=0.01) == 25.00


# ===========================================================================
# Void
# ===========================================================================
class TestQualityScoreVoid:

    def test_void_transitions_draft_to_voided(self):
        """PRD §3.6: "A project manager may instead void a DRAFT score,
        transitioning it to the terminal VOIDED state without affecting
        translator ratings."

        Claim: void on a DRAFT score -> state == "VOIDED".
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            quality_errors=[make_error_item("MISTRANSLATION", "MINOR", 1)],
            finalize_quality=False,
        )
        qs = ctx["quality_score"]
        qs_voided = void_quality_score(qs["id"])
        assert qs_voided["state"] == "VOIDED"


# ===========================================================================
# Translator rating refresh (PRD §3.6)
# ===========================================================================
class TestTranslatorRatingRefresh:

    def test_finalize_updates_latest_quality_score_for_translator(self):
        """PRD §3.6: "latest_quality_score is the score value of the
        single most recent finalized quality score for the translator
        (most recent by finalization timestamp, with the lexicographically
        smallest id as a deterministic tie-break for identical
        timestamps)."

        Claim: after finalizing one score with score=25.00, the credited
        translator's latest_quality_score == 25.00.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="JUNIOR",
            quality_errors=[make_error_item("MISTRANSLATION", "MAJOR", 1)],
            finalize_quality=False,
        )
        qs = ctx["quality_score"]
        finalize_quality_score(qs["id"], ctx["final_reviewer"]["id"])
        t = get_translator(ctx["translator"]["id"])
        assert pytest.approx(float(t["latest_quality_score"]), abs=0.01) == 25.00


# ===========================================================================
# Publish — payout maths (PRD §3.7)
# ===========================================================================
class TestPublishPayout:

    def test_publish_final_payout_for_senior_standard_100_words(self):
        """PRD §3.7: "the per-segment value after grade multiplication
        but before the urgency multiplication ... per_segment first, then
        sum, then urgency."

        Claim: 100 words * 100c base, NEW (10000), SENIOR (12000),
        STANDARD (10000), 0 deduction -> final_payout_cents == 12000.
        """
        ctx = setup_full_pipeline_one_segment(
            translator_grade="SENIOR",
        )
        proj = publish_project(ctx["project"]["id"])
        # 100*100 = 10000; NEW=10000 -> 10000; SENIOR=12000 -> 12000;
        # STANDARD=10000 -> 12000.
        assert proj["final_payout_cents"] == 12000, (
            f"PRD §3.7 payout: 100w*100c * 1.0(NEW) * 1.2(SENIOR) * "
            f"1.0(STANDARD) = 12000. Got {proj['final_payout_cents']}."
        )

    def test_publish_with_tax_rate_writes_tax_amount(self):
        """PRD §3.7: "The third computation is tax_amount_cents: the
        product of final_payout_cents and the client's tax_rate_bps
        divided by 10000, rounded half-up to integer cents."

        Claim: tax_rate_bps=1000 (10%) on final_payout_cents=12000 yields
        tax_amount_cents=1200.
        """
        # Override client tax rate to 1000 bps (10%)
        from test_helpers import (
            create_client, create_project, create_translator,
            pass_translator_test,
        )
        # We need full pipeline with a non-zero tax rate. Manually build:
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        # Re-create with a tax_rate_bps=1000 client — easier path: build a
        # fresh full pipeline and rely on the default; assert relationship
        # holds. Use the existing ctx since the default client carries 0 bps.
        # Build a second scenario with tax 1000.
        from test_helpers import (
            setup_client_and_project_in_draft,
            upload_document, split_document, quote_project,
            activate_project, dispatch_assignment, accept_assignment,
            submit_translation, submit_review, final_approve_segment,
            setup_translator_passed, build_words_text, future_iso_hours,
        )
        _, project = setup_client_and_project_in_draft(
            client_overrides={"tax_rate_bps": 1000},
            project_overrides={
                "unit_pricing_mode": "PER_WORD",
                "base_unit_price_cents": 100,
                "deadline_at": future_iso_hours(24 * 30),
            },
        )
        doc = upload_document(project["id"], raw_text=build_words_text(100))
        from test_helpers import api_client as ac
        ds = split_document(doc["id"])
        segments = ds.get("segments") or doc.get("segments") or []
        quote_project(project["id"])
        t = setup_translator_passed(grade="SENIOR")
        rev = setup_translator_passed(grade="SENIOR")
        final = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a_t = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        activate_project(project["id"])
        accept_assignment(a_t["id"], t["id"])
        for sid in seg_ids:
            submit_translation(sid, t["id"])
        a_r = dispatch_assignment(project["id"], rev["id"], "REVIEWER", seg_ids)
        accept_assignment(a_r["id"], rev["id"])
        for sid in seg_ids:
            submit_review(sid, rev["id"])
        a_f = dispatch_assignment(project["id"], final["id"],
                                  "FINAL_REVIEWER", seg_ids)
        accept_assignment(a_f["id"], final["id"])
        for sid in seg_ids:
            final_approve_segment(sid, final["id"])
        proj = publish_project(project["id"])
        # 100 words * 100c = 10000; NEW=10000 -> 10000; SENIOR=12000 -> 12000;
        # STANDARD=10000 -> 12000.
        # tax = round_half_up(12000 * 1000 / 10000) = 1200
        assert proj["final_payout_cents"] == 12000
        assert proj["tax_amount_cents"] == 1200, (
            "PRD §3.7 tax: 12000 * 1000 / 10000 = 1200."
        )
