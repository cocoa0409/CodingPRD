"""Side-effect surveillance, triage, the clinical-hold cascade and the two indices."""

from test_helpers import (
    assert_check_in,
    assert_lot_split,
    assert_same_instant,
    create_check_in_payload,
    file_check_in,
    make_patient_headers,
    make_provider_headers,
    platform_admin_headers,
    read_prescription,
    read_supply_lot,
    resolve_check_in,
    set_clock,
    setup_active_prescription,
    setup_reserved_order,
    setup_shipped_order,
    triage_check_in,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_score_of_exactly_seven_escalates_without_freezing_the_therapy(api):
    """PRD §3.8: "A `severity_score` of 7 or above moves it `SUBMITTED →
    ESCALATED`; the threshold comparison is inclusive of 7."
    PRD §3.8: "A score of 7 or 8 raises the flag and stops there: the report sits
    `ESCALATED`, the prescription stays `ACTIVE`, and nothing else moves — but while
    that report remains open, the escalation gate of §3.5 will refuse any dose
    increase."
    PRD §3.8: "The `severity_score` is the `nausea_score` counted once, plus the
    `vomiting_score` counted twice, plus a flat 4 when `dehydration_flag` is true
    and nothing when it is false — vomiting weighs double a comparable nausea
    report, and dehydration alone outweighs maximal nausea."

    Design: Difficulty/boundary_precision_check/check_in_score_exactly_seven_escalates_without_holding
    """
    scenario = setup_active_prescription(
        patient={"email": "uma@example.com", "full_name": "Uma Bright"}
    )
    set_clock("2026-06-05T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=2,
        dehydration_flag=False,
    )
    assert report["severity_score"] == 7

    triaged = triage_check_in(report["id"], scenario["clinician"]["id"])

    assert_check_in(triaged)
    assert triaged["status"] == "ESCALATED"
    assert triaged["triaged_by_provider_id"] == scenario["clinician"]["id"]

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["clinical_status"] == "ACTIVE"
    assert prescription["severity_index_rolling"] == 7
    assert prescription["severity_index_since_dose_change"] == 7


def test_score_of_six_clears_the_report(api):
    """PRD §3.8: "A `severity_score` strictly below 7 — that is, 6 or lower — moves
    the report `SUBMITTED → CLEARED`."
    PRD §3.8: "Both branches set `triaged_at` to the clock and
    `triaged_by_provider_id` to the acting clinician, both recompute the
    prescription's two severity indices, and both count toward the billing cycle's
    adherence tier described in §3.9."

    Design: Difficulty/boundary_precision_check/check_in_score_exactly_seven_escalates_without_holding
    """
    scenario = setup_active_prescription(
        patient={"email": "uma2@example.com", "full_name": "Uma Bright"}
    )
    set_clock("2026-06-05T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=2,
        vomiting_score=2,
        dehydration_flag=False,
    )
    assert report["severity_score"] == 6

    triaged = triage_check_in(report["id"], scenario["clinician"]["id"])

    assert triaged["status"] == "CLEARED"
    assert_same_instant(triaged["triaged_at"], "2026-06-05T00:00:00Z", "triaged_at")

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["clinical_status"] == "ACTIVE"
    assert prescription["severity_index_rolling"] == 6
    assert prescription["severity_index_since_dose_change"] == 6


def test_untriaged_report_is_invisible_to_both_severity_indices(api):
    """PRD §3.8: "The report lands in `SUBMITTED` with `triaged_by_provider_id`,
    `triaged_at` and `resolved_at` all null, and — importantly — a report still in
    `SUBMITTED` counts toward nothing. It is excluded from both prescription
    severity indices until a clinician has looked at it."
    PRD §3.8: "Both draw from the same candidate pool — check-ins whose
    `prescription_id` matches and whose status is `CLEARED`, `ESCALATED` or
    `RESOLVED` — and both take the single largest `severity_score` in their
    candidate set, returning zero when the set is empty."

    Design: Corner/calculations/severity_index_ignores_untriaged_check_in
    """
    scenario = setup_active_prescription(
        patient={"email": "cal4@example.com", "full_name": "Cal Four"}
    )
    set_clock("2026-06-05T00:00:00Z")
    low = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=1,
        vomiting_score=2,
    )
    high = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
    )
    assert high["severity_score"] == 9
    assert high["status"] == "SUBMITTED"

    triaged = triage_check_in(low["id"], scenario["clinician"]["id"])
    assert triaged["severity_score"] == 5
    assert triaged["status"] == "CLEARED"

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["severity_index_rolling"] == 5
    assert prescription["severity_index_since_dose_change"] == 5
    assert prescription["clinical_status"] == "ACTIVE"

    untouched = validate_success(api.get_check_in(high["id"], platform_admin_headers()))
    assert untouched["status"] == "SUBMITTED"


