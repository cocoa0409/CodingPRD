"""Casing, TireAsset, TireSurvey and the casing credit ledger read surface."""

from flask import Blueprint, g

import calc
import common
import derive
import errors
import serialize
import validate as v
from auth import endpoint, fleet_scope, is_fleet_manager, scope_filter_value
from db import db, insert, ordered, touch
from errors import fail
from response import created, ok

bp = Blueprint("tire", __name__)


# ================================================================ Casing

@bp.post("/casings")
@endpoint("DealerAdmin", "TireTechnician")
def create_casing():
    payload = v.body()
    fleet_account_id = v.s_str(payload, "fleet_account_id")
    casing_serial = v.s_str(payload, "casing_serial")
    brand = v.s_str(payload, "brand")
    casing_spec_code = v.s_str(payload, "casing_spec_code")
    intended_position = v.s_enum(payload, "intended_position", derive.POSITIONS)
    scrap_weight_lbs = v.s_int(payload, "scrap_weight_lbs", minimum=1, maximum=500)
    retread_count = v.s_int(payload, "retread_count", required=False, minimum=0, maximum=5)
    if retread_count is None:
        retread_count = 0
    common.fleet(fleet_account_id)
    for row in db.casings.values():
        if row["casing_serial"] == casing_serial:
            fail(errors.ERR_DUPLICATE_CASING_SERIAL)
    row = insert(
        db.casings,
        {
            "fleet_account_id": fleet_account_id,
            "casing_serial": casing_serial,
            "brand": brand,
            "casing_spec_code": casing_spec_code,
            "intended_position": intended_position,
            "retread_count": retread_count,
            "scrap_weight_lbs": scrap_weight_lbs,
            "status": "ON_WHEEL",
            "inspection_grade": None,
            "inspected_by_user_id": None,
            "collected_at_location_id": None,
            "scrap_manifest_id": None,
            "rejection_reason": None,
        },
    )
    return created(serialize.casing(row))


@bp.post("/casings/<casing_id>/collect")
@endpoint("TireTechnician")
def collect_casing(casing_id):
    row = common.casing(casing_id)
    payload = v.body()
    location_id = v.s_str(payload, "collected_at_location_id")
    common.location(location_id)
    if row["status"] != "ON_WHEEL":
        fail(errors.ERR_CASING_INVALID_STATE)
    for asset in derive.casing_assets(row["id"]):
        if asset["status"] not in ("IN_INVENTORY", "PULLED", "SCRAPPED"):
            fail(errors.ERR_CASING_INVALID_STATE)
    row["collected_at_location_id"] = location_id
    row["status"] = "COLLECTED"
    touch(row)
    return ok(serialize.casing(row))


@bp.post("/casings/<casing_id>/inspect")
@endpoint("CasingInspector")
def inspect_casing(casing_id):
    row = common.casing(casing_id)
    payload = v.body()
    grade = v.s_enum(payload, "grade", derive.GRADES)
    expected_version = v.s_int(payload, "expected_casing_version")

    retreadable = grade in ("A", "B", "C")
    if row["status"] == "COLLECTED":
        pass
    elif row["status"] == "INSPECTED" and retreadable:
        if derive.casing_has_live_job(row["id"]):
            fail(errors.ERR_CASING_INVALID_STATE)
    else:
        fail(errors.ERR_CASING_INVALID_STATE)

    if expected_version != row["version"]:
        fail(errors.ERR_STALE_CASING_VERSION)

    fleet_row = db.fleet_accounts.get(row["fleet_account_id"])
    # Grading always requires the governing policy, whatever the grade (PRD 3.4).
    if derive.find_policy(row["fleet_account_id"], row["intended_position"]) is None:
        fail(errors.ERR_TIRE_POLICY_MISSING)

    if not retreadable:
        # COLLECTED + REJECT: no ledger entry at all.
        row["inspection_grade"] = grade
        row["inspected_by_user_id"] = g.user_id
        row["status"] = "REJECTED"
        touch(row)
        touch(fleet_row)
        return ok(serialize.casing(row))

    superseding = row["status"] == "INSPECTED"
    prior_credit = derive.casing_provisional_credit_cents(row["id"])
    accrual_cents = calc.credit_provisional_cents(
        row["fleet_account_id"], grade, row["retread_count"], db.clock_date()
    )

    balance = derive.fleet_balance_cents(row["fleet_account_id"])
    if superseding:
        if balance - prior_credit < 0:
            fail(errors.ERR_CREDIT_BALANCE_NEGATIVE)
        balance -= prior_credit
    if balance + accrual_cents < 0:
        fail(errors.ERR_CREDIT_BALANCE_NEGATIVE)

    if superseding:
        common.post_entry(
            fleet_row,
            "REVERSAL",
            -prior_credit,
            "CASING",
            row["id"],
            "Reversal of provisional casing credit superseded by re-grade",
            casing_id=row["id"],
        )
    common.post_entry(
        fleet_row,
        "ACCRUAL",
        accrual_cents,
        "CASING",
        row["id"],
        "Provisional casing credit accrual at grade %s" % grade,
        casing_id=row["id"],
    )

    row["inspection_grade"] = grade
    row["inspected_by_user_id"] = g.user_id
    row["status"] = "INSPECTED"
    touch(row)
    touch(fleet_row)
    return ok(serialize.casing(row))


