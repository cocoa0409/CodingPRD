"""Edition posture machine gates (PRD §2.5 plus the per-transition gates of
§3.1, §3.3, §3.5, §3.6, §3.8, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_category_config_payload,
    fx_invited, fx_responded, fx_screening, fx_voting_open,
    set_clock,
    st_advance, st_deliberate, st_edition, st_film, st_lock, st_rule,
    st_slate, st_submitter,
    make_filmmaker_headers, make_juror_headers,
    validate_error, validate_success,
)


class TestAdvanceShape:
    def test_edition_advance_invalid_from_rejected(self, api, admin_headers):
        """PRD §2.5: "A request to advance to a phase that is not the declared
        next phase is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/edition_advance_invalid_from_rejected
        """
        ctx = st_edition(with_config=False)
        resp = api.advance_edition(ctx["edition"]["id"], "SCREENING", admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        edition = validate_success(api.get_edition(ctx["edition"]["id"], admin_headers))
        assert edition["status"] == "SETUP"

    def test_edition_open_requires_category_config(self, api, admin_headers):
        """PRD §3.1: "Advancing from `SETUP` to `INTAKE_OPEN` requires that at
        least one category configuration exist for the edition; otherwise the
        advance is rejected with `ERR_NO_CATEGORY_CONFIG`."

        Design: Corner/state_machines/edition_open_requires_category_config
        """
        ctx = st_edition(with_config=False)
        resp = api.advance_edition(ctx["edition"]["id"], "INTAKE_OPEN", admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_CATEGORY_CONFIG.value)

        created = validate_success(api.create_category_config(
            create_category_config_payload(ctx["edition"]["id"]), admin_headers,
        ), 201)
        assert created["edition_id"] == ctx["edition"]["id"]

        advanced = validate_success(
            api.advance_edition(ctx["edition"]["id"], "INTAKE_OPEN", admin_headers)
        )
        assert advanced["status"] == "INTAKE_OPEN"


class TestScreeningExitGates:
    def test_edition_scoring_incomplete_gate(self, api, admin_headers):
        """PRD §3.3: advancing SCREENING → DELIBERATION requires that "every
        film in `IN_SCREENING` must hold at least its category's
        `screener_count_required` assignments in `SCORED` status, failing with
        `ERR_SCORING_INCOMPLETE`."

        Design: Corner/state_machines/edition_scoring_incomplete_gate
        """
        # One score against a required count of two.
        ctx = fx_screening(films=[{"title": "Gate Film",
                                   "scores": [("STAFF", 8)]}])
        resp = api.advance_edition(ctx["edition"]["id"], "DELIBERATION", admin_headers)
        validate_error(resp, ApiErrorId.ERR_SCORING_INCOMPLETE.value)
        edition = validate_success(api.get_edition(ctx["edition"]["id"], admin_headers))
        assert edition["status"] == "SCREENING"

    def test_edition_eligibility_pending_gate(self, api, admin_headers):
        """PRD §3.3: "no submission may remain in `SUBMITTED` or `NEEDS_INFO`,
        failing with `ERR_ELIGIBILITY_DECISIONS_PENDING`."

        Design: Corner/state_machines/edition_eligibility_pending_gate
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        st_film(ctx, submitter, {"title": "Pending Film"})  # SUBMITTED, no ruling
        st_advance(ctx, "INTAKE_CLOSED")
        st_advance(ctx, "SCREENING")
        resp = api.advance_edition(ctx["edition"]["id"], "DELIBERATION", admin_headers)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_DECISIONS_PENDING.value)
        edition = validate_success(api.get_edition(ctx["edition"]["id"], admin_headers))
        assert edition["status"] == "SCREENING"


