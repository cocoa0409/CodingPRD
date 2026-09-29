"""Rejection precedence: when one request breaks two rules, which one is reported.

Each suite builds a request that breaks exactly two declared rules at once and
proves two things: the earlier rule in the platform's ordered rejection list is
the one reported, and nothing the later rule's path would have written was
written. A companion case in each suite fires the later rule on its own, so the
precedence claim rests on a check that is demonstrably live rather than absent.
"""

import pytest

from test_helpers import (
    FLEET_OPS_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_fields,
    create_ticket,
    dispatch_payload,
    fetch_device,
    fetch_service_ticket,
    fetch_technician,
    list_reads_for_device,
    make_field_technician_headers,
    make_fleet_ops_headers,
    meter_read_payload,
    resolve_ticket_payload,
    setup_dispatched_ticket,
    setup_onsite_ticket,
    setup_print_environment,
    submit_automated_read,
    validate_error,
)

OPS = TEST_USERS["fleet_ops_headers"]

DISPATCH_CLOCK = "2026-08-05T08:00:00Z"
WINDOW_START = "2026-08-05T09:00:00Z"
WINDOW_END = "2026-08-05T10:00:00Z"

# One L1 technician based outside the site's region, and one L2 technician also
# based outside it: the first breaks both dispatch rules, the second only one.
UNCERTIFIED_OUT_OF_REGION = {
    "full_name": "Ivo Mendes",
    "home_region": "SE-02",
    "skill_level": "L1",
    "travel_buffer_minutes": 30,
}
CERTIFIED_OUT_OF_REGION = {
    "full_name": "Ada Fern",
    "home_region": "SE-02",
    "skill_level": "L2",
    "travel_buffer_minutes": 30,
}

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
READ_CLOCK = "2026-08-20T00:00:00Z"
FIRST_COVERAGE_END = "2026-08-15T00:00:00Z"
FIRST_MONO_METER = 5_000
FIRST_TONER_PCT = 80
SECOND_MONO_METER = 9_000
SECOND_TONER_PCT = 70


def _dispatched_ticket_that_never_arrived_onsite():
    """A STANDARD ticket sitting in DISPATCHED: nobody has recorded an arrival."""
    return setup_dispatched_ticket(
        severity="STANDARD",
        symptom_code="PAPER_JAM",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        clock=DISPATCH_CLOCK,
    )


def _resolve(env, labor_hours):
    """Resolve as the assigned technician, so ownership never masks the outcome."""
    return api_client.resolve_service_ticket(
        env["ticket_id"],
        resolve_ticket_payload(labor_hours=labor_hours),
        make_field_technician_headers(env["technician_id"]),
    )


