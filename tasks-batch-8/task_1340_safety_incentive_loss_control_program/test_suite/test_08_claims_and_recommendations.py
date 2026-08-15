"""Claims and carrier loss-control recommendations: the ERA medical-only
factor, denial terminality, the carrier rejection loop, the verified-evidence
gate, and the program close-out guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_claim_record,
    assert_claim_record,
    assert_recommendation,
    create_active_program,
    create_claim_record,
    create_hazard_record,
    create_recommendation_record,
    list_awards,
    make_safety_manager_headers,
    set_clock,
    setup_hazard_with_controls,
    setup_roster,
    get_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]
CARRIER = TEST_USERS["carrier_consultant_headers"]


class TestClaimEffectiveIncurred:
    def test_emr_medical_only_era_factor(self, api):
        """PRD §3.6: "The system immediately derives `effective_incurred_cents`:
        under the experience-rating ERA rule, a `MEDICAL_ONLY` claim counts at
        thirty percent of its incurred amount, rounded half-up to the cent,
        while an `INDEMNITY` claim counts in full."

        Design: Corner/calculations/emr_medical_only_era_factor
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster()
        manager = employees["Marta M"]

        medical = create_claim_record(program["id"], manager["id"],
                                      occurred_on="2026-03-01",
                                      kind="MEDICAL_ONLY",
                                      incurred_cents=800_000)
        assert_claim_record(medical)
        assert medical["effective_incurred_cents"] == 240_000, \
            "MEDICAL_ONLY counts at thirty percent: 0.3 * 800000"

        indemnity = create_claim_record(program["id"], manager["id"],
                                        occurred_on="2026-03-02",
                                        kind="INDEMNITY",
                                        incurred_cents=100_001)
        assert indemnity["effective_incurred_cents"] == 100_001, \
            "INDEMNITY passes through unscaled"


class TestClaimDenialTerminal:
    def test_deny_claim_then_accept_returns_invalid_state(self, api):
        """PRD §3.6: "From there the `SafetyManager` may accept it — moving to
        `ACCEPTED`, optionally replacing `incurred_cents` in the same call and
        recomputing the effective amount — or deny it, which requires a
        `reason` (`ERR_INVALID_REQUEST` when missing) and lands in `DENIED`."
        PRD §2.6: "`ERR_INVALID_STATE` as the generic fallback for any other
        impermissible transition."

        Design: Corner/state_machines/deny_claim_then_accept_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        claim = create_claim_record(program["id"], manager["id"],
                                    occurred_on="2026-03-01", kind="INDEMNITY",
                                    incurred_cents=100_000)
        assert claim["status"] == "REPORTED"

        denied = validate_success(api.deny_claim(
            claim["id"], {"reason": "not work related"},
            make_safety_manager_headers(manager["id"])))
        assert denied["status"] == "DENIED"

        resp = api.accept_claim(claim["id"], {},
                                make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert validate_success(api.get_claim(claim["id"], ADMIN))["status"] == \
            "DENIED", "acceptance is defined only from REPORTED"


class TestCarrierRejectionLoop:
    def test_lcr_carrier_rejection_loop(self, api):
        """PRD §3.6: "Responding moves the recommendation to
        `RESPONSE_SUBMITTED`, and is permitted from `ISSUED`, from `OVERDUE`,
        and from `CARRIER_REJECTED` — the carrier rejection loop lets the
        employer try again. The `CarrierConsultant` then adjudicates: an
        `ACCEPT` outcome closes the recommendation at `CLOSED_ACCEPTED`; a
        `REJECT` outcome requires a `review_note` (`ERR_INVALID_REQUEST` when
        missing) and moves it to `CARRIER_REJECTED`. Either way, `reviewed_by`
        records the consultant's identity."

        Design: Corner/state_machines/lcr_carrier_rejection_loop
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        recommendation = create_recommendation_record(program["id"])
        assert_recommendation(recommendation)
        assert recommendation["status"] == "ISSUED"

        first_response = validate_success(api.respond_recommendation(
            recommendation["id"], {"response_text": "Guards ordered"},
            make_safety_manager_headers(manager["id"])))
        assert first_response["status"] == "RESPONSE_SUBMITTED"
        assert first_response["responded_by"] == manager["id"]

        rejected = validate_success(api.review_recommendation_response(
            recommendation["id"],
            {"outcome": "REJECT",
             "review_note": "PO insufficient; need install proof"},
            CARRIER))
        assert rejected["status"] == "CARRIER_REJECTED"
        assert rejected["reviewed_by"] == "test-carrier-consultant-1", \
            "reviewed_by records the adjudicating consultant's identity"

        second_response = validate_success(api.respond_recommendation(
            recommendation["id"], {"response_text": "Install photos attached"},
            make_safety_manager_headers(manager["id"])))
        assert second_response["status"] == "RESPONSE_SUBMITTED", \
            "the employer may respond again after a carrier rejection"
        assert second_response["responded_by"] == manager["id"]

        accepted = validate_success(api.review_recommendation_response(
            recommendation["id"], {"outcome": "ACCEPT"}, CARRIER))
        assert accepted["status"] == "CLOSED_ACCEPTED"
        assert accepted["reviewed_by"] == "test-carrier-consultant-1"


