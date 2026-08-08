"""Analyte banding, the red-flag freeze cascade and referral loop closure."""

from test_helpers import (
    ApiErrorId,
    assert_calendar_date,
    assert_lab_result,
    assert_referral,
    make_nd_headers,
    raise_routine_referral,
    read_patient,
    referral_transition,
    register_nd,
    register_patient,
    setup_collected_panel,
    setup_frozen_by_critical_result,
    take_titration_decision,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN

TSH_DUAL_BAND = {
    "analyte_code": "TSH",
    "value": 4.2,
    "unit": "uIU/mL",
    "standard_low": 0.45,
    "standard_high": 4.50,
    "optimal_low": 1.00,
    "optimal_high": 2.50,
    "critical_low": 0.10,
    "critical_high": 10.00,
}


def test_one_value_is_conventionally_in_range_and_functionally_above_optimal(api):
    """PRD §3.5: "The `standard_band` is `LOW` when the value falls below
    `standard_low`, `HIGH` when it rises above `standard_high`, and `IN_RANGE`
    in every other case — the conventional range is closed at both ends, so a
    value sitting exactly on `standard_high` is still `IN_RANGE`."
    PRD §3.5: "The `optimal_band` is `BELOW_OPTIMAL` when the value falls below
    `optimal_low`, `ABOVE_OPTIMAL` when the value reaches or exceeds
    `optimal_high`, and `OPTIMAL` in every other case — the functional range is
    closed at the bottom but half-open at the top, so a value sitting exactly on
    `optimal_high` is already `ABOVE_OPTIMAL`."

    Design: Difficulty/dual_variant_calc/analyte_in_standard_range_but_above_functional_optimal
    """
    ctx = setup_collected_panel(api)
    result = validate_success(
        api.create_lab_result(
            ctx["order"]["id"], dict(TSH_DUAL_BAND), make_nd_headers(ctx["nd"]["id"])
        ),
        201,
    )

    assert_lab_result(result)
    assert result["standard_band"] == "IN_RANGE"
    assert result["optimal_band"] == "ABOVE_OPTIMAL"
    assert result["is_critical"] is False


def test_the_dual_banded_value_routes_the_order_to_the_non_critical_branch(api):
    """PRD §3.5: "Separately, `is_critical` is true when the value is at or below
    `critical_low` or at or above `critical_high`."
    PRD §3.5: "Posting a non-critical analyte to a `COLLECTED` order moves it
    `COLLECTED → RESULTED`; posting further non-critical analytes to an order
    already at `RESULTED` leaves it at `RESULTED` in a self-loop, creating and
    classifying an additional result each time."

    Design: Difficulty/dual_variant_calc/analyte_in_standard_range_but_above_functional_optimal
    """
    ctx = setup_collected_panel(api)
    nd, order = ctx["nd"], ctx["order"]
    validate_success(
        api.create_lab_result(order["id"], dict(TSH_DUAL_BAND), make_nd_headers(nd["id"])),
        201,
    )

    refreshed = validate_success(api.get_lab_order(order["id"], make_nd_headers(nd["id"])))
    assert refreshed["status"] == "RESULTED"
    assert refreshed["has_critical_result"] is False

    rows, meta = validate_paginated(
        api.list_lab_results(order["id"], make_nd_headers(nd["id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["standard_band"] == "IN_RANGE"
    assert rows[0]["optimal_band"] == "ABOVE_OPTIMAL"


def test_lab_results_carry_neither_updated_at_nor_version(api):
    """PRD §2.4: "There is exactly one exception: a `LabResult` is an immutable
    observation and carries only `id` and `created_at` — it has no `updated_at`
    field and no `version` field at all, and neither may be invented for it."
    PRD §3.5: "Only a `NaturopathicDoctor` may post one, and the resulting
    record carries an `id` and a `created_at` but neither an `updated_at` nor a
    `version`, because a result is never edited."

    Design: Corner/entities/lab_result_is_immutable_and_carries_no_version_field
    """
    ctx = setup_collected_panel(api)
    result = validate_success(
        api.create_lab_result(
            ctx["order"]["id"],
            {
                "analyte_code": "TSH",
                "value": 2.0,
                "unit": "uIU/mL",
                "standard_low": 0.45,
                "standard_high": 4.50,
                "optimal_low": 1.00,
                "optimal_high": 2.50,
                "critical_low": 0.10,
                "critical_high": 10.00,
            },
            make_nd_headers(ctx["nd"]["id"]),
        ),
        201,
    )

    assert_lab_result(result)
    assert "updated_at" not in result
    assert "version" not in result
    assert result["standard_band"] == "IN_RANGE"
    assert result["optimal_band"] == "OPTIMAL"


def test_both_analytes_of_an_order_are_listed_with_their_own_bands(api):
    """PRD §3.5: "The analytes recorded against a given order can be listed back
    in `created_at` order like any other collection."
    PRD §3.5: "One and the same number can therefore be reported `IN_RANGE`
    conventionally and `ABOVE_OPTIMAL` functionally, which is precisely the
    distinction functional medicine trades on."

    Design: Corner/endpoints/lab_results_are_listed_through_the_sub_resource_of_their_order
    """
    ctx = setup_collected_panel(api)
    nd, order = ctx["nd"], ctx["order"]

    on_standard_high = validate_success(
        api.create_lab_result(
            order["id"],
            {
                "analyte_code": "TSH",
                "value": 4.50,
                "unit": "uIU/mL",
                "standard_low": 0.45,
                "standard_high": 4.50,
                "optimal_low": 1.00,
                "optimal_high": 2.50,
                "critical_low": 0.10,
                "critical_high": 10.00,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    on_optimal_high = validate_success(
        api.create_lab_result(
            order["id"],
            {
                "analyte_code": "FT4",
                "value": 2.50,
                "unit": "ng/dL",
                "standard_low": 0.80,
                "standard_high": 3.00,
                "optimal_low": 1.20,
                "optimal_high": 2.50,
                "critical_low": 0.20,
                "critical_high": 6.00,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_lab_results(order["id"], make_nd_headers(nd["id"]), params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}

    assert by_id[on_standard_high["id"]]["standard_band"] == "IN_RANGE"
    assert by_id[on_standard_high["id"]]["optimal_band"] == "ABOVE_OPTIMAL"
    assert by_id[on_optimal_high["id"]]["standard_band"] == "IN_RANGE"
    assert by_id[on_optimal_high["id"]]["optimal_band"] == "ABOVE_OPTIMAL"

    refreshed = validate_success(api.get_lab_order(order["id"], make_nd_headers(nd["id"])))
    assert refreshed["status"] == "RESULTED"


def test_critical_analyte_escalates_the_order_and_raises_a_red_flag_referral(api):
    """PRD §3.5: "Posting a critical analyte moves the order to
    `CRITICAL_ESCALATED`, from `COLLECTED` or from `RESULTED` alike, and fires
    the identical five-link escalation cascade in both cases: the result's
    `is_critical` and the order's `has_critical_result` are set true; a
    `Referral` is created with `referral_type` of `RED_FLAG_AUTO`, `status` of
    `SENT`, its `lab_order_id` pointing at this order, its
    `referring_practitioner_id` copied from the order's
    `ordering_practitioner_id`, and its `due_by_date` set to 3 days after the
    logical clock's date; the patient's `red_flag_referral_open` becomes true
    and their `clinical_write_gate` becomes `FROZEN_RED_FLAG` unless it is
    already `FROZEN_SCOPE_REVIEW`, in which case the scope freeze stands; every
    `ACTIVE` protocol of that patient gets `advancement_blocked` set true; and
    every `ACTIVE` or `HELD` line beneath those protocols gets
    `titration_locked` set true."

    Design: Difficulty/transitive_cascade/critical_analyte_freezes_the_chart_through_five_chained_hops
    """
    ctx = setup_frozen_by_critical_result(api, with_tech=False, with_lot=False)

    assert ctx["result"]["is_critical"] is True
    assert ctx["result"]["standard_band"] == "HIGH"
    assert ctx["result"]["optimal_band"] == "ABOVE_OPTIMAL"

    order = validate_success(
        api.get_lab_order(ctx["order"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert order["status"] == "CRITICAL_ESCALATED"
    assert order["has_critical_result"] is True

    referral = ctx["referral"]
    assert_referral(referral)
    assert referral["referral_type"] == "RED_FLAG_AUTO"
    assert referral["status"] == "SENT"
    assert referral["lab_order_id"] == order["id"]
    assert referral["referring_practitioner_id"] == order["ordering_practitioner_id"]
    assert_calendar_date(referral["due_by_date"], "2026-05-04", "Referral.due_by_date")

    patient = read_patient(api, ctx["patient"]["id"])
    assert patient["red_flag_referral_open"] is True
    assert patient["clinical_write_gate"] == "FROZEN_RED_FLAG"


def test_the_closed_gate_blocks_the_protocol_and_locks_its_line(api):
    """PRD §2.5: "Freezing and unfreezing propagate down the chart. Whenever the
    gate leaves `OPEN`, every `Protocol` of that patient in status `ACTIVE` has
    `advancement_blocked` set to true, and every `ProtocolItem` under those
    protocols in status `ACTIVE` or `HELD` has `titration_locked` set to true."
    PRD §3.1: "It answers with the current `clinical_write_gate`, the current
    `scope_review_status`, the `red_flag_referral_open` flag, the
    `open_red_flag_referral_id` naming the referral holding the freeze when
    there is one, and both intake scores — and it materialises intake-section
    expiry before answering, so the numbers it returns are never stale."

    Design: Difficulty/transitive_cascade/critical_analyte_freezes_the_chart_through_five_chained_hops
    """
    ctx = setup_frozen_by_critical_result(api, with_tech=False, with_lot=False)
    nd = ctx["nd"]

    protocol = validate_success(
        api.get_protocol(ctx["protocol"]["id"], make_nd_headers(nd["id"]))
    )
    assert protocol["advancement_blocked"] is True

    item = validate_success(
        api.get_protocol_item(ctx["item"]["id"], make_nd_headers(nd["id"]))
    )
    assert item["titration_locked"] is True
    assert item["status"] == "ACTIVE", "The freeze locks the line without stopping it"

    gate = validate_success(api.get_patient_gate(ctx["patient"]["id"], ADMIN))
    assert gate["clinical_write_gate"] == "FROZEN_RED_FLAG"
    assert gate["red_flag_referral_open"] is True
    assert gate["open_red_flag_referral_id"] == ctx["referral"]["id"]


def test_an_escalated_order_cannot_be_interpreted_while_the_red_flag_is_open(api):
    """PRD §3.5: "Interpretation is deliberately **not** part of the gated
    family, so it remains available to the very clinician whose other clinical
    writes are frozen — but an escalated order carries its own guard: it cannot
    be interpreted while the automatic red-flag referral naming it is still in
    status `SENT`, `DECLINED` or `ABANDONED`, and the attempt is refused with
    `ERR_RED_FLAG_UNACKNOWLEDGED`."

    Design: Difficulty/cross_entity_state_dependency/interpretation_blocked_until_the_red_flag_referral_is_acknowledged
    """
    ctx = setup_frozen_by_critical_result(api, with_tech=False, with_lot=False)
    nd, order = ctx["nd"], ctx["order"]

    response = api.interpret_lab_order(
        order["id"],
        {"interpretation_summary": "hyperkalaemia, urgent"},
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RED_FLAG_UNACKNOWLEDGED.value, 409)

    still = validate_success(api.get_lab_order(order["id"], make_nd_headers(nd["id"])))
    assert still["status"] == "CRITICAL_ESCALATED"


def test_acknowledging_the_red_flag_unblocks_the_same_interpret_call(api):
    """PRD §3.5: "**`ACKNOWLEDGE`** moves `SENT → ACKNOWLEDGED` and stamps
    `acknowledged_at`. This is the operation that unfreezes a patient, and it
    runs the five-link unfreeze cascade: once no `RED_FLAG_AUTO` referral of
    that patient remains in status `SENT`, `DECLINED` or `ABANDONED`,
    `red_flag_referral_open` is set false; because that flag cleared,
    `clinical_write_gate` is recomputed to `OPEN` unless `scope_review_status`
    is `UNDER_REVIEW` or `RESTRICTED`, in which case it remains
    `FROZEN_SCOPE_REVIEW`; because the gate re-opened, every `ACTIVE` protocol
    of the patient has `advancement_blocked` set false; and because those
    protocols unblocked, every `ACTIVE` or `HELD` line beneath them has
    `titration_locked` set false."
    PRD §3.5: "A `NaturopathicDoctor` records the `interpretation_summary`,
    moving the order `RESULTED → INTERPRETED` or
    `CRITICAL_ESCALATED → INTERPRETED`, and the order's `version` increments by
    1."

    Design: Difficulty/cross_entity_state_dependency/interpretation_blocked_until_the_red_flag_referral_is_acknowledged
    """
    ctx = setup_frozen_by_critical_result(api, with_tech=False, with_lot=False)
    nd, order, referral = ctx["nd"], ctx["order"], ctx["referral"]

    acknowledged = referral_transition(api, nd["id"], referral["id"], "ACKNOWLEDGE")
    assert acknowledged["status"] == "ACKNOWLEDGED"

    patient = read_patient(api, ctx["patient"]["id"])
    assert patient["red_flag_referral_open"] is False
    assert patient["clinical_write_gate"] == "OPEN"

    interpreted = validate_success(
        api.interpret_lab_order(
            order["id"],
            {"interpretation_summary": "hyperkalaemia, urgent"},
            make_nd_headers(nd["id"]),
        )
    )
    assert interpreted["status"] == "INTERPRETED"


def test_the_whole_unfreeze_chain_lands_inside_the_acknowledge_request(api):
    """PRD §3.7: "A decision may only be taken while the line's
    `titration_locked` is false and the owning protocol is `ACTIVE`; a locked
    line or a protocol that is not active is refused with
    `ERR_DEPENDENT_STATE_INVALID`, and taking a decision is itself one of the
    eight gated families, so a frozen patient is refused with
    `ERR_CLINICAL_WRITE_FROZEN` first."
    PRD §3.7: "The delta selects one of four decisions on a fixed ladder: an
    improvement of 8 or more resolves to `ADVANCE`; an improvement of at least 3
    but less than 8 resolves to `HOLD`; an improvement of at least 0 but less
    than 3 resolves to `REDUCE`; and any negative delta — the patient is worse
    than baseline — resolves to `DISCONTINUE`."
    PRD §3.7: "`ADVANCE` replaces `dose_amount_mg` with the current dose
    multiplied by 1.25, rounded half up to a whole milligram."

    Design: Corner/consistency_model/five_link_unfreeze_is_fully_applied_before_the_acknowledge_response_returns
    """
    ctx = setup_frozen_by_critical_result(api, with_tech=False, with_lot=False)
    nd = ctx["nd"]

    referral_transition(api, nd["id"], ctx["referral"]["id"], "ACKNOWLEDGE")

    patient = read_patient(api, ctx["patient"]["id"])
    assert patient["clinical_write_gate"] == "OPEN"
    assert patient["red_flag_referral_open"] is False

    protocol = validate_success(
        api.get_protocol(ctx["protocol"]["id"], make_nd_headers(nd["id"]))
    )
    assert protocol["advancement_blocked"] is False

    item = validate_success(
        api.get_protocol_item(ctx["item"]["id"], make_nd_headers(nd["id"]))
    )
    assert item["titration_locked"] is False

    decided = take_titration_decision(api, nd["id"], ctx["item"]["id"], 20)
    assert decided["last_decision"] == "ADVANCE"
    assert decided["dose_amount_mg"] == 500


def test_closing_a_referral_straight_from_sent_is_refused(api):
    """PRD §3.5: "**`CLOSE`** moves `REPORT_RECEIVED → CLOSED` and stamps
    `closed_at`. `CLOSED` is terminal."
    PRD §2.6: "The addressed resource is in a state from which the requested
    transition is declared, on the relevant axis, on every state-transition
    endpoint — otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/closing_a_referral_straight_from_sent_returns_invalid_state
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    referral = raise_routine_referral(api, nd["id"], patient["id"], reason="goitre")
    assert referral["status"] == "SENT"

    response = api.create_referral_transition(
        referral["id"], {"action": "CLOSE"}, make_nd_headers(nd["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    still = validate_success(api.get_referral(referral["id"], make_nd_headers(nd["id"])))
    assert still["status"] == "SENT"
    assert still["closed_at"] is None


def test_declining_and_re_referring_cycles_the_referral_back_to_sent(api):
    """PRD §3.5: "**`DECLINE`** moves `SENT → DECLINED` and stores the
    `decline_reason`. Declining never clears a red flag: the patient's gate
    stays `FROZEN_RED_FLAG`."
    PRD §3.5: "While `attempt_no` is still below the maximum of 3, the referral
    moves `DECLINED → SENT`, `attempt_no` increments by 1, the supplied
    `recipient_name` replaces the previous one, and `decline_reason` is cleared
    — the decline-and-retry cycle."

    Design: Difficulty/non_linear_state_machine/referral_decline_re_refer_cycle_then_abandon_at_attempt_cap
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    referral = raise_routine_referral(api, nd["id"], patient["id"])
    assert referral["attempt_no"] == 1

    declined = referral_transition(
        api, nd["id"], referral["id"], "DECLINE",
        decline_reason="not accepting new patients",
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "not accepting new patients"

    resent = referral_transition(
        api, nd["id"], referral["id"], "RE_REFER",
        recipient_name="Willamette Endocrine",
    )
    assert resent["status"] == "SENT"
    assert resent["attempt_no"] == 2
    assert resent["decline_reason"] is None
    assert resent["recipient_name"] == "Willamette Endocrine"


def test_a_re_refer_at_the_attempt_cap_abandons_the_referral(api):
    """PRD §3.5: "Once `attempt_no` has already reached 3, the same action
    instead moves the referral `DECLINED → ABANDONED` with `attempt_no` left
    unchanged and nothing re-sent."
    PRD §3.5: "An abandoned red flag never unfreezes anything; the gate stays
    `FROZEN_RED_FLAG` and the escalated order stays uninterpretable.
    `ABANDONED` is terminal."

    Design: Difficulty/non_linear_state_machine/referral_decline_re_refer_cycle_then_abandon_at_attempt_cap
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    referral = raise_routine_referral(api, nd["id"], patient["id"])

    referral_transition(
        api, nd["id"], referral["id"], "DECLINE", decline_reason="not accepting"
    )
    referral_transition(
        api, nd["id"], referral["id"], "RE_REFER", recipient_name="Willamette Endocrine"
    )
    referral_transition(
        api, nd["id"], referral["id"], "DECLINE", decline_reason="out of network"
    )
    third = referral_transition(
        api, nd["id"], referral["id"], "RE_REFER", recipient_name="Rose City Endocrine"
    )
    assert third["status"] == "SENT"
    assert third["attempt_no"] == 3

    referral_transition(
        api, nd["id"], referral["id"], "DECLINE", decline_reason="no capacity"
    )
    abandoned = referral_transition(
        api, nd["id"], referral["id"], "RE_REFER", recipient_name="Columbia Endocrine"
    )

    assert abandoned["status"] == "ABANDONED"
    assert abandoned["attempt_no"] == 3
    assert abandoned["recipient_name"] == "Rose City Endocrine"
