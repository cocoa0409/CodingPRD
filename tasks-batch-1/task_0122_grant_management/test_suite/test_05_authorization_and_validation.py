"""Authentication, authorization, validation ordering, OCC, and segregation of duties.

Sources: Difficulty queue (priority_pair_validation_conflict) and Corner queue
(entities FK/listing/type-constraints, validations ordering/period, errors auth/award/
stale, rbac, cross_cutting OCC stale-version).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers.test_users import ANONYMOUS_HEADERS
import test_helpers.fixtures as fx

GW = TEST_USERS["grant_writer_headers"]
FO = TEST_USERS["finance_officer_headers"]
PM = TEST_USERS["program_manager_headers"]
AO = TEST_USERS["agency_officer_headers"]
AU = TEST_USERS["auditor_headers"]


# ==========================================================================
# Priority-pair validation conflicts (Difficulty Rule 5)
# ==========================================================================
def test_state_check_precedes_ceiling_on_disburse(api):
    """PRD §3.9: "State validity comes fourth: a transition attempted from a state in
    which it is not defined fails with ERR_INVALID_STATE."
    PRD §3.9: "Twelfth, the federal-ceiling guard on disbursement fails with
    ERR_CEILING_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_ceiling_on_disburse
    """
    # ceiling = 10000000 * 0.80 = 8000000; one fund budget 10000000; a 8000000 drawdown
    # already DISBURSED. A second disburse of the same drawdown is no longer REQUESTED
    # AND would breach the ceiling -> the lower-priority state check (409) wins.
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A9", applicant_org_name="Org I",
        requested_amount_cents=10_000_000, federal_share_pct=0.80,
    )
    fund = funds[0]
    dd = fx.create_disbursed_drawdown(
        award["id"], 8_000_000, fx.single_line_plan(fund["id"], 8_000_000),
        initiator_user_id="officer-draw-A9",
    )
    resp = api.disburse_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A9"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"] == 8_000_000


def test_redisburse_disbursed_drawdown_stays_disbursed_state_error(api):
    """PRD §3.5: "Disbursing a drawdown is where the money actually moves" — defined only
    from REQUESTED.
    PRD §3.9: "State validity comes fourth: a transition attempted from a state in which it
    is not defined fails with ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_ceiling_on_disburse
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A9b", applicant_org_name="Org I2",
        requested_amount_cents=10_000_000, federal_share_pct=0.80,
    )
    fund = funds[0]
    dd = fx.create_disbursed_drawdown(
        award["id"], 8_000_000, fx.single_line_plan(fund["id"], 8_000_000),
        initiator_user_id="officer-draw-A9b",
    )
    resp = api.disburse_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A9b"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    # The already-disbursed drawdown is unchanged (no double debit, no RETURNED).
    assert validate_success(api.get_drawdown(dd["id"], FO))["status"] == "DISBURSED"


