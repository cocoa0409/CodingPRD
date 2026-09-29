"""Every refusal names its own cause rather than a nearby one.

Three eligibility clauses, three session-window defects, three batch-sizing
defects and seven unknown-row paths each answer with their own catalogue entry,
and none of them stands in for another.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_money, assert_rate_4dp, assert_status
from test_helpers.constants import BOGUS_UUID_4
from test_helpers.factories import (
    assignment_payload,
    batch_payload,
    qc_validate_payload,
    session_payload,
)
from test_helpers.fixtures import REVIEWER_ADA, REVIEWER_BEN, REVIEWER_ELENA
from test_helpers.test_users import ENGAGEMENT_MANAGER, QC_LEAD, STAFFING_COORDINATOR


class TestEligibilityTrioEachMapsToItsOwnError:
    """Three fully papered reviewers, one failing clause apiece."""

    def test_the_bar_the_language_and_the_tier_clauses_answer_separately(
        self, matter_in_staffing
    ):
        """PRD §3.6: "The candidate must clear, in the precedence order of Section 2.5,
        a `CLEARED` screening for the pair (`ERR_CONFLICTS_NOT_CLEARED`), a live
        `EXECUTED` agreement covering the clock (`ERR_CONFIDENTIALITY_NOT_EXECUTED`), a
        `credential_status` of `VERIFIED` (`ERR_CREDENTIAL_NOT_VERIFIED`), the
        second-level separation rule (`ERR_SECOND_LEVEL_SAME_REVIEWER`), every one of
        the matter's `required_bar_states` appearing in their `bar_admissions`
        (`ERR_BAR_ADMISSION_MISSING`), an `active_assignment_count` strictly below their
        `max_concurrent_batches` (`ERR_REVIEWER_CAPACITY_EXCEEDED`), every one of the
        matter's `required_languages` appearing in their `languages`
        (`ERR_LANGUAGE_REQUIREMENT_UNMET`), and a `tier` exactly equal to the requested
        `pass_type` (`ERR_TIER_MISMATCH`)."

        Each reviewer is complete on every axis but one, so the three refusals name
        three different unmet requirements.

        Design: Corner/errors/eligibility_trio_each_maps_to_its_own_error
        """
        ladder = matter_in_staffing["ladder"]
        wrong_bar = ladder.onboard(
            REVIEWER_ELENA, full_name="Emil Navarro", bar_admissions=["CA"]
        )
        wrong_language = ladder.onboard(
            REVIEWER_ELENA, full_name="Fiona Reyes", languages=["EN"]
        )
        wrong_tier = ladder.onboard(REVIEWER_BEN, full_name="Gil Trevino")
        batch = ladder.carve_batch(400)

        for reviewer, expected in (
            (wrong_bar, e.ERR_BAR_ADMISSION_MISSING),
            (wrong_language, e.ERR_LANGUAGE_REQUIREMENT_UNMET),
            (wrong_tier, e.ERR_TIER_MISMATCH),
        ):
            validate_error(
                ladder.api.create_assignment(
                    batch["id"],
                    assignment_payload(
                        batch["version"], reviewer["reviewer_id"], "FIRST_PASS"
                    ),
                    STAFFING_COORDINATOR,
                ),
                expected,
                422,
            )

        after = ladder.read_batch(batch["id"])
        assert_status(after, "CREATED")
        assert after["version"] == batch["version"] == 1

        matter = validate_success(
            ladder.api.get_matter(matter_in_staffing["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_status(matter, "IN_REVIEW")
        assert matter["staffed_reviewer_count"] == 3
        assert_money(matter["committed_spend_cents"], 0, "committed_spend_cents")


class TestSessionWindowErrorsAreDistinguishable:
    """One endpoint, three different defects in the requested window."""

    def test_a_zero_length_window_an_uncovered_window_and_an_overlap_differ(
        self, matter_in_staffing
    ):
        """PRD §2.5: "One reviewer does not hold two sessions in `SCHEDULED` or `ACTIVE`
        whose half-open windows overlap, and this check spans **all** matters rather
        than only the requested one — otherwise `ERR_SESSION_WINDOW_OVERLAP` (HTTP 409),
        on session scheduling."

        With two onsite seats the seat rule is never operative, so the fourth request is
        answered on the reviewer's own double-booking.

        Design: Corner/errors/session_window_errors_are_distinguishable
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]
        ada = ladder.onboard(REVIEWER_ADA)

        validate_error(
            ladder.api.create_session(
                session_payload(
                    ada["reviewer_id"],
                    matter_id,
                    starts_at_utc="2026-08-05T00:00:00Z",
                    ends_at_utc="2026-08-05T00:00:00Z",
                ),
                ada["headers"],
            ),
            e.ERR_INVALID_TIME_WINDOW,
            422,
        )

        validate_error(
            ladder.api.create_session(
                session_payload(
                    ada["reviewer_id"],
                    matter_id,
                    starts_at_utc="2026-11-01T00:00:00Z",
                    ends_at_utc="2026-11-05T00:00:00Z",
                ),
                ada["headers"],
            ),
            e.ERR_SESSION_OUTSIDE_COVERAGE,
            422,
        )

        booked = validate_success(
            ladder.api.create_session(
                session_payload(ada["reviewer_id"], matter_id), ada["headers"]
            ),
            expected_status=201,
        )
        assert_status(booked, "SCHEDULED")

        body = validate_error(
            ladder.api.create_session(
                session_payload(
                    ada["reviewer_id"],
                    matter_id,
                    starts_at_utc="2026-08-15T00:00:00Z",
                    ends_at_utc="2026-08-20T00:00:00Z",
                ),
                ada["headers"],
            ),
            e.ERR_SESSION_WINDOW_OVERLAP,
            409,
        )
        assert body["error_id"] != e.ERR_ONSITE_SEATS_EXHAUSTED

        sessions, _ = validate_paginated(
            ladder.api.list_sessions(
                STAFFING_COORDINATOR, reviewer_id=ada["reviewer_id"]
            )
        )
        assert len(sessions) == 1


