"""Which check fires first when a single request breaks several rules at once,
and which checks only apply under a condition."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_assessment_roll_payload,
    create_delinquency_action_payload,
    make_clerk_headers,
    make_commissioner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    read_charge,
    read_member,
    read_parcel,
    read_project,
    reclassify_parcel_payload,
    recall_payload,
    set_clock,
    setup_annual_assessment,
    setup_assessment_roll,
    setup_association,
    setup_member,
    setup_parcel,
    setup_project,
    setup_road_segment,
    subdivide,
    validate_error,
    validate_paginated,
    validate_success,
    verify_deed_payload,
)
from test_helpers import list_roll_charges

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-2")

MAIN_SEGMENT = {
    "length_feet": 1600,
    "width_feet": 22,
    "max_grade_pct": 8,
    "surface_type": "GRAVEL",
    "turnout_count": 1,
    "turnaround_present": True,
    "bridge_present": False,
    "culvert_count": 2,
}


def _open_roll(association_id, **overrides):
    payload = create_assessment_roll_payload(association_id, **overrides)
    return api_client.create_assessment_roll(payload, CLERK)


class TestFiscalIntervalUniqueness:
    """Two uniqueness rules on a roll, in a fixed order."""

    def test_a_touching_interval_opens_a_second_roll(self, api):
        """PRD §3.4: "Two uniqueness rules apply: no other roll of the association
        may already carry that `fiscal_year`, and the roll's closed fiscal interval
        may not overlap any existing roll's interval of that association by even one
        day. Intervals that merely touch — one roll ending the day before the next
        begins — are permitted"

        Design: Corner/validations/fiscal_year_duplication_outranks_interval_overlap_while_touching_intervals_pass
        """
        association = setup_association(
            name="Calendar Hill Road Association", reserve_target_cents=1_000_000
        )
        setup_assessment_roll(
            association["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
        )

        second = validate_success(
            _open_roll(
                association["id"],
                fiscal_year=2027,
                fy_start_date="2027-01-01",
                fy_end_date="2027-12-31",
                budget_requirement_cents=4_100_000,
            ),
            expected_status=201,
        )

        assert second["status"] == "DRAFT"
        assert second["fy_start_date"] == "2027-01-01"
        assert second["total_levied_cents"] == 0
        assert second["total_share_units"] == pytest.approx(0, abs=0.0001)

    def test_one_shared_day_is_an_overlap(self, api):
        """PRD §2.10: "43. The roll's fiscal interval does not overlap another
        roll's interval — otherwise `ERR_FISCAL_INTERVAL_OVERLAP` (409)."
        PRD §3.4: "the roll's closed fiscal interval may not overlap any existing
        roll's interval of that association by even one day."

        Design: Corner/validations/fiscal_year_duplication_outranks_interval_overlap_while_touching_intervals_pass
        """
        association = setup_association(
            name="Calendar Hill Road Association", reserve_target_cents=1_000_000
        )
        setup_assessment_roll(
            association["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
        )
        validate_success(
            _open_roll(
                association["id"],
                fiscal_year=2027,
                fy_start_date="2027-01-01",
                fy_end_date="2027-12-31",
                budget_requirement_cents=4_100_000,
            ),
            expected_status=201,
        )

        response = _open_roll(
            association["id"],
            fiscal_year=2028,
            fy_start_date="2027-12-31",
            fy_end_date="2028-12-31",
            budget_requirement_cents=4_200_000,
        )

        validate_error(response, "ERR_FISCAL_INTERVAL_OVERLAP", 409)
        _, meta = validate_paginated(
            api_client.list_assessment_rolls(
                CLERK, params={"association_id": association["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 2, "the rejected submission persisted no row"

    def test_a_duplicate_fiscal_year_masks_the_overlap(self, api):
        """PRD §2.10: "42. No other roll of the association shares this
        `fiscal_year` — otherwise `ERR_FISCAL_YEAR_ROLL_EXISTS` (409)."
        PRD §2.10: "every request walks the following checks in this exact order,
        and the first failure is the error returned. Where several checks could all
        fire, the earlier one masks the later ones."

        Design: Corner/validations/fiscal_year_duplication_outranks_interval_overlap_while_touching_intervals_pass
        """
        association = setup_association(
            name="Calendar Hill Road Association", reserve_target_cents=1_000_000
        )
        setup_assessment_roll(
            association["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
        )
        validate_success(
            _open_roll(
                association["id"],
                fiscal_year=2027,
                fy_start_date="2027-01-01",
                fy_end_date="2027-12-31",
                budget_requirement_cents=4_100_000,
            ),
            expected_status=201,
        )

        # Duplicates FY2026 and overlaps FY2027 at the same time.
        response = _open_roll(
            association["id"],
            fiscal_year=2026,
            fy_start_date="2027-06-01",
            fy_end_date="2028-05-31",
            budget_requirement_cents=4_300_000,
        )

        validate_error(response, "ERR_FISCAL_YEAR_ROLL_EXISTS", 409)
        _, meta = validate_paginated(
            api_client.list_assessment_rolls(
                CLERK, params={"association_id": association["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 2


class TestDeedVerificationIsAThreeWayEquality:
    """The submitted page must match the member row and the parcel row."""

    def _two_deeds(self):
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Deed Book Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Deed Book Main", **MAIN_SEGMENT)
        parcel_a = setup_parcel(
            segment["id"],
            deed_book_page="DB150-P01",
            frontage_feet=240,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=4,
            covenant_recorded=True,
        )
        member_a = setup_member(
            parcel_a["id"],
            verified=False,
            owner_name="A. Whitcomb",
            deed_book_page="DB150-P01",
            deed_recorded_date="2019-04-11",
        )
        parcel_b = setup_parcel(
            segment["id"],
            deed_book_page="DB150-P02",
            frontage_feet=200,
            usage_class="SEASONAL",
            trips_per_day=2,
            covenant_recorded=True,
        )
        member_b = setup_member(
            parcel_b["id"],
            verified=False,
            owner_name="B. Okafor",
            deed_book_page="DB150-P02X",
            deed_recorded_date="2020-06-02",
        )
        return member_a, member_b

    def test_a_page_matching_neither_record_is_refused(self, api):
        """PRD §3.3: "The secretary submits a `verified_deed_book_page`, which must
        equal both the member's own asserted `deed_book_page` and the
        `deed_book_page` recorded against the parcel; any divergence is rejected
        with `ERR_DEED_MISMATCH`."

        Design: Corner/validations/verify_deed_requires_matching_member_and_parcel_pages
        """
        member_a, _ = self._two_deeds()

        response = api_client.verify_deed(
            member_a["id"], verify_deed_payload("DB150-P09"), SECRETARY
        )

        validate_error(response, "ERR_DEED_MISMATCH", 409)
        held = read_member(member_a["id"])
        assert held["standing_status"] == "PENDING_DEED_VERIFICATION"
        assert held["deed_verified_at"] is None

    def test_a_page_matching_only_the_member_row_is_refused(self, api):
        """PRD §2.10: "30. `verified_deed_book_page` equals both the member's
        `deed_book_page` and the parcel's `deed_book_page` — otherwise
        `ERR_DEED_MISMATCH` (409)."

        Design: Corner/validations/verify_deed_requires_matching_member_and_parcel_pages
        """
        _, member_b = self._two_deeds()
        assert member_b["deed_book_page"] == "DB150-P02X"

        response = api_client.verify_deed(
            member_b["id"], verify_deed_payload("DB150-P02X"), SECRETARY
        )

        validate_error(response, "ERR_DEED_MISMATCH", 409)
        assert read_member(member_b["id"])["standing_status"] == "PENDING_DEED_VERIFICATION"

    def test_the_matching_page_verifies_and_a_repeat_is_already_verified(self, api):
        """PRD §3.3: "A second attempt on an already-verified member fails with
        `ERR_MEMBER_ALREADY_VERIFIED`. On success the member advances
        `PENDING_DEED_VERIFICATION → GOOD_STANDING`, `deed_verified_at` is stamped
        with the current logical-clock instant, and the member's parcel becomes
        eligible to appear on an assessment roll."

        Design: Corner/validations/verify_deed_requires_matching_member_and_parcel_pages
        """
        member_a, _ = self._two_deeds()

        verified = validate_success(
            api_client.verify_deed(member_a["id"], verify_deed_payload("DB150-P01"), SECRETARY)
        )
        assert verified["standing_status"] == "GOOD_STANDING"
        assert verified["access_status"] == "UNRESTRICTED"
        assert verified["deed_verified_at"].startswith("2026-08-01T00:00:00")
        assert verified["version"] == 2

        repeat = api_client.verify_deed(
            member_a["id"], verify_deed_payload("DB150-P01"), SECRETARY
        )
        validate_error(repeat, "ERR_MEMBER_ALREADY_VERIFIED", 409)

        after = read_member(member_a["id"])
        assert after["deed_verified_at"] == verified["deed_verified_at"]
        assert after["version"] == 2


SINGLE_PARCEL_151 = [
    {
        "deed_book_page": "DB151-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]


def _past_due_charge(association_name, segment_name, parcel_specs):
    """A levied single-parcel roll read at 2026-10-15, thirty grace days past the
    charge's 2026-09-15 due date."""
    set_clock("2026-08-01T00:00:00Z")
    scenario = setup_annual_assessment(
        parcel_specs=parcel_specs,
        fiscal_year=2026,
        fy_start_date="2026-01-01",
        fy_end_date="2026-12-31",
        budget_requirement_cents=4_000_000,
        method_variant="FRONTAGE_WEIGHTED",
        association_overrides={"name": association_name, "reserve_target_cents": 1_000_000},
        segment_overrides=dict(MAIN_SEGMENT, name=segment_name),
    )
    scenario["charge"] = list_roll_charges(scenario["roll"]["id"])[0]
    return scenario


