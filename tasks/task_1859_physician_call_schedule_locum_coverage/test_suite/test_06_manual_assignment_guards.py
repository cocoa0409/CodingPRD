"""Manual assignment (backfill) guards: program phase, slot state, physician
activity, unavailability conflicts, employment type, and the immediate
visibility of creation side effects."""
from test_helpers import (
    ApiErrorId,
    assign_staff,
    create_approved_window,
    create_draft_program,
    create_locum_physician,
    create_published_program,
    create_staff_physician,
    create_window,
    generate_program,
    get_program,
    get_slot_for_date,
    list_assignments,
    list_gaps,
    set_clock,
    setup_published_with_assignment,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Cross-entity state dependency: assignment requires PUBLISHED ─────

def test_manual_assignment_requires_program_published_rejected(api):
    """PRD §3.1: "Publication moves the program from GENERATED to PUBLISHED
    (`ERR_PROGRAM_NOT_GENERATED` otherwise) and unlocks the operational phase:
    manual assignments and the swap marketplace exist only against PUBLISHED
    programs."
    PRD §3.3: "the program must be PUBLISHED (`ERR_PROGRAM_NOT_PUBLISHED`) and
    the slot OPEN (`ERR_SLOT_NOT_OPEN`)".

    Design: Difficulty/cross_entity_state_dependency/manual_assignment_requires_program_published
    """
    program = create_draft_program(name="Cards Unpublished")
    generate_program(program["id"])  # GENERATED, never published
    physician = create_staff_physician("Dr Alvarez")
    slot = get_slot_for_date(program["id"], "2026-09-08")

    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": physician["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED, 409)


def test_manual_assignment_requires_program_published_no_side_effects(api):
    """PRD §3.1: "manual assignments and the swap marketplace exist only against
    PUBLISHED programs."
    PRD §3.3: "On creation the slot moves OPEN → ASSIGNED" — so a rejected
    creation must leave the slot OPEN with no assignment created.

    Design: Difficulty/cross_entity_state_dependency/manual_assignment_requires_program_published
    """
    program = create_draft_program(name="Cards Unpublished")
    generate_program(program["id"])
    physician = create_staff_physician("Dr Alvarez")
    slot = get_slot_for_date(program["id"], "2026-09-08")

    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": physician["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED, 409)

    slot_after = validate_success(api.get_slot(slot["id"], ADMIN))
    assert slot_after["status"] == "OPEN"
    assert list_assignments(slot_id=slot["id"]) == []


# ─── Slot-state and temporal guards ──────────────────────────────────

def test_assign_to_occupied_slot_returns_slot_not_open(api):
    """PRD §3.3: "the program must be PUBLISHED (`ERR_PROGRAM_NOT_PUBLISHED`) and
    the slot OPEN (`ERR_SLOT_NOT_OPEN`)".

    Design: Corner/errors/assign_to_occupied_slot_returns_slot_not_open
    """
    program, _p1, slot, _a1 = setup_published_with_assignment()
    p2 = create_staff_physician("Dr B")
    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": p2["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN, 409)


def test_assign_to_past_slot_rejected(api):
    """PRD §3.3: "and the slot window must not already have ended
    (`ERR_SLOT_WINDOW_PASSED`)".

    Design: Corner/validations/assign_to_past_slot_rejected
    """
    program = create_published_program()  # slot stays OPEN (no physicians yet)
    physician = create_staff_physician("Dr A")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    set_clock("2026-09-10T00:00:00Z")  # window ended 2026-09-09T07:00:00Z
    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": physician["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_PASSED, 409)
    slot_after = validate_success(api.get_slot(slot["id"], ADMIN))
    assert slot_after["status"] == "OPEN"


# ─── Physician-state and employment guards ───────────────────────────

def test_assignment_on_approved_unavailable_date_rejected(api):
    """PRD §3.3: "no APPROVED unavailability window of the physician may cover
    the slot date (`ERR_UNAVAILABILITY_CONFLICT`)".

    Only APPROVED windows block: a merely REQUESTED window over a different
    date does not prevent assignment.

    Design: Corner/errors/assignment_on_approved_unavailable_date_rejected
    """
    program = create_published_program(
        period_start="2026-09-08", period_end="2026-09-09"
    )
    physician = create_staff_physician("Dr A")
    create_approved_window(
        physician["id"], start_date="2026-09-08", end_date="2026-09-08"
    )
    create_window(physician["id"], start_date="2026-09-09", end_date="2026-09-09",
                  kind="CME")

    slot_approved = get_slot_for_date(program["id"], "2026-09-08")
    resp = api.create_assignment(
        {"slot_id": slot_approved["id"], "physician_id": physician["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_UNAVAILABILITY_CONFLICT, 409)

    slot_requested = get_slot_for_date(program["id"], "2026-09-09")
    accepted = assign_staff(slot_requested["id"], physician["id"])
    assert accepted["status"] == "SCHEDULED"


def test_assign_inactive_physician_rejected(api):
    """PRD §3.3: "the physician must be ACTIVE (`ERR_PHYSICIAN_INACTIVE`)".

    Design: Corner/errors/assign_inactive_physician_rejected
    """
    program = create_published_program()
    physician = create_staff_physician("Dr A")
    deactivated = validate_success(api.deactivate_physician(physician["id"], ADMIN))
    assert deactivated["status"] == "INACTIVE"

    slot = get_slot_for_date(program["id"], "2026-09-08")
    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": physician["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_INACTIVE, 409)


def test_manual_assignment_of_locum_rejected(api):
    """PRD §3.3: "a LOCUM physician is refused outright with
    `ERR_MANUAL_ASSIGNMENT_STAFF_ONLY`, because locums are placed only via the
    requisition flow."

    Design: Corner/errors/manual_assignment_of_locum_rejected
    """
    program = create_published_program()
    locum = create_locum_physician("Dr Locum")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": locum["id"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_MANUAL_ASSIGNMENT_STAFF_ONLY, 409)
    slot_after = validate_success(api.get_slot(slot["id"], ADMIN))
    assert slot_after["status"] == "OPEN"


# ─── Immediate consistency of creation side effects ──────────────────

def test_immediate_consistency_after_assignment_create(api):
    """PRD §3.3: "On creation the slot moves OPEN → ASSIGNED; the projected pay
    variant is computed — activation assumed absent, the premium tier evaluated
    on projected hours — and stored in `projected_pay_cents`; the reserve
    increases by that amount; and the program `version` increments. When the
    slot had an OPEN or REQUISITIONED coverage gap, the gap becomes RESOLVED
    with `resolved_by_assignment_id` set to the new assignment".

    Design: Corner/consistency_model/immediate_consistency_after_assignment_create
    """
    program = create_published_program()
    physician = create_staff_physician("Dr A")
    slot = get_slot_for_date(program["id"], "2026-09-08")

    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": physician["id"]}, ADMIN
    )
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "SCHEDULED"
    assert assignment["projected_pay_cents"] == 50000  # weekday primary base rate

    slot_after = validate_success(api.get_slot(slot["id"], ADMIN))
    assert slot_after["status"] == "ASSIGNED"

    program_after = get_program(program["id"])
    assert program_after["payroll_reserved_cents"] == 50000

    gaps = list_gaps(program["id"], slot_id=slot["id"])
    assert len(gaps) == 1
    assert gaps[0]["status"] == "RESOLVED"
    assert gaps[0]["resolved_by_assignment_id"] == assignment["id"]
