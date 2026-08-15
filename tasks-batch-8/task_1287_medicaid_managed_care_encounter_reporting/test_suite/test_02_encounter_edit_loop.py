"""Encounter intake filters, the edit-correction loop, and cross-entity validation gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    EDIT_CODES,
    create_encounter,
    create_encounter_payload,
    create_validated_encounter,
    get_scorecard_for,
    get_success_data,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import OPS, STATE


class TestEncounterListing:
    def test_encounters_list_filters_by_status_and_paginates(self):
        """PRD §3.4: "Encounter collections can be filtered by `program_id`, `member_id`,
        `provider_id`, `submitter_id`, `attributed_cycle_id`, `batch_id`,
        `replaces_encounter_id`, and `status`; an encounter's lines are exposed as a
        nested collection."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a
        number of items from the start of the result set and defaults to 0."

        Design: Corner/endpoints/encounters_list_filters_by_status_and_paginates
        """
        scenario = setup_basic_scenario(program_name="P-EP1")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        e1 = create_validated_encounter(program["id"], scenario["cycle"]["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        e2 = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E2",
                              service_from_date="2026-08-11", service_to_date="2026-08-11",
                              diagnosis_codes=["9XX"], paid_amount_cents=3000,
                              lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                      "billed_amount_cents": 3000, "paid_amount_cents": 3000}])
        rejected = get_success_data(api_client.validate_encounter(e2["id"], OPS))
        assert rejected["status"] == "REJECTED", "Setup failed: e2 must be REJECTED"

        data, meta = validate_paginated(
            api_client.list_encounters(OPS, params={"program_id": program["id"], "status": "REJECTED"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == e2["id"]
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"pagination meta missing {field}"

        data_all, meta_all = validate_paginated(
            api_client.list_encounters(OPS, params={"program_id": program["id"]}))
        assert meta_all["total_count"] == 2


class TestEditCorrectionLoop:
    def test_warn_finding_accepts_encounter_with_warning(self):
        """PRD §3.4: "A run that produces zero `FATAL` findings moves the encounter
        `RECEIVED → VALIDATED` (warnings may still be attached); a run with one or more
        `FATAL` findings moves it `RECEIVED → REJECTED`."
        PRD §3.4: "The syntax tier covers `E101_SERVICE_DATE_ORDER` and
        `E102_DIAG_FORMAT`; the referential tier covers `E201_MEMBER_NOT_ELIGIBLE` and
        `E202_PROVIDER_INACTIVE`; the business tier covers `E301_DUPLICATE_SUSPECT` and
        `E302_UNITS_HIGH`."

        Design: Corner/endpoints/warn_finding_accepts_encounter_with_warning
        """
        scenario = setup_basic_scenario(program_name="P-EP2")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        encounter = create_encounter(
            program["id"], member["id"], provider["id"], encounter_ref="E1",
            paid_amount_cents=9500,
            lines=[{"line_number": 1, "procedure_code": "99213", "units": 95,
                    "billed_amount_cents": 9500, "paid_amount_cents": 9500}])
        validated = validate_success(api_client.validate_encounter(encounter["id"], OPS))
        assert validated["status"] == "VALIDATED"

        findings, fmeta = validate_paginated(api_client.list_encounter_findings(encounter["id"], OPS))
        assert fmeta["total_count"] == 1
        finding = findings[0]
        assert finding["edit_code"] == EDIT_CODES["E302_UNITS_HIGH"]
        assert finding["severity"] == "WARN"
        assert finding["tier"] == "BUSINESS"
        assert finding["origin"] == "MCO_EDIT"

        scorecard = get_scorecard_for(provider["id"], cycle["id"])
        assert scorecard["run_count"] == 1
        assert scorecard["fatal_finding_count"] == 0

    def test_validate_from_validated_returns_invalid_state(self):
        """PRD §3.4: "An `McoEncounterOps` operator runs the companion-guide edits
        against a `RECEIVED` encounter (any other state is rejected with
        `ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.4: "Each run increments the encounter's `validation_run_seq` and persists
        one `ValidationFinding` per fired edit, stamped with the producing `run_seq`"

        Design: Corner/state_machines/validate_from_validated_returns_invalid_state
        """
        scenario = setup_basic_scenario(program_name="P-SM1")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        encounter = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                               encounter_ref="E1")
        resp = api_client.validate_encounter(encounter["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_encounter(encounter["id"], OPS))
        assert after["validation_run_seq"] == 1, f"no new run may be recorded, got {after['validation_run_seq']}"
        assert after["status"] == "VALIDATED"

    def test_correction_loop_cycles_rejected_to_validated(self):
        """PRD §3.4: "On a `REJECTED` encounter, the operator submits corrected values
        for any of `service_from_date`, `service_to_date`, `place_of_service`,
        `diagnosis_codes`, `paid_amount_cents`, and `lines`; the edits re-run over the
        corrected record with a fresh `validation_run_seq`, new findings are appended
        alongside the retained prior-run findings, and the encounter moves
        `REJECTED → VALIDATED` when the re-run is clean of `FATAL` findings or stays
        `REJECTED → REJECTED` when it is not."
        PRD §3.4: "Every validate or correct run — including correction loops that fail
        again — counts against the provider's quality measurement below."

        Design: Difficulty/non_linear_state_machine/encounter_correction_loop_cycles_rejected_to_validated
        """
        scenario = setup_basic_scenario(program_name="P-LOOP")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1",
                                     diagnosis_codes=["9XX"])
        r1 = get_success_data(api_client.validate_encounter(encounter["id"], OPS))
        assert r1["status"] == "REJECTED", "Setup failed: run 1 must reject on malformed diagnosis"
        r2 = get_success_data(api_client.correct_encounter(encounter["id"], {"diagnosis_codes": ["7QQ"]}, OPS))
        assert r2["status"] == "REJECTED", "Setup failed: run 2 must reject on malformed diagnosis"

        r3 = get_success_data(api_client.correct_encounter(encounter["id"], {"diagnosis_codes": ["E11"]}, OPS))
        assert r3["status"] == "VALIDATED"
        assert r3["correction_sequence"] == 0, "in-place correct never increments correction_sequence"
        assert r3["validation_run_seq"] == 3

        scorecard = get_scorecard_for(provider["id"], cycle["id"])
        assert scorecard["run_count"] == 3
        assert scorecard["fatal_finding_count"] == 2, "E102 fired on run 1 and run 2"
        assert scorecard["tier"] == "RED", "error_rate 0.6667 >= 0.05"

    def test_correction_loop_retains_findings_across_runs(self):
        """PRD §3.4: "the edits re-run over the corrected record with a fresh
        `validation_run_seq`, new findings are appended alongside the retained prior-run
        findings"
        PRD §3.4: "an encounter's findings can be listed across all runs, filterable by
        `run_seq` and `severity`."

        Design: Difficulty/non_linear_state_machine/encounter_correction_loop_cycles_rejected_to_validated
        """
        scenario = setup_basic_scenario(program_name="P-LOOP2")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1",
                                     diagnosis_codes=["9XX"])
        get_success_data(api_client.validate_encounter(encounter["id"], OPS))
        get_success_data(api_client.correct_encounter(encounter["id"], {"diagnosis_codes": ["7QQ"]}, OPS))
        final = get_success_data(api_client.correct_encounter(encounter["id"], {"diagnosis_codes": ["E11"]}, OPS))
        assert final["status"] == "VALIDATED"

        findings, meta = validate_paginated(api_client.list_encounter_findings(encounter["id"], OPS))
        run_seqs = {f["run_seq"] for f in findings}
        assert run_seqs == {1, 2, 3}, f"prior-run findings must be retained, got run_seqs {run_seqs}"
        e102_codes = [f for f in findings if f["edit_code"] == EDIT_CODES["E102_DIAG_FORMAT"]]
        assert len(e102_codes) == 2
        assert all(f["severity"] == "FATAL" and f["tier"] == "SYNTAX" and f["origin"] == "MCO_EDIT"
                   for f in e102_codes)


class TestMemberEnrollmentGate:
    def test_encounter_validation_gated_by_member_enrollment_state(self):
        """PRD §3.2: "the member's `enrolled_to` is set to that date, and from then on
        the referential edit `E201_MEMBER_NOT_ELIGIBLE` fires during validation for any
        encounter whose service dates fall outside the closed enrollment interval from
        `enrolled_from` through `enrolled_to`."
        PRD §3.4: "a run with one or more `FATAL` findings moves it
        `RECEIVED → REJECTED`."

        Design: Difficulty/cross_entity_state_dependency/encounter_validation_gated_by_member_enrollment_state
        """
        scenario = setup_basic_scenario(program_name="P-X1")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        disenrolled = get_success_data(api_client.disenroll_member(member["id"], {"disenrolled_date": "2026-08-05"}, OPS))
        assert disenrolled["status"] == "DISENROLLED"
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1",
                                     service_from_date="2026-08-10", service_to_date="2026-08-10")
        rejected = validate_success(api_client.validate_encounter(encounter["id"], OPS))
        assert rejected["status"] == "REJECTED"

        findings, _meta = validate_paginated(api_client.list_encounter_findings(encounter["id"], OPS))
        assert len(findings) >= 1
        finding = findings[0]
        assert finding["edit_code"] == EDIT_CODES["E201_MEMBER_NOT_ELIGIBLE"]
        assert finding["tier"] == "REFERENTIAL"
        assert finding["severity"] == "FATAL"
        assert finding["origin"] == "MCO_EDIT"

    def test_encounter_inside_enrollment_window_validates_clean(self):
        """PRD §3.2: "the referential edit `E201_MEMBER_NOT_ELIGIBLE` fires during
        validation for any encounter whose service dates fall outside the closed
        enrollment interval from `enrolled_from` through `enrolled_to`."
        PRD §3.4: "A run that produces zero `FATAL` findings moves the encounter
        `RECEIVED → VALIDATED` (warnings may still be attached)"

        Design: Difficulty/cross_entity_state_dependency/encounter_validation_gated_by_member_enrollment_state
        """
        scenario = setup_basic_scenario(program_name="P-X1B")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        get_success_data(api_client.disenroll_member(member["id"], {"disenrolled_date": "2026-08-05"}, OPS))
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E-IN",
                                     service_from_date="2026-08-03", service_to_date="2026-08-03")
        validated = validate_success(api_client.validate_encounter(encounter["id"], OPS))
        assert validated["status"] == "VALIDATED", (
            "service date 2026-08-03 is inside the closed enrollment interval "
            "[2026-08-01, 2026-08-05], so E201 must not fire"
        )
        findings, meta = validate_paginated(api_client.list_encounter_findings(encounter["id"], OPS))
        assert all(f["edit_code"] != EDIT_CODES["E201_MEMBER_NOT_ELIGIBLE"] for f in findings)
