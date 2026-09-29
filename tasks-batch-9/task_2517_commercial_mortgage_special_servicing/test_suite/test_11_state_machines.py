"""The declared status machines: valid moves, their preconditions, their side
effects, their initial states, their terminal lock-downs and the servicing cycle.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSET_MANAGER,
    ASSET_MANAGER_2,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    TRUSTEE,
    make_borrower_headers,
)


# ==========================================================================
# MASTER_SERVICING -> SPECIAL_SERVICING
# ==========================================================================
def test_a_receivership_event_carries_the_loan_into_special_servicing(api):
    """The declared move lands, and only the servicing dimension moves with it.

    The PRD: "The loan must currently be in `MASTER_SERVICING`, and at least one
    event on it must have `triggers_transfer` true and `consumed_by_transfer`
    false; without one, the transfer is refused with
    `ERR_NO_QUALIFYING_TRANSFER_EVENT`."

    Design: Corner/state_machines/loan_master_servicing_to_special_servicing_valid_transition
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V1")
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V01",
        maturity_date="2029-06-01T00:00:00Z",
    )
    a.assert_version_is(loan, 1, "loan")

    event = fx.record_transfer_event(
        api,
        loan["id"],
        event_code="RECEIVERSHIP",
        occurred_on="2026-07-10T00:00:00Z",
        evidence_note="receiver appointed over the property",
        days_delinquent_at_event=None,
    )
    assert event["triggers_transfer"] is True, "RECEIVERSHIP always qualifies"

    transferred = validate_success(
        api.set_loan_servicing_status(
            loan["id"],
            f.status_payload("SPECIAL_SERVICING", note="transferred on receivership"),
            MASTER_SERVICER,
        )
    )
    a.assert_status(transferred, "SPECIAL_SERVICING", "servicing_status")
    a.assert_version_is(transferred, 2, "loan")
    assert transferred["transfer_event_code"] == "RECEIVERSHIP"
    a.assert_status(transferred, "CURRENT", "payment_status")


def test_two_non_qualifying_events_leave_the_loan_master_serviced(api):
    """Having events is not the same as having a qualifying one.

    The PRD: "`BANKRUPTCY` and `RECEIVERSHIP` always qualify; and
    `OTHER_MATERIAL_DEFAULT` never qualifies."

    Design: Corner/state_machines/loan_transfer_without_qualifying_event_rejected
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V2")
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V02",
        maturity_date="2029-06-01T00:00:00Z",
    )
    other = fx.record_transfer_event(
        api,
        loan["id"],
        event_code="OTHER_MATERIAL_DEFAULT",
        occurred_on="2026-07-05T00:00:00Z",
        evidence_note="deferred maintenance covenant breach",
        days_delinquent_at_event=None,
    )
    imminent = fx.record_transfer_event(
        api,
        loan["id"],
        event_code="IMMINENT_DEFAULT",
        occurred_on="2026-07-06T00:00:00Z",
        evidence_note="borrower letter, not yet certified",
        days_delinquent_at_event=None,
        imminent_default_certified=False,
    )
    assert other["triggers_transfer"] is False
    assert imminent["triggers_transfer"] is False, (
        "an IMMINENT_DEFAULT event qualifies only on the servicer's certification"
    )

    response = api.set_loan_servicing_status(
        loan["id"], f.status_payload("SPECIAL_SERVICING"), MASTER_SERVICER
    )
    validate_error(response, e.ERR_NO_QUALIFYING_TRANSFER_EVENT, 422)

    unchanged = fx.read_loan(api, loan["id"], MASTER_SERVICER)
    a.assert_status(unchanged, "MASTER_SERVICING", "servicing_status")
    a.assert_fields_null(
        unchanged, "transferred_to_special_on", "asset_business_plan_due_date"
    )
    trust_after = fx.read_trust(api, trust["id"], TRUSTEE)
    assert trust_after["loans_in_special_servicing_count"] == 0


def test_the_transfer_consumes_the_earliest_event_and_writes_both_dates(api):
    """Two qualifying events, and the earlier occurred_on is the one spent.

    The PRD: "On success the service selects the **earliest** such event, ordering
    by `occurred_on` ascending and breaking ties by `created_at` ascending, and
    marks its `consumed_by_transfer` true — a consumed event can never justify a
    second transfer."

    Design: Corner/state_machines/loan_transfer_side_effects_write_dates_and_trust_counter
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V3")
    a.assert_version_is(trust, 1, "trust")
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V03",
        maturity_date="2029-06-01T00:00:00Z",
    )
    later = fx.record_transfer_event(
        api,
        loan["id"],
        event_code="RECEIVERSHIP",
        occurred_on="2026-07-20T00:00:00Z",
        evidence_note="receiver appointed",
        days_delinquent_at_event=None,
    )
    earlier = fx.record_transfer_event(
        api,
        loan["id"],
        event_code="BANKRUPTCY",
        occurred_on="2026-07-01T00:00:00Z",
        evidence_note="chapter 11 petition",
        days_delinquent_at_event=None,
    )

    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    assert transferred["transfer_event_code"] == "BANKRUPTCY", (
        "the earliest occurred_on wins, not the earliest created_at"
    )
    assert transferred["transferred_to_special_on"].startswith("2026-08-01")
    assert transferred["asset_business_plan_due_date"].startswith("2026-09-30")

    events, _ = validate_paginated(
        api.list_loan_transfer_events(loan["id"], MASTER_SERVICER)
    )
    assert a.find_by_id(events, earlier["id"])["consumed_by_transfer"] is True
    assert a.find_by_id(events, later["id"])["consumed_by_transfer"] is False

    trust_after = fx.read_trust(api, trust["id"], TRUSTEE)
    assert trust_after["loans_in_special_servicing_count"] == 1
    a.assert_version_is(trust_after, 2, "trust")


