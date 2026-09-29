"""
The two dimensions that run alongside development: the appeal window, counted to
the instant from an anchor that must actually exist, and patent clearance, an
any-blocking aggregate whose meaning changes the moment the call for patents
closes.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestTheDeadlineInstantIsInclusive:
    """Thirty days after the close, to the instant, is still timely."""

    def test_an_appeal_filed_at_exactly_the_deadline_is_accepted(self, api):
        """
        Given an anchor, `filing_deadline_at` is that anchor instant advanced by 30 days, and
        a filing is timely when the logical clock is at or before that deadline — the deadline
        instant itself is timely. A ballot that closed at `2026-09-15T00:00:00Z` therefore
        yields a `filing_deadline_at` of `2026-10-15T00:00:00Z`; a filing at exactly that
        instant is accepted, and a filing one second later is refused with
        `ERR_APPEAL_UNTIMELY`.

        Design: Corner/calculations/an_appeal_filed_at_exactly_the_deadline_instant_is_timely
        """
        scenario = fx.published_work_item(api)
        consensus_ballot_id = scenario.ballot_id
        a.assert_same_instant(
            scenario.get_ballot(consensus_ballot_id)["closed_at"],
            "2026-09-15T00:00:00Z",
        )
        published = scenario.get_work_item()
        assert published["progress_status"] == "PUBLISHED", (
            f"the standard is out, got {published['progress_status']}"
        )
        assert published["consensus_gate"] == "OPEN", (
            f"nothing is holding the work item yet, got {published['consensus_gate']}"
        )

        scenario.set_clock("2026-10-15T00:00:00Z")
        appeal = scenario.file_appeal(
            "p2",
            cited_ballot_id=consensus_ballot_id,
            grounds="VOTING_PROCEDURE_DEFECT",
            statement="The tally was announced before the negative deadline",
        )

        a.assert_has_fields(appeal, "Appeal")
        assert appeal["status"] == "FILED", (
            f"the filing at the deadline instant is accepted, got {appeal['status']}"
        )
        assert appeal["remedy"] == "NONE", (
            f"a fresh appeal carries no remedy, got {appeal['remedy']}"
        )
        a.assert_same_instant(appeal["filed_at"], "2026-10-15T00:00:00Z")
        a.assert_same_instant(appeal["filing_deadline_at"], "2026-10-15T00:00:00Z")
        assert appeal["decided_at"] is None, (
            f"nothing has been decided, got {appeal['decided_at']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["consensus_gate"] == "BLOCKED", (
            "merely filing the appeal is a stop-work order, got "
            f"{work_item['consensus_gate']}"
        )
        assert work_item["progress_status"] == "PUBLISHED", (
            "the filing moves no progress dimension, got "
            f"{work_item['progress_status']}"
        )

    def test_an_appeal_one_second_past_the_deadline_is_untimely(self, api):
        """
        a filing is timely when the logical clock is at or before that deadline — the deadline
        instant itself is timely. A ballot that closed at `2026-09-15T00:00:00Z` therefore
        yields a `filing_deadline_at` of `2026-10-15T00:00:00Z`; a filing at exactly that
        instant is accepted, and a filing one second later is refused with
        `ERR_APPEAL_UNTIMELY`.

        Design: Corner/validations/an_appeal_one_second_past_the_deadline_instant_is_untimely
        """
        scenario = fx.published_work_item(api)
        consensus_ballot_id = scenario.ballot_id

        scenario.set_clock("2026-10-15T00:00:01Z")
        response = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                scenario.pid("p2"),
                cited_ballot_id=consensus_ballot_id,
                grounds="VOTING_PROCEDURE_DEFECT",
                statement="The tally was announced before the negative deadline",
            ),
            scenario.member("p2"),
        )
        validate_error(response, "ERR_APPEAL_UNTIMELY", 409)

        appeals, meta = validate_paginated(
            api.list_appeals(scenario.staff, {"work_item_id": scenario.work_item_id})
        )
        a.assert_total_count(meta, 0)
        assert appeals == [], f"the late filing stored nothing, got {appeals}"
        work_item = scenario.get_work_item()
        assert work_item["consensus_gate"] == "OPEN", (
            "a rejected filing never gates the work item, got "
            f"{work_item['consensus_gate']}"
        )
        assert work_item["progress_status"] == "PUBLISHED", (
            f"progress_status expected PUBLISHED, got {work_item['progress_status']}"
        )
        a.assert_same_instant(
            scenario.get_ballot(consensus_ballot_id)["closed_at"],
            "2026-09-15T00:00:00Z",
        )


class TestTheWindowNeedsSomethingToCountFrom:
    """Neither an open ballot nor an unpublished work item is an anchor."""

    def test_an_appeal_citing_a_still_open_ballot_has_no_anchor(self, api):
        """
        When `cited_ballot_id` is supplied, the anchor is that ballot's `closed_at`; when it is
        omitted, the anchor is the work item's `published_at`. If the cited ballot has no
        `closed_at` — which is the case for a ballot still `OPEN` and for one that was
        `VACATED` — or if no ballot was cited and the work item has never been published,
        there is nothing to count from and the filing is refused with
        `ERR_APPEAL_ANCHOR_MISSING`.

        Design: Corner/validations/an_appeal_citing_a_still_open_ballot_has_no_timing_anchor
        """
        scenario = fx.open_subcommittee_ballot(api)
        assert scenario.get_ballot()["closed_at"] is None, (
            "the cited ballot is still running"
        )
        assert scenario.get_work_item()["published_at"] is None, (
            "and the work item has never been published"
        )
        assert scenario.get_membership("m2")["status"] == "ACTIVE", (
            "the appellant holds an active seat, so standing is not the problem"
        )

        citing_open_ballot = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                scenario.pid("p2"),
                cited_ballot_id=scenario.ballot_id,
                grounds="VOTING_PROCEDURE_DEFECT",
                statement="The ballot window was announced with the wrong closing date",
            ),
            scenario.member("p2"),
        )
        validate_error(citing_open_ballot, "ERR_APPEAL_ANCHOR_MISSING", 409)

        citing_nothing = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                scenario.pid("p2"),
                grounds="BALANCE_VIOLATION",
                statement="The committee roster is packed by one employer",
            ),
            scenario.member("p2"),
        )
        validate_error(citing_nothing, "ERR_APPEAL_ANCHOR_MISSING", 409)

        appeals, meta = validate_paginated(
            api.list_appeals(scenario.staff, {"work_item_id": scenario.work_item_id})
        )
        a.assert_total_count(meta, 0)
        assert appeals == [], f"neither filing was stored, got {appeals}"
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "a rejected filing never gates the work item, got "
            f"{scenario.get_work_item()['consensus_gate']}"
        )
        ballot = scenario.get_ballot()
        assert ballot["closed_at"] is None, (
            f"closed_at expected null, got {ballot['closed_at']}"
        )
        assert ballot["hold_reason"] == "NONE", (
            "no hold was placed by a refused appeal, got "
            f"{ballot['hold_reason']}"
        )


class TestTheDisclosureTokenGuardsACalculation:
    """The version a discloser read before the draft existed is stale after it."""

    def test_a_work_item_version_read_before_the_draft_existed_is_stale(self, api):
        """
        Recording a disclosure re-evaluates patent clearance and can move the work item's
        `ip_status` to `IP_BLOCKED`, which in turn changes what publication will accept;
        because that outcome depends on the disclosures already on file, the caller must
        present the version it read. A mismatch is rejected with
        `ERR_STALE_WORK_ITEM_VERSION` (HTTP 412), leaving no patent disclosure row and no
        change to `ip_status`. A work item's `version` is advanced by scope approval, draft
        creation, ballot cascades, disclosure recording, commitment recording, publication,
        periodic-review actions and maintenance resolutions.

        Design: Corner/cross_cutting_complexity_layers/a_work_item_version_observed_before_the_draft_existed_is_rejected_as_stale
        """
        scenario = fx.work_item_in_development(api)
        stale_version = scenario.get_work_item()["version"]
        scenario.add_draft(total_clause_count=40, changed_clause_count=0)
        fresh_version = scenario.get_work_item()["version"]
        assert fresh_version > stale_version, (
            "creating the revision advanced the work item, got "
            f"{fresh_version} against {stale_version}"
        )

        stale = api.create_patent_disclosure(
            f.patent_disclosure_payload(
                scenario.work_item_id,
                scenario.pid("p2"),
                stale_version,
                patent_number="US-4444444",
                essentiality="ESSENTIAL",
            ),
            scenario.member("p2"),
        )
        validate_error(stale, "ERR_STALE_WORK_ITEM_VERSION", 412)

        rows, meta = validate_paginated(
            api.list_patent_disclosures(
                scenario.staff, {"work_item_id": scenario.work_item_id}
            )
        )
        a.assert_total_count(meta, 0)
        assert rows == [], f"the rejected disclosure stored nothing, got {rows}"
        refused = scenario.get_work_item()
        assert refused["ip_status"] == "IP_PENDING", (
            "nobody has spoken on patents yet, got "
            f"{refused['ip_status']}"
        )
        assert refused["consensus_gate"] == "OPEN", (
            f"consensus_gate expected OPEN, got {refused['consensus_gate']}"
        )

        disclosure = scenario.disclose_patent(
            "p2",
            expected_work_item_version=fresh_version,
            patent_number="US-4444444",
            essentiality="ESSENTIAL",
            headers=scenario.member("p2"),
        )

        assert disclosure["status"] == "DISCLOSED_NO_COMMITMENT", (
            "the re-read token carries the identical body through, got "
            f"{disclosure['status']}"
        )
        assert disclosure["blocks_publication"] is True, (
            "an essential patent with no commitment blocks, got "
            f"{disclosure['blocks_publication']}"
        )
        assert disclosure["committed_at"] is None, (
            f"committed_at expected null, got {disclosure['committed_at']}"
        )
        assert disclosure["commitment_letter_ref"] is None, (
            f"commitment_letter_ref expected null, got {disclosure['commitment_letter_ref']}"
        )
        after = scenario.get_work_item()
        assert after["ip_status"] == "IP_BLOCKED", (
            f"the intellectual-property dimension moved, got {after['ip_status']}"
        )
        assert after["progress_status"] == "IN_DEVELOPMENT", (
            "and the progress dimension did not, got "
            f"{after['progress_status']}"
        )


class TestClearanceIsNotTheSameAsUnblocking:
    """A commitment lifts a block; only a closed call for patents clears the field."""

    def test_a_rand_commitment_returns_the_work_item_to_disclosed(self, api):
        """
        So: if any disclosure on the work item has `blocks_publication` true, `ip_status` is
        `IP_BLOCKED`; otherwise, if the call for patents has closed, `ip_status` is
        `IP_CLEARED`; otherwise, if the work item has no disclosures at all, `ip_status` is
        `IP_PENDING`; otherwise `ip_status` is `IP_DISCLOSED`.

        A commitment of `RAND`, `RAND_ZERO` or `WITHDRAW` that leaves no blocking disclosure
        on the work item moves `IP_BLOCKED` back to `IP_DISCLOSED`

        Design: Corner/calculations/a_rand_commitment_lifts_the_block_without_granting_clearance
        """
        scenario = fx.work_item_with_draft(api)
        assert scenario.get_work_item()["ip_status"] == "IP_PENDING", (
            "no disclosures are on file yet"
        )

        harmless = scenario.disclose_patent(
            "p2",
            patent_number="US-1111111",
            essentiality="NON_ESSENTIAL",
            headers=scenario.member("p2"),
        )

        assert harmless["blocks_publication"] is False, (
            "a non-essential patent never blocks, got "
            f"{harmless['blocks_publication']}"
        )
        assert scenario.get_work_item()["ip_status"] == "IP_DISCLOSED", (
            "somebody has spoken, but nothing blocks, got "
            f"{scenario.get_work_item()['ip_status']}"
        )

        blocking = scenario.disclose_patent(
            "p3",
            patent_number="US-2222222",
            essentiality="ESSENTIAL",
            headers=scenario.member("p3"),
        )

        assert blocking["status"] == "DISCLOSED_NO_COMMITMENT", (
            f"the second disclosure arrives uncommitted, got {blocking['status']}"
        )
        assert blocking["blocks_publication"] is True, (
            f"blocks_publication expected true, got {blocking['blocks_publication']}"
        )
        assert scenario.get_work_item()["ip_status"] == "IP_BLOCKED", (
            "one blocking disclosure is enough, got "
            f"{scenario.get_work_item()['ip_status']}"
        )

        scenario.commit_licence(
            disclosure_id=blocking["id"],
            commitment="RAND",
            commitment_letter_ref="LTR-2026-88",
            headers=scenario.member("p3"),
        )

        committed = scenario.get_disclosure(blocking["id"])
        assert committed["status"] == "RAND_COMMITTED", (
            f"the commitment maps onto the status, got {committed['status']}"
        )
        assert committed["commitment_letter_ref"] == "LTR-2026-88", (
            "the filed letter is recorded, got "
            f"{committed['commitment_letter_ref']}"
        )
        assert committed["blocks_publication"] is False, (
            f"the block is lifted, got {committed['blocks_publication']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["ip_status"] == "IP_DISCLOSED", (
            "lifting a block is not clearance while the call for patents is open, got "
            f"{work_item['ip_status']}"
        )
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {work_item['progress_status']}"
        )

    def test_a_late_essential_patent_blocks_publication_until_the_letter_lands(self, api):
        """
        A late blocking disclosure filed after consensus approval moves `IP_CLEARED` to
        `IP_BLOCKED` — the edge that makes intellectual property a real gate, since
        publication is then refused with `ERR_IP_NOT_CLEARED`.

        The very same commitment, on a work item whose call for patents has already closed,
        moves `IP_BLOCKED` directly to `IP_CLEARED` instead: unblocking a late essential
        patent on an already consensus-approved standard clears intellectual property outright
        rather than dropping back to `IP_DISCLOSED`, and that is precisely what lets
        publication resume.

        Design: Corner/validations/publishing_with_an_uncommitted_essential_patent_is_blocked_until_the_letter_lands
        """
        scenario = fx.consensus_approved_work_item(api)
        approved = scenario.get_work_item()
        assert approved["progress_status"] == "CONSENSUS_APPROVED", (
            f"the consensus cycle is complete, got {approved['progress_status']}"
        )
        assert approved["ip_status"] == "IP_CLEARED", (
            "consensus approval closed the call for patents on an empty field, got "
            f"{approved['ip_status']}"
        )

        late = scenario.disclose_patent(
            "p2",
            patent_number="US-3333333",
            essentiality="ESSENTIAL",
            headers=scenario.member("p2"),
        )
        assert scenario.get_work_item()["ip_status"] == "IP_BLOCKED", (
            "clearance is no one-way latch, got "
            f"{scenario.get_work_item()['ip_status']}"
        )

        refused = api.publish_work_item(scenario.work_item_id, scenario.staff)
        validate_error(refused, "ERR_IP_NOT_CLEARED", 409)

        held = scenario.get_work_item()
        assert held["ip_status"] == "IP_BLOCKED", (
            f"ip_status expected IP_BLOCKED, got {held['ip_status']}"
        )
        assert scenario.get_disclosure(late["id"])["blocks_publication"] is True, (
            "the blockage is attributable to the one patent"
        )
        assert held["progress_status"] == "CONSENSUS_APPROVED", (
            f"the refusal published nothing, got {held['progress_status']}"
        )
        assert held["published_at"] is None, (
            f"published_at expected null, got {held['published_at']}"
        )
        assert held["consensus_gate"] == "OPEN", (
            "the procedural gate and the patent dimension are independent, got "
            f"{held['consensus_gate']}"
        )

        scenario.commit_licence(
            disclosure_id=late["id"],
            commitment="RAND_ZERO",
            commitment_letter_ref="LTR-2026-91",
            headers=scenario.member("p2"),
        )

        committed = scenario.get_disclosure(late["id"])
        assert committed["status"] == "RAND_ZERO_COMMITTED", (
            f"the royalty-free letter lands, got {committed['status']}"
        )
        assert committed["blocks_publication"] is False, (
            f"blocks_publication expected false, got {committed['blocks_publication']}"
        )
        assert scenario.get_work_item()["ip_status"] == "IP_CLEARED", (
            "the call for patents closed at consensus approval, so unblocking clears, got "
            f"{scenario.get_work_item()['ip_status']}"
        )

        published = scenario.publish()

        assert published["progress_status"] == "PUBLISHED", (
            f"the identical publish call now succeeds, got {published['progress_status']}"
        )
        a.assert_same_instant(published["published_at"], "2026-09-15T00:00:00Z")
        assert published["periodic_review_due_date"] == "2031-09-15", (
            "publication anchors the five-year review, got "
            f"{published['periodic_review_due_date']}"
        )
