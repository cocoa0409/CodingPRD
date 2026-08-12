"""Corner coverage: tranche exit paths (waive, cure-window boundaries), and
post-facto window expiries (rescission, appeal)."""
from test_helpers import (
    api_client,
    create_active_community,
    create_and_close_lot,
    create_offered_lot,
    create_open_phase,
    create_builder,
    create_resident,
    create_violation_hearing_scheduled,
    create_phase,
    create_lot,
    set_clock,
    setup_active_agreement_scenario,
    setup_missed_tranche_scenario,
    get_success_data,
    validate_error,
    make_builder_rep_headers,
    make_homeowner_resident_headers,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]


class TestTrancheWaivePath:
    def test_waive_lands_waived_and_leaves_builder_on_probation(self):
        """PRD §3.3: "An `AssociationDirector` may waive it, moving it to `WAIVED` with a recorded `waiver_reason` and forgiving the accrued penalty — it is frozen at its current value and no longer owed — but only while the community's `transition_stage` is not `TURNOVER_COMPLETE` (`ERR_DECLARANT_AUTHORITY_ENDED`)."
        PRD §3.3: "Standing is enforced automatically: the moment any tranche of any of the builder's agreements becomes `MISSED`, the builder drops to `PROBATION`; the moment any of its agreements becomes `DEFAULTED`, it drops to `SUSPENDED`.".

        Design: Corner/state_machines/tranche_waive_path
        """
        scenario = setup_missed_tranche_scenario(community_name="Waiver Wash")
        tranche = scenario["tranches"][0]
        waived = get_success_data(
            api_client.waive_tranche(tranche["id"], {"waiver_reason": "force majeure — flood"}, DIRECTOR)
        )
        assert waived["status"] == "WAIVED"

        builder = get_success_data(api_client.get_builder(scenario["builder"]["id"], EXEC))
        assert builder["standing"] == "PROBATION", (
            f"waiver does not restore standing, got {builder['standing']}"
        )
        agreement = get_success_data(api_client.get_agreement(scenario["agreement"]["id"], CTRL))
        assert agreement["status"] == "ACTIVE", (
            f"the agreement survives a waived tranche, got {agreement['status']}"
        )


class TestTrancheCureWindowBoundaries:
    def test_certify_inside_window_and_cure_past_deadline_both_rejected(self):
        """PRD §3.3: "Or a `DeclarantExecutive` may certify the default once the cure window has closed — the logical clock must be strictly after the `cure_deadline` (`ERR_CURE_WINDOW_OPEN` while it is still open) — moving the tranche to `DEFAULTED`.".
        PRD §3.3: "The builder's own `BuilderRep` may cure it — the acting user's `X-User-ID` must equal the agreement's `builder_id` (`ERR_FORBIDDEN_ROLE` otherwise) — by paying `payment_cents` exactly equal to the current `accrued_penalty_cents` (`ERR_PENALTY_AMOUNT_MISMATCH` on any other amount) while the logical clock is on or before the `cure_deadline`; attempting to cure a tranche that is not `MISSED`, or one whose cure deadline has already passed, is rejected with `ERR_TRANCHE_NOT_CURABLE`."
        PRD §3.3: "Each tranche's `cure_deadline` is computed as its `due_date` plus fourteen days, and its `lots_credited` and `accrued_penalty_cents` start at zero in `SCHEDULED` status.".

        Design: Corner/state_machines/tranche_cure_window_boundaries
        """
        scenario = setup_active_agreement_scenario(
            total_planned_units=20, planned_lot_count=10, total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 1), ("2026-06-30T00:00:00Z", 1)],
            community_name="Window Wells", earnest_money_cents=1000000,
        )
        t1, t2 = scenario["tranches"]
        builder = scenario["builder"]
        set_clock("2026-06-01T00:00:00Z")
        # 2026-07-10: both MISSED (due 2026-06-30), cure deadline 2026-07-14.
        set_clock("2026-07-10T00:00:00Z")

        resp_cert = api_client.certify_default(t1["id"], EXEC)
        validate_error(resp_cert, ApiErrorId.ERR_CURE_WINDOW_OPEN)

        set_clock("2026-07-15T00:00:00Z")
        resp_cure = api_client.cure_tranche(
            t2["id"], {"payment_cents": 15000}, make_builder_rep_headers(builder["id"])
        )
        validate_error(resp_cure, ApiErrorId.ERR_TRANCHE_NOT_CURABLE)


