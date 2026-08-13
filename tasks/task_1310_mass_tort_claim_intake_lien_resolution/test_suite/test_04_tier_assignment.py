"""Tier assignment: OCC, severity window boundaries, matrix referential checks,
input-set filtering, and immediate derived-field consistency."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_claim_invariants,
    create_program, create_published_matrix, create_claimant,
    create_injury_verified_claim, create_eligibility_passed_claim,
    create_tier_assigned_claim, get_claim_version,
    create_medical_record_payload, create_tier_matrix_payload,
    TEST_USERS,
)

RECORDS = TEST_USERS["records_analyst_headers"]


class TestTierAssignmentOcc:
    def test_stale_expected_version_rejected_with_412(self, api, program_admin_headers):
        """PRD §2.6: "A tier-assignment request must carry `expected_claim_version`, a non-optional input holding the value of the claim's `version` the client last observed. If the claim's current `version` does not match — for example because another writer has filed an appeal against the claim, which mutates the claim and advances its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/assign-tier_occ_stale_version_returns_412
        """
        program = create_program(program_code="MT-OCC1")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Pat", ssn_last4="3333")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        cid = claim["id"]
        v_stale = get_claim_version(pid, cid)
        # Another write bumps the claim version after the client captured v_stale.
        validate_success(api.create_medical_record(
            pid, cid,
            create_medical_record_payload(provider_name="Z", record_type="PHARMACY",
                                          severity_score=55, confirms_qualifying_injury=False),
            RECORDS,
        ), expected_status=201)
        resp = api.assign_tier(pid, cid, {"tier_matrix_id": matrix["id"], "expected_claim_version": v_stale - 1},
                               program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_matching_expected_version_accepted(self, api, program_admin_headers):
        """PRD §2.6: "A tier-assignment request must carry `expected_claim_version`, a non-optional input holding the value of the claim's `version` the client last observed."

        Design: Corner/endpoints/assign-tier_occ_stale_version_returns_412
        """
        program = create_program(program_code="MT-OCC1B")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Pat B", ssn_last4="3334")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        cid = claim["id"]
        version = get_claim_version(pid, cid)
        resp = api.assign_tier(pid, cid, {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               program_admin_headers)
        data = validate_success(resp)
        assert data["status"] == "TIER_ASSIGNED"


class TestValidationPriorityStaleBeatsState:
    def test_stale_version_beats_claim_invalid_state(self, api, program_admin_headers, records_analyst_headers):
        """PRD §2.6: "The version check on both endpoints is performed before any business-state validation on the same request, so a stale request is reported as stale even if the claim has also moved out of the required state."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_claim_invalid_state
        """
        program = create_program(program_code="MT-P1")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Jack", ssn_last4="8888")
        claim = create_eligibility_passed_claim(pid, claimant["id"])
        cid = claim["id"]
        # One upload moves the claim to RECORDS_PENDING (not INJURY_VERIFIED, so the
        # business-state check would also fail on this call).
        validate_success(api.create_medical_record(
            pid, cid, create_medical_record_payload(provider_name="X", record_type="DIAGNOSTIC",
                                                    severity_score=70, confirms_qualifying_injury=True),
            records_analyst_headers,
        ), expected_status=201)
        v_stale = get_claim_version(pid, cid)
        validate_success(api.create_medical_record(
            pid, cid, create_medical_record_payload(provider_name="Y", record_type="TREATMENT",
                                                    severity_score=65, confirms_qualifying_injury=False),
            records_analyst_headers,
        ), expected_status=201)
        resp = api.assign_tier(pid, cid, {"tier_matrix_id": matrix["id"], "expected_claim_version": v_stale - 1},
                               program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_current_version_on_wrong_state_reports_state_error(self, api, program_admin_headers, records_analyst_headers):
        """PRD §3.4: "The claim must currently be `INJURY_VERIFIED` (`ERR_CLAIM_INVALID_STATE`)."
        PRD §2.6: "The version check on both endpoints is performed before any business-state validation on the same request, so a stale request is reported as stale even if the claim has also moved out of the required state."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_claim_invalid_state
        """
        program = create_program(program_code="MT-P1B")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Jack B", ssn_last4="8889")
        claim = create_eligibility_passed_claim(pid, claimant["id"])
        cid = claim["id"]
        # Claim is in ELIGIBILITY_PASSED (not INJURY_VERIFIED) and the version matches,
        # so the state check is what must fire.
        version = get_claim_version(pid, cid)
        resp = api.assign_tier(pid, cid, {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)


class TestSeverityBoundary:
    def test_severity_equal_to_max_matches_inclusive(self, api, program_admin_headers):
        """PRD §3.4: "Finally, the claim's severity score — defined as the maximum `severity_score` across the claim's `ACCEPTED` medical records — must fall within the matrix row's severity window, bounded by `severity_score_min` and `severity_score_max` inclusively on both ends, otherwise `ERR_SEVERITY_OUT_OF_RANGE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/severity_score_inclusive_max_boundary
        """
        program = create_program(program_code="MT-BND1")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=50, severity_score_max=75,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Leo", ssn_last4="1212")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(75, 65))
        version = get_claim_version(pid, claim["id"])
        resp = api.assign_tier(pid, claim["id"], {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               program_admin_headers)
        data = validate_success(resp)
        assert data["status"] == "TIER_ASSIGNED", (
            f"severity 75 == severity_score_max must match (inclusive), got status {data['status']}"
        )

    def test_severity_below_min_rejected(self, api, program_admin_headers):
        """PRD §3.4: "Finally, the claim's severity score — defined as the maximum `severity_score` across the claim's `ACCEPTED` medical records — must fall within the matrix row's severity window, bounded by `severity_score_min` and `severity_score_max` inclusively on both ends, otherwise `ERR_SEVERITY_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/validations/severity_below_min_returns_out_of_range
        """
        program = create_program(program_code="MT-SOOR")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=50, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Hank", ssn_last4="2525")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(30, 25))
        version = get_claim_version(pid, claim["id"])
        resp = api.assign_tier(pid, claim["id"], {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEVERITY_OUT_OF_RANGE)


class TestMatrixReferentialChecks:
    def test_category_mismatch_rejected(self, api, program_admin_headers):
        """PRD §3.4: "The claimant's `injury_category` must equal the matrix row's `injury_category`, otherwise `ERR_MATRIX_CATEGORY_MISMATCH` (HTTP 422)."

        Design: Corner/validations/matrix_category_mismatch
        """
        program = create_program(program_code="MT-CAT")
        pid = program["id"]
        matrix = create_published_matrix(pid, injury_category="QUALIFYING_CAT_A",
                                         severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Ilse", ssn_last4="2626",
                                   injury_category="QUALIFYING_CAT_B")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        version = get_claim_version(pid, claim["id"])
        resp = api.assign_tier(pid, claim["id"], {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_MATRIX_CATEGORY_MISMATCH)

    def test_draft_matrix_not_assignable(self, api, program_admin_headers):
        """PRD §3.4: "The supplied `tier_matrix_id` must belong to this program and itself be in `PUBLISHED` state, otherwise `ERR_MATRIX_NOT_PUBLISHED` (HTTP 409)."
        PRD §3.1: "A new row starts in `DRAFT` state and is not assignable."

        Design: Difficulty/boundary_precision_check/severity_score_inclusive_max_boundary
        """
        program = create_program(program_code="MT-DRAFT")
        pid = program["id"]
        # Publish one row so the program-level "at least one PUBLISHED row"
        # precondition (ERR_NO_PUBLISHED_MATRIX, listed first in PRD §3.4) is
        # satisfied and the supplied-row check is the one under test. The
        # publish cascade only supersedes PUBLISHED rows (PRD §3.1), so the
        # draft row below stays DRAFT.
        create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                base_award_cents=5_000_000)
        draft = get_success_data(api.create_tier_matrix(
            pid, create_tier_matrix_payload(severity_score_min=0, severity_score_max=100,
                                            base_award_cents=5_000_000),
            program_admin_headers,
        ))
        claimant = create_claimant(pid, full_name="Draft User", ssn_last4="7777")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        version = get_claim_version(pid, claim["id"])
        resp = api.assign_tier(pid, claim["id"], {"tier_matrix_id": draft["id"], "expected_claim_version": version},
                               program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_MATRIX_NOT_PUBLISHED)


class TestSeverityInputSetFiltering:
    def test_max_severity_uses_accepted_records_only(self, api, program_admin_headers, records_analyst_headers):
        """PRD §3.4: "On success, the tier-assignment calculation sets `gross_award_cents` to the matched matrix row's `base_award_cents`, using only the claim's accepted records and the requested matrix row."

        Design: Corner/calculations/tier_assignment_uses_max_severity_only_accepted_records
        """
        program = create_program(program_code="MT-FILT")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=50, severity_score_max=75,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Belle", ssn_last4="1919")
        claim, _records = create_injury_verified_claim(pid, claimant["id"], severities=(50, 60))
        cid = claim["id"]
        # A PENDING_REVIEW record with severity 99 must NOT enter the max computation;
        # max ACCEPTED severity is 60, inside [50,75].
        validate_success(api.create_medical_record(
            pid, cid, create_medical_record_payload(provider_name="Z", record_type="PHARMACY",
                                                    severity_score=99, confirms_qualifying_injury=False),
            records_analyst_headers,
        ), expected_status=201)
        version = get_claim_version(pid, cid)
        resp = api.assign_tier(pid, cid, {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               program_admin_headers)
        data = validate_success(resp)
        assert data["status"] == "TIER_ASSIGNED", (
            f"max ACCEPTED severity 60 is inside [50,75]; got status {data['status']}"
        )
        assert data["gross_award_cents"] == 5_000_000


class TestImmediateConsistency:
    def test_assign_tier_response_carries_recomputed_fields(self, api, program_admin_headers):
        """PRD §3.4: "On success, the tier-assignment calculation sets `gross_award_cents` to the matched matrix row's `base_award_cents`, using only the claim's accepted records and the requested matrix row. The attorney fee calculation then runs (§3.7), `net_award_cents` is recomputed as the gross award minus total liens minus attorney fee with a floor of zero, and the claim's `lien_posture` flips to `IDENTIFYING`."

        Design: Corner/consistency_model/immediate_consistency_derived_fields_in_same_response
        """
        ctx = create_tier_assigned_claim(base_award_cents=5_000_000, represented_by_counsel=True,
                                         severities=(70, 65))
        claim = ctx["claim"]
        assert claim["status"] == "TIER_ASSIGNED"
        assert claim["gross_award_cents"] == 5_000_000
        assert claim["attorney_fee_cents"] == 2_000_000, (
            f"fee = round(5000000*0.4) - 0 = 2000000, got {claim['attorney_fee_cents']}"
        )
        assert claim["net_award_cents"] == 3_000_000
        assert claim["lien_posture"] == "IDENTIFYING"
        assert_claim_invariants(claim)

    def test_assign_tier_increments_claim_version(self, api, program_admin_headers):
        """PRD §2.4: "A `Claim`'s `version` advances not only on direct claim transitions but also on events that conceptually mutate the claim's posture: filing an appeal, upholding, denying, or withdrawing an appeal, resolving a lien, and preparing disbursement each increment the claim's `version` by 1, in addition to the tier-assignment transition itself."

        Design: Corner/consistency_model/immediate_consistency_derived_fields_in_same_response
        """
        program = create_program(program_code="MT-IMM2B")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Ursula B", ssn_last4="3839",
                                   represented_by_counsel=True)
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        before = get_claim_version(pid, claim["id"])
        resp = api.assign_tier(pid, claim["id"], {"tier_matrix_id": matrix["id"], "expected_claim_version": before},
                               program_admin_headers)
        data = validate_success(resp)
        assert data["version"] == before + 1, (
            f"tier assignment must advance claim version by 1: {before} -> {data['version']}"
        )
