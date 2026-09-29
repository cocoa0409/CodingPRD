"""
Boundary behaviour of the Urology Procedure Suite's validation rules.

Four of this contract's rules are stated as closed or strict boundaries, and a
fifth reads a second entity before it will accept a write. This module pins each
of them from both sides of the line that matters: the prophylaxis window is
tested one minute outside each end and then exactly on each end, the no-show
grace allowance is tested at the grace instant and one minute later, the
preparation ladder is tested with a code the procedure type never asked for and
with the required set first partly and then fully acknowledged, and a pelvic
health referral is tested against the same source case before and after that
case completes. Each refusal is checked to have changed nothing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_NO_SHOW_GRACE_NOT_ELAPSED,
    ERR_PREP_CODE_NOT_REQUIRED,
    ERR_PREP_INCOMPLETE,
    ERR_PROPHYLAXIS_WINDOW_MISSED,
    ERR_SOURCE_CASE_NOT_COMPLETED,
)
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_fields,
    assert_null_fields,
    assert_version_advanced,
    assert_version_unchanged,
    assert_visit_counters,
)
from test_helpers.constants import (
    AGENT_AUTO,
    AGENT_CEFAZOLIN,
    ANTIBIOTIC_ADMINISTERED,
    ANTIBIOTIC_ORDERED,
    CASE_DRAFT,
    CASE_NO_SHOW,
    CASE_SCHEDULED,
    CHANNEL_PORTAL,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    CLEARANCE_CLEARED,
    CLEARANCE_DECISION_CLEAR,
    CLEARANCE_PENDING_PREP,
    CLEARANCE_PREP_ACKNOWLEDGED,
    DEFAULT_PREP_CODE,
    NO_SHOW_CANCEL_REASON_CODE,
    PROGRAM_BIOFEEDBACK,
    REFERRAL_REQUESTED,
    ROOM_TYPE_CYSTO_SUITE,
    ROUTE_IV,
    TYPE_CYSTOSCOPY,
    TYPE_PROSTATE_BIOPSY,
)

# ─── Preparation instruction codes used here ───────────────────────────────
PREP_NPO_MIDNIGHT = DEFAULT_PREP_CODE
PREP_HOLD_ANTICOAGULANT = "HOLD_ANTICOAGULANT"
# A declared preparation instruction that the procedure type below never asks
# for, so acknowledging it can only be a relevance failure.
PREP_BOWEL_PREP = "BOWEL_PREP"

# ─── The prophylaxis scenario ──────────────────────────────────────────────
FIRST_CASE_START_AT = "2026-09-14T14:00:00.000Z"
FIRST_WINDOW_START_AT = "2026-09-14T13:00:00.000Z"
SECOND_CASE_START_AT = "2026-09-14T16:00:00.000Z"
SECOND_WINDOW_START_AT = "2026-09-14T15:00:00.000Z"


def _setup_two_biopsies_with_open_prophylaxis_orders(api):
    """
    Two prostate biopsies for the same unallergic patient, one starting at 14:00
    and one at 16:00, each with an automatically resolved prophylaxis order still
    at ``ORDERED``. Each order's window therefore opens one hour before its own
    case: 13:00 for the first and 15:00 for the second.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, full_name="Ada Volk", date_of_birth="1960-01-01", egfr=62
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    biopsy_type = fx.create_procedure_type(
        api,
        TYPE_PROSTATE_BIOPSY,
        base_minutes=30,
        cleanup_class=CLEANUP_LOW,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=True,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, "2026-09-14T07:00:00.000Z")
    orders = []
    for start_at in (FIRST_CASE_START_AT, SECOND_CASE_START_AT):
        case = fx.draft_case(api, roster, patient, biopsy_type, room, start_at)
        orders.append(
            validate_success(
                api.create_antibiotic_order(
                    factories.antibiotic_order_payload(
                        case_id=case["id"],
                        ordered_by_provider_id=roster.urologist["id"],
                        requested_agent=AGENT_AUTO,
                    ),
                    roster.urologist_headers,
                ),
                201,
            )
        )
    return {"roster": roster, "first_order": orders[0], "second_order": orders[1]}