class TestSuspendedMatterBlocksWritesUntilLifted:
    """Suspension gates the whole matter, not one endpoint."""

    def test_lifting_the_suspension_re_derives_the_status_and_reopens_the_writes(
        self, matter_in_staffing
    ):
        """PRD §3.1: "While a matter is `SUSPENDED`, sixteen operations named in Section
        2.5 are refused outright with `ERR_MATTER_SUSPENDED`."

        Two unrelated writes are both refused on the suspension, and the resume lands
        back where the staffing count puts it rather than where it left.

        Design: Corner/errors/suspended_matter_blocks_writes_until_lifted
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]
        ada = ladder.onboard(REVIEWER_ADA)
        batch = ladder.carve_batch(400)
        ladder.suspend_matter("collection hold pending a protective order")

        validate_error(
            ladder.api.create_assignment(
                batch["id"],
                assignment_payload(
                    batch["version"], ada["reviewer_id"], "FIRST_PASS"
                ),
                STAFFING_COORDINATOR,
            ),
            e.ERR_MATTER_SUSPENDED,
            409,
        )
        refused = ladder.read_batch(batch["id"])
        assert_status(refused, "CREATED")
        assert refused["version"] == 1

        validate_error(
            ladder.api.create_session(
                session_payload(ada["reviewer_id"], matter_id), ada["headers"]
            ),
            e.ERR_MATTER_SUSPENDED,
            409,
        )
        sessions, _ = validate_paginated(
            ladder.api.list_sessions(STAFFING_COORDINATOR, matter_id=matter_id)
        )
        assert sessions == []

        resumed = ladder.resume_matter()
        assert_status(resumed, "IN_REVIEW")
        assert resumed["staffed_reviewer_count"] == 1
        assert resumed["min_staffed_reviewers"] == 1

        created = validate_success(
            ladder.api.create_assignment(
                batch["id"],
                assignment_payload(
                    batch["version"], ada["reviewer_id"], "FIRST_PASS"
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_money(
            created["committed_amount_cents"], 85200, "committed_amount_cents"
        )
        assert ladder.read_batch(batch["id"])["version"] == 2


class TestUnverifiedCredentialBlocksAssignment:
    """Contractually complete paper is not the same as a verified credential."""

    def test_an_uncredentialled_reviewer_is_refused_and_never_counted(
        self, staffed_matter
    ):
        """PRD §2.5: "The reviewer's `credential_status` is `VERIFIED` — otherwise
        `ERR_CREDENTIAL_NOT_VERIFIED` (HTTP 409), on named-reviewer assignment creation
        and assignment start."

        The staffing count demands a verified credential, so the reviewer with perfect
        paper is neither counted nor assignable.

        Design: Corner/errors/unverified_credential_blocks_assignment
        """
        ladder = staffed_matter["ladder"]
        matter_id = staffed_matter["matter_id"]

        hana = ladder.source_reviewer(REVIEWER_ELENA, full_name="Hana Duval")
        screening = ladder.open_screening(hana["id"])
        ladder.decide_screening(screening["id"], "CLEARED")
        agreement = ladder.issue_agreement(hana["id"])
        ladder.execute_agreement(agreement["id"], hana["id"], "Hana Duval")

        batch = ladder.carve_batch(400)
        validate_error(
            ladder.api.create_assignment(
                batch["id"],
                assignment_payload(batch["version"], hana["id"], "FIRST_PASS"),
                STAFFING_COORDINATOR,
            ),
            e.ERR_CREDENTIAL_NOT_VERIFIED,
            409,
        )

        reviewer = ladder.read_reviewer(hana["id"])
        assert_status(reviewer, "UNVERIFIED", "credential_status")
        assert_status(reviewer, "CLEARED", "engagement_status")

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert matter["staffed_reviewer_count"] == 1
        assert_money(matter["committed_spend_cents"], 0, "committed_spend_cents")
        assert_status(ladder.read_batch(batch["id"]), "CREATED")


class TestMinStaffingGateBlocksTheFirstAssignment:
    """A matter demanding two reviewers refuses work while only one is aboard."""

    def test_one_individually_eligible_reviewer_is_still_short_of_the_floor(
        self, registered_client
    ):
        """PRD §2.5: "The matter's `status` is `IN_REVIEW`, which is to say
        `staffed_reviewer_count` has reached `min_staffed_reviewers` — otherwise
        `ERR_MIN_STAFFING_UNMET` (HTTP 409), on named-reviewer assignment creation and
        auto-assignment."

        The gate is read from the matter's status, so an otherwise perfect reviewer is
        refused while the count sits one short.

        Design: Corner/errors/min_staffing_gate_blocks_the_first_assignment
        """
        ladder = registered_client["ladder"]
        matter = ladder.open_matter(
            name="Northwind v. Calder — Paired Tranche",
            document_count=200,
            min_staffed_reviewers=2,
        )
        ladder.approved_protocol()
        ada = ladder.onboard(REVIEWER_ADA)
        batch = ladder.carve_batch(200)

        validate_error(
            ladder.api.create_assignment(
                batch["id"],
                assignment_payload(
                    batch["version"], ada["reviewer_id"], "FIRST_PASS"
                ),
                STAFFING_COORDINATOR,
            ),
            e.ERR_MIN_STAFFING_UNMET,
            409,
        )

        readout = validate_success(
            ladder.api.get_matter(matter["id"], ENGAGEMENT_MANAGER)
        )
        assert_status(readout, "STAFFING")
        assert readout["staffed_reviewer_count"] == 1
        assert readout["min_staffed_reviewers"] == 2
        assert readout["unbatched_document_count"] == 0
        assert_money(readout["committed_spend_cents"], 0, "committed_spend_cents")

        after = ladder.read_batch(batch["id"])
        assert_status(after, "CREATED")
        assert after["version"] == 1


class TestBatchSizingErrorsAreDistinguishable:
    """A shape error and a pool error are not the same refusal."""

    def test_zero_documents_and_an_over_large_carve_answer_differently(
        self, matter_in_staffing
    ):
        """PRD §3.6: "A `document_count` below 1 is `ERR_ZERO_DOCUMENT_BATCH`, and a
        `document_count` greater than the matter's current `unbatched_document_count` is
        `ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS`."

        Zero is a shape defect rather than a pool defect, and once the pool is empty
        even a single document is a pool defect.

        Design: Corner/errors/batch_sizing_errors_are_distinguishable
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]

        validate_error(
            ladder.api.create_batch(matter_id, batch_payload(0), ENGAGEMENT_MANAGER),
            e.ERR_ZERO_DOCUMENT_BATCH,
            422,
        )
        validate_error(
            ladder.api.create_batch(matter_id, batch_payload(601), ENGAGEMENT_MANAGER),
            e.ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS,
            422,
        )

        whole = validate_success(
            ladder.api.create_batch(matter_id, batch_payload(600), ENGAGEMENT_MANAGER),
            expected_status=201,
        )
        assert whole["document_count"] == 600
        assert whole["batch_number"] == 1
        assert whole["qc_sample_target_size"] == 60

        validate_error(
            ladder.api.create_batch(matter_id, batch_payload(1), ENGAGEMENT_MANAGER),
            e.ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS,
            422,
        )

        batches, _ = validate_paginated(
            ladder.api.list_batches(ENGAGEMENT_MANAGER, matter_id=matter_id)
        )
        assert len(batches) == 1
        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert matter["unbatched_document_count"] == 0


