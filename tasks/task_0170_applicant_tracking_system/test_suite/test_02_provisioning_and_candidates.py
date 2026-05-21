"""Provisioning of people and candidate-source consistency
— PRD §3.1.

Covers: Recruiter, HiringManager, Interviewer, Candidate creation
schemas; Candidate.referrer_employee_id rule (PRD §3.1
ERR_REFERRAL_REQUIRES_REFERRER); EEORecord attachment.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_candidate,
    assert_eeo_record,
    assert_hiring_manager,
    assert_interviewer,
    assert_recruiter,
    attach_eeo_record,
    create_candidate,
    create_candidate_payload,
    create_eeo_record_payload,
    create_hiring_manager,
    create_hiring_manager_payload,
    create_interviewer,
    create_interviewer_payload,
    create_recruiter,
    create_recruiter_payload,
    make_candidate_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# Provisioning happy paths — PRD §3.1
# ===========================================================================
class TestProvisioning:

    def test_create_recruiter_default_is_active_true(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "A new `Recruiter` is born with `is_active` set
        to true by default; only active recruiters may own or create
        requisitions."

        Claim: POST /recruiters returns a Recruiter with is_active=true.
        """
        payload = create_recruiter_payload()
        resp = api.create_recruiter(payload, platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_recruiter(data)
        assert data["is_active"] is True, (
            f"new Recruiter must have is_active=true, got {data['is_active']!r}"
        )

    def test_create_hiring_manager_carries_budget(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "A new `HiringManager` additionally carries
        `budget_cents` — the annual hiring budget against which
        approved offers are debited and rescinded offers are credited
        back, expressed in USD cents and constrained to be
        non-negative."

        Claim: POST /hiring-managers stores budget_cents verbatim.
        """
        payload = create_hiring_manager_payload(budget_cents=500_000_00)
        resp = api.create_hiring_manager(payload, platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_hiring_manager(data)
        assert data["budget_cents"] == 500_000_00, (
            f"budget_cents must equal supplied 50000000, got "
            f"{data['budget_cents']}"
        )

    def test_create_interviewer_default_is_certified_for_eeo_is_false(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "A new `Interviewer` carries an
        `is_certified_for_eeo` flag, defaulting to false, that must be
        true before that interviewer may score a candidate flagged
        `is_in_eeo_protected_class`."

        Claim: POST /interviewers without is_certified_for_eeo returns
        is_certified_for_eeo=false.
        """
        payload = create_interviewer_payload()  # no flag override
        resp = api.create_interviewer(payload, platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_interviewer(data)
        assert data["is_certified_for_eeo"] is False, (
            f"is_certified_for_eeo must default to false, got "
            f"{data['is_certified_for_eeo']!r}"
        )


# ===========================================================================
# Candidate source / referrer consistency — PRD §3.1
# ===========================================================================
class TestCandidateSourceRule:

    def test_referral_without_referrer_id_is_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "When `source` is `REFERRAL`, the request body
        must also include a non-null `referrer_employee_id` pointing
        to a `Recruiter`, `HiringManager`, or `Interviewer`; ...
        The system rejects either violation with
        `ERR_REFERRAL_REQUIRES_REFERRER`."

        Claim: candidate with source=REFERRAL and no referrer_employee_id
        → ERR_REFERRAL_REQUIRES_REFERRER / 422.
        """
        payload = create_candidate_payload(source="REFERRAL")
        # Note: factory only includes referrer_employee_id when value
        # is non-None, so it is absent here.
        resp = api.create_candidate(payload, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_REQUIRES_REFERRER.value)

    def test_non_referral_with_referrer_id_is_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "conversely, when `source` is anything other than
        `REFERRAL`, `referrer_employee_id` must be null. The system
        rejects either violation with `ERR_REFERRAL_REQUIRES_REFERRER`."

        Claim: source=DIRECT with non-null referrer_employee_id →
        ERR_REFERRAL_REQUIRES_REFERRER.
        """
        # Need a real referrer first so we're testing the consistency
        # rule, not ERR_REFERENCE_NOT_FOUND (priority 4 fires before
        # priority 9 — but here we point to a real recruiter and assert
        # the consistency-rule still fires for the source=DIRECT case).
        recruiter = create_recruiter()
        payload = create_candidate_payload(
            source="DIRECT",
            referrer_employee_id=recruiter["id"],
        )
        resp = api.create_candidate(payload, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_REQUIRES_REFERRER.value)

    def test_referral_with_valid_referrer_succeeds(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "When `source` is `REFERRAL`, the request body
        must also include a non-null `referrer_employee_id` pointing
        to a `Recruiter`, `HiringManager`, or `Interviewer`".

        Claim: source=REFERRAL with a real Recruiter id as referrer →
        201 and the candidate exposes referrer_employee_id.
        """
        recruiter = create_recruiter()
        payload = create_candidate_payload(
            source="REFERRAL",
            referrer_employee_id=recruiter["id"],
        )
        resp = api.create_candidate(payload, platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_candidate(data)
        assert data["source"] == "REFERRAL"
        assert data["referrer_employee_id"] == recruiter["id"]


# ===========================================================================
# EEORecord — PRD §3.1
# ===========================================================================
class TestEEORecord:

    def test_eeo_record_immutable_append_only(self, api):
        """PRD §2.4: "`EEORecord` (a self-identification snapshot that
        is immutable once attached to a candidate)" and PRD §2.4:
        "they carry only `id` and `created_at`. These are `EEORecord`
        ... read code must not expect `updated_at` or `version` on
        either."

        Claim: POST /candidates/{id}/eeo-record returns a payload with
        only id + created_at + entity-specific fields — no updated_at
        or version.
        """
        candidate = create_candidate(is_in_eeo_protected_class=True)
        rec = attach_eeo_record(
            candidate_id=candidate["id"],
            gender="FEMALE",
            ethnicity="ASIAN",
            veteran_status="NOT_VETERAN",
            disability_status="NO",
            actor="candidate",
        )
        assert_eeo_record(rec)
        # Specific PRD §2.4 negative assertions — sanity already runs
        # in assert_append_only_fields, but reiterate the rule here.
        assert "updated_at" not in rec, (
            "EEORecord must NOT expose updated_at"
        )
        assert "version" not in rec, "EEORecord must NOT expose version"

    def test_eeo_record_stores_submitted_at(self, api):
        """PRD §3.1: "The server stamps `submitted_at` at attachment
        time."

        Claim: POST /candidates/{id}/eeo-record returns a record
        carrying a submitted_at ISO 8601 timestamp.
        """
        candidate = create_candidate()
        rec = attach_eeo_record(
            candidate_id=candidate["id"], actor="candidate",
        )
        from test_helpers import is_iso8601_timestamp
        assert is_iso8601_timestamp(str(rec["submitted_at"])), (
            f"submitted_at must be ISO 8601, got {rec.get('submitted_at')!r}"
        )

    def test_eeo_record_field_validation_enums(self, api):
        """PRD §3.1: "`gender` (one of `MALE`, `FEMALE`, `NON_BINARY`,
        `DECLINE`), `ethnicity` (one of `HISPANIC_LATINO`, `WHITE`,
        `BLACK_AFRICAN_AMERICAN`, `NATIVE_HAWAIIAN_PI`, `ASIAN`,
        `AMERICAN_INDIAN_AN`, `TWO_OR_MORE`, `DECLINE`), `veteran_status`
        (one of `NOT_VETERAN`, `PROTECTED_VETERAN`, `OTHER_VETERAN`,
        `DECLINE`), and `disability_status` (one of `YES`, `NO`,
        `DECLINE`)."

        Claim: round-trip of valid enum values is faithful.
        """
        candidate = create_candidate()
        h = make_candidate_headers(candidate["id"])
        payload = create_eeo_record_payload(
            gender="NON_BINARY",
            ethnicity="TWO_OR_MORE",
            veteran_status="PROTECTED_VETERAN",
            disability_status="DECLINE",
        )
        resp = api.create_eeo_record(candidate["id"], payload, h)
        data = validate_success(resp, expected_status=201)
        assert data["gender"] == "NON_BINARY"
        assert data["ethnicity"] == "TWO_OR_MORE"
        assert data["veteran_status"] == "PROTECTED_VETERAN"
        assert data["disability_status"] == "DECLINE"
