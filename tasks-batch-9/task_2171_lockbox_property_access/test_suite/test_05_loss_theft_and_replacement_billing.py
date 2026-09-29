"""Loss and theft reports, the two replacement variants, recovery and posture."""

from test_helpers import (
    ApiErrorId,
    charge_action,
    enroll_member,
    intake_lockbox,
    list_charges,
    only_charge,
    read_association,
    read_charge,
    read_grant,
    read_lockbox,
    read_member,
    read_placement,
    read_showing,
    register_association,
    report_lockbox_lost,
    report_lockbox_stolen,
    setup_approved_grant,
    setup_assigned_box,
    setup_frozen_association,
    setup_placed_box,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import (
    add_second_agent,
    assign_lockbox,
    lockbox_action,
    make_member_headers,
    placement_payload,
    set_clock,
    setup_confirmed_showing,
)


def _two_holders_with_identical_boxes():
    """Two agents, each holding a 12000-cent unit in service since 2025-08-01, with the
    logical clock at 2026-08-15 so both units are twelve months old."""
    association = register_association()
    set_clock("2026-08-15T00:00:00Z")
    ana = enroll_member(association["id"], full_name="Ana Reyes", email="ana@example.com")
    ben = enroll_member(association["id"], full_name="Ben Ortiz", email="ben@example.com")
    box_one = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_PRO",
        replacement_cost_cents=12000,
        in_service_since="2025-08-01",
    )
    box_two = intake_lockbox(
        association["id"],
        serial_number="LB-0002",
        model="LB_PRO",
        replacement_cost_cents=12000,
        in_service_since="2025-08-01",
    )
    assign_lockbox(box_one["id"], ana["id"])
    assign_lockbox(box_two["id"], ben["id"])
    return {
        "association": association,
        "ana": ana,
        "ben": ben,
        "box_one": box_one,
        "box_two": box_two,
    }


def test_plain_loss_report_charges_the_full_flat_schedule_amount(api, admin_headers):
    """PRD §3.7: "In every other case — a plain loss, or a theft with no report number —
    the flat-schedule variant applies and `variant_applied` is `FLAT_SCHEDULE`."
    PRD §3.7: "A first loss carries a repeat multiplier of 1.00; a second loss, where the
    prior count is exactly 1, carries 1.50; a third or subsequent loss, where the prior count
    is 2 or more, carries 2.00. The amount is the published replacement cost multiplied by
    that repeat multiplier, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/replacement_charge_flat_schedule_vs_depreciated_book
    """
    scenario = _two_holders_with_identical_boxes()
    report_lockbox_lost(scenario["box_one"]["id"])
    report_lockbox_stolen(scenario["box_two"]["id"], "SPD-2026-4417")

    charge = only_charge(member_id=scenario["ana"]["id"], charge_type="REPLACEMENT")
    assert charge["amount_cents"] == 12000
    assert charge["variant_applied"] == "FLAT_SCHEDULE"

    assert read_member(scenario["ana"]["id"])["outstanding_balance_cents"] == 12300

    lockbox = read_lockbox(scenario["box_one"]["id"])
    assert lockbox["status"] == "MISSING"
    assert lockbox["loss_type"] == "LOST"


def test_theft_report_with_a_police_number_charges_depreciated_book(api, admin_headers):
    """PRD §3.7: "*The depreciated-book variant* charges depreciated book value halved by a
    theft security offset, and it deliberately ignores the holder's prior loss history
    altogether."
    PRD §3.7: "To make the divergence concrete: a twelve-month-old unit with a published cost
    of 12000 cents yields 4560 under the depreciated-book variant and 12000 under the
    flat-schedule variant with no prior losses."

    Design: Difficulty/dual_variant_calc/replacement_charge_flat_schedule_vs_depreciated_book
    """
    scenario = _two_holders_with_identical_boxes()
    report_lockbox_lost(scenario["box_one"]["id"])
    report_lockbox_stolen(scenario["box_two"]["id"], "SPD-2026-4417")

    charge = only_charge(member_id=scenario["ben"]["id"], charge_type="REPLACEMENT")
    assert charge["amount_cents"] == 4560
    assert charge["variant_applied"] == "DEPRECIATED_BOOK"

    assert read_member(scenario["ben"]["id"])["outstanding_balance_cents"] == 4674

    lockbox = read_lockbox(scenario["box_two"]["id"])
    assert lockbox["status"] == "MISSING"
    assert lockbox["loss_type"] == "STOLEN"


