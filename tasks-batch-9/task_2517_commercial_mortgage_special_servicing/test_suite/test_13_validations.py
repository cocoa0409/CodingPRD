"""Field-level and cross-field validations: the scope of a uniqueness rule, an
inclusive money floor, conditionally required and conditionally forbidden
fields, an inclusive calendar deadline, an aggregate counter gate, and the fixed
precedence between an existence check and a version check.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    TRUSTEE,
    make_borrower_headers,
)


# ==========================================================================
# A loan number is unique inside its trust and free outside it
# ==========================================================================
def _two_trusts_and_one_boarded_loan(api):
    """Two trusts; the number L-SHARED-01 is taken in the first one only."""
    trust_a = fx.create_trust(api, deal_name="CMBS 2026-V21")
    trust_b = fx.create_trust(
        api,
        deal_name="CMBS 2026-V22",
        closing_date="2026-02-15T00:00:00Z",
        original_controlling_class_balance_usd=25000000,
    )
    incumbent = fx.create_mid_size_loan(
        api, trust_a["id"], loan_number="L-SHARED-01"
    )
    return trust_a, trust_b, incumbent


def _contender_payload(trust_id):
    """A materially different loan that reuses the same loan number."""
    return f.loan_payload(
        trust_id,
        loan_number="L-SHARED-01",
        original_balance_usd=8000000,
        current_principal_balance_usd=7500000,
        note_rate_pct=5.75,
        monthly_debt_service_usd=48000,
        maturity_date="2030-03-01T00:00:00Z",
        securitization_value_usd=9000000,
    )


def test_the_second_loan_bearing_an_existing_number_in_the_trust_is_refused(api):
    """Uniqueness bites on the pair, and the refusal boards nothing.

    The PRD: "The `loan_number` must be unique within the trust; a second loan in
    the same trust bearing an existing number is refused with
    `ERR_DUPLICATE_LOAN_NUMBER`, while the same number in a different trust is
    perfectly acceptable."

    Design: Corner/validations/duplicate_loan_number_rejected_within_a_trust_but_free_across_trusts
    """
    trust_a, _, incumbent = _two_trusts_and_one_boarded_loan(api)
    version_before = fx.trust_version(api, trust_a["id"])

    response = api.create_loan(_contender_payload(trust_a["id"]), MASTER_SERVICER)
    validate_error(response, e.ERR_DUPLICATE_LOAN_NUMBER, 409)

    rows, meta = validate_paginated(
        api.list_loans(TRUSTEE, {"trust_id": trust_a["id"]})
    )
    assert len(rows) == 1, "the refused body boards no loan"
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incumbent["id"]
    a.assert_money(
        rows[0]["current_principal_balance_usd"], 10000000.00, "current_principal_balance_usd"
    )
    assert fx.trust_version(api, trust_a["id"]) == version_before, (
        "a refused loan creation leaves the parent trust untouched"
    )


def test_the_same_number_in_a_different_trust_is_perfectly_acceptable(api):
    """The identical body that was refused succeeds under the other trust.

    The PRD: "A loan number is unique within its trust, or
    `ERR_DUPLICATE_LOAN_NUMBER`."

    Design: Corner/validations/duplicate_loan_number_rejected_within_a_trust_but_free_across_trusts
    """
    trust_a, trust_b, incumbent = _two_trusts_and_one_boarded_loan(api)
    validate_error(
        api.create_loan(_contender_payload(trust_a["id"]), MASTER_SERVICER),
        e.ERR_DUPLICATE_LOAN_NUMBER,
    )

    namesake = validate_success(
        api.create_loan(_contender_payload(trust_b["id"]), MASTER_SERVICER), 201
    )
    assert namesake["loan_number"] == "L-SHARED-01"
    assert namesake["trust_id"] == trust_b["id"]
    assert namesake["id"] != incumbent["id"]
    a.assert_status(namesake, "MASTER_SERVICING", "servicing_status")

    for trust_id in (trust_a["id"], trust_b["id"]):
        rows, meta = validate_paginated(
            api.list_loans(TRUSTEE, {"trust_id": trust_id})
        )
        assert meta["total_count"] == 1, "each trust holds exactly one L-SHARED-01"
        assert rows[0]["loan_number"] == "L-SHARED-01"


# ==========================================================================
# The deposit floor is inclusive on the accepting side
# ==========================================================================
def test_a_modification_deposit_exactly_at_the_floor_is_accepted(api):
    """Twenty-five thousand dollars is not below twenty-five thousand dollars.

    The PRD: "A deposit strictly below its floor is refused with
    `ERR_DEPOSIT_BELOW_MINIMUM`; a deposit exactly equal to the floor is
    accepted."

    Design: Corner/validations/modification_deposit_exactly_at_the_floor_is_accepted
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V23")
    loan = fx.create_mid_size_loan(api, trust["id"], loan_number="L-V23")
    event = fx.record_transfer_event(
        api,
        loan["id"],
        event_code="IMMINENT_DEFAULT",
        occurred_on="2026-07-15T00:00:00Z",
        evidence_note="borrower notified imminent monetary default",
        days_delinquent_at_event=None,
        imminent_default_certified=True,
    )
    assert event["triggers_transfer"] is True, (
        "a certified imminent default is a qualifying transfer event"
    )
    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    a.assert_status(transferred, "SPECIAL_SERVICING", "servicing_status")

    request = validate_success(
        api.create_borrower_request(
            f.modification_request_payload(
                loan["id"],
                processing_fee_deposit_usd=25000,
                proposed_rate_pct=4.5,
                proposed_maturity_date="2031-06-01T00:00:00Z",
            ),
            make_borrower_headers(loan["id"]),
        ),
        201,
    )
    a.assert_status(request, "SUBMITTED")
    a.assert_money(
        request["processing_fee_deposit_usd"], 25000.00, "processing_fee_deposit_usd"
    )
    assert request["info_request_count"] == 0
    a.assert_rate_pct(request["proposed_rate_pct"], 4.5, "proposed_rate_pct")
    assert request["proposed_maturity_date"].startswith("2031-06-01")
    a.assert_fields_null(
        request,
        "servicing_standard_margin_usd",
        "servicing_standard_conclusion",
        "decided_on",
        "decided_by_user_id",
        "assumption_buyer_name",
        "suite_code",
        "lease_commencement_date",
        "lease_expiration_date",
        "lease_base_rent_annual_usd",
    )