@bp.post("/casings/<casing_id>/reject")
@endpoint("CasingInspector")
def reject_casing(casing_id):
    row = common.casing(casing_id)
    payload = v.body()
    rejection_reason = v.s_str(payload, "rejection_reason")
    if row["status"] != "INSPECTED" or derive.casing_has_live_job(row["id"]):
        fail(errors.ERR_CASING_INVALID_STATE)
    row["status"] = "REJECTED"
    row["rejection_reason"] = rejection_reason
    touch(row)
    return ok(serialize.casing(row))


_CASING_READERS = (
    "DealerAdmin",
    "FleetManager",
    "TireTechnician",
    "CasingInspector",
    "PlantScheduler",
    "ComplianceOfficer",
)


@bp.get("/casings/<casing_id>")
@endpoint(*_CASING_READERS)
def get_casing(casing_id):
    row = common.casing(casing_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.casing(row))


@bp.get("/casings")
@endpoint(*_CASING_READERS)
def list_casings():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    rows = common.filtered(
        db.casings,
        [
            ("fleet_account_id", fleet_account_id),
            ("collected_at_location_id", v.q_str("collected_at_location_id")),
            ("scrap_manifest_id", v.q_str("scrap_manifest_id")),
            ("status", v.q_enum("status", derive.CASING_STATUSES)),
            ("intended_position", v.q_enum("intended_position", derive.POSITIONS)),
            ("inspection_grade", v.q_enum("inspection_grade", derive.GRADES)),
        ],
    )
    return common.page(rows, serialize.casing)


# ================================================================ TireAsset

def _new_asset(fleet_account_id, casing_id, brand, cost_basis_cents):
    return insert(
        db.tire_assets,
        {
            "fleet_account_id": fleet_account_id,
            "casing_id": casing_id,
            "brand": brand,
            "cost_basis_cents": cost_basis_cents,
            "vehicle_id": None,
            "position": None,
            "status": "IN_INVENTORY",
            "mounted_at": None,
            "mounted_at_dt": None,
            "odometer_at_mount": None,
            "tread_depth_at_mount_32nds": None,
            "replaced_tire_asset_id": None,
            "pull_reason": None,
        },
    )


@bp.post("/tire-assets")
@endpoint("DealerAdmin", "TireTechnician")
def create_tire_asset():
    payload = v.body()
    fleet_account_id = v.s_str(payload, "fleet_account_id")
    casing_id = v.s_str(payload, "casing_id")
    brand = v.s_str(payload, "brand")
    cost_basis_cents = v.s_int(payload, "cost_basis_cents", minimum=0)
    common.fleet(fleet_account_id)
    casing_row = common.casing(casing_id)
    if casing_row["fleet_account_id"] != fleet_account_id:
        fail(errors.ERR_FLEET_MISMATCH)
    row = _new_asset(fleet_account_id, casing_id, brand, cost_basis_cents)
    return created(serialize.tire_asset(row))


def _release_casing_from_holding(casing_row):
    """Closes the retread cycle: RETREADED -> ON_WHEEL, clears the holding link."""
    if casing_row is not None and casing_row["status"] == "RETREADED":
        casing_row["status"] = "ON_WHEEL"
        casing_row["collected_at_location_id"] = None
        touch(casing_row)


