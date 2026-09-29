"""Validation precedence: pairs of rules that a single request violates at once,
where the answer must be the higher-ranked one and the lower-ranked one is shown
to be implemented by a control call that violates it alone.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CONSULTATION_DEADLINE_SEP,
    NPV_MOD_NPV_CONTRACTUAL,
    NPV_NOTE_NPV_CONTRACTUAL,
)
from test_helpers.test_users import (
    ASSET_MANAGER,
    MASTER_SERVICER,
    make_controlling_class_representative_headers,
)


# ==========================================================================
# The loan state gate outranks the deposit floor
# ==========================================================================
def _master_serviced_and_special_serviced_loans(api):
    trust = fx.create_trust(api, deal_name="CMBS 2026-Q1")
    master_serviced = fx.create_loan(api, trust["id"], loan_number="L-Q0M")
    special_serviced = fx.create_loan(api, trust["id"], loan_number="L-Q0S")
    fx.record_bankruptcy_event(api, special_serviced["id"])
    fx.transfer_to_special_servicing(api, special_serviced["id"])
    return trust["id"], master_serviced["id"], special_serviced["id"]


def test_a_master_serviced_loan_with_a_short_deposit_reports_the_loan_state(api):
    """Both rules are broken at once and the state gate answers.

    The PRD: "Because this ranks below rule 12, a request against a
    master-serviced loan with a sub-floor deposit is answered with
    `ERR_LOAN_NOT_IN_SPECIAL_SERVICING`."

    Design: Difficulty/priority_pair_validation_conflict/loan_state_gate_outranks_deposit_floor_on_request_intake
    """
    _, master_serviced_id, _ = _master_serviced_and_special_serviced_loans(api)

    response = api.create_borrower_request(
        f.modification_request_payload(
            master_serviced_id,
            processing_fee_deposit_usd=1000,
            requested_terms_note="both rules violated at once",
        ),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_LOAN_NOT_IN_SPECIAL_SERVICING, 409)


def test_the_loan_state_gate_bites_on_its_own_with_a_compliant_deposit(api):
    """The higher-ranked rule is not merely a side effect of the short deposit.

    The PRD: "Intake is only open on a loan the special servicer actually
    controls: the loan's `servicing_status` must be `SPECIAL_SERVICING` or
    `IN_WORKOUT`, and a request against a master-serviced loan is refused with
    `ERR_LOAN_NOT_IN_SPECIAL_SERVICING`, because such a borrower's requests are
    the master servicer's business."

    Design: Difficulty/priority_pair_validation_conflict/loan_state_gate_outranks_deposit_floor_on_request_intake
    """
    _, master_serviced_id, _ = _master_serviced_and_special_serviced_loans(api)

    response = api.create_borrower_request(
        f.modification_request_payload(
            master_serviced_id, requested_terms_note="only the loan state is wrong"
        ),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_LOAN_NOT_IN_SPECIAL_SERVICING, 409)


def test_the_deposit_floor_bites_on_its_own_once_the_loan_qualifies(api):
    """The outranked rule is implemented, and answers with its own 402.

    The PRD: "A deposit strictly below its floor is refused with
    `ERR_DEPOSIT_BELOW_MINIMUM`; a deposit exactly equal to the floor is
    accepted."

    Design: Difficulty/priority_pair_validation_conflict/loan_state_gate_outranks_deposit_floor_on_request_intake
    """
    _, master_serviced_id, special_serviced_id = (
        _master_serviced_and_special_serviced_loans(api)
    )

    response = api.create_borrower_request(
        f.modification_request_payload(
            special_serviced_id,
            processing_fee_deposit_usd=1000,
            requested_terms_note="only the deposit is short",
        ),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_DEPOSIT_BELOW_MINIMUM, 402)

    for loan_id in (master_serviced_id, special_serviced_id):
        rows, _ = validate_paginated(
            api.list_borrower_requests(ASSET_MANAGER, {"loan_id": loan_id})
        )
        assert rows == [], "a refused intake must leave no borrower request behind"


# ==========================================================================
# The cross-reference check outranks the servicing standard
# ==========================================================================
def _two_scored_plans_in_one_trust(api):
    trust = fx.create_trust(api, deal_name="CMBS 2026-X1")
    plans = {}
    for label, loan_number, builders in (
        ("a", "L-X0A", [fx.add_modification_alternative]),
        ("b", "L-X0B", [fx.add_modification_alternative, fx.add_note_sale_alternative]),
    ):
        loan = fx.create_mid_size_loan(api, trust["id"], loan_number=loan_number)
        fx.record_transfer_event(
            api,
            loan["id"],
            event_code="RECEIVERSHIP",
            occurred_on="2026-07-10T00:00:00Z",
            evidence_note="receiver appointed",
            days_delinquent_at_event=None,
        )
        fx.transfer_to_special_servicing(api, loan["id"])
        plans[label] = fx.scored_plan(api, loan["id"], alternative_builders=builders)
    return trust["id"], plans


def test_selecting_another_plans_alternative_reports_the_reference_mismatch(api):
    """Both rules are broken at once and the cross-reference check answers.

    The PRD: "the alternative must belong to the plan being recommended, or the
    request is `ERR_SUBJECT_REFERENCE_MISMATCH`; and it must equal the plan's
    `recommended_alternative_id`, or the request is
    `ERR_SERVICING_STANDARD_VIOLATION` — putting forward anything other than the
    highest-ranked alternative is a breach of the servicing standard, not a
    matter of taste."

    Design: Difficulty/priority_pair_validation_conflict/alternative_reference_mismatch_outranks_servicing_standard_on_recommendation
    """
    _, plans = _two_scored_plans_in_one_trust(api)
    foreign_note_sale_id = plans["b"]["alternative_ids"][1]

    response = api.set_workout_plan_status(
        plans["a"]["plan_id"],
        f.status_payload("RECOMMENDED", selected_alternative_id=foreign_note_sale_id),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_SUBJECT_REFERENCE_MISMATCH, 422)

    unchanged = validate_success(
        api.get_workout_plan(plans["a"]["plan_id"], ASSET_MANAGER)
    )
    a.assert_status(unchanged, "SCORED")
    a.assert_fields_null(unchanged, "selected_alternative_id")


def test_selecting_the_plans_own_rank_two_alternative_breaches_the_standard(api):
    """The outranked rule is implemented, and answers with its own 422.

    The PRD: "Only a `SERVICING_STANDARD_MET` conclusion opens the door to
    `UNDER_ANALYSIS → RECOMMENDED`; attempting that move on a
    `SERVICING_STANDARD_NOT_MET` conclusion, or before any analysis has been
    recorded at all, is refused with `ERR_SERVICING_STANDARD_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/alternative_reference_mismatch_outranks_servicing_standard_on_recommendation
    """
    _, plans = _two_scored_plans_in_one_trust(api)
    modification_id, note_sale_id = plans["b"]["alternative_ids"]

    modification = validate_success(
        api.get_workout_alternative(modification_id, ASSET_MANAGER)
    )
    note_sale = validate_success(api.get_workout_alternative(note_sale_id, ASSET_MANAGER))
    a.assert_money(modification["npv_usd"], NPV_MOD_NPV_CONTRACTUAL, "modification npv_usd")
    assert modification["rank"] == 1
    a.assert_money(note_sale["npv_usd"], NPV_NOTE_NPV_CONTRACTUAL, "note sale npv_usd")
    assert note_sale["rank"] == 2
    assert plans["b"]["plan"]["recommended_alternative_id"] == modification_id

    response = api.set_workout_plan_status(
        plans["b"]["plan_id"],
        f.status_payload("RECOMMENDED", selected_alternative_id=note_sale_id),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_SERVICING_STANDARD_VIOLATION, 422)

    unchanged = validate_success(
        api.get_workout_plan(plans["b"]["plan_id"], ASSET_MANAGER)
    )
    a.assert_status(unchanged, "SCORED")
    a.assert_fields_null(unchanged, "selected_alternative_id")


# ==========================================================================
# The ownership check outranks the closed response window
# ==========================================================================
def _consultation_past_its_deadline(api):
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    trust_a = fx.create_trust(api, deal_name="CMBS 2026-Y1")
    trust_b = fx.create_trust(api, deal_name="CMBS 2026-Y2")

    loan = fx.create_mid_size_loan(api, trust_a["id"], loan_number="L-Y0A")
    fx.record_bankruptcy_event(api, loan["id"], occurred_on="2026-08-20T00:00:00Z")
    fx.transfer_to_special_servicing(api, loan["id"])

    built = fx.scored_plan(api, loan["id"])
    fx.recommend_plan(
        api, built["plan_id"], built["plan"]["recommended_alternative_id"]
    )
    consultation = fx.issue_plan_consultation(api, trust_a["id"], built["plan_id"])

    fx.set_clock(api, "2026-09-20T00:00:00Z")
    return {
        "trust_a_id": trust_a["id"],
        "trust_b_id": trust_b["id"],
        "plan_id": built["plan_id"],
        "consultation_id": consultation["id"],
        "consultation": consultation,
    }


def test_the_wrong_trusts_representative_is_told_only_that_it_is_not_the_owner(api):
    """Both rules are broken at once and identity is checked first.

    The PRD: "Because this ranks below ownership, a representative of the wrong
    trust responding after the deadline is told `ERR_NOT_RESOURCE_OWNER`."

    Design: Difficulty/priority_pair_validation_conflict/consultation_owner_check_outranks_closed_response_window
    """
    scenario = _consultation_past_its_deadline(api)
    assert scenario["consultation"]["deadline_at"] == CONSULTATION_DEADLINE_SEP
    a.assert_status(scenario["consultation"], "CONSENT_RIGHT", "rights_type")

    response = api.respond_to_consultation(
        scenario["consultation_id"],
        f.consultation_response_payload("CONSENTED", response_note="wrong trust, and too late"),
        make_controlling_class_representative_headers(scenario["trust_b_id"]),
    )
    validate_error(response, e.ERR_NOT_RESOURCE_OWNER, 403)


def test_the_right_trusts_representative_is_told_the_window_has_closed(api):
    """The outranked rule is implemented, and answers with its own 409.

    The PRD: "the current logical clock must be at or before `deadline_at` — a
    response arriving strictly after the deadline is refused with
    `ERR_CONSULTATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/consultation_owner_check_outranks_closed_response_window
    """
    scenario = _consultation_past_its_deadline(api)

    response = api.respond_to_consultation(
        scenario["consultation_id"],
        f.consultation_response_payload(
            "CONSENTED", response_note="right trust, still too late"
        ),
        make_controlling_class_representative_headers(scenario["trust_a_id"]),
    )
    validate_error(response, e.ERR_CONSULTATION_WINDOW_CLOSED, 409)


def test_neither_refusal_disturbs_the_consultation_or_its_subject_plan(api):
    """Both refusals leave the pending consultation exactly as it was.

    The PRD: "the consultation starts in status `PENDING` with `responded_at`,
    `response_note` and `responded_by_user_id` null."

    Design: Difficulty/priority_pair_validation_conflict/consultation_owner_check_outranks_closed_response_window
    """
    scenario = _consultation_past_its_deadline(api)

    for trust_key, expected_error in (
        ("trust_b_id", e.ERR_NOT_RESOURCE_OWNER),
        ("trust_a_id", e.ERR_CONSULTATION_WINDOW_CLOSED),
    ):
        validate_error(
            api.respond_to_consultation(
                scenario["consultation_id"],
                f.consultation_response_payload("CONSENTED"),
                make_controlling_class_representative_headers(scenario[trust_key]),
            ),
            expected_error,
        )

    consultation = validate_success(
        api.get_consultation(scenario["consultation_id"], MASTER_SERVICER)
    )
    a.assert_status(consultation, "PENDING")
    a.assert_fields_null(consultation, "responded_at", "responded_by_user_id")

    plan = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    a.assert_status(plan, "CONSULTATION")
