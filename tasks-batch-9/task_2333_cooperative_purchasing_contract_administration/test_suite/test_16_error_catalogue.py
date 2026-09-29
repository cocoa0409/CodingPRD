"""Error catalogue: every refusal family reached from a live fixture by one minimal deviation."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_INTAKE,
    ADMIN_PIGGYBACK,
    ADMIN_REVIEW,
    ADMIN_REVIEW_ID,
    ApiErrorId,
    OFFICER_AWARDER,
    OFFICER_AWARDER_ID,
    OFFICER_CONDUCTOR,
    OFFICER_CONDUCTOR_ID,
    assert_cents,
    assert_error_data_shape,
    assert_fee_ledger_balanced,
    assert_instant,
    assert_score,
    make_member_headers,
    make_supplier_headers,
)
from test_helpers.constants import (
    BASE_TERM_END,
    CLOCK_AFTER_RESPONSE_DUE,
    CLOCK_AUG_31,
    CLOCK_NOV_01,
    CLOCK_OCT_01,
    CLOCK_OCT_15,
    CLOCK_REGISTRY,
    OCT_PERIOD_END,
    OCT_PERIOD_START,
    SKU_DISPENSER,
    SKU_LINER,
)
from test_helpers.factories import (
    CART_LINE,
    TX_RULE,
    contract_usage_payload,
    line_item_payload,
    master_contract_payload,
    member_agency_payload,
    price_quote_params,
    renewal_amendment_payload,
    solicitation_payload,
    solicitation_response_payload,
    state_law_rule_payload,
    supplier_payload,
)
from test_helpers.fixtures import (
    accept_report,
    add_line_item,
    create_member,
    file_response,
    open_report,
    read_amendment,
    read_analysis,
    read_contract,
    read_line_item,
    read_member,
    read_report,
    read_response,
    read_solicitation,
    read_supplier,
    read_usage,
    reconcile_report,
    record_confirmed_usage,
    remit_fee,
    seed_state_law_rules,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    setup_awarded_solicitation,
    setup_confirmed_usage_world,
    setup_evaluated_solicitation,
    setup_posted_solicitation,
    submit_report,
)

PAST_DUE_AT = "2026-05-01T00:00:00Z"
TERM_END_55_MONTHS = "2031-04-01T00:00:00Z"
TERM_END_36_MONTHS = "2029-09-01T00:00:00Z"
RENEWAL_TO_67_MONTHS = "2032-04-01T00:00:00Z"
RENEWAL_TO_48_MONTHS = "2030-09-01T00:00:00Z"
RENEWAL_TO_60_MONTHS = "2031-09-01T00:00:00Z"
RENEWAL_TERM_END = "2028-09-01T00:00:00Z"
FEE_DUE_AT = "2026-10-31T00:00:00Z"
UNKNOWN_ROLE = "PROCUREMENT_ROBOT"
JUNIPER = "Juniper Sanitation LLC"


def _draft(api, **overrides):
    return validate_success(
        api.create_solicitation(solicitation_payload(**overrides), OFFICER_CONDUCTOR), 201
    )


def _lifecycle(api, solicitation_id, action, headers=OFFICER_CONDUCTOR):
    return api.solicitation_lifecycle(solicitation_id, {"action": action}, headers)


def _mark_responsive(api, response_id, technical_score):
    return validate_success(
        api.response_review(
            response_id,
            {"action": "MARK_RESPONSIVE", "technical_score": technical_score},
            OFFICER_CONDUCTOR,
        )
    )


def _file_again(api, solicitation_id, supplier_id):
    return api.create_solicitation_response(
        solicitation_response_payload(solicitation_id, supplier_id),
        make_supplier_headers(supplier_id),
    )


def _award_pending_world(api):
    """Two RESPONSIVE responses scored and recommended, the solicitation not yet awarded."""
    world = setup_evaluated_solicitation(api)
    world["response_a"] = _mark_responsive(api, world["response_a"]["id"], 88.00)
    world["response_b"] = _mark_responsive(api, world["response_b"]["id"], 95.00)
    world["solicitation"] = validate_success(
        _lifecycle(api, world["solicitation"]["id"], "RECOMMEND_AWARD")
    )
    return world


def _duplicate_world(api):
    """One ACTIVE contract, its awarded solicitation, two suppliers and one member row."""
    world = setup_active_contract(api)
    world["member"] = create_member(api)
    return world


def _line_item_world(api):
    """Two contracts on one awarded solicitation, only the first of them executed."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    second = validate_success(
        api.create_master_contract(
            master_contract_payload(
                world["solicitation"]["id"],
                world["supplier_a"]["id"],
                contract_number="COOP-MC-2026-002",
            ),
            OFFICER_AWARDER,
        ),
        201,
    )
    world["member"] = member
    world["analysis"] = analysis
    world["second"] = second
    world["second_line"] = add_line_item(api, second["id"], CART_LINE)
    world["line"] = world["lines"][SKU_DISPENSER]
    return world


def _quote(api, contract_id, line_item_id, member_id):
    return api.get_price_quote(
        contract_id,
        make_member_headers(member_id),
        price_quote_params(line_item_id, member_id),
    )


def _september_report_world(api):
    """Three confirmed September orders on the liner line under one DRAFT report."""
    world = setup_confirmed_usage_world(api)
    world["report"] = open_report(api, world)
    return world


def _submitted_september_world(api):
    world = _september_report_world(api)
    set_clock(api, CLOCK_OCT_01)
    world["report"] = submit_report(api, world, world["report"]["id"])
    return world


def _reconciled_september_world(api):
    """The September period settled at 541 cents and then audited down to 540."""
    world = _submitted_september_world(api)
    report_id = world["report"]["id"]
    accept_report(api, report_id)
    remit_fee(api, world, report_id, 541)
    world["report"] = reconcile_report(api, report_id)
    return world


