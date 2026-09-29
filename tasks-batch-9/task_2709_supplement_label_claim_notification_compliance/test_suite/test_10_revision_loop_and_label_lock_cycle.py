"""Two cycles in the state graph, one counted and one indefinite.

A claim may bounce between substantiation review and revision, but the trip is
counted and the counter caps it. A product may bounce between draft and
label-locked as often as its label is reprinted, and nothing caps that at all;
the backward edge is driven from a different entity entirely.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_REVISION_LIMIT_EXCEEDED
from test_helpers.assertions import assert_panel_computed
from test_helpers.constants import (
    DECISION_REJECT,
    DOSSIER_DRAFT,
    DOSSIER_REJECTED,
    LIFECYCLE_DRAFT,
    LIFECYCLE_LABEL_LOCKED,
    PANEL_STATUS_LOCKED,
    PANEL_STATUS_SUPERSEDED,
    PANEL_STATUS_VALIDATED,
    SUBSTANTIATION_REVISION_REQUESTED,
    WARNING_PEDIATRIC,
)
from test_helpers.factories import label_panel_payload, review_payload
from test_helpers.fixtures import (
    append_studies,
    make_claim,
    make_dossier,
    make_grandfathered_ingredient,
    make_line,
    make_locked_panel,
    make_product,
    product_version,
)

# One adequate trial per round, so nothing but the round counter can be at fault.
ONE_TRIAL = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 400,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Elderberry confirmatory RCT",
    }
]


def _claim_after_four_rejected_rounds(api, specialist_headers, reviewer_headers):
    """Drive four complete reject cycles, leaving revision_round at its cap."""
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Elderberry Extract",
        ingredient_class="BOTANICAL",
        daily_intake_mg=600,
        rdi_mg=None,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Elderberry Syrup",
        net_quantity_g=240,
        servings_per_container=48,
    )
    claim = make_claim(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        claim_text="Supports seasonal immune resilience",
        claim_type="STRUCTURE_FUNCTION",
    )
    rejected = []
    for round_number in range(1, 5):
        dossier = make_dossier(
            api,
            claim["id"],
            specialist_headers,
            dossier_summary="Round {} evidence package".format(round_number),
        )
        append_studies(api, dossier["id"], ONE_TRIAL, specialist_headers)
        validate_success(
            api.submit_claim_for_review(claim["id"], specialist_headers), 200
        )
        validate_success(
            api.review_dossier(
                dossier["id"],
                review_payload(DECISION_REJECT, rejection_reason="Single trial is not a totality."),
                reviewer_headers,
            ),
            200,
        )
        rejected.append(dossier["id"])
    return product, claim, rejected


def test_the_fourth_completed_revision_loop_closes_the_claim_for_good(
    api, specialist_headers, reviewer_headers
):
    """The counter records completed loops and the guard reads it.

    PRD §3.4: "The claim must be in ``DRAFT`` or in ``REVISION_REQUESTED``; from
    ``REVISION_REQUESTED`` it must additionally have a ``revision_round`` strictly
    below 3, and a fourth attempt is refused with ``ERR_REVISION_LIMIT_EXCEEDED``
    (HTTP 409)." The same paragraph explains the arithmetic: "The resubmission edge
    additionally advances ``revision_round`` by 1: the counter records completed
    revision loops, so a claim that has looped three times sits at ``revision_round``
    3 and can never be submitted again."

    Design: Difficulty/non_linear_state_machine/claim_substantiation_revision_loop_capped_at_third_round
    """
    product, claim, rejected = _claim_after_four_rejected_rounds(
        api, specialist_headers, reviewer_headers
    )
    capped = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert capped["substantiation_status"] == SUBSTANTIATION_REVISION_REQUESTED
    assert capped["revision_round"] == 3

    fresh = make_dossier(
        api, claim["id"], specialist_headers, dossier_summary="Round 5 evidence package"
    )
    append_studies(api, fresh["id"], ONE_TRIAL, specialist_headers)

    refused = api.submit_claim_for_review(claim["id"], specialist_headers)
    validate_error(refused, ERR_REVISION_LIMIT_EXCEEDED, 409)

    stalled = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert stalled["substantiation_status"] == SUBSTANTIATION_REVISION_REQUESTED
    assert stalled["revision_round"] == 3

    untouched = validate_success(api.get_dossier(fresh["id"], specialist_headers), 200)
    assert untouched["dossier_status"] == DOSSIER_DRAFT
    assert untouched["final_score"] is None

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["active_claim_count"] == 0
    assert len(rejected) == 4


def test_every_rejected_dossier_of_the_loop_stays_terminal_and_readable(
    api, specialist_headers, reviewer_headers
):
    """Each loop retires its own dossier; none is superseded or reopened.

    PRD §3.4: "rejection drives ``UNDER_REVIEW → REJECTED``, records
    ``rejection_reason``, and cascades the parent claim ``UNDER_SUBSTANTIATION_REVIEW
    → REVISION_REQUESTED``, advancing the claim's ``version``. The author then opens a
    fresh dossier — superseding nothing, since the rejected one is terminal — and
    resubmits, consuming one of the three permitted revision loops."

    Design: Difficulty/non_linear_state_machine/claim_substantiation_revision_loop_capped_at_third_round
    """
    _product, claim, rejected = _claim_after_four_rejected_rounds(
        api, specialist_headers, reviewer_headers
    )
    assert len(set(rejected)) == 4

    for dossier_id in rejected:
        retired = validate_success(api.get_dossier(dossier_id, specialist_headers), 200)
        assert retired["dossier_status"] == DOSSIER_REJECTED
        assert retired["review_decision"] == DECISION_REJECT
        assert retired["rejection_reason"] == "Single trial is not a totality."
        assert retired["reviewed_at"] is not None

    claim_after = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert claim_after["substantiation_status"] == SUBSTANTIATION_REVISION_REQUESTED
    assert claim_after["revision_round"] == 3


def _c500_label_locked(api, specialist_headers, officer_headers):
    """One product with one ACTIVE line and one LOCKED panel over 2026-09-01..2027-08-31."""
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="C-500",
        net_quantity_g=120,
        servings_per_container=60,
    )
    make_line(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        amount_per_serving_mg=500,
        panel_position=1,
    )
    first_panel = make_locked_panel(
        api,
        product["id"],
        specialist_headers,
        officer_headers,
        servings_per_container_declared=60,
        effective_from="2026-09-01",
        effective_until="2027-08-31",
        declared_warning_codes=[WARNING_PEDIATRIC],
    )
    return product, first_panel


def _replacement_panel(api, product_id, superseded_panel_id, specialist_headers):
    """Draft a replacement over the identical window, naming the panel it retires."""
    return validate_success(
        api.create_label_panel(
            label_panel_payload(
                product_id,
                product_version(api, product_id, specialist_headers),
                declared_warning_codes=[WARNING_PEDIATRIC],
                servings_per_container_declared=60,
                effective_from="2026-09-01",
                effective_until="2027-08-31",
                supersedes_panel_id=superseded_panel_id,
            ),
            specialist_headers,
        ),
        201,
    )


def test_drafting_a_replacement_panel_walks_the_product_backwards_to_draft(
    api, specialist_headers, officer_headers
):
    """The retired panel vacates its window, so the replacement may reuse it.

    PRD §3.5: "When the request succeeds, the named panel moves ``VALIDATED →
    SUPERSEDED`` or ``LOCKED → SUPERSEDED`` depending on where it stood, the
    product's ``version`` advances, and — if the superseded panel was the locked one
    that had put the product into ``LABEL_LOCKED`` — the product itself moves
    ``LABEL_LOCKED → DRAFT``." The window comparison excuses the retiring panel: "The
    panel named by ``supersedes_panel_id`` is excluded from the comparison set, since
    it is being retired by this very request and vacates its window."

    Design: Difficulty/non_linear_state_machine/product_label_lock_cycle_revisits_draft_via_superseding_panel
    """
    product, first_panel = _c500_label_locked(api, specialist_headers, officer_headers)
    assert first_panel["panel_status"] == PANEL_STATUS_LOCKED
    locked = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert locked["lifecycle_status"] == LIFECYCLE_LABEL_LOCKED

    replacement = _replacement_panel(
        api, product["id"], first_panel["id"], specialist_headers
    )
    assert replacement["supersedes_panel_id"] == first_panel["id"]
    assert replacement["effective_from"][:10] == "2026-09-01"
    assert replacement["effective_until"][:10] == "2027-08-31"

    reopened = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert reopened["lifecycle_status"] == LIFECYCLE_DRAFT

    retired = validate_success(
        api.get_label_panel(first_panel["id"], specialist_headers), 200
    )
    assert retired["panel_status"] == PANEL_STATUS_SUPERSEDED


def test_the_replacement_panel_locks_the_product_a_second_time(
    api, specialist_headers, officer_headers
):
    """The draft / label-locked pair may be re-entered without limit.

    PRD §3.5: "That cyclic edge is the heart of the label revision loop: a product
    that has been label-locked returns to draft the moment a replacement panel is
    drafted, and it stays there until the replacement is validated and locked in
    turn." The lock cascade is spelled out too: "A successful lock moves the panel
    ``VALIDATED → LOCKED``, stamps ``locked_at`` from the logical clock, advances the
    panel's ``version``, and cascades onto the product: ``DRAFT → LABEL_LOCKED``".

    Design: Difficulty/non_linear_state_machine/product_label_lock_cycle_revisits_draft_via_superseding_panel
    """
    product, first_panel = _c500_label_locked(api, specialist_headers, officer_headers)
    replacement = _replacement_panel(
        api, product["id"], first_panel["id"], specialist_headers
    )

    validated = validate_success(
        api.validate_label_panel(replacement["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert_panel_computed(
        validated,
        required_warning_codes=[WARNING_PEDIATRIC],
        panel_lines_required=6,
        panel_lines_allowed=24,
        panel_total_dv_coverage_pct=556,
    )

    relocked = validate_success(
        api.lock_label_panel(replacement["id"], officer_headers), 200
    )
    assert relocked["panel_status"] == PANEL_STATUS_LOCKED
    assert relocked["locked_at"] is not None

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["lifecycle_status"] == LIFECYCLE_LABEL_LOCKED

    panels, meta = validate_paginated(
        api.list_label_panels(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["panel_status"] for row in panels} == {
        PANEL_STATUS_LOCKED,
        PANEL_STATUS_SUPERSEDED,
    }
