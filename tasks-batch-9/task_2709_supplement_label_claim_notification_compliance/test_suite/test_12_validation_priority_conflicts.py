"""Two requests that each break two rules at once, and the order that decides.

The refusal order is global and numbered, so when a single call violates two
checks the caller must always hear the lower-numbered one. Each pair here is
proved rather than assumed: the masked complaint is made to surface afterwards by
repairing only the violation that outranked it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CLAIM_STATE_INVALID,
    ERR_DOSSIER_NOT_ACCEPTED,
    ERR_MANDATORY_WARNING_MISSING,
    ERR_PANEL_LINE_BUDGET_EXCEEDED,
)
from test_helpers.constants import (
    DOSSIER_UNDER_REVIEW,
    PANEL_FORMAT_LINEAR,
    PANEL_STATUS_DRAFT,
    SUBSTANTIATION_DRAFT,
    SUBSTANTIATION_UNDER_REVIEW,
    WARNING_PEDIATRIC,
)
from test_helpers.fixtures import (
    make_claim,
    make_claim_under_review,
    make_draft_panel,
    make_grandfathered_ingredient,
    make_line,
    make_product,
)

WARNING_ANTICOAGULANT = "CONTRAINDICATION_ANTICOAGULANT"
WARNING_SOYBEAN = "ALLERGEN_SOYBEAN"

ONE_TRIAL = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "J Nutr Immunol 2025;14:221-233",
    }
]


def _ingredient_and_product(api, specialist_headers):
    """One cleared ingredient and one draft product, nothing else."""
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
    return ingredient, product


def test_the_claim_state_screen_answers_before_the_dossier_lookup(
    api, specialist_headers, officer_headers
):
    """A draft claim with no evidence at all hears about its state, not its evidence.

    PRD §2.7 rank 9: "A claim's ``substantiation_status`` must be ``DRAFT`` or
    ``REVISION_REQUESTED`` to be submitted for review or reworded,
    ``UNDER_SUBSTANTIATION_REVIEW`` to be approved, and ``APPROVED`` both to be
    withdrawn and to be notified to the agency, otherwise
    ``ERR_CLAIM_STATE_INVALID``." That screen sits at rank 9, far above the rank-16
    band that holds "dossier acceptance at approval", and PRD §2.7 explains why the
    sequence is pinned at all: "a caller cannot
    distinguish 'the panel is frozen' from 'the panel does not exist' if the order is
    not fixed."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_outranks_missing_accepted_dossier
    """
    ingredient, product = _ingredient_and_product(api, specialist_headers)
    claim = make_claim(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        claim_text="Supports immune function",
        claim_type="STRUCTURE_FUNCTION",
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_DRAFT

    refused = api.approve_claim(claim["id"], officer_headers)
    body = validate_error(refused, ERR_CLAIM_STATE_INVALID, 409)
    assert body["error_id"] != ERR_DOSSIER_NOT_ACCEPTED

    untouched = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert untouched["substantiation_status"] == SUBSTANTIATION_DRAFT
    assert untouched["approved_by_user_id"] is None
    assert untouched["approved_at"] is None

    ledger = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert ledger["active_claim_count"] == 0


def test_the_dossier_complaint_surfaces_only_once_the_state_screen_is_satisfied(
    api, specialist_headers, officer_headers
):
    """The masked lower-priority refusal is real, and it appears in its own right.

    PRD §3.4: "Approval is reserved to a ``ClaimApprovalOfficer`` and requires the
    claim to be in ``UNDER_SUBSTANTIATION_REVIEW``, the product not to be ``FROZEN``,
    and the claim to have exactly one dossier in ``ACCEPTED``; a missing acceptance is
    refused with ``ERR_DOSSIER_NOT_ACCEPTED`` (HTTP 409)." Because the dossier is only
    ``UNDER_REVIEW``, PRD §3.4 leaves it short of the state acceptance needs:
    "Acceptance drives ``UNDER_REVIEW → ACCEPTED``."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_outranks_missing_accepted_dossier
    """
    ingredient, product = _ingredient_and_product(api, specialist_headers)
    claim, dossier = make_claim_under_review(
        api,
        product["id"],
        ingredient["id"],
        ONE_TRIAL,
        specialist_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW
    assert dossier["dossier_status"] == DOSSIER_UNDER_REVIEW

    refused = api.approve_claim(claim["id"], officer_headers)
    body = validate_error(refused, ERR_DOSSIER_NOT_ACCEPTED, 409)
    assert body["error_id"] != ERR_CLAIM_STATE_INVALID

    held = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert held["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW
    assert held["approved_by_user_id"] is None

    ledger = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert ledger["active_claim_count"] == 0


def _linear_panel_missing_the_allergen_warning(api, specialist_headers):
    """Three-line botanical pack on a LINEAR panel, one required code left undeclared."""
    soy = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Soy Isoflavones",
        ingredient_class="BOTANICAL",
        daily_intake_mg=80,
        rdi_mg=None,
        allergen_code="SOYBEAN",
    )
    ginkgo = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ginkgo Biloba Extract",
        ingredient_class="BOTANICAL",
        daily_intake_mg=120,
        rdi_mg=120,
        contraindication_code="ANTICOAGULANT",
    )
    ascorbate = make_grandfathered_ingredient(
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
        brand_name="VitaTrust",
        product_name="Botanical Trio",
        net_quantity_g=60,
        servings_per_container=30,
    )
    soy_line = make_line(
        api,
        product["id"],
        soy["id"],
        specialist_headers,
        amount_per_serving_mg=80,
        panel_position=1,
    )
    make_line(
        api,
        product["id"],
        ginkgo["id"],
        specialist_headers,
        amount_per_serving_mg=60,
        panel_position=2,
    )
    make_line(
        api,
        product["id"],
        ascorbate["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=3,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        panel_format=PANEL_FORMAT_LINEAR,
        serving_size_text="2 capsules",
        servings_per_container_declared=30,
        declared_warning_codes=[WARNING_ANTICOAGULANT, WARNING_PEDIATRIC],
    )
    return product, soy_line, panel


def test_the_missing_safety_warning_is_reported_before_the_line_budget(
    api, specialist_headers
):
    """Eleven lines will not fit in eight, and the caller hears about soy instead.

    PRD §2.7 rank 12: "**Mandatory label content and panel capacity**, evaluated in
    this order: serving-size format, then servings-per-container reconciliation, then
    mandatory warning coverage, then disclaimer presence, then the printed line
    budget." The undeclared code is required by PRD §3.5: "an ingredient whose
    ``allergen_code`` is non-null contributes the code formed by prefixing
    ``ALLERGEN_`` to that allergen value — so a soy-bearing ingredient contributes
    ``ALLERGEN_SOYBEAN``".

    Design: Difficulty/priority_pair_validation_conflict/mandatory_warning_error_outranks_panel_line_budget
    """
    _product, soy_line, panel = _linear_panel_missing_the_allergen_warning(
        api, specialist_headers
    )
    assert soy_line["dv_established"] is False
    assert soy_line["percent_dv_declared"] is None

    refused = api.validate_label_panel(panel["id"], specialist_headers)
    body = validate_error(refused, ERR_MANDATORY_WARNING_MISSING, 422)
    assert body["error_id"] != ERR_PANEL_LINE_BUDGET_EXCEEDED

    held = validate_success(api.get_label_panel(panel["id"], specialist_headers), 200)
    assert held["panel_status"] == PANEL_STATUS_DRAFT
    assert held["validated_at"] is None
    assert held["panel_lines_required"] is None
    assert held["panel_lines_allowed"] is None


def test_the_line_budget_complaint_surfaces_once_every_warning_is_declared(
    api, specialist_headers
):
    """Declaring the soy code removes the outranking refusal and the pack still overflows.

    PRD §3.5: "``panel_lines_required`` is assembled by counting: a fixed header block
    of 4 lines, plus one line for each ``ACTIVE`` supplement-facts line of the product,
    plus one dagger-footnote line if at least one of those active lines has
    ``dv_established`` false — one footnote covers all of them, so the value is 1 or 0
    and never more — plus one line for each code in the computed
    ``required_warning_codes``". The allowance is flat: "A ``LINEAR`` panel has a flat
    allowance of 8 lines. ... Validation fails with ``ERR_PANEL_LINE_BUDGET_EXCEEDED``
    (HTTP 422) when ``panel_lines_required`` exceeds ``panel_lines_allowed``".

    Design: Difficulty/priority_pair_validation_conflict/mandatory_warning_error_outranks_panel_line_budget
    """
    _product, _soy_line, panel = _linear_panel_missing_the_allergen_warning(
        api, specialist_headers
    )
    validate_error(
        api.validate_label_panel(panel["id"], specialist_headers),
        ERR_MANDATORY_WARNING_MISSING,
        422,
    )

    amended = validate_success(
        api.patch_label_panel(
            panel["id"],
            {
                "declared_warning_codes": [
                    WARNING_SOYBEAN,
                    WARNING_ANTICOAGULANT,
                    WARNING_PEDIATRIC,
                ]
            },
            specialist_headers,
        ),
        200,
    )
    assert WARNING_SOYBEAN in amended["declared_warning_codes"]

    refused = api.validate_label_panel(panel["id"], specialist_headers)
    body = validate_error(refused, ERR_PANEL_LINE_BUDGET_EXCEEDED, 422)
    assert body["error_id"] != ERR_MANDATORY_WARNING_MISSING

    still_draft = validate_success(
        api.get_label_panel(panel["id"], specialist_headers), 200
    )
    assert still_draft["panel_status"] == PANEL_STATUS_DRAFT
    assert still_draft["validated_at"] is None
