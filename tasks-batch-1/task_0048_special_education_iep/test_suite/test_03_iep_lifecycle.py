"""IEP lifecycle: the DRAFT → MEETING_HELD → ACTIVE → AMENDMENT_PENDING cycle,
archival with its child cascade, the placement-consent revocation cascade, the
single-active-program rule, and the active_iep_id pointer invariant
(PRD §3.5, §3.4).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_admin_headers,
    make_case_manager_headers,
    make_parent_headers,
    open_amendment_payload,
    create_iep_payload,
    set_clock,
    create_student,
    make_eligible_student,
    make_draft_iep_for_eligible_student,
    make_meeting_held_iep,
    make_active_iep,
    grant_placement_consent,
    create_goal,
    add_related_service,
    create_draft_iep,
    get_student,
    get_iep,
)

ADMIN = make_admin_headers("adm_1")
CM = make_case_manager_headers("cm_1")
PAR = make_parent_headers("par_1")


class TestIepCycle:
    def test_active_to_amendment_pending_status(self, api):
        """PRD §3.5: "Opening an amendment moves a program `ACTIVE → AMENDMENT_PENDING`; it may be driven explicitly by a `CaseManager` or arise as the system cascade from a placement-consent withdrawal. It requires the program to be `ACTIVE`."

        Opening an amendment on an ACTIVE IEP (with the current expected_iep_version)
        moves it to AMENDMENT_PENDING.

        Design: Difficulty/non_linear_state_machine/iep_cycle_active_amendment_active
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Omar Diaz", "date_of_birth": "2014-08-08"},
        )
        amended = validate_success(
            api.open_amendment(iep["id"], open_amendment_payload(iep["version"]), CM), 200
        )
        assert amended["status"] == "AMENDMENT_PENDING", amended["status"]

    def test_amendment_pending_back_to_active(self, api):
        """PRD §3.5: "From `AMENDMENT_PENDING`, the program is turned back on by a `SpecialEdAdmin` through the same activation action that serves `MEETING_HELD`: it moves `AMENDMENT_PENDING → ACTIVE`, subject to the same three preconditions"
        PRD §3.5: "This `ACTIVE → AMENDMENT_PENDING → ACTIVE` cycle may repeat across successive revision rounds."

        After opening an amendment, re-activating returns the IEP to ACTIVE — the
        full cyclic loop.

        Design: Difficulty/non_linear_state_machine/iep_cycle_active_amendment_active
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Omar Diaz2", "date_of_birth": "2014-08-08"},
        )
        amended = validate_success(
            api.open_amendment(iep["id"], open_amendment_payload(iep["version"]), CM), 200
        )
        assert amended["status"] == "AMENDMENT_PENDING"
        reactivated = validate_success(api.activate_iep(iep["id"], ADMIN), 200)
        assert reactivated["status"] == "ACTIVE", reactivated["status"]


class TestArchiveCascade:
    def test_archive_cascades_goal_service_and_clears_pointer(self, api):
        """PRD §3.5: "Archival clears the student's `active_iep_id` and increments the student's `version` by one, and increments the program's `version` by one. It also cascades to the program's children: every goal on this program whose status is `ACTIVE` transitions to `DISCONTINUED`, and every related service on this program whose status is `ACTIVE` transitions to `DISCONTINUED`."

        Design: Difficulty/transitive_cascade/archive_iep_cascades_goals_and_services_depth3
        """
        set_clock("2026-03-01T09:00:00Z")
        # Build IEP with a goal + pull-out service while DRAFT, then activate, then archive.
        student = make_eligible_student(student_overrides={
            "full_name": "Priya Sen", "date_of_birth": "2014-09-09", "grade_level": 6})
        iep = create_draft_iep(student["id"])
        goal = create_goal(iep["id"], domain="READING", baseline_value=0, target_value=100)
        rs = add_related_service(iep["id"], iep["version"], service_type="SPEECH",
                                 minutes_per_week=150, delivered_in_general_ed=False)
        validate_success(api.hold_meeting(iep["id"], CM), 200)
        grant_placement_consent(student["id"], iep["id"])
        validate_success(api.activate_iep(iep["id"], ADMIN), 200)

        archived = validate_success(api.archive_iep(iep["id"], ADMIN), 200)
        assert archived["status"] == "ARCHIVED", archived["status"]
        assert validate_success(api.get_goal(goal["id"], ADMIN), 200)["status"] == "DISCONTINUED"
        assert validate_success(api.get_related_service(rs["id"], ADMIN), 200)["status"] == "DISCONTINUED"
        assert get_student(student["id"])["active_iep_id"] is None

    def test_archive_discontinues_active_goal(self, api):
        """PRD §3.5: "every goal on this program whose status is `ACTIVE` transitions to `DISCONTINUED ... Each such child transition is an independent mutation of that child."

        Focused assertion on the goal arm of the depth-3 archive cascade: an ACTIVE
        goal becomes DISCONTINUED when its parent IEP is archived.

        Design: Difficulty/transitive_cascade/archive_iep_cascades_goals_and_services_depth3
        """
        set_clock("2026-03-01T09:00:00Z")
        student = make_eligible_student(student_overrides={
            "full_name": "Priya Sen2", "date_of_birth": "2014-09-09", "grade_level": 6})
        iep = create_draft_iep(student["id"])
        goal = create_goal(iep["id"], domain="MATH", baseline_value=0, target_value=100)
        validate_success(api.hold_meeting(iep["id"], CM), 200)
        grant_placement_consent(student["id"], iep["id"])
        validate_success(api.activate_iep(iep["id"], ADMIN), 200)
        validate_success(api.archive_iep(iep["id"], ADMIN), 200)
        assert validate_success(api.get_goal(goal["id"], ADMIN), 200)["status"] == "DISCONTINUED"


class TestRevokePlacementCascade:
    def test_revoke_placement_consent_drives_iep_to_amendment_pending(self, api):
        """PRD §3.4: "if the revoked consent is of type `PLACEMENT` and its linked program (named by the request's `iep_id`) is currently turned on, the program is forced out of its active state into its amendment-pending state, and that program transition in turn clears the student's `active_iep_id` (and bumps the student's version)."

        Design: Difficulty/transitive_cascade/revoke_placement_consent_cascades_iep_out_of_active_depth2
        """
        set_clock("2026-03-01T09:00:00Z")
        student, iep, plc_cr_id = make_active_iep(
            student_overrides={"full_name": "Sam Yoo", "date_of_birth": "2014-10-10"},
        )
        revoked = validate_success(api.revoke_consent(plc_cr_id, PAR), 200)
        assert revoked["status"] == "REVOKED", revoked["status"]
        assert get_iep(iep["id"])["status"] == "AMENDMENT_PENDING"
        assert get_student(student["id"])["active_iep_id"] is None

    def test_revoke_placement_consent_clears_active_iep_pointer(self, api):
        """PRD §3.4: "that program transition in turn clears the student's `active_iep_id` (and bumps the student's version)."

        Focused assertion on the depth-2 arm reaching the Student: revoking the
        PLACEMENT consent on an ACTIVE program nulls Student.active_iep_id.

        Design: Difficulty/transitive_cascade/revoke_placement_consent_cascades_iep_out_of_active_depth2
        """
        set_clock("2026-03-01T09:00:00Z")
        student, iep, plc_cr_id = make_active_iep(
            student_overrides={"full_name": "Sam Yoo2", "date_of_birth": "2014-10-10"},
        )
        assert get_student(student["id"])["active_iep_id"] == iep["id"]
        validate_success(api.revoke_consent(plc_cr_id, PAR), 200)
        assert get_student(student["id"])["active_iep_id"] is None


class TestActiveIepPointerInvariant:
    def test_active_iep_id_set_on_activate_cleared_on_amendment(self, api):
        """PRD §3.5: "activation stamps `activated_at` with the server clock, sets the student's `active_iep_id` to this program's `id` and increments the student's `version` by one"
        PRD §3.5: "leaving the active state clears the student's `active_iep_id` (sets it to null) and increments the student's `version` by one"

        The 0/1 pointer returns to its pre-activation value: set to the IEP on
        activate, back to null on opening an amendment.

        Design: Difficulty/compensating_invariant/active_iep_id_set_then_cleared_invariant
        """
        set_clock("2026-03-01T09:00:00Z")
        student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Kit Vance", "date_of_birth": "2014-06-06"},
        )
        assert get_student(student["id"])["active_iep_id"] == iep["id"]
        validate_success(
            api.open_amendment(iep["id"], open_amendment_payload(iep["version"]), CM), 200
        )
        assert get_student(student["id"])["active_iep_id"] is None

    def test_active_iep_id_equals_iep_while_active(self, api):
        """PRD §3.5: "activation ... sets the student's `active_iep_id` to this program's `id"
        PRD §3.1: "The `active_iep_id` holds the `id` of the student's program that is currently turned on — at most one — and is null when no program is on"

        While the IEP is ACTIVE, Student.active_iep_id points exactly at it.

        Design: Difficulty/compensating_invariant/active_iep_id_set_then_cleared_invariant
        """
        set_clock("2026-03-01T09:00:00Z")
        student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Kit Vance2", "date_of_birth": "2014-06-06"},
        )
        assert get_student(student["id"])["active_iep_id"] == iep["id"]


class TestActivateConsentDependency:
    def test_activate_with_pending_placement_consent_rejected(self, api):
        """PRD §3.5: "the `PLACEMENT` consent request for this program must be in `GRANTED` status, failing which the activation is rejected with `ERR_CONSENT_NOT_GRANTED` (HTTP 409)"

        A MEETING_HELD IEP whose PLACEMENT consent is still PENDING cannot be
        activated.

        Design: Difficulty/cross_entity_state_dependency/iep_activate_requires_consentrequest_granted
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, _plc = make_meeting_held_iep(
            student_overrides={"full_name": "Rosa Kim", "date_of_birth": "2014-03-03"},
        )
        validate_error(
            api.activate_iep(iep["id"], ADMIN),
            ApiErrorId.ERR_CONSENT_NOT_GRANTED.value,
        )

    def test_activate_succeeds_once_placement_consent_granted(self, api):
        """PRD §3.5: "the `PLACEMENT` consent request for this program must be in `GRANTED` status, failing which the activation is rejected with `ERR_CONSENT_NOT_GRANTED` (HTTP 409)"
        PRD §3.5: "Activation moves a program `MEETING_HELD → ACTIVE`."

        Once the PLACEMENT consent is GRANTED, activation proceeds and the IEP turns
        ACTIVE — the positive complement of the consent-dependency guard.

        Design: Difficulty/cross_entity_state_dependency/iep_activate_requires_consentrequest_granted
        """
        set_clock("2026-03-01T09:00:00Z")
        student, iep, _plc = make_meeting_held_iep(
            student_overrides={"full_name": "Rosa Kim2", "date_of_birth": "2014-03-03"},
        )
        grant_placement_consent(student["id"], iep["id"])
        activated = validate_success(api.activate_iep(iep["id"], ADMIN), 200)
        assert activated["status"] == "ACTIVE", activated["status"]


