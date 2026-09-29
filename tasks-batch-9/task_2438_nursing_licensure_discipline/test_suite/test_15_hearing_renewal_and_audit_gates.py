"""Panel, issuance, renewal, and audit refusals — each one isolated from its neighbours."""
from test_helpers import (
    ANALYST,
    CLOCK_DEFAULT_STAMP,
    INVESTIGATOR,
    PRESIDING,
    THREE_MEMBER_PANEL,
    ApiClient,
    ApiErrorId,
    assert_decimal_equals,
    assert_renewal_dimensions,
    cast_vote,
    change_status,
    decide_audit,
    evidence_request_payload,
    finalize_renewal,
    issue_order,
    mint_license,
    pay_renewal,
    practice_hour_period,
    record_clean_screening,
    record_hearing_event,
    reread_license,
    reread_nurse,
    reread_proceeding,
    reread_renewal,
    request_audit_docs,
    seed_active_license,
    seed_application,
    seed_ce_record,
    seed_convened_proceeding,
    seed_deliberating_proceeding,
    seed_docs_requested_renewal,
    seed_docs_submitted_renewal,
    seed_investigated_complaint,
    seed_licensed_renewal_context,
    seed_noticed_proceeding,
    submit_application,
    submit_audit_docs,
    submit_renewal,
    validate_error,
    validate_paginated,
    validate_success,
    verify_application_qualification,
)


def test_a_panel_of_two_is_seated_but_cannot_convene(api: ApiClient):
    """PRD §3.8: "`CONVENE` is permitted from `NOTICED` or `CONTINUED` and moves
    the proceeding to `HEARING_CONVENED`."

    PRD §3.8: "Two conditions must hold: the `hearing_date` current at the moment
    of the convene call must sit at or after `noticed_at` advanced by
    `notice_period_days`, refused otherwise with `ERR_NOTICE_PERIOD_NOT_MET`; and
    the panel must have quorum, meaning the count of `seated_member_user_ids` less
    `recused_member_user_ids` must be at least 3, refused otherwise with
    `ERR_QUORUM_NOT_MET`."

    PRD §3.8: "The proceeding takes `status` `NOTICED`, stamps `noticed_at` from
    the logical clock, starts `continuance_count` at 0, `votes` as an empty array,
    `sanction_floor_tier` and `adopted_sanction_tier` at `NONE`, and
    `ordered_restriction_codes` as an empty array with `order_issued_at` null."

    Design: Corner/validations/convening_with_only_two_seated_members_returns_quorum_not_met
    """
    ctx = seed_noticed_proceeding(api, ["bm-x1", "bm-x2"])
    assert ctx["proceeding"]["status"] == "NOTICED", (
        "A sub-quorum panel is seated without objection at creation"
    )
    assert ctx["proceeding"]["sanction_floor_tier"] == "NONE"

    refused = api.record_hearing_event(ctx["proceeding_id"], {"event_type": "CONVENE"},
                                       PRESIDING)

    error = validate_error(refused, ApiErrorId.ERR_QUORUM_NOT_MET.value)
    assert error["error_id"] != ApiErrorId.ERR_NOTICE_PERIOD_NOT_MET.value, (
        "The hearing date is forty-five days out, so the notice check passes and "
        "cannot mask the quorum check"
    )
    stored = reread_proceeding(api, ctx["proceeding_id"])
    assert stored["status"] == "NOTICED", (
        f"A refused convene moves nothing, got {stored['status']}"
    )
    assert stored["sanction_floor_tier"] == "NONE", (
        "The floor is frozen by a successful convene only"
    )


