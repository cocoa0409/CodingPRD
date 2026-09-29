"""Customer sell-in: the commercial cycle, dev-state dependence and window capacity."""
import pytest

from test_helpers import (
    assert_sell_in_presentation,
    book_presentation,
    intake_project,
    open_case_with_line,
    open_reset_window,
    present_presentation,
    read_project,
    read_window,
    record_outcome,
    sell_in_presentation_payload,
    set_clock,
    setup_pilot_qualified_project,
    setup_retailer_with_window,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_presentation,
)

SNACK_WINDOW = {
    "window_start": "2026-10-12T00:00:00Z",
    "window_end": "2026-11-06T23:59:59Z",
    "max_presentations": 2,
}
SNACK_RETAILER = {"name": "SnackMart", "acv_contribution_pct": 28.00,
                  "presentation_lead_days": 21}


def _qualified_snack_project(name, owner="lead-ps", chair="chair-ps", window_overrides=None):
    ctx = setup_pilot_qualified_project(
        category="SNACK", project_type="LINE_EXTENSION",
        project_overrides={"name": name}, owner_user_id=owner, chair_user_id=chair,
    )
    retailer, window = setup_retailer_with_window(
        category="SNACK", channel="GROCERY",
        window_overrides=dict(SNACK_WINDOW, **(window_overrides or {})),
        retailer_overrides=dict(SNACK_RETAILER),
    )
    ctx["retailer"] = retailer
    ctx["window"] = window
    return ctx


def _snack_project_still_an_idea(name="Idea Stage Probe"):
    """A snack project with a full business case that has never been screened."""
    project = intake_project(owner_user_id="lead-is", name=name, category="SNACK",
                             project_type="LINE_EXTENSION")
    open_case_with_line(project["id"])
    return read_project(project["id"])


def test_the_commercial_track_returns_to_sell_in_scheduled_after_a_refusal(api):
    """A rejected pitch and a second retailer conversation walk the track back and forward.

    PRD: "The presentation starts in `PLANNED` and the project's `commercial_status` moves to
    `SELL_IN_SCHEDULED` — from `NOT_STARTED → SELL_IN_SCHEDULED` on a first booking, and equally
    from `SELL_IN_REJECTED → SELL_IN_SCHEDULED` when the team returns to a retailer after an
    earlier refusal."

    Design: Difficulty/non_linear_state_machine/project_commercial_track_cycles_while_dev_track_holds
    """
    ctx = _qualified_snack_project("Chili Lime Crisps")
    project_id = ctx["project"]["id"]
    trail = [read_project(project_id)["commercial_status"]]

    first = book_presentation(project_id, ctx["retailer"]["id"], ctx["window"]["id"],
                              scheduled_at="2026-09-14T10:00:00Z", proposed_sku_count=3)
    trail.append(read_project(project_id)["commercial_status"])
    set_clock("2026-09-14T10:00:00Z")
    present_presentation(first["id"])
    trail.append(read_project(project_id)["commercial_status"])
    first = record_outcome(first["id"], "REJECTED")
    trail.append(read_project(project_id)["commercial_status"])

    second = book_presentation(project_id, ctx["retailer"]["id"], ctx["window"]["id"],
                               scheduled_at="2026-09-15T10:00:00Z", proposed_sku_count=3)
    trail.append(read_project(project_id)["commercial_status"])
    set_clock("2026-09-15T10:00:00Z")
    present_presentation(second["id"])
    trail.append(read_project(project_id)["commercial_status"])
    second = record_outcome(second["id"], "ACCEPTED", accepted_sku_count=3)
    trail.append(read_project(project_id)["commercial_status"])

    assert trail == [
        "NOT_STARTED", "SELL_IN_SCHEDULED", "PRESENTED", "SELL_IN_REJECTED",
        "SELL_IN_SCHEDULED", "PRESENTED", "AUTHORIZED",
    ], "the commercial track re-entered SELL_IN_SCHEDULED after leaving it"
    assert first["status"] == "REJECTED"
    assert second["status"] == "ACCEPTED"
    assert read_project(project_id)["authorized_acv_pct"] == pytest.approx(28.00, abs=0.01)
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 1, (
        "the rejected presentation released its slot before the second took one"
    )


