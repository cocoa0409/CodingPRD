"""Events of default and noteholder direction: declaration, confirmation
cascade, quorum thresholds, endorse/withdraw oscillation, lapse, cure timing
(PRD §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    CLOCK_START, set_clock,
    setup_indenture_with_positions, create_interest_run, fund_run, execute_run,
    register_account,
    declare_default, confirm_default, cure_default, create_direction,
    endorse_direction, withdraw_endorsement,
    get_default_case, get_direction, get_indenture, get_payment_run,
    get_account, list_run_records,
    create_endorsement_payload,
    make_trust_officer_headers, make_trust_manager_headers,
    make_noteholder_headers,
)

OFFICER = make_trust_officer_headers("officer-1")
MANAGER = make_trust_manager_headers("manager-1")


class TestDefaultConfirmSuspensionCascade:
    def _setup_confirm_scenario(self, api):
        """R1 executed (records PENDING), R2 still SCHEDULED/UNFUNDED, one
        ALLEGED default case ready to confirm."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000, 250000000),
            holder_prefixes=("H-A", "H-B", "H-C"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000},
            reset_clock=False)
        r1 = create_interest_run(ctx["tranche"]["id"])
        fund_run(r1["id"], 25416667, issuer_ref="issuer-1")
        execute_run(r1["id"])
        r2 = create_interest_run(ctx["tranche"]["id"],
                                 start="2026-12-15", end="2027-06-15",
                                 pay_date="2027-06-15")
        case = declare_default(ctx["indenture"]["id"], officer_id="officer-1")
        ctx.update({"r1": r1, "r2": r2, "case": case})
        return ctx

    def test_confirm_default_suspends_runs_and_indents(self, api):
        """PRD §3.5: "Confirmation records `confirmed_by_user_id`, moves the
        case to `CONFIRMED`, and fires the full default cascade: the indenture
        moves `ACTIVE` → `DEFAULTED`, every payment run of every tranche with
        `distribution_status` `SCHEDULED` becomes `SUSPENDED`"

        Design: Difficulty/transitive_cascade/default_confirm_suspension_cascade
        """
        ctx = self._setup_confirm_scenario(api)
        confirm_default(ctx["case"]["id"], manager_id="manager-1")

        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "DEFAULTED", "link 1: indenture defaulted"
        assert indenture["active_default_count"] == 1

        r2_after = get_payment_run(ctx["r2"]["id"])
        assert r2_after["distribution_status"] == "SUSPENDED", (
            "link 2: still-SCHEDULED run suspended")
        r1_after = get_payment_run(ctx["r1"]["id"])
        assert r1_after["distribution_status"] == "DISTRIBUTED", (
            "already-executed run is not suspended")

    def test_confirm_default_holds_records_and_unpaid_totals(self, api):
        """PRD §3.5: "every `PENDING` distribution record under a
        `DISTRIBUTED` run of the indenture becomes `HELD` with its
        `allocated_cents` added to the holder's `total_unpaid_cents`, and each
        affected account's unpaid total is recomputed."

        Design: Difficulty/transitive_cascade/default_confirm_suspension_cascade
        """
        ctx = self._setup_confirm_scenario(api)
        confirm_default(ctx["case"]["id"], manager_id="manager-1")

        records = list_run_records(ctx["r1"]["id"])
        assert len(records) == 3
        for record in records:
            assert record["status"] == "HELD", "link 3: pending records held"

        expected_unpaid = [10166667, 8895833, 6354167]
        for account, want in zip(ctx["accounts"], expected_unpaid):
            account_after = get_account(account["id"])
            assert account_after["total_unpaid_cents"] == want, (
                f"link 4: unpaid total: expected {want}, "
                f"got {account_after['total_unpaid_cents']}")
            assert account_after["total_received_cents"] == 0, (
                "nothing settled: clock precedes the scheduled payment date")


