"""Derived state, lazy expiry and the cascades (PRD Sections 2.5, 2.8, 3.1-3.9)."""
from datetime import timedelta

from db import db, touch, ordered
from timeutil import add_days, floor_day_diff
from services import calc

LIVE_SLOT_STATUSES = ("RESERVED", "CONFIRMED", "IN_BUILD", "COMPLETED")
COUNTED_SLOT_STATUSES = ("RESERVED", "CONFIRMED", "IN_BUILD")


# --------------------------------------------------------------------------
# equipment model posture (PRD Section 3.1)
# --------------------------------------------------------------------------
def listings_for_model(model_id):
    return [l for l in ordered(db.certification_listings) if l["equipment_model_id"] == model_id]


def recompute_model_posture(model):
    listings = listings_for_model(model["id"])
    covered = set()
    for listing in listings:
        if listing["status"] == "LISTED" and listing["expires_on"] is not None \
                and db.clock < listing["expires_on"]:
            covered.update(listing["scopes"])
    covered_scopes = calc.sort_scopes(covered)

    if any(l["status"] == "SUSPENDED" for l in listings):
        posture = "SUSPENDED"
    elif all(scope in covered for scope in model["required_scopes"]):
        posture = "LISTED"
    elif covered_scopes:
        posture = "PARTIAL"
    else:
        posture = "UNLISTED"

    if model["covered_scopes"] != covered_scopes or model["certification_posture"] != posture:
        model["covered_scopes"] = covered_scopes
        model["certification_posture"] = posture
        touch(model)
    return posture


def configurations_for_model(model_id):
    return [c for c in ordered(db.chain_configurations) if c["equipment_model_id"] == model_id]


def cascade_suspension(model):
    """Hops three to six of the compliance cascade (PRD Section 3.2)."""
    held = []
    for config in configurations_for_model(model["id"]):
        if config["status"] == "RELEASED":
            config["status"] = "COMPLIANCE_HOLD"
            touch(config)
            held.append(config)
    if not held:
        return
    held_ids = set(c["id"] for c in held)

    affected_orders = [so for so in ordered(db.site_orders)
                       if so["chain_configuration_id"] in held_ids]
    for site_order in affected_orders:
        for slot in slots_for_site_order(site_order["id"]):
            if slot["status"] in ("RESERVED", "CONFIRMED"):
                slot["status"] = "CANCELLED"
                touch(slot)
                line = db.build_lines.get(slot["build_line_id"])
                if line is not None:
                    line["committed_units"] -= slot["units"]
                    touch(line)

    programs = []
    for site_order in affected_orders:
        if not live_slots_for_site_order(site_order["id"]):
            if site_order["fulfillment_status"] == "SCHEDULED":
                site_order["fulfillment_status"] = "PENDING"
                touch(site_order)
        recompute_site_order_commitment(site_order)
        if site_order["construction_program_id"] not in programs:
            programs.append(site_order["construction_program_id"])

    for program_id in programs:
        program = db.construction_programs.get(program_id)
        if program is not None:
            recompute_program_posture(program)


def release_compliance_holds(model):
    for config in configurations_for_model(model["id"]):
        if config["status"] == "COMPLIANCE_HOLD":
            config["status"] = "RELEASED"
            touch(config)


# --------------------------------------------------------------------------
# configuration pricing (PRD Section 3.3)
# --------------------------------------------------------------------------
def configuration_price_pair(config):
    model = db.equipment_models[config["equipment_model_id"]]
    account = db.chain_accounts[config["chain_account_id"]]
    return calc.configuration_prices(
        model["base_price_cents"],
        config["option_codes"],
        config["controls_package"],
        config["branding_kit"],
        account["contracted_unit_volume"],
    )


def refresh_indicative_price(config):
    indicative, _firm = configuration_price_pair(config)
    if config["indicative_unit_price_cents"] != indicative:
        config["indicative_unit_price_cents"] = indicative
        touch(config)
    return indicative


# --------------------------------------------------------------------------
# site order commitment / programme posture (PRD Section 3.6)
# --------------------------------------------------------------------------
def slots_for_site_order(site_order_id):
    return [s for s in ordered(db.production_slots) if s["site_order_id"] == site_order_id]


def live_slots_for_site_order(site_order_id):
    return [s for s in slots_for_site_order(site_order_id) if s["status"] in LIVE_SLOT_STATUSES]


def recompute_site_order_commitment(site_order):
    candidates = live_slots_for_site_order(site_order["id"])
    if not candidates:
        projected = None
        slack = None
        status = "UNSCHEDULED"
    else:
        # latest window_end wins, earliest created_at breaks the tie
        by_created = sorted(candidates, key=lambda s: (s["created_at"], s["_seq"]))
        selected = sorted(by_created, key=lambda s: s["window_end"], reverse=True)[0]
        projected = selected["window_end"] + timedelta(days=calc.TRANSIT_DAYS)
        slack = floor_day_diff(site_order["committed_delivery_date"], projected)
        if slack >= 0:
            status = "COMMITTED"
        elif slack >= -calc.AT_RISK_GRACE_DAYS:
            status = "AT_RISK"
        else:
            status = "BREACHED"

    if site_order["commitment_status"] == "WAIVED":
        status = "WAIVED"  # terminal and sticky

    changed = False
    if site_order["projected_delivery_date"] != projected:
        site_order["projected_delivery_date"] = projected
        changed = True
    if site_order["slack_days"] != slack:
        site_order["slack_days"] = slack
        changed = True
    if site_order["commitment_status"] != status:
        site_order["commitment_status"] = status
        changed = True
    if changed:
        touch(site_order)
    return site_order


