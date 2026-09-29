"""Both variants of the filing fee assessment, both variants of the response
deadline, and the two bases on which a panel outcome can be reached.
"""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    admit_panelist,
    appointment_payload,
    api_client,
    assert_case,
    assert_case_money_invariants,
    assert_honoraria_waterfall,
    case_version,
    fund_case_to_assessment,
    read_appointment,
    record_delivery,
    read_case,
    set_clock,
    setup_commenced_case,
    setup_filed_case,
    setup_issued_three_member_decision,
    setup_responded_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFilingFeeVariants:
    def test_filing_prices_the_provisional_single_member_variant(self):
        """PRD §3.2: "A standard single-member filing therefore assesses 150000
        cents entirely to the complainant with a pool of 105000 cents, and an
        expedited single-member filing assesses 168750 cents entirely to the
        complainant with a pool of 118125 cents."

        Design: Difficulty/dual_variant_calc/filing_fee_provisional_at_filing_vs_final_at_respondent_election
        """
        bundle = setup_filed_case(pay_filing_fee=False)
        case = bundle["case"]
        assert_case(case)
        assert case["status"] == "FILED"
        assert case["fee_variant_applied"] == "PROVISIONAL"
        assert case["required_seat_count"] == 1
        assert case["respondent_panel_election"] == "NONE"
        assert case["assessed_fee_cents"] == 150000
        assert case["complainant_share_cents"] == 150000
        assert case["respondent_share_cents"] == 0
        assert case["honoraria_pool_cents"] == 105000
        assert case["paid_cents"] == 0

    def test_three_member_election_reprices_the_case_upward_for_the_complainant(self):
        """PRD §3.5: "The consequence is counter-intuitive and intended: because
        the surcharge is charged on the base fee alone and the respondent is
        billed only half the raw supplement, the **complainant's** share rises
        when the respondent elects a larger panel — from 150000 to 275000 cents
        on a standard case, and from 168750 to 293750 cents on an expedited one."
        PRD §3.5: "The re-pricing writes no adjusting ledger line: all four money
        fields are overwritten in place while every existing ledger line stands
        untouched, so a case that was fully paid a moment earlier is instantly in
        arrears by the difference, and the parties must pay the gap before the
        panel can be nominated."

        Design: Difficulty/dual_variant_calc/filing_fee_provisional_at_filing_vs_final_at_respondent_election
        """
        bundle = setup_responded_case(requests_three_member_panel=True)
        case = bundle["case"]
        assert case["status"] == "RESPONSE_RECEIVED"
        assert case["respondent_panel_election"] == "THREE"
        assert case["required_seat_count"] == 3
        assert case["fee_variant_applied"] == "FINAL"
        assert case["assessed_fee_cents"] == 400000
        assert case["complainant_share_cents"] == 275000
        assert case["respondent_share_cents"] == 125000
        assert case["honoraria_pool_cents"] == 280000
        assert_case_money_invariants(case)
        # The single filing-fee line is untouched, so the case is now short.
        assert case["paid_cents"] == 150000
        assert case["complainant_paid_cents"] == 150000
        ledger, meta = validate_paginated(
            api_client.list_fee_transactions(case["id"], CASE_MANAGER)
        )
        assert meta["total_count"] == 1, "re-pricing mints no adjusting ledger line"

    def test_nomination_is_refused_until_the_repriced_assessment_is_funded(self):
        """PRD §3.6: "The parties' money must also be in before neutrals are
        engaged: `paid_cents` must be greater than or equal to
        `assessed_fee_cents`, or the nomination is refused with
        `ERR_PANEL_SUPPLEMENT_UNPAID`."

        Design: Difficulty/dual_variant_calc/filing_fee_provisional_at_filing_vs_final_at_respondent_election
        """
        bundle = setup_responded_case(requests_three_member_panel=True)
        case_id = bundle["case"]["id"]
        panelist = admit_panelist(full_name="Anna Bauer", nationality_code="DE")
        payload = appointment_payload("PRESIDING", case_version(case_id))
        payload["panelist_id"] = panelist["id"]
        refused = api_client.create_appointment(case_id, payload, CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_PANEL_SUPPLEMENT_UNPAID.value, 402)

        funded = fund_case_to_assessment(case_id)
        assert funded["paid_cents"] == 400000
        assert funded["complainant_paid_cents"] == 275000
        assert funded["respondent_paid_cents"] == 125000
        payload["expected_case_version"] = case_version(case_id)
        accepted = api_client.create_appointment(case_id, payload, CASE_MANAGER)
        seat = validate_success(accepted, 201)
        assert seat["status"] == "NOMINATED"
        assert seat["seat"] == "PRESIDING"