class TestTicketStateGateOutranksLabourCeiling:
    """Resolving a DISPATCHED ticket with 12 reported hours breaks two rules at once."""

    @pytest.mark.parametrize("labor_hours", [9, 12])
    def test_the_state_gate_is_reported_and_the_labour_ceiling_is_not(self, labor_hours):
        """A ticket that never reached ONSITE reports its state, whatever the hours.

        PRD: "When a single request violates more than one rule, the response must report the violation that comes **first** in the ordered list below, not whichever check the implementation happens to run first."
        PRD: "The list is exhaustive and strictly ascending; a rule that appears later can never mask a rule that appears earlier."
        PRD: "**Transition existence.** The target resource is in a state from which the requested transition exists — otherwise `ERR_CONTRACT_INVALID_STATE`, `ERR_DEVICE_INVALID_STATE`, `ERR_READ_INVALID_STATE`, `ERR_PERIOD_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_TICKET_INVALID_STATE`, `ERR_REVIEW_ALREADY_APPROVED` or `ERR_REMOVAL_INVALID_STATE` (all 409). Applies to every action endpoint."
        PRD: "**Labour ceiling.** Reported `labor_hours` must not exceed 8 hours per ticket — otherwise `ERR_LABOR_HOURS_EXCEED_LIMIT` (422). Applies to `POST /service-tickets/{id}/resolve`."
        PRD: "Attempting resolution on a ticket that never reached `ONSITE` reports `ERR_TICKET_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/ticket_state_gate_outranks_labor_hour_ceiling_on_resolve
        """
        env = _dispatched_ticket_that_never_arrived_onsite()
        assert_fields(env["ticket"], status="DISPATCHED")

        error = validate_error(_resolve(env, labor_hours), ApiErrorId.ERR_TICKET_INVALID_STATE)

        assert error["error_id"] != ApiErrorId.ERR_LABOR_HOURS_EXCEED_LIMIT, (
            "the labour ceiling sits later in the ordered list and must not be "
            f"reported ahead of the state gate: {error}"
        )

    def test_the_rejected_resolution_writes_none_of_the_resolution_numbers(self):
        """No hours, no labour cost, no response stamp, no downward dispatch count.

        PRD: "Resolution performs `ONSITE → RESOLVED`, stamps `responded_at` from the logical clock, recomputes the technician's `open_dispatch_count` downward, increments the ticket's `version`, and cascades onto the hardware: when the device's `lifecycle_state` is `SERVICE_HOLD` it returns `SERVICE_HOLD → ACTIVE` with its own `version` increment, making `ACTIVE → SERVICE_HOLD → ACTIVE` a cycle that repeats once per dispatched ticket."
        PRD: "The new ticket has `status` `OPEN`, a null `assigned_technician_id`, a null `window_start` and `window_end` until a dispatch reserves them, a null `hold_started_at` and `responded_at`, a `parts_hold_hours`, `hours_late`, `labor_hours`, `labor_cents` and `sla_credit_cents` of 0, `opened_at` stamped from the logical clock, and — this is the response-time commitment made concrete — a `respond_by` deadline computed as `opened_at` plus the contract's `response_sla_hours_critical` hours when `severity` is `CRITICAL`, or plus the contract's `response_sla_hours_standard` hours when `severity` is `STANDARD`."
        PRD: "Successful dispatch performs `OPEN → DISPATCHED`, writes `assigned_technician_id` from the supplied `technician_id`, recomputes the technician's `open_dispatch_count` upward, increments the ticket's `version`, and cascades onto the hardware: when the ticket's device has a `lifecycle_state` of `ACTIVE`, that device moves `ACTIVE → SERVICE_HOLD` and its own `version` increments."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number of tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or `ONSITE`."

        Design: Difficulty/priority_pair_validation_conflict/ticket_state_gate_outranks_labor_hour_ceiling_on_resolve
        """
        env = _dispatched_ticket_that_never_arrived_onsite()

        validate_error(_resolve(env, 12), ApiErrorId.ERR_TICKET_INVALID_STATE)

        ticket = fetch_service_ticket(env["ticket_id"])
        assert_fields(
            ticket,
            status="DISPATCHED",
            labor_hours=0,
            labor_cents=0,
            sla_credit_cents=0,
            hours_late=0,
            assigned_technician_id=env["technician_id"],
        )
        assert ticket["responded_at"] is None, (
            f"a rejected resolution must not stamp responded_at: {ticket['responded_at']}"
        )
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="SERVICE_HOLD")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=1)

    def test_the_labour_ceiling_still_bites_once_the_state_gate_is_satisfied(self):
        """Same 12 hours on an ONSITE ticket: now the later rule is the one reported.

        PRD: "A `FieldTechnician` resolves an `ONSITE` ticket by reporting `labor_hours` (zero or greater, and never more than 8 hours per ticket — a larger figure reports `ERR_LABOR_HOURS_EXCEED_LIMIT`)."
        PRD: "**Labour ceiling.** Reported `labor_hours` must not exceed 8 hours per ticket — otherwise `ERR_LABOR_HOURS_EXCEED_LIMIT` (422). Applies to `POST /service-tickets/{id}/resolve`."

        Design: Difficulty/priority_pair_validation_conflict/ticket_state_gate_outranks_labor_hour_ceiling_on_resolve
        """
        env = setup_onsite_ticket(
            severity="STANDARD",
            symptom_code="PAPER_JAM",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            clock=DISPATCH_CLOCK,
        )
        assert_fields(env["ticket"], status="ONSITE")

        validate_error(_resolve(env, 12), ApiErrorId.ERR_LABOR_HOURS_EXCEED_LIMIT)

        assert_fields(fetch_service_ticket(env["ticket_id"]), status="ONSITE", labor_hours=0)


