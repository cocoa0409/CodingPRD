"""Shared lookups, guards and cascades."""
from datetime import timedelta

import clock
import calc
import constants as C
import db
from errors import fail
from util import D, dt_of, format_dt

# ------------------------------------------------------------ path lookups --

_NOT_FOUND = {
    "projects": "ERR_PROJECT_NOT_FOUND",
    "influent_profiles": "ERR_INFLUENT_PROFILE_NOT_FOUND",
    "treatment_stages": "ERR_TREATMENT_STAGE_NOT_FOUND",
    "equipment_packages": "ERR_EQUIPMENT_PACKAGE_NOT_FOUND",
    "skids": "ERR_SKID_NOT_FOUND",
    "fat_runs": "ERR_FAT_RUN_NOT_FOUND",
    "or_equal_submittals": "ERR_SUBMITTAL_NOT_FOUND",
    "spec_deviations": "ERR_DEVIATION_NOT_FOUND",
    "performance_demos": "ERR_DEMO_NOT_FOUND",
    "service_agreements": "ERR_SERVICE_AGREEMENT_NOT_FOUND",
    "consumable_draws": "ERR_CONSUMABLE_DRAW_NOT_FOUND",
    "treatment_objectives": "ERR_TREATMENT_OBJECTIVE_NOT_FOUND",
    "process_technologies": "ERR_CATALOG_REF_NOT_FOUND",
    "material_specs": "ERR_CATALOG_REF_NOT_FOUND",
    "test_bays": "ERR_CATALOG_REF_NOT_FOUND",
}


def load(tablename, row_id):
    row = db.get(tablename, row_id)
    if row is None:
        fail(_NOT_FOUND[tablename], "%s %s does not exist" % (tablename, row_id))
    return row


def project(pid):
    return load("projects", pid)


def profile(pid):
    return load("influent_profiles", pid)


def stage(sid):
    return load("treatment_stages", sid)


def package(pid):
    return load("equipment_packages", pid)


def skid(sid):
    return load("skids", sid)


def fat_run(rid):
    return load("fat_runs", rid)


def submittal(sid):
    return load("or_equal_submittals", sid)


def deviation(did):
    return load("spec_deviations", did)


def demo(did):
    return load("performance_demos", did)


def agreement(aid):
    return load("service_agreements", aid)


def draw(did):
    return load("consumable_draws", did)


def objective(oid):
    return load("treatment_objectives", oid)


# -------------------------------------------------------------------- OCC ----

def check_version(row, expected, error_id):
    if expected is None:
        return
    if int(row.get("version", 1)) != int(expected):
        fail(error_id, "expected version %s but row is at version %s"
             % (expected, row.get("version")))


# ------------------------------------------------------------------- SOD -----

def forbid_same_user(actor_user_id, other_user_id, error_id):
    if other_user_id is not None and actor_user_id == other_user_id:
        fail(error_id, "segregation of duties violated")


# ---------------------------------------------------------- material screens --

def screen_material(material, design_pressure_psig, code_stamp_required,
                    technology, governing_profile):
    if governing_profile is not None:
        if D(material["max_chloride_ppm"]) < D(governing_profile["chloride_mg_l"]):
            fail("ERR_MATERIAL_NOT_RATED_FOR_SERVICE",
                 "material chloride rating below governing influent chloride")
        if D(material["max_temp_c"]) < D(governing_profile["temperature_c"]):
            fail("ERR_MATERIAL_NOT_RATED_FOR_SERVICE",
                 "material temperature rating below governing influent temperature")
        ph = D(governing_profile["ph"])
        if D(material["ph_min"]) > ph or D(material["ph_max"]) < ph:
            fail("ERR_MATERIAL_NOT_RATED_FOR_SERVICE",
                 "governing influent pH outside the material band")
    if technology is not None:
        if technology["chemical_service_class"] not in material["service_classes_allowed"]:
            fail("ERR_MATERIAL_NOT_RATED_FOR_SERVICE",
                 "material is not rated for the stage chemical service class")
    if D(design_pressure_psig) > D(material["max_pressure_psig"]):
        fail("ERR_MATERIAL_PRESSURE_EXCEEDED",
             "design pressure exceeds the material rating")
    stamp = code_stamp_required
    capable = {
        "ASME_U": material["asme_u_capable"],
        "NSF61": material["nsf61_certified"],
        "AWWA": material["awwa_compliant"],
    }
    if stamp in capable and not capable[stamp]:
        fail("ERR_MATERIAL_NOT_CODE_STAMPABLE",
             "material cannot carry the %s stamp" % stamp)


def governing_profile_of(project_row):
    pid = project_row.get("governing_influent_profile_id")
    return db.get("influent_profiles", pid) if pid else None


