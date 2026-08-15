"""Issue enforcement, strike standing bands, eviction cascade, cancellation
refunds, and waitlist promotion."""
from test_helpers import (
    CLOCK_JURY_REVIEW,
    STANDARD_SCORES,
    ApiErrorId,
    TEST_USERS,
    advance_phase,
    api_client,
    create_application,
    create_convention,
    create_freight_booking,
    create_load_slot,
    create_placement,
    create_staff_member,
    decide,
    find_dock_door,
    get_application,
    get_exhibitor,
    get_load_slot,
    get_space_unit,
    issue_badge,
    make_director_headers,
    make_exhibitor_headers,
    post_scores,
    record_guilty_issue,
    register_exhibitor,
    report_issue,
    resolve_issue,
    set_clock,
    setup_open_convention,
    setup_placed_application,
    setup_placed_for_a,
    setup_two_applications_decided,
    submit_and_verify_permit,
    submit_application,
    validate_error,
    validate_success,
)

ARTIST_TABLE_SPEC = {
    "space_code": "T-01",
    "block": "T",
    "unit_number": 1,
    "hall": "ARTIST_ALLEY_HALL",
    "kind": "ARTIST_TABLE",
    "base_price_cents": 30000,
}


def _setup_eviction_ready():
    """A (DEALER) PLACED with one ISSUED badge and a CONFIRMED 3-pallet freight
    booking; B (DEALER) JURIED_WAITLISTED; convention in LOGISTICS; A already
    SUSPENDED on 6 strike points from two CRITICAL guilty findings, with a
    third MAJOR issue ESCALATED and ready to resolve."""
    bundle = setup_two_applications_decided()  # A ACCEPTED, B WAITLISTED
    bundle = setup_placed_for_a(bundle)  # A CONTRACTED -> placement confirmed
    bundle["convention"] = advance_phase(bundle["convention"]["id"])  # LOGISTICS

    conv_id = bundle["convention"]["id"]
    ex_a = bundle["exhibitor_a"]["id"]
    staff = create_staff_member(conv_id, ex_a, "Alice Aisle")
    bundle["staff"] = issue_badge(staff["id"], ex_a)

    slot = create_load_slot(conv_id, pallet_capacity=10)
    door = find_dock_door(conv_id, "D1")
    booking = create_freight_booking(
        bundle["application_a"]["id"],
        ex_a,
        slot["id"],
        door["id"],
        door_starts_at="2026-10-14T08:00:00Z",
        door_ends_at="2026-10-14T09:00:00Z",
        pallet_count=3,
    )
    bundle["load_slot"] = slot
    bundle["booking"] = validate_success(
        api_client.confirm_freight_booking(booking["id"], TEST_USERS["ops_headers"])
    )

    # Two CRITICAL guilty resolutions: 3 + 3 = 6 points -> SUSPENDED.
    record_guilty_issue(conv_id, ex_a, "CRITICAL", "Harassment report at booth")
    record_guilty_issue(conv_id, ex_a, "CRITICAL", "Prohibited replica weapons sold")
    # Third issue (MAJOR, 2 points) escalated and awaiting resolution.
    third = report_issue(
        conv_id, ex_a, severity="MAJOR", category="ENCROACHMENT",
        description="Encroaches 2 feet into aisle",
    )
    validate_success(
        api_client.escalate_issue(third["id"], TEST_USERS["director_headers"])
    )
    bundle["third_issue"] = third
    return bundle


