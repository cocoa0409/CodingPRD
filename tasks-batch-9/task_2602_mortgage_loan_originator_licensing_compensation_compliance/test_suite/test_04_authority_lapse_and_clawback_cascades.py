"""Two five-hop cascades, each hop caused by the mutation the previous hop made.

The nightly sweep expiring a licence reaches a sponsorship, a licence, a loan,
an investigation and a counter. An early payoff reaches a loan, a ledger line,
an originator's balances, its supervision status and an unrelated pricing
exception still in flight.
"""
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import (
    close_loan,
    get_license,
    get_loan,
    get_originator,
    get_pricing_exception,
    list_audit_events,
    list_investigations,
    lock_loan,
    payoff_loan,
    request_pricing_exception,
    run_reconciliation,
    run_sweep,
    set_clock,
    setup_authorized_originator,
    setup_originator_with_plan,
    sole_record_for_loan,
    take_loan,
)

# --- local scenario builders ------------------------------------------------


def _sole_event_of_type(events, event_type):
    """The single audit entry of one type, so the ordering assertion reads cleanly."""
    matches = [event for event in events if event["event_type"] == event_type]
    assert len(matches) == 1, f"expected exactly one {event_type} entry, found {len(matches)}"
    return matches[0]


def _build_licence_about_to_expire(api):
    """An authorised CA originator holding one open application, licence expiring 2026-09-01."""
    context = setup_authorized_originator(
        api,
        license_overrides={
            "expiration_date": "2026-09-01T00:00:00Z",
            "renewal_window_opens_at": "2026-07-01T00:00:00Z",
        },
    )
    set_clock(api, "2026-08-05T00:00:00Z")
    context["loan"] = take_loan(
        api,
        context["originator"]["id"],
        state_code=context["state_code"],
        requested_amount_cents=18_000_000,
        par_rate_bps=645,
    )
    return context


def _build_two_dual_paid_reconciled_loans(api):
    """Two dual-paid loans reconciled at 400,000 cents each, plus a third still locked.

    The third loan carries a SUBMITTED pricing exception, which is the unrelated
    row the last hop of the payoff cascade reaches.
    """
    context = setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 200,
            "min_fee_cents": 100_000,
            "max_fee_cents": 900_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
    )
    originator_id = context["originator"]["id"]
    state_code = context["state_code"]
    loans = []
    scores = []
    for funded_at, note_rate_bps in (
        ("2026-09-01T00:00:00Z", 710),
        ("2026-09-05T00:00:00Z", 710),
    ):
        loan = take_loan(
            api,
            originator_id,
            state_code=state_code,
            requested_amount_cents=20_000_000,
            par_rate_bps=650,
        )
        lock_loan(
            api,
            loan["id"],
            originator_id,
            note_rate_bps=note_rate_bps,
            locked_amount_cents=20_000_000,
        )
        loans.append(
            close_loan(
                api,
                loan["id"],
                funded_amount_cents=20_000_000,
                funded_at=funded_at,
                lender_paid_comp_cents=400_000,
                borrower_paid_comp_cents=100_000,
            )
        )
        scores.append(get_originator(api, originator_id))
    context["first_loan"], context["second_loan"] = loans
    context["originator_after_first_close"] = scores[0]
    context["originator_after_second_close"] = scores[1]

    context["reconciliation"] = run_reconciliation(api, originator_id)

    third = take_loan(
        api,
        originator_id,
        state_code=state_code,
        requested_amount_cents=20_000_000,
        par_rate_bps=650,
    )
    context["third_loan"] = lock_loan(
        api, third["id"], originator_id, note_rate_bps=655, locked_amount_cents=20_000_000
    )
    context["exception"] = request_pricing_exception(
        api,
        third["id"],
        originator_id,
        requested_rate_bps=655,
        concession_cents=100_000,
        reason_code="SERVICE_ISSUE",
    )
    return context


# --- Sweep expiry: sponsorship -> licence -> loan -> investigation -> counter


