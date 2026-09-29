"""What registration, scheduling and the single-resource reads actually store."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_FOUND,
    ERR_TOURNAMENT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_identity_fields,
    assert_pagination_meta,
)
from test_helpers.constants import (
    SEASON_AGE_CUTOFF_DATE,
    SEASON_ASSISTANCE_BUDGET_CENTS,
    STANDARD_ENTRY_FEE_CENTS,
)
from test_helpers.test_users import ANONYMOUS, TOUR_ADMIN, member_headers
from test_helpers.types import (
    DIVISION_U17,
    DIVISION_U19,
    ELIGIBILITY_PENDING_VERIFICATION,
    ENTRY_APPLIED,
    FEE_UNPAID,
    EXEMPTION_SPONSOR_INVITE,
    HANDICAP_SOURCE_SELF_ATTESTED,
)


class TestSeasonOpening:
    def test_new_season_carries_three_funded_ledger_buckets(self, api):
        """A new season answers with a full purse and empty ranking watermarks.

        PRD: "A freshly opened season starts fully funded and completely unspent.
        Its `assistance_available_cents` equals its `assistance_budget_cents`,
        while `assistance_committed_cents` and `assistance_disbursed_cents` both
        start at zero."

        Design: Corner/entities/season_creation_returns_funded_three_bucket_ledger
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        assert_identity_fields(season, expected_version=1)
        assert_cents(season["assistance_budget_cents"], SEASON_ASSISTANCE_BUDGET_CENTS,
                     "assistance_budget_cents")
        assert_cents(season["assistance_available_cents"], SEASON_ASSISTANCE_BUDGET_CENTS,
                     "assistance_available_cents")
        assert_cents(season["assistance_committed_cents"], 0, "assistance_committed_cents")
        assert_cents(season["assistance_disbursed_cents"], 0, "assistance_disbursed_cents")
        assert season["age_cutoff_date"] == SEASON_AGE_CUTOFF_DATE
        assert season["ranking_epoch"] == 0
        assert season["ranked_member_count"] == 0
        assert season["last_ranking_run_at"] is None
        assert season["last_ranking_as_of_date"] is None


class TestJuniorRegistration:
    def test_member_read_returns_exactly_what_registration_stored(self, api):
        """The single-junior read hands back the stored registration untouched.

        PRD: "Registration sets `conduct_points` to zero, `late_withdrawal_count`
        to zero, `provisional_ranking_points` to 0.00 and
        `provisional_counted_events` to zero; the certified ranking fields start
        empty, with `certified_ranking_points` null, `certified_counted_events`
        zero, `certified_rank_position` null and `last_ranking_epoch` null."

        Design: Corner/entities/member_retrieval_returns_stored_registration
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)
        created = validate_success(
            api.register_member(f.member_payload(season["id"]), ANONYMOUS), 201
        )

        member = validate_success(api.get_member(created["id"], TOUR_ADMIN), 200)

        assert member["id"] == created["id"]
        assert member["handicap_index"] == 3.2
        assert member["birth_date"] == "2010-05-04"
        assert member["age_division"] == DIVISION_U17
        assert member["eligibility_status"] == ELIGIBILITY_PENDING_VERIFICATION
        assert member["publication_opt_in"] is True
        assert member["conduct_points"] == 0
        assert member["late_withdrawal_count"] == 0

    def test_registration_without_a_birth_date_is_refused_as_invalid(self, api):
        """A junior with no birth date is not created with a null one instead.

        PRD: "The schema check covers every `POST` endpoint and requires that the
        body parses, that every required input field is present, that every
        enum-typed value belongs to its declared set, that integers are integers,
        that dates are ISO 8601, and that no numeric field is negative where the
        entity declares a non-negative constraint."

        Design: Corner/entities/member_registration_missing_birth_date_is_invalid_request
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        response = api.register_member(
            f.member_payload(season["id"], birth_date=None, publication_opt_in=None),
            ANONYMOUS,
        )

        validate_error(response, ERR_INVALID_REQUEST, 422)
        rows, meta = validate_paginated(
            api.list_members({"season_id": season["id"]}, TOUR_ADMIN)
        )
        assert_pagination_meta(meta, total_count=0)
        assert rows == []

    def test_publication_consent_defaults_to_withheld(self, api):
        """Recruiting exposure is opt-in, so an omitted flag stores false.

        PRD: "The optional `publication_opt_in` flag records the guardian's
        consent to publish results to college coaches and defaults to false when
        omitted."

        Design: Corner/entities/member_publication_opt_in_defaults_to_false
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        member = validate_success(
            api.register_member(
                f.second_member_payload(season["id"], publication_opt_in=None),
                ANONYMOUS,
            ),
            201,
        )

        assert member["publication_opt_in"] is False
        assert member["certified_ranking_points"] is None
        assert member["certified_counted_events"] == 0
        assert member["certified_rank_position"] is None
        assert member["last_ranking_epoch"] is None
        assert float(member["provisional_ranking_points"]) == 0.00
        stored = fx.read_member(api, member["id"])
        assert stored["publication_opt_in"] is False

    def test_age_division_is_derived_from_the_cutoff_month_and_day(self, api):
        """The cutoff birthday counts as reached, and a ten-year-old has no division.

        PRD: "`age_at_cutoff` is the number of full elapsed years from the
        junior's `birth_date` to the season's `age_cutoff_date`, where the
        birthday counts as reached when the month-and-day of the `birth_date`
        falls on or before the month-and-day of the cutoff."

        Design: Corner/entities/member_age_division_is_computed_and_client_value_ignored
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        day_after = validate_success(
            api.register_member(
                f.member_payload(
                    season["id"],
                    full_name="Eli Ward",
                    birth_date="2008-09-01",
                    guardian_email="eli.guardian@example.com",
                    handicap_index=4.0,
                    state_code="TN",
                    publication_opt_in=None,
                ),
                ANONYMOUS,
            ),
            201,
        )
        on_the_cutoff = validate_success(
            api.register_member(
                f.member_payload(
                    season["id"],
                    full_name="Finn Ward",
                    birth_date="2008-08-31",
                    guardian_email="finn.guardian@example.com",
                    handicap_index=4.0,
                    state_code="TN",
                    publication_opt_in=None,
                ),
                ANONYMOUS,
            ),
            201,
        )
        too_young = validate_success(
            api.register_member(
                f.member_payload(
                    season["id"],
                    full_name="Gus Small",
                    birth_date="2016-01-01",
                    guardian_email="gus.guardian@example.com",
                    handicap_index=20.0,
                    handicap_source=HANDICAP_SOURCE_SELF_ATTESTED,
                    state_code="TN",
                    publication_opt_in=None,
                ),
                ANONYMOUS,
            ),
            201,
        )

        assert day_after["age_at_cutoff"] == 17
        assert day_after["age_division"] == DIVISION_U17
        assert on_the_cutoff["age_at_cutoff"] == 18
        assert on_the_cutoff["age_division"] == DIVISION_U19
        assert too_young["age_at_cutoff"] == 10
        assert too_young["age_division"] is None
        assert fx.read_member(api, day_after["id"])["age_division"] == DIVISION_U17
        assert fx.read_member(api, on_the_cutoff["id"])["age_division"] == DIVISION_U19
        assert fx.read_member(api, too_young["id"])["age_division"] is None


