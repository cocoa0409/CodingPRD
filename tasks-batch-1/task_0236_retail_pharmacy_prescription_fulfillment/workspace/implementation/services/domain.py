"""Cross-entity domain operations: derived-field reconciliation, PDMP
regeneration, DUR screening, and the patient monitoring cascade.

These helpers mutate multiple resources within a single request and bump each
mutated resource's version/updated_at (PRD §2.6).
"""
import db
from common import stamp_create, touch
from clock import parse_iso
from services import calc

# Fill workflow states that "consume" a refill (PRD §3.3 refills_remaining).
CONSUMING_STATES = {"ADJUDICATING", "PA_REFERRAL", "READY_FILL", "WILL_CALL", "DISPENSED"}

CONTROLLED_SCHEDULES = {"CII", "CIII", "CIV", "CV"}


# ---------------------------------------------------------------------------
# Refills remaining (PRD §3.3)
# ---------------------------------------------------------------------------


def recompute_refills_remaining(prescription):
    """consumed = consuming fills excluding the original (fill_sequence==1)."""
    consumed = 0
    for f in db.fills.values():
        if f["prescription_id"] != prescription["id"]:
            continue
        if f["fill_sequence"] == 1:
            continue
        if f["status"] in CONSUMING_STATES:
            consumed += 1
    remaining = max(prescription["refills_authorized"] - consumed, 0)
    if prescription.get("refills_remaining") != remaining:
        prescription["refills_remaining"] = remaining
        touch(prescription)
    else:
        prescription["refills_remaining"] = remaining
    return remaining


# ---------------------------------------------------------------------------
# DUR screen (PRD §3.5)
# ---------------------------------------------------------------------------


def run_dur_screen(fill):
    """Create DurAlert rows from four heterogeneous sources; return max severity.

    Mutates: creates DurAlert rows, sets fill.dur_severity.
    """
    prescription = db.prescriptions[fill["prescription_id"]]
    patient = db.patients[prescription["patient_id"]]
    drug = db.drug_products[prescription["drug_id"]]

    # Other non-cancelled fills of the SAME patient (their drugs).
    other_fills = []
    for f in db.fills.values():
        if f["id"] == fill["id"]:
            continue
        if f["status"] == "CANCELLED":
            continue
        rx = db.prescriptions.get(f["prescription_id"])
        if rx is None or rx["patient_id"] != patient["id"]:
            continue
        other_fills.append((f, rx))

    severities = []

    # 1) Drug-drug interactions: rule pairing fill's drug with any other
    #    non-cancelled fill's drug for the same patient.
    other_drug_ids = {rx["drug_id"] for (_f, rx) in other_fills}
    for rule in db.interaction_rules.values():
        a, b = rule["drug_a_id"], rule["drug_b_id"]
        matches = (a == drug["id"] and b in other_drug_ids) or \
                  (b == drug["id"] and a in other_drug_ids)
        if matches:
            severities.append(rule["severity"])
            _create_alert(fill, "INTERACTION", rule["severity"], rule["detail"])

    # 2) Allergy: fill's drug shares an allergy class with patient's allergy_classes.
    drug_allergy_classes = set(drug.get("allergy_classes") or [])
    # DrugProduct has no allergy_classes field in the schema; the spec keys
    # allergy off shared class membership. We treat the drug's NAME class via
    # an explicit drug allergy class list if present; otherwise match on the
    # drug name appearing in patient's allergy_classes (defensive). The PRD
    # says "if the fill's drug shares an allergy class present in the patient's
    # allergy_classes". With no class field on the drug, we match the drug name.
    shared = False
    patient_allergies = set(patient.get("allergy_classes") or [])
    if drug_allergy_classes and (drug_allergy_classes & patient_allergies):
        shared = True
    elif drug.get("name") in patient_allergies:
        shared = True
    if shared:
        severities.append("SEVERE")
        _create_alert(fill, "ALLERGY", "SEVERE",
                      "Patient allergy class matches drug")

    # 3) Duplicate therapy: another non-cancelled fill of same patient, same drug.
    if any(rx["drug_id"] == drug["id"] for (_f, rx) in other_fills):
        severities.append("MODERATE")
        _create_alert(fill, "DUPLICATE_THERAPY", "MODERATE",
                      "Duplicate therapy for the same drug")

    # 4) High dose: quantity_dispensed / days_supply > 4 units/day.
    if fill["days_supply"] > 0 and \
            (fill["quantity_dispensed"] / fill["days_supply"]) > calc.HIGH_DOSE_UNITS_PER_DAY:
        severities.append("MODERATE")
        _create_alert(fill, "HIGH_DOSE", "MODERATE",
                      "Daily dose exceeds high-dose threshold")

    fill["dur_severity"] = calc.severity_max(severities)
    return fill["dur_severity"]


