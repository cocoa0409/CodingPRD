"""Role gates, entity-backed grower scope and the two segregation-of-duties pairs."""

from __future__ import annotations

import pytest

from test_helpers import (
    FIELD_OFFICER_2_ID,
    FIELD_OFFICER_ID,
    GOLDEN_FIGURES,
    SETTLEMENT_ACCOUNTANT_2_ID,
    SETTLEMENT_ACCOUNTANT_ID,
    TEST_DEFAULTS,
    assert_field_inspection,
    computed_settlement_state,
    create_field_inspection_payload,
    get_success_data,
    make_field_officer_headers,
    make_grower,
    make_grower_headers,
    make_headers,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    offered_contract_state,
    planted_contract_state,
    pay_settlement_payload,
    rogueing_declaration_payload,
    rogueing_verification_payload,
    set_clock,
    sign_contract_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNDECLARED_ROLE = "SeedInspectorGeneral"
UNDECLARED_ROLE_USER_ID = "sig-1"
ROGUEING_OFF_TYPE_PLANTS = 21
ROGUEING_OFF_TYPE_RATE = 10.50
VERIFIED_REMAINING_OFF_TYPE_PLANTS = 15
CHAIN_PAYMENT_REFERENCE = "ACH-2026-0917-001"


class TestInspectionRecordingIsFieldOfficerOnly:
    def test_the_program_admin_who_owns_the_reference_data_may_not_walk_the_field(self, api):
        """The identical count sheet is refused from an admin and accepted from an officer.

        PRD: "Once the caller is authenticated, the role in `X-User-Role` must appear on the endpoint
        being addressed; a caller whose role is not authorized for that endpoint is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD: "A `ProgramAdmin` may read every resource in the system but may not inspect fields,
        condition lots, issue certification tags or touch settlements."

        PRD: "A `FieldOfficer` is a certification field officer who registers production fields and
        their crop history, records inspection count sheets and verifies grower rogueing."

        PRD: "The recording officer's `X-User-ID` is stored on the inspection as
        `inspector_user_id`, and the inspection is stamped with an `inspection_round` equal to the
        contract's current `inspection_round` plus one, so the first walk of a contract is round 1."

        PRD: "On the `PASSED` branch the contract advances `PLANTED → INSPECTION_PASSED`, the
        inspection remains in `RECORDED` status, the contract's `inspection_round` increments by 1,
        the contract's `version` increments by 1, and no compliance flag is raised against the
        grower."

        Design: Corner/rbac/program_admin_cannot_record_field_inspection
        """
        state = planted_contract_state(api)
        contract_id = state["contract"]["id"]
        set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
        payload = create_field_inspection_payload(contract_id)

        response = api.create_field_inspection(payload, make_program_admin_headers())
        validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)

        refused = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert refused["status"] == "PLANTED"
        assert refused["inspection_round"] == 0

        _walks, meta = validate_paginated(
            api.list_field_inspections(
                make_field_officer_headers(), {"production_contract_id": contract_id}
            )
        )
        assert meta["total_count"] == 0

        inspection = validate_success(
            api.create_field_inspection(payload, make_field_officer_headers(FIELD_OFFICER_ID)), 201
        )
        assert_field_inspection(inspection)
        assert inspection["outcome"] == "PASSED"
        assert inspection["inspector_user_id"] == FIELD_OFFICER_ID
        assert inspection["inspection_round"] == 1
        assert inspection["status"] == "RECORDED"

        passed = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert passed["status"] == "INSPECTION_PASSED"
        assert passed["inspection_round"] == 1


class TestUnknownRoleIsAnAuthenticationFailure:
    def test_a_role_outside_the_declared_six_is_refused_before_authorisation_runs(self, api):
        """An unrecognised role never reaches the endpoint's role list at all.

        PRD: "If either header is absent, or if the value of `X-User-Role` is not one of the six role
        names enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD: "This check runs before every other check in the system, including request-shape
        parsing."

        PRD: "The six roles are `ProgramAdmin`, `FieldOfficer`, `Grower`, `ConditioningManager`,
        `CertificationAgency` and `SettlementAccountant`."

        Design: Corner/rbac/unknown_role_header_rejected
        """
        grower = make_grower(api)

        response = api.get_grower(
            grower["id"], make_headers(UNDECLARED_ROLE_USER_ID, UNDECLARED_ROLE)
        )
        error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
        assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED"
        assert response.status_code != 403

        fetched = validate_success(
            api.get_grower(grower["id"], make_program_admin_headers()), 200
        )
        assert fetched["id"] == grower["id"]


