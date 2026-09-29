"""
Requests whose legality is decided by the state of a *different* row: a
dispenser gated on its parent placement, and a retrieval gated on a sibling
ticket.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_OPEN_TICKET_BLOCKS_RETRIEVAL,
    ERR_PLACEMENT_NOT_INSTALLED,
)
from test_helpers.assertions import (
    assert_axes,
    assert_equipment_ledger,
    assert_instant_equals,
    assert_lockout,
)
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS, PLATFORM_ADMIN_HEADERS
from test_helpers.types import (
    DISPENSER_ACTIVE,
    DISPENSER_LOCKED_OUT,
    DISPENSER_REMOVED,
    LOCKOUT_AGREEMENT_ENDED,
    OP_OFFLINE,
    PLACEMENT_INSTALLED,
    PLACEMENT_PENDING_INSTALL,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    PLACEMENT_RETRIEVED,
    TICKET_CLOSED,
    TICKET_PENDING_VERIFICATION,
    VERDICT_PASS,
    VISIT_VERIFIED,
)


def _pending_install_with_both_products_covered(api):
    """
    One agreement covering DET-100 *and* SAN-200, so a product-coverage error can
    never stand in for the lifecycle error, and one placement left in
    PENDING_INSTALL.
    """
    base = X.program_base(api, with_sanitizer=True)
    placement = X.create_placement(api, base, asset_tag="AT-B01")
    assert_axes(placement, placement_status=PLACEMENT_PENDING_INSTALL)
    assert base["detergent_id"] in base["agreement"]["covered_product_ids"]
    assert base["sanitizer_id"] in base["agreement"]["covered_product_ids"]

    base["placement_id"] = placement["id"]
    return base


def _dispensers_on(api, placement_id, headers):
    rows, _meta = validate_paginated(
        api.list_dispensers(headers, {"placement_id": placement_id, "limit": 100})
    )
    return rows


def test_dispenser_is_refused_before_install_and_accepted_after(api):
    """
    The identical dispenser payload fails and then succeeds with nothing changed
    but the parent placement's lifecycle state, and the refused attempt leaves no
    dispenser row behind.

    PRD §3.4: "Once a placement is off `INSTALLED`, it accepts no telemetry: a
    reading submitted against a placement whose `placement_status` is
    `PENDING_INSTALL`, `RETRIEVAL_SCHEDULED`, `RETRIEVED` or `CANCELLED` is
    refused with `ERR_PLACEMENT_NOT_INSTALLED`. The same requirement governs
    fitting a dispenser and filing a service ticket."

    Design: Difficulty/cross_entity_state_dependency/dispenser_creation_gated_by_placement_lifecycle_state
    """
    base = _pending_install_with_both_products_covered(api)
    payload = F.dispenser_payload(base["placement_id"], base["detergent_id"], 8.00)

    validate_error(
        api.create_dispenser(payload, base["technician_headers"]),
        ERR_PLACEMENT_NOT_INSTALLED,
        409,
    )
    assert _dispensers_on(api, base["placement_id"], base["technician_headers"]) == []

    installed = X.install_placement(api, base, base["placement_id"])
    assert_axes(installed, placement_status=PLACEMENT_INSTALLED)

    dispenser = validate_success(
        api.create_dispenser(payload, base["technician_headers"]), 201
    )
    assert_lockout(dispenser, DISPENSER_ACTIVE, None)
    assert dispenser["placement_id"] == base["placement_id"]
    assert dispenser["prior_dose_ml_per_rack"] is None


def test_the_dispenser_window_closes_again_once_retrieval_is_scheduled(api):
    """
    RETRIEVAL_SCHEDULED is on the far side of the window, so a second dispenser —
    for SAN-200, which the agreement genuinely covers — is refused for the
    lifecycle state and not for product coverage, leaving exactly one dispenser
    on the machine.

    PRD §3.4: "The product must appear in the `covered_product_ids` of the
    agreement covering the placement, or the request is refused with
    `ERR_PRODUCT_NOT_ON_AGREEMENT`: the program only meters chemistry it has
    contracted to supply."

    Design: Difficulty/cross_entity_state_dependency/dispenser_creation_gated_by_placement_lifecycle_state
    """
    base = _pending_install_with_both_products_covered(api)
    X.install_placement(api, base, base["placement_id"])
    detergent_feed = X.fit_dispenser(api, base, base["placement_id"], dose=8.00)

    scheduled = validate_success(
        api.create_retrieval_order(
            base["placement_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-15"),
        )
    )
    assert_axes(scheduled, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)

    locked = get_success_data(
        api.get_dispenser(detergent_feed["id"], base["technician_headers"])
    )
    assert_lockout(locked, DISPENSER_LOCKED_OUT, LOCKOUT_AGREEMENT_ENDED)

    validate_error(
        api.create_dispenser(
            F.dispenser_payload(base["placement_id"], base["sanitizer_id"], 2.50),
            base["technician_headers"],
        ),
        ERR_PLACEMENT_NOT_INSTALLED,
        409,
    )

    rows = _dispensers_on(api, base["placement_id"], base["technician_headers"])
    assert len(rows) == 1
    assert rows[0]["id"] == detergent_feed["id"]


def _retrieval_scheduled_behind_a_pending_verification_ticket(api):
    """
    An INSTALLED machine whose visit has arrived, filed one PASS calibration
    record and been submitted — so its ticket stands PENDING_VERIFICATION — and
    only then is the retrieval order raised. Filing the record before the order
    matters: an AGREEMENT_ENDED lockout would otherwise refuse it.
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-B02")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    work = X.visit_in_progress(api, base, placement["id"])
    record = X.record_calibration(
        api, base, work["visit_id"], dispenser["id"], measured_ppm=1200
    )
    assert record["calibration_verdict"] == VERDICT_PASS
    assert record["drift_pct"] == 0.00

    X.submit_visit(api, base, work["visit_id"], repair_confirmed=True)

    scheduled = validate_success(
        api.create_retrieval_order(
            placement["id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-15"),
        )
    )
    assert_axes(scheduled, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)

    base.update(
        {
            "placement_id": placement["id"],
            "dispenser_id": dispenser["id"],
            "ticket_id": work["ticket_id"],
            "visit_id": work["visit_id"],
        }
    )
    return base


