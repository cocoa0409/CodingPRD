"""Error-catalogue corners: which single error id wins for a given illegitimate request.

Each test drives one malformed or illegitimate call and pins the exact code the
catalogue assigns to it, then proves the refusal left no trace behind.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_empty, assert_fields, round_half_up
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ANALYST_HEADERS,
    SECOND_AGENT_HEADERS,
    UNDERWRITER_HEADERS,
    consumer_headers,
)

#: Syntactically valid UUIDs that name no row of any kind.
_ABSENT = [f"aaaaaaaa-0000-4000-8000-{index:012d}" for index in range(1, 11)]


def test_each_flat_read_route_returns_its_own_not_found_code(api):
    """Seven single-identifier read routes each answer with the code belonging to their own type.

    PRD: "The remaining path-level not-found codes are `ERR_ENROLLMENT_NOT_FOUND` for a promotion enrollment, `ERR_APPLICATION_NOT_FOUND` for a credit application, `ERR_LOAN_ACCOUNT_NOT_FOUND` for a loan account, `ERR_PROJECT_NOT_FOUND` for a project, `ERR_DRAW_NOT_FOUND` for a funding draw and `ERR_DISPUTE_NOT_FOUND` for a dispute case."

    Design: Corner/errors/every_unresolvable_identifier_returns_its_own_not_found_code
    """
    validate_error(
        api.get_promotion_enrollment(_ABSENT[0], ADMIN_HEADERS), E.ERR_ENROLLMENT_NOT_FOUND
    )
    validate_error(api.get_consumer(_ABSENT[1], ADMIN_HEADERS), E.ERR_CONSUMER_NOT_FOUND)
    validate_error(
        api.get_credit_application(_ABSENT[2], ADMIN_HEADERS), E.ERR_APPLICATION_NOT_FOUND
    )
    validate_error(
        api.get_loan_account(_ABSENT[3], ADMIN_HEADERS), E.ERR_LOAN_ACCOUNT_NOT_FOUND
    )
    validate_error(api.get_project(_ABSENT[4], ADMIN_HEADERS), E.ERR_PROJECT_NOT_FOUND)
    validate_error(api.get_funding_draw(_ABSENT[5], ADMIN_HEADERS), E.ERR_DRAW_NOT_FOUND)
    validate_error(api.get_dispute_case(_ABSENT[6], ADMIN_HEADERS), E.ERR_DISPUTE_NOT_FOUND)


def test_nested_action_routes_resolve_the_child_after_a_valid_parent(api):
    """With a real parent in the path, an unknown child raises the child's own not-found code.

    PRD: "Identifiers are resolved strictly left to right, and the request fails on the first identifier that does not resolve, with the not-found code belonging to that identifier rather than to any identifier further right."

    Design: Corner/errors/every_unresolvable_identifier_returns_its_own_not_found_code
    """
    scenario = S.project(api)

    validate_error(
        api.claim_milestone(
            scenario.project_id, _ABSENT[7], F.claim_payload(), scenario.as_merchant
        ),
        E.ERR_MILESTONE_NOT_FOUND,
    )
    validate_error(
        api.investigate_fraud_alert(
            scenario.merchant_id,
            _ABSENT[8],
            F.investigation_payload("CLEARED"),
            ANALYST_HEADERS,
        ),
        E.ERR_ALERT_NOT_FOUND,
    )
    validate_error(
        api.verify_license(
            scenario.merchant_id,
            _ABSENT[9],
            F.license_verification_payload("VERIFIED"),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_LICENSE_NOT_FOUND,
    )


def test_a_real_licence_of_another_merchant_is_treated_as_unresolved(api):
    """A licence that exists but hangs off a different merchant still fails as not found.

    PRD: "Containment counts as non-resolution: a `license_id` that names a real licence belonging to a different merchant fails with `ERR_LICENSE_NOT_FOUND`, a `milestone_id` belonging to a different project fails with `ERR_MILESTONE_NOT_FOUND`, and an `alert_id` belonging to a different merchant fails with `ERR_ALERT_NOT_FOUND`."

    Design: Corner/errors/every_unresolvable_identifier_returns_its_own_not_found_code
    """
    scenario = S.approved_merchant(api)
    other = S.register_merchant(api, **C.SECOND_MERCHANT)
    other_license = S.file_license(api, other["id"], license_number="TX-RCF-77001")

    response = api.verify_license(
        scenario.merchant_id,
        other_license["id"],
        F.license_verification_payload("VERIFIED"),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, E.ERR_LICENSE_NOT_FOUND)

    assert_fields(
        validate_success(api.list_licenses(other["id"], ADMIN_HEADERS))[0],
        id=other_license["id"],
        verification_status="UNVERIFIED",
    )


def test_a_second_trade_rule_for_the_same_trade_is_refused(api):
    """A repeat trade rule is refused and the first row keeps its posture untouched.

    PRD: "Registering a second rule for a trade that already has one is refused with `ERR_DUPLICATE_TRADE_RULE`."

    Design: Corner/errors/uniqueness_and_monotonicity_violations_return_their_declared_codes
    """
    S.create_trade_rule(api)

    response = api.create_trade_rule(
        F.trade_rule_payload(max_ticket_cents=9900000), ADMIN_HEADERS
    )
    validate_error(response, E.ERR_DUPLICATE_TRADE_RULE)

    rows, meta = validate_paginated(
        api.list_trade_rules(ADMIN_HEADERS, {"trade_type": "ROOFING"})
    )
    assert meta["total_count"] == 1, "The refused write must not have added a row"
    assert_fields(rows[0], trade_type="ROOFING", max_ticket_cents=5000000)


def test_a_second_plan_with_the_same_code_is_refused(api):
    """A repeat promotion code is refused and the original product stands unchanged.

    PRD: "Each plan carries a program-wide unique `code`, refused as `ERR_DUPLICATE_PROMOTION_CODE` on a repeat, and a `promotion_type` drawn from `DEFERRED_INTEREST`, `ZERO_INTEREST_EQUAL_PAY`, `REDUCED_APR` and `STANDARD_REVOLVING`."

    Design: Corner/errors/uniqueness_and_monotonicity_violations_return_their_declared_codes
    """
    S.create_promotion_plan(api)

    response = api.create_promotion_plan(
        F.promotion_plan_payload(promotion_type="REDUCED_APR"), ADMIN_HEADERS
    )
    validate_error(response, E.ERR_DUPLICATE_PROMOTION_CODE)

    rows, meta = validate_paginated(
        api.list_promotion_plans(ADMIN_HEADERS, {"code": "DI12-ROOF"})
    )
    assert meta["total_count"] == 1, "The refused write must not have added a plan"
    assert_fields(rows[0], code="DI12-ROOF", promotion_type="DEFERRED_INTEREST")


def test_a_second_milestone_at_the_same_sequence_is_refused(api):
    """Sequence numbers are unique within one project, so the repeat is refused.

    PRD: "A milestone's `sequence_no` must be unique within its project, otherwise `ERR_DUPLICATE_MILESTONE_SEQUENCE`."

    Design: Corner/errors/uniqueness_and_monotonicity_violations_return_their_declared_codes
    """
    scenario = S.project(api)
    S.add_milestones(api, scenario, (3000,))

    response = api.create_milestone(
        scenario.project_id,
        F.milestone_payload(sequence_no=1, name="Duplicate stage", release_pct_bps=2000),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_DUPLICATE_MILESTONE_SEQUENCE)

    milestones = S.read_milestones(api, scenario.project_id)
    assert len(milestones) == 1, "The refused write must not have added a milestone"
    assert_fields(milestones[0], sequence_no=1, release_pct_bps=3000)


def test_the_clock_refuses_to_rewind_but_accepts_the_equal_instant(api):
    """A backwards clock instant is refused while the identical instant is accepted.

    PRD: "The clock is monotonic: a supplied instant that is earlier than the stored instant is rejected with `ERR_CLOCK_NOT_MONOTONIC`, while an instant equal to the stored one is accepted and leaves the clock unchanged."

    Design: Corner/errors/uniqueness_and_monotonicity_violations_return_their_declared_codes
    """
    advanced = S.set_clock(api, "2026-08-05T00:00:00Z")
    assert advanced["current_utc"].startswith("2026-08-05T00:00:00")

    response = api.set_clock(F.clock_payload("2026-08-04T23:59:59Z"), AGENT_HEADERS)
    validate_error(response, E.ERR_CLOCK_NOT_MONOTONIC)

    unchanged = validate_success(
        api.set_clock(F.clock_payload("2026-08-05T00:00:00Z"), AGENT_HEADERS)
    )
    assert unchanged["current_utc"].startswith("2026-08-05T00:00:00")
    assert unchanged["previous_utc"].startswith("2026-08-05T00:00:00")


def _pipeline_with_every_decision_taken(api):
    """One merchant carried to a settled draw, a cleared alert and a certified project.

    The draw funds 1050000 — exactly the headroom one verified milestone of 3000 basis
    points on a 3500000 contract supports — so the whole chain is at its terminal
    decision on every axis.
    """
    scenario = S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))
    alert = S.raise_fraud_alert(
        api, scenario.merchant_id, "PHANTOM_PROJECT", 20, evidence_ref="EV-PH-1"
    )
    validate_success(
        api.investigate_fraud_alert(
            scenario.merchant_id,
            alert["id"],
            F.investigation_payload("CLEARED"),
            ANALYST_HEADERS,
        )
    )
    scenario.project = validate_success(
        api.certify_completion(
            scenario.project_id, F.completion_certification_payload(), scenario.as_consumer
        )
    )
    return scenario, alert


def test_settling_an_already_settled_draw_is_refused(api):
    """A second settlement decision on a settled draw is refused and moves no money.

    PRD: "Draw state admission: a settlement decision only from `REQUESTED`, a reversal only from `SETTLED`."

    Design: Corner/errors/repeated_decisions_on_already_decided_rows_return_their_state_codes
    """
    scenario, _alert = _pipeline_with_every_decision_taken(api)
    version = S.merchant_version(api, scenario.merchant_id)

    response = api.settle_funding_draw(
        scenario.draw["id"], F.settlement_payload("SETTLE"), AGENT_HEADERS
    )
    validate_error(response, E.ERR_INVALID_DRAW_STATE)

    assert_fields(
        S.read_draw(api, scenario.draw["id"]),
        status="SETTLED",
        funded_amount_cents=1050000,
        # 1050000 - 47145 discount - 42000 holdback.
        net_settlement_cents=960855,
    )
    assert S.merchant_version(api, scenario.merchant_id) == version


def test_claiming_an_already_verified_milestone_is_refused(api):
    """A claim is admitted only from `PENDING` or `REJECTED`, so a verified milestone refuses it.

    PRD: "Milestone state admission: a claim only from `PENDING` or `REJECTED`, and a verification decision only from `CLAIMED` or — for a rescission — `VERIFIED`."

    Design: Corner/errors/repeated_decisions_on_already_decided_rows_return_their_state_codes
    """
    scenario, _alert = _pipeline_with_every_decision_taken(api)
    version = S.merchant_version(api, scenario.merchant_id)

    response = api.claim_milestone(
        scenario.project_id,
        scenario.milestone_id(0),
        F.claim_payload(),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_INVALID_MILESTONE_STATE)

    assert_fields(S.read_milestones(api, scenario.project_id)[0], status="VERIFIED")
    assert S.merchant_version(api, scenario.merchant_id) == version


def test_rescinding_the_signoff_on_a_funded_milestone_is_refused(api):
    """A milestone whose money has already been advanced cannot have its signoff rescinded.

    PRD: "A milestone becomes `is_funded` the moment a draw in `REQUESTED` or `SETTLED` status references it, so a milestone whose money has already been advanced or is already in the settlement queue cannot be rescinded — the attempt is refused with `ERR_MILESTONE_ALREADY_FUNDED`."

    Design: Corner/errors/repeated_decisions_on_already_decided_rows_return_their_state_codes
    """
    scenario, _alert = _pipeline_with_every_decision_taken(api)

    response = api.verify_milestone(
        scenario.project_id,
        scenario.milestone_id(0),
        F.milestone_verification_payload("REJECT"),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_MILESTONE_ALREADY_FUNDED)

    assert_fields(
        S.read_milestones(api, scenario.project_id)[0], status="VERIFIED", is_funded=True
    )


def test_a_second_investigation_on_a_cleared_alert_is_refused(api):
    """An investigation outcome is admitted only while the alert is still open.

    PRD: "A fraud alert must still be `OPEN` when an investigation outcome arrives, otherwise `ERR_INVALID_ALERT_STATE`."

    Design: Corner/errors/repeated_decisions_on_already_decided_rows_return_their_state_codes
    """
    scenario, alert = _pipeline_with_every_decision_taken(api)

    response = api.investigate_fraud_alert(
        scenario.merchant_id,
        alert["id"],
        F.investigation_payload("CONFIRMED"),
        ANALYST_HEADERS,
    )
    validate_error(response, E.ERR_INVALID_ALERT_STATE)

    alerts = validate_success(api.list_fraud_alerts(scenario.merchant_id, ADMIN_HEADERS))
    assert_fields(alerts[0], id=alert["id"], status="CLEARED")
    assert_fields(S.read_merchant(api, scenario.merchant_id), phantom_risk_score=0)


def test_a_second_completion_certification_is_refused(api):
    """Certification is admitted only from `IN_PROGRESS` or `SUBSTANTIALLY_COMPLETE`.

    PRD: "Project state admission: completion certification only from `IN_PROGRESS` or `SUBSTANTIALLY_COMPLETE`, and milestone, draw and dispute writes only while the project is not `ABANDONED`."

    Design: Corner/errors/repeated_decisions_on_already_decided_rows_return_their_state_codes
    """
    scenario, _alert = _pipeline_with_every_decision_taken(api)
    certified = S.read_project(api, scenario.project_id)
    assert_fields(certified, completion_status="CERTIFIED_COMPLETE")

    response = api.certify_completion(
        scenario.project_id,
        F.completion_certification_payload(completion_certificate_ref="CERT-SECOND-TRY"),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_INVALID_PROJECT_STATE)

    assert_fields(
        S.read_project(api, scenario.project_id),
        completion_certificate_ref=C.COMPLETION_CERTIFICATE_REF,
        certified_on=certified["certified_on"],
    )


def _case_resolved_in_merchant_favour(api):
    """A project with one settled draw of 1050000 and one dispute already resolved.

    The draw was released by `sa-1`, so the resolution is rendered by `sa-2` to keep
    the duty separation the program requires.
    """
    scenario = S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))
    case = S.file_dispute(api, scenario, 50000)
    validate_success(
        api.respond_to_dispute(
            case["id"],
            F.merchant_response_payload("WORK_COMPLETE_EVIDENCE"),
            scenario.as_merchant,
        )
    )
    resolved = validate_success(
        api.resolve_dispute(
            case["id"],
            F.resolution_payload("MERCHANT_FAVOR", S.merchant_version(api, scenario.merchant_id)),
            SECOND_AGENT_HEADERS,
        )
    )
    return scenario, resolved


def test_a_merchant_response_on_a_resolved_case_is_refused(api):
    """A response is admitted only while the case awaits one, so a resolved case refuses it.

    PRD: "Dispute state admission: a merchant response only from `MERCHANT_RESPONSE_PENDING`; a consumer-favour resolution from `MERCHANT_RESPONSE_PENDING` or `ESCALATED_NO_RESPONSE`; a merchant-favour resolution only from `MERCHANT_RESPONSE_PENDING` and only after a response of type `WORK_COMPLETE_EVIDENCE` has been recorded."

    Design: Corner/errors/application_and_dispute_lifecycle_violations_return_their_declared_codes
    """
    scenario, resolved = _case_resolved_in_merchant_favour(api)
    assert_fields(resolved, status="RESOLVED_MERCHANT_FAVOR")

    response = api.respond_to_dispute(
        resolved["id"],
        F.merchant_response_payload("WORK_COMPLETE_EVIDENCE"),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_INVALID_DISPUTE_STATE)

    assert_fields(
        S.read_dispute(api, resolved["id"]),
        status="RESOLVED_MERCHANT_FAVOR",
        merchant_responded_at=resolved["merchant_responded_at"],
    )


def test_a_second_acceptance_of_an_activated_offer_is_refused(api):
    """Acceptance is admitted only from `APPROVED` or `COUNTER_OFFERED`, never twice.

    PRD: "Application state admission: disclosure delivery only from `NOT_SENT` or `EXPIRED_UNACKNOWLEDGED`, acknowledgement only from `DELIVERED`, acceptance only from `APPROVED` or `COUNTER_OFFERED`, and project creation only against an `ACTIVATED` application."

    Design: Corner/errors/application_and_dispute_lifecycle_violations_return_their_declared_codes
    """
    scenario = S.activated_loan(api)

    response = api.accept_offer(
        scenario.application_id, F.acceptance_payload(), scenario.as_consumer
    )
    validate_error(response, E.ERR_INVALID_APPLICATION_STATE)

    rows, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert meta["total_count"] == 1, "One acceptance originates exactly one account"
    assert rows[0]["id"] == scenario.loan_id


def test_a_second_project_on_the_same_application_is_refused(api):
    """One activated application funds one job, so the second project is refused.

    PRD: "At most one project may exist for a given activated application, otherwise `ERR_PROJECT_ALREADY_EXISTS`."

    Design: Corner/errors/application_and_dispute_lifecycle_violations_return_their_declared_codes
    """
    scenario = S.project(api)

    response = api.create_project(
        F.project_payload(
            scenario.application_id,
            scope_description="Second roof on the same offer",
            contract_amount_cents=1000000,
        ),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_PROJECT_ALREADY_EXISTS)

    _rows, meta = validate_paginated(
        api.list_projects(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert meta["total_count"] == 1, "The refused write must not have added a project"


def test_a_dispute_claim_above_the_settled_funding_is_refused(api):
    """A homeowner cannot dispute a cent more than the program actually advanced.

    PRD: "A dispute's `claimed_incomplete_amount_cents` must not exceed the project's `settled_funded_cents`, because a consumer cannot dispute money the program never advanced; a larger claim is `ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED`."

    Design: Corner/errors/application_and_dispute_lifecycle_violations_return_their_declared_codes
    """
    scenario, _resolved = _case_resolved_in_merchant_favour(api)
    assert_fields(S.read_project(api, scenario.project_id), settled_funded_cents=1050000)

    response = api.create_dispute_case(
        F.dispute_case_payload(scenario.loan_id, scenario.project_id, 1050001),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED)


def test_a_reopen_past_the_thirty_day_window_is_refused(api):
    """A merchant-favour case may be reopened for thirty days and no longer.

    PRD: "When `reopens_case_id` is supplied it must name a case on the same project whose `status` is `RESOLVED_MERCHANT_FAVOR` and whose `resolved_on` date is no more than thirty days before the clock date, the thirty-day boundary being inclusive."

    Design: Corner/errors/application_and_dispute_lifecycle_violations_return_their_declared_codes
    """
    scenario, resolved = _case_resolved_in_merchant_favour(api)
    assert_fields(resolved, resolved_on="2026-08-01")
    # Thirty days after 2026-08-01 is 2026-08-31, so 2026-09-01 is one day too late.
    S.set_clock(api, "2026-09-01T00:00:00Z")

    response = api.create_dispute_case(
        F.dispute_case_payload(
            scenario.loan_id, scenario.project_id, 50000, reopens_case_id=resolved["id"]
        ),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_DISPUTE_NOT_REOPENABLE)


def test_a_fresh_case_opens_but_a_second_live_one_is_refused(api):
    """A new case may be filed once the old one is terminal, but only one may be live at a time.

    PRD: "No second dispute case may be opened on a project while an existing case on that project stands in a non-terminal status, meaning `SUBMITTED`, `MERCHANT_RESPONSE_PENDING` or `ESCALATED_NO_RESPONSE`."

    Design: Corner/errors/application_and_dispute_lifecycle_violations_return_their_declared_codes
    """
    scenario, _resolved = _case_resolved_in_merchant_favour(api)
    S.set_clock(api, "2026-09-01T00:00:00Z")

    fresh = validate_success(
        api.create_dispute_case(
            F.dispute_case_payload(scenario.loan_id, scenario.project_id, 60000),
            scenario.as_consumer,
        ),
        201,
    )
    assert_fields(fresh, status="MERCHANT_RESPONSE_PENDING", opened_on="2026-09-01")
    assert fresh["response_due_at"].startswith("2026-09-11T00:00:00")
    assert_empty(fresh, "reopens_case_id")

    response = api.create_dispute_case(
        F.dispute_case_payload(scenario.loan_id, scenario.project_id, 70000),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_DISPUTE_ALREADY_OPEN)

    _rows, meta = validate_paginated(
        api.list_dispute_cases(ADMIN_HEADERS, {"project_id": scenario.project_id})
    )
    assert meta["total_count"] == 2, "The refused third filing left no row"


def test_delivering_a_superseded_disclosure_template_is_refused(api):
    """Delivery must carry the plan's current template version, not a superseded one.

    PRD: "The move `NOT_SENT → DELIVERED` requires the application's `decision` to be `APPROVED` or `COUNTER_OFFERED`, and requires the supplied template version to equal the promotion plan's current `disclosure_template_version`; a mismatch is refused with `ERR_DISCLOSURE_TEMPLATE_MISMATCH`."

    Design: Corner/errors/disclosure_dimension_violations_return_their_declared_codes
    """
    scenario = S.application(api)

    response = api.deliver_disclosure(
        scenario.application_id,
        F.disclosure_delivery_payload(disclosure_template_version="DI-2026.1"),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_DISCLOSURE_TEMPLATE_MISMATCH)

    application = S.read_application(api, scenario.application_id)
    assert_fields(application, disclosure_status="NOT_SENT", decision="APPROVED")
    assert_empty(application, "disclosure_delivered_at")


def test_accepting_before_any_disclosure_was_sent_is_refused(api):
    """Credit is never extended before the terms have been acknowledged.

    PRD: "An offer may only be accepted once `disclosure_status` is `ACKNOWLEDGED`, because the deferred-interest terms must be acknowledged before credit is extended; otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Corner/errors/disclosure_dimension_violations_return_their_declared_codes
    """
    scenario = S.application(api)

    response = api.accept_offer(
        scenario.application_id, F.acceptance_payload(), scenario.as_consumer
    )
    validate_error(response, E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)

    assert_fields(
        S.read_application(api, scenario.application_id),
        decision="APPROVED",
        disclosure_status="NOT_SENT",
    )


def test_acknowledging_exactly_three_days_after_delivery_succeeds(api):
    """The three-day acknowledgement boundary is inclusive, so the last instant still lands.

    PRD: "The move `DELIVERED → ACKNOWLEDGED` requires the disclosure to be standing at `DELIVERED` and requires the clock to be no later than three days after `disclosure_delivered_at`, the three-day boundary being inclusive; a later attempt is refused with `ERR_DISCLOSURE_WINDOW_EXPIRED`."

    Design: Corner/errors/disclosure_dimension_violations_return_their_declared_codes
    """
    scenario = S.disclosed_application(api, acknowledge=False)
    assert scenario.application["disclosure_delivered_at"].startswith("2026-08-01T00:00:00")
    S.set_clock(api, "2026-08-04T00:00:00Z")

    application = validate_success(
        api.acknowledge_disclosure(
            scenario.application_id,
            F.disclosure_acknowledgement_payload(),
            scenario.as_consumer,
        )
    )
    assert_fields(application, disclosure_status="ACKNOWLEDGED")
    assert application["disclosure_acknowledged_at"].startswith("2026-08-04T00:00:00")


def test_acknowledging_one_day_past_the_window_is_refused(api):
    """One day beyond the inclusive boundary the acknowledgement is refused outright.

    PRD: "An acknowledgement must arrive no later than three days after `disclosure_delivered_at`, the boundary being inclusive; later than that is `ERR_DISCLOSURE_WINDOW_EXPIRED`."

    Design: Corner/errors/disclosure_dimension_violations_return_their_declared_codes
    """
    scenario = S.disclosed_application(api, acknowledge=False)
    S.set_clock(api, "2026-08-05T00:00:00Z")

    response = api.acknowledge_disclosure(
        scenario.application_id,
        F.disclosure_acknowledgement_payload(),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_DISCLOSURE_WINDOW_EXPIRED)

    # Only the operations checkpoint writes EXPIRED_UNACKNOWLEDGED; a refused
    # acknowledgement leaves the disclosure exactly where delivery left it.
    assert_fields(
        S.read_application(api, scenario.application_id), disclosure_status="DELIVERED"
    )


def _counter_offered_application(api):
    """An acknowledged application counter-offered down to the tier ceiling of 1500000.

    A 620 score sits in the lowest lending tier: the income factor yields
    9600000 * 2000 / 10000 == 1920000 but the tier's own cap of 1500000 binds, and
    the 1600000 ticket therefore exceeds the ceiling.
    """
    scenario = S.enrolled_merchant(api)
    consumer = S.register_consumer(
        api,
        scenario.merchant_id,
        full_name="Rita Vance",
        ssn_last4="3311",
        fico_score=620,
        annual_income_cents=9600000,
    )
    application = validate_success(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id,
                consumer["id"],
                scenario.plan_id,
                project_amount_cents=1600000,
            ),
            scenario.as_merchant,
        ),
        201,
    )
    validate_success(
        api.deliver_disclosure(
            application["id"], F.disclosure_delivery_payload(), scenario.as_merchant
        )
    )
    validate_success(
        api.acknowledge_disclosure(
            application["id"],
            F.disclosure_acknowledgement_payload(),
            consumer_headers(consumer["id"]),
        )
    )
    return scenario, consumer, application


def test_a_counter_offer_cannot_be_accepted_without_the_explicit_flag(api):
    """A bare acceptance of a counter-offered application is refused for want of the flag.

    PRD: "`COUNTER_OFFERED → ACTIVATED` carries exactly the same disclosure, offer-window, merchant-posture and debt-to-income preconditions, and adds one of its own: `accept_counter_offer` must be supplied as true, and an attempt to accept a counter-offered application without it is refused with `ERR_COUNTER_OFFER_NOT_ACCEPTED`."

    Design: Corner/errors/offer_expiry_and_counter_offer_acceptance_return_their_declared_codes
    """
    _scenario, consumer, application = _counter_offered_application(api)
    assert_fields(
        application,
        decision="COUNTER_OFFERED",
        approved_limit_cents=1500000,
        # 1600000 * 10000 / 9600000 == 1666.66..., rounded half up to 1667.
        decision_dti_bps=round_half_up(1600000 * 10000, 9600000),
        decision_reason_codes=["LIMIT_BELOW_TICKET"],
    )

    response = api.accept_offer(
        application["id"], F.acceptance_payload(), consumer_headers(consumer["id"])
    )
    validate_error(response, E.ERR_COUNTER_OFFER_NOT_ACCEPTED)

    _rows, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": application["id"]})
    )
    assert meta["total_count"] == 0, "A refused acceptance originates no account"


def test_a_counter_offer_activates_at_the_counter_amount(api):
    """With the flag supplied the offer activates, and the line is the counter-offered ceiling.

    PRD: "Its `credit_limit_cents` is a frozen copy of the application's `approved_limit_cents` — which, on a counter-offered origination, is the counter-offered ceiling and therefore sits below the ticket the homeowner originally asked to finance."

    Design: Corner/errors/offer_expiry_and_counter_offer_acceptance_return_their_declared_codes
    """
    _scenario, consumer, application = _counter_offered_application(api)

    accepted = validate_success(
        api.accept_offer(
            application["id"],
            F.acceptance_payload(accept_counter_offer=True),
            consumer_headers(consumer["id"]),
        )
    )
    assert_fields(accepted, decision="ACTIVATED")

    rows, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": application["id"]})
    )
    assert meta["total_count"] == 1
    assert_fields(rows[0], credit_limit_cents=1500000, consumer_id=consumer["id"])


def test_accepting_after_the_offer_window_closed_is_refused(api):
    """One day past `offer_expires_at` the acceptance is refused and no account is born.

    PRD: "Acceptance must occur at or before `offer_expires_at`, the boundary being inclusive; later is `ERR_OFFER_EXPIRED`."

    Design: Corner/errors/offer_expiry_and_counter_offer_acceptance_return_their_declared_codes
    """
    scenario = S.disclosed_application(api)
    assert scenario.application["offer_expires_at"].startswith("2026-08-15T00:00:00")
    S.set_clock(api, "2026-08-16T00:00:00Z")

    response = api.accept_offer(
        scenario.application_id, F.acceptance_payload(), scenario.as_consumer
    )
    validate_error(response, E.ERR_OFFER_EXPIRED)

    assert_fields(S.read_application(api, scenario.application_id), decision="APPROVED")
    _rows, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert meta["total_count"] == 0, "The refused acceptance originated nothing"


def _submitted_hvac_merchant(api):
    """A submitted HVAC merchant holding a verified HVAC licence through 2028-06-30."""
    merchant = S.register_merchant(
        api,
        legal_name="Bluebonnet Air LLC",
        trade_type="HVAC",
        contact_email="ops@bluebonnetair.example",
    )
    license_ = S.file_license(
        api,
        merchant["id"],
        trade_type="HVAC",
        license_number="TX-HVAC-40551",
        expires_on="2028-06-30",
    )
    S.verify_license(api, merchant["id"], license_["id"])
    S.submit_enrollment(api, merchant["id"])
    return merchant


def test_approving_a_merchant_whose_trade_has_no_rule_is_refused(api):
    """Enrollment approval needs the trade rule governing the merchant's own trade to exist.

    PRD: "Last in this group, whenever an operation is about to apply a trade-specific program rule — merchant enrollment approval, the ticket ceiling on a point-of-sale application, or a draw settlement — the trade rule row governing the acting merchant's trade must exist, and its absence is reported as `ERR_TRADE_RULE_NOT_FOUND`."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    S.program(api)
    merchant = _submitted_hvac_merchant(api)

    response = api.decide_enrollment(
        merchant["id"], F.enrollment_decision_payload("APPROVE"), UNDERWRITER_HEADERS
    )
    validate_error(response, E.ERR_TRADE_RULE_NOT_FOUND)

    assert_fields(S.read_merchant(api, merchant["id"]), enrollment_status="PENDING_REVIEW")


