"""Settlement sweeps, liability views, and funder reporting (PRD §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_program,
    setup_booth_scenario, setup_approved_claim, issue_tokens, redeem_serials,
    create_submission, close_day, verify_submission, decide_submission,
    create_open_day, create_settlement_run_payload, create_issuance_payload,
    assert_settlement_run,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

_SWEEP_EFFECTS_QUOTE = (
    "Each swept claim transitions `APPROVED → PAID` with its "
    "`paid_amount_cents` set equal to its `approved_amount_cents`; the "
    "vendor's `payable_cents` falls by the paid amount; and the program's "
    "`paid_out_cents` rises by the same amount, with the vendor's and the "
    "program's `version` incrementing for each swept claim — the program's "
    "`version` advancing once more for the creation of the run itself."
)
_RUN_OUTPUTS_QUOTE = (
    "The run records `swept_submission_ids` in processing order, "
    "`total_paid_cents` as the sum of the paid amounts, and "
    "`vendor_payment_count` as the number of distinct vendors receiving "
    "payment."
)
_CUTOFF_QUOTE = (
    "The sweep collects the program's claims in `APPROVED` status whose "
    "`approved_at` falls at or before `cutoff_at` — the boundary is "
    "inclusive, so a claim approved exactly at the cutoff is swept — and "
    "processes them in a pinned order: earliest `approved_at` first, ties "
    "broken by earliest `created_at`, never by `id`."
)
_FORWARD_QUOTE = (
    "The forward-looking view, `liability_forward_cents`, sums the face value "
    "of every token of the program that may still legitimately be presented — "
    "those in `ISSUED`, `REDEEMED`, or `FLAGGED` — treating flagged value as "
    "contingent exposure for pool planning."
)
_REALIZED_QUOTE = (
    "The chronological view, `liability_realized_cents`, counts only value "
    "actually presented at stalls: tokens in `REDEEMED` or `SETTLED`."
)


class TestSettlementSweepCascade:
    def test_sweep_marks_paid_and_records_run_totals(self, api):
        """PRD §3.8: "Each swept claim transitions `APPROVED → PAID` with its
        `paid_amount_cents` set equal to its `approved_amount_cents`; the
        vendor's `payable_cents` falls by the paid amount; and the program's
        `paid_out_cents` rises by the same amount, with the vendor's and the
        program's `version` incrementing for each swept claim — the program's
        `version` advancing once more for the creation of the run itself."
        PRD §3.8: "The run records `swept_submission_ids` in processing order,
        `total_paid_cents` as the sum of the paid amounts, and
        `vendor_payment_count` as the number of distinct vendors receiving
        payment."

        Design: Difficulty/transitive_cascade/settlement_sweep_cascade_marks_paid_and_recomputes_payables
        """
        sc = setup_approved_claim(charge=200, token_count=2)
        version = get_success_data(api.get_program(sc["program"]["id"], ADMIN))["version"]
        run = validate_success(api.create_settlement_run(
            create_settlement_run_payload(program_id=sc["program"]["id"],
                                          cutoff_at="2026-08-31T23:59:59Z",
                                          expected_program_version=version),
            ADMIN), expected_status=201)
        assert_settlement_run(run)
        assert run["total_paid_cents"] == 195
        assert run["vendor_payment_count"] == 1
        assert run["swept_submission_ids"] == [sc["submission"]["id"]]

        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "PAID", "hop 1: swept claim paid"
        assert submission["paid_amount_cents"] == 195

    def test_sweep_recomputes_payable_and_paid_out(self, api):
        """PRD §3.8: "Each swept claim transitions `APPROVED → PAID` with its
        `paid_amount_cents` set equal to its `approved_amount_cents`; the
        vendor's `payable_cents` falls by the paid amount; and the program's
        `paid_out_cents` rises by the same amount, with the vendor's and the
        program's `version` incrementing for each swept claim — the program's
        `version` advancing once more for the creation of the run itself."
        PRD §3.5: "The `payable_cents` figure is the vendor's
        approved-but-unpaid balance: the sum of `approved_amount_cents` over
        its claims in `APPROVED` or `PAID` status, minus the sum of
        `paid_amount_cents` over its paid claims."

        Design: Difficulty/transitive_cascade/settlement_sweep_cascade_marks_paid_and_recomputes_payables
        """
        sc = setup_approved_claim(charge=200, token_count=2)
        version = get_success_data(api.get_program(sc["program"]["id"], ADMIN))["version"]
        validate_success(api.create_settlement_run(
            create_settlement_run_payload(program_id=sc["program"]["id"],
                                          cutoff_at="2026-08-31T23:59:59Z",
                                          expected_program_version=version),
            ADMIN), expected_status=201)

        vendor = get_success_data(api.get_vendor(sc["vendor"]["id"], ADMIN))
        assert vendor["payable_cents"] == 0, "hop 2: 195 approved unpaid - 195 paid"
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["paid_out_cents"] == 195, "hop 2: program disbursed total"


class TestSettlementCutoffBoundary:
    def _setup_approved_at_pinned_clock(self, api):
        """Claim APPROVED with the logical clock pinned to 2026-08-05T12:00:00Z,
        so approved_at equals that instant."""
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 200)
        vend_id = sc["vendor"]["id"]
        t0, t1 = tokens[0], tokens[1]
        redeem_serials(vend_id, [t0["serial_number"], t1["serial_number"]])
        submission = create_submission(vend_id, sc["market_day"]["id"], [t0["id"], t1["id"]])
        close_day(sc["market_day"]["id"])
        verify_submission(submission["id"], "VERIFIED")
        validate_success(api.set_clock("2026-08-05T12:00:00Z", ADMIN))
        decide_submission(submission["id"], "APPROVED")
        sc.update({"issuance": issuance, "tokens": tokens, "submission": submission})
        return sc

    def test_cutoff_inclusive_sweeps_claim(self, api):
        """PRD §3.8: "The sweep collects the program's claims in `APPROVED`
        status whose `approved_at` falls at or before `cutoff_at` — the
        boundary is inclusive, so a claim approved exactly at the cutoff is
        swept — and processes them in a pinned order: earliest `approved_at`
        first, ties broken by earliest `created_at`, never by `id`."

        Design: Difficulty/boundary_precision_check/settlement_cutoff_inclusive_boundary
        """
        sc = self._setup_approved_at_pinned_clock(api)
        version = get_success_data(api.get_program(sc["program"]["id"], ADMIN))["version"]
        validate_success(api.create_settlement_run(
            create_settlement_run_payload(program_id=sc["program"]["id"],
                                          cutoff_at="2026-08-05T12:00:00Z",
                                          expected_program_version=version),
            ADMIN), expected_status=201)

        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "PAID", "approved_at == cutoff_at is swept"
        assert submission["approved_at"].startswith("2026-08-05T12:00:00")

    def test_cutoff_inclusive_run_totals(self, api):
        """PRD §3.8: "The sweep collects the program's claims in `APPROVED`
        status whose `approved_at` falls at or before `cutoff_at` — the
        boundary is inclusive, so a claim approved exactly at the cutoff is
        swept — and processes them in a pinned order: earliest `approved_at`
        first, ties broken by earliest `created_at`, never by `id`."
        PRD §3.8: "The run records `swept_submission_ids` in processing order,
        `total_paid_cents` as the sum of the paid amounts, and
        `vendor_payment_count` as the number of distinct vendors receiving
        payment."

        Design: Difficulty/boundary_precision_check/settlement_cutoff_inclusive_boundary
        """
        sc = self._setup_approved_at_pinned_clock(api)
        version = get_success_data(api.get_program(sc["program"]["id"], ADMIN))["version"]
        run = validate_success(api.create_settlement_run(
            create_settlement_run_payload(program_id=sc["program"]["id"],
                                          cutoff_at="2026-08-05T12:00:00Z",
                                          expected_program_version=version),
            ADMIN), expected_status=201)
        assert run["total_paid_cents"] == 195
        assert run["swept_submission_ids"] == [sc["submission"]["id"]]
        assert run["vendor_payment_count"] == 1


class TestPayableConservation:
    def test_approve_then_settle_net_zero_payable(self, api):
        """PRD §3.5: "The `payable_cents` figure is the vendor's
        approved-but-unpaid balance: the sum of `approved_amount_cents` over
        its claims in `APPROVED` or `PAID` status, minus the sum of
        `paid_amount_cents` over its paid claims."
        PRD §3.6: "Approval computes `approved_amount_cents` by the
        aggregate-rounding variant, stamps `approved_at`, moves every attached
        token still `REDEEMED` to `SETTLED`, recomputes the vendor's
        `payable_cents` upward by the approved amount, and recomputes each
        token's market-day totals — because `REDEEMED` and `SETTLED` both count
        toward `redeemed_value_cents`, the day's variance does not move."

        Design: Difficulty/compensating_invariant/approve_then_settle_conserves_zero_net_payable
        """
        sc = setup_approved_claim(charge=200, token_count=2)
        vendor_mid = get_success_data(api.get_vendor(sc["vendor"]["id"], ADMIN))
        assert vendor_mid["payable_cents"] == 195, "approved, unpaid"

        version = get_success_data(api.get_program(sc["program"]["id"], ADMIN))["version"]
        validate_success(api.create_settlement_run(
            create_settlement_run_payload(program_id=sc["program"]["id"],
                                          cutoff_at="2026-08-31T23:59:59Z",
                                          expected_program_version=version),
            ADMIN), expected_status=201)

        vendor = get_success_data(api.get_vendor(sc["vendor"]["id"], ADMIN))
        assert vendor["payable_cents"] == 0, "net-zero conservation after the sweep"

    def test_paid_out_accumulates_without_drift(self, api):
        """PRD §3.8: "Each swept claim transitions `APPROVED → PAID` with its
        `paid_amount_cents` set equal to its `approved_amount_cents`; the
        vendor's `payable_cents` falls by the paid amount; and the program's
        `paid_out_cents` rises by the same amount, with the vendor's and the
        program's `version` incrementing for each swept claim — the program's
        `version` advancing once more for the creation of the run itself."
        PRD §3.8: "Both views exclude `VOIDED` and `CONFISCATED` tokens, and
        `paid_out_cents` accumulates what settlement runs have actually
        disbursed, completing the bridge from issuance to reimbursement."

        Design: Difficulty/compensating_invariant/approve_then_settle_conserves_zero_net_payable
        """
        sc = setup_approved_claim(charge=200, token_count=2)
        version = get_success_data(api.get_program(sc["program"]["id"], ADMIN))["version"]
        validate_success(api.create_settlement_run(
            create_settlement_run_payload(program_id=sc["program"]["id"],
                                          cutoff_at="2026-08-31T23:59:59Z",
                                          expected_program_version=version),
            ADMIN), expected_status=201)

        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["paid_out_cents"] == 195
        vendor = get_success_data(api.get_vendor(sc["vendor"]["id"], ADMIN))
        assert vendor["payable_cents"] + program["paid_out_cents"] == 195, (
            "outstanding payable + paid out == approved amount, no drift")


class TestSettlementOcc:
    def test_stale_program_version_rejected(self, api):
        """PRD §2.8: "Creating a settlement run (`POST /settlement-runs`)
        requires a non-optional `expected_program_version` carrying the program
        `version` the client last observed. If the program's current `version`
        has since advanced, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so a run is never priced off a superseded approval and
        payable state. Endpoints not named here take no version field."

        Design: Corner/validations/c_val_settlement_run_stale_program_version_rejected
        """
        program = create_program(pool_cents=50000)
        assert program["version"] == 1
        resp = api.create_settlement_run(
            create_settlement_run_payload(program_id=program["id"],
                                          cutoff_at="2026-08-31T23:59:59Z",
                                          expected_program_version=program["version"] + 5),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestLiabilityViews:
    def _setup_minted_2000_redeemed_500(self, api):
        """Charge 1000 -> 2x500 base + 10x100 match (2000 face); redeem serial
        100001 (500)."""
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 1000)
        assert tokens[0]["serial_number"] == 100001
        redeem_serials(sc["vendor"]["id"], [100001])
        sc.update({"issuance": issuance, "tokens": tokens})
        return sc

    def test_liability_forward_counts_contingent_exposure(self, api):
        """PRD §3.8: "The forward-looking view, `liability_forward_cents`, sums
        the face value of every token of the program that may still
        legitimately be presented — those in `ISSUED`, `REDEEMED`, or `FLAGGED`
        — treating flagged value as contingent exposure for pool planning."
        PRD §3.8: "The chronological view, `liability_realized_cents`, counts
        only value actually presented at stalls: tokens in `REDEEMED` or
        `SETTLED`."

        Design: Difficulty/dual_variant_calc/program_liability_forward_vs_realized_diverge
        """
        sc = self._setup_minted_2000_redeemed_500(api)
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["liability_forward_cents"] == 2000, "1500 ISSUED + 500 REDEEMED"

    def test_liability_realized_counts_presented_only(self, api):
        """PRD §3.8: "The chronological view, `liability_realized_cents`,
        counts only value actually presented at stalls: tokens in `REDEEMED` or
        `SETTLED`."
        PRD §3.8: "The forward-looking view, `liability_forward_cents`, sums
        the face value of every token of the program that may still
        legitimately be presented — those in `ISSUED`, `REDEEMED`, or `FLAGGED`
        — treating flagged value as contingent exposure for pool planning."

        Design: Difficulty/dual_variant_calc/program_liability_forward_vs_realized_diverge
        """
        sc = self._setup_minted_2000_redeemed_500(api)
        program = get_success_data(api.get_program(sc["program"]["id"], ADMIN))
        assert program["liability_realized_cents"] == 500, "REDEEMED only"
        assert program["liability_forward_cents"] - program["liability_realized_cents"] == 1500, (
            "the gap is the outstanding unredeemed face value")


class TestFunderReport:
    def test_funder_report_period_filter_is_half_open(self, api):
        """PRD §3.8: "The funder report, available to `ProgramAdmin` and
        `Auditor`, accepts optional `period_start` and `period_end` bounds
        applied as a half-open window over issuance creation time —
        `period_start` inclusive, `period_end` exclusive — and returns the
        season's picture: `issued_base_cents` and `issued_match_cents`, the
        base and match value minted by in-window issuances; `redeemed_cents`,
        the value of in-window tokens that have since been redeemed or settled;
        `reimbursed_cents`, the amounts paid out through `PAID` claims; the
        current `match_pool_remaining_cents`; both liability views;
        `days_flagged_count`, the number of the program's market days currently
        sitting in `VARIANCE_FLAGGED`; and `utilization_bp`, the share of the
        season's match budget already consumed — the budget minus the remaining
        pool — scaled by ten thousand and rounded down to a whole number of
        basis points."
        PRD §3.8: "The forward-looking view, `liability_forward_cents`, sums
        the face value of every token of the program that may still
        legitimately be presented — those in `ISSUED`, `REDEEMED`, or `FLAGGED`
        — treating flagged value as contingent exposure for pool planning."

        Design: Corner/calculations/c_calc_funder_report_period_filter_is_half_open
        """
        sc = setup_booth_scenario(with_vendor=False)
        shop_id = sc["shopper"]["id"]

        def issue(charge, day_id):
            shopper = get_success_data(api.get_shopper(shop_id, BOOTH))
            return validate_success(api.create_issuance(
                create_issuance_payload(shopper_id=shop_id, market_day_id=day_id,
                                        benefit_charged_cents=charge,
                                        expected_shopper_version=shopper["version"]),
                BOOTH), expected_status=201)

        first = issue(500, sc["market_day"]["id"])  # created at clock 2026-08-01
        assert first["match_cents"] == 500

        validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
        day2 = create_open_day(sc["market"]["id"], date="2026-08-02",
                               opens_at="2026-08-02T08:00:00Z",
                               closes_at="2026-08-02T14:00:00Z")
        second = issue(300, day2["id"])  # created at clock 2026-08-02
        assert second["match_cents"] == 300

        report = validate_success(api.get_funder_report(
            sc["program"]["id"], AUDITOR,
            params={"period_start": "2026-08-02T00:00:00Z",
                    "period_end": "2026-09-01T00:00:00Z"}))
        assert report["issued_base_cents"] == 300, "only the 08-02 issuance is in [08-02, 09-01)"
        assert report["issued_match_cents"] == 300
        assert report["liability_forward_cents"] == 1600, (
            "point-in-time across all tokens: 1000 + 600 face value, none redeemed")
        assert report["match_pool_remaining_cents"] == 99200, "800 total match minted"
