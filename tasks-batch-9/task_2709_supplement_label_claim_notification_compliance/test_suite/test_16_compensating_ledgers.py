"""Two ledgers that must land exactly back where they started.

Releasing a lot and then recalling it has to leave the supplier's released-mass
ledger at its pre-release figure with no drift, and approving a claim and then
withdrawing it has to leave the product's active-claim ledger at its pre-approval
figure with the unit moved into the withdrawn column.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_claim_ledger,
    assert_lot_mass_identity,
    assert_posture,
    assert_risk_index,
    assert_score,
    assert_supplier_ledger,
)
from test_helpers.constants import (
    IDENTITY_METHOD_HPTLC,
    LOT_RECALLED,
    LOT_RELEASED,
    NOTIFICATION_NOT_DUE,
    POSTURE_OPEN,
    SUBSTANTIATION_APPROVED,
    SUBSTANTIATION_WITHDRAWN,
    SUPPLIER_QUALIFIED,
)
from test_helpers.factories import recall_payload, withdrawal_payload
from test_helpers.fixtures import (
    make_accepted_coa,
    make_claim_with_accepted_dossier,
    make_grandfathered_ingredient,
    make_lot,
    make_product,
    make_qualified_supplier,
)

# Two peer-reviewed studies at or below the labeled dose plus one small trial: the
# screening read is 78.00 and the frozen final score settles at 66.00.
BONE_STUDY_SET = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Nyberg 2021 Bone Metab 9:14",
    },
    {
        "study_type": "OBSERVATIONAL_HUMAN",
        "subject_count": 150,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Ibarra 2022 Osteo Cohort 5:60",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 60,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Zhao 2023 Skeletal Trials 3:88",
    },
]


def _two_released_lots(api, specialist_headers, quality_headers):
    """One qualified supplier with 37.25 kg and 12.50 kg both released to manufacturing."""
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Kerala Herb Works",
        country_code="IN",
        audit_score=90,
    )
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Turmeric Rhizome Extract",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1000,
        rdi_mg=None,
    )
    first = make_lot(
        api,
        supplier["id"],
        ingredient["id"],
        quality_headers,
        lot_code="KHW-2026-0011",
        quantity_kg=37.25,
    )
    make_accepted_coa(
        api,
        first["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=99.1,
    )
    second = make_lot(
        api,
        supplier["id"],
        ingredient["id"],
        quality_headers,
        lot_code="KHW-2026-0012",
        quantity_kg=12.50,
    )
    make_accepted_coa(
        api,
        second["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=101.7,
    )
    first = validate_success(api.release_lot(first["id"], quality_headers), 200)
    second = validate_success(api.release_lot(second["id"], quality_headers), 200)
    return supplier, first, second


def test_the_ledger_returns_to_the_value_it_held_before_that_lot_shipped(
    api, specialist_headers, quality_headers
):
    """49.75 kg goes out, 37.25 kg comes back, and 12.50 kg is the answer.

    PRD §2.8: "The consequence that matters most is the compensating pair: releasing a
    lot and then recalling it must leave ``total_released_kg`` at exactly its
    pre-release value, with zero drift at 2-decimal precision." PRD §3.7 states the
    decrement: "The supplier's ``total_released_kg`` is decremented by the same mass,
    restoring it to exactly its pre-release value with no drift at two decimal places,
    and both ``version`` counters advance."

    Design: Difficulty/compensating_invariant/lot_recall_restores_supplier_released_mass_ledger
    """
    supplier, first, second = _two_released_lots(
        api, specialist_headers, quality_headers
    )
    shipped = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert_score(shipped["total_released_kg"], 49.75)

    validate_success(
        api.recall_lot(
            first["id"],
            recall_payload(
                "Retained sample failed a post-release solvent residue retest."
            ),
            quality_headers,
        ),
        200,
    )

    restored = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert_score(restored["total_released_kg"], 12.50)

    untouched = validate_success(
        api.get_ingredient_lot(second["id"], quality_headers), 200
    )
    assert untouched["lot_status"] == LOT_RELEASED
    assert_score(untouched["released_quantity_kg"], 12.50)


def test_the_recalled_lot_moves_its_mass_without_creating_or_destroying_any(
    api, specialist_headers, quality_headers
):
    """The three buckets still sum to the immutable intake quantity.

    PRD §3.7: "It requires the lot to be in ``RELEASED`` and a ``recall_reason``, drives
    ``RELEASED → RECALLED``, stamps ``recalled_at``, and moves the mass again:
    ``rejected_quantity_kg`` becomes the full ``quantity_kg`` and
    ``released_quantity_kg`` returns to 0.00, so the per-lot identity of §2.8 still
    holds." That identity is stated as: "For every ingredient lot,
    ``quarantined_quantity_kg`` plus ``released_quantity_kg`` plus
    ``rejected_quantity_kg`` equals ``quantity_kg``, exactly, at 2-decimal precision on
    kilograms."

    Design: Difficulty/compensating_invariant/lot_recall_restores_supplier_released_mass_ledger
    """
    supplier, first, second = _two_released_lots(
        api, specialist_headers, quality_headers
    )
    recalled = validate_success(
        api.recall_lot(
            first["id"],
            recall_payload(
                "Retained sample failed a post-release solvent residue retest."
            ),
            quality_headers,
        ),
        200,
    )
    assert recalled["lot_status"] == LOT_RECALLED
    assert recalled["recalled_at"] is not None
    assert_score(recalled["rejected_quantity_kg"], 37.25)
    assert_score(recalled["released_quantity_kg"], 0.00)
    assert_score(recalled["quarantined_quantity_kg"], 0.00)
    assert_lot_mass_identity(recalled)

    second_after = validate_success(
        api.get_ingredient_lot(second["id"], quality_headers), 200
    )
    supplier_after = validate_success(
        api.get_supplier(supplier["id"], quality_headers), 200
    )
    assert_supplier_ledger(supplier_after, [recalled, second_after])
    assert supplier_after["coa_rejection_count"] == 0
    assert supplier_after["qualification_status"] == SUPPLIER_QUALIFIED


def _approved_bone_claim(api, specialist_headers, reviewer_headers):
    """A claim whose dossier an independent reviewer has already accepted."""
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Cholecalciferol",
        ingredient_class="VITAMIN",
        daily_intake_mg=1,
        rdi_mg=2,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="D3 Daily",
        net_quantity_g=45,
        servings_per_container=90,
    )
    claim, dossier = make_claim_with_accepted_dossier(
        api,
        product["id"],
        ingredient["id"],
        BONE_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        claim_overrides={
            "claim_text": "Supports bone health",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    return product, claim, dossier


def test_approval_lifts_the_active_claim_ledger_by_exactly_one(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """The counter is a literal count, so one approval is worth exactly one unit.

    PRD §3.4: "Approval drives ``UNDER_SUBSTANTIATION_REVIEW → APPROVED``, stamps
    ``approved_by_user_id`` from ``X-User-ID`` and ``approved_at`` from the logical
    clock, clears ``requires_recheck`` to false, advances the product's
    ``active_claim_count`` by 1, and advances the claim's ``version``." PRD §2.8 defines
    the counter itself: "``active_claim_count`` equals the number of that product's
    claims whose ``substantiation_status`` is ``APPROVED``".

    Design: Difficulty/compensating_invariant/claim_withdrawal_restores_product_active_claim_ledger
    """
    product, claim, dossier = _approved_bone_claim(
        api, specialist_headers, reviewer_headers
    )
    opening = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert opening["active_claim_count"] == 0
    assert opening["withdrawn_claim_count"] == 0
    assert_score(dossier["screening_score"], 78.00)
    assert_score(dossier["final_score"], 66.00)

    approved = validate_success(api.approve_claim(claim["id"], officer_headers), 200)
    assert approved["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert approved["approved_by_user_id"] is not None
    assert approved["requires_recheck"] is False

    lifted = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert lifted["active_claim_count"] == 1
    assert lifted["withdrawn_claim_count"] == 0
    assert_claim_ledger(lifted, [approved])


def test_withdrawal_returns_the_ledger_and_the_index_to_their_opening_values(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """The unit moves out of the active column and into the withdrawn one.

    PRD §3.4: "It requires a ``withdrawal_reason``, drives ``APPROVED → WITHDRAWN``,
    decrements the product's ``active_claim_count`` by 1 and increments its
    ``withdrawn_claim_count`` by 1 so that the ledger identity of §2.8 continues to
    hold, recomputes the product's ``compliance_risk_index`` and then its
    ``label_posture``, and advances the claim's ``version``." PRD §2.8 names that pair
    as the load-bearing case: "approving a claim and then withdrawing it leaves
    ``active_claim_count`` back at its pre-approval value with the unit moved into
    ``withdrawn_claim_count``."

    Design: Difficulty/compensating_invariant/claim_withdrawal_restores_product_active_claim_ledger
    """
    product, claim, _dossier = _approved_bone_claim(
        api, specialist_headers, reviewer_headers
    )
    validate_success(api.approve_claim(claim["id"], officer_headers), 200)

    withdrawn = validate_success(
        api.withdraw_claim(
            claim["id"],
            withdrawal_payload("Sponsor retired the marketing message before launch."),
            officer_headers,
        ),
        200,
    )
    assert withdrawn["substantiation_status"] == SUBSTANTIATION_WITHDRAWN
    assert (
        withdrawn["withdrawal_reason"]
        == "Sponsor retired the marketing message before launch."
    )
    assert withdrawn["approved_by_user_id"] is not None
    assert withdrawn["approved_at"] is not None
    assert withdrawn["notification_status"] == NOTIFICATION_NOT_DUE
    assert withdrawn["notification_due_date"] is None

    settled = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert settled["active_claim_count"] == 0
    assert settled["withdrawn_claim_count"] == 1
    assert_claim_ledger(settled, [withdrawn])

    profile = validate_success(
        api.get_risk_profile(product["id"], specialist_headers), 200
    )
    assert_risk_index(profile, 10)
    assert_posture(profile, POSTURE_OPEN)
    assert profile["requires_label_revision"] is False