class TestSlatePhaseGates:
    def test_edition_slates_unlocked_gate(self, api, admin_headers):
        """PRD §3.5: "The edition itself cannot advance `DELIBERATION` →
        `SLATE_LOCKED` until at least one slate exists and every slate of the
        edition is `LOCKED`, failing with `ERR_SLATES_UNLOCKED`."

        Design: Corner/state_machines/edition_slates_unlocked_gate
        """
        ctx = fx_screening()
        st_advance(ctx, "DELIBERATION")
        slate = st_slate(ctx, section="SHORTS", capacity_slots=1)
        st_deliberate(slate["id"])  # DELIBERATING, never locked
        resp = api.advance_edition(ctx["edition"]["id"], "SLATE_LOCKED", admin_headers)
        validate_error(resp, ApiErrorId.ERR_SLATES_UNLOCKED.value)
        edition = validate_success(api.get_edition(ctx["edition"]["id"], admin_headers))
        assert edition["status"] == "DELIBERATION"

    def test_edition_invitations_pending_gate(self, api, admin_headers):
        """PRD §3.6: "The edition leaves `NOTIFICATION` for `SCHEDULING` only
        when every invitation has been answered or swept: any entry still
        `INVITED` blocks the advance with `ERR_INVITATIONS_PENDING`."

        Design: Corner/state_machines/edition_invitations_pending_gate
        """
        ctx = fx_invited(films=1, capacity_slots=1)
        entry = ctx["entries"][0]
        resp = api.advance_edition(ctx["edition"]["id"], "SCHEDULING", admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVITATIONS_PENDING.value)

        film = ctx["films"][0]
        answered = validate_success(api.respond_to_entry(
            entry["id"], True, make_filmmaker_headers(film["submitter"]["id"]),
        ))
        assert answered["status"] == "CONFIRMED"

        advanced = validate_success(
            api.advance_edition(ctx["edition"]["id"], "SCHEDULING", admin_headers)
        )
        assert advanced["status"] == "SCHEDULING"

    def test_edition_festival_not_started_gate(self, api, admin_headers):
        """PRD §3.8: "the administrator advances the edition `SCHEDULING` →
        `FESTIVAL_LIVE`, which requires the logical clock to read at or after
        `festival_start_at`, failing with `ERR_FESTIVAL_NOT_STARTED`."

        Design: Corner/state_machines/edition_festival_not_started_gate
        """
        ctx = fx_responded(films=1, capacity_slots=1, sign_agreements=False)
        st_advance(ctx, "SCHEDULING")
        set_clock("2027-01-01T00:00:00Z")  # before festival_start_at
        resp = api.advance_edition(ctx["edition"]["id"], "FESTIVAL_LIVE", admin_headers)
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_STARTED.value)

        set_clock("2027-01-21T00:00:00Z")  # exactly at the start (inclusive)
        advanced = validate_success(
            api.advance_edition(ctx["edition"]["id"], "FESTIVAL_LIVE", admin_headers)
        )
        assert advanced["status"] == "FESTIVAL_LIVE"


class TestAwardsPendingGate:
    def test_edition_awards_pending_gate(self, api, admin_headers,
                                         director_headers, awards_headers):
        """PRD §3.9: "The season ends when the administrator advances the
        edition `AWARDS_NIGHT` → `CLOSED`, permitted only when every award of
        the edition has been disbursed — any award short of `DISBURSED` blocks
        the close with `ERR_AWARDS_PENDING`"; disbursement "pays the prize in
        full — `disbursed_amount_cents` equals `prize_cents`"; and announcing
        "appends the award's name to the winning submission's `award_names`."

        Design: Corner/state_machines/edition_awards_pending_gate
        """
        ctx = fx_voting_open(films=1, num_jurors=1)
        award = ctx["award"]
        juror = ctx["jurors"][0]
        film_id = ctx["films"][0]["film"]["id"]
        ballot = api.cast_ballot(award["id"], [film_id],
                                 make_juror_headers(juror["id"]))
        validate_success(ballot, 201)
        tallied = validate_success(api.tally_award(award["id"], awards_headers))
        assert tallied["status"] == "TALLIED"

        st_advance(ctx, "AWARDS_NIGHT")
        blocked = api.advance_edition(ctx["edition"]["id"], "CLOSED", admin_headers)
        validate_error(blocked, ApiErrorId.ERR_AWARDS_PENDING.value)

        announced = validate_success(api.announce_award(award["id"], director_headers))
        assert announced["status"] == "ANNOUNCED"
        film = validate_success(api.get_submission(film_id, admin_headers))
        assert award["name"] in film["award_names"]

        disbursed = validate_success(api.disburse_award(award["id"], awards_headers))
        assert disbursed["status"] == "DISBURSED"
        assert disbursed["disbursed_amount_cents"] == award["prize_cents"]

        closed = validate_success(
            api.advance_edition(ctx["edition"]["id"], "CLOSED", admin_headers)
        )
        assert closed["status"] == "CLOSED"
        edition = validate_success(api.get_edition(ctx["edition"]["id"], admin_headers))
        assert edition["prize_disbursed_cents"] == award["prize_cents"]
