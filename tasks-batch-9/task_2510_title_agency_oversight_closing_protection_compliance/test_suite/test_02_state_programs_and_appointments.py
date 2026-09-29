"""State program definition, appointment creation and the registration keys."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_common_fields,
    assert_fields_equal,
    create_agency,
    create_appointment,
    create_appointment_payload,
    create_escrow_account_payload,
    create_state_program,
    create_state_program_payload,
    make_agency_principal_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER


class TestStateProgramCreation:
    """A state program is the rule book for one jurisdiction."""

    def test_state_program_persists_every_declared_input(self, api):
        """The created program echoes all eight declared inputs unchanged.

        PRD: "the agency's retention fraction of gross premium in
        `premium_split_agency_pct`, from which the underwriter's factor is derived as
        one minus that fraction; the number of whole days after a closing within
        which a policy may still be issued on time, in
        `policy_issuance_deadline_days`, which must be at least 1"

        Design: Corner/entities/creation_state_program_persists_every_declared_input
        """
        payload = create_state_program_payload(
            cpl_permitted=True,
            cpl_coverage_cap_cents=100_000_000,
            cpl_scope_allowed=["FULL_SETTLEMENT", "LENDER_ONLY", "SELLER_PROCEEDS"],
            premium_split_agency_pct=0.80,
            policy_issuance_deadline_days=30,
            three_way_tolerance_cents=100_000,
            counsel_referral_threshold_cents=60_000_000,
        )

        created = validate_success(api.create_state_program(payload, OFFICER), 201)

        assert_common_fields(created, "state program")
        assert_fields_equal(created, payload, "state program")
        assert created["version"] == 1, (
            f"a new state program must be at version 1, got {created['version']}"
        )

        fetched = validate_success(api.get_state_program(created["id"], ANALYST))
        assert_fields_equal(fetched, payload, "state program on read")

    def test_split_percentage_above_one_is_rejected(self, api):
        """The retention fraction lives in the closed interval from 0 through 1.

        PRD: "A percentage input, `premium_split_agency_pct`, is accepted as a number
        in the closed interval from 0 through 1, expressed with at most three decimal
        places; a value outside that interval is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/type_constraints_state_program_split_pct_above_one_returns_400
        """
        payload = create_state_program_payload(
            cpl_scope_allowed=["FULL_SETTLEMENT"], premium_split_agency_pct=1.5
        )

        response = api.create_state_program(payload, OFFICER)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestBodyReferenceResolution:
    """Body foreign keys resolve in the PRD's declaration order."""

    def test_unknown_agency_is_reported_before_unknown_state_program(self, api):
        """With both keys unresolvable the answer names the agency, not the program.

        PRD: "Foreign keys supplied in a request body are resolved the same way, in a
        fixed declaration order rather than in the order the client happened to
        serialize them: `agency_id` first, then `state_program_id`, then
        `escrow_account_id`, then `policy_file_id`, then `cpl_id`, then
        `follow_up_of_audit_id`, then `transferee_agency_id`."

        Design: Corner/entities/flat_body_fk_resolution_reports_agency_before_state_program_returns_404
        """
        payload = create_appointment_payload(
            NON_EXISTENT_UUID, "11111111-1111-4111-8111-111111111111"
        )

        response = api.create_appointment(payload, ANALYST)

        validate_error(response, ApiErrorId.ERR_AGENCY_NOT_FOUND.value, 404)

        _rows, meta = validate_paginated(api.list_appointments(ANALYST))
        assert meta["total_count"] == 0, (
            f"no appointment may be written, but the list reports {meta['total_count']}"
        )


class TestRegistrationUniqueness:
    """Each registration key has its own uniqueness scope."""

    def test_reused_tax_id_is_rejected(self, api):
        """The federal identifier is unique across every agency ever registered.

        PRD: "The `tax_id` must be unique across all agencies ever registered, and a
        reused identifier is refused with `ERR_DUPLICATE_TAX_ID` (HTTP 409)."

        Design: Corner/errors/duplicate_registration_keys_are_rejected_returns_409
        """
        first = create_agency(api, legal_name="Harbor Title Agency")

        response = api.create_agency(
            {
                "legal_name": "Harbor Title of Nevada",
                "tax_id": first["tax_id"],
                "underwriting_authority_limit_cents": 20_000_000,
            },
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_TAX_ID.value, 409)
        _rows, meta = validate_paginated(api.list_agencies(ANALYST))
        assert meta["total_count"] == 1, (
            f"only the first agency may exist, but the list reports {meta['total_count']}"
        )

    def test_reused_state_code_is_rejected(self, api):
        """A state program is keyed by its two-letter code.

        PRD: "It is keyed by a two-letter `state_code`, unique across all state
        programs, with a reuse refused as `ERR_DUPLICATE_STATE_CODE` (HTTP 409)."

        Design: Corner/errors/duplicate_registration_keys_are_rejected_returns_409
        """
        first = create_state_program(api)

        response = api.create_state_program(
            create_state_program_payload(
                state_code=first["state_code"],
                cpl_permitted=False,
                cpl_coverage_cap_cents=10_000_000,
                cpl_scope_allowed=["FULL_SETTLEMENT"],
                premium_split_agency_pct=0.70,
                policy_issuance_deadline_days=20,
                three_way_tolerance_cents=50_000,
                counsel_referral_threshold_cents=30_000_000,
            ),
            OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_STATE_CODE.value, 409)

    def test_second_live_appointment_for_the_same_pair_is_rejected(
        self, api, state_program
    ):
        """Only one live appointment may exist per agency-and-state pair.

        PRD: "so a creation is refused with `ERR_DUPLICATE_APPOINTMENT` (HTTP 409)
        whenever an appointment for the same agency and the same state program
        already exists with a `status` of `PENDING_LICENSE_VERIFICATION`, `ACTIVE` or
        `LAPSED`."

        Design: Corner/errors/duplicate_registration_keys_are_rejected_returns_409
        """
        agency = create_agency(api)
        create_appointment(api, agency["id"], state_program["id"])

        response = api.create_appointment(
            create_appointment_payload(agency["id"], state_program["id"]), ANALYST
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_APPOINTMENT.value, 409)
        _rows, meta = validate_paginated(
            api.list_appointments(ANALYST, params={"agency_id": agency["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the agency must hold one appointment, not {meta['total_count']}"
        )

    def test_reused_escrow_account_ref_is_rejected(self, api):
        """The masked reference is unique among the agency's open accounts.

        PRD: "The reference must be unique among that agency's accounts whose
        `status` is not `CLOSED`, else `ERR_DUPLICATE_ESCROW_ACCOUNT_REF` (HTTP 409);
        a reference freed by closure may be reused."

        Design: Corner/errors/duplicate_registration_keys_are_rejected_returns_409
        """
        agency = create_agency(api)
        principal = make_agency_principal_headers(agency["id"])
        first = validate_success(
            api.create_escrow_account(
                create_escrow_account_payload(
                    agency["id"], bank_name="First Trust Bank"
                ),
                principal,
            ),
            201,
        )

        response = api.create_escrow_account(
            create_escrow_account_payload(
                agency["id"],
                bank_name="Second State Bank",
                account_ref=first["account_ref"],
            ),
            principal,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ESCROW_ACCOUNT_REF.value, 409)
