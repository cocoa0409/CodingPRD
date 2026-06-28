"""Refund computation, date outcomes, and the multi-level exit/flag cascades."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    ApiErrorId,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def _make_active_counterpart(plan_id, email):
    member, _ = fx.create_active_member(plan_id, email, gender="FEMALE",
                                        pref_overrides={"seeking_gender": "MALE"})
    return member


# ---------------------------------------------------------------------------
# Refund per-line rounding (dual_variant_calc + combinatorial_formula)
# ---------------------------------------------------------------------------
def test_refund_per_line_rounding_with_months_part(api):
    """PRD §3.9: "The coaching refund is computed by rounding the per-session rate half-up **for each** unused session line and then summing those rounded lines — this round-per-line-then-sum order is pinned and must not be replaced by rounding the product of the rate and the unused count." Worked: 5000/3=1666.6667, each line
    rounds to 1667, summed over 3 = 5001; months: floor(70/30)=2 elapsed months,
    remaining 6-2-1=3, at 12000 each = 36000; total 41001.

    Design: Difficulty/dual_variant_calc/refund_per_line_vs_sum_rounding_diverge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="ELITE", monthly_fee_cents=12000, term_months=6,
                          guaranteed_introductions=8, included_coaching_sessions=3,
                          coaching_value_cents=5000, background_check_addon_cents=2500)
    member, membership = fx.create_active_member(plan["id"], "c@x.com", with_preferences=False)
    fx.set_clock("2026-08-10T00:00:00Z")  # 70 days elapsed

    resp = api.cancel_membership(membership["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["refund_cents"] == 41001, (
        f"36000 months + 5001 coaching = 41001, got {data['refund_cents']}"
    )
    assert data["status"] == "CANCELLED", f"expected CANCELLED, got {data['status']}"


def test_refund_credited_to_member_wallet_on_cancel(api):
    """PRD §3.9: "it computes the refund, records it on the membership's `refund_cents`, moves the membership to `CANCELLED`, and credits the refund to the member's `wallet_credit_cents`." The 41001 refund (36000 months + 5001 per-line coaching)
    must appear in the member's wallet.

    Design: Difficulty/dual_variant_calc/refund_per_line_vs_sum_rounding_diverge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="ELITE", monthly_fee_cents=12000, term_months=6,
                          guaranteed_introductions=8, included_coaching_sessions=3,
                          coaching_value_cents=5000, background_check_addon_cents=2500)
    member, membership = fx.create_active_member(plan["id"], "cw@x.com", with_preferences=False)
    fx.set_clock("2026-08-10T00:00:00Z")

    data = validate_success(api.cancel_membership(membership["id"], ADMIN), 200)
    assert data["refund_cents"] == 41001, f"expected 41001, got {data['refund_cents']}"

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["wallet_credit_cents"] == 41001, (
        f"refund must be credited to wallet, got {member_after['wallet_credit_cents']}"
    )


def test_refund_per_line_rounding_with_one_consumed_session(api):
    """PRD §3.9: "the unused sessions are the plan's `included_coaching_sessions` minus the count of the member's coaching sessions whose status is `HELD` or `NO_SHOW` (booked and cancelled sessions do not consume). The coaching refund is computed by rounding the per-session rate half-up **for each** unused session line and then summing those rounded lines". With one HELD session, 2 of 3 remain unused: rate 5000/3=1666.6667,
    per-line 1667+1667 = 3334 (not round(3333.33)=3333).

    Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned_per_line
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=0, term_months=6,
                          guaranteed_introductions=4, included_coaching_sessions=3,
                          coaching_value_cents=5000, background_check_addon_cents=2500)
    member, membership = fx.create_active_member(plan["id"], "d2@x.com", with_preferences=False)
    m_id = member["id"]

    # Consume exactly one coaching session (HELD) so 2 of 3 remain unused.
    s = fx.book_coaching(m_id, "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    fx.set_clock("2026-06-02T12:00:00Z")
    fx.mark_coaching_outcome(s["id"], "HELD")

    data = validate_success(api.cancel_membership(membership["id"], ADMIN), 200)
    assert data["refund_cents"] == 3334, (
        f"2 unused at per-line 1667 each = 3334 (not 3333), got {data['refund_cents']}"
    )


def test_refund_rounding_order_pinned_per_line_isolated(api):
    """PRD §3.9: "with a coaching value of 5000 cents over 3 included sessions the
    per-session rate is 1666.6667; with 3 unused sessions, rounding each line gives
    1667 and summing gives 5001 — not the 5000 that rounding the product would yield,
    so the pinned result is 5001." With monthly_fee 0 the months part is 0, isolating
    the coaching part at 5001.

    Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned_per_line
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=0, term_months=6,
                          guaranteed_introductions=4, included_coaching_sessions=3,
                          coaching_value_cents=5000, background_check_addon_cents=2500)
    member, membership = fx.create_active_member(plan["id"], "d@x.com", with_preferences=False)

    resp = api.cancel_membership(membership["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["refund_cents"] == 5001, (
        f"per-line rounding of 1666.6667*3 = 5001 (not 5000), got {data['refund_cents']}"
    )


# ---------------------------------------------------------------------------
# DateEvent branch outcomes
# ---------------------------------------------------------------------------
def test_date_no_show_recorded_without_coaching_strike(api):
    """PRD §3.6: "A date no-show carries **no** coaching consequence — it does not add
    coaching strikes, which arise only from coaching-session no-shows."

    Design: Difficulty/non_linear_state_machine/date_event_branch_outcome_completed_vs_no_show
    """
    ctx = fx.setup_mutual_with_date(start_at="2026-06-05T18:00:00Z", end_at="2026-06-05T20:00:00Z",
                                    a_email="a3@x.com", b_email="b7@x.com")
    a_id = ctx["member_a"]["id"]
    date_id = ctx["date_event"]["id"]
    fx.set_clock("2026-06-05T21:00:00Z")

    resp = api.date_event_outcome(date_id, {"outcome": "NO_SHOW"}, MATCHMAKER)
    data = validate_success(resp, 200)
    assert data["status"] == "NO_SHOW", f"expected NO_SHOW, got {data['status']}"

    member_a = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a["no_show_strikes"] == 0, (
        f"date no-show must NOT add coaching strikes, got {member_a['no_show_strikes']}"
    )


def test_date_completed_outcome_after_start(api):
    """PRD §3.6: "Recording an outcome of `COMPLETED` or `NO_SHOW` requires the date to be `SCHEDULED` (else `ERR_DATE_NOT_SCHEDULED`) and the clock to have reached the date's `start_at` (else `ERR_DATE_NOT_STARTED`); the supplied `outcome` is set and the matching terminal `status` (`COMPLETED` or `NO_SHOW`) is recorded."

    Design: Difficulty/non_linear_state_machine/date_event_branch_outcome_completed_vs_no_show
    """
    ctx = fx.setup_mutual_with_date(start_at="2026-06-05T18:00:00Z", end_at="2026-06-05T20:00:00Z",
                                    a_email="a3c@x.com", b_email="b7c@x.com")
    date_id = ctx["date_event"]["id"]
    fx.set_clock("2026-06-05T19:00:00Z")
    resp = api.date_event_outcome(date_id, {"outcome": "COMPLETED"}, MATCHMAKER)
    data = validate_success(resp, 200)
    assert data["status"] == "COMPLETED", f"expected COMPLETED, got {data['status']}"


def test_date_outcome_before_start_returns_not_started(api):
    """PRD §3.6: "Recording an outcome of `COMPLETED` or `NO_SHOW` requires the date to
    be `SCHEDULED` (else `ERR_DATE_NOT_SCHEDULED`) and the clock to have reached the
    date's `start_at` (else `ERR_DATE_NOT_STARTED`)".

    Design: Corner/state_machines/date_outcome_before_start_returns_not_started
    """
    ctx = fx.setup_mutual_with_date(start_at="2026-06-15T18:00:00Z", end_at="2026-06-15T20:00:00Z",
                                    a_email="ca5@x.com", b_email="cb5@x.com")
    date_id = ctx["date_event"]["id"]
    # Clock is still 2026-06-01 (set by the fixture), before the date start.
    resp = api.date_event_outcome(date_id, {"outcome": "COMPLETED"}, MATCHMAKER)
    validate_error(resp, ApiErrorId.ERR_DATE_NOT_STARTED.value, 409)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def test_member_exit_cascades_intro_close_then_date_cancel(api):
    """PRD §3.9: "On exit the member moves to EXITED ... Every SUGGESTED or ONE_SIDED
    introduction for the member is closed as a cascade ... every SCHEDULED date on the
    member's introductions is cancelled ... This is the depth-three cascade: member
    exit closes introductions, and closing an introduction cancels its scheduled date."

    Design: Difficulty/transitive_cascade/member_exit_cascades_intro_close_then_date_cancel
    """
    ctx = fx.setup_mutual_with_date(start_at="2026-06-20T18:00:00Z", end_at="2026-06-20T20:00:00Z",
                                    a_email="a4@x.com", b_email="b8@x.com")
    a_id = ctx["member_a"]["id"]
    intro_id = ctx["introduction"]["id"]
    date_id = ctx["date_event"]["id"]

    validate_success(api.exit_member(a_id, ADMIN), 200)

    member_a = validate_success(api.get_member(a_id, ADMIN), 200)
    assert member_a["status"] == "EXITED", f"expected EXITED, got {member_a['status']}"

    intro = validate_success(api.get_introduction(intro_id, ADMIN), 200)
    assert intro["status"] == "CLOSED", f"introduction must cascade to CLOSED, got {intro['status']}"

    date = validate_success(api.get_date_event(date_id, ADMIN), 200)
    assert date["status"] == "CANCELLED", (
        f"scheduled date must cascade to CANCELLED, got {date['status']}"
    )


def test_member_exit_cancels_booked_coaching_and_refunds_below_mutual_credit(api):
    """PRD §3.9: "Every `SUGGESTED` or `ONE_SIDED` introduction for the member is closed
    as a cascade, and each such closed introduction — being below the mutual stage —
    refunds its consumed credits".
    PRD §3.9: "every `SCHEDULED` date on the member's introductions is cancelled, and
    every `BOOKED` coaching session for the member is cancelled." A SUGGESTED
    introduction + a BOOKED coaching session both cascade on exit; the credit is refunded.

    Design: Difficulty/transitive_cascade/member_exit_cascades_intro_close_then_date_cancel
    """
    ctx = fx.setup_suggested_introduction(plan_overrides={"guaranteed_introductions": 8},
                                          a_email="ex_a@x.com", b_email="ex_b@x.com")
    a_id = ctx["member_a"]["id"]
    intro_id = ctx["introduction"]["id"]
    session = fx.book_coaching(a_id, "2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z")

    validate_success(api.exit_member(a_id, ADMIN), 200)

    intro = validate_success(api.get_introduction(intro_id, ADMIN), 200)
    assert intro["status"] == "CLOSED", f"suggested intro must close on exit, got {intro['status']}"

    sess = validate_success(api.get_coaching_session(session["id"], ADMIN), 200)
    assert sess["status"] == "CANCELLED", (
        f"booked coaching must cancel on exit, got {sess['status']}"
    )

    member_a = validate_success(api.get_member(a_id, ADMIN), 200)
    assert member_a["guarantee_remaining_forecast"] == 8, (
        f"below-MUTUAL close refunds the credit, forecast back to 8, got "
        f"{member_a['guarantee_remaining_forecast']}"
    )


def test_background_flagged_check_completes(api):
    """PRD §3.10: "A `ScreeningOfficer` completes an ordered check by supplying a `result` of `CLEAR` or `FLAGGED`. Completion requires the check to be `ORDERED` (else `ERR_CHECK_NOT_ORDERED`); the `result` is set and the `status` becomes `COMPLETED`."

    Design: Difficulty/transitive_cascade/background_flagged_cascades_intro_close_with_refund
    """
    ctx = fx.setup_suggested_introduction(plan_overrides={"guaranteed_introductions": 8},
                                          a_email="bf_a@x.com", b_email="bf_b@x.com")
    b_id = ctx["member_b"]["id"]
    chk = fx.order_background_check(b_id, provider_ref="PRV-X")

    resp = api.complete_background_check(
        b_id, chk["id"], f.complete_background_check_payload("FLAGGED"), SCREENING
    )
    data = validate_success(resp, 200)
    assert data["result"] == "FLAGGED", f"expected FLAGGED, got {data['result']}"
    assert data["status"] == "COMPLETED", f"expected COMPLETED, got {data['status']}"


def test_background_flagged_cascades_intro_close_with_refund(api):
    """PRD §3.10: "When the result is `FLAGGED`, every open `SUGGESTED` or `ONE_SIDED` introduction for the subject member is closed as a cascade, each with its credit refund." PRD §3.5: "If the introduction's status before closing was below `MUTUAL`, its `credits_consumed` are refunded to member A's guarantee".

    Design: Difficulty/transitive_cascade/background_flagged_cascades_intro_close_with_refund
    """
    ctx = fx.setup_suggested_introduction(plan_overrides={"guaranteed_introductions": 8},
                                          a_email="a5@x.com", b_email="b9@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro_id = ctx["introduction"]["id"]

    chk = fx.order_background_check(b_id, provider_ref="PRV-1")
    resp = api.complete_background_check(
        b_id, chk["id"], f.complete_background_check_payload("FLAGGED"), SCREENING
    )
    chk_data = validate_success(resp, 200)
    assert chk_data["result"] == "FLAGGED", f"expected FLAGGED, got {chk_data['result']}"

    intro = validate_success(api.get_introduction(intro_id, MATCHMAKER), 200)
    assert intro["status"] == "CLOSED", (
        f"flagged check must close the open introduction, got {intro['status']}"
    )

    member_a = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a["guarantee_remaining_forecast"] == 8, (
        f"closing a below-MUTUAL intro refunds the credit, forecast back to 8, got "
        f"{member_a['guarantee_remaining_forecast']}"
    )


def test_background_check_cancel_refunds_wallet_conserved(api):
    """PRD §3.10: "Ordering creates a `BackgroundCheck` in status `ORDERED`, with
    `result` `NONE`, and charges the add-on fee: `fee_charged_cents` is snapshotted from
    the plan's `background_check_addon_cents` at order time."
    PRD §3.10: "A `ScreeningOfficer` may instead cancel an ordered check (else
    `ERR_CHECK_NOT_ORDERED`), which moves it to `CANCELLED` and refunds the
    `fee_charged_cents` back to the member's `wallet_credit_cents`."

    Design: Difficulty/compensating_invariant/background_check_cancel_refunds_wallet_conserved
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", background_check_addon_cents=2500)
    member, _ = fx.create_active_member(plan["id"], "a14@x.com", with_preferences=False)
    a_id = member["id"]

    chk = fx.order_background_check(a_id, provider_ref="PRV-2")
    assert chk["fee_charged_cents"] == 2500, (
        f"fee snapshotted from plan addon 2500, got {chk['fee_charged_cents']}"
    )

    resp = api.cancel_background_check(a_id, chk["id"], SCREENING)
    chk_data = validate_success(resp, 200)
    assert chk_data["status"] == "CANCELLED", f"expected CANCELLED, got {chk_data['status']}"

    member_after = validate_success(api.get_member(a_id, SCREENING), 200)
    assert member_after["wallet_credit_cents"] == 2500, (
        f"cancel refunds 2500 to wallet, got {member_after['wallet_credit_cents']}"
    )


