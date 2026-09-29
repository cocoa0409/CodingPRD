"""Two calculations that each exist in two variants over the same inputs.

The substantiation strength score is computed twice from one evidence array — a
generous provisional read and a strict frozen one — and the thirty-day claim
notification window is computed once but anchored on either of two dates
depending on whether approval or launch came first.
"""

from datetime import date, timedelta

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_SUBSTANTIATION_INSUFFICIENT
from test_helpers.assertions import assert_calendar_date, assert_score
from test_helpers.constants import (
    BASIS_CLAIM_ACTIVATION,
    BASIS_PRODUCT_LAUNCH,
    DOSSIER_DRAFT,
    DOSSIER_UNDER_REVIEW,
    FDA_DISCLAIMER_TEXT,
    LIFECYCLE_LABEL_LOCKED,
    LIFECYCLE_MARKETED,
    NOTIFICATION_DUE,
    NOTIFICATION_NOT_DUE,
    SUBSTANTIATION_APPROVED,
    SUBSTANTIATION_UNDER_REVIEW,
)
from test_helpers.factories import review_payload, start_marketing_payload
from test_helpers.fixtures import (
    append_studies,
    make_approved_claim,
    make_claim,
    make_dossier,
    make_grandfathered_ingredient,
    make_line,
    make_locked_panel,
    make_product,
    set_clock,
)

# Three studies that screen at 70.80 and freeze at 28.80: the 300-subject RCT is
# generous under the provisional read and vanishes entirely under the final one.
DIVERGENT_STUDY_SET = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 60,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Okafor 2023 J Joint Health 12:44",
    },
    {
        "study_type": "OBSERVATIONAL_HUMAN",
        "subject_count": 200,
        "dose_match": False,
        "peer_reviewed": True,
        "citation": "Lindqvist 2022 Nutr Obs 8:210",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 300,
        "dose_match": True,
        "peer_reviewed": False,
        "citation": "Internal Trial TX-9 (unpublished)",
    },
]

# Two peer-reviewed trials and one cohort, all dose-matched: a comfortable file.
IMMUNE_STUDY_SET = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Hayashi 2021 Immunol Nutr 4:11",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 150,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Moreau 2022 Clin Nutr 19:87",
    },
    {
        "study_type": "OBSERVATIONAL_HUMAN",
        "subject_count": 100,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Ferreira 2020 Cohort Rev 2:5",
    },
]


def _turmeric_dossier(api, specialist_headers):
    """A DRAFT dossier holding the three divergent studies."""
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Turmeric Extract 95%",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1000,
        rdi_mg=None,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Turmeric 500",
        net_quantity_g=90,
        servings_per_container=45,
    )
    claim = make_claim(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        claim_text="Helps maintain joint flexibility",
        claim_type="STRUCTURE_FUNCTION",
    )
    dossier = make_dossier(
        api,
        claim["id"],
        specialist_headers,
        dossier_summary="Joint flexibility substantiation, three human studies",
    )
    append_studies(api, dossier["id"], DIVERGENT_STUDY_SET, specialist_headers)
    return claim, dossier


