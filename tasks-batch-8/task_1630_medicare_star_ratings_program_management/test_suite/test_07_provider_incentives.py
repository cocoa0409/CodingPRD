"""Provider incentive programs: payout amount variants, segregation of duties,
pool conservation, fiscal and state gates, and terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_payout,
    assert_pool_invariant,
    close_gap,
    close_group,
    create_active_measure,
    create_cycle,
    create_draft_set,
    create_group,
    create_member,
    cutpoint_row,
    deny_payout,
    get_group,
    get_payout,
    lock_performance,
    make_incentive_manager_headers,
    open_gap,
    pay_payout,
    propose_payout,
    publish_set,
    report_performance,
    setup_collecting_measure,
    setup_gap_closure_group,
    setup_paid_out_group,
    transition_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_dual_variant_scenario():
    """Cycle in CUTPOINT_REVIEW with a PUBLISHED set; attainment measure MA bands
    to published_star 4 (raw 0.85 vs floors 0.60/0.72/0.85/0.94); gap-closure
    measure MG has exactly 3 CLOSED PHARMACY_ADHERENCE gaps."""
    cycle = create_cycle()
    ma = create_active_measure(cycle["id"], code="BCS", title="Breast Cancer Screening",
                               measure_type="OUTCOME", data_source="HEDIS")
    mg = create_active_measure(cycle["id"], code="SPD", title="Statin Adherence",
                               domain="DRUG_SAFETY", measure_type="OUTCOME",
                               data_source="PHARMACY_PDE")
    set_p = create_draft_set(cycle["id"],
                             [cutpoint_row(ma["id"], 0.60, 0.72, 0.85, 0.94),
                              cutpoint_row(mg["id"], 0.70, 0.78, 0.85, 0.92)],
                             label="official-2028")
    transition_cycle(cycle["id"], "DATA_COLLECTION")
    perf_a = report_performance(cycle["id"], ma["id"], 17, 20)
    perf_g = report_performance(cycle["id"], mg["id"], 0, 0)
    for i in range(3):
        member = create_member(f"MBR-{i + 1}")
        gap = open_gap(member["id"], mg["id"], "PHARMACY_ADHERENCE")
        close_gap(gap["id"])
    lock_performance(perf_a["id"])
    lock_performance(perf_g["id"])
    transition_cycle(cycle["id"], "CUTPOINT_REVIEW")
    publish_set(cycle["id"], set_p["id"])

    group_a = create_group("Group A", "ATTAINMENT", ma["id"], target_star=5,
                           unit_reward_per_gap=100.0, max_pool_amount=10000.0)
    group_g = create_group("Group G", "GAP_CLOSURE", mg["id"], target_star=5,
                           unit_reward_per_gap=250.0, max_pool_amount=10000.0)
    return {"cycle_id": cycle["id"], "ma": ma, "mg": mg,
            "group_a": group_a, "group_g": group_g}


class TestPayoutAmountVariants:
    def test_attainment_payout_amount_proportional_to_star(
            self, api, incentive_manager_headers):
        """PRD §3.7: "**Attainment.** The star is the `published_star` of the
        performance recorded for the group's linked measure in that measure's
        cycle."
        PRD §3.7: "The attainment percentage is the star divided by `target_star`,
        capped at 1.0, and the amount is the group's `max_pool_amount` multiplied
        by that percentage, rounded half up to 2 decimal places."
        PRD §3.7: "The server computes the `amount` at propose time by the group's
        variant, snapshotting the inputs into `basis_snapshot` — the
        `program_type`, the `published_star` used, the `target_star`, the
        `closed_gap_count`, the `unit_reward_per_gap`, and the `max_pool_amount` —
        and records the proposer's `X-User-ID` as `proposed_by_user_id`."

        published_star 4 against target_star 5 yields 10000.00 x 0.8 = 8000.00.

        Design: Difficulty/dual_variant_calc/incentive_payout_variant_divergence
        """
        sc = _setup_dual_variant_scenario()
        resp = api.create_incentive_payout(
            {"provider_group_id": sc["group_a"]["id"]},
            make_incentive_manager_headers("im-1"),
        )
        payout = validate_success(resp, 201)
        assert payout["amount"] == pytest.approx(8000.00), (
            f"ATTAINMENT amount must be 8000.00, got {payout['amount']}"
        )
        assert payout["basis_snapshot"]["published_star"] == 4
        assert payout["status"] == "PENDING"
        assert payout["proposed_by_user_id"] == "im-1"

    def test_gap_closure_payout_amount_unit_times_closed_count(
            self, api, incentive_manager_headers):
        """PRD §3.7: "**Gap closure.** The `closed_gap_count` is the number of care
        gaps on the linked measure currently in `CLOSED` status at propose time."
        PRD §3.7: "The amount is the `unit_reward_per_gap` multiplied by that
        count, rounded half up to 2 decimal places, then capped at the group's
        `max_pool_amount`."

        Three CLOSED gaps at 250.00 per gap yield 750.00 — diverging from the
        ATTAINMENT variant's 8000.00 on the same underlying cycle data.

        Design: Difficulty/dual_variant_calc/incentive_payout_variant_divergence
        """
        sc = _setup_dual_variant_scenario()
        resp = api.create_incentive_payout(
            {"provider_group_id": sc["group_g"]["id"]},
            make_incentive_manager_headers("im-1"),
        )
        payout = validate_success(resp, 201)
        assert payout["amount"] == pytest.approx(750.00), (
            f"GAP_CLOSURE amount must be 750.00, got {payout['amount']}"
        )
        assert payout["basis_snapshot"]["closed_gap_count"] == 3


class TestPayoutSegregationOfDuties:
    def test_sod_approver_must_differ_from_proposer(self, api,
                                                    incentive_manager_headers):
        """PRD §3.7: "The payout must be `PENDING` (otherwise
        `ERR_PAYOUT_NOT_PENDING`), and the approver's `X-User-ID` must differ from
        the payout's `proposed_by_user_id` — an operator approving their own
        proposal is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_approver_must_differ_from_proposer
        """
        sc = setup_gap_closure_group(num_closed_gaps=1)
        payout = propose_payout(sc["group"]["id"], "im-1")

        resp = api.transition_incentive_payout(
            payout["id"], "APPROVED", make_incentive_manager_headers("im-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        approved = approve_payout(payout["id"], "im-2")
        assert approved["status"] == "APPROVED", (
            "A different IncentiveManager operator approves successfully"
        )

    def test_auditor_cannot_propose_payout(self, api, complaints_auditor_headers):
        """PRD §2.1: "If the headers are present but the role named in
        `X-User-Role` is not one of the declared roles, or the role is not
        permitted for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "All list and detail (read) endpoints are shared across all six
        roles. Write endpoints are restricted per role as enumerated in §4; a role
        attempting a write outside its grant is rejected with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/auditor_cannot_propose_payout
        """
        cycle = create_cycle()
        measure = create_active_measure(
            cycle["id"], code="SPD", title="Statin Adherence",
            domain="DRUG_SAFETY", measure_type="OUTCOME",
            data_source="PHARMACY_PDE")
        group = create_group("Group G", "GAP_CLOSURE", measure["id"])

        resp = api.create_incentive_payout({"provider_group_id": group["id"]},
                                           complaints_auditor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestPayoutGates:
    def test_attainment_payout_requires_banded_star(self, api,
                                                    incentive_manager_headers):
        """PRD §3.7: "That star must be non-null — an `ATTAINMENT` proposal against
        an unbanded performance is rejected with `ERR_PERFORMANCE_NOT_BANDED`."

        No cut point set is published, so the linked measure's published_star is
        null and the proposal is rejected without reserving anything.

        Design: Corner/calculations/attainment_payout_requires_banded_star
        """
        sc = setup_collecting_measure(
            10, 20,
            measure_kwargs={"code": "BCS", "title": "Breast Cancer Screening",
                            "measure_type": "OUTCOME"})
        group = create_group("Group A", "ATTAINMENT", sc["measure"]["id"],
                             target_star=5, unit_reward_per_gap=100.0,
                             max_pool_amount=10000.0)

        resp = api.create_incentive_payout({"provider_group_id": group["id"]},
                                           make_incentive_manager_headers("im-1"))
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_NOT_BANDED)
        group_after = validate_success(api.get_provider_group(group["id"],
                                                              incentive_manager_headers))
        assert group_after["reserved_total"] == pytest.approx(0.0), (
            "A rejected proposal reserves nothing"
        )

    def test_propose_on_closed_group_reports_state_error(
            self, api, incentive_manager_headers):
        """PRD §3.7: "Proposing a payout requires only the `provider_group_id` in
        the payload; the group must be `ACTIVE`, else `ERR_GROUP_NOT_ACTIVE`."
        PRD §2.11: "When a request fails more than one rule, the first applicable
        rule in the following priority order determines the rejection, so earlier
        failures mask later ones:"
        PRD §2.11: "7. **Cross-entity state gates** — the workflow-specific state
        checks: `ERR_CYCLE_NOT_COLLECTING`, `ERR_PERFORMANCE_LOCKED`,
        `ERR_MEMBER_NOT_ENROLLED`, `ERR_GROUP_NOT_ACTIVE`,
        `ERR_CYCLE_STATE_FORBIDS`, `ERR_CUTPOINT_SET_IMMUTABLE`,
        `ERR_PAYOUT_NOT_PENDING`, `ERR_PAYOUT_NOT_APPROVED`, `ERR_GAP_NOT_OPEN`,
        `ERR_GAP_NOT_CLOSED`, `ERR_INTERVENTION_LIMIT_REACHED`,
        `ERR_GROUP_HAS_OPEN_PAYOUTS`, `ERR_WAVE_OUTSIDE_WINDOW`,
        `ERR_PERFORMANCES_NOT_LOCKED`, `ERR_NO_PUBLISHED_CUTPOINT_SET`,
        `ERR_NO_BANDED_PERFORMANCES`, and `ERR_PERFORMANCE_NOT_BANDED` (all HTTP
        409)."
        PRD §2.11: "12. **Fiscal sufficiency** — `ERR_INCENTIVE_POOL_EXCEEDED`
        (HTTP 402) on payout proposal."

        The closed group's computed amount (100.00) would also exceed
        remaining_amount (0.00), but the tier-7 state gate masks the tier-12
        fiscal gate.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payout_propose
        """
        sc = setup_paid_out_group(unit_reward_per_gap=250.0, max_pool_amount=100.0)
        assert sc["group"]["status"] == "CLOSED"
        assert sc["group"]["remaining_amount"] == pytest.approx(0.0), (
            "The pool is fully paid out, so the fiscal rule would also fail"
        )

        resp = api.create_incentive_payout({"provider_group_id": sc["group"]["id"]},
                                           make_incentive_manager_headers("im-1"))
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE)

    def test_rejected_propose_on_closed_group_leaves_pool_unchanged(
            self, api, incentive_manager_headers):
        """PRD §3.7: "A successful proposal creates the payout in `PENDING`, moves
        the amount into reserve — `reserved_total` increases by the amount and
        `remaining_amount` decreases by it — and bumps the provider group's
        `version` by 1."
        PRD §3.7: "Throughout the group's life the fiscal invariant holds:
        `max_pool_amount` always equals `paid_total` plus `reserved_total` plus
        `remaining_amount`."

        The rejected proposal creates no payout and moves no pool fields.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payout_propose
        """
        sc = setup_paid_out_group(unit_reward_per_gap=250.0, max_pool_amount=100.0)
        group_id = sc["group"]["id"]

        resp = api.create_incentive_payout({"provider_group_id": group_id},
                                           make_incentive_manager_headers("im-1"))
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE)

        group = validate_success(api.get_provider_group(group_id,
                                                        incentive_manager_headers))
        assert group["paid_total"] == pytest.approx(100.0)
        assert group["reserved_total"] == pytest.approx(0.0)
        assert group["remaining_amount"] == pytest.approx(0.0)
        assert_pool_invariant(group)
        _payouts, meta = validate_paginated(api.list_incentive_payouts(
            incentive_manager_headers, params={"provider_group_id": group_id}))
        assert meta["total_count"] == 1, "No new payout is persisted"


class TestPoolConservation:
    def test_propose_reserves_amount(self, api, incentive_manager_headers):
        """PRD §3.7: "A successful proposal creates the payout in `PENDING`, moves
        the amount into reserve — `reserved_total` increases by the amount and
        `remaining_amount` decreases by it — and bumps the provider group's
        `version` by 1."

        Two CLOSED gaps at 250.00 produce a 500.00 proposal: reserved_total
        500.00 and remaining_amount 9500.00.

        Design: Difficulty/compensating_invariant/pool_conservation_propose_then_deny
        """
        sc = setup_gap_closure_group(num_closed_gaps=2)
        payout = propose_payout(sc["group"]["id"], "im-1")
        assert payout["amount"] == pytest.approx(500.00)
        assert payout["status"] == "PENDING"

        group = validate_success(api.get_provider_group(sc["group"]["id"],
                                                        incentive_manager_headers))
        assert group["reserved_total"] == pytest.approx(500.0)
        assert group["remaining_amount"] == pytest.approx(9500.0)
        assert_pool_invariant(group)

    def test_deny_releases_reservation_restoring_invariant(
            self, api, incentive_manager_headers):
        """PRD §3.7: "Denial is the compensation path from `PENDING` (otherwise
        `ERR_PAYOUT_NOT_PENDING`) to the terminal `DENIED` state: the reservation
        unwinds — `reserved_total` decreases by the amount and `remaining_amount`
        increases by it — and both versions increment by 1."
        PRD §3.7: "Throughout the group's life the fiscal invariant holds:
        `max_pool_amount` always equals `paid_total` plus `reserved_total` plus
        `remaining_amount`."

        After propose (reserve 500.00) and deny (release 500.00) the group is
        restored to paid 0.00 / reserved 0.00 / remaining 10000.00.

        Design: Difficulty/compensating_invariant/pool_conservation_propose_then_deny
        """
        sc = setup_gap_closure_group(num_closed_gaps=2)
        payout = propose_payout(sc["group"]["id"], "im-1")
        denied = deny_payout(payout["id"], "im-2")
        assert denied["status"] == "DENIED"

        group = validate_success(api.get_provider_group(sc["group"]["id"],
                                                        incentive_manager_headers))
        assert group["paid_total"] == pytest.approx(0.0)
        assert group["reserved_total"] == pytest.approx(0.0)
        assert group["remaining_amount"] == pytest.approx(10000.0)
        assert_pool_invariant(group)


class TestPayoutTerminalLockdown:
    def test_payout_pay_terminal_lockdown(self, api, incentive_manager_headers):
        """PRD §3.7: "Payment moves an `APPROVED` payout (otherwise
        `ERR_PAYOUT_NOT_APPROVED`) to the terminal `PAID` state: the group's
        `paid_total` increases by the amount while `reserved_total` decreases by
        it, leaving `remaining_amount` untouched, and both the payout's and the
        group's `version` increment by 1."

        A second pay against the terminal PAID payout is rejected and the group's
        totals move exactly once.

        Design: Corner/state_machines/payout_pay_terminal_lockdown
        """
        sc = setup_gap_closure_group(num_closed_gaps=1)
        payout = propose_payout(sc["group"]["id"], "im-1")
        approve_payout(payout["id"], "im-2")
        paid = pay_payout(payout["id"], "im-2")
        assert paid["status"] == "PAID"

        resp = api.transition_incentive_payout(
            payout["id"], "PAID", make_incentive_manager_headers("im-2"))
        validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_APPROVED)

        payout_after = get_payout(payout["id"])
        assert payout_after["status"] == "PAID"
        group = validate_success(api.get_provider_group(sc["group"]["id"],
                                                        incentive_manager_headers))
        assert group["paid_total"] == pytest.approx(250.0), (
            "paid_total moves exactly once (250.00)"
        )
        assert group["remaining_amount"] == pytest.approx(9750.0)
        assert_pool_invariant(group)
