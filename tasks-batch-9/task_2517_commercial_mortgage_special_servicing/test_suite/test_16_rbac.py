"""The role matrix proved in both directions: every role performing the
operations that belong to it alone, every role turned away from the operations
that belong to another, and the three blessings that no author may perform on
its own artefact.
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
    PLATFORM_ADMIN,
    ROLE_COMMITTEE_OFFICER,
    TRUSTEE,
    make_borrower_headers,
    make_controlling_class_representative_headers,
    make_headers,
)


# ==========================================================================
# The positive half of the matrix: all seven roles in one pass
# ==========================================================================
def test_all_seven_roles_perform_the_operations_reserved_to_them(api):
    """One end-to-end pass in which no call is ever refused.

    The PRD: "Only the `SpecialServicerAssetManager` orders appraisals."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    # PlatformAdmin — boarding a trust.
    trust = fx.create_trust(api, deal_name="CMBS 2026-V42")
    a.assert_status(trust, "CONTROLLING", "control_status")

    # MasterServicer — boarding a loan, both status dimensions and the advance.
    loan = fx.create_mid_size_loan(
        api, trust["id"], loan_number="L-V42", maturity_date="2029-06-01T00:00:00Z"
    )
    # The ladder is walked one rung at a time: CURRENT -> DELINQUENT_30 -> DELINQUENT_60.
    validate_success(
        api.set_loan_payment_status(
            loan["id"],
            f.status_payload("DELINQUENT_30", as_of_date="2026-06-15T00:00:00Z"),
            MASTER_SERVICER,
        )
    )
    delinquent = validate_success(
        api.set_loan_payment_status(
            loan["id"],
            f.status_payload("DELINQUENT_60", as_of_date="2026-07-15T00:00:00Z"),
            MASTER_SERVICER,
        )
    )
    a.assert_status(delinquent, "DELINQUENT_60", "payment_status")
    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    a.assert_status(transferred, "SPECIAL_SERVICING", "servicing_status")
    assert transferred["transfer_event_code"] == "MONETARY_DEFAULT_60D"
    advance = fx.record_advance(
        api,
        loan["id"],
        advance_type="PI_ADVANCE",
        amount_usd=60000,
        advanced_on="2026-07-01T00:00:00Z",
    )
    a.assert_status(advance, "OUTSTANDING")

    # SpecialServicerAssetManager — the valuation it orders and receives.
    appraisal = fx.order_appraisal(
        api,
        loan["id"],
        ordered_on="2026-06-20T00:00:00Z",
        appraiser_firm="Meridian Valuation",
    )
    assert appraisal["ordered_by_user_id"] == "amgr-001"
    fx.receive_appraisal(api, appraisal["id"], 9000000, "2026-07-01T00:00:00Z")
    accepted = fx.accept_appraisal(api, appraisal["id"])
    a.assert_status(accepted, "ACCEPTED")
    assert accepted["accepted_by_user_id"] == "amgr-002"

    # SpecialServicingCommitteeOfficer — blessing the reduction that acceptance made.
    provisional, meta = validate_paginated(
        api.list_appraisal_reductions(
            COMMITTEE_OFFICER, {"loan_id": loan["id"], "status": "PROVISIONAL"}
        )
    )
    assert meta["total_count"] == 1
    assert provisional[0]["appraisal_id"] == appraisal["id"]
    effective = fx.make_reduction_effective(api, provisional[0]["id"])
    a.assert_status(effective, "EFFECTIVE")

    # Borrower — its own request, submitted and withdrawn on its own loan id.
    request = fx.submit_assumption_request(api, loan["id"])
    a.assert_status(request, "SUBMITTED")
    withdrawn = fx.set_request_status(
        api, request["id"], "WITHDRAWN", headers=make_borrower_headers(loan["id"])
    )
    a.assert_status(withdrawn, "WITHDRAWN")

    # SpecialServicerAssetManager — authoring, scoring and recommending the plan.
    plan = fx.create_plan(api, loan["id"], discount_rate_pct=8.0)
    assert plan["prepared_by_user_id"] == "amgr-001"
    alternative = fx.add_modification_alternative(
        api,
        plan["id"],
        projected_cash_flows=[
            {"period_index": 1, "amount_usd": 1000000},
            {"period_index": 2, "amount_usd": 8500000},
        ],
        upfront_cost_usd=100000,
    )
    scored = fx.score_plan(api, plan["id"])
    assert scored["recommended_alternative_id"] == alternative["id"]
    fx.recommend_plan(api, plan["id"], alternative["id"])
    consultation = fx.issue_plan_consultation(api, trust["id"], plan["id"])
    assert consultation["rights_type"] == "CONSENT_RIGHT"

    # ControllingClassRepresentative — responding on its own trust id.
    answered = fx.respond_to_consultation(
        api, consultation["id"], trust["id"], "CONSENTED"
    )
    a.assert_status(answered, "CONSENTED")
    consented_plan = validate_success(api.get_workout_plan(plan["id"], ASSET_MANAGER))
    a.assert_status(consented_plan, "CONSENT_SATISFIED")

    # SpecialServicingCommitteeOfficer — the approval reserved to the committee.
    approved = fx.approve_plan(api, plan["id"])
    a.assert_status(approved, "APPROVED")
    assert approved["approved_by_user_id"] == "cmte-001"

    # Trustee — the report workflow that belongs to no one else.
    report = fx.create_distribution_report(
        api, trust["id"], period_end="2026-07-31T00:00:00Z"
    )
    certified = validate_success(
        api.set_distribution_report_status(
            report["id"], f.status_payload("CERTIFIED"), TRUSTEE
        )
    )
    a.assert_status(certified, "CERTIFIED")
    assert certified["certified_by_user_id"] == "trustee-001"

    # MasterServicer — accruing and then collecting the monthly fee.
    fee = validate_success(
        api.create_fee_accrual(
            f.special_servicing_fee_payload(
                loan["id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    assert fee["accrued_by_user_id"] == "ms-001"

    # PlatformAdmin — the sweep and the clock.
    swept = validate_success(
        api.sweep_consultations({"trust_id": trust["id"]}, PLATFORM_ADMIN)
    )
    assert swept["swept_count"] == 0, "the only consultation was answered in time"
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    collected = validate_success(
        api.set_fee_accrual_status(
            fee["id"], f.status_payload("COLLECTED"), MASTER_SERVICER
        )
    )
    a.assert_status(collected, "COLLECTED")
    assert collected["collected_on"].startswith("2026-08-02")


def test_the_two_entity_backed_roles_act_with_their_own_owning_key(api):
    """Presenting the owned row's id is what makes these two roles legitimate.

    The PRD: "A `Borrower` submitting a request must therefore present a `loan_id`
    equal to its own `X-User-ID`, may only withdraw a request whose `loan_id`
    equals its `X-User-ID`, and may only read its own loan and its own requests."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V42"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V42"},
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id, trust_id = built["loan_id"], built["trust_id"]
    borrower = make_borrower_headers(loan_id)
    representative = make_controlling_class_representative_headers(trust_id)

    request = fx.submit_assumption_request(api, loan_id)
    assert request["loan_id"] == loan_id
    own_loan = validate_success(api.get_loan(loan_id, borrower))
    assert own_loan["id"] == loan_id
    own_request = validate_success(api.get_borrower_request(request["id"], borrower))
    a.assert_status(own_request, "SUBMITTED")

    own_trust = validate_success(api.get_trust(trust_id, representative))
    a.assert_status(own_trust, "CONTROLLING", "control_status")
    plan = fx.create_plan(api, loan_id, discount_rate_pct=8.0)
    readable_plan = validate_success(api.get_workout_plan(plan["id"], representative))
    a.assert_status(readable_plan, "DRAFT")
    rows, meta = validate_paginated(
        api.list_consultations(representative, {"trust_id": trust_id})
    )
    assert rows == []
    assert meta["total_count"] == 0


# ==========================================================================
# The negative half: no role reaches another role's exclusive operation
# ==========================================================================
def _two_loans_with_one_in_special_servicing(api):
    """Loan P is transferred and carries an advance and a submitted lease
    request; loan Q is a second loan in the same trust."""
    trust = fx.create_trust(api, deal_name="CMBS 2026-V43")
    fx.create_trust(api, deal_name="CMBS 2026-V44", closing_date="2026-02-15T00:00:00Z",
                    original_controlling_class_balance_usd=25000000)
    loan_p = fx.create_mid_size_loan(
        api, trust["id"], loan_number="L-V43-P", maturity_date="2029-06-01T00:00:00Z"
    )
    loan_q = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V43-Q",
        original_balance_usd=8000000,
        current_principal_balance_usd=7000000,
        note_rate_pct=5.75,
        monthly_debt_service_usd=45000,
        maturity_date="2029-09-01T00:00:00Z",
        securitization_value_usd=9000000,
    )
    fx.record_bankruptcy_event(api, loan_p["id"], occurred_on="2026-07-01T00:00:00Z")
    fx.transfer_to_special_servicing(api, loan_p["id"])
    advance = fx.record_advance(
        api,
        loan_p["id"],
        advance_type="PI_ADVANCE",
        amount_usd=60000,
        advanced_on="2026-07-01T00:00:00Z",
    )
    request = fx.submit_lease_request(api, loan_p["id"], suite_code="S-100")
    return {
        "trust_id": trust["id"],
        "loan_p": fx.read_loan(api, loan_p["id"]),
        "loan_q": loan_q,
        "advance": advance,
        "request": request,
    }


def test_no_role_reaches_the_authoring_endpoint_of_another_role(api):
    """Five endpoints, five roles that plainly may not call them.

    The PRD: "The role appears in the endpoint's permitted list, or
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    built = _two_loans_with_one_in_special_servicing(api)
    loan_p_id = built["loan_p"]["id"]

    validate_error(
        api.create_appraisal(
            f.appraisal_payload(loan_p_id, ordered_on="2026-07-10T00:00:00Z"),
            MASTER_SERVICER,
        ),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_advance(
            f.advance_payload(
                loan_p_id,
                advance_type="PI_ADVANCE",
                amount_usd=10000,
                advanced_on="2026-07-15T00:00:00Z",
            ),
            ASSET_MANAGER,
        ),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.record_borrower_request_analysis(
            built["request"]["id"], f.lease_analysis_payload(), PLATFORM_ADMIN
        ),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.sweep_consultations({"trust_id": built["trust_id"]}, ASSET_MANAGER),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_workout_plan(
            f.workout_plan_payload(
                loan_p_id, built["loan_p"]["version"], discount_rate_pct=8.0
            ),
            COMMITTEE_OFFICER,
        ),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # Nothing was written by any of the five refusals.
    appraisals, appraisal_meta = validate_paginated(
        api.list_appraisals(ASSET_MANAGER, {"loan_id": loan_p_id})
    )
    assert appraisals == []
    assert appraisal_meta["total_count"] == 0
    plans, plan_meta = validate_paginated(
        api.list_workout_plans(ASSET_MANAGER, {"loan_id": loan_p_id})
    )
    assert plans == []
    assert plan_meta["total_count"] == 0
    advances, advance_meta = validate_paginated(
        api.list_advances(MASTER_SERVICER, {"loan_id": loan_p_id})
    )
    assert advance_meta["total_count"] == 1
    assert [row["id"] for row in advances] == [built["advance"]["id"]]
    still_submitted = validate_success(
        api.get_borrower_request(built["request"]["id"], ASSET_MANAGER)
    )
    a.assert_status(still_submitted, "SUBMITTED")
    a.assert_fields_null(
        still_submitted, "servicing_standard_margin_usd", "servicing_standard_conclusion"
    )
    after = fx.read_loan(api, loan_p_id)
    a.assert_status(after, "SPECIAL_SERVICING", "servicing_status")
    a.assert_version_is(after, built["loan_p"]["version"], "loan")


def test_the_master_servicer_may_call_the_advance_endpoint_but_not_that_target(api):
    """The endpoint gate passes and the narrower target gate refuses.

    The PRD: "`ERR_ROLE_NOT_PERMITTED_FOR_STATUS` covers a specific requested
    target state: an endpoint's role list is the union over all the target states
    it can drive, and this narrower rule decides whether *this* role may request
    *this* target"

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    built = _two_loans_with_one_in_special_servicing(api)
    advance_id = built["advance"]["id"]

    validate_error(
        api.set_advance_status(
            advance_id,
            f.status_payload(
                "DEEMED_NONRECOVERABLE",
                reversal_reason="collateral value below the advance",
            ),
            MASTER_SERVICER,
        ),
        e.ERR_ROLE_NOT_PERMITTED_FOR_STATUS,
        403,
    )
    untouched = validate_success(api.get_advance(advance_id, MASTER_SERVICER))
    a.assert_status(untouched, "OUTSTANDING")
    a.assert_version_is(untouched, built["advance"]["version"], "advance")

    # The same body from the committee is the legitimate call.
    deemed = validate_success(
        api.set_advance_status(
            advance_id,
            f.status_payload(
                "DEEMED_NONRECOVERABLE",
                reversal_reason="collateral value below the advance",
            ),
            COMMITTEE_OFFICER,
        )
    )
    a.assert_status(deemed, "DEEMED_NONRECOVERABLE")


def test_an_entity_backed_role_on_a_row_it_does_not_own_is_a_different_refusal(api):
    """Ownership denial and role denial are two distinct codes.

    The PRD: "An entity-backed caller owns the addressed row, or
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    built = _two_loans_with_one_in_special_servicing(api)
    loan_p_id = built["loan_p"]["id"]
    stranger = make_borrower_headers(built["loan_q"]["id"])
    owner = make_borrower_headers(loan_p_id)
    representative = make_controlling_class_representative_headers(built["trust_id"])

    validate_error(
        api.set_borrower_request_status(
            built["request"]["id"], f.status_payload("WITHDRAWN"), stranger
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(api.get_loan(loan_p_id, stranger), e.ERR_NOT_RESOURCE_OWNER, 403)
    # GET /loans/{id} does not list the representative at all, so no ownership
    # comparison is ever attempted.
    validate_error(
        api.get_loan(loan_p_id, representative), e.ERR_ROLE_NOT_PERMITTED, 403
    )
    # The advance ledger is outside the borrower's read surface even on its own loan.
    validate_error(
        api.get_advance(built["advance"]["id"], owner), e.ERR_ROLE_NOT_PERMITTED, 403
    )

    still_submitted = validate_success(
        api.get_borrower_request(built["request"]["id"], owner)
    )
    a.assert_status(still_submitted, "SUBMITTED")

    # The rightful borrower withdraws the very request the stranger could not.
    withdrawn = validate_success(
        api.set_borrower_request_status(
            built["request"]["id"], f.status_payload("WITHDRAWN"), owner
        )
    )
    a.assert_status(withdrawn, "WITHDRAWN")


# ==========================================================================
# Segregation of duties: the barrier is the individual, not the capacity
# ==========================================================================
def _received_appraisal_and_accrued_fee(api):
    """A valuation ordered and received by amgr-001 and a July fee accrued by
    ms-001, both awaiting somebody else's blessing."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V45"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V45",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=lambda client, loan_id: fx.record_transfer_event(
            client,
            loan_id,
            event_code="IMMINENT_DEFAULT",
            occurred_on="2026-07-01T00:00:00Z",
            evidence_note="borrower notice of imminent monetary default",
            days_delinquent_at_event=None,
            imminent_default_certified=True,
        ),
    )
    appraisal = fx.order_appraisal(
        api,
        built["loan_id"],
        ordered_on="2026-06-20T00:00:00Z",
        appraiser_firm="Meridian Valuation",
    )
    assert appraisal["ordered_by_user_id"] == "amgr-001"
    built["appraisal"] = fx.receive_appraisal(
        api, appraisal["id"], 9000000, "2026-07-01T00:00:00Z"
    )
    fee = validate_success(
        api.create_fee_accrual(
            f.special_servicing_fee_payload(
                built["loan_id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    assert fee["accrued_by_user_id"] == "ms-001"
    built["fee"] = fee
    return built


def test_the_orderer_may_neither_accept_nor_reject_its_own_valuation(api):
    """Both blessings are barred to the ordering user, and only to that user.

    The PRD: "Accepting a received appraisal — `RECEIVED → ACCEPTED` — is the
    single most consequential read of collateral value in the system, and it may
    not be performed by the person who ordered it: an `X-User-ID` equal to
    `ordered_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_author_of_a_row_can_never_bless_it
    """
    built = _received_appraisal_and_accrued_fee(api)
    appraisal = built["appraisal"]

    validate_error(
        api.set_appraisal_status(
            appraisal["id"], f.status_payload("ACCEPTED"), ASSET_MANAGER
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.set_appraisal_status(
            appraisal["id"],
            f.status_payload("REJECTED", rejection_reason="comparable set unusable"),
            ASSET_MANAGER,
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    untouched = validate_success(api.get_appraisal(appraisal["id"], ASSET_MANAGER))
    a.assert_status(untouched, "RECEIVED")
    a.assert_fields_null(untouched, "accepted_by_user_id")
    a.assert_version_is(untouched, appraisal["version"], "appraisal")
    assert fx.reductions_for_loan(api, built["loan_id"]) == []

    accepted = validate_success(
        api.set_appraisal_status(
            appraisal["id"], f.status_payload("ACCEPTED"), ASSET_MANAGER_2
        )
    )
    a.assert_status(accepted, "ACCEPTED")
    assert accepted["accepted_by_user_id"] == "amgr-002"
    reductions = fx.reductions_for_loan(api, built["loan_id"])
    assert len(reductions) == 1
    a.assert_status(reductions[0], "PROVISIONAL")
    a.assert_money(reductions[0]["ara_amount_usd"], 1900000.00, "ara_amount_usd")


def test_the_accruing_user_cannot_waive_even_wearing_the_committee_role(api):
    """The committee role is right and the individual is wrong.

    The PRD: "These are the only three operations that carry the check, and the
    check bites even when the caller's role plainly permits the operation — the
    barrier is the individual, not the capacity."

    Design: Corner/rbac/the_author_of_a_row_can_never_bless_it
    """
    built = _received_appraisal_and_accrued_fee(api)
    fee = built["fee"]
    waiver = f.status_payload("WAIVED", waived_reason="fee accrued in error")

    validate_error(
        api.set_fee_accrual_status(
            fee["id"], waiver, make_headers(ROLE_COMMITTEE_OFFICER, "ms-001")
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    untouched = validate_success(api.get_fee_accrual(fee["id"], MASTER_SERVICER))
    a.assert_status(untouched, "ACCRUED")
    a.assert_fields_null(untouched, "waived_reason")
    a.assert_version_is(untouched, fee["version"], "fee accrual")
    a.assert_money(fx.read_loan(api, built["loan_id"])["fees_payable_usd"], 2083.33)

    waived = validate_success(
        api.set_fee_accrual_status(fee["id"], waiver, COMMITTEE_OFFICER)
    )
    a.assert_status(waived, "WAIVED")
    assert waived["waived_reason"] == "fee accrued in error"
    a.assert_money(fx.read_loan(api, built["loan_id"])["fees_payable_usd"], 0.00)


def test_the_preparer_of_a_plan_cannot_approve_it_under_any_header(api):
    """The plan's author is barred though the target belongs to its header's role.

    The PRD: "The acting `X-User-ID` must differ from the plan's
    `prepared_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_author_of_a_row_can_never_bless_it
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V45"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={
            "loan_number": "L-V45",
            "maturity_date": "2029-06-01T00:00:00Z",
        },
        event_factory=fx.record_bankruptcy_event,
    )
    consented = fx.consented_plan(
        api,
        built["trust_id"],
        built["loan_id"],
        alternative_builders=[
            lambda client, plan_id: fx.add_modification_alternative(
                client,
                plan_id,
                projected_cash_flows=[
                    {"period_index": 1, "amount_usd": 1000000},
                    {"period_index": 2, "amount_usd": 8500000},
                ],
                upfront_cost_usd=100000,
            )
        ],
        discount_rate_pct=8.0,
    )
    plan_id = consented["plan_id"]
    before = validate_success(api.get_workout_plan(plan_id, ASSET_MANAGER))
    a.assert_status(before, "CONSENT_SATISFIED")
    assert before["prepared_by_user_id"] == "amgr-001"

    validate_error(
        api.set_workout_plan_status(
            plan_id,
            f.status_payload("APPROVED"),
            make_headers(ROLE_COMMITTEE_OFFICER, "amgr-001"),
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    unchanged = validate_success(api.get_workout_plan(plan_id, ASSET_MANAGER))
    a.assert_status(unchanged, "CONSENT_SATISFIED")
    a.assert_fields_null(unchanged, "approved_by_user_id")
    a.assert_version_is(unchanged, before["version"], "workout plan")

    approved = validate_success(
        api.set_workout_plan_status(
            plan_id, f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")
    assert approved["approved_by_user_id"] == "cmte-001"
    assert approved["prepared_by_user_id"] == "amgr-001"