class TestGrowerScopeIsPerRow:
    def test_a_second_grower_may_not_sign_the_first_growers_offered_contract(self, api):
        """A valid Grower role on the wrong row is still refused; the owner then signs.

        PRD: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` entity;
        ownership checks on any resource that references a `Grower` compare the resource's grower
        foreign key to `X-User-ID`."

        PRD: "Concretely, for the three grower-actor operations — signing an offered contract, filing
        a rogueing declaration on an inspection, and disputing a settlement — the platform resolves
        the `ProductionContract` that owns the target resource and requires that its `grower_id`
        equal `X-User-ID`; a mismatch is rejected with `ERR_GROWER_SCOPE_VIOLATION` (HTTP 403)."

        PRD: "A `Grower` accepts an offered contract by signing it, which advances the contract
        `OFFERED → PLANTED` and records `planted_on`, the ISO 8601 date on which the field was
        actually planted."

        PRD: "The signing grower's `X-User-ID` must equal the contract's `grower_id`, or the request
        is refused with `ERR_GROWER_SCOPE_VIOLATION`."

        Design: Corner/rbac/grower_cannot_sign_another_growers_contract
        """
        state = offered_contract_state(api)
        contract_id = state["contract"]["id"]
        outsider = make_grower(
            api,
            grower_name=TEST_DEFAULTS["SECOND_GROWER_NAME"],
            region_code=TEST_DEFAULTS["SECOND_REGION_CODE"],
            contact_email=TEST_DEFAULTS["SECOND_CONTACT_EMAIL"],
        )

        response = api.sign_production_contract(
            contract_id, sign_contract_payload(), make_grower_headers(outsider["id"])
        )
        validate_error(response, "ERR_GROWER_SCOPE_VIOLATION", 403)

        refused = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert refused["status"] == "OFFERED"
        assert refused["planted_on"] is None
        assert refused["version"] == state["contract"]["version"]

        signed = validate_success(
            api.sign_production_contract(
                contract_id, sign_contract_payload(), make_grower_headers(state["grower"]["id"])
            ),
            200,
        )
        assert signed["status"] == "PLANTED"
        assert signed["planted_on"] == TEST_DEFAULTS["PLANTED_ON"]
        assert signed["version"] == state["contract"]["version"] + 1


def _inspection_awaiting_verification(api):
    """A rogueing-ordered inspection recorded by fo-1 with the grower's declaration on file."""
    state = planted_contract_state(api)
    set_clock(api, TEST_DEFAULTS["INSPECTION_CLOCK"])
    inspection = validate_success(
        api.create_field_inspection(
            create_field_inspection_payload(
                state["contract"]["id"], off_type_plants=ROGUEING_OFF_TYPE_PLANTS
            ),
            make_field_officer_headers(FIELD_OFFICER_ID),
        ),
        201,
    )
    assert inspection["outcome"] == "ROGUEING_ORDERED"
    assert inspection["off_type_rate_per_10000"] == pytest.approx(ROGUEING_OFF_TYPE_RATE, abs=0.01)

    state["inspection"] = get_success_data(
        api.declare_rogueing(
            inspection["id"],
            rogueing_declaration_payload(rogueing_declared_on=TEST_DEFAULTS["INSPECTED_ON"]),
            make_grower_headers(state["grower"]["id"]),
        )
    )
    return state


class TestRogueingVerificationIsSegregated:
    def test_the_officer_who_recorded_the_walk_cannot_sign_off_his_own_rogueing(self, api):
        """The same role and the same payload succeed only from the second officer.

        PRD: "The verifying officer's `X-User-ID` must differ from the inspection's
        `inspector_user_id`; a self-verification is refused with
        `ERR_SOD_ROGUEING_SELF_VERIFICATION`."

        PRD: "The verified remaining off-type rate is computed exactly as the original rate was — the
        remaining off-type plant count divided by the inspection's `sampled_plants`, multiplied by ten
        thousand, rounded half-up to two decimal places — and compared against the variety's
        `max_off_type_per_10000`."

        PRD: "When the remaining rate is at or below the variety's off-type tolerance *and* the
        contract's `rogueing_rounds_used` has not exceeded the variety's `max_rogueing_rounds`, the
        rogueing is accepted: the inspection moves `ROGUEING_DECLARED → ROGUEING_VERIFIED`,
        `rogueing_verified_by_user_id` is set from the verifying officer's `X-User-ID`, the contract
        returns `ROGUEING_REQUIRED → PLANTED` so that a further inspection round may be recorded, the
        inspection's `version` increments by 1, and the contract's `version` increments by 1."

        Design: Corner/rbac/rogueing_self_verification_rejected
        """
        state = _inspection_awaiting_verification(api)
        inspection_id = state["inspection"]["id"]
        payload = rogueing_verification_payload(
            verified_remaining_off_type_plants=VERIFIED_REMAINING_OFF_TYPE_PLANTS
        )

        response = api.verify_rogueing(
            inspection_id, payload, make_field_officer_headers(FIELD_OFFICER_ID)
        )
        validate_error(response, "ERR_SOD_ROGUEING_SELF_VERIFICATION", 403)

        refused = get_success_data(
            api.get_field_inspection(inspection_id, make_field_officer_headers())
        )
        assert refused["status"] == "ROGUEING_DECLARED"
        assert refused["rogueing_verified_by_user_id"] is None
        assert refused["inspector_user_id"] == FIELD_OFFICER_ID

        verified = validate_success(
            api.verify_rogueing(
                inspection_id, payload, make_field_officer_headers(FIELD_OFFICER_2_ID)
            ),
            200,
        )
        assert verified["status"] == "ROGUEING_VERIFIED"
        assert verified["rogueing_verified_by_user_id"] == FIELD_OFFICER_2_ID
        assert verified["verified_remaining_off_type_plants"] == VERIFIED_REMAINING_OFF_TYPE_PLANTS

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "PLANTED"
        assert contract["rogueing_rounds_used"] == 1