def test_loss_report_raises_a_replacement_charge_and_lifts_the_balance(api, admin_headers):
    """PRD §3.7: "Either kind of report raises a charge with `charge_type` of `REPLACEMENT`
    against the member in `assigned_member_id`, linked by `lockbox_id`, in `PENDING`, after
    which that member's `outstanding_balance_cents` is recomputed."
    PRD §2.7: "Each open line is grossed up by an administration surcharge of 2.5 percent of
    its `amount_cents`, and **the rounding order is pinned: the grossed-up figure is rounded
    half up to a whole cent for each line individually, and only then are the rounded line
    totals added together.**"

    Design: Difficulty/compensating_invariant/loss_then_recover_conserves_member_outstanding_balance
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_PRO", replacement_cost_cents=12000)
    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 0

    report_lockbox_lost(ctx["lockbox_id"])

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 12300
    charge = only_charge(member_id=ctx["agent_id"], charge_type="REPLACEMENT")
    assert charge["status"] == "PENDING"
    assert charge["amount_cents"] == 12000


def test_recovery_voids_the_replacement_charge_and_restores_the_balance(api, admin_headers):
    """PRD §3.7: "Recovery voids the open replacement charge for that box — the charge with
    `charge_type` of `REPLACEMENT` still in `PENDING` or `INVOICED` moves to `VOID` — and
    because that line has left the open set, the holder's `outstanding_balance_cents` is
    recomputed and returns to exactly its pre-report value. The association's
    `missing_box_count` falls by one and `posture` is recomputed."

    Design: Difficulty/compensating_invariant/loss_then_recover_conserves_member_outstanding_balance
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_PRO", replacement_cost_cents=12000)
    report_lockbox_lost(ctx["lockbox_id"])
    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 12300

    recovered = lockbox_action(ctx["lockbox_id"], "RECOVER")
    assert recovered["status"] == "QUARANTINE"

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 0
    charge = only_charge(member_id=ctx["agent_id"], charge_type="REPLACEMENT")
    assert charge["status"] == "VOID"
    assert charge["amount_cents"] == 12000

    association = read_association(ctx["association_id"])
    assert association["missing_box_count"] == 0
    assert association["posture"] == "OPEN"


def test_loss_report_drives_the_placement_delinquent_and_revokes_the_grant(api, admin_headers):
    """PRD §3.7: "The placement on that box sitting in `PLACED` or `REMOVAL_DUE` becomes
    `DELINQUENT` — and its `billing_status` deliberately stays at `NONE`, because a missing
    box accrues a replacement charge, never a late-removal charge."
    PRD §3.7: "Because that placement went delinquent, every grant naming that `lockbox_id`
    still in `REQUESTED` or `APPROVED` becomes `REVOKED`; because those grants were revoked,
    every showing on the placement's listing still in `REQUESTED` or `CONFIRMED` with a
    `window_start` strictly after the current logical clock becomes `CANCELLED` with
    `cancel_reason` of `ACCESS_LOST`."

    Design: Difficulty/transitive_cascade/loss_report_cascades_lockbox_to_placement_to_grant_to_showing
    """
    ctx = setup_approved_grant(clock="2026-08-05T00:00:00Z", grant_type="INSPECTOR")
    add_second_agent(ctx)
    setup_confirmed_showing(ctx, ctx["other_agent_id"])

    report_lockbox_lost(ctx["lockbox_id"], headers=make_member_headers(ctx["agent_id"]))

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "MISSING"
    assert lockbox["loss_type"] == "LOST"
    assert lockbox.get("current_listing_id") is None

    placement = read_placement(ctx["placement_id"])
    assert placement["placement_status"] == "DELINQUENT"
    assert placement["billing_status"] == "NONE"

    assert read_grant(ctx["grant_id"])["status"] == "REVOKED"


