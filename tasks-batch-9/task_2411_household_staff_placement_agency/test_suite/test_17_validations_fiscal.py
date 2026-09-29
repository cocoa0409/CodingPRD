"""Compliance, billing, guarantee and enforcement gates.

The last stretch of the validation ladder guards money and paperwork: the payroll
handoff, exact settlement of a milestone, the separation date, the single open
claim, the remedy actually asked for, and the enforcement penalty.
"""
from test_helpers import (
    BILLING,
    CASE_OPENER,
    CONSULTANT,
    PRINCIPAL,
    api_client,
    attest_handoff_payload,
    create_payroll_handoff_payload,
    create_replacement_claim_payload,
    file_claim,
    file_enforcement_case,
    investigate_case_payload,
    invoice_milestone,
    prepare_payroll_handoff,
    read_case,
    read_claim,
    read_client,
    read_clock,
    read_handoff,
    read_milestone,
    read_placement,
    record_payment_payload,
    register_candidate,
    review_claim,
    review_claim_payload,
    set_clock,
    settle_case_payload,
    setup_active_placement,
    setup_scenario,
    setup_substantiated_case,
    terminate_placement,
    terminate_placement_payload,
    update_handoff_ein,
    validate_error,
    validate_paginated,
)


class TestPayrollHandoffGates:
    def test_01_attestation_waits_for_the_employer_number_to_issue(self):
        """The handoff is PREPARED and the attestor is named, so only the EIN is
        wrong.

        PRD §3.7: "Attestation may be performed by the household as `Client` or by
        a `ComplianceOfficer`, supplying `attested_by_name`. The handoff must be
        `PREPARED`, or the request is refused with `ERR_ENTITY_TERMINAL`, and its
        `ein_status` must be exactly `ISSUED`, or it is refused with
        `ERR_EIN_NOT_ISSUED` (HTTP 409)."

        Design: Corner/validations/attesting_before_the_ein_is_issued_is_refused
        """
        scenario = setup_active_placement()
        handoff = prepare_payroll_handoff(scenario["placement"])
        assert handoff["status"] == "PREPARED"
        assert handoff["ein_status"] == "NOT_APPLIED"

        validate_error(
            api_client.attest_payroll_handoff(
                handoff["id"], attest_handoff_payload(), scenario["client_headers"]
            ),
            "ERR_EIN_NOT_ISSUED",
            409,
        )

        stored = read_handoff(handoff)
        assert stored["status"] == "PREPARED"
        assert stored["ein_status"] == "NOT_APPLIED"
        assert stored["attested_at"] is None

        applied = update_handoff_ein(handoff, "APPLIED")
        assert applied["ein_status"] == "APPLIED"
        validate_error(
            api_client.attest_payroll_handoff(
                handoff["id"], attest_handoff_payload(), scenario["client_headers"]
            ),
            "ERR_EIN_NOT_ISSUED",
            409,
        )

    def test_02_a_placement_carries_at_most_one_payroll_handoff(self):
        """A different bureau on the same placement is still a second handoff.

        PRD §3.7: "Only one handoff may exist per placement, and a second attempt
        is refused with `ERR_PAYROLL_HANDOFF_EXISTS` (HTTP 409)."

        Design: Corner/validations/a_second_payroll_handoff_for_one_placement_is_refused
        """
        scenario = setup_active_placement()
        first = prepare_payroll_handoff(scenario["placement"])

        validate_error(
            api_client.create_payroll_handoff(
                scenario["placement"]["id"],
                create_payroll_handoff_payload(
                    provider_name="Second Payroll Bureau",
                    guidance_packet_version="SP-2026.1",
                ),
                CASE_OPENER,
            ),
            "ERR_PAYROLL_HANDOFF_EXISTS",
            409,
        )

        handoffs, meta = validate_paginated(
            api_client.list_placement_payroll_handoffs(
                scenario["placement"]["id"], CASE_OPENER
            )
        )
        assert meta["total_count"] == 1
        assert handoffs[0]["provider_name"] == first["provider_name"]