def test_the_commercial_cycle_never_moves_the_development_track(api):
    """Through two retailer conversations dev_status stays PILOT_QUALIFIED.

    PRD: "An `InnovationProject` carries two enumerated state fields that evolve independently
    on the same row."

    Design: Difficulty/non_linear_state_machine/project_commercial_track_cycles_while_dev_track_holds
    """
    ctx = _qualified_snack_project("Chili Lime Crisps")
    project_id = ctx["project"]["id"]
    dev_trail = [read_project(project_id)["dev_status"]]

    first = book_presentation(project_id, ctx["retailer"]["id"], ctx["window"]["id"],
                              scheduled_at="2026-09-14T10:00:00Z", proposed_sku_count=3)
    set_clock("2026-09-14T10:00:00Z")
    present_presentation(first["id"])
    record_outcome(first["id"], "REJECTED")
    dev_trail.append(read_project(project_id)["dev_status"])
    second = book_presentation(project_id, ctx["retailer"]["id"], ctx["window"]["id"],
                               scheduled_at="2026-09-15T10:00:00Z", proposed_sku_count=3)
    set_clock("2026-09-15T10:00:00Z")
    present_presentation(second["id"])
    record_outcome(second["id"], "ACCEPTED", accepted_sku_count=3)
    dev_trail.append(read_project(project_id)["dev_status"])

    assert dev_trail == ["PILOT_QUALIFIED", "PILOT_QUALIFIED", "PILOT_QUALIFIED"]
    project = read_project(project_id)
    assert project["next_gate_number"] == 3
    assert project["recycle_count"] == 0
    assert project["commercial_status"] == "AUTHORIZED"


def test_booking_a_presentation_from_dev_status_idea_is_refused(
    api, sales_account_manager_headers
):
    """An unqualified project cannot take a retailer slot, however complete its case.

    PRD: "From `NOT_STARTED`, booking additionally requires `dev_status` in `PILOT_QUALIFIED`,
    `LAUNCH_READY`, `LAUNCHED` or `IN_MARKET_FIX`; from `SELL_IN_REJECTED`, it requires only that
    `dev_status` be neither `KILLED` nor `DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/sell_in_presentation_depends_on_project_dev_status
    """
    ctx = _qualified_snack_project("Qualified Probe", owner="lead-sq", chair="chair-sq")
    idea = _snack_project_still_an_idea()

    response = api.create_sell_in_presentation(
        idea["id"],
        sell_in_presentation_payload(ctx["retailer"]["id"], ctx["window"]["id"],
                                     scheduled_at="2026-09-14T10:00:00Z",
                                     proposed_sku_count=3),
        sales_account_manager_headers,
    )

    validate_error(response, "ERR_PROJECT_INVALID_STATE", 409)
    refused = read_project(idea["id"])
    assert refused["dev_status"] == "IDEA"
    assert refused["commercial_status"] == "NOT_STARTED"
    _, meta = validate_paginated(
        api.list_sell_in_presentations(sales_account_manager_headers,
                                       params={"project_id": idea["id"]})
    )
    assert meta["total_count"] == 0
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 0


