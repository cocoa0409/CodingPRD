"""Three endpoints read for what they publish: the assessment that branches on impact
and cascades, the document verification that touches both ends of its link, and the
applicant read as a pure derived projection.
"""

from test_helpers import (
    ChangeType,
    Decision,
    DocType,
    GlutenContainingOperations,
    ImpactLevel,
    IngredientSpec,
    NcCategory,
    NcSeverity,
    NcSourceType,
    RiskClass,
    add_supplier_document,
    create_applicant,
    create_ingredient,
    create_supplier,
    file_change_notification,
    make_admin_headers,
    make_reviewer_headers,
    raise_nonconformance,
    read_applicant,
    read_certificate,
    read_ingredient,
    read_nonconformance,
    read_product,
    read_supplier,
    read_supplier_document,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    setup_issued_certificate,
    start_audit,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_ISSUED = "2026-07-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
AUDIT_OPENS = "2026-08-05T09:00:00Z"
AUDIT_CLOSES = "2026-08-05T17:00:00Z"
ISSUE_DAY = "2026-08-06T00:00:00Z"
THIRTY_DAYS_OUT = "2026-09-05T00:00:00Z"

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


def _a_submitted_supplier_change_on_a_live_certificate(api):
    """One certified STANDARD product with a SUPPLIER_CHANGE notification filed exactly
    30 days ahead of its effective date, so it is `SUBMITTED` and not late.

    The notice period is satisfied on purpose: the only thing left to decide is the
    assessed impact, which is what the assessment endpoint branches on.
    """
    context = setup_issued_certificate(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        onsite_start_at=AUDIT_OPENS,
        onsite_end_at=AUDIT_CLOSES,
        audit_start_clock=AUDIT_OPENS,
        audit_close_clock=AUDIT_CLOSES,
        issue_clock=ISSUE_DAY,
    )
    notification = file_change_notification(
        api,
        context.applicant_id,
        context.certificate_id,
        change_type=ChangeType.SUPPLIER_CHANGE,
        effective_on=THIRTY_DAYS_OUT,
        description="Second mill added as an alternate source",
    )
    assert notification["status"] == "SUBMITTED"
    assert context.certificate["mark_usage_locked"] is False
    return context, notification


def test_an_accept_at_high_impact_lands_where_a_reject_would(api):
    """The branch is chosen by `impact_level` and not by the decision, so an ACCEPT
    carrying HIGH answers 200 in REJECTED_REQUIRES_RECERT and suspends the certificate.

    PRD: "A `REJECT`, and equally an `impact_level` of `HIGH` whatever the decision says,
    moves it to `REJECTED_REQUIRES_RECERT`, sets `required_retest` to true, suspends an
    `ISSUED` linked certificate with `suspension_reason` of `CHANGE_REQUIRES_RECERT` —
    freezing the product's `label_status` and recomputing the applicant's posture — and
    raises a nonconformance with `source_type` of `CHANGE_NOTIFICATION`, `category` of
    `DOCUMENTATION`, `severity` of `MAJOR`, `certificate_id` set to the linked certificate,
    `applicant_id` taken from that certificate, `raised_by_user_id` set to the acting
    `X-User-ID`, and a `ca_due_on` 30 days after the finding's `created_at`."
    PRD: "However it is reached, suspension sets `suspended_on` to the logical clock,
    records the `suspension_reason`, increases `suspension_count` by 1 and sets
    `mark_usage_locked` to true, which is the flag that tells the applicant the mark may no
    longer be displayed."

    Design: Corner/endpoints/high_impact_assessment_rejects_the_change_and_cascades_the_suspension
    """
    context, notification = _a_submitted_supplier_change_on_a_live_certificate(api)

    response = api.assess_change_notification(
        notification["id"],
        make_reviewer_headers("rev-2"),
        decision=Decision.ACCEPT,
        impact_level=ImpactLevel.HIGH,
    )
    assert response.status_code == 200, response.text
    assessed = response.json()["data"]

    assert assessed["id"] == notification["id"]
    assert assessed["status"] == "REJECTED_REQUIRES_RECERT"
    assert assessed["impact_level"] == ImpactLevel.HIGH
    assert assessed["required_retest"] is True
    assert assessed["assessed_by_user_id"] == "rev-2"
    assert assessed["assessed_on"] == ISSUE_DAY

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "SUSPENDED"
    assert certificate["suspension_reason"] == "CHANGE_REQUIRES_RECERT"
    assert certificate["suspension_count"] == 1
    assert certificate["suspended_on"] == ISSUE_DAY
    assert certificate["mark_usage_locked"] is True
    assert read_product(api, context.product_id)["label_status"] == "FROZEN"


def test_the_rejected_change_leaves_a_major_finding_and_an_eighty_seven_posture(api):
    """The cascade's finding is a MAJOR DOCUMENTATION record charged to the certificate,
    and the applicant loses 8 points for it plus 5 for the suspension.

    PRD: "`ca_due_on`, the deadline for the applicant's corrective-action plan, is set to
    the record's `created_at` plus a severity-dependent window: 15 days for a `CRITICAL`
    finding, 30 days for a `MAJOR` one and 90 days for a `MINOR` one, because a critical
    exceedance cannot be left to drift for a quarter."
    PRD: "Start from 100 and subtract three terms: first, the sum of `penalty_points` over
    this applicant's nonconformances whose `status` is `OPEN`, `CA_SUBMITTED`,
    `CA_REJECTED` or `ESCALATED` **and** whose `created_at` falls inside the window running
    from 365 days before the logical clock up to the logical clock; second, 5 points for
    each certificate counted in `suspended_certificate_count`; third, 15 points for each
    complaint counted in `substantiated_complaint_count_rolling`."

    Design: Corner/endpoints/high_impact_assessment_rejects_the_change_and_cascades_the_suspension
    """
    context, notification = _a_submitted_supplier_change_on_a_live_certificate(api)

    validate_success(
        api.assess_change_notification(
            notification["id"],
            make_reviewer_headers("rev-2"),
            decision=Decision.ACCEPT,
            impact_level=ImpactLevel.HIGH,
        )
    )

    rows, meta = validate_paginated(
        api.list_nonconformances(
            make_admin_headers(), certificate_id=context.certificate_id
        )
    )
    assert meta["total_count"] == 1
    finding = rows[0]
    assert finding["source_type"] == "CHANGE_NOTIFICATION"
    assert finding["category"] == "DOCUMENTATION"
    assert finding["severity"] == "MAJOR"
    assert finding["status"] == "OPEN"
    assert finding["penalty_points"] == 8
    assert finding["ca_due_on"] == THIRTY_DAYS_OUT
    assert finding["raised_by_user_id"] == "rev-2"

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["suspended_certificate_count"] == 1
    assert applicant["active_certified_product_count"] == 0
    assert applicant["posture_score_cycle"] == 87
    assert applicant["compliance_posture"] == "GOOD_STANDING"


def test_verification_updates_the_supplier_counter_and_only_one_ingredient_set(api):
    """Two documents from one supplier evidence two different ingredients; verifying one
    lifts the supplier-wide counter to 1 while only that ingredient gains a doc type.

    PRD: "On approval the document moves `PENDING → VERIFIED`, records
    `verified_by_user_id` as the acting `X-User-ID` and `verified_on` as the logical clock,
    and triggers a recompute of the supplier's `verified_document_count` and of the
    evidenced ingredient's `verified_doc_types`."
    PRD: "`verified_doc_types` is derived, not supplied: it is the distinct set of
    `doc_type` values of this ingredient's documents whose `status` is `VERIFIED`, held in
    ascending sorted order so that two ingredients with the same evidence always present
    the same list."

    Design: Corner/endpoints/verified_document_associates_with_both_its_supplier_and_its_ingredient
    """
    set_clock(api, CLOCK_START)
    applicant = create_applicant(api, legal_name="Northgate Bakehouse Ltd")
    supplier = create_supplier(api, name="Prairie Mills", country_code="CA")
    rice = create_ingredient(
        api,
        applicant["id"],
        supplier["id"],
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
    )
    starch = create_ingredient(
        api,
        applicant["id"],
        supplier["id"],
        name="Modified Corn Starch",
        risk_class=RiskClass.GF_PROCESSED,
    )
    documents = {}
    for key, ingredient in (("rice", rice), ("starch", starch)):
        documents[key] = add_supplier_document(
            api,
            applicant["id"],
            supplier["id"],
            ingredient["id"],
            doc_type=DocType.ALLERGEN_STATEMENT,
            issued_on=DOC_ISSUED,
            expires_on=DOC_EXPIRES,
            verify=False,
        )
    assert documents["rice"]["status"] == "PENDING"

    response = api.verify_supplier_document(
        documents["rice"]["id"], make_reviewer_headers("rev-1"), decision=Decision.APPROVE
    )
    assert response.status_code == 200, response.text
    verified = response.json()["data"]

    assert verified["id"] == documents["rice"]["id"]
    assert verified["supplier_id"] == supplier["id"]
    assert verified["ingredient_id"] == rice["id"]
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == "rev-1"
    assert verified["verified_on"] == CLOCK_START

    assert read_supplier(api, supplier["id"])["verified_document_count"] == 1
    assert read_ingredient(api, rice["id"])["verified_doc_types"] == [
        DocType.ALLERGEN_STATEMENT
    ]
    assert read_ingredient(api, starch["id"])["verified_doc_types"] == []
    assert read_supplier_document(api, documents["starch"]["id"])["status"] == "PENDING"

    _rows, all_docs = validate_paginated(
        api.list_supplier_documents(make_admin_headers(), supplier_id=supplier["id"])
    )
    assert all_docs["total_count"] == 2
    _rows, verified_docs = validate_paginated(
        api.list_supplier_documents(
            make_admin_headers(), supplier_id=supplier["id"], status="VERIFIED"
        )
    )
    assert verified_docs["total_count"] == 1
    rows, by_ingredient = validate_paginated(
        api.list_supplier_documents(make_admin_headers(), ingredient_id=rice["id"])
    )
    assert by_ingredient["total_count"] == 1
    assert rows[0]["id"] == documents["rice"]["id"]
    _rows, starch_verified = validate_paginated(
        api.list_supplier_documents(
            make_admin_headers(), ingredient_id=starch["id"], status="VERIFIED"
        )
    )
    assert starch_verified["total_count"] == 0


def test_the_applicant_read_projects_every_posture_field_from_one_finding(api):
    """One open MAJOR finding is enough to move both posture figures to 92 while every
    certificate counter, both complaint counters and the fee balance stay at zero.

    PRD: "All of these applicant figures — the penalty balance, both posture scores, the
    banded posture, the three certificate counters, the two complaint counters and
    `fee_balance_cents` — are readable on the applicant read endpoint and are recomputed
    whenever any contributing nonconformance, certificate or complaint changes, and on every
    surveillance sweep."
    PRD: "The cycle figure, `posture_score_cycle`, applies identical arithmetic over the
    window running from `current_cycle_started_on` up to the logical clock — or from the
    applicant's own `created_at` up to the logical clock when `current_cycle_started_on` is
    null — and takes its complaint term from `substantiated_complaint_count_cycle` instead."

    Design: Corner/endpoints/applicant_read_reports_every_derived_posture_field_from_one_open_finding
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    assert context.applicant["posture_score_cycle"] == 100

    audit = schedule_audit(
        api,
        context.facility_id,
        onsite_start_at=CLOCK_START,
        onsite_end_at="2026-08-01T17:00:00Z",
    )
    start_audit(api, audit["id"])
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        raiser_user_id="rev-1",
        role="reviewer",
        source_type=NcSourceType.AUDIT,
        category=NcCategory.SANITATION,
        severity=NcSeverity.MAJOR,
        description="Swab log gap for the 2026-07 sanitation cycle",
        audit_id=audit["id"],
    )
    assert finding["penalty_points"] == 8
    assert finding["ca_due_on"] == "2026-08-31T00:00:00Z"

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["id"] == context.applicant_id
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["posture_score_rolling_12m"] == 92
    assert applicant["posture_score_cycle"] == 92
    assert applicant["compliance_posture"] == "GOOD_STANDING"
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 0
    assert applicant["revoked_certificate_count"] == 0
    assert applicant["substantiated_complaint_count_rolling"] == 0
    assert applicant["substantiated_complaint_count_cycle"] == 0
    assert applicant["current_cycle_started_on"] is None
    assert applicant["fee_balance_cents"] == 0

    row = read_nonconformance(api, finding["id"])
    assert row["status"] == "OPEN"
    assert row["certificate_id"] is None
    assert row["audit_id"] == audit["id"]
