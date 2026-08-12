"""Billing claims: lifecycle, pinned rounding order, and the monthly cap gate."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, document_response, finalize_response,
    get_consult, make_specialist_headers, set_clock,
    setup_answered_consult, setup_assigned_consult, setup_finalized_consult,
    submit_response, validate_error, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestBillingClaims:
    def test_billing_claim_happy_path_to_paid(self, api):
        """PRD §3.9: "A successful submission moves the claim to `SUBMITTED` and
        advances the consult's `billing_status` from `CHARGEABLE` to `CLAIMED`. From
        `SUBMITTED`, the clerk either marks the claim `PAID` or denies it"
        PRD §3.9: "Only then is the documentation add-on computed, and it is derived
        from the **rounded** professional component: ten percent of it when a
        conversion in `SCHEDULED` or `COMPLETED` status exists for the consult, five
        percent otherwise, itself rounded half up to whole cents."

        Design: Corner/state_machines/billing_claim_happy_path_to_paid
        """
        scenario = setup_finalized_consult(
            patient_ref="PAT-S6", provider_npi="1000002006",
            specialist_npi="2000002006", disposition="MANAGE_WITH_PLAN",
            consult_overrides={
                "question_text": "Atrial fibrillation rate control review; current metoprolol dose insufficient per home readings.",
                "icd10_primary": "I48",
            },
        )
        claim = validate_success(
            api.create_billing_claim(scenario["consult"]["id"], BILLING), 201
        )
        assert claim["status"] == "DRAFT"
        # ROUTINE + no conversion: 10000 professional + 5% add-on 500 = 10500.
        assert claim["amount_cents"] == 10500
        assert claim["claim_code"] == "ECONSULT-RUT-ANSW"

        submitted = validate_success(api.submit_claim(claim["id"], BILLING), 200)
        assert submitted["status"] == "SUBMITTED"
        consult = get_consult(scenario["consult"]["id"])
        assert consult["billing_status"] == "CLAIMED"
        assert consult["status"] == "ANSWERED"

        paid = validate_success(api.mark_claim_paid(claim["id"], BILLING), 200)
        assert paid["status"] == "PAID"

    def test_denied_claim_writeoff_voids_consult_billing(self, api):
        """PRD §3.9: "From `SUBMITTED`, the clerk either marks the claim `PAID` or
        denies it; denial moves it to `DENIED`. Writing off a denied claim moves it to
        `VOID` and drops the consult's `billing_status` from `CLAIMED` to `VOID`."

        Design: Corner/state_machines/denied_claim_writeoff_voids_consult_billing
        """
        scenario = setup_finalized_consult(
            patient_ref="PAT-S7", provider_npi="1000002007",
            specialist_npi="2000002007",
            consult_overrides={
                "question_text": "Orthostatic dizziness on midodrine; asks about dose timing relative to meals and bedtime.",
                "icd10_primary": "I95",
            },
        )
        claim = validate_success(
            api.create_billing_claim(scenario["consult"]["id"], BILLING), 201
        )
        validate_success(api.submit_claim(claim["id"], BILLING), 200)

        denied = validate_success(api.deny_claim(claim["id"], BILLING), 200)
        assert denied["status"] == "DENIED"
        # Denial alone does NOT move the consult's billing status.
        assert get_consult(scenario["consult"]["id"])["billing_status"] == "CLAIMED"

        voided = validate_success(api.write_off_claim(claim["id"], BILLING), 200)
        assert voided["status"] == "VOID"
        # Only the write-off drops the consult's billing status to VOID.
        assert get_consult(scenario["consult"]["id"])["billing_status"] == "VOID"

    def test_urgent_claim_uses_urgent_sla_and_code(self, api):
        """PRD §3.5: the consult's `sla_due_at` is "computed at assignment time as the
        consult's `created_at` plus the track's `urgent_target_hours` when the
        consult's `urgency` is `URGENT`"
        PRD §3.9: "The `claim_code` is the string "ECONSULT-" followed by "URG" when
        the consult's `urgency` is `URGENT` (otherwise "RUT"), a hyphen, and "CONV"
        when the response's disposition is `CONVERT_TO_VISIT` (otherwise "ANSW")."
        PRD §3.9: "Creation computes the claim's two derived fields and leaves it in
        `DRAFT`."

        Design: Difficulty/combinatorial_formula/claim_amount_rounds_per_component_then_sums
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-CF3", provider_npi="1000000031",
            specialist_npi="2000000031",
            track_overrides={"specialty_code": "DERMATOLOGY",
                             "base_response_fee_cents": 9999},
            consult_overrides={
                "question_text": "Rapidly spreading urticarial rash unresponsive to cetirizine; urgent guidance on steroid course.",
                "icd10_primary": "L50", "urgency": "URGENT",
            },
        )
        consult = scenario["consult"]
        # URGENT target 12h from creation 2026-06-01T00:00:00Z.
        assert _parse(consult["sla_due_at"]) == datetime(
            2026, 6, 1, 12, tzinfo=timezone.utc
        )
        set_clock("2026-06-01T01:00:00Z")  # respond well within the urgent SLA
        response = submit_response(
            consult["id"], scenario["specialist"]["id"],
            disposition="MANAGE_WITH_PLAN",
            recommendation_text="Prednisone 40mg daily x5 days, add famotidine 20mg BID, escalate if airway symptoms.",
        )
        assert response["on_time"] is True
        document_response(response["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        finalize_response(response["id"], scenario["specialist"]["id"])
        claim = validate_success(api.create_billing_claim(consult["id"], BILLING), 201)
        assert claim["status"] == "DRAFT"
        assert claim["claim_code"] == "ECONSULT-URG-ANSW"

    def test_claim_amount_rounds_per_component_then_sums(self, api):
        """PRD §3.9: "First the professional component: the track's
        `base_response_fee_cents` multiplied by an urgency factor — 1.5 when the
        consult is `URGENT`, 1.0 when `ROUTINE` — rounded half up to whole cents. Only
        then is the documentation add-on computed, and it is derived from the
        **rounded** professional component: ten percent of it when a conversion in
        `SCHEDULED` or `COMPLETED` status exists for the consult, five percent
        otherwise, itself rounded half up to whole cents. The claim amount is the sum
        of the rounded component and the rounded add-on. Deriving the add-on from the
        unrounded component and rounding once at the end yields a different cent value
        and is non-conformant."

        Design: Difficulty/combinatorial_formula/claim_amount_rounds_per_component_then_sums
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-CF3", provider_npi="1000000031",
            specialist_npi="2000000031",
            track_overrides={"specialty_code": "DERMATOLOGY",
                             "base_response_fee_cents": 9999},
            consult_overrides={
                "question_text": "Rapidly spreading urticarial rash unresponsive to cetirizine; urgent guidance on steroid course.",
                "icd10_primary": "L50", "urgency": "URGENT",
            },
        )
        consult = scenario["consult"]
        set_clock("2026-06-01T01:00:00Z")
        response = submit_response(
            consult["id"], scenario["specialist"]["id"],
            disposition="MANAGE_WITH_PLAN",
            recommendation_text="Prednisone 40mg daily x5 days, add famotidine 20mg BID, escalate if airway symptoms.",
        )
        document_response(response["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        finalize_response(response["id"], scenario["specialist"]["id"])
        claim = validate_success(api.create_billing_claim(consult["id"], BILLING), 201)
        # Pinned order: professional = round_half_up(9999 * 1.5) = 14999;
        # add-on = round_half_up(14999 * 0.05) = 750; amount = 15749.
        assert claim["amount_cents"] == 15749, (
            "pinned per-component rounding yields 15749 (round-once-at-end "
            "would yield 15748)"
        )

    def test_claim_amount_uses_conversion_addon_ten_percent(self, api):
        """PRD §3.9: "Only then is the documentation add-on computed, and it is
        derived from the **rounded** professional component: ten percent of it when a
        conversion in `SCHEDULED` or `COMPLETED` status exists for the consult, five
        percent otherwise"

        Design: Corner/calculations/claim_amount_uses_conversion_addon_ten_percent
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-C3", provider_npi="1000003003",
            specialist_npi="2000003003", disposition="CONVERT_TO_VISIT",
            consult_overrides={
                "question_text": "HOCM with worsening obstruction symptoms despite beta blocker; needs in-person evaluation.",
                "icd10_primary": "I42",
            },
            response_overrides={
                "recommendation_text": "Obstructive HCM refractory to medical therapy needs in-person visit for myectomy evaluation.",
            },
        )
        validate_success(api.create_conversion(
            scenario["consult"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            make_specialist_headers(scenario["specialist"]["id"]),
        ), 201)
        claim = validate_success(
            api.create_billing_claim(scenario["consult"]["id"], BILLING), 201
        )
        # ROUTINE professional 10000 + 10% conversion add-on 1000 = 11000.
        assert claim["amount_cents"] == 11000
        assert claim["claim_code"] == "ECONSULT-RUT-CONV"

    def _setup_low_cap_claim_scenario(self):
        """RHEUMATOLOGY track with a 100-cent monthly cap; consult answered on time
        but NOT yet documented; a DRAFT claim of 10500 cents exists."""
        scenario = setup_answered_consult(
            patient_ref="PAT-PP1", provider_npi="1000000081",
            specialist_npi="2000000081",
            track_overrides={"specialty_code": "RHEUMATOLOGY",
                             "monthly_billing_cap_cents": 100},
            consult_overrides={
                "question_text": "Rheumatoid flare on methotrexate; asks about short prednisone bridge and infection screening.",
                "icd10_primary": "M06",
            },
            disposition="MANAGE_WITH_PLAN",
            response_overrides={
                "recommendation_text": "Prednisone 20mg daily x7 days with taper; screen HBV/HCV before any biologic escalation.",
            },
        )
        claim = validate_success(
            api_client.create_billing_claim(scenario["consult"]["id"], BILLING), 201
        )
        # ROUTINE, no conversion: professional 10000 + 5% add-on 500.
        assert claim["amount_cents"] == 10500
        scenario["claim"] = claim
        return scenario

    def test_claim_submit_state_error_beats_fiscal_error(self, api):
        """PRD §3.9: "The claim must be `DRAFT` (`ERR_CLAIM_INVALID_STATE`), and the
        consult's `billing_status` must be `CHARGEABLE` (`ERR_CONSULT_NOT_CHARGEABLE`)"
        PRD §2.8: "Only then are state-machine preconditions evaluated, then the
        standing and segregation-of-duties gates, then uniqueness and cap rules, then
        interval and overlap rules, then the usability of referenced actors, and
        finally — last, so that every cheaper rejection is detected before it — the
        aggregate fiscal gate on claim submission."

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_error_beats_fiscal_error
        """
        scenario = self._setup_low_cap_claim_scenario()
        # Both gates are violated: billing_status is PENDING_DOCUMENTATION (state)
        # and 10500 cents exceed the 100-cent monthly cap (fiscal). The state
        # precondition is evaluated before the fiscal gate.
        res = api.submit_claim(scenario["claim"]["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_CONSULT_NOT_CHARGEABLE,
                       expected_status=409)

    def test_claim_submit_fiscal_error_after_state_cured(self, api):
        """PRD §3.9: "The monthly cap check then sums the `amount_cents` of every
        claim belonging to the same track — claims are attributed to a track through
        their consult — whose `status` is `SUBMITTED` or `PAID` and whose `period_key`
        matches the new claim's, and rejects the submission with
        `ERR_TRACK_BILLING_CAP_EXCEEDED` (HTTP 402) when that consumed total plus the
        new claim's amount would exceed the track's `monthly_billing_cap_cents`."

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_error_beats_fiscal_error
        """
        scenario = self._setup_low_cap_claim_scenario()
        # Cure the state gate: document both sides and finalize -> CHARGEABLE.
        document_response(scenario["response"]["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        finalize_response(scenario["response"]["id"], scenario["specialist"]["id"])
        assert get_consult(scenario["consult"]["id"])["billing_status"] == "CHARGEABLE"
        res = api.submit_claim(scenario["claim"]["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_TRACK_BILLING_CAP_EXCEEDED,
                       expected_status=402)
