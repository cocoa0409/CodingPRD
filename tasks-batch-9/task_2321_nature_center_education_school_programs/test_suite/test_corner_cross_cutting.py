"""Cross-cutting behaviour of the Nature Center Education API.

These tests exercise rules that span several entities at once: the optimistic
concurrency preconditions of PRD §2.8, the version discipline of PRD §2.4, the
rain-plan selector of PRD §3.7 and the money cascade that PRD §3.7 and §3.8
drive out of a single delivery call.
"""

from test_helpers import (
    BC,
    ED,
    GO,
    DEFAULT_ALIGNMENTS,
    ApiErrorId,
    assert_fund_ledger_conserved,
    confirm_booking,
    create_aid_application_payload,
    create_fund,
    create_published_offering,
    create_trail_segment,
    refresh_booking,
    setup_booking_scenario,
    setup_booking_with_approved_aid,
    validate_error,
    validate_success,
)

# Three claims are enough to out-rank a two-claim alternate on standards coverage.
_THREE_ALIGNMENTS = (
    {"standard_code": "3-LS4-3", "dimension": "DISCIPLINARY_CORE_IDEA"},
    {"standard_code": "3-LS4-4", "dimension": "SCIENCE_PRACTICE"},
    {"standard_code": "3-ESS2-1", "dimension": "CROSSCUTTING_CONCEPT"},
)


def _publish_rain_alternate(
    primary_offering_id: str,
    title: str,
    base_fee_cents_per_student: int,
    alignments,
    slug_prefix: str,
) -> dict:
    """Publish an offering that declares itself a rain alternate for ``primary_offering_id``."""
    return create_published_offering(
        alignments=alignments,
        slug_prefix=slug_prefix,
        title=title,
        base_fee_cents_per_student=base_fee_cents_per_student,
        rain_alternate_for_offering_id=primary_offering_id,
    )


def _setup_rain_alternate_pool() -> dict:
    """A CONFIRMED booking on a primary offering that has four declared rain alternates.

    The four alternates are arranged so that each ranking key decides a different
    comparison: alternate A is the cheapest of all but carries only two standards
    claims, alternate D is the cheapest of the three-claim group, and alternates B
    and C tie on both coverage and price with B created first.
    """
    scenario = setup_booking_scenario()
    primary_id = scenario["offering"]["id"]
    scenario["alternate_a"] = _publish_rain_alternate(
        primary_id, "Indoor Watershed Lab", 700, DEFAULT_ALIGNMENTS, "alt-a"
    )
    scenario["alternate_b"] = _publish_rain_alternate(
        primary_id, "Owl Pellet Lab", 900, _THREE_ALIGNMENTS, "alt-b"
    )
    scenario["alternate_c"] = _publish_rain_alternate(
        primary_id, "Seed Dispersal Lab", 900, _THREE_ALIGNMENTS, "alt-c"
    )
    scenario["alternate_d"] = _publish_rain_alternate(
        primary_id, "Water Quality Lab", 600, _THREE_ALIGNMENTS, "alt-d"
    )
    scenario["booking"] = confirm_booking(scenario["booking"]["id"])
    return scenario


