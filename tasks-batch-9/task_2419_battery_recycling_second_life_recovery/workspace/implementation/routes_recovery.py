"""Campaigns, lots, the assay ledger, discharge compliance and passports (PRD 3.6 - 3.8)."""

from decimal import Decimal as D

from flask import Blueprint, g

import calc
import services
from core import (
    ApiError,
    db,
    endpoint,
    f_dt,
    f_enum,
    f_id_list,
    f_int,
    f_num,
    f_str,
    filter_eq,
    new_row,
    paginate,
    payload,
    q3,
    sort_rows,
    touch,
)

bp = Blueprint("recovery", __name__)

CAMPAIGN_READ_ROLES = [
    "PlatformAdmin",
    "PlantOperator",
    "AssayTechnician",
    "ComplianceOfficer",
]
LOT_READ_ROLES = [
    "PlatformAdmin",
    "PlantOperator",
    "AssayTechnician",
    "ComplianceOfficer",
    "CertificationOfficer",
    "SettlementAccountant",
]
OUTPUT_READ_ROLES = [
    "PlatformAdmin",
    "AssayTechnician",
    "PlantOperator",
    "SettlementAccountant",
    "CertificationOfficer",
    "ComplianceOfficer",
]
EVENT_READ_ROLES = [
    "PlatformAdmin",
    "ComplianceOfficer",
    "PlantOperator",
    "AssayTechnician",
]
PASSPORT_READ_ROLES = [
    "PlatformAdmin",
    "CertificationOfficer",
    "ComplianceOfficer",
    "SettlementAccountant",
    "SupplierRep",
]

OCCUPYING_STATUSES = ("SCHEDULED", "RUNNING")


# ---------------------------------------------------------------------------
# campaigns
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/campaigns", ["POST"], ["PlantOperator"], 201)
def create_campaign():
    data = payload()
    line_id = f_str(data, "line_id")
    family = f_enum(data, "chemistry_family", calc.FAMILIES)
    window_start = f_dt(data, "window_start")
    window_end = f_dt(data, "window_end")
    if not window_end > window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "'window_end' must be after 'window_start'."
        )
    planned = f_num(data, "planned_input_kg", gt=0)

    line = services.line_or_404(line_id)

    incumbents = [
        c
        for c in services.campaigns_of_line(line["id"])
        if c["status"] in OCCUPYING_STATUSES
    ]
    incumbents.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]))

    for incumbent in incumbents:
        if calc.intervals_overlap(
            window_start, window_end, incumbent["window_start"], incumbent["window_end"]
        ):
            raise ApiError("ERR_CAMPAIGN_WINDOW_CONFLICT")

    buffer_hours = D(line["changeover_buffer_hours"])
    for incumbent in incumbents:
        if incumbent["chemistry_family"] == family:
            continue
        if window_start >= incumbent["window_end"]:
            gap = calc.hours_between(window_start, incumbent["window_end"])
        else:
            gap = calc.hours_between(incumbent["window_start"], window_end)
        if gap < buffer_hours:
            raise ApiError("ERR_CHANGEOVER_BUFFER_VIOLATION")

    capacity = calc.hours_between(window_end, window_start) * line["throughput_kg_per_hour"]
    if planned > capacity:
        raise ApiError("ERR_CAMPAIGN_CAPACITY_EXCEEDED")

    if family != line["chemistry_family"]:
        raise ApiError("ERR_CAMPAIGN_FAMILY_MISMATCH")

    row = new_row(
        {
            "line_id": line["id"],
            "chemistry_family": family,
            "window_start": window_start,
            "window_end": window_end,
            "planned_input_kg": planned,
            "committed_input_kg": D("0.0"),
            "status": "SCHEDULED",
            "cancel_reason": None,
        }
    )
    db.campaigns[row["id"]] = row
    return row


@endpoint(bp, "/recycling/campaigns", ["GET"], CAMPAIGN_READ_ROLES, 200)
def list_campaigns():
    data = payload()
    rows = sort_rows(db.campaigns.values())
    rows = filter_eq(rows, data, "line_id")
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(bp, "/recycling/campaigns/<campaign_id>", ["GET"], CAMPAIGN_READ_ROLES, 200)
def get_campaign(campaign_id):
    return services.campaign_or_404(campaign_id)


