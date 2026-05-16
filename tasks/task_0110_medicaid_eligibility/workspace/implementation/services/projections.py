"""Read-side projections — convert raw store rows to API response dicts.

Computed fields are derived on read (PRD §2.4). The system also bumps
updated_at/version on the host resource when any computed value changes
that depends on a child write (PRD §2.8); that bump is done at write time
in the routes / domain layer — projections here are pure read-helpers.
"""

from datetime import datetime, timezone

from core.store import STORE
from core.clock import CLOCK
from core.timeutils import iso_format
from services.calculations import (
    compute_applicant_magi,
    applicant_countable_assets,
    effective_household_size,
    household_size_basic,
    fpl_threshold_amount,
    compute_total_magi,
    compute_fpl_percent,
    asset_exempt_under_federal,
    asset_exempt_under_state,
    FEDERAL_EXEMPT_ASSET_TYPES,
)
from services.money import round2_float


# ----- helpers -----------------------------------------------------------------

def list_applicants_of_household(household_id: str):
    return [a for a in STORE.applicants.values() if a["household_id"] == household_id]


def list_income_of_applicant(applicant_id: str):
    return [i for i in STORE.income_records.values() if i["applicant_id"] == applicant_id]


def list_assets_of_applicant(applicant_id: str):
    return [a for a in STORE.asset_records.values() if a["applicant_id"] == applicant_id]


def list_enrollments_of_household(household_id: str):
    applicant_ids = {a["id"] for a in list_applicants_of_household(household_id)}
    return [e for e in STORE.enrollments.values() if e["applicant_id"] in applicant_ids]


def find_policy_by_state(state_code: str):
    pid = STORE.state_policies_by_code.get(state_code)
    if pid is None:
        return None
    return STORE.state_policies.get(pid)


# ----- EmergencyDeclaration ----------------------------------------------------

def emergency_status(decl: dict) -> str:
    """ACTIVE iff declared_at <= clock_now < expires_at; EXPIRED otherwise."""
    now = CLOCK.now()
    declared = decl["_declared_at_dt"]
    expires = decl["_expires_at_dt"]
    if declared <= now < expires:
        return "ACTIVE"
    return "EXPIRED"


def project_emergency_declaration(decl: dict) -> dict:
    return {
        "id": decl["id"],
        "scope": decl["scope"],
        "state_code": decl.get("state_code"),
        "declared_at": iso_format(decl["_declared_at_dt"]),
        "expires_at": iso_format(decl["_expires_at_dt"]),
        "status": emergency_status(decl),
        "created_at": decl["created_at"],
    }


def state_emergency_continuous_active(state_code: str) -> bool:
    """True iff some EmergencyDeclaration with status ACTIVE covers state_code."""
    for d in STORE.emergency_declarations.values():
        if emergency_status(d) != "ACTIVE":
            continue
        if d["scope"] == "FEDERAL":
            return True
        if d["scope"] == "STATE" and d.get("state_code") == state_code:
            return True
    return False


# ----- StatePolicy -------------------------------------------------------------

def project_state_policy(policy: dict) -> dict:
    return {
        "id": policy["id"],
        "state_code": policy["state_code"],
        "fpl_year": policy["fpl_year"],
        "fpl_base_amount": round2_float(policy["fpl_base_amount"]),
        "fpl_per_member_amount": round2_float(policy["fpl_per_member_amount"]),
        "magi_income_limit_pct": round2_float(policy["magi_income_limit_pct"]),
        "asset_limit_per_member": round2_float(policy.get("asset_limit_per_member", 0) or 0),
        "asset_test_applies": bool(policy.get("asset_test_applies", False)),
        "state_disregard_amount": round2_float(policy.get("state_disregard_amount", 0) or 0),
        "state_exempt_asset_types": list(policy.get("state_exempt_asset_types") or []),
        "emergency_continuous_active": state_emergency_continuous_active(policy["state_code"]),
        "created_at": policy["created_at"],
        "updated_at": policy["updated_at"],
        "version": policy["version"],
    }


# ----- Applicant ---------------------------------------------------------------

def project_applicant(applicant: dict) -> dict:
    return {
        "id": applicant["id"],
        "household_id": applicant["household_id"],
        "full_name": applicant["full_name"],
        "date_of_birth": applicant["date_of_birth"],
        "dependent_status": applicant["dependent_status"],
        "is_disabled": bool(applicant.get("is_disabled", False)),
        "is_pregnant": bool(applicant.get("is_pregnant", False)),
        "magi_income": _applicant_magi_income(applicant),
        "countable_assets": _applicant_countable_assets_for_household_default(applicant),
        "redetermination_count_this_year": _applicant_redet_count_this_year(applicant),
        "created_at": applicant["created_at"],
        "updated_at": applicant["updated_at"],
        "version": applicant["version"],
    }


