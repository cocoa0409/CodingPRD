"""Stop-loss quoting for level-funded business: pricing and lifecycle."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    create_broker,
    create_case_in_rating,
    add_modeled_plan,
    create_draft_quote,
    add_stop_loss_quote,
    setup_level_funded_case_with_quote,
    setup_level_funded_quote_with_stop_loss,
    setup_case_with_proposed_quote,
    make_broker_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestStopLossPricing:
    def test_stop_loss_tiered_premium_computation(self):
        """PRD section 3.7: "Expected annual claims,
        `expected_annual_claims_cents`, project the case's experience rate
        across the year: `experience_rate_cents` times 12 times the census
        `enrolled_employees` times 0.82, the claims-fund share of the
        level-funded dollar; when no experience rate exists the manual rate
        stands in."
        PRD section 3.7: "The aggregate attachment,
        `aggregate_attachment_cents`, is expected annual claims multiplied by
        `aggregate_attachment_pct`, rounded half-up to whole cents."
        PRD section 3.7: "The specific premium is tiered by the specific
        deductible: at or below 2,500,000 cents ($25,000) the rate is 850 per
        thousand per hundred enrollees; above that and at or below 5,000,000
        cents it is 620; above that and at or below 10,000,000 cents it is 410;
        above 10,000,000 cents it is 280."
        PRD section 3.7: "The aggregate premium, `aggregate_premium_cents`, is
        a flat 2 percent of the aggregate attachment, rounded half-up to whole
        cents."
        PRD section 3.7: "The `total_stop_loss_premium_cents` is the sum of the
        two."

        Design: Corner/calculations/stop_loss_tiered_premium_computation
        """
        broker, case, plan, quote = setup_level_funded_case_with_quote()
        slq = add_stop_loss_quote(quote["id"])
        data = validate_success(api_client.quote_stop_loss(slq["id"], UW))
        assert data["status"] == "QUOTED"
        assert data["expected_annual_claims_cents"] == 21010368
        assert data["aggregate_attachment_cents"] == 26262960
        assert data["specific_premium_cents"] == 12400000
        assert data["aggregate_premium_cents"] == 525259
        assert data["total_stop_loss_premium_cents"] == 12925259

    def test_stop_loss_laser_loads_specific_premium(self):
        """PRD section 3.7: "When `laser_claimant_ids` is non-empty, the specific
        premium is loaded an additional 25 percent — multiplied by 1.25 and
        re-rounded to whole cents — and the total recomputed as the loaded
        specific premium plus the aggregate premium."

        Design: Corner/calculations/stop_loss_laser_loads_specific_premium
        """
        broker, case, plan, quote = setup_level_funded_case_with_quote()
        slq = add_stop_loss_quote(
            quote["id"],
            laser_claimant_ids=["CLM-001"],
            laser_deductible_cents=10000000,
        )
        data = validate_success(api_client.quote_stop_loss(slq["id"], UW))
        assert data["specific_premium_cents"] == 15500000
        assert data["aggregate_premium_cents"] == 525259
        assert data["total_stop_loss_premium_cents"] == 16025259


class TestStopLossGates:
    def test_stop_loss_quote_requires_active_parent_quote(self):
        """PRD section 3.7: "Pricing the stop-loss requires the record to be
        `DRAFT` (else `ERR_STOP_LOSS_NOT_DRAFT`), the parent quote to be live in
        `PROPOSED` or `COUNTERED` (else `ERR_QUOTE_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/stop_loss_quote_requires_active_parent_quote
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"], funding_type="LEVEL_FUNDED")
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"],
                                   funding_type="LEVEL_FUNDED")
        slq = add_stop_loss_quote(quote["id"])
        # Parent quote still DRAFT -> not active.
        resp = api_client.quote_stop_loss(slq["id"], UW)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACTIVE)
        # Once proposed, the same action succeeds and computes premiums.
        validate_success(api_client.propose_quote(quote["id"], UW))
        data = validate_success(api_client.quote_stop_loss(slq["id"], UW))
        assert data["status"] == "QUOTED"
        assert data["total_stop_loss_premium_cents"] == 12925259

    def test_stop_loss_quote_rejected_while_parent_draft(self):
        """PRD section 3.7: "the parent quote to be live in `PROPOSED` or
        `COUNTERED` (else `ERR_QUOTE_NOT_ACTIVE`)" — a DRAFT parent quote is in
        neither state.

        Design: Difficulty/cross_entity_state_dependency/stop_loss_quote_requires_active_parent_quote
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"], funding_type="LEVEL_FUNDED")
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"],
                                   funding_type="LEVEL_FUNDED")
        slq = add_stop_loss_quote(quote["id"])
        resp = api_client.quote_stop_loss(slq["id"], UW)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACTIVE)
        slq = get_success_data(api_client.get_stop_loss_quote(slq["id"], UW))
        assert slq["status"] == "DRAFT"

    def test_stop_loss_on_fully_insured_quote_fails(self):
        """PRD section 3.7: "the parent quote's funding type to be `LEVEL_FUNDED`
        (else `ERR_NOT_LEVEL_FUNDED`)".

        Design: Corner/validations/stop_loss_on_fully_insured_quote_fails
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        slq = add_stop_loss_quote(quote["id"])
        resp = api_client.quote_stop_loss(slq["id"], UW)
        validate_error(resp, ApiErrorId.ERR_NOT_LEVEL_FUNDED)
        slq = get_success_data(api_client.get_stop_loss_quote(slq["id"], UW))
        assert slq["status"] == "DRAFT"

    def test_quote_stop_loss_twice_fails(self):
        """PRD section 3.7: "Pricing the stop-loss requires the record to be
        `DRAFT` (else `ERR_STOP_LOSS_NOT_DRAFT`)".

        Design: Corner/validations/quote_stop_loss_twice_fails
        """
        broker, case, plan, quote, slq = setup_level_funded_quote_with_stop_loss()
        assert slq["status"] == "QUOTED"
        resp = api_client.quote_stop_loss(slq["id"], UW)
        validate_error(resp, ApiErrorId.ERR_STOP_LOSS_NOT_DRAFT)
        slq = get_success_data(api_client.get_stop_loss_quote(slq["id"], UW))
        assert slq["status"] == "QUOTED"


class TestStopLossBinding:
    def test_bind_draft_stop_loss_fails(self):
        """PRD section 3.7: "Binding is the final stop-loss act: the record must
        be `QUOTED` (else `ERR_STOP_LOSS_NOT_QUOTED`)".

        Design: Corner/state_machines/bind_draft_stop_loss_fails
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"], funding_type="LEVEL_FUNDED")
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"],
                                   funding_type="LEVEL_FUNDED")
        slq = add_stop_loss_quote(quote["id"])
        resp = api_client.bind_stop_loss(slq["id"], UW)
        validate_error(resp, ApiErrorId.ERR_STOP_LOSS_NOT_QUOTED)
        slq = get_success_data(api_client.get_stop_loss_quote(slq["id"], UW))
        assert slq["status"] == "DRAFT"

    def test_bind_stop_loss_before_quote_accepted_fails(self):
        """PRD section 3.7: "the parent quote must have reached `ACCEPTED` (else
        `ERR_QUOTE_NOT_ACCEPTED`)".

        Design: Corner/validations/bind_stop_loss_before_quote_accepted_fails
        """
        broker, case, plan, quote, slq = setup_level_funded_quote_with_stop_loss()
        resp = api_client.bind_stop_loss(slq["id"], UW)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED)
        slq = get_success_data(api_client.get_stop_loss_quote(slq["id"], UW))
        assert slq["status"] == "QUOTED"

    def test_level_funded_stop_loss_bind_happy_path(self):
        """PRD section 3.7: "Binding is the final stop-loss act: the record must
        be `QUOTED` (else `ERR_STOP_LOSS_NOT_QUOTED`) and the parent quote must
        have reached `ACCEPTED` (else `ERR_QUOTE_NOT_ACCEPTED`), at which point
        the stop-loss becomes `BOUND`."

        Design: Corner/endpoints/level_funded_stop_loss_bind_happy_path
        """
        broker, case, plan, quote, slq = setup_level_funded_quote_with_stop_loss()
        broker_headers = make_broker_headers(broker["id"])
        quote = validate_success(api_client.accept_quote(quote["id"], broker_headers))
        assert quote["status"] == "ACCEPTED"
        data = validate_success(api_client.bind_stop_loss(slq["id"], UW))
        assert data["status"] == "BOUND"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "APPROVED"
