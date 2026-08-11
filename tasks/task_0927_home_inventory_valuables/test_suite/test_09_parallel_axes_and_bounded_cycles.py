"""Two non-linear state machines: the subscription's two independent axes, and
the bounded denied/appealed/denied loop on a claim line."""
from test_helpers import (
    add_cataloged_item,
    add_claim_line,
    add_generated_package,
    add_policy,
    add_room,
    adjudicate,
    ApiErrorId,
    appeal,
    assert_same_instant,
    billing_event,
    bootstrap_household,
    make_platform_admin_headers,
    open_claim,
    set_clock,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = make_platform_admin_headers()

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}


def _setup_overdue_but_active_subscription():
    """A PLUS subscription created and activated at 2026-05-01, then observed at
    2027-06-01 — past `refresh_due_at` plus the 30-day grace, so the refresh axis
    has collapsed to OVERDUE while the billing axis is still ACTIVE."""
    ctx = bootstrap_household(tier="PLUS", activate=True)
    set_clock("2027-06-01T00:00:00Z")
    return ctx


def test_refresh_axis_reaches_overdue_while_the_billing_axis_moves_on_its_own(api):
    """PRD 3.2: "Running on the very same subscription row, and entirely
    independently of the billing axis, is `refresh_state`: a past-due subscription
    can be refresh-`CURRENT`, and an active subscription can be refresh-`OVERDUE`."
    PRD 3.2: "At 30 days after `refresh_due_at` and beyond, the state is
    `OVERDUE`."
    PRD 3.2: "From `ACTIVE`, a `PAYMENT_FAILED` outcome moves `ACTIVE → PAST_DUE`
    and stamps `past_due_since_at` with the current instant. A past-due household
    keeps **full** write access — `write_gate_state` does not change."

    Design: Difficulty/non_linear_state_machine/subscription_status_and_refresh_axes_move_independently
    """
    ctx = _setup_overdue_but_active_subscription()

    before = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert before["status"] == "ACTIVE"
    assert before["refresh_state"] == "OVERDUE"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "RESTRICTED"

    after = validate_success(
        api.billing_event(
            ctx["subscription_id"],
            {"outcome": "PAYMENT_FAILED"},
            ADMIN_HEADERS,
        )
    )
    assert after["status"] == "PAST_DUE"
    assert after["refresh_state"] == "OVERDUE", (
        "a billing-axis move must leave the refresh axis exactly where it was"
    )
    assert_same_instant(
        after["past_due_since_at"], "2027-06-01T00:00:00Z", "past_due_since_at"
    )


def test_attestation_resets_the_refresh_axis_without_touching_the_billing_axis(api):
    """PRD 3.2: "It stamps `last_attested_at` with the current instant, recomputes
    `refresh_due_at` as 365 days after that instant, and returns `refresh_state` to
    `CURRENT` — the four legal moves being `DUE → CURRENT`, `GRACE → CURRENT`,
    `OVERDUE → CURRENT` and the `CURRENT → CURRENT` self-loop of an early
    attestation."
    PRD 3.2: "From `OVERDUE` it additionally returns the household's
    `write_gate_state` to `OPEN`, unless `status` is `LAPSED`, in which case the
    household stays `READ_ONLY`."

    Design: Difficulty/non_linear_state_machine/subscription_status_and_refresh_axes_move_independently
    """
    ctx = _setup_overdue_but_active_subscription()
    billing_event(ctx, "PAYMENT_FAILED")

    attested = validate_success(
        api.attest_refresh(
            ctx["subscription_id"],
            {"attestation_note": "annual walkthrough done"},
            ctx["owner_headers"],
        )
    )
    assert attested["status"] == "PAST_DUE", (
        "attesting the refresh must not move the billing axis"
    )
    assert attested["refresh_state"] == "CURRENT"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "OPEN", (
        "a PAST_DUE household is not READ_ONLY, so clearing OVERDUE reopens the gate"
    )


