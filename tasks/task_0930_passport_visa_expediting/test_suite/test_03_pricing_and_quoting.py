"""Pricing the two money streams: bases, rounding order, the waiver and tier changes."""

import pytest

from test_helpers import (
    ApiErrorId,
    QUOTING_USER_ID,
    build_scenario,
    new_applicant,
    new_catalog_item,
    new_order,
    order_version,
    quote,
    read_order,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CASE_MANAGER


def _order_with_applicants(catalog_id, count, service_level="STANDARD", prefix="P"):
    order = new_order(catalog_id, service_level=service_level)
    for i in range(count):
        new_applicant(
            order["id"],
            full_name=f"{prefix} {i}",
            date_of_birth=f"199{i}-03-04",
        )
    return order


# ==========================================================================
# The GOVERNMENT stream: two bases on the same catalogue number
# ==========================================================================
def test_government_fee_basis_per_applicant_multiplies_and_per_order_does_not(api):
    """PRD §3.5: "When the catalog item's `government_fee_basis` is `PER_ORDER`,
    `government_fee_quoted_cents` is exactly the catalog item's `government_fee_cents` — a
    single per-file charge that does not change as travellers are added."
    PRD §3.5: "When the basis is `PER_APPLICANT`, `government_fee_quoted_cents` is the
    catalog item's `government_fee_cents` multiplied by the counted traveller total, so the
    same catalogue number yields an n-fold larger government total."

    Design: Difficulty/dual_variant_calc/government_fee_basis_per_order_versus_per_applicant
    """
    set_clock()
    per_applicant_catalog = new_catalog_item(
        destination_country="IN", government_fee_basis="PER_APPLICANT"
    )
    per_order_catalog = new_catalog_item(
        destination_country="BR", government_fee_basis="PER_ORDER"
    )
    pa_order = _order_with_applicants(per_applicant_catalog["id"], 3, prefix="PA")
    po_order = _order_with_applicants(per_order_catalog["id"], 3, prefix="PO")

    pa_quoted = validate_success(api.quote_order(pa_order["id"], {}, CASE_MANAGER))
    po_quoted = validate_success(api.quote_order(po_order["id"], {}, CASE_MANAGER))

    assert pa_quoted["government_fee_quoted_cents"] == 48000, (
        "PER_APPLICANT multiplies 16000 by the three counted travellers, got "
        f"{pa_quoted['government_fee_quoted_cents']}"
    )
    assert po_quoted["government_fee_quoted_cents"] == 16000, (
        "PER_ORDER charges the catalogue number once, got "
        f"{po_quoted['government_fee_quoted_cents']}"
    )
    assert pa_quoted["total_quoted_cents"] == 68250
    assert po_quoted["total_quoted_cents"] == 36250


def test_government_fee_basis_leaves_the_service_stream_byte_identical(api):
    """PRD §3.5: "No discount, no tier surcharge, no handling fee and no waiver ever
    touches this figure."
    PRD §3.5: "*Step one.* An automatic discount fraction is set to **0.10** when the
    counted traveller total is at least **3**, and to 0.00 otherwise."
    PRD §3.5: "*Step four.* `handling_fee_waived` is true when **both** conditions hold:
    the counted traveller total is at least **3**, and the service subtotal from step three
    is at least **20000** cents. Otherwise it is false."

    Design: Difficulty/dual_variant_calc/government_fee_basis_per_order_versus_per_applicant
    """
    set_clock()
    per_applicant_catalog = new_catalog_item(
        destination_country="IN", government_fee_basis="PER_APPLICANT"
    )
    per_order_catalog = new_catalog_item(
        destination_country="BR", government_fee_basis="PER_ORDER"
    )
    pa_order = _order_with_applicants(per_applicant_catalog["id"], 3, prefix="PA")
    po_order = _order_with_applicants(per_order_catalog["id"], 3, prefix="PO")

    pa_quoted = validate_success(api.quote_order(pa_order["id"], {}, CASE_MANAGER))
    po_quoted = validate_success(api.quote_order(po_order["id"], {}, CASE_MANAGER))

    assert pa_quoted["service_fee_quoted_cents"] == 20250
    assert po_quoted["service_fee_quoted_cents"] == 20250, (
        "the SERVICE stream is identical across both government bases, got "
        f"{po_quoted['service_fee_quoted_cents']}"
    )
    assert pa_quoted["discount_pct_applied"] == pytest.approx(0.10, abs=1e-9)
    assert pa_quoted["handling_fee_waived"] is True
    assert po_quoted["handling_fee_waived"] is True


# ==========================================================================
# Mode (b): rounding per line, then summing
# ==========================================================================
def test_service_line_is_rounded_per_traveller_before_the_lines_are_summed(api):
    """PRD §3.5: "For each traveller: take the catalog item's `base_service_fee_cents`,
    multiply it by one plus the tier surcharge fraction for the order's `service_level` —
    **0.00** for `STANDARD`, **0.35** for `EXPEDITED`, **0.80** for `RUSH` — then multiply
    that by one minus `discount_pct_applied`, and **round that per-traveller amount half up
    to whole cents**. Only then are the rounded per-traveller amounts summed to give the
    service subtotal. Summing the unrounded amounts and rounding once at the end is
    explicitly **not** the specified order and will produce a different total on fractional
    inputs."

    Design: Difficulty/combinatorial_formula/service_line_rounded_per_applicant_then_summed
    """
    set_clock()
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 3, service_level="EXPEDITED", prefix="Exp")

    quoted = validate_success(api.quote_order(order["id"], {}, CASE_MANAGER))

    # 7500 * 1.35 * 0.90 = 9112.5 per line; rounded half up per line gives 9113,
    # and three of those sum to 27339. Summing first would give 27338.
    assert quoted["service_fee_quoted_cents"] == 27339, (
        "round-per-line-then-sum gives 27339, got "
        f"{quoted['service_fee_quoted_cents']}"
    )
    assert quoted["service_fee_quoted_cents"] != 27338, (
        "27338 is the sum-then-round answer, which is expressly not specified"
    )


