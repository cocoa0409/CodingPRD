"""License agreement lifecycle: fee schedule, execution gates, termination, renewal."""
import pytest

from test_helpers import (
    ADMIN, ESM, FIN, REP,
    AgreementStatus, ApiClient, ApiErrorId, EVENT_E1, SEASON2, SuiteStatus,
    activate_account, execute_agreement, get_license_fee_invoice,
    get_single_invoice, list_invoice_rows, make_account, make_active_account,
    make_draft_agreement, make_event, make_executed_agreement, make_issued_invoice,
    make_season, make_suite, make_venue, make_waitlist_entry,
    make_account_holder_headers, pay_invoice_in_full, set_clock,
    setup_active_agreement, setup_renewal_offer, submit_agreement,
    validate_error, validate_paginated, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


class TestFeeScheduleVariants:
    def test_fee_schedule_compounds_on_rounded_step(self, api: ApiClient):
        """PRD §3.3: "the season-one fee equals `base_annual_fee_cents`, and each
        subsequent season's fee is the previous season's already-rounded fee
        multiplied by one plus the escalator — `escalator_bp` divided by ten
        thousand — with the product rounded half-up to a whole cent at every season
        step."
        Design: Difficulty/dual_variant_calc/license_fee_rounded_step_beats_base_indexed
        """
        s = setup_active_agreement(
            num_seasons=1,
            suite_over=dict(suite_code="P-001", tier="PLATINUM", capacity_seats=12,
                            base_annual_fee_cents=20000000, f_b_minimum_cents=6000000),
            agreement_over=dict(term_seasons=4, base_annual_fee_cents=5001208,
                                escalator_bp=625, f_b_minimum_cents=6000000))
        ag = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert ag["fee_schedule_cents"] == [5001208, 5313784, 5645896, 5998765], (
            f"rounded_step schedule expected, got {ag['fee_schedule_cents']} "
            "(base_indexed would read 5645895 / 5998763 from season 3)")

    def test_full_season_one_fee_when_executed_before_season_start(self, api: ApiClient):
        """PRD §3.3: "The first invoice is a `LICENSE_FEE` invoice, created already
        `ISSUED` with `due_on` set thirty days after the clock, covering the
        season-one fee — prorated when execution happens after the season has begun."
        Design: Difficulty/dual_variant_calc/license_fee_rounded_step_beats_base_indexed
        """
        s = setup_active_agreement(
            num_seasons=1,
            suite_over=dict(suite_code="P-001", tier="PLATINUM", capacity_seats=12,
                            base_annual_fee_cents=20000000, f_b_minimum_cents=6000000),
            agreement_over=dict(term_seasons=4, base_annual_fee_cents=5001208,
                                escalator_bp=625, f_b_minimum_cents=6000000))
        inv = get_license_fee_invoice(s["agreement"]["id"])
        # Executed at 2026-08-01, before the season's 2026-09-01 start: no proration.
        assert inv["subtotal_cents"] == 5001208, (
            f"Expected full season-1 fee 5001208, got {inv['subtotal_cents']}")
        assert inv["status"] == "ISSUED"
        assert inv["due_on"].startswith("2026-08-31T00:00:00")


class TestSuspendCureCycle:
    def test_manual_account_suspend_cascades_administrative(self, api: ApiClient):
        """PRD §3.2: "both ways cascade identically down the hierarchy: every license
        agreement of the account sitting in `ACTIVE` or `EXPIRING` is pulled into
        `SUSPENDED`, recording a `suspension_reason` of `ADMINISTRATIVE` when a manual
        suspension triggered the cascade and `ACCOUNT_DEFAULT` when the settle sweep
        did."
        Design: Difficulty/non_linear_state_machine/agreement_suspend_cure_cycle_restores_active
        """
        s = setup_active_agreement(num_seasons=2, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=2))
        ac, ag = s["account"], s["agreement"]
        validate_success(api.set_account_status(ac["id"], {"target_status": "SUSPENDED"}, FIN))
        after = validate_success(api.get_agreement(ag["id"], REP))
        assert after["status"] == "SUSPENDED"
        assert after["suspension_reason"] == "ADMINISTRATIVE"
        assert after["suspension_count"] == 1

    def test_manual_reinstate_does_not_cure_administrative_explicit_cure_does(
            self, api: ApiClient):
        """PRD §3.2: "agreements suspended with reason `ACCOUNT_DEFAULT` auto-cure back
        to `ACTIVE`, while `ADMINISTRATIVE` suspensions deliberately do not and require
        the explicit agreement cure described in §3.3."
        PRD §3.3: "on success the `suspension_reason` clears to null."
        Design: Difficulty/non_linear_state_machine/agreement_suspend_cure_cycle_restores_active
        """
        s = setup_active_agreement(num_seasons=2, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=2))
        ac, ag = s["account"], s["agreement"]
        validate_success(api.set_account_status(ac["id"], {"target_status": "SUSPENDED"}, FIN))
        validate_success(api.set_account_status(ac["id"], {"target_status": "ACTIVE"}, FIN))
        still = validate_success(api.get_agreement(ag["id"], REP))
        assert still["status"] == "SUSPENDED", "manual reinstate must not cure ADMINISTRATIVE"
        cured = validate_success(api.cure_agreement(ag["id"], FIN))
        assert cured["status"] == "ACTIVE"
        assert cured["suspension_reason"] is None
        assert cured["suspension_count"] == 1, "exactly one suspension lap completed"


