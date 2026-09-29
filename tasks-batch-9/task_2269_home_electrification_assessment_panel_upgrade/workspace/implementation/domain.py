"""Shared lookups, allocation plumbing and the cascade families (PRD 2.11)."""
import clock
import calc
import errors
import store
from errors import ApiError

QUALITY_RESULTS = ("PASSED", "CONDITIONAL_PASS", "FAILED")
LIVE_INSTALL_STATES = ("INSTALLED", "INSPECTION_FAILED", "REMEDIATION", "VERIFIED", "PAID")
BLOCKING_ASSESSMENT_PROJECT_STATES = (
    "RESERVED", "CONTRACTOR_HOLD", "INSTALLED", "INSPECTION_FAILED",
    "REMEDIATION", "VERIFIED", "PAID",
)


# ------------------------------------------------------------ path lookups ---
def _require(record, error_id):
    if record is None:
        raise ApiError(error_id)
    return record


def get_program(program_id):
    return _require(store.programs.get(program_id), errors.ERR_PROGRAM_NOT_FOUND)


def get_household(household_id):
    return _require(store.households.get(household_id), errors.ERR_HOUSEHOLD_NOT_FOUND)


def get_contractor(contractor_id):
    return _require(store.contractors.get(contractor_id), errors.ERR_CONTRACTOR_NOT_FOUND)


def get_inspector(inspector_id):
    return _require(store.inspectors.get(inspector_id), errors.ERR_INSPECTOR_NOT_FOUND)


def get_assessment(assessment_id):
    return _require(store.assessments.get(assessment_id), errors.ERR_ASSESSMENT_NOT_FOUND)


def get_income_verification(verification_id):
    return _require(
        store.income_verifications.get(verification_id),
        errors.ERR_INCOME_VERIFICATION_NOT_FOUND,
    )


def get_project(project_id):
    return _require(store.projects.get(project_id), errors.ERR_PROJECT_NOT_FOUND)


def get_reservation(reservation_id):
    return _require(store.reservations.get(reservation_id), errors.ERR_RESERVATION_NOT_FOUND)


def get_inspection(inspection_id):
    return _require(store.inspections.get(inspection_id), errors.ERR_INSPECTION_NOT_FOUND)


def get_clawback_action(action_id):
    return _require(
        store.clawback_actions.get(action_id), errors.ERR_CLAWBACK_ACTION_NOT_FOUND
    )


# ------------------------------------------------------------- navigation ----
def program_of_household(household):
    return store.programs.get(household["program_id"])


def program_of_project(project):
    household = store.households.get(project["household_id"])
    if household is None:
        return None
    return store.programs.get(household["program_id"])


def household_of_project(project):
    return store.households.get(project["household_id"])


def contractor_of_project(project):
    return store.contractors.get(project["contractor_id"])


def catalog_item(program_id, measure_code):
    for item in store.ordered(store.catalog_items):
        if item["program_id"] == program_id and item["measure_code"] == measure_code:
            return item
    return None


def project_measures(project_id):
    """The project's lines in the pinned proration order."""
    lines = [m for m in store.project_measures.values() if m["project_id"] == project_id]
    lines.sort(key=lambda m: (m["pinned_sort_order"], m["_seq"]))
    return lines


def eligible_measures(assessment_id):
    rows = [r for r in store.eligible_measures.values() if r["assessment_id"] == assessment_id]
    rows.sort(key=lambda r: r["evaluation_order"])
    return rows


def verified_income_verification(household_id):
    for row in store.ordered(store.income_verifications):
        if row["household_id"] == household_id and row["status"] == "VERIFIED":
            return row
    return None


def reservation_of_project(project_id, statuses=None):
    found = None
    for row in store.ordered(store.reservations):
        if row["project_id"] != project_id:
            continue
        if statuses is not None and row["status"] not in statuses:
            continue
        found = row
    return found


def active_declaration(project_id):
    for row in store.ordered(store.stacking_declarations):
        if row["project_id"] == project_id and row["status"] == "ACTIVE":
            return row
    return None


