"""Registration lifecycle: the two independent state dimensions, waiver gates,
capacity gates, ownership rules, listing/pagination, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_signed_registration,
    begin_ready_event,
    cancel_registration,
    confirm_registration,
    create_event,
    create_partner,
    create_project,
    create_volunteer,
    get_event,
    get_project,
    get_registration,
    make_employee_volunteer_headers,
    make_staff_lead_headers,
    match_project,
    MINOR_DOB,
    open_event_registration,
    register_volunteer,
    setup_in_progress_event,
    setup_matched_scenario,
    setup_ready_event,
    sign_waiver_self,
    validate_error,
    validate_paginated,
    validate_success,
    verify_waiver,
    vet_project,
)

TEST_CEM = TEST_USERS["cem_headers"]


class TestIndependentDimensions:
    def test_sign_and_confirm_move_one_dimension_at_a_time(self, api):
        """PRD §3.4: "A registration lives on two independent state dimensions. The RSVP dimension runs `REGISTERED` → `CONFIRMED` → `CHECKED_IN`, with `CANCELLED` and `NO_SHOW` as terminal outcomes. The waiver dimension runs `WAIVER_PENDING` → `WAIVER_SIGNED` → `WAIVER_VERIFIED`, with `WAIVER_VOIDED` as the reset state. One dimension never substitutes for the other — confirm and check-in each look at both."

        Design: Difficulty/non_linear_state_machine/registration_independent_rsvp_waiver_dimensions
        """
        sc = setup_matched_scenario(event_name="Day E", max_volunteers=5)
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = register_volunteer(
            vol, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )
        assert reg["rsvp_status"] == "REGISTERED"
        assert reg["waiver_status"] == "WAIVER_PENDING"

        signed = sign_waiver_self(reg["id"], vol, media_consent=True)
        assert signed["rsvp_status"] == "REGISTERED", "signing must not move the RSVP dimension"
        assert signed["waiver_status"] == "WAIVER_SIGNED"

        confirmed = confirm_registration(reg["id"])
        assert confirmed["rsvp_status"] == "CONFIRMED"
        assert confirmed["waiver_status"] == "WAIVER_SIGNED", "confirm must not move the waiver dimension"

    def test_verify_and_cancel_leave_the_other_dimension_untouched(self, api):
        """PRD §3.4: "One dimension never substitutes for the other — confirm and check-in each look at both."
        PRD §3.4: "A registration can be cancelled from `REGISTERED` or `CONFIRMED` — other states are `ERR_INVALID_REGISTRATION_TRANSITION` — by a manager, or by the volunteer themselves, in which case the caller's `X-User-ID` must equal the registration's `volunteer_id` (`ERR_FORBIDDEN_ROLE` otherwise)."

        Design: Difficulty/non_linear_state_machine/registration_independent_rsvp_waiver_dimensions
        """
        sc = setup_matched_scenario(event_name="Day E2", max_volunteers=5)
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = register_volunteer(
            vol, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )
        sign_waiver_self(reg["id"], vol, media_consent=True)
        confirm_registration(reg["id"])

        verified = verify_waiver(reg["id"])
        assert verified["rsvp_status"] == "CONFIRMED", "verify must not move the RSVP dimension"
        assert verified["waiver_status"] == "WAIVER_VERIFIED"

        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_employee_volunteer_headers(vol["id"])),
            200,
        )
        assert cancelled["rsvp_status"] == "CANCELLED"
        assert cancelled["waiver_status"] == "WAIVER_VERIFIED", (
            "cancelling the RSVP dimension leaves the waiver dimension untouched"
        )


class TestHeadcountConservation:
    def test_confirm_raises_counts(self, api):
        """PRD §3.4: "A successful confirm increments the project's `confirmed_volunteer_count` by one and recomputes `required_staff_leads` per the supervision rule; if the project was `LOCKED` and the new requirement now exceeds `active_staff_leads`, the project automatically demotes `LOCKED` → `MATCHED` and the event's posture is recomputed."
        PRD §3.3: "Otherwise it is the confirmed adult count divided by 8 and rounded up to a whole number, plus the confirmed minor count divided by 4 and rounded up to a whole number — so exactly 8 confirmed adults need 1 lead while 9 need 2, and exactly 4 confirmed minors need 1 dedicated lead while 5 need 2."

        Design: Difficulty/compensating_invariant/headcount_confirm_cancel_conservation
        """
        sc = setup_matched_scenario(event_name="Day R")
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=False
        )

        confirm_registration(reg["id"])
        project = get_project(sc["project"]["id"])
        event = get_event(sc["event"]["id"])
        assert project["confirmed_volunteer_count"] == 1
        assert project["required_staff_leads"] == 1  # ceil(1/8)
        assert event["confirmed_headcount"] == 1

    def test_confirm_then_cancel_restores_counts_exactly(self, api):
        """PRD §3.4: "When the cancelled registration had been `CONFIRMED`, the project's `confirmed_volunteer_count` decrements and `required_staff_leads` recomputes; if the project was `LOCKED` and the confirmed count has fallen below `min_volunteers`, the project demotes `LOCKED` → `MATCHED`, and the event's posture recomputes."

        Design: Difficulty/compensating_invariant/headcount_confirm_cancel_conservation
        """
        sc = setup_matched_scenario(event_name="Day R2")
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=False
        )
        confirm_registration(reg["id"])

        validate_success(
            api.cancel_registration(reg["id"], make_employee_volunteer_headers(vol["id"])),
            200,
        )
        project = get_project(sc["project"]["id"])
        event = get_event(sc["event"]["id"])
        assert project["confirmed_volunteer_count"] == 0
        assert project["required_staff_leads"] == 0
        assert event["confirmed_headcount"] == 0


class TestCheckInGates:
    def test_checkin_from_registered_rejected(self, api):
        """PRD §3.4: "With the event `IN_PROGRESS`, a confirmed volunteer is checked in by a manager or by a `StaffLead`; an event in any other status rejects the check-in with `ERR_EVENT_STATE_FORBIDS_WRITE`, and a registration not in `CONFIRMED` rejects with `ERR_INVALID_REGISTRATION_TRANSITION`."

        Design: Corner/state_machines/checkin_from_registered_rejected
        """
        # Isolate the RSVP from-state failure: the event IS in progress (one confirmed
        # volunteer made it READY); the second volunteer stays REGISTERED.
        sc = setup_ready_event(event_name="Day 5", budget_cents=500000)
        vol2 = create_volunteer("Vol Two", "v2@corp.com")
        reg2 = register_volunteer(
            vol2, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )
        sign_waiver_self(reg2["id"], vol2, media_consent=True)
        begin_ready_event(sc["event"]["id"])

        resp = api.check_in_registration(reg2["id"], TEST_CEM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_TRANSITION)
        assert get_registration(reg2["id"])["rsvp_status"] == "REGISTERED"

    def test_checkin_requires_verified_waiver_not_just_signed(self, api):
        """PRD §3.4: "The waiver must have reached `WAIVER_VERIFIED` — a merely signed waiver is not enough on the day — failing as `ERR_WAIVER_NOT_VERIFIED`."

        Design: Corner/validations/checkin_requires_verified_waiver_not_just_signed
        """
        # CONFIRMED (a SIGNED waiver passes confirm) but never verified
        sc = setup_ready_event(event_name="Day 34", budget_cents=500000, verify_waivers=False)
        begin_ready_event(sc["event"]["id"])
        reg = sc["registrations"][0]
        assert get_registration(reg["id"])["waiver_status"] == "WAIVER_SIGNED"

        resp = api.check_in_registration(reg["id"], TEST_CEM)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_VERIFIED)
        assert get_registration(reg["id"])["rsvp_status"] == "CONFIRMED"


class TestConfirmGates:
    def test_double_confirm_rejected_idempotency(self, api, cem_headers):
        """PRD §3.4: "Confirmation is a manager-only action with five preconditions, which the pipeline orders as state first, safety next, capacity last: the registration must be in `REGISTERED` (`ERR_INVALID_REGISTRATION_TRANSITION` otherwise), the event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` (`ERR_EVENT_STATE_FORBIDS_WRITE`), the project must be `MATCHED` or `LOCKED` (`ERR_INVALID_PROJECT_TRANSITION`), the waiver must be `WAIVER_SIGNED` or `WAIVER_VERIFIED` (`ERR_WAIVER_NOT_SIGNED`), and the project's `confirmed_volunteer_count` must be below its `max_volunteers` (`ERR_PROJECT_AT_CAPACITY`)."

        Design: Corner/state_machines/double_confirm_rejected_idempotency
        """
        sc = setup_matched_scenario(event_name="Day 6")
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=False, confirm=True
        )

        resp = api.confirm_registration(reg["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_TRANSITION)
        assert get_project(sc["project"]["id"])["confirmed_volunteer_count"] == 1

    def test_confirm_waiver_safety_precedes_capacity_constraint(self, api, cem_headers):
        """PRD §2.6: "The practical consequence: a confirm request that would fail both the waiver gate and the capacity gate surfaces `ERR_WAIVER_NOT_SIGNED`, because safety gates (step 7) precede capacity (step 11); an order approval that would breach the budget surfaces `ERR_BUDGET_WOULD_EXCEED` only after auth, existence, state, and every other check has passed, because the fiscal gate is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/confirm_waiver_safety_precedes_capacity_constraint
        """
        sc = setup_matched_scenario(event_name="Day J", min_volunteers=1, max_volunteers=1)
        vol_a = create_volunteer("Vol A", "va@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol_a, wants_meal=False, confirm=True
        )
        vol_b = create_volunteer("Vol B", "vb@corp.com")
        reg_b = register_volunteer(
            vol_b, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )  # waiver stays WAIVER_PENDING

        resp = api.confirm_registration(reg_b["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_SIGNED)

    def test_confirm_dual_failure_leaves_state_untouched(self, api, cem_headers):
        """PRD §2.6: "The practical consequence: a confirm request that would fail both the waiver gate and the capacity gate surfaces `ERR_WAIVER_NOT_SIGNED`, because safety gates (step 7) precede capacity (step 11); an order approval that would breach the budget surfaces `ERR_BUDGET_WOULD_EXCEED` only after auth, existence, state, and every other check has passed, because the fiscal gate is evaluated last."
        PRD §3.4: "the waiver must be `WAIVER_SIGNED` or `WAIVER_VERIFIED` (`ERR_WAIVER_NOT_SIGNED`), and the project's `confirmed_volunteer_count` must be below its `max_volunteers` (`ERR_PROJECT_AT_CAPACITY`)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_waiver_safety_precedes_capacity_constraint
        """
        sc = setup_matched_scenario(event_name="Day J2", min_volunteers=1, max_volunteers=1)
        vol_a = create_volunteer("Vol A", "va@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol_a, wants_meal=False, confirm=True
        )
        vol_b = create_volunteer("Vol B", "vb@corp.com")
        reg_b = register_volunteer(
            vol_b, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )

        api.confirm_registration(reg_b["id"], cem_headers)
        assert get_registration(reg_b["id"])["rsvp_status"] == "REGISTERED"
        assert get_project(sc["project"]["id"])["confirmed_volunteer_count"] == 1

    def test_project_capacity_reached_with_valid_waiver(self, api, cem_headers):
        """PRD §3.4: "the waiver must be `WAIVER_SIGNED` or `WAIVER_VERIFIED` (`ERR_WAIVER_NOT_SIGNED`), and the project's `confirmed_volunteer_count` must be below its `max_volunteers` (`ERR_PROJECT_AT_CAPACITY`)."

        Design: Corner/validations/project_capacity_reached_with_valid_waiver
        """
        sc = setup_matched_scenario(event_name="Day 24", min_volunteers=1, max_volunteers=1)
        vol_a = create_volunteer("Vol A", "va@corp.com")
        add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol_a, wants_meal=False, confirm=True
        )
        vol_b = create_volunteer("Vol B", "vb@corp.com")
        # The safety gate IS satisfied here (waiver signed) — only capacity can fail
        reg_b = add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol_b, wants_meal=False
        )

        resp = api.confirm_registration(reg_b["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_PROJECT_AT_CAPACITY)
        assert get_registration(reg_b["id"])["rsvp_status"] == "REGISTERED"


class TestRegistrationUniqueness:
    def test_duplicate_active_registration_rejected(self, api):
        """PRD §3.4: "One non-`CANCELLED` registration per volunteer per event is the uniqueness rule: a second live registration for the same pair is rejected with `ERR_DUPLICATE_REGISTRATION`."

        Design: Corner/validations/duplicate_active_registration_rejected
        """
        sc = setup_matched_scenario(event_name="Day 20")
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = register_volunteer(vol, sc["event"]["id"], sc["project"]["id"])

        dup = api.create_registration(
            {"event_id": sc["event"]["id"], "project_id": sc["project"]["id"]},
            make_employee_volunteer_headers(vol["id"]),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REGISTRATION)

        # After cancelling, the pair is free again (the rule covers non-CANCELLED only)
        cancel_registration(reg["id"], make_employee_volunteer_headers(vol["id"]))
        re_registered = api.create_registration(
            {"event_id": sc["event"]["id"], "project_id": sc["project"]["id"]},
            make_employee_volunteer_headers(vol["id"]),
        )
        data = validate_success(re_registered, 201)
        assert data["id"] != reg["id"]


class TestWaiverSigningRules:
    def test_minor_self_sign_requires_guardian(self, api):
        """PRD §3.4: "The guardian rule is strict: for a registration whose `is_minor` is true, `signer_relation` must be `GUARDIAN` and `guardian_name` must be non-empty, otherwise the request is rejected with `ERR_GUARDIAN_SIGNATURE_REQUIRED` (HTTP 422); for an adult, `signer_relation` must be `SELF`, and any other value is rejected with `ERR_VALIDATION`."

        Design: Corner/validations/minor_self_sign_requires_guardian
        """
        sc = setup_matched_scenario(event_name="Day 16")
        teen = create_volunteer("Teen", "teen@corp.com", date_of_birth=MINOR_DOB, department="Intern")
        reg = register_volunteer(teen, sc["event"]["id"], sc["project"]["id"])

        resp = api.sign_waiver(
            reg["id"],
            {"signer_name": "Teen", "signer_relation": "SELF", "media_consent": False},
            make_employee_volunteer_headers(teen["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GUARDIAN_SIGNATURE_REQUIRED)
        assert get_registration(reg["id"])["waiver_status"] == "WAIVER_PENDING"

    def test_registration_is_minor_computed_from_event_date(self, api):
        """PRD §3.3: "Whether a volunteer counts as a minor is decided per event: a registration's `is_minor` is true when the volunteer's age, computed from `date_of_birth`, is under 18 at the event's `event_start_at`."
        PRD §3.4: "A new registration starts with `rsvp_status` `REGISTERED` and `waiver_status` `WAIVER_PENDING`, with `waiver_signed_version`, `waiver_signer_relation`, `waiver_signer_name`, and `checked_in_at` all null, `media_consent` false, `transport_manifest_id` null, and both hours credits at zero; the event's headcounts recompute immediately."

        Design: Corner/entities/registration_is_minor_computed_from_event_date
        """
        sc = setup_matched_scenario(event_name="Day 2", budget_cents=500000)
        teen = create_volunteer("Teen", "teen@corp.com", date_of_birth=MINOR_DOB, department="Intern")
        adult = create_volunteer("Adult", "adult@corp.com")

        reg_minor = register_volunteer(teen, sc["event"]["id"], sc["project"]["id"])
        reg_adult = register_volunteer(adult, sc["event"]["id"], sc["project"]["id"])
        # 2011-05-01 -> age 15 at 2026-08-20 (minor); 1990-01-01 -> 36 (adult)
        assert reg_minor["is_minor"] is True
        assert reg_adult["is_minor"] is False
        assert reg_minor["waiver_signed_version"] is None
        assert reg_minor["waiver_status"] == "WAIVER_PENDING"


class TestRegistrationRbac:
    def test_volunteer_cannot_confirm_own_registration(self, api):
        """PRD §3.4: "Confirmation is a manager-only action with five preconditions, which the pipeline orders as state first, safety next, capacity last: the registration must be in `REGISTERED` (`ERR_INVALID_REGISTRATION_TRANSITION` otherwise), the event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` (`ERR_EVENT_STATE_FORBIDS_WRITE`), the project must be `MATCHED` or `LOCKED` (`ERR_INVALID_PROJECT_TRANSITION`), the waiver must be `WAIVER_SIGNED` or `WAIVER_VERIFIED` (`ERR_WAIVER_NOT_SIGNED`), and the project's `confirmed_volunteer_count` must be below its `max_volunteers` (`ERR_PROJECT_AT_CAPACITY`)."
        PRD §2.1: "an authenticated caller whose role is not in an endpoint's list, or who fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/volunteer_cannot_confirm_own_registration
        """
        sc = setup_matched_scenario(event_name="Day 43")
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = register_volunteer(vol, sc["event"]["id"], sc["project"]["id"])

        resp = api.confirm_registration(
            reg["id"], make_employee_volunteer_headers(vol["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_registration(reg["id"])["rsvp_status"] == "REGISTERED"

    def test_volunteer_cannot_cancel_others_registration(self, api):
        """PRD §3.4: "A registration can be cancelled from `REGISTERED` or `CONFIRMED` — other states are `ERR_INVALID_REGISTRATION_TRANSITION` — by a manager, or by the volunteer themselves, in which case the caller's `X-User-ID` must equal the registration's `volunteer_id` (`ERR_FORBIDDEN_ROLE` otherwise)."

        Design: Corner/rbac/volunteer_cannot_cancel_others_registration
        """
        sc = setup_matched_scenario(event_name="Day 44")
        vol1 = create_volunteer("Vol 1", "v1@corp.com")
        vol2 = create_volunteer("Vol 2", "v2@corp.com")
        reg1 = register_volunteer(vol1, sc["event"]["id"], sc["project"]["id"])

        resp = api.cancel_registration(
            reg1["id"], make_employee_volunteer_headers(vol2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_registration(reg1["id"])["rsvp_status"] == "REGISTERED"

    def test_staff_lead_checkin_requires_active_assignment(self, api):
        """PRD §3.4: "A staff-lead caller must hold an `ACTIVE` supervision assignment on the registration's project, otherwise `ERR_NOT_PROJECT_LEAD` (HTTP 403)."

        Design: Corner/rbac/staff_lead_checkin_requires_active_assignment
        """
        sc = setup_in_progress_event(event_name="Day 47", budget_cents=500000)
        other_lead = create_volunteer(
            "Lead Two", "lead2@corp.com", date_of_birth="1986-04-04", is_staff_lead=True
        )
        reg = sc["registrations"][0]

        # A staff lead with no ACTIVE assignment on this project is rejected
        denied = api.check_in_registration(
            reg["id"], make_staff_lead_headers(other_lead["id"])
        )
        validate_error(denied, ApiErrorId.ERR_NOT_PROJECT_LEAD)

        # The assigned lead checks the volunteer in
        ok = api.check_in_registration(
            reg["id"], make_staff_lead_headers(sc["lead"]["id"])
        )
        data = validate_success(ok, 200)
        assert data["rsvp_status"] == "CHECKED_IN"


class TestRegistrationListing:
    def test_list_pagination_envelope_and_flags(self, api, any_headers):
        """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."

        Design: Corner/endpoints/list_pagination_envelope_and_flags
        """
        sc = setup_matched_scenario(event_name="Day 35")
        for i in range(3):
            vol = create_volunteer(f"Vol {i + 1}", f"v{i + 1}@corp.com")
            register_volunteer(vol, sc["event"]["id"], sc["project"]["id"])

        page1, meta1 = validate_paginated(
            api.list_registrations(
                any_headers, params={"event_id": sc["event"]["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_registrations(
                any_headers, params={"event_id": sc["event"]["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        body = api.list_registrations(
            any_headers, params={"event_id": sc["event"]["id"], "limit": 2, "offset": 0}
        ).json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestRegistrationReferentialRules:
    def test_body_fk_event_not_found_on_registration(self, api):
        """PRD §2.10: "The full not-found family — `ERR_NONPROFIT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_MEAL_PLAN_NOT_FOUND`, `ERR_SUPERVISION_NOT_FOUND`, `ERR_SPONSORSHIP_NOT_FOUND`, `ERR_IMPACT_RECORD_NOT_FOUND`, and `ERR_SURVEY_NOT_FOUND` — is likewise used for body-referenced foreign keys that do not exist, checked after the path identifiers."

        Design: Corner/validations/body_fk_event_not_found_on_registration
        """
        vol = create_volunteer("Vol One", "v1@corp.com")
        resp = api.create_registration(
            {"event_id": NON_EXISTENT_UUID, "project_id": NON_EXISTENT_UUID},
            make_employee_volunteer_headers(vol["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)

    def test_registration_project_event_mismatch_rejected(self, api):
        """PRD §3.4: "The project must belong to the same event — a mismatch is rejected with `ERR_PROJECT_EVENT_MISMATCH` (HTTP 422) — and must currently be `MATCHED` or `LOCKED` to that event, otherwise `ERR_INVALID_PROJECT_TRANSITION`."

        Design: Corner/validations/registration_project_event_mismatch_rejected
        """
        partner = create_partner()
        proj_b = create_project(partner["id"], "P-B")
        ev_a = create_event("Day 30A")
        ev_b = create_event(
            "Day 30B", event_start_at="2026-08-21T09:00:00Z", event_end_at="2026-08-21T15:00:00Z"
        )
        vet_project(proj_b["id"])
        match_project(proj_b["id"], ev_b["id"])  # matched to EvB only
        open_event_registration(ev_a["id"])
        vol = create_volunteer("Vol One", "v1@corp.com")

        resp = api.create_registration(
            {"event_id": ev_a["id"], "project_id": proj_b["id"]},
            make_employee_volunteer_headers(vol["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_EVENT_MISMATCH)


class TestImmediateConsistency:
    def test_immediate_visibility_after_confirm(self, api, cem_headers):
        """PRD §3.4: "A successful confirm increments the project's `confirmed_volunteer_count` by one and recomputes `required_staff_leads` per the supervision rule; if the project was `LOCKED` and the new requirement now exceeds `active_staff_leads`, the project automatically demotes `LOCKED` → `MATCHED` and the event's posture is recomputed. Event headcounts recompute as well."

        Design: Corner/consistency_model/immediate_visibility_after_confirm
        """
        sc = setup_matched_scenario(event_name="Day 52")
        vol = create_volunteer("Vol One", "v1@corp.com")
        reg = add_signed_registration(
            sc["event"]["id"], sc["project"]["id"], vol, wants_meal=False
        )

        resp = api.confirm_registration(reg["id"], cem_headers)
        data = validate_success(resp, 200)
        assert data["rsvp_status"] == "CONFIRMED"  # response itself reflects the write

        project = get_project(sc["project"]["id"])
        event = get_event(sc["event"]["id"])
        assert project["confirmed_volunteer_count"] == 1
        assert project["required_staff_leads"] == 1
        assert event["confirmed_headcount"] == 1
