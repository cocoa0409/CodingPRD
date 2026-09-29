"""Opening an audit, accepting a methodology, voiding paperwork and filing a protest."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abandon_audit_payload,
    agree_agreement_payload,
    DEFAULT_LOGICAL_CLOCK_DATE,
    api_client,
    base_expiry_for,
    counter_agreement_payload,
    convert_lead_payload,
    create_appeal_proceeding_payload,
    execute_waiver_payload,
    make_taxpayer_headers,
    propose_agreement,
    read_agreement,
    read_assessment,
    read_audit,
    read_lead,
    read_industry_project,
    read_taxpayer,
    setup_issued_assessment,
    setup_project_with_scored_leads,
    setup_proposed_methodology,
    setup_scoped_audit,
    setup_waiver_draft,
    validate_error,
    validate_success,
    void_waiver,
)

SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
LEAD_AUDITOR_ID = "auditor-1"
QUOTA_OF_TWO = {"selection_quota": 2}


def test_a_converted_lead_mints_an_audit_with_nothing_yet_decided():
    """The new audit lands in PLANNED, and the holder is removed from future runs.

    PRD 3.1: "On success the lead moves `SELECTED → CONVERTED`, a new audit is
    created in `PLANNED` status carrying `taxpayer_id`, `audit_lead_id` and
    `lead_auditor_user_id`, the holder's `open_audit_count` increments by one — which
    removes it from every future scoring run — and the project's `selections_used`
    does not move, because `SELECTED` and `CONVERTED` both consume a slot."
    PRD 3.2: "A converted audit arrives in `PLANNED` with almost nothing decided:
    `audit_type` is null, both `scope_period_start` and `scope_period_end` are null,
    `projection_method` is `NONE`, `projection_status` is `NOT_RUN`, `statute_status`
    is `UNSET`, `agreed_agreement_id` is null, `fraud_indicator` is false,
    `reopen_count` is 0 and every deficiency total is 0."

    Design: Corner/state_machines/audit_created_by_conversion_starts_in_planned
    """
    ctx = setup_project_with_scored_leads(project_overrides=QUOTA_OF_TWO)
    lead = ctx["leads"][0]
    assert lead["status"] == "SELECTED"

    audit = validate_success(
        api_client.convert_audit_lead(
            lead["id"], convert_lead_payload(LEAD_AUDITOR_ID, "DESK"), SUPERVISOR
        ),
        201,
    )

    assert audit["status"] == "PLANNED"
    assert audit["version"] == 1
    assert audit["statute_status"] == "UNSET"
    assert audit["projection_status"] == "NOT_RUN"
    assert audit["projection_method"] == "NONE"
    assert audit["agreed_agreement_id"] is None
    assert audit["fraud_indicator"] is False
    assert audit["reopen_count"] == 0
    assert audit["waiver_days_added"] == 0
    assert audit["tolled_days"] == 0
    assert audit["taxpayer_id"] == ctx["taxpayer"]["id"]
    assert audit["audit_lead_id"] == lead["id"]
    assert audit["lead_auditor_user_id"] == LEAD_AUDITOR_ID

    assert read_lead(lead["id"])["status"] == "CONVERTED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["open_audit_count"] == 1

    project = read_industry_project(ctx["project"]["id"])
    assert project["selections_used"] == 1
    assert project["selections_remaining"] == 1


def _two_rival_methodologies():
    """One audit carrying two live proposals, the second reading the bumped version."""
    ctx = setup_proposed_methodology(
        methodology="RATIO_ESTIMATION", confidence_level_bp=9_500, minimum_sample_size=1
    )
    ctx["rival"] = propose_agreement(
        read_audit(ctx["audit"]["id"]),
        methodology="MEAN_PER_UNIT",
        confidence_level_bp=9_000,
        minimum_sample_size=2,
    )
    return ctx


def test_accepting_one_methodology_opens_fieldwork_and_supersedes_the_other():
    """One acceptance lands three side effects, not just the one on the agreement.

    PRD 3.3: "Acceptance moves the agreement `PROPOSED → AGREED` and cascades: the
    audit's `agreed_agreement_id` is set to that agreement, the audit moves
    `SCOPED → FIELDWORK`, and every other sampling agreement of the same audit still
    in `PROPOSED` or `COUNTERED` moves to `SUPERSEDED`."
    PRD 3.3: "Accepting requires the agreement to be `PROPOSED`, the audit to be
    `SCOPED` and the audit's `statute_status` not to be `EXPIRED`; the accepting party
    supplies `agreed_by_name`, the taxpayer officer who accepted the methodology."

    Design: Corner/state_machines/agreeing_the_methodology_opens_fieldwork_and_supersedes_the_rival
    """
    ctx = _two_rival_methodologies()
    assert read_agreement(ctx["rival"]["id"])["status"] == "PROPOSED"

    agreed = validate_success(
        api_client.agree_sampling_agreement(
            ctx["agreement"]["id"],
            agree_agreement_payload(agreed_by_name="R. Vance"),
            make_taxpayer_headers(ctx["taxpayer"]["id"]),
        ),
        200,
    )
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_by_name"] == "R. Vance"
    assert read_agreement(ctx["rival"]["id"])["status"] == "SUPERSEDED"

    audit = read_audit(ctx["audit"]["id"])
    assert audit["status"] == "FIELDWORK"
    assert audit["agreed_agreement_id"] == ctx["agreement"]["id"]
    assert audit["projection_method"] == "NONE"
    assert audit["projection_status"] == "NOT_RUN"


def _agreed_methodology_in_fieldwork():
    ctx = setup_proposed_methodology()
    ctx["agreement"] = validate_success(
        api_client.agree_sampling_agreement(
            ctx["agreement"]["id"],
            agree_agreement_payload(agreed_by_name="R. Vance"),
            make_taxpayer_headers(ctx["taxpayer"]["id"]),
        ),
        200,
    )
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def test_countering_a_methodology_already_accepted_is_refused():
    """A late objection cannot drag a live audit back into negotiation.

    PRD 3.3: "Both `AGREED` and `SUPERSEDED` are terminal — no counter, revision or
    acceptance is accepted against a superseded row, and attempting one is
    `ERR_INVALID_STATE`."
    PRD 3.3: "Countering, which only the `Taxpayer` may do and only while the
    agreement is `PROPOSED` and the audit is still `SCOPED`, moves the agreement
    `PROPOSED → COUNTERED` and records the mandatory `counter_note` stating the
    objection along with an optional `requested_minimum_sample_size` of at least one."

    Design: Corner/state_machines/countering_an_already_agreed_methodology_is_refused
    """
    ctx = _agreed_methodology_in_fieldwork()

    response = api_client.counter_sampling_agreement(
        ctx["agreement"]["id"],
        counter_agreement_payload(
            counter_note="We want a bigger sample after all",
            requested_minimum_sample_size=5,
        ),
        make_taxpayer_headers(ctx["taxpayer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "AGREED"
    assert agreement["round_number"] == 1
    assert agreement["counter_note"] is None
    assert read_audit(ctx["audit"]["id"])["status"] == "FIELDWORK"


def test_accepting_the_same_methodology_a_second_time_is_refused():
    """Acceptance is not idempotent, so the cascade never runs twice.

    PRD 3.3: "Both `AGREED` and `SUPERSEDED` are terminal — no counter, revision or
    acceptance is accepted against a superseded row, and attempting one is
    `ERR_INVALID_STATE`."
    PRD 3.3: "Acceptance moves the agreement `PROPOSED → AGREED` and cascades: the
    audit's `agreed_agreement_id` is set to that agreement, the audit moves
    `SCOPED → FIELDWORK`, and every other sampling agreement of the same audit still
    in `PROPOSED` or `COUNTERED` moves to `SUPERSEDED`."

    Design: Corner/state_machines/agreeing_the_same_methodology_twice_is_refused
    """
    ctx = _agreed_methodology_in_fieldwork()

    response = api_client.agree_sampling_agreement(
        ctx["agreement"]["id"],
        agree_agreement_payload(agreed_by_name="R. Vance"),
        make_taxpayer_headers(ctx["taxpayer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert read_agreement(ctx["agreement"]["id"])["status"] == "AGREED"
    audit = read_audit(ctx["audit"]["id"])
    assert audit["status"] == "FIELDWORK"
    assert audit["agreed_agreement_id"] == ctx["agreement"]["id"]


def test_a_waiver_voided_before_signature_can_never_be_executed():
    """The voided paperwork is dead, and the limitation date never left the base date.

    PRD 3.2: "`VOIDED` is terminal: no execution is accepted afterwards, and
    attempting one is `ERR_INVALID_STATE`."
    PRD 3.2: "Voiding a waiver that is still `DRAFTED` is also permitted and records
    the `void_reason`, but changes no date at all, because an unexecuted waiver never
    contributed a day."
    PRD 3.2: "The draft lands in `DRAFTED`, contributes no days to anything, and
    carries `prior_expiry_date` null and `days_added` 0."

    Design: Corner/state_machines/executing_a_voided_draft_waiver_is_refused
    """
    ctx = setup_waiver_draft()
    voided = void_waiver(ctx["waiver"]["id"], void_reason="Signature page was unsigned.")
    assert voided["status"] == "VOIDED"

    response = api_client.execute_statute_waiver(
        ctx["waiver"]["id"],
        execute_waiver_payload(DEFAULT_LOGICAL_CLOCK_DATE),
        make_taxpayer_headers(ctx["taxpayer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    waiver = validate_success(
        api_client.get_statute_waiver(ctx["waiver"]["id"], SUPERVISOR), 200
    )
    assert waiver["status"] == "VOIDED"
    assert waiver["days_added"] == 0
    assert waiver["prior_expiry_date"] is None

    audit = read_audit(ctx["audit"]["id"])
    assert audit["statute_expiry_date"] == base_expiry_for()
    assert audit["waiver_days_added"] == 0
    assert audit["statute_status"] == "PROTECTED"


def test_an_audit_whose_limitation_period_still_runs_cannot_be_abandoned():
    """Abandonment is for lapsed matters only, and it never frees a live holder.

    PRD 3.2: "Abandonment is available from `PLANNED`, `SCOPED`, `FIELDWORK` and
    `REVIEW_COMPLETE`, and it inverts the usual statute rule: the audit's
    `statute_status` must be `EXPIRED`, and abandoning an audit whose limitation
    period is still alive is refused with `ERR_STATUTE_NOT_EXPIRED`."
    PRD 3.2: "Abandonment moves the audit to `ABANDONED`, supersedes every sampling
    agreement of that audit still in `PROPOSED` or `COUNTERED`, and decrements the
    permit holder's `open_audit_count` by one, freeing it for future scoring runs."

    Design: Corner/state_machines/abandoning_an_audit_whose_statute_still_runs_is_refused
    """
    ctx = setup_scoped_audit()
    assert ctx["audit"]["statute_status"] == "PROTECTED"

    response = api_client.abandon_audit(
        ctx["audit"]["id"],
        abandon_audit_payload(abandon_reason="Limitation period has run."),
        SUPERVISOR,
    )
    validate_error(response, ApiErrorId.ERR_STATUTE_NOT_EXPIRED.value, 409)

    audit = read_audit(ctx["audit"]["id"])
    assert audit["status"] == "SCOPED"
    assert audit["statute_status"] == "PROTECTED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["open_audit_count"] == 1


def test_filing_the_informal_conference_puts_the_notice_under_a_collection_hold():
    """The protest opens at the first rung and freezes collection without moving status.

    PRD 3.8: "A new proceeding starts at `status` `OPEN` with `outcome` `NONE`, and it
    sets the assessment's `collection_hold` to true. That flag is the taxpayer's
    practical protection: while it is true the assessment cannot be referred to
    collections, so the state does not pursue money that is under dispute."
    PRD 3.8: "A first proceeding must be an `INFORMAL_CONFERENCE` and must be filed on
    or before the assessment's `protest_deadline_date`; day 60 inclusive is still
    open, and a filing after it is refused with `ERR_PROTEST_WINDOW_CLOSED`."

    Design: Corner/state_machines/filing_the_informal_conference_sets_the_collection_hold
    """
    ctx = setup_issued_assessment(tax_deficiency_cents=4_763)
    assessment = ctx["assessment"]
    assert assessment["total_due_cents"] == 5_001
    assert assessment["protest_deadline_date"] == "2026-08-29"

    proceeding = validate_success(
        api_client.create_appeal_proceeding(
            create_appeal_proceeding_payload(assessment["id"]),
            make_taxpayer_headers(ctx["taxpayer"]["id"]),
        ),
        201,
    )

    assert proceeding["forum"] == "INFORMAL_CONFERENCE"
    assert proceeding["status"] == "OPEN"
    assert proceeding["outcome"] == "NONE"
    assert proceeding["tolled_days"] == 0
    assert proceeding["decided_date"] is None
    assert proceeding["predecessor_proceeding_id"] is None
    assert proceeding["presiding_officer_user_id"] is None

    stored = read_assessment(assessment["id"])
    assert stored["collection_hold"] is True
    assert stored["status"] == "ISSUED"
    assert stored["collection_status"] == "DUE"
    assert stored["protest_deadline_date"] == "2026-08-29"
    assert stored["total_due_cents"] == 5_001
