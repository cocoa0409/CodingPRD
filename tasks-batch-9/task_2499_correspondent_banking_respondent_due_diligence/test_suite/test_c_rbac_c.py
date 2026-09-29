"""Corner queue - section rbac, part C: the remaining segregation-of-duties pairs."""
from test_helpers import (
    ANALYST_ID,
    ANALYST_ID_2,
    COMMITTEE_ID,
    CONTROL_DOMAIN_ORDER,
    RM_ID,
    RM_ID_2,
    ApiErrorId,
    add_control_rows,
    adjudicate_request,
    build_user_headers,
    dispatch_request,
    dispose_alert,
    draft_plan,
    make_respondent_headers,
    new_jurisdiction,
    open_questionnaire,
    raise_alert,
    read_alert,
    read_plan,
    read_request,
    read_respondent,
    setup_approved_respondent,
    setup_pending_committee,
    submit_questionnaire,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_the_assessor_may_not_be_the_identity_that_scored_the_respondent(api):
    """The forbidden identity here is the entity-backed contact id, so a perfectly legitimate
    analyst role header is refused when it carries the respondent's own id, and the refusal
    consumes no clarification round and mirrors no score onto the respondent.

    Design: Corner/rbac/the_assessor_may_not_be_the_respondent_that_submitted_the_questionnaire
    """
    _de()
    bundle = setup_pending_committee(
        "DE", self_ratings={domain: 4 for domain in CONTROL_DOMAIN_ORDER},
        legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    assert bundle["respondent"]["control_score"] == 80.00

    questionnaire = open_questionnaire(rid)
    add_control_rows(questionnaire["id"], rid)
    submitted = submit_questionnaire(questionnaire["id"], rid)
    assert submitted["state"] == "SUBMITTED"

    impersonating = build_user_headers(rid, "ComplianceAnalyst")
    validate_error(
        api.decide_assessment(
            questionnaire["id"],
            {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"},
            impersonating,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        expected_status=409,
    )

    refused = validate_success(api.get_questionnaire(questionnaire["id"], ANALYST))
    assert refused["state"] == "SUBMITTED"
    assert refused["assessed_at"] is None
    assert refused["computed_control_score"] is None
    assert refused["clarification_rounds"] == 0
    assert read_respondent(rid)["control_score"] == 80.00

    assessed = validate_success(
        api.decide_assessment(
            questionnaire["id"],
            {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"},
            ANALYST,
        )
    )
    assert assessed["state"] == "ASSESSED"
    assert assessed["control_score_variant"] == "ONBOARDING_PROVISIONAL"
    assert assessed["assessed_by_user_id"] == ANALYST_ID
    assert assessed["computed_control_score"] == 60.00
    assert read_respondent(rid)["control_score"] == 60.00


def test_the_plan_approver_may_not_be_the_identity_that_drafted_it(api):
    """The drafter cannot set its own release budget, and a second relationship-manager identity
    is refused with the role 403 rather than the duties 409, which pins the two gates apart.

    Design: Corner/rbac/the_plan_approver_may_not_be_the_identity_that_drafted_it
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=1000.00, expected_monthly_count=10,
    )
    rid = bundle["respondent"]["id"]
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )
    assert plan["drafted_by_user_id"] == RM_ID
    assert submit_plan(plan["id"])["state"] == "PENDING_APPROVAL"

    validate_error(
        api.approve_closure_plan(
            plan["id"], {"action": "APPROVE"}, build_user_headers(RM_ID, "CommitteeApprover")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        expected_status=409,
    )
    validate_error(
        api.approve_closure_plan(
            plan["id"], {"action": "APPROVE"},
            build_user_headers(RM_ID_2, "FIGRelationshipManager"),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    refused = read_plan(plan["id"])
    assert refused["state"] == "PENDING_APPROVAL"
    assert refused["approved_by_user_id"] is None

    approved = validate_success(
        api.approve_closure_plan(
            plan["id"], {"action": "APPROVE"},
            build_user_headers(COMMITTEE_ID, "CommitteeApprover"),
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["approved_by_user_id"] == COMMITTEE_ID
    assert approved["notice_period_days"] == 90
    assert approved["wind_down_cap_usd"] == 1800.00


def test_the_alert_disposer_may_not_be_the_identity_that_adjudicated_its_request(api):
    """The forbidden identity is reached by following the request's alert link backwards, so two
    analyst identities that are interchangeable everywhere else are not interchangeable here.

    Design: Corner/rbac/the_alert_disposer_may_not_be_the_identity_that_adjudicated_its_information_request
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    analyst_two = build_user_headers(ANALYST_ID_2, "ComplianceAnalyst")

    alert = raise_alert(rid, "VOLUME_BREACH", "MEDIUM")
    assert alert["state"] == "OPEN"
    investigating = dispose_alert(alert["id"], "INVESTIGATE", headers=analyst_two)
    assert investigating["state"] == "UNDER_INVESTIGATION"
    assert investigating["investigated_by_user_id"] == ANALYST_ID_2

    request = validate_success(
        api.create_information_request(
            rid,
            {"request_topic": "ACTIVITY_EXPLANATION", "severity": "MEDIUM",
             "monitoring_alert_id": alert["id"]},
            ANALYST,
        ),
        expected_status=201,
    )
    assert dispatch_request(request["id"])["state"] == "SENT"
    responded = validate_success(
        api.respond_request(
            request["id"], {"response_note": "Volumes explained."},
            make_respondent_headers(rid),
        )
    )
    assert responded["state"] == "RESPONDED"
    adjudicated = adjudicate_request(request["id"], "ACCEPT", headers=ANALYST)
    assert adjudicated["state"] == "ACCEPTED"
    assert adjudicated["adjudicated_by_user_id"] == ANALYST_ID
    assert read_request(request["id"])["monitoring_alert_id"] == alert["id"]

    validate_error(
        api.dispose_alert(
            alert["id"],
            {"action": "CLOSE_FALSE_POSITIVE", "disposition_reason": "RESPONDENT_EXPLAINED"},
            ANALYST,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        expected_status=409,
    )
    validate_error(
        api.dispose_alert(alert["id"], {"action": "ESCALATE"}, ANALYST),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        expected_status=409,
    )

    untouched = read_alert(alert["id"])
    assert untouched["state"] == "UNDER_INVESTIGATION"
    assert untouched["investigated_by_user_id"] == ANALYST_ID_2

    closed = validate_success(
        api.dispose_alert(
            alert["id"],
            {"action": "CLOSE_FALSE_POSITIVE", "disposition_reason": "RESPONDENT_EXPLAINED"},
            analyst_two,
        )
    )
    assert closed["state"] == "CLOSED_FALSE_POSITIVE"
    assert closed["disposition_reason"] == "RESPONDENT_EXPLAINED"
