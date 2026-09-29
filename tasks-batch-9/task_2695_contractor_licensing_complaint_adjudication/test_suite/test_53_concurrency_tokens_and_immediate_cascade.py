"""Concurrency tokens, cumulative ceilings and the immediacy of the cascade.

Three writes in this system make the caller present the version of a parent row
it last observed, and that check outranks the state and fiscal tests that would
otherwise answer. The same tokens also have to move: an accepted write advances
the version it guards. These tests present stale tokens on all three endpoints,
watch the token advance on consecutive writes, walk a cumulative hour bank onto
its ceiling, and read back every row one approval touched.
"""

from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    ApplicationDecision,
    ApplicationStatus,
    AssignmentStatus,
    ClaimStatus,
    CompliancePosture,
    LicenseStatus,
    RelationshipType,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


def _list_rows(api, path, headers, params):
    """Reads a collection endpoint and returns its rows plus pagination meta."""
    return validate_paginated(api.get(path, headers=headers, params=params))


def _submitted_application(
    api, *, classification, legal_name, contact_email, full_name
):
    """Files and submits an application whose eligibility gates all pass."""
    licensee = FX.register_licensee(
        api, legal_name=legal_name, contact_email=contact_email
    )
    individual = FX.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        taken_on="2025-03-01",
        law_score=88,
        trade_score=84,
        full_name=full_name,
    )
    application = FX.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=400000,
    )
    validate_success(
        api.submit_application(
            application["id"], make_licensee_headers(licensee["id"])
        )
    )
    return licensee, individual, application


def _approve_into_license(api, application):
    """Approves the application and returns the licence the cascade minted."""
    validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )
    rows, _ = _list_rows(
        api,
        "/licensing/licenses",
        LICENSING_ANALYST_HEADERS,
        {"application_id": application["id"]},
    )
    assert rows, "approving the application must mint a licence"
    return rows[0]


def test_stale_license_version_is_rejected_on_qualifier_designation(api):
    """The token guards a write no state precondition could ever refuse.

    "A `POST /licensing/qualifier-assignments` request must carry
    `expected_license_version`, holding the client's last observed `version` of
    the target `License`. If it does not equal that licence's current
    `version`, the request is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP
    412)."

    Design: Corner/cross-cutting complexity layers/corner_stale_license_version_is_rejected_on_qualifier_designation
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    _, individual, application = _submitted_application(
        api,
        classification=classification,
        legal_name="Stale Token Electric LLC",
        contact_email="stale@x.test",
        full_name="Stella Stale",
    )
    license_row = _approve_into_license(api, application)
    second = FX.register_qualifying_individual(
        api, full_name="Nick Newman", verified_experience_months=72
    )
    license_version = FX.read_license(api, license_row["id"])["version"]

    response = FX.designate_qualifier(
        api,
        license_row["id"],
        second["id"],
        license_version - 1,
        relationship_type=RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
        effective_from="2026-08-15",
    )

    validate_error(response, ApiErrorId.STALE_LICENSE_VERSION, 412)
    stored = FX.read_license(api, license_row["id"])
    assert stored["version"] == license_version
    assert stored["qualifying_individual_id"] == individual["id"]
    newcomer = validate_success(
        api.get_qualifying_individual(second["id"], LICENSING_ANALYST_HEADERS)
    )
    assert newcomer["active_qualification_count"] == 0
    _, meta = _list_rows(
        api,
        "/licensing/qualifier-assignments",
        LICENSING_ANALYST_HEADERS,
        {"license_id": license_row["id"]},
    )
    assert meta["total_count"] == 1

    accepted = FX.designate_qualifier(
        api,
        license_row["id"],
        second["id"],
        license_version,
        relationship_type=RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
        effective_from="2026-08-15",
    )
    validate_success(accepted, 201)
    superseded = FX.read_license(api, license_row["id"])
    assert superseded["qualifying_individual_id"] == second["id"]
    rows, meta = _list_rows(
        api,
        "/licensing/qualifier-assignments",
        LICENSING_ANALYST_HEADERS,
        {"license_id": license_row["id"]},
    )
    assert meta["total_count"] == 2
    incumbent = [
        row for row in rows if row["qualifying_individual_id"] == individual["id"]
    ]
    assert incumbent and incumbent[0]["status"] == AssignmentStatus.WITHDRAWN


def test_stale_license_version_is_rejected_on_recovery_repayment(api):
    """The stale token outranks the fiscal test on a licence that owes nothing.

    "First, the concurrency band sits *above* the state band: a request carrying
    a stale `expected_license_version` against a licence that is also in the
    wrong state reports the stale-version error, not the state error."

    Design: Corner/cross-cutting complexity layers/corner_stale_license_version_is_rejected_on_recovery_repayment
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    licensee, _, application = _submitted_application(
        api,
        classification=classification,
        legal_name="Repay Token Electric LLC",
        contact_email="repay@x.test",
        full_name="Rita Repay",
    )
    license_row = _approve_into_license(api, application)
    licensee_headers = make_licensee_headers(licensee["id"])
    license_version = validate_success(
        api.get_license(license_row["id"], licensee_headers)
    )["version"]

    response = api.credit_recovery_repayment(
        license_row["id"],
        F.repayment_payload(100000, license_version - 1),
        licensee_headers,
    )

    validate_error(response, ApiErrorId.STALE_LICENSE_VERSION, 412)
    stored = FX.read_license(api, license_row["id"])
    assert stored["version"] == license_version
    assert stored["outstanding_recovery_repayment_cents"] == 0
    assert stored["recovery_paid_to_date_cents"] == 0


