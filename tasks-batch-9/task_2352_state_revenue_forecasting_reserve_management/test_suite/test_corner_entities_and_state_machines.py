"""Entity contracts and state-machine transitions of the State Revenue
Forecasting Reserves API.

Every test builds its own world through the public endpoints: the server is
restarted with an empty database before each one.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import test_users as U


# =========================================================================== #
# Entities
# =========================================================================== #
def test_revenue_source_creation_returns_201_with_system_defaults(api):
    """PRD §3.2: "A newly registered source begins with `status` `ACTIVE`, `mape_bps` 0, `methodology_flag` false and `posted_actual_count` 0."

    PRD §2.6: "Every resource carries an `id`: a server-minted UUID with no type prefix, supplied by the server and never by the client."

    Design: Corner/entities/revenue_source_creation_returns_201_with_system_defaults
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    response = api.create_revenue_source(F.pit_source_payload(), U.make_director_headers())
    source = validate_success(response, 201)

    assert is_valid_uuid(source["id"])
    assert source["status"] == "ACTIVE"
    assert source["mape_bps"] == 0
    assert source["methodology_flag"] is False
    assert source["posted_actual_count"] == 0
    A.assert_version(source, 1)
    assert source["base_year_receipts_cents"] == C.PIT_BASE_RECEIPTS_CENTS
    assert source["elasticity_wage_income_bps"] == C.PIT_ELASTICITY_WAGE_BPS
    assert source["volatility_class"] == "MEDIUM"
    assert is_iso8601_timestamp(source["created_at"])


def test_forecast_cycle_retrieval_returns_stored_row_with_null_aggregates(api):
    """PRD §3.1: "A new cycle is created in `DRAFT` with `scenario_weight_total_bps` at 0, `reopen_count` at 0, and every certified aggregate (`certified_total_cents`, `certified_one_time_cents`, `certified_recurring_total_cents`, `certified_at`, `shortfall_gap_cents`, `shortfall_pct_bps`, `ratified_round_id`) null."

    PRD §3.1: "a `BASELINE` cycle must leave `supersedes_cycle_id` null."

    Design: Corner/entities/forecast_cycle_retrieval_returns_stored_row
    """
    created = get_success_data(
        api.create_forecast_cycle(F.cycle_payload(), U.make_director_headers())
    )

    cycle = validate_success(
        api.get_forecast_cycle(created["id"], U.make_director_headers()), 200
    )

    assert cycle["fiscal_year"] == C.FISCAL_YEAR
    assert cycle["cycle_type"] == "BASELINE"
    assert cycle["reconciliation_policy"] == "MIDPOINT_AVERAGE"
    assert cycle["enacted_appropriation_cents"] == C.ENACTED_APPROPRIATION_CENTS
    assert cycle["prior_recurring_baseline_cents"] == C.PRIOR_RECURRING_BASELINE_CENTS
    A.assert_cycle_status(cycle, "DRAFT")
    assert cycle["scenario_weight_total_bps"] == 0
    assert cycle["reopen_count"] == 0
    A.assert_version(cycle, 1)
    assert cycle["supersedes_cycle_id"] is None
    assert cycle["ratified_round_id"] is None
    assert cycle["certified_total_cents"] is None
    assert cycle["certified_one_time_cents"] is None
    assert cycle["certified_recurring_total_cents"] is None
    assert cycle["certified_at"] is None
    assert cycle["shortfall_gap_cents"] is None
    assert cycle["shortfall_pct_bps"] is None


