"""The grievance ladder, the remand loop, the filing window and the fiscal remedy."""

from test_helpers import (
    ApiErrorId,
    assert_grievance,
    assert_money_invariant,
    assert_same_instant,
    fixtures as fx,
    make_inmate_headers,
    validate_error,
    validate_success,
)


class TestFilingWindow:
    def test_filing_exactly_fifteen_days_after_the_event_is_inside_the_window(self, api):
        """PRD §3.8: "Filing is bounded: a grievance is accepted only while the current clock
        instant is at or before `grieved_event_at` plus 15 days, with the boundary instant
        itself still inside the window. Filing later is rejected at rung 13 with
        `ERR_GRIEVANCE_FILING_WINDOW_EXPIRED` (422). A filed grievance starts at `stage`
        `INFORMAL` and `status` `FILED`, with `stage_entered_at` stamped from the clock,
        `remand_count` 0 and `outcome` null."
        PRD §3.8: "The response window depends on the rung of the ladder the grievance
        currently occupies: 5 days at `INFORMAL`, 15 days at `FORMAL`, and 30 days at
        `APPEAL`, always measured from `stage_entered_at`."

        Design: Corner/validations/grievance_filing_window_boundary
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2300", full_name="Wil Yates", booked_at="2026-05-01T00:00:00Z"
        )
        fx.set_clock("2026-05-16T00:00:00Z")

        resp = api.create_grievance(
            inmate["id"],
            {
                "grievance_text": "filed exactly on the window boundary",
                "grieved_event_at": "2026-05-01T00:00:00Z",
            },
            make_inmate_headers(inmate["id"]),
        )
        data = validate_success(resp, 201)
        assert_grievance(data)
        assert data["stage"] == "INFORMAL"
        assert data["status"] == "FILED"
        assert_same_instant(
            data["response_due_at"], "2026-05-21T00:00:00Z", "response_due_at"
        )

        fx.set_clock("2026-05-16T00:00:01Z")
        late = api.create_grievance(
            inmate["id"],
            {
                "grievance_text": "filed one second too late",
                "grieved_event_at": "2026-05-01T00:00:00Z",
            },
            make_inmate_headers(inmate["id"]),
        )
        validate_error(late, ApiErrorId.ERR_GRIEVANCE_FILING_WINDOW_EXPIRED.value, 422)


class TestRemandLoop:
    def test_remand_returns_an_appeal_to_the_formal_rung(self, api, grievance_coordinator_headers):
        """PRD §3.8: "The second cycle edge is the remand. A `GrievanceCoordinator` reviewing
        a grievance that is `UNDER_REVIEW` at stage `APPEAL` may remand it back for
        re-hearing: the status becomes `REMANDED`, `remand_count` increments by 1 and the
        stage drops back to `FORMAL`."

        Design: Difficulty/non_linear_state_machine/grievance_remand_cycle_returns_appeal_to_formal
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1060", full_name="Harper Ives", booked_at="2026-05-01T00:00:00Z"
        )
        grievance = fx.setup_grievance_at_appeal_under_review(
            inmate["id"], "2026-05-01T00:00:00Z"
        )
        assert grievance["stage"] == "APPEAL"

        resp = api.remand_grievance(grievance["id"], grievance_coordinator_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "REMANDED"
        assert data["stage"] == "FORMAL"
        assert data["remand_count"] == 1

    def test_reaccepting_a_remanded_appeal_restarts_the_formal_response_window(
        self, api, grievance_coordinator_headers
    ):
        """PRD §3.8: "A `GrievanceCoordinator` accepts a grievance for review, moving it from
        `FILED` to `UNDER_REVIEW`; the same acceptance operation also brings a `REMANDED`
        grievance back to `UNDER_REVIEW`. Either way `stage_entered_at` is reset to the
        current clock instant and `response_due_at` recomputed for whatever stage the
        grievance now sits at — for a remanded appeal, that is the `FORMAL` rung's 15 days."

        Design: Difficulty/non_linear_state_machine/grievance_remand_cycle_returns_appeal_to_formal
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1061", full_name="Harper Ives", booked_at="2026-05-01T00:00:00Z"
        )
        grievance = fx.setup_grievance_at_appeal_under_review(
            inmate["id"], "2026-05-01T00:00:00Z"
        )
        validate_success(api.remand_grievance(grievance["id"], grievance_coordinator_headers), 200)

        resp = api.accept_grievance(grievance["id"], grievance_coordinator_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "UNDER_REVIEW"
        assert data["stage"] == "FORMAL"
        assert data["remand_count"] == 1
        assert_same_instant(
            data["stage_entered_at"], "2026-05-01T00:00:00Z", "stage_entered_at"
        )
        assert_same_instant(
            data["response_due_at"], "2026-05-16T00:00:00Z", "response_due_at"
        )

    def test_second_remand_is_refused_once_the_cap_is_reached(
        self, api, grievance_coordinator_headers
    ):
        """PRD §3.8: "A remand is accepted only while `remand_count` is strictly less than 1
        — one remand per grievance, no more — and a second attempt is rejected at rung 14 with
        `ERR_MAX_REMANDS_EXCEEDED` (409)."
        PRD §3.8: "Escalating advances the stage one rung, `INFORMAL` to `FORMAL` or `FORMAL`
        to `APPEAL`, returns the status to `FILED`, clears `outcome` back to null, resets
        `stage_entered_at` to the current clock instant and recomputes `response_due_at` for
        the new stage."

        Design: Corner/state_machines/grievance_max_remands_rejected_on_second_remand
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2170", full_name="Ivy Krebs", booked_at="2026-05-01T00:00:00Z"
        )
        grievance = fx.setup_grievance_at_appeal_under_review(
            inmate["id"], "2026-05-01T00:00:00Z"
        )
        validate_success(api.remand_grievance(grievance["id"], grievance_coordinator_headers), 200)
        fx.accept_grievance(grievance["id"])
        fx.decide_grievance(grievance["id"], "DENIED")
        fx.escalate_grievance(grievance["id"], inmate["id"])
        fx.accept_grievance(grievance["id"])

        resp = api.remand_grievance(grievance["id"], grievance_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_MAX_REMANDS_EXCEEDED.value, 409)

        current = fx.read_grievance(grievance["id"])
        assert current["remand_count"] == 1
        assert current["stage"] == "APPEAL"
        assert current["status"] == "UNDER_REVIEW"