def test_sweep_expiry_closes_the_sponsorship_and_empties_the_authority_set(api):
    """PRD §3.9: "First, every licence whose `status` is `ACTIVE` or `RENEWAL_PENDING` and whose
    `expiration_date` is at or before the logical clock instant moves to `EXPIRED` and runs the
    full five-hop authority-lapse cascade of §3.1"
    PRD §3.1: "1. The licence's `ACTIVE` sponsorship moves to `RELINQUISHED` with
    `relinquished_at` stamped from the logical clock."
    PRD §3.1: "2. Because that sponsorship closed, the licence's
    `active_sponsoring_institution_code` and `active_sponsorship_effective_at` go null and the
    originator's `authorized_state_codes` is recomputed, losing that `state_code`."
    PRD §3.9: "`swept_at` gives the instant it ran"

    Design: Difficulty/transitive_cascade/license_expiry_sweep_five_hop_authority_lapse_cascade
    """
    context = _build_licence_about_to_expire(api)
    licence_id = context["license"]["id"]
    sponsorship_id = context["sponsorship"]["id"]

    before = get_originator(api, context["originator"]["id"])
    assert before["authorized_state_codes"] == [TEST_DEFAULTS["STATE_CODE"]], (
        "the originator is authorised in CA right up to the sweep"
    )

    set_clock(api, "2026-09-02T00:00:00Z")
    report = run_sweep(api)

    assert report["swept_at"].startswith("2026-09-02T00:00:00"), (
        f"the sweep reports the clock instant it ran at: {report['swept_at']}"
    )
    assert report["expired_license_ids"] == [licence_id]
    assert report["relinquished_sponsorship_ids"] == [sponsorship_id]

    licence = get_license(api, licence_id)
    assert licence["status"] == "EXPIRED"
    assert licence["active_sponsoring_institution_code"] is None
    assert licence["active_sponsorship_effective_at"] is None

    originator = get_originator(api, context["originator"]["id"])
    assert originator["authorized_state_codes"] == [], (
        "hop 2 recomputes the authority set, which loses its only state"
    )


def test_sweep_expiry_suspends_the_open_loan_and_opens_one_cascade_investigation(api):
    """PRD §3.1: "3. Because the state dropped out of `authorized_state_codes`, every loan
    application belonging to that originator, carrying that `state_code`, and sitting in
    `status` `TAKEN` or `LOCKED` has its `authority_flag` set to `SUSPENDED`."
    PRD §3.1: "4. Because those loans were suspended, one unlicensed-activity investigation is
    opened for each of them, with `opened_by` set to `CASCADE`, `trigger_reason` forced to
    `AUTHORITY_LAPSE`, and `status` `OPEN`."
    PRD §3.1: "5. Because those investigations were created, the originator's
    `open_investigation_count` is recomputed."
    PRD §3.1: "The audit trail records this chain as one `LICENSE_STATUS_CHANGED` entry followed
    by one `INVESTIGATION_OPENED` entry per created investigation, the investigation entries
    ordered by their suspended loans' `funded_at` ascending and then `created_at` ascending."

    Design: Difficulty/transitive_cascade/license_expiry_sweep_five_hop_authority_lapse_cascade
    """
    context = _build_licence_about_to_expire(api)
    loan_id = context["loan"]["id"]
    originator_id = context["originator"]["id"]

    set_clock(api, "2026-09-02T00:00:00Z")
    report = run_sweep(api)

    assert report["suspended_loan_ids"] == [loan_id]
    assert len(report["opened_investigation_ids"]) == 1

    loan = get_loan(api, loan_id)
    assert loan["authority_flag"] == "SUSPENDED"
    assert loan["status"] == "TAKEN", (
        "the cascade rewrites the authority record, never the origination dimension"
    )

    investigations = list_investigations(api, loan_application_id=loan_id)
    assert len(investigations) == 1, f"exactly one cascade investigation: {investigations}"
    investigation = investigations[0]
    assert investigation["id"] == report["opened_investigation_ids"][0]
    assert investigation["status"] == "OPEN"
    assert investigation["opened_by"] == "CASCADE"
    assert investigation["trigger_reason"] == "AUTHORITY_LAPSE"
    assert investigation["originator_id"] == originator_id
    assert investigation["restitution_cents"] == 0

    originator = get_originator(api, originator_id)
    assert originator["open_investigation_count"] == 1

    events = list_audit_events(api, limit=100)
    licence_event = [
        event
        for event in events
        if event["event_type"] == "LICENSE_STATUS_CHANGED"
        and event["subject_ref"] == context["license"]["id"]
    ]
    opened = _sole_event_of_type(events, "INVESTIGATION_OPENED")
    assert licence_event, "the expiry itself is recorded as a licence status change"
    assert licence_event[-1]["sequence_no"] < opened["sequence_no"], (
        "the licence status change is appended before the investigation it caused"
    )