def test_prophylaxis_given_a_minute_outside_either_end_of_the_window_is_refused(api):
    """PRD 2.8: "`administered_at` falls inside the closed interval that begins at
    the order's `prophylaxis_window_start_at` and ends at the case's
    `scheduled_start_at`; both endpoints are accepted. Otherwise
    `ERR_PROPHYLAXIS_WINDOW_MISSED`, HTTP 422."
    PRD 3.4: "That instant must fall inside the closed interval running from the
    order's `prophylaxis_window_start_at` through the case's `scheduled_start_at`,
    both endpoints inclusive; a dose given even a minute before the window opens
    or after the scheduled start is refused with
    `ERR_PROPHYLAXIS_WINDOW_MISSED`."

    Design: Corner/validations/val_violation_to_error_prophylaxis_window_missed_both_ends
    """
    scene = _setup_two_biopsies_with_open_prophylaxis_orders(api)
    roster = scene["roster"]
    order = scene["first_order"]
    assert order["prophylaxis_window_start_at"] == FIRST_WINDOW_START_AT, (
        "precondition: the window must open one hour before the 14:00 case, "
        f"got {order['prophylaxis_window_start_at']!r}"
    )

    too_early = api.administer_antibiotic_order(
        order["id"],
        factories.administer_payload("2026-09-14T12:59:00.000Z"),
        roster.nurse_headers,
    )
    validate_error(too_early, ERR_PROPHYLAXIS_WINDOW_MISSED)

    too_late = api.administer_antibiotic_order(
        order["id"],
        factories.administer_payload("2026-09-14T14:01:00.000Z"),
        roster.urologist_headers,
    )
    validate_error(too_late, ERR_PROPHYLAXIS_WINDOW_MISSED)

    unchanged = validate_success(
        api.get_antibiotic_order(order["id"], roster.urologist_headers), 200
    )
    assert_fields(
        unchanged,
        status=ANTIBIOTIC_ORDERED,
        agent=AGENT_CEFAZOLIN,
        prophylaxis_window_start_at=FIRST_WINDOW_START_AT,
    )
    assert_null_fields(unchanged, "administered_at")
    assert_version_unchanged(order, unchanged)


def test_prophylaxis_given_exactly_on_either_closed_end_of_the_window_is_accepted(api):
    """PRD 2.8: "`administered_at` falls inside the closed interval that begins at
    the order's `prophylaxis_window_start_at` and ends at the case's
    `scheduled_start_at`; both endpoints are accepted. Otherwise
    `ERR_PROPHYLAXIS_WINDOW_MISSED`, HTTP 422."
    PRD 3.4: "On success the order's `status` moves from `ORDERED` to
    `ADMINISTERED`, `administered_at` is stored, and the antibiotic gate drops out
    of the case's `blocking_reason_codes`."

    Design: Corner/validations/val_satisfaction_to_pass_prophylaxis_at_both_closed_ends
    """
    scene = _setup_two_biopsies_with_open_prophylaxis_orders(api)
    roster = scene["roster"]

    # The lower end: the very instant the window opens.
    at_window_open = validate_success(
        api.administer_antibiotic_order(
            scene["first_order"]["id"],
            factories.administer_payload(FIRST_WINDOW_START_AT),
            roster.nurse_headers,
        ),
        200,
    )
    assert_fields(
        at_window_open,
        status=ANTIBIOTIC_ADMINISTERED,
        administered_at=FIRST_WINDOW_START_AT,
        agent=AGENT_CEFAZOLIN,
        dose_mg=1000,
        route=ROUTE_IV,
    )

    # The upper end: the case's own scheduled start instant.
    assert scene["second_order"]["prophylaxis_window_start_at"] == SECOND_WINDOW_START_AT, (
        "precondition: the second window must open one hour before the 16:00 "
        f"case, got {scene['second_order']['prophylaxis_window_start_at']!r}"
    )
    at_scheduled_start = validate_success(
        api.administer_antibiotic_order(
            scene["second_order"]["id"],
            factories.administer_payload(SECOND_CASE_START_AT),
            roster.urologist_headers,
        ),
        200,
    )
    assert_fields(
        at_scheduled_start,
        status=ANTIBIOTIC_ADMINISTERED,
        administered_at=SECOND_CASE_START_AT,
        agent=AGENT_CEFAZOLIN,
        dose_mg=1000,
        route=ROUTE_IV,
    )


