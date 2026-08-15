"""Protocol submission gates: validation priority pairs (state vs fiscal,
approval gate vs cage consistency), grant solvency at submission, enum
validation, and server-minted protocol fields (PRD §2.8, §3.3, §3.4).
"""
import re

from test_helpers import (
    ADMIN,
    BILLING,
    FACILITY,
    STAFF,
    ApiErrorId,
    api_client,
    assert_protocol,
    create_draft_protocol,
    create_protocol_payload,
    get_success_data,
    setup_suspended_protocol,
    validate_error,
)
from test_helpers.factories import create_animal_payload, create_cage_payload
from test_helpers.fixtures import (
    add_cage,
    add_mouse,
    compute_provisional_ok,
    create_approved_protocol,
    create_billing_run,
    file_daily_census,
    finalize_run,
    post_run,
)


def _drain_grant_via_posted_run(scenario):
    """Drive the scenario's grant to zero remaining by posting a 2625-cent
    mouse-cage run (PRD §3.7 cage-day model: 21 days at 125 cents). A clean
    census is filed for every day of the period so the FINAL reconciled-census
    model ("a day counts only when a reconciled census — a census record whose
    `discrepancy` is zero — confirms occupancy for that day") bills all 21
    days."""
    cage = add_cage(scenario["protocol"]["id"], species="MOUSE", capacity_adults=5)
    add_mouse(cage["id"], scenario["protocol"]["id"])
    file_daily_census(cage["id"], 21, 1)
    run = create_billing_run("2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z")
    run = compute_provisional_ok(run["id"])
    run = finalize_run(run["id"], run["version"])
    post_run(run["id"])
    return cage


