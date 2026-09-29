"""Conditional inputs, the arrangement terms and the good-faith standard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_sample_unit_payload,
    create_taxpayer_payload,
    create_use_tax_purchase_payload,
    file_certificate,
    get_success_data,
    read_arrangement,
    read_assessment,
    read_audit,
    read_certificate,
    register_taxpayer,
    request_installment_plan,
    request_offer_in_compromise,
    setup_agreed_methodology,
    setup_issued_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["selection_analyst_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]

SMALL_BALANCE_CENTS = 4_762


def _small_balance_notice():
    """An issued notice whose penalty was waived, leaving a balance of 4,762 cents."""
    ctx = setup_issued_assessment(tax_deficiency_cents=SMALL_BALANCE_CENTS)
    assert ctx["assessment"]["penalty_waived_small_balance"] is True
    assert ctx["assessment"]["balance_due_cents"] == SMALL_BALANCE_CENTS
    return ctx


def _approve(arrangement_id):
    return api_client.approve_payment_arrangement(arrangement_id, COLLECTIONS)


def test_an_offer_in_compromise_must_clear_the_hardship_gate_and_the_statutory_floor():
    """Two independent gates, and the floor is decided on cross-multiplied integers.

    PRD 3.9: "An `OFFER_IN_COMPROMISE` must first have `hardship_documented` true,
    without which it is refused with `ERR_HARDSHIP_NOT_DOCUMENTED`, and must then reach
    the statutory minimum of 2,000 basis points — twenty percent — of the balance. That
    minimum is tested on cross-multiplied integers with no rounding and no division
    anywhere: the offer is acceptable when `offer_amount_cents` multiplied by 10,000 is
    greater than or equal to 2,000 multiplied by `balance_due_cents`. An offer below
    that line is refused with `ERR_OFFER_BELOW_MINIMUM`."
    PRD 3.9: "Approval sets `approved_at`, moves the arrangement from `REQUESTED` to
    `APPROVED`, and moves the assessment's `collection_status` to `ARRANGED` — from
    `DUE` or from `REFERRED` alike — while leaving the notice axis exactly where it was."

    Design: Corner/validations/offer_in_compromise_gates_on_both_the_minimum_and_the_hardship
    """
    ctx = _small_balance_notice()
    assessment_id = ctx["assessment"]["id"]

    # 952 * 10,000 = 9,520,000 falls short of 2,000 * 4,762 = 9,524,000.
    too_low = request_offer_in_compromise(assessment_id, 952, hardship_documented=True)
    assert too_low["scheduled_total_cents"] == 952
    validate_error(
        _approve(too_low["id"]), ApiErrorId.ERR_OFFER_BELOW_MINIMUM.value, 422
    )
    assert read_arrangement(too_low["id"])["status"] == "REQUESTED"
    assert read_arrangement(too_low["id"])["approved_at"] is None

    undocumented = request_offer_in_compromise(
        assessment_id, 953, hardship_documented=False
    )
    validate_error(
        _approve(undocumented["id"]), ApiErrorId.ERR_HARDSHIP_NOT_DOCUMENTED.value, 422
    )
    assert read_arrangement(undocumented["id"])["status"] == "REQUESTED"

    # 953 * 10,000 = 9,530,000 clears the same line.
    acceptable = request_offer_in_compromise(assessment_id, 953, hardship_documented=True)
    approved = validate_success(_approve(acceptable["id"]), 200)
    assert approved["status"] == "APPROVED"
    assert approved["scheduled_total_cents"] == 953
    assert approved["approved_at"] is not None

    assessment = read_assessment(assessment_id)
    assert assessment["collection_status"] == "ARRANGED"
    assert assessment["status"] == "ISSUED"
    assert assessment["balance_due_cents"] == SMALL_BALANCE_CENTS


def test_an_installment_plan_must_schedule_the_whole_balance():
    """Two cents short is a shortfall; exact coverage is enough.

    PRD 3.9: "An `INSTALLMENT_PLAN` must cover the whole liability: its
    `scheduled_total_cents` must be greater than or equal to the assessment's
    `balance_due_cents`, and a plan that would leave a shortfall is refused with
    `ERR_PLAN_UNDERFUNDED`."
    PRD 3.9: "The request computes `scheduled_total_cents` — `monthly_installment_cents`
    multiplied by `term_months` for an installment plan, and `offer_amount_cents` for an
    offer in compromise — and lands at `status` `REQUESTED` with `payments_made_count` 0,
    `amount_paid_cents` 0 and `approved_at` null."

    Design: Corner/validations/installment_plan_must_cover_the_whole_balance
    """
    ctx = _small_balance_notice()
    assessment_id = ctx["assessment"]["id"]

    short = request_installment_plan(assessment_id, 2_380, 2)
    assert short["scheduled_total_cents"] == 4_760
    assert short["payments_made_count"] == 0
    assert short["amount_paid_cents"] == 0
    validate_error(_approve(short["id"]), ApiErrorId.ERR_PLAN_UNDERFUNDED.value, 422)
    assert read_arrangement(short["id"])["status"] == "REQUESTED"

    exact = request_installment_plan(assessment_id, 2_381, 2)
    assert exact["scheduled_total_cents"] == SMALL_BALANCE_CENTS
    approved = validate_success(_approve(exact["id"]), 200)
    assert approved["status"] == "APPROVED"

    assert read_assessment(assessment_id)["collection_status"] == "ARRANGED"


def _units_of(agreement_id):
    return get_success_data(api_client.list_agreement_sample_units(agreement_id, AUDITOR))


def test_the_declared_error_amount_is_required_only_by_the_classes_that_use_it():
    """An omitted optional input becomes a money error in exactly two classes.

    PRD 3.4: "`UNREPORTED_TAXABLE_SALE` and `RATE_ERROR` both require
    `declared_error_amount_cents`, the auditor-stated error in cents; omitting it in
    either class is refused with `ERR_ERROR_AMOUNT_REQUIRED`, and supplying it in any
    other class is refused as a malformed request."
    PRD 3.4: "From these the system computes `error_amount_cents`, which is 0 for both
    `NO_ERROR` and `PENDING`, equals `declared_error_amount_cents` for
    `UNREPORTED_TAXABLE_SALE` and `RATE_ERROR`"

    Design: Corner/validations/error_class_requiring_a_declared_amount_is_enforced_conditionally
    """
    ctx = setup_agreed_methodology()
    agreement_id = ctx["agreement"]["id"]

    response = api_client.create_sample_unit(
        create_sample_unit_payload(
            agreement_id,
            0,
            "2026-03-02",
            400_000,
            invoice_reference="RT-201",
            error_class="UNREPORTED_TAXABLE_SALE",
        ),
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_ERROR_AMOUNT_REQUIRED.value, 422)
    assert [unit["invoice_reference"] for unit in _units_of(agreement_id)] == []

    undetermined = validate_success(
        api_client.create_sample_unit(
            create_sample_unit_payload(
                agreement_id,
                0,
                "2026-03-03",
                400_000,
                invoice_reference="RT-202",
                error_class="NO_ERROR",
            ),
            AUDITOR,
        ),
        201,
    )
    assert undetermined["error_amount_cents"] == 0

    rate_error = validate_success(
        api_client.create_sample_unit(
            create_sample_unit_payload(
                agreement_id,
                0,
                "2026-03-04",
                400_000,
                invoice_reference="RT-203",
                error_class="RATE_ERROR",
                declared_error_amount_cents=12_500,
            ),
            AUDITOR,
        ),
        201,
    )
    assert rate_error["error_amount_cents"] == 12_500
    assert read_audit(ctx["audit"]["id"])["projection_status"] == "STALE"


def test_the_entry_value_is_demanded_only_when_the_stepdown_branch_is_taken():
    """Eight months out of state needs the entry value; five months does not.

    PRD 3.5: "A `CAPITAL_ASSET` purchase first chooses its pre-apportionment base:
    when `first_use_outside_state` is true **and** `months_used_outside_state` is at
    least 6, the asset entered the state already used and the base steps down to
    `fair_market_value_at_entry_cents`, which is mandatory in exactly that branch and
    whose omission is refused with `ERR_CAPITAL_ASSET_FMV_REQUIRED`; otherwise the base
    is `purchase_price_cents`."
    PRD 3.5: "The audit's `use_tax_deficiency_cents` is the sum of `use_tax_due_cents`
    over every untaxed purchase of that audit, including rows whose liability computes
    to 0."

    Design: Corner/validations/capital_asset_fmv_is_required_only_inside_the_stepdown_branch
    """
    ctx = setup_agreed_methodology()
    audit_id = ctx["audit"]["id"]

    def _capital_asset(invoice_date, months):
        return create_use_tax_purchase_payload(
            audit_id,
            invoice_date,
            10_000_000,
            asset_class="CAPITAL_ASSET",
            in_state_usage_pct_bp=7_500,
            first_use_outside_state=True,
            months_used_outside_state=months,
            vendor_name="Cascade Machine Works",
        )

    validate_error(
        api_client.create_use_tax_purchase(_capital_asset("2026-02-10", 8), AUDITOR),
        ApiErrorId.ERR_CAPITAL_ASSET_FMV_REQUIRED.value,
        422,
    )

    inside_the_state = validate_success(
        api_client.create_use_tax_purchase(_capital_asset("2026-02-11", 5), AUDITOR), 201
    )
    # The base stays at the purchase price: 10,000,000 * 7,500 / 10,000.
    assert inside_the_state["taxable_basis_cents"] == 7_500_000
    assert inside_the_state["gross_use_tax_cents"] == 468_750
    assert inside_the_state["credit_applied_cents"] == 0
    assert inside_the_state["use_tax_due_cents"] == 468_750

    # The refused row contributed nothing.
    assert read_audit(audit_id)["use_tax_deficiency_cents"] == 468_750


def test_a_second_registration_on_the_same_permit_number_is_a_conflict():
    """The permit number is unique, and the clash is a business conflict, not a 400.

    PRD 3.1: "A `permit_number` is a state sales-tax permit number written as the
    literal prefix `STP-` followed by exactly six digits, and it is unique across all
    permit holders: a second registration reusing one already on file is rejected with
    `ERR_DUPLICATE_PERMIT_NUMBER`."
    PRD 2.8: "14. **Quotas, rounds, empty sets, sequence and uniqueness — checked
    last.** `ERR_NO_ELIGIBLE_CANDIDATES` (422), `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`
    (422), `ERR_SAMPLE_SET_EMPTY` (422), `ERR_SAMPLE_SIZE_NOT_MET` (422),
    `ERR_ASSESSMENT_ALREADY_OPEN` (409), `ERR_FORUM_SEQUENCE_INVALID` (409),
    `ERR_ADJUSTMENT_KIND_SYSTEM_ONLY` (422), `ERR_DUPLICATE_PERMIT_NUMBER` (409) and
    `ERR_ASSESSMENT_NOT_FINALIZABLE` (409)."

    Design: Corner/validations/duplicate_permit_number_is_refused
    """
    taken = "STP-500001"
    first = register_taxpayer(legal_name="Ridgeline Tools LLC", permit_number=taken)

    validate_error(
        api_client.create_taxpayer(
            create_taxpayer_payload(legal_name="Copycat Tools LLC", permit_number=taken),
            ANALYST,
        ),
        ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER.value,
        409,
    )

    rows, meta = validate_paginated(api_client.list_taxpayers(ANALYST))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["legal_name"] == "Ridgeline Tools LLC"


def test_a_certificate_failing_one_diligence_condition_cannot_be_validated():
    """The favourable determination is barred, and the rejection prices the sale.

    PRD 3.5: "The computed flag `good_faith_accepted` is true only when all four
    diligence conditions hold together: the certificate was received before the sale,
    the form is complete, a `purchaser_permit_number` is present, and the claimed
    exemption matches the purchaser's business. Any single failure makes it false."
    PRD 3.5: "A `VALIDATED` determination is available from `ON_FILE` and from `CURED`,
    and it requires `good_faith_accepted` to be true; asking for it on a certificate
    that fails the standard is refused with `ERR_GOOD_FAITH_STANDARD_NOT_MET`."
    PRD 3.5: "First, the certificate records the `review_note`, takes status
    `REJECTED`, and computes `missing_certificate_tax_cents` as
    `covered_sale_amount_cents` multiplied by 625 basis points, divided by 10,000 and
    rounded half up."

    Design: Corner/validations/validated_determination_requires_the_good_faith_standard
    """
    ctx = setup_agreed_methodology()
    certificate = file_certificate(
        ctx["audit"]["id"],
        purchaser_name="Lakeside Grange",
        claimed_exemption_type="MANUFACTURING",
        covered_sale_amount_cents=1_600_000,
        received_before_sale=True,
        form_complete=True,
        claimed_exemption_matches_purchaser_business=False,
    )
    assert certificate["good_faith_accepted"] is False
    assert certificate["status"] == "ON_FILE"

    validate_error(
        api_client.review_exemption_certificate(
            certificate["id"],
            {"determination": "VALIDATED", "review_note": "Long-standing customer"},
            AUDITOR,
        ),
        ApiErrorId.ERR_GOOD_FAITH_STANDARD_NOT_MET.value,
        422,
    )
    unchanged = read_certificate(certificate["id"])
    assert unchanged["status"] == "ON_FILE"
    assert unchanged["missing_certificate_tax_cents"] == 0

    rejected = validate_success(
        api_client.review_exemption_certificate(
            certificate["id"],
            {
                "determination": "REJECTED",
                "review_note": "Exemption does not match the purchaser's business",
            },
            AUDITOR,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["missing_certificate_tax_cents"] == 100_000

    audit = read_audit(ctx["audit"]["id"])
    assert audit["certificate_deficiency_cents"] == 100_000
    assert audit["projection_status"] == "STALE"
