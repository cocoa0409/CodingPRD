"""Dangerous-goods declarations, segregation of duties, and the build-up gate."""
from test_helpers import (
    ApiErrorId,
    accept_dg_declaration,
    create_build_up_plan,
    create_dg_declaration_payload,
    file_dg_declaration,
    get_booking,
    make_accepted_booking,
    make_booking,
    make_dg_inspector_headers,
    make_flight,
    make_open_flight,
    make_uld_type_and_unit,
    reject_dg_declaration,
    validate_error,
    validate_success,
)
from test_helpers import DG_INSPECTOR_USER, FWD_USER_1


class TestDeclarationFiling:
    def test_dg_declaration_invalid_enum_packing_group(
        self, api, forwarder_agent_headers
    ):
        """PRD §3.3: "a `packing_group` of exactly `I`, `II`, or `III`"
        PRD §2.7: "Required fields must be present, types must be valid, and
        enum fields must be within their declared values ... Any violation
        yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/dg_declaration_invalid_enum_packing_group
        """
        flight = make_flight(flight_number="CA306", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], shipper_ref="SHP-E1", commodity_code="DG",
            gross_weight_kg=50, volume_m3=1, is_dangerous_goods=True,
        )
        res = api.create_dg_declaration(
            booking["id"],
            create_dg_declaration_payload(packing_group="IV"),
            forwarder_agent_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_dg_declaration_on_non_dg_booking_not_applicable(
        self, api, forwarder_agent_headers
    ):
        """PRD §3.3: "a declaration against a booking with `is_dangerous_goods`
        false is incoherent and rejected with `ERR_DG_NOT_APPLICABLE`
        (HTTP 422)"

        Design: Corner/validations/dg_declaration_on_non_dg_booking_not_applicable
        """
        flight = make_flight(flight_number="CA319", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], shipper_ref="SHP-N1", gross_weight_kg=50, volume_m3=1
        )
        res = api.create_dg_declaration(
            booking["id"], create_dg_declaration_payload(), forwarder_agent_headers
        )
        validate_error(res, ApiErrorId.ERR_DG_NOT_APPLICABLE)

    def test_second_pending_dg_declaration_rejected(self, api, forwarder_agent_headers):
        """PRD §3.3: "A booking may carry at most one declaration in
        `PENDING_CHECK` at a time; a second filing while a check is outstanding
        is refused with `ERR_DG_CHECK_ALREADY_PENDING`."

        Design: Corner/errors/second_pending_dg_declaration_rejected
        """
        flight = make_flight(flight_number="CA332", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], shipper_ref="SHP-DG3", commodity_code="DG",
            gross_weight_kg=50, volume_m3=1, is_dangerous_goods=True,
        )
        file_dg_declaration(booking["id"])
        res = api.create_dg_declaration(
            booking["id"],
            create_dg_declaration_payload(
                un_number="UN1845", dg_class="9", packing_group="III",
                declaration_doc_ref="DGD-2",
            ),
            forwarder_agent_headers,
        )
        validate_error(res, ApiErrorId.ERR_DG_CHECK_ALREADY_PENDING)


class TestSegregatedCheck:
    def test_sod_self_check_forbidden(self, api):
        """PRD §3.3: "the acting `X-User-ID` must differ from the booking's
        `created_by_user_id`, and a self-check is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/sod_self_check_forbidden
        """
        flight = make_flight(flight_number="CA327", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], user_id=FWD_USER_1, shipper_ref="SHP-SOD",
            commodity_code="DG", gross_weight_kg=50, volume_m3=1,
            is_dangerous_goods=True,
        )
        declaration = file_dg_declaration(booking["id"], user_id=FWD_USER_1)
        res = api.accept_dg_declaration(
            declaration["id"], make_dg_inspector_headers(FWD_USER_1)
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)
        accepted = accept_dg_declaration(declaration["id"], DG_INSPECTOR_USER)
        assert accepted["status"] == "ACCEPTED", (
            "An independent inspector must be able to complete the check"
        )

    def test_dg_declaration_resubmission_loop(self, api):
        """PRD §3.3: "A rejected declaration is terminal — the forwarder's
        remedy is to correct the paperwork and file a fresh declaration on the
        same booking, which is permitted once no `PENDING_CHECK` declaration
        remains."

        Design: Corner/state_machines/dg_declaration_resubmission_loop
        """
        flight = make_flight(flight_number="CA310", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], user_id=FWD_USER_1, shipper_ref="SHP-DG1",
            commodity_code="DG", gross_weight_kg=50, volume_m3=1,
            is_dangerous_goods=True,
        )
        first = file_dg_declaration(
            booking["id"], user_id=FWD_USER_1, declaration_doc_ref="DGD-OLD"
        )
        rejected = reject_dg_declaration(
            first["id"], DG_INSPECTOR_USER, "illegible packing group"
        )
        assert rejected["status"] == "REJECTED", (
            "Rejection is terminal for that declaration row"
        )
        second = file_dg_declaration(
            booking["id"], user_id=FWD_USER_1, declaration_doc_ref="DGD-NEW"
        )
        assert second["status"] == "PENDING_CHECK", (
            "Resubmission opens a fresh check"
        )
        accepted = accept_dg_declaration(second["id"], DG_INSPECTOR_USER)
        assert accepted["status"] == "ACCEPTED"


class TestBuildUpDocumentationGate:
    def test_assign_dg_booking_without_accepted_declaration(
        self, api, ramp_operator_headers
    ):
        """PRD §3.3: "an `is_dangerous_goods` booking may only be assigned into
        a plan if an `ACCEPTED` declaration exists for it. Assigning one without
        that acceptance is rejected with `ERR_DG_NOT_ACCEPTED` (HTTP 409)."

        Design: Corner/errors/assign_dg_booking_without_accepted_declaration
        """
        flight = make_open_flight(flight_number="CA331", max_payload_kg=5000)
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00116CA")
        booking = make_accepted_booking(
            flight["id"], user_id=FWD_USER_1, shipper_ref="SHP-DG2",
            commodity_code="DG", gross_weight_kg=50, volume_m3=1,
            is_dangerous_goods=True,
        )
        declaration = file_dg_declaration(booking["id"], user_id=FWD_USER_1)
        plan = create_build_up_plan(flight["id"], uld["id"])
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": booking["id"],
                "expected_build_up_plan_version": plan["version"],
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_DG_NOT_ACCEPTED)
        accept_dg_declaration(declaration["id"], DG_INSPECTOR_USER)
        updated = validate_success(
            api.assign_booking_to_plan(
                plan["id"],
                {
                    "booking_id": booking["id"],
                    "expected_build_up_plan_version": plan["version"],
                },
                ramp_operator_headers,
            )
        )
        assert updated["total_weight_kg"] == 50, (
            "Once the declaration is ACCEPTED the identical assign succeeds"
        )
        assert get_booking(booking["id"], ramp_operator_headers)["status"] == "BUILT_UP"