class TestEntryWritesAndReads:
    def test_entry_list_combines_filter_offset_and_count(self, api):
        """One filtered page shows the second entry of that event and nothing else.

        PRD: "The response envelope's `meta` object carries four pagination
        fields on list responses — `limit` (the effective page size), `offset`
        (the effective starting position), `total_count` (the number of rows
        matching the filters before the page window is applied), and `has_more`
        (true when rows remain beyond the current window)."

        Design: Corner/entities/entries_list_filters_by_tournament_and_paginates
        """
        ctx = fx.verified_roster(api, 3)
        carolina = fx.create_tournament(api, ctx["season_id"], field_size_limit=4)
        piedmont = fx.create_tournament(
            api, ctx["season_id"], builder=f.october_tournament_payload,
            field_size_limit=4,
        )
        validate_success(api.open_entries(carolina["id"], TOUR_ADMIN), 200)
        validate_success(api.open_entries(piedmont["id"], TOUR_ADMIN), 200)
        first = fx.submit_entry(api, ctx["member_ids"][0], carolina["id"])
        second = fx.submit_entry(api, ctx["member_ids"][1], carolina["id"])
        elsewhere = fx.submit_entry(api, ctx["member_ids"][2], piedmont["id"])

        rows, meta = validate_paginated(
            api.list_entries(
                {"tournament_id": carolina["id"], "limit": 1, "offset": 1}, TOUR_ADMIN
            )
        )

        assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)
        assert len(rows) == 1
        assert rows[0]["id"] == second["id"]
        returned_ids = [row["id"] for row in rows]
        assert first["id"] not in returned_ids
        assert elsewhere["id"] not in returned_ids

    def test_entry_stamps_its_own_identity_status_and_fee_breakdown(self, api):
        """The submitter supplies neither the timestamp nor the money figures.

        PRD: "Once every gate clears, the entry is written. Its `entry_status`
        starts at `APPLIED` and its `submitted_at` is stamped from the logical
        clock — that instant is the primary tie-break inside a priority band, so
        it must be recorded exactly."

        Design: Corner/entities/entry_system_fields_are_server_generated_and_input_ignored
        """
        ctx = fx.entry_open_tournament(api, 1)

        entry = validate_success(
            api.submit_entry(
                f.entry_payload(ctx["member_ids"][0], ctx["tournament_id"]),
                member_headers(ctx["member_ids"][0]),
            ),
            201,
        )

        assert_identity_fields(entry, expected_version=1)
        assert entry["submitted_at"].startswith("2026-08-10T00:00:00")
        assert entry["entry_status"] == ENTRY_APPLIED
        assert_cents(entry["gross_fee_cents"], STANDARD_ENTRY_FEE_CENTS, "gross_fee_cents")
        assert_cents(entry["late_entry_surcharge_cents"], 0, "late_entry_surcharge_cents")
        assert_cents(entry["aid_award_cents"], 0, "aid_award_cents")
        assert_cents(entry["net_fee_due_cents"], STANDARD_ENTRY_FEE_CENTS,
                     "net_fee_due_cents")
        assert entry["fee_status"] == FEE_UNPAID
        assert_cents(entry["amount_paid_cents"], 0, "amount_paid_cents")
        assert entry["rank_at_entry"] is None
        assert entry["waitlist_position"] is None

    def test_entry_body_foreign_key_to_a_missing_event_is_dereferenced(self, api):
        """A body-borne tournament reference is resolved before any row is written.

        PRD: "Then an unresolvable `tournament_id`, `tournamentId`,
        `source_tournament_id` or `qualifies_into_tournament_id` yields
        `ERR_TOURNAMENT_NOT_FOUND`, on every endpoint carrying any of the four."

        Design: Corner/entities/entry_foreign_key_to_unknown_tournament_is_rejected
        """
        ctx = fx.verified_roster(api, 1)
        member_id = ctx["member_ids"][0]

        response = api.submit_entry(
            f.entry_payload(member_id, NON_EXISTENT_UUID), member_headers(member_id)
        )

        validate_error(response, ERR_TOURNAMENT_NOT_FOUND, 404)
        rows, meta = validate_paginated(
            api.list_entries({"member_id": member_id}, TOUR_ADMIN)
        )
        assert_pagination_meta(meta, total_count=0)
        assert rows == []