def test_a_panel_may_not_order_a_sanction_milder_than_the_frozen_floor(api: ApiClient):
    """PRD §3.8: "The floor index is the base index plus the net score halved and
    rounded **toward positive infinity** — so a net of negative three contributes
    negative one, not negative two — and the result is then clamped to the range 1
    through 6."

    PRD §3.8: "Two conditions must hold: `adopted_sanction_tier` must not be
    `NONE`, and its tier index must be at or above the tier index of the frozen
    `sanction_floor_tier`."

    PRD §3.8: "A panel that adopted a sanction milder than the floor is refused
    with `ERR_SANCTION_BELOW_FLOOR` and the proceeding stays in `DELIBERATION`,
    where it may be reopened and revoted."

    PRD §3.8: "`REOPEN` moves `DELIBERATION` back to `HEARING_CONVENED`, resets
    `adopted_sanction_tier` to `NONE`, clears `votes` back to an empty array so
    the panel must vote again from scratch, and also increments `continuance_count`
    by one."

    Design: Corner/validations/adopting_a_tier_below_the_frozen_floor_returns_sanction_below_floor
    """
    panel = ["bm-s1", "bm-s2", "bm-s3"]
    ctx = seed_deliberating_proceeding(
        api, [("bm-s1", "FINE"), ("bm-s2", "FINE"), ("bm-s3", "REPRIMAND")], panel,
        violation_category="BOUNDARY_VIOLATION",
    )
    assert ctx["proceeding"]["sanction_floor_tier"] == "PROBATION", (
        f"A boundary violation bases at 4 and a net of minus three lifts it down "
        f"by one, got {ctx['proceeding']['sanction_floor_tier']}"
    )
    assert ctx["proceeding"]["status"] == "DELIBERATION"
    assert ctx["proceeding"]["adopted_sanction_tier"] == "FINE", (
        "Two of three seats support tier 2 but none supports tier 3"
    )

    refused = api.issue_order(ctx["proceeding_id"], PRESIDING,
                              {"ordered_restriction_codes": []})

    validate_error(refused, ApiErrorId.ERR_SANCTION_BELOW_FLOOR.value)
    stored = reread_proceeding(api, ctx["proceeding_id"])
    assert stored["status"] == "DELIBERATION", (
        f"The proceeding waits to be revoted, got {stored['status']}"
    )
    assert stored["adopted_sanction_tier"] == "FINE"
    assert stored["order_issued_at"] is None
    credential = reread_license(api, ctx["license_id"])
    assert credential["encumbrance_status"] == "INVESTIGATION_PENDING", (
        "No order issued, so no disciplinary consequence reached the credential"
    )
    assert credential["practice_restriction_codes"] == []
    assert reread_nurse(api, ctx["nurse_id"])["prior_discipline_count"] == 0

    record_hearing_event(api, ctx["proceeding_id"], "REOPEN")
    cast_vote(api, ctx["proceeding_id"], "bm-s1", "PROBATION")
    cast_vote(api, ctx["proceeding_id"], "bm-s2", "PROBATION")
    revoted = record_hearing_event(api, ctx["proceeding_id"], "CLOSE_HEARING")
    assert revoted["adopted_sanction_tier"] == "PROBATION"
    ordered = issue_order(api, ctx["proceeding_id"])
    assert ordered["status"] == "ORDER_ISSUED", (
        f"A tier at the floor may be ordered, got {ordered['status']}"
    )


def test_a_nurse_may_not_hold_two_live_registered_nurse_credentials(api: ApiClient):
    """PRD §3.3: "Issuance is guarded against duplication on two clauses."

    PRD §3.3: "No credential may already reference the same application as its
    `source_application_id`, and — the clause that actually bites in practice —
    the application's nurse must not already hold a credential of the same
    `credential_type` at the same `issuing_board_config_id` whose `license_status`
    is anything other than `LAPSED` or `SURRENDERED`."

    PRD §3.3: "Either violation is refused with `ERR_LICENSE_ALREADY_ISSUED`."

    PRD §3.3: "Re-licensure after a credential has gone `LAPSED` or `SURRENDERED`
    is likewise permitted."

    Design: Corner/validations/second_live_rn_credential_for_the_same_nurse_returns_license_already_issued
    """
    ctx = seed_active_license(api)
    second = seed_application(api, ctx["nurse_id"], ctx["board_id"], ctx["program_id"])
    submit_application(api, second["id"])
    verify_application_qualification(api, second["id"])
    approved = record_clean_screening(api, second["id"])
    assert approved["status"] == "APPROVED", (
        f"The second filing is itself fully qualified, got {approved['status']}"
    )

    refused = api.create_license({"source_application_id": second["id"]}, ANALYST)

    validate_error(refused, ApiErrorId.ERR_LICENSE_ALREADY_ISSUED.value)
    credentials, meta = validate_paginated(
        api.list_licenses(ANALYST, params={"nurse_id": ctx["nurse_id"]})
    )
    assert meta["total_count"] == 1, (
        f"The nurse still holds exactly one credential, got {meta['total_count']}"
    )
    assert credentials[0]["id"] == ctx["license_id"]
    stored = validate_success(api.get_license_application(second["id"], ANALYST))
    assert stored["status"] == "APPROVED", (
        f"A refused mint does not move the application to ISSUED, got "
        f"{stored['status']}"
    )

    change_status(api, ctx["license_id"], "SURRENDERED")
    reissued = mint_license(api, second["id"])
    assert reissued["license_status"] == "ACTIVE", (
        "A surrendered credential is not live, so re-licensure is permitted"
    )