class TestRestrictionDatesApplyOnlyToRestrictions:
    """One conditional date rule, four ways of meeting or missing it."""

    @pytest.mark.parametrize(
        "dates,label",
        [
            ({}, "no dates at all"),
            (
                {"restriction_start_date": "2026-11-16", "restriction_end_date": "2026-11-01"},
                "an inverted window",
            ),
            (
                {"restriction_start_date": "2026-12-20", "restriction_end_date": "2027-01-05"},
                "a window running past the fiscal year end",
            ),
        ],
    )
    def test_an_access_restriction_needs_a_well_formed_in_year_window(self, api, dates, label):
        """PRD §2.10: "49. Date ranges are well formed: restriction dates are
        present for an `ACCESS_RESTRICTION` and form a half-open interval whose
        start precedes its end and which lies inside the fiscal interval of the
        charge's roll; `balloting_closes_at` is after the current clock;
        `completed_at` is not before the project's `window_start_date`; and a roll's
        `fy_start_date` precedes its `fy_end_date` — otherwise
        `ERR_INVALID_DATE_RANGE` (422)."

        Design: Corner/validations/restriction_dates_are_required_and_bounded_only_for_access_restriction
        """
        scenario = _past_due_charge(
            "Conditional Dates Road Association", "Conditional Dates Main", SINGLE_PARCEL_151
        )
        set_clock("2026-10-15T00:00:00Z")

        response = api_client.create_delinquency_action(
            scenario["charge"]["id"],
            dict({"action_type": "ACCESS_RESTRICTION"}, **dates),
            TREASURER,
        )

        validate_error(response, "ERR_INVALID_DATE_RANGE", 422)
        assert read_charge(scenario["charge"]["id"])["status"] == "OPEN", (
            f"{label} never even reaches the charge"
        )

    def test_a_dateless_notice_is_accepted_with_zero_restriction_days(self, api):
        """PRD §3.6: "The treasurer supplies an `action_type` of `NOTICE`,
        `LIEN_FILING`, or `ACCESS_RESTRICTION`, and for an `ACCESS_RESTRICTION` also
        a `restriction_start_date` and `restriction_end_date`."
        PRD §3.6: "The remedy's `restriction_days` is the whole number of days from
        the start date to the end date on that half-open reading, and it is zero for
        the other two action types."

        Design: Corner/validations/restriction_dates_are_required_and_bounded_only_for_access_restriction
        """
        scenario = _past_due_charge(
            "Conditional Dates Road Association", "Conditional Dates Main", SINGLE_PARCEL_151
        )
        set_clock("2026-10-15T00:00:00Z")

        notice = validate_success(
            api_client.create_delinquency_action(
                scenario["charge"]["id"], {"action_type": "NOTICE"}, TREASURER
            ),
            expected_status=201,
        )

        assert notice["status"] == "INITIATED"
        assert notice["restriction_start_date"] is None
        assert notice["restriction_end_date"] is None
        assert notice["restriction_days"] == 0

    def test_a_half_open_window_accrues_only_the_days_it_covers(self, api):
        """PRD §3.6: "Those two dates form a half-open interval — the start day is
        restricted, the end day is not — the start must fall strictly before the
        end, and the whole interval must lie inside the fiscal interval of the
        charge's roll; violations are rejected with `ERR_INVALID_DATE_RANGE`."
        PRD §2.8: "The companion counter `restricted_days_used` is the sum of
        `restriction_days` over that member's `ACCESS_RESTRICTION` actions whose
        `status` is `EFFECTIVE` or `RELEASED`"

        Design: Corner/validations/restriction_dates_are_required_and_bounded_only_for_access_restriction
        """
        scenario = _past_due_charge(
            "Conditional Dates Road Association", "Conditional Dates Main", SINGLE_PARCEL_151
        )
        set_clock("2026-10-15T00:00:00Z")
        validate_success(
            api_client.create_delinquency_action(
                scenario["charge"]["id"], {"action_type": "NOTICE"}, TREASURER
            ),
            expected_status=201,
        )

        restriction = validate_success(
            api_client.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload(
                    "ACCESS_RESTRICTION",
                    restriction_start_date="2026-11-01",
                    restriction_end_date="2026-11-16",
                ),
                TREASURER,
            ),
            expected_status=201,
        )

        assert restriction["status"] == "INITIATED"
        assert restriction["restriction_days"] == 15
        assert read_member(scenario["members"][0]["id"])["restricted_days_used"] == 0, (
            "nothing is EFFECTIVE yet, so no days are consumed"
        )

        _, meta = validate_paginated(
            api_client.list_charge_delinquency_actions(
                scenario["charge"]["id"], CLERK, params={"limit": 100}
            )
        )
        assert meta["total_count"] == 2


