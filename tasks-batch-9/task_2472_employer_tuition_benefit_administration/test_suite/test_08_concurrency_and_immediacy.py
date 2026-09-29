"""Optimistic-concurrency preconditions and same-request cascade visibility."""

from test_helpers import (
    AcademicStatus,
    AgreementStatus,
    EligibilityStatus,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_STALE_EMPLOYEE_VERSION,
    FundingModel,
    FundingStatus,
    ListingStatus,
    PersistenceTier,
    Scenario,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_employee_share_tracks_money_axis,
    assert_persistence,
    assert_versioned_record,
    build_vantage_base,
    build_vantage_reimbursement_enrolled,
    catalog_listing_payload,
    employee_patch_payload,
    enrollment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_unrelated_employee_patch_makes_the_enrollment_version_stale(api):
    """A weekly_hours patch bumps the version the enrolling client already read.

    PRD §2.7: "Creating an enrollment requires `expected_employee_version` as a
    non-optional field in the request body, carrying the client's last observed
    `version` of the target `Employee`. If it does not equal that employee's current
    `version`, the create is rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_employee_version_rejects_enrollment_create
    """
    s = build_vantage_base(api)
    stale_version = s.employee_version()
    assert stale_version == 1

    patched = validate_success(
        api.patch_employee(
            s.employee_id, employee_patch_payload(weekly_hours=38), s.benefit_admin
        )
    )
    assert patched["version"] == 2
    assert patched["eligibility_status"] == EligibilityStatus.ELIGIBLE

    def enrol(expected_version):
        return api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=expected_version,
                term_code="2026-FA",
                term_start_date="2026-09-01",
                term_end_date="2026-12-15",
                credits=4,
                funding_model=FundingModel.REIMBURSEMENT,
            ),
            s.employee,
        )

    validate_error(enrol(stale_version), ERR_STALE_EMPLOYEE_VERSION, 412)

    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 0
    assert s.read_employee()["cap_reserved_cents"] == 0

    accepted = validate_success(enrol(patched["version"]), 201)
    assert accepted["employer_reserved_cents"] == 80_000


def test_activating_the_agreement_makes_the_listing_version_stale(api):
    """The activation transition itself invalidates the version read before it.

    PRD §2.7: "Curating a catalog listing requires `expected_agreement_version` as
    a non-optional field in the request body, carrying the client's last observed
    `version` of the referenced `PartnerAgreement`. If it does not equal that
    agreement's current `version`, the create is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_rejects_listing_create
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_school()
    s.publish_program()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    pending = s.read_agreement()
    assert pending["status"] == AgreementStatus.PENDING
    assert_versioned_record(pending, expected_version=1)

    activated = s.activate_agreement()
    assert activated["status"] == AgreementStatus.ACTIVE
    assert activated["version"] == 2

    def curate(expected_version):
        return api.create_catalog_listing(
            catalog_listing_payload(
                employer_id=s.employer_id,
                program_id=s.program_id,
                agreement_id=s.agreement_id,
                expected_agreement_version=expected_version,
            ),
            s.benefit_admin,
        )

    validate_error(curate(pending["version"]), ERR_STALE_AGREEMENT_VERSION, 412)

    _, meta = validate_paginated(
        api.list_catalog_listings(s.benefit_admin, {"employer_id": s.employer_id})
    )
    assert meta["total_count"] == 0

    listing = validate_success(curate(activated["version"]), 201)
    assert listing["status"] == ListingStatus.CURATED
    assert listing["negotiated_tuition_per_credit_cents"] == 40_000


def test_the_enrollment_response_already_carries_the_recomputed_cap_ledger(api):
    """No re-read is needed: the 201 and the next employee read agree immediately.

    PRD §2.6: "The ledger is recomputed inside the request that changed anything
    relevant to it — creating an enrollment, withdrawing, paying an invoice,
    deciding a claim, posting an outcome, recording or waiving a repayment,
    patching an employee, activating a policy, or running term-close — so the
    caller reads the settled numbers in that same response or in the very next
    read."

    Design: Corner/consistency_model/enrollment_create_response_already_reflects_the_cap_ledger
    """
    s = build_vantage_base(api)
    before = s.read_employee()
    assert before["cap_reserved_cents"] == 0
    assert before["cap_available_cents"] == 1_000_000

    created = validate_success(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=before["version"],
                term_code="2026-FA",
                term_start_date="2026-09-01",
                term_end_date="2026-12-15",
                credits=4,
                funding_model=FundingModel.REIMBURSEMENT,
            ),
            s.employee,
        ),
        201,
    )
    assert created["gross_tuition_cents"] == 160_000
    assert created["employer_reserved_cents"] == 80_000
    assert created["employee_share_cents"] == 80_000
    assert created["plan_year"] == 2026
    assert created["drop_deadline_date"] == "2026-09-15"
    assert_persistence(created, 30)
    assert created["persistence_tier"] == PersistenceTier.MEDIUM

    after = validate_success(api.get_employee(s.employee_id, s.benefit_admin))
    assert after["cap_reserved_cents"] == 80_000
    assert after["cap_available_cents"] == 920_000
    assert after["version"] == before["version"] + 1
    assert_cap_buckets(after, 80_000, 0, 0, 920_000)
    assert_cap_pool_conserved(after, 1_000_000)


def test_the_agreement_termination_cascade_is_visible_on_the_next_read(api):
    """Agreement, listing, enrollment and cap ledger all settle inside one request.

    PRD §2.8: "Every such cascade completes inside the triggering request — there
    is no deferred worker and no eventual convergence — and every resource the
    cascade touches has its `updated_at` refreshed and its `version` incremented by
    1, exactly as if the client had modified it directly."

    PRD §3.2: "Because those listings are now suspended, every `Enrollment` sitting
    on them whose `academic_status` is `REGISTERED` moves its academic axis to
    `WITHDRAWN` and its funding axis from `RESERVED` or `BILLED` to `RELEASED` —
    enrollments already `IN_PROGRESS` are deliberately left running, on the
    reasoning that a learner mid-term should not be stranded."

    Design: Corner/consistency_model/agreement_termination_cascade_is_visible_immediately
    """
    s = build_vantage_reimbursement_enrolled(api)

    terminated = validate_success(
        api.terminate_partner_agreement(s.agreement_id, s.benefit_admin)
    )
    assert terminated["status"] == AgreementStatus.TERMINATED
    assert terminated["terminated_on"] == "2026-08-01"

    listing = s.read_listing()
    assert listing["status"] == ListingStatus.SUSPENDED

    enrollment = s.read_enrollment()
    assert enrollment["academic_status"] == AcademicStatus.WITHDRAWN
    assert enrollment["funding_status"] == FundingStatus.RELEASED
    assert enrollment["employee_share_cents"] == 160_000
    assert_employee_share_tracks_money_axis(enrollment)

    employee = s.read_employee()
    assert employee["cap_reserved_cents"] == 0
    assert employee["cap_available_cents"] == 1_000_000
    assert_cap_buckets(employee, 0, 0, 0, 1_000_000)
    assert_cap_pool_conserved(employee, 1_000_000)