@endpoint(
    bp, "/recycling/campaigns/<campaign_id>/start", ["POST"], ["PlantOperator"], 200
)
def start_campaign(campaign_id):
    campaign = services.campaign_or_404(campaign_id)
    if campaign["status"] != "SCHEDULED":
        raise ApiError("ERR_CAMPAIGN_NOT_SCHEDULED")
    line = services.line_or_404(campaign["line_id"])
    if line["status"] != "AVAILABLE":
        raise ApiError("ERR_LINE_NOT_AVAILABLE")
    if not db.now() < campaign["window_end"]:
        raise ApiError("ERR_CAMPAIGN_WINDOW_CLOSED")
    campaign["status"] = "RUNNING"
    touch(campaign)
    return campaign


@endpoint(
    bp, "/recycling/campaigns/<campaign_id>/cancel", ["POST"], ["PlantOperator"], 200
)
def cancel_campaign(campaign_id):
    data = payload()
    reason = f_str(data, "cancel_reason")
    campaign = services.campaign_or_404(campaign_id)
    if campaign["status"] != "SCHEDULED":
        raise ApiError("ERR_CAMPAIGN_NOT_SCHEDULED")
    lots = services.lots_of_campaign(campaign["id"])
    if any(lot["status"] in ("CHARGED", "FINALIZED") for lot in lots):
        raise ApiError("ERR_CAMPAIGN_NOT_SCHEDULED")
    campaign["status"] = "CANCELLED"
    campaign["cancel_reason"] = reason
    for lot in lots:
        if lot["status"] == "OPEN":
            lot["status"] = "VOIDED"
            lot["void_reason"] = "CAMPAIGN_CANCELLED"
            touch(lot)
    services.recompute_campaign_committed(campaign)
    touch(campaign)
    return campaign


@endpoint(
    bp, "/recycling/campaigns/<campaign_id>/lots", ["POST"], ["PlantOperator"], 201
)
def create_lot(campaign_id):
    data = payload()
    lot_code = f_str(data, "lot_code")
    campaign = services.campaign_or_404(campaign_id)
    row = new_row(
        {
            "campaign_id": campaign["id"],
            "lot_code": lot_code,
            "charged_mass_kg": D("0.0"),
            "residue_mass_kg": None,
            "recovered_mass_kg": D("0.0"),
            "accounted_mass_kg": None,
            "unaccounted_mass_kg": None,
            "mass_balance_pct": None,
            "recycled_content_pct": None,
            "status": "OPEN",
            "finalized_at": None,
            "void_reason": None,
        }
    )
    db.lots[row["id"]] = row
    touch(campaign)
    return row


# ---------------------------------------------------------------------------
# lots
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/lots", ["GET"], LOT_READ_ROLES, 200)
def list_lots():
    data = payload()
    rows = sort_rows(db.lots.values())
    rows = filter_eq(rows, data, "campaign_id")
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(bp, "/recycling/lots/<lot_id>", ["GET"], LOT_READ_ROLES, 200)
def get_lot(lot_id):
    return services.lot_or_404(lot_id)


@endpoint(bp, "/recycling/lots/<lot_id>/charge", ["POST"], ["PlantOperator"], 200)
def charge_lot(lot_id):
    data = payload()
    module_ids = f_id_list(data, "module_ids")
    expected_version = f_int(data, "expected_lot_version")

    lot = services.lot_or_404(lot_id)
    modules = [services.module_or_404(module_id) for module_id in module_ids]

    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION")

    if lot["status"] != "OPEN":
        raise ApiError("ERR_LOT_NOT_OPEN")
    campaign = services.campaign_or_404(lot["campaign_id"])
    if campaign["status"] != "RUNNING":
        raise ApiError("ERR_CAMPAIGN_NOT_RUNNING")
    for module in modules:
        if module["status"] != "RECOVERY_QUEUE":
            raise ApiError("ERR_MODULE_NOT_IN_RECOVERY_QUEUE")

    total = D(0)
    for module in modules:
        total += module["mass_kg"]
    if campaign["committed_input_kg"] + total > campaign["planned_input_kg"]:
        raise ApiError("ERR_LOT_CHARGE_EXCEEDS_PLAN")

    for module in modules:
        intake = db.intakes.get(module["intake_id"])
        if intake is None or intake["custody_state"] != "RELEASED":
            raise ApiError("ERR_INTAKE_NOT_RELEASED")
    for module in modules:
        if calc.CHEMISTRY_FAMILY_MAP.get(module["chemistry"]) != campaign["chemistry_family"]:
            raise ApiError("ERR_MODULE_CHEMISTRY_MISMATCH")

    touched_intakes = []
    for module in modules:
        module["status"] = "CHARGED"
        module["lot_id"] = lot["id"]
        touch(module)
        intake = db.intakes[module["intake_id"]]
        if intake["id"] not in [i["id"] for i in touched_intakes]:
            touched_intakes.append(intake)

    lot["status"] = "CHARGED"
    services.recompute_lot_charged_mass(lot)
    touch(lot)
    for intake in touched_intakes:
        services.recompute_intake_masses(intake)
        touch(intake)
    services.recompute_campaign_committed(campaign)
    touch(campaign)
    return lot


