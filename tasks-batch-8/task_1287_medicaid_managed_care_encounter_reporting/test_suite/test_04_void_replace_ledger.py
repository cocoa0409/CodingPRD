"""Void and replace rework, the cycle net-accepted ledger, and duplicate-ref scoping."""
import pytest

from test_helpers import (
    ApiErrorId,
    EDIT_CODES,
    acknowledge_batch,
    create_acknowledged_encounter,
    create_batch,
    create_encounter,
    create_validated_encounter,
    get_success_data,
    replace_encounter,
    seal_batch,
    setup_basic_scenario,
    setup_partial_batch_with_denial,
    stage_encounter,
    transmit_batch,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import OPS, STATE


class TestVoidPreconditions:
    def test_void_from_validated_returns_not_voidable(self):
        """PRD §3.7: "Voiding is the simpler leg: an `ACKNOWLEDGED` encounter — and only
        an `ACKNOWLEDGED` one, otherwise `ERR_ENCOUNTER_NOT_VOIDABLE` — moves to the
        terminal `VOIDED` state"

        Design: Corner/state_machines/void_from_validated_returns_not_voidable
        """
        scenario = setup_basic_scenario(program_name="P-SM2")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        encounter = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                               encounter_ref="E1")
        resp = api_client.void_encounter(encounter["id"], {"void_reason": "duplicate"}, OPS)
        validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_VOIDABLE)
        after = get_success_data(api_client.get_encounter(encounter["id"], OPS))
        assert after["status"] == "VALIDATED"


