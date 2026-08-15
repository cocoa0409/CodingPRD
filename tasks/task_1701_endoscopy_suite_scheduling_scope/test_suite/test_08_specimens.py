"""Specimen chain of custody: collect, label, handoff, receive, result, reject."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_instants_equal,
    assert_specimen,
    collect_specimen,
    create_in_progress_booking,
    handoff_specimen,
    label_specimen,
    make_pathology_headers,
    make_registry,
    setup_in_progress_with_specimen,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]


class TestCustodyHappyPath:
    def test_specimen_chain_of_custody_happy_path(self, api):
        """PRD §3.8: "The specimen is born `COLLECTED`, its `collected_at` stamped
        to the current logical time — that stamp anchors every later custody
        window — and its `patient_id` denormalized from the booking for
        traceability."
        PRD §3.8: "Either the `Endoscopist` or `PathologyStaff` may label; the
        specimen moves to `LABELED` with `labeled_at` stamped and `labeled_by` set
        from the caller."
        PRD §3.8: "the specimen moves to `IN_TRANSIT` with `handed_off_at` stamped
        and `handed_off_by` set from the caller."
        PRD §3.8: "Success stamps `received_at` and records `received_by`,
        settling the specimen at `RECEIVED_BY_LAB`."
        PRD §3.8: "the request carries the `adenoma_confirmed` pathology flag,
        `resulted_at` is stamped, and the specimen settles at `RESULTED`."

        Design: Corner/state_machines/specimen_chain_of_custody_happy_path
        """
        fx = setup_in_progress_with_specimen(mrn="MRN-SP")
        booking, reg_patient, dr1 = fx["booking"], fx["patient"], fx["provider"]
        sp = collect_specimen(booking["id"], dr1["id"], specimen_type="POLYP",
                              container_count=2)
        assert_specimen(sp)
        assert sp["status"] == "COLLECTED"
        assert sp["patient_id"] == reg_patient["id"], "denormalized from the booking"
        assert_instants_equal(sp["collected_at"], "2026-08-03T09:00:00Z")

        data = validate_success(api.label_specimen(
            sp["id"], {"X-User-ID": dr1["id"], "X-User-Role": "Endoscopist",
                       "Content-Type": "application/json"}), 200)
        assert data["status"] == "LABELED"
        assert data["labeled_by"] == dr1["id"]

        data = validate_success(api.handoff_specimen(
            sp["id"], {"courier_id": "courier-7"}, make_pathology_headers("lab-1")), 200)
        assert data["status"] == "IN_TRANSIT"
        assert data["courier_id"] == "courier-7"
        assert data["handed_off_by"] == "lab-1"

        advance_clock("2026-08-03T10:30:00Z")
        data = validate_success(api.receive_specimen(
            sp["id"], make_pathology_headers("lab-2")), 200)
        assert data["status"] == "RECEIVED_BY_LAB"
        assert data["received_by"] == "lab-2"

        data = validate_success(api.result_specimen(
            sp["id"], {"adenoma_confirmed": True}, make_pathology_headers("lab-2")), 200)
        assert data["status"] == "RESULTED"
        assert data["adenoma_confirmed"] is True


class TestCustodyOrderGates:
    def test_specimen_handoff_before_label_rejected(self, api):
        """PRD §3.8: "Courier handoff belongs to `PathologyStaff` and is legal
        only from `LABELED` (`ERR_SPECIMEN_NOT_LABELED`)."

        Design: Corner/state_machines/specimen_handoff_before_label_rejected
        """
        fx = setup_in_progress_with_specimen(mrn="MRN-HL")
        sp = collect_specimen(fx["booking"]["id"], fx["provider"]["id"],
                              specimen_type="BIOPSY")
        resp = api.handoff_specimen(sp["id"], {"courier_id": "courier-7"},
                                    make_pathology_headers("lab-1"))
        validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_LABELED)
        assert validate_success(api.get_specimen(sp["id"], ADMIN))["status"] == "COLLECTED"

    def test_specimen_receive_before_handoff_rejected(self, api):
        """PRD §3.8: "Laboratory receipt, again `PathologyStaff`, requires
        `IN_TRANSIT` (`ERR_SPECIMEN_NOT_IN_TRANSIT`)".

        Design: Corner/state_machines/specimen_receive_before_handoff_rejected
        """
        fx = setup_in_progress_with_specimen(mrn="MRN-RV")
        sp = collect_specimen(fx["booking"]["id"], fx["provider"]["id"],
                              specimen_type="BIOPSY")
        label_specimen(sp["id"])
        resp = api.receive_specimen(sp["id"], make_pathology_headers("lab-1"))
        validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_IN_TRANSIT)
        assert validate_success(api.get_specimen(sp["id"], ADMIN))["status"] == "LABELED"

    def test_specimen_result_before_receive_rejected(self, api):
        """PRD §3.8: "Result recording by `PathologyStaff` requires
        `RECEIVED_BY_LAB` (`ERR_SPECIMEN_NOT_RECEIVED`)".

        Design: Corner/state_machines/specimen_result_before_receive_rejected
        """
        fx = setup_in_progress_with_specimen(mrn="MRN-RS")
        sp = collect_specimen(fx["booking"]["id"], fx["provider"]["id"])
        label_specimen(sp["id"])
        handoff_specimen(sp["id"], courier_id="courier-1")
        resp = api.result_specimen(sp["id"], {"adenoma_confirmed": True},
                                   make_pathology_headers("lab-1"))
        validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_RECEIVED)
        assert validate_success(api.get_specimen(sp["id"], ADMIN))["status"] == "IN_TRANSIT"

    def test_specimen_reject_from_transit_terminal(self, api):
        """PRD §3.8: "Rejection by `PathologyStaff` is available while the
        specimen is `LABELED` or `IN_TRANSIT` — after receipt or result the option
        is gone (`ERR_SPECIMEN_TERMINAL`) — storing the supplied `reason` into
        `reject_reason` and settling at `REJECTED_BY_LAB`."

        Design: Corner/state_machines/specimen_reject_from_transit_terminal
        """
        fx = setup_in_progress_with_specimen(mrn="MRN-RJ")
        sp = collect_specimen(fx["booking"]["id"], fx["provider"]["id"],
                              specimen_type="OTHER")
        label_specimen(sp["id"])
        handoff_specimen(sp["id"], courier_id="courier-2")
        data = validate_success(api.reject_specimen(
            sp["id"], {"reason": "container broken"}, make_pathology_headers("lab-2")), 200)
        assert data["status"] == "REJECTED_BY_LAB"
        assert data["reject_reason"] == "container broken"
        resp = api.receive_specimen(sp["id"], make_pathology_headers("lab-2"))
        validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_IN_TRANSIT)


class TestCustodyWindows:
    def _two_specimens_in_transit(self):
        fx = setup_in_progress_with_specimen(mrn="MRN-TW")
        booking, dr1 = fx["booking"], fx["provider"]
        advance_clock("2026-08-03T09:10:00Z")
        sp1 = collect_specimen(booking["id"], dr1["id"], specimen_type="POLYP")
        sp2 = collect_specimen(booking["id"], dr1["id"], specimen_type="BIOPSY")
        label_specimen(sp1["id"])
        label_specimen(sp2["id"])
        handoff_specimen(sp1["id"], courier_id="courier-1")
        handoff_specimen(sp2["id"], courier_id="courier-1")
        return sp1, sp2

    def test_specimen_transport_120_minute_boundary(self, api):
        """PRD §3.8: "receipt must occur no later than 120 minutes after
        `collected_at`, inclusive — a later receipt is refused with
        `ERR_TRANSPORT_WINDOW_EXCEEDED`."

        Design: Corner/validations/specimen_transport_120_minute_boundary
        """
        sp1, sp2 = self._two_specimens_in_transit()
        advance_clock("2026-08-03T11:10:00Z")  # exactly +120 minutes
        data = validate_success(api.receive_specimen(
            sp1["id"], make_pathology_headers("lab-2")), 200)
        assert data["status"] == "RECEIVED_BY_LAB"
        advance_clock("2026-08-03T11:11:00Z")  # +121 minutes
        resp = api.receive_specimen(sp2["id"], make_pathology_headers("lab-2"))
        validate_error(resp, ApiErrorId.ERR_TRANSPORT_WINDOW_EXCEEDED)
        data = validate_success(api.reject_specimen(
            sp2["id"], {"reason": "transport window exceeded"},
            make_pathology_headers("lab-2")), 200)
        assert data["status"] == "REJECTED_BY_LAB"
        assert data["reject_reason"] == "transport window exceeded"

    def test_label_window_15_minute_boundary(self, api):
        """PRD §3.8: "Labeling must happen fast: within fifteen minutes of
        `collected_at`, inclusive — a labeling attempted later is refused with
        `ERR_LABEL_WINDOW_EXCEEDED`."

        Design: Corner/validations/label_window_15_minute_boundary
        """
        fx = setup_in_progress_with_specimen(mrn="MRN-LW")
        booking, dr1 = fx["booking"], fx["provider"]
        advance_clock("2026-08-03T09:10:00Z")
        spa = collect_specimen(booking["id"], dr1["id"], specimen_type="POLYP")
        spb = collect_specimen(booking["id"], dr1["id"], specimen_type="BIOPSY")
        advance_clock("2026-08-03T09:25:00Z")  # exactly +15 minutes
        data = validate_success(api.label_specimen(
            spa["id"], make_pathology_headers("lab-1")), 200)
        assert data["status"] == "LABELED"
        advance_clock("2026-08-03T09:26:00Z")  # +16 minutes
        resp = api.label_specimen(spb["id"], make_pathology_headers("lab-1"))
        validate_error(resp, ApiErrorId.ERR_LABEL_WINDOW_EXCEEDED)
        assert validate_success(api.get_specimen(spb["id"], ADMIN))["status"] == "COLLECTED"

    def test_specimen_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/specimen_not_found_returns_404
        """
        resp = api.get_specimen(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_FOUND)