SINGLE_PARCEL_152 = [
    {
        "deed_book_page": "DB152-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]


class TestTheThirtiethGraceDay:
    """The same call, one second apart, on either side of a date boundary."""

    def test_the_day_before_the_boundary_is_too_early(self, api):
        """PRD §3.6: "the current logical-clock date must have reached the charge's
        `due_date` plus thirty grace days — an inclusive boundary, so a remedy on
        exactly the thirtieth day after the due date is permitted while anything
        earlier is rejected with `ERR_CHARGE_NOT_YET_DELINQUENT`."

        Design: Corner/validations/delinquency_remedy_opens_only_on_the_thirtieth_grace_day
        """
        scenario = _past_due_charge(
            "Grace Day Road Association", "Grace Day Main", SINGLE_PARCEL_152
        )
        assert scenario["charge"]["due_date"] == "2026-09-15"
        set_clock("2026-10-14T23:59:59Z")

        response = api_client.create_delinquency_action(
            scenario["charge"]["id"], create_delinquency_action_payload("NOTICE"), TREASURER
        )

        validate_error(response, "ERR_CHARGE_NOT_YET_DELINQUENT", 409)
        held = read_charge(scenario["charge"]["id"])
        assert held["status"] == "OPEN"
        assert held["delinquent_since"] is None

    def test_the_boundary_day_itself_opens_the_remedy(self, api):
        """PRD §3.6: "As a side effect of the first action against a charge, the
        charge moves `OPEN → DELINQUENT` and `delinquent_since` is stamped with the
        current clock date, and the member's `standing_status` is reconciled to
        `DELINQUENT`."
        PRD §3.6: "The new remedy starts `INITIATED`, records
        `initiated_by_user_id` from `X-User-ID`, copies `member_id` from the charge,
        and has `lien_amount_cents` and `payoff_amount_cents` at zero and
        `release_reason` null."

        Design: Corner/validations/delinquency_remedy_opens_only_on_the_thirtieth_grace_day
        """
        scenario = _past_due_charge(
            "Grace Day Road Association", "Grace Day Main", SINGLE_PARCEL_152
        )
        set_clock("2026-10-14T23:59:59Z")
        validate_error(
            api_client.create_delinquency_action(
                scenario["charge"]["id"], create_delinquency_action_payload("NOTICE"), TREASURER
            ),
            "ERR_CHARGE_NOT_YET_DELINQUENT",
            409,
        )

        set_clock("2026-10-15T00:00:00Z")
        action = validate_success(
            api_client.create_delinquency_action(
                scenario["charge"]["id"], create_delinquency_action_payload("NOTICE"), TREASURER
            ),
            expected_status=201,
        )

        assert action["status"] == "INITIATED"
        assert action["initiated_by_user_id"] == "bt-1"
        assert action["lien_amount_cents"] == 0
        assert action["release_reason"] is None

        charge = read_charge(scenario["charge"]["id"])
        assert charge["status"] == "DELINQUENT"
        assert charge["delinquent_since"] == "2026-10-15"
        assert charge["balance_cents"] == 1_600_000

        member = read_member(scenario["members"][0]["id"])
        assert member["standing_status"] == "DELINQUENT"
        assert member["access_status"] == "UNRESTRICTED", (
            "the notice is only INITIATED, so no access projection moves"
        )


UNRESOLVABLE_BID_ID = "22222222-2222-4222-8222-222222222222"


class TestPathIdentifiersResolveBeforeBodyIdentifiers:
    """Two unresolvable identifiers on one call, one reported error."""

    def test_the_unresolvable_path_id_wins(self, api):
        """PRD §2.10: "5. Path-templated identifiers resolve, left to right —
        otherwise the matching 404: `ERR_ASSOCIATION_NOT_FOUND`,
        `ERR_ROAD_SEGMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
        `ERR_PROPOSAL_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
        `ERR_BID_NOT_FOUND`, `ERR_DELINQUENCY_ACTION_NOT_FOUND`, or
        `ERR_CONNECTION_REQUEST_NOT_FOUND`."

        Design: Corner/validations/award_path_project_not_found_outranks_body_bid_not_found
        """
        segment = _cascade_order_segment()
        setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )

        response = api_client.award_project(
            NON_EXISTENT_UUID, {"bid_id": UNRESOLVABLE_BID_ID}, SECOND_COMMISSIONER
        )

        validate_error(response, "ERR_PROJECT_NOT_FOUND", 404)

    def test_once_the_path_resolves_the_body_key_surfaces(self, api):
        """PRD §2.10: "6. Foreign keys supplied in the body resolve —
        `association_id`, `road_segment_id`, `parcel_id`, `member_id`,
        `proposal_id`, and `bid_id` — otherwise `ERR_ASSOCIATION_NOT_FOUND`,
        `ERR_ROAD_SEGMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, or `ERR_BID_NOT_FOUND`
        respectively."
        PRD §3.7: "The new project starts in `BID_SOLICITATION` with
        `created_by_user_id` set from `X-User-ID`, a null `awarded_bid_id`,
        `awarded_amount_cents` and `reserve_draw_cents` at zero, and null
        `awarded_by_user_id`, `completed_at`, `actual_cost_cents`, and
        `cancellation_reason`."

        Design: Corner/validations/award_path_project_not_found_outranks_body_bid_not_found
        """
        segment = _cascade_order_segment()
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )

        response = api_client.award_project(
            project["id"], {"bid_id": UNRESOLVABLE_BID_ID}, SECOND_COMMISSIONER
        )

        validate_error(response, "ERR_BID_NOT_FOUND", 404)
        held = read_project(project["id"])
        assert held["status"] == "BID_SOLICITATION"
        assert held["awarded_bid_id"] is None
        assert held["awarded_by_user_id"] is None
        assert held["version"] == 1


