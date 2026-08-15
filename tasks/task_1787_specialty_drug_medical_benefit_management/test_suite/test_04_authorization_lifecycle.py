"""Prior-authorization submission gates, approval lifecycle, and validity-window
overlap semantics (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    approve_auth,
    assert_prior_authorization,
    create_drug,
    create_policy,
    create_provider,
    get_auth,
    make_provider_rep_headers,
    setup_approved_scenario,
    setup_drug_with_policy,
    submit_auth,
    TEST_USERS,
    validate_error,
    validate_success,
)

MPO = TEST_USERS["mpo_headers"]


class TestSubmissionGates:
    def test_past_start_and_missing_weight_rejected(self, api):
        """PRD §3.4: "a `requested_start_date`, which must not be earlier than the current
        clock date or submission fails with `ERR_START_DATE_IN_PAST`".
        PRD §3.4: "a weight-based drug requires `weight_kg`, while any other drug requires
        `requested_dose_mg`, and the missing input fails with `ERR_MISSING_WEIGHT_OR_DOSE`".

        Design: Corner/entities/auth_submission_guards
        """
        drug_wb = create_drug(
            j_code="J8100",
            drug_name="WBDrug",
            weight_based_dosing=True,
            mg_per_kg=2.5,
        )
        drug_nd = create_drug(j_code="J8101", drug_name="NDDrug")
        provider = create_provider(name="Guard Provider")

        # Start date before the startup clock date 2026-08-01 (PRD §2.4).
        resp = api.create_prior_authorization(
            {
                "drug_id": drug_nd["id"],
                "member_id": "MEM-G1",
                "diagnosis_code": "C50",
                "requested_start_date": "2026-07-15",
                "requested_dose_mg": 100,
            },
            make_provider_rep_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_START_DATE_IN_PAST, 422)

        # Weight-based drug without weight_kg.
        resp = api.create_prior_authorization(
            {
                "drug_id": drug_wb["id"],
                "member_id": "MEM-G2",
                "diagnosis_code": "C50",
                "requested_start_date": "2026-08-01",
            },
            make_provider_rep_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_WEIGHT_OR_DOSE, 422)

    def test_dose_equal_to_cap_accepted(self, api):
        """PRD §3.1: "`max_single_dose_mg` is an inclusive cap enforced twice — at
        authorization submission against `requested_dose_mg`, and at approval against the
        computed dose: a dose exactly equal to the cap is allowed, while one milligram
        above it is rejected with `ERR_DOSE_EXCEEDS_MAX`."

        Design: Difficulty/boundary_precision_check/dose_cap_inclusive_boundary
        """
        backbone = setup_drug_with_policy(
            drug_overrides={
                "j_code": "J3100",
                "drug_name": "CapDrug",
                "max_single_dose_mg": 500,
            },
            with_rate=False,
        )
        provider = create_provider(name="Cap Provider")
        auth = submit_auth(
            backbone["drug"]["id"],
            provider["id"],
            "MEM-11",
            requested_dose_mg=500,
        )
        assert auth["status"] == "SUBMITTED", "dose == cap is allowed at submission"

    def test_dose_one_mg_above_cap_rejected(self, api):
        """PRD §3.1: "a dose exactly equal to the cap is allowed, while one milligram
        above it is rejected with `ERR_DOSE_EXCEEDS_MAX`."

        Design: Difficulty/boundary_precision_check/dose_cap_inclusive_boundary
        """
        backbone = setup_drug_with_policy(
            drug_overrides={
                "j_code": "J3101",
                "drug_name": "CapDrug2",
                "max_single_dose_mg": 500,
            },
            with_rate=False,
        )
        provider = create_provider(name="Cap Provider 2")
        resp = api.create_prior_authorization(
            {
                "drug_id": backbone["drug"]["id"],
                "member_id": "MEM-12",
                "diagnosis_code": "C50",
                "requested_start_date": "2026-08-01",
                "requested_dose_mg": 501,
            },
            make_provider_rep_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOSE_EXCEEDS_MAX, 422)


class TestComputedFieldsAtCreation:
    def test_auth_create_leaves_computed_fields_unset(self, api):
        """PRD §3.4: "The new authorization lands in `SUBMITTED`, stamped with the
        creating representative's account as `provider_account_id`."
        PRD §3.4: "`approved_dose_mg` — null until this point" (approval); "The governing
        policy's identity is pinned onto the authorization as `policy_id` and
        `policy_version_no` — both null until approval — `administrations_used` starts at
        zero".

        Design: Corner/entities/auth_computed_fields_input_ignored
        """
        backbone = setup_drug_with_policy(
            drug_overrides={"j_code": "J4200", "drug_name": "CompDrug"}, with_rate=False
        )
        provider = create_provider(name="Comp Provider")
        auth = submit_auth(
            backbone["drug"]["id"], provider["id"], "MEM-D2", requested_dose_mg=100
        )
        assert_prior_authorization(auth)
        assert auth["status"] == "SUBMITTED"
        assert auth["administrations_used"] == 0
        assert auth.get("approved_dose_mg") is None
        assert auth.get("validity_start") is None
        assert auth.get("validity_end") is None
        assert auth.get("policy_id") is None
        assert auth.get("policy_version_no") is None
        assert auth.get("denial_reason") is None
        assert auth["provider_account_id"] == provider["id"]


class TestApprovalTransitions:
    def test_second_approve_rejected(self, api):
        """PRD §3.4: "The authorization must be `SUBMITTED`, otherwise
        `ERR_AUTH_NOT_PENDING`."

        Design: Corner/state_machines/auth_approve_twice_rejected
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J4400", "drug_name": "TwiceDrug"},
            member_id="MEM-T2",
            with_rate=False,
        )
        auth = scenario["auth"]
        assert auth["approved_dose_mg"] == 100

        resp = api.approve_auth(auth["id"], {"max_administrations": 4}, MPO)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_PENDING, 409)

        after = get_auth(auth["id"])
        assert after["status"] == "APPROVED"
        assert after["administrations_used"] == 0
        assert after["approved_dose_mg"] == 100

    def test_cancel_terminal_denied_auth_rejected(self, api):
        """PRD §3.4: "Cancellation is legal from `SUBMITTED`, `APPROVED`, or `SUSPENDED`;
        attempted from a terminal authorization it fails with
        `ERR_AUTH_NOT_CANCELLABLE`."
        PRD §3.4: "the payload's `reason` is recorded as `denial_reason` — null at every
        other time — and the authorization becomes `DENIED`, terminal."

        Design: Corner/state_machines/auth_terminal_lockdown_cancel_denied
        """
        drug = create_drug(j_code="J4300", drug_name="TermDrug")
        provider = create_provider(name="Term Provider")
        auth = submit_auth(drug["id"], provider["id"], "MEM-T1", requested_dose_mg=100)
        denied = validate_success(
            api.deny_auth(auth["id"], {"reason": "not medically necessary"}, MPO)
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "not medically necessary"

        resp = api.cancel_auth(auth["id"], MPO)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_CANCELLABLE, 409)

        after = get_auth(auth["id"])
        assert after["status"] == "DENIED"
        assert after["denial_reason"] == "not medically necessary"

    def test_reinstate_approved_auth_rejected(self, api):
        """PRD §3.4: "Reinstating requires `SUSPENDED` — otherwise
        `ERR_AUTH_NOT_SUSPENDED` — and returns the authorization to `APPROVED`".

        Design: Corner/state_machines/reinstate_approved_auth_rejected
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J4950", "drug_name": "ReinDrug"},
            member_id="MEM-T6",
            with_rate=False,
        )
        resp = api.reinstate_auth(scenario["auth"]["id"], MPO)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_SUSPENDED, 409)
        assert get_auth(scenario["auth"]["id"])["status"] == "APPROVED"


class TestRetrieval:
    def test_auth_get_after_approval(self, api, mpo_headers):
        """PRD §3.4: "On approval the validity window is pinned: `validity_start` equals
        `requested_start_date`, and `validity_end` is exactly 180 days later, the window
        closed on both ends."
        PRD §3.4: "The governing policy's identity is pinned onto the authorization as
        `policy_id` and `policy_version_no`".

        Design: Corner/endpoints/auth_get_retrieval
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J7100", "drug_name": "GetDrug"},
            member_id="MEM-E1",
            with_rate=False,
        )
        auth = scenario["auth"]
        got = validate_success(api.get_prior_authorization(auth["id"], mpo_headers))
        assert_prior_authorization(got)
        assert got["status"] == "APPROVED"
        assert got["approved_dose_mg"] == 100
        assert got["validity_start"] == "2026-08-01"
        # 2026-08-01 + 180 days, inclusive window end.
        assert got["validity_end"] == "2027-01-28"
        assert got["max_administrations"] == 4
        assert got["policy_id"] == scenario["policy"]["id"]
        assert got["policy_version_no"] == 1
        assert got["provider_account_id"] == scenario["provider"]["id"]


