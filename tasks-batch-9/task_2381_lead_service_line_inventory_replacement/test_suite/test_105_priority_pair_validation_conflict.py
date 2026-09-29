"""Queue A - rule ``priority_pair_validation_conflict``.

Three requests that each violate two or three rungs of the §2.10 ladder at once.
The ladder is normative, so only the earliest applicable rung may be reported.
Each instance is probed twice: once with every rung of the pair violated, and
once with the higher rung satisfied so that the suppressed lower rung surfaces
and is proved to have been genuinely violated all along.
"""

from test_helpers import ApiClient, factories, fixtures, validate_error
from test_helpers.test_users import ADMIN_HEADERS, CONTRACTOR_HEADERS
from test_helpers.types import (
    AppointmentState,
    CctOptimizationStatus,
    ConsentOutcome,
    ConsentState,
    FulfillmentState,
    FundingMode,
    OrderScope,
    ProgramPosture,
    SourceKind,
    VerificationMethod,
)


# ---------------------------------------------------------------------------
# funding_plan_on_draft_order_prefers_consent_error_over_fiscal_error
# ---------------------------------------------------------------------------


def _draft_order_with_no_money_at_all(api: ApiClient):
    """A DRAFT order on a published system that owns not one funding source."""
    system = fixtures.create_water_system(
        api,
        "IL2031010",
        system_name="Ashgrove Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(api, system["id"])
    fixtures.publish_inventory(api, system["id"], line["id"])
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    return {"system": system, "line": line, "order": order}


def test_funding_plan_reports_unresolved_consent_before_state_or_fiscal_failure(
    api: ApiClient,
) -> None:
    """A DRAFT order with no consent and no money at all reports rung 12, not 13 or 24.

    PRD 2.10: "The ordering is normative: a request that violates two rules always
    reports the higher rung's error, never the lower one's."
    PRD 2.10: "Before the funding plan even looks at the order's work state, it
    requires the consent canvass to be settled: `consent_state` must be `GRANTED`,
    `DENIED` or `NO_RESPONSE` and `scope` must be non-null, else
    `ERR_CONSENT_NOT_RESOLVED` (409)."
    PRD 2.10: "This rung sits deliberately **above** the general work-state check
    on the next rung, so that an order still parked in `DRAFT` is told the real
    reason — consent is unresolved — rather than merely that its state is wrong."

    Design: Difficulty/priority_pair_validation_conflict/funding_plan_on_draft_order_prefers_consent_error_over_fiscal_error
    """
    scenario = _draft_order_with_no_money_at_all(api)
    order = scenario["order"]
    assert order["fulfillment_state"] == FulfillmentState.DRAFT
    assert order["consent_state"] == ConsentState.NOT_REQUESTED

    response = api.plan_funding(order["id"], ADMIN_HEADERS)

    error = validate_error(response, "ERR_CONSENT_NOT_RESOLVED", 409)
    assert error["error_id"] != "ERR_ORDER_STATE_INVALID"
    assert error["error_id"] != "ERR_FUNDING_INSUFFICIENT"

    unchanged = fixtures.read_order(api, order["id"])
    assert unchanged["fulfillment_state"] == FulfillmentState.DRAFT
    assert unchanged["funding_allocations"] == []
    assert unchanged["allocated_total_cents"] == 0


def test_resolving_consent_lets_the_suppressed_fiscal_rung_surface(
    api: ApiClient,
) -> None:
    """With consent GRANTED the very same plan reports the empty candidate pool at 402.

    PRD 3.7: "A `ProgramAdministrator` commits a funding plan against a `SCOPED`
    order, moving it to `FUNDED`."
    PRD 3.7: "The candidate pool is pinned. It comprises the funding sources of the
    order's water system whose `status` is `ACTIVE` and whose `available_cents` is
    strictly greater than zero, ordered by `priority_rank` ascending with ties
    broken by `created_at` ascending."
    PRD 3.7: "If the pool is empty, the commit fails with `ERR_FUNDING_INSUFFICIENT`
    (HTTP 402)."
    PRD 2.10: "**Funding sufficiency.** `ERR_FUNDING_INSUFFICIENT` (402) when the
    candidate pool cannot cover the order's estimated cost. This is the last rung:
    an order that is both equity-breaching and underfunded reports the equity
    breach."

    Design: Difficulty/priority_pair_validation_conflict/funding_plan_on_draft_order_prefers_consent_error_over_fiscal_error
    """
    scenario = _draft_order_with_no_money_at_all(api)
    order = scenario["order"]
    scoped = fixtures.resolve_consent(api, order["id"], outcome=ConsentOutcome.GRANTED)
    assert scoped["fulfillment_state"] == FulfillmentState.SCOPED
    assert scoped["consent_state"] == ConsentState.GRANTED
    assert scoped["scope"] == OrderScope.FULL

    response = api.plan_funding(order["id"], ADMIN_HEADERS)

    error = validate_error(response, "ERR_FUNDING_INSUFFICIENT", 402)
    assert error["error_id"] != "ERR_CONSENT_NOT_RESOLVED"

    unchanged = fixtures.read_order(api, order["id"])
    assert unchanged["fulfillment_state"] == FulfillmentState.SCOPED
    assert unchanged["funding_allocations"] == []
    assert unchanged["allocated_total_cents"] == 0


# ---------------------------------------------------------------------------
# schedule_prefers_corrosion_control_safety_over_moratorium_conflict
# ---------------------------------------------------------------------------


def _funded_order_inside_the_moratorium(api: ApiClient):
    """A FUNDED order whose 08-10..08-12 window sits inside a 08-05..08-20 moratorium."""
    system = fixtures.create_water_system(
        api,
        "IL2031011",
        system_name="Brackenmill Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    project = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Elm St Resurfacing",
        moratorium_start_date="2026-08-05",
        moratorium_end_date="2026-08-20",
        paving_start_date="2027-06-01",
        max_concurrent_excavations=2,
    )
    line = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", street_project_id=project["id"]
    )
    fixtures.publish_inventory(api, system["id"], line["id"])
    fixtures.deliver_notification_for_line(api, line["id"], delivered_at="2026-08-01T09:00:00Z")
    fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=200000,
        priority_rank=1,
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        max_share_pct=100.0,
        equity_required_pct=0.0,
    )
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-12",
        street_project_id=project["id"],
    )
    fixtures.resolve_consent(api, order["id"], outcome=ConsentOutcome.GRANTED)
    funded = fixtures.plan_funding(api, order["id"])
    assert funded["fulfillment_state"] == FulfillmentState.FUNDED
    return {"system": system, "project": project, "line": line, "order": order}


