"""Domain service: derived-field recomputation, bubble-up, and state
transition cascades for Bond / ForfeitureProceeding / GpsDevice / CollateralItem /
IndemnityAgreement.

Every recompute of a derived field on a mutable resource counts as a mutation:
it bumps that resource's updated_at and version (PRD §2.4, §2.8).
"""
from datetime import timedelta

import db
from clock import now_utc, now_iso, iso, parse_iso
from errors import err
from services import calculations as calc

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def bonds_for_defendant(defendant_id):
    return [b for b in db.bonds.values() if b["defendant_id"] == defendant_id]


def agreements_for_bond(bond_id):
    return [a for a in db.indemnity_agreements.values() if a["bond_id"] == bond_id]


def agreements_for_indemnitor(indemnitor_id):
    return [a for a in db.indemnity_agreements.values() if a["indemnitor_id"] == indemnitor_id]


def collateral_for_bond(bond_id):
    return [c for c in db.collateral_items.values() if c["bond_id"] == bond_id]


def court_dates_for_bond(bond_id):
    return [c for c in db.court_dates.values() if c["bond_id"] == bond_id]


def devices_for_bond(bond_id):
    return [d for d in db.gps_devices.values() if d.get("assigned_bond_id") == bond_id]


def bonds_for_order(order_id):
    return [b for b in db.bonds.values() if b["bail_order_id"] == order_id]


# ---------------------------------------------------------------------------
# Derived-field recomputation (each bumps version/updated_at of the owner)
# ---------------------------------------------------------------------------

def recompute_defendant_exposure(defendant):
    total = sum(b["bail_amount_cents"] for b in bonds_for_defendant(defendant["id"])
                if b["coverage_status"] in ("ACTIVE", "FORFEITED"))
    defendant["total_active_exposure_cents"] = total
    db.touch(defendant)


def recompute_defendant_status(defendant):
    """ACTIVE while any bond is ACTIVE/FORFEITED; CLEARED once every bond is
    EXONERATED or REVOKED. Recompute counts as a mutation."""
    bonds = bonds_for_defendant(defendant["id"])
    if bonds and all(b["coverage_status"] in ("EXONERATED", "REVOKED") for b in bonds):
        new_status = "CLEARED"
    else:
        new_status = "ACTIVE"
    defendant["status"] = new_status
    db.touch(defendant)


def recompute_indemnitor_exposure(indemnitor):
    total = sum(a["liability_share_cents"] for a in agreements_for_indemnitor(indemnitor["id"])
                if a["status"] == "BINDING")
    indemnitor["total_exposure_cents"] = total
    db.touch(indemnitor)


def recompute_collateral_held(bond, touch=True):
    total = sum(c["pledged_value_cents"] for c in collateral_for_bond(bond["id"])
                if c["status"] == "HELD")
    bond["collateral_held_cents"] = total
    if touch:
        db.touch(bond)


# ---------------------------------------------------------------------------
# Bubble-up: bond coverage drives BailOrder.status then Defendant.status
# ---------------------------------------------------------------------------

def recompute_bail_order_status(order):
    """OPEN until a bond is posted+activated, BONDED once active, RESOLVED once
    the bond reaches a terminal coverage_status. Derived from the order's bonds."""
    bonds = bonds_for_order(order["id"])
    if not bonds:
        new_status = "OPEN"
    elif all(b["coverage_status"] in ("EXONERATED", "REVOKED") for b in bonds):
        new_status = "RESOLVED"
    elif any(b["coverage_status"] in ("ACTIVE", "FORFEITED") for b in bonds):
        new_status = "BONDED"
    else:
        # bonds exist but all still DRAFT
        new_status = "OPEN"
    if order["status"] != new_status:
        order["status"] = new_status
        db.touch(order)