def test_rounded_service_lines_carry_through_to_the_order_total(api):
    """PRD §3.5: "*Step five.* The handling component is 0 when the waiver was granted, and
    **3000** cents otherwise."
    PRD §3.5: "*Step six.* `service_fee_quoted_cents` is the service subtotal plus the
    handling component. *Step seven.* `total_quoted_cents` is `government_fee_quoted_cents`
    plus `service_fee_quoted_cents`."

    Design: Difficulty/combinatorial_formula/service_line_rounded_per_applicant_then_summed
    """
    set_clock()
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 3, service_level="EXPEDITED", prefix="Exp")

    quoted = validate_success(api.quote_order(order["id"], {}, CASE_MANAGER))

    assert quoted["handling_fee_waived"] is True, (
        "three travellers and a 27339-cent subtotal clear both waiver conditions"
    )
    assert quoted["government_fee_quoted_cents"] == 48000
    assert quoted["total_quoted_cents"] == 75339, (
        "48000 government plus a waived-handling 27339 service, got "
        f"{quoted['total_quoted_cents']}"
    )


# ==========================================================================
# Mode (c): the waiver reads the POST-discount subtotal
# ==========================================================================
def test_a_larger_promo_discount_forfeits_the_waiver_and_raises_the_total(api):
    """PRD §3.5: "A consequence of this ordering deserves stating outright, because it is
    counter-intuitive and correct: **a larger discount can produce a larger total.** The
    waiver test in step four reads the post-discount subtotal. A promotion generous enough
    to drag that subtotal below 20000 cents forfeits a 3000-cent waiver, and the forfeited
    waiver can easily exceed the money the discount saved."

    Design: Difficulty/combinatorial_formula/handling_waiver_reads_post_discount_subtotal_so_a_bigger_discount_costs_more
    """
    set_clock()
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 3, prefix="Trap")

    without_promo = validate_success(api.quote_order(order["id"], {}, CASE_MANAGER))
    assert without_promo["total_quoted_cents"] == 68250
    assert without_promo["handling_fee_waived"] is True

    with_promo = validate_success(
        api.quote_order(order["id"], {"promo_discount_pct": 0.05}, CASE_MANAGER)
    )

    assert with_promo["handling_fee_waived"] is False, (
        "a 19125-cent post-discount subtotal falls below the 20000-cent floor"
    )
    assert with_promo["total_quoted_cents"] == 70125
    assert with_promo["total_quoted_cents"] > without_promo["total_quoted_cents"], (
        "the forfeited waiver exceeds what the promotion saved"
    )


def test_promo_discount_combines_with_the_automatic_fraction_before_the_waiver_test(api):
    """PRD §3.5: "*Step two.* `discount_pct_applied` is the smaller of two numbers: the
    automatic fraction plus the supplied `promo_discount_pct`, and the hard ceiling
    **0.25**."
    PRD §3.5: "**The `SERVICE` stream is priced through a seven-step waterfall whose order
    is pinned**, because the waiver test reads a subtotal that does not exist until after
    the discount has been chosen."

    Design: Difficulty/combinatorial_formula/handling_waiver_reads_post_discount_subtotal_so_a_bigger_discount_costs_more
    """
    set_clock()
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 3, prefix="Trap")
    validate_success(api.quote_order(order["id"], {}, CASE_MANAGER))

    with_promo = validate_success(
        api.quote_order(order["id"], {"promo_discount_pct": 0.05}, CASE_MANAGER)
    )

    assert with_promo["discount_pct_applied"] == pytest.approx(0.15, abs=1e-9), (
        "0.10 automatic plus 0.05 promotional, under the 0.25 ceiling, got "
        f"{with_promo['discount_pct_applied']}"
    )
    # 7500 * 1.00 * 0.85 = 6375 per line; three lines give 19125, plus the
    # forfeited-waiver handling component of 3000.
    assert with_promo["service_fee_quoted_cents"] == 22125, (
        f"expected 19125 + 3000, got {with_promo['service_fee_quoted_cents']}"
    )
    assert with_promo["government_fee_quoted_cents"] == 48000, (
        "the promotion never touches the GOVERNMENT stream"
    )