def test_stale_fund_account_version_is_rejected_on_claim_payment(api):
    """Payment presents the appropriation's token, and a stale one preempts state.

    "A `POST /licensing/recovery-fund-claims/{id}/pay` request must carry
    `expected_fund_account_version`, holding the client's last observed
    `version` of the `RecoveryFundAccount` the claim is charged to. A value that
    does not equal that account's current `version` is rejected with
    `ERR_STALE_FUND_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/corner_stale_fund_account_version_is_rejected_on_claim_payment
    """
    FX.set_clock(api, CLOCK)
    fund_account = FX.open_fund_account(
        api,
        fiscal_year=2027,
        initial_balance_cents=5000000,
        per_claim_cap_cents=1500000,
        per_license_aggregate_cap_cents=3000000,
    )
    classification = FX.create_c20_classification(api)
    _, _, application = _submitted_application(
        api,
        classification=classification,
        legal_name="Fund Token HVAC LLC",
        contact_email="fundtok@x.test",
        full_name="Fay Fundtoken",
    )
    license_row = _approve_into_license(api, application)
    consumer = FX.register_consumer(
        api,
        full_name="Fern Filer",
        contact_email="fern@home.test",
        mailing_state="CA",
    )
    complaint = FX.file_complaint(
        api,
        consumer["id"],
        license_row["id"],
        alleged_loss_cents=900000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Rooftop unit never delivered",
    )
    FX.screen_accepted(api, complaint["id"])
    claim = FX.file_judgment_claim(
        api,
        fund_account["id"],
        complaint["id"],
        consumer["id"],
        900000,
        900000,
        "CV-2026-950",
        "2026-08-25",
    )
    fund_version = FX.read_fund_account(api, fund_account["id"])["version"]

    response = api.pay_claim(
        claim["id"], F.payment_payload(fund_version - 1), FUND_ADJUDICATOR_HEADERS
    )

    validate_error(response, ApiErrorId.STALE_FUND_ACCOUNT_VERSION, 412)
    account = FX.read_fund_account(api, fund_account["id"])
    assert account["balance_cents"] == 5000000
    assert account["version"] == fund_version
    stored = validate_success(api.get_claim(claim["id"], FUND_ADJUDICATOR_HEADERS))
    assert stored["status"] == ClaimStatus.FILED

    with_current_token = api.pay_claim(
        claim["id"], F.payment_payload(fund_version), FUND_ADJUDICATOR_HEADERS
    )
    validate_error(with_current_token, ApiErrorId.CLAIM_STATE_INVALID, 409)


