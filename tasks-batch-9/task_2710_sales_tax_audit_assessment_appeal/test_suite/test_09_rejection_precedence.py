"""Which single error a request gets when it breaks more than one rule at once."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SUPERVISOR_USER_ID,
    TEST_USERS,
    api_client,
    close_fieldwork_payload,
    issue_assessment_payload,
    make_supervisor_headers,
    make_taxpayer_headers,
    read_arrangement,
    read_assessment,
    read_audit,
    register_taxpayer,
    request_installment_plan,
    set_clock_date,
    setup_audit_with_findings,
    setup_draft_assessment,
    setup_issued_assessment,
    setup_open_proceeding,
    stale_the_findings,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]

SCOPE_START = "2026-01-01"
PRICE_FOR_4762_CENTS = 76_192
EXTRA_PRICE_FOR_2500_CENTS = 40_000
WRONG_NOTICE_DATE = "2026-05-01"
EXPIRY_DATE = "2029-06-29"
DAY_PAST_EXPIRY = "2029-07-01"
OTHER_SUPERVISOR_USER_ID = "supervisor-2"


def _purchase(price_cents):
    return {
        "invoice_date": SCOPE_START,
        "purchase_price_cents": price_cents,
        "asset_class": "CONSUMABLE",
    }


def _issue_with(assessment_id, notice_mailed_date):
    return api_client.issue_assessment(
        assessment_id, issue_assessment_payload(notice_mailed_date), SUPERVISOR
    )


def test_a_stale_notice_is_refused_for_its_state_before_its_date_is_read():
    """Own-state outranks the notice-date rule, so the state error is the one returned.

    PRD 2.8: "Checks are evaluated in the fourteen tiers below, in ascending order;
    the first tier that finds a violation decides the response, and no later tier may
    pre-empt an earlier one."
    PRD 3.6: "The assessment must be in `DRAFT` — a `DRAFT_STALE` notice is refused
    with `ERR_INVALID_STATE` — the audit must still be in `REVIEW_COMPLETE`, and the
    audit's derived `statute_status` must not be `EXPIRED`, since a notice mailed
    after the limitation period has run is void and is refused with
    `ERR_STATUTE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_7_outranks_notice_date_priority_12
    """
    ctx = setup_draft_assessment(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])
    stale_the_findings(ctx, purchase_price_cents=EXTRA_PRICE_FOR_2500_CENTS)
    assert ctx["assessment"]["status"] == "DRAFT_STALE"

    response = _issue_with(ctx["assessment"]["id"], WRONG_NOTICE_DATE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = read_assessment(ctx["assessment"]["id"])
    assert after["status"] == "DRAFT_STALE"
    assert after["notice_mailed_date"] is None


def test_the_same_wrong_date_is_reported_as_a_date_error_on_a_live_draft():
    """With the state objection removed, the later tier finally speaks.

    PRD 3.6: "Issuance is the supervisor's act of mailing the notice, and it takes a
    `notice_mailed_date` in the body which must equal the current logical clock date;
    any other value, past or future, is refused with `ERR_NOTICE_DATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_7_outranks_notice_date_priority_12
    """
    ctx = setup_draft_assessment(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])
    assert ctx["assessment"]["status"] == "DRAFT"

    response = _issue_with(ctx["assessment"]["id"], WRONG_NOTICE_DATE)
    validate_error(response, ApiErrorId.ERR_NOTICE_DATE_INVALID.value, 422)

    after = read_assessment(ctx["assessment"]["id"])
    assert after["status"] == "DRAFT"
    assert after["notice_mailed_date"] is None


def test_an_open_protest_blocks_approval_before_the_plan_is_even_priced():
    """The appeal objection is raised first, so the shortfall is never reported.

    PRD 2.8: "Sibling records that the operation depends on are in the state it
    requires: the lead being converted is `SELECTED` (`ERR_LEAD_NOT_SELECTED`); the
    audit has an `AGREED` sampling agreement and the unit being drawn names that same
    agreement (`ERR_AGREEMENT_NOT_AGREED`); the audit's `projection_status` is
    `CURRENT` before an assessment is drafted or recomputed and before fieldwork
    closes (`ERR_PROJECTION_STALE`); the predecessor proceeding is `DECIDED` before an
    escalation is filed (`ERR_PREDECESSOR_NOT_DECIDED`); no proceeding of the
    assessment is `OPEN` before penalty abatement, finalization or arrangement
    approval, and the assessment is `ISSUED` or `FINAL` before an arrangement is
    approved (`ERR_APPEAL_PENDING`)."

    Design: Difficulty/priority_pair_validation_conflict/appeal_pending_priority_10_outranks_plan_underfunded_priority_13
    """
    ctx = setup_open_proceeding(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])
    assert ctx["assessment"]["balance_due_cents"] == 4_762
    plan = request_installment_plan(ctx["assessment"]["id"], 1_000, 1)
    assert plan["scheduled_total_cents"] == 1_000

    response = api_client.approve_payment_arrangement(plan["id"], COLLECTIONS)
    validate_error(response, ApiErrorId.ERR_APPEAL_PENDING.value, 409)

    assert read_arrangement(plan["id"])["status"] == "REQUESTED"
    assert read_assessment(ctx["assessment"]["id"])["collection_status"] == "DUE"


def test_the_same_short_plan_is_reported_as_underfunded_with_no_protest_pending():
    """Once nothing is under appeal the money rule decides the request.

    PRD 3.9: "An `INSTALLMENT_PLAN` must cover the whole liability: its
    `scheduled_total_cents` must be greater than or equal to the assessment's
    `balance_due_cents`, and a plan that would leave a shortfall is refused with
    `ERR_PLAN_UNDERFUNDED`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_pending_priority_10_outranks_plan_underfunded_priority_13
    """
    ctx = setup_issued_assessment(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])
    plan = request_installment_plan(ctx["assessment"]["id"], 1_000, 1)

    response = api_client.approve_payment_arrangement(plan["id"], COLLECTIONS)
    validate_error(response, ApiErrorId.ERR_PLAN_UNDERFUNDED.value, 422)

    assert read_arrangement(plan["id"])["status"] == "REQUESTED"
    assert read_assessment(ctx["assessment"]["id"])["collection_status"] == "DUE"


def test_an_unknown_permit_holder_is_missing_before_it_is_someone_elses():
    """Path existence is settled first, so the caller learns nothing about ownership.

    PRD 2.8: "Every identifier embedded in the request path resolves to an existing
    record, validated left to right, producing that entity's own 404:
    `ERR_TAXPAYER_NOT_FOUND`, `ERR_INFORMATION_RETURN_NOT_FOUND`,
    `ERR_INDUSTRY_PROJECT_NOT_FOUND`, `ERR_AUDIT_LEAD_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_STATUTE_WAIVER_NOT_FOUND`,
    `ERR_SAMPLING_AGREEMENT_NOT_FOUND`, `ERR_SAMPLE_UNIT_NOT_FOUND`,
    `ERR_EXEMPTION_CERTIFICATE_NOT_FOUND`, `ERR_USE_TAX_PURCHASE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ASSESSMENT_ADJUSTMENT_NOT_FOUND`,
    `ERR_APPEAL_PROCEEDING_NOT_FOUND` or `ERR_PAYMENT_ARRANGEMENT_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/path_existence_priority_3_outranks_ownership_priority_4
    """
    holder = register_taxpayer(legal_name="Ridgeline Tools LLC")

    response = api_client.get_taxpayer(
        NON_EXISTENT_UUID, make_taxpayer_headers(holder["id"])
    )
    validate_error(response, ApiErrorId.ERR_TAXPAYER_NOT_FOUND.value, 404)


def test_a_permit_holder_that_exists_but_belongs_to_someone_else_is_forbidden():
    """The ownership tier runs only once the record has been found.

    PRD 2.8: "When the acting role is `Taxpayer`, the addressed resource must belong
    to the permit holder named by `X-User-ID` — otherwise `ERR_NOT_RESOURCE_OWNER`
    (403)."
    PRD 2.8: "It deliberately runs after tier 3."

    Design: Difficulty/priority_pair_validation_conflict/path_existence_priority_3_outranks_ownership_priority_4
    """
    holder = register_taxpayer(legal_name="Ridgeline Tools LLC")
    stranger = register_taxpayer(legal_name="Coastal Fabrication Inc")
    own_headers = make_taxpayer_headers(holder["id"])

    response = api_client.get_taxpayer(stranger["id"], own_headers)
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    own = validate_success(api_client.get_taxpayer(holder["id"], own_headers), 200)
    assert own["id"] == holder["id"]


def _expired_audit_led_by_the_supervisor():
    """Fieldwork ready to close, but led by the very supervisor who would close it."""
    ctx = setup_audit_with_findings(lead_auditor_user_id=SUPERVISOR_USER_ID)
    assert ctx["audit"]["lead_auditor_user_id"] == SUPERVISOR_USER_ID
    assert ctx["audit"]["statute_expiry_date"] == EXPIRY_DATE
    set_clock_date(DAY_PAST_EXPIRY)
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    assert ctx["audit"]["statute_status"] == "EXPIRED"
    return ctx


def test_the_reviewer_separation_is_checked_before_the_limitation_period():
    """A compliance separation is never masked by a downstream deadline complaint.

    PRD 2.7: "These two endpoints — closing fieldwork and deciding a proceeding — are
    the complete scope of the segregation check. It is evaluated ahead of every
    deadline rule and every money rule, because a compliance separation must never be
    masked by a downstream arithmetic complaint."
    PRD 2.7: "The supervisor who closes that audit's fieldwork may not be that same
    person: if the acting `X-User-ID` equals the audit's `lead_auditor_user_id`,
    closing fieldwork is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_priority_8_outranks_statute_expired_priority_12
    """
    ctx = _expired_audit_led_by_the_supervisor()

    response = api_client.close_fieldwork(
        ctx["audit"]["id"], close_fieldwork_payload(), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after = read_audit(ctx["audit"]["id"])
    assert after["status"] == "FIELDWORK"
    assert after["statute_status"] == "EXPIRED"


def test_an_independent_supervisor_is_stopped_by_the_limitation_period_instead():
    """With the separation satisfied, the expired statute is what refuses the close.

    PRD 3.4: "The audit must be in `FIELDWORK`, its `statute_status` must not be
    `EXPIRED`, its `projection_status` must be `CURRENT` — a stale projection is
    refused with `ERR_PROJECTION_STALE` — and its `examined_unit_count` must be at
    least the agreed agreement's `minimum_sample_size`, or the close is refused with
    `ERR_SAMPLE_SIZE_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_priority_8_outranks_statute_expired_priority_12
    """
    ctx = _expired_audit_led_by_the_supervisor()

    response = api_client.close_fieldwork(
        ctx["audit"]["id"],
        close_fieldwork_payload(),
        make_supervisor_headers(OTHER_SUPERVISOR_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_STATUTE_EXPIRED.value, 409)

    assert read_audit(ctx["audit"]["id"])["status"] == "FIELDWORK"
