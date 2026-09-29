"""The refusal gates: division, handicap, duplication, windows, money, consent."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AID_ALLOCATION_EXHAUSTED,
    ERR_AID_BUDGET_EXHAUSTED,
    ERR_AID_NOT_APPROVED,
    ERR_DIVISION_MISMATCH,
    ERR_DUPLICATE_ENTRY,
    ERR_EMPTY_FIELD,
    ERR_ENTRY_WINDOW_CLOSED,
    ERR_EXEMPTION_NOT_APPLICABLE,
    ERR_HANDICAP_ABOVE_LIMIT,
    ERR_HANDICAP_STALE,
    ERR_INCOME_INELIGIBLE,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_PUBLICATION_NOT_CONSENTED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_entry_status,
    assert_fee_status,
    assert_grant_status,
    assert_ledger,
    assert_slot_census,
    assert_tournament_status,
    assert_two_decimals,
)
from test_helpers.constants import (
    PER_MEMBER_CAP_CENTS,
    SEASON_ASSISTANCE_BUDGET_CENTS,
    STANDARD_ENTRY_FEE_CENTS,
)
from test_helpers.test_users import COACH, COACH_USER_ID, TOUR_ADMIN, member_headers
from test_helpers.types import (
    AID_APPROVED,
    AID_DECISION_APPROVED,
    AID_DECISION_DENIED,
    AID_DENIED,
    AID_SUBMITTED,
    COACH_GRANT_REQUESTED,
    DIVISION_U15,
    DIVISION_U17,
    ENTRY_APPLIED,
    EXEMPTION_NATIONAL_TEAM,
    EXEMPTION_SPONSOR_INVITE,
    FEE_AID_COVERED,
    FEE_PAID,
    FEE_UNPAID,
    GRANT_ACTIVE,
    GRANT_EXPIRED,
    HANDICAP_SOURCE_SELF_ATTESTED,
    TIER_LOCAL,
    TIER_NATIONAL,
    TOURNAMENT_ENTRY_OPEN,
    TOURNAMENT_FIELD_SET,
)


class TestEntryEligibilityGates:
    def test_entry_into_the_wrong_age_division_is_refused(self, api):
        """A U17 junior cannot buy into a U15 event, and nothing is written.

        PRD: "The junior's `age_division` must equal the tournament's
        `division`, or `ERR_DIVISION_MISMATCH`."

        Design: Corner/validations/entry_into_the_wrong_age_division_is_rejected
        """
        ctx = fx.entry_open_tournament(
            api, member_count=1, division=DIVISION_U15, name="Piedmont U15 Classic"
        )
        member_id = ctx["member_ids"][0]
        assert ctx["members"][0]["age_division"] == DIVISION_U17

        response = api.submit_entry(
            f.entry_payload(member_id, ctx["tournament_id"]),
            member_headers(member_id),
        )
        validate_error(response, ERR_DIVISION_MISMATCH, 409)

        tournament = fx.read_tournament(api, ctx["tournament_id"])
        assert_slot_census(tournament, entry_count=0, applied_count=0)

    def test_a_handicap_exactly_on_the_ceiling_still_enters(self, api):
        """12.5 is turned away by an 8.4 ceiling while 8.4 itself is admitted.

        PRD: "The junior's `handicap_index` must be less than or equal to the
        tournament's `max_handicap_index` — equality passes — or
        `ERR_HANDICAP_ABOVE_LIMIT`."

        Design: Corner/validations/handicap_above_the_ceiling_is_rejected_but_equal_is_accepted
        """
        ctx = fx.entry_open_tournament(
            api,
            member_count=3,
            member_overrides={1: {"handicap_index": 12.5}, 2: {"handicap_index": 8.4}},
            field_size_limit=4,
        )
        over_ceiling = ctx["member_ids"][1]
        on_ceiling = ctx["member_ids"][2]

        refused = api.submit_entry(
            f.entry_payload(over_ceiling, ctx["tournament_id"]),
            member_headers(over_ceiling),
        )
        validate_error(refused, ERR_HANDICAP_ABOVE_LIMIT, 409)

        accepted = validate_success(
            api.submit_entry(
                f.entry_payload(on_ceiling, ctx["tournament_id"]),
                member_headers(on_ceiling),
            ),
            201,
        )
        assert_entry_status(accepted, ENTRY_APPLIED)
        assert_cents(accepted["gross_fee_cents"], STANDARD_ENTRY_FEE_CENTS, "gross fee")

        tournament = fx.read_tournament(api, ctx["tournament_id"])
        assert_slot_census(tournament, entry_count=1, applied_count=1)

    def test_the_handicap_freshness_window_reaches_back_exactly_180_days(self, api):
        """At a 2026-08-10 clock a 2026-02-11 index enters and 2026-02-10 does not.

        PRD: "The handicap must be both fresh and adequately sourced: its
        `handicap_effective_date` must be no more than 180 days before the
        logical clock, **and** its `handicap_source` must not be
        `SELF_ATTESTED` when the tournament's `tier` is `NATIONAL` or
        `INVITATIONAL`; either failure yields `ERR_HANDICAP_STALE`."

        Design: Corner/validations/handicap_older_than_the_validity_window_is_rejected_at_the_day_boundary
        """
        ctx = fx.verified_roster(
            api,
            member_count=3,
            clock="2026-07-01T00:00:00Z",
            member_overrides={
                0: {"handicap_effective_date": "2026-02-10"},
                2: {"handicap_effective_date": "2026-02-11"},
            },
        )
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        tournament = fx.create_tournament(api, ctx["season_id"], field_size_limit=4)
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        one_day_stale = ctx["member_ids"][0]
        just_fresh = ctx["member_ids"][2]

        refused = api.submit_entry(
            f.entry_payload(one_day_stale, tournament["id"]),
            member_headers(one_day_stale),
        )
        validate_error(refused, ERR_HANDICAP_STALE, 409)

        accepted = validate_success(
            api.submit_entry(
                f.entry_payload(just_fresh, tournament["id"]),
                member_headers(just_fresh),
            ),
            201,
        )
        assert_entry_status(accepted, ENTRY_APPLIED)
        assert_slot_census(
            fx.read_tournament(api, tournament["id"]), entry_count=1, applied_count=1
        )

    def test_a_self_attested_index_is_barred_only_from_the_top_tiers(self, api):
        """The same fresh self-attested figure fails NATIONAL and passes REGIONAL.

        PRD: "A junior may bring a self-attested figure to a `LOCAL` or
        `REGIONAL` event, but the two strongest tiers demand a `WHS_CLUB` or
        `STATE_ASSOC` index."

        Design: Corner/validations/self_attested_handicap_is_refused_only_at_the_top_tiers
        """
        ctx = fx.verified_roster(
            api,
            member_count=1,
            member_overrides={0: {"handicap_source": HANDICAP_SOURCE_SELF_ATTESTED}},
        )
        member_id = ctx["member_ids"][0]
        assert ctx["members"][0]["handicap_source"] == HANDICAP_SOURCE_SELF_ATTESTED

        national = fx.create_tournament(
            api,
            ctx["season_id"],
            name="US Junior National",
            tier=TIER_NATIONAL,
            course_rating=72.0,
            slope_rating=130,
            field_size_limit=4,
        )
        regional = fx.create_tournament(
            api,
            ctx["season_id"],
            f.october_tournament_payload,
            entry_fee_cents=20000,
            course_rating=70.0,
            slope_rating=120,
            field_size_limit=4,
        )
        validate_success(api.open_entries(national["id"], TOUR_ADMIN), 200)
        validate_success(api.open_entries(regional["id"], TOUR_ADMIN), 200)

        refused = api.submit_entry(
            f.entry_payload(member_id, national["id"]), member_headers(member_id)
        )
        validate_error(refused, ERR_HANDICAP_STALE, 409)

        accepted = validate_success(
            api.submit_entry(
                f.entry_payload(member_id, regional["id"]), member_headers(member_id)
            ),
            201,
        )
        assert_entry_status(accepted, ENTRY_APPLIED)
        assert_cents(accepted["gross_fee_cents"], 20000, "gross fee")
        assert_slot_census(fx.read_tournament(api, national["id"]), entry_count=0)
        assert_slot_census(fx.read_tournament(api, regional["id"]), entry_count=1)

    def test_a_second_entry_into_the_same_event_is_a_duplicate(self, api):
        """A live APPLIED entry bars a second submission for the same event.

        PRD: "Duplication is then barred: the junior must have no existing
        entry for this tournament in any status other than `WITHDRAWN`,
        `REJECTED` or `CANCELLED`, or the submission is refused with
        `ERR_DUPLICATE_ENTRY`."

        Design: Corner/validations/second_entry_into_the_same_tournament_is_a_duplicate
        """
        ctx = fx.entry_open_tournament(api, member_count=1, field_size_limit=4)
        member_id = ctx["member_ids"][0]
        first = fx.submit_entry(api, member_id, ctx["tournament_id"])

        second = api.submit_entry(
            f.entry_payload(member_id, ctx["tournament_id"]),
            member_headers(member_id),
        )
        validate_error(second, ERR_DUPLICATE_ENTRY, 409)

        assert_entry_status(fx.read_entry(api, first["id"]), ENTRY_APPLIED)
        assert_slot_census(
            fx.read_tournament(api, ctx["tournament_id"]),
            entry_count=1,
            applied_count=1,
        )

    def test_an_entry_one_second_before_the_window_opens_is_refused(self, api):
        """The gate is the clock against entry_open_at, not the event's state.

        PRD: "The entry window is checked next: the logical clock must be at or
        after `entry_open_at` and strictly before `entry_close_at`, or the
        submission is refused with `ERR_ENTRY_WINDOW_CLOSED`."

        Design: Corner/validations/entry_before_the_window_opens_is_rejected
        """
        ctx = fx.entry_open_tournament(
            api,
            member_count=1,
            clock=fx.CLOCK_BEFORE_ENTRY_OPEN,
            field_size_limit=4,
        )
        member_id = ctx["member_ids"][0]
        assert_tournament_status(ctx["tournament"], TOURNAMENT_ENTRY_OPEN)

        fx.set_clock(api, "2026-08-04T23:59:59Z")
        refused = api.submit_entry(
            f.entry_payload(member_id, ctx["tournament_id"]),
            member_headers(member_id),
        )
        validate_error(refused, ERR_ENTRY_WINDOW_CLOSED, 409)

        fx.set_clock(api, "2026-08-05T00:00:00Z")
        accepted = validate_success(
            api.submit_entry(
                f.entry_payload(member_id, ctx["tournament_id"]),
                member_headers(member_id),
            ),
            201,
        )
        assert_entry_status(accepted, ENTRY_APPLIED)
        assert accepted["submitted_at"].startswith("2026-08-05T00:00:00")
        assert_slot_census(
            fx.read_tournament(api, ctx["tournament_id"]), entry_count=1
        )


class TestExemptionAndAssistanceReferents:
    def test_an_expired_grant_and_another_junior_s_grant_share_one_refusal(self, api):
        """Both a lapsed own grant and a live foreign grant are inapplicable.

        PRD: "An invoked exemption is then checked on four counts at once: the
        referenced grant must be `ACTIVE`, must belong to the entering junior,
        must name this very tournament, and must have an `expires_at` strictly
        after the logical clock."

        Design: Corner/validations/expired_or_foreign_exemption_grant_is_not_applicable
        """
        ctx = fx.scheduled_tournament(
            api,
            member_count=2,
            clock="2026-08-06T00:00:00Z",
            field_size_limit=4,
        )
        entrant, other = ctx["member_ids"]
        lapsed = fx.create_exemption_grant(
            api, entrant, ctx["tournament_id"], EXEMPTION_SPONSOR_INVITE,
            "2026-08-09T00:00:00Z",
        )
        foreign = fx.create_exemption_grant(
            api, other, ctx["tournament_id"], EXEMPTION_NATIONAL_TEAM,
            "2026-09-01T00:00:00Z",
        )
        validate_success(api.open_entries(ctx["tournament_id"], TOUR_ADMIN), 200)
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)

        on_lapsed = api.submit_entry(
            f.entry_payload(
                entrant, ctx["tournament_id"], exemption_grant_id=lapsed["id"]
            ),
            member_headers(entrant),
        )
        validate_error(on_lapsed, ERR_EXEMPTION_NOT_APPLICABLE, 409)

        on_foreign = api.submit_entry(
            f.entry_payload(
                entrant, ctx["tournament_id"], exemption_grant_id=foreign["id"]
            ),
            member_headers(entrant),
        )
        validate_error(on_foreign, ERR_EXEMPTION_NOT_APPLICABLE, 409)

        lapsed_now = validate_success(
            api.get_exemption_grant(lapsed["id"], TOUR_ADMIN), 200
        )
        assert_grant_status(lapsed_now, GRANT_EXPIRED)
        assert lapsed_now["consumed_by_entry_id"] is None
        foreign_now = validate_success(
            api.get_exemption_grant(foreign["id"], TOUR_ADMIN), 200
        )
        assert_grant_status(foreign_now, GRANT_ACTIVE)
        assert foreign_now["consumed_by_entry_id"] is None
        assert_slot_census(
            fx.read_tournament(api, ctx["tournament_id"]), entry_count=0
        )

    def test_assistance_on_an_undecided_application_is_refused(self, api):
        """A SUBMITTED application cannot fund an entry and the purse is untouched.

        PRD: "When `request_assistance` is true, the junior must hold exactly
        one `APPROVED` assistance application for the tournament's season and
        the supplied `aid_application_id` must be that row; otherwise
        `ERR_AID_NOT_APPROVED`."

        Design: Corner/validations/assistance_request_without_an_approved_application_is_rejected
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        application = fx.submit_aid_application(
            api, member_id, ctx["season_id"], household_income_cents=1200000
        )
        assert application["status"] == AID_SUBMITTED

        tournament = fx.create_tournament(api, ctx["season_id"], field_size_limit=4)
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        refused = api.submit_entry(
            f.entry_payload(
                member_id,
                tournament["id"],
                request_assistance=True,
                aid_application_id=application["id"],
            ),
            member_headers(member_id),
        )
        validate_error(refused, ERR_AID_NOT_APPROVED, 409)

        assert_slot_census(fx.read_tournament(api, tournament["id"]), entry_count=0)
        assert_ledger(
            fx.read_season(api, ctx["season_id"]),
            available=SEASON_ASSISTANCE_BUDGET_CENTS,
            committed=0,
        )
        stored = validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )
        assert_cents(stored["consumed_cents"], 0, "consumed")


