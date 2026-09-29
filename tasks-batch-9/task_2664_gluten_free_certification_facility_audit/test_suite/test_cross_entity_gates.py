"""Writes gated by the state of an entity the caller never names: the product's
facility sanitation dimension, and an ingredient's supplier document set.
"""

from test_helpers import (
    ApiErrorId,
    Decision,
    DocType,
    IngredientSpec,
    RiskClass,
    add_supplier_document,
    advance_and_sweep,
    create_ingredient,
    create_supplier,
    make_admin_headers,
    make_decision_maker_headers,
    make_reviewer_headers,
    read_applicant,
    read_facility,
    read_ingredient,
    read_product,
    read_supplier,
    review_ingredient,
    setup_applicant_with_facility,
    setup_certification_ready_product,
    submit_ingredient,
    validate_error,
    validate_paginated,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
SANITATION_LAPSED_DAY = "2027-08-04T00:00:00Z"
DOC_ISSUED = "2026-07-01T00:00:00Z"

SOLE_LINE = IngredientSpec(
    name="Brown Rice Flour",
    risk_class=RiskClass.INHERENTLY_GF,
    inclusion_pct=40,
    doc_issued_on=DOC_ISSUED,
    doc_expires_on="2029-07-01T00:00:00Z",
)


def _issuable_product_whose_facility_validation_lapsed(api):
    """A product that is perfect on every dimension it owns, on a facility whose
    sanitation validation the sweep has just expired.

    The validation was recorded on 2026-08-03, so it expires 2027-08-03, and the
    sweep is run one day later; the ingredient document runs to 2029 so nothing else
    the sweep touches can interfere.
    """
    context = setup_certification_ready_product(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SOLE_LINE,),
    )
    facility = read_facility(api, context.facility_id)
    assert facility["sanitation_expires_on"] == "2027-08-03T00:00:00Z"

    summary = advance_and_sweep(api, SANITATION_LAPSED_DAY)
    assert summary["facility_validations_expired"] == 1
    return context, summary


def test_issuance_fails_on_a_facility_dimension_the_request_never_names(api):
    """The sweep's expiry of the sanitation validation two hops away is enough to
    refuse the issuance with 422.

    PRD: "Once `sanitation_expires_on` has been reached, the next surveillance sweep
    moves the facility from `VALIDATED` to `EXPIRED`."
    PRD: "**Sanitation currently validated.** The relevant facility's
    `sanitation_validation_status` is `VALIDATED` at the instant of the call; both
    `UNVALIDATED` and `EXPIRED` fail with `ERR_FACILITY_SANITATION_NOT_VALIDATED`
    (422). Three operations are guarded: closing an audit, issuing a certificate and
    reinstating a certificate."

    Design: Difficulty/cross_entity_state_dependency/issuance_blocked_by_facility_sanitation_expired_by_the_sweep
    """
    context, _summary = _issuable_product_whose_facility_validation_lapsed(api)

    response = api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=context.product_id,
        expected_product_version=context.product_version,
    )
    validate_error(response, ApiErrorId.FACILITY_SANITATION_NOT_VALIDATED, 422)

    facility = read_facility(api, context.facility_id)
    assert facility["sanitation_validation_status"] == "EXPIRED"
    assert facility["last_closed_audit_outcome"] == "CLOSED_PASS"


def test_the_refused_issuance_persists_no_certificate_and_no_fee(api):
    """No certificate row, no fee, no opened certification cycle, and the product's
    version is exactly the one the request offered.

    PRD: "`current_cycle_started_on` is the earliest `issued_on` among that
    applicant's certificates whose `status` is `ISSUED` or `SUSPENDED`, and it stays
    null while no such certificate exists."
    PRD: "`total_fee_cents` is then added to the applicant's `fee_balance_cents`."

    Design: Difficulty/cross_entity_state_dependency/issuance_blocked_by_facility_sanitation_expired_by_the_sweep
    """
    context, _summary = _issuable_product_whose_facility_validation_lapsed(api)

    api.issue_certificate(
        make_decision_maker_headers("dm-1"),
        product_id=context.product_id,
        expected_product_version=context.product_version,
    )

    rows, _meta = validate_paginated(
        api.list_certificates(make_admin_headers(), product_id=context.product_id)
    )
    assert rows == []

    product = read_product(api, context.product_id)
    assert product["formula_status"] == "CLEARED"
    assert product["label_status"] == "APPROVED"
    assert product["version"] == context.product_version

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["fee_balance_cents"] == 0
    assert applicant["current_cycle_started_on"] is None
    assert applicant["posture_score_cycle"] == 100


