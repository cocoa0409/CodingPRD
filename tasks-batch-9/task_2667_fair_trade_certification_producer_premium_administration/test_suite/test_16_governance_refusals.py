"""What the premium governance machine turns away: a second committee, a vote before
the money is there, a vote while the holder is out, an unapproved use and a second ballot.
"""

from test_helpers import (
    CHAIR,
    CHAIR_1_ID,
    CHAIR_2_ID,
    MEMBER_1,
    MEMBER_1_ID,
    OFFICER,
    api_errors as E,
    assert_clock_stamp,
    assert_fund_partition,
    assert_money,
    assert_pct,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)


def _committee_over_an_eight_hundred_thousand_cent_fund(api, approved_use_categories=None):
    """A FORMING committee whose fund holds 800000 cents from one 10000 kg shipment."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(
        api, chain["producer_id"], approved_use_categories=approved_use_categories
    )
    chain["committee_id"] = committee["id"]
    chain["committee_version"] = committee["version"]
    chain["trade"] = f.record_settled_trade(api, chain, 10000)
    return chain


class TestOnlyOneCommitteePerEligibleHolder:
    """A cooperative governs its premium through exactly one standing committee."""

    def test_a_rival_committee_and_a_brands_committee_are_both_turned_away(self, api, clock):
        """A second committee for the cooperative that already has one is refused, and so is
        a committee for the roaster, which has no premium of its own to govern.

        Design: Corner/validations/second_committee_for_a_holder_and_a_committee_for_a_brand_are_both_rejected
        """
        chain = f.build_certified_chain(api, harvest_kg=None)
        committee = f.constitute_committee(api, chain["producer_id"])

        rival = api.create_committee(
            f.committee_payload(
                chain["producer_id"], chair_user_id=CHAIR_2_ID, member_count=7,
                approved_use_categories=["HEALTHCARE"],
            ),
            OFFICER,
        )
        for_a_brand = api.create_committee(
            f.committee_payload(
                chain["brand_id"], chair_user_id="chair-3", member_count=5,
                approved_use_categories=["EDUCATION"],
            ),
            OFFICER,
        )

        validate_error(rival, E.ERR_COMMITTEE_ALREADY_EXISTS, 409)
        validate_error(for_a_brand, E.ERR_COMMITTEE_ALREADY_EXISTS, 409)
        rows, meta = validate_paginated(
            api.list_holder_committees(chain["producer_id"], OFFICER)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == committee["id"]
        assert rows[0]["chair_user_id"] == CHAIR_1_ID
        brand_rows, brand_meta = validate_paginated(
            api.list_holder_committees(chain["brand_id"], OFFICER)
        )
        assert brand_meta["total_count"] == 0 and brand_rows == []
        standing = f.read_committee(api, committee["id"])
        assert standing["member_count"] == 5, "the refused create changed nothing"
        assert standing["approved_use_categories"] == ["EDUCATION"]


class TestAVoteNeedsAGoverningCommitteeAndACertifiedHolder:
    """Drafting is open to a young committee; balloting is not."""

    def test_a_round_cannot_be_opened_while_the_fund_is_below_the_threshold(self, api, clock):
        """The cooperative has real premium but not yet the million cents that puts its
        committee in charge, so the school roof plan stays on the drafting table.

        Design: Corner/validations/open_vote_on_a_forming_committee_is_rejected
        """
        chain = _committee_over_an_eight_hundred_thousand_cent_fund(api)
        proposal = f.draft_proposal(api, chain, 500000)

        response = api.open_vote(proposal["id"], CHAIR)

        validate_error(response, E.ERR_COMMITTEE_NOT_ACTIVE, 409)
        assert f.read_committee(api, chain["committee_id"])["status"] == "FORMING"
        after = f.read_proposal(api, proposal["id"])
        assert after["status"] == "DRAFT"
        assert after["current_round"] == 0
        assert_pct(after["turnout_pct"], "0.00", "turnout_pct")
        assert_pct(after["approval_pct"], "0.00", "approval_pct")
        fund = f.read_fund(api, chain["producer_id"])
        assert_money(fund["balance_cents"], 800000, "balance_cents")
        assert fund["pending_proposal_count"] == 1

    def test_a_round_cannot_be_opened_while_the_cooperative_is_suspended(self, api, clock):
        """The committee is fully in charge, but its cooperative has lost its certificate,
        so the refusal names the holder rather than the committee.

        Design: Corner/validations/open_vote_while_the_holder_is_suspended_is_rejected
        """
        chain = f.build_funded_committee(api)
        proposal = f.draft_proposal(api, chain, 500000)
        validate_success(
            api.suspend_holder(chain["producer_id"], f.reason_payload("MANUAL"), OFFICER), 200
        )

        response = api.open_vote(proposal["id"], CHAIR)

        validate_error(response, E.ERR_HOLDER_NOT_CERTIFIED, 409)
        assert f.read_committee(api, chain["committee_id"])["status"] == "ACTIVE", (
            "the committee itself is in order, so the block came from the holder"
        )
        holder = f.read_holder(api, chain["producer_id"])
        assert holder["certificate_status"] == "SUSPENDED"
        assert holder["suspension_reason"] == "MANUAL"
        after = f.read_proposal(api, proposal["id"])
        assert after["status"] == "DRAFT" and after["current_round"] == 0
        assert f.read_node(api, chain["seller_node_id"])["status"] == "SUSPENDED"
        assert f.read_trade(api, chain["trade_id"])["settlement_status"] == "SETTLED", (
            "money already paid out is not unwound by a suspension"
        )


class TestWhatThePremiumMayBeSpentOn:
    """A committee may only propose spending inside the mandate it was given."""

    def test_a_clinic_is_refused_where_only_schools_and_works_were_approved(self, api, clock):
        """The healthcare plan is outside the mandate; the drying patio is inside it, and it
        is still accepted against the fund version the refused plan quoted.

        Design: Corner/validations/proposal_in_a_category_the_committee_never_approved_is_rejected
        """
        chain = _committee_over_an_eight_hundred_thousand_cent_fund(
            api, ["EDUCATION", "INFRASTRUCTURE"]
        )
        fund_version = f.read_fund(api, chain["producer_id"])["version"]

        refused = api.create_proposal(
            f.proposal_payload(
                chain["committee_id"], fund_version, 300000, title="Village clinic",
                use_category="HEALTHCARE", use_period_start="2026-09-01",
                use_period_end="2026-12-01",
            ),
            CHAIR,
        )

        validate_error(refused, E.ERR_USE_CATEGORY_NOT_APPROVED, 422)
        accepted = validate_success(
            api.create_proposal(
                f.proposal_payload(
                    chain["committee_id"], fund_version, 300000, title="Drying patio",
                    use_category="INFRASTRUCTURE", use_period_start="2026-09-01",
                    use_period_end="2026-12-01",
                ),
                CHAIR,
            ),
            201,
        )
        assert accepted["status"] == "DRAFT"
        assert accepted["use_category"] == "INFRASTRUCTURE"
        assert f.read_committee(api, chain["committee_id"])["open_proposal_count"] == 1
        fund = f.read_fund(api, chain["producer_id"])
        assert fund["pending_proposal_count"] == 1, "the refused plan was never counted"
        assert fund["version"] == fund_version + 1, (
            "only the accepted draft moved the fund on, which is why it could reuse the "
            "version the refused one quoted"
        )

    def test_a_plan_for_every_last_cent_in_the_fund_is_accepted(self, api, clock):
        """Sufficiency is measured with an inclusive comparison, so a plan for the entire
        balance goes through, and drafting still commits nothing.

        Design: Corner/validations/proposal_for_exactly_the_available_balance_is_accepted
        """
        chain = _committee_over_an_eight_hundred_thousand_cent_fund(api)
        fund_version = f.read_fund(api, chain["producer_id"])["version"]

        proposal = validate_success(
            api.create_proposal(
                f.proposal_payload(
                    chain["committee_id"], fund_version, 800000,
                    title="Whole fund to schools", use_period_start="2026-09-01",
                    use_period_end="2026-12-01",
                ),
                CHAIR,
            ),
            201,
        )

        assert proposal["status"] == "DRAFT"
        assert_money(proposal["requested_amount_cents"], 800000, "requested_amount_cents")
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(
            fund, total_accrued_cents=800000, balance_cents=800000,
            committed_cents=0, disbursed_cents=0,
        )
        assert fund["pending_proposal_count"] == 1
        assert fund["version"] == fund_version + 1
        committee = f.read_committee(api, chain["committee_id"])
        assert committee["open_proposal_count"] == 1
        assert committee["status"] == "FORMING"


class TestOneBallotPerMemberPerRound:
    """A member who has voted in this round has finished voting in this round."""

    def test_a_member_who_changes_his_mind_cannot_replace_his_ballot(self, api, clock):
        """The second ballot is refused outright rather than overwriting the first, and the
        tally still reads one approval out of five elected members.

        Design: Corner/validations/second_ballot_from_the_same_member_in_one_round_is_rejected
        """
        chain = f.build_funded_committee(api)
        proposal = f.draft_proposal(api, chain, 500000)
        validate_success(api.open_vote(proposal["id"], CHAIR), 200)
        f.cast_ballots(api, proposal["id"], ["APPROVE"])

        response = api.cast_vote(
            proposal["id"], f.vote_payload("REJECT", "Changed my mind"), MEMBER_1
        )

        validate_error(response, E.ERR_DUPLICATE_VOTE, 409)
        rows, meta = validate_paginated(api.list_proposal_votes(proposal["id"], OFFICER))
        assert meta["total_count"] == 1 and len(rows) == 1
        surviving = rows[0]
        assert surviving["voter_user_id"] == MEMBER_1_ID
        assert surviving["ballot"] == "APPROVE", "the first ballot stands"
        assert surviving["round_number"] == 1
        assert_clock_stamp(surviving["cast_at"], clock, "cast_at")
        after = f.read_proposal(api, proposal["id"])
        assert_pct(after["turnout_pct"], "20.00", "turnout_pct")
        assert_pct(after["approval_pct"], "100.00", "approval_pct")
        assert after["status"] == "UNDER_VOTE"
        assert after["current_round"] == 1
