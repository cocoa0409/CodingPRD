"""Input rules: structural bounds, temporal windows, uniqueness and quorum.

Some of these fire on a payload read in isolation, some need the rest of the
table, and two of them need a record two hops away — a shift's drive window and an
airing's parent show format. Each refusal is paired with a read proving nothing was
written, and the phone-bank window rule is driven from both sides so the predicate
is not merely rejecting everything.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_ONE,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_volunteer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
DRIVE_START = "2026-08-01T00:00:00Z"
DRIVE_END = "2026-08-10T00:00:00Z"
INSIDE_START = "2026-08-02T18:00:00Z"
INSIDE_END = "2026-08-02T21:00:00Z"
BEFORE_START = "2026-07-31T18:00:00Z"
BEFORE_END = "2026-07-31T21:00:00Z"
EPISODE_START = "2026-08-03T09:00:00Z"
LOG_DUE_AT = "2026-08-06T09:00:00Z"


def _drive_running_the_first_ten_days_of_august(phone_line_count=2):
    fixtures.set_clock(CLOCK)
    return fixtures.create_active_drive(
        name="Fall Drive 2026",
        goal_cents=500000,
        start_at=DRIVE_START,
        end_at=DRIVE_END,
        phone_line_count=phone_line_count,
    )


def _roster(drive_id, volunteer_id, start_at, end_at):
    return api_client.create_phone_bank_shift(
        factories.create_phone_bank_shift_payload(drive_id, volunteer_id, start_at, end_at),
        DEVELOPMENT_HEADERS,
    )


class TestStructuralBounds:
    def test_a_page_size_above_the_maximum_is_refused(self):
        """The bound sits on a query parameter, so no row is even considered.

        "`limit` caps how many rows come back; when omitted it defaults to 10, its
        smallest accepted value is 1 and its largest accepted value is 100 ... A
        `limit` below 1, a `limit` above 100, or a negative `offset` is a structural
        failure and is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_above_the_maximum_is_rejected
        """
        fixtures.set_clock(CLOCK)

        validate_error(
            api_client.list_volunteers(DIRECTOR_HEADERS, params={"limit": 101, "offset": 0}),
            "ERR_VALIDATION",
            400,
        )

    def test_a_drive_window_that_ends_before_it_starts_is_refused(self):
        """A semantically impossible window carries its own code, not the generic one.

        The coordinator plans a drive "with a public `name`, a `goal_cents` of at
        least 1, a `start_at` and an `end_at` strictly after it — otherwise
        `ERR_INVALID_INTERVAL`".

        Design: Corner/validations/drive_window_ending_before_it_starts_is_rejected
        """
        fixtures.set_clock(CLOCK)

        validate_error(
            api_client.create_membership_drive(
                factories.create_membership_drive_payload(
                    name="Backwards Drive",
                    goal_cents=500000,
                    start_at="2026-08-10T00:00:00Z",
                    end_at="2026-08-01T00:00:00Z",
                    phone_line_count=2,
                ),
                DEVELOPMENT_HEADERS,
            ),
            "ERR_INVALID_INTERVAL",
            422,
        )

        _, meta = validate_paginated(api_client.list_membership_drives(DEVELOPMENT_HEADERS))
        assert meta["total_count"] == 0

    def test_a_reused_premium_sku_is_refused_and_the_first_row_survives(self):
        """Uniqueness is a whole-table predicate and can only fail on the second write.

        A premium is registered "with a `sku` that must be non-empty and unique
        across premiums — a reused code answers `ERR_DUPLICATE_KEY`".

        Design: Corner/validations/duplicate_premium_sku_is_rejected
        """
        fixtures.set_clock(CLOCK)
        fixtures.create_premium(
            sku="MUG-01",
            name="Station mug",
            tier_threshold_cents=5000,
            fair_market_value_cents=1500,
            units_received_qty=2,
        )

        validate_error(
            api_client.create_premium_item(
                factories.create_premium_item_payload(
                    sku="MUG-01",
                    name="Second mug",
                    tier_threshold_cents=9000,
                    fair_market_value_cents=2500,
                    units_received_qty=5,
                ),
                DEVELOPMENT_HEADERS,
            ),
            "ERR_DUPLICATE_KEY",
            409,
        )

        rows, meta = validate_paginated(api_client.list_premium_items(DEVELOPMENT_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["name"] == "Station mug"


class TestPhoneBankWindowRules:
    def test_a_shift_wholly_inside_the_drive_window_is_accepted(self):
        """The positive half of the window rule writes the shift.

        "The shift must sit inside the drive's own window: a `start_at` earlier than
        the drive's `start_at`, or an `end_at` later than the drive's `end_at`,
        answers `ERR_SHIFT_OUTSIDE_DRIVE_WINDOW`." A shift inside the window trips no
        such refusal, and `COMPLETED` later "moves the shift `SCHEDULED →
        COMPLETED`", so a freshly rostered shift rests on `SCHEDULED`.

        Design: Corner/validations/shift_inside_the_drive_window_is_accepted
        """
        drive = _drive_running_the_first_ten_days_of_august()
        fern = fixtures.create_volunteer(
            legal_name="Fern Duval",
            email="fern@krcr.example",
            role_track="DEVELOPMENT",
            seniority_start_date="2023-01-01",
        )

        shift = validate_success(
            _roster(drive["id"], fern["id"], INSIDE_START, INSIDE_END), 201
        )
        assert shift["status"] == "SCHEDULED"
        assert shift["drive_id"] == drive["id"]
        assert shift["volunteer_id"] == fern["id"]
        assertions.assert_phone_bank_shift(shift)

    def test_a_shift_starting_before_the_drive_window_is_refused(self):
        """One instant outside the window is enough, and nothing is rostered.

        "a `start_at` earlier than the drive's `start_at` ... answers
        `ERR_SHIFT_OUTSIDE_DRIVE_WINDOW`."

        Design: Corner/validations/shift_starting_before_the_drive_window_is_rejected
        """
        drive = _drive_running_the_first_ten_days_of_august()
        fern = fixtures.create_volunteer(
            legal_name="Fern Duval",
            email="fern@krcr.example",
            role_track="DEVELOPMENT",
            seniority_start_date="2023-01-01",
        )

        validate_error(
            _roster(drive["id"], fern["id"], BEFORE_START, BEFORE_END),
            "ERR_SHIFT_OUTSIDE_DRIVE_WINDOW",
            422,
        )

        _, meta = validate_paginated(api_client.list_phone_bank_shifts(DEVELOPMENT_HEADERS))
        assert meta["total_count"] == 0

    def test_two_lines_held_by_two_people_leave_no_line_for_a_third(self):
        """The capacity predicate aggregates other volunteers' shifts on the drive.

        "line capacity is measured on **half-open** windows ... counted against
        shifts on the same drive whose `status` is `SCHEDULED` or `COMPLETED`. Two
        shifts that touch at an endpoint therefore do **not** consume the same line
        at the same time. When the number of shifts simultaneously holding a line
        would exceed the drive's `phone_line_count`, the roster is refused with
        `ERR_PHONE_LINE_CAPACITY`."

        Design: Corner/validations/phone_line_capacity_counts_concurrent_shifts_across_volunteers
        """
        drive = _drive_running_the_first_ten_days_of_august(phone_line_count=2)
        gus, hana, iris = fixtures.create_development_volunteers(count=3)
        fixtures.create_shift(drive["id"], gus["id"], INSIDE_START, INSIDE_END)
        fixtures.create_shift(drive["id"], hana["id"], INSIDE_START, INSIDE_END)

        validate_error(
            _roster(
                drive["id"], iris["id"], "2026-08-02T19:00:00Z", "2026-08-02T20:00:00Z"
            ),
            "ERR_PHONE_LINE_CAPACITY",
            409,
        )

        _, meta = validate_paginated(api_client.list_phone_bank_shifts(DEVELOPMENT_HEADERS))
        assert meta["total_count"] == 2

        handover = validate_success(
            _roster(drive["id"], iris["id"], INSIDE_END, "2026-08-02T22:00:00Z"), 201
        )
        assert handover["status"] == "SCHEDULED"


class TestQuorumBeforeTally:
    def test_two_ballots_against_three_seats_stop_the_tally_before_the_score(self):
        """The gate runs first, so no composite and no show are written.

        "The required quorum is the larger of 3 and sixty percent of that eligible
        seat count rounded up to a whole number. When the number of ballots in the
        current round falls short, the tally is refused with `ERR_QUORUM_NOT_MET`."
        The proposal therefore keeps "a null `composite_score`" and "a null
        `decided_at`", and no `Program` exists because only "An approval creates the
        show."

        Design: Corner/validations/quorum_is_enforced_before_any_composite_is_written
        """
        fixtures.set_clock(CLOCK)
        host = fixtures.create_certified_host()
        members = fixtures.create_committee_members(count=3)
        chain = fixtures.open_review_chain(host["id"], members)
        fixtures.cast_ballot(chain["proposal_id"], members[0]["id"])
        fixtures.cast_ballot(chain["proposal_id"], members[1]["id"])

        validate_error(
            api_client.decide_proposal(
                chain["proposal_id"],
                factories.decide_proposal_payload(
                    fixtures.proposal_version(chain["proposal_id"])
                ),
                DIRECTOR_HEADERS,
            ),
            "ERR_QUORUM_NOT_MET",
            422,
        )

        stalled = validate_success(
            api_client.get_proposal(chain["proposal_id"], DIRECTOR_HEADERS), 200
        )
        assert stalled["status"] == "IN_COMMITTEE"
        assert stalled["composite_score"] is None
        assert stalled["decided_at"] is None

        _, meta = validate_paginated(api_client.list_programs(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestConditionalObligations:
    def test_a_psa_owes_no_public_file_entry_and_refuses_the_posting(self):
        """The obligation follows the spot's class, not its approval.

        "Spots of class `UNDERWRITING` and `PSA` incur no obligation and keep
        `public_file_status` `NOT_REQUIRED`", and "A spot that owes no outstanding
        entry — one whose `public_file_status` is `NOT_REQUIRED`, or already
        `POSTED`, or already `LATE_POSTED` — answers
        `ERR_PUBLIC_FILE_NOT_REQUIRED`." A draft opens with "null `public_file_due_at`,
        `public_file_posted_at` and `public_file_reference`", and a refused posting
        writes none of them.

        Design: Corner/validations/public_file_posting_on_a_psa_is_rejected_as_not_required
        """
        fixtures.set_clock(CLOCK)
        spot = fixtures.create_spot(
            underwriter_name="County Health",
            spot_class="PSA",
            copy_text="County Health reminds listeners that flu shots are available.",
            flight_start="2026-08-05T00:00:00Z",
            flight_end="2026-09-05T00:00:00Z",
        )
        fixtures.submit_spot(spot["id"])

        reviewed = validate_success(
            api_client.review_underwriting_spot(
                spot["id"],
                factories.review_spot_payload(),
                make_compliance_officer_headers(OFFICER_ONE),
            ),
            200,
        )
        assert reviewed["status"] == "APPROVED"
        assert reviewed["noncommercial_risk_score"] == 0
        assert reviewed["public_file_status"] == "NOT_REQUIRED"

        validate_error(
            api_client.post_public_file(
                spot["id"],
                factories.public_file_posting_payload(public_file_reference="PF-2026-0001"),
                make_compliance_officer_headers(OFFICER_ONE),
            ),
            "ERR_PUBLIC_FILE_NOT_REQUIRED",
            409,
        )

        stored = fixtures.read_spot(spot["id"])
        assert stored["public_file_status"] == "NOT_REQUIRED"
        assert stored["public_file_posted_at"] is None
        assert stored["public_file_reference"] is None

    def test_a_music_airing_with_no_spins_cannot_submit_its_log(self):
        """The rule is read off the parent show's format, two hops from the log.

        "when the show's `format_code` is `MUSIC` the `log_status` moves to `PENDING`
        and `log_due_at` is stamped at `scheduled_start_utc` plus 72 hours". "A
        `MUSIC` show whose airing has zero playlist entries cannot submit, and
        answers `ERR_PLAYLIST_EMPTY`", and submission is what "writes
        `provisional_royalty_cents`", so a refused submission leaves it null.

        Design: Corner/validations/music_show_cannot_submit_an_empty_playlist_log
        """
        base = fixtures.station()
        chain = fixtures.episode_chain(
            base["host_id"],
            base["members"],
            title="Delta Blues Hour",
            format_code="MUSIC",
            requested_daypart="MIDDAY",
            duration_minutes=60,
            day_of_week=1,
            start_minute=540,
            scheduled_start_utc=EPISODE_START,
            air_status=None,
        )

        aired = fixtures.record_air_result(chain["episode_id"], air_status="AIRED")
        assert aired["air_status"] == "AIRED"
        assert aired["log_status"] == "PENDING"
        assertions.assert_instant_equals(aired["log_due_at"], LOG_DUE_AT, "log_due_at")

        validate_error(
            api_client.submit_playlist_log(
                chain["episode_id"], make_volunteer_headers(base["host_id"])
            ),
            "ERR_PLAYLIST_EMPTY",
            422,
        )

        stored = fixtures.read_episode(chain["episode_id"])
        assert stored["log_status"] == "PENDING"
        assert stored["provisional_royalty_cents"] is None