def _two_high_risk_ingredients_one_missing_its_coa(api):
    """Two HIGH_RISK_GRAIN ingredients from one supplier: the first has its
    ALLERGEN_STATEMENT and PROCESS_FLOW verified but its COA left PENDING, while the
    second has all three verified and is APPROVED.

    The pending COA claims exactly the 5 ppm cap for the risk class, so nothing about
    the document's own content is what holds the first ingredient back.
    """
    context = setup_applicant_with_facility(api, clock=SANITATION_DAY)
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")

    incomplete = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Oat Groats",
        risk_class=RiskClass.HIGH_RISK_GRAIN,
    )
    for doc_type in (DocType.ALLERGEN_STATEMENT, DocType.PROCESS_FLOW):
        add_supplier_document(
            api,
            context.applicant_id,
            supplier["id"],
            incomplete["id"],
            doc_type=doc_type,
            issued_on=DOC_ISSUED,
            expires_on="2029-07-01T00:00:00Z",
        )
    add_supplier_document(
        api,
        context.applicant_id,
        supplier["id"],
        incomplete["id"],
        doc_type=DocType.COA,
        issued_on=DOC_ISSUED,
        expires_on="2029-07-01T00:00:00Z",
        lab_ppm_claim=5,
        verify=False,
    )

    complete = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Sorghum Grain",
        risk_class=RiskClass.HIGH_RISK_GRAIN,
    )
    for doc_type in (DocType.ALLERGEN_STATEMENT, DocType.PROCESS_FLOW):
        add_supplier_document(
            api,
            context.applicant_id,
            supplier["id"],
            complete["id"],
            doc_type=doc_type,
            issued_on=DOC_ISSUED,
            expires_on="2029-07-01T00:00:00Z",
        )
    add_supplier_document(
        api,
        context.applicant_id,
        supplier["id"],
        complete["id"],
        doc_type=DocType.COA,
        issued_on=DOC_ISSUED,
        expires_on="2029-07-01T00:00:00Z",
        lab_ppm_claim=5,
    )

    submit_ingredient(api, context.applicant_id, incomplete["id"])
    submit_ingredient(api, context.applicant_id, complete["id"])
    approved = review_ingredient(api, complete["id"])
    assert approved["status"] == "APPROVED"
    return context, supplier, incomplete, complete


def test_approval_is_refused_while_one_required_document_class_is_still_pending(api):
    """A HIGH_RISK_GRAIN ingredient needs all three classes verified, so the review
    is refused even though the missing document exists and its claim is within cap.

    PRD: "**Required documents verified.** On an approving ingredient review, the
    ingredient's `verified_doc_types` covers every document class its risk class
    demands — otherwise `ERR_REQUIRED_SUPPLIER_DOCS_MISSING` (422)."
    PRD: "A `HIGH_RISK_GRAIN` ingredient requires `ALLERGEN_STATEMENT`,
    `PROCESS_FLOW` and `COA`."

    Design: Difficulty/cross_entity_state_dependency/ingredient_approval_gated_by_verified_document_set_of_its_supplier
    """
    _context, _supplier, incomplete, _complete = _two_high_risk_ingredients_one_missing_its_coa(api)

    response = api.review_ingredient(
        incomplete["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )
    validate_error(response, ApiErrorId.REQUIRED_SUPPLIER_DOCS_MISSING, 422)

    row = read_ingredient(api, incomplete["id"])
    assert row["status"] == "UNDER_REVIEW"
    assert row["approved_on"] is None
    assert row["review_cycle_count"] == 1
    assert row["verified_doc_types"] == ["ALLERGEN_STATEMENT", "PROCESS_FLOW"]


def test_the_supplier_counter_and_the_sibling_ingredient_are_unaffected(api):
    """Five of the supplier's six documents are verified, and the sibling ingredient
    whose set is complete is APPROVED.

    PRD: "A new supplier's `status` is `ACTIVE` and its `verified_document_count` is
    0; that counter is always the number of this supplier's documents whose `status`
    is `VERIFIED`."
    PRD: "On approval the ingredient moves `UNDER_REVIEW → APPROVED`, records
    `reviewed_by_user_id` as the acting `X-User-ID` and `approved_on` as the logical
    clock, and clears `blocked_reason` to null."

    Design: Difficulty/cross_entity_state_dependency/ingredient_approval_gated_by_verified_document_set_of_its_supplier
    """
    _context, supplier, incomplete, complete = _two_high_risk_ingredients_one_missing_its_coa(api)

    api.review_ingredient(
        incomplete["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )

    assert read_supplier(api, supplier["id"])["verified_document_count"] == 5

    sibling = read_ingredient(api, complete["id"])
    assert sibling["status"] == "APPROVED"
    assert sibling["reviewed_by_user_id"] == "rev-1"
    assert sibling["approved_on"] == SANITATION_DAY
    assert sibling["blocked_reason"] is None