def test_enrolling_in_a_plan_that_excludes_the_merchant_trade_is_refused(api):
    """A roofer may not enroll in a solar-only product.

    PRD: "The merchant's `trade_type` must be a member of the plan's `allowed_trade_types`, otherwise `ERR_TRADE_NOT_ELIGIBLE`."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    scenario = S.approved_merchant(api)
    solar_plan = S.create_promotion_plan(api, **C.SOLAR_ONLY_PLAN)

    response = api.create_promotion_enrollment(
        scenario.merchant_id,
        F.promotion_enrollment_payload(solar_plan["id"]),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, E.ERR_TRADE_NOT_ELIGIBLE)


def test_an_enrollment_window_starting_before_approval_is_refused(api):
    """A window may not reach back behind the day the merchant was approved.

    PRD: "An enrollment window may not begin before the merchant was approved: `window_start_date` must fall on or after the calendar date of the merchant's `approved_on` instant, otherwise `ERR_ENROLLMENT_WINDOW_BEFORE_APPROVAL`."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    scenario = S.approved_merchant(api)
    assert S.read_merchant(api, scenario.merchant_id)["approved_on"].startswith("2026-08-01")

    response = api.create_promotion_enrollment(
        scenario.merchant_id,
        F.promotion_enrollment_payload(scenario.plan_id, window_start_date="2026-07-01"),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, E.ERR_ENROLLMENT_WINDOW_BEFORE_APPROVAL)


