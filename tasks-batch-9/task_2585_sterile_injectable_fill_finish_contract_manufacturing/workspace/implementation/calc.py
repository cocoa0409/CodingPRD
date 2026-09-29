"""Every derived quantity in the specification.

The pinned rounding order of PRD 2.9 is reproduced literally here: each
function applies round-half-up or ceiling at exactly the point the prose names
it and nowhere else. No function in this module writes to the store.
"""

from decimal import Decimal

from common import ceil_dec, clock_now, dec, round_half_up, rhu_int
from store import (
    DB,
    LIVE_PRODUCTION,
    by_created,
    deviations_of_batch,
    em_samples_of_suite,
    ipcs_of_batch,
    live_batches_of_suite,
    quals_of_suite,
)

# --------------------------------------------------------------------------
# Constants named by the specification
# --------------------------------------------------------------------------

CLEANING_RESIDUE_LIMIT_UG = 100
MEDIA_FILL_MIN_UNITS = 5000
MEDIA_FILL_VALIDITY_DAYS = 183
SUITE_INITIAL_SETUP_MINUTES = 60
OPERATOR_ROSTER_THRESHOLD = 2

FILL_WEIGHT_FAIL_PCT = dec("0.0500")
FILL_WEIGHT_ALERT_PCT = dec("0.0300")
VISUAL_AQL = dec("0.0250")

EM_LIMITS = {
    "A": {
        "VIABLE_AIR": (1, 1),
        "SURFACE": (1, 1),
        "PERSONNEL_GLOVE": (1, 1),
    },
    "B": {
        "VIABLE_AIR": (5, 10),
        "SURFACE": (3, 5),
        "PERSONNEL_GLOVE": (1, 5),
    },
    "C": {
        "VIABLE_AIR": (50, 100),
        "SURFACE": (15, 25),
        "PERSONNEL_GLOVE": (5, 10),
    },
}

GRADE_WEIGHT = {"A": 3, "B": 2, "C": 1}
TYPE_SURCHARGE = {"PERSONNEL_GLOVE": 25, "SURFACE": 10, "VIABLE_AIR": 0}
BATCH_EXPOSURE_POINTS = 20
RISK_INDEX_CAP = 150

BILL_OF_COMPONENTS = {
    "VIAL": ("VIAL", "STOPPER"),
    "PRESYRINGE": ("SYRINGE", "PLUNGER"),
}
OVERAGE_PCT = {
    "VIAL": dec("0.03"),
    "STOPPER": dec("0.05"),
    "SYRINGE": dec("0.03"),
    "PLUNGER": dec("0.05"),
}
PACK_SIZE = {"VIAL": 480, "STOPPER": 1000, "SYRINGE": 500, "PLUNGER": 1000}

DEVIATION_BASE = {"MINOR": 5, "MAJOR": 20, "CRITICAL": 50}
DEVIATION_RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}
DEVIATION_RISK_CAP = 120

BASE_RELEASE_FEE_CENTS = 150000
PER_UNIT_FEE_CENTS = 40
DEVIATION_SURCHARGE_PCT = {
    "NONE": dec("0"),
    "MINOR": dec("0.05"),
    "MAJOR": dec("0.12"),
    "CRITICAL": dec("0.25"),
}
VOLUME_DISCOUNT_TIERS = (
    (2000000, dec("0.10")),
    (1000000, dec("0.06")),
    (500000, dec("0.03")),
)

TECH_STAGE_ORDER = ("NOT_STARTED", "GAP_ASSESSMENT", "ENGINEERING_RUN", "COMPLETE")
ANALYTICAL_ORDER = ("NOT_STARTED", "IN_TRANSFER", "VALIDATED")


# --------------------------------------------------------------------------
# Environmental monitoring
# --------------------------------------------------------------------------


def em_limits(grade, sample_type):
    return EM_LIMITS[grade][sample_type]


