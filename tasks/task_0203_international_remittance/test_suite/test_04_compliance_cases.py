"""Compliance-case workflow: the request-info/provide-info cycle, the case-decide
cascade onto the transfer, OCC version guarding, terminal lockdown, and the
sender-block side effect of a confirmed match.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_corridor, setup_sender, setup_recipient, add_sanctions_entry,
    setup_held_transfer_with_case, create_locked_quote, create_transfer_from_quote,
    decide_case_payload, provide_info_payload, create_quote_payload,
    ledger_entries_for, get_corridor, ledger_net,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── case cycle OPEN -> AWAITING_INFO -> OPEN (non-linear state machine) ─────

def test_request_provide_loop_returns_to_open(api):
    """PRD §3.5: "From `OPEN`, an officer may request more information, which moves
    the case to `AWAITING_INFO` and increments `info_request_count` by one; an agent
    then provides the requested information — optionally attaching a `note` — which
    returns the case to `OPEN`."

    Design: Difficulty/non_linear_state_machine/compliance_case_cycle_open_awaiting_open_loop
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case()
    awaiting = validate_success(api.request_info_compliance_case(case["id"], OFFICER), 200)
    assert awaiting["status"] == "AWAITING_INFO", awaiting["status"]
    back = validate_success(
        api.provide_info_compliance_case(case["id"], provide_info_payload("first"), AGENT), 200)
    assert back["status"] == "OPEN", back["status"]


def test_two_loops_set_info_request_count_to_two(api):
    """PRD §3.5: "This `OPEN` → `AWAITING_INFO` → `OPEN` loop may repeat any number of
    times, and `info_request_count` records how many times it has cycled."

    Design: Difficulty/non_linear_state_machine/compliance_case_cycle_open_awaiting_open_loop
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case()
    for note in ("first response", "second response"):
        validate_success(api.request_info_compliance_case(case["id"], OFFICER), 200)
        validate_success(
            api.provide_info_compliance_case(case["id"], provide_info_payload(note), AGENT), 200)
    after = validate_success(api.get_compliance_case(case["id"], OFFICER), 200)
    assert after["status"] == "OPEN", after["status"]
    assert after["info_request_count"] == 2, after["info_request_count"]


# ─── REJECT decide -> depth-3 compensating cascade (transitive cascade) ─────

def test_reject_case_bubbles_rejected_and_refunds_transfer(api):
    """PRD §3.5: "A `REJECT` decision sets the case `status` to `REJECTED` and bubbles
    `REJECTED` onto the transfer's `compliance_status`; furthermore, if the transfer is
    currently funded and still pending delivery, the rejection triggers the
    compensating refund chain (with reason `COMPLIANCE_REJECT`) that drives the
    transfer's `delivery_status` to `REFUNDED`."

    Design: Difficulty/transitive_cascade/compliance_reject_cascade_depth3_case_transfer_refund_ledger
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        send_principal_minor=50000)
    before = get_corridor(corridor["id"])
    assert before["reserved_minor"] == 50000, before["reserved_minor"]
    decided = validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("REJECT", case["version"]), OFFICER), 200)
    assert decided["status"] == "REJECTED", decided["status"]
    after_t = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after_t["compliance_status"] == "REJECTED", after_t["compliance_status"]
    assert after_t["delivery_status"] == "REFUNDED", after_t["delivery_status"]


def test_reject_cascade_restores_reservation_and_writes_fault_refund(api):
    """PRD §3.7: "For a `COMPLIANCE_REJECT` or a `DELIVERY_FAILED` — neither of which
    is the sender's fault — the fee is always fully reversed when it was charged:
    `fee_refunded_minor` equals `fee_minor` when `funding_status` is `FUNDED`."
    PRD §3.7: "When a refund actually moves money for a funded transfer, it restores
    the corridor: `reserved_minor` is decreased by `send_principal_minor`."

    Design: Difficulty/transitive_cascade/compliance_reject_cascade_depth3_case_transfer_refund_ledger
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        send_principal_minor=50000)
    validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("REJECT", case["version"]), OFFICER), 200)
    after_c = get_corridor(corridor["id"])
    assert after_c["reserved_minor"] == 0, after_c["reserved_minor"]
    data, _meta = validate_paginated_refunds(api, transfer["id"])
    assert data, "expected a refund for the rejected transfer"
    refund = data[0]
    assert refund["reason"] == "COMPLIANCE_REJECT", refund["reason"]
    assert refund["fee_refunded_minor"] == 799, refund["fee_refunded_minor"]
    assert refund["total_refunded_minor"] == 50799, refund["total_refunded_minor"]


def validate_paginated_refunds(api, transfer_id):
    return validate_paginated(api.list_refunds(AGENT, params={"transfer_id": transfer_id}))


# ─── funds-conservation invariant on the reject compensating path ───────────

def test_reject_path_ledger_nets_to_zero(api):
    """PRD §3.8: "A refunded transfer that travelled the compensating path has written
    four entries: the `SENDER_DEBIT` of negative principal-plus-fee, the `FEE_REVENUE`
    of positive fee, the `REFUND_CREDIT` of positive principal, and the `FEE_REVERSAL`
    of positive refunded fee; these net to exactly the difference between `fee_minor`
    and `fee_refunded_minor`."

    Design: Difficulty/compensating_invariant/refund_conserves_funds_ledger_nets_to_retained_fee
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        send_principal_minor=50000)
    validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("REJECT", case["version"]), OFFICER), 200)
    entries = ledger_entries_for(transfer["id"])
    # SENDER_DEBIT -50799, FEE_REVENUE +799, REFUND_CREDIT +50000, FEE_REVERSAL +799.
    # fee fully reversed on COMPLIANCE_REJECT -> net == fee_minor - fee_refunded == 0.
    assert ledger_net(entries) == 0, ledger_net(entries)