def bubble_up_from_bond(bond):
    """Recompute the owning order's status and the defendant's status."""
    order = db.bail_orders.get(bond["bail_order_id"])
    if order:
        recompute_bail_order_status(order)
    defendant = db.defendants.get(bond["defendant_id"])
    if defendant:
        recompute_defendant_status(defendant)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def append_ledger(bond_id, entry_type, amount_cents, memo=""):
    rec = db.make_record({
        "bond_id": bond_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
    }, mutable=False)
    db.ledger_entries[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Bond transitions
# ---------------------------------------------------------------------------

def activate_bond(defendant, bond, actor_user_id):
    """DRAFT -> ACTIVE. Validations (priority order) already partly done by caller
    for state; this enforces the fiscal preconditions then fires the cascade."""
    if bond["coverage_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Bond is not in DRAFT.")

    order = db.bail_orders.get(bond["bail_order_id"])
    # Re-affirm bond-type permission at activation.
    if order is not None:
        allowed = order["bond_type_allowed"]
        if allowed != "ANY" and allowed != bond["bond_type"]:
            raise err("ERR_BOND_TYPE_NOT_ALLOWED", "Bond type not permitted by order.")

    # Recompute required collateral now (depends on risk tier).
    required = calc.required_collateral(bond["bond_type"], bond["bail_amount_cents"],
                                        defendant["risk_tier"])

    # Fiscal precondition: SURETY indemnity coverage (priority 18 before collateral 19).
    if bond["bond_type"] == "SURETY":
        pending_total = sum(a["liability_share_cents"] for a in agreements_for_bond(bond["id"])
                            if a["status"] == "PENDING")
        if pending_total < bond["bail_amount_cents"]:
            raise err("ERR_INSUFFICIENT_INDEMNITY", "Insufficient pending indemnity coverage.")

    # Fiscal precondition: collateral (SURETY + CASH).
    if bond["bond_type"] in ("SURETY", "CASH"):
        held = sum(c["pledged_value_cents"] for c in collateral_for_bond(bond["id"])
                   if c["status"] == "HELD")
        if held < required:
            raise err("ERR_INSUFFICIENT_COLLATERAL", "Insufficient collateral held.")

    # --- commit cascade ---
    if bond["bond_type"] == "SURETY":
        premium = calc.surety_premium(bond["bail_amount_cents"], bond["premium_rate_bps"])
    else:
        premium = 0

    bond["coverage_status"] = "ACTIVE"
    bond["posted_at"] = now_iso()
    bond["premium_cents"] = premium
    bond["required_collateral_cents"] = required
    bond["settlement_status"] = "PREMIUM_COLLECTED"
    bond["activated_by_user_id"] = actor_user_id
    db.touch(bond)

    if bond["bond_type"] == "SURETY" and premium != 0:
        append_ledger(bond["id"], "PREMIUM_COLLECTED", +premium)

    # Bind PENDING agreements -> BINDING; recompute each indemnitor's exposure.
    for a in agreements_for_bond(bond["id"]):
        if a["status"] == "PENDING":
            a["status"] = "BINDING"
            db.touch(a)
            indemnitor = db.indemnitors.get(a["indemnitor_id"])
            if indemnitor:
                recompute_indemnitor_exposure(indemnitor)

    bubble_up_from_bond(bond)
    recompute_defendant_exposure(defendant)
    return bond


def revoke_bond(defendant, bond):
    """DRAFT -> REVOKED. Discharge PENDING agreements, release HELD collateral
    (no ledger), bubble up."""
    if bond["coverage_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Bond is not in DRAFT.")

    bond["coverage_status"] = "REVOKED"
    db.touch(bond)

    for a in agreements_for_bond(bond["id"]):
        if a["status"] == "PENDING":
            a["status"] = "DISCHARGED"
            db.touch(a)
            indemnitor = db.indemnitors.get(a["indemnitor_id"])
            if indemnitor:
                recompute_indemnitor_exposure(indemnitor)

    for c in collateral_for_bond(bond["id"]):
        if c["status"] == "HELD":
            c["status"] = "RELEASED"
            db.touch(c)
    recompute_collateral_held(bond)

    bubble_up_from_bond(bond)
    recompute_defendant_exposure(defendant)
    return bond


def exonerate_bond(defendant, bond, actor_user_id):
    """ACTIVE -> EXONERATED. Preconditions checked by caller for state; this
    enforces no-open-hearing + segregation, then fires the cascade."""
    if bond["coverage_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Bond is not ACTIVE.")

    # No court date on this bond may be SCHEDULED or NOTIFIED.
    for cd in court_dates_for_bond(bond["id"]):
        if cd["status"] in ("SCHEDULED", "NOTIFIED"):
            raise err("ERR_INVALID_STATE", "Open court dates remain on this bond.")

    # Segregation of duties: actor must not be the activating BondsAgent.
    if bond.get("activated_by_user_id") is not None and \
            actor_user_id == bond["activated_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Exonerating officer must not be the activating agent.")

    bond["coverage_status"] = "EXONERATED"
    bond["premium_earned_cents"] = bond["premium_cents"]
    bond["settlement_status"] = "COLLATERAL_REFUNDED"
    db.touch(bond)

    # Release HELD collateral; append per-item COLLATERAL_REFUND (negative).
    for c in collateral_for_bond(bond["id"]):
        if c["status"] == "HELD":
            c["status"] = "RELEASED"
            db.touch(c)
            refund = calc.collateral_refund_amount(c["pledged_value_cents"])
            append_ledger(bond["id"], "COLLATERAL_REFUND", -refund)
    recompute_collateral_held(bond)

    # Discharge BINDING agreements.
    for a in agreements_for_bond(bond["id"]):
        if a["status"] == "BINDING":
            a["status"] = "DISCHARGED"
            db.touch(a)
            indemnitor = db.indemnitors.get(a["indemnitor_id"])
            if indemnitor:
                recompute_indemnitor_exposure(indemnitor)

    # Return any ACTIVE GPS device on this bond.
    for d in devices_for_bond(bond["id"]):
        if d["status"] == "ACTIVE":
            d["status"] = "RETURNED"
            d["assigned_bond_id"] = None
            db.touch(d)

    bubble_up_from_bond(bond)
    recompute_defendant_exposure(defendant)
    return bond


# ---------------------------------------------------------------------------
# Forfeiture (driven by record-fta) + recovery / reinstate / judgment / remit
# ---------------------------------------------------------------------------

def forfeit_bond(defendant, bond, trigger_court_date):
    """Cascade Bond ACTIVE -> FORFEITED, create ForfeitureProceeding."""
    bond["coverage_status"] = "FORFEITED"
    db.touch(bond)

    forfeited_dt = now_utc()
    grace_dt = forfeited_dt + timedelta(days=calc.GRACE_PERIOD_DAYS)
    proceeding = db.make_record({
        "bond_id": bond["id"],
        "trigger_court_date_id": trigger_court_date["id"],
        "forfeited_utc": iso(forfeited_dt),
        "grace_deadline_utc": iso(grace_dt),
        "judgment_amount_cents": 0,
        "status": "FORFEITED",
        "passed_recovery_open": False,  # internal flag for judgment credit
    }, mutable=True)
    db.forfeitures[proceeding["id"]] = proceeding

    bubble_up_from_bond(bond)
    recompute_defendant_exposure(defendant)
    return proceeding


def open_recovery(defendant, proceeding):
    """FORFEITED -> RECOVERY_OPEN (RecoveryAgent)."""
    if proceeding["status"] != "FORFEITED":
        raise err("ERR_INVALID_STATE", "Proceeding is not FORFEITED.")
    if now_utc() > parse_iso(proceeding["grace_deadline_utc"]):
        raise err("ERR_GRACE_EXPIRED", "Grace period has expired.")
    proceeding["status"] = "RECOVERY_OPEN"
    proceeding["passed_recovery_open"] = True
    db.touch(proceeding)
    return proceeding


def reinstate(defendant, proceeding):
    """RECOVERY_OPEN -> REINSTATED, cascade Bond FORFEITED -> ACTIVE."""
    if proceeding["status"] != "RECOVERY_OPEN":
        raise err("ERR_INVALID_STATE", "Proceeding is not RECOVERY_OPEN.")
    bond = db.bonds.get(proceeding["bond_id"])
    if bond is None or bond["coverage_status"] != "FORFEITED":
        raise err("ERR_INVALID_STATE", "Bond is not FORFEITED.")
    if now_utc() > parse_iso(proceeding["grace_deadline_utc"]):
        raise err("ERR_GRACE_EXPIRED", "Grace period has expired.")

    proceeding["status"] = "REINSTATED"
    db.touch(proceeding)

    bond["coverage_status"] = "ACTIVE"
    db.touch(bond)

    bubble_up_from_bond(bond)
    recompute_defendant_exposure(defendant)
    return proceeding


def enter_judgment(defendant, proceeding, expected_bond_version):
    """FORFEITED|RECOVERY_OPEN -> JUDGMENT. OCC on bond version; liquidate
    collateral, call indemnity, record net judgment, bump bond version."""
    if proceeding["status"] not in ("FORFEITED", "RECOVERY_OPEN"):
        raise err("ERR_INVALID_STATE", "Proceeding is not FORFEITED or RECOVERY_OPEN.")

    bond = db.bonds.get(proceeding["bond_id"])
    if bond is None:
        raise err("ERR_INVALID_STATE", "Bond missing.")

    # Grace must be STRICTLY past (state check already passed; §2.6 ordering:
    # state -> OCC -> business temporal). OCC precedes grace per priority 9<16.
    if expected_bond_version != bond["version"]:
        raise err("ERR_STALE_VERSION", "Bond version is stale.")

    if now_utc() <= parse_iso(proceeding["grace_deadline_utc"]):
        raise err("ERR_GRACE_NOT_EXPIRED", "Judgment is premature; grace not expired.")

    # Liquidate HELD collateral.
    liquidated = 0
    for c in collateral_for_bond(bond["id"]):
        if c["status"] == "HELD":
            c["status"] = "LIQUIDATED"
            db.touch(c)
            liquidated += c["pledged_value_cents"]
            append_ledger(bond["id"], "FORFEITURE_JUDGMENT", +c["pledged_value_cents"])
    # Recompute held collateral WITHOUT a separate bond touch: entering judgment
    # increments the bond's version by exactly one (PRD §3.6), so all of the
    # bond's own mutations in this operation collapse into a single bump below.
    recompute_collateral_held(bond, touch=False)

    # Call BINDING agreements.
    for a in agreements_for_bond(bond["id"]):
        if a["status"] == "BINDING":
            a["status"] = "CALLED"
            db.touch(a)
            indemnitor = db.indemnitors.get(a["indemnitor_id"])
            if indemnitor:
                recompute_indemnitor_exposure(indemnitor)

    net = calc.judgment_amount(bond["bail_amount_cents"], liquidated,
                               proceeding.get("passed_recovery_open", False))
    proceeding["judgment_amount_cents"] = net
    proceeding["status"] = "JUDGMENT"
    db.touch(proceeding)

    # Bond stays FORFEITED; settlement -> JUDGMENT_ENTERED; single version bump.
    bond["settlement_status"] = "JUDGMENT_ENTERED"
    db.touch(bond)

    append_ledger(bond["id"], "FORFEITURE_JUDGMENT", +net, memo="net judgment")
    return proceeding


def remit(defendant, proceeding, remission_pct):
    """JUDGMENT -> REMITTED. Append REMISSION_CREDIT (negative); no other cascades."""
    if proceeding["status"] != "JUDGMENT":
        raise err("ERR_INVALID_STATE", "Proceeding is not JUDGMENT.")
    remitted = calc.remission_credit(proceeding["judgment_amount_cents"], remission_pct)
    proceeding["status"] = "REMITTED"
    db.touch(proceeding)
    append_ledger(proceeding["bond_id"], "REMISSION_CREDIT", -remitted)
    return proceeding
