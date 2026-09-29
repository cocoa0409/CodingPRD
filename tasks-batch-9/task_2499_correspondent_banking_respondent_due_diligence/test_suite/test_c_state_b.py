"""Corner queue - section state_machines, part B: preconditions and repeat transitions."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    ApiErrorId,
    assert_instant_equals,
    dispatch_request,
    licensed_respondent,
    make_respondent_headers,
    new_jurisdiction,
    new_respondent,
    open_questionnaire,
    raise_request,
    read_respondent,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, OFFICER


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _prospect():
    _de()
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def _verified():
    _de()
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def test_submission_with_seven_control_domains_rejected_as_incomplete(api):
    """Seven of the eight domains is the off-by-one boundary of the completeness rule: the
    submission is refused and the questionnaire keeps its draft identity.

    Design: Corner/state_machines/submission_with_seven_control_domains_rejected_as_incomplete
    """
    rid = _verified()["id"]
    questionnaire = open_questionnaire(rid)
    for domain in CONTROL_DOMAIN_ORDER:
        if domain == "NESTED_CONTROLS":
            continue
        validate_success(
            api.create_control_assessment(
                questionnaire["id"], {"control_domain": domain, "self_rating": 4}, ANALYST
            ),
            expected_status=201,
        )

    response = api.submit_questionnaire(questionnaire["id"], {}, make_respondent_headers(rid))
    validate_error(response, ApiErrorId.ERR_CONTROL_DOMAINS_INCOMPLETE)

    stored = validate_success(api.get_questionnaire(questionnaire["id"], ANALYST))
    assert stored["state"] == "DRAFT"
    assert stored["submitted_at"] is None


def test_duplicate_control_domain_for_same_questionnaire_rejected(api):
    """The questionnaire-plus-domain pair is unique, so a second GOVERNANCE row is a
    duplicate rather than an overwrite and the first row's rating survives.

    Design: Corner/state_machines/duplicate_control_domain_for_same_questionnaire_rejected
    """
    rid = _verified()["id"]
    questionnaire = open_questionnaire(rid)
    first = validate_success(
        api.create_control_assessment(
            questionnaire["id"], {"control_domain": "GOVERNANCE", "self_rating": 4}, ANALYST
        ),
        expected_status=201,
    )

    response = api.create_control_assessment(
        questionnaire["id"],
        {"control_domain": "GOVERNANCE", "self_rating": 2},
        make_respondent_headers(rid),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    stored = validate_success(api.get_control_assessment(first["id"], ANALYST))
    assert stored["self_rating"] == 4

    _rows, meta = validate_paginated(
        api.list_control_assessments(ANALYST, params={"questionnaire_id": questionnaire["id"]})
    )
    assert meta["total_count"] == 1


def test_invalid_transition_respondent_approval_from_prospect_rejected(api):
    """The committee decision has exactly one legal source state, so a never-assessed
    PROSPECT is refused and no approval stamp is written.

    Design: Corner/state_machines/invalid_transition_respondent_approval_from_prospect_rejected
    """
    rid = _prospect()["id"]

    response = api.decide_committee(
        rid, {"action": "APPROVE", "decision_note": "premature"}, COMMITTEE
    )
    validate_error(response, ApiErrorId.ERR_INVALID_RESPONDENT_STATE)

    stored = read_respondent(rid)
    assert stored["dd_state"] == "PROSPECT"
    assert stored["last_approved_at"] is None


def test_invalid_transition_rfi_response_before_dispatch_rejected(api):
    """A request that was never dispatched has no answerable state, so the respondent's
    reply is refused and the response stamp stays empty.

    Design: Corner/state_machines/invalid_transition_rfi_response_before_dispatch_rejected
    """
    rid = _verified()["id"]
    request = raise_request(rid, request_topic="LICENSING_EVIDENCE", severity="MEDIUM")

    response = api.respond_request(
        request["id"], {"response_note": "Documents attached."}, make_respondent_headers(rid)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_RFI_STATE)

    stored = validate_success(api.get_information_request(request["id"], ANALYST))
    assert stored["state"] == "DRAFT"
    assert stored["responded_at"] is None


def test_idempotency_second_rfi_dispatch_rejected(api):
    """Dispatch is a once-only transition: the second call is refused and, critically, does
    not re-stamp the dispatch instant or recompute the deadline from the newer clock.

    Design: Corner/state_machines/idempotency_second_rfi_dispatch_rejected
    """
    rid = _verified()["id"]
    request = raise_request(rid, request_topic="OWNERSHIP_EVIDENCE", severity="HIGH")
    dispatch_request(request["id"])
    set_clock("2026-08-02T00:00:00Z")

    response = api.dispatch_request(request["id"], {}, OFFICER)
    validate_error(response, ApiErrorId.ERR_INVALID_RFI_STATE)

    stored = validate_success(api.get_information_request(request["id"], ANALYST))
    assert stored["state"] == "SENT"
    assert_instant_equals(stored["dispatched_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(stored["due_at"], "2026-08-04T00:00:00Z")