def _setup_claim_with_one_approved_and_one_denied_line():
    """A submitted RCV claim over two PHOTO_SERIAL items; line A approved so the
    claim can never auto-deny, line B denied and ready to be appealed."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Den", floor_label="1")
    item_a = add_cataloged_item(
        ctx,
        room["id"],
        250000,
        photo_bytes=60000,
        name="Camera Body",
        category="GENERAL",
        acquired_at="2025-05-01T00:00:00Z",
        quantity=1,
        serial_number="GN-A1",
        replacement_cost_cents=300000,
    )
    item_b = add_cataloged_item(
        ctx,
        room["id"],
        180000,
        photo_bytes=60000,
        name="Zoom Lens",
        category="GENERAL",
        acquired_at="2025-06-01T00:00:00Z",
        quantity=1,
        serial_number="GN-B1",
        replacement_cost_cents=200000,
    )
    policy = add_policy(
        ctx, policy_number="NW-6006", deductible_cents=0, scheduled_allowance_cents=0
    )
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="FIRE",
        settlement_basis="RCV",
        deductible_mode="PRO_RATA",
    )
    line_a = add_claim_line(ctx, claim["id"], item_a["id"])
    line_b = add_claim_line(ctx, claim["id"], item_b["id"])
    submit_claim(ctx, claim["id"])
    adjudicate(line_a["id"], "APPROVE")
    adjudicate(line_b["id"], "DENY", "VALUE_DISPUTED")
    ctx.update(
        {
            "room": room,
            "item_a": item_a,
            "item_b": item_b,
            "policy": policy,
            "package": package,
            "claim": claim,
            "line_a": line_a,
            "line_b": line_b,
        }
    )
    return ctx


def test_third_appeal_on_a_line_is_refused_at_the_per_line_limit(api):
    """PRD 3.7: "The homeowner may appeal a denied line, optionally with an
    `appeal_note`, while the line's `appeal_count` is below the limit of 2 and the
    claim sits in `UNDER_REVIEW` or `SUPPLEMENT_REQUESTED`; at the limit the appeal
    is refused with `ERR_APPEAL_LIMIT_REACHED`."
    PRD 3.7: "An appeal moves the line `DENIED → APPEALED`, raises `appeal_count`
    by one, clears `denial_reason` back to null, and bubbles the claim
    `UNDER_REVIEW → SUPPLEMENT_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/claim_line_denied_appealed_denied_bounded_cycle
    """
    ctx = _setup_claim_with_one_approved_and_one_denied_line()
    line_b_id = ctx["line_b"]["id"]

    appeal(ctx, line_b_id, "receipt attached")
    adjudicate(line_b_id, "DENY", "VALUE_DISPUTED")
    appeal(ctx, line_b_id, "second receipt")
    adjudicate(line_b_id, "DENY", "VALUE_DISPUTED")

    response = api.appeal_claim_line(
        line_b_id, {"appeal_note": "third attempt"}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)

    line_b = validate_success(api.get_claim_line(line_b_id, ctx["owner_headers"]))
    assert line_b["appeal_count"] == 2, (
        f"appeal_count must settle at the limit of 2, got {line_b['appeal_count']}"
    )
    assert line_b["status"] == "DENIED"
    assert line_b["denial_reason"] == "VALUE_DISPUTED"


def test_claim_oscillates_between_under_review_and_supplement_requested(api):
    """PRD 3.7: "Adjudicating an appealed line sends it to `APPROVED` or back to
    `DENIED`, and once no line under the claim remains `APPEALED` the claim returns
    `SUPPLEMENT_REQUESTED → UNDER_REVIEW`. That is the cycle, and the per-line
    appeal limit is what bounds it."
    PRD 3.7: "Denying a line — `PENDING → DENIED` or `APPEALED → DENIED` — writes
    the `denial_reason`, forces `net_settlement_cents` to 0 and recomputes
    `denied_line_count`."

    Design: Difficulty/non_linear_state_machine/claim_line_denied_appealed_denied_bounded_cycle
    """
    ctx = _setup_claim_with_one_approved_and_one_denied_line()
    claim_id = ctx["claim"]["id"]
    line_b_id = ctx["line_b"]["id"]

    appeal(ctx, line_b_id, "receipt attached")
    mid = validate_success(api.get_claim(claim_id, ctx["owner_headers"]))
    assert mid["status"] == "SUPPLEMENT_REQUESTED"

    adjudicate(line_b_id, "DENY", "VALUE_DISPUTED")
    back = validate_success(api.get_claim(claim_id, ctx["owner_headers"]))
    assert back["status"] == "UNDER_REVIEW"

    appeal(ctx, line_b_id, "second receipt")
    adjudicate(line_b_id, "DENY", "VALUE_DISPUTED")

    final_claim = validate_success(api.get_claim(claim_id, ctx["owner_headers"]))
    line_a = validate_success(api.get_claim_line(ctx["line_a"]["id"], ctx["owner_headers"]))
    assert line_a["status"] == "APPROVED"
    assert final_claim["status"] == "UNDER_REVIEW"
    assert final_claim["denied_line_count"] == 1
    assert final_claim["approved_line_count"] == 1
