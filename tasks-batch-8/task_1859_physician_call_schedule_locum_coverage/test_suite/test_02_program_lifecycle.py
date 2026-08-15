"""Program lifecycle transitions: generate/publish preconditions, OCC-guarded
regeneration, and the regenerate progress lock."""
from test_helpers import (
    ApiErrorId,
    assert_call_program,
    create_draft_program,
    create_generated_program,
    create_staff_physician,
    generate_program,
    get_program,
    list_assignments,
    serve_assignment,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_generate_from_generated_returns_invalid_state(api):
    """PRD §3.1: "Generation turns a DRAFT program into a GENERATED one;
    attempting it in any other phase is `ERR_PROGRAM_NOT_DRAFT`."

    Design: Corner/state_machines/generate_from_generated_returns_invalid_state
    """
    program = create_generated_program()
    resp = api.generate_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_DRAFT, 409)
    after = get_program(program["id"])
    assert after["status"] == "GENERATED"


def test_publish_from_draft_rejected(api):
    """PRD §3.1: "Publication moves the program from GENERATED to PUBLISHED
    (`ERR_PROGRAM_NOT_GENERATED` otherwise)".

    Design: Corner/state_machines/publish_from_draft_rejected
    """
    program = create_draft_program()
    resp = api.publish_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_GENERATED, 409)
    after = get_program(program["id"])
    assert after["status"] == "DRAFT"


def test_occ_regenerate_stale_version_rejected(api):
    """PRD §2.10: "The request must carry `expected_call_program_version`, holding
    the program's `version` as the client last observed it. If another writer has
    advanced the program's version since that read — most commonly by
    regenerating, which legitimately supersedes the prior slot and assignment
    set — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_regenerate_stale_version_rejected
    """
    program = create_draft_program(name="Cards OCC")
    assert program["version"] == 1
    generated = generate_program(program["id"])
    assert generated["version"] == 2

    # First regenerate with the observed version succeeds.
    resp = api.regenerate_program(program["id"], generated["version"], ADMIN)
    regenerated = validate_success(resp, 200)
    assert_call_program(regenerated)
    assert regenerated["version"] == 3
    assert regenerated["status"] == "GENERATED"

    # The same (now stale) version is rejected on the strictly sequential retry.
    resp = api.regenerate_program(program["id"], generated["version"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    # The failed regenerate changed nothing.
    after = get_program(program["id"])
    assert after["version"] == 3
    assert after["status"] == "GENERATED"


def test_regenerate_with_served_assignment_rejected(api):
    """PRD §3.1: "It requires the program to be GENERATED
    (`ERR_PROGRAM_NOT_GENERATED`), requires that no assignment in the program be
    ACTIVATED or SERVED (`ERR_REGENERATE_HAS_PROGRESS`)".

    Design: Corner/errors/regenerate_with_served_assignment_rejected
    """
    # Register the physician BEFORE generation so auto-assignment fills the slot.
    program = create_draft_program(name="Cards")
    physician = create_staff_physician("Dr A")
    generated = generate_program(program["id"])

    assignments = list_assignments(program_id=program["id"])
    assert len(assignments) == 1, "generation must auto-assign the only slot"
    assignment = assignments[0]
    assert assignment["origin"] == "GENERATED"
    assert assignment["physician_id"] == physician["id"]

    # Serve the assignment (window ends 2026-09-09T07:00:00Z), creating progress.
    set_clock("2026-09-09T08:00:00Z")
    serve_assignment(assignment["id"])

    # Regenerate is blocked by the SERVED assignment even with the observed
    # version from generation time — the progress check is a state precondition.
    resp = api.regenerate_program(program["id"], generated["version"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REGENERATE_HAS_PROGRESS, 409)
