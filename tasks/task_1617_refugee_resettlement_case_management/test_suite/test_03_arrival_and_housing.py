"""Arrival-day cascade and housing preparation (PRD §3.2, §3.3): the
housing-readiness gate on arrival, furnishing rules, the capacity boundary,
and the cross-entity arrive cascade onto the setup and unit.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    date_part, assert_housing_setup, make_case,
    make_housing_unit, make_housing_setup, furnish_item, mark_setup_ready,
    arrive_case, get_case, get_housing_unit, set_clock, setup_case_with_housing,
    setup_arrived_case, REQUIRED_FURNISHINGS,
)
from test_helpers.fixtures import CM, HC


class TestArriveBlockedUntilHousingReady:
    def test_arrive_with_preparing_setup_rejected(self, api):
        """PRD §3.3: "the case must have a housing setup in `READY` status: a
        family cannot be recorded as arrived when no ready home exists, and
        the attempt is rejected with `ERR_HOUSING_NOT_READY` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/arrive_blocked_until_housing_ready
        """
        ctx = setup_case_with_housing(case_number="CASE-XD1", household_size=1,
                                      furnish_count=5, ready=False, arrive=False)
        resp = api.arrive_case(ctx["case"]["id"],
                               {"actual_arrival_date": "2026-08-10"}, CM)
        validate_error(resp, ApiErrorId.ERR_HOUSING_NOT_READY)

    def test_arrive_succeeds_after_sixth_item_and_ready(self, api):
        """PRD §3.3: "the case must have a housing setup in `READY` status: a
        family cannot be recorded as arrived when no ready home exists, and
        the attempt is rejected with `ERR_HOUSING_NOT_READY` (HTTP 409)."
        PRD §3.2: "Once `furnishing_items_completed` contains every member of
        the required set, the coordinator may mark the setup ready, moving it
        `PREPARING → READY`".

        Design: Difficulty/cross_entity_state_dependency/arrive_blocked_until_housing_ready
        """
        ctx = setup_case_with_housing(case_number="CASE-XD1B", household_size=1,
                                      furnish_count=5, ready=False, arrive=False)
        furnish_item(ctx["setup"]["id"], REQUIRED_FURNISHINGS[5])
        setup = mark_setup_ready(ctx["setup"]["id"])
        assert setup["status"] == "READY"
        case = arrive_case(ctx["case"]["id"], actual_arrival_date="2026-08-10")
        assert case["status"] == "ARRIVED"
        assert date_part(case["actual_arrival_date"]) == "2026-08-10"


class TestArrivalCascade:
    def test_arrive_occupies_setup_and_recomputes_unit(self, api):
        """PRD §3.3: "The `READY` housing setup for the case transitions
        `READY → OCCUPIED`, and because that setup became `OCCUPIED`, its
        unit's derived status recomputes to `OCCUPIED` while today is inside
        the occupancy window."

        Design: Difficulty/cross_entity_state_dependency/arrive_blocked_until_housing_ready
        """
        ctx = setup_arrived_case(case_number="CASE-AR1", household_size=1,
                                 actual_arrival_date="2026-08-10")
        # PRD §3.3 conditions the unit reading OCCUPIED on "today is inside
        # the occupancy window"; move the logical clock to the arrival date
        # (the window is [2026-08-10, 2027-02-10)).
        set_clock("2026-08-10T00:00:00Z")
        setups = get_success_data(
            api.list_case_housing_setups(ctx["case"]["id"], HC))
        assert setups[0]["status"] == "OCCUPIED"
        unit = get_housing_unit(ctx["unit"]["id"], headers=HC)
        assert unit["status"] == "OCCUPIED"

    def test_arrive_stamps_pickup_and_computes_member_ages(self, api):
        """PRD §3.3: "The case itself moves `PRE_ARRIVAL → ARRIVED`;
        `actual_arrival_date` is stored from the request and
        `airport_pickup_completed` becomes true, since airport pickup is
        recorded as part of arrival. Every household member's
        `age_at_arrival` is computed as age in whole years on the
        `actual_arrival_date`, and `school_age_at_arrival` becomes true
        exactly when that age is at least 5 and at most 17."

        Design: Difficulty/cross_entity_state_dependency/arrive_blocked_until_housing_ready
        """
        ctx = setup_arrived_case(
            case_number="CASE-AR2", household_size=2,
            members=[{"full_name": "Adult", "date_of_birth": "1990-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True},
                     {"full_name": "Child", "date_of_birth": "2016-05-20",
                      "relationship": "CHILD", "work_eligible": False}],
            actual_arrival_date="2026-08-10")
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["status"] == "ARRIVED"
        assert case["airport_pickup_completed"] is True
        members = get_success_data(api.list_members(case["id"], CM))
        by_name = {m["full_name"]: m for m in members}
        assert by_name["Adult"]["age_at_arrival"] == 36
        assert by_name["Adult"]["school_age_at_arrival"] is False
        assert by_name["Child"]["age_at_arrival"] == 10
        assert by_name["Child"]["school_age_at_arrival"] is True


class TestFurnishingRules:
    def test_duplicate_furnishing_item_rejected(self, api):
        """PRD §3.2: "Naming an item that is already in that list is rejected
        with `ERR_ITEM_ALREADY_FURNISHED` (HTTP 409)".

        Design: Corner/validations/furnishing_duplicate_item_returns_already_furnished
        """
        case = make_case(case_number="CASE-V12", household_size=1)
        unit = make_housing_unit(address="550 Elmwood St", bedrooms=1)
        setup = make_housing_setup(case["id"], unit["id"])
        furnish_item(setup["id"], "BED")
        resp = api.furnish_setup(setup["id"], {"item": "BED"}, HC)
        validate_error(resp, ApiErrorId.ERR_ITEM_ALREADY_FURNISHED)

    def test_ready_with_five_of_six_items_rejected(self, api):
        """PRD §3.2: "Once `furnishing_items_completed` contains every member
        of the required set, the coordinator may mark the setup ready, moving
        it `PREPARING → READY`; if any required item is still missing, the
        ready call fails with `ERR_FURNISHING_INCOMPLETE` (HTTP 409)."

        Design: Corner/validations/ready_with_incomplete_furnishing_returns_incomplete
        """
        ctx = setup_case_with_housing(case_number="CASE-V13", household_size=1,
                                      furnish_count=5, ready=False, arrive=False)
        resp = api.ready_setup(ctx["setup"]["id"], HC)
        validate_error(resp, ApiErrorId.ERR_FURNISHING_INCOMPLETE)

    def test_ready_with_all_six_items_succeeds(self, api):
        """PRD §3.2: "Once `furnishing_items_completed` contains every member
        of the required set, the coordinator may mark the setup ready, moving
        it `PREPARING → READY`".

        Design: Corner/validations/ready_with_incomplete_furnishing_returns_incomplete
        """
        ctx = setup_case_with_housing(case_number="CASE-V13B", household_size=1,
                                      furnish_count=6, ready=False, arrive=False)
        setup = mark_setup_ready(ctx["setup"]["id"])
        assert setup["status"] == "READY"
        assert sorted(setup["furnishing_items_completed"]) == sorted(REQUIRED_FURNISHINGS)


class TestHousingCapacityBoundary:
    def test_exact_fit_size_four_two_bedrooms_allowed(self, api):
        """PRD §3.2: "The capacity rule prevents overcrowding: the unit's
        `bedrooms` must be at least the household size divided by two and
        rounded up to a whole number — a household of five therefore needs at
        least three bedrooms — and a unit that is too small is rejected with
        `ERR_HOUSING_CAPACITY_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/housing_capacity_exact_fit
        """
        case = make_case(case_number="CASE-BP2A", household_size=4)
        unit = make_housing_unit(address="150 Pine Ct", bedrooms=2)
        resp = api.create_housing_setup(
            {"case_id": case["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2026-08-10", "occupancy_end": "2027-02-10"}, HC)
        setup = validate_success(resp, 201)
        assert setup["status"] == "PREPARING"
        assert_housing_setup(setup)

    def test_one_bedroom_short_size_five_rejected(self, api):
        """PRD §3.2: "a household of five therefore needs at least three
        bedrooms — and a unit that is too small is rejected with
        `ERR_HOUSING_CAPACITY_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/housing_capacity_exact_fit
        """
        case = make_case(case_number="CASE-BP2B", household_size=5)
        unit = make_housing_unit(address="160 Pine Ct", bedrooms=2)
        resp = api.create_housing_setup(
            {"case_id": case["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2026-08-10", "occupancy_end": "2027-02-10"}, HC)
        validate_error(resp, ApiErrorId.ERR_HOUSING_CAPACITY_INSUFFICIENT)


class TestSingleSetupPerCase:
    def test_second_setup_for_same_case_rejected(self, api):
        """PRD §3.2: "A case may also have at most one non-terminal setup at
        a time — a second setup for a case that already has one in
        `PREPARING`, `READY`, or `OCCUPIED` is rejected with
        `ERR_SETUP_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/validations/setup_already_exists_for_case
        """
        case = make_case(case_number="CASE-V16", household_size=1)
        unit1 = make_housing_unit(address="590 Firwood St", bedrooms=1)
        unit2 = make_housing_unit(address="600 Firwood St", bedrooms=1)
        make_housing_setup(case["id"], unit1["id"])
        resp = api.create_housing_setup(
            {"case_id": case["id"], "housing_unit_id": unit2["id"],
             "occupancy_start": "2026-08-10", "occupancy_end": "2027-02-10"}, HC)
        validate_error(resp, ApiErrorId.ERR_SETUP_ALREADY_EXISTS)


class TestHousingWindowValidation:
    def test_inverted_occupancy_window_rejected(self, api):
        """PRD §3.2: "Creating one takes the `case_id` (the case must still
        be `PRE_ARRIVAL`, else `ERR_INVALID_STATE`), the `housing_unit_id`,
        and the half-open window `occupancy_start` (inclusive) through
        `occupancy_end` (exclusive); an end that is not strictly after the
        start fails schema validation with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/housing_inverted_window_returns_invalid_request
        """
        case = make_case(case_number="CASE-V5", household_size=1)
        unit = make_housing_unit(address="480 Spruce Ct", bedrooms=1)
        resp = api.create_housing_setup(
            {"case_id": case["id"], "housing_unit_id": unit["id"],
             "occupancy_start": "2026-08-10", "occupancy_end": "2026-08-10"}, HC)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