# ==========================================================================
# Tier changes
# ==========================================================================
def test_pre_intake_tier_change_reprices_from_scratch_with_no_admin_fee(api):
    """PRD §3.5: "*Before intake* — `workflow_status` `DRAFT` or `QUOTED` — the whole quote
    is **recomputed from scratch** at the new tier. Both streams re-run their calculations,
    the automatic discount and the waiver are re-evaluated against the current traveller
    set with the promotional component treated as 0.00, and **no administration fee is
    charged**. The previously quoted numbers are discarded rather than adjusted."

    Design: Corner/calculations/corner_tier_change_pre_intake_variant_is_a_full_requote
    """
    set_clock()
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 1, prefix="Requote")
    quoted = quote(order["id"])
    assert quoted["total_quoted_cents"] == 26500

    upgraded = validate_success(
        api.change_service_level(
            order["id"],
            {"service_level": "RUSH", "expected_order_version": order_version(order["id"])},
            CASE_MANAGER,
        )
    )

    assert upgraded["service_level"] == "RUSH"
    # 7500 * 1.80 = 13500 subtotal, one traveller so no waiver, plus 3000 handling.
    assert upgraded["service_fee_quoted_cents"] == 16500, (
        "the pre-intake variant re-prices rather than adding a delta plus 2500, got "
        f"{upgraded['service_fee_quoted_cents']}"
    )
    assert upgraded["government_fee_quoted_cents"] == 16000
    assert upgraded["total_quoted_cents"] == 32500
    assert upgraded["handling_fee_waived"] is False
    assert upgraded["workflow_status"] == "QUOTED", "the tier change does not move the workflow"


def test_quote_response_already_carries_every_derived_field(api):
    """PRD §3.5: "Quoting also stamps `quoted_by_user_id` with the acting `X-User-ID` and
    `quoted_at` with the logical clock, raises `furthest_stage_reached` to `QUOTED`, and
    re-runs the completion projection and its feasibility verdict described in §3.9."
    PRD §3.9: "`feasibility_status` is `FEASIBLE` when `projected_completion_date` is on or
    before that deadline date, and `INFEASIBLE` when it is strictly after."

    Design: Corner/consistency_model/corner_quote_side_effects_visible_in_the_same_response
    """
    set_clock("2026-06-01T09:00:00Z")
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 1, prefix="Immediate")

    quoted = validate_success(api.quote_order(order["id"], {}, CASE_MANAGER))

    assert quoted["total_quoted_cents"] == 26500
    assert quoted["feasibility_status"] == "FEASIBLE"
    assert quoted["quoted_by_user_id"] == QUOTING_USER_ID
    assert quoted["projected_completion_date"] == "2026-06-26", (
        f"expected the projection in the same response, got {quoted['projected_completion_date']}"
    )
    assert quoted["workflow_status"] == "QUOTED"
    assert quoted["furthest_stage_reached"] == "QUOTED"


def test_sideways_tier_request_is_not_an_upgrade(api):
    """PRD §3.5: "the requested `service_level` must be strictly higher than the current
    one in the order `STANDARD`, `EXPEDITED`, `RUSH` — a sideways or downward request is
    `ERR_TIER_NOT_AN_UPGRADE`"

    Design: Corner/errors/corner_error_tier_not_an_upgrade
    """
    set_clock()
    catalog = new_catalog_item()
    order = _order_with_applicants(catalog["id"], 1, prefix="Same Tier")
    quote(order["id"])

    resp = api.change_service_level(
        order["id"],
        {"service_level": "STANDARD", "expected_order_version": order_version(order["id"])},
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_TIER_NOT_AN_UPGRADE.value)

    stored = read_order(order["id"])
    assert stored["service_level"] == "STANDARD"
    assert stored["total_quoted_cents"] == 26500


def test_tier_change_is_closed_once_the_order_is_submitted(api):
    """PRD §3.5: "the order's `workflow_status` must be one of `DRAFT`, `QUOTED`, `INTAKE`
    or `READY_FOR_SUBMISSION`, since a tier change is closed from `SUBMITTED` onward with
    `ERR_UPGRADE_STAGE_CLOSED`"

    Design: Corner/errors/corner_error_upgrade_stage_closed_after_submission
    """
    scenario = build_scenario("submitted")
    order_id = scenario["order_id"]
    assert scenario["order"]["workflow_status"] == "SUBMITTED"

    resp = api.change_service_level(
        order_id,
        {"service_level": "RUSH", "expected_order_version": order_version(order_id)},
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_UPGRADE_STAGE_CLOSED.value)

    stored = read_order(order_id)
    assert stored["service_level"] == "STANDARD"
    assert stored["workflow_status"] == "SUBMITTED"
    assert stored["total_quoted_cents"] == 26500
