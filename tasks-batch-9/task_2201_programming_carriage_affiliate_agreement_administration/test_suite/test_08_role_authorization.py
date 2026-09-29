"""Role authorisation across the carriage administration API.

Every endpoint declares the roles it admits (PRD §4); a well-formed caller whose
role is not among them is refused `ERR_FORBIDDEN_ROLE`, a `DistributorLiaison`
reaching another operator's records is refused `ERR_DISTRIBUTOR_SCOPE_VIOLATION`,
and no refusal leaves a trace on the records it addressed.

Every test builds its own state from an empty database through PRD-declared
endpoints only.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agreement_version,
    clock_payload,
    create_agreement_payload,
    create_audit_engagement_payload,
    create_audit_finding_payload,
    create_blackout_rule_payload,
    create_content_title_payload,
    create_distributor_payload,
    create_invoice_payload,
    create_rate_card_entry_payload,
    create_renewal_analysis_payload,
    create_rights_window_payload,
    create_subscriber_report_payload,
    distributor_version,
    draft_agreement,
    draft_invoice,
    fetch_agreement,
    fetch_distributor,
    fetch_report,
    file_and_accept_report,
    file_report,
    headers_for_role,
    issue_findings,
    make_distributor_liaison_headers,
    plan_window,
    read_clock,
    register_cleared_title,
    register_distributor,
    schedule_blackout,
    setup_accepted_report,
    setup_engagement_in_fieldwork,
    setup_executed_agreement,
    setup_license_fee_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared operator and contract shapes (all values PRD-legal inputs)
# ---------------------------------------------------------------------------
MERIDIAN = {
    "legal_name": "Meridian Broadband",
    "distributor_type": "CABLE_MSO",
    "rate_card_class": "CLASS_A",
    "total_subscribers": 1_500_000,
}
HARBOR = {
    "legal_name": "Harbor Satellite",
    "distributor_type": "DBS",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 800_000,
}
CLIFFSIDE = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
    "credit_limit_cents": 150_000_000,
}
TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}

ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
SALES = TEST_USERS["affiliate_sales_exec_headers"]
ADMIN = TEST_USERS["network_admin_headers"]
AUDITOR = TEST_USERS["audit_manager_headers"]
RIGHTS = TEST_USERS["rights_administrator_headers"]

NON_SALES_ROLES = [
    "NetworkAdmin",
    "RevenueAccountant",
    "AuditManager",
    "RightsAdministrator",
    "DistributorLiaison",
]
NON_ACCOUNTANT_ROLES = [
    "AffiliateSalesExec",
    "AuditManager",
    "RightsAdministrator",
    "NetworkAdmin",
    "DistributorLiaison",
]
NON_RIGHTS_ROLES = [
    "NetworkAdmin",
    "AffiliateSalesExec",
    "RevenueAccountant",
    "AuditManager",
    "DistributorLiaison",
]


def _headers_bound_to(role: str, distributor: dict) -> dict:
    """Headers for `role`; a liaison is bound to the operator that owns the
    resource under test, so only endpoint role membership can fail."""
    if role == "DistributorLiaison":
        return make_distributor_liaison_headers(distributor["id"])
    return headers_for_role(role)


# ===========================================================================
# Negotiating and advancing an agreement
# ===========================================================================
@pytest.mark.parametrize("role", NON_SALES_ROLES)
def test_only_affiliate_sales_exec_may_draft_amend_or_advance_an_agreement(api, role):
    """PRD §2.1: "If both headers are well-formed but the named role is not among
    the roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "An `AffiliateSalesExec` negotiates: drafting and amending
    agreements, driving the lifecycle and renewal dimensions, attaching and
    resetting most-favored-nations clauses, opening marketing commitment lines and
    recording proof of performance against them, and running renewal leverage
    models."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."
    PRD §3.2: "A fresh draft is stamped `lifecycle_status` `DRAFT`,
    `renewal_status` `NOT_DUE`, `negotiation_round` 0,
    `penetration_compliance_status` `UNKNOWN`, `penetration_breach_count` 0,
    `consecutive_compliant_periods` 0, `recognized_revenue_cents` 0 and `version`
    1, and both rate fields are stamped immediately from the terms as described in
    §3.3."

    Design: Corner/rbac/other_roles_cannot_negotiate_or_advance_an_agreement
    """
    distributor = register_distributor(**MERIDIAN)
    agreement = draft_agreement(distributor["id"], **TERMS)
    headers = _headers_bound_to(role, distributor)

    attempts = {
        "POST /carriage/agreements": lambda: api.create_agreement(
            create_agreement_payload(distributor["id"], **TERMS), headers
        ),
        "POST /carriage/agreements/{agreementId}/lifecycle": lambda: api.agreement_lifecycle(
            agreement["id"], {"action": "SUBMIT_FOR_NEGOTIATION"}, headers
        ),
        "PATCH /carriage/agreements/{agreementId}": lambda: api.patch_agreement(
            agreement["id"], {"base_license_fee_cents_per_sub": 41.0000}, headers
        ),
        "POST /carriage/agreements/{agreementId}/renewal": lambda: api.agreement_renewal(
            agreement["id"], {"action": "START_ANALYSIS"}, headers
        ),
        "POST /carriage/renewal-analyses": lambda: api.create_renewal_analysis(
            create_renewal_analysis_payload(agreement["id"]), headers
        ),
    }

    for label, call in attempts.items():
        validate_error(call(), ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    stored = fetch_agreement(agreement["id"])
    assert stored["lifecycle_status"] == "DRAFT", (
        f"{role} refusals must leave lifecycle_status DRAFT, got {stored['lifecycle_status']}"
    )
    assert stored["renewal_status"] == "NOT_DUE", (
        f"{role} refusals must leave renewal_status NOT_DUE, got {stored['renewal_status']}"
    )
    assert stored["version"] == 1, (
        f"a refused write mutates nothing, so version must stay 1, got {stored['version']}"
    )

    _rows, meta = validate_paginated(
        api.list_agreements(SALES, params={"distributor_id": distributor["id"], "limit": 10})
    )
    assert meta["total_count"] == 1, (
        "only the AffiliateSalesExec agreement may exist after the refusals, "
        f"got total_count {meta['total_count']}"
    )


# ===========================================================================
# Adjudicating reports and moving money
# ===========================================================================
@pytest.mark.parametrize(
    "endpoint,role",
    [("review", "AffiliateSalesExec"), ("review", "AuditManager"), ("create_invoice", "AuditManager")]
    + [("invoice_lifecycle", role) for role in NON_ACCOUNTANT_ROLES],
)
def test_only_revenue_accountant_may_review_reports_or_move_invoices(api, endpoint, role):
    """PRD §2.1: "If both headers are well-formed but the named role is not among
    the roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `RevenueAccountant` owns revenue recognition and receivables:
    reviewing subscriber reports, drafting invoices and driving them through
    issuance, payment, write-off and void, and placing or releasing credit holds."
    PRD §2.1: "This role never accepts a subscriber report and never moves money."
    PRD §2.1: "It is deliberately barred from raising the recovery invoice."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/rbac/other_roles_cannot_adjudicate_reports_or_move_money
    """
    if endpoint == "review":
        distributor, agreement = setup_executed_agreement(CLIFFSIDE, TERMS)
        report = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2026-06",
            reported_subscribers=130_000,
            reported_tier="BASIC",
        )
        headers = _headers_bound_to(role, distributor)
        validate_error(
            api.review_subscriber_report(report["id"], {"action": "ACCEPT"}, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        )
        assert fetch_report(report["id"])["status"] == "SUBMITTED", (
            f"a refused review by {role} must leave the report SUBMITTED"
        )
        return

    if endpoint == "create_invoice":
        distributor, agreement, report = setup_accepted_report(
            CLIFFSIDE,
            TERMS,
            {"period_month": "2026-06", "reported_subscribers": 130_000, "reported_tier": "BASIC"},
        )
        headers = _headers_bound_to(role, distributor)
        payload = create_invoice_payload(
            distributor["id"],
            agreement["id"],
            "2026-06",
            distributor_version(distributor["id"]),
        )
        validate_error(api.create_invoice(payload, headers), ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        _rows, meta = validate_paginated(
            api.list_invoices(ACCOUNTANT, params={"agreement_id": agreement["id"], "limit": 10})
        )
        assert meta["total_count"] == 0, (
            f"a refused draft by {role} must persist no invoice, got total_count {meta['total_count']}"
        )
        return

    distributor, agreement, _report, invoice = setup_license_fee_invoice(
        CLIFFSIDE,
        TERMS,
        {"period_month": "2026-06", "reported_subscribers": 130_000, "reported_tier": "BASIC"},
    )
    headers = _headers_bound_to(role, distributor)
    validate_error(
        api.invoice_lifecycle(invoice["id"], {"action": "ISSUE"}, headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    stored = validate_success(api.get_invoice(invoice["id"], ACCOUNTANT))
    assert stored["status"] == "DRAFT", (
        f"a refused ISSUE by {role} must leave the invoice DRAFT, got {stored['status']}"
    )
    assert stored["issued_at"] is None, "a refused ISSUE must not stamp issued_at"


def test_revenue_accountant_alone_can_accept_the_filed_report(api):
    """PRD §3.4: "A `RevenueAccountant` reviews a filed report with one of four
    actions — accept, dispute, request restatement, or accept adjustment —
    optionally accompanied by a `note`."
    PRD §3.4: "A successful acceptance stamps `billable_subscribers`,
    `rate_applied_cents_per_sub` and `license_fee_due_cents` under the final
    variant, sets `accepted_at` to the current logical instant, and moves the
    report `SUBMITTED → ACCEPTED`."
    PRD §3.4: "Under the **final** variant, stamped at acceptance into
    `billable_subscribers` and `license_fee_due_cents`, the billable count is the
    greater of `reported_subscribers` and the floor subscriber count."

    Design: Corner/rbac/other_roles_cannot_adjudicate_reports_or_move_money
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE, TERMS)
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )

    data = validate_success(
        api.review_subscriber_report(report["id"], {"action": "ACCEPT"}, ACCOUNTANT)
    )

    assert data["status"] == "ACCEPTED", (
        f"the accountant's ACCEPT must move the report to ACCEPTED, got {data['status']}"
    )
    assert data["license_fee_due_cents"] == 5_200_000, (
        "130,000 billable subscribers at 40.0000 cents on BASIC must stamp "
        f"license_fee_due_cents 5200000, got {data['license_fee_due_cents']}"
    )


