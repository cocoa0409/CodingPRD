"""Crew, fleet, and pickup logistics: half-open vs buffered overlap, priority
pairs, pickup fees, labor ledger (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_assignment,
    book_appointment,
    create_accepted_offer,
    create_category,
    create_cleared_job,
    create_crew_member,
    create_donor,
    create_in_progress_job,
    create_lead_member,
    create_offer,
    create_scheduled_job,
    create_technician,
    create_vehicle,
    get_success_data,
    schedule_job,
    setup_accepted_pickup_offer,
    setup_issued_receipt,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

COORD = TEST_USERS["crew_coordinator_headers"]
INTAKE = TEST_USERS["intake_staff_headers"]
ADMIN = TEST_USERS["warehouse_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / crew_member_half_open_overlap
# ---------------------------------------------------------------------------

def _setup_scheduled_job_for_worker():
    """Job SCHEDULED 2026-06-10 08:00-16:00; returns ctx plus a free worker."""
    ctx = create_scheduled_job(start="2026-06-10T08:00:00Z", end="2026-06-10T16:00:00Z",
                               title="Job H", quoted_fee_cents=80000)
    worker = create_crew_member(full_name="Worker Eight", hourly_rate_cents=3500)
    ctx["worker"] = worker
    return ctx


class TestCrewMemberHalfOpenOverlap:
    def test_crew_adjacent_windows_legal_half_open(self, api):
        """PRD §3.5: "Adjacent windows — one ending exactly when the next begins —
        are legal and carry no buffer, and assignments in `NO_SHOW` or `CANCELLED`
        never conflict."

        Design: Difficulty/resource_temporal_overlap/crew_member_half_open_overlap
        """
        ctx = _setup_scheduled_job_for_worker()
        first = add_assignment(ctx["job"]["id"], ctx["worker"]["id"],
                               "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z")
        second = add_assignment(ctx["job"]["id"], ctx["worker"]["id"],
                                "2026-06-10T12:00:00Z", "2026-06-10T15:00:00Z")
        assert first["status"] == "ASSIGNED"
        assert second["status"] == "ASSIGNED", (
            "half-open [start, end): end == next start is not an overlap")

        rows, meta = validate_paginated(api.list_crew_assignments(
            COORD, params={"crew_member_id": ctx["worker"]["id"], "status": "ASSIGNED"}))
        assert len(rows) == 2

    def test_crew_intersecting_windows_rejected(self, api):
        """PRD §3.5: "Assignments for the same crew member follow half-open
        interval semantics: a new assignment conflicts with an existing `ASSIGNED`
        or `COMPLETED` assignment of that member only when the existing window
        starts before the new window ends and ends after the new window starts, and
        any such conflict is rejected with `ERR_CREW_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_member_half_open_overlap
        """
        ctx = _setup_scheduled_job_for_worker()
        add_assignment(ctx["job"]["id"], ctx["worker"]["id"],
                       "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z")
        response = api.create_crew_assignment(
            {"job_id": ctx["job"]["id"], "crew_member_id": ctx["worker"]["id"],
             "role_on_job": "WORKER",
             "start_at": "2026-06-10T11:00:00Z", "end_at": "2026-06-10T13:00:00Z"},
            COORD)
        validate_error(response, ApiErrorId.ERR_CREW_TIME_OVERLAP)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / vehicle_buffered_gap_overlap
# ---------------------------------------------------------------------------

def _setup_vehicle_with_accepted_offers():
    category = create_category(code="TILE9", display_name="Tile 9",
                               pricing_model="PER_SQFT", base_rate_cents=300)
    donor = create_donor(full_name="D Ten")
    offers = [
        create_accepted_offer(donor["id"], category["id"], source_type="PICKUP",
                              description_text=f"lot {i}", estimated_quantity=50,
                              quantity_unit="SQFT", condition_grade="B")
        for i in (1, 2, 3)
    ]
    vehicle = create_vehicle(plate_code="TRK-10", capacity_lbs=8000)
    return category, donor, offers, vehicle


class TestVehicleBufferedGapOverlap:
    def test_vehicle_touching_window_within_buffer_rejected(self, api):
        """PRD §3.5: "Vehicle scheduling uses buffered overlap semantics, stricter
        than the crew rule: a vehicle is occupied by its `BOOKED` appointments and
        its `SCHEDULED` or `IN_PROGRESS` jobs, and a new window does not conflict
        with an existing occupation only when the new window's end, extended by a
        60-minute buffer, is still at or before the existing window's start, or the
        new window's start is at or after the existing window's end extended by the
        same buffer. Touching windows without that full one-hour gap are rejected
        with `ERR_VEHICLE_TIME_OVERLAP` — where the crew rule lets adjacent windows
        pass, the vehicle rule does not."

        Design: Difficulty/resource_temporal_overlap/vehicle_buffered_gap_overlap
        """
        _, _, offers, vehicle = _setup_vehicle_with_accepted_offers()
        first = book_appointment("DONATION_OFFER", offers[0]["id"], vehicle["id"],
                                 "2026-06-16T09:00:00Z", "2026-06-16T10:00:00Z")
        assert first["status"] == "BOOKED"
        assert first["fee_cents"] == 5000, "NONE-tier donor pays the flat $50 pickup fee"

        response = api.create_pickup_appointment(
            {"subject_type": "DONATION_OFFER", "subject_id": offers[1]["id"],
             "vehicle_id": vehicle["id"],
             "window_start": "2026-06-16T10:00:00Z", "window_end": "2026-06-16T11:00:00Z"},
            INTAKE)
        validate_error(response, ApiErrorId.ERR_VEHICLE_TIME_OVERLAP)

    def test_vehicle_window_at_exact_buffer_accepted(self, api):
        """PRD §3.5: "a new window does not conflict with an existing occupation
        only when the new window's end, extended by a 60-minute buffer, is still at
        or before the existing window's start, or the new window's start is at or
        after the existing window's end extended by the same buffer."

        Design: Difficulty/resource_temporal_overlap/vehicle_buffered_gap_overlap
        """
        _, _, offers, vehicle = _setup_vehicle_with_accepted_offers()
        book_appointment("DONATION_OFFER", offers[0]["id"], vehicle["id"],
                         "2026-06-16T09:00:00Z", "2026-06-16T10:00:00Z")
        third = book_appointment("DONATION_OFFER", offers[2]["id"], vehicle["id"],
                                 "2026-06-16T11:00:00Z", "2026-06-16T12:00:00Z")
        assert third["status"] == "BOOKED", (
            "start 11:00 >= prior end 10:00 + 60-minute buffer: exactly at the buffer is legal")


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / constraint_beats_temporal_on_assignment
# ---------------------------------------------------------------------------

def _setup_two_jobs_shared_worker():
    """Jobs A and B both SCHEDULED 2026-06-10 08:00-16:00 on distinct vehicles;
    worker assigned on B 09:00-12:00."""
    tech = create_technician(full_name="Tech Six")
    lead_a = create_lead_member(full_name="Lead A6")
    lead_b = create_lead_member(full_name="Lead B6")
    worker = create_crew_member(full_name="Worker Six", hourly_rate_cents=3500)
    veh_a = create_vehicle(plate_code="TRK-6A")
    veh_b = create_vehicle(plate_code="TRK-6B")
    ctx_a = create_scheduled_job(lead_id=lead_a["id"], vehicle_id=veh_a["id"],
                                 start="2026-06-10T08:00:00Z", end="2026-06-10T16:00:00Z",
                                 title="Job F1", quoted_fee_cents=100000)
    ctx_b = create_scheduled_job(lead_id=lead_b["id"], vehicle_id=veh_b["id"],
                                 start="2026-06-10T08:00:00Z", end="2026-06-10T16:00:00Z",
                                 title="Job F2", quoted_fee_cents=100000)
    add_assignment(ctx_b["job"]["id"], worker["id"],
                   "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z")
    return ctx_a, ctx_b, worker


class TestConstraintBeatsTemporalOnAssignment:
    def test_overlap_error_wins_over_window_error(self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the first failing
        check produces the response."
        PRD §2.10: "9. **Business constraints** — uniqueness of codes, plates, and
        report periods; crew and vehicle time overlaps; zone capacity and category
        fit; certifications; acceptance grading; active-appointment and
        weighed-batch blocks: `ERR_DUPLICATE_CODE`, `ERR_DUPLICATE_REPORT_PERIOD`,
        `ERR_CREW_TIME_OVERLAP`, `ERR_VEHICLE_TIME_OVERLAP`, `ERR_ZONE_AT_CAPACITY`,
        `ERR_ZONE_CATEGORY_MISMATCH`, `ERR_CAPACITY_BELOW_OCCUPANCY`,
        `ERR_CERTIFICATION_MISMATCH`, `ERR_CONDITION_BELOW_ACCEPTANCE`,
        `ERR_ACTIVE_APPOINTMENT_EXISTS`, `ERR_JOB_HAS_WEIGHED_BATCHES`."
        PRD §2.10: "10. **Temporal arithmetic** — window end strictly after window
        start, assignment containment inside the job window, agreement validity
        windows, split quantity bounds: `ERR_INVALID_TIME_WINDOW`,
        `ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW`, `ERR_AGREEMENT_NOT_IN_WINDOW`,
        `ERR_SPLIT_INVALID_QUANTITY`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_assignment
        """
        ctx_a, ctx_b, worker = _setup_two_jobs_shared_worker()
        # 11:00-17:00 overlaps the worker's 09:00-12:00 window AND runs past the
        # job's 16:00 scheduled end: both checks fail; the overlap wins.
        response = api.create_crew_assignment(
            {"job_id": ctx_a["job"]["id"], "crew_member_id": worker["id"],
             "role_on_job": "WORKER",
             "start_at": "2026-06-10T11:00:00Z", "end_at": "2026-06-10T17:00:00Z"},
            COORD)
        error = validate_error(response, ApiErrorId.ERR_CREW_TIME_OVERLAP)
        assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW, (
            "constraint (priority 9) beats temporal (priority 10)")

    def test_outside_window_alone_rejected_temporally(self, api):
        """PRD §3.5: "The window must lie inside the job's scheduled window — an
        assignment that begins before the job's `scheduled_start` or ends after its
        `scheduled_end` fails with `ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_assignment
        """
        ctx_a, ctx_b, worker = _setup_two_jobs_shared_worker()
        # 12:00-17:00 touches but does not overlap the 09:00-12:00 window
        # (half-open); only the temporal containment check fails.
        response = api.create_crew_assignment(
            {"job_id": ctx_a["job"]["id"], "crew_member_id": worker["id"],
             "role_on_job": "WORKER",
             "start_at": "2026-06-10T12:00:00Z", "end_at": "2026-06-10T17:00:00Z"},
            COORD)
        validate_error(response, ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / safety_beats_constraint_on_screener_lead
# ---------------------------------------------------------------------------

def _setup_screener_lead_conflict():
    """Tech T5 (hazmat + lead certified) clears job J5; vehicle V5 carries a
    BOOKED appointment 09:00-10:00 for an ACCEPTED pickup offer."""
    tech = create_technician(full_name="Tech Five", lead_certified=True)
    vehicle = create_vehicle(plate_code="TRK-5")
    ctx_offer = setup_accepted_pickup_offer(
        description_text="tile pallet", estimated_quantity=200,
        quantity_unit="SQFT", condition_grade="B",
    )
    book_appointment("DONATION_OFFER", ctx_offer["offer"]["id"], vehicle["id"],
                     "2026-06-20T09:00:00Z", "2026-06-20T10:00:00Z")
    job = create_cleared_job(tech_id=tech["id"], title="Job E",
                             site_address_text="3 Birch", quoted_fee_cents=120000)[0]
    return tech, vehicle, job


class TestSafetyBeatsConstraintOnScreenerLead:
    def test_screener_cannot_lead_wins_over_vehicle_overlap(self, api):
        """PRD §2.10: "8. **Hazardous-material and segregation-of-duties safety** —
        screening inheritance on hazmat-exposed item intake, open quarantines
        blocking job completion, screener-versus-lead separation, and receipt
        issuer-versus-receiver separation, producing
        `ERR_HAZMAT_SCREENING_REQUIRED`, `ERR_QUARANTINED_BATCHES_OPEN`,
        `ERR_SCREENER_CANNOT_LEAD`, or `ERR_RECEIPT_ISSUER_IS_RECEIVER`."
        PRD §2.10: "9. **Business constraints** — uniqueness of codes, plates, and
        report periods; crew and vehicle time overlaps; zone capacity and category
        fit; certifications; acceptance grading; active-appointment and
        weighed-batch blocks: `ERR_DUPLICATE_CODE`, `ERR_DUPLICATE_REPORT_PERIOD`,
        `ERR_CREW_TIME_OVERLAP`, `ERR_VEHICLE_TIME_OVERLAP`, `ERR_ZONE_AT_CAPACITY`,
        `ERR_ZONE_CATEGORY_MISMATCH`, `ERR_CAPACITY_BELOW_OCCUPANCY`,
        `ERR_CERTIFICATION_MISMATCH`, `ERR_CONDITION_BELOW_ACCEPTANCE`,
        `ERR_ACTIVE_APPOINTMENT_EXISTS`, `ERR_JOB_HAS_WEIGHED_BATCHES`."
        PRD §3.4: "Segregation of duties bars the technician who cleared the job
        from leading it: a proposed lead equal to the clearing screening's
        `performed_by_crew_id` is refused with `ERR_SCREENER_CANNOT_LEAD`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_screener_lead
        """
        tech, vehicle, job = _setup_screener_lead_conflict()
        # Lead == the clearing screener (safety violation) AND the window
        # 09:30-12:30 sits inside the booked appointment's 60-minute buffer.
        response = api.schedule_job(job["id"], {
            "lead_crew_member_id": tech["id"], "vehicle_id": vehicle["id"],
            "scheduled_start": "2026-06-20T09:30:00Z", "scheduled_end": "2026-06-20T12:30:00Z",
        }, COORD)
        error = validate_error(response, ApiErrorId.ERR_SCREENER_CANNOT_LEAD)
        assert error["error_id"] != ApiErrorId.ERR_VEHICLE_TIME_OVERLAP, (
            "safety (priority 8) beats the overlap constraint (priority 9)")

    def test_failed_schedule_leaves_job_cleared(self, api):
        """PRD §3.4: "Only a `CLEARED` job can be scheduled (`ERR_JOB_NOT_CLEARED`
        otherwise)."
        PRD §3.4: "A `CLEARED` outcome on a `SCREENING_PENDING` job moves it to
        `CLEARED` and records the screening's `id` as the job's
        `clearing_screening_id`"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_screener_lead
        """
        tech, vehicle, job = _setup_screener_lead_conflict()
        validate_error(api.schedule_job(job["id"], {
            "lead_crew_member_id": tech["id"], "vehicle_id": vehicle["id"],
            "scheduled_start": "2026-06-20T09:30:00Z", "scheduled_end": "2026-06-20T12:30:00Z",
        }, COORD), ApiErrorId.ERR_SCREENER_CANNOT_LEAD)
        job = get_success_data(api.get_deconstruction_job(job["id"], COORD))
        assert job["status"] == "CLEARED", "rejected schedule must not move the job"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / offer_receive_requires_completed_pickup
# ---------------------------------------------------------------------------

def _setup_pickup_offer_with_booked_appointment():
    category = create_category(code="TILE8", display_name="Tile 8",
                               pricing_model="PER_SQFT", base_rate_cents=300)
    donor = create_donor(full_name="D Nine")
    offer = create_accepted_offer(donor["id"], category["id"], source_type="PICKUP",
                                  description_text="tile lot", estimated_quantity=100,
                                  quantity_unit="SQFT", condition_grade="B")
    vehicle = create_vehicle(plate_code="TRK-9", capacity_lbs=8000)
    appointment = book_appointment("DONATION_OFFER", offer["id"], vehicle["id"],
                                   "2026-06-15T09:00:00Z", "2026-06-15T10:00:00Z")
    return offer, appointment


class TestOfferReceiveRequiresCompletedPickup:
    def test_receive_with_booked_appointment_rejected(self, api):
        """PRD §3.3: "Breaching the provenance gate fails with
        `ERR_OFFER_NOT_RECEIVABLE_SOURCE`."
        PRD §3.5: "For a `DONATION_OFFER` subject the fee reads the donor's
        recognition standing at that moment: donors at `BUILDER` or `CORNERSTONE`
        pay nothing, while `NONE` and `SUPPORTER` donors are charged a flat $50
        (5,000 cents)."

        Design: Difficulty/cross_entity_state_dependency/offer_receive_requires_completed_pickup
        """
        offer, appointment = _setup_pickup_offer_with_booked_appointment()
        assert appointment["fee_cents"] == 5000, (
            f"tier NONE at booking: flat 5000, got {appointment['fee_cents']}")
        response = api.receive_offer(offer["id"], INTAKE)
        validate_error(response, ApiErrorId.ERR_OFFER_NOT_RECEIVABLE_SOURCE)

    def test_receive_after_completed_appointment_succeeds(self, api):
        """PRD §3.3: "a `PICKUP` offer is receivable only once a pickup appointment
        naming the offer as its `DONATION_OFFER` subject has reached `COMPLETED`"
        PRD §3.3: "Receiving lands the offer in `RECEIVED` and records the acting
        operator's `X-User-ID` in the offer's `received_by_user_id`"

        Design: Difficulty/cross_entity_state_dependency/offer_receive_requires_completed_pickup
        """
        offer, appointment = _setup_pickup_offer_with_booked_appointment()
        validate_success(api.complete_appointment(appointment["id"], INTAKE))
        offer = validate_success(api.receive_offer(offer["id"], INTAKE))
        assert offer["status"] == "RECEIVED"
        assert offer["received_by_user_id"] == "intake-1", (
            "the acting operator's X-User-ID is recorded as the SoD anchor")


# ---------------------------------------------------------------------------
# Corner: calculations / pickup_fee_waived_for_builder_tier
# ---------------------------------------------------------------------------

def test_pickup_fee_waived_for_builder_tier(api):
    """PRD §3.5: "The booking computes its `fee_cents` once, at booking time. A
    `DECONSTRUCTION_JOB` subject always rides free. For a `DONATION_OFFER` subject
    the fee reads the donor's recognition standing at that moment: donors at
    `BUILDER` or `CORNERSTONE` pay nothing, while `NONE` and `SUPPORTER` donors
    are charged a flat $50 (5,000 cents)."
    PRD §3.1: "From that trailing figure the system derives the donor's
    `recognition_tier`: at least $10,000 (1,000,000 cents) earns `CORNERSTONE`, at
    least $2,500 (250,000 cents) earns `BUILDER`, at least $500 (50,000 cents)
    earns `SUPPORTER`, and anything less is `NONE`; every threshold is inclusive."

    Design: Corner/calculations/pickup_fee_waived_for_builder_tier
    """
    # Donor B earns BUILDER through one ISSUED receipt valued 270000 (3 x 90000).
    ctx = setup_issued_receipt(
        [90000, 90000, 90000], receiver_id="staff-fee-r", issuer_id="staff-fee-i",
        category_overrides={"code": "FEECAT", "display_name": "Fee Cat",
                            "base_rate_cents": 100000},
        offer_overrides={"description_text": "builder lot", "estimated_quantity": 3},
    )
    donor_b = get_success_data(api.get_donor(ctx["donor"]["id"], INTAKE))
    assert donor_b["recognition_tier"] == "BUILDER"
    assert donor_b["trailing_receipt_value_cents"] == 270000

    offer_b = create_accepted_offer(donor_b["id"], ctx["category"]["id"],
                                    source_type="PICKUP", description_text="builder pickup")
    donor_n = create_donor(full_name="D None")
    offer_n = create_accepted_offer(donor_n["id"], ctx["category"]["id"],
                                    source_type="PICKUP", description_text="none pickup")
    vehicle = create_vehicle(plate_code="TRK-FEE", capacity_lbs=8000)

    appt_b = book_appointment("DONATION_OFFER", offer_b["id"], vehicle["id"],
                              "2026-06-29T09:00:00Z", "2026-06-29T10:00:00Z")
    appt_n = book_appointment("DONATION_OFFER", offer_n["id"], vehicle["id"],
                              "2026-06-29T11:00:00Z", "2026-06-29T12:00:00Z")
    assert appt_b["fee_cents"] == 0, "BUILDER donors pay no pickup fee"
    assert appt_n["fee_cents"] == 5000, "NONE donors pay the flat $50"


# ---------------------------------------------------------------------------
# Corner: calculations / crew_labor_cost_and_fee_overage
# ---------------------------------------------------------------------------

def test_crew_labor_cost_and_fee_overage(api):
    """PRD §3.5: "When the work is done the coordinator completes it with the
    `hours_worked`, which lands the assignment in `COMPLETED` and triggers the
    labor ledger: the assignment's `labor_cost_cents` is 0 for a `VOLUNTEER` and
    the half-up-rounded product of `hours_worked` and the member's
    `hourly_rate_cents` for `PAID` crew; the member's `cumulative_job_hours` grows
    by the hours worked; and the job's `actual_fee_cents` is recomputed as the
    `quoted_fee_cents` plus the amount — never below zero — by which the summed
    `labor_cost_cents` of the job's completed paid assignments exceeds the quote's
    `included_labor_cents`."

    Design: Corner/calculations/crew_labor_cost_and_fee_overage
    """
    ctx = create_in_progress_job(start="2026-07-02T08:00:00Z", end="2026-07-02T16:00:00Z",
                                 title="Labor Job", quoted_fee_cents=80000,
                                 included_labor_cents=10000)
    volunteer = create_crew_member(full_name="Vol L", crew_type="VOLUNTEER")
    vol_assignment = add_assignment(ctx["job"]["id"], volunteer["id"],
                                    "2026-07-02T08:00:00Z", "2026-07-02T12:00:00Z")

    paid = validate_success(api.complete_assignment(
        ctx["assignment"]["id"], {"hours_worked": 4}, COORD))
    assert paid["labor_cost_cents"] == 20000, (
        f"4h x 5000 = 20000, got {paid['labor_cost_cents']}")
    vol = validate_success(api.complete_assignment(
        vol_assignment["id"], {"hours_worked": 4}, COORD))
    assert vol["labor_cost_cents"] == 0, "volunteer hours cost 0"

    job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
    assert job["actual_fee_cents"] == 90000, (
        f"80000 + max(0, 20000 - 10000) = 90000, got {job['actual_fee_cents']}")


# ---------------------------------------------------------------------------
# Corner: validations / vehicle_maintenance_blocked_with_booked_appointment
# ---------------------------------------------------------------------------

def test_vehicle_maintenance_blocked_with_booked_appointment(api):
    """PRD §3.5: "A coordinator or administrator can send a vehicle to
    `IN_MAINTENANCE` — only while no `BOOKED` pickup appointment references it,
    else `ERR_ACTIVE_APPOINTMENT_EXISTS` — return it to `AVAILABLE`, or retire it
    from `IN_MAINTENANCE` to terminal `RETIRED`."

    Design: Corner/validations/vehicle_maintenance_blocked_with_booked_appointment
    """
    ctx = setup_accepted_pickup_offer(description_text="mnt")
    vehicle = create_vehicle(plate_code="TRK-MNT", capacity_lbs=8000)
    book_appointment("DONATION_OFFER", ctx["offer"]["id"], vehicle["id"],
                     "2026-07-08T09:00:00Z", "2026-07-08T10:00:00Z")
    response = api.update_vehicle(vehicle["id"], {"status": "IN_MAINTENANCE"}, COORD)
    validate_error(response, ApiErrorId.ERR_ACTIVE_APPOINTMENT_EXISTS)
    vehicle = get_success_data(api.get_vehicle(vehicle["id"], COORD))
    assert vehicle["status"] == "AVAILABLE"