def test_license_version_increments_on_every_write(api):
    """Two accepted writes advance the token by exactly one each.

    "`version` (integer): a counter that increments by one on every mutation of
    the row."

    Design: Corner/cross-cutting complexity layers/corner_license_version_increments_on_every_write
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    licensee, _, application = _submitted_application(
        api,
        classification=classification,
        legal_name="Version Bump Electric LLC",
        contact_email="bump@x.test",
        full_name="Vera Version",
    )
    license_row = _approve_into_license(api, application)
    second = FX.register_qualifying_individual(
        api, full_name="Vince Second", verified_experience_months=72
    )
    version_before = FX.read_license(api, license_row["id"])["version"]

    after_credit = validate_success(
        api.bank_ce_credits(
            license_row["id"],
            F.ce_credit_payload(4, "2026-09-01", "Statewide CE Institute"),
            make_licensee_headers(licensee["id"]),
        )
    )
    assert after_credit["version"] == version_before + 1

    stale = FX.designate_qualifier(
        api,
        license_row["id"],
        second["id"],
        version_before,
        relationship_type=RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
        effective_from="2026-09-02",
    )
    validate_error(stale, ApiErrorId.STALE_LICENSE_VERSION, 412)

    designation = validate_success(
        FX.designate_qualifier(
            api,
            license_row["id"],
            second["id"],
            after_credit["version"],
            relationship_type=RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
            effective_from="2026-09-02",
        ),
        201,
    )
    assert designation["status"] == AssignmentStatus.ACTIVE
    stored = FX.read_license(api, license_row["id"])
    assert stored["version"] == version_before + 2
    assert stored["qualifying_individual_id"] == second["id"]


def test_ce_credit_crossing_the_forty_hour_ceiling_is_rejected_at_the_boundary(api):
    """The bank stops on forty, and the hour that would cross it is refused.

    "A non-positive credit or one that would push the running total past forty
    hours is refused with `ERR_CE_HOURS_CEILING_EXCEEDED`."

    Design: Corner/cross-cutting complexity layers/corner_ce_credit_crossing_the_forty_hour_ceiling_is_rejected_at_the_boundary
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    licensee, _, application = _submitted_application(
        api,
        classification=classification,
        legal_name="Ceiling CE Electric LLC",
        contact_email="ceilce@x.test",
        full_name="Cecil Ceiling",
    )
    license_row = _approve_into_license(api, application)
    licensee_headers = make_licensee_headers(licensee["id"])
    validate_success(
        api.bank_ce_credits(
            license_row["id"],
            F.ce_credit_payload(20, "2026-09-01", "Statewide CE Institute"),
            licensee_headers,
        )
    )
    at_ceiling = validate_success(
        api.bank_ce_credits(
            license_row["id"],
            F.ce_credit_payload(20, "2026-10-01", "Statewide CE Institute"),
            licensee_headers,
        )
    )
    assert at_ceiling["ce_hours_completed"] == 40

    response = api.bank_ce_credits(
        license_row["id"],
        F.ce_credit_payload(1, "2026-11-01", "One More Hour Seminars"),
        licensee_headers,
    )

    validate_error(response, ApiErrorId.CE_HOURS_CEILING_EXCEEDED, 422)
    assert FX.read_license(api, license_row["id"])["ce_hours_completed"] == 40


def test_approval_is_immediately_readable_on_every_touched_row(api):
    """No sweep and no retry: the reads after the approval already see it all.

    "When they do, the cascade is not optional, not asynchronous, and not
    partial: every downstream effect lands inside the same request, and every
    row it touches has its `updated_at` refreshed and its `version` incremented,
    exactly as if it had been written directly."

    Design: Corner/consistency model/corner_approval_is_immediately_readable_on_every_touched_row
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    _, individual, application = _submitted_application(
        api,
        classification=classification,
        legal_name="Immediate Read Electric LLC",
        contact_email="immediate@x.test",
        full_name="Ima Immediate",
    )

    decided = validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )

    assert decided["status"] == ApplicationStatus.APPROVED
    licenses, license_meta = _list_rows(
        api,
        "/licensing/licenses",
        LICENSING_ANALYST_HEADERS,
        {"application_id": application["id"]},
    )
    assert license_meta["total_count"] == 1
    license_row = FX.read_license(api, licenses[0]["id"])
    assert license_row["status"] == LicenseStatus.ACTIVE
    assert license_row["issued_on"] == "2026-08-01"
    assert license_row["expires_on"] == "2028-08-01"
    assert license_row["compliance_posture"] == CompliancePosture.NON_COMPLIANT
    assert license_row["qualifying_individual_id"] == individual["id"]

    assignments, assignment_meta = _list_rows(
        api,
        "/licensing/qualifier-assignments",
        LICENSING_ANALYST_HEADERS,
        {"license_id": license_row["id"]},
    )
    assert assignment_meta["total_count"] == 1
    designation = validate_success(
        api.get_qualifier_assignment(
            assignments[0]["id"], LICENSING_ANALYST_HEADERS
        )
    )
    assert (
        designation["relationship_type"]
        == RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE
    )
    assert designation["status"] == AssignmentStatus.ACTIVE
    assert designation["effective_from"] == "2026-08-01"
    qualifier = validate_success(
        api.get_qualifying_individual(individual["id"], LICENSING_ANALYST_HEADERS)
    )
    assert qualifier["active_qualification_count"] == 1
