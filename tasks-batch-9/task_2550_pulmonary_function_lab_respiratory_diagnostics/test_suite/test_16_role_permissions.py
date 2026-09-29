"""Who may do what, and how the three authorisation rungs differ from each other.

The role model has three distinct refusals stacked at the top of the ladder: a
role the laboratory does not recognise at all, a recognised role that this
operation does not admit, and a recognised role presenting an identity that does
not back it.  Each earns its own code, and the segregation-of-duties rules add a
fourth refusal that no role change can talk its way out of.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STAFF_IDENTITY_MISMATCH,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_device_cleared,
    assert_device_quarantined,
    assert_page,
)
from test_helpers.constants import MORNING_CLOCK, UNKNOWN_UUID
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR,
    LAB_MANAGER,
    make_headers,
    make_ordering_physician_headers,
    make_technologist_headers,
)


class TestExclusiveOperationsAreNotShared:
    """Four roles, four operations that belong to somebody else.

    The role gate sits at the second rung, so none of these refusals depends on
    the target resource being in any particular state.
    """

    def test_each_role_is_refused_the_operations_that_belong_to_another(self, api):
        """The interpreter cannot hand the work to themselves; the manager can.

        PRD 2.1: "When the acting role is not among the roles authorised for the
        target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED`
        (HTTP 403)."

        PRD 2.1: "`LabManager` owns the configuration surface — registering
        devices, staff, reference equation sets and rescue medication lots — plus
        clearing quarantined devices back into service, assigning accepted studies
        to interpreting physicians, and driving the logical clock."

        PRD 2.1: "`InterpretingPhysician` signs and amends the reports assigned to
        them and does nothing else; an interpreting physician cannot assign work to
        themselves, because assignment belongs exclusively to `LabManager` and the
        interpreter is chosen by a selector rather than nominated."

        PRD 2.1: "`ComplianceAuditor` is read-only across the entire API with
        exactly one write: the witness attestation that a disability report cannot
        be signed without."

        Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
        """
        lab = fx.build_lab(api, interpreters=1)
        session = fx.build_accepted_session(api, lab)
        assignment = f.report_assignment_payload(session["version"])

        validate_error(
            api.create_device(f.device_payload("SPIRO-9"), lab.doc1),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_interpretation_report(
                session["id"], assignment, lab.roster.rad1
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_test_order(
                f.test_order_payload(lab.patient_id), COMPLIANCE_AUDITOR
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_reference_equation(
                f.reference_equation_payload(equation_code="GLI-X"), lab.tech1
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

        report = validate_success(
            api.create_interpretation_report(session["id"], assignment, LAB_MANAGER),
            expected_status=201,
        )
        assert report["interpreter_staff_id"] == lab.roster.rad1_id

        _, meta = validate_paginated(api.list_devices(LAB_MANAGER))
        assert_page(meta, total_count=1, has_more=False)


class TestPatientRegistrationIsShared:
    """One write is shared by exactly two roles, and sharing is exact."""

    def test_two_roles_may_register_a_patient_and_the_technologist_may_only_read(
        self, api
    ):
        """The refused role still holds the read surface it was granted.

        PRD 2.1: "`OrderingPhysician` drafts, revises, submits and cancels orders,
        and may register patients."

        PRD 2.1: "Patient registration is shared between `LabManager` and
        `OrderingPhysician`; order cancellation is shared between
        `OrderingPhysician` and `LabManager`; read access is broad but not uniform,
        and the authoritative per-endpoint role list is the table in §4 — in
        particular `OrderingPhysician` is not granted the staff,
        device-quality-event, maneuver, custody-event, challenge-run or rescue-lot
        read surfaces, and the rescue-lot read surface is further limited to
        `LabManager`, `Technologist` and `ComplianceAuditor`."

        Design: Corner/rbac/patient_registration_is_shared_while_the_testing_floor_is_not
        """
        fx.set_clock(api, MORNING_CLOCK)
        technologist = fx.register_technologist(api)
        physician = fx.register_ordering_physician(api)
        tech_headers = make_technologist_headers(technologist["id"])
        doc_headers = make_ordering_physician_headers(physician["id"])

        by_manager = validate_success(
            api.create_patient(f.patient_payload(), LAB_MANAGER), expected_status=201
        )
        assert by_manager["mrn"] == "MRN-7001"

        by_physician = validate_success(
            api.create_patient(
                f.patient_payload(
                    mrn="MRN-7002",
                    full_name="Bea Nolan",
                    birth_date="1979-11-02",
                    sex="FEMALE",
                    height_cm=162.0,
                    weight_kg=64.0,
                    smoking_status="NEVER",
                ),
                doc_headers,
            ),
            expected_status=201,
        )
        assert by_physician["mrn"] == "MRN-7002"

        validate_error(
            api.create_patient(
                f.patient_payload(
                    mrn="MRN-7003",
                    full_name="Cy Duarte",
                    birth_date="1990-04-19",
                    height_cm=180.0,
                    weight_kg=88.0,
                    smoking_status="CURRENT",
                ),
                tech_headers,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

        read_by_technologist = validate_success(
            api.get_patient(by_physician["id"], tech_headers)
        )
        assert read_by_technologist["mrn"] == "MRN-7002"
        assert read_by_technologist["full_name"] == "Bea Nolan"


class TestUndeclaredRoleHeader:
    """Rung 1 separates "not a role at all" from "the wrong role"."""

    def test_an_unrecognised_role_is_unauthenticated_and_a_wrong_one_is_forbidden(
        self, api
    ):
        """The same body earns 401, then 403, then 201 as the role changes.

        PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, declaring the capacity in which they
        act. If either header is absent, or if `X-User-Role` is not one of the five
        role names the laboratory recognises, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). The five roles are `LabManager`,
        `Technologist`, `OrderingPhysician`, `InterpretingPhysician` and
        `ComplianceAuditor`, spelled exactly as written."

        Design: Corner/rbac/an_undeclared_role_header_is_rejected_as_unauthenticated
        """
        fx.set_clock(api, MORNING_CLOCK)
        physician = fx.register_ordering_physician(api)
        doc_headers = make_ordering_physician_headers(physician["id"])
        fellow = make_headers("PulmonaryFellow", physician["id"])
        registration = f.technologist_payload(
            employee_code="T-050",
            full_name="Ari Fenn",
            credentialed_modalities=("SPIROMETRY",),
        )

        validate_error(
            api.create_staff(registration, fellow), ERR_UNAUTHENTICATED
        )
        validate_error(
            api.create_staff(registration, doc_headers), ERR_ROLE_NOT_PERMITTED
        )

        registered = validate_success(
            api.create_staff(registration, LAB_MANAGER), expected_status=201
        )
        assert registered["employee_code"] == "T-050"

        stored = validate_success(api.get_staff(registered["id"], LAB_MANAGER))
        assert stored["employee_code"] == "T-050"
        assert stored["role_type"] == "TECHNOLOGIST"


class TestEntityBackedRoleIdentity:
    """The identity assertion is checked before the path is even resolved."""

    def test_a_mismatched_and_an_unknown_staff_identity_are_refused_alike(self, api):
        """A body that is otherwise impeccable is still refused on identity alone.

        PRD 2.1: "When `X-User-Role` is `Technologist`, `X-User-ID` is the `id` of
        the acting `Staff` row, and that row's `role_type` must be `TECHNOLOGIST`;
        ownership checks on any resource that references a `Staff` row — for
        example the `technologist_staff_id` recorded on a study, or the
        `ordering_staff_id` recorded on an order — compare that foreign-key field
        to `X-User-ID`."

        PRD 2.1: "In all three cases, an `X-User-ID` that does not resolve to a
        `Staff` row at all, or that resolves to a `Staff` row whose `role_type`
        does not match the asserted role, is rejected with
        `ERR_STAFF_IDENTITY_MISMATCH` (HTTP 403), and that rejection happens before
        any existence check on identifiers appearing in the URL path."

        Design: Corner/rbac/entity_backed_roles_must_present_a_staff_row_of_the_matching_type
        """
        fx.set_clock(api, MORNING_CLOCK)
        technologist = fx.register_technologist(api)
        physician = fx.register_ordering_physician(api)
        device = fx.register_device(api)
        calibration = f.calibration_event_payload()

        validate_error(
            api.create_quality_event(
                device["id"],
                calibration,
                make_technologist_headers(physician["id"]),
            ),
            ERR_STAFF_IDENTITY_MISMATCH,
        )
        validate_error(
            api.create_quality_event(
                device["id"], calibration, make_technologist_headers(UNKNOWN_UUID)
            ),
            ERR_STAFF_IDENTITY_MISMATCH,
        )
        validate_error(
            api.create_quality_event(
                UNKNOWN_UUID, calibration, make_technologist_headers(UNKNOWN_UUID)
            ),
            ERR_STAFF_IDENTITY_MISMATCH,
        )

        untouched = validate_success(api.get_device(device["id"], LAB_MANAGER))
        assert untouched["status"] == "NEW"

        accepted = validate_success(
            api.create_quality_event(
                device["id"],
                calibration,
                make_technologist_headers(technologist["id"]),
            ),
            expected_status=201,
        )
        assert accepted["outcome"] == "PASS"
        assert_2dp(accepted["error_pct"], 0.00)

        promoted = validate_success(api.get_device(device["id"], LAB_MANAGER))
        assert promoted["status"] == "AVAILABLE"


def _a_quarantined_device_and_its_accuser(api):
    """SPIRO-1 condemned by T-001, who then records the clearing evidence himself.

    The hygiene pair is fitted too, because PRD 2.9 rung 36 puts
    ``ERR_INFECTION_CONTROL_INCOMPLETE`` "on both study scheduling and
    return-to-service", above the segregation rung this scenario is aiming at;
    without it the clearance request would never reach rung 42.  The filter and
    the disinfectant are not "clearing measurements" in the sense of PRD 3.3, so
    the accusing technologist may perform them himself.
    """
    fx.set_clock(api, MORNING_CLOCK)
    roster = fx.build_roster(api, second_technologist=True)
    device = fx.register_device(api)
    fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(2.848), roster.tech1
    )
    fx.append_quality_event(
        api, device["id"], f.filter_replacement_event_payload("F-1001"), roster.tech1
    )
    fx.append_quality_event(
        api, device["id"], f.disinfection_event_payload(25), roster.tech1
    )
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(), roster.tech1
    )
    fx.append_quality_event(
        api,
        device["id"],
        f.biologic_control_event_payload(roster.bcs_id),
        roster.tech1,
    )
    return roster, device["id"]


class TestQuarantineClearanceSegregation:
    """The measurement that condemned the device may not also redeem it."""

    def test_clearance_waits_for_a_second_technologist_to_repeat_both_measurements(
        self, api
    ):
        """Two impeccable clearing records are worth nothing while they are his own.

        PRD 2.10: "A technologist may never prove healthy a device their own
        failing measurement condemned. Returning a quarantined device to service
        requires two clearing quality records recorded after the quarantine, and
        each of them must have been performed by somebody other than the
        `quarantine_trigger_staff_id` the device is carrying; a violation is again
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD 3.3: "Fourth, neither of those two clearing measurements may have been
        performed by the technologist recorded in `quarantine_trigger_staff_id`;
        the person whose measurement condemned the device may not be the person
        whose measurement redeems it, and a violation reports
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/quarantine_clearance_requires_a_second_technologist
        """
        roster, device_id = _a_quarantined_device_and_its_accuser(api)
        clearance = f.return_to_service_payload(
            "Second technologist reproduced a passing calibration and control."
        )

        validate_error(
            api.return_device_to_service(device_id, clearance, LAB_MANAGER),
            ERR_SEGREGATION_OF_DUTIES,
        )

        still_condemned = validate_success(api.get_device(device_id, LAB_MANAGER))
        assert_device_quarantined(
            still_condemned,
            "CALIBRATION_FAILED",
            trigger_staff_id=roster.tech1_id,
            quarantined_at="2026-08-03T08:00:00Z",
        )

        fx.set_clock(api, "2026-08-03T10:00:00Z")
        second_calibration = fx.append_quality_event(
            api, device_id, f.calibration_event_payload(), roster.tech2
        )
        second_control = fx.append_quality_event(
            api,
            device_id,
            f.biologic_control_event_payload(roster.bcs_id),
            roster.tech2,
        )
        assert second_calibration["outcome"] == "PASS"
        assert second_control["outcome"] == "PASS"

        cleared = validate_success(
            api.return_device_to_service(device_id, clearance, LAB_MANAGER)
        )
        assert_device_cleared(cleared)

        reread = validate_success(api.get_device(device_id, LAB_MANAGER))
        assert_device_cleared(reread)