def test_a_second_sweep_finds_nothing_left_to_expire(api):
    """PRD §3.9: "A sweep that finds nothing to do still succeeds, returning empty lists."
    PRD §3.9: "which at all times equals the number of that originator's investigations whose
    `status` is `OPEN` or `SUBSTANTIATED`"

    Design: Difficulty/transitive_cascade/license_expiry_sweep_five_hop_authority_lapse_cascade
    """
    context = _build_licence_about_to_expire(api)
    loan_id = context["loan"]["id"]

    set_clock(api, "2026-09-02T00:00:00Z")
    run_sweep(api)
    second = run_sweep(api)

    assert second["expired_license_ids"] == [], (
        "the licence already reads EXPIRED, so the first pass has nothing to match"
    )
    assert second["relinquished_sponsorship_ids"] == []
    assert second["suspended_loan_ids"] == []
    assert second["opened_investigation_ids"] == []

    assert len(list_investigations(api, loan_application_id=loan_id)) == 1, (
        "the cascade must not open a duplicate investigation on the same loan"
    )
    originator = get_originator(api, context["originator"]["id"])
    assert originator["open_investigation_count"] == 1
    assert get_license(api, context["license"]["id"])["status"] == "EXPIRED"


# --- Payoff clawback: loan -> line -> balances -> supervision -> exception ---


def test_thirty_day_payoff_recaptures_the_whole_final_line(api):
    """PRD §3.7: "The amount recaptured, `clawback_cents`, is the line's `paid_cents` multiplied
    by `recapture_pct`, divided by one hundred, rounded half up to whole cents."
    PRD §3.7: "1. Because the loan's `status` became `PAID_OFF`, its `compensation_status`
    advances `RECONCILED → CLAWED_BACK`."
    PRD §3.7: "2. Because the loan's compensation dimension moved, the loan's `FINAL` ledger
    line advances `RECONCILED → CLAWED_BACK`, writing `days_held`, `recapture_pct` and
    `clawback_cents` onto the line. `CLAWED_BACK` is the ledger line's terminal state."
    PRD §3.7: "3. Because the line now carries a `clawback_cents`, the originator's
    `lifetime_clawed_back_cents` and `net_compensation_cents` are recomputed from it, so that
    `net_compensation_cents` remains exactly `lifetime_accrued_cents` less
    `lifetime_clawed_back_cents` with zero drift."

    Design: Difficulty/transitive_cascade/early_payoff_five_hop_clawback_and_monitoring_cascade
    """
    context = _build_two_dual_paid_reconciled_loans(api)
    first_loan_id = context["first_loan"]["id"]
    originator_id = context["originator"]["id"]

    assert context["reconciliation"]["reconciled_count"] == 2
    assert context["reconciliation"]["total_final_cents"] == 800_000

    set_clock(api, "2026-10-01T00:00:00Z")
    paid_off = payoff_loan(api, first_loan_id, "2026-10-01T00:00:00Z")

    assert paid_off["status"] == "PAID_OFF"
    assert paid_off["compensation_status"] == "CLAWED_BACK"

    record = sole_record_for_loan(api, first_loan_id)
    assert record["status"] == "CLAWED_BACK"
    assert record["days_held"] == 30, (
        "2026-09-01 to 2026-10-01 is 30 whole days: got {}".format(record["days_held"])
    )
    assert record["recapture_pct"] == 100, "thirty days is inside the ninety-day window"
    assert record["paid_cents"] == 400_000
    assert record["clawback_cents"] == 400_000

    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 800_000
    assert originator["lifetime_clawed_back_cents"] == 400_000
    assert originator["net_compensation_cents"] == 400_000