class TestDutySegregation:
    def test_duty_segregation_reporter_cannot_resolve(self, api):
        """PRD §3.9: "Segregation of duties is enforced at this step: the
        resolving director's `X-User-ID` must differ from the ticket's
        `reporter_user_id` (`ERR_DUTY_SEGREGATION`), so no one adjudicates
        their own complaint."

        Design: Corner/validations/duty_segregation_reporter_cannot_resolve
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        exhibitor = register_exhibitor(
            legal_name="Dealer One LLC", category="DEALER"
        )
        issue = report_issue(
            conv["id"],
            exhibitor["id"],
            reporter="dir-1",  # the ShowDirector may also report
            severity="MINOR",
            category="CONDUCT",
            description="Reported by director",
        )
        resp = api.resolve_issue(
            issue["id"], {"outcome": "GUILTY"}, make_director_headers("dir-1")
        )
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION)
        current = validate_success(
            api.get_issue_ticket(issue["id"], TEST_USERS["director_headers"])
        )
        assert current["status"] == "OPEN"


class TestIssueOutcomes:
    def test_escalated_issue_resolvable_unfounded_no_strikes(self, api, director_headers):
        """PRD §3.9: "Resolution records an `outcome` of `GUILTY` or `UNFOUNDED`
        and moves the ticket to the terminal `RESOLVED`."
        PRD §3.9: "An `UNFOUNDED` resolution applies nothing. A `GUILTY` one
        sets the ticket's `strike_points_applied` to the severity's point value
        — one for `MINOR`, two for `MAJOR`, three for `CRITICAL` — and adds
        those points to the exhibitor's `strike_points`."

        Design: Corner/state_machines/escalated_issue_resolvable_unfounded_no_strikes
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        exhibitor = register_exhibitor(
            legal_name="Dealer One LLC", category="DEALER"
        )
        issue = report_issue(
            conv["id"],
            exhibitor["id"],
            severity="MAJOR",
            category="NOISE",
            description="Loud PA at booth",
        )
        validate_success(api.escalate_issue(issue["id"], director_headers))
        resolved = validate_success(
            api.resolve_issue(
                issue["id"], {"outcome": "UNFOUNDED"}, make_director_headers("dir-1")
            )
        )
        assert resolved["status"] == "RESOLVED"  # via the ESCALATED branch
        assert resolved["strike_points_applied"] == 0
        assert get_exhibitor(exhibitor["id"])["strike_points"] == 0


class TestStandingBands:
    def test_strike_threshold_probation_boundary(self, api, director_headers):
        """PRD §3.2: "Standing derives from strike points in bands that are
        inclusive at their lower edge: fewer than three points is `GOOD`; at
        least three but fewer than five is `PROBATION`; at least five but fewer
        than seven is `SUSPENDED`; seven or more is `EVICTED`."

        Design: Corner/calculations/strike_threshold_probation_boundary
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        exhibitor = register_exhibitor(
            legal_name="Dealer One LLC", category="DEALER"
        )
        record_guilty_issue(conv["id"], exhibitor["id"], "MINOR", "n1")
        record_guilty_issue(conv["id"], exhibitor["id"], "MINOR", "n2")
        assert get_exhibitor(exhibitor["id"])["standing"] == "GOOD"  # 2 points

        third = record_guilty_issue(conv["id"], exhibitor["id"], "MINOR", "n3")
        assert third["strike_points_applied"] == 1
        after = get_exhibitor(exhibitor["id"])
        assert after["strike_points"] == 3
        assert after["standing"] == "PROBATION"  # inclusive lower edge

    def test_standing_suspension_threshold_at_five(self, api, director_headers):
        """PRD §3.2: "Standing derives from strike points in bands that are
        inclusive at their lower edge: fewer than three points is `GOOD`; at
        least three but fewer than five is `PROBATION`; at least five but fewer
        than seven is `SUSPENDED`; seven or more is `EVICTED`."

        Design: Corner/cross_cutting_layers/standing_suspension_threshold_at_five
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        exhibitor = register_exhibitor(
            legal_name="Dealer One LLC", category="DEALER"
        )
        record_guilty_issue(conv["id"], exhibitor["id"], "MAJOR", "m1")
        record_guilty_issue(conv["id"], exhibitor["id"], "MAJOR", "m2")
        assert get_exhibitor(exhibitor["id"])["standing"] == "PROBATION"  # 4 pts

        record_guilty_issue(conv["id"], exhibitor["id"], "MINOR", "m3")
        after = get_exhibitor(exhibitor["id"])
        assert after["strike_points"] == 5
        assert after["standing"] == "SUSPENDED"  # inclusive threshold


