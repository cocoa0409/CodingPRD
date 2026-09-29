"""Corner queue - section rbac, part B: the respondent contact and segregation of duties."""
from test_helpers import (
    ANALYST_ID,
    COMMITTEE_ID,
    CONTROL_DOMAIN_ORDER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_control_rows,
    add_verified_owner,
    assessed_questionnaire,
    assert_instant_equals,
    build_user_headers,
    licensed_respondent,
    make_respondent_headers,
    new_jurisdiction,
    questionnaire_payload,
    read_request,
    read_respondent,
    respondent_version,
    score_respondent,
    setup_sent_request,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_questionnaire_submission_and_rfi_response_belong_to_the_respondent_contact(api):
    """The analyst that opened the questionnaire, populated all eight domains and dispatched the
    request is still refused both attestations, so authorship confers no right to attest.

    Design: Corner/rbac/questionnaire_submission_and_rfi_response_belong_to_the_respondent_contact
    """
    _de()
    bundle = setup_sent_request(
        severity="MEDIUM", topic="ACTIVITY_EXPLANATION", jurisdiction_code="DE",
        legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    request_id = bundle["request"]["id"]
    questionnaire = validate_success(
        api.create_questionnaire(
            rid, questionnaire_payload(respondent_version(rid)), ANALYST
        ),
        expected_status=201,
    )
    assert questionnaire["state"] == "DRAFT"
    add_control_rows(questionnaire["id"], rid)

    validate_error(
        api.submit_questionnaire(questionnaire["id"], {}, ANALYST),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.submit_questionnaire(questionnaire["id"], {}, ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.respond_request(
            request_id, {"response_note": "Explanation attached."}, ANALYST
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    still_draft = validate_success(api.get_questionnaire(questionnaire["id"], ANALYST))
    assert still_draft["state"] == "DRAFT"
    assert still_draft["submitted_at"] is None
    still_sent = read_request(request_id)
    assert still_sent["state"] == "SENT"
    assert still_sent["responded_at"] is None

    contact = make_respondent_headers(rid)
    submitted = validate_success(api.submit_questionnaire(questionnaire["id"], {}, contact))
    assert submitted["state"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z")

    responded = validate_success(
        api.respond_request(request_id, {"response_note": "Explanation attached."}, contact)
    )
    assert responded["state"] == "RESPONDED"
    assert_instant_equals(responded["responded_at"], "2026-08-01T00:00:00Z")


def _owner_payload():
    return {
        "owner_name": "Kai Brandt", "owner_type": "NATURAL_PERSON",
        "ownership_pct": 80.00, "country_of_residence": "DE",
    }


def test_respondent_contact_writes_are_confined_to_its_own_respondent(api):
    """The scope check guards writes as well as reads, and because it precedes path resolution an
    unknown respondent id answers 403 rather than 404, so ids cannot be probed.

    Design: Corner/rbac/respondent_contact_writes_are_confined_to_its_own_respondent
    """
    _de()
    bank_a = licensed_respondent(
        "DE", legal_name="A Bank AG", swift_bic="ABNKDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    bank_b = licensed_respondent(
        "DE", legal_name="B Bank AG", swift_bic="BBNKDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    assert bank_a["dd_state"] == "DD_IN_PROGRESS"
    assert bank_b["dd_state"] == "DD_IN_PROGRESS"
    contact_b = make_respondent_headers(bank_b["id"])

    validate_error(
        api.create_beneficial_owner(bank_a["id"], _owner_payload(), contact_b),
        ApiErrorId.ERR_RESPONDENT_SCOPE_VIOLATION,
        expected_status=403,
    )
    validate_error(
        api.create_nested_relationship(
            bank_a["id"],
            {"downstream_institution_name": "Ostbank AG",
             "downstream_jurisdiction_code": "DE",
             "relationship_type": "DOWNSTREAM_CORRESPONDENT",
             "discovery_source": "QUESTIONNAIRE"},
            contact_b,
        ),
        ApiErrorId.ERR_RESPONDENT_SCOPE_VIOLATION,
        expected_status=403,
    )
    validate_error(
        api.create_beneficial_owner(NON_EXISTENT_UUID, _owner_payload(), contact_b),
        ApiErrorId.ERR_RESPONDENT_SCOPE_VIOLATION,
        expected_status=403,
    )

    _owners, owner_meta = validate_paginated(
        api.list_beneficial_owners(ANALYST, params={"respondent_bank_id": bank_a["id"]})
    )
    assert owner_meta["total_count"] == 0
    _nested, nested_meta = validate_paginated(
        api.list_nested_relationships(ANALYST, params={"respondent_bank_id": bank_a["id"]})
    )
    assert nested_meta["total_count"] == 0

    own_owner = validate_success(
        api.create_beneficial_owner(bank_b["id"], _owner_payload(), contact_b),
        expected_status=201,
    )
    assert own_owner["owner_name"] == "Kai Brandt"
    own_questionnaire = validate_success(
        api.create_questionnaire(
            bank_b["id"], questionnaire_payload(respondent_version(bank_b["id"])), contact_b
        ),
        expected_status=201,
    )
    assert own_questionnaire["state"] == "DRAFT"


def test_the_approver_may_not_be_the_identity_that_scored_the_respondent(api):
    """The committee is the only role that can approve at all, so the pair is only reachable by
    presenting the committee role under the scoring analyst's id - and the retry under a distinct
    committee identity approves the identical file, which shows the 409 was about the identity.

    Design: Corner/rbac/the_approver_may_not_be_the_identity_that_scored_the_respondent
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    add_verified_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)
    assessed_questionnaire(
        rid, "ONBOARDING_PROVISIONAL",
        self_ratings={domain: 4 for domain in CONTROL_DOMAIN_ORDER},
    )
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["dd_state"] == "PENDING_COMMITTEE"
    assert scored["ownership_verified"] is True
    assert scored["assessed_by_user_id"] == ANALYST_ID
    assert scored["residual_risk_score"] == 6.63
    assert scored["risk_rating"] == "LOW"

    impersonating = api.decide_committee(
        rid, {"action": "APPROVE"}, build_user_headers(ANALYST_ID, "CommitteeApprover")
    )
    validate_error(impersonating, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=409)
    refused = read_respondent(rid)
    assert refused["dd_state"] == "PENDING_COMMITTEE"
    assert refused["approved_by_user_id"] is None
    assert refused["last_approved_at"] is None

    approved = validate_success(
        api.decide_committee(
            rid, {"action": "APPROVE"},
            build_user_headers(COMMITTEE_ID, "CommitteeApprover"),
        )
    )
    assert approved["dd_state"] == "APPROVED"
    assert approved["approved_risk_rating"] == "LOW"
    assert approved["payment_posture"] == "OPEN"
    assert approved["approved_by_user_id"] == COMMITTEE_ID