def _authorised_world(api, **overrides):
    world = setup_active_contract(api, **overrides)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    world["line"] = world["lines"][SKU_DISPENSER]
    return world


def _propose_renewal(api, contract, requested_term_end):
    return api.create_contract_amendment(
        renewal_amendment_payload(contract["id"], contract["version"], requested_term_end),
        make_supplier_headers(contract["supplier_id"]),
    )


def _decide(api, amendment_id, action, note):
    return api.amendment_decision(
        amendment_id, {"action": action, "decision_note": note}, ADMIN_REVIEW
    )


class TestSolicitationLifecycleErrors:
    def test_01_posting_checks_the_state_law_row_and_the_response_deadline(self, api):
        """PRD §3.2: "It requires a configuration row for `lead_agency_state_code`, a
        `response_due_at` strictly after the logical clock (otherwise
        `ERR_RESPONSE_DUE_IN_PAST`), and weights that still sum to exactly 100." PRD §2.9: "The
        required state law configuration row exists — `ERR_STATE_LAW_RULE_NOT_FOUND`, 404, on
        `POST /coop/solicitations/{id}/lifecycle`, `POST /coop/suppliers/{id}/qualification`,
        `POST /coop/member-agencies/{id}/registration` and
        `POST /coop/piggyback-analyses/{id}/determination`."

        Design: Corner/Errors/solicitation_lifecycle_error_family_is_triggerable_end_to_end
        """
        set_clock(api, CLOCK_REGISTRY)
        seed_state_law_rules(api)
        past_due = _draft(
            api, solicitation_number="COOP-2026-011", response_due_at=PAST_DUE_AT
        )
        wyoming = _draft(
            api, solicitation_number="COOP-2026-012", lead_agency_state_code="WY"
        )

        validate_error(
            _lifecycle(api, past_due["id"], "POST_NOTICE"),
            ApiErrorId.ERR_RESPONSE_DUE_IN_PAST,
            422,
        )
        validate_error(
            _lifecycle(api, wyoming["id"], "POST_NOTICE"),
            ApiErrorId.ERR_STATE_LAW_RULE_NOT_FOUND,
            404,
        )

        refused_state = read_solicitation(api, wyoming["id"])
        assert refused_state["status"] == "DRAFT"
        assert refused_state["posted_at"] is None
        assert refused_state["notice_days"] is None
        refused_deadline = read_solicitation(api, past_due["id"])
        assert refused_deadline["status"] == "DRAFT"
        assert refused_deadline["posted_at"] is None

    def test_02_the_response_window_closes_and_one_supplier_files_once(self, api):
        """PRD §3.2: "`OPEN_EVALUATION` moves `POSTED → EVALUATION` and requires the logical
        clock to have reached or passed `response_due_at`; attempting it earlier is
        `ERR_RESPONSE_WINDOW_OPEN`." PRD §3.2: "The acting supplier must be `QUALIFIED`
        (`ERR_SUPPLIER_NOT_QUALIFIED`), and the same supplier may not hold two live responses on
        one solicitation: a prior response in any status other than `WITHDRAWN` or
        `NON_RESPONSIVE` blocks the new one with `ERR_DUPLICATE_RESPONSE`." PRD §3.2: "From that
        moment no further response may be filed on this solicitation, which surfaces as
        `ERR_SOLICITATION_CLOSED_FOR_RESPONSES`."

        Design: Corner/Errors/solicitation_lifecycle_error_family_is_triggerable_end_to_end
        """
        world = setup_posted_solicitation(api)
        solicitation_id = world["solicitation"]["id"]

        validate_error(
            _lifecycle(api, solicitation_id, "OPEN_EVALUATION"),
            ApiErrorId.ERR_RESPONSE_WINDOW_OPEN,
            409,
        )
        first = file_response(api, solicitation_id, world["supplier_a"])
        validate_error(
            _file_again(api, solicitation_id, world["supplier_a"]["id"]),
            ApiErrorId.ERR_DUPLICATE_RESPONSE,
            409,
        )

        set_clock(api, CLOCK_AFTER_RESPONSE_DUE)
        opened = validate_success(_lifecycle(api, solicitation_id, "OPEN_EVALUATION"))
        assert opened["status"] == "EVALUATION"
        validate_error(
            _file_again(api, solicitation_id, world["supplier_b"]["id"]),
            ApiErrorId.ERR_SOLICITATION_CLOSED_FOR_RESPONSES,
            409,
        )

        rows, meta = validate_paginated(api.list_solicitation_responses(ADMIN_REVIEW))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "SUBMITTED"

    def test_03_an_unscored_field_cannot_be_recommended_and_fails_instead(self, api):
        """PRD §3.2: "`MARK_RESPONSIVE` moves `SUBMITTED → RESPONSIVE`, requires the
        solicitation to be in `EVALUATION` and the supplier to be `QUALIFIED`, and requires a
        `technical_score` in the request body between 0.00 and 100.00; a missing or out-of-range
        score is `ERR_TECHNICAL_SCORE_MISSING`." PRD §3.2: "`RECOMMEND_AWARD` moves `EVALUATION →
        AWARD_PENDING` and requires at least two responses in `RESPONSIVE` status — fewer is
        `ERR_INSUFFICIENT_RESPONSIVE_RESPONSES` — and requires every `RESPONSIVE` response to
        carry a non-null `technical_score`, failing which it is `ERR_TECHNICAL_SCORE_MISSING`."
        PRD §3.2: "`FAIL` moves `EVALUATION → FAILED` and is available only when the responsive
        count is strictly below two; it sets every response whose status is `SUBMITTED` or
        `INFO_REQUESTED` to `NON_RESPONSIVE`, and — this is the difference from the sibling
        branch — writes no `price_score`, no `composite_score` and no `award_rank` on any
        response at all."

        Design: Corner/Errors/solicitation_lifecycle_error_family_is_triggerable_end_to_end
        """
        world = setup_posted_solicitation(api)
        solicitation_id = world["solicitation"]["id"]
        response = file_response(api, solicitation_id, world["supplier_a"])
        set_clock(api, CLOCK_AFTER_RESPONSE_DUE)
        validate_success(_lifecycle(api, solicitation_id, "OPEN_EVALUATION"))

        validate_error(
            api.response_review(response["id"], {"action": "MARK_RESPONSIVE"}, OFFICER_CONDUCTOR),
            ApiErrorId.ERR_TECHNICAL_SCORE_MISSING,
            422,
        )
        unscored = read_response(api, response["id"])
        assert unscored["status"] == "SUBMITTED"
        assert unscored["technical_score"] is None
        assert read_solicitation(api, solicitation_id)["responsive_response_count"] == 0

        validate_error(
            _lifecycle(api, solicitation_id, "RECOMMEND_AWARD"),
            ApiErrorId.ERR_INSUFFICIENT_RESPONSIVE_RESPONSES,
            422,
        )
        failed = validate_success(_lifecycle(api, solicitation_id, "FAIL"))
        assert failed["status"] == "FAILED"

        demoted = read_response(api, response["id"])
        assert demoted["status"] == "NON_RESPONSIVE"
        assert demoted["price_score"] is None
        assert demoted["composite_score"] is None
        assert demoted["award_rank"] is None


