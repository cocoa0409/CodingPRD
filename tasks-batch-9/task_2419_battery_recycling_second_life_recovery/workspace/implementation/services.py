"""Aggregate maintenance, settlement pricing and the cascades of PRD 2.11 / 3.x."""

from decimal import Decimal as D

import calc
from core import ApiError, D as Dec, db, new_row, q0, q3, sort_rows, touch

# ---------------------------------------------------------------------------
# path resolution -- PRD 2.6, left to right
# ---------------------------------------------------------------------------


def get_or_404(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def facility_or_404(facility_id):
    return get_or_404(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")


def supplier_or_404(supplier_id):
    return get_or_404(db.suppliers, supplier_id, "ERR_SUPPLIER_NOT_FOUND")


def intake_or_404(intake_id):
    return get_or_404(db.intakes, intake_id, "ERR_INTAKE_NOT_FOUND")


def module_or_404(module_id):
    return get_or_404(db.modules, module_id, "ERR_MODULE_NOT_FOUND")


def line_or_404(line_id):
    return get_or_404(db.lines, line_id, "ERR_LINE_NOT_FOUND")


def campaign_or_404(campaign_id):
    return get_or_404(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")


def lot_or_404(lot_id):
    return get_or_404(db.lots, lot_id, "ERR_LOT_NOT_FOUND")


def settlement_or_404(settlement_id):
    return get_or_404(db.settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND")


def allotment_or_404(allotment_id):
    return get_or_404(db.allotments, allotment_id, "ERR_PERMIT_NOT_FOUND")


def event_or_404(event_id):
    return get_or_404(db.events, event_id, "ERR_DISCHARGE_EVENT_NOT_FOUND")


def passport_or_404(passport_id):
    return get_or_404(db.passports, passport_id, "ERR_PASSPORT_NOT_FOUND")


def manifest_under_intake_or_404(intake, manifest_id):
    manifest = db.manifests.get(manifest_id)
    if manifest is None or manifest["intake_id"] != intake["id"]:
        raise ApiError("ERR_MANIFEST_NOT_FOUND")
    return manifest


# ---------------------------------------------------------------------------
# child collections
# ---------------------------------------------------------------------------


def modules_of_intake(intake_id):
    return sort_rows([m for m in db.modules.values() if m["intake_id"] == intake_id])


def modules_of_lot(lot_id):
    return sort_rows([m for m in db.modules.values() if m.get("lot_id") == lot_id])


def manifests_of_intake(intake_id):
    return sort_rows([m for m in db.manifests.values() if m["intake_id"] == intake_id])


def decisions_of_module(module_id):
    return sort_rows([d for d in db.decisions.values() if d["module_id"] == module_id])


def lots_of_campaign(campaign_id):
    return sort_rows([l for l in db.lots.values() if l["campaign_id"] == campaign_id])


def campaigns_of_line(line_id):
    return sort_rows([c for c in db.campaigns.values() if c["line_id"] == line_id])


def settlements_of_intake(intake_id):
    return sort_rows(
        [s for s in db.settlements.values() if s["intake_id"] == intake_id]
    )


def intakes_of_supplier(supplier_id):
    return sort_rows([i for i in db.intakes.values() if i["supplier_id"] == supplier_id])


def campaign_of_lot(lot):
    return db.campaigns.get(lot["campaign_id"])


def line_of_campaign(campaign):
    return db.lines.get(campaign["line_id"])


# ---------------------------------------------------------------------------
# aggregate recomputation
# ---------------------------------------------------------------------------

ASSIGNED_STATUSES = ("CHARGED", "CONSUMED")


def recompute_intake_masses(intake):
    total = D(0)
    assigned = D(0)
    for module in modules_of_intake(intake["id"]):
        total += module["mass_kg"]
        if module["status"] in ASSIGNED_STATUSES:
            assigned += module["mass_kg"]
    intake["module_mass_total_kg"] = q3(total)
    intake["assigned_mass_kg"] = q3(assigned)
    intake["unassigned_mass_kg"] = q3(intake["module_mass_total_kg"] - intake["assigned_mass_kg"])


def recompute_lot_charged_mass(lot):
    total = D(0)
    for module in db.modules.values():
        if module.get("lot_id") == lot["id"] and module["status"] in ASSIGNED_STATUSES:
            total += module["mass_kg"]
    lot["charged_mass_kg"] = q3(total)


def recompute_campaign_committed(campaign):
    total = D(0)
    for lot in lots_of_campaign(campaign["id"]):
        if lot["status"] in ("OPEN", "CHARGED", "FINALIZED"):
            total += lot["charged_mass_kg"]
    campaign["committed_input_kg"] = q3(total)


def recompute_lot_recovered(lot):
    lot["recovered_mass_kg"] = calc.lot_recovered_mass(lot["id"])


def recompute_permit_consumed(allotment):
    allotment["consumed_kg"] = calc.permit_consumed(allotment["id"])


# ---------------------------------------------------------------------------
# settlement pricing
# ---------------------------------------------------------------------------


def contributor_masses(lot_id):
    """intake_id -> summed mass of its modules charged/consumed into this lot."""
    masses = {}
    for module in db.modules.values():
        if module.get("lot_id") != lot_id:
            continue
        if module["status"] not in ASSIGNED_STATUSES:
            continue
        masses[module["intake_id"]] = masses.get(module["intake_id"], D(0)) + module["mass_kg"]
    return masses


def contributor_intakes(lot_id):
    masses = contributor_masses(lot_id)
    intakes = [db.intakes[i] for i in masses if i in db.intakes]
    return sort_rows(intakes)


def apportion(lot, intake_id, lot_recovered):
    """Split the lot's recovered figure across contributing intakes (PRD 3.7).

    The intake with the latest created_at absorbs the rounding remainder so the
    parts sum exactly to the lot's recovered figure for that metal.
    """
    target = q3(lot_recovered)
    if target == 0:
        return q3(0)
    masses = contributor_masses(lot["id"])
    charged = lot["charged_mass_kg"]
    if not masses or charged == 0:
        return q3(0)
    ordered = sort_rows([db.intakes[i] for i in masses if i in db.intakes])
    running = D(0)
    parts = {}
    for index, contributor in enumerate(ordered):
        if index == len(ordered) - 1:
            parts[contributor["id"]] = target - running
        else:
            share = masses[contributor["id"]] / charged
            value = q3(target * share)
            parts[contributor["id"]] = value
            running += value
    return parts.get(intake_id, q3(0))


def final_contained(lot, intake_id, umpire_metal=None, umpire_contained_kg=None):
    contained = {}
    for metal in calc.PAYABLE_METALS:
        output = next(
            (o for o in calc.lot_outputs(lot["id"]) if o["metal"] == metal), None
        )
        lot_recovered = output["recovered_mass_kg"] if output else D(0)
        if umpire_metal is not None and metal == umpire_metal and umpire_contained_kg is not None:
            lot_recovered = umpire_contained_kg
        contained[metal] = apportion(lot, intake_id, lot_recovered)
    return contained


def price_settlement(
    settlement,
    intake,
    supplier,
    variant,
    price_date,
    lot=None,
    umpire_metal=None,
    umpire_contained_kg=None,
    strike_count=None,
):
    """Price a settlement and run the seven-step waterfall. Raises on missing quotes."""
    if variant == "PROVISIONAL":
        contained = calc.provisional_contained(intake)
        factors = calc.provisional_factors(intake)
    else:
        contained = final_contained(lot, intake["id"], umpire_metal, umpire_contained_kg)
        factors = {metal: D(1) for metal in calc.PAYABLE_METALS}
    lines, gross_cents = calc.price_lines(contained, factors, price_date)
    if strike_count is None:
        strike_count = supplier["quality_strike_count"]
    deduction_pct = calc.quality_deduction_pct(intake, strike_count)
    money = calc.waterfall(gross_cents, intake, deduction_pct)

    settlement["variant"] = variant
    settlement["price_basis_date"] = price_date
    settlement["line_breakdown"] = lines
    settlement["gross_cents"] = gross_cents
    settlement.update(money)
    if variant == "FINAL":
        settlement["max_variance_pp"] = calc.assay_variance_pp(intake, lines)
    else:
        settlement["max_variance_pp"] = None
    return settlement


def create_provisional_settlement(intake, supplier):
    """Cascade child of custody release; never returned in the release response body."""
    settlement = new_row(
        {
            "intake_id": intake["id"],
            "supplier_id": intake["supplier_id"],
            "variant": "PROVISIONAL",
            "price_basis_date": intake["received_at"],
            "line_breakdown": [],
            "gross_cents": 0,
            "processing_fee_pct": D("0.0"),
            "processing_fee_cents": 0,
            "quality_deduction_pct": D("0.0"),
            "quality_deduction_cents": 0,
            "pre_surcharge_net_cents": 0,
            "hazmat_surcharge_cents": 0,
            "net_payable_cents": 0,
            "posted_amount_cents": 0,
            "max_variance_pp": None,
            "dispute_round": 0,
            "dispute_reason": None,
            "umpire_metal": None,
            "umpire_contained_kg": None,
            "payment_reference": None,
            "void_reason": None,
            "state": "DRAFT",
            "_lot_id": None,
        }
    )
    price_settlement(
        settlement,
        intake,
        supplier,
        "PROVISIONAL",
        intake["received_at"],
    )
    db.settlements[settlement["id"]] = settlement
    return settlement


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------


def quarantine_credit_hold_intakes(supplier):
    """Link 4 of the settlement-post cascade: RECEIVED intakes go to QUARANTINED."""
    for intake in intakes_of_supplier(supplier["id"]):
        if intake["custody_state"] == "RECEIVED":
            intake["custody_state"] = "QUARANTINED"
            intake["hold_reason"] = "SUPPLIER_CREDIT_HOLD"
            touch(intake)


def release_credit_hold(supplier):
    """Compensating link: credit_hold true -> false releases its quarantines to RECEIVED."""
    if not supplier["credit_hold"]:
        return
    if supplier["payable_balance_cents"] > supplier["credit_limit_cents"]:
        return
    supplier["credit_hold"] = False
    for intake in intakes_of_supplier(supplier["id"]):
        if (
            intake["custody_state"] == "QUARANTINED"
            and intake["hold_reason"] == "SUPPLIER_CREDIT_HOLD"
        ):
            intake["custody_state"] = "RECEIVED"
            intake["hold_reason"] = None
            touch(intake)


def apply_credit_hold(supplier):
    if not supplier["credit_hold"] and supplier["payable_balance_cents"] > supplier["credit_limit_cents"]:
        supplier["credit_hold"] = True
        quarantine_credit_hold_intakes(supplier)


def bubble_up_campaign_close(campaign):
    """A RUNNING campaign closes itself once every lot is terminal (PRD 3.6)."""
    if campaign is None or campaign["status"] != "RUNNING":
        return
    lots = lots_of_campaign(campaign["id"])
    if not lots:
        return
    if all(lot["status"] in ("FINALIZED", "VOIDED") for lot in lots):
        campaign["status"] = "CLOSED"
        touch(campaign)
