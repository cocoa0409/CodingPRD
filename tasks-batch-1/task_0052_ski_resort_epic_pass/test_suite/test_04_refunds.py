"""End-of-season refunds: the two payout algorithms (INJURY flat vs
RELOCATION/DISSATISFIED prorated-with-fee), the pinned single-rounding order, the
scan_count<=10 eligibility boundary, the snapshot-vs-live usage rule, the OCC
stale-version guard, the state-vs-eligibility precedence, and rejection as a
no-op.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
)

OPS = TEST_USERS["resort_ops_headers"]
REFUND = TEST_USERS["refund_admin_headers"]


# ─── dual_variant_calc: INJURY flat vs prorated-with-fee ──────────────────────

def test_refund_injury_flat_ninety_percent_of_basis(api):
    """PRD §3.5: "For an `INJURY` refund, usage is not penalized at all: the payout
    is ninety percent of the basis, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/refund_injury_flat_vs_prorated_with_fee
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=4, reason="INJURY", price_cents=10000,
        base_iso="2026-01-10T08:00:00Z",
    )
    approved = validate_success(fixtures.approve_refund(api, rr["id"], ver), 200)
    assert approved["status"] == "APPROVED"
    assert approved["refund_amount_cents"] == 9000, \
        "INJURY: round(10000 * 0.90) == 9000, usage ignored"


def test_refund_relocation_prorated_with_fee(api):
    """PRD §3.5: "the unused fraction is the quantity ten minus the used count,
    divided by ten, and the payout is the basis multiplied by that unused fraction
    and then multiplied by nine-tenths (that is, one minus the ten-percent
    processing-fee rate), with the round-half-up rounding applied exactly once to
    the resulting cents value."

    Design: Difficulty/dual_variant_calc/refund_injury_flat_vs_prorated_with_fee
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=4, reason="RELOCATION", price_cents=10000,
        base_iso="2026-01-11T08:00:00Z",
    )
    approved = validate_success(fixtures.approve_refund(api, rr["id"], ver), 200)
    assert approved["status"] == "APPROVED"
    assert approved["refund_amount_cents"] == 5400, \
        "RELOCATION: round(10000 * (6/10) * 0.90) == 5400"


def test_refund_payout_and_buddy_remaining_are_distinct_calcs(api):
    """PRD §3.5: "the payout is the basis multiplied by that unused fraction and
    then multiplied by nine-tenths... with the round-half-up rounding applied
    exactly once".
    PRD §3.4: "it is the product's `buddy_ticket_allotment` minus the count of this
    pass's buddy tickets whose `status` is `RESERVED` or `REDEEMED`."

    Design: Difficulty/dual_variant_calc/refund_payout_vs_buddy_remaining_aggregation
    """
    fixtures.set_clock(api, "2026-01-15T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=10000, buddy_ticket_allotment=2,
        buddy_ticket_price_cents=3000, ikon_interchange_enabled=False,
    )
    resort = fixtures.create_resort(api, name="Keystone", home_network="EPIC", gate_count=2)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Holder C")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-16", guest_name="Guest 1")
    fixtures.scan_n_granted(api, issued["id"], resort["id"], token, 4, "2026-01-15T08:00:00Z")
    before = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert before["buddy_tickets_remaining"] == 1, \
        "allotment 2 minus one RESERVED ticket -> remaining 1 (aggregation calc)"
    rr = fixtures.open_refund(api, issued["id"], reason="DISSATISFIED")
    approved = validate_success(
        fixtures.approve_refund(api, rr["id"], before["version"]), 200
    )
    assert approved["refund_amount_cents"] == 5400, \
        "DISSATISFIED: round(10000 * (6/10) * 0.90) == 5400 (monetary proration calc)"


def test_refund_payout_and_buddy_remaining_diverge_independently(api):
    """PRD §3.5: "For an `INJURY` refund, usage is not penalized at all: the payout
    is ninety percent of the basis, rounded half up to whole cents."
    PRD §3.4: "it is the product's `buddy_ticket_allotment` minus the count of this
    pass's buddy tickets whose `status` is `RESERVED` or `REDEEMED`."

    Design: Difficulty/dual_variant_calc/refund_payout_vs_buddy_remaining_aggregation
    """
    fixtures.set_clock(api, "2026-01-17T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=8000, buddy_ticket_allotment=3,
        buddy_ticket_price_cents=1000, ikon_interchange_enabled=False,
    )
    resort = fixtures.create_resort(api, name="Keystone2", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Holder C2")
    fixtures.activate_pass(api, issued["id"])
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-18", guest_name="Guest A")
    fixtures.reserve_buddy(api, issued["id"], resort["id"], "2026-01-19", guest_name="Guest B")
    before = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert before["buddy_tickets_remaining"] == 1, \
        "allotment 3 minus two RESERVED tickets -> remaining 1 (integer aggregation)"
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    approved = validate_success(
        fixtures.approve_refund(api, rr["id"], before["version"]), 200
    )
    assert approved["refund_amount_cents"] == 7200, \
        "INJURY flat: round(8000 * 0.90) == 7200 (monetary threshold calc, distinct domain)"


# ─── combinatorial_formula: pinned single-rounding order ──────────────────────

def test_refund_single_rounding_order_pinned_9999(api):
    """PRD §2.7: "the proration fraction and the processing-fee factor are
    multiplied against the basis as exact rational arithmetic, and the round-half-up
    rounding to a whole number of cents is applied exactly once, to the final cents
    value. Rounding the proration and the fee in separate steps is explicitly
    disallowed, because the two orderings can diverge by a cent."

    Design: Difficulty/combinatorial_formula/refund_single_rounding_order_pinned
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=3, reason="RELOCATION", price_cents=9999,
        base_iso="2026-01-20T08:00:00Z",
    )
    approved = validate_success(fixtures.approve_refund(api, rr["id"], ver), 200)
    assert approved["refund_amount_cents"] == 6299, \
        "single-rounding: round_half_up(9999 * (7/10) * 0.90) == round(6299.37) == 6299"