class TestBillingExactnessGates:
    def test_03_a_payment_one_cent_short_settles_nothing(self):
        """The row is INVOICED, so the only defect is the amount.

        PRD §3.7: "`paid_amount_cents` must equal the row's `amount_cents` exactly
        — there are no partial payments, a household settles a milestone in full or
        not at all — and any other figure is refused with
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/a_payment_one_cent_short_of_the_milestone_is_refused
        """
        scenario = setup_active_placement()
        invoiced = invoice_milestone(scenario["milestones"][0])
        assert invoiced["amount_cents"] == 600_000
        assert invoiced["invoice_status"] == "INVOICED"

        validate_error(
            api_client.record_milestone_payment(
                invoiced["id"], record_payment_payload(599_999), BILLING
            ),
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            422,
        )

        stored = read_milestone(invoiced)
        assert stored["invoice_status"] == "INVOICED"
        assert stored["paid_on"] is None
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 600_000


class TestGuaranteeGates:
    def test_04_a_separation_before_the_start_date_is_refused(self):
        """A date equal to the clock is accepted, so only the lower bound bites.

        PRD §3.6: "The `separation_date` must not be earlier than the placement's
        `start_date` and must not be later than the logical-clock date, either
        violation being refused with `ERR_INVALID_SEPARATION_DATE` (HTTP 422).
        Recording it moves the placement `ACTIVE → TERMINATED_NO_REMEDY`, stamps
        `separation_date`, and moves the candidate `PLACED → COOLING_OFF` with
        `cooling_off_until` set to the logical-clock date plus 30 days."

        Design: Corner/validations/a_separation_date_before_the_start_date_is_refused
        """
        scenario = setup_active_placement()
        set_clock("2026-09-10T00:00:00Z")

        validate_error(
            api_client.terminate_placement(
                scenario["placement"]["id"],
                terminate_placement_payload("2026-08-31"),
                CONSULTANT,
            ),
            "ERR_INVALID_SEPARATION_DATE",
            422,
        )

        stored = read_placement(scenario["placement"])
        assert stored["placement_status"] == "ACTIVE"
        assert stored["separation_date"] is None

        terminated = terminate_placement(scenario["placement"], "2026-09-10")
        assert terminated["placement_status"] == "TERMINATED_NO_REMEDY"
        assert terminated["separation_date"] == "2026-09-10"

    def test_05_a_second_claim_is_refused_while_the_first_is_open(self):
        """The version supplied is current, so this is not a concurrency refusal.

        PRD §3.8: "And only one claim may be open at a time: if a claim on this
        placement has `status` `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`, the
        filing is refused with `ERR_OPEN_CLAIM_EXISTS` (HTTP 409)."

        Design: Corner/validations/a_second_claim_while_one_is_open_is_refused
        """
        scenario = setup_active_placement()
        set_clock("2026-09-10T00:00:00Z")
        terminate_placement(scenario["placement"], "2026-09-10")
        first = file_claim(
            scenario["placement"], scenario["client_headers"], "REPLACEMENT", "2026-09-10"
        )
        assert review_claim(first, "OPEN_REVIEW")["status"] == "UNDER_REVIEW"

        current = read_placement(scenario["placement"])
        validate_error(
            api_client.create_replacement_claim(
                current["id"],
                create_replacement_claim_payload(
                    "REFUND", "2026-09-10", current["version"]
                ),
                scenario["client_headers"],
            ),
            "ERR_OPEN_CLAIM_EXISTS",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_placement_replacement_claims(current["id"], PRINCIPAL)
        )
        assert meta["total_count"] == 1

    def test_06_a_refund_may_not_be_granted_on_a_replacement_claim(self):
        """The claim is UNDER_REVIEW, so only the remedy is out of step.

        PRD §3.8: "The two approvals must also match what was asked for: approving
        a replacement on a claim whose `requested_remedy` is `REFUND`, or approving
        a refund on a claim whose `requested_remedy` is `REPLACEMENT`, is refused
        with `ERR_REMEDY_MISMATCH` (HTTP 409)."

        Design: Corner/validations/approving_a_refund_on_a_replacement_claim_is_refused
        """
        scenario = setup_active_placement()
        set_clock("2026-09-10T00:00:00Z")
        terminate_placement(scenario["placement"], "2026-09-10")
        claim = review_claim(
            file_claim(
                scenario["placement"],
                scenario["client_headers"],
                "REPLACEMENT",
                "2026-09-10",
            ),
            "OPEN_REVIEW",
        )

        validate_error(
            api_client.review_replacement_claim(
                claim["id"], review_claim_payload("APPROVE_REFUND"), PRINCIPAL
            ),
            "ERR_REMEDY_MISMATCH",
            409,
        )

        stored = read_claim(claim)
        assert stored["status"] == "UNDER_REVIEW"
        assert stored["net_refund_cents"] is None

        _, meta = validate_paginated(
            api_client.list_ledger_entries(scenario["client"]["id"], BILLING)
        )
        assert meta["total_count"] == 0


