"""Protesting a notice, climbing the ladder and living with what the forum decides."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_arrangement,
    close_fieldwork,
    create_appeal_proceeding_payload,
    decide_proceeding,
    get_success_data,
    issue_assessment,
    list_adjustments,
    make_taxpayer_headers,
    project_sample,
    read_arrangement,
    read_assessment,
    read_audit,
    read_proceeding,
    read_taxpayer,
    recompute_assessment,
    request_installment_plan,
    set_clock_date,
    setup_draft_assessment,
    setup_issued_assessment,
    setup_open_proceeding,
    stale_the_findings,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["audit_supervisor_headers"]

SCOPE_START = "2026-01-01"
SCOPE_END = "2026-06-30"
PRICE_FOR_4762_CENTS = 76_192
ONE_CENT_OF_TAX = 16
PROTEST_DEADLINE = "2026-08-29"
DAY_AFTER_DEADLINE = "2026-08-30"
ESCALATION_DEADLINE = "2026-07-30"
BASIS = "The projection overstates the taxable measure of the sample."


def _purchase(price_cents):
    return {
        "invoice_date": SCOPE_START,
        "purchase_price_cents": price_cents,
        "asset_class": "CONSUMABLE",
    }


def _small_issued_notice():
    """An issued notice of 4,762 cents mailed on the scope's last day."""
    return setup_issued_assessment(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])


def _proceedings_of(assessment_id):
    return get_success_data(
        api_client.list_appeal_proceedings(
            SUPERVISOR, params={"assessment_id": assessment_id}
        )
    )


def _file(ctx, forum="INFORMAL_CONFERENCE", predecessor_proceeding_id=...):
    return api_client.create_appeal_proceeding(
        create_appeal_proceeding_payload(
            ctx["assessment"]["id"],
            forum=forum,
            protest_basis=BASIS,
            predecessor_proceeding_id=predecessor_proceeding_id,
        ),
        make_taxpayer_headers(ctx["taxpayer"]["id"]),
    )


def test_a_protest_filed_the_day_after_day_sixty_is_out_of_time():
    """One day past the deadline the notice can no longer be protested at all.

    PRD 3.8: "A first proceeding must be an `INFORMAL_CONFERENCE` and must be filed
    on or before the assessment's `protest_deadline_date`; day 60 inclusive is still
    open, and a filing after it is refused with `ERR_PROTEST_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/protest_deadline_day_60_inclusive
    """
    ctx = _small_issued_notice()
    assert ctx["assessment"]["notice_mailed_date"] == SCOPE_END
    assert ctx["assessment"]["protest_deadline_date"] == PROTEST_DEADLINE
    set_clock_date(DAY_AFTER_DEADLINE)

    response = _file(ctx)
    validate_error(response, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value, 409)

    assert _proceedings_of(ctx["assessment"]["id"]) == []
    assert read_assessment(ctx["assessment"]["id"])["collection_hold"] is False


def test_a_protest_filed_on_day_sixty_itself_is_timely():
    """The deadline day is still open, and filing puts the balance under hold.

    PRD 3.8: "A new proceeding starts at `status` `OPEN` with `outcome` `NONE`, and
    it sets the assessment's `collection_hold` to true."
    PRD 3.8: "The request body also accepts a `filed_date`, for symmetry with the
    paper form, but the value is ignored: the stored `filed_date` is always the
    logical clock date at the moment of filing."

    Design: Difficulty/boundary_precision_check/protest_deadline_day_60_inclusive
    """
    ctx = _small_issued_notice()
    set_clock_date(PROTEST_DEADLINE)

    proceeding = validate_success(_file(ctx), 201)

    assert proceeding["forum"] == "INFORMAL_CONFERENCE"
    assert proceeding["status"] == "OPEN"
    assert proceeding["outcome"] == "NONE"
    assert proceeding["filed_date"] == PROTEST_DEADLINE
    assert len(_proceedings_of(ctx["assessment"]["id"])) == 1
    assert read_assessment(ctx["assessment"]["id"])["collection_hold"] is True


