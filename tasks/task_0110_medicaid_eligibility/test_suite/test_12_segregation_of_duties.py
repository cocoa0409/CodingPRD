"""Segregation-of-duties (SoD) rules — same-actor checks across the
caseworker re-decision path and the appeal grant/uphold path.

Exercises PRD §2.1 (SoD rules) and §3.6 (officer != deciding caseworker).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    decide_application,
    decide_application_payload,
    file_appeal,
    grant_appeal_payload,
    hold_hearing,
    iso_offset,
    make_appeals_officer_headers,
    make_eligibility_caseworker_headers,
    schedule_hearing_payload,
    server_now_dt,
    setup_appeal_under_review,
    setup_denied_application,
    setup_eligible_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Caseworker re-decide cannot equal prior denier — PRD §2.1, §3.3
# ===========================================================================
class TestCaseworkerReDecideSoD:

    def test_same_caseworker_cannot_re_decide_after_overturn(self, api):
        """PRD §2.1: "An EligibilityCaseworker who is asked to re-decide
        an application that has cycled back into review must not be the
        same X-User-ID who issued the prior INELIGIBLE determination on
        that same application."
        PRD §3.3: "the acting caseworker's X-User-ID is not the same
        X-User-ID who issued any prior INELIGIBLE determination on this
        application (otherwise ERR_FORBIDDEN_SAME_ACTOR, enforcing
        segregation of duties on re-decisions)."

        Claim: after appeal grant cycles the Application back into
        UNDER_REVIEW, attempting to re-decide with the same X-User-ID
        who originally DENIED → ERR_FORBIDDEN_SAME_ACTOR.
        """
        # Step 1: DENY by primary caseworker.
        deny_cw = TEST_USERS["eligibility_caseworker_headers"]
        denied_setup = setup_denied_application(decider_headers=deny_cw)
        # Step 2: walk to Appeal.UNDER_REVIEW + FairHearing.HELD using
        # the alt officer (distinct from deny caseworker — PRD §3.6
        # SoD).
        household, application, determination, appeal, _fh = (
            setup_appeal_under_review(
                denied_setup=denied_setup,
                deny_caseworker_headers=deny_cw,
                appeals_officer_headers=TEST_USERS["appeals_officer_headers"],
            )
        )
        # Step 3: grant the appeal — Application returns to UNDER_REVIEW.
        api.grant_appeal(
            appeal["id"], grant_appeal_payload(),
            TEST_USERS["appeals_officer_headers"],
        )
        # Step 4: attempt re-decide with the SAME caseworker → SoD.
        res = api.decide_application(
            household["id"], application["id"],
            decide_application_payload(decision="APPROVE"),
            deny_cw,
        )
        validate_error(res, "ERR_FORBIDDEN_SAME_ACTOR")

    def test_different_caseworker_can_re_decide_after_overturn(self, api):
        """PRD §2.1: SoD compares X-User-IDs; a DIFFERENT caseworker may
        re-decide.

        Claim: after grant, a DIFFERENT caseworker (alt) re-deciding
        succeeds.
        """
        deny_cw = TEST_USERS["eligibility_caseworker_headers"]
        denied_setup = setup_denied_application(
            decider_headers=deny_cw,
            # Permissive eligibility so the re-decide-APPROVE path can
            # actually succeed after grant.
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        household, application, determination, appeal, _fh = (
            setup_appeal_under_review(
                denied_setup=denied_setup,
                deny_caseworker_headers=deny_cw,
                appeals_officer_headers=TEST_USERS["appeals_officer_headers"],
            )
        )
        api.grant_appeal(
            appeal["id"], grant_appeal_payload(),
            TEST_USERS["appeals_officer_headers"],
        )
        # Re-decide with the ALT caseworker.
        res = api.decide_application(
            household["id"], application["id"],
            decide_application_payload(decision="APPROVE"),
            TEST_USERS["eligibility_caseworker_headers_alt"],
        )
        validate_success(res)


# ===========================================================================
# Appeals officer != deciding caseworker — PRD §2.1, §3.6
# ===========================================================================
class TestAppealsOfficerSoD:

    def test_officer_equals_deciding_caseworker_rejected_on_schedule(self, api):
        """PRD §2.1: "An AppealsOfficer who is asked to grant or uphold
        an appeal must not be the same X-User-ID who issued the
        determination being appealed (in either role capacity)."
        PRD §3.6: "the acting AppealsOfficer's X-User-ID must differ
        from the X-User-ID of the EligibilityCaseworker who issued the
        appealed EligibilityDetermination; a same-actor violation is
        rejected with ERR_FORBIDDEN_SAME_ACTOR."

        Claim: scheduling a hearing under an AppealsOfficer X-User-ID
        equal to the deciding caseworker's X-User-ID →
        ERR_FORBIDDEN_SAME_ACTOR.

        Setup uses identical opaque operator id under both roles.
        """
        same_id = "shared-actor-1"
        deny_cw = make_eligibility_caseworker_headers(same_id)
        _sp, _hh, _, _app, determination = setup_denied_application(
            decider_headers=deny_cw,
        )
        appeal = file_appeal(determination=determination)
        # Schedule with the SAME X-User-ID under AppealsOfficer role.
        same_officer = make_appeals_officer_headers(same_id)
        start = iso_offset(days=1, base=server_now_dt())
        end = iso_offset(days=1, hours=1, base=server_now_dt())
        res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=same_id,
                scheduled_start=start, scheduled_end=end,
            ),
            same_officer,
        )
        validate_error(res, "ERR_FORBIDDEN_SAME_ACTOR")