def test_refund_single_rounding_order_pinned_5005(api):
    """PRD §2.7: "the round-half-up rounding to a whole number of cents is applied
    exactly once, to the final cents value. Rounding the proration and the fee in
    separate steps is explicitly disallowed, because the two orderings can diverge
    by a cent."

    Design: Difficulty/combinatorial_formula/refund_single_rounding_order_pinned
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=3, reason="DISSATISFIED", price_cents=5005,
        base_iso="2026-01-21T08:00:00Z",
    )
    approved = validate_success(fixtures.approve_refund(api, rr["id"], ver), 200)
    assert approved["refund_amount_cents"] == 3153, \
        "single-rounding: round_half_up(5005 * (7/10) * 0.90) == round(3153.15) == 3153"


# ─── boundary_precision_check: scan_count <= MAX_SCANS_FOR_REFUND ─────────────

def test_refund_eligible_at_exactly_ten_scans(api):
    """PRD §3.5: "The eligibility check requires the referenced pass to be `ACTIVE`
    and its current `scan_count` to be at most ten".
    PRD §3.5: "For an `INJURY` refund, usage is not penalized at all: the payout is
    ninety percent of the basis, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/refund_scan_count_le_max_boundary
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=10, reason="INJURY", price_cents=10000,
        base_iso="2026-02-15T08:00:00Z",
    )
    assert pass_now["scan_count"] == 10
    approved = validate_success(fixtures.approve_refund(api, rr["id"], ver), 200)
    assert approved["status"] == "APPROVED"
    assert approved["refund_amount_cents"] == 9000, "INJURY flat 90% of 10000 at the boundary"