class TestEvictionCascade:
    def test_eviction_cancels_application_without_refund(self, api):
        """PRD §3.9: "When an exhibitor's `standing` becomes `EVICTED`, every
        application of that exhibitor in `JURIED_ACCEPTED`, `CONTRACTED`, or
        `PLACED` is cancelled with `cancellation_reason` `EVICTION` and a
        `refund_cents` of zero."
        PRD §3.9: "The `refund_cents` is the `amount_paid_cents` multiplied by
        the applicable fraction, rounded half-up to the nearest cent, and
        eviction-driven cancellations bypass this rule entirely with a refund
        of zero."

        Design: Difficulty/transitive_cascade/eviction_cascade_depth_four
        """
        bundle = _setup_eviction_ready()
        ex_a = bundle["exhibitor_a"]["id"]
        resolved = resolve_issue(bundle["third_issue"]["id"], "GUILTY")
        assert resolved["strike_points_applied"] == 2  # MAJOR

        exhibitor = get_exhibitor(ex_a)
        assert exhibitor["strike_points"] == 8  # 6 -> 8
        assert exhibitor["standing"] == "EVICTED"

        app = get_application(bundle["application_a"]["id"])
        assert app["status"] == "CANCELLED"
        assert app["cancellation_reason"] == "EVICTION"
        assert app["refund_cents"] == 0

    def test_eviction_cascade_releases_space_badge_freight_and_promotes(self, api):
        """PRD §3.9: "Each cancelled application then unwinds in full: its
        `TENTATIVE` and `CONFIRMED` placements are released and their spaces
        return to `AVAILABLE` with `current_application_id` cleared; its
        `ISSUED` staff badges are revoked; its `REQUESTED` and `CONFIRMED`
        freight bookings are cancelled, releasing their pallets from the load
        slots and returning any `FULL` slot to `OPEN` when the count drops
        below capacity; the category quota's `accepted_count` is decremented;
        and the promotion sweep runs for each affected category."

        Design: Difficulty/transitive_cascade/eviction_cascade_depth_four
        """
        bundle = _setup_eviction_ready()
        resolve_issue(bundle["third_issue"]["id"], "GUILTY")

        space = get_space_unit(bundle["spaces"]["A-101"]["id"])
        assert space["status"] == "AVAILABLE"
        assert space["current_application_id"] is None

        staff = validate_success(
            api_client.get_staff_member(
                bundle["staff"]["id"], TEST_USERS["director_headers"]
            )
        )
        assert staff["badge_status"] == "REVOKED"

        booking = validate_success(
            api_client.get_freight_booking(
                bundle["booking"]["id"], TEST_USERS["director_headers"]
            )
        )
        assert booking["status"] == "CANCELLED"
        assert get_load_slot(bundle["load_slot"]["id"])["reserved_pallets"] == 0

        # The accepted_count decrease promoted the waitlisted application.
        promoted = get_application(bundle["application_b"]["id"])
        assert promoted["status"] == "JURIED_ACCEPTED"