def test_the_provisional_read_and_the_frozen_score_disagree_by_forty_two_points(
    api, specialist_headers
):
    """One evidence array, two denominators, two peer-review policies.

    PRD §3.4: "Every study in ``evidence_studies`` participates regardless of
    peer-review status, the human-study denominator is 50 subjects, and peer review
    is not enforced, so the peer factor is 1.0 for every study including those whose
    ``peer_reviewed`` is false." The strict variant differs on both counts: "Only
    studies whose ``peer_reviewed`` is true participate at all — a non-peer-reviewed
    study is excluded from the set entirely rather than down-weighted — the
    human-study denominator rises to 100 subjects, and peer review is enforced."

    Design: Difficulty/dual_variant_calc/substantiation_score_screening_vs_final_peer_exclusion
    """
    claim, dossier = _turmeric_dossier(api, specialist_headers)

    screened = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert screened["study_count"] == 3
    assert screened["dossier_status"] == DOSSIER_DRAFT
    assert_score(screened["screening_score"], 70.80)
    assert screened["final_score"] is None

    validate_success(api.submit_claim_for_review(claim["id"], specialist_headers), 200)

    frozen = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert frozen["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert_score(frozen["final_score"], 28.80)
    assert_score(frozen["screening_score"], 70.80)
    assert frozen["study_count"] == 3


def test_the_frozen_score_and_not_the_screening_read_decides_acceptance(
    api, specialist_headers, reviewer_headers
):
    """A file that screens well above the threshold is still refused.

    PRD §3.4: "An ``ACCEPT`` carries two further preconditions: the acting
    ``X-User-ID`` must differ from the dossier's ``authored_by_user_id`` per §2.10,
    and the frozen ``final_score`` must be at least 65.00 — the
    competent-and-reliable evidence threshold — with a shortfall refused as
    ``ERR_SUBSTANTIATION_INSUFFICIENT`` (HTTP 409)." The same section pins that the
    frozen figure is the only one that counts: it "is never recomputed afterwards,
    no matter what happens to the dossier".

    Design: Difficulty/dual_variant_calc/substantiation_score_screening_vs_final_peer_exclusion
    """
    claim, dossier = _turmeric_dossier(api, specialist_headers)
    validate_success(api.submit_claim_for_review(claim["id"], specialist_headers), 200)

    refused = api.review_dossier(
        dossier["id"], review_payload("ACCEPT"), reviewer_headers
    )
    validate_error(refused, ERR_SUBSTANTIATION_INSUFFICIENT, 409)

    held = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert held["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert held["reviewed_by_user_id"] is None
    assert held["review_decision"] is None
    assert_score(held["final_score"], 28.80)
    assert_score(held["screening_score"], 70.80)

    claim_after = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert claim_after["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW


def _c500_locked_with_approved_claim(api, specialist_headers, reviewer_headers, officer_headers):
    """A LABEL_LOCKED product whose first claim was approved on 2026-09-01."""
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
    set_clock(api, "2026-09-01T00:00:00Z", specialist_headers)
    claim_a, _dossier_a = make_approved_claim(
        api,
        product["id"],
        ingredient["id"],
        IMMUNE_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        officer_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    make_locked_panel(
        api,
        product["id"],
        specialist_headers,
        officer_headers,
        servings_per_container_declared=60,
        disclaimer_text=FDA_DISCLAIMER_TEXT,
    )
    return product, ingredient, claim_a


def test_a_claim_approved_before_launch_anchors_on_the_marketing_date(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """Until the product ships, the notification obligation does not exist.

    PRD §3.6: "Approval of a claim on a product still in ``DRAFT`` or
    ``LABEL_LOCKED`` leaves ``notification_status`` at ``NOT_DUE``, with
    ``notification_due_date`` and ``notification_due_basis`` both null, until the
    launch sweeps it up." The sweep then fixes the anchor: "When a claim reached
    ``APPROVED`` while its product was still in ``DRAFT`` or ``LABEL_LOCKED``, the
    basis is ``PRODUCT_LAUNCH_BASIS`` and ``notification_due_date`` is the product's
    ``marketing_start_date`` plus 30 days".

    Design: Difficulty/dual_variant_calc/claim_notification_due_date_launch_basis_vs_activation_basis
    """
    product, _ingredient, claim_a = _c500_locked_with_approved_claim(
        api, specialist_headers, reviewer_headers, officer_headers
    )

    before = validate_success(api.get_claim(claim_a["id"], specialist_headers), 200)
    assert before["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert before["notification_status"] == NOTIFICATION_NOT_DUE
    assert before["notification_due_date"] is None
    assert before["notification_due_basis"] is None

    locked = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert locked["lifecycle_status"] == LIFECYCLE_LABEL_LOCKED

    set_clock(api, "2026-09-10T00:00:00Z", specialist_headers)
    launched = validate_success(
        api.start_marketing(
            product["id"], start_marketing_payload("2026-09-10"), officer_headers
        ),
        200,
    )
    assert launched["lifecycle_status"] == LIFECYCLE_MARKETED
    assert_calendar_date(launched["marketing_start_date"], "2026-09-10")
    assert launched["active_claim_count"] == 1

    swept = validate_success(api.get_claim(claim_a["id"], specialist_headers), 200)
    assert swept["notification_status"] == NOTIFICATION_DUE
    assert swept["notification_due_basis"] == BASIS_PRODUCT_LAUNCH
    assert_calendar_date(swept["notification_due_date"], "2026-10-10")


def test_a_claim_approved_after_launch_anchors_on_its_own_approval(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """The same 30-day rule on one product yields two dates 25 days apart.

    PRD §3.6: "When a claim reaches ``APPROVED`` while its product is already
    ``MARKETED``, the basis is ``CLAIM_ACTIVATION_BASIS`` and
    ``notification_due_date`` is the UTC calendar date of the claim's
    ``approved_at`` plus 30 days; the notification obligation starts the day the
    claim goes live." The section states the consequence outright: "The same claim on
    the same product therefore gets a later due date under the activation basis than
    under the launch basis whenever approval follows marketing."

    Design: Difficulty/dual_variant_calc/claim_notification_due_date_launch_basis_vs_activation_basis
    """
    product, ingredient, claim_a = _c500_locked_with_approved_claim(
        api, specialist_headers, reviewer_headers, officer_headers
    )
    set_clock(api, "2026-09-10T00:00:00Z", specialist_headers)
    validate_success(
        api.start_marketing(
            product["id"], start_marketing_payload("2026-09-10"), officer_headers
        ),
        200,
    )

    set_clock(api, "2026-10-05T00:00:00Z", specialist_headers)
    claim_b, _dossier_b = make_approved_claim(
        api,
        product["id"],
        ingredient["id"],
        IMMUNE_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        officer_headers,
        claim_overrides={
            "claim_text": "Supports collagen formation",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    assert claim_b["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert claim_b["notification_status"] == NOTIFICATION_DUE
    assert claim_b["notification_due_basis"] == BASIS_CLAIM_ACTIVATION
    assert_calendar_date(claim_b["notification_due_date"], "2026-11-04")

    first = validate_success(api.get_claim(claim_a["id"], specialist_headers), 200)
    assert first["notification_due_basis"] == BASIS_PRODUCT_LAUNCH
    assert_calendar_date(first["notification_due_date"], "2026-10-10")

    spread = date.fromisoformat(claim_b["notification_due_date"][:10]) - date.fromisoformat(
        first["notification_due_date"][:10]
    )
    assert spread == timedelta(days=25)

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["lifecycle_status"] == LIFECYCLE_MARKETED
    assert product_after["active_claim_count"] == 2
    assert_calendar_date(product_after["marketing_start_date"], "2026-09-10")
