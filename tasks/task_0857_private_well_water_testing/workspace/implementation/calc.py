"""Calculations and derived-field reconciliation (PRD §3.2, §3.4, §3.5, §2.7)."""
from decimal import Decimal

from store import (
    store,
    DEPTH_TIER1_MAX_FT, DEPTH_TIER2_MAX_FT,
    DEPTH_TIER1_CENTS, DEPTH_TIER2_CENTS, DEPTH_TIER3_CENTS,
    USE_MULT, AQ_SURCHARGE, EXPEDITE_FEE_CENTS,
    ANALYTE_BASE_CENTS, PANEL_REGION_FACTOR,
    NITRATE_MCL_MG_L, NITRATE_ADVISORY_MG_L, LEAD_ACTION_PPB,
)
from helpers import round_half_up
from models import touch


# ---------------------------------------------------------------------------
# permit_fee — tiered pricing, dual variant ESTIMATE / FINAL (PRD §3.2/§3.3)
# ---------------------------------------------------------------------------
def _depth_base(depth):
    if depth <= DEPTH_TIER1_MAX_FT:
        return DEPTH_TIER1_CENTS
    if depth <= DEPTH_TIER2_MAX_FT:
        return DEPTH_TIER2_CENTS
    return DEPTH_TIER3_CENTS


def permit_fee(depth, intended_use, sensitivity, expedite):
    base = _depth_base(depth)
    mult = Decimal(USE_MULT[intended_use])
    # round the depth_base * use_mult product to whole cents BEFORE adding extras
    product = int(round_half_up(Decimal(base) * mult, 0))
    fee = product + AQ_SURCHARGE[sensitivity]
    if expedite:
        fee += EXPEDITE_FEE_CENTS
    return fee


# ---------------------------------------------------------------------------
# panel_fee — round per-analyte line, then sum (PRD §3.4)
# ---------------------------------------------------------------------------
def panel_fee(analytes):
    factor = Decimal(PANEL_REGION_FACTOR)
    total = 0
    for a in analytes:
        line = int(round_half_up(Decimal(ANALYTE_BASE_CENTS[a]) * factor, 0))
        total += line
    return total


# ---------------------------------------------------------------------------
# Advisory grading (PRD §3.5)
# ---------------------------------------------------------------------------
def grade_level(nitrate, bacteria, ecoli, lead):
    if bacteria == "PRESENT" or ecoli == "PRESENT" \
            or lead >= LEAD_ACTION_PPB or nitrate >= NITRATE_MCL_MG_L:
        return "UNSAFE"
    if nitrate >= NITRATE_ADVISORY_MG_L:
        return "ADVISORY"
    return "SAFE"


def _resulted_results_for_well(well_id, exclude_result_id=None):
    """SampleResults whose parent WaterSample is RESULTED, on this well."""
    out = []
    for res in store.sample_results.values():
        if exclude_result_id is not None and res["id"] == exclude_result_id:
            continue
        sample = store.water_samples.get(res["water_sample_id"])
        if sample is None or sample["well_id"] != well_id:
            continue
        if sample["status"] != "RESULTED":
            continue
        out.append((res, sample))
    return out


def _latest_prior(well_id, this_result_id):
    """Most recent OTHER resulted result: sample.collected_on DESC, created_at DESC."""
    candidates = _resulted_results_for_well(well_id, exclude_result_id=this_result_id)
    if not candidates:
        return None
    candidates.sort(
        key=lambda rs: (rs[1]["collected_on"], rs[0]["created_at"], rs[0]["_seq"]),
        reverse=True,
    )
    return candidates[0][0]


def compute_result_grades(this_result, well_id):
    """Fill advisory_level_provisional/confirmed/exceedances on this_result."""
    nitrate = this_result["nitrate_mg_l"]
    bacteria = this_result["bacteria_coliform"]
    ecoli = this_result["ecoli"]
    lead = this_result["lead_ppb"]

    provisional = grade_level(nitrate, bacteria, ecoli, lead)

    prior = _latest_prior(well_id, this_result["id"])
    if prior is not None:
        nitrate_conf = float(round_half_up((nitrate + prior["nitrate_mg_l"]) / 2, 3))
    else:
        nitrate_conf = nitrate
    confirmed = grade_level(nitrate_conf, bacteria, ecoli, lead)

    exceedances = []
    if bacteria == "PRESENT" or ecoli == "PRESENT":
        exceedances.append("BACTERIA")
    if nitrate_conf >= NITRATE_MCL_MG_L:
        exceedances.append("NITRATE")
    if lead >= LEAD_ACTION_PPB:
        exceedances.append("LEAD")

    this_result["advisory_level_provisional"] = provisional
    this_result["advisory_level_confirmed"] = confirmed
    this_result["exceedances"] = exceedances
    this_result["_nitrate_conf"] = nitrate_conf
    return confirmed


CONFIRMED_TO_POTABILITY = {"SAFE": "POTABLE", "ADVISORY": "ADVISORY", "UNSAFE": "UNSAFE"}
OPEN_CASE_STATES = {"OPEN", "INVESTIGATING", "MITIGATION", "RESOLVED"}


def _latest_resulted_confirmed(well_id):
    """Confirmed level of the latest remaining RESULTED sample on the well."""
    candidates = _resulted_results_for_well(well_id)
    if not candidates:
        return None
    candidates.sort(
        key=lambda rs: (rs[1]["collected_on"], rs[0]["created_at"], rs[0]["_seq"]),
        reverse=True,
    )
    return candidates[0][0]["advisory_level_confirmed"]


def recompute_potability(well):
    """Recompute from latest RESULTED sample; any non-closed case forces UNSAFE."""
    well_id = well["id"]
    for case in store.contamination_cases.values():
        if case["well_id"] == well_id and case["status"] in OPEN_CASE_STATES:
            _set_potability(well, "UNSAFE")
            return
    confirmed = _latest_resulted_confirmed(well_id)
    if confirmed is None:
        _set_potability(well, "UNKNOWN")
    else:
        _set_potability(well, CONFIRMED_TO_POTABILITY[confirmed])


def _set_potability(well, value):
    if well["potability_status"] != value:
        well["potability_status"] = value
        touch(well)


def set_potability_direct(well, value):
    _set_potability(well, value)


# ---------------------------------------------------------------------------
# Derived reconciliation: net_fees_paid_cents, active_advisory_count (PRD §2.7)
# ---------------------------------------------------------------------------
def recompute_net_fees(applicant):
    total = 0
    for p in store.construction_permits.values():
        if p["applicant_id"] != applicant["id"]:
            continue
        if p["fee_paid"]:
            total += p["fee_charged_cents"]
        total -= p["fee_refunded_cents"]
    if applicant["net_fees_paid_cents"] != total:
        applicant["net_fees_paid_cents"] = total
        touch(applicant)


def recompute_advisory_count(well):
    count = sum(
        1 for a in store.advisories.values()
        if a["well_id"] == well["id"] and a["status"] == "ACTIVE"
    )
    if well["active_advisory_count"] != count:
        well["active_advisory_count"] = count
        touch(well)
