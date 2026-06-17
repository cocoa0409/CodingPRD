"""The forward-looking quote estimate: nested tier x rush x certification interaction,
pinned per-band rounding order, the volume-discount tier boundary, the notarized add-on,
and immediate consistency of the computed quote.

Covers difficulty-design rule `combinatorial_formula` and `boundary_precision_check`
(volume tier), plus corner-design `calculations` and `consistency_model` instances.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_quotable_project,
)

PM = TEST_USERS["pm_headers"]


# ─── combinatorial_formula: nested tier x rush x cert (MODE a) ──────────────
def test_quote_nested_tier_rush_cert_express_certified(api):
    """PRD §3.3: "**Step seven** sets `quoted_total_cents` to the after-rush amount plus
    the certification add-on."
    PRD §3.3: "**Step five** multiplies the after-discount amount by the rush multiplier
    for the project's rush tier — one for `STANDARD`, one and thirty hundredths for
    `EXPRESS`, and one and seventy-five hundredths for `SAME_DAY` — and rounds the result
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/cf_quote_nested_tier_rush_cert_mode_a
    """
    ctx = setup_quotable_project(
        rush_tier="EXPRESS", certification_mode="CERTIFIED",
        bands={"quoted_no_match_words": 1200, "quoted_fuzzy_words": 600,
               "quoted_reps_words": 400, "quoted_context_words": 300})
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    assert quoted["quoted_total_cents"] == 39613, \
        f"expected 39613, got {quoted['quoted_total_cents']}"


def test_quote_nested_interaction_not_linearly_separable_status_quoted(api):
    """PRD §3.3: "When the job list is settled, a `ProjectManager` requests a quote,
    which drives the project from `DRAFT` to `QUOTED`."
    PRD §3.3: "**Step seven** sets `quoted_total_cents` to the after-rush amount plus
    the certification add-on."

    Second probe of the same nested interaction: the quote both advances the project to
    QUOTED and writes the composite 39613 figure to quoted_total_cents.

    Design: Difficulty/combinatorial_formula/cf_quote_nested_tier_rush_cert_mode_a
    """
    ctx = setup_quotable_project(
        rush_tier="EXPRESS", certification_mode="CERTIFIED",
        bands={"quoted_no_match_words": 1200, "quoted_fuzzy_words": 600,
               "quoted_reps_words": 400, "quoted_context_words": 300})
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    assert quoted["status"] == "QUOTED", f"got {quoted['status']}"
    assert quoted["quoted_total_cents"] == 39613, \
        f"expected 39613, got {quoted['quoted_total_cents']}"


# ─── combinatorial_formula: per-band-then-sum rounding order (MODE b) ───────
def test_quote_round_per_band_then_sum_order_pinned(api):
    """PRD §2.7: "the platform **rounds each translation-memory band separately and then
    sums the rounded per-band amounts** — it never sums the raw per-band products first
    and rounds once at the end."
    PRD §3.3: "**Step two** sets the translation subtotal to the sum, over every job and
    every band, of those rounded per-band amounts — recall from §2.7 that the rounding
    happens per band, before summing."

    Design: Difficulty/combinatorial_formula/cf_quote_round_per_band_then_sum_order_pinned_mode_b
    """
    ctx = setup_quotable_project(
        bands={"quoted_no_match_words": 800, "quoted_fuzzy_words": 2,
               "quoted_reps_words": 2, "quoted_context_words": 2})
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    # round(2*15*0.65)=20, round(2*15*0.35)=11, round(2*15*0.15)=5, 800*15=12000 -> 12036.
    # sum-then-round would give 12035; the pinned per-band order yields 12036.
    assert quoted["quoted_total_cents"] == 12036, \
        f"expected 12036 (per-band rounding), got {quoted['quoted_total_cents']}"


def test_quote_per_band_rounding_excludes_revision_surcharge(api):
    """PRD §3.3: "The estimate uses quoted bands only and includes no revision surcharge."
    PRD §2.7: "the platform **rounds each translation-memory band separately and then
    sums the rounded per-band amounts**".

    Second probe of the pinned per-band order on the same fixture: the estimate is the
    rounded per-band subtotal with no revision surcharge, i.e. exactly 12036.

    Design: Difficulty/combinatorial_formula/cf_quote_round_per_band_then_sum_order_pinned_mode_b
    """
    ctx = setup_quotable_project(
        bands={"quoted_no_match_words": 800, "quoted_fuzzy_words": 2,
               "quoted_reps_words": 2, "quoted_context_words": 2})
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    assert quoted["quoted_total_cents"] == 12036, \
        f"expected 12036, got {quoted['quoted_total_cents']}"


# ─── boundary_precision_check: volume-discount tier at 5000 ─────────────────
def test_volume_discount_tier_inclusive_at_5000(api):
    """PRD §3.3: "**Step four** selects the volume-discount fraction from that weighted
    word total: the discount is ten hundredths when the weighted word total is at least
    twenty thousand, five hundredths when it is at least five thousand but below twenty
    thousand, and zero otherwise".

    Boundary X: weighted_words == 5000 triggers the inclusive 5% tier.

    Design: Difficulty/boundary_precision_check/bpc_volume_discount_tier_at_5000
    """
    ctx = setup_quotable_project(bands={"quoted_no_match_words": 5000}, name="P-tier-at")
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    # 5000*15 = 75000; 5% off -> round(75000*0.95)=71250.
    assert quoted["quoted_total_cents"] == 71250, \
        f"expected 71250 (5% tier), got {quoted['quoted_total_cents']}"


def test_volume_discount_tier_below_5000_no_discount(api):
    """PRD §3.3: "**Step four** selects the volume-discount fraction from that weighted
    word total: the discount is ten hundredths when the weighted word total is at least
    twenty thousand, five hundredths when it is at least five thousand but below twenty
    thousand, and zero otherwise".

    Boundary X-1: weighted_words == 4999 is below the inclusive 5000 threshold, so no
    discount applies.

    Design: Difficulty/boundary_precision_check/bpc_volume_discount_tier_at_5000
    """
    ctx = setup_quotable_project(bands={"quoted_no_match_words": 4999}, name="P-tier-below")
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    # 4999*15 = 74985; weighted 4999 < 5000 -> 0% -> 74985.
    assert quoted["quoted_total_cents"] == 74985, \
        f"expected 74985 (no discount), got {quoted['quoted_total_cents']}"


# ─── corner: notarized certification add-on ────────────────────────────────
def test_notarized_certification_add_on_correct(api):
    """PRD §3.3: "**Step six** computes the certification add-on: the total source words
    is the sum over all jobs of the four raw band-word counts; the page count is that
    total divided by two hundred fifty words per page and rounded up to the next whole
    page; the add-on is zero for `NONE`, the page count multiplied by five hundred cents
    per page for `CERTIFIED`, and the page count multiplied by five hundred cents per
    page plus a three-thousand-five-hundred-cent notary flat for `NOTARIZED`."

    Design: Corner/calculations/notarized_certification_add_on_correct
    """
    ctx = setup_quotable_project(certification_mode="NOTARIZED",
                                 bands={"quoted_no_match_words": 5000}, name="Pnot")
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    # after_vol 71250 (5% tier, STANDARD) + cert 20*500+3500 = 13500 -> 84750.
    assert quoted["quoted_total_cents"] == 84750, \
        f"expected 84750, got {quoted['quoted_total_cents']}"


# ─── corner: immediate consistency ─────────────────────────────────────────
def test_immediate_quote_visible_in_same_response(api):
    """PRD §3.3: "The quote is a forward-looking provisional estimate computed over the
    *quoted* band words, and it is written to `quoted_total_cents`".
    PRD §3.3: "a `ProjectManager` requests a quote, which drives the project from `DRAFT`
    to `QUOTED`."

    Design: Corner/consistency_model/immediate_quote_visible_in_same_response
    """
    ctx = setup_quotable_project(bands={"quoted_no_match_words": 1000}, name="P1")
    quoted = validate_success(api.quote_project(ctx["project"]["id"], PM), 200)
    assert quoted["status"] == "QUOTED", f"got {quoted['status']}"
    # 1000*15 = 15000; weighted 1000 < 5000 -> 0%; STANDARD; NONE -> 15000.
    assert quoted["quoted_total_cents"] == 15000, \
        f"expected 15000, got {quoted['quoted_total_cents']}"