def test_twenty_provisional_credit_hours_cannot_carry_a_renewal_submission(
    api: ApiClient,
):
    """PRD §3.4: "The provisional total must be at or above the board's
    `ce_hours_required` — an exact match passes — and a shortfall is refused with
    `ERR_CE_HOURS_INSUFFICIENT`."

    PRD §3.4: "The **provisional** total, written to `ce_credit_hours_provisional`
    at submit, admits a claim whose `verification_status` is `UNVERIFIED` or
    `VERIFIED`, does not look at `provider_accredited` at all, and does not check
    the accounting window; it is therefore an upper bound."

    PRD §3.4: "The filing begins with `renewal_status` `DRAFT` and `audit_status`
    `NOT_SELECTED`, with `ce_credit_hours_provisional`, `ce_credit_hours_audited`,
    `verified_practice_hours`, `audit_risk_score`, and `submitted_at` all null,
    `fee_applied_cents`, `fee_paid_cents`, `late_days`, and
    `doc_request_cycle_count` all 0, and `practice_hour_periods` an empty array."

    Design: Corner/validations/submitting_a_renewal_with_twenty_ce_hours_returns_ce_hours_insufficient
    """
    ctx = seed_licensed_renewal_context(api, "DRAFT")
    claim = seed_ce_record(api, ctx["renewal_id"], minutes=1200,
                          completion_date="2027-06-01T00:00:00Z")
    assert_decimal_equals(claim["credit_hours"], 20.00, "credit_hours")
    paid = pay_renewal(api, ctx["renewal_id"])
    assert paid["fee_applied_cents"] == 12000
    assert paid["fee_paid_cents"] == 12000

    refused = api.submit_renewal_application(ctx["renewal_id"], ANALYST)

    error = validate_error(refused, ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value)
    assert error["error_id"] != ApiErrorId.ERR_RENEWAL_FEE_UNPAID.value, (
        "The fee is settled, so the fiscal rule is satisfied"
    )
    stored = reread_renewal(api, ctx["renewal_id"])
    assert stored["renewal_status"] == "DRAFT", (
        f"A refused submit leaves the filing at DRAFT, got {stored['renewal_status']}"
    )
    assert stored["submitted_at"] is None
    assert stored["ce_credit_hours_provisional"] is None, (
        "The provisional total is only written by a successful submit"
    )

    seed_ce_record(api, ctx["renewal_id"], minutes=600,
                   completion_date="2027-07-01T00:00:00Z")
    submitted = submit_renewal(api, ctx["renewal_id"])
    assert submitted["renewal_status"] == "SUBMITTED"
    assert_decimal_equals(submitted["ce_credit_hours_provisional"], 30.00,
                          "ce_credit_hours_provisional")