class TestResponseDeadlineVariants:
    def test_postal_dispatch_projects_the_provisional_deadline(self):
        """PRD §3.5: "The response deadline is then projected in its
        **provisional** form: both `provisional_response_due_at` and
        `response_due_at` are set to the attempt's `dispatched_at` plus its
        `transmission_allowance_days` days plus the 20-day response period, and
        the case records `deadline_variant_applied` as `PROVISIONAL`."

        Design: Difficulty/dual_variant_calc/response_deadline_provisional_at_dispatch_vs_final_at_delivery_moves_backwards
        """
        set_clock("2026-08-05T00:00:00Z")
        bundle = setup_commenced_case(
            channel="POSTAL", iana_id="IANA-2002", domain_name="postalcase.example",
            verification_response_hours=72, legal_name="Nordwind GmbH",
            remedy_requested="CANCELLATION",
        )
        attempt = bundle["notification"]
        assert attempt["channel"] == "POSTAL"
        assert attempt["transmission_allowance_days"] == 5
        assert attempt["dispatched_at"] == "2026-08-05T00:00:00.000Z"
        case = bundle["case"]
        assert case["status"] == "COMMENCED"
        assert case["commenced_at"] == "2026-08-05T00:00:00.000Z"
        assert case["deadline_variant_applied"] == "PROVISIONAL"
        assert case["provisional_response_due_at"] == "2026-08-30T00:00:00.000Z"
        assert case["response_due_at"] == "2026-08-30T00:00:00.000Z"

    def test_delivery_reanchors_the_deadline_backwards_without_clamping(self):
        """PRD §3.5: "Delivery re-anchors the deadline in its **final** form:
        `response_due_at` is replaced by `deemed_received_at` plus the 20-day
        response period — with no transmission allowance, since actual receipt is
        now known — and `deadline_variant_applied` becomes `FINAL`."
        PRD §3.5: "The provisional value stays visible in
        `provisional_response_due_at` for audit."

        Design: Difficulty/dual_variant_calc/response_deadline_provisional_at_dispatch_vs_final_at_delivery_moves_backwards
        """
        set_clock("2026-08-05T00:00:00Z")
        bundle = setup_commenced_case(
            channel="POSTAL", iana_id="IANA-2002", domain_name="postalcase.example",
            verification_response_hours=72, legal_name="Nordwind GmbH",
            remedy_requested="CANCELLATION",
        )
        set_clock("2026-08-07T00:00:00Z")
        record_delivery(bundle, "DELIVERED", deemed_received_at="2026-08-07T00:00:00Z")
        case = read_case(bundle["case"]["id"])
        assert case["deadline_variant_applied"] == "FINAL"
        assert case["response_due_at"] == "2026-08-27T00:00:00.000Z", (
            "the final deadline lands three days earlier than the provisional one"
        )
        assert case["provisional_response_due_at"] == "2026-08-30T00:00:00.000Z"


class TestOutcomeBasisVariants:
    def test_three_way_split_is_decided_by_the_presiding_casting_ballot(self):
        """PRD §3.7: "Otherwise no label commands a majority, and the outcome is
        taken from the ballot cast by the `PRESIDING` seat, with `outcome_basis`
        recorded as `PRESIDING_CASTING`."
        PRD §3.7: "`dissent_present` is true when the ballots were not unanimous
        — equivalently, when the leading count is below `required_seat_count`."

        Design: Difficulty/dual_variant_calc/panel_outcome_strict_majority_vs_presiding_casting_on_three_way_split
        """
        bundle = setup_issued_three_member_decision(
            votes=["CANCELLATION", "TRANSFER", "DENY"],
            iana_id="IANA-3003", domain_name="splitpanel.example",
            legal_name="Trois SARL",
        )
        decision = bundle["decision"]
        assert decision["transfer_votes"] == 1
        assert decision["cancellation_votes"] == 1
        assert decision["deny_votes"] == 1
        assert decision["outcome"] == "CANCELLATION"
        assert decision["outcome_basis"] == "PRESIDING_CASTING"
        assert decision["dissent_present"] is True
        assert decision["rdnh_finding"] is False
        assert decision["status"] == "ISSUED"
        assert decision["issued_at"] == "2026-08-01T00:00:00.000Z"
        assert decision["implementation_deadline_at"] == "2026-08-14T00:00:00.000Z"
        case = read_case(bundle["case"]["id"])
        assert case["status"] == "IMPLEMENTATION_WAITING"
        assert case["paid_cents"] == 400000
        appointments = [read_appointment(a["id"]) for a in bundle["appointments"]]
        assert_honoraria_waterfall(appointments, 280000)
        assert [a["honoraria_cents"] for a in appointments] == [112000, 84000, 84000]

    def test_unanimous_three_member_panel_is_decided_by_strict_majority(self):
        """PRD §3.7: "When twice the leading count exceeds `required_seat_count`,
        that leading label becomes the `outcome` and `outcome_basis` is
        `STRICT_MAJORITY` — which covers every single-member decision, and every
        three-member decision where two or three seats agree."

        Design: Difficulty/dual_variant_calc/panel_outcome_strict_majority_vs_presiding_casting_on_three_way_split
        """
        bundle = setup_issued_three_member_decision(
            votes=["TRANSFER", "TRANSFER", "TRANSFER"],
            iana_id="IANA-3004", domain_name="unanimous.example",
            legal_name="Unis SARL",
        )
        decision = bundle["decision"]
        assert decision["transfer_votes"] == 3
        assert decision["cancellation_votes"] == 0
        assert decision["deny_votes"] == 0
        assert decision["outcome"] == "TRANSFER"
        assert decision["outcome_basis"] == "STRICT_MAJORITY"
        assert decision["dissent_present"] is False
