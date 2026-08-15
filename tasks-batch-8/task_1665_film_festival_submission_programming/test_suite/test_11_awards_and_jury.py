"""Awards: jury panels, ballots, provisional standings vs the official IRV
tally, and the prize pool (PRD §2.6, §3.9)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    fx_festival_live, fx_voting_open,
    make_juror_headers,
    set_clock,
    st_award, st_ballot, st_edition, st_juror,
    validate_error, validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AWARDS = TEST_USERS["awards_headers"]


def _three_film_award(api, num_jurors):
    """Three PROGRAMMED shorts on a capacity-3 slate; voting open."""
    ctx = fx_voting_open(
        films=[{"title": "Film A"}, {"title": "Film B"}, {"title": "Film C"}],
        num_jurors=num_jurors, capacity_slots=3,
    )
    return ctx


class TestBallotImmutability:
    def test_juryvote_immutable_no_version_field(self, api):
        """PRD §2.6: "A jury vote carries only `id` and `created_at`: both
        `updated_at` and `version` are absent from it, because a ballot is
        immutable once cast"; §3.9: "The ballot's `juror_id` is stamped from
        the caller's `X-User-ID` and its `submitted_at` from the logical
        clock."

        Design: Corner/entities/juryvote_immutable_no_version_field
        """
        ctx = fx_voting_open(films=1, num_jurors=1)
        award = ctx["award"]
        juror = ctx["jurors"][0]
        film_id = ctx["films"][0]["film"]["id"]

        ballot = st_ballot(award["id"], juror["id"], [film_id])
        assert ballot["id"]
        assert ballot["created_at"]
        assert ballot["juror_id"] == juror["id"]
        assert ballot["award_id"] == award["id"]
        assert ballot["submitted_at"]
        assert "version" not in ballot, "a ballot carries no version field"
        assert "updated_at" not in ballot, "a ballot carries no updated_at field"


class TestBallotGuards:
    def test_juror_panel_coi_ballot_and_quorum_guards(self, api):
        """PRD §3.9: "a juror not listed in the award's `assigned_juror_ids`
        is rejected with `ERR_JUROR_NOT_ON_PANEL`"; "a ballot ranking a film
        whose `production_company` appears in the juror's
        `coi_production_companies` is rejected with `ERR_JUROR_CONFLICT`";
        "a ballot ranking anything else, an empty ballot, or a ballot with
        duplicates is rejected with `ERR_BALLOT_INVALID`"; "a second ballot
        is rejected with `ERR_BALLOT_EXISTS`"; and the tally "requires
        quorum: the number of ballots submitted must be at least half the
        panel size rounded up — that is, the count of `assigned_juror_ids`
        divided by two, rounded up — failing with `ERR_QUORUM_NOT_MET`."

        Design: Corner/validations/juror_panel_coi_ballot_and_quorum_guards
        """
        ctx = fx_festival_live(
            films=[{"title": "Juried",
                    "submission_over": {"production_company": "A Co"}}],
            capacity_slots=1,
        )
        edition_id = ctx["edition"]["id"]
        film_id = ctx["films"][0]["film"]["id"]
        j_on = st_juror(edition_id, {"display_name": "Juror On"})
        j_coi = st_juror(edition_id, {"display_name": "Juror Conflict",
                                      "coi_production_companies": ["A Co"]})
        j3 = st_juror(edition_id, {"display_name": "Juror Three"})
        j_out = st_juror(edition_id, {"display_name": "Juror Out"})

        award = st_award(edition_id, [j_on["id"], j_coi["id"], j3["id"]],
                         {"name": "Shorts Prize", "prize_cents": 2500000})
        validate_success(api.open_voting(award["id"], AWARDS))

        not_on_panel = api.cast_ballot(
            award["id"], [film_id], make_juror_headers(j_out["id"]),
        )
        validate_error(not_on_panel, ApiErrorId.ERR_JUROR_NOT_ON_PANEL.value)

        conflict = api.cast_ballot(
            award["id"], [film_id], make_juror_headers(j_coi["id"]),
        )
        validate_error(conflict, ApiErrorId.ERR_JUROR_CONFLICT.value)

        duplicates = api.cast_ballot(
            award["id"], [film_id, film_id], make_juror_headers(j_on["id"]),
        )
        validate_error(duplicates, ApiErrorId.ERR_BALLOT_INVALID.value)

        non_candidate = api.cast_ballot(
            award["id"], [NON_EXISTENT_UUID], make_juror_headers(j_on["id"]),
        )
        validate_error(non_candidate, ApiErrorId.ERR_BALLOT_INVALID.value)

        no_quorum = api.tally_award(award["id"], AWARDS)
        validate_error(no_quorum, ApiErrorId.ERR_QUORUM_NOT_MET.value)

        st_ballot(award["id"], j_on["id"], [film_id])
        second = api.cast_ballot(
            award["id"], [film_id], make_juror_headers(j_on["id"]),
        )
        validate_error(second, ApiErrorId.ERR_BALLOT_EXISTS.value)

        st_ballot(award["id"], j3["id"], [film_id])  # quorum: 2 of ceil(3/2)
        tallied = validate_success(api.tally_award(award["id"], AWARDS))
        assert tallied["status"] == "TALLIED"
        assert tallied["winner_submission_id"] == film_id


class TestIrvTally:
    def test_provisional_standings_diverge_from_irv_winner(self, api, awards_headers):
        """PRD §3.9: "While voting is open, observers may consult the
        provisional standings, which report raw first-preference counts per
        candidate in `first_preference_counts` and the current leaders in
        `provisional_leaders`. These standings are deliberately provisional —
        a film can lead on first preferences and still lose the runoff, as
        the tally below shows."

        Design: Difficulty/dual_variant_calc/jury_first_preference_vs_irv_winner
        """
        ctx = _three_film_award(api, num_jurors=5)
        award = ctx["award"]
        jurors = ctx["jurors"]
        a, b, c = (ctx["films"][i]["film"]["id"] for i in range(3))

        st_ballot(award["id"], jurors[0]["id"], [a, c])
        st_ballot(award["id"], jurors[1]["id"], [a, c])
        st_ballot(award["id"], jurors[2]["id"], [b, a])
        st_ballot(award["id"], jurors[3]["id"], [b, a])
        st_ballot(award["id"], jurors[4]["id"], [c, b])

        standings = validate_success(
            api.get_award_standings(award["id"], awards_headers)
        )
        counts = standings["first_preference_counts"]
        assert counts.get(a) == 2
        assert counts.get(b) == 2
        assert counts.get(c) == 1
        assert set(standings["provisional_leaders"]) == {a, b}, (
            "A and B tie on first preferences at 2 each"
        )

    def test_official_irv_tally_crowns_runoff_winner(self, api, awards_headers):
        """PRD §3.9: "A worked example with five ballots — two ranking A over
        C, two ranking B over A, one ranking C over B — counts first
        preferences at two for A, two for B, and one for C; C is eliminated,
        its ballot transfers to B, and B wins three to two even though A had
        tied B on first preferences."

        Design: Difficulty/dual_variant_calc/jury_first_preference_vs_irv_winner
        """
        ctx = _three_film_award(api, num_jurors=5)
        award = ctx["award"]
        jurors = ctx["jurors"]
        a, b, c = (ctx["films"][i]["film"]["id"] for i in range(3))

        st_ballot(award["id"], jurors[0]["id"], [a, c])
        st_ballot(award["id"], jurors[1]["id"], [a, c])
        st_ballot(award["id"], jurors[2]["id"], [b, a])
        st_ballot(award["id"], jurors[3]["id"], [b, a])
        st_ballot(award["id"], jurors[4]["id"], [c, b])

        tallied = validate_success(api.tally_award(award["id"], awards_headers))
        assert tallied["status"] == "TALLIED"
        assert tallied["winner_submission_id"] == b, (
            "C eliminated as unique-lowest; its ballot transfers to B; "
            "B holds 3 of 5 active ballots"
        )

    def test_irv_tiebreak_earliest_ballot_latest_loses(self, api, awards_headers):
        """PRD §3.9: "when several candidates tie for fewest, the eliminated
        one is the tied candidate whose earliest current first-preference
        ballot — ordered by the ballot's `submitted_at`, then by its
        `created_at` — is the latest"; the transferred ballot then decides:
        "A ballot whose ranked candidates have all been eliminated becomes
        exhausted and leaves the active set" — here it transfers to A.

        Design: Corner/calculations/irv_tiebreak_earliest_ballot_latest_loses
        """
        ctx = _three_film_award(api, num_jurors=3)
        award = ctx["award"]
        jurors = ctx["jurors"]
        a, b, c = (ctx["films"][i]["film"]["id"] for i in range(3))

        set_clock("2027-01-22T00:00:00Z")
        st_ballot(award["id"], jurors[0]["id"], [a, b])
        set_clock("2027-01-23T00:00:00Z")
        st_ballot(award["id"], jurors[1]["id"], [b, c])
        set_clock("2027-01-24T00:00:00Z")
        st_ballot(award["id"], jurors[2]["id"], [c, a])

        tallied = validate_success(api.tally_award(award["id"], awards_headers))
        assert tallied["status"] == "TALLIED"
        # Round 1: A/B/C tie at 1 first preference each; C's earliest
        # first-preference ballot (01-24) is the latest, so C is eliminated;
        # C's ballot transfers to A; A leads 2-1 and wins the majority.
        assert tallied["winner_submission_id"] == a
        assert isinstance(tallied["rounds_log"], list)
        assert len(tallied["rounds_log"]) >= 1


class TestPrizePool:
    def test_prize_pool_exhaustion(self, api, awards_headers, admin_headers):
        """PRD §3.9: "`prize_cents` may not exceed `prize_pool_cents` minus
        the prizes of every award already created for the edition — awards
        are never cancelled, so each existing award, even a disbursed one,
        remains charged against the pool — and an overdraw is rejected with
        `ERR_PRIZE_POOL_EXHAUSTED`"; §2.8: "`prize_committed_cents` sums
        `prize_cents` over awards in `SETUP`, `VOTING_OPEN`, `TALLIED`,
        `ANNOUNCED`, or `DISBURSED` status".

        Design: Corner/calculations/prize_pool_exhaustion
        """
        ctx = st_edition(with_config=False)
        edition_id = ctx["edition"]["id"]
        juror = st_juror(edition_id, {"display_name": "Juror One"})

        first = validate_success(api.create_award(
            {"edition_id": edition_id, "name": "Prize One", "section": "SHORTS",
             "prize_cents": 2500000, "assigned_juror_ids": [juror["id"]]},
            awards_headers,
        ), 201)
        second = validate_success(api.create_award(
            {"edition_id": edition_id, "name": "Prize Two",
             "section": "US_DRAMATIC", "prize_cents": 2500000,
             "assigned_juror_ids": [juror["id"]]},
            awards_headers,
        ), 201)
        assert first["status"] == "SETUP" and second["status"] == "SETUP"

        overdraw = api.create_award(
            {"edition_id": edition_id, "name": "Prize Three", "section": "NEXT",
             "prize_cents": 1, "assigned_juror_ids": [juror["id"]]},
            awards_headers,
        )
        validate_error(overdraw, ApiErrorId.ERR_PRIZE_POOL_EXHAUSTED.value)

        edition = validate_success(api.get_edition(edition_id, admin_headers))
        assert edition["prize_committed_cents"] == 5000000