def test_the_next_rung_cannot_be_filed_while_the_conference_is_still_open():
    """An undecided predecessor blocks the escalation and writes no second proceeding.

    PRD 3.8: "A proceeding at a higher forum must name a `predecessor_proceeding_id`,
    that predecessor must sit at the immediately preceding forum, and it must be
    `DECIDED`."

    Design: Difficulty/cross_entity_state_dependency/escalation_requires_a_decided_predecessor_proceeding
    """
    ctx = setup_open_proceeding(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])
    assert ctx["proceeding"]["status"] == "OPEN"

    response = _file(
        ctx,
        forum="ADMINISTRATIVE_APPEAL",
        predecessor_proceeding_id=ctx["proceeding"]["id"],
    )
    validate_error(response, ApiErrorId.ERR_PREDECESSOR_NOT_DECIDED.value, 409)

    assert len(_proceedings_of(ctx["assessment"]["id"])) == 1


def test_the_next_rung_opens_once_the_conference_has_been_decided():
    """A decision closes the hold and opens the escalation window the next rung uses.

    PRD 3.8: "The `escalation_deadline_date` is set to `decided_date` plus the
    escalation window of the next rung up — 30 calendar days to reach the
    `ADMINISTRATIVE_APPEAL` and 30 calendar days to reach the `TAX_TRIBUNAL` — and
    is null when the deciding forum is the `TAX_TRIBUNAL`, because there is no next
    rung, or when the outcome is `REMANDED`, because the notice being appealed no
    longer exists."
    PRD 3.8: "A `SUSTAINED` decision at a lower forum leaves the assessment `ISSUED`
    with a fresh escalation window running."

    Design: Difficulty/cross_entity_state_dependency/escalation_requires_a_decided_predecessor_proceeding
    """
    ctx = setup_open_proceeding(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])

    decided = decide_proceeding(ctx["proceeding"]["id"], "SUSTAINED")
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "SUSTAINED"
    assert decided["tolled_days"] == 0
    assert decided["escalation_deadline_date"] == ESCALATION_DEADLINE
    released = read_assessment(ctx["assessment"]["id"])
    assert released["collection_hold"] is False
    assert released["status"] == "ISSUED"
    assert released["balance_due_cents"] == 4_762

    escalated = validate_success(
        _file(
            ctx,
            forum="ADMINISTRATIVE_APPEAL",
            predecessor_proceeding_id=decided["id"],
        ),
        201,
    )
    assert escalated["forum"] == "ADMINISTRATIVE_APPEAL"
    assert escalated["status"] == "OPEN"
    assert escalated["predecessor_proceeding_id"] == decided["id"]
    assert read_assessment(ctx["assessment"]["id"])["collection_hold"] is True


def _reduced_to_zero():
    """A delinquent taxpayer's arranged notice wiped out by an appeals reduction."""
    ctx = setup_issued_assessment(
        taxpayer_overrides={"compliance_status": "DELINQUENT"},
        purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)],
    )
    assert ctx["assessment"]["balance_due_cents"] == 4_762
    ctx["arrangement"] = request_installment_plan(ctx["assessment"]["id"], 4_762, 1)
    approve_arrangement(ctx["arrangement"]["id"])
    ctx["proceeding"] = validate_success(_file(ctx), 201)
    ctx["decision"] = decide_proceeding(
        ctx["proceeding"]["id"], "REDUCED", reduction_amount_cents=4_762
    )
    return ctx


