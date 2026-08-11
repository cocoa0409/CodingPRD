"""Home registration, licensing, closure, and derived census counter tests."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_home, create_home_payload,
    create_pending_admission_scenario, create_licensed_home, create_home, add_bed,
    add_caregiver, set_clock, fresh_home,
    create_approved_admission_scenario, complete_admission,
    discharge_resident_now, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestHomeCreationDefaults:
    def test_home_create_defaults_applied(self, api):
        """PRD §2.6: "Each home declares an IANA `timezone` — defaulting to
        `America/Los_Angeles` when omitted — that defines its local day boundary."
        PRD §3.1: "A new home begins `PROVISIONAL`."
        PRD §2.11: "`current_census` counts the home's residents in `ADMITTED` status
        and is recomputed on every admission completion and every discharge.
        `open_case_count` counts the home's compliance cases in `OPEN` or
        `SUBSTANTIATED` status and is recomputed on every compliance-case status change."

        Design: Corner/entities/home_create_defaults_applied
        """
        res = api.create_home(
            create_home_payload(name="Corner Maple", licensed_bed_capacity=4),
            PROVIDER)
        home = validate_success(res, 201)
        assert_home(home)
        assert home["timezone"] == "America/Los_Angeles", \
            f"default timezone not applied: {home.get('timezone')}"
        assert home["status"] == "PROVISIONAL"
        assert home["version"] == 1
        assert home["open_case_count"] == 0
        assert home["current_census"] == 0


class TestHomeCapacityBounds:
    def test_capacity_above_six_rejected(self, api):
        """PRD §3.1: "A `Provider` registers a home with its state-issued
        `license_number` (unique across all homes), an operating `name`, the
        `licensed_bed_capacity` the state license permits — between 2 and 6 beds
        inclusive — and an optional `timezone`."
        PRD §2.9: "Structural payload validity — a missing required field, a wrong
        type, an enum outside its declared set, or an inverted range such as a
        `period_end` not after its `period_start` or an `end_at` not after its
        `start_at`; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/home_bed_capacity_bounds_enforced
        """
        res = api.create_home(
            create_home_payload(name="Too Big", licensed_bed_capacity=7),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_capacity_below_two_rejected(self, api):
        """PRD §3.1: "A `Provider` registers a home with its state-issued
        `license_number` (unique across all homes), an operating `name`, the
        `licensed_bed_capacity` the state license permits — between 2 and 6 beds
        inclusive — and an optional `timezone`."
        PRD §2.9: "Structural payload validity — a missing required field, a wrong
        type, an enum outside its declared set, or an inverted range such as a
        `period_end` not after its `period_start` or an `end_at` not after its
        `start_at`; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/home_bed_capacity_bounds_enforced
        """
        res = api.create_home(
            create_home_payload(name="Too Small", licensed_bed_capacity=1),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestLicensingPreconditions:
    def test_license_without_bed_or_caregiver_rejected(self, api):
        """PRD §3.1: "Licensing — the `PROVISIONAL` → `LICENSED` transition performed
        by a `Provider` — requires the home to have at least one bed that is not
        `OUT_OF_SERVICE` and at least one `ACTIVE` caregiver, and it bumps the home's
        `version`."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/home_license_requires_bed_and_active_caregiver
        """
        home = create_home(name="Pre Lic", licensed_bed_capacity=4)
        res = api.license_home(home["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_license_succeeds_with_bed_and_active_caregiver(self, api):
        """PRD §3.1: "Licensing — the `PROVISIONAL` → `LICENSED` transition performed
        by a `Provider` — requires the home to have at least one bed that is not
        `OUT_OF_SERVICE` and at least one `ACTIVE` caregiver, and it bumps the home's
        `version`."

        Design: Corner/state_machines/home_license_requires_bed_and_active_caregiver
        """
        home = create_home(name="Pre Lic", licensed_bed_capacity=4)
        add_bed(home["id"], label="1A")
        add_caregiver(home["id"], full_name="Cg Lic")
        licensed = validate_success(api.license_home(home["id"], PROVIDER), 200)
        assert licensed["status"] == "LICENSED"


class TestHomeClosure:
    def test_closed_home_rejects_suspend(self, api):
        """PRD §3.1: "Closure is terminal (`CLOSED`), is reachable from either
        `LICENSED` or `SUSPENDED`, and requires a `current_census` of zero — no
        `ADMITTED` residents remain."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/home_terminal_closed_lockdown
        """
        ctx = create_licensed_home(name="Close Lock", bed_label="1A")
        home = ctx["home"]
        closed = validate_success(api.close_home(home["id"], PROVIDER), 200)
        assert closed["status"] == "CLOSED"
        res = api.suspend_home(home["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_closed_home_cascades_bed_out_of_service(self, api):
        """PRD §3.1: "Closing a home cascades in the same step: every bed not already
        `OUT_OF_SERVICE` goes `OUT_OF_SERVICE`; where such a bed was `HELD`, its
        linked `PENDING` admission is forced to `REJECTED` with the system recorded
        as the decider, and the admission's usual bed-release compensation is
        suppressed because the bed is leaving service rather than returning to
        availability — a depth-three chain from home to bed to admission."

        Design: Corner/state_machines/home_terminal_closed_lockdown
        """
        ctx = create_licensed_home(name="Close Lock", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        validate_success(api.close_home(home["id"], PROVIDER), 200)
        bed_after = validate_success(api.get_bed(bed["id"], PROVIDER), 200)
        assert bed_after["status"] == "OUT_OF_SERVICE"

    def test_close_blocked_with_census(self, api):
        """PRD §3.1: "Closure is terminal (`CLOSED`), is reachable from either
        `LICENSED` or `SUSPENDED`, and requires a `current_census` of zero — no
        `ADMITTED` residents remain."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/home_close_blocked_with_census
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Close Block", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_approved_admission_scenario(home["id"], bed["id"])
        complete_admission(adm["admission"]["id"])
        res = api.close_home(home["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        home_after = validate_success(api.get_home(home["id"], PROVIDER), 200)
        assert home_after["status"] == "LICENSED", \
            "home must stay LICENSED when closure is rejected"
        assert home_after["current_census"] == 1


class TestHomeCloseDepth3Cascade:
    def test_close_closes_home_and_puts_held_bed_out_of_service(self, api):
        """PRD §3.1: "Closing a home cascades in the same step: every bed not already
        `OUT_OF_SERVICE` goes `OUT_OF_SERVICE`; where such a bed was `HELD`, its
        linked `PENDING` admission is forced to `REJECTED` with the system recorded
        as the decider, and the admission's usual bed-release compensation is
        suppressed because the bed is leaving service rather than returning to
        availability — a depth-three chain from home to bed to admission."

        Design: Difficulty/transitive_cascade/home_close_cascades_bed_then_admission
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Oak AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        create_pending_admission_scenario(home["id"], bed["id"])
        validate_success(api.close_home(home["id"], PROVIDER), 200)
        home_after = validate_success(api.get_home(home["id"], PROVIDER), 200)
        assert home_after["status"] == "CLOSED"
        bed_after = validate_success(api.get_bed(bed["id"], PROVIDER), 200)
        assert bed_after["status"] == "OUT_OF_SERVICE", (
            "held bed must go OUT_OF_SERVICE on closure (release-to-AVAILABLE "
            "compensation suppressed)")

    def test_close_forces_pending_admission_rejected_resident_untouched(self, api):
        """PRD §3.1: "Closing a home cascades in the same step: every bed not already
        `OUT_OF_SERVICE` goes `OUT_OF_SERVICE`; where such a bed was `HELD`, its
        linked `PENDING` admission is forced to `REJECTED` with the system recorded
        as the decider, and the admission's usual bed-release compensation is
        suppressed because the bed is leaving service rather than returning to
        availability — a depth-three chain from home to bed to admission."

        Design: Difficulty/transitive_cascade/home_close_cascades_bed_then_admission
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Oak AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        resident_id = adm["resident"]["id"]
        validate_success(api.close_home(home["id"], PROVIDER), 200)
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "REJECTED", (
            "pending admission linked to the held bed must be forced to REJECTED "
            "by the closure cascade")
        resident_after = validate_success(api.get_resident(resident_id, PROVIDER), 200)
        assert resident_after["status"] == "APPLICANT", \
            "resident machine is untouched by the home closure cascade"


class TestCurrentCensusTracking:
    def test_census_zero_until_admission_completion(self, api):
        """PRD §2.11: "`current_census` counts the home's residents in `ADMITTED`
        status and is recomputed on every admission completion and every discharge."

        Design: Corner/cross_cutting_layers/home_current_census_tracks_admission_and_discharge
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Census", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        create_approved_admission_scenario(home["id"], bed["id"])
        home_before = fresh_home(home["id"])
        assert home_before["current_census"] == 0, \
            "an APPROVED admission does not count toward census"

    def test_census_recomputed_on_completion_and_discharge(self, api):
        """PRD §2.11: "`current_census` counts the home's residents in `ADMITTED`
        status and is recomputed on every admission completion and every discharge."

        Design: Corner/cross_cutting_layers/home_current_census_tracks_admission_and_discharge
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Census", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_approved_admission_scenario(home["id"], bed["id"])
        complete_admission(adm["admission"]["id"])
        home_mid = fresh_home(home["id"])
        assert home_mid["current_census"] == 1, "completion must raise census to 1"
        discharge_resident_now(adm["resident"]["id"], reason="VOLUNTARY",
                               notice_days=30, clock="2026-06-05T09:00:00Z")
        home_after = fresh_home(home["id"])
        assert home_after["current_census"] == 0, "discharge must return census to 0"