def test_forecast_cycle_listing_paginates_with_stable_total_count(api):
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not be lower than 1, and may not exceed 100."

    PRD §2.3: "`offset` is the number of rows to skip and defaults to 0."

    PRD §2.3: "Both appear in the `meta` block of the response together with `total_count` and `has_more`."

    PRD §2.3: "Unless a specific endpoint says otherwise, every list is ordered by `created_at` ascending."

    Design: Corner/entities/forecast_cycle_listing_paginates_with_total_count
    """
    cycle_27 = fx.create_cycle(api, fiscal_year=2027)
    cycle_28 = fx.create_cycle(
        api,
        fiscal_year=2028,
        enacted_appropriation_cents=1_700_000_000,
        prior_recurring_baseline_cents=1_600_000_000,
    )
    cycle_29 = fx.create_cycle(
        api,
        fiscal_year=2029,
        reconciliation_policy="LOWER_OF_TWO",
        enacted_appropriation_cents=1_750_000_000,
        prior_recurring_baseline_cents=1_650_000_000,
    )
    analyst = U.make_rating_analyst_headers()

    first_page, first_meta = validate_paginated(
        api.list_forecast_cycles(analyst, params={"limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_forecast_cycles(analyst, params={"limit": 2, "offset": 2})
    )

    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    first_ids = [row["id"] for row in first_page]
    second_ids = [row["id"] for row in second_page]
    assert set(first_ids).isdisjoint(second_ids)
    assert set(first_ids + second_ids) == {cycle_27["id"], cycle_28["id"], cycle_29["id"]}

    filtered, filtered_meta = validate_paginated(
        api.list_forecast_cycles(analyst, params={"fiscal_year": 2029})
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == cycle_29["id"]
    assert filtered[0]["reconciliation_policy"] == "LOWER_OF_TWO"


def test_revenue_source_unknown_id_returns_source_not_found(api):
    """PRD §2.9: "The 404 code always identifies the resource type of the segment that failed: `ERR_CYCLE_NOT_FOUND` for a forecast cycle, `ERR_SCENARIO_NOT_FOUND` for an economic scenario, `ERR_SOURCE_NOT_FOUND` for a revenue source, `ERR_ADJUSTMENT_NOT_FOUND` for a policy change adjustment, `ERR_ONE_TIME_ITEM_NOT_FOUND` for a one-time item, `ERR_ROUND_NOT_FOUND` for a negotiation round, `ERR_ESTIMATE_NOT_FOUND` for a source estimate, `ERR_DISAGREEMENT_NOT_FOUND` for a disagreement record, `ERR_FUND_NOT_FOUND` for a reserve fund, `ERR_TRANSACTION_NOT_FOUND` for a ledger row, `ERR_REQUEST_NOT_FOUND` for a withdrawal request, `ERR_VOTE_NOT_FOUND` for a ballot, `ERR_ACTUAL_NOT_FOUND` for a posted actual collection, and `ERR_BRIEFING_NOT_FOUND` for a rating-agency briefing."

    Design: Corner/entities/revenue_source_not_found_returns_404
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    response = api.get_revenue_source(NON_EXISTENT_UUID, U.make_director_headers())

    validate_error(response, ApiErrorId.SOURCE_NOT_FOUND.value)