def test_a_fourth_documentation_demand_is_refused_once_the_budget_is_spent(
    api: ApiClient,
):
    """PRD §3.5: "It moves `audit_status` from `SELECTED` to `DOCS_REQUESTED`, or
    from `DOCS_SUBMITTED` back to `DOCS_REQUESTED` when a submission arrives
    incomplete, and each demand increments `doc_request_cycle_count` and clears
    `practice_hour_periods` back to an empty array — a fresh demand discards
    whatever was submitted before."

    PRD §3.5: "The cycle is budgeted: once `doc_request_cycle_count` has reached
    3, no further demand may be issued from either state, and the attempt is
    refused with `ERR_AUDIT_DOC_REQUEST_LIMIT_REACHED`."

    PRD §3.5: "If `verified_practice_hours` is at or above the board's
    `practice_hours_required`, `audit_status` moves from `DOCS_SUBMITTED` to
    `PASSED`; otherwise it moves to `FAILED`."

    Design: Corner/validations/fourth_audit_document_request_returns_audit_doc_request_limit_reached
    """
    periods = [practice_hour_period("2026-08-01T00:00:00Z", "2028-08-01T00:00:00Z", 1000)]
    ctx = seed_docs_submitted_renewal(api, periods)
    for _ in range(2):
        request_audit_docs(api, ctx["renewal_id"])
        submit_audit_docs(api, ctx["renewal_id"], periods)
    spent = reread_renewal(api, ctx["renewal_id"])
    assert spent["doc_request_cycle_count"] == 3, (
        f"Three round trips spend the budget, got {spent['doc_request_cycle_count']}"
    )
    assert spent["audit_status"] == "DOCS_SUBMITTED"

    refused = api.request_audit_documentation(ctx["renewal_id"], ANALYST,
                                              {"note": "round four"})

    error = validate_error(refused, ApiErrorId.ERR_AUDIT_DOC_REQUEST_LIMIT_REACHED.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "DOCS_SUBMITTED is a declared origin state for a demand, so the budget refuses"
    )
    stored = reread_renewal(api, ctx["renewal_id"])
    assert stored["audit_status"] == "DOCS_SUBMITTED"
    assert stored["doc_request_cycle_count"] == 3
    assert stored["practice_hour_periods"] == periods, (
        "The refused demand did not clear the periods already on file"
    )
    decided = decide_audit(api, ctx["renewal_id"])
    assert decided["verified_practice_hours"] == 1000
    assert decided["audit_status"] == "PASSED"


def test_an_audit_decision_needs_at_least_one_employment_period(api: ApiClient):
    """PRD §3.5: "A decision may only be taken when `audit_status` is
    `DOCS_SUBMITTED` and `practice_hour_periods` is a non-empty array; an attempt
    from any other audit state, or on an empty period array, is refused with
    `ERR_AUDIT_DOCS_NOT_SUBMITTED`."

    PRD §2.11: "An audit decision has documentation to decide on: `audit_status`
    is `DOCS_SUBMITTED` and `practice_hour_periods` is a non-empty array.
    Otherwise `ERR_AUDIT_DOCS_NOT_SUBMITTED`."

    PRD §3.5: "The licensee responds by submitting employment periods, which moves
    `audit_status` from `DOCS_REQUESTED` to `DOCS_SUBMITTED` and **overwrites**
    `practice_hour_periods` wholesale with the submitted array rather than
    appending to it."

    Design: Corner/validations/audit_decision_over_an_empty_period_array_returns_audit_docs_not_submitted
    """
    ctx = seed_docs_requested_renewal(api)
    empty = submit_audit_docs(api, ctx["renewal_id"], [])
    assert empty["audit_status"] == "DOCS_SUBMITTED", (
        f"An empty answer still moves the dimension, got {empty['audit_status']}"
    )
    assert empty["practice_hour_periods"] == []

    refused = api.decide_audit(ctx["renewal_id"], ANALYST)

    error = validate_error(refused, ApiErrorId.ERR_AUDIT_DOCS_NOT_SUBMITTED.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "The audit dimension is in the declared origin state; only the array is empty"
    )
    stored = reread_renewal(api, ctx["renewal_id"])
    assert stored["audit_status"] == "DOCS_SUBMITTED"
    assert stored["verified_practice_hours"] is None, (
        "Nothing was totalled, so no figure was recorded"
    )

    request_audit_docs(api, ctx["renewal_id"])
    submit_audit_docs(
        api, ctx["renewal_id"],
        [practice_hour_period("2026-08-01T00:00:00Z", "2028-08-01T00:00:00Z", 1000)],
    )
    decided = decide_audit(api, ctx["renewal_id"])
    assert decided["audit_status"] == "PASSED"
    assert decided["verified_practice_hours"] == 1000