class TestSettlementApprovalIsSegregated:
    def test_the_accountant_who_computed_the_settlement_cannot_approve_it(self, api):
        """No recovery is booked until a second accountant puts her name to it.

        PRD: "The approving accountant's `X-User-ID` must differ from the settlement's
        `computed_by_user_id`, or the request is refused with `ERR_SOD_SETTLEMENT_SELF_APPROVAL`."

        PRD: "On success the settlement moves `COMPUTED → APPROVED`, `approved_by_user_id` is set
        from the approving accountant's identifier, the settlement's `advance_recovery_cents` is
        subtracted from the contract's `advance_outstanding_cents`, the contract advances
        `HARVESTED → SETTLED`, the settlement's `version` increments by 1 and the contract's `version`
        increments by 1."

        PRD: "This is the one operation that books an advance recovery."

        Design: Corner/rbac/settlement_self_approval_rejected
        """
        state = computed_settlement_state(api)
        settlement_id = state["settlement"]["id"]
        contract_id = state["contract"]["id"]
        assert state["settlement"]["computed_by_user_id"] == SETTLEMENT_ACCOUNTANT_ID

        response = api.approve_settlement(
            settlement_id, {}, make_settlement_accountant_headers(SETTLEMENT_ACCOUNTANT_ID)
        )
        validate_error(response, "ERR_SOD_SETTLEMENT_SELF_APPROVAL", 403)

        refused = get_success_data(
            api.get_settlement(settlement_id, make_settlement_accountant_headers())
        )
        assert refused["status"] == "COMPUTED"
        assert refused["approved_by_user_id"] is None

        held = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert held["advance_outstanding_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]
        assert held["status"] == "HARVESTED"

        approved = validate_success(
            api.approve_settlement(
                settlement_id, {}, make_settlement_accountant_headers(SETTLEMENT_ACCOUNTANT_2_ID)
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == SETTLEMENT_ACCOUNTANT_2_ID

        settled = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert settled["advance_outstanding_cents"] == 0
        assert settled["status"] == "SETTLED"


class TestApprovalChainCompletesWithTwoAccountants:
    def test_payment_waits_for_the_approval_and_then_closes_the_contract(self, api):
        """Paying a merely computed settlement is refused; the same accountant may pay what she approved.

        PRD: "A `SettlementAccountant` pays a settlement whose status is `APPROVED`, supplying the
        bank `payment_reference`; any other status is refused with `ERR_INVALID_SETTLEMENT_STATE`."

        PRD: "The reference is stored, the settlement moves `APPROVED → PAID`, the contract advances
        `SETTLED → CLOSED`, and both versions increment by 1."

        PRD: "`CLOSED` is terminal for the contract."

        PRD: "The approving accountant's `X-User-ID` must differ from the settlement's
        `computed_by_user_id`, or the request is refused with `ERR_SOD_SETTLEMENT_SELF_APPROVAL`."

        Design: Corner/rbac/settlement_approval_chain_completes_with_two_accountants
        """
        state = computed_settlement_state(api)
        settlement_id = state["settlement"]["id"]
        contract_id = state["contract"]["id"]
        second_accountant = make_settlement_accountant_headers(SETTLEMENT_ACCOUNTANT_2_ID)

        early = api.pay_settlement(
            settlement_id, pay_settlement_payload(payment_reference=CHAIN_PAYMENT_REFERENCE), second_accountant
        )
        validate_error(early, "ERR_INVALID_SETTLEMENT_STATE", 409)

        unpaid = get_success_data(
            api.get_settlement(settlement_id, make_settlement_accountant_headers())
        )
        assert unpaid["status"] == "COMPUTED"
        assert unpaid["payment_reference"] is None

        approved = validate_success(
            api.approve_settlement(settlement_id, {}, second_accountant), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["advance_recovery_cents"] == GOLDEN_FIGURES["ADVANCE_RECOVERY_CENTS"]
        assert approved["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]

        paid = validate_success(
            api.pay_settlement(
                settlement_id, pay_settlement_payload(payment_reference=CHAIN_PAYMENT_REFERENCE), second_accountant
            ),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["payment_reference"] == CHAIN_PAYMENT_REFERENCE
        assert paid["approved_by_user_id"] == SETTLEMENT_ACCOUNTANT_2_ID

        closed = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert closed["status"] == "CLOSED"
        assert closed["advance_outstanding_cents"] == 0