class TestExhibitorCancellation:
    def test_exhibitor_cancel_in_half_band_refunds_half(self, api):
        """PRD §3.9: "The refund follows the calendar: cancelling on or before
        the instant exactly sixty days before the show's `starts_at` refunds
        the full `amount_paid_cents`; after that instant but on or before the
        instant exactly thirty days before `starts_at`, half; later than that,
        nothing."
        PRD §3.9: "An exhibitor — or the director acting on the convention's
        behalf — may cancel a `CONTRACTED` or `PLACED` application; the
        `cancellation_reason` records `EXHIBITOR` or `DIRECTOR` according to
        the actor."

        Design: Difficulty/transitive_cascade/exhibitor_cancel_promotion_cascade
        """
        bundle = setup_placed_for_a(setup_two_applications_decided())
        # 2026-09-01 is inside the (60d, 30d] band for starts 2026-10-15.
        set_clock("2026-09-01T00:00:00Z")
        cancelled = validate_success(
            api.cancel_application(
                bundle["application_a"]["id"],
                make_exhibitor_headers(bundle["exhibitor_a"]["id"]),
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "EXHIBITOR"
        assert cancelled["refund_cents"] == 11250  # 50% of deposit 22500

    def test_cancel_releases_space_and_promotes_waitlisted(self, api):
        """PRD §3.9: "Alongside the refund, the full release cascade runs
        exactly as in eviction — placements released, spaces freed, badges
        revoked, freight cancelled with pallet release, `accepted_count`
        decremented, the promotion sweep fired, neighbor requests mooted — and
        `CANCELLED` is terminal."

        Design: Difficulty/transitive_cascade/exhibitor_cancel_promotion_cascade
        """
        bundle = setup_placed_for_a(setup_two_applications_decided())
        set_clock("2026-09-01T00:00:00Z")
        validate_success(
            api.cancel_application(
                bundle["application_a"]["id"],
                make_exhibitor_headers(bundle["exhibitor_a"]["id"]),
            )
        )
        space = get_space_unit(bundle["spaces"]["A-101"]["id"])
        assert space["status"] == "AVAILABLE"
        promoted = get_application(bundle["application_b"]["id"])
        assert promoted["status"] == "JURIED_ACCEPTED"


class TestWaitlistPromotionOrder:
    def test_waitlist_promotion_tiebreak_renewal_then_created(self, api):
        """PRD §3.4: "The sweep considers the category's `JURIED_WAITLISTED`
        applications, ordered by `jury_composite_score` descending, then by the
        exhibitor's `renewal_priority_score` descending, then by the
        application's `created_at` ascending, and promotes exactly one to
        `JURIED_ACCEPTED`, restamping its `decided_at` and shifting the
        counters: `waitlisted_count` down by one, `accepted_count` up by one."
        PRD §3.5: "An exhibitor may instead decline the offer: `JURIED_ACCEPTED`
        → `DECLINED`, terminal. Declining decrements the quota's
        `accepted_count` and then fires the promotion sweep for the category"

        Design: Corner/calculations/waitlist_promotion_tiebreak_renewal_then_created
        """
        bundle = setup_open_convention(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 2}
            ],
            dock_doors=[{"door_code": "D1"}],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Dealer A LLC", category="DEALER")
        # B: renewal_priority_score = 10*2 + 3*3 - 8*0 = 29; C: 0.
        ex_b = register_exhibitor(
            legal_name="Dealer B LLC",
            category="DEALER",
            prior_years_completed=2,
            prior_on_time_payments=3,
        )
        ex_c = register_exhibitor(legal_name="Dealer C LLC", category="DEALER")
        app_a = create_application(conv_id, ex_a["id"], category="DEALER")
        app_b = create_application(conv_id, ex_b["id"], category="DEALER")
        app_c = create_application(conv_id, ex_c["id"], category="DEALER")
        submit_application(app_a["id"], ex_a["id"])
        submit_application(app_b["id"], ex_b["id"])
        submit_application(app_c["id"], ex_c["id"])
        set_clock(CLOCK_JURY_REVIEW)
        advance_phase(conv_id)
        # All three composite at 77.67 — an exact jury-score tie for B and C.
        post_scores(app_a["id"], STANDARD_SCORES)
        post_scores(app_b["id"], STANDARD_SCORES)
        post_scores(app_c["id"], STANDARD_SCORES)
        decide(app_a["id"], "ACCEPTED")
        decide(app_b["id"], "WAITLISTED")
        decide(app_c["id"], "WAITLISTED")
        advance_phase(conv_id)  # -> PLACEMENT
        create_placement(app_a["id"], bundle["spaces"]["A-101"]["id"])
        submit_and_verify_permit(app_a["id"], ex_a["id"])

        # A declines: accepted_count 1 -> 0 fires the sweep for DEALER.
        validate_success(
            api.decline_offer(app_a["id"], make_exhibitor_headers(ex_a["id"]))
        )
        # The composite tie (77.67) is broken by renewal_priority_score 29 > 0.
        assert get_application(app_b["id"])["status"] == "JURIED_ACCEPTED"
        assert get_application(app_c["id"])["status"] == "JURIED_WAITLISTED"


class TestRefundBoundary:
    def test_cancel_exactly_sixty_days_before_full_refund(self, api):
        """PRD §3.9: "The refund follows the calendar: cancelling on or before
        the instant exactly sixty days before the show's `starts_at` refunds
        the full `amount_paid_cents`; after that instant but on or before the
        instant exactly thirty days before `starts_at`, half; later than that,
        nothing."

        Design: Difficulty/boundary_precision_check/refund_boundary_exactly_sixty_days
        """
        bundle = setup_placed_application()
        # starts_at 2026-10-15T09:00:00Z minus exactly 60 days.
        set_clock("2026-08-16T09:00:00Z")
        cancelled = validate_success(
            api.cancel_application(
                bundle["application"]["id"],
                make_exhibitor_headers(bundle["exhibitor"]["id"]),
            )
        )
        assert cancelled["refund_cents"] == 22500  # 100%, inclusive boundary
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_one_day_inside_sixty_day_boundary_half_refund(self, api):
        """PRD §3.9: "The refund follows the calendar: cancelling on or before
        the instant exactly sixty days before the show's `starts_at` refunds
        the full `amount_paid_cents`; after that instant but on or before the
        instant exactly thirty days before `starts_at`, half; later than that,
        nothing."
        PRD §3.9: "The `refund_cents` is the `amount_paid_cents` multiplied by
        the applicable fraction, rounded half-up to the nearest cent, and
        eviction-driven cancellations bypass this rule entirely with a refund
        of zero."

        Design: Difficulty/boundary_precision_check/refund_boundary_exactly_sixty_days
        """
        bundle = setup_placed_application(
            category="ARTIST_ALLEY",
            kinds=("ARTIST_TABLE",),
            estimated_daily_sales_cents=10000,
            space_specs=[ARTIST_TABLE_SPEC],
            deposit_cents=6750,  # invoice 27000 after early-bird 10%
        )
        # 2026-08-17 is one day past the sixty-day boundary (2026-08-16T09:00).
        set_clock("2026-08-17T00:00:00Z")
        cancelled = validate_success(
            api.cancel_application(
                bundle["application"]["id"],
                make_exhibitor_headers(bundle["exhibitor"]["id"]),
            )
        )
        assert cancelled["refund_cents"] == 3375  # 50% of deposit 6750
