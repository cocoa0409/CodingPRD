"""Appeal lifecycle — PRD §3.6.

Covers filing, segregation of duties, hearing-start, withdraw,
SUSTAINED / REVERSED branches, and the version pin
(ERR_STALE_APPEAL_SUBJECT).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    APPEAL_WINDOW_DAYS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_by_days,
    audit_certification,
    create_appeal_payload,
    create_denied_claim,
    create_eligible_claim,
    approve_one_weekly_certification,
    decide_appeal,
    decide_appeal_payload,
    file_appeal,
    get_claim,
    list_claim_overpayments,
    make_appeal_officer_headers,
    make_claimant_headers,
    setup_filed_appeal_on_denied_claim,
    setup_in_hearing_appeal_on_denied_claim,
    setup_outstanding_overpayment,
    start_appeal_hearing,
    validate_error,
    validate_success,
    withdraw_appeal,
)


class TestAppealFiling:

    def test_appeal_created_in_filed_state(self, api):
        """PRD §3.6: "The appeal starts life in FILED."
        """
        bundle = setup_filed_appeal_on_denied_claim()
        appeal = bundle["appeal"]
        assert appeal["status"] == "FILED"
        assert appeal["subject_type"] == "MONETARY_DETERMINATION"
        assert appeal["assigned_appeal_officer_id"] == "appeal-officer-0001"

    def test_appeal_pins_subject_version_at_filing(self, api):
        """PRD §3.6: "On creation, the server pins the subject entity's
        current version into the appeal's subject_locked_version."
        """
        bundle = setup_filed_appeal_on_denied_claim()
        appeal = bundle["appeal"]
        claim = get_claim(bundle["claim"]["id"])
        assert appeal["subject_locked_version"] == claim["version"]

    def test_appeal_pins_adjudicator_id_for_segregation(self, api):
        """PRD §3.6: "copies the subject's adjudicator into the appeal's
        assigned_adjudicator_id (the X-User-ID that was recorded when
        the subject's determination was made)."
        """
        bundle = setup_filed_appeal_on_denied_claim(
            adjudicator_id="adjudicator-xyz",
        )
        appeal = bundle["appeal"]
        assert appeal["assigned_adjudicator_id"] == "adjudicator-xyz"

    def test_appeal_deadline_set_to_window(self, api):
        """PRD §3.6: "its deadline_at is computed as filed_at plus the
        30-day appeal window (APPEAL_WINDOW_DAYS)."
        """
        from datetime import datetime
        bundle = setup_filed_appeal_on_denied_claim()
        appeal = bundle["appeal"]
        filed = datetime.fromisoformat(appeal["filed_at"].replace("Z", "+00:00"))
        deadline = datetime.fromisoformat(
            appeal["deadline_at"].replace("Z", "+00:00"),
        )
        delta_days = (deadline - filed).days
        assert delta_days == APPEAL_WINDOW_DAYS, (
            f"deadline_at must be filed_at + {APPEAL_WINDOW_DAYS} days, "
            f"got delta={delta_days}"
        )

    def test_duplicate_appeal_on_same_subject_rejected(self, api):
        """PRD §3.6: "At most one appeal may exist for any given
        (subject_type, subject_id) pair; a second filing attempt is
        rejected with ERR_APPEAL_ALREADY_FILED."
        """
        bundle = setup_filed_appeal_on_denied_claim()
        # Try filing another appeal on the same claim's monetary determination.
        resp = api.create_appeal(
            create_appeal_payload(
                claim_id=bundle["claim"]["id"],
                subject_type="MONETARY_DETERMINATION",
                subject_id=bundle["claim"]["id"],
                assigned_appeal_officer_id="appeal-officer-0001",
            ),
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_FILED.value)


class TestSegregationOfDuties:

    def test_start_hearing_by_assigned_adjudicator_rejected(self, api):
        """PRD §3.6: "Starting a hearing requires that the requesting
        X-User-ID equals the appeal's assigned_appeal_officer_id, that
        the requesting X-User-ID is not equal to the appeal's
        assigned_adjudicator_id (otherwise
        ERR_SEGREGATION_OF_DUTIES_VIOLATION)."
        """
        # Assign the appeal officer to the SAME user_id as the adjudicator.
        shared = "shared-user-123"
        from test_helpers import create_denied_claim, file_appeal
        bundle = create_denied_claim(adjudicator_id=shared)
        appeal = file_appeal(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            subject_type="MONETARY_DETERMINATION",
            subject_id=bundle["claim"]["id"],
            assigned_appeal_officer_id=shared,
        )
        # appeal is FILED, but start-hearing with shared user_id collides.
        resp = api.start_hearing(
            appeal["id"], make_appeal_officer_headers(shared),
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        )

    def test_decide_by_assigned_adjudicator_rejected(self, api):
        """PRD §3.6: "The same segregation-of-duties rule applies again:
        the deciding X-User-ID cannot equal assigned_adjudicator_id."

        Setup: get the appeal into IN_HEARING via a distinct officer,
        then try to decide via the adjudicator id.
        """
        bundle = setup_in_hearing_appeal_on_denied_claim(
            adjudicator_id="adj-1", officer_id="officer-2",
        )
        # Decide with X-User-ID = the adjudicator id, role = AppealOfficer.
        resp = api.decide_appeal(
            bundle["appeal"]["id"],
            decide_appeal_payload("SUSTAINED"),
            make_appeal_officer_headers("adj-1"),
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        )


class TestHearingAndDecision:

    def test_start_hearing_moves_to_in_hearing(self, api):
        """PRD §3.6: "The appeal transitions FILED → IN_HEARING."
        """
        bundle = setup_in_hearing_appeal_on_denied_claim()
        assert bundle["appeal"]["status"] == "IN_HEARING"

    def test_sustained_leaves_subject_unchanged(self, api):
        """PRD §3.6: "A decision of SUSTAINED transitions the appeal
        IN_HEARING → SUSTAINED, sets decision_at to SystemClock.now,
        and leaves the subject unchanged — the original determination
        stands."
        """
        bundle = setup_in_hearing_appeal_on_denied_claim()
        appeal = decide_appeal(bundle["appeal"]["id"], "SUSTAINED")
        assert appeal["status"] == "SUSTAINED"
        assert appeal.get("decision_at") is not None
        # Subject (Claim) remains DENIED.
        claim = get_claim(bundle["claim"]["id"])
        assert claim["status"] == "DENIED"

    def test_reversed_monetary_determination_flips_claim_to_eligible(self, api):
        """PRD §3.6: "For MONETARY_DETERMINATION: the parent Claim
        transitions DENIED → MONETARILY_ELIGIBLE and its version is
        incremented."
        """
        bundle = setup_in_hearing_appeal_on_denied_claim()
        appeal = decide_appeal(bundle["appeal"]["id"], "REVERSED")
        assert appeal["status"] == "REVERSED"
        claim = get_claim(bundle["claim"]["id"])
        assert claim["status"] == "MONETARILY_ELIGIBLE"

    def test_reversed_overpayment_assessment_waives(self, api):
        """PRD §3.6: "For OVERPAYMENT_ASSESSMENT: the Overpayment is
        set to status equal to WAIVED with balance_cents set to zero."
        """
        bundle = setup_outstanding_overpayment(
            classification="NON_FRAUD",
            adjudicator_id="adj-A",
        )
        op = bundle["overpayment"]
        # File appeal of OVERPAYMENT_ASSESSMENT.
        appeal = file_appeal(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            subject_type="OVERPAYMENT_ASSESSMENT",
            subject_id=op["id"],
            assigned_appeal_officer_id="officer-distinct",
        )
        start_appeal_hearing(appeal["id"], officer_id="officer-distinct")
        decide_appeal(appeal["id"], "REVERSED", officer_id="officer-distinct")
        from test_helpers import get_overpayment
        op_after = get_overpayment(op["id"])
        assert op_after["status"] == "WAIVED"
        assert op_after["balance_cents"] == 0


class TestWithdraw:

    def test_claimant_can_withdraw_filed_appeal(self, api):
        """PRD §3.6: "A claimant may withdraw a FILED appeal at any
        time, transitioning the appeal FILED → WITHDRAWN."
        """
        bundle = setup_filed_appeal_on_denied_claim()
        appeal = withdraw_appeal(
            bundle["appeal"]["id"], bundle["claimant"]["id"],
        )
        assert appeal["status"] == "WITHDRAWN"


class TestVersionPin:

    def test_decide_with_stale_subject_version_rejected(self, api):
        """PRD §3.6: "Before either decision is allowed, the server
        enforces the version pin: the appeal's subject_locked_version
        must equal the current subject entity's version; otherwise the
        decision is rejected with ERR_STALE_APPEAL_SUBJECT."

        # difficulty: cross_entity_state_dependency/appeal_decide_depends_on_subject_version
        """
        # Setup: deny a claim, file an appeal (pins claim.version),
        # mutate the claim (here: via the appeal-reversal pathway is
        # impossible since claim is DENIED; instead, force a mutation
        # by re-adjudicating - not allowed from DENIED. So we set up
        # against a WEEKLY_DENIAL subject we can mutate.)
        #
        # Approach: create an eligible claim, submit a cert that gets
        # DENIED (no work search), file an appeal on the cert
        # (WEEKLY_DENIAL subject), then mutate the cert by ... actually
        # an unrelated audit of an unrelated APPROVED cert would mutate
        # the claim, not the cert. We need to bump the cert's version
        # itself. The cleanest path is to file an appeal on a DENIED
        # claim's monetary determination, then bump the claim version
        # via a subsequent action that doesn't require the claim being
        # eligible. There is no such action — DENIED is terminal except
        # via appeal.
        #
        # Alternative: use OVERPAYMENT_ASSESSMENT subject. Mutate the
        # overpayment via repayment AFTER filing the appeal, which
        # bumps Overpayment.version.
        bundle = setup_outstanding_overpayment(
            classification="NON_FRAUD",
            adjudicator_id="adj-A",
        )
        op = bundle["overpayment"]
        appeal = file_appeal(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            subject_type="OVERPAYMENT_ASSESSMENT",
            subject_id=op["id"],
            assigned_appeal_officer_id="officer-distinct",
        )
        # Mutate the overpayment by a partial repayment -> bumps its version.
        from test_helpers import repay_overpayment
        repay_overpayment(op["id"], bundle["claimant"]["id"], amount_cents=1)
        # Start hearing & try to decide.
        start_appeal_hearing(appeal["id"], officer_id="officer-distinct")
        resp = api.decide_appeal(
            appeal["id"], decide_appeal_payload("SUSTAINED"),
            make_appeal_officer_headers("officer-distinct"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_APPEAL_SUBJECT.value)


class TestDeadline:

    def test_appeal_auto_dismissed_after_deadline(self, api):
        """PRD §3.6: "Independently, when SystemClock.now advances past
        the appeal's deadline_at while the appeal is still FILED, the
        system transitions it FILED → DISMISSED_LATE automatically."
        """
        bundle = setup_filed_appeal_on_denied_claim()
        # Advance the clock past the 30-day window.
        advance_clock_by_days(APPEAL_WINDOW_DAYS + 1)
        from test_helpers import api_client as ac
        resp = ac.get_appeal(
            bundle["appeal"]["id"],
            TEST_USERS["system_admin_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "DISMISSED_LATE", (
            f"expected DISMISSED_LATE after deadline passes, "
            f"got {data['status']}"
        )