class TestRenewalNegotiationCycle:
    def _setup_offer(self, api: ApiClient):
        s = setup_active_agreement(num_seasons=3, agreement_over=dict(term_seasons=2))
        offer = setup_renewal_offer(s["agreement"]["id"], s["seasons"][2]["id"],
                                    at_clock="2027-12-10T00:00:00Z",
                                    proposed_fee_cents=13000000,
                                    proposed_escalator_bp=300, proposed_term_seasons=2,
                                    response_due_on="2028-01-10T00:00:00Z")
        return s, offer

    def test_counter_revise_cycle_increments_round_index(self, api: ApiClient):
        """PRD §3.10: "The holder counters — moving `OFFERED` or `REVISED` to
        `COUNTERED` with a `counter_fee_cents` naming the fee it would accept ... each
        counter increments `round_index` by one. The office revises — moving
        `COUNTERED` to `REVISED` with a `revised_fee_cents`, which replaces the offer's
        `proposed_fee_cents` — a step reserved to the rep and admin, likewise
        incrementing `round_index` by one."
        Design: Difficulty/non_linear_state_machine/renewal_offer_counter_revise_cycle_increments_rounds
        """
        s, offer = self._setup_offer(api)
        holder = make_account_holder_headers(s["account"]["id"])
        o = validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "COUNTERED", "counter_fee_cents": 12500000}, holder))
        assert o["round_index"] == 2
        o = validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "REVISED", "revised_fee_cents": 12750000}, REP))
        assert o["round_index"] == 3 and o["proposed_fee_cents"] == 12750000
        o = validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "COUNTERED", "counter_fee_cents": 12600000}, holder))
        assert o["round_index"] == 4
        o = validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "REVISED", "revised_fee_cents": 12650000}, REP))
        assert o["round_index"] == 5 and o["proposed_fee_cents"] == 12650000
        o = validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "ACCEPTED"}, holder))
        assert o["status"] == "ACCEPTED"
        assert o["round_index"] == 5, "initial 1 + 2 COUNTERED + 2 REVISED"

    def test_acceptance_creates_draft_renewal_from_final_terms(self, api: ApiClient):
        """PRD §3.10: "Acceptance immediately creates the renewal LicenseAgreement in
        `DRAFT` — same suite and account, `start_season_id` taken from the offer's
        `season_id`, term, escalator, and season-one fee taken from the offer, and the
        food-and-beverage minimum taken from the suite's current `f_b_minimum_cents` —
        and records it on the expiring agreement's `renewal_agreement_id`."
        Design: Difficulty/non_linear_state_machine/renewal_offer_counter_revise_cycle_increments_rounds
        """
        s, offer = self._setup_offer(api)
        holder = make_account_holder_headers(s["account"]["id"])
        validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "COUNTERED", "counter_fee_cents": 12500000}, holder))
        validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "REVISED", "revised_fee_cents": 12650000}, REP))
        validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "ACCEPTED"}, holder))
        rows = validate_paginated(api.list_agreements(
            REP, params={"suite_id": s["suite"]["id"], "status": "DRAFT"}))[0]
        assert len(rows) == 1, f"expected 1 DRAFT renewal, got {len(rows)}"
        renewal = rows[0]
        assert renewal["start_season_id"] == s["seasons"][2]["id"]
        assert renewal["base_annual_fee_cents"] == 12650000
        assert renewal["account_id"] == s["account"]["id"]
        original = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert original["renewal_agreement_id"] == renewal["id"]