class TestOptimisticConcurrencyPreconditions:
    def test_stale_expected_booking_version_is_refused_and_assigns_nothing(self, api):
        """PRD §2.8: "If `expected_booking_version` does not equal the booking's current `version`, the request is rejected with `ERR_STALE_BOOKING_VERSION` and HTTP 412."

        Design: Corner/cross-cutting complexity layers/a_booking_version_captured_before_an_assignment_is_refused_afterwards
        """
        scenario = setup_booking_scenario(
            assign_educator=False,
            offering_overrides={"requires_trail_segment": True},
        )
        booking_id = scenario["booking"]["id"]
        educator_id = scenario["educator"]["id"]
        trail = create_trail_segment(
            capacity_persons=60, weekly_visitor_budget_persons=300
        )
        assert scenario["booking"]["version"] == 1

        assigned = validate_success(
            api.assign_booking_resources(
                booking_id,
                {"expected_booking_version": 1, "lead_educator_id": educator_id},
                BC,
            )
        )
        assert assigned["version"] == 2
        assert assigned["lead_educator_id"] == educator_id

        replayed = api.assign_booking_resources(
            booking_id,
            {"expected_booking_version": 1, "trail_segment_id": trail["id"]},
            BC,
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_BOOKING_VERSION.value)

        mid = refresh_booking(booking_id)
        assert mid["trail_segment_id"] is None, (
            "a refused assignment must not partially apply the trail segment"
        )
        assert mid["version"] == 2

        fresh = validate_success(
            api.assign_booking_resources(
                booking_id,
                {"expected_booking_version": 2, "trail_segment_id": trail["id"]},
                BC,
            )
        )
        assert fresh["version"] == 3
        assert fresh["trail_segment_id"] == trail["id"]

    def test_a_freeze_and_reopen_makes_the_original_fund_version_stale(self, api):
        """PRD §2.8: "If `expected_fund_version` does not equal the fund's current `version`, the request is rejected with `ERR_STALE_FUND_VERSION` and HTTP 412."

        Design: Corner/cross-cutting complexity layers/a_fund_version_captured_before_a_freeze_and_reopen_is_refused
        """
        scenario = setup_booking_scenario(assign_educator=False)
        booking_id = scenario["booking"]["id"]
        fund = create_fund()
        assert fund["version"] == 1

        frozen = validate_success(
            api.set_scholarship_fund_status(fund["id"], {"status": "FROZEN"}, GO)
        )
        assert frozen["status"] == "FROZEN"
        assert frozen["version"] == 2

        reopened = validate_success(
            api.set_scholarship_fund_status(fund["id"], {"status": "OPEN"}, GO)
        )
        assert reopened["status"] == "OPEN"
        assert reopened["version"] == 3

        stale = api.create_aid_application(
            create_aid_application_payload(
                booking_id,
                fund["id"],
                1,
                requested_scholarship_cents=9000,
                requested_transport_cents=0,
            ),
            BC,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_FUND_VERSION.value)

        accepted = validate_success(
            api.create_aid_application(
                create_aid_application_payload(
                    booking_id,
                    fund["id"],
                    3,
                    requested_scholarship_cents=9000,
                    requested_transport_cents=0,
                ),
                BC,
            ),
            expected_status=201,
        )
        assert accepted["status"] == "SUBMITTED"
        assert accepted["fund_id"] == fund["id"]


