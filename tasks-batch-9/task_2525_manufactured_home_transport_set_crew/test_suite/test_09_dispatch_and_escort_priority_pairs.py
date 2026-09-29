"""Validation-priority pairs on dispatch and on escort reservation (PRD §2.10).

Two requests here each break two rules at once. A dispatch that is both
site-blocked and crew-unlicensed must report the priority-8 site error, and an
escort reservation that is both unendorsed and window-clashing must report the
priority-12 safety error. Curing only the higher-ranked fault then exposes the
lower-ranked one on an otherwise identical request.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_route_leg,
    api_client,
    book_set_job,
    create_escort_assignment_payload,
    inspect_site,
    make_transport_manager_headers,
    measure_and_release_section,
    open_order,
    read_escort_crew,
    read_permit,
    read_set_crew,
    read_set_job,
    read_site,
    record_section,
    register_escort_crew,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    request_permit,
    reserve_escort,
    set_logical_clock,
    validate_error,
)

ADMIN = TEST_USERS["network_admin_headers"]


def _scheduled_job_with_failed_site_and_lapsed_crew():
    """A job whose site failed its pad inspection and whose crew's licence lapsed."""
    set_logical_clock()
    plant = register_plant(name="Champion Chandler", state_code="AZ")
    set_crew = register_set_crew(
        company_name="Lapsed Set Co",
        license_state="AZ",
        license_expiry_date="2026-07-01",
        daily_capacity=1,
    )
    order = open_order(
        plant["id"],
        home_model="Titan 2860",
        section_count=1,
        destination_state="AZ",
        wind_zone="I",
    )
    site = register_site(
        order["id"], pad_type="RUNNER", pier_plan_ref="PP-2860-A", pier_count=6
    )
    inspect_site(site["id"], pad_pass=False, pier_plan_pass=True, utility_pass=True)
    set_job = book_set_job(order["id"], set_crew["id"], labor_base_cents=480000)
    return {
        "plant": plant,
        "set_crew": set_crew,
        "order": order,
        "site": read_site(site["id"]),
        "set_job": set_job,
    }


def _attempt_dispatch(job_id):
    return api_client.dispatch_set_job(job_id, {}, ADMIN)