class TestIepGuardsAndState:
    def test_hold_meeting_on_not_evaluated_student_rejected(self, api):
        """PRD §3.5: "it requires the program to be in `DRAFT` and the student's `eligibility_status` to be `ELIGIBLE`; if the student is not eligible, the meeting is rejected with `ERR_STUDENT_NOT_ELIGIBLE` (HTTP 409)."

        Design: Corner/state_machines/hold_meeting_on_not_evaluated_student_returns_not_eligible
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Tess Page",
                                 date_of_birth="2014-06-06", grade_level=6)
        iep = create_draft_iep(student["id"])
        validate_error(
            api.hold_meeting(iep["id"], CM),
            ApiErrorId.ERR_STUDENT_NOT_ELIGIBLE.value,
        )

    def test_archive_from_draft_rejected(self, api):
        """PRD §3.5: "A `SpecialEdAdmin` archives a program that is `ACTIVE`, moving it `ACTIVE → ARCHIVED`."

        Archive is only defined from ACTIVE; archiving a DRAFT IEP is rejected with
        ERR_INVALID_STATE.

        Design: Corner/state_machines/archive_from_draft_returns_invalid_state
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Sky Boon", "date_of_birth": "2014-08-08"},
        )
        validate_error(
            api.archive_iep(iep["id"], ADMIN),
            ApiErrorId.ERR_INVALID_STATE.value,
        )

    def test_activate_second_iep_while_one_active_rejected(self, api):
        """PRD §3.5: "the student must have no other program already turned on, failing which the activation is rejected with `ERR_ACTIVE_IEP_EXISTS` (HTTP 409)."

        With IEP-A already ACTIVE, activating IEP-B (its own PLACEMENT consent
        GRANTED) is rejected.

        Design: Corner/state_machines/activate_second_iep_while_one_active_returns_active_iep_exists
        """
        set_clock("2026-03-01T09:00:00Z")
        student = make_eligible_student(student_overrides={
            "full_name": "Uma Lott", "date_of_birth": "2014-09-09", "grade_level": 6})
        iep_a = create_draft_iep(student["id"])
        validate_success(api.hold_meeting(iep_a["id"], CM), 200)
        grant_placement_consent(student["id"], iep_a["id"])
        validate_success(api.activate_iep(iep_a["id"], ADMIN), 200)

        iep_b = create_draft_iep(student["id"], annual_review_due_date="2027-09-01")
        validate_success(api.hold_meeting(iep_b["id"], CM), 200)
        grant_placement_consent(student["id"], iep_b["id"])
        validate_error(
            api.activate_iep(iep_b["id"], ADMIN),
            ApiErrorId.ERR_ACTIVE_IEP_EXISTS.value,
        )

    def test_iep_initial_state_is_draft_full_inclusion(self, api):
        """PRD §3.5: "A drafted program begins in status `DRAFT`, with a least-restrictive-environment percentage of 100.0 and a setting of `FULL_INCLUSION`."

        Design: Corner/state_machines/iep_initial_state_is_draft
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Dot Ives",
                                 date_of_birth="2014-02-02", grade_level=6)
        iep = validate_success(api.create_iep(create_iep_payload(student["id"]), CM), 201)
        assert iep["status"] == "DRAFT", iep["status"]
        assert iep["lre_general_ed_pct"] == 100.0, iep["lre_general_ed_pct"]
        assert iep["lre_setting"] == "FULL_INCLUSION", iep["lre_setting"]


class TestOpenAmendmentOcc:
    def test_open_amendment_with_current_version_succeeds(self, api):
        """PRD §2.9: "A request to open an amendment must carry `expected_iep_version` as a required field whose value is the program `version` the client last observed. If that value does not match the program's current `version ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.5: "Opening an amendment moves a program `ACTIVE → AMENDMENT_PENDING"

        Opening an amendment with the current (activate-response) version succeeds
        and the IEP moves to AMENDMENT_PENDING.

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_open_amendment_succeeds
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Ida Voss", "date_of_birth": "2014-06-06"},
        )
        amended = validate_success(
            api.open_amendment(iep["id"], open_amendment_payload(iep["version"]), CM), 200
        )
        assert amended["status"] == "AMENDMENT_PENDING", amended["status"]