# ==========================================================================
# One field that is required on one variant and forbidden on the others
# ==========================================================================
def _loan_awaiting_a_valuation(api):
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V24"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V24"},
        event_factory=fx.record_bankruptcy_event,
    )
    return built["loan_id"]


def test_the_liquidation_expense_field_is_refused_where_it_is_forbidden(api):
    """Present on an UPDATE and absent on a FULL_NARRATIVE both fail the schema.

    The PRD: "it is **required** when the `appraisal_type` is `FULL_NARRATIVE` and
    **forbidden** otherwise, and it may not be negative. Supplying it on an
    `UPDATE` or `INTERNAL_VALUATION` appraisal, or omitting it on a
    `FULL_NARRATIVE` one, is likewise `ERR_INVALID_REQUEST`."

    Design: Corner/validations/conditionally_required_and_conditionally_forbidden_fields_both_enforced
    """
    loan_id = _loan_awaiting_a_valuation(api)
    update = fx.order_appraisal(api, loan_id)
    narrative = fx.order_appraisal(
        api,
        loan_id,
        appraisal_type="FULL_NARRATIVE",
        appraiser_firm="Beta Valuation",
    )

    forbidden = api.set_appraisal_status(
        update["id"],
        f.appraisal_received_payload(
            6000000, "2026-08-01T00:00:00Z", estimated_liquidation_expenses_usd=400000
        ),
        ASSET_MANAGER,
    )
    validate_error(forbidden, e.ERR_INVALID_REQUEST, 400)

    missing = api.set_appraisal_status(
        narrative["id"],
        f.appraisal_received_payload(6000000, "2026-08-01T00:00:00Z"),
        ASSET_MANAGER,
    )
    validate_error(missing, e.ERR_INVALID_REQUEST, 400)

    for appraisal in (update, narrative):
        untouched = validate_success(api.get_appraisal(appraisal["id"], ASSET_MANAGER))
        a.assert_status(untouched, "ORDERED")
        a.assert_fields_null(
            untouched,
            "value_usd",
            "as_of_date",
            "estimated_liquidation_expenses_usd",
            "coverage_start_date",
            "coverage_end_date",
        )


