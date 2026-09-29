"""Capability review arithmetic and the qualification gate on scoring."""

from test_helpers import (
    ApiErrorId,
    advance_program_to_scoring,
    api_client,
    create_score_sheet_payload,
    current_application_version,
    read_subgrantee,
    register_subgrantee,
    run_capability_review,
    score_application,
    setup_challenge_open_program,
    setup_qualified_subgrantee,
    setup_remediation_required_subgrantee,
    setup_submitted_application,
    submit_remediation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import REVIEWER, SCORER


def test_capability_index_initial_variant_uses_the_unaudited_basis_unhaircut():
    """On the first pass the declared unaudited net assets are the basis, the
    haircut is 1.00 and the full declared headcount drives the managerial leg.

    PRD 3.4: "Under the **initial review** variant, in force when
    `review_variant` is `INITIAL`, the net-asset basis is the unaudited
    `net_assets_cents`, the haircut is 1.00 (no reduction at all), and the
    personnel basis is the full declared `key_personnel_count`."
    PRD 3.4: "It moves `UNDER_CAPABILITY_REVIEW → REMEDIATION_REQUIRED` when
    `review_variant` is `INITIAL` and either `capability_index` falls in the
    band from 55.00 up to but not including 70.00, or `capability_index` reaches
    70.00 while `technical_component` is below 24.00 or `financial_component` is
    below 17.50 — a strong overall score with a weak leg still buys only a
    second chance."

    Design: Difficulty/dual_variant_calc/subgrantee_capability_index_initial_vs_remediation
    """
    ctx = setup_challenge_open_program(("L3",))
    reviewed = setup_remediation_required_subgrantee(ctx["program_id"])

    assert reviewed["review_variant"] == "INITIAL"
    assert reviewed["technical_component"] == 30.00
    assert reviewed["financial_component"] == 28.00, (
        "600000 against a liquidity requirement of 750000 is a ratio of 0.8, so "
        "35.00 times 0.8 with no haircut is 28.00"
    )
    assert reviewed["managerial_component"] == 10.00
    assert reviewed["capability_index"] == 68.00
    assert reviewed["capability_state"] == "REMEDIATION_REQUIRED"


def test_capability_index_remediation_variant_scores_identical_figures_lower():
    """The second pass restates the same money as audited and applies the 0.85
    haircut, so an unchanged submission lands strictly below its first score and
    the remediation route disqualifies anything under 70.00.

    PRD 3.4: "Under the **remediation review** variant, in force when
    `review_variant` is `REMEDIATION`, the net-asset basis is the audited
    restatement `audited_net_assets_cents`, the haircut is 0.85, and the
    personnel basis is `key_personnel_count` minus `withdrawn_personnel_count`."
    PRD 3.4: "It moves `UNDER_CAPABILITY_REVIEW → DISQUALIFIED` when
    `capability_index` is below 55.00, or when `review_variant` is
    `REMEDIATION` and `capability_index` is below 70.00."

    Design: Difficulty/dual_variant_calc/subgrantee_capability_index_initial_vs_remediation
    """
    ctx = setup_challenge_open_program(("L3",))
    first_pass = setup_remediation_required_subgrantee(ctx["program_id"])
    assert first_pass["capability_index"] == 68.00

    reopened = submit_remediation(
        first_pass["id"], audited_net_assets_cents=600000, withdrawn_personnel_count=0
    )
    assert reopened["capability_state"] == "UNDER_CAPABILITY_REVIEW"
    assert reopened["review_variant"] == "REMEDIATION"
    assert reopened["remediation_count"] == 1

    second_pass = validate_success(
        api_client.record_capability_determination(
            first_pass["id"], {"technical_raw_score": 30}, REVIEWER
        )
    )
    assert second_pass["technical_component"] == 30.00
    assert second_pass["financial_component"] == 23.80, (
        "The 0.85 haircut lands inside the single rounding step: 35.00 times 0.8 "
        "times 0.85 is 23.80"
    )
    assert second_pass["managerial_component"] == 10.00
    assert second_pass["capability_index"] == 63.80
    assert second_pass["capability_index"] < first_pass["capability_index"]
    assert second_pass["capability_state"] == "DISQUALIFIED"


def test_capability_remediation_personnel_basis_nets_off_withdrawals():
    """The remediation personnel basis is the declared headcount less the
    withdrawn count, so a departure costs five managerial points.

    PRD 3.4: "The **managerial component**, `managerial_component`, awards 5
    points per person in the applicable personnel basis plus a flat 5 points
    when `has_prior_federal_award` is true, takes the smaller of that sum and
    25.00, and rounds half up to 2 decimals; it is capped at 25.00."

    Design: Difficulty/dual_variant_calc/subgrantee_capability_index_initial_vs_remediation
    """
    ctx = setup_challenge_open_program(("L3",))
    first_pass = setup_remediation_required_subgrantee(ctx["program_id"])
    assert first_pass["managerial_component"] == 10.00

    submit_remediation(
        first_pass["id"], audited_net_assets_cents=600000, withdrawn_personnel_count=1
    )
    second_pass = validate_success(
        api_client.record_capability_determination(
            first_pass["id"], {"technical_raw_score": 30}, REVIEWER
        )
    )
    assert second_pass["withdrawn_personnel_count"] == 1
    assert second_pass["managerial_component"] == 5.00
    assert second_pass["capability_index"] == 58.80


def test_score_sheet_creation_requires_a_qualified_applicant():
    """Scoring is gated on the applicant's capability state, so an applicant
    parked in REMEDIATION_REQUIRED is refused while a qualified one on the same
    program is scored.

    PRD 2.12: "37. **Priority 82 — applicant qualification.** Score-sheet
    creation and award obligation both require the application's subgrantee to
    be `QUALIFIED` → `ERR_SUBGRANTEE_NOT_QUALIFIED`."

    Design: Difficulty/cross_entity_state_dependency/score_sheet_gated_by_subgrantee_capability_state
    """
    ctx = setup_challenge_open_program(("L2", "L3", "L5"))

    qualified = setup_qualified_subgrantee(ctx["program_id"])
    assert qualified["capability_state"] == "QUALIFIED"
    strong_app, _ = setup_submitted_application(
        ctx["program_id"],
        qualified["id"],
        [(ctx["location_ids"]["L2"], 900002), (ctx["location_ids"]["L3"], 900002)],
    )

    weak = setup_remediation_required_subgrantee(ctx["program_id"])
    assert weak["capability_state"] == "REMEDIATION_REQUIRED"
    weak_app, _ = setup_submitted_application(
        ctx["program_id"], weak["id"], [(ctx["location_ids"]["L5"], 900002)]
    )

    advance_program_to_scoring(ctx["program_id"])

    refused = api_client.create_score_sheet(
        create_score_sheet_payload(
            weak_app["id"], current_application_version(weak_app["id"])
        ),
        SCORER,
    )
    validate_error(refused, ApiErrorId.ERR_SUBGRANTEE_NOT_QUALIFIED)

    permitted = score_application(strong_app["id"])
    assert permitted["score_state"] == "FINAL"


def test_score_sheet_gate_lifts_once_remediation_raises_the_applicant():
    """The gate reads the live capability state, so the identical scoring
    request that was refused succeeds once the remediation pass qualifies the
    applicant.

    PRD 3.4: "The applicant becomes `QUALIFIED` — moving
    `UNDER_CAPABILITY_REVIEW → QUALIFIED` — when `capability_index` is at least
    70.00 **and** `technical_component` is at least 24.00 **and**
    `financial_component` is at least 17.50."
    PRD 2.12: "37. **Priority 82 — applicant qualification.** Score-sheet
    creation and award obligation both require the application's subgrantee to
    be `QUALIFIED` → `ERR_SUBGRANTEE_NOT_QUALIFIED`."

    Design: Difficulty/cross_entity_state_dependency/score_sheet_gated_by_subgrantee_capability_state
    """
    ctx = setup_challenge_open_program(("L2", "L3"))

    applicant = register_subgrantee(
        ctx["program_id"],
        legal_name="Cedar Valley Networks",
        ein="83-5550001",
        net_assets_cents=400000,
        requested_amount_cents=3000000,
        key_personnel_count=3,
        has_prior_federal_award=False,
    )
    first_pass = run_capability_review(applicant["id"], technical_raw_score=30)
    assert first_pass["capability_index"] == 63.67
    assert first_pass["capability_state"] == "REMEDIATION_REQUIRED"

    application, _ = setup_submitted_application(
        ctx["program_id"],
        applicant["id"],
        [(ctx["location_ids"]["L2"], 900002), (ctx["location_ids"]["L3"], 900002)],
    )
    advance_program_to_scoring(ctx["program_id"])

    refused = api_client.create_score_sheet(
        create_score_sheet_payload(
            application["id"], current_application_version(application["id"])
        ),
        SCORER,
    )
    validate_error(refused, ApiErrorId.ERR_SUBGRANTEE_NOT_QUALIFIED)

    submit_remediation(
        applicant["id"], audited_net_assets_cents=900000, withdrawn_personnel_count=0
    )
    second_pass = validate_success(
        api_client.record_capability_determination(
            applicant["id"], {"technical_raw_score": 30}, REVIEWER
        )
    )
    assert second_pass["financial_component"] == 29.75, (
        "Coverage over 1.0 is capped, so 35.00 times 1.0 times the 0.85 haircut "
        "is 29.75"
    )
    assert second_pass["capability_index"] == 74.75
    assert second_pass["capability_state"] == "QUALIFIED"
    assert read_subgrantee(applicant["id"])["capability_state"] == "QUALIFIED"

    accepted = score_application(application["id"])
    assert accepted["score_state"] == "FINAL"
