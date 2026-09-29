"""Validation gates around the product file: the two formula-clearance preconditions,
the plan-activation state gate, the two uniqueness guards, the cross-applicant facility
check, the two lot-recording bars and the mark-tier equality rule.
"""

from test_helpers import (
    ApiErrorId,
    AssayMethod,
    Decision,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    MarkTier,
    RiskClass,
    create_applicant,
    create_facility,
    create_ingredient,
    create_product,
    create_supplier,
    link_ingredient,
    make_admin_headers,
    make_applicant_contact_headers,
    make_lab_technician_headers,
    make_reviewer_headers,
    read_applicant,
    read_product,
    review_formula,
    set_clock,
    setup_applicant_with_facility,
    setup_certification_ready_product,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
SAMPLE_CLOCK = "2026-08-10T12:00:00Z"
ONE_SECOND_LATE = "2026-08-10T12:00:01Z"


def test_an_empty_formula_is_refused_before_any_line_is_inspected(api):
    """A product with zero formula lines cannot be cleared, and the refusal names the
    empty formula rather than any ingredient state.

    PRD: "**Formula not empty.** The product's `linked_ingredient_count` is at least 1 —
    otherwise `ERR_NO_INGREDIENTS_LINKED` (422). This guards a clearing formula review and
    testing-plan activation."
    PRD: "A new product opens with `formula_status` of `DRAFT`, `label_status` of
    `NOT_SUBMITTED`, `testing_plan_status` of `NONE`, `testing_plan_revision` of 0,
    `mark_tier_granted` of `NONE`, `linked_ingredient_count` and `blocked_ingredient_count`
    of 0, `threshold_ppm` and `sampling_lots_per_year` and `sampling_exclusion_days` all
    null, and `formula_cleared_by_user_id`, `label_reviewed_by_user_id`,
    `label_rejection_reason` and `last_scheduled_sample_on` all null."

    Design: Corner/validations/formula_review_with_no_linked_lines_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )
    assert product["linked_ingredient_count"] == 0

    response = api.review_formula(
        product["id"], make_reviewer_headers("rev-1"), decision=Decision.CLEAR
    )
    validate_error(response, ApiErrorId.NO_INGREDIENTS_LINKED, 422)

    row = read_product(api, product["id"])
    assert row["formula_status"] == "DRAFT"
    assert row["formula_cleared_by_user_id"] is None
    assert row["threshold_ppm"] is None


def test_a_single_unapproved_line_blocks_the_whole_clearance(api):
    """One DRAFT ingredient on an otherwise legal product answers 422 on the ingredient
    approval gate, not on the ingredient's own state machine.

    PRD: "**Linked ingredients approved.** Every ingredient referenced by a formula line
    of the product has `status` of `APPROVED` — otherwise `ERR_INGREDIENT_NOT_APPROVED`
    (422). This guards a clearing formula review and certificate issuance."
    PRD: "On clearance `formula_status` becomes `CLEARED` and `formula_cleared_by_user_id`
    records the acting `X-User-ID`; that recorded identifier is precisely the value the
    segregation-of-duties check at issuance later compares against."

    Design: Corner/validations/formula_review_with_a_draft_line_is_rejected_as_ingredient_not_approved
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
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )
    link_ingredient(api, context.applicant_id, product["id"], ingredient["id"], 100)
    assert ingredient["status"] == "DRAFT"

    response = api.review_formula(
        product["id"], make_reviewer_headers("rev-1"), decision=Decision.CLEAR
    )
    validate_error(response, ApiErrorId.INGREDIENT_NOT_APPROVED, 422)

    row = read_product(api, product["id"])
    assert row["linked_ingredient_count"] == 1
    assert row["formula_status"] == "DRAFT"
    assert row["testing_plan_status"] == "NONE"