@endpoint(
    bp, "/recycling/lots/<lot_id>/recovery-outputs", ["POST"], ["AssayTechnician"], 201
)
def create_recovery_output(lot_id):
    data = payload()
    metal = f_enum(data, "metal", calc.METALS)
    mass = f_num(data, "recovered_mass_kg", gt=0)
    purity = f_num(data, "assay_purity_pct", gt=0, le=100)

    lot = services.lot_or_404(lot_id)

    for existing in calc.lot_outputs(lot["id"]):
        if existing["metal"] == metal:
            raise ApiError(
                "ERR_INVALID_REQUEST", "'metal' already has an assay line on this lot."
            )

    if lot["status"] != "CHARGED":
        raise ApiError("ERR_LOT_NOT_CHARGED")

    campaign = services.campaign_of_lot(lot)
    line = services.line_of_campaign(campaign) if campaign else None
    if (
        metal in calc.HYDROMET_ONLY_METALS
        and line is not None
        and line["line_type"] == "MECHANICAL"
    ):
        raise ApiError("ERR_METAL_NOT_RECOVERABLE_ON_LINE")

    row = new_row(
        {
            "lot_id": lot["id"],
            "metal": metal,
            "recovered_mass_kg": mass,
            "assay_purity_pct": purity,
            "recorded_by_user_id": g.user_id,
        },
        common_fields=False,
    )
    db.outputs[row["id"]] = row
    services.recompute_lot_recovered(lot)
    touch(lot)
    return row


@endpoint(bp, "/recycling/lots/<lot_id>/recovery-outputs", ["GET"], OUTPUT_READ_ROLES, 200)
def list_recovery_outputs(lot_id):
    data = payload()
    lot = services.lot_or_404(lot_id)
    rows = calc.lot_outputs(lot["id"])
    rows = filter_eq(rows, data, "metal")
    return paginate(rows, data)