class TestDirectionOscillation:
    def _setup_direction_with_positions(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000, 250000000),
            holder_prefixes=("H-A", "H-B", "H-C"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "ACCELERATE")
        ctx.update({"case": case, "direction": direction})
        return ctx

    def test_direction_flips_effective_at_quarter_then_cycles(self, api):
        """PRD §3.5: "for `ACCELERATE` and `WAIVE_DEFAULT` the direction
        becomes `EFFECTIVE` when supporting principal reaches at least one
        quarter of eligible principal, the boundary inclusive — evaluated as
        supporting multiplied by four being at least the eligible figure"
        PRD §3.5: "A withdrawal that drops support below the threshold flips
        an `EFFECTIVE` direction back to `CIRCULATING`."

        C holds exactly one quarter of the 1000000000 eligible principal.

        Design: Difficulty/non_linear_state_machine/direction_circulating_effective_oscillation
        """
        ctx = self._setup_direction_with_positions(api)
        account_c = ctx["accounts"][2]
        endorsement = endorse_direction(ctx["direction"]["id"], account_c["id"])
        assert endorsement["endorsed_principal_cents"] == 250000000

        direction = get_direction(ctx["direction"]["id"])
        assert direction["status"] == "EFFECTIVE", (
            "250000000*4 >= 1000000000 — inclusive quarter reached")

        withdraw_endorsement(endorsement["id"], account_c["id"])
        direction = get_direction(ctx["direction"]["id"])
        assert direction["status"] == "CIRCULATING", (
            "threshold lost: EFFECTIVE cycles back to CIRCULATING")
        assert direction["supporting_principal_cents"] == 0

    def test_direction_reaches_effective_again_after_withdrawal(self, api):
        """PRD §3.5: "A `Noteholder` endorses a circulating direction by
        naming its `noteholder_account_id`, which must equal the caller's
        `X-User-ID`."
        PRD §3.5: "A successful endorsement is `ACTIVE` and snapshots the
        holder's aggregate `ACTIVE` principal across the indenture into
        `endorsed_principal_cents` at endorsement time."
        PRD §3.5: "withdrawal moves the endorsement to `WITHDRAWN` and
        recomputes support"

        Design: Difficulty/non_linear_state_machine/direction_circulating_effective_oscillation
        """
        ctx = self._setup_direction_with_positions(api)
        account_a, _, account_c = ctx["accounts"]
        endorsement_c = endorse_direction(ctx["direction"]["id"], account_c["id"])
        withdraw_endorsement(endorsement_c["id"], account_c["id"])

        endorsement_a = endorse_direction(ctx["direction"]["id"], account_a["id"])
        assert endorsement_a["endorsed_principal_cents"] == 400000000
        direction = get_direction(ctx["direction"]["id"])
        assert direction["status"] == "EFFECTIVE", (
            "A's 400000000 restores support above the inclusive quarter")
        assert direction["supporting_principal_cents"] == 400000000

        from test_helpers import get_success_data
        endorsement_c_after = get_success_data(
            api.get_direction_endorsement(endorsement_c["id"], OFFICER))
        assert endorsement_c_after["status"] == "WITHDRAWN"