# ─── The preparation ladder ────────────────────────────────────────────────
def _setup_case_needing_two_prep_codes(api):
    """
    One drafted cystoscopy whose procedure type demands two preparation
    instructions, NPO_MIDNIGHT and HOLD_ANTICOAGULANT, and nothing else.
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, full_name="Iris Wren", date_of_birth="1968-06-06", egfr=80
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    cysto_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[PREP_NPO_MIDNIGHT, PREP_HOLD_ANTICOAGULANT],
    )

    fx.set_clock(api, "2026-09-14T07:00:00.000Z")
    case = fx.draft_case(
        api, roster, patient, cysto_type, room, "2026-09-14T09:00:00.000Z"
    )
    return {"roster": roster, "case": case}


def test_acknowledging_an_instruction_the_procedure_type_never_asked_for_is_refused(api):
    """PRD 3.1: "Finally, `required_prep_codes` is an array of preparation
    instruction codes drawn from `NPO_MIDNIGHT`, `BOWEL_PREP`,
    `HOLD_ANTICOAGULANT`, `BLADDER_FILL` and `ARRIVE_WITH_ESCORT`; it is optional
    and defaults to the empty array, and an empty array is a meaningful
    configuration — it means the preparation-completeness rung at priority 34
    passes vacuously for every case of that type, so clearance may be granted
    with no acknowledgements at all."
    PRD 3.4: "The supplied `instruction_code` must be one of the codes in the
    procedure type's `required_prep_codes`; an instruction that type never asked
    for is refused with `ERR_PREP_CODE_NOT_REQUIRED`."

    Design: Corner/validations/val_conditional_validation_prep_codes_present_and_absent
    """
    scene = _setup_case_needing_two_prep_codes(api)
    roster = scene["roster"]
    case = scene["case"]

    response = api.acknowledge_prep(
        case["id"],
        factories.prep_acknowledgement_payload(instruction_code=PREP_BOWEL_PREP),
        roster.nurse_headers,
    )
    validate_error(response, ERR_PREP_CODE_NOT_REQUIRED)

    unchanged = fx.read_case(api, roster, case["id"])
    assert_case_dimensions(unchanged, CASE_DRAFT, CLEARANCE_PENDING_PREP)
    assert unchanged["acknowledged_prep_codes"] == [], (
        "a refused acknowledgement must append nothing to the case, got "
        f"{unchanged['acknowledged_prep_codes']}"
    )
    assert_version_unchanged(case, unchanged)


def test_clearance_needs_every_required_code_and_a_repeat_acknowledgement_is_idempotent(api):
    """PRD 3.4: "It requires that every code in the procedure type's
    `required_prep_codes` is present in the case's `acknowledged_prep_codes`; a
    missing code is refused with `ERR_PREP_INCOMPLETE`."
    PRD 3.4: "On success the code is appended to the case's
    `acknowledged_prep_codes` array — which holds distinct codes in the order they
    were acknowledged — unless it is already present, in which case the array is
    left untouched."
    PRD 3.4: "**A repeat acknowledgement of the same code is idempotent and is
    explicitly not an error.**"
    PRD 3.4: "A successful clear sets `clearance_block_reason` back to null and
    recomputes the readiness gates."

    Design: Corner/validations/val_conditional_validation_prep_codes_present_and_absent
    """
    scene = _setup_case_needing_two_prep_codes(api)
    roster = scene["roster"]
    case_id = scene["case"]["id"]

    with_nothing_acknowledged = api.review_clearance(
        case_id,
        factories.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
        roster.nurse_headers,
    )
    validate_error(with_nothing_acknowledged, ERR_PREP_INCOMPLETE)
    assert_case_dimensions(
        fx.read_case(api, roster, case_id), CASE_DRAFT, CLEARANCE_PENDING_PREP
    )

    first_code = validate_success(
        api.acknowledge_prep(
            case_id,
            factories.prep_acknowledgement_payload(
                instruction_code=PREP_NPO_MIDNIGHT
            ),
            roster.nurse_headers,
        ),
        200,
    )
    assert_fields(
        first_code,
        clearance_status=CLEARANCE_PREP_ACKNOWLEDGED,
        acknowledged_prep_codes=[PREP_NPO_MIDNIGHT],
    )

    with_one_code_missing = api.review_clearance(
        case_id,
        factories.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
        roster.nurse_headers,
    )
    validate_error(with_one_code_missing, ERR_PREP_INCOMPLETE)

    repeated = validate_success(
        api.acknowledge_prep(
            case_id,
            factories.prep_acknowledgement_payload(
                instruction_code=PREP_NPO_MIDNIGHT, channel=CHANNEL_PORTAL
            ),
            roster.scheduler_headers,
        ),
        200,
    )
    assert repeated["acknowledged_prep_codes"] == [PREP_NPO_MIDNIGHT], (
        "re-acknowledging a code already present must leave the array untouched "
        f"rather than duplicating it, got {repeated['acknowledged_prep_codes']}"
    )
    assert repeated["clearance_status"] == CLEARANCE_PREP_ACKNOWLEDGED, (
        "the repeat acknowledgement is a self-loop on PREP_ACKNOWLEDGED, got "
        f"{repeated['clearance_status']!r}"
    )

    second_code = validate_success(
        api.acknowledge_prep(
            case_id,
            factories.prep_acknowledgement_payload(
                instruction_code=PREP_HOLD_ANTICOAGULANT
            ),
            roster.nurse_headers,
        ),
        200,
    )
    assert second_code["acknowledged_prep_codes"] == [
        PREP_NPO_MIDNIGHT,
        PREP_HOLD_ANTICOAGULANT,
    ], (
        "acknowledged codes are held in the order they were acknowledged, got "
        f"{second_code['acknowledged_prep_codes']}"
    )

    cleared = validate_success(
        api.review_clearance(
            case_id,
            factories.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            roster.nurse_headers,
        ),
        200,
    )
    assert_case_dimensions(cleared, CASE_DRAFT, CLEARANCE_CLEARED)
    assert_null_fields(cleared, "clearance_block_reason")


# ─── Cross-entity and temporal boundaries ──────────────────────────────────
def test_referral_naming_a_case_that_has_not_completed_is_refused_then_accepted(api):
    """PRD 3.9: "A referral may also be direct, with `source_case_id` null; but
    when a source case *is* named it must have reached `schedule_status`
    `COMPLETED`, and naming a case that has not is refused with
    `ERR_SOURCE_CASE_NOT_COMPLETED`."
    PRD 3.9: "The new referral starts at `status` `REQUESTED` with
    `visits_authorized`, `visits_used`, `visits_remaining` and `visits_forfeited`
    all 0, and with `waitlist_position`, `therapy_start_by`, `first_visit_date`
    and `decline_reason` all null."

    Design: Corner/validations/val_cross_entity_validation_referral_source_case_not_completed
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, full_name="Omar Sill", date_of_birth="1974-04-04", egfr=85
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    cysto_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, "2026-09-15T09:00:00.000Z")
    case = fx.schedule_new_case(
        api, roster, patient, cysto_type, room, "2026-09-15T09:00:00.000Z"
    )
    assert case["schedule_status"] == CASE_SCHEDULED, (
        "precondition: the source case must be merely booked, not completed, got "
        f"{case['schedule_status']!r}"
    )

    request_body = factories.referral_payload(
        patient_id=patient["id"],
        source_case_id=case["id"],
        program=PROGRAM_BIOFEEDBACK,
        requested_visits=4,
    )

    too_soon = api.create_pelvic_health_referral(request_body, roster.urologist_headers)
    validate_error(too_soon, ERR_SOURCE_CASE_NOT_COMPLETED)

    referrals, meta = validate_paginated(
        api.list_pelvic_health_referrals(
            roster.coordinator_headers, patient_id=patient["id"]
        )
    )
    assert meta["total_count"] == 0, (
        "a refused referral must not have been persisted, got total_count "
        f"{meta['total_count']}"
    )
    assert referrals == [], f"expected no referral rows, got {referrals}"

    fx.clear_case(api, roster, case["id"])
    fx.check_in_case(api, roster, case["id"])
    fx.complete_case(api, roster, case["id"], headers=roster.urologist_headers)

    accepted_now = validate_success(
        api.create_pelvic_health_referral(request_body, roster.urologist_headers), 201
    )
    assert_fields(
        accepted_now,
        status=REFERRAL_REQUESTED,
        program=PROGRAM_BIOFEEDBACK,
        requested_visits=4,
        source_case_id=case["id"],
    )
    assert_visit_counters(accepted_now, authorized=0, used=0, remaining=0, forfeited=0)
    assert_null_fields(
        accepted_now,
        "waitlist_position",
        "therapy_start_by",
        "first_visit_date",
        "decline_reason",
    )