def project_has_scheduled_inspection(project_id, exclude_id=None):
    for row in store.inspections.values():
        if row["project_id"] != project_id or row["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        return True
    return False


# --------------------------------------------------------------- allocation --
def allocation_inputs(project, variant):
    lines = project_measures(project["id"])
    entries = []
    for line in lines:
        if line["install_status"] == "VOID" or line["verification_status"] == "REJECTED":
            continue
        entries.append({
            "ref": line,
            "measure_code": line["measure_code"],
            "group": line["pinned_combined_cap_group"],
            "is_panel": line["pinned_is_panel_upgrade"],
            "unit": line["pinned_unit_incentive_cents"],
            "maxq": line["pinned_max_quantity"],
            "mcap": line["pinned_measure_cap_cents"],
            "qty": line["verified_quantity"] if variant == "final" else line["planned_quantity"],
            "cost": line["actual_cost_cents"] if variant == "final" else line["estimated_cost_cents"],
        })
    return entries


def run_allocation(project, variant):
    program = program_of_project(project)
    household = household_of_project(project)
    share = calc.tier_cost_share(program, household["income_tier"])
    ceiling = household["lifetime_cap_remaining_cents"]
    if variant == "final":
        reservation = reservation_of_project(project["id"], statuses=("RESERVED",))
        if reservation is not None:
            ceiling += reservation["reserved_amount_cents"]
    return calc.allocate(
        allocation_inputs(project, variant),
        program,
        share,
        ceiling,
        final=(variant == "final"),
        conditional=project["conditional_pass_flag"],
    )


def persist_allocation(project, variant, result, bump=True):
    field = "final_incentive_cents" if variant == "final" else "provisional_incentive_cents"
    for detail in result["lines"]:
        line = detail["ref"]
        if line is None:
            continue
        if line[field] != detail["allocated_cents"]:
            line[field] = detail["allocated_cents"]
            if bump:
                store.touch(line)
    total_field = (
        "final_total_incentive_cents" if variant == "final"
        else "provisional_total_incentive_cents"
    )
    project[total_field] = result["total_incentive_cents"]
    return result


def recompute_stacking(project):
    """Re-run benefit_stacking_limit for the project's ACTIVE declaration."""
    declaration = active_declaration(project["id"])
    if declaration is None:
        return None
    program = program_of_project(project)
    outcome = calc.benefit_stacking_limit(program, project, declaration["utility_rebate_cents"])
    declaration.update(outcome)
    store.touch(declaration)
    project["stacking_adjusted_state_incentive_cents"] = outcome["allowed_state_incentive_cents"]
    return outcome


# ---------------------------------------------------------------- cascades ---
def void_project_measures(project):
    for line in project_measures(project["id"]):
        if line["install_status"] != "VOID":
            line["install_status"] = "VOID"
            store.touch(line)


def cancel_scheduled_inspections(project, exclude_id=None):
    for inspection in store.ordered(store.inspections):
        if inspection["project_id"] != project["id"] or inspection["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and inspection["id"] == exclude_id:
            continue
        inspection["status"] = "CANCELLED"
        store.touch(inspection)


def suspend_contractor(contractor, reason):
    """Contractor ENROLLED_ACTIVE -> SUSPENDED plus the CONTRACTOR_HOLD cascade."""
    contractor["status"] = "SUSPENDED"
    contractor["suspension_reason"] = reason
    store.touch(contractor)
    for project in store.ordered(store.projects):
        if project["contractor_id"] == contractor["id"] and project["status"] == "RESERVED":
            project["status"] = "CONTRACTOR_HOLD"
            store.touch(project)


def reinstate_contractor(contractor):
    contractor["status"] = "ENROLLED_ACTIVE"
    contractor["suspension_reason"] = None
    store.touch(contractor)
    for project in store.ordered(store.projects):
        if project["contractor_id"] != contractor["id"]:
            continue
        if project["status"] != "CONTRACTOR_HOLD":
            continue
        reservation = reservation_of_project(project["id"])
        if reservation is not None and reservation["status"] == "RESERVED":
            project["status"] = "RESERVED"
            store.touch(project)


def recompute_quality(contractor):
    """Refresh quality_score_rolling / completed_inspection_count and auto-suspend."""
    if contractor is None:
        return
    candidates = calc.quality_candidates(contractor["id"])
    score, _window = calc.rolling_window_score(candidates)
    count = len(candidates)
    if contractor["quality_score_rolling"] != score or contractor["completed_inspection_count"] != count:
        contractor["quality_score_rolling"] = score
        contractor["completed_inspection_count"] = count
        store.touch(contractor)
    program = store.programs.get(contractor["program_id"])
    threshold = program["quality_suspension_threshold"] if program else 70
    if score < threshold and contractor["status"] == "ENROLLED_ACTIVE":
        suspend_contractor(contractor, "QUALITY_SCORE")


def expire_reservation(reservation):
    """Reservation RESERVED -> EXPIRED and the whole expiry cascade."""
    amount = reservation["reserved_amount_cents"]
    reservation["status"] = "EXPIRED"
    reservation["release_reason"] = "EXPIRY"
    store.touch(reservation)

    program = store.programs.get(reservation["program_id"])
    if program is not None:
        program["budget_reserved_cents"] -= amount
        program["budget_available_cents"] += amount
        store.touch(program)

    project = store.projects.get(reservation["project_id"])
    if project is None:
        return None
    household = household_of_project(project)
    if household is not None:
        household["encumbered_cents"] -= amount
        household["lifetime_cap_remaining_cents"] += amount
        store.touch(household)

    if project["status"] in ("RESERVED", "CONTRACTOR_HOLD"):
        project["status"] = "EXPIRED"
        store.touch(project)
        void_project_measures(project)
        cancel_scheduled_inspections(project)
    return project


def _record_clawback(project, reservation, inspection, reason, disbursed_before,
                     recovered, released, actor_id):
    program = program_of_project(project)
    household = household_of_project(project)
    action = store.new_record({
        "project_id": project["id"],
        "reservation_id": reservation["id"] if reservation is not None else None,
        "triggered_by_inspection_id": inspection["id"] if inspection is not None else None,
        "reason": reason,
        "disbursed_before_cents": disbursed_before,
        "recovered_cents": recovered,
        "released_reservation_cents": released,
        "program_budget_available_after_cents": (
            program["budget_available_cents"] if program else 0
        ),
        "household_cap_remaining_after_cents": (
            household["lifetime_cap_remaining_cents"] if household else 0
        ),
        "recorded_by_user_id": actor_id,
    }, versioned=False)
    store.clawback_actions[action["id"]] = action
    return action


def fail_final(project, inspection, actor_id):
    """Project INSTALLED -> FAILED_FINAL: release the reservation, write a clawback."""
    reservation = reservation_of_project(project["id"], statuses=("RESERVED",))
    amount = reservation["reserved_amount_cents"] if reservation is not None else 0
    project["status"] = "FAILED_FINAL"

    if reservation is not None:
        reservation["status"] = "RELEASED"
        reservation["release_reason"] = "FAILED_REINSPECTION"
        store.touch(reservation)
        program = program_of_project(project)
        if program is not None:
            program["budget_reserved_cents"] -= amount
            program["budget_available_cents"] += amount
            store.touch(program)
        household = household_of_project(project)
        if household is not None:
            household["encumbered_cents"] -= amount
            household["lifetime_cap_remaining_cents"] += amount
            store.touch(household)
        _record_clawback(
            project, reservation, inspection, "FAILED_REINSPECTION",
            project["disbursed_amount_cents"], 0, amount, actor_id,
        )

    for line in project_measures(project["id"]):
        changed = False
        if line["install_status"] != "VOID":
            line["install_status"] = "VOID"
            changed = True
        if line["verification_status"] != "REJECTED":
            line["verification_status"] = "REJECTED"
            changed = True
        if changed:
            store.touch(line)

    cancel_scheduled_inspections(project, exclude_id=inspection["id"] if inspection else None)
    store.touch(project)


def post_payment_clawback(project, inspection, actor_id):
    """Project PAID -> CLAWED_BACK: recover the disbursed amount."""
    reservation = reservation_of_project(project["id"], statuses=("COMMITTED",))
    amount = reservation["reserved_amount_cents"] if reservation is not None else 0
    disbursed_before = project["disbursed_amount_cents"]

    if reservation is not None:
        reservation["status"] = "CLAWED_BACK"
        reservation["release_reason"] = "CLAWBACK"
        store.touch(reservation)
        program = program_of_project(project)
        if program is not None:
            program["budget_committed_cents"] -= amount
            program["budget_available_cents"] += amount
            program["budget_clawed_back_cents"] += disbursed_before
            store.touch(program)
        household = household_of_project(project)
        if household is not None:
            household["encumbered_cents"] -= amount
            household["lifetime_cap_remaining_cents"] += amount
            store.touch(household)

    project["status"] = "CLAWED_BACK"
    project["disbursed_amount_cents"] = 0

    for line in project_measures(project["id"]):
        if line["verification_status"] != "CLAWED_BACK":
            line["verification_status"] = "CLAWED_BACK"
            store.touch(line)

    if reservation is not None:
        _record_clawback(
            project, reservation, inspection, "POST_PAYMENT_INSPECTION_FAILURE",
            disbursed_before, disbursed_before, amount, actor_id,
        )

    cancel_scheduled_inspections(project, exclude_id=inspection["id"] if inspection else None)
    store.touch(project)


def inspection_failure_cascade(project, rejected_codes):
    """Reject the named lines, then anchor-dependent panel lines, then recompute."""
    lines = project_measures(project["id"])
    codes = set(rejected_codes or [])

    for line in lines:
        if line["measure_code"] in codes and line["verification_status"] == "PENDING":
            line["verification_status"] = "REJECTED"
            line["rejection_reason"] = "INSPECTION_DEFICIENCY"
            line["final_incentive_cents"] = 0
            store.touch(line)

    program = program_of_project(project)
    anchors = []
    for line in lines:
        item = catalog_item(program["id"], line["measure_code"]) if program else None
        if item is not None and item.get("qualifies_as_appliance_anchor"):
            anchors.append(line)
    if anchors and all(a["verification_status"] == "REJECTED" for a in anchors):
        for line in lines:
            if line["pinned_is_panel_upgrade"] and line["verification_status"] == "PENDING":
                line["verification_status"] = "REJECTED"
                line["rejection_reason"] = "ANCHOR_REJECTED"
                line["final_incentive_cents"] = 0
                store.touch(line)

    result = run_allocation(project, "final")
    persist_allocation(project, "final", result)
    recompute_stacking(project)


# ------------------------------------------------------- fitness / windows ---
def require_contractor_fitness(contractor):
    """Rung 11: enrollment status first, then credential currency."""
    if contractor is None:
        raise ApiError(errors.ERR_CONTRACTOR_NOT_FOUND)
    if contractor["status"] != "ENROLLED_ACTIVE":
        raise ApiError(errors.ERR_CONTRACTOR_NOT_ACTIVE)
    today = clock.today().isoformat()
    if contractor["license_expires_on"] < today or contractor["insurance_expires_on"] < today:
        raise ApiError(errors.ERR_CONTRACTOR_CREDENTIAL_EXPIRED)


def inspector_window_conflict(inspector_id, start, end):
    buffer_minutes = calc.TRAVEL_BUFFER_MINUTES
    from datetime import timedelta
    buffer_delta = timedelta(minutes=buffer_minutes)
    for inspection in store.inspections.values():
        if inspection["inspector_id"] != inspector_id:
            continue
        if inspection["status"] not in ("SCHEDULED", "PASSED", "CONDITIONAL_PASS", "FAILED"):
            continue
        other_start = clock.parse_datetime(inspection["scheduled_start"])
        other_end = clock.parse_datetime(inspection["scheduled_end"])
        if other_start is None or other_end is None:
            continue
        if start < other_end + buffer_delta and other_start < end + buffer_delta:
            return True
    return False


def install_window_overlaps(project, contractor_id, start_date, end_date):
    count = 0
    for other in store.projects.values():
        if other["id"] == project["id"] or other["contractor_id"] != contractor_id:
            continue
        if other["status"] not in LIVE_INSTALL_STATES:
            continue
        if not other["install_start_date"] or not other["install_end_date"]:
            continue
        if start_date <= other["install_end_date"] and other["install_start_date"] <= end_date:
            count += 1
    return count
