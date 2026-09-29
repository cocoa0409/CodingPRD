"""Who may act, who may not, and what the two identity headers have to carry.

Authentication is checked before anything else, exclusive operations refuse other
roles ahead of existence checks, one payload field is role-scoped, and shared
operations behave identically whichever declared role performs them.
"""

from test_helpers import (
    ALL_ROLES,
    ApiErrorId,
    BedStatus,
    BedType,
    COMPLIANCE_OFFICER_HEADERS,
    InterventionType,
    LegalStatus,
    NON_EXISTENT_UUID,
    PlacementStatus,
    SafetySearchStatus,
    SearchType,
    StaffRole,
    UnitPosture,
    active_hold_case,
    assert_error,
    assert_first_failing_check,
    assert_ok,
    assert_page,
    assert_posture_threshold,
    assert_unit_availability,
    build_ward,
    complete_safety_search,
    create_admission,
    create_patient,
    make_unauthenticated_headers,
    make_headers,
    place_admission,
    placement_payload,
    read_admission,
    read_bed,
    read_unit,
    restraint_payload,
    safety_search_payload,
    set_bed_status,
    signed_evaluation,
    unit_version,
)

STARTUP_INSTANT = "2026-08-01T00:00:00.000Z"
UNDECLARED_ROLE = "BedManager"
ROGUE_LICENCE = "LIC-RN-2367-9"
NURSE_OVERRIDE_REASON = "Nurse asserts override authority."
ROGUE_ROOM = "9901"
ESCALATION_JUSTIFICATION = "Attempted role escalation."
RESTRAINT_MINUTES = 30

RBAC_UNIT = "Ward 37 Roles"
# Two beds each, so PRD 3.1's restriction threshold — "the greater of 1 and one fifth of
# `licensed_placement_bed_count` rounded down" — leaves these units `OPEN` and an
# ordinary placement is not refused by the `RESTRICTED` safety reserve.
RBAC_BEDS = (
    {"room_number": "561", "wing_code": "A", "bed_label": "A"},
    {"room_number": "562", "wing_code": "A", "bed_label": "A"},
)
SHARED_UNIT = "Ward 38 Shared"
SHARED_BEDS = ({"room_number": "571", "wing_code": "A", "bed_label": "A"},)
SEARCH_UNIT = "Ward 39 Search"
SEARCH_BEDS = (
    {"room_number": "581", "wing_code": "A", "bed_label": "A"},
    {"room_number": "582", "wing_code": "A", "bed_label": "A"},
)
ITEMS_SECURED = 2


class TestMissingOrUnknownIdentityHeaders:
    """Priority one wants both headers and one of exactly five role names."""

    def test_an_absent_header_or_an_undeclared_role_is_refused_before_any_other_check(
        self, api, roster
    ):
        """No user id, an invented role, and no role at all: three ways to fail authentication.

        PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity in which they act.
        Exactly five roles exist, spelled precisely as follows: `ComplianceOfficer`,
        `IntakeClinician`, `AttendingPsychiatrist`, `ChargeNurse`, and
        `PatientRightsAdvocate`. A request missing either header, or presenting an
        `X-User-Role` value outside this set of five, is rejected with
        `ERR_UNAUTHENTICATED` (401)."

        PRD 2.1: "When `X-User-Role` is `IntakeClinician`, `AttendingPsychiatrist`,
        `ChargeNurse`, or `PatientRightsAdvocate`, `X-User-ID` is the `id` of the acting
        `Clinician` row."

        PRD 2.9: "`ERR_UNAUTHENTICATED` — on every endpoint: both context headers
        present and `X-User-Role` among the five declared roles."

        Design: Corner/rbac/missing_x_user_headers_returns_unauthenticated
        """
        assert UNDECLARED_ROLE not in ALL_ROLES
        nurse_id = roster.charge_nurse["id"]

        no_user_id = api.get_clinician(
            make_unauthenticated_headers(role="ChargeNurse"), nurse_id
        )
        assert_error(no_user_id, ApiErrorId.UNAUTHENTICATED)

        unknown_role = api.get_clinician(
            make_headers(UNDECLARED_ROLE, nurse_id), nurse_id
        )
        assert_error(unknown_role, ApiErrorId.UNAUTHENTICATED)

        no_role = api.create_bed(
            make_unauthenticated_headers(user_id=nurse_id),
            {"unit_id": NON_EXISTENT_UUID, "room_number": ROGUE_ROOM},
        )
        assert_first_failing_check(
            no_role,
            ApiErrorId.UNAUTHENTICATED,
            (ApiErrorId.INVALID_REQUEST, ApiErrorId.UNIT_NOT_FOUND),
        )


