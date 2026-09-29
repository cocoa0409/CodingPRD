"""Temporary lodging: its authorisation gate, its calendar and its money."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

HAZARD_CLOCK = "2026-09-20T10:00:00Z"
SEPTEMBER = "2026-09"
LODGING_START_DATE = "2026-09-20"
LODGING_END_DATE = "2026-09-30"

# The hazard credit the assessment already posted: eleven inclusive days of
# September at 7172 a day.
ABATEMENT_CENTS = 78892
BALANCE_AFTER_ABATEMENT_CENTS = 139258

# min(21000, 25000) room rate plus four meal allowances of 6900.
PER_NIGHT_AUTHORIZED_CENTS = 48600
TEN_NIGHTS = 10
TEN_NIGHT_AUTHORIZED_CENTS = 486000
TEN_NIGHT_RENT_ABATEMENT_CENTS = 71720
FORBIDDEN_ROUNDING_ORDER_CENTS = 71721
OPENING_BALANCE_CENTS = const.TEST_DEFAULTS["OPENING_BALANCE_CENTS"]
ACCOUNT_AFTER_TEN_NIGHTS_CENTS = 4514000


def _displaced_household(api):
    """A charged tenancy displaced by a severe mold finding on 2026-09-20."""
    state = fx.setup_charged_lease(api)
    return fx.setup_displaced_household(
        api,
        occupied_state=state,
        hazard_clock=HAZARD_CLOCK,
        report_overrides={
            "lease_id": state["lease"]["id"],
            "reported_symptoms": "Black growth spreading across master bedroom wall",
        },
        assess_overrides={"child_under_six_present": True},
    )


def _lodged_with_a_capital_account(api, **lodging_overrides):
    """A displaced family booked into ten nights of lodging, plus the account.

    The contract rate of 21000 a night sits under the nightly cap, so the cap
    itself is not what shapes this figure — the meal allowance is.
    """
    state = _displaced_household(api)
    fx.setup_account(api, occupied_state=state)
    state["lodging"] = fx.authorize_lodging(
        api, state["hazard_case"]["id"], state["lease"]["id"], **lodging_overrides
    )
    asserts.assert_displacement_lodging(state["lodging"])
    assert state["lodging"]["status"] == "AUTHORIZED"
    assert state["lodging"]["nights_displaced"] == 0
    return state


def test_ten_nights_authorise_the_capped_room_rate_plus_the_meal_allowance(api):
    """The room rate is capped first and the per-occupant meals are added after.

    PRD: "`per_night_authorized_cents` is the smaller of `nightly_rate_cents` and the nightly room-rate cap of 25000 cents — two hundred and fifty dollars a night — plus a per-occupant meal allowance of 6900 cents for each authorised occupant; the cap applies to the room rate only, and the meal allowance is added after the cap and is itself uncapped."

    Design: Difficulty/combinatorial_formula/displacement_abatement_round_then_multiply
    """
    state = _lodged_with_a_capital_account(api)

    closed = fx.close_lodging(api, state["lodging"]["id"], LODGING_END_DATE)

    asserts.assert_displacement_lodging(closed)
    assert closed["status"] == "CLOSED"
    assert closed["actual_end_date"] == LODGING_END_DATE
    assert closed["nights_displaced"] == TEN_NIGHTS
    assert closed["per_night_authorized_cents"] == PER_NIGHT_AUTHORIZED_CENTS
    assert closed["lodging_authorized_cents"] == TEN_NIGHT_AUTHORIZED_CENTS


def test_rent_abatement_multiplies_the_once_rounded_daily_rent(api):
    """Round-then-multiply and multiply-then-round differ by a cent here.

    PRD: "For a lease whose `net_rent_cents` is 218150, giving a `daily_rent_cents` of 7172, ten nights yield exactly 71720; the unrounded-then-rounded route would yield 71721, which is wrong."

    Design: Difficulty/combinatorial_formula/displacement_abatement_round_then_multiply
    """
    state = _lodged_with_a_capital_account(api)
    assert state["lease"]["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert state["lease"]["daily_rent_cents"] == const.BASE_DAILY_RENT_CENTS

    closed = fx.close_lodging(api, state["lodging"]["id"], LODGING_END_DATE)

    assert closed["rent_abatement_cents"] == TEN_NIGHT_RENT_ABATEMENT_CENTS
    assert closed["rent_abatement_cents"] != FORBIDDEN_ROUNDING_ORDER_CENTS
    assert (
        closed["rent_abatement_cents"]
        == const.BASE_DAILY_RENT_CENTS * closed["nights_displaced"]
    )


def test_closing_the_lodging_spends_capital_but_posts_no_ledger_row(api):
    """The lodging is paid for out of the project's account, not the resident's.

    PRD: "The reinvestment account for that installation and the calendar year of the `actual_end_date` has its `expenditures_cents` raised by the closed lodging's `lodging_authorized_cents` and its `closing_balance_cents` recomputed, with its `version` incremented by 1."

    Design: Difficulty/combinatorial_formula/displacement_abatement_round_then_multiply
    """
    state = _lodged_with_a_capital_account(api)
    account_before = state["account"]
    assert account_before["expenditures_cents"] == 0

    fx.close_lodging(api, state["lodging"]["id"], LODGING_END_DATE)

    account = fx.read_account(api, account_before["id"])
    asserts.assert_reinvestment_account(account)
    assert account["expenditures_cents"] == TEN_NIGHT_AUTHORIZED_CENTS
    assert account["closing_balance_cents"] == ACCOUNT_AFTER_TEN_NIGHTS_CENTS
    assert account["version"] == account_before["version"] + 1
    # The resident's ledger is untouched: the credit was posted at suspension.
    lease = fx.read_lease(api, state["lease"]["id"])
    ledger = fx.read_ledger(api, lease["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "ABATEMENT"]
    assert lease["allotment_balance_cents"] == BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == ABATEMENT_CENTS


def test_closing_on_the_start_date_authorises_no_nights(api):
    """A zero-width stay is zero nights, not one, and still prices a night.

    PRD: "`nights_displaced` is the number of whole days from `start_date` inclusive to `actual_end_date` exclusive, so a lodging closed on its own start date yields 0 nights."

    Design: Difficulty/boundary_precision_check/lodging_close_on_start_date_yields_zero_nights
    """
    state = _lodged_with_a_capital_account(api)

    closed = fx.close_lodging(api, state["lodging"]["id"], LODGING_START_DATE)

    asserts.assert_displacement_lodging(closed)
    assert closed["status"] == "CLOSED"
    assert closed["actual_end_date"] == LODGING_START_DATE
    assert closed["nights_displaced"] == 0
    # The per-night figure is stamped in full even though no night was authorised.
    assert closed["per_night_authorized_cents"] == PER_NIGHT_AUTHORIZED_CENTS
    assert closed["rent_abatement_cents"] == 0


def test_the_zero_night_closure_moves_no_money_at_all(api):
    """Nothing is authorised, so nothing is spent and nothing is credited.

    PRD: "`lodging_authorized_cents` is `per_night_authorized_cents` multiplied by `nights_displaced`, so a zero-night lodging authorises 0 cents."

    Design: Difficulty/boundary_precision_check/lodging_close_on_start_date_yields_zero_nights
    """
    state = _lodged_with_a_capital_account(api)

    closed = fx.close_lodging(api, state["lodging"]["id"], LODGING_START_DATE)

    assert closed["lodging_authorized_cents"] == 0
    account = fx.read_account(api, state["account"]["id"])
    assert account["expenditures_cents"] == 0
    assert account["closing_balance_cents"] == OPENING_BALANCE_CENTS
    lease = fx.read_lease(api, state["lease"]["id"])
    ledger = fx.read_ledger(api, lease["id"])
    assert len(ledger) == 2
    assert lease["allotment_balance_cents"] == BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == ABATEMENT_CENTS
    asserts.assert_ledger_conservation(ledger, lease)


UNASSESSED_LODGING_START = "2026-09-21"
UNASSESSED_LODGING_END = "2026-09-28"
CONTRACT_RATE_CENTS = 22000
AUTHORIZED_OCCUPANTS = 4


def _lodgings_on_the_case(api, hazard_case_id):
    return validate_success(
        api.list_displacement_lodgings(
            TEST_USERS["property_manager_headers"],
            params={"hazard_case_id": hazard_case_id},
        )
    )


def _charged_tenancy_with_an_unassessed_case(api):
    """A charged tenancy and a mold case nobody has graded yet."""
    state = fx.setup_charged_lease(api)
    return fx.setup_reported_hazard(
        api,
        occupied_state=state,
        hazard_clock=HAZARD_CLOCK,
        lease_id=state["lease"]["id"],
        reported_symptoms="Musty odour and staining behind the master bedroom baseboard",
    )


def _lodging_request(api, state):
    """The same flawless lodging payload, sent twice around the assessment."""
    return api.create_displacement_lodging(
        f.create_displacement_lodging_payload(
            state["hazard_case"]["id"],
            state["lease"]["id"],
            start_date=UNASSESSED_LODGING_START,
            end_date=UNASSESSED_LODGING_END,
            nightly_rate_cents=CONTRACT_RATE_CENTS,
            occupants_count=AUTHORIZED_OCCUPANTS,
        ),
        TEST_USERS["property_manager_headers"],
    )


def test_lodging_on_a_case_nobody_has_assessed_is_refused(api):
    """A reported concern is not yet a finding, so it authorises no lodging.

    PRD: "Temporary lodging is authorised by a `PropertyManager` or an `EnvironmentalSpecialist` once the case has been assessed — a case still in `REPORTED` is refused with `ERR_HAZARD_NOT_ASSESSED`."

    Design: Difficulty/cross_entity_state_dependency/lodging_authorization_gated_on_hazard_case_assessment
    """
    state = _charged_tenancy_with_an_unassessed_case(api)
    assert state["hazard_case"]["status"] == "REPORTED"
    assert state["hazard_case"]["assessment_severity"] is None

    response = _lodging_request(api, state)

    validate_error(response, ApiErrorId.ERR_HAZARD_NOT_ASSESSED, 409)
    assert _lodgings_on_the_case(api, state["hazard_case"]["id"]) == []
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_status"] == "ACTIVE"
    assert lease["allotment_balance_cents"] == const.BASE_NET_RENT_CENTS


def test_the_identical_lodging_request_succeeds_once_the_case_is_graded(api):
    """Only the other entity moved, and that is what unblocks the request.

    PRD: "A new lodging is created in `status` `AUTHORIZED` with `actual_end_date` null and `nights_displaced`, `per_night_authorized_cents`, `lodging_authorized_cents` and `rent_abatement_cents` all 0 until it closes."

    Design: Difficulty/cross_entity_state_dependency/lodging_authorization_gated_on_hazard_case_assessment
    """
    state = _charged_tenancy_with_an_unassessed_case(api)
    validate_error(
        _lodging_request(api, state), ApiErrorId.ERR_HAZARD_NOT_ASSESSED, 409
    )
    assessed = fx.assess_hazard(
        api,
        state["hazard_case"]["id"],
        affected_area_sqft=45,
        child_under_six_present=True,
    )
    assert assessed["status"] == "DISPLACEMENT_ACTIVE"

    lodging = validate_success(_lodging_request(api, state), 201)

    asserts.assert_displacement_lodging(lodging)
    assert lodging["status"] == "AUTHORIZED"
    assert lodging["hazard_case_id"] == state["hazard_case"]["id"]
    assert lodging["lease_id"] == state["lease"]["id"]
    assert lodging["actual_end_date"] is None
    assert lodging["nights_displaced"] == 0
    assert lodging["per_night_authorized_cents"] == 0
    assert lodging["lodging_authorized_cents"] == 0
    assert lodging["rent_abatement_cents"] == 0
    assert len(_lodgings_on_the_case(api, state["hazard_case"]["id"])) == 1


RIGHT_ADJACENT = ("2026-09-30", "2026-10-05")
LEFT_ADJACENT = ("2026-09-19", "2026-09-20")
STRADDLING = ("2026-09-29", "2026-10-02")
CONTAINED = ("2026-09-25", "2026-09-26")
INSIDE_THE_CLOSED_INTERVAL = ("2026-09-22", "2026-09-24")


def _lodging_calendar(api):
    """A displaced family whose lease already holds [2026-09-20, 2026-09-30)."""
    state = _displaced_household(api)
    state["lodging"] = fx.authorize_lodging(
        api,
        state["hazard_case"]["id"],
        state["lease"]["id"],
        start_date=LODGING_START_DATE,
        end_date=LODGING_END_DATE,
        nightly_rate_cents=CONTRACT_RATE_CENTS,
        occupants_count=AUTHORIZED_OCCUPANTS,
    )
    return state


def _book(api, state, interval):
    start_date, end_date = interval
    return api.create_displacement_lodging(
        f.create_displacement_lodging_payload(
            state["hazard_case"]["id"],
            state["lease"]["id"],
            start_date=start_date,
            end_date=end_date,
            nightly_rate_cents=CONTRACT_RATE_CENTS,
            occupants_count=AUTHORIZED_OCCUPANTS,
        ),
        TEST_USERS["property_manager_headers"],
    )


def _lodgings_on_the_lease(api, lease_id):
    return validate_success(
        api.list_displacement_lodgings(
            TEST_USERS["property_manager_headers"], params={"lease_id": lease_id}
        )
    )


def test_a_lodging_may_begin_on_the_date_another_ended(api):
    """The right edge touches without overlapping, so the booking stands.

    PRD: "Adjacency is explicitly permitted — a new lodging may begin on the exact date a previous one ended."

    Design: Difficulty/resource_temporal_overlap/lodging_half_open_intervals_allow_adjacency_reject_containment
    """
    state = _lodging_calendar(api)

    right_adjacent = validate_success(_book(api, state, RIGHT_ADJACENT), 201)

    asserts.assert_displacement_lodging(right_adjacent)
    assert right_adjacent["status"] == "AUTHORIZED"
    assert right_adjacent["start_date"] == LODGING_END_DATE
    assert right_adjacent["id"] != state["lodging"]["id"]
    assert len(_lodgings_on_the_lease(api, state["lease"]["id"])) == 2


def test_a_lodging_may_end_on_the_date_another_began(api):
    """The left edge is excluded by the half-open rule, so it touches too.

    PRD: "The interval is **half-open**: a night is counted for each date from `start_date` inclusive up to `end_date` exclusive."

    Design: Difficulty/resource_temporal_overlap/lodging_half_open_intervals_allow_adjacency_reject_containment
    """
    state = _lodging_calendar(api)

    left_adjacent = validate_success(_book(api, state, LEFT_ADJACENT), 201)

    assert left_adjacent["status"] == "AUTHORIZED"
    assert left_adjacent["end_date"] == LODGING_START_DATE
    assert left_adjacent["nights_displaced"] == 0
    assert len(_lodgings_on_the_lease(api, state["lease"]["id"])) == 2


def test_straddling_and_fully_contained_intervals_are_both_refused(api):
    """Sharing even one night with a booked interval is an overlap.

    PRD: "Rung 40 requires the requested lodging interval, which runs from `start_date` inclusive to `end_date` exclusive, not to overlap any `AUTHORIZED` or `CLOSED` lodging interval already on the same lease; adjacency is explicitly allowed, so a new lodging may begin on the same date a previous one ended."

    Design: Difficulty/resource_temporal_overlap/lodging_half_open_intervals_allow_adjacency_reject_containment
    """
    state = _lodging_calendar(api)
    validate_success(_book(api, state, RIGHT_ADJACENT), 201)
    validate_success(_book(api, state, LEFT_ADJACENT), 201)

    straddling = _book(api, state, STRADDLING)
    contained = _book(api, state, CONTAINED)

    validate_error(straddling, ApiErrorId.ERR_LODGING_INTERVAL_OVERLAP, 409)
    validate_error(contained, ApiErrorId.ERR_LODGING_INTERVAL_OVERLAP, 409)
    rows = _lodgings_on_the_lease(api, state["lease"]["id"])
    assert len(rows) == 3
    for row in rows:
        assert row["status"] == "AUTHORIZED"
        assert row["nights_displaced"] == 0
        assert row["per_night_authorized_cents"] == 0
        assert row["lodging_authorized_cents"] == 0
        assert row["rent_abatement_cents"] == 0


def test_a_closed_interval_still_occupies_the_calendar(api):
    """Closing a stay does not free the nights it covered for a second booking.

    PRD: "Two constraints apply beyond the shared referential check that lease and case agree: the occupants may not exceed two plus the sponsor's full-time-custody dependent count, or the request fails with `ERR_OCCUPANTS_EXCEED_AUTHORIZED`; and the requested interval may not overlap any `AUTHORIZED` or `CLOSED` lodging interval already on the same lease, or the request fails with `ERR_LODGING_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lodging_half_open_intervals_allow_adjacency_reject_containment
    """
    state = _lodging_calendar(api)
    closed = fx.close_lodging(api, state["lodging"]["id"], LODGING_END_DATE)
    assert closed["status"] == "CLOSED"

    response = _book(api, state, INSIDE_THE_CLOSED_INTERVAL)

    validate_error(response, ApiErrorId.ERR_LODGING_INTERVAL_OVERLAP, 409)
    assert len(_lodgings_on_the_lease(api, state["lease"]["id"])) == 1


MISMATCH_START = "2026-09-21"
MISMATCH_END = "2026-09-26"
EXCESSIVE_OCCUPANTS = 9
AUTHORIZED_CEILING = 5


def _case_on_the_second_unit(api):
    """Two occupied tenancies, with the severe finding on the second unit only."""
    state = fx.setup_two_occupied_tenancies(api)
    fx.set_clock(api, HAZARD_CLOCK)
    state["hazard_case"] = fx.assess_hazard(
        api,
        fx.report_hazard(
            api,
            state["units"][1]["id"],
            lease_id=state["leases"][1]["id"],
            hazard_type="MOLD",
            reported_symptoms="Visible growth behind the kitchen cabinetry",
        )["id"],
        affected_area_sqft=45,
        child_under_six_present=True,
    )
    assert state["hazard_case"]["status"] == "DISPLACEMENT_ACTIVE"
    return state


def _lodging_for(api, state, lease_id):
    return api.create_displacement_lodging(
        f.create_displacement_lodging_payload(
            state["hazard_case"]["id"],
            lease_id,
            start_date=MISMATCH_START,
            end_date=MISMATCH_END,
            nightly_rate_cents=CONTRACT_RATE_CENTS,
            occupants_count=EXCESSIVE_OCCUPANTS,
        ),
        TEST_USERS["property_manager_headers"],
    )


def test_the_wrong_lease_is_reported_before_the_occupant_ceiling(api):
    """Naming another family's lease answers ahead of an impossible headcount.

    PRD: "Rung 32 requires a supplied `lease_id` and `housing_unit_id` to agree, meaning the lease must be that unit's current non-`TERMINATED` lease; it guards work-order submission, hazard-case reporting and lodging authorisation, failing with `ERR_LEASE_UNIT_MISMATCH` (422)."

    Design: Difficulty/priority_pair_validation_conflict/lodging_lease_unit_mismatch_outranks_occupant_cap
    """
    state = _case_on_the_second_unit(api)

    response = _lodging_for(api, state, state["leases"][0]["id"])

    validate_error(response, ApiErrorId.ERR_LEASE_UNIT_MISMATCH, 422)
    assert _lodgings_on_the_case(api, state["hazard_case"]["id"]) == []
    assert (
        fx.read_lease(api, state["leases"][0]["id"])["allotment_status"] == "ACTIVE"
    )
    assert (
        fx.read_lease(api, state["leases"][1]["id"])["allotment_status"] == "SUSPENDED"
    )


def test_curing_the_mismatch_exposes_the_armed_occupant_ceiling(api):
    """The headcount rule was live all along; it was merely outranked.

    PRD: "Rung 39 requires the lodging's `occupants_count` not to exceed two plus the sponsor's full-time-custody dependent count; it guards lodging authorisation, failing with `ERR_OCCUPANTS_EXCEED_AUTHORIZED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/lodging_lease_unit_mismatch_outranks_occupant_cap
    """
    state = _case_on_the_second_unit(api)
    validate_error(
        _lodging_for(api, state, state["leases"][0]["id"]),
        ApiErrorId.ERR_LEASE_UNIT_MISMATCH,
        422,
    )
    assert state["sponsors"][1]["dependent_count"] == AUTHORIZED_CEILING - 2

    response = _lodging_for(api, state, state["leases"][1]["id"])

    validate_error(response, ApiErrorId.ERR_OCCUPANTS_EXCEED_AUTHORIZED, 422)
    assert _lodgings_on_the_case(api, state["hazard_case"]["id"]) == []