class TestQuorumBoundaries:
    def _setup_quarter_boundary(self, api):
        """Positions C 250000000 and R 750000000 (eligible 1000000000)."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(250000000, 750000000),
            holder_prefixes=("H-C", "H-R"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "ACCELERATE")
        ctx.update({"case": case, "direction": direction})
        return ctx

    def test_accelerate_effective_at_exact_quarter(self, api):
        """PRD §3.5: "for `ACCELERATE` and `WAIVE_DEFAULT` the direction
        becomes `EFFECTIVE` when supporting principal reaches at least one
        quarter of eligible principal, the boundary inclusive — evaluated as
        supporting multiplied by four being at least the eligible figure"

        Design: Difficulty/boundary_precision_check/accelerate_quorum_inclusive_quarter_boundary
        """
        ctx = self._setup_quarter_boundary(api)
        account_c = ctx["accounts"][0]
        endorsement = endorse_direction(ctx["direction"]["id"], account_c["id"])
        assert endorsement["endorsed_principal_cents"] == 250000000

        direction = get_direction(ctx["direction"]["id"])
        assert direction["status"] == "EFFECTIVE", (
            "exactly 25% (250000000*4 == 1000000000) is EFFECTIVE — inclusive >=")
        assert direction["eligible_principal_cents"] == 1000000000
        assert direction["supporting_principal_cents"] == 250000000

    def test_execute_accelerate_at_boundary_quorum(self, api):
        """PRD §3.5: "An executed direction becomes `EXECUTED` and applies
        its instruction: `ACCELERATE` moves the default case `CONFIRMED` →
        `ACCELERATED`, the indenture `DEFAULTED` → `ACCELERATED`, and every
        `ACTIVE` tranche to `ACCELERATED`"

        Design: Difficulty/boundary_precision_check/accelerate_quorum_inclusive_quarter_boundary
        """
        from test_helpers import get_tranche
        ctx = self._setup_quarter_boundary(api)
        endorse_direction(ctx["direction"]["id"], ctx["accounts"][0]["id"])
        direction = get_direction(ctx["direction"]["id"])
        assert direction["status"] == "EFFECTIVE"

        resp = api.execute_direction(direction["id"], MANAGER)
        executed = validate_success(resp)
        assert executed["status"] == "EXECUTED"

        case = get_default_case(ctx["case"]["id"])
        assert case["status"] == "ACCELERATED"
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "ACCELERATED"
        tranche = get_tranche(ctx["tranche"]["id"])
        assert tranche["status"] == "ACCELERATED"

    def _setup_strict_majority(self, api):
        """200000000 eligible split evenly between holders G and H; the case
        is first ACCELERATED via an inclusive-quarter ACCELERATE direction,
        then a RESCIND_ACCELERATION direction circulates."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(100000000, 100000000),
            holder_prefixes=("H-G", "H-H"),
            indenture_overrides={"name": "I2", "issuer_ref": "issuer-2"},
            tranche_overrides={"series_code": "T4", "original_principal_cents": 200000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        accelerate = create_direction(case["id"], "ACCELERATE")
        endorse_direction(accelerate["id"], ctx["accounts"][0]["id"])
        api.execute_direction(accelerate["id"], MANAGER)
        rescind = create_direction(case["id"], "RESCIND_ACCELERATION")
        ctx.update({"case": case, "accelerate": accelerate, "rescind": rescind})
        return ctx

    def test_rescind_exact_half_stays_circulating(self, api):
        """PRD §3.5: "for `RESCIND_ACCELERATION` the test is strict,
        requiring more than one half — supporting multiplied by two exceeding
        the eligible figure; both tests use integer cross-multiplication
        only."

        G alone supplies exactly half of the 200000000 eligible principal:
        100000000*2 > 200000000 is false.

        Design: Difficulty/boundary_precision_check/rescind_strict_majority_boundary
        """
        ctx = self._setup_strict_majority(api)
        endorse_direction(ctx["rescind"]["id"], ctx["accounts"][0]["id"])
        direction = get_direction(ctx["rescind"]["id"])
        assert direction["status"] == "CIRCULATING", (
            "strict > rejects exact 50%")
        assert direction["eligible_principal_cents"] == 200000000, (
            "acceleration does not extinguish voting principal")
        assert direction["supporting_principal_cents"] == 100000000

    def test_rescind_above_half_becomes_effective(self, api):
        """PRD §3.5: "for `RESCIND_ACCELERATION` the test is strict,
        requiring more than one half — supporting multiplied by two exceeding
        the eligible figure"

        G+H supply 200000000: 200000000*2 > 200000000 holds.

        Design: Difficulty/boundary_precision_check/rescind_strict_majority_boundary
        """
        ctx = self._setup_strict_majority(api)
        endorse_direction(ctx["rescind"]["id"], ctx["accounts"][0]["id"])
        mid = get_direction(ctx["rescind"]["id"])
        assert mid["status"] == "CIRCULATING"
        endorse_direction(ctx["rescind"]["id"], ctx["accounts"][1]["id"])
        direction = get_direction(ctx["rescind"]["id"])
        assert direction["status"] == "EFFECTIVE", "full support crosses the strict half"
        assert direction["supporting_principal_cents"] == 200000000


class TestSupportConservation:
    def _setup_support_scenario(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 600000000),
            holder_prefixes=("H-A", "H-R"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "ACCELERATE")
        ctx.update({"case": case, "direction": direction})
        return ctx

    def test_endorsement_support_recomputed_then_withdrawn(self, api):
        """PRD §3.5: "and starts the direction `CIRCULATING` with
        `eligible_principal_cents` — the sum of `principal_amount_cents` over
        `ACTIVE` positions of the indenture's tranches in `ACTIVE` or
        `ACCELERATED` status, so acceleration does not extinguish voting
        principal — and `supporting_principal_cents`, the sum of
        `endorsed_principal_cents` over `ACTIVE` endorsements."
        PRD §3.5: "Both aggregates are recomputed on every endorsement and
        every withdrawal."

        Design: Difficulty/compensating_invariant/endorse_withdraw_support_conservation
        """
        ctx = self._setup_support_scenario(api)
        endorsement = endorse_direction(ctx["direction"]["id"], ctx["accounts"][0]["id"])
        direction = get_direction(ctx["direction"]["id"])
        assert direction["supporting_principal_cents"] == 400000000
        assert direction["status"] == "EFFECTIVE", "400000000*4 >= 1000000000"
        assert direction["eligible_principal_cents"] == 1000000000

        withdraw_endorsement(endorsement["id"], ctx["accounts"][0]["id"])
        direction = get_direction(ctx["direction"]["id"])
        assert direction["supporting_principal_cents"] == 0, (
            "support conserved: withdrawal returns the tally to its exact prior value")

    def test_withdrawal_restores_support_to_zero(self, api):
        """PRD §3.5: "A withdrawal that drops support below the threshold
        flips an `EFFECTIVE` direction back to `CIRCULATING`."
        PRD §3.5: "withdrawal moves the endorsement to `WITHDRAWN` and
        recomputes support, collapsing the direction to `CIRCULATING` if the
        threshold is lost."

        Design: Difficulty/compensating_invariant/endorse_withdraw_support_conservation
        """
        from test_helpers import get_success_data
        ctx = self._setup_support_scenario(api)
        account_a = ctx["accounts"][0]
        endorsement = endorse_direction(ctx["direction"]["id"], account_a["id"])
        withdraw_endorsement(endorsement["id"], account_a["id"])

        direction = get_direction(ctx["direction"]["id"])
        assert direction["status"] == "CIRCULATING", "threshold lost"
        assert direction["eligible_principal_cents"] == 1000000000, "eligible unchanged"
        endorsement_after = get_success_data(
            api.get_direction_endorsement(endorsement["id"], OFFICER))
        assert endorsement_after["status"] == "WITHDRAWN"


class TestDirectionLapseAndEligibility:
    def test_direction_lapses_and_rejects_endorsement(self, api):
        """PRD §3.5: "Directions whose circulation deadline passes without
        execution are swept to `LAPSED`."
        PRD §3.5: "the direction must be `CIRCULATING` or `EFFECTIVE` with the
        logical clock strictly before `expires_at`, else
        `ERR_DIRECTION_LAPSED`."

        Design: Corner/validations/direction_lapses_via_clock_sweep
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "WAIVE_DEFAULT",
                                     expires_at="2026-06-30T00:00:00Z")

        set_clock("2026-07-01T00:00:00Z")
        direction = get_direction(direction["id"])
        assert direction["status"] == "LAPSED", "clock sweep past expires_at"

        account_a = ctx["accounts"][0]
        resp = api.endorse_direction(
            direction["id"], create_endorsement_payload(account_a["id"]),
            make_noteholder_headers(account_a["id"]))
        validate_error(resp, ApiErrorId.ERR_DIRECTION_LAPSED)

    def test_endorsement_without_position_rejected(self, api):
        """PRD §3.5: "Endorsement requires an eligible position: the holder's
        aggregate principal across `ACTIVE` positions of the indenture must
        exceed zero, else `ERR_NO_ELIGIBLE_POSITION`"

        Design: Corner/validations/endorsement_without_eligible_position_rejected
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        account_d = register_account("H-D", "Holder D", "d@x.com")  # no positions
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "ACCELERATE")

        resp = api.endorse_direction(
            direction["id"], create_endorsement_payload(account_d["id"]),
            make_noteholder_headers(account_d["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_POSITION)

    def test_duplicate_active_endorsement_rejected(self, api):
        """PRD §3.5: "at most one `ACTIVE` endorsement exists per direction
        and account, else `ERR_DUPLICATE_CONSTRAINT`"

        Design: Corner/validations/duplicate_active_endorsement_rejected
        """
        from test_helpers import get_success_data
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "ACCELERATE")
        account_a = ctx["accounts"][0]
        endorse_direction(direction["id"], account_a["id"])

        resp = api.endorse_direction(
            direction["id"], create_endorsement_payload(account_a["id"]),
            make_noteholder_headers(account_a["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONSTRAINT)

        endorsements = get_success_data(api.list_direction_endorsements(
            OFFICER, params={"direction_id": direction["id"],
                             "noteholder_account_id": account_a["id"],
                             "status": "ACTIVE"}))
        assert len(endorsements) == 1, "exactly one ACTIVE endorsement stands"


class TestCureDeadline:
    def _setup_two_confirmed_cases(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        case1 = declare_default(ctx["indenture"]["id"], default_type="PAYMENT",
                                cure_deadline="2026-06-30T00:00:00Z")
        case2 = declare_default(ctx["indenture"]["id"], default_type="CROSS_DEFAULT",
                                cure_deadline="2026-06-30T00:00:00Z")
        confirm_default(case1["id"])
        confirm_default(case2["id"])
        ctx.update({"case1": case1, "case2": case2})
        return ctx

    def test_cure_at_exact_deadline_valid(self, api):
        """PRD §3.5: "A `TrustManager` may cure a `CONFIRMED` case while the
        logical clock reads at or before `cure_deadline` — a cure at the exact
        deadline instant is valid, and a cure attempted later is rejected with
        `ERR_CURE_DEADLINE_PASSED`."

        Design: Corner/validations/cure_deadline_equality_and_expiry
        """
        ctx = self._setup_two_confirmed_cases(api)
        set_clock("2026-06-30T00:00:00Z")  # exactly the deadline instant
        cured = cure_default(ctx["case1"]["id"], manager_id="manager-1")
        assert cured["status"] == "CURED", "equality cures"

    def test_cure_one_second_past_deadline_rejected(self, api):
        """PRD §3.5: "A `TrustManager` may cure a `CONFIRMED` case while the
        logical clock reads at or before `cure_deadline` — a cure at the exact
        deadline instant is valid, and a cure attempted later is rejected with
        `ERR_CURE_DEADLINE_PASSED`."

        Design: Corner/validations/cure_deadline_equality_and_expiry
        """
        ctx = self._setup_two_confirmed_cases(api)
        set_clock("2026-06-30T00:00:00Z")
        cure_default(ctx["case1"]["id"], manager_id="manager-1")
        set_clock("2026-06-30T00:00:01Z")  # one second past

        resp = api.cure_default_case(ctx["case2"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CURE_DEADLINE_PASSED)
        case2_after = get_default_case(ctx["case2"]["id"])
        assert case2_after["status"] == "CONFIRMED", "unchanged"