def test_a_failed_practice_hour_audit_blocks_the_grant_but_not_the_denial(
    api: ApiClient,
):
    """PRD §3.4: "Granting requires `renewal_status` `CE_VERIFIED` and an
    `audit_status` of either `NOT_SELECTED` or `PASSED`; a filing whose
    practice-hour audit stands `FAILED` cannot be granted, and the attempt is
    refused with `ERR_PRACTICE_HOURS_INSUFFICIENT`."

    PRD §3.4: "A denial moves `renewal_status` to the terminal `DENIED` and
    performs the compensating fiscal action: the filing's `fee_applied_cents` is
    added to the nurse's `fee_credit_cents` and then set to 0, while
    `fee_paid_cents` and the nurse's `fee_paid_total_cents` are left exactly as
    they were, so the ledger identity of §2.12 still balances."

    PRD §3.4: "A grant moves `renewal_status` to the terminal `RENEWED`, advances
    the credential's `expires_on` by the board's `renewal_period_months` from its
    prior value, returns `license_status` from `EXPIRED` to `ACTIVE` (or leaves an
    `ACTIVE` credential `ACTIVE`), re-runs the privilege determination under
    `RESIDENCY_DECLARED`, and advances the credential's `version` by one."

    Design: Corner/validations/finalising_renewed_after_a_failed_audit_returns_practice_hours_insufficient
    """
    ctx = seed_docs_submitted_renewal(
        api,
        [practice_hour_period("2026-08-01T00:00:00Z", "2028-08-01T00:00:00Z", 500)],
    )
    failed = decide_audit(api, ctx["renewal_id"])
    assert failed["verified_practice_hours"] == 500
    assert_renewal_dimensions(failed, "CE_VERIFIED", "FAILED")

    refused = api.finalize_renewal_application(ctx["renewal_id"],
                                               {"outcome": "RENEWED"}, ANALYST)

    validate_error(refused, ApiErrorId.ERR_PRACTICE_HOURS_INSUFFICIENT.value)
    assert reread_renewal(api, ctx["renewal_id"])["renewal_status"] == "CE_VERIFIED", (
        "A refused grant leaves the filing dimension where it stood"
    )
    credential = reread_license(api, ctx["license_id"])
    assert credential["expires_on"] == "2028-08-01T00:00:00.000Z", (
        f"The refused grant did not advance the term, got {credential['expires_on']}"
    )

    denied = finalize_renewal(api, ctx["renewal_id"], "DENIED")
    assert denied["renewal_status"] == "DENIED"
    assert denied["fee_applied_cents"] == 0, (
        f"The denial zeroes the applied fee, got {denied['fee_applied_cents']}"
    )
    assert denied["fee_paid_cents"] == 12000, (
        "What was received stays received"
    )
    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["fee_credit_cents"] == 12000, (
        f"The applied fee became a credit, got {nurse['fee_credit_cents']}"
    )
    assert nurse["fee_paid_total_cents"] == 12000


def test_a_paid_filing_with_exactly_thirty_credit_hours_submits(api: ApiClient):
    """PRD §3.4: "**Submitting** the filing advances `renewal_status` from `DRAFT`
    to `SUBMITTED`, or resubmits it from `CE_DEFICIENT` to `SUBMITTED`,
    recomputing `ce_credit_hours_provisional` over the current claim set and
    restamping `submitted_at` from the logical clock each time."

    PRD §3.4: "The provisional total must be at or above the board's
    `ce_hours_required` — an exact match passes — and a shortfall is refused with
    `ERR_CE_HOURS_INSUFFICIENT`."

    PRD §3.4: "The fee must be settled: `fee_applied_cents` must be greater than
    zero and `fee_paid_cents` must be at least `fee_applied_cents`, and an
    unassessed or underpaid filing is refused with `ERR_RENEWAL_FEE_UNPAID`."

    PRD §3.4: "Any `fee_credit_cents` the nurse is holding is applied first and
    reduced by the portion it satisfies, and the nurse's `fee_paid_total_cents` is
    increased by the full `fee_applied_cents`."

    Design: Corner/validations/renewal_submit_with_fee_paid_and_thirty_ce_hours_succeeds
    """
    ctx = seed_licensed_renewal_context(api, "DRAFT", clock=None)
    claim = seed_ce_record(api, ctx["renewal_id"], minutes=1800)
    assert_decimal_equals(claim["credit_hours"], 30.00, "credit_hours")
    paid = pay_renewal(api, ctx["renewal_id"])
    assert paid["fee_applied_cents"] == 12000, (
        f"A filing made before expiry carries no surcharge, got "
        f"{paid['fee_applied_cents']}"
    )
    assert paid["fee_paid_cents"] == 12000

    submitted = submit_renewal(api, ctx["renewal_id"])

    assert submitted["renewal_status"] == "SUBMITTED"
    assert_decimal_equals(submitted["ce_credit_hours_provisional"], 30.00,
                          "ce_credit_hours_provisional")
    assert submitted["submitted_at"] == CLOCK_DEFAULT_STAMP, (
        f"submitted_at comes from the logical clock, got {submitted['submitted_at']}"
    )
    assert_renewal_dimensions(submitted, "SUBMITTED", "NOT_SELECTED")
    assert reread_nurse(api, ctx["nurse_id"])["fee_paid_total_cents"] == 12000