class TestRescissionAndAppealWindowsExpire:
    def _setup(self):
        """One CLOSED closing at 2026-06-01 and one FINED violation at
        2026-07-20 (cure deadline 2026-07-16, levy at day 4 -> 20,000c)."""
        scenario = setup_active_agreement_scenario(
            total_planned_units=10, planned_lot_count=5, total_lots_committed=1,
            tranches=[("2026-06-30T00:00:00Z", 1)], community_name="Window Waste",
            earnest_money_cents=1000000,
        )
        lot = create_offered_lot(scenario["phase"]["id"], "W1")
        set_clock("2026-06-01T00:00:00Z")
        closing = create_and_close_lot(scenario["agreement"]["id"], lot["id"])

        resident = create_resident(scenario["community"]["id"], "Wanda Late", "wanda@x.com")
        # Notice sent 2026-07-02 -> cure deadline 2026-07-16.
        violation = create_violation_hearing_scheduled(
            scenario["community"]["id"], lot["id"],
            escalate_at="2026-07-17T00:00:00Z",
            hearing_date="2026-07-20T00:00:00Z",
            respondent_resident_id=resident["id"],
            violation_type="SETBACK",
            notice_clock="2026-07-02T00:00:00Z",
        )
        set_clock("2026-07-20T00:00:00Z")
        fined = get_success_data(api_client.levy_fine(violation["id"], DIRECTOR))
        return closing, violation["id"], resident["id"], fined

    def test_rescind_past_thirty_days_rejected(self):
        """PRD §3.4: "Rescission of a `CLOSED` closing is a `DeclarantExecutive` action available only within thirty days of the `closing_date` — later attempts are rejected `ERR_RESCISSION_WINDOW_EXPIRED` — and it moves the closing to `RESCINDED` and unwinds the close: the credited tranche, when `credited_tranche_id` is set, loses one credit and, if it had been `SATISFIED`, reverts to `OPEN` when the logical clock is still on or before its `due_date` and to `MISSED` when the due date has passed; `closed_unit_count`, `closed_lot_count`, `lots_closed_count`, and `total_lots_purchased` each decrement and `closed_unit_pct` is recomputed; the lot returns to `OFFERED`; and the resident, if any, remains an `OWNER`.".

        Design: Corner/state_machines/rescission_and_appeal_windows_expire
        """
        closing, _, _, _ = self._setup()
        # closing_date 2026-06-01 + 30 days = 2026-07-01; clock is 2026-07-20.
        resp = api_client.rescind_closing(closing["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_EXPIRED)

    def test_appeal_past_thirty_days_rejected(self):
        """PRD §3.7: "Alternatively the respondent — resident or builder, with the acting user matching the respondent (`ERR_FORBIDDEN_ROLE`) — may appeal within thirty days of the fine with an `appeal_reason` (`ERR_APPEAL_WINDOW_EXPIRED` beyond that window), moving the violation to `APPEALED`."

        Design: Corner/state_machines/rescission_and_appeal_windows_expire
        """
        _, violation_id, resident_id, fined = self._setup()
        # Day-4 fine: 4 * 5000 = 20000.
        assert fined["fine_cents"] == 20000
        # Fine levied 2026-07-20; 2026-08-20 is 31 days later.
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.appeal_violation(
            violation_id, {"appeal_reason": "too late"},
            make_homeowner_resident_headers(resident_id),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