def test_the_compliant_narrative_drives_the_net_liquidation_variant(api):
    """Supplying the expenses where they are required flips the credit basis.

    The PRD: "When the driving appraisal's `appraisal_type` is `FULL_NARRATIVE`,
    the `calculation_basis` is `NET_LIQUIDATION_BASIS`: the appraiser's
    `estimated_liquidation_expenses_usd` is subtracted from `value_usd` first, and
    the credit is ninety percent of that net figure."

    Design: Corner/validations/conditionally_required_and_conditionally_forbidden_fields_both_enforced
    """
    loan_id = _loan_awaiting_a_valuation(api)
    narrative = fx.order_appraisal(
        api,
        loan_id,
        appraisal_type="FULL_NARRATIVE",
        appraiser_firm="Beta Valuation",
    )
    received = validate_success(
        api.set_appraisal_status(
            narrative["id"],
            f.appraisal_received_payload(
                6000000,
                "2026-08-01T00:00:00Z",
                estimated_liquidation_expenses_usd=400000,
            ),
            ASSET_MANAGER,
        )
    )
    a.assert_status(received, "RECEIVED")
    a.assert_money(
        received["estimated_liquidation_expenses_usd"],
        400000.00,
        "estimated_liquidation_expenses_usd",
    )
    assert received["coverage_start_date"].startswith("2026-08-01")
    assert received["coverage_end_date"].startswith("2027-08-01")

    fx.accept_appraisal(api, narrative["id"])
    reduction = fx.provisional_reduction(api, loan_id)
    assert reduction["calculation_basis"] == "NET_LIQUIDATION_BASIS"
    a.assert_money(reduction["deficiency_base_usd"], 10000000.00, "deficiency_base_usd")
    a.assert_money(reduction["appraisal_credit_usd"], 5040000.00, "appraisal_credit_usd")
    a.assert_money(reduction["ara_amount_usd"], 4960000.00, "ara_amount_usd")
    a.assert_ara_percentage(reduction["ara_percentage"], 49.6000)
    assert reduction["appraisal_credit_usd"] < 5400000.00, (
        "the net basis credits less than ninety percent of the raw value"
    )