def _applicant_magi_income(applicant: dict) -> float:
    incs = list_income_of_applicant(applicant["id"])
    val = compute_applicant_magi(applicant, incs)
    return float(val)


def _applicant_countable_assets_for_household_default(applicant: dict) -> float:
    """Used for free-standing applicant reads — uses the household's policy
    state_exempt_asset_types under the STATE variant by default. This is an
    informational field; the authoritative snapshot is captured on application
    submit using the application's rule_variant.
    """
    household = STORE.households.get(applicant["household_id"])
    if household is None:
        return 0.0
    policy = find_policy_by_state(household["state_code"])
    state_exempt = (policy.get("state_exempt_asset_types") if policy else None) or []
    assets = list_assets_of_applicant(applicant["id"])
    val = applicant_countable_assets(assets, "STATE", state_exempt)
    return float(val)


def _applicant_redet_count_this_year(applicant: dict) -> int:
    household = STORE.households.get(applicant["household_id"])
    if household is None:
        return 0
    policy = find_policy_by_state(household["state_code"])
    if policy is None:
        return 0
    year = policy["fpl_year"]
    # Find enrollments for this applicant
    enrollment_ids = [e["id"] for e in STORE.enrollments.values()
                      if e["applicant_id"] == applicant["id"]]
    count = 0
    for r in STORE.redeterminations.values():
        if r["enrollment_id"] not in enrollment_ids:
            continue
        if r["status"] == "WITHDRAWN":
            continue
        due_dt = r.get("_due_date_dt")
        if due_dt is None:
            continue
        if due_dt.astimezone(timezone.utc).year == year:
            count += 1
    return count


# ----- IncomeRecord / AssetRecord --------------------------------------------

def project_income_record(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "applicant_id": rec["applicant_id"],
        "source_type": rec["source_type"],
        "gross_amount": round2_float(rec["gross_amount"]),
        "frequency": rec["frequency"],
        "created_at": rec["created_at"],
    }


def project_asset_record(rec: dict, rule_variant_for_view: str = "STATE") -> dict:
    """Project an AssetRecord.

    `rule_variant_for_view` controls the countable_value semantics. By default
    we use the household's STATE variant (the informational view). When called
    from inside a snapshot computation, callers compute countable_value themselves.
    """
    household = None
    applicant = STORE.applicants.get(rec["applicant_id"])
    if applicant is not None:
        household = STORE.households.get(applicant["household_id"])
    policy = find_policy_by_state(household["state_code"]) if household else None
    state_exempt = (policy.get("state_exempt_asset_types") if policy else None) or []
    fed = asset_exempt_under_federal(rec["asset_type"])
    st = asset_exempt_under_state(rec["asset_type"], state_exempt)
    if rule_variant_for_view == "FEDERAL":
        countable = 0 if fed else float(rec["market_value"])
    else:
        countable = 0 if (fed or st) else float(rec["market_value"])
    return {
        "id": rec["id"],
        "applicant_id": rec["applicant_id"],
        "asset_type": rec["asset_type"],
        "market_value": round2_float(rec["market_value"]),
        "exempt_under_federal": fed,
        "exempt_under_state": st,
        "countable_value": round2_float(countable),
        "created_at": rec["created_at"],
    }


# ----- Household ---------------------------------------------------------------

def household_computed_fields(household: dict, rule_variant: str = "STATE") -> dict:
    """Compute household_size, total_magi, fpl_threshold_amount, fpl_percent,
    active_enrollment_count under the default STATE view."""
    applicants = list_applicants_of_household(household["id"])
    size = household_size_basic(applicants)
    eff_size = effective_household_size(applicants)
    policy = find_policy_by_state(household["state_code"])
    if policy is None:
        return {
            "household_size": size,
            "total_magi": 0.0,
            "fpl_threshold_amount": 0.0,
            "fpl_percent": None,
            "active_enrollment_count": _household_active_enrollment_count(household["id"]),
        }
    # Sum applicant magi (non-EXCLUDED)
    raw_sum = sum(
        compute_applicant_magi(a, list_income_of_applicant(a["id"]))
        for a in applicants if a["dependent_status"] != "EXCLUDED"
    )
    total_magi = compute_total_magi(raw_sum, rule_variant, policy)
    threshold = fpl_threshold_amount(eff_size, policy)
    fpl_pct = compute_fpl_percent(total_magi, threshold) if threshold > 0 else None
    return {
        "household_size": size,
        "total_magi": round2_float(total_magi),
        "fpl_threshold_amount": round2_float(threshold),
        "fpl_percent": (round2_float(fpl_pct) if fpl_pct is not None else None),
        "active_enrollment_count": _household_active_enrollment_count(household["id"]),
    }


