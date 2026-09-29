"""Endpoint contracts: the administrative clock, the computed funded-status read,
the participant-assignment link, carrier solicitation, and the settlement-entry
ledger reads.

Each test drives one declared endpoint from an empty database, builds every
precondition through other declared endpoints, and asserts the figures the PRD
derives rather than a hardcoded guess.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    constants,
    factories,
    fixtures,
    make_insurer_rep_headers,
    sponsor_headers,
)
from test_helpers.api_errors import (
    ERR_DUPLICATE_QUOTE_REQUEST,
    ERR_INSURER_NOT_FOUND,
    ERR_PARTICIPANT_ALREADY_ASSIGNED,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_PARTICIPANT_PLAN_MISMATCH,
    ERR_SETTLEMENT_ENTRY_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_fields,
    assert_settlement_entry_shape,
    assert_version_unchanged,
)

RETIREE = "RETIREE_IN_PAY"
DEFERRED = "DEFERRED_VESTED"


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------


def _lump_sum_authorized_plan(api, **plan_overrides):
    """A plan whose amendment authorizes lump-sum activity only."""
    plan = fixtures.create_plan(api, **plan_overrides)
    fixtures.create_approved_strategy(api, plan["id"], "LUMP_SUM_WINDOW")
    return fixtures.adopt_amendment(api, plan["id"], "LUMP_SUM_ONLY")


def _deferred_participant(api, plan_id, monthly_cents, months=240):
    """A cleansed deferred-vested participant eligible for a notice."""
    return fixtures.create_clean_participant(
        api,
        plan_id,
        cohort=DEFERRED,
        stated_monthly_benefit_cents=monthly_cents,
        credited_service_months=months,
        final_average_monthly_earnings_cents=constants.fame_for_zero_variance(
            monthly_cents, months
        ),
    )


def _open_window(api, plan_id, opens_at, closes_at, **window_overrides):
    """Schedule a window, move the clock to its opening instant, and open it."""
    window = fixtures.create_window(
        api, plan_id, opens_at=opens_at, closes_at=closes_at, **window_overrides
    )
    fixtures.set_clock(api, opens_at)
    return fixtures.open_window(api, window["id"])


class TestLogicalClockEndpoint:
    """The clock capability moves time and nothing else."""

    def test_endpoint_clock_move_past_a_deadline_fires_no_transition(self, api):
        """Moving the clock beyond a window's `closes_at` leaves the window OPEN and its notice untouched.

        Moving the clock changes no entity state and fires no transitions.
        The server maintains a logical clock whose value at startup is exactly `2026-08-01T00:00:00Z`, and which may only be moved by an administrative test-driving capability that accepts a `current_utc` instant and sets the clock to it.

        Design: Corner/endpoints/clock_endpoint_moves_time_without_firing_any_transition
        """
        fixtures.reset_clock(api)
        plan = _lump_sum_authorized_plan(api)
        participant = _deferred_participant(api, plan["id"], 20000)
        window = _open_window(
            api,
            plan["id"],
            "2026-09-01T00:00:00Z",
            "2026-10-15T00:00:00Z",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        assert_fields(window, window_status="OPEN", notice_count=1)
        election = fixtures.election_for(api, window["id"], participant["id"])
        assert election["election_status"] == "NOTICE_SENT"
        plan_before = fixtures.read_plan(api, plan["id"])
        participant_before = fixtures.read_participant(api, participant["id"])

        fixtures.set_clock(api, "2026-11-01T00:00:00Z")

        windows = fixtures.list_windows(api, plan["id"])
        assert len(windows) == 1
        assert windows[0]["window_status"] == "OPEN"
        assert windows[0]["closed_at"] is None
        assert_version_unchanged(window, windows[0])
        election_after = fixtures.read_election(api, election["id"])
        assert election_after["election_status"] == "NOTICE_SENT"
        assert_version_unchanged(election, election_after)
        assert_version_unchanged(plan_before, fixtures.read_plan(api, plan["id"]))
        assert_version_unchanged(
            participant_before, fixtures.read_participant(api, participant["id"])
        )

    def test_endpoint_clock_move_only_ripens_the_closing_the_client_must_still_request(
        self, api, administrator
    ):
        """The closing the clock made possible only happens when it is asked for, and stamps the clock.

        Closing a window moves it `OPEN → CLOSED` and may only be requested once the logical clock has reached `closes_at`; an early attempt is rejected with `ERR_WINDOW_STATE_INVALID`.
        First, every election of the window still sitting in `NOTICE_SENT` transitions to `DEFAULTED_NO_RESPONSE` — silence is a decision, and the participant keeps their annuity.
        Third, `closed_at` is stamped from the logical clock and the window's `version` is bumped.

        Design: Corner/endpoints/clock_endpoint_moves_time_without_firing_any_transition
        """
        fixtures.reset_clock(api)
        plan = _lump_sum_authorized_plan(api)
        participant = _deferred_participant(api, plan["id"], 20000)
        window = _open_window(
            api,
            plan["id"],
            "2026-09-01T00:00:00Z",
            "2026-10-15T00:00:00Z",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        election = fixtures.election_for(api, window["id"], participant["id"])

        fixtures.set_clock(api, "2026-11-01T00:00:00Z")
        closed = validate_success(api.post_window_closing(window["id"], {}, administrator))

        assert_fields(closed, window_status="CLOSED", approved_lump_sum_total_cents=0)
        assert closed["closed_at"].startswith("2026-11-01T00:00:00")
        assert closed["version"] == window["version"] + 1
        election_after = fixtures.read_election(api, election["id"])
        assert election_after["election_status"] == "DEFAULTED_NO_RESPONSE"


class TestFundedStatusRead:
    """The funded-status read is a pure computation over stored measurements."""

    def test_endpoint_funded_status_computes_every_figure_fresh(self, api, regulator):
        """A regulator's funded-status read reports both bases, the gap and the participant total.

        Its accounting figure, `accounting_funded_status_bp`, is 0 whenever `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by 10,000 and rounded half up over `total_liability_cents`, so a fully funded plan reads 10000 basis points.
        Alongside it the system computes a settlement-basis view: `settlement_basis_liability_cents` is `total_liability_cents` multiplied by 10,700 basis points and rounded half up over 10,000 — that is, the accounting obligation uplifted by seven percent to reflect what a carrier would charge to take it on — and `settlement_funded_status_bp` is 0 when that uplifted liability is 0 and otherwise `plan_assets_cents` multiplied by 10,000 and rounded half up over `settlement_basis_liability_cents`.
        The `unfunded_settlement_gap_cents` is the amount by which `settlement_basis_liability_cents` exceeds `plan_assets_cents`, or 0 when assets already reach or exceed the uplifted liability.
        Finally `participant_liability_total_cents` is the sum of `accounting_liability_cents` across the plan's participant records whose `participant_status` is `IN_PLAN` or `ASSIGNED`, and is 0 when no participant qualifies.

        Design: Corner/endpoints/funded_status_is_a_pure_computed_read_visible_to_the_regulator
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(
            api, total_liability_cents=100000000, plan_assets_cents=92000000
        )
        fixtures.create_participant(
            api,
            plan["id"],
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            credited_service_months=320,
            final_average_monthly_earnings_cents=250000,
        )

        view = validate_success(api.get_funded_status(plan["id"], regulator))

        assert_fields(
            view,
            accounting_funded_status_bp=constants.funded_status_bp(92000000, 100000000),
            settlement_basis_liability_cents=constants.settlement_basis_liability(100000000),
            settlement_funded_status_bp=constants.settlement_funded_status_bp(
                92000000, 100000000
            ),
            unfunded_settlement_gap_cents=constants.unfunded_settlement_gap_cents(
                92000000, 100000000
            ),
            participant_liability_total_cents=constants.accounting_liability(100000, DEFERRED),
            cumulative_settlement_charge_cents=0,
            deferred_settlement_charge_cents=0,
        )
        assert view["accounting_funded_status_bp"] == 9200
        assert view["settlement_basis_liability_cents"] == 107000000
        assert view["settlement_funded_status_bp"] == 8598
        assert view["unfunded_settlement_gap_cents"] == 15000000
        assert view["participant_liability_total_cents"] == 11460000

    def test_endpoint_funded_status_persists_nothing_and_reads_alike_for_every_reader(
        self, api, regulator, actuary
    ):
        """The regulator and the actuary see the same figures, and the read leaves no trace.

        A funded-status read returns all of these together with the plan's `cumulative_settlement_charge_cents` and `deferred_settlement_charge_cents`, computes them fresh, and persists nothing.

        Design: Corner/endpoints/funded_status_is_a_pure_computed_read_visible_to_the_regulator
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(
            api, total_liability_cents=100000000, plan_assets_cents=92000000
        )
        fixtures.create_participant(
            api,
            plan["id"],
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            credited_service_months=320,
            final_average_monthly_earnings_cents=250000,
        )
        plan_before = fixtures.read_plan(api, plan["id"])

        regulator_view = validate_success(api.get_funded_status(plan["id"], regulator))
        actuary_view = validate_success(api.get_funded_status(plan["id"], actuary))
        second_regulator_view = validate_success(api.get_funded_status(plan["id"], regulator))

        assert regulator_view == actuary_view
        assert regulator_view == second_regulator_view
        assert_version_unchanged(plan_before, fixtures.read_plan(api, plan["id"]))
        _rows, meta = validate_paginated(
            api.list_settlement_entries(sponsor_headers(), {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0


class TestParticipantAssignment:
    """Assignment links a participant to a tranche or refuses with a named code."""

    def _plan_pair(self, api):
        plan_a = fixtures.create_plan(api)
        plan_b = fixtures.create_plan(api)
        deferred_a = fixtures.create_participant(
            api,
            plan_a["id"],
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            credited_service_months=320,
            final_average_monthly_earnings_cents=250000,
        )
        retiree_a = fixtures.create_participant(
            api,
            plan_a["id"],
            cohort=RETIREE,
            stated_monthly_benefit_cents=250000,
            credited_service_months=400,
        )
        deferred_b = fixtures.create_participant(
            api,
            plan_b["id"],
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            credited_service_months=320,
            final_average_monthly_earnings_cents=250000,
        )
        tranche = fixtures.create_tranche(api, plan_a["id"], DEFERRED)
        return tranche, deferred_a, retiree_a, deferred_b

    def test_endpoint_participant_assignment_refuses_an_unknown_or_foreign_participant(
        self, api, administrator
    ):
        """An unresolvable participant is a 404 while a foreign plan or cohort is a plan mismatch.

        The same discipline extends to identifiers supplied in a request body or as a list filter rather than in the path. A quote request naming an `insurer_id` that does not exist fails with `ERR_INSURER_NOT_FOUND`; a tranche assignment naming a `participant_id` that does not exist fails with `ERR_PARTICIPANT_NOT_FOUND`.
        A participant whose plan differs from the tranche's plan, or whose `cohort` differs from the tranche's `target_cohort`, is rejected with `ERR_PARTICIPANT_PLAN_MISMATCH`.

        Design: Corner/endpoints/participant_assignment_links_two_entities_or_refuses
        """
        fixtures.reset_clock(api)
        tranche, _deferred_a, retiree_a, deferred_b = self._plan_pair(api)

        validate_error(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(NON_EXISTENT_UUID),
                administrator,
            ),
            ERR_PARTICIPANT_NOT_FOUND,
        )
        validate_error(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(deferred_b["id"]),
                administrator,
            ),
            ERR_PARTICIPANT_PLAN_MISMATCH,
        )
        validate_error(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(retiree_a["id"]),
                administrator,
            ),
            ERR_PARTICIPANT_PLAN_MISMATCH,
        )

        after = fixtures.read_tranche(api, tranche["id"])
        assert_fields(
            after,
            assigned_participant_count=0,
            accounting_liability_cents=0,
            settlement_liability_cents=0,
            data_readiness_flag="BLOCKED",
        )
        assert_version_unchanged(tranche, after)

    def test_endpoint_participant_assignment_links_the_pair_and_recomputes_the_tranche(
        self, api, administrator
    ):
        """A matching participant moves to ASSIGNED and the tranche's sums and readiness follow.

        A `PlanAdministrator` then assigns participants one at a time by supplying a `participant_id`, moving that participant `IN_PLAN → ASSIGNED` and setting its `tranche_id`.
        A successful assignment recomputes the tranche's `assigned_participant_count`, `accounting_liability_cents`, `settlement_liability_cents`, and `data_readiness_flag`, and bumps both the participant's and the tranche's `version`.
        The `data_readiness_flag` is `BLOCKED` if the population is empty, `BLOCKED` if any assigned participant's `data_status` is anything other than `CLEAN`, `BLOCKED` if any assigned participant's `mortality_status` is anything other than `ALIVE_CONFIRMED`, `BLOCKED` if any assigned participant's `benefit_audit_status` is outside `PASSED_CLOSED` and `CORRECTED`, and `READY` only when none of those conditions holds.

        Design: Corner/endpoints/participant_assignment_links_two_entities_or_refuses
        """
        fixtures.reset_clock(api)
        tranche, deferred_a, _retiree_a, _deferred_b = self._plan_pair(api)

        updated = validate_success(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(deferred_a["id"]),
                administrator,
            )
        )

        assert_fields(
            updated,
            assigned_participant_count=1,
            accounting_liability_cents=constants.accounting_liability(100000, DEFERRED),
            settlement_liability_cents=constants.settlement_liability(100000, DEFERRED),
            data_readiness_flag="BLOCKED",
        )
        assert updated["accounting_liability_cents"] == 11460000
        assert updated["settlement_liability_cents"] == 12540000
        assert updated["version"] == tranche["version"] + 1
        participant_after = fixtures.read_participant(api, deferred_a["id"])
        assert_fields(
            participant_after, participant_status="ASSIGNED", tranche_id=tranche["id"]
        )
        assert participant_after["version"] == deferred_a["version"] + 1

    def test_endpoint_participant_assignment_refuses_a_second_link(self, api, administrator):
        """Re-assigning the participant the tranche already holds is refused as already assigned.

        A participant who is not `IN_PLAN` — because they already belong to a tranche or have already settled — is rejected with `ERR_PARTICIPANT_ALREADY_ASSIGNED`.

        Design: Corner/endpoints/participant_assignment_links_two_entities_or_refuses
        """
        fixtures.reset_clock(api)
        tranche, deferred_a, _retiree_a, _deferred_b = self._plan_pair(api)
        linked = fixtures.assign_participant(api, tranche["id"], deferred_a["id"])

        validate_error(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(deferred_a["id"]),
                administrator,
            ),
            ERR_PARTICIPANT_ALREADY_ASSIGNED,
        )

        after = fixtures.read_tranche(api, tranche["id"])
        assert after["assigned_participant_count"] == 1
        assert_version_unchanged(linked, after)


class TestQuoteSolicitation:
    """A carrier may hold only one live quote per tranche at a time."""

    def _quoting_tranche(self, api):
        authorized = fixtures.build_authorized_plan(
            api,
            participants=[
                fixtures.ParticipantSpec(
                    stated_monthly_benefit_cents=250000,
                    cohort=RETIREE,
                    credited_service_months=400,
                )
            ],
        )
        quoting = fixtures.build_quoting_tranche(
            api, authorized.plan_id, authorized.participants, RETIREE
        )
        insurer = fixtures.create_insurer(api, "Northwall Life Assurance", "AA", 4200, 500000000)
        return quoting.tranche_id, insurer

    def test_endpoint_second_quote_request_to_the_same_carrier_is_a_duplicate(
        self, api, fiduciary
    ):
        """A carrier already holding a REQUESTED quote cannot be solicited again, and an unknown carrier is a 404.

        A carrier that already holds a non-terminal quote on this tranche — one whose `quote_status` is `REQUESTED`, `SUBMITTED`, `SHORTLISTED`, `LOCKED`, or `BOUND` — may not be solicited a second time, and the duplicate is rejected with `ERR_DUPLICATE_QUOTE_REQUEST`.
        A created quote starts in `REQUESTED` with `requested_at` stamped from the logical clock, records its `tranche_id` and `insurer_id`, leaves `premium_cents`, `lock_days`, `quote_valid_days`, `submitted_at`, `expires_at`, `rating_at_submission`, `composite_score_bp`, and `decline_reason` null, and bumps the tranche's `version`.
        The same discipline extends to identifiers supplied in a request body or as a list filter rather than in the path. A quote request naming an `insurer_id` that does not exist fails with `ERR_INSURER_NOT_FOUND`; a tranche assignment naming a `participant_id` that does not exist fails with `ERR_PARTICIPANT_NOT_FOUND`.

        Design: Corner/endpoints/second_quote_request_to_the_same_insurer_is_rejected_until_the_first_is_terminal
        """
        fixtures.reset_clock(api)
        tranche_id, insurer = self._quoting_tranche(api)

        first = validate_success(
            api.create_quote(
                tranche_id, factories.quote_request_payload(insurer["id"]), fiduciary
            ),
            201,
        )
        assert_fields(
            first,
            quote_status="REQUESTED",
            tranche_id=tranche_id,
            insurer_id=insurer["id"],
            premium_cents=None,
            expires_at=None,
            rating_at_submission=None,
        )

        validate_error(
            api.create_quote(
                tranche_id, factories.quote_request_payload(insurer["id"]), fiduciary
            ),
            ERR_DUPLICATE_QUOTE_REQUEST,
        )
        validate_error(
            api.create_quote(
                tranche_id, factories.quote_request_payload(NON_EXISTENT_UUID), fiduciary
            ),
            ERR_INSURER_NOT_FOUND,
        )

        _rows, meta = validate_paginated(
            api.list_quotes(fiduciary, {"tranche_id": tranche_id})
        )
        assert meta["total_count"] == 1

    def test_endpoint_quote_request_is_admitted_again_once_the_first_is_terminal(
        self, api, fiduciary
    ):
        """After the carrier declines, a fresh solicitation of the same carrier is accepted.

        A `DECLINE` moves the quote `REQUESTED → DECLINED` instead and requires a non-empty `decline_reason`, whose absence is likewise rejected with `ERR_INVALID_REQUEST`; it records the reason and bumps the `version`.
        A carrier that already holds a non-terminal quote on this tranche — one whose `quote_status` is `REQUESTED`, `SUBMITTED`, `SHORTLISTED`, `LOCKED`, or `BOUND` — may not be solicited a second time, and the duplicate is rejected with `ERR_DUPLICATE_QUOTE_REQUEST`.

        Design: Corner/endpoints/second_quote_request_to_the_same_insurer_is_rejected_until_the_first_is_terminal
        """
        fixtures.reset_clock(api)
        tranche_id, insurer = self._quoting_tranche(api)
        first = fixtures.request_quote(api, tranche_id, insurer["id"])

        declined = get_success_data(
            api.post_quote_submission(
                first["id"],
                factories.quote_decline_payload(),
                make_insurer_rep_headers(insurer["id"]),
            )
        )
        assert declined["quote_status"] == "DECLINED"

        second = validate_success(
            api.create_quote(
                tranche_id, factories.quote_request_payload(insurer["id"]), fiduciary
            ),
            201,
        )
        assert second["id"] != first["id"]
        assert_fields(second, quote_status="REQUESTED", insurer_id=insurer["id"])

        rows, meta = validate_paginated(api.list_quotes(fiduciary, {"tranche_id": tranche_id}))
        assert meta["total_count"] == 2
        assert {row["quote_status"] for row in rows} == {"DECLINED", "REQUESTED"}


class TestSettlementEntryReads:
    """The ledger listing composes its filters and the single read agrees with it."""

    def _settled_window(self, api):
        plan = _lump_sum_authorized_plan(api)
        participant = _deferred_participant(api, plan["id"], 20000)
        window = _open_window(
            api,
            plan["id"],
            "2026-08-01T00:00:00Z",
            "2026-09-15T00:00:00Z",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        election = fixtures.election_for(api, window["id"], participant["id"])
        fixtures.elect(api, election["id"], participant["id"], "LUMP_SUM")
        fixtures.set_clock(api, "2026-09-15T00:00:00Z")
        fixtures.close_window(api, window["id"])
        settled = fixtures.settle_window(api, window["id"])
        return plan, participant, settled

    def test_endpoint_settlement_entry_filters_compose_across_plan_window_and_type(
        self, api, sponsor
    ):
        """One recognition entry answers both the plan and window filters and none answers the buyout type.

        Alongside the cascade, one settlement accounting entry is appended with an `entry_type` of `LUMP_SUM_RECOGNITION` and its `window_id` set. Its `pbo_settled_cents` is the sum of the paid participants' `accounting_liability_cents`, its `amount_cents` is `paid_lump_sum_total_cents` minus that `pbo_settled_cents`, and its `deferred_amount_cents` is 0 — a lump-sum disbursement is recognised immediately and nothing is held back in accumulated other comprehensive income.
        Which of the two cross-references is populated follows from the type: a `BUYOUT_RECOGNITION` entry carries a `tranche_id` and a null `window_id`, a `LUMP_SUM_RECOGNITION` entry carries a `window_id` and a null `tranche_id`, and the remaining three types carry neither.
        Its `amount_cents` is the charge recognised immediately in earnings, negative for a reversal, and every entry's `amount_cents` sums into the plan's `cumulative_settlement_charge_cents`.

        Design: Corner/endpoints/settlement_entry_list_filters_compose_and_the_single_read_matches
        """
        fixtures.reset_clock(api)
        plan, _participant, settled_window = self._settled_window(api)
        expected_pbo = constants.accounting_liability(20000, DEFERRED)
        expected_amount = settled_window["paid_lump_sum_total_cents"] - expected_pbo

        by_plan, plan_meta = validate_paginated(
            api.list_settlement_entries(sponsor, {"plan_id": plan["id"]})
        )
        assert plan_meta["total_count"] == 1
        entry = by_plan[0]
        assert_fields(
            entry,
            plan_id=plan["id"],
            entry_type="LUMP_SUM_RECOGNITION",
            window_id=settled_window["id"],
            tranche_id=None,
            pbo_settled_cents=expected_pbo,
            amount_cents=expected_amount,
            deferred_amount_cents=0,
        )
        assert entry["pbo_settled_cents"] == 2292000
        assert entry["amount_cents"] == 108000

        by_window, window_meta = validate_paginated(
            api.list_settlement_entries(sponsor, {"window_id": settled_window["id"]})
        )
        assert window_meta["total_count"] == 1
        assert by_window[0]["id"] == entry["id"]

        by_type, type_meta = validate_paginated(
            api.list_settlement_entries(
                sponsor, {"plan_id": plan["id"], "entry_type": "BUYOUT_RECOGNITION"}
            )
        )
        assert by_type == []
        assert type_meta["total_count"] == 0
        assert type_meta["has_more"] is False

        assert (
            fixtures.read_plan(api, plan["id"])["cumulative_settlement_charge_cents"]
            == expected_amount
        )

    def test_endpoint_settlement_entry_single_read_matches_the_listed_row(self, api, sponsor):
        """The single entry read returns the listed row unchanged, without a version, and an unknown id is a 404.

        The single exception is the settlement accounting entry. Settlement entries are append-only and are never mutated after they are written, so a `SettlementEntry` carries only `id` and `created_at`: it has neither `updated_at` nor `version`.
        The full set of not-found errors is `ERR_PLAN_NOT_FOUND`, `ERR_STRATEGY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_SETTLEMENT_ENTRY_NOT_FOUND`, each carrying HTTP 404.

        Design: Corner/endpoints/settlement_entry_list_filters_compose_and_the_single_read_matches
        """
        fixtures.reset_clock(api)
        plan, _participant, _settled_window = self._settled_window(api)
        rows, _meta = validate_paginated(
            api.list_settlement_entries(sponsor, {"plan_id": plan["id"]})
        )
        listed = rows[0]

        single = validate_success(api.get_settlement_entry(listed["id"], sponsor))

        assert single == listed
        assert_settlement_entry_shape(single)
        assert "updated_at" not in single
        assert "version" not in single

        validate_error(
            api.get_settlement_entry(NON_EXISTENT_UUID, sponsor),
            ERR_SETTLEMENT_ENTRY_NOT_FOUND,
        )