def test_a_pending_verification_ticket_blocks_retrieval_completion(api):
    """
    The retrieval order cancels QUEUED tickets only, so this one survives at
    PENDING_VERIFICATION and blocks the completion; the placement is left exactly
    where it stood.

    PRD §3.3: "It requires `placement_status` `RETRIEVAL_SCHEDULED` and,
    critically, that the placement have **no** ticket in `DISPATCHED`, `ON_SITE`
    or `PENDING_VERIFICATION`; if one exists the request is refused with
    `ERR_OPEN_TICKET_BLOCKS_RETRIEVAL`. Tickets in `QUEUED` never block, because
    the retrieval order already cancelled them."

    Design: Difficulty/cross_entity_state_dependency/retrieval_completion_gated_by_open_service_ticket_state
    """
    base = _retrieval_scheduled_behind_a_pending_verification_ticket(api)

    ticket = get_success_data(
        api.get_service_ticket(base["ticket_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert ticket["status"] == TICKET_PENDING_VERIFICATION

    validate_error(
        api.complete_retrieval(base["placement_id"], base["technician_headers"]),
        ERR_OPEN_TICKET_BLOCKS_RETRIEVAL,
        409,
    )

    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(placement, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)
    assert placement["retrieved_at"] is None


def test_verifying_the_visit_unblocks_a_placement_it_never_names(api):
    """
    An auditor's verify call closes the ticket and frees the engineer's slot, and
    that alone lets the previously refused retrieval succeed — no request in
    between mentions the placement. Removal, not the PASS record, is what clears
    the AGREEMENT_ENDED lockout.

    PRD §3.3: "every dispenser of the placement — whether it stood `ACTIVE` or
    `LOCKED_OUT` — becomes `REMOVED` with its `lockout_reason` cleared to null,
    the model's `equipment_value_cents` is subtracted from the customer's
    `equipment_on_placement_value_cents` restoring that ledger exactly to its
    pre-placement value, the agreement's `placement_count` falls by one with a
    `version` increment, and the site's `service_posture` is re-derived."

    Design: Difficulty/cross_entity_state_dependency/retrieval_completion_gated_by_open_service_ticket_state
    """
    base = _retrieval_scheduled_behind_a_pending_verification_ticket(api)

    validate_error(
        api.complete_retrieval(base["placement_id"], base["technician_headers"]),
        ERR_OPEN_TICKET_BLOCKS_RETRIEVAL,
        409,
    )

    visit = X.verify_visit(api, base["visit_id"])
    assert visit["visit_status"] == VISIT_VERIFIED

    ticket = get_success_data(
        api.get_service_ticket(base["ticket_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert ticket["status"] == TICKET_CLOSED
    technician = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert technician["open_ticket_count"] == 0

    retrieved = validate_success(
        api.complete_retrieval(base["placement_id"], base["technician_headers"])
    )
    assert_axes(
        retrieved,
        placement_status=PLACEMENT_RETRIEVED,
        operational_status=OP_OFFLINE,
    )
    assert_instant_equals(retrieved["retrieved_at"], "2026-08-01T10:00:00Z", "retrieved_at")

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert_lockout(dispenser, DISPENSER_REMOVED, None)

    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["placement_count"] == 0
    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_equipment_ledger(customer, 0)
