"""Who may call what: the two header tiers, the exclusive operations and the forum match."""
from test_helpers import (
    APPEALS_OFFICER_USER_ID,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    collection_referral_payload,
    create_appeal_proceeding_payload,
    create_assessment_payload,
    create_information_return_payload,
    create_taxpayer_payload,
    decision_payload,
    issue_assessment_payload,
    make_taxpayer_headers,
    read_assessment,
    read_audit,
    read_proceeding,
    read_taxpayer,
    register_taxpayer,
    set_clock_date,
    setup_issued_assessment,
    setup_open_proceeding,
    setup_review_complete_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["selection_analyst_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]
TRIBUNAL = TEST_USERS["tax_tribunal_judge_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]

NO_HEADERS = {}

SCOPE_END = "2026-06-30"
SMALL_BALANCE_TAX_CENTS = 4_762
COLLECTION_FEE_CENTS = 476
BALANCE_AFTER_FEE_CENTS = 5_238
PROTEST_DEADLINE = "2026-08-29"
MAGNITUDE_BP = 200
NEUTRAL_PRIOR_BP = 3_500

REPORTED_CENTS = 120_000_000
MATCHED_CENTS = 90_000_000
VARIANCE_CENTS = 30_000_000


def _return_body(taxpayer_id):
    """One under-reported federal 1099-K, identical in both attempts."""
    return create_information_return_payload(
        taxpayer_id,
        reported_amount_cents=REPORTED_CENTS,
        matched_return_amount_cents=MATCHED_CENTS,
    )


def _holders():
    return validate_paginated(api_client.list_taxpayers(ANALYST))


def test_a_registration_from_the_wrong_caller_never_reaches_the_body():
    """No headers is 401, and a role the endpoint does not list is 403 even with a broken body.

    PRD 2.1: "Every request to the API must carry two headers. `X-User-ID`
    identifies the acting user and `X-User-Role` names the role that user is
    acting in. If either header is absent, or if `X-User-Role` is not exactly one
    of the seven role names defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."
    PRD 2.8: "**Role authorization.** The acting role appears in the endpoint's
    authorized-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to
    every endpoint."
    PRD 2.8: "A test that expects a 409 conflict on a request that also carries a
    malformed body will get the 400 instead, because body shape is tier 5 and
    cross-entity state is tier 10."

    Design: Corner/rbac/a_wrong_role_or_a_missing_header_cannot_reach_any_business_rule
    """
    set_clock_date(SCOPE_END)
    register_taxpayer(legal_name="Ridgeline Tools LLC")

    headerless = api_client.create_taxpayer(
        create_taxpayer_payload(legal_name="Northgate Supply Inc"), NO_HEADERS
    )
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # The auditor's body is missing the required permit_number as well.
    wrong_role = api_client.create_taxpayer(
        create_taxpayer_payload(legal_name="Northgate Supply Inc", permit_number=...),
        AUDITOR,
    )
    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    holders, meta = _holders()
    assert meta["total_count"] == 1
    assert len(holders) == 1


def test_an_unlisted_role_is_refused_before_the_bodys_foreign_key_is_resolved():
    """Loading a return is the analyst's alone, so the supervisor never learns the id is fake.

    PRD 2.8: "**Body foreign keys.** Every foreign key supplied in the body
    resolves to an existing record, producing that entity's 404 from the same
    catalogue as tier 3. Applies to every write endpoint whose body carries a
    foreign key."
    PRD 3.1: "Third-party information returns are what turn a permit holder from
    a name into a risk. A `SelectionAnalyst` loads one at a time, naming the
    `taxpayer_id` it belongs to"
    PRD 3.1: "Loading computes `variance_cents` as the reported amount minus the
    matched amount, a signed value, and classifies the row in `match_status`:
    `MATCHED` when the variance is exactly zero, `UNDER_REPORTED` when it is
    positive, and `OVER_REPORTED` when it is negative."

    Design: Corner/rbac/a_wrong_role_or_a_missing_header_cannot_reach_any_business_rule
    """
    set_clock_date(SCOPE_END)
    holder = register_taxpayer(legal_name="Ridgeline Tools LLC")

    ghost = api_client.create_information_return(
        _return_body(NON_EXISTENT_UUID), SUPERVISOR
    )
    validate_error(ghost, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    loaded = validate_success(
        api_client.create_information_return(_return_body(holder["id"]), ANALYST), 201
    )
    assert loaded["taxpayer_id"] == holder["id"]
    assert loaded["match_status"] == "UNDER_REPORTED"
    assert loaded["variance_cents"] == VARIANCE_CENTS

    _, meta = _holders()
    assert meta["total_count"] == 1


def test_the_analyst_rescores_the_holder_and_the_supervisor_drafts_and_issues():
    """Two roles drive two operations nobody else may drive, on one live matter.

    PRD 3.1: "A `SelectionAnalyst` may also ask for a recomputation of a single
    holder on demand, which refreshes the two totals, the four component fields
    and `screening_score` without touching anything else."
    PRD 3.1: "The magnitude component takes the smaller of
    `gross_receipts_annual_cents` and the magnitude cap of 5,000,000,000 cents
    ($50,000,000.00), multiplies it by 10,000, divides by that same cap, rounds
    half up and caps at 10,000"
    PRD 3.1: "The prior-audit component is the neutral 3,500 basis points when
    `prior_audit_error_rate_bp` is null, and otherwise the smaller of that stored
    rate and 10,000."
    PRD 3.6: "If that provisional total is less than or equal to 5,000 cents —
    the comparison is inclusive, so a provisional total of exactly 5,000 cents is
    waived — then `penalty_waived_small_balance` becomes true, `penalty_cents` is
    set to 0, and `interest_cents` is recomputed from scratch on the bare tax"

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operation_end_to_end
    """
    set_clock_date(SCOPE_END)
    ctx = setup_review_complete_audit(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    taxpayer_id = ctx["taxpayer"]["id"]

    validate_success(api_client.rescore_screening(taxpayer_id, ANALYST), 200)
    holder = read_taxpayer(taxpayer_id)
    assert holder["screening_score"] == 0
    assert holder["info_variance_bp"] == 0
    assert holder["delinquency_bp"] == 0
    assert holder["magnitude_bp"] == MAGNITUDE_BP
    assert holder["prior_audit_bp"] == NEUTRAL_PRIOR_BP

    draft = validate_success(
        api_client.create_assessment(
            create_assessment_payload(ctx["audit"]["id"]), SUPERVISOR
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    assert draft["penalty_waived_small_balance"] is True
    assert draft["total_due_cents"] == SMALL_BALANCE_TAX_CENTS

    issued = validate_success(
        api_client.issue_assessment(
            draft["id"], issue_assessment_payload(SCOPE_END), SUPERVISOR
        ),
        200,
    )
    assert issued["status"] == "ISSUED"
    assert issued["collection_status"] == "DUE"
    assert issued["protest_deadline_date"] == PROTEST_DEADLINE
    assert read_audit(ctx["audit"]["id"])["status"] == "ASSESSED"


def test_collections_refers_the_notice_the_holder_protests_and_appeals_decides():
    """The remaining three roles each drive their own step on the same notice.

    PRD 3.9: "Second, caused by the first, a `SYSTEM` adjustment of kind
    `COLLECTION_FEE` is posted whose `amount_cents` is the negative of
    `balance_due_cents` multiplied by the collection-fee rate of 1,000 basis
    points, divided by 10,000 and rounded half up — ten percent of the balance at
    the moment of referral, charged as a negative credit so that it raises
    `balance_due_cents`. Third, caused by the second, the taxpayer's
    `compliance_status` becomes `DELINQUENT`"
    PRD 3.8: "A new proceeding starts at `status` `OPEN` with `outcome` `NONE`,
    and it sets the assessment's `collection_hold` to true."
    PRD 3.8: "Whatever the branch, deciding moves `status` from `OPEN` to the
    terminal `DECIDED`, sets `decided_date` to the logical clock date, sets
    `tolled_days` to the whole number of days from `filed_date` to
    `decided_date`, records `presiding_officer_user_id` as the deciding user,
    clears the assessment's `collection_hold` when no other proceeding of that
    assessment remains `OPEN`"

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operation_end_to_end
    """
    ctx = setup_issued_assessment(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    assessment_id = ctx["assessment"]["id"]
    taxpayer_id = ctx["taxpayer"]["id"]

    referred = validate_success(
        api_client.refer_to_collections(
            assessment_id,
            collection_referral_payload(referral_note="No response to the demand."),
            COLLECTIONS,
        ),
        200,
    )
    assert referred["collection_status"] == "REFERRED"
    assert referred["total_adjustments_cents"] == -COLLECTION_FEE_CENTS
    assert referred["balance_due_cents"] == BALANCE_AFTER_FEE_CENTS
    assert read_taxpayer(taxpayer_id)["compliance_status"] == "DELINQUENT"

    proceeding = validate_success(
        api_client.create_appeal_proceeding(
            create_appeal_proceeding_payload(
                assessment_id, protest_basis="The referral was premature."
            ),
            make_taxpayer_headers(taxpayer_id),
        ),
        201,
    )
    assert proceeding["status"] == "OPEN"
    assert proceeding["forum"] == "INFORMAL_CONFERENCE"
    assert read_assessment(assessment_id)["collection_hold"] is True

    decided = validate_success(
        api_client.decide_appeal_proceeding(
            proceeding["id"],
            decision_payload("SUSTAINED", decision_rationale="Assessment upheld."),
            APPEALS,
        ),
        200,
    )
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "SUSTAINED"
    assert decided["presiding_officer_user_id"] == APPEALS_OFFICER_USER_ID
    assert read_assessment(assessment_id)["collection_hold"] is False


def _conference_on_the_small_balance():
    """One OPEN informal conference filed the day the 4,762-cent notice was mailed."""
    ctx = setup_open_proceeding(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    assert ctx["proceeding"]["status"] == "OPEN"
    assert ctx["proceeding"]["filed_date"] == SCOPE_END
    return ctx


def _sustain(proceeding_id, headers, rationale):
    return api_client.decide_appeal_proceeding(
        proceeding_id, decision_payload("SUSTAINED", decision_rationale=rationale), headers
    )


def test_a_tribunal_judge_may_not_decide_an_informal_conference():
    """The judge is on the endpoint's role list and still cannot hear this forum.

    PRD 2.7: "The same error also covers forum-role mismatch: an `AppealsOfficer`
    may decide only an `INFORMAL_CONFERENCE` or an `ADMINISTRATIVE_APPEAL`, and a
    `TaxTribunalJudge` may decide only a `TAX_TRIBUNAL` proceeding, so a
    `TaxTribunalJudge` deciding an informal conference and an `AppealsOfficer`
    deciding a tribunal matter are both refused."
    PRD 2.8: "**Segregation of duties.** The §2.7 rules, returning
    `ERR_SEGREGATION_OF_DUTIES` (403). Applies to exactly two endpoints: `POST
    /appeal-proceedings/{id}/decision` and `POST /audits/{id}/close-fieldwork`."

    Design: Corner/rbac/the_presiding_role_must_match_the_forum_it_decides
    """
    ctx = _conference_on_the_small_balance()
    proceeding_id = ctx["proceeding"]["id"]

    response = _sustain(proceeding_id, TRIBUNAL, "Wrong forum for a judge.")
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    proceeding = read_proceeding(proceeding_id)
    assert proceeding["status"] == "OPEN"
    assert proceeding["outcome"] == "NONE"
    assert proceeding["decided_date"] is None
    assert proceeding["presiding_officer_user_id"] is None


def test_the_identical_decision_from_the_appeals_officer_is_accepted():
    """Only the caller changes, and the same conference is decided on the filing day.

    PRD 3.8: "The deciding act belongs to the forum's officer. An
    `AppealsOfficer` decides an `INFORMAL_CONFERENCE` or an
    `ADMINISTRATIVE_APPEAL`; a `TaxTribunalJudge` decides a `TAX_TRIBUNAL`
    proceeding. A role that does not match the forum is refused with
    `ERR_SEGREGATION_OF_DUTIES` even though both roles are listed on the
    endpoint"
    PRD 3.8: "**Branch one: `SUSTAINED`.** The forum upholds the assessment as
    issued. No ledger row is written and no money moves; `reduction_amount_cents`
    must be absent."
    PRD 3.8: "A `SUSTAINED` decision at a lower forum leaves the assessment
    `ISSUED` with a fresh escalation window running."

    Design: Corner/rbac/the_presiding_role_must_match_the_forum_it_decides
    """
    ctx = _conference_on_the_small_balance()
    proceeding_id = ctx["proceeding"]["id"]

    decided = validate_success(
        _sustain(proceeding_id, APPEALS, "Assessment upheld."), 200
    )
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "SUSTAINED"
    assert decided["presiding_officer_user_id"] == APPEALS_OFFICER_USER_ID
    assert decided["decided_date"] == SCOPE_END
    assert decided["tolled_days"] == 0

    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "ISSUED"
    assert assessment["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