def test_schedule_reports_the_corrosion_control_safety_gate_before_the_moratorium(
    api: ApiClient,
) -> None:
    """A window inside the moratorium during re-optimization reports rung 19, not 21.

    PRD 2.10: "**Safety gates.** `ERR_CCT_NOT_OPTIMIZED` (422) when excavation is
    scheduled during corrosion-control re-optimization; `ERR_NOTIFICATION_OVERDUE_BLOCK`
    (409) when certification is attempted while any notification of the water
    system is overdue."
    PRD 2.10: "**Temporal conflicts.** `ERR_CREW_WINDOW_CONFLICT` (409),
    `ERR_MORATORIUM_CONFLICT` (409), `ERR_COMPLIANCE_DEADLINE_PASSED` (409),
    `ERR_PERIOD_OVERLAP` (409) and `ERR_CLOCK_NOT_MONOTONIC` (422)."
    PRD 3.7: "Its `cct_optimization_status` must not be `PENDING_REOPTIMIZATION` —
    excavation may not proceed while corrosion control is being re-optimized —
    else `ERR_CCT_NOT_OPTIMIZED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_prefers_corrosion_control_safety_over_moratorium_conflict
    """
    scenario = _funded_order_inside_the_moratorium(api)
    patched = fixtures.patch_corrosion_control(
        api,
        scenario["system"]["id"],
        cct_optimization_status=CctOptimizationStatus.PENDING_REOPTIMIZATION,
        cct_orthophosphate_mg_l=3.0,
        cct_target_ph=7.5,
    )
    assert patched["program_posture"] == ProgramPosture.OPEN
    assert patched["cct_optimization_status"] == CctOptimizationStatus.PENDING_REOPTIMIZATION

    response = api.schedule_order(
        scenario["order"]["id"],
        factories.schedule_order_payload("2026-08-10", "2026-08-12"),
        CONTRACTOR_HEADERS,
    )

    error = validate_error(response, "ERR_CCT_NOT_OPTIMIZED", 422)
    assert error["error_id"] != "ERR_MORATORIUM_CONFLICT"
    assert error["error_id"] != "ERR_PROGRAM_POSTURE_RESTRICTED"

    unchanged = fixtures.read_order(api, scenario["order"]["id"])
    assert unchanged["fulfillment_state"] == FulfillmentState.FUNDED
    assert (
        fixtures.read_street_project(api, scenario["project"]["id"])[
            "active_excavation_order_count"
        ]
        == 0
    )


