"""PriorAuthorization lifecycle: DRAFT -> SUBMITTED -> APPROVED |
DENIED | INFO_REQUESTED <-> SUBMITTED -> APPROVED -> REVOKED.

PRD §3.3 Prior Authorization Lifecycle.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PA_EFFECTIVE_WINDOW_DAYS,
    PA_EFFECTIVE_WINDOW_SECONDS,
    PA_REVISION_LIMIT,
    SECONDS_PER_DAY,
    advance_clock,
    approve_pa,
    assert_prior_authorization,
    assert_version_incremented_by_one,
    create_drug,
    create_member,
    create_pa_in_draft,
    create_plan,
    create_prior_authorization_payload,
    deny_pa,
    occ_payload,
    re_get_prior_authorization,
    request_info_pa,
    resubmit_pa,
    resubmit_prior_authorization_payload,
    revoke_pa,
    setup_approved_pa,
    setup_denied_pa,
    setup_pa_at_revision_count,
    setup_reference_data,
    setup_revoked_pa,
    setup_submitted_pa,
    submit_pa,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create -> DRAFT
# ===========================================================================
class TestCreateDraftPA:
    """PRD §3.3 PA creation."""

    def test_create_pa_starts_in_draft(self, api, prescriber_headers):
        """PRD §3.3: "A Prescriber initiates a PriorAuthorization by
        supplying a member_id, a drug_id, a ten-digit prescriber_npi
        … and a clinical_rationale free-text justification that must
        be non-empty. The prior authorization is created in DRAFT".

        Claim: POST /pbm/prior-authorizations creates a PA in DRAFT
        with revision_count=0.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_prior_authorization_payload(
            member_id=member["id"], drug_id=drug["id"],
            prescriber_npi="1234567890",
            clinical_rationale="Pt meets clinical criteria.",
        )
        pa = validate_success(
            api.create_prior_authorization(payload, prescriber_headers),
            201,
        )
        assert_prior_authorization(pa)
        assert pa["status"] == "DRAFT"
        assert pa["revision_count"] == 0

    @pytest.mark.parametrize("bad_npi", ["123", "12345678901", "abcdefghij"])
    def test_invalid_npi_rejected(
        self, api, prescriber_headers, bad_npi,
    ):
        """PRD §3.3: "a ten-digit prescriber_npi matching the National
        Provider Identifier format (exactly ten digit characters)".
        PRD §5: ERR_VALIDATION covers "invalid NDC format, etc."
        (generic field validation; "etc." extends to NPI format).

        Note (PRD-only readers): the verbatim PRD sentence about NPI
        format does not explicitly enumerate ERR_VALIDATION as the
        rejection code, so this assertion is widened to accept any
        4xx (a fair PRD-only implementer might also reject with a
        more generic input-validation error). The test still verifies
        the format rule is enforced.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_prior_authorization_payload(
            member_id=member["id"], drug_id=drug["id"],
            prescriber_npi=bad_npi,
            clinical_rationale="x",
        )
        res = api.create_prior_authorization(payload, prescriber_headers)
        assert 400 <= res.status_code < 500, (
            f"invalid NPI must be rejected with a 4xx, got "
            f"{res.status_code}"
        )


# ===========================================================================
# Submit, approve, deny — happy paths
# ===========================================================================
class TestSubmitApproveDeny:

    def test_submit_transitions_to_submitted(
        self, api, prescriber_headers,
    ):
        """PRD §3.3: "The submit transition requires that the prior
        authorization actually be in DRAFT and that clinical_rationale
        remain non-empty; the only fields the transition touches are
        status itself, updated_at, and version."

        Claim: submit transitions DRAFT -> SUBMITTED and bumps
        version.
        """
        _, drug, _, member = setup_reference_data()
        pa = create_pa_in_draft(member_id=member["id"], drug_id=drug["id"])
        old_version = pa["version"]
        res = api.submit_prior_authorization(
            pa["id"], occ_payload(version=old_version),
            prescriber_headers,
        )
        submitted = validate_success(res, 200)
        assert submitted["status"] == "SUBMITTED"
        assert_version_incremented_by_one(
            submitted["version"], old_version,
        )

    def test_approve_writes_effective_window(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "the approval writes effective_start to the
        current clock time, writes effective_end to the current clock
        time plus 180 days, and transitions the prior authorization
        to APPROVED."

        Claim: approve transitions SUBMITTED -> APPROVED and writes
        both effective_start and effective_end.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_submitted_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.approve_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        approved = validate_success(res, 200)
        assert approved["status"] == "APPROVED"
        assert approved.get("effective_start") is not None
        assert approved.get("effective_end") is not None

    def test_approve_effective_end_is_180_days_after_start(
        self, api,
    ):
        """PRD §3.3: "effective_end to the current clock time plus
        180 days".

        Claim: effective_end == effective_start + 180 days
        (in seconds, since both are second-granular timestamps
        relative to the simulated clock).
        """
        from datetime import datetime

        def parse(ts: str) -> datetime:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        _, drug, _, member = setup_reference_data()
        pa = setup_approved_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        start = parse(pa["effective_start"])
        end = parse(pa["effective_end"])
        delta_seconds = int((end - start).total_seconds())
        assert delta_seconds == PA_EFFECTIVE_WINDOW_SECONDS, (
            f"effective_end - effective_start must equal 180 days "
            f"({PA_EFFECTIVE_WINDOW_SECONDS}s), got {delta_seconds}s"
        )

    def test_deny_writes_denial_reason(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "Denying it requires the prior authorization to
        be in SUBMITTED, takes a denial_reason from the request body,
        and transitions the prior authorization to DENIED."

        Claim: deny transitions SUBMITTED -> DENIED and stores
        denial_reason.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_submitted_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.deny_prior_authorization(
            pa["id"],
            {"denial_reason": "Off-label use.", "version": pa["version"]},
            clinical_reviewer_headers,
        )
        denied = validate_success(res, 200)
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Off-label use."

    def test_request_info_does_not_change_revision_count(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "Requesting more information from the prescriber
        also requires SUBMITTED as the source state and transitions
        the prior authorization to INFO_REQUESTED; this hop alone does
        not change revision_count."

        Claim: request-info bumps status only; revision_count stays
        the same.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_submitted_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        pre_rev = pa["revision_count"]
        res = api.request_info_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        info = validate_success(res, 200)
        assert info["status"] == "INFO_REQUESTED"
        assert info["revision_count"] == pre_rev


# ===========================================================================
# Resubmit cycle — revision_count bound by 3.
# ===========================================================================
class TestResubmitCycle:
    """PRD §3.3 cyclic SUBMITTED <-> INFO_REQUESTED, bounded by
    revision_count < 3."""

    def test_resubmit_increments_revision_count(
        self, api,
    ):
        """PRD §3.3: "The resubmit hop increments revision_count by
        exactly one as part of the transition back to SUBMITTED".

        Claim: after one INFO_REQUESTED -> SUBMITTED resubmit, the PA
        is in SUBMITTED with revision_count incremented by exactly 1.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_pa_at_revision_count(
            member_id=member["id"], drug_id=drug["id"],
            revision_count=1,
        )
        assert pa["status"] == "SUBMITTED"
        assert pa["revision_count"] == 1

    def test_resubmit_at_revision_three_rejected(
        self, api, prescriber_headers,
    ):
        """PRD §3.3: "a fresh revision is only legal while
        revision_count is strictly less than 3 at the moment of
        resubmit (so 0, 1, and 2 are the only legal source values,
        yielding 1, 2, and 3 respectively after the increment). An
        attempt to resubmit when revision_count is already 3 is
        rejected with ERR_PA_REVISION_LIMIT."

        Claim: after the third resubmit (revision_count=3), a fourth
        attempt is rejected with ERR_PA_REVISION_LIMIT.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_pa_at_revision_count(
            member_id=member["id"], drug_id=drug["id"],
            revision_count=3,
        )
        assert pa["revision_count"] == 3
        # Cycle back to INFO_REQUESTED so the next resubmit is even
        # syntactically a legal transition target — its
        # revision_count check is what we want to exercise.
        info = request_info_pa(pa)
        res = api.resubmit_prior_authorization(
            info["id"],
            resubmit_prior_authorization_payload(
                clinical_rationale="any", version=info["version"],
            ),
            prescriber_headers,
        )
        validate_error(res, "ERR_PA_REVISION_LIMIT")


# ===========================================================================
# Approve / Deny / Revoke from wrong states.
# ===========================================================================
class TestStateLegality:
    """PRD §2.8 rung 4: state legality. PRD §3.3 source-state rules."""

    def test_approve_from_draft_rejected(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "Approving it requires that the prior
        authorization currently be in SUBMITTED".
        PRD §2.8 rung 4: "the target resource must be in a state
        legal for the requested transition … Violations yield
        ERR_INVALID_STATE (409)."

        Claim: approve on DRAFT -> ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        pa = create_pa_in_draft(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.approve_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_deny_from_approved_rejected(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "Denying it requires the prior authorization to
        be in SUBMITTED".

        Claim: deny on APPROVED -> ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_approved_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.deny_prior_authorization(
            pa["id"],
            {"denial_reason": "late", "version": pa["version"]},
            clinical_reviewer_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_revoke_from_draft_rejected(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "A ClinicalReviewer may revoke an APPROVED
        prior authorization".
        PRD §2.8 rung 4: "Violations yield ERR_INVALID_STATE (409)."

        Claim: revoke on DRAFT -> ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        pa = create_pa_in_draft(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.revoke_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_resubmit_from_draft_rejected(
        self, api, prescriber_headers,
    ):
        """PRD §3.3: resubmit applies only to PAs in INFO_REQUESTED.
        PRD §2.8 rung 4: "Violations yield ERR_INVALID_STATE (409)."

        Claim: resubmit on DRAFT -> ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        pa = create_pa_in_draft(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.resubmit_prior_authorization(
            pa["id"],
            resubmit_prior_authorization_payload(
                clinical_rationale="x", version=pa["version"],
            ),
            prescriber_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Approve requires ACTIVE member (cross-entity).
# ===========================================================================
class TestApproveRequiresActiveMember:
    """PRD §2.8 rung 5: ERR_MEMBER_NOT_ACTIVE."""

    def test_approve_on_suspended_member_rejected(
        self, api, admin_headers, clinical_reviewer_headers,
    ):
        """PRD §2.8 rung 5: "for claim adjudicate and prior-
        authorization approve, the referenced Member must satisfy
        enrollment_status equal to ACTIVE; otherwise the request
        yields ERR_MEMBER_NOT_ACTIVE (409)."
        PRD §3.3: "Approving it requires that the prior authorization
        currently be in SUBMITTED and that the referenced member be
        ACTIVE".

        Claim: approve when Member is SUSPENDED -> ERR_MEMBER_NOT_ACTIVE.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_submitted_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        # Suspend member.
        suspend_res = api.suspend_member(
            member["id"], {"version": member["version"]},
            admin_headers,
        )
        validate_success(suspend_res, 200)
        # Now try to approve.
        res = api.approve_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


# ===========================================================================
# Revoke — terminal state cleanup.
# ===========================================================================
class TestRevokeAndExpire:
    """PRD §3.3 terminal states + revoke."""

    def test_revoke_from_approved(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §3.3: "A ClinicalReviewer may revoke an APPROVED
        prior authorization, transitioning it to REVOKED."

        Claim: revoke from APPROVED transitions to REVOKED.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_approved_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        res = api.revoke_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        revoked = validate_success(res, 200)
        assert revoked["status"] == "REVOKED"

    def test_pa_auto_expires_at_effective_end(
        self, api, admin_headers,
    ):
        """PRD §2.11: "any APPROVED prior authorization whose
        effective_end is at or earlier than the new clock time auto-
        transitions to EXPIRED".
        PRD §3.3: "Independently of any operator action, an APPROVED
        prior authorization auto-transitions to EXPIRED the moment
        the simulated clock advances to a time at or after
        effective_end."

        Claim: advancing the clock to effective_end auto-transitions
        an APPROVED PA to EXPIRED.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_approved_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        # Advance exactly 180 days.
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS)
        refreshed = re_get_prior_authorization(pa["id"])
        assert refreshed["status"] == "EXPIRED"