class TestWindowOverlap:
    def _setup_member_with_approved_auth(self, j_code, member_id):
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": j_code},
            member_id=member_id,
            with_rate=False,
        )
        return scenario

    def test_touching_window_boundaries_count_as_overlap(self, api):
        """PRD §3.4: "Because validity windows are closed intervals, overlap is symmetric
        and inclusive: two windows overlap exactly when each window's start falls on or
        before the other window's end — windows that merely touch on a single calendar
        date do overlap."
        PRD §3.4: "no other authorization for the same `member_id` and drug may sit in
        `APPROVED` or `SUSPENDED` with an overlapping validity window, otherwise
        `ERR_AUTH_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/auth_window_overlap_closed_interval
        """
        scenario = self._setup_member_with_approved_auth("J3400", "MEM-15")
        # Auth A window: [2026-08-01, 2027-01-28] inclusive.
        assert scenario["auth"]["validity_end"] == "2027-01-28"
        auth_b = submit_auth(
            scenario["drug"]["id"],
            scenario["provider"]["id"],
            "MEM-15",
            requested_start_date="2027-01-28",  # touches A's inclusive end
        )
        resp = api.approve_auth(auth_b["id"], {"max_administrations": 4}, MPO)
        validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP, 409)
        assert get_auth(auth_b["id"])["status"] == "SUBMITTED"

    def test_one_day_past_touching_boundary_accepted(self, api):
        """PRD §3.4: "two windows overlap exactly when each window's start falls on or
        before the other window's end — windows that merely touch on a single calendar
        date do overlap."
        PRD §3.4: "`validity_start` equals `requested_start_date`, and `validity_end` is
        exactly 180 days later, the window closed on both ends."

        Design: Difficulty/resource_temporal_overlap/auth_window_overlap_closed_interval
        """
        scenario = self._setup_member_with_approved_auth("J3401", "MEM-15B")
        auth_c = submit_auth(
            scenario["drug"]["id"],
            scenario["provider"]["id"],
            "MEM-15B",
            requested_start_date="2027-01-29",  # one day past A's inclusive end
        )
        approved = approve_auth(auth_c["id"], 4)
        assert approved["status"] == "APPROVED"
        assert approved["validity_start"] == "2027-01-29"
        assert approved["validity_end"] == "2027-07-28"