def test_clearing_the_safety_gate_lets_the_suppressed_moratorium_rung_surface(
    api: ApiClient,
) -> None:
    """With corrosion control untouched the identical window reports the moratorium at 409.

    PRD 3.7: "**Scheduling and breaking ground.** A `ReplacementContractor`
    schedules a `FUNDED` order into a concrete window by supplying
    `excavation_start_date` and `excavation_end_date`, moving the order to
    `SCHEDULED`."
    PRD 3.7: "The requested window must not intersect the linked street project's
    moratorium: with both windows treated as closed inclusive date ranges, the
    request is refused with `ERR_MORATORIUM_CONFLICT` when the excavation start
    falls on or before the moratorium end and the excavation end falls on or after
    the moratorium start."

    Design: Difficulty/priority_pair_validation_conflict/schedule_prefers_corrosion_control_safety_over_moratorium_conflict
    """
    scenario = _funded_order_inside_the_moratorium(api)
    system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert system["cct_optimization_status"] != CctOptimizationStatus.PENDING_REOPTIMIZATION
    assert system["program_posture"] == ProgramPosture.OPEN

    response = api.schedule_order(
        scenario["order"]["id"],
        factories.schedule_order_payload("2026-08-10", "2026-08-12"),
        CONTRACTOR_HEADERS,
    )

    error = validate_error(response, "ERR_MORATORIUM_CONFLICT", 409)
    assert error["error_id"] != "ERR_CCT_NOT_OPTIMIZED"

    unchanged = fixtures.read_order(api, scenario["order"]["id"])
    assert unchanged["fulfillment_state"] == FulfillmentState.FUNDED
    assert (
        fixtures.read_street_project(api, scenario["project"]["id"])[
            "active_excavation_order_count"
        ]
        == 0
    )


# ---------------------------------------------------------------------------
# appointment_create_prefers_uncertified_method_over_crew_window_conflict
# ---------------------------------------------------------------------------


def _crew_certified_for_visual_work_only(api: ApiClient):
    """A VISUAL_INSPECTION-only crew already holding 09:00-10:00 on 2026-08-05."""
    system = fixtures.create_water_system(
        api,
        "IL2031012",
        system_name="Thistledown Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    crew = fixtures.create_crew(
        api,
        system["id"],
        crew_name="Crew Visual",
        shift_start_utc_time="08:00",
        shift_end_utc_time="18:00",
        daily_appointment_capacity=5,
        certified_methods=[VerificationMethod.VISUAL_INSPECTION],
    )
    first = fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.VISUAL_INSPECTION,
        window_start_utc="2026-08-05T09:00:00Z",
        window_end_utc="2026-08-05T10:00:00Z",
    )
    return {"system": system, "line": line, "crew": crew, "first": first}


