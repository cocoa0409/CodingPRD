"""Response envelope shape, authentication, authorization, and peer-role RBAC."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID,
    make_coordinator_headers, make_caretaker_headers,
    make_clinic_staff_headers,
    create_caretaker, setup_cat_at_post_surgery, setup_kitten_in_foster,
    create_foster_home, create_cat,
    setup_caretaker_with_colony, setup_clinic_day_with_slots,
    create_foster_placement_payload, get_success_data,
)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and a `data`
        carrying "`error_id`" and "`message`".
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_cat(NON_EXISTENT_UUID, make_coordinator_headers())
        body = resp.json()
        assert resp.status_code == 404
        assert body.get("response_type") == "error"
        assert isinstance(body["data"].get("error_id"), str)
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str)
        assert len(body["data"]["message"].strip()) > 0
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.list_colonies({})  # no role headers at all
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestAuthorization:
    def test_err_forbidden_triggerable(self, api):
        """PRD §2.1: "A well-identified caller attempting an operation not granted
        to their role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /tnr/vouchers authorized role is ProgramCoordinator.

        Design: Corner/errors/err_forbidden_triggerable
        """
        ct, cth = create_caretaker()
        resp = api.create_voucher(
            {"caretaker_id": ct["id"], "face_value_cents": 1000,
             "funding_source": "MUNICIPAL_GRANT"},
            cth)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_clinic_staff_cannot_decide_pathway(self, api):
        """PRD §2.1: "A well-identified caller attempting an operation not granted
        to their role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /tnr/cats/{id}/decide-pathway authorized role is
        ProgramCoordinator only.

        Design: Corner/roles/clinic_staff_cannot_decide_pathway
        """
        sc = setup_cat_at_post_surgery()
        cat = sc["cat"]
        resp = api.decide_pathway(
            cat["id"],
            {"pathway": "RETURN_TO_FIELD", "expected_cat_version": cat["version"]},
            make_clinic_staff_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_coordinator_cannot_record_surgery(self, api):
        """PRD §2.1: "A well-identified caller attempting an operation not granted
        to their role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /tnr/surgery-records authorized role is ClinicStaff only.

        Design: Corner/roles/coordinator_cannot_record_surgery
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col)
        clinic, day, slots = setup_clinic_day_with_slots(base_capacity=1)
        from test_helpers import book_appointment
        appt, _ = book_appointment(cat, slots[0], day["id"], cth)
        get_success_data(api.mark_trapped(appt["id"], cth))
        get_success_data(api.check_in(appt["id"], make_clinic_staff_headers()))

        resp = api.create_surgery_record(
            {"appointment_id": appt["id"], "surgeon_initials": "PC",
             "ear_tipped": True, "rabies_vaccinated": True, "outcome": "STERILIZED"},
            make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_foster_volunteer_wrong_home_rejected(self, api):
        """PRD §3.6: "each requires the acting `FosterVolunteer` to operate their
        own home — the placement's home must match `X-User-ID`, else
        `ERR_OWNERSHIP_MISMATCH`"

        Design: Corner/roles/foster_volunteer_wrong_home_rejected
        """
        sc = setup_kitten_in_foster()
        other_home, other_vh = create_foster_home(volunteer_name="Home Two")
        resp = api.graduate_placement(sc["placement"]["id"], other_vh)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)
