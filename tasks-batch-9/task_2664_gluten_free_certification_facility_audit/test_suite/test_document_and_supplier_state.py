"""Terminal and non-idempotent edges on the supply side: a rejected document that
cannot be re-approved, a supplier standing replayed at its own value, and the
FOR_CAUSE retest that retires an earlier lot of the same code.
"""

from test_helpers import (
    ApiErrorId,
    AssayMethod,
    Decision,
    DocRejectionReason,
    DocType,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    RiskClass,
    SupplierStatus,
    add_supplier_document,
    create_ingredient,
    create_supplier,
    make_admin_headers,
    make_lab_technician_headers,
    make_reviewer_headers,
    read_applicant,
    read_ingredient,
    read_lot_test,
    read_product,
    read_supplier,
    read_supplier_document,
    record_lot_test,
    set_clock,
    setup_applicant_with_facility,
    setup_certification_ready_product,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_ISSUED = "2026-07-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
FIRST_SAMPLE = "2026-08-05T00:00:00Z"
RETEST_DAY = "2026-08-06T00:00:00Z"


def _an_ingredient_whose_only_document_was_rejected(api):
    """One applicant with one supplier and one DRAFT GF_PROCESSED ingredient, whose
    single PROCESS_FLOW document reviewer rev-1 has rejected as ILLEGIBLE.

    The document was live when it was decided — it runs to 2028 — so the rejection is
    the only reason it is not verified.
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
        doc_type=DocType.PROCESS_FLOW,
        issued_on=DOC_ISSUED,
        expires_on=DOC_EXPIRES,
        verify=False,
    )
    rejected = validate_success(
        api.verify_supplier_document(
            document["id"],
            make_reviewer_headers("rev-1"),
            decision=Decision.REJECT,
            rejection_reason=DocRejectionReason.ILLEGIBLE,
        )
    )
    assert rejected["status"] == "REJECTED"
    return context, supplier, ingredient, rejected


def test_a_rejected_document_cannot_be_quietly_re_approved(api):
    """Re-posting the verification with APPROVE on a REJECTED document answers 409 and
    the first decision survives untouched.

    PRD: "Only a `PENDING` document may be decided; a second decision on an
    already-decided document is refused with `ERR_DOCUMENT_ALREADY_DECIDED`."
    PRD: "`REJECTED` and `EXPIRED` are both terminal for a document; neither can be
    revived, and a replacement must be uploaded instead."

    Design: Corner/state_machines/supplier_document_verified_twice_is_rejected_as_already_decided
    """
    _context, supplier, ingredient, rejected = _an_ingredient_whose_only_document_was_rejected(api)

    response = api.verify_supplier_document(
        rejected["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )
    validate_error(response, ApiErrorId.DOCUMENT_ALREADY_DECIDED, 409)

    row = read_supplier_document(api, rejected["id"])
    assert row["status"] == "REJECTED"
    assert row["rejection_reason"] == DocRejectionReason.ILLEGIBLE
    assert row["verified_by_user_id"] is None
    assert row["verified_on"] is None
    assert row["version"] == rejected["version"]

    assert read_supplier(api, supplier["id"])["verified_document_count"] == 0
    assert read_ingredient(api, ingredient["id"])["verified_doc_types"] == []


def test_reposting_a_supplier_standing_at_its_current_value_is_refused(api):
    """A supplier already moved to UNDER_REVIEW cannot be moved there again, and the
    rejected replay does not advance its version.

    PRD: "Only a `ProgramAdministrator` may move a supplier's standing, and the
    requested `status` must differ from the current one or the request fails with
    `ERR_SUPPLIER_STATUS_UNCHANGED`. `ACTIVE → UNDER_REVIEW` is advisory: it refreshes
    the supplier's `updated_at`, increases its `version` by 1, and deliberately leaves
    every ingredient that supplier feeds exactly where it is."

    Design: Corner/state_machines/supplier_status_reposted_at_its_current_value_is_rejected
    """
    set_clock(api, CLOCK_START)
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")
    assert supplier["version"] == 1

    under_review = validate_success(
        api.set_supplier_status(
            supplier["id"], SupplierStatus.UNDER_REVIEW, make_admin_headers()
        )
    )
    assert under_review["status"] == SupplierStatus.UNDER_REVIEW
    assert under_review["version"] == 2

    response = api.set_supplier_status(
        supplier["id"], SupplierStatus.UNDER_REVIEW, make_admin_headers()
    )
    validate_error(response, ApiErrorId.SUPPLIER_STATUS_UNCHANGED, 409)

    row = read_supplier(api, supplier["id"])
    assert row["status"] == SupplierStatus.UNDER_REVIEW
    assert row["version"] == 2


def _a_scheduled_lot_then_a_for_cause_retest_of_the_same_code(api):
    """A STANDARD product on a site with no shared equipment and no gluten operations,
    so every threshold cap is 20 and the plan lands on the two-lot floor.

    Lot RSL-L1 is sampled SCHEDULED on 2026-08-05 at 12.0 ppm and passes; the clock
    then moves to 2026-08-06 and the same lot code is re-tested FOR_CAUSE at 18.0 ppm,
    still under the 20 ppm bound so nothing fails and no finding can confound the read.
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
    product = read_product(api, context.product_id)
    assert product["threshold_ppm"] == 20
    assert product["sampling_lots_per_year"] == 2
    assert product["sampling_exclusion_days"] == 182

    set_clock(api, FIRST_SAMPLE)
    first = record_lot_test(
        api,
        context.product_id,
        lot_code="RSL-L1",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=FIRST_SAMPLE,
        ppm_result=12.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    assert first["verdict"] == "PASS"

    set_clock(api, RETEST_DAY)
    response = api.create_lot_test(
        make_lab_technician_headers(),
        product_id=context.product_id,
        lot_code="RSL-L1",
        test_type=LotTestType.FOR_CAUSE,
        sample_collected_on=RETEST_DAY,
        ppm_result=18.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    return context, first, response


def test_the_for_cause_retest_is_recorded_against_the_snapshotted_bound(api):
    """The retest answers 201 as a RECORDED FOR_CAUSE lot, snapshots the same 20 ppm
    bound, passes at 18.0 and enters recall scope at false.

    PRD: "Every recorded lot snapshots `threshold_applied_ppm` from the product's
    `threshold_ppm` at record time, and that snapshot — not the product's later value —
    is the bound the verdict is judged against."
    PRD: "A new lot's `status` is `RECORDED`, `nonconformance_created` is false and
    `in_recall_scope` is false."

    Design: Corner/state_machines/for_cause_retest_supersedes_the_earlier_lot_test_of_the_same_lot_code
    """
    context, _first, response = _a_scheduled_lot_then_a_for_cause_retest_of_the_same_code(api)

    assert response.status_code == 201, response.text
    retest = response.json()["data"]
    assert retest["test_type"] == LotTestType.FOR_CAUSE
    assert retest["status"] == "RECORDED"
    assert retest["threshold_applied_ppm"] == 20
    assert retest["verdict"] == "PASS"
    assert retest["nonconformance_created"] is False
    assert retest["in_recall_scope"] is False

    assert read_applicant(api, context.applicant_id)["open_nc_penalty_points"] == 0


def test_the_earlier_lot_is_retired_but_keeps_its_own_verdict_and_bound(api):
    """The first lot moves to SUPERSEDED_BY_RETEST while keeping its PASS and its 20 ppm
    snapshot, its recall eligibility drops to false, and both rows remain listed.

    PRD: "When a `FOR_CAUSE` lot is recorded for the same `product_id` and the same
    `lot_code` as an existing lot whose `status` is `RECORDED`, and the earlier lot's
    `sample_collected_on` is at or before the new one's, the earlier lot moves `RECORDED
    → SUPERSEDED_BY_RETEST`. A superseded lot keeps its `verdict` and its
    `threshold_applied_ppm` as historical record but stops being eligible for recall
    scoping, and its `in_recall_scope` is recomputed to false."

    Design: Corner/state_machines/for_cause_retest_supersedes_the_earlier_lot_test_of_the_same_lot_code
    """
    context, first, _response = _a_scheduled_lot_then_a_for_cause_retest_of_the_same_code(api)

    superseded = read_lot_test(api, first["id"])
    assert superseded["status"] == "SUPERSEDED_BY_RETEST"
    assert superseded["verdict"] == "PASS"
    assert superseded["threshold_applied_ppm"] == 20
    assert superseded["in_recall_scope"] is False

    _rows, meta = validate_paginated(
        api.list_lot_tests(make_admin_headers(), product_id=context.product_id)
    )
    assert meta["total_count"] == 2


def test_a_for_cause_retest_never_moves_the_scheduled_sampling_date(api):
    """`last_scheduled_sample_on` still reads 2026-08-05 after the FOR_CAUSE retest,
    because only SCHEDULED lots refresh it.

    PRD: "Recording a `SCHEDULED` lot also refreshes the product's
    `last_scheduled_sample_on`, which is the greatest `sample_collected_on` among that
    product's `SCHEDULED` lots whose `status` is `RECORDED`."

    Design: Corner/state_machines/for_cause_retest_supersedes_the_earlier_lot_test_of_the_same_lot_code
    """
    context, _first, _response = _a_scheduled_lot_then_a_for_cause_retest_of_the_same_code(api)

    product = read_product(api, context.product_id)
    assert product["last_scheduled_sample_on"] == FIRST_SAMPLE
    assert product["testing_plan_status"] == "ACTIVE"