class TestExclusiveOperationsRefuseOtherRoles:
    """Each exclusive operation refuses the wrong role ahead of any existence check."""

    def test_the_wrong_role_is_refused_before_the_dangling_identifiers_are_resolved(
        self, api, roster
    ):
        """Roster maintenance, the clock, restraint ordering and admission opening each name one role.

        PRD 2.9: "`ERR_UNAUTHORIZED` — on every endpoint: the acting role is authorized
        for the operation, and `posture_override_reason` on placement is accepted only
        from an `AttendingPsychiatrist`."

        PRD 2.4: "A `ComplianceOfficer` moves the clock by submitting a `to_iso8601`
        instant, and the response body reports the new value as `current_utc`."

        PRD 3.2: "The server stamps `evaluating_clinician_id` from the header and
        `evaluation_started_at` from the logical clock, and the evaluation's `status`
        begins at `DRAFT`."

        Design: Corner/rbac/exclusive_operations_of_other_roles_are_rejected
        """
        rogue_hire = api.create_clinician(
            roster.charge_nurse_headers,
            {
                "full_name": "Rogue Hire",
                "staff_role": StaffRole.CHARGE_NURSE.value,
                "license_number": ROGUE_LICENCE,
            },
        )
        assert_error(rogue_hire, ApiErrorId.UNAUTHORIZED)

        moved_clock = api.set_clock(
            roster.psychiatrist_headers, {"to_iso8601": "2026-09-03T08:00:00Z"}
        )
        assert_error(moved_clock, ApiErrorId.UNAUTHORIZED)

        rogue_restraint = api.create_restraint(
            roster.charge_nurse_headers,
            restraint_payload(
                admission_id=NON_EXISTENT_UUID,
                intervention_type=InterventionType.MECHANICAL_RESTRAINT.value,
                ordered_duration_minutes=RESTRAINT_MINUTES,
                clinical_justification=ESCALATION_JUSTIFICATION,
            ),
        )
        assert_first_failing_check(
            rogue_restraint,
            ApiErrorId.UNAUTHORIZED,
            (ApiErrorId.ADMISSION_NOT_FOUND,),
        )

        ward = build_ward(
            api,
            name=RBAC_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=RBAC_BEDS,
        )
        rogue_admission = api.create_admission(
            roster.advocate_headers,
            {
                "patient_id": NON_EXISTENT_UUID,
                "evaluation_id": NON_EXISTENT_UUID,
                "unit_id": ward.id,
                "requested_legal_status": LegalStatus.VOLUNTARY.value,
            },
        )
        assert_first_failing_check(
            rogue_admission,
            ApiErrorId.UNAUTHORIZED,
            (ApiErrorId.PATIENT_NOT_FOUND,),
        )

        still_default = signed_evaluation(
            api,
            roster.intake_headers,
            create_patient(
                api,
                mrn="MRN-2367-RB",
                legal_name="Role Boundary",
                age_years=46,
                gender_care_category="MALE",
            )["id"],
        )
        assert still_default["evaluation_started_at"] == STARTUP_INSTANT

    def test_only_a_psychiatrist_may_carry_a_posture_override_on_placement(
        self, api, roster
    ):
        """The nurse may place, but the same call with the override field is a permission failure.

        PRD 2.1: "The same 403 code covers one role-scoped payload restriction: only an
        `AttendingPsychiatrist` may supply a `posture_override_reason` when placing an
        admission, so the same field submitted by a `ChargeNurse` is a permission
        failure rather than a schema failure."

        Design: Corner/rbac/exclusive_operations_of_other_roles_are_rejected
        """
        ward = build_ward(
            api,
            name=RBAC_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=RBAC_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-RO",
            legal_name="Override Case",
            age_years=39,
            gender_care_category="MALE",
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        complete_safety_search(api, roster, admission["id"])
        version = unit_version(api, ward.id)

        refused = api.place_admission(
            roster.charge_nurse_headers,
            admission["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=version,
                bed_id=ward.beds[0]["id"],
                posture_override_reason=NURSE_OVERRIDE_REASON,
            ),
        )
        assert_error(refused, ApiErrorId.UNAUTHORIZED)
        assert (
            read_admission(api, admission["id"])["placement_status"]
            == PlacementStatus.PENDING_PLACEMENT.value
        )
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.AVAILABLE.value
        )

        placed = assert_ok(
            api.place_admission(
                roster.charge_nurse_headers,
                admission["id"],
                placement_payload(
                    unit_id=ward.id,
                    expected_unit_version=version,
                    bed_id=ward.beds[0]["id"],
                ),
            )
        )
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )


