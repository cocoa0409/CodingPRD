"""Scheduling site visits: prior-inspection rules, the season gate and the buffer."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    INSPECTOR_ONE_ID,
    ApiErrorId,
    create_inspection_payload,
    log_water_reading,
    make_inspector_headers,
    read_inspection,
    schedule_inspection,
    setup_facility_with_issued_permit,
    setup_finalized_inspection,
    setup_inspection_in_progress,
    setup_operator_and_pool,
    setup_operator_with_two_pools,
    submit_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    void_inspection,
)


def test_reinspection_without_a_prior_inspection_rejected(api):
    """PRD 3.5: A reinspection additionally names the `prior_inspection_id` of
    the finalized visit whose findings are being re-checked; every other
    inspection type must leave that field null, and getting this wrong either way
    is rejected with `ERR_INSPECTION_TYPE_REQUIRES_PRIOR` (HTTP 422).

    Design: Corner/validations/reinspection_without_prior_inspection_rejected
    """
    ctx = setup_operator_and_pool()

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                ctx["facility_id"], inspection_type="REINSPECTION",
                scheduled_start_at="2026-05-02T09:00:00Z",
                scheduled_end_at="2026-05-02T10:00:00Z",
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_INSPECTION_TYPE_REQUIRES_PRIOR.value, 422,
    )

    rows, meta = validate_paginated(
        api.list_inspections(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_reinspection_naming_another_venues_prior_visit_rejected(api):
    """PRD 3.5: When a prior inspection is named, it must belong to the same
    facility and its `workflow_status` must be `FINALIZED`, or the request is
    rejected with `ERR_PRIOR_INSPECTION_MISMATCH`.

    Design: Corner/validations/reinspection_prior_belonging_to_another_facility_rejected
    """
    ctx = setup_operator_with_two_pools(
        operator_overrides={
            "legal_name": "Twin Pools Trust",
            "contact_email": "ops@twinpools.example",
        }
    )
    finalized, _ = setup_finalized_inspection(ctx["facility_a_id"])

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                ctx["facility_b_id"], inspection_type="REINSPECTION",
                scheduled_start_at="2026-05-02T09:00:00Z",
                scheduled_end_at="2026-05-02T10:00:00Z",
                prior_inspection_id=finalized["id"],
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_PRIOR_INSPECTION_MISMATCH.value, 409,
    )

    rows, meta = validate_paginated(
        api.list_inspections(ADMIN, params={"prior_inspection_id": finalized["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_a_voided_visit_stops_blocking_the_scheduling_window(api):
    """PRD 3.5: A new visit conflicts with any other inspection of the same
    facility whose `workflow_status` is `SCHEDULED`, `IN_PROGRESS`, `SUBMITTED`
    or `FINALIZED` — voided inspections are ignored — when the new start is at or
    before that other visit's end extended forward by 60 minutes **and** the new
    end is at or after that other visit's start pulled back by 60 minutes.
    PRD 3.5: Voiding is available from every non-voided workflow state —
    `SCHEDULED`, `IN_PROGRESS`, `SUBMITTED` and `FINALIZED` all move to `VOIDED`

    Design: Corner/validations/voided_inspection_no_longer_blocks_the_scheduling_window
    """
    ctx = setup_operator_and_pool()
    first = schedule_inspection(
        ctx["facility_id"], INSPECTOR,
        scheduled_start_at="2026-05-02T09:00:00Z",
        scheduled_end_at="2026-05-02T11:00:00Z",
    )
    void_inspection(first["id"])

    second = validate_success(
        api.create_inspection(
            create_inspection_payload(
                ctx["facility_id"],
                scheduled_start_at="2026-05-02T12:00:00Z",
                scheduled_end_at="2026-05-02T13:00:00Z",
            ),
            INSPECTOR,
        ),
        201,
    )

    assert second["workflow_status"] == "SCHEDULED"
    assert read_inspection(first["id"])["workflow_status"] == "VOIDED"

    rows, meta = validate_paginated(
        api.list_inspections(
            ADMIN,
            params={
                "facility_id": ctx["facility_id"],
                "workflow_status": "SCHEDULED",
            },
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == second["id"]


def test_routine_visit_outside_the_declared_season_rejected(api):
    """PRD 3.5: **Routine visits respect the season.** For an `inspection_type`
    of `ROUTINE` at a facility whose `is_seasonal` is true, the date part of
    `scheduled_start_at` must fall inside the inclusive range from
    `season_start_date` to `season_end_date`; otherwise `ERR_OUT_OF_SEASON`. The
    other three inspection types are not season-gated.
    PRD 2.9: The facility has no permit records at all → `CLOSED` with reason
    `PERMIT_MISSING`.

    Design: Corner/validations/routine_inspection_outside_the_declared_season_rejected
    """
    ctx = setup_operator_and_pool(
        operator_overrides={
            "legal_name": "Lakeside Recreation District",
            "contact_email": "permits@lakeside.example",
        },
        name="Lakeside Seasonal Pool",
        is_seasonal=True,
        season_start_date="2026-06-01",
        season_end_date="2026-08-31",
    )

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                ctx["facility_id"],
                scheduled_start_at="2026-05-02T09:00:00Z",
                scheduled_end_at="2026-05-02T10:00:00Z",
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_OUT_OF_SEASON.value, 409,
    )

    complaint_visit = validate_success(
        api.create_inspection(
            create_inspection_payload(
                ctx["facility_id"], inspection_type="COMPLAINT",
                scheduled_start_at="2026-05-02T09:00:00Z",
                scheduled_end_at="2026-05-02T10:00:00Z",
            ),
            INSPECTOR,
        ),
        201,
    )
    assert complaint_visit["workflow_status"] == "SCHEDULED"

    facility = validate_success(api.get_facility(ctx["facility_id"], ADMIN))
    assert facility["operating_posture"] == "CLOSED"
    assert facility["posture_reason"] == "PERMIT_MISSING"


def test_a_different_inspector_may_not_start_the_visit(api):
    """PRD 3.5: The inspector who created the row is the only one who may start
    it or submit it; any other inspector attempting either action is rejected
    with `ERR_INVALID_INSPECTION_STATE`.
    PRD 3.5: The row is created in `SCHEDULED` with `enforcement_status`
    initialised to `NONE` and `inspector_user_id` taken from the acting
    `X-User-ID`; that field is immutable thereafter.

    Design: Corner/state_machines/inspection_start_by_a_different_inspector_rejected
    """
    ctx = setup_operator_and_pool()
    inspection = schedule_inspection(ctx["facility_id"], INSPECTOR)

    validate_error(
        api.transition_inspection(
            inspection["id"], {"action": "START"}, make_inspector_headers("insp-2")
        ),
        ApiErrorId.ERR_INVALID_INSPECTION_STATE.value, 409,
    )

    unchanged = read_inspection(inspection["id"])
    assert unchanged["workflow_status"] == "SCHEDULED"
    assert unchanged["inspector_user_id"] == INSPECTOR_ONE_ID


def test_findings_may_not_be_appended_after_submission(api):
    """PRD 3.6: Findings may only be appended while the parent's
    `workflow_status` is `IN_PROGRESS`; an attempt outside that window is
    `ERR_INVALID_INSPECTION_STATE`.
    PRD 3.5: Submitting advances `IN_PROGRESS → SUBMITTED`, stamps
    `submitted_at`, and closes the finding list — no further violation may be
    appended after that point.

    Design: Corner/state_machines/violation_append_after_submit_rejected
    """
    ctx = setup_operator_and_pool()
    inspection = setup_inspection_in_progress(ctx["facility_id"])
    first_finding = validate_success(
        api.create_violation(
            inspection["id"],
            {
                "code": "SN-201",
                "severity": "NONCRITICAL",
                "description": "Deck hose left uncoiled",
                "corrected_on_site": False,
            },
            INSPECTOR,
        ),
        201,
    )
    submit_inspection(inspection["id"])

    validate_error(
        api.create_violation(
            inspection["id"],
            {
                "code": "SN-202",
                "severity": "NONCRITICAL",
                "description": "Log book entry missing",
                "corrected_on_site": False,
            },
            INSPECTOR,
        ),
        ApiErrorId.ERR_INVALID_INSPECTION_STATE.value, 409,
    )

    rows, meta = validate_paginated(api.list_violations(inspection["id"], ADMIN))
    assert meta["total_count"] == 1 and rows[0]["id"] == first_finding["id"]


def test_every_declared_list_filter_resolves_its_foreign_key(api):
    """PRD 3.1: Facilities can be listed and narrowed by `operator_id`, by
    `facility_class`, or by `operating_posture`.
    PRD 3.7: Closure orders can be read individually or listed and narrowed by
    `facility_id`, by `triggering_reading_id` or by `status`.
    PRD 3.1: Ledger history can be read one posting at a time, or listed and
    narrowed by `operator_id`, by `permit_id` or by `entry_type`, with the usual
    `limit` and `offset` paging.
    PRD 3.5: Inspections can be read individually or listed and narrowed by
    `facility_id`, by `prior_inspection_id`, by `inspection_type`, by
    `workflow_status` or by `enforcement_status`.

    Design: Corner/endpoints/filtered_list_endpoints_resolve_every_declared_foreign_key
    """
    ctx = setup_facility_with_issued_permit()
    routine, _ = setup_finalized_inspection(ctx["facility_id"])
    reinspection = schedule_inspection(
        ctx["facility_id"], INSPECTOR, inspection_type="REINSPECTION",
        scheduled_start_at="2026-05-03T09:00:00Z",
        scheduled_end_at="2026-05-03T10:00:00Z",
        prior_inspection_id=routine["id"],
    )
    hazard_reading = log_water_reading(
        ctx["facility_id"], ctx["op_headers"], free_chlorine_ppm=0.2
    )

    facilities, facilities_meta = validate_paginated(
        api.list_facilities(
            ctx["op_headers"], params={"operator_id": ctx["operator_id"]}
        )
    )
    assert facilities_meta["total_count"] == 1
    assert facilities[0]["id"] == ctx["facility_id"]

    orders, orders_meta = validate_paginated(
        api.list_closure_orders(
            INSPECTOR, params={"triggering_reading_id": hazard_reading["id"]}
        )
    )
    assert orders_meta["total_count"] == 1
    assert orders[0]["closure_reason"] == "WATER_CHEMISTRY"

    postings, postings_meta = validate_paginated(
        api.list_fee_ledger_entries(ADMIN, params={"permit_id": ctx["permit_id"]})
    )
    assert postings_meta["total_count"] == 1
    assert postings[0]["entry_type"] == "PERMIT_FEE"
    assert postings[0]["amount_cents"] == 40000

    reinspections, reinspections_meta = validate_paginated(
        api.list_inspections(INSPECTOR, params={"prior_inspection_id": routine["id"]})
    )
    assert reinspections_meta["total_count"] == 1
    assert reinspections[0]["id"] == reinspection["id"]
    assert reinspections[0]["inspection_type"] == "REINSPECTION"


class TestBufferedInspectionWindow:
    """The 60-minute buffer is applied to both ends with inclusive comparisons."""

    @staticmethod
    def _setup():
        ctx = setup_operator_and_pool()
        ctx["first"] = schedule_inspection(
            ctx["facility_id"], INSPECTOR,
            scheduled_start_at="2026-05-02T09:00:00Z",
            scheduled_end_at="2026-05-02T11:00:00Z",
        )
        return ctx

    def test_a_visit_at_the_exact_buffer_edge_conflicts(self, api):
        """PRD 3.5: Both comparisons are inclusive, so a visit that begins
        exactly 60 minutes after another one ends still conflicts, and the
        request is rejected with `ERR_INSPECTION_WINDOW_CONFLICT`.

        Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_window_conflicts_at_exact_buffer_edge
        """
        ctx = self._setup()

        validate_error(
            api.create_inspection(
                create_inspection_payload(
                    ctx["facility_id"],
                    scheduled_start_at="2026-05-02T12:00:00Z",
                    scheduled_end_at="2026-05-02T13:00:00Z",
                ),
                INSPECTOR,
            ),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT.value, 409,
        )

        untouched = read_inspection(ctx["first"]["id"])
        assert untouched["workflow_status"] == "SCHEDULED"
        assert untouched["enforcement_status"] == "NONE"

        rows, meta = validate_paginated(
            api.list_inspections(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert meta["total_count"] == 1 and rows[0]["id"] == ctx["first"]["id"]

    def test_a_visit_one_minute_past_the_buffer_is_accepted(self, api):
        """PRD 3.5: A new visit conflicts with any other inspection of the same
        facility whose `workflow_status` is `SCHEDULED`, `IN_PROGRESS`,
        `SUBMITTED` or `FINALIZED` — voided inspections are ignored — when the
        new start is at or before that other visit's end extended forward by 60
        minutes **and** the new end is at or after that other visit's start
        pulled back by 60 minutes.

        Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_window_conflicts_at_exact_buffer_edge
        """
        ctx = self._setup()

        accepted = validate_success(
            api.create_inspection(
                create_inspection_payload(
                    ctx["facility_id"],
                    scheduled_start_at="2026-05-02T12:01:00Z",
                    scheduled_end_at="2026-05-02T13:00:00Z",
                ),
                INSPECTOR,
            ),
            201,
        )
        assert accepted["workflow_status"] == "SCHEDULED"

        rows, meta = validate_paginated(
            api.list_inspections(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {ctx["first"]["id"], accepted["id"]}