def test_dispatch_reports_the_site_fault_ahead_of_the_lapsed_installer_licence():
    """PRD §2.10: "**Priority 8** — the order's site has readiness `READY`. Applies
    to `POST /installations/set-jobs/{id}/dispatch`. Violation: `ERR_SITE_NOT_READY`
    (409). This rule is deliberately ranked above the installer-licence check at
    priority 11, so a dispatch that is simultaneously site-blocked and
    crew-unlicensed reports `ERR_SITE_NOT_READY`."
    PRD §3.6: "Because the site check outranks the licence check, a dispatch that is
    both site-blocked and crew-unlicensed reports `ERR_SITE_NOT_READY`."

    Design: Difficulty/priority_pair_validation_conflict/site_not_ready_outranks_installer_license_invalid
    """
    scenario = _scheduled_job_with_failed_site_and_lapsed_crew()
    assert scenario["site"]["readiness_status"] == "READINESS_FAILED", (
        "the failed pad verdict must leave the site READINESS_FAILED, got "
        f"{scenario['site']['readiness_status']}"
    )
    lapsed_crew = read_set_crew(scenario["set_crew"]["id"])
    assert lapsed_crew["status"] == "LICENSE_EXPIRED", (
        "a licence expiring 2026-07-01 has lapsed against the 2026-08-01 logical "
        f"clock, so the crew reads LICENSE_EXPIRED, got {lapsed_crew['status']}"
    )

    refused = _attempt_dispatch(scenario["set_job"]["id"])

    error = validate_error(refused, ApiErrorId.ERR_SITE_NOT_READY.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INSTALLER_LICENSE_INVALID.value, (
        "the priority-11 licence error must not pre-empt the priority-8 site error, "
        f"got {error['error_id']}"
    )

    unchanged = read_set_job(scenario["set_job"]["id"])
    assert unchanged["progress_status"] == "SCHEDULED", (
        f"a refused dispatch leaves the progress dimension SCHEDULED, got {unchanged['progress_status']}"
    )


def test_curing_the_site_exposes_the_installer_licence_refusal_underneath():
    """PRD §3.3: "From `READINESS_FAILED` a clean evaluation moves the site
    `READINESS_FAILED → READY`, writing `blocking_defect_count` as 0, incrementing
    `inspection_round` by 1, stamping `last_inspector_user_id`, and re-deriving the
    order's posture."
    PRD §2.10: "**Priority 11** — the assigned set crew's `status` is `ACTIVE` and
    its `license_expiry_date` falls on or after the logical current date. Applies to
    `POST /installations/set-jobs/{id}/dispatch` and `POST
    /installations/anchor-certifications`. Violation:
    `ERR_INSTALLER_LICENSE_INVALID` (422)."

    Design: Difficulty/priority_pair_validation_conflict/site_not_ready_outranks_installer_license_invalid
    """
    scenario = _scheduled_job_with_failed_site_and_lapsed_crew()
    validate_error(
        _attempt_dispatch(scenario["set_job"]["id"]),
        ApiErrorId.ERR_SITE_NOT_READY.value,
        409,
    )

    inspect_site(
        scenario["site"]["id"], pad_pass=True, pier_plan_pass=True, utility_pass=True
    )

    cured_site = read_site(scenario["site"]["id"])
    assert cured_site["readiness_status"] == "READY", (
        f"a clean re-inspection moves the site to READY, got {cured_site['readiness_status']}"
    )
    assert cured_site["blocking_defect_count"] == 0, (
        f"a clean re-inspection writes blocking_defect_count 0, got {cured_site['blocking_defect_count']}"
    )
    assert cured_site["inspection_round"] == 2, (
        "the second inspection increments inspection_round to 2, got "
        f"{cured_site['inspection_round']}"
    )

    refused = _attempt_dispatch(scenario["set_job"]["id"])

    validate_error(refused, ApiErrorId.ERR_INSTALLER_LICENSE_INVALID.value, 422)

    unchanged = read_set_job(scenario["set_job"]["id"])
    assert unchanged["progress_status"] == "SCHEDULED", (
        "the licence refusal also leaves the progress dimension SCHEDULED, got "
        f"{unchanged['progress_status']}"
    )


STANDARD_LEG_WINDOW = ("2026-08-05T06:00:00.000Z", "2026-08-05T14:00:00.000Z")
OVERSIZE_LEG_WINDOW = ("2026-08-05T10:00:00.000Z", "2026-08-05T18:00:00.000Z")


def _two_permit_classes_with_both_crews_already_booked():
    """A STANDARD leg carrying both crews, plus an OVERSIZE leg overlapping it."""
    set_logical_clock()
    plant = register_plant(name="Champion Athens", state_code="TX")
    hauler = register_hauler(
        name="Lone Star Toters",
        insurance_expiry_date="2027-03-31",
        endorsed_states=["TX"],
    )
    standard_crew = register_escort_crew(
        vendor_name="Standard Only Escort",
        endorsed_states=["TX"],
        certified_roles=["ESCORT"],
        endorsement_class="STANDARD",
        buffer_minutes=45,
        max_reserved_minutes=1200,
    )
    superload_crew = register_escort_crew(
        vendor_name="Superload Escort",
        endorsed_states=["TX"],
        certified_roles=["ESCORT"],
        endorsement_class="SUPERLOAD",
        buffer_minutes=45,
        max_reserved_minutes=1200,
    )
    order = open_order(
        plant["id"],
        dealer_name="Hill Country Homes",
        home_model="Titan 3266",
        section_count=2,
        destination_state="TX",
        wind_zone="II",
    )
    section_a = record_section(
        order["id"],
        plant["id"],
        section_index=1,
        declared_width_in=168,
        declared_height_in=150,
        declared_length_in=768,
        declared_weight_lb=24000,
    )
    section_b = record_section(
        order["id"],
        plant["id"],
        section_index=2,
        declared_width_in=200,
        declared_height_in=150,
        declared_length_in=768,
        declared_weight_lb=26500,
        mates_to_section_id=section_a["id"],
    )
    measure_and_release_section(section_a["id"], plant["id"])
    permit_a = request_permit(section_a["id"], state_code="TX", planned_leg_count=1)
    standard_leg = add_route_leg(
        permit_a["id"],
        hauler["id"],
        sequence_no=1,
        corridor_id="TX-US79",
        state_code="TX",
        window_start=STANDARD_LEG_WINDOW[0],
        window_end=STANDARD_LEG_WINDOW[1],
    )
    measure_and_release_section(section_b["id"], plant["id"])
    permit_b = request_permit(section_b["id"], state_code="TX", planned_leg_count=1)
    oversize_leg = add_route_leg(
        permit_b["id"],
        hauler["id"],
        sequence_no=1,
        corridor_id="TX-US290",
        state_code="TX",
        window_start=OVERSIZE_LEG_WINDOW[0],
        window_end=OVERSIZE_LEG_WINDOW[1],
    )
    for crew in (standard_crew, superload_crew):
        reserve_escort(
            standard_leg["id"],
            crew["id"],
            hauler["id"],
            role="ESCORT",
            window_start=STANDARD_LEG_WINDOW[0],
            window_end=STANDARD_LEG_WINDOW[1],
        )
    return {
        "plant": plant,
        "hauler": hauler,
        "standard_crew": standard_crew,
        "superload_crew": superload_crew,
        "order": order,
        "permit_a": read_permit(permit_a["id"]),
        "permit_b": read_permit(permit_b["id"]),
        "standard_leg": standard_leg,
        "oversize_leg": oversize_leg,
    }


def _attempt_reservation_on_the_oversize_leg(scenario, crew):
    return api_client.create_escort_assignment(
        create_escort_assignment_payload(
            scenario["oversize_leg"]["id"],
            crew["id"],
            role="ESCORT",
            window_start=OVERSIZE_LEG_WINDOW[0],
            window_end=OVERSIZE_LEG_WINDOW[1],
        ),
        make_transport_manager_headers(scenario["hauler"]["id"]),
    )


def test_unendorsed_escort_crew_with_a_clashing_window_reports_the_endorsement_error():
    """PRD §2.10: "**Priority 12** — the escort crew carries an endorsement covering
    the permit class of the leg it is being reserved for. Applies to `POST
    /installations/escort-assignments`. Violation: `ERR_ESCORT_ENDORSEMENT_MISSING`
    (422). This safety qualification is deliberately ranked above the window-conflict
    test at priority 22, so an unendorsed crew with a clashing window reports the
    endorsement error."
    PRD §3.5: "Only then is the window tested for conflict, so an unendorsed crew
    whose window also clashes reports the endorsement error rather than the conflict."

    Design: Difficulty/priority_pair_validation_conflict/escort_endorsement_outranks_escort_window_conflict
    """
    scenario = _two_permit_classes_with_both_crews_already_booked()
    assert scenario["permit_a"]["permit_class"] == "STANDARD", (
        "a 168-inch floor is classed STANDARD, got "
        f"{scenario['permit_a']['permit_class']}"
    )
    assert scenario["permit_b"]["permit_class"] == "OVERSIZE", (
        "a 200-inch floor is classed OVERSIZE, got "
        f"{scenario['permit_b']['permit_class']}"
    )

    refused = _attempt_reservation_on_the_oversize_leg(
        scenario, scenario["standard_crew"]
    )

    error = validate_error(
        refused, ApiErrorId.ERR_ESCORT_ENDORSEMENT_MISSING.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_ESCORT_WINDOW_CONFLICT.value, (
        "the priority-22 window conflict must not pre-empt the priority-12 "
        f"endorsement rule, got {error['error_id']}"
    )

    crew = read_escort_crew(scenario["standard_crew"]["id"])
    assert crew["reserved_minutes"] == 480, (
        "only the accepted eight-hour reservation counts toward the crew's minutes, "
        f"expected 480, got {crew['reserved_minutes']}"
    )


def test_endorsed_escort_crew_with_the_same_window_reports_the_window_conflict():
    """PRD §2.10: "**Priority 22** — the requested escort window does not conflict
    with any reserved window of the same escort crew once both intervals are inflated
    by that crew's `buffer_minutes`. Applies to `POST
    /installations/escort-assignments`. Violation: `ERR_ESCORT_WINDOW_CONFLICT`
    (409)."
    PRD §3.5: "A conflict exists when some other reservation of the same crew, in
    `RESERVED` status, satisfies both of two strict comparisons: the candidate's
    opening instant falls before that reservation's closing instant advanced by the
    buffer, and that reservation's opening instant falls before the candidate's
    closing instant advanced by the buffer."
    PRD §3.5: "The crew's `endorsement_class` must cover the permit class of the
    leg's permit: a `SUPERLOAD` permit demands a crew endorsed `SUPERLOAD`; an
    `OVERSIZE` permit accepts `SUPERLOAD` or `OVERSIZE`; a `STANDARD` permit accepts
    any endorsement class."

    Design: Difficulty/priority_pair_validation_conflict/escort_endorsement_outranks_escort_window_conflict
    """
    scenario = _two_permit_classes_with_both_crews_already_booked()
    assert scenario["permit_b"]["permit_class"] == "OVERSIZE", (
        "the second floor's permit must be OVERSIZE for the endorsement rule to "
        f"pass for a SUPERLOAD crew, got {scenario['permit_b']['permit_class']}"
    )

    refused = _attempt_reservation_on_the_oversize_leg(
        scenario, scenario["superload_crew"]
    )

    validate_error(refused, ApiErrorId.ERR_ESCORT_WINDOW_CONFLICT.value, 409)

    crew = read_escort_crew(scenario["superload_crew"]["id"])
    assert crew["reserved_minutes"] == 480, (
        "the refused reservation adds nothing, so the crew still carries only its "
        f"eight-hour booking, expected 480, got {crew['reserved_minutes']}"
    )
    assert crew["status"] == "AVAILABLE", (
        "480 minutes is below the crew's 1200-minute ceiling, so it stays AVAILABLE, "
        f"got {crew['status']}"
    )
