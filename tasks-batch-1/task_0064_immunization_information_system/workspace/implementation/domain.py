from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from store import STORE, now_iso

# -------------------------------------------------------------------
# Date helpers
# -------------------------------------------------------------------

def parse_date(s):
    """Parse an ISO YYYY-MM-DD date string. Returns date or None on failure."""
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def days_between(d1, d2):
    """Exact calendar-day difference d2 - d1 (integer days)."""
    return (d2 - d1).days


def date_plus(d, days):
    return d + timedelta(days=days)


# -------------------------------------------------------------------
# System field management
# -------------------------------------------------------------------

def touch(entity):
    """Mark an entity mutated: bump updated_at and version."""
    entity["updated_at"] = now_iso(STORE.clock)
    entity["version"] = entity["version"] + 1


def stamp_new(entity):
    ts = now_iso(STORE.clock)
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = STORE.next_seq()
    return entity


# -------------------------------------------------------------------
# Product / antigen helpers
# -------------------------------------------------------------------

def product_of_lot(lot):
    return STORE.products.get(lot["product_id"])


def antigen_of_immunization(imm):
    lot = STORE.lots.get(imm["lot_id"])
    if not lot:
        return None
    prod = product_of_lot(lot)
    return prod["antigen"] if prod else None


def mandated_antigens():
    """Distinct antigen values over all ACTIVE products."""
    seen = []
    for p in STORE.products.values():
        if p["status"] == "ACTIVE" and p["antigen"] not in seen:
            seen.append(p["antigen"])
    return seen


def active_product_for_antigen(antigen):
    """Return an ACTIVE product representing the antigen's series parameters."""
    for p in STORE.products.values():
        if p["status"] == "ACTIVE" and p["antigen"] == antigen:
            return p
    return None


# -------------------------------------------------------------------
# compute_dose_validity (§1.3 / §2.7)
# -------------------------------------------------------------------

def compute_dose_validity(patient_id, antigen):
    """Chronological replay over a patient's non-DELETED doses of one antigen.
    Mutates validity & dose_number in place on the immunization rows."""
    patient = STORE.patients.get(patient_id)
    if not patient:
        return
    dob = parse_date(patient["date_of_birth"])

    doses = []
    for imm in STORE.immunizations.values():
        if imm["patient_id"] != patient_id:
            continue
        if imm["status"] == "DELETED":
            continue
        if antigen_of_immunization(imm) != antigen:
            continue
        doses.append(imm)

    # order by administered_date ASC, then created_at ASC (via _seq tie-break)
    doses.sort(key=lambda d: (parse_date(d["administered_date"]) or date.min, d["_seq"]))

    last_valid_date = None
    valid_index = 0
    for d in doses:
        lot = STORE.lots.get(d["lot_id"])
        prod = product_of_lot(lot) if lot else None
        grace = prod["grace_period_days"] if prod else 0
        adm = parse_date(d["administered_date"])
        age_days = days_between(dob, adm) if (dob and adm) else 0

        # An INVALIDATED-by-recall dose stays INVALID_RECALL and is not counted
        # until it is revalidated (status restored to RECORDED).
        if d["status"] == "INVALIDATED":
            d["validity"] = "INVALID_RECALL"
            continue
        if lot and lot["status"] == "RECALLED":
            d["validity"] = "INVALID_RECALL"
            continue
        if prod and age_days < (prod["min_age_days"] - grace):
            d["validity"] = "INVALID_AGE"
            continue
        if (last_valid_date is not None and prod is not None and
                days_between(last_valid_date, adm) < (prod["min_interval_days"] - grace)):
            d["validity"] = "INVALID_INTERVAL"
            continue
        # VALID
        d["validity"] = "VALID"
        valid_index += 1
        d["dose_number"] = valid_index
        last_valid_date = adm


def recompute_patient_antigen(patient_id, antigen):
    compute_dose_validity(patient_id, antigen)


# -------------------------------------------------------------------
# Lot inventory reconciliation (§1.3 lot_inventory_balance)
# -------------------------------------------------------------------

def reconcile_lot(lot_id):
    """Set lot.administered_count = count of RECORDED/AMENDED immunizations on it.
    Touches the lot (updated_at/version) only when the count actually changes."""
    lot = STORE.lots.get(lot_id)
    if not lot:
        return
    cnt = 0
    for imm in STORE.immunizations.values():
        if imm["lot_id"] == lot_id and imm["status"] in ("RECORDED", "AMENDED"):
            cnt += 1
    if lot["administered_count"] != cnt:
        lot["administered_count"] = cnt
        touch(lot)


# -------------------------------------------------------------------
# schedule_next_due + compliance_completeness (§1.3 / §3.6)
# -------------------------------------------------------------------

def valid_doses_for_antigen(patient_id, antigen):
    out = []
    for imm in STORE.immunizations.values():
        if (imm["patient_id"] == patient_id and imm["status"] != "DELETED"
                and imm["validity"] == "VALID" and antigen_of_immunization(imm) == antigen):
            out.append(imm)
    out.sort(key=lambda d: d["dose_number"])
    return out