class TestRecommendationEvidenceGate:
    def test_lcr_evidence_control_must_be_verified(self, api):
        """PRD §3.6: "a response carries `response_text`, may cite an
        `evidence_control_id` pointing at a completed control as proof — which
        must reference a control in `VERIFIED`, else
        `ERR_CONTROL_NOT_VERIFIED`"

        Design: Corner/validations/lcr_evidence_control_must_be_verified
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        _hazard, controls = setup_hazard_with_controls(
            program["id"], ann["id"], manager["id"], control_count=1,
            implementer_id=ann["id"], description="Noise")
        assert controls[0]["status"] == "PLANNED"
        recommendation = create_recommendation_record(
            program["id"], description="Reduce press noise")

        resp = api.respond_recommendation(
            recommendation["id"],
            {"response_text": "Enclosure planned",
             "evidence_control_id": controls[0]["id"]},
            make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTROL_NOT_VERIFIED)
        unchanged = validate_success(
            api.get_recommendation(recommendation["id"], ADMIN))
        assert unchanged["status"] == "ISSUED", \
            "the rejected response is not recorded"


class TestProgramCloseGuards:
    def test_close_blocked_by_open_hazard(self, api):
        """PRD §3.8: "Any hazard still in `OPEN`, `ASSESSED`,
        `CONTROLS_PLANNED`, `IN_PROGRESS`, or `PENDING_VERIFICATION` blocks the
        close with `ERR_OPEN_HAZARDS_REMAIN`"

        Design: Corner/validations/close_blocked_by_open_hazard
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        manager = employees["Marta M"]
        hazard = create_hazard_record(program["id"], manager["id"],
                                      identified_by=employees["Ann A"]["id"],
                                      description="Unassessed")
        assert hazard["status"] == "OPEN"

        resp = api.close_program(program["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_HAZARDS_REMAIN)
        assert get_program(program["id"])["status"] == "ACTIVE", \
            "the rejected close leaves the program ACTIVE"
        assert list_awards(program_id=program["id"]) == [], \
            "no awards are computed by a rejected close"

    def test_close_blocked_by_open_recommendation(self, api):
        """PRD §3.8: "any recommendation still in `ISSUED`, `OVERDUE`,
        `RESPONSE_SUBMITTED`, or `CARRIER_REJECTED` blocks it with
        `ERR_OPEN_RECOMMENDATIONS_REMAIN`"

        Design: Corner/validations/close_blocked_by_open_recommendation
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        recommendation = create_recommendation_record(
            program["id"], priority="MEDIUM", description="Refresh JHA library",
            due_date="2026-12-01T00:00:00Z")
        assert recommendation["status"] == "ISSUED"

        resp = api.close_program(program["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_RECOMMENDATIONS_REMAIN)
        assert get_program(program["id"])["status"] == "ACTIVE"
