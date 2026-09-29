"""Award arithmetic, the conserved cap pool and the persistence risk score."""

from test_helpers import (
    AcademicStatus,
    ClaimDecision,
    CompletionStatus,
    ERR_ANNUAL_CAP_EXCEEDED,
    FundingModel,
    FundingStatus,
    InvoiceStatus,
    JobFamily,
    Modality,
    PersistenceTier,
    RiskFlag,
    Scenario,
    TaxEntryType,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_employee_share_tracks_money_axis,
    assert_enrollment_axes,
    assert_ledger_row,
    assert_ledger_year_identity,
    assert_persistence,
    build_vantage_direct_bill_billed,
    build_vantage_reimbursement_enrolled,
    build_vantage_reimbursement_in_progress,
    claim_decision_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_persistence_score_combines_every_component_and_caps_the_flags(api):
    """Three sessions drive the score 30 → 15 → 10 → 15, the flag cap biting last.

    PRD §3.8: "A flag penalty is added at 5 points per observed risk flag, counting
    the total number of `risk_flags` entries across the three most recent sessions
    of that enrollment ordered by `session_date` descending with `created_at`
    ascending as the tie-break, and capping the counted flags at 4 — so the flag
    penalty never exceeds 20 points."

    Design: Corner/calculations/persistence_risk_score_components_combine_with_flag_cap
    """
    s = build_vantage_reimbursement_in_progress(api)
    confirmed = s.read_enrollment()
    assert_persistence(confirmed, 30)
    assert confirmed["persistence_tier"] == PersistenceTier.MEDIUM
    assert confirmed["last_session_date"] is None

    first = s.log_session(
        "2026-07-20",
        Modality.VIDEO,
        [RiskFlag.ACADEMIC_STRUGGLE, RiskFlag.FINANCIAL_STRESS],
    )
    assert first["persistence_risk_score_after"] == 15

    second = s.log_session("2026-07-26", Modality.PHONE, [])
    assert second["persistence_risk_score_after"] == 10

    third = s.log_session(
        "2026-08-01",
        Modality.VIDEO,
        [
            RiskFlag.ACADEMIC_STRUGGLE,
            RiskFlag.FINANCIAL_STRESS,
            RiskFlag.SCHEDULE_CONFLICT,
        ],
    )
    assert third["persistence_risk_score_after"] == 15

    enrollment = s.read_enrollment()
    assert_persistence(enrollment, 15)
    assert enrollment["persistence_tier"] == PersistenceTier.LOW
    assert enrollment["last_session_date"] == "2026-08-01"

    _, meta = validate_paginated(
        api.list_coaching_sessions(s.enrollment_id, s.coach)
    )
    assert meta["total_count"] == 3
    assert s.read_employee()["coaching_hold"] is False


def test_reimbursement_settlement_scales_by_the_earned_credit_ratio(api):
    """Three of four credits earned settles 72,000, not 96,000 and not 90,000.

    PRD §3.6: "The earned-credit base is `gross_tuition_cents` multiplied by the
    ratio of the latest outcome's `credits_earned` to the enrollment's `credits`,
    rounded half up to a whole cent at that point."

    Design: Corner/calculations/reimbursement_final_scales_by_earned_credit_ratio
    """
    s = build_vantage_reimbursement_in_progress(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.PASSED, 3, 3.60)
    s.file_claim(160_000, "CVC-2026FA-RDELGADO-PARTIAL")

    claim = validate_success(
        api.decide_reimbursement_claim(
            s.claim_id,
            claim_decision_payload(ClaimDecision.APPROVE),
            s.benefit_admin,
        )
    )
    assert claim["approved_amount_cents"] == 72_000
    assert claim["platform_admin_fee_cents"] == 3_600

    enrollment = s.read_enrollment()
    assert_enrollment_axes(enrollment, AcademicStatus.PASSED, FundingStatus.SETTLED)
    assert enrollment["credits_earned"] == 3
    assert enrollment["employer_settled_cents"] == 72_000
    assert enrollment["employer_disbursed_cents"] == 72_000
    assert enrollment["employee_share_cents"] == 88_000
    assert_employee_share_tracks_money_axis(enrollment)

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 72_000, 0, 928_000)
    assert_cap_pool_conserved(employee, 1_000_000)

    entries = s.ledger_entries()
    assert len(entries) == 1
    assert_ledger_row(entries[0], TaxEntryType.BENEFIT, 72_000, 72_000, 0, 2026)