def test_reject_path_restores_reserved_to_zero(api):
    """PRD §3.7: "When a refund actually moves money for a funded transfer, it restores
    the corridor: `reserved_minor` is decreased by `send_principal_minor`."

    Design: Difficulty/compensating_invariant/refund_conserves_funds_ledger_nets_to_retained_fee
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        send_principal_minor=50000)
    validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("REJECT", case["version"]), OFFICER), 200)
    after = get_corridor(corridor["id"])
    assert after["reserved_minor"] == 0, after["reserved_minor"]


# ─── OCC stale version on decide (corner: cross-cutting) ────────────────────

def test_decide_with_stale_case_version_rejected(api):
    """PRD §2.10: "If the case's current `version` differs — for instance because a
    request-info / provide-info exchange legitimately advanced the case after the
    officer loaded its detail — the decision is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_decide_returns_412
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case()
    stale_version = case["version"]
    # A request-info/provide-info loop advances the case version beyond the captured one.
    validate_success(api.request_info_compliance_case(case["id"], OFFICER), 200)
    validate_success(
        api.provide_info_compliance_case(case["id"], provide_info_payload("info"), AGENT), 200)
    res = api.decide_compliance_case(
        case["id"], decide_case_payload("CLEAR", stale_version), OFFICER)
    validate_error(res, "ERR_STALE_VERSION")
    after_t = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after_t["compliance_status"] == "HELD", after_t["compliance_status"]


# ─── terminal-state lockdown on decide (corner: state_machines) ─────────────

def test_decide_already_cleared_case_rejected(api):
    """PRD §3.5: "A decision is allowed only from `OPEN` or `ESCALATED`; deciding a
    case in any other status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decide_terminal_compliance_case_returns_invalid_state
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case()
    cleared = validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("CLEAR", case["version"]), OFFICER), 200)
    assert cleared["status"] == "CLEARED", cleared["status"]
    res = api.decide_compliance_case(
        case["id"], decide_case_payload("CLEAR", cleared["version"]), OFFICER)
    validate_error(res, "ERR_INVALID_STATE")
    after_t = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after_t["compliance_status"] == "CLEARED", after_t["compliance_status"]


# ─── confirmed match blocks the sender (corner: errors) ─────────────────────

def test_rejected_self_match_blocks_sender_for_new_quote(api):
    """PRD §3.2: "A sender whose `status` is `BLOCKED` — a state reached only through a
    confirmed sanctions match — may not be the subject of new quotes or transfers; such
    attempts are rejected with `ERR_SENDER_BLOCKED`."

    Design: Corner/errors/blocked_sender_cannot_create_quote_returns_sender_blocked
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    add_sanctions_entry("Konstantin Volkov", "US")
    # Sender's own name/country matches the list -> SENDER-subject score 100 -> HELD.
    sender = setup_sender(kyc_tier="TIER1", full_name="Konstantin Volkov", country="US")
    recipient = setup_recipient(sender["id"], full_name="Clean Beneficiary", country="PH")
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    validate_success(api.fund_transfer(transfer["id"], AGENT), 200)
    validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    data, _meta = validate_paginated_cases(api, transfer["id"])
    case = data[0]
    validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("REJECT", case["version"]), OFFICER), 200)
    after_s = validate_success(api.get_sender(sender["id"], OFFICER), 200)
    assert after_s["status"] == "BLOCKED", after_s["status"]
    res = api.create_quote(create_quote_payload(
        corridor["id"], sender["id"], send_principal_minor=40000, payout_method="BANK"), AGENT)
    validate_error(res, "ERR_SENDER_BLOCKED")


def validate_paginated_cases(api, transfer_id):
    return validate_paginated(api.list_compliance_cases(OFFICER, params={"transfer_id": transfer_id}))