class TestSharedOperationsAcceptEitherRole:
    """A shared operation is the same operation whoever performs it."""

    def test_two_roles_register_patients_and_two_roles_patch_the_same_bed(
        self, api, clock, roster
    ):
        """Both registrations succeed, both bed patches recompute the unit, and the advocate reads it all.

        PRD 4: "In the table below, an authorized role of **Any** means all five
        declared roles: `ComplianceOfficer`, `IntakeClinician`, `AttendingPsychiatrist`,
        `ChargeNurse` and `PatientRightsAdvocate`."

        PRD 4: "| POST | `/behavioral-health/patients` | Register a patient |
        ComplianceOfficer, IntakeClinician |"

        PRD 3.1: "A new bed's `status` starts at `AVAILABLE` and thereafter takes one of
        `AVAILABLE`, `OCCUPIED`, `BLOCKED_CLEANING` or `OUT_OF_SERVICE`. A
        `ComplianceOfficer` or a `ChargeNurse` may change a bed's `status` directly —
        blocking it for cleaning, taking it out of service, or returning it to service —
        and the beds of a unit can be listed with optional filters on `status` and
        `bed_type`."

        PRD 3.1: "Step two derives `posture` from `raw_available_bed_count` and nothing
        else: first compute a restriction threshold equal to the greater of 1 and one
        fifth of `licensed_placement_bed_count` rounded down to a whole number; then the
        posture is `CLOSED` when `raw_available_bed_count` is zero, `RESTRICTED` when it
        is greater than zero but no greater than that threshold, and `OPEN` otherwise."

        Design: Corner/rbac/shared_operations_accept_either_declared_role
        """
        ward = build_ward(
            api,
            name=SHARED_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=SHARED_BEDS,
        )
        bed = ward.beds[0]
        baseline = unit_version(api, ward.id)

        by_officer = create_patient(
            api,
            mrn="MRN-2367-SH1",
            legal_name="Registered By Officer",
            age_years=33,
            gender_care_category="MALE",
            headers=COMPLIANCE_OFFICER_HEADERS,
        )
        by_clinician = create_patient(
            api,
            mrn="MRN-2367-SH2",
            legal_name="Registered By Clinician",
            age_years=34,
            gender_care_category="FEMALE",
            headers=roster.intake_headers,
        )
        assert by_officer["id"] != by_clinician["id"]

        set_bed_status(
            api,
            bed["id"],
            BedStatus.OUT_OF_SERVICE.value,
            headers=roster.charge_nurse_headers,
        )
        emptied = read_unit(api, ward.id, headers=roster.advocate_headers)
        assert_unit_availability(emptied, licensed=0, raw_available=0)
        assert emptied["posture"] == UnitPosture.CLOSED.value
        assert emptied["effective_available_bed_count"] == 0

        set_bed_status(
            api,
            bed["id"],
            BedStatus.AVAILABLE.value,
            headers=COMPLIANCE_OFFICER_HEADERS,
        )
        restored = read_unit(api, ward.id, headers=roster.advocate_headers)
        assert_unit_availability(restored, licensed=1, raw_available=1)
        assert_posture_threshold(1, 1)
        assert restored["posture"] == UnitPosture.RESTRICTED.value
        assert restored["effective_available_bed_count"] == 0
        assert restored["version"] == baseline + 2

        beds, meta = assert_page(
            api.list_unit_beds(roster.advocate_headers, ward.id), 1
        )
        assert beds[0]["bed_type"] == BedType.STANDARD.value
        assert meta["has_more"] is False