class TestApprovalGateOrdering:
    def test_uncovered_diagnosis_reported_over_window_overlap(self, api):
        """PRD §3.4: "Approval by a `MedicalPolicyOfficer` walks its gates in a fixed
        order, and the first failing gate is the one reported." The diagnosis gate ("The
        `diagnosis_code` must appear in that policy's `covered_diagnoses`, otherwise
        `ERR_DIAGNOSIS_NOT_COVERED`") is listed before the window gate ("Finally, no other
        authorization ... with an overlapping validity window, otherwise
        `ERR_AUTH_WINDOW_OVERLAP`"), and §2.8 orders clinical safety before temporal rules.

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_vs_temporal_priority
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2900", "drug_name": "PrioDrugB"},
            member_id="MEM-9",
            with_rate=False,
        )
        # Auth B: same member+drug, uncovered diagnosis, overlapping start.
        auth_b = submit_auth(
            scenario["drug"]["id"],
            scenario["provider"]["id"],
            "MEM-9",
            diagnosis_code="Z99",
            requested_start_date="2026-09-01",
        )
        resp = api.approve_auth(auth_b["id"], {"max_administrations": 4}, MPO)
        # Both the safety rule and the temporal rule are violated; the earlier gate wins.
        validate_error(resp, ApiErrorId.ERR_DIAGNOSIS_NOT_COVERED, 422)
        assert get_auth(auth_b["id"])["status"] == "SUBMITTED"

    def test_window_overlap_fires_when_diagnosis_covered(self, api):
        """PRD §3.4: "Finally, no other authorization for the same `member_id` and drug
        may sit in `APPROVED` or `SUSPENDED` with an overlapping validity window,
        otherwise `ERR_AUTH_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_vs_temporal_priority
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2901", "drug_name": "PrioDrugB2"},
            member_id="MEM-9B",
            with_rate=False,
        )
        auth_c = submit_auth(
            scenario["drug"]["id"],
            scenario["provider"]["id"],
            "MEM-9B",
            diagnosis_code="C50",  # covered: only the temporal gate can fail
            requested_start_date="2026-09-01",
        )
        resp = api.approve_auth(auth_c["id"], {"max_administrations": 4}, MPO)
        validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP, 409)
        assert get_auth(auth_c["id"])["status"] == "SUBMITTED"