def test_background_check_order_charges_fee_then_cancel_clears_check(api):
    """PRD §3.10: "Ordering creates a `BackgroundCheck` in status `ORDERED`, with `result` `NONE`, and charges the add-on fee: `fee_charged_cents` is snapshotted from the plan's `background_check_addon_cents` at order time." and "A `ScreeningOfficer` may instead cancel an ordered check (else `ERR_CHECK_NOT_ORDERED`), which moves it to `CANCELLED` and refunds the `fee_charged_cents` back to the member's `wallet_credit_cents`."

    Design: Difficulty/compensating_invariant/background_check_cancel_refunds_wallet_conserved
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="PLUS", background_check_addon_cents=2500)
    member, _ = fx.create_active_member(plan["id"], "bw@x.com", with_preferences=False)
    a_id = member["id"]

    chk = fx.order_background_check(a_id, provider_ref="PRV-3")
    assert chk["status"] == "ORDERED", f"new check is ORDERED, got {chk['status']}"
    assert chk["result"] == "NONE", f"new check result NONE, got {chk['result']}"
    assert chk["fee_charged_cents"] == 2500, (
        f"fee snapshotted from plan addon, got {chk['fee_charged_cents']}"
    )

    cancelled = validate_success(api.cancel_background_check(a_id, chk["id"], SCREENING), 200)
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