def test_loss_report_cancels_the_future_showing_and_freezes_the_association(api, admin_headers):
    """PRD §2.9: "In each case the third hop cancels only future showings — a
    `ShowingAppointment` whose `window_start` is strictly later than the current logical clock
    — and stamps `cancel_reason` as `ACCESS_LOST` to distinguish it from a human cancellation,
    which stamps `AGENT_CANCELLED`."
    PRD §2.8: "If `missing_box_count` is at least 3, or the delinquent ratio is at least 0.50,
    the posture is `FROZEN`."

    Design: Difficulty/transitive_cascade/loss_report_cascades_lockbox_to_placement_to_grant_to_showing
    """
    ctx = setup_approved_grant(clock="2026-08-05T00:00:00Z", grant_type="INSPECTOR")
    add_second_agent(ctx)
    setup_confirmed_showing(ctx, ctx["other_agent_id"])

    report_lockbox_lost(ctx["lockbox_id"], headers=make_member_headers(ctx["agent_id"]))

    appointment = read_showing(ctx["appointment_id"])
    assert appointment["status"] == "CANCELLED"
    assert appointment["cancel_reason"] == "ACCESS_LOST"

    charge = only_charge(member_id=ctx["agent_id"], charge_type="REPLACEMENT")
    assert charge["amount_cents"] == 12000
    assert charge["status"] == "PENDING"
    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 12300

    association = read_association(ctx["association_id"])
    assert association["missing_box_count"] == 1
    assert association["delinquent_placement_count"] == 1
    assert association["posture"] == "FROZEN"


def test_second_loss_by_the_same_holder_applies_the_repeat_multiplier(api, admin_headers):
    """PRD §3.7: "The holder's history is `loss_report_count`: the number of that member's
    lockboxes sitting in `MISSING` or `QUARANTINE`, counted **before** the current report
    flips this unit to `MISSING`."
    PRD §3.7: "A first loss carries a repeat multiplier of 1.00; a second loss, where the
    prior count is exactly 1, carries 1.50; a third or subsequent loss, where the prior count
    is 2 or more, carries 2.00."

    Design: Corner/calculations/replacement_charge_repeat_multiplier_on_second_loss
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_PRO", replacement_cost_cents=12000)
    second_box = intake_lockbox(
        ctx["association_id"],
        serial_number="LB-0002",
        model="LB_PRO",
        replacement_cost_cents=12000,
    )
    assign_lockbox(second_box["id"], ctx["agent_id"])

    report_lockbox_lost(ctx["lockbox_id"])
    report_lockbox_lost(second_box["id"])

    first_charge = only_charge(lockbox_id=ctx["lockbox_id"])
    second_charge = only_charge(lockbox_id=second_box["id"])
    assert first_charge["amount_cents"] == 12000
    assert first_charge["variant_applied"] == "FLAT_SCHEDULE"
    assert second_charge["amount_cents"] == 18000
    assert second_charge["variant_applied"] == "FLAT_SCHEDULE"

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 30750

    association = read_association(ctx["association_id"])
    assert association["missing_box_count"] == 2
    assert association["posture"] == "RESTRICTED"


def test_voiding_a_paid_charge_is_refused(api, admin_headers):
    """PRD §3.7: "`PAID`, `WAIVED` and `VOID` are terminal, and any money action against a
    charge already in one of them is refused with `ERR_CHARGE_NOT_ADJUSTABLE`; the same
    refusal applies to voiding a `REPLACEMENT` charge whose lockbox has since been retired."
    PRD §3.7: "Paying moves a charge in `PENDING` or `INVOICED` to `PAID`, and waiving moves a
    charge in `PENDING` or `INVOICED` to `WAIVED`; both recompute the member's
    `outstanding_balance_cents` because the line has left the open set, and both move a linked
    placement's `billing_status` from `ACCRUED` to `SETTLED`."

    Design: Corner/validations/void_after_paid_charge_not_adjustable
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_PRO", replacement_cost_cents=12000)
    report_lockbox_lost(ctx["lockbox_id"])
    charge = only_charge(member_id=ctx["agent_id"], charge_type="REPLACEMENT")
    paid = charge_action(charge["id"], "PAY")

    response = api.billing_charge_state(
        charge["id"],
        {"action": "VOID", "expected_charge_version": paid["version"]},
        admin_headers,
    )
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_CHARGE_NOT_ADJUSTABLE.value,
            ApiErrorId.ERR_ENTITY_TERMINAL.value,
        ],
    )
    assert response.status_code == 409

    stored = read_charge(charge["id"])
    assert stored["status"] == "PAID"
    assert stored["amount_cents"] == 12000
    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 0