class TestAwardGates:
    def test_04_a_recommended_field_is_not_yet_a_contractable_award(self, api):
        """PRD §2.9: "The `Solicitation` named by a new contract is `AWARDED` —
        `ERR_SOLICITATION_NOT_AWARDED`, 409, on `POST /coop/master-contracts`." PRD §3.2:
        "`RECOMMEND_AWARD` moves `EVALUATION → AWARD_PENDING` and requires at least two responses
        in `RESPONSIVE` status — fewer is `ERR_INSUFFICIENT_RESPONSIVE_RESPONSES` — and requires
        every `RESPONSIVE` response to carry a non-null `technical_score`, failing which it is
        `ERR_TECHNICAL_SCORE_MISSING`."

        Design: Corner/Errors/award_gate_errors_separate_the_solicitation_state_from_the_ranked_supplier_identity
        """
        world = _award_pending_world(api)
        solicitation_id = world["solicitation"]["id"]
        assert world["solicitation"]["status"] == "AWARD_PENDING"
        assert world["solicitation"]["recommended_by_user_id"] == OFFICER_CONDUCTOR_ID

        refused = api.create_master_contract(
            master_contract_payload(solicitation_id, world["supplier_a"]["id"]), OFFICER_AWARDER
        )

        validate_error(refused, ApiErrorId.ERR_SOLICITATION_NOT_AWARDED, 409)
        _, meta = validate_paginated(api.list_master_contracts(ADMIN_REVIEW))
        assert meta["total_count"] == 0
        assert read_solicitation(api, solicitation_id)["status"] == "AWARD_PENDING"

    def test_05_only_the_rank_one_supplier_may_be_papered(self, api):
        """PRD §3.3: "The named solicitation must be `AWARDED` (`ERR_SOLICITATION_NOT_AWARDED`),
        and the named supplier must be the one holding `award_rank` 1 among that solicitation's
        `RESPONSIVE` responses — any other supplier, even on a properly awarded solicitation, is
        `ERR_AWARD_NOT_HIGHEST_RANKED`." PRD §3.2: "On success it stamps `awarded_by_user_id` and
        unlocks master-contract creation for that rank-1 supplier's `supplier_id`." PRD §3.3: "A
        new contract starts in `status` `PENDING_EXECUTION` with `compliance_posture`
        `COMPLIANT`, `current_term_end` initialised to `base_term_end`, `renewals_used` 0, and
        every ledger total — `usage_chargeable_cents_total`, `fee_assessed_cents_total`,
        `fee_remitted_cents_total`, `fee_outstanding_cents` and `delinquent_report_count` — at
        0."

        Design: Corner/Errors/award_gate_errors_separate_the_solicitation_state_from_the_ranked_supplier_identity
        """
        world = setup_awarded_solicitation(api)
        solicitation_id = world["solicitation"]["id"]

        refused = api.create_master_contract(
            master_contract_payload(
                solicitation_id,
                world["supplier_b"]["id"],
                contract_number="COOP-MC-2026-002",
            ),
            OFFICER_AWARDER,
        )

        validate_error(refused, ApiErrorId.ERR_AWARD_NOT_HIGHEST_RANKED, 422)
        _, meta = validate_paginated(api.list_master_contracts(ADMIN_REVIEW))
        assert meta["total_count"] == 0
        awarded = read_solicitation(api, solicitation_id)
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_by_user_id"] == OFFICER_AWARDER_ID
        ranked_first = read_response(api, world["response_a"]["id"])
        ranked_second = read_response(api, world["response_b"]["id"])
        assert ranked_first["award_rank"] == 1
        assert ranked_second["award_rank"] == 2
        assert_score(ranked_first["composite_score"], 92.80, "composite_score")
        assert_score(ranked_second["composite_score"], 89.00, "composite_score")

        contract = validate_success(
            api.create_master_contract(
                master_contract_payload(solicitation_id, world["supplier_a"]["id"]),
                OFFICER_AWARDER,
            ),
            201,
        )
        assert contract["status"] == "PENDING_EXECUTION"
        assert contract["supplier_id"] == world["supplier_a"]["id"]
        assert contract["renewals_used"] == 0


