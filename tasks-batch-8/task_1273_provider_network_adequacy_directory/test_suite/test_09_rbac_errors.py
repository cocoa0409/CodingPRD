"""RBAC denials, auth-header enforcement, and error-code sweeps (PRD §2.1, §2.7, §5)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_region_payload, create_complaint_payload, create_correction_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, create_member, create_probe, create_cycle,
    create_evaluation, finalize_evaluation, record_for_listing, respond_record,
    setup_listed_network, setup_complaint, confirm_complaint,
    make_member_headers, make_provider_rep_headers,
)

NM = TEST_USERS["network_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestRbacDenials:
    def test_member_cannot_create_region_forbidden(self, api):
        """PRD §2.1: "A request whose role is not listed on the endpoint's
        authorized-role set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST /network/regions — Create a service region — NetworkManager".

        Design: Corner/rbac/member_cannot_create_region_forbidden
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_region(
            create_region_payload(county_fips="06107", name="Nope",
                                  enrolled_member_count=1),
            make_member_headers("some-member-id"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_providerrep_cannot_respond_for_foreign_listing(self, api):
        """PRD §3.5: "A `ProviderRep` responds to attestation outreach on behalf of the
        provider they represent — the call's `X-User-ID` must equal the `id` of the
        `Provider` that owns the record's listing, else `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/providerrep_cannot_respond_for_foreign_listing
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06111", name="Placer2")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        pa = create_provider(legal_name="PA87")
        pb = create_provider(legal_name="PB88")
        loca = create_location(pa["id"], region["id"], address_line="87 A St")
        la = publish_listing(create_listing(pa["id"], loca["id"], display_name="A87",
                                            phone="555-0187")["id"])
        cycle = create_cycle(cycle_label="T6")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        reca = record_for_listing(cycle["id"], la["id"])
        resp = api.respond_attestation_record(
            reca["id"], {"data_accurate": True}, make_provider_rep_headers(pb["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_member_cannot_adjudicate_complaint_forbidden(self, api):
        """PRD §2.1: "A request whose role is not listed on the endpoint's
        authorized-role set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST /network/complaints/{id}/adjudicate — ComplianceOfficer confirms
        or dismisses a complaint — ComplianceOfficer".

        Design: Corner/rbac/member_cannot_adjudicate_complaint_forbidden
        """
        ctx = setup_listed_network(county_fips="06115", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L91",
                                                      "phone": "555-0191"})
        filed = setup_complaint(ctx["region"], ctx["listing"], error_type="OTHER",
                                description="x")
        resp = api.adjudicate_complaint(
            filed["complaint"]["id"], {"outcome": "UNFOUNDED"},
            make_member_headers(filed["member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and `X-User-Role`.
        The `X-User-Role` value must be exactly one of `NetworkManager`,
        `ComplianceOfficer`, `Regulator`, `ProviderRep`, or `Member`. A request missing
        either header, or carrying an unrecognized role string, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        create_region(county_fips="06117", name="Solano2", enrolled_member_count=1)
        resp = api_client._request("GET", "/network/regions", headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFoundSweep:
    def test_resource_get_nonexistent_ids_return_not_found_sweep(self, api):
        """PRD §2.7: "Next, path and body-referenced identifiers are resolved
        left-to-right (`ERR_REGION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`,
        `ERR_PROVIDER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
        `ERR_ATTESTATION_RECORD_NOT_FOUND`, `ERR_PROBE_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`,
        `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_CORRECTION_NOT_FOUND`)."

        Design: Corner/errors/resource_get_nonexistent_ids_return_not_found_sweep
        """
        set_clock("2026-05-01T00:00:00Z")
        missing = "00000000-0000-4000-8000-000000000010"
        cases = [
            (api.get_standard, ApiErrorId.ERR_STANDARD_NOT_FOUND),
            (api.get_provider, ApiErrorId.ERR_PROVIDER_NOT_FOUND),
            (api.get_location, ApiErrorId.ERR_LOCATION_NOT_FOUND),
            (api.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api.get_cycle, ApiErrorId.ERR_CYCLE_NOT_FOUND),
            (api.get_attestation_record, ApiErrorId.ERR_ATTESTATION_RECORD_NOT_FOUND),
            (api.get_probe, ApiErrorId.ERR_PROBE_NOT_FOUND),
            (api.get_evaluation, ApiErrorId.ERR_EVALUATION_NOT_FOUND),
            (api.get_access_plan_request, ApiErrorId.ERR_ACCESS_PLAN_REQUEST_NOT_FOUND),
            (api.get_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(missing, NM)
            validate_error(resp, error_id)
            assert resp.status_code == 404, f"{error_id} must be HTTP 404"


class TestTerminalStateDoubleTransitions:
    def test_terminal_state_double_transitions_rejected_sweep(self, api):
        """PRD §3.5: "Recording against a probe already in `RECORDED` is rejected with
        `ERR_PROBE_INVALID_STATE`."
        PRD §3.7: "Finalizing an evaluation not in `OPEN` is rejected with
        `ERR_EVALUATION_INVALID_STATE`."
        PRD §3.6: "A `ComplianceOfficer` adjudicates an `OPEN` complaint (else
        `ERR_COMPLAINT_NOT_OPEN`)."
        PRD §3.6: "The correction must be in `SUBMITTED` (else
        `ERR_CORRECTION_NOT_VERIFIABLE`)."
        PRD §3.5: "Any other combination — responding twice, responding after the record
        has already been cancelled, responding while the cycle is still `SCHEDULED` — is
        rejected with `ERR_RECORD_NOT_RESPONDABLE`."

        Design: Corner/errors/terminal_state_double_transitions_rejected_sweep
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_listed_network(county_fips="06089", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L77",
                                                      "phone": "555-0177"})
        listing = ctx["listing"]
        # recorded probe (terminal RECORDED)
        probe = create_probe(listing["id"], requested_date="2026-04-20")
        validate_success(api.record_probe(
            probe["id"], {"outcome": "KEPT", "offered_appointment_date": "2026-04-22"}, NM))
        # finalized evaluation (terminal FINALIZED)
        ev = create_evaluation(measurement_period="SW", period_start_date="2026-04-01",
                               period_end_date="2026-04-30")
        finalize_evaluation(ev["id"])
        # unfounded complaint (terminal UNFOUNDED)
        filed = setup_complaint(ctx["region"], listing, error_type="OTHER",
                                observed_date="2026-04-25", description="misc")
        validate_success(api.adjudicate_complaint(
            filed["complaint"]["id"],
            {"outcome": "UNFOUNDED", "notes": "no error present"}, CO))
        # verified manual correction (terminal VERIFIED)
        correction = validate_success(api.create_correction(
            create_correction_payload(listing["id"], changes={"phone": "555-0178"}), NM),
            expected_status=201)
        validate_success(api.verify_correction(correction["id"], {"approve": True}, CO))
        # attested record in an open cycle (terminal ATTESTED)
        cycle = create_cycle(cycle_label="T5", open_date="2026-04-01",
                             due_date="2026-04-10", outreach_close_date="2026-04-20")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        record = record_for_listing(cycle["id"], listing["id"])
        respond_record(record["id"], ctx["provider"]["id"], data_accurate=True)

        e1 = api.record_probe(probe["id"], {"outcome": "UNREACHABLE"}, NM)
        validate_error(e1, ApiErrorId.ERR_PROBE_INVALID_STATE)
        e2 = api.finalize_evaluation(ev["id"], NM)
        validate_error(e2, ApiErrorId.ERR_EVALUATION_INVALID_STATE)
        e3 = api.adjudicate_complaint(filed["complaint"]["id"],
                                      {"outcome": "UNFOUNDED"}, CO)
        validate_error(e3, ApiErrorId.ERR_COMPLAINT_NOT_OPEN)
        e4 = api.verify_correction(correction["id"], {"approve": True}, CO)
        validate_error(e4, ApiErrorId.ERR_CORRECTION_NOT_VERIFIABLE)
        e5 = api.respond_attestation_record(
            record["id"], {"data_accurate": True},
            make_provider_rep_headers(ctx["provider"]["id"]))
        validate_error(e5, ApiErrorId.ERR_RECORD_NOT_RESPONDABLE)
