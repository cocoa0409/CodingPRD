"""Gate entry/exit: bather-capacity boundary, derived counter reconciliation,
enter/exit conservation, date validity, and double-entry rejection
(PRD §3.2, §3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    assert_admission, assert_facility,
    create_admission_payload,
    make_facility, make_season, make_pass_holder, make_admission,
    make_lifeguard, make_chemistry_log, make_rental, approve_rental,
    set_clock, get_facility, make_passholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def _setup_with_holders(n_holders, clock_date="2026-07-05",
                        facility_overrides=None):
    facility = make_facility(**(facility_overrides or {}))
    make_season(facility["id"])
    holders = [make_pass_holder() for _ in range(n_holders)]
    set_clock(f"{clock_date}T10:00:00Z")
    return facility, holders


def _issue(facility_id, holder_id, date="2026-07-05"):
    return make_admission(facility_id, holder_id, f"{date}T00:00:00Z")


def test_bather_capacity_final_seat_enter_succeeds(api):
    """PRD §3.2: "Entry at the gate transitions it to `ENTERED` and stamps
    `entered_at` with the current clock; entry requires the facility to be
    `OPEN` or `RESTRICTED` (rejecting with `ERR_FACILITY_CLOSED`), the patron
    not to be currently banned (`ERR_HOLDER_BANNED`), the `admission_date` to
    equal today, and the facility's `current_bather_count` to be strictly
    below `max_bather_capacity` (`ERR_FACILITY_AT_CAPACITY` when the cap has
    been reached)."

    Design: Difficulty/boundary_precision_check/bather_capacity_at_max_boundary
    """
    facility, holders = _setup_with_holders(
        2, facility_overrides=dict(max_bather_capacity=2, lap_lane_count=0)
    )
    a1 = _issue(facility["id"], holders[0]["id"])
    a2 = _issue(facility["id"], holders[1]["id"])
    d1 = validate_success(api.enter_admission(a1["id"], GATE))
    d2 = validate_success(api.enter_admission(a2["id"], GATE))
    assert d1["status"] == "ENTERED"
    assert d2["status"] == "ENTERED"
    facility_after = get_facility(facility["id"])
    assert facility_after["current_bather_count"] == 2


def test_bather_capacity_enter_beyond_max_rejected(api):
    """PRD §3.2: "Entry at the gate transitions it to `ENTERED` and stamps
    `entered_at` with the current clock; entry requires the facility to be
    `OPEN` or `RESTRICTED` (rejecting with `ERR_FACILITY_CLOSED`), the patron
    not to be currently banned (`ERR_HOLDER_BANNED`), the `admission_date` to
    equal today, and the facility's `current_bather_count` to be strictly
    below `max_bather_capacity` (`ERR_FACILITY_AT_CAPACITY` when the cap has
    been reached)."

    Design: Difficulty/boundary_precision_check/bather_capacity_at_max_boundary
    """
    facility, holders = _setup_with_holders(
        3, facility_overrides=dict(max_bather_capacity=2, lap_lane_count=0)
    )
    admissions = [_issue(facility["id"], h["id"]) for h in holders]
    get_success_data(api.enter_admission(admissions[0]["id"], GATE))
    get_success_data(api.enter_admission(admissions[1]["id"], GATE))
    resp = api.enter_admission(admissions[2]["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_FACILITY_AT_CAPACITY)
    third = validate_success(api.get_admission(admissions[2]["id"], GATE))
    assert third["status"] == "ISSUED"
    assert get_facility(facility["id"])["current_bather_count"] == 2


def test_bather_count_enter_exit_invariant(api):
    """PRD §3.2: "A successful entry increments the facility's
    `current_bather_count` by 1 and recomputes `required_lifeguard_count`.
    Exit transitions the admission from `ENTERED` to `EXITED`, stamps
    `exited_at`, decrements `current_bather_count` by 1, and recomputes the
    lifeguard requirement."

    Design: Difficulty/compensating_invariant/bather_count_enter_exit_invariant
    """
    facility, holders = _setup_with_holders(
        1, clock_date="2026-07-18",
        facility_overrides=dict(max_bather_capacity=100, lap_lane_count=2),
    )
    admission = _issue(facility["id"], holders[0]["id"], date="2026-07-18")
    count_before = get_facility(facility["id"])["current_bather_count"]
    assert count_before == 0
    entered = validate_success(api.enter_admission(admission["id"], GATE))
    assert entered["status"] == "ENTERED"
    assert entered["entered_at"] is not None
    assert get_facility(facility["id"])["current_bather_count"] == 1
    exited = validate_success(api.exit_admission(admission["id"], GATE))
    assert exited["status"] == "EXITED"
    assert exited["exited_at"] is not None
    facility_after = get_facility(facility["id"])
    assert facility_after["current_bather_count"] == 0, (
        "Enter/exit pair must leave current_bather_count unchanged"
    )
    assert facility_after["required_lifeguard_count"] == 0


def test_bather_count_invariant_interleaved_pairs(api):
    """PRD §3.2: "A successful entry increments the facility's
    `current_bather_count` by 1 and recomputes `required_lifeguard_count`.
    Exit transitions the admission from `ENTERED` to `EXITED`, stamps
    `exited_at`, decrements `current_bather_count` by 1, and recomputes the
    lifeguard requirement."

    Design: Difficulty/compensating_invariant/bather_count_enter_exit_invariant
    """
    facility, holders = _setup_with_holders(
        2, clock_date="2026-07-18",
        facility_overrides=dict(max_bather_capacity=100, lap_lane_count=2),
    )
    a1 = _issue(facility["id"], holders[0]["id"], date="2026-07-18")
    a2 = _issue(facility["id"], holders[1]["id"], date="2026-07-18")
    get_success_data(api.enter_admission(a1["id"], GATE))
    get_success_data(api.enter_admission(a2["id"], GATE))
    assert get_facility(facility["id"])["current_bather_count"] == 2
    get_success_data(api.exit_admission(a1["id"], GATE))
    assert get_facility(facility["id"])["current_bather_count"] == 1
    get_success_data(api.exit_admission(a2["id"], GATE))
    assert get_facility(facility["id"])["current_bather_count"] == 0


def test_admission_enter_twice_rejected_no_double_count(api):
    """PRD §3.2: "A second entry attempt on an already-`ENTERED` admission,
    or a second check-in on any already-active record elsewhere in the
    system, is rejected with `ERR_ALREADY_CHECKED_IN` (HTTP 409)."
    PRD §3.2: "A successful entry increments the facility's
    `current_bather_count` by 1 and recomputes `required_lifeguard_count`."

    Design: Corner/state_machines/admission_enter_twice_returns_invalid_state
    """
    facility, holders = _setup_with_holders(1)
    admission = _issue(facility["id"], holders[0]["id"])
    get_success_data(api.enter_admission(admission["id"], GATE))
    resp = api.enter_admission(admission["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_IN)
    assert get_facility(facility["id"])["current_bather_count"] == 1, (
        "A rejected second entry must not double-count the bather"
    )


def test_admission_date_not_today_returns_422(api):
    """PRD §3.2: "Issue-time checks reject the request when `admission_date`
    is not today's date per the logical clock, or when the season covering
    that date is not `PUBLISHED`, with `ERR_ADMISSION_DATE_INVALID`
    (HTTP 422)."

    Design: Corner/validations/admission_date_not_today_returns_422
    """
    facility, holders = _setup_with_holders(1)
    resp = api.create_admission(
        create_admission_payload(
            facility["id"], holders[0]["id"], "2026-07-06T00:00:00Z"
        ),
        GATE,
    )
    validate_error(resp, ApiErrorId.ERR_ADMISSION_DATE_INVALID)


def test_body_fk_pass_holder_not_found_returns_404(api):
    """PRD §2.9: "The same left-to-right rule applies to foreign keys inside
    request bodies: an unresolvable `pass_holder_id`, `season_id`,
    `level_id`, `lifeguard_id`, `lesson_session_id`,
    `owning_lesson_session_id`, `placement_evidence_level_id`,
    `involved_pass_holder_id`, or `reporting_lifeguard_id` produces
    `ERR_NOT_FOUND`."

    Design: Corner/validations/body_fk_pass_holder_not_found_returns_404
    """
    facility = make_facility()
    make_season(facility["id"])
    set_clock("2026-07-01T00:00:00Z")
    resp = api.create_admission(
        create_admission_payload(
            facility["id"], NON_EXISTENT_UUID, "2026-07-01T00:00:00Z"
        ),
        GATE,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_admission_enter_gated_by_closed_chemistry_posture(api):
    """PRD §3.2: "Entry at the gate transitions it to `ENTERED` and stamps
    `entered_at` with the current clock; entry requires the facility to be
    `OPEN` or `RESTRICTED` (rejecting with `ERR_FACILITY_CLOSED`)".
    PRD §2.10: "Facility not in a `CLOSED_*` posture for operations that
    admit, check in, schedule, or approve (`ERR_FACILITY_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/admission_enter_gated_by_facility_posture
    """
    facility, holders = _setup_with_holders(
        1, clock_date="2026-07-12",
        facility_overrides=dict(max_bather_capacity=100, lap_lane_count=2),
    )
    lifeguard = make_lifeguard()
    set_clock("2026-07-12T09:00:00Z")
    admission = _issue(facility["id"], holders[0]["id"], date="2026-07-12")
    make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-07-12T09:30:00Z",
        free_chlorine_ppm=6.0, ph=7.5, combined_chlorine_ppm=0.2,
    )
    assert get_facility(facility["id"])["operational_status"] == "CLOSED_CHEMISTRY"
    resp = api.enter_admission(admission["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLOSED)
    admission_after = validate_success(api.get_admission(admission["id"], GATE))
    assert admission_after["status"] == "ISSUED"


def test_admission_enter_allowed_while_restricted(api):
    """PRD §3.3: "A `WARNING` reading on an `OPEN` facility transitions it to
    `RESTRICTED` and sets `chemistry_state` to `WARNING`; new lesson sessions
    cannot be started while restricted, but gate admissions continue."
    PRD §3.2: "entry requires the facility to be `OPEN` or `RESTRICTED`
    (rejecting with `ERR_FACILITY_CLOSED`)".

    Design: Difficulty/cross_entity_state_dependency/admission_enter_gated_by_facility_posture
    """
    facility, holders = _setup_with_holders(
        1, clock_date="2026-07-12",
        facility_overrides=dict(max_bather_capacity=100, lap_lane_count=2),
    )
    lifeguard = make_lifeguard()
    set_clock("2026-07-12T09:00:00Z")
    admission = _issue(facility["id"], holders[0]["id"], date="2026-07-12")
    make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-07-12T09:30:00Z",
        free_chlorine_ppm=2.5, ph=7.5, combined_chlorine_ppm=0.6,
    )
    assert get_facility(facility["id"])["operational_status"] == "RESTRICTED"
    entered = validate_success(api.enter_admission(admission["id"], GATE))
    assert entered["status"] == "ENTERED"


def test_bather_load_at_zero_requires_zero_guards(api):
    """PRD §3.5: "The staffing requirement is recomputed every time
    `current_bather_count` changes. When the count is 0, the requirement is 0
    guards. When the count is between 1 and 50 inclusive, the requirement is
    2 guards."

    Design: Corner/calculations/bather_load_at_zero_requires_zero_guards
    """
    facility = make_facility(max_bather_capacity=200, lap_lane_count=2)
    data = validate_success(api.get_facility(facility["id"], MANAGER))
    assert_facility(data)
    assert data["current_bather_count"] == 0
    assert data["required_lifeguard_count"] == 0
    # One entered bather -> 2 guards required.
    make_season(facility["id"])
    holder = make_pass_holder()
    set_clock("2026-07-01T10:00:00Z")
    admission = make_admission(
        facility["id"], holder["id"], "2026-07-01T00:00:00Z"
    )
    get_success_data(api.enter_admission(admission["id"], GATE))
    after = get_facility(facility["id"])
    assert after["current_bather_count"] == 1
    assert after["required_lifeguard_count"] == 2


def test_derived_bather_count_reconciles_after_rental_checkin_checkout(api):
    """PRD §3.7: "Check-in adds `party_size` to `current_bather_count` and
    recomputes `required_lifeguard_count`. Check-out moves the rental to
    `COMPLETED`, subtracts `party_size` from `current_bather_count`".
    PRD §3.2: "A successful entry increments the facility's
    `current_bather_count` by 1 and recomputes `required_lifeguard_count`."

    Design: Corner/cross_cutting/derived_bather_count_reconciles_after_rental_checkin_checkout
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    make_season(facility["id"])
    p = make_pass_holder(full_name="P")
    q = make_pass_holder(full_name="Q")
    r = make_pass_holder(full_name="R")
    set_clock("2026-07-15T00:00:00Z")
    rental = make_rental(
        facility["id"], p["id"],
        party_size=8,
        start_datetime="2026-08-01T14:00:00Z",
        end_datetime="2026-08-01T16:00:00Z",
    )
    approve_rental(rental["id"], facility["id"])
    set_clock("2026-08-01T14:00:00Z")
    get_success_data(api.check_in_rental(rental["id"], GATE))
    adm_q = make_admission(facility["id"], q["id"], "2026-08-01T00:00:00Z")
    adm_r = make_admission(facility["id"], r["id"], "2026-08-01T00:00:00Z")
    get_success_data(api.enter_admission(adm_q["id"], GATE))
    get_success_data(api.enter_admission(adm_r["id"], GATE))
    peak = get_facility(facility["id"])["current_bather_count"]
    assert peak == 10, f"Peak must be 8 rental + 2 admissions = 10, got {peak}"
    get_success_data(api.check_out_rental(rental["id"], GATE))
    get_success_data(api.exit_admission(adm_q["id"], GATE))
    after = get_facility(facility["id"])["current_bather_count"]
    assert after == 1, (
        f"After rental check-out and one exit the count must be 1, got {after}"
    )
