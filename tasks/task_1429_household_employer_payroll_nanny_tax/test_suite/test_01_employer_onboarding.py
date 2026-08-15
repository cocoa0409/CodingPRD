"""Employer onboarding, rule packs, and registrations."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_household_employer,
    assert_state_rule_pack,
    build_user_headers,
    create_employer,
    create_employer_payload,
    create_registration,
    create_rule_pack,
    create_state_rule_pack_payload,
    get_employer,
    is_valid_uuid,
    make_compliance_officer_headers,
    make_household_client_headers,
    make_payroll_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmployerCreate:
    def test_employer_create_applies_defaults_and_system_fields(self, api):
        """PRD §3.2: "A new employer is born with `status` set to `ONBOARDING` and `compliance_posture` initialized to `CLEAR`."
        PRD §3.2: "`prior_year_schedule_h_cents` defaults to 0 when omitted and feeds the safe-harbor leg of the estimated-payment calculation."

        Design: Corner/entities/employer_create_defaults_and_computed_fields
        """
        create_rule_pack("AA")
        resp = api.create_employer(
            {
                "legal_name": "Fam Def",
                "primary_state_code": "AA",
                "fein": "123456789",
                "pay_frequency": "WEEKLY",
            },
            make_payroll_admin_headers(),
        )
        data = validate_success(resp, 201)
        assert_household_employer(data)
        assert data["status"] == "ONBOARDING"
        assert data["compliance_posture"] == "CLEAR"
        assert data["prior_year_schedule_h_cents"] == 0
        assert is_valid_uuid(data["id"])

    def test_employer_create_ignores_client_supplied_status(self, api):
        """PRD §3.2: "A new employer is born with `status` set to `ONBOARDING` and `compliance_posture` initialized to `CLEAR`."

        Design: Corner/entities/employer_create_status_input_ignored
        """
        create_rule_pack("AA")
        resp = api.create_employer(
            {
                "legal_name": "Fam Ig",
                "primary_state_code": "AA",
                "fein": "123456789",
                "pay_frequency": "WEEKLY",
                "status": "ACTIVE",
            },
            make_payroll_admin_headers(),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "ONBOARDING", (
            f"system-owned status must win over client input, got {data['status']}"
        )

    def test_employer_create_missing_fein_returns_400(self, api):
        """PRD §2.8: "**Request shape** — required fields present, types correct, enum members valid, ISO dates well-formed and ordered, and `hourly_rate_cents` divisible by 60; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/employer_create_missing_required_field_returns_400
        """
        create_rule_pack("AA")
        resp = api.create_employer(
            {"legal_name": "Fam Bad", "primary_state_code": "AA", "pay_frequency": "WEEKLY"},
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_employer_create_invalid_pay_frequency_enum_returns_400(self, api):
        """PRD §2.8: "**Request shape** — required fields present, types correct, enum members valid, ISO dates well-formed and ordered, and `hourly_rate_cents` divisible by 60; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/employer_create_invalid_enum_returns_400
        """
        create_rule_pack("AA")
        resp = api.create_employer(
            {
                "legal_name": "Fam Enum",
                "primary_state_code": "AA",
                "fein": "123456789",
                "pay_frequency": "DAILY",
            },
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_employer_create_unknown_state_returns_422(self, api):
        """PRD §3.2: "The primary state must already have a rule pack — otherwise the create is rejected with `ERR_STATE_RULES_MISSING` (HTTP 422)."

        Design: Corner/validations/employer_create_unknown_state_returns_422
        """
        resp = api.create_employer(
            {
                "legal_name": "Fam ZZ",
                "primary_state_code": "ZZ",
                "fein": "123456789",
                "pay_frequency": "WEEKLY",
            },
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STATE_RULES_MISSING)

    def test_employer_create_below_state_pay_frequency_floor_returns_422(self, api):
        """PRD §3.2: "The `pay_frequency` must be at least as frequent as the primary state's `min_pay_frequency` — the ordering, from most to least frequent, is `WEEKLY`, then `BIWEEKLY`, then `SEMIMONTHLY`, then `MONTHLY`; choosing a frequency less frequent than the floor is rejected with `ERR_PAY_FREQUENCY_NONCOMPLIANT` (HTTP 422)."

        Design: Corner/validations/pay_frequency_below_state_minimum_returns_422
        """
        create_rule_pack("SM", min_pay_frequency="SEMIMONTHLY")
        resp = api.create_employer(
            {
                "legal_name": "Fam Slow",
                "primary_state_code": "SM",
                "fein": "123456789",
                "pay_frequency": "MONTHLY",
            },
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PAY_FREQUENCY_NONCOMPLIANT)


class TestStateRulePacks:
    def test_state_rule_pack_is_immutable_carrying_no_version(self, api):
        """PRD §2.4: "`StateRulePack` and `TaxDeposit` are the two exceptions: they carry `id` and `created_at` only — `updated_at` and `version` are absent on both, because neither entity is ever mutated after creation and neither participates in optimistic concurrency control."

        Design: Corner/entities/state_rule_pack_immutable_no_update_endpoint
        """
        resp = api.create_state_rule_pack(
            create_state_rule_pack_payload("GG", sit_rate=0.0),
            make_payroll_admin_headers(),
        )
        data = validate_success(resp, 201)
        assert_state_rule_pack(data)

    def test_duplicate_state_rule_pack_returns_409(self, api):
        """PRD §3.1: "Each pack is created for exactly one `state_code`, unique across the system — a duplicate create is rejected with `ERR_DUPLICATE_RULE_PACK` (HTTP 409)."

        Design: Corner/validations/duplicate_rule_pack_returns_409
        """
        create_rule_pack("AA")
        resp = api.create_state_rule_pack(
            create_state_rule_pack_payload("AA", min_pay_frequency="MONTHLY"),
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RULE_PACK)


class TestEmployerStateMachine:
    def test_first_registration_activation_flips_employer_active(self, api):
        """PRD §3.2: "The employer remains in `ONBOARDING` until the system observes its first `StateRegistration` reach `ACTIVE`, at which point the employer automatically transitions `ONBOARDING → ACTIVE` and its `version` increments by 1."

        Design: Corner/state_machines/employer_auto_activates_on_first_registration
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        reg = create_registration(employer["id"], "AA", "NEW_HIRE_DIRECTORY")
        resp = api.submit_registration(reg["id"], make_payroll_admin_headers())
        validate_success(resp, 200)
        resp = api.activate_registration(
            reg["id"], {"agency_account_number": "NH-001"}, make_payroll_admin_headers()
        )
        validate_success(resp, 200)
        after = get_employer(employer["id"])
        assert after["status"] == "ACTIVE", (
            f"employer must auto-activate on first ACTIVE registration, got {after['status']}"
        )

    def test_suspend_blocks_payrun_create_and_reinstate_restores(self, api):
        """PRD §3.2: "A `ComplianceOfficer` may suspend an `ACTIVE` employer — a transition to `SUSPENDED` that blocks pay-run creation and finalization for the duration."
        PRD §3.6: "The employer's `status` must be `ACTIVE` — creating a pay run against a `SUSPENDED` employer is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/employer_suspend_reinstate_cycle
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        reg = create_registration(employer["id"], "AA", "NEW_HIRE_DIRECTORY")
        resp = api.submit_registration(reg["id"], make_payroll_admin_headers())
        validate_success(resp, 200)
        resp = api.activate_registration(
            reg["id"], {"agency_account_number": "NH-001"}, make_payroll_admin_headers()
        )
        validate_success(resp, 200)

        resp = api.suspend_employer(employer["id"], make_compliance_officer_headers())
        suspended = validate_success(resp, 200)
        assert suspended["status"] == "SUSPENDED"

        resp = api.create_pay_run(
            employer["id"],
            {"period_start": "2026-01-05", "period_end": "2026-01-12", "pay_date": "2026-01-12"},
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.reinstate_employer(employer["id"], make_compliance_officer_headers())
        reinstated = validate_success(resp, 200)
        assert reinstated["status"] == "ACTIVE"

    def test_suspend_from_onboarding_returns_invalid_state(self, api):
        """PRD §3.2: "Either action against an employer in the wrong from-state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/suspend_from_onboarding_returns_invalid_state
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        resp = api.suspend_employer(employer["id"], make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRegistrations:
    def test_registration_activate_from_draft_returns_invalid_state(self, api):
        """PRD §3.3: "Activation moves it `SUBMITTED → ACTIVE` and captures `agency_account_number` from the request body; until activation the account number is null."
        PRD §2.8: "**State-machine preconditions** — the target transition's `from`-state and any parent-status gates; failure yields `ERR_INVALID_STATE`, with the pay-run-finalize staleness gate surfacing as `ERR_PAYRUN_STALE`."

        Design: Corner/state_machines/registration_activate_from_draft_returns_invalid_state
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        reg = create_registration(employer["id"], "AA", "SUTA")
        assert reg["status"] == "DRAFT"
        resp = api.activate_registration(
            reg["id"], {"agency_account_number": "X-1"}, make_payroll_admin_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_duplicate_registration_returns_409(self, api):
        """PRD §3.3: "A duplicate registration — one for the same (employer, `state_code`, `agency`) triple that is not in a terminal state — is rejected with `ERR_DUPLICATE_REGISTRATION` (HTTP 409)."

        Design: Corner/validations/duplicate_registration_returns_409
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        create_registration(employer["id"], "AA", "NEW_HIRE_DIRECTORY")
        fresh_version = get_employer(employer["id"])["version"]
        resp = api.create_registration(
            employer["id"],
            {
                "state_code": "AA",
                "agency": "NEW_HIRE_DIRECTORY",
                "expected_employer_version": fresh_version,
            },
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)

    def test_registration_create_with_stale_employer_version_returns_412(self, api):
        """PRD §2.7: "The server compares the supplied value to the employer's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from building a registration on a stale view of the employer (for example, after another registration's activation has flipped the employer's `status` and recomputed its posture)."
        PRD §2.7: "Successful creation under either rule increments the parent entity's `version` by 1 as a side effect."

        Design: Corner/cross_cutting_layers/registration_create_stale_occ
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        stale_version = employer["version"]

        # First create succeeds and bumps the employer version.
        first = create_registration(employer["id"], "AA", "SUTA", stale_version)
        assert first["status"] == "DRAFT"

        # The stale version is now rejected with 412.
        resp = api.create_registration(
            employer["id"],
            {
                "state_code": "AA",
                "agency": "SIT_WITHHOLDING",
                "expected_employer_version": stale_version,
            },
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        # Retry with the freshly observed version succeeds and bumps by exactly 1.
        before_retry = get_employer(employer["id"])["version"]
        resp = api.create_registration(
            employer["id"],
            {
                "state_code": "AA",
                "agency": "SIT_WITHHOLDING",
                "expected_employer_version": before_retry,
            },
            make_payroll_admin_headers(),
        )
        validate_success(resp, 201)
        after_retry = get_employer(employer["id"])["version"]
        assert after_retry == before_retry + 1, (
            f"employer version must increment by exactly 1, {before_retry} -> {after_retry}"
        )


class TestEmployerListing:
    def test_employer_registrations_list_empty_is_array_envelope(self, api):
        """PRD §2.3: "The `meta` envelope of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when further results exist beyond the current page."
        PRD §2.2: "The `response_type` is either \"object\" for a single resource or \"array\" for a list of resources."

        Design: Corner/endpoints/get_employers_filtered_list_is_array
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        resp = api.list_registrations(employer["id"], make_payroll_admin_headers())
        data, meta = validate_paginated(resp)
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert resp.json()["response_type"] == "array"
