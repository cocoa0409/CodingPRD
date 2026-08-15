"""Access control: identity headers, role authorization, entity-backed ownership,
segregation of duties, and optimistic concurrency (PRD §2.1, §2.7, §2.9, §3.2, §3.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_privilege_evaluation,
    build_user_headers,
    create_license_draft,
    create_nurse,
    create_nurse_payload,
    create_packet,
    create_unit,
    get_nurse,
    list_privilege_evals,
    packet_items_by_type,
    report_discipline,
    acknowledge_discipline,
    set_clock,
    setup_credentialed_nurse,
    submit_license,
    request_psv,
    record_psv_verified,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

SPEC1 = TEST_USERS["specialist_1"]
SPEC2 = TEST_USERS["specialist_2"]
VER1 = TEST_USERS["verifier_1"]
MGR1 = TEST_USERS["manager_1"]
CO1 = TEST_USERS["compliance_1"]
CO2 = TEST_USERS["compliance_2"]
OPS1 = TEST_USERS["operator_1"]


class TestIdentityHeadersAndRoles:
    def test_invalid_role_header_returns_400(self):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID` and
        `X-User-Role`. When either header is absent, or when the role value is not one
        of the roles declared below, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/invalid_role_header_returns_400
        """
        mystery = build_user_headers("mystery-1", "MysteryRole")
        resp = api_client.create_nurse(create_nurse_payload(), mystery)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        _data, meta = validate_paginated(api_client.list_nurses(SPEC1))
        assert meta["total_count"] == 0

    def test_nurse_cannot_create_license(self):
        """PRD §2.1: "A well-formed request whose declared role lacks permission for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST /credentialing/state-licenses | Register a license (born
        `DRAFT`)... | CredentialingSpecialist".

        Design: Corner/rbac/nurse_cannot_create_license
        """
        set_clock()
        nurse_headers = build_user_headers(NON_EXISTENT_UUID, "Nurse")
        payload = {
            "nurse_id": NON_EXISTENT_UUID,
            "state_code": "AZ",
            "license_number": "RN-AZ-NR1",
            "license_class": "RN",
            "multistate_flag": True,
            "issued_on": "2026-06-15",
            "expires_on": "2027-06-30",
        }
        resp = api_client.create_state_license(payload, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_specialist_cannot_record_psv_result(self):
        """PRD §2.1: "A well-formed request whose declared role lacks permission for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST
        /credentialing/primary-source-verifications/{psvId}/record-result | ...
        | PrimarySourceVerifier".

        Design: Corner/rbac/specialist_cannot_record_psv_result
        """
        set_clock()
        nurse = create_nurse(full_name="Role Gate", email="role.gate@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-RG1")
        submit_license(lic["id"])
        psv = request_psv(lic["id"])

        resp = api_client.record_psv_result(psv["id"], {"outcome": "VERIFIED"}, SPEC2)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = validate_success(api_client.get_psv(psv["id"], SPEC1), 200)
        assert after["status"] == "REQUESTED", "the rejected record must not move the PSV"

    def test_nurse_manager_cannot_create_audit_run(self):
        """PRD §2.1: "A well-formed request whose declared role lacks permission for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST /credentialing/audit-runs | Create an audit run (born
        `INITIATED`) over an inclusive date window | ComplianceOfficer".

        Design: Corner/rbac/nurse_manager_cannot_create_audit_run
        """
        set_clock()
        resp = api_client.create_audit_run(
            {"window_start": "2026-07-01", "window_end": "2026-08-01",
             "per_unit_sample_size": 5},
            MGR1,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _data, meta = validate_paginated(api_client.list_audit_runs(CO1))
        assert meta["total_count"] == 0

    def test_system_operator_cannot_create_nurse(self):
        """PRD §2.1: "A well-formed request whose declared role lacks permission for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST /credentialing/nurses | Create a nurse record, born `ONBOARDING`
        with posture `SCHEDULING_SUSPENDED` and privilege `NONE` |
        CredentialingSpecialist".

        Design: Corner/rbac/system_operator_cannot_create_nurse
        """
        set_clock()
        resp = api_client.create_nurse(
            create_nurse_payload(full_name="Op Nurse", email="op.nurse@x.com"), OPS1
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _data, meta = validate_paginated(api_client.list_nurses(SPEC1))
        assert meta["total_count"] == 0


class TestOwnershipAndSegregation:
    def test_ownership_violation_on_item_evidence(self):
        """PRD §2.1: "Ownership checks on any resource that references a nurse — a
        credential packet, a packet item, a competency completion — compare the
        resource's nurse foreign key (its `nurse_id`, or the owning packet's nurse) to
        `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION`
        (HTTP 403)."

        Design: Corner/validations/ownership_violation_on_item_evidence
        """
        set_clock()
        unit = create_unit(name="MED")
        nurse_a = create_nurse(full_name="Amy Own", email="amy.own@x.com",
                               employment_type="TRAVEL")
        nurse_b = create_nurse(full_name="Bob Own", email="bob.own@x.com",
                               employment_type="TRAVEL")
        packet_b = create_packet(nurse_b["id"], unit["id"])
        items = packet_items_by_type(packet_b["id"])
        att_item = items["ATTESTATION"]

        forged = build_user_headers(nurse_a["id"], "Nurse")
        resp = api_client.submit_item_evidence(
            att_item["id"], {"evidence_ref": "forged"}, forged
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
        after = validate_success(api_client.get_packet_item(att_item["id"], SPEC1), 200)
        assert after["status"] == "MISSING", "the rejected submission must not move the item"

    def test_license_attest_segregation_of_duties_rejected(self):
        """PRD §3.2: "Attestation promotes a license from `VERIFIED` to `ACTIVE` and is
        performed by a `PrimarySourceVerifier` who must not be the specialist who
        created the record: the acting user's id is compared against
        `created_by_user_id`, and a match is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/license_attest_segregation_of_duties_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="Seg Duty", email="seg.duty@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-SD1")
        submit_license(lic["id"])
        psv = request_psv(lic["id"])
        record_psv_verified(psv["id"])

        # The verifier-role caller whose id matches the license creator's id.
        same_user = build_user_headers("spec-1", "PrimarySourceVerifier")
        resp = api_client.attest_license(lic["id"], same_user)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = validate_success(api_client.attest_license(lic["id"], VER1), 200)
        assert ok["status"] == "ACTIVE"
        assert ok["verified_by_user_id"] == "ver-1"

    def test_discipline_adjudicate_same_officer_rejected(self):
        """PRD §3.8: "Adjudication then moves it from `UNDER_REVIEW` to `ADJUDICATED`
        when the `outcome` is `SUSTAINED`, or to `DISMISSED` when the `outcome` is
        `DISMISSED`; the adjudicating officer must differ from the acknowledger, else
        `ERR_SEGREGATION_OF_DUTIES`, and is stamped into `adjudicated_by_user_id`."
        PRD §3.8: "A sustained `REPRIMAND` changes no license, privilege, or posture —
        it is record only, though it still counts as an open encumbrance."

        Design: Corner/rbac/discipline_adjudicate_same_officer_rejected
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Four Eyes", email="four.eyes@x.com")
        nurse = ctx["nurse"]
        lic = ctx["license"]
        action = report_discipline(nurse["id"], scope="PRIVILEGE",
                                   action_type="REPRIMAND", effective_on="2026-08-01")
        acknowledge_discipline(action["id"], headers=CO1)

        resp = api_client.adjudicate_disciplinary_action(
            action["id"], {"outcome": "SUSTAINED"}, CO1
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = validate_success(
            api_client.adjudicate_disciplinary_action(
                action["id"], {"outcome": "SUSTAINED"}, CO2
            ),
            200,
        )
        assert ok["status"] == "ADJUDICATED"
        assert ok["adjudicated_by_user_id"] == "co-2"

        nurse_after = get_nurse(nurse["id"])
        assert nurse_after["credential_posture"] == "CLEAR", (
            "a sustained REPRIMAND is record-only for posture"
        )
        lic_after = validate_success(api_client.get_state_license(lic["id"], SPEC1), 200)
        assert lic_after["status"] == "ACTIVE"


class TestOptimisticConcurrency:
    def test_occ_nurse_patch_stale_version(self):
        """PRD §2.7: "The first is `PATCH /credentialing/nurses/{nurseId}`, the nurse
        profile patch. If `expected_nurse_version` does not equal the nurse's current
        `version` — because the record has advanced since the client last read it, for
        example through a privilege re-derivation that the client has not observed —
        the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "Both guarded operations increment the nurse's `version` by exactly
        1 on success."

        Design: Corner/cross_cutting_layers/occ_nurse_patch_stale_version
        """
        set_clock()
        nurse = create_nurse(full_name="Occ Patch", email="occ.patch@x.com")
        base_version = nurse["version"]

        first = validate_success(
            api_client.patch_nurse(
                nurse["id"],
                {"primary_state_of_residence": "TX",
                 "expected_nurse_version": base_version},
                SPEC1,
            ),
            200,
        )
        assert first["primary_state_of_residence"] == "TX"
        assert first["version"] == base_version + 1

        resp = api_client.patch_nurse(
            nurse["id"],
            {"primary_state_of_residence": "FL",
             "expected_nurse_version": base_version},
            SPEC2,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = get_nurse(nurse["id"])
        assert after["primary_state_of_residence"] == "TX", "the winner's write stands"
        assert after["version"] == base_version + 1

    def test_occ_privilege_eval_stale_version(self):
        """PRD §2.7: "The second is `POST /credentialing/privilege-evaluations`, the
        explicit multistate privilege evaluation. ... A mismatch with the nurse's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "The explicit evaluation always appends a `PrivilegeEvaluation` with
        `trigger_reason` `MANUAL`, updates `multistate_privilege_status` and
        `practice_scope` on the nurse, increments the nurse's `version` by 1, and
        recomputes posture."

        Design: Corner/cross_cutting_layers/occ_privilege_eval_stale_version
        """
        set_clock()
        nurse = create_nurse(full_name="Occ Eval", email="occ.eval@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-OE1")
        submit_license(lic["id"])
        psv = request_psv(lic["id"])
        record_psv_verified(psv["id"])
        validate_success(api_client.attest_license(lic["id"], VER1), 200)
        observed = get_nurse(nurse["id"])

        first = validate_success(
            api_client.create_privilege_evaluation(
                {"nurse_id": nurse["id"],
                 "expected_nurse_version": observed["version"]},
                SPEC1,
            ),
            201,
        )
        assert_privilege_evaluation(first)
        assert first["trigger_reason"] == "MANUAL"
        assert first["resulting_status"] == "ELIGIBLE_MULTISTATE"

        resp = api_client.create_privilege_evaluation(
            {"nurse_id": nurse["id"], "expected_nurse_version": observed["version"]},
            SPEC2,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        evals = list_privilege_evals(nurse["id"])
        assert len(evals) == 2, (
            "exactly the attest-time LICENSE_CHANGE row and the one MANUAL row exist"
        )
        assert evals[0]["trigger_reason"] == "LICENSE_CHANGE"
        assert evals[1]["trigger_reason"] == "MANUAL"