class TestSafetySearchWitnessMustDiffer:
    """The performer comes from the header and the witness from the body."""

    def test_a_self_witnessed_search_is_refused_and_leaves_the_placement_gate_closed(
        self, api, clock, roster
    ):
        """The nurse cannot witness her own search, and the refusal keeps the search PENDING.

        PRD 3.5: "Either way the server records `search_performed_by_clinician_id` from
        the header and increments `Admission.version` by one. The witness must be a
        different person from the performer, per §2.10."

        PRD 3.5: "The admission must be in `PENDING_PLACEMENT`, or the request fails
        with `ERR_ADMISSION_NOT_PLACEABLE`, and its `safety_search_status` must be
        exactly `COMPLETED`, or the request fails with `ERR_SAFETY_SEARCH_INCOMPLETE`."

        Design: Corner/rbac/safety_search_witness_equal_to_performer_is_rejected
        """
        ward = build_ward(
            api,
            name=SEARCH_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=SEARCH_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-SD",
            legal_name="Duties Search",
            age_years=36,
            gender_care_category="FEMALE",
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )

        self_witnessed = api.record_safety_search(
            roster.charge_nurse_headers,
            admission["id"],
            safety_search_payload(
                search_witness_clinician_id=roster.charge_nurse["id"],
                search_type=SearchType.WANDED.value,
                search_items_secured_count=ITEMS_SECURED,
                contraband_found=True,
            ),
        )
        assert_error(self_witnessed, ApiErrorId.SEGREGATION_OF_DUTIES)

        untouched = read_admission(api, admission["id"])
        assert untouched["safety_search_status"] == SafetySearchStatus.PENDING.value
        assert untouched["search_performed_by_clinician_id"] is None
        assert untouched["version"] == admission["version"]

        blocked = api.place_admission(
            roster.charge_nurse_headers,
            admission["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=unit_version(api, ward.id),
                bed_id=ward.beds[0]["id"],
            ),
        )
        assert_error(blocked, ApiErrorId.SAFETY_SEARCH_INCOMPLETE)

        searched = complete_safety_search(
            api,
            roster,
            admission["id"],
            witness_clinician_id=roster.intake["id"],
            items_secured=ITEMS_SECURED,
            contraband_found=True,
        )
        assert searched["safety_search_status"] == SafetySearchStatus.COMPLETED.value
        assert searched["search_performed_by_clinician_id"] == roster.charge_nurse["id"]
        assert searched["search_witness_clinician_id"] == roster.intake["id"]
        assert searched["contraband_found"] is True
        assert searched["version"] == admission["version"] + 1

        placed = place_admission(
            api, roster, admission["id"], ward.id, bed_id=ward.beds[0]["id"]
        )
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )
