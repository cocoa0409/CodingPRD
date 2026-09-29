"""Two operations blocked by the state of a resource they never name.

A claim submission carries no ingredient identifier, yet the ingredient's
eligibility decides it; a lot release carries no supplier identifier, yet the
supplier's standing decides it. Each pair proves the gate by moving only the
distant resource and repeating the identical request.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INGREDIENT_NOT_ELIGIBLE,
    ERR_SUPPLIER_NOT_QUALIFIED,
)
from test_helpers.assertions import assert_lot_mass_identity, assert_score
from test_helpers.constants import (
    DECISION_PROBATION,
    DECISION_REINSTATE,
    DOSSIER_DRAFT,
    DOSSIER_UNDER_REVIEW,
    ELIGIBILITY_NDI_ACKNOWLEDGED,
    ELIGIBILITY_NDI_PENDING,
    IDENTITY_METHOD_HPTLC,
    LOT_QUARANTINED,
    LOT_RELEASED,
    NDI_STATUS_ACKNOWLEDGED,
    RESPONSE_ACKNOWLEDGE,
    SUBSTANTIATION_DRAFT,
    SUBSTANTIATION_UNDER_REVIEW,
    SUPPLIER_PROBATION,
    SUPPLIER_QUALIFIED,
)
from test_helpers.factories import (
    agency_response_payload,
    qualification_decision_payload,
)
from test_helpers.fixtures import (
    make_accepted_coa,
    make_claim,
    make_dossier_with_studies,
    make_grandfathered_ingredient,
    make_lot,
    make_ndi_pending_ingredient,
    make_product,
    make_qualified_supplier,
    set_clock,
)

ONE_TRIAL = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Beta-glucan immune RCT 2025",
    }
]


def _claim_on_a_pending_ingredient(api, specialist_headers):
    """A ready dossier on a claim whose ingredient is still waiting on the agency."""
    ingredient, notification = make_ndi_pending_ingredient(
        api,
        specialist_headers,
        ingredient_name="Fermented Beta-Glucan XR",
        ingredient_class="BOTANICAL",
        daily_intake_mg=250,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Immune Beta",
        net_quantity_g=90,
        servings_per_container=30,
    )
    claim = make_claim(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        claim_text="Supports healthy immune response",
        claim_type="STRUCTURE_FUNCTION",
    )
    dossier = make_dossier_with_studies(
        api,
        claim["id"],
        ONE_TRIAL,
        specialist_headers,
        dossier_summary="One randomized controlled human trial at the labeled dose.",
    )
    claim = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    return ingredient, notification, claim, dossier


def test_the_claim_cannot_enter_review_while_its_ingredient_awaits_the_agency(
    api, specialist_headers
):
    """The submission names only the claim, and an ingredient two hops away refuses it.

    PRD §3.4: "The claim's ingredient must have ``eligibility_status`` of
    ``GRANDFATHERED`` or ``NDI_ACKNOWLEDGED``, and anything else is refused with
    ``ERR_INGREDIENT_NOT_ELIGIBLE`` (HTTP 409)." Nothing on the dossier side has moved:
    PRD §3.4 pins the freeze to the successful edge only, "Submitting a claim for
    substantiation review is the transition that freezes the score".

    Design: Difficulty/cross_entity_state_dependency/claim_review_gated_by_ingredient_ndi_pending_state
    """
    ingredient, notification, claim, dossier = _claim_on_a_pending_ingredient(
        api, specialist_headers
    )
    assert ingredient["eligibility_status"] == ELIGIBILITY_NDI_PENDING
    assert notification["waiting_period_end"].startswith("2026-10-15T00:00:00")

    refused = api.submit_claim_for_review(claim["id"], specialist_headers)
    validate_error(refused, ERR_INGREDIENT_NOT_ELIGIBLE, 409)

    held = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert held["substantiation_status"] == SUBSTANTIATION_DRAFT
    assert held["version"] == claim["version"]

    unfrozen = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert unfrozen["dossier_status"] == DOSSIER_DRAFT
    assert unfrozen["final_score"] is None


def test_an_acknowledged_ingredient_unblocks_the_identical_submission(
    api, specialist_headers
):
    """Moving the distant ingredient, and nothing else, admits the same request.

    PRD §3.2: "An ``ACKNOWLEDGE`` may only be recorded once the waiting period has
    actually run — the logical clock must be at or after the package's
    ``waiting_period_end`` — and a premature acknowledgement is refused with
    ``ERR_WAITING_PERIOD_NOT_ELAPSED`` (HTTP 409)." The cascade then clears the article:
    "An acknowledgement drives ``SUBMITTED → ACKNOWLEDGED``, stamps
    ``agency_response_at`` from the logical clock, and cascades the ingredient
    ``NDI_PENDING → NDI_ACKNOWLEDGED``, at last clearing the article for labelled use."

    Design: Difficulty/cross_entity_state_dependency/claim_review_gated_by_ingredient_ndi_pending_state
    """
    ingredient, notification, claim, dossier = _claim_on_a_pending_ingredient(
        api, specialist_headers
    )
    validate_error(
        api.submit_claim_for_review(claim["id"], specialist_headers),
        ERR_INGREDIENT_NOT_ELIGIBLE,
        409,
    )

    set_clock(api, "2026-10-15T00:00:00Z", specialist_headers)
    answered = validate_success(
        api.record_agency_response(
            notification["id"],
            agency_response_payload(RESPONSE_ACKNOWLEDGE),
            specialist_headers,
        ),
        200,
    )
    assert answered["notification_status"] == NDI_STATUS_ACKNOWLEDGED

    cleared = validate_success(
        api.get_ingredient(ingredient["id"], specialist_headers), 200
    )
    assert cleared["eligibility_status"] == ELIGIBILITY_NDI_ACKNOWLEDGED

    admitted = validate_success(
        api.submit_claim_for_review(claim["id"], specialist_headers), 200
    )
    assert admitted["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW
    assert admitted["revision_round"] == 0

    frozen = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert frozen["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert frozen["final_score"] is not None


def _verified_lot_on_a_probation_supplier(api, specialist_headers, quality_headers):
    """A fully tested quarantined lot whose supplier has since been put on probation."""
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Andes Botanica SA",
        country_code="PE",
        audit_score=85,
    )
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    lot = make_lot(
        api,
        supplier["id"],
        ingredient["id"],
        quality_headers,
        lot_code="AB-2026-0440",
        quantity_kg=40.00,
    )
    make_accepted_coa(
        api,
        lot["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=103.4,
    )
    validate_success(
        api.qualification_decision(
            supplier["id"],
            qualification_decision_payload(DECISION_PROBATION),
            quality_headers,
        ),
        200,
    )
    return supplier, lot


def test_a_probation_supplier_blocks_the_release_of_a_fully_tested_lot(
    api, specialist_headers, quality_headers
):
    """Every test on the material passed; the standing of its maker did not.

    PRD §3.7: "Releasing a quarantined lot to manufacturing is the payoff of all that
    testing, and it has three preconditions. The lot's ``lot_status`` must be
    ``QUARANTINED``. The lot's own supplier must have ``qualification_status`` equal to
    ``QUALIFIED``, refused otherwise with ``ERR_SUPPLIER_NOT_QUALIFIED``." The mass must
    not budge, because PRD §2.8 requires that "Every lot transition therefore *moves*
    mass between the three buckets rather than adjusting one of them in isolation."

    Design: Difficulty/cross_entity_state_dependency/lot_release_gated_by_supplier_probation_state
    """
    supplier, lot = _verified_lot_on_a_probation_supplier(
        api, specialist_headers, quality_headers
    )
    tested = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert tested["identity_verified"] is True
    assert tested["lot_status"] == LOT_QUARANTINED

    refused = api.release_lot(lot["id"], quality_headers)
    validate_error(refused, ERR_SUPPLIER_NOT_QUALIFIED, 409)

    held = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert held["lot_status"] == LOT_QUARANTINED
    assert_score(held["quarantined_quantity_kg"], 40.00)
    assert_score(held["released_quantity_kg"], 0.00)
    assert_lot_mass_identity(held)

    standing = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert standing["qualification_status"] == SUPPLIER_PROBATION
    assert_score(standing["total_released_kg"], 0.00)


def test_a_reinstatement_carrying_a_remediation_reference_unblocks_the_release(
    api, specialist_headers, quality_headers
):
    """The corrective-action file restores the standing and the identical call succeeds.

    PRD §3.7: "``REINSTATE`` is legal only from ``PROBATION``, requires a non-empty
    ``remediation_reference`` naming the corrective-action file — a missing one is
    refused with ``ERR_REMEDIATION_REFERENCE_REQUIRED`` (HTTP 422) — and drives
    ``PROBATION → QUALIFIED``, recording the reference and resetting
    ``coa_rejection_count`` to 0." Release then moves the mass as PRD §3.7 prescribes:
    "Release drives ``QUARANTINED → RELEASED``, stamps ``released_at`` from the logical
    clock, moves the mass so that ``released_quantity_kg`` becomes the full
    ``quantity_kg`` and ``quarantined_quantity_kg`` falls to 0.00, increments the
    supplier's ``total_released_kg`` by that mass".

    Design: Difficulty/cross_entity_state_dependency/lot_release_gated_by_supplier_probation_state
    """
    supplier, lot = _verified_lot_on_a_probation_supplier(
        api, specialist_headers, quality_headers
    )
    validate_error(
        api.release_lot(lot["id"], quality_headers), ERR_SUPPLIER_NOT_QUALIFIED, 409
    )

    reinstated = validate_success(
        api.qualification_decision(
            supplier["id"],
            qualification_decision_payload(
                DECISION_REINSTATE, remediation_reference="CAPA-2026-014"
            ),
            quality_headers,
        ),
        200,
    )
    assert reinstated["qualification_status"] == SUPPLIER_QUALIFIED
    assert reinstated["remediation_reference"] == "CAPA-2026-014"

    released = validate_success(api.release_lot(lot["id"], quality_headers), 200)
    assert released["lot_status"] == LOT_RELEASED
    assert released["released_at"] is not None
    assert_score(released["released_quantity_kg"], 40.00)
    assert_score(released["quarantined_quantity_kg"], 0.00)
    assert_lot_mass_identity(released)

    ledger = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert_score(ledger["total_released_kg"], 40.00)
    assert ledger["coa_rejection_count"] == 0