def test_a_full_reduction_credits_the_ledger_and_clears_the_balance():
    """The credit is a system row that points back at the proceeding that granted it.

    PRD 3.8: "Second, caused by the first, a `SYSTEM` adjustment of kind
    `APPEAL_REDUCTION` is posted for `reduction_amount_cents` with its
    `appeal_proceeding_id` pointing back at this proceeding."
    PRD 3.8: "Third, caused by the second, the assessment's `total_adjustments_cents`
    and `balance_due_cents` are re-derived, and if `balance_due_cents` reaches 0 the
    collection axis moves to `SATISFIED`."

    Design: Difficulty/transitive_cascade/appeal_reduction_five_hop_cascade_to_taxpayer_compliance
    """
    ctx = _reduced_to_zero()

    rows = list_adjustments(assessment_id=ctx["assessment"]["id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == "APPEAL_REDUCTION"
    assert rows[0]["source"] == "SYSTEM"
    assert rows[0]["status"] == "POSTED"
    assert rows[0]["amount_cents"] == 4_762
    assert rows[0]["appeal_proceeding_id"] == ctx["proceeding"]["id"]

    after = read_assessment(ctx["assessment"]["id"])
    assert after["total_adjustments_cents"] == 4_762
    assert after["balance_due_cents"] == 0
    assert after["collection_status"] == "SATISFIED"
    assert after["collection_hold"] is False


def test_a_full_reduction_reaches_the_arrangement_and_the_compliance_flag():
    """With nothing left to pay, the plan completes and the delinquency clears.

    PRD 3.8: "Fourth, caused by the third, every payment arrangement of that
    assessment whose `status` is `REQUESTED` or `APPROVED` moves to `COMPLETED` —
    there is nothing left to pay."
    PRD 3.8: "Fifth, caused by the fourth, the taxpayer's `compliance_status` is
    recomputed to `COMPLIANT`, provided the taxpayer has no other assessment whose
    `collection_status` is `REFERRED`."

    Design: Difficulty/transitive_cascade/appeal_reduction_five_hop_cascade_to_taxpayer_compliance
    """
    ctx = _reduced_to_zero()

    assert read_arrangement(ctx["arrangement"]["id"])["status"] == "COMPLETED"
    assert read_taxpayer(ctx["taxpayer"]["id"])["compliance_status"] == "COMPLIANT"


def _remanded_after_an_earlier_reopen():
    """A notice reopened once by the supervisor and then remanded by the conference."""
    ctx = setup_draft_assessment(purchase_specs=[_purchase(PRICE_FOR_4762_CENTS)])
    stale_the_findings(ctx, purchase_price_cents=ONE_CENT_OF_TAX)
    assert read_audit(ctx["audit"]["id"])["reopen_count"] == 1

    project_sample(ctx["audit"]["id"])
    ctx["assessment"] = recompute_assessment(ctx["assessment"]["id"])
    close_fieldwork(ctx["audit"]["id"])
    ctx["assessment"] = issue_assessment(ctx["assessment"]["id"], SCOPE_END)
    assert ctx["assessment"]["balance_due_cents"] == 5_001

    ctx["proceeding"] = validate_success(_file(ctx), 201)
    ctx["decision"] = decide_proceeding(ctx["proceeding"]["id"], "REMANDED")
    return ctx


def test_a_remand_vacates_the_whole_notice_it_was_appealing():
    """The balance is written off in full and the collection axis goes back to sleep.

    PRD 3.8: "It then vacates the notice: the assessment moves from `ISSUED` to the
    terminal `WITHDRAWN`, a `SYSTEM` adjustment of kind `ASSESSMENT_VACATED` is
    posted for the whole remaining `balance_due_cents` so that the balance falls to
    exactly 0, `collection_status` is reset to `NOT_DUE`, `collection_hold` is
    cleared, and every payment arrangement of the assessment in `REQUESTED` or
    `APPROVED` moves to the terminal `CANCELLED` — with an arrangement that had been
    `APPROVED` also returning the collection axis to `NOT_DUE` as part of that
    vacate."

    Design: Difficulty/non_linear_state_machine/audit_reopen_then_remand_returns_to_fieldwork_twice
    """
    ctx = _remanded_after_an_earlier_reopen()

    after = read_assessment(ctx["assessment"]["id"])
    assert after["status"] == "WITHDRAWN"
    assert after["collection_status"] == "NOT_DUE"
    assert after["collection_hold"] is False
    assert after["balance_due_cents"] == 0

    rows = list_adjustments(assessment_id=ctx["assessment"]["id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == "ASSESSMENT_VACATED"
    assert rows[0]["source"] == "SYSTEM"
    assert rows[0]["amount_cents"] == 5_001


def test_a_remand_sends_the_audit_back_to_fieldwork_for_the_second_time():
    """The audit counts both trips back, and its findings need projecting again.

    PRD 3.8: "Finally it reopens the audit: the audit moves from `ASSESSED` back to
    `FIELDWORK`, its `reopen_count` increments by one and its `projection_status`
    becomes `STALE`, so the auditor must revisit the findings and project again
    before any replacement notice can be drafted."
    PRD 3.4: "Reopening increments `reopen_count` by one and unfreezes the finding
    set."

    Design: Difficulty/non_linear_state_machine/audit_reopen_then_remand_returns_to_fieldwork_twice
    """
    ctx = _remanded_after_an_earlier_reopen()

    audit = read_audit(ctx["audit"]["id"])
    assert audit["status"] == "FIELDWORK"
    assert audit["reopen_count"] == 2
    assert audit["projection_status"] == "STALE"

    proceeding = read_proceeding(ctx["proceeding"]["id"])
    assert proceeding["status"] == "DECIDED"
    assert proceeding["outcome"] == "REMANDED"
    assert proceeding["tolled_days"] == 0
    assert proceeding["escalation_deadline_date"] is None