def em_classification(cfu_count, alert_limit, action_limit):
    """PRD 3.7: the action test runs first, both boundaries inclusive."""
    if cfu_count >= action_limit:
        return "ACTION"
    if cfu_count >= alert_limit:
        return "ALERT"
    return "WITHIN_LIMIT"


def em_risk_index(classification, cfu_count, action_limit, grade, sample_type,
                  batch_exposed):
    if classification == "WITHIN_LIMIT":
        return 0
    ratio = dec(cfu_count) / dec(action_limit)
    core = ratio * dec(20) * dec(GRADE_WEIGHT[grade])
    if core < 0:
        core = dec(0)
    if core > 100:
        core = dec(100)
    core = int(round_half_up(core, 0))  # rounded before the surcharges join
    total = core + TYPE_SURCHARGE[sample_type]
    if batch_exposed:
        total += BATCH_EXPOSURE_POINTS
    return min(RISK_INDEX_CAP, total)


# --------------------------------------------------------------------------
# Suite derived counts and posture (PRD 2.5)
# --------------------------------------------------------------------------


def open_action_excursion_count(suite_id):
    total = 0
    for sample in em_samples_of_suite(suite_id):
        if sample["classification"] == "ACTION" and sample["investigation_status"] in (
            "OPEN",
            "INVESTIGATING",
        ):
            total += 1
    return total


def qualified_operator_count(suite_id):
    now = clock_now()
    total = 0
    for qual in quals_of_suite(suite_id):
        if qual["status"] == "QUALIFIED" and qual["expires_on"] is not None \
                and qual["expires_on"] >= now:
            total += 1
    return total


def suite_posture(suite):
    if suite["aseptic_qualification_status"] == "INVALIDATED" \
            or suite["cleaning_validation_status"] == "FAILED":
        return "FROZEN"
    valid_until = suite["media_fill_valid_until"]
    if open_action_excursion_count(suite["id"]) >= 1 \
            or valid_until is None \
            or valid_until < clock_now() \
            or qualified_operator_count(suite["id"]) < OPERATOR_ROSTER_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


def suite_committed_minutes(suite_id):
    """PRD 3.5: window minutes plus the frozen changeover, over live batches."""
    batches = live_batches_of_suite(suite_id)
    batches = sorted(batches, key=lambda b: (b["planned_start"], b["created_at"], b["_seq"]))
    total = 0
    for batch in batches:
        total += window_minutes(batch) + batch["changeover_minutes_applied"]
    return total


