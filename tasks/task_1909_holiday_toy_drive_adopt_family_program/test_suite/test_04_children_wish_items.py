"""Child registration: age-band derivation, caps, and wish-list valuation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_child_payload, create_wish_item_payload, ApiErrorId,
    setup_campaign_intake_open, create_family, add_child, add_wish_item,
    get_child, make_agency_coordinator_headers, make_caseworker_headers,
)


class TestAgeBandComputation:
    def test_age_band_computed_from_dob_at_create(self, api):
        """PRD §3.4: "On create, the server computes the child's `age_band` from
        the child's `dob` and the parent campaign's `distribution_date`." PRD §3.4:
        "The band is then `INFANT` if the age in years is less than 1, `TODDLER`
        if it is at least 1 and less than 3, `PRESCHOOL` if it is at least 3 and
        less than 5, `SCHOOL_AGE` if it is at least 5 and less than 10, `PRETEEN`
        if it is at least 10 and less than 13, and `TEEN` if it is at least 13 and
        less than 19." A child born 2022-06-01 is 4 years old on 2026-12-18.

        Design: Corner/entities/child_age_band_computed_not_client_settable
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        child = add_child(family["id"], agency["id"], dob="2022-06-01")
        assert child["age_band"] == "PRESCHOOL"

    def test_thirteen_year_boundary_maps_to_teen(self, api):
        """PRD §3.4: "The age in years is the floor of that day count divided by
        365.25." PRD §3.4: "The band is then `INFANT` if the age in years is less
        than 1, `TODDLER` if it is at least 1 and less than 3, `PRESCHOOL` if it
        is at least 3 and less than 5, `SCHOOL_AGE` if it is at least 5 and less
        than 10, `PRETEEN` if it is at least 10 and less than 13, and `TEEN` if it
        is at least 13 and less than 19." Against distribution_date 2026-12-18,
        dob 2013-12-17 yields 4749 days -> floor(13.002) = 13 -> TEEN, while dob
        2013-12-18 yields 4748 days -> floor(12.999) = 12 -> PRETEEN.

        Design: Corner/calculations/age_band_teen_boundary_at_13_years
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        teen = add_child(family["id"], agency["id"], first_name="teen",
                         dob="2013-12-17")
        preteen = add_child(family["id"], agency["id"], first_name="preteen",
                            dob="2013-12-18")
        assert teen["age_band"] == "TEEN"
        assert preteen["age_band"] == "PRETEEN"

    def test_nineteen_at_distribution_rejected(self, api):
        """PRD §3.4: "A child whose age in years is 19 or greater is rejected at
        create time with `ERR_CHILD_TOO_OLD` (HTTP 422)." Against
        distribution_date 2026-12-18, dob 2007-12-18 yields 6940 days ->
        floor(19.000) = 19, while dob 2007-12-19 yields 6939 days -> 18.

        Design: Corner/calculations/child_exactly_19_at_distribution_rejected
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        too_old = api.create_child(
            family["id"],
            create_child_payload(first_name="old", dob="2007-12-18"),
            make_agency_coordinator_headers(agency["id"]))
        validate_error(too_old, ApiErrorId.ERR_CHILD_TOO_OLD, expected_status=422)
        still_ok = api.create_child(
            family["id"],
            create_child_payload(first_name="ok", dob="2007-12-19"),
            make_agency_coordinator_headers(agency["id"]))
        child = validate_success(still_ok, 201)
        assert child["age_band"] == "TEEN"

    def test_invalid_gender_enum_rejected(self, api):
        """PRD §2.8: "A required field that is missing, of the wrong type, or an
        enum value outside its declared set yields `ERR_INVALID_REQUEST`
        (HTTP 400)." PRD §3.4: "`gender` (one of `F`, `M`, or `X`)".

        Design: Corner/entities/child_invalid_gender_enum_rejected
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        res = api.create_child(
            family["id"], create_child_payload(gender="Q"),
            make_agency_coordinator_headers(agency["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestFamilyChildCap:
    def test_child_added_at_exact_cap_succeeds(self, api):
        """PRD §3.4: "Adding a child is capped by the campaign's
        `max_children_per_family`: if the family's `total_children_count` has
        already reached that cap, the create is rejected with
        `ERR_FAMILY_CHILD_CAP` (HTTP 409)." With cap 2, the second child brings
        the count to exactly the cap and is permitted.

        Design: Difficulty/boundary_precision_check/family_child_cap_at_exact_limit_vs_one_over
        """
        campaign, agency = setup_campaign_intake_open(max_children_per_family=2)
        family = create_family(agency, campaign)
        first = add_child(family["id"], agency["id"], first_name="c1")
        second = add_child(family["id"], agency["id"], first_name="c2",
                           dob="2019-01-01")
        assert first["id"] != second["id"]
        family_after = api.get_family(family["id"],
                                      make_agency_coordinator_headers(
                                          agency["id"]))
        assert validate_success(family_after)["total_children_count"] == 2

    def test_child_one_over_cap_rejected(self, api):
        """PRD §3.4: "Adding a child is capped by the campaign's
        `max_children_per_family`: if the family's `total_children_count` has
        already reached that cap, the create is rejected with
        `ERR_FAMILY_CHILD_CAP` (HTTP 409)." With cap 2 and two children present,
        the third create exceeds the cap.

        Design: Difficulty/boundary_precision_check/family_child_cap_at_exact_limit_vs_one_over
        """
        campaign, agency = setup_campaign_intake_open(max_children_per_family=2)
        family = create_family(agency, campaign)
        add_child(family["id"], agency["id"], first_name="c1")
        add_child(family["id"], agency["id"], first_name="c2", dob="2019-01-01")
        res = api.create_child(
            family["id"], create_child_payload(first_name="c3",
                                               dob="2018-01-01"),
            make_agency_coordinator_headers(agency["id"]))
        validate_error(res, ApiErrorId.ERR_FAMILY_CHILD_CAP, expected_status=409)


class TestWishListValuation:
    def test_rejected_items_excluded_from_estimate(self, api, admin_headers):
        """PRD §3.4: "Each child carries a computed `gift_estimate_cents`, the sum
        of `estimated_price_cents` over the child's wish items whose status is
        either `REQUESTED` or `APPROVED`. Items in `REJECTED`, `COMMITTED`,
        `RECEIVED`, `DELIVERED`, or `BACKFILL_SOURCED` are excluded from the sum."

        Design: Corner/calculations/wish_list_value_excludes_rejected_items
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        child = add_child(family["id"], agency["id"])
        add_wish_item(child["id"], agency["id"], estimated_price_cents=3000,
                      priority_rank=1)
        drop = add_wish_item(child["id"], agency["id"],
                             estimated_price_cents=7000, priority_rank=2)
        validate_success(api.reject_wish_item(drop["id"],
                                              make_caseworker_headers("cw_1")))
        child_after = get_child(child["id"])
        assert child_after["gift_estimate_cents"] == 3000, \
            "the REJECTED 7000-cent item must be excluded from the estimate"

    def test_cumulative_wish_value_over_cap_rejected_at_create(self, api):
        """PRD §3.4: "The same per-child cap applies at wish-item create: the sum
        of the child's `REQUESTED` plus `APPROVED` items after the write must not
        exceed `max_gift_value_cents`. Either violation yields
        `ERR_WISH_VALUE_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/wish_item_value_exceeds_campaign_cap
        """
        campaign, agency = setup_campaign_intake_open(max_gift_value_cents=5000,
                                                      min_gift_value_cents=1000)
        family = create_family(agency, campaign)
        child = add_child(family["id"], agency["id"])
        headers = make_agency_coordinator_headers(agency["id"])
        first = api.create_wish_item(
            child["id"], create_wish_item_payload(estimated_price_cents=3000,
                                                  priority_rank=1), headers)
        validate_success(first, 201)
        over = api.create_wish_item(
            child["id"], create_wish_item_payload(estimated_price_cents=3000,
                                                  priority_rank=2), headers)
        validate_error(over, ApiErrorId.ERR_WISH_VALUE_EXCEEDED,
                       expected_status=422)
