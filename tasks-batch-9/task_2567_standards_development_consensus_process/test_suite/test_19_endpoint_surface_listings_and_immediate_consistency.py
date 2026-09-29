"""
The API surface read on its own terms: one clock advance acting on many rows, one
resolve endpoint carrying three actions bound to two item kinds, a listing that
reaches the server's own record of an objection, filters that compose
conjunctively, and a cascade that is fully readable in the very next request.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestOneClockAdvanceMovesManyRows:
    """Promotion is driven by the clock, not by a per-review endpoint."""

    def test_one_advance_promotes_every_scheduled_review_at_once(self, api):
        """
        `StandardsStaff` may set the clock to any ISO 8601 UTC instant by supplying
        `to_iso8601`; the response reports the new `current_utc` together with
        `promoted_public_review_ids`, the identifiers of public reviews that the clock movement
        promoted from a scheduled state to an open one.

        A review left `SCHEDULED` is promoted to `OPEN` when the logical clock is later moved
        to an instant at or after its `start_date`, and the identifiers of every review
        promoted that way are reported back in `promoted_public_review_ids`, each promoted
        review's `version` advancing by 1.

        Design: Corner/endpoints/one_clock_advance_promotes_every_scheduled_public_review_at_once
        """
        scenario = fx.balanced_active_committee(api)

        scenario.propose_work_item("p1", title="Fastener torque specification")
        scenario.approve_scope(designation="STD-1400")
        first_draft = scenario.add_draft(total_clause_count=40, changed_clause_count=0)
        first_ballot = scenario.open_ballot(draft_id=first_draft["id"])
        for seat_key, vote_key in (("m1", "v1"), ("m2", "v2"), ("m3", "v3")):
            scenario.cast(
                seat_key,
                "AFFIRMATIVE",
                ballot_id=first_ballot["id"],
                vote_key=vote_key,
            )
        scenario.close_ballot(first_ballot["id"])

        scenario.propose_work_item("p1", title="Coating thickness specification")
        scenario.approve_scope(designation="STD-1500")
        second_draft = scenario.add_draft(total_clause_count=20, changed_clause_count=0)
        second_ballot = scenario.open_ballot(draft_id=second_draft["id"])
        for seat_key, vote_key in (("m1", "w1"), ("m2", "w2"), ("m3", "w3")):
            scenario.cast(
                seat_key,
                "AFFIRMATIVE",
                ballot_id=second_ballot["id"],
                vote_key=vote_key,
            )
        scenario.close_ballot(second_ballot["id"])

        first_review = scenario.announce_public_review(
            draft_id=first_draft["id"],
            start_date="2026-09-01",
            end_date="2026-10-15",
        )
        second_review = scenario.announce_public_review(
            draft_id=second_draft["id"],
            start_date="2026-09-01",
            end_date="2026-10-15",
        )
        assert first_review["status"] == "SCHEDULED", (
            "a window that has not begun leaves the review scheduled, got "
            f"{first_review['status']}"
        )
        assert second_review["status"] == "SCHEDULED", (
            f"status expected SCHEDULED, got {second_review['status']}"
        )

        advance = scenario.set_clock("2026-09-01T00:00:00Z")

        a.assert_same_instant(advance["current_utc"], "2026-09-01T00:00:00Z")
        assert set(advance["promoted_public_review_ids"]) == {
            first_review["id"],
            second_review["id"],
        }, (
            "one request promoted both reviews, got "
            f"{advance['promoted_public_review_ids']}"
        )
        assert len(advance["promoted_public_review_ids"]) == 2, (
            "each promoted review is reported once, got "
            f"{advance['promoted_public_review_ids']}"
        )
        for review_id in (first_review["id"], second_review["id"]):
            promoted = scenario.get_public_review(review_id)
            assert promoted["status"] == "OPEN", (
                f"review {review_id} is now open, got {promoted['status']}"
            )
            assert promoted["duration_days"] == 45, (
                f"duration_days expected 45, got {promoted['duration_days']}"
            )
        for draft_id in (first_draft["id"], second_draft["id"]):
            assert scenario.get_draft(draft_id)["status"] == "PUBLIC_REVIEW", (
                f"draft {draft_id} is out for comment, got "
                f"{scenario.get_draft(draft_id)['status']}"
            )

        again = scenario.set_clock("2026-09-02T00:00:00Z")

        assert again["promoted_public_review_ids"] == [], (
            "a review is promoted once and once only, got "
            f"{again['promoted_public_review_ids']}"
        )
        a.assert_same_instant(again["current_utc"], "2026-09-02T00:00:00Z")


class TestOneResolveEndpointThreeActions:
    """Each action is bound to an item kind, and only one touches each counter."""

    def test_resolving_an_erratum_report_as_an_interpretation_is_refused(self, api):
        """
        ISSUE_INTERPRETATION is the chair's branch and is available only where `item_kind` is
        `INTERPRETATION_REQUEST`; asking for it on an erratum report is refused with
        `ERR_MAINTENANCE_ACTION_MISMATCH`.

        It moves the item from `RECEIVED` to `ERRATUM_ISSUED` and increments the parent's
        `errata_count` by 1, leaving `interpretation_count` untouched.

        Design: Corner/endpoints/resolving_an_erratum_report_as_an_interpretation_is_refused
        """
        scenario = fx.published_work_item(api)
        before = scenario.get_work_item()
        report = scenario.submit_maintenance_item(
            "p2",
            item_kind="ERRATUM_REPORT",
            question_text="Clause 27 cites a test method that has been withdrawn",
            clause_reference="27",
        )
        assert report["status"] == "RECEIVED", (
            f"the report is on file, got {report['status']}"
        )

        wrong_branch = api.resolve_maintenance_item(
            report["id"],
            f.maintenance_resolution_payload(
                action="ISSUE_INTERPRETATION",
                response_text="The committee reads clause 27 as referring to the successor method",
            ),
            scenario.chair,
        )
        validate_error(wrong_branch, "ERR_MAINTENANCE_ACTION_MISMATCH", 409)

        untouched = scenario.get_maintenance_item(report["id"])
        assert untouched["status"] == "RECEIVED", (
            f"the refusal resolved nothing, got {untouched['status']}"
        )
        assert untouched["resolved_at"] is None, (
            f"resolved_at expected null, got {untouched['resolved_at']}"
        )
        held = scenario.get_work_item()
        assert held["interpretation_count"] == 0, (
            f"interpretation_count expected 0, got {held['interpretation_count']}"
        )
        assert held["errata_count"] == 0, (
            f"errata_count expected 0, got {held['errata_count']}"
        )

        scenario.resolve_maintenance(
            report["id"],
            headers=scenario.staff,
            action="ISSUE_ERRATUM",
            response_text="Clause 27 is corrected to cite the successor method",
            erratum_clause_reference="27",
        )

        resolved = scenario.get_maintenance_item(report["id"])
        assert resolved["status"] == "ERRATUM_ISSUED", (
            f"the matching branch lands, got {resolved['status']}"
        )
        assert resolved["erratum_clause_reference"] == "27", (
            "the corrected clause is stored on the item, got "
            f"{resolved['erratum_clause_reference']}"
        )
        a.assert_same_instant(resolved["resolved_at"], "2026-09-15T00:00:00Z")
        after = scenario.get_work_item()
        assert after["errata_count"] == 1, (
            f"errata_count expected 1, got {after['errata_count']}"
        )
        assert after["interpretation_count"] == 0, (
            "an erratum never moves the interpretation counter, got "
            f"{after['interpretation_count']}"
        )
        a.assert_unchanged(before, after, ["edition", "published_at"])
        assert after["progress_status"] == "PUBLISHED", (
            f"progress_status expected PUBLISHED, got {after['progress_status']}"
        )

    def test_an_erratum_against_an_unpublished_standard_is_refused_but_a_decline_is_not(
        self, api
    ):
        """
        it requires the parent work item's `progress_status` to be `PUBLISHED`, `REAFFIRMED`
        or `UNDER_PERIODIC_REVIEW`, else `ERR_STANDARD_NOT_PUBLISHED` — an erratum cannot be
        issued against text that was never published.

        DECLINE is available for either kind and to either role, requires only a non-empty
        `response_text`, and moves the item from `RECEIVED` to `DECLINED`. It is the branch
        that touches nothing else: neither `errata_count` nor `interpretation_count` changes

        Design: Corner/endpoints/an_erratum_against_an_unpublished_standard_is_refused_while_a_decline_is_not
        """
        scenario = fx.work_item_with_draft(api)
        assert scenario.get_work_item()["progress_status"] == "IN_DEVELOPMENT", (
            "the standard has never been published, got "
            f"{scenario.get_work_item()['progress_status']}"
        )
        report = scenario.submit_maintenance_item(
            "p2",
            item_kind="ERRATUM_REPORT",
            question_text="Clause 27 cites a test method that has been withdrawn",
            clause_reference="27",
        )
        request = scenario.submit_maintenance_item(
            "p3",
            item_kind="INTERPRETATION_REQUEST",
            question_text="Does clause 5 apply to fittings installed before the edition",
            clause_reference="5",
        )

        premature = api.resolve_maintenance_item(
            report["id"],
            f.maintenance_resolution_payload(
                action="ISSUE_ERRATUM",
                response_text="Clause 27 is corrected to cite the successor method",
                erratum_clause_reference="27",
            ),
            scenario.staff,
        )
        validate_error(premature, "ERR_STANDARD_NOT_PUBLISHED", 409)

        held = scenario.get_maintenance_item(report["id"])
        assert held["status"] == "RECEIVED", (
            f"the refusal resolved nothing, got {held['status']}"
        )
        assert held["erratum_clause_reference"] is None, (
            "no corrected clause was recorded, got "
            f"{held['erratum_clause_reference']}"
        )
        assert held["resolved_at"] is None, (
            f"resolved_at expected null, got {held['resolved_at']}"
        )
        assert scenario.get_work_item()["errata_count"] == 0, (
            "errata_count expected 0, got "
            f"{scenario.get_work_item()['errata_count']}"
        )

        scenario.resolve_maintenance(
            request["id"],
            headers=scenario.staff,
            action="DECLINE",
            response_text="The question is outside the scope of the committee",
        )

        declined = scenario.get_maintenance_item(request["id"])
        assert declined["status"] == "DECLINED", (
            "the same endpoint accepts the decline on an unpublished parent, got "
            f"{declined['status']}"
        )
        assert declined["response_text"] == (
            "The question is outside the scope of the committee"
        ), f"the reply is stored on the item, got {declined['response_text']}"
        a.assert_same_instant(declined["resolved_at"], "2026-08-01T00:00:00Z")
        work_item = scenario.get_work_item()
        assert work_item["interpretation_count"] == 0, (
            "a decline moves no interpretation counter, got "
            f"{work_item['interpretation_count']}"
        )
        assert work_item["errata_count"] == 0, (
            f"nor the errata counter, got {work_item['errata_count']}"
        )
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {work_item['progress_status']}"
        )
        items, meta = validate_paginated(
            api.list_maintenance_items(
                scenario.staff, {"work_item_id": scenario.work_item_id}
            )
        )
        a.assert_total_count(meta, 2)
        assert {row["status"] for row in items} == {"RECEIVED", "DECLINED"}, (
            "one item stands unresolved and one is declined, got "
            f"{[row['status'] for row in items]}"
        )


class TestTheCommentsListingReachesTheServersOwnRecord:
    """The objection the server wrote for a negative is a first-class comment."""

    def test_a_ballot_negative_is_reachable_through_its_source_vote(self, api):
        """
        the server itself creates the objection on file as a comment against the ballot's
        draft: that comment's `source_type` is `BALLOT_NEGATIVE`, its `source_vote_id` points
        back at the vote, its `ballot_id` names the ballot, and its `public_review_id` is
        null

        List comments, filterable by draft, ballot, public review, source vote, submitter and
        status.

        Design: Corner/endpoints/the_comments_listing_reaches_a_ballot_negative_through_its_source_vote
        """
        scenario = fx.voted_subcommittee_ballot(api)
        negative_vote = scenario.votes["v3"]

        by_ballot, ballot_meta = validate_paginated(
            api.list_comments(scenario.staff, {"ballot_id": scenario.ballot_id})
        )
        a.assert_total_count(ballot_meta, 1)
        objection = by_ballot[0]
        assert objection["source_type"] == "BALLOT_NEGATIVE", (
            f"source_type expected BALLOT_NEGATIVE, got {objection['source_type']}"
        )
        assert objection["source_vote_id"] == negative_vote["id"], (
            "the objection points back at the vote that raised it, got "
            f"{objection['source_vote_id']}"
        )
        assert objection["ballot_id"] == scenario.ballot_id, (
            f"ballot_id expected the ballot, got {objection['ballot_id']}"
        )
        assert objection["draft_id"] == scenario.draft_id, (
            f"draft_id expected the balloted revision, got {objection['draft_id']}"
        )
        assert objection["public_review_id"] is None, (
            "and it belongs to no public review, got "
            f"{objection['public_review_id']}"
        )
        assert objection["status"] == "OPEN", (
            f"status expected OPEN, got {objection['status']}"
        )

        by_vote, vote_meta = validate_paginated(
            api.list_comments(scenario.staff, {"source_vote_id": negative_vote["id"]})
        )
        a.assert_total_count(vote_meta, 1)
        assert by_vote[0]["id"] == objection["id"], (
            "the source-vote filter reaches the same row, got "
            f"{by_vote[0]['id']} against {objection['id']}"
        )

        disposed, disposed_meta = validate_paginated(
            api.list_comments(
                scenario.staff,
                {"draft_id": scenario.draft_id, "status": "DISPOSED"},
            )
        )
        a.assert_total_count(disposed_meta, 0)
        assert disposed == [], (
            f"nothing on this revision has been disposed of yet, got {disposed}"
        )

        open_on_draft, open_meta = validate_paginated(
            api.list_comments(
                scenario.staff,
                {"draft_id": scenario.draft_id, "status": "OPEN"},
            )
        )
        a.assert_total_count(open_meta, 1)
        assert open_on_draft[0]["id"] == objection["id"], (
            "the draft-and-status pair reaches the objection too, got "
            f"{open_on_draft[0]['id']}"
        )

        negatives, negative_meta = validate_paginated(
            api.list_votes(
                scenario.staff,
                {"ballot_id": scenario.ballot_id, "position": "NEGATIVE"},
            )
        )
        a.assert_total_count(negative_meta, 1)
        assert negatives[0]["id"] == negative_vote["id"], (
            "the votes listing agrees on which seat objected"
        )
        assert negatives[0]["membership_id"] == scenario.mid("m3"), (
            f"membership_id expected the third seat, got {negatives[0]['membership_id']}"
        )


class TestListingFiltersCompose:
    """Two filters narrow to their intersection, and the count precedes the page."""

    def test_the_work_item_listing_composes_its_two_filters_conjunctively(self, api):
        """
        The `meta` block of a list response carries `limit` and `offset` as they were applied,
        `total_count` as the number of rows matching the filters before pagination, and
        `has_more` as a boolean that is true when rows remain beyond the current page.

        List work items, filterable by proposer, sponsoring committee, progress status, IP
        status and consensus gate.

        Design: Corner/endpoints/the_work_item_listing_composes_its_two_filters_conjunctively
        """
        scenario = fx.work_item_with_draft(api)
        developed_id = scenario.work_item_id
        fresh = scenario.propose_work_item("p1", title="Anchor bolt embedment depth")
        fresh_id = fresh["id"]
        assert fresh_id != developed_id, "the second proposal is a distinct work item"

        by_progress, progress_meta = validate_paginated(
            api.list_work_items(scenario.staff, {"progress_status": "IN_DEVELOPMENT"})
        )
        a.assert_total_count(progress_meta, 1)
        assert [row["id"] for row in by_progress] == [developed_id], (
            "only the developed item matches the progress filter, got "
            f"{[row['id'] for row in by_progress]}"
        )

        by_committee, committee_meta = validate_paginated(
            api.list_work_items(
                scenario.staff, {"sponsoring_committee_id": scenario.committee_id}
            )
        )
        a.assert_total_count(committee_meta, 1)
        assert [row["id"] for row in by_committee] == [developed_id], (
            "only the scoped item has a sponsoring committee, got "
            f"{[row['id'] for row in by_committee]}"
        )

        both, both_meta = validate_paginated(
            api.list_work_items(
                scenario.staff,
                {
                    "sponsoring_committee_id": scenario.committee_id,
                    "progress_status": "PROPOSED",
                },
            )
        )
        a.assert_total_count(both_meta, 0)
        assert both == [], (
            "no row satisfies both filters at once, got "
            f"{[row['id'] for row in both]}"
        )
        assert both_meta["has_more"] is False, (
            f"has_more expected false on an empty result, got {both_meta['has_more']}"
        )

        page, page_meta = validate_paginated(
            api.list_work_items(
                scenario.staff,
                {
                    "proposer_participant_id": scenario.pid("p1"),
                    "limit": 1,
                    "offset": 1,
                },
            )
        )
        a.assert_total_count(page_meta, 2)
        assert page_meta["limit"] == 1, (
            f"limit expected 1, got {page_meta['limit']}"
        )
        assert page_meta["offset"] == 1, (
            f"offset expected 1, got {page_meta['offset']}"
        )
        assert page_meta["has_more"] is False, (
            "the second row of two is the last one, got "
            f"{page_meta['has_more']}"
        )
        assert len(page) == 1, (
            f"the page holds a single row, got {len(page)}"
        )
        assert page[0]["id"] == fresh_id, (
            "ascending creation order puts the newer proposal second, got "
            f"{page[0]['id']}"
        )

        unscoped = scenario.get_work_item(fresh_id)
        assert unscoped["progress_status"] == "PROPOSED", (
            f"the fresh proposal is still PROPOSED, got {unscoped['progress_status']}"
        )
        assert unscoped["sponsoring_committee_id"] is None, (
            "and carries no sponsoring committee, got "
            f"{unscoped['sponsoring_committee_id']}"
        )
        assert unscoped["designation"] is None, (
            f"designation expected null, got {unscoped['designation']}"
        )
        assert unscoped["consensus_gate"] == "OPEN", (
            f"consensus_gate expected OPEN, got {unscoped['consensus_gate']}"
        )
        assert unscoped["ip_status"] == "IP_PENDING", (
            f"ip_status expected IP_PENDING, got {unscoped['ip_status']}"
        )


class TestTheCascadeIsReadableImmediately:
    """Every hop of the close cascade has landed before the response is written."""

    def test_every_cascaded_counter_is_readable_in_the_first_request_after_the_close(
        self, api
    ):
        """
        all hops of a cascade complete inside the request that triggered the first one. There
        is no deferred or eventually-consistent settlement anywhere in this specification.

        Design: Corner/consistency_model/every_cascaded_counter_is_readable_in_the_first_request_after_the_close
        """
        scenario = fx.voted_subcommittee_ballot(api)
        negative_vote_id = scenario.votes["v3"]["id"]

        closed = scenario.close_ballot()

        assert closed["status"] == "EVALUATED", (
            "the close response already reports the evaluated ballot, got "
            f"{closed['status']}"
        )
        a.assert_seat_ledger(
            closed,
            affirmative=2,
            negative=1,
            abstain=0,
            returned=3,
            not_returned=0,
            eligible=3,
        )
        a.assert_pct(closed["return_rate_pct"], 100.0)
        a.assert_pct(closed["provisional_approval_pct"], 66.7)
        assert closed["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {closed['pending_negative_count']}"
        )
        assert closed["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            f"consensus_result expected APPROVED_PENDING_NEGATIVES, got "
            f"{closed['consensus_result']}"
        )
        assert closed["final_approval_pct"] is None, (
            f"final_approval_pct expected null, got {closed['final_approval_pct']}"
        )

        vote = scenario.get_vote("v3")
        assert vote["adjudication_status"] == "PENDING", (
            "the very next read finds the negative already awaiting adjudication, got "
            f"{vote['adjudication_status']}"
        )
        draft = scenario.get_draft()
        assert draft["status"] == "COMMENT_RESOLUTION", (
            f"and the draft already moved, got {draft['status']}"
        )
        assert draft["unresolved_negative_count"] == 1, (
            f"unresolved_negative_count expected 1, got {draft['unresolved_negative_count']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["unresolved_negative_count"] == 1, (
            "the third hop is on file too, got "
            f"{work_item['unresolved_negative_count']}"
        )
        assert work_item["consensus_gate"] == "BLOCKED", (
            f"consensus_gate expected BLOCKED, got {work_item['consensus_gate']}"
        )
        objections, objection_meta = validate_paginated(
            api.list_comments(scenario.staff, {"source_vote_id": negative_vote_id})
        )
        a.assert_total_count(objection_meta, 1)
        assert objections[0]["status"] == "OPEN", (
            f"the objection is reachable and open, got {objections[0]['status']}"
        )

        assert scenario.get_ballot() == closed, (
            "re-reading the ballot returns the identical payload the close reported"
        )
        assert scenario.get_vote("v3") == vote, (
            "and so does re-reading the vote"
        )
        assert scenario.get_work_item() == work_item, (
            "nothing settled late on the work item either"
        )