def test_a_rejected_formula_cannot_have_its_testing_plan_activated(api):
    """The version supplied is current, so the 409 can only be the formula dimension:
    activation demands CLEARED and REJECTED is not it.

    PRD: "**Product dimension state.** The product dimension the operation targets is in a
    permitted state: formula review requires `formula_status` of `DRAFT` or `REJECTED`;
    testing-plan activation requires `formula_status` of `CLEARED`; label review requires
    `label_status` of `NOT_SUBMITTED`, `REJECTED` or `APPROVED`; linking a formula line
    requires `formula_status` of `DRAFT` or `REJECTED`. A breach is
    `ERR_INVALID_PRODUCT_STATE` (409)."
    PRD: "A rejection from either `DRAFT` or `REJECTED` sets `formula_status` to `REJECTED`
    and leaves `formula_cleared_by_user_id` null, and it does not touch `label_status`."

    Design: Corner/validations/testing_plan_activation_on_an_uncleared_formula_is_rejected
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
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )
    link_ingredient(api, context.applicant_id, product["id"], ingredient["id"], 100)
    rejected = review_formula(
        api,
        product["id"],
        decision=Decision.REJECT,
        rejection_reason="Sub-component disclosure incomplete",
    )
    assert rejected["formula_status"] == "REJECTED"

    response = api.activate_testing_plan(
        product["id"],
        make_reviewer_headers("rev-1"),
        expected_product_version=rejected["version"],
    )
    validate_error(response, ApiErrorId.INVALID_PRODUCT_STATE, 409)

    row = read_product(api, product["id"])
    assert row["formula_status"] == "REJECTED"
    assert row["testing_plan_status"] == "NONE"
    assert row["threshold_ppm"] is None
    assert row["version"] == rejected["version"]


def test_the_sku_guard_is_scoped_to_the_owning_applicant(api):
    """A second applicant holds the identical SKU without complaint, and only the
    same-applicant reuse is refused.

    PRD: "**Unique SKU.** A product's `sku` is unique within its owning `applicant_id` —
    otherwise `ERR_DUPLICATE_SKU` (409)."
    PRD: "That `sku` must be unique among the products of the same `applicant_id`, or the
    declaration is refused with `ERR_DUPLICATE_SKU`, and the named facility must itself
    belong to the supplied `applicant_id`, or the refusal is
    `ERR_FACILITY_APPLICANT_MISMATCH`."

    Design: Corner/validations/reusing_a_sku_within_the_same_applicant_is_rejected
    """
    set_clock(api, CLOCK_START)
    northgate = create_applicant(api, legal_name="Northgate Bakehouse Ltd")
    southbank = create_applicant(
        api, legal_name="Southbank Snacks Inc", contact_email="qa@southbank.example"
    )
    plant_4 = create_facility(api, northgate["id"], site_name="Plant 4")
    plant_12 = create_facility(api, southbank["id"], site_name="Plant 12")

    create_product(
        api, northgate["id"], plant_4["id"], name="Rice Sandwich Loaf", sku="RSL-001"
    )
    twin = create_product(
        api, southbank["id"], plant_12["id"], name="Southbank Rice Loaf", sku="RSL-001"
    )
    assert twin["sku"] == "RSL-001"

    response = api.create_product(
        make_applicant_contact_headers(northgate["id"]),
        applicant_id=northgate["id"],
        facility_id=plant_4["id"],
        name="Rice Sandwich Loaf V2",
        sku="RSL-001",
    )
    validate_error(response, ApiErrorId.DUPLICATE_SKU, 409)

    for applicant_id in (northgate["id"], southbank["id"]):
        _rows, meta = validate_paginated(
            api.list_products(make_admin_headers(), applicant_id=applicant_id)
        )
        assert meta["total_count"] == 1


def test_relinking_the_same_ingredient_at_a_new_percentage_is_still_a_duplicate(api):
    """The junction is keyed on the pair alone, so a second link at 25 pct is refused and
    the original 60 pct line is left exactly as it was.

    PRD: "**Unique formula line.** No formula line already links this `product_id` to this
    `ingredient_id` — otherwise `ERR_DUPLICATE_PRODUCT_INGREDIENT` (409)."
    PRD: "Creating a line then recomputes the product's `linked_ingredient_count` and
    `blocked_ingredient_count`."

    Design: Corner/validations/linking_the_same_ingredient_to_a_product_twice_is_rejected
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
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )
    line = link_ingredient(
        api, context.applicant_id, product["id"], ingredient["id"], 60
    )

    response = api.link_product_ingredient(
        make_applicant_contact_headers(context.applicant_id),
        product_id=product["id"],
        ingredient_id=ingredient["id"],
        inclusion_pct=25,
    )
    validate_error(response, ApiErrorId.DUPLICATE_PRODUCT_INGREDIENT, 409)

    kept = validate_success(api.get_product_ingredient(line["id"], make_admin_headers()))
    assert kept["inclusion_pct"] == 60
    assert read_product(api, product["id"])["linked_ingredient_count"] == 1

    _rows, meta = validate_paginated(
        api.list_product_ingredients(make_admin_headers(), product_id=product["id"])
    )
    assert meta["total_count"] == 1


