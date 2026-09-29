"""One supplier status write travelling all five hops: sub-component, compound
parent, product formula, certificate, and finally label plus applicant posture.
"""

from test_helpers import (
    BlockedReason,
    DocType,
    IngredientSpec,
    OutcomeEvidence,
    SymptomSeverity,
    MarkTier,
    RiskClass,
    activate_testing_plan,
    add_supplier_document,
    create_ingredient,
    create_product,
    create_supplier,
    file_complaint,
    issue_certificate,
    link_ingredient,
    make_admin_headers,
    make_reviewer_headers,
    read_applicant,
    read_certificate,
    read_ingredient,
    read_product,
    read_supplier,
    review_formula,
    review_ingredient,
    record_investigation_outcome,
    review_label,
    set_clock,
    setup_applicant_with_facility,
    setup_issued_certificate,
    setup_passed_audit,
    submit_ingredient,
    triage_complaint,
    validate_paginated,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
ISSUE_DAY = "2026-08-11T00:00:00Z"
DOC_ISSUED = "2026-07-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
COMPLAINT_DAY = "2026-09-05T00:00:00Z"
EXPOSURE_DAY = "2026-09-01T00:00:00Z"


def _certified_product_over_a_two_supplier_ingredient_tree(api):
    """A compound GF_PROCESSED blend from one supplier containing an INHERENTLY_GF
    sub-component from another, with only the compound parent in the formula.

    The product is certified at 2026-08-11 for 178800 cents; the sub-component's
    supplier is the one that will be suspended, and the blend's supplier stays
    ACTIVE throughout so any blocking of the parent must arrive through the tree.
    """
    context = setup_applicant_with_facility(
        api, clock=SANITATION_DAY, sanitation_validated_on=SANITATION_DAY
    )
    supplier_a = create_supplier(api, name="Prairie Mills", country_code="CA")
    supplier_b = create_supplier(api, name="Cascade Blending Co", country_code="US")

    parent = create_ingredient(
        api,
        context.applicant_id,
        supplier_b["id"],
        name="Multigrain GF Blend",
        risk_class=RiskClass.GF_PROCESSED,
    )
    for doc_type in (DocType.ALLERGEN_STATEMENT, DocType.PROCESS_FLOW):
        add_supplier_document(
            api,
            context.applicant_id,
            supplier_b["id"],
            parent["id"],
            doc_type=doc_type,
            issued_on=DOC_ISSUED,
            expires_on=DOC_EXPIRES,
        )
    child = create_ingredient(
        api,
        context.applicant_id,
        supplier_a["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        parent_ingredient_id=parent["id"],
    )
    add_supplier_document(
        api,
        context.applicant_id,
        supplier_a["id"],
        child["id"],
        doc_type=DocType.ALLERGEN_STATEMENT,
        issued_on=DOC_ISSUED,
        expires_on=DOC_EXPIRES,
    )
    for ingredient_id in (child["id"], parent["id"]):
        submit_ingredient(api, context.applicant_id, ingredient_id)
        approved = review_ingredient(api, ingredient_id)
        assert approved["status"] == "APPROVED"

    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Multigrain Rice Loaf",
        sku="MRL-001",
        requested_mark_tier=MarkTier.STANDARD,
    )
    link_ingredient(api, context.applicant_id, product["id"], parent["id"], 40)
    cleared = review_formula(api, product["id"])
    activate_testing_plan(api, product["id"], cleared["version"])
    labelled = review_label(api, product["id"], mark_tier_granted=MarkTier.STANDARD)

    setup_passed_audit(api, context.facility_id)
    set_clock(api, ISSUE_DAY)
    certificate = issue_certificate(api, product["id"], labelled["version"])

    return {
        "context": context,
        "supplier_a": supplier_a,
        "supplier_b": supplier_b,
        "parent": parent,
        "child": child,
        "product": product,
        "certificate": certificate,
    }


def test_the_cascade_climbs_the_parent_chain_with_two_distinct_blocked_reasons(api):
    """The suspended supplier's own ingredient is blocked as SUPPLIER_SUSPENDED and
    its compound parent — fed by a still-ACTIVE supplier — as SUB_COMPONENT_BLOCKED.

    PRD: "**Hop one:** every ingredient supplied by this supplier whose `status` is
    `APPROVED` moves `APPROVED → BLOCKED` with `blocked_reason` set to
    `SUPPLIER_SUSPENDED`."
    PRD: "**Hop two:** for each ingredient blocked by hop one, the compound
    ingredient it is a sub-component of — the row its `parent_ingredient_id` names —
    moves `APPROVED → BLOCKED` with `blocked_reason` set to
    `SUB_COMPONENT_BLOCKED`, if that parent was `APPROVED`."

    Design: Difficulty/transitive_cascade/supplier_suspension_propagates_five_hops_to_certificate_and_posture
    """
    built = _certified_product_over_a_two_supplier_ingredient_tree(api)

    response = api.set_supplier_status(
        built["supplier_a"]["id"], "SUSPENDED", make_admin_headers()
    )
    assert response.status_code == 200, response.text

    assert read_supplier(api, built["supplier_a"]["id"])["status"] == "SUSPENDED"
    assert read_supplier(api, built["supplier_b"]["id"])["status"] == "ACTIVE"

    child = read_ingredient(api, built["child"]["id"])
    assert child["status"] == "BLOCKED"
    assert child["blocked_reason"] == BlockedReason.SUPPLIER_SUSPENDED

    parent = read_ingredient(api, built["parent"]["id"])
    assert parent["status"] == "BLOCKED"
    assert parent["blocked_reason"] == BlockedReason.SUB_COMPONENT_BLOCKED


def test_the_blocked_parent_suspends_the_certificate_and_freezes_the_label(api):
    """Because the formula links the parent, the product blocks, its certificate
    suspends with INGREDIENT_BLOCKED, and only then does the label freeze.

    PRD: "**Hop four:** every certificate of a product blocked in hop three whose
    `status` is `ISSUED` moves `ISSUED → SUSPENDED` with `suspension_reason` set to
    `INGREDIENT_BLOCKED`, `suspended_on` set to the logical clock, `suspension_count`
    increased by 1 and `mark_usage_locked` set to true."
    PRD: "**Hop five:** each of those products moves `label_status` from `APPROVED`
    to `FROZEN`, and each owning applicant recomputes
    `active_certified_product_count`, `suspended_certificate_count`,
    `posture_score_rolling_12m`, `posture_score_cycle` and `compliance_posture`."

    Design: Difficulty/transitive_cascade/supplier_suspension_propagates_five_hops_to_certificate_and_posture
    """
    built = _certified_product_over_a_two_supplier_ingredient_tree(api)

    api.set_supplier_status(built["supplier_a"]["id"], "SUSPENDED", make_admin_headers())

    product = read_product(api, built["product"]["id"])
    assert product["formula_status"] == "BLOCKED"
    assert product["blocked_ingredient_count"] == 1
    assert product["label_status"] == "FROZEN"

    certificate = read_certificate(api, built["certificate"]["id"])
    assert certificate["status"] == "SUSPENDED"
    assert certificate["suspension_reason"] == "INGREDIENT_BLOCKED"
    assert certificate["suspension_count"] == 1
    assert certificate["mark_usage_locked"] is True
    assert certificate["suspended_on"] == ISSUE_DAY


def test_posture_drops_five_points_while_the_fee_ledger_holds(api):
    """The one suspended certificate costs the applicant exactly 5 posture points,
    which still leaves GOOD_STANDING, and the 178800 already billed stays billed.

    PRD: "Start from 100 and subtract three terms: first, the sum of
    `penalty_points` over this applicant's nonconformances whose `status` is
    `OPEN`, `CA_SUBMITTED`, `CA_REJECTED` or `ESCALATED` **and** whose `created_at`
    falls inside the window running from 365 days before the logical clock up to
    the logical clock; second, 5 points for each certificate counted in
    `suspended_certificate_count`; third, 15 points for each complaint counted in
    `substantiated_complaint_count_rolling`."
    PRD: "At every observable instant it equals the sum of `total_fee_cents` over
    that applicant's certificates whose `fee_charged` is true and whose
    `fee_refunded` is false."

    Design: Difficulty/transitive_cascade/supplier_suspension_propagates_five_hops_to_certificate_and_posture
    """
    built = _certified_product_over_a_two_supplier_ingredient_tree(api)

    api.set_supplier_status(built["supplier_a"]["id"], "SUSPENDED", make_admin_headers())

    applicant = read_applicant(api, built["context"].applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 1
    assert applicant["posture_score_rolling_12m"] == 95
    assert applicant["posture_score_cycle"] == 95
    assert applicant["compliance_posture"] == "GOOD_STANDING"
    assert applicant["fee_balance_cents"] == 178800


def test_the_certified_product_starts_from_the_expected_plan_and_fee(api):
    """Before the suspension the compound line yields a 10 ppm threshold with 3 lots
    at 121 days, and the single-ingredient shared-equipment base bills 178800.

    PRD: "Then, for **each** formula line separately, compute an inclusion factor
    of 0.5 when that line's `inclusion_pct` is below 2 and 1.0 otherwise, and
    multiply four things together: a base of 4 lots per year, the line's risk
    weight (0.25 for `INHERENTLY_GF`, 0.5 for `GF_PROCESSED`, 1.0 for
    `HIGH_RISK_GRAIN`), the shared threshold multiplier, and that inclusion factor."
    PRD: "Step three sets `surveillance_surcharge_cents` to `base_fee_cents`
    multiplied by that rate, rounded half up to whole cents."

    Design: Difficulty/transitive_cascade/supplier_suspension_propagates_five_hops_to_certificate_and_posture
    """
    built = _certified_product_over_a_two_supplier_ingredient_tree(api)

    product = read_product(api, built["product"]["id"])
    assert product["threshold_ppm"] == 10
    assert product["sampling_lots_per_year"] == 3
    assert product["sampling_exclusion_days"] == 121
    assert product["linked_ingredient_count"] == 1

    certificate = read_certificate(api, built["certificate"]["id"])
    assert certificate["base_fee_cents"] == 149000
    assert certificate["surveillance_surcharge_cents"] == 29800
    assert certificate["total_fee_cents"] == 178800


def _substantiated_anaphylaxis_complaint(api):
    """The canonical certified product with no lot test ever recorded, then an
    ANAPHYLAXIS complaint filed at 2026-09-05 and triaged.

    With zero candidate lots the triage selector must leave the recall scope empty,
    which is what keeps the substantiated branch on SUBSTANTIATED rather than
    RECALL_COORDINATION.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(
            IngredientSpec(
                name="Brown Rice Flour",
                risk_class=RiskClass.INHERENTLY_GF,
                inclusion_pct=40,
                doc_issued_on=DOC_ISSUED,
                doc_expires_on=DOC_EXPIRES,
            ),
        ),
        issue_clock=ISSUE_DAY,
    )
    set_clock(api, COMPLAINT_DAY)
    complaint = file_complaint(
        api,
        context.certificate_id,
        exposure_date=EXPOSURE_DAY,
        symptom_severity=SymptomSeverity.ANAPHYLAXIS,
    )
    triaged = triage_complaint(api, complaint["id"])
    return context, triaged


def test_an_empty_recall_scope_keeps_the_substantiated_branch_out_of_recall(api):
    """Triage fixes P1 with an empty scope and ADVISORY_ONLY, so substantiating the
    complaint lands on SUBSTANTIATED even at the highest symptom severity.

    PRD: "When there are no candidates at all, `recall_scope_lot_codes` stays empty
    and `recall_action` is `ADVISORY_ONLY`."
    PRD: "An outcome of `SUBSTANTIATED` forks on the `recall_action` computed at
    triage: while `recall_action` is `ADVISORY_ONLY` the complaint moves
    `INVESTIGATING → SUBSTANTIATED`, and while `recall_action` is
    `VOLUNTARY_RECALL` or `MANDATORY_RECALL_SUPPORT` it moves `INVESTIGATING →
    RECALL_COORDINATION` instead, with `recall_scope_lot_codes` necessarily
    non-empty on that branch."

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascades_through_critical_nc_to_probation
    """
    _context, triaged = _substantiated_anaphylaxis_complaint(api)
    assert triaged["triage_priority"] == "P1"
    assert triaged["recall_scope_lot_codes"] == []
    assert triaged["recall_action"] == "ADVISORY_ONLY"

    response = api.record_investigation_outcome(
        triaged["id"],
        make_reviewer_headers(),
        outcome="SUBSTANTIATED",
        outcome_evidence=OutcomeEvidence.LOT_TEST_FAILURE,
    )
    assert response.status_code == 200, response.text
    outcome = response.json()["data"]

    assert outcome["status"] == "SUBSTANTIATED"
    assert outcome["triage_priority"] == "P1"
    assert outcome["recall_scope_lot_codes"] == []
    assert outcome["recall_action"] == "ADVISORY_ONLY"
    assert outcome["investigated_by_user_id"] == "rev-1"


def test_substantiation_raises_one_critical_finding_dated_fifteen_days_out(api):
    """Exactly one CRITICAL THRESHOLD_EXCEEDANCE finding is raised from the
    complaint, worth 25 points and due 15 days after it was created.

    PRD: "a nonconformance is raised with `source_type` of `COMPLAINT`,
    `complaint_id` naming this complaint, `applicant_id` taken from the certificate,
    `category` of `THRESHOLD_EXCEEDANCE`, and `severity` of `CRITICAL` when
    `symptom_severity` is `SEVERE` or `ANAPHYLAXIS` and `MAJOR` otherwise"
    PRD: "`ca_due_on`, the deadline for the applicant's corrective-action plan, is
    set to the record's `created_at` plus a severity-dependent window: 15 days for a
    `CRITICAL` finding, 30 days for a `MAJOR` one and 90 days for a `MINOR` one,
    because a critical exceedance cannot be left to drift for a quarter."

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascades_through_critical_nc_to_probation
    """
    _context, triaged = _substantiated_anaphylaxis_complaint(api)

    record_investigation_outcome(
        api,
        triaged["id"],
        outcome="SUBSTANTIATED",
        outcome_evidence=OutcomeEvidence.LOT_TEST_FAILURE,
    )

    rows, _meta = validate_paginated(
        api.list_nonconformances(make_admin_headers(), complaint_id=triaged["id"])
    )
    assert len(rows) == 1
    finding = rows[0]
    assert finding["severity"] == "CRITICAL"
    assert finding["category"] == "THRESHOLD_EXCEEDANCE"
    assert finding["source_type"] == "COMPLAINT"
    assert finding["status"] == "OPEN"
    assert finding["penalty_points"] == 25
    assert finding["ca_due_on"] == "2026-09-20T00:00:00Z"


def test_three_independent_penalties_land_together_and_force_probation(api):
    """25 finding points, 5 for the suspended certificate and 15 for the
    substantiated complaint take both posture figures to 55 and the band to PROBATION.

    PRD: "when that finding is `CRITICAL` and the complaint's certificate is
    `ISSUED`, the certificate moves `ISSUED → SUSPENDED` with `suspension_reason` of
    `SUBSTANTIATED_COMPLAINT` and the product's `label_status` freezes"
    PRD: "`compliance_posture` is banded from `posture_score_cycle`: a score of
    at least 85 is `GOOD_STANDING`, a score from 60 up to but not including 85 is
    `WATCH`, and a score below 60 is `PROBATION`."

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascades_through_critical_nc_to_probation
    """
    context, triaged = _substantiated_anaphylaxis_complaint(api)

    record_investigation_outcome(
        api,
        triaged["id"],
        outcome="SUBSTANTIATED",
        outcome_evidence=OutcomeEvidence.LOT_TEST_FAILURE,
    )

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "SUSPENDED"
    assert certificate["suspension_reason"] == "SUBSTANTIATED_COMPLAINT"
    assert certificate["mark_usage_locked"] is True
    assert read_product(api, context.product_id)["label_status"] == "FROZEN"

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 25
    assert applicant["suspended_certificate_count"] == 1
    assert applicant["active_certified_product_count"] == 0
    assert applicant["substantiated_complaint_count_cycle"] == 1
    assert applicant["posture_score_cycle"] == 55
    assert applicant["posture_score_rolling_12m"] == 55
    assert applicant["compliance_posture"] == "PROBATION"
