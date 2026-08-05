"""Settlement, reversal, proration, pausing, resuming and cancellation."""

from test_helpers import (
    assert_credit_split,
    assert_patient_billing_conservation,
    assert_same_instant,
    assert_subscription,
    billing_admin_headers,
    book_coaching_session,
    make_patient_headers,
    make_provider_headers,
    open_billing_cycle,
    platform_admin_headers,
    read_billing_cycle,
    read_patient,
    read_subscription,
    set_clock,
    setup_coaching_subscription,
    setup_invoiced_cycle,
    setup_subscription,
    validate_error,
    validate_success,
)


def test_proration_rounds_each_component_before_summing(api):
    """PRD §3.9: "Each is multiplied by the unused days, divided by 30, and rounded
    half-up to whole cents **separately**; the three rounded results are then added
    together to give `proration_credit_cents`, and that sum is never rounded again."
    PRD §3.9: "Take the whole days elapsed from the cycle's `period_start_at` to the
    clock — the difference in seconds divided by 86,400 with the remainder discarded
    — and clamp that figure to the range 0 through 30 inclusive, so a void before the
    window opened prorates as though no days had elapsed and a void long after it
    closed prorates as though all 30 had."
    PRD §2.9: "In proration, each charge component is prorated and rounded to whole
    cents **separately**, and only then are the rounded components summed; the sum is
    never rounded a second time."

    Design: Difficulty/combinatorial_formula/mode_b_proration_rounds_per_component_then_sums
    """
    scenario = setup_invoiced_cycle(
        patient={"email": "eli@example.com", "full_name": "Eli Park", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
        subscription={"coaching_addon_enabled": True},
    )
    cycle = scenario["cycle"]
    assert cycle["medication_charge_cents"] == 34000
    assert cycle["coaching_addon_fee_cents"] == 4900
    assert cycle["dispensing_fee_cents"] == 0
    assert cycle["total_due_cents"] == 38900

    set_clock("2026-06-11T00:00:00Z")
    validate_success(
        api.pause_subscription(
            scenario["subscription"]["id"], {}, billing_admin_headers()
        )
    )

    voided = read_billing_cycle(cycle["id"])
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "SUBSCRIPTION_PAUSED"
    assert voided["proration_credit_cents"] == 25934, (
        "22667 plus 3267 rounded separately, not the 25933 a single rounding yields"
    )


def test_pause_of_an_invoiced_cycle_leaves_the_lifetime_counters_untouched(api):
    """PRD §3.9: "- From `INVOICED`, the void computes `proration_credit_cents` using
    the clock as the stop instant, and leaves both lifetime counters untouched because
    nothing was ever collected."
    PRD §3.9: "A successful pause sets `paused_at` to the clock and fires a three-hop
    cascade: hop one is the status change; hop two moves the subscription's billing
    cycle currently in `OPEN` or `INVOICED` to `VOIDED` with `void_reason`
    `SUBSCRIPTION_PAUSED`, computing `proration_credit_cents` when that cycle had been
    invoiced; hop three moves every coaching session citing that voided cycle's
    `billing_cycle_id` and still in `SCHEDULED` to `FORFEITED`."

    Design: Difficulty/combinatorial_formula/mode_b_proration_rounds_per_component_then_sums
    """
    scenario = setup_invoiced_cycle(
        patient={"email": "eli2@example.com", "full_name": "Eli Park", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
        subscription={"coaching_addon_enabled": True},
    )

    set_clock("2026-06-11T00:00:00Z")
    paused = validate_success(
        api.pause_subscription(
            scenario["subscription"]["id"], {}, billing_admin_headers()
        )
    )

    assert_subscription(paused)
    assert paused["status"] == "PAUSED"
    member = read_patient(scenario["patient"]["id"])
    assert member["lifetime_charged_cents"] == 0
    assert member["lifetime_credited_cents"] == 0
    assert_patient_billing_conservation(member, [])


def test_settlement_charges_the_member_and_opens_the_next_cycle(api):
    """PRD §3.9: "Settlement first computes `coaching_unused_credit_cents` under the
    completed-only reading of the coaching entitlement described in §3.10, then sets
    `settled_amount_cents` to `total_due_cents` less that credit, floored at zero. That
    settled amount is added to the member's `lifetime_charged_cents`, the forward leg of
    the billing conservation identity."
    PRD §3.9: "Settlement also rolls the subscription forward: it opens the next billing
    cycle with `period_start_at` exactly equal to this cycle's `period_end_at` and
    `period_end_at` 30 days beyond that, gives it `sequence_number` equal to the
    subscription's `cycle_count` plus one, increments `cycle_count`, and — when
    `coaching_addon_enabled` is true — grants another 4 coaching credits."

    Design: Difficulty/compensating_invariant/patient_cash_conserved_across_settle_then_void
    """
    scenario = setup_invoiced_cycle(
        patient={"email": "eve@example.com", "full_name": "Eve Marsh", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )
    first = scenario["cycle"]
    assert first["total_due_cents"] == 36500

    settled = validate_success(
        api.settle_billing_cycle(
            first["id"], {"payment_reference": "PAY-9003"}, billing_admin_headers()
        )
    )

    assert settled["status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 36500
    member = read_patient(scenario["patient"]["id"])
    assert member["lifetime_charged_cents"] == 36500
    assert_patient_billing_conservation(member, [settled])

    subscription = read_subscription(scenario["subscription"]["id"])
    assert subscription["cycle_count"] == 2
    second = open_billing_cycle(scenario["subscription"]["id"])
    assert second["sequence_number"] == 2
    assert_same_instant(
        second["period_start_at"], first["period_end_at"], "period_start_at"
    )


def test_voiding_a_settled_cycle_credits_the_member_back_to_zero_net(api):
    """PRD §3.9: "- From `SETTLED`, the void adds the pre-void `settled_amount_cents`
    to the member's `lifetime_credited_cents` and then sets `settled_amount_cents` to
    zero. This is the compensating leg of the billing conservation identity: the charge
    is not erased, it is offset by a visible credit."
    PRD §2.10: "For every member, `lifetime_charged_cents` minus
    `lifetime_credited_cents` always equals the sum of `settled_amount_cents` across
    that member's billing cycles that are currently settled."

    Design: Difficulty/compensating_invariant/patient_cash_conserved_across_settle_then_void
    """
    scenario = setup_invoiced_cycle(
        patient={"email": "eve2@example.com", "full_name": "Eve Marsh", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )
    first = scenario["cycle"]
    validate_success(
        api.settle_billing_cycle(
            first["id"], {"payment_reference": "PAY-9003"}, billing_admin_headers()
        )
    )
    assert read_patient(scenario["patient"]["id"])["lifetime_charged_cents"] == 36500

    voided = validate_success(
        api.void_billing_cycle(
            first["id"], {"void_reason": "ADMIN_REVERSAL"}, billing_admin_headers()
        )
    )

    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "ADMIN_REVERSAL"
    assert voided["settled_amount_cents"] == 0

    member = read_patient(scenario["patient"]["id"])
    assert member["lifetime_charged_cents"] == 36500
    assert member["lifetime_credited_cents"] == 36500
    assert_patient_billing_conservation(member, [])


def test_pause_then_resume_accumulates_whole_paused_days(api):
    """PRD §3.9: "Resuming moves the subscription `PAUSED → ACTIVE`. It adds the whole
    days between `paused_at` and the clock to `pause_days_used`, clears `paused_at`, and
    opens a fresh billing cycle whose `period_start_at` is the clock and whose
    `period_end_at` is 30 days later, with `sequence_number` equal to `cycle_count` plus
    one and `cycle_count` incremented."
    PRD §3.9: "- From `OPEN`, the void leaves `proration_credit_cents` at zero, because
    nothing was ever invoiced, and likewise touches neither lifetime counter."

    Design: Corner/state_machines/subscription_pause_resume_cycle_accumulates_pause_days
    """
    scenario = setup_subscription(
        patient={"email": "sm3@example.com", "full_name": "Sm Three"},
        prescription={"units_per_cycle": 2},
    )
    first = scenario["cycle"]

    set_clock("2026-06-05T00:00:00Z")
    validate_success(
        api.pause_subscription(
            scenario["subscription"]["id"], {}, billing_admin_headers()
        )
    )
    voided = read_billing_cycle(first["id"])
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "SUBSCRIPTION_PAUSED"
    assert voided["proration_credit_cents"] == 0

    set_clock("2026-06-11T00:00:00Z")
    resumed = validate_success(
        api.resume_subscription(
            scenario["subscription"]["id"], {}, billing_admin_headers()
        )
    )

    assert resumed["status"] == "ACTIVE"
    assert resumed["pause_days_used"] == 6
    assert resumed["cycle_count"] == 2

    second = open_billing_cycle(scenario["subscription"]["id"])
    assert second["sequence_number"] == 2
    assert_same_instant(second["period_start_at"], "2026-06-11T00:00:00Z", "period_start_at")
    assert_same_instant(second["period_end_at"], "2026-07-11T00:00:00Z", "period_end_at")


def test_pause_beyond_the_cumulative_ceiling_is_refused(api):
    """PRD §3.9: "The pause is refused with `ERR_PAUSE_LIMIT_EXCEEDED` (422) when
    `pause_days_used` has already reached the cumulative ceiling of 60 days; a pause is
    admissible only while `pause_days_used` is strictly less than 60."

    Design: Corner/validations/pause_limit_exceeded_after_sixty_days_paused
    """
    scenario = setup_subscription(
        patient={"email": "val4@example.com", "full_name": "Val Four"},
        prescription={"units_per_cycle": 2},
    )
    validate_success(
        api.pause_subscription(
            scenario["subscription"]["id"], {}, billing_admin_headers()
        )
    )
    set_clock("2026-08-15T00:00:00Z")
    resumed = validate_success(
        api.resume_subscription(
            scenario["subscription"]["id"], {}, billing_admin_headers()
        )
    )
    assert resumed["pause_days_used"] == 75

    refused = api.pause_subscription(
        scenario["subscription"]["id"], {}, billing_admin_headers()
    )
    validate_error(refused, "ERR_PAUSE_LIMIT_EXCEEDED")

    assert read_subscription(scenario["subscription"]["id"])["status"] == "ACTIVE"


def test_void_reason_other_than_admin_reversal_is_refused(api):
    """PRD §3.9: "A void request submitted directly by a `BillingAdmin` carries a
    `void_reason` in its body, and the only value that endpoint accepts is
    `ADMIN_REVERSAL`; any other value is rejected with `ERR_VALIDATION` (400). The
    other two reasons, `SUBSCRIPTION_PAUSED` and `SUBSCRIPTION_CANCELLED`, are written
    only by the cascades described below."

    Design: Corner/validations/void_reason_other_than_admin_reversal_rejected
    """
    scenario = setup_subscription(
        patient={"email": "val6@example.com", "full_name": "Val Six"},
        prescription={"units_per_cycle": 2},
    )

    refused = api.void_billing_cycle(
        scenario["cycle"]["id"],
        {"void_reason": "SUBSCRIPTION_PAUSED"},
        billing_admin_headers(),
    )
    validate_error(refused, "ERR_VALIDATION")

    untouched = read_billing_cycle(scenario["cycle"]["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["void_reason"] is None


def test_clinician_may_not_invoice_a_billing_cycle(api):
    """PRD §2.1: "When a well-formed, recognised role attempts an operation that role
    is not authorised for, the rejection is `ERR_UNAUTHORIZED` (403)."
    PRD §2.7: "**Role authorisation.** The acting role appears in the endpoint's
    authorised-role list in §4 — otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/provider_cannot_invoice_billing_cycle
    """
    scenario = setup_subscription(
        patient={"email": "rb4@example.com", "full_name": "Rb Four"},
        prescription={"units_per_cycle": 2},
    )

    refused = api.invoice_billing_cycle(
        scenario["cycle"]["id"], {}, make_provider_headers(scenario["clinician"]["id"])
    )
    validate_error(refused, "ERR_UNAUTHORIZED")

    untouched = read_billing_cycle(scenario["cycle"]["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["total_due_cents"] == 0


def test_cancellation_voids_the_invoiced_cycle_and_forfeits_the_session(api):
    """PRD §3.9: "Cancelling from `ACTIVE` fires the same three-hop cascade as a pause,
    except that `void_reason` is written as `SUBSCRIPTION_CANCELLED`: the `OPEN` or
    `INVOICED` cycle is voided with `proration_credit_cents` computed when it had been
    invoiced, and every `SCHEDULED` coaching session on that cycle is forfeited."

    Design: Difficulty/transitive_cascade/subscription_cancellation_three_hop_cascade_to_coaching_forfeit
    """
    scenario = setup_coaching_subscription(
        patient={"email": "kai@example.com", "full_name": "Kai Rowe", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )
    session = book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-12T16:00:00Z",
        scheduled_end_at="2026-06-12T17:00:00Z",
    )
    validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    set_clock("2026-06-11T00:00:00Z")
    cancelled = validate_success(
        api.cancel_subscription(
            scenario["subscription"]["id"],
            {},
            make_patient_headers(scenario["patient"]["id"]),
        )
    )

    assert cancelled["status"] == "CANCELLED"

    voided = read_billing_cycle(scenario["cycle"]["id"])
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "SUBSCRIPTION_CANCELLED"
    assert voided["proration_credit_cents"] == 25934

    forfeited = validate_success(
        api.get_coaching_session(session["id"], platform_admin_headers())
    )
    assert forfeited["status"] == "FORFEITED"
    assert forfeited["billing_cycle_id"] == scenario["cycle"]["id"]


def test_cancellation_forfeit_preserves_the_credit_identity(api):
    """PRD §2.10: "For every subscription, `coaching_credits_granted` always equals
    `coaching_credits_available` plus `coaching_credits_reserved` plus
    `coaching_credits_consumed` plus `coaching_credits_forfeited`."
    PRD §2.10: "Forfeiture is deliberately *not* a compensating action: it moves the
    credit from reserved to forfeited, which preserves the identity while permanently
    removing the credit from availability."
    PRD §3.9: "- From `INVOICED`, the void computes `proration_credit_cents` using the
    clock as the stop instant, and leaves both lifetime counters untouched because
    nothing was ever collected."

    Design: Difficulty/transitive_cascade/subscription_cancellation_three_hop_cascade_to_coaching_forfeit
    """
    scenario = setup_coaching_subscription(
        patient={"email": "kai2@example.com", "full_name": "Kai Rowe", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )
    book_coaching_session(
        scenario["patient"]["id"],
        scenario["subscription"]["id"],
        scenario["coach"]["id"],
        scheduled_start_at="2026-06-12T16:00:00Z",
        scheduled_end_at="2026-06-12T17:00:00Z",
    )
    validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    set_clock("2026-06-11T00:00:00Z")
    validate_success(
        api.cancel_subscription(
            scenario["subscription"]["id"],
            {},
            make_patient_headers(scenario["patient"]["id"]),
        )
    )

    subscription = read_subscription(scenario["subscription"]["id"])
    assert_credit_split(
        subscription, granted=4, available=3, reserved=0, consumed=0, forfeited=1
    )

    member = read_patient(scenario["patient"]["id"])
    assert member["lifetime_charged_cents"] == 0
    assert member["lifetime_credited_cents"] == 0