def test_the_clawback_escalates_supervision_on_one_assembled_sum(api):
    """PRD §3.7: "4. Because the ledger moved, the originator's `exposure_score` is recomputed,
    and `monitoring_status` flips to `ELEVATED` as soon as that score reaches sixty."
    PRD §3.7: "Those four terms are weighted and added: the dual-compensation ratio at
    thirty-five hundredths, the capped average spread at twenty-five hundredths, the exception
    rate at fifteen hundredths, and the capped clawback ratio at twenty-five hundredths."
    PRD §3.7: "**One** rounding half up is applied to the fully assembled weighted sum;
    rounding the four terms individually and then adding them is forbidden and yields a
    different score."

    Design: Difficulty/transitive_cascade/early_payoff_five_hop_clawback_and_monitoring_cascade
    """
    context = _build_two_dual_paid_reconciled_loans(api)

    assert context["originator_after_first_close"]["exposure_score"] == 50, (
        "one dual-paid loan sixty basis points above par scores 0.35*100 + 0.25*60 = 50"
    )
    assert context["originator_after_first_close"]["monitoring_status"] == "STANDARD"
    assert context["originator_after_second_close"]["exposure_score"] == 50, (
        "a second identical loan moves neither ratio nor the average spread"
    )
    assert context["originator_after_second_close"]["monitoring_status"] == "STANDARD"
    assert context["originator_after_second_close"]["lifetime_accrued_cents"] == 800_000

    set_clock(api, "2026-10-01T00:00:00Z")
    payoff_loan(api, context["first_loan"]["id"], "2026-10-01T00:00:00Z")

    originator = get_originator(api, context["originator"]["id"])
    assert originator["exposure_score"] == 63, (
        "0.35*100 + 0.25*60 + 0.15*0 + 0.25*50 is 62.5, and the assembled sum rounds half up "
        f"once to 63: got {originator['exposure_score']}"
    )
    assert originator["monitoring_status"] == "ELEVATED"


def test_escalation_raises_the_bar_on_an_unrelated_submitted_exception(api):
    """PRD §3.7: "5. Because supervision escalated, **every** pricing exception whose `status`
    is `SUBMITTED` and whose loan belongs to this same originator has its
    `requires_second_approval` set to true — retroactively raising the approval bar on work
    already in flight. This hop fires only when hop 4 actually changed `monitoring_status`."
    PRD §3.7: "The audit trail records a `COMP_CLAWED_BACK` entry, followed by a
    `MONITORING_ESCALATED` entry when hop 4 changed `monitoring_status`."

    Design: Difficulty/transitive_cascade/early_payoff_five_hop_clawback_and_monitoring_cascade
    """
    context = _build_two_dual_paid_reconciled_loans(api)
    assert context["exception"]["requires_second_approval"] is False, (
        "the exception was filed while the originator still read STANDARD"
    )

    set_clock(api, "2026-10-01T00:00:00Z")
    payoff_loan(api, context["first_loan"]["id"], "2026-10-01T00:00:00Z")

    exception = get_pricing_exception(api, context["exception"]["id"])
    assert exception["requires_second_approval"] is True, (
        "the last hop reaches a SUBMITTED exception on an entirely different loan"
    )
    assert exception["status"] == "SUBMITTED", "the exception itself is not decided by the cascade"
    assert exception["comp_impact_cents"] == 0

    untouched = get_loan(api, context["second_loan"]["id"])
    assert untouched["status"] == "CLOSED", "the second loan was never paid off"
    assert untouched["compensation_status"] == "RECONCILED"
    assert sole_record_for_loan(api, untouched["id"])["clawback_cents"] == 0

    events = list_audit_events(api, limit=100)
    clawed_back = _sole_event_of_type(events, "COMP_CLAWED_BACK")
    escalated = _sole_event_of_type(events, "MONITORING_ESCALATED")
    assert clawed_back["sequence_no"] < escalated["sequence_no"], (
        "the clawback entry is appended before the escalation it caused"
    )