def _cascade_order_segment():
    association = setup_association(
        name="Cascade Order Road Association", reserve_target_cents=1_000_000
    )
    return setup_road_segment(association["id"], name="Cascade Order Main", **MAIN_SEGMENT)


class TestTheCertifiedRollLockMasksParcelStatus:
    """A recall reveals the rule the lock had been hiding."""

    def _locked(self):
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Locked Roll Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Locked Roll Main", **MAIN_SEGMENT)

        parcel_a = setup_parcel(
            segment["id"],
            deed_book_page="DB153-P01",
            frontage_feet=240,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=4,
            covenant_recorded=True,
        )
        setup_member(parcel_a["id"], verified=True, deed_book_page="DB153-P01")

        parcel_b = setup_parcel(
            segment["id"],
            deed_book_page="DB153-P02",
            frontage_feet=100,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=2,
            covenant_recorded=True,
        )
        setup_member(parcel_b["id"], verified=True, deed_book_page="DB153-P02")
        split = subdivide(
            parcel_b["id"],
            [
                {"deed_book_page": "DB153-P02A", "frontage_feet": 60},
                {"deed_book_page": "DB153-P02B", "frontage_feet": 40},
            ],
        )

        roll = setup_assessment_roll(
            association["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
        )
        validate_success(api_client.certify_roll(roll["id"], CLERK))
        return {
            "roll": roll,
            "parcel_a": parcel_a,
            "subdivided_parcel": split["parent_parcel"],
        }

    def test_the_lock_answers_for_a_subdivided_parcel_and_an_active_one_alike(self, api):
        """PRD §2.10: "14. No roll of the parcel's association is `CERTIFIED`, for
        reclassification and subdivision — otherwise `ERR_CERTIFIED_ROLL_LOCKED`
        (409)."
        PRD §3.2: "Two guards protect the assessment record: the parcel must be
        `ACTIVE`, and no roll of the parcel's association may currently be
        `CERTIFIED` — a certified roll freezes parcel data until it is either
        recalled or levied, and an attempt made against a certified roll is rejected
        with `ERR_CERTIFIED_ROLL_LOCKED`."

        Design: Corner/validations/certified_roll_lock_outranks_parcel_status_then_recall_reveals_it
        """
        state = self._locked()

        on_subdivided = api_client.reclassify_parcel(
            state["subdivided_parcel"]["id"],
            reclassify_parcel_payload(state["subdivided_parcel"]["version"], trips_per_day=3),
            SECRETARY,
        )
        validate_error(on_subdivided, "ERR_CERTIFIED_ROLL_LOCKED", 409)

        on_active = api_client.reclassify_parcel(
            state["parcel_a"]["id"],
            reclassify_parcel_payload(
                state["parcel_a"]["version"], usage_class="COMMERCIAL", trips_per_day=10
            ),
            SECRETARY,
        )
        validate_error(on_active, "ERR_CERTIFIED_ROLL_LOCKED", 409)
        assert read_parcel(state["parcel_a"]["id"])["usage_class"] == "RESIDENTIAL_YEAR_ROUND"

    def test_after_the_recall_the_parcel_status_rule_answers_instead(self, api):
        """PRD §2.10: "15. The parcel is `ACTIVE` for reclassification and
        subdivision, and `PENDING_CONNECTION` for connection filing and connection
        decisions — otherwise `ERR_PARCEL_NOT_ACTIVE` (409)."
        PRD §3.4: "A recall, available to the `AssessmentClerk` on a `CERTIFIED`
        roll and taking a `recall_reason`, moves the roll `CERTIFIED → DRAFT`"

        Design: Corner/validations/certified_roll_lock_outranks_parcel_status_then_recall_reveals_it
        """
        state = self._locked()

        recalled = validate_success(
            api_client.recall_roll(state["roll"]["id"], recall_payload(), CLERK)
        )
        assert recalled["status"] == "DRAFT"
        assert recalled["recall_count"] == 1

        response = api_client.reclassify_parcel(
            state["subdivided_parcel"]["id"],
            reclassify_parcel_payload(state["subdivided_parcel"]["version"], trips_per_day=3),
            SECRETARY,
        )

        validate_error(response, "ERR_PARCEL_NOT_ACTIVE", 409)

    def test_the_recall_frees_the_active_parcel_to_be_reclassified(self, api):
        """PRD §3.2: "Reclassifying a parcel is an `AssociationSecretary` operation
        that takes `expected_parcel_version` plus any subset of `frontage_feet`,
        `usage_class`, and `trips_per_day`. Only the supplied fields are
        overwritten, and both share units are recomputed afterwards."

        Design: Corner/validations/certified_roll_lock_outranks_parcel_status_then_recall_reveals_it
        """
        state = self._locked()
        validate_success(api_client.recall_roll(state["roll"]["id"], recall_payload(), CLERK))

        reclassified = validate_success(
            api_client.reclassify_parcel(
                state["parcel_a"]["id"],
                reclassify_parcel_payload(
                    state["parcel_a"]["version"], usage_class="COMMERCIAL", trips_per_day=10
                ),
                SECRETARY,
            )
        )

        assert reclassified["usage_class"] == "COMMERCIAL"
        assert reclassified["trips_per_day"] == 10
        assert reclassified["frontage_share_units"] == pytest.approx(420.0, abs=0.0001)
        assert reclassified["trip_share_units"] == pytest.approx(298.0, abs=0.0001)
        assert reclassified["version"] == 2
