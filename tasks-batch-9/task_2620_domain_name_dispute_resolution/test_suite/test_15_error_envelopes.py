"""Path scoping across sibling cases, and the one envelope every refusal speaks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CASE_MANAGER,
    PROVIDER_ADMIN,
    admit_registrar,
    api_client,
    assert_all_mandatory_grounds,
    build_docket,
    clear_compliance,
    complainant_payload,
    domain_payload,
    file_complaint,
    first_verification,
    get_success_data,
    make_registrar_headers,
    panelist_payload,
    post_ledger_line,
    read_case,
    read_domain,
    register_domain,
    validate_error,
    validate_paginated,
    verification_response_payload,
)

NESTED_DOCKET = {
    "iana_id": "IANA-9034",
    "domain_name": "nested-a.example",
    "legal_name": "Nested Ltd",
    "country_code": "GB",
    "registrar_name": "Nested Registrar",
}


class TestNestedIdentifiersAreScopedToTheCaseInThePath:
    def _two_cleared_cases(self):
        docket = build_docket(**NESTED_DOCKET)
        complainant = docket["complainant"]
        domain_b = register_domain(docket["registrar"]["id"], "nested-b.example")
        cases = {}
        for label, domain in (("a", docket["domain"]), ("b", domain_b)):
            case = file_complaint(complainant, domain)
            assert_all_mandatory_grounds(case, complainant, evidence_count=1)
            post_ledger_line(
                case["id"], case["complainant_share_cents"],
                reference="WIRE-9034-%s" % label.upper(),
            )
            cleared = clear_compliance(case["id"], reviewer_notes="Complete.")
            assert cleared["status"] == "VERIFICATION_PENDING"
            cases[label] = {"case": case, "verification": first_verification(case["id"])}
        return {
            "registrar": docket["registrar"],
            "domain_a": docket["domain"],
            "domain_b": domain_b,
            "a": cases["a"],
            "b": cases["b"],
        }

    def test_a_real_child_of_the_wrong_case_is_reported_as_a_missing_resource(self):
        """PRD §2.6: "Only once the parent has resolved does the server look at a
        nested sub-resource identifier — a verification id or a notification id — and
        such an identifier must both exist and belong to the case named earlier in the
        same path; failing either, the answer is `ERR_RESOURCE_NOT_FOUND`."
        PRD §2.6: "A court challenge identifier is resolved the same way, with the
        same error."
        PRD §3.4: "A valid answer moves the row to `RESPONDED` with `responded_at`
        stamped from the clock; if it was answered out of `OVERDUE`, the registrar's
        `overdue_verification_count` drops by one at that moment. A domain sitting in
        `UNLOCKED` moves to `LOCKED` with `locked_at` stamped from the clock and the
        domain's `version` advancing; a domain already locked is left as it stands."

        Design: Corner/errors/nested_sub_resource_ids_are_scoped_to_the_case_in_the_path
        """
        fixture = self._two_cleared_cases()
        registrar_headers = make_registrar_headers(fixture["registrar"]["id"])
        case_a_id = fixture["a"]["case"]["id"]
        verification_b_id = fixture["b"]["verification"]["id"]
        assert fixture["a"]["verification"]["id"] != verification_b_id

        borrowed = api_client.respond_to_verification(
            case_a_id, verification_b_id,
            verification_response_payload(
                verified_registrant_name="Nested Underlying Holder",
                verified_registrant_email="registrant@nested-a.example",
            ),
            registrar_headers,
        )
        validate_error(borrowed, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

        fabricated_notification = api_client.record_delivery(
            case_a_id, NON_EXISTENT_UUID,
            {"outcome": "DELIVERED", "deemed_received_at": "2026-08-01T00:00:00Z"},
            CASE_MANAGER,
        )
        validate_error(fabricated_notification, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

        fabricated_challenge = api_client.resolve_court_challenge(
            NON_EXISTENT_UUID,
            {"outcome": "DISMISSED", "resolution_note": "No such docket."},
            PROVIDER_ADMIN,
        )
        validate_error(fabricated_challenge, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

        untouched = first_verification(case_a_id)
        assert untouched["status"] == "REQUESTED"
        assert untouched["lock_applied"] is False
        assert untouched["responded_at"] is None
        assert read_domain(fixture["domain_a"]["id"])["lock_status"] == "UNLOCKED"
        assert read_case(case_a_id)["status"] == "VERIFICATION_PENDING"

        answered = get_success_data(
            api_client.respond_to_verification(
                fixture["b"]["case"]["id"], verification_b_id,
                verification_response_payload(
                    verified_registrant_name="Nested B Underlying Holder",
                    verified_registrant_email="registrant@nested-b.example",
                ),
                registrar_headers,
            )
        )
        assert answered["status"] == "RESPONDED"
        assert answered["responded_at"] == "2026-08-01T00:00:00.000Z"
        assert read_domain(fixture["domain_b"]["id"])["lock_status"] == "LOCKED"

    def test_a_fabricated_case_segment_is_reported_before_the_child_segment(self):
        """PRD §2.6: "Identifiers in a path are resolved strictly left to right, and
        the first identifier that names nothing aborts the request with the 404 that
        belongs to that position."
        PRD §2.6: "A path rooted at a case resolves the case first and reports
        `ERR_CASE_NOT_FOUND` when it names no case; a domain path reports
        `ERR_DOMAIN_NOT_FOUND`; a panelist path reports `ERR_PANELIST_NOT_FOUND`; an
        appointment path reports `ERR_APPOINTMENT_NOT_FOUND`; a decision path reports
        `ERR_DECISION_NOT_FOUND`."

        Design: Corner/errors/nested_sub_resource_ids_are_scoped_to_the_case_in_the_path
        """
        fixture = self._two_cleared_cases()
        registrar_headers = make_registrar_headers(fixture["registrar"]["id"])
        verification_b_id = fixture["b"]["verification"]["id"]

        wrong_root = api_client.respond_to_verification(
            NON_EXISTENT_UUID, verification_b_id,
            verification_response_payload(
                verified_registrant_name="Nested Underlying Holder",
                verified_registrant_email="registrant@nested-b.example",
            ),
            registrar_headers,
        )
        validate_error(wrong_root, ApiErrorId.ERR_CASE_NOT_FOUND.value, 404)
        assert wrong_root.json()["data"]["error_id"] != ApiErrorId.ERR_RESOURCE_NOT_FOUND.value

        still_requested = first_verification(fixture["b"]["case"]["id"])
        assert still_requested["status"] == "REQUESTED"
        assert still_requested["lock_applied"] is False
        assert read_domain(fixture["domain_b"]["id"])["lock_status"] == "UNLOCKED"


def _error_envelope(response, error_id, status):
    """Every refusal is the same shape: meta, response_type error, and a two-key data."""
    validate_error(response, error_id, status)
    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    return body


class TestOneEnvelopeForEveryRefusal:
    def test_four_status_codes_come_back_in_the_same_shape_and_write_nothing(self):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."
        PRD §3.1: "Complainants are registered with a `legal_name`, an ISO 3166-1
        alpha-2 `country_code` of exactly two uppercase letters, and a correspondence
        `email`."
        PRD §3.1: "Roster admission is a `ProviderAdmin` prerogative."
        PRD §3.1: "The `domain_name` is stored lowercased, must be between 4 and 253
        characters, and is globally unique — a second attempt at a name already on the
        docket is refused with `ERR_DUPLICATE_DOMAIN_NAME`."

        Design: Corner/errors/every_refusal_uses_the_same_error_envelope_and_writes_nothing
        """
        registrar = admit_registrar(iana_id="IANA-9035", name="Envelope Registrar")
        domain = register_domain(registrar["id"], "envelope.example")

        no_email = dict(complainant_payload(legal_name="Envelope Ltd", country_code="GB"))
        no_email.pop("email")
        schema = _error_envelope(
            api_client.create_complainant(no_email, CASE_MANAGER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        role = _error_envelope(
            api_client.create_panelist(
                panelist_payload(
                    full_name="Oliver Grant", nationality_code="GB",
                    roster_admitted_at="2018-01-01T00:00:00Z",
                ),
                CASE_MANAGER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        missing = _error_envelope(
            api_client.get_case(NON_EXISTENT_UUID, CASE_MANAGER),
            ApiErrorId.ERR_CASE_NOT_FOUND.value,
            404,
        )

        duplicate = _error_envelope(
            api_client.create_domain(
                domain_payload(
                    registrar["id"], "envelope.example",
                    registrant_name_public="Second Filing",
                    registrant_email_public="env2@proxy.example",
                    registration_date="2021-01-01T00:00:00Z",
                    expiry_date="2028-01-01T00:00:00Z",
                ),
                PROVIDER_ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_DOMAIN_NAME.value,
            409,
        )

        for body in (schema, role, missing, duplicate):
            assert "id" not in body["data"], "no entity fields leak into an error's data"
            assert "version" not in body["data"]
        assert len({body["meta"]["api_request_id"] for body in
                    (schema, role, missing, duplicate)}) == 4

        rows, meta = validate_paginated(
            api_client.list_domains(
                PROVIDER_ADMIN,
                params={"registrar_id": registrar["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, "not one of the four refusals wrote a row"
        assert rows[0]["domain_name"] == "envelope.example"
        assert rows[0]["id"] == domain["id"]