class TestNaturalKeyCollisions:
    def test_06_the_registry_keys_each_answer_with_their_own_duplicate_code(self, api):
        """PRD §2.9: "Global natural-key uniqueness — `ERR_DUPLICATE_STATE_LAW_RULE`,
        `ERR_DUPLICATE_SOLICITATION_NUMBER`, `ERR_DUPLICATE_CONTRACT_NUMBER`,
        `ERR_DUPLICATE_SUPPLIER_NAME` or `ERR_DUPLICATE_MEMBER_NAME`, 409, on
        `POST /coop/state-law-rules`, `POST /coop/solicitations`, `POST /coop/master-contracts`,
        `POST /coop/suppliers` and `POST /coop/member-agencies` respectively." PRD §3.1: "An
        administrator registers one with a `legal_name` — 1 to 200 characters, globally unique,
        with a collision rejected as `ERR_DUPLICATE_SUPPLIER_NAME` — and a `home_state_code`
        naming the state of its principal place of business."

        Design: Corner/Errors/every_natural_key_collision_reports_its_own_duplicate_error
        """
        _duplicate_world(api)

        validate_error(
            api.create_state_law_rule(state_law_rule_payload(**TX_RULE), ADMIN_INTAKE),
            ApiErrorId.ERR_DUPLICATE_STATE_LAW_RULE,
            409,
        )
        validate_error(
            api.create_solicitation(solicitation_payload(), OFFICER_CONDUCTOR),
            ApiErrorId.ERR_DUPLICATE_SOLICITATION_NUMBER,
            409,
        )
        validate_error(
            api.create_supplier(supplier_payload(), ADMIN_INTAKE),
            ApiErrorId.ERR_DUPLICATE_SUPPLIER_NAME,
            409,
        )

        _, rules = validate_paginated(api.list_state_law_rules(ADMIN_REVIEW))
        assert rules["total_count"] == 2
        _, solicitations = validate_paginated(api.list_solicitations(ADMIN_REVIEW))
        assert solicitations["total_count"] == 1
        _, suppliers = validate_paginated(api.list_suppliers(ADMIN_REVIEW))
        assert suppliers["total_count"] == 2

    def test_07_the_contract_the_member_and_the_catalogue_number_collide_separately(self, api):
        """PRD §2.9: "Catalogue numbers are unique within a contract — `ERR_DUPLICATE_SKU`, 409,
        on `POST /coop/master-contracts/{id}/line-items` and
        `POST /coop/contract-amendments/{id}/decision`." PRD §3.3: "The `sku` must be unique
        within the contract, counting both `AWARD` and `EXPANSION` lines whose `status` is not
        `WITHDRAWN`; a collision is `ERR_DUPLICATE_SKU`." PRD §3.4: "Registering a member records
        a `legal_name` of 1 to 200 characters that must be unique across all member agencies
        (`ERR_DUPLICATE_MEMBER_NAME`), a `state_code` naming the state whose procurement law
        governs it, a `member_category`, and an `annual_spend_ceiling_cents` of at least 1 giving
        the board-approved ceiling on cumulative cooperative spend."

        Design: Corner/Errors/every_natural_key_collision_reports_its_own_duplicate_error
        """
        world = _duplicate_world(api)

        validate_error(
            api.create_master_contract(
                master_contract_payload(
                    world["solicitation"]["id"], world["supplier_a"]["id"]
                ),
                OFFICER_AWARDER,
            ),
            ApiErrorId.ERR_DUPLICATE_CONTRACT_NUMBER,
            409,
        )
        validate_error(
            api.create_member_agency(member_agency_payload(), ADMIN_INTAKE),
            ApiErrorId.ERR_DUPLICATE_MEMBER_NAME,
            409,
        )
        validate_error(
            api.create_line_item(world["contract"]["id"], line_item_payload(), OFFICER_AWARDER),
            ApiErrorId.ERR_DUPLICATE_SKU,
            409,
        )

        _, contracts = validate_paginated(api.list_master_contracts(ADMIN_REVIEW))
        assert contracts["total_count"] == 1
        _, members = validate_paginated(api.list_member_agencies(ADMIN_REVIEW))
        assert members["total_count"] == 1
        _, lines = validate_paginated(
            api.list_line_items_of_contract(world["contract"]["id"], ADMIN_REVIEW)
        )
        assert lines["total_count"] == 1