def test_booking_reports_the_uncertified_method_before_the_window_conflict(
    api: ApiClient,
) -> None:
    """A POTHOLE booking inside the travel buffer reports rung 20, not rung 21.

    PRD 2.10: "**Uniqueness, membership and shape.** `ERR_DUPLICATE_PWSID`,
    `ERR_DUPLICATE_ADDRESS_LABEL` and `ERR_DUPLICATE_STRATUM_CODE` (all 409);
    `ERR_CREW_METHOD_NOT_CERTIFIED`, `ERR_CREW_OUTSIDE_SHIFT`,
    `ERR_EVIDENCE_SIDE_MISMATCH`, `ERR_REPLACED_SIDES_MISMATCH` and
    `ERR_SAMPLE_COUNT_INSUFFICIENT` (all 422); and `ERR_SAMPLE_NOT_FOUND` (404)
    when a supplied `sample_seq` matches no entry of the batch's `samples`."
    PRD 3.3: "First, the requested `method` must be a member of the crew's
    `certified_methods`, else `ERR_CREW_METHOD_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/appointment_create_prefers_uncertified_method_over_crew_window_conflict
    """
    scenario = _crew_certified_for_visual_work_only(api)

    response = api.create_verification_appointment(
        factories.verification_appointment_payload(
            scenario["line"]["id"],
            scenario["crew"]["id"],
            method=VerificationMethod.POTHOLE,
            window_start_utc="2026-08-05T10:30:00Z",
            window_end_utc="2026-08-05T11:30:00Z",
        ),
        ADMIN_HEADERS,
    )

    error = validate_error(response, "ERR_CREW_METHOD_NOT_CERTIFIED", 422)
    assert error["error_id"] != "ERR_CREW_WINDOW_CONFLICT"

    assert (
        fixtures.read_appointment(api, scenario["first"]["id"])["state"]
        == AppointmentState.SCHEDULED
    )
    assert fixtures.read_crew(api, scenario["crew"]["id"])["scheduled_appointment_count"] == 1


def test_naming_a_certified_method_lets_the_suppressed_window_rung_surface(
    api: ApiClient,
) -> None:
    """The identical 10:30-11:30 window as VISUAL_INSPECTION reports the buffer breach.

    PRD 3.3: "Third, the crew must not already be committed elsewhere at that time,
    and the collision test carries a travel buffer: measured against every other
    appointment of the same `crew_id` whose `state` is `SCHEDULED`, `ON_SITE` or
    `COMPLETED`, the booking is refused with `ERR_CREW_WINDOW_CONFLICT` when the
    new window's start is earlier than three quarters of an hour past the existing
    appointment's end **and** the new window's end is strictly later than the
    existing appointment's start."
    PRD 3.3: "The buffer is applied to the existing appointment's end only, and the
    comparison at the new window's start is strict-less-than, so a new window
    beginning exactly 45 minutes after an existing one ends is accepted."

    Design: Difficulty/priority_pair_validation_conflict/appointment_create_prefers_uncertified_method_over_crew_window_conflict
    """
    scenario = _crew_certified_for_visual_work_only(api)

    response = api.create_verification_appointment(
        factories.verification_appointment_payload(
            scenario["line"]["id"],
            scenario["crew"]["id"],
            method=VerificationMethod.VISUAL_INSPECTION,
            window_start_utc="2026-08-05T10:30:00Z",
            window_end_utc="2026-08-05T11:30:00Z",
        ),
        ADMIN_HEADERS,
    )

    error = validate_error(response, "ERR_CREW_WINDOW_CONFLICT", 409)
    assert error["error_id"] != "ERR_CREW_METHOD_NOT_CERTIFIED"

    assert fixtures.read_crew(api, scenario["crew"]["id"])["scheduled_appointment_count"] == 1
