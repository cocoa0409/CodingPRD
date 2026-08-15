"""Site plan documents and first-responder walkthroughs: coverage validation,
whole-day drill conflict, currency windows, and clock-sweep expiries."""
from test_helpers import (
    ApiErrorId,
    complete_walkthrough,
    create_eop,
    create_site,
    create_site_plan_payload,
    create_walkthrough_payload,
    get_site_plan_document,
    get_walkthrough,
    publish_site_plan,
    schedule_drill,
    schedule_walkthrough,
    set_clock,
    setup_site_with_requirement,
    validate_error,
    validate_success,
)


class TestSitePlanCoverage:
    def test_incomplete_coverage_rejected(self, api, officer_headers):
        """PRD: "`coverage_tags` — a subset of `FLOOR_PLANS`, `ACCESS_POINTS`, `UTILITY_SHUTOFFS`, and `ASSEMBLY_AREAS` that must include both `FLOOR_PLANS` and `ACCESS_POINTS` (omission of either is rejected with `ERR_INCOMPLETE_COVERAGE`, HTTP 400)."

        Design: Corner/errors/incomplete_coverage_rejected
        """
        site = create_site(name="Cedar Grove High", enrollment_count=1200)
        resp = api.create_site_plan_document(
            create_site_plan_payload(site_id=site["id"],
                                     document_title="Partial plan",
                                     coverage_tags=["FLOOR_PLANS"]),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_COVERAGE)


class TestClockSweepExpiries:
    def test_walkthrough_missed_by_clock_sweep(self, api):
        """PRD: "When the system clock sweep fires and logical today passes a `SCHEDULED` walkthrough's `scheduled_date`, the walkthrough transitions to `MISSED` — a terminal state."

        Design: Corner/state_machines/walkthrough_missed_by_clock_sweep
        """
        site = create_site(name="Harborview Middle", enrollment_count=700)
        walkthrough = schedule_walkthrough(site["id"], agency="POLICE",
                                           scheduled_date="2026-09-10")
        assert walkthrough["status"] == "SCHEDULED"

        set_clock("2026-09-11T00:00:00Z")

        current = get_walkthrough(site["id"], walkthrough["id"])
        assert current["status"] == "MISSED", (
            f"Walkthrough past its scheduled_date must be MISSED, "
            f"got {current['status']}")

    def test_site_plan_expiry_by_clock_sweep(self, api, officer_headers):
        """PRD: "Similarly, when logical today passes a `CURRENT` SitePlanDocument's `review_by_date`, the document transitions to `EXPIRED` (terminal), and from that point the campus no longer satisfies the site-plan gate for EOP submission until a new document is published."
        PRD: "first, the site must have a SitePlanDocument in `CURRENT` status (else `ERR_SITE_PLAN_REQUIRED`, HTTP 409)"

        Design: Corner/state_machines/site_plan_expiry_by_clock_sweep
        """
        site = create_site()
        document = publish_site_plan(site["id"], review_by_date="2026-09-01")
        walkthrough = schedule_walkthrough(site["id"], agency="FIRE",
                                           scheduled_date="2026-07-20")
        complete_walkthrough(walkthrough["id"], completed_date="2026-07-20")
        eop = create_eop(site["id"])

        set_clock("2026-09-02T00:00:00Z")

        current_doc = get_site_plan_document(site["id"], document["id"])
        assert current_doc["status"] == "EXPIRED", (
            f"Site plan past its review_by_date must be EXPIRED, "
            f"got {current_doc['status']}")

        resp = api.submit_eop(eop["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_PLAN_REQUIRED)


class TestWalkthroughDrillDayConflict:
    def test_walkthrough_drill_day_conflict(self, api, officer_headers):
        """PRD: "A walkthrough may not share a calendar date with any drill at the same site that is in `SCHEDULED` or `IN_PROGRESS` status — this is a whole-day exclusion checked in both directions, so scheduling a walkthrough on a drill day is rejected with `ERR_WALKTHROUGH_DRILL_CONFLICT`, and conversely scheduling a drill on a walkthrough's `scheduled_date` (when the walkthrough is `SCHEDULED`) is likewise rejected."

        Design: Corner/validations/walkthrough_drill_day_conflict
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        site_id = ctx["site"]["id"]
        schedule_drill(site_id, scheduled_date="2026-09-15")

        same_day = api.create_walkthrough(
            create_walkthrough_payload(site_id=site_id, agency="FIRE",
                                       scheduled_date="2026-09-15"),
            officer_headers,
        )
        validate_error(same_day, ApiErrorId.ERR_WALKTHROUGH_DRILL_CONFLICT)

        next_day = api.create_walkthrough(
            create_walkthrough_payload(site_id=site_id, agency="FIRE",
                                       scheduled_date="2026-09-16"),
            officer_headers,
        )
        created = validate_success(next_day, 201)
        assert created["status"] == "SCHEDULED"
        assert created["scheduled_date"] == "2026-09-16"


class TestWalkthroughCurrencyGate:
    def test_walkthrough_required_when_window_expired(self, api, officer_headers):
        """PRD: "second, the site must have a FirstResponderWalkthrough in `COMPLETED` status whose `completed_date` falls within the trailing 365-day window ending at logical today, inclusive of the boundary (a walkthrough completed exactly 365 days before today is eligible; else `ERR_WALKTHROUGH_REQUIRED`, HTTP 409)."

        Design: Corner/validations/walkthrough_required_when_window_expired
        """
        site = create_site()
        publish_site_plan(site["id"])
        old_walk = schedule_walkthrough(site["id"], agency="FIRE",
                                        scheduled_date="2025-06-30")
        complete_walkthrough(old_walk["id"], completed_date="2025-07-01",
                             findings_summary="Last year's walk")
        eop = create_eop(site["id"])

        # Logical today is 2026-08-01; 2025-07-01 is more than 365 days back.
        first = api.submit_eop(eop["id"], officer_headers)
        validate_error(first, ApiErrorId.ERR_WALKTHROUGH_REQUIRED)

        new_walk = schedule_walkthrough(site["id"], agency="POLICE",
                                        scheduled_date="2026-07-22")
        complete_walkthrough(new_walk["id"], completed_date="2026-07-22",
                             findings_summary="This year's walk",
                             recommendations_count=2)

        second = api.submit_eop(eop["id"], officer_headers)
        submitted = validate_success(second, 200)
        assert submitted["status"] == "SUBMITTED", (
            "An in-window COMPLETED walkthrough must unblock EOP submission")