class TestPriorityPairs:
    def _setup_draft_with_credit_hold(self, api: ApiClient, submit: bool):
        """Agreement (DRAFT or PENDING_EXECUTION) for an account on credit HOLD."""
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        account = make_active_account()
        make_issued_invoice(account["id"], lines=[{"description": "Deposit", "quantity": 1,
                                                   "unit_price_cents": 500000}],
                            due_on="2026-08-10T00:00:00Z")
        ag = make_draft_agreement(suite["id"], account["id"], season["id"])
        if submit:
            submit_agreement(ag["id"])
        set_clock("2026-09-15T00:00:00Z")  # invoice is 36 days past due -> HOLD
        return account, ag

    def test_execute_draft_with_credit_hold_returns_state_error(self, api: ApiClient):
        """PRD §2.8: "Incoming requests are validated against a fixed sequence of
        gates; an earlier failure masks all later checks." (from-state validity is gate
        7; credit gates are gate 23.)
        Design: Difficulty/priority_pair_validation_conflict/execute_draft_with_credit_hold_returns_state_error
        """
        account, ag = self._setup_draft_with_credit_hold(api, submit=False)
        resp = api.execute_agreement(ag["id"], make_account_holder_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_execute_pending_with_credit_hold_returns_fiscal_error(self, api: ApiClient):
        """PRD §3.3: "the account's `credit_standing` must not be `HOLD` (else
        `ERR_ACCOUNT_CREDIT_HOLD`)".
        Design: Difficulty/priority_pair_validation_conflict/execute_draft_with_credit_hold_returns_state_error
        """
        account, ag = self._setup_draft_with_credit_hold(api, submit=True)
        acct = validate_success(api.get_account(account["id"], FIN))
        assert acct["credit_standing"] == "HOLD"
        resp = api.execute_agreement(ag["id"], make_account_holder_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CREDIT_HOLD)


class TestAgreementCornerCases:
    def test_draft_agreement_has_no_schedule_until_execute(self, api: ApiClient):
        """PRD §3.3: "A successful execution stamps `executed_on` — null until the
        agreement reaches `ACTIVE` — with the logical clock, computes the agreement's
        `fee_schedule_cents`, issues the first invoice, and flips the suite to
        `LICENSED`."
        PRD §3.3: "A fresh agreement is `DRAFT`."
        Design: Corner/entities/agreement_draft_has_no_schedule_until_execute
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        account = make_active_account()
        ag = validate_success(api.create_agreement(
            {"suite_id": suite["id"], "account_id": account["id"],
             "start_season_id": season["id"], "term_seasons": 1,
             "base_annual_fee_cents": 12000000, "escalator_bp": 300,
             "f_b_minimum_cents": 4000000}, REP), expected_status=201)
        assert ag["status"] == "DRAFT"
        assert ag["executed_on"] is None
        assert ag.get("fee_schedule_cents") in (None, []), (
            "no fee schedule may materialize before execution")

    def test_agreement_double_execute_rejected(self, api: ApiClient):
        """PRD §2.8: "The target resource must be in a valid from-state for the
        requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409); terminal
        states are locked down."
        Design: Corner/state_machines/agreement_double_execute_rejected
        """
        s = setup_active_agreement(num_seasons=1)
        holder = make_account_holder_headers(s["account"]["id"])
        resp = api.execute_agreement(s["agreement"]["id"], holder)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        rows = list_invoice_rows({"agreement_id": s["agreement"]["id"],
                                  "invoice_type": "LICENSE_FEE"})
        assert len(rows) == 1, "exactly one LICENSE_FEE invoice may exist after one execution"

    def test_execute_on_licensed_suite_rejected(self, api: ApiClient):
        """PRD §3.3: "the suite must be `AVAILABLE`, with `OUT_OF_SERVICE` rejected as
        `ERR_SUITE_NOT_AVAILABLE` and `LICENSED` as `ERR_SUITE_ALREADY_LICENSED`".
        Design: Corner/validations/agreement_execute_on_licensed_suite_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        ac1 = make_active_account()
        make_executed_agreement(suite, ac1, season)
        ac2 = make_active_account()
        agb = make_draft_agreement(suite["id"], ac2["id"], season["id"],
                                   base_annual_fee_cents=13000000)
        submit_agreement(agb["id"])
        resp = api.execute_agreement(agb["id"], make_account_holder_headers(ac2["id"]))
        validate_error(resp, ApiErrorId.ERR_SUITE_ALREADY_LICENSED)
        agb_after = validate_success(api.get_agreement(agb["id"], REP))
        assert agb_after["status"] == "PENDING_EXECUTION"
        suite_after = validate_success(api.get_suite(suite["id"], REP))
        assert suite_after["status"] == "LICENSED"

    def test_suite_out_of_service_while_licensed_rejected(self, api: ApiClient):
        """PRD §3.1: "taking it out of service while `LICENSED` is forbidden and is
        rejected with `ERR_SUITE_LICENSED` — the agreement must end first."
        Design: Corner/validations/suite_out_of_service_while_licensed_rejected
        """
        s = setup_active_agreement(num_seasons=1)
        resp = api.set_suite_status(s["suite"]["id"], {"target_status": "OUT_OF_SERVICE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SUITE_LICENSED)
        suite = validate_success(api.get_suite(s["suite"]["id"], ADMIN))
        assert suite["status"] == "LICENSED"

    def test_agreement_terminate_blocked_by_open_invoice(self, api: ApiClient):
        """PRD §3.3: "From `ACTIVE` or `SUSPENDED` it lands in `TERMINATED`, but only
        when no invoice of the agreement remains in `ISSUED` or `PARTIALLY_PAID` (else
        `ERR_UNSETTLED_BALANCE`)".
        Design: Corner/validations/agreement_terminate_blocked_by_open_invoice
        """
        s = setup_active_agreement(num_seasons=2, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=2))
        resp = api.terminate_agreement(s["agreement"]["id"], REP)
        validate_error(resp, ApiErrorId.ERR_UNSETTLED_BALANCE)

    def test_termination_fee_and_suite_release_after_invoice_paid(self, api: ApiClient):
        """PRD §3.3: "The early termination fee is the greater of two figures: twice
        the fee scheduled for the agreement's `current_season_index`, or half of the
        sum of all scheduled fees for seasons beyond the current one, that half rounded
        half-up." PRD §3.3: "termination then creates a `TERMINATION_FEE` invoice,
        issued immediately with `due_on` thirty days out, and releases the suite to
        `AVAILABLE` with `current_agreement_id` cleared."
        Design: Corner/validations/agreement_terminate_blocked_by_open_invoice
        """
        s = setup_active_agreement(num_seasons=2, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=2))
        lic = get_license_fee_invoice(s["agreement"]["id"])
        pay_invoice_in_full(s["account"]["id"], lic)
        # Pre-season execution: current_season_index 1; fee = max(2*12000000, 6180000).
        terminated = validate_success(api.terminate_agreement(s["agreement"]["id"], REP))
        assert terminated["status"] == "TERMINATED"
        fee = get_single_invoice({"agreement_id": s["agreement"]["id"],
                                  "invoice_type": "TERMINATION_FEE"})
        assert fee["subtotal_cents"] == 24000000
        assert fee["status"] == "ISSUED"
        suite = validate_success(api.get_suite(s["suite"]["id"], REP))
        assert suite["status"] == "AVAILABLE"
        assert suite["current_agreement_id"] is None

    def test_admin_override_terminates_draft_agreement_without_fee(self, api: ApiClient):
        """PRD §3.3: "From `DRAFT` or `PENDING_EXECUTION`, the agreement simply lands
        in `WITHDRAWN` with no fee."
        Design: Corner/rbac/admin_override_terminates_agreement
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        account = make_active_account()
        ag = make_draft_agreement(suite["id"], account["id"], season["id"])
        withdrawn = validate_success(api.terminate_agreement(ag["id"], ADMIN))
        assert withdrawn["status"] == "WITHDRAWN"
        rows = list_invoice_rows({"agreement_id": ag["id"], "invoice_type": "TERMINATION_FEE"})
        assert rows == [], "no termination fee may be charged before activation"


class TestRenewalOfferOccAndWindow:
    def _setup_renewable(self, api: ApiClient):
        """ACTIVE term-1 agreement; S2 published; clock inside S1's renewal window."""
        s = setup_active_agreement(num_seasons=2, agreement_over=dict(term_seasons=1))
        set_clock("2026-12-10T00:00:00Z")
        return s

    def test_stale_agreement_version_rejected_and_supersede(self, api: ApiClient):
        """PRD §2.7: "Because a successful create supersedes the agreement's
        outstanding offer and increments the agreement's `version` by one, a create
        carrying a pre-supersede version is working from a stale view of the agreement
        and is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        Design: Corner/cross_cutting_layers/occ_renewal_offer_stale_version_and_supersede
        """
        s = self._setup_renewable(api)
        ag_id, s2_id = s["agreement"]["id"], s["seasons"][1]["id"]
        v1 = validate_success(api.get_agreement(ag_id, REP))["version"]
        ro1 = validate_success(api.create_renewal_offer(
            {"agreement_id": ag_id, "season_id": s2_id, "proposed_fee_cents": 12400000,
             "proposed_escalator_bp": 300, "proposed_term_seasons": 1,
             "response_due_on": "2027-01-10T00:00:00Z",
             "expected_agreement_version": v1}, REP), expected_status=201)
        v2 = validate_success(api.get_agreement(ag_id, REP))["version"]
        assert v2 == v1 + 1, "offer creation increments the agreement version by one"
        stale = api.create_renewal_offer(
            {"agreement_id": ag_id, "season_id": s2_id, "proposed_fee_cents": 12300000,
             "proposed_escalator_bp": 300, "proposed_term_seasons": 1,
             "response_due_on": "2027-01-10T00:00:00Z",
             "expected_agreement_version": v1}, REP)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        ro2 = validate_success(api.create_renewal_offer(
            {"agreement_id": ag_id, "season_id": s2_id, "proposed_fee_cents": 12300000,
             "proposed_escalator_bp": 300, "proposed_term_seasons": 1,
             "response_due_on": "2027-01-10T00:00:00Z",
             "expected_agreement_version": v2}, REP), expected_status=201)
        ro1_after = validate_success(api.get_renewal_offer(ro1["id"], REP))
        assert ro1_after["status"] == "SUPERSEDED"
        assert ro2["status"] == "OFFERED"

    def test_renewal_window_close_is_inclusive(self, api: ApiClient):
        """PRD §3.10: "The clock must also fall within the renewal window of the
        agreement's last covered season — from `renewal_window_opens_on` through
        `renewal_window_closes_on`, both ends inclusive — or creation fails with
        `ERR_RENEWAL_WINDOW_CLOSED`."
        Design: Corner/validations/renewal_offer_window_inclusive_boundary
        """
        s = setup_active_agreement(num_seasons=2, agreement_over=dict(term_seasons=1))
        ag_id, s2_id = s["agreement"]["id"], s["seasons"][1]["id"]
        set_clock("2027-01-15T00:00:00Z")  # exactly renewal_window_closes_on
        v = validate_success(api.get_agreement(ag_id, REP))["version"]
        offer = validate_success(api.create_renewal_offer(
            {"agreement_id": ag_id, "season_id": s2_id, "proposed_fee_cents": 12400000,
             "proposed_escalator_bp": 300, "proposed_term_seasons": 1,
             "response_due_on": "2027-02-01T00:00:00Z",
             "expected_agreement_version": v}, REP), expected_status=201)
        assert offer["status"] == "OFFERED"
        set_clock("2027-01-15T00:00:01Z")  # one second past the close
        v2 = validate_success(api.get_agreement(ag_id, REP))["version"]
        resp = api.create_renewal_offer(
            {"agreement_id": ag_id, "season_id": s2_id, "proposed_fee_cents": 12300000,
             "proposed_escalator_bp": 300, "proposed_term_seasons": 1,
             "response_due_on": "2027-02-01T00:00:00Z",
             "expected_agreement_version": v2}, REP)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)


