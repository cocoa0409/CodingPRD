"""One write that crosses three aggregates at once, read back with no sweep and no
second write in between.
"""

from test_helpers import (
    AssayMethod,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    RiskClass,
    make_admin_headers,
    make_lab_technician_headers,
    read_applicant,
    read_product,
    setup_certification_ready_product,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
CA_DUE_ON = "2026-08-31T00:00:00Z"

CLEAN_SITE = {
    "site_name": "Plant 9",
    "shared_equipment_present": False,
    "gluten_containing_operations": GlutenContainingOperations.NONE,
}
ONE_CLEAN_LINE = (
    IngredientSpec(
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        inclusion_pct=55,
        doc_expires_on=DOC_EXPIRES,
    ),
)


def test_one_failing_lot_publishes_verdict_finding_and_posture_at_once(api):
    """The lab's own 201 already carries the applied bound and the verdict, the raised
    finding is listable with its points and its deadline, and the applicant's posture
    already reads 92.

    PRD: "Propagation is **immediate and complete within the request**. By the time a write
    returns 2xx, every derived count, every cascaded state and every recomputed score is
    already readable through the corresponding read endpoints; there is no deferred queue and
    no eventual convergence."
    PRD: "Every recorded lot snapshots `threshold_applied_ppm` from the product's
    `threshold_ppm` at record time, and that snapshot — not the product's later value — is
    the bound the verdict is judged against."
    PRD: "Recording a `SCHEDULED` lot also refreshes the product's
    `last_scheduled_sample_on`, which is the greatest `sample_collected_on` among that
    product's `SCHEDULED` lots whose `status` is `RECORDED`."

    Design: Corner/consistency_model/failing_lot_test_publishes_verdict_finding_and_posture_in_one_response
    """
    context = setup_certification_ready_product(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        review_label_decision=None,
        run_audit=False,
    )
    planned = read_product(api, context.product_id)
    assert planned["threshold_ppm"] == 20
    assert planned["last_scheduled_sample_on"] is None
    assert read_applicant(api, context.applicant_id)["posture_score_cycle"] == 100

    response = api.create_lot_test(
        make_lab_technician_headers("lab-1"),
        product_id=context.product_id,
        lot_code="RSL-L1",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=CLOCK_START,
        ppm_result=25.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    assert response.status_code == 201, response.text
    lot = response.json()["data"]

    assert lot["product_id"] == context.product_id
    assert lot["lot_code"] == "RSL-L1"
    assert lot["threshold_applied_ppm"] == 20
    assert lot["verdict"] == "FAIL"
    assert lot["status"] == "RECORDED"
    assert lot["nonconformance_created"] is True
    assert lot["in_recall_scope"] is False

    rows, meta = validate_paginated(
        api.list_nonconformances(
            make_admin_headers(), applicant_id=context.applicant_id
        )
    )
    assert meta["total_count"] == 1
    finding = rows[0]
    assert finding["source_type"] == "LOT_TEST"
    assert finding["category"] == "THRESHOLD_EXCEEDANCE"
    assert finding["severity"] == "MAJOR"
    assert finding["status"] == "OPEN"
    assert finding["penalty_points"] == 8
    assert finding["ca_due_on"] == CA_DUE_ON

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["posture_score_cycle"] == 92
    assert applicant["posture_score_rolling_12m"] == 92
    assert applicant["compliance_posture"] == "GOOD_STANDING"

    assert read_product(api, context.product_id)["last_scheduled_sample_on"] == CLOCK_START
