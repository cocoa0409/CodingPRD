"""What a stored row is required to say about itself.

Creation echoes every declared field, optional inputs fall back to their
declared defaults, system-owned fields cannot be dictated by the caller, and
the two append-only streams carry no mutable bookkeeping at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_ledger_movements,
    assert_money,
    assert_pace_2dp,
    assert_rate_4dp,
    assert_status,
    assert_stream_row_has_no_version,
    qc_sample_target_size,
)
from test_helpers.constants import (
    BOGUS_UUID_1,
    BOGUS_UUID_2,
    CLOCK_START_UTC,
    INJECTED_UUID,
)
from test_helpers.factories import (
    OMIT,
    batch_payload,
    matter_payload,
    reviewer_payload,
    screening_payload,
)
from test_helpers.test_users import (
    ENGAGEMENT_MANAGER,
    QC_LEAD,
    STAFFING_COORDINATOR,
)


class TestMatterCreationEchoesDeclaredFields:
    """An intake response restates the instructions and computes the rest."""

    def test_the_new_matter_reports_its_own_intake_terms_and_opening_pace(
        self, registered_client
    ):
        """PRD §3.1: "A newly opened matter lands in `INTAKE` with `suspension_reason`
        null, and its `unbatched_document_count` is initialised to the full
        `document_count` because nothing has been carved yet."

        Six hundred documents against a sixty-day runway need barely half a document an
        hour from a single reviewer.

        Design: Corner/entities/matter_creation_echoes_declared_fields
        """
        ladder = registered_client["ladder"]

        created = validate_success(
            ladder.api.create_matter(
                matter_payload(registered_client["client_id"]), ENGAGEMENT_MANAGER
            ),
            expected_status=201,
        )
        assert created["document_count"] == 600
        assert created["pricing_model"] == "PER_DOCUMENT"
        assert_money(created["per_document_rate_cents"], 150, "per_document_rate_cents")
        assert_money(created["budget_cap_cents"], 600000, "budget_cap_cents")

        assert_status(created, "INTAKE")
        assert created["version"] == 1
        assert created["unbatched_document_count"] == 600
        assert_money(created["committed_spend_cents"], 0, "committed_spend_cents")
        assert created["staffed_reviewer_count"] == 0
        assert_pace_2dp(created["required_pace_dph"], 0.42)

        client = validate_success(
            ladder.api.get_client(registered_client["client_id"], ENGAGEMENT_MANAGER)
        )
        assert client["matter_count"] == 1


class TestMatterReadReturnsStoredAndRecomputedFields:
    """A read restates the stored terms and recomputes the derived ones."""

    def test_reading_an_untouched_matter_returns_both_kinds_of_field(
        self, matter_in_intake
    ):
        """PRD §3.1: "Reading a single matter recomputes `staffed_reviewer_count`,
        `committed_spend_cents`, `unbatched_document_count` and `required_pace_dph`
        before answering, and — because the read consults confidentiality agreements —
        it may also apply lazy expiry to an agreement whose coverage has elapsed, which
        can itself drop the matter from `IN_REVIEW` back to `STAFFING` inside a read."

        Nothing has happened to the matter yet, so every derived figure is at its
        opening value while the instructions read back unchanged.

        Design: Corner/entities/matter_read_returns_stored_and_recomputed_fields
        """
        ladder = matter_in_intake["ladder"]

        read = validate_success(
            ladder.api.get_matter(matter_in_intake["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert read["id"] == matter_in_intake["matter_id"]
        assert read["name"] == "Northwind v. Calder — Second Request"
        assert_status(read, "INTAKE")
        assert read["version"] == 1
        assert read["unbatched_document_count"] == 600
        assert read["staffed_reviewer_count"] == 0
        assert_money(read["committed_spend_cents"], 0, "committed_spend_cents")
        assert read["required_languages"] == ["EN", "JA"]
        assert read["required_bar_states"] == ["NY"]


class TestUnknownIdsReturnEntitySpecificNotFound:
    """Each entity has its own not-found answer rather than a shared one."""

    def test_three_unknown_identifiers_produce_three_different_answers(
        self, matter_in_intake
    ):
        """PRD §2.5: "Every identifier embedded in the path resolves to a stored row of
        the declared entity — otherwise the entity's own not-found error:
        `ERR_MATTER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`,
        `ERR_REVIEWER_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_QC_SAMPLE_NOT_FOUND` or `ERR_PRIVILEGE_ENTRY_NOT_FOUND`."

        The same unknown identifier read as a matter, a reviewer and a batch is refused
        three different ways, and creates nothing.

        Design: Corner/entities/unknown_ids_return_entity_specific_not_found
        """
        ladder = matter_in_intake["ladder"]

        validate_error(
            ladder.api.get_matter(BOGUS_UUID_1, ENGAGEMENT_MANAGER),
            e.ERR_MATTER_NOT_FOUND,
            404,
        )
        validate_error(
            ladder.api.get_reviewer(BOGUS_UUID_1, STAFFING_COORDINATOR),
            e.ERR_REVIEWER_NOT_FOUND,
            404,
        )
        validate_error(
            ladder.api.get_batch(BOGUS_UUID_1, ENGAGEMENT_MANAGER),
            e.ERR_BATCH_NOT_FOUND,
            404,
        )

        matters, _ = validate_paginated(
            ladder.api.list_matters(
                ENGAGEMENT_MANAGER, client_id=matter_in_intake["client_id"]
            )
        )
        assert len(matters) == 1
        reviewers, _ = validate_paginated(
            ladder.api.list_reviewers(STAFFING_COORDINATOR)
        )
        assert reviewers == []
        batches, _ = validate_paginated(ladder.api.list_batches(ENGAGEMENT_MANAGER))
        assert batches == []


class TestMatterMissingRequiredFieldRejected:
    """A required intake field cannot be left out."""

    def test_omitting_the_budget_cap_is_refused_and_registers_no_matter(
        self, registered_client
    ):
        """PRD §3.1: "Supplying the wrong rate for the chosen model, omitting the right
        one, or breaching any of these shape rules is rejected with
        `ERR_INVALID_REQUEST`."

        Without a spending ceiling the matter cannot be opened at all, and the client's
        docket stays empty.

        Design: Corner/entities/matter_missing_required_field_rejected
        """
        ladder = registered_client["ladder"]
        client_id = registered_client["client_id"]

        validate_error(
            ladder.api.create_matter(
                matter_payload(
                    client_id,
                    name="Northwind v. Calder — Missing Cap",
                    required_languages=["EN"],
                    hourly_rate_cents=OMIT,
                    budget_cap_cents=OMIT,
                    min_staffed_reviewers=OMIT,
                    onsite_seat_count=OMIT,
                    remote_work_permitted=OMIT,
                ),
                ENGAGEMENT_MANAGER,
            ),
            e.ERR_INVALID_REQUEST,
            422,
        )

        matters, _ = validate_paginated(
            ladder.api.list_matters(ENGAGEMENT_MANAGER, client_id=client_id)
        )
        assert matters == []

        client = validate_success(ladder.api.get_client(client_id, ENGAGEMENT_MANAGER))
        assert client["matter_count"] == 0


class TestOptionalInputsFallBackToDeclaredDefaults:
    """Omitted optional fields take their documented defaults."""

    def test_an_omitted_staffing_floor_and_seat_count_take_their_defaults(
        self, registered_client
    ):
        """PRD §3.1: "`min_staffed_reviewers` is the count of cleared-and-covered
        reviewers that must exist before batch assignment may begin; it must be at least
        1 and defaults to 2."

        A matter opened without staffing instructions demands two reviewers, offers one
        seat and forbids remote work.

        Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
        """
        ladder = registered_client["ladder"]

        matter = validate_success(
            ladder.api.create_matter(
                matter_payload(
                    registered_client["client_id"],
                    name="Northwind v. Calder — Defaults Probe",
                    document_count=300,
                    complexity_tier="STANDARD",
                    required_languages=["EN"],
                    required_bar_states=[],
                    subject_matter_tags=[],
                    budget_cap_cents=400000,
                    hourly_rate_cents=OMIT,
                    min_staffed_reviewers=OMIT,
                    onsite_seat_count=OMIT,
                    remote_work_permitted=OMIT,
                ),
                ENGAGEMENT_MANAGER,
            ),
            expected_status=201,
        )
        assert matter["min_staffed_reviewers"] == 2
        assert matter["onsite_seat_count"] == 1
        assert matter["remote_work_permitted"] is False
        assert_status(matter, "INTAKE")
        assert matter["unbatched_document_count"] == 300

    def test_a_newly_sourced_reviewer_takes_her_own_opening_defaults(
        self, registered_client
    ):
        """PRD §3.3: "The second axis, `engagement_status`, is staffing standing: it
        begins at `SOURCED` and moves among `SOURCED`, `CLEARED`, `ENGAGED` and
        `REMOVED`, with `REMOVED` terminal."

        Sourcing carries no credential, no engagement beyond sourcing, a perfect
        accuracy score and no recorded pace.

        Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
        """
        ladder = registered_client["ladder"]

        reviewer = validate_success(
            ladder.api.create_reviewer(
                reviewer_payload(
                    full_name="Default Probe Reviewer",
                    languages=["EN"],
                    subject_matter_tags=[],
                    hourly_cost_cents=5000,
                    max_concurrent_batches=OMIT,
                    remote_work_authorized=OMIT,
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert reviewer["max_concurrent_batches"] == 2
        assert reviewer["remote_work_authorized"] is False
        assert_status(reviewer, "UNVERIFIED", "credential_status")
        assert_status(reviewer, "SOURCED", "engagement_status")
        assert_rate_4dp(reviewer["accuracy_score"], 1.0000, "accuracy_score")
        assert_pace_2dp(reviewer["pace_dph"], 0.00)
        assert reviewer["scorecard_strikes"] == 0


class TestBatchingRecomputesUnbatchedCountAndRequiredPace:
    """Carving moves documents out of the pool without changing the workload."""

    def test_carving_four_hundred_documents_shrinks_the_pool_but_not_the_pace(
        self, matter_in_staffing
    ):
        """PRD §3.6: "A carve creates the batch in `CREATED`, assigns it a
        `batch_number` equal to the prior maximum for that matter plus 1 — dissolved
        batches keep their number, so numbers are never reused — decrements the matter's
        `unbatched_document_count` by the batch's `document_count`, freezes the sampling
        target from the currently `APPROVED` protocol's `qc_sample_pct`, and increments
        the matter's `version`."

        The carved documents are still outstanding work, so the required pace is exactly
        what it was before the batch existed.

        Design: Corner/entities/batching_recomputes_unbatched_count_and_required_pace
        """
        ladder = matter_in_staffing["ladder"]

        batch = validate_success(
            ladder.api.create_batch(
                matter_in_staffing["matter_id"], batch_payload(400), ENGAGEMENT_MANAGER
            ),
            expected_status=201,
        )
        assert batch["batch_number"] == 1
        assert batch["document_count"] == 400
        assert_status(batch, "CREATED")
        assert batch["priority_rank"] == 5
        assert batch["version"] == 1
        assert batch["qc_sample_target_size"] == qc_sample_target_size(400, 0.10) == 40

        matter = validate_success(
            ladder.api.get_matter(matter_in_staffing["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["unbatched_document_count"] == 200
        assert batch["document_count"] + matter["unbatched_document_count"] == 600
        assert_pace_2dp(matter["required_pace_dph"], 0.42)
        assert_status(matter, "STAFFING")
        assert matter["staffed_reviewer_count"] == 0


class TestSystemAndComputedFieldsInputIgnored:
    """Caller-supplied bookkeeping is ignored rather than honoured."""

    def test_an_injected_identifier_status_and_spend_are_all_discarded(
        self, registered_client
    ):
        """PRD §2.5: "Every required input field is present, of its declared type,
        inside its declared enumeration, and non-negative where the field is a count, an
        amount or a percentage; unknown fields are ignored rather than rejected."

        The matter opens with its own identifier, in intake, at version one and with
        nothing committed, and its creation stamp comes from the clock.

        Design: Corner/entities/system_and_computed_fields_input_ignored
        """
        ladder = registered_client["ladder"]

        created = validate_success(
            ladder.api.create_matter(
                matter_payload(
                    registered_client["client_id"],
                    name="Northwind v. Calder — Injection Probe",
                    hourly_rate_cents=OMIT,
                    min_staffed_reviewers=OMIT,
                    onsite_seat_count=OMIT,
                    remote_work_permitted=OMIT,
                    id=INJECTED_UUID,
                    status="CLOSED",
                    version=99,
                    committed_spend_cents=500000,
                    staffed_reviewer_count=7,
                ),
                ENGAGEMENT_MANAGER,
            ),
            expected_status=201,
        )
        assert created["id"] != INJECTED_UUID
        assert_status(created, "INTAKE")
        assert created["version"] == 1
        assert_money(created["committed_spend_cents"], 0, "committed_spend_cents")
        assert created["staffed_reviewer_count"] == 0
        assert created["created_at"].startswith(CLOCK_START_UTC[:19])


class TestEnumAndLanguageConstraintsRejected:
    """An unknown tier and a review without English are both malformed."""

    def test_an_unknown_complexity_tier_and_a_missing_english_are_both_refused(
        self, registered_client
    ):
        """PRD §3.1: "Three array fields describe the staffing profile:
        `required_languages`, a non-empty list of distinct two-letter uppercase codes
        which **must** include `"EN"`; `required_bar_states`, a list of distinct
        two-letter uppercase codes that may legitimately be empty when no admission is
        required; and `subject_matter_tags`, a list of distinct upper-snake-case
        competency tags that may also be empty."

        Neither attempt opens a matter, so the client's docket stays empty.

        Design: Corner/entities/enum_and_language_constraints_rejected
        """
        ladder = registered_client["ladder"]
        client_id = registered_client["client_id"]

        validate_error(
            ladder.api.create_matter(
                matter_payload(
                    client_id,
                    name="Northwind v. Calder — Bad Tier",
                    complexity_tier="EXTREME",
                    required_languages=["EN"],
                    hourly_rate_cents=OMIT,
                    min_staffed_reviewers=OMIT,
                    onsite_seat_count=OMIT,
                    remote_work_permitted=OMIT,
                ),
                ENGAGEMENT_MANAGER,
            ),
            e.ERR_INVALID_REQUEST,
            422,
        )
        validate_error(
            ladder.api.create_matter(
                matter_payload(
                    client_id,
                    name="Northwind v. Calder — No English",
                    required_languages=["JA"],
                    hourly_rate_cents=OMIT,
                    min_staffed_reviewers=OMIT,
                    onsite_seat_count=OMIT,
                    remote_work_permitted=OMIT,
                ),
                ENGAGEMENT_MANAGER,
            ),
            e.ERR_INVALID_REQUEST,
            422,
        )

        matters, _ = validate_paginated(
            ladder.api.list_matters(ENGAGEMENT_MANAGER, client_id=client_id)
        )
        assert matters == []


class TestLedgerAndScorecardRowsAreAppendOnly:
    """Settling an assignment adds rows; it never edits one."""

    def test_the_settlement_leaves_the_original_commitment_row_untouched(
        self, submitted_assignment
    ):
        """PRD §2.6: "Neither is ever amended or deleted; a mistake is corrected by
        appending a compensating row, never by editing a stored one."

        Three movements stand on the record, the earlier commitment among them
        unchanged, and none of the rows carries mutable bookkeeping.

        Design: Corner/entities/ledger_and_scorecard_rows_are_append_only
        """
        ladder = submitted_assignment["ladder"]
        assignment_id = submitted_assignment["assignment_id"]

        rows, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                assignment_id, ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert len(rows) == 3
        assert_created_at_ascending(rows)
        assert_ledger_movements(
            rows,
            [
                ("COMMITMENT", 85200),
                ("REVERSAL", -85200),
                ("ACTUAL_PER_DOCUMENT", 85200),
            ],
        )
        for row in rows:
            assert_stream_row_has_no_version(row, "budget ledger entry")

        commitments, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                assignment_id, ENGAGEMENT_MANAGER, entry_type="COMMITMENT", limit=100
            )
        )
        assert len(commitments) == 1
        assert_money(commitments[0]["amount_cents"], 85200, "amount_cents")

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(
                submitted_assignment["ada_id"], QC_LEAD, limit=100
            )
        )
        assert events == []


class TestFilteredListsPaginateDeterministically:
    """Two pages of a filtered list partition the collection exactly once."""

    def test_three_batches_split_two_and_one_across_the_pages(
        self, matter_in_staffing
    ):
        """PRD §2.3: "`total_count` is the size of the filtered collection before
        pagination, and `has_more` is true exactly when rows remain beyond the current
        window."

        Carving order decides page order, the pages share no row, and the status filter
        still sees all three.

        Design: Corner/entities/filtered_lists_paginate_deterministically
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]

        ladder.carve_batch(400, priority_rank=5)
        ladder.carve_batch(150, priority_rank=4)
        ladder.carve_batch(50, priority_rank=3)

        first_page, _ = validate_paginated(
            ladder.api.list_batches(
                ENGAGEMENT_MANAGER, matter_id=matter_id, limit=2, offset=0
            )
        )
        assert [(r["batch_number"], r["document_count"]) for r in first_page] == [
            (1, 400),
            (2, 150),
        ]

        second_page, _ = validate_paginated(
            ladder.api.list_batches(
                ENGAGEMENT_MANAGER, matter_id=matter_id, limit=2, offset=2
            )
        )
        assert [(r["batch_number"], r["document_count"]) for r in second_page] == [
            (3, 50)
        ]
        assert not {r["id"] for r in first_page} & {r["id"] for r in second_page}

        created, _ = validate_paginated(
            ladder.api.list_batches(
                ENGAGEMENT_MANAGER, matter_id=matter_id, status="CREATED"
            )
        )
        assert len(created) == 3

        matter = validate_success(
            ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER)
        )
        assert matter["unbatched_document_count"] == 0