@bp.post("/tire-assets/<tire_asset_id>/mount")
@endpoint("TireTechnician")
def mount_tire_asset(tire_asset_id):
    row = common.tire_asset(tire_asset_id)
    payload = v.body()
    vehicle_id = v.s_str(payload, "vehicle_id")
    position = v.s_enum(payload, "position", derive.POSITIONS)
    mounted_raw, mounted_dt = v.s_datetime(payload, "mounted_at")
    odometer_at_mount = v.s_int(payload, "odometer_at_mount", minimum=0)
    tread_depth = v.s_int(payload, "tread_depth_at_mount_32nds", minimum=0, maximum=32)
    vehicle_row = common.vehicle(vehicle_id)

    if row["status"] != "IN_INVENTORY":
        fail(errors.ERR_TIRE_ASSET_INVALID_STATE)

    policy = derive.find_policy(row["fleet_account_id"], position)
    if policy is not None and not tread_depth > policy["min_tread_depth_32nds"]:
        fail(errors.ERR_TREAD_BELOW_POLICY_MINIMUM)
    if policy is None:
        fail(errors.ERR_TIRE_POLICY_MISSING)
    if row["brand"] not in policy["approved_brands"]:
        fail(errors.ERR_BRAND_NOT_APPROVED)
    casing_row = db.casings.get(row["casing_id"])
    if policy["casing_spec_code"] != "ANY" and (
        casing_row is None or casing_row["casing_spec_code"] != policy["casing_spec_code"]
    ):
        fail(errors.ERR_CASING_SPEC_MISMATCH)
    if vehicle_row["fleet_account_id"] != row["fleet_account_id"]:
        fail(errors.ERR_FLEET_MISMATCH)
    for other in db.tire_assets.values():
        if (
            other["id"] != row["id"]
            and other["vehicle_id"] == vehicle_id
            and other["position"] == position
            and other["status"] in ("MOUNTED", "PULL_FLAGGED")
        ):
            fail(errors.ERR_POSITION_OCCUPIED)

    row["vehicle_id"] = vehicle_id
    row["position"] = position
    row["mounted_at"] = mounted_raw
    row["mounted_at_dt"] = mounted_dt
    row["odometer_at_mount"] = odometer_at_mount
    row["tread_depth_at_mount_32nds"] = tread_depth
    row["status"] = "MOUNTED"
    touch(row)
    _release_casing_from_holding(casing_row)
    return ok(serialize.tire_asset(row))


@bp.post("/tire-assets/<tire_asset_id>/pull")
@endpoint("TireTechnician")
def pull_tire_asset(tire_asset_id):
    row = common.tire_asset(tire_asset_id)
    payload = v.body()
    pull_reason = v.s_str(payload, "pull_reason")
    if row["status"] not in ("MOUNTED", "PULL_FLAGGED"):
        fail(errors.ERR_TIRE_ASSET_INVALID_STATE)
    row["status"] = "PULLED"
    row["pull_reason"] = pull_reason
    touch(row)
    return ok(serialize.tire_asset(row))


@bp.post("/tire-assets/<tire_asset_id>/surveys")
@endpoint("TireTechnician")
def create_survey(tire_asset_id):
    asset = common.tire_asset(tire_asset_id)
    payload = v.body()
    surveyed_raw, surveyed_dt = v.s_datetime(payload, "surveyed_at")
    pressure_psi = v.s_num(payload, "pressure_psi", minimum=0, maximum=200)
    tread_depth = v.s_int(payload, "tread_depth_32nds", minimum=0, maximum=32)
    odometer_miles = v.s_int(payload, "odometer_miles", minimum=0)

    if asset["status"] not in ("MOUNTED", "PULL_FLAGGED"):
        fail(errors.ERR_TIRE_ASSET_INVALID_STATE)

    policy = derive.find_policy(asset["fleet_account_id"], asset["position"])
    if policy is None:
        fail(errors.ERR_TIRE_POLICY_MISSING)

    floor_miles = asset["odometer_at_mount"] or 0
    previous = derive.latest_survey(asset["id"])
    if previous is not None:
        floor_miles = max(floor_miles, previous["odometer_miles"])
    if odometer_miles < floor_miles:
        fail(errors.ERR_ODOMETER_REGRESSION)

    deviation, finding_code, pull_recommended = calc.survey_finding(
        pressure_psi, tread_depth, policy
    )
    row = insert(
        db.tire_surveys,
        {
            "tire_asset_id": asset["id"],
            "surveyed_at": surveyed_raw,
            "surveyed_at_dt": surveyed_dt,
            "pressure_psi": pressure_psi,
            "tread_depth_32nds": tread_depth,
            "odometer_miles": odometer_miles,
            "surveyed_by_user_id": g.user_id,
            "pressure_deviation_pct": deviation,
            "finding_code": finding_code,
            "pull_recommended": pull_recommended,
        },
        versioned=False,
    )
    if pull_recommended and asset["status"] == "MOUNTED":
        asset["status"] = "PULL_FLAGGED"
        touch(asset)
    elif finding_code == "COMPLIANT" and asset["status"] == "PULL_FLAGGED":
        asset["status"] = "MOUNTED"
        touch(asset)
    return created(serialize.tire_survey(row))


