"""Difficulty queue: cross-entity state dependencies (Motion->Committee, ExitValuation->Motion)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    adopt_buyout_approval,
    api_client,
    appraise_valuation,
    charter_amendment_payload,
    create_committee,
    create_motion,
    create_policy,
    create_shareholder,
    finalize_exit,
    get_committee,
    get_exit_valuation,
    get_motion,
    get_physician,
    initiate_exit,
    make_physician_headers,
    open_motion,
    propose_motion,
    remove_member,
    validate_error,
)


class TestCharterAmendmentOpenRequiresActiveCommittee:
    def test_impaired_committee_blocks_open(self, api):
        """PRD §3.4: "Opening a `CHARTER_AMENDMENT` has one extra gate: the referenced
        committee must be `ACTIVE`, otherwise `ERR_COMMITTEE_IMPAIRED`."
        PRD §3.3: "a removal that drops the count below quorum moves it from `ACTIVE`
        to `IMPAIRED`"

        Design: Difficulty/cross_entity_state_dependency/charter_amendment_open_requires_active_committee
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        committee = create_committee(
            name="Compensation Committee", committee_type="COMPENSATION", quorum_count=1
        )
        add_member(committee["id"], a["id"], "CHAIR")
        remove_member(committee["id"], a["id"])
        impaired = get_committee(committee["id"])
        assert impaired["status"] == "IMPAIRED", "Setup failed: removal below quorum must impair"

        motion = create_motion(
            "CHARTER_AMENDMENT", a, charter_amendment_payload(new_quorum_count=1),
            committee_id=committee["id"],
        )
        propose_motion(motion["id"], a)
        resp = api_client.open_motion(motion["id"], make_physician_headers(a["id"]))
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_IMPAIRED)
        assert get_motion(motion["id"])["status"] == "PROPOSED"

    def test_restored_membership_unblocks_open(self, api):
        """PRD §3.3: "Adding members until the count reaches quorum moves the
        committee from `CHARTERED` to `ACTIVE`; a removal that drops the count below
        quorum moves it from `ACTIVE` to `IMPAIRED`, and adding back to quorum restores
        it from `IMPAIRED` to `ACTIVE`."
        PRD §3.4: "Opening snapshots the eligible electorate: `eligible_voter_ids` is
        the set of physicians who are `SHAREHOLDER` and `GOOD_STANDING` at that
        instant"

        Design: Difficulty/cross_entity_state_dependency/charter_amendment_open_requires_active_committee
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        committee = create_committee(
            name="Compensation Committee", committee_type="COMPENSATION", quorum_count=1
        )
        add_member(committee["id"], a["id"], "CHAIR")
        remove_member(committee["id"], a["id"])
        motion = create_motion(
            "CHARTER_AMENDMENT", a, charter_amendment_payload(new_quorum_count=1),
            committee_id=committee["id"],
        )
        propose_motion(motion["id"], a)
        resp = api_client.open_motion(motion["id"], make_physician_headers(a["id"]))
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_IMPAIRED)

        add_member(committee["id"], a["id"], "CHAIR")
        restored = get_committee(committee["id"])
        assert restored["status"] == "ACTIVE", "IMPAIRED -> ACTIVE once quorum restored"

        opened = open_motion(motion["id"], a)
        assert opened["status"] == "OPEN"
        assert opened["eligible_voter_count"] == 1
        assert opened["eligible_voter_ids"] == [a["id"]]


class TestExitFinalizeRequiresAdoptedBuyoutMotion:
    def _setup_appraised_exit(self):
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        t = create_shareholder("Dr T", 1000, "2011-01-01T00:00:00Z")
        valuation = initiate_exit(x["id"], "RETIREMENT")
        appraised = appraise_valuation(valuation, 90000000)
        return x, t, appraised

    def test_finalize_with_proposed_motion_rejected(self, api):
        """PRD §3.6: "The referenced motion must be an `ADOPTED` `BUYOUT_APPROVAL`
        motion whose payload's `exit_valuation_id` names this valuation, and it must
        not already have been consumed by another finalize — otherwise
        `ERR_BUYOUT_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/exit_finalize_requires_adopted_buyout_motion
        """
        x, t, appraised = self._setup_appraised_exit()
        motion = create_motion(
            "BUYOUT_APPROVAL", t, {"exit_valuation_id": appraised["id"]}
        )
        propose_motion(motion["id"], t)
        resp = api_client.finalize_exit_valuation(
            appraised["id"], {"motion_id": motion["id"]},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BUYOUT_NOT_APPROVED)
        assert get_exit_valuation(appraised["id"])["status"] == "APPRAISED"
        assert get_physician(x["id"])["partnership_status"] == "EXITING"

    def test_finalize_with_adopted_motion_succeeds(self, api):
        """PRD §3.6: "Finalization sets `approving_motion_id`, computes
        `payment_schedule_cents` — 40 percent of `final_value_cents` at finalization,
        30 percent at plus 12 months, 30 percent at plus 24 months, the first two
        entries rounded half-up and the last entry absorbing the rounding residue — and
        fires the exit cascade in three links. First, the physician moves from
        `EXITING` to `EXITED`, `shares_held` goes to 0, and the returned shares flow
        back to `treasury_shares`."
        final = round(90000000 * 0.5 * 0.85) = 38250000 -> [15300000, 11475000, 11475000].

        Design: Difficulty/cross_entity_state_dependency/exit_finalize_requires_adopted_buyout_motion
        """
        x, t, appraised = self._setup_appraised_exit()
        motion = adopt_buyout_approval(t, appraised["id"])
        finalized = finalize_exit(appraised["id"], motion["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["approving_motion_id"] == motion["id"]
        assert finalized["payment_schedule_cents"] == [15300000, 11475000, 11475000]
        assert get_physician(x["id"])["partnership_status"] == "EXITED"
