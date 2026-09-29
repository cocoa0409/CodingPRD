"""Two operations here are gated on a field that lives on another entity.

Booking a study reads the device's status, and signing a report reads the parent
study's chain-of-custody status.  In both cases the request payload is identical
across the refusal and the success, so only the foreign field can explain the
difference.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CUSTODY_NOT_SEALED, ERR_DEVICE_NOT_AVAILABLE
from test_helpers.assertions import (
    assert_3dp,
    assert_device_cleared,
    assert_device_quarantined,
    assert_unsigned_report,
)
from test_helpers.test_users import LAB_MANAGER

BOOKING_START = "2026-08-03T10:00:00Z"
BOOKING_END = "2026-08-03T10:30:00Z"


def _quarantined_device_and_a_waiting_order(api):
    """A device condemned by T-001's own calibration, with an order left at READY."""
    lab = fx.build_lab(api, second_technologist=True)
    order = fx.build_ready_order(api, lab)
    fx.append_quality_event(
        api, lab.device_id, f.calibration_event_payload(2.848), lab.tech1
    )
    return lab, order


def _attempt_to_book(api, lab, order):
    return api.create_test_session(
        f.test_session_payload(order["id"], lab.device_id, BOOKING_START, BOOKING_END),
        lab.tech1,
    )


class TestSchedulingGatedOnDeviceStatus:
    """A study cannot be booked onto a device the laboratory has withdrawn."""

    def test_a_quarantined_device_refuses_the_booking_and_leaves_the_order_alone(self, api):
        """The order stays exactly where it was, at READY and at its old version.

        PRD 2.9: "**Device state admits the operation** —
        `ERR_DEVICE_NOT_AVAILABLE` (409): study scheduling and maneuver appending
        require `AVAILABLE`; return-to-service requires `QUARANTINED`."

        Design: Difficulty/cross_entity_state_dependency/session_creation_gated_on_foreign_device_status_quarantined_then_cleared
        """
        lab, order = _quarantined_device_and_a_waiting_order(api)

        refused = _attempt_to_book(api, lab, order)

        validate_error(refused, ERR_DEVICE_NOT_AVAILABLE)
        device = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert_device_quarantined(
            device, "CALIBRATION_FAILED", trigger_staff_id=lab.tech1_id
        )
        untouched = validate_success(api.get_test_order(order["id"], lab.doc1))
        assert untouched["status"] == "READY"
        assert untouched["version"] == order["version"]

    def test_clearing_that_same_field_admits_the_identical_booking(self, api):
        """Return-to-service flips the device's status and the booking then succeeds.

        PRD 3.3: "When all four hold, the `status` returns to `AVAILABLE` and
        `quarantined_at`, `quarantine_reason` and `quarantine_trigger_staff_id`
        are all cleared to null."

        Design: Difficulty/cross_entity_state_dependency/session_creation_gated_on_foreign_device_status_quarantined_then_cleared
        """
        lab, order = _quarantined_device_and_a_waiting_order(api)
        validate_error(_attempt_to_book(api, lab, order), ERR_DEVICE_NOT_AVAILABLE)

        fx.set_clock(api, "2026-08-03T09:00:00Z")
        fx.append_quality_event(
            api, lab.device_id, f.calibration_event_payload(2.764), lab.roster.tech2
        )
        fx.append_quality_event(
            api,
            lab.device_id,
            f.biologic_control_event_payload(lab.bcs_id, 3.850, 5.100),
            lab.roster.tech2,
        )
        cleared = validate_success(
            api.return_device_to_service(
                lab.device_id, f.return_to_service_payload(), LAB_MANAGER
            )
        )
        assert_device_cleared(cleared)

        booked = validate_success(_attempt_to_book(api, lab, order), expected_status=201)
        assert booked["session_status"] == "SCHEDULED"
        assert booked["custody_status"] == "NOT_APPLICABLE"
        assert_3dp(booked["predicted_fev1_l"], 4.000)
        assert_3dp(booked["lln_fev1_l"], 3.145)
        assert_3dp(booked["ratio_lln"], 0.700)
        in_testing = validate_success(api.get_test_order(order["id"], lab.doc1))
        assert in_testing["status"] == "IN_TESTING"