# ===========================================================================
# Rights writes, and the narrowed rights read surface
# ===========================================================================
def _setup_rights_targets():
    """Executed agreement, cleared title, one PLANNED window and one SCHEDULED
    blackout rule — a live target for every rights write endpoint."""
    distributor, agreement = setup_executed_agreement(MERIDIAN, TERMS)
    title = register_cleared_title(
        title="Night Circuit", linear_premiere_at="2026-01-15T00:00:00Z"
    )
    window = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-08T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    rule = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-10T00:00:00Z",
        blackout_end="2026-09-11T00:00:00Z",
        substitution_required=False,
    )
    return distributor, agreement, title, window, rule


@pytest.mark.parametrize("role", NON_RIGHTS_ROLES)
def test_only_rights_administrator_may_write_titles_windows_and_blackouts(api, role):
    """PRD §2.1: "If both headers are well-formed but the named role is not among
    the roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `RightsAdministrator` administers content: registering titles,
    setting their rights status, planning and clearing platform windows, and
    scheduling, enforcing and waiving territorial blackouts."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/rbac/rights_administrator_cannot_read_money_and_others_cannot_write_rights
    """
    distributor, agreement, title, window, rule = _setup_rights_targets()
    headers = _headers_bound_to(role, distributor)

    attempts = {
        "POST /carriage/content-titles": lambda: api.create_content_title(
            create_content_title_payload(title="Rogue Signal"), headers
        ),
        "POST /carriage/content-titles/{titleId}/rights-status": lambda: api.set_title_rights_status(
            title["id"], {"rights_status": "EXPIRED_RIGHTS"}, headers
        ),
        "POST /carriage/rights-windows": lambda: api.create_rights_window(
            create_rights_window_payload(
                agreement["id"],
                title["id"],
                platform="VOD",
                window_start="2026-11-01T00:00:00Z",
                window_end="2026-11-08T00:00:00Z",
                exclusivity="NON_EXCLUSIVE",
            ),
            headers,
        ),
        "POST /carriage/rights-windows/{windowId}/lifecycle": lambda: api.rights_window_lifecycle(
            window["id"], {"action": "CLEAR"}, headers
        ),
        "POST /carriage/blackout-rules": lambda: api.create_blackout_rule(
            create_blackout_rule_payload(
                agreement["id"],
                territory_code="CA",
                blackout_start="2026-09-20T00:00:00Z",
                blackout_end="2026-09-21T00:00:00Z",
                substitution_required=False,
            ),
            headers,
        ),
        "POST /carriage/blackout-rules/{blackoutRuleId}/lifecycle": lambda: api.blackout_rule_lifecycle(
            rule["id"], {"action": "ENFORCE"}, headers
        ),
    }

    for label, call in attempts.items():
        validate_error(call(), ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    stored_title = validate_success(api.get_content_title(title["id"], RIGHTS))
    assert stored_title["rights_status"] == "OWNED_CLEARED", (
        f"a refused rights-status write by {role} must not move the title, "
        f"got {stored_title['rights_status']}"
    )
    stored_window = validate_success(api.get_rights_window(window["id"], RIGHTS))
    assert stored_window["status"] == "PLANNED", (
        f"a refused CLEAR by {role} must leave the window PLANNED, got {stored_window['status']}"
    )
    stored_rule = validate_success(api.get_blackout_rule(rule["id"], RIGHTS))
    assert stored_rule["status"] == "SCHEDULED", (
        f"a refused ENFORCE by {role} must leave the rule SCHEDULED, got {stored_rule['status']}"
    )
    assert stored_rule["enforced_at"] is None, "a refused ENFORCE must not stamp enforced_at"


def test_rights_administrator_read_surface_excludes_invoices_and_reports(api):
    """PRD §2.1: "If both headers are well-formed but the named role is not among
    the roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `RightsAdministrator` administers content: registering titles,
    setting their rights status, planning and clearing platform windows, and
    scheduling, enforcing and waiving territorial blackouts."
    PRD §2.3: "`total_count` is the number of records matching the filter before
    pagination is applied, and `has_more` is true exactly when records remain
    beyond the current page."

    Design: Corner/rbac/rights_administrator_cannot_read_money_and_others_cannot_write_rights
    """
    _distributor, agreement = setup_executed_agreement(MERIDIAN, TERMS)
    register_cleared_title(title="Night Circuit", linear_premiere_at="2026-01-15T00:00:00Z")

    validate_error(api.list_invoices(RIGHTS), ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    validate_error(api.list_subscriber_reports(RIGHTS), ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    _titles, title_meta = validate_paginated(api.list_content_titles(RIGHTS, params={"limit": 10}))
    assert title_meta["total_count"] == 1, (
        f"the rights administrator reads its own titles, got total_count {title_meta['total_count']}"
    )

    _agreements, agreement_meta = validate_paginated(
        api.list_agreements(RIGHTS, params={"limit": 10})
    )
    assert agreement_meta["total_count"] == 1, (
        "agreements are inside the rights administrator's read surface, "
        f"got total_count {agreement_meta['total_count']}"
    )
    stored = validate_success(api.get_agreement(agreement["id"], RIGHTS))
    assert stored["id"] == agreement["id"], "the rights administrator may read one agreement"


# ===========================================================================
# The platform operator's powers, and their boundary
# ===========================================================================
def test_network_admin_has_no_agreement_report_audit_rights_or_invoice_write_powers(api):
    """PRD §2.1: "A `NetworkAdmin` is the platform operator: onboarding
    distributors, publishing rate-card rows, adjusting an operator's subscriber
    base or credit limit, and advancing the logical clock. It is deliberately
    **not** granted agreement, report, audit, rights or invoice write powers."
    PRD §2.1: "If both headers are well-formed but the named role is not among the
    roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/rbac/network_admin_cannot_act_outside_its_own_exclusive_powers
    """
    distributor, agreement = setup_executed_agreement(MERIDIAN, TERMS)
    file_and_accept_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-05",
        reported_subscribers=900_000,
        reported_tier="BASIC",
    )
    invoice = draft_invoice(distributor["id"], agreement["id"], "2026-05")
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=900_000,
        reported_tier="BASIC",
    )
    title = register_cleared_title(
        title="Harbour Lights", linear_premiere_at="2026-01-15T00:00:00Z"
    )
    window = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-08T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )

    attempts = {
        "POST /carriage/agreements/{agreementId}/lifecycle": lambda: api.agreement_lifecycle(
            agreement["id"], {"action": "SUSPEND"}, ADMIN
        ),
        "POST /carriage/subscriber-reports/{reportId}/review": lambda: api.review_subscriber_report(
            report["id"], {"action": "ACCEPT"}, ADMIN
        ),
        "POST /carriage/audit-engagements": lambda: api.create_audit_engagement(
            create_audit_engagement_payload(agreement["id"]), ADMIN
        ),
        "POST /carriage/rights-windows/{windowId}/lifecycle": lambda: api.rights_window_lifecycle(
            window["id"], {"action": "CLEAR"}, ADMIN
        ),
        "POST /carriage/invoices/{invoiceId}/lifecycle": lambda: api.invoice_lifecycle(
            invoice["id"], {"action": "ISSUE"}, ADMIN
        ),
    }
    for label, call in attempts.items():
        validate_error(call(), ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    assert fetch_agreement(agreement["id"])["lifecycle_status"] == "EXECUTED", (
        "a refused SUSPEND by the NetworkAdmin must leave the agreement EXECUTED"
    )
    assert fetch_report(report["id"])["status"] == "SUBMITTED", (
        "a refused review by the NetworkAdmin must leave the report SUBMITTED"
    )
    assert validate_success(api.get_rights_window(window["id"], RIGHTS))["status"] == "PLANNED", (
        "a refused CLEAR by the NetworkAdmin must leave the window PLANNED"
    )
    assert validate_success(api.get_invoice(invoice["id"], ACCOUNTANT))["status"] == "DRAFT", (
        "a refused ISSUE by the NetworkAdmin must leave the invoice DRAFT"
    )
    _rows, meta = validate_paginated(
        api.list_audit_engagements(AUDITOR, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"a refused engagement open must persist nothing, got total_count {meta['total_count']}"
    )


def test_network_admin_powers_are_exclusive_to_the_network_admin(api):
    """PRD §3.1: "Only a `NetworkAdmin` may adjust an operator's
    `total_subscribers` or `credit_limit_cents` after registration, and either
    adjustment bumps the operator's `version` by one."
    PRD §3.1: "Alongside operators, a `NetworkAdmin` publishes the network's rate
    card as immutable rows."
    PRD §2.5: "A `NetworkAdmin` moves the clock by supplying `to_iso8601`."
    PRD §2.1: "If both headers are well-formed but the named role is not among the
    roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/rbac/network_admin_cannot_act_outside_its_own_exclusive_powers
    """
    distributor = register_distributor(**MERIDIAN)
    clock_before = read_clock()["current_utc"]

    validate_error(
        api.patch_distributor(distributor["id"], {"credit_limit_cents": 400_000_000}, ACCOUNTANT),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_rate_card_entry(
            create_rate_card_entry_payload(
                rate_card_class="CLASS_A", tier="BASIC", published_rate_cents_per_sub=42.0000
            ),
            ACCOUNTANT,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.set_clock(clock_payload("2026-09-01T00:00:00Z"), SALES),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    unchanged = fetch_distributor(distributor["id"])
    assert unchanged["credit_limit_cents"] == 500_000_000, (
        "a refused PATCH must leave credit_limit_cents as registered, got "
        f"{unchanged['credit_limit_cents']}"
    )
    assert unchanged["version"] == 1, (
        f"a refused PATCH must not bump the operator's version, got {unchanged['version']}"
    )
    assert read_clock()["current_utc"] == clock_before, (
        "a refused clock advance must leave the logical clock where it was"
    )
    _rows, refused_card_meta = validate_paginated(api.list_rate_card_entries(ADMIN, params={"limit": 10}))
    assert refused_card_meta["total_count"] == 0, (
        f"a refused publish must persist no row, got total_count {refused_card_meta['total_count']}"
    )

    adjusted = validate_success(
        api.patch_distributor(distributor["id"], {"credit_limit_cents": 400_000_000}, ADMIN)
    )
    assert adjusted["credit_limit_cents"] == 400_000_000, (
        f"the NetworkAdmin's adjustment must stand, got {adjusted['credit_limit_cents']}"
    )
    assert adjusted["version"] == 2, (
        f"an adjustment bumps the operator's version by one, got {adjusted['version']}"
    )

    row = validate_success(
        api.create_rate_card_entry(
            create_rate_card_entry_payload(
                rate_card_class="CLASS_A", tier="BASIC", published_rate_cents_per_sub=42.0000
            ),
            ADMIN,
        ),
        201,
    )
    assert row["published_rate_cents_per_sub"] == 42.0000, (
        f"the published row keeps its rate, got {row['published_rate_cents_per_sub']}"
    )
    _rows, card_meta = validate_paginated(api.list_rate_card_entries(ADMIN, params={"limit": 10}))
    assert card_meta["total_count"] == 1, (
        f"exactly one row is published, got total_count {card_meta['total_count']}"
    )


# ===========================================================================
# Onboarding is a shared power
# ===========================================================================
@pytest.mark.parametrize(
    "role", ["RevenueAccountant", "AuditManager", "RightsAdministrator", "DistributorLiaison"]
)
def test_only_network_admin_and_sales_exec_may_onboard_an_operator(api, role):
    """PRD §3.1: "An operator enters the system as a `Distributor` registered by a
    `NetworkAdmin` or an `AffiliateSalesExec`."
    PRD §2.1: "If both headers are well-formed but the named role is not among the
    roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/rbac/distributor_onboarding_is_shared_and_other_roles_cannot_onboard
    """
    payload = create_distributor_payload(**MERIDIAN)

    validate_error(
        api.create_distributor(payload, headers_for_role(role)), ApiErrorId.ERR_FORBIDDEN_ROLE.value
    )

    _rows, meta = validate_paginated(api.list_distributors(ADMIN, params={"limit": 10}))
    assert meta["total_count"] == 0, (
        f"a refused onboarding by {role} must persist no operator, got total_count {meta['total_count']}"
    )


def test_both_authorised_roles_onboard_operators_with_identical_opening_posture(api):
    """PRD §3.1: "An operator enters the system as a `Distributor` registered by a
    `NetworkAdmin` or an `AffiliateSalesExec`."
    PRD §3.1: "A newly registered operator starts `ACTIVE` with
    `credit_hold_reason` of `NONE`, with `receivable_balance_cents`,
    `audit_recovery_balance_cents` and `executed_agreement_count` all at zero, and
    with `version` 1."

    Design: Corner/rbac/distributor_onboarding_is_shared_and_other_roles_cannot_onboard
    """
    by_admin = validate_success(api.create_distributor(create_distributor_payload(**MERIDIAN), ADMIN), 201)
    by_sales = validate_success(api.create_distributor(create_distributor_payload(**HARBOR), SALES), 201)

    for label, data in (("NetworkAdmin", by_admin), ("AffiliateSalesExec", by_sales)):
        assert data["status"] == "ACTIVE", f"{label}'s operator must open ACTIVE, got {data['status']}"
        assert data["credit_hold_reason"] == "NONE", (
            f"{label}'s operator must open with credit_hold_reason NONE, got {data['credit_hold_reason']}"
        )
        assert data["receivable_balance_cents"] == 0, (
            f"{label}'s operator must open with a zero receivable, got {data['receivable_balance_cents']}"
        )
        assert data["audit_recovery_balance_cents"] == 0, (
            f"{label}'s operator must open with a zero audit recovery balance, "
            f"got {data['audit_recovery_balance_cents']}"
        )
        assert data["executed_agreement_count"] == 0, (
            f"{label}'s operator must open with no executed agreements, "
            f"got {data['executed_agreement_count']}"
        )
        assert data["version"] == 1, f"{label}'s operator must open at version 1, got {data['version']}"

    _rows, meta = validate_paginated(api.list_distributors(ADMIN, params={"limit": 10}))
    assert meta["total_count"] == 2, (
        f"both authorised roles onboarded one operator each, got total_count {meta['total_count']}"
    )


# ===========================================================================
# Credit posture is a shared power of two peers
# ===========================================================================
def test_credit_posture_is_driven_by_either_peer_role(api):
    """PRD §3.1: "Credit posture is driven separately, by a `NetworkAdmin` or a
    `RevenueAccountant`, through a posture action naming one of `PLACE_HOLD`,
    `RELEASE_HOLD`, `SUSPEND`, `TERMINATE` or `REACTIVATE`, optionally accompanied
    by a free-text `reason`."
    PRD §3.1: "Releasing a hold is only permitted when `receivable_balance_cents`
    is at or below `credit_limit_cents` **and** `audit_recovery_balance_cents` is
    exactly zero; the operator returns to `ACTIVE` with `credit_hold_reason` back
    to `NONE`."
    PRD §3.1: "Every posture action increments the operator's `version` by one."

    Design: Corner/rbac/credit_review_peers_share_it_and_auditor_cannot_use_it
    """
    distributor = register_distributor(**MERIDIAN)

    held = validate_success(
        api.credit_review(distributor["id"], {"action": "PLACE_HOLD"}, ACCOUNTANT)
    )
    assert held["status"] == "CREDIT_HOLD", (
        f"the accountant's PLACE_HOLD must move the operator to CREDIT_HOLD, got {held['status']}"
    )
    assert held["credit_hold_reason"] == "MANUAL_REVIEW", (
        f"a hand-placed hold records MANUAL_REVIEW, got {held['credit_hold_reason']}"
    )

    released = validate_success(
        api.credit_review(distributor["id"], {"action": "RELEASE_HOLD"}, ADMIN)
    )
    assert released["status"] == "ACTIVE", (
        f"the NetworkAdmin's RELEASE_HOLD must return the operator to ACTIVE, got {released['status']}"
    )
    assert released["credit_hold_reason"] == "NONE", (
        f"release restores credit_hold_reason NONE, got {released['credit_hold_reason']}"
    )
    assert released["version"] == 3, (
        f"two posture actions on a version-1 operator leave version 3, got {released['version']}"
    )


@pytest.mark.parametrize(
    "role", ["AuditManager", "AffiliateSalesExec", "RightsAdministrator", "DistributorLiaison"]
)
def test_credit_review_is_closed_to_every_other_role(api, role):
    """PRD §3.1: "Credit posture is driven separately, by a `NetworkAdmin` or a
    `RevenueAccountant`, through a posture action naming one of `PLACE_HOLD`,
    `RELEASE_HOLD`, `SUSPEND`, `TERMINATE` or `REACTIVATE`, optionally accompanied
    by a free-text `reason`."
    PRD §2.1: "If both headers are well-formed but the named role is not among the
    roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/rbac/credit_review_peers_share_it_and_auditor_cannot_use_it
    """
    distributor = register_distributor(**MERIDIAN)
    headers = _headers_bound_to(role, distributor)

    validate_error(
        api.credit_review(distributor["id"], {"action": "PLACE_HOLD"}, headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    unchanged = fetch_distributor(distributor["id"])
    assert unchanged["status"] == "ACTIVE", (
        f"a refused posture action by {role} must leave the operator ACTIVE, got {unchanged['status']}"
    )
    assert unchanged["credit_hold_reason"] == "NONE", (
        f"a refused posture action by {role} must not write a hold reason, "
        f"got {unchanged['credit_hold_reason']}"
    )
    assert unchanged["version"] == 1, (
        f"a refused posture action by {role} must not bump version, got {unchanged['version']}"
    )


# ===========================================================================
# Delegated liaison authority, scoped to one operator
# ===========================================================================
def test_liaison_files_only_for_its_own_operator(api):
    """PRD §2.1: "A `DistributorLiaison` acts on behalf of exactly one distributing
    operator. It files that operator's monthly subscriber reports and reads that
    operator's agreements, invoices and commitments."
    PRD §2.1: "When `X-User-Role` is `DistributorLiaison`, `X-User-ID` is the `id`
    of the acting `Distributor`; ownership checks on any resource that references a
    `Distributor` compare the resource's resolved distributor identity to
    `X-User-ID`."
    PRD §2.1: "A `DistributorLiaison` acting on a resource that resolves to any
    other operator is rejected with `ERR_DISTRIBUTOR_SCOPE_VIOLATION` (HTTP 403)."
    PRD §3.4: "A new report opens in `SUBMITTED` with `license_fee_due_cents` 0,
    `audit_adjustment_cents` 0, `invoice_id` null, `accepted_at` null and `version`
    1, and it increments the agreement's `version` by one."

    Design: Corner/rbac/liaison_authority_is_delegated_and_scoped_to_one_operator
    """
    owner, agreement = setup_executed_agreement(MERIDIAN, TERMS)
    outsider = register_distributor(**HARBOR)
    own_liaison = make_distributor_liaison_headers(owner["id"])
    foreign_liaison = make_distributor_liaison_headers(outsider["id"])

    foreign_payload = create_subscriber_report_payload(
        agreement["id"],
        agreement_version(agreement["id"]),
        period_month="2026-06",
        reported_subscribers=900_000,
        reported_tier="BASIC",
    )
    validate_error(
        api.create_subscriber_report(foreign_payload, foreign_liaison),
        ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION.value,
    )
    _rows, meta = validate_paginated(
        api.list_subscriber_reports(ACCOUNTANT, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"the foreign liaison's filing must persist nothing, got total_count {meta['total_count']}"
    )

    own_payload = create_subscriber_report_payload(
        agreement["id"],
        agreement_version(agreement["id"]),
        period_month="2026-06",
        reported_subscribers=900_000,
        reported_tier="BASIC",
    )
    filed = validate_success(api.create_subscriber_report(own_payload, own_liaison), 201)
    assert filed["status"] == "SUBMITTED", (
        f"the operator's own liaison files a SUBMITTED report, got {filed['status']}"
    )
    assert filed["reported_subscribers"] == 900_000, (
        f"the filing keeps its declared count, got {filed['reported_subscribers']}"
    )
    assert filed["version"] == 1, f"a new report opens at version 1, got {filed['version']}"

    validate_error(
        api.get_agreement(agreement["id"], foreign_liaison),
        ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION.value,
    )
    read_back = validate_success(api.get_agreement(agreement["id"], own_liaison))
    assert read_back["id"] == agreement["id"], (
        "the operator's own liaison reads that operator's agreement"
    )


# ===========================================================================
# The audit recovery chain needs two roles
# ===========================================================================
def test_audit_recovery_chain_requires_the_auditor_and_the_accountant(api):
    """PRD §2.1: "An `AuditManager` exercises audit rights: opening engagements,
    recording findings and issuing them. It is deliberately barred from raising the
    recovery invoice."
    PRD §3.7: "On creation the server snapshots the report's `period_month` and its
    `reported_subscribers` onto the finding, so a later restatement cannot rewrite
    audit history, and computes `variance_subscribers` as the audited count less
    the reported count, floored at zero — an operator that over-reported produces a
    finding of zero variance, never a negative one."
    PRD §3.7: "The recovery is billed by the accountant, not the auditor, and the
    money's path back closes the engagement."
    PRD §3.7: "When an audit-recovery invoice is drafted naming this engagement,
    the engagement moves `FINDINGS_ISSUED → RECOVERY_INVOICED` and its
    `recovery_invoice_id` is set to the new invoice — permitted only while
    `recovery_invoice_id` is null and `recovery_amount_cents` is strictly
    positive."
    PRD §2.1: "If both headers are well-formed but the named role is not among the
    roles authorised for the endpoint being called (see the table in §4), the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/audit_recovery_chain_cannot_be_completed_by_one_role
    """
    distributor, agreement, report, engagement = setup_engagement_in_fieldwork(
        CLIFFSIDE,
        TERMS,
        {"period_month": "2026-06", "reported_subscribers": 130_000, "reported_tier": "BASIC"},
    )

    validate_error(
        api.create_audit_finding(
            engagement["id"], create_audit_finding_payload(report["id"], 140_000), ACCOUNTANT
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    finding = validate_success(
        api.create_audit_finding(
            engagement["id"], create_audit_finding_payload(report["id"], 140_000), AUDITOR
        ),
        201,
    )
    assert finding["variance_subscribers"] == 10_000, (
        "140,000 audited against 130,000 reported is a variance of 10000, got "
        f"{finding['variance_subscribers']}"
    )

    issued = issue_findings(engagement["id"])
    assert issued["status"] == "FINDINGS_ISSUED", (
        f"the auditor's ISSUE_FINDINGS must move the engagement on, got {issued['status']}"
    )
    assert issued["recovery_amount_cents"] > 0, (
        f"a substantiated shortfall prices a positive recovery, got {issued['recovery_amount_cents']}"
    )

    auditor_attempt = create_invoice_payload(
        distributor["id"],
        agreement["id"],
        "2026-08",
        distributor_version(distributor["id"]),
        invoice_kind="AUDIT_RECOVERY",
        audit_engagement_id=engagement["id"],
    )
    validate_error(
        api.create_invoice(auditor_attempt, AUDITOR), ApiErrorId.ERR_FORBIDDEN_ROLE.value
    )
    still_issued = validate_success(api.get_audit_engagement(engagement["id"], AUDITOR))
    assert still_issued["status"] == "FINDINGS_ISSUED", (
        f"the auditor's refused draft must leave the engagement where it was, got {still_issued['status']}"
    )
    assert still_issued["recovery_invoice_id"] is None, (
        "the auditor's refused draft must leave recovery_invoice_id null"
    )

    accountant_payload = create_invoice_payload(
        distributor["id"],
        agreement["id"],
        "2026-08",
        distributor_version(distributor["id"]),
        invoice_kind="AUDIT_RECOVERY",
        audit_engagement_id=engagement["id"],
    )
    invoice = validate_success(api.create_invoice(accountant_payload, ACCOUNTANT), 201)

    settled = validate_success(api.get_audit_engagement(engagement["id"], AUDITOR))
    assert settled["status"] == "RECOVERY_INVOICED", (
        f"the accountant's draft moves the engagement to RECOVERY_INVOICED, got {settled['status']}"
    )
    assert settled["recovery_invoice_id"] == invoice["id"], (
        "recovery_invoice_id must name the drafted invoice, got "
        f"{settled['recovery_invoice_id']} vs {invoice['id']}"
    )