def recompute_program_posture(program):
    children = [so for so in ordered(db.site_orders)
                if so["construction_program_id"] == program["id"]]
    considered = [so["commitment_status"] for so in children
                  if so["commitment_status"] in ("COMMITTED", "AT_RISK", "BREACHED")]
    if "BREACHED" in considered:
        posture = "BREACHED"
    elif "AT_RISK" in considered:
        posture = "AT_RISK"
    else:
        posture = "ON_TRACK"
    if program["commit_posture"] != posture:
        program["commit_posture"] = posture
        touch(program)
    return posture


def refresh_site_order(site_order):
    """Recompute the commitment dimension and the parent programme's posture."""
    recompute_site_order_commitment(site_order)
    program = db.construction_programs.get(site_order["construction_program_id"])
    if program is not None:
        recompute_program_posture(program)


# --------------------------------------------------------------------------
# connected units (PRD Section 3.8, 3.9)
# --------------------------------------------------------------------------
def reference_firmware_version(equipment_model_id):
    completed = [c for c in ordered(db.firmware_campaigns)
                 if c["equipment_model_id"] == equipment_model_id and c["status"] == "COMPLETED"]
    if not completed:
        return None
    by_created = sorted(completed, key=lambda c: (c["created_at"], c["_seq"]))
    latest = sorted(by_created, key=lambda c: c["window_start"], reverse=True)[0]
    return latest["target_firmware_version"]


def compute_health_score(unit):
    score = 100
    score -= calc.FAULT_WEIGHT * int(unit["fault_count_30d"])
    score -= calc.HEARTBEAT_WEIGHT * int(unit["missed_heartbeat_count"])
    reference = reference_firmware_version(unit["equipment_model_id"])
    if reference is not None and unit["firmware_version"] == reference:
        score += calc.FIRMWARE_CURRENT_BONUS
    if score < 0:
        score = 0
    elif score > 100:
        score = 100
    return score


def refresh_health_score(unit):
    score = compute_health_score(unit)
    if unit["health_score"] != score:
        unit["health_score"] = score
        touch(unit)
    return score


def refresh_unit_coverage(unit):
    """Lazy expiry, evaluated on any read or write touching the unit (PRD Section 3.9)."""
    status = unit["service_program_status"]
    if status in ("ACTIVE", "EXTENDED"):
        end = unit["coverage_end_date"]
        if end is not None and db.clock >= end:
            unit["service_program_status"] = "EXPIRED"
            touch(unit)
    elif status == "GRACE":
        grace_end = unit["grace_expires_on"]
        if grace_end is not None and db.clock >= grace_end:
            unit["service_program_status"] = "EXPIRED"
            touch(unit)
    return unit


# --------------------------------------------------------------------------
# service partner claim authority (PRD Section 3.9)
# --------------------------------------------------------------------------
def certifications_for_partner(partner_id):
    return [c for c in ordered(db.technician_certifications)
            if c["service_partner_id"] == partner_id]


def compute_authorized_model_ids(partner):
    counts = {}
    for cert in certifications_for_partner(partner["id"]):
        if cert["status"] != "PASSED":
            continue
        if cert["expires_on"] is None or not db.clock < cert["expires_on"]:
            continue
        counts[cert["equipment_model_id"]] = counts.get(cert["equipment_model_id"], 0) + 1
    qualifying = [mid for mid, count in counts.items()
                  if count >= calc.MIN_CERTIFIED_TECHS_PER_MODEL]
    models = [m for m in ordered(db.equipment_models) if m["id"] in qualifying]
    return [m["id"] for m in models]


def refresh_partner_authority(partner):
    model_ids = compute_authorized_model_ids(partner)
    if partner["authorized_model_ids"] != model_ids:
        partner["authorized_model_ids"] = model_ids
        touch(partner)
    return model_ids


# --------------------------------------------------------------------------
# clock advance reconciliation (PRD Section 2.5)
# --------------------------------------------------------------------------
def reconcile_after_clock_move():
    for model in ordered(db.equipment_models):
        recompute_model_posture(model)
    for partner in ordered(db.service_partners):
        refresh_partner_authority(partner)
    for unit in ordered(db.connected_units):
        refresh_unit_coverage(unit)
    for site_order in ordered(db.site_orders):
        recompute_site_order_commitment(site_order)
    for program in ordered(db.construction_programs):
        recompute_program_posture(program)