def window_minutes(batch):
    delta = batch["planned_end"] - batch["planned_start"]
    return int(delta.total_seconds() // 60)


# --------------------------------------------------------------------------
# Project ledgers (PRD 2.6)
# --------------------------------------------------------------------------


def committed_demand_units(project_id):
    total = 0
    for batch in DB.batches.values():
        if batch["client_project_id"] == project_id \
                and batch["production_status"] in LIVE_PRODUCTION:
            total += batch["component_demand_units"]
    return total


def open_deviation_risk_total(project_id):
    batch_ids = set(
        b["id"] for b in DB.batches.values() if b["client_project_id"] == project_id
    )
    total = 0
    for dev in DB.deviations.values():
        if dev["batch_order_id"] in batch_ids and dev["status"] != "CLOSED":
            total += dev["risk_score"]
    return total


def last_client_audit_finding_count(project_id):
    hosted = [
        e
        for e in DB.engagements.values()
        if e["client_project_id"] == project_id and e["status"] == "HOSTED"
        and e["hosted_at"] is not None
    ]
    if not hosted:
        return 0
    hosted.sort(key=lambda e: (e["hosted_at"], e["created_at"], e["_seq"]), reverse=True)
    return hosted[0]["finding_count"]


def lot_quantity_available_from_reservations(lot):
    """The ledger identity of PRD 2.6, used as a cross-check."""
    held = 0
    for res in DB.reservations.values():
        if res["component_lot_id"] == lot["id"] and res["status"] in ("RESERVED", "CONSUMED"):
            held += res["quantity_reserved"]
    return lot["quantity_received"] - held


# --------------------------------------------------------------------------
# Scheduling (PRD 3.5)
# --------------------------------------------------------------------------


def changeover_minutes_applied(suite, molecule_name, planned_start):
    candidates = [
        b for b in live_batches_of_suite(suite["id"]) if b["planned_end"] <= planned_start
    ]
    if not candidates:
        return SUITE_INITIAL_SETUP_MINUTES
    candidates.sort(key=lambda b: (b["planned_end"], b["created_at"], b["_seq"]))
    previous = candidates[-1]
    prev_project = DB.projects.get(previous["client_project_id"])
    prev_molecule = prev_project["molecule_name"] if prev_project else None
    if prev_molecule == molecule_name:
        return suite["changeover_minutes_same_product"]
    return suite["changeover_minutes_product_change"]


def component_demand_units(dosage_form, target_fill_units):
    """Ceiling per component line first, then sum the lines (PRD 3.5)."""
    total = 0
    for line in BILL_OF_COMPONENTS[dosage_form]:
        gross = dec(target_fill_units) * (dec(1) + OVERAGE_PCT[line])
        pack = PACK_SIZE[line]
        packs = ceil_dec(gross / dec(pack))
        total += packs * pack
    return total


def applicable_buffer(suite, molecule_a, molecule_b):
    if molecule_a == molecule_b:
        return suite["changeover_minutes_same_product"]
    return suite["changeover_minutes_product_change"]


# --------------------------------------------------------------------------
# In-process controls (PRD 3.6)
# --------------------------------------------------------------------------


def in_process_check_result(check_type, sample_size, reject_unit_count,
                            measured_fill_weights_mg, target_fill_weight_mg):
    if check_type == "FILL_WEIGHT":
        target = dec(target_fill_weight_mg)
        worst = dec(0)
        for weight in measured_fill_weights_mg:
            deviation = abs(dec(weight) - target) / target
            if deviation > worst:
                worst = deviation
        pct = round_half_up(worst, 4)  # rounded before either comparison
        if pct > FILL_WEIGHT_FAIL_PCT:
            result = "FAIL"
        elif pct >= FILL_WEIGHT_ALERT_PCT:
            result = "ALERT"
        else:
            result = "PASS"
        return result, pct
    if check_type == "CCI":
        return ("FAIL" if reject_unit_count >= 1 else "PASS"), dec(0)
    rate = dec(reject_unit_count) / dec(sample_size)  # exact, never pre-rounded
    return ("FAIL" if rate >= VISUAL_AQL else "PASS"), dec(0)


# --------------------------------------------------------------------------
# Releasable units (PRD 3.8)
# --------------------------------------------------------------------------


def destructive_total_units(batch_id):
    total = 0
    for check in ipcs_of_batch(batch_id):
        total += check["destructive_sample_units"]
    return total


def actual_visual_reject_units(batch_id):
    total = 0
    for check in ipcs_of_batch(batch_id):
        if check["check_type"] == "VISUAL_INSPECTION":
            total += check["reject_unit_count"]
    return total


def expected_reject_units(filled_unit_count, historical_reject_rate_ppm):
    """Ceiling, never round-half-up."""
    return ceil_dec(
        dec(filled_unit_count) * dec(historical_reject_rate_ppm) / dec(1000000)
    )


def provisional_releasable_units(batch, project):
    filled = batch["filled_unit_count"] or 0
    expected = expected_reject_units(filled, project["historical_reject_rate_ppm"])
    return filled - expected - destructive_total_units(batch["id"])


def final_releasable_units(batch):
    filled = batch["filled_unit_count"] or 0
    return (
        filled
        - actual_visual_reject_units(batch["id"])
        - destructive_total_units(batch["id"])
        - (batch["quarantined_unit_count"] or 0)
    )


def max_open_deviation_class(batch_id):
    worst = "NONE"
    for dev in deviations_of_batch(batch_id):
        if dev["status"] == "CLOSED" or dev["classification"] is None:
            continue
        if worst == "NONE" or DEVIATION_RANK[dev["classification"]] > DEVIATION_RANK[worst]:
            worst = dev["classification"]
    return worst


def qp_release_fee_cents(final_units, open_class):
    """The five pinned steps of PRD 3.8; the tier is selected exactly once."""
    subtotal = BASE_RELEASE_FEE_CENTS + PER_UNIT_FEE_CENTS * int(final_units)
    surcharge = int(round_half_up(dec(subtotal) * DEVIATION_SURCHARGE_PCT[open_class], 0))
    pre_discount = subtotal + surcharge
    tier = dec(0)
    for threshold, pct in VOLUME_DISCOUNT_TIERS:
        if pre_discount >= threshold:
            tier = pct
            break
    discount = int(round_half_up(dec(pre_discount) * tier, 0))
    return pre_discount - discount


# --------------------------------------------------------------------------
# Deviation risk (PRD 3.7)
# --------------------------------------------------------------------------


def deviation_risk_score(classification, capa_rejection_count, em_sample_id):
    base = DEVIATION_BASE[classification]
    multiplier = dec(1) + dec("0.5") * dec(capa_rejection_count)
    score = int(round_half_up(dec(base) * multiplier, 0))  # rounded before the bonus
    if em_sample_id is not None:
        sample = DB.em_samples.get(em_sample_id)
        if sample is not None and sample["classification"] == "ACTION":
            score += 15
    return min(DEVIATION_RISK_CAP, score)  # cap applied last


# --------------------------------------------------------------------------
# Project readiness (PRD 3.9)
# --------------------------------------------------------------------------

INTAKE_TECH_POINTS = {
    "NOT_STARTED": 0,
    "GAP_ASSESSMENT": 15,
    "ENGINEERING_RUN": 30,
    "COMPLETE": 30,
}
INTAKE_ANALYTICAL_POINTS = {"NOT_STARTED": 0, "IN_TRANSFER": 25, "VALIDATED": 25}
AUDIT_TECH_POINTS = {
    "NOT_STARTED": 0,
    "GAP_ASSESSMENT": 0,
    "ENGINEERING_RUN": 15,
    "COMPLETE": 30,
}
AUDIT_ANALYTICAL_POINTS = {"NOT_STARTED": 0, "IN_TRANSFER": 12, "VALIDATED": 25}


def operator_points(counted):
    if counted >= OPERATOR_ROSTER_THRESHOLD:
        return 20
    return int(round_half_up(dec(20) * dec(counted) / dec(2), 0))


def project_readiness_score(project, suite, variant):
    now = clock_now()
    if variant == "INTAKE_FORECAST":
        tech = INTAKE_TECH_POINTS[project["tech_transfer_stage"]]
        analytical = INTAKE_ANALYTICAL_POINTS[project["analytical_method_transfer_status"]]
        aseptic = 25 if suite["aseptic_qualification_status"] == "QUALIFIED" else 0
        counted = len(
            [q for q in quals_of_suite(suite["id"])
             if q["status"] in ("PENDING", "QUALIFIED", "LAPSED")]
        )
    else:
        tech = AUDIT_TECH_POINTS[project["tech_transfer_stage"]]
        analytical = AUDIT_ANALYTICAL_POINTS[project["analytical_method_transfer_status"]]
        if suite["aseptic_qualification_status"] != "QUALIFIED":
            aseptic = 0
        elif suite["media_fill_valid_until"] is None \
                or suite["media_fill_valid_until"] < now:
            aseptic = 10
        else:
            aseptic = 25
        counted = len(
            [q for q in quals_of_suite(suite["id"])
             if q["status"] == "QUALIFIED" and q["expires_on"] is not None
             and q["expires_on"] >= now]
        )
    ops = operator_points(counted)
    return {
        "tech_points": tech,
        "analytical_points": analytical,
        "aseptic_points": aseptic,
        "operator_points": ops,
        "counted_operator_count": counted,
        "readiness_score": tech + analytical + aseptic + ops,
    }