def _create_alert(fill, alert_type, severity, detail):
    alert = {
        "fill_id": fill["id"],
        "alert_type": alert_type,
        "severity": severity,
        "detail": detail,
        "overridden": False,
        "override_reason": None,
    }
    stamp_create(alert)
    db.dur_alerts[alert["id"]] = alert
    return alert


def alerts_for_fill(fill_id):
    return [a for a in db.dur_alerts.values() if a["fill_id"] == fill_id]


def unoverridden_blocking_alerts(fill_id):
    """MODERATE/SEVERE alerts on the fill that are not yet overridden."""
    out = []
    for a in alerts_for_fill(fill_id):
        if a["severity"] in ("MODERATE", "SEVERE") and not a["overridden"]:
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# PDMP risk + patient posture cascade (PRD §3.7 / §3.2)
# ---------------------------------------------------------------------------


def _qualifying_controlled_fills(patient, statuses):
    """Controlled fills for the patient in the given workflow statuses, within
    the 90-day lookback measured back from current_utc (the LOGICAL clock).

    The lookback anchor is each fill's logical dispense instant
    (Fill.dispensed_utc = current_utc at dispense). In-flight fills counted by
    the provisional variant have not dispensed yet, so they are anchored at the
    current logical clock (always inside the window).
    """
    cur = parse_iso(db.current_utc())
    out = []
    for f in db.fills.values():
        if f["status"] not in statuses:
            continue
        rx = db.prescriptions.get(f["prescription_id"])
        if rx is None or rx["patient_id"] != patient["id"]:
            continue
        drug = db.drug_products.get(rx["drug_id"])
        if drug is None or drug["dea_schedule"] not in CONTROLLED_SCHEDULES:
            continue
        # Logical anchor for the lookback window.
        anchor_raw = f.get("dispensed_utc") or db.current_utc()
        anchor = parse_iso(anchor_raw)
        if anchor > cur:
            continue
        if (cur - anchor).days > calc.PDMP_LOOKBACK_DAYS:
            continue
        out.append((f, rx))
    return out


def compute_pdmp(patient, variant):
    """Compute (controlled_fill_count, distinct_prescriber_count, risk_score,
    resulting_flag) for the patient.

    variant 'committed' counts only DISPENSED fills; 'provisional' also counts
    in-flight fills in {ADJUDICATING, READY_FILL}.
    """
    if variant == "committed":
        statuses = {"DISPENSED"}
    elif variant == "provisional":
        statuses = {"DISPENSED", "ADJUDICATING", "READY_FILL"}
    else:
        raise ValueError(variant)
    qualifying = _qualifying_controlled_fills(patient, statuses)
    count = len(qualifying)
    prescribers = {rx["prescriber_id"] for (_f, rx) in qualifying}
    distinct = len(prescribers)
    score = calc.pdmp_risk_score(count, distinct)
    flag = calc.pdmp_flag_for_score(score)
    return count, distinct, score, flag


def apply_posture(patient, resulting_flag):
    """Drive Patient.pdmp_flag / controlled_status from a committed report.

    Mirrors the Patient parallel state machine (scaffold §1.2): REVIEW keeps
    controlled_status ELIGIBLE; BLOCKED flips controlled_status to LOCKED.
    A CLEAR/REVIEW result does not lift an existing LOCK (only the manual
    clear-pdmp-block does), so we never downgrade BLOCKED automatically.
    """
    changed = False
    if resulting_flag == "BLOCKED":
        if patient["pdmp_flag"] != "BLOCKED" or patient["controlled_status"] != "LOCKED":
            patient["pdmp_flag"] = "BLOCKED"
            patient["controlled_status"] = "LOCKED"
            changed = True
    elif resulting_flag == "REVIEW":
        # Do not downgrade an existing BLOCKED posture automatically.
        if patient["pdmp_flag"] == "CLEAR":
            patient["pdmp_flag"] = "REVIEW"
            changed = True
    else:  # CLEAR
        if patient["pdmp_flag"] == "REVIEW":
            patient["pdmp_flag"] = "CLEAR"
            changed = True
    if changed:
        touch(patient)
    return changed


def generate_pdmp_report(patient, fill_id, variant="committed"):
    """Create a persisted PdmpReport (committed variant) and drive posture.

    Returns the created report. Used both by the dispense cascade and by the
    manual /pdmp-reports query.
    """
    count, distinct, score, flag = compute_pdmp(patient, variant)
    report = {
        "patient_id": patient["id"],
        "fill_id": fill_id,
        "lookback_days": calc.PDMP_LOOKBACK_DAYS,
        "controlled_fill_count": count,
        "distinct_prescriber_count": distinct,
        "risk_score": score,
        "resulting_flag": flag,
    }
    stamp_create(report)
    db.pdmp_reports[report["id"]] = report
    apply_posture(patient, flag)
    return report