class TestBookingVersionCounter:
    def test_a_confirmation_missing_a_required_resource_leaves_the_version_untouched(
        self, api
    ):
        """PRD §3.6: "It then insists that the resources the programme actually needs are present: `lead_educator_id` must be set on every booking, `trail_segment_id` must be set when the offering's `requires_trail_segment` is true, and `animal_id` must be set when `requires_live_animal` is true — a gap answers `ERR_REQUIRED_RESOURCE_MISSING`."

        Design: Corner/cross-cutting complexity layers/the_version_counter_advances_once_per_accepted_write_and_never_on_a_refusal
        """
        scenario = setup_booking_scenario(
            assign_educator=False,
            offering_overrides={"requires_trail_segment": True},
        )
        booking_id = scenario["booking"]["id"]
        assert scenario["booking"]["version"] == 1

        refused = api.confirm_booking(booking_id, BC)
        validate_error(refused, ApiErrorId.ERR_REQUIRED_RESOURCE_MISSING.value)

        after = refresh_booking(booking_id)
        assert after["version"] == 1, "a rejected request mutates nothing"
        assert after["delivery_status"] == "REQUESTED"

    def test_each_accepted_write_advances_the_booking_version_by_exactly_one(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource."

        Design: Corner/cross-cutting complexity layers/the_version_counter_advances_once_per_accepted_write_and_never_on_a_refusal
        """
        scenario = setup_booking_scenario(
            assign_educator=False,
            offering_overrides={"requires_trail_segment": True},
        )
        booking_id = scenario["booking"]["id"]
        educator_id = scenario["educator"]["id"]
        trail = create_trail_segment(
            capacity_persons=60, weekly_visitor_budget_persons=300
        )
        assert scenario["booking"]["version"] == 1

        assigned = validate_success(
            api.assign_booking_resources(
                booking_id,
                {
                    "expected_booking_version": 1,
                    "trail_segment_id": trail["id"],
                    "lead_educator_id": educator_id,
                },
                BC,
            )
        )
        assert assigned["version"] == 2

        confirmed = validate_success(api.confirm_booking(booking_id, BC))
        assert confirmed["version"] == 3

        delivered = validate_success(
            api.deliver_booking(
                booking_id,
                {"actual_student_count": 30, "actual_chaperone_count": 3},
                BC,
            )
        )
        assert delivered["version"] == 4
        assert delivered["delivery_status"] == "DELIVERED"


class TestRainAlternateSelector:
    def test_the_selector_prefers_coverage_then_the_cheaper_of_the_well_covered(self, api):
        """PRD §3.7: "The pool is ranked by `standard_alignment_count` descending, so the best-aligned substitute wins; ties on alignment count are broken by `base_fee_cents_per_student` ascending, so the cheaper substitute wins; and ties on both are broken by `created_at` ascending, so the longest-standing offering wins."

        Design: Corner/cross-cutting complexity layers/the_rain_selector_ranks_on_coverage_then_price_and_only_then_on_creation_order
        """
        pool = _setup_rain_alternate_pool()
        booking_id = pool["booking"]["id"]

        diverted = validate_success(
            api.rain_divert_booking(
                booking_id, {"reason": "Storm cell over the property"}, BC
            )
        )
        assert diverted["rain_diverted_to_offering_id"] == pool["alternate_d"]["id"], (
            "the cheapest three-claim alternate wins over the cheaper two-claim one"
        )
        assert diverted["delivery_status"] == "RAIN_DIVERTED"
        assert diverted["provisional_gross_fee_cents"] == 26640

        delivered = validate_success(
            api.deliver_booking(
                booking_id,
                {"actual_student_count": 30, "actual_chaperone_count": 3},
                BC,
            )
        )
        assert delivered["final_gross_fee_cents"] == 26640
        assert pool["alternate_a"]["standard_alignment_count"] == 2

    def test_a_tie_on_coverage_and_price_falls_to_the_earlier_creation_order(self, api):
        """PRD §3.7: "The pool is ranked by `standard_alignment_count` descending, so the best-aligned substitute wins; ties on alignment count are broken by `base_fee_cents_per_student` ascending, so the cheaper substitute wins; and ties on both are broken by `created_at` ascending, so the longest-standing offering wins."

        Design: Corner/cross-cutting complexity layers/the_rain_selector_ranks_on_coverage_then_price_and_only_then_on_creation_order
        """
        pool = _setup_rain_alternate_pool()

        retired = validate_success(
            api.retire_program_offering(
                pool["alternate_d"]["id"], ED, {"reason": "Instructor on leave"}
            )
        )
        assert retired["status"] == "RETIRED"
        assert pool["alternate_c"]["base_fee_cents_per_student"] == 900

        diverted = validate_success(
            api.rain_divert_booking(
                pool["booking"]["id"], {"reason": "Storm cell over the property"}, BC
            )
        )
        assert diverted["rain_diverted_to_offering_id"] == pool["alternate_b"]["id"], (
            "with the winner retired the earlier of the two tied alternates wins"
        )


class TestDeliveryMoneyCascade:
    def test_one_delivery_disburses_the_award_and_bills_the_school(self, api):
        """PRD §3.7: "Both branches then compute `final_gross_fee_cents` through the final variant of the fee assessment, recompute `net_due_cents` from it, advance `funding_status` to `INVOICED`, transition every aid application of this booking whose status is `APPROVED` or `PARTIALLY_APPROVED` to `DISBURSED`, and recompute the school's `outstanding_balance_cents`."

        Design: Corner/cross-cutting complexity layers/delivery_settles_the_award_the_fund_and_the_school_ledger_in_one_write
        """
        scenario = setup_booking_with_approved_aid(
            requested_scholarship_cents=20000, requested_transport_cents=0
        )
        assert scenario["aid_application"]["status"] == "APPROVED"
        booking_id = scenario["booking"]["id"]
        confirm_booking(booking_id)

        delivered = validate_success(
            api.deliver_booking(
                booking_id,
                {"actual_student_count": 30, "actual_chaperone_count": 3},
                BC,
            )
        )
        assert delivered["delivery_status"] == "DELIVERED"
        assert delivered["funding_status"] == "INVOICED"
        assert delivered["final_gross_fee_cents"] == 33300
        assert delivered["net_due_cents"] == 13300

        application = validate_success(
            api.get_aid_application(scenario["aid_application"]["id"], GO)
        )
        assert application["status"] == "DISBURSED"

        fund = validate_success(api.get_scholarship_fund(scenario["fund"]["id"], GO))
        assert fund["committed_cents"] == 0
        assert fund["disbursed_cents"] == 20000
        assert fund["available_cents"] == 4980000
        assert_fund_ledger_conserved(fund)

        school = validate_success(api.get_school(scenario["school"]["id"], GO))
        assert school["outstanding_balance_cents"] == 13300
        assert school["status"] == "ACTIVE"
