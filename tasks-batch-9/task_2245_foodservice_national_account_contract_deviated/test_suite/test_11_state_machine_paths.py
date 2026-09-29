"""The declared state machines walked end to end: initial states, the legal
edges, the preconditions guarding them, the refusals from states that do not
declare a trigger, and the cascades a transition drives into other rows.
"""
from test_helpers import (
    AUG_05,
    AUG_10,
    NOV_START,
    OCT_START,
    SEP_05,
    SEP_START,
    TERM_START,
    acknowledge_notice,
    activate_notice,
    amendment_payload,
    api_client,
    assert_pct,
    bootstrap_partners,
    build_active_deviation,
    build_invoiced_line_world,
    build_signed_contract,
    build_submitted_claim,
    close_rebate_period,
    create_contract_draft,
    create_deviation,
    create_dispute,
    create_invoiced_line,
    create_notice,
    create_order_line,
    create_product,
    decide_deviation,
    issue_credit,
    open_rebate_period,
    rebate_period_payload,
    resolve_dispute,
    set_clock,
    sign_contract,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, ANALYST, NAM, add_coverage, add_tier

AUG_02 = "2026-08-02T00:00:00Z"
AUG_20 = "2026-08-20T00:00:00Z"

TWO_BAND_TIERS = [
    {"markup_value": 12.50, "min_case_volume": 0, "max_case_volume": 500},
    {"markup_value": 9.00, "min_case_volume": 500},
]


class TestDeclaredInitialStates:
    def test_every_fresh_row_sits_in_the_state_its_machine_declares(self):
        """PRD §3.5: "The line lands with `pricing_status` `DRAFT_PRICED` and
        `billback_status` `NOT_APPLICABLE`, with `credited_amount_cents` 0 and
        with `substituted_from_product_id`, `substitution_rule_id` and
        `bill_back_claim_id` all null."

        Design: Corner/State Machines/every_state_machine_starts_in_its_declared_initial_state
        """
        world = bootstrap_partners()
        product = create_product(world["manufacturer_id"])
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        assert contract["status"] == "DRAFT"

        tier = add_tier(contract["id"])
        coverage = add_coverage(contract["id"], world["dc_id"])
        assert tier["status"] == "ACTIVE"
        assert coverage["status"] == "ACTIVE"

        sign_contract(contract["id"], world["operator_id"])
        period = open_rebate_period(contract["id"])
        assert period["status"] == "OPEN"

        deviation = create_deviation(
            contract["id"],
            product["id"],
            world["manufacturer_id"],
            4500,
            OCT_START,
            NOV_START,
            requested_net_price_cents=3900,
        )
        assert deviation["status"] == "DRAFT"
        assert deviation["revision_round"] == 0
        assert deviation["price_revision_count"] == 0

        set_clock(AUG_05)
        line = create_order_line(
            contract["id"],
            product["id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )

        assert line["pricing_status"] == "DRAFT_PRICED"
        # The deviation window opens in October, so the pair starts unbilled.
        assert line["billback_status"] == "NOT_APPLICABLE"
        assert line["credited_amount_cents"] == 0
        assert line["substituted_from_product_id"] is None
        assert line["substitution_rule_id"] is None
        assert line["bill_back_claim_id"] is None


class TestSignaturePath:
    def test_the_revision_cycle_walks_every_declared_edge_in_order(self):
        """PRD §3.3: "Returning the contract for revision moves
        `PENDING_SIGNATURE → DRAFT`, optionally carrying a `note`, and is
        available only to the `OperatorBuyer` whose `X-User-ID` equals the
        contract's `operator_id`; the manager may then resubmit, so
        `PENDING_SIGNATURE → DRAFT → PENDING_SIGNATURE` is an ordinary revision
        cycle rather than an error path."

        Design: Corner/State Machines/contract_signature_path_walks_draft_pending_active
        """
        world = bootstrap_partners()
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        add_tier(contract["id"])
        add_coverage(contract["id"], world["dc_id"])

        first_submit = validate_success(
            api_client.submit_contract_for_signature(contract["id"], NAM)
        )
        assert first_submit["status"] == "PENDING_SIGNATURE"

        returned = validate_success(
            api_client.return_contract_to_draft(contract["id"], world["buyer"])
        )
        assert returned["status"] == "DRAFT"

        second_submit = validate_success(
            api_client.submit_contract_for_signature(contract["id"], NAM)
        )
        assert second_submit["status"] == "PENDING_SIGNATURE"

        signed = validate_success(
            api_client.sign_contract(contract["id"], world["buyer"])
        )
        assert signed["status"] == "ACTIVE"
        assert signed["signed_by_user_id"] == world["operator_id"]
        assert signed["signed_at"].startswith("2026-08-01T00:00:00")
        # Four actions on top of the create, each worth exactly one version.
        assert signed["version"] == 5


class TestSubmitPreconditions:
    def test_a_missing_tier_and_a_missing_coverage_are_refused_separately(self):
        """PRD §3.3: "The move is refused unless the contract is currently in
        `DRAFT` and the configuration is complete: at least one markup tier of
        that contract must be `ACTIVE`, and at least one coverage row must be
        `ACTIVE`."

        Design: Corner/State Machines/submit_for_signature_requires_a_tier_and_a_coverage
        """
        world = bootstrap_partners()
        bare = create_contract_draft(
            world["operator_id"], world["manufacturer_id"], contract_code="HLG-NONE"
        )
        tier_only = create_contract_draft(
            world["operator_id"], world["manufacturer_id"], contract_code="HLG-TIER"
        )
        add_tier(tier_only["id"])

        validate_error(
            api_client.submit_contract_for_signature(bare["id"], NAM),
            "ERR_CONTRACT_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.submit_contract_for_signature(tier_only["id"], NAM),
            "ERR_CONTRACT_INVALID_STATE",
            409,
        )

        for contract_id in (bare["id"], tier_only["id"]):
            still_draft = validate_success(api_client.get_contract(contract_id, NAM))
            assert still_draft["status"] == "DRAFT"

        # The coverage create is accepted while the contract is still DRAFT.
        coverage = add_coverage(tier_only["id"], world["dc_id"])
        assert coverage["status"] == "ACTIVE"

        accepted = validate_success(
            api_client.submit_contract_for_signature(tier_only["id"], NAM)
        )
        assert accepted["status"] == "PENDING_SIGNATURE"


class TestUndeclaredTriggers:
    def test_three_machines_each_answer_with_their_own_invalid_state_code(self):
        """PRD §2.8: "The target resource is in a declared from-state of the
        requested transition — `ERR_CONTRACT_INVALID_STATE`,
        `ERR_DEVIATION_INVALID_STATE`, `ERR_NOTICE_INVALID_STATE`,
        `ERR_ORDER_LINE_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`,
        `ERR_REMITTANCE_INVALID_STATE`, `ERR_REBATE_PERIOD_INVALID_STATE` or
        `ERR_DISPUTE_INVALID_STATE` (409), on every action endpoint."

        Design: Corner/State Machines/triggers_absent_from_the_current_state_are_refused
        """
        world = bootstrap_partners()
        product = create_product(world["manufacturer_id"])
        stalled = create_contract_draft(
            world["operator_id"], world["manufacturer_id"], contract_code="HLG-2026"
        )
        add_tier(stalled["id"])
        add_coverage(stalled["id"], world["dc_id"])

        live = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            contract_code="HLG-LIVE",
        )
        deviation = create_deviation(
            live["contract_id"],
            product["id"],
            world["manufacturer_id"],
            4500,
            TERM_START,
            NOV_START,
            requested_net_price_cents=3900,
        )
        period = open_rebate_period(live["contract_id"])

        validate_error(
            api_client.sign_contract(stalled["id"], world["buyer"]),
            "ERR_CONTRACT_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.activate_deviation_agreement(deviation["id"], NAM),
            "ERR_DEVIATION_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.settle_rebate_period(
                period["id"], {"settlement_reference": "ACH-TOO-EARLY"}, ACCOUNTANT
            ),
            "ERR_REBATE_PERIOD_INVALID_STATE",
            409,
        )

        untouched_contract = validate_success(
            api_client.get_contract(stalled["id"], NAM)
        )
        assert untouched_contract["status"] == "DRAFT"
        assert untouched_contract["version"] == stalled["version"]

        untouched_deviation = validate_success(
            api_client.get_deviation_agreement(deviation["id"], ANALYST)
        )
        assert untouched_deviation["status"] == "DRAFT"
        assert untouched_deviation["version"] == deviation["version"]

        untouched_period = validate_success(
            api_client.get_rebate_period(period["id"], ACCOUNTANT)
        )
        assert untouched_period["status"] == "OPEN"
        assert untouched_period["version"] == period["version"]


class TestReplayedActions:
    def test_invoicing_twice_is_refused_rather_than_applied_twice(self):
        """PRD §3.5: "It moves `pricing_status` `DRAFT_PRICED → INVOICED`, and it
        is also the only entry point to the line's second, entirely independent
        status dimension: when `deviation_agreement_id` is not null,
        `billback_status` moves `NOT_APPLICABLE → ACCRUED` in the same request,
        and when it is null `billback_status` stays `NOT_APPLICABLE`."

        Design: Corner/State Machines/replaying_a_completed_action_is_refused_not_reapplied
        """
        world = build_invoiced_line_world(quantity_cases=10)
        invoiced = world["order_line"]
        assert invoiced["pricing_status"] == "INVOICED"
        assert invoiced["extended_price_cents"] == 47250

        replay = api_client.invoice_order_line(world["order_line_id"], NAM)
        validate_error(replay, "ERR_ORDER_LINE_INVALID_STATE", 409)

        after = validate_success(
            api_client.get_order_line(world["order_line_id"], NAM)
        )
        assert after["pricing_status"] == "INVOICED"
        assert after["billback_status"] == "NOT_APPLICABLE"
        assert after["extended_price_cents"] == 47250
        assert after["version"] == invoiced["version"]


class TestTerminalStateLockdown:
    def test_a_terminated_contract_refuses_every_further_trigger(self):
        """PRD §3.3: "`EXPIRED` and `TERMINATED` are the contract's two terminal
        states, and the sweep reports what it touched through
        `expired_contract_ids` and `expired_deviation_ids`."

        Design: Corner/State Machines/terminated_contract_accepts_no_further_transition
        """
        world = bootstrap_partners()
        signed = build_signed_contract(
            world["operator_id"], world["manufacturer_id"], world["dc_id"]
        )
        contract_id = signed["contract_id"]

        terminated = validate_success(
            api_client.terminate_contract(
                contract_id, NAM, {"reason": "Operator exited the program"}
            )
        )
        assert terminated["status"] == "TERMINATED"

        tier = validate_success(
            api_client.get_contract_tier(signed["tier_ids"][0], NAM)
        )
        coverage = validate_success(
            api_client.get_dc_coverage(signed["coverage_ids"][0], NAM)
        )
        assert tier["status"] == "SUPERSEDED"
        assert coverage["status"] == "ENDED"

        validate_error(
            api_client.suspend_contract(
                contract_id, NAM, {"note": "Attempt on a terminal row"}
            ),
            "ERR_CONTRACT_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.reinstate_contract(contract_id, NAM),
            "ERR_CONTRACT_INVALID_STATE",
            409,
        )
        validate_error(
            api_client.open_contract_amendment(
                contract_id, NAM, amendment_payload(effective_from=SEP_START)
            ),
            "ERR_CONTRACT_INVALID_STATE",
            409,
        )
        # A rebate period needs a live contract, which this one no longer is.
        validate_error(
            api_client.create_rebate_period(
                rebate_period_payload(contract_id, SEP_START, OCT_START), ACCOUNTANT
            ),
            "ERR_CONTRACT_NOT_ACTIVE",
            409,
        )

        after = validate_success(api_client.get_contract(contract_id, NAM))
        assert after["status"] == "TERMINATED"
        assert after["version"] == terminated["version"]


class TestSignatureSideEffects:
    def test_one_call_stamps_the_clock_the_signer_and_the_posture(self):
        """PRD §3.3: "Signature stamps `signed_at` from the logical clock and
        `signed_by_user_id` from `X-User-ID`, recomputes `compliance_posture`
        (which on a fresh contract with no closed period resolves to `OPEN`), and
        increments the contract's `version` by 1."

        Design: Corner/State Machines/signature_side_effects_all_land_in_one_response
        """
        world = bootstrap_partners()
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        add_tier(contract["id"])
        add_coverage(contract["id"], world["dc_id"])
        submitted = validate_success(
            api_client.submit_contract_for_signature(contract["id"], NAM)
        )

        set_clock(AUG_02)
        signed = validate_success(
            api_client.sign_contract(contract["id"], world["buyer"])
        )

        assert signed["status"] == "ACTIVE"
        assert signed["signed_at"].startswith("2026-08-02T00:00:00")
        assert signed["signed_by_user_id"] == world["operator_id"]
        assert signed["compliance_posture"] == "OPEN"
        assert signed["version"] == submitted["version"] + 1


def _build_terminable_world():
    """An ACTIVE contract carrying two ACTIVE tiers, one ACTIVE coverage, one
    ACTIVE deviation on the chicken item and one already REJECTED deviation on
    the beef item."""
    world = bootstrap_partners()
    chicken = create_product(world["manufacturer_id"])
    beef = create_product(
        world["manufacturer_id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=6000,
        avg_cost_cents=5900,
        replacement_cost_cents=6100,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=TWO_BAND_TIERS,
    )
    world.update(signed)

    world["live_deviation"] = build_active_deviation(
        signed["contract_id"],
        chicken["id"],
        world["manufacturer_id"],
        4500,
        TERM_START,
        NOV_START,
        requested_net_price_cents=3900,
    )
    submitted = build_active_deviation(
        signed["contract_id"],
        beef["id"],
        world["manufacturer_id"],
        6200,
        TERM_START,
        NOV_START,
        stage="SUBMITTED",
        requested_net_price_cents=5800,
    )
    world["rejected_deviation"] = decide_deviation(
        submitted["id"],
        world["manufacturer_id"],
        "REJECT",
        "No funding for beef this quarter",
    )
    return world


class TestTerminationCascade:
    def test_the_cascade_reaches_live_children_and_spares_terminal_ones(self):
        """PRD §3.3: "A termination moves the contract to `TERMINATED` and
        cascades in four directions: every deviation agreement of the contract in
        `DRAFT`, `SUBMITTED`, `MANUFACTURER_APPROVED`, `REVISION_REQUESTED`,
        `ACTIVE` or `PRICE_CEILING_BREACHED` becomes `TERMINATED`; every `ACTIVE`
        markup tier becomes `SUPERSEDED`; every `ACTIVE` coverage row becomes
        `ENDED`; and when the terminated row is itself an amendment draft whose
        parent is `AMENDING`, the parent returns to `ACTIVE`."

        Design: Corner/State Machines/contract_termination_cascades_only_to_non_terminal_children
        """
        world = _build_terminable_world()
        rejected = world["rejected_deviation"]
        assert rejected["status"] == "REJECTED"

        terminated = validate_success(
            api_client.terminate_contract(
                world["contract_id"], NAM, {"reason": "Operator exited the program"}
            )
        )
        assert terminated["status"] == "TERMINATED"

        for tier_id in world["tier_ids"]:
            tier = validate_success(api_client.get_contract_tier(tier_id, NAM))
            assert tier["status"] == "SUPERSEDED"

        coverage = validate_success(
            api_client.get_dc_coverage(world["coverage_ids"][0], NAM)
        )
        assert coverage["status"] == "ENDED"

        live_after = validate_success(
            api_client.get_deviation_agreement(world["live_deviation"]["id"], ANALYST)
        )
        assert live_after["status"] == "TERMINATED"

        # A child already in a terminal state is not touched at all.
        rejected_after = validate_success(
            api_client.get_deviation_agreement(rejected["id"], ANALYST)
        )
        assert rejected_after["status"] == "REJECTED"
        assert rejected_after["version"] == rejected["version"]

        _, active_tier_meta = validate_paginated(
            api_client.list_contract_tiers(
                NAM, {"contract_id": world["contract_id"], "status": "ACTIVE"}
            )
        )
        assert active_tier_meta["total_count"] == 0

        _, active_coverage_meta = validate_paginated(
            api_client.list_dc_coverages(
                NAM, {"contract_id": world["contract_id"], "status": "ACTIVE"}
            )
        )
        assert active_coverage_meta["total_count"] == 0


def _build_credit_side_branch_world():
    """Two submitted claims on one cost-plus-protected agreement, and an UPHELD
    dispute on a line that sits inside the August claim only.

    A minor cost reset from 4200 to 4000 drops the protected price from 3900 to
    3700, which is what gives the audit a positive variance to uphold.
    """
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=TWO_BAND_TIERS,
    )
    world.update(signed)
    world["product_id"] = product["id"]

    deviation = build_active_deviation(
        signed["contract_id"],
        product["id"],
        world["manufacturer_id"],
        4500,
        TERM_START,
        NOV_START,
        bill_back_basis="COST_PLUS_PROTECTED",
        protected_discount_cents=300,
    )
    world["deviation"] = deviation
    world["august"] = open_rebate_period(
        signed["contract_id"], TERM_START, SEP_START
    )
    world["september"] = open_rebate_period(
        signed["contract_id"], SEP_START, OCT_START
    )

    # 300 cases at 4725 list against 3900 deviated, twice, inside August.
    world["line_a"] = create_invoiced_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        300,
        order_clock=AUG_05,
    )
    world["line_b"] = create_invoiced_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        300,
        order_clock=AUG_10,
    )

    notice = create_notice(
        signed["contract_id"], product["id"], AUG_20, proposed_cost_cents=4000
    )
    acknowledge_notice(notice["id"], world["operator_id"])
    set_clock(AUG_20)
    world["notice"] = activate_notice(notice["id"])

    # 100 September cases now price off 4000: list 4360 against 3700 deviated.
    world["line_c"] = create_invoiced_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        100,
        order_clock=SEP_05,
    )

    world["claim_august"] = build_submitted_claim(
        deviation["id"], TERM_START, SEP_START
    )
    world["claim_september"] = build_submitted_claim(
        deviation["id"], SEP_START, OCT_START
    )
    close_rebate_period(world["august"]["id"])

    dispute = create_dispute(
        world["line_a"]["id"], world["operator_id"], 3700, "DEVIATION_NOT_APPLIED"
    )
    world["audited"] = start_audit(dispute["id"])
    world["dispute"] = resolve_dispute(
        dispute["id"], "UPHELD", "The protected price fell after the cost reset"
    )
    return world