class TestSchedulingAndExemptionReferents:
    def test_unknown_tournament_read_answers_not_found(self, api):
        """An event that was never scheduled is a 404, not an empty success.

        PRD: "Then an unresolvable `tournament_id`, `tournamentId`,
        `source_tournament_id` or `qualifies_into_tournament_id` yields
        `ERR_TOURNAMENT_NOT_FOUND`, on every endpoint carrying any of the four."

        Design: Corner/entities/tournament_not_found_on_unknown_identifier
        """
        validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        response = api.get_tournament(NON_EXISTENT_UUID, TOUR_ADMIN)

        validate_error(response, ERR_TOURNAMENT_NOT_FOUND, 404)

    def test_tournament_tier_outside_the_band_set_is_refused(self, api):
        """An unknown strength band never reaches the ranking arithmetic.

        PRD: "A `TourAdmin` supplies the owning `season_id`, the event `name` (1
        to 120 characters), the `division` it is played in — one of `U13`, `U15`,
        `U17` or `U19` — and its `tier`, which is the event-strength band and is
        one of `LOCAL`, `REGIONAL`, `NATIONAL` or `INVITATIONAL`."

        Design: Corner/entities/tournament_tier_rejects_value_outside_enum
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        response = api.create_tournament(
            f.tournament_payload(season["id"], name="Bad Tier Event", tier="MAJOR"),
            TOUR_ADMIN,
        )

        validate_error(response, ERR_INVALID_REQUEST, 422)
        rows, meta = validate_paginated(
            api.list_tournaments({"season_id": season["id"]}, TOUR_ADMIN)
        )
        assert_pagination_meta(meta, total_count=0)
        assert rows == []

    def test_exemption_grant_for_an_unknown_junior_answers_member_not_found(self, api):
        """The junior is resolved before the event that would happily take the grant.

        PRD: "Then a `member_id` or `memberId` that does not resolve yields
        `ERR_MEMBER_NOT_FOUND`, on every endpoint that carries either."

        Design: Corner/entities/exemption_grant_requires_an_existing_member
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)
        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        response = api.create_exemption_grant(
            f.exemption_grant_payload(
                NON_EXISTENT_UUID, tournament["id"], EXEMPTION_SPONSOR_INVITE,
                "2026-09-01T00:00:00Z",
            ),
            TOUR_ADMIN,
        )

        validate_error(response, ERR_MEMBER_NOT_FOUND, 404)
        rows, meta = validate_paginated(
            api.list_exemption_grants({"tournament_id": tournament["id"]}, TOUR_ADMIN)
        )
        assert_pagination_meta(meta, total_count=0)
        assert rows == []
