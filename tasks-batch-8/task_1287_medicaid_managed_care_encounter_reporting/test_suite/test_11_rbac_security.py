"""RBAC and caller-context security: header presence, role exclusivity, delegated
submitter identity scoping, and segregation of duties on seal/transmit."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_audit,
    create_batch,
    create_encounter,
    create_encounter_payload,
    create_member_payload,
    create_program_payload,
    create_submitter,
    create_validated_encounter,
    get_success_data,
    make_delegated_submitter_headers,
    make_mco_compliance_headers,
    make_mco_encounter_ops_headers,
    seal_batch,
    setup_basic_scenario,
    stage_encounter,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import FIN, OPS, OPS_SEALER, STATE


class TestCallerContext:
    def test_missing_auth_header_returns_unauthenticated(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in which
        they act. ... A request with a missing or malformed header, or a role outside
        this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api_client.create_program(
            create_program_payload(name="P-NOAUTH", penalty_threshold_cents=100000), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestDelegatedSubmitterIdentity:
    def test_delegated_submitter_creates_encounter_with_own_identity(self):
        """PRD §2.1: "When `X-User-Role` is `DelegatedSubmitter`, `X-User-ID` is the
        `id` of the acting Submitter entity; ownership checks on any resource that
        references a Submitter compare the resource's submitter foreign-key field to
        `X-User-ID`."
        PRD §3.2: "when the caller's role is `DelegatedSubmitter`, the encounter payload
        is required to carry a `submitter_id`, and it must equal the caller's
        `X-User-ID`; a mismatch is an authorization failure rejected with
        `ERR_FORBIDDEN_FOR_ROLE`, evaluated before the body is even examined."

        Design: Corner/rbac/delegated_submitter_creates_encounter_with_own_identity
        """
        scenario = setup_basic_scenario(program_name="P-R1")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        submitter = create_submitter(program["id"])
        payload = create_encounter_payload(program["id"], member["id"], provider["id"], encounter_ref="DE1")
        payload["submitter_id"] = submitter["id"]
        resp = api_client.create_encounter(payload, make_delegated_submitter_headers(submitter["id"]))
        encounter = validate_success(resp, expected_status=201)
        assert encounter["submitter_id"] == submitter["id"]
        assert encounter["status"] == "RECEIVED"

    def test_delegated_submitter_cannot_manage_members(self):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §2.1: "An `McoEncounterOps` caller is the plan's encounter operations team:
        it manages the roster (members, providers, submitters)"

        Design: Corner/rbac/delegated_submitter_cannot_manage_members
        """
        scenario = setup_basic_scenario(program_name="P-R2")
        program = scenario["program"]
        submitter = create_submitter(program["id"])
        resp = api_client.create_member(
            create_member_payload(program["id"], medicaid_id="M9"),
            make_delegated_submitter_headers(submitter["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestRoleExclusivity:
    def test_compliance_cannot_validate_encounters(self):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §2.1: "An `McoCompliance` caller transmits sealed batches to the state,
        requests deadline extensions, and appeals penalty assessments."

        Design: Corner/rbac/compliance_cannot_validate_encounters
        """
        scenario = setup_basic_scenario(program_name="P-R3")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1")
        assert encounter["status"] == "RECEIVED"
        resp = api_client.validate_encounter(encounter["id"], TEST_USERS["mco_compliance_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = get_success_data(api_client.get_encounter(encounter["id"], OPS))
        assert after["status"] == "RECEIVED"

    def test_ops_cannot_transmit_and_finance_cannot_determine(self):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §2.1: "An `McoCompliance` caller transmits sealed batches to the state,
        requests deadline extensions, and appeals penalty assessments."
        PRD §2.1: "A `StateAgency` caller is the state Medicaid regulator: it configures
        programs, cycles, and rate schedules, acknowledges transmitted batches, opens
        and determines audits, decides extension requests and penalty appeals, closes
        cycles, and drives the test clock."

        Design: Corner/rbac/ops_cannot_transmit_and_finance_cannot_determine
        """
        scenario = setup_basic_scenario(program_name="P-R4")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        audit = create_audit(cycle["id"], sample_size=5, defect_count=0)

        resp_t = api_client.transmit_batch(batch["id"], make_mco_encounter_ops_headers("ops-2"))
        validate_error(resp_t, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp_d = api_client.determine_audit(audit["id"], FIN)
        validate_error(resp_d, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestSegregationOfDuties:
    def test_same_user_cannot_seal_and_transmit_segregation_of_duties(self):
        """PRD §3.5: "segregation of duties forbids the transmitter from being the
        sealer — a caller whose `X-User-ID` equals the batch's `sealed_by_user_id` is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/same_user_cannot_seal_and_transmit_segregation_of_duties
        """
        scenario = setup_basic_scenario(program_name="P-R5")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        sealed = get_success_data(api_client.seal_batch(batch["id"], make_mco_encounter_ops_headers("shared-1")))
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_user_id"] == "shared-1"

        # The same X-User-ID may not transmit, even under the permitted role.
        resp = api_client.transmit_batch(sealed["id"], make_mco_compliance_headers("shared-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api_client.get_batch(sealed["id"], OPS))
        assert after["status"] == "SEALED"
