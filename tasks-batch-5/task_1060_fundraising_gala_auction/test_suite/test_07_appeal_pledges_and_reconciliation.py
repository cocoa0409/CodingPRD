"""The challenge-match appeal, the pledge book and reconciliation runs."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_reconciliation_run,
    channel_amount,
    confirm_sponsor,
    finalize_run,
    prepare_run,
    read_event,
    read_paddle_raise,
    read_pledge,
    read_reconciliation_run,
    record_installment,
    record_paddle_raise,
    record_pledge,
    register_bidder,
    register_sponsor,
    set_clock,
    setup_draft_event,
    setup_finalized_invoice_scenario,
    setup_partially_fulfilled_pledge,
    setup_published_event,
    validate_error,
    validate_paginated,
    validate_success,
    BIDDER_SPECS,
    event_version,
    make_finance_headers,
)


def test_paddle_raise_match_drains_the_cap_then_yields_zero(api):
    """PRD §3.6: "The remaining cap is the event's `match_cap_cents` less its
    `match_awarded_cents`, floored at zero so it never goes negative. The raw
    match this gift would earn is the gift's `level_cents` multiplied by a match
    ratio of 1.0 — a dollar-for-dollar challenge — rounded half up to a whole
    cent. The gift's `match_cents` is then whichever is smaller of that raw
    match and the remaining cap, and that awarded amount is added to the event's
    `match_awarded_cents`."
    PRD §3.6: "Because gifts are consumed in `created_at` ascending order, the
    cap drains chronologically: early donors receive their full match, the gift
    that straddles the cap receives a partial match, and every gift after it
    receives `match_cents` of 0."

    Design: Corner/calculations/paddle_raise_match_drains_the_event_cap_then_yields_zero
    """
    env = setup_published_event(bidder_count=1, match_cap_cents=500_000)
    event_id = env["event"]["id"]
    guest_id = env["bidders"][0]["id"]

    first = record_paddle_raise(event_id, guest_id, 100_000)
    second = record_paddle_raise(event_id, guest_id, 450_000)
    third = record_paddle_raise(event_id, guest_id, 10_000)

    assert first["match_cents"] == 100_000, (
        f"The first gift matches in full, got {first['match_cents']}"
    )
    assert second["match_cents"] == 400_000, (
        f"The straddling gift takes only the remaining cap, got "
        f"{second['match_cents']}"
    )
    assert third["match_cents"] == 0, (
        f"Once the cap is drained later gifts match nothing, got "
        f"{third['match_cents']}"
    )
    assert read_event(event_id)["match_awarded_cents"] == 500_000
    assert read_paddle_raise(third["id"])["settlement_status"] == "UNSETTLED"


def test_pledge_lapse_before_grace_expires_is_rejected(api):
    """PRD §3.10: "A `FinanceOfficer` may mark a pledge in `PROMISED` or
    `PARTIALLY_FULFILLED` as `LAPSED`, but only once the grace window has run
    out: the clock must be strictly later than the pledge's `first_due_utc` plus
    30 days, and an early attempt is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pledge_lapse_before_grace_window_expires_is_rejected
    """
    event = setup_draft_event()
    guest = register_bidder(event["id"], **BIDDER_SPECS[0], payment_method_on_file=True)
    pledge = record_pledge(
        event["id"], guest["id"], first_due_utc="2026-08-01T00:00:00Z"
    )
    set_clock("2026-08-20T00:00:00Z")

    response = api.lapse_pledge(pledge["id"], TEST_USERS["finance_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = read_pledge(pledge["id"])
    assert stored["status"] == "PROMISED", (
        f"An early lapse leaves the pledge PROMISED, got {stored['status']}"
    )
    assert stored["received_amount_cents"] == 0


def test_reopen_returns_run_to_prepared_and_unfreezes_event(api):
    """PRD §3.9: "Reopening moves a `FINALIZED` run back to `PREPARED`, and is
    refused with `ERR_INVALID_STATE` when the run's event has already reached
    `CLOSED`."
    PRD §3.9: "Reopening clears `finalized_by_user_id` back to null, recomputes
    `expected_total_cents`, `collected_total_cents`, `variance_cents`,
    `is_material_variance` and `channel_breakdown` from current data under the
    run's stored `revenue_basis`, and lifts the frozen gate the finalized run
    imposed: the event's posture becomes `RESTRICTED` when the event's `status`
    is `SETTLING`, and `OPEN` otherwise."

    Design: Corner/state_machines/reconciliation_run_reopen_returns_run_to_prepared
    """
    env = setup_published_event(bidder_count=0)
    event_id = env["event"]["id"]

    run = prepare_run(event_id, user_id="fin-1")
    assert run["expected_total_cents"] == 0, (
        "An event with no revenue expects nothing"
    )
    assert run["is_material_variance"] is False, (
        "A zero variance is below the 5000-cent materiality floor"
    )

    finalized = finalize_run(run["id"], user_id="fin-2")
    assert finalized["finalized_by_user_id"] == "fin-2"
    assert read_event(event_id)["posture"] == "FROZEN"

    response = api.reopen_reconciliation_run(
        run["id"], make_finance_headers("fin-2")
    )
    reopened = validate_success(response, 200)

    assert reopened["status"] == "PREPARED", (
        f"Reopening returns the run to PREPARED, got {reopened['status']}"
    )
    assert reopened["finalized_by_user_id"] is None, (
        "Reopening clears finalized_by_user_id"
    )
    assert read_event(event_id)["posture"] == "OPEN", (
        "A PUBLISHED event un-freezes back to OPEN"
    )


def test_second_run_supersedes_the_prepared_one(api):
    """PRD §3.9: "The run is stamped with `prepared_by_user_id` from the acting
    `X-User-ID`, opens in `PREPARED` with `finalized_by_user_id` null, and any
    run of that event already in `PREPARED` is moved to the terminal
    `SUPERSEDED`, advancing that older run's `version`."

    Design: Corner/state_machines/creating_a_second_run_supersedes_the_prepared_one
    """
    event = setup_draft_event()
    first = prepare_run(event["id"], revenue_basis="BOOKED", user_id="fin-1")

    second = prepare_run(event["id"], revenue_basis="CASH_BASIS", user_id="fin-1")

    assert second["status"] == "PREPARED"
    assert second["prepared_by_user_id"] == "fin-1", (
        f"prepared_by_user_id records the acting operator, got "
        f"{second['prepared_by_user_id']}"
    )
    assert read_reconciliation_run(first["id"])["status"] == "SUPERSEDED", (
        "The older PREPARED run is superseded"
    )


def test_stale_expected_event_version_is_refused(api):
    """PRD §2.9: "The request that creates a run for an event must carry
    `expected_event_version`, a non-optional integer field holding the `version`
    of the gala event as the client last observed it. If that value does not
    equal the event's current `version`, the create is rejected with
    `ERR_STALE_EVENT_VERSION` (HTTP 412)."
    PRD §3.9: "Preparing a run advances the event's `version`."

    Design: Corner/cross_cutting_layers/stale_expected_event_version_on_run_create_returns_412
    """
    event = setup_draft_event()
    observed_version = event_version(event["id"])
    first = prepare_run(
        event["id"], user_id="fin-1", expected_event_version=observed_version
    )

    response = api.create_reconciliation_run(
        event["id"],
        {
            "expected_event_version": observed_version,
            "revenue_basis": "CASH_BASIS",
        },
        TEST_USERS["finance_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_EVENT_VERSION.value, 412)
    rows, meta = validate_paginated(
        api.list_reconciliation_runs(event["id"], TEST_USERS["finance_headers"])
    )
    assert meta["total_count"] == 1, (
        f"A refused create stores no run, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]
    assert read_reconciliation_run(first["id"])["status"] == "PREPARED"


def test_revenue_summary_reports_each_channel_separately(api):
    """PRD §3.9: "Separately from any run, an `EventOrganizer` or
    `FinanceOfficer` may pull a live per-channel snapshot of an event that
    reports `tickets_cents`, `auction_cents`, `paddle_cents`, both pledge
    readings side by side as `pledge_booked_cents` and `pledge_cash_cents`,
    `sponsorship_cents`, `gross_collected_cents` and `match_awarded_cents`,
    using the same channel filters described above."
    PRD §3.9: "The sponsorship channel sums `paid_amount_cents` over the event's
    sponsors whose `status` is `CONFIRMED`, so `PENDING` and `WITHDRAWN`
    sponsors contribute nothing."

    Design: Corner/endpoints/revenue_summary_reports_each_channel_separately
    """
    event = setup_draft_event()
    guest = register_bidder(event["id"], **BIDDER_SPECS[0], payment_method_on_file=True)
    sponsor = register_sponsor(event["id"])
    confirm_sponsor(sponsor["id"], 250_000)
    pledge = record_pledge(event["id"], guest["id"], total_amount_cents=300_000)
    record_installment(pledge["id"], 50_000)

    response = api.get_revenue_summary(event["id"], TEST_USERS["finance_headers"])
    summary = validate_success(response, 200)

    assert summary["tickets_cents"] == 0
    assert summary["auction_cents"] == 0
    assert summary["pledge_booked_cents"] == 300_000, (
        f"The accrual reading recognises the full promise, got "
        f"{summary['pledge_booked_cents']}"
    )
    assert summary["pledge_cash_cents"] == 50_000, (
        f"The cash reading counts only received cash, got "
        f"{summary['pledge_cash_cents']}"
    )
    assert summary["sponsorship_cents"] == 250_000
    assert summary["gross_collected_cents"] == 0


class TestPledgeRevenueBasis:
    """PRD §3.9's two pledge readings over one identical pledge row."""

    def test_booked_basis_recognises_the_full_promised_pledge(self, api):
        """PRD §3.9: "Under the `BOOKED` basis — the accrual view the board
        report uses — the pledge channel sums `total_amount_cents` over every
        pledge of the event whose `status` is `PROMISED`,
        `PARTIALLY_FULFILLED` or `FULFILLED`; pledges in `LAPSED` are excluded
        outright, and the full promised amount is recognized the night it is
        promised regardless of how much cash has arrived."
        PRD §3.9: "The run's `collected_total_cents` is the event's
        `gross_collected_cents` at run time, and `variance_cents` is
        `expected_total_cents` less `collected_total_cents` — a figure that may
        be negative."

        Design: Difficulty/dual_variant_calc/pledge_expected_revenue_booked_vs_cash_basis
        """
        env = setup_partially_fulfilled_pledge()

        response = api.create_reconciliation_run(
            env["event"]["id"],
            {
                "expected_event_version": event_version(env["event"]["id"]),
                "revenue_basis": "BOOKED",
            },
            TEST_USERS["finance_headers"],
        )
        run = validate_success(response, 201)

        assert_reconciliation_run(run)
        assert run["expected_total_cents"] == 300_000, (
            f"BOOKED recognises the whole 300000 promise, got "
            f"{run['expected_total_cents']}"
        )
        assert channel_amount(run, "PLEDGE") == 300_000
        assert run["variance_cents"] == 300_000, (
            "No cash has been collected, so the whole promise is variance"
        )
        assert env["pledge"]["status"] == "PARTIALLY_FULFILLED"

    def test_cash_basis_recognises_only_received_cash(self, api):
        """PRD §3.9: "Under the `CASH_BASIS` basis — the treasurer's bank
        tie-out — the pledge channel instead sums `received_amount_cents` over
        every pledge of the event in `PROMISED`, `PARTIALLY_FULFILLED`,
        `FULFILLED` or `LAPSED`; every pledge including the lapsed ones
        contributes, but only cash actually received counts."
        PRD §3.10: "Installments are recorded by a `FinanceOfficer` supplying an
        `amount_cents`, which is added to the pledge's `received_amount_cents`
        and advances the pledge's `version`."

        Design: Difficulty/dual_variant_calc/pledge_expected_revenue_booked_vs_cash_basis
        """
        env = setup_partially_fulfilled_pledge()
        assert env["pledge"]["received_amount_cents"] == 50_000

        response = api.create_reconciliation_run(
            env["event"]["id"],
            {
                "expected_event_version": event_version(env["event"]["id"]),
                "revenue_basis": "CASH_BASIS",
            },
            TEST_USERS["finance_headers"],
        )
        run = validate_success(response, 201)

        assert run["expected_total_cents"] == 50_000, (
            f"CASH_BASIS recognises only the 50000 received, got "
            f"{run['expected_total_cents']}"
        )
        assert channel_amount(run, "PLEDGE") == 50_000
        assert run["variance_cents"] == 50_000


