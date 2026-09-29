"""Validation gates on the supply side of the file: the sanitation swab ceiling, the
two document-verification bars, and the two gates an ingredient must clear to enter
and to leave review.
"""

from test_helpers import (
    ApiErrorId,
    AssayMethod,
    Decision,
    DocType,
    RiskClass,
    SupplierStatus,
    add_supplier_document,
    create_ingredient,
    create_supplier,
    make_admin_headers,
    make_applicant_contact_headers,
    make_auditor_headers,
    make_reviewer_headers,
    read_facility,
    read_ingredient,
    read_supplier,
    read_supplier_document,
    set_clock,
    setup_applicant_with_facility,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
FIRST_EXPIRY = "2027-08-01T00:00:00Z"
RESWAB_DAY = "2026-09-01T00:00:00Z"
SECOND_EXPIRY = "2027-09-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"


def _a_site_validated_at_two_ppm_a_month_ago(api):
    """One facility validated on 2026-08-01 with a 2.0 ppm G12_ELISA swab, read a month
    later at 2026-09-01.

    The first record is well inside its 365 days, so the facility is `VALIDATED` when
    the second swab arrives and the self-loop is the only thing under test.
    """
    context = setup_applicant_with_facility(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
    )
    first = validate_success(
        api.validate_sanitation(
            context.facility_id,
            make_auditor_headers("aud-1"),
            swab_ppm=2.0,
            method=AssayMethod.G12_ELISA,
            validated_on=CLOCK_START,
        )
    )
    assert first["sanitation_expires_on"] == FIRST_EXPIRY
    set_clock(api, RESWAB_DAY)
    return context, first


def test_a_swab_of_exactly_five_ppm_revalidates_and_rebases_the_expiry(api):
    """5.0 ppm is inside the inclusive ceiling, and the accepted record replaces the
    stored swab and moves the expiry to a year past the new reading.

    PRD: "The swab must read at most 5 ppm; exactly 5 ppm is accepted, and 5.1 ppm is
    rejected with `ERR_SANITATION_SWAB_ABOVE_LIMIT`."
    PRD: "The same operation is accepted from all three of `UNVALIDATED`, `VALIDATED` and
    `EXPIRED`: a facility already `VALIDATED` may be re-validated, which replaces the
    stored swab record and re-bases `sanitation_expires_on` from the new `validated_on`,
    and a facility that has lapsed to `EXPIRED` returns to `VALIDATED` on the same terms."

    Design: Corner/validations/sanitation_revalidation_at_exactly_the_swab_limit_is_accepted
    """
    context, first = _a_site_validated_at_two_ppm_a_month_ago(api)

    response = api.validate_sanitation(
        context.facility_id,
        make_auditor_headers("aud-1"),
        swab_ppm=5.0,
        method=AssayMethod.R5_ELISA,
        validated_on=RESWAB_DAY,
    )
    assert response.status_code == 200, response.text
    revalidated = response.json()["data"]

    assert revalidated["sanitation_validation_status"] == "VALIDATED"
    assert revalidated["sanitation_swab_ppm"] == 5.0
    assert revalidated["sanitation_method"] == AssayMethod.R5_ELISA
    assert revalidated["sanitation_validated_on"] == RESWAB_DAY
    assert revalidated["sanitation_expires_on"] == SECOND_EXPIRY
    assert first["sanitation_expires_on"] == FIRST_EXPIRY


def test_a_swab_a_tenth_above_the_limit_leaves_the_record_untouched(api):
    """5.1 ppm is refused with 422 and none of the four sanitation fields is partially
    overwritten.

    PRD: "**Swab within limit.** On a sanitation validation, `swab_ppm` is at most 5 ppm;
    a swab of exactly 5 ppm is accepted and 5.1 ppm is not. A breach is
    `ERR_SANITATION_SWAB_ABOVE_LIMIT` (422)."
    PRD: "On acceptance the facility copies the submitted values into
    `sanitation_swab_ppm`, `sanitation_method` and `sanitation_validated_on`, sets
    `sanitation_expires_on` to 365 days after `validated_on`, and moves
    `sanitation_validation_status` to `VALIDATED`."

    Design: Corner/validations/sanitation_swab_one_tenth_above_the_limit_is_rejected
    """
    context, first = _a_site_validated_at_two_ppm_a_month_ago(api)

    response = api.validate_sanitation(
        context.facility_id,
        make_reviewer_headers("rev-1"),
        swab_ppm=5.1,
        method=AssayMethod.R5_ELISA,
        validated_on=RESWAB_DAY,
    )
    validate_error(response, ApiErrorId.SANITATION_SWAB_ABOVE_LIMIT, 422)

    row = read_facility(api, context.facility_id)
    assert row["sanitation_swab_ppm"] == 2.0
    assert row["sanitation_method"] == AssayMethod.G12_ELISA
    assert row["sanitation_validated_on"] == CLOCK_START
    assert row["sanitation_expires_on"] == FIRST_EXPIRY
    assert row["version"] == first["version"]


def test_a_coa_claiming_six_ppm_on_a_high_risk_grain_is_refused(api):
    """A 6 ppm claim is over the 5 ppm cap the ingredient's risk class sets, and the
    refused document stays PENDING rather than becoming REJECTED.

    PRD: "**Certificate-of-analysis claim within cap.** On an approving document
    verification of a certificate of analysis, `lab_ppm_claim` is at most the cap for the
    referenced ingredient's risk class — otherwise `ERR_COA_PPM_CLAIM_TOO_HIGH` (422). A
    claim exactly at the cap is accepted."
    PRD: "And for a `COA`, `lab_ppm_claim` must be at most the cap set by the referenced
    ingredient's `risk_class`: 20 ppm for `INHERENTLY_GF`, 10 ppm for `GF_PROCESSED` and 5
    ppm for `HIGH_RISK_GRAIN`."

    Design: Corner/validations/coa_claiming_more_ppm_than_the_risk_class_cap_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Purity Protocol Oats",
        risk_class=RiskClass.HIGH_RISK_GRAIN,
    )
    document = add_supplier_document(
        api,
        context.applicant_id,
        supplier["id"],
        ingredient["id"],
        doc_type=DocType.COA,
        expires_on=DOC_EXPIRES,
        lab_ppm_claim=6,
        verify=False,
    )
    assert document["lab_ppm_claim"] == 6

    response = api.verify_supplier_document(
        document["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )
    validate_error(response, ApiErrorId.COA_PPM_CLAIM_TOO_HIGH, 422)

    row = read_supplier_document(api, document["id"])
    assert row["status"] == "PENDING"
    assert row["verified_by_user_id"] is None
    assert read_supplier(api, supplier["id"])["verified_document_count"] == 0
    assert read_ingredient(api, ingredient["id"])["verified_doc_types"] == []


def test_a_document_whose_expiry_has_passed_cannot_be_verified(api):
    """With the clock a day past `expires_on` and no sweep having run, the row is still
    PENDING and the approval is refused on the clock rather than on the status.

    PRD: "**Documents still in force.** At verification the supplier document's
    `expires_on` is strictly after the logical clock, and at an approving ingredient
    review every document counted toward the required set has `expires_on` strictly after
    the logical clock. A breach is `ERR_SUPPLIER_DOCUMENT_EXPIRED` (422)."
    PRD: "The document's `expires_on` must be strictly after the logical clock — a
    document that has already lapsed cannot be verified, and the refusal is
    `ERR_SUPPLIER_DOCUMENT_EXPIRED`."

    Design: Corner/validations/verification_of_an_already_expired_document_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Oat Flour",
        risk_class=RiskClass.GF_PROCESSED,
    )
    document = add_supplier_document(
        api,
        context.applicant_id,
        supplier["id"],
        ingredient["id"],
        doc_type=DocType.ALLERGEN_STATEMENT,
        expires_on="2026-08-15T00:00:00Z",
        verify=False,
    )
    assert document["status"] == "PENDING"

    set_clock(api, "2026-08-16T00:00:00Z")
    response = api.verify_supplier_document(
        document["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )
    validate_error(response, ApiErrorId.SUPPLIER_DOCUMENT_EXPIRED, 422)

    row = read_supplier_document(api, document["id"])
    assert row["status"] == "PENDING"
    assert row["verified_on"] is None
    assert read_supplier(api, supplier["id"])["verified_document_count"] == 0


def test_a_draft_ingredient_cannot_be_decided_without_a_submission(api):
    """A reviewer aiming an APPROVE at a DRAFT ingredient is refused 409, and the row
    still shows no review lap.

    PRD: "**Ingredient state.** The ingredient is in a state that permits the requested
    operation: submission for review requires `DRAFT`, `REJECTED` or `BLOCKED`; a review
    decision requires `UNDER_REVIEW`; linking the ingredient into a product formula
    requires any state other than `REJECTED`. A breach is
    `ERR_INVALID_INGREDIENT_STATE` (409)."
    PRD: "A new ingredient starts with `status` of `DRAFT`, `review_cycle_count` of 0,
    `verified_doc_types` as an empty list, and `blocked_reason`, `rejection_reason`,
    `reviewed_by_user_id` and `approved_on` all null."

    Design: Corner/validations/ingredient_review_of_a_draft_record_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    add_supplier_document(
        api,
        context.applicant_id,
        supplier["id"],
        ingredient["id"],
        doc_type=DocType.ALLERGEN_STATEMENT,
        expires_on=DOC_EXPIRES,
    )
    assert ingredient["status"] == "DRAFT"

    response = api.review_ingredient(
        ingredient["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )
    validate_error(response, ApiErrorId.INVALID_INGREDIENT_STATE, 409)

    row = read_ingredient(api, ingredient["id"])
    assert row["status"] == "DRAFT"
    assert row["review_cycle_count"] == 0
    assert row["reviewed_by_user_id"] is None
    assert row["approved_on"] is None


def test_a_suspended_supplier_blocks_the_ingredient_at_the_submission_door(api):
    """With the supplier moved to SUSPENDED the applicant's submission is refused 422,
    and the ingredient never leaves DRAFT nor counts a lap.

    PRD: "**Supplier not suspended.** The ingredient's supplier does not have `status` of
    `SUSPENDED` — otherwise `ERR_SUPPLIER_SUSPENDED` (422). This guards ingredient
    submission for review, ingredient review decisions and formula-line linking."
    PRD: "In every case the ingredient moves to `UNDER_REVIEW` and `review_cycle_count`
    increases by 1; `blocked_reason` is cleared to null, and on a resubmission after a
    rejection `rejection_reason` is cleared to null as well."

    Design: Corner/validations/ingredient_submission_while_its_supplier_is_suspended_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    suspended = validate_success(
        api.set_supplier_status(
            supplier["id"], SupplierStatus.SUSPENDED, make_admin_headers()
        )
    )
    assert suspended["status"] == SupplierStatus.SUSPENDED

    response = api.submit_ingredient(
        ingredient["id"], make_applicant_contact_headers(context.applicant_id)
    )
    validate_error(response, ApiErrorId.SUPPLIER_SUSPENDED, 422)

    row = read_ingredient(api, ingredient["id"])
    assert row["status"] == "DRAFT"
    assert row["review_cycle_count"] == 0
    assert row["blocked_reason"] is None
