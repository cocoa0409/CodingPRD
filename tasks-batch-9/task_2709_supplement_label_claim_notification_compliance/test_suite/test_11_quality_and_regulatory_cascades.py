"""Two cascades that start in different corners of the record and end far away.

A single failing laboratory result walks four hops from a certificate to an
approved claim, and a single agency letter walks three hops from a notification
package to a printed panel. Neither trigger touches the entity it ultimately
retracts, and each stops at a different point on the label.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_lot_mass_identity,
    assert_panel_computed,
    assert_posture,
    assert_risk_index,
    assert_score,
)
from test_helpers.constants import (
    COA_REJECTED,
    DOSSIER_ACCEPTED,
    DOSSIER_UNDER_REVIEW,
    ELIGIBILITY_NDI_OBJECTED,
    ELIGIBILITY_NDI_PENDING,
    FDA_DISCLAIMER_TEXT,
    LIFECYCLE_LABEL_LOCKED,
    LOT_RECALLED,
    NDI_STATUS_OBJECTED,
    NDI_STATUS_SUBMITTED,
    PANEL_STATUS_LOCKED,
    PANEL_STATUS_SUPERSEDED,
    PANEL_STATUS_VALIDATED,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    SUBSTANTIATION_APPROVED,
    SUBSTANTIATION_REVISION_REQUESTED,
    SUPPLIER_PROBATION,
    SUPPLIER_QUALIFIED,
    WARNING_PEDIATRIC,
)
from test_helpers.factories import review_payload
from test_helpers.fixtures import (
    make_approved_claim,
    make_coa,
    make_grandfathered_ingredient,
    make_line,
    make_locked_panel,
    make_ndi_pending_ingredient,
    make_objected_notification,
    make_product,
    make_qualified_supplier,
    make_released_lot,
    make_validated_panel,
)

WARNING_ANTICOAGULANT = "CONTRAINDICATION_ANTICOAGULANT"

# Two peer-reviewed trials and one cohort: the frozen final score is 78.00, well
# clear of the acceptance threshold, so the cascade is the only thing at work.
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


def _released_lot_under_a_finished_label(
    api, specialist_headers, reviewer_headers, officer_headers, quality_headers
):
    """A complete record: released lot, approved claim, locked panel, one bad certificate."""
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Hebei Botanicals",
        country_code="CN",
        audit_score=85,
    )
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    lot, _accepted = make_released_lot(
        api,
        supplier["id"],
        ingredient["id"],
        quality_headers,
        lot_code="L-2026-001",
        quantity_kg=100,
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
    claim, dossier = make_approved_claim(
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
    panel = make_locked_panel(
        api,
        product["id"],
        specialist_headers,
        officer_headers,
        servings_per_container_declared=60,
        disclaimer_text=FDA_DISCLAIMER_TEXT,
    )
    failing = make_coa(
        api,
        lot["id"],
        quality_headers,
        identity_match=False,
        assay_percent_of_label=99.0,
    )
    return supplier, lot, product, claim, dossier, panel, failing


def _reject(api, coa_id, quality_headers):
    """Reject the certificate, firing the whole four-hop chain in one request."""
    return validate_success(
        api.review_coa(
            coa_id,
            review_payload(
                "REJECT",
                rejection_reason="Identity peak does not match reference standard",
            ),
            quality_headers,
        ),
        200,
    )


def test_one_failing_certificate_walks_from_the_lab_bench_to_the_supplier_ledger(
    api, specialist_headers, reviewer_headers, officer_headers, quality_headers
):
    """Hops one to three: the counter, the supplier standing and the mass ledger.

    PRD §3.7: "First, every product with an ``ACTIVE`` supplement-facts line on the
    lot's ingredient has its ``rejected_coa_count`` incremented by 1, and its
    ``compliance_risk_index`` recomputed. Second, the lot itself is disposed of
    according to where it stood: a lot in ``QUARANTINED`` moves ``QUARANTINED →
    REJECTED`` with its full mass moved from ``quarantined_quantity_kg`` into
    ``rejected_quantity_kg``, while a lot already in ``RELEASED`` moves ``RELEASED →
    RECALLED`` with ``recall_reason`` recorded as ``COA_REJECTED``". The third hop is
    counted too: "a count reaching 1 moves a ``QUALIFIED`` supplier ``QUALIFIED →
    PROBATION``".

    Design: Difficulty/transitive_cascade/coa_rejection_cascades_four_hops_to_claim_recheck
    """
    supplier, lot, product, _claim, _dossier, _panel, failing = (
        _released_lot_under_a_finished_label(
            api, specialist_headers, reviewer_headers, officer_headers, quality_headers
        )
    )
    assert failing["coa_acceptable"] is False
    before = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert before["qualification_status"] == SUPPLIER_QUALIFIED
    assert_score(before["total_released_kg"], 100.00)

    rejected = _reject(api, failing["id"], quality_headers)
    assert rejected["coa_status"] == COA_REJECTED
    assert rejected["coa_acceptable"] is False

    hop_one = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert hop_one["rejected_coa_count"] == 1
    assert_risk_index(hop_one, 18)

    hop_two = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert hop_two["coa_rejection_count"] == 1
    assert hop_two["qualification_status"] == SUPPLIER_PROBATION

    hop_three = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert hop_three["lot_status"] == LOT_RECALLED
    assert_score(hop_three["rejected_quantity_kg"], 100.00)
    assert_score(hop_three["released_quantity_kg"], 0.00)
    assert_lot_mass_identity(hop_three)
    assert_score(hop_two["total_released_kg"], 0.00)


def test_the_fourth_hop_retracts_the_claim_and_stops_short_of_the_printed_panel(
    api, specialist_headers, reviewer_headers, officer_headers, quality_headers
):
    """Probation restricts, and a restriction retracts claim work but not the label.

    PRD §3.9: "Every claim of the product whose ``substantiation_status`` is
    ``APPROVED`` is dragged ``APPROVED → REVISION_REQUESTED`` with
    ``requires_recheck`` set true, and the product's ``active_claim_count`` is
    decremented by 1 for each such claim". The dossier follows: "a substantiation
    dossier sitting in ``ACCEPTED`` is dragged ``ACCEPTED → UNDER_REVIEW``, and in the
    process its ``reviewed_by_user_id``, ``reviewed_at`` and ``review_decision`` are
    all cleared back to null". Only the frozen band dismantles the label: "every panel
    of the product whose ``panel_status`` is ``DRAFT``, ``VALIDATED`` or ``LOCKED`` is
    driven to ``SUPERSEDED``".

    Design: Difficulty/transitive_cascade/coa_rejection_cascades_four_hops_to_claim_recheck
    """
    _supplier, _lot, product, claim, dossier, panel, failing = (
        _released_lot_under_a_finished_label(
            api, specialist_headers, reviewer_headers, officer_headers, quality_headers
        )
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert dossier["dossier_status"] == DOSSIER_ACCEPTED
    assert_score(dossier["final_score"], 78.00)

    _reject(api, failing["id"], quality_headers)

    restricted = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert_posture(restricted, POSTURE_RESTRICTED)
    assert restricted["requires_label_revision"] is True
    assert restricted["active_claim_count"] == 0
    assert restricted["lifecycle_status"] == LIFECYCLE_LABEL_LOCKED

    dragged = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert dragged["substantiation_status"] == SUBSTANTIATION_REVISION_REQUESTED
    assert dragged["requires_recheck"] is True

    reopened = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert reopened["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert_score(reopened["final_score"], 78.00)
    assert reopened["reviewed_by_user_id"] is None
    assert reopened["reviewed_at"] is None
    assert reopened["review_decision"] is None

    spared = validate_success(api.get_label_panel(panel["id"], specialist_headers), 200)
    assert spared["panel_status"] == PANEL_STATUS_LOCKED


def _pending_ingredient_on_a_validated_label(api, specialist_headers):
    """One ingredient awaiting the agency, one product, one VALIDATED panel."""
    ingredient, notification = make_ndi_pending_ingredient(
        api,
        specialist_headers,
        ingredient_name="Nicotinamide Riboside",
        ingredient_class="VITAMIN",
        pre_dshea_marketed=False,
        chemical_alteration=False,
        daily_intake_mg=300,
        rdi_mg=400,
        contraindication_code="ANTICOAGULANT",
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="NR Cellular",
        net_quantity_g=60,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        amount_per_serving_mg=100,
        panel_position=1,
    )
    panel = make_validated_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=30,
        declared_warning_codes=[WARNING_ANTICOAGULANT, WARNING_PEDIATRIC],
    )
    return ingredient, notification, product, panel


def test_an_agency_objection_freezes_every_product_carrying_the_article(
    api, specialist_headers
):
    """The letter lands on the package and the freeze lands on the product.

    PRD §3.2: "It drives ``SUBMITTED → OBJECTED``, stamps ``agency_response_at``,
    records the supplied ``agency_objection_reason`` on the package, and cascades the
    ingredient ``NDI_PENDING → NDI_OBJECTED``." The propagation is immediate: "every
    product carrying that ingredient on an ``ACTIVE`` supplement-facts line has its
    ``label_posture`` recomputed, and because an ``NDI_OBJECTED`` ingredient on an
    active line is one of the three frozen conditions of §2.9, each of those products
    reaches ``FROZEN``".

    Design: Difficulty/transitive_cascade/ndi_objection_cascades_three_hops_to_frozen_panel
    """
    ingredient, notification, product, _panel = _pending_ingredient_on_a_validated_label(
        api, specialist_headers
    )
    assert ingredient["eligibility_status"] == ELIGIBILITY_NDI_PENDING
    assert notification["notification_status"] == NDI_STATUS_SUBMITTED
    assert notification["waiting_period_end"].startswith("2026-10-15T00:00:00")

    objected = make_objected_notification(api, notification["id"], specialist_headers)
    assert objected["notification_status"] == NDI_STATUS_OBJECTED
    assert objected["agency_response_at"] is not None
    assert objected["waiting_period_end"].startswith("2026-10-15T00:00:00")

    hop_one = validate_success(
        api.get_ingredient(ingredient["id"], specialist_headers), 200
    )
    assert hop_one["eligibility_status"] == ELIGIBILITY_NDI_OBJECTED

    hop_two = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert_posture(hop_two, POSTURE_FROZEN)
    assert hop_two["requires_label_revision"] is True


def test_the_freeze_supersedes_the_panel_without_disturbing_its_computed_figures(
    api, specialist_headers
):
    """A superseded panel keeps the four numbers validation wrote onto it.

    PRD §3.9: "Both set ``label_posture`` to ``FROZEN`` and ``requires_label_revision``
    to true, and both then dismantle the printed label: every panel of the product
    whose ``panel_status`` is ``DRAFT``, ``VALIDATED`` or ``LOCKED`` is driven to
    ``SUPERSEDED``". Nothing on the risk side moves, because the posture came from the
    ingredient rather than from a counter: PRD §2.9 fixes that floor as "a floor of 10"
    before any event is added.

    Design: Difficulty/transitive_cascade/ndi_objection_cascades_three_hops_to_frozen_panel
    """
    _ingredient, notification, product, panel = _pending_ingredient_on_a_validated_label(
        api, specialist_headers
    )
    assert panel["panel_status"] == PANEL_STATUS_VALIDATED
    assert_panel_computed(
        panel,
        required_warning_codes=[WARNING_ANTICOAGULANT, WARNING_PEDIATRIC],
        panel_lines_required=7,
        panel_lines_allowed=20,
        panel_total_dv_coverage_pct=25,
    )

    make_objected_notification(api, notification["id"], specialist_headers)

    dismantled = validate_success(
        api.get_label_panel(panel["id"], specialist_headers), 200
    )
    assert dismantled["panel_status"] == PANEL_STATUS_SUPERSEDED
    assert_panel_computed(
        dismantled,
        required_warning_codes=[WARNING_ANTICOAGULANT, WARNING_PEDIATRIC],
        panel_lines_required=7,
        panel_lines_allowed=20,
        panel_total_dv_coverage_pct=25,
    )

    untouched = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert_risk_index(untouched, 10)
    assert untouched["rejected_coa_count"] == 0
    assert untouched["serious_ae_count"] == 0
