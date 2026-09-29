"""
Boundaries: the room's half-open occupancy interval and the renal dose step.

Two kinds of boundary are probed here. The first is an interval boundary: the
room is booked on a half-open interval, so a start one minute inside the
previous case's block is refused while a start exactly on that block's end
instant fits perfectly — and the boundary instant is itself derived from the
procedure duration and the turnover arithmetic, so an off-by-one anywhere in
the chain flips the verdict. The second is a numeric boundary plus a rounding
step: the renal adjustment threshold is compared with "at least", and the
dispensing increment is snapped by rounding the quotient half up before
multiplying back, which for one of the agents rounds the dose down rather than
up.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ROOM_WINDOW_CONFLICT
from test_helpers.assertions import assert_fields
from test_helpers.constants import (
    AGENT_AUTO,
    AGENT_CIPROFLOXACIN,
    AGENT_TMP_SMX,
    ANTIBIOTIC_ORDERED,
    CASE_DRAFT,
    CASE_SCHEDULED,
    CLEANUP_HIGH,
    ROOM_TYPE_CYSTO_SUITE,
    ROUTE_ORAL,
    TYPE_CYSTOSCOPY,
)

# ─── The room's half-open occupancy interval ────────────────────────────────

WINDOW_CLOCK = "2026-09-14T07:00:00Z"

FIRST_START_AT = "2026-09-14T14:00:00Z"
FIRST_END_AT = "2026-09-14T14:20:00.000Z"
FIRST_BLOCK_END_AT = "2026-09-14T15:00:00.000Z"

# One minute inside the first case's turnover tail.
INSIDE_START_AT = "2026-09-14T14:59:00Z"

# Exactly on the first case's block_end_at.
ADJACENT_START_AT = "2026-09-14T15:00:00Z"
ADJACENT_END_AT = "2026-09-14T15:20:00.000Z"
ADJACENT_BLOCK_END_AT = "2026-09-14T16:00:00.000Z"


def _build_scope_cystoscopy_practice(api):
    """
    A cystoscopy suite with a ten-minute baseline turnover and a scope-handling
    cystoscopy of twenty base minutes with a high cleanup class. The patient is
    not anticoagulated and their renal function is well above the adjustment
    threshold, so the in-room duration takes neither of its two additions.

    The scope obligation is never satisfied — no scope is ever assigned — which
    is harmless here because the scope gate only bites at check-in, while its
    twenty extra turnover minutes are part of the window from the moment the
    case is drafted.
    """
    roster = fx.build_roster(api)
    room = fx.create_room(api, ROOM_TYPE_CYSTO_SUITE, turnover_minutes=10)
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=True,
        requires_antibiotic=False,
        required_prep_codes=[],
    )
    patient = fx.create_patient(
        api,
        roster.urologist,
        full_name="Vera Solis",
        date_of_birth="1968-05-27",
        egfr=60,
        anticoagulant_flag=False,
    )
    fx.set_clock(api, WINDOW_CLOCK, roster.admin_headers)
    return roster, room, procedure_type, patient


def test_drafted_window_derives_the_block_end_from_turnover_arithmetic(api):
    """PRD §3.2: "First the room's own `turnover_minutes` is multiplied by a
    cleanup multiplier of 2 when the procedure type's `cleanup_class` is `HIGH`
    and by 1 when it is `LOW`. That product is then floored at a quarter of an
    hour: whichever of the product and 15 minutes is larger becomes the working
    figure. Only then, if the procedure type's `requires_scope` is true, a
    further twenty minutes is added for scope handling."
    PRD §3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by
    `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at`
    advanced by `turnover_minutes` minutes."

    Design: Difficulty/boundary_precision_check/bp_room_turnover_adjacent_boundary
    """
    roster, room, procedure_type, patient = _build_scope_cystoscopy_practice(api)

    case = fx.draft_case(
        api, roster, patient, procedure_type, room, FIRST_START_AT
    )

    # 10 baseline x 2 for the high cleanup class is 20, which already clears the
    # quarter-hour floor, and scope handling adds a further 20.
    assert_fields(
        case,
        schedule_status=CASE_DRAFT,
        procedure_minutes=20,
        turnover_minutes=40,
        scheduled_end_at=FIRST_END_AT,
        block_end_at=FIRST_BLOCK_END_AT,
    )


def test_start_one_minute_inside_the_previous_block_is_refused(api):
    """PRD §3.3: "A room's occupancy is the *half-open* interval that begins at
    `scheduled_start_at` and ends at `block_end_at`, the endpoint excluded."
    PRD §3.3: "Two cases in the same room conflict when their half-open
    intervals intersect; a new case whose `scheduled_start_at` falls exactly on
    an existing case's `block_end_at` therefore fits perfectly and is accepted,
    while a start one minute earlier than that is refused with
    `ERR_ROOM_WINDOW_CONFLICT`."

    Design: Difficulty/boundary_precision_check/bp_room_turnover_adjacent_boundary
    """
    roster, room, procedure_type, patient = _build_scope_cystoscopy_practice(api)

    first = fx.draft_case(api, roster, patient, procedure_type, room, FIRST_START_AT)
    first = fx.commit_case(api, roster, first, room)
    assert_fields(
        first,
        schedule_status=CASE_SCHEDULED,
        scheduled_end_at=FIRST_END_AT,
        block_end_at=FIRST_BLOCK_END_AT,
    )

    second = fx.draft_case(api, roster, patient, procedure_type, room, INSIDE_START_AT)

    # The room's version is read again so the optimistic-concurrency rung is
    # satisfied and cannot mask the occupancy rule under test.
    room_now = fx.read_room(api, roster, room["id"])
    response = api.schedule_case(
        second["id"],
        f.schedule_payload(room_now["version"]),
        roster.scheduler_headers,
    )

    validate_error(response, ERR_ROOM_WINDOW_CONFLICT)

    after = validate_success(
        api.get_procedure_case(second["id"], roster.scheduler_headers)
    )
    assert_fields(after, schedule_status=CASE_DRAFT)


def test_start_exactly_on_the_previous_block_end_is_accepted(api):
    """PRD §3.3: "Two cases in the same room conflict when their half-open
    intervals intersect; a new case whose `scheduled_start_at` falls exactly on
    an existing case's `block_end_at` therefore fits perfectly and is accepted,
    while a start one minute earlier than that is refused with
    `ERR_ROOM_WINDOW_CONFLICT`."
    PRD §3.3: "Committing a case to the calendar is the `Scheduler`'s exclusive
    act, and it advances `schedule_status` from `DRAFT` to `SCHEDULED`."

    Design: Difficulty/boundary_precision_check/bp_room_turnover_adjacent_boundary
    """
    roster, room, procedure_type, patient = _build_scope_cystoscopy_practice(api)

    first = fx.draft_case(api, roster, patient, procedure_type, room, FIRST_START_AT)
    first = fx.commit_case(api, roster, first, room)
    assert_fields(first, block_end_at=FIRST_BLOCK_END_AT)

    adjacent = fx.draft_case(
        api, roster, patient, procedure_type, room, ADJACENT_START_AT
    )

    room_now = fx.read_room(api, roster, room["id"])
    response = api.schedule_case(
        adjacent["id"],
        f.schedule_payload(room_now["version"]),
        roster.scheduler_headers,
    )

    data = validate_success(response, 200)
    # The two buffered provider intervals — 13:50 to 14:30 and 14:50 to 15:30 —
    # do not touch, so the provider rule stays silent and the accepted booking
    # is the room rule's verdict alone.
    assert_fields(
        data,
        schedule_status=CASE_SCHEDULED,
        procedure_minutes=20,
        turnover_minutes=40,
        scheduled_end_at=ADJACENT_END_AT,
        block_end_at=ADJACENT_BLOCK_END_AT,
    )


# ─── The renal adjustment threshold and the dispensing increment ─────────────

DOSE_CLOCK = "2026-09-14T07:00:00Z"
DOSE_START_AT = "2026-09-14T14:00:00Z"
DOSE_WINDOW_START_AT = "2026-09-14T13:00:00.000Z"

AT_THRESHOLD_BLOCK_END_AT = "2026-09-14T14:40:00.000Z"
BELOW_THRESHOLD_BLOCK_END_AT = "2026-09-14T14:50:00.000Z"


def _build_prophylaxis_practice(api):
    """
    A cystoscopy that requires prophylaxis, booked for two patients whose renal
    function straddles the adjustment threshold: one at exactly 45 and one at
    44. Neither carries an antibiotic allergy, so the only agent excluded from
    the eligible pool is the one whose renal floor is 60.

    Both cases stay drafts and may therefore share a start instant: a draft
    occupies neither the room nor the urologist.
    """
    roster = fx.build_roster(api)
    room = fx.create_room(api, ROOM_TYPE_CYSTO_SUITE, turnover_minutes=10)
    procedure_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_antibiotic=True,
        consignment_required=False,
        required_prep_codes=[],
    )
    patient_at_threshold = fx.create_patient(
        api,
        roster.urologist,
        full_name="Hugo Vance",
        date_of_birth="1957-07-07",
        egfr=45,
        anticoagulant_flag=False,
        antibiotic_allergy_class="NONE",
    )
    patient_below = fx.create_patient(
        api,
        roster.urologist,
        full_name="Marta Quill",
        date_of_birth="1951-10-19",
        egfr=44,
        anticoagulant_flag=False,
        antibiotic_allergy_class="NONE",
    )
    fx.set_clock(api, DOSE_CLOCK, roster.admin_headers)
    case_at_threshold = fx.draft_case(
        api, roster, patient_at_threshold, procedure_type, room, DOSE_START_AT
    )
    case_below = fx.draft_case(
        api, roster, patient_below, procedure_type, room, DOSE_START_AT
    )
    return roster, case_at_threshold, case_below


def _order(api, roster, case_id, requested_agent):
    """Place one prophylaxis order as the operating urologist."""
    return validate_success(
        api.create_antibiotic_order(
            f.antibiotic_order_payload(
                case_id=case_id,
                ordered_by_provider_id=roster.urologist["id"],
                requested_agent=requested_agent,
            ),
            roster.urologist_headers,
        ),
        201,
    )


def test_dose_is_full_strength_at_egfr_exactly_45(api):
    """PRD §3.4: "The selected agent's base dose is taken at full strength when
    the patient's `egfr` is at least 45, and at exactly half strength when it is
    below 45. That raw figure is divided by 25, the quotient is rounded half up
    to a whole number, and the result is multiplied back by 25 to give the
    stored `dose_mg`."
    PRD §3.4: "The order also records `prophylaxis_window_start_at`, fixed at
    one hour before the case's `scheduled_start_at`, and is created with
    `status` `ORDERED` and `administered_at` null."

    Design: Difficulty/boundary_precision_check/bp_renal_dose_step_rounding_at_egfr_45
    """
    roster, case_at_threshold, _ = _build_prophylaxis_practice(api)

    order = _order(api, roster, case_at_threshold["id"], AGENT_AUTO)

    # A renal floor of 60 puts one agent out of the pool for this patient, so
    # the automatic choice is the cystoscopy protocol's first-ranked agent at
    # its full 500 mg, which is already a whole multiple of the 25 mg step.
    assert_fields(
        order,
        agent=AGENT_CIPROFLOXACIN,
        dose_mg=500,
        route=ROUTE_ORAL,
        status=ANTIBIOTIC_ORDERED,
        prophylaxis_window_start_at=DOSE_WINDOW_START_AT,
        administered_at=None,
    )


def test_dose_is_halved_one_point_below_the_renal_threshold(api):
    """PRD §3.4: "The selected agent's base dose is taken at full strength when
    the patient's `egfr` is at least 45, and at exactly half strength when it is
    below 45. That raw figure is divided by 25, the quotient is rounded half up
    to a whole number, and the result is multiplied back by 25 to give the
    stored `dose_mg`."

    Design: Difficulty/boundary_precision_check/bp_renal_dose_step_rounding_at_egfr_45
    """
    roster, _, case_below = _build_prophylaxis_practice(api)

    order = _order(api, roster, case_below["id"], AGENT_AUTO)

    # Half of 500 is 250, and 250 divided by the 25 mg step is 10 exactly.
    assert_fields(
        order,
        agent=AGENT_CIPROFLOXACIN,
        dose_mg=250,
        route=ROUTE_ORAL,
        status=ANTIBIOTIC_ORDERED,
    )


def test_explicit_agent_dose_snaps_down_when_the_quotient_rounds_down(api):
    """PRD §2.7: "Doses are whole milligrams, and where a dose must be snapped
    to a dispensing increment the division by the increment is rounded half up
    **before** multiplying back up, never after."
    PRD §3.4: "`TMP_SMX` belongs to `SULFA`, needs at least 30, has a base dose
    of 160 milligrams and is `ORAL`."

    Design: Difficulty/boundary_precision_check/bp_renal_dose_step_rounding_at_egfr_45
    """
    roster, _, case_below = _build_prophylaxis_practice(api)

    order = _order(api, roster, case_below["id"], AGENT_TMP_SMX)

    # Half of 160 is 80; 80 divided by the 25 mg step is 3.2, which rounds half
    # up to 3, and 3 steps back up is 75 mg — not the 100 mg a snap upwards to
    # the next increment would produce.
    assert_fields(
        order,
        agent=AGENT_TMP_SMX,
        dose_mg=75,
        route=ROUTE_ORAL,
        status=ANTIBIOTIC_ORDERED,
    )


def test_renal_extra_minutes_apply_only_strictly_below_the_threshold(api):
    """PRD §3.2: "Ten further minutes are added when the patient's `egfr` is
    strictly below 45 **and** the procedure type's `requires_antibiotic` is
    true, covering the extra time renal-dosed prophylaxis takes to run in."
    PRD §3.2: "The sum of `base_minutes` and those two additions is stored as
    the case's `procedure_minutes`."

    Design: Difficulty/boundary_precision_check/bp_renal_dose_step_rounding_at_egfr_45
    """
    roster, case_at_threshold, case_below = _build_prophylaxis_practice(api)

    at_threshold = validate_success(
        api.get_procedure_case(case_at_threshold["id"], roster.urologist_headers)
    )
    below = validate_success(
        api.get_procedure_case(case_below["id"], roster.urologist_headers)
    )

    # The same threshold constant drives both the dose factor and the duration,
    # and both read it as "at least 45": the patient at exactly 45 takes the
    # base twenty minutes, the patient at 44 takes thirty.
    assert_fields(
        at_threshold,
        procedure_minutes=20,
        turnover_minutes=20,
        block_end_at=AT_THRESHOLD_BLOCK_END_AT,
    )
    assert_fields(
        below,
        procedure_minutes=30,
        turnover_minutes=20,
        block_end_at=BELOW_THRESHOLD_BLOCK_END_AT,
    )
