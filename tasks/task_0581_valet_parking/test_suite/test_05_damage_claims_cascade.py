"""Damage-claim adjudication: the depth-3 liability cascade, the independence of the two
ticket axes, the deny branch, and settle preconditions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_damage_claim_payload, make_attendant_headers,
)
from test_helpers.fixtures import setup_open_damage_claim, setup_retrieval_ready

SUP = TEST_USERS["supervisor_headers"]


def test_approve_disputes_ticket_and_zeros_net(api):
    """PRD §3.8: "Hop one: the linked ticket's `settlement_status` is moved to `DISPUTED` and
    its `net_charge_cents` is set to 0 — and because the two ticket axes are independent (§2.8),
    this applies whether the ticket was `UNSETTLED` or already `SETTLED`, and regardless of its
    `park_status`."

    Design: Difficulty/transitive_cascade/claim_approve_liability_suspends_attendant_closes_shift
    """
    env = setup_open_damage_claim(claimed_amount_cents=10000, with_active_shift=True)
    validate_success(api.approve_damage_claim(
        env["claim"]["id"], {"approved_liability_cents": 10000}, SUP), 200)
    ticket = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert ticket["settlement_status"] == "DISPUTED"
    assert ticket["net_charge_cents"] == 0


def test_approve_suspends_attendant_and_closes_shift(api):
    """PRD §3.8: "Hop two: the charged attendant's `total_liability_cents` is increased by the
    approved liability amount. Hop three: if that attendant's `total_liability_cents` has
    thereby reached or exceeded 10,000 cents, the attendant's `status` is flipped to
    `INACTIVE`, and as a further consequence every shift of that attendant currently in
    `ACTIVE` status is closed to `CLOSED`."

    Design: Difficulty/transitive_cascade/claim_approve_liability_suspends_attendant_closes_shift
    """
    env = setup_open_damage_claim(claimed_amount_cents=10000, with_active_shift=True)
    validate_success(api.approve_damage_claim(
        env["claim"]["id"], {"approved_liability_cents": 10000}, SUP), 200)
    attendant = validate_success(api.get_attendant(env["attendant"]["id"], SUP), 200)
    assert attendant["total_liability_cents"] == 10000
    assert attendant["status"] == "INACTIVE"
    shift = validate_success(api.get_shift(env["shift"]["id"], SUP), 200)
    assert shift["status"] == "CLOSED"


def test_park_and_settlement_axes_move_independently(api):
    """PRD §2.8: "The two move independently: a ticket that has been physically closed can still
    be moved to `DISPUTED` by a later damage-claim approval, and conversely a ticket can be
    disputed while still `PARKED`."
    PRD §3.6: "Marking ready advances `STAGING` to `READY`, records `ready_at`, and — as a
    cross-entity effect — flips the underlying ticket's `park_status` from `PARKED` to
    `RETRIEVED`".

    Design: Difficulty/non_linear_state_machine/ticket_park_and_settlement_axes_independent
    """
    env = setup_retrieval_ready()  # ticket park_status RETRIEVED, settlement still UNSETTLED
    a_id = env["attendant"]["id"]
    claim = validate_success(api.create_damage_claim(
        create_damage_claim_payload(env["ticket"]["id"], claimed_amount_cents=500),
        make_attendant_headers(a_id)), 201)
    validate_success(api.approve_damage_claim(
        claim["id"], {"approved_liability_cents": 500}, SUP), 200)
    ticket = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert ticket["park_status"] == "RETRIEVED"
    assert ticket["settlement_status"] == "DISPUTED"


def test_small_liability_keeps_attendant_active(api):
    """PRD §3.8: "Hop three: if that attendant's `total_liability_cents` has thereby reached or
    exceeded 10,000 cents, the attendant's `status` is flipped to `INACTIVE`".
    PRD §3.4: "An attendant's `status` starts `ACTIVE` and its `total_liability_cents` starts
    at 0; both are system-maintained, the status flipping to `INACTIVE` only through the
    liability mechanism of §3.8."

    Design: Difficulty/non_linear_state_machine/ticket_park_and_settlement_axes_independent
    """
    env = setup_retrieval_ready()
    a_id = env["attendant"]["id"]
    claim = validate_success(api.create_damage_claim(
        create_damage_claim_payload(env["ticket"]["id"], claimed_amount_cents=500),
        make_attendant_headers(a_id)), 201)
    validate_success(api.approve_damage_claim(
        claim["id"], {"approved_liability_cents": 500}, SUP), 200)
    attendant = validate_success(api.get_attendant(a_id, SUP), 200)
    assert attendant["total_liability_cents"] == 500
    assert attendant["status"] == "ACTIVE"


def test_deny_claim_leaves_ledger_unchanged(api):
    """PRD §3.8: "Denial advances `OPEN` to `DENIED` and has no ledger or ticket effect
    whatsoever."

    Design: Corner/state_machines/deny_claim_branch_no_ledger_change
    """
    env = setup_open_damage_claim(claimed_amount_cents=9000)
    claim = validate_success(api.deny_damage_claim(env["claim"]["id"], SUP), 200)
    assert claim["status"] == "DENIED"
    attendant = validate_success(api.get_attendant(env["attendant"]["id"], SUP), 200)
    assert attendant["total_liability_cents"] == 0
    ticket = validate_success(api.get_ticket(env["ticket"]["id"], SUP), 200)
    assert ticket["settlement_status"] == "UNSETTLED"


def test_settle_open_claim_rejected(api):
    """PRD §3.8: "a settle attempted on a claim not in `APPROVED` is rejected with
    `ERR_CLAIM_NOT_APPROVED`."

    Design: Corner/state_machines/settle_claim_not_approved_returns_error
    """
    env = setup_open_damage_claim(claimed_amount_cents=300)
    res = api.settle_damage_claim(env["claim"]["id"], SUP)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_APPROVED)