def test_an_inverted_enrollment_window_is_a_date_range_failure(api):
    """A window that ends before it starts fails on payload coherence, not on approval timing.

    PRD: "Date-range coherence inside a single payload: a licence must have `effective_from` strictly earlier than `expires_on`, because the interval is half-open and equal dates would describe an empty coverage period; an enrollment must have `window_start_date` earlier than or equal to `window_end_date`, because the interval is closed and equal dates describe a legitimate one-day window."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    scenario = S.approved_merchant(api)

    response = api.create_promotion_enrollment(
        scenario.merchant_id,
        F.promotion_enrollment_payload(
            scenario.plan_id, window_start_date="2026-12-31", window_end_date="2026-08-01"
        ),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, E.ERR_INVALID_DATE_RANGE)


def test_a_licence_covering_no_days_at_all_is_a_date_range_failure(api):
    """Licence coverage is half-open, so equal endpoints describe an empty period.

    PRD: "Date-range coherence inside a single payload: a licence must have `effective_from` strictly earlier than `expires_on`, because the interval is half-open and equal dates would describe an empty coverage period; an enrollment must have `window_start_date` earlier than or equal to `window_end_date`, because the interval is closed and equal dates describe a legitimate one-day window."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    scenario = S.approved_merchant(api)

    response = api.file_license(
        scenario.merchant_id,
        F.license_payload(
            license_number="TX-RCF-99001",
            effective_from="2027-07-01",
            expires_on="2027-07-01",
        ),
        ADMIN_HEADERS,
    )
    validate_error(response, E.ERR_INVALID_DATE_RANGE)

    licenses = validate_success(api.list_licenses(scenario.merchant_id, ADMIN_HEADERS))
    assert len(licenses) == 1, "The refused filing must not have created a licence"


