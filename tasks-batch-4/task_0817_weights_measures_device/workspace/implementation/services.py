"""Business logic: derived-field recomputation, calculations, state
transitions and cascades. All money uses Decimal with ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

from core import store, now, iso, base_common, touch, ApiError

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

BASE_FEE_CENTS = {"SCALE": 12000, "FUEL_PUMP": 8000, "SCANNER": 15000}

MAINT_TOL = {
    "CLASS_III": [(5000, 6), (20000, 12), (None, 20)],
    "CLASS_IIIL": [(10000, 10), (50000, 20), (None, 40)],
}

MAX_ERRORS = 2
MIN_SAMPLE = 1

PENALTY_RATE = Decimal("1.5")
BASE_PENALTY_CENTS = {"OUT_OF_TOLERANCE": 5000, "PRICE_ERROR": 0, "OPERATING_CONDEMNED": 20000}

DEVICE_BUFFER_MINUTES = 60

TESTABLE_STATES = {"REGISTERED", "SEALED", "CONDEMNED", "OUT_OF_SERVICE"}


def round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Establishment derived fields
# ---------------------------------------------------------------------------

def compute_balance(est_id):
    bal = 0
    for inv in store.fee_invoices.values():
        if inv["establishment_id"] == est_id and inv["status"] == "DUE":
            bal += inv["amount_due_cents"]
    for pen in store.penalties.values():
        if pen["establishment_id"] == est_id and pen["status"] == "ASSESSED":
            bal += pen["amount_cents"]
    return bal


def compute_sealed_count(est_id):
    return sum(
        1 for d in store.devices.values()
        if d["establishment_id"] == est_id and d["status"] == "SEALED"
    )


def refresh_est_values(est):
    """Set derived fields to freshly computed values. Returns True if changed."""
    bal = compute_balance(est["id"])
    sealed = compute_sealed_count(est["id"])
    changed = (est["balance_due_cents"] != bal) or (est["sealed_device_count"] != sealed)
    est["balance_due_cents"] = bal
    est["sealed_device_count"] = sealed
    return changed


def apply_est_side_effect(est):
    """Recompute derived fields as a cross-resource side effect: bump version
    once if anything changed (PRD §2.4 / §2.8)."""
    if refresh_est_values(est):
        touch(est)


# ---------------------------------------------------------------------------
# registration_fee (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def quarter_factor(month):
    if month in (1, 2, 3):
        return Decimal("1.00")
    if month in (4, 5, 6):
        return Decimal("0.75")
    if month in (7, 8, 9):
        return Decimal("0.50")
    return Decimal("0.25")


def create_registration_invoice(device):
    base = BASE_FEE_CENTS[device["device_type"]]
    factor = quarter_factor(now().month)
    amount = round_half_up(Decimal(base) * factor)
    inv = base_common("FeeInvoice")
    inv.update({
        "establishment_id": device["establishment_id"],
        "device_id": device["id"],
        "fee_type": "REGISTRATION",
        "base_amount_cents": base,
        "amount_due_cents": amount,
        "proration_applied": factor < Decimal("1.00"),
        "status": "DUE",
    })
    store.fee_invoices[inv["id"]] = inv
    return inv


# ---------------------------------------------------------------------------
# accuracy_tolerance (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def maintenance_tol(device_class, applied_load):
    tiers = MAINT_TOL[device_class]
    for bound, tol in tiers:
        if bound is None or applied_load <= bound:
            return tol
    return tiers[-1][1]


def evaluate_accuracy(inspection, device):
    readings = [r for r in store.test_readings.values()
                if r["inspection_id"] == inspection["id"]]
    use_acceptance = (device["status"] == "REGISTERED")
    for r in readings:
        maint = maintenance_tol(device["device_class"], r["applied_load"])
        applicable = (maint / 2) if use_acceptance else maint
        if r["error_grams"] > applicable:
            return "FAIL"
    return "PASS"


# ---------------------------------------------------------------------------
# scanner_audit_evaluation (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def evaluate_scanner(inspection):
    items = [i for i in store.audit_items.values()
             if i["inspection_id"] == inspection["id"]]
    error_count = sum(1 for i in items
                      if i["scanned_price_cents"] != i["posted_price_cents"])
    return "FAIL" if error_count > MAX_ERRORS else "PASS"


# ---------------------------------------------------------------------------
# penalty_amount (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def repeat_multiplier(est_id, order):
    # Count condemnation orders of this establishment created strictly earlier
    # than `order`. `created_at` is the primary key; `_seq` (the monotonic
    # creation counter, same tiebreaker used by ordered listings) breaks ties so
    # records minted under the same logical-clock instant still order by true
    # creation sequence.
    key = (order["created_at"], order["_seq"])
    prior = 0
    for co in store.condemnations.values():
        dev = store.devices.get(co["device_id"])
        if dev is None or dev["establishment_id"] != est_id:
            continue
        if (co["created_at"], co["_seq"]) < key:
            prior += 1
    if prior == 0:
        return Decimal("1.0")
    if 1 <= prior <= 2:
        return Decimal("1.5")
    return Decimal("2.0")


def compute_penalty_amount(violation_type, est_id, order, inspection):
    mult = repeat_multiplier(est_id, order)
    if violation_type == "PRICE_ERROR":
        subtotal = 0
        for item in store.audit_items.values():
            if item["inspection_id"] != inspection["id"]:
                continue
            if item["overcharge_cents"] > 0:
                subtotal += round_half_up(Decimal(item["overcharge_cents"]) * PENALTY_RATE)
        return round_half_up(Decimal(subtotal) * mult)
    base = BASE_PENALTY_CENTS[violation_type]
    return round_half_up(Decimal(base) * mult)


# ---------------------------------------------------------------------------
# Seal / condemnation helpers
# ---------------------------------------------------------------------------

def void_active_seals(device_id):
    for seal in store.seals.values():
        if seal["device_id"] == device_id and seal["status"] == "ACTIVE":
            seal["status"] = "VOIDED"
            touch(seal)


def create_seal(device, inspection):
    seal = base_common("Seal")
    seal.update({
        "device_id": device["id"],
        "inspection_id": inspection["id"],
        "seal_number": store.next_seal_number(),
        "status": "ACTIVE",
    })
    store.seals[seal["id"]] = seal
    return seal


def lift_condemnations(device_id):
    for co in store.condemnations.values():
        if co["device_id"] == device_id and co["status"] == "ISSUED":
            co["status"] = "LIFTED"
            touch(co)


# ---------------------------------------------------------------------------
# Finalize: device seal / condemn cascades
# ---------------------------------------------------------------------------

def finalize_pass(inspection, device, est):
    was_condemned = (device["status"] == "CONDEMNED")
    device["status"] = "SEALED"
    touch(device)
    create_seal(device, inspection)
    if was_condemned:
        lift_condemnations(device["id"])
    apply_est_side_effect(est)


def condemnation_reason(inspection_type, violation_type):
    if violation_type == "OPERATING_CONDEMNED":
        return "Device found operating under an outstanding condemnation order"
    if inspection_type == "PRICE_VERIFICATION":
        return "Condemned due to failed price verification (scanner audit)"
    return "Condemned due to failed accuracy test (out of tolerance)"


def finalize_fail(inspection, device, est):
    pre_status = device["status"]
    if pre_status == "SEALED":
        void_active_seals(device["id"])
    device["status"] = "CONDEMNED"
    touch(device)

    # violation type
    if pre_status == "CONDEMNED":
        violation_type = "OPERATING_CONDEMNED"
    elif inspection["inspection_type"] == "PRICE_VERIFICATION":
        violation_type = "PRICE_ERROR"
    else:
        violation_type = "OUT_OF_TOLERANCE"

    order = base_common("CondemnationOrder")
    order.update({
        "device_id": device["id"],
        "inspection_id": inspection["id"],
        "reason": condemnation_reason(inspection["inspection_type"], violation_type),
        "status": "ISSUED",
    })
    store.condemnations[order["id"]] = order

    amount = compute_penalty_amount(violation_type, est["id"], order, inspection)
    penalty = base_common("Penalty")
    penalty.update({
        "establishment_id": est["id"],
        "device_id": device["id"],
        "violation_type": violation_type,
        "amount_cents": amount,
        "status": "ASSESSED",
    })
    store.penalties[penalty["id"]] = penalty

    apply_est_side_effect(est)