@endpoint(bp, "/recycling/lots/<lot_id>/finalize", ["POST"], ["AssayTechnician"], 200)
def finalize_lot(lot_id):
    data = payload()
    residue = f_num(data, "residue_mass_kg", ge=0)

    lot = services.lot_or_404(lot_id)
    if lot["status"] != "CHARGED":
        raise ApiError("ERR_LOT_NOT_CHARGED")

    outputs = calc.lot_outputs(lot["id"])
    if not outputs:
        raise ApiError("ERR_NO_RECOVERY_OUTPUTS")

    ledger = calc.lot_mass_balance(lot, residue)
    if ledger["mass_balance_pct"] < calc.MASS_BALANCE_FLOOR_PCT:
        raise ApiError("ERR_MASS_BALANCE_OUT_OF_TOLERANCE")

    contributors = services.contributor_intakes(lot["id"])
    settlements = []
    for intake in contributors:
        for settlement in services.settlements_of_intake(intake["id"]):
            if settlement["state"] != "DRAFT":
                raise ApiError("ERR_SETTLEMENT_NOT_DRAFT")
            settlements.append((settlement, intake))

    finalized_at = db.now()
    for output in outputs:
        if output["metal"] not in calc.PAYABLE_METALS:
            continue
        if calc.lookup_index_price(output["metal"], finalized_at) is None:
            raise ApiError("ERR_INDEX_PRICE_UNAVAILABLE")

    # strike counts are read as they stand at the start of the request
    strike_snapshot = {}
    for settlement, intake in settlements:
        supplier_id = settlement["supplier_id"]
        if supplier_id in db.suppliers and supplier_id not in strike_snapshot:
            strike_snapshot[supplier_id] = db.suppliers[supplier_id]["quality_strike_count"]

    # link 1
    lot["status"] = "FINALIZED"
    lot["residue_mass_kg"] = q3(residue)
    lot["recovered_mass_kg"] = ledger["recovered_mass_kg"]
    lot["accounted_mass_kg"] = ledger["accounted_mass_kg"]
    lot["unaccounted_mass_kg"] = ledger["unaccounted_mass_kg"]
    lot["mass_balance_pct"] = ledger["mass_balance_pct"]
    lot["recycled_content_pct"] = ledger["recycled_content_pct"]
    lot["finalized_at"] = finalized_at
    touch(lot)

    # link 2
    for module in services.modules_of_lot(lot["id"]):
        if module["status"] == "CHARGED":
            module["status"] = "CONSUMED"
            touch(module)

    # link 3 and link 4
    for settlement, intake in settlements:
        supplier = db.suppliers.get(settlement["supplier_id"])
        services.price_settlement(
            settlement,
            intake,
            supplier,
            "FINAL",
            finalized_at,
            lot=lot,
            strike_count=strike_snapshot.get(settlement["supplier_id"], 0),
        )
        settlement["_lot_id"] = lot["id"]
        touch(settlement)
        if (
            supplier is not None
            and settlement["max_variance_pp"] is not None
            and settlement["max_variance_pp"] > calc.SEVERE_VARIANCE_PP
        ):
            supplier["quality_strike_count"] += 1
            touch(supplier)

    services.bubble_up_campaign_close(services.campaign_of_lot(lot))
    return lot


@endpoint(bp, "/recycling/lots/<lot_id>/void", ["POST"], ["PlantOperator"], 200)
def void_lot(lot_id):
    data = payload()
    reason = f_str(data, "void_reason")
    lot = services.lot_or_404(lot_id)
    if lot["status"] not in ("OPEN", "CHARGED"):
        raise ApiError("ERR_LOT_NOT_OPEN")

    lot["status"] = "VOIDED"
    lot["void_reason"] = reason

    touched_intakes = []
    for module in services.modules_of_lot(lot["id"]):
        if module["status"] != "CHARGED":
            continue
        module["status"] = "RECOVERY_QUEUE"
        module["lot_id"] = None
        touch(module)
        intake = db.intakes.get(module["intake_id"])
        if intake is not None and intake["id"] not in [i["id"] for i in touched_intakes]:
            touched_intakes.append(intake)

    lot["charged_mass_kg"] = D("0.0")
    touch(lot)
    for intake in touched_intakes:
        services.recompute_intake_masses(intake)
        touch(intake)
    campaign = services.campaign_of_lot(lot)
    if campaign is not None:
        services.recompute_campaign_committed(campaign)
        touch(campaign)
        services.bubble_up_campaign_close(campaign)
    return lot


# ---------------------------------------------------------------------------
# discharge events
# ---------------------------------------------------------------------------


@endpoint(
    bp, "/recycling/lots/<lot_id>/discharge-events", ["POST"], ["ComplianceOfficer"], 201
)
def create_discharge_event(lot_id):
    data = payload()
    allotment_id = f_str(data, "allotment_id")
    event_date = f_dt(data, "event_date")
    mass = f_num(data, "mass_kg", gt=0)
    analyte = f_enum(data, "analyte", ("NICKEL_DISSOLVED", "FLUORIDE", "TSS"))

    lot = services.lot_or_404(lot_id)
    allotment = services.allotment_or_404(allotment_id)

    # lazy, clock-driven expiry evaluated at the very start of the booking
    if allotment["status"] == "ACTIVE" and db.now() > allotment["valid_to"]:
        allotment["status"] = "EXPIRED"
        touch(allotment)
    if allotment["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE")

    if event_date < allotment["valid_from"] or event_date > allotment["valid_to"]:
        raise ApiError("ERR_PERMIT_WINDOW_EXCLUDED")

    bucket = calc.permit_daily_bucket(allotment["id"], event_date)
    if q3(bucket + mass) > allotment["daily_cap_kg"]:
        raise ApiError("ERR_DISCHARGE_DAILY_CAP_EXCEEDED")

    row = new_row(
        {
            "allotment_id": allotment["id"],
            "lot_id": lot["id"],
            "event_date": event_date,
            "mass_kg": mass,
            "analyte": analyte,
            "status": "POSTED",
            "void_reason": None,
        }
    )
    db.events[row["id"]] = row
    services.recompute_permit_consumed(allotment)
    touch(allotment)
    return row


