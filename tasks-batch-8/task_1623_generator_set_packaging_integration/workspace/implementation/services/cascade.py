"""Cascade / side-effect helpers shared across route handlers.

These implement the order-advancement triggers and the multi-hop cancellation
cascade described in PRD Sections 2.10, 3.7, and 3.8.
"""

import db
import services.calculations as calc


# ---------------------------------------------------------------------------
# Shipment release (used by FAIL regression, explicit release, and cancel)
# ---------------------------------------------------------------------------

def release_shipment(shipment):
    """Transition a BOOKED shipment to RELEASED and return crane occupancy."""
    if shipment["status"] != "BOOKED":
        return
    slot = db.crane_slots.get(shipment["crane_slot_id"])
    if slot is not None:
        slot["reserved_hours"] = slot["reserved_hours"] - (
            shipment["lift_hours"] + slot["buffer_hours"]
        )
        slot["free_hours"] = (
            slot["window_end_hour"] - slot["window_start_hour"]
        ) - slot["reserved_hours"]
        db.touch(slot)
    shipment["status"] = "RELEASED"
    db.touch(shipment)


def release_booked_shipments_for_order(order_id):
    for s in db.shipments.values():
        if s["order_id"] == order_id and s["status"] == "BOOKED":
            release_shipment(s)


# ---------------------------------------------------------------------------
# Permit withdrawal -> certificate void (hop 3 / direct withdraw side effect)
# ---------------------------------------------------------------------------

def void_certificates_for_configuration(configuration_id):
    for cert in db.emissions_certificates.values():
        if (
            cert["configuration_id"] == configuration_id
            and cert["status"] in ("APP_DRAFT", "SUBMITTED", "REJECTED")
        ):
            cert["status"] = "VOIDED"
            db.touch(cert)


def withdraw_permit(permit):
    """Move a permit to WITHDRAWN and void the linked certificate."""
    permit["status"] = "WITHDRAWN"
    db.touch(permit)
    void_certificates_for_configuration(permit["configuration_id"])


# ---------------------------------------------------------------------------
# Configuration cancellation (hop 1) with hop 2 / hop 2-alternate
# ---------------------------------------------------------------------------

def cancel_configuration(config):
    """Cancel one configuration and run its permit/cert cascades."""
    config["status"] = "CANCELLED"
    db.touch(config)

    # Hop 2: permits in DRAFT / SUBMITTED / CORRECTION_REQUESTED -> WITHDRAWN
    live_permit_found = False
    for permit in db.permit_cases.values():
        if (
            permit["configuration_id"] == config["id"]
            and permit["status"] in ("DRAFT", "SUBMITTED", "CORRECTION_REQUESTED")
        ):
            live_permit_found = True
            # Withdrawal itself (hop 2) triggers hop 3: void the certificate.
            withdraw_permit(permit)

    # Hop 2 alternate: configuration has NO non-terminal permit at all ->
    # void the certificate directly.
    if not live_permit_found:
        any_non_terminal_permit = any(
            p["configuration_id"] == config["id"]
            and p["status"] in ("DRAFT", "SUBMITTED", "CORRECTION_REQUESTED")
            for p in db.permit_cases.values()
        )
        if not any_non_terminal_permit:
            void_certificates_for_configuration(config["id"])


# ---------------------------------------------------------------------------
# Order build advancement helpers
# ---------------------------------------------------------------------------

def advance_order(order, new_build_status):
    """Move build_status forward, incrementing version (system cascade)."""
    order["build_status"] = new_build_status
    db.touch(order)


def maybe_advance_to_testing(order):
    """PERMITTING -> TESTING when both a permit APPROVED and a cert ISSUED exist."""
    if order["build_status"] != "PERMITTING":
        return
    has_approved_permit = any(
        p["order_id"] == order["id"] and p["status"] == "APPROVED"
        for p in db.permit_cases.values()
    )
    has_issued_cert = any(
        c["order_id"] == order["id"] and c["status"] == "ISSUED"
        for c in db.emissions_certificates.values()
    )
    if has_approved_permit and has_issued_cert:
        advance_order(order, "TESTING")