class TestLineItemAndTermErrors:
    def test_08_the_three_line_item_failure_modes_are_distinct_codes(self, api):
        """PRD §2.8: "A usage naming a line item that does not exist is therefore a 404, not a
        422 mismatch." PRD §2.9: "The named line item belongs to the named contract —
        `ERR_LINE_ITEM_CONTRACT_MISMATCH`, 422, on `POST /coop/contract-usages`,
        `POST /coop/contract-amendments` and `GET /coop/master-contracts/{id}/price-quote`." PRD
        §3.3: "A line's `status` is either `ACTIVE` or `WITHDRAWN`, and only an `ACTIVE` line may
        be purchased or repriced (`ERR_LINE_ITEM_NOT_ACTIVE`)." PRD §3.6: "The quote is subject
        to the same line-item liveness, line-contract matching and add-on catalogue checks as a
        real order."

        Design: Corner/Errors/line_item_referential_and_term_window_errors_on_the_usage_family
        """
        world = _line_item_world(api)
        member_id = world["member"]["id"]

        validate_error(
            _quote(api, world["contract"]["id"], world["second_line"]["id"], member_id),
            ApiErrorId.ERR_LINE_ITEM_CONTRACT_MISMATCH,
            422,
        )
        validate_error(
            _quote(api, world["contract"]["id"], NON_EXISTENT_UUID, member_id),
            ApiErrorId.ERR_LINE_ITEM_NOT_FOUND,
            404,
        )

        terminated = validate_success(
            api.contract_award_status(
                world["second"]["id"],
                {"action": "TERMINATE", "note": "papered in error"},
                ADMIN_REVIEW,
            )
        )
        assert terminated["status"] == "TERMINATED"
        assert read_line_item(api, world["second_line"]["id"])["status"] == "WITHDRAWN"

        validate_error(
            _quote(api, world["second"]["id"], world["second_line"]["id"], member_id),
            ApiErrorId.ERR_LINE_ITEM_NOT_ACTIVE,
            409,
        )
        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "DETERMINED"

    def test_09_an_order_one_day_before_the_term_start_is_outside_the_half_open_term(self, api):
        """PRD §3.6: "The order's `ordered_at`, taken from the logical clock at creation, must
        fall inside the contract's half-open term: an instant equal to `base_term_start` is
        inside, an instant equal to `current_term_end` is outside, and either violation is
        `ERR_OUTSIDE_CONTRACT_TERM`." PRD §2.9: "A usage's `ordered_at` falls inside the
        contract's term — `ERR_OUTSIDE_CONTRACT_TERM`, 409, on `POST /coop/contract-usages`."

        Design: Corner/Errors/line_item_referential_and_term_window_errors_on_the_usage_family
        """
        world = _line_item_world(api)
        member_id = world["member"]["id"]
        set_clock(api, CLOCK_AUG_31)

        refused = api.create_contract_usage(
            contract_usage_payload(
                world["contract"]["id"], member_id, world["line"]["id"], world["analysis"]["id"]
            ),
            make_member_headers(member_id),
        )

        validate_error(refused, ApiErrorId.ERR_OUTSIDE_CONTRACT_TERM, 409)
        assert_cents(
            read_member(api, member_id)["committed_spend_cents"], 0, "committed_spend_cents"
        )
        contract = read_contract(api, world["contract"]["id"])
        assert contract["status"] == "ACTIVE"
        assert_cents(
            contract["usage_chargeable_cents_total"], 0, "usage_chargeable_cents_total"
        )
        _, usages = validate_paginated(api.list_contract_usages(ADMIN_REVIEW))
        assert usages["total_count"] == 0
        assert read_analysis(api, world["analysis"]["id"])["status"] == "DETERMINED"


class TestFeeSettlementErrors:
    def test_10_the_settlement_pipeline_refuses_every_premature_step(self, api):
        """PRD §3.7: "In both cases it requires the acting `X-User-ID` to be the contract's
        `supplier_id`, requires the logical clock to be strictly past `period_end` so the period
        has fully elapsed (otherwise `ERR_REPORT_PERIOD_NOT_ELAPSED`), and re-runs the overlap
        test against every *other* non-rejected report on the contract, excluding this report
        itself." PRD §3.7: "A review or submission action that is not a declared transition on
        the acceptance dimension is `ERR_REPORT_INVALID_STATE`." PRD §3.7: "A remittance against
        a `NOT_DUE` or `PAID` report, or an acceptance of a report whose `fee_status` is not
        `NOT_DUE`, is `ERR_FEE_STATUS_INVALID`."

        Design: Corner/Errors/fee_settlement_error_family_from_an_unelapsed_period_to_an_exact_remittance
        """
        world = _september_report_world(api)
        report_id = world["report"]["id"]
        supplier_headers = make_supplier_headers(world["contract"]["supplier_id"])

        validate_error(
            api.report_submission(report_id, {"action": "SUBMIT"}, supplier_headers),
            ApiErrorId.ERR_REPORT_PERIOD_NOT_ELAPSED,
            422,
        )
        validate_error(
            api.report_review(report_id, {"action": "ACCEPT"}, ADMIN_REVIEW),
            ApiErrorId.ERR_REPORT_INVALID_STATE,
            409,
        )
        validate_error(
            api.report_fee_remittance(
                report_id, {"action": "REMIT", "amount_cents": 541}, supplier_headers
            ),
            ApiErrorId.ERR_FEE_STATUS_INVALID,
            409,
        )

        still_draft = read_report(api, report_id)
        assert still_draft["status"] == "DRAFT"
        assert still_draft["fee_status"] == "NOT_DUE"
        assert_cents(still_draft["remitted_cents"], 0, "remitted_cents")

        set_clock(api, CLOCK_OCT_01)
        submitted = submit_report(api, world, report_id)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["swept_usage_count"] == 3
        assert_cents(submitted["reported_chargeable_cents"], 27045, "reported_chargeable_cents")
        assert_cents(submitted["reported_usage_cents"], 27585, "reported_usage_cents")
        assert_cents(submitted["reported_fee_cents"], 541, "reported_fee_cents")

    def test_11_acceptance_settles_the_period_only_on_an_exact_remittance(self, api):
        """PRD §3.7: "`ACCEPT` moves `SUBMITTED → ACCEPTED`, stamps `accepted_at` with the
        current logical instant, sets `fee_due_at` to thirty days after `accepted_at`, moves the
        parallel `fee_status` from `NOT_DUE` to `DUE`, and adds `reported_fee_cents` to both the
        contract's and the supplier's `fee_assessed_cents_total` before recomputing the
        contract's `fee_outstanding_cents`." PRD §3.7: "`REMIT`, performed by the supplier on its
        own report, is reachable from `DUE` and from `DELINQUENT`, requires the acting
        `X-User-ID` to be the contract's `supplier_id`, and requires the supplied `amount_cents`
        to equal `reported_fee_cents` minus `remitted_cents` exactly — partial payments and
        over-payments are both refused with `ERR_REMITTANCE_AMOUNT_MISMATCH`." PRD §3.6: "Once
        the sweeping report has reached `ACCEPTED` or `RECONCILED` the fee ledger can no longer be
        unwound and retraction is refused with `ERR_USAGE_ALREADY_SETTLED`."

        Design: Corner/Errors/fee_settlement_error_family_from_an_unelapsed_period_to_an_exact_remittance
        """
        world = _submitted_september_world(api)
        report_id = world["report"]["id"]
        supplier_headers = make_supplier_headers(world["contract"]["supplier_id"])

        validate_error(
            api.report_review(report_id, {"action": "RECONCILE"}, ADMIN_REVIEW),
            ApiErrorId.ERR_REPORT_INVALID_STATE,
            409,
        )
        accepted = accept_report(api, report_id)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["fee_status"] == "DUE"
        assert_instant(accepted["accepted_at"], CLOCK_OCT_01, "accepted_at")
        assert_instant(accepted["fee_due_at"], FEE_DUE_AT, "fee_due_at")
        assessed = read_contract(api, world["contract"]["id"])
        assert_cents(assessed["fee_assessed_cents_total"], 541, "fee_assessed_cents_total")
        assert_cents(assessed["fee_outstanding_cents"], 541, "fee_outstanding_cents")

        validate_error(
            api.report_fee_remittance(
                report_id, {"action": "REMIT", "amount_cents": 540}, supplier_headers
            ),
            ApiErrorId.ERR_REMITTANCE_AMOUNT_MISMATCH,
            422,
        )
        settled_usage = world["usages"][0]
        validate_error(
            api.usage_disposition(
                settled_usage["id"],
                {"action": "RETRACT"},
                make_member_headers(world["member"]["id"]),
            ),
            ApiErrorId.ERR_USAGE_ALREADY_SETTLED,
            409,
        )
        assert read_usage(api, settled_usage["id"])["status"] == "CONFIRMED"

        paid = remit_fee(api, world, report_id, 541)
        assert paid["fee_status"] == "PAID"
        assert_cents(paid["remitted_cents"], 541, "remitted_cents")
        closed = read_contract(api, world["contract"]["id"])
        assert_cents(closed["fee_remitted_cents_total"], 541, "fee_remitted_cents_total")
        assert_cents(closed["fee_outstanding_cents"], 0, "fee_outstanding_cents")
        assert_fee_ledger_balanced(closed)
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_cents(supplier["fee_remitted_cents_total"], 541, "fee_remitted_cents_total")


