"""Role authorisation, identity threading and duty separation.

Every test builds its own world from the public endpoints: the harness restarts
the server and empties the store before each test, and the logical clock starts
at 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import types as T
from test_helpers.assertions import assert_empty, assert_fields, round_half_up
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ANALYST_HEADERS,
    RISK_ANALYST_ID,
    SECOND_AGENT_HEADERS,
    SECOND_SERVICING_AGENT_ID,
    SERVICING_AGENT_ID,
    UNDERWRITER_HEADERS,
    UNDERWRITER_ID,
    consumer_headers,
    headers_without_user_id,
    merchant_headers,
)


# ─── Shared builders ──────────────────────────────────

def _requested_draw(api):
    """An approved merchant with one VERIFIED milestone and one REQUESTED draw of 1050000."""
    scenario = S.project_with_milestones(api, releases=(3000,), verify=(0,))
    S.request_draw(api, scenario, 1050000)
    return scenario


def _settled_draw(api):
    """The same world carried one step further: the 1050000 draw is SETTLED by sa-1."""
    return S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))


def _delivered_disclosure(api):
    """Dana's application with the disclosure DELIVERED and not yet acknowledged."""
    return S.disclosed_application(api, acknowledge=False)


# ─── Exclusive operations refuse every role outside their list ──────

