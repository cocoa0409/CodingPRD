"""Validation-priority pairs — when a request fails multiple checks,
the priority ordering in PRD §2.9 dictates which error_id is returned."""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    create_work_order_payload,
    setup_pending_workorder,
    setup_two_sites_for_cross_site_test,
    validate_error,
)


# ---------------------------------------------------------------------------
# Pair: state (priority 5) vs business_safety/evidence (priority 8)
# ---------------------------------------------------------------------------
def test_accept_pending_reports_invalid_state_over_evidence(api,
                                                              site_manager_headers):
    """PRD §2.9: 'When a request can fail multiple checks, validations are
    evaluated in a fixed priority order so that the first failure
    determines the returned error_id. The order, from highest to lowest
    priority, is: ... (5) target resource state for the operation —
    ERR_INVALID_STATE; (6) equipment lifecycle gate ... (8)
    acceptance-evidence presence — ERR_EVIDENCE_MISSING'.

    A PENDING WO has no RepairRecord (cannot, since /complete has not
    happened) AND is in the wrong state for /accept. State (5) wins over
    evidence (8).
    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_evidence
    """
    bag = setup_pending_workorder()
    # /accept on PENDING — caller is responsible_user_id of equipment so
    # the responsible-owner check (priority 10) does not pre-empt; the
    # earlier state check (priority 5) wins.
    from test_helpers import make_site_manager_headers
    headers = make_site_manager_headers(bag["equipment"]["responsible_user_id"])
    res = api.accept_work_order(
        bag["site"]["id"], bag["work_order"]["id"], headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------------
# Pair: business_referential cross-site (priority 4) vs business_safety
# busy (priority 7).
# ---------------------------------------------------------------------------
def test_create_workorder_cross_site_template_reports_cross_site(
        api, dispatcher_headers):
    """PRD §2.9: '(4) cross-aggregate reference site match for
    equipment_id, template_id, plan_id, part_id, and similar —
    ERR_CROSS_SITE_REFERENCE; ... (7) equipment-busy gate —
    ERR_EQUIPMENT_BUSY'.

    A POST /work-orders that references a template owned by a different
    site, on an equipment that is already busy with an open WO, must
    surface ERR_CROSS_SITE_REFERENCE first (priority 4 < 7).
    # difficulty: priority_pair_validation_conflict/business_safety_busy_vs_business_referential_cross_site
    """
    bag = setup_two_sites_for_cross_site_test()
    res = api.create_work_order(
        bag["site_a"]["id"],
        create_work_order_payload(
            bag["equipment_a"]["id"],   # in site_a, currently busy
            bag["template_b"]["id"],    # in site_b — cross-site
        ),
        dispatcher_headers,
    )
    validate_error(res, "ERR_CROSS_SITE_REFERENCE", expected_status=422)


# ---------------------------------------------------------------------------
# 3.4 — work-order create on INSTALLED equipment → ERR_EQUIPMENT_LIFECYCLE.
# ---------------------------------------------------------------------------
def test_create_workorder_on_installed_equipment_rejected(api,
                                                            dispatcher_headers):
    """PRD §3.4: 'Equipment whose lifecycle_status is not in COMMISSIONED
    or IN_SERVICE cannot host new work and produces
    ERR_EQUIPMENT_LIFECYCLE'.
    # difficulty: cross_entity_state_dependency/workorder_start_requires_equipment_lifecycle
    """
    from test_helpers import (
        create_equipment, create_site, create_template,
    )
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")  # INSTALLED
    res = api.create_work_order(
        site["id"], create_work_order_payload(eq["id"], template["id"]),
        dispatcher_headers,
    )
    validate_error(res, "ERR_EQUIPMENT_LIFECYCLE", expected_status=409)


# ---------------------------------------------------------------------------
# RBAC ordering vs ownership: priority 2 (FORBIDDEN) precedes 11
# (FORBIDDEN_NOT_OWNER).
# ---------------------------------------------------------------------------
def test_role_check_precedes_ownership_check(api, plan_owner_headers):
    """PRD §2.9: '(2) RBAC role permission — ERR_FORBIDDEN; ... (11)
    work-order ownership match for technician transitions —
    ERR_FORBIDDEN_NOT_OWNER'.

    PlanOwner is not authorized to /start a WO; the role gate at priority
    2 must trigger ERR_FORBIDDEN before any ownership check.
    """
    bag = setup_pending_workorder()
    res = api.start_work_order(
        bag["site"]["id"], bag["work_order"]["id"], plan_owner_headers,
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
