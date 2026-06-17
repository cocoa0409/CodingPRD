"""Booking, contract, and payment lifecycle: transitions, cycles, parallel
state dimensions, and cross-entity gating.

Covers Difficulty rules non_linear_state_machine and cross_entity_state_dependency,
plus the corner state_machines section. PRD §3.3, §3.5, §3.6, §3.7, §3.8.
"""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, fixtures as fx
from test_helpers.test_users import make_client_headers

AGENT = fx.AGENT
ADMIN = fx.ADMIN


# =====================================================================
# Difficulty/non_linear_state_machine
# =====================================================================
def test_negotiation_cycle_declines_revision1_and_issues_revision2(api):
    """PRD §3.5: "Requesting a revision moves the booking from `CONTRACT_SENT` to
    `NEGOTIATING` and cascades the current contract's `status` to `DECLINED`."
    PRD §3.5: "Re-issuing carries an `expected_booking_version` matching the
    booking's current `version`, supersedes any still-`ISSUED` contract on the booking
    by moving its `status` to `SUPERSEDED`, creates a fresh `ContractDocument` whose
    `revision` is one greater than the highest revision yet seen on the booking, with
    `status` `ISSUED` and `quoted_total_cents` snapshotting the current quote, and
    returns the booking to `CONTRACT_SENT`."

    Per PRD the request-revision step already moves revision 1 to DECLINED, so by the
    time the agent re-issues there is no still-`ISSUED` contract left to supersede;
    revision 1 therefore ends terminal as DECLINED and revision 2 is the fresh ISSUED
    contract.

    Design: Difficulty/non_linear_state_machine/booking_negotiation_cycle_contract_sent_negotiating_contract_sent
    """
    cat, bk, ct1_id = fx.create_contract_sent_booking(contracted_set_minutes=120)
    revision_resp = api.request_revision(bk["id"], make_client_headers(cat["cli_id"]))
    negotiating = validate_success(revision_resp)
    assert negotiating["status"] == "NEGOTIATING"

    reissue = api.issue_contract(bk["id"], negotiating["version"], AGENT)
    reissued = validate_success(reissue)
    assert reissued["status"] == "CONTRACT_SENT"

    contracts = validate_success(api.list_contracts(bk["id"], AGENT))
    by_rev = {c["revision"]: c for c in contracts}
    assert by_rev[1]["status"] == "DECLINED", by_rev[1]
    assert by_rev[2]["status"] == "ISSUED", by_rev[2]


def test_negotiation_cycle_can_repeat_to_revision_three(api):
    """PRD §3.5: "This `CONTRACT_SENT → NEGOTIATING → CONTRACT_SENT` cycle may repeat
    as many times as the client and agent need."
    PRD §3.5: "creates a fresh `ContractDocument` whose `revision` is one greater than
    the highest revision yet seen on the booking, with `status` `ISSUED`"

    Design: Difficulty/non_linear_state_machine/booking_negotiation_cycle_contract_sent_negotiating_contract_sent
    """
    cat, bk, ct1_id = fx.create_contract_sent_booking(contracted_set_minutes=120)
    # cycle 1
    neg1 = validate_success(api.request_revision(bk["id"], make_client_headers(cat["cli_id"])))
    re1 = validate_success(api.issue_contract(bk["id"], neg1["version"], AGENT))
    # cycle 2
    neg2 = validate_success(api.request_revision(bk["id"], make_client_headers(cat["cli_id"])))
    re2 = validate_success(api.issue_contract(bk["id"], neg2["version"], AGENT))
    assert re2["status"] == "CONTRACT_SENT"

    contracts = validate_success(api.list_contracts(bk["id"], AGENT))
    revisions = sorted(c["revision"] for c in contracts)
    assert revisions == [1, 2, 3], revisions
    by_rev = {c["revision"]: c for c in contracts}
    assert by_rev[3]["status"] == "ISSUED", by_rev[3]


def test_payment_capture_and_settlement_dimensions_evolve_independently(api):
    """PRD §3.6: "A new payment record begins with a `capture_status` of `AUTHORIZED`
    and a `settlement_status` of `UNSETTLED`."
    PRD §3.8: "Settling marks every captured payment on the booking that is still
    `UNSETTLED` as `SETTLED`, and moves the booking from `PERFORMED` to its terminal
    `SETTLED` state."

    Design: Difficulty/non_linear_state_machine/payment_parallel_dimensions_capture_vs_settlement_evolve_independently
    """
    cat = fx.setup_home_catalogue()
    cat2, settled, payments = fx.create_settled_booking(cat, quote_cents=250000,
                                                        deposit_cents=62500,
                                                        contracted_set_minutes=120)
    dep = payments[0]
    dep_now = validate_success(api.get_payment(dep["id"], AGENT))

    assert dep_now["capture_status"] == "CAPTURED", dep_now["capture_status"]
    assert dep_now["settlement_status"] == "SETTLED", dep_now["settlement_status"]
    assert settled["status"] == "SETTLED"


