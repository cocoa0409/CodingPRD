"""Lifecycle transitions and their guards.

Each test drives one entity across a transition the PRD names and then asserts
both the resulting status and the counters the PRD says that transition touches
— revision rounds, return counts, committed minutes, coverage gaps and the
year-to-date billing ledger.  Rejected transitions assert the exact error
identifier §3 states in prose.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_DEFAULTS, THRESHOLDS, factories
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_incident_report


# ==========================================================================
# Client contract — the draft/pending revision loop
# ==========================================================================
def test_client_return_increments_revision_round_on_every_lap(api):
    """PRD §3.1: "A `decision` of `RETURN` sends the contract back
    `PENDING_CLIENT_APPROVAL → DRAFT` and increments `revision_round` by 1; the
    loop from draft to pending and back may repeat without bound, and
    `revision_round` is the count of those returns."

    PRD §3.1: "A newly created contract lands in `DRAFT` with `revision_round`,
    `ytd_billed_cents`, `pending_penalty_cents`, `uncovered_session_count`, and
    `eligible_member_count` all initialised to 0, `supersedes_contract_id` null,
    and `approved_at` null."

    Design: Corner/state_machines/contract_client_decision_return_increments_revision_round
    """
    scenario = scenarios.setup_draft_contract("COST_PLUS")
    contract_id = scenario["contract_id"]

    validate_success(api.submit_client_contract(contract_id, scenario["admin_headers"]))
    pending = scenarios.read_contract(contract_id)
    assert pending["status"] == "PENDING_CLIENT_APPROVAL", (
        f"expected PENDING_CLIENT_APPROVAL, got {pending['status']} after the first submit"
    )
    assert pending["revision_round"] == 0, (
        f"expected revision_round 0, got {pending['revision_round']} before any return"
    )

    first_return = validate_success(
        api.client_decision(
            contract_id,
            {"decision": "RETURN", "comment": "Raise the participation target to 40."},
            scenario["sponsor_headers"],
        )
    )
    assert first_return["status"] == "DRAFT", (
        f"expected DRAFT, got {first_return['status']} after the first RETURN"
    )
    assert first_return["revision_round"] == 1, (
        f"expected revision_round 1, got {first_return['revision_round']} after the first RETURN"
    )
    assert first_return["approved_at"] is None, (
        f"approved_at must stay null on a returned contract, got {first_return['approved_at']!r}"
    )

    resubmitted = validate_success(
        api.submit_client_contract(contract_id, scenario["admin_headers"])
    )
    assert resubmitted["status"] == "PENDING_CLIENT_APPROVAL", (
        f"expected PENDING_CLIENT_APPROVAL, got {resubmitted['status']} after re-submitting"
    )
    assert resubmitted["revision_round"] == 1, (
        "re-submitting must not reset the return counter: expected revision_round 1, "
        f"got {resubmitted['revision_round']}"
    )

    second_return = validate_success(
        api.client_decision(
            contract_id,
            {"decision": "RETURN", "comment": "Second pass: fix the fee schedule."},
            scenario["sponsor_headers"],
        )
    )
    assert second_return["status"] == "DRAFT", (
        f"expected DRAFT, got {second_return['status']} after the second RETURN"
    )
    assert second_return["revision_round"] == 2, (
        "each RETURN increments the counter by exactly 1: expected revision_round 2, "
        f"got {second_return['revision_round']}"
    )
    assert second_return["approved_at"] is None, (
        f"approved_at must still be null, got {second_return['approved_at']!r}"
    )
    assert second_return["ytd_billed_cents"] == 0, (
        "a contract that never reached ACTIVE has billed nothing: expected 0, got "
        f"{second_return['ytd_billed_cents']}"
    )


def test_submit_without_an_active_duty_site_manager_is_refused(api):
    """PRD §3.1: "Submission for client approval moves the contract `DRAFT →
    PENDING_CLIENT_APPROVAL`, and it is gated twice: the fee terms must already
    be complete for the declared `fee_structure`, and the contract must have at
    least one staff member whose `role_type` is `SITE_MANAGER` and whose
    `duty_status` is `ACTIVE_DUTY`."

    PRD §3.1: "A submission with no such site manager on the roster is refused
    with `ERR_SITE_MANAGER_REQUIRED`."

    PRD §3.2: "A new hire starts with `duty_status` of `ACTIVE_DUTY`,
    `committed_minutes_current_period` at 0, `last_drill_on` null, and
    `readiness_index` computed immediately — which in practice means 0, since a
    fresh hire holds no verified credential yet."

    Design: Corner/state_machines/submit_without_active_site_manager_returns_422
    """
    scenarios.set_clock()
    contract = scenarios.create_draft_contract("COST_PLUS")
    contract_id = contract["id"]
    admin = scenarios.ADMIN

    scenarios.hire_staff(
        contract_id,
        role_type="GROUP_EX_INSTRUCTOR",
        full_name="Ravi Patel",
        hourly_cost_cents=TEST_DEFAULTS["INSTRUCTOR_HOURLY_COST_CENTS"],
    )
    before = scenarios.read_contract(contract_id)

    validate_error(
        api.submit_client_contract(contract_id, admin),
        ApiErrorId.ERR_SITE_MANAGER_REQUIRED.value,
    )

    rejected = scenarios.read_contract(contract_id)
    assert rejected["status"] == "DRAFT", (
        f"expected DRAFT, got {rejected['status']} after the refused submit"
    )
    assert rejected["version"] == before["version"], (
        f"a refused submit mutates nothing: expected version {before['version']}, "
        f"got {rejected['version']}"
    )

    manager = scenarios.hire_staff(
        contract_id,
        role_type="SITE_MANAGER",
        full_name="Dana Reed",
        hourly_cost_cents=TEST_DEFAULTS["MANAGER_HOURLY_COST_CENTS"],
    )
    assert manager["duty_status"] == "ACTIVE_DUTY", (
        "a fresh hire is on active duty with no verification step: expected ACTIVE_DUTY, "
        f"got {manager['duty_status']}"
    )

    submitted = validate_success(api.submit_client_contract(contract_id, admin))
    assert submitted["status"] == "PENDING_CLIENT_APPROVAL", (
        "the rule reads role_type, not headcount: expected PENDING_CLIENT_APPROVAL once a "
        f"SITE_MANAGER is on the roster, got {submitted['status']}"
    )


# ==========================================================================
# Program offering — closing is guarded by its own children
# ==========================================================================
def test_offering_close_is_blocked_while_a_scheduled_session_remains(api):
    """PRD §3.4: "An `ACTIVE` or `PAUSED` offering may be **closed**, moving it
    to `CLOSED`, but only when it has no session left in `SCHEDULED`, `STAFFED`,
    `STAFFING_AT_RISK`, or `IN_PROGRESS` status; a close attempted with live
    sessions outstanding is refused with `ERR_OPEN_SESSIONS`."

    PRD §3.5: "A `cancel_reason` of `CLIENT_REQUEST` moves the session from
    `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK` to `CANCELLED_CLIENT`."

    PRD §3.4: "Closing recomputes `final_attainment_pct` one last time and
    freezes `provisional_attainment_pct` at whatever value it last held."

    Design: Corner/state_machines/offering_close_with_open_sessions_rejected
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={
            "participation_target": 8,
            "eligible_member_classes": ["EMPLOYEE"],
        }
    )
    offering_id = scenario["offering_id"]
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    assert session["status"] == "SCHEDULED", (
        f"expected a SCHEDULED session to block the close, got {session['status']}"
    )

    close_payload = {"action": "CLOSE", "reason": "Program retired at client request"}
    validate_error(
        api.offering_status_change(offering_id, close_payload, scenario["manager_headers"]),
        ApiErrorId.ERR_OPEN_SESSIONS.value,
    )
    blocked = scenarios.read_offering(offering_id)
    assert blocked["status"] == "ACTIVE", (
        f"a refused close leaves the offering ACTIVE, got {blocked['status']}"
    )

    cancelled = validate_success(
        api.session_status_change(
            session["id"],
            {"action": "CANCEL", "cancel_reason": "CLIENT_REQUEST"},
            scenario["manager_headers"],
        )
    )
    assert cancelled["status"] == "CANCELLED_CLIENT", (
        f"expected CANCELLED_CLIENT, got {cancelled['status']} after cancelling on client request"
    )

    closed = validate_success(
        api.offering_status_change(offering_id, close_payload, scenario["manager_headers"])
    )
    assert closed["status"] == "CLOSED", (
        "a cancelled session is not an open session, so the identical close now succeeds: "
        f"expected CLOSED, got {closed['status']}"
    )
    assert closed["final_attainment_pct"] == 0, (
        "no check-in ever happened, so the final numerator is empty: expected 0, got "
        f"{closed['final_attainment_pct']}"
    )
    assert closed["counted_participation_total"] == 0, (
        f"expected counted_participation_total 0, got {closed['counted_participation_total']}"
    )


# ==========================================================================
# Incident report — the review cascade and the review loop
# ==========================================================================
def test_reviewing_a_serious_equipment_incident_fires_the_full_cascade(api):
    """PRD §3.8: "**Review** moves the report `REPORTED → UNDER_REVIEW` and
    records the reviewer in `reviewed_by_user_id`, optionally alongside a
    `review_note`."

    PRD §3.8: "First, the named asset moves to `OUT_OF_SERVICE` with
    `out_of_service_since` set to the current instant — which starts its
    downtime-credit clock, as §3.3 describes."

    PRD §3.8: "Second, because that asset is now out of service, the room housing
    it moves from `OPEN` to `RESTRICTED` and its `open_deficiency_count`
    increases by 1."

    PRD §3.8: "Third, because that room is now restricted, every session of the
    room in `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK` status whose
    `scheduled_start_utc` falls within the next 24 hours moves to
    `CANCELLED_FACILITY`."

    PRD §3.8: "Fourth, each of those cancellations releases its assignments and
    subtracts each released assignment's `paid_minutes` from the corresponding
    staff member's `committed_minutes_current_period`."

    Design: Corner/state_machines/incident_review_takes_equipment_out_of_service
    """
    scenario = scenarios.setup_active_program()
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    assignment = scenarios.staff_session(scenario, session["id"])
    expected_paid = 55 + THRESHOLDS["LEAD_SETUP_MIN"]
    assert assignment["paid_minutes"] == expected_paid, (
        f"a LEAD on a 55-minute session is paid {expected_paid} minutes, got "
        f"{assignment['paid_minutes']}"
    )
    assert scenarios.read_session(session["id"])["status"] == "STAFFED", (
        "the confirmed LEAD must have staffed the session before the cascade is provoked"
    )
    assert (
        scenarios.read_staff(scenario["instructor_id"])["committed_minutes_current_period"]
        == expected_paid
    ), f"expected {expected_paid} committed minutes booked by the confirmed LEAD"

    # Twelve hours before the session — inside the 24-hour lock window.
    scenarios.set_clock("2026-08-05T00:00:00Z")
    incident = scenarios.file_incident(
        scenario,
        severity="SERIOUS",
        cause_category="EQUIPMENT",
        narrative="AED self-test failed during pre-class checks.",
        asset_id=scenario["aed_id"],
        aed_deployed=False,
        occurred_at_utc="2026-08-04T18:30:00Z",
    )

    reviewed = validate_success(
        api.review_incident(
            incident["id"],
            {"review_note": "Unit pulled from the wall pending vendor service."},
            scenario["manager_headers"],
        )
    )
    assert reviewed["status"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW, got {reviewed['status']} after the review"
    )
    assert reviewed["reviewed_by_user_id"] == scenario["manager_id"], (
        "the reviewing site manager's principal id is recorded: expected "
        f"{scenario['manager_id']}, got {reviewed['reviewed_by_user_id']!r}"
    )
    assert reviewed["return_count"] == 0, (
        f"expected return_count 0 on a first review, got {reviewed['return_count']}"
    )

    asset = scenarios.read_asset(scenario["aed_id"])
    assert asset["status"] == "OUT_OF_SERVICE", (
        f"cascade link 1: expected OUT_OF_SERVICE, got {asset['status']}"
    )
    assert asset["out_of_service_since"] is not None and asset[
        "out_of_service_since"
    ].startswith("2026-08-05T00:00:00"), (
        "out_of_service_since is stamped from the logical clock: expected "
        f"2026-08-05T00:00:00, got {asset['out_of_service_since']!r}"
    )
    assert asset["readiness_status"] == "NOT_READY", (
        "a defibrillator that is not IN_SERVICE is NOT_READY, got "
        f"{asset['readiness_status']}"
    )

    room = scenarios.read_room(scenario["room_id"])
    assert room["room_state"] == "RESTRICTED", (
        f"cascade link 2: expected RESTRICTED, got {room['room_state']}"
    )
    assert room["open_deficiency_count"] == 1, (
        f"cascade link 2: expected open_deficiency_count 1, got {room['open_deficiency_count']}"
    )

    cancelled = scenarios.read_session(session["id"])
    assert cancelled["status"] == "CANCELLED_FACILITY", (
        f"cascade link 3: expected CANCELLED_FACILITY, got {cancelled['status']}"
    )
    assert cancelled["cancel_reason"] == "FACILITY", (
        f"cascade link 3: expected cancel_reason FACILITY, got {cancelled['cancel_reason']!r}"
    )

    released = scenarios.read_assignment(assignment["id"])
    assert released["status"] == "RELEASED", (
        f"cascade link 4: expected RELEASED, got {released['status']}"
    )
    assert (
        scenarios.read_staff(scenario["instructor_id"])["committed_minutes_current_period"]
        == 0
    ), (
        f"cascade link 4: the released {expected_paid} minutes must return to the ledger, "
        "expected 0 committed minutes"
    )

    assert scenarios.read_offering(scenario["offering_id"])["status"] == "ACTIVE", (
        "the four links stop at the session and its assignments; the offering is untouched"
    )

# ==========================================================================
# Monthly invoice — the draft/issue/dispute/rebill cycle
# ==========================================================================
def test_rebilling_a_draft_invoice_is_refused_before_any_dispute(api):
    """PRD §3.9: "A new invoice lands in `DRAFT` with `rebill_count` at 0 and
    `issued_at`, `disputed_at`, `paid_at`, and `dispute_reason` all null."

    PRD §3.9: "Rebilling anything not in `DISPUTED` is refused with
    `ERR_INVOICE_NOT_DISPUTED`."

    PRD §3.9: "`coverage_penalty_cents` is 0 — the client is already paying only
    for work actually delivered, so a missed session costs them nothing to
    penalise."

    Design: Corner/state_machines/pay_a_draft_invoice_returns_409
    """
    scenario = scenarios.setup_active_contract("COST_PLUS")
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    assert invoice["status"] == "DRAFT", (
        f"a freshly drafted invoice is DRAFT, got {invoice['status']}"
    )
    assert invoice["rebill_count"] == 0, (
        f"expected rebill_count 0 on a new draft, got {invoice['rebill_count']}"
    )
    assert invoice["issued_at"] is None, (
        f"issued_at must be null on a draft, got {invoice['issued_at']!r}"
    )
    assert invoice["paid_at"] is None, (
        f"paid_at must be null on a draft, got {invoice['paid_at']!r}"
    )
    assert invoice["coverage_penalty_cents"] == 0, (
        "a cost-plus period never carries a coverage penalty: expected 0, got "
        f"{invoice['coverage_penalty_cents']}"
    )

    validate_error(
        api.rebill_invoice(invoice["id"], scenario["admin_headers"]),
        ApiErrorId.ERR_INVOICE_NOT_DISPUTED.value,
    )

    untouched = scenarios.read_invoice(invoice["id"])
    assert untouched["status"] == "DRAFT", (
        f"a refused rebill leaves the invoice in DRAFT, got {untouched['status']}"
    )
    assert untouched["rebill_count"] == 0, (
        f"a refused rebill increments nothing: expected rebill_count 0, got "
        f"{untouched['rebill_count']}"
    )
    assert scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"] == 0, (
        "nothing has been issued, so the year-to-date ledger is still empty"
    )


def test_paying_an_issued_invoice_stamps_paid_at_without_rebilling_the_ledger(api):
    """PRD §3.9: "**Issuing** moves the invoice `DRAFT → ISSUED`, stamps
    `issued_at`, and adds `net_amount_cents` to the contract's
    `ytd_billed_cents`."

    PRD §3.9: "**Paying** is again the client's move, optionally recording a
    `payment_reference` for their own reconciliation; it moves the invoice
    `ISSUED → PAID`, stamps `paid_at`, and leaves `ytd_billed_cents` untouched,
    because issuing already counted it."

    PRD §3.9: "`PAID` and `SUPERSEDED` are both terminal, and any further action
    against either is refused with `ERR_TERMINAL_STATE`."

    Design: Corner/state_machines/pay_a_draft_invoice_returns_409
    """
    scenario = scenarios.setup_active_contract("COST_PLUS")
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")

    issued = validate_success(api.issue_invoice(invoice["id"], scenario["admin_headers"]))
    assert issued["status"] == "ISSUED", (
        f"expected ISSUED, got {issued['status']} after issuing the draft"
    )
    assert issued["net_amount_cents"] == 0, (
        "no assignment completed and no supplies were bought, so the period bills nothing: "
        f"expected 0, got {issued['net_amount_cents']}"
    )
    assert (
        scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"]
        == issued["net_amount_cents"]
    ), "issuing adds exactly net_amount_cents to the year-to-date ledger"

    paid = validate_success(
        api.pay_invoice(
            invoice["id"], {"payment_reference": "ACH-90001"}, scenario["sponsor_headers"]
        )
    )
    assert paid["status"] == "PAID", (
        f"expected PAID, got {paid['status']} after the client paid"
    )
    assert paid["paid_at"] is not None and paid["paid_at"].startswith(
        "2026-08-01T00:00:00"
    ), f"paid_at is stamped from the logical clock, got {paid['paid_at']!r}"
    assert (
        scenarios.read_contract(scenario["contract_id"])["ytd_billed_cents"]
        == issued["net_amount_cents"]
    ), "payment must not double-count: the ledger keeps the amount issuing already added"

    validate_error(
        api.pay_invoice(
            invoice["id"], {"payment_reference": "ACH-90002"}, scenario["sponsor_headers"]
        ),
        ApiErrorId.ERR_TERMINAL_STATE.value,
    )
    assert scenarios.read_invoice(invoice["id"])["status"] == "PAID", (
        "a second payment attempt against a terminal invoice changes nothing"
    )


# ==========================================================================
# Incident report — the opening state
# ==========================================================================
def test_a_newly_filed_incident_report_opens_in_reported(api):
    """PRD §3.8: "A new report lands in `REPORTED` with `return_count` at 0 and
    `reviewed_by_user_id`, `claim_reference`, and `closure_note` all null."

    PRD §3.8: "Three optional fields make the report specific: `member_id` names
    the person involved when there was one, `asset_id` names the equipment
    involved when there was any, and `aed_deployed` records whether a
    defibrillator was actually used, defaulting to false."

    PRD §2.4: "Most records additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the record — and `version`, an
    integer that starts at 1 when the record is created and increments by exactly
    1 on every mutation of that record, including mutations caused by a cascade
    originating elsewhere."

    Design: Corner/state_machines/new_incident_report_starts_in_reported
    """
    scenario = scenarios.setup_active_contract("COST_PLUS")
    payload = factories.incident_report_payload(
        scenario["contract_id"],
        scenario["manager_id"],
        occurred_at_utc="2026-07-31T16:05:00Z",
        severity="MINOR",
        cause_category="SLIP_FALL",
        narrative="Member slipped on a wet patch by the water fountain; no injury reported.",
    )
    report = validate_success(
        api.create_incident_report(payload, scenario["manager_headers"]), 201
    )
    assert_incident_report(report)

    assert report["status"] == "REPORTED", (
        f"every report opens in REPORTED, got {report['status']}"
    )
    assert report["return_count"] == 0, (
        f"expected return_count 0 on a brand new report, got {report['return_count']}"
    )
    assert report["reviewed_by_user_id"] is None, (
        f"nobody has reviewed it yet, got {report['reviewed_by_user_id']!r}"
    )
    assert report["claim_reference"] is None, (
        f"claim_reference must open null, got {report['claim_reference']!r}"
    )
    assert report["closure_note"] is None, (
        f"closure_note must open null, got {report['closure_note']!r}"
    )
    assert report["version"] == 1, (
        f"a created record carries version 1, got {report['version']}"
    )
    assert report["aed_deployed"] is False, (
        f"aed_deployed defaults to false when it is not supplied, got {report['aed_deployed']!r}"
    )
    assert report["member_id"] is None, (
        f"this filing names no member, got {report['member_id']!r}"
    )
    assert report["asset_id"] is None, (
        f"this filing names no equipment, got {report['asset_id']!r}"
    )
    assert report["reported_by_staff_id"] == scenario["manager_id"], (
        f"expected reporter {scenario['manager_id']}, got {report['reported_by_staff_id']!r}"
    )


# ==========================================================================
# Client contract — withdrawal is terminal
# ==========================================================================
def test_a_withdrawn_draft_contract_refuses_every_further_action(api):
    """PRD §3.1: "A `TERMINATE` action requested against a contract still in `DRAFT`
    does not terminate it — it withdraws it, moving the contract `DRAFT →
    WITHDRAWN`."

    PRD §3.1: "`TERMINATED` and `WITHDRAWN` are terminal: any further action on
    such a contract is refused with `ERR_TERMINAL_STATE`."

    PRD §3.1: "A withdrawn contract releases its `site_code` back into
    circulation."

    Design: Corner/state_machines/submit_a_withdrawn_contract_returns_409
    """
    scenario = scenarios.setup_draft_contract("COST_PLUS")
    contract_id = scenario["contract_id"]
    admin = scenario["admin_headers"]
    site_code = scenario["contract"]["site_code"]

    withdrawn = validate_success(
        api.service_status(
            contract_id,
            {"action": "TERMINATE", "reason": "Client cancelled before signature"},
            admin,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        "terminating a draft withdraws it rather than terminating it: expected WITHDRAWN, "
        f"got {withdrawn['status']}"
    )

    validate_error(
        api.submit_client_contract(contract_id, admin),
        ApiErrorId.ERR_TERMINAL_STATE.value,
    )
    validate_error(
        api.service_status(contract_id, {"action": "RESUME"}, admin),
        ApiErrorId.ERR_TERMINAL_STATE.value,
    )

    final = scenarios.read_contract(contract_id)
    assert final["status"] == "WITHDRAWN", (
        f"a withdrawn contract never leaves that state, got {final['status']}"
    )
    assert final["revision_round"] == 0, (
        "the refused submit never reached the approval loop: expected revision_round 0, got "
        f"{final['revision_round']}"
    )
    assert final["approved_at"] is None, (
        f"approved_at must still be null, got {final['approved_at']!r}"
    )

    successor = validate_success(
        api.create_client_contract(
            factories.client_contract_payload(site_code=site_code), admin
        ),
        201,
    )
    assert successor["site_code"] == site_code, (
        f"the released site code must be reusable: expected {site_code}, got "
        f"{successor['site_code']}"
    )
    assert successor["status"] == "DRAFT", (
        f"the replacement site opens in DRAFT, got {successor['status']}"
    )


# ==========================================================================
# Staff credential — the verification decision fires once
# ==========================================================================
def test_a_second_accept_on_a_verified_credential_is_refused(api):
    """PRD §3.2: "Either decision against a record that is not in
    `PENDING_VERIFICATION` is refused with `ERR_CREDENTIAL_NOT_PENDING`, and — as
    §2.1 established — the holder may never be the decider."

    PRD §3.2: "Renewal attempted on a record that is neither `EXPIRED` nor
    `REJECTED` is refused with `ERR_CREDENTIAL_NOT_RENEWABLE`."

    PRD §3.2: "An `ACCEPT` moves the record `PENDING_VERIFICATION → VERIFIED`,
    stamps `verified_at` with the logical clock instant and `verified_by_user_id`
    with the deciding principal's identifier, and recomputes the holder's
    `readiness_index`."

    Design: Corner/state_machines/second_verify_on_a_verified_credential_returns_409
    """
    scenario = scenarios.setup_draft_contract("COST_PLUS")
    credential_id = scenario["manager_credential"]["id"]
    admin = scenario["admin_headers"]

    verified = scenarios.read_credential(credential_id)
    assert verified["status"] == "VERIFIED", (
        f"the site manager's card was already accepted, got {verified['status']}"
    )

    validate_error(
        api.verify_credential(credential_id, {"decision": "ACCEPT"}, admin),
        ApiErrorId.ERR_CREDENTIAL_NOT_PENDING.value,
    )
    validate_error(
        api.verify_credential(
            credential_id,
            {"decision": "REJECT", "rejection_reason": "Second look at the same card"},
            admin,
        ),
        ApiErrorId.ERR_CREDENTIAL_NOT_PENDING.value,
    )
    validate_error(
        api.renew_credential(
            credential_id,
            {"credential_number": "AHA-772", "expires_on": "2028-06-30"},
            admin,
        ),
        ApiErrorId.ERR_CREDENTIAL_NOT_RENEWABLE.value,
    )

    unchanged = scenarios.read_credential(credential_id)
    assert unchanged["status"] == "VERIFIED", (
        f"the replayed decisions leave the record VERIFIED, got {unchanged['status']}"
    )
    assert unchanged["credential_number"] == verified["credential_number"], (
        "a refused renewal must not overwrite the certificate number: expected "
        f"{verified['credential_number']}, got {unchanged['credential_number']}"
    )
    assert unchanged["expires_on"] == TEST_DEFAULTS["TERM_END_ON"], (
        f"expected expires_on {TEST_DEFAULTS['TERM_END_ON']}, got {unchanged['expires_on']}"
    )
    assert unchanged["version"] == verified["version"], (
        f"three refused calls mutate nothing: expected version {verified['version']}, got "
        f"{unchanged['version']}"
    )
    assert unchanged["renewal_count"] == 0, (
        f"the card has taken no lap around the loop: expected 0, got {unchanged['renewal_count']}"
    )
    assert unchanged["rejection_reason"] is None, (
        f"a refused REJECT stores no reason, got {unchanged['rejection_reason']!r}"
    )
    assert scenarios.read_staff(scenario["manager_id"])["duty_status"] == "ACTIVE_DUTY", (
        "the holder's duty status is untouched by the refused decisions"
    )


# ==========================================================================
# Incident report — the review loop repeats
# ==========================================================================
def test_returning_an_incident_report_restarts_the_review_loop(api):
    """PRD §3.8: "**Review** moves the report `REPORTED → UNDER_REVIEW` and
    records the reviewer in `reviewed_by_user_id`, optionally alongside a
    `review_note`."

    PRD §3.8: "Return moves it `UNDER_REVIEW → REPORTED`, increases `return_count`
    by 1, and clears `reviewed_by_user_id` back to null so that the next review is
    a fresh decision."

    PRD §3.8: "The return loop may repeat as often as needed, so `return_count`
    accumulates across the whole life of the report."

    Design: Corner/state_machines/incident_return_restarts_the_review_loop
    """
    scenario = scenarios.setup_active_contract("COST_PLUS")
    contract_id = scenario["contract_id"]
    auditor = scenario["auditor_headers"]
    report = validate_success(
        api.create_incident_report(
            factories.incident_report_payload(
                contract_id,
                scenario["manager_id"],
                occurred_at_utc="2026-07-31T16:05:00Z",
                severity="MINOR",
                cause_category="SLIP_FALL",
                narrative="Member slipped by the water fountain; narrative needs more detail.",
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    report_id = report["id"]

    first_review = validate_success(
        api.review_incident(report_id, {"review_note": "Taking a first look."}, auditor)
    )
    assert first_review["status"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW, got {first_review['status']} on the first review"
    )
    assert first_review["reviewed_by_user_id"] == "auditor-1", (
        "the auditor's opaque principal id is recorded as the reviewer: expected auditor-1, "
        f"got {first_review['reviewed_by_user_id']!r}"
    )

    first_return = validate_success(
        api.return_incident(
            report_id, {"return_note": "Name the member and the time of day."}, auditor
        )
    )
    assert first_return["status"] == "REPORTED", (
        f"a return sends the report back to REPORTED, got {first_return['status']}"
    )
    assert first_return["return_count"] == 1, (
        f"expected return_count 1 after one return, got {first_return['return_count']}"
    )
    assert first_return["reviewed_by_user_id"] is None, (
        "the return clears the reviewer so the next review is a fresh decision, got "
        f"{first_return['reviewed_by_user_id']!r}"
    )

    second_review = validate_success(
        api.review_incident(report_id, {"review_note": "Second look."}, auditor)
    )
    assert second_review["status"] == "UNDER_REVIEW", (
        "the loop reopens from REPORTED: expected UNDER_REVIEW, got "
        f"{second_review['status']}"
    )
    assert second_review["reviewed_by_user_id"] == "auditor-1", (
        f"expected the reviewer recorded again, got {second_review['reviewed_by_user_id']!r}"
    )
    assert second_review["return_count"] == 1, (
        "a review never resets the accumulated count: expected 1, got "
        f"{second_review['return_count']}"
    )

    second_return = validate_success(
        api.return_incident(
            report_id, {"return_note": "Still missing the equipment involved."}, auditor
        )
    )
    assert second_return["status"] == "REPORTED", (
        f"expected REPORTED after the second return, got {second_return['status']}"
    )
    assert second_return["return_count"] == 2, (
        "the counter accumulates across the whole life of the report: expected 2, got "
        f"{second_return['return_count']}"
    )
    assert second_return["reviewed_by_user_id"] is None, (
        f"the reviewer is cleared again, got {second_return['reviewed_by_user_id']!r}"
    )
    assert second_return["claim_reference"] is None, (
        f"no claim was ever filed, got {second_return['claim_reference']!r}"
    )
    assert second_return["closure_note"] is None, (
        f"the report is not closed, got {second_return['closure_note']!r}"
    )

    reported, meta = validate_paginated(
        api.list_incident_reports(
            scenario["admin_headers"], {"contract_id": contract_id, "status": "REPORTED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one REPORTED incident on this site, got {meta['total_count']}"
    )
    assert [item["id"] for item in reported] == [report_id], (
        f"expected the returned report to be listed as REPORTED, got {reported}"
    )


# ==========================================================================
# Staffing assignment — losing the lead puts the session at risk
# ==========================================================================
def test_releasing_the_lead_puts_the_session_back_at_risk(api):
    """PRD §3.5: "Release **compensates** the committed-minutes ledger: the
    assignment's `paid_minutes` is subtracted from the staff member's
    `committed_minutes_current_period` — except when the assignment was already
    in `VACANT_NEEDS_COVER`, because vacating it already performed that
    subtraction and doing it twice would corrupt the invariant."

    PRD §3.5: "When the released assignment was the `LEAD` and the session is in
    `SCHEDULED` or `STAFFED`, the session moves to `STAFFING_AT_RISK` and the
    offering's `coverage_gap_count` increments by 1."

    PRD §3.5: "A `cancel_reason` of `NO_COVER` moves the session from
    `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK` to `CANCELLED_NO_COVER`, and
    additionally requires that the session genuinely has no cover: no assignment
    of it may have `role_on_session` of `LEAD` in `ASSIGNED` or `CONFIRMED`
    status."

    PRD §3.5: "On a `COST_PLUS` contract the penalty is always 0, because the
    client is already bearing actual cost."

    Design: Corner/state_machines/releasing_the_lead_puts_the_session_back_at_risk
    """
    scenario, session, assignment = scenarios.setup_staffed_session(
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
    )
    expected_paid = 55 + THRESHOLDS["LEAD_SETUP_MIN"]
    assert assignment["role_on_session"] == "LEAD", (
        f"this scenario releases the lead, got {assignment['role_on_session']}"
    )
    assert assignment["paid_minutes"] == expected_paid, (
        f"a LEAD on a 55-minute session is paid {expected_paid} minutes, got "
        f"{assignment['paid_minutes']}"
    )
    assert (
        scenarios.read_staff(scenario["instructor_id"])["committed_minutes_current_period"]
        == expected_paid
    ), f"expected {expected_paid} committed minutes while the lead is confirmed"
    assert session["status"] == "STAFFED", (
        f"expected STAFFED before the release, got {session['status']}"
    )

    released = validate_success(
        api.release_assignment(
            assignment["id"],
            {"reason": "Instructor reassigned to the wellness suite"},
            scenario["manager_headers"],
        )
    )
    assert released["status"] == "RELEASED", (
        f"expected RELEASED, got {released['status']}"
    )
    assert (
        scenarios.read_staff(scenario["instructor_id"])["committed_minutes_current_period"]
        == 0
    ), (
        f"the release must give back all {expected_paid} minutes: expected 0 committed "
        "minutes"
    )

    at_risk = scenarios.read_session(session["id"])
    assert at_risk["status"] == "STAFFING_AT_RISK", (
        f"losing the lead puts the session at risk: expected STAFFING_AT_RISK, got "
        f"{at_risk['status']}"
    )
    assert scenarios.read_offering(scenario["offering_id"])["coverage_gap_count"] == 1, (
        "the drop out of STAFFED increments the offering's coverage gap count once"
    )

    cancelled = validate_success(
        api.session_status_change(
            session["id"],
            {"action": "CANCEL", "cancel_reason": "NO_COVER"},
            scenario["manager_headers"],
        )
    )
    assert cancelled["status"] == "CANCELLED_NO_COVER", (
        "with no LEAD left in ASSIGNED or CONFIRMED status the uncovered cancellation is "
        f"allowed: expected CANCELLED_NO_COVER, got {cancelled['status']}"
    )
    assert cancelled["cancel_reason"] == "NO_COVER", (
        f"expected cancel_reason NO_COVER, got {cancelled['cancel_reason']!r}"
    )

    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["uncovered_session_count"] == 1, (
        "an uncovered cancellation is the one branch that counts against the operator: "
        f"expected 1, got {contract['uncovered_session_count']}"
    )
    assert contract["pending_penalty_cents"] == 0, (
        "a cost-plus site never accrues a coverage penalty: expected 0, got "
        f"{contract['pending_penalty_cents']}"
    )
