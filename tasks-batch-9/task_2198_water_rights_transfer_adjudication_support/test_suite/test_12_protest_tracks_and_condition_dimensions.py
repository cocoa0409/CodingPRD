"""Protest closure routes, and the two independent axes of an approval condition.

PRD §3.6: "Whichever route clears the last protest — a stipulation on either
track, a dismissal, or a withdrawal — the same clearance cascade fires when
`unresolved_protest_count` reaches exactly 0."
"""
import pytest
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
)
from test_helpers.factories import condition_entry
from test_helpers.fixtures import (
    ANALYST,
    HEARING_OFFICER,
    conditions_of,
    create_claimant,
    decide,
    deposit,
    file_protest,
    make_claimant_headers,
    open_account,
    read_account,
    read_application,
    read_claimant,
    read_condition,
    read_right,
    route_protest,
    set_clock,
    setup_application_ready_for_decision,
    setup_published_application,
)

CLOCK = "2026-03-01T00:00:00Z"


class TestTheClearanceCascadeIsKeyedOnTheCounter:
    """PRD §3.6 — two protestants, two withdrawals, one cascade.

    A 100.00 AF application on a 195.00 AF right is published with a
    `SEASONAL_AVERAGE` analysis whose 78.00 AF return-flow credit exactly cancels
    its 78.00 AF gross depletion. Two separate claimants each file one protest,
    so `unresolved_protest_count` starts at 2.
    """

    def _two_protests(self):
        bundle = setup_published_application(
            requested_af=100.00,
            clock=CLOCK,
            analysis_overrides={"return_flow_credit_af": 78.00},
        )
        application_id = bundle["application"]["id"]
        bundle["protests"] = []
        for name, email, kind, injury in (
            ("Cottonwood Cattle Co", "b@cotton.example", "INDIVIDUAL", 12.00),
            ("City of Rill", "c@rill.example", "MUNICIPALITY", 4.00),
        ):
            protestant = create_claimant(
                legal_name=name, contact_email=email, entity_type=kind
            )
            bundle["protests"].append(
                (protestant, file_protest(application_id, protestant["id"], injury))
            )
        bundle["application"] = read_application(application_id)
        return bundle

    def _withdraw(self, protestant, protest, reason):
        return get_success_data(
            api_client.withdraw_protest(
                protest["id"], reason, make_claimant_headers(protestant["id"])
            )
        )

    def test_withdrawing_the_first_of_two_protests_moves_only_the_counter(self):
        """PRD §3.6: "A protestant may also abandon its own protest from `FILED`,
        `IN_NEGOTIATION` or `IN_HEARING`, supplying a `withdrawal_reason`... The
        protest reaches the terminal `WITHDRAWN` with no offset and no condition,
        and `unresolved_protest_count` is decremented."

        The cascade of PRD §3.6 fires only "when `unresolved_protest_count` reaches
        exactly 0", so with one protest still outstanding the application stays
        `UNDER_PROTEST` and its analysis stays `DRAFT`.

        Design: Corner/state_machines/sm_protest_withdrawal_of_the_last_protest_finalizes_the_application
        """
        bundle = self._two_protests()
        assert bundle["application"]["status"] == "UNDER_PROTEST"
        assert bundle["application"]["unresolved_protest_count"] == 2
        protestant, protest = bundle["protests"][0]

        withdrawn = self._withdraw(protestant, protest, "Settled privately.")

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "UNDER_PROTEST"
        assert application["unresolved_protest_count"] == 1
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], HEARING_OFFICER)
        )
        assert analysis["status"] == "DRAFT"
        assert read_right(bundle["right"]["id"])["pending_review_count"] == 1

    def test_withdrawing_the_last_protest_finalizes_the_analysis_with_no_offset(self):
        """PRD §3.6: "The application auto-transitions `UNDER_PROTEST →
        READY_FOR_DECISION`; its `DRAFT` injury analysis moves to the terminal
        `FINALIZED`, freezing `gross_depletion_af`, `offset_af` and
        `net_injury_af`; `pending_review_count` on the right is decremented".

        No operator asks for the transition — clearing the counter is what causes
        it. The withdrawal route grants nothing volumetric, so `offset_af` freezes
        at 0.00 rather than absorbing either claim, and PRD §3.6's cascade "fires
        regardless of whether `protest_deadline` has passed" even though the clock
        is still inside the window. Clearing protests is not a release of escrow.

        Design: Corner/state_machines/sm_protest_withdrawal_of_the_last_protest_finalizes_the_application
        """
        bundle = self._two_protests()
        first_protestant, first_protest = bundle["protests"][0]
        self._withdraw(first_protestant, first_protest, "Settled privately.")
        last_protestant, last_protest = bundle["protests"][1]

        withdrawn = self._withdraw(
            last_protestant, last_protest, "No longer opposed to the transfer."
        )

        assert withdrawn["status"] == "WITHDRAWN"
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["unresolved_protest_count"] == 0
        assert application["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], HEARING_OFFICER)
        )
        assert analysis["status"] == "FINALIZED"
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["pending_review_count"] == 0
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)


