"""ParentingPlan: propose, counter, accept, overnight totals, custody.

PRD §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_parenting_plan,
    api_client,
    assert_parenting_plan,
    create_case,
    create_parenting_plan_payload,
    make_petitioner_headers,
    make_respondent_headers,
    propose_parenting_plan,
    re_get_parenting_plan,
    setup_case_with_both_disclosures_accepted,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Overnights validation — PRD §3.3
# ===========================================================================
class TestOvernightsInvalid:

    def test_overnights_summing_to_not_365_rejected(self, api):
        """PRD §3.3: 'Each overnight count must be in the inclusive
        range zero to 365, and the two values must sum to exactly 365;
        any other combination is rejected with ERR_OVERNIGHTS_INVALID
        (HTTP 422).'

        Claim: 100 + 200 = 300 != 365 → ERR_OVERNIGHTS_INVALID.
        """
        case = create_case()
        payload = create_parenting_plan_payload(
            proposing_party_id=case["petitioner_party_id"],
            petitioner_overnights_per_year=100,
            respondent_overnights_per_year=200,
        )
        res = api.create_parenting_plan(
            case["id"], payload,
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_OVERNIGHTS_INVALID", expected_status=422,
        )

    def test_overnights_out_of_range_rejected(self, api):
        """PRD §3.3: 'Each overnight count must be in the inclusive
        range zero to 365'.

        Claim: a negative overnight count is rejected
        ERR_OVERNIGHTS_INVALID.
        """
        case = create_case()
        payload = create_parenting_plan_payload(
            proposing_party_id=case["petitioner_party_id"],
            petitioner_overnights_per_year=-1,
            respondent_overnights_per_year=366,
        )
        res = api.create_parenting_plan(
            case["id"], payload,
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_OVERNIGHTS_INVALID", expected_status=422,
        )

    def test_zero_and_365_split_accepted(self, api):
        """PRD §3.3: 'in the inclusive range zero to 365'.

        Claim: 0/365 split is a valid boundary.
        """
        case = create_case()
        plan = propose_parenting_plan(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            petitioner_overnights=0,
            respondent_overnights=365,
        )
        assert_parenting_plan(plan)
        assert plan["petitioner_overnights_per_year"] == 0
        assert plan["respondent_overnights_per_year"] == 365


# ===========================================================================
# Counter — PRD §3.3
# ===========================================================================
class TestCounter:

    def test_counter_by_proposer_rejected(self, api):
        """PRD §3.3: 'The counter must be filed by the party who did
        not propose the original; an attempt by the original proposer
        (or their attorney) to file the counter is rejected with
        ERR_COUNTER_BY_PROPOSER (HTTP 422).'

        Claim: Petitioner proposes; Petitioner then tries to file a
        counter → ERR_COUNTER_BY_PROPOSER.
        """
        case = create_case()
        plan = propose_parenting_plan(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        # Same Petitioner files a counter.
        counter_payload = create_parenting_plan_payload(
            proposing_party_id=case["petitioner_party_id"],
            petitioner_overnights_per_year=150,
            respondent_overnights_per_year=215,
            countered_plan_id=plan["id"],
        )
        res = api.create_parenting_plan(
            case["id"], counter_payload,
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_COUNTER_BY_PROPOSER", expected_status=422,
        )

    def test_counter_by_other_party_transitions_original_to_countered(
        self, api,
    ):
        """PRD §3.3: 'On a successful counter the original plan
        transitions from PROPOSED to COUNTERED and its
        countered_by_plan_id is set to the id of the new plan.'

        Claim: a valid counter sets original.status=COUNTERED and
        original.countered_by_plan_id to the new plan's id.
        """
        case = create_case()
        plan = propose_parenting_plan(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        counter_payload = create_parenting_plan_payload(
            proposing_party_id=case["respondent_party_id"],
            petitioner_overnights_per_year=150,
            respondent_overnights_per_year=215,
            countered_plan_id=plan["id"],
        )
        res = api.create_parenting_plan(
            case["id"], counter_payload,
            make_respondent_headers(case["respondent_party_id"]),
        )
        new_plan = validate_success(res, 201)
        original = re_get_parenting_plan(case["id"], plan["id"])
        assert original["status"] == "COUNTERED"
        assert original["countered_by_plan_id"] == new_plan["id"]


# ===========================================================================
# Self-accept — PRD §3.3
# ===========================================================================
class TestSelfAccept:

    def test_proposer_cannot_self_accept(self, api):
        """PRD §3.3: 'The acceptor must not be the proposer (otherwise
        ERR_SELF_ACCEPT, HTTP 422)'.

        Claim: Petitioner proposes; Petitioner tries to accept →
        ERR_SELF_ACCEPT.
        """
        ctx = setup_case_with_both_disclosures_accepted()
        plan = propose_parenting_plan(
            ctx["case"]["id"], ctx["petitioner_party_id"],
            actor_role="petitioner",
        )
        res = api.accept_parenting_plan(
            ctx["case"]["id"], plan["id"],
            make_petitioner_headers(ctx["petitioner_party_id"]),
        )
        validate_error(res, "ERR_SELF_ACCEPT", expected_status=422)


# ===========================================================================
# Accept requires disclosures ACCEPTED — PRD §3.3
# ===========================================================================
class TestAcceptRequiresDisclosure:

    def test_accept_without_both_disclosures_accepted_rejected(
        self, api,
    ):
        """PRD §3.3: 'both parties' disclosures must already be in
        ACCEPTED (otherwise ERR_DISCLOSURE_INCOMPLETE, HTTP 409)'.

        Claim: attempt to accept a plan before any disclosure is
        ACCEPTED → ERR_DISCLOSURE_INCOMPLETE.
        """
        case = create_case()
        plan = propose_parenting_plan(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        res = api.accept_parenting_plan(
            case["id"], plan["id"],
            make_respondent_headers(case["respondent_party_id"]),
        )
        validate_error(
            res, "ERR_DISCLOSURE_INCOMPLETE",
            expected_status=409,
        )


# ===========================================================================
# Successful accept — PRD §3.3
# ===========================================================================
class TestAcceptSuccess:

    def test_accept_pins_disclosure_versions(self, api):
        """PRD §3.3: 'On a successful accept the plan transitions to
        AGREED, and the server pins
        pinned_petitioner_disclosure_version and
        pinned_respondent_disclosure_version to the current version of
        each party's accepted disclosure'.

        Claim: AGREED plan carries non-null
        pinned_petitioner_disclosure_version and
        pinned_respondent_disclosure_version.
        """
        ctx = setup_case_with_both_disclosures_accepted()
        plan = propose_parenting_plan(
            ctx["case"]["id"], ctx["petitioner_party_id"],
            actor_role="petitioner",
        )
        agreed = accept_parenting_plan(
            ctx["case"]["id"], plan["id"],
            ctx["respondent_party_id"], actor_role="respondent",
        )
        assert agreed["status"] == "AGREED"
        assert isinstance(agreed.get("pinned_petitioner_disclosure_version"), int)
        assert isinstance(agreed.get("pinned_respondent_disclosure_version"), int)
        assert agreed["pinned_petitioner_disclosure_version"] >= 1
        assert agreed["pinned_respondent_disclosure_version"] >= 1
