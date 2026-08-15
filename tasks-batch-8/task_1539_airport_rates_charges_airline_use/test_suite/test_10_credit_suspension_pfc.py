"""Agreement credit standing and PFC remittance: the parallel signature/credit
dimensions, the suspension billing guard, and PFC eligibility and cap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_airline,
    create_pfc_application_payload,
    get_success_data,
    make_signatory_airline_headers,
    set_clock,
    setup_open_year,
    setup_settlement_in_review,
    validate_error,
    validate_paginated,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]
DIRECTOR = TEST_USERS["director_headers"]

PAST_DUE_CLOCK = "2027-01-15T00:00:00Z"


def _setup_delinquent_then_suspended(api, label, iata, pfc_approved=False):
    """Signatory carrier with a published settlement line left PENDING past
    its due date, then suspended by the airport. Returns the workspace."""
    ws = setup_settlement_in_review(
        label,
        airline_specs=[{"iata_code": iata, "pfc_approved": pfc_approved}],
        activity_specs=[{"iata_code": iata, "landed_weight_kg": 1000}],
    )
    # Publish-review stamped a sixty-day due date at 2026-09-10; the clock now
    # moves past it, so the standing first degrades to DELINQUENT.
    set_clock(PAST_DUE_CLOCK)
    validate_success(api.suspend_agreement(ws["agreements"][iata]["id"],
                                           FINANCE))
    return ws


class TestParallelDimensions:
    def test_overdue_line_moves_credit_to_delinquent_only(self, api):
        """PRD §3.1: "These are two independent dimensions that evolve in
        parallel; an agreement has no terminal state."
        PRD §3.1: "When the logical clock passes a settlement line's payment
        due date while that line still stands `PENDING`, the agreement's
        `credit_standing` moves from `GOOD` to `DELINQUENT` automatically."

        Design: Difficulty/non_linear_state_machine/airline_agreement_parallel_dimensions
        """
        ws = setup_settlement_in_review(
            "FY_PAR", [{"iata_code": "PA"}],
            [{"iata_code": "PA", "landed_weight_kg": 1000}])
        set_clock(PAST_DUE_CLOCK)

        agreement = get_success_data(api.get_airline_agreement(
            ws["agreements"]["PA"]["id"], FINANCE))
        assert agreement["credit_standing"] == "DELINQUENT", (
            "The overdue PENDING line degrades the credit standing "
            "automatically, without anyone editing the agreement")

    def test_suspend_moves_credit_only(self, api):
        """PRD §3.1: "From `DELINQUENT`, `AirportFinance` may suspend the
        carrier — permitted only while at least one settlement line for that
        airline on that fiscal year remains `PENDING` — moving the standing to
        `SUSPENDED`."
        PRD §3.1: "These are two independent dimensions that evolve in
        parallel; an agreement has no terminal state."

        Design: Difficulty/non_linear_state_machine/airline_agreement_parallel_dimensions
        """
        ws = setup_settlement_in_review(
            "FY_PAR2", [{"iata_code": "PA"}],
            [{"iata_code": "PA", "landed_weight_kg": 1000}])
        set_clock(PAST_DUE_CLOCK)

        before = get_success_data(api.get_airline_agreement(
            ws["agreements"]["PA"]["id"], FINANCE))
        assert before["credit_standing"] == "DELINQUENT"

        suspended = validate_success(api.suspend_agreement(
            ws["agreements"]["PA"]["id"], FINANCE))
        assert suspended["credit_standing"] == "SUSPENDED"

        after = get_success_data(api.get_airline_agreement(
            ws["agreements"]["PA"]["id"], FINANCE))
        assert after["signature_status"] == before["signature_status"], (
            "Suspension moves credit_standing without touching "
            "signature_status")


class TestSuspensionBlocksBilling:
    def test_activity_record_rejected_while_suspended(self, api):
        """PRD §3.1: "While `SUSPENDED`, the carrier is grounded for billing
        purposes: creating activity records or PFC applications for it is
        rejected with `ERR_AIRLINE_SUSPENDED`."
        PRD §3.3: "If the carrier's agreement stands `SUSPENDED`, creation is
        rejected with `ERR_AIRLINE_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/activity_record_requires_agreement_not_suspended
        """
        ws = _setup_delinquent_then_suspended(api, "FY_XSA", "SA")

        before, meta_before = validate_paginated(
            api.list_activity_records(ws["fy"]["id"], FINANCE))
        resp = api.create_activity_record(
            ws["fy"]["id"],
            {"airline_id": ws["airlines"]["SA"]["id"],
             "activity_date": "2027-01-10T00:00:00Z",
             "landed_weight_kg": 500,
             "signature_status_at_activity": "SIGNATORY"},
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_AIRLINE_SUSPENDED)

        _after, meta_after = validate_paginated(
            api.list_activity_records(ws["fy"]["id"], FINANCE))
        assert meta_after["total_count"] == meta_before["total_count"], (
            "No activity record may be persisted for a suspended carrier")

    def test_pfc_application_rejected_while_suspended(self, api):
        """PRD §3.7: "the parent fiscal year must also still stand `OPEN`, and
        a suspended carrier is turned away under the suspension guard with
        `ERR_AIRLINE_SUSPENDED`."
        PRD §3.1: "While `SUSPENDED`, the carrier is grounded for billing
        purposes: creating activity records or PFC applications for it is
        rejected with `ERR_AIRLINE_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/activity_record_requires_agreement_not_suspended
        """
        ws = _setup_delinquent_then_suspended(api, "FY_XSB", "SB",
                                              pfc_approved=True)
        airline = ws["airlines"]["SB"]

        resp = api.create_pfc_application(
            ws["fy"]["id"],
            create_pfc_application_payload(airline["id"],
                                           enplaned_passengers=100),
            make_signatory_airline_headers(airline["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AIRLINE_SUSPENDED)


class TestPfcAmountAndEligibility:
    def test_pfc_amount_capped_at_annual_cap(self, api):
        """PRD §3.7: "The collectible amount is computed at submission and
        stored as `pfc_amount_cents`: the enplaned passenger count multiplied
        by 450 cents per passenger — a $4.50 charge — except that passengers
        beyond the annual cap are not collectible, so the multiplication uses
        the lesser of the reported count and an annual cap of 2,000,000
        enplaned passengers."

        Design: Corner/calculations/pfc_amount_with_cap
        """
        ws = setup_open_year("FY_PFC")
        airline = create_airline("PC", legal_name="PFC Air", pfc_approved=True)

        application = validate_success(
            api.create_pfc_application(
                ws["fy"]["id"],
                create_pfc_application_payload(airline["id"],
                                               enplaned_passengers=3000000),
                make_signatory_airline_headers(airline["id"])),
            201,
        )
        # min(3_000_000, 2_000_000) * 450 = 900_000_000
        assert application["pfc_amount_cents"] == 900000000, (
            "Passengers beyond the annual cap are not collectible")
        assert application["status"] == "SUBMITTED"

    def test_ineligible_carriers_rejected(self, api):
        """PRD §3.7: "Eligibility is strict: the carrier's `carrier_class` must
        be `PASSENGER` and its `pfc_approved` flag must be true, and anything
        short of both is rejected with `ERR_PFC_INELIGIBLE`"

        Design: Corner/calculations/pfc_ineligible_cargo_rejected
        """
        ws = setup_open_year("FY_PFC2")
        cargo = create_airline("CG", legal_name="Cargo Air",
                               carrier_class="CARGO", pfc_approved=True)
        unapproved = create_airline("UP", legal_name="Unapproved Air",
                                    carrier_class="PASSENGER",
                                    pfc_approved=False)

        for airline in (cargo, unapproved):
            resp = api.create_pfc_application(
                ws["fy"]["id"],
                create_pfc_application_payload(airline["id"],
                                               enplaned_passengers=100),
                make_signatory_airline_headers(airline["id"]),
            )
            validate_error(resp, ApiErrorId.ERR_PFC_INELIGIBLE)