def _two_sealed_occupational_studies(api):
    """Two employer-facing studies, both accepted and both sitting at CUSTODY_SEALED."""
    lab = fx.build_lab(
        api,
        clock="2026-08-03T10:00:00Z",
        device_codes=("SPIRO-1", "SPIRO-2"),
        interpreters=1,
    )
    closed = []
    orders = []
    windows = (
        ("2026-08-03T11:00:00Z", "2026-08-03T11:30:00Z"),
        ("2026-08-03T12:00:00Z", "2026-08-03T12:30:00Z"),
    )
    for index, (start, end) in enumerate(windows):
        order = fx.build_ready_order(
            api,
            lab,
            indication_code="OCCUPATIONAL_SURVEILLANCE_ANNUAL",
            test_context="OCCUPATIONAL_SURVEILLANCE",
        )
        session = fx.schedule_session(
            api, order["id"], lab.device_ids[index], lab.tech1, start, end
        )
        fx.verify_identity(api, session["id"], lab.tech1)
        fx.apply_seal(api, session["id"], lab.tech1, seal_serial=f"SEAL-900{index + 1}")
        fx.append_maneuver_series(api, session["id"], lab.tech1)
        closed.append(fx.finalize_quality(api, session["id"], lab.tech1))
        orders.append(order)
    return lab, orders, closed


class TestSigningGatedOnSessionCustodyStatus:
    """The report's own state says nothing about the seal on the study."""

    def test_a_sealed_study_signs_and_carries_its_order_to_completion(self, api):
        """CUSTODY_SEALED is the one custody value that admits a signature.

        PRD 3.8: "The two dimensions meet at exactly one place: report signing.
        For a study whose order `test_context` is anything other than
        `ROUTINE_CLINICAL`, `custody_status` must be exactly `CUSTODY_SEALED` at
        signing time, and any other value — including `CUSTODY_BROKEN` and
        including a chain that simply never got as far as sealing — reports
        `ERR_CUSTODY_NOT_SEALED`."

        Design: Difficulty/cross_entity_state_dependency/report_signing_gated_on_foreign_session_custody_status_sealed_vs_broken
        """
        lab, orders, closed = _two_sealed_occupational_studies(api)
        assert closed[0]["custody_status"] == "CUSTODY_SEALED"

        report = fx.assign_report(api, closed[0]["id"], closed[0]["version"])
        signed = fx.sign_report(api, report["id"], lab.roster.rad1)

        assert signed["status"] == "SIGNED"
        study = validate_success(api.get_test_session(closed[0]["id"], lab.tech1))
        assert study["session_status"] == "REPORTED"
        order = validate_success(api.get_test_order(orders[0]["id"], lab.doc1))
        assert order["status"] == "COMPLETED"

    def test_a_broken_seal_forecloses_signing_the_report_on_that_study(self, api):
        """The seal is broken on one dimension and the signature dies on the other.

        PRD 3.8: "The sequence is one-way: `CUSTODY_BROKEN` has no successor, so
        breaking a seal permanently forecloses signing the report for any
        non-routine study, and the only remedy is to run the study again."

        Design: Difficulty/cross_entity_state_dependency/report_signing_gated_on_foreign_session_custody_status_sealed_vs_broken
        """
        lab, orders, closed = _two_sealed_occupational_studies(api)
        first = fx.assign_report(api, closed[0]["id"], closed[0]["version"])
        fx.sign_report(api, first["id"], lab.roster.rad1)

        second = fx.assign_report(api, closed[1]["id"], closed[1]["version"])
        fx.append_custody_event(
            api, closed[1]["id"], f.seal_broken_payload("SEAL-9002"), lab.tech1
        )
        broken = validate_success(api.get_test_session(closed[1]["id"], lab.tech1))
        assert broken["custody_status"] == "CUSTODY_BROKEN"
        assert broken["session_status"] == "ACCEPTED"

        refused = api.sign_interpretation_report(
            second["id"], f.sign_report_payload(), lab.roster.rad1
        )

        validate_error(refused, ERR_CUSTODY_NOT_SEALED)
        unsigned = validate_success(
            api.get_interpretation_report(second["id"], lab.roster.rad1)
        )
        assert unsigned["status"] == "ASSIGNED"
        assert_unsigned_report(unsigned)
        still_open = validate_success(api.get_test_session(closed[1]["id"], lab.tech1))
        assert still_open["session_status"] == "ACCEPTED"
        order2 = validate_success(api.get_test_order(orders[1]["id"], lab.doc1))
        assert order2["status"] == "IN_TESTING"
        interpreter = validate_success(api.get_staff(lab.roster.rad1_id, LAB_MANAGER))
        assert interpreter["open_report_count"] == 1
        patient = validate_success(api.get_patient(lab.patient_id, LAB_MANAGER))
        assert patient["completed_order_count"] == 1
