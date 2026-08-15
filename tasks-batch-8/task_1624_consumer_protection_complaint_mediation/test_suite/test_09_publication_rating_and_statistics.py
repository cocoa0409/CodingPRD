"""Publication axis, public rating variants and bands, statistics, and redaction."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_unresolved,
    complete_session,
    drive_to_executed_settlement,
    dual_confirm_session,
    file_complaint,
    get_business,
    get_complaint,
    make_consumer_headers,
    mark_received,
    notify_business,
    offer_mediation,
    pledge_payment,
    propose_session,
    refer_complaint,
    register_business,
    register_consumer,
    register_mediation_room,
    register_mediator,
    screen_accept,
    set_clock,
    setup_settled_case,
    validate_success,
)

ANON = TEST_USERS["anonymous_headers"]
OFFICER_1 = TEST_USERS["intake_officer_headers"]
OFFICER_2 = TEST_USERS["intake_officer_2_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]


def _setup_rating_history(api):
    """Business (SMALL, LIFETIME) with K1 CLOSED_UNRESOLVED published 2025-07-21
    (14 months before the observation date) and K2 SETTLED published 2026-07-19.
    Clock rests at 2026-08-01."""
    consumer = register_consumer(full_name="C One", email="c1@x.com", state_code="OR")
    business = register_business(legal_name="RateCo", home_state="OR", operates_in_states=["OR"])
    mediator = register_mediator(full_name="Med One", employee_ref="EMP-1")
    room = register_mediation_room(room_name="Room A", capacity=8, location="Salem")

    set_clock("2025-06-01T00:00:00Z")
    k1 = file_complaint(
        consumer, business, incident_date="2025-05-20",
        category="REFUND_REFUSAL", description="k1", amount_in_dispute_cents=2000,
    )
    screen_accept(k1["id"], OFFICER_1)
    notify_business(k1["id"], OFFICER_1)  # in-state deadline 2025-07-01
    set_clock("2025-07-02T00:00:00Z")    # strictly past: RESPONSE_OVERDUE
    offer_mediation(k1["id"], OFFICER_1)
    s1 = propose_session(k1["id"], mediator, room,
                         starts_at="2025-07-10T10:00:00Z", ends_at="2025-07-10T11:00:00Z")
    dual_confirm_session(s1["id"], consumer, business)
    complete_session(s1["id"], mediator, {"outcome": "IMPASSE"}, at_clock="2025-07-10T10:30:00Z")
    close_unresolved(k1["id"], OFFICER_2, closure_summary="no agreement reached")
    set_clock("2025-07-21T00:00:00Z")    # embargo (closed 07-10T10:30 + 10d) matured: PUBLISHED

    set_clock("2026-07-01T00:00:00Z")
    ctx2 = drive_to_executed_settlement(
        consumer, business, mediator, room,
        incident_date="2026-06-01", category="BILLING_DISPUTE", description="k2",
        restitution_cents=5000,
        session_starts_at="2026-07-05T10:00:00Z", session_ends_at="2026-07-05T11:00:00Z",
    )
    payment = pledge_payment(business, ctx2["settlement"]["outstanding_cents"])
    mark_received(payment["id"])         # K2 SETTLED, EMBARGOED
    set_clock("2026-07-19T00:00:00Z")    # K2 embargo matured: PUBLISHED
    set_clock("2026-08-01T00:00:00Z")
    return consumer, business, k1, ctx2["complaint"]


class TestRatingMethodVariants:
    def test_rating_method_switch_recomputes_score_and_tier(self, api):
        """PRD §3.9: "The default `LIFETIME` sums demerits over every published complaint regardless of age."
        PRD §3.9: "`ROLLING_12M` weights each published complaint's demerit in full when its publication date falls within the trailing 365 days, and at one quarter otherwise; the weighted demerit sum is rounded half-up to a whole number first, and only then subtracted from 100 — so a single 15-demerit complaint published fourteen months ago contributes 3.75 into that rounding step."
        PRD §3.1: "the switch recomputes `rating_score` and `rating_tier` under the new variant within the same request, so the response already reflects the new method"

        Design: Difficulty/dual_variant_calc/d_rating_lifetime_vs_rolling12m
        """
        _, business, k1, k2 = _setup_rating_history(api)
        before = get_business(business["id"])
        # LIFETIME: demerits 15 (unresolved) + 5 (settled) = 20 -> 100 - 20 = 80, tier B.
        assert before["rating_score"] == 80
        assert before["rating_tier"] == "B"
        assert before["published_complaint_count"] == 2

        switched = validate_success(
            api.set_rating_method(business["id"], {"rating_method": "ROLLING_12M"}, DIRECTOR_1)
        )
        # ROLLING_12M: K1 (published 2025-07-21, outside the trailing 365 days) counts
        # 15 * 0.25; K2 counts 5. round_half_up(3.75 + 5) = 9 -> 100 - 9 = 91, tier A.
        assert switched["rating_method"] == "ROLLING_12M"
        assert switched["rating_score"] == 91
        assert switched["rating_tier"] == "A"

    def test_variant_switch_changes_scoring_not_the_published_set(self, api):
        """PRD §3.9: "The rating is recomputed whenever a complaint is published or retracted, and whenever the `UnitDirector` switches the business's rating method as described in §3.1."
        PRD §3.9: "Only complaints currently `PUBLISHED` count — `EMBARGOED`, `SUPPRESSED`, `REDACTED`, and `UNPUBLISHED` complaints are all invisible to the rating."

        Design: Difficulty/dual_variant_calc/d_rating_lifetime_vs_rolling12m
        """
        _, business, k1, k2 = _setup_rating_history(api)
        switched = validate_success(
            api.set_rating_method(business["id"], {"rating_method": "ROLLING_12M"}, DIRECTOR_1)
        )
        assert switched["published_complaint_count"] == 2, "variant switch is scoring-only"
        assert get_complaint(k1["id"])["publication_status"] == "PUBLISHED"
        assert get_complaint(k2["id"])["publication_status"] == "PUBLISHED"


class TestDualAxisComplaint:
    def test_publication_axis_advances_while_case_axis_stays_settled(self, api):
        """PRD §2.10: "A complaint lives on two independent state axes."
        PRD §3.9: "A case that closes with consumer consent sits `EMBARGOED` for ten days measured from `closed_at`; the clock sweep publishes it — moving it to `PUBLISHED` — once the current time reaches or passes that ten-day mark, the boundary day itself included."
        PRD §2.10: "Once published, a complaint can still leave the record: the consumer may retract it, moving it to `REDACTED`."

        Design: Difficulty/non_linear_state_machine/d_complaint_dual_axis_publication
        """
        ctx = setup_settled_case(restitution_cents=5000)
        complaint = ctx["complaint"]
        assert complaint["case_status"] == "SETTLED"
        assert complaint["publication_status"] == "EMBARGOED"

        set_clock("2026-08-14T00:00:00Z")  # closed 2026-08-04 + 10 days, boundary included
        mid = get_complaint(complaint["id"])
        assert mid["publication_status"] == "PUBLISHED"
        assert mid["case_status"] == "SETTLED", "case axis untouched by publication"

        retracted = validate_success(
            api.retract_publication(complaint["id"], make_consumer_headers(ctx["consumer"]["id"]))
        )
        assert retracted["publication_status"] == "REDACTED"
        assert retracted["case_status"] == "SETTLED", "publication axis moves; case axis never reopens"

    def test_publication_and_retraction_reconcile_business_rating(self, api):
        """PRD §3.9: "Publication increments the business's `published_complaint_count`, recomputes its rating, and writes a `PUBLISHED` event."
        PRD §3.9: "A business's public rating begins at 100 and loses demerits for each published complaint by outcome: 5 for `SETTLED`, 15 for `CLOSED_UNRESOLVED`, 25 for `REFERRED_ENFORCEMENT`."
        PRD §3.9: "retraction moves a `PUBLISHED` complaint to `REDACTED`, decrements `published_complaint_count`, removes the complaint's demerit, and recomputes the rating again"

        Design: Difficulty/non_linear_state_machine/d_complaint_dual_axis_publication
        """
        ctx = setup_settled_case(restitution_cents=5000)
        set_clock("2026-08-14T00:00:00Z")
        published_business = get_business(ctx["business"]["id"])
        assert published_business["published_complaint_count"] == 1
        assert published_business["rating_score"] == 95, "100 - 5 SETTLED demerit"

        validate_success(
            api.retract_publication(ctx["complaint"]["id"],
                                    make_consumer_headers(ctx["consumer"]["id"]))
        )
        after = get_business(ctx["business"]["id"])
        assert after["published_complaint_count"] == 0
        assert after["rating_score"] == 100, "derived fields reconcile on redaction"


def _setup_tier_flip_case(api):
    """Business with K1 PUBLISHED as REFERRED_ENFORCEMENT (25 demerits) and K2
    CLOSED_UNRESOLVED (15 demerits) still EMBARGOED until 2026-09-25T10:30."""
    consumer = register_consumer(full_name="C C", email="cc@x.com", state_code="OR")
    business = register_business(legal_name="CascCo", home_state="OR", operates_in_states=["OR"])
    mediator = register_mediator(full_name="Med C", employee_ref="EMP-8")
    room = register_mediation_room(room_name="Room C", capacity=6, location="Salem")
    set_clock("2026-08-01T00:00:00Z")
    k1 = file_complaint(consumer, business, incident_date="2026-07-01",
                        category="DECEPTIVE_PRACTICE", description="k1", amount_in_dispute_cents=1000)
    screen_accept(k1["id"], OFFICER_1)
    refer_complaint(k1["id"], "pattern under review", OFFICER_1)  # closed 08-01, EMBARGOED
    set_clock("2026-08-11T00:00:00Z")  # boundary day included: K1 PUBLISHED (rating 75, tier B)

    k2 = file_complaint(consumer, business, incident_date="2026-07-20",
                        category="BILLING_DISPUTE", description="k2", amount_in_dispute_cents=800)
    screen_accept(k2["id"], OFFICER_1)
    notify_business(k2["id"], OFFICER_1)  # deadline 2026-09-10
    set_clock("2026-09-11T00:00:00Z")   # strictly past: RESPONSE_OVERDUE
    offer_mediation(k2["id"], OFFICER_1)
    s2 = propose_session(k2["id"], mediator, room,
                         starts_at="2026-09-15T10:00:00Z", ends_at="2026-09-15T11:00:00Z")
    dual_confirm_session(s2["id"], consumer, business)
    complete_session(s2["id"], mediator, {"outcome": "IMPASSE"}, at_clock="2026-09-15T10:30:00Z")
    close_unresolved(k2["id"], OFFICER_2, closure_summary="impasse")  # EMBARGOED until 09-25T10:30
    return consumer, business, k1, k2


class TestPublicationCascadeTierFlip:
    def test_publication_sweep_cascades_count_and_rating(self, api):
        """PRD §2.6: "Third, complaints sitting in `EMBARGOED` whose embargo has matured — current time at or after `closed_at` plus ten days — become `PUBLISHED`, with the business's published count and rating recomputed as described in §3.9."
        PRD §3.9: "Publication increments the business's `published_complaint_count`, recomputes its rating, and writes a `PUBLISHED` event."

        Design: Difficulty/transitive_cascade/d_cascade_publication_tier_flip
        """
        _, business, _, k2 = _setup_tier_flip_case(api)
        pre = get_business(business["id"])
        assert pre["published_complaint_count"] == 1, "EMBARGOED K2 invisible"
        assert pre["rating_score"] == 75, "100 - 25 referred demerit"

        set_clock("2026-09-26T00:00:00Z")  # K2 embargo matured 2026-09-25T10:30
        assert get_complaint(k2["id"])["publication_status"] == "PUBLISHED"
        post = get_business(business["id"])
        assert post["published_complaint_count"] == 2
        assert post["rating_score"] == 60, "demerits 25 + 15 = 40 -> 100 - 40"

    def test_tier_flips_when_recomputed_score_crosses_band(self, api):
        """PRD §3.9: "The `rating_tier` bands on inclusive lower bounds: `A` at 90 or above, `B` at 70 or above, `C` at 40 or above, and `D` below 40."

        Design: Difficulty/transitive_cascade/d_cascade_publication_tier_flip
        """
        _, business, _, _ = _setup_tier_flip_case(api)
        assert get_business(business["id"])["rating_tier"] == "B", "75 >= 70"
        set_clock("2026-09-26T00:00:00Z")
        post = get_business(business["id"])
        assert post["rating_tier"] == "C", "60 < 70 crosses the B/C band"
        assert post["rating_score"] == 60


class TestStatisticsAndComputedReads:
    def _setup_stats_case(self, api):
        """K1 SETTLED 2026-08-04 and PUBLISHED 2026-08-14; K2 CLOSED_UNRESOLVED
        2026-09-16T10:30 and still EMBARGOED."""
        consumer = register_consumer(full_name="ST", email="st@x.com", state_code="OR")
        business = register_business(legal_name="StatCo", home_state="OR", operates_in_states=["OR"])
        mediator = register_mediator(full_name="Med ST", employee_ref="EMP-24")
        room = register_mediation_room(room_name="Room ST", capacity=4, location="Salem")
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = drive_to_executed_settlement(
            consumer, business, mediator, room,
            incident_date="2026-07-01", description="s1", restitution_cents=5000,
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        payment = pledge_payment(business, ctx1["settlement"]["outstanding_cents"])
        mark_received(payment["id"])  # K1 SETTLED at 2026-08-04 (filed 2026-08-01)
        set_clock("2026-08-14T00:00:00Z")  # K1 PUBLISHED (embargo boundary day)

        k2 = file_complaint(consumer, business, incident_date="2026-07-15",
                            category="BILLING_DISPUTE", description="s2", amount_in_dispute_cents=900)
        screen_accept(k2["id"], OFFICER_1)
        notify_business(k2["id"], OFFICER_1)  # deadline 2026-09-13
        set_clock("2026-09-14T00:00:00Z")   # RESPONSE_OVERDUE
        offer_mediation(k2["id"], OFFICER_1)
        s2 = propose_session(k2["id"], mediator, room,
                             starts_at="2026-09-16T10:00:00Z", ends_at="2026-09-16T11:00:00Z")
        dual_confirm_session(s2["id"], consumer, business)
        complete_session(s2["id"], mediator, {"outcome": "IMPASSE"}, at_clock="2026-09-16T10:30:00Z")
        close_unresolved(k2["id"], OFFICER_2, closure_summary="impasse")  # EMBARGOED to 09-26T10:30
        return business, k2

    def test_statistics_count_published_complaints_only(self, api):
        """PRD §3.9: "The public statistics view counts only `PUBLISHED` complaints: `published_total` overall, then `settled_count`, `unresolved_count`, and `referred_count` by outcome, plus `average_days_to_close` — the mean of the whole-day spans between `filed_at` and `closed_at` across the published complaints, rounded half-up to whole days, and zero when nothing has been published."
        PRD §3.9: "Embargoed complaints remain invisible to statistics until the sweep publishes them."

        Design: Corner/calculations/c_calc_stats_published_filter
        """
        business, k2 = self._setup_stats_case(api)
        stats = validate_success(api.get_business_complaint_statistics(business["id"], ANON))
        assert stats["published_total"] == 1
        assert stats["settled_count"] == 1
        assert stats["unresolved_count"] == 0
        assert stats["referred_count"] == 0
        assert stats["average_days_to_close"] == 3, "filed 2026-08-01, closed 2026-08-04"
        assert get_complaint(k2["id"])["publication_status"] == "EMBARGOED"

    def _setup_published_referred(self, api, legal_name):
        """One complaint REFERRED_ENFORCEMENT at 2026-08-01, PUBLISHED by the sweep
        at 2026-08-11 (the embargo boundary day)."""
        consumer = register_consumer(full_name="RR", email=f"{legal_name.lower()}@x.com", state_code="OR")
        business = register_business(legal_name=legal_name, home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, category="DECEPTIVE_PRACTICE", description="rr")
        screen_accept(complaint["id"], OFFICER_1)
        refer_complaint(complaint["id"], "pattern", OFFICER_1)
        set_clock("2026-08-11T00:00:00Z")
        return consumer, business, complaint

    def test_rating_view_reports_computed_signals(self, api):
        """PRD §3.9: "The rating view reports `rating_score`, `rating_tier`, `rating_method`, `published_complaint_count`, `pattern_score`, and `watch_status` together."
        PRD §3.9: "A business's public rating begins at 100 and loses demerits for each published complaint by outcome: 5 for `SETTLED`, 15 for `CLOSED_UNRESOLVED`, 25 for `REFERRED_ENFORCEMENT`."
        PRD §2.11: "A business scoring below 60 sits `CLEAR`."

        Design: Corner/endpoints/c_ep_rating_computed_read
        """
        _, business, complaint = self._setup_published_referred(api, "RateReadCo")
        assert get_complaint(complaint["id"])["publication_status"] == "PUBLISHED"

        view = validate_success(api.get_business_rating(business["id"], ANON))
        assert view["rating_score"] == 75, "100 - 25 referred demerit"
        assert view["rating_tier"] == "B"
        assert view["rating_method"] == "LIFETIME"
        assert view["published_complaint_count"] == 1
        assert view["pattern_score"] == 25
        assert view["watch_status"] == "CLEAR", "25 < 60"

    def test_redaction_removes_complaint_from_derived_fields(self, api):
        """PRD §3.9: "retraction moves a `PUBLISHED` complaint to `REDACTED`, decrements `published_complaint_count`, removes the complaint's demerit, and recomputes the rating again"
        PRD §2.10: "Once published, a complaint can still leave the record: the consumer may retract it, moving it to `REDACTED`."

        Design: Corner/complexity_layers/c_layer_redaction_reconcile
        """
        consumer, business, complaint = self._setup_published_referred(api, "RcCo")
        before = get_business(business["id"])
        assert before["published_complaint_count"] == 1
        assert before["rating_score"] == 75

        retracted = validate_success(
            api.retract_publication(complaint["id"], make_consumer_headers(consumer["id"]))
        )
        assert retracted["publication_status"] == "REDACTED"

        after = get_business(business["id"])
        assert after["published_complaint_count"] == 0
        assert after["rating_score"] == 100
        assert after["rating_tier"] == "A", "derived fields reconcile immediately"
