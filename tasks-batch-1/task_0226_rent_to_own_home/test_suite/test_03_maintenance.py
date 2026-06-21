"""Maintenance tickets and the clean threshold split between tenant and landlord."""

from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_maintenance_split_conserved,
    create_active_agreement,
    file_ticket,
    approve_ticket,
    resolve_ticket,
    setup_approved_ticket,
    make_landlord_headers,
    make_tenant_headers,
)


def test_estimate_split_then_actual_split_overrides(api):
    """PRD §3.5: "it transitions the ticket `OPEN → APPROVED` and computes the cost
    split from the **estimate**."
    PRD §3.5: "transitions the ticket `APPROVED → RESOLVED`, and recomputes the split
    from the **actual** cost, overriding the provisional estimate-based split."
    PRD §3.5: "the landlord's portion, `landlord_share_cents`, is the cost minus the
    threshold but never below zero."

    Design: Difficulty/dual_variant_calc/dvc_maintenance_estimate_vs_actual_split
    """
    landlord, tenant, prop, agreement, ticket = setup_approved_ticket(
        estimated_cost_cents=80000, maintenance_threshold_cents=50000
    )
    assert ticket["landlord_share_cents"] == 30000, (
        f"estimate split (80000-50000) must be 30000, got {ticket['landlord_share_cents']}"
    )
    resolved = resolve_ticket(landlord, ticket, 120000)
    assert resolved["landlord_share_cents"] == 70000, (
        f"actual split (120000-50000) must be 70000, got {resolved['landlord_share_cents']}"
    )
    assert resolved["tenant_share_cents"] == 50000, resolved["tenant_share_cents"]


def test_estimate_split_at_approval(api):
    """PRD §3.5: "it transitions the ticket `OPEN → APPROVED` and computes the cost
    split from the **estimate**."
    PRD §3.5: "the tenant's portion, `tenant_share_cents`, is the smaller of that cost
    and the threshold, and the landlord's portion, `landlord_share_cents`, is the cost
    minus the threshold but never below zero."

    Design: Difficulty/dual_variant_calc/dvc_maintenance_estimate_vs_actual_split
    """
    landlord, tenant, prop, agreement, ticket = setup_approved_ticket(
        estimated_cost_cents=80000, maintenance_threshold_cents=50000
    )
    assert ticket["tenant_share_cents"] == 50000, (
        f"estimate split tenant share min(80000,50000) must be 50000, got {ticket['tenant_share_cents']}"
    )
    assert ticket["landlord_share_cents"] == 30000, ticket["landlord_share_cents"]


def test_maintenance_cost_fully_allocated_no_drift(api):
    """PRD §3.5: "the tenant's portion, `tenant_share_cents`, is the smaller of that
    cost and the threshold, and the landlord's portion, `landlord_share_cents`, is
    the cost minus the threshold but never below zero. By construction the two shares
    always sum exactly to the full cost, with no rounding and no drift."

    Design: Difficulty/compensating_invariant/ci_maintenance_cost_fully_allocated_conserved
    """
    landlord, tenant, prop, agreement, ticket = setup_approved_ticket(
        estimated_cost_cents=80000, maintenance_threshold_cents=50000
    )
    resolved = resolve_ticket(landlord, ticket, 120000)
    assert resolved["tenant_share_cents"] == 50000, resolved["tenant_share_cents"]
    assert resolved["landlord_share_cents"] == 70000, resolved["landlord_share_cents"]
    assert_maintenance_split_conserved(resolved, 120000)


def test_maintenance_cost_conserved_below_threshold(api):
    """PRD §3.5: "By construction the two shares always sum exactly to the full cost,
    with no rounding and no drift."

    Design: Difficulty/compensating_invariant/ci_maintenance_cost_fully_allocated_conserved
    """
    landlord, tenant, prop, agreement, ticket = setup_approved_ticket(
        estimated_cost_cents=40000, maintenance_threshold_cents=50000
    )
    resolved = resolve_ticket(landlord, ticket, 30000)
    assert resolved["tenant_share_cents"] == 30000, resolved["tenant_share_cents"]
    assert resolved["landlord_share_cents"] == 0, resolved["landlord_share_cents"]
    assert_maintenance_split_conserved(resolved, 30000)


def test_resolve_below_threshold_landlord_share_zero(api):
    """PRD §3.5: "the tenant's portion, `tenant_share_cents`, is the smaller of that
    cost and the threshold, and the landlord's portion, `landlord_share_cents`, is
    the cost minus the threshold but never below zero."

    Design: Corner/state_machines/sm_resolve_ticket_below_threshold_landlord_zero
    """
    landlord, tenant, prop, agreement, ticket = setup_approved_ticket(
        estimated_cost_cents=40000, maintenance_threshold_cents=50000
    )
    resolved = resolve_ticket(landlord, ticket, 30000)
    assert resolved["tenant_share_cents"] == 30000, resolved["tenant_share_cents"]
    assert resolved["landlord_share_cents"] == 0, resolved["landlord_share_cents"]


def test_maintenance_split_at_exact_threshold(api):
    """PRD §3.5: "the tenant's portion, `tenant_share_cents`, is the smaller of that
    cost and the threshold, and the landlord's portion, `landlord_share_cents`, is
    the cost minus the threshold but never below zero."

    Design: Corner/calculations/calc_maintenance_at_threshold_boundary
    """
    landlord, tenant, prop, agreement, ticket = setup_approved_ticket(
        estimated_cost_cents=50000, maintenance_threshold_cents=50000
    )
    resolved = resolve_ticket(landlord, ticket, 50000)
    assert resolved["tenant_share_cents"] == 50000, resolved["tenant_share_cents"]
    assert resolved["landlord_share_cents"] == 0, resolved["landlord_share_cents"]


def test_reject_open_ticket_terminal(api):
    """PRD §3.5: "Rejection is also permitted only on an `OPEN` ticket ... it
    transitions `OPEN → REJECTED` and is terminal."

    Design: Corner/state_machines/sm_reject_ticket_from_open
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    ticket = file_ticket(tenant, agreement, summary="Leak", estimated_cost_cents=40000)
    res = api.reject_maintenance_ticket(ticket["id"], make_landlord_headers(landlord["id"]))
    data = validate_success(res, expected_status=200)
    assert data["status"] == "REJECTED", f"reject must yield REJECTED, got {data['status']}"


def test_approve_non_open_ticket_rejected(api):
    """PRD §3.5: "Approval is permitted only on an `OPEN` ticket (otherwise
    `ERR_TICKET_NOT_OPEN`)".

    Design: Corner/errors/err_ticket_not_open_on_approve
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    ticket = file_ticket(tenant, agreement, summary="Door", estimated_cost_cents=10000)
    get_success_data(
        api.reject_maintenance_ticket(ticket["id"], make_landlord_headers(landlord["id"]))
    )
    res = api.approve_maintenance_ticket(ticket["id"], make_landlord_headers(landlord["id"]))
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_OPEN.value)


def test_resolve_non_approved_ticket_rejected(api):
    """PRD §3.5: "Resolution acts only on an `APPROVED` ticket (otherwise
    `ERR_TICKET_NOT_APPROVED`)".

    Design: Corner/errors/err_ticket_not_approved_on_resolve
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    ticket = file_ticket(tenant, agreement, summary="Window", estimated_cost_cents=20000)
    res = api.resolve_maintenance_ticket(
        ticket["id"], {"actual_cost_cents": 20000}, make_landlord_headers(landlord["id"])
    )
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_APPROVED.value)