def test_revenue_source_missing_base_year_receipts_returns_validation_error(api):
    """PRD §2.9: "**Request shape** — `ERR_VALIDATION` (HTTP 422) when a required field is missing, an enum value is outside its declared set, a `_cents`, `_bps` or count value is not an integer, a money or basis-point value is negative where negatives are not allowed (only `judgmental_adjustment_cents` and a ledger row's `signed_amount_cents` may be negative), a date is not a well-formed ISO date, or a `rationale`, `narrative` or `memo` falls outside its length bounds."

    PRD §3.2: "Only a `ForecastDirector` may register one, supplying a display `name` such as "Personal Income Tax", a `tax_type` drawn from `PIT`, `CIT`, `SALES`, `CAPITAL_GAINS`, `EXCISE` or `OTHER`, the prior fiscal year's actual receipts as `base_year_receipts_cents` (strictly greater than zero, and the multiplicand of every scenario-weighted estimate), four elasticities, and a `volatility_class` of `LOW`, `MEDIUM` or `HIGH`."

    Design: Corner/entities/revenue_source_missing_required_field_returns_validation_error
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    response = api.create_revenue_source(
        F.pit_source_payload(base_year_receipts_cents=F.OMIT), U.make_director_headers()
    )

    validate_error(response, ApiErrorId.VALIDATION.value)
    _, meta = validate_paginated(api.list_revenue_sources(U.make_director_headers()))
    assert meta["total_count"] == 0


def test_reserve_fund_creation_applies_declared_defaults(api):
    """PRD §3.7: "At creation, `balance_cents` and `fy_opening_balance_cents` both equal `opening_balance_cents`, `fy_withdrawn_cents` is 0, `deposit_posture` is `ACCEPTING`, and the adequacy figures stay at their initial values — `cap_cents` and `required_reserve_cents` null, `volatility_index_bps` 0, `target_pct_bps` and `disclosed_target_pct_bps` 500, `coverage_ratio_bps` 0, `cushion_credit_bps` 0 and `adequacy_band` `INSUFFICIENT` — until a cycle is certified or adequacy is recomputed."

    PRD §3.7: "`cooling_off_until` is the `created_at` of the most recent non-reversed `WITHDRAWAL` row plus `cooling_off_days`, and is null when no such row exists"

    Design: Corner/entities/reserve_fund_defaults_applied_on_create
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    fund = validate_success(
        api.create_reserve_fund(F.fund_payload(), U.make_director_headers()), 201
    )

    assert fund["balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert fund["fy_opening_balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert fund["fy_withdrawn_cents"] == 0
    assert fund["deposit_posture"] == "ACCEPTING"
    A.assert_adequacy_disclosure(
        fund,
        volatility_index_bps=0,
        target_pct_bps=500,
        coverage_ratio_bps=0,
        adequacy_band="INSUFFICIENT",
        cushion_credit_bps=0,
        disclosed_target_pct_bps=500,
    )
    assert fund["cap_cents"] is None
    assert fund["required_reserve_cents"] is None
    assert fund["cooling_off_until"] is None
    A.assert_version(fund, 1)


def test_one_time_item_created_active_with_null_voided_at(api):
    """PRD §3.3: "A recorded item starts with `status` `ACTIVE`, and `voided_at` null."

    PRD §2.9: "**Request shape** — `ERR_VALIDATION` (HTTP 422) when a required field is missing, an enum value is outside its declared set, a `_cents`, `_bps` or count value is not an integer, a money or basis-point value is negative where negatives are not allowed (only `judgmental_adjustment_cents` and a ledger row's `signed_amount_cents` may be negative), a date is not a well-formed ISO date, or a `rationale`, `narrative` or `memo` falls outside its length bounds."

    Design: Corner/entities/one_time_item_system_status_input_ignored
    """
    source = fx.create_pit_source(api)
    cycle = fx.create_cycle(api)

    payload = F.one_time_item_payload(
        cycle["id"],
        source["id"],
        item_type="TAX_AMNESTY",
        amount_cents=5_000_000,
        description="Amnesty programme receipts, one collection window",
        status="VOIDED",
        voided_at=C.DEFAULT_CLOCK,
    )
    item = validate_success(
        api.create_one_time_item(payload, U.make_exec_economist_headers()), 201
    )

    assert item["status"] == "ACTIVE"
    assert item["voided_at"] is None
    assert item["amount_cents"] == 5_000_000
    assert item["item_type"] == "TAX_AMNESTY"
    A.assert_version(item, 1)

    _, meta = validate_paginated(
        api.list_one_time_items(U.make_director_headers(), params={"status": "VOIDED"})
    )
    assert meta["total_count"] == 0


def test_economic_scenario_negative_weight_returns_validation_error(api):
    """PRD §3.1: "Its `weight_bps` is the probability weight assigned to the scenario, at least 0 and at most 10000."

    PRD §2.9: "**Request shape** — `ERR_VALIDATION` (HTTP 422) when a required field is missing, an enum value is outside its declared set, a `_cents`, `_bps` or count value is not an integer, a money or basis-point value is negative where negatives are not allowed (only `judgmental_adjustment_cents` and a ledger row's `signed_amount_cents` may be negative), a date is not a well-formed ISO date, or a `rationale`, `narrative` or `memo` falls outside its length bounds."

    Design: Corner/entities/economic_scenario_invalid_weight_rejected
    """
    cycle = fx.create_cycle(api)

    response = api.create_scenario(
        cycle["id"], F.scenario_payload(weight_bps=-100), U.make_director_headers()
    )

    validate_error(response, ApiErrorId.VALIDATION.value)
    stored = fx.read_cycle(api, cycle["id"])
    assert stored["scenario_weight_total_bps"] == 0
    A.assert_version(stored, 1)
    _, meta = validate_paginated(
        api.list_cycle_scenarios(cycle["id"], U.make_director_headers())
    )
    assert meta["total_count"] == 0


def test_reserve_transaction_carries_no_version_and_no_updated_at(api):
    """PRD §2.6: "Two entities are exceptions and carry only `id` and `created_at`: the **reserve ledger row** (`ReserveTransaction`) and the **ballot** (`WithdrawalVote`)."

    PRD §2.6: "Both are immutable audit records; neither has an `updated_at` field and neither has a `version` field."

    PRD §3.7: "The posting mints a ledger row with `origin` `MANUAL_DEPOSIT`, `signed_amount_cents` equal to the positive `amount_cents`, `gross_computed_cents` equal to the same amount and `overflow_returned_cents` 0; the fund's `balance_cents` rises by that amount, `last_transaction_at` becomes the row's `created_at`, the adequacy disclosure is re-derived, `deposit_posture` may flip `ACCEPTING → AT_CAP`, every `PUBLISHED` briefing of the fund goes `STALE` with `stale_reason` `RESERVE_BALANCE_CHANGED`, and the fund's `version` increments by one."

    Design: Corner/entities/reserve_transaction_is_immutable_and_has_no_version
    """
    fund = fx.create_fund(api)
    posted = fx.deposit(api, fund["id"], 10_000_000)

    row = validate_success(
        api.get_reserve_transaction(posted["id"], U.make_treasurer_headers()), 200
    )

    A.assert_audit_record_shape(row)
    A.assert_transaction_row(
        row,
        origin="MANUAL_DEPOSIT",
        signed_amount_cents=10_000_000,
        gross_computed_cents=10_000_000,
        overflow_returned_cents=0,
    )
    assert fx.read_fund(api, fund["id"])["balance_cents"] == 60_000_000


def test_scenario_creation_on_unknown_cycle_returns_cycle_not_found(api):
    """PRD §2.9: "Nested paths are resolved strictly left to right."

    PRD §2.9: "For a request against `/forecast-cycles/{id}/consensus-rounds`, the cycle is looked up first; if it does not exist the response is `ERR_CYCLE_NOT_FOUND` (HTTP 404) and the server never considers the rest of the request."

    Design: Corner/entities/economic_scenario_requires_existing_parent_cycle_not_found
    """
    cycle = fx.create_cycle(api)

    response = api.create_scenario(
        NON_EXISTENT_UUID,
        F.scenario_payload(weight_bps=10000),
        U.make_director_headers(),
    )

    validate_error(response, ApiErrorId.CYCLE_NOT_FOUND.value)
    assert fx.read_cycle(api, cycle["id"])["scenario_weight_total_bps"] == 0


def test_withdrawal_draft_with_unknown_fund_id_returns_fund_not_found(api):
    """PRD §2.9: "The same codes are reused when a foreign key supplied **in a request body** — `cycle_id`, `source_id`, `round_id`, `fund_id`, or a referenced ledger row — names a row that does not exist."

    PRD §3.8: "Creating a draft also **rejects any other request on the same fund that is still in `DRAFT`**, moving each to `REJECTED` with `authorized_amount_cents` 0 and `approval_basis` left null and incrementing each one's `version` by one, and it increments the fund's own `version` by one even though no money has moved — which is exactly why the next drafter's pin must be fresh."

    Design: Corner/entities/withdrawal_request_rejects_unknown_fund_fk_not_found
    """
    cycle = fx.create_cycle(api)
    fund = fx.create_fund(api)

    payload = F.withdrawal_request_payload(
        NON_EXISTENT_UUID,
        cycle["id"],
        fund["version"],
        requested_amount_cents=1_000_000,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date="2026-12-31",
    )
    response = api.create_withdrawal_request(payload, U.make_treasurer_headers())

    validate_error(response, ApiErrorId.FUND_NOT_FOUND.value)
    A.assert_version(fx.read_fund(api, fund["id"]), 1)
    _, meta = validate_paginated(
        api.list_withdrawal_requests(
            U.make_director_headers(), params={"fund_id": fund["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_source_estimate_filing_stores_derived_money_and_role_derived_body(api):
    """PRD §3.4: "Only an `ExecutiveEconomist` or a `LegislativeEconomist` may file, and the `body` field is derived from the caller's role rather than supplied: `ExecutiveEconomist` produces `EXECUTIVE`, `LegislativeEconomist` produces `LEGISLATIVE`."

    PRD §3.4: "Then multiply each scenario's amount by that scenario's `weight_bps`, sum the products across all scenarios, divide by 10000, and round half up exactly once."

    PRD §3.4: "A newly filed estimate has `locked` false."

    Design: Corner/entities/source_estimate_computed_money_fields_input_ignored
    """
    ctx = fx.short_chain(api, stop_at="round")

    payload = F.estimate_payload(
        ctx["round_id"],
        ctx["pit_source_id"],
        judgmental_adjustment_cents=F.OMIT,
        estimate_amount_cents=999_999_999,
        weighted_scenario_cents=1,
        policy_adjustment_cents=500,
        one_time_cents=700,
        recurring_component_cents=900,
        body="EXECUTIVE",
        locked=True,
    )
    estimate = validate_success(
        api.create_source_estimate(payload, U.make_leg_economist_headers()), 201
    )

    A.assert_estimate_components(
        estimate,
        weighted_scenario_cents=C.PIT_WEIGHTED_SCENARIO_CENTS,
        policy_adjustment_cents=0,
        judgmental_adjustment_cents=0,
        one_time_cents=0,
    )
    assert estimate["estimate_amount_cents"] == C.SHORT_ESTIMATE_CENTS
    assert estimate["body"] == "LEGISLATIVE"
    assert estimate["submitted_by_user_id"] == U.LEG_ECONOMIST_USER_ID
    assert estimate["locked"] is False


# =========================================================================== #
# State machines
# =========================================================================== #
def test_new_forecast_cycle_status_is_draft(api):
    """PRD §3.1: "The **forecast cycle** is the organising unit of the whole system: one cycle is one forecast of one state fiscal year, and it moves through `DRAFT`, `INPUTS_LOCKED`, `IN_CONSENSUS`, `CONSENSUS_REACHED`, `CERTIFIED` and finally `SUPERSEDED`, which is terminal."

    PRD §3.1: "A new cycle is created in `DRAFT` with `scenario_weight_total_bps` at 0, `reopen_count` at 0, and every certified aggregate (`certified_total_cents`, `certified_one_time_cents`, `certified_recurring_total_cents`, `certified_at`, `shortfall_gap_cents`, `shortfall_pct_bps`, `ratified_round_id`) null."

    Design: Corner/state_machines/forecast_cycle_initial_state_is_draft
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    cycle = validate_success(
        api.create_forecast_cycle(F.cycle_payload(), U.make_director_headers()), 201
    )

    A.assert_cycle_status(cycle, "DRAFT")
    assert cycle["reopen_count"] == 0
    assert cycle["ratified_round_id"] is None

    rows, meta = validate_paginated(
        api.list_forecast_cycles(U.make_director_headers(), params={"status": "DRAFT"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == cycle["id"]


def test_lock_inputs_with_weights_below_ten_thousand_is_rejected(api):
    """PRD §3.1: "A cycle whose scenario weights total anything other than 10000, or that has no scenarios at all, is rejected with `ERR_SCENARIO_WEIGHTS_INVALID` (HTTP 422)."

    PRD §3.1: "Every scenario creation, re-weighting or deletion rewrites the cycle's `scenario_weight_total_bps` to the sum of the weights of the cycle's scenarios and increments the cycle's `version` by one; a re-weighting also increments the scenario's own `version`."

    Design: Corner/state_machines/lock_inputs_with_weights_below_total_rejected
    """
    fx.create_pit_source(api)
    cycle = fx.create_cycle(api)
    fx.add_scenario(api, cycle["id"], **C.SCENARIO_BASELINE)
    fx.add_scenario(
        api,
        cycle["id"],
        label="OPTIMISTIC",
        weight_bps=3000,
        employment_growth_bps=300,
        wage_income_bps=700,
        retail_sales_bps=600,
        asset_market_return_bps=1500,
    )

    response = api.lock_inputs(cycle["id"], U.make_director_headers())

    validate_error(response, ApiErrorId.SCENARIO_WEIGHTS_INVALID.value)
    stored = fx.read_cycle(api, cycle["id"])
    A.assert_cycle_status(stored, "DRAFT")
    assert stored["scenario_weight_total_bps"] == 9000
    _, meta = validate_paginated(
        api.list_cycle_scenarios(cycle["id"], U.make_director_headers())
    )
    assert meta["total_count"] == 2


def test_scenario_patch_after_lock_inputs_returns_cycle_not_in_draft(api):
    """PRD §3.1: "Once the cycle is `INPUTS_LOCKED`, its scenarios are immutable: any further attempt to add, re-weight or delete one comes back as `ERR_CYCLE_NOT_IN_DRAFT`."

    PRD §3.1: "When the scenario set is complete the director locks it, moving the cycle `DRAFT → INPUTS_LOCKED`."

    Design: Corner/state_machines/lock_inputs_side_effect_freezes_scenarios
    """
    ctx = fx.short_chain(api, stop_at="locked")
    baseline_scenario = ctx["scenarios"][0]

    response = api.update_scenario(
        baseline_scenario["id"], {"weight_bps": 5000}, U.make_exec_economist_headers()
    )

    validate_error(response, ApiErrorId.CYCLE_NOT_IN_DRAFT.value)
    stored_scenario = validate_success(
        api.get_scenario(baseline_scenario["id"], U.make_director_headers()), 200
    )
    assert stored_scenario["weight_bps"] == C.SCENARIO_BASELINE["weight_bps"]
    A.assert_version(stored_scenario, 1)
    stored_cycle = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(stored_cycle, "INPUTS_LOCKED")
    assert stored_cycle["scenario_weight_total_bps"] == C.SCENARIO_WEIGHT_TOTAL_BPS


def test_certify_on_draft_cycle_returns_cycle_not_consensus_reached(api):
    """PRD §3.6: "Only a `ForecastDirector` may certify, only from `CONSENSUS_REACHED` — any other status is rejected with `ERR_CYCLE_NOT_CONSENSUS_REACHED` (HTTP 409) — and only when `ratified_round_id` is not null."

    Design: Corner/state_machines/certify_from_draft_cycle_rejected
    """
    cycle = fx.create_cycle(api)

    response = api.certify_cycle(cycle["id"], U.make_director_headers())

    validate_error(response, ApiErrorId.CYCLE_NOT_CONSENSUS_REACHED.value)
    stored = fx.read_cycle(api, cycle["id"])
    A.assert_cycle_status(stored, "DRAFT")
    assert stored["certified_total_cents"] is None
    assert stored["certified_at"] is None
    assert stored["shortfall_pct_bps"] is None


def test_second_lock_inputs_call_returns_cycle_not_in_draft(api):
    """PRD §3.1: "Locking requires the cycle to be in `DRAFT` (otherwise `ERR_CYCLE_NOT_IN_DRAFT`), requires at least one scenario to exist on the cycle, requires `scenario_weight_total_bps` to equal exactly 10000 — the probabilities must sum to precisely one — and requires at least one revenue source with `status` `ACTIVE` to exist in the system."

    PRD §3.1: "Locking increments the cycle's `version` by one."

    Design: Corner/state_machines/lock_inputs_twice_second_attempt_rejected
    """
    ctx = fx.short_chain(api, stop_at="locked")
    version_after_first_lock = ctx["cycle"]["version"]

    response = api.lock_inputs(ctx["cycle_id"], U.make_director_headers())

    validate_error(response, ApiErrorId.CYCLE_NOT_IN_DRAFT.value)
    stored = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(stored, "INPUTS_LOCKED")
    A.assert_version(stored, version_after_first_lock)


def test_retracted_briefing_rejects_second_retract_and_publish(api):
    """PRD §3.9: "`RETRACTED` is terminal: nothing further may be done with the briefing, and any attempt is met with `ERR_BRIEFING_TERMINAL`."

    PRD §3.9: "The briefing must be in `DRAFT` or `STALE`; anything else, including a briefing already `PUBLISHED`, is rejected with `ERR_BRIEFING_NOT_PUBLISHABLE` (HTTP 409), and the separate rule that no transition may be attempted on a `RETRACTED` briefing — `ERR_BRIEFING_TERMINAL` (HTTP 409) — ranks immediately below it."

    Design: Corner/state_machines/retracted_briefing_rejects_second_retract
    """
    cycle = fx.create_cycle(api)
    fund = fx.create_fund(api)
    briefing = fx.draft_briefing(api, fund["id"], cycle["id"])
    retracted = get_success_data(
        api.retract_briefing(briefing["id"], U.make_director_headers())
    )
    version_after_retract = retracted["version"]

    second_retract = api.retract_briefing(briefing["id"], U.make_director_headers())
    publish_attempt = api.publish_briefing(briefing["id"], U.make_director_headers())

    validate_error(second_retract, ApiErrorId.BRIEFING_TERMINAL.value)
    validate_error(publish_attempt, ApiErrorId.BRIEFING_NOT_PUBLISHABLE.value)
    stored = fx.read_briefing(api, briefing["id"])
    assert stored["status"] == "RETRACTED"
    assert stored["published_at"] is None
    A.assert_version(stored, version_after_retract)


def test_cycle_reopen_returns_to_draft_and_supersedes_open_round(api):
    """PRD §3.1: "A cycle in `IN_CONSENSUS` can be sent back to `DRAFT` by the director so the economists can re-weight the scenarios — the revision loop of the negotiation."

    PRD §3.1: "Reopening carries a wide cascade: every round of the cycle whose `status` is `OPEN`, `COMPARED` or `DISPUTED` becomes `SUPERSEDED`, every `OPEN` disagreement record of those rounds becomes `VOIDED`, `reopen_count` is increased by one, `ratified_round_id` is set back to null, the cycle's scenarios become mutable again, and the cycle's `version` increments by one."

    PRD §3.4: "The server assigns `round_number` as one more than the count of rounds already on the cycle, so the first round of a cycle is round 1, and creates the round with `status` `OPEN`, `exec_submission_status` and `leg_submission_status` both `PENDING`, and `open_disagreement_count` 0."

    Design: Corner/state_machines/cycle_reopen_returns_to_draft_and_supersedes_round
    """
    ctx = fx.short_chain(api, stop_at="round")

    reopened = validate_success(
        api.reopen_cycle(ctx["cycle_id"], U.make_director_headers()), 200
    )

    A.assert_cycle_status(reopened, "DRAFT")
    assert reopened["reopen_count"] == 1
    assert reopened["ratified_round_id"] is None
    assert reopened["scenario_weight_total_bps"] == C.SCENARIO_WEIGHT_TOTAL_BPS

    stored_round = fx.read_round(api, ctx["round_id"])
    assert stored_round["status"] == "SUPERSEDED"
    assert stored_round["round_number"] == 1

    rows, meta = validate_paginated(
        api.list_consensus_rounds(
            U.make_director_headers(),
            params={"cycle_id": ctx["cycle_id"], "status": "SUPERSEDED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["round_id"]


def test_submission_dimensions_move_independently_before_comparison(api):
    """PRD §3.4: "These two dimensions live on the same round row, evolve independently, may reach `SUBMITTED` in either order, and neither constrains the other."

    PRD §3.4: "A successful submission writes the acting body's total — `exec_total_cents` as the sum of `estimate_amount_cents` over the round's `EXECUTIVE` estimates, or `leg_total_cents` as the same sum over its `LEGISLATIVE` estimates, each null until its own dimension is `SUBMITTED` — and increments the round's `version` by one."

    PRD §3.4: "When the *second* of the two dimensions reaches `SUBMITTED`, the server compares the two submissions."

    Design: Corner/state_machines/exec_and_leg_submission_dimensions_move_independently
    """
    ctx = fx.short_chain(api, stop_at="filed")

    after_exec = fx.submit_body(api, ctx["round_id"], "EXECUTIVE")
    after_leg = fx.submit_body(api, ctx["round_id"], "LEGISLATIVE")

    A.assert_submission_dimensions(after_exec, exec_status="SUBMITTED", leg_status="PENDING")
    assert after_exec["status"] == "OPEN"
    assert after_exec["exec_total_cents"] == C.SHORT_EXEC_TOTAL_CENTS
    assert after_exec["leg_total_cents"] is None

    A.assert_submission_dimensions(after_leg, exec_status="SUBMITTED", leg_status="SUBMITTED")
    A.assert_round_comparison(
        after_leg,
        status="COMPARED",
        exec_total_cents=C.SHORT_EXEC_TOTAL_CENTS,
        leg_total_cents=C.SHORT_LEG_TOTAL_CENTS,
        variance_bps=C.SHORT_VARIANCE_BPS,
        reconciled_total_cents=C.SHORT_RECONCILED_TOTAL_CENTS,
        open_disagreement_count=0,
    )
    _, meta = validate_paginated(
        api.list_disagreement_records(
            U.make_director_headers(), params={"round_id": ctx["round_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_ratify_bubbles_cycle_to_consensus_reached_and_locks_estimates(api):
    """PRD §3.5: "Ratifying stamps `ratified_at` with the logical clock, sets `locked` to true on every source estimate of the round, and increments the round's `version` by one."

    PRD §3.5: "It also bubbles up: the owning cycle moves `IN_CONSENSUS → CONSENSUS_REACHED`, records the ratified round's id in `ratified_round_id`, and increments its own `version` by one."

    Design: Corner/state_machines/ratify_bubbles_cycle_to_consensus_reached_and_locks_estimates
    """
    ctx = fx.short_chain(api, stop_at="compared")

    ratified_round = validate_success(
        api.ratify_round(ctx["round_id"], U.make_director_headers()), 200
    )

    assert ratified_round["status"] == "RATIFIED"
    assert is_iso8601_timestamp(ratified_round["ratified_at"])

    stored_cycle = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(stored_cycle, "CONSENSUS_REACHED")
    assert stored_cycle["ratified_round_id"] == ctx["round_id"]

    stored_estimate = validate_success(
        api.get_source_estimate(ctx["exec_estimate"]["id"], U.make_director_headers()), 200
    )
    assert stored_estimate["locked"] is True
    assert stored_estimate["estimate_amount_cents"] == C.SHORT_ESTIMATE_CENTS


def test_stale_briefing_republished_only_with_refresh_snapshot(api):
    """PRD §3.9: "Last comes the snapshot check: `snapshot_fund_version` must still equal the fund's live `version` unless the request sets the optional `refresh_snapshot` flag to true, and a behind-the-fund snapshot published without that flag is rejected with `ERR_ADEQUACY_STALE` (HTTP 409)."

    PRD §3.9: "When `refresh_snapshot` is true, all three snapshot fields — `snapshot_fund_version`, `snapshot_adequacy_band` and `snapshot_coverage_ratio_bps` — are re-read from the live fund *before* publication, so the published briefing always describes a state that existed."

    PRD §3.9: "Publication then sets `published_at` to the logical clock, clears `stale_reason` back to null, and increments the briefing's `version` by one."

    PRD §2.8: "Any change to a fund's `balance_cents` re-derives the whole adequacy disclosure (§3.7), re-evaluates `deposit_posture`, refreshes `last_transaction_at`, increments the fund's `version`, and marks every `PUBLISHED` briefing of that fund `STALE` with `stale_reason` `RESERVE_BALANCE_CHANGED`."

    Design: Corner/state_machines/stale_briefing_republished_only_with_refresh_snapshot
    """
    ctx = fx.short_chain(api, stop_at="certified", fund_overrides={})
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])
    A.assert_briefing_snapshot(
        briefing, fund_version=2, adequacy_band="ADEQUATE", coverage_ratio_bps=7713
    )
    fx.publish_briefing(api, briefing["id"])
    fx.deposit(api, ctx["fund_id"], 10_000_000)
    A.assert_briefing_stale(
        fx.read_briefing(api, briefing["id"]), stale_reason="RESERVE_BALANCE_CHANGED"
    )
    fx.set_clock(api, "2026-08-03T00:00:00Z")

    without_flag = api.publish_briefing(briefing["id"], U.make_director_headers())
    validate_error(without_flag, ApiErrorId.ADEQUACY_STALE.value)

    republished = validate_success(
        api.publish_briefing(
            briefing["id"], U.make_director_headers(), F.publish_payload(True)
        ),
        200,
    )

    assert republished["status"] == "PUBLISHED"
    assert republished["stale_reason"] is None
    A.assert_briefing_snapshot(
        republished, fund_version=3, adequacy_band="ADEQUATE", coverage_ratio_bps=9255
    )
    assert is_iso8601_timestamp(republished["published_at"])
    assert republished["published_at"].startswith("2026-08-03T00:00:00")

    stored_fund = fx.read_fund(api, ctx["fund_id"])
    assert stored_fund["balance_cents"] == 60_000_000
    assert stored_fund["coverage_ratio_bps"] == 9255
    A.assert_version(stored_fund, 3)
