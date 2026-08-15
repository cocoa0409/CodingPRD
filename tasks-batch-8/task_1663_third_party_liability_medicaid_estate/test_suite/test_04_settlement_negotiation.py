"""Settlement negotiation: dual-variant recovery formula, counter cycle, accept gates, OCC (PRD §2.7, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_expense_claim,
    assert_settlement,
    create_case,
    create_member,
    factories,
    get_case,
    get_case_version,
    get_settlement,
    set_clock,
    setup_settlement_offered,
    validate_error,
    validate_paginated,
    validate_success,
)

SPEC = TEST_USERS["specialist_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
SUP2 = TEST_USERS["supervisor2_headers"]


class TestDualVariantRecovery:
    def test_reimbursement_variant_recovery(self, api):
        """PRD §3.1: "Members whose `state_code` is MT or WY are assigned `SUBROGATION`; members from every other state are assigned `REIMBURSEMENT`."
        PRD §3.4: "Under `REIMBURSEMENT`, the state recovers the smallest of three values — the lien's current `outstanding_cents`; the gross less the attorney fee and less the litigation costs; and thirty-five percent of the gross amount, that statutory medical portion rounded half-up to a whole cent — floored at zero so the recovery is never negative. The `cost_share_cents` is zero under this variant."

        Design: Difficulty/dual_variant_calc/settlement_recovery_subrogation_vs_reimbursement
        """
        # CA member (REIMBURSEMENT); lien outstanding 200000;
        # gross 1000000, fee 0.25, costs 100000 ->
        # min(200000, 650000, 350000) = 200000.
        ctx = setup_settlement_offered(
            state_code="CA", claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=100000, offered_by="INSURER",
        )
        s = ctx["settlement"]
        assert_settlement(s)
        assert s["state_recovery_cents"] == 200000, (
            f"REIMBURSEMENT recovery must be the min() of the three limits, got {s['state_recovery_cents']}"
        )
        assert s["cost_share_cents"] == 0, (
            "cost_share_cents is zero under REIMBURSEMENT"
        )

    def test_subrogation_variant_recovery(self, api):
        """PRD §3.4: "Under `SUBROGATION`, the state stands in the member's shoes and evaluation order is pinned. First, the pre-cost recovery is the lesser of the lien's current `outstanding_cents` and the `gross_amount_cents`. Second, `cost_share_cents` is the lesser of `litigation_costs_cents` and twenty-five percent of that pre-cost recovery, the percentage rounded half-up to a whole cent — the cap is always a fraction of the pre-cost recovery, never of the post-deduction value. Third, `state_recovery_cents` is the pre-cost recovery minus `cost_share_cents`."

        Design: Difficulty/dual_variant_calc/settlement_recovery_subrogation_vs_reimbursement
        """
        # MT member (SUBROGATION); lien outstanding 200000;
        # gross 1000000 -> pre_cost 200000; cost_share min(100000, 50000) = 50000;
        # recovery = 200000 - 50000 = 150000.
        ctx = setup_settlement_offered(
            state_code="MT", claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=100000, offered_by="INSURER",
        )
        s = ctx["settlement"]
        assert_settlement(s)
        assert s["cost_share_cents"] == 50000, (
            f"Cost share must be capped by 25% of the pre-cost recovery, got {s['cost_share_cents']}"
        )
        assert s["state_recovery_cents"] == 150000, (
            f"SUBROGATION recovery must be pre-cost less cost share, got {s['state_recovery_cents']}"
        )

    def test_variant_member_net_divergence(self, api):
        """PRD §3.4: "Under both variants, the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`."

        Design: Difficulty/dual_variant_calc/settlement_recovery_subrogation_vs_reimbursement
        """
        ca = setup_settlement_offered(
            state_code="CA", medicaid_id=None,
            claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=100000, offered_by="INSURER",
        )["settlement"]
        assert ca["member_net_cents"] == 450000, (
            f"REIMBURSEMENT member net = 1000000-250000-100000-200000, got {ca['member_net_cents']}"
        )
        mt = setup_settlement_offered(
            state_code="MT",
            claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=100000, offered_by="INSURER",
        )["settlement"]
        assert mt["member_net_cents"] == 500000, (
            f"SUBROGATION member net = 1000000-250000-100000-150000, got {mt['member_net_cents']}"
        )


class TestSubrogationCostSharePinnedOrder:
    def test_cost_share_capped_by_pre_cost_recovery(self, api):
        """PRD §3.4: "Second, `cost_share_cents` is the lesser of `litigation_costs_cents` and twenty-five percent of that pre-cost recovery, the percentage rounded half-up to a whole cent — the cap is always a fraction of the pre-cost recovery, never of the post-deduction value."

        Design: Difficulty/combinatorial_formula/subrogation_cost_share_pinned_order
        """
        # MT member; lien 200000; gross 1000000; costs 40000 ->
        # pre_cost 200000; cost_share = min(40000, 50000) = 40000.
        ctx = setup_settlement_offered(
            state_code="MT", claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=40000, offered_by="INSURER",
        )
        s = ctx["settlement"]
        assert s["cost_share_cents"] == 40000, (
            f"Cost share must be capped against the pre-cost recovery, got {s['cost_share_cents']}"
        )
        assert s["state_recovery_cents"] == 160000

    def test_fee_and_member_net_under_subrogation(self, api):
        """PRD §3.4: "The attorney fee `fee_amount_cents` is the `gross_amount_cents` multiplied by `attorney_fee_pct`, rounded half-up to a whole cent, in both variants."
        PRD §3.4: "Under both variants, the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`."

        Design: Difficulty/combinatorial_formula/subrogation_cost_share_pinned_order
        """
        ctx = setup_settlement_offered(
            state_code="MT", claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=40000, offered_by="INSURER",
        )
        s = ctx["settlement"]
        assert s["fee_amount_cents"] == 250000
        assert s["member_net_cents"] == 550000, (
            f"member net = 1000000-250000-40000-160000, got {s['member_net_cents']}"
        )


class TestCounterCycle:
    def test_first_counter_moves_to_countered_round_two(self, api):
        """PRD §3.4: "A counter by a `RecoverySpecialist` or `RecoverySupervisor` moves `OFFERED` to `COUNTERED`, and the next counter moves `COUNTERED` back to `OFFERED`; each counter increments `round_number` by one, replaces all four offer fields — `gross_amount_cents`, `attorney_fee_pct`, `litigation_costs_cents`, and `offered_by` — from the payload, and recomputes `fee_amount_cents`, `cost_share_cents`, `state_recovery_cents`, and `member_net_cents` under the same formulas."

        Design: Difficulty/non_linear_state_machine/settlement_counter_cycle_rounds
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000, offered_by="INSURER",
        )
        s = ctx["settlement"]
        assert s["round_number"] == 1 and s["status"] == "OFFERED"
        countered = validate_success(
            api.counter_settlement(
                s["id"],
                factories.counter_payload(
                    gross_amount_cents=600000, attorney_fee_pct=0.25,
                    litigation_costs_cents=60000, offered_by="STATE",
                ),
                SPEC,
            ),
            200,
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 2
        assert countered["gross_amount_cents"] == 600000
        assert countered["offered_by"] == "STATE"

    def test_second_counter_returns_to_offered_round_three(self, api):
        """PRD §3.4: "A counter by a `RecoverySpecialist` or `RecoverySupervisor` moves `OFFERED` to `COUNTERED`, and the next counter moves `COUNTERED` back to `OFFERED`; each counter increments `round_number` by one, replaces all four offer fields — `gross_amount_cents`, `attorney_fee_pct`, `litigation_costs_cents`, and `offered_by` — from the payload, and recomputes `fee_amount_cents`, `cost_share_cents`, `state_recovery_cents`, and `member_net_cents` under the same formulas."

        Design: Difficulty/non_linear_state_machine/settlement_counter_cycle_rounds
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000, offered_by="INSURER",
        )
        s = ctx["settlement"]
        validate_success(
            api.counter_settlement(
                s["id"],
                factories.counter_payload(
                    gross_amount_cents=600000, attorney_fee_pct=0.25,
                    litigation_costs_cents=60000, offered_by="STATE",
                ),
                SPEC,
            ),
            200,
        )
        offered_again = validate_success(
            api.counter_settlement(
                s["id"],
                factories.counter_payload(
                    gross_amount_cents=700000, attorney_fee_pct=0.25,
                    litigation_costs_cents=60000, offered_by="INSURER",
                ),
                SPEC,
            ),
            200,
        )
        assert offered_again["status"] == "OFFERED"
        assert offered_again["round_number"] == 3
        assert offered_again["gross_amount_cents"] == 700000
        assert offered_again["fee_amount_cents"] == 175000


class TestOpenNegotiationGates:
    def test_second_open_settlement_rejected(self, api):
        """PRD §3.4: "Only one negotiation may be live at a time: if a settlement in `OFFERED` or `COUNTERED` status already exists on the case, the attempt is rejected with `ERR_NEGOTIATION_IN_PROGRESS` (HTTP 409)."

        Design: Corner/validations/second_open_settlement_rejected
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000,
        )
        case_id = ctx["case"]["id"]
        resp = api.create_settlement(
            case_id,
            factories.settlement_payload(
                get_case_version(case_id),
                gross_amount_cents=600000, attorney_fee_pct=0.20,
                litigation_costs_cents=50000, offered_by="STATE",
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_IN_PROGRESS)
        data, meta = validate_paginated(
            api.list_settlements(SPEC, params={"case_id": case_id})
        )
        assert meta["total_count"] == 1

    def test_settlement_create_with_stale_case_version_rejected(self, api):
        """PRD §2.7: "`POST /recovery/cases/{caseId}/settlements` requires the input field `expected_case_version`, carrying the client's last observed `version` of the case. A mismatch with the case's current `version` — for example, because another writer has mutated the case since the client last read it, such as adding an expense claim and thereby changing the lien basis — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/settlement_create_stale_case_version_returns_412
        """
        # Build a LIEN_FILED case while holding the version observed right
        # after attorney notification; the claim and the lien filing both
        # advance the case version, leaving the held version stale.
        member = create_member(state_code="CA", medicaid_id="M-OC-3")
        case = create_case(member["id"])
        notified = validate_success(api.notify_attorney(case["id"], SPEC), 200)
        stale_version = notified["version"]
        add_expense_claim(case["id"], "2026-01-10", 100000)
        validate_success(api.file_lien(case["id"], SPEC), 201)
        resp = api.create_settlement(
            case["id"],
            factories.settlement_payload(
                stale_version,
                gross_amount_cents=500000, attorney_fee_pct=0.20,
                litigation_costs_cents=50000, offered_by="INSURER",
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data, meta = validate_paginated(
            api.list_settlements(SPEC, params={"case_id": case["id"]})
        )
        assert data == [] and meta["total_count"] == 0


class TestAcceptanceGates:
    def test_specialist_cannot_accept_settlement(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: the accept endpoint is authorized for RecoverySupervisor only.

        Design: Corner/validations/specialist_cannot_accept_settlement_forbidden
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000,
        )
        resp = api.accept_settlement(ctx["settlement"]["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_settlement(ctx["settlement"]["id"])["status"] == "OFFERED"

    def test_supervisor_cannot_accept_own_settlement(self, api):
        """PRD §3.4: "Segregation of duties comes first: the acting `X-User-ID` must differ from the settlement's `created_by_user_id`, and a supervisor accepting their own offer is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/sod_supervisor_cannot_accept_own_settlement
        """
        # The settlement is tabled by supervisor sup_1, so sup_1 is barred;
        # a different supervisor sup_2 may accept.
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000, offered_by="STATE",
            creator="supervisor",
        )
        s = ctx["settlement"]
        assert s["created_by_user_id"] == "sup_1"
        resp = api.accept_settlement(s["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        accepted = validate_success(api.accept_settlement(s["id"], SUP2), 200)
        assert accepted["status"] == "ACCEPTED"

    def test_accept_rejected_settlement_rejected(self, api):
        """PRD §3.4: "Rejection is likewise a `RecoverySupervisor` decision, available from `OFFERED` or `COUNTERED`: the settlement moves to the terminal `REJECTED` status, and the case falls back from `SETTLEMENT_PENDING` to `LIEN_FILED`, freeing the lien for a later negotiation."
        PRD §2.8: "6. State-transition preconditions — failure is `ERR_INVALID_STATE_TRANSITION` (HTTP 409) or one of its specialized variants `ERR_ATTORNEY_NOT_NOTIFIED`, `ERR_LIEN_NOT_AMENDABLE`, `ERR_LIEN_NOT_ACTIVE`, or `ERR_CLAIM_NOT_FILED` (all HTTP 409)."

        Design: Corner/state_machines/accept_rejected_settlement_returns_invalid_state
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000,
        )
        s = ctx["settlement"]
        validate_success(api.reject_settlement(s["id"], SUP1), 200)
        assert get_case(ctx["case"]["id"])["status"] == "LIEN_FILED"
        resp = api.accept_settlement(s["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_settlement(s["id"])["status"] == "REJECTED"

    def test_accept_without_active_lien_rejected(self, api):
        """PRD §3.4: "The settlement must stand at `OFFERED` or `COUNTERED`, and a lien in `FILED` or `AMENDED` status must exist on the case; without an active lien the acceptance is rejected with `ERR_LIEN_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_accept_requires_lien_active
        """
        ctx = setup_settlement_offered(claims=[("2026-01-10", 200000)])
        validate_success(api.release_lien(ctx["lien"]["id"], SUP1), 200)
        resp = api.accept_settlement(ctx["settlement"]["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_LIEN_NOT_ACTIVE)
        assert get_settlement(ctx["settlement"]["id"])["status"] == "OFFERED"

    def test_case_stays_settlement_pending_after_failed_accept(self, api):
        """PRD §3.3: "Release feeds back into the case: when the case stands at `LIEN_FILED`, it reverts to `ATTORNEY_NOTIFIED`; when the case stands at `SETTLEMENT_PENDING`, its status is left unchanged."
        PRD §3.4: "without an active lien the acceptance is rejected with `ERR_LIEN_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_accept_requires_lien_active
        """
        ctx = setup_settlement_offered(claims=[("2026-01-10", 200000)])
        validate_success(api.release_lien(ctx["lien"]["id"], SUP1), 200)
        assert get_case(ctx["case"]["id"])["status"] == "SETTLEMENT_PENDING", (
            "Releasing the lien during negotiation must leave the case unchanged"
        )
        validate_error(
            api.accept_settlement(ctx["settlement"]["id"], SUP1),
            ApiErrorId.ERR_LIEN_NOT_ACTIVE,
        )
        assert get_case(ctx["case"]["id"])["status"] == "SETTLEMENT_PENDING"


class TestAcceptanceReconciliation:
    def test_accept_recomputes_recovery_against_amended_lien(self, api):
        """PRD §3.4: "On acceptance the recovery is recomputed against the lien's current `outstanding_cents` — derived-field reconciliation, since amendments or postings may have moved the outstanding balance since the offer was tabled — and `fee_amount_cents`, `cost_share_cents`, and `member_net_cents` are recomputed with it."

        Design: Corner/calculations/accept_recomputes_recovery_after_lien_amend
        """
        # Offer tabled against a 200000 lien (recovery 200000); the lien is
        # amended down to 180000 outside the freeze window before acceptance.
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 200000)],
            gross_amount_cents=1000000, attorney_fee_pct=0.25,
            litigation_costs_cents=100000, offered_by="INSURER",
        )
        assert ctx["settlement"]["state_recovery_cents"] == 200000
        lien = ctx["lien"]
        set_clock("2026-08-16T00:00:00Z")  # past the 14-day freeze
        amended = validate_success(
            api.amend_lien(
                lien["id"],
                factories.amend_lien_payload(lien["version"], new_amount_cents=180000),
                SPEC,
            ),
            200,
        )
        assert amended["outstanding_cents"] == 180000
        accepted = validate_success(
            api.accept_settlement(ctx["settlement"]["id"], SUP1), 200
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["state_recovery_cents"] == 180000, (
            f"Acceptance must recompute against the amended lien, got {accepted['state_recovery_cents']}"
        )
        assert accepted["member_net_cents"] == 470000, (
            f"member net = 1000000-250000-100000-180000, got {accepted['member_net_cents']}"
        )