def test_segregation_of_duties_fires_on_certify_while_award_active(api):
    """PRD §3.6: "certification enforces segregation of duties: the acting X-User-ID must
    not equal any initiated_by_user_id recorded on any drawdown of the same award, so that
    the operator who moved the money cannot be the operator who attests to its propriety.
    A certifier who initiated a drawdown on that award is rejected with
    ERR_SEGREGATION_OF_DUTIES."
    PRD §3.6: "Certification is permitted only when the parent award is in ACTIVE or
    PENDING_CLOSEOUT status."

    Design: Difficulty/priority_pair_validation_conflict/safety_segregation_before_referential_award_active_on_certify
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A10", applicant_org_name="Org J",
        requested_amount_cents=20_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 5_000_000, fx.single_line_plan(fund["id"], 5_000_000),
        initiator_user_id="officer-X",
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    )
    # officer-X both initiated a drawdown and now tries to certify -> segregation violation,
    # while award is ACTIVE (so the referential award-active check passes).
    resp = api.certify_financial_report(report["id"], fx.make_finance_officer_headers("officer-X"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409)
    assert validate_success(api.get_financial_report(report["id"], FO))["status"] == "DRAFT"
    assert validate_success(api.get_award(award["id"], AO))["status"] == "ACTIVE"


def test_segregation_violation_leaves_report_uncertified(api):
    """PRD §3.6: "A certifier who initiated a drawdown on that award is rejected with
    ERR_SEGREGATION_OF_DUTIES."
    PRD §3.6: "The FinanceOfficer certifies a DRAFT report, moving it to SUBMITTED and
    recording the acting operator on certified_by_user_id."

    Design: Difficulty/priority_pair_validation_conflict/safety_segregation_before_referential_award_active_on_certify
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A10b", applicant_org_name="Org J2",
        requested_amount_cents=20_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 5_000_000, fx.single_line_plan(fund["id"], 5_000_000),
        initiator_user_id="officer-Y",
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    )
    resp = api.certify_financial_report(report["id"], fx.make_finance_officer_headers("officer-Y"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409)
    # The rejected certification left the report in DRAFT (no certified_by recorded).
    after = validate_success(api.get_financial_report(report["id"], FO))
    assert after["status"] == "DRAFT"
    assert after.get("certified_by_user_id") in (None, "")


# ==========================================================================
# Corner: errors (unauthenticated, award-not-active, stale-version)
# ==========================================================================
def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    payload = {
        "nofo_number": "NOFO-2026-C35", "applicant_org_name": "Corner Org 35",
        "requested_amount_cents": 30_000_000,
        "period_start_date": "2026-01-01T00:00:00Z", "period_end_date": "2026-12-31T00:00:00Z",
    }
    resp = api.create_application(payload, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_award_not_active_on_disburse_suspended_award(api):
    """PRD §3.5: "The parent award must be ACTIVE, failing otherwise with
    ERR_AWARD_NOT_ACTIVE."

    Design: Corner/errors/error_award_not_active_on_disburse_suspended_award
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C36", applicant_org_name="Corner Org 36",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    dd = fx.create_drawdown(
        award["id"], 3_000_000, fx.single_line_plan(fund["id"], 3_000_000),
        initiator_user_id="officer-draw-C36",
    )
    validate_success(api.suspend_award(award["id"], {"expected_award_version": award["version"]}, AO))
    resp = api.disburse_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-C36"))
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_ACTIVE.value, expected_status=409)
    assert validate_success(api.get_drawdown(dd["id"], FO))["status"] == "REQUESTED"
    assert validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"] == 0


def test_stale_version_on_suspend_after_rate_bump(api):
    """PRD §2.6: "The server compares it to the award's current version; if they differ,
    the request is rejected with ERR_STALE_VERSION (HTTP 412) and no change is made."
    PRD §3.3: "Because this mutates the award, the create requires expected_award_version
    and increments the award's version."

    Design: Corner/errors/error_stale_version_triggerable
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C37", applicant_org_name="Corner Org 37",
        requested_amount_cents=50_000_000,
    )
    v0 = award["version"]
    # rate-create advances award.version.
    fx.set_indirect_cost_rate(award["id"], v0, rate_type="DE_MINIMIS", base_type="MTDC")
    resp = api.suspend_award(award["id"], {"expected_award_version": v0}, AO)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    assert validate_success(api.get_award(award["id"], AO))["status"] == "ACTIVE"


def test_stale_version_on_second_rate_create(api):
    """PRD §2.6: "a second create request that still carries the version the client first
    observed describes a stale view: the first create already moved the award forward, so
    the second is rejected with ERR_STALE_VERSION (HTTP 412) on the stale version, not on
    any state precondition."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_rate_create_returns_stale_version
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C43", applicant_org_name="Corner Org 43",
        requested_amount_cents=50_000_000,
    )
    v0 = award["version"]
    fx.set_indirect_cost_rate(award["id"], v0, rate_type="NEGOTIATED", negotiated_rate=0.30, base_type="MTDC")
    resp = api.create_indirect_cost_rate({
        "award_id": award["id"], "rate_type": "DE_MINIMIS", "base_type": "MTDC",
        "expected_award_version": v0,
    }, FO)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ==========================================================================
# Corner: existence-before-state ordering and period validation
# ==========================================================================
def test_existence_precedes_state_on_disburse_nonexistent_drawdown(api):
    """PRD §3.9: "Existence comes third: any path resource or required foreign key that
    does not exist fails with ERR_NOT_FOUND, with path segments resolved left to right.
    State validity comes fourth."

    Design: Corner/validations/existence_before_state_on_disburse_nonexistent_drawdown
    """
    resp = api.disburse_drawdown("00000000-0000-4000-8000-000000000000", FO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_invalid_period_end_not_after_start(api):
    """PRD §3.1: "A DRAFT application advances to SUBMITTED when the writer submits it,
    provided it is currently in DRAFT and its period_end_date is strictly after its
    period_start_date; a period that fails this ordering is rejected with
    ERR_INVALID_PERIOD."

    Design: Corner/validations/invalid_period_end_not_after_start_returns_invalid_period
    """
    app = fx.create_draft_application(
        nofo_number="NOFO-2026-C26", applicant_org_name="Corner Org 26",
        period_start_date="2026-01-01T00:00:00Z", period_end_date="2026-01-01T00:00:00Z",
    )
    resp = api.submit_application(app["id"], GW)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value, expected_status=422)
    assert validate_success(api.get_application(app["id"], GW))["status"] == "DRAFT"


# ==========================================================================
# Corner: entities FK / type-constraints / listing filter
# ==========================================================================
def test_create_subaward_nonexistent_award_fk_returns_not_found(api):
    """PRD §2.8: "a body that names an award, a drawdown, a restricted fund, or a single
    audit that does not exist is rejected with ERR_NOT_FOUND."

    Design: Corner/entities/create_subaward_nonexistent_award_fk_returns_not_found
    """
    resp = api.create_subaward({
        "award_id": "00000000-0000-4000-8000-000000000000",
        "subrecipient_name": "Sub C10", "subaward_amount_cents": 1_000_000, "risk_tier": "LOW",
    }, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_subaward_invalid_risk_tier_enum(api):
    """PRD §3.4: "a risk_tier of LOW, MEDIUM, or HIGH that defaults to LOW."
    PRD §3.9: "general request validity — required fields present, correct types, valid
    enum members... fails with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_subaward_invalid_risk_tier_enum_returns_invalid_request
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C8", applicant_org_name="Corner Org 8",
        requested_amount_cents=30_000_000,
    )
    resp = api.create_subaward({
        "award_id": award["id"], "subrecipient_name": "Sub C8",
        "subaward_amount_cents": 1_000_000, "risk_tier": "CRITICAL",
    }, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_list_restricted_funds_filtered_by_award_id(api):
    """PRD §3.5: "Restricted funds may be listed by award_id and individually retrieved to
    inspect allocated_cents."

    Design: Corner/entities/filtered_list_restricted_funds_by_award_id_fk_integrity
    """
    award_a = fx.create_active_award(
        nofo_number="NOFO-2026-C11A", applicant_org_name="Corner Org 11A",
        requested_amount_cents=50_000_000,
    )
    award_b = fx.create_active_award(
        nofo_number="NOFO-2026-C11B", applicant_org_name="Corner Org 11B",
        requested_amount_cents=50_000_000,
    )
    fx.create_restricted_fund(award_a["id"], category="PERSONNEL", budgeted_cents=5_000_000, priority_order=1)
    fx.create_restricted_fund(award_a["id"], category="TRAVEL", budgeted_cents=3_000_000, priority_order=2)
    fx.create_restricted_fund(award_b["id"], category="PERSONNEL", budgeted_cents=4_000_000, priority_order=1)
    resp = api.list_restricted_funds(FO, params={"award_id": award_a["id"]})
    from test_helpers import validate_paginated
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(rf["award_id"] == award_a["id"] for rf in data)


# ==========================================================================
# Corner: RBAC
# ==========================================================================
def test_grant_writer_cannot_disburse_drawdown(api):
    """PRD §2.1: "When the headers are well-formed and the role is recognized but that role
    is not permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN (HTTP 403)."
    PRD §4: "| POST | /drawdowns/{id}/disburse | Disburse a REQUESTED drawdown; post the waterfall | FinanceOfficer |"

    Design: Corner/rbac/rbac_grantwriter_cannot_disburse_drawdown_forbidden
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C38", applicant_org_name="Corner Org 38",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    dd = fx.create_drawdown(
        award["id"], 3_000_000, fx.single_line_plan(fund["id"], 3_000_000),
        initiator_user_id="officer-draw-C38",
    )
    resp = api.disburse_drawdown(dd["id"], GW)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert validate_success(api.get_drawdown(dd["id"], FO))["status"] == "REQUESTED"


def test_auditor_cannot_award_application(api):
    """PRD §2.1: "the request is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4: "POST | /applications/{id}/award | Award a reviewed application; create the
    Award | AgencyOfficer"

    Design: Corner/rbac/rbac_auditor_cannot_award_application_forbidden
    """
    app = fx.create_under_review_application(
        nofo_number="NOFO-2026-C39", applicant_org_name="Corner Org 39",
        requested_amount_cents=30_000_000,
    )
    resp = api.award_application(app["id"], AU)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert validate_success(api.get_application(app["id"], GW))["status"] == "UNDER_REVIEW"


def test_auditor_can_read_shared_award(api):
    """PRD §4: "GET | /awards/{id} | Retrieve one award | GrantWriter, FinanceOfficer,
    ProgramManager, AgencyOfficer, Auditor"

    Design: Corner/rbac/rbac_shared_get_awards_allowed_for_auditor
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C40", applicant_org_name="Corner Org 40",
        requested_amount_cents=30_000_000,
    )
    data = validate_success(api.get_award(award["id"], AU))
    assert data["status"] == "ACTIVE"


def test_segregation_pass_when_certifier_differs_from_initiator(api):
    """PRD §3.6: "the acting X-User-ID must not equal any initiated_by_user_id recorded on
    any drawdown of the same award."
    PRD §3.6: "The FinanceOfficer certifies a DRAFT report, moving it to SUBMITTED and
    recording the acting operator on certified_by_user_id."

    Design: Corner/rbac/rbac_segregation_certifier_differs_from_initiator_succeeds
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C41", applicant_org_name="Corner Org 41",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 3_000_000, fx.single_line_plan(fund["id"], 3_000_000),
        initiator_user_id="officer-draw-C41",
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    )
    certified = validate_success(
        api.certify_financial_report(report["id"], fx.make_finance_officer_headers("officer-cert-C41"))
    )
    assert certified["status"] == "SUBMITTED"
    assert certified["certified_by_user_id"] == "officer-cert-C41"