def test_the_identical_booking_succeeds_from_pilot_qualified(
    api, sales_account_manager_headers
):
    """The same payload against a qualified project books the slot.

    PRD: "Either way the window's `booked_slot_count` increments."

    Design: Difficulty/cross_entity_state_dependency/sell_in_presentation_depends_on_project_dev_status
    """
    ctx = _qualified_snack_project("Qualified Probe", owner="lead-sq", chair="chair-sq")
    idea = _snack_project_still_an_idea()
    payload = sell_in_presentation_payload(
        ctx["retailer"]["id"], ctx["window"]["id"], scheduled_at="2026-09-14T10:00:00Z",
        proposed_sku_count=3,
    )
    validate_error(
        api.create_sell_in_presentation(idea["id"], payload, sales_account_manager_headers),
        "ERR_PROJECT_INVALID_STATE",
        409,
    )

    booked = validate_success(
        api.create_sell_in_presentation(
            ctx["project"]["id"], payload, sales_account_manager_headers
        ),
        201,
    )

    assert_sell_in_presentation(booked)
    assert booked["status"] == "PLANNED"
    assert booked["accepted_sku_count"] is None
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "PILOT_QUALIFIED"
    assert project["commercial_status"] == "SELL_IN_SCHEDULED"
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 1


def test_a_second_booking_into_a_full_window_is_refused(api, sales_account_manager_headers):
    """A window of one slot refuses a perfectly legal second presentation.

    PRD: "The window's aggregate capacity comes first: if `booked_slot_count` has already
    reached the window's `max_presentations`, the booking answers
    `ERR_RESET_WINDOW_CAPACITY_FULL` (409) — each individual presentation is perfectly legal,
    but the collective count over the window interval is capped."

    Design: Difficulty/resource_temporal_overlap/shelf_reset_window_aggregate_slot_capacity
    """
    ctx = _qualified_snack_project("Capacity Probe", owner="lead-ap", chair="chair-ap",
                                   window_overrides={"max_presentations": 1})
    book_presentation(ctx["project"]["id"], ctx["retailer"]["id"], ctx["window"]["id"],
                      scheduled_at="2026-09-14T10:00:00Z", proposed_sku_count=3)

    response = api.create_sell_in_presentation(
        ctx["project"]["id"],
        sell_in_presentation_payload(ctx["retailer"]["id"], ctx["window"]["id"],
                                     scheduled_at="2026-09-15T10:00:00Z",
                                     proposed_sku_count=3),
        sales_account_manager_headers,
    )

    validate_error(response, "ERR_RESET_WINDOW_CAPACITY_FULL", 409)
    window = read_window(ctx["window"]["id"])
    assert window["booked_slot_count"] == 1, "the counter never passed the window's maximum"
    assert window["max_presentations"] == 1
    assert read_project(ctx["project"]["id"])["commercial_status"] == "SELL_IN_SCHEDULED"


