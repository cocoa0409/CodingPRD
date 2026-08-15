"""Clawback lifecycle and cascades, cash-flow projection variants, and
multi-jurisdiction allocation shares."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_qualified_entries,
    add_spend_entry,
    approve_application,
    assert_milestone_present,
    assert_program_ledger_invariant,
    create_application,
    create_production,
    disqualify_entry,
    engage_audit,
    get_application,
    get_certificate,
    get_program,
    issue_credit,
    make_producer_headers,
    open_clawback_case,
    open_program,
    qualify_entry,
    register_company,
    register_vendor,
    register_verified_vendor,
    resolve_case,
    review_vendor,
    run_accepted_audit,
    send_notice,
    set_logical_clock,
    setup_approved_application,
    setup_issued_certificate,
    submit_application,
    claim_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER1 = TEST_USERS["reviewer1_headers"]

STANDARD_ENTRIES = [
    {"category": "ATL", "amount_cents": 40_000_000,
     "spend_date": "2026-10-05T00:00:00Z", "external_invoice_ref": "INV-ATL-001"},
    {"category": "BTL", "is_resident_labor": True, "amount_cents": 100_000_000,
     "spend_date": "2026-10-12T00:00:00Z", "external_invoice_ref": "INV-BTL-002"},
    {"category": "BTL", "amount_cents": 60_000_000,
     "spend_date": "2026-10-19T00:00:00Z", "external_invoice_ref": "INV-BTL-003"},
]


class TestClawbackCreateGuards:
    def test_clawback_shortfall_exceeds_issued_rejected(self, api):
        """PRD §3.8: "The assessment base must be positive and must not exceed
        the certificate's `issued_amount_cents`; a base of zero or one exceeding
        the issued amount is rejected with `ERR_CLAWBACK_EXCEEDS_EXPOSURE`."

        Design: Corner/validations/clawback_shortfall_exceeds_issued_rejected
        """
        scenario = setup_issued_certificate()
        resp = api.create_clawback_case(
            {"application_id": scenario.application["id"],
             "trigger_reason": "MISREPRESENTATION", "penalty_mode": "AGGRAVATED",
             "shortfall_amount_cents": 70_000_000},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLAWBACK_EXCEEDS_EXPOSURE)
        data, _ = validate_paginated(api.list_clawback_cases(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert data == []


class TestNoticeAppealWindows:
    def _setup_two_noticed_cases(self, api):
        scenario = setup_issued_certificate()
        case1 = open_clawback_case(scenario.application,
                                   trigger_reason="SPEND_SHORTFALL",
                                   shortfall_amount_cents=1_000_000)
        case2 = open_clawback_case(scenario.application,
                                   trigger_reason="RESIDENCY_FAILURE",
                                   shortfall_amount_cents=1_000_000)
        case1 = send_notice(case1)
        case2 = send_notice(case2)
        return scenario, case1, case2

    def test_notice_quiet_period_blocks_sustain(self, api):
        """PRD §3.8: "Sustaining from `NOTICE_SENT` additionally requires the
        appeal window to have lapsed: the clock must stand strictly after
        `appeal_deadline_at`, and an attempt during the quiet period is rejected
        with `ERR_NOTICE_WINDOW_ACTIVE`; sustaining from `APPEALED` carries no
        such waiting period, the appeal having been heard."
        PRD §3.8: "An admin sending the notice moves the case from `OPENED` to
        `NOTICE_SENT`, stamping `notice_sent_at` and computing
        `appeal_deadline_at` as the notice instant plus the program's
        `appeal_window_days` days."

        Design: Corner/validations/notice_quiet_period_and_appeal_window_enforced
        """
        _scenario, case1, _case2 = self._setup_two_noticed_cases(api)
        assert case1["appeal_deadline_at"].startswith("2026-08-31"), (
            "notice at the 2026-08-01 default clock plus 30 appeal days")

        set_logical_clock("2026-08-10T00:00:00Z")
        resp = api.resolve_clawback_case(case1["id"], {"outcome": "SUSTAINED"},
                                         ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_ACTIVE)
        current = validate_success(api.get_clawback_case(case1["id"], ADMIN), 200)
        assert current["status"] == "NOTICE_SENT"

    def test_appeal_window_inclusive_then_closed(self, api):
        """PRD §3.8: "The owning producer may then appeal — optionally stating
        `appeal_grounds` — while the clock stands at or before
        `appeal_deadline_at`; a late appeal is rejected with
        `ERR_APPEAL_WINDOW_CLOSED`. A successful appeal stamps `appealed_at` and
        moves the case to `APPEALED`."

        Design: Corner/validations/notice_quiet_period_and_appeal_window_enforced
        """
        scenario, case1, case2 = self._setup_two_noticed_cases(api)
        producer = make_producer_headers(scenario.company["id"])

        set_logical_clock("2026-08-31T00:00:00Z")
        appealed = validate_success(api.appeal_clawback_case(
            case1["id"], producer, appeal_grounds="books under review"), 200)
        assert appealed["status"] == "APPEALED", (
            "appeal exactly at appeal_deadline_at is allowed (inclusive)")
        assert appealed["appealed_at"] is not None

        set_logical_clock("2026-09-01T00:00:00Z")
        resp = api.appeal_clawback_case(case2["id"], producer)
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
        current = validate_success(api.get_clawback_case(case2["id"], ADMIN), 200)
        assert current["status"] == "NOTICE_SENT"


class TestClawbackAssessment:
    def test_clawback_interest_capped_at_fifty_percent(self, api):
        """PRD §3.8: "Raw interest is the `shortfall_amount_cents` multiplied by
        the program's `daily_interest_rate` multiplied by the day count, rounded
        half up to whole cents, and `interest_cents` is the lesser of that raw
        interest and one half of the shortfall base rounded down to whole cents.
        Under `SIMPLE` — the default, suited to shortfalls and residency failures
        — `assessed_total_cents` is the shortfall base plus the interest."

        Design: Corner/calculations/clawback_interest_capped_at_fifty_percent
        """
        scenario = setup_issued_certificate(
            attested_atl=0, attested_btl=20_000_000,
            estimated_qualified_spend_cents=20_000_000,
            total_budget_cents=100_000_000)
        case = open_clawback_case(scenario.application,
                                  trigger_reason="SPEND_SHORTFALL",
                                  penalty_mode="SIMPLE",
                                  shortfall_amount_cents=2_000_000)
        send_notice(case)  # notice at the 2026-08-01 default clock
        set_logical_clock("2034-10-18T00:00:00Z")  # exactly 3000 calendar days

        resolved = resolve_case(case, "SUSTAINED")
        assert resolved["status"] == "SUSTAINED"
        assert resolved["interest_cents"] == 1_000_000, (
            "min(raw 2000000 * 0.0005 * 3000 = 3000000, floor(2000000 * 0.5)) "
            "— the 50% cap binds")
        assert resolved["assessed_total_cents"] == 3_000_000

    def _setup_penalty_pair(self, api):
        """Two productions, each issued a 5,000,000 certificate (attested BTL
        20,000,000 at the 0.25 standard rate), each redeemed down to a
        1,000,000 remainder; case A SIMPLE, case B AGGRAVATED, both shortfall
        2,000,000, both noticed at the default clock."""
        program = open_program()
        company = register_company()
        certs = {}
        for key, title in (("a", "Atlantic Crossing"), ("b", "Okefenokee Nights")):
            production = create_production(company, title=title,
                                           total_budget_cents=100_000_000)
            application = create_application(
                production, program, estimated_qualified_spend_cents=20_000_000)
            submit_application(application, company)
            claim_application(application)
            application = approve_application(application)
            run_accepted_audit(application, 0, 20_000_000)
            certificate = issue_credit(application)
            validate_success(api.redeem_certificate(
                certificate["id"], 4_000_000,
                make_producer_headers(company["id"])), 200)
            certs[key] = (application, certificate)
        case_a = open_clawback_case(certs["a"][0], trigger_reason="SPEND_SHORTFALL",
                                    penalty_mode="SIMPLE",
                                    shortfall_amount_cents=2_000_000)
        case_b = open_clawback_case(certs["b"][0],
                                    trigger_reason="MISREPRESENTATION",
                                    penalty_mode="AGGRAVATED",
                                    shortfall_amount_cents=2_000_000)
        send_notice(case_a)
        send_notice(case_b)
        set_logical_clock("2026-09-10T00:00:00Z")  # 40 days past notice
        return certs, case_a, case_b

    def test_clawback_simple_assessment(self, api):
        """PRD §3.8: "Under `SIMPLE` — the default, suited to shortfalls and
        residency failures — `assessed_total_cents` is the shortfall base plus
        the interest."
        PRD §3.8: "Finally, `cash_assessment_cents` is zero when the certificate
        recovery covers the assessed total, and otherwise the excess of
        `assessed_total_cents` over `recovered_from_certificate_cents`."

        Design: Difficulty/dual_variant_calc/clawback_simple_vs_aggravated_penalty
        """
        _certs, case_a, _case_b = self._setup_penalty_pair(api)
        resolved = resolve_case(case_a, "SUSTAINED")
        assert resolved["interest_cents"] == 40_000, (
            "round_half_up(2000000 * 0.0005 * 40)")
        assert resolved["assessed_total_cents"] == 2_040_000
        assert resolved["recovered_from_certificate_cents"] == 1_000_000, (
            "the certificate's entire remaining balance is forfeited")
        assert resolved["cash_assessment_cents"] == 1_040_000

    def test_clawback_aggravated_exceeds_simple_on_identical_base(self, api):
        """PRD §3.8: "Under `AGGRAVATED` — intended for misrepresentation —
        `assessed_total_cents` is the base multiplied by 1.25 and rounded half up
        to whole cents, plus the interest; for any positive base the aggravated
        total is strictly greater than the simple one."

        Design: Difficulty/dual_variant_calc/clawback_simple_vs_aggravated_penalty
        """
        certs, case_a, case_b = self._setup_penalty_pair(api)
        simple = resolve_case(case_a, "SUSTAINED")
        aggravated = resolve_case(case_b, "SUSTAINED")
        assert aggravated["interest_cents"] == 40_000, (
            "identical base and identical days yield identical interest")
        assert aggravated["assessed_total_cents"] == 2_540_000, (
            "round_half_up(2000000 * 1.25) + 40000")
        assert aggravated["recovered_from_certificate_cents"] == 1_000_000
        assert aggravated["cash_assessment_cents"] == 1_540_000
        assert (aggravated["assessed_total_cents"]
                - simple["assessed_total_cents"]) == 500_000, (
                    "only penalty_mode differs between the two cases")

        for application, certificate in certs.values():
            assert get_certificate(certificate)["status"] == "CLAWED_BACK"
            assert get_application(application)["status"] == "REVOKED"


class TestSustainCascade:
    def test_issue_then_clawback_assessment_and_recovery(self, api):
        """PRD §3.8: "The certificate moves to `CLAWED_BACK` — identically
        whether it stood `ISSUED` or `PARTIALLY_TRANSFERRED`: its entire
        `remaining_amount_cents` at that instant is forfeited,
        `recovered_from_certificate_cents` records the forfeited amount, and the
        remainder drops to zero."

        Design: Difficulty/compensating_invariant/issue_then_clawback_conserves_program_cap
        """
        scenario = setup_issued_certificate()
        case = open_clawback_case(scenario.application,
                                  trigger_reason="SPEND_SHORTFALL",
                                  penalty_mode="SIMPLE",
                                  shortfall_amount_cents=25_125_000)
        send_notice(case)  # notice at the 2026-08-01 default clock
        set_logical_clock("2026-09-10T00:00:00Z")  # 40 days, past appeal window

        resolved = resolve_case(case, "SUSTAINED")
        assert resolved["interest_cents"] == 502_500, (
            "round_half_up(25125000 * 0.0005 * 40), under the 50% cap")
        assert resolved["assessed_total_cents"] == 25_627_500
        assert resolved["recovered_from_certificate_cents"] == 60_750_000
        assert resolved["cash_assessment_cents"] == 0, (
            "the certificate recovery covers the assessment")

        certificate = get_certificate(scenario.certificate)
        assert certificate["status"] == "CLAWED_BACK"
        assert certificate["remaining_amount_cents"] == 0
        assert get_application(scenario.application)["status"] == "REVOKED"

    def test_issue_then_clawback_conserves_program_cap(self, api):
        """PRD §2.7: "Each jurisdiction program behaves as a credit ledger
        governed by one invariant: `allocated_credit_cents` plus
        `remaining_cap_cents` always equals `annual_cap_cents`."
        PRD §2.7: "Credit issuance debits the ledger — the remaining cap falls
        by the issued amount and the allocated total rises by the same amount. A
        sustained clawback restores the ledger — the amount recovered from a
        certificate returns to the remaining cap and leaves the allocated total."

        Design: Difficulty/compensating_invariant/issue_then_clawback_conserves_program_cap
        """
        scenario = setup_issued_certificate()
        mid = get_program(scenario.program)
        assert mid["allocated_credit_cents"] == 60_750_000
        assert mid["remaining_cap_cents"] == 39_250_000
        assert_program_ledger_invariant(mid)

        case = open_clawback_case(scenario.application,
                                  trigger_reason="SPEND_SHORTFALL",
                                  penalty_mode="SIMPLE",
                                  shortfall_amount_cents=25_125_000)
        send_notice(case)
        set_logical_clock("2026-09-10T00:00:00Z")
        resolve_case(case, "SUSTAINED")

        post = get_program(scenario.program)
        assert post["allocated_credit_cents"] == 0, (
            "the forfeited remainder leaves the allocated total")
        assert post["remaining_cap_cents"] == 100_000_000, (
            "the recovery returns to the remaining cap — full restoration")
        assert_program_ledger_invariant(post)


class TestDisqualifyAutoClawback:
    def _setup_issued_with_entries(self, api):
        return setup_issued_certificate(entry_specs=STANDARD_ENTRIES)

    def test_disqualify_after_issuance_recomputes_application_and_exposure(self, api):
        """PRD §3.4: "Disqualifying a previously `QUALIFIED` entry returns its
        effective amount to zero."
        PRD §3.6: "Exposure: `overissued_exposure_cents` is the amount by which
        `issued_amount_cents` exceeds the application's
        `recomputed_credit_cents`, or zero when it does not; it is recomputed
        whenever the application's totals change after issuance"

        Design: Difficulty/transitive_cascade/disqualify_after_issuance_auto_clawback
        """
        scenario = self._setup_issued_with_entries(api)
        entry_b2 = scenario.entries[2]  # BTL 60,000,000
        disqualified = disqualify_entry(
            entry_b2, reason="post-issuance audit finding: out-of-state rental",
            reviewer_user_id="reviewer-2")
        assert disqualified["status"] == "DISQUALIFIED"
        assert disqualified["effective_amount_cents"] == 0

        application = get_application(scenario.application)
        assert application["btl_qualified_cents"] == 102_500_000
        assert application["capped_total_qualified_cents"] == 142_500_000
        assert application["recomputed_credit_cents"] == 35_625_000, (
            "142500000 falls back to the 0.25 standard rate tier")
        certificate = get_certificate(scenario.certificate)
        assert certificate["overissued_exposure_cents"] == 25_125_000, (
            "60750000 issued minus 35625000 recomputed")

    def test_disqualify_after_issuance_auto_opens_shortfall_case(self, api):
        """PRD §3.8: "Cases also arise automatically: whenever a certificate's
        exposure transitions from zero to positive — through a disqualification,
        a superseding amendment, or the vendor-revocation cascade — the system
        opens a `SPEND_SHORTFALL` case at the current exposure, or, when an
        unresolved `SPEND_SHORTFALL` case already exists for the certificate (one
        standing `OPENED`, `NOTICE_SENT`, or `APPEALED`), updates that case's
        shortfall to the current exposure instead."

        Design: Difficulty/transitive_cascade/disqualify_after_issuance_auto_clawback
        """
        scenario = self._setup_issued_with_entries(api)
        disqualify_entry(scenario.entries[2],
                         reason="post-issuance audit finding",
                         reviewer_user_id="reviewer-2")

        data, meta = validate_paginated(api.list_clawback_cases(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert len(data) == 1, "exactly one case auto-opens from the cascade"
        case = data[0]
        assert case["status"] == "OPENED"
        assert case["trigger_reason"] == "SPEND_SHORTFALL"
        assert case["shortfall_amount_cents"] == 25_125_000
        assert case["certificate_id"] == scenario.certificate["id"]
        assert meta["total_count"] == 1


class TestVendorRevocationCascade:
    def _setup_two_vendors_issued(self, api):
        scenario = setup_approved_application()
        grip = register_verified_vendor(scenario.production, scenario.company,
                                        legal_name="Savannah Grip & Electric")
        star = register_verified_vendor(scenario.production, scenario.company,
                                        legal_name="Star Talent Agency")
        e_atl = add_spend_entry(scenario.application, star, scenario.company,
                                category="ATL", amount_cents=40_000_000,
                                spend_date="2026-10-05T00:00:00Z",
                                external_invoice_ref="INV-ATL-001")
        e_b1 = add_spend_entry(scenario.application, grip, scenario.company,
                               category="BTL", is_resident_labor=True,
                               amount_cents=100_000_000,
                               spend_date="2026-10-12T00:00:00Z",
                               external_invoice_ref="INV-BTL-002")
        e_b2 = add_spend_entry(scenario.application, grip, scenario.company,
                               category="BTL", amount_cents=60_000_000,
                               spend_date="2026-10-19T00:00:00Z",
                               external_invoice_ref="INV-BTL-003")
        e_atl = qualify_entry(e_atl)
        e_b1 = qualify_entry(e_b1)
        e_b2 = qualify_entry(e_b2)
        run_accepted_audit(scenario.application, 40_000_000, 162_500_000)
        certificate = issue_credit(scenario.application)
        scenario.grip = grip
        scenario.star = star
        scenario.e_atl = e_atl
        scenario.grip_entries = [e_b1, e_b2]
        scenario.certificate = certificate
        return scenario

    def test_vendor_revocation_disqualifies_only_that_vendors_entries(self, api):
        """PRD §3.2: "Revoking a vendor — the transition from `VERIFIED` to
        `REJECTED` — fires a deep cascade. Every spend entry anywhere in the
        production, across all of the production's applications in every
        jurisdiction, that names this vendor and currently stands `QUALIFIED` is
        moved to `DISQUALIFIED` with its `disqualify_reason` set to
        `VENDOR_RESIDENCY_REVOKED`."

        Design: Difficulty/transitive_cascade/vendor_revocation_deep_cascade
        """
        scenario = self._setup_two_vendors_issued(api)
        revoked = review_vendor(scenario.grip, "REJECTED",
                                reviewer_user_id="reviewer-2",
                                rejection_reason="residency affidavits invalidated")
        assert revoked["residency_status"] == "REJECTED"

        data, _ = validate_paginated(api.list_spend_entries(
            REVIEWER1, params={"vendor_id": scenario.grip["id"]}))
        assert len(data) == 2
        for entry in data:
            assert entry["status"] == "DISQUALIFIED"
            assert entry["disqualify_reason"] == "VENDOR_RESIDENCY_REVOKED"
            assert entry["effective_amount_cents"] == 0

        atl = validate_success(api.get_spend_entry(scenario.e_atl["id"], REVIEWER1),
                               200)
        assert atl["status"] == "QUALIFIED", (
            "entries of the other vendor survive the selective cascade")

    def test_vendor_revocation_recomputes_totals_exposure_and_case(self, api):
        """PRD §3.2: "Each affected application then recomputes its qualified
        totals, its capped total, its provisional and recomputed credit figures,
        and its allocation share per the rules of §3.4 and §3.9. For each
        affected application that already holds a certificate, the certificate's
        `overissued_exposure_cents` is recomputed, and a transition from zero to
        a positive exposure auto-opens — or updates the shortfall of an existing
        unresolved — `SPEND_SHORTFALL` clawback case as described in §3.8."

        Design: Difficulty/transitive_cascade/vendor_revocation_deep_cascade
        """
        scenario = self._setup_two_vendors_issued(api)
        review_vendor(scenario.grip, "REJECTED", reviewer_user_id="reviewer-2",
                      rejection_reason="residency affidavits invalidated")

        application = get_application(scenario.application)
        assert application["btl_qualified_cents"] == 0
        assert application["capped_total_qualified_cents"] == 16_000_000, (
            "the ATL cap now binds: min(40000000, floor(0.40 * 40000000))")
        assert application["recomputed_credit_cents"] == 4_000_000

        certificate = get_certificate(scenario.certificate)
        assert certificate["overissued_exposure_cents"] == 56_750_000, (
            "60750000 issued minus 4000000 recomputed")

        data, _ = validate_paginated(api.list_clawback_cases(
            ADMIN, params={"application_id": scenario.application["id"],
                           "status": "OPENED"}))
        assert len(data) == 1
        assert data[0]["trigger_reason"] == "SPEND_SHORTFALL"
        assert data[0]["shortfall_amount_cents"] == 56_750_000


class TestCashflowProjection:
    def _setup_projection(self, api):
        return setup_issued_certificate(entry_specs=STANDARD_ENTRIES)

    def test_cashflow_optimistic_schedule(self, api):
        """PRD §3.9: "`PRODUCTION_WRAP` lands on the wrap date itself and carries
        forty percent of the basis, rounded half up to whole cents.
        `AUDIT_COMPLETE` lands ninety days after the wrap date and carries thirty
        percent of the basis, likewise rounded half up. `CREDIT_ISSUANCE` lands
        one hundred eighty days after the wrap date and carries the remainder —
        the basis minus the first two milestone amounts — which is never itself
        rounded, so the three amounts always sum exactly to the basis. Under
        `OPTIMISTIC`, the default, the milestones stand at those dates at full
        face value and `expected_net_proceeds_cents` equals the basis."

        Design: Difficulty/dual_variant_calc/cashflow_optimistic_vs_conservative_schedule
        """
        scenario = self._setup_projection(api)
        projection = validate_success(api.get_cashflow_projection(
            scenario.application["id"],
            make_producer_headers(scenario.company["id"]),
            params={"variant": "OPTIMISTIC"}), 200)
        assert projection["variant"] == "OPTIMISTIC"
        assert projection["basis_credit_cents"] == 60_750_000
        assert projection["expected_net_proceeds_cents"] == 60_750_000
        milestones = projection["milestones"]
        assert_milestone_present(milestones, "PRODUCTION_WRAP", "2026-12-15",
                                 24_300_000)
        assert_milestone_present(milestones, "AUDIT_COMPLETE", "2027-03-15",
                                 18_225_000)
        assert_milestone_present(milestones, "CREDIT_ISSUANCE", "2027-06-13",
                                 18_225_000)

    def test_cashflow_conservative_discounts_and_shifts(self, api):
        """PRD §3.9: "Under `CONSERVATIVE` the credit is assumed sold on the
        transfer market: the net is the basis multiplied by the program's
        `transfer_price_floor_pct`, rounded half up to whole cents; the
        forty–thirty–remainder split is applied to that net; and every milestone
        date shifts thirty days later to reflect settlement lag."

        Design: Difficulty/dual_variant_calc/cashflow_optimistic_vs_conservative_schedule
        """
        scenario = self._setup_projection(api)
        producer = make_producer_headers(scenario.company["id"])
        optimistic = validate_success(api.get_cashflow_projection(
            scenario.application["id"], producer,
            params={"variant": "OPTIMISTIC"}), 200)
        conservative = validate_success(api.get_cashflow_projection(
            scenario.application["id"], producer,
            params={"variant": "CONSERVATIVE"}), 200)
        assert conservative["variant"] == "CONSERVATIVE"
        assert conservative["expected_net_proceeds_cents"] == 54_675_000, (
            "round_half_up(60750000 * 0.90)")
        assert conservative["expected_net_proceeds_cents"] < \
            optimistic["expected_net_proceeds_cents"]
        milestones = conservative["milestones"]
        assert_milestone_present(milestones, "PRODUCTION_WRAP", "2027-01-14",
                                 21_870_000)
        assert_milestone_present(milestones, "AUDIT_COMPLETE", "2027-04-14",
                                 16_402_500)
        assert_milestone_present(milestones, "CREDIT_ISSUANCE", "2027-07-13",
                                 16_402_500)

    def test_cashflow_basis_falls_back_to_provisional_pre_audit(self, api):
        """PRD §3.9: "The projection's `basis_credit_cents` is the application's
        `final_credit_cents` when an `ACCEPTED` audit package exists or a
        certificate has been issued, and `provisional_credit_cents` otherwise."

        Design: Corner/calculations/cashflow_basis_falls_back_to_provisional_pre_audit
        """
        scenario = setup_approved_application()
        vendor = register_verified_vendor(scenario.production, scenario.company)
        add_qualified_entries(scenario.application, vendor, scenario.company,
                              STANDARD_ENTRIES)

        projection = validate_success(api.get_cashflow_projection(
            scenario.application["id"],
            make_producer_headers(scenario.company["id"]),
            params={"variant": "OPTIMISTIC"}), 200)
        assert projection["basis_credit_cents"] == 60_750_000, (
            "no ACCEPTED package and no certificate: the basis is the "
            "provisional credit")
        assert projection["expected_net_proceeds_cents"] == 60_750_000
        assert_milestone_present(projection["milestones"], "PRODUCTION_WRAP",
                                 "2026-12-15", 24_300_000)


class TestAllocationShares:
    def test_allocation_share_recomputed_across_jurisdictions(self, api):
        """PRD §3.9: "Otherwise each application's share is its own
        `capped_total_qualified_cents` multiplied by ten thousand, divided by the
        sibling sum, rounded half up to a whole number, and then divided by one
        hundred — a percentage carrying exactly two decimal places. Shares
        recompute on every application approval and on every qualified-spend
        recompute touching any application of the production, so a change in one
        jurisdiction reprices the shares in all of them."

        Design: Corner/calculations/allocation_share_recomputed_across_jurisdictions
        """
        program_ga = open_program()
        program_nm = open_program(
            jurisdiction_code="NM", program_name="NM Film Credit FY27",
            annual_cap_cents=50_000_000, minimum_qualified_spend_cents=5_000_000,
            elevated_tier_threshold_cents=100_000_000)
        company = register_company()
        production = create_production(company, title="Split State Shoot")
        app_ga = create_application(production, program_ga,
                                    estimated_qualified_spend_cents=150_000_000)
        app_nm = create_application(production, program_nm,
                                    estimated_qualified_spend_cents=100_000_000)
        for app in (app_ga, app_nm):
            submit_application(app, company)
            claim_application(app)
        app_ga = approve_application(app_ga)
        app_nm = approve_application(app_nm)
        vendor = register_verified_vendor(production, company,
                                          legal_name="Regional Grip Services")

        e_ga = add_spend_entry(app_ga, vendor, company, category="BTL",
                               amount_cents=120_000_000,
                               spend_date="2026-10-05T00:00:00Z",
                               external_invoice_ref="INV-GA-001")
        e_nm = add_spend_entry(app_nm, vendor, company, category="BTL",
                               amount_cents=80_000_000,
                               spend_date="2026-10-06T00:00:00Z",
                               external_invoice_ref="INV-NM-001")
        qualify_entry(e_ga)
        qualify_entry(e_nm)

        share_ga = get_application(app_ga)["allocation_share_pct"]
        share_nm = get_application(app_nm)["allocation_share_pct"]
        assert share_ga == 60.0, "120000000 / 200000000 of the sibling sum"
        assert share_nm == 40.0

        e_nm2 = add_spend_entry(app_nm, vendor, company, category="BTL",
                                amount_cents=40_000_000,
                                spend_date="2026-10-07T00:00:00Z",
                                external_invoice_ref="INV-NM-002")
        qualify_entry(e_nm2)
        share_ga2 = get_application(app_ga)["allocation_share_pct"]
        share_nm2 = get_application(app_nm)["allocation_share_pct"]
        assert share_ga2 == 50.0, "120000000 / 240000000 after the NM recompute"
        assert share_nm2 == 50.0, (
            "the change in one jurisdiction reprices the shares in all of them")


class TestReverseReachability:
    def test_reverse_reachability_filtered_lists(self, api):
        """PRD §3.4: "spend entries can be listed with optional `application_id`,
        `vendor_id`, `amends_entry_id`, and `status` filters."
        PRD §3.5: "at most one live package exists per application, which is why
        filtering the audit-package list by `application_id` (or by `status`)
        returns an array of zero or one."
        PRD §3.6: "Certificates can be listed with optional `application_id` and
        `status` filters; because the relationship is one-to-one, an
        application-filtered list returns an array of zero or one."

        Design: Corner/endpoints/reverse_reachability_filtered_lists
        """
        scenario = setup_approved_application()
        producer = make_producer_headers(scenario.company["id"])
        vendor = register_vendor(scenario.production, scenario.company)
        e1 = add_spend_entry(scenario.application, vendor, company=scenario.company,
                             amount_cents=1_000_000,
                             external_invoice_ref="INV-L-001")
        e2 = add_spend_entry(scenario.application, vendor, company=scenario.company,
                             amount_cents=1_500_000,
                             external_invoice_ref="INV-L-001A",
                             amends_entry_id=e1["id"])
        engage_audit(scenario.application, "cpa-1")

        by_app, _ = validate_paginated(api.list_spend_entries(
            producer, params={"application_id": scenario.application["id"]}))
        assert {e["id"] for e in by_app} == {e1["id"], e2["id"]}

        by_vendor, _ = validate_paginated(api.list_spend_entries(
            producer, params={"vendor_id": vendor["id"]}))
        assert {e["id"] for e in by_vendor} == {e1["id"], e2["id"]}

        by_amends, _ = validate_paginated(api.list_spend_entries(
            producer, params={"amends_entry_id": e1["id"]}))
        assert [e["id"] for e in by_amends] == [e2["id"]], (
            "the self-reference is reverse-reachable")

        packages, _ = validate_paginated(api.list_audit_packages(
            producer, params={"application_id": scenario.application["id"]}))
        assert len(packages) == 1, "1:1 relationship returns an array of one"

        certificates, _ = validate_paginated(api.list_certificates(
            producer, params={"application_id": scenario.application["id"]}))
        assert certificates == [], "1:1 not-yet-created returns an empty array"
