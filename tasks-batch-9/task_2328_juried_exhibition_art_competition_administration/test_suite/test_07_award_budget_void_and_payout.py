"""Award confirmation precedence, the compensating sale void, and the tax-form
gate on artist payouts."""

from test_helpers import (
    CALL_MANAGER,
    FINANCE_A,
    FINANCE_B,
    FINANCE_OFFICER_B_USER_ID,
    JURY_CHAIR_B,
    ApiErrorId,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_SALEABLE_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 400000, "for_sale": True,
        "list_price_cents": 250000,
    },
    {
        "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
        "declared_value_cents": 300000, "for_sale": True,
        "list_price_cents": 180000,
    },
]

SALE_PRICE_CENTS = 250000
SALE_BASE = 229885
SALE_TAX = 20115
SALE_COMMISSION = 80460
SALE_PAYABLE = 149425

OVER_BUDGET_PRIZE_CENTS = 900000


# ─── Phase guard outranks the award budget test ───────

def test_award_confirmation_in_jurying_reports_the_phase_not_the_budget(api):
    """PRD §2.10: "**Exhibition phase guard** — the exhibition's `status` permits
    the operation and the requested target phase is reachable from it, else
    `ERR_EXHIBITION_PHASE_INVALID` (409)." at position 8, ahead of "**Council
    award budget** — else `ERR_AWARD_BUDGET_EXCEEDED` (402); see §3.8." at
    position 47.

    Design: Difficulty/priority_pair_validation_conflict/award_confirm_phase_before_budget
    """
    exhibition = fixtures.open_call(award_budget_cents=500000)
    artist = fixtures.register_artist(member_status="MEMBER")
    _, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, [TWO_SALEABLE_WORKS[0]]
    )
    fixtures.enter_jurying(exhibition["id"])

    award = fixtures.propose_award(
        exhibition["id"], artworks[0]["id"], category="BEST_IN_SHOW",
        prize_cents=OVER_BUDGET_PRIZE_CENTS,
    )
    version = fixtures.exhibition_version(exhibition["id"])
    response = api.confirm_award(
        award["id"], {"expected_exhibition_version": version}, JURY_CHAIR_B
    )
    validate_error(response, ApiErrorId.ERR_EXHIBITION_PHASE_INVALID.value)

    unchanged = fixtures.read_award(award["id"])
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["confirmed_by_user_id"] is None

    after = fixtures.read_exhibition(exhibition["id"])
    assert after["status"] == "JURYING"
    assert after["award_committed_cents"] == 0


def test_award_over_the_council_budget_is_refused_once_the_phase_permits(api):
    """PRD §3.8: "Two budget tests then apply, each to its own kind of award: for
    an award with no sponsor, the exhibition's `award_committed_cents` plus this
    award's `prize_cents` must be at most `award_budget_cents`, else
    `ERR_AWARD_BUDGET_EXCEEDED`; and for a `PURCHASE_AWARD`, the sponsor's
    `purchase_award_committed_cents` plus this award's `prize_cents` must be at
    most that sponsor's `purchase_award_budget_cents`, else
    `ERR_SPONSOR_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/award_confirm_phase_before_budget
    """
    ctx = fixtures.setup_results_published_show(
        works=[TWO_SALEABLE_WORKS[0]],
        artist_overrides={"member_status": "MEMBER"},
        exhibition_overrides={"award_budget_cents": 500000},
    )
    exhibition, artwork = ctx["exhibition"], ctx["artworks"][0]

    award = fixtures.propose_award(
        exhibition["id"], artwork["id"], category="BEST_IN_SHOW",
        prize_cents=OVER_BUDGET_PRIZE_CENTS,
    )
    version = fixtures.exhibition_version(exhibition["id"])
    response = api.confirm_award(
        award["id"], {"expected_exhibition_version": version}, JURY_CHAIR_B
    )
    validate_error(response, ApiErrorId.ERR_AWARD_BUDGET_EXCEEDED.value)

    assert fixtures.read_award(award["id"])["status"] == "PROPOSED"
    after = fixtures.read_exhibition(exhibition["id"])
    assert after["status"] == "RESULTS_PUBLISHED"
    assert after["award_committed_cents"] == 0


# ─── Voiding a sale restores the money aggregates ─────

def _paid_gallery_sale():
    ctx = fixtures.setup_on_view_show(
        works=TWO_SALEABLE_WORKS,
        artist_overrides={"member_status": "MEMBER"},
    )
    sold_id, other_id = ctx["accepted_artwork_ids"]
    sale = fixtures.setup_paid_sale(
        sold_id, recorder=FINANCE_A, sale_price_cents=SALE_PRICE_CENTS
    )
    return ctx, sale, sold_id, other_id


