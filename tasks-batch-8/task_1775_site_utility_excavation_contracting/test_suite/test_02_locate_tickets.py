"""Locate ticket lifecycle: submit, clock-driven activation/expiry, renewal,
and the single-open-ticket rule."""

from test_helpers import (
    OPS_ADMIN,
    PROJECT_MANAGER,
    ApiErrorId,
    advance_clock,
    create_locate_ticket,
    create_project,
    get_ticket,
    validate_error,
    validate_success,
)

LEGAL_START = "2026-08-03T00:00:00Z"


def test_ticket_submit_then_clock_activation(api):
    """PRD §3.2: "The ticket is born `DRAFT`, with `renew_count` zero and a
    computed `valid_until` set exactly 672 hours — twenty-eight days — after
    `legal_start_at`."
    PRD §3.2: "Submitting moves the ticket `DRAFT → SUBMITTED` and re-checks
    that same exclusivity rule."
    PRD §3.2: "When the clock reaches `legal_start_at`, a `SUBMITTED` ticket
    becomes `ACTIVE`; when it reaches `valid_until`, a ticket in `ACTIVE` — or
    one still waiting in `SUBMITTED` — becomes `EXPIRED`."

    Design: Corner/state_machines/ticket_submit_valid_transition
    """
    project = create_project(name="P-TS", contract_ref="C-200")
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1", legal_start_at=LEGAL_START
    )
    assert ticket["status"] == "DRAFT"
    assert ticket["renew_count"] == 0
    assert ticket["valid_until"].startswith("2026-08-31T00:00:00"), (
        f"valid_until must be legal_start + 672h, got {ticket['valid_until']}"
    )

    submitted = validate_success(
        api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER)
    )
    assert submitted["status"] == "SUBMITTED"

    advance_clock(LEGAL_START)
    activated = get_ticket(ticket["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["valid_until"].startswith("2026-08-31T00:00:00")


def test_submit_expired_ticket_returns_invalid_state(api):
    """PRD §2.10: "Sixth, the target resource must be in a valid from-state
    for the requested transition, and a resource in a terminal state rejects
    every action, else `ERR_INVALID_STATE`."
    PRD §3.2: "Submitting moves the ticket `DRAFT → SUBMITTED` and re-checks
    that same exclusivity rule."

    Design: Corner/state_machines/submit_expired_ticket_returns_invalid_state
    """
    project = create_project(name="P-TE", contract_ref="C-201")
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1", legal_start_at=LEGAL_START
    )
    validate_success(api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))
    # valid_until == legal_start + 672h == 2026-08-31T00:00:00Z; past that the
    # still-SUBMITTED-then-ACTIVE ticket is EXPIRED.
    advance_clock(LEGAL_START)
    advance_clock("2026-09-01T00:00:00Z")
    assert get_ticket(ticket["id"])["status"] == "EXPIRED"

    response = api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_ticket(ticket["id"])["status"] == "EXPIRED"


def test_renew_expired_ticket_reactivates_when_validity_covers_now(api):
    """PRD §3.2: "A `ProjectManager` may renew a ticket, which extends
    `valid_until` by another 672 hours and increments `renew_count` by one."
    PRD §3.2: "Renewing an `EXPIRED` ticket returns it to `ACTIVE` only when
    the extended validity covers the current instant; if even the extended
    deadline lies in the past, the ticket stays `EXPIRED`, though
    `renew_count` still increments."

    Design: Corner/state_machines/ticket_renew_after_expiry_reactivates
    """
    project = create_project(name="P-RNW", contract_ref="C-207")
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1", legal_start_at=LEGAL_START
    )
    validate_success(api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))
    advance_clock(LEGAL_START)
    advance_clock("2026-09-01T00:00:00Z")
    assert get_ticket(ticket["id"])["status"] == "EXPIRED"

    renewed = validate_success(api.renew_locate_ticket(ticket["id"], PROJECT_MANAGER))
    assert renewed["status"] == "ACTIVE"
    assert renewed["renew_count"] == 1
    # 2026-08-31T00:00:00Z + 672h == 2026-09-28T00:00:00Z, which covers
    # the current instant (2026-09-01).
    assert renewed["valid_until"].startswith("2026-09-28T00:00:00"), (
        f"valid_until must extend by 672h, got {renewed['valid_until']}"
    )


def test_second_open_ticket_rejected(api):
    """PRD §3.2: "A project may have at most one open ticket: creation is
    rejected with `ERR_DUPLICATE_OPEN_TICKET` if the project already holds a
    ticket in `DRAFT`, `SUBMITTED`, or `ACTIVE`."

    Design: Corner/validations/duplicate_open_ticket_rejected
    """
    project = create_project(name="P-DT", contract_ref="C-410")
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1", legal_start_at=LEGAL_START
    )
    validate_success(api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))

    response = api.create_locate_ticket(
        {"project_id": project["id"], "ticket_number": "T-2",
         "legal_start_at": "2026-08-04T00:00:00Z"},
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_OPEN_TICKET, 409)
    assert get_ticket(ticket["id"])["status"] == "SUBMITTED"


def test_ticket_version_increments_on_each_mutation(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the resource
    is created and increments by one on every mutation. Mutations include
    user-driven actions, system-driven state transitions, and recomputations
    of derived fields"
    PRD §2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with
    three fractional digits; `updated_at` refreshes on every mutation of the
    resource."

    Design: Corner/entities/ticket_version_increments_on_mutation
    """
    project = create_project(name="P-SYS", contract_ref="C-103")
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-9", legal_start_at=LEGAL_START
    )
    assert ticket["version"] == 1
    created_at = ticket["created_at"]

    submitted = validate_success(
        api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER)
    )
    assert submitted["version"] == 2, (
        f"submit must advance version by exactly 1, got {submitted['version']}"
    )
    assert submitted["updated_at"] >= created_at
