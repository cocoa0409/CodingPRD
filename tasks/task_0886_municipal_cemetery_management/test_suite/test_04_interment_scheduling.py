"""Interment scheduling gates: capacity, double-booking, crew window, occupancy."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    setup_scheduled_interment, setup_pending_deed, setup_issued_deed, add_second_interment,
    create_cemetery, create_plot, create_holder, create_decedent, pay_invoice,
    create_deed_payload, create_interment_payload, set_clock, CLOCK_DEFAULT,
)

REG = TEST_USERS["registrar_headers"]


def _single_crew_two_issued_plots():
    """One crew_team_count=1 cemetery with two SOLD plots (ISSUED deeds)."""
    set_clock(CLOCK_DEFAULT)
    cem = create_cemetery(crew_team_count=1)
    holder = create_holder()
    p1 = create_plot(cem["id"], plot_number="1", gis_lng=2.0)
    p2 = create_plot(cem["id"], plot_number="2", gis_lng=2.1)
    d1 = get_success_data(api_client.create_deed(
        create_deed_payload(p1["id"], holder["id"], p1["version"]), REG))
    pay_invoice(d1["sale_invoice_id"])
    d2 = get_success_data(api_client.create_deed(
        create_deed_payload(p2["id"], holder["id"], p2["version"]), REG))
    pay_invoice(d2["sale_invoice_id"])
    return cem, p1, p2, d1, d2, holder


# ── Difficulty: boundary_precision_check / plot_capacity_full_blocks_schedule ──

def test_first_schedule_below_capacity_succeeds(api):
    """PRD §3.3: "The plot's interments_used must be strictly below its
    interment_capacity, otherwise ERR_PLOT_CAPACITY."

    Design: Difficulty/boundary_precision_check/plot_capacity_full_blocks_schedule
    """
    r = setup_scheduled_interment(interment_capacity=1)
    assert r["interment"]["operational_status"] == "SCHEDULED"
    plot = validate_success(api.get_plot(r["plot"]["id"], REG), 200)
    assert plot["interments_used"] == 1


def test_second_schedule_at_capacity_rejected(api):
    """PRD §3.3: "The plot's interments_used must be strictly below its
    interment_capacity, otherwise ERR_PLOT_CAPACITY."

    Design: Difficulty/boundary_precision_check/plot_capacity_full_blocks_schedule
    """
    r = setup_scheduled_interment(interment_capacity=1)
    dec2 = create_decedent(full_name="Dec B", date_of_death="2026-04-02")
    res = api.create_interment(create_interment_payload(
        r["plot"]["id"], dec2["id"], r["deed"]["id"], depth_position=2,
        scheduled_date="2026-06-08", scheduled_start="2026-06-08T09:00:00Z",
        scheduled_end="2026-06-08T11:00:00Z"), REG)
    validate_error(res, "ERR_PLOT_CAPACITY")


# ── Difficulty: resource_temporal_overlap / plot_same_date_double_booking ──

def test_second_interment_same_date_double_booked(api):
    """PRD §3.3: "a plot may hold at most one non-cancelled interment on any single
    scheduled_date; a second booking on the same day is rejected with
    ERR_PLOT_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/plot_same_date_double_booking
    """
    r = setup_scheduled_interment(crew_team_count=2, interment_capacity=2)
    dec2 = create_decedent(full_name="Dec B", date_of_death="2026-04-02")
    res = api.create_interment(create_interment_payload(
        r["plot"]["id"], dec2["id"], r["deed"]["id"], interment_type="ENTOMBMENT",
        depth_position=2, scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T14:00:00Z", scheduled_end="2026-06-01T16:00:00Z"), REG)
    validate_error(res, "ERR_PLOT_DOUBLE_BOOKED")


def test_second_interment_different_date_allowed(api):
    """PRD §3.3: "a plot may hold at most one non-cancelled interment on any single
    scheduled_date; a second booking on the same day is rejected with
    ERR_PLOT_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/plot_same_date_double_booking
    """
    r = setup_scheduled_interment(crew_team_count=2, interment_capacity=2)
    second = add_second_interment(r)  # 2026-06-08, distinct date
    assert second["operational_status"] == "SCHEDULED"


# ── Difficulty: resource_temporal_overlap / crew_time_window_buffer_collision ──

def test_crew_window_within_buffer_collides(api):
    """PRD §3.3: "for the same calendar day, the count of existing interments (those
    with operational_status of SCHEDULED, OPENED, or COMPLETED) whose buffered window
    intersects the new buffered window must be strictly less than the cemetery's
    crew_team_count, otherwise ERR_CREW_UNAVAILABLE."

    Design: Difficulty/resource_temporal_overlap/crew_time_window_buffer_collision
    """
    cem, p1, p2, d1, d2, holder = _single_crew_two_issued_plots()
    dec1 = create_decedent(full_name="Dec A", date_of_death="2026-04-01")
    dec2 = create_decedent(full_name="Dec B", date_of_death="2026-04-02")
    validate_success(api.create_interment(create_interment_payload(
        p1["id"], dec1["id"], d1["id"], scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T11:00:00Z"), REG), 201)
    # 30-minute gap (11:00 -> 11:30) is smaller than the 60-minute buffer.
    res = api.create_interment(create_interment_payload(
        p2["id"], dec2["id"], d2["id"], scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T11:30:00Z", scheduled_end="2026-06-01T13:00:00Z"), REG)
    validate_error(res, "ERR_CREW_UNAVAILABLE")


def test_crew_window_exactly_buffer_gap_allowed(api):
    """PRD §3.3: "windows that merely touch at an endpoint do not overlap, while any
    gap smaller than the 60-minute buffer does count as an overlap."

    Design: Difficulty/resource_temporal_overlap/crew_time_window_buffer_collision
    """
    cem, p1, p2, d1, d2, holder = _single_crew_two_issued_plots()
    dec1 = create_decedent(full_name="Dec A", date_of_death="2026-04-01")
    dec2 = create_decedent(full_name="Dec B", date_of_death="2026-04-02")
    validate_success(api.create_interment(create_interment_payload(
        p1["id"], dec1["id"], d1["id"], scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T11:00:00Z"), REG), 201)
    # Exactly 60-minute gap (11:00 -> 12:00): not smaller than the buffer, so allowed.
    second = validate_success(api.create_interment(create_interment_payload(
        p2["id"], dec2["id"], d2["id"], scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T12:00:00Z", scheduled_end="2026-06-01T13:00:00Z"), REG), 201)
    assert second["operational_status"] == "SCHEDULED"


# ── Difficulty: compensating_invariant / plot_occupancy_count_conserved ──

def test_two_schedules_raise_occupancy_to_two(api):
    """PRD §3.1: "The interments_used field is always the count of interments on the
    plot whose operational_status is SCHEDULED, OPENED, or COMPLETED"

    Design: Difficulty/compensating_invariant/plot_occupancy_count_conserved
    """
    r = setup_scheduled_interment(crew_team_count=2, interment_capacity=2)
    add_second_interment(r)
    plot = validate_success(api.get_plot(r["plot"]["id"], REG), 200)
    assert plot["interments_used"] == 2


def test_cancel_restores_occupancy_count(api):
    """PRD §3.1: "it is maintained so that scheduling an interment and later
    cancelling or disinterring it restores the prior count exactly."

    Design: Difficulty/compensating_invariant/plot_occupancy_count_conserved
    """
    r = setup_scheduled_interment(crew_team_count=2, interment_capacity=2)
    add_second_interment(r)
    validate_success(api.cancel_interment(r["interment"]["id"], REG), 200)
    plot = validate_success(api.get_plot(r["plot"]["id"], REG), 200)
    assert plot["interments_used"] == 1


# ── Difficulty: cross_entity_state_dependency / interment_requires_issued_deed ──

def test_pending_deed_blocks_interment_scheduling(api):
    """PRD §3.3: "The referenced deed must be ISSUED; if it is in any other state the
    scheduling is rejected with ERR_DEED_NOT_ISSUED."

    Design: Difficulty/cross_entity_state_dependency/interment_requires_issued_deed
    """
    set_clock(CLOCK_DEFAULT)
    r = setup_pending_deed()
    dec = create_decedent()
    res = api.create_interment(create_interment_payload(
        r["plot"]["id"], dec["id"], r["deed"]["id"], scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T11:00:00Z"), REG)
    validate_error(res, "ERR_DEED_NOT_ISSUED")


def test_issued_deed_allows_interment_scheduling(api):
    """PRD §3.3: "The referenced deed must be ISSUED; if it is in any other state the
    scheduling is rejected with ERR_DEED_NOT_ISSUED."

    Design: Difficulty/cross_entity_state_dependency/interment_requires_issued_deed
    """
    r = setup_scheduled_interment()  # deed is ISSUED before scheduling
    assert r["interment"]["operational_status"] == "SCHEDULED"


# ── Difficulty: priority_pair_validation_conflict / interment_referential_beats_temporal ──

def test_referential_gate_reported_over_temporal(api):
    """PRD §2.5: "the first failing rung determines the error returned"; the ladder
    ranks "Cross-entity referential gates" (rung 7) above "Temporal gates" (rung 9).
    PRD §3.3: "The referenced deed must be ISSUED; if it is in any other state the
    scheduling is rejected with ERR_DEED_NOT_ISSUED."

    Design: Difficulty/priority_pair_validation_conflict/interment_referential_beats_temporal
    """
    set_clock(CLOCK_DEFAULT)
    r = setup_pending_deed()
    dec = create_decedent(full_name="Dec A", date_of_death="2026-03-01")
    res = api.create_interment(create_interment_payload(
        r["plot"]["id"], dec["id"], r["deed"]["id"], scheduled_date="2026-04-01",
        scheduled_start="2026-04-01T09:00:00Z", scheduled_end="2026-04-01T11:00:00Z"), REG)
    validate_error(res, "ERR_DEED_NOT_ISSUED")


def test_referential_gate_not_masked_by_past_date(api):
    """PRD §2.5: "the first failing rung determines the error returned"; with
    "Cross-entity referential gates" (rung 7) ranked above "Temporal gates" (rung 9), a
    pending deed with a past date reports the deed error, not ERR_DATE_IN_PAST.

    Design: Difficulty/priority_pair_validation_conflict/interment_referential_beats_temporal
    """
    set_clock(CLOCK_DEFAULT)
    r = setup_pending_deed()
    dec = create_decedent(full_name="Dec A", date_of_death="2026-03-01")
    res = api.create_interment(create_interment_payload(
        r["plot"]["id"], dec["id"], r["deed"]["id"], scheduled_date="2026-04-15",
        scheduled_start="2026-04-15T09:00:00Z", scheduled_end="2026-04-15T11:00:00Z"), REG)
    body = res.json()["data"]
    assert body["error_id"] == "ERR_DEED_NOT_ISSUED"
    assert body["error_id"] != "ERR_DATE_IN_PAST"


# ── Corner: validations / schedule_future_deed_issued_but_date_in_past ──

def test_issued_deed_past_date_rejected(api):
    """PRD §3.3: "The scheduled_date may not be earlier than the current logical-clock
    date, otherwise ERR_DATE_IN_PAST."

    Design: Corner/validations/schedule_future_deed_issued_but_date_in_past
    """
    set_clock(CLOCK_DEFAULT)
    base = setup_issued_deed()
    dec = create_decedent()
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_interment(create_interment_payload(
        base["plot"]["id"], dec["id"], base["deed"]["id"], scheduled_date="2026-05-01",
        scheduled_start="2026-05-01T09:00:00Z", scheduled_end="2026-05-01T11:00:00Z"), REG)
    validate_error(res, "ERR_DATE_IN_PAST")


# ── Corner: validations / interment_end_before_start_validation ──

def test_interment_end_before_start_validation(api):
    """PRD §2.5: "scheduled_end strictly after scheduled_start, else ERR_VALIDATION
    (400)."

    Design: Corner/validations/interment_end_before_start_validation
    """
    set_clock(CLOCK_DEFAULT)
    base = setup_issued_deed()
    dec = create_decedent()
    res = api.create_interment(create_interment_payload(
        base["plot"]["id"], dec["id"], base["deed"]["id"], scheduled_date="2026-06-01",
        scheduled_start="2026-06-01T11:00:00Z", scheduled_end="2026-06-01T09:00:00Z"), REG)
    validate_error(res, "ERR_VALIDATION")
