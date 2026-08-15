"""True-up reconciliation: provisional vs final share variants, rounding
order, credit waterfall, invoice issuance, late fees, exact payment, disputes,
segregation of duties, and supersede.

PRD §3.9 (finance workflow), §3.1 (provisional waterfall), §2.9 (SoD).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_instant_equal,
    assert_actual_cost_entry,
    create_project,
    invite_participation,
    commit_participation,
    mobilize_project,
    install_participation,
    create_actual_cost_entry_payload,
    setup_reconciliation_project,
    post_actual_costs,
    create_true_up_run,
    publish_true_up_run,
    list_run_invoices,
    make_coordinator_headers,
    make_pm_headers,
    make_finance_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]


def _rounding_project(api):
    """3-party project, estimate 1000001, bp 3333/3333/3334, all COMMITTED,
    then MOBILIZE."""
    project = create_project(name="Rounding Project", rule20_credit_cents=0,
                             estimated_total_cost_cents=1000001,
                             target_cutover_on="2026-12-31T00:00:00Z",
                             contingency_days=0)
    parts = []
    for name, utype, bp, seq in (
        ("U1", "ELECTRIC", 3333, 1),
        ("U2", "TELECOM", 3333, 2),
        ("U3", "CATV", 3334, 3),
    ):
        p = invite_participation(project["id"], name, utype, bp, seq)
        parts.append(commit_participation(p["id"]))
    project = mobilize_project(project["id"])
    return project, parts


class TestProvisionalRoundingRemainder:
    def test_remainder_cent_lands_on_lowest_sequence_order(self, api):
        """PRD §3.1: "On success, the system computes each committed
        participant's `provisional_share_cents` by waterfall allocation: taking
        the project's estimated total cost, each participant's raw share is the
        total multiplied by its basis points and divided by ten thousand,
        rounded half up to a whole cent, computed per participant in the pinned
        order (ascending `sequence_order`, ties by ascending `created_at`); the
        remainder — the estimated total minus the sum of those raw shares — is
        then distributed one cent at a time, added when the remainder is
        positive and removed when negative, walking participants in that same
        pinned order, which never wraps because the absolute remainder is
        always smaller than the participant count."

        Design: Difficulty/combinatorial_formula/provisional_share_rounding_remainder
        """
        _project, parts = _rounding_project(api)
        shares = [
            validate_success(api.get_participation(p["id"], PM), 200)["provisional_share_cents"]
            for p in parts
        ]
        # raw rounds to 333300/333300/333400 (sum 1000000); the +1 cent
        # remainder walks to sequence_order 1 first.
        assert shares == [333301, 333300, 333400], (
            f"per-participant rounding first, remainder reconciled in order: {shares}"
        )

    def test_provisional_shares_sum_to_estimate(self, api):
        """PRD §3.1: "The invariant after every run of this computation is that
        the provisional shares of the active participants sum exactly to the
        estimated total."

        Design: Difficulty/combinatorial_formula/provisional_share_rounding_remainder
        """
        project, parts = _rounding_project(api)
        shares = [
            validate_success(api.get_participation(p["id"], PM), 200)["provisional_share_cents"]
            for p in parts
        ]
        assert sum(shares) == 1000001 == project["estimated_total_cost_cents"]


class TestProvisionalVsFinalDivergence:
    def _setup(self, api):
        """3-party project (bp 3333/3333/3334, estimate 1000001, credit 200000)
        driven to RECONCILIATION with all participants INSTALLED; actuals
        900000 JOINT_TRENCH + 50000 EXCLUSIVE on P2 posted."""
        env = setup_reconciliation_project(
            [
                {"utility_name": "U-Elec", "utility_type": "ELECTRIC", "cost_share_bp": 3333, "sequence_order": 1, "has_separation_waiver": False},
                {"utility_name": "U-Tel", "utility_type": "TELECOM", "cost_share_bp": 3333, "sequence_order": 2, "has_separation_waiver": False},
                {"utility_name": "U-Catv", "utility_type": "CATV", "cost_share_bp": 3334, "sequence_order": 3, "has_separation_waiver": False},
            ],
            project_overrides={
                "name": "Rule20 Alpha", "rule20_credit_cents": 200000,
                "estimated_total_cost_cents": 1000001,
                "target_cutover_on": "2026-12-31T00:00:00Z", "contingency_days": 0,
            },
            with_slots=[
                {"participation_index": 0, "depth_top_inches": 36, "depth_bottom_inches": 60,
                 "install_start_at": "2026-09-01T00:00:00Z", "install_end_at": "2026-09-03T00:00:00Z"},
                {"participation_index": 1, "depth_top_inches": 12, "depth_bottom_inches": 24,
                 "install_start_at": "2026-09-03T00:00:00Z", "install_end_at": "2026-09-05T00:00:00Z"},
            ],
        )
        post_actual_costs(env["project"]["id"], [
            {"cost_code": "JOINT_TRENCH", "amount_cents": 900000,
             "incurred_on": "2026-09-20T00:00:00Z"},
            {"cost_code": "EXCLUSIVE", "participation_id": env["participations"][1]["id"],
             "amount_cents": 50000, "incurred_on": "2026-09-21T00:00:00Z"},
        ], submitter="fin-1")
        return env

    def test_provisional_variant_prices_the_estimate(self, api):
        """PRD §3.1: "On success, the system computes each committed
        participant's `provisional_share_cents` by waterfall allocation: taking
        the project's estimated total cost, each participant's raw share is the
        total multiplied by its basis points and divided by ten thousand,
        rounded half up to a whole cent, computed per participant in the pinned
        order (ascending `sequence_order`, ties by ascending `created_at`)".
        PRD §3.9: "Where the provisional waterfall priced the estimate and
        ignored actuals, credits, and exclusives, this final variant prices
        audited actuals — identical participation data can and does produce
        different numbers."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_share_divergence
        """
        env = self._setup(api)
        p2 = env["participations"][1]
        before = validate_success(api.get_participation(p2["id"], PM), 200)
        assert before["provisional_share_cents"] == 333300, (
            f"provisional variant on estimate 1000001 at bp 3333, got "
            f"{before['provisional_share_cents']}"
        )
        assert before["final_share_cents"] is None, (
            "final share stays null until the first draft true-up run computes it"
        )

    def test_final_variant_prices_actuals_with_credit_waterfall(self, api):
        """PRD §3.9: "The Rule 20 credit then consumes in participation order:
        starting from the project's `rule20_credit_cents`, each participant in
        turn absorbs the smaller of the remaining credit and its own gross
        share, the remainder shrinking as the walk proceeds; the run's
        `rule20_credit_applied_cents` is the pool minus whatever remains, and
        never exceeds the pool. Each participant's `final_share_cents` is its
        gross share minus its absorbed credit plus its exclusive total, and
        this value is also written back onto the participation itself — before
        the first draft run exists, the participation's `final_share_cents` is
        null. The delta is the final share minus the provisional share, and the
        refund is the absolute value of a negative delta — zero when the delta
        is positive."
        PRD §3.9: "A successful publish stamps `published_by_user_id`,
        refreshes the project's `latest_true_up_run_id`, and issues an invoice
        to every non-withdrawn participation whose `delta_cents` is greater
        than zero — nothing is billed for a zero or negative delta."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_share_divergence
        """
        env = self._setup(api)
        p1, p2, p3 = [p["id"] for p in env["participations"]]

        run = create_true_up_run(env["project"]["id"], creator="fin-1")
        run = publish_true_up_run(run["id"], publisher="pm-1")

        run_data = validate_success(api.get_true_up_run(run["id"], make_finance_headers("fin-1")), 200)
        assert run_data["total_actual_cost_cents"] == 950000
        assert run_data["rule20_credit_applied_cents"] == 200000
        lines = {line["participation_id"]: line for line in run_data["lines"]}

        assert lines[p1]["gross_share_cents"] == 299970
        assert lines[p1]["credit_cents"] == 200000, "credit waterfall absorbs on P1 first"
        assert lines[p1]["final_share_cents"] == 99970
        assert lines[p1]["delta_cents"] == -233331
        assert lines[p1]["refund_cents"] == 233331

        assert lines[p2]["gross_share_cents"] == 299970
        assert lines[p2]["credit_cents"] == 0
        assert lines[p2]["exclusive_cents"] == 50000
        assert lines[p2]["final_share_cents"] == 349970
        assert lines[p2]["delta_cents"] == 16670
        assert 333300 != 349970, "identical participation data, different variants, different money"

        assert lines[p3]["gross_share_cents"] == 300060
        assert lines[p3]["final_share_cents"] == 300060
        assert lines[p3]["delta_cents"] == -33340

        invoices = list_run_invoices(run["id"])
        assert len(invoices) == 1, (
            f"negative deltas produce refunds, not invoices; got {len(invoices)} invoices"
        )
        assert invoices[0]["participation_id"] == p2
        assert invoices[0]["principal_cents"] == 16670


class TestLateFeeTierPinnedOnPrincipal:
    def _setup(self, api):
        """2-party project (bp 5000/5000, estimate 1000000, credit 0) driven to
        a published run with joint actuals 20999998; each delta is 9999999."""
        env = setup_reconciliation_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 5000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 5000, "sequence_order": 2},
            ],
            project_overrides={
                "name": "Tier Project", "rule20_credit_cents": 0,
                "estimated_total_cost_cents": 1000000,
                "target_cutover_on": "2026-12-31T00:00:00Z", "contingency_days": 0,
            },
            task_type="LANDSCAPE",
        )
        post_actual_costs(env["project"]["id"], [
            {"cost_code": "JOINT_TRENCH", "amount_cents": 20999998,
             "incurred_on": "2026-09-20T00:00:00Z"},
        ], submitter="fin-1")
        run = create_true_up_run(env["project"]["id"], creator="fin-1")
        publish_true_up_run(run["id"], publisher="pm-1")
        env["invoices"] = list_run_invoices(run["id"])
        return env

    def test_fee_tier_keyed_on_principal_not_post_fee_total(self, api):
        """PRD §3.9: "The rate is keyed on `principal_cents` alone: two percent
        when the principal is at least one hundred thousand dollars (10000000
        cents), one and a half percent below that, and the fee never feeds back
        into the tier. The `late_fee_cents` is the principal multiplied by the
        rate and by the number of periods, rounded half up to a whole cent, and
        `amount_due_cents` is `principal_cents` plus `late_fee_cents`."
        PRD §3.9: "No fee accrues until the invoice is at least thirty days
        past `due_on`; from there, lateness is counted in complete thirty-day
        periods — thirty to fifty-nine days overdue is one period, sixty days
        is two — where the days overdue are the whole days between `due_on` and
        the clock."

        Design: Difficulty/combinatorial_formula/late_fee_tier_pinned_on_principal
        """
        env = self._setup(api)
        inv1 = env["invoices"][0]
        validate_success(api.set_clock("2026-09-30T00:00:00Z", PM), 200)
        data = validate_success(api.get_invoice(inv1["id"], PM), 200)
        assert data["principal_cents"] == 9999999, (
            f"principal below the 10000000 threshold, got {data['principal_cents']}"
        )
        # 30 days overdue -> 1 period; round_half_up(9999999 * 0.015 * 1) = 150000
        assert data["late_fee_cents"] == 150000, (
            f"STANDARD rate applies even though the post-fee total crosses the tier: "
            f"{data['late_fee_cents']}"
        )
        assert data["amount_due_cents"] == 10149999, (
            "the post-fee total crosses 10000000 yet the tier stays STANDARD "
            "(pinned order: principal -> tier -> fee)"
        )

    def test_symmetric_participation_same_standard_tier(self, api):
        """PRD §3.9: "The rate is keyed on `principal_cents` alone: two percent
        when the principal is at least one hundred thousand dollars (10000000
        cents), one and a half percent below that, and the fee never feeds back
        into the tier."
        PRD §3.9: "Invoices are created in participation order (ascending
        `sequence_order`, ties by ascending `created_at`), each with
        `principal_cents` equal to the delta, `issued_on` stamped from the
        clock, `due_on` exactly thirty days after issuance, and status
        `ISSUED`; every participation that receives one moves `INSTALLED →
        BILLED` at that moment."

        Design: Difficulty/combinatorial_formula/late_fee_tier_pinned_on_principal
        """
        env = self._setup(api)
        inv1, inv2 = env["invoices"]
        validate_success(api.set_clock("2026-09-30T00:00:00Z", PM), 200)
        data2 = validate_success(api.get_invoice(inv2["id"], PM), 200)
        assert data2["late_fee_cents"] == 150000, (
            f"symmetric participation accrues the same fee, got {data2['late_fee_cents']}"
        )
        # exact-change payment of the fee-inclusive amount settles the invoice
        p1_id = inv1["participation_id"]
        pay = api.transition_invoice(
            inv1["id"], {"to": "PAID", "paid_amount_cents": 10149999},
            make_coordinator_headers(p1_id))
        paid = validate_success(pay, 200)
        assert paid["status"] == "PAID"


class TestLateFeeGraceDayBoundary:
    def _setup(self, api):
        """2-party project (bp 7000/3000, estimate 10000000, credit 1000000)
        published at clock 2026-08-01 with joint actuals 12000000 and EXCLUSIVE
        1000000 on P2; invoices: P1 400000 (idx 0), P2 1600000 (idx 1), due
        2026-08-31."""
        env = setup_reconciliation_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            project_overrides={
                "name": "Fee Project", "rule20_credit_cents": 1000000,
                "estimated_total_cost_cents": 10000000,
                "target_cutover_on": "2026-12-31T00:00:00Z", "contingency_days": 0,
            },
            task_type="IRRIGATION",
        )
        post_actual_costs(env["project"]["id"], [
            {"cost_code": "JOINT_TRENCH", "amount_cents": 12000000,
             "incurred_on": "2026-09-20T00:00:00Z"},
            {"cost_code": "EXCLUSIVE", "participation_id": env["participations"][1]["id"],
             "amount_cents": 1000000, "incurred_on": "2026-09-21T00:00:00Z"},
        ], submitter="fin-1")
        run = create_true_up_run(env["project"]["id"], creator="fin-1")
        publish_true_up_run(run["id"], publisher="pm-1")
        env["invoices"] = list_run_invoices(run["id"])
        return env

    def test_grace_period_29_and_30_days(self, api):
        """PRD §3.9: "Invoices accrue late fees against the logical clock,
        evaluated fresh at every read. No fee accrues until the invoice is at
        least thirty days past `due_on`; from there, lateness is counted in
        complete thirty-day periods — thirty to fifty-nine days overdue is one
        period, sixty days is two — where the days overdue are the whole days
        between `due_on` and the clock."
        PRD §3.9: "Payment is exact-change only: the owning `UtilityCoordinator`
        pays by submitting `paid_amount_cents`, which must equal
        `amount_due_cents` as of the clock — principal plus whatever late fee
        has accrued — with any mismatch rejected as
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/late_fee_grace_day_boundary
        """
        env = self._setup(api)
        inv1 = env["invoices"][0]
        assert inv1["principal_cents"] == 400000

        validate_success(api.set_clock("2026-09-29T00:00:00Z", PM), 200)
        at29 = validate_success(api.get_invoice(inv1["id"], PM), 200)
        assert at29["late_fee_cents"] == 0 and at29["amount_due_cents"] == 400000, (
            "29 days overdue is still inside the 30-day grace"
        )

        validate_success(api.set_clock("2026-09-30T00:00:00Z", PM), 200)
        at30 = validate_success(api.get_invoice(inv1["id"], PM), 200)
        # exactly 30 days -> 1 period; round_half_up(400000 * 0.015 * 1) = 6000
        assert at30["late_fee_cents"] == 6000, f"got {at30['late_fee_cents']}"
        assert at30["amount_due_cents"] == 406000

        pay = api.transition_invoice(
            inv1["id"], {"to": "PAID", "paid_amount_cents": 406000},
            make_coordinator_headers(inv1["participation_id"]))
        paid = validate_success(pay, 200)
        assert paid["status"] == "PAID", (
            "payment exactly equal to the fee-inclusive amount_due succeeds"
        )

    def test_two_periods_at_60_days_and_settlement_cascade(self, api):
        """PRD §3.9: "No fee accrues until the invoice is at least thirty days
        past `due_on`; from there, lateness is counted in complete thirty-day
        periods — thirty to fifty-nine days overdue is one period, sixty days
        is two — where the days overdue are the whole days between `due_on` and
        the clock."
        PRD §3.9: "Success moves the invoice `ISSUED → PAID`, stamps `paid_on`,
        and when every invoice of that participation has reached `PAID` or
        `VOID`, the participation cascades `BILLED → SETTLED`."

        Design: Difficulty/boundary_precision_check/late_fee_grace_day_boundary
        """
        env = self._setup(api)
        inv1, inv2 = env["invoices"]
        p1_id = inv1["participation_id"]

        validate_success(api.set_clock("2026-09-30T00:00:00Z", PM), 200)
        validate_success(api.transition_invoice(
            inv1["id"], {"to": "PAID", "paid_amount_cents": 406000},
            make_coordinator_headers(p1_id)), 200)

        validate_success(api.set_clock("2026-10-30T00:00:00Z", PM), 200)
        at60 = validate_success(api.get_invoice(inv2["id"], PM), 200)
        # 60 days -> floor(60/30) = 2 periods on principal 1600000 at 1.5%
        assert at60["late_fee_cents"] == 48000, f"got {at60['late_fee_cents']}"
        assert at60["amount_due_cents"] == 1648000
        pay = api.transition_invoice(
            inv2["id"], {"to": "PAID", "paid_amount_cents": 1648000},
            make_coordinator_headers(inv2["participation_id"]))
        assert validate_success(pay, 200)["status"] == "PAID"

        p1 = validate_success(api.get_participation(p1_id, PM), 200)
        assert p1["status"] == "SETTLED", (
            f"payment cascades BILLED -> SETTLED once its invoices are final, got {p1['status']}"
        )


class TestTrueUpPrerequisites:
    def _setup(self, api):
        """Golden path to RECONCILIATION with P1 INSTALLED and P2 left at
        MOBILIZED (never marked INSTALLED)."""
        return setup_reconciliation_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            project_overrides={
                "name": "Prereq Project", "rule20_credit_cents": 0,
                "estimated_total_cost_cents": 10000000,
                "target_cutover_on": "2026-12-31T00:00:00Z", "contingency_days": 0,
            },
            install_indexes=[0],
            mobilize_only_indexes=[1],
        )

    def test_trueup_blocked_by_uninstalled_participation(self, api):
        """PRD §3.9: "Three prerequisites gate creation — the project must be
        in `RECONCILIATION`, every trench segment must be `CLOSED`, and every
        non-withdrawn participation must be `INSTALLED`, `BILLED`, or
        `SETTLED` — with any failure rejected as `ERR_TRUEUP_PREREQUISITES`."

        Design: Difficulty/cross_entity_state_dependency/trueup_requires_participations_installed
        """
        env = self._setup(api)
        project = validate_success(api.get_project(env["project"]["id"], PM), 200)
        resp = api.create_true_up_run(
            {"project_id": env["project"]["id"],
             "expected_project_version": project["version"]},
            make_finance_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_TRUEUP_PREREQUISITES)

    def test_trueup_created_once_all_participations_installed(self, api):
        """PRD §3.9: "Three prerequisites gate creation — the project must be
        in `RECONCILIATION`, every trench segment must be `CLOSED`, and every
        non-withdrawn participation must be `INSTALLED`, `BILLED`, or
        `SETTLED` — with any failure rejected as `ERR_TRUEUP_PREREQUISITES`."
        PRD §3.9: "The new run starts in `DRAFT`, records `created_by_user_id`
        from the header, bumps the project `version` by one, and becomes the
        project's `latest_true_up_run_id`."

        Design: Difficulty/cross_entity_state_dependency/trueup_requires_participations_installed
        """
        env = self._setup(api)
        p2 = env["participations"][1]
        install_participation(p2["id"])  # MOBILIZED -> INSTALLED (holds no slots)
        project = validate_success(api.get_project(env["project"]["id"], PM), 200)
        resp = api.create_true_up_run(
            {"project_id": env["project"]["id"],
             "expected_project_version": project["version"]},
            make_finance_headers("fin-1"))
        run = validate_success(resp, 201)
        assert run["status"] == "DRAFT"


class TestInvoiceDisputeCycle:
    def test_invoice_dispute_resolution_and_exact_payment_cycle(self, api):
        """PRD §3.9: "The owning coordinator moves `ISSUED → DISPUTED` with a
        `reason`; the `ProgramManager` resolves the dispute (`DISPUTED →
        ISSUED`) optionally carrying `adjusted_principal_cents`, which when
        provided must be greater than zero (`ERR_VALIDATION`) and replaces
        `principal_cents`, after which the late fee recomputes from the new
        principal."
        PRD §3.9: "Payment is exact-change only: the owning `UtilityCoordinator`
        pays by submitting `paid_amount_cents`, which must equal
        `amount_due_cents` as of the clock — principal plus whatever late fee
        has accrued — with any mismatch rejected as
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Success moves the invoice
        `ISSUED → PAID`, stamps `paid_on`, and when every invoice of that
        participation has reached `PAID` or `VOID`, the participation cascades
        `BILLED → SETTLED`."

        Design: Corner/endpoints/invoice_dispute_resolution_and_exact_payment_cycle
        """
        env = setup_reconciliation_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            project_overrides={
                "name": "Inv Project", "rule20_credit_cents": 1000000,
                "estimated_total_cost_cents": 10000000,
                "target_cutover_on": "2026-12-31T00:00:00Z", "contingency_days": 0,
            },
        )
        post_actual_costs(env["project"]["id"], [
            {"cost_code": "JOINT_TRENCH", "amount_cents": 12000000,
             "incurred_on": "2026-09-20T00:00:00Z"},
            {"cost_code": "EXCLUSIVE", "participation_id": env["participations"][1]["id"],
             "amount_cents": 1000000, "incurred_on": "2026-09-21T00:00:00Z"},
        ], submitter="fin-1")
        run = create_true_up_run(env["project"]["id"], creator="fin-1")
        publish_true_up_run(run["id"], publisher="pm-1")
        inv1 = list_run_invoices(run["id"])[0]
        p1_id = env["participations"][0]["id"]
        assert inv1["principal_cents"] == 400000, (
            f"delta = 8400000 gross - 1000000 credit - 7000000 provisional, got "
            f"{inv1['principal_cents']}"
        )

        disputed = validate_success(api.transition_invoice(
            inv1["id"], {"to": "DISPUTED", "reason": "wrong base"},
            make_coordinator_headers(p1_id)), 200)
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(api.transition_invoice(
            inv1["id"], {"to": "ISSUED", "adjusted_principal_cents": 450000}, PM), 200)
        assert resolved["status"] == "ISSUED"
        assert resolved["principal_cents"] == 450000, "adjustment replaces principal"

        resp = api.transition_invoice(
            inv1["id"], {"to": "PAID", "paid_amount_cents": 400000},
            make_coordinator_headers(p1_id))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        paid = validate_success(api.transition_invoice(
            inv1["id"], {"to": "PAID", "paid_amount_cents": 450000},
            make_coordinator_headers(p1_id)), 200)
        assert paid["status"] == "PAID"
        assert_instant_equal(paid["paid_on"], "2026-08-01T00:00:00Z",
                             "paid_on stamps the startup clock")

        p1 = validate_success(api.get_participation(p1_id, PM), 200)
        assert p1["status"] == "SETTLED", "all of P1's invoices final -> SETTLED"


class TestSegregationOfDuties:
    def test_segregation_of_duties_then_publish_and_supersede(self, api):
        """PRD §2.9: "Only a `ProgramManager` may publish a run, and
        publication is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) in
        two cases: when the publisher's `X-User-ID` equals the run's
        `created_by_user_id`, and when the publisher's `X-User-ID` equals the
        `submitted_by_user_id` of any actual cost entry included in the run."
        PRD §3.9: "Creating a run supersedes: any previously `PUBLISHED` run of
        the same project flips to `SUPERSEDED`, and its invoices still in
        `ISSUED` or `DISPUTED` flip to `VOID`."

        Design: Corner/endpoints/segregation_of_duties_then_publish_and_supersede
        """
        env = setup_reconciliation_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            project_overrides={
                "name": "SoD Project", "rule20_credit_cents": 1000000,
                "estimated_total_cost_cents": 10000000,
                "target_cutover_on": "2026-12-31T00:00:00Z", "contingency_days": 0,
            },
            task_type="LANDSCAPE",
        )
        post_actual_costs(env["project"]["id"], [
            {"cost_code": "JOINT_TRENCH", "amount_cents": 12000000,
             "incurred_on": "2026-09-20T00:00:00Z"},
            {"cost_code": "EXCLUSIVE", "participation_id": env["participations"][1]["id"],
             "amount_cents": 1000000, "incurred_on": "2026-09-21T00:00:00Z"},
        ], submitter="fin-1")
        run1 = create_true_up_run(env["project"]["id"], creator="fin-1")

        # Publisher 'fin-1' both created the run and submitted included costs.
        resp = api.transition_true_up_run(
            run1["id"], {"to": "PUBLISHED"}, make_pm_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        published = publish_true_up_run(run1["id"], publisher="pm-7")
        assert published["status"] == "PUBLISHED"
        inv1 = list_run_invoices(run1["id"])[0]

        run2 = create_true_up_run(env["project"]["id"], creator="fin-2")
        assert run2["status"] == "DRAFT"

        run1_after = validate_success(
            api.get_true_up_run(run1["id"], make_finance_headers("fin-2")), 200)
        assert run1_after["status"] == "SUPERSEDED"
        inv_after = validate_success(api.get_invoice(inv1["id"], PM), 200)
        assert inv_after["status"] == "VOID", (
            "supersede cascade voids the prior run's open invoices"
        )


class TestActualCostEntryImmutability:
    def test_actual_cost_entry_is_immutable(self, api):
        """PRD §2.4: "An `ActualCostEntry` is append-only: it carries `id` and
        `created_at` only, has no `updated_at` and no `version`, and exposes no
        update or transition endpoints. Once appended, a cost entry is
        immutable; corrections take the form of new entries."
        PRD §3.9: "The server records the submitter's `X-User-ID` as
        `submitted_by_user_id`, anchoring the segregation-of-duties check at
        publication."

        Design: Corner/entities/actual_cost_entry_is_immutable
        """
        project = create_project(name="Immutable", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        entry = validate_success(api.create_actual_cost_entry(
            create_actual_cost_entry_payload(
                project["id"], cost_code="JOINT_TRENCH", amount_cents=12345,
                incurred_on="2026-09-01T00:00:00Z"),
            make_finance_headers("fin-1")), 201)
        data = validate_success(
            api.get_actual_cost_entry(entry["id"], make_finance_headers("fin-1")), 200)
        assert data["submitted_by_user_id"] == "fin-1", "system-stamped from X-User-ID"
        assert data["amount_cents"] == 12345
        assert_actual_cost_entry(data)
