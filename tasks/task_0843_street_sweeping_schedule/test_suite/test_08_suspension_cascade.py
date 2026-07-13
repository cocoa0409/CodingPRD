"""Suspension activation cascade and suspension-scope validation.

Translates the queue A (Difficulty) transitive_cascade suspension instance and the
queue B (Corner) suspension-scope validation instance.
"""
from test_helpers import (
    validate_success, validate_error,
    create_suspension_payload,
    TEST_USERS,
    setup_verified_block, create_sweep_event, set_clock, issue_citation,
    create_suspension, activate_suspension,
)

DISPATCHER = TEST_USERS["route_dispatcher_headers"]
ADMIN = TEST_USERS["public_works_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


def _setup_scheduled_sweep_with_tied_citation():
    """Verified block + a SCHEDULED sweep on 2026-03-10 + an ISSUED citation tied to
    that sweep + a SCHEDULED ROUTE suspension covering 2026-03-09..03-11."""
    route, block = setup_verified_block(restriction_start_local="08:00", restriction_end_local="10:00")
    ev = create_sweep_event(block["id"], scheduled_date="2026-03-10",
                            window_start_utc="2026-03-10T08:00:00Z", window_end_utc="2026-03-10T10:00:00Z")
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    cit = issue_citation(block["id"], plate="SUS777", scanned_at_utc="2026-03-10T08:30:00Z",
                         sweep_event_id=ev["id"])
    sus = create_suspension(reason="HOLIDAY", scope="ROUTE", route_id=route["id"],
                            start_date="2026-03-09", end_date="2026-03-11")
    return route, block, ev, cit, sus


def test_activate_suspends_scheduled_sweep_and_counts_it(api):
    """PRD §3.6: "For every sweep event that is currently `SCHEDULED`, whose `scheduled_date` falls on or between the suspension's `start_date` and `end_date`, and that is in scope — meaning the suspension is `SYSTEM`-scoped, or the event's block belongs to the suspension's `route_id` — the event is transitioned `SCHEDULED → SUSPENDED`. The count of events moved this way is written to `suspended_event_count`."

    Design: Difficulty/transitive_cascade/suspension_activate_suspends_event_dismisses_citation
    """
    route, block, ev, cit, sus = _setup_scheduled_sweep_with_tied_citation()
    activated = activate_suspension(sus["id"])
    assert activated["suspended_event_count"] == 1
    ev_after = validate_success(api.get_sweep_event(ev["id"], DISPATCHER), 200)
    assert ev_after["status"] == "SUSPENDED"


def test_activate_dismisses_tied_citation_and_debits_block(api):
    """PRD §3.6: "As the second hop, each newly suspended event dismisses any citation tied to it: for every citation whose `sweep_event_id` equals the suspended event and whose status is `ISSUED`, the citation transitions `ISSUED → DISMISSED`. As the third hop, each such dismissal subtracts that citation's `amount_due_cents` from its block's `pending_citation_cents`, per §2.10."

    Design: Difficulty/transitive_cascade/suspension_activate_suspends_event_dismisses_citation
    """
    route, block, ev, cit, sus = _setup_scheduled_sweep_with_tied_citation()
    activate_suspension(sus["id"])
    cit_after = validate_success(api.get_citation(cit["id"], OFFICER), 200)
    assert cit_after["status"] == "DISMISSED"
    block_after = validate_success(api.get_block(block["id"], OFFICER), 200)
    assert block_after["pending_citation_cents"] == 0


def test_route_scope_without_route_id_rejected(api):
    """PRD §3.6: "When `scope` is `ROUTE` a `route_id` is required, and when `scope` is `SYSTEM` a `route_id` must not be supplied; violating this shape is rejected with `ERR_SUSPENSION_SCOPE_INVALID`."

    Design: Corner/validations/suspension_scope_route_without_route_id_returns_422
    """
    payload = create_suspension_payload(reason="HOLIDAY", scope="ROUTE",
                                        start_date="2026-03-10", end_date="2026-03-11")
    payload.pop("route_id", None)
    res = api.create_suspension(payload, ADMIN)
    validate_error(res, "ERR_SUSPENSION_SCOPE_INVALID", expected_status=422)
