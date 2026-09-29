"""
What a stored row looks like when it comes back: the fields a creation echoes,
the counters a committee persists, the page metadata a listing reports, and the
values the server supplies when the client leaves an optional field out.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestStoredRepresentations:
    """A creation echoes what it was given; a retrieval echoes what was derived."""

    def test_participant_registration_echoes_every_declared_field(
        self, api, staff_headers
    ):
        """
        Registering a participant records their `full_name` (a non-blank string of 1 to
        120 characters), their `organization` (a non-blank string of 1 to 160
        characters, free text naming the employer or represented body), their
        `interest_category` — one of `PRODUCER`, `USER`, `GENERAL_INTEREST`,
        `REGULATORY` or `ACADEMIC` — and optionally their `employer_affiliation_code`,
        a group code of 1 to 32 characters that defaults to null when omitted.

        Design: Corner/entities/participant_creation_returns_all_declared_input_fields
        """
        data = validate_success(
            api.create_participant(
                f.participant_payload(
                    full_name="Ada Producer",
                    organization="Acme Steel",
                    interest_category="PRODUCER",
                    employer_affiliation_code="ACME",
                ),
                staff_headers,
            ),
            201,
        )

        a.assert_has_fields(data, "Participant")
        assert data["full_name"] == "Ada Producer", (
            f"full_name expected Ada Producer, got {data['full_name']}"
        )
        assert data["organization"] == "Acme Steel", (
            f"organization expected Acme Steel, got {data['organization']}"
        )
        assert data["interest_category"] == "PRODUCER", (
            f"interest_category expected PRODUCER, got {data['interest_category']}"
        )
        assert data["employer_affiliation_code"] == "ACME", (
            "the optional affiliation code is stored as supplied, got "
            f"{data['employer_affiliation_code']}"
        )
        a.assert_common_fields(data, expected_version=1)
        a.assert_same_instant(data["created_at"], "2026-08-01T00:00:00Z")
        a.assert_same_instant(data["updated_at"], "2026-08-01T00:00:00Z")

        unaffiliated = validate_success(
            api.create_participant(
                f.participant_payload(
                    full_name="Zoe Outsider",
                    organization="Unaffiliated Consultancy",
                    interest_category="ACADEMIC",
                    employer_affiliation_code=None,
                ),
                staff_headers,
            ),
            201,
        )
        assert unaffiliated["employer_affiliation_code"] is None, (
            "an omitted affiliation code defaults to null, got "
            f"{unaffiliated['employer_affiliation_code']}"
        )

    def test_committee_retrieval_reports_its_persisted_balance_counters(self, api):
        """
        Both label groups, together with `active_member_count`, `roster_member_count`,
        `dominance_pct`, `roster_dominance_pct`, `distinct_category_count` and
        `category_counts`, are recomputed and persisted whenever a seat is appointed,
        whenever a seat's `status` or `voting_rights` is edited, whenever a committee
        is activated, and whenever a seat is suspended by the system for repeated
        non-return at a ballot close.

        Design: Corner/entities/committee_retrieval_returns_the_stored_balance_counters
        """
        scenario = fx.balanced_active_committee(api)

        committee = scenario.get_committee()
        a.assert_has_fields(committee, "TechnicalCommittee")
        assert committee["designation"] == "TC-14", (
            f"designation expected TC-14, got {committee['designation']}"
        )
        assert committee["status"] == "ACTIVE", (
            f"status expected ACTIVE, got {committee['status']}"
        )
        a.assert_voting_balance(
            committee,
            balance_status="BALANCED",
            active_member_count=3,
            distinct_category_count=3,
            dominance_pct=33.3,
            category_counts={"PRODUCER": 1, "USER": 1, "GENERAL_INTEREST": 1},
        )
        a.assert_roster_balance(
            committee,
            roster_balance_status="BALANCED",
            roster_member_count=3,
            roster_dominance_pct=33.3,
        )
        assert committee["open_ballot_count"] == 0, (
            "no ballot has been opened on this committee, got "
            f"{committee['open_ballot_count']}"
        )
        assert committee["chair_participant_id"] == scenario.pid("p1"), (
            "the chair identifier is stored as supplied"
        )

    def test_participant_listing_reports_total_count_and_has_more(self, api, staff_headers):
        """
        The `meta` block of a list response carries `limit` and `offset` as they were
        applied, `total_count` as the number of rows matching the filters before
        pagination, and `has_more` as a boolean that is true when rows remain beyond
        the current page.

        Design: Corner/entities/participant_listing_reports_total_count_and_has_more_across_two_pages
        """
        scenario = fx.Scenario(api)
        scenario.register_core()

        first_page, first_meta = validate_paginated(
            api.list_participants(staff_headers, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2, (
            f"a limit of 2 returns two rows, got {len(first_page)}"
        )
        assert first_meta["limit"] == 2, (
            f"limit is echoed as applied, got {first_meta['limit']}"
        )
        assert first_meta["offset"] == 0, (
            f"offset is echoed as applied, got {first_meta['offset']}"
        )
        a.assert_total_count(first_meta, 3)
        assert first_meta["has_more"] is True, (
            "a third row remains beyond this page, got has_more "
            f"{first_meta['has_more']}"
        )

        second_page, second_meta = validate_paginated(
            api.list_participants(staff_headers, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1, (
            f"the tail page holds the remaining row, got {len(second_page)}"
        )
        assert second_meta["offset"] == 2, (
            f"offset expected 2, got {second_meta['offset']}"
        )
        a.assert_total_count(second_meta, 3)
        assert second_meta["has_more"] is False, (
            "nothing remains beyond the tail page, got has_more "
            f"{second_meta['has_more']}"
        )
        assert second_page[0]["id"] not in {row["id"] for row in first_page}, (
            "the two pages walk disjoint rows"
        )


class TestServerSuppliedDefaults:
    """What the server writes when the client leaves an optional field out."""

    def test_committee_omitting_the_ballot_cap_takes_the_declared_default(self, api):
        """
        A technical committee is created by the secretariat with a `designation` such as
        TC-14 (a non-blank string of 1 to 32 characters), a `scope_text` statement of 1
        to 600 non-blank characters, a `chair_participant_id` naming the presiding
        chair, and optionally `max_concurrent_ballots`, an integer of at least 1 that
        defaults to 2 and caps how many of the committee's ballot windows may overlap.

        Design: Corner/entities/committee_creation_omitting_max_concurrent_ballots_applies_the_declared_default
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")

        committee = scenario.create_committee("p1", max_concurrent_ballots=None)

        assert committee["max_concurrent_ballots"] == 2, (
            "the omitted cap takes the declared default of 2, got "
            f"{committee['max_concurrent_ballots']}"
        )
        assert committee["status"] == "FORMING", (
            f"a new committee is born FORMING, got {committee['status']}"
        )
        a.assert_voting_balance(
            committee,
            balance_status="UNBALANCED",
            active_member_count=0,
            distinct_category_count=0,
            dominance_pct=0.0,
        )
        assert committee["roster_balance_status"] == "UNBALANCED", (
            "balance is computed immediately on the empty roster, got "
            f"{committee['roster_balance_status']}"
        )
        assert committee["open_ballot_count"] == 0, (
            f"open_ballot_count starts at 0, got {committee['open_ballot_count']}"
        )
        a.assert_common_fields(committee, expected_version=1)

    def test_appointment_omitting_voting_rights_defaults_it_and_snapshots_the_seat(
        self, api
    ):
        """
        The body names the `participant_id` being appointed and may carry
        `voting_rights`, which defaults to true; a seat created with `voting_rights`
        false is an observer — it is excluded from every ballot's eligible set and from
        both balance bases.

        Design: Corner/entities/membership_creation_omitting_voting_rights_defaults_to_true_and_snapshots_the_category
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")
        scenario.create_committee("p1")

        seat = scenario.appoint("p1", "m1", voting_rights=None)

        a.assert_has_fields(seat, "CommitteeMembership")
        assert seat["voting_rights"] is True, (
            f"the omitted flag defaults to true, got {seat['voting_rights']}"
        )
        assert seat["status"] == "ACTIVE", (
            f"a new seat is put in ACTIVE, got {seat['status']}"
        )
        assert seat["interest_category"] == "PRODUCER", (
            "the appointment snapshots the participant's category, got "
            f"{seat['interest_category']}"
        )
        assert seat["employer_affiliation_code"] == "ACME", (
            "the appointment snapshots the affiliation code, got "
            f"{seat['employer_affiliation_code']}"
        )
        assert seat["missed_ballot_streak"] == 0, (
            f"missed_ballot_streak starts at 0, got {seat['missed_ballot_streak']}"
        )
        assert seat["committee_id"] == scenario.committee_id, (
            "the committee identifier comes from the path"
        )
        a.assert_same_instant(seat["appointed_at"], "2026-08-01T00:00:00Z")
        a.assert_common_fields(seat, expected_version=1)


class TestServerDerivedFields:
    """Fields the server computes, and which the client may not supply."""

    def test_editorial_comment_is_not_substantive_while_technical_is(self, api):
        """
        The `comment_type` is `GENERAL`, `TECHNICAL` or `EDITORIAL`, and the server
        derives `is_substantive` from it: general and technical comments are
        substantive, editorial comments are not.

        Design: Corner/entities/editorial_comment_computes_is_substantive_false_while_technical_computes_true
        """
        scenario = fx.work_item_with_draft(api)

        editorial = scenario.submit_committee_comment(
            "p2",
            comment_type="EDITORIAL",
            comment_text="Clause 4 cross-reference should read Annex B",
        )
        technical = scenario.submit_committee_comment(
            "p3",
            comment_type="TECHNICAL",
            comment_text="Clause 12 torque ceiling contradicts the fatigue annex",
        )

        a.assert_has_fields(editorial, "Comment")
        assert editorial["is_substantive"] is False, (
            f"an editorial comment is not substantive, got {editorial['is_substantive']}"
        )
        assert technical["is_substantive"] is True, (
            f"a technical comment is substantive, got {technical['is_substantive']}"
        )
        for comment in (editorial, technical):
            assert comment["status"] == "OPEN", (
                f"a new comment opens in OPEN, got {comment['status']}"
            )
            assert comment["source_type"] == "COMMITTEE", (
                f"source_type expected COMMITTEE, got {comment['source_type']}"
            )
            assert comment["draft_id"] == scenario.draft_id, (
                "a committee comment attaches directly to the revision"
            )
            assert comment["public_review_id"] is None, (
                "a committee comment belongs to no public review, got "
                f"{comment['public_review_id']}"
            )
            assert comment["source_vote_id"] is None, (
                f"no vote produced this comment, got {comment['source_vote_id']}"
            )
            assert comment["disposition_rationale"] is None, (
                "a new comment carries a null rationale, got "
                f"{comment['disposition_rationale']}"
            )
            a.assert_common_fields(comment, expected_version=1)

    def test_work_item_system_fields_are_server_written_and_a_supplied_one_is_rejected(
        self, api, staff_headers
    ):
        """
        Required fields present; enum fields carrying a declared member; integer fields
        non-negative integers; date fields parsing as ISO 8601 calendar dates and
        datetime fields as ISO 8601 UTC instants; text fields that must be non-empty
        being non-empty after trimming; `limit` an integer from 1 to 100 and `offset` a
        non-negative integer; unknown body fields rejected; and any field this document
        describes as computed or server-maintained rejected when a client supplies it.

        Design: Corner/entities/work_item_system_fields_are_server_generated_and_a_supplied_progress_status_is_rejected
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")

        proposal = scenario.propose_work_item("p1")
        a.assert_has_fields(proposal, "WorkItem")
        assert proposal["progress_status"] == "PROPOSED", (
            f"a new proposal is born PROPOSED, got {proposal['progress_status']}"
        )
        assert proposal["ip_status"] == "IP_PENDING", (
            f"ip_status starts at IP_PENDING, got {proposal['ip_status']}"
        )
        assert proposal["consensus_gate"] == "OPEN", (
            "no appeal, no draft in comment resolution and no sponsoring committee "
            f"means no blocker holds, got {proposal['consensus_gate']}"
        )
        assert proposal["sponsoring_committee_id"] is None, (
            f"sponsoring_committee_id starts null, got {proposal['sponsoring_committee_id']}"
        )
        assert proposal["designation"] is None, (
            f"designation starts null, got {proposal['designation']}"
        )
        for field in (
            "scope_approved_at",
            "edition",
            "published_at",
            "periodic_review_due_date",
            "last_periodic_action_at",
        ):
            assert proposal[field] is None, (
                f"{field} starts null on a proposal, got {proposal[field]}"
            )
        for field in ("errata_count", "interpretation_count", "unresolved_negative_count"):
            assert proposal[field] == 0, (
                f"{field} starts at 0, got {proposal[field]}"
            )
        a.assert_common_fields(proposal, expected_version=1)

        response = api.create_work_item(
            f.work_item_payload(
                scenario.pid("p1"),
                title="Fastener torque spec part two",
                progress_status="IN_DEVELOPMENT",
            ),
            scenario.proposer("p1"),
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api.list_work_items(staff_headers))
        a.assert_total_count(meta, 1)
