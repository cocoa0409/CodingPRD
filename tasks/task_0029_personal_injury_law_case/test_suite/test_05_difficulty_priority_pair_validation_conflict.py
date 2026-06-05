"""Difficulty Rule 5 — priority_pair_validation_conflict.

When two validations would fail on the same request, PRD §2.9 pins which
error_id the server must report:

  • state (priority 5) beats segregation-of-duties (priority 8)
  • statute (priority 7) beats demand-prerequisites (priority 11)
"""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    setup_active_case_with_reviewed_records,
    ApiErrorId,
    make_managing_partner_headers,
    make_attorney_headers,
    create_demand_letter_payload,
    api_client,
)


# =============================================================================
# Instance: state_beats_segregation_on_already_sent_demand
# =============================================================================


class TestStateBeatsSegregationOnAlreadySentDemand:
    """A second send attempt on an already-SENT DemandLetter, by the same user
    who drafted it, triggers BOTH ERR_INVALID_STATE (priority 5) and
    ERR_SEGREGATION_OF_DUTIES (priority 8). PRD §2.9 pins state above
    business-safety, so the server must report ERR_INVALID_STATE."""

    def _send_letter_then_attempt_second_send_as_drafter(self):
        """Active CA case, REVIEWED records, DemandLetter drafted by
        'drafter-5a' and SENT by 'partner-5a'. The trigger is a SECOND send
        invoked by 'drafter-5a' (same user-id as the drafter), targeting the
        already-SENT letter. That violates BOTH ERR_INVALID_STATE (status !=
        DRAFT) AND ERR_SEGREGATION_OF_DUTIES (X-User-ID == drafted_by_user_id).
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-5a")
        send_demand_letter(dl["id"], partner_user_id="partner-5a")
        # Second send by the drafter (acting as ManagingPartner with the
        # drafter's X-User-ID). Both ERR_INVALID_STATE and ERR_SEGREGATION_OF_DUTIES
        # would apply; PRD §2.9 priority order pins ERR_INVALID_STATE.
        return dl["id"]

    def test_second_send_attempt_by_drafter_returns_invalid_state(self, api):
        """PRD §2.9: "After existence comes state: the direct state precondition
        on the target resource (`ERR_INVALID_STATE`) is checked before any
        cross-entity state precondition (`ERR_CROSS_ENTITY_STATE`).
        Business-safety and compliance checks follow — the statute-of-limitations
        guard (`ERR_STATUTE_EXPIRED`), the demand-letter segregation-of-duties
        guard (`ERR_SEGREGATION_OF_DUTIES`), and the retainer-signed
        precondition (`ERR_RETAINER_MISSING`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_already_sent_demand
        """
        dl_id = self._send_letter_then_attempt_second_send_as_drafter()
        # ManagingPartner with the drafter's X-User-ID.
        headers = make_managing_partner_headers("drafter-5a")
        res = api.send_demand_letter(dl_id, headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_second_send_attempt_priority_returns_409_not_422(self, api):
        """PRD §2.9: "After existence comes state: the direct state precondition
        on the target resource (`ERR_INVALID_STATE`) is checked before any
        cross-entity state precondition (`ERR_CROSS_ENTITY_STATE`).
        Business-safety and compliance checks follow — the statute-of-limitations
        guard (`ERR_STATUTE_EXPIRED`), the demand-letter segregation-of-duties
        guard (`ERR_SEGREGATION_OF_DUTIES`), and the retainer-signed
        precondition (`ERR_RETAINER_MISSING`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_already_sent_demand
        """
        dl_id = self._send_letter_then_attempt_second_send_as_drafter()
        headers = make_managing_partner_headers("drafter-5a")
        res = api.send_demand_letter(dl_id, headers)
        assert res.status_code == 409, (
            f"ERR_INVALID_STATE (409) must precede ERR_SEGREGATION_OF_DUTIES (422), "
            f"got HTTP {res.status_code}"
        )


# =============================================================================
# Instance: statute_expired_beats_demand_prerequisites_on_draft
# =============================================================================


class TestStatuteExpiredBeatsDemandPrerequisitesOnDraft:
    """A DemandLetter draft attempted on a case whose SOL has expired AND
    whose case has no REVIEWED records triggers both ERR_STATUTE_EXPIRED
    (priority 7, business-safety) and ERR_DEMAND_PREREQUISITES_NOT_MET
    (priority 11, business-referential). PRD §2.9 pins business-safety above
    business-referential, so the server must report ERR_STATUTE_EXPIRED."""

    def _build_active_case_then_expire_sol(self):
        """CA case (SOL = 2026-01-15) activated at clock 2025-01-01; clock
        then advanced to 2026-02-01 (past SOL). No MedicalRecordsRequest is
        ever created, so the demand-prerequisites check would also fire."""
        set_clock("2025-01-01T00:00:00Z")
        c = register_client(email="pri7@example.com")
        sign_retainer(c["id"])
        case = create_case(c["id"], accident_date="2024-01-15", jurisdiction="CA")
        activate_case(case["id"])
        # Advance clock past SOL.
        set_clock("2026-02-01T00:00:00Z")
        return case["id"]

    def test_demand_draft_on_expired_sol_no_records_returns_statute_expired(self, api):
        """PRD §2.9: "Business-safety and compliance checks follow — the
        statute-of-limitations guard (`ERR_STATUTE_EXPIRED`), the demand-letter
        segregation-of-duties guard (`ERR_SEGREGATION_OF_DUTIES`), and the
        retainer-signed precondition (`ERR_RETAINER_MISSING`). Business-referential
        checks then run: the medical-records prerequisite for including a
        medical bill (`ERR_MISSING_MEDICAL_RECORDS`), the demand-letter
        prerequisites (`ERR_DEMAND_PREREQUISITES_NOT_MET`), and the
        disputed-lien guard on accept (`ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT`)."

        Design: Difficulty/priority_pair_validation_conflict/statute_expired_beats_demand_prerequisites_on_draft
        """
        case_id = self._build_active_case_then_expire_sol()
        headers = make_attorney_headers("drafter-5b")
        res = api_client.create_demand_letter(
            create_demand_letter_payload(case_id, pain_multiplier=1.5),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_STATUTE_EXPIRED.value)

    def test_demand_draft_on_expired_sol_returns_422_not_demand_prereq(self, api):
        """PRD §2.9: "Business-safety and compliance checks follow — the
        statute-of-limitations guard (`ERR_STATUTE_EXPIRED`), the demand-letter
        segregation-of-duties guard (`ERR_SEGREGATION_OF_DUTIES`), and the
        retainer-signed precondition (`ERR_RETAINER_MISSING`). Business-referential
        checks then run: the medical-records prerequisite for including a
        medical bill (`ERR_MISSING_MEDICAL_RECORDS`), the demand-letter
        prerequisites (`ERR_DEMAND_PREREQUISITES_NOT_MET`), and the
        disputed-lien guard on accept (`ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT`)."

        Design: Difficulty/priority_pair_validation_conflict/statute_expired_beats_demand_prerequisites_on_draft
        """
        case_id = self._build_active_case_then_expire_sol()
        headers = make_attorney_headers("drafter-5c")
        res = api_client.create_demand_letter(
            create_demand_letter_payload(case_id, pain_multiplier=1.5),
            headers,
        )
        # Both ERR_STATUTE_EXPIRED and ERR_DEMAND_PREREQUISITES_NOT_MET are 422,
        # so the discriminator is the error_id, not the HTTP status.
        body = validate_error(res, ApiErrorId.ERR_STATUTE_EXPIRED.value)
        assert body["error_id"] == "ERR_STATUTE_EXPIRED"
