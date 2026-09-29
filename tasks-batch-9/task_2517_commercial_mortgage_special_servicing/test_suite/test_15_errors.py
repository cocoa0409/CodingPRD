"""The error surface: the two header gates that run ahead of every business
check, the narrower refusal of a forbidden target state, the per-entity
not-found codes, the empty scoring pool, and the two guards that stand between
a workout fee and the loan it would be earned on.
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
    ASSET_MANAGER_2,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    ROLE_MASTER_SERVICER,
    TRUSTEE,
    make_borrower_headers,
    make_controlling_class_representative_headers,
    make_headers,
)


# ==========================================================================
# The two header gates, ahead of every existence and state check
# ==========================================================================
def _one_trust_and_one_master_serviced_loan(api):
    """A boarded trust with a single loan still in MASTER_SERVICING."""
    trust = fx.create_trust(api, deal_name="CMBS 2026-V35")
    loan = fx.create_mid_size_loan(api, trust["id"], loan_number="L-V35")
    a.assert_status(loan, "MASTER_SERVICING", "servicing_status")
    return trust, loan


def test_an_empty_user_id_is_refused_before_the_addressed_row_is_looked_up(api):
    """Authentication is decided on the headers alone.

    The PRD: "Both authentication headers are present, non-empty and name one of
    the seven roles, or `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/unauthenticated_and_role_denied_calls_rejected_before_any_business_check
    """
    trust, loan = _one_trust_and_one_master_serviced_loan(api)
    anonymous = make_headers(ROLE_MASTER_SERVICER, "")

    validate_error(api.get_loan(loan["id"], anonymous), e.ERR_UNAUTHENTICATED, 401)
    validate_error(
        api.get_loan(NON_EXISTENT_UUID, anonymous), e.ERR_UNAUTHENTICATED, 401
    )
    validate_error(api.get_trust(trust["id"], anonymous), e.ERR_UNAUTHENTICATED, 401)
    validate_error(
        api.create_advance(f.advance_payload(loan["id"]), anonymous),
        e.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_loan(loan["id"], make_headers("Custodian", "ms-001")),
        e.ERR_UNAUTHENTICATED,
        401,
    )

    survivor = fx.read_loan(api, loan["id"], MASTER_SERVICER)
    a.assert_version_is(survivor, loan["version"], "loan")
    advances, meta = validate_paginated(
        api.list_advances(MASTER_SERVICER, {"loan_id": loan["id"]})
    )
    assert advances == []
    assert meta["total_count"] == 0


def test_a_role_outside_the_endpoints_list_is_refused_before_the_body_is_read(api):
    """The endpoint gate outranks the body's dangling foreign key.

    The PRD: "The role appears in the endpoint's permitted list, or
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/errors/unauthenticated_and_role_denied_calls_rejected_before_any_business_check
    """
    trust, loan = _one_trust_and_one_master_serviced_loan(api)
    trust_before = fx.read_trust(api, trust["id"])
    loan_before = fx.read_loan(api, loan["id"])

    # POST /advances admits the MasterServicer alone, so the Trustee is turned
    # away at rule 2 even though the body's loan_id names no stored row.
    validate_error(
        api.create_advance(f.advance_payload(NON_EXISTENT_UUID), TRUSTEE),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_trust(f.trust_payload(deal_name="CMBS 2026-V36"), MASTER_SERVICER),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(api.sweep_consultations({}, TRUSTEE), e.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(
        api.get_trust(trust["id"], make_borrower_headers(loan["id"])),
        e.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    trusts, trust_meta = validate_paginated(api.list_trusts(TRUSTEE))
    assert trust_meta["total_count"] == 1, "the refused creation boarded no trust"
    assert trusts[0]["deal_name"] == "CMBS 2026-V35"
    advances, advance_meta = validate_paginated(
        api.list_advances(MASTER_SERVICER, {"loan_id": loan["id"]})
    )
    assert advances == []
    assert advance_meta["total_count"] == 0
    a.assert_version_is(fx.read_trust(api, trust["id"]), trust_before["version"], "trust")
    a.assert_version_is(fx.read_loan(api, loan["id"]), loan_before["version"], "loan")


# ==========================================================================
# The narrower refusal: this role may not request this target state
# ==========================================================================
def _loan_in_special_servicing_with_one_advance(api):
    """A transferred loan carrying a single 60,000.00 principal-and-interest
    advance, both rows read back as stored."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V37"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V37"},
        event_factory=fx.record_bankruptcy_event,
    )
    advance = fx.record_advance(
        api,
        built["loan_id"],
        advance_type="PI_ADVANCE",
        amount_usd=60000,
        advanced_on="2026-08-01T00:00:00Z",
    )
    built["advance"] = advance
    return built


def test_the_system_only_targets_are_refused_to_every_role_that_asks(api):
    """Three system-driven targets, three refusals with the same code.

    The PRD: "That servicing-dimension move is system-driven only: a client asking
    for `IN_WORKOUT` directly is refused with `ERR_ROLE_NOT_PERMITTED_FOR_STATUS`
    regardless of role."

    Design: Corner/errors/permitted_role_requesting_a_forbidden_target_status_rejected
    """
    built = _loan_in_special_servicing_with_one_advance(api)
    loan_id = built["loan_id"]
    before = fx.read_loan(api, loan_id)
    a.assert_status(before, "SPECIAL_SERVICING", "servicing_status")

    for headers in (MASTER_SERVICER, ASSET_MANAGER, COMMITTEE_OFFICER):
        validate_error(
            api.set_loan_servicing_status(
                loan_id, f.status_payload("IN_WORKOUT"), headers
            ),
            e.ERR_ROLE_NOT_PERMITTED_FOR_STATUS,
            403,
        )
    still_special = fx.read_loan(api, loan_id)
    a.assert_status(still_special, "SPECIAL_SERVICING", "servicing_status")
    a.assert_version_is(still_special, before["version"], "loan")
    a.assert_fields_null(still_special, "active_workout_plan_id")

    # The plan's own system-only target, on a plan whose state does declare it:
    # a DRAFT plan is exactly what a later plan on the same loan supersedes.
    plan = fx.create_plan(api, loan_id, discount_rate_pct=8.0)
    a.assert_status(plan, "DRAFT")
    validate_error(
        api.set_workout_plan_status(
            plan["id"], f.status_payload("SUPERSEDED"), ASSET_MANAGER
        ),
        e.ERR_ROLE_NOT_PERMITTED_FOR_STATUS,
        403,
    )
    untouched_plan = validate_success(api.get_workout_plan(plan["id"], ASSET_MANAGER))
    a.assert_status(untouched_plan, "DRAFT")
    a.assert_version_is(untouched_plan, plan["version"], "workout plan")

    advance = built["advance"]
    a.assert_status(advance, "OUTSTANDING")
    for target, headers in (
        ("REIMBURSED", MASTER_SERVICER),
        ("PARTIALLY_REIMBURSED", COMMITTEE_OFFICER),
    ):
        validate_error(
            api.set_advance_status(advance["id"], f.status_payload(target), headers),
            e.ERR_ROLE_NOT_PERMITTED_FOR_STATUS,
            403,
        )
    untouched_advance = validate_success(
        api.get_advance(advance["id"], MASTER_SERVICER)
    )
    a.assert_status(untouched_advance, "OUTSTANDING")
    a.assert_money(untouched_advance["reimbursed_principal_usd"], 0.00)
    a.assert_money(untouched_advance["reimbursed_interest_usd"], 0.00)
    a.assert_version_is(untouched_advance, advance["version"], "advance")


def test_a_target_belonging_to_another_role_is_refused_though_the_state_allows_it(api):
    """The asset manager reaches the endpoint but not the committee's target.

    The PRD: "`ERR_ROLE_NOT_PERMITTED_FOR_STATUS` covers a specific requested
    target state: an endpoint's role list is the union over all the target states
    it can drive, and this narrower rule decides whether *this* role may request
    *this* target"

    Design: Corner/errors/permitted_role_requesting_a_forbidden_target_status_rejected
    """
    built = _loan_in_special_servicing_with_one_advance(api)
    consented = fx.consented_plan(
        api,
        built["trust_id"],
        built["loan_id"],
        alternative_builders=[fx.add_modification_alternative],
        discount_rate_pct=8.0,
    )
    plan_id = consented["plan_id"]
    before = validate_success(api.get_workout_plan(plan_id, ASSET_MANAGER))
    a.assert_status(before, "CONSENT_SATISFIED")

    # amgr-002 never authored this plan, so segregation of duties cannot be what
    # answers here; only the target state can be.
    validate_error(
        api.set_workout_plan_status(
            plan_id, f.status_payload("APPROVED"), ASSET_MANAGER_2
        ),
        e.ERR_ROLE_NOT_PERMITTED_FOR_STATUS,
        403,
    )
    validate_error(
        api.set_loan_servicing_status(
            built["loan_id"], f.status_payload("CORRECTED"), ASSET_MANAGER
        ),
        e.ERR_ROLE_NOT_PERMITTED_FOR_STATUS,
        403,
    )

    unchanged = validate_success(api.get_workout_plan(plan_id, ASSET_MANAGER))
    a.assert_status(unchanged, "CONSENT_SATISFIED")
    a.assert_fields_null(unchanged, "approved_by_user_id")
    a.assert_version_is(unchanged, before["version"], "workout plan")
    loan = fx.read_loan(api, built["loan_id"])
    a.assert_status(loan, "IN_WORKOUT", "servicing_status")

    approved = validate_success(
        api.set_workout_plan_status(
            plan_id, f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")
    assert approved["approved_by_user_id"] == "cmte-001"


# ==========================================================================
# Ten absent rows, ten distinct not-found codes
# ==========================================================================
def test_each_absent_row_answers_with_the_code_of_its_own_entity(api):
    """The one identifier is absent everywhere, yet every answer differs.

    The PRD: "Every identifier appearing as a path segment resolves to a stored
    row, or the 404 not-found error naming the entity of the *failing segment*"

    Design: Corner/errors/every_absent_row_id_returns_its_own_not_found_code
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V38")
    missing = NON_EXISTENT_UUID

    probes = [
        (api.get_trust(missing, ASSET_MANAGER), e.ERR_TRUST_NOT_FOUND),
        (api.get_loan(missing, ASSET_MANAGER), e.ERR_LOAN_NOT_FOUND),
        (api.get_transfer_event(missing, ASSET_MANAGER), e.ERR_TRANSFER_EVENT_NOT_FOUND),
        (
            api.get_borrower_request(missing, ASSET_MANAGER),
            e.ERR_BORROWER_REQUEST_NOT_FOUND,
        ),
        (api.get_appraisal(missing, ASSET_MANAGER), e.ERR_APPRAISAL_NOT_FOUND),
        (
            api.get_appraisal_reduction(missing, ASSET_MANAGER),
            e.ERR_APPRAISAL_REDUCTION_NOT_FOUND,
        ),
        (api.get_advance(missing, ASSET_MANAGER), e.ERR_ADVANCE_NOT_FOUND),
        (api.get_workout_plan(missing, ASSET_MANAGER), e.ERR_WORKOUT_PLAN_NOT_FOUND),
        (
            api.get_workout_alternative(missing, ASSET_MANAGER),
            e.ERR_WORKOUT_ALTERNATIVE_NOT_FOUND,
        ),
        (api.get_consultation(missing, ASSET_MANAGER), e.ERR_CONSULTATION_NOT_FOUND),
        (api.get_reo_asset(missing, ASSET_MANAGER), e.ERR_REO_ASSET_NOT_FOUND),
        (api.get_fee_accrual(missing, ASSET_MANAGER), e.ERR_FEE_ACCRUAL_NOT_FOUND),
        (
            api.get_distribution_report(missing, ASSET_MANAGER),
            e.ERR_DISTRIBUTION_REPORT_NOT_FOUND,
        ),
    ]
    reported = [
        validate_error(response, expected, 404)["error_id"]
        for response, expected in probes
    ]
    assert len(set(reported)) == len(probes), (
        "each addressed collection names its own entity, so no two codes coincide"
    )

    # The one row that does exist is still readable by its own id.
    a.assert_version_is(fx.read_trust(api, trust["id"]), trust["version"], "trust")


def test_an_absent_row_is_answered_before_its_state_or_its_owner_is_considered(api):
    """Existence of the addressed row precedes ownership and legality alike.

    The PRD: "Path segments are validated left to right, so where a loan owns the
    addressed sub-collection the loan is resolved before the child and the loan's
    not-found error wins."

    Design: Corner/errors/every_absent_row_id_returns_its_own_not_found_code
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-V38")
    missing = NON_EXISTENT_UUID

    # A transition on an appraisal that does not exist cannot be an illegal
    # transition: there is no current state to leave.
    validate_error(
        api.set_appraisal_status(
            missing,
            f.appraisal_received_payload(9000000, "2026-08-01T00:00:00Z"),
            ASSET_MANAGER,
        ),
        e.ERR_APPRAISAL_NOT_FOUND,
        404,
    )
    # The representative's ownership check compares trust_id to X-User-ID, but
    # there is no row to own.
    validate_error(
        api.respond_to_consultation(
            missing,
            f.consultation_response_payload("CONSENTED"),
            make_controlling_class_representative_headers(trust["id"]),
        ),
        e.ERR_CONSULTATION_NOT_FOUND,
        404,
    )
    # A computed read is no different: the loan segment fails first.
    validate_error(
        api.get_asset_business_plan(missing, ASSET_MANAGER), e.ERR_LOAN_NOT_FOUND, 404
    )
    validate_error(
        api.list_loan_transfer_events(missing, ASSET_MANAGER), e.ERR_LOAN_NOT_FOUND, 404
    )


# ==========================================================================
# Scoring needs a pool, and a superseded alternative is not in it
# ==========================================================================
def _draft_plan_on_a_receivership_loan(api):
    """An empty DRAFT plan at an 8% discount rate on a transferred loan."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V39"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V39"},
        event_factory=lambda client, loan_id: fx.record_transfer_event(
            client,
            loan_id,
            event_code="RECEIVERSHIP",
            occurred_on="2026-07-20T00:00:00Z",
            evidence_note="receiver appointed over the collateral",
        ),
    )
    plan = fx.create_plan(api, built["loan_id"], discount_rate_pct=8.0)
    built["plan"] = plan
    built["plan_id"] = plan["id"]
    return built


def test_a_plan_carrying_no_alternative_at_all_cannot_be_scored(api):
    """An empty plan presents an empty pool.

    The PRD: "Scoring — `DRAFT → SCORED` — requires at least one alternative on
    the plan that is still `PROPOSED` and is not named by any sibling's
    `supersedes_alternative_id`"

    Design: Corner/errors/scoring_a_plan_with_no_eligible_alternative_rejected
    """
    built = _draft_plan_on_a_receivership_loan(api)
    plan = built["plan"]
    a.assert_status(plan, "DRAFT")

    response = api.set_workout_plan_status(
        built["plan_id"], f.status_payload("SCORED"), ASSET_MANAGER
    )
    validate_error(response, e.ERR_NO_ALTERNATIVES, 422)

    unchanged = validate_success(api.get_workout_plan(built["plan_id"], ASSET_MANAGER))
    a.assert_status(unchanged, "DRAFT")
    a.assert_fields_null(
        unchanged, "recommended_alternative_id", "selected_alternative_id", "scored_on"
    )
    a.assert_version_is(unchanged, plan["version"], "workout plan")
    rows, meta = validate_paginated(
        api.list_workout_alternatives(ASSET_MANAGER, {"workout_plan_id": built["plan_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_superseded_alternative_is_outside_the_pool_that_gets_ranked(api):
    """The richer route is superseded, so the thinner one is recommended.

    The PRD: "alternatives named by a sibling's `supersedes_alternative_id` are
    moved to `SUPERSEDED` with `rank` null and are excluded from the pool."

    Design: Corner/errors/scoring_a_plan_with_no_eligible_alternative_rejected
    """
    built = _draft_plan_on_a_receivership_loan(api)
    plan_id = built["plan_id"]

    superseded = validate_success(
        api.create_workout_alternative(
            f.modification_alternative_payload(
                plan_id,
                projected_cash_flows=[{"period_index": 1, "amount_usd": 6000000}],
                upfront_cost_usd=100000,
            ),
            ASSET_MANAGER,
        ),
        201,
    )
    survivor = validate_success(
        api.create_workout_alternative(
            f.note_sale_alternative_payload(
                plan_id,
                projected_cash_flows=[{"period_index": 1, "amount_usd": 5000000}],
                upfront_cost_usd=50000,
                supersedes_alternative_id=superseded["id"],
            ),
            ASSET_MANAGER,
        ),
        201,
    )
    assert (
        superseded["projected_cash_flows"][0]["amount_usd"]
        > survivor["projected_cash_flows"][0]["amount_usd"]
    ), "the superseded route is the one with the larger recovery"

    scored = fx.score_plan(api, plan_id)
    a.assert_status(scored, "SCORED")
    assert scored["recommended_alternative_id"] == survivor["id"]
    assert scored["scored_on"].startswith("2026-08-01")
    a.assert_version_advanced_by(built["plan"], scored, 1, "workout plan")

    ranked = validate_success(api.get_workout_alternative(survivor["id"], ASSET_MANAGER))
    a.assert_status(ranked, "SCORED")
    assert ranked["rank"] == 1
    a.assert_money(ranked["discounted_pv_usd"], 4629629.63, "discounted_pv_usd")
    a.assert_money(ranked["npv_usd"], 4579629.63, "npv_usd")

    excluded = validate_success(
        api.get_workout_alternative(superseded["id"], ASSET_MANAGER)
    )
    a.assert_status(excluded, "SUPERSEDED")
    a.assert_fields_null(excluded, "rank")


# ==========================================================================
# The workout fee's two conjuncts, falsified one at a time
# ==========================================================================
def _one_transferred_loan_and_one_untouched_loan(api):
    """Loan X sits in SPECIAL_SERVICING; loan Y never left MASTER_SERVICING."""
    trust = fx.create_trust(api, deal_name="CMBS 2026-V40")
    loan_x = fx.create_mid_size_loan(api, trust["id"], loan_number="L-V40-X")
    fx.record_bankruptcy_event(api, loan_x["id"])
    fx.transfer_to_special_servicing(api, loan_x["id"])
    loan_y = fx.create_mid_size_loan(api, trust["id"], loan_number="L-V40-Y")
    return trust, fx.read_loan(api, loan_x["id"]), fx.read_loan(api, loan_y["id"])


def test_a_workout_fee_on_a_loan_still_in_special_servicing_is_refused(api):
    """The first conjunct fails: the asset has not gone back to the master servicer.

    The PRD: "the loan's `servicing_status` must be `MASTER_SERVICING` and its
    `correction_source_plan_id` must be non-null, failing which the accrual is
    refused with `ERR_WORKOUT_FEE_NOT_ELIGIBLE`."

    Design: Corner/errors/workout_fee_rejected_unless_the_loan_was_corrected_under_a_plan
    """
    _, loan_x, _ = _one_transferred_loan_and_one_untouched_loan(api)
    a.assert_status(loan_x, "SPECIAL_SERVICING", "servicing_status")
    a.assert_fields_null(loan_x, "correction_source_plan_id")

    response = api.create_fee_accrual(
        f.workout_fee_payload(loan_x["id"], collection_amount_usd=200000),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_WORKOUT_FEE_NOT_ELIGIBLE, 409)

    assert fx.fees_for_loan(api, loan_x["id"]) == []
    a.assert_money(fx.read_loan(api, loan_x["id"])["fees_payable_usd"], 0.00)

    # The monthly fee on that very loan, in that very state, is accepted — the
    # refusal above belongs to the workout fee's own eligibility rule.
    monthly = validate_success(
        api.create_fee_accrual(
            f.special_servicing_fee_payload(
                loan_x["id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            ASSET_MANAGER,
        ),
        201,
    )
    a.assert_status(monthly, "ACCRUED")
    assert monthly["fee_type"] == "SPECIAL_SERVICING_FEE"
    a.assert_money(monthly["basis_amount_usd"], 10000000.00, "basis_amount_usd")
    a.assert_rate_pct(monthly["rate_pct"], 0.020833)
    a.assert_money(monthly["amount_usd"], 2083.33, "amount_usd")

    rows, meta = validate_paginated(
        api.list_fee_accruals(ASSET_MANAGER, {"loan_id": loan_x["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [monthly["id"]]
    a.assert_money(fx.read_loan(api, loan_x["id"])["fees_payable_usd"], 2083.33)


def test_a_workout_fee_on_a_loan_that_was_never_corrected_is_refused(api):
    """The second conjunct fails on its own: master-serviced, but never corrected.

    The PRD: "The **workout fee** rewards handing a corrected loan back to the
    master servicer, and it is available only on a loan that genuinely completed
    that cycle"

    Design: Corner/errors/workout_fee_rejected_unless_the_loan_was_corrected_under_a_plan
    """
    _, _, loan_y = _one_transferred_loan_and_one_untouched_loan(api)
    a.assert_status(loan_y, "MASTER_SERVICING", "servicing_status")
    a.assert_fields_null(loan_y, "correction_source_plan_id")

    response = api.create_fee_accrual(
        f.workout_fee_payload(loan_y["id"], collection_amount_usd=200000),
        MASTER_SERVICER,
    )
    validate_error(response, e.ERR_WORKOUT_FEE_NOT_ELIGIBLE, 409)

    assert fx.fees_for_loan(api, loan_y["id"]) == []
    after = fx.read_loan(api, loan_y["id"])
    a.assert_money(after["fees_payable_usd"], 0.00)
    a.assert_version_is(after, loan_y["version"], "loan")


# ==========================================================================
# The mutual exclusion of the workout fee and the liquidation fee
# ==========================================================================
def _liquidated_loan_carrying_the_waterfalls_liquidation_fee(api):
    """A foreclosure carried through to a closed sale, minting the 1% fee."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V41"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V41"},
        event_factory=fx.record_bankruptcy_event,
    )
    loan_id = built["loan_id"]
    fx.accepted_appraisal(api, loan_id, value_usd=5200000)
    plan = fx.executed_plan(
        api,
        built["trust_id"],
        loan_id,
        alternative_builders=[
            lambda client, plan_id: fx.add_foreclosure_alternative(
                client,
                plan_id,
                projected_cash_flows=[{"period_index": 1, "amount_usd": 5200000}],
                upfront_cost_usd=150000,
            )
        ],
        discount_rate_pct=8.0,
    )
    reo = fx.reo_under_contract(
        api,
        loan_id,
        plan["plan_id"],
        list_price_usd=5500000,
        initial_noi_annual_usd=400000,
    )
    sold = validate_success(
        api.set_reo_asset_status(
            reo["id"],
            f.liquidation_payload(5000000, 300000, "2026-08-01T00:00:00Z", "SOLD"),
            COMMITTEE_OFFICER,
        )
    )
    a.assert_status(sold, "SOLD")
    built["reo"] = sold
    return built


def test_the_workout_fee_yields_to_the_liquidation_fee_already_on_the_loan(api):
    """The conflict is decided before eligibility is even considered.

    The PRD: "Accruing a `WORKOUT_FEE` on a loan that already carries a
    `LIQUIDATION_FEE` accrual in any status other than `WAIVED` is refused with
    `ERR_FEE_TYPE_CONFLICT`, and the reverse is equally forbidden."

    Design: Corner/errors/workout_fee_after_a_liquidation_fee_returns_the_conflict_code
    """
    built = _liquidated_loan_carrying_the_waterfalls_liquidation_fee(api)
    loan_id = built["loan_id"]

    minted = fx.fees_for_loan(api, loan_id, fee_type="LIQUIDATION_FEE")
    assert len(minted) == 1, "the waterfall mints exactly one liquidation fee"
    fee = minted[0]
    a.assert_status(fee, "ACCRUED")
    a.assert_money(fee["basis_amount_usd"], 5000000.00, "basis_amount_usd")
    a.assert_rate_pct(fee["rate_pct"], 1.0)
    a.assert_money(fee["amount_usd"], 50000.00, "amount_usd")
    assert fee["accrued_by_user_id"] == "system"

    liquidated = fx.read_loan(api, loan_id)
    a.assert_status(liquidated, "LIQUIDATED", "servicing_status")
    a.assert_money(liquidated["realized_loss_usd"], 5350000.00, "realized_loss_usd")

    response = api.create_fee_accrual(
        f.workout_fee_payload(loan_id, collection_amount_usd=200000), ASSET_MANAGER
    )
    validate_error(response, e.ERR_FEE_TYPE_CONFLICT, 409)
    assert fx.fees_for_loan(api, loan_id, fee_type="WORKOUT_FEE") == []
    rows, meta = validate_paginated(
        api.list_fee_accruals(ASSET_MANAGER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [fee["id"]]


def test_waiving_the_liquidation_fee_clears_the_conflict_but_not_the_eligibility(api):
    """With the conflict released, the workout fee's own rule answers instead.

    The PRD: "Waiving the earlier accrual clears the conflict."

    Design: Corner/errors/workout_fee_after_a_liquidation_fee_returns_the_conflict_code
    """
    built = _liquidated_loan_carrying_the_waterfalls_liquidation_fee(api)
    loan_id = built["loan_id"]
    fee = fx.fees_for_loan(api, loan_id, fee_type="LIQUIDATION_FEE")[0]

    waived = validate_success(
        api.set_fee_accrual_status(
            fee["id"],
            f.status_payload(
                "WAIVED", waived_reason="fee waived under the disposition settlement"
            ),
            COMMITTEE_OFFICER,
        )
    )
    a.assert_status(waived, "WAIVED")
    a.assert_money(fx.read_loan(api, loan_id)["fees_payable_usd"], 0.00)

    response = api.create_fee_accrual(
        f.workout_fee_payload(loan_id, collection_amount_usd=200000), ASSET_MANAGER
    )
    validate_error(response, e.ERR_WORKOUT_FEE_NOT_ELIGIBLE, 409)

    assert fx.fees_for_loan(api, loan_id, fee_type="WORKOUT_FEE") == []
    rows, meta = validate_paginated(
        api.list_fee_accruals(ASSET_MANAGER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [fee["id"]]