# ==========================================================================
# The REMIC disposition deadline is inclusive on the permitting side
# ==========================================================================
def _reo_under_contract_from_a_foreclosure_plan(api):
    """A foreclosure carried to title and to contract, deadline 2029-08-01."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V25"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V25"},
        event_factory=fx.record_bankruptcy_event,
    )
    fx.accepted_appraisal(api, built["loan_id"], value_usd=5200000)
    plan = fx.executed_plan(
        api,
        built["trust_id"],
        built["loan_id"],
        alternative_builders=[
            lambda client, plan_id: fx.add_foreclosure_alternative(
                client,
                plan_id,
                projected_cash_flows=[
                    {"period_index": 1, "amount_usd": 0},
                    {"period_index": 2, "amount_usd": 5500000},
                ],
                upfront_cost_usd=400000,
            )
        ],
    )
    reo = fx.reo_under_contract(
        api,
        built["loan_id"],
        plan["plan_id"],
        list_price_usd=5400000,
        initial_noi_annual_usd=300000,
    )
    return built["loan_id"], reo


def test_a_closing_one_day_past_the_remic_deadline_is_refused(api):
    """2029-08-02 is beyond the third anniversary of 2026-08-01.

    The PRD: "A real-estate-owned sale closes on or before the REMIC disposition
    deadline, or `ERR_REMIC_DEADLINE_EXCEEDED`."

    Design: Corner/validations/reo_sale_after_the_three_year_remic_deadline_rejected
    """
    loan_id, reo = _reo_under_contract_from_a_foreclosure_plan(api)
    assert reo["remic_disposition_deadline"].startswith("2029-08-01")
    a.assert_status(reo, "UNDER_CONTRACT")

    response = api.set_reo_asset_status(
        reo["id"],
        f.liquidation_payload(
            5000000, 300000, "2029-08-02T00:00:00Z", to_status="SOLD"
        ),
        COMMITTEE_OFFICER,
    )
    validate_error(response, e.ERR_REMIC_DEADLINE_EXCEEDED, 422)

    unchanged = validate_success(api.get_reo_asset(reo["id"], COMMITTEE_OFFICER))
    a.assert_status(unchanged, "UNDER_CONTRACT")
    a.assert_fields_null(
        unchanged, "gross_sale_proceeds_usd", "liquidation_expenses_usd", "closing_date"
    )
    assert fx.fees_for_loan(api, loan_id, "LIQUIDATION_FEE") == [], (
        "a refused closing runs no waterfall and accrues no liquidation fee"
    )
    loan = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_status(loan, "REO", "servicing_status")


def test_a_closing_exactly_on_the_third_anniversary_is_permitted(api):
    """The identical body one day earlier closes and runs the waterfall.

    The PRD: "The `closing_date` must be at or before the asset's
    `remic_disposition_deadline`; a closing exactly on the third anniversary is
    permitted and one day later is refused with `ERR_REMIC_DEADLINE_EXCEEDED`."

    Design: Corner/validations/reo_sale_after_the_three_year_remic_deadline_rejected
    """
    loan_id, reo = _reo_under_contract_from_a_foreclosure_plan(api)
    validate_error(
        api.set_reo_asset_status(
            reo["id"],
            f.liquidation_payload(
                5000000, 300000, "2029-08-02T00:00:00Z", to_status="SOLD"
            ),
            COMMITTEE_OFFICER,
        ),
        e.ERR_REMIC_DEADLINE_EXCEEDED,
    )

    sold = validate_success(
        api.set_reo_asset_status(
            reo["id"],
            f.liquidation_payload(
                5000000, 300000, "2029-08-01T00:00:00Z", to_status="SOLD"
            ),
            COMMITTEE_OFFICER,
        )
    )
    a.assert_status(sold, "SOLD")
    a.assert_money(sold["gross_sale_proceeds_usd"], 5000000.00, "gross_sale_proceeds_usd")
    a.assert_money(sold["liquidation_expenses_usd"], 300000.00, "liquidation_expenses_usd")
    assert sold["closing_date"].startswith("2029-08-01")

    fees = fx.fees_for_loan(api, loan_id, "LIQUIDATION_FEE")
    assert len(fees) == 1, "the waterfall accrues exactly one liquidation fee"
    a.assert_money(fees[0]["basis_amount_usd"], 5000000.00, "basis_amount_usd")
    a.assert_money(fees[0]["amount_usd"], 50000.00, "amount_usd")


# ==========================================================================
# Three timely payments, counted in aggregate, gate the hand-back
# ==========================================================================
def _corrected_loan_with_two_timely_payments(api):
    """A modified loan in CORRECTED whose counter stands at two."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V26"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V26"},
        event_factory=fx.record_bankruptcy_event,
    )
    fx.accepted_appraisal(api, built["loan_id"], value_usd=9000000)
    plan = fx.executed_plan(
        api,
        built["trust_id"],
        built["loan_id"],
        alternative_builders=[fx.add_modification_alternative],
    )
    for as_of, expected in (("2026-08-01", 1), ("2026-08-02", 2)):
        paid = validate_success(
            api.set_loan_payment_status(
                built["loan_id"],
                {
                    "to_status": "CURRENT",
                    "as_of_date": f"{as_of}T00:00:00Z",
                    "timely_payment_recorded": True,
                },
                MASTER_SERVICER,
            )
        )
        assert paid["consecutive_timely_payments"] == expected
    corrected = validate_success(
        api.set_loan_servicing_status(
            built["loan_id"], f.status_payload("CORRECTED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(corrected, "CORRECTED", "servicing_status")
    assert corrected["correction_source_plan_id"] == plan["plan_id"]
    return built["trust_id"], built["loan_id"], corrected


def test_two_timely_payments_are_a_shortfall_and_three_are_enough(api):
    """The counter is read in aggregate; two is refused, the third unlocks it.

    The PRD: "the loan's `consecutive_timely_payments` must be at least three.
    Exactly three succeeds and two does not; a shortfall is refused with
    `ERR_INSUFFICIENT_TIMELY_PAYMENTS`."

    Design: Corner/validations/three_timely_payments_required_in_aggregate_before_returning_to_master_servicing
    """
    trust_id, loan_id, corrected = _corrected_loan_with_two_timely_payments(api)
    assert corrected["consecutive_timely_payments"] == 2

    response = api.set_loan_servicing_status(
        loan_id, f.status_payload("MASTER_SERVICING"), ASSET_MANAGER
    )
    validate_error(response, e.ERR_INSUFFICIENT_TIMELY_PAYMENTS, 422)

    stranded = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_status(stranded, "CORRECTED", "servicing_status")
    assert stranded["consecutive_timely_payments"] == 2
    assert stranded["version"] == corrected["version"], (
        "a refused hand-back advances neither the loan nor the trust"
    )
    trust = fx.read_trust(api, trust_id, TRUSTEE)
    assert trust["loans_in_special_servicing_count"] == 0, (
        "a CORRECTED loan is outside the special servicing population"
    )

    third = validate_success(
        api.set_loan_payment_status(
            loan_id,
            {
                "to_status": "CURRENT",
                "as_of_date": "2026-08-03T00:00:00Z",
                "timely_payment_recorded": True,
            },
            MASTER_SERVICER,
        )
    )
    assert third["consecutive_timely_payments"] == 3
    a.assert_status(third, "CORRECTED", "servicing_status")

    handed_back = validate_success(
        api.set_loan_servicing_status(
            loan_id, f.status_payload("MASTER_SERVICING"), ASSET_MANAGER
        )
    )
    a.assert_status(handed_back, "MASTER_SERVICING", "servicing_status")
    assert handed_back["consecutive_timely_payments"] == 3
    assert handed_back["is_modified"] is True
    assert handed_back["correction_source_plan_id"] == corrected["correction_source_plan_id"]


# ==========================================================================
# A dangling foreign key outranks a stale expected version
# ==========================================================================
def _loan_whose_version_has_already_moved(api):
    """Returns the loan id and a version that is now one behind."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V27"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V27"},
        event_factory=fx.record_bankruptcy_event,
    )
    stale_version = built["loan"]["version"]
    moved = validate_success(
        api.set_loan_payment_status(
            built["loan_id"],
            {
                "to_status": "CURRENT",
                "as_of_date": "2026-08-01T00:00:00Z",
                "timely_payment_recorded": True,
            },
            MASTER_SERVICER,
        )
    )
    assert moved["version"] > stale_version, "the payment write advanced the loan"
    return built["loan_id"], stale_version


def test_an_absent_loan_answers_not_found_even_with_a_stale_version(api):
    """Both rules fail; the earlier one in the precedence wins.

    The PRD: "Every foreign key in the request body resolves to a stored row, or
    the 404 not-found error naming that entity: a dangling `trust_id` gives
    `ERR_TRUST_NOT_FOUND`, a dangling `loan_id` gives `ERR_LOAN_NOT_FOUND`"

    Design: Corner/validations/existence_check_runs_before_the_optimistic_concurrency_check
    """
    loan_id, stale_version = _loan_whose_version_has_already_moved(api)

    response = api.create_workout_plan(
        f.workout_plan_payload(NON_EXISTENT_UUID, stale_version), ASSET_MANAGER
    )
    validate_error(response, e.ERR_LOAN_NOT_FOUND, 404)

    untouched = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_status(untouched, "SPECIAL_SERVICING", "servicing_status")
    a.assert_fields_null(untouched, "active_workout_plan_id")


def test_the_real_loan_with_the_same_stale_version_answers_a_conflict(api):
    """Swapping the identifier for the stored one exposes the version rule.

    The PRD: "The body's expected parent version matches the parent row's current
    `version`, or `ERR_STALE_LOAN_VERSION` / `ERR_STALE_TRUST_VERSION`."

    Design: Corner/validations/existence_check_runs_before_the_optimistic_concurrency_check
    """
    loan_id, stale_version = _loan_whose_version_has_already_moved(api)
    validate_error(
        api.create_workout_plan(
            f.workout_plan_payload(NON_EXISTENT_UUID, stale_version), ASSET_MANAGER
        ),
        e.ERR_LOAN_NOT_FOUND,
    )

    conflict = api.create_workout_plan(
        f.workout_plan_payload(loan_id, stale_version), ASSET_MANAGER
    )
    validate_error(conflict, e.ERR_STALE_LOAN_VERSION, 412)

    blocked = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_status(blocked, "SPECIAL_SERVICING", "servicing_status")
    a.assert_fields_null(blocked, "active_workout_plan_id")

    plan = validate_success(
        api.create_workout_plan(
            f.workout_plan_payload(loan_id, blocked["version"]), ASSET_MANAGER
        ),
        201,
    )
    a.assert_status(plan, "DRAFT")
    assert plan["revision_round"] == 0

    opened = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_status(opened, "IN_WORKOUT", "servicing_status")
    assert opened["active_workout_plan_id"] == plan["id"]

    rows, meta = validate_paginated(
        api.list_workout_plans(ASSET_MANAGER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 1, "the two refusals created no plan of their own"
    assert rows[0]["id"] == plan["id"]
