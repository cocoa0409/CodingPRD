"""Difficulty-design coverage — at least two tests per declared
instance per the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>` tag
so coverage can be audited. Each test pins to a verbatim PRD sentence
stating the underlying rule.

The difficulty-design index covers 9 rules × 2 instances = 18
instances. Each instance has at least two dedicated tests below.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ATTORNEY_ID,
    ApiErrorId,
    accept_offer,
    advance_clock_seconds,
    advance_clock_to_iso,
    api_client,
    approve_disbursement,
    approve_disbursement_payload,
    assert_disbursement_conservation,
    create_case,
    create_client,
    create_contingency_fee,
    create_court_event,
    create_court_event_payload,
    create_damages_multiplier,
    create_damages_multiplier_payload,
    create_demand_letter,
    create_demand_letter_payload,
    create_lien,
    create_med_request,
    create_offer,
    create_settlement_offer_payload,
    dismiss_case,
    get_case,
    get_damages,
    iso_utc,
    make_managing_partner_headers,
    minor_dob_for,
    adult_dob_for,
    parse_iso_date,
    patch_damages_payload,
    patch_damages_to_per_diem,
    receive_med_request,
    recent_incident_date,
    reject_med_request,
    send_demand_letter,
    send_demand_letter_payload,
    send_med_request,
    server_now_dt,
    setup_case_with_fee,
    setup_demand_sent,
    setup_negotiating,
    setup_negotiating_with_two_pending_offers,
    setup_negotiation_chain,
    setup_ready_for_demand,
    setup_records_pending,
    setup_settled,
    setup_settled_via_litigation,
    setup_settled_with_liens,
    setup_two_demand_sent_cases,
    TEST_USERS,
    toll_case,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_damages_multiplier_vs_per_diem_differ(self, api):
        """# difficulty: dual_variant_calc/damages_total_multiplier_vs_per_diem

        PRD §3.4: "under the MULTIPLIER method it is the economic
        component multiplied by multiplier_value, with the product
        rounded half-up to a whole number of cents; under the PER_DIEM
        method it is per_diem_rate_cents multiplied by per_diem_days,
        with no rounding because both operands are already integer
        values."

        Claim: same row with same economic inputs (medical 2_000_000,
        lost_wages 500_000) produces different total_damages_cents
        when method flips from MULTIPLIER(3.0) to PER_DIEM(15000,365).
        """
        _, case, _, request = setup_records_pending()
        damages = create_damages_multiplier(
            case["id"], lost_wages_cents=500_000,
            property_damage_cents=0, multiplier_value=3.0,
        )
        send_med_request(case["id"], request["id"])
        receive_med_request(case["id"], request["id"], 2_000_000)
        # economic = 2_000_000 + 500_000 = 2_500_000
        # pain_mult = 2_500_000 * 3.0 = 7_500_000
        # total = 10_000_000
        d_mult = get_damages(case["id"])
        assert d_mult["total_damages_cents"] == 10_000_000
        # Now patch to PER_DIEM with rate=15000, days=365 → pain=5_475_000
        d_per = patch_damages_to_per_diem(
            case["id"], 15_000, 365, version=d_mult["version"],
        )
        # economic unchanged = 2_500_000
        # pain_per = 15_000 * 365 = 5_475_000
        # total = 2_500_000 + 5_475_000 = 7_975_000
        assert d_per["total_damages_cents"] == 7_975_000
        assert d_mult["total_damages_cents"] != d_per["total_damages_cents"]

    def test_damages_method_branch_pin_values(self, api):
        """# difficulty: dual_variant_calc/damages_total_multiplier_vs_per_diem

        PRD §3.4: "pain_suffering_cents is computed according to the
        active method: under the MULTIPLIER method it is the economic
        component multiplied by multiplier_value ...; under the
        PER_DIEM method it is per_diem_rate_cents multiplied by
        per_diem_days, with no rounding".

        Claim: pin pain_suffering_cents == 7_500_000 (MULT) and
        5_475_000 (PER_DIEM) on the SAME row across the flip.
        """
        _, case, _, request = setup_records_pending()
        damages = create_damages_multiplier(
            case["id"], lost_wages_cents=500_000, multiplier_value=3.0,
        )
        send_med_request(case["id"], request["id"])
        receive_med_request(case["id"], request["id"], 2_000_000)
        d_mult = get_damages(case["id"])
        assert d_mult["pain_suffering_cents"] == 7_500_000
        d_per = patch_damages_to_per_diem(
            case["id"], 15_000, 365, version=d_mult["version"],
        )
        assert d_per["pain_suffering_cents"] == 5_475_000

    def test_disbursement_chronological_vs_prorata_diverge(self, api):
        """# difficulty: dual_variant_calc/net_disbursement_chronological_vs_prorata

        PRD §3.10: "Both disbursement variants —
        CHRONOLOGICAL_PRIORITY and FORWARD_LOOKING_PRORATA — share the
        same priority ordering and tie-break and the same lien-status
        preconditions; they differ only in the per-lien payment
        formula and (in the pro-rata case) the residual-rounding rule
        that hands the final cents to the last lien."

        Claim: For the same gross, costs, fee tier and identical lien
        set, the two strategies produce different client_net_cents.
        """
        # Two parallel cases — A chronological, B prorata.
        case_a = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
            medicare_face_cents=1_500_000,
            provider_negotiated_face_cents=800_000,
            provider_negotiated_reduced_to_cents=400_000,
        )
        case_b = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
            medicare_face_cents=1_500_000,
            provider_negotiated_face_cents=800_000,
            provider_negotiated_reduced_to_cents=400_000,
        )
        d_chron = approve_disbursement(
            case_a["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        d_prora = approve_disbursement(
            case_b["case"]["id"], "FORWARD_LOOKING_PRORATA",
        )
        assert d_chron["client_net_cents"] != d_prora["client_net_cents"]
        assert_disbursement_conservation(d_chron)
        assert_disbursement_conservation(d_prora)

    def test_chronological_statutory_reduction_pin(self, api):
        """# difficulty: dual_variant_calc/net_disbursement_chronological_vs_prorata

        PRD §3.10: "the reduced figure for the lien is
        face_amount_cents multiplied by the quantity one minus the
        attorney ratio minus the cost ratio, with the product rounded
        half-up to a whole number of cents".

        Claim: under chronological, MEDICARE.final_paid_amount_cents
        == 962_550, PROVIDER (negotiated to 400_000) ==
        final_paid_amount_cents == 400_000.
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
            medicare_face_cents=1_500_000,
            provider_negotiated_face_cents=800_000,
            provider_negotiated_reduced_to_cents=400_000,
        )
        approve_disbursement(case["case"]["id"], "CHRONOLOGICAL_PRIORITY")
        # Re-fetch liens to inspect final_paid_amount.
        resp = api_client.list_liens(
            case["case"]["id"], TEST_USERS["managing_partner_headers"],
        )
        liens, _ = validate_paginated(resp)
        by_type = {l["lien_type"]: l for l in liens}
        assert by_type["MEDICARE"]["final_paid_amount_cents"] == 962_550
        assert by_type["PROVIDER_NEGOTIATED"]["final_paid_amount_cents"] == 400_000


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_net_disbursement_pre_suit_branch_no_filed(self, api):
        """# difficulty: combinatorial_formula/net_disbursement_nested_min_with_state_branch

        PRD §3.9: "Otherwise, the pre-suit rate pre_suit_rate_bps
        applies — this is the path taken when the case settles before
        any complaint is filed."

        Claim: SETTLED via NEGOTIATING (filed_in_court==false) uses
        pre_suit_rate_bps for the attorney fee — pin
        attorney_fee_cents=3_333_000 at rate 3333 over gross 10_000_000.
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
        )
        d = approve_disbursement(
            case["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        # filed_in_court==false on this case (SETTLED via NEGOTIATING).
        refreshed = get_case(case["case"]["id"])
        # Re-fetch — should be CLOSED now; but we're checking the
        # pre-suit tier was selected at approval time.
        assert d["attorney_fee_cents"] == 3_333_000
        assert_disbursement_conservation(d)

    def test_net_disbursement_chronological_three_lien_pin(self, api):
        """# difficulty: combinatorial_formula/net_disbursement_nested_min_with_state_branch

        PRD §3.10: chronological waterfall with statutory (MEDICARE,
        CHILD_SUPPORT) ASSERTED-auto-reduce + a negotiated
        PROVIDER_NEGOTIATED lien. PRD §3.9: "if Case.filed_in_court is
        true, the post-suit rate post_suit_rate_bps applies".

        Claim: gross=10_000_000, costs=250_000, pre_suit_rate_bps=3333
        (case settled via NEGOTIATING, filed_in_court==false),
        MEDICARE=1_500_000, CHILD_SUPPORT=500_000,
        PROVIDER_NEGOTIATED reduced to 400_000 → attorney_fee=3_333_000,
        MEDICARE final=962_550, CHILD_SUPPORT final=320_850,
        PROVIDER_NEGOTIATED final=400_000, client_net=4_733_600.
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
            medicare_face_cents=1_500_000,
            provider_negotiated_face_cents=800_000,
            provider_negotiated_reduced_to_cents=400_000,
            extra_liens=[{
                "lien_type": "CHILD_SUPPORT",
                "face_amount_cents": 500_000,
            }],
        )
        d = approve_disbursement(
            case["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        assert d["attorney_fee_cents"] == 3_333_000
        # Inspect lien final_paid.
        resp = api_client.list_liens(
            case["case"]["id"], TEST_USERS["managing_partner_headers"],
        )
        liens, _ = validate_paginated(resp)
        by_type = {l["lien_type"]: l for l in liens}
        assert by_type["MEDICARE"]["final_paid_amount_cents"] == 962_550
        assert by_type["CHILD_SUPPORT"]["final_paid_amount_cents"] == 320_850
        assert by_type["PROVIDER_NEGOTIATED"]["final_paid_amount_cents"] == 400_000
        # total_lien_payment = 962_550 + 320_850 + 400_000 = 1_683_400
        # client_net = 10_000_000 - 3_333_000 - 250_000 - 1_683_400 = 4_733_600
        assert d["client_net_cents"] == 4_733_600
        assert_disbursement_conservation(d)

    def test_attorney_fee_half_up_rounding_pin(self, api):
        """# difficulty: combinatorial_formula/attorney_fee_rounding_order_pin

        PRD §3.9: "The attorney fee in cents is the gross settlement
        multiplied by the chosen rate divided by ten thousand, with
        the product rounded half-up to a whole number of cents."

        Claim: gross=10_000_002, rate=3333 bps →
        10_000_002 * 3333 / 10000 = 3_333_000.6666 →
        attorney_fee_cents == 3_333_001 (half-up), client_net=6_667_001.
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_002,
            case_costs_cents=0,
            pre_suit_rate_bps=3333,
        )
        d = approve_disbursement(
            case["case"]["id"], "FORWARD_LOOKING_PRORATA",
        )
        assert d["attorney_fee_cents"] == 3_333_001, (
            "PRD §3.9: round half up — expected 3_333_001, got "
            f"{d['attorney_fee_cents']}"
        )
        assert d["client_net_cents"] == 6_667_001
        assert_disbursement_conservation(d)

    def test_attorney_fee_half_up_rounding_under_chronological(self, api):
        """# difficulty: combinatorial_formula/attorney_fee_rounding_order_pin

        PRD §2.5: "the system applies round half up to the nearest
        integer cent. Banker's rounding is explicitly not used."
        PRD §3.9: "The attorney fee in cents is the gross settlement
        multiplied by the chosen rate divided by ten thousand, with
        the product rounded half-up to a whole number of cents."

        Claim: half-up rounding is independent of strategy — the same
        gross=10_000_002, rate=3333 under CHRONOLOGICAL_PRIORITY also
        yields attorney_fee==3_333_001 (NOT 3_333_000, which would be
        the floor).
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_002,
            case_costs_cents=0,
            pre_suit_rate_bps=3333,
        )
        d = approve_disbursement(
            case["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        assert d["attorney_fee_cents"] == 3_333_001
        # client_net = gross - fee - costs - liens
        assert d["client_net_cents"] == 6_667_001
        assert_disbursement_conservation(d)

    def test_sol_deadline_evaluation_order_minor_then_toll(self, api):
        """# difficulty: combinatorial_formula/sol_deadline_evaluation_order_pin

        PRD §3.2: "Second, if the client's is_minor_at_incident is
        true, the system computes a minor-tail deadline by adding 18
        years plus a jurisdiction-specific minor tail to the client's
        date_of_birth (California's minor tail is 2 years, New York's
        is 3 years, and Texas's is 2 years) and replaces the base
        deadline with whichever of the base deadline and the
        minor-tail deadline is later."
        PRD §3.2: "Third, the resulting deadline is shifted forward
        by sol_tolled_days calendar days to yield the effective
        sol_deadline."

        Claim: minor client + 10-day tolling → sol_deadline =
        max(base, minor) + 10 days (the tolling is applied AFTER the
        max).
        """
        # Pick a recent incident date so SoL hasn't fired against
        # whatever clock the server is on.
        inc_iso = recent_incident_date(days_ago=90)
        # Minor at 14 → dob + 20y = inc + 4 years after inc + 2y =
        # roughly 6 years after incident.
        dob_iso = minor_dob_for(inc_iso, age_at_incident=14)
        client = create_client(date_of_birth=dob_iso)
        case = create_case(
            client["id"], incident_date=inc_iso,
            incident_type="AUTO", jurisdiction_state="CA",
        )
        base = parse_iso_date(case["sol_deadline"])
        # Toll 10 days.
        toll_case(case["id"], 10, reason="incapacity")
        refreshed = get_case(case["id"])
        new_deadline = parse_iso_date(refreshed["sol_deadline"])
        assert (new_deadline - base).days == 10, (
            f"PRD §3.2: tolling adds days to the (max base, minor) "
            f"deadline. Expected +10 days from {base}, got {new_deadline}"
        )
        assert refreshed["sol_tolled_days"] == 10

    def test_sol_minor_tail_max_wins_over_base(self, api):
        """# difficulty: combinatorial_formula/sol_deadline_evaluation_order_pin

        PRD §3.2: "replaces the base deadline with whichever of the
        base deadline and the minor-tail deadline is later."

        Claim: For a young minor (age 6 at CA AUTO incident), the
        minor-tail deadline (dob+20y) is later than incident+2y, so
        sol_deadline == dob+20y exactly.
        """
        inc_iso = recent_incident_date(days_ago=90)
        # Age 6 at incident → dob+20y is ~14 years past incident,
        # whereas incident+2y is just 2 years past incident.
        dob_iso = minor_dob_for(inc_iso, age_at_incident=6)
        client = create_client(date_of_birth=dob_iso)
        case = create_case(
            client["id"], incident_date=inc_iso,
            incident_type="AUTO", jurisdiction_state="CA",
        )
        # Expected minor deadline = dob + 18 + 2 = dob + 20y.
        dob = parse_iso_date(dob_iso)
        minor_deadline_year = dob.year + 20
        minor_deadline = dob.replace(year=minor_deadline_year)
        assert case["sol_deadline"] == minor_deadline.isoformat(), (
            f"PRD §3.2 minor-tail max — expected {minor_deadline}, "
            f"got {case['sol_deadline']}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_settlement_offer_cyclic_three_rounds(self, api):
        """# difficulty: non_linear_state_machine/settlement_offer_cyclic_counter_rounds

        PRD §3.6: "the server computes round_number as the length of
        the chain of predecessors plus one. ... Recording a counter
        automatically flips the predecessor offer from PENDING to
        COUNTERED."

        Claim: chain of three offers (round 1→2→3) with O1.status==
        COUNTERED, O2.status==COUNTERED, O3.status==PENDING after a
        DEF→PLA→DEF counter sequence.
        """
        chain = setup_negotiation_chain(
            first_offer_amount_cents=5_000_000,
            second_offer_amount_cents=8_000_000,
            third_offer_amount_cents=6_000_000,
        )
        resp = api_client.list_settlement_offers(
            chain["case"]["id"], TEST_USERS["attorney_headers"],
        )
        offers, _ = validate_paginated(resp)
        by_round = {o["round_number"]: o for o in offers}
        assert by_round[1]["status"] == "COUNTERED"
        assert by_round[2]["status"] == "COUNTERED"
        assert by_round[3]["status"] == "PENDING"
        # Party alternation
        assert by_round[1]["offer_party"] == "DEFENDANT"
        assert by_round[2]["offer_party"] == "PLAINTIFF"
        assert by_round[3]["offer_party"] == "DEFENDANT"

    def test_round_number_increments_along_predecessor_chain(self, api):
        """# difficulty: non_linear_state_machine/settlement_offer_cyclic_counter_rounds

        PRD §3.6: "the server computes round_number as the length of
        the chain of predecessors plus one. The first offer registered
        on a case omits predecessor_offer_id and is round 1."

        Claim: round numbers 1, 2, 3 line up with the predecessor chain.
        """
        chain = setup_negotiation_chain()
        assert chain["o1"]["round_number"] == 1
        assert chain["o2"]["round_number"] == 2
        assert chain["o3"]["round_number"] == 3
        # Predecessor wiring
        assert chain["o1"].get("predecessor_offer_id") in (None, "")
        assert chain["o2"]["predecessor_offer_id"] == chain["o1"]["id"]
        assert chain["o3"]["predecessor_offer_id"] == chain["o2"]["id"]

    def test_case_branches_to_negotiating_or_litigation(self, api):
        """# difficulty: non_linear_state_machine/case_branching_demand_to_negotiating_or_litigation

        PRD §3.6: "The first defendant-party offer registered against
        a case in DEMAND_SENT cascades the demand letter from SENT to
        RESPONDED and the case from DEMAND_SENT to NEGOTIATING."
        PRD §3.7: "If the case is in DEMAND_SENT with no defendant
        offer received and the demand letter's response_due_at has
        already passed, that filing cascades the demand letter from
        SENT to SUPERSEDED, flips Case.filed_in_court to true, and
        advances the case from DEMAND_SENT to LITIGATION."

        Claim: Case A receives a defendant offer → NEGOTIATING; Case
        B advances past response_due_at and gets a COMPLAINT_FILED →
        LITIGATION.
        """
        case_a, _, case_b, _ = setup_two_demand_sent_cases()
        # Case A: defendant offer → NEGOTIATING
        create_offer(case_a["id"], "DEFENDANT", 5_000_000)
        refreshed_a = get_case(case_a["id"])
        assert refreshed_a["status"] == "NEGOTIATING"
        assert refreshed_a["filed_in_court"] is False

        # Case B: advance clock past response_due_at (30 days) and
        # file complaint → LITIGATION.
        advance_clock_seconds(31 * 86400)
        now_dt = server_now_dt()
        create_court_event(
            case_b["id"], "COMPLAINT_FILED",
            scheduled_at=iso_utc(now_dt + timedelta(days=14)),
            duration_minutes=30,
        )
        refreshed_b = get_case(case_b["id"])
        assert refreshed_b["status"] == "LITIGATION"
        assert refreshed_b["filed_in_court"] is True

    def test_negotiating_branch_to_litigation_with_offers_withdrawn(
        self, api,
    ):
        """# difficulty: non_linear_state_machine/case_branching_demand_to_negotiating_or_litigation

        PRD §3.7: "If the case is in NEGOTIATING with at least one
        offer of any round on file and the sol_deadline is still in
        the future, filing the complaint cascades every offer still
        in PENDING to WITHDRAWN, flips Case.filed_in_court to true,
        and advances the case from NEGOTIATING to LITIGATION."

        Claim: Case in NEGOTIATING with one PENDING offer →
        COMPLAINT_FILED → case LITIGATION + filed_in_court==true +
        PENDING offer WITHDRAWN.
        """
        _, case, _, _, _, _, offer = setup_negotiating()
        now_dt = server_now_dt()
        create_court_event(
            case["id"], "COMPLAINT_FILED",
            scheduled_at=iso_utc(now_dt + timedelta(days=14)),
            duration_minutes=30,
        )
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "LITIGATION"
        assert refreshed["filed_in_court"] is True
        # Offer cascade
        resp = api_client.list_settlement_offers(
            case["id"], TEST_USERS["attorney_headers"],
        )
        offers, _ = validate_paginated(resp)
        assert offers[0]["status"] == "WITHDRAWN"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_records_received_three_hop_cascade(self, api):
        """# difficulty: transitive_cascade/records_received_cascade_to_ready_for_demand

        PRD §3.3: "Marking a sent request as received — accomplished
        by patching its status to RECEIVED together with a
        billed_amount_cents value that must be at least zero — stamps
        received_at, persists the billed amount, recomputes
        Damages.medical_bills_cents and Damages.total_damages_cents
        (bumping Damages.version), and, if this was the last
        outstanding non-terminal request and Case.assigned_attorney_id
        is set and Damages.total_damages_cents is now greater than
        zero, advances the case from RECORDS_PENDING to
        READY_FOR_DEMAND."

        Claim: PATCH RECEIVED triggers three observable hops:
        (1) MedicalRecordRequest.status==RECEIVED with billed amount,
        (2) Damages.medical_bills_cents and total_damages_cents
            recomputed, version bumped,
        (3) Case.status flips to READY_FOR_DEMAND.
        """
        _, case, _, request = setup_records_pending()
        damages_before = create_damages_multiplier(
            case["id"], multiplier_value=2.0,
        )
        send_med_request(case["id"], request["id"])
        received = receive_med_request(case["id"], request["id"], 1_000_000)
        # Hop 1
        assert received["status"] == "RECEIVED"
        assert received["billed_amount_cents"] == 1_000_000
        # Hop 2
        damages_after = get_damages(case["id"])
        assert damages_after["medical_bills_cents"] == 1_000_000
        # economic=1M, pain=2M, total=3M
        assert damages_after["total_damages_cents"] == 3_000_000
        assert damages_after["version"] > damages_before["version"]
        # Hop 3
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "READY_FOR_DEMAND"

    def test_records_received_does_not_promote_if_total_zero(
        self, api,
    ):
        """# difficulty: transitive_cascade/records_received_cascade_to_ready_for_demand

        PRD §3.3: "and Damages.total_damages_cents is now greater
        than zero, advances the case from RECORDS_PENDING to
        READY_FOR_DEMAND."

        Claim: If the RECEIVED transition results in total_damages==0
        (billed_amount=0, no wages, no property, MULT 2.0), the case
        stays in RECORDS_PENDING — not promoted.
        """
        _, case, _, request = setup_records_pending()
        create_damages_multiplier(
            case["id"], lost_wages_cents=0, property_damage_cents=0,
            multiplier_value=2.0,
        )
        send_med_request(case["id"], request["id"])
        receive_med_request(case["id"], request["id"], 0)
        refreshed = get_case(case["id"])
        # damages.total_damages_cents is 0 → no promotion.
        assert refreshed["status"] == "RECORDS_PENDING"

    def test_complaint_filed_in_negotiating_three_hop_cascade(
        self, api,
    ):
        """# difficulty: transitive_cascade/complaint_filed_cascade_through_negotiation_to_litigation

        PRD §3.7: "filing the complaint cascades every offer still in
        PENDING to WITHDRAWN, flips Case.filed_in_court to true, and
        advances the case from NEGOTIATING to LITIGATION."

        Claim: Three hops observable:
        (1) CourtEvent created with event_type==COMPLAINT_FILED,
        (2) Case.filed_in_court==true and Case.status==LITIGATION,
        (3) PENDING offers cascaded to WITHDRAWN.
        """
        chain = setup_negotiating_with_two_pending_offers()
        now_dt = server_now_dt()
        ev = create_court_event(
            chain["case"]["id"], "COMPLAINT_FILED",
            scheduled_at=iso_utc(now_dt + timedelta(days=14)),
            duration_minutes=30,
        )
        # Hop 1
        assert ev["event_type"] == "COMPLAINT_FILED"
        # Hop 2
        refreshed = get_case(chain["case"]["id"])
        assert refreshed["filed_in_court"] is True
        assert refreshed["status"] == "LITIGATION"
        # Hop 3
        resp = api_client.list_settlement_offers(
            chain["case"]["id"], TEST_USERS["attorney_headers"],
        )
        offers, _ = validate_paginated(resp)
        by_id = {o["id"]: o for o in offers}
        assert by_id[chain["o3"]["id"]]["status"] == "WITHDRAWN"

    def test_complaint_filed_leaves_countered_offers_untouched(
        self, api,
    ):
        """# difficulty: transitive_cascade/complaint_filed_cascade_through_negotiation_to_litigation

        PRD §3.7: "filing the complaint cascades every offer still in
        PENDING to WITHDRAWN" — so already-COUNTERED offers are NOT
        flipped to WITHDRAWN.

        Claim: COUNTERED offers remain COUNTERED after the cascade
        (only PENDING offers are withdrawn).
        """
        chain = setup_negotiating_with_two_pending_offers()
        now_dt = server_now_dt()
        create_court_event(
            chain["case"]["id"], "COMPLAINT_FILED",
            scheduled_at=iso_utc(now_dt + timedelta(days=14)),
            duration_minutes=30,
        )
        resp = api_client.list_settlement_offers(
            chain["case"]["id"], TEST_USERS["attorney_headers"],
        )
        offers, _ = validate_paginated(resp)
        by_id = {o["id"]: o for o in offers}
        assert by_id[chain["o1"]["id"]]["status"] == "COUNTERED"
        assert by_id[chain["o2"]["id"]]["status"] == "COUNTERED"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_beats_business_fiscal_on_demand_resend(
        self, api, attorney_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_demand_send

        PRD §2.8: "Authentication checks run before role checks, which
        run before existence checks, which run before state-machine
        preconditions, which run before business-safety rules, which
        run before referential and constraint rules, which run before
        temporal and fiscal rules, and the optimistic-concurrency
        check runs last of all."
        PRD §2.8: "A request that fails more than one check surfaces
        only the highest-priority error."

        Claim: When an already-SENT demand letter is re-sent against
        damages that have grown beyond the demanded amount, both the
        state error (ERR_DEMAND_NOT_DRAFT) and the fiscal error
        (ERR_DEMAND_BELOW_DAMAGES) apply — PRD says state precedes
        fiscal, so ERR_DEMAND_NOT_DRAFT is surfaced.
        """
        _, case, _, _, damages, letter = setup_demand_sent()
        # Increase lost_wages so total_damages > demanded.
        api.patch_damages(
            case["id"],
            patch_damages_payload(lost_wages_cents=10_000_000_000,
                                  version=damages["version"]),
            TEST_USERS["paralegal_headers"],
        )
        # Now attempt to re-send the SENT letter; both checks apply
        # but state precedes fiscal.
        resp = api.send_demand_letter(
            case["id"], letter["id"], attorney_headers,
            send_demand_letter_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_NOT_DRAFT.value)

    def test_state_check_priority_holds_for_active_demand_exists(
        self, api, attorney_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_demand_send

        PRD §2.8: "state-machine preconditions, which run before
        business-safety rules, which run before referential and
        constraint rules, which run before temporal and fiscal rules".

        Claim: Resending an already-SENT letter returns
        ERR_DEMAND_NOT_DRAFT (state) rather than any constraint error.
        """
        _, case, _, _, _, letter = setup_demand_sent()
        resp = api.send_demand_letter(
            case["id"], letter["id"], attorney_headers,
            send_demand_letter_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_NOT_DRAFT.value)

    def test_sol_beats_court_event_time_invalid(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_on_court_event

        PRD §2.8: "then the safety rules — statute-of-limitations
        expiry (ERR_STATUTE_OF_LIMITATIONS_EXPIRED), ...; then the
        referential, constraint, temporal, and fiscal rules".

        Claim: When the case is out of statute AND scheduled_at is
        before incident_date, the SoL safety error fires (priority 30)
        before the temporal court-event error (priority 60).
        """
        _, case, _, _ = setup_records_pending()
        # Advance past SoL.
        sol_iso = f"{case['sol_deadline']}T00:00:01.000Z"
        advance_clock_to_iso(sol_iso)
        # Pre-incident scheduled_at would normally trigger
        # ERR_COURT_EVENT_TIME_INVALID.
        inc = parse_iso_date(case["incident_date"])
        bad_iso = f"{(inc - timedelta(days=1)).isoformat()}T12:00:00.000Z"
        resp = api.create_court_event(
            case["id"],
            create_court_event_payload(
                "MOTION_HEARING", bad_iso, 60,
            ),
            TEST_USERS["attorney_headers"],
        )
        validate_error(
            resp,
            ApiErrorId.ERR_STATUTE_OF_LIMITATIONS_EXPIRED.value,
        )

    def test_sol_safety_priority_before_temporal_dual_violation(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_on_court_event

        PRD §2.8: "business-safety rules, which run before
        referential and constraint rules, which run before temporal
        and fiscal rules".
        PRD §2.8: "A request that fails more than one check surfaces
        only the highest-priority error."

        Claim: When the case is out of statute AND scheduled_at is
        before incident_date, the surfaced error is the SoL safety
        error (not the temporal ERR_COURT_EVENT_TIME_INVALID).
        """
        # Reuse fixture from previous test but ensure repeatability.
        _, case, _, _ = setup_records_pending()
        sol_iso = f"{case['sol_deadline']}T00:00:01.000Z"
        advance_clock_to_iso(sol_iso)
        inc = parse_iso_date(case["incident_date"])
        bad_iso = f"{(inc - timedelta(days=1)).isoformat()}T12:00:00.000Z"
        resp = api.create_court_event(
            case["id"],
            create_court_event_payload(
                "MOTION_HEARING", bad_iso, 60,
            ),
            TEST_USERS["attorney_headers"],
        )
        body = resp.json()
        assert body["data"]["error_id"] != (
            ApiErrorId.ERR_COURT_EVENT_TIME_INVALID.value
        ), "PRD §2.8: safety rules precede temporal rules"


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_send_demand_one_second_before_sol_succeeds(self, api):
        """# difficulty: boundary_precision_check/sol_deadline_hard_ge_boundary

        PRD §2.10: "from the instant the server's current time reaches
        or passes sol_deadline, every state-advancing mutation on the
        case is blocked".

        Claim: Sending exactly 1 second before sol_deadline midnight
        SUCCEEDS.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        letter = create_demand_letter(case["id"], damages["total_damages_cents"])
        # Advance to 1 second before midnight of sol_deadline.
        sol_iso = f"{case['sol_deadline']}T00:00:00.000Z"
        sol_dt = parse_iso_date(case["sol_deadline"])
        # advance_clock_to_iso advances to the target; we want one
        # second before.
        target_dt = server_now_dt()  # current time
        from datetime import datetime, timezone
        boundary_minus_1s = datetime(
            sol_dt.year, sol_dt.month, sol_dt.day,
            0, 0, 0, tzinfo=timezone.utc,
        ) - timedelta(seconds=1)
        advance_clock_to_iso(iso_utc(boundary_minus_1s))
        # Should still be in-statute.
        resp = api.send_demand_letter(
            case["id"], letter["id"],
            TEST_USERS["attorney_headers"],
        )
        sent = validate_success(resp)
        assert sent["status"] == "SENT"

    def test_send_demand_at_exact_sol_midnight_blocked(self, api):
        """# difficulty: boundary_precision_check/sol_deadline_hard_ge_boundary

        PRD §2.10: "The comparison is inclusive on the boundary — a
        request that arrives at exactly the deadline is already too
        late."

        Claim: Sending at exactly sol_deadline midnight returns
        ERR_STATUTE_OF_LIMITATIONS_EXPIRED.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        letter = create_demand_letter(case["id"], damages["total_damages_cents"])
        # Advance to exact midnight of sol_deadline.
        sol_iso = f"{case['sol_deadline']}T00:00:00.000Z"
        advance_clock_to_iso(sol_iso)
        resp = api.send_demand_letter(
            case["id"], letter["id"],
            TEST_USERS["attorney_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_STATUTE_OF_LIMITATIONS_EXPIRED.value,
        )

    def test_rejected_request_leaves_case_in_records_pending(self, api):
        """# difficulty: boundary_precision_check/empty_records_set_blocks_ready_for_demand

        PRD §3.3: "advances the case from RECORDS_PENDING to
        READY_FOR_DEMAND" only when "at least one request reached
        RECEIVED" (the natural-language pre-condition).
        PRD §3.3: "If the provider declines, patching status to
        REJECTED records the rejection without any billed amount and
        may leave the case's state unchanged".

        Claim: Single request → REJECTED, Case stays
        RECORDS_PENDING (no RECEIVED → no promotion).
        """
        _, case, _, request = setup_records_pending()
        send_med_request(case["id"], request["id"])
        reject_med_request(case["id"], request["id"])
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "RECORDS_PENDING"

    def test_received_request_promotes_case(self, api):
        """# difficulty: boundary_precision_check/empty_records_set_blocks_ready_for_demand

        PRD §3.3: "if this was the last outstanding non-terminal
        request and Case.assigned_attorney_id is set and
        Damages.total_damages_cents is now greater than zero, advances
        the case from RECORDS_PENDING to READY_FOR_DEMAND."

        Claim: With a single RECEIVED request and non-zero damages,
        Case promotes to READY_FOR_DEMAND. Pairs with the REJECTED
        test above to demonstrate the at-least-one-RECEIVED boundary.
        """
        _, case, _, request = setup_records_pending()
        create_damages_multiplier(case["id"], multiplier_value=2.0)
        send_med_request(case["id"], request["id"])
        receive_med_request(case["id"], request["id"], 500_000)
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "READY_FOR_DEMAND"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_disbursement_blocked_by_negotiating_lien(self, api):
        """# difficulty: cross_entity_state_dependency/case_disbursement_blocked_by_unresolved_liens

        PRD §3.10: "any lien whose status is NEGOTIATING blocks the
        approval (it must first complete to REDUCED or be moved to
        DISPUTED)".

        Claim: Lien in NEGOTIATING state → approve →
        ERR_INVALID_STATE.
        """
        _, case, _, _, _ = setup_settled(case_costs_cents=0)
        lien = create_lien(case["id"], "PROVIDER_NEGOTIATED", 500_000)
        # Open negotiation but never close it.
        api_client.negotiate_lien(
            case["id"], lien["id"], TEST_USERS["paralegal_headers"],
        )
        resp = api.approve_disbursement(
            case["id"],
            approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
            TEST_USERS["managing_partner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_disbursement_blocked_by_asserted_non_statutory_lien(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/case_disbursement_blocked_by_unresolved_liens

        PRD §3.10: "non-statutory liens of type HOSPITAL_STATUTORY,
        ATTORNEY_PRIOR_COUNSEL, or PROVIDER_NEGOTIATED must be in
        REDUCED, RESOLVED, or DISPUTED."

        Claim: Lien in ASSERTED for PROVIDER_NEGOTIATED → approve →
        ERR_INVALID_STATE.
        """
        _, case, _, _, _ = setup_settled(case_costs_cents=0)
        # Create lien but do not negotiate or dispute.
        create_lien(case["id"], "PROVIDER_NEGOTIATED", 500_000)
        resp = api.approve_disbursement(
            case["id"],
            approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
            TEST_USERS["managing_partner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_record_request_send_blocked_on_dismissed_case(self, api):
        """# difficulty: cross_entity_state_dependency/medical_record_request_send_blocked_by_case_status

        PRD §3.3: "Operations against a case whose status is already
        DISMISSED or CLOSED are rejected with ERR_CASE_CLOSED."

        Claim: After dismiss, attempting to send a record request →
        ERR_CASE_CLOSED.
        """
        _, case, _, request = setup_records_pending()
        # Dismiss the case (still in RECORDS_PENDING).
        dismiss_case(case["id"])
        # The dismissal cascade may have flipped the DRAFT request to
        # CANCELED, but in any case the case is now DISMISSED, so the
        # send must reject with ERR_CASE_CLOSED.
        resp = api.send_medical_record_request(
            case["id"], request["id"],
            TEST_USERS["paralegal_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CASE_CLOSED.value)

    def test_record_request_create_blocked_on_dismissed_case(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/medical_record_request_send_blocked_by_case_status

        PRD §3.3: "Operations against a case whose status is already
        DISMISSED or CLOSED are rejected with ERR_CASE_CLOSED."

        Claim: Creating a new record request on a DISMISSED case →
        ERR_CASE_CLOSED.
        """
        _, case, _, _ = setup_records_pending()
        dismiss_case(case["id"])
        from test_helpers import create_medical_record_request_payload
        resp = api.create_medical_record_request(
            case["id"],
            create_medical_record_request_payload(),
            TEST_USERS["paralegal_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CASE_CLOSED.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_attorney_buffered_overlap_rejected(self, api):
        """# difficulty: resource_temporal_overlap/attorney_calendar_buffered_overlap

        PRD §3.7: "with a 15-minute travel buffer added to each side.
        Two events conflict if and only if the later of the two
        buffered start times is strictly less than the earlier of the
        two buffered end times".

        Claim: Two events on the same attorney, second starting 29
        minutes after first ends, buffered intervals overlap (11:14 <
        11:15) → ERR_ATTORNEY_CALENDAR_CONFLICT.
        """
        _, case_a, _, _, _, _, _ = setup_negotiating()
        _, case_b, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        start_a = (now_dt + timedelta(days=30)).replace(
            hour=10, minute=0, second=0, microsecond=0,
        )
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60,
        )
        # 11:29 → buffered [11:14, 12:44), overlaps event_a's
        # buffered tail (11:15).
        start_b = start_a.replace(hour=11, minute=29)
        resp = api.create_court_event(
            case_b["id"],
            create_court_event_payload(
                "MOTION_HEARING", iso_utc(start_b), 60,
            ),
            TEST_USERS["attorney_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_ATTORNEY_CALENDAR_CONFLICT.value,
        )

    def test_attorney_buffered_adjacency_allowed(self, api):
        """# difficulty: resource_temporal_overlap/attorney_calendar_buffered_overlap

        PRD §3.7: "Adjacency exactly at the buffered edge (the
        back-to-back case where one event's buffered end equals the
        next event's buffered start, producing a 30-minute clearance
        between the unbuffered windows) does not conflict and is
        allowed."

        Claim: Second event 30 minutes after first event ends (same
        attorney) accepted.
        """
        _, case_a, _, _, _, _, _ = setup_negotiating()
        _, case_b, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        start_a = (now_dt + timedelta(days=30)).replace(
            hour=10, minute=0, second=0, microsecond=0,
        )
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60,
        )
        # 11:30 → buffered start 11:15 == buffered end of event_a.
        start_b = start_a.replace(hour=11, minute=30)
        ev_b = create_court_event(
            case_b["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_b),
            duration_minutes=60,
        )
        assert ev_b["status"] == "SCHEDULED"

    def test_courtroom_unbuffered_overlap_rejected(self, api):
        """# difficulty: resource_temporal_overlap/courtroom_unbuffered_overlap

        PRD §3.7: "any two events that share the same non-null
        courtroom string conflict if and only if their unbuffered
        half-open intervals (scheduled_at through scheduled_at plus
        duration_minutes) overlap".

        Claim: Two same-courtroom events whose intervals overlap at
        the last minute (14:59 < 15:00) → ERR_COURTROOM_DOUBLE_BOOKED.
        Different attorneys to avoid the attorney rule firing first.
        """
        from test_helpers import ATTORNEY_ID, ATTORNEY_ID_ALT
        client_a = create_client()
        case_a = create_case(
            client_a["id"], assigned_attorney_id=ATTORNEY_ID,
        )
        create_contingency_fee(case_a["id"])
        client_b = create_client()
        case_b = create_case(
            client_b["id"], assigned_attorney_id=ATTORNEY_ID_ALT,
        )
        create_contingency_fee(case_b["id"])
        now_dt = server_now_dt()
        room = "Room-9"
        start_a = (now_dt + timedelta(days=30)).replace(
            hour=14, minute=0, second=0, microsecond=0,
        )
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60, courtroom=room,
        )
        # 14:59 → overlaps at minute 14:59 with [14:00, 15:00).
        start_b = start_a.replace(hour=14, minute=59)
        resp = api.create_court_event(
            case_b["id"],
            create_court_event_payload(
                "MOTION_HEARING", iso_utc(start_b), 60,
                courtroom=room,
            ),
            TEST_USERS["attorney_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_COURTROOM_DOUBLE_BOOKED.value,
        )

    def test_courtroom_exact_adjacency_no_buffer_allowed(self, api):
        """# difficulty: resource_temporal_overlap/courtroom_unbuffered_overlap

        PRD §3.7: "touching boundaries (one event's end equal to the
        next event's start) do not conflict".

        Claim: Same-courtroom events back-to-back (event_a 14:00-15:00,
        event_b 15:00-16:00) both accepted, no buffer applied.
        """
        from test_helpers import ATTORNEY_ID, ATTORNEY_ID_ALT
        client_a = create_client()
        case_a = create_case(
            client_a["id"], assigned_attorney_id=ATTORNEY_ID,
        )
        create_contingency_fee(case_a["id"])
        client_b = create_client()
        case_b = create_case(
            client_b["id"], assigned_attorney_id=ATTORNEY_ID_ALT,
        )
        create_contingency_fee(case_b["id"])
        now_dt = server_now_dt()
        room = "Room-11"
        start_a = (now_dt + timedelta(days=30)).replace(
            hour=14, minute=0, second=0, microsecond=0,
        )
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60, courtroom=room,
        )
        start_b = start_a.replace(hour=15)
        ev_b = create_court_event(
            case_b["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_b),
            duration_minutes=60, courtroom=room,
        )
        assert ev_b["status"] == "SCHEDULED"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_disbursement_cents_conserved_exact(self, api):
        """# difficulty: compensating_invariant/disbursement_cents_conservation

        PRD §3.10: "The post-condition gross_amount_cents minus
        attorney_fee_cents minus case_costs_cents minus
        total_lien_payment_cents must equal client_net_cents with no
        cents drift".

        Claim: gross=10_000_002, case_costs=250_000, no liens, fee
        3333 bps → exact conservation, attorney_fee=3_333_001,
        client_net=6_417_001.
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_002,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
        )
        d = approve_disbursement(
            case["case"]["id"], "FORWARD_LOOKING_PRORATA",
        )
        assert d["gross_amount_cents"] == 10_000_002
        assert d["attorney_fee_cents"] == 3_333_001
        assert d["case_costs_cents"] == 250_000
        assert d["total_lien_payment_cents"] == 0
        assert d["client_net_cents"] == 6_417_001
        # gross == fee + costs + lien + client
        assert (
            d["gross_amount_cents"]
            == d["attorney_fee_cents"]
               + d["case_costs_cents"]
               + d["total_lien_payment_cents"]
               + d["client_net_cents"]
        )
        assert_disbursement_conservation(d)

    def test_disbursement_conservation_with_liens_and_costs(self, api):
        """# difficulty: compensating_invariant/disbursement_cents_conservation

        PRD §3.10: "The post-condition gross_amount_cents minus
        attorney_fee_cents minus case_costs_cents minus
        total_lien_payment_cents must equal client_net_cents with no
        cents drift".

        Claim: Even with statutory liens reducing via ratable formula
        and a non-statutory reduced lien, conservation holds exactly.
        """
        case = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
            medicare_face_cents=1_500_000,
            provider_negotiated_face_cents=800_000,
            provider_negotiated_reduced_to_cents=400_000,
            extra_liens=[{
                "lien_type": "CHILD_SUPPORT",
                "face_amount_cents": 500_000,
            }],
        )
        d = approve_disbursement(
            case["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        assert (
            d["gross_amount_cents"]
            == d["attorney_fee_cents"]
               + d["case_costs_cents"]
               + d["total_lien_payment_cents"]
               + d["client_net_cents"]
        )
        assert_disbursement_conservation(d)

    def test_sol_tolling_days_accumulate_exactly(self, api):
        """# difficulty: compensating_invariant/sol_tolling_days_conservation

        PRD §3.2: "the system adds additional_days to sol_tolled_days
        and reruns the deadline calculation."

        Claim: Three toll calls (7 + 3 + 20) accumulate to
        sol_tolled_days==30 and shift the deadline by 30 calendar days.
        """
        inc_iso = recent_incident_date(days_ago=60)
        client = create_client(date_of_birth=adult_dob_for(inc_iso))
        case = create_case(
            client["id"], incident_date=inc_iso,
            incident_type="AUTO", jurisdiction_state="CA",
        )
        base = parse_iso_date(case["sol_deadline"])
        toll_case(case["id"], 7, reason="incapacity-1")
        toll_case(case["id"], 3, reason="incapacity-2")
        toll_case(case["id"], 20, reason="fraud-concealment")
        refreshed = get_case(case["id"])
        assert refreshed["sol_tolled_days"] == 30
        new_deadline = parse_iso_date(refreshed["sol_deadline"])
        assert (new_deadline - base).days == 30, (
            f"PRD §3.2: tolling shifts deadline by sum of days; "
            f"expected +30, got {(new_deadline - base).days}"
        )

    def test_sol_tolling_single_call_invariant(self, api):
        """# difficulty: compensating_invariant/sol_tolling_days_conservation

        PRD §3.2: "the resulting deadline is shifted forward by
        sol_tolled_days calendar days to yield the effective
        sol_deadline."

        Claim: Single toll of 30 days → sol_tolled_days==30 and
        sol_deadline shifted by exactly 30 days from base.
        """
        inc_iso = recent_incident_date(days_ago=60)
        client = create_client(date_of_birth=adult_dob_for(inc_iso))
        case = create_case(
            client["id"], incident_date=inc_iso,
            incident_type="AUTO", jurisdiction_state="CA",
        )
        base = parse_iso_date(case["sol_deadline"])
        toll_case(case["id"], 30, reason="incapacity")
        refreshed = get_case(case["id"])
        assert refreshed["sol_tolled_days"] == 30
        new_deadline = parse_iso_date(refreshed["sol_deadline"])
        assert (new_deadline - base).days == 30