def technology_of_stage(stage_row):
    return db.get("process_technologies", stage_row.get("technology_id"))


# ------------------------------------------------------------- cost stamping --

def stamp_budgetary(package_row, stage_row):
    package_row["budgetary_cost_cents"] = calc.budgetary_cost_cents(
        stage_row, package_row)
    return package_row["budgetary_cost_cents"]


def stamp_firm(package_row, stage_row, material):
    firm = calc.firm_cost_cents(stage_row, package_row, material)
    package_row["firm_cost_cents"] = firm
    pct, flag = calc.cost_variance(firm, package_row["budgetary_cost_cents"])
    package_row["cost_variance_pct"] = pct
    package_row["variance_flag"] = flag
    return firm


# ------------------------------------------------------------------ posture --

def recompute_posture(project_row):
    project_row["delivery_posture"] = calc.delivery_posture(project_row)
    db.touch(project_row)
    return project_row["delivery_posture"]


# ------------------------------------------------------------- skid readiness --

def refresh_skid_readiness(skid_row, package_row):
    skid_row["fat_readiness"] = calc.fat_readiness(skid_row, package_row)
    return skid_row["fat_readiness"]


# ------------------------------------------------------- test bay ledger ------

def reserve_bay(bay, minutes):
    current = D(bay["reserved_footprint_minutes"])
    bay["reserved_footprint_minutes"] = calc.round_half_up(current + D(minutes), 2)
    db.touch(bay)


def release_bay(bay, minutes):
    current = D(bay["reserved_footprint_minutes"])
    updated = calc.round_half_up(current - D(minutes), 2)
    if updated < 0:
        updated = D("0.00")
    bay["reserved_footprint_minutes"] = updated
    db.touch(bay)


def release_run_reservation(run):
    bay = db.get("test_bays", run["test_bay_id"])
    if bay is None:
        return
    release_bay(bay, calc.footprint_minutes(run["footprint_sf"], run["duration_minutes"]))


# ---------------------------------------------------- agreement activation ----

def activate_agreement(agreement_row):
    """PENDING_ACTIVATION -> ACTIVE: stamp, derive expiry, seed the reserve."""
    activated_at = clock.now()
    agreement_row["status"] = "ACTIVE"
    agreement_row["activated_at"] = format_dt(activated_at)
    agreement_row["expires_at"] = format_dt(
        activated_at + timedelta(days=30 * int(agreement_row["term_months"])))
    agreement_row["reserve_available_cents"] = (
        int(agreement_row["reserve_funded_cents"])
        - int(agreement_row["reserve_committed_accrual_cents"]))
    db.touch(agreement_row)
    return agreement_row


# ------------------------------------------------- agreement expiry sweep -----

def sweep_agreement_expiry(agreement_row):
    """Lazy expiry: an ACTIVE/SUSPENDED agreement past expires_at flips EXPIRED."""
    expires_at = agreement_row.get("expires_at")
    if not expires_at:
        return False
    if agreement_row["status"] not in ("ACTIVE", "SUSPENDED"):
        return False
    if clock.now() >= dt_of(expires_at):
        agreement_row["status"] = "EXPIRED"
        db.touch(agreement_row)
        return True
    return False


def guard_agreement_usable(agreement_row):
    if sweep_agreement_expiry(agreement_row) or agreement_row["status"] == "EXPIRED":
        fail("ERR_AGREEMENT_EXPIRED", "service agreement has expired")
    if agreement_row["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_AGREEMENT_NOT_ACTIVE", "service agreement is not active")


# --------------------------------------------------------- compliance rescore --

def rescore_submittal(submittal_row):
    score, open_fundamental = calc.or_equal_compliance(submittal_row["id"])
    submittal_row["compliance_score"] = score
    submittal_row["open_fundamental_count"] = open_fundamental
    return submittal_row


def reprice_deviation(deviation_row):
    deviation_row["weighted_penalty_points"] = calc.deviation_penalty_points(
        deviation_row)
    return deviation_row


# ------------------------------------------------------------ misc helpers ----

def stage_of_package(package_row):
    return db.get("treatment_stages", package_row["treatment_stage_id"])


def project_of_stage(stage_row):
    return db.get("projects", stage_row["project_id"])


def project_of_package(package_row):
    return project_of_stage(stage_of_package(package_row))


def package_of_skid(skid_row):
    return db.get("equipment_packages", skid_row["equipment_package_id"])


def project_of_skid(skid_row):
    return project_of_package(package_of_skid(skid_row))


def skids_of_package(package_id):
    return [s for s in db.all_rows("skids")
            if s["equipment_package_id"] == package_id]


def iso(dt):
    return format_dt(dt)
