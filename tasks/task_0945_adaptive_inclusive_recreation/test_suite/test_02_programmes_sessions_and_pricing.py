"""Programme configuration, session lifecycle and sliding-scale pricing."""

from test_helpers import (
    ApiErrorId,
    activity_program_payload,
    api_client,
    cancel_session,
    charge_for,
    create_active_participant,
    create_fee_band,
    create_open_session,
    create_participant,
    create_program,
    create_session,
    create_staff,
    open_session,
    read_session,
    request_enrollment,
    session_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORD, OFFICER
from test_helpers.test_users import make_activity_lead_headers


def test_activity_program_optional_fields_take_their_declared_defaults():
    """PRD §3.1: "`required_consent_types` is a list drawn from `MEDIA_RELEASE`,
    `EMERGENCY_MEDICAL`, `BEHAVIOR_SUPPORT_PLAN` and `MEDICATION_ADMIN`, and
    defaults to the empty list when omitted or sent as null, meaning no consent
    is demanded."
    PRD §3.1: "`required_certification_types` is a list drawn from
    `ADAPTIVE_AQUATICS`, `BEHAVIOR_SUPPORT`, `MEDICATION_ADMIN` and `CPR`, and
    likewise defaults to the empty list. `requires_medication_admin` is a boolean
    defaulting to false."
    PRD §3.1: "`required_equipment_model_code` and `required_equipment_size_code`
    are strings that both default to null; a null model code means the programme
    needs no adaptive equipment, and a size code is meaningful only alongside a
    model code."
    PRD §3.1: "Each programme also carries a computed `session_count_created`,
    which starts at 0 and counts the sessions built from it."

    Design: Corner/entities/activity_program_optional_fields_take_their_declared_defaults
    """
    payload = {
        "name": "Minimal Program",
        "activity_type": "ARTS",
        "risk_tier": "LOW",
        "pricing_mode": "PER_SESSION",
        "rounding_policy": "ROUND_ON_TOTAL",
        "waitlist_policy": "FIFO",
        "fee_multiplier_bp": 10000,
        "scheduled_session_count": 1,
    }
    data = validate_success(
        api_client.create_activity_program(payload, ADMIN), expected_status=201
    )

    assert data["required_consent_types"] == []
    assert data["required_certification_types"] == []
    assert data["requires_medication_admin"] is False
    assert data["required_equipment_model_code"] is None
    assert data["required_equipment_size_code"] is None
    assert data["session_count_created"] == 0


def test_missing_fee_band_for_household_returns_fee_band_not_found():
    """PRD §3.3: "The candidate set is every fee-scale band whose
    `household_size_min` is less than or equal to the participant's
    `household_size` and whose `household_size_max` is greater than or equal to
    it, and whose `income_band` equals the participant's `income_band` — both
    bounds inclusive."
    PRD §3.3: "When the candidate set is empty the whole enrolment request fails
    with `ERR_FEE_BAND_NOT_FOUND` (404) and nothing is written."

    Design: Corner/entities/fee_band_missing_for_household_returns_fee_band_not_found
    """
    create_fee_band(income_band="BAND_C")
    _program, session = create_open_session()
    who = create_active_participant(
        legal_name="Dara Kim", household_id="HH-4", income_band="BAND_D"
    )

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": who["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": session_version(session["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_FEE_BAND_NOT_FOUND.value,
        expected_status=404,
    )

    _rows, meta = validate_paginated(
        api_client.list_enrollments(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0, "nothing is written when no band covers the household"
    _charges, charge_meta = validate_paginated(api_client.list_enrollment_charges(OFFICER))
    assert charge_meta["total_count"] == 0


def test_enrollment_charge_is_discoverable_only_through_the_filtered_list():
    """PRD §3.3: "Because the charge is created by a cascade and not returned by
    the create call, the only way to discover it is through the enrolment-charge
    list read, filtered by `enrollment_id`."
    PRD §3.3: "It is born with the pinned `fee_scale_band_id`, the computed
    `program_fee_cents`, `scholarship_applied_cents` 0, `copay_cents` equal to
    `program_fee_cents`, `transport_fee_cents` 0, `sibling_discount_bp` 0,
    `amount_paid_cents` 0, a `family_responsibility_cents` computed by the rule
    in §3.8, a `balance_cents` equal to `family_responsibility_cents` minus
    `amount_paid_cents`, and `status` `QUOTED`."

    Design: Corner/entities/enrollment_charge_is_discoverable_only_through_the_filtered_list
    """
    band = create_fee_band(per_session_cents=4000)
    _program, session = create_open_session()
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    rows, meta = validate_paginated(
        api_client.list_enrollment_charges(OFFICER, params={"enrollment_id": enrollment["id"]})
    )
    assert meta["total_count"] == 1, f"Expected exactly one charge, got {meta['total_count']}"
    charge = rows[0]
    assert charge["program_fee_cents"] == 4000
    assert charge["copay_cents"] == 4000
    assert charge["status"] == "QUOTED", "the enrolment is still REQUESTED"
    assert charge["fee_scale_band_id"] == band["id"]
    assert charge["enrollment_id"] == enrollment["id"]

    direct = validate_success(api_client.get_enrollment_charge(charge["id"], OFFICER))
    assert direct["id"] == charge["id"]


def test_cancelling_an_already_cancelled_session_returns_already_terminal():
    """PRD §2.10 rung 27: "On every state-transition endpoint, the target row is
    not already in a terminal state of the axis being driven — otherwise
    `ERR_ALREADY_TERMINAL` (409)."
    PRD §3.1: "Cancellation is available from `DRAFT`, from `OPEN` and from
    `STAFFING_LOCKED`, and `CANCELLED` is likewise terminal."

    Design: Corner/state_machines/cancel_an_already_cancelled_session_returns_already_terminal
    """
    _program, session = create_open_session()
    cancel_session(session["id"])

    validate_error(
        api_client.cancel_session(session["id"], ADMIN),
        ApiErrorId.ERR_ALREADY_TERMINAL.value,
        expected_status=409,
    )
    assert read_session(session["id"])["status"] == "CANCELLED"


def test_unlock_staffing_on_an_open_session_returns_invalid_state():
    """PRD §2.10 rung 26: "On every state-transition endpoint, the target row is
    in a declared source state for the requested transition — otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §3.5: "Unlocking returns a `STAFFING_LOCKED` session to `OPEN`, raises
    its `unlock_count` by one and its `version` by one, and is capped: the third
    attempt, made when `unlock_count` already equals 2, is refused with
    `ERR_UNLOCK_LIMIT_REACHED`."

    Design: Corner/state_machines/unlock_staffing_on_an_open_session_returns_invalid_state
    """
    _program, session = create_open_session()
    staff_id = create_staff()["id"]

    validate_error(
        api_client.unlock_staffing(session["id"], make_activity_lead_headers(staff_id)),
        ApiErrorId.ERR_INVALID_STATE.value,
        expected_status=409,
    )

    after = read_session(session["id"])
    assert after["status"] == "OPEN"
    assert after["unlock_count"] == 0


def test_bad_pagination_and_bad_enum_are_reported_separately():
    """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is
    rejected with `ERR_INVALID_PAGINATION` (400)."
    PRD §2.10 rung 23: "Every enum-typed field in a write payload carries a
    declared member of that enumeration — otherwise `ERR_INVALID_ENUM` (400)."

    Design: Corner/validations/request_shape_rungs_reject_bad_pagination_and_bad_enum
    """
    create_participant()

    validate_error(
        api_client.list_participants(ADMIN, params={"limit": 500, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        expected_status=400,
    )

    bad = activity_program_payload(name="Bad Program", activity_type="AQUATICS")
    bad["risk_tier"] = "EXTREME"
    validate_error(
        api_client.create_activity_program(bad, ADMIN),
        ApiErrorId.ERR_INVALID_ENUM.value,
        expected_status=400,
    )


def test_logical_clock_defaults_to_2026_05_01_before_any_set_call():
    """PRD §2.4: "Instead the server keeps a **logical clock**, an ISO 8601 UTC
    instant that begins its life at exactly `2026-05-01T00:00:00Z` and that
    changes only when a `ProgramAdmin` sets it."
    PRD §3.3: "The session's `start_at` must be at least 24 hours later than the
    logical clock; a session starting in exactly 24 hours is still enrollable,
    one starting in 23 hours 59 minutes is not, and the failure is
    `ERR_ENROLLMENT_CUTOFF_PASSED`."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_05_01_before_any_set_call
    """
    create_fee_band()
    program = create_program(scheduled_session_count=2)
    near = create_session(
        program["id"], start_at="2026-05-01T12:00:00Z", end_at="2026-05-01T14:00:00Z"
    )
    edge = create_session(
        program["id"], start_at="2026-05-02T00:00:00Z", end_at="2026-05-02T02:00:00Z"
    )
    open_session(near["id"])
    open_session(edge["id"])
    who = create_active_participant()

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": who["participant"]["id"],
                "session_id": near["id"],
                "expected_session_version": session_version(near["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_ENROLLMENT_CUTOFF_PASSED.value,
        expected_status=422,
    )

    accepted = validate_success(
        api_client.create_enrollment(
            {
                "participant_id": who["participant"]["id"],
                "session_id": edge["id"],
                "expected_session_version": session_version(edge["id"]),
            },
            COORD,
        ),
        expected_status=201,
    )
    assert accepted["enrollment_status"] == "REQUESTED"
    assert accepted["funding_status"] == "QUOTED"


def test_series_flat_loads_the_whole_remainder_onto_sequence_number_one():
    """PRD §3.3: "Divide the series total by the programme's
    `scheduled_session_count` and take the floor to get the per-session base. The
    remainder is the series total minus the base multiplied by the session count.
    The fee for this enrolment is the base, plus the entire remainder when and
    only when the session's `sequence_number` is 1."
    PRD §3.1: "The server stamps `sequence_number` as the programme's
    `session_count_created` plus one — so the first session of a series is
    sequence number 1 — then raises `session_count_created` by one and bumps the
    programme's `version`."

    Design: Difficulty/dual_variant_calc/series_flat_remainder_lands_on_sequence_one_not_per_session
    """
    band = create_fee_band(per_session_cents=4000, series_cents=24000)
    program = create_program(
        name="Adaptive Aquatics Series",
        activity_type="AQUATICS",
        pricing_mode="SERIES_FLAT",
        fee_multiplier_bp=11250,
        scheduled_session_count=7,
    )
    first = create_session(
        program["id"], start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T11:00:00Z",
        slot_capacity=5,
    )
    second = create_session(
        program["id"], start_at="2026-06-08T09:00:00Z", end_at="2026-06-08T11:00:00Z",
        slot_capacity=5,
    )
    open_session(first["id"])
    open_session(second["id"])
    who = create_active_participant(household_size=3, income_band="BAND_C")
    participant_id = who["participant"]["id"]

    enrollment_one = request_enrollment(participant_id, first["id"])
    enrollment_two = request_enrollment(participant_id, second["id"])

    assert read_session(first["id"])["sequence_number"] == 1
    assert read_session(second["id"])["sequence_number"] == 2

    charge_one = charge_for(enrollment_one["id"])
    charge_two = charge_for(enrollment_two["id"])
    assert charge_one["program_fee_cents"] == 3858, (
        "series total 27000 over 7 sessions is a base of 3857 plus a remainder of 1 on "
        f"sequence 1; got {charge_one['program_fee_cents']}"
    )
    assert charge_two["program_fee_cents"] == 3857, (
        f"every other session carries the bare base; got {charge_two['program_fee_cents']}"
    )
    assert charge_one["fee_scale_band_id"] == band["id"]


def test_per_session_pricing_ignores_the_series_divisor():
    """PRD §3.3: "Under `PER_SESSION`, the fee is the band's `per_session_cents`
    multiplied by the programme's `fee_multiplier_bp`, divided by 10000, and
    rounded half up to a whole cent. The programme's `scheduled_session_count`
    and the session's `sequence_number` are ignored entirely."

    Design: Difficulty/dual_variant_calc/series_flat_remainder_lands_on_sequence_one_not_per_session
    """
    create_fee_band(per_session_cents=4000, series_cents=24000)
    program = create_program(
        name="Adaptive Aquatics Drop-in",
        activity_type="AQUATICS",
        pricing_mode="PER_SESSION",
        fee_multiplier_bp=11250,
        scheduled_session_count=7,
    )
    session = create_session(
        program["id"], start_at="2026-06-15T09:00:00Z", end_at="2026-06-15T11:00:00Z",
        slot_capacity=5,
    )
    open_session(session["id"])
    who = create_active_participant(household_size=3, income_band="BAND_C")

    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    charge = charge_for(enrollment["id"])
    assert charge["program_fee_cents"] == 4500, (
        "4000 cents at 11250 basis points is 4500 on every session of the series; "
        f"got {charge['program_fee_cents']}"
    )
    assert read_session(session["id"])["sequence_number"] == 1


def test_enrollment_create_on_a_cancelled_session_returns_session_not_open():
    """PRD §2.10 rung 28: "On enrolment creation and enrolment confirmation, the
    enrolment's session has `status` `OPEN` — otherwise `ERR_SESSION_NOT_OPEN`
    (409)."
    PRD §3.3: "The named session must currently be `OPEN`, or the request fails
    with `ERR_SESSION_NOT_OPEN` — a draft, locked, delivered or cancelled session
    accepts no new requests."

    Design: Difficulty/cross_entity_state_dependency/enrollment_create_blocked_by_cancelled_session
    """
    create_fee_band()
    _program, session = create_open_session()
    who = create_active_participant()
    cancel_session(session["id"])

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": who["participant"]["id"],
                "session_id": session["id"],
                "expected_session_version": session_version(session["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_SESSION_NOT_OPEN.value,
        expected_status=409,
    )

    after = read_session(session["id"])
    assert after["status"] == "CANCELLED"
    assert after["slots_committed"] == 0


def test_enrollment_rejected_by_a_cancelled_session_writes_no_row():
    """PRD §3.3: "The named session must currently be `OPEN`, or the request fails
    with `ERR_SESSION_NOT_OPEN` — a draft, locked, delivered or cancelled session
    accepts no new requests."
    PRD §2.10 rung 28: "On enrolment creation and enrolment confirmation, the
    enrolment's session has `status` `OPEN` — otherwise `ERR_SESSION_NOT_OPEN`
    (409)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_create_blocked_by_cancelled_session
    """
    create_fee_band()
    _program, session = create_open_session()
    who = create_active_participant()
    participant_id = who["participant"]["id"]
    cancel_session(session["id"])

    validate_error(
        api_client.create_enrollment(
            {
                "participant_id": participant_id,
                "session_id": session["id"],
                "expected_session_version": session_version(session["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_SESSION_NOT_OPEN.value,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api_client.list_enrollments(ADMIN, params={"participant_id": participant_id})
    )
    assert meta["total_count"] == 0, "a refused request leaves no enrolment behind"
    assert rows == []
