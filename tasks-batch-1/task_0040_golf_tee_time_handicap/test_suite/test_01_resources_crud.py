"""Resource creation, defaults, computed fields, field-level validation, and
foreign-key existence checks."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_course_payload, create_golfer_payload, create_score_payload,
    create_tee_time_payload, make_proshop_headers,
    create_course, create_golfer, set_clock,
)


class TestCourseCreation:
    def test_create_course_returns_201_with_fields(self, api):
        """PRD §3.1: "A ProShop operator establishes a course by supplying its name, its
        course_rating and slope_rating, the peak_fee_cents and offpeak_fee_cents, and
        optionally the peak-window hours peak_start_hour and peak_end_hour and the
        member_discount_pct."
        PRD §2.4: "The version field is an integer that starts at 1 and increments by exactly
        1 on every mutation."

        Design: Corner/entities/create_course_returns_201_with_all_fields
        """
        resp = api.create_course(
            create_course_payload(name="Augusta", course_rating=76.2, slope_rating=137,
                                   peak_fee_cents=12000, offpeak_fee_cents=8000),
            make_proshop_headers(),
        )
        course = validate_success(resp, 201)
        assert course["course_rating"] == 76.2
        assert course["slope_rating"] == 137
        assert course["version"] == 1

    def test_course_default_peak_window_and_discount(self, api):
        """PRD §2.8: "The peak_start_hour is the local hour, inclusive, at which peak pricing
        begins and defaults to 7; the peak_end_hour is the local hour, exclusive, at which
        peak pricing ends and defaults to 15. ... a value between 0.0 and 1.0 inclusive that
        defaults to 0.20."

        Design: Corner/entities/course_default_peak_window_and_discount_applied
        """
        course = create_course(name="Defaults")
        assert course["peak_start_hour"] == 7
        assert course["peak_end_hour"] == 15
        assert course["member_discount_pct"] == 0.20


class TestGolferDefaults:
    def test_golfer_defaults_public_and_empty_handicaps(self, api):
        """PRD §3.1: "A registration supplies the golfer's full_name and, optionally, a
        membership_tier; when the tier is omitted the golfer is PUBLIC. A newly registered
        golfer has no handicap history yet, so its computed handicap_index,
        provisional_handicap_index, and low_handicap_index all begin empty (null), its
        handicap_revision begins at 0."

        Design: Corner/entities/golfer_default_membership_tier_public
        """
        resp = api.create_golfer(create_golfer_payload(full_name="Defaulted"), make_proshop_headers())
        golfer = validate_success(resp, 201)
        assert golfer["membership_tier"] == "PUBLIC"
        assert golfer["handicap_index"] is None
        assert golfer["handicap_revision"] == 0


class TestComputedFields:
    def test_teetime_capacity_derived_from_group_type(self, api):
        """PRD §3.5: "On creation the slot derives its capacity from the group type — TWOSOME
        seats 2 and FOURSOME seats 4 — sets confirmed_count to 0, and opens in OPEN status."

        Design: Corner/entities/teetime_capacity_derived_from_group_type
        """
        set_clock()
        course = create_course(name="CapCrs")
        resp = api.create_tee_time(
            create_tee_time_payload(course["id"], "2026-06-20T09:00:00Z", 9, "FOURSOME"),
            make_proshop_headers(),
        )
        tt = validate_success(resp, 201)
        assert tt["capacity"] == 4
        assert tt["confirmed_count"] == 0
        assert tt["status"] == "OPEN"


class TestFieldValidation:
    def test_create_course_missing_slope_rejected(self, api):
        """PRD §2.9: "Any missing required field, malformed enum, out-of-range number, or
        violated ordering constraint is rejected with ERR_VALIDATION and HTTP status 422."

        Design: Corner/entities/create_course_missing_required_field
        """
        resp = api.create_course(
            {"name": "NoSlope", "course_rating": 70.0, "peak_fee_cents": 8000, "offpeak_fee_cents": 5000},
            make_proshop_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_course_slope_out_of_range_rejected(self, api):
        """PRD §2.7: "The slope_rating is an integer in the inclusive range from 55 to 155 and
        acts as the per-round normalizer."
        PRD §2.9: "any ... out-of-range number ... is rejected with ERR_VALIDATION and HTTP
        status 422."

        Design: Corner/entities/course_slope_out_of_range_rejected
        """
        resp = api.create_course(
            create_course_payload(name="BadSlope", slope_rating=200), make_proshop_headers()
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_course_peak_end_not_after_start_rejected(self, api):
        """PRD §2.9: "A course's peak_end_hour must be strictly greater than its
        peak_start_hour, and both hours lie in the inclusive range 0 through 23."

        Design: Corner/entities/course_peak_end_not_after_start_rejected
        """
        resp = api.create_course(
            create_course_payload(name="BadWindow", peak_start_hour=7, peak_end_hour=7),
            make_proshop_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_score_invalid_ags_range_rejected(self, api):
        """PRD §2.9: "A posted round's adjusted_gross_score is an integer in the inclusive
        range from 50 to 150."

        Design: Corner/entities/score_invalid_ags_range_rejected
        """
        course = create_course(name="AgsCourse")
        golfer = create_golfer(full_name="AG", membership_tier="PUBLIC")
        resp = api.create_score(
            create_score_payload(golfer["id"], course["id"], "2026-05-01", 40),
            make_proshop_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