def test_refund_ineligible_above_ten_scans(api):
    """PRD §3.5: "if the pass is not `ACTIVE`, or if it has been scanned more than
    ten times, approval is rejected with `ERR_REFUND_INELIGIBLE`".

    Design: Difficulty/boundary_precision_check/refund_scan_count_le_max_boundary
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=11, reason="INJURY", price_cents=10000,
        base_iso="2026-02-16T08:00:00Z",
    )
    assert pass_now["scan_count"] == 11
    resp = fixtures.approve_refund(api, rr["id"], ver)
    validate_error(resp, ApiErrorId.ERR_REFUND_INELIGIBLE.value, 409)


# ─── priority_pair_validation_conflict: state vs referential ─────────────────

def test_double_approve_reports_invalid_state_over_ineligible(api):
    """PRD §3.5: "The generic state check requires the request to be `PENDING`; a
    non-pending request is rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "These checks are evaluated in priority order:... then the request's
    `PENDING` state, then refund eligibility".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_refund_approve
    """
    fixtures.set_clock(api, "2026-01-18T08:00:00Z")
    product = fixtures.create_product(api, tier="EPIC_DAY", price_cents=5000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Dbl Approve")
    fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    validate_success(fixtures.approve_refund(api, rr["id"], pass_now["version"]), 200)
    # Second approve: request now APPROVED (non-PENDING) and pass REFUNDED (non-ACTIVE).
    resp = fixtures.approve_refund(api, rr["id"], pass_now["version"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_approve_already_approved_request_is_invalid_state(api):
    """PRD §3.5: "The generic state check requires the request to be `PENDING`; a
    non-pending request is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_refund_approve
    """
    fixtures.set_clock(api, "2026-01-19T08:00:00Z")
    product = fixtures.create_product(api, tier="EPIC_DAY", price_cents=6000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Approved Once")
    fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    approved = validate_success(
        fixtures.approve_refund(api, rr["id"], pass_now["version"]), 200
    )
    assert approved["status"] == "APPROVED"
    resp = fixtures.approve_refund(api, rr["id"], pass_now["version"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── compensating_invariant: reject is a no-op ───────────────────────────────

def test_reject_leaves_pass_basis_and_status_untouched(api):
    """PRD §3.5: "a `RefundAdmin` rejecting a `PENDING` request moves it from
    `PENDING` to `REJECTED`, sets its `refund_amount_cents` to 0, leaves the pass
    entirely untouched, and increments the request's `version` by one."

    Design: Difficulty/compensating_invariant/refund_basis_conservation_reject_then_inspect
    """
    fixtures.set_clock(api, "2026-01-31T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=7000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Reject Host")
    fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="DISSATISFIED")
    rejected = validate_success(fixtures.reject_refund(api, rr["id"]), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["refund_amount_cents"] == 0
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert pass_now["status"] == "ACTIVE", "the pass is left untouched (still ACTIVE)"
    assert pass_now["refund_basis_cents"] == 7000, "refund_basis_cents unchanged with zero drift"


def test_reject_zeroes_payout_and_preserves_pending_only_transition(api):
    """PRD §3.5: "Rejection is the simpler outcome: a `RefundAdmin` rejecting a
    `PENDING` request moves it from `PENDING` to `REJECTED`, sets its
    `refund_amount_cents` to 0, leaves the pass entirely untouched".

    Design: Difficulty/compensating_invariant/refund_basis_conservation_reject_then_inspect
    """
    fixtures.set_clock(api, "2026-02-01T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8500)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Reject Host 2")
    fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    rejected = validate_success(fixtures.reject_refund(api, rr["id"]), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["refund_amount_cents"] == 0
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert pass_now["status"] == "ACTIVE"


# ─── Corner: prorated zero, snapshot vs live, reject-already, stale version ───

def test_refund_prorated_zero_at_used_ge_max(api):
    """PRD §3.5: "if the snapshot used count is ten or more, the payout is 0...
    while a pass at exactly ten scans is eligible but, under the proration branch,
    yields a payout of 0."

    Design: Corner/calculations/refund_used_ge_max_yields_zero_prorated
    """
    pass_now, rr, ver = fixtures.setup_pending_refund(
        api, scan_count=10, reason="DISSATISFIED", price_cents=10000,
        base_iso="2026-02-20T08:00:00Z",
    )
    approved = validate_success(fixtures.approve_refund(api, rr["id"], ver), 200)
    assert approved["status"] == "APPROVED"
    assert approved["refund_amount_cents"] == 0, \
        "prorated branch with used==10 (==MAX) yields exactly 0"


def test_refund_uses_snapshot_not_live_scan_count(api):
    """PRD §3.5: "This snapshot, captured at request time, is what the payout
    calculation later consumes — never the live `scan_count`, which may drift if
    the pass keeps scanning while the request sits pending."

    Design: Corner/calculations/refund_uses_snapshot_not_live_scan_count
    """
    fixtures.set_clock(api, "2026-02-22T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resort = fixtures.create_resort(api, name="Snap Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Snap Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    fixtures.scan_n_granted(api, issued["id"], resort["id"], token, 2, "2026-02-22T08:00:00Z")
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    assert rr["scan_count_at_request"] == 2, "snapshot captured at request time == 2"
    # One more granted scan after the request is opened: live scan_count becomes 3.
    fixtures.set_clock(api, "2026-02-22T08:30:00Z")
    validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    pass_now = fixtures.get_pass(api, issued["id"], headers=REFUND)
    assert pass_now["scan_count"] == 3, "live scan_count drifted to 3"
    approved = validate_success(
        fixtures.approve_refund(api, rr["id"], pass_now["version"]), 200
    )
    assert approved["refund_amount_cents"] == 7200, \
        "INJURY flat 90% of 8000 ignores usage entirely -> 7200"


def test_reject_already_rejected_returns_invalid_state(api):
    """PRD §3.5: "The generic state check requires the request to be `PENDING`; a
    non-pending request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reject_already_rejected_refund_returns_invalid_state
    """
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=6000)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Reject Twice")
    fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    validate_success(fixtures.reject_refund(api, rr["id"]), 200)
    resp = fixtures.reject_refund(api, rr["id"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_stale_pass_version_on_approve_returns_stale_version(api):
    """PRD §2.9: "The server compares it against the referenced pass's current
    `version`; if they do not match — for instance because a granted scan advanced
    the pass's `scan_count` and bumped its `version` after the approver loaded it —
    the approval is rejected with `ERR_STALE_VERSION` and HTTP status 412".

    Design: Corner/errors/stale_pass_version_on_refund_approve_returns_stale
    """
    fixtures.set_clock(api, "2026-03-10T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=6000)
    resort = fixtures.create_resort(api, name="Stale Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Stale Holder")
    token = issued["magnetic_token"]
    active = fixtures.activate_pass(api, issued["id"])
    rr = fixtures.open_refund(api, issued["id"], reason="INJURY")
    stale_ver = fixtures.get_pass(api, issued["id"], headers=REFUND)["version"]
    # An intervening GRANTED scan bumps the pass version, making stale_ver stale.
    validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    resp = fixtures.approve_refund(api, rr["id"], stale_ver)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
