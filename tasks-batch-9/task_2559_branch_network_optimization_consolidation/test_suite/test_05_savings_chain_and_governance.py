"""Submission gates, the pinned savings chain, the decision branches and the review cycle."""

from test_helpers import (
    APPROVER,
    HR,
    OPS_ADMIN,
    REAL_ESTATE,
    SECOND_APPROVER,
    SECOND_STRATEGIST,
    STRATEGIST,
    ApiErrorId,
    api_client,
    closure_notice_payload,
    consolidation_case_payload,
    leased_property_disposition_payload,
    make_approver_headers,
    read_branch,
    read_case,
    read_forecast,
    read_property_disposition,
    retention_forecast_payload,
    setup_case_with_forecast,
    setup_draft_case,
    setup_market_with_branches,
    setup_submitted_case,
    validate_error,
    validate_paginated,
    validate_success,
)

RIVERBEND = {
    "name": "Riverbend North",
    "region_code": "MW-04",
    "population": 120000,
    "median_household_income_cents": 8500000,
    "deposit_market_total_cents": 240000000000,
    "competitor_branch_count": 24,
    "household_growth_pct_bps": 350,
    "digital_penetration_bps": 5200,
}

CEDAR_FLATS = {
    "name": "Cedar Flats",
    "region_code": "MW-07",
    "population": 90000,
    "median_household_income_cents": 6900000,
    "deposit_market_total_cents": 150000000000,
    "competitor_branch_count": 14,
    "household_growth_pct_bps": 180,
    "digital_penetration_bps": 4800,
}

DECAY_AT_3_4 = {
    "model_variant": "DISTANCE_DECAY",
    "distance_miles": 3.4,
    "retail_share_bps": 6000,
    "small_business_share_bps": 2500,
    "wealth_share_bps": 1500,
}


def _riverbend_case_with_forecast(closing_overrides=None, receiving_overrides=None):
    """Riverbend North pair carrying a DRAFT case and one ACTIVE decay forecast."""
    receiving = {
        "monthly_transaction_count": 7200,
        "digital_adoption_bps": 6800,
        "annual_noninterest_expense_cents": 118000000,
        "annual_revenue_cents": 305000000,
        "opened_on": "1998-06-15",
        "onboarding_capacity_households_per_day": 60,
    }
    receiving.update(receiving_overrides or {})
    closing = {"monthly_transaction_count": 3600, "annual_revenue_cents": 140000000}
    closing.update(closing_overrides or {})
    ctx = setup_market_with_branches(
        market_overrides=RIVERBEND,
        closing_overrides=closing,
        receiving_overrides=receiving,
    )
    return setup_case_with_forecast(
        ctx,
        case_overrides={"planned_closure_date": "2026-11-15"},
        forecast_overrides=DECAY_AT_3_4,
    )


def test_01_a_case_with_no_deposit_model_cannot_reach_the_approvers_desk():
    """Submitting a case that has never been modelled fails on the model gate, leaves the case
    in its opening state and runs none of the submission's arithmetic.

    PRD: "The case must also have exactly one retention forecast in `ACTIVE` status; none, and the submission fails with `ERR_RETENTION_FORECAST_MISSING`."
    PRD: "Submission carries no request body of its own and moves the case `DRAFT → SUBMITTED`, recomputing `severance_pool_cents` and the entire savings chain on the way through and incrementing the case's `version` by one."
    Design: Corner/validations/submit_without_an_active_forecast_returns_retention_forecast_missing
    """
    ctx = setup_draft_case()
    opening_version = ctx["case"]["version"]

    validate_error(
        api_client.submit_consolidation_case(ctx["case"]["id"], STRATEGIST),
        ApiErrorId.ERR_RETENTION_FORECAST_MISSING.value,
        expected_status=409,
    )

    case = read_case(ctx["case"]["id"])
    assert case["status"] == "DRAFT"
    assert case["version"] == opening_version
    assert case["gross_annual_savings_cents"] == 0
    assert case["net_annual_savings_cents"] == 0
    assert case["severance_pool_cents"] == 0


