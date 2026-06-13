"""Dunning: pause-window buffer conflict, the CURRENT->DUNNING bubble, notice
reverse-reachability, and pause-suppressed runs.

Queue A (Difficulty): closed-window-with-1-day-buffer pause conflict (and a
clear-of-buffer pause allowed). Queue B (Corner): dunning run bubbles stage to
DUNNING, notice discoverable via reverse GET, run skips invoice under active
pause.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_customer,
    create_invoice,
    create_dunning_sequence,
    run_dunning,
    create_pause,
    create_dunning_pause_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — closed pause window with 1-day buffer
# --------------------------------------------------------------------------- #
def test_pause_window_within_buffer_conflict(api, collections_agent_headers):
    """PRD §3.7: "A new pause must keep a one-day buffer from every existing
    pause for that customer: any two windows for the same customer whose gap is
    one day or less, inclusive, collide, and the new pause is rejected with
    `ERR_PAUSE_WINDOW_CONFLICT` (HTTP 409)."

    A pause beginning 2026-07-11 — one day after a prior pause ending
    2026-07-10 — is inside the buffer and rejected.

    Design: Difficulty/resource_temporal_overlap/dunning_pause_window_closed_with_buffer_conflict_rejected
    """
    customer = create_customer(name="DP")
    create_pause(customer["id"], "2026-07-01T00:00:00Z", "2026-07-10T00:00:00Z")
    res = api.create_dunning_pause(
        create_dunning_pause_payload(
            customer["id"],
            pause_start="2026-07-11T00:00:00Z",
            pause_end="2026-07-15T00:00:00Z",
        ),
        collections_agent_headers,
    )
    validate_error(res, "ERR_PAUSE_WINDOW_CONFLICT")


def test_pause_window_clear_of_buffer_allowed(api, collections_agent_headers):
    """PRD §3.7: "A new pause must keep a one-day buffer from every existing
    pause for that customer: any two windows for the same customer whose gap is
    one day or less, inclusive, collide, and the new pause is rejected with
    `ERR_PAUSE_WINDOW_CONFLICT` (HTTP 409)."

    A pause beginning 2026-07-13 — three days after a prior pause ending
    2026-07-10 — clears the one-day buffer, so the create succeeds.

    Design: Difficulty/resource_temporal_overlap/dunning_pause_window_closed_with_buffer_conflict_rejected
    """
    customer = create_customer(name="DPok")
    create_pause(customer["id"], "2026-07-01T00:00:00Z", "2026-07-10T00:00:00Z")
    res = api.create_dunning_pause(
        create_dunning_pause_payload(
            customer["id"],
            pause_start="2026-07-13T00:00:00Z",
            pause_end="2026-07-15T00:00:00Z",
        ),
        collections_agent_headers,
    )
    pause = validate_success(res, 201)
    assert pause["customer_id"] == customer["id"]


# --------------------------------------------------------------------------- #
# Queue B — corner cases
# --------------------------------------------------------------------------- #
def test_dunning_run_bubbles_collection_stage_to_dunning(api, ar_manager_headers, collections_agent_headers):
    """PRD §3.7: "when it emits the first notice for an overdue invoice it moves
    the customer's `collection_stage` from `CURRENT` to `DUNNING`; this requires
    at least one invoice to have reached `B1_30` or worse with no active pause
    suppressing it."

    Design: Corner/state_machines/dunning_run_bubbles_collection_stage_to_dunning
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer(name="BU")
    create_invoice(
        customer["id"], face_amount_cents=5000,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-03-15T00:00:00Z",
    )  # ~17 days overdue -> B1_30
    sequence = create_dunning_sequence(name="S")
    run_dunning(customer["id"], sequence["id"])
    after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert after["collection_stage"] == "DUNNING"


def test_dunning_notice_discoverable_via_reverse_get(api, ar_manager_headers, collections_agent_headers):
    """PRD §3.7: "The run emits a **DunningNotice** for each eligible invoice...
    Each notice records the targeted `invoice_id`, the `sequence_id` that
    produced it, the 1-based `step_index` of the step that fired".
    PRD §3.7: "Notices for an invoice can be listed under that invoice".

    Design: Corner/entities/dunning_notice_discoverable_only_via_reverse_get
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer(name="DN")
    invoice = create_invoice(
        customer["id"], face_amount_cents=5000,
        invoice_date="2026-01-01T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    sequence = create_dunning_sequence(name="S")
    run_dunning(customer["id"], sequence["id"])
    res = api.list_invoice_dunning_notices(invoice["id"], collections_agent_headers)
    data, _meta = validate_paginated(res)
    assert len(data) >= 1
    assert data[0]["step_index"] == 1


def test_dunning_run_skips_invoice_under_active_pause(api, ar_manager_headers, collections_agent_headers):
    """PRD §3.7: "The run emits a **DunningNotice** for each eligible invoice,
    skipping any invoice that falls under an active dunning pause."
    PRD §3.7: "when it emits the first notice for an overdue invoice it moves the
    customer's `collection_stage` from `CURRENT` to `DUNNING`".

    With an ACTIVE pause covering today the overdue invoice is skipped, no notice
    is emitted, and the stage stays CURRENT.

    Design: Corner/endpoints/dunning_run_skips_invoice_under_active_pause
    """
    set_clock("2026-05-10T00:00:00Z")
    customer = create_customer(name="PZ")
    create_invoice(
        customer["id"], face_amount_cents=5000,
        invoice_date="2026-02-01T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    create_pause(customer["id"], "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z")  # ACTIVE
    sequence = create_dunning_sequence(name="S")
    notices = run_dunning(customer["id"], sequence["id"])
    assert len(notices) == 0
    after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert after["collection_stage"] == "CURRENT"
