"""Tool-pool unit conservation, stock boundaries, terminal lockdown, and the
shed-key lifecycle with its registry cap (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_shed_key,
    assert_tool,
    assert_tool_conservation,
    create_tool_checkout_payload,
    make_admin_headers,
    make_participating_volunteer,
    make_shed_key,
    make_tool,
    make_tool_checkout,
    make_volunteer_headers,
    setup_open_slot_scenario,
    validate_error,
    validate_success,
)


def test_tool_unit_conservation_across_return_damage_writeoff(api):
    """PRD §3.7: "One conservation invariant holds at all times: `total_count`
    always equals the sum of available, checked-out, in-maintenance, and
    written-off units."
    PRD §3.7: "the pool's `checked_out_count` falls by the units returned this
    call, and the condition routes them — `GOOD` units flow back into
    `available_count`, while `DAMAGED` units accumulate in `in_maintenance_count`
    until repaired."
    PRD §3.7: "The outstanding units — `qty` minus `qty_returned` — leave
    `checked_out_count` and accumulate in `written_off_count`, and the loss
    cascades to the borrower's record: a borrower in `GOOD` standing drops to
    `PROBATION`."

    Design: Difficulty/compensating_invariant/tool_unit_conservation_across_return_damage_writeoff
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()
    tool = make_tool(total_count=5, tool_name="Hoe set")

    co1 = make_tool_checkout(tool["id"], vol["id"], 2)
    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert tool_now["available_count"] == 3 and tool_now["checked_out_count"] == 2
    assert_tool_conservation(tool_now)

    partial = validate_success(
        api.transition_tool_checkout(
            co1["id"],
            {"to_state": "RETURNED", "qty_returned": 1, "condition_on_return": "DAMAGED"},
            make_volunteer_headers(vol["id"]),
        )
    )
    assert partial["status"] == "PARTIAL_RETURN", "1 of 2 returned: partial"

    returned = validate_success(
        api.transition_tool_checkout(
            co1["id"],
            {"to_state": "RETURNED", "qty_returned": 1, "condition_on_return": "GOOD"},
            make_volunteer_headers(vol["id"]),
        )
    )
    assert returned["status"] == "RETURNED", "remainder returned in full"

    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert tool_now["available_count"] == 4
    assert tool_now["checked_out_count"] == 0
    assert tool_now["in_maintenance_count"] == 1
    assert_tool_conservation(tool_now)

    restored = validate_success(api.restore_tool(tool["id"], {"qty": 1}, admin))
    assert restored["available_count"] == 5
    assert restored["in_maintenance_count"] == 0
    assert_tool_conservation(restored)

    co2 = make_tool_checkout(tool["id"], vol["id"], 2)
    written_off = validate_success(
        api.transition_tool_checkout(co2["id"], {"to_state": "CLOSED_LOSS"}, admin)
    )
    assert written_off["status"] == "CLOSED_LOSS"

    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert_tool(tool_now)
    assert tool_now["available_count"] == 3
    assert tool_now["checked_out_count"] == 0
    assert tool_now["in_maintenance_count"] == 0
    assert tool_now["written_off_count"] == 2
    assert_tool_conservation(tool_now)

    vol_now = validate_success(api.get_volunteer(vol["id"], admin))
    assert vol_now["standing"] == "PROBATION", "write-off loss cascade"