def test_capacity_is_counted_per_window_not_per_retailer(api, sales_account_manager_headers):
    """The refused booking is accepted by the same retailer's next reset window.

    PRD: "Each window maintains `booked_slot_count`, a conserved counter equal to the number of
    trade presentations against it whose `status` is `PLANNED`, `PRESENTED`, `DEFERRED` or
    `ACCEPTED`."

    Design: Difficulty/resource_temporal_overlap/shelf_reset_window_aggregate_slot_capacity
    """
    ctx = _qualified_snack_project("Capacity Probe", owner="lead-ap", chair="chair-ap",
                                   window_overrides={"max_presentations": 1})
    later_window = open_reset_window(
        ctx["retailer"]["id"], category="SNACK", window_start="2026-11-16T00:00:00Z",
        window_end="2026-12-04T23:59:59Z", max_presentations=1,
    )
    book_presentation(ctx["project"]["id"], ctx["retailer"]["id"], ctx["window"]["id"],
                      scheduled_at="2026-09-14T10:00:00Z", proposed_sku_count=3)
    validate_error(
        api.create_sell_in_presentation(
            ctx["project"]["id"],
            sell_in_presentation_payload(ctx["retailer"]["id"], ctx["window"]["id"],
                                         scheduled_at="2026-09-15T10:00:00Z",
                                         proposed_sku_count=3),
            sales_account_manager_headers,
        ),
        "ERR_RESET_WINDOW_CAPACITY_FULL",
        409,
    )

    accepted = validate_success(
        api.create_sell_in_presentation(
            ctx["project"]["id"],
            sell_in_presentation_payload(ctx["retailer"]["id"], later_window["id"],
                                         scheduled_at="2026-09-15T10:00:00Z",
                                         proposed_sku_count=3),
            sales_account_manager_headers,
        ),
        201,
    )

    assert accepted["status"] == "PLANNED"
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 1
    assert read_window(later_window["id"])["booked_slot_count"] == 1
    _, meta = validate_paginated(
        api.list_sell_in_presentations(sales_account_manager_headers,
                                       params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 2
    assert read_project(ctx["project"]["id"])["commercial_status"] == "SELL_IN_SCHEDULED"


def test_withdrawing_a_presentation_returns_the_slot_to_the_window(
    api, sales_account_manager_headers
):
    """The counter falls back to zero the moment the conversation is withdrawn.

    PRD: "A presentation in `PLANNED`, `PRESENTED`, `DEFERRED` or `ACCEPTED` may be withdrawn
    with a `reason`, moving it to `WITHDRAWN` and decrementing the window's
    `booked_slot_count`."

    Design: Difficulty/compensating_invariant/reset_window_slot_counter_restored_after_withdraw
    """
    ctx = _qualified_snack_project("Slot Ledger Probe", owner="lead-wp", chair="chair-wp",
                                   window_overrides={"max_presentations": 1})
    booked = book_presentation(ctx["project"]["id"], ctx["retailer"]["id"],
                               ctx["window"]["id"], scheduled_at="2026-09-14T10:00:00Z",
                               proposed_sku_count=3)
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 1

    withdrawn = validate_success(
        api.withdraw_sell_in_presentation(
            booked["id"], {"reason": "Buyer meeting moved to the next reset"},
            sales_account_manager_headers,
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert read_window(ctx["window"]["id"])["booked_slot_count"] == 0
    assert read_project(ctx["project"]["id"])["authorized_acv_pct"] == pytest.approx(
        0.00, abs=0.01
    )


def test_the_released_slot_can_be_rebooked_without_double_counting(
    api, sales_account_manager_headers
):
    """A window of one slot accepts a fresh booking after the first is withdrawn.

    PRD: "The window's aggregate capacity comes first: if `booked_slot_count` has already
    reached the window's `max_presentations`, the booking answers
    `ERR_RESET_WINDOW_CAPACITY_FULL` (409) — each individual presentation is perfectly legal,
    but the collective count over the window interval is capped."

    Design: Difficulty/compensating_invariant/reset_window_slot_counter_restored_after_withdraw
    """
    ctx = _qualified_snack_project("Slot Ledger Probe", owner="lead-wp", chair="chair-wp",
                                   window_overrides={"max_presentations": 1})
    booked = book_presentation(ctx["project"]["id"], ctx["retailer"]["id"],
                               ctx["window"]["id"], scheduled_at="2026-09-14T10:00:00Z",
                               proposed_sku_count=3)
    withdraw_presentation(booked["id"], reason="Buyer meeting moved to the next reset")

    rebooked = validate_success(
        api.create_sell_in_presentation(
            ctx["project"]["id"],
            sell_in_presentation_payload(ctx["retailer"]["id"], ctx["window"]["id"],
                                         scheduled_at="2026-09-16T10:00:00Z",
                                         proposed_sku_count=3),
            sales_account_manager_headers,
        ),
        201,
    )

    assert rebooked["status"] == "PLANNED"
    window = read_window(ctx["window"]["id"])
    assert window["booked_slot_count"] == 1, "the counter came back to one, never two"
    assert window["booked_slot_count"] <= window["max_presentations"]
    withdrawn = validate_success(
        api.get_sell_in_presentation(booked["id"], sales_account_manager_headers)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    project = read_project(ctx["project"]["id"])
    assert project["commercial_status"] == "SELL_IN_SCHEDULED"
    assert project["authorized_acv_pct"] == pytest.approx(0.00, abs=0.01)
