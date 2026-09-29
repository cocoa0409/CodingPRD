"""State machine contracts: initial states, legal walks, refusals and fan-out."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_PIGGYBACK,
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_member_headers,
    make_supplier_headers,
)
from test_helpers.constants import (
    BASE_TERM_END,
    BASE_TERM_START,
    CLOCK_AFTER_RESPONSE_DUE,
    CLOCK_REGISTRY,
    CLOCK_TERM_END,
    CLOCK_TERM_START,
    SKU_CART,
    SKU_DISPENSER,
)
from test_helpers.factories import (
    CART_LINE,
    DISPENSER_LINE,
    TX_RULE,
    contract_usage_payload,
    solicitation_payload,
    solicitation_response_payload,
)
from test_helpers.fixtures import (
    add_line_item,
    create_member,
    determine_analysis,
    file_complaint,
    file_response,
    open_analysis,
    open_report,
    read_analysis,
    read_contract,
    read_line_item,
    read_member,
    read_response,
    read_solicitation,
    read_supplier,
    read_usage,
    record_usage,
    register_qualified_supplier,
    register_supplier,
    retract_usage,
    seed_state_law_rules,
    set_clock,
    setup_active_contract,
    setup_active_member,
    setup_authorised_member,
    setup_awarded_solicitation,
    setup_evaluated_solicitation,
    setup_pending_contract,
    setup_posted_solicitation,
)
from test_helpers.test_users import (
    OFFICER_AWARDER,
    OFFICER_AWARDER_ID,
    OFFICER_CONDUCTOR,
    OFFICER_CONDUCTOR_ID,
)

AUSTIN = dict(
    legal_name="City of Austin",
    state_code="TX",
    member_category="CITY",
    annual_spend_ceiling_cents=5000000,
    governing_body_resolution_number="RES-2026-208",
)
REQUIRED_DOC_ORDER = [
    "NOTICE_OF_SOLICITATION",
    "SPECIFICATION_PACKAGE",
    "PROCUREMENT_METHOD_JUSTIFICATION",
    "ADDENDA_LOG",
    "RESPONSE_TABULATION",
    "EVALUATION_SCORESHEET",
    "AWARD_RECOMMENDATION",
    "CONTRACT_EXECUTION",
]


def _posted_with_two_responses(api):
    """A POSTED solicitation carrying two SUBMITTED responses past the deadline."""
    world = setup_posted_solicitation(api)
    sol_id = world["solicitation"]["id"]
    world["response_a"] = file_response(api, sol_id, world["supplier_a"])
    world["response_b"] = file_response(
        api, sol_id, world["supplier_b"], proposed_annual_value_cents=1250000
    )
    set_clock(api, CLOCK_AFTER_RESPONSE_DUE)
    return world


def _assemble(api, world, headers=OFFICER_CONDUCTOR):
    return validate_success(
        api.solicitation_audit_package(
            world["solicitation"]["id"], {"action": "ASSEMBLE"}, headers
        )
    )


def _order(api, world, member, analysis, sku=SKU_DISPENSER, quantity=1):
    return api.create_contract_usage(
        contract_usage_payload(
            world["contract"]["id"],
            member["id"],
            world["lines"][sku]["id"],
            analysis["id"],
            quantity=quantity,
        ),
        make_member_headers(member["id"]),
    )


class TestInitialStates:
    def test_01_the_registry_rows_land_on_their_declared_initial_state(self, api):
        """PRD §3.1: "A newly registered supplier starts `UNQUALIFIED` with a pristine record:
        `performance_score` 100.00, `deduction_points_total` 0.00, `performance_tier`
        `PREFERRED`, `substantiated_complaint_count` 0, `delinquent_report_count` 0, and
        `fee_assessed_cents_total` and `fee_remitted_cents_total` both 0." PRD §3.2: "A new
        solicitation lands in `status` `DRAFT` and `audit_package_status` `NOT_ASSEMBLED`, with
        `addenda_count` and `responsive_response_count` both 0 and `posted_at`, `notice_days`
        and `audit_completeness_pct` all null." PRD §3.4: "A new member starts in
        `registration_status` `PENDING_VERIFICATION` with `committed_spend_cents` 0,
        `docs_request_count` 0, and `verified_at` and `verified_by_user_id` null."

        Design: Corner/State Machines/freshly_created_rows_sit_on_the_declared_initial_state_of_every_dimension
        """
        set_clock(api, CLOCK_REGISTRY)
        seed_state_law_rules(api)

        supplier = register_supplier(api, legal_name="Cedar Supply Co", home_state_code="TX")
        solicitation = validate_success(
            api.create_solicitation(solicitation_payload(), OFFICER_CONDUCTOR), 201
        )
        member = create_member(api, **AUSTIN)

        assert supplier["qualification_status"] == "UNQUALIFIED"
        assert_score(supplier["performance_score"], 100.00, "performance_score")
        assert_score(supplier["deduction_points_total"], 0.00, "deduction_points_total")
        assert supplier["performance_tier"] == "PREFERRED"
        assert supplier["substantiated_complaint_count"] == 0
        assert supplier["delinquent_report_count"] == 0
        assert_cents(supplier["fee_assessed_cents_total"], 0, "fee_assessed_cents_total")
        assert_cents(supplier["fee_remitted_cents_total"], 0, "fee_remitted_cents_total")
        assert solicitation["status"] == "DRAFT"
        assert solicitation["audit_package_status"] == "NOT_ASSEMBLED"
        assert solicitation["addenda_count"] == 0
        assert solicitation["responsive_response_count"] == 0
        assert solicitation["posted_at"] is None
        assert solicitation["notice_days"] is None
        assert solicitation["audit_completeness_pct"] is None
        assert member["registration_status"] == "PENDING_VERIFICATION"
        assert_cents(member["committed_spend_cents"], 0, "committed_spend_cents")
        assert member["docs_request_count"] == 0
        assert member["verified_at"] is None
        assert member["verified_by_user_id"] is None

    def test_02_the_award_writes_both_contract_dimensions_and_the_price_sheet(self, api):
        """PRD §3.3: "A new contract starts in `status` `PENDING_EXECUTION` with
        `compliance_posture` `COMPLIANT`, `current_term_end` initialised to `base_term_end`,
        `renewals_used` 0, and every ledger total — `usage_chargeable_cents_total`,
        `fee_assessed_cents_total`, `fee_remitted_cents_total`, `fee_outstanding_cents` and
        `delinquent_report_count` — at 0." PRD §3.3: "A published line starts with `origin`
        `AWARD`, `status` `ACTIVE`, `price_change_count` 0, `last_price_change_at` null, and
        `price_effective_from` initialised to the contract's `base_term_start`."

        Design: Corner/State Machines/freshly_created_rows_sit_on_the_declared_initial_state_of_every_dimension
        """
        world = setup_pending_contract(api)

        contract = world["contract"]
        line = world["lines"][SKU_DISPENSER]

        assert contract["status"] == "PENDING_EXECUTION"
        assert contract["compliance_posture"] == "COMPLIANT"
        assert_instant(contract["current_term_end"], BASE_TERM_END, "current_term_end")
        assert contract["renewals_used"] == 0
        assert_cents(contract["usage_chargeable_cents_total"], 0, "usage_chargeable_cents_total")
        assert_cents(contract["fee_assessed_cents_total"], 0, "fee_assessed_cents_total")
        assert_cents(contract["fee_remitted_cents_total"], 0, "fee_remitted_cents_total")
        assert_cents(contract["fee_outstanding_cents"], 0, "fee_outstanding_cents")
        assert contract["delinquent_report_count"] == 0
        assert line["origin"] == "AWARD"
        assert line["status"] == "ACTIVE"
        assert line["price_change_count"] == 0
        assert line["last_price_change_at"] is None
        assert_instant(line["price_effective_from"], BASE_TERM_START, "price_effective_from")

    def test_03_the_three_child_rows_of_a_contract_open_on_their_own_initial_state(self, api):
        """PRD §3.5: "The new row starts in `status` `PENDING` with `determination`,
        `doctrine_applied`, `authority_score`, `determined_at` and `expires_on` all null,
        `deduction_detail` empty and `local_waiver_required` false." PRD §3.7: "A new report
        starts in `status` `DRAFT` with `fee_status` `NOT_DUE`, every figure at 0, and
        `audited_fee_cents`, `fee_true_up_cents`, `variance_pct`, `accepted_at` and `fee_due_at`
        null." PRD §3.9: "A new complaint starts in `status` `INTAKE` with `points_reversed`
        false and `deduction_points`, `investigator_user_id`, `adjudicator_user_id`,
        `substantiated_at`, `appeal_filed_at` and `appeal_deadline_at` all null."

        Design: Corner/State Machines/freshly_created_rows_sit_on_the_declared_initial_state_of_every_dimension
        """
        world = setup_pending_contract(api)
        member = create_member(api, **AUSTIN)

        analysis = open_analysis(api, member["id"], world["contract"]["id"])
        report = open_report(api, world)
        complaint = file_complaint(api, world["contract"]["id"], member["id"])

        assert analysis["status"] == "PENDING"
        assert analysis["determination"] is None
        assert analysis["doctrine_applied"] is None
        assert analysis["authority_score"] is None
        assert analysis["determined_at"] is None
        assert analysis["expires_on"] is None
        assert analysis["deduction_detail"] == []
        assert analysis["local_waiver_required"] is False
        assert report["status"] == "DRAFT"
        assert report["fee_status"] == "NOT_DUE"
        assert report["swept_usage_count"] == 0
        assert_cents(report["remitted_cents"], 0, "remitted_cents")
        assert report["audited_fee_cents"] is None
        assert report["fee_true_up_cents"] is None
        assert report["variance_pct"] is None
        assert report["accepted_at"] is None
        assert report["fee_due_at"] is None
        assert complaint["status"] == "INTAKE"
        assert complaint["points_reversed"] is False
        assert complaint["deduction_points"] is None
        assert complaint["investigator_user_id"] is None
        assert complaint["adjudicator_user_id"] is None
        assert complaint["substantiated_at"] is None
        assert complaint["appeal_filed_at"] is None
        assert complaint["appeal_deadline_at"] is None


class TestTheLegalWalk:
    def test_04_each_hop_of_the_competitive_walk_writes_its_own_artefact(self, api):
        """PRD §3.2: "`OPEN_EVALUATION` moves `POSTED → EVALUATION` and requires the logical
        clock to have reached or passed `response_due_at`; attempting it earlier is
        `ERR_RESPONSE_WINDOW_OPEN`." PRD §3.2: "A new response starts in `SUBMITTED` with
        `info_request_rounds` 0 and every score null." PRD §3.2: "It stores `technical_score`
        and increments the solicitation's `responsive_response_count` by 1."

        Design: Corner/State Machines/solicitation_walks_draft_to_awarded_writing_each_transitions_own_side_effects
        """
        world = setup_evaluated_solicitation(api)

        assert world["solicitation"]["status"] == "EVALUATION"
        assert_instant(world["solicitation"]["posted_at"], CLOCK_REGISTRY, "posted_at")
        assert world["solicitation"]["notice_days"] == 21
        assert world["response_a"]["status"] == "SUBMITTED"
        assert world["response_a"]["info_request_rounds"] == 0
        assert world["response_a"]["technical_score"] is None
        assert world["response_a"]["price_score"] is None
        assert world["response_a"]["composite_score"] is None
        assert world["response_a"]["award_rank"] is None
        first = validate_success(
            api.response_review(
                world["response_a"]["id"],
                {"action": "MARK_RESPONSIVE", "technical_score": 88.00},
                OFFICER_CONDUCTOR,
            )
        )
        assert first["status"] == "RESPONSIVE"
        assert_score(first["technical_score"], 88.00, "technical_score")
        assert read_solicitation(api, world["solicitation"]["id"])[
            "responsive_response_count"
        ] == 1
        second = validate_success(
            api.response_review(
                world["response_b"]["id"],
                {"action": "MARK_RESPONSIVE", "technical_score": 95.00},
                OFFICER_CONDUCTOR,
            )
        )
        assert second["status"] == "RESPONSIVE"
        solicitation = read_solicitation(api, world["solicitation"]["id"])
        assert solicitation["responsive_response_count"] == 2
        assert solicitation["audit_package_status"] == "NOT_ASSEMBLED"
        assert solicitation["notice_days"] == 21

    def test_05_recommendation_scores_the_field_and_a_second_officer_awards_it(self, api):
        """PRD §3.2: "It then scores the whole responsive field and stamps
        `recommended_by_user_id` with the acting `X-User-ID`." PRD §3.2: "`composite_score` is
        the sum of those two *already-rounded* components, rounded half up to two decimals."
        PRD §3.2: "Finally rank the same responsive set by `composite_score` descending,
        breaking ties by `created_at` ascending and never by `id`, and write `award_rank` as 1
        through N." PRD §3.2: "On success it stamps `awarded_by_user_id` and unlocks
        master-contract creation for that rank-1 supplier's `supplier_id`."

        Design: Corner/State Machines/solicitation_walks_draft_to_awarded_writing_each_transitions_own_side_effects
        """
        world = setup_awarded_solicitation(api)

        first = read_response(api, world["response_a"]["id"])
        second = read_response(api, world["response_b"]["id"])

        assert_score(first["price_score"], 100.00, "price_score")
        assert_score(second["price_score"], 80.00, "price_score")
        assert_score(first["composite_score"], 92.80, "composite_score")
        assert_score(second["composite_score"], 89.00, "composite_score")
        assert first["award_rank"] == 1
        assert second["award_rank"] == 2
        solicitation = world["solicitation"]
        assert solicitation["status"] == "AWARDED"
        assert solicitation["recommended_by_user_id"] == OFFICER_CONDUCTOR_ID
        assert solicitation["awarded_by_user_id"] == OFFICER_AWARDER_ID
        assert solicitation["notice_days"] == 21
        assert solicitation["audit_package_status"] == "NOT_ASSEMBLED"

    def test_06_execution_refuses_an_empty_price_sheet_and_then_a_spent_term(self, api):
        """PRD §2.9: "Execution requires at least one active price-sheet line —
        `ERR_NO_ACTIVE_LINE_ITEMS`, 409, on `POST /coop/master-contracts/{id}/award-status`."
        PRD §2.9: "The `MasterContract` is in a from-state permitting the requested
        award-status action, with the additional clock conditions for `EXECUTE` and `EXPIRE` —
        `ERR_CONTRACT_INVALID_STATE`, 409, on `POST
        /coop/master-contracts/{id}/award-status`."

        Design: Corner/State Machines/execute_enforces_the_line_item_precondition_then_the_term_window_precondition
        """
        world = setup_pending_contract(api, lines=())
        contract_id = world["contract"]["id"]

        bare = api.contract_award_status(contract_id, {"action": "EXECUTE"}, ADMIN_REVIEW)

        validate_error(bare, ApiErrorId.ERR_NO_ACTIVE_LINE_ITEMS, 409)
        assert read_contract(api, contract_id)["status"] == "PENDING_EXECUTION"
        line = add_line_item(api, contract_id, DISPENSER_LINE)
        set_clock(api, CLOCK_TERM_END)
        expired = api.contract_award_status(contract_id, {"action": "EXECUTE"}, ADMIN_REVIEW)
        validate_error(expired, ApiErrorId.ERR_CONTRACT_INVALID_STATE, 409)
        assert read_contract(api, contract_id)["status"] == "PENDING_EXECUTION"
        assert read_line_item(api, line["id"])["status"] == "ACTIVE"

    def test_07_execution_inside_the_window_activates_the_whole_price_sheet(self, api):
        """PRD §3.3: "`EXECUTE` moves `PENDING_EXECUTION → ACTIVE` and requires the supplier
        to be `QUALIFIED`, the solicitation to be `AWARDED`, at least one `ACTIVE` line on the
        price sheet (otherwise `ERR_NO_ACTIVE_LINE_ITEMS`), and the logical clock to be
        strictly before `base_term_end`; it sets `price_effective_from` to `base_term_start` on
        every `ACTIVE` line and sets `current_term_end` to `base_term_end` if that field is
        still null."

        Design: Corner/State Machines/execute_enforces_the_line_item_precondition_then_the_term_window_precondition
        """
        world = setup_pending_contract(api, lines=())
        contract_id = world["contract"]["id"]
        line = add_line_item(api, contract_id, DISPENSER_LINE)
        set_clock(api, CLOCK_TERM_END)
        validate_error(
            api.contract_award_status(contract_id, {"action": "EXECUTE"}, ADMIN_REVIEW),
            ApiErrorId.ERR_CONTRACT_INVALID_STATE,
            409,
        )
        set_clock(api, CLOCK_TERM_START)

        executed = validate_success(
            api.contract_award_status(contract_id, {"action": "EXECUTE"}, ADMIN_REVIEW)
        )

        assert executed["status"] == "ACTIVE"
        assert executed["compliance_posture"] == "COMPLIANT"
        assert_instant(executed["current_term_end"], BASE_TERM_END, "current_term_end")
        stored = read_line_item(api, line["id"])
        assert stored["status"] == "ACTIVE"
        assert_instant(stored["price_effective_from"], BASE_TERM_START, "price_effective_from")


class TestRefusedTransitions:
    def test_08_from_draft_every_action_but_posting_is_refused(self, api):
        """PRD §2.9: "The `Solicitation` is in a from-state permitting the requested lifecycle
        or audit-package action, and responses may only be created while its `status` is
        `POSTED` — `ERR_SOLICITATION_INVALID_STATE`, `ERR_SOLICITATION_CLOSED_FOR_RESPONSES` or
        `ERR_AUDIT_PACKAGE_NOT_ASSEMBLED`, 409, on `POST /coop/solicitations/{id}/lifecycle`,
        `POST /coop/solicitations/{id}/audit-package` and `POST
        /coop/solicitation-responses`."

        Design: Corner/State Machines/transitions_absent_from_the_draft_row_of_the_table_are_all_refused
        """
        set_clock(api, CLOCK_REGISTRY)
        seed_state_law_rules(api, rules=(TX_RULE,))
        supplier = register_qualified_supplier(api)
        drafted = validate_success(
            api.create_solicitation(solicitation_payload(), OFFICER_CONDUCTOR), 201
        )

        for action in ("OPEN_EVALUATION", "RECOMMEND_AWARD"):
            validate_error(
                api.solicitation_lifecycle(drafted["id"], {"action": action}, OFFICER_CONDUCTOR),
                ApiErrorId.ERR_SOLICITATION_INVALID_STATE,
                409,
            )
        validate_error(
            api.solicitation_lifecycle(drafted["id"], {"action": "AWARD"}, OFFICER_AWARDER),
            ApiErrorId.ERR_SOLICITATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.create_solicitation_response(
                solicitation_response_payload(drafted["id"], supplier["id"]),
                make_supplier_headers(supplier["id"]),
            ),
            ApiErrorId.ERR_SOLICITATION_CLOSED_FOR_RESPONSES,
            409,
        )
        validate_error(
            api.solicitation_audit_package(
                drafted["id"], {"action": "CERTIFY"}, OFFICER_AWARDER
            ),
            ApiErrorId.ERR_AUDIT_PACKAGE_NOT_ASSEMBLED,
            409,
        )
        solicitation = read_solicitation(api, drafted["id"])
        assert solicitation["status"] == "DRAFT"
        assert solicitation["audit_package_status"] == "NOT_ASSEMBLED"
        assert solicitation["posted_at"] is None
        assert solicitation["notice_days"] is None
        assert solicitation["recommended_by_user_id"] is None
        assert solicitation["awarded_by_user_id"] is None
        _, responses = validate_paginated(
            api.list_responses_of_solicitation(drafted["id"], ADMIN_REVIEW)
        )
        assert responses["total_count"] == 0

    def test_09_a_retracted_order_and_a_terminated_member_refuse_revival(self, api):
        """PRD §3.6: "A disposition that is not a declared transition out of the order's
        current status is `ERR_USAGE_INVALID_STATE`. `RETRACTED` is terminal." PRD §3.4:
        "`TERMINATE` is reachable from `PENDING_VERIFICATION`, `DOCS_REQUESTED`, `ACTIVE` and
        `SUSPENDED`, and voids every analysis of this member whose `status` is `PENDING` *or*
        `DETERMINED` with `voided_reason` `MEMBER_TERMINATED` — a wider net than suspension,
        which touches only determined opinions." PRD §3.4: "A registration action that is not a
        declared transition is `ERR_MEMBER_INVALID_STATE`; an operation that requires a
        verified member and finds one that is not `ACTIVE` is `ERR_MEMBER_NOT_ACTIVE`."

        Design: Corner/State Machines/terminal_rows_refuse_every_further_action_on_their_own_dimension
        """
        world = setup_active_contract(api)
        member, analysis = setup_authorised_member(api, world)
        usage = record_usage(
            api,
            world["contract"]["id"],
            member["id"],
            world["lines"][SKU_DISPENSER]["id"],
            analysis["id"],
        )
        retract_usage(api, usage)
        terminated = validate_success(
            api.member_registration(
                member["id"],
                {"action": "TERMINATE", "note": "member left the cooperative"},
                ADMIN_REVIEW,
            )
        )

        member_headers = make_member_headers(member["id"])
        for action in ("CONFIRM", "RETRACT"):
            validate_error(
                api.usage_disposition(usage["id"], {"action": action}, member_headers),
                ApiErrorId.ERR_USAGE_INVALID_STATE,
                409,
            )
        for action in ("REINSTATE", "VERIFY"):
            validate_error(
                api.member_registration(member["id"], {"action": action}, ADMIN_REVIEW),
                ApiErrorId.ERR_MEMBER_INVALID_STATE,
                409,
            )
        assert terminated["registration_status"] == "TERMINATED"
        stored_usage = read_usage(api, usage["id"])
        assert stored_usage["status"] == "RETRACTED"
        assert_instant(stored_usage["retracted_at"], CLOCK_TERM_START, "retracted_at")
        stored_member = read_member(api, member["id"])
        assert stored_member["registration_status"] == "TERMINATED"
        assert_cents(stored_member["committed_spend_cents"], 0, "committed_spend_cents")
        stored_analysis = read_analysis(api, analysis["id"])
        assert stored_analysis["status"] == "VOIDED"
        assert stored_analysis["voided_reason"] == "MEMBER_TERMINATED"
        assert stored_analysis["determination"] == "CONDITIONAL"
        assert_cents(
            read_contract(api, world["contract"]["id"])["usage_chargeable_cents_total"],
            0,
            "usage_chargeable_cents_total",
        )

    def test_10_a_superseded_opinion_refuses_a_later_determination(self, api):
        """PRD §3.5: "Opening one is a supersession event: any prior analysis for the same
        member-and-contract pair whose `status` is `PENDING` or `DETERMINED` becomes `VOIDED`
        with `voided_reason` `SUPERSEDED_BY_NEWER_ANALYSIS`, and the member's own `version`
        increments." PRD §3.5: "An action that is not a declared transition is
        `ERR_ANALYSIS_INVALID_STATE`."

        Design: Corner/State Machines/terminal_rows_refuse_every_further_action_on_their_own_dimension
        """
        world = setup_active_contract(api)
        member = setup_active_member(api)
        first = open_analysis(api, member["id"], world["contract"]["id"])
        determine_analysis(api, first["id"])

        second = open_analysis(api, member["id"], world["contract"]["id"])

        superseded = read_analysis(api, first["id"])
        assert superseded["status"] == "VOIDED"
        assert superseded["voided_reason"] == "SUPERSEDED_BY_NEWER_ANALYSIS"
        assert superseded["determination"] == "CONDITIONAL"
        assert_score(superseded["authority_score"], 70.00, "authority_score")
        validate_error(
            api.analysis_determination(first["id"], {"action": "DETERMINE"}, ADMIN_PIGGYBACK),
            ApiErrorId.ERR_ANALYSIS_INVALID_STATE,
            409,
        )
        assert read_analysis(api, first["id"])["status"] == "VOIDED"
        assert second["status"] == "PENDING"
        assert determine_analysis(api, second["id"])["status"] == "DETERMINED"

    def test_11_replaying_an_applied_transition_is_refused_and_writes_nothing_twice(self, api):
        """PRD §3.1: "An action that is not a declared transition out of the supplier's current
        standing is `ERR_SUPPLIER_INVALID_STATE`, and a `REINSTATE` blocked by a `PROBATION`
        tier carries the same code." PRD §3.3: "An award-status action that is not a declared
        transition — including an `EXECUTE` past `base_term_end` or an `EXPIRE` before
        `current_term_end` — is `ERR_CONTRACT_INVALID_STATE`." PRD §3.2: "Any lifecycle action
        that is not a declared transition out of the current `status` is
        `ERR_SOLICITATION_INVALID_STATE`."

        Design: Corner/State Machines/replaying_an_already_applied_transition_is_refused_rather_than_silently_absorbed
        """
        world = setup_active_contract(api)

        validate_error(
            api.supplier_qualification(
                world["supplier_a"]["id"], {"action": "QUALIFY"}, ADMIN_REVIEW
            ),
            ApiErrorId.ERR_SUPPLIER_INVALID_STATE,
            409,
        )
        validate_error(
            api.contract_award_status(
                world["contract"]["id"], {"action": "EXECUTE"}, ADMIN_REVIEW
            ),
            ApiErrorId.ERR_CONTRACT_INVALID_STATE,
            409,
        )
        validate_error(
            api.solicitation_lifecycle(
                world["solicitation"]["id"], {"action": "AWARD"}, OFFICER_AWARDER
            ),
            ApiErrorId.ERR_SOLICITATION_INVALID_STATE,
            409,
        )

        assert read_supplier(api, world["supplier_a"]["id"])["qualification_status"] == "QUALIFIED"
        contract = read_contract(api, world["contract"]["id"])
        assert contract["status"] == "ACTIVE"
        assert_instant(contract["current_term_end"], BASE_TERM_END, "current_term_end")
        line = read_line_item(api, world["lines"][SKU_DISPENSER]["id"])
        assert_instant(line["price_effective_from"], BASE_TERM_START, "price_effective_from")
        assert line["price_change_count"] == 0
        solicitation = read_solicitation(api, world["solicitation"]["id"])
        assert solicitation["status"] == "AWARDED"
        assert solicitation["awarded_by_user_id"] == OFFICER_AWARDER_ID
        assert solicitation["responsive_response_count"] == 2


class TestFanOutAndCycles:
    def test_12_termination_withdraws_every_line_and_voids_every_opinion(self, api):
        """PRD §3.3: "`TERMINATE` is reachable from `PENDING_EXECUTION`, `ACTIVE` and
        `SUSPENDED`; in every case it sets every line item of the contract to `WITHDRAWN`, and
        from `ACTIVE` or `SUSPENDED` it additionally voids the contract's `DETERMINED` opinions
        with `voided_reason` `CONTRACT_TERMINATED`." PRD §2.9: "The `MasterContract` the
        operation depends on is `ACTIVE` — `ERR_CONTRACT_NOT_ACTIVE`, 409, on `POST
        /coop/contract-usages`, `POST /coop/piggyback-analyses/{id}/determination`, `POST
        /coop/contract-amendments` and `POST /coop/contract-amendments/{id}/decision`."

        Design: Corner/State Machines/contract_termination_withdraws_every_line_and_voids_every_determined_analysis
        """
        world = setup_active_contract(api, lines=(DISPENSER_LINE, CART_LINE))
        riverside, riverside_analysis = setup_authorised_member(api, world)
        austin, austin_analysis = setup_authorised_member(api, world, **AUSTIN)

        terminated = validate_success(
            api.contract_award_status(
                world["contract"]["id"],
                {"action": "TERMINATE", "note": "supplier withdrew from the cooperative"},
                ADMIN_REVIEW,
            )
        )

        assert terminated["status"] == "TERMINATED"
        assert read_line_item(api, world["lines"][SKU_DISPENSER]["id"])["status"] == "WITHDRAWN"
        assert read_line_item(api, world["lines"][SKU_CART]["id"])["status"] == "WITHDRAWN"
        for opinion in (riverside_analysis, austin_analysis):
            stored = read_analysis(api, opinion["id"])
            assert stored["status"] == "VOIDED"
            assert stored["voided_reason"] == "CONTRACT_TERMINATED"
        assert read_supplier(api, world["contract"]["supplier_id"])["qualification_status"] == (
            "QUALIFIED"
        )
        assert read_member(api, riverside["id"])["registration_status"] == "ACTIVE"
        assert read_member(api, austin["id"])["registration_status"] == "ACTIVE"
        validate_error(
            _order(api, world, austin, austin_analysis),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
            409,
        )
        assert_cents(
            read_member(api, austin["id"])["committed_spend_cents"], 0, "committed_spend_cents"
        )

    def test_13_the_clarification_budget_is_spent_by_resubmission_not_by_the_request(self, api):
        """PRD §3.2: "The officer's `REQUEST_INFO` moves `SUBMITTED → INFO_REQUESTED`, requires
        the parent solicitation to be in `EVALUATION` and `info_request_rounds` to be strictly
        below two, and stores the `responsiveness_note`; exhausting the allowance is
        `ERR_INFO_REQUEST_ROUNDS_EXHAUSTED`." PRD §3.2: "The supplier's own `RESUBMIT` closes
        the cycle `INFO_REQUESTED → SUBMITTED`, again requires the solicitation to be in
        `EVALUATION`, requires the acting `X-User-ID` to be the response's own `supplier_id`,
        and increments `info_request_rounds` by 1 — so the `SUBMITTED → INFO_REQUESTED →
        SUBMITTED` loop can run at most twice." PRD §3.2: "Any action that is not a declared
        transition out of the response's current status is `ERR_RESPONSE_INVALID_STATE`."

        Design: Corner/State Machines/request_info_and_resubmit_cycle_twice_then_the_round_budget_is_spent
        """
        world = setup_evaluated_solicitation(api)
        response_id = world["response_a"]["id"]
        supplier_headers = make_supplier_headers(world["supplier_a"]["id"])

        first_request = validate_success(
            api.response_review(
                response_id,
                {"action": "REQUEST_INFO", "responsiveness_note": "clarify freight terms"},
                OFFICER_CONDUCTOR,
            )
        )
        first_resubmit = validate_success(
            api.response_submission(
                response_id,
                {"action": "RESUBMIT", "responsiveness_note": "freight is prepaid and added"},
                supplier_headers,
            )
        )
        second_request = validate_success(
            api.response_review(
                response_id,
                {"action": "REQUEST_INFO", "responsiveness_note": "clarify inside delivery"},
                OFFICER_CONDUCTOR,
            )
        )
        second_resubmit = validate_success(
            api.response_submission(
                response_id,
                {"action": "RESUBMIT", "responsiveness_note": "inside delivery is per stop"},
                supplier_headers,
            )
        )

        assert first_request["status"] == "INFO_REQUESTED"
        assert first_request["info_request_rounds"] == 0
        assert first_resubmit["status"] == "SUBMITTED"
        assert first_resubmit["info_request_rounds"] == 1
        assert second_request["status"] == "INFO_REQUESTED"
        assert second_request["info_request_rounds"] == 1
        assert second_resubmit["status"] == "SUBMITTED"
        assert second_resubmit["info_request_rounds"] == 2
        validate_error(
            api.response_review(
                response_id,
                {"action": "REQUEST_INFO", "responsiveness_note": "clarify training hours"},
                OFFICER_CONDUCTOR,
            ),
            ApiErrorId.ERR_INFO_REQUEST_ROUNDS_EXHAUSTED,
            409,
        )
        validate_error(
            api.response_submission(response_id, {"action": "RESUBMIT"}, supplier_headers),
            ApiErrorId.ERR_RESPONSE_INVALID_STATE,
            409,
        )
        stored = read_response(api, response_id)
        assert stored["status"] == "SUBMITTED"
        assert stored["info_request_rounds"] == 2
        assert stored["technical_score"] is None
        assert read_solicitation(api, world["solicitation"]["id"])[
            "responsive_response_count"
        ] == 0
        assert read_response(api, world["response_b"]["id"])["info_request_rounds"] == 0


class TestAuditPackageDimension:
    def test_14_assembly_writes_the_eight_code_denominator_and_lands_on_fifty(self, api):
        """PRD §3.2: "The required list is a fixed eight-code base, in exactly this order:
        `NOTICE_OF_SOLICITATION`, `SPECIFICATION_PACKAGE`, `PROCUREMENT_METHOD_JUSTIFICATION`,
        `ADDENDA_LOG`, `RESPONSE_TABULATION`, `EVALUATION_SCORESHEET`, `AWARD_RECOMMENDATION`,
        `CONTRACT_EXECUTION`." PRD §3.2: "A solicitation with no responsive responses at all
        therefore loses exactly the four response-dependent codes against an eight-code
        denominator and lands on 50.00."

        Design: Corner/State Machines/audit_package_goes_stale_on_a_solicitation_status_change_and_is_rebuilt_by_reassembly
        """
        world = _posted_with_two_responses(api)

        assembled = _assemble(api, world)

        assert assembled["audit_package_status"] == "ASSEMBLED"
        assert assembled["audit_required_doc_codes"] == REQUIRED_DOC_ORDER
        assert "AMENDMENT_LOG" not in assembled["audit_required_doc_codes"]
        assert assembled["audit_present_doc_codes"] == [
            "NOTICE_OF_SOLICITATION",
            "SPECIFICATION_PACKAGE",
            "PROCUREMENT_METHOD_JUSTIFICATION",
            "ADDENDA_LOG",
        ]
        assert_score(assembled["audit_completeness_pct"], 50.00, "audit_completeness_pct")
        assert assembled["addenda_count"] == 0
        assert assembled["status"] == "POSTED"
        assert assembled["responsive_response_count"] == 0

    def test_15_a_lifecycle_change_makes_the_package_stale_until_it_is_rebuilt(self, api):
        """PRD §3.2: "Whenever an amendment on this solicitation's master contract is approved,
        or whenever the competitive `status` changes, an `ASSEMBLED` package becomes `STALE` and
        `audit_completeness_pct` is cleared to null so the stale figure cannot be cited; a
        `CERTIFIED` package likewise becomes `STALE` with `audit_completeness_pct` cleared *and*
        `certified_at` and `certified_by_user_id` cleared, so certification must be performed
        again from scratch." PRD §3.2: "Requesting certification while the package is
        `NOT_ASSEMBLED` or `STALE` is `ERR_AUDIT_PACKAGE_NOT_ASSEMBLED`." PRD §3.2: "`ASSEMBLE`
        is reachable from `NOT_ASSEMBLED`, from `ASSEMBLED` (re-assembly is legal and idempotent
        in shape though not in value — the recomputed percentage may differ) and from `STALE`;
        in all three cases it requires `posted_at` to be non-null."

        Design: Corner/State Machines/audit_package_goes_stale_on_a_solicitation_status_change_and_is_rebuilt_by_reassembly
        """
        world = _posted_with_two_responses(api)
        _assemble(api, world)

        opened = validate_success(
            api.solicitation_lifecycle(
                world["solicitation"]["id"], {"action": "OPEN_EVALUATION"}, OFFICER_CONDUCTOR
            )
        )

        assert opened["status"] == "EVALUATION"
        assert opened["audit_package_status"] == "STALE"
        assert opened["audit_completeness_pct"] is None
        validate_error(
            api.solicitation_audit_package(
                world["solicitation"]["id"], {"action": "CERTIFY"}, OFFICER_AWARDER
            ),
            ApiErrorId.ERR_AUDIT_PACKAGE_NOT_ASSEMBLED,
            409,
        )
        stale = read_solicitation(api, world["solicitation"]["id"])
        assert stale["audit_package_status"] == "STALE"
        assert stale["certified_at"] is None
        assert stale["certified_by_user_id"] is None
        rebuilt = _assemble(api, world)
        assert rebuilt["audit_package_status"] == "ASSEMBLED"
        assert_score(rebuilt["audit_completeness_pct"], 50.00, "audit_completeness_pct")
        assert rebuilt["status"] == "EVALUATION"