def test_a_product_cannot_name_a_plant_its_applicant_does_not_own(api):
    """Both identifiers resolve, so the refusal is the ownership check at 422 rather than
    a missing-resource answer, and neither side gains a product.

    PRD: "**Facility belongs to the applicant.** On product declaration, the referenced
    facility's `applicant_id` equals the `applicant_id` supplied on the product —
    otherwise `ERR_FACILITY_APPLICANT_MISMATCH` (422)."
    PRD: "An `ApplicantContact` declares a product for certification with the owning
    `applicant_id`, the `facility_id` of the site where it is manufactured, a `name` as it
    appears on the label, and a `sku`, the applicant-scoped stock keeping unit."

    Design: Corner/validations/product_pointing_at_another_applicants_facility_is_rejected
    """
    set_clock(api, CLOCK_START)
    northgate = create_applicant(api, legal_name="Northgate Bakehouse Ltd")
    southbank = create_applicant(
        api, legal_name="Southbank Snacks Inc", contact_email="qa@southbank.example"
    )
    plant_12 = create_facility(
        api,
        southbank["id"],
        site_name="Plant 12",
        shared_equipment_present=True,
        gluten_containing_operations=GlutenContainingOperations.SAME_LINE,
    )

    response = api.create_product(
        make_applicant_contact_headers(northgate["id"]),
        applicant_id=northgate["id"],
        facility_id=plant_12["id"],
        name="Borrowed Plant Loaf",
        sku="BPL-001",
    )
    validate_error(response, ApiErrorId.FACILITY_APPLICANT_MISMATCH, 422)

    _rows, by_applicant = validate_paginated(
        api.list_products(make_admin_headers(), applicant_id=northgate["id"])
    )
    assert by_applicant["total_count"] == 0
    _rows, by_facility = validate_paginated(
        api.list_products(make_admin_headers(), facility_id=plant_12["id"])
    )
    assert by_facility["total_count"] == 0