class TestWaitlist:
    def test_duplicate_waitlist_entry_rejected_until_withdrawn(self, api: ApiClient):
        """PRD §3.10: "an account may hold only one non-terminal entry for the same
        tier and target season: a second entry while one is `WAITING` or `OFFERED` for
        the same combination is `ERR_WAITLIST_DUPLICATE`."
        Design: Corner/validations/waitlist_duplicate_entry_rejected
        """
        venue = make_venue()
        season = make_season(venue["id"])
        account = make_active_account()
        entry = make_waitlist_entry(account["id"], desired_tier="GOLD",
                                    target_season_id=season["id"])
        dup = api.create_waitlist_entry(
            {"account_id": account["id"], "desired_tier": "GOLD",
             "target_season_id": season["id"]}, REP)
        validate_error(dup, ApiErrorId.ERR_WAITLIST_DUPLICATE)
        validate_success(api.set_waitlist_entry_status(
            entry["id"], {"target_status": "WITHDRAWN"},
            make_account_holder_headers(account["id"])))
        rejoined = api.create_waitlist_entry(
            {"account_id": account["id"], "desired_tier": "GOLD",
             "target_season_id": season["id"]}, REP)
        validate_success(rejoined, expected_status=201)

    def test_waitlist_score_ranking_and_offer_pending(self, api: ApiClient):
        """PRD §3.10: "waiting time contributes half a point for every whole thirty-day
        period since the entry's `created_at`, capped at ten periods ... a `CORPORATE`
        account adds a flat 2.0-point bonus"; "Ranking is by `priority_score`
        descending, with ties broken first by the entry's earlier `created_at`";
        "no other entry may already be `OFFERED` against that same suite (else
        `ERR_SUITE_OFFER_PENDING`)"; "the promoted entry must be the top-ranked
        eligible `WAITING` entry, else `ERR_NOT_NEXT_IN_LINE`".
        Design: Corner/calculations/waitlist_score_ranking_and_tiebreak
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], suite_code="G-202", tier="GOLD", capacity_seats=20)
        make_season(venue["id"])
        ac_a = make_active_account(legal_name="Alpha Corp", account_type="CORPORATE")
        ac_b = make_active_account(legal_name="Bob Ind", account_type="INDIVIDUAL")
        wa = make_waitlist_entry(ac_a["id"], desired_tier="GOLD")
        wb = make_waitlist_entry(ac_b["id"], desired_tier="GOLD")
        ac_c = make_active_account(legal_name="Cara Corp", account_type="CORPORATE")
        set_clock("2026-11-21T00:00:00Z")
        wc = make_waitlist_entry(ac_c["id"], desired_tier="GOLD")
        set_clock("2026-12-01T00:00:00Z")
        sa = validate_success(api.get_waitlist_entry(wa["id"], REP))["priority_score"]
        sb = validate_success(api.get_waitlist_entry(wb["id"], REP))["priority_score"]
        sc = validate_success(api.get_waitlist_entry(wc["id"], REP))["priority_score"]
        assert sa == pytest.approx(4.0), f"A: 4 periods * 0.5 + 2.0 corporate = 4.0, got {sa}"
        assert sb == pytest.approx(2.0)
        assert sc == pytest.approx(2.0)
        # B ties C on score but wins on earlier created_at; both lose to A.
        not_top = api.set_waitlist_entry_status(
            wb["id"], {"target_status": "OFFERED", "suite_id": suite["id"]}, REP)
        validate_error(not_top, ApiErrorId.ERR_NOT_NEXT_IN_LINE)
        offered = validate_success(api.set_waitlist_entry_status(
            wa["id"], {"target_status": "OFFERED", "suite_id": suite["id"]}, REP))
        assert offered["status"] == "OFFERED"
        assert offered["offered_suite_id"] == suite["id"]
        blocked = api.set_waitlist_entry_status(
            wc["id"], {"target_status": "OFFERED", "suite_id": suite["id"]}, REP)
        validate_error(blocked, ApiErrorId.ERR_SUITE_OFFER_PENDING)

    def test_waitlist_convert_creates_draft_agreement(self, api: ApiClient):
        """PRD §3.10: "moving `OFFERED` to `CONVERTED` — a rep or admin step — requires
        the offered suite still `AVAILABLE` (else `ERR_SUITE_NOT_AVAILABLE`) and creates
        a LicenseAgreement in `DRAFT` for the offered suite and the entry's account,
        with `start_season_id` taken from the entry's `target_season_id` when set ...,
        the base fee and food-and-beverage minimum taken from the suite's defaults, an
        escalator of zero, and a term of one season."
        Design: Corner/state_machines/waitlist_convert_creates_draft_agreement
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        account = make_active_account()
        entry = make_waitlist_entry(account["id"], desired_tier="GOLD",
                                    target_season_id=season["id"])
        validate_success(api.set_waitlist_entry_status(
            entry["id"], {"target_status": "OFFERED", "suite_id": suite["id"]}, REP))
        converted = validate_success(api.set_waitlist_entry_status(
            entry["id"], {"target_status": "CONVERTED"}, REP))
        assert converted["status"] == "CONVERTED"
        rows = validate_paginated(api.list_agreements(
            REP, params={"suite_id": suite["id"], "status": "DRAFT"}))[0]
        assert len(rows) == 1
        ag = rows[0]
        assert ag["account_id"] == account["id"]
        assert ag["start_season_id"] == season["id"]
        assert ag["base_annual_fee_cents"] == 12000000
        assert ag["f_b_minimum_cents"] == 4000000
        assert ag["escalator_bp"] == 0
        assert ag["term_seasons"] == 1
        suite_after = validate_success(api.get_suite(suite["id"], REP))
        assert suite_after["status"] == "AVAILABLE", (
            "a suite becomes LICENSED only when the new agreement is executed")
