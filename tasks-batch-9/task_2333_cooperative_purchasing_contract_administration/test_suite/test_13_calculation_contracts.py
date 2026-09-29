"""Calculations that hinge on which rows enter the input set and which cap binds."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_supplier_headers,
)
from test_helpers.constants import (
    CLOCK_AFTER_RESPONSE_DUE,
    CLOCK_OCT_01,
    CLOCK_TERM_START,
    SKU_LINER,
)
from test_helpers.factories import (
    LINER_LINE,
    price_adjustment_amendment_payload,
)
from test_helpers.fixtures import (
    file_response,
    open_report,
    read_amendment,
    read_contract,
    read_line_item,
    read_member,
    read_response,
    read_solicitation,
    read_usage,
    record_confirmed_usage,
    record_usage,
    register_qualified_supplier,
    retract_usage,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    setup_awarded_solicitation,
    setup_posted_solicitation,
    submit_report,
)
from test_helpers.test_users import (
    OFFICER_AWARDER,
    OFFICER_AWARDER_ID,
    OFFICER_CONDUCTOR,
)

EIGHT_CODES = [
    "NOTICE_OF_SOLICITATION",
    "SPECIFICATION_PACKAGE",
    "PROCUREMENT_METHOD_JUSTIFICATION",
    "ADDENDA_LOG",
    "RESPONSE_TABULATION",
    "EVALUATION_SCORESHEET",
    "AWARD_RECOMMENDATION",
    "CONTRACT_EXECUTION",
]


def _assemble(api, solicitation_id):
    return validate_success(
        api.solicitation_audit_package(
            solicitation_id, {"action": "ASSEMBLE"}, OFFICER_CONDUCTOR
        )
    )


def _certify(api, solicitation_id):
    return api.solicitation_audit_package(
        solicitation_id, {"action": "CERTIFY"}, OFFICER_AWARDER
    )


def _three_response_world(api):
    """One solicitation in EVALUATION carrying three RESPONSIVE responses."""
    world = setup_posted_solicitation(api)
    sol_id = world["solicitation"]["id"]
    world["supplier_c"] = register_qualified_supplier(
        api, legal_name="Cedar Supply Co", home_state_code="TX"
    )
    world["response_a"] = file_response(
        api, sol_id, world["supplier_a"], proposed_annual_value_cents=1000000
    )
    world["response_b"] = file_response(
        api, sol_id, world["supplier_b"], proposed_annual_value_cents=1250000
    )
    world["response_c"] = file_response(
        api, sol_id, world["supplier_c"], proposed_annual_value_cents=500000
    )
    set_clock(api, CLOCK_AFTER_RESPONSE_DUE)
    world["solicitation"] = validate_success(
        api.solicitation_lifecycle(sol_id, {"action": "OPEN_EVALUATION"}, OFFICER_CONDUCTOR)
    )
    for key, score in (("response_a", 88.00), ("response_b", 95.00), ("response_c", 60.00)):
        world[key] = validate_success(
            api.response_review(
                world[key]["id"],
                {"action": "MARK_RESPONSIVE", "technical_score": score},
                OFFICER_CONDUCTOR,
            )
        )
    return world


def _demote_cedar(api, world):
    return validate_success(
        api.response_review(
            world["response_c"]["id"],
            {"action": "MARK_NON_RESPONSIVE", "responsiveness_note": "no performance bond"},
            OFFICER_CONDUCTOR,
        )
    )


def _propose_price(api, world, new_unit_price_cents, price_index, index_change_pct):
    contract = read_contract(api, world["contract"]["id"])
    return api.create_contract_amendment(
        price_adjustment_amendment_payload(
            contract["id"],
            contract["version"],
            world["lines"][world["sku"]]["id"],
            new_unit_price_cents,
            price_index=price_index,
            index_change_pct=index_change_pct,
        ),
        make_supplier_headers(contract["supplier_id"]),
    )


def _price_world(api):
    """An ACTIVE contract whose single dispenser line has never moved in price."""
    world = setup_active_contract(api)
    world["sku"] = next(iter(world["lines"]))
    return world


def _sweep_world(api):
    """One CONFIRMED, one RECORDED and one RETRACTED order inside a single DRAFT period."""
    world = setup_active_contract(api, lines=(LINER_LINE,))
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    contract_id = world["contract"]["id"]
    line_id = world["lines"][SKU_LINER]["id"]
    world["confirmed"] = record_confirmed_usage(
        api, contract_id, member["id"], line_id, analysis["id"]
    )
    world["recorded"] = record_usage(api, contract_id, member["id"], line_id, analysis["id"])
    third = record_confirmed_usage(api, contract_id, member["id"], line_id, analysis["id"])
    world["retracted"] = retract_usage(api, third)
    world["report"] = open_report(api, world)
    set_clock(api, CLOCK_OCT_01)
    return world


class TestAuditCompleteness:
    def test_01_seven_of_the_eight_codes_are_present_before_any_contract_exists(self, api):
        """PRD §3.2: "The required list is a fixed eight-code base, in exactly this order:
        `NOTICE_OF_SOLICITATION`, `SPECIFICATION_PACKAGE`, `PROCUREMENT_METHOD_JUSTIFICATION`,
        `ADDENDA_LOG`, `RESPONSE_TABULATION`, `EVALUATION_SCORESHEET`, `AWARD_RECOMMENDATION`,
        `CONTRACT_EXECUTION`." PRD §3.2: "`audit_present_doc_codes` holds the subset whose
        evidence exists, tested code by code in the same order: `NOTICE_OF_SOLICITATION` is
        present when `posted_at` is non-null; `SPECIFICATION_PACKAGE` when
        `specification_document_ref` is non-null; `PROCUREMENT_METHOD_JUSTIFICATION` when
        `method_justification_ref` is non-null; `ADDENDA_LOG` whenever `posted_at` is non-null,
        because a solicitation that issued no addenda still has an addenda log and an
        `addenda_count` of 0 is a legitimate value that does not make the code absent;
        `RESPONSE_TABULATION` when `responsive_response_count` is at least 1;
        `EVALUATION_SCORESHEET` when `responsive_response_count` is at least 1 *and* every
        `RESPONSIVE` response carries a non-null `technical_score`; `AWARD_RECOMMENDATION` when
        `status` is `AWARD_PENDING` or `AWARDED`; `CONTRACT_EXECUTION` when a master contract on
        this solicitation exists whose status is `ACTIVE`, `SUSPENDED`, `EXPIRED` or
        `TERMINATED`; and `AMENDMENT_LOG` when `amendment_log_document_ref` is non-null." PRD
        §3.2: "`audit_completeness_pct` is one hundred multiplied by the number of present codes
        and divided by the number of required codes, rounded half up to two decimals."

        Design: Corner/Calculations/audit_completeness_reaches_one_hundred_only_once_the_contract_is_executed
        """
        world = setup_awarded_solicitation(api)

        assembled = _assemble(api, world["solicitation"]["id"])

        assert assembled["audit_required_doc_codes"] == EIGHT_CODES
        assert len(assembled["audit_present_doc_codes"]) == 7
        assert "CONTRACT_EXECUTION" not in assembled["audit_present_doc_codes"]
        for code in ("RESPONSE_TABULATION", "EVALUATION_SCORESHEET", "AWARD_RECOMMENDATION"):
            assert code in assembled["audit_present_doc_codes"]
        assert_score(assembled["audit_completeness_pct"], 87.50, "audit_completeness_pct")

    def test_02_certification_is_refused_below_one_hundred_and_stamps_nothing(self, api):
        """PRD §3.2: "It requires `audit_completeness_pct` to be exactly 100.00 — anything less
        is `ERR_AUDIT_PACKAGE_INCOMPLETE` — and it requires the competitive dimension to have
        reached `AWARDED` or `FAILED`."

        Design: Corner/Calculations/audit_completeness_reaches_one_hundred_only_once_the_contract_is_executed
        """
        world = setup_awarded_solicitation(api)
        _assemble(api, world["solicitation"]["id"])

        refused = _certify(api, world["solicitation"]["id"])

        validate_error(refused, ApiErrorId.ERR_AUDIT_PACKAGE_INCOMPLETE, 409)
        solicitation = read_solicitation(api, world["solicitation"]["id"])
        assert solicitation["audit_package_status"] == "ASSEMBLED"
        assert solicitation["certified_at"] is None
        assert solicitation["certified_by_user_id"] is None
        assert_score(solicitation["audit_completeness_pct"], 87.50, "audit_completeness_pct")

    def test_03_execution_supplies_the_last_code_and_unlocks_certification(self, api):
        """PRD §3.2: "If any amendment with status `APPROVED` exists on a master contract of
        this solicitation, `AMENDMENT_LOG` is appended, taking the denominator to nine." PRD
        §3.2: "On success it stamps `certified_at` with the current logical instant and
        `certified_by_user_id` with the acting `X-User-ID`."

        Design: Corner/Calculations/audit_completeness_reaches_one_hundred_only_once_the_contract_is_executed
        """
        world = setup_awarded_solicitation(api)
        _assemble(api, world["solicitation"]["id"])
        validate_error(
            _certify(api, world["solicitation"]["id"]),
            ApiErrorId.ERR_AUDIT_PACKAGE_INCOMPLETE,
            409,
        )
        world = setup_active_contract(api, world=world)

        reassembled = _assemble(api, world["solicitation"]["id"])
        certified = validate_success(_certify(api, world["solicitation"]["id"]))

        assert len(reassembled["audit_present_doc_codes"]) == 8
        assert "CONTRACT_EXECUTION" in reassembled["audit_present_doc_codes"]
        assert reassembled["audit_required_doc_codes"] == EIGHT_CODES
        assert "AMENDMENT_LOG" not in reassembled["audit_required_doc_codes"]
        assert_score(reassembled["audit_completeness_pct"], 100.00, "audit_completeness_pct")
        assert certified["audit_package_status"] == "CERTIFIED"
        assert_instant(certified["certified_at"], CLOCK_TERM_START, "certified_at")
        assert certified["certified_by_user_id"] == OFFICER_AWARDER_ID
        assert certified["status"] == "AWARDED"


class TestResponsiveInputSet:
    def test_04_the_demotion_clears_the_row_and_decrements_the_count(self, api):
        """PRD §3.2: "`MARK_NON_RESPONSIVE` is reachable from `SUBMITTED`, from
        `INFO_REQUESTED` and from `RESPONSIVE`, always requires the solicitation to be in
        `EVALUATION`, and stores the `responsiveness_note`; when it is applied to a response
        that was already `RESPONSIVE` it additionally decrements `responsive_response_count` by
        1 and clears `technical_score`, `price_score`, `composite_score` and `award_rank` to
        null."

        Design: Corner/Calculations/composite_scoring_reads_only_responsive_rows_for_both_the_minimum_and_the_ranking
        """
        world = _three_response_world(api)
        assert read_solicitation(api, world["solicitation"]["id"])[
            "responsive_response_count"
        ] == 3

        demoted = _demote_cedar(api, world)

        assert demoted["status"] == "NON_RESPONSIVE"
        assert demoted["technical_score"] is None
        assert demoted["price_score"] is None
        assert demoted["composite_score"] is None
        assert demoted["award_rank"] is None
        assert read_solicitation(api, world["solicitation"]["id"])[
            "responsive_response_count"
        ] == 2

    def test_05_the_ranking_ignores_the_cheapest_bid_once_it_leaves_the_set(self, api):
        """PRD §3.2: "Take every response on this solicitation whose status is `RESPONSIVE`;
        responses in `SUBMITTED`, `INFO_REQUESTED`, `NON_RESPONSIVE` or `WITHDRAWN` are excluded
        entirely and keep their `price_score`, `composite_score` and `award_rank` null." PRD
        §3.2: "Find the smallest `proposed_annual_value_cents` in that responsive set." PRD
        §3.2: "Then, walking the set in ascending `created_at` order, give each response a
        `price_score` of one hundred multiplied by that smallest proposed value and divided by
        this response's own `proposed_annual_value_cents`, rounded half up to two decimals — so
        the cheapest bid scores 100.00 and a bid twice as expensive scores 50.00."

        Design: Corner/Calculations/composite_scoring_reads_only_responsive_rows_for_both_the_minimum_and_the_ranking
        """
        world = _three_response_world(api)
        _demote_cedar(api, world)

        recommended = validate_success(
            api.solicitation_lifecycle(
                world["solicitation"]["id"], {"action": "RECOMMEND_AWARD"}, OFFICER_CONDUCTOR
            )
        )

        assert recommended["status"] == "AWARD_PENDING"
        first = read_response(api, world["response_a"]["id"])
        second = read_response(api, world["response_b"]["id"])
        third = read_response(api, world["response_c"]["id"])
        assert_score(first["price_score"], 100.00, "price_score")
        assert_score(second["price_score"], 80.00, "price_score")
        assert_score(first["composite_score"], 92.80, "composite_score")
        assert_score(second["composite_score"], 89.00, "composite_score")
        assert first["award_rank"] == 1
        assert second["award_rank"] == 2
        assert third["price_score"] is None
        assert third["composite_score"] is None
        assert third["award_rank"] is None


class TestEscalationCeiling:
    def test_06_the_smallest_of_the_three_fractions_binds_each_proposal(self, api):
        """PRD §3.8: "The cited index carries its own statutory escalation cap: `CPI_U` caps
        escalation at four percent (the fraction 0.0400) and `PPI_COMMODITY` at six percent (the
        fraction 0.0600)." PRD §3.8: "The effective cap is the smallest of three four-decimal
        fractions — the contract's `price_escalation_cap_pct`, the index's own cap, and the
        `index_change_pct` the supplier actually cited — and that three-way minimum is taken on
        the fractions *before* any multiplication." PRD §3.8: "`price_ceiling_cents` is then the
        target line's current `base_unit_price_cents` multiplied by one plus the effective cap,
        rounded half up to a whole cent."

        Design: Corner/Calculations/escalation_ceiling_takes_the_three_way_minimum_of_contract_index_and_request
        """
        world = _price_world(api)

        index_capped = validate_success(_propose_price(api, world, 13000, "CPI_U", 0.0450), 201)
        request_capped = validate_success(
            _propose_price(api, world, 13063, "PPI_COMMODITY", 0.0450), 201
        )
        contract_capped = validate_success(
            _propose_price(api, world, 13125, "PPI_COMMODITY", 0.0800), 201
        )

        assert_cents(index_capped["price_ceiling_cents"], 13000, "price_ceiling_cents")
        assert_cents(request_capped["price_ceiling_cents"], 13063, "price_ceiling_cents")
        assert_cents(contract_capped["price_ceiling_cents"], 13125, "price_ceiling_cents")

    def test_07_each_new_proposal_withdraws_the_older_one_of_its_own_type(self, api):
        """PRD §3.8: "Proposing supersedes: any prior amendment on the same contract with the
        same `amendment_type` whose `status` is `PROPOSED` becomes `WITHDRAWN`."

        Design: Corner/Calculations/escalation_ceiling_takes_the_three_way_minimum_of_contract_index_and_request
        """
        world = _price_world(api)
        first = validate_success(_propose_price(api, world, 13000, "CPI_U", 0.0450), 201)
        second = validate_success(
            _propose_price(api, world, 13063, "PPI_COMMODITY", 0.0450), 201
        )

        third = validate_success(
            _propose_price(api, world, 13125, "PPI_COMMODITY", 0.0800), 201
        )

        assert third["status"] == "PROPOSED"
        stored_first = read_amendment(api, first["id"])
        stored_second = read_amendment(api, second["id"])
        assert stored_first["status"] == "WITHDRAWN"
        assert stored_second["status"] == "WITHDRAWN"
        assert_cents(stored_first["price_ceiling_cents"], 13000, "price_ceiling_cents")
        rows, meta = validate_paginated(
            api.list_contract_amendments(ADMIN_REVIEW, {"contract_id": world["contract"]["id"]})
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_08_one_cent_over_the_ceiling_and_one_cent_under_the_floor_differ(self, api):
        """PRD §3.8: "The boundary is inclusive: a `new_unit_price_cents` exactly equal to
        `price_ceiling_cents` is allowed, and one cent above it is
        `ERR_PRICE_ESCALATION_EXCEEDS_CAP`." PRD §3.8: "A `new_unit_price_cents` below the
        target line's `price_floor_cents` is `ERR_PRICE_BELOW_FLOOR`."

        Design: Corner/Calculations/escalation_ceiling_takes_the_three_way_minimum_of_contract_index_and_request
        """
        world = _price_world(api)
        validate_success(_propose_price(api, world, 13000, "CPI_U", 0.0450), 201)

        over_cap = _propose_price(api, world, 13001, "CPI_U", 0.0450)
        under_floor = _propose_price(api, world, 8999, "PPI_COMMODITY", 0.0800)

        validate_error(over_cap, ApiErrorId.ERR_PRICE_ESCALATION_EXCEEDS_CAP, 422)
        validate_error(under_floor, ApiErrorId.ERR_PRICE_BELOW_FLOOR, 422)
        line = read_line_item(api, world["lines"][world["sku"]]["id"])
        assert_cents(line["base_unit_price_cents"], 12500, "base_unit_price_cents")
        assert line["price_change_count"] == 0
        assert line["last_price_change_at"] is None


class TestReportSweepInputSet:
    def test_09_only_the_confirmed_order_enters_the_sweep(self, api):
        """PRD §3.7: "Submission gathers the orders the report covers: every order on the
        report's own `contract_id` whose `status` is `CONFIRMED`, whose `ordered_at` lies inside
        the closed period with both endpoints inclusive, and whose `usage_report_id` is either
        null or already this report's own id." PRD §3.7: "Orders still in `RECORDED` are never
        swept, because the member has not confirmed receipt, and `RETRACTED` orders are removed
        from a sweep by the retraction cascade." PRD §3.7: "`reported_fee_cents` is
        `reported_chargeable_cents` multiplied by the contract's `admin_fee_rate_bps` and
        divided by 10,000, rounded half up to a whole cent."

        Design: Corner/Calculations/report_sweep_claims_confirmed_usages_only_and_ignores_recorded_and_retracted_rows
        """
        world = _sweep_world(api)

        submitted = submit_report(api, world, world["report"]["id"])

        assert submitted["status"] == "SUBMITTED"
        assert submitted["swept_usage_count"] == 1
        assert_cents(submitted["reported_chargeable_cents"], 9015, "reported_chargeable_cents")
        assert_cents(submitted["reported_usage_cents"], 9195, "reported_usage_cents")
        assert_cents(submitted["reported_fee_cents"], 180, "reported_fee_cents")
        assert submitted["fee_status"] == "NOT_DUE"
        assert submitted["audited_fee_cents"] is None

    def test_10_the_unswept_orders_keep_their_status_and_take_no_stamp(self, api):
        """PRD §3.7: "Every swept order has its `usage_report_id` stamped with this report's
        id."

        Design: Corner/Calculations/report_sweep_claims_confirmed_usages_only_and_ignores_recorded_and_retracted_rows
        """
        world = _sweep_world(api)

        submitted = submit_report(api, world, world["report"]["id"])

        swept = read_usage(api, world["confirmed"]["id"])
        assert swept["usage_report_id"] == submitted["id"]
        assert swept["status"] == "CONFIRMED"
        recorded = read_usage(api, world["recorded"]["id"])
        assert recorded["status"] == "RECORDED"
        assert recorded["usage_report_id"] is None
        retracted = read_usage(api, world["retracted"]["id"])
        assert retracted["status"] == "RETRACTED"
        assert retracted["usage_report_id"] is None

    def test_11_the_ledgers_still_hold_the_two_live_orders_and_no_fee_yet(self, api):
        """PRD §3.6: "Afterwards the committed-spend arithmetic must balance exactly: the
        member's `committed_spend_cents` equals the sum of `total_cents` over its `RECORDED` and
        `CONFIRMED` orders and nothing else." PRD §3.7: "`ACCEPT` moves `SUBMITTED → ACCEPTED`,
        stamps `accepted_at` with the current logical instant, sets `fee_due_at` to thirty days
        after `accepted_at`, moves the parallel `fee_status` from `NOT_DUE` to `DUE`, and adds
        `reported_fee_cents` to both the contract's and the supplier's `fee_assessed_cents_total`
        before recomputing the contract's `fee_outstanding_cents`."

        Design: Corner/Calculations/report_sweep_claims_confirmed_usages_only_and_ignores_recorded_and_retracted_rows
        """
        world = _sweep_world(api)

        submit_report(api, world, world["report"]["id"])

        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            18390,
            "committed_spend_cents",
        )
        contract = read_contract(api, world["contract"]["id"])
        assert_cents(
            contract["usage_chargeable_cents_total"], 18030, "usage_chargeable_cents_total"
        )
        assert_cents(contract["fee_assessed_cents_total"], 0, "fee_assessed_cents_total")
        assert_cents(contract["fee_outstanding_cents"], 0, "fee_outstanding_cents")