def test_tool_checkout_exact_stock_then_empty_rejected(api):
    """PRD §3.7: "`qty` must not exceed the pool's `available_count` (otherwise
    `ERR_TOOL_INSUFFICIENT_STOCK`)".
    PRD §3.7: "A successful checkout starts `OPEN` with `qty_returned` at zero and
    `condition_on_return` null, and the pool's `checked_out_count` rises by `qty`
    while `available_count` falls by `qty`".

    Design: Difficulty/boundary_precision_check/tool_checkout_exact_stock_then_empty_rejected
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()
    tool = make_tool(total_count=3, tool_name="Hoe set")

    checkout = validate_success(
        api.create_tool_checkout(
            create_tool_checkout_payload(
                tool_id=tool["id"], volunteer_id=vol["id"], qty=3
            ),
            make_volunteer_headers(vol["id"]),
        ),
        expected_status=201,
    )
    assert checkout["status"] == "OPEN", "qty == available_count exactly is allowed"
    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert tool_now["available_count"] == 0
    assert tool_now["checked_out_count"] == 3

    err = validate_error(
        api.create_tool_checkout(
            create_tool_checkout_payload(
                tool_id=tool["id"], volunteer_id=vol["id"], qty=1
            ),
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_TOOL_INSUFFICIENT_STOCK,
    )
    assert err["error_id"] == "ERR_TOOL_INSUFFICIENT_STOCK", "qty 1 > available 0"


def test_shed_key_lifecycle_overdue_loss_and_standing_gates(api):
    """PRD §3.7: "One key per person: the holder's `held_key_count` — the number
    of keys whose `current_holder_volunteer_id` names this volunteer with status
    `CHECKED_OUT` or `OVERDUE` — must be zero, otherwise `ERR_KEY_LIMIT_EXCEEDED`."
    PRD §3.7: "Time catches up with forgotten keys: when the clock passes
    `due_back_at`, the next epoch run moves the key from `CHECKED_OUT` to
    `OVERDUE`. Return is a staff action — requested with `to_state` `RETURNED` —
    from `CHECKED_OUT` or `OVERDUE` (otherwise `ERR_INVALID_KEY_STATE`); it
    restores the key to `AVAILABLE`, clears `current_holder_volunteer_id` and
    `due_back_at` to null, and decrements the holder's `held_key_count`. Declaring
    a key lost, from `CHECKED_OUT` or `OVERDUE`, moves it to the terminal `LOST`
    state, clears the holder, decrements `held_key_count`, and cascades a standing
    penalty: a holder in `GOOD` standing drops to `PROBATION`."
    PRD §3.7: "the holder must be `ORIENTED` (otherwise `ERR_ORIENTATION_REQUIRED`),
    must hold a `SIGNED` waiver (otherwise `ERR_WAIVER_REQUIRED`), and must be in
    `GOOD` standing — `PROBATION` is disqualifying here (otherwise
    `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING`)."

    Design: Corner/state_machines/shed_key_lifecycle_overdue_loss_and_standing_gates
    """
    admin = make_admin_headers()
    holder = make_participating_volunteer()
    k1 = make_shed_key("K-1")
    k2 = make_shed_key("K-2")

    checked_out = validate_success(
        api.transition_shed_key(
            k1["id"],
            {
                "to_state": "CHECKED_OUT",
                "holder_volunteer_id": holder["id"],
                "due_back_at": "2026-08-05T00:00:00Z",
            },
            admin,
        )
    )
    assert checked_out["status"] == "CHECKED_OUT"

    err = validate_error(
        api.transition_shed_key(
            k2["id"],
            {
                "to_state": "CHECKED_OUT",
                "holder_volunteer_id": holder["id"],
                "due_back_at": "2026-08-06T00:00:00Z",
            },
            admin,
        ),
        ApiErrorId.ERR_KEY_LIMIT_EXCEEDED,
    )
    assert err["error_id"] == "ERR_KEY_LIMIT_EXCEEDED", "held_key_count already 1"

    validate_success(api.set_clock({"to_iso8601": "2026-08-06T00:00:00Z"}, admin))
    validate_success(api.run_epoch(admin))
    overdue = validate_success(api.get_shed_key(k1["id"], admin))
    assert overdue["status"] == "OVERDUE", "epoch past due_back_at 2026-08-05"

    returned = validate_success(
        api.transition_shed_key(k1["id"], {"to_state": "RETURNED"}, admin)
    )
    assert returned["status"] == "AVAILABLE", "return restores the key to AVAILABLE"
    assert returned["current_holder_volunteer_id"] is None
    assert returned["due_back_at"] is None

    err = validate_error(
        api.transition_shed_key(k1["id"], {"to_state": "RETURNED"}, admin),
        ApiErrorId.ERR_INVALID_KEY_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_KEY_STATE", "an AVAILABLE key cannot be returned"

    validate_success(
        api.transition_shed_key(
            k2["id"],
            {
                "to_state": "CHECKED_OUT",
                "holder_volunteer_id": holder["id"],
                "due_back_at": "2026-08-07T00:00:00Z",
            },
            admin,
        )
    )
    lost = validate_success(
        api.transition_shed_key(k2["id"], {"to_state": "LOST"}, admin)
    )
    assert_shed_key(lost)
    assert lost["status"] == "LOST"

    holder_now = validate_success(api.get_volunteer(holder["id"], admin))
    assert holder_now["standing"] == "PROBATION", "loss cascade"
    assert holder_now["held_key_count"] == 0

    err = validate_error(
        api.transition_shed_key(
            k1["id"],
            {
                "to_state": "CHECKED_OUT",
                "holder_volunteer_id": holder["id"],
                "due_back_at": "2026-08-08T00:00:00Z",
            },
            admin,
        ),
        ApiErrorId.ERR_VOLUNTEER_NOT_IN_GOOD_STANDING,
    )
    assert err["error_id"] == "ERR_VOLUNTEER_NOT_IN_GOOD_STANDING", (
        "PROBATION blocks shed-key checkout"
    )


def test_shed_key_registry_cap_at_four(api):
    """PRD §3.7: "A `GardenAdmin` registers each physical key with a unique
    `key_code` (duplicates fail with `ERR_KEY_CODE_TAKEN`), and the registry is
    capped: at most 4 keys may exist in any status other than `RETIRED`, so
    registering a fifth live key is rejected with `ERR_KEY_REGISTRY_FULL`."

    Design: Corner/state_machines/shed_key_registry_cap_at_four
    """
    admin = make_admin_headers()
    for code in ("K-1", "K-2", "K-3", "K-4"):
        key = validate_success(api.create_shed_key({"key_code": code}, admin), expected_status=201)
        assert key["status"] == "AVAILABLE"

    err = validate_error(
        api.create_shed_key({"key_code": "K-5"}, admin),
        ApiErrorId.ERR_KEY_REGISTRY_FULL,
    )
    assert err["error_id"] == "ERR_KEY_REGISTRY_FULL", "exactly 4 non-RETIRED keys allowed"


def test_terminal_entities_reject_all_transitions(api):
    """PRD §3.7: "`RETIRED` is terminal, and attempting a new checkout against a
    retired pool fails with `ERR_INVALID_TOOL_STATE`."
    PRD §3.7: "`RETURNED`, `CLOSED_LOSS`, and `AUTO_CLOSED` are terminal."
    PRD §3.5: "A manual cancel from a state outside `REQUESTED`, `WAITLISTED`, or
    `CONFIRMED` is rejected with `ERR_INVALID_SIGNUP_STATE`."

    Design: Corner/state_machines/terminal_entities_reject_all_transitions
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()
    tool = make_tool(total_count=3, tool_name="Hoe set")
    checkout = make_tool_checkout(tool["id"], vol["id"], 1)
    validate_success(
        api.transition_tool_checkout(
            checkout["id"],
            {"to_state": "RETURNED", "qty_returned": 1, "condition_on_return": "GOOD"},
            make_volunteer_headers(vol["id"]),
        )
    )

    ctx = setup_open_slot_scenario(capacity_total=3, capacity_youth=1)
    signup = validate_success(
        api.create_shift_signup(
            {"slot_id": ctx["slot"]["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.cancel_shift_signup(signup["id"], make_volunteer_headers(vol["id"])))

    retired = validate_success(api.retire_tool(tool["id"], admin))
    assert retired["status"] == "RETIRED", "first retire succeeds with zero checked out"

    err = validate_error(api.retire_tool(tool["id"], admin), ApiErrorId.ERR_INVALID_TOOL_STATE)
    assert err["error_id"] == "ERR_INVALID_TOOL_STATE", "RETIRED is terminal"

    err = validate_error(
        api.create_tool_checkout(
            create_tool_checkout_payload(
                tool_id=tool["id"], volunteer_id=vol["id"], qty=1
            ),
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_INVALID_TOOL_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_TOOL_STATE", "checkout against a RETIRED pool"

    err = validate_error(
        api.transition_tool_checkout(checkout["id"], {"to_state": "CLOSED_LOSS"}, admin),
        ApiErrorId.ERR_INVALID_CHECKOUT_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_CHECKOUT_STATE", "RETURNED is terminal"

    err = validate_error(
        api.cancel_shift_signup(signup["id"], make_volunteer_headers(vol["id"])),
        ApiErrorId.ERR_INVALID_SIGNUP_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_SIGNUP_STATE", "CANCELLED is terminal"


def test_tool_full_damaged_return_and_restore(api):
    """PRD §3.7: "the pool's `checked_out_count` falls by the units returned this
    call, and the condition routes them — `GOOD` units flow back into
    `available_count`, while `DAMAGED` units accumulate in `in_maintenance_count`
    until repaired."
    PRD §3.7: "Damaged tools are restored to service by a `GardenAdmin` or
    `Coordinator` through a restore action carrying a `qty`: that many units move
    from `in_maintenance_count` back to `available_count`".

    Design: Difficulty/compensating_invariant/tool_unit_conservation_across_return_damage_writeoff
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()
    tool = make_tool(total_count=4)

    checkout = make_tool_checkout(tool["id"], vol["id"], 2)
    returned = validate_success(
        api.transition_tool_checkout(
            checkout["id"],
            {"to_state": "RETURNED", "qty_returned": 2, "condition_on_return": "DAMAGED"},
            make_volunteer_headers(vol["id"]),
        )
    )
    assert returned["status"] == "RETURNED", "full-remainder return skips PARTIAL_RETURN"
    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert tool_now["available_count"] == 2
    assert tool_now["checked_out_count"] == 0
    assert tool_now["in_maintenance_count"] == 2, "damaged units divert to maintenance"
    assert_tool_conservation(tool_now)

    restored = validate_success(api.restore_tool(tool["id"], {"qty": 2}, admin))
    assert restored["available_count"] == 4
    assert restored["in_maintenance_count"] == 0
    assert_tool_conservation(restored)


def test_tool_partial_drain_to_empty(api):
    """PRD §3.7: "`qty` must not exceed the pool's `available_count` (otherwise
    `ERR_TOOL_INSUFFICIENT_STOCK`)".
    PRD §3.7: "A successful checkout starts `OPEN` with `qty_returned` at zero and
    `condition_on_return` null, and the pool's `checked_out_count` rises by `qty`
    while `available_count` falls by `qty`".

    Design: Difficulty/boundary_precision_check/tool_checkout_exact_stock_then_empty_rejected
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()
    tool = make_tool(total_count=3)

    first = make_tool_checkout(tool["id"], vol["id"], 1)
    assert first["status"] == "OPEN"
    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert tool_now["available_count"] == 2

    second = make_tool_checkout(tool["id"], vol["id"], 2)
    assert second["status"] == "OPEN", "draining the exact remainder is allowed"
    tool_now = validate_success(api.get_tool(tool["id"], admin))
    assert tool_now["available_count"] == 0
    assert tool_now["checked_out_count"] == 3

    err = validate_error(
        api.create_tool_checkout(
            create_tool_checkout_payload(
                tool_id=tool["id"], volunteer_id=vol["id"], qty=1
            ),
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_TOOL_INSUFFICIENT_STOCK,
    )
    assert err["error_id"] == "ERR_TOOL_INSUFFICIENT_STOCK"