def test_nausea_score_above_three_is_refused(api):
    """PRD §3.8: "A member files a check-in naming their own `patient_id` and the
    `prescription_id` the symptoms relate to, with a `nausea_score` and a
    `vomiting_score` each an integer from 0 through 3 inclusive, and an optional
    `dehydration_flag` boolean that defaults to false."
    PRD §2.7: "every bounded integer sits inside its range (`nausea_score` and
    `vomiting_score` from 0 through 3 inclusive; `units_per_cycle` and
    `units_requested` from 1 through 4 inclusive; `limit` from 1 through 100;
    `offset` at least 0)"

    Design: Corner/entities/check_in_nausea_score_out_of_range_rejected
    """
    scenario = setup_active_prescription(
        patient={"email": "corner8@example.com", "full_name": "Corner Eight"}
    )

    response = api.create_check_in(
        create_check_in_payload(
            scenario["patient"]["id"],
            scenario["prescription"]["id"],
            nausea_score=4,
            vomiting_score=0,
            dehydration_flag=False,
        ),
        make_patient_headers(scenario["patient"]["id"]),
    )

    validate_error(response, "ERR_VALIDATION")
    rows, meta = validate_paginated(
        api.list_check_ins(
            platform_admin_headers(),
            params={"prescription_id": scenario["prescription"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_severe_triage_cascades_from_report_to_pharmacy_order(api):
    """PRD §3.8: "A score of **9 or above** additionally fires a five-hop cascade.
    Hop one is the triage itself landing the report in `ESCALATED`. Hop two moves
    the prescription's `clinical_status` from `ACTIVE` to `HELD`. Hop three moves
    that prescription's titration rung currently in `DUE` to `HELD` with
    `hold_reason` set to `SIDE_EFFECT`. Hop four cancels every pharmacy order citing
    that rung's `titration_step_id` whose status is `CREATED` or `RESERVED`, setting
    `cancel_reason` to `CLINICAL_HOLD`. Hop five is the stock consequence of hop
    four: each cancelled reservation returns its `units_requested` from the lot's
    `reserved_units` to its `available_units`."

    Design: Difficulty/transitive_cascade/triage_escalation_five_hop_cascade_to_supply_lot
    """
    scenario = setup_reserved_order(
        patient={"email": "jo@example.com", "full_name": "Jo Kim"},
        lot={"lot_code": "L-0002", "total_units": 24},
    )
    set_clock("2026-06-20T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
        dehydration_flag=True,
    )
    assert report["severity_score"] == 13

    triaged = triage_check_in(report["id"], scenario["clinician"]["id"])
    assert triaged["status"] == "ESCALATED"

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["clinical_status"] == "HELD"

    rung = validate_success(
        api.get_titration_step(scenario["step"]["id"], platform_admin_headers())
    )
    assert rung["status"] == "HELD"
    assert rung["hold_reason"] == "SIDE_EFFECT"

    order = validate_success(
        api.get_pharmacy_order(scenario["order"]["id"], platform_admin_headers())
    )
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "CLINICAL_HOLD"


def test_severe_triage_returns_the_reserved_units_and_rewinds_fulfilment(api):
    """PRD §2.10: "For every supply lot, `total_units` always equals
    `available_units` plus `reserved_units` plus `dispensed_units`."
    PRD §3.8: "Hop five is the stock consequence of hop four: each cancelled
    reservation returns its `units_requested` from the lot's `reserved_units` to its
    `available_units`."
    PRD §3.7: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`,
    increments the lot's `available_units` by `units_requested` and decrements its
    `reserved_units` by the same amount — restoring the pre-reservation split
    exactly, component for component — and additionally rewinds the prescription's
    `fulfillment_status` to `UNROUTED` when no other order for that prescription
    remains in `CREATED` or `RESERVED`."

    Design: Difficulty/transitive_cascade/triage_escalation_five_hop_cascade_to_supply_lot
    """
    scenario = setup_reserved_order(
        patient={"email": "jo2@example.com", "full_name": "Jo Kim"},
        lot={"lot_code": "L-0002B", "total_units": 24},
    )
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=22, reserved=2, dispensed=0
    )

    set_clock("2026-06-20T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
        dehydration_flag=True,
    )
    triage_check_in(report["id"], scenario["clinician"]["id"])

    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["fulfillment_status"] == "UNROUTED"


def test_clinical_hold_leaves_the_fulfilment_axis_at_dispensed(api):
    """PRD §3.4: "Every prescription carries **two status axes that advance
    independently**, and neither constrains the other's value."
    PRD §3.4: "A prescription frozen on the clinical axis keeps whatever value it
    had on the fulfilment axis; nothing about a hold rewinds fulfilment."
    PRD §3.8: "Hop two moves the prescription's `clinical_status` from `ACTIVE` to
    `HELD`."

    Design: Difficulty/non_linear_state_machine/prescription_parallel_clinical_and_fulfillment_axes
    """
    scenario = setup_shipped_order(
        patient={"email": "gus@example.com", "full_name": "Gus Hale"},
        lot={"lot_code": "L-0001", "total_units": 24},
    )
    dispensed = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert dispensed["fulfillment_status"] == "DISPENSED"

    set_clock("2026-06-20T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
        dehydration_flag=False,
    )
    assert report["severity_score"] == 9
    triaged = triage_check_in(report["id"], scenario["clinician"]["id"])
    assert triaged["status"] == "ESCALATED"

    frozen = read_prescription(scenario["prescription"]["id"], scenario["clinician"]["id"])
    assert frozen["clinical_status"] == "HELD"
    assert frozen["fulfillment_status"] == "DISPENSED"

    rung = validate_success(
        api.get_titration_step(scenario["step"]["id"], platform_admin_headers())
    )
    assert rung["status"] == "HELD"
    assert rung["hold_reason"] == "SIDE_EFFECT"


def test_shipped_order_survives_the_clinical_hold_cascade(api):
    """PRD §3.8: "Hop four cancels every pharmacy order citing that rung's
    `titration_step_id` whose status is `CREATED` or `RESERVED`, setting
    `cancel_reason` to `CLINICAL_HOLD`."
    PRD §3.7: "`SHIPPED` is terminal."

    Design: Difficulty/non_linear_state_machine/prescription_parallel_clinical_and_fulfillment_axes
    """
    scenario = setup_shipped_order(
        patient={"email": "gus2@example.com", "full_name": "Gus Hale"},
        lot={"lot_code": "L-0001B", "total_units": 24},
    )
    set_clock("2026-06-20T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
        dehydration_flag=False,
    )
    triage_check_in(report["id"], scenario["clinician"]["id"])

    order = validate_success(
        api.get_pharmacy_order(scenario["order"]["id"], platform_admin_headers())
    )
    assert order["status"] == "SHIPPED"
    assert order["cancel_reason"] is None
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=22, reserved=0, dispensed=2
    )


def test_rolling_index_keeps_the_severe_report_after_a_dose_change(api):
    """PRD §3.8: "- `severity_index_rolling` restricts the pool to reports whose
    `submitted_at` is strictly after the clock minus 30 days and at or before the
    clock. It knows nothing about dose history."
    PRD §3.5: "It then recomputes **both** severity indices against the current
    clock; because the since-last-dose-change window's baseline has just moved to
    now, `severity_index_since_dose_change` necessarily resets to zero, while
    `severity_index_rolling` is recomputed over its own thirty-day window and may
    well stay high."

    Design: Difficulty/dual_variant_calc/rolling_window_versus_since_dose_change_severity_index
    """
    scenario = setup_active_prescription(
        patient={"email": "dee@example.com", "full_name": "Dee Fox"}
    )
    set_clock("2026-07-08T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
    )
    triage_check_in(report["id"], scenario["clinician"]["id"])
    set_clock("2026-07-09T00:00:00Z")
    resolved = resolve_check_in(report["id"], scenario["clinician"]["id"])
    assert resolved["status"] == "RESOLVED"

    set_clock("2026-07-13T00:00:00Z")
    validate_success(
        api.escalate_titration_step(
            scenario["step"]["id"], {}, make_provider_headers(scenario["clinician"]["id"])
        )
    )

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["clinical_status"] == "ACTIVE"
    assert prescription["severity_index_rolling"] == 9, (
        "2026-07-08 still sits inside the thirty-day rolling window"
    )


def test_since_dose_change_index_resets_when_the_rung_is_escalated(api):
    """PRD §3.8: "- `severity_index_since_dose_change` restricts the pool to reports
    whose `submitted_at` is at or after the prescription's `last_dose_change_at`. A
    severe report filed before the most recent dose change is therefore invisible to
    this index while still dominating the rolling one."
    PRD §3.5: "On the prescription it increments `dose_level` by one, re-reads
    `dose_mg` from the ladder table at the new level, and sets `last_dose_change_at`
    to the clock."

    Design: Difficulty/dual_variant_calc/rolling_window_versus_since_dose_change_severity_index
    """
    scenario = setup_active_prescription(
        patient={"email": "dee2@example.com", "full_name": "Dee Fox"}
    )
    set_clock("2026-07-08T00:00:00Z")
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
    )
    triage_check_in(report["id"], scenario["clinician"]["id"])
    set_clock("2026-07-09T00:00:00Z")
    resolve_check_in(report["id"], scenario["clinician"]["id"])

    set_clock("2026-07-13T00:00:00Z")
    validate_success(
        api.escalate_titration_step(
            scenario["step"]["id"], {}, make_provider_headers(scenario["clinician"]["id"])
        )
    )

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["severity_index_since_dose_change"] == 0
    assert prescription["dose_level"] == 2
    assert_same_instant(
        prescription["last_dose_change_at"],
        "2026-07-13T00:00:00Z",
        "last_dose_change_at",
    )


def test_member_may_not_triage_a_check_in(api):
    """PRD §2.1: "When a well-formed, recognised role attempts an operation that
    role is not authorised for, the rejection is `ERR_UNAUTHORIZED` (403)."
    PRD §3.8: "**Triage** is the branch point. A `Provider` triages a submitted
    report, and the branch is decided purely by the report's own `severity_score`."

    Design: Corner/rbac/patient_cannot_triage_check_in
    """
    scenario = setup_active_prescription(
        patient={"email": "rb2@example.com", "full_name": "Rb Two"}
    )
    report = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=1,
        vomiting_score=2,
    )

    response = api.triage_check_in(
        report["id"], {}, make_patient_headers(scenario["patient"]["id"])
    )

    validate_error(response, "ERR_UNAUTHORIZED")
    untouched = validate_success(api.get_check_in(report["id"], platform_admin_headers()))
    assert untouched["status"] == "SUBMITTED"
    assert untouched["triaged_by_provider_id"] is None