class TestBodyAndPathParentsMustResolve:
    """A parent named in the body and a parent named in the path both resolve."""

    def test_an_unknown_client_and_an_unknown_matter_are_named_separately(
        self, matter_in_staffing
    ):
        """PRD §2.5: "Every foreign key supplied in a request **body** resolves to a
        stored row — `matter_id`, `reviewer_id`, `batch_id`, `validated_by_reviewer_id`
        and `client_id` — otherwise `ERR_MATTER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`,
        `ERR_REVIEWER_NOT_FOUND` or `ERR_BATCH_NOT_FOUND` as appropriate."

        Each refusal names the parent that could not be found, and neither attempt
        disturbs the real client or the real matter.

        Design: Corner/entities/body_and_path_parents_must_resolve
        """
        ladder = matter_in_staffing["ladder"]

        validate_error(
            ladder.api.create_matter(
                matter_payload(
                    BOGUS_UUID_2,
                    name="Northwind v. Calder — Orphan",
                    document_count=100,
                    complexity_tier="SIMPLE",
                    required_languages=["EN"],
                    required_bar_states=[],
                    subject_matter_tags=[],
                    budget_cap_cents=100000,
                    hourly_rate_cents=OMIT,
                    min_staffed_reviewers=OMIT,
                    onsite_seat_count=OMIT,
                    remote_work_permitted=OMIT,
                ),
                ENGAGEMENT_MANAGER,
            ),
            e.ERR_CLIENT_NOT_FOUND,
            404,
        )
        validate_error(
            ladder.api.create_batch(
                BOGUS_UUID_2, batch_payload(100), ENGAGEMENT_MANAGER
            ),
            e.ERR_MATTER_NOT_FOUND,
            404,
        )

        client = validate_success(
            ladder.api.get_client(matter_in_staffing["client_id"], ENGAGEMENT_MANAGER)
        )
        assert client["matter_count"] == 1

        matter = validate_success(
            ladder.api.get_matter(matter_in_staffing["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["unbatched_document_count"] == 600


class TestReviewerMatterJunctionRowsArePerPair:
    """Screening is per reviewer-and-matter pair, not per reviewer."""

    def test_a_second_matter_opens_its_own_pending_screening(self, matter_in_staffing):
        """PRD §2.5: "At most one conflicts screening per reviewer-and-matter pair sits
        in a non-terminal status, the non-terminal statuses being `PENDING`,
        `WAIVER_REQUIRED` and `CLEARED` — otherwise `ERR_SCREENING_ALREADY_OPEN` (HTTP
        409), on screening creation."

        Clearing the first pair leaves the second pair pending, staffs only the first
        matter, and still leaves the reviewer cleared overall.

        Design: Corner/entities/reviewer_matter_junction_rows_are_per_pair
        """
        ladder = matter_in_staffing["ladder"]
        first_matter_id = matter_in_staffing["matter_id"]
        ada = ladder.onboard()

        companion = ladder.open_matter(
            name="Northwind v. Calder — Companion Matter",
            document_count=200,
            complexity_tier="STANDARD",
            required_languages=["EN"],
            budget_cap_cents=200000,
            onsite_seat_count=1,
            remote_work_permitted=False,
        )
        ladder.approved_protocol()

        second_screening = validate_success(
            ladder.api.create_screening(
                screening_payload(
                    ada["reviewer_id"],
                    companion["id"],
                    declared_adverse_parties=["Calder Holdings LLC"],
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_status(second_screening, "PENDING")
        assert_status(
            validate_success(
                ladder.api.get_screening(ada["screening_id"], STAFFING_COORDINATOR)
            ),
            "CLEARED",
        )

        screenings, _ = validate_paginated(
            ladder.api.list_screenings(
                STAFFING_COORDINATOR, reviewer_id=ada["reviewer_id"]
            )
        )
        assert len(screenings) == 2

        first = validate_success(
            ladder.api.get_matter(first_matter_id, ENGAGEMENT_MANAGER)
        )
        assert first["staffed_reviewer_count"] == 1
        assert_status(first, "IN_REVIEW")

        second = validate_success(
            ladder.api.get_matter(companion["id"], ENGAGEMENT_MANAGER)
        )
        assert second["staffed_reviewer_count"] == 0
        assert_status(second, "STAFFING")

        assert_status(
            ladder.read_reviewer(ada["reviewer_id"]), "CLEARED", "engagement_status"
        )