class TestAnalysisAndAmendmentStateErrors:
    def test_12_a_determined_opinion_refuses_a_second_determination_and_a_second_void(self, api):
        """PRD §3.5: "`VOID` is reachable from `PENDING` and from `DETERMINED` and sets
        `voided_reason` to `ADMIN_VOID` when an administrator requests it explicitly." PRD §3.5:
        "An action that is not a declared transition is `ERR_ANALYSIS_INVALID_STATE`." PRD §2.9:
        "The `PiggybackAnalysis` is in a from-state permitting the requested action —
        `ERR_ANALYSIS_INVALID_STATE`, 409, on `POST /coop/piggyback-analyses/{id}/determination`."

        Design: Corner/Errors/analysis_and_amendment_state_errors_are_reported_by_their_own_codes
        """
        world = _authorised_world(api)
        analysis_id = world["analysis"]["id"]
        assert world["analysis"]["determination"] == "CONDITIONAL"

        validate_error(
            api.analysis_determination(analysis_id, {"action": "DETERMINE"}, ADMIN_PIGGYBACK),
            ApiErrorId.ERR_ANALYSIS_INVALID_STATE,
            409,
        )
        unchanged = read_analysis(api, analysis_id)
        assert unchanged["status"] == "DETERMINED"
        assert unchanged["determination"] == "CONDITIONAL"
        assert_score(unchanged["authority_score"], 70.00, "authority_score")

        voided = validate_success(
            api.analysis_determination(analysis_id, {"action": "VOID"}, ADMIN_PIGGYBACK)
        )
        assert voided["status"] == "VOIDED"
        assert voided["voided_reason"] == "ADMIN_VOID"

        validate_error(
            api.analysis_determination(analysis_id, {"action": "VOID"}, ADMIN_PIGGYBACK),
            ApiErrorId.ERR_ANALYSIS_INVALID_STATE,
            409,
        )
        assert read_analysis(api, analysis_id)["voided_reason"] == "ADMIN_VOID"

    def test_13_a_rejected_amendment_refuses_a_second_decision(self, api):
        """PRD §3.8: "`REJECT` moves `PROPOSED → REJECTED`, stamps `decided_by_user_id`, stores
        the `decision_note`, and changes no field on the contract or on any line item." PRD §3.8:
        "Both require the amendment to be `PROPOSED`, otherwise `ERR_AMENDMENT_NOT_PROPOSED`."
        PRD §2.9: "The `ContractAmendment` is `PROPOSED` — `ERR_AMENDMENT_NOT_PROPOSED`, 409, on
        `POST /coop/contract-amendments/{id}/decision` and
        `POST /coop/contract-amendments/{id}/withdrawal`."

        Design: Corner/Errors/analysis_and_amendment_state_errors_are_reported_by_their_own_codes
        """
        world = setup_active_contract(api)
        contract = world["contract"]
        proposal = validate_success(_propose_renewal(api, contract, RENEWAL_TERM_END), 201)
        assert proposal["status"] == "PROPOSED"

        rejected = validate_success(
            _decide(api, proposal["id"], "REJECT", "not required this cycle")
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["decided_by_user_id"] == ADMIN_REVIEW_ID
        assert rejected["effective_from"] is None

        validate_error(
            _decide(api, proposal["id"], "APPROVE", "reconsidered"),
            ApiErrorId.ERR_AMENDMENT_NOT_PROPOSED,
            409,
        )
        assert read_amendment(api, proposal["id"])["status"] == "REJECTED"
        untouched = read_contract(api, contract["id"])
        assert_instant(untouched["current_term_end"], BASE_TERM_END, "current_term_end")
        assert untouched["renewals_used"] == 0


class TestRenewalCeilings:
    def test_14_a_legal_extension_still_breaks_the_sixty_month_total(self, api):
        """PRD §3.8: "The merged total term, computed by the same calendar arithmetic between
        `base_term_start` and `requested_term_end`, must not exceed sixty months, a longer total
        being `ERR_TOTAL_TERM_EXCEEDS_MAX`." PRD §2.9: "Renewal interval arithmetic —
        `ERR_RENEWAL_TERM_NOT_EXTENDING`, `ERR_RENEWAL_TERM_TOO_LONG` or
        `ERR_TOTAL_TERM_EXCEEDS_MAX`, 422, on `POST /coop/contract-amendments` and
        `POST /coop/contract-amendments/{id}/decision`."

        Design: Corner/Errors/renewal_ceilings_split_the_total_term_cap_from_the_renewal_count_cap
        """
        world = setup_active_contract(
            api,
            contract_overrides={
                "contract_number": "COOP-MC-2026-0A1",
                "base_term_end": TERM_END_55_MONTHS,
            },
        )

        refused = _propose_renewal(api, world["contract"], RENEWAL_TO_67_MONTHS)

        validate_error(refused, ApiErrorId.ERR_TOTAL_TERM_EXCEEDS_MAX, 422)
        contract = read_contract(api, world["contract"]["id"])
        assert_instant(contract["current_term_end"], TERM_END_55_MONTHS, "current_term_end")
        assert contract["renewals_used"] == 0
        _, amendments = validate_paginated(api.list_contract_amendments(ADMIN_REVIEW))
        assert amendments["total_count"] == 0

    def test_15_the_second_renewal_passes_the_arithmetic_and_fails_the_allowance(self, api):
        """PRD §3.8: "Approval additionally requires `renewals_used` to be strictly below
        `max_renewals`, otherwise `ERR_RENEWAL_LIMIT_REACHED`." PRD §3.8: "The `RENEWAL` branch
        sets the contract's `current_term_end` to `requested_term_end` and increments
        `renewals_used` by 1; already-determined authority opinions keep their frozen
        `expires_on` and are not extended." PRD §2.9: "Renewals are bounded by the contract's
        allowance — `ERR_RENEWAL_LIMIT_REACHED`, 409, on
        `POST /coop/contract-amendments/{id}/decision`."

        Design: Corner/Errors/renewal_ceilings_split_the_total_term_cap_from_the_renewal_count_cap
        """
        world = setup_active_contract(
            api,
            contract_overrides={
                "contract_number": "COOP-MC-2026-0B1",
                "base_term_end": TERM_END_36_MONTHS,
                "max_renewals": 1,
            },
        )
        first = validate_success(
            _propose_renewal(api, world["contract"], RENEWAL_TO_48_MONTHS), 201
        )
        approved = validate_success(_decide(api, first["id"], "APPROVE", "first renewal"))
        assert approved["status"] == "APPROVED"
        renewed = read_contract(api, world["contract"]["id"])
        assert_instant(renewed["current_term_end"], RENEWAL_TO_48_MONTHS, "current_term_end")
        assert renewed["renewals_used"] == 1

        second = validate_success(_propose_renewal(api, renewed, RENEWAL_TO_60_MONTHS), 201)
        assert second["status"] == "PROPOSED"

        validate_error(
            _decide(api, second["id"], "APPROVE", "second renewal"),
            ApiErrorId.ERR_RENEWAL_LIMIT_REACHED,
            409,
        )
        assert read_amendment(api, second["id"])["status"] == "PROPOSED"
        final = read_contract(api, world["contract"]["id"])
        assert_instant(final["current_term_end"], RENEWAL_TO_48_MONTHS, "current_term_end")
        assert final["renewals_used"] == 1


class TestHeaderAndSchemaRungs:
    def test_16_an_absent_and_an_unrecognised_role_answer_with_the_same_401(self, api):
        """PRD §2.9: "Auth headers present and `X-User-Role` recognised —
        `ERR_MISSING_AUTH_HEADERS`, 401, on every endpoint." PRD §2.9: "The endpoint's role list
        contains `X-User-Role` — `ERR_UNAUTHORIZED`, 403, on every endpoint." PRD §2.2: "The
        `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/Errors/header_and_schema_rungs_answer_before_any_business_rule_is_consulted
        """
        world = _authorised_world(api)
        contract_id = world["contract"]["id"]

        headerless = api.get_master_contract(contract_id, {})
        undeclared = api.get_master_contract(
            contract_id, build_user_headers(ADMIN_REVIEW_ID, UNKNOWN_ROLE)
        )

        validate_error(headerless, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)
        validate_error(undeclared, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)
        for refusal in (headerless, undeclared):
            body = refusal.json()
            assert body["response_type"] == "error"
            assert body["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
            assert_error_data_shape(body["data"])
            assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}

    def test_17_the_schema_rung_refuses_an_unknown_field_an_oversized_limit_and_a_zero_quantity(
        self, api
    ):
        """PRD §2.9: "Request body and query string conform to the endpoint's input schema: no
        unknown fields, no missing required fields, correct scalar types, enum values (including
        the endpoint's `action` set) inside their declared sets, `limit` within 1 to 100, `offset`
        at least 0, `quantity` at least 1, `amount_cents` at least 0, `technical_score` within
        0.00 to 100.00, `technical_weight_pct` and `price_weight_pct` summing to exactly 100,
        `base_term_start` strictly before `base_term_end`, `period_start` at or before
        `period_end`, and `discount_tiers` and `permitted_add_ons` well formed per their own
        constraints — `ERR_INVALID_REQUEST`, 400, on every endpoint." PRD §2.3: "A `limit`
        outside 1 through 100, or a negative `offset`, is a request-shape failure and is rejected
        with `ERR_INVALID_REQUEST`."

        Design: Corner/Errors/header_and_schema_rungs_answer_before_any_business_rule_is_consulted
        """
        world = _authorised_world(api)
        member_id = world["member"]["id"]

        unknown_field = api.create_supplier(
            {
                "legal_name": JUNIPER,
                "home_state_code": "TX",
                "primary_contact_email": "ops@juniper.example",
            },
            ADMIN_INTAKE,
        )
        oversized_limit = api.list_suppliers(ADMIN_REVIEW, {"limit": 101})
        zero_quantity = api.create_contract_usage(
            contract_usage_payload(
                world["contract"]["id"],
                member_id,
                world["line"]["id"],
                world["analysis"]["id"],
                quantity=0,
            ),
            make_member_headers(member_id),
        )

        validate_error(unknown_field, ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(oversized_limit, ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(zero_quantity, ApiErrorId.ERR_INVALID_REQUEST, 400)
        for refusal in (unknown_field, oversized_limit, zero_quantity):
            assert_error_data_shape(refusal.json()["data"])

        rows, meta = validate_paginated(api.list_suppliers(ADMIN_REVIEW))
        assert meta["total_count"] == 2
        assert all(row["legal_name"] != JUNIPER for row in rows)
        assert_cents(
            read_member(api, member_id)["committed_spend_cents"], 0, "committed_spend_cents"
        )


class TestLedgerIdentity:
    def test_18_a_negative_true_up_drives_the_contract_ledger_below_zero(self, api):
        """PRD §3.7: "`RECONCILE` moves `ACCEPTED → RECONCILED` and requires `fee_status` to be
        `PAID` or `DELINQUENT`." PRD §3.7: "`variance_pct` is one hundred multiplied by the
        absolute value of `fee_true_up_cents` and divided by `audited_fee_cents`, rounded half up
        to two decimals; when `audited_fee_cents` is zero, `variance_pct` is 0.00 rather than
        undefined." PRD §3.7: "`fee_true_up_cents` is then applied to both the contract's and the
        supplier's `fee_assessed_cents_total`, and the contract's `fee_outstanding_cents` is
        recomputed." PRD §3.7: "When `variance_pct` is strictly greater than fifteen percent,
        `variance_flagged` is set to true and five performance points are added to the supplier's
        `deduction_points_total`."

        Design: Corner/Errors/a_negative_true_up_lets_a_later_exact_remittance_break_the_ledger_identity
        """
        world = _reconciled_september_world(api)

        report = read_report(api, world["report"]["id"])
        assert report["status"] == "RECONCILED"
        assert_cents(report["reported_fee_cents"], 541, "reported_fee_cents")
        assert_cents(report["audited_fee_cents"], 540, "audited_fee_cents")
        assert_cents(report["fee_true_up_cents"], -1, "fee_true_up_cents")
        assert_cents(report["fee_rebate_cents"], 1, "fee_rebate_cents")
        assert_score(report["variance_pct"], 0.19, "variance_pct")
        assert report["variance_flagged"] is False

        contract = read_contract(api, world["contract"]["id"])
        assert_cents(contract["fee_assessed_cents_total"], 540, "fee_assessed_cents_total")
        assert_cents(contract["fee_remitted_cents_total"], 541, "fee_remitted_cents_total")
        assert_cents(contract["fee_outstanding_cents"], -1, "fee_outstanding_cents")
        assert contract["fee_outstanding_cents"] == (
            contract["fee_assessed_cents_total"] - contract["fee_remitted_cents_total"]
        )

    def test_19_an_exact_october_remittance_is_refused_by_the_ledger_invariant(self, api):
        """PRD §3.7: "The fee ledger has an invariant the system must never violate: a contract's
        `fee_outstanding_cents` always equals its `fee_assessed_cents_total` minus its
        `fee_remitted_cents_total` after every fee mutation, and no remittance may drive
        `fee_outstanding_cents` below zero." PRD §3.7: "A mutation that would break either half
        is refused with `ERR_FEE_LEDGER_INCONSISTENT`." PRD §2.9: "The fee ledger stays
        internally consistent — `ERR_FEE_LEDGER_INCONSISTENT`, 409, on
        `POST /coop/usage-reports/{id}/fee-remittance` and
        `POST /coop/usage-reports/{id}/review`."

        Design: Corner/Errors/a_negative_true_up_lets_a_later_exact_remittance_break_the_ledger_identity
        """
        world = _reconciled_september_world(api)
        set_clock(api, CLOCK_OCT_15)
        record_confirmed_usage(
            api,
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_LINER]["id"],
            world["analysis"]["id"],
        )
        october = open_report(
            api, world, period_start=OCT_PERIOD_START, period_end=OCT_PERIOD_END
        )
        set_clock(api, CLOCK_NOV_01)
        submitted = submit_report(api, world, october["id"])
        assert_cents(submitted["reported_fee_cents"], 180, "reported_fee_cents")
        accept_report(api, october["id"])
        before = read_contract(api, world["contract"]["id"])
        assert_cents(before["fee_assessed_cents_total"], 720, "fee_assessed_cents_total")
        assert_cents(before["fee_remitted_cents_total"], 541, "fee_remitted_cents_total")
        assert_cents(before["fee_outstanding_cents"], 179, "fee_outstanding_cents")

        refused = api.report_fee_remittance(
            october["id"],
            {"action": "REMIT", "amount_cents": 180},
            make_supplier_headers(world["contract"]["supplier_id"]),
        )

        validate_error(refused, ApiErrorId.ERR_FEE_LEDGER_INCONSISTENT, 409)
        unpaid = read_report(api, october["id"])
        assert unpaid["fee_status"] == "DUE"
        assert_cents(unpaid["remitted_cents"], 0, "remitted_cents")
        after = read_contract(api, world["contract"]["id"])
        assert_cents(after["fee_remitted_cents_total"], 541, "fee_remitted_cents_total")
        assert_cents(after["fee_outstanding_cents"], 179, "fee_outstanding_cents")
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_cents(supplier["fee_remitted_cents_total"], 541, "fee_remitted_cents_total")
        assert_score(supplier["performance_score"], 100.00, "performance_score")
