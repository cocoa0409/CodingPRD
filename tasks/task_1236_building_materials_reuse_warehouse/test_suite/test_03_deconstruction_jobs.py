"""Deconstruction jobs: screening gates, remediation cycle, terminal lockdown,
cascading cancel, post-hoc quarantine (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_cleared_job,
    create_in_progress_job,
    create_job,
    create_lead_member,
    create_manifested_batch,
    create_category,
    create_technician,
    create_vehicle,
    get_success_data,
    record_screening,
    schedule_job,
    setup_job_with_weighed_batch,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_hazmat_technician_headers

COORD = TEST_USERS["crew_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / job_hazmat_remediation_cycle
# ---------------------------------------------------------------------------

def _setup_screening_pending_job():
    from test_helpers import api_client
    tech = create_technician(full_name="Tech Three")
    job = create_job(title="Job C", site_address_text="7 Pine", quoted_fee_cents=150000)
    get_success_data(api_client.request_screening(job["id"], COORD))
    return job, tech


class TestJobHazmatRemediationCycle:
    def test_failed_screening_routes_to_hazmat_hold_and_remediation_cycle(self, api):
        """PRD §3.4: "A `CLEARED` outcome on a `SCREENING_PENDING` job moves it to
        `CLEARED` and records the screening's `id` as the job's
        `clearing_screening_id`; a `FAILED` outcome on a `SCREENING_PENDING` job
        moves it to `HAZMAT_HOLD`."
        PRD §3.4: "From `HAZMAT_HOLD` the coordinator begins remediation, moving
        the job to `REMEDIATION_IN_PROGRESS` (any other from-state fails with
        `ERR_JOB_NOT_IN_HAZMAT_HOLD`), and when the cleanup is done, completing
        remediation returns the job to `SCREENING_PENDING` (from any other state,
        `ERR_JOB_NOT_REMEDIATING`) for a fresh screening round."

        Design: Difficulty/non_linear_state_machine/job_hazmat_remediation_cycle
        """
        job, tech = _setup_screening_pending_job()

        screening = record_screening(job["id"], tech["id"],
                                     lead_result="POSITIVE", asbestos_result="NOT_TESTED")
        assert screening["outcome"] == "FAILED", "lead POSITIVE forces FAILED"
        job = get_success_data(api.get_deconstruction_job(job["id"], COORD))
        assert job["status"] == "HAZMAT_HOLD"

        job = validate_success(api.begin_remediation(job["id"], COORD))
        assert job["status"] == "REMEDIATION_IN_PROGRESS"
        job = validate_success(api.complete_remediation(job["id"], COORD))
        assert job["status"] == "SCREENING_PENDING", (
            "remediation completes back to SCREENING_PENDING for a fresh round")

    def test_rescreening_round_increments_and_clears(self, api):
        """PRD §3.4: "its `screening_round` is the 1-based count of screenings
        recorded for that job in `created_at` order, and its `outcome` is computed:
        `CLEARED` when both results are `NEGATIVE`, `FAILED` when either result is
        `POSITIVE`, and `PENDING` otherwise."
        PRD §3.4: "The screening–hold–remediation loop is unbounded, and each pass
        through it increments the job's screening count."

        Design: Difficulty/non_linear_state_machine/job_hazmat_remediation_cycle
        """
        job, tech = _setup_screening_pending_job()
        first = record_screening(job["id"], tech["id"],
                                 lead_result="POSITIVE", asbestos_result="NOT_TESTED")
        assert first["screening_round"] == 1
        assert first["outcome"] == "FAILED"
        validate_success(api.begin_remediation(job["id"], COORD))
        validate_success(api.complete_remediation(job["id"], COORD))

        second = record_screening(job["id"], tech["id"])
        assert second["screening_round"] == 2, (
            f"second pass through the loop is round 2, got {second['screening_round']}")
        assert second["outcome"] == "CLEARED"
        job = get_success_data(api.get_deconstruction_job(job["id"], COORD))
        assert job["status"] == "CLEARED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / job_schedule_requires_cleared_screening
# ---------------------------------------------------------------------------

class TestJobScheduleRequiresClearedScreening:
    def test_schedule_before_clearance_rejected(self, api):
        """PRD §3.4: "Only a `CLEARED` job can be scheduled (`ERR_JOB_NOT_CLEARED`
        otherwise)."

        Design: Difficulty/cross_entity_state_dependency/job_schedule_requires_cleared_screening
        """
        tech = create_technician(full_name="Tech Seven")
        lead = create_lead_member(full_name="Lead Seven")
        vehicle = create_vehicle(plate_code="TRK-7")
        job = create_job(title="Job G", site_address_text="8 Fir", quoted_fee_cents=90000)
        get_success_data(api.request_screening(job["id"], COORD))
        response = api.schedule_job(job["id"], {
            "lead_crew_member_id": lead["id"], "vehicle_id": vehicle["id"],
            "scheduled_start": "2026-07-01T08:00:00Z", "scheduled_end": "2026-07-01T16:00:00Z",
        }, COORD)
        validate_error(response, ApiErrorId.ERR_JOB_NOT_CLEARED)

    def test_schedule_after_clearance_succeeds(self, api):
        """PRD §3.4: "Only a `CLEARED` job can be scheduled (`ERR_JOB_NOT_CLEARED`
        otherwise). Scheduling assigns the `lead_crew_member_id`, the `vehicle_id`,
        and the job window from `scheduled_start` (inclusive) to `scheduled_end`
        (exclusive), and enforces a battery of checks."

        Design: Difficulty/cross_entity_state_dependency/job_schedule_requires_cleared_screening
        """
        tech = create_technician(full_name="Tech Seven")
        lead = create_lead_member(full_name="Lead Seven")
        vehicle = create_vehicle(plate_code="TRK-7")
        job = create_job(title="Job G", site_address_text="8 Fir", quoted_fee_cents=90000)
        get_success_data(api.request_screening(job["id"], COORD))
        record_screening(job["id"], tech["id"])
        scheduled = schedule_job(job["id"], lead["id"], vehicle["id"],
                                 "2026-07-01T08:00:00Z", "2026-07-01T16:00:00Z")
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["lead_crew_member_id"] == lead["id"]
        assert scheduled["vehicle_id"] == vehicle["id"]


# ---------------------------------------------------------------------------
# Corner: state_machines / completed_job_lockdown_cancel_rejected
# ---------------------------------------------------------------------------

def test_completed_job_lockdown_cancel_rejected(api):
    """PRD §3.4: "Completion, by the coordinator or the assigned lead under the
    same ownership rule, requires the job to be `IN_PROGRESS`
    (`ERR_JOB_NOT_IN_PROGRESS`) and no batch of the job to stand `QUARANTINED`
    (`ERR_QUARANTINED_BATCHES_OPEN`); completion lands the job in terminal
    `COMPLETED` with its certified tonnage finalized from its `WEIGHED` and
    `SORTED` batches."
    PRD §2.10: "7. **State** — the target resource stands in the from-state the
    transition requires, else the per-entity state error (§5), each an HTTP 409."

    Design: Corner/state_machines/completed_job_lockdown_cancel_rejected
    """
    ctx = create_in_progress_job(start="2026-06-22T08:00:00Z", end="2026-06-22T16:00:00Z",
                                 title="Lock Job", quoted_fee_cents=1000)
    job = validate_success(api.complete_job(ctx["job"]["id"], COORD))
    assert job["status"] == "COMPLETED"

    response = api.cancel_job(job["id"], COORD)
    validate_error(response, ApiErrorId.ERR_INVALID_JOB_STATE)
    after = get_success_data(api.get_deconstruction_job(job["id"], COORD))
    assert after["status"] == "COMPLETED", "terminal state must not be left by cancel"


# ---------------------------------------------------------------------------
# Corner: state_machines / job_cancel_cascades_to_assignments_and_appointments
# ---------------------------------------------------------------------------

def test_job_cancel_cascades_to_assignments_and_appointments(api):
    """PRD §3.4: "From `SCHEDULED`, the cancellation cascades downward: every crew
    assignment of the job still `ASSIGNED` is cancelled, and every pickup
    appointment booked for the job as a `DECONSTRUCTION_JOB` subject and still
    `BOOKED` is cancelled."

    Design: Corner/state_machines/job_cancel_cascades_to_assignments_and_appointments
    """
    from test_helpers import add_assignment, book_appointment, create_scheduled_job

    ctx = create_scheduled_job(start="2026-06-24T08:00:00Z", end="2026-06-24T16:00:00Z",
                               title="Cascade Job", quoted_fee_cents=1000)
    assignment = add_assignment(ctx["job"]["id"], ctx["lead"]["id"],
                                "2026-06-24T08:00:00Z", "2026-06-24T12:00:00Z",
                                role_on_job="LEAD")
    appointment = book_appointment("DECONSTRUCTION_JOB", ctx["job"]["id"],
                                   ctx["vehicle"]["id"],
                                   "2026-06-25T09:00:00Z", "2026-06-25T10:00:00Z",
                                   as_intake=False)
    job = validate_success(api.cancel_job(ctx["job"]["id"], COORD))
    assert job["status"] == "CANCELLED"

    assignment = get_success_data(api.get_crew_assignment(assignment["id"], COORD))
    assert assignment["status"] == "CANCELLED", "ASSIGNED assignment cascades to CANCELLED"
    appointment = get_success_data(api.get_pickup_appointment(appointment["id"], COORD))
    assert appointment["status"] == "CANCELLED", "BOOKED appointment cascades to CANCELLED"


# ---------------------------------------------------------------------------
# Corner: state_machines / failed_screening_quarantines_only_weighed_batches
# ---------------------------------------------------------------------------

def test_failed_screening_quarantines_only_weighed_batches(api):
    """PRD §3.4: "A `FAILED` outcome can also arrive post-hoc, while the job is
    already `IN_PROGRESS`: the job drops to `HAZMAT_HOLD`, every one of its batches
    standing in `WEIGHED` is forced to `QUARANTINED`, and each quarantined batch's
    diverted pounds are subtracted from the job's certified tonnage — a conditional
    cascade with compensation."

    Design: Corner/state_machines/failed_screening_quarantines_only_weighed_batches
    """
    ctx = setup_job_with_weighed_batch(
        scale_weight_lbs=480, contamination_weight_lbs=30, estimated_weight_lbs=500,
        start="2026-06-26T08:00:00Z", end="2026-06-26T16:00:00Z",
        code="QCAT", display_name="Q Cat", hazmat_risk_flag=True,
    )
    assert ctx["batch"]["diverted_weight_lbs"] == 450
    assert ctx["job"]["certified_diverted_weight_lbs"] == 450
    batch2 = create_manifested_batch(ctx["job"]["id"], ctx["category"]["id"],
                                     estimated_weight_lbs=200)

    record_screening(ctx["job"]["id"], ctx["tech"]["id"],
                     lead_result="POSITIVE", asbestos_result="NOT_TESTED")

    job = get_success_data(api.get_deconstruction_job(ctx["job"]["id"], COORD))
    assert job["status"] == "HAZMAT_HOLD"
    assert job["certified_diverted_weight_lbs"] == 0, (
        f"quarantined batch's 450 diverted pounds subtracted: {job['certified_diverted_weight_lbs']}")
    batch1 = get_success_data(api.get_salvage_batch(ctx["batch"]["id"], COORD))
    assert batch1["status"] == "QUARANTINED"
    batch2 = get_success_data(api.get_salvage_batch(batch2["id"], COORD))
    assert batch2["status"] == "MANIFESTED", (
        "conditional cascade touches only WEIGHED batches; MANIFESTED is untouched")


# ---------------------------------------------------------------------------
# Corner: entities / screening_immutable_record_shape
# ---------------------------------------------------------------------------

def test_screening_immutable_record_shape(api):
    """PRD §2.5: "Three resources are deliberately leaner: a `HazmatScreening`, a
    `MarkdownRun`, and a `SaleLineItem` each carry only `id` and `created_at`. Both
    `updated_at` and `version` are absent from these three; they are never mutated
    after creation, so there is nothing to version."
    PRD §3.4: "its `outcome` is computed: `CLEARED` when both results are
    `NEGATIVE`, `FAILED` when either result is `POSITIVE`, and `PENDING` otherwise."

    Design: Corner/entities/screening_immutable_record_shape
    """
    tech = create_technician(full_name="Tech C", crew_type="VOLUNTEER")
    job = create_job(title="Imm Job", site_address_text="3 Rd", quoted_fee_cents=1000)
    get_success_data(api.request_screening(job["id"], COORD))
    screening = record_screening(job["id"], tech["id"],
                                 lead_result="NEGATIVE", asbestos_result="NOT_TESTED")
    assert screening["outcome"] == "PENDING", "asbestos NOT_TESTED leaves outcome PENDING"
    assert screening["screening_round"] == 1
    assert "version" not in screening, "screening carries no version (lean record)"
    assert "updated_at" not in screening, "screening carries no updated_at (lean record)"
    assert screening["id"] and screening["created_at"]


# ---------------------------------------------------------------------------
# Corner: rbac / technician_requires_hazmat_certification
# ---------------------------------------------------------------------------

def test_technician_requires_hazmat_certification(api):
    """PRD §3.4: "A `HazmatTechnician` — who must hold hazmat certification, else
    `ERR_CERTIFICATION_MISMATCH` — records a `HazmatScreening` naming the `job_id`,
    a `lead_result` and an `asbestos_result`, each one of `NOT_TESTED`, `NEGATIVE`,
    or `POSITIVE`, and optional technician `notes`."

    Design: Corner/rbac/technician_requires_hazmat_certification
    """
    from test_helpers import create_crew_member

    uncertified = create_crew_member(full_name="Not Cert", crew_type="VOLUNTEER",
                                     hazmat_certified=False)
    job = create_job(title="Cert Job", site_address_text="24 Rd", quoted_fee_cents=1000)
    get_success_data(api.request_screening(job["id"], COORD))
    response = api.create_hazmat_screening(
        {"job_id": job["id"], "lead_result": "NEGATIVE", "asbestos_result": "NEGATIVE"},
        make_hazmat_technician_headers(uncertified["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_MISMATCH)
    screenings = api.list_hazmat_screenings(COORD, params={"job_id": job["id"]})
    from test_helpers import validate_paginated
    rows, meta = validate_paginated(screenings)
    assert rows == [], "no screening may be persisted for an uncertified technician"
