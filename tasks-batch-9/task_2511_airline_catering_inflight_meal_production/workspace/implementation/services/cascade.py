"""Shared cascades: audit findings, airline suspension, cart/manifest unwinding."""

import clock
import db
from services import calc
from timeutil import fmt_ms

TERMINAL_CART_BUILD = ("RETURNED",)


# ---------------------------------------------------------------------------
# audit findings and airline suspension


def open_finding_count(airline_id):
    return len([
        f for f in db.where("audit_findings", airline_id=airline_id)
        if f["status"] == "OPEN"
    ])


def penalty_accrued_cents(airline_id):
    return sum(
        f["penalty_cents"] for f in db.where("audit_findings", airline_id=airline_id)
        if f["status"] == "ACCEPTED"
    )


def refresh_airline_status(airline):
    """Cross the suspension threshold in either direction."""
    if airline is None:
        return
    count = open_finding_count(airline["id"])
    if airline["status"] == "ACTIVE" and count >= calc.OPEN_FINDING_SUSPEND_THRESHOLD:
        airline["status"] = "SUSPENDED"
        db.touch(airline)
        for flight in db.where("flights", airline_id=airline["id"]):
            if flight["status"] in ("SCHEDULED", "COUNTS_LOCKED") and not flight["production_hold"]:
                flight["production_hold"] = True
                db.touch(flight)
    elif airline["status"] == "SUSPENDED" and count < calc.OPEN_FINDING_SUSPEND_THRESHOLD:
        airline["status"] = "ACTIVE"
        db.touch(airline)
        for flight in db.where("flights", airline_id=airline["id"]):
            if flight["production_hold"]:
                flight["production_hold"] = False
                db.touch(flight)


def raise_finding(airline_id, flight_id, finding_type, severity, source, evidence_ref=None):
    finding = db.insert("audit_findings", {
        "airline_id": airline_id,
        "flight_id": flight_id,
        "finding_type": finding_type,
        "severity": severity,
        "source": source,
        "evidence_ref": evidence_ref,
        "penalty_cents": calc.finding_penalty_cents(finding_type, severity),
        "status": "OPEN",
    })
    refresh_airline_status(db.get("airlines", airline_id))
    return finding


# ---------------------------------------------------------------------------
# manifest amendment


def pinning_issued_manifest(cart):
    for manifest in calc.flight_manifests(cart["flight_id"]):
        if manifest["status"] != "ISSUED":
            continue
        for entry in manifest.get("cart_seal_snapshot") or []:
            if entry.get("cart_id") == cart["id"]:
                return manifest
    return None


def amend_manifest(manifest):
    """ISSUED -> AMENDED, and the flight LOADED -> PLANNED."""
    if manifest is None or manifest["status"] != "ISSUED":
        return
    manifest["status"] = "AMENDED"
    manifest["amendment_count"] = manifest["amendment_count"] + 1
    db.touch(manifest)
    flight = db.get("flights", manifest["flight_id"])
    if flight is not None and flight["status"] == "LOADED":
        flight["status"] = "PLANNED"
        db.touch(flight)


def amend_for_cart(cart):
    amend_manifest(pinning_issued_manifest(cart))


# ---------------------------------------------------------------------------
# cart items


def break_cart_seal(cart):
    if cart["seal_status"] in ("SEALED", "RESEALED"):
        cart["seal_status"] = "BROKEN"
        cart["sealed_by_user_id"] = None
        return True
    return False


def void_item(item):
    """ACTIVE -> VOID with the full ripple, in the fixed order of PRD 3.6."""
    item["status"] = "VOID"
    item["voided_at"] = fmt_ms(clock.now())
    db.touch(item)

    cart = db.get("carts", item["cart_id"])
    if cart is None:
        return
    axes_moved = False
    if cart["build_status"] == "BUILT":
        cart["build_status"] = "BUILDING"
        axes_moved = True
    if break_cart_seal(cart):
        axes_moved = True
    # PRD 3.6: the void recomputes the cart's loaded_units either way, so the
    # cart row is mutated even when neither axis had anywhere to move.
    db.touch(cart)
    if axes_moved:
        amend_for_cart(cart)
    # PRD 3.6: the void also recomputes the flight's units_loaded, unit_balance
    # and cost_per_pax_cents; PRD 2.9 makes that a real mutation of the flight.
    flight = db.get("flights", cart["flight_id"])
    if flight is not None:
        db.touch(flight)


# ---------------------------------------------------------------------------
# batch rejection


def reject_batch(batch, scrap=True):
    batch["production_status"] = "REJECTED"
    if scrap:
        batch["scrapped_qty"] = batch["planned_qty"]
    batch["haccp_risk_score"] = calc.risk_score(batch)
    db.touch(batch)
    # PRD 3.5: the rejection recomputes the flight's units_produced,
    # units_scrapped and unit_balance, which PRD 2.9 counts as a real mutation
    # of the flight row.
    flight = db.get("flights", batch["flight_id"])
    if flight is not None:
        db.touch(flight)


def reject_released_batch_cascade(batch):
    """The four-hop cascade a FAIL on a RELEASED batch heads."""
    # hop 1 — the batch itself
    reject_batch(batch)

    # hop 2 — its ACTIVE cart items and their carts' two axes
    for item in db.where("cart_items", production_batch_id=batch["id"]):
        if item["status"] != "ACTIVE":
            continue
        void_item(item)


# ---------------------------------------------------------------------------
# departure join


def check_departure(manifest):
    """Flight LOADED -> DEPARTED once every run of the ISSUED manifest is terminal."""
    if manifest is None or manifest["status"] != "ISSUED":
        return
    flight = db.get("flights", manifest["flight_id"])
    if flight is None or flight["status"] != "LOADED":
        return
    runs = calc.manifest_runs(manifest["id"])
    if not runs:
        return
    terminal = ("DELIVERED", "RECOVERED", "CANCELLED")
    if not all(run["status"] in terminal for run in runs):
        return
    if not any(run["status"] == "DELIVERED" for run in runs):
        return
    flight["status"] = "DEPARTED"
    db.touch(flight)
    for cart in calc.flight_carts(flight["id"]):
        if cart["build_status"] == "BUILT":
            cart["build_status"] = "LOADED"
            db.touch(cart)