def test_no_show_is_refused_at_the_grace_instant_and_accepted_one_minute_later(api):
    """PRD 2.8: "The logical clock is strictly after the case's
    `scheduled_start_at` plus the 15-minute grace allowance. Otherwise
    `ERR_NO_SHOW_GRACE_NOT_ELAPSED`, HTTP 422. Applies to no-show marking only."
    PRD 3.3: "It may not be exercised early: the logical clock must be *strictly
    after* `scheduled_start_at` plus the fifteen-minute grace allowance, and an
    attempt at or before that instant is refused with
    `ERR_NO_SHOW_GRACE_NOT_ELAPSED`."
    PRD 3.3: "The case's `cancel_reason_code` is then set to the constant string
    `NO_SHOW_GRACE_ELAPSED` — the client does not supply it."
    PRD 3.3: "Antibiotic orders in `ORDERED` are likewise cancelled, the room's
    `version` is incremented by 1 and its `occupied_block_count` recomputed, and
    the case's `blocking_reason_codes` collapses to the empty array."

    Design: Corner/validations/val_temporal_validation_no_show_grace_strictly_after
    """
    roster = fx.build_roster(api)
    patient = fx.create_patient(
        api, roster.urologist, full_name="Vera Lund", date_of_birth="1965-09-09", egfr=90
    )
    room = fx.create_room(
        api, ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
    )
    cysto_type = fx.create_procedure_type(
        api,
        TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )

    fx.set_clock(api, "2026-09-14T08:00:00.000Z")
    case = fx.schedule_new_case(
        api, roster, patient, cysto_type, room, "2026-09-14T09:00:00.000Z"
    )
    room_while_booked = fx.read_room(api, roster, room["id"])
    assert room_while_booked["occupied_block_count"] == 1, (
        "precondition: a booked case occupies exactly one block of its room, got "
        f"{room_while_booked['occupied_block_count']}"
    )

    # 09:15 is scheduled_start_at plus the grace allowance exactly, and the rule
    # demands an instant strictly after it.
    fx.set_clock(api, "2026-09-14T09:15:00.000Z")
    at_the_grace_instant = api.no_show_case(case["id"], {}, roster.scheduler_headers)
    validate_error(at_the_grace_instant, ERR_NO_SHOW_GRACE_NOT_ELAPSED)

    still_booked = fx.read_case(api, roster, case["id"])
    assert still_booked["schedule_status"] == CASE_SCHEDULED, (
        "a refused no-show must leave the case booked, got "
        f"{still_booked['schedule_status']!r}"
    )
    room_after_refusal = fx.read_room(api, roster, room["id"])
    assert_fields(room_after_refusal, occupied_block_count=1)
    assert_version_unchanged(room_while_booked, room_after_refusal)

    fx.set_clock(api, "2026-09-14T09:16:00.000Z")
    no_showed = validate_success(
        api.no_show_case(case["id"], {}, roster.scheduler_headers), 200
    )
    assert_fields(
        no_showed,
        schedule_status=CASE_NO_SHOW,
        cancel_reason_code=NO_SHOW_CANCEL_REASON_CODE,
        blocking_reason_codes=[],
    )

    room_after_no_show = fx.read_room(api, roster, room["id"])
    assert_fields(room_after_no_show, occupied_block_count=0)
    assert_version_advanced(room_while_booked, room_after_no_show)
