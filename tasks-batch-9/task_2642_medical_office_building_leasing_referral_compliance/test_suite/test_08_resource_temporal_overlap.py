"""Two resources with deliberately opposite interval conventions: suites and shared spaces."""
from test_helpers import ApiErrorId, validate_error, validate_paginated
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import LEASING_AGENT


def _probe(api, building, incumbent_tenant, candidate_tenant, suite_class, rentable_sf,
           rent, candidate_start, candidate_end, **suite_kwargs):
    """One suite carrying an EXECUTED incumbent and one certified candidate awaiting execution."""
    suite = fx.register_suite(api, building["id"], suite_number=f.next_suite_number(),
                              floor=2, rentable_sf=rentable_sf, suite_class=suite_class,
                              **suite_kwargs)
    incumbent = fx.draft_lease(api, building["id"], suite["id"], incumbent_tenant["id"],
                              term_start="2026-09-01", term_end="2029-08-31",
                              base_rent_psf_annual=rent)
    fx.file_attestation(api, incumbent["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, incumbent["id"], "Incumbent")
    fx.certify(api, incumbent["id"], "Inside the published band")
    incumbent = fx.execute(api, incumbent["id"], "Incumbent executed")

    candidate = fx.draft_lease(api, building["id"], suite["id"], candidate_tenant["id"],
                              term_start=candidate_start, term_end=candidate_end,
                              base_rent_psf_annual=rent)
    fx.file_attestation(api, candidate["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, candidate["id"], "Candidate")
    candidate = fx.certify(api, candidate["id"], "Inside the published band")
    return {"suite": suite, "incumbent": incumbent, "candidate": candidate}


def _four_turnover_probes(api):
    """Four suites with identical incumbent terms and four candidates straddling the buffer."""
    building = fx.register_building(api)
    incumbent_tenant = fx.register_tenant(api, legal_name="Lakeside Surgical Partners LLC",
                                          primary_specialty="ORTHOPEDICS")
    candidate_tenant = fx.register_tenant(api, legal_name="Northgate Medical Group PC",
                                          primary_specialty="GASTROENTEROLOGY")
    ctx = {"building": building}
    ctx["procedure_on_buffer"] = _probe(
        api, building, incumbent_tenant, candidate_tenant, "PROCEDURE", 4000, 34.25,
        "2029-09-14", "2032-09-13", power_amps_available=300, medical_gas_available=True)
    ctx["procedure_past_buffer"] = _probe(
        api, building, incumbent_tenant, candidate_tenant, "PROCEDURE", 4000, 34.25,
        "2029-09-15", "2032-09-14", power_amps_available=300, medical_gas_available=True)
    ctx["exam_after_last_day"] = _probe(
        api, building, incumbent_tenant, candidate_tenant, "STANDARD_EXAM", 5000, 30.00,
        "2029-09-01", "2032-08-31", power_amps_available=200)
    ctx["exam_on_last_day"] = _probe(
        api, building, incumbent_tenant, candidate_tenant, "STANDARD_EXAM", 5000, 30.00,
        "2029-08-31", "2032-08-30", power_amps_available=200)
    return ctx


def _attempt_execution(api, lease_id, note):
    return api.execute_lease(lease_id, {"execution_note": note}, LEASING_AGENT)


def test_the_procedure_buffer_endpoint_is_inclusive_and_one_day_later_is_clean(api):
    """A fortnight buffer around the incumbent makes 2029-09-14 conflict and 2029-09-15 clear.

    PRD: "For each incumbent, widen its term symmetrically by the buffer: the low edge is its
    `term_start` less the buffer in days and the high edge is its `term_end` plus the buffer in
    days."

    PRD: "To illustrate the endpoint inclusivity: on a `PROCEDURE` suite whose incumbent runs 1
    September 2026 through 31 August 2029, the buffered window runs 18 August 2026 through 14
    September 2029, so a candidate starting on 14 September 2029 still conflicts and one starting
    15 September 2029 is clean."

    PRD: "The referenced suite's `occupancy_status` is `VACANT` at execution and no other lease
    holds it with status `EXECUTED`, `ACTIVE` or `HOLDOVER` — otherwise `ERR_SUITE_NOT_AVAILABLE`
    (409), guarding `POST /leases/{id}/execute`."

    Design: Difficulty/resource_temporal_overlap/suite_term_closed_interval_with_class_turnover_buffer
    """
    ctx = _four_turnover_probes(api)

    on_buffer = _attempt_execution(api, ctx["procedure_on_buffer"]["candidate"]["id"],
                                   "PROCEDURE, starts 2029-09-14")
    validate_error(on_buffer, ApiErrorId.ERR_SUITE_TERM_CONFLICT)

    past_buffer = _attempt_execution(api, ctx["procedure_past_buffer"]["candidate"]["id"],
                                     "PROCEDURE, starts 2029-09-15")
    validate_error(past_buffer, ApiErrorId.ERR_SUITE_NOT_AVAILABLE)

    for key in ("procedure_on_buffer", "procedure_past_buffer"):
        assert fx.read_lease(api, ctx[key]["candidate"]["id"])["status"] == "FMV_CERTIFIED"
        assert fx.read_lease(api, ctx[key]["incumbent"]["id"])["status"] == "EXECUTED"

    building = fx.read_building(api, ctx["building"]["id"])
    assert building["leased_rentable_sf"] == 18000
    assert building["vacant_rentable_sf"] == 82000


def test_the_zero_buffer_exam_suite_still_conflicts_on_the_incumbents_closed_endpoint(api):
    """With no buffer the class becomes decisive: the same calendar dates swap verdicts.

    PRD: "The turnover buffer is drawn from the suite's class: 0 days for `STANDARD_EXAM`, a full
    30 days for `IMAGING`, and a fortnight — 14 days — for both `PROCEDURE` and `INFUSION`."

    PRD: "Lease terms are **closed** intervals — the opposite convention from the shared-space
    sweep described in §3.9 — so the candidate conflicts whenever its `term_start` is on or
    before the incumbent's high edge **and** the incumbent's low edge is on or before the
    candidate's `term_end`; both comparisons are non-strict."

    PRD: "No incumbent lease on the same suite conflicts once the class-dependent turnover buffer
    is applied to the closed term intervals — otherwise `ERR_SUITE_TERM_CONFLICT` (409), guarding
    `POST /leases/{id}/execute`."

    Design: Difficulty/resource_temporal_overlap/suite_term_closed_interval_with_class_turnover_buffer
    """
    ctx = _four_turnover_probes(api)

    after_last_day = _attempt_execution(api, ctx["exam_after_last_day"]["candidate"]["id"],
                                        "STANDARD_EXAM, starts 2029-09-01")
    validate_error(after_last_day, ApiErrorId.ERR_SUITE_NOT_AVAILABLE)

    on_last_day = _attempt_execution(api, ctx["exam_on_last_day"]["candidate"]["id"],
                                     "STANDARD_EXAM, starts 2029-08-31")
    validate_error(on_last_day, ApiErrorId.ERR_SUITE_TERM_CONFLICT)

    for key in ("exam_after_last_day", "exam_on_last_day"):
        assert fx.read_lease(api, ctx[key]["candidate"]["id"])["status"] == "FMV_CERTIFIED"
        assert fx.read_lease(api, ctx[key]["incumbent"]["id"])["status"] == "EXECUTED"

    building = fx.read_building(api, ctx["building"]["id"])
    assert building["leased_rentable_sf"] == 18000
    assert building["vacant_rentable_sf"] == 82000


def _waiting_room_on_a_draft_lease(api):
    """A 24-seat waiting room open 07:00-19:00, bookable from an unauthorised draft lease."""
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"], suite_number="210", floor=2,
                              rentable_sf=5000, suite_class="STANDARD_EXAM",
                              power_amps_available=200)
    tenant = fx.register_tenant(api, legal_name="Northgate Medical Group PC",
                                primary_specialty="GASTROENTEROLOGY")
    lease = fx.draft_lease(api, building["id"], suite["id"], tenant["id"],
                           base_rent_psf_annual=30.00)
    lease = fx.file_attestation(api, lease["id"], "SPACE_SHARING_SCHEDULE")
    space = fx.register_shared_space(api, building["id"],
                                     name="Second Floor Shared Waiting Room",
                                     space_type="WAITING_ROOM", capacity_seats=24,
                                     opens_at="07:00", closes_at="19:00")
    return {"building": building, "suite": suite, "tenant": tenant,
            "lease": lease, "shared_space": space}


def _attempt_booking(api, space_id, lease_id, window_start, window_end, occupant_count):
    return api.create_booking(
        f.create_booking_payload(space_id, lease_id, window_start, window_end, occupant_count),
        LEASING_AGENT)


def test_the_seat_sweep_admits_a_load_exactly_at_capacity_and_refuses_one_seat_more(api):
    """Overlapping windows aggregate; touching windows do not, and 24 of 24 seats is admissible.

    PRD: "Intervals are half-open on both sides, and overlap is tested with strict inequalities
    in both directions: two bookings overlap only when the first starts strictly before the
    second ends and the second starts strictly before the first ends."

    PRD: "A booking that begins exactly when another ends therefore does not overlap it and the
    two never compete for seats."

    PRD: "The rejection test is a load **strictly greater than** `capacity_seats`, so a load
    exactly equal to capacity is admitted."

    PRD: "The booking is created in `BOOKED` and its `is_after_hours` flag is derived: it is true
    when any part of the requested window falls outside the space's operating window, and false
    only when the whole window sits inside it."

    Design: Difficulty/resource_temporal_overlap/shared_space_half_open_aggregate_capacity_sweep
    """
    ctx = _waiting_room_on_a_draft_lease(api)
    space_id = ctx["shared_space"]["id"]
    lease_id = ctx["lease"]["id"]

    first = fx.book(api, space_id, lease_id, "2026-08-05T09:00:00Z",
                    "2026-08-05T11:00:00Z", 10)
    assert first["status"] == "BOOKED"
    assert first["is_after_hours"] is False
    assert first["occupant_count"] == 10

    second = fx.book(api, space_id, lease_id, "2026-08-05T10:00:00Z",
                     "2026-08-05T12:00:00Z", 14)
    assert second["status"] == "BOOKED"

    overdrawn = _attempt_booking(api, space_id, lease_id, "2026-08-05T10:30:00Z",
                                 "2026-08-05T11:30:00Z", 1)
    validate_error(overdrawn, ApiErrorId.ERR_SHARED_SPACE_CAPACITY_EXCEEDED)

    touching = fx.book(api, space_id, lease_id, "2026-08-05T12:00:00Z",
                       "2026-08-05T13:00:00Z", 24)
    assert touching["status"] == "BOOKED"

    rows, meta = validate_paginated(
        api.list_bookings(LEASING_AGENT,
                          params={"shared_space_id": space_id, "status": "BOOKED"}))
    assert meta["total_count"] == 3
    assert sorted(row["id"] for row in rows) == sorted(
        [first["id"], second["id"], touching["id"]])


def test_the_after_hours_gate_runs_before_the_seat_sweep_on_an_empty_room(api):
    """A single occupant in an empty room is still refused for falling outside the posted hours.

    PRD: "A booking whose window falls wholly or partly outside the space's operating window
    requires the lease's `after_hours_authorized` to be true — otherwise
    `ERR_AFTER_HOURS_NOT_AUTHORIZED` (422), guarding `POST /shared-space-bookings`."

    PRD: "Third, a booking that is after hours requires the lease's `after_hours_authorized` to
    be true, and this check runs **before** the capacity sweep — an unauthorised 20:00 request in
    a room open until 19:00 is refused on the authorization ground even if the room is completely
    empty, and even if it would also have been refused on capacity."

    Design: Difficulty/resource_temporal_overlap/shared_space_half_open_aggregate_capacity_sweep
    """
    ctx = _waiting_room_on_a_draft_lease(api)
    space_id = ctx["shared_space"]["id"]
    lease_id = ctx["lease"]["id"]
    assert ctx["lease"]["after_hours_authorized"] is False

    refused = _attempt_booking(api, space_id, lease_id, "2026-08-05T20:00:00Z",
                               "2026-08-05T21:00:00Z", 1)
    validate_error(refused, ApiErrorId.ERR_AFTER_HOURS_NOT_AUTHORIZED)

    rows, meta = validate_paginated(
        api.list_bookings(LEASING_AGENT, params={"shared_space_id": space_id}))
    assert meta["total_count"] == 0
    assert rows == []
