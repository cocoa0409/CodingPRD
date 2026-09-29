"""Which error a request earns when more than one rule could complain."""
from test_helpers import (
    APPEALS_OFFICER_USER_ID,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    convert_lead,
    decide_proceeding,
    convert_lead_payload,
    create_appeal_proceeding_payload,
    create_assessment_adjustment_payload,
    create_industry_project,
    create_sample_unit_payload,
    create_statute_waiver_payload,
    abate_penalty_payload,
    arrangement_payment_payload,
    decision_payload,
    draft_waiver,
    draw_sample_unit,
    execute_waiver,
    file_protest,
    list_leads,
    read_agreement,
    read_arrangement,
    read_assessment,
    read_audit,
    read_lead,
    read_proceeding,
    read_taxpayer,
    redetermine_sample_unit,
    run_selection,
    set_clock_date,
    setup_agreed_methodology,
    setup_issued_assessment,
    setup_project_with_scored_leads,
    setup_requested_installment_plan,
    setup_scoped_audit,
    validate_error,
    validate_paginated,
    validate_success,
    void_waiver,
)

ANALYST = TEST_USERS["selection_analyst_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
SUPERVISOR = TEST_USERS["audit_supervisor_headers"]
COLLECTIONS = TEST_USERS["collections_agent_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]

SMALL_BALANCE_TAX_CENTS = 4_762
SCOPE_END = "2026-06-30"
BASE_EXPIRY = "2029-06-29"
WAIVER_TARGET = "2031-01-01"
SECOND_TARGET = "2031-06-01"
DAYS_ADDED = 551


def _reads_by_family():
    """One GET-by-id per resource family, each addressed with a ghost identifier."""
    return [
        (api_client.get_information_return, ApiErrorId.ERR_INFORMATION_RETURN_NOT_FOUND),
        (api_client.get_industry_project, ApiErrorId.ERR_INDUSTRY_PROJECT_NOT_FOUND),
        (api_client.get_audit_lead, ApiErrorId.ERR_AUDIT_LEAD_NOT_FOUND),
        (api_client.get_audit, ApiErrorId.ERR_AUDIT_NOT_FOUND),
        (api_client.get_statute_waiver, ApiErrorId.ERR_STATUTE_WAIVER_NOT_FOUND),
        (api_client.get_sampling_agreement, ApiErrorId.ERR_SAMPLING_AGREEMENT_NOT_FOUND),
        (api_client.get_sample_unit, ApiErrorId.ERR_SAMPLE_UNIT_NOT_FOUND),
        (
            api_client.get_exemption_certificate,
            ApiErrorId.ERR_EXEMPTION_CERTIFICATE_NOT_FOUND,
        ),
        (api_client.get_use_tax_purchase, ApiErrorId.ERR_USE_TAX_PURCHASE_NOT_FOUND),
        (api_client.get_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (
            api_client.get_assessment_adjustment,
            ApiErrorId.ERR_ASSESSMENT_ADJUSTMENT_NOT_FOUND,
        ),
        (api_client.get_appeal_proceeding, ApiErrorId.ERR_APPEAL_PROCEEDING_NOT_FOUND),
        (api_client.get_payment_arrangement, ApiErrorId.ERR_PAYMENT_ARRANGEMENT_NOT_FOUND),
    ]


def test_each_resource_family_answers_a_ghost_id_with_its_own_not_found_code():
    """Thirteen collections, thirteen distinct 404 codes, none of them generic.

    PRD 2.8: "**Path existence.** Every identifier embedded in the request path
    resolves to an existing record, validated left to right, producing that
    entity's own 404: `ERR_TAXPAYER_NOT_FOUND`, `ERR_INFORMATION_RETURN_NOT_FOUND`,
    `ERR_INDUSTRY_PROJECT_NOT_FOUND`, `ERR_AUDIT_LEAD_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_STATUTE_WAIVER_NOT_FOUND`,
    `ERR_SAMPLING_AGREEMENT_NOT_FOUND`, `ERR_SAMPLE_UNIT_NOT_FOUND`,
    `ERR_EXEMPTION_CERTIFICATE_NOT_FOUND`, `ERR_USE_TAX_PURCHASE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ASSESSMENT_ADJUSTMENT_NOT_FOUND`,
    `ERR_APPEAL_PROCEEDING_NOT_FOUND` or `ERR_PAYMENT_ARRANGEMENT_NOT_FOUND`."

    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_code
    """
    seen = []
    for read, expected in _reads_by_family():
        validate_error(read(NON_EXISTENT_UUID, SUPERVISOR), expected.value, 404)
        seen.append(expected.value)

    assert len(set(seen)) == 13


def _one_holder_selected_twice():
    """One permit holder holding a SELECTED lead in each of two projects."""
    ctx = setup_project_with_scored_leads()
    second = create_industry_project(project_name="Hardware Retail Second Pass")
    run_selection(second["id"])
    taxpayer_id = ctx["taxpayer"]["id"]
    ctx["lead_a"] = ctx["leads"][0]
    ctx["lead_b"] = list_leads(
        industry_project_id=second["id"], taxpayer_id=taxpayer_id
    )[0]
    assert ctx["lead_a"]["status"] == "SELECTED"
    assert ctx["lead_b"]["status"] == "SELECTED"
    return ctx


def test_a_second_conversion_of_the_same_lead_is_a_lead_status_complaint():
    """The already-converted lead answers for its own status, not for the audit.

    PRD 2.8: "converting a lead is exempt from the generic check entirely — its
    status test is deferred to tier 10, where a lead that is not `SELECTED`
    returns `ERR_LEAD_NOT_SELECTED`."
    PRD 3.1: "`NOT_SELECTED`, `CONVERTED` and `DECLINED` are terminal lead states;
    no further operation is accepted on a lead in any of them."

    Design: Corner/errors/a_converted_lead_reports_its_own_code_before_the_open_audit_conflict
    """
    ctx = _one_holder_selected_twice()
    audit = convert_lead(ctx["lead_a"]["id"])
    assert audit["status"] == "PLANNED"

    response = api_client.convert_audit_lead(
        ctx["lead_a"]["id"], convert_lead_payload("auditor-1", "DESK"), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_LEAD_NOT_SELECTED.value, 409)

    assert read_lead(ctx["lead_a"]["id"])["status"] == "CONVERTED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["open_audit_count"] == 1


def test_a_sibling_lead_of_a_holder_under_audit_reports_the_open_audit_instead():
    """A still-SELECTED lead passes the status test and hits the interval rule.

    PRD 3.1: "The lead must be `SELECTED` — a lead in any other status, including
    a waitlisted `SCORED` lead, is refused with `ERR_LEAD_NOT_SELECTED` — and the
    permit holder's `open_audit_count` must be 0, or the conversion is refused with
    `ERR_TAXPAYER_AUDIT_IN_PROGRESS`."

    Design: Corner/errors/a_converted_lead_reports_its_own_code_before_the_open_audit_conflict
    """
    ctx = _one_holder_selected_twice()
    audit = convert_lead(ctx["lead_a"]["id"])

    response = api_client.convert_audit_lead(
        ctx["lead_b"]["id"], convert_lead_payload("auditor-1", "DESK"), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_TAXPAYER_AUDIT_IN_PROGRESS.value, 409)

    assert read_lead(ctx["lead_b"]["id"])["status"] == "SELECTED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["open_audit_count"] == 1

    audits, meta = validate_paginated(
        api_client.list_audits(SUPERVISOR, params={"taxpayer_id": ctx["taxpayer"]["id"]})
    )
    assert meta["total_count"] == 1
    assert audits[0]["id"] == audit["id"]


UNIT_REFERENCE = "RT-500"
UNIT_DATE = "2026-03-02"
UNIT_CENTS = 100_000


def _unit_body(agreement_id, stratum_index):
    """The same invoice twice, differing only in the stratum it claims."""
    return create_sample_unit_payload(
        agreement_id,
        stratum_index,
        UNIT_DATE,
        UNIT_CENTS,
        invoice_reference=UNIT_REFERENCE,
        error_class="NO_ERROR",
    )


def test_a_stratum_index_past_the_end_of_the_agreed_array_stores_nothing():
    """With one stratum agreed, 0 is the only index the array has.

    PRD 3.4: "The unit declares its `stratum_index`, a 0-based index into that
    agreement's `strata` array, and an index that is not a valid contiguous
    position in the array is refused with `ERR_STRATUM_INDEX_INVALID`."
    PRD 3.4: "The agreement additionally tracks its own `examined_unit_count` as
    the number of sample units created against it."

    Design: Corner/errors/stratum_index_must_index_the_agreed_strata
    """
    ctx = setup_agreed_methodology()
    agreement_id = ctx["agreement"]["id"]
    assert read_agreement(agreement_id)["examined_unit_count"] == 0

    response = api_client.create_sample_unit(_unit_body(agreement_id, 1), AUDITOR)
    validate_error(response, ApiErrorId.ERR_STRATUM_INDEX_INVALID.value, 422)

    unit = validate_success(
        api_client.create_sample_unit(_unit_body(agreement_id, 0), AUDITOR), 201
    )
    assert unit["stratum_index"] == 0

    units, meta = validate_paginated(
        api_client.list_agreement_sample_units(agreement_id, AUDITOR)
    )
    assert meta["total_count"] == 1
    assert units[0]["id"] == unit["id"]
    assert read_agreement(agreement_id)["examined_unit_count"] == 1


def _scoped_audit_on_the_base_expiry():
    """A DESK audit scoped 2026-01-01..2026-06-30 with the clock on its last day."""
    set_clock_date(SCOPE_END)
    ctx = setup_scoped_audit()
    assert ctx["audit"]["base_statute_expiry_date"] == BASE_EXPIRY
    assert ctx["audit"]["statute_expiry_date"] == BASE_EXPIRY
    assert ctx["audit"]["statute_status"] == "PROTECTED"
    return ctx


def test_only_one_waiver_may_await_signature_and_it_must_add_a_day():
    """The pending slot blocks the second draft; freed, the non-extending date fails.

    PRD 3.2: "Only one waiver per audit may sit in `DRAFTED` awaiting signature at
    a time; drafting a second while one is outstanding is refused with
    `ERR_WAIVER_ALREADY_PENDING`."
    PRD 3.2: "the `extended_to_date` being requested, which must fall strictly
    after the audit's current `statute_expiry_date`"
    PRD 3.2: "Voiding a waiver that is still `DRAFTED` is also permitted and
    records the `void_reason`, but changes no date at all, because an unexecuted
    waiver never contributed a day."

    Design: Corner/errors/one_pending_waiver_at_a_time_and_it_must_actually_extend
    """
    ctx = _scoped_audit_on_the_base_expiry()
    audit_id = ctx["audit"]["id"]

    first = draft_waiver(audit_id, SCOPE_END, WAIVER_TARGET)
    assert first["status"] == "DRAFTED"
    assert first["days_added"] == 0
    assert first["prior_expiry_date"] is None

    response = api_client.create_statute_waiver(
        create_statute_waiver_payload(audit_id, SCOPE_END, SECOND_TARGET), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_ALREADY_PENDING.value, 409)

    audit = read_audit(audit_id)
    assert audit["waiver_days_added"] == 0
    assert audit["statute_expiry_date"] == BASE_EXPIRY

    assert void_waiver(first["id"])["status"] == "VOIDED"
    assert read_audit(audit_id)["statute_expiry_date"] == BASE_EXPIRY

    response = api_client.create_statute_waiver(
        create_statute_waiver_payload(audit_id, SCOPE_END, BASE_EXPIRY), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_NOT_EXTENDING.value, 422)

    _, meta = validate_paginated(
        api_client.list_audit_statute_waivers(audit_id, SUPERVISOR)
    )
    assert meta["total_count"] == 1


def test_the_replacement_waiver_adds_the_days_from_the_running_expiry():
    """Once the slot is free the signed replacement moves the limitation date.

    PRD 3.2: "The waiver moves `DRAFTED → EXECUTED`, capturing `prior_expiry_date`
    as the audit's expiry at that moment and `days_added` as the whole number of
    days from that snapshot to `extended_to_date`."
    PRD 3.2: "The sum of all such contributions is stored on the audit as
    `waiver_days_added`."

    Design: Corner/errors/one_pending_waiver_at_a_time_and_it_must_actually_extend
    """
    ctx = _scoped_audit_on_the_base_expiry()
    audit_id = ctx["audit"]["id"]
    stuck = draft_waiver(audit_id, SCOPE_END, WAIVER_TARGET)
    void_waiver(stuck["id"])

    replacement = draft_waiver(audit_id, SCOPE_END, WAIVER_TARGET)
    executed = execute_waiver(replacement["id"], ctx["taxpayer"]["id"], SCOPE_END)

    assert executed["status"] == "EXECUTED"
    assert executed["signed_date"] == SCOPE_END
    assert executed["prior_expiry_date"] == BASE_EXPIRY
    assert executed["days_added"] == DAYS_ADDED

    audit = read_audit(audit_id)
    assert audit["waiver_days_added"] == DAYS_ADDED
    assert audit["statute_expiry_date"] == WAIVER_TARGET
    assert audit["base_statute_expiry_date"] == BASE_EXPIRY
    assert audit["statute_status"] == "PROTECTED"


NOTICE_DATE = "2026-06-30"
PROTEST_FILED_DATE = "2026-07-01"
PAPER_FILED_DATE = "2026-07-05"
DECISION_DATE = "2026-07-15"
ESCALATION_DEADLINE = "2026-08-14"
INSIDE_THE_WINDOW = "2026-07-16"
PAST_THE_WINDOW = "2026-08-15"


def _decided_informal_conference():
    """A 4,762-cent notice whose informal conference was sustained on 2026-07-15."""
    ctx = setup_issued_assessment(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    assert ctx["assessment"]["notice_mailed_date"] == NOTICE_DATE
    assert ctx["assessment"]["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
    set_clock_date(PROTEST_FILED_DATE)
    ctx["proceeding"] = file_protest(
        ctx["assessment"]["id"],
        ctx["taxpayer"]["id"],
        forum="INFORMAL_CONFERENCE",
        filed_date=PAPER_FILED_DATE,
    )
    set_clock_date(DECISION_DATE)
    ctx["proceeding"] = decide_proceeding(
        ctx["proceeding"]["id"], "SUSTAINED", decision_rationale="Projection upheld"
    )
    ctx["assessment"] = read_assessment(ctx["assessment"]["id"])
    return ctx


def _protest_body(assessment_id, forum, predecessor_id, filed_date):
    return create_appeal_proceeding_payload(
        assessment_id,
        forum=forum,
        protest_basis="Escalating the sustained conference",
        predecessor_proceeding_id=predecessor_id,
        filed_date=filed_date,
    )


def test_skipping_the_middle_rung_is_a_sequence_defect_not_a_clock_defect():
    """Inside the escalation window the only thing wrong is the forum itself.

    PRD 3.8: "the protest ladder has three rungs which must be climbed in order:
    `INFORMAL_CONFERENCE`, then `ADMINISTRATIVE_APPEAL`, then `TAX_TRIBUNAL`."
    PRD 3.8: "Skipping a rung — going straight to the tribunal from an informal
    conference — or repeating a rung already used on that assessment is
    `ERR_FORUM_SEQUENCE_INVALID`"
    PRD 3.8: "The request body also accepts a `filed_date`, for symmetry with the
    paper form, but the value is ignored: the stored `filed_date` is always the
    logical clock date at the moment of filing."

    Design: Corner/errors/the_forum_ladder_is_checked_before_the_escalation_clock
    """
    ctx = _decided_informal_conference()
    conference = ctx["proceeding"]
    assert conference["filed_date"] == PROTEST_FILED_DATE
    assert conference["decided_date"] == DECISION_DATE
    assert conference["tolled_days"] == 14
    assert conference["status"] == "DECIDED"
    assert conference["outcome"] == "SUSTAINED"
    assert conference["escalation_deadline_date"] == ESCALATION_DEADLINE
    assert conference["presiding_officer_user_id"] == APPEALS_OFFICER_USER_ID

    set_clock_date(INSIDE_THE_WINDOW)
    response = api_client.create_appeal_proceeding(
        _protest_body(
            ctx["assessment"]["id"], "TAX_TRIBUNAL", conference["id"], INSIDE_THE_WINDOW
        ),
        ctx["taxpayer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_FORUM_SEQUENCE_INVALID.value, 409)

    _, meta = validate_paginated(
        api_client.list_appeal_proceedings(
            APPEALS, params={"assessment_id": ctx["assessment"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_the_correct_rung_filed_one_day_late_is_a_closed_escalation_window():
    """Day 30 was the last day, so day 31 fails on the clock and not the ladder.

    PRD 3.8: "The `escalation_deadline_date` is set to `decided_date` plus the
    escalation window of the next rung up — 30 calendar days to reach the
    `ADMINISTRATIVE_APPEAL` and 30 calendar days to reach the `TAX_TRIBUNAL`"
    PRD 3.8: "filing after the predecessor's `escalation_deadline_date` is
    `ERR_ESCALATION_WINDOW_CLOSED`"

    Design: Corner/errors/the_forum_ladder_is_checked_before_the_escalation_clock
    """
    ctx = _decided_informal_conference()
    conference = ctx["proceeding"]
    assert conference["escalation_deadline_date"] == ESCALATION_DEADLINE

    set_clock_date(PAST_THE_WINDOW)
    response = api_client.create_appeal_proceeding(
        _protest_body(
            ctx["assessment"]["id"],
            "ADMINISTRATIVE_APPEAL",
            conference["id"],
            PAST_THE_WINDOW,
        ),
        ctx["taxpayer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_WINDOW_CLOSED.value, 409)

    proceedings, meta = validate_paginated(
        api_client.list_appeal_proceedings(
            APPEALS, params={"assessment_id": ctx["assessment"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert proceedings[0]["id"] == conference["id"]

    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "ISSUED"
    assert assessment["collection_hold"] is False
    assert assessment["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS


ONE_CENT_OVER = SMALL_BALANCE_TAX_CENTS + 1
TOKEN_FEE_CENTS = 100


def _small_balance_notice():
    """An issued 4,762-cent notice whose penalty the small-balance pass waived."""
    ctx = setup_issued_assessment(tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS)
    assert ctx["assessment"]["penalty_waived_small_balance"] is True
    assert ctx["assessment"]["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
    return ctx


def _post(assessment, kind, amount_cents):
    return api_client.create_assessment_adjustment(
        create_assessment_adjustment_payload(
            assessment["id"], assessment["version"], amount_cents, kind=kind
        ),
        COLLECTIONS,
    )


def test_a_system_only_kind_is_refused_even_well_inside_the_balance():
    """A 100-cent fee clears the money rule and still fails on its kind.

    PRD 3.7: "Naming any of the five `SYSTEM`-only kinds — `PENALTY_ABATEMENT`,
    `APPEAL_REDUCTION`, `COLLECTION_FEE`, `OIC_WRITEOFF` or `ASSESSMENT_VACATED` —
    is refused with `ERR_ADJUSTMENT_KIND_SYSTEM_ONLY`, because each of those kinds
    has exactly one lawful producer inside the system and permitting a client to
    forge one would break the correspondence between the ledger and the events that
    justify it."

    Design: Corner/errors/the_ledger_endpoint_guards_the_kind_then_the_ceiling
    """
    ctx = _small_balance_notice()
    assessment = ctx["assessment"]

    validate_error(
        _post(assessment, "COLLECTION_FEE", TOKEN_FEE_CENTS),
        ApiErrorId.ERR_ADJUSTMENT_KIND_SYSTEM_ONLY.value,
        422,
    )

    stored = read_assessment(assessment["id"])
    assert stored["version"] == assessment["version"]
    assert stored["total_adjustments_cents"] == 0
    assert stored["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS


def test_a_payment_one_cent_over_the_balance_is_refused_and_the_exact_one_posts():
    """The ledger refuses to over-credit, then accepts the balance to the cent.

    PRD 3.7: "An `amount_cents` greater than the assessment's current
    `balance_due_cents` is refused with `ERR_ADJUSTMENT_EXCEEDS_BALANCE`; the ledger
    never over-credits an assessment into a negative balance."
    PRD 3.7: "A successful posting sets `status` to `POSTED` and `source` to
    `MANUAL`, re-derives the assessment's `total_adjustments_cents` and
    `balance_due_cents`, and, when the balance reaches exactly 0, moves the
    collection axis to `SATISFIED`."
    PRD 3.7: "`amount_paid_cents` is a deliberately separate aggregate that
    accumulates only the cash recorded through an arrangement's payments, not the
    ledger's `PAYMENT` rows; a manually posted `PAYMENT` adjustment flows into
    `total_adjustments_cents` instead."

    Design: Corner/errors/the_ledger_endpoint_guards_the_kind_then_the_ceiling
    """
    ctx = _small_balance_notice()
    assessment = ctx["assessment"]

    validate_error(
        _post(assessment, "PAYMENT", ONE_CENT_OVER),
        ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_BALANCE.value,
        422,
    )
    assert read_assessment(assessment["id"])["total_adjustments_cents"] == 0

    row = validate_success(_post(assessment, "PAYMENT", SMALL_BALANCE_TAX_CENTS), 201)
    assert row["kind"] == "PAYMENT"
    assert row["amount_cents"] == SMALL_BALANCE_TAX_CENTS
    assert row["status"] == "POSTED"
    assert row["source"] == "MANUAL"
    assert row["abatement_pct"] is None

    settled = read_assessment(assessment["id"])
    assert settled["total_adjustments_cents"] == SMALL_BALANCE_TAX_CENTS
    assert settled["amount_paid_cents"] == 0
    assert settled["balance_due_cents"] == 0
    assert settled["total_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert settled["collection_status"] == "SATISFIED"
    assert settled["status"] == "ISSUED"


def test_a_waived_penalty_leaves_nothing_to_abate():
    """Zero penalty is refused outright rather than posting a zero-cent credit.

    PRD 3.7: "Third, if the assessment's `penalty_waived_small_balance` is true the
    request is refused with `ERR_ABATEMENT_NOT_ALLOWED`, because the small-balance
    pass already zeroed the penalty and there is nothing left to abate. An
    assessment whose `penalty_cents` is 0 for any reason is refused the same way."

    Design: Corner/errors/a_waived_penalty_blocks_abatement_and_a_reduction_stops_at_the_balance
    """
    ctx = _small_balance_notice()
    assessment_id = ctx["assessment"]["id"]

    response = api_client.abate_penalty(
        assessment_id, abate_penalty_payload(["FIRST_TIME_COMPLIANT"]), SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_ABATEMENT_NOT_ALLOWED.value, 422)

    stored = read_assessment(assessment_id)
    assert stored["penalty_cents"] == 0
    assert stored["penalty_waived_small_balance"] is True
    assert stored["total_abated_cents"] == 0
    assert stored["total_adjustments_cents"] == 0

    _, meta = validate_paginated(
        api_client.list_assessment_adjustments(
            SUPERVISOR, params={"assessment_id": assessment_id}
        )
    )
    assert meta["total_count"] == 0


REDUCTION_ESCALATION_DEADLINE = "2026-07-31"


def _open_conference_on_the_small_balance():
    """The same 4,762-cent notice, protested the day after it was mailed."""
    ctx = _small_balance_notice()
    set_clock_date(PROTEST_FILED_DATE)
    ctx["proceeding"] = file_protest(ctx["assessment"]["id"], ctx["taxpayer"]["id"])
    assert ctx["proceeding"]["status"] == "OPEN"
    assert ctx["proceeding"]["outcome"] == "NONE"
    assert read_assessment(ctx["assessment"]["id"])["collection_hold"] is True
    return ctx


def _decide(proceeding_id, reduction_amount_cents):
    return api_client.decide_appeal_proceeding(
        proceeding_id,
        decision_payload(
            "REDUCED",
            reduction_amount_cents=reduction_amount_cents,
            decision_rationale="Basis conceded",
        ),
        APPEALS,
    )


def test_a_reduction_one_cent_over_the_balance_leaves_the_proceeding_open():
    """The forum may concede the whole balance but never a cent more.

    PRD 3.8: "The `reduction_amount_cents` is required here and forbidden on the
    other two branches; it must not exceed the assessment's `balance_due_cents`,
    and a larger figure is refused with `ERR_REDUCTION_EXCEEDS_BALANCE`."
    PRD 3.8: "A new proceeding starts at `status` `OPEN` with `outcome` `NONE`, and
    it sets the assessment's `collection_hold` to true."

    Design: Corner/errors/a_waived_penalty_blocks_abatement_and_a_reduction_stops_at_the_balance
    """
    ctx = _open_conference_on_the_small_balance()

    validate_error(
        _decide(ctx["proceeding"]["id"], ONE_CENT_OVER),
        ApiErrorId.ERR_REDUCTION_EXCEEDS_BALANCE.value,
        422,
    )

    still_open = read_proceeding(ctx["proceeding"]["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["outcome"] == "NONE"
    assert read_assessment(ctx["assessment"]["id"])["balance_due_cents"] == (
        SMALL_BALANCE_TAX_CENTS
    )


def test_a_reduction_of_exactly_the_balance_settles_the_notice_through_the_ledger():
    """Conceding the whole balance posts a SYSTEM row that points back at the forum.

    PRD 3.8: "Second, caused by the first, a `SYSTEM` adjustment of kind
    `APPEAL_REDUCTION` is posted for `reduction_amount_cents` with its
    `appeal_proceeding_id` pointing back at this proceeding."
    PRD 3.8: "Third, caused by the second, the assessment's
    `total_adjustments_cents` and `balance_due_cents` are re-derived, and if
    `balance_due_cents` reaches 0 the collection axis moves to `SATISFIED`."
    PRD 3.8: "Whatever the branch, deciding moves `status` from `OPEN` to the
    terminal `DECIDED`, sets `decided_date` to the logical clock date, sets
    `tolled_days` to the whole number of days from `filed_date` to `decided_date`,
    records `presiding_officer_user_id` as the deciding user, clears the
    assessment's `collection_hold` when no other proceeding of that assessment
    remains `OPEN`, and recomputes the audit's `statute_expiry_date` so that the
    days the dispute consumed are added to the limitation period."

    Design: Corner/errors/a_waived_penalty_blocks_abatement_and_a_reduction_stops_at_the_balance
    """
    ctx = _open_conference_on_the_small_balance()
    assessment_id = ctx["assessment"]["id"]

    decided = validate_success(
        _decide(ctx["proceeding"]["id"], SMALL_BALANCE_TAX_CENTS), 200
    )
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "REDUCED"
    assert decided["decided_date"] == PROTEST_FILED_DATE
    assert decided["tolled_days"] == 0
    assert decided["escalation_deadline_date"] == REDUCTION_ESCALATION_DEADLINE

    rows, meta = validate_paginated(
        api_client.list_assessment_adjustments(
            APPEALS, params={"assessment_id": assessment_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["kind"] == "APPEAL_REDUCTION"
    assert rows[0]["amount_cents"] == SMALL_BALANCE_TAX_CENTS
    assert rows[0]["source"] == "SYSTEM"
    assert rows[0]["appeal_proceeding_id"] == ctx["proceeding"]["id"]

    settled = read_assessment(assessment_id)
    assert settled["total_adjustments_cents"] == SMALL_BALANCE_TAX_CENTS
    assert settled["balance_due_cents"] == 0
    assert settled["collection_status"] == "SATISFIED"
    assert settled["status"] == "ISSUED"
    assert settled["collection_hold"] is False


INSTALLMENT_CENTS = 2_381
PROTEST_DEADLINE = "2026-08-29"
DAY_AFTER_PROTEST_DEADLINE = "2026-08-30"


def _requested_plan_on_the_small_balance():
    """Two installments of 2,381 cents requested and left unapproved."""
    ctx = setup_requested_installment_plan(
        monthly_installment_cents=INSTALLMENT_CENTS,
        term_months=2,
        tax_deficiency_cents=SMALL_BALANCE_TAX_CENTS,
    )
    assert ctx["arrangement"]["status"] == "REQUESTED"
    return ctx


def test_a_requested_plan_cannot_take_a_payment_yet():
    """Until collections approves the terms there is no plan to pay into.

    PRD 3.9: "The arrangement must be `APPROVED`; a payment against a `REQUESTED`,
    `COMPLETED`, `DEFAULTED` or `CANCELLED` arrangement is refused with
    `ERR_ARRANGEMENT_NOT_ACTIVE`, which occupies the state tier of the precedence
    order in place of the generic state code."
    PRD 3.9: "The request computes `scheduled_total_cents` —
    `monthly_installment_cents` multiplied by `term_months` for an installment plan,
    and `offer_amount_cents` for an offer in compromise — and lands at `status`
    `REQUESTED` with `payments_made_count` 0, `amount_paid_cents` 0 and `approved_at`
    null."

    Design: Corner/errors/payments_need_an_approved_plan_and_finalization_needs_a_closed_window
    """
    ctx = _requested_plan_on_the_small_balance()

    response = api_client.create_arrangement_payment(
        ctx["arrangement"]["id"], arrangement_payment_payload(INSTALLMENT_CENTS), COLLECTIONS
    )
    validate_error(response, ApiErrorId.ERR_ARRANGEMENT_NOT_ACTIVE.value, 409)

    plan = read_arrangement(ctx["arrangement"]["id"])
    assert plan["status"] == "REQUESTED"
    assert plan["amount_paid_cents"] == 0
    assert plan["payments_made_count"] == 0
    assert plan["scheduled_total_cents"] == SMALL_BALANCE_TAX_CENTS
    assert plan["approved_at"] is None

    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["amount_paid_cents"] == 0
    assert assessment["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert assessment["collection_status"] == "DUE"


def test_finalization_waits_for_the_protest_window_and_then_closes_the_audit():
    """On the deadline the notice is still protestable; a day later it is not.

    PRD 3.6: "An `AuditSupervisor` may finalize an assessment whose `status` is
    `ISSUED` only when every avenue of protest has closed: no proceeding of the
    assessment may be `OPEN`, the logical clock date must be strictly after
    `protest_deadline_date`, and it must be strictly after the
    `escalation_deadline_date` of every `DECIDED` proceeding of that assessment."
    PRD 3.6: "Finalization moves `status` from `ISSUED` to the terminal `FINAL`,
    which cascades the audit from `ASSESSED` to `CLOSED`, which in turn decrements
    the taxpayer's `open_audit_count` by one and so frees that taxpayer to be
    audited again."

    Design: Corner/errors/payments_need_an_approved_plan_and_finalization_needs_a_closed_window
    """
    ctx = _requested_plan_on_the_small_balance()
    assessment_id = ctx["assessment"]["id"]
    assert ctx["assessment"]["protest_deadline_date"] == PROTEST_DEADLINE

    validate_error(
        api_client.finalize_assessment(assessment_id, SUPERVISOR),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZABLE.value,
        409,
    )
    assert read_assessment(assessment_id)["status"] == "ISSUED"

    set_clock_date(DAY_AFTER_PROTEST_DEADLINE)
    finalized = validate_success(
        api_client.finalize_assessment(assessment_id, SUPERVISOR), 200
    )
    assert finalized["status"] == "FINAL"
    assert finalized["balance_due_cents"] == SMALL_BALANCE_TAX_CENTS
    assert finalized["collection_status"] == "DUE"
    assert read_audit(ctx["audit"]["id"])["status"] == "CLOSED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["open_audit_count"] == 0


FIRST_UNIT_DATE = "2026-02-10"
FIRST_UNIT_CENTS = 120_000
SECOND_UNIT_DATE = "2026-05-04"
SECOND_UNIT_CENTS = 80_000


def _fieldwork_with_one_undetermined_unit():
    """An agreed plan demanding two examined units, with one still PENDING."""
    ctx = setup_agreed_methodology(minimum_sample_size=2)
    ctx["unit"] = draw_sample_unit(
        ctx["agreement"]["id"],
        0,
        FIRST_UNIT_DATE,
        FIRST_UNIT_CENTS,
        invoice_reference="RT-901",
    )
    assert ctx["unit"]["error_class"] == "PENDING"
    return ctx


def test_an_undetermined_sample_is_empty_rather_than_merely_short():
    """A PENDING unit was never examined, so the set is empty, not undersized.

    PRD 3.4: "The examined set is exactly those sample units of the audit's agreed
    agreement whose `error_class` is not `PENDING`; undetermined units are excluded
    both from the sums and from the unit count, and units belonging to a superseded
    agreement never contribute anything."
    PRD 3.4: "A projection requested when no unit of the agreed agreement has been
    determined at all — every unit still `PENDING` — is refused with
    `ERR_SAMPLE_SET_EMPTY`, and a projection whose examined count is below the
    agreement's `minimum_sample_size` is refused with `ERR_SAMPLE_SIZE_NOT_MET`."

    Design: Corner/errors/projection_needs_a_determined_unit_and_then_the_agreed_minimum
    """
    ctx = _fieldwork_with_one_undetermined_unit()
    audit_id = ctx["audit"]["id"]

    validate_error(
        api_client.project_sample(audit_id, AUDITOR),
        ApiErrorId.ERR_SAMPLE_SET_EMPTY.value,
        422,
    )

    audit = read_audit(audit_id)
    assert audit["projection_method"] == "NONE"
    assert audit["examined_unit_count"] == 0


def test_a_determined_but_lonely_unit_is_short_of_the_agreed_minimum():
    """Determining the unit changes the complaint from empty to undersized.

    PRD 3.4: "Redetermining a unit takes a new `error_class` and, where that class
    demands it, a new `declared_error_amount_cents`; the system recomputes
    `error_amount_cents` under the same rules, increments the unit's
    `redetermination_count` by one, sets the audit's `projection_status` to `STALE`
    and again cascades any `DRAFT` assessment of the audit to `DRAFT_STALE`."
    PRD 3.4: "a projection whose examined count is below the agreement's
    `minimum_sample_size` is refused with `ERR_SAMPLE_SIZE_NOT_MET`."

    Design: Corner/errors/projection_needs_a_determined_unit_and_then_the_agreed_minimum
    """
    ctx = _fieldwork_with_one_undetermined_unit()
    audit_id = ctx["audit"]["id"]

    redetermined = redetermine_sample_unit(ctx["unit"]["id"], "NO_ERROR")
    assert redetermined["error_class"] == "NO_ERROR"
    assert redetermined["redetermination_count"] == 1
    assert redetermined["error_amount_cents"] == 0

    validate_error(
        api_client.project_sample(audit_id, AUDITOR),
        ApiErrorId.ERR_SAMPLE_SIZE_NOT_MET.value,
        422,
    )

    assert read_agreement(ctx["agreement"]["id"])["examined_unit_count"] == 1
    assert read_audit(audit_id)["projection_status"] == "STALE"


def test_the_second_determined_unit_finally_lets_the_projection_run():
    """Two examined units meet the minimum, and a clean sample projects to zero.

    PRD 3.4: "`sample_error_rate_bp` is the error sum multiplied by 10,000, divided
    by the base sum and rounded half up to a whole basis point — computed and
    reported under both methodologies, even though only ratio estimation uses it
    arithmetically — `projected_deficiency_cents` holds the projected population
    deficiency, `examined_unit_count` holds the examined count, `projection_method`
    records the methodology just applied, and `projection_status` becomes `CURRENT`."

    Design: Corner/errors/projection_needs_a_determined_unit_and_then_the_agreed_minimum
    """
    ctx = _fieldwork_with_one_undetermined_unit()
    redetermine_sample_unit(ctx["unit"]["id"], "NO_ERROR")
    draw_sample_unit(
        ctx["agreement"]["id"],
        0,
        SECOND_UNIT_DATE,
        SECOND_UNIT_CENTS,
        invoice_reference="RT-902",
        error_class="NO_ERROR",
    )

    projected = validate_success(
        api_client.project_sample(ctx["audit"]["id"], AUDITOR), 200
    )
    assert projected["projection_status"] == "CURRENT"
    assert projected["projection_method"] == "RATIO_ESTIMATION"
    assert projected["sample_error_rate_bp"] == 0
    assert projected["projected_deficiency_cents"] == 0
    assert projected["examined_unit_count"] == 2
    assert read_agreement(ctx["agreement"]["id"])["examined_unit_count"] == 2