def _household_active_enrollment_count(household_id: str) -> int:
    applicants = list_applicants_of_household(household_id)
    applicant_ids = {a["id"] for a in applicants}
    return sum(
        1 for e in STORE.enrollments.values()
        if e["applicant_id"] in applicant_ids
        and e["coverage_status"] in ("ACTIVE", "CONTINUOUS_COVERAGE")
    )


def project_household(household: dict) -> dict:
    computed = household_computed_fields(household, rule_variant="STATE")
    return {
        "id": household["id"],
        "state_code": household["state_code"],
        "head_applicant_id": household.get("head_applicant_id"),
        "address_line": household["address_line"],
        "filing_status": household["filing_status"],
        "household_size": computed["household_size"],
        "total_magi": computed["total_magi"],
        "fpl_threshold_amount": computed["fpl_threshold_amount"],
        "fpl_percent": computed["fpl_percent"],
        "active_enrollment_count": computed["active_enrollment_count"],
        "created_at": household["created_at"],
        "updated_at": household["updated_at"],
        "version": household["version"],
    }


# ----- Application & EligibilityDetermination ---------------------------------

def project_application(app: dict) -> dict:
    return {
        "id": app["id"],
        "household_id": app["household_id"],
        "program": app["program"],
        "rule_variant": app["rule_variant"],
        "submitted_at": app.get("submitted_at"),
        "status": app["status"],
        "snapshot_magi": app.get("snapshot_magi"),
        "snapshot_fpl_percent": app.get("snapshot_fpl_percent"),
        "snapshot_countable_assets": app.get("snapshot_countable_assets"),
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "version": app["version"],
    }


def project_determination(d: dict) -> dict:
    return {
        "id": d["id"],
        "application_id": d["application_id"],
        "decided_at": d["decided_at"],
        "outcome": d["outcome"],
        "ineligibility_reason": d.get("ineligibility_reason"),
        "computed_magi": d.get("computed_magi"),
        "computed_fpl_percent": d.get("computed_fpl_percent"),
        "applied_rule_variant": d["applied_rule_variant"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


# ----- Enrollment --------------------------------------------------------------

def project_enrollment(e: dict) -> dict:
    return {
        "id": e["id"],
        "applicant_id": e["applicant_id"],
        "determination_id": e["determination_id"],
        "coverage_start": e["coverage_start"],
        "coverage_end": e["coverage_end"],
        "coverage_status": e["coverage_status"],
        "continuous_coverage_flag": (e["coverage_status"] == "CONTINUOUS_COVERAGE"),
        "redetermination_due_at": e["redetermination_due_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


# ----- Redetermination ---------------------------------------------------------

def project_redetermination(r: dict, include_premium: bool = True) -> dict:
    out = {
        "id": r["id"],
        "enrollment_id": r["enrollment_id"],
        "due_date": r["due_date"],
        "status": r["status"],
        "new_snapshot_magi": r.get("new_snapshot_magi"),
        "new_snapshot_fpl_percent": r.get("new_snapshot_fpl_percent"),
        "decision": r.get("decision"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
    if include_premium and r["status"] == "PENDING":
        from services.premium import premium_estimate_for_pending
        out["premium_estimate"] = premium_estimate_for_pending(r)
    return out


# ----- Appeal & FairHearing ---------------------------------------------------

def project_appeal(a: dict) -> dict:
    return {
        "id": a["id"],
        "determination_id": a["determination_id"],
        "filed_at": a["filed_at"],
        "deadline_at": a["deadline_at"],
        "status": a["status"],
        "officer_id": a.get("officer_id"),
        "outcome_reason": a.get("outcome_reason"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def project_fair_hearing(h: dict) -> dict:
    return {
        "id": h["id"],
        "appeal_id": h["appeal_id"],
        "officer_id": h["officer_id"],
        "scheduled_start": h["scheduled_start"],
        "scheduled_end": h["scheduled_end"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }
