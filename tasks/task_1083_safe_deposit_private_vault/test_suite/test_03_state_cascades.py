"""Cyclic state machines, branching forks, transitive cascades, and
compensating invariants (Difficulty queue A).
"""
from test_helpers import (
    validate_success, TEST_USERS,
)
from test_helpers import fixtures as X

ADMIN = TEST_USERS["vault_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / rental_delinquent_cure_cycle
# ---------------------------------------------------------------------------
def test_delinquent_rental_cures_to_active_on_full_payment(api):
    """PRD §3.5: "If, after applying, the balance reaches zero and the rental is
    `PAST_DUE` or `DELINQUENT`, the cure cascade fires: the rental returns to
    `ACTIVE`, `delinquent_since` is cleared to null, and — for a rental leaving
    `DELINQUENT` — the box cascades from `DELINQUENT` back to `RENTED`."

    Design: Difficulty/non_linear_state_machine/rental_delinquent_cure_cycle
    """
    ctx = X.setup_delinquent_rental(api)   # clock 2026-06-15, balance 26500, box DELINQUENT
    assert ctx["rental"]["status"] == "DELINQUENT"
    assert ctx["box"]["status"] == "DELINQUENT"
    X.pay_full_and_clear(api, ctx["rental"]["id"], 26500)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert rental["status"] == "ACTIVE"
    assert box["status"] == "RENTED"


def test_cure_clears_delinquent_since(api):
    """PRD §3.5: "the rental returns to `ACTIVE`, `delinquent_since` is cleared
    to null".

    Design: Difficulty/non_linear_state_machine/rental_delinquent_cure_cycle
    """
    ctx = X.setup_delinquent_rental(api)
    assert ctx["rental"]["delinquent_since"] is not None
    X.pay_full_and_clear(api, ctx["rental"]["id"], 26500)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    assert rental["status"] == "ACTIVE"
    assert rental["delinquent_since"] is None


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / drilling_order_branch_fork
# ---------------------------------------------------------------------------
def test_scheduled_drill_completes_and_abandons_rental(api):
    """PRD §3.9: "the order moves to `DRILLED` and stamps `drilled_at`; the
    proceeds waterfall is computed; the box moves from `DRILL_PENDING` to
    `DRILLED`; the (delinquent) rental moves to `ABANDONED`".

    Design: Difficulty/non_linear_state_machine/drilling_order_branch_fork
    """
    ctx = X.setup_scheduled_drilling(api)
    order = validate_success(
        api.complete_drilling_order(ctx["order"]["id"], {"proceeds_cents": 0}, ADMIN), 200)
    assert order["status"] == "DRILLED"
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    assert box["status"] == "DRILLED"
    assert rental["status"] == "ABANDONED"


def test_scheduled_drill_cancel_restores_box_to_delinquent(api):
    """PRD §3.9: "cancelling a `SCHEDULED` order restores the box from
    `DRILL_PENDING` back to `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/drilling_order_branch_fork
    """
    ctx = X.setup_scheduled_drilling(api)
    order = validate_success(api.cancel_drilling_order(ctx["order"]["id"], ADMIN), 200)
    assert order["status"] == "CANCELLED"
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    assert box["status"] == "DELINQUENT"
    assert rental["status"] == "DELINQUENT"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / drilling_complete_depth4_cascade
# ---------------------------------------------------------------------------
def test_drill_completion_revokes_active_grant(api):
    """PRD §3.9: "the box moves from `DRILL_PENDING` to `DRILLED`; the (delinquent)
    rental moves to `ABANDONED`; and every `ACTIVE` or `SUSPENDED` access grant
    on that rental is `REVOKED`."

    Design: Difficulty/transitive_cascade/drilling_complete_depth4_cascade
    """
    ctx = X.setup_scheduled_drilling(api, with_grant=True)
    order = validate_success(
        api.complete_drilling_order(ctx["order"]["id"], {"proceeds_cents": 0}, ADMIN), 200)
    assert order["status"] == "DRILLED"
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    grant = validate_success(api.get_access_grant(ctx["grant"]["id"], ADMIN), 200)
    assert box["status"] == "DRILLED"
    assert rental["status"] == "ABANDONED"
    assert grant["status"] == "REVOKED"


def test_drill_completion_revokes_suspended_grant(api):
    """PRD §3.9: "every `ACTIVE` or `SUSPENDED` access grant on that rental is
    `REVOKED`."

    Design: Difficulty/transitive_cascade/drilling_complete_depth4_cascade
    """
    ctx = X.setup_scheduled_drilling(api, with_grant=True, grant_suspended=True)
    assert ctx["grant"]["status"] == "SUSPENDED"
    validate_success(
        api.complete_drilling_order(ctx["order"]["id"], {"proceeds_cents": 0}, ADMIN), 200)
    grant = validate_success(api.get_access_grant(ctx["grant"]["id"], ADMIN), 200)
    assert grant["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / payment_cure_depth2_cascade
# ---------------------------------------------------------------------------
def test_payment_cure_cascades_box_back_to_rented(api):
    """PRD §3.5: "the cure cascade fires: the rental returns to `ACTIVE`,
    `delinquent_since` is cleared to null, and — for a rental leaving
    `DELINQUENT` — the box cascades from `DELINQUENT` back to `RENTED`."

    Design: Difficulty/transitive_cascade/payment_cure_depth2_cascade
    """
    ctx = X.setup_delinquent_rental(api)
    X.pay_full_and_clear(api, ctx["rental"]["id"], 26500)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert rental["status"] == "ACTIVE"
    assert box["status"] == "RENTED"


def test_partial_payment_does_not_cure_delinquency(api):
    """PRD §3.5: "If, after applying, the balance reaches zero and the rental is
    `PAST_DUE` or `DELINQUENT`, the cure cascade fires".

    Design: Difficulty/transitive_cascade/payment_cure_depth2_cascade
    """
    ctx = X.setup_delinquent_rental(api)   # balance 26500
    X.pay_full_and_clear(api, ctx["rental"]["id"], 26400)   # 100 short → no cure
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert rental["status"] == "DELINQUENT"
    assert box["status"] == "DELINQUENT"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / payment_reverse_restores_balance
# ---------------------------------------------------------------------------
def test_payment_reverse_restores_balance_and_reopens_invoice(api):
    """PRD §3.5: "A `CLEARED` payment may be **reversed** by a `VaultAdmin`: the
    previously applied amount is removed from its invoices, any invoice that had
    gone `PAID` reverts to `OPEN`, and the rental's `balance_due_cents` is
    increased back by the applied amount."

    Design: Difficulty/compensating_invariant/payment_reverse_restores_balance
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    payment = X.pay_full_and_clear(api, rental_id, 24000)
    reversed_pay = validate_success(api.reverse_payment(payment["id"], ADMIN), 200)
    assert reversed_pay["status"] == "REVERSED"
    rental = validate_success(api.get_rental(rental_id, ADMIN), 200)
    assert rental["balance_due_cents"] == 24000
    inv = X.get_first_invoice(api, rental_id)
    assert inv["status"] == "OPEN"


def test_payment_clear_zeroes_balance_and_pays_invoice(api):
    """PRD §3.5: "any invoice thereby fully covered flips to `PAID`; the rental's
    `balance_due_cents` is reduced by the applied amount".

    Design: Difficulty/compensating_invariant/payment_reverse_restores_balance
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    X.pay_full_and_clear(api, rental_id, 24000)
    rental = validate_success(api.get_rental(rental_id, ADMIN), 200)
    assert rental["balance_due_cents"] == 0
    inv = X.get_first_invoice(api, rental_id)
    assert inv["status"] == "PAID"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / activate_close_box_occupancy_conserved
# ---------------------------------------------------------------------------
def test_close_returns_box_and_restores_zero_occupancy(api):
    """PRD §3.6: "Closing also cascades: the box returns to `AVAILABLE`, every
    `ACTIVE` or `SUSPENDED` access grant on the rental is `REVOKED`, and every
    non-`RELEASED` inventory item on the rental is `RELEASED`."

    Design: Difficulty/compensating_invariant/activate_close_box_occupancy_conserved
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    branch_id = ctx["branch"]["id"]
    X.pay_full_and_clear(api, rental_id, 24000)
    validate_success(api.request_surrender(rental_id, ADMIN), 200)
    data = validate_success(api.close_rental(rental_id, ADMIN), 200)
    assert data["status"] == "CLOSED"
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert box["status"] == "AVAILABLE"
    assert X.count_rented_boxes(api, branch_id) == 0


def test_activate_occupies_box_raising_rented_count(api):
    """PRD §3.3: "the rental transitions to `ACTIVE`, its `start_date` is set from
    the logical clock, the box cascades from `AVAILABLE` to `RENTED`".

    Design: Difficulty/compensating_invariant/activate_close_box_occupancy_conserved
    """
    ctx = X.setup_active_rental(api)
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert box["status"] == "RENTED"
    assert X.count_rented_boxes(api, ctx["branch"]["id"]) == 1