class TestAssistanceMoneyGates:
    def test_a_household_above_the_top_band_cannot_be_approved(self, api):
        """Approval needs a positive covered share; denial of the same row stands.

        PRD: "Approval is permitted only when the computed `covered_pct` is
        strictly greater than 0.00; an application from a household above the
        top income band is refused with `ERR_INCOME_INELIGIBLE`."

        Design: Corner/validations/approval_of_an_income_ineligible_application_is_refused
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        application = fx.submit_aid_application(
            api, member_id, ctx["season_id"], household_income_cents=8000000
        )
        assert_cents(
            application["income_per_dependent_cents"], 8000000, "income per dependent"
        )

        refused = api.decide_aid_application(
            application["id"], f.aid_decision_payload(AID_DECISION_APPROVED), TOUR_ADMIN
        )
        validate_error(refused, ERR_INCOME_INELIGIBLE, 409)
        still_open = validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )
        assert still_open["status"] == AID_SUBMITTED

        denied = validate_success(
            api.decide_aid_application(
                application["id"], f.aid_decision_payload(AID_DECISION_DENIED),
                TOUR_ADMIN,
            ),
            200,
        )
        assert denied["status"] == AID_DENIED
        assert_two_decimals(denied["covered_pct"], 0.00, "covered_pct")
        assert_cents(denied["estimated_award_cents"], 0, "estimated award")

    def test_the_per_junior_cap_blocks_a_third_award_while_the_purse_is_full(self, api):
        """Two 30,000 awards exhaust the 60,000 personal cap, not the season purse.

        PRD: "If the clamped award is not strictly positive — because the
        application's `consumed_cents` has already reached or exceeded its
        `per_member_cap_cents` — the submission is refused with
        `ERR_AID_ALLOCATION_EXHAUSTED`."

        Design: Corner/validations/per_member_assistance_cap_blocks_the_third_award
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        application = fx.approved_aid_application(api, member_id, ctx["season_id"])
        assert application["status"] == AID_APPROVED
        assert_two_decimals(application["covered_pct"], 1.00, "covered_pct")
        assert_cents(
            application["per_member_cap_cents"], PER_MEMBER_CAP_CENTS, "per-member cap"
        )

        local = dict(
            tier=TIER_LOCAL,
            entry_fee_cents=30000,
            course_rating=70.0,
            slope_rating=120,
            field_size_limit=4,
        )
        first = fx.create_tournament(
            api, ctx["season_id"], name="Autumn Local A", **local
        )
        second = fx.create_tournament(
            api, ctx["season_id"], f.october_tournament_payload,
            name="Autumn Local B", **local
        )
        third = fx.create_tournament(
            api, ctx["season_id"], name="Autumn Local C",
            start_date="2026-11-12", end_date="2026-11-13",
            entry_close_at="2026-11-01T00:00:00Z",
            withdrawal_deadline_at="2026-11-08T00:00:00Z", **local
        )
        for tournament in (first, second, third):
            validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        for tournament in (first, second):
            funded = validate_success(
                api.submit_entry(
                    f.entry_payload(
                        member_id,
                        tournament["id"],
                        request_assistance=True,
                        aid_application_id=application["id"],
                    ),
                    member_headers(member_id),
                ),
                201,
            )
            assert_cents(funded["aid_award_cents"], 30000, "aid award")
            assert_fee_status(funded, FEE_AID_COVERED)

        exhausted = api.submit_entry(
            f.entry_payload(
                member_id,
                third["id"],
                request_assistance=True,
                aid_application_id=application["id"],
            ),
            member_headers(member_id),
        )
        validate_error(exhausted, ERR_AID_ALLOCATION_EXHAUSTED, 409)

        assert_slot_census(fx.read_tournament(api, third["id"]), entry_count=0)
        stored = validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )
        assert_cents(stored["consumed_cents"], PER_MEMBER_CAP_CENTS, "consumed")
        assert_ledger(
            fx.read_season(api, ctx["season_id"]),
            available=SEASON_ASSISTANCE_BUDGET_CENTS - 60000,
            committed=60000,
        )

    def test_an_award_the_purse_cannot_cover_whole_is_not_part_funded(self, api):
        """A 30,000 award against 20,000 available is refused outright.

        PRD: "If the clamped award exceeds the season's current
        `assistance_available_cents`, the submission is refused with
        `ERR_AID_BUDGET_EXHAUSTED`: the association never part-funds an entry,
        so an award that cannot be granted whole is not granted at all."

        Design: Corner/validations/season_budget_too_small_to_fund_the_award_whole
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api, assistance_budget_cents=20000)
        assert_ledger(season, available=20000, committed=0, disbursed=0)
        member = fx.register_member(api, season["id"])
        fx.verify_member(api, member["id"])
        application = fx.approved_aid_application(api, member["id"], season["id"])
        assert_two_decimals(application["covered_pct"], 1.00, "covered_pct")

        tournament = fx.create_tournament(
            api,
            season["id"],
            name="Autumn Local A",
            tier=TIER_LOCAL,
            entry_fee_cents=30000,
            course_rating=70.0,
            slope_rating=120,
            field_size_limit=4,
        )
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        refused = api.submit_entry(
            f.entry_payload(
                member["id"],
                tournament["id"],
                request_assistance=True,
                aid_application_id=application["id"],
            ),
            member_headers(member["id"]),
        )
        validate_error(refused, ERR_AID_BUDGET_EXHAUSTED, 409)

        assert_ledger(fx.read_season(api, season["id"]), available=20000, committed=0)
        stored = validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )
        assert_cents(stored["consumed_cents"], 0, "consumed")
        assert_slot_census(fx.read_tournament(api, tournament["id"]), entry_count=0)


class TestPaymentExactness:
    def test_a_part_payment_banks_nothing_and_the_exact_remainder_settles(self, api):
        """10,000 against a 25,000 remainder is refused; 25,000 pays the entry off.

        PRD: "A `Member` or a `TourAdmin` supplies an `amount_cents` that must
        be strictly positive and must equal exactly the entry's outstanding
        remainder, which is `net_fee_due_cents` less `amount_paid_cents`; any
        other figure, including a partial instalment or an overpayment, is
        refused with `ERR_PAYMENT_AMOUNT_INVALID`."

        Design: Corner/validations/partial_payment_is_refused_and_the_exact_remainder_settles
        """
        ctx = fx.field_set(api, member_count=1)
        member_id = ctx["member_ids"][0]
        entry = ctx["entries"][0]
        assert_cents(entry["net_fee_due_cents"], STANDARD_ENTRY_FEE_CENTS, "net due")
        assert_fee_status(entry, FEE_UNPAID)

        refused = api.pay_entry(
            entry["id"], f.payment_payload(10000), member_headers(member_id)
        )
        validate_error(refused, ERR_PAYMENT_AMOUNT_INVALID, 422)
        assert_cents(
            fx.read_entry(api, entry["id"])["amount_paid_cents"], 0, "amount paid"
        )

        settled = validate_success(
            api.pay_entry(
                entry["id"],
                f.payment_payload(STANDARD_ENTRY_FEE_CENTS),
                member_headers(member_id),
            ),
            200,
        )
        assert_fee_status(settled, FEE_PAID)
        assert_cents(
            settled["amount_paid_cents"], STANDARD_ENTRY_FEE_CENTS, "amount paid"
        )
        assert_cents(settled["refunded_cents"], 0, "refunded")


class TestStartAndConsentGates:
    def test_an_event_whose_selector_found_nobody_cannot_start(self, api):
        """FIELD_SET with accepted_count 0 is refused on the field, not the state.

        PRD: "The tournament's `accepted_count` must be at least 1 — a
        tournament whose selector produced an empty field cannot be started,
        and the attempt is refused with `ERR_EMPTY_FIELD`."

        Design: Corner/validations/start_with_an_empty_field_is_refused
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        selected = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        assert_tournament_status(selected, TOURNAMENT_FIELD_SET)
        assert_slot_census(selected, accepted_count=0)

        fx.set_clock(api, fx.CLOCK_ROUND_ONE)
        refused = api.start_tournament(tournament["id"], TOUR_ADMIN)
        validate_error(refused, ERR_EMPTY_FIELD, 409)
        assert_tournament_status(
            fx.read_tournament(api, tournament["id"]), TOURNAMENT_FIELD_SET
        )

    def test_recruiting_access_needs_the_junior_s_own_publication_consent(self, api):
        """Consent is read from the target junior: one refuses, the other admits.

        PRD: "A junior's results are visible to recruiters only while their
        `publication_opt_in` is true; a request to read a junior's published
        results, or a coach's request for access to them, for a junior whose
        flag is false is refused with `ERR_PUBLICATION_NOT_CONSENTED`."

        Design: Corner/validations/coach_access_request_without_publication_consent_is_refused
        """
        ctx = fx.verified_roster(api, member_count=2)
        consenting, withholding = ctx["member_ids"]
        assert ctx["members"][1]["publication_opt_in"] is False

        refused = api.request_coach_access(
            f.coach_access_payload(withholding, fx.member_version(api, withholding)),
            COACH,
        )
        validate_error(refused, ERR_PUBLICATION_NOT_CONSENTED, 409)
        _rows, meta = validate_paginated(
            api.list_coach_access_grants({"member_id": withholding}, TOUR_ADMIN)
        )
        assert meta["total_count"] == 0

        granted = validate_success(
            api.request_coach_access(
                f.coach_access_payload(consenting, fx.member_version(api, consenting)),
                COACH,
            ),
            201,
        )
        assert granted["status"] == COACH_GRANT_REQUESTED
        assert granted["member_id"] == consenting
        assert granted["coach_user_id"] == COACH_USER_ID