class TestEnforcementGates:
    def test_07_a_household_never_placed_has_no_term_to_enforce(self):
        """The filing is accepted, which shows the gate lives on the
        investigation.

        PRD §3.9: "The respondent household's term must actually cover the
        conduct: its `non_solicitation_expires_on` must not be null and the case's
        `discovered_on` must not be later than that date, or the investigation is
        refused with `ERR_NON_SOLICITATION_TERM_EXPIRED` (HTTP 422)."

        Design: Corner/validations/investigating_a_household_with_no_non_solicitation_term_is_refused
        """
        scenario = setup_scenario(stage="household")
        candidate = register_candidate()
        household = read_client(scenario["client"])
        assert household["placement_count"] == 0
        assert household["non_solicitation_expires_on"] is None

        case = file_enforcement_case(household, candidate, "2026-09-01")
        assert case["status"] == "ALLEGED"

        validate_error(
            api_client.investigate_non_solicitation_case(
                case["id"], investigate_case_payload(), CASE_OPENER
            ),
            "ERR_NON_SOLICITATION_TERM_EXPIRED",
            422,
        )

        stored = read_case(case)
        assert stored["status"] == "ALLEGED"
        assert stored["investigation_opened_at"] is None

    def test_08_a_settlement_one_cent_above_the_penalty_is_refused(self):
        """The comparison is strictly greater than, so 1,500,001 is the first
        refusal.

        PRD §3.9: "A negative `settlement_amount_cents` is caught by the numeric
        range check and refused with `ERR_INVALID_RANGE` (HTTP 400), and a
        non-negative amount greater than the case's `penalty_cents` is refused with
        `ERR_SETTLEMENT_EXCEEDS_PENALTY` (HTTP 422) — the household may settle for
        less than the assessed penalty, or for exactly it, but never for more."

        Design: Corner/validations/a_settlement_one_cent_above_the_penalty_is_refused
        """
        scenario = setup_substantiated_case()
        assert scenario["case"]["penalty_cents"] == 1_500_000

        validate_error(
            api_client.settle_non_solicitation_case(
                scenario["case"]["id"], settle_case_payload(1_500_001), BILLING
            ),
            "ERR_SETTLEMENT_EXCEEDS_PENALTY",
            422,
        )

        stored = read_case(scenario["case"])
        assert stored["status"] == "SUBSTANTIATED"
        assert stored["settlement_amount_cents"] is None

        household = read_client(scenario["client"])
        assert household["status"] == "SUSPENDED"
        assert household["outstanding_balance_cents"] == 1_500_000


class TestClockGate:
    def test_09_the_clock_refuses_to_wind_backwards(self):
        """One second earlier than the stored instant is already too early.

        PRD §2.6: "The clock is monotonic: a requested instant earlier than the
        currently stored clock is refused with `ERR_CLOCK_NOT_MONOTONIC` (HTTP
        422), which guarantees that a sweep-driven transition can never be
        un-fired."

        Design: Corner/validations/winding_the_clock_backwards_is_refused
        """
        set_clock("2026-09-01T00:00:00Z")

        validate_error(
            api_client.set_clock("2026-08-31T23:59:59Z", BILLING),
            "ERR_CLOCK_NOT_MONOTONIC",
            422,
        )

        assert read_clock()["current_utc"] == "2026-09-01T00:00:00Z"
