"""Resource baseline claims: documented defaults, existence, required fields,
server-computed attribution, child-row immutability, and scoped listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    assert_encounter,
    assert_encounter_line,
    assert_program,
    assert_program_invariants,
    create_cycle,
    create_encounter,
    create_encounter_payload,
    create_member,
    create_member_payload,
    create_program,
    create_program_payload,
    create_provider,
    create_cycle_payload,
    get_success_data,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import OPS, STATE


class TestProgramBaseline:
    def test_program_created_with_documented_defaults(self):
        """PRD §3.1: "`completeness_threshold` defaults to 0.98 and is the minimum
        eligibility-benchmark completeness rate for an audit to pass. `accuracy_threshold`
        defaults to 0.95 and is the minimum sample accuracy rate. `provider_yellow_threshold`
        defaults to 0.02 and `provider_red_threshold` defaults to 0.05; they drive the
        provider scorecard tiers described in §3.4. `penalty_cap_percent` defaults to 0.10
        and caps an audit-driven penalty at that fraction of the cycle statement's
        provisional paid amount."
        PRD §2.10: "A freshly created program starts with `posture` `OPEN` and zero
        outstanding."

        Design: Corner/entities/program_created_with_documented_defaults
        """
        resp = api_client.create_program(
            create_program_payload(name="P-DEF", penalty_threshold_cents=100000), STATE)
        program = validate_success(resp, expected_status=201)
        assert_program(program)
        assert program["completeness_threshold"] == pytest.approx(0.98)
        assert program["accuracy_threshold"] == pytest.approx(0.95)
        assert program["provider_yellow_threshold"] == pytest.approx(0.02)
        assert program["provider_red_threshold"] == pytest.approx(0.05)
        assert program["penalty_cap_percent"] == pytest.approx(0.10)
        assert program["posture"] == "OPEN"
        assert program["penalties_outstanding_cents"] == 0
        assert program["version"] == 1
        assert_program_invariants(program)

    def test_program_get_not_found_returns_404(self):
        """PRD §2.8: "Every resource identifier in the path and body — program, cycle,
        member, provider, submitter, encounter, batch, audit, penalty, statement,
        scorecard — must exist; otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/program_get_not_found_returns_404
        """
        resp = api_client.get_program(NON_EXISTENT_UUID, STATE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMemberBaseline:
    def test_member_missing_required_field_returns_invalid_request(self):
        """PRD §2.8: "The body parses, all required fields are present, scalar and enum
        values are valid, amounts are not negative, and a `reduced_amount_cents` supplied
        outside its permitted range fails here; unknown fields are ignored. Violations
        return `ERR_INVALID_REQUEST`."

        Design: Corner/entities/member_missing_required_field_returns_invalid_request
        """
        program = create_program(name="P-REQ")
        payload = create_member_payload(program["id"], medicaid_id="M1")
        del payload["aid_category"]
        resp = api_client.create_member(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api_client.list_members(STATE, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0, f"no member may persist, got {meta['total_count']}"
        assert data == []


class TestEncounterIntakeBaseline:
    def test_encounter_attributed_cycle_is_server_computed(self):
        """PRD §3.4: "Attribution assigns the encounter's computed `attributed_cycle_id`
        to the `OPEN` cycle of the program whose half-open window contains the
        `service_from_date`; when no such cycle exists, intake is rejected with
        `ERR_NO_CYCLE_FOR_SERVICE_DATE`."
        PRD §3.4: "A successful intake lands in `RECEIVED` with `correction_sequence`
        zero, `validation_run_seq` zero, `batch_id` and `replaces_encounter_id` null, and
        the attributed cycle's `intake_encounter_count` incremented by one."

        Design: Corner/entities/encounter_attributed_cycle_is_server_computed
        """
        scenario = setup_basic_scenario(program_name="P-ATTR")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        resp = api_client.create_encounter(
            create_encounter_payload(program["id"], member["id"], provider["id"],
                                     encounter_ref="E1",
                                     service_from_date="2026-08-31", service_to_date="2026-08-31",
                                     paid_amount_cents=5000),
            OPS)
        encounter = validate_success(resp, expected_status=201)
        assert_encounter(encounter)
        # 2026-08-31 is inside the half-open window [2026-08-01, 2026-09-01)
        assert encounter["attributed_cycle_id"] == cycle["id"]
        assert encounter["status"] == "RECEIVED"
        assert encounter["correction_sequence"] == 0
        assert encounter["validation_run_seq"] == 0

    def test_encounter_lines_reverse_reachable_and_immutable(self):
        """PRD §3.4: "Encounter collections can be filtered by `program_id`, `member_id`,
        `provider_id`, `submitter_id`, `attributed_cycle_id`, `batch_id`,
        `replaces_encounter_id`, and `status`; an encounter's lines are exposed as a
        nested collection."
        PRD §2.5: "An EncounterLine and a ValidationFinding carry only `id` and
        `created_at`; both `updated_at` and `version` are absent from them, since lines
        and findings are immutable once written."

        Design: Corner/entities/encounter_lines_reverse_reachable_and_immutable
        """
        scenario = setup_basic_scenario(program_name="P-LINE")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        line = {
            "line_number": 1,
            "procedure_code": "99213",
            "units": 2,
            "billed_amount_cents": 7000,
            "paid_amount_cents": 7000,
        }
        encounter = create_encounter(program["id"], member["id"], provider["id"],
                                     encounter_ref="E1", paid_amount_cents=7000, lines=[line])
        data, meta = validate_paginated(api_client.list_encounter_lines(encounter["id"], OPS))
        assert meta["total_count"] == 1
        assert len(data) == 1
        row = data[0]
        assert_encounter_line(row)
        assert row["procedure_code"] == "99213"
        assert row["units"] == 2
        assert row["paid_amount_cents"] == 7000


class TestCycleBaseline:
    def test_cycle_effective_deadline_defaults_to_submission_deadline(self):
        """PRD §3.3: "A new cycle starts with `status` `OPEN`, `extension_status` `NONE`,
        and `effective_deadline_at` equal to `submission_deadline_at`."

        Design: Corner/entities/cycle_effective_deadline_defaults_to_submission_deadline
        """
        program = create_program(name="P-EFF")
        resp = api_client.create_cycle(create_cycle_payload(program["id"]), STATE)
        cycle = validate_success(resp, expected_status=201)
        assert cycle["effective_deadline_at"] == TEST_DEFAULTS["SUBMISSION_DEADLINE"]
        assert cycle["extension_status"] == "NONE"
        assert cycle["status"] == "OPEN"


class TestProviderListing:
    def test_providers_list_scoped_by_program_with_pagination_envelope(self):
        """PRD §3.2: "The provider list filters on `program_id`, `contract_status`, and
        `quality_tier`."
        PRD §2.3: "The `meta` object of every list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/providers_list_scoped_by_program_with_pagination_envelope
        """
        program_a = create_program(name="P-LA")
        program_b = create_program(name="P-LB")
        provider_a = create_provider(program_a["id"], npi="1111111111")
        create_provider(program_b["id"], npi="2222222222")
        data, meta = validate_paginated(api_client.list_providers(OPS, params={"program_id": program_a["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == provider_a["id"]
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"pagination meta missing {field}"
        assert meta["has_more"] is False