class TestTerminalStates:
    def test_closing_a_decided_grievance_is_terminal_and_a_second_close_is_refused(
        self, api, grievance_coordinator_headers
    ):
        """PRD §3.8: "Two terminal states close the file. A `GrievanceCoordinator` closes a
        `DECIDED` grievance, moving it to `CLOSED`."
        PRD §2.5: "**Target state.** The addressed row's own `status` or `outcome` is one from
        which the requested transition is declared. Failure yields `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/grievance_close_and_withdraw_terminals
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2180", full_name="Jo Lopes", booked_at="2026-05-01T00:00:00Z"
        )
        grievance = fx.setup_accepted_grievance(
            inmate["id"], "2026-05-01T00:00:00Z", grievance_text="grievance A"
        )
        fx.decide_grievance(grievance["id"], "DENIED")

        first = api.close_grievance(grievance["id"], grievance_coordinator_headers)
        assert validate_success(first, 200)["status"] == "CLOSED"

        second = api.close_grievance(grievance["id"], grievance_coordinator_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE.value, 409)

        other = fx.file_grievance(
            inmate["id"], "2026-05-01T00:00:00Z", grievance_text="grievance B"
        )
        withdrawn = validate_success(
            api.withdraw_grievance(other["id"], make_inmate_headers(inmate["id"])), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["outcome"] == "WITHDRAWN"


class TestGrantedBillingGrievanceCascade:
    def test_granting_reverses_the_charge_and_appends_a_compensating_ledger_entry(
        self, api, grievance_coordinator_headers
    ):
        """PRD §3.8: "Level two applies when the outcome is `GRANTED`,
        `subject_copay_charge_id` is not null, and that charge's `status` is either `POSTED`
        or `DEBT_LIEN`: the charge transitions to `REVERSED` and its `reversal_grievance_id`
        is set to this grievance. Level three follows from the reversal — one ledger entry of
        type `REVERSAL` is appended whose `amount_cents` is the exact negation of the
        `amount_cents` of the ledger entry that originally posted that charge, so a 500-cent
        charge that posted as minus 500 is undone by plus 500."

        Design: Difficulty/transitive_cascade/grievance_granted_depth5_charge_reversal_to_indigency
        """
        scenario = fx.setup_billing_grievance_after_lookback_window()
        resp = api.decide_grievance(
            scenario["grievance"]["id"], {"outcome": "GRANTED"}, grievance_coordinator_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "DECIDED"
        assert data["outcome"] == "GRANTED"

        charge = fx.read_charge(scenario["charge"]["id"])
        assert charge["status"] == "REVERSED"
        assert charge["reversal_grievance_id"] == scenario["grievance"]["id"]

        entries = fx.ledger_entries_for(scenario["inmate"]["id"])
        reversals = [e for e in entries if e["entry_type"] == "REVERSAL"]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == 500
        assert reversals[0]["source_copay_charge_id"] == scenario["charge"]["id"]

    def test_the_reversal_restores_the_balance_and_re_derives_the_indigency_flag(
        self, api, grievance_coordinator_headers
    ):
        """PRD §3.8: "Level four recomputes the inmate's `account_balance_cents` from the
        full entry walk, and level five re-derives the inmate's `indigent_flag` from the
        changed balance."

        Design: Difficulty/transitive_cascade/grievance_granted_depth5_charge_reversal_to_indigency
        """
        scenario = fx.setup_billing_grievance_after_lookback_window()
        validate_success(
            api.decide_grievance(
                scenario["grievance"]["id"], {"outcome": "GRANTED"}, grievance_coordinator_headers
            ),
            200,
        )
        refreshed = fx.read_inmate(scenario["inmate"]["id"])
        assert refreshed["account_balance_cents"] == 600
        assert refreshed["indigent_flag"] is False

        entries = fx.ledger_entries_for(scenario["inmate"]["id"])
        assert len(entries) == 3
        assert sum(e["amount_cents"] for e in entries) == 600
        assert_money_invariant(entries, refreshed)

    def test_the_charge_and_its_reversal_conserve_the_trust_account_balance(
        self, api, grievance_coordinator_headers
    ):
        """PRD §2.9: "**The money invariant.** For every inmate, the sum of `amount_cents`
        across all of that inmate's ledger entries equals that inmate's
        `account_balance_cents` exactly, and the `balance_after_cents` recorded on the
        chronologically last entry equals `account_balance_cents` exactly. The compensating
        pair is a co-pay charge posting — which appends either a `CHARGE` or a `LIEN` entry —
        followed by the grievance-granted reversal, which appends a `REVERSAL` entry. After
        both have run, `account_balance_cents` must equal its exact pre-charge value with zero
        drift in either direction."

        Design: Difficulty/compensating_invariant/copay_reversal_conserves_trust_account_balance
        """
        scenario = fx.setup_billing_grievance_over_sick_call_charge()
        charge_before = fx.read_charge(scenario["charge_id"])
        assert charge_before["charge_variant"] == "FUNDED"
        assert charge_before["amount_cents"] == 500

        validate_success(
            api.decide_grievance(
                scenario["grievance"]["id"], {"outcome": "GRANTED"}, grievance_coordinator_headers
            ),
            200,
        )
        refreshed = fx.read_inmate(scenario["inmate"]["id"])
        assert refreshed["account_balance_cents"] == 1000
        assert fx.read_charge(scenario["charge_id"])["status"] == "REVERSED"

    def test_the_ledger_walk_ends_on_the_restored_running_balance(
        self, api, grievance_coordinator_headers
    ):
        """PRD §2.9: "**The money invariant.** For every inmate, the sum of `amount_cents`
        across all of that inmate's ledger entries equals that inmate's
        `account_balance_cents` exactly, and the `balance_after_cents` recorded on the
        chronologically last entry equals `account_balance_cents` exactly."

        Design: Difficulty/compensating_invariant/copay_reversal_conserves_trust_account_balance
        """
        scenario = fx.setup_billing_grievance_over_sick_call_charge()
        validate_success(
            api.decide_grievance(
                scenario["grievance"]["id"], {"outcome": "GRANTED"}, grievance_coordinator_headers
            ),
            200,
        )
        entries = fx.ledger_entries_for(scenario["inmate"]["id"])
        assert [e["amount_cents"] for e in entries] == [1000, -500, 500]
        assert entries[-1]["balance_after_cents"] == 1000

        refreshed = fx.read_inmate(scenario["inmate"]["id"])
        assert_money_invariant(entries, refreshed)
        assert fx.read_sick_call(scenario["sick_call"]["id"])["status"] == "SEEN"


class TestChargeReversibility:
    def test_a_waived_charge_cannot_be_reversed_by_a_granted_grievance(
        self, api, grievance_coordinator_headers
    ):
        """PRD §3.8: "A granted grievance that names a charge already `WAIVED` or already
        `REVERSED` is refused at rung 14 with `ERR_CHARGE_NOT_REVERSIBLE` (409) — there is
        nothing left to reverse."

        Design: Corner/validations/waived_charge_is_not_reversible_by_grievance
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2310", full_name="Xia Zeller", booked_at="2026-05-01T00:00:00Z"
        )
        charge = fx.post_copay_charge(inmate["id"], "MENTAL_HEALTH")
        assert charge["status"] == "WAIVED"
        grievance = fx.setup_accepted_grievance(
            inmate["id"],
            "2026-05-01T00:00:00Z",
            grievance_text="I should not have been billed at all",
            subject_copay_charge_id=charge["id"],
        )

        resp = api.decide_grievance(
            grievance["id"], {"outcome": "GRANTED"}, grievance_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_REVERSIBLE.value, 409)

        assert fx.read_charge(charge["id"])["status"] == "WAIVED"
        assert fx.read_grievance(grievance["id"])["status"] == "UNDER_REVIEW"
        assert fx.ledger_entries_for(inmate["id"]) == []