def has_contraindication(patient_id, antigen):
    for a in STORE.allergy_records.values():
        if (a["patient_id"] == patient_id and a["antigen"] == antigen
                and a["severity"] == "CONTRAINDICATED"):
            return True
    return False


def compute_evaluation_fields(patient_id, as_of_date):
    """Returns (antigen_results, completeness_pct, overall_status)."""
    patient = STORE.patients.get(patient_id)
    dob = parse_date(patient["date_of_birth"])
    antigens = mandated_antigens()

    antigen_results = []
    per_antigen_pct = []
    any_unsatisfiable_contra = False
    all_satisfied = True
    behind_due_dates_ok = True  # every unsatisfied antigen not yet due

    for ag in antigens:
        prod = active_product_for_antigen(ag)
        required = prod["doses_in_series"] if prod else 1
        grace = prod["grace_period_days"] if prod else 0
        valids = valid_doses_for_antigen(patient_id, ag)
        valid_count = len(valids)
        satisfied = valid_count >= required

        if valid_count == 0:
            last_valid_date = dob
            next_valid = date_plus(dob, prod["min_age_days"] - grace) if prod else dob
            next_rec = date_plus(dob, prod["recommended_age_days"]) if prod else dob
        else:
            last_valid_date = parse_date(valids[-1]["administered_date"])
            next_valid = date_plus(last_valid_date, prod["min_interval_days"] - grace) if prod else last_valid_date
            next_rec = date_plus(last_valid_date, prod["min_interval_days"]) if prod else last_valid_date

        contra = has_contraindication(patient_id, ag)

        antigen_results.append({
            "antigen": ag,
            "valid_dose_count": valid_count,
            "required_doses": required,
            "next_valid_due_date": next_valid.isoformat(),
            "next_recommended_due_date": next_rec.isoformat(),
            "satisfied": satisfied,
        })

        # per-antigen pct: round per antigen first
        pct = (Decimal(100) * Decimal(min(valid_count, required)) / Decimal(required)
               ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        per_antigen_pct.append(pct)

        if not satisfied:
            all_satisfied = False
            if contra:
                any_unsatisfiable_contra = True
            if not (next_valid > as_of_date):
                behind_due_dates_ok = False

    if antigens:
        avg = (sum(per_antigen_pct) / Decimal(len(antigens))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        completeness_pct = float(avg)
    else:
        completeness_pct = 100.00

    if any_unsatisfiable_contra:
        overall = "NON_COMPLIANT"
    elif all_satisfied:
        overall = "UP_TO_DATE"
    elif behind_due_dates_ok:
        overall = "CONDITIONAL"
    else:
        overall = "BEHIND"

    return antigen_results, completeness_pct, overall


def create_evaluation(patient_id, as_of_date):
    """Create a new ScheduleEvaluation, copy overall_status to patient.schedule_status,
    bump patient.version."""
    antigen_results, completeness_pct, overall = compute_evaluation_fields(patient_id, as_of_date)
    eid = STORE.new_id()
    ev = stamp_new({
        "id": eid,
        "patient_id": patient_id,
        "as_of_date": as_of_date.isoformat(),
        "overall_status": overall,
        "antigen_results": antigen_results,
        "completeness_pct": completeness_pct,
    })
    STORE.evaluations[eid] = ev
    patient = STORE.patients[patient_id]
    patient["schedule_status"] = overall
    touch(patient)
    return ev


def latest_evaluation(patient_id):
    evs = [e for e in STORE.evaluations.values() if e["patient_id"] == patient_id]
    if not evs:
        return None
    evs.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return evs[-1]


def recompute_latest_evaluation(patient_id):
    """Cascade hop 2: recompute the patient's latest evaluation in place
    (same as_of_date) and update schedule_status. Returns the new overall_status
    (or current schedule_status if no evaluation exists yet)."""
    patient = STORE.patients.get(patient_id)
    if not patient:
        return None
    ev = latest_evaluation(patient_id)
    if ev is None:
        return patient["schedule_status"]
    as_of = parse_date(ev["as_of_date"])
    antigen_results, completeness_pct, overall = compute_evaluation_fields(patient_id, as_of)
    ev["overall_status"] = overall
    ev["antigen_results"] = antigen_results
    ev["completeness_pct"] = completeness_pct
    touch(ev)
    patient["schedule_status"] = overall
    touch(patient)
    return overall


# -------------------------------------------------------------------
# Certificate revocation cascade (§3.7 hop 3)
# -------------------------------------------------------------------

def revoke_certs_if_dropped(patient_id, overall_status):
    """If overall_status is BEHIND or NON_COMPLIANT, revoke the patient's ACTIVE cert."""
    if overall_status not in ("BEHIND", "NON_COMPLIANT"):
        return
    patient = STORE.patients.get(patient_id)
    for c in STORE.certificates.values():
        if c["patient_id"] == patient_id and c["status"] == "ACTIVE":
            c["status"] = "REVOKED"
            touch(c)
            if patient:
                patient["active_certificate_id"] = None
                touch(patient)