def _open_critical_ticket_and_two_out_of_region_technicians():
    """A CRITICAL ticket, plus an L1 and an L2 technician who both live elsewhere.

    The device sits at a site in the default NE-01 region, so either extra
    technician breaks the region rule; only the L1 also breaks the certification
    rule, which lets the two cases be told apart.
    """
    env = setup_print_environment(
        extra_technicians=[dict(UNCERTIFIED_OUT_OF_REGION), dict(CERTIFIED_OUT_OF_REGION)],
        clock=DISPATCH_CLOCK,
    )
    env["uncertified"] = env["technicians"][1]
    env["certified_elsewhere"] = env["technicians"][2]
    env["ticket"] = create_ticket(
        env["device_id"], env["site_id"], severity="CRITICAL", symptom_code="FUSER_FAIL"
    )
    env["ticket_id"] = env["ticket"]["id"]
    return env


def _dispatch(ticket_id, technician_id):
    """Reserve the 09:00-10:00 slot, an hour after the logical clock."""
    return api_client.dispatch_service_ticket(
        ticket_id, dispatch_payload(technician_id, WINDOW_START, WINDOW_END), OPS
    )


class TestCriticalCertificationGateOutranksRegionMismatch:
    """Dispatching a CRITICAL ticket to an L1 technician in the wrong region."""

    def test_the_certification_gate_is_reported_and_the_region_mismatch_is_not(self):
        """One dispatch breaks both rules; the earlier certification rule answers.

        PRD: "When a single request violates more than one rule, the response must report the violation that comes **first** in the ordered list below, not whichever check the implementation happens to run first."
        PRD: "The list is exhaustive and strictly ascending; a rule that appears later can never mask a rule that appears earlier."
        PRD: "**Technician certification.** A `CRITICAL` ticket may only be dispatched to a technician whose `skill_level` is `L2` or `L3` — otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` (422). Applies to `POST /service-tickets/{id}/dispatch`."
        PRD: "**Dispatch region match.** The dispatched technician's `home_region` equals the `address_region` of the site hosting the ticket's device — otherwise `ERR_TECHNICIAN_REGION_MISMATCH` (422). Applies to `POST /service-tickets/{id}/dispatch`."

        Design: Difficulty/priority_pair_validation_conflict/critical_certification_gate_outranks_region_mismatch_on_dispatch
        """
        env = _open_critical_ticket_and_two_out_of_region_technicians()
        assert_fields(env["uncertified"], skill_level="L1", home_region="SE-02")
        assert env["uncertified"]["home_region"] != env["site"]["address_region"], (
            "the fixture technician must sit outside the hosting site's region"
        )

        error = validate_error(
            _dispatch(env["ticket_id"], env["uncertified"]["id"]),
            ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED,
        )

        assert error["error_id"] != ApiErrorId.ERR_TECHNICIAN_REGION_MISMATCH, (
            "the region rule sits later in the ordered list and must not be "
            f"reported ahead of the certification rule: {error}"
        )

    def test_the_rejected_dispatch_reserves_nothing_and_holds_no_hardware(self):
        """No assignment, no window, no raised dispatch count, no SERVICE_HOLD.

        PRD: "Successful dispatch performs `OPEN → DISPATCHED`, writes `assigned_technician_id` from the supplied `technician_id`, recomputes the technician's `open_dispatch_count` upward, increments the ticket's `version`, and cascades onto the hardware: when the ticket's device has a `lifecycle_state` of `ACTIVE`, that device moves `ACTIVE → SERVICE_HOLD` and its own `version` increments."
        PRD: "The new ticket has `status` `OPEN`, a null `assigned_technician_id`, a null `window_start` and `window_end` until a dispatch reserves them, a null `hold_started_at` and `responded_at`, a `parts_hold_hours`, `hours_late`, `labor_hours`, `labor_cents` and `sla_credit_cents` of 0, `opened_at` stamped from the logical clock, and — this is the response-time commitment made concrete — a `respond_by` deadline computed as `opened_at` plus the contract's `response_sla_hours_critical` hours when `severity` is `CRITICAL`, or plus the contract's `response_sla_hours_standard` hours when `severity` is `STANDARD`."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number of tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or `ONSITE`."

        Design: Difficulty/priority_pair_validation_conflict/critical_certification_gate_outranks_region_mismatch_on_dispatch
        """
        env = _open_critical_ticket_and_two_out_of_region_technicians()

        validate_error(
            _dispatch(env["ticket_id"], env["uncertified"]["id"]),
            ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED,
        )

        ticket = fetch_service_ticket(env["ticket_id"])
        assert_fields(ticket, status="OPEN", severity="CRITICAL")
        assert ticket["assigned_technician_id"] is None, (
            f"a rejected dispatch must not assign a technician: {ticket}"
        )
        assert ticket["window_start"] is None and ticket["window_end"] is None, (
            f"a rejected dispatch must not reserve a slot: {ticket}"
        )
        assert_fields(fetch_technician(env["uncertified"]["id"]), open_dispatch_count=0)
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="ACTIVE")

    def test_the_region_rule_still_bites_for_a_certified_technician_elsewhere(self):
        """An L2 technician in SE-02 clears certification and fails on region alone.

        PRD: "The technician's `home_region` must equal the `address_region` of the site hosting the ticket's device, failing which the dispatch reports `ERR_TECHNICIAN_REGION_MISMATCH`."
        PRD: "A `CRITICAL` ticket may only go to a technician whose `skill_level` is `L2` or `L3` — an `L1` technician is not certified for critical work and the dispatch reports `ERR_TECHNICIAN_NOT_CERTIFIED`; a `STANDARD` ticket may go to any skill level."

        Design: Difficulty/priority_pair_validation_conflict/critical_certification_gate_outranks_region_mismatch_on_dispatch
        """
        env = _open_critical_ticket_and_two_out_of_region_technicians()
        assert_fields(env["certified_elsewhere"], skill_level="L2", home_region="SE-02")

        validate_error(
            _dispatch(env["ticket_id"], env["certified_elsewhere"]["id"]),
            ApiErrorId.ERR_TECHNICIAN_REGION_MISMATCH,
        )

        assert_fields(fetch_service_ticket(env["ticket_id"]), status="OPEN")


