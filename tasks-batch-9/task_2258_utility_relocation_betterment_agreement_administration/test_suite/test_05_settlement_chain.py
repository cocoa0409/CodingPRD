"""The two eligible-cost variants, the nine-step chain and the settlement preview."""
from test_helpers import (
    AS_BUILT_REFERENCE,
    CANON_BETTERMENT_AMOUNT_CENTS,
    CANON_BETTERMENT_RATIO,
    CANON_ESTIMATE_BETTERMENT_CREDIT_CENTS,
    CANON_ESTIMATE_ELIGIBLE_CENTS,
    CANON_ESTIMATE_INDIRECT_CENTS,
    CANON_ESTIMATE_NET_ALLOWABLE_CENTS,
    CANON_ESTIMATE_OWNER_SHARE_CENTS,
    CANON_ESTIMATE_PARTICIPATION_TIER_PCT,
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    assert_settlement_figures,
    assert_version_unchanged,
    make_external_auditor_headers,
    read_agreement,
    read_cost_document,
    read_project,
    read_settlement_preview,
    settle_agreement,
    world_agreement_drafted,
    world_cost_documents,
)

WATER_OWNER = {
    "legal_name": "Northline Water District",
    "utility_type": "WATER",
    "is_public_agency": False,
    "indirect_cost_rate_pct": 0.00,
}