class TestSegregationBeatsOpenInvoices:
    """PRD §2.5's ordering when a finalize violates both duties and hygiene."""

    def test_segregation_of_duties_beats_open_invoices_on_run_finalize(self, api):
        """PRD §2.5: "Segregation of duties on run finalization and payment
        void, else `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.5: "Absence of unpaid invoices on event close and run
        finalization, else `ERR_OPEN_INVOICES_REMAIN`."
        PRD §2.9: "The operator who prepared a reconciliation run — recorded as
        `prepared_by_user_id` — may not be the operator who finalizes it."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_open_invoices_on_run_finalize
        """
        env = setup_finalized_invoice_scenario()
        assert read_event(env["event"]["id"])["unpaid_invoice_count"] == 1
        run = prepare_run(env["event"]["id"], user_id="fin-1")

        response = api.finalize_reconciliation_run(
            run["id"], {}, make_finance_headers("fin-1")
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    def test_run_stays_prepared_after_segregation_of_duties_rejection(self, api):
        """PRD §3.9: "On success `finalized_by_user_id` is set to the acting
        user, the run moves `PREPARED → FINALIZED`, the event recomputes its
        posture — which becomes `FROZEN` — and the run's `version` advances."
        PRD §2.9: "Segregation of duties applies to two `FinanceOfficer`
        operations, and in both cases the comparison is on `X-User-ID`, not on
        the role."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_open_invoices_on_run_finalize
        """
        env = setup_finalized_invoice_scenario()
        run = prepare_run(env["event"]["id"], user_id="fin-1")

        api.finalize_reconciliation_run(run["id"], {}, make_finance_headers("fin-1"))

        stored = read_reconciliation_run(run["id"])
        assert stored["status"] == "PREPARED", (
            f"A refused finalize leaves the run PREPARED, got {stored['status']}"
        )
        assert stored["finalized_by_user_id"] is None, (
            "A refused finalize stamps no finalizing operator"
        )
        assert read_event(env["event"]["id"])["posture"] != "FROZEN", (
            "A refused finalize does not freeze the event"
        )