class TestSampleErrorCountsCannotExceedTheSample:
    """The guard is on the sum of both error kinds."""

    def test_a_refused_validation_leaves_the_sample_open_for_a_clean_one(
        self, drawn_sample
    ):
        """PRD §3.8: "Their sum must not exceed the sample's frozen
        `sampled_document_count`, since a document cannot be wrong more times than it
        was read; a sum that exceeds it is `ERR_ERROR_COUNT_EXCEEDS_SAMPLE`."

        Thirty-nine coding errors plus two privilege errors overshoot a forty document
        sample, and the refusal does not consume the row.

        Design: Corner/errors/sample_error_counts_cannot_exceed_the_sample
        """
        ladder = drawn_sample["ladder"]
        sample_id = drawn_sample["sample_id"]

        validate_error(
            ladder.api.validate_qc_sample(
                sample_id, qc_validate_payload(39, 2), QC_LEAD
            ),
            e.ERR_ERROR_COUNT_EXCEEDS_SAMPLE,
            422,
        )

        pending = validate_success(ladder.api.get_qc_sample(sample_id, QC_LEAD))
        assert pending["outcome"] == "PENDING"
        assert pending["sampled_document_count"] == 40
        assert_rate_4dp(pending["discrepancy_rate"], 0.0000, "discrepancy_rate")
        assert_status(ladder.read_batch(drawn_sample["batch_id"]), "QC_SAMPLING")

        validated = ladder.validate_sample(sample_id, 0, 0)
        assert validated["outcome"] == "PASSED"
        assert_rate_4dp(validated["discrepancy_rate"], 0.0000, "discrepancy_rate")
        assert_status(ladder.read_batch(drawn_sample["batch_id"]), "QC_PASSED")

        reviewer = ladder.read_reviewer(drawn_sample["ada_id"])
        assert_rate_4dp(reviewer["accuracy_score"], 1.0000, "accuracy_score")
        assert reviewer["scorecard_strikes"] == 0


