"""Cross-cutting claims: optimistic concurrency, cascade version semantics,
sanction clearing, and immediate read-after-write consistency (PRD 2.8, 2.10,
3.1, 3.2, 3.8)."""
from test_helpers import (
    ApiErrorId,
    close_complaint,
    confirm_appointment,
    create_appraiser,
    create_client,
    create_complaint,
    create_fee_schedule_payload,
    create_membership,
    create_revision_request,
    draft_complaint,
    get_client,
    get_order,
    get_scorecard,
    set_clock,
    setup_assigned_order,
    setup_delivered_order,
    submit_complaint,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN
from test_helpers.fixtures import create_appointment


def test_occ_stale_order_version_on_revision_create(api):
    """PRD 2.8: "Creating a revision request — `POST
    /appraisal/orders/{id}/revision-requests` — requires the request body to
    carry `expected_order_version`, holding the order `version` the caller
    last observed. If that value does not equal the order's current `version`
    at the time of the write — for example because another writer has since
    created a revision request on the same order, legitimately superseding the
    previously open one and advancing the order's version — the request is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), protecting the caller
    from acting on a view of the order it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_order_version_on_revision_create
    """
    ctx = setup_delivered_order()
    observed = get_order(ctx["order"]["id"])["version"]

    first = validate_success(
        api.create_revision_request(
            ctx["order"]["id"],
            {
                "kind": "CORRECTION",
                "detail": "first writer",
                "expected_order_version": observed,
            },
            ctx["client_headers"],
        ),
        201,
    )
    assert first["status"] == "OPEN"

    stale = api.create_revision_request(
        ctx["order"]["id"],
        {
            "kind": "CORRECTION",
            "detail": "stale second writer",
            "expected_order_version": observed,
        },
        ctx["client_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION, 412)

    # the stale write never happened: the first request was not superseded
    rr1 = validate_success(api.get_revision_request(first["id"], ADMIN), 200)
    assert rr1["status"] == "OPEN"


def test_occ_stale_client_version_on_schedule_create(api):
    """PRD 2.8: "Creating a fee schedule — `POST /appraisal/fee-schedules` —
    likewise requires `expected_client_version` matching the client record's
    current `version`. Because creating a schedule legitimately closes the
    prior open-ended window for that client and tier and advances the client's
    `version`, a caller working from a stale view of the client is rejected
    with `ERR_STALE_CLIENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_client_version_on_schedule_create
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    observed = client["version"]

    first = validate_success(
        api.create_fee_schedule(
            create_fee_schedule_payload(client["id"], observed), ADMIN
        ),
        201,
    )
    assert first["client_id"] == client["id"]

    stale = api.create_fee_schedule(
        create_fee_schedule_payload(
            client["id"], observed, complexity_tier="COMPLEX", base_fee_cents=60000
        ),
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CLIENT_VERSION, 412)


def test_order_version_increments_on_cascade_side_effect(api):
    """PRD 2.10: "Every transition of an order, whether operator-invoked or
    system-invoked, increments the order's `version` by exactly one and
    refreshes its `updated_at`".
    PRD 3.4: "The first confirmation for an order automatically advances the
    order from `ASSIGNED` to `INSPECTION_SCHEDULED`."

    Design: Corner/cross_cutting_layers/order_version_increments_on_cascade_side_effect
    """
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    appointment = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )
    before = get_order(ctx["order"]["id"])["version"]

    confirm_appointment(appointment["id"], ctx["appraiser"]["id"])

    after = get_order(ctx["order"]["id"])
    assert after["version"] == before + 1, "cascade bumps the order version by one"
    assert after["status"] == "INSPECTION_SCHEDULED"


def test_clear_sanction_restores_standing_without_restoring_memberships(api):
    """PRD 3.2: "When a board sanction has run its course, a `FirmAdmin`
    clears it: the appraiser's `sanction_override` flips to false and
    `standing` recomputes under the ordinary ladder above. Clearing a sanction
    restores nothing the cascade took — `REMOVED` memberships stay removed,
    and orders unassigned by the cascade stay unassigned until a fresh
    assignment is made."

    Design: Corner/cross_cutting_layers/clear_sanction_restores_standing_without_restoring_memberships
    """
    ctx = setup_delivered_order()
    membership = ctx["membership"]
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])
    draft_complaint(complaint["id"])
    submit_complaint(complaint["id"])
    close_complaint(complaint["id"], "SANCTIONED")

    validate_success(api.clear_sanction(ctx["appraiser"]["id"], ADMIN), 200)

    scorecard = get_scorecard(ctx["appraiser"]["id"])
    assert scorecard["sanction_override"] is False
    # one on-time completion, below the four-completion rating threshold
    assert scorecard["standing"] == "GOOD_STANDING"

    membership_after = validate_success(
        api.get_panel_membership(membership["id"], ADMIN), 200
    )
    assert membership_after["status"] == "REMOVED"


def test_immediate_consistency_read_after_write(api):
    """PRD 3.1: "From there the firm may suspend an `ACTIVE` client, moving it
    to `SUSPENDED`".
    PRD 2.10: "State changes propagate across entity boundaries."
    PRD 2.10: "These system-driven transitions are part of the same write
    that triggered them — no separate client call is needed or possible for
    the propagated change."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    validate_success(api.suspend_client(client["id"], ADMIN), 200)

    fetched = get_client(client["id"])
    assert fetched["status"] == "SUSPENDED", "the very next read observes the write"