def test_partial_coverage_takes_the_min_of_the_reserve_and_the_headroom(api):
    """A 40,000 entitlement against 20,000 of headroom reserves only 20,000.

    PRD §3.4: "`employer_reserved_cents` is then the smaller of that uncapped
    amount and the employee's `cap_available_cents`, and `employee_share_cents` is
    `gross_tuition_cents` minus `employer_reserved_cents`."

    Design: Corner/calculations/annual_cap_partial_coverage_takes_min_of_reserve_and_headroom
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Cedar Ridge Dairy",
        benefit_admin_contact_email="benefits@cedarridge-dairy.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=0,
        min_weekly_hours=0,
        eligible_job_families=[JobFamily.OPERATIONS],
        annual_cap_cents=100_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
        max_concurrent_credits=12,
        drop_window_days=14,
        service_commitment_months=12,
    )
    s.activate_policy()
    s.register_employee()
    s.register_school()
    s.publish_program()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()

    first = s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=4,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    assert first["gross_tuition_cents"] == 160_000
    assert first["employer_reserved_cents"] == 80_000
    assert first["employee_share_cents"] == 80_000
    assert s.read_employee()["cap_available_cents"] == 20_000

    second = s.enroll(
        primary=False,
        term_code="2026-WI",
        term_start_date="2026-12-20",
        term_end_date="2027-03-20",
        credits=2,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    assert second["gross_tuition_cents"] == 80_000
    assert second["employer_reserved_cents"] == 20_000
    assert second["employee_share_cents"] == 60_000
    assert second["plan_year"] == 2026

    employee = s.read_employee()
    assert_cap_buckets(employee, 100_000, 0, 0, 0)
    assert_cap_pool_conserved(employee, 100_000)

    validate_error(
        api.create_enrollment(
            {
                "employee_id": s.employee_id,
                "catalog_listing_id": s.listing_id,
                "term_code": "2026-SU",
                "term_start_date": "2026-06-01",
                "term_end_date": "2026-08-15",
                "credits": 1,
                "funding_model": FundingModel.REIMBURSEMENT,
                "expected_employee_version": s.employee_version(),
            },
            s.employee,
        ),
        ERR_ANNUAL_CAP_EXCEEDED,
    )


def test_a_released_reserve_stays_on_the_row_but_leaves_the_cap_ledger(api):
    """The withdrawn row keeps its 80,000 while the employee's buckets forget it.

    PRD §3.4: "When `funding_status` is `RELEASED` the employer contributes nothing
    and the field is the full `gross_tuition_cents`; the `employer_reserved_cents`
    figure is retained on the record for audit but excluded from every cap bucket."

    Design: Corner/calculations/cap_ledger_excludes_released_enrollment_reserves
    """
    s = build_vantage_reimbursement_enrolled(api)
    released = s.withdraw()
    assert_enrollment_axes(
        released, AcademicStatus.WITHDRAWN, FundingStatus.RELEASED
    )
    assert released["employer_reserved_cents"] == 80_000
    assert released["employee_share_cents"] == 160_000

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 0, 0, 1_000_000)
    assert_cap_pool_conserved(employee, 1_000_000)

    second = s.enroll(
        primary=False,
        term_code="2026-WI",
        term_start_date="2026-12-20",
        term_end_date="2027-03-20",
        credits=2,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    assert second["employer_reserved_cents"] == 40_000

    employee = s.read_employee()
    assert_cap_buckets(employee, 40_000, 0, 0, 960_000)
    assert_cap_pool_conserved(employee, 1_000_000)

    _, meta = validate_paginated(
        api.list_enrollments(
            s.benefit_admin,
            {"employee_id": s.employee_id, "funding_status": FundingStatus.RELEASED},
        )
    )
    assert meta["total_count"] == 1


def test_the_direct_bill_variant_settles_with_no_academic_input(api):
    """Disbursement settles the full 160,000 while no outcome row exists at all.

    PRD §3.5: "The enrollment's money axis moves `BILLED → SETTLED`, and both
    `employer_settled_cents` and `employer_disbursed_cents` are set to the invoice's
    `amount_cents`, which is itself the reservation the employer committed at
    confirmation time."

    Design: Corner/calculations/direct_bill_variant_settles_before_any_outcome_exists
    """
    s = build_vantage_direct_bill_billed(api)
    invoice = s.first_invoice()
    assert invoice["amount_cents"] == 160_000
    s.approve_invoice()

    paid = validate_success(api.pay_invoice(s.invoice_id, s.platform_admin))
    assert paid["status"] == InvoiceStatus.PAID
    assert paid["paid_on"] == "2026-08-01"

    enrollment = s.read_enrollment()
    assert_enrollment_axes(
        enrollment, AcademicStatus.IN_PROGRESS, FundingStatus.SETTLED
    )
    assert enrollment["employer_settled_cents"] == 160_000
    assert enrollment["employer_disbursed_cents"] == 160_000
    assert enrollment["employee_share_cents"] == 0
    assert_employee_share_tracks_money_axis(enrollment)

    _, meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert meta["total_count"] == 0

    entries = s.ledger_entries()
    assert len(entries) == 1
    assert_ledger_row(entries[0], TaxEntryType.BENEFIT, 160_000, 160_000, 0, 2026)

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 160_000, 0, 840_000)
    assert_cap_pool_conserved(employee, 1_000_000)
    assert_ledger_year_identity(entries, employee)

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 160_000
    assert employer["total_admin_fee_cents"] == 0