WATER_MAIN_FACILITY = {
    "facility_type": "WATER_MAIN",
    "station_begin": 300.0,
    "station_end": 320.0,
    "offset_ft": 8.0,
    "depth_in": 60,
    "material": "Ductile iron",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

FIVE_DOCUMENT_BILLING = [
    {
        "doc_type": "LABOR",
        "amount_cents": 12_345_678,
        "incurred_on": "2027-04-02T00:00:00Z",
        "support_reference": "PR-2027-04-A",
        "review": "ACCEPT",
    },
    {
        "doc_type": "MATERIAL",
        "amount_cents": 9_876_543,
        "incurred_on": "2027-04-10T00:00:00Z",
        "support_reference": "INV-88213",
        "review": "ACCEPT",
    },
    {
        "doc_type": "EQUIPMENT",
        "amount_cents": 5_555_555,
        "incurred_on": "2027-04-15T00:00:00Z",
        "support_reference": "EQ-4410",
        "review": "DISALLOW",
        "exclusion_reason": "NOT_SUPPORTED",
    },
    {
        "doc_type": "CREDIT_SALVAGE",
        "amount_cents": 1_000_000,
        "incurred_on": "2027-04-20T00:00:00Z",
        "support_reference": "SALV-77",
        "review": "ACCEPT",
    },
    {
        "doc_type": "CONTRACT",
        "amount_cents": 30_000_000,
        "incurred_on": "2027-05-01T00:00:00Z",
        "support_reference": "SUB-9001",
        "review": "ACCEPT",
    },
]

FOUR_ACCEPTED_LINES = [
    {
        "doc_type": "LABOR",
        "amount_cents": 12_345_678,
        "incurred_on": "2027-05-10T00:00:00Z",
        "support_reference": "Certified payroll 2027-05-10",
        "review": "ACCEPT",
    },
    {
        "doc_type": "MATERIAL",
        "amount_cents": 9_876_543,
        "incurred_on": "2027-05-20T00:00:00Z",
        "support_reference": "Conductor and duct invoices",
        "review": "ACCEPT",
    },
    {
        "doc_type": "CREDIT_SALVAGE",
        "amount_cents": 1_000_000,
        "incurred_on": "2027-05-25T00:00:00Z",
        "support_reference": "Copper salvage ticket",
        "review": "ACCEPT",
    },
    {
        "doc_type": "CONTRACT",
        "amount_cents": 30_000_000,
        "incurred_on": "2027-06-01T00:00:00Z",
        "support_reference": "Boring subcontract final",
        "review": "ACCEPT",
    },
]

SINGLE_LABOR_LINE = [
    {
        "doc_type": "LABOR",
        "amount_cents": 12_345_678,
        "incurred_on": "2027-05-10T00:00:00Z",
        "support_reference": "Certified payroll 2027-05-10",
        "review": "ACCEPT",
    }
]


def test_the_estimate_variant_ignores_every_reviewed_cost_document(api):
    """PRD 3.8: "Under `ESTIMATE_BASIS`, which holds from drafting until final
    settlement, `eligible_cost_cents` is simply the governing plan's
    `estimated_cost_cents`, taken verbatim."

    Design: Difficulty/dual_variant_calc/agreement_eligible_cost_estimate_versus_actual_basis
    """
    world = world_cost_documents(api, documents=FIVE_DOCUMENT_BILLING)
    assert world["plan"]["betterment_ratio"] == CANON_BETTERMENT_RATIO

    agreement = read_agreement(api, world["agreement_id"])
    assert_settlement_figures(
        agreement,
        cost_basis="ESTIMATE_BASIS",
        eligible_cost_cents=CANON_ESTIMATE_ELIGIBLE_CENTS,
        indirect_cost_cents=CANON_ESTIMATE_INDIRECT_CENTS,
        betterment_credit_cents=CANON_ESTIMATE_BETTERMENT_CREDIT_CENTS,
        net_allowable_cents=CANON_ESTIMATE_NET_ALLOWABLE_CENTS,
        participation_tier_pct=CANON_ESTIMATE_PARTICIPATION_TIER_PCT,
        state_share_cents=CANON_ESTIMATE_STATE_SHARE_CENTS,
        owner_share_cents=CANON_ESTIMATE_OWNER_SHARE_CENTS,
    )
    assert agreement["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert read_cost_document(api, world["document_ids"][4])["review_status"] == "ACCEPTED"


def test_the_actual_variant_walks_the_accrual_and_drops_the_straddling_document(api):
    """PRD 3.8: "If the candidate total would be greater than the agreement's
    `not_to_exceed_cents`, the document is excluded whole — marked with
    `exclusion_reason` `EXCEEDS_NOT_TO_EXCEED_CAP` — the running total is left
    untouched, and the walk **continues to the following documents**, so a later,
    smaller document can still be included after a large one was skipped."

    Design: Difficulty/dual_variant_calc/agreement_eligible_cost_estimate_versus_actual_basis
    """
    world = world_cost_documents(api, documents=FIVE_DOCUMENT_BILLING)
    labor_id, _material_id, equipment_id, _salvage_id, contract_id = world["document_ids"]

    settled = settle_agreement(api, world["agreement_id"], "ASB-2258-0007")

    assert_settlement_figures(
        settled,
        cost_basis="ACTUAL_BASIS",
        eligible_cost_cents=21_222_221,
        indirect_cost_cents=2_652_778,
        betterment_credit_cents=7_639_999,
        net_allowable_cents=16_235_000,
        participation_tier_pct=95,
        state_share_cents=15_423_250,
        owner_share_cents=811_750,
    )
    assert settled["settlement_status"] == "SETTLED"
    assert settled["execution_status"] == "EXECUTED"

    contract = read_cost_document(api, contract_id)
    assert contract["review_status"] == "DISALLOWED"
    assert contract["exclusion_reason"] == "EXCEEDS_NOT_TO_EXCEED_CAP"
    assert contract["disallowed_amount_cents"] == 30_000_000

    assert read_cost_document(api, labor_id)["review_status"] == "ACCEPTED"
    assert read_cost_document(api, equipment_id)["exclusion_reason"] == "NOT_SUPPORTED"

    project = read_project(api, world["project_id"])
    assert project["total_committed_reimbursement_cents"] == 15_423_250


def test_drafting_pins_every_intermediate_of_the_nine_step_chain(api):
    """PRD 3.8: "The `participation_tier_pct` is selected from the net allowable —
    never from the gross — and is applied to the whole net allowable as a single
    rate, never marginally."

    Design: Difficulty/combinatorial_formula/settlement_nine_step_chain_pinned_at_every_intermediate
    """
    world = world_agreement_drafted(api)
    plan = world["plan"]
    agreement = world["agreement"]

    assert plan["betterment_ratio"] == CANON_BETTERMENT_RATIO
    assert plan["betterment_amount_cents"] == CANON_BETTERMENT_AMOUNT_CENTS

    assert_settlement_figures(
        agreement,
        cost_basis="ESTIMATE_BASIS",
        eligible_cost_cents=40_000_000,
        indirect_cost_cents=5_000_000,
        betterment_credit_cents=14_400_000,
        net_allowable_cents=30_600_000,
        participation_tier_pct=95,
        state_share_cents=29_070_000,
        owner_share_cents=1_530_000,
    )
    gross_allowable = (
        agreement["eligible_cost_cents"] + agreement["indirect_cost_cents"]
    )
    assert gross_allowable == 45_000_000
    assert (
        gross_allowable - agreement["betterment_credit_cents"]
        == agreement["net_allowable_cents"]
    )
    assert (
        agreement["state_share_cents"] + agreement["owner_share_cents"] == 30_600_000
    )


def test_accepting_a_document_reruns_the_chain_on_the_current_basis(api):
    """PRD 3.8: "From the eligible direct cost, the State's share and the owner's
    residual are derived in nine ordered steps, and the same chain runs at
    drafting, at each cost-document disposition while the agreement is in final
    billing, and at final settlement."

    Design: Difficulty/combinatorial_formula/settlement_nine_step_chain_pinned_at_every_intermediate
    """
    world = world_cost_documents(api, documents=SINGLE_LABOR_LINE)

    agreement = read_agreement(api, world["agreement_id"])
    assert_settlement_figures(
        agreement,
        cost_basis="ESTIMATE_BASIS",
        eligible_cost_cents=40_000_000,
        indirect_cost_cents=5_000_000,
        betterment_credit_cents=14_400_000,
        net_allowable_cents=30_600_000,
        participation_tier_pct=95,
        state_share_cents=29_070_000,
        owner_share_cents=1_530_000,
        not_to_exceed_cents=45_000_000,
    )
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 29_070_000


def test_a_net_allowable_of_exactly_five_million_takes_the_full_tier(api):
    """PRD 3.8: "A net allowable at or below 5,000,000 cents (fifty thousand
    dollars) takes a tier of 100."

    Design: Difficulty/boundary_precision_check/participation_tier_boundary_at_five_million_net_allowable
    """
    world = world_agreement_drafted(
        api,
        not_to_exceed_cents=5_000_000,
        project_overrides={"name": "SR-14 Minor Relocations"},
        owner_overrides=WATER_OWNER,
        facility_overrides=WATER_MAIN_FACILITY,
        conflict_overrides={"conflict_station": 310.0, "clearance_deficiency_in": 8},
        plan_overrides={
            "estimated_cost_cents": 5_000_000,
            "replacement_in_kind_cost_cents": 5_000_000,
            "proposed_capacity_ratio": 1.00,
            "work_days": 4,
        },
    )
    assert world["plan"]["betterment_ratio"] == 0.0
    assert world["conflict"]["state_share_pct"] == 100

    assert_settlement_figures(
        world["agreement"],
        eligible_cost_cents=5_000_000,
        indirect_cost_cents=0,
        betterment_credit_cents=0,
        net_allowable_cents=5_000_000,
        participation_tier_pct=100,
        state_share_cents=5_000_000,
        owner_share_cents=0,
    )


def test_one_cent_past_the_tier_ceiling_costs_the_owner_a_quarter_million(api):
    """PRD 3.8: "A net allowable above that but at or below 50,000,000 cents (five
    hundred thousand dollars) takes a tier of 95."

    Design: Difficulty/boundary_precision_check/participation_tier_boundary_at_five_million_net_allowable
    """
    world = world_agreement_drafted(
        api,
        not_to_exceed_cents=5_000_001,
        project_overrides={"name": "SR-14 Minor Relocations"},
        owner_overrides=WATER_OWNER,
        facility_overrides={
            **WATER_MAIN_FACILITY,
            "station_begin": 400.0,
            "station_end": 420.0,
        },
        conflict_overrides={"conflict_station": 410.0, "clearance_deficiency_in": 8},
        plan_overrides={
            "estimated_cost_cents": 5_000_001,
            "replacement_in_kind_cost_cents": 5_000_001,
            "proposed_capacity_ratio": 1.00,
            "work_days": 4,
        },
    )
    assert world["plan"]["betterment_ratio"] == 0.0

    assert_settlement_figures(
        world["agreement"],
        eligible_cost_cents=5_000_001,
        indirect_cost_cents=0,
        betterment_credit_cents=0,
        net_allowable_cents=5_000_001,
        participation_tier_pct=95,
        state_share_cents=4_750_001,
        owner_share_cents=250_000,
    )


def test_final_settlement_moves_the_committed_ledger_by_the_revision_delta(api):
    """PRD 3.8: "Because an agreement stays `EXECUTED` across its settlement, a
    final settlement that revises `state_share_cents` moves the ledger by exactly
    the revision delta."

    Design: Corner/calculations/final_settlement_switches_the_basis_and_moves_the_ledger_by_the_exact_delta
    """
    world = world_cost_documents(api, documents=SINGLE_LABOR_LINE)
    before = read_agreement(api, world["agreement_id"])
    assert before["cost_basis"] == "ESTIMATE_BASIS"
    assert before["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
    ledger_before = read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ]
    assert ledger_before == CANON_ESTIMATE_STATE_SHARE_CENTS

    preview = read_settlement_preview(api, world["agreement_id"])
    assert_settlement_figures(
        preview,
        cost_basis="ACTUAL_BASIS",
        eligible_cost_cents=12_345_678,
        indirect_cost_cents=1_543_210,
        betterment_credit_cents=4_444_444,
        net_allowable_cents=9_444_444,
        state_share_cents=8_972_222,
        included_document_count=1,
        excluded_document_count=0,
    )
    assert_version_unchanged(before, read_agreement(api, world["agreement_id"]))

    settled = settle_agreement(api, world["agreement_id"], AS_BUILT_REFERENCE)
    assert_settlement_figures(
        settled,
        cost_basis="ACTUAL_BASIS",
        eligible_cost_cents=12_345_678,
        indirect_cost_cents=1_543_210,
        betterment_credit_cents=4_444_444,
        net_allowable_cents=9_444_444,
        participation_tier_pct=95,
        state_share_cents=8_972_222,
        owner_share_cents=472_222,
    )
    assert settled["settlement_status"] == "SETTLED"
    assert settled["execution_status"] == "EXECUTED"
    assert settled["as_built_reference"] == AS_BUILT_REFERENCE

    ledger_after = read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ]
    assert ledger_after == 8_972_222
    assert ledger_after - ledger_before == -20_097_778

    document = read_cost_document(api, world["document_ids"][0])
    assert document["review_status"] == "ACCEPTED"
    assert document["disallowed_amount_cents"] == 0


def test_the_preview_shows_the_cutoff_without_disallowing_anything(api):
    """PRD 3.8: "That per-document test is the point of the algorithm, and summing
    every eligible row and then clamping the total to the ceiling is a different
    and wrong answer whenever one document straddles the ceiling: rows of
    12,345,678, then 9,876,543, then a 1,000,000 salvage credit, then 30,000,000,
    against a ceiling of 45,000,000, accrue to 21,222,221 under the rule above,
    while sum-then-clamp yields 45,000,000."

    Design: Corner/endpoints/settlement_preview_shows_the_chronological_cutoff_without_touching_a_row
    """
    world = world_cost_documents(api, documents=FOUR_ACCEPTED_LINES)
    before = read_agreement(api, world["agreement_id"])
    auditor = make_external_auditor_headers()

    preview = read_settlement_preview(api, world["agreement_id"], auditor)

    assert_settlement_figures(
        preview,
        eligible_cost_cents=21_222_221,
        indirect_cost_cents=2_652_778,
        betterment_credit_cents=7_639_999,
        net_allowable_cents=16_235_000,
        participation_tier_pct=95,
        state_share_cents=15_423_250,
        owner_share_cents=811_750,
        included_document_count=3,
        excluded_document_count=1,
    )
    assert preview["eligible_cost_cents"] != 45_000_000

    contract = read_cost_document(api, world["document_ids"][3])
    assert contract["review_status"] == "ACCEPTED"
    assert contract["disallowed_amount_cents"] == 0

    after = read_agreement(api, world["agreement_id"])
    assert_version_unchanged(before, after)
    assert after["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
