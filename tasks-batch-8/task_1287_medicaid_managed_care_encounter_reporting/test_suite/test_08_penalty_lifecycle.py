"""Penalty lifecycle: appeal, resolve (UPHELD/WAIVED/REDUCED), pay, and the
compensating legs on the program's outstanding-penalty ledger; plus the audit-fail
cascade that flips program posture and blocks transmit."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_acknowledged_encounter,
    create_audit,
    create_batch,
    create_cycle,
    create_member,
    create_program,
    create_provider,
    create_rate_schedule,
    create_statement,
    create_validated_encounter,
    determine_audit,
    get_success_data,
    make_mco_compliance_headers,
    seal_batch,
    setup_determined_fail_audit,
    setup_late_penalty,
    stage_encounter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import COMP_TRANSMITTER, FIN, OPS, STATE


def make_compliance():
    return make_mco_compliance_headers("fx-comp-appeal")


class TestAuditFailCascade:
    def test_audit_fail_penalty_posture_transmit_block(self):
        """PRD §3.8: "A `FAIL` determination spawns the penalty cascade. The system
        creates a PenaltyAssessment in status `ASSESSED` ... The cascade then adds that
        amount to the program's `penalties_outstanding_cents` and recomputes posture per
        §2.10, and a flip to `RESTRICTED` immediately blocks further batch transmissions
        with `ERR_PROGRAM_RESTRICTED`."
        PRD §2.10: "When `penalties_outstanding_cents` reaches or exceeds the program's
        `penalty_threshold_cents` (the comparison is inclusive at the boundary), the
        posture flips to `RESTRICTED`"

        Design: Difficulty/transitive_cascade/audit_fail_penalty_posture_transmit_block
        """
        program = create_program(name="P-CAS1", penalty_threshold_cents=40000)
        create_rate_schedule(program["id"], aid_category="SSI", pmpm_cents=120000)
        cycle = create_cycle(program["id"])
        members = [create_member(program["id"], aid_category="SSI") for _ in range(4)]
        provider = create_provider(program["id"])
        # One acknowledged encounter: eligibility completeness = 1 / ceil(4 * 0.5) = 0.5.
        create_acknowledged_encounter(program["id"], cycle["id"], members[0]["id"], provider["id"],
                                      encounter_ref="E1")
        # An unrelated SEALED batch awaiting transmit.
        e2 = create_validated_encounter(program["id"], cycle["id"], members[0]["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-20",
                                        service_to_date="2026-08-20", paid_amount_cents=5000,
                                        lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                                "billed_amount_cents": 5000, "paid_amount_cents": 5000}])
        batch2 = create_batch(cycle["id"])
        batch2 = stage_encounter(batch2, e2["id"])
        batch2 = seal_batch(batch2)

        create_statement(cycle["id"])
        audit = create_audit(cycle["id"], sample_size=20, defect_count=4)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["determination"] == "FAIL"

        penalties, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 1
        assert penalties[0]["amount_cents"] == 48000, "capped: raw 3150000 vs cap 10% of 480000"
        assert penalties[0]["status"] == "ASSESSED"

        program_after = get_success_data(api_client.get_program(program["id"], STATE))
        assert program_after["penalties_outstanding_cents"] == 48000
        assert program_after["posture"] == "RESTRICTED", "48000 >= 40000"

        resp = api_client.transmit_batch(batch2["id"], COMP_TRANSMITTER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_RESTRICTED)

    def test_audit_fail_posture_flip_blocks_then_waiver_restores_transmit(self):
        """PRD §3.8: "A `decision` of `WAIVED` moves it to the terminal `WAIVED` and
        subtracts the full `amount_cents` from `penalties_outstanding_cents` as a
        compensating leg, recomputing posture."
        PRD §2.10: "when the ledger falls back below the threshold, the posture returns
        to `OPEN`."

        Design: Difficulty/transitive_cascade/audit_fail_penalty_posture_transmit_block
        """
        program = create_program(name="P-CAS1B", penalty_threshold_cents=40000)
        create_rate_schedule(program["id"], aid_category="SSI", pmpm_cents=120000)
        cycle = create_cycle(program["id"])
        members = [create_member(program["id"], aid_category="SSI") for _ in range(4)]
        provider = create_provider(program["id"])
        create_acknowledged_encounter(program["id"], cycle["id"], members[0]["id"], provider["id"],
                                      encounter_ref="E1")
        e2 = create_validated_encounter(program["id"], cycle["id"], members[0]["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-20",
                                        service_to_date="2026-08-20", paid_amount_cents=5000,
                                        lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                                "billed_amount_cents": 5000, "paid_amount_cents": 5000}])
        batch2 = create_batch(cycle["id"])
        batch2 = stage_encounter(batch2, e2["id"])
        batch2 = seal_batch(batch2)
        create_statement(cycle["id"])
        audit = create_audit(cycle["id"], sample_size=20, defect_count=4)
        validate_success(api_client.determine_audit(audit["id"], STATE))

        program_mid = get_success_data(api_client.get_program(program["id"], STATE))
        assert program_mid["posture"] == "RESTRICTED"
        resp = api_client.transmit_batch(batch2["id"], COMP_TRANSMITTER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_RESTRICTED)

        penalties, _ = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        penalty = penalties[0]
        validate_success(api_client.appeal_penalty(penalty["id"], make_compliance()))
        validate_success(api_client.resolve_penalty(penalty["id"], {"decision": "WAIVED"}, STATE))

        program_after = get_success_data(api_client.get_program(program["id"], STATE))
        assert program_after["penalties_outstanding_cents"] == 0
        assert program_after["posture"] == "OPEN", "posture returns to OPEN below the threshold"
        transmitted = validate_success(api_client.transmit_batch(batch2["id"], COMP_TRANSMITTER))
        assert transmitted["status"] == "TRANSMITTED"


class TestAssessWaiveCompensation:
    def test_assess_then_waive_restores_outstanding_penalties(self):
        """PRD §3.8: "A `decision` of `WAIVED` moves it to the terminal `WAIVED` and
        subtracts the full `amount_cents` from `penalties_outstanding_cents` as a
        compensating leg, recomputing posture."
        PRD §2.10: "The program's `penalties_outstanding_cents` is a live ledger: it is
        the sum of `amount_cents` over all of the program's penalty assessments whose
        status is `ASSESSED`, `APPEALED`, or `UPHELD`, plus the sum of
        `reduced_amount_cents` over assessments in status `REDUCED`; assessments in
        `WAIVED` or `PAID` status contribute nothing."

        Design: Difficulty/compensating_invariant/assess_then_waive_restores_outstanding_penalties
        """
        result = setup_determined_fail_audit(program_name="P-INV2", aid_category="SSI",
                                             pmpm_cents=120000, member_count=4,
                                             acknowledged_count=1, sample_size=20, defect_count=4)
        program = result["program"]
        penalty = result["penalties"][0]
        assert penalty["amount_cents"] == 48000

        mid = get_success_data(api_client.get_program(program["id"], STATE))
        assert mid["penalties_outstanding_cents"] == 48000, "forward leg"
        assert mid["posture"] == "OPEN", "threshold 100000000 never crossed"

        appealed = validate_success(api_client.appeal_penalty(penalty["id"], make_compliance()))
        assert appealed["status"] == "APPEALED"
        waived = validate_success(api_client.resolve_penalty(penalty["id"], {"decision": "WAIVED"}, STATE))
        assert waived["status"] == "WAIVED"

        after = get_success_data(api_client.get_program(program["id"], STATE))
        assert after["penalties_outstanding_cents"] == 0, "compensating leg restores exactly"
        assert after["posture"] == "OPEN"

    def test_assess_appeal_waive_round_trip_via_get_endpoints(self):
        """PRD §3.8: "A `decision` of `WAIVED` moves it to the terminal `WAIVED` and
        subtracts the full `amount_cents` from `penalties_outstanding_cents` as a
        compensating leg, recomputing posture."
        PRD §3.8: "Appeal by an `McoCompliance` officer moves the assessment
        `ASSESSED → APPEALED` and freezes it there — an appealed penalty must be
        resolved before it can be paid."

        Design: Difficulty/compensating_invariant/assess_then_waive_restores_outstanding_penalties
        """
        result = setup_determined_fail_audit(program_name="P-INV2B", aid_category="SSI",
                                             pmpm_cents=120000, member_count=4,
                                             acknowledged_count=1, sample_size=20, defect_count=4)
        program = result["program"]
        penalty = result["penalties"][0]
        assert get_success_data(api_client.get_program(program["id"], STATE))["penalties_outstanding_cents"] == 48000

        validate_success(api_client.appeal_penalty(penalty["id"], make_compliance()))
        # APPEALED still counts against the ledger per the §2.10 status set.
        mid = get_success_data(api_client.get_program(program["id"], STATE))
        assert mid["penalties_outstanding_cents"] == 48000, "APPEALED remains in the outstanding sum"
        fetched = validate_success(api_client.get_penalty(penalty["id"], STATE))
        assert fetched["status"] == "APPEALED"

        validate_success(api_client.resolve_penalty(penalty["id"], {"decision": "WAIVED"}, STATE))
        final = validate_success(api_client.get_penalty(penalty["id"], STATE))
        assert final["status"] == "WAIVED"
        after = get_success_data(api_client.get_program(program["id"], STATE))
        assert after["penalties_outstanding_cents"] == 0
        assert after["posture"] == "OPEN"


class TestPaymentGates:
    def test_penalty_pay_from_appealed_returns_invalid_state(self):
        """PRD §3.8: "Payment by `McoFinance` settles the debt: from any of `ASSESSED`,
        `UPHELD`, or `REDUCED` (an `APPEALED` assessment draws
        `ERR_INVALID_STATE_TRANSITION`), the assessment moves to the terminal `PAID`"

        Design: Corner/state_machines/penalty_pay_from_appealed_returns_invalid_state
        """
        fx = setup_late_penalty(program_name="P-SM11")
        penalty = fx["penalty"]
        validate_success(api_client.appeal_penalty(penalty["id"], make_compliance()))
        resp = api_client.pay_penalty(penalty["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_penalty(penalty["id"], STATE))
        assert after["status"] == "APPEALED"

    def test_penalty_reduced_then_paid_conserves_amounts(self):
        """PRD §3.8: "A `decision` of `REDUCED` requires a `reduced_amount_cents` that
        is zero or greater and strictly less than `amount_cents` — an out-of-range value
        is a request-validity failure rejected with `ERR_INVALID_REQUEST` ahead of any
        state check — and moves the assessment to `REDUCED` while subtracting the
        difference between `amount_cents` and `reduced_amount_cents` from the
        outstanding ledger, again recomputing posture."
        PRD §3.8: "the assessment moves to the terminal `PAID`, and the ledger
        decrements by the effective amount — the `reduced_amount_cents` for a reduced
        assessment, the `amount_cents` otherwise — with posture recomputed."

        Design: Corner/state_machines/penalty_reduced_then_paid_conserves_amounts
        """
        fx = setup_late_penalty(program_name="P-SM12")
        program, penalty = fx["program"], fx["penalty"]
        assert penalty["amount_cents"] == 500000, "1 second late => flat component only"
        validate_success(api_client.appeal_penalty(penalty["id"], make_compliance()))

        reduced = validate_success(api_client.resolve_penalty(
            penalty["id"], {"decision": "REDUCED", "reduced_amount_cents": 300000}, STATE))
        assert reduced["status"] == "REDUCED"
        assert reduced["reduced_amount_cents"] == 300000
        mid = get_success_data(api_client.get_program(program["id"], STATE))
        assert mid["penalties_outstanding_cents"] == 300000, "500000 - (500000 - 300000)"

        paid = validate_success(api_client.pay_penalty(penalty["id"], FIN))
        assert paid["status"] == "PAID"
        end = get_success_data(api_client.get_program(program["id"], STATE))
        assert end["penalties_outstanding_cents"] == 0, "payment subtracts exactly the reduced amount"
        assert end["posture"] == "OPEN"
