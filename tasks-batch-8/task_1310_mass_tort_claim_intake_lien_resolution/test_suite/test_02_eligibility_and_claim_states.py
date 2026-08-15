"""Eligibility screening rules, claim initial state, invalid transitions, withdrawal."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_claim,
    create_program, create_claimant, create_submitted_claim,
    create_eligibility_passed_claim, create_tier_assigned_claim,
    create_claim_payload,
    make_claimant_headers,
)


class TestClaimInitialState:
    def test_new_claim_starts_submitted(self, api, intake_specialist_headers):
        """PRD §3.2: "Filing a claim for a registered claimant produces a `Claim` whose `status` is `SUBMITTED`, with a server-minted human-readable `claim_number` of the form `CLM-####`."

        Design: Corner/state_machines/claim_initial_state_submitted
        """
        program = create_program(program_code="MT-INIT")
        claimant = create_claimant(program["id"], full_name="Walt", ssn_last4="1414")
        resp = api.create_claim(program["id"], create_claim_payload(claimant["id"]), intake_specialist_headers)
        data = validate_success(resp, expected_status=201)
        assert_claim(data)
        assert data["status"] == "SUBMITTED", f"New claim must start SUBMITTED, got {data['status']}"


class TestEligibilityScreening:
    def test_diagnosis_before_exposure_start_rejected(self, api, intake_specialist_headers):
        """PRD §3.2: "the claimant's dates must satisfy the ordering in which `date_of_exposure_start` is on or before `date_of_diagnosis`, which is on or before `date_of_exposure_end`, with violations rejected as `ERR_ELIGIBILITY_DATE_ORDER` (HTTP 422)"

        Design: Corner/validations/eligibility_date_order_violation
        """
        program = create_program(program_code="MT-DT")
        claimant = create_claimant(
            program["id"], full_name="Fay", ssn_last4="2323",
            date_of_exposure_start="2020-01-01", date_of_exposure_end="2022-12-31",
            date_of_diagnosis="2019-06-15",
        )
        claim = create_submitted_claim(program["id"], claimant["id"])
        resp = api.screen_eligibility(program["id"], claim["id"], intake_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_DATE_ORDER)

    def test_non_qualifying_injury_rejected(self, api, intake_specialist_headers):
        """PRD §3.2: "an `injury_category` of `NON_QUALIFYING` is rejected as `ERR_INELIGIBLE_INJURY` (HTTP 422)"

        Design: Corner/validations/non_qualifying_injury_returns_ineligible
        """
        program = create_program(program_code="MT-NQ")
        claimant = create_claimant(
            program["id"], full_name="Gus", ssn_last4="2424", injury_category="NON_QUALIFYING",
        )
        claim = create_submitted_claim(program["id"], claimant["id"])
        resp = api.screen_eligibility(program["id"], claim["id"], intake_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_INELIGIBLE_INJURY)


class TestDuplicateActiveClaimOverlap:
    def test_second_active_claim_screen_rejected(self, api, intake_specialist_headers):
        """PRD §3.2: "if any other claim exists for the same claimant in a status other than `DENIED`, `WITHDRAWN`, or `CLOSED`, the screen is rejected as `ERR_DUPLICATE_ACTIVE_CLAIM` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/active_claim_lifecycle_overlap_on_claimant
        """
        program = create_program(program_code="MT-OVL2")
        claimant = create_claimant(program["id"], full_name="Paula", ssn_last4="6767")
        claim1 = create_submitted_claim(program["id"], claimant["id"])
        resp = api.screen_eligibility(program["id"], claim1["id"], intake_specialist_headers)
        validate_success(resp)
        claim2 = create_submitted_claim(program["id"], claimant["id"])
        resp2 = api.screen_eligibility(program["id"], claim2["id"], intake_specialist_headers)
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_ACTIVE_CLAIM)

    def test_screen_allowed_after_first_claim_withdrawn(self, api, intake_specialist_headers):
        """PRD §3.2: "if any other claim exists for the same claimant in a status other than `DENIED`, `WITHDRAWN`, or `CLOSED`, the screen is rejected as `ERR_DUPLICATE_ACTIVE_CLAIM` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/active_claim_lifecycle_overlap_on_claimant
        """
        program = create_program(program_code="MT-OVL2B")
        claimant = create_claimant(program["id"], full_name="Paula B", ssn_last4="6768")
        claim1 = create_submitted_claim(program["id"], claimant["id"])
        # Withdraw claim 1: its lifecycle window closes (terminal state), so the
        # second claim's screen must not trip the duplicate-active rule.
        resp_w = api.withdraw_claim(program["id"], claim1["id"], make_claimant_headers(claimant["id"]))
        validate_success(resp_w)
        claim2 = create_submitted_claim(program["id"], claimant["id"])
        resp2 = api.screen_eligibility(program["id"], claim2["id"], intake_specialist_headers)
        data = validate_success(resp2)
        assert data["status"] == "ELIGIBILITY_PASSED"
        assert data["eligibility_status"] == "PASSED"


class TestDenyAndWithdraw:
    def test_deny_from_eligibility_passed_returns_invalid_state(self, api, intake_specialist_headers):
        """PRD §3.2: "denying a claim that is not `SUBMITTED` is again `ERR_CLAIM_INVALID_STATE`."

        Design: Corner/state_machines/deny_from_eligibility_passed_returns_invalid_state
        """
        program = create_program(program_code="MT-IVT")
        claimant = create_claimant(program["id"], full_name="Xena", ssn_last4="1515")
        claim = create_eligibility_passed_claim(program["id"], claimant["id"])
        resp = api.deny_claim(program["id"], claim["id"], {"denied_reason": "Too late"}, intake_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)

    def test_withdraw_from_tier_assigned_returns_not_withdrawable(self, api):
        """PRD §3.2: "A claimant acting through `ClaimantRole` may instead withdraw the claim, moving it to the terminal `WITHDRAWN` status, but only while the claim is in `SUBMITTED`, `ELIGIBILITY_PASSED`, `RECORDS_PENDING`, or `INJURY_VERIFIED`; a claim that has progressed beyond `INJURY_VERIFIED` is rejected as `ERR_CLAIM_NOT_WITHDRAWABLE` (HTTP 409)."

        Design: Corner/state_machines/withdraw_from_tier_assigned_returns_not_withdrawable
        """
        ctx = create_tier_assigned_claim()
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        resp = api.withdraw_claim(pid, cid, make_claimant_headers(ctx["claimant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_WITHDRAWABLE)