class TestCreditSideBranch:
    def test_only_the_claim_covering_the_credited_line_is_reopened(self):
        """PRD §3.9: "**And a side branch off hop two:** when the credited line's
        `billback_status` is `CLAIMED`, the bill-back claim it belongs to moves
        `SUBMITTED → DISPUTED` and its `claimed_amount_cents` is recomputed over
        the currently swept lines, since the credit has shrunk — possibly to
        nothing — that line's recoverable delta."

        Design: Corner/State Machines/credit_side_branch_disputes_only_a_claimed_line
        """
        world = _build_credit_side_branch_world()
        august_claim = world["claim_august"]
        september_claim = world["claim_september"]

        # 825 per case over 600 August cases, and 660 over 100 September cases.
        assert august_claim["claimed_amount_cents"] == 495000
        assert september_claim["claimed_amount_cents"] == 66000
        assert world["deviation"]["deviated_price_cents"] == 3900
        assert world["notice"]["new_cost_cents"] == 4000
        assert world["line_c"]["list_unit_price_cents"] == 4360
        assert world["line_c"]["invoiced_unit_price_cents"] == 3700
        assert world["audited"]["audited_correct_unit_price_cents"] == 3700
        assert world["audited"]["variance_cents_per_case"] == 200
        assert_pct(world["audited"]["variance_pct"], 5.13, "variance_pct")

        credited = issue_credit(world["dispute"]["id"])
        assert credited["status"] == "CREDIT_ISSUED"
        assert credited["credit_amount_cents"] == 60000

        line_a = validate_success(
            api_client.get_order_line(world["line_a"]["id"], NAM)
        )
        assert line_a["pricing_status"] == "CREDITED"
        assert line_a["invoiced_unit_price_cents"] == 3700
        assert line_a["billback_status"] == "CLAIMED"

        reopened_claim = validate_success(
            api_client.get_bill_back_claim(august_claim["id"], NAM)
        )
        assert reopened_claim["status"] == "DISPUTED"
        # The credited line's recoverable delta grew to 4725 - 3700 per case.
        assert reopened_claim["claimed_amount_cents"] == 555000

        untouched_claim = validate_success(
            api_client.get_bill_back_claim(september_claim["id"], NAM)
        )
        assert untouched_claim["status"] == "SUBMITTED"
        assert untouched_claim["claimed_amount_cents"] == 66000
        assert untouched_claim["version"] == september_claim["version"]

        line_c = validate_success(
            api_client.get_order_line(world["line_c"]["id"], NAM)
        )
        assert line_c["pricing_status"] == "INVOICED"
        assert line_c["billback_status"] == "CLAIMED"