class TestReplacePreconditions:
    def test_replace_from_received_returns_not_replaceable(self):
        """PRD §3.7: "Replacement by an `McoEncounterOps` operator is admissible from
        `DENIED` or `ACKNOWLEDGED` only — any other status draws
        `ERR_ENCOUNTER_NOT_REPLACEABLE`"

        Design: Corner/state_machines/replace_from_received_returns_not_replaceable
        """
        scenario = setup_basic_scenario(program_name="P-SM3")
        program, member, provider = scenario["program"], scenario["member"], scenario["provider"]
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1")
        assert encounter["status"] == "RECEIVED"
        resp = api_client.replace_encounter(encounter["id"], {
            "encounter_ref": "E1R",
            "service_from_date": "2026-08-10",
            "service_to_date": "2026-08-10",
            "place_of_service": "11",
            "diagnosis_codes": ["Z00"],
            "paid_amount_cents": 10000,
            "lines": [{"line_number": 1, "procedure_code": "99213", "units": 1,
                       "billed_amount_cents": 10000, "paid_amount_cents": 10000}],
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_REPLACEABLE)
        after = get_success_data(api_client.get_encounter(encounter["id"], OPS))
        assert after["status"] == "RECEIVED"


class TestTerminalVoided:
    def test_terminal_voided_lockdown(self):
        """PRD §3.7: "Voiding is the simpler leg: an `ACKNOWLEDGED` encounter — and only
        an `ACKNOWLEDGED` one, otherwise `ERR_ENCOUNTER_NOT_VOIDABLE` — moves to the
        terminal `VOIDED` state, optionally recording a `void_reason`, and the cycle's
        net-accepted count and paid total each decrement by the voided encounter's
        contribution."
        PRD §3.4: "An `McoEncounterOps` operator runs the companion-guide edits against a
        `RECEIVED` encounter (any other state is rejected with
        `ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/terminal_voided_lockdown
        """
        scenario = setup_basic_scenario(program_name="P-SM4")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        outcome = create_acknowledged_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                                encounter_ref="E1")
        encounter = outcome["encounter"]
        voided = validate_success(api_client.void_encounter(encounter["id"], {"void_reason": "submitted in error"}, OPS))
        assert voided["status"] == "VOIDED"

        resp_second = api_client.void_encounter(encounter["id"], {"void_reason": "again"}, OPS)
        validate_error(resp_second, ApiErrorId.ERR_ENCOUNTER_NOT_VOIDABLE)
        resp_validate = api_client.validate_encounter(encounter["id"], OPS)
        validate_error(resp_validate, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        cycle_after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert cycle_after["net_accepted_encounter_count"] == 0
        assert cycle_after["net_accepted_paid_cents"] == 0


class TestCycleLedgerCompensation:
    def test_replace_round_trip_restores_cycle_ledger(self):
        """PRD §3.7: "When the original was `ACKNOWLEDGED`, replacement additionally
        fires the ledger compensation leg: the cycle's `net_accepted_encounter_count` and
        `net_accepted_paid_cents` each decrement by the original's contribution, and when
        the replacement eventually reaches `ACKNOWLEDGED` the ledger re-increments by the
        replacement's contribution."

        Design: Difficulty/compensating_invariant/replace_round_trip_restores_cycle_ledger
        """
        scenario = setup_basic_scenario(program_name="P-INV1", with_rate_schedule=True)
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        o1 = create_acknowledged_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                           encounter_ref="E1", paid_amount_cents=10000)
        o2 = create_acknowledged_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                           encounter_ref="E2", paid_amount_cents=20000,
                                           service_from_date="2026-08-11", service_to_date="2026-08-11",
                                           billed_amount_cents=20000)
        e1 = o1["encounter"]

        before = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert before["net_accepted_encounter_count"] == 2
        assert before["net_accepted_paid_cents"] == 30000

        replacement = validate_success(api_client.replace_encounter(e1["id"], {
            "encounter_ref": "E1R",
            "service_from_date": "2026-08-10",
            "service_to_date": "2026-08-10",
            "place_of_service": "11",
            "diagnosis_codes": ["Z00"],
            "paid_amount_cents": 10000,
            "lines": [{"line_number": 1, "procedure_code": "99213", "units": 1,
                       "billed_amount_cents": 10000, "paid_amount_cents": 10000}],
        }, OPS), expected_status=201)
        assert replacement["replaces_encounter_id"] == e1["id"]
        assert replacement["correction_sequence"] == 1

        mid = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert mid["net_accepted_encounter_count"] == 1, "compensation leg removes the superseded original"
        assert mid["net_accepted_paid_cents"] == 20000

        r_validated = get_success_data(api_client.validate_encounter(replacement["id"], OPS))
        assert r_validated["status"] == "VALIDATED"
        batch2 = create_batch(cycle["id"])
        batch2 = stage_encounter(batch2, replacement["id"])
        batch2 = seal_batch(batch2)
        batch2 = transmit_batch(batch2)
        acknowledge_batch(batch2, [{"encounter_id": replacement["id"], "outcome": "ACCEPTED"}])

        after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert after["net_accepted_encounter_count"] == 2, "ledger restored exactly after replacement acknowledged"
        assert after["net_accepted_paid_cents"] == 30000

        original = get_success_data(api_client.get_encounter(e1["id"], OPS))
        assert original["status"] == "SUPERSEDED"
        final_replacement = get_success_data(api_client.get_encounter(replacement["id"], OPS))
        assert final_replacement["status"] == "ACKNOWLEDGED"
        assert final_replacement["correction_sequence"] == 1

    def test_replace_acknowledged_reincrements_ledger_by_replacement_contribution(self):
        """PRD §3.7: "When the original was `ACKNOWLEDGED`, replacement additionally
        fires the ledger compensation leg: the cycle's `net_accepted_encounter_count`
        and `net_accepted_paid_cents` each decrement by the original's contribution, and
        when the replacement eventually reaches `ACKNOWLEDGED` the ledger re-increments
        by the replacement's contribution."

        Design: Difficulty/compensating_invariant/replace_round_trip_restores_cycle_ledger
        """
        scenario = setup_basic_scenario(program_name="P-INV1B", with_rate_schedule=True)
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        outcome = create_acknowledged_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                                encounter_ref="E1", paid_amount_cents=10000)
        e1 = outcome["encounter"]
        before = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert before["net_accepted_encounter_count"] == 1
        assert before["net_accepted_paid_cents"] == 10000

        # Replacement carries a DIFFERENT paid amount (15000): the ledger must track
        # the replacement's own contribution, not the original's.
        replacement = validate_success(api_client.replace_encounter(e1["id"], {
            "encounter_ref": "E1R",
            "service_from_date": "2026-08-10",
            "service_to_date": "2026-08-10",
            "place_of_service": "11",
            "diagnosis_codes": ["Z00"],
            "paid_amount_cents": 15000,
            "lines": [{"line_number": 1, "procedure_code": "99213", "units": 1,
                       "billed_amount_cents": 15000, "paid_amount_cents": 15000}],
        }, OPS), expected_status=201)
        mid = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert mid["net_accepted_encounter_count"] == 0
        assert mid["net_accepted_paid_cents"] == 0

        r_validated = get_success_data(api_client.validate_encounter(replacement["id"], OPS))
        assert r_validated["status"] == "VALIDATED"
        batch2 = create_batch(cycle["id"])
        batch2 = stage_encounter(batch2, replacement["id"])
        batch2 = seal_batch(batch2)
        batch2 = transmit_batch(batch2)
        acknowledge_batch(batch2, [{"encounter_id": replacement["id"], "outcome": "ACCEPTED"}])

        after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert after["net_accepted_encounter_count"] == 1
        assert after["net_accepted_paid_cents"] == 15000, "re-increment uses the replacement's contribution"

    def test_superseded_original_stops_counting_in_intake_tally(self):
        """PRD §3.3: "Its derived tallies — `intake_encounter_count` (encounters
        attributed to the cycle whose status is anything other than `SUPERSEDED`)"
        PRD §3.7: "Because a superseded record drops out of the intake tally while its
        replacement joins it, the pair nets out inside `intake_encounter_count`."

        Design: Corner/calculations/intake_count_excludes_superseded_after_replace
        """
        partial = setup_partial_batch_with_denial(program_name="P-CALC4")
        cycle = partial["cycle"]
        denied = partial["denied_encounter"]
        assert denied["status"] == "DENIED", "Setup failed: denied leg must be DENIED"

        replacement = replace_encounter(denied["id"], encounter_ref="E1R")
        assert replacement["status"] == "RECEIVED"
        assert replacement["replaces_encounter_id"] == denied["id"]

        original = get_success_data(api_client.get_encounter(denied["id"], OPS))
        assert original["status"] == "SUPERSEDED"

        cycle_after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert cycle_after["intake_encounter_count"] == 2, (
            "SUPERSEDED original drops out while the replacement enters; a naive count would read 3"
        )
        assert cycle_after["net_accepted_encounter_count"] == 1, "only the ACCEPTED leg contributes"