def test_a_lot_cannot_be_recorded_before_a_plan_gives_it_a_bound(api):
    """A 3.0 ppm result that would pass under every possible threshold is still refused,
    which places the gate on the plan and not on the number.

    PRD: "**Testing plan active.** The product's `testing_plan_status` is `ACTIVE` —
    otherwise `ERR_TESTING_PLAN_NOT_ACTIVE` (422). This guards lot-test recording and
    certificate issuance."
    PRD: "The product's `testing_plan_status` must be `ACTIVE` or the recording is refused
    with `ERR_TESTING_PLAN_NOT_ACTIVE`; `sample_collected_on` may not be after the logical
    clock (`ERR_SAMPLE_DATE_IN_FUTURE`); and `ppm_result` must be at least 0."

    Design: Corner/validations/lot_test_recorded_before_the_testing_plan_exists_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
    )
    assert product["testing_plan_status"] == "NONE"
    assert product["threshold_ppm"] is None

    response = api.create_lot_test(
        make_lab_technician_headers("lab-1"),
        product_id=product["id"],
        lot_code="RSL-L1",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=CLOCK_START,
        ppm_result=3.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    validate_error(response, ApiErrorId.TESTING_PLAN_NOT_ACTIVE, 422)

    _rows, meta = validate_paginated(
        api.list_lot_tests(make_admin_headers(), product_id=product["id"])
    )
    assert meta["total_count"] == 0
    assert read_applicant(api, context.applicant_id)["open_nc_penalty_points"] == 0


def test_a_sample_stamped_one_second_ahead_of_the_clock_is_refused(api):
    """The bound on `sample_collected_on` is checked to the second, so 12:00:01 against a
    12:00:00 clock is in the future even though it is the same day.

    PRD: "**Sample not in the future.** `sample_collected_on` is at or before the logical
    clock — otherwise `ERR_SAMPLE_DATE_IN_FUTURE` (422)."
    PRD: "The product's `testing_plan_status` must be `ACTIVE` or the recording is refused
    with `ERR_TESTING_PLAN_NOT_ACTIVE`; `sample_collected_on` may not be after the logical
    clock (`ERR_SAMPLE_DATE_IN_FUTURE`); and `ppm_result` must be at least 0."

    Design: Corner/validations/lot_test_sampled_one_second_after_the_clock_is_rejected
    """
    context = setup_certification_ready_product(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides={
            "site_name": "Plant 9",
            "shared_equipment_present": False,
            "gluten_containing_operations": GlutenContainingOperations.NONE,
        },
        ingredients=(
            IngredientSpec(
                name="Brown Rice Flour",
                risk_class=RiskClass.INHERENTLY_GF,
                inclusion_pct=55,
                doc_expires_on=DOC_EXPIRES,
            ),
        ),
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        review_label_decision=None,
        run_audit=False,
    )
    planned = read_product(api, context.product_id)
    assert planned["testing_plan_status"] == "ACTIVE"
    assert planned["threshold_ppm"] == 20

    set_clock(api, SAMPLE_CLOCK)
    response = api.create_lot_test(
        make_lab_technician_headers("lab-1"),
        product_id=context.product_id,
        lot_code="RSL-L1",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=ONE_SECOND_LATE,
        ppm_result=3.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    validate_error(response, ApiErrorId.SAMPLE_DATE_IN_FUTURE, 422)

    _rows, meta = validate_paginated(
        api.list_lot_tests(make_admin_headers(), product_id=context.product_id)
    )
    assert meta["total_count"] == 0


def test_the_reviewer_may_not_upgrade_the_tier_the_applicant_asked_for(api):
    """Granting PREMIUM against a STANDARD request is refused even though PREMIUM is a
    legal and stricter tier, and the label dimension does not move.

    PRD: "**Mark tier granted.** On an approving label review, the payload
    `mark_tier_granted` is present and equal to the product's `requested_mark_tier`; at
    issuance the product's `mark_tier_granted` is not `NONE` and equals
    `requested_mark_tier`. A breach is `ERR_MARK_TIER_NOT_GRANTED` (422)."
    PRD: "An approval must carry `mark_tier_granted` in the payload, and that value must
    equal the product's `requested_mark_tier`; a missing or mismatched tier is refused with
    `ERR_MARK_TIER_NOT_GRANTED`."

    Design: Corner/validations/label_review_granting_a_richer_tier_than_requested_is_rejected
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
        requested_mark_tier=MarkTier.STANDARD,
    )
    assert product["requested_mark_tier"] == MarkTier.STANDARD
    assert product["label_status"] == "NOT_SUBMITTED"
    assert product["mark_tier_granted"] == "NONE"

    response = api.review_label(
        product["id"],
        make_reviewer_headers("rev-1"),
        decision=Decision.APPROVE,
        mark_tier_granted=MarkTier.PREMIUM,
    )
    validate_error(response, ApiErrorId.MARK_TIER_NOT_GRANTED, 422)

    row = read_product(api, product["id"])
    assert row["label_status"] == "NOT_SUBMITTED"
    assert row["mark_tier_granted"] == "NONE"
    assert row["label_reviewed_by_user_id"] is None
