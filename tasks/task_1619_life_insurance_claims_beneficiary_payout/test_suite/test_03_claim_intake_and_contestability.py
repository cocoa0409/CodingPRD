"""Claim intake: policy snapshots, death-date temporal bounds, statute
resolution, the contestability boundary, and the begin-review routing fork
with its interpleader exit branch."""
from test_helpers import (
    ApiErrorId,
    assert_claim,
    begin_review,
    create_designation,
    create_policy,
    create_policy_with_statute,
    file_beneficiary_claim,
    file_claim,
    get_claim,
    set_clock,
    validate_beneficiary_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClaimCreation:
    def test_claim_snapshots_policy_fields(self, api, claims_examiner_headers):
        """PRD §3.4: "A successfully filed claim stands in `NOTIFIED` status
        with its `notification_date` stamped from the logical clock, the filing
        examiner's `X-User-ID` recorded as `assigned_examiner_id` (the
        segregation-of-duties anchor for later decisions), and the policy's
        `face_amount_cents` and `state_code` snapshotted onto the claim so that
        later policy edits cannot rewrite the claim's basis."

        Design: Corner/entities/c_claim_snapshots_policy_fields
        """
        policy = create_policy_with_statute("IL", policy_number="P-COR-3",
                                            face_amount_cents=7000000)
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        assert_claim(claim)
        assert claim["face_amount_cents"] == 7000000, "Snapshot from the policy"
        assert claim["state_code"] == "IL", "Snapshot from the policy"
        assert claim["notification_date"] == "2026-03-05"
        assert claim["assigned_examiner_id"] == "examiner-1"
        assert claim["status"] == "NOTIFIED"


class TestDeathDateTemporalBounds:
    def test_death_date_in_future_rejected(self, api, claims_examiner_headers):
        """PRD §3.4: "The `date_of_death` must fall on or after the policy's
        `issue_date` and on or before the logical current date; a death date
        before issuance or in the future is rejected with
        `ERR_INVALID_DEATH_DATE`."

        Future leg: death 2026-03-01 against the 2026-01-01 logical clock.

        Design: Corner/validations/c_invalid_death_date_boundaries_rejected
        """
        policy = create_policy_with_statute("IL", policy_number="P-VAL-3")
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_claim({"policy_id": policy["id"],
                                 "date_of_death": "2026-03-01"},
                                claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_DEATH_DATE)

    def test_death_date_before_issue_rejected(self, api, claims_examiner_headers):
        """PRD §3.4: "The `date_of_death` must fall on or after the policy's
        `issue_date` and on or before the logical current date; a death date
        before issuance or in the future is rejected with
        `ERR_INVALID_DEATH_DATE`."

        Pre-issuance leg: death 2023-12-31 against issue 2024-03-01.

        Design: Corner/validations/c_invalid_death_date_boundaries_rejected
        """
        policy = create_policy_with_statute("IL", policy_number="P-VAL-3")
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_claim({"policy_id": policy["id"],
                                 "date_of_death": "2023-12-31"},
                                claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_DEATH_DATE)

        data, meta = validate_paginated(
            api.list_claims(claims_examiner_headers,
                            params={"policy_id": policy["id"]}))
        assert meta["total_count"] == 0 and data == []


class TestStatuteResolutionAtFiling:
    def test_claim_without_statute_rejected(self, api, claims_examiner_headers):
        """PRD §2.7: "Filing a claim against a policy whose state has no
        configured statute is rejected with `ERR_STATUTE_NOT_CONFIGURED`
        (HTTP 422)."

        Design: Corner/validations/c_claim_without_statute_rejected
        """
        policy = create_policy(policy_number="P-VAL-4", state_code="ZZ")
        set_clock("2026-03-05T00:00:00Z")
        resp = api.create_claim({"policy_id": policy["id"],
                                 "date_of_death": "2026-03-01"},
                                claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_STATUTE_NOT_CONFIGURED)


class TestContestabilityBoundary:
    def test_death_one_day_inside_window_is_contestable(
        self, api, claims_examiner_headers
    ):
        """PRD §3.4: "The boundary date is the policy's `issue_date` advanced by
        `contestability_months` calendar months, preserving the day of month; a
        death strictly before that boundary renders the flag true, while a death
        exactly on the boundary date is not contestable and renders it false."

        X-1 leg: death 2026-02-28 is one day inside the 2024-03-01 + 24 months
        boundary, so the flag is true and review routes to
        CONTESTABILITY_REVIEW (PRD §3.4: "a claim whose `contestability_flag`
        is false moves to `UNDER_REVIEW`, while a contestable claim moves to
        `CONTESTABILITY_REVIEW`").

        Design: Difficulty/boundary_precision_check/contestability_exactly_24_months_is_not_contestable
        """
        policy = create_policy_with_statute("IL", policy_number="P-BND-A",
                                            contestability_months=24)
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-02-28")
        assert claim["contestability_flag"] is True

        routed = validate_success(api.begin_review(claim["id"],
                                                   claims_examiner_headers))
        assert routed["status"] == "CONTESTABILITY_REVIEW"

    def test_death_exactly_on_boundary_is_not_contestable(
        self, api, claims_examiner_headers
    ):
        """PRD §3.4: "The boundary date is the policy's `issue_date` advanced by
        `contestability_months` calendar months, preserving the day of month; a
        death strictly before that boundary renders the flag true, while a death
        exactly on the boundary date is not contestable and renders it false."

        X leg: death 2026-03-01 is exactly issue_date + 24 months, so the flag
        is false and review routes to UNDER_REVIEW (PRD §3.4: "a claim whose
        `contestability_flag` is false moves to `UNDER_REVIEW`, while a
        contestable claim moves to `CONTESTABILITY_REVIEW`").

        Design: Difficulty/boundary_precision_check/contestability_exactly_24_months_is_not_contestable
        """
        policy = create_policy_with_statute("IL", policy_number="P-BND-B",
                                            contestability_months=24)
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        assert claim["contestability_flag"] is False

        routed = validate_success(api.begin_review(claim["id"],
                                                   claims_examiner_headers))
        assert routed["status"] == "UNDER_REVIEW"


class TestBeginReviewFork:
    def test_begin_review_twice_rejected(self, api, claims_examiner_headers):
        """PRD §3.4: "When a `ClaimsExaminer` begins review — allowed only from
        `NOTIFIED`, else `ERR_CLAIM_NOT_REVIEWABLE` — a claim whose
        `contestability_flag` is false moves to `UNDER_REVIEW`, while a
        contestable claim moves to `CONTESTABILITY_REVIEW`."
        PRD §2.5: "The `version` is a system-managed integer that increments by
        one with every mutation of the resource" — a rejected call performs no
        mutation.

        Design: Corner/state_machines/c_begin_review_twice_rejected
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-1")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        routed = validate_success(api.begin_review(claim["id"],
                                                   claims_examiner_headers))
        assert routed["status"] == "UNDER_REVIEW"

        resp = api.begin_review(claim["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)

        after = get_claim(claim["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["version"] == routed["version"], (
            "A rejected transition must not bump the claim version")

    def test_begin_review_contestability_fork(self, api, claims_examiner_headers):
        """PRD §3.4: "When a `ClaimsExaminer` begins review — allowed only from
        `NOTIFIED`, else `ERR_CLAIM_NOT_REVIEWABLE` — a claim whose
        `contestability_flag` is false moves to `UNDER_REVIEW`, while a
        contestable claim moves to `CONTESTABILITY_REVIEW`."

        Both fork branches side by side: the same trigger routes claim A (death
        inside the window) to CONTESTABILITY_REVIEW and claim B (death on the
        boundary) to UNDER_REVIEW.

        Design: Difficulty/non_linear_state_machine/claim_contestability_fork_and_interpleader_branch
        """
        policy_a = create_policy_with_statute("IL", policy_number="P-BR-A",
                                              contestability_months=24)
        policy_b = create_policy_with_statute("IL", policy_number="P-BR-B",
                                              contestability_months=24,
                                              insured_name="Bob Doe",
                                              insured_dob="1971-08-08")
        set_clock("2026-03-05T00:00:00Z")
        claim_a = file_claim(policy_a["id"], "2026-02-28")
        claim_b = file_claim(policy_b["id"], "2026-03-01")
        assert claim_a["contestability_flag"] is True
        assert claim_b["contestability_flag"] is False

        routed_a = validate_success(api.begin_review(claim_a["id"],
                                                     claims_examiner_headers))
        routed_b = validate_success(api.begin_review(claim_b["id"],
                                                     claims_examiner_headers))
        assert routed_a["status"] == "CONTESTABILITY_REVIEW"
        assert routed_b["status"] == "UNDER_REVIEW"

    def test_interpleader_branch_from_legal_hold(
        self, api, legal_counsel_headers
    ):
        """PRD §3.7: "Referral requires the claim to be in `LEGAL_HOLD` — from
        any other state it is rejected with `ERR_CLAIM_NOT_IN_LEGAL_HOLD` — and
        requires a `court_reference`."
        PRD §3.7: "The claim moves to the terminal `INTERPLEADED` state, accrued
        interest is recomputed as of the referral date and frozen there, every
        beneficiary claim still in `DISPUTED` moves to `INTERPLEADED`, every
        payout election of the claim in `ELECTED`, `CONFIRMED`, or `SUSPENDED`
        is superseded to `SUPERSEDED`, and the claim's `version` increments."

        Branch leg: a rival filing places the under-review claim on legal hold,
        and the interpleader referral exits the hold branch into INTERPLEADED.

        Design: Difficulty/non_linear_state_machine/claim_contestability_fork_and_interpleader_branch
        """
        policy = create_policy_with_statute("IL", policy_number="P-BR-B")
        designation = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                         share_percent=100)
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        begin_review(claim["id"])
        alice = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                       claimant_name="Alice Doe")
        validate_beneficiary_claim(alice["id"])

        # Rival filing under a different claimant name triggers the hold branch.
        eve = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                     claimant_name="Eve Smith")
        assert eve["status"] == "SUBMITTED"
        held = get_claim(claim["id"])
        assert held["status"] == "LEGAL_HOLD"
        assert held["hold_return_state"] == "UNDER_REVIEW"

        referred = validate_success(
            api.refer_interpleader(claim["id"],
                                   {"court_reference": "2026-CV-0042"},
                                   legal_counsel_headers))
        assert referred["status"] == "INTERPLEADED"

        alice_after = api.get_beneficiary_claim(alice["id"],
                                                legal_counsel_headers).json()["data"]
        assert alice_after["status"] == "INTERPLEADED", (
            "The DISPUTED beneficiary claim cascades to INTERPLEADED")