class TestUndeclaredProtestEdges:
    """PRD §3.6 — the protest fork has exactly one entry and three exits.

    One protest sits on a published 100.00 AF application, which is therefore
    `UNDER_PROTEST`. Each attempt below asks for an edge the document never
    declares, and each request is otherwise well formed and correctly authorised.
    """

    def _one_protest(self):
        bundle = setup_published_application(requested_af=100.00, clock=CLOCK)
        protestant = create_claimant(
            legal_name="Cottonwood Cattle Co",
            contact_email="b@cotton.example",
            entity_type="INDIVIDUAL",
        )
        bundle["protestant"] = protestant
        bundle["protest"] = file_protest(
            bundle["application"]["id"], protestant["id"], 12.00
        )
        bundle["application"] = read_application(bundle["application"]["id"])
        return bundle

    def test_four_undeclared_protest_edges_are_all_refused_on_state(self):
        """PRD §3.6: "Routing is the fork, and it belongs exclusively to the
        `HearingOfficer`. Supplying a `track` of `NEGOTIATION` moves the protest
        `FILED → IN_NEGOTIATION`; supplying `HEARING` moves it `FILED →
        IN_HEARING`." Resolution runs from those two states only: "exactly three
        combinations of track and `outcome` are admissible", and "The fourth
        combination — negotiation plus dismissal — is not a declared transition
        and is refused with `ERR_INVALID_STATE`."

        PRD §3.5 closes the set: "attempting to close the window on an
        `UNDER_PROTEST` application is `ERR_INVALID_STATE`."

        So an unrouted protest cannot be resolved, a negotiation-track protest
        cannot be dismissed, a routed protest cannot be re-routed, and the window
        of a protested application cannot be closed — four refusals, one code.

        Design: Corner/state_machines/sm_protest_invalid_transitions_rejected
        """
        bundle = self._one_protest()
        protest_id = bundle["protest"]["id"]
        application_id = bundle["application"]["id"]
        version_before = bundle["application"]["version"]

        premature = api_client.resolve_protest(
            protest_id,
            {
                "outcome": "STIPULATE",
                "resolution_note": "Resolving before routing.",
                "stipulated_offset_af": 5.00,
            },
            HEARING_OFFICER,
        )
        validate_error(
            premature, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
        )
        unrouted = get_success_data(api_client.get_protest(protest_id, ANALYST))
        assert unrouted["status"] == "FILED"
        assert unrouted["track"] is None
        assert unrouted["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)

        route_protest(protest_id, "NEGOTIATION")
        dismissal = api_client.resolve_protest(
            protest_id,
            {
                "outcome": "DISMISS",
                "resolution_note": "Dismissal attempted on the negotiation track.",
            },
            HEARING_OFFICER,
        )
        validate_error(
            dismissal, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
        )
        rerouted = api_client.route_protest(protest_id, "HEARING", HEARING_OFFICER)
        validate_error(
            rerouted, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
        )
        closure = api_client.close_protest_period(application_id, HEARING_OFFICER)
        validate_error(closure, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

        protest = get_success_data(api_client.get_protest(protest_id, ANALYST))
        assert protest["status"] == "IN_NEGOTIATION"
        assert protest["track"] == "NEGOTIATION"
        application = read_application(application_id)
        assert application["status"] == "UNDER_PROTEST"
        assert application["unresolved_protest_count"] == 1
        assert application["version"] == version_before
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "DRAFT"


class TestTheTwoConditionDimensionsInterlockOneWay:
    """PRD §3.8 — "`status` is the compliance dimension and `payment_status` is
    the fiscal dimension, and the two evolve independently through separate
    operations."

    A 100.00 AF application on a bank-enrolled 195.00 AF right leaves a residual
    injury of 20.00 AF, because its `SEASONAL_AVERAGE` gross depletion of 78.00 AF
    is met by a 58.00 AF return-flow credit. It is approved with a single 20.00 AF
    `MITIGATION_PAYMENT` condition. The claimant also holds a bank account funded
    with 20.00 AF of credit, which is comfortably clear of PRD §2.10's 5.00
    acre-foot floor, so the claimant's standing is the only restriction trigger in
    play.
    """

    DUE = "2026-06-01T00:00:00Z"

    def _approved_with_a_priced_condition(self):
        bundle = setup_application_ready_for_decision(
            requested_af=100.00,
            clock=CLOCK,
            analysis_overrides={"return_flow_credit_af": 58.00},
            bank_enrolled=True,
        )
        assert bundle["analysis"]["net_injury_af"] == pytest.approx(20.00, abs=0.01)
        bundle["account"] = open_account(bundle["claimant"]["id"])
        deposit(bundle["account"]["id"], bundle["right"]["id"], 20.00)
        bundle["application"] = decide(
            bundle["application"]["id"],
            "APPROVE_WITH_CONDITIONS",
            conditions=[condition_entry("MITIGATION_PAYMENT", 20.00, self.DUE)],
        )
        bundle["condition"] = conditions_of(bundle["application"]["id"])[0]
        return bundle

    def _satisfy(self, bundle, evidence):
        return api_client.satisfy_approval_condition(
            bundle["condition"]["id"],
            evidence,
            make_claimant_headers(bundle["claimant"]["id"]),
        )

    def test_an_outstanding_fee_blocks_compliance_sign_off(self):
        """PRD §3.8: "First, `base_fee_usd` is `required_af` multiplied by a base
        rate of 125.00 dollars per acre-foot, rounded to 2 decimal places. Second,
        the tier is selected from that pre-surcharge subtotal and never from the
        final total: a `base_fee_usd` strictly below 5,000.00 dollars takes a
        `surcharge_pct` of 0.040". 20.00 AF prices at 2,500.00 plus 100.00 for a
        total of 2,600.00.

        PRD §3.8: "The cross-dimension guard bites here: `payment_status` must be
        `NOT_APPLICABLE` or `PAID`, so an outstanding mitigation fee blocks
        compliance sign-off and yields `ERR_CONDITION_FEE_OUTSTANDING` (HTTP 409).
        The compliance dimension cannot terminate while the fiscal dimension is
        still owed."

        Design: Corner/state_machines/sm_approval_condition_fee_and_compliance_dimensions_are_independent
        """
        bundle = self._approved_with_a_priced_condition()
        condition = bundle["condition"]
        assert condition["source"] == "DECISION"
        assert condition["status"] == "IMPOSED"
        assert condition["payment_status"] == "OUTSTANDING"
        assert condition["base_fee_usd"] == pytest.approx(2500.00, abs=0.01)
        assert condition["surcharge_pct"] == pytest.approx(0.040, abs=0.0005)
        assert condition["admin_surcharge_usd"] == pytest.approx(100.00, abs=0.01)
        assert condition["total_fee_usd"] == pytest.approx(2600.00, abs=0.01)
        assert bundle["application"]["mitigation_fee_total_usd"] == pytest.approx(
            2600.00, abs=0.01
        )
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(
            2600.00, abs=0.01
        )
        assert claimant["standing_status"] == "DELINQUENT"
        assert read_account(bundle["account"]["id"])["posture"] == "RESTRICTED"

        response = self._satisfy(bundle, "Device installed, fee unpaid.")

        validate_error(
            response,
            ApiErrorId.ERR_CONDITION_FEE_OUTSTANDING.value,
            expected_status=409,
        )
        unchanged = read_condition(condition["id"])
        assert unchanged["status"] == "IMPOSED"
        assert unchanged["payment_status"] == "OUTSTANDING"

    def test_payment_restores_standing_and_posture_then_sign_off_succeeds(self):
        """PRD §3.8: "The condition's `payment_status` moves `OUTSTANDING → PAID`
        and its `version` is bumped, while `status` stays exactly where it was,
        because paying does not satisfy a condition."

        PRD §3.8: "When that balance reaches precisely 0.00 and `standing_status`
        reads `DELINQUENT`, standing returns to `IN_GOOD_STANDING`... Finally every
        water bank account of that claimant recomputes its posture and bumps its
        `version`, so a `RESTRICTED` account clears only when the standing is
        genuinely restored and no other restriction trigger — thin available credit
        — still applies." The account's 20.00 AF of available credit clears PRD
        §2.10's floor, so restoring standing is enough to take it back to `OPEN`.

        Only then does the compliance axis move: PRD §3.8 — "From `IMPOSED` it is
        ordinary sign-off, moving the condition `IMPOSED → SATISFIED`, which is
        terminal, bumping the condition's `version` and touching no other row."

        Design: Corner/state_machines/sm_approval_condition_fee_and_compliance_dimensions_are_independent
        """
        bundle = self._approved_with_a_priced_condition()
        condition_id = bundle["condition"]["id"]

        paid = get_success_data(
            api_client.pay_approval_condition(
                condition_id, make_claimant_headers(bundle["claimant"]["id"])
            )
        )

        assert paid["payment_status"] == "PAID"
        assert paid["status"] == "IMPOSED", (
            "PRD §3.8 — paying does not sign off compliance"
        )
        assert paid["version"] > bundle["condition"]["version"]
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert claimant["standing_status"] == "IN_GOOD_STANDING"
        account = read_account(bundle["account"]["id"])
        assert account["posture"] == "OPEN"
        assert account["deposited_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)

        satisfied = get_success_data(
            self._satisfy(bundle, "Mitigation works completed and inspected.")
        )

        assert satisfied["status"] == "SATISFIED"
        assert satisfied["payment_status"] == "PAID"


class TestTheCureLegUnlocksReinstatement:
    """PRD §3.8 — "`VIOLATED` is deliberately not terminal for exactly this
    reason."

    A 100.00 AF transfer is approved subject to a single 20.00 AF
    `DRY_YEAR_FORBEARANCE` condition due 2026-06-01, so the fiscal axis reads
    `NOT_APPLICABLE` throughout and no fee can interfere. With the clock at
    2026-06-02 the condition is recorded as violated, which suspends the right.

    PRD §3.2 puts *two* gates on reinstatement — "no approval condition on any
    application of this right may still read `VIOLATED`, and
    `consecutive_nonuse_years` must be strictly below five" — so the right is
    documented with a metered record for every year from 2020 through 2025. At
    the 2026 clock the window is 2016 through 2025, which leaves the run
    2016-2019, four consecutive non-use years: the statutory gate is satisfied at
    its boundary and the violated condition is the only thing standing between
    the right and reinstatement, which is exactly what this class exercises. The
    study period stays 2023-2025, so `certified_hcu_af` still reads 195.00.
    """

    DUE = "2026-06-01T00:00:00Z"
    AFTER_DUE = "2026-06-02T00:00:00Z"
    USE_YEARS = (2020, 2021, 2022, 2023, 2024, 2025)

    def _violated(self):
        bundle = setup_application_ready_for_decision(
            requested_af=100.00,
            clock=CLOCK,
            use_years=self.USE_YEARS,
            analysis_overrides={"return_flow_credit_af": 58.00},
        )
        bundle["application"] = decide(
            bundle["application"]["id"],
            "APPROVE_WITH_CONDITIONS",
            conditions=[condition_entry("DRY_YEAR_FORBEARANCE", 20.00, self.DUE)],
        )
        bundle["condition"] = conditions_of(bundle["application"]["id"])[0]
        set_clock(self.AFTER_DUE)
        bundle["condition"] = get_success_data(
            api_client.violate_approval_condition(
                bundle["condition"]["id"],
                "No forbearance recorded by the due date.",
                ANALYST,
            )
        )
        bundle["right"] = read_right(bundle["right"]["id"])
        return bundle

    def _assessment(self, right_id):
        return get_success_data(api_client.get_forfeiture_assessment(right_id, ANALYST))

    def _reinstate(self, right_id, note):
        return api_client.reinstate_water_right(right_id, note, ANALYST)

    def test_reinstatement_is_refused_while_the_violation_stands(self):
        """PRD §3.2: "Two conditions must hold: no approval condition on any
        application of this right may still read `VIOLATED`, and
        `consecutive_nonuse_years` must be strictly below five. Failure on either
        count is `ERR_VIOLATION_UNRESOLVED` (HTTP 409)."

        Here the second condition already holds — four consecutive non-use years
        is "strictly below five" — so the violated condition is the sole ground of
        refusal.

        PRD §3.8's violation cascade put the right here: "The water right behind
        the application moves to `SUSPENDED` — reachable from `ACTIVE`, from
        `ENCUMBERED` or from `PARTIALLY_TRANSFERRED` — its forfeiture score is
        recomputed with the twelve-point suspension penalty now applying". PRD
        §3.2's sum reads 9 x 4 non-use years, plus 25 x 0.0000 unverified, plus
        30 x (1 - 0.7500) underuse, plus the 12-point suspension penalty, less the
        10-point meter credit: 45.50, which PRD §3.2 bands `ELEVATED`. Without the
        penalty the same right would read 33.50.

        Design: Corner/state_machines/sm_approval_condition_cure_leg_unlocks_water_right_reinstatement
        """
        bundle = self._violated()
        right_id = bundle["right"]["id"]
        assert bundle["condition"]["status"] == "VIOLATED"
        assert bundle["condition"]["payment_status"] == "NOT_APPLICABLE"
        assert bundle["right"]["status"] == "SUSPENDED"
        suspended = self._assessment(right_id)
        assert suspended["consecutive_nonuse_years"] == 4
        assert suspended["suspended_penalty"] == pytest.approx(12.00, abs=0.01)
        assert suspended["forfeiture_risk_score"] == pytest.approx(45.50, abs=0.01)
        assert suspended["forfeiture_risk_band"] == "ELEVATED"
        version_before = bundle["right"]["version"]

        response = self._reinstate(
            right_id, "Premature reinstatement while the violation stands."
        )

        validate_error(
            response, ApiErrorId.ERR_VIOLATION_UNRESOLVED.value, expected_status=409
        )
        right = read_right(right_id)
        assert right["status"] == "SUSPENDED"
        assert right["version"] == version_before

    def test_the_cured_right_reinstates_onto_partially_transferred(self):
        """PRD §3.8: "From `VIOLATED` it is the cure leg — late compliance after
        field enforcement already recorded a violation — moving the condition
        `VIOLATED → SATISFIED` and bumping its `version`... Curing does not itself
        lift anything: the right stays `SUSPENDED`, since suspension is sticky in the
        status derivation, and its suspended leases stay `SUSPENDED` until each is
        separately resumed."

        PRD §3.2: "On success the right leaves `SUSPENDED` and its status is
        re-derived — which means it may well land on `ENCUMBERED` or
        `PARTIALLY_TRANSFERRED` rather than `ACTIVE`, depending on what its ledger
        holds — the forfeiture score is recomputed without the twelve-point
        suspension penalty". With 100.00 AF already transferred away, PRD §2.10's
        precedence lands the right on `PARTIALLY_TRANSFERRED` and the score falls
        back to 33.50 — the same sum as before, less the 12-point penalty.

        Design: Corner/state_machines/sm_approval_condition_cure_leg_unlocks_water_right_reinstatement
        """
        bundle = self._violated()
        right_id = bundle["right"]["id"]

        cured = get_success_data(
            api_client.satisfy_approval_condition(
                bundle["condition"]["id"],
                "Late forbearance agreement executed and verified.",
                make_claimant_headers(bundle["claimant"]["id"]),
            )
        )

        assert cured["status"] == "SATISFIED"
        assert cured["payment_status"] == "NOT_APPLICABLE"
        assert read_right(right_id)["status"] == "SUSPENDED", (
            "PRD §3.8 — curing does not itself lift the suspension"
        )

        right = get_success_data(
            self._reinstate(right_id, "Violation cured; right returned to service.")
        )

        assert right["status"] == "PARTIALLY_TRANSFERRED"
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assessment = self._assessment(right_id)
        assert assessment["suspended_penalty"] == pytest.approx(0.00, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(33.50, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "LOW"
