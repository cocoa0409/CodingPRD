"""Transmission gates, the fixed default clock, and the validation pipeline's
stage ordering (state before business safety; referential before fiscal)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    acknowledge_batch,
    create_acknowledged_encounter,
    create_batch,
    create_encounter_payload,
    create_validated_encounter,
    create_member,
    create_program,
    create_provider,
    create_rate_schedule,
    create_cycle,
    create_submitter,
    get_success_data,
    seal_batch,
    set_clock,
    setup_basic_scenario,
    setup_determined_fail_audit,
    stage_encounter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import COMP_TRANSMITTER, OPS, OPS_SEALER, STATE


class TestClockSemantics:
    def test_clock_default_makes_transmit_on_time(self):
        """PRD §2.4: "Before any client call, the logical clock reads exactly
        2026-08-01T00:00:00Z (a fixed startup default)."
        PRD §3.5: "The batch's `late` flag, false until then, is computed at this
        instant: it is true exactly when `transmitted_at` falls strictly after the
        cycle's `effective_deadline_at`, with a transmission exactly at the deadline
        counting as on time."

        Design: Corner/endpoints/clock_default_makes_transmit_on_time
        """
        scenario = setup_basic_scenario(program_name="P-EP3")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        transmitted = validate_success(api_client.transmit_batch(batch["id"], COMP_TRANSMITTER))
        assert transmitted["transmitted_at"] == TEST_DEFAULTS["CLOCK_DEFAULT"]
        assert transmitted["late"] is False
        data, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0


class TestTransmitPipelinePriority:
    def _setup_restricted_program_with_draft_batch(self):
        """Program at threshold 0 (RESTRICTED from creation) + VALIDATED encounter +
        an empty DRAFT batch."""
        program = create_program(name="P-PRIO1", penalty_threshold_cents=0)
        assert program["posture"] == "RESTRICTED", "Setup failed: 0 >= 0 must flip posture to RESTRICTED"
        cycle = create_cycle(program["id"])
        member = create_member(program["id"])
        provider = create_provider(program["id"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        return {"program": program, "cycle": cycle, "e1": e1, "batch": batch}

    def test_transmit_draft_batch_while_restricted_state_beats_safety(self):
        """PRD §2.8: "A request that fails an earlier stage is rejected immediately and
        never reaches a later stage, so when several rules could fire on the same
        malformed request, the earliest stage's error is the one returned."
        PRD §3.5: "The batch must be `SEALED` (`ERR_INVALID_STATE_TRANSITION` otherwise)
        and its cycle still `OPEN` (`ERR_CYCLE_CLOSED` otherwise); the program's
        `posture` must be `OPEN`, a `RESTRICTED` program drawing
        `ERR_PROGRAM_RESTRICTED`"

        Design: Difficulty/priority_pair_validation_conflict/transmit_draft_batch_while_restricted_state_beats_safety
        """
        fx = self._setup_restricted_program_with_draft_batch()
        resp = api_client.transmit_batch(fx["batch"]["id"], COMP_TRANSMITTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_transmit_sealed_batch_on_restricted_program_surfaces_posture_gate(self):
        """PRD §2.8: "A request that fails an earlier stage is rejected immediately and
        never reaches a later stage, so when several rules could fire on the same
        malformed request, the earliest stage's error is the one returned."
        PRD §2.10: "A `RESTRICTED` posture blocks batch transmission with
        `ERR_PROGRAM_RESTRICTED` until the outstanding balance is worked down."

        Design: Difficulty/priority_pair_validation_conflict/transmit_draft_batch_while_restricted_state_beats_safety
        """
        fx = self._setup_restricted_program_with_draft_batch()
        batch = stage_encounter(fx["batch"], fx["e1"]["id"])
        batch = seal_batch(batch)
        resp = api_client.transmit_batch(batch["id"], COMP_TRANSMITTER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_RESTRICTED)


class TestIntakePipelinePriority:
    def test_encounter_create_referential_beats_fiscal(self):
        """PRD §2.8: "A request that fails an earlier stage is rejected immediately and
        never reaches a later stage, so when several rules could fire on the same
        malformed request, the earliest stage's error is the one returned."
        PRD §3.4: "Intake evaluates the pipeline of §2.8 in order: after body
        well-formedness and roster existence, the suspended-party gates fire
        (`ERR_PROVIDER_SUSPENDED`, `ERR_SUBMITTER_SUSPENDED`), then cycle attribution,
        then the fiscal checks, then reference uniqueness."

        Design: Difficulty/priority_pair_validation_conflict/encounter_create_referential_beats_fiscal
        """
        scenario = setup_basic_scenario(program_name="P-PRIO2")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        payload = create_encounter_payload(
            program["id"], member["id"], provider["id"], encounter_ref="EX",
            service_from_date="2026-10-05", service_to_date="2026-10-05",
            paid_amount_cents=9999,
            lines=[{"line_number": 1, "procedure_code": "99213", "units": 1,
                    "billed_amount_cents": 10000, "paid_amount_cents": 100}])
        resp = api_client.create_encounter(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_NO_CYCLE_FOR_SERVICE_DATE)
        _data, meta = validate_paginated(api_client.list_encounters(OPS, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0, "nothing may persist from the rejected intake"

    def test_encounter_create_outside_cycle_window_rejected_when_fiscally_consistent(self):
        """PRD §3.4: "Attribution assigns the encounter's computed `attributed_cycle_id`
        to the `OPEN` cycle of the program whose half-open window contains the
        `service_from_date`; when no such cycle exists, intake is rejected with
        `ERR_NO_CYCLE_FOR_SERVICE_DATE`."
        PRD §3.4: "Intake evaluates the pipeline of §2.8 in order: after body
        well-formedness and roster existence, the suspended-party gates fire
        (`ERR_PROVIDER_SUSPENDED`, `ERR_SUBMITTER_SUSPENDED`), then cycle attribution,
        then the fiscal checks, then reference uniqueness."

        Design: Difficulty/priority_pair_validation_conflict/encounter_create_referential_beats_fiscal
        """
        scenario = setup_basic_scenario(program_name="P-PRIO2B")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        # Header equals the sum of lines here; only cycle attribution can fail.
        payload = create_encounter_payload(
            program["id"], member["id"], provider["id"], encounter_ref="EY",
            service_from_date="2026-10-05", service_to_date="2026-10-05",
            paid_amount_cents=10000,
            lines=[{"line_number": 1, "procedure_code": "99213", "units": 1,
                    "billed_amount_cents": 10000, "paid_amount_cents": 10000}])
        resp = api_client.create_encounter(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_NO_CYCLE_FOR_SERVICE_DATE)
        _data, meta = validate_paginated(api_client.list_encounters(OPS, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0

    def test_encounter_create_header_lines_mismatch_rejected(self):
        """PRD §3.4: "Fiscally, the header `paid_amount_cents` must equal the sum of the
        lines' paid amounts, otherwise `ERR_HEADER_LINES_PAID_MISMATCH`"

        Design: Corner/validations/encounter_create_header_lines_mismatch_rejected
        """
        scenario = setup_basic_scenario(program_name="P-V2")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        payload = create_encounter_payload(
            program["id"], member["id"], provider["id"], encounter_ref="E1",
            paid_amount_cents=10000,
            lines=[{"line_number": 1, "procedure_code": "99213", "units": 1,
                    "billed_amount_cents": 8000, "paid_amount_cents": 8000}])
        resp = api_client.create_encounter(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_HEADER_LINES_PAID_MISMATCH)

    def test_encounter_create_paid_exceeds_billed_rejected(self):
        """PRD §3.4: "any line violating the paid-to-billed or units constraints is
        rejected with `ERR_PAID_EXCEEDS_BILLED`."
        PRD §3.4: "a line `paid_amount_cents` that may not be negative and may not
        exceed the line's billed amount."

        Design: Corner/validations/encounter_create_paid_exceeds_billed_rejected
        """
        scenario = setup_basic_scenario(program_name="P-V1")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        payload = create_encounter_payload(
            program["id"], member["id"], provider["id"], encounter_ref="E1",
            paid_amount_cents=12000,
            lines=[{"line_number": 1, "procedure_code": "99213", "units": 1,
                    "billed_amount_cents": 10000, "paid_amount_cents": 12000}])
        resp = api_client.create_encounter(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_PAID_EXCEEDS_BILLED)
        _data, meta = validate_paginated(api_client.list_encounters(OPS, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0, "nothing may persist from the rejected intake"


class TestSuspendedParties:
    def test_suspended_provider_and_submitter_block_encounter_create(self):
        """PRD §3.2: "Once suspended, two consequences follow: encounter intake naming
        that provider fails with `ERR_PROVIDER_SUSPENDED`, and the referential edit
        `E202_PROVIDER_INACTIVE` fires at validation time for the provider's in-flight
        encounters."
        PRD §3.2: "Suspending a submitter moves it to `SUSPENDED`, after which encounter
        intake carrying that `submitter_id` fails with `ERR_SUBMITTER_SUSPENDED`."

        Design: Corner/validations/suspended_provider_and_submitter_block_encounter_create
        """
        scenario = setup_basic_scenario(program_name="P-V10")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        get_success_data(api_client.suspend_provider(provider["id"], OPS))
        provider2 = create_provider(program["id"], npi="9876543210")
        submitter = create_submitter(program["id"])
        get_success_data(api_client.suspend_submitter(submitter["id"], OPS))

        payload_p = create_encounter_payload(program["id"], member["id"], provider["id"], encounter_ref="E1")
        resp_p = api_client.create_encounter(payload_p, OPS)
        validate_error(resp_p, ApiErrorId.ERR_PROVIDER_SUSPENDED)

        payload_s = create_encounter_payload(program["id"], member["id"], provider2["id"], encounter_ref="E2")
        payload_s["submitter_id"] = submitter["id"]
        resp_s = api_client.create_encounter(payload_s, OPS)
        validate_error(resp_s, ApiErrorId.ERR_SUBMITTER_SUSPENDED)


class TestLatePenaltyCascade:
    def test_late_transmit_penalty_posture_cascade(self):
        """PRD §3.5: "A late transmission sets off a three-link cascade. First, the
        system creates a PenaltyAssessment with `reason` `LATE_SUBMISSION`, status
        `ASSESSED`, and a null `audit_id`; its amount is a flat 500000 cents plus 100000
        cents for each whole day late, where whole days are counted at 86400-second
        granularity and any partial day is discarded — a file transmitted one second
        past the deadline is late but owes only the flat amount. Second, that amount is
        added to the program's `penalties_outstanding_cents`. Third, the posture is
        recomputed per §2.10, and if the outstanding total now reaches
        `penalty_threshold_cents` the program flips to `RESTRICTED`, gating all further
        transmissions for the program."

        Design: Difficulty/transitive_cascade/late_transmit_penalty_posture_cascade
        """
        program = create_program(name="P-CAS2", penalty_threshold_cents=650000)
        cycle = create_cycle(program["id"])
        member = create_member(program["id"])
        provider = create_provider(program["id"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        set_clock("2026-09-17T00:00:01Z")
        transmitted = validate_success(api_client.transmit_batch(batch["id"], COMP_TRANSMITTER))
        assert transmitted["late"] is True

        penalties, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 1
        penalty = penalties[0]
        assert penalty["reason"] == "LATE_SUBMISSION"
        assert penalty["status"] == "ASSESSED"
        # floor(172801s / 86400s) = 2 whole days late => 500000 + 2 * 100000
        assert penalty["amount_cents"] == 700000

        program_after = get_success_data(api_client.get_program(program["id"], STATE))
        assert program_after["penalties_outstanding_cents"] == 700000
        assert program_after["posture"] == "RESTRICTED", "700000 >= 650000"

    def test_late_penalty_day_floor_at_zero_days_late(self):
        """PRD §3.5: "its amount is a flat 500000 cents plus 100000 cents for each whole
        day late, where whole days are counted at 86400-second granularity and any
        partial day is discarded — a file transmitted one second past the deadline is
        late but owes only the flat amount."
        PRD §3.5: "it is true exactly when `transmitted_at` falls strictly after the
        cycle's `effective_deadline_at`, with a transmission exactly at the deadline
        counting as on time."

        Design: Corner/calculations/late_penalty_day_floor_at_zero_days_late
        """
        scenario = setup_basic_scenario(program_name="P-CALC6")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        set_clock("2026-09-15T00:00:01Z")
        transmitted = validate_success(api_client.transmit_batch(batch["id"], COMP_TRANSMITTER))
        assert transmitted["late"] is True
        penalties, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 1
        # floor(1s / 86400s) = 0 days => flat component only
        assert penalties[0]["amount_cents"] == 500000

    def test_transmit_exactly_at_deadline_is_on_time(self):
        """PRD §3.5: "The batch's `late` flag, false until then, is computed at this
        instant: it is true exactly when `transmitted_at` falls strictly after the
        cycle's `effective_deadline_at`, with a transmission exactly at the deadline
        counting as on time."
        PRD §3.5: "A late transmission sets off a three-link cascade. First, the system
        creates a PenaltyAssessment with `reason` `LATE_SUBMISSION`, status `ASSESSED`,
        and a null `audit_id`"

        Design: Difficulty/transitive_cascade/late_transmit_penalty_posture_cascade
        """
        scenario = setup_basic_scenario(program_name="P-CAS2B")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        # Exactly at the deadline: equality is on-time, so no cascade link fires.
        set_clock(TEST_DEFAULTS["SUBMISSION_DEADLINE"])
        transmitted = validate_success(api_client.transmit_batch(batch["id"], COMP_TRANSMITTER))
        assert transmitted["late"] is False
        assert transmitted["transmitted_at"] == TEST_DEFAULTS["SUBMISSION_DEADLINE"]
        _data, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0, "an on-time transmit spawns no penalty"
        program_after = get_success_data(api_client.get_program(program["id"], STATE))
        assert program_after["penalties_outstanding_cents"] == 0
        assert program_after["posture"] == "OPEN"