def test_a_single_missing_box_moves_the_posture_to_restricted(api, admin_headers):
    """PRD §2.8: "The two tests are then applied in order, and the first match wins. If
    `missing_box_count` is at least 3, or the delinquent ratio is at least 0.50, the posture is
    `FROZEN`. Otherwise, if `missing_box_count` is at least 1, or the delinquent ratio is at
    least 0.25, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/calculations/association_posture_restricted_at_exactly_one_missing_box
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    second_box = intake_lockbox(
        ctx["association_id"],
        serial_number="LB-0002",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    assign_lockbox(second_box["id"], ctx["agent_id"])

    before = read_association(ctx["association_id"])
    assert before["posture"] == "OPEN"
    assert before["missing_box_count"] == 0

    report_lockbox_lost(ctx["lockbox_id"])

    after = read_association(ctx["association_id"])
    assert after["missing_box_count"] == 1
    assert after["posture"] == "RESTRICTED"
    assert after["boxes_in_field_count"] == 1
    assert after["unplaced_inventory_count"] == 1


def test_frozen_association_blocks_a_new_placement(api, admin_headers):
    """PRD §2.8: "A `FROZEN` association may not have new placements created and may not have
    grants created or approved; the rejection is `ERR_ASSOCIATION_FROZEN` (HTTP 409)."
    PRD §3.4: "A `FROZEN` association blocks the operation with `ERR_ASSOCIATION_FROZEN`."

    Design: Corner/validations/frozen_association_blocks_new_placement
    """
    ctx = setup_frozen_association()

    association = read_association(ctx["association_id"])
    assert association["missing_box_count"] == 3
    assert association["posture"] == "FROZEN"

    response = api.create_placement(
        placement_payload(ctx["clean_lockbox_id"], ctx["other_listing_id"]),
        make_member_headers(ctx["other_agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_ASSOCIATION_FROZEN.value)

    clean_box = read_lockbox(ctx["clean_lockbox_id"])
    assert clean_box["status"] == "ASSIGNED"
    assert clean_box.get("current_listing_id") is None

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 41513


def test_loss_report_cascade_is_visible_in_the_same_response(api, admin_headers):
    """PRD §2.9: "The hops are not optional and are not deferred — they complete inside the
    originating request, and each entity they touch has its own `version` advanced and its own
    `updated_at` refreshed exactly as if it had been acted on directly."
    PRD §3.7: "On acceptance the box moves to `MISSING`, its `loss_type` is written as `LOST`
    or `STOLEN` respectively, any `police_report_number` is stored, `missing_box_count` rises
    by one while `boxes_in_field_count` and `unplaced_inventory_count` each fall by one, and
    `posture` is recomputed."

    Design: Corner/consistency_model/loss_report_cascade_is_visible_in_the_same_response
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_PRO", replacement_cost_cents=12000)
    current = read_lockbox(ctx["lockbox_id"])

    response = api.lockbox_state(
        ctx["lockbox_id"],
        {"action": "REPORT_LOST", "expected_lockbox_version": current["version"]},
        admin_headers,
    )
    data = validate_success(response, 200)
    assert data["status"] == "MISSING"
    assert data["loss_type"] == "LOST"
    assert data.get("current_listing_id") is None

    assert read_placement(ctx["placement_id"])["placement_status"] == "DELINQUENT"
    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 12300

    association = read_association(ctx["association_id"])
    assert association["missing_box_count"] == 1
    assert association["delinquent_placement_count"] == 1
    assert association["posture"] == "FROZEN"