def test_captured_payment_stays_unsettled_before_settle(api):
    """PRD §3.6: "The `settlement_status` dimension evolves independently of capture. A
    captured payment stays `UNSETTLED` until either a cancellation routes it to
    `REFUNDED` or a settlement marks it `SETTLED`; a captured payment can therefore be
    `UNSETTLED` and only later become `REFUNDED`."

    Design: Difficulty/non_linear_state_machine/payment_parallel_dimensions_capture_vs_settlement_evolve_independently
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    dep = fx.create_payment(held["id"], kind="DEPOSIT", amount_cents=62500)
    captured = validate_success(api.capture_payment(dep["id"], AGENT))

    assert captured["capture_status"] == "CAPTURED", captured["capture_status"]
    assert captured["settlement_status"] == "UNSETTLED", captured["settlement_status"]


# =====================================================================
# Difficulty/cross_entity_state_dependency
# =====================================================================
def test_hold_rejected_when_performer_inactive(api):
    """PRD §3.3: "The booked performer's `availability_status` must be either
    `AVAILABLE` or `ON_HOLD` for the hold to proceed."
    PRD §3.2: "an administrator may force it to `INACTIVE` by deactivating the
    performer, removing them from the bookable roster."

    Design: Difficulty/cross_entity_state_dependency/hold_requires_performer_not_inactive_booking_vs_performer
    """
    cat = fx.setup_home_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    fx.get_success_data(api.deactivate_performer(cat["perf_id"], ADMIN))

    resp = api.hold_booking(bk["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_booking(bk["id"], AGENT))
    assert after["status"] == "INQUIRY"


def test_capture_deposit_does_not_confirm_while_contract_only_issued(api):
    """PRD §3.6: "When a `DEPOSIT` payment is captured against a booking that is in
    `CONTRACT_SENT` with a `SIGNED` contract, and the cumulative captured deposit
    amount for the booking reaches or exceeds `deposit_required_cents`, the system
    automatically advances the booking from `CONTRACT_SENT` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_contract_signed_booking_vs_contract
    """
    cat, bk, ct_id = fx.create_contract_sent_booking(contracted_set_minutes=120)
    # contract is ISSUED, NOT signed
    dep = fx.create_payment(bk["id"], kind="DEPOSIT", amount_cents=62500)
    resp = api.capture_payment(dep["id"], AGENT)
    captured = validate_success(resp)

    after = validate_success(api.get_booking(bk["id"], AGENT))
    assert after["status"] == "CONTRACT_SENT", after["status"]
    assert captured["capture_status"] == "CAPTURED"


def test_hold_succeeds_when_performer_available(api):
    """PRD §3.3: "The booked performer's `availability_status` must be either
    `AVAILABLE` or `ON_HOLD` for the hold to proceed."

    Design: Difficulty/cross_entity_state_dependency/hold_requires_performer_not_inactive_booking_vs_performer
    """
    cat = fx.setup_home_catalogue()
    perf = validate_success(api.get_performer(cat["perf_id"], AGENT))
    assert perf["availability_status"] == "AVAILABLE"
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    held = validate_success(api.hold_booking(bk["id"], AGENT))
    assert held["status"] == "HOLD", held["status"]


def test_capture_deposit_confirms_when_contract_signed(api):
    """PRD §3.6: "When a `DEPOSIT` payment is captured against a booking that is in
    `CONTRACT_SENT` with a `SIGNED` contract, and the cumulative captured deposit
    amount for the booking reaches or exceeds `deposit_required_cents`, the system
    automatically advances the booking from `CONTRACT_SENT` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_contract_signed_booking_vs_contract
    """
    cat, bk, ct_id = fx.create_signed_contract_booking(contracted_set_minutes=120)
    dep = fx.create_payment(bk["id"], kind="DEPOSIT", amount_cents=62500)
    fx.capture_payment(dep["id"])
    after = validate_success(api.get_booking(bk["id"], AGENT))
    assert after["status"] == "CONFIRMED", after["status"]


# =====================================================================
# Corner/state_machines
# =====================================================================
def test_hold_from_inquiry_moves_booking_and_performer(api):
    """PRD §3.3: "When all of these pass, the hold computes the provisional grand
    total (described in 3.4), derives the required deposit, sets `balance_due_cents`
    to the quote total minus whatever has already been paid, records
    `active_performer_id` as the originally booked `performer_id`, moves the
    performer's `availability_status` to `ON_HOLD`, and transitions the booking from
    `INQUIRY` to `HOLD`."

    Design: Corner/state_machines/hold_from_inquiry_valid_transition
    """
    cat = fx.setup_home_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.hold_booking(bk["id"], AGENT)
    held = validate_success(resp)

    assert held["status"] == "HOLD"
    assert held["quote_total_cents"] == 250000, held["quote_total_cents"]

    perf = validate_success(api.get_performer(cat["perf_id"], AGENT))
    assert perf["availability_status"] == "ON_HOLD"


def test_hold_again_from_hold_rejected(api):
    """PRD §3.3: "A hold is only legal from `INQUIRY`."

    Design: Corner/state_machines/hold_from_already_held_returns_invalid_state
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    resp = api.hold_booking(held["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_from_settled_terminal_rejected(api):
    """PRD §3.8: "Settling marks every captured payment on the booking that is still
    `UNSETTLED` as `SETTLED`, and moves the booking from `PERFORMED` to its terminal
    `SETTLED` state."
    PRD §3.9: "A booking may be cancelled from `HOLD`, `CONTRACT_SENT`, `NEGOTIATING`,
    or `CONFIRMED`, by either the booking agent or the owning client."

    Design: Corner/state_machines/cancel_from_settled_terminal_rejected
    """
    cat, settled, payments = fx.create_settled_booking(quote_cents=250000,
                                                       deposit_cents=62500,
                                                       contracted_set_minutes=120)
    resp = api.cancel_booking(settled["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_booking(settled["id"], AGENT))
    assert after["status"] == "SETTLED"


def test_decline_contract_from_issued_moves_to_declined(api):
    """PRD §3.5: "Alternatively, the client may decline the issued contract directly,
    moving its `status` to `DECLINED`; declining unlocks no deposit path."

    Design: Corner/state_machines/contract_decline_from_issued_branch_b
    """
    cat, bk, ct_id = fx.create_contract_sent_booking(contracted_set_minutes=120)
    resp = api.decline_contract(ct_id, make_client_headers(cat["cli_id"]))
    declined = validate_success(resp)

    assert declined["status"] == "DECLINED"


def test_void_captured_payment_rejected(api):
    """PRD §3.6: "Voiding is legal only while a payment is still `AUTHORIZED`;
    attempting to void a payment that is already `CAPTURED` or `VOID` is rejected with
    `ERR_PAYMENT_NOT_VOIDABLE` (HTTP 409)."

    Design: Corner/state_machines/void_captured_payment_rejected
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    dep = fx.create_payment(held["id"], kind="DEPOSIT", amount_cents=62500)
    fx.capture_payment(dep["id"])

    resp = api.void_payment(dep["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_VOIDABLE.value)


def test_decline_backup_drops_reliability_score_by_five(api):
    """PRD §3.11: "Declining is legal only while the assignment is `OFFERED` and only
    by the candidate; declining moves the assignment to `DECLINED` and decrements that
    performer's `reliability_score` by 5, floored at 0."

    Design: Corner/state_machines/backup_decline_drops_reliability_and_cycles
    """
    cat = fx.setup_home_catalogue()
    backup = fx.create_performer(cat["zhome_id"], stage_name="Backup", base_set_rate_cents=180000)
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500)
    ba = fx.offer_backup(confirmed["id"], backup["id"], rank=1)

    resp = api.decline_backup(ba["id"], fx.make_performer_headers(backup["id"]))
    declined = validate_success(resp)
    assert declined["status"] == "DECLINED"

    perf = validate_success(api.get_performer(backup["id"], AGENT))
    assert perf["reliability_score"] == 95, perf["reliability_score"]


def test_song_request_conflicts_with_existing_do_not_play(api):
    """PRD §3.10: "However, if a newly created `REQUEST` collides with an existing
    `DO_NOT_PLAY` entry on the same booking — meaning the two share the same title and
    artist when both are compared case-insensitively — the new request is recorded with
    `status` `CONFLICTED` instead of `ACCEPTED`."

    Design: Corner/state_machines/song_request_conflicts_with_do_not_play
    """
    cat = fx.setup_home_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    fx.add_song_request(bk["id"], cat["cli_id"], title="Mr Brightside",
                        artist="The Killers", list_type="DO_NOT_PLAY")

    resp = api.create_song_request(
        bk["id"],
        {"title": "Mr Brightside", "artist": "The Killers", "list_type": "REQUEST", "priority": 1},
        make_client_headers(cat["cli_id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CONFLICTED", data["status"]
