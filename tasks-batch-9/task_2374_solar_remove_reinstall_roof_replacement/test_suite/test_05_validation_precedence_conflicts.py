"""Validation precedence: requests that violate two rules at once must answer with
the higher-priority error id.
"""

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    ApiErrorId,
    add_bin,
    add_finding,
    api_client,
    book_inspection,
    create_core_parties,
    create_jurisdiction,
    create_party,
    create_permit,
    create_project,
    get_success_data,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    refresh_project,
    remove_unit,
    set_clock,
    setup_deenergized_project,
    store_unit,
    submit_permit,
    validate_error,
)

MISSING_PROJECT_ID = "00000000-0000-0000-0000-0000000000ff"


# --------------------------------------------------------------------------
# Composite setups
# --------------------------------------------------------------------------
def _setup_frozen_project_with_full_bin_and_one_removed_unit() -> dict:
    """A FROZEN project whose only bin is already at capacity, with u2 still REMOVED.

    Both panels are removed while the posture is still OPEN and u1 is stored, taking
    BIN-A to `occupied_slots` 1 of 1. A CRITICAL finding is then recorded, so the
    project is FROZEN at the moment u2's storage is attempted.
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_deenergized_project(
        ownership_model="HOST_OWNED", circuit_count=1, unit_count=2
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    storage_bin = add_bin(
        project_id, bin_label="BIN-A", capacity_slots=1, climate_controlled=True
    )
    unit_one, unit_two = ctx["units"][0], ctx["units"][1]

    remove_unit(unit_one["id"], crew_id)
    remove_unit(unit_two["id"], crew_id)
    store_unit(unit_one["id"], storage_bin["id"], crew_id)

    finding = add_finding(
        project_id,
        ctx["parties"]["roofer"]["id"],
        finding_type="MOISTURE_INTRUSION",
        severity="CRITICAL",
        affected_area_sqft=60,
        attachment_count_affected=4,
    )

    ctx["bin"] = storage_bin
    ctx["unit_one"] = unit_one
    ctx["unit_two"] = unit_two
    ctx["finding"] = finding
    ctx["project"] = refresh_project(project_id)
    return ctx


def _setup_exhausted_slot_with_draft_permit_on_a_second_project() -> dict:
    """One jurisdiction slot per day, already consumed on 2026-08-06 by another project.

    The target application belongs to a second project and is still DRAFT, so the
    booking attempt violates the permit-state rule and the day-capacity rule at once.
    """
    set_clock(CLOCK_EPOCH)
    jurisdiction = create_jurisdiction(
        name="Narrowgap AHJ",
        code="NARROWGAP",
        repermit_required_for_reinstall=False,
        reinspection_required=True,
        inspection_slots_per_day=1,
        backlog_days=3,
        permit_review_days=7,
    )
    parties = create_core_parties()
    project_one = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    project_two = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="912 Saguaro Rd, Mesa AZ",
        system_dc_kw=5.2,
        baseline_daily_kwh=26.0,
        downtime_days_estimated=3,
        upgrade_budget_cents=1_500_000,
    )
    permit_one = create_permit(
        project_one["id"], jurisdiction["id"], scope="REINSTALL_ONLY"
    )
    submit_permit(permit_one["id"])
    inspection_one = book_inspection(
        permit_one["id"],
        inspection_type="ROOF_DECK",
        slot_date="2026-08-06",
        window_start_utc="2026-08-06T15:00:00Z",
        window_end_utc="2026-08-06T17:00:00Z",
    )
    permit_two = create_permit(
        project_two["id"], jurisdiction["id"], scope="REINSTALL_ONLY"
    )
    return {
        "jurisdiction": jurisdiction,
        "permit_one": permit_one,
        "permit_two": permit_two,
        "inspection_one": inspection_one,
    }


def _read_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_hardware_unit(unit_id, COORD))


def _read_bin(bin_id: str) -> dict:
    return get_success_data(api_client.get_storage_bin(bin_id, COORD))


def _read_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit_application(permit_id, COORD))


def _read_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, COORD))


# --------------------------------------------------------------------------
# Frozen posture (10) vs bin capacity (29)
# --------------------------------------------------------------------------
class TestFrozenPostureOutranksBinCapacity:
    def test_storage_on_a_frozen_project_with_a_full_bin_answers_posture_frozen(self):
        """Both the frozen bar and bin capacity are violated; the frozen bar wins.

        "When several rules could reject the same request, they are evaluated in a fixed order so that the returned `error_id` is deterministic."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_priority_10_outranks_bin_capacity_priority_29_on_storage
        """
        ctx = _setup_frozen_project_with_full_bin_and_one_removed_unit()

        assert ctx["project"]["posture"] == "FROZEN", (
            f"the OPEN CRITICAL finding must freeze the project, "
            f"got {ctx['project']['posture']}"
        )
        assert _read_bin(ctx["bin"]["id"])["occupied_slots"] == 1, (
            "BIN-A must be at its single-slot capacity before the trigger"
        )

        response = api_client.store_hardware_unit(
            ctx["unit_two"]["id"],
            {"storage_bin_id": ctx["bin"]["id"]},
            make_solar_contractor_headers(ctx["parties"]["crew"]["id"]),
        )

        error = validate_error(response, ApiErrorId.ERR_PROJECT_POSTURE_FROZEN)
        assert error["error_id"] != ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED.value, (
            "the frozen-posture bar is checked before bin capacity"
        )

    def test_refused_storage_leaves_the_unit_removed_and_the_bin_occupancy_untouched(self):
        """The rejected request writes nothing on either the unit or the bin.

        "Operations that merely require the project not to be frozen — de-energizing or re-energizing a circuit, removing a unit, storing a unit, reinstalling a unit, scheduling a crew window, and starting a crew window — are refused with `ERR_PROJECT_POSTURE_FROZEN` (HTTP 409) while the posture is `FROZEN`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_priority_10_outranks_bin_capacity_priority_29_on_storage
        """
        ctx = _setup_frozen_project_with_full_bin_and_one_removed_unit()

        response = api_client.store_hardware_unit(
            ctx["unit_two"]["id"],
            {"storage_bin_id": ctx["bin"]["id"]},
            make_solar_contractor_headers(ctx["parties"]["crew"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_POSTURE_FROZEN)

        unit_two = _read_unit(ctx["unit_two"]["id"])
        assert unit_two["handling_status"] == "REMOVED", (
            f"the refused unit stays REMOVED, got {unit_two['handling_status']}"
        )
        assert unit_two["storage_bin_id"] is None, (
            f"the refused unit keeps no storage_bin_id, got {unit_two['storage_bin_id']}"
        )

        bin_after = _read_bin(ctx["bin"]["id"])
        assert bin_after["occupied_slots"] == 1, (
            f"BIN-A still holds only u1, got occupied_slots {bin_after['occupied_slots']}"
        )

        project = refresh_project(ctx["project"]["id"])
        assert project["posture"] == "FROZEN", (
            f"the project remains FROZEN, got {project['posture']}"
        )


# --------------------------------------------------------------------------
# Permit state (8) vs aggregate inspection slot capacity (23)
# --------------------------------------------------------------------------
class TestPermitStateOutranksSlotCapacity:
    def test_booking_on_a_draft_permit_and_a_full_day_answers_permit_not_submitted(self):
        """The parent application's state is checked before the jurisdiction's capacity.

        "The parent application's `status` must be `SUBMITTED` or `APPROVED`; anything else is `ERR_PERMIT_NOT_SUBMITTED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_submitted_state_priority_8_outranks_slot_full_priority_23
        """
        ctx = _setup_exhausted_slot_with_draft_permit_on_a_second_project()

        response = api_client.create_inspection(
            ctx["permit_two"]["id"],
            {
                "inspection_type": "ROOF_DECK",
                "slot_date": "2026-08-06",
                "window_start_utc": "2026-08-06T18:00:00Z",
                "window_end_utc": "2026-08-06T20:00:00Z",
            },
            COORD,
        )

        error = validate_error(response, ApiErrorId.ERR_PERMIT_NOT_SUBMITTED)
        assert error["error_id"] != ApiErrorId.ERR_INSPECTION_SLOT_FULL.value, (
            "state legality is checked before aggregate day capacity"
        )

    def test_refused_booking_leaves_the_draft_permit_and_the_existing_inspection_intact(self):
        """Neither the DRAFT application nor the slot-holding inspection is disturbed.

        "When several rules could reject the same request, they are evaluated in a fixed order so that the returned `error_id` is deterministic."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_submitted_state_priority_8_outranks_slot_full_priority_23
        """
        ctx = _setup_exhausted_slot_with_draft_permit_on_a_second_project()

        response = api_client.create_inspection(
            ctx["permit_two"]["id"],
            {
                "inspection_type": "ROOF_DECK",
                "slot_date": "2026-08-06",
                "window_start_utc": "2026-08-06T18:00:00Z",
                "window_end_utc": "2026-08-06T20:00:00Z",
            },
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_PERMIT_NOT_SUBMITTED)

        permit_two = _read_permit(ctx["permit_two"]["id"])
        assert permit_two["status"] == "DRAFT", (
            f"the target application is still DRAFT, got {permit_two['status']}"
        )

        inspection_one = _read_inspection(ctx["inspection_one"]["id"])
        assert inspection_one["status"] == "SCHEDULED", (
            f"the slot-holding inspection is untouched, got {inspection_one['status']}"
        )


# --------------------------------------------------------------------------
# Role authorization (2) vs path existence (3)
# --------------------------------------------------------------------------
class TestRoleCheckOutranksPathExistence:
    def test_solar_owner_opening_a_consent_on_a_missing_project_answers_role_not_permitted(self):
        """The role check fires before the path id is resolved.

        "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/role_check_priority_2_outranks_path_existence_priority_3_and_project_not_found_is_masked
        """
        set_clock(CLOCK_EPOCH)
        owner = create_party(
            "SOLAR_OWNER",
            name="Alvarez Household",
            contact_email="owner2@example.com",
        )

        response = api_client.create_party_approval(
            MISSING_PROJECT_ID,
            {"party_id": owner["id"]},
            make_solar_owner_headers(owner["id"]),
        )

        error = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        assert error["error_id"] != ApiErrorId.ERR_PROJECT_NOT_FOUND.value, (
            "a caller who is not allowed on the endpoint must not learn whether the "
            "project id exists"
        )

    def test_the_masked_404_is_returned_to_the_role_that_is_allowed_on_the_endpoint(self):
        """The same missing id yields the 404 only once the role check passes.

        "Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the 404 that comes back: `ERR_PROJECT_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND` or `ERR_SOURCING_ORDER_NOT_FOUND`."

        Design: Difficulty/priority_pair_validation_conflict/role_check_priority_2_outranks_path_existence_priority_3_and_project_not_found_is_masked
        """
        set_clock(CLOCK_EPOCH)
        owner = create_party(
            "SOLAR_OWNER",
            name="Alvarez Household",
            contact_email="owner2@example.com",
        )

        coordinator_response = api_client.create_party_approval(
            MISSING_PROJECT_ID, {"party_id": owner["id"]}, COORD
        )
        validate_error(coordinator_response, ApiErrorId.ERR_PROJECT_NOT_FOUND)

        solar_owner_response = api_client.create_party_approval(
            MISSING_PROJECT_ID,
            {"party_id": owner["id"]},
            make_solar_owner_headers(owner["id"]),
        )
        validate_error(solar_owner_response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
