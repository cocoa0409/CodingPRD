"""Audit calendars: closed windows, notice and gap arithmetic, and the empty-scope boundary."""
from test_helpers import (
    AM,
    ApiErrorId,
    api_client,
    assert_audit_scope_identity,
    assert_floor_plan_audit,
    floor_unit,
    read_dealer,
    reconcile_audit,
    record_observation,
    schedule_audit,
    schedule_audit_payload,
    set_clock,
    setup_active_line,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dealer_without_inventory(legal_name):
    """An ACTIVE dealer and line carrying no units at all, so audits can close clean."""
    return setup_active_line(
        dealer_overrides={"legal_name": legal_name, "franchise_type": "INDEPENDENT_USED",
                          "state_code": "SD"},
        credit_limit_cents=100000000,
    )


def _schedule(dealer_id, start_date, end_date, audit_type="ANNOUNCED"):
    """Raw scheduling call, so refusals can be inspected."""
    return api_client.schedule_audit(
        schedule_audit_payload(dealer_id, start_date, end_date, audit_type), AM
    )


def test_a_new_window_touching_an_existing_end_date_collides():
    """Audit windows are closed intervals, so an abutting window is refused, unlike a ladder rung.

    PRD: "Finally, the new closed window must not intersect the closed window of any existing audit of the same dealership whose `status` is `SCHEDULED`, `IN_PROGRESS`, `RECONCILED_CLEAN` or `RECONCILED_EXCEPTIONS`; **touching endpoints do collide**, so an existing window ending on 2026-08-10 blocks a new one starting on 2026-08-10, and the refusal is `ERR_AUDIT_WINDOW_OVERLAP`."

    PRD: "An `ANNOUNCED` count must give the dealership at least 7 days of notice, so `window_start_date` must be at least 7 days after the current logical-clock date; exactly 7 days is acceptable, and less is `ERR_AUDIT_NOTICE_TOO_SHORT`."

    Design: Difficulty/resource_temporal_overlap/audit_windows_are_closed_intervals_and_unannounced_needs_a_fourteen_day_gap
    """
    ctx = _dealer_without_inventory("Calendar Collision Motors LLC")
    dealer_id = ctx["dealer"]["id"]

    booked = validate_success(_schedule(dealer_id, "2026-08-10", "2026-08-12"), expected_status=201)
    assert_floor_plan_audit(booked)
    assert booked["status"] == "SCHEDULED"
    assert str(booked["window_start_date"])[:10] == "2026-08-10"
    assert str(booked["window_end_date"])[:10] == "2026-08-12"
    assert booked["units_in_scope_count"] == 0
    assert booked["observer_user_ids"] == []

    validate_error(
        _schedule(dealer_id, "2026-08-12", "2026-08-14"),
        ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP,
        409,
    )
    validate_error(
        _schedule(dealer_id, "2026-08-05", "2026-08-06"),
        ApiErrorId.ERR_AUDIT_NOTICE_TOO_SHORT,
        422,
    )

    rows, meta = validate_paginated(api_client.list_audits(AM, params={"dealer_id": dealer_id}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == booked["id"]


def test_an_unannounced_count_needs_fourteen_days_after_the_last_reconciled_window():
    """Thirteen days past the reconciled window end is refused; exactly fourteen is accepted.

    PRD: "An `UNANNOUNCED` count needs no notice at all — that is its whole point — but it may not be used to harass a dealership, so its `window_start_date` must be at least 14 days after the `window_end_date` of that dealership's most recent count that reached either reconciled outcome; exactly 14 days is acceptable, and less is `ERR_AUDIT_GAP_TOO_SHORT`."

    Design: Difficulty/resource_temporal_overlap/audit_windows_are_closed_intervals_and_unannounced_needs_a_fourteen_day_gap
    """
    ctx = _dealer_without_inventory("Calendar Collision Motors LLC")
    dealer_id = ctx["dealer"]["id"]
    first = schedule_audit(dealer_id, "2026-08-10", "2026-08-12")
    set_clock("2026-08-10T00:00:00Z")
    start_audit(first["id"])
    reconciled = reconcile_audit(first["id"], notes="No floored inventory to count")
    assert reconciled["status"] == "RECONCILED_CLEAN"
    assert reconciled["units_in_scope_count"] == 0
    assert reconciled["sot_exposure_cents"] == 0

    validate_error(
        _schedule(dealer_id, "2026-08-25", "2026-08-25", "UNANNOUNCED"),
        ApiErrorId.ERR_AUDIT_GAP_TOO_SHORT,
        422,
    )
    accepted = validate_success(
        _schedule(dealer_id, "2026-08-26", "2026-08-26", "UNANNOUNCED"), expected_status=201
    )
    assert accepted["audit_type"] == "UNANNOUNCED"
    assert accepted["status"] == "SCHEDULED"

    rows, meta = validate_paginated(api_client.list_audits(AM, params={"dealer_id": dealer_id}))
    assert meta["total_count"] == 2
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[first["id"]] == "RECONCILED_CLEAN"
    assert statuses[accepted["id"]] == "SCHEDULED"


def test_an_unannounced_window_may_not_span_more_than_three_calendar_days():
    """A five-day surprise window is refused even though its gap and overlap checks pass.

    PRD: "An `UNANNOUNCED` window may span at most three calendar days, meaning `window_end_date` may be no more than 2 days after `window_start_date`, and for every audit type `window_end_date` must not precede `window_start_date`; a violation of either is `ERR_UNANNOUNCED_WINDOW_INVALID`."

    Design: Difficulty/resource_temporal_overlap/audit_windows_are_closed_intervals_and_unannounced_needs_a_fourteen_day_gap
    """
    ctx = _dealer_without_inventory("Calendar Collision Motors LLC")
    dealer_id = ctx["dealer"]["id"]
    first = schedule_audit(dealer_id, "2026-08-10", "2026-08-12")
    set_clock("2026-08-10T00:00:00Z")
    start_audit(first["id"])
    reconcile_audit(first["id"], notes="No floored inventory to count")

    validate_error(
        _schedule(dealer_id, "2026-09-10", "2026-09-14", "UNANNOUNCED"),
        ApiErrorId.ERR_UNANNOUNCED_WINDOW_INVALID,
        422,
    )

    rows, meta = validate_paginated(api_client.list_audits(AM, params={"dealer_id": dealer_id}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def _one_unit_and_one_empty_lot():
    """Dealer A with a single FLOORED unit and dealer B with nothing, each mid-count."""
    a = setup_active_line(
        dealer_overrides={"legal_name": "Cardinality A Motors LLC", "state_code": "AZ"},
        credit_limit_cents=500000000,
    )
    floored = floor_unit(
        a["dealer"]["id"],
        a["credit_line"]["id"],
        "CARDAUNIT0000010",
        dealer_headers=a["dealer_headers"],
        requested_amount_cents=3000000,
        document_reference="MSO-0014A",
        disbursement_reference="WIRE-0014A",
        invoice_amount_cents=3000000,
        odometer_miles=12,
    )
    b = _dealer_without_inventory("Cardinality B Motors LLC")
    audit_a = schedule_audit(a["dealer"]["id"], "2026-08-10", "2026-08-12")
    audit_b = schedule_audit(b["dealer"]["id"], "2026-08-10", "2026-08-12")
    set_clock("2026-08-10T00:00:00Z")
    started_a = start_audit(audit_a["id"])
    started_b = start_audit(audit_b["id"])
    return {
        "dealer_a": a["dealer"],
        "dealer_b": b["dealer"],
        "unit": floored["unit"],
        "audit_a": started_a,
        "audit_b": started_b,
    }


def test_an_empty_observation_set_is_legal_only_when_the_scope_froze_empty():
    """Scope one with no readings is refused; scope zero with no readings signs off clean.

    PRD: "And an audit that froze at least one unit into scope must have produced at least one reading: if `units_in_scope_count` is greater than zero while `units_verified_count` plus `units_exception_count` is zero, the request is refused with `ERR_AUDIT_NO_OBSERVATIONS`, because a count with no readings is a refusal to count rather than a clean result."

    Design: Difficulty/boundary_precision_check/reconcile_boundary_between_zero_observations_and_zero_units_in_scope
    """
    ctx = _one_unit_and_one_empty_lot()
    assert ctx["audit_a"]["units_in_scope_count"] == 1
    assert ctx["audit_b"]["units_in_scope_count"] == 0

    validate_error(
        api_client.reconcile_audit(
            ctx["audit_a"]["id"],
            {"notes": "Attempting sign-off with an empty observation set"},
            AM,
        ),
        ApiErrorId.ERR_AUDIT_NO_OBSERVATIONS,
        409,
    )
    still_open = validate_success(api_client.get_audit(ctx["audit_a"]["id"], AM))
    assert still_open["status"] == "IN_PROGRESS"
    assert read_dealer(ctx["dealer_a"]["id"])["audit_in_progress"] is True

    empty = validate_success(
        api_client.reconcile_audit(
            ctx["audit_b"]["id"], {"notes": "Nothing on the lot to count"}, AM
        )
    )
    assert empty["status"] == "RECONCILED_CLEAN"
    assert empty["sot_exposure_cents"] == 0
    assert empty["units_verified_count"] == 0
    assert empty["units_exception_count"] == 0
    assert empty["units_unobserved_count"] == 0
    assert empty["observer_user_ids"] == []
    assert_audit_scope_identity(empty)


def test_one_reading_unblocks_the_same_sign_off_and_resets_the_cadence():
    """A single verified reading turns the refused audit into a clean one and moves the due date.

    PRD: "Both outcomes share the same join point: `reconciled_at` is stamped from the logical clock, `reconciled_by_user_id` is set from `X-User-ID`, the dealership's `audit_in_progress` returns to false, the risk assessment of §2.10 re-runs, and `next_audit_due_at` is then rewritten as `reconciled_at` plus the dealership's (possibly just-changed) `audit_frequency_days`."

    Design: Difficulty/boundary_precision_check/reconcile_boundary_between_zero_observations_and_zero_units_in_scope
    """
    ctx = _one_unit_and_one_empty_lot()
    validate_error(
        api_client.reconcile_audit(ctx["audit_a"]["id"], {"notes": "Too early"}, AM),
        ApiErrorId.ERR_AUDIT_NO_OBSERVATIONS,
        409,
    )

    reading = record_observation(
        ctx["audit_a"]["id"], ctx["unit"]["id"], "PRESENT", True, odometer_miles=12
    )
    assert reading["classification"] == "VERIFIED"
    assert reading["is_out_of_trust"] is False

    signed = reconcile_audit(ctx["audit_a"]["id"], notes="One unit counted and verified")
    assert signed["status"] == "RECONCILED_CLEAN"
    assert signed["units_verified_count"] == 1
    assert signed["units_exception_count"] == 0
    assert signed["units_unobserved_count"] == 0
    assert signed["sot_exposure_cents"] == 0
    assert signed["reconciled_by_user_id"] == AM["X-User-ID"]
    assert str(signed["reconciled_at"]).startswith("2026-08-10T00:00:00")
    assert_audit_scope_identity(signed)

    dealer_a = read_dealer(ctx["dealer_a"]["id"])
    assert dealer_a["audit_in_progress"] is False
    assert dealer_a["open_sot_incident_count"] == 0
    assert dealer_a["risk_rating"] == "A"
    assert dealer_a["audit_frequency_days"] == 180
    assert str(dealer_a["next_audit_due_at"]).startswith("2027-02-06T00:00:00")

    reconcile_audit(ctx["audit_b"]["id"], notes="Nothing on the lot to count")
    dealer_b = read_dealer(ctx["dealer_b"]["id"])
    assert dealer_b["risk_rating"] == "A"
    assert str(dealer_b["next_audit_due_at"]).startswith("2027-02-06T00:00:00")
