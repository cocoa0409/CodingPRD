"""The billing dimension: self-serve refunds, the refund window, dispute
resolution cascades, and wallet conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_pro_headers,
    reset_clock, set_clock,
    create_dispute_payload,
    setup_distributed_lead,
)

ADMIN = TEST_USERS["admin_headers"]
CS = TEST_USERS["cs_headers"]


def test_refund_at_exact_window_boundary_is_closed(api):
    """PRD 3.7: "This is allowed only while the logical clock is strictly earlier
    than the lead's distributed_at plus the category's refund_window_hours; a
    request at or after that deadline is rejected with ERR_REFUND_WINDOW_CLOSED."

    Design: Difficulty/boundary_precision_check/refund_window_exact_hour_boundary_closed
    """
    ctx = setup_distributed_lead(api=api)  # distributed_at = 2026-03-01T00:00:00Z, window 24h
    set_clock("2026-03-02T00:00:00Z", api)  # exactly distributed_at + 24h
    resp = api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(ctx["pro"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_CLOSED)
    after = get_success_data(api.get_lead(ctx["lead"]["id"], ADMIN))
    assert after["billing_status"] == "CHARGED"


def test_refund_just_before_window_boundary_succeeds(api):
    """PRD 3.7: "Within the window, the lead's billing_status moves to REFUNDED,
    the pro's wallet is credited by the lead's charge_cents, and — if the lead
    had consumed a subscription credit — one credit is restored to
    remaining_lead_credits."

    Design: Difficulty/boundary_precision_check/refund_window_exact_hour_boundary_closed
    """
    ctx = setup_distributed_lead(api=api)
    set_clock("2026-03-01T23:59:59Z", api)  # strictly earlier than the 24h deadline
    lead = validate_success(
        api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(ctx["pro"]["id"]))
    )
    assert lead["billing_status"] == "REFUNDED"


def test_second_refund_reports_state_error_over_window_error(api):
    """PRD 2.9: "5. State — the target resource is in a state that permits the
    requested transition, else ERR_INVALID_STATE (409)."
    PRD 2.9: "9. Refund window — a refund request falls inside the category's
    refund window, else ERR_REFUND_WINDOW_CLOSED (409)."

    Design: Difficulty/priority_pair_validation_conflict/refund_state_beats_temporal_window
    """
    ctx = setup_distributed_lead(api=api)
    pid = ctx["pro"]["id"]
    get_success_data(api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(pid)))
    set_clock("2026-03-05T00:00:00Z", api)  # now also past the refund window
    resp = api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(pid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_second_refund_leaves_lead_refunded(api):
    """PRD 3.7: "The pro who owns a CHARGED lead may request a refund, optionally
    supplying a reason."

    Design: Difficulty/priority_pair_validation_conflict/refund_state_beats_temporal_window
    """
    ctx = setup_distributed_lead(api=api)
    pid = ctx["pro"]["id"]
    get_success_data(api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(pid)))
    set_clock("2026-03-05T00:00:00Z", api)
    api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(pid))
    after = get_success_data(api.get_lead(ctx["lead"]["id"], ADMIN))
    assert after["billing_status"] == "REFUNDED", "the already-refunded lead is unchanged"


def _resolved_refund_ctx(api):
    """A DISPUTED lead taken UNDER_REVIEW and resolved REFUND."""
    ctx = setup_distributed_lead(api=api)  # charge 5000, wallet 20000 -> 15000
    pid = ctx["pro"]["id"]
    dispute = get_success_data(
        api.create_dispute(create_dispute_payload(ctx["lead"]["id"], reason="OUT_OF_AREA"),
                           make_pro_headers(pid))
    )
    get_success_data(api.review_dispute(dispute["id"], CS))
    resolved = get_success_data(
        api.resolve_dispute(dispute["id"], {"decision": "REFUND", "resolution_note": "valid claim"}, CS)
    )
    ctx["dispute"] = resolved
    return ctx


def test_dispute_refund_resolution_sets_refund_amount(api):
    """PRD 3.7: "A decision of `REFUND` requires the disputed lead's
    `billing_status` to still be `DISPUTED`; it moves the dispute to
    `RESOLVED_REFUNDED`, sets the dispute's `refund_cents` to the disputed lead's
    `charge_cents`, and cascades the lead's `billing_status` from `DISPUTED` back
    to `REFUNDED` — crediting the pro's wallet by that `charge_cents` and
    restoring one subscription credit to `remaining_lead_credits` if the lead had
    consumed one."

    Design: Difficulty/transitive_cascade/dispute_resolve_refund_cascade_lead_and_wallet_depth2
    """
    ctx = _resolved_refund_ctx(api)
    assert ctx["dispute"]["status"] == "RESOLVED_REFUNDED"
    assert ctx["dispute"]["refund_cents"] == 5000


def test_dispute_refund_resolution_credits_wallet_and_refunds_lead(api):
    """PRD 3.7: "A decision of `REFUND` requires the disputed lead's
    `billing_status` to still be `DISPUTED`; it moves the dispute to
    `RESOLVED_REFUNDED`, sets the dispute's `refund_cents` to the disputed lead's
    `charge_cents`, and cascades the lead's `billing_status` from `DISPUTED` back
    to `REFUNDED` — crediting the pro's wallet by that `charge_cents` and
    restoring one subscription credit to `remaining_lead_credits` if the lead had
    consumed one."

    Design: Difficulty/transitive_cascade/dispute_resolve_refund_cascade_lead_and_wallet_depth2
    """
    ctx = _resolved_refund_ctx(api)
    lead = get_success_data(api.get_lead(ctx["lead"]["id"], ADMIN))
    pro = get_success_data(api.get_pro(ctx["pro"]["id"], ADMIN))
    assert lead["billing_status"] == "REFUNDED"
    assert pro["credit_balance_cents"] == 20000, "wallet 15000 credited back by charge 5000"


def test_dispute_on_refunded_lead_rejected(api):
    """PRD 3.7: "A dispute may only be raised on a lead whose billing_status is
    CHARGED; otherwise it is rejected with ERR_DISPUTE_NOT_ALLOWED."

    Design: Corner/validations/dispute_on_refunded_lead_returns_dispute_not_allowed
    """
    ctx = setup_distributed_lead(api=api)
    pid = ctx["pro"]["id"]
    get_success_data(api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(pid)))
    resp = api.create_dispute(create_dispute_payload(ctx["lead"]["id"], reason="DUPLICATE"),
                              make_pro_headers(pid))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_ALLOWED)


def test_resolve_dispute_before_review_returns_invalid_state(api):
    """PRD 3.7: "The same role then resolves an UNDER_REVIEW dispute by supplying
    a decision, optionally with a resolution_note."
    PRD 2.9: "State — the target resource is in a state that permits the
    requested transition, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/resolve_dispute_before_review_returns_invalid_state
    """
    ctx = setup_distributed_lead(api=api)
    pid = ctx["pro"]["id"]
    dispute = get_success_data(
        api.create_dispute(create_dispute_payload(ctx["lead"]["id"], reason="DUPLICATE"),
                           make_pro_headers(pid))
    )
    resp = api.resolve_dispute(dispute["id"], {"decision": "REFUND"}, CS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_distribution_debits_wallet_by_charge(api):
    """PRD 3.3: "For a PAY_PER_LEAD pro, charge_cents is the gross price,
    credits_consumed is 0, and credit_balance_cents is debited by that amount (a
    pro qualifies for funding only when the wallet already covers the gross price)."

    Design: Difficulty/compensating_invariant/pro_credit_cents_conserved_charge_then_refund
    """
    ctx = setup_distributed_lead(api=api)
    pro = get_success_data(api.get_pro(ctx["pro"]["id"], ADMIN))
    assert pro["credit_balance_cents"] == 15000, "wallet 20000 debited by charge 5000"


def test_refund_restores_wallet_exactly(api):
    """PRD 2.10: "When a charged lead is refunded — whether by the pro's
    self-serve request or by a dispute resolved in the pro's favor — the pro's
    wallet is credited by exactly that lead's charge_cents (pro-credit conservation)."

    Design: Difficulty/compensating_invariant/pro_credit_cents_conserved_charge_then_refund
    """
    ctx = setup_distributed_lead(api=api)
    pid = ctx["pro"]["id"]
    lead = validate_success(
        api.refund_request(ctx["lead"]["id"], {"reason": "DUPLICATE"}, make_pro_headers(pid))
    )
    assert lead["billing_status"] == "REFUNDED"
    pro = get_success_data(api.get_pro(pid, ADMIN))
    assert pro["credit_balance_cents"] == 20000, "charge fully restored, no drift"
