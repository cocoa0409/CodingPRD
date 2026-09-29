"""State machines: initial states, declared transitions, terminal lockdown and
the clock-driven legs of the agreement, report, window, invoice, blackout and
renewal dimensions.

Every test builds its own state from an empty database through PRD-declared
endpoints only.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    agreement_version,
    assert_agreement,
    assert_blackout_rule,
    assert_marketing_commitment,
    clock_payload,
    commitment_of_type,
    create_agreement_payload,
    create_renewal_analysis_payload,
    create_subscriber_report_payload,
    draft_agreement,
    fetch_agreement,
    fetch_blackout_rule,
    fetch_distributor,
    fetch_invoice,
    fetch_report,
    fetch_title,
    fetch_window,
    file_report,
    make_affiliate_sales_exec_headers,
    make_distributor_liaison_headers,
    make_network_admin_headers,
    make_revenue_accountant_headers,
    make_rights_administrator_headers,
    read_clock,
    register_distributor,
    schedule_blackout,
    setup_accepted_report,
    setup_cleared_window,
    setup_draft_agreement,
    setup_executed_agreement,
    setup_issued_invoice,
    setup_negotiating_agreement,
    start_renewal_analysis,
    submit_agreement_for_negotiation,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_network_admin_headers()
SALES = make_affiliate_sales_exec_headers()
ACCOUNTANT = make_revenue_accountant_headers()
RIGHTS = make_rights_administrator_headers()

# Flat, non-escalating commercial terms whose derived rate is the base fee.
FLAT_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}

MERIDIAN = {"legal_name": "Meridian Broadband", "total_subscribers": 1_500_000}

CLIFFSIDE = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
}

REPORT_130K = {
    "period_month": "2026-06",
    "reported_subscribers": 130_000,
    "reported_tier": "BASIC",
}


def _instant_is(value, expected_instant: str) -> bool:
    """Compare a returned instant against a whole-second UTC instant, tolerating
    the three fractional digits of PRD §2.4."""
    return isinstance(value, str) and value.startswith(expected_instant.rstrip("Z"))


def test_agreement_initial_states_are_draft_and_not_due(api):
    """PRD §3.2: "A fresh draft is stamped `lifecycle_status` `DRAFT`,
    `renewal_status` `NOT_DUE`, `negotiation_round` 0,
    `penetration_compliance_status` `UNKNOWN`, `penetration_breach_count` 0,
    `consecutive_compliant_periods` 0, `recognized_revenue_cents` 0 and `version`
    1, and both rate fields are stamped immediately from the terms as described in
    §3.3."
    PRD §3.3: "If there is no `ACTIVE` clause, or the `ACTIVE` clause's
    `benchmark_status` is `NOT_EVALUATED` or `NO_COMPARABLE`, the effective rate
    equals the escalated rate and `mfn_capped` is false."
    PRD §3.2: "On success the server stamps `executed_at` with the current logical
    instant, re-stamps `escalated_rate_cents_per_sub` and
    `effective_rate_cents_per_sub`, increments the operator's
    `executed_agreement_count` by one, and opens the network's marketing
    obligations: when `launch_fee_cents` is positive a commitment line of type
    `LAUNCH_FEE` is created with `committed_cents` equal to `launch_fee_cents` and
    a `performance_deadline` 180 days after `executed_at`, and when
    `marketing_commitment_cents` is positive a second line of type
    `MARKETING_SUPPORT` is created with `committed_cents` equal to
    `marketing_commitment_cents` and a `performance_deadline` equal to
    `term_end_date`."
    PRD §3.1: "`executed_agreement_count` is the number of that operator's
    agreements whose `lifecycle_status` is `EXECUTED` or `SUSPENDED`."

    Design: Corner/state_machines/agreement_initial_states_are_draft_and_not_due
    """
    distributor = register_distributor(**MERIDIAN)

    data = validate_success(
        api.create_agreement(
            create_agreement_payload(distributor["id"], contract_code="MB-INIT", **FLAT_TERMS),
            SALES,
        ),
        201,
    )

    assert data["lifecycle_status"] == "DRAFT", (
        f"a fresh draft opens on the lifecycle dimension at DRAFT, got {data['lifecycle_status']}"
    )
    assert data["renewal_status"] == "NOT_DUE", (
        f"a fresh draft opens on the renewal dimension at NOT_DUE, got {data['renewal_status']}"
    )
    assert data["penetration_compliance_status"] == "UNKNOWN", (
        "penetration compliance opens UNKNOWN, got "
        f"{data['penetration_compliance_status']}"
    )
    assert data["negotiation_round"] == 0, (
        f"negotiation_round opens at 0, got {data['negotiation_round']}"
    )
    assert data["penetration_breach_count"] == 0, (
        f"penetration_breach_count opens at 0, got {data['penetration_breach_count']}"
    )
    assert data["consecutive_compliant_periods"] == 0, (
        f"consecutive_compliant_periods opens at 0, got {data['consecutive_compliant_periods']}"
    )
    assert data["recognized_revenue_cents"] == 0, (
        f"recognized_revenue_cents opens at 0, got {data['recognized_revenue_cents']}"
    )
    assert data["version"] == 1, f"a created agreement carries version 1, got {data['version']}"
    assert data["mfn_capped"] is False, (
        f"with no MFN clause attached mfn_capped is false, got {data['mfn_capped']}"
    )
    assert data["executed_at"] is None, (
        f"executed_at is stamped only by execution, got {data['executed_at']}"
    )
    assert_agreement(data)

    operator = fetch_distributor(distributor["id"])
    assert operator["executed_agreement_count"] == 0, (
        "a DRAFT agreement is neither EXECUTED nor SUSPENDED, so the operator's "
        f"executed_agreement_count stays 0, got {operator['executed_agreement_count']}"
    )


def test_agreement_execute_spawns_launch_fee_and_marketing_commitments(api):
    """PRD §3.2: "On success the server stamps `executed_at` with the current
    logical instant, re-stamps `escalated_rate_cents_per_sub` and
    `effective_rate_cents_per_sub`, increments the operator's
    `executed_agreement_count` by one, and opens the network's marketing
    obligations: when `launch_fee_cents` is positive a commitment line of type
    `LAUNCH_FEE` is created with `committed_cents` equal to `launch_fee_cents` and
    a `performance_deadline` 180 days after `executed_at`, and when
    `marketing_commitment_cents` is positive a second line of type
    `MARKETING_SUPPORT` is created with `committed_cents` equal to
    `marketing_commitment_cents` and a `performance_deadline` equal to
    `term_end_date`."
    PRD §3.2: "Both lines open in `OPEN` status."
    PRD §3.8: "A new line opens `OPEN` with `earned_cents`,
    `earned_unbilled_cents`, `billed_cents` and `forfeited_cents` all zero,
    `remaining_cents` equal to `committed_cents`, and `version` 1."
    PRD §2.5: "At startup that value is exactly `2026-08-01T00:00:00Z`, and the
    server never falls back to real wall-clock time for any decision: contract
    expiry, window activation, blackout expiry, holdback measurement, interest
    accrual, commitment forfeiture, write-off ageing and renewal-window tests all
    read `current_utc`."

    Design: Corner/state_machines/agreement_execute_spawns_launch_fee_and_marketing_commitments
    """
    distributor = register_distributor(**MERIDIAN)
    agreement = draft_agreement(
        distributor["id"],
        contract_code="MB-LAUNCH",
        launch_fee_cents=1_000_000,
        marketing_commitment_cents=4_000_000,
        **FLAT_TERMS,
    )
    submit_agreement_for_negotiation(agreement["id"])

    data = validate_success(
        api.agreement_lifecycle(agreement["id"], {"action": "EXECUTE"}, SALES)
    )

    assert data["lifecycle_status"] == "EXECUTED", (
        f"EXECUTE moves NEGOTIATING to EXECUTED, got {data['lifecycle_status']}"
    )
    assert _instant_is(data["executed_at"], "2026-08-01T00:00:00"), (
        "executed_at is stamped with the current logical instant, which is the "
        f"startup clock 2026-08-01T00:00:00Z, got {data['executed_at']}"
    )
    assert data["effective_rate_cents_per_sub"] == pytest.approx(40.0000, abs=0.01), (
        "a zero escalator leaves the effective rate at the base fee, got "
        f"{data['effective_rate_cents_per_sub']}"
    )

    _rows, meta = validate_paginated(
        api.list_marketing_commitments(
            SALES, params={"agreement_id": agreement["id"], "limit": 10}
        )
    )
    assert meta["total_count"] == 2, (
        "execution opens exactly two commitment lines without any client call, got "
        f"total_count {meta['total_count']}"
    )

    launch = commitment_of_type(agreement["id"], "LAUNCH_FEE")
    assert launch["committed_cents"] == 1_000_000, (
        f"the LAUNCH_FEE line carries launch_fee_cents, got {launch['committed_cents']}"
    )
    assert _instant_is(launch["performance_deadline"], "2027-01-28T00:00:00"), (
        "the LAUNCH_FEE deadline is 180 days after executed_at, got "
        f"{launch['performance_deadline']}"
    )
    assert launch["status"] == "OPEN", f"the LAUNCH_FEE line opens OPEN, got {launch['status']}"
    assert launch["earned_cents"] == 0, f"earned_cents opens at 0, got {launch['earned_cents']}"
    assert launch["remaining_cents"] == 1_000_000, (
        f"remaining_cents opens equal to committed_cents, got {launch['remaining_cents']}"
    )
    assert_marketing_commitment(launch)

    support = commitment_of_type(agreement["id"], "MARKETING_SUPPORT")
    assert support["committed_cents"] == 4_000_000, (
        "the MARKETING_SUPPORT line carries marketing_commitment_cents, got "
        f"{support['committed_cents']}"
    )
    assert _instant_is(support["performance_deadline"], "2028-12-31T00:00:00"), (
        "the MARKETING_SUPPORT deadline equals the agreement's term_end_date, got "
        f"{support['performance_deadline']}"
    )
    assert support["remaining_cents"] == 4_000_000, (
        f"remaining_cents opens equal to committed_cents, got {support['remaining_cents']}"
    )
    assert_marketing_commitment(support)

    operator = fetch_distributor(distributor["id"])
    assert operator["executed_agreement_count"] == 1, (
        "execution increments the operator's executed_agreement_count by one, got "
        f"{operator['executed_agreement_count']}"
    )


def test_execute_directly_from_draft_is_not_a_declared_transition(api):
    """PRD §3.2: "Execution moves `NEGOTIATING → EXECUTED` and is the heaviest
    transition in the lifecycle."
    PRD §3.2: "An action that is not a declared transition out of the current
    `lifecycle_status` is rejected with `ERR_INVALID_AGREEMENT_STATE`; an action
    that is not a declared transition out of the current `renewal_status` is
    rejected with `ERR_INVALID_RENEWAL_STATE`."
    PRD §2.8: "**The first rule that fails decides the response, and no side
    effect of the requested operation fires.**"

    Design: Corner/state_machines/execute_directly_from_draft_is_not_a_declared_transition
    """
    distributor, agreement = setup_draft_agreement(MERIDIAN, FLAT_TERMS)

    validate_error(
        api.agreement_lifecycle(agreement["id"], {"action": "EXECUTE"}, SALES),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE,
        409,
    )

    after = fetch_agreement(agreement["id"])
    assert after["lifecycle_status"] == "DRAFT", (
        f"the rejected EXECUTE leaves the agreement in DRAFT, got {after['lifecycle_status']}"
    )
    assert after["executed_at"] is None, (
        f"no side effect fires, so executed_at stays null, got {after['executed_at']}"
    )
    assert after["version"] == 1, (
        f"a rejected action applies no mutation, so version stays 1, got {after['version']}"
    )

    operator = fetch_distributor(distributor["id"])
    assert operator["executed_agreement_count"] == 0, (
        "the operator's executed_agreement_count is untouched, got "
        f"{operator['executed_agreement_count']}"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "EXECUTE"},
        {"action": "SUSPEND", "suspension_reason": "MANUAL_SUSPENSION"},
        {"action": "REINSTATE"},
        {"action": "TERMINATE"},
    ],
    ids=["execute", "suspend", "reinstate", "terminate_again"],
)
def test_terminated_agreement_rejects_every_further_lifecycle_action(api, payload):
    """PRD §3.2: "`lifecycle_status` runs through `DRAFT`, `NEGOTIATING`,
    `EXECUTED`, `SUSPENDED` and terminally `EXPIRED` or `TERMINATED`."
    PRD §3.2: "An action that is not a declared transition out of the current
    `lifecycle_status` is rejected with `ERR_INVALID_AGREEMENT_STATE`; an action
    that is not a declared transition out of the current `renewal_status` is
    rejected with `ERR_INVALID_RENEWAL_STATE`."
    PRD §3.2: "Terminating from `NEGOTIATING` needs nothing beyond the state
    itself, and forces `renewal_status` to `LAPSED` when it stood at
    `RENEWAL_ANALYSIS` or `RENEWAL_OFFERED`."
    PRD §2.8: "**The first rule that fails decides the response, and no side
    effect of the requested operation fires.**"

    Design: Corner/state_machines/terminated_agreement_rejects_every_further_lifecycle_action
    """
    _distributor, agreement = setup_negotiating_agreement(MERIDIAN, FLAT_TERMS)
    dead = validate_success(
        api.agreement_lifecycle(agreement["id"], {"action": "TERMINATE"}, SALES)
    )
    assert dead["lifecycle_status"] == "TERMINATED", (
        f"TERMINATE from NEGOTIATING reaches TERMINATED, got {dead['lifecycle_status']}"
    )
    dead_version = dead["version"]

    validate_error(
        api.agreement_lifecycle(agreement["id"], payload, SALES),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE,
        409,
    )

    after = fetch_agreement(agreement["id"])
    assert after["lifecycle_status"] == "TERMINATED", (
        f"TERMINATED is terminal, got {after['lifecycle_status']}"
    )
    assert after["version"] == dead_version, (
        f"a rejected {payload['action']} applies no mutation, so version stays "
        f"{dead_version}, got {after['version']}"
    )


def test_execute_requires_penetration_floor_that_binds_a_subscriber(api):
    """PRD §3.2: "It requires the operator to be strictly `ACTIVE` — an operator
    on `CREDIT_HOLD` cannot have a new agreement executed, and the rejection is
    `ERR_DISTRIBUTOR_CREDIT_HOLD` — that the current logical instant lies at or
    after `term_start_date` and strictly before `term_end_date`, and that the
    penetration floor actually binds at least one subscriber:
    `penetration_floor_pct` multiplied by the operator's `total_subscribers` must
    be at least 1, or the request is refused with
    `ERR_PENETRATION_FLOOR_UNENFORCEABLE`."
    PRD §3.1: "Only a `NetworkAdmin` may adjust an operator's `total_subscribers`
    or `credit_limit_cents` after registration, and either adjustment bumps the
    operator's `version` by one."

    Design: Corner/state_machines/execute_requires_penetration_floor_that_binds_a_subscriber
    """
    distributor = register_distributor(
        legal_name="Pinhole Cable",
        distributor_type="TELCO",
        rate_card_class="CLASS_C",
        total_subscribers=1,
    )
    agreement = draft_agreement(distributor["id"], contract_code="PH-1", **FLAT_TERMS)
    submit_agreement_for_negotiation(agreement["id"])

    validate_error(
        api.agreement_lifecycle(agreement["id"], {"action": "EXECUTE"}, SALES),
        ApiErrorId.ERR_PENETRATION_FLOOR_UNENFORCEABLE,
        422,
    )
    blocked = fetch_agreement(agreement["id"])
    assert blocked["lifecycle_status"] == "NEGOTIATING", (
        "0.50 of a single subscriber binds nobody, so the agreement stays "
        f"NEGOTIATING, got {blocked['lifecycle_status']}"
    )

    grown = validate_success(
        api.patch_distributor(distributor["id"], {"total_subscribers": 2}, ADMIN)
    )
    assert grown["total_subscribers"] == 2, (
        f"the NetworkAdmin adjustment lands, got {grown['total_subscribers']}"
    )

    executed = validate_success(
        api.agreement_lifecycle(agreement["id"], {"action": "EXECUTE"}, SALES)
    )
    assert executed["lifecycle_status"] == "EXECUTED", (
        "0.50 of two subscribers binds one, so the identical EXECUTE now succeeds, "
        f"got {executed['lifecycle_status']}"
    )

    operator = fetch_distributor(distributor["id"])
    assert operator["executed_agreement_count"] == 1, (
        "execution increments executed_agreement_count by one, got "
        f"{operator['executed_agreement_count']}"
    )


def test_dispute_then_restatement_supersedes_the_original_report(api):
    """PRD §3.4: "Disputing a report moves it `SUBMITTED → DISPUTED`, and is
    admissible while the owning agreement's `lifecycle_status` is `EXECUTED` or
    `SUSPENDED`."
    PRD §3.4: "A dispute leaves `license_fee_due_cents` at 0 while retaining
    `provisional_fee_cents` for accrual reporting."
    PRD §3.4: "Requesting a restatement then moves the report `DISPUTED →
    RESTATED`, which is purely an eligibility change: it makes the report a
    legitimate target for a later filing's `restatement_of_report_id`, and that
    later filing is what finally drives it to `SUPERSEDED`."
    PRD §3.4: "A valid restatement drives the named report from `RESTATED` to the
    terminal `SUPERSEDED` state as part of the same request."
    PRD §3.4: "No fee is ever recognised against a superseded report, and the
    agreement's `recognized_revenue_cents` is unaffected by the supersession,
    because a report that reached `RESTATED` never contributed revenue in the
    first place."

    Design: Corner/state_machines/dispute_then_restatement_supersedes_the_original_report
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE, FLAT_TERMS)
    original = file_report(agreement["id"], distributor["id"], **REPORT_130K)

    disputed = validate_success(
        api.review_subscriber_report(
            original["id"], {"action": "DISPUTE", "note": "subscriber count queried"}, ACCOUNTANT
        )
    )
    assert disputed["status"] == "DISPUTED", (
        f"DISPUTE moves SUBMITTED to DISPUTED, got {disputed['status']}"
    )
    assert disputed["license_fee_due_cents"] == 0, (
        "a dispute leaves license_fee_due_cents at 0, got "
        f"{disputed['license_fee_due_cents']}"
    )

    restated = validate_success(
        api.review_subscriber_report(
            original["id"], {"action": "REQUEST_RESTATEMENT"}, ACCOUNTANT
        )
    )
    assert restated["status"] == "RESTATED", (
        f"REQUEST_RESTATEMENT moves DISPUTED to RESTATED, got {restated['status']}"
    )

    replacement_payload = create_subscriber_report_payload(
        agreement["id"],
        agreement_version(agreement["id"]),
        period_month="2026-06",
        reported_subscribers=141_000,
        reported_tier="BASIC",
        restatement_of_report_id=original["id"],
    )
    replacement = validate_success(
        api.create_subscriber_report(
            replacement_payload, make_distributor_liaison_headers(distributor["id"])
        ),
        201,
    )
    assert replacement["status"] == "SUBMITTED", (
        f"the replacement filing opens in SUBMITTED, got {replacement['status']}"
    )
    assert replacement["restatement_of_report_id"] == original["id"], (
        "the replacement names the restated report, got "
        f"{replacement['restatement_of_report_id']}"
    )
    assert replacement["provisional_fee_cents"] == 5_640_000, (
        "141,000 subscribers at 40.0000 cents accrue 5,640,000 cents, got "
        f"{replacement['provisional_fee_cents']}"
    )

    superseded = fetch_report(original["id"])
    assert superseded["status"] == "SUPERSEDED", (
        "the named report is driven to the terminal SUPERSEDED state by the same "
        f"request, got {superseded['status']}"
    )

    _rows, meta = validate_paginated(
        api.list_subscriber_reports(ACCOUNTANT, params={"agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 2, (
        "supersession retains the original row alongside the replacement, got "
        f"total_count {meta['total_count']}"
    )

    after = fetch_agreement(agreement["id"])
    assert after["recognized_revenue_cents"] == 0, (
        "no fee is recognised against a superseded report, got "
        f"{after['recognized_revenue_cents']}"
    )


def test_window_clear_then_clock_advance_activates_then_expires(api):
    """PRD §3.6: "Its `windowing_holdback_days` is stamped immediately, as the
    whole number of days from the title's `linear_premiere_at` to the window's
    `window_start`, discarding any fraction; a window that opens before the linear
    premiere therefore carries a negative holdback."
    PRD §3.6: "Thereafter the clock takes over: a `CLEARED` window whose start has
    arrived and whose end has not moves `CLEARED → ACTIVE` on a clock advance,
    provided the granting agreement is still `EXECUTED`; and a window in `CLEARED`
    or `ACTIVE` whose `window_end` has been reached moves to `EXPIRED`,
    decrementing the title's `cleared_window_count` and re-deriving coverage."
    PRD §2.5: "A successful advance increments `set_count` by one and then runs a
    single sweep whose step order is pinned and observable:"
    PRD §3.6: "Blocking is available from both `CLEARED` and `ACTIVE`, and arrives
    either from a `RightsAdministrator` acting deliberately — in which case a
    `block_reason` may accompany the action and the recorded reason is
    `MANUAL_BLOCK` — or from a system event: the granting agreement entering
    `SUSPENDED` records `AGREEMENT_SUSPENDED`, a blackout being enforced over the
    window records `BLACKOUT_CONFLICT`, and a title losing its rights records
    `RIGHTS_LAPSED`."

    Design: Corner/state_machines/window_clear_then_clock_advance_activates_then_expires
    """
    _distributor, _agreement, title, window = setup_cleared_window(
        MERIDIAN,
        FLAT_TERMS,
        {"title": "Harbor Nights", "linear_premiere_at": "2026-08-15T00:00:00Z"},
        {
            "platform": "VOD",
            "territory_code": "US",
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-30T00:00:00Z",
            "exclusivity": "NON_EXCLUSIVE",
        },
    )
    assert window["status"] == "CLEARED", (
        f"the window starts this scenario in CLEARED, got {window['status']}"
    )
    assert window["windowing_holdback_days"] == 17, (
        "2026-08-15 to 2026-09-01 is 17 whole days of holdback, got "
        f"{window['windowing_holdback_days']}"
    )
    assert title["cleared_window_count"] == 1, (
        f"clearance counts one window on the title, got {title['cleared_window_count']}"
    )

    before = read_clock()["set_count"]
    advanced = validate_success(api.set_clock(clock_payload("2026-09-15T00:00:00Z"), ADMIN))
    assert advanced["set_count"] == before + 1, (
        f"a successful advance increments set_count by one, expected {before + 1}, "
        f"got {advanced['set_count']}"
    )

    active = fetch_window(window["id"])
    assert active["status"] == "ACTIVE", (
        "with the start passed and the end still ahead the sweep moves CLEARED to "
        f"ACTIVE, got {active['status']}"
    )
    assert active["block_reason"] == "NONE", (
        f"an activated window carries no block reason, got {active['block_reason']}"
    )

    validate_success(api.set_clock(clock_payload("2026-09-30T00:00:00Z"), ADMIN))
    expired = fetch_window(window["id"])
    assert expired["status"] == "EXPIRED", (
        f"reaching window_end moves the window to EXPIRED, got {expired['status']}"
    )

    title_after = fetch_title(title["id"])
    assert title_after["cleared_window_count"] == 0, (
        "expiry decrements the title's cleared_window_count, got "
        f"{title_after['cleared_window_count']}"
    )

    validate_error(
        api.rights_window_lifecycle(window["id"], {"action": "BLOCK"}, RIGHTS),
        ApiErrorId.ERR_INVALID_WINDOW_STATE,
        409,
    )
    assert fetch_window(window["id"])["status"] == "EXPIRED", (
        "blocking is available only from CLEARED or ACTIVE, so the expired window "
        "is unchanged"
    )


def test_invoice_partial_payment_then_closing_payment_reaches_paid(api):
    """PRD §3.8: "A payment that leaves a residue moves the invoice `ISSUED →
    PARTIALLY_PAID`; a payment that closes the balance exactly moves it `ISSUED →
    PAID` or `PARTIALLY_PAID → PAID`."
    PRD §3.8: "Either way `paid_cents` increases by the amount and the operator's
    `receivable_balance_cents` decreases by the same amount, with
    `audit_recovery_balance_cents` decreasing identically when `invoice_kind` is
    `AUDIT_RECOVERY`."
    PRD §3.8: "`VOID` and `PAID` are both terminal."
    PRD §3.8: "`coop_cap_pct` is selected from that gross: 0.05 when the gross is
    below 5,000,000 cents, 0.08 from 5,000,000 cents up to but not including
    25,000,000 cents, and 0.12 at 25,000,000 cents and above."

    Design: Corner/state_machines/invoice_partial_payment_then_closing_payment_reaches_paid
    """
    distributor, _agreement, _report, invoice = setup_issued_invoice(
        CLIFFSIDE, FLAT_TERMS, REPORT_130K
    )
    assert invoice["gross_license_fee_cents"] == 5_200_000, (
        "the single accepted report for the period grosses 5,200,000 cents, got "
        f"{invoice['gross_license_fee_cents']}"
    )
    assert invoice["coop_cap_pct"] == pytest.approx(0.08, abs=0.01), (
        f"a gross of 5,200,000 cents selects the 0.08 band, got {invoice['coop_cap_pct']}"
    )
    assert invoice["net_due_cents"] == 5_200_000, (
        f"with no offsets the net due equals the gross, got {invoice['net_due_cents']}"
    )
    assert distributor["receivable_balance_cents"] == 5_200_000, (
        "issuing the invoice raised the operator's receivable to the net due, got "
        f"{distributor['receivable_balance_cents']}"
    )

    partial = validate_success(
        api.invoice_lifecycle(
            invoice["id"], {"action": "RECORD_PAYMENT", "amount_cents": 2_000_000}, ACCOUNTANT
        )
    )
    assert partial["status"] == "PARTIALLY_PAID", (
        f"a payment leaving a residue moves ISSUED to PARTIALLY_PAID, got {partial['status']}"
    )
    assert partial["paid_cents"] == 2_000_000, (
        f"paid_cents increases by the amount, got {partial['paid_cents']}"
    )
    mid = fetch_distributor(distributor["id"])
    assert mid["receivable_balance_cents"] == 3_200_000, (
        "the receivable decreases by the same amount, got "
        f"{mid['receivable_balance_cents']}"
    )

    closing = validate_success(
        api.invoice_lifecycle(
            invoice["id"], {"action": "RECORD_PAYMENT", "amount_cents": 3_200_000}, ACCOUNTANT
        )
    )
    assert closing["status"] == "PAID", (
        "a payment that closes the balance exactly moves PARTIALLY_PAID to PAID, got "
        f"{closing['status']}"
    )
    assert closing["paid_cents"] == 5_200_000, (
        f"paid_cents accumulates both payments, got {closing['paid_cents']}"
    )
    settled = fetch_distributor(distributor["id"])
    assert settled["receivable_balance_cents"] == 0, (
        f"the receivable returns to zero, got {settled['receivable_balance_cents']}"
    )

    validate_error(
        api.invoice_lifecycle(
            invoice["id"], {"action": "RECORD_PAYMENT", "amount_cents": 1}, ACCOUNTANT
        ),
        ApiErrorId.ERR_INVALID_INVOICE_STATE,
        409,
    )
    assert fetch_invoice(invoice["id"])["paid_cents"] == 5_200_000, (
        "PAID is terminal, so the refused payment changes nothing"
    )


def test_waived_blackout_rule_rejects_later_enforce(api):
    """PRD §3.6: "A new rule opens in `SCHEDULED` with `enforced_at` null and
    `version` 1."
    PRD §3.6: "The rule's own `blackout_hours` is the elapsed time from
    `blackout_start` to `blackout_end` expressed in hours and rounded half up to
    two decimal places."
    PRD §3.6: "Waiving instead moves `SCHEDULED → WAIVED`, after which the rule
    stops conflicting with anything and stops counting toward
    `monthly_blackout_hours` for its month."
    PRD §3.6: "A scheduled rule can be enforced or waived, and either action
    requires the rule to still be in `SCHEDULED`; anything else is
    `ERR_INVALID_BLACKOUT_STATE`."

    Design: Corner/state_machines/waived_blackout_rule_rejects_later_enforce
    """
    _distributor, agreement = setup_executed_agreement(MERIDIAN, FLAT_TERMS)
    rule = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-05T18:00:00Z",
        blackout_end="2026-09-05T22:00:00Z",
    )
    assert rule["status"] == "SCHEDULED", (
        f"a new rule opens in SCHEDULED, got {rule['status']}"
    )
    assert rule["enforced_at"] is None, (
        f"a new rule opens with enforced_at null, got {rule['enforced_at']}"
    )
    assert rule["blackout_hours"] == pytest.approx(4.0, abs=0.01), (
        f"18:00 to 22:00 is four hours, got {rule['blackout_hours']}"
    )
    assert_blackout_rule(rule)

    waived = validate_success(
        api.blackout_rule_lifecycle(rule["id"], {"action": "WAIVE"}, RIGHTS)
    )
    assert waived["status"] == "WAIVED", (
        f"WAIVE moves SCHEDULED to WAIVED, got {waived['status']}"
    )
    assert waived["enforced_at"] is None, (
        f"waiving never stamps enforced_at, got {waived['enforced_at']}"
    )

    validate_error(
        api.blackout_rule_lifecycle(rule["id"], {"action": "ENFORCE"}, RIGHTS),
        ApiErrorId.ERR_INVALID_BLACKOUT_STATE,
        409,
    )
    validate_error(
        api.blackout_rule_lifecycle(rule["id"], {"action": "WAIVE"}, RIGHTS),
        ApiErrorId.ERR_INVALID_BLACKOUT_STATE,
        409,
    )

    after = fetch_blackout_rule(rule["id"])
    assert after["status"] == "WAIVED", (
        f"both refused actions leave the rule WAIVED, got {after['status']}"
    )
    assert after["enforced_at"] is None, (
        f"no side effect of the refused ENFORCE fires, got {after['enforced_at']}"
    )


def test_renewal_offer_requires_an_existing_analysis_row(api):
    """PRD §3.9: "An `AffiliateSalesExec` moves the agreement `NOT_DUE →
    RENEWAL_ANALYSIS`, which requires the `lifecycle_status` to be `EXECUTED` or
    `SUSPENDED` — an operator under suspension is still a renewal candidate — and
    requires the renewal window to be open: `term_end_date` must be no more than
    270 days beyond the current logical instant."
    PRD §3.9: "Offering with no model on file is refused with
    `ERR_RENEWAL_REQUIRES_ANALYSIS`: the system will not let terms go out
    unpriced."
    PRD §3.9: "Once at least one model exists, the exec can table terms, moving
    the agreement `RENEWAL_ANALYSIS → RENEWAL_OFFERED` and stamping
    `renewal_offer_sent_at`."
    PRD §3.9: "That report's identifier is recorded as
    `latest_accepted_report_id`."

    Design: Corner/state_machines/renewal_offer_requires_an_existing_analysis_row
    """
    _distributor, agreement, report = setup_accepted_report(
        CLIFFSIDE,
        {**FLAT_TERMS, "term_end_date": "2027-01-31T00:00:00Z"},
        REPORT_130K,
    )

    started = start_renewal_analysis(agreement["id"])
    assert started["renewal_status"] == "RENEWAL_ANALYSIS", (
        f"START_ANALYSIS moves NOT_DUE to RENEWAL_ANALYSIS, got {started['renewal_status']}"
    )
    assert started["lifecycle_status"] == "EXECUTED", (
        "the renewal dimension moves independently of the lifecycle dimension, got "
        f"{started['lifecycle_status']}"
    )

    validate_error(
        api.agreement_renewal(agreement["id"], {"action": "OFFER"}, SALES),
        ApiErrorId.ERR_RENEWAL_REQUIRES_ANALYSIS,
        422,
    )
    assert fetch_agreement(agreement["id"])["renewal_status"] == "RENEWAL_ANALYSIS", (
        "the refused offer leaves the agreement in RENEWAL_ANALYSIS"
    )

    analysis = validate_success(
        api.create_renewal_analysis(
            create_renewal_analysis_payload(agreement["id"], variant="BASE_CASE"), SALES
        ),
        201,
    )
    assert analysis["variant"] == "BASE_CASE", (
        f"the model is stored under the requested variant, got {analysis['variant']}"
    )
    assert analysis["latest_accepted_report_id"] == report["id"], (
        "the analysis records the identifier of the latest accepted report, got "
        f"{analysis['latest_accepted_report_id']}"
    )

    offered = validate_success(
        api.agreement_renewal(agreement["id"], {"action": "OFFER"}, SALES)
    )
    assert offered["renewal_status"] == "RENEWAL_OFFERED", (
        "with a model on file OFFER moves RENEWAL_ANALYSIS to RENEWAL_OFFERED, got "
        f"{offered['renewal_status']}"
    )
    assert offered["lifecycle_status"] == "EXECUTED", (
        f"the lifecycle dimension is untouched by the offer, got {offered['lifecycle_status']}"
    )
