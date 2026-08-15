"""Season close cascades, sponsor block cascade, valuation reports, renewal
pipeline."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    activate_grant,
    advance_season,
    countersign_contract,
    create_active_contract,
    create_active_sponsor,
    create_asset,
    create_draft_contract,
    create_grant,
    create_open_deliverable,
    create_opportunity,
    create_report,
    create_venue,
    get_success_data,
    list_contract_invoices,
    make_sponsor_contact_headers,
    propose_contract,
    setup_active_contract_scenario,
    submit_and_approve,
    submit_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AM_SUBMITTER,
    FINANCE,
    SALES,
    am_headers,
)
from test_helpers.factories import (
    create_credit_payload,
    create_opportunity_payload,
)


class TestDeliveredValueDualVariant:
    """Difficulty rule dual_variant_calc, deliverable-valuation domain."""

    def _setup_report_scenario(self, api):
        """Two deliverables: D1 7/10 approved on LED (rate 50,000, imp 120,000,
        cpm 2,500); D2 9/10 approved on digital (rate 80,000, imp 200,000, cpm
        3,000); season 2026 closed by advancing the venue."""
        venue = create_venue()
        sponsor = create_active_sponsor()
        a1 = create_asset(venue["id"], name="Bowl LED Ribbon",
                          asset_class="SIGNAGE", rate_card_unit_cents=50_000,
                          avg_impressions_per_unit=120_000, cpm_cents=2_500)
        a2 = create_asset(venue["id"], name="App Banner Block",
                          asset_class="DIGITAL", rate_card_unit_cents=80_000,
                          avg_impressions_per_unit=200_000, cpm_cents=3_000)
        contract = create_active_contract(
            venue["id"], sponsor["id"], term_first_season=2026,
            term_last_season=2026, base_fee_cents=10_000_000,
            escalator_pct=0.03, escalator_mode="SIMPLE")
        d1 = create_open_deliverable(contract["id"], a1["id"], season=2026,
                                     contracted_units=10)
        d2 = create_open_deliverable(contract["id"], a2["id"], season=2026,
                                     unit_kind="IMPRESSION_BLOCK",
                                     contracted_units=10)
        submit_and_approve(d1["id"], 7)
        submit_and_approve(d2["id"], 9)
        advance_season(venue["id"])
        return venue, sponsor, contract

    def test_provisional_vs_final_media_value_amounts(self, api):
        """PRD §3.8: "`delivered_value_provisional_cents` sums, per
        deliverable, `approved_units` multiplied by the asset's
        `rate_card_unit_cents` — what the venue quoted.
        `delivered_value_final_cents` sums, per deliverable, `approved_units`
        multiplied by the asset's `avg_impressions_per_unit` multiplied by the
        asset's `cpm_cents` and divided by one thousand, each deliverable line
        rounded half-up to whole cents before the lines are summed — what the
        exposure was actually worth"

        Design: Difficulty/dual_variant_calc/delivered_value_provisional_vs_final_media_value
        """
        _v, _s, contract = self._setup_report_scenario(api)
        report = create_report(contract["id"], 2026)
        # provisional: 7*50,000 + 9*80,000 = 350,000 + 720,000
        assert report["delivered_value_provisional_cents"] == 1_070_000
        # final: round(7*120,000*2,500/1000) + round(9*200,000*3,000/1000)
        #      = 2,100,000 + 5,400,000
        assert report["delivered_value_final_cents"] == 7_500_000
        assert (report["delivered_value_provisional_cents"]
                != report["delivered_value_final_cents"])

    def test_provisional_vs_final_fulfillment_pct(self, api):
        """PRD §3.8: "`fulfillment_pct` divides the total approved units by the
        total contracted units across the same deliverable set, rounded half-up
        to four decimal places."

        Design: Difficulty/dual_variant_calc/delivered_value_provisional_vs_final_media_value
        """
        _v, _s, contract = self._setup_report_scenario(api)
        report = create_report(contract["id"], 2026)
        # (7 + 9) / (10 + 10) = 0.8
        assert report["fulfillment_pct"] == pytest.approx(0.8, abs=1e-9)


class TestMakeGoodTierMultiplierWithCap:
    """Difficulty rule combinatorial_formula, tiered-threshold mode."""

    def _setup_three_missed(self, api):
        """D1 7/10 (1.25 tier), D2 9/10 (0.90 boundary -> 1.00 tier) on a big
        contract; D3 0/10 on a small contract whose season fee caps the raw
        credit."""
        venue = create_venue()
        sponsor = create_active_sponsor()
        asset = create_asset(venue["id"], rate_card_unit_cents=50_000)

        c1 = create_active_contract(venue["id"], sponsor["id"], title="Big",
                                    term_first_season=2026,
                                    term_last_season=2026,
                                    base_fee_cents=10_000_000)
        d1 = create_open_deliverable(c1["id"], asset["id"], season=2026,
                                     contracted_units=10)
        d2 = create_open_deliverable(c1["id"], asset["id"], season=2026,
                                     contracted_units=10)
        submit_and_approve(d1["id"], 7)
        submit_and_approve(d2["id"], 9)

        c2 = create_active_contract(venue["id"], sponsor["id"], title="Small",
                                    term_first_season=2026,
                                    term_last_season=2026,
                                    base_fee_cents=600_000)
        d3 = create_open_deliverable(c2["id"], asset["id"], season=2026,
                                     contracted_units=10)

        advance_season(venue["id"])
        return venue, sponsor, asset, c1, d1, d2, c2, d3

    def _credit_for(self, api, deliverable_id):
        credits, _meta = validate_paginated(api.list_credits(
            FINANCE, params={"deliverable_id": deliverable_id}))
        assert len(credits) == 1
        return credits[0]

    def test_tier_boundaries_select_multiplier(self, api):
        """PRD §3.5: "The multiplier is 1.00 when the fraction is at least
        0.90, 1.25 when the fraction is at least 0.70 but below 0.90, and 1.50
        when the fraction is below 0.70 — the tier boundaries are inclusive on
        the lower side, so a fraction of exactly 0.90 earns the 1.00 multiplier
        and a fraction of exactly 0.70 earns 1.25."
        PRD §3.5: "The raw credit is the missed value multiplied by the
        multiplier, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/make_good_tier_multiplier_with_season_cap
        """
        _v, _s, _a, _c1, d1, d2, _c2, _d3 = self._setup_three_missed(api)
        mg1 = self._credit_for(api, d1["id"])
        mg2 = self._credit_for(api, d2["id"])
        # pct 0.70 -> 1.25: (10-7) * 50,000 * 1.25 = 187,500
        assert mg1["requested_amount_cents"] == 187_500
        # pct 0.90 exactly -> 1.00 (inclusive lower boundary): 1 * 50,000
        assert mg2["requested_amount_cents"] == 50_000
        assert mg1["credit_status"] == "REQUESTED"
        assert mg2["credit_status"] == "REQUESTED"

    def test_season_fee_cap_engages_via_min(self, api):
        """PRD §3.5: "The cap is the season fee of the deliverable's `season`
        under the owning contract's escalator terms, computed exactly as in
        §3.3. The make-good amount is the lesser of the raw credit and the
        cap."

        Design: Difficulty/combinatorial_formula/make_good_tier_multiplier_with_season_cap
        """
        _v, _s, _a, _c1, _d1, _d2, _c2, d3 = self._setup_three_missed(api)
        mg3 = self._credit_for(api, d3["id"])
        # pct 0 -> 1.50 tier raw 10*50,000*1.50 = 750,000; cap = season fee
        # 600,000 -> min() = 600,000
        assert mg3["requested_amount_cents"] == 600_000
        assert mg3["credit_status"] == "REQUESTED"


class TestSponsorBlockThreeHopCascade:
    """Difficulty rule transitive_cascade, sponsor BLOCK trigger (depth 3)."""

    def _setup_book_of_business(self, api):
        venue = create_venue()
        sponsor = create_active_sponsor()
        asset = create_asset(venue["id"])
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        grant = create_grant(contract["id"], first_season=2026,
                             last_season=2028)
        proposed = propose_contract(contract["id"])
        countersign_contract(contract["id"], sponsor["id"], proposed["version"])
        # Activate grant before contract activation (PENDING grants block it)
        activate_grant(grant["id"])
        activate_contract(contract["id"])
        deliverable = create_open_deliverable(contract["id"], asset["id"],
                                              season=2026, contracted_units=10)
        evidence = submit_evidence(deliverable["id"], 4,
                                   evidence_uri="s3://pop/e.pdf")
        credit = get_success_data(api.create_credit(
            create_credit_payload(contract["id"], deliverable["id"],
                                  requested_amount_cents=50_000),
            am_headers(AM_SUBMITTER)))
        invoice = list_contract_invoices(contract["id"])[0]
        return venue, sponsor, asset, contract, grant, deliverable, evidence, \
            credit, invoice

    def test_block_terminates_contract_and_cancels_deliverable(self, api):
        """PRD §3.1: "Hop one terminates every contract of the sponsor in
        `COUNTERSIGNED`, `ACTIVE`, or `SUSPENDED`. Hop two, caused by those
        terminations, cancels every deliverable of a terminated contract in
        `SCHEDULED` or `IN_PROGRESS`, releases every exclusivity grant of a
        terminated contract in `PENDING`, `ACTIVE`, or `CONFLICTED`, voids
        every draft invoice of a terminated contract, and voids every make-good
        credit of a terminated contract in `REQUESTED` or `APPROVED`. Hop
        three, caused by the deliverable cancellations, voids every evidence
        submission of a cancelled deliverable in `SUBMITTED` or `REJECTED`."

        Design: Difficulty/transitive_cascade/sponsor_block_three_hop_termination
        """
        (_v, sponsor, _a, contract, grant, deliverable, evidence, credit,
         invoice) = self._setup_book_of_business(api)
        get_success_data(api.transition_sponsor(sponsor["id"],
                                                {"action": "BLOCK"}, SALES))

        got_c = validate_success(api.get_contract(contract["id"], SALES))
        assert got_c["contract_status"] == "TERMINATED"
        got_d = validate_success(api.get_deliverable(deliverable["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert got_d["deliverable_status"] == "CANCELLED"
        got_g = validate_success(api.get_grant(grant["id"], ADMIN))
        assert got_g["grant_status"] == "RELEASED"

    def test_block_voids_open_evidence_credit_and_draft_invoice(self, api):
        """PRD §3.1: "Hop two, caused by those terminations, cancels every
        deliverable of a terminated contract in `SCHEDULED` or `IN_PROGRESS`,
        releases every exclusivity grant of a terminated contract in `PENDING`,
        `ACTIVE`, or `CONFLICTED`, voids every draft invoice of a terminated
        contract, and voids every make-good credit of a terminated contract in
        `REQUESTED` or `APPROVED`. Hop three, caused by the deliverable
        cancellations, voids every evidence submission of a cancelled
        deliverable in `SUBMITTED` or `REJECTED`."

        Design: Difficulty/transitive_cascade/sponsor_block_three_hop_termination
        """
        (_v, sponsor, _a, contract, _g, deliverable, evidence, credit,
         invoice) = self._setup_book_of_business(api)
        get_success_data(api.transition_sponsor(sponsor["id"],
                                                {"action": "BLOCK"}, SALES))

        got_e = validate_success(api.get_evidence(evidence["id"],
                                                  am_headers(AM_SUBMITTER)))
        assert got_e["submission_status"] == "VOIDED"
        got_mg = validate_success(api.get_credit(credit["id"], FINANCE))
        assert got_mg["credit_status"] == "VOIDED"
        got_inv = validate_success(api.get_invoice(invoice["id"], FINANCE))
        assert got_inv["invoice_status"] == "VOID"


class TestAdvanceSeasonAutoCredit:
    """Difficulty rule transitive_cascade, advance-season trigger (depth 2)."""

    def _setup_partial_delivery(self, api):
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE",
                                           term_first_season=2026,
                                           term_last_season=2028)
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        submit_and_approve(d["id"], 7)
        df = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                     season=2027, contracted_units=5)
        return s, d, df

    def test_missed_flip_auto_creates_credit_with_formula_amount(self, api):
        """PRD §3.5: "Every deliverable whose `season` is now earlier than the
        new epoch and whose `approved_units` still fall short of
        `contracted_units` flips to `MISSED`, whether it was `SCHEDULED` or
        `IN_PROGRESS`, and missing an element auto-creates a make-good credit
        in `REQUESTED` status with its `contract_id` and `deliverable_id` set
        and its `requested_amount_cents` equal to the make-good formula below."

        Design: Difficulty/transitive_cascade/advance_season_missed_deliverable_auto_credit
        """
        s, d, _df = self._setup_partial_delivery(api)
        venue = advance_season(s["venue"]["id"])
        assert venue["current_season"] == 2027

        got_d = validate_success(api.get_deliverable(d["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert got_d["deliverable_status"] == "MISSED"

        credits, _meta = validate_paginated(api.list_credits(
            FINANCE, params={"deliverable_id": d["id"]}))
        assert len(credits) == 1
        assert credits[0]["credit_status"] == "REQUESTED"
        # pct 0.70 -> 1.25 tier: 3 * 50,000 * 1.25 = 187,500
        assert credits[0]["requested_amount_cents"] == 187_500

    def test_new_season_deliverable_enters_in_progress(self, api):
        """PRD §3.5: "Every `SCHEDULED` deliverable whose `season` equals the
        new epoch flips to `IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/advance_season_missed_deliverable_auto_credit
        """
        s, _d, df = self._setup_partial_delivery(api)
        before = validate_success(api.get_deliverable(df["id"],
                                                      am_headers(AM_SUBMITTER)))
        assert before["deliverable_status"] == "SCHEDULED"

        advance_season(s["venue"]["id"])
        after = validate_success(api.get_deliverable(df["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert after["deliverable_status"] == "IN_PROGRESS"


class TestReportInputSetFiltering:
    def test_report_excludes_cancelled_deliverables(self, api):
        """PRD §3.8: "Generation snapshots four measures over the contract's
        deliverables for that season, excluding `CANCELLED` ones."
        PRD §3.8: "`make_good_due_cents` sums `approved_amount_cents` over the
        credits tied to those deliverables whose `credit_status` is `APPROVED`
        or `REDEEMED`."

        Design: Corner/calculations/report_excludes_cancelled_deliverables
        """
        s = setup_active_contract_scenario(base_fee_cents=10_000_000,
                                           escalator_pct=0,
                                           escalator_mode="SIMPLE")
        d1 = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                     season=2026, contracted_units=10)
        d2 = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                     season=2026, contracted_units=4)
        submit_and_approve(d1["id"], 7)
        get_success_data(api.transition_deliverable(
            d2["id"], {"action": "CANCEL"}, am_headers(AM_SUBMITTER)))
        advance_season(s["venue"]["id"])

        report = create_report(s["contract"]["id"], 2026)
        # D1 alone: 7 * 50,000
        assert report["delivered_value_provisional_cents"] == 350_000
        # round(7 * 120,000 * 2,500 / 1000) = 2,100,000
        assert report["delivered_value_final_cents"] == 2_100_000
        # 7 / 10 — CANCELLED D2's 4 contracted units excluded
        assert report["fulfillment_pct"] == pytest.approx(0.7, abs=1e-9)
        # D1's auto-credit is REQUESTED, not APPROVED/REDEEMED
        assert report["make_good_due_cents"] == 0

    def test_report_season_not_closed_rejected(self, api):
        """PRD §3.8: "the season must already be closed — strictly earlier than
        the venue's `current_season`, otherwise `ERR_SEASON_NOT_CLOSED`"

        Design: Corner/validations/report_season_not_closed_rejected
        """
        s = setup_active_contract_scenario(term_last_season=2028,
                                           with_asset=False)
        resp = api.create_report(
            {"contract_id": s["contract"]["id"], "season": 2026},
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_CLOSED,
                       expected_status=422)


class TestReportHandoff:
    def test_report_issue_then_sponsor_acknowledge(self, api):
        """PRD §3.8: "The report's `report_status` starts `DRAFT`; issuance
        (`ISSUE`) by an `ActivationManager` moves it to `ISSUED`, and
        acknowledgement (`ACKNOWLEDGE`) by the sponsor contact whose
        `X-User-ID` equals the report contract's `sponsor_id` (`ERR_FORBIDDEN`
        otherwise) moves it to the terminal `ACKNOWLEDGED`."

        Design: Corner/endpoints/report_issue_then_sponsor_acknowledge
        """
        s = setup_active_contract_scenario(with_asset=False)
        advance_season(s["venue"]["id"])
        report = create_report(s["contract"]["id"], 2026)

        issued = validate_success(api.transition_report(
            report["id"], {"action": "ISSUE"}, am_headers(AM_SUBMITTER)))
        assert issued["report_status"] == "ISSUED"

        acked = validate_success(api.transition_report(
            report["id"], {"action": "ACKNOWLEDGE"},
            make_sponsor_contact_headers(s["sponsor"]["id"])))
        assert acked["report_status"] == "ACKNOWLEDGED"

        resp = api.transition_report(
            report["id"], {"action": "ACKNOWLEDGE"},
            make_sponsor_contact_headers(s["sponsor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestRenewalPipeline:
    def test_renewal_requires_active_or_expired_contract(self, api):
        """PRD §3.8: "the source contract must be `ACTIVE` or `EXPIRED`
        (`ERR_RENEWAL_CONTRACT_STATE`)"

        Design: Corner/validations/renewal_requires_active_or_expired_contract
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028,
                                         escalator_pct=0.03,
                                         escalator_mode="COMPOUND")
        resp = api.create_opportunity(
            create_opportunity_payload(contract["id"],
                                       proposed_fee_cents=12_000_000), SALES)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_CONTRACT_STATE,
                       expected_status=409)

    def test_duplicate_open_opportunity_rejected(self, api):
        """PRD §3.8: "A contract may have at most one open opportunity — open
        means a `stage` of `IDENTIFIED`, `PROPOSED`, or `NEGOTIATING` — and a
        duplicate is rejected with `ERR_DUPLICATE_OPEN_OPPORTUNITY`"

        Design: Corner/validations/duplicate_open_opportunity_rejected
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          term_last_season=2028,
                                          escalator_pct=0.03,
                                          escalator_mode="COMPOUND")
        create_opportunity(contract["id"], proposed_fee_cents=12_000_000)
        resp = api.create_opportunity(
            create_opportunity_payload(contract["id"],
                                       proposed_fee_cents=13_000_000), SALES)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_OPPORTUNITY,
                       expected_status=409)

    def test_renewal_mark_won_creates_renewal_contract(self, api):
        """PRD §3.8: "Marking won (`MARK_WON`) from `PROPOSED` or `NEGOTIATING`
        creates the renewal contract in `DRAFT`: `venue_id`, `sponsor_id`,
        `escalator_pct`, and `escalator_mode` are copied from the source
        contract; the new `term_first_season` is the source's
        `term_last_season` plus one; the new `term_last_season` extends that by
        the source term's length, preserving the original duration; the new
        `base_fee_cents` is the opportunity's `proposed_fee_cents`; and the new
        contract's `renewed_from_contract_id` points back at the source, while
        the opportunity records the new contract in `resulting_contract_id`."

        Design: Corner/endpoints/renewal_mark_won_creates_renewal_contract
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          term_first_season=2026,
                                          term_last_season=2028,
                                          base_fee_cents=10_000_000,
                                          escalator_pct=0.03,
                                          escalator_mode="COMPOUND")
        opp = create_opportunity(contract["id"], proposed_fee_cents=12_000_000)
        get_success_data(api.transition_opportunity(opp["id"],
                                                    {"action": "PROPOSE"}, SALES))
        negotiating = get_success_data(api.transition_opportunity(
            opp["id"], {"action": "OPEN_NEGOTIATION"}, SALES))
        get_success_data(api.counter_opportunity(
            opp["id"], {"proposed_fee_cents": 11_500_000,
                        "expected_opportunity_version": negotiating["version"]},
            SALES))

        won = validate_success(api.transition_opportunity(
            opp["id"], {"action": "MARK_WON"}, SALES))
        assert won["stage"] == "WON"
        rc_id = won["resulting_contract_id"]
        assert rc_id

        rc = validate_success(api.get_contract(rc_id, SALES))
        assert rc["term_first_season"] == 2029
        assert rc["term_last_season"] == 2031  # source length 3 seasons
        assert rc["base_fee_cents"] == 11_500_000
        assert rc["escalator_mode"] == "COMPOUND"
        assert rc["escalator_pct"] == pytest.approx(0.03)
        assert rc["contract_status"] == "DRAFT"
        assert rc["renewed_from_contract_id"] == contract["id"]

        linked, _meta = validate_paginated(api.list_contracts(
            SALES, params={"renewed_from_contract_id": contract["id"]}))
        assert len(linked) == 1
        assert linked[0]["id"] == rc_id

    def test_opportunity_terminal_stages_reject_further_actions(self, api):
        """PRD §3.8: "Marking lost (`MARK_LOST`) is available from
        `IDENTIFIED`, `PROPOSED`, or `NEGOTIATING`; both `WON` and `LOST` are
        terminal."
        PRD §2.12: "**State-machine legality** — the target entity's own
        lifecycle permits the requested action from its current state,
        including terminal-state lockdown and compound state preconditions
        expressed as `ERR_INVALID_STATE`."

        Design: Corner/endpoints/opportunity_terminal_stages_reject_further_actions
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          term_last_season=2028,
                                          escalator_pct=0.03,
                                          escalator_mode="COMPOUND")
        opp = create_opportunity(contract["id"], proposed_fee_cents=12_000_000)
        get_success_data(api.transition_opportunity(opp["id"],
                                                    {"action": "MARK_LOST"},
                                                    SALES))
        resp = api.transition_opportunity(opp["id"], {"action": "MARK_WON"},
                                          SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        got = validate_success(api.get_opportunity(opp["id"], SALES))
        assert got["resulting_contract_id"] is None

    def test_opportunity_counter_stale_version_returns_412(self, api):
        """PRD §2.11: "A request to counter a renewal opportunity (`POST
        /renewal-opportunities/{opportunity_id}/counter`) must carry
        `expected_opportunity_version`, holding the opportunity `version` the
        seller last observed. A mismatch with the opportunity's current
        `version` is rejected with `ERR_STALE_OPPORTUNITY_VERSION` (HTTP 412),
        since the new counter would otherwise be priced against terms that have
        already moved."

        Design: Corner/validations/opportunity_counter_stale_version_returns_412
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          term_last_season=2028,
                                          escalator_pct=0.03,
                                          escalator_mode="COMPOUND")
        opp = create_opportunity(contract["id"], proposed_fee_cents=12_000_000)
        get_success_data(api.transition_opportunity(opp["id"],
                                                    {"action": "PROPOSE"}, SALES))
        negotiating = get_success_data(api.transition_opportunity(
            opp["id"], {"action": "OPEN_NEGOTIATION"}, SALES))
        stale_version = negotiating["version"]
        # First counter succeeds and bumps the version.
        get_success_data(api.counter_opportunity(
            opp["id"], {"proposed_fee_cents": 11_500_000,
                        "expected_opportunity_version": stale_version}, SALES))
        get_success_data(api.transition_opportunity(
            opp["id"], {"action": "OPEN_NEGOTIATION"}, SALES))

        resp = api.counter_opportunity(
            opp["id"], {"proposed_fee_cents": 11_600_000,
                        "expected_opportunity_version": stale_version}, SALES)
        validate_error(resp, ApiErrorId.ERR_STALE_OPPORTUNITY_VERSION,
                       expected_status=412)
        got = validate_success(api.get_opportunity(opp["id"], SALES))
        assert got["proposed_fee_cents"] == 11_500_000


class TestSponsorGateOnContractCreate:
    def test_sponsor_not_active_blocks_contract_create(self, api):
        """PRD §3.3: "then requires the sponsor to be `ACTIVE`
        (`ERR_SPONSOR_NOT_ACTIVE`)"

        Design: Corner/validations/sponsor_not_active_blocks_contract_create
        """
        venue = create_venue()
        # Sponsor stays PROSPECT — never QUALIFYd.
        sponsor = get_success_data(api.create_sponsor(
            {"legal_name": "FizzCo Beverages LLC", "display_name": "FizzCo",
             "industry_category": "BEVERAGE"}, SALES))
        resp = api.create_contract(
            {"venue_id": venue["id"], "sponsor_id": sponsor["id"],
             "title": "Naming", "term_first_season": 2026,
             "term_last_season": 2028, "base_fee_cents": 10_000_000,
             "escalator_pct": 0, "escalator_mode": "SIMPLE"}, SALES)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ACTIVE,
                       expected_status=409)