def test_02_each_exclusive_operation_refuses_every_role_that_does_not_own_it():
    """The role gate is evaluated before any state or version rule, so an operations admin, an
    HR partner and a premises manager are each refused the operation they do not own — while the
    premises manager keeps the shared read and the owning role's identical call succeeds.

    PRD: "The server evaluates guards in one fixed global order and returns the first failure it encounters; it never masks an earlier-ranked failure behind a later-ranked one."
    PRD: "2. **Role authorisation for the endpoint** — `ERR_FORBIDDEN_ROLE`."
    PRD: "Regulatory work — impact assessment, assessment finalisation, notice filing and withdrawal, transition-wave planning and launch, closure execution and closure unwind — belongs exclusively to `ComplianceOfficer`."
    Design: Corner/rbac/every_other_role_is_refused_an_exclusive_operation_it_does_not_own
    """
    ctx = setup_case_with_forecast()
    case_id = ctx["case"]["id"]
    drafted_version = ctx["case"]["version"]

    validate_error(
        api_client.submit_consolidation_case(case_id, OPS_ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    validate_error(
        api_client.create_closure_notice(closure_notice_payload(case_id), HR),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    validate_error(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": drafted_version},
            REAL_ESTATE,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )

    read_back = validate_success(api_client.get_consolidation_case(case_id, REAL_ESTATE))
    assert read_back["status"] == "DRAFT"
    assert read_back["version"] == drafted_version
    assert read_back["decided_by_user_id"] is None

    _, notice_meta = validate_paginated(
        api_client.list_case_closure_notices(case_id, STRATEGIST)
    )
    assert notice_meta["total_count"] == 0

    submitted = validate_success(
        api_client.submit_consolidation_case(case_id, STRATEGIST)
    )
    assert submitted["status"] == "SUBMITTED"


def test_03_holding_the_strategist_role_does_not_make_a_case_yours():
    """A second strategist is refused both the submission and the revision of a colleague's
    case, the refused revision changes nothing on the record, and the author's identical
    submission goes through.

    PRD: "Conversely, submission and revision of a case are reserved to its author: a `NetworkStrategist` whose `X-User-ID` differs from the case's `created_by_user_id` is rejected with `ERR_CASE_AUTHOR_REQUIRED` (HTTP 403)."
    PRD: "Revision is likewise restricted to the case's author."
    Design: Corner/rbac/a_second_strategist_cannot_submit_another_authors_case
    """
    ctx = setup_case_with_forecast(case_overrides={"rationale_code": "DIGITAL_MIGRATION"})
    case_id = ctx["case"]["id"]
    drafted_version = ctx["case"]["version"]
    assert ctx["case"]["created_by_user_id"] == "u_strategist_1"

    validate_error(
        api_client.submit_consolidation_case(case_id, SECOND_STRATEGIST),
        ApiErrorId.ERR_CASE_AUTHOR_REQUIRED.value,
        expected_status=403,
    )
    validate_error(
        api_client.revise_consolidation_case(
            case_id, {"planned_closure_date": "2026-12-15"}, SECOND_STRATEGIST
        ),
        ApiErrorId.ERR_CASE_AUTHOR_REQUIRED.value,
        expected_status=403,
    )
    assert read_case(case_id)["planned_closure_date"] == "2026-12-01"

    submitted = validate_success(
        api_client.submit_consolidation_case(case_id, STRATEGIST)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] > drafted_version
    assert submitted["returned_count"] == 0
    assert submitted["net_annual_savings_cents"] == 18320000


def test_04_the_incentive_tier_is_read_off_gross_savings_and_never_off_net():
    """A case whose gross savings clear the top tier pays the thinnest incentive rate, and the
    resulting net figure — itself below that same tier threshold — never feeds back into the rate.

    PRD: "Fifth, `transition_incentive_rate_bps` is selected from a tier table keyed on that gross figure: 12 basis points when gross savings reach 1,000,000 dollars (one hundred million cents, 100,000,000) or more, 18 basis points when gross savings are at least 400,000 dollars (forty million cents, 40,000,000) but below 100,000,000 cents, and 25 basis points when gross savings fall below 40,000,000 cents."
    PRD: "The tier in the fifth step is always selected from the fourth step's **gross** value and is never re-derived from the seventh step's **net** value, even though net is the figure the governance floor is tested against."
    PRD: "Seventh, `net_annual_savings_cents` is `gross_annual_savings_cents` minus `transition_incentive_cents`."
    Design: Difficulty/combinatorial_formula/net_savings_incentive_tier_pinned_to_gross_not_net
    """
    ctx = _riverbend_case_with_forecast(
        closing_overrides={
            "branch_code": "RB-301",
            "deposit_balance_cents": 8000000000,
            "annual_noninterest_expense_cents": 125000000,
            "monthly_transaction_count": 4200,
            "annual_revenue_cents": 300000000,
            "fte_count": 12,
            "opened_on": "2001-09-04",
        },
        receiving_overrides={
            "branch_code": "RB-302",
            "deposit_balance_cents": 9000000000,
            "monthly_transaction_count": 7000,
            "digital_adoption_bps": 6600,
            "annual_noninterest_expense_cents": 130000000,
            "annual_revenue_cents": 320000000,
            "fte_count": 15,
            "opened_on": "1996-02-20",
        },
    )
    property_disposition = validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"],
                ctx["case"]["id"],
                atm_disposition="RELOCATE",
                buyout_offer_cents=500000,
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert property_disposition["annual_carry_cents"] == 3000000

    submitted = validate_success(
        api_client.submit_consolidation_case(ctx["case"]["id"], STRATEGIST)
    )

    assert submitted["forecast_retained_deposits_cents"] == 7360000000
    assert submitted["forecast_runoff_cents"] == 640000000
    assert submitted["gross_annual_savings_cents"] == 107600000
    assert submitted["transition_incentive_rate_bps"] == 12
    assert submitted["transition_incentive_cents"] == 8832000
    assert submitted["net_annual_savings_cents"] == 98768000
    assert submitted["transition_incentive_cents"] != 13248000
    assert submitted["status"] == "SUBMITTED"


def test_05_the_pinned_tier_already_holds_when_a_premises_carry_lands():
    """The chain is recomputed the moment a premises disposition is opened, and even at that
    earlier point the rate is chosen from gross: the same 12 basis points, not the 18 a
    net-derived tier would charge.

    PRD: "The chain is recomputed in full whenever a retention forecast is created, whenever a case is submitted, whenever a staff disposition is created, and on every premises-disposition status change that moves `annual_carry_cents`."
    PRD: "Third, the **property carry** is the sum of `annual_carry_cents` across every premises disposition attached to the case, regardless of that disposition's status."
    PRD: "Sixth, `transition_incentive_cents` is the case's `forecast_retained_deposits_cents` multiplied by that selected rate, divided by 10000 and rounded half up — the bank pays to keep the deposits it expects to retain, and it pays a *higher* rate when the underlying savings are thinner."
    Design: Difficulty/combinatorial_formula/net_savings_incentive_tier_pinned_to_gross_not_net
    """
    ctx = _riverbend_case_with_forecast(
        closing_overrides={
            "branch_code": "RB-301",
            "deposit_balance_cents": 8000000000,
            "annual_noninterest_expense_cents": 125000000,
            "monthly_transaction_count": 4200,
            "annual_revenue_cents": 300000000,
            "fte_count": 12,
            "opened_on": "2001-09-04",
        },
        receiving_overrides={"branch_code": "RB-302"},
    )

    before_carry = read_case(ctx["case"]["id"])
    assert before_carry["gross_annual_savings_cents"] == 110600000
    assert before_carry["transition_incentive_rate_bps"] == 12
    assert before_carry["net_annual_savings_cents"] == 101768000

    disposition = validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"],
                ctx["case"]["id"],
                atm_disposition="RELOCATE",
                buyout_offer_cents=500000,
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert read_property_disposition(disposition["id"])["status"] == "PENDING"

    after_carry = read_case(ctx["case"]["id"])
    assert after_carry["gross_annual_savings_cents"] == 107600000
    assert after_carry["transition_incentive_rate_bps"] == 12
    assert after_carry["transition_incentive_cents"] == 8832000
    assert after_carry["net_annual_savings_cents"] == 98768000
    assert after_carry["status"] == "DRAFT"


def test_06_a_returned_case_keeps_its_branch_and_its_model_while_it_is_reworked():
    """Returning a case advances the revision counter once and hands the file back to its author
    without releasing the branch or discarding the deposit model; revision reopens it for edit.

    PRD: "On success the case transitions `SUBMITTED → RETURNED` and `returned_count` increments by one."
    PRD: "The author may then revise the case, which moves it `RETURNED → DRAFT` and optionally applies a new `planned_closure_date` and a new `receiving_branch_id`; when a receiving branch is supplied on revision it must be in `ACTIVE` status and must not be the closing branch itself, on pain of `ERR_RECEIVING_BRANCH_INVALID`."
    PRD: "All three branches stamp `decided_by_user_id` from the deciding approver and increment the case's `version` by one."
    Design: Difficulty/non_linear_state_machine/case_return_revise_resubmit_cycle_then_approved
    """
    ctx = _riverbend_case_with_forecast()
    case_id = ctx["case"]["id"]
    submitted = validate_success(api_client.submit_consolidation_case(case_id, STRATEGIST))

    returned = validate_success(
        api_client.decide_consolidation_case(
            case_id,
            {
                "decision": "RETURN",
                "reason_code": "NEED_TRADE_AREA_DETAIL",
                "expected_case_version": submitted["version"],
            },
            APPROVER,
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["returned_count"] == 1
    assert returned["decided_by_user_id"] == "u_approver_1"
    assert returned["version"] == submitted["version"] + 1
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    assert read_forecast(ctx["forecast"]["id"])["status"] == "ACTIVE"

    revised = validate_success(
        api_client.revise_consolidation_case(
            case_id, {"planned_closure_date": "2026-12-01"}, STRATEGIST
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["planned_closure_date"] == "2026-12-01"
    assert revised["returned_count"] == 1


def test_07_a_case_that_loops_through_revision_can_still_be_approved():
    """The full submit, return, revise, resubmit, approve cycle lands the case at approval with
    its counter at one, its revised closure date on file and its branch still under review.

    PRD: "The full `DRAFT → SUBMITTED → RETURNED → DRAFT` cycle may therefore run at most three times before the case is permanently stuck in review."
    PRD: "An `APPROVE` decision requires that the case's `net_annual_savings_cents` be at least the governance floor of 150,000 dollars — fifteen million cents, written out as 15,000,000."
    PRD: "On success the case transitions `SUBMITTED → APPROVED` and nothing else moves; the closing branch remains at `UNDER_REVIEW`."
    Design: Difficulty/non_linear_state_machine/case_return_revise_resubmit_cycle_then_approved
    """
    ctx = _riverbend_case_with_forecast()
    case_id = ctx["case"]["id"]

    first_submit = validate_success(
        api_client.submit_consolidation_case(case_id, STRATEGIST)
    )
    validate_success(
        api_client.decide_consolidation_case(
            case_id,
            {
                "decision": "RETURN",
                "reason_code": "NEED_TRADE_AREA_DETAIL",
                "expected_case_version": first_submit["version"],
            },
            APPROVER,
        )
    )
    validate_success(
        api_client.revise_consolidation_case(
            case_id, {"planned_closure_date": "2026-12-01"}, STRATEGIST
        )
    )
    second_submit = validate_success(
        api_client.submit_consolidation_case(case_id, STRATEGIST)
    )
    assert second_submit["status"] == "SUBMITTED"

    approved = validate_success(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": second_submit["version"]},
            APPROVER,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["returned_count"] == 1
    assert approved["planned_closure_date"] == "2026-12-01"
    assert approved["decided_by_user_id"] == "u_approver_1"
    assert approved["net_annual_savings_cents"] == 18320000
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    assert read_forecast(ctx["forecast"]["id"])["status"] == "ACTIVE"


def test_08_a_returned_case_must_be_revised_before_it_can_be_resubmitted():
    """Submission is declared only out of the drafting state, so pushing a returned case
    straight back to the approver is refused and writes nothing.

    PRD: "Submission is available only to the strategist who authored the case, and only from `DRAFT` status; a submission from any other status is `ERR_CASE_STATE_INVALID`, and a submission by any other `NetworkStrategist` is `ERR_CASE_AUTHOR_REQUIRED`."
    Design: Corner/state_machines/submit_case_from_returned_returns_case_state_invalid
    """
    ctx = setup_submitted_case()
    case_id = ctx["case"]["id"]
    returned = validate_success(
        api_client.decide_consolidation_case(
            case_id,
            {
                "decision": "RETURN",
                "reason_code": "FORECAST_REVISION",
                "expected_case_version": ctx["case"]["version"],
            },
            APPROVER,
        )
    )

    validate_error(
        api_client.submit_consolidation_case(case_id, STRATEGIST),
        ApiErrorId.ERR_CASE_STATE_INVALID.value,
        expected_status=409,
    )

    case = read_case(case_id)
    assert case["status"] == "RETURNED"
    assert case["returned_count"] == 1
    assert case["version"] == returned["version"]


def test_09_a_rejected_case_is_closed_to_every_further_decision():
    """Rejection is terminal: a second decision from a different approver is refused, and the
    rejection's own cascade — branch released, model superseded, impact figures reset — stands.

    PRD: "`REJECTED`, `SUPERSEDED`, `UNWOUND` and `CLOSED_OUT` are the four terminal statuses a case can reach; no operation moves a case out of any of them."
    PRD: "The closing branch transitions `UNDER_REVIEW → ACTIVE` and its `version` increments — released back into the network, provided the rejected case is the only case on that branch in `SUBMITTED`, `APPROVED` or `NOTICE_FILED` status."
    PRD: "The case's `ACTIVE` retention forecast transitions to `SUPERSEDED`."
    Design: Corner/state_machines/rejected_case_accepts_no_further_decision
    """
    ctx = setup_submitted_case(case_overrides={"rationale_code": "LEASE_EXPIRY"})
    case_id = ctx["case"]["id"]
    rejected = validate_success(
        api_client.decide_consolidation_case(
            case_id,
            {
                "decision": "REJECT",
                "reason_code": "STRATEGY_HOLD",
                "expected_case_version": ctx["case"]["version"],
            },
            APPROVER,
        )
    )
    assert rejected["status"] == "REJECTED"

    validate_error(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": rejected["version"]},
            SECOND_APPROVER,
        ),
        ApiErrorId.ERR_CASE_STATE_INVALID.value,
        expected_status=409,
    )

    case = read_case(case_id)
    assert case["status"] == "REJECTED"
    assert case["version"] == rejected["version"]
    assert case["decided_by_user_id"] == "u_approver_1"
    assert case["impact_tier"] == "UNASSESSED"
    assert case["notice_required_days"] == 0
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "ACTIVE"
    assert read_forecast(ctx["forecast"]["id"])["status"] == "SUPERSEDED"


def test_10_the_fourth_return_is_refused_while_an_approval_on_the_same_state_succeeds():
    """The revision counter only ever moves on a return, and once it stands at the limit a
    further return is refused without consuming the pinned version — which the very next
    approval proves by validating against that same token.

    PRD: "A `RETURN` decision requires that the case's `returned_count` still be below the revision limit of three."
    PRD: "A fourth return attempt is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
    PRD: "On success the case transitions `SUBMITTED → APPROVED` and nothing else moves; the closing branch remains at `UNDER_REVIEW`."
    Design: Corner/errors/a_fourth_return_decision_hits_the_revision_limit
    """
    ctx = setup_submitted_case()
    case_id = ctx["case"]["id"]
    current = ctx["case"]

    for expected_count in (1, 2, 3):
        returned = validate_success(
            api_client.decide_consolidation_case(
                case_id,
                {
                    "decision": "RETURN",
                    "reason_code": "SAVINGS_CASE_THIN",
                    "expected_case_version": current["version"],
                },
                APPROVER,
            )
        )
        assert returned["returned_count"] == expected_count
        validate_success(api_client.revise_consolidation_case(case_id, {}, STRATEGIST))
        current = validate_success(
            api_client.submit_consolidation_case(case_id, STRATEGIST)
        )
        assert current["returned_count"] == expected_count

    assert current["status"] == "SUBMITTED"
    pinned = current["version"]

    validate_error(
        api_client.decide_consolidation_case(
            case_id,
            {
                "decision": "RETURN",
                "reason_code": "SAVINGS_CASE_THIN",
                "expected_case_version": pinned,
            },
            APPROVER,
        ),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value,
        expected_status=409,
    )
    assert read_case(case_id)["status"] == "SUBMITTED"

    approved = validate_success(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": pinned},
            APPROVER,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["returned_count"] == 3
    assert approved["net_annual_savings_cents"] == 18320000
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"


def _cedar_flats_submitted_case() -> dict:
    """Cedar Flats pair whose submitted case nets 10320000 cents — below the governance floor.

    Returns the context plus "creation_version", the version token captured at case creation
    and therefore stale once the forecast and the submission have each bumped it.
    """
    ctx = setup_market_with_branches(
        market_overrides=CEDAR_FLATS,
        closing_overrides={
            "branch_code": "RB-201",
            "annual_noninterest_expense_cents": 30000000,
            "monthly_transaction_count": 3100,
            "annual_revenue_cents": 126000000,
            "fte_count": 7,
            "atm_count": 1,
            "opened_on": "2009-04-01",
        },
        receiving_overrides={
            "branch_code": "RB-202",
            "deposit_balance_cents": 8800000000,
            "monthly_transaction_count": 6900,
            "digital_adoption_bps": 6600,
            "annual_noninterest_expense_cents": 104000000,
            "annual_revenue_cents": 280000000,
            "fte_count": 13,
            "atm_count": 2,
            "opened_on": "2001-02-01",
            "onboarding_capacity_households_per_day": 45,
        },
    )
    created = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    ctx["creation_version"] = created["version"]
    validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(created["id"], created["version"], **DECAY_AT_3_4),
            STRATEGIST,
        ),
        expected_status=201,
    )
    ctx["case"] = validate_success(
        api_client.submit_consolidation_case(created["id"], STRATEGIST)
    )
    return ctx


def test_11_a_case_whose_net_savings_miss_the_floor_cannot_be_approved():
    """A thin business case computes cleanly, pays the fattest incentive rate because its gross
    savings are small, and is then refused at approval by the governance floor.

    PRD: "Fourth, `gross_annual_savings_cents` is the expense avoided minus the revenue attrition minus the property carry; it may legitimately be negative."
    PRD: "A case below that floor is rejected with `ERR_SAVINGS_BELOW_FLOOR`, and the boundary is inclusive, so a case whose net savings equal exactly 15,000,000 cents is approvable."
    Design: Difficulty/priority_pair_validation_conflict/segregation_then_stale_version_then_savings_floor_ladder
    """
    ctx = _cedar_flats_submitted_case()
    case = ctx["case"]

    assert case["gross_annual_savings_cents"] == 21360000
    assert case["transition_incentive_rate_bps"] == 25
    assert case["transition_incentive_cents"] == 11040000
    assert case["net_annual_savings_cents"] == 10320000

    validate_error(
        api_client.decide_consolidation_case(
            case["id"],
            {"decision": "APPROVE", "expected_case_version": case["version"]},
            APPROVER,
        ),
        ApiErrorId.ERR_SAVINGS_BELOW_FLOOR.value,
        expected_status=422,
    )

    after = read_case(case["id"])
    assert after["status"] == "SUBMITTED"
    assert after["version"] == case["version"]
    assert after["decided_by_user_id"] is None


def test_12_the_decision_ladder_peels_authority_then_concurrency_then_the_floor():
    """One decision body that violates segregation of duties, version pinning and the savings
    floor at once reports them strictly in precedence order as each earlier fault is fixed, and
    none of the three refusals leaves a trace on the case.

    PRD: "A `ConsolidationApprover` whose `X-User-ID` equals the case's `created_by_user_id` may not record a decision on that case; the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD: "The same pinning field and the same error code guard `POST /distribution/consolidation-cases/{caseId}/decision`, where the approver's decision must be taken against the exact case revision the approver read."
    PRD: "The practical consequence of this ordering is worth stating twice: a request that is simultaneously unauthorised and malformed reports the authorisation failure, a request that names a stale branch version and also targets a branch with an open case reports the stale version, and a de novo approval that fails both the score minimum and the saturation gate reports the score minimum."
    Design: Difficulty/priority_pair_validation_conflict/segregation_then_stale_version_then_savings_floor_ladder
    """
    ctx = _cedar_flats_submitted_case()
    case_id = ctx["case"]["id"]
    stale_version = ctx["creation_version"]
    current_version = ctx["case"]["version"]
    author_as_approver = make_approver_headers("u_strategist_1")

    validate_error(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": stale_version},
            author_as_approver,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    validate_error(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": stale_version},
            APPROVER,
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
        expected_status=412,
    )
    validate_error(
        api_client.decide_consolidation_case(
            case_id,
            {"decision": "APPROVE", "expected_case_version": current_version},
            APPROVER,
        ),
        ApiErrorId.ERR_SAVINGS_BELOW_FLOOR.value,
        expected_status=422,
    )

    case = read_case(case_id)
    assert case["status"] == "SUBMITTED"
    assert case["version"] == current_version
    assert case["decided_by_user_id"] is None
    assert case["returned_count"] == 0