class TestDuplicateRefScoping:
    def test_duplicate_encounter_ref_rejected_then_reusable_after_supersede(self):
        """PRD §3.4: "Finally, the `encounter_ref` must be unique within its program and
        submitter scope among encounters whose status is neither `SUPERSEDED` nor
        `VOIDED`; a collision returns `ERR_DUPLICATE_ENCOUNTER_REF`."
        PRD §3.7: "and because `SUPERSEDED` records do not count against uniqueness, a
        corrected record may lawfully reuse a superseded reference."

        Design: Corner/validations/duplicate_encounter_ref_rejected_then_reusable_after_supersede
        """
        scenario = setup_basic_scenario(program_name="P-V3")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="DUP")
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="OK2", service_from_date="2026-08-13",
                                        service_to_date="2026-08-13", paid_amount_cents=2000,
                                        lines=[{"line_number": 1, "procedure_code": "99211", "units": 1,
                                                "billed_amount_cents": 2000, "paid_amount_cents": 2000}])
        dup_payload = {
            "program_id": program["id"],
            "member_id": member["id"],
            "provider_id": provider["id"],
            "encounter_ref": "DUP",
            "service_from_date": "2026-08-12",
            "service_to_date": "2026-08-12",
            "place_of_service": "11",
            "diagnosis_codes": ["Z00"],
            "paid_amount_cents": 3000,
            "lines": [{"line_number": 1, "procedure_code": "99212", "units": 1,
                       "billed_amount_cents": 3000, "paid_amount_cents": 3000}],
        }
        resp_dup = api_client.create_encounter(dup_payload, OPS)
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_ENCOUNTER_REF)

        # Drive e1 to DENIED via a mixed acknowledgment, then supersede it.
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = stage_encounter(batch, e2["id"])
        batch = seal_batch(batch)
        batch = transmit_batch(batch)
        acknowledge_batch(batch, [
            {"encounter_id": e1["id"], "outcome": "DENIED", "edit_code": EDIT_CODES["STATE_DENIAL"]},
            {"encounter_id": e2["id"], "outcome": "ACCEPTED"},
        ])
        replace_encounter(e1["id"], encounter_ref="E1R")

        resp_reuse = api_client.create_encounter(dup_payload, OPS)
        reused = validate_success(resp_reuse, expected_status=201)
        assert reused["status"] == "RECEIVED"
        assert reused["encounter_ref"] == "DUP"