def test_a_records_demand_must_name_a_custodian_the_complaint_lists(api: ApiClient):
    """PRD §3.6: "Second, the custodian must be linked to the complaint:
    `custodian_code` must appear in the complaint's `employer_custodian_codes`,
    and a demand served on an unlinked custodian is refused with
    `ERR_CUSTODIAN_NOT_LINKED`."

    PRD §3.6: "First, protected health information requires authorisation: when
    `record_class` is `PATIENT_CHART` or `PHARMACY_DISPENSING`, a non-empty
    `phi_authorization_id` must be present, and its absence is refused with
    `ERR_PHI_AUTHORIZATION_REQUIRED`."

    PRD §3.6: "The other two record classes need no authorisation."

    PRD §3.6: "A new demand takes `status` `REQUESTED` and `page_count` 0, with
    `produced_at` null."

    Design: Corner/validations/employer_record_demand_on_an_unlisted_custodian_returns_custodian_not_linked
    """
    ctx = seed_active_license(api)
    complaint = seed_investigated_complaint(api, ctx["license_id"],
                                           employer_custodian_codes=["MERCY-GEN"])
    assert complaint["employer_custodian_codes"] == ["MERCY-GEN"]
    assert complaint["status"] == "INVESTIGATION_OPEN"
    version = complaint["version"]

    refused = api.create_evidence_request(
        complaint["id"],
        evidence_request_payload(record_class="EMPLOYER_PERSONNEL",
                                 custodian_code="UNLINKED-CLINIC"),
        INVESTIGATOR,
    )

    error = validate_error(refused, ApiErrorId.ERR_CUSTODIAN_NOT_LINKED.value)
    assert error["error_id"] != ApiErrorId.ERR_PHI_AUTHORIZATION_REQUIRED.value, (
        "An employer personnel file is not patient data, so the privacy gate is silent"
    )
    _, meta = validate_paginated(
        api.list_complaint_evidence_requests(complaint["id"], INVESTIGATOR)
    )
    assert meta["total_count"] == 0, (
        f"No demand was created by the refused call, got {meta['total_count']}"
    )
    stored = validate_success(api.get_complaint(complaint["id"], INVESTIGATOR))
    assert stored["version"] == version, (
        f"A refused child create does not bump the parent, got {stored['version']}"
    )

    accepted = validate_success(
        api.create_evidence_request(
            complaint["id"],
            evidence_request_payload(record_class="EMPLOYER_PERSONNEL",
                                     custodian_code="MERCY-GEN"),
            INVESTIGATOR,
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["page_count"] == 0
    assert accepted["produced_at"] is None


def test_the_fourth_continuance_and_a_later_reopening_draw_on_one_spent_budget(
    api: ApiClient,
):
    """PRD §3.8: "`CONTINUE` moves `HEARING_CONVENED` to `CONTINUED`, replaces
    `hearing_date` with the supplied `new_hearing_date`, resets `noticed_at` to
    the logical clock — so the notice period must be satisfied afresh against the
    new date — and increments `continuance_count` by one."

    PRD §3.8: "The two events share one budget of three: while `continuance_count`
    is below 3 either is accepted, and once it has reached 3 neither is, refused
    with `ERR_CONTINUANCE_LIMIT_REACHED`."

    PRD §3.8: "Two continuances and one reopening therefore exhaust the allowance
    jointly."

    Design: Corner/validations/fourth_continuance_request_returns_continuance_limit_reached
    """
    ctx = seed_convened_proceeding(api, THREE_MEMBER_PANEL)
    for new_date in ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
                     "2026-12-01T00:00:00Z"):
        record_hearing_event(api, ctx["proceeding_id"], "CONTINUE",
                             new_hearing_date=new_date)
        record_hearing_event(api, ctx["proceeding_id"], "CONVENE")
    spent = reread_proceeding(api, ctx["proceeding_id"])
    assert spent["continuance_count"] == 3, (
        f"Three continuances spend the budget, got {spent['continuance_count']}"
    )
    assert spent["hearing_date"] == "2026-12-01T00:00:00.000Z"
    assert spent["status"] == "HEARING_CONVENED", (
        "A legal origin state for a further continuance"
    )

    refused = api.record_hearing_event(
        ctx["proceeding_id"],
        {"event_type": "CONTINUE", "new_hearing_date": "2027-01-01T00:00:00Z"},
        PRESIDING,
    )

    error = validate_error(refused, ApiErrorId.ERR_CONTINUANCE_LIMIT_REACHED.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "The state is a declared origin, so only the budget can refuse"
    )
    stored = reread_proceeding(api, ctx["proceeding_id"])
    assert stored["continuance_count"] == 3
    assert stored["hearing_date"] == "2026-12-01T00:00:00.000Z", (
        "The refused continuance did not replace the hearing date"
    )
    assert stored["status"] == "HEARING_CONVENED"

    cast_vote(api, ctx["proceeding_id"], "bm-1", "REPRIMAND")
    cast_vote(api, ctx["proceeding_id"], "bm-2", "REPRIMAND")
    deliberating = record_hearing_event(api, ctx["proceeding_id"], "CLOSE_HEARING")
    assert deliberating["status"] == "DELIBERATION"
    validate_error(
        api.record_hearing_event(ctx["proceeding_id"], {"event_type": "REOPEN"},
                                 PRESIDING),
        ApiErrorId.ERR_CONTINUANCE_LIMIT_REACHED.value,
    )


def test_an_unassessed_renewal_fee_refuses_the_submission_with_payment_required(
    api: ApiClient,
):
    """PRD §3.4: "The fee must be settled: `fee_applied_cents` must be greater
    than zero and `fee_paid_cents` must be at least `fee_applied_cents`, and an
    unassessed or underpaid filing is refused with `ERR_RENEWAL_FEE_UNPAID`."

    PRD §3.4: "**Assessing the fee** is a separate act, performed by the applicant
    or by analyst staff, and it is where lateness is priced."

    PRD §3.4: "`fee_paid_cents` is set equal to `fee_applied_cents`, because
    assessment and receipt happen in the same act."

    PRD §3.4: "Because the renewability check outranks the fiscal check, a submit
    on a credential that is neither `ACTIVE` nor within its grace window reports
    `ERR_LICENSE_NOT_RENEWABLE` even when nothing has been paid."

    Design: Corner/validations/submitting_an_unpaid_renewal_returns_renewal_fee_unpaid
    """
    ctx = seed_licensed_renewal_context(api, "DRAFT", clock=None)
    assert ctx["renewal"]["fee_applied_cents"] == 0, (
        "Creation does not assess the fee"
    )
    assert ctx["renewal"]["fee_paid_cents"] == 0
    claim = seed_ce_record(api, ctx["renewal_id"], minutes=1800)
    assert_decimal_equals(claim["credit_hours"], 30.00, "credit_hours")

    refused = api.submit_renewal_application(ctx["renewal_id"], ANALYST)

    error = validate_error(refused, ApiErrorId.ERR_RENEWAL_FEE_UNPAID.value)
    assert error["error_id"] != ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, (
        "Thirty credit hours meet the requirement exactly"
    )
    assert error["error_id"] != ApiErrorId.ERR_LICENSE_NOT_RENEWABLE.value, (
        "The credential is ACTIVE, so the renewability check passes"
    )
    stored = reread_renewal(api, ctx["renewal_id"])
    assert stored["renewal_status"] == "DRAFT"
    assert stored["submitted_at"] is None

    paid = pay_renewal(api, ctx["renewal_id"])
    assert paid["fee_applied_cents"] == 12000
    assert paid["fee_paid_cents"] == 12000
    submitted = submit_renewal(api, ctx["renewal_id"])
    assert submitted["renewal_status"] == "SUBMITTED", (
        f"The settled fee clears the fiscal gate, got {submitted['renewal_status']}"
    )
