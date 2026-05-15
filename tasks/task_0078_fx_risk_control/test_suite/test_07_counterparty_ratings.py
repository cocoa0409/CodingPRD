"""Counterparty ratings, the worse-of-two-bands rule, watchlist & credit limit.

Citations refer to PRD.md §3.6.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    INVESTMENT_TIER_USD,
    SPECULATIVE_TIER_USD,
    STANDARD_TIER_USD,
    WATCH_TIER_USD,
    assert_counterparty,
    create_counterparty,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_counterparty_payload,
    patch_counterparty_payload,
)


# ===========================================================================
# Worse-of-two-bands rule — PRD §3.6
# ===========================================================================
class TestRatingBandWorseOfTwo:
    """PRD §3.6: "the system computes a `rating_band` of `INVESTMENT`,
    `STANDARD`, `SPECULATIVE`, or `WATCH`, by combining two separate band
    derivations and taking the worse of the two on a severity scale where
    `INVESTMENT` is the least severe (rank 0), `STANDARD` rank 1,
    `SPECULATIVE` rank 2, and `WATCH` the most severe (rank 3)."

    # difficulty: dual_variant_calc/counterparty_credit_band_worse_of_two
    """

    def test_external_a_internal_70_resolves_to_standard(self, api, compliance_officer_headers):
        """PRD §3.6: "`A` and `BBB` map to `STANDARD`" (external);
        "a score from 60 through 79 inclusive is `STANDARD`" (internal).
        Worse-of(STANDARD, STANDARD) = STANDARD; tier table maps STANDARD
        → fifty-million-USD ceiling; on_watchlist false.

        Claim: (external=A, internal=70) → band=STANDARD,
        credit_limit_usd=50_000_000.00, on_watchlist=false.

        # difficulty: dual_variant_calc/counterparty_credit_band_worse_of_two
        """
        cp = create_counterparty(external_rating="A", internal_score=70)
        assert_counterparty(cp)
        assert cp["rating_band"] == "STANDARD"
        assert cp["credit_limit_usd"] == STANDARD_TIER_USD
        assert cp["on_watchlist"] is False

    def test_external_a_internal_30_collapses_to_watch(self, api, compliance_officer_headers):
        """PRD §3.6: "a score strictly below 40 is `WATCH`" (internal); the
        final `rating_band` is whichever of the two bands is more severe.
        Worse-of(STANDARD, WATCH) = WATCH → credit_limit_usd =
        one-million-USD; on_watchlist=true.

        Claim: (external=A, internal=30) → band=WATCH,
        credit_limit_usd=1_000_000.00, on_watchlist=true.

        # difficulty: dual_variant_calc/counterparty_credit_band_worse_of_two
        """
        cp = create_counterparty(external_rating="A", internal_score=30)
        assert_counterparty(cp)
        assert cp["rating_band"] == "WATCH"
        assert cp["credit_limit_usd"] == WATCH_TIER_USD
        assert cp["on_watchlist"] is True


@pytest.mark.parametrize("rating,score,band,limit", [
    ("AAA", 90, "INVESTMENT", INVESTMENT_TIER_USD),
    ("AA", 85, "INVESTMENT", INVESTMENT_TIER_USD),
    ("BBB", 65, "STANDARD", STANDARD_TIER_USD),
    ("BB", 50, "SPECULATIVE", SPECULATIVE_TIER_USD),
    ("B", 45, "SPECULATIVE", SPECULATIVE_TIER_USD),
    ("CCC", 90, "WATCH", WATCH_TIER_USD),    # WATCH external overrides any internal
    ("NR", 90, "WATCH", WATCH_TIER_USD),
])
def test_band_and_credit_limit_tier_table(
    api, compliance_officer_headers, rating, score, band, limit,
):
    """PRD §3.6: "From `rating_band` the system reads `credit_limit_usd`
    from a pinned four-tier table: `INVESTMENT` counterparties carry a
    one-hundred-million-USD ceiling; `STANDARD` counterparties carry a
    fifty-million-USD ceiling; `SPECULATIVE` counterparties carry a
    ten-million-USD ceiling; `WATCH` counterparties carry a one-million-USD
    ceiling."

    Claim: each (external,internal) combination resolves to the documented
    band and tier amount.
    """
    cp = create_counterparty(external_rating=rating, internal_score=score)
    assert_counterparty(cp)
    assert cp["rating_band"] == band, (
        f"({rating}, {score}) expected band={band}; got {cp['rating_band']!r}"
    )
    assert cp["credit_limit_usd"] == limit, (
        f"({rating}, {score}) expected credit_limit_usd={limit}; "
        f"got {cp['credit_limit_usd']!r}"
    )
    assert cp["on_watchlist"] is (band == "WATCH")


# ===========================================================================
# Rating update recomputes band + watchlist — PRD §3.6
# ===========================================================================
def test_rating_update_to_watch_sets_on_watchlist_true(api, compliance_officer_headers):
    """PRD §3.6: "When the counterparty crosses from a non-`WATCH` band
    into `WATCH`, `on_watchlist` flips to true, `credit_limit_usd` drops
    to the one-million-USD `WATCH` tier".

    Claim: PATCH that lowers internal_score below 40 → on_watchlist=true,
    credit_limit_usd=1_000_000.
    """
    cp = create_counterparty(external_rating="A", internal_score=70)
    res = api.patch_counterparty(
        cp["id"],
        patch_counterparty_payload(version=cp["version"], internal_score=30),
        compliance_officer_headers,
    )
    updated = validate_success(res, 200)
    assert updated["rating_band"] == "WATCH"
    assert updated["on_watchlist"] is True
    assert updated["credit_limit_usd"] == WATCH_TIER_USD


def test_rating_update_back_out_of_watch_clears_flag(api, compliance_officer_headers):
    """PRD §3.6: "When a subsequent update lifts the counterparty back out
    of `WATCH`, `on_watchlist` flips to false and `credit_limit_usd` is
    recomputed back to the new band's tier."

    Claim: start at internal=30 (WATCH), then patch internal=70 → band
    returns to STANDARD, on_watchlist=false, credit_limit_usd=50_000_000.
    """
    cp = create_counterparty(external_rating="A", internal_score=30)
    assert cp["on_watchlist"] is True
    res = api.patch_counterparty(
        cp["id"],
        patch_counterparty_payload(version=cp["version"], internal_score=70),
        compliance_officer_headers,
    )
    updated = validate_success(res, 200)
    assert updated["rating_band"] == "STANDARD"
    assert updated["on_watchlist"] is False
    assert updated["credit_limit_usd"] == STANDARD_TIER_USD


def test_invalid_external_rating_rejected_as_validation(api, compliance_officer_headers):
    """PRD §3.6: "an `external_rating` drawn from the set `AAA`, `AA`, `A`,
    `BBB`, `BB`, `B`, `CCC`, or `NR`". A value outside that set is a
    generic input failure → ERR_VALIDATION per PRD §2.9.

    Claim: external_rating="ZZZ" → ERR_VALIDATION (422).
    """
    res = api.create_counterparty(
        create_counterparty_payload(external_rating="ZZZ", internal_score=50),
        compliance_officer_headers,
    )
    assert res.status_code == 422
    assert res.json()["data"]["error_id"] == "ERR_VALIDATION"


def test_internal_score_out_of_range_rejected(api, compliance_officer_headers):
    """PRD §3.6: "an `internal_score` integer in the inclusive range 0
    through 100". A value outside [0, 100] is a generic input failure.

    Claim: internal_score=150 → ERR_VALIDATION.
    """
    res = api.create_counterparty(
        create_counterparty_payload(external_rating="A", internal_score=150),
        compliance_officer_headers,
    )
    assert res.status_code == 422
    assert res.json()["data"]["error_id"] == "ERR_VALIDATION"
