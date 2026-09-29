"""Fraud-case investigation, disposition cascades, BSA referrals and closure."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_bsa_referral,
    assert_fraud_case,
    assert_same_instant,
    advance_case,
    create_active_account,
    dispose_case,
    draft_referral,
    legal_review_subpoena,
    new_subpoena,
    open_case,
    read_account,
    read_case,
    read_check_hold,
    read_customer,
    read_review,
    settle_item,
    setup_submitted_review,
    submit_referral,
    take_deposit,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
COUNSEL_2 = TEST_USERS["counsel_2_headers"]


# ===========================================================================
# The mule substantiation cascade
# ===========================================================================
def _investigating_mule_case_over_a_submitted_review(**overrides):
    scenario = setup_submitted_review(**overrides)
    case = open_case(scenario["account_id"], "MULE")
    advance_case(case["id"])
    scenario.update({"case": case, "case_id": case["id"]})
    return scenario


def test_mule_substantiation_schedules_the_account_closure(api, analyst_headers):
    """PRD §3.7: "`SUBSTANTIATE` moves the case `INVESTIGATING → SUBSTANTIATED` and
    records `disposition_note`. For a `MULE` case the cascade then runs three
    further hops. The primary account is forced to `lifecycle_status` `RESTRICTED`;
    its `closure_scheduled_at` is set to the logical clock advanced by ten calendar
    days — the statutory notice period the depositor gets before the relationship
    is shut — and its `closure_reason` is set to `MULE_SUBSTANTIATED`."

    Design: Difficulty/transitive_cascade/mule_substantiation_cascades_account_then_holds_then_override_reviews
    """
    scenario = _investigating_mule_case_over_a_submitted_review(
        legal_name="Marcus Iyengar", tin_last4="3145", kyc_tier="TIER_2", watchlist_hit=False
    )

    disposed = validate_success(
        api.dispose_fraud_case(
            scenario["case_id"],
            {
                "decision": "SUBSTANTIATE",
                "disposition_note": "Third-party funds moved through the account",
            },
            SUPERVISOR,
        )
    )
    assert_fraud_case(disposed)
    assert disposed["status"] == "SUBSTANTIATED"

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["lifecycle_status"] == "RESTRICTED"
    assert account["closure_reason"] == "MULE_SUBSTANTIATED"
    assert_same_instant(
        account["closure_scheduled_at"], "2026-08-11T00:00:00Z", "closure_scheduled_at"
    )


def test_mule_substantiation_retypes_active_holds_and_supersedes_live_reviews(
    api, analyst_headers
):
    """PRD §3.7: "Because the account has acquired a scheduled closure, every check
    hold in `ACTIVE` status on that account's deposited items has its `hold_type`
    rewritten to `EXCEPTION_FRAUD` and its `hold_release_at` rewritten to that same
    `closure_scheduled_at`, while its `held_amount_cents` is left untouched — the
    funds stay held until the account closes. And because those holds were retyped,
    every early-release review against them whose status is `DRAFT`, `SUBMITTED`,
    `RETURNED_FOR_INFO`, or `APPROVED` is moved to `SUPERSEDED`, so no pending or
    approved release survives a mule substantiation."
    PRD §3.3: "2. Otherwise, if the account's age in whole days is *less than* 30,
    the hold is `EXCEPTION_NEW_ACCOUNT`."

    Design: Difficulty/transitive_cascade/mule_substantiation_cascades_account_then_holds_then_override_reviews
    """
    scenario = _investigating_mule_case_over_a_submitted_review(
        legal_name="Marcus Iyengar", tin_last4="3145", kyc_tier="TIER_2", watchlist_hit=False
    )
    assert scenario["hold"]["hold_type"] == "EXCEPTION_NEW_ACCOUNT"

    dispose_case(
        scenario["case_id"], "SUBSTANTIATE", "Third-party funds moved through the account"
    )

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["hold_type"] == "EXCEPTION_FRAUD"
    assert_same_instant(hold["hold_release_at"], "2026-08-11T00:00:00Z", "hold_release_at")
    assert hold["status"] == "ACTIVE", "The funds stay held until the account closes"
    assert hold["held_amount_cents"] == 7500

    review = read_review(scenario["review_id"], analyst_headers)
    assert review["status"] == "SUPERSEDED", (
        "No pending release survives a mule substantiation"
    )


# ===========================================================================
# The closure ladder: preservation hold outranks the referral prerequisite
# ===========================================================================
def _substantiated_case_under_a_live_preservation_hold():
    scenario = create_active_account(
        legal_name="Yusuf Aldridge", tin_last4="7311", kyc_tier="TIER_2", watchlist_hit=False
    )
    case = open_case(scenario["account_id"], "MULE")
    advance_case(case["id"])
    dispose_case(case["id"], "SUBSTANTIATE", "Funnel account confirmed")
    subpoena = new_subpoena(
        scenario["customer_id"],
        issuing_agency="US Postal Inspection Service",
        docket_number="26-CR-0448",
        response_due_at="2026-09-01T00:00:00Z",
        preservation_start_at="2026-08-01T00:00:00Z",
        preservation_end_at="2026-12-01T00:00:00Z",
    )
    scenario.update(
        {"case": case, "case_id": case["id"], "subpoena": subpoena, "subpoena_id": subpoena["id"]}
    )
    return scenario


def test_a_live_preservation_hold_blocks_closure_before_the_referral_check_runs(
    api, analyst_headers
):
    """PRD §3.7: "**Closure.** A `FraudSupervisor` closes a disposed case. Two
    gates apply beyond the state check. The owning depositor's
    `preservation_hold_active` must be false, else `ERR_PRESERVATION_HOLD_ACTIVE`
    (HTTP 409) — records under a live law-enforcement preservation obligation are
    not shut away. And when the case's status immediately before the call is
    `SUBSTANTIATED`, at least one referral drawn from it must be in `ACCEPTED`,
    else `ERR_BSA_REFERRAL_REQUIRED` (HTTP 409). No referral is required to close
    an unsubstantiated case."
    PRD §2.10: "13. **Duty separation and preservation holds,** at the same rank:
    `ERR_SEGREGATION_OF_DUTIES` and `ERR_PRESERVATION_HOLD_ACTIVE`."
    PRD §2.10: "18. **Referral prerequisite for closure:**
    `ERR_BSA_REFERRAL_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/case_close_preservation_hold_outranks_bsa_referral_requirement
    """
    scenario = _substantiated_case_under_a_live_preservation_hold()

    validate_error(
        api.close_fraud_case(scenario["case_id"], SUPERVISOR),
        ApiErrorId.ERR_PRESERVATION_HOLD_ACTIVE.value,
    )

    assert read_customer(scenario["customer_id"], analyst_headers)["preservation_hold_active"] is True
    assert read_case(scenario["case_id"], analyst_headers)["status"] == "SUBSTANTIATED"


def test_the_referral_prerequisite_surfaces_once_the_preservation_hold_lifts(
    api, analyst_headers
):
    """PRD §3.7: "And when the case's status immediately before the call is
    `SUBSTANTIATED`, at least one referral drawn from it must be in `ACCEPTED`,
    else `ERR_BSA_REFERRAL_REQUIRED` (HTTP 409). No referral is required to close
    an unsubstantiated case."
    PRD §3.9: "`OBJECTED` and `QUASHED` fall outside the holding set immediately,
    so `preservation_hold_active` drops to false — unless another subpoena on the
    same depositor still holds it."
    PRD §3.7: "`SUBSTANTIATE` moves the case `INVESTIGATING → SUBSTANTIATED` and
    records `disposition_note`."

    Design: Difficulty/priority_pair_validation_conflict/case_close_preservation_hold_outranks_bsa_referral_requirement
    """
    scenario = _substantiated_case_under_a_live_preservation_hold()
    validate_error(
        api.close_fraud_case(scenario["case_id"], SUPERVISOR),
        ApiErrorId.ERR_PRESERVATION_HOLD_ACTIVE.value,
    )

    legal_review_subpoena(scenario["subpoena_id"], COUNSEL)
    validate_success(
        api.respond_to_subpoena(
            scenario["subpoena_id"],
            {"disposition": "OBJECT", "production_note": "Overbroad; objection filed"},
            COUNSEL_2,
        )
    )

    customer = read_customer(scenario["customer_id"], analyst_headers)
    assert customer["preservation_hold_active"] is False

    validate_error(
        api.close_fraud_case(scenario["case_id"], SUPERVISOR),
        ApiErrorId.ERR_BSA_REFERRAL_REQUIRED.value,
    )

    assert read_case(scenario["case_id"], analyst_headers)["status"] == "SUBSTANTIATED"
    assert read_account(scenario["account_id"], analyst_headers)["lifecycle_status"] == "RESTRICTED"


# ===========================================================================
# The investigation loop
# ===========================================================================
def test_unsubstantiate_then_reopen_swings_the_account_and_bumps_reopen_count(
    api, analyst_headers
):
    """PRD §3.7: "`UNSUBSTANTIATE` moves the case `INVESTIGATING → UNSUBSTANTIATED`
    and records `disposition_note`. Because the case has been cleared, the primary
    account is reinstated `RESTRICTED → ACTIVE` with `closure_scheduled_at` and
    `closure_reason` cleared to null — but only when no *other* case on that
    account is in `OPENED`, `INVESTIGATING`, or `SUBSTANTIATED`. A second live case
    keeps the account restricted."
    PRD §3.7: "`REOPEN` moves the case `UNSUBSTANTIATED → INVESTIGATING`,
    increments `reopen_count` by 1, and, because the case is live again, drives the
    primary account `ACTIVE → RESTRICTED`. This closes the investigation loop
    `INVESTIGATING → UNSUBSTANTIATED → INVESTIGATING`."

    Design: Corner/state_machines/fraud_case_reopen_loop_increments_reopen_count_and_re_restricts_the_account
    """
    scenario = create_active_account(legal_name="Reopen Loop Depositor", tin_last4="0010")
    case = open_case(scenario["account_id"], "MULE")
    advance_case(case["id"])

    cleared = validate_success(
        api.dispose_fraud_case(
            case["id"],
            {"decision": "UNSUBSTANTIATE",
             "disposition_note": "Documentation clears the depositor"},
            SUPERVISOR,
        )
    )
    assert cleared["status"] == "UNSUBSTANTIATED"
    assert cleared["reopen_count"] == 0

    reinstated = read_account(scenario["account_id"], analyst_headers)
    assert reinstated["lifecycle_status"] == "ACTIVE"
    assert reinstated["closure_scheduled_at"] is None

    reopened = validate_success(
        api.dispose_fraud_case(
            case["id"],
            {"decision": "REOPEN", "disposition_note": "New counterparty evidence"},
            SUPERVISOR,
        )
    )
    assert reopened["status"] == "INVESTIGATING"
    assert reopened["reopen_count"] == 1

    assert read_account(scenario["account_id"], analyst_headers)["lifecycle_status"] == "RESTRICTED"


def test_closing_an_unsubstantiated_case_twice_is_refused_the_second_time(api, analyst_headers):
    """PRD §3.7: "Every operation on a case checks that the case is in the state
    that operation expects, and all such failures report `ERR_CASE_INVALID_STATE`
    (HTTP 409): advancing requires `OPENED`; a disposition of `SUBSTANTIATE` or
    `UNSUBSTANTIATE` requires `INVESTIGATING`; a disposition of `REOPEN` requires
    `UNSUBSTANTIATED`; and closing requires `SUBSTANTIATED` or `UNSUBSTANTIATED`."
    PRD §3.7: "From `UNSUBSTANTIATED`, no account transition occurs at all — the
    account keeps whatever `lifecycle_status` the unsubstantiating disposition
    already produced."
    PRD §3.7: "No referral is required to close an unsubstantiated case."

    Design: Corner/state_machines/closing_an_unsubstantiated_case_twice_rejects_the_second_attempt
    """
    scenario = create_active_account(legal_name="Terminal Case Depositor", tin_last4="0012")
    case = open_case(scenario["account_id"], "MULE")
    advance_case(case["id"])
    dispose_case(case["id"], "UNSUBSTANTIATE", "No suspicious pattern")

    closed = validate_success(api.close_fraud_case(case["id"], SUPERVISOR))
    assert closed["status"] == "CLOSED"

    validate_error(
        api.close_fraud_case(case["id"], SUPERVISOR),
        ApiErrorId.ERR_CASE_INVALID_STATE.value,
    )

    assert read_account(scenario["account_id"], analyst_headers)["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# Duplicate suppression is keyed on (account, case_type)
# ===========================================================================
def test_a_second_mule_case_is_refused_while_a_kiting_case_is_permitted(api, analyst_headers):
    """PRD §3.7: "Duplicate suppression is by type: no second case of the same
    `case_type` may be opened against the same account while an existing one is
    `OPENED`, `INVESTIGATING`, or `SUBSTANTIATED`, and an attempt is refused with
    `ERR_DUPLICATE_OPEN_CASE`. A `MULE` case and a `KITING` case may therefore be
    live on the same account simultaneously."
    PRD §3.7: "A manually opened case is recorded with `status` `OPENED` and
    `detection_source` `ANALYST_MANUAL`, its `kiting_score` and `scan_mode` stay
    null, and its `cycle_account_ids` stays empty."
    PRD §3.1: "`open_fraud_case_count` is the number of fraud cases whose primary
    account belongs to this depositor and whose status is `OPENED` or
    `INVESTIGATING`."

    Design: Corner/validations/second_open_mule_case_on_one_account_is_rejected_while_a_kiting_case_is_allowed
    """
    scenario = create_active_account(legal_name="Duplicate Case Depositor", tin_last4="0031")
    open_case(scenario["account_id"], "MULE")

    validate_error(
        api.create_fraud_case(
            {"primary_account_id": scenario["account_id"], "case_type": "MULE"}, analyst_headers
        ),
        ApiErrorId.ERR_DUPLICATE_OPEN_CASE.value,
    )

    kiting = validate_success(
        api.create_fraud_case(
            {"primary_account_id": scenario["account_id"], "case_type": "KITING"}, analyst_headers
        ),
        201,
    )
    assert kiting["detection_source"] == "ANALYST_MANUAL"
    assert kiting["case_type"] == "KITING"
    assert kiting["status"] == "OPENED"
    assert kiting["kiting_score"] is None
    assert kiting["scan_mode"] is None
    assert kiting["cycle_account_ids"] == []

    _rows, meta = validate_paginated(
        api.list_account_fraud_cases(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 2

    customer = read_customer(scenario["customer_id"], analyst_headers)
    assert customer["open_fraud_case_count"] == 2


def test_case_opening_side_effects_are_visible_on_the_very_next_read(api, analyst_headers):
    """PRD §3.7: "Its `exposure_at_risk_cents` is computed at once from the primary
    account's `held_amount_cents`, and the primary account transitions
    `ACTIVE → RESTRICTED`."
    PRD §2.8: "A fraud case's `exposure_at_risk_cents` is always the sum of
    `held_amount_cents` over the case's primary account plus every account named in
    the case's `cycle_account_ids`, deduplicated, and it is recomputed on every
    operation that changes any of those accounts' held totals."
    PRD §3.1: "`open_fraud_case_count` is the number of fraud cases whose primary
    account belongs to this depositor and whose status is `OPENED` or
    `INVESTIGATING`."

    Design: Corner/consistency_model/case_opening_side_effects_are_readable_in_the_immediately_following_request
    """
    scenario = create_active_account(
        legal_name="Immediate Consistency Depositor", tin_last4="0046"
    )
    take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)

    case = validate_success(
        api.create_fraud_case(
            {"primary_account_id": scenario["account_id"], "case_type": "MULE"}, analyst_headers
        ),
        201,
    )
    assert case["exposure_at_risk_cents"] == 7500, (
        "The creation response itself already carries the computed exposure"
    )

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["lifecycle_status"] == "RESTRICTED"
    assert account["held_amount_cents"] == 7500

    customer = read_customer(scenario["customer_id"], analyst_headers)
    assert customer["open_fraud_case_count"] == 1

    rows, meta = validate_paginated(
        api.list_account_fraud_cases(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == case["id"]


# ===========================================================================
# The BSA referral loop and its frozen aggregate
# ===========================================================================
def test_referral_returned_then_refiled_then_accepted_becomes_terminal(api, analyst_headers,
                                                                       bsa_officer_headers):
    """PRD §3.7: "Filing the referral is also a `FraudAnalyst` action and is
    permitted from `DRAFT` or from `RETURNED`; from any other status it is
    `ERR_REFERRAL_INVALID_STATE` (HTTP 409), and if the parent case is no longer
    `SUBSTANTIATED` it is `ERR_CASE_NOT_SUBSTANTIATED`. Both edges land in
    `SUBMITTED` and stamp `submitted_at`; the edge out of `RETURNED` additionally
    increments `revision_count` by 1, closing the loop
    `SUBMITTED → RETURNED → SUBMITTED`."
    PRD §3.7: "A `BsaOfficer` adjudicates a filed referral, and only one in
    `SUBMITTED` — anything else is `ERR_REFERRAL_INVALID_STATE`."
    PRD §3.7: "`ACCEPT` moves the referral `SUBMITTED → ACCEPTED`, stamping
    `adjudicated_by_user_id` and `adjudicated_at`, and makes the parent case
    eligible for closure. `RETURN` moves it `SUBMITTED → RETURNED` with the
    `return_reason` recorded, and the analyst may revise and re-file."
    PRD §3.7: "The referral is created in `DRAFT` with `drafted_by_user_id` taken
    from `X-User-ID`, `aggregate_amount_cents` 0, `revision_count` 0, and
    `adjudicated_by_user_id`, `return_reason`, `submitted_at`, and `adjudicated_at`
    all null."

    Design: Corner/state_machines/bsa_referral_returned_then_resubmitted_then_accepted_and_locked
    """
    scenario = create_active_account(legal_name="Referral Loop Depositor", tin_last4="0011")
    case = open_case(scenario["account_id"], "MULE")
    advance_case(case["id"])
    dispose_case(case["id"], "SUBSTANTIATE", "Funnel behaviour confirmed")

    referral = draft_referral(
        case["id"],
        narrative="Rapid pass-through of third-party deposits.",
        suspected_activity_code="MULE_ACTIVITY",
    )
    assert_bsa_referral(referral)
    assert referral["status"] == "DRAFT"

    filed = submit_referral(referral["id"])
    assert filed["status"] == "SUBMITTED"
    assert filed["aggregate_amount_cents"] == 0, (
        "The account holds no PENDING or RETURNED deposited item"
    )

    returned = validate_success(
        api.adjudicate_bsa_referral(
            referral["id"],
            {"decision": "RETURN", "return_reason": "Narrative lacks counterparty detail"},
            bsa_officer_headers,
        )
    )
    assert returned["status"] == "RETURNED"

    refiled = submit_referral(referral["id"])
    assert refiled["status"] == "SUBMITTED"
    assert refiled["revision_count"] == 1

    accepted = validate_success(
        api.adjudicate_bsa_referral(referral["id"], {"decision": "ACCEPT"}, bsa_officer_headers)
    )
    assert accepted["status"] == "ACCEPTED"

    validate_error(
        api.adjudicate_bsa_referral(
            referral["id"], {"decision": "RETURN", "return_reason": "Second thoughts"},
            bsa_officer_headers,
        ),
        ApiErrorId.ERR_REFERRAL_INVALID_STATE.value,
    )

    rows, meta = validate_paginated(api.list_case_bsa_referrals(case["id"], analyst_headers))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ACCEPTED"
    assert rows[0]["adjudicated_by_user_id"] == "bsa-1"


def test_referral_aggregate_excludes_cleared_items_and_freezes_at_filing(api, analyst_headers):
    """PRD §3.7: "Filing freezes `aggregate_amount_cents` onto the referral: it is
    the sum of `amount_cents` over every deposited item whose account is the case's
    primary account or appears in the case's `cycle_account_ids` — the account set
    deduplicated — and whose `status` is `PENDING` or `RETURNED`. Cleared items are
    excluded, on the reasoning that money which actually collected is not
    suspicious volume."
    PRD §3.7: "The referral is created in `DRAFT` with `drafted_by_user_id` taken
    from `X-User-ID`, `aggregate_amount_cents` 0, `revision_count` 0, and
    `adjudicated_by_user_id`, `return_reason`, `submitted_at`, and `adjudicated_at`
    all null."
    PRD §3.3: "A **returned** item transitions `PENDING → RETURNED` and records its
    `return_reason`. Every hold on that item still in `ACTIVE` transitions
    `ACTIVE → CHARGED_BACK` with `released_at` stamped."

    Design: Corner/calculations/bsa_aggregate_amount_excludes_cleared_items_and_freezes_at_submit
    """
    scenario = create_active_account(legal_name="Aggregate Amount Depositor", tin_last4="0026")
    take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=50000)
    cleared_item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=60000)
    returned_item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=70000)
    settle_item(cleared_item["id"], "CLEARED")
    settle_item(returned_item["id"], "RETURNED", "NSF")

    case = open_case(scenario["account_id"], "MULE")
    advance_case(case["id"])
    dispose_case(case["id"], "SUBSTANTIATE", "Returned-item pattern")

    referral = draft_referral(
        case["id"],
        narrative="Deposits returned unpaid after immediate withdrawal attempts.",
        suspected_activity_code="KITING",
    )
    assert referral["aggregate_amount_cents"] == 0, "A draft carries a zero aggregate"

    filed = submit_referral(referral["id"])
    assert filed["aggregate_amount_cents"] == 120000, (
        f"50000 PENDING + 70000 RETURNED, with the 60000 cleared item excluded, "
        f"got {filed['aggregate_amount_cents']}"
    )
    assert filed["status"] == "SUBMITTED"

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["ledger_balance_cents"] == 110000
    assert account["available_balance_cents"] == 82500
    assert account["held_amount_cents"] == 27500