def test_the_merchant_cannot_settle_the_draw_it_requested(api):
    """A merchant calling the settlement endpoint is refused on role, leaving the draw REQUESTED.

    PRD: "A `ServicingAgent` moves money: it settles and reverses draws, posts reserve adjustments, resolves disputes, posts payments, drives the logical clock and runs the expiration sweep."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = _requested_draw(api)
    draw_id = scenario.draw["id"]

    response = api.settle_funding_draw(
        draw_id, F.settlement_payload("SETTLE"), scenario.as_merchant
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    draw = S.read_draw(api, draw_id)
    assert_fields(draw, status="REQUESTED")
    assert_empty(draw, "settled_on", "released_by_user_id", "net_settlement_cents")


def test_the_homeowner_cannot_open_the_contracted_project(api):
    """Project creation belongs to the merchant, so a homeowner's attempt is refused on role.

    PRD: "When both headers are well-formed but the declared role is not listed among the roles authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = S.project(api)

    response = api.create_project(
        F.project_payload(scenario.application_id), scenario.as_consumer
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    projects, meta = validate_paginated(
        api.list_projects(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert meta["total_count"] == 1, "The refused call must not have opened a second project"
    assert projects[0]["id"] == scenario.project_id


def test_the_risk_analyst_cannot_move_the_holdback_reserve(api):
    """Reserve movement is the agent's alone: an analyst's deposit is refused without touching the reserve.

    PRD: "A `RiskAnalyst` raises and investigates phantom-project fraud alerts."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = _settled_draw(api)
    before = S.read_merchant(api, scenario.merchant_id)
    assert_fields(before, holdback_reserve_cents=42000)

    response = api.post_holdback_adjustment(
        scenario.merchant_id,
        F.holdback_adjustment_payload("DEPOSIT", 500, before["version"]),
        ANALYST_HEADERS,
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    after = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        after, holdback_reserve_cents=42000, version=before["version"]
    )


def test_the_underwriter_cannot_publish_a_trade_rule(api):
    """Trade rules are the program administrator's table, so an underwriter's write is refused.

    PRD: "A `ProgramAdmin` owns the program: it maintains trade rules and promotion plans, registers merchants, and changes program posture."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    S.create_trade_rule(api)

    response = api.create_trade_rule(
        F.trade_rule_payload(**C.HVAC_TRADE_RULE), UNDERWRITER_HEADERS
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    _rules, meta = validate_paginated(api.list_trade_rules(ADMIN_HEADERS))
    assert meta["total_count"] == 1, "The refused call must not have published a trade rule"


def test_the_servicing_agent_cannot_change_program_posture(api):
    """Suspension is a posture change reserved to the administrator, so the agent is refused on role.

    PRD: "A `ProgramAdmin` owns the program: it maintains trade rules and promotion plans, registers merchants, and changes program posture."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = S.approved_merchant(api)

    response = api.program_action(
        scenario.merchant_id, F.program_action_payload("SUSPEND"), AGENT_HEADERS
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    assert_fields(S.read_merchant(api, scenario.merchant_id), enrollment_status="APPROVED")


def test_the_merchant_is_refused_on_role_before_the_application_state_is_examined(api):
    """The role gate precedes the state gate: a merchant accepting an already-activated offer sees the role error.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = S.activated_loan(api)
    assert_fields(S.read_application(api, scenario.application_id), decision="ACTIVATED")

    response = api.accept_offer(
        scenario.application_id, F.acceptance_payload(), scenario.as_merchant
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)


def test_the_servicing_agent_cannot_raise_a_phantom_project_alert(api):
    """Alert creation belongs to the analyst, so the agent's alert is refused and no score moves.

    PRD: "A `RiskAnalyst` raises an alert manually, supplying an `alert_type` of `PHANTOM_PROJECT`, `PRE_COMPLETION_FULL_DRAW`, `VELOCITY_SPIKE` or `DUPLICATE_CONSUMER`, a `severity_weight` from 1 through 100, and optionally an `evidence_ref`."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = S.approved_merchant(api)

    response = api.create_fraud_alert(
        scenario.merchant_id,
        F.fraud_alert_payload("PHANTOM_PROJECT", 35),
        AGENT_HEADERS,
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    _alerts, meta = validate_paginated(
        api.list_fraud_alerts(scenario.merchant_id, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0, "The refused call must not have recorded an alert"
    assert_fields(S.read_merchant(api, scenario.merchant_id), phantom_risk_score=0)


def test_the_program_admin_cannot_decide_merchant_enrollment(api):
    """Administrative reach does not override the underwriter's exclusive enrollment decision.

    PRD: "A `ProgramUnderwriter` verifies licences, decides merchant enrollment and grants promotion enrollments."

    Design: Corner/rbac/merchant_consumer_and_operator_roles_cannot_cross_into_exclusive_operations
    """
    scenario = S.approved_merchant(api, approve=False)
    assert_fields(S.read_merchant(api, scenario.merchant_id), enrollment_status="PENDING_REVIEW")

    response = api.decide_enrollment(
        scenario.merchant_id, F.enrollment_decision_payload("APPROVE"), ADMIN_HEADERS
    )
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    assert_fields(
        S.read_merchant(api, scenario.merchant_id), enrollment_status="PENDING_REVIEW"
    )
    assert_empty(S.read_merchant(api, scenario.merchant_id), "approved_by_user_id")


# ─── Shared operations succeed for every declared holder ────────────

def test_the_program_admin_may_register_a_homeowner(api):
    """Registration is shared with the administrator, and the new homeowner opens with empty aggregates.

    PRD: "A newly registered consumer carries `existing_program_debt_cents` of zero and `active_loan_count` of zero."

    Design: Corner/rbac/shared_operations_succeed_for_every_declared_holder
    """
    S.enrolled_merchant(api)

    consumer = validate_success(
        api.create_consumer(F.consumer_payload(), ADMIN_HEADERS), 201
    )
    assert_fields(
        consumer,
        full_name=C.CANONICAL_CONSUMER["full_name"],
        existing_program_debt_cents=0,
        active_loan_count=0,
    )


def test_the_program_admin_may_file_a_licence_for_the_merchant(api):
    """A licence filed by the administrator opens UNVERIFIED with no verifier recorded.

    PRD: "A newly filed licence stands at `verification_status` `UNVERIFIED`, with `verified_by_user_id` and `verified_on` empty."

    Design: Corner/rbac/shared_operations_succeed_for_every_declared_holder
    """
    scenario = S.approved_merchant(api)

    licence = validate_success(
        api.file_license(
            scenario.merchant_id,
            F.license_payload(
                license_number="OK-RCF-30017",
                state_code="OK",
                effective_from="2026-02-01",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(
        licence,
        merchant_id=scenario.merchant_id,
        state_code="OK",
        verification_status="UNVERIFIED",
    )
    assert_empty(licence, "verified_by_user_id", "verified_on")


def test_the_servicing_agent_may_sign_off_a_milestone_that_waives_consumer_signoff(api):
    """With `requires_consumer_signoff` false the agent's verification lands and releases headroom.

    PRD: "It also carries `requires_consumer_signoff`, which defaults to true when omitted: when true, only the owning homeowner may sign the milestone off; when false, a `ServicingAgent` may sign it off as well."

    Design: Corner/rbac/shared_operations_succeed_for_every_declared_holder
    """
    scenario = S.project(api)
    S.add_milestones(api, scenario, (3000,), requires_consumer_signoff=False)
    S.claim_milestone(api, scenario, 0)

    milestone = validate_success(
        api.verify_milestone(
            scenario.project_id,
            scenario.milestone_id(0),
            F.milestone_verification_payload("VERIFY"),
            AGENT_HEADERS,
        )
    )
    assert_fields(milestone, status="VERIFIED")
    # 3500000 * min(3000, 7000) / 10000 = 1050000, nothing settled and nothing pending.
    assert_fields(
        S.read_project(api, scenario.project_id),
        verified_release_bps=3000,
        max_fundable_now_cents=1050000,
    )


def test_the_servicing_agent_may_post_a_payment_for_the_homeowner(api):
    """An agent-posted payment allocates to principal and stamps the account's last payment date.

    PRD: "Payments may be posted by the homeowner or by a `ServicingAgent`, naming the `loan_account_id` and an `amount_cents` strictly greater than zero."

    Design: Corner/rbac/shared_operations_succeed_for_every_declared_holder
    """
    scenario = S.settled_draw(api, amount_cents=300000, releases=(3000,), verify=(0,))
    assert_fields(S.read_loan(api, scenario.loan_id), principal_balance_cents=300000)

    payment = validate_success(
        api.create_payment(F.payment_payload(scenario.loan_id, 100000), AGENT_HEADERS), 201
    )
    # No capitalised interest exists while the promotion is active, so all of it hits principal.
    assert_fields(
        payment,
        applied_to_capitalized_interest_cents=0,
        applied_to_principal_cents=100000,
        resulting_principal_balance_cents=200000,
        source_role="SERVICING_AGENT",
        posted_on=C.DEFAULT_CLOCK_DATE,
    )
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=200000,
        balance_status="CURRENT",
        last_payment_on=C.DEFAULT_CLOCK_DATE,
    )


def test_the_program_admin_may_drive_the_clock_and_run_the_checkpoint(api):
    """The administrator shares the clock and the ops checkpoint, which reports nothing due one day on.

    PRD: "Everything else that is driven purely by the passage of time happens in one ops-run checkpoint, which a `ServicingAgent` or `ProgramAdmin` invokes with no payload."

    Design: Corner/rbac/shared_operations_succeed_for_every_declared_holder
    """
    S.activated_loan(api)

    clock = validate_success(
        api.set_clock(F.clock_payload("2026-08-02T00:00:00Z"), ADMIN_HEADERS)
    )
    assert clock["current_utc"][:19] == "2026-08-02T00:00:00", clock["current_utc"]
    assert clock["previous_utc"][:19] == C.DEFAULT_CLOCK[:19], clock["previous_utc"]

    counts = validate_success(api.run_expiration_sweep({}, ADMIN_HEADERS))
    for key in T.SWEEP_COUNT_KEYS:
        assert counts[key] == 0, f"Nothing is due at 2026-08-02, but {key} reported {counts[key]}"


# ─── Identity resolution and cross-owner access ─────────────────────

def test_acknowledgement_without_a_user_id_header_is_unauthenticated(api):
    """A write that omits `X-User-ID` is refused before identity is resolved at all.

    PRD: "A request whose `X-User-Role` header is absent, or whose value is not one of those six strings, is rejected with `ERR_UNAUTHENTICATED`; the same rejection applies to any request other than a read that omits `X-User-ID` or supplies it empty."

    Design: Corner/rbac/missing_identity_headers_and_cross_owner_access_are_rejected
    """
    scenario = _delivered_disclosure(api)

    response = api.acknowledge_disclosure(
        scenario.application_id,
        F.disclosure_acknowledgement_payload(),
        headers_without_user_id(T.ROLE_CONSUMER),
    )
    validate_error(response, E.ERR_UNAUTHENTICATED)

    application = S.read_application(api, scenario.application_id)
    assert_fields(application, disclosure_status="DELIVERED")
    assert_empty(application, "disclosure_acknowledged_at")


def test_acknowledgement_by_an_id_that_is_not_a_consumer_row_is_identity_unknown(api):
    """A well-formed `Consumer` header whose id belongs to another table resolves to nothing.

    PRD: "For both of these roles, if `X-User-ID` does not resolve to an existing row of the backing entity, the request fails with `ERR_IDENTITY_UNKNOWN`."

    Design: Corner/rbac/missing_identity_headers_and_cross_owner_access_are_rejected
    """
    scenario = _delivered_disclosure(api)

    response = api.acknowledge_disclosure(
        scenario.application_id,
        F.disclosure_acknowledgement_payload(),
        consumer_headers(scenario.plan_id),
    )
    validate_error(response, E.ERR_IDENTITY_UNKNOWN)

    assert_fields(
        S.read_application(api, scenario.application_id), disclosure_status="DELIVERED"
    )


def test_another_homeowner_cannot_acknowledge_this_homeowners_disclosure(api):
    """An id that resolves to a different homeowner is a scope violation, not an unknown identity.

    PRD: "If it resolves but points at a different party than the resource being touched, a merchant acting outside its own book is rejected with `ERR_MERCHANT_SCOPE_VIOLATION` and a consumer acting outside its own book with `ERR_CONSUMER_SCOPE_VIOLATION`."

    Design: Corner/rbac/missing_identity_headers_and_cross_owner_access_are_rejected
    """
    scenario = _delivered_disclosure(api)
    stranger = S.register_consumer(api, scenario.merchant_id, **C.SECOND_CONSUMER)

    response = api.acknowledge_disclosure(
        scenario.application_id,
        F.disclosure_acknowledgement_payload(),
        consumer_headers(stranger["id"]),
    )
    validate_error(response, E.ERR_CONSUMER_SCOPE_VIOLATION)

    application = S.read_application(api, scenario.application_id)
    assert_fields(application, disclosure_status="DELIVERED")
    assert_empty(application, "disclosure_acknowledged_at")


def test_a_merchant_cannot_file_an_application_in_another_merchants_name(api):
    """A merchant naming another merchant's `merchant_id` is refused and files nothing.

    PRD: "If it resolves but points at a different party than the resource being touched, a merchant acting outside its own book is rejected with `ERR_MERCHANT_SCOPE_VIOLATION` and a consumer acting outside its own book with `ERR_CONSUMER_SCOPE_VIOLATION`."

    Design: Corner/rbac/missing_identity_headers_and_cross_owner_access_are_rejected
    """
    scenario = S.application(api)
    intruder = S.register_merchant(api, **C.SECOND_MERCHANT)

    response = api.create_credit_application(
        F.credit_application_payload(
            scenario.merchant_id, scenario.consumer_id, scenario.plan_id
        ),
        merchant_headers(intruder["id"]),
    )
    validate_error(response, E.ERR_MERCHANT_SCOPE_VIOLATION)

    _apps, meta = validate_paginated(
        api.list_credit_applications(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id})
    )
    assert meta["total_count"] == 1, "The refused call must not have filed an application"


def test_the_owning_homeowner_acknowledges_the_same_disclosure(api):
    """The identical call from the owning homeowner lands, proving only identity was at fault.

    PRD: "Acknowledgement stamps `disclosure_acknowledged_at` from the logical clock."

    Design: Corner/rbac/missing_identity_headers_and_cross_owner_access_are_rejected
    """
    scenario = _delivered_disclosure(api)

    application = validate_success(
        api.acknowledge_disclosure(
            scenario.application_id,
            F.disclosure_acknowledgement_payload(),
            scenario.as_consumer,
        )
    )
    assert_fields(application, disclosure_status="ACKNOWLEDGED")
    assert application["disclosure_acknowledged_at"], "Acknowledgement must be stamped"


# ─── Duty separation: alerts and disputes ───────────────────────────

def test_the_underwriter_that_approved_the_merchant_cannot_close_its_alert(api):
    """An analyst-role call carrying the approving underwriter's handle is refused on duty separation.

    PRD: "The `RiskAnalyst` closing a fraud investigation must not be the same operator identifier recorded in that merchant's `approved_by_user_id`."

    Design: Corner/rbac/the_underwriter_that_approved_the_merchant_cannot_close_its_fraud_alert
    """
    scenario = S.approved_merchant(api)
    alert = S.raise_fraud_alert(api, scenario.merchant_id, severity_weight=40)
    before = S.read_merchant(api, scenario.merchant_id)
    # One OPEN alert counts at half weight: round_half_up(40 / 2) = 20.
    assert_fields(
        before, approved_by_user_id=UNDERWRITER_ID, phantom_risk_score=round_half_up(40, 2)
    )

    response = api.investigate_fraud_alert(
        scenario.merchant_id,
        alert["id"],
        F.investigation_payload("CLEARED"),
        build_user_headers(UNDERWRITER_ID, T.ROLE_RISK_ANALYST),
    )
    validate_error(response, E.ERR_SEGREGATION_OF_DUTIES)

    alerts, _meta = validate_paginated(
        api.list_fraud_alerts(scenario.merchant_id, ANALYST_HEADERS)
    )
    assert_fields(alerts[0], status="OPEN")
    assert_empty(alerts[0], "investigated_by_user_id")
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        phantom_risk_score=20,
        version=before["version"],
    )


def test_a_different_analyst_closes_the_same_alert(api):
    """A distinct analyst handle clears the alert, dropping it from the phantom score entirely.

    PRD: "`OPEN → CLEARED` instead recomputes `phantom_risk_score` with the alert dropped entirely, and recomputes `risk_tier`, `portfolio_grade`, `termination_recommended` and `holdback_target_cents`."

    Design: Corner/rbac/the_underwriter_that_approved_the_merchant_cannot_close_its_fraud_alert
    """
    scenario = S.approved_merchant(api)
    alert = S.raise_fraud_alert(api, scenario.merchant_id, severity_weight=40)
    before = S.read_merchant(api, scenario.merchant_id)

    closed = validate_success(
        api.investigate_fraud_alert(
            scenario.merchant_id,
            alert["id"],
            F.investigation_payload("CLEARED"),
            ANALYST_HEADERS,
        )
    )
    assert_fields(closed, status="CLEARED", investigated_by_user_id=RISK_ANALYST_ID)
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        phantom_risk_score=0,
        version=before["version"] + 1,
    )


def test_the_agent_that_released_the_draw_cannot_resolve_that_projects_dispute(api):
    """The releasing agent is barred from the resolution, and the bar precedes the version guard.

    PRD: "The `ServicingAgent` resolving a dispute case must not be the same operator identifier recorded in `released_by_user_id` on any settled draw belonging to the disputed project."

    Design: Corner/rbac/the_agent_that_released_the_draw_cannot_resolve_that_projects_dispute
    """
    scenario = _settled_draw(api)
    assert_fields(scenario.draw, released_by_user_id=SERVICING_AGENT_ID)
    case = S.file_dispute(api, scenario, 50000)
    validate_success(
        api.respond_to_dispute(
            case["id"],
            F.merchant_response_payload("WORK_COMPLETE_EVIDENCE"),
            scenario.as_merchant,
        )
    )
    version_before = S.merchant_version(api, scenario.merchant_id)

    response = api.resolve_dispute(
        case["id"], F.resolution_payload("MERCHANT_FAVOR", version_before), AGENT_HEADERS
    )
    validate_error(response, E.ERR_SEGREGATION_OF_DUTIES)

    assert_fields(
        S.read_dispute(api, case["id"]),
        status="MERCHANT_RESPONSE_PENDING",
        chargeback_amount_cents=0,
    )
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        version=version_before,
        holdback_reserve_cents=42000,
    )


def test_a_second_agent_resolves_the_same_dispute_in_the_merchants_favour(api):
    """An agent who released nothing on the project may resolve it, and the merchant keeps the funds.

    PRD: "The merchant keeps the funds: `chargeback_amount_cents` stays at zero and there is no reserve, receivable or write-off movement of any kind."

    Design: Corner/rbac/the_agent_that_released_the_draw_cannot_resolve_that_projects_dispute
    """
    scenario = _settled_draw(api)
    case = S.file_dispute(api, scenario, 50000)
    validate_success(
        api.respond_to_dispute(
            case["id"],
            F.merchant_response_payload("WORK_COMPLETE_EVIDENCE"),
            scenario.as_merchant,
        )
    )
    version_before = S.merchant_version(api, scenario.merchant_id)

    resolved = validate_success(
        api.resolve_dispute(
            case["id"],
            F.resolution_payload("MERCHANT_FAVOR", version_before),
            SECOND_AGENT_HEADERS,
        )
    )
    assert_fields(
        resolved,
        status="RESOLVED_MERCHANT_FAVOR",
        resolved_by_user_id=SECOND_SERVICING_AGENT_ID,
        resolved_on=C.DEFAULT_CLOCK_DATE,
        chargeback_amount_cents=0,
        chargeback_absorbed_from_reserve_cents=0,
        chargeback_receivable_cents=0,
        chargeback_write_off_cents=0,
    )
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=42000,
        settlement_offset_receivable_cents=0,
        program_write_off_cents=0,
        version=version_before + 1,
    )