@bp.get("/tire-assets/<tire_asset_id>")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician", "PlantScheduler")
def get_tire_asset(tire_asset_id):
    row = common.tire_asset(tire_asset_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.tire_asset(row))


@bp.get("/tire-assets")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician", "PlantScheduler")
def list_tire_assets():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    rows = common.filtered(
        db.tire_assets,
        [
            ("fleet_account_id", fleet_account_id),
            ("casing_id", v.q_str("casing_id")),
            ("vehicle_id", v.q_str("vehicle_id")),
            ("replaced_tire_asset_id", v.q_str("replaced_tire_asset_id")),
            ("status", v.q_enum("status", derive.TIRE_ASSET_STATUSES)),
            ("position", v.q_enum("position", derive.POSITIONS)),
            ("brand", v.q_str("brand")),
        ],
    )
    return common.page(rows, serialize.tire_asset)


# ================================================================ TireSurvey

@bp.get("/tire-surveys/<survey_id>")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician")
def get_survey(survey_id):
    row = common.tire_survey(survey_id)
    asset = db.tire_assets.get(row["tire_asset_id"])
    if asset is not None:
        fleet_scope(asset["fleet_account_id"])
    return ok(serialize.tire_survey(row))


@bp.get("/tire-surveys")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician")
def list_surveys():
    tire_asset_id = v.q_str("tire_asset_id")
    finding_code = v.q_enum("finding_code", derive.FINDING_CODES)
    pull_recommended = v.q_bool("pull_recommended")
    rows = []
    for row in db.tire_surveys.values():
        if tire_asset_id is not None and row["tire_asset_id"] != tire_asset_id:
            continue
        if finding_code is not None and row["finding_code"] != finding_code:
            continue
        if pull_recommended is not None and row["pull_recommended"] != pull_recommended:
            continue
        if is_fleet_manager():
            asset = db.tire_assets.get(row["tire_asset_id"])
            if asset is None or asset["fleet_account_id"] != g.user_id:
                continue
        rows.append(row)
    rows.sort(key=lambda s: (s["surveyed_at_dt"], s["created_at"], s["_seq"]))
    return common.page(rows, serialize.tire_survey)


# ================================================================ CasingCreditEntry

@bp.get("/casing-credit-entries/<entry_id>")
@endpoint("DealerAdmin", "BillingClerk", "FleetManager", "CasingInspector")
def get_credit_entry(entry_id):
    row = common.credit_entry(entry_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.casing_credit_entry(row))


@bp.get("/casing-credit-entries")
@endpoint("DealerAdmin", "BillingClerk", "FleetManager", "CasingInspector")
def list_credit_entries():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    casing_id = v.q_str("casing_id")
    entry_type = v.q_enum("entry_type", derive.ENTRY_TYPES)
    source_entity_type = v.q_enum("source_entity_type", derive.SOURCE_ENTITY_TYPES)
    rows = [
        row for row in db.casing_credit_entries.values()
        if (fleet_account_id is None or row["fleet_account_id"] == fleet_account_id)
        and (casing_id is None or row["casing_id"] == casing_id)
        and (entry_type is None or row["entry_type"] == entry_type)
        and (source_entity_type is None or row["source_entity_type"] == source_entity_type)
    ]
    return common.page(derive.ledger_replay_order(rows), serialize.casing_credit_entry)