class TestStateVsFiscalPriority:
    def test_resubmit_with_drained_grant_surfaces_state_error(self, api):
        """PRD §2.8: "When several checks could reject the same request, the
        server evaluates them in a single fixed priority order and surfaces
        the earliest failure." with "6. State legality — the target resource
        is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`, 409)." ranked ahead of "23. Grant solvency at
        protocol submission (`ERR_GRANT_EXHAUSTED`, 402)." PRD §3.3: "the
        protocol must be in `DRAFT` (else `ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_protocol_submit
        """
        scenario = create_approved_protocol(budget=2625)
        _drain_grant_via_posted_run(scenario)

        grant = get_success_data(
            api_client.get_grant(scenario["grant"]["id"], BILLING)
        )
        assert grant["budget_remaining_cents"] == 0, (
            "posting 2625 against a 2625-cent grant must drain it (the fiscal "
            "violation is real)"
        )

        resp = api_client.submit_protocol(
            scenario["protocol"]["id"], scenario["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_resubmit_leaves_protocol_unchanged(self, api):
        """PRD §2.8: "the server evaluates them in a single fixed priority
        order and surfaces the earliest failure." PRD §3.7: "Posting moves the
        run from `FINALIZED` to `POSTED`, which is terminal, and debits each
        grant's `budget_remaining_cents` by the sum of that grant's charge
        amounts."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_protocol_submit
        """
        scenario = create_approved_protocol(budget=2625)
        _drain_grant_via_posted_run(scenario)

        before = get_success_data(
            api_client.get_protocol(scenario["protocol"]["id"], ADMIN)
        )
        resp = api_client.submit_protocol(
            scenario["protocol"]["id"], scenario["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(
            api_client.get_protocol(scenario["protocol"]["id"], ADMIN)
        )
        assert after["status"] == "APPROVED", (
            "a rejected resubmission must not move the protocol"
        )
        assert after["version"] == before["version"], (
            "a rejected resubmission must not mutate the protocol"
        )
        grant = get_success_data(
            api_client.get_grant(scenario["grant"]["id"], BILLING)
        )
        assert grant["budget_remaining_cents"] == 0


class TestApprovalGateVsCageConsistencyPriority:
    def test_draft_protocol_and_species_mismatch_surfaces_approval_gate(self, api):
        """PRD §2.8 ranks "11. The protocol-approved gate
        (`ERR_PROTOCOL_NOT_APPROVED`, 409)." ahead of "13. Species and
        protocol consistency between animal and cage (`ERR_CAGE_MISMATCH`,
        422)." PRD §3.4: "Admission is refused — in the order fixed by §2.8 —
        when the protocol has reached its justified ceiling, when the protocol
        is not `APPROVED`, when species or protocol disagree between animal
        and cage or the cage is `DECOMMISSIONED`, or when the addition would
        overflow the cage."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_animal_add
        """
        scenario = create_draft_protocol(species="MOUSE", max_animals=5)
        cage = get_success_data(api_client.create_cage(
            create_cage_payload(
                scenario["protocol"]["id"], species="RAT", capacity_adults=2,
                cage_barcode="RAT-CAGE-1",
            ),
            FACILITY,
        ))

        resp = api_client.create_animal(
            create_animal_payload(
                cage["id"], scenario["protocol"]["id"], species="MOUSE",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

    def test_rejected_add_creates_no_animal_row(self, api):
        """PRD §3.4: "A protocol that is not `APPROVED` refuses admission with
        `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409)." PRD §2.8: "the server
        evaluates them in a single fixed priority order and surfaces the
        earliest failure."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_animal_add
        """
        scenario = create_draft_protocol(species="MOUSE", max_animals=5)
        cage = get_success_data(api_client.create_cage(
            create_cage_payload(
                scenario["protocol"]["id"], species="RAT", capacity_adults=2,
                cage_barcode="RAT-CAGE-2",
            ),
            FACILITY,
        ))

        resp = api_client.create_animal(
            create_animal_payload(
                cage["id"], scenario["protocol"]["id"], species="MOUSE",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

        animals = get_success_data(
            api_client.list_protocol_animals(scenario["protocol"]["id"], ADMIN)
        )
        assert animals == [], (
            f"no Animal row may be created by a rejected add, got {animals}"
        )


class TestGrantSolvencyAtSubmission:
    def test_zero_budget_grant_blocks_submit(self, api):
        """PRD §3.3: "the referenced grant must be solvent —
        `budget_remaining_cents` greater than zero and `expires_on` still
        ahead of the current clock time (else `ERR_GRANT_EXHAUSTED`, HTTP
        402)."

        Design: Corner/validations/grant_exhausted_blocks_submit
        """
        scenario = create_draft_protocol(budget=0)

        resp = api_client.submit_protocol(
            scenario["protocol"]["id"], scenario["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_EXHAUSTED)

        current = get_success_data(
            api_client.get_protocol(scenario["protocol"]["id"], ADMIN)
        )
        assert current["status"] == "DRAFT", (
            "a submission rejected for an exhausted grant leaves the protocol "
            "in DRAFT"
        )


class TestProtocolCreationFields:
    def test_invalid_species_enum_rejected(self, api):
        """PRD §2.8: "3. Payload well-formedness — required fields present and
        well-typed, enum values within their declared sets, integers within
        range (`ERR_INVALID_REQUEST`, 400)." PRD §3.3: "`species` (one of
        `MOUSE`, `RAT`, `RABBIT`, or `ZEBRAFISH`)".

        Design: Corner/entities/invalid_enum_value_rejected
        """
        scenario = create_draft_protocol(species="MOUSE")
        payload = create_protocol_payload(
            scenario["investigator"]["id"], scenario["grant"]["id"],
            species="HAMSTER",
        )
        resp = api_client.create_protocol(
            payload, scenario["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_protocol_number_minted_by_server(self, api):
        """PRD §3.3: "The server mints a human-readable `protocol_number` in
        the format IACUC-YYYY-NNNN." and "The protocol begins in `DRAFT`, with
        `animals_used_count` at zero and both `approved_at` and `expires_at`
        unset."

        Design: Corner/entities/protocol_number_minted_by_server
        """
        scenario = create_draft_protocol(species="MOUSE", max_animals=5)
        protocol = scenario["protocol"]
        assert_protocol(protocol)
        assert re.fullmatch(r"IACUC-\d{4}-\d{4}", protocol["protocol_number"]), (
            f"protocol_number must match IACUC-YYYY-NNNN, got "
            f"{protocol['protocol_number']!r}"
        )
        assert protocol["status"] == "DRAFT"
        assert protocol["animals_used_count"] == 0
        assert protocol["approved_at"] is None
        assert protocol["expires_at"] is None


class TestSuspendedProtocolGate:
    def test_animal_add_blocked_while_protocol_suspended(self, api):
        """PRD §3.4: "A protocol that is not `APPROVED` refuses admission with
        `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409)." — a SUSPENDED protocol is not
        APPROVED, so the gate is a status allowlist.

        Design: Corner/complexity_layers/animal_add_blocked_while_protocol_suspended
        """
        scenario = setup_suspended_protocol()
        assert scenario["protocol"]["status"] == "SUSPENDED"

        resp = api_client.create_animal(
            create_animal_payload(
                scenario["cage"]["id"], scenario["protocol"]["id"],
                species="MOUSE",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