class TestEveryEntityPathHasItsOwnNotFound:
    """The same unknown identifier on eight paths gives eight answers."""

    def test_no_path_falls_back_to_a_generic_unknown_row(self, ladder):
        """PRD §2.5: "Every identifier embedded in the path resolves to a stored row of
        the declared entity — otherwise the entity's own not-found error:
        `ERR_MATTER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`,
        `ERR_REVIEWER_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_QC_SAMPLE_NOT_FOUND` or `ERR_PRIVILEGE_ENTRY_NOT_FOUND`."

        Each single-row read names the entity it failed to find, so the family of
        unknown-row answers is complete rather than collapsed.

        Design: Corner/errors/every_entity_path_has_its_own_not_found
        """
        probes = (
            (ladder.api.get_protocol, e.ERR_PROTOCOL_NOT_FOUND),
            (ladder.api.get_screening, e.ERR_SCREENING_NOT_FOUND),
            (ladder.api.get_agreement, e.ERR_AGREEMENT_NOT_FOUND),
            (ladder.api.get_session, e.ERR_SESSION_NOT_FOUND),
            (ladder.api.get_assignment, e.ERR_ASSIGNMENT_NOT_FOUND),
            (ladder.api.get_qc_sample, e.ERR_QC_SAMPLE_NOT_FOUND),
            (ladder.api.get_privilege_entry, e.ERR_PRIVILEGE_ENTRY_NOT_FOUND),
            (ladder.api.get_client, e.ERR_CLIENT_NOT_FOUND),
        )
        seen = []
        for read, expected in probes:
            body = validate_error(
                read(BOGUS_UUID_4, ENGAGEMENT_MANAGER), expected, 404
            )
            assert body["message"]
            seen.append(body["error_id"])

        assert len(set(seen)) == len(probes)