@endpoint(bp, "/recycling/discharge-events", ["GET"], EVENT_READ_ROLES, 200)
def list_discharge_events():
    data = payload()
    rows = sort_rows(db.events.values())
    rows = filter_eq(rows, data, "allotment_id")
    rows = filter_eq(rows, data, "lot_id")
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(bp, "/recycling/discharge-events/<event_id>", ["GET"], EVENT_READ_ROLES, 200)
def get_discharge_event(event_id):
    return services.event_or_404(event_id)


@endpoint(
    bp,
    "/recycling/discharge-events/<event_id>/void",
    ["POST"],
    ["ComplianceOfficer"],
    200,
)
def void_discharge_event(event_id):
    data = payload()
    reason = f_str(data, "void_reason")
    event = services.event_or_404(event_id)
    if event["status"] != "POSTED":
        raise ApiError("ERR_DISCHARGE_EVENT_NOT_POSTED")
    event["status"] = "VOIDED"
    event["void_reason"] = reason
    touch(event)
    allotment = db.allotments.get(event["allotment_id"])
    if allotment is not None:
        services.recompute_permit_consumed(allotment)
        touch(allotment)
    return event


# ---------------------------------------------------------------------------
# passports
# ---------------------------------------------------------------------------


@endpoint(
    bp, "/recycling/lots/<lot_id>/passports", ["POST"], ["CertificationOfficer"], 201
)
def create_passport(lot_id):
    data = payload()
    passport_code = f_str(data, "passport_code")
    customer_name = f_str(data, "customer_name")

    for existing in db.passports.values():
        if existing["passport_code"] == passport_code:
            raise ApiError("ERR_INVALID_REQUEST", "'passport_code' must be globally unique.")

    lot = services.lot_or_404(lot_id)

    for existing in db.passports.values():
        if existing["lot_id"] == lot["id"] and existing["status"] == "ISSUED":
            raise ApiError("ERR_PASSPORT_ALREADY_ISSUED")

    content_pct = lot["recycled_content_pct"]
    if content_pct is None or content_pct < calc.PASSPORT_MIN_CONTENT_PCT:
        raise ApiError("ERR_RECYCLED_CONTENT_BELOW_MINIMUM")

    metal_content = [
        {
            "metal": output["metal"],
            "recovered_mass_kg": output["recovered_mass_kg"],
            "assay_purity_pct": output["assay_purity_pct"],
        }
        for output in calc.lot_outputs(lot["id"])
    ]
    row = new_row(
        {
            "lot_id": lot["id"],
            "passport_code": passport_code,
            "customer_name": customer_name,
            "recycled_content_pct": content_pct,
            "metal_content": metal_content,
            "status": "ISSUED",
            "issued_at": db.now(),
            "revoked_reason": None,
        }
    )
    db.passports[row["id"]] = row
    return row


@endpoint(bp, "/recycling/passports", ["GET"], PASSPORT_READ_ROLES, 200)
def list_passports():
    data = payload()
    rows = sort_rows(db.passports.values())
    rows = filter_eq(rows, data, "lot_id")
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(bp, "/recycling/passports/<passport_id>", ["GET"], PASSPORT_READ_ROLES, 200)
def get_passport(passport_id):
    return services.passport_or_404(passport_id)


@endpoint(
    bp,
    "/recycling/passports/<passport_id>/revoke",
    ["POST"],
    ["CertificationOfficer"],
    200,
)
def revoke_passport(passport_id):
    data = payload()
    reason = f_str(data, "revoked_reason")
    passport = services.passport_or_404(passport_id)
    if passport["status"] != "ISSUED":
        raise ApiError("ERR_PASSPORT_NOT_ISSUED")
    passport["status"] = "REVOKED"
    passport["revoked_reason"] = reason
    touch(passport)
    return passport