def _device_with_one_accepted_reading_over_the_first_half_of_august():
    """An ACCEPTED reading covering 1-15 August, with the clock at 20 August."""
    env = setup_print_environment(period=(PERIOD_START, PERIOD_END), clock=READ_CLOCK)
    env["read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=FIRST_MONO_METER,
        color_meter=0,
        toner_level_pct=FIRST_TONER_PCT,
        coverage_start=PERIOD_START,
        coverage_end=FIRST_COVERAGE_END,
    )
    return env


def _submit_second_reading(env, coverage_start, coverage_end):
    """A second automated reading over the supplied window, 4,000 pages later."""
    return api_client.submit_automated_meter_read(
        meter_read_payload(
            env["device_id"],
            env["period_id"],
            mono_meter=SECOND_MONO_METER,
            color_meter=0,
            toner_level_pct=SECOND_TONER_PCT,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        ),
        make_fleet_ops_headers(FLEET_OPS_USER_ID),
    )


class TestReadPeriodContainmentOutranksIntervalOverlap:
    """A reading that both leaves the period and overlaps an accepted reading."""

    def test_the_containment_gate_is_reported_and_the_overlap_is_not(self):
        """Coverage from 10 August to 15 September overlaps and escapes the period.

        PRD: "When a single request violates more than one rule, the response must report the violation that comes **first** in the ordered list below, not whichever check the implementation happens to run first."
        PRD: "The list is exhaustive and strictly ascending; a rule that appears later can never mask a rule that appears earlier."
        PRD: "**Reading belongs to the period.** The reading's device belongs to the same contract as the period, and `coverage_end` falls inside the half-open window running from `period_start` up to but excluding `period_end` — otherwise `ERR_READ_OUTSIDE_PERIOD` (422). Applies to both meter-reading intake endpoints."
        PRD: "**Reading interval sanity.** `coverage_start` is strictly earlier than `coverage_end`, and the reading's half-open interval does not intersect the interval of any other reading of the same device whose `status` is `PENDING_VALIDATION` or `ACCEPTED`; intervals that merely touch (one reading's `coverage_end` equal to the next reading's `coverage_start`) are allowed. Otherwise `ERR_READ_INTERVAL_OVERLAP` (409). Applies to both meter-reading intake endpoints."

        Design: Difficulty/priority_pair_validation_conflict/read_period_containment_outranks_coverage_interval_overlap
        """
        env = _device_with_one_accepted_reading_over_the_first_half_of_august()
        assert_fields(env["read"], status="ACCEPTED", mono_delta=FIRST_MONO_METER)

        error = validate_error(
            _submit_second_reading(env, "2026-08-10T00:00:00Z", "2026-09-15T00:00:00Z"),
            ApiErrorId.ERR_READ_OUTSIDE_PERIOD,
        )

        assert error["error_id"] != ApiErrorId.ERR_READ_INTERVAL_OVERLAP, (
            "the overlap rule sits later in the ordered list and must not be "
            f"reported ahead of the containment rule: {error}"
        )

    def test_the_rejected_reading_is_never_stored_and_moves_no_device_counter(self):
        """One reading on file, still ACCEPTED, and the watermarks left at 5,000.

        PRD: "The second hop writes the device: `last_accepted_mono_meter` and `last_accepted_color_meter` take the submitted absolute values, `last_read_at` takes the reading's `coverage_end`, `toner_level_pct` takes the reading's reported level, `lifetime_mono_pages` grows by `mono_delta`, `lifetime_color_pages` grows by `color_delta`, `pages_since_last_cartridge` grows by the sum of the two deltas, and the device's `version` increments."
        PRD: "A reading that is not `ACCEPTED` carries a `mono_delta` and a `color_delta` of exactly 0 and moves no device counter whatsoever."

        Design: Difficulty/priority_pair_validation_conflict/read_period_containment_outranks_coverage_interval_overlap
        """
        env = _device_with_one_accepted_reading_over_the_first_half_of_august()

        validate_error(
            _submit_second_reading(env, "2026-08-10T00:00:00Z", "2026-09-15T00:00:00Z"),
            ApiErrorId.ERR_READ_OUTSIDE_PERIOD,
        )

        reads = list_reads_for_device(env["device_id"])
        assert len(reads) == 1, f"the rejected reading must not be stored, got {reads}"
        assert_fields(reads[0], id=env["read"]["id"], status="ACCEPTED")
        assert_fields(
            fetch_device(env["device_id"]),
            last_accepted_mono_meter=FIRST_MONO_METER,
            last_accepted_color_meter=0,
            lifetime_mono_pages=FIRST_MONO_METER,
            lifetime_color_pages=0,
            pages_since_last_cartridge=FIRST_MONO_METER,
            toner_level_pct=FIRST_TONER_PCT,
        )

    def test_the_overlap_rule_still_bites_for_a_reading_that_stays_in_the_period(self):
        """Coverage from 10 to 20 August is contained, so the overlap answers instead.

        PRD: "**Reading interval sanity.** `coverage_start` is strictly earlier than `coverage_end`, and the reading's half-open interval does not intersect the interval of any other reading of the same device whose `status` is `PENDING_VALIDATION` or `ACCEPTED`; intervals that merely touch (one reading's `coverage_end` equal to the next reading's `coverage_start`) are allowed. Otherwise `ERR_READ_INTERVAL_OVERLAP` (409). Applies to both meter-reading intake endpoints."

        Design: Difficulty/priority_pair_validation_conflict/read_period_containment_outranks_coverage_interval_overlap
        """
        env = _device_with_one_accepted_reading_over_the_first_half_of_august()

        validate_error(
            _submit_second_reading(env, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"),
            ApiErrorId.ERR_READ_INTERVAL_OVERLAP,
        )

        reads = list_reads_for_device(env["device_id"])
        assert len(reads) == 1, f"the rejected reading must not be stored, got {reads}"
