"""Project quote, urgency tier assignment, and repetition-price gate.

PRD §3.2 (Quotation Round).
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
    build_words_text,
    build_repeated_sentence_text,
    create_client,
    create_project,
    create_project_payload,
    future_iso_hours,
    quote_project,
    setup_client_and_project_in_draft,
    setup_repetition_project,
    split_document,
    upload_document,
)


# ===========================================================================
# Empty project gate (PRD §3.2 / validation #18)
# ===========================================================================
class TestEmptyProjectGate:

    def test_quote_empty_project_returns_err_empty_project(self):
        """PRD §3.2: "The quote runs only when every document under the
        project is in SPLIT and the project's word_count is strictly
        greater than zero (otherwise ERR_EMPTY_PROJECT)."

        Claim: POST /projects/{id}/quote on a project with no documents
        yields ERR_EMPTY_PROJECT.
        """
        _, project = setup_client_and_project_in_draft()
        resp = api_client.quote_project(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PROJECT)


# ===========================================================================
# Urgency tier boundaries (PRD §3.2)
# ===========================================================================
class TestUrgencyTierBoundaries:

    def test_deadline_exactly_48_hours_lands_in_rush(self):
        """PRD §3.2: "The boundary is strict: a remaining-hours value of
        exactly 48 lands in RUSH, and a value of exactly 168 lands in
        STANDARD."

        Claim: deadline 48h ahead -> urgency_tier == "RUSH" after quote.
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={"deadline_at": future_iso_hours(48)},
        )
        doc = upload_document(project["id"], raw_text=build_words_text(10))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "RUSH", \
            "exactly 48 hours -> RUSH (boundary strict-less-than)"

    def test_deadline_exactly_168_hours_lands_in_standard(self):
        """PRD §3.2: "The boundary is strict: a remaining-hours value of
        exactly 48 lands in RUSH, and a value of exactly 168 lands in
        STANDARD."

        Claim: deadline 168h ahead -> urgency_tier == "STANDARD".
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={"deadline_at": future_iso_hours(168)},
        )
        doc = upload_document(project["id"], raw_text=build_words_text(10))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "STANDARD"

    def test_deadline_inside_48_hours_yields_critical(self):
        """PRD §3.2: "when the remaining hours are strictly less than 48,
        the tier is CRITICAL."

        Claim: deadline 24h ahead -> urgency_tier == "CRITICAL".
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={"deadline_at": future_iso_hours(24)},
        )
        doc = upload_document(project["id"], raw_text=build_words_text(10))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "CRITICAL"


# ===========================================================================
# Quote arithmetic (PRD §3.2)
# ===========================================================================
class TestQuoteArithmetic:

    def test_quote_for_standard_per_word_100_words_at_100c(self):
        """PRD §3.2: "the result is multiplied by the forward-looking grade
        multiplier of 10000 (the SENIOR assumption) and divided by 10000,
        rounded half-up to integer cents; the rounded per-segment
        contributions are summed to a subtotal; finally the subtotal is
        multiplied by the urgency multiplier (STANDARD is 10000, RUSH is
        12500, CRITICAL is 15000) and divided by 10000."

        Claim: 100 words * 100c base, NEW, SENIOR (10000), STANDARD (10000)
        -> quoted_total_cents == 10000.
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={
                "unit_pricing_mode": "PER_WORD",
                "base_unit_price_cents": 100,
                "deadline_at": future_iso_hours(24 * 30),
            },
        )
        doc = upload_document(project["id"], raw_text=build_words_text(100))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "STANDARD"
        assert project["quoted_total_cents"] == 10000, (
            f"PRD §3.2 quote: 100 words * 100c = 10000 base, NEW (rep=10000)"
            f"-> 10000, SENIOR (10000) -> 10000, STANDARD (10000) -> 10000."
        )

    def test_quote_critical_tier_marks_up_50pct(self):
        """PRD §3.2: "the subtotal is multiplied by the urgency multiplier
        (STANDARD is 10000, RUSH is 12500, CRITICAL is 15000) and divided
        by 10000, with one final half-up rounding to integer cents."

        Claim: CRITICAL urgency multiplies subtotal by 1.5.
        """
        client, project = setup_client_and_project_in_draft(
            project_overrides={
                "unit_pricing_mode": "PER_WORD",
                "base_unit_price_cents": 100,
                "deadline_at": future_iso_hours(24),  # CRITICAL
            },
        )
        doc = upload_document(project["id"], raw_text=build_words_text(100))
        split_document(doc["id"])
        project = quote_project(project["id"])
        assert project["urgency_tier"] == "CRITICAL"
        # 100*100=10000 base; NEW=10000 -> 10000; SENIOR=10000 -> 10000;
        # CRITICAL=15000 -> 15000.
        assert project["quoted_total_cents"] == 15000


# ===========================================================================
# Repetition-price gate (PRD §3.2)
# ===========================================================================
class TestRepetitionPriceGate:

    def test_repetition_rate_at_75_percent_blocks_low_price_update(self):
        """PRD §3.2: "When that ratio reaches or exceeds 75 percent (the
        boundary is inclusive: exactly 75.00 percent triggers the gate,
        74.99 percent does not), the project's base_unit_price_cents must
        be at least the platform's minimum high-repetition price,
        otherwise the creation or update is rejected with
        ERR_REPETITION_PRICE_TOO_LOW."

        Claim: repetition rate == 75% with base_unit_price_cents == 1 on
        PUT -> ERR_REPETITION_PRICE_TOO_LOW.

        Construction: 4 sentences of 25 words each — 1 NEW + 3
        EXACT_REPEAT (75 words / 100 word_count = 75%).
        """
        # 1 unique 25-word sentence, then 3 repeated 25-word sentences.
        # build_repeated_sentence_text repeats the SAME word string,
        # so the first instance is NEW and the rest EXACT_REPEAT.
        client, project, doc, segments = setup_repetition_project(
            repeated_word_count=25,
            repetitions=4,  # 1 NEW + 3 EXACT_REPEAT
            base_unit_price_cents=100,
        )
        # Confirm word_count is 100 and repetition rate is 75%
        proj = api_client.get_project(project["id"], PM).json()["data"]
        assert proj["word_count"] == 100
        # Now update price to 1 (clearly low for high-repetition gate)
        resp = api_client.update_project(
            project["id"], {"base_unit_price_cents": 1}, PM,
        )
        validate_error(resp, ApiErrorId.ERR_REPETITION_PRICE_TOO_LOW)

    def test_repetition_rate_below_75_percent_does_not_trigger(self):
        """PRD §3.2: "exactly 75.00 percent triggers the gate, 74.99 percent
        does not."

        Claim: with EXACT_REPEAT word ratio < 75%, the same PUT succeeds.

        Construction: 1 NEW + 2 EXACT_REPEAT of 25 words each (50 of 75
        words = 66.7% repeats — below 75%).
        """
        client, project, doc, segments = setup_repetition_project(
            repeated_word_count=25,
            repetitions=3,  # 1 NEW + 2 EXACT_REPEAT
            base_unit_price_cents=100,
        )
        resp = api_client.update_project(
            project["id"], {"base_unit_price_cents": 1}, PM,
        )
        # Below threshold => not blocked by the repetition price gate.
        validate_success(resp)
