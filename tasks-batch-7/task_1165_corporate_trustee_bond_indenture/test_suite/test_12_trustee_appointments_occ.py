"""Successor trustee appointments and optimistic concurrency: stale-version
rejection, sibling supersede, effectiveness timing, and the draft-invoice
void cascade (PRD §2.7, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    CLOCK_START, set_clock,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    create_annual_invoice, create_appointment, get_indenture,
    get_default_case, get_direction, get_fee_invoice,
    declare_default, confirm_default, create_direction,
    create_trustee_appointment_payload, create_direction_payload,
    get_success_data,
    make_platform_admin_headers, make_trust_officer_headers,
    make_trust_manager_headers,
)

ADMIN = make_platform_admin_headers("admin-1")
OFFICER = make_trust_officer_headers("officer-1")
MANAGER = make_trust_manager_headers("manager-1")


class TestTrusteeAppointmentOcc:
    def test_trustee_appointment_occ_and_supersede(self, api):
        """PRD §2.7: "A `POST /trustee-appointments` request must carry
        `expected_indenture_version` matching the target indenture's current
        `version`. Because creating an appointment supersedes any in-flight
        appointment on the same indenture (and advances the indenture's
        version), a writer whose view predates another writer's appointment
        is stale and is rejected with `ERR_STALE_VERSION`."
        PRD §3.9: "Creation snapshots the indenture's `current_trustee_ref`
        into `outgoing_trustee_ref`, supersedes any in-flight appointment on
        the same indenture — both `PROPOSED` and `ACCEPTED` siblings become
        `SUPERSEDED` — increments the indenture's `version` by one, and
        starts the appointment `PROPOSED`."

        Design: Corner/complexity_layers/occ_trustee_appointment_stale_version_and_supersede
        """
        indenture, tranche = create_active_indenture_with_tranche()
        observed = get_indenture(indenture["id"])
        observed_version = observed["version"]

        first = validate_success(api.create_trustee_appointment(
            create_trustee_appointment_payload(
                indenture["id"], expected_indenture_version=observed_version,
                incoming_trustee_ref="trustee-beta"),
            ADMIN), 201)
        assert first["status"] == "PROPOSED"

        # Replaying the same captured version is stale after the first create.
        resp = api.create_trustee_appointment(
            create_trustee_appointment_payload(
                indenture["id"], expected_indenture_version=observed_version,
                incoming_trustee_ref="trustee-gamma", reason="REMOVAL",
                proposed_effective_date="2026-10-01"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current_version = get_indenture(indenture["id"])["version"]
        second = validate_success(api.create_trustee_appointment(
            create_trustee_appointment_payload(
                indenture["id"], expected_indenture_version=current_version,
                incoming_trustee_ref="trustee-gamma", reason="REMOVAL",
                proposed_effective_date="2026-10-01"),
            ADMIN), 201)
        assert second["status"] == "PROPOSED"

        first_after = get_success_data(api.get_trustee_appointment(first["id"], ADMIN))
        assert first_after["status"] == "SUPERSEDED", "in-flight sibling superseded"
        final_version = get_indenture(indenture["id"])["version"]
        assert final_version == observed_version + 2, (
            "indenture version advanced by exactly 2 across the two "
            "successful creates")


class TestDirectionOcc:
    def test_direction_occ_and_supersede(self, api):
        """PRD §2.7: "A `POST /directions` request must carry
        `expected_default_case_version` matching the target default case's
        current `version`. Because creating a direction supersedes any
        `CIRCULATING` direction on the same case (and advances the case's
        version), a stale view is rejected with `ERR_STALE_VERSION`."
        PRD §3.5: "Opening a direction supersedes any `CIRCULATING` sibling
        on the same case (which becomes `SUPERSEDED`), increments the case's
        `version` by one, and starts the direction `CIRCULATING`"

        Design: Corner/complexity_layers/occ_direction_stale_case_and_supersede
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        observed_version = get_default_case(case["id"])["version"]

        first = validate_success(api.create_direction(
            create_direction_payload(
                case["id"], expected_default_case_version=observed_version,
                instruction_type="ACCELERATE"),
            OFFICER), 201)
        assert first["status"] == "CIRCULATING"

        resp = api.create_direction(
            create_direction_payload(
                case["id"], expected_default_case_version=observed_version,
                instruction_type="WAIVE_DEFAULT"),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current_version = get_default_case(case["id"])["version"]
        second = validate_success(api.create_direction(
            create_direction_payload(
                case["id"], expected_default_case_version=current_version,
                instruction_type="WAIVE_DEFAULT"),
            OFFICER), 201)
        assert second["status"] == "CIRCULATING"

        first_after = get_direction(first["id"])
        assert first_after["status"] == "SUPERSEDED", "circulating sibling superseded"


class TestAppointmentEffectTiming:
    def test_appointment_effect_timing_and_invoice_void_cascade(self, api):
        """PRD §3.9: "Effecting the transfer requires the logical clock's
        date to be on or after `proposed_effective_date`; an earlier attempt
        is rejected with `ERR_NOT_YET_EFFECTIVE`."
        PRD §3.9: "On effectiveness the appointment becomes `EFFECTIVE`, the
        indenture's `current_trustee_ref` is swapped to the
        `incoming_trustee_ref`, the indenture's `version` increments again,
        and every `DRAFT` fee invoice of the indenture is voided per §3.8."
        PRD §3.8: "when a trustee appointment on the indenture becomes
        `EFFECTIVE`, every invoice of that indenture still `DRAFT` moves to
        `VOID`."

        Design: Corner/validations/appointment_effect_timing_and_draft_invoice_void_cascade
        """
        set_clock(CLOCK_START)
        indenture, tranche = create_active_indenture_with_tranche(reset_clock=False)
        invoice = create_annual_invoice(indenture["id"], officer_id="officer-1")
        appointment = create_appointment(indenture, incoming_trustee_ref="trustee-beta",
                                         proposed_effective_date="2026-09-01")
        accepted = validate_success(api.accept_trustee_appointment(appointment["id"], ADMIN))
        assert accepted["status"] == "ACCEPTED"

        # Before the proposed date: rejected, appointment unchanged.
        resp = api.effect_trustee_appointment(appointment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_YET_EFFECTIVE)
        pending = get_success_data(api.get_trustee_appointment(appointment["id"], ADMIN))
        assert pending["status"] == "ACCEPTED"

        # On the proposed date itself (equality): the transfer completes.
        set_clock("2026-09-01T00:00:00Z")
        effected = validate_success(api.effect_trustee_appointment(appointment["id"], ADMIN))
        assert effected["status"] == "EFFECTIVE"

        indenture_after = get_indenture(indenture["id"])
        assert indenture_after["current_trustee_ref"] == "trustee-beta"
        invoice_after = get_fee_invoice(invoice["id"])
        assert invoice_after["status"] == "VOID", "draft invoice voided by succession"
