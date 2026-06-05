"""Account CRUD & defaults, input validation, FK integrity, CNC, RBAC, auth, OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    make_revenue_officer_headers,
    create_tax_account_payload,
    create_payment_payload,
    create_cnc_payload,
    create_account,
    create_period,
    setup_account_with_recomputed_period,
    propose_agreement,
    get_account_version,
    set_clock,
    build_user_headers,
)

OFFICER = TEST_USERS["revenue_officer_headers"]
REVIEWER = TEST_USERS["case_reviewer_headers"]


def test_create_tax_account_returns_201_with_defaults(api):
    """PRD §3.1: "The account is born in ACTIVE_COLLECTION posture with a zero
    total_balance_cents, a csed_protection_count of zero".
    PRD §2.4: "The version is an integer that begins at its initial value and
    increments by one on every mutation".

    Design: Corner/entities/create_tax_account_returns_201_with_defaults
    """
    res = api.create_tax_account(
        create_tax_account_payload(taxpayer_name="New Co", tin="200000001",
                                   filing_status="INDIVIDUAL",
                                   monthly_disposable_income_cents=100000), OFFICER)
    acct = validate_success(res, 201)
    assert acct["collection_status"] == "ACTIVE_COLLECTION", acct
    assert acct["total_balance_cents"] == 0, acct
    assert acct["version"] == 1, acct


def test_get_tax_account_not_found(api):
    """PRD §2.8: "each referenced TaxAccount ... must exist, and the first identifier
    that does not resolve causes rejection with ERR_RESOURCE_NOT_FOUND."

    Design: Corner/entities/get_tax_account_not_found_returns_404
    """
    res = api.get_tax_account("00000000-0000-4000-8000-000000000000", OFFICER)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


def test_create_tax_account_missing_tin(api):
    """PRD §2.9: "required fields must be present and correctly typed ... A malformed
    body is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_tax_account_missing_required_field_returns_400
    """
    payload = create_tax_account_payload(taxpayer_name="No Tin",
                                         filing_status="INDIVIDUAL",
                                         monthly_disposable_income_cents=100000)
    del payload["tin"]
    res = api.create_tax_account(payload, OFFICER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_tax_account_bad_filing_status_enum(api):
    """PRD §2.9: "enum-valued fields must hold one of their allowed values ... A
    malformed body is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_tax_account_bad_enum_returns_400
    """
    res = api.create_tax_account(
        create_tax_account_payload(taxpayer_name="Bad Enum", tin="200000002",
                                   filing_status="TRUST",
                                   monthly_disposable_income_cents=100000), OFFICER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_tin_rejected(api):
    """PRD §2.8: "Account creation enforces that the taxpayer identification number is
    unique: a second account using a tin already in use is rejected with
    ERR_DUPLICATE_TIN."

    Design: Corner/entities/duplicate_tin_returns_409
    """
    validate_success(api.create_tax_account(
        create_tax_account_payload(taxpayer_name="First", tin="200000010",
                                   filing_status="BUSINESS",
                                   monthly_disposable_income_cents=100000), OFFICER), 201)
    res = api.create_tax_account(
        create_tax_account_payload(taxpayer_name="Dup", tin="200000010",
                                   filing_status="BUSINESS",
                                   monthly_disposable_income_cents=100000), OFFICER)
    validate_error(res, "ERR_DUPLICATE_TIN")


def test_list_tax_accounts_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_tax_accounts_paginated_envelope
    """
    create_account(taxpayer_name="L1", tin="200000020",
                   monthly_disposable_income_cents=0)
    create_account(taxpayer_name="L2", tin="200000021",
                   monthly_disposable_income_cents=0)
    data, meta = validate_paginated(api.list_tax_accounts(REVIEWER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2, meta
    assert meta["has_more"] is True, meta


def test_list_periods_filtered_by_account(api):
    """PRD §4: "GET /collections/tax-periods | List tax periods, filterable by
    account".

    Design: Corner/endpoints/list_periods_filtered_by_account
    """
    acct = create_account(taxpayer_name="ListP Co", tin="200000061",
                          monthly_disposable_income_cents=0)
    create_period(acct["id"], assessed_tax_cents=100000,
                  assessment_date="2023-01-15T00:00:00.000Z", tax_year=2022)
    create_period(acct["id"], assessed_tax_cents=200000,
                  assessment_date="2024-01-15T00:00:00.000Z", tax_year=2023)
    data, meta = validate_paginated(
        api.list_tax_periods(REVIEWER, params={"tax_account_id": acct["id"]}))
    assert meta["total_count"] == 2, meta
    assert all(p["tax_account_id"] == acct["id"] for p in data), data


def test_payment_fk_mismatch_cross_account_period(api):
    """PRD §2.8: "when a payment or an account-event body names both an account and a
    period (or other child), that child must belong to the named account, or the
    request is rejected with ERR_FK_MISMATCH."

    Design: Corner/validations/payment_fk_mismatch_cross_account_period
    """
    acct1 = create_account(taxpayer_name="FkA", tin="200000050",
                           monthly_disposable_income_cents=0)
    acct2 = create_account(taxpayer_name="FkB", tin="200000051",
                           monthly_disposable_income_cents=0)
    period_p = create_period(acct1["id"], assessed_tax_cents=500000,
                             assessment_date="2024-01-15T00:00:00.000Z", tax_year=2023)
    res = api.create_payment(
        create_payment_payload(acct2["id"], 1000, payment_source="MANUAL",
                               tax_period_id=period_p["id"]), OFFICER)
    validate_error(res, "ERR_FK_MISMATCH")


def test_cnc_create_then_revoke_flips_collection_status(api):
    """PRD §3.11: "The determination is created ACTIVE, and the account's
    collection_status recomputes to CNC ... The officer may later revoke it,
    advancing the determination ACTIVE → REVOKED and recomputing the account's
    collection_status to ACTIVE_COLLECTION."

    Design: Corner/state_machines/cnc_create_then_revoke_flips_collection_status
    """
    # Give the account a non-zero balance: per §2.5 the collection_status precedence is
    # RESOLVED-when-balance-zero *before* CNC, so a zero-balance account would derive
    # RESOLVED regardless of an ACTIVE CncDetermination. A recomputed period yields a
    # positive total_balance_cents so CNC is the status §3.11 actually drives to.
    acct, _period = setup_account_with_recomputed_period(
        taxpayer_name="Cnc Co", tin="200000034",
        filing_status="INDIVIDUAL")
    cnc = get_success_data(api.create_cnc(
        create_cnc_payload(acct["id"], hardship_reason="NO_DISPOSABLE_INCOME"), OFFICER))
    a_before = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a_before["collection_status"] == "CNC", a_before

    revoked = validate_success(api.revoke_cnc(cnc["id"], OFFICER), 200)
    assert revoked["status"] == "REVOKED", revoked
    a_after = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a_after["collection_status"] == "ACTIVE_COLLECTION", a_after


def test_case_reviewer_cannot_create_tax_account(api):
    """PRD §2.1: "A CaseReviewer cannot create accounts, periods, or payments, and
    cannot approve installment agreements."

    Design: Corner/rbac/case_reviewer_cannot_create_tax_account
    """
    res = api.create_tax_account(
        create_tax_account_payload(taxpayer_name="Nope", tin="200000070",
                                   filing_status="BUSINESS",
                                   monthly_disposable_income_cents=0), REVIEWER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_revenue_officer_cannot_accept_offer(api):
    """PRD §2.1: "The CaseReviewer is the independent reviewer: they begin evaluation
    of, accept, or reject Offers in Compromise".

    Design: Corner/rbac/revenue_officer_cannot_accept_offer
    """
    from test_helpers import setup_offer_in_evaluating
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000)
    v = get_account_version(acct["id"])
    res = api.accept_offer(offer["id"], {"expected_tax_account_version": v}, OFFICER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request that omits either header, or that names a role the system
    does not recognize, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api.get_tax_account("00000000-0000-4000-8000-000000000000",
                              build_user_headers("ghost-1", "Anonymous"))
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_occ_stale_account_version_on_approve(api):
    """PRD §2.6: "An approve request must carry expected_tax_account_version matching
    the target account's current version. If another writer has advanced the
    account's version since the officer last read it ... the approval is rejected with
    ERR_STALE_ACCOUNT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_approve
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z", mdi_cents=0)
    agr = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6)
    v = get_account_version(acct["id"])
    res = api.approve_agreement(agr["id"], {"expected_tax_account_version": v - 1}, OFFICER)
    validate_error(res, "ERR_STALE_ACCOUNT_VERSION")