def test_point_of_sale_without_an_active_enrollment_is_refused(api):
    """A merchant may not sell a plan it never enrolled in.

    PRD: "At point of sale, the named `promotion_plan_id` must have an enrollment for this merchant whose `status` is `ACTIVE` and whose closed window from `window_start_date` through `window_end_date` contains the clock date, otherwise `ERR_PROMOTION_NOT_ENROLLED`; and the merchant must still hold a licence whose `verification_status` is `VERIFIED` — not one swept to `EXPIRED` — for its own `trade_type` and `state_code`, otherwise `ERR_LICENSE_EXPIRED`."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    scenario = S.approved_merchant(api)
    consumer = S.register_consumer(api, scenario.merchant_id)

    response = api.create_credit_application(
        F.credit_application_payload(
            scenario.merchant_id, consumer["id"], scenario.plan_id
        ),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_PROMOTION_NOT_ENROLLED)

    _rows, meta = validate_paginated(
        api.list_credit_applications(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id})
    )
    assert meta["total_count"] == 0, "The refused application left no row"


def test_point_of_sale_after_the_licence_is_swept_expired_is_refused(api):
    """Once the checkpoint expires the covering licence, the same enrolled sale fails on the licence.

    PRD: "A licence moves `VERIFIED → EXPIRED` once the clock date has reached or passed its `expires_on`, the half-open coverage interval having closed."

    Design: Corner/errors/enrollment_and_licensing_eligibility_violations_return_their_declared_codes
    """
    scenario = S.approved_merchant(api)
    enrollment = S.enroll_in_promotion(
        api, scenario.merchant_id, scenario.plan_id, window_end_date="2027-12-31"
    )
    assert_fields(enrollment, status="ACTIVE", window_end_date="2027-12-31")
    consumer = S.register_consumer(api, scenario.merchant_id)

    S.set_clock(api, "2027-06-30T00:00:00Z")
    assert_fields(
        S.run_sweep(api),
        expired_licenses=1,
        expired_offers=0,
        expired_disclosures=0,
        capitalized_loans=0,
        delinquent_loans=0,
        charged_off_loans=0,
        escalated_disputes=0,
    )

    response = api.create_credit_application(
        F.credit_application_payload(
            scenario.merchant_id, consumer["id"], scenario.plan_id
        ),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_LICENSE_EXPIRED)


def _second_borrower_on_the_same_merchant(api, scenario, ticket_cents, scope):
    """A second homeowner of the same merchant, activated and holding an open project.

    The homeowner states the same 9600000 income and 742 score as the canonical one, so
    the ceiling is again 9600000 * 4500 / 10000 == 4320000 and the ticket fits inside it.
    """
    consumer = S.register_consumer(
        api, scenario.merchant_id, full_name="Owen Pratt", ssn_last4="2210"
    )
    application = validate_success(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id,
                consumer["id"],
                scenario.plan_id,
                project_amount_cents=ticket_cents,
            ),
            scenario.as_merchant,
        ),
        201,
    )
    validate_success(
        api.deliver_disclosure(
            application["id"], F.disclosure_delivery_payload(), scenario.as_merchant
        )
    )
    validate_success(
        api.acknowledge_disclosure(
            application["id"],
            F.disclosure_acknowledgement_payload(),
            consumer_headers(consumer["id"]),
        )
    )
    validate_success(
        api.accept_offer(
            application["id"], F.acceptance_payload(), consumer_headers(consumer["id"])
        )
    )
    loan = validate_success(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": application["id"]})
    )[0]
    project = validate_success(
        api.create_project(
            F.project_payload(
                application["id"],
                contract_amount_cents=ticket_cents,
                scope_description=scope,
            ),
            scenario.as_merchant,
        ),
        201,
    )
    return consumer, loan, project


def test_a_contract_above_the_frozen_credit_limit_is_refused(api):
    """A signed contract worth one cent more than the credit line cannot be opened.

    PRD: "A project's `contract_amount_cents` must not exceed the funding account's `credit_limit_cents`, otherwise `ERR_CONTRACT_EXCEEDS_CREDIT_LIMIT`."

    Design: Corner/errors/fiscal_ceiling_violations_return_their_declared_codes
    """
    scenario = S.activated_loan(api)
    assert_fields(S.read_loan(api, scenario.loan_id), credit_limit_cents=4320000)

    response = api.create_project(
        F.project_payload(scenario.application_id, contract_amount_cents=4320001),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_CONTRACT_EXCEEDS_CREDIT_LIMIT)

    _rows, meta = validate_paginated(
        api.list_projects(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert meta["total_count"] == 0, "The refused write must not have opened a project"


def test_a_contract_exactly_at_the_credit_limit_is_accepted(api):
    """The ceiling is inclusive, so a contract equal to the line opens normally.

    PRD: "A project's `contract_amount_cents` must not exceed the funding account's `credit_limit_cents`, otherwise `ERR_CONTRACT_EXCEEDS_CREDIT_LIMIT`."

    Design: Corner/errors/fiscal_ceiling_violations_return_their_declared_codes
    """
    scenario = S.activated_loan(api)

    project = validate_success(
        api.create_project(
            F.project_payload(scenario.application_id, contract_amount_cents=4320000),
            scenario.as_merchant,
        ),
        201,
    )
    assert_fields(
        project,
        contract_amount_cents=4320000,
        loan_account_id=scenario.loan_id,
        merchant_id=scenario.merchant_id,
    )


def test_a_draw_naming_another_loans_milestone_is_refused(api):
    """A draw must debit the very account its milestone's project funds.

    PRD: "Cross-aggregate coherence of a draw: the `loan_account_id` recorded on the project behind the named milestone must equal the `loan_account_id` on the draw, otherwise `ERR_MILESTONE_PROJECT_MISMATCH`."

    Design: Corner/errors/fiscal_ceiling_violations_return_their_declared_codes
    """
    scenario = S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))
    consumer, _loan, project = _second_borrower_on_the_same_merchant(
        api, scenario, 1000000, "Attic insulation and air sealing"
    )
    milestone = validate_success(
        api.create_milestone(
            project["id"],
            F.milestone_payload(sequence_no=1, name="Rough-in", release_pct_bps=3000),
            scenario.as_merchant,
        ),
        201,
    )
    validate_success(
        api.claim_milestone(
            project["id"], milestone["id"], F.claim_payload(), scenario.as_merchant
        )
    )
    validate_success(
        api.verify_milestone(
            project["id"],
            milestone["id"],
            F.milestone_verification_payload("VERIFY"),
            consumer_headers(consumer["id"]),
        )
    )

    response = api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id, milestone["id"], 100000, S.loan_version(api, scenario.loan_id)
        ),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_MILESTONE_PROJECT_MISMATCH)

    _rows, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert meta["total_count"] == 1, "Only the original settled draw exists"


def test_a_payment_above_the_payoff_ceiling_is_refused(api):
    """Overpayment is gated before either allocation bucket is written.

    PRD: "A payment's `amount_cents` must not exceed the sum of the account's `capitalized_interest_cents` and `principal_balance_cents`, otherwise `ERR_PAYMENT_EXCEEDS_PAYOFF`."

    Design: Corner/errors/fiscal_ceiling_violations_return_their_declared_codes
    """
    scenario = S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=1050000,
        capitalized_interest_cents=0,
    )

    response = api.create_payment(
        F.payment_payload(scenario.loan_id, 1050001), scenario.as_consumer
    )
    validate_error(response, E.ERR_PAYMENT_EXCEEDS_PAYOFF)

    assert_fields(S.read_loan(api, scenario.loan_id), principal_balance_cents=1050000)


def test_a_payment_exactly_at_the_payoff_ceiling_closes_the_loan(api):
    """A payment of the whole ceiling wins the deferred-interest wager and closes the account.

    PRD: "If the payment brings `principal_balance_cents` to zero on or before `promo_expires_on` — the boundary being inclusive, so a payment posted on the expiration date itself still wins the wager — the promotional dimension moves `PROMO_ACTIVE → PROMO_SATISFIED`: `waived_interest_cents` is written with the accrual standing at that instant, `accrued_deferred_interest_cents` and `deferred_interest_at_risk_cents` both drop to zero, `capitalized_interest_cents` stays at zero, and the repayment dimension moves `CURRENT → PAID_OFF`, with the consumer's `existing_program_debt_cents` and `active_loan_count` recomputed."

    Design: Corner/errors/fiscal_ceiling_violations_return_their_declared_codes
    """
    scenario = S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))

    validate_success(
        api.create_payment(
            F.payment_payload(scenario.loan_id, 1050000), scenario.as_consumer
        ),
        201,
    )

    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=0,
        balance_status="PAID_OFF",
        promo_status="PROMO_SATISFIED",
        capitalized_interest_cents=0,
        accrued_deferred_interest_cents=0,
        deferred_interest_at_risk_cents=0,
        # Funding and payoff fall on the same clock date, so nothing had accrued yet.
        waived_interest_cents=0,
    )
    assert_fields(
        validate_success(api.get_consumer(scenario.consumer_id, ADMIN_HEADERS)),
        existing_program_debt_cents=0,
        active_loan_count=0,
    )


def _acknowledged_second_offer_behind_a_funded_loan(api):
    """One homeowner with a funded first loan and a second offer already acknowledged.

    The second application is filed while the first account still carries no principal,
    so it is decided at 3646 basis points and stands `APPROVED`. Only afterwards does the
    first draw settle and put 1050000 of principal on the books.
    """
    scenario = S.activated_loan(api)
    second = validate_success(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id, scenario.consumer_id, scenario.plan_id
            ),
            scenario.as_merchant,
        ),
        201,
    )
    assert_fields(second, decision="APPROVED", decision_dti_bps=3646)
    validate_success(
        api.deliver_disclosure(
            second["id"], F.disclosure_delivery_payload(), scenario.as_merchant
        )
    )
    validate_success(
        api.acknowledge_disclosure(
            second["id"], F.disclosure_acknowledgement_payload(), scenario.as_consumer
        )
    )
    scenario = S.project(api, scenario)
    scenario = S.project_with_milestones(api, scenario, releases=(3000,), verify=(0,))
    S.request_draw(api, scenario, 1050000)
    S.settle_draw(api, scenario)
    return scenario, second


def test_a_settled_draw_becomes_the_consumers_program_debt(api):
    """Settled principal shows up immediately as the homeowner's program debt.

    PRD: "Both figures are maintained by the program rather than supplied: `existing_program_debt_cents` is the sum, over every loan account of that consumer whose `balance_status` is neither `PAID_OFF` nor `CHARGED_OFF`, of the account's `principal_balance_cents` plus its `capitalized_interest_cents`; `active_loan_count` counts that consumer's accounts whose `balance_status` is `CURRENT` or `DELINQUENT`."

    Design: Corner/errors/acceptance_time_dti_recomputation_breach_returns_its_declared_code
    """
    scenario, _second = _acknowledged_second_offer_behind_a_funded_loan(api)

    assert_fields(
        validate_success(api.get_consumer(scenario.consumer_id, ADMIN_HEADERS)),
        existing_program_debt_cents=1050000,
        active_loan_count=1,
    )


def test_acceptance_is_refused_and_the_offer_revoked_once_debt_breaches_the_ratio(api):
    """The ratio is recomputed at acceptance, so an offer approved earlier is now unaffordable.

    PRD: "At acceptance the debt-to-income ratio is recomputed against the consumer's current `existing_program_debt_cents` and must remain no greater than four thousand five hundred basis points; a breach is `ERR_DTI_LIMIT_EXCEEDED` and revokes the offer rather than activating it."

    Design: Corner/errors/acceptance_time_dti_recomputation_breach_returns_its_declared_code
    """
    scenario, second = _acknowledged_second_offer_behind_a_funded_loan(api)
    # (1050000 + 3500000) * 10000 / 9600000 == 4739.58..., rounded half up to 4740.
    assert round_half_up((1050000 + 3500000) * 10000, 9600000) == 4740

    response = api.accept_offer(
        second["id"], F.acceptance_payload(), scenario.as_consumer
    )
    validate_error(response, E.ERR_DTI_LIMIT_EXCEEDED)

    revoked = S.read_application(api, second["id"])
    assert_fields(revoked, decision="REVOKED", disclosure_status="ACKNOWLEDGED")
    assert "REVOKED_DTI_BREACH" in revoked["decision_reason_codes"]

    _rows, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"consumer_id": scenario.consumer_id})
    )
    assert meta["total_count"] == 1, "The breached acceptance originated no second account"