def test_voiding_a_paid_sale_restores_every_exhibition_money_aggregate(api):
    """PRD §3.9: "Either way the exhibition's `sales_gross_cents`,
    `commission_total_cents`, `sales_tax_total_cents` and
    `artist_payable_total_cents` are recomputed back to their pre-sale values."

    Design: Difficulty/compensating_invariant/sale_void_restores_exhibition_money_aggregates
    """
    ctx, sale, _, _ = _paid_gallery_sale()

    before = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert before["settlement_status"] == "NOT_STARTED"
    assert before["sales_gross_cents"] == SALE_PRICE_CENTS
    assert before["commission_total_cents"] == SALE_COMMISSION
    assert before["sales_tax_total_cents"] == SALE_TAX
    assert before["artist_payable_total_cents"] == SALE_PAYABLE

    voided = validate_success(
        api.void_sale(
            sale["id"], {"reason": "Buyer financing withdrawn."}, FINANCE_A
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "Buyer financing withdrawn."

    after = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert after["sales_gross_cents"] == 0
    assert after["commission_total_cents"] == 0
    assert after["sales_tax_total_cents"] == 0
    assert after["artist_payable_total_cents"] == 0
    assert after["payouts_released_cents"] == 0


def test_voided_sale_frees_the_artwork_but_keeps_its_own_split_figures(api):
    """PRD §3.9: "Voiding releases the artwork: when the sale was that work's only
    non-voided sale and the exhibition is still `ON_VIEW`, the work returns `SOLD →
    ON_VIEW` with `sold_price_cents` cleared to null; when the exhibition has
    already reached `CLOSED`, the work returns to `RETURN_PENDING` instead."

    Design: Difficulty/compensating_invariant/sale_void_restores_exhibition_money_aggregates
    """
    _, sale, sold_id, other_id = _paid_gallery_sale()

    assert fixtures.read_artwork(sold_id)["status"] == "SOLD"

    api.void_sale(sale["id"], {"reason": "Buyer financing withdrawn."}, FINANCE_A)

    released = fixtures.read_artwork(sold_id)
    assert released["status"] == "ON_VIEW"
    assert released["sold_price_cents"] is None
    assert fixtures.read_artwork(other_id)["status"] == "ON_VIEW"

    retained = fixtures.read_sale(sale["id"])
    assert retained["status"] == "VOIDED"
    assert retained["artist_payable_cents"] == SALE_PAYABLE
    assert retained["taxable_base_cents"] == SALE_BASE

    _, meta = validate_paginated(
        api.list_sales(FINANCE_A, params={"artwork_id": sold_id})
    )
    assert meta["total_count"] == 1, "the voided row is retained, not deleted"


# ─── The tax-form gate on payout release ──────────────

def _paid_sale_awaiting_payout(tax_form_on_file):
    ctx = fixtures.setup_on_view_show(
        works=TWO_SALEABLE_WORKS,
        artist_overrides={
            "member_status": "MEMBER",
            "tax_form_on_file": tax_form_on_file,
        },
    )
    sold_id = ctx["accepted_artwork_ids"][0]
    sale = fixtures.setup_paid_sale(
        sold_id, recorder=FINANCE_A, sale_price_cents=SALE_PRICE_CENTS
    )
    fixtures.advance_settlement(ctx["exhibition"]["id"], "RECONCILING")
    return ctx, sale


def test_payout_release_without_a_tax_form_on_file_is_refused(api):
    """PRD §3.9: "Releasing the artist's money carries it `PAID → PAYOUT_RELEASED`
    and is the most heavily gated operation in the system: the exhibition's
    `settlement_status` must be `RECONCILING`, else `ERR_SETTLEMENT_PHASE_INVALID`;
    the artist must have `tax_form_on_file` true, else `ERR_TAX_FORM_MISSING`; the
    artist's `payout_hold` must be false, else `ERR_ARTIST_PAYOUT_HOLD`; the
    releasing identity must differ from `recorded_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`; and `expected_exhibition_version` must match."

    Design: Difficulty/cross_entity_state_dependency/payout_requires_artist_tax_form_on_file
    """
    ctx, sale = _paid_sale_awaiting_payout(tax_form_on_file=False)

    assert fixtures.read_artist(ctx["artist"]["id"])["payout_hold"] is False

    version = fixtures.exhibition_version(ctx["exhibition"]["id"])
    response = api.release_sale_payout(
        sale["id"], {"expected_exhibition_version": version}, FINANCE_B
    )
    validate_error(response, ApiErrorId.ERR_TAX_FORM_MISSING.value)

    still_paid = fixtures.read_sale(sale["id"])
    assert still_paid["status"] == "PAID"
    assert still_paid["artist_payable_cents"] == SALE_PAYABLE
    assert still_paid["buyer_total_cents"] == SALE_PRICE_CENTS

    after = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert after["payouts_released_cents"] == 0


def test_payout_release_succeeds_once_the_tax_form_is_recorded(api):
    """PRD §3.9: "On success the sale records `payout_released_by_user_id`, the
    exhibition's `payouts_released_cents` — the sum of `artist_payable_cents` over
    that exhibition's sales at `PAYOUT_RELEASED` — is recomputed, and both the
    exhibition's `version` and the sale's `version` increment by 1."

    Design: Difficulty/cross_entity_state_dependency/payout_requires_artist_tax_form_on_file
    """
    ctx, sale = _paid_sale_awaiting_payout(tax_form_on_file=False)

    version = fixtures.exhibition_version(ctx["exhibition"]["id"])
    validate_error(
        api.release_sale_payout(
            sale["id"], {"expected_exhibition_version": version}, FINANCE_B
        ),
        ApiErrorId.ERR_TAX_FORM_MISSING.value,
    )

    patched = validate_success(
        api.patch_artist(
            ctx["artist"]["id"], {"tax_form_on_file": True}, CALL_MANAGER
        )
    )
    assert patched["tax_form_on_file"] is True

    released = fixtures.release_payout(sale["id"], ctx["exhibition"]["id"])
    assert released["status"] == "PAYOUT_RELEASED"
    assert released["payout_released_by_user_id"] == FINANCE_OFFICER_B_USER_ID
    assert released["artist_payable_cents"] == SALE_PAYABLE

    after = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert after["payouts_released_cents"] == SALE_PAYABLE
    assert after["payouts_released_cents"] == after["artist_payable_total_cents"]
