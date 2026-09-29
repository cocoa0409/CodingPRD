"""Caller-selected calculation variants and the ordered composition of the
derived numbers they feed.

Every test builds its own world from scratch: the harness restarts the server
before each test, so the database is empty and the logical clock sits at its
mandatory startup default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    RSO,
    add_disclosure_item,
    add_personnel,
    assert_commitment_totals_consistent,
    begin_review,
    certify_disclosure,
    create_disclosure,
    create_investigator,
    create_organization,
    create_project,
    create_subaward,
    create_support_statement,
    make_investigator_headers,
    read_disclosure,
    read_investigator,
    read_organization,
    read_project,
    reconcile_support_statement,
    return_for_revision,
    set_item_status,
    setup_owned_organization_pair,
    submit_disclosure,
    validate_success,
)

NEUTRAL_ORG = {
    "legal_name": "Neutral Academy",
    "country_code": "SG",
    "org_type": "UNIVERSITY",
    "own_designation": "NONE",
}


# --------------------------------------------------------------------------- #
# Local setup helpers
# --------------------------------------------------------------------------- #

def _setup_subaward_on_owned_counterparty():
    """A NONE-designated counterparty held 60 percent by an SDN parent, plus one
    PENDING subaward on it. The project stays at PENDING_CLEARANCE so a BLOCKED
    outcome drives no security cascade.

    Returns (parent, child, project, subaward).
    """
    parent, child = setup_owned_organization_pair(
        parent_designation="SDN",
        child_designation="NONE",
        ownership_pct=60.00,
        parent_overrides={"legal_name": "Parent Holdings"},
        child_overrides={"legal_name": "Child Institute"},
    )
    project = create_project(
        title="Photonics Array",
        agency_code="NSF",
        sensitivity_level="STANDARD",
        controlled_area_capacity=0,
    )
    subaward = create_subaward(
        project["id"],
        child["id"],
        scope="Optics fabrication",
        amount_cents=4_000_000,
    )
    return parent, child, project, subaward


def _setup_two_agency_support_statement():
    """One investigator with a CERTIFIED disclosure carrying a 320-hour foreign
    appointment and a 160-hour talent programme, an ACTIVE 2.00 person-month row
    on an NIH award and an ACTIVE 3.00 person-month row on a DOD award, and an
    NIH current-and-pending page declaring 2.00 person-months and 1 appointment.

    Returns (investigator, nih_project, dod_project, statement).
    """
    investigator = create_investigator(
        full_name="Ada Reed", home_department="Materials",
        institutional_base_effort_pct=0,
    )
    organization = create_organization(**NEUTRAL_ORG)
    disclosure = create_disclosure(investigator["id"])
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="FOREIGN_APPOINTMENT",
        start_date="2025-03-01T00:00:00Z",
        annual_effort_hours=320,
        is_paid=True,
    )
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="TALENT_PROGRAM",
        start_date="2025-06-01T00:00:00Z",
        annual_effort_hours=160,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    certify_disclosure(disclosure["id"])

    nih_project = create_project(title="NIH Imaging Core", agency_code="NIH")
    dod_project = create_project(title="DOD Sensing Study", agency_code="DOD")
    add_personnel(
        nih_project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=2.00,
    )
    add_personnel(
        dod_project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=3.00,
    )
    statement = create_support_statement(
        investigator["id"],
        nih_project["id"],
        agency_code="NIH",
        document_type="CURRENT_AND_PENDING",
        declared_person_months=2.00,
        declared_appointment_count=1,
        declared_support_count=0,
    )
    return investigator, nih_project, dod_project, statement


def _setup_capped_item_scoring():
    """A SUBMITTED disclosure carrying a paid talent-programme item on an SDN
    organization and an unpaid foreign appointment on a NONE organization.

    Returns (investigator, talent_item, appointment_item).
    """
    investigator = create_investigator(
        full_name="Bo Chan", home_department="Chemistry",
        institutional_base_effort_pct=0,
    )
    sdn_organization = create_organization(
        legal_name="Listed Defence Works",
        country_code="RU",
        org_type="GOVERNMENT_AGENCY",
        own_designation="SDN",
        designated_on="2025-11-01T00:00:00Z",
    )
    neutral_organization = create_organization(**NEUTRAL_ORG)
    disclosure = create_disclosure(investigator["id"])
    talent_item = add_disclosure_item(
        disclosure["id"],
        sdn_organization["id"],
        investigator_id=investigator["id"],
        item_type="TALENT_PROGRAM",
        start_date="2025-01-10T00:00:00Z",
        annual_effort_hours=0,
        is_paid=True,
    )
    appointment_item = add_disclosure_item(
        disclosure["id"],
        neutral_organization["id"],
        investigator_id=investigator["id"],
        item_type="FOREIGN_APPOINTMENT",
        start_date="2025-02-10T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    return investigator, talent_item, appointment_item


def _setup_three_rows_and_three_items():
    """One investigator with three PROPOSED roster rows of 1.00 person-month each
    and a SUBMITTED disclosure carrying three 100-hour outside-support items.

    Returns (investigator, personnel_rows, items).
    """
    investigator = create_investigator(
        full_name="Cy Duarte",
        appointment_type="RESEARCH_STAFF",
        home_department="Bioengineering",
        institutional_base_effort_pct=0,
    )
    organization = create_organization(**NEUTRAL_ORG)
    rows = []
    for index, title in enumerate(("Grant One", "Grant Two", "Grant Three")):
        project = create_project(title=title, award_amount_cents=10_000_000)
        rows.append(
            add_personnel(
                project["id"],
                investigator["id"],
                role_on_project="PI" if index == 0 else "CO_PI",
                committed_person_months=1.00,
                activate=False,
            )
        )
    disclosure = create_disclosure(investigator["id"])
    items = [
        add_disclosure_item(
            disclosure["id"],
            organization["id"],
            investigator_id=investigator["id"],
            item_type="OUTSIDE_SUPPORT",
            start_date=start_date,
            annual_effort_hours=100,
            is_paid=False,
        )
        for start_date in (
            "2025-04-01T00:00:00Z",
            "2025-05-01T00:00:00Z",
            "2025-06-01T00:00:00Z",
        )
    ]
    submit_disclosure(disclosure["id"], investigator["id"])
    return investigator, rows, items


def _setup_three_late_items_after_one_revision_round():
    """A disclosure returned once for revision, then given three further items, so
    revision_round is 1 and every item counts as late. Left RETURNED_FOR_REVISION.

    Returns (investigator, disclosure).
    """
    investigator = create_investigator(
        full_name="Dev Iyer", home_department="Computer Science",
        institutional_base_effort_pct=0,
    )
    organization = create_organization(**NEUTRAL_ORG)
    disclosure = create_disclosure(investigator["id"])
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    return_for_revision(disclosure["id"])
    for item_type, start_date in (
        ("FOREIGN_APPOINTMENT", "2025-01-05T00:00:00Z"),
        ("OUTSIDE_SUPPORT", "2025-02-05T00:00:00Z"),
        ("IN_KIND_RESOURCE", "2025-03-05T00:00:00Z"),
    ):
        add_disclosure_item(
            disclosure["id"],
            organization["id"],
            investigator_id=investigator["id"],
            item_type=item_type,
            start_date=start_date,
            annual_effort_hours=0,
            is_paid=False,
        )
    return investigator, disclosure


# --------------------------------------------------------------------------- #
# Counterparty screening: the variant decides the outcome
# --------------------------------------------------------------------------- #

def test_direct_match_screen_clears_counterparty_owned_by_sanctioned_parent(api):
    """PRD §3.6: "Under `DIRECT_MATCH` the screen compares only the named
    counterparty against the restricted-entity lists: it reads the counterparty's
    `own_designation`, always reports a `screening_match_depth` of 0, sets
    `screening_matched_organization_id` to the counterparty itself, and never
    inspects ancestors — so a counterparty whose `own_designation` is `NONE`
    always clears with 0 risk points no matter who owns it."

    Design: Difficulty/dual_variant_calc/subaward_screening_direct_match_vs_ownership_transitive_diverge
    """
    _parent, child, project, subaward = _setup_subaward_on_owned_counterparty()

    # The counterparty inherits SDN through the 60 percent controlling stake, yet
    # DIRECT_MATCH never looks past the counterparty itself.
    inherited = read_organization(child["id"])
    assert inherited["effective_designation"] == "SDN"
    assert inherited["effective_designation_depth"] == 1
    assert inherited["own_designation"] == "NONE"

    screened = validate_success(
        api.screen_subaward(subaward["id"], {"variant": "DIRECT_MATCH"}, RSO),
        expected_status=200,
    )
    assert screened["applied_screening_variant"] == "DIRECT_MATCH"
    assert screened["status"] == "CLEARED"
    assert screened["screening_designation"] == "NONE"
    assert screened["screening_risk_points"] == 0
    assert screened["screening_match_depth"] == 0
    assert screened["screening_matched_organization_id"] == child["id"]

    # A CLEARED outcome leaves the security dimension alone.
    assert read_project(project["id"])["security_status"] == "PENDING_CLEARANCE"


def test_ownership_transitive_screen_blocks_counterparty_owned_by_sanctioned_parent(api):
    """PRD §3.6: "The variant choice is therefore load-bearing: an organization
    whose `own_designation` is `NONE` but which is held 60 percent by an `SDN`
    parent screens as `CLEARED` with 0 risk points and depth 0 under
    `DIRECT_MATCH`, and as `BLOCKED` with 90 risk points and depth 1 under
    `OWNERSHIP_TRANSITIVE`, on identical stored data."

    Design: Difficulty/dual_variant_calc/subaward_screening_direct_match_vs_ownership_transitive_diverge
    """
    parent, child, project, subaward = _setup_subaward_on_owned_counterparty()

    screened = validate_success(
        api.screen_subaward(
            subaward["id"], {"variant": "OWNERSHIP_TRANSITIVE"}, RSO
        ),
        expected_status=200,
    )
    assert screened["applied_screening_variant"] == "OWNERSHIP_TRANSITIVE"
    assert screened["status"] == "BLOCKED"
    assert screened["screening_designation"] == "SDN"
    # SDN sits at strictness rank 5: 40 plus 10 times 5.
    assert screened["screening_risk_points"] == 90
    assert screened["screening_match_depth"] == 1
    assert screened["screening_matched_organization_id"] == parent["id"]

    # The project was never CLEARED, so no suspension cascade follows.
    assert read_project(project["id"])["security_status"] == "PENDING_CLEARANCE"


# --------------------------------------------------------------------------- #
# Support-statement reconciliation: the variant decides the verdict
# --------------------------------------------------------------------------- #

def test_strict_agency_reconciliation_counts_only_the_sponsor_own_roster(api):
    """PRD §3.5: "Under `STRICT_AGENCY` — the view a single sponsor takes of its
    own current-and-pending page — the institutional truth counts only those
    personnel rows of this investigator whose `status` is `ACTIVE` **and** whose
    project's `agency_code` equals the statement's `agency_code`; it draws
    disclosure items from exactly one source, the single newest disclosure of this
    investigator whose review status is `CERTIFIED`, selected by the latest
    `submitted_at` and breaking ties by the latest `created_at`; it counts only
    items whose `item_type` is `FOREIGN_APPOINTMENT`; and it never converts
    outside hours into person-months, so the outside contribution is 0.00."

    Design: Difficulty/dual_variant_calc/support_statement_strict_agency_vs_institutional_rollup_flip_verdict
    """
    investigator, nih_project, _dod_project, statement = (
        _setup_two_agency_support_statement()
    )

    reconciled = validate_success(
        api.reconcile_support_statement(
            statement["id"], {"variant": "STRICT_AGENCY"}, RSO
        ),
        expected_status=200,
    )
    assert reconciled["applied_variant"] == "STRICT_AGENCY"
    # Only the NIH row (2.00 person-months) counts, and outside hours convert to 0.00.
    assert reconciled["institutional_person_months"] == pytest.approx(2.00, abs=0.01)
    assert reconciled["variance_person_months"] == pytest.approx(0.00, abs=0.01)
    # One counted appointment against one declared appointment.
    assert reconciled["omission_count"] == 0
    assert reconciled["verdict"] == "CONSISTENT"
    assert reconciled["status"] == "RECONCILED"

    assert read_investigator(investigator["id"])["material_discrepancy_count"] == 0
    assert "SUPPORT_INCONSISTENT" not in read_project(nih_project["id"])[
        "activation_blockers"
    ]


def test_institutional_rollup_reconciliation_flips_the_same_statement_to_material_discrepancy(api):
    """PRD §3.5: "To make the variant difference concrete: an organization-heavy
    investigator whose talent-programme and visiting-scholar relationships sit
    outside the sponsor's own portfolio can reconcile as `CONSISTENT` under
    `STRICT_AGENCY` and as `MATERIAL_DISCREPANCY` under `INSTITUTIONAL_ROLLUP` on
    exactly the same stored data, because the rollup raises
    `institutional_person_months` and widens the counted item set."

    Design: Difficulty/dual_variant_calc/support_statement_strict_agency_vs_institutional_rollup_flip_verdict
    """
    investigator, nih_project, _dod_project, statement = (
        _setup_two_agency_support_statement()
    )
    strict = reconcile_support_statement(statement["id"], "STRICT_AGENCY")
    assert strict["verdict"] == "CONSISTENT"

    rolled_up = validate_success(
        api.reconcile_support_statement(
            statement["id"], {"variant": "INSTITUTIONAL_ROLLUP"}, RSO
        ),
        expected_status=200,
    )
    assert rolled_up["applied_variant"] == "INSTITUTIONAL_ROLLUP"
    # 2.00 plus 3.00 person-months of roster, plus 480 outside hours at 160 hours
    # per person-month.
    assert rolled_up["institutional_person_months"] == pytest.approx(8.00, abs=0.01)
    assert rolled_up["variance_person_months"] == pytest.approx(6.00, abs=0.01)
    # Two counted appointment-flavoured items against one declared appointment.
    assert rolled_up["omission_count"] == 1
    assert rolled_up["verdict"] == "MATERIAL_DISCREPANCY"
    assert rolled_up["status"] == "INCONSISTENT"

    assert read_investigator(investigator["id"])["material_discrepancy_count"] == 1
    assert "SUPPORT_INCONSISTENT" in read_project(nih_project["id"])[
        "activation_blockers"
    ]


# --------------------------------------------------------------------------- #
# Risk score: per-item rounding, then the item cap, then the clamp
# --------------------------------------------------------------------------- #

def test_item_risk_points_apply_the_exposure_multiplier_then_the_paid_surcharge(api):
    """PRD §3.3: "Multiply that base by the counterparty's exposure multiplier,
    read from the referenced organization's `effective_designation`: 1.0 for
    `NONE`, 1.5 for `UNVERIFIED_END_USER`, 2.0 for `ENTITY_LIST`, 2.5 for
    `FOREIGN_MILITARY`, and 3.0 for both `MALIGN_TALENT_PROGRAM` and `SDN`. If
    the relationship is compensated — `is_paid` true — add a flat surcharge of 5
    after the multiplication. Round the result half up to a whole number; that
    whole number is the item's contribution."

    Design: Difficulty/combinatorial_formula/risk_score_per_item_rounding_then_cap_then_clamp
    """
    _investigator, talent_item, appointment_item = _setup_capped_item_scoring()

    verified_talent = validate_success(
        api.set_disclosure_item_status(
            talent_item["id"], {"to_status": "VERIFIED"}, RSO
        ),
        expected_status=200,
    )
    verified_appointment = validate_success(
        api.set_disclosure_item_status(
            appointment_item["id"], {"to_status": "VERIFIED"}, RSO
        ),
        expected_status=200,
    )

    # TALENT_PROGRAM 30 times the SDN multiplier of 3.0, plus the paid surcharge of 5.
    assert verified_talent["item_risk_points"] == 95
    # FOREIGN_APPOINTMENT 12 times the NONE multiplier of 1.0, unpaid.
    assert verified_appointment["item_risk_points"] == 12


def test_risk_score_caps_the_item_subtotal_before_the_final_clamp(api):
    """PRD §3.3: "Add the capped item subtotal, the incident subtotal and the
    discrepancy subtotal; subtract the credit; then clamp the result into the
    range 0 to 100 — no lower than 0, no higher than 100. The cap of 60 applies
    only to the item term, and it applies to the already-summed integer, not to
    individual items."

    Design: Difficulty/combinatorial_formula/risk_score_per_item_rounding_then_cap_then_clamp
    """
    investigator, talent_item, appointment_item = _setup_capped_item_scoring()
    set_item_status(talent_item["id"], "VERIFIED")
    set_item_status(appointment_item["id"], "VERIFIED")

    scored = validate_success(
        api.get_investigator(investigator["id"], RSO), expected_status=200
    )
    # 95 plus 12 is 107; the item term is capped at 60, and the clamp finds nothing
    # left to do.
    assert scored["risk_score"] == 60
    assert scored["disclosure_posture"] == "RESTRICTED"


# --------------------------------------------------------------------------- #
# Commitment totals: rounding happens per row and per item, before summation
# --------------------------------------------------------------------------- #

def test_committed_effort_rounds_each_active_roster_row_before_summation(api):
    """PRD §2.6: "Commitment percentages round **per contributing row, before
    summation, and the sum of the rounded parts is never rounded again**. An
    investigator's `committed_effort_pct` is the sum, over their personnel rows in
    `ACTIVE` status, of each row's `committed_person_months` divided by 12 months,
    multiplied by 100, and rounded half up to two decimal places at that point."

    Design: Difficulty/combinatorial_formula/commitment_totals_round_per_row_and_per_item_before_summation
    """
    investigator, rows, _items = _setup_three_rows_and_three_items()

    for row in rows:
        validate_success(
            api.set_personnel_status(row["id"], {"to_status": "ACTIVE"}, ADMIN),
            expected_status=200,
        )

    committed = read_investigator(investigator["id"])
    # Each row contributes round(8.3333, 2) = 8.33, so the sum is 24.99, never 25.00.
    assert committed["committed_effort_pct"] == pytest.approx(24.99, abs=0.01)


def test_outside_effort_rounds_each_verified_item_and_the_total_is_never_re_rounded(api):
    """PRD §2.6: "Their `outside_effort_pct` is the sum, over their `VERIFIED`
    disclosure items on disclosures that are not `REJECTED`, of each item's
    `annual_effort_hours` divided by 2,080 hours — the institution's definition of
    a full research year — multiplied by 100, and rounded half up to two decimal
    places at that point. `total_commitment_pct` is then the plain sum of three
    already-rounded terms: the investigator's own `institutional_base_effort_pct`,
    plus `committed_effort_pct`, plus `outside_effort_pct`. That sum is never
    re-rounded."

    Design: Difficulty/combinatorial_formula/commitment_totals_round_per_row_and_per_item_before_summation
    """
    investigator, rows, items = _setup_three_rows_and_three_items()
    for row in rows:
        validate_success(
            api.set_personnel_status(row["id"], {"to_status": "ACTIVE"}, ADMIN),
            expected_status=200,
        )

    for item in items:
        validate_success(
            api.set_disclosure_item_status(
                item["id"], {"to_status": "VERIFIED"}, RSO
            ),
            expected_status=200,
        )

    totals = read_investigator(investigator["id"])
    # Each item contributes round(4.8077, 2) = 4.81, so the sum is 14.43, never 14.42.
    assert totals["outside_effort_pct"] == pytest.approx(14.43, abs=0.01)
    assert totals["committed_effort_pct"] == pytest.approx(24.99, abs=0.01)
    # 0 plus 24.99 plus 14.43, with no further rounding of the sum.
    assert totals["total_commitment_pct"] == pytest.approx(39.42, abs=0.01)
    assert totals["overcommitment_pct"] == pytest.approx(0.00, abs=0.01)
    assert_commitment_totals_consistent(totals)


# --------------------------------------------------------------------------- #
# Completeness: the tier is keyed on the raw score, not the penalised score
# --------------------------------------------------------------------------- #

def test_completeness_tier_is_selected_from_the_raw_score_before_the_tier_penalty(api):
    """PRD §3.4: "Step two selects `completeness_tier` **from that raw score**:
    `A` if the raw score is at least 90, otherwise `B` if the raw score is at
    least 70, otherwise `C`. Step three produces the final `completeness_score` by
    subtracting the tier's own penalty from the raw score and flooring at 0 — 0
    for tier `A`, 5 for tier `B`, and 12 for tier `C`. The tier is never
    re-derived from the penalised score. Worked through: three late items and one
    completed revision round give a raw score of 100 minus 0 minus 24 minus 6,
    which is 70; 70 selects tier `B`; and the final `completeness_score` is 65."

    Design: Difficulty/combinatorial_formula/completeness_tier_penalty_keyed_on_raw_score_not_penalized_score
    """
    investigator, disclosure = _setup_three_late_items_after_one_revision_round()

    resubmitted = validate_success(
        api.submit_disclosure(
            disclosure["id"], make_investigator_headers(investigator["id"])
        ),
        expected_status=200,
    )
    assert resubmitted["revision_round"] == 1
    assert resubmitted["late_item_count"] == 3
    assert resubmitted["undisclosed_item_count"] == 0
    assert resubmitted["completeness_tier"] == "B"
    assert resubmitted["completeness_score"] == 65


def test_certification_succeeds_on_the_raw_score_keyed_tier_penalty(api):
    """PRD §3.4: "Re-deriving the tier from 65 would wrongly yield tier `C` and a
    score of 58, a value this API must never return — and because the
    certification floor sits at 60, that mistake also flips certification
    outcomes near the boundary."

    Design: Difficulty/combinatorial_formula/completeness_tier_penalty_keyed_on_raw_score_not_penalized_score
    """
    investigator, disclosure = _setup_three_late_items_after_one_revision_round()
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])

    certified = validate_success(
        api.review_disclosure(disclosure["id"], {"action": "CERTIFY"}, RSO),
        expected_status=200,
    )
    assert certified["review_status"] == "CERTIFIED"
    assert certified["completeness_tier"] == "B"
    assert certified["completeness_score"] == 65

    stored = read_disclosure(disclosure["id"])
    assert stored["completeness_score"] == 65
    assert stored["completeness_tier"] == "B"