# ==========================================================================
# Invalid transitions and declared initial states
# ==========================================================================
def test_an_appraisal_cannot_be_accepted_straight_out_of_ordered(api):
    """ORDERED -> ACCEPTED is not a declared pair, so the state gate answers.

    The PRD: "An appraisal's lifecycle runs `ORDERED`, `RECEIVED`, `ACCEPTED`,
    with `REJECTED`, `SUPERSEDED` and `CANCELLED` as terminal outcomes"

    Design: Corner/state_machines/appraisal_accepted_directly_from_ordered_is_invalid_transition
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V4"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V04",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    appraisal = fx.order_appraisal(api, built["loan_id"])
    a.assert_status(appraisal, "ORDERED")
    assert appraisal["valuation_valid_months"] == 12

    response = api.set_appraisal_status(
        appraisal["id"], f.status_payload("ACCEPTED"), ASSET_MANAGER_2
    )
    validate_error(response, e.ERR_INVALID_STATE_TRANSITION, 409)

    untouched = validate_success(api.get_appraisal(appraisal["id"], ASSET_MANAGER))
    a.assert_status(untouched, "ORDERED")
    a.assert_fields_null(
        untouched,
        "value_usd",
        "as_of_date",
        "coverage_start_date",
        "coverage_end_date",
        "accepted_by_user_id",
    )
    assert fx.reductions_for_loan(api, built["loan_id"]) == [], (
        "a refused acceptance creates no appraisal reduction"
    )
    loan = fx.read_loan(api, built["loan_id"])
    a.assert_fields_null(loan, "last_appraised_value_usd")


def test_three_aggregates_each_land_on_their_own_declared_initial_state(api):
    """A request, an appraisal and an advance created back to back.

    The PRD: "A new request starts in status `SUBMITTED` with `info_request_count`
    at zero." / "A new appraisal starts in status `ORDERED`, has its `due_date`
    stamped at sixty calendar days after `ordered_on` — the turnaround the pooling
    and servicing agreement allows — and records the ordering `X-User-ID` in
    `ordered_by_user_id`." / "A new advance starts in status `OUTSTANDING` with
    `reimbursed_principal_usd`, `reimbursed_interest_usd` and
    `accrued_interest_usd` all zero."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V5"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V05",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id = built["loan_id"]

    request = validate_success(
        api.create_borrower_request(
            f.modification_request_payload(
                loan_id,
                processing_fee_deposit_usd=25000,
                requested_terms_note="rate relief for eighteen months",
                proposed_maturity_date="2031-06-01T00:00:00Z",
            ),
            make_borrower_headers(loan_id),
        ),
        201,
    )
    a.assert_status(request, "SUBMITTED")
    assert request["info_request_count"] == 0
    a.assert_fields_null(
        request,
        "servicing_standard_margin_usd",
        "servicing_standard_conclusion",
        "decided_on",
    )
    a.assert_version_is(request, 1, "borrower request")

    appraisal = validate_success(
        api.create_appraisal(
            f.appraisal_payload(loan_id, valuation_valid_months=None), ASSET_MANAGER
        ),
        201,
    )
    a.assert_status(appraisal, "ORDERED")
    assert appraisal["valuation_valid_months"] == 12, "the declared default"
    assert appraisal["due_date"].startswith("2026-09-30")
    assert appraisal["ordered_by_user_id"] == "amgr-001"
    a.assert_fields_null(appraisal, "received_on")
    a.assert_version_is(appraisal, 1, "appraisal")

    advance = validate_success(
        api.create_advance(
            f.advance_payload(
                loan_id,
                advance_type="TAX_INSURANCE_ADVANCE",
                amount_usd=50000,
                advanced_on="2026-08-01T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    a.assert_status(advance, "OUTSTANDING")
    a.assert_money(advance["reimbursed_principal_usd"], 0.00, "reimbursed_principal_usd")
    a.assert_money(advance["reimbursed_interest_usd"], 0.00, "reimbursed_interest_usd")
    a.assert_money(advance["accrued_interest_usd"], 0.00, "accrued_interest_usd")
    a.assert_version_is(advance, 1, "advance")


def test_a_withdrawn_request_admits_no_further_status_move(api):
    """WITHDRAWN is terminal, and the deposit stays where it is.

    The PRD: "Withdrawal belongs to the borrower and is legal from `SUBMITTED`,
    `UNDER_ANALYSIS` or `INFO_REQUESTED`; the withdrawing caller's `X-User-ID`
    must equal the request's `loan_id`, and the `processing_fee_deposit_usd` is
    untouched — the borrower does not get its money back."

    Design: Corner/state_machines/withdrawn_borrower_request_is_terminal_and_locked_down
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V6"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V06",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id = built["loan_id"]
    borrower = make_borrower_headers(loan_id)
    request = fx.submit_modification_request(api, loan_id)

    withdrawn = validate_success(
        api.set_borrower_request_status(
            request["id"], f.status_payload("WITHDRAWN"), borrower
        )
    )
    a.assert_status(withdrawn, "WITHDRAWN")
    a.assert_money(
        withdrawn["processing_fee_deposit_usd"], 25000.00, "processing_fee_deposit_usd"
    )

    validate_error(
        api.set_borrower_request_status(
            request["id"], f.status_payload("UNDER_ANALYSIS"), ASSET_MANAGER
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.set_borrower_request_status(
            request["id"], f.status_payload("WITHDRAWN"), borrower
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    still_withdrawn = validate_success(
        api.get_borrower_request(request["id"], ASSET_MANAGER)
    )
    a.assert_status(still_withdrawn, "WITHDRAWN")
    a.assert_version_is(still_withdrawn, withdrawn["version"], "borrower request")
    a.assert_fields_null(
        still_withdrawn,
        "servicing_standard_margin_usd",
        "servicing_standard_conclusion",
    )


def test_replaying_the_transfer_is_refused_by_the_state_gate(api):
    """The second call is not a no-op, and the state gate answers before the
    business gate.

    The PRD: "The requested transition from the row's current state to the
    requested target is a declared transition, or `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/repeated_transfer_to_special_servicing_rejected
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V7"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V07",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    first = built["loan"]

    response = api.set_loan_servicing_status(
        built["loan_id"], f.status_payload("SPECIAL_SERVICING"), MASTER_SERVICER
    )
    validate_error(response, e.ERR_INVALID_STATE_TRANSITION, 409)

    after = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_status(after, "SPECIAL_SERVICING", "servicing_status")
    a.assert_version_is(after, first["version"], "loan")
    assert after["transferred_to_special_on"] == first["transferred_to_special_on"]
    assert after["asset_business_plan_due_date"] == first["asset_business_plan_due_date"]

    trust_after = fx.read_trust(api, built["trust_id"], TRUSTEE)
    assert trust_after["loans_in_special_servicing_count"] == 1


# ==========================================================================
# The cyclic servicing dimension, and the cross-entity acceptance cascade
# ==========================================================================
def test_the_loan_walks_the_whole_cycle_and_is_transferred_a_second_time(api):
    """MASTER_SERVICING to SPECIAL_SERVICING to IN_WORKOUT to CORRECTED to
    MASTER_SERVICING, then round again on a fresh event.

    The PRD: "It also closes the cycle: `MASTER_SERVICING → SPECIAL_SERVICING →
    IN_WORKOUT → CORRECTED → MASTER_SERVICING`, after which a fresh qualifying
    event can start the whole sequence again."

    Design: Corner/state_machines/loan_completes_the_workout_correction_cycle_and_re_enters_special_servicing
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V8"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V08",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id, trust_id = built["loan_id"], built["trust_id"]
    fx.accepted_appraisal(api, loan_id, value_usd=9000000)
    plan = fx.executed_plan(
        api, trust_id, loan_id, alternative_builders=[fx.add_modification_alternative]
    )
    plan_id = plan["plan_id"]

    in_workout = fx.read_loan(api, loan_id)
    a.assert_status(in_workout, "IN_WORKOUT", "servicing_status")
    assert in_workout["active_workout_plan_id"] == plan_id
    assert in_workout["is_modified"] is True

    for as_of in ("2026-08-01", "2026-08-02", "2026-08-03"):
        paid = validate_success(
            api.set_loan_payment_status(
                loan_id,
                {
                    "to_status": "CURRENT",
                    "as_of_date": f"{as_of}T00:00:00Z",
                    "timely_payment_recorded": True,
                },
                MASTER_SERVICER,
            )
        )
    assert paid["consecutive_timely_payments"] == 3
    a.assert_status(paid, "CURRENT", "payment_status")

    corrected = validate_success(
        api.set_loan_servicing_status(
            loan_id, f.status_payload("CORRECTED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(corrected, "CORRECTED", "servicing_status")
    assert corrected["correction_source_plan_id"] == plan_id
    a.assert_fields_null(corrected, "active_workout_plan_id")
    assert fx.read_trust(api, trust_id, TRUSTEE)["loans_in_special_servicing_count"] == 0

    handed_back = validate_success(
        api.set_loan_servicing_status(
            loan_id, f.status_payload("MASTER_SERVICING"), ASSET_MANAGER
        )
    )
    a.assert_status(handed_back, "MASTER_SERVICING", "servicing_status")
    assert handed_back["correction_source_plan_id"] == plan_id, (
        "the cycle does not erase its own history"
    )
    assert handed_back["is_modified"] is True

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.record_transfer_event(
        api,
        loan_id,
        event_code="RECEIVERSHIP",
        occurred_on="2026-08-25T00:00:00Z",
        evidence_note="receiver appointed after the modification failed",
        days_delinquent_at_event=None,
    )
    second = fx.transfer_to_special_servicing(api, loan_id)
    a.assert_status(second, "SPECIAL_SERVICING", "servicing_status")
    assert second["transfer_event_code"] == "RECEIVERSHIP"
    assert second["transferred_to_special_on"].startswith("2026-09-01")
    assert second["asset_business_plan_due_date"].startswith("2026-10-31")
    assert fx.read_trust(api, trust_id, TRUSTEE)["loans_in_special_servicing_count"] == 1

    closed_plan = validate_success(api.get_workout_plan(plan_id, ASSET_MANAGER))
    a.assert_status(closed_plan, "EXECUTED")


def test_accepting_an_appraisal_writes_the_loan_and_mints_the_reduction(api):
    """One appraisal write reaches into the loan and creates a third row.

    The PRD: "Fourth, the loan's `last_appraised_value_usd` is set to the
    appraisal's `value_usd` and its `appraisal_required` flag is cleared. The
    appraisal's `version` and the loan's `version` each advance by one. Because the
    new reduction is only `PROVISIONAL`, the trust's `total_ara_usd` is **not** yet
    affected by it; that happens only when the committee makes it effective."

    Design: Corner/state_machines/appraisal_acceptance_writes_loan_valuation_fields_cross_entity
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V9")
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V09",
        maturity_date="2029-06-01T00:00:00Z",
    )
    for to_status, as_of in (
        ("DELINQUENT_30", "2026-06-15"),
        ("DELINQUENT_60", "2026-07-15"),
        ("DELINQUENT_90_PLUS", "2026-07-31"),
    ):
        delinquent = validate_success(
            api.set_loan_payment_status(
                loan["id"],
                {"to_status": to_status, "as_of_date": f"{as_of}T00:00:00Z"},
                MASTER_SERVICER,
            )
        )
    assert delinquent["appraisal_required"] is True

    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    assert transferred["transfer_event_code"] == "MONETARY_DEFAULT_60D"

    appraisal = fx.order_appraisal(api, loan["id"])
    fx.receive_appraisal(api, appraisal["id"], 9000000, "2026-08-01T00:00:00Z")
    before = fx.read_loan(api, loan["id"])
    a.assert_fields_null(before, "last_appraised_value_usd")

    accepted = validate_success(
        api.set_appraisal_status(
            appraisal["id"], f.status_payload("ACCEPTED"), ASSET_MANAGER_2
        )
    )
    a.assert_status(accepted, "ACCEPTED")
    assert accepted["accepted_by_user_id"] == "amgr-002"
    assert accepted["ordered_by_user_id"] == "amgr-001"

    after = fx.read_loan(api, loan["id"])
    assert after["appraisal_required"] is False
    a.assert_money(
        after["last_appraised_value_usd"], 9000000.00, "last_appraised_value_usd"
    )
    a.assert_version_advanced_by(before, after, 1, "loan")

    reductions = fx.reductions_for_loan(api, loan["id"])
    assert len(reductions) == 1, "acceptance mints exactly one reduction"
    reduction = reductions[0]
    a.assert_status(reduction, "PROVISIONAL")
    assert reduction["appraisal_id"] == appraisal["id"]
    a.assert_status(reduction, "GROSS_APPRAISED_BASIS", "calculation_basis")
    a.assert_money(reduction["deficiency_base_usd"], 10000000.00, "deficiency_base_usd")
    a.assert_money(reduction["appraisal_credit_usd"], 8100000.00, "appraisal_credit_usd")
    a.assert_money(reduction["ara_amount_usd"], 1900000.00, "ara_amount_usd")
    a.assert_ara_percentage(reduction["ara_percentage"], 19.0000)

    trust_after = fx.read_trust(api, trust["id"], TRUSTEE)
    a.assert_money(trust_after["total_ara_usd"], 0.00, "total_ara_usd")


# ==========================================================================
# Ledger side effects, conditional fan-out and the write-off cascade
# ==========================================================================
def test_each_advance_lands_in_the_loan_ledger_and_the_trust_roll_up(api):
    """Two ledgers at two levels, both carrying principal only.

    The PRD: "Creating an advance recomputes the loan's `advances_outstanding_usd`
    and the trust's `total_advances_outstanding_usd`."

    Design: Corner/state_machines/advance_creation_syncs_loan_and_trust_advance_ledgers
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V10")
    a.assert_money(
        trust["total_advances_outstanding_usd"], 0.00, "total_advances_outstanding_usd"
    )
    loan_a = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V10-A",
        maturity_date="2029-06-01T00:00:00Z",
    )
    a.assert_money(loan_a["advances_outstanding_usd"], 0.00, "advances_outstanding_usd")
    loan_b = fx.create_loan(
        api,
        trust["id"],
        loan_number="L-V10-B",
        original_balance_usd=6000000,
        current_principal_balance_usd=5000000,
        note_rate_pct=5.5,
        monthly_debt_service_usd=31000,
        maturity_date="2030-01-01T00:00:00Z",
        securitization_value_usd=7000000,
    )

    advance_a = fx.record_advance(
        api,
        loan_a["id"],
        advance_type="PI_ADVANCE",
        amount_usd=60000,
        advanced_on="2026-02-01T00:00:00Z",
    )
    a.assert_status(advance_a, "OUTSTANDING")
    a.assert_money(
        fx.read_loan(api, loan_a["id"])["advances_outstanding_usd"],
        60000.00,
        "loan advances_outstanding_usd",
    )
    a.assert_money(
        fx.read_trust(api, trust["id"], TRUSTEE)["total_advances_outstanding_usd"],
        60000.00,
        "trust total_advances_outstanding_usd",
    )

    advance_b = fx.record_advance(
        api,
        loan_a["id"],
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=150000,
        advanced_on="2026-04-01T00:00:00Z",
    )
    a.assert_money(
        fx.read_loan(api, loan_a["id"])["advances_outstanding_usd"],
        210000.00,
        "loan advances_outstanding_usd",
    )

    advance_c = fx.record_advance(
        api,
        loan_b["id"],
        advance_type="TAX_INSURANCE_ADVANCE",
        amount_usd=90000,
        advanced_on="2026-06-01T00:00:00Z",
    )
    a.assert_money(
        fx.read_trust(api, trust["id"], TRUSTEE)["total_advances_outstanding_usd"],
        300000.00,
        "trust total_advances_outstanding_usd",
    )
    a.assert_money(
        fx.read_loan(api, loan_a["id"])["advances_outstanding_usd"],
        210000.00,
        "the loan field does not span loans",
    )
    a.assert_money(
        fx.read_loan(api, loan_b["id"])["advances_outstanding_usd"],
        90000.00,
        "a master-serviced loan still carries its advances",
    )

    rows, _ = validate_paginated(api.list_advances(MASTER_SERVICER))
    a.assert_money(
        a.find_by_id(rows, advance_a["id"])["accrued_interest_usd"], 1500.00, "interest A"
    )
    a.assert_money(
        a.find_by_id(rows, advance_b["id"])["accrued_interest_usd"], 2500.00, "interest B"
    )
    a.assert_money(
        a.find_by_id(rows, advance_c["id"])["accrued_interest_usd"], 750.00, "interest C"
    )


def test_abandonment_waives_the_pending_consultation_and_spares_the_answered_one(api):
    """The fan-out is conditional on the consultation still being PENDING.

    The PRD: "It clears the loan's `active_workout_plan_id` to null while leaving
    the loan in `IN_WORKOUT`, and it moves every still-`PENDING` consultation on
    that plan to `WAIVED`."

    Design: Corner/state_machines/plan_abandonment_waives_only_the_still_pending_consultation
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V11"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V11",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id, trust_id = built["loan_id"], built["trust_id"]
    plan = fx.scored_plan(
        api, loan_id, alternative_builders=[fx.add_modification_alternative]
    )
    plan_id = plan["plan_id"]
    alternative_id = plan["alternative_ids"][0]

    fx.recommend_plan(api, plan_id, alternative_id)
    first = fx.issue_plan_consultation(api, trust_id, plan_id)
    answered = fx.respond_to_consultation(api, first["id"], trust_id, "OBJECTED")
    a.assert_status(answered, "OBJECTED")
    a.assert_status(answered, "CONSENT_RIGHT", "rights_type")
    assert answered["responded_at"] is not None

    revised = validate_success(
        api.set_workout_plan_status(plan_id, f.status_payload("DRAFT"), ASSET_MANAGER)
    )
    assert revised["revision_round"] == 1
    fx.score_plan(api, plan_id)
    fx.recommend_plan(api, plan_id, alternative_id)
    second = fx.issue_plan_consultation(api, trust_id, plan_id)
    a.assert_status(second, "PENDING")

    abandoned = validate_success(
        api.set_workout_plan_status(
            plan_id,
            f.status_payload("ABANDONED", note="borrower filed a competing plan"),
            ASSET_MANAGER,
        )
    )
    a.assert_status(abandoned, "ABANDONED")

    untouched = validate_success(api.get_consultation(first["id"], ASSET_MANAGER))
    a.assert_status(untouched, "OBJECTED")
    a.assert_status(untouched, "CONSENT_RIGHT", "rights_type")
    assert untouched["responded_at"] == answered["responded_at"]
    a.assert_version_is(untouched, answered["version"], "consultation")

    waived = validate_success(api.get_consultation(second["id"], ASSET_MANAGER))
    a.assert_status(waived, "WAIVED")
    a.assert_fields_null(waived, "responded_at")
    a.assert_status(waived, "CONSENT_RIGHT", "rights_type")

    loan = fx.read_loan(api, loan_id)
    a.assert_fields_null(loan, "active_workout_plan_id")
    a.assert_status(loan, "IN_WORKOUT", "servicing_status")

    validate_error(
        api.set_workout_plan_status(plan_id, f.status_payload("SCORED"), ASSET_MANAGER),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )


def test_writing_the_property_off_takes_the_loan_down_with_it(api):
    """The write-off cascade is not the waterfall's: no fee, no reimbursement.

    The PRD: "It has its own cascade rather than the waterfall's: the loan's
    `realized_loss_usd` becomes its `current_principal_balance_usd` plus its
    `advances_outstanding_usd`, rounded half up to two decimal places; its
    `current_principal_balance_usd` is set to zero; the trust's `realized_loss_usd`
    is recomputed and the control test re-runs; every advance on the loan whose
    status is `OUTSTANDING` or `PARTIALLY_REIMBURSED` moves to
    `DEEMED_NONRECOVERABLE`; and the loan's `servicing_status` becomes
    `WRITTEN_OFF`."

    Design: Corner/state_machines/reo_write_off_cascades_down_to_the_loan_without_touching_the_advance_ledger
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V12")
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V12",
        maturity_date="2029-06-01T00:00:00Z",
    )
    loan_id = loan["id"]
    advance_a = fx.record_advance(
        api,
        loan_id,
        advance_type="PI_ADVANCE",
        amount_usd=60000,
        advanced_on="2026-02-01T00:00:00Z",
    )
    advance_b = fx.record_advance(
        api,
        loan_id,
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=290000,
        advanced_on="2026-04-01T00:00:00Z",
    )
    fx.record_bankruptcy_event(api, loan_id)
    fx.transfer_to_special_servicing(api, loan_id)
    fx.accepted_appraisal(api, loan_id, value_usd=6000000)
    plan = fx.executed_plan(
        api,
        trust["id"],
        loan_id,
        alternative_builders=[fx.add_foreclosure_alternative],
    )
    reo = fx.acquire_reo(api, loan_id, plan["plan_id"], initial_noi_annual_usd=240000)
    assert reo["remic_disposition_deadline"].startswith("2029-08-01")
    fx.set_reo_status(api, reo["id"], "MARKETED", list_price_usd=6200000)

    written_off = validate_success(
        api.set_reo_asset_status(
            reo["id"], f.status_payload("WRITTEN_OFF"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(written_off, "WRITTEN_OFF")

    after = fx.read_loan(api, loan_id)
    a.assert_status(after, "WRITTEN_OFF", "servicing_status")
    a.assert_money(
        after["current_principal_balance_usd"], 0.00, "current_principal_balance_usd"
    )
    a.assert_money(after["realized_loss_usd"], 10350000.00, "realized_loss_usd")

    advances, _ = validate_paginated(
        api.list_advances(MASTER_SERVICER, {"loan_id": loan_id})
    )
    for advance in (advance_a, advance_b):
        row = a.find_by_id(advances, advance["id"])
        a.assert_status(row, "DEEMED_NONRECOVERABLE")
        a.assert_money(row["reimbursed_principal_usd"], 0.00, "reimbursed_principal_usd")

    assert fx.fees_for_loan(api, loan_id, "LIQUIDATION_FEE") == [], (
        "the liquidation fee belongs to the waterfall, not to a write-off"
    )

    trust_after = fx.read_trust(api, trust["id"], TRUSTEE)
    a.assert_money(trust_after["realized_loss_usd"], 10350000.00, "realized_loss_usd")
    a.assert_money(
        trust_after["controlling_class_notional_usd"],
        29650000.00,
        "controlling_class_notional_usd",
    )
    a.assert_status(trust_after, "CONTROLLING", "control_status")
    assert trust_after["loans_in_special_servicing_count"] == 0

    validate_error(
        api.set_reo_asset_status(
            reo["id"],
            f.status_payload("MARKETED", list_price_usd=6200000),
            COMMITTEE_OFFICER,
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )
