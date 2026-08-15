"""Consent-gated privacy, consent lifecycle, and the caseload pause/resume
round trip (PRD §2.5, §2.6, §3.6)."""
from test_helpers import (
    ApiErrorId,
    add_senior,
    coord,
    create_matched_senior,
    fresh_senior,
    get_staff,
    grant_consent,
    set_clock,
    setup_campaign_with_school,
    setup_verification_case,
    accept_case,
    validate_error,
    validate_success,
)


class TestConsentGatedVisibility:
    def test_status_quartet_masked_until_status_detail_consent(self, api):
        """PRD §2.6: "Each senior's `data_visibility` is a computed value: it
        is `NORMAL` if and only if a `GRANTED` consent record carrying the
        `STATUS_DETAIL` scope exists for that senior, and `RESTRICTED`
        otherwise."
        PRD §2.6: "When a senior's `data_visibility` is `RESTRICTED`, any
        retrieval of that senior — whether a single-record read or an entry in
        a list — returns `fafsa_status`, `submitted_at`,
        `deadline_classification`, and `current_match_link_id` as `null`,
        regardless of the caller's role. Identity and roster fields (name,
        school, language, tags) remain visible; only the aid-status quartet is
        masked."

        Design: Corner/entities/senior_status_fields_masked_without_consent
        """
        campaign, school = setup_campaign_with_school()
        senior, _aid, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_status="SUBMITTED",
            aid_effective_date="2027-01-10",
        )
        assert link["status"] == "AUTO_CONFIRMED"

        masked = fresh_senior(senior["id"])
        assert masked["data_visibility"] == "RESTRICTED"
        assert masked["match_status"] == "MATCHED", (
            "the match axis is not part of the masked quartet"
        )
        for field in (
            "fafsa_status",
            "submitted_at",
            "deadline_classification",
            "current_match_link_id",
        ):
            assert masked[field] is None, (
                f"{field} must be masked to null while RESTRICTED, got "
                f"{masked[field]!r}"
            )

        grant_consent(school, senior["id"], ["STATUS_DETAIL"])
        visible = fresh_senior(senior["id"])
        assert visible["data_visibility"] == "NORMAL"
        assert visible["fafsa_status"] == "SUBMITTED"
        assert visible["current_match_link_id"] == link["id"]


class TestConsentLifecycle:
    def test_consent_auto_expires_when_clock_passes_expires_at(self, api):
        """PRD §2.5: "A consent record in `GRANTED` moves to `EXPIRED` once the
        clock reaches or passes its non-null `expires_at`, firing the same
        cascade as a manual revocation (§3.5)."

        Design: Corner/state_machines/consent_auto_expiry_at_expires_at
        """
        _campaign, school = setup_campaign_with_school()
        senior = add_senior(school)
        consent = grant_consent(
            school,
            senior["id"],
            ["STATUS_DETAIL"],
            granted_by="ADULT_STUDENT",
            expires_at="2026-12-01T00:00:00Z",
        )
        assert fresh_senior(senior["id"])["data_visibility"] == "NORMAL"

        set_clock("2026-12-02T00:00:00Z")
        resp = api.get_consent_record(consent["id"], coord(school))
        consent = validate_success(resp, 200)
        assert consent["status"] == "EXPIRED", (
            f"consent must auto-expire once the clock passes expires_at, got "
            f"{consent['status']}"
        )
        assert fresh_senior(senior["id"])["data_visibility"] == "RESTRICTED"

    def test_repeat_and_invalid_consent_transitions_rejected(self, api):
        """PRD §3.6: "Revoking requires the consent to be `GRANTED` (otherwise
        `ERR_CONSENT_NOT_GRANTED`)" and "It requires the consent to be
        `REVOKED` (`ERR_CONSENT_NOT_REVOKED`)" for regrant.

        Design: Corner/state_machines/consent_invalid_transitions
        """
        _campaign, school = setup_campaign_with_school()
        senior = add_senior(school)
        consent = grant_consent(school, senior["id"], ["OUTREACH"])

        # Regrant while still GRANTED.
        resp = api.regrant_consent(consent["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_REVOKED)

        resp = api.revoke_consent(consent["id"], coord(school))
        revoked = validate_success(resp, 200)
        assert revoked["status"] == "REVOKED"

        # Second revoke of an already-REVOKED consent.
        resp = api.revoke_consent(consent["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED)


class TestCaseloadPauseResumeRoundTrip:
    def test_revoke_pauses_case_and_decrements_caseload(self, api):
        """PRD §3.6: "The senior's `data_visibility` drops to `RESTRICTED`, and
        that flip propagates: every support case of the senior in `OPEN`,
        `IN_REVIEW`, `AWAITING_FAMILY`, or `ESCALATED` moves to `PAUSED` with
        its prior state captured in `previous_status`, and each pause
        decrements the assigned specialist's `active_case_count` with overload
        recovery re-evaluated".

        Design: Difficulty/compensating_invariant/caseload_pause_resume_roundtrip
        """
        ctx = setup_verification_case()
        case = accept_case(ctx["case"], ctx["specialist"])
        assert case["status"] == "IN_REVIEW"
        assert get_staff(ctx["specialist"]["id"])["active_case_count"] == 1

        resp = api.revoke_consent(ctx["consent"]["id"], coord(ctx["school"]))
        validate_success(resp, 200)

        resp = api.get_support_case(case["id"], coord(ctx["school"]))
        paused = validate_success(resp, 200)
        assert paused["status"] == "PAUSED"
        assert paused["previous_status"] == "IN_REVIEW", (
            "the pause must capture the pre-pause working state"
        )
        staff = get_staff(ctx["specialist"]["id"])
        assert staff["active_case_count"] == 0, (
            f"pause must decrement the caseload, got {staff['active_case_count']}"
        )
        assert fresh_senior(ctx["senior"]["id"])["data_visibility"] == "RESTRICTED"

    def test_regrant_resumes_case_and_restores_caseload_exactly(self, api):
        """PRD §3.6: "each `PAUSED` case of the senior resumes to its captured
        `previous_status` — which is then cleared to `null` — while the
        specialist's `active_case_count` re-increments with overload
        re-evaluated; the caseload invariant guarantees a revoke-then-regrant
        round trip returns the count to its exact pre-revoke value."

        Design: Difficulty/compensating_invariant/caseload_pause_resume_roundtrip
        """
        ctx = setup_verification_case()
        case = accept_case(ctx["case"], ctx["specialist"])
        count_before = get_staff(ctx["specialist"]["id"])["active_case_count"]
        assert count_before == 1

        api.revoke_consent(ctx["consent"]["id"], coord(ctx["school"]))
        assert get_staff(ctx["specialist"]["id"])["active_case_count"] == 0

        resp = api.regrant_consent(ctx["consent"]["id"], coord(ctx["school"]))
        validate_success(resp, 200)

        resp = api.get_support_case(case["id"], coord(ctx["school"]))
        resumed = validate_success(resp, 200)
        assert resumed["status"] == "IN_REVIEW", (
            f"resume must restore the captured previous_status, got "
            f"{resumed['status']}"
        )
        assert resumed["previous_status"] is None
        staff = get_staff(ctx["specialist"]["id"])
        assert staff["active_case_count"] == count_before, (
            f"revoke-then-regrant must return the count to exactly "
            f"{count_before}, got {staff['active_case_count']}"
        )
        assert fresh_senior(ctx["senior"]["id"])["data_visibility"] == "NORMAL"
