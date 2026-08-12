"""Business logic: calculations, state-machine side effects, clock sweeps.

Everything here derives from SCAFFOLD.yaml §1.2/§1.3 and PRD §3; the PRD is
the literal contract wherever the two disagree.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store
import errors as E
from util import iso_z, touch, stamp_new, new_id, is_after_hours_instant

# ---------------------------------------------------------------------------
# constants from SCAFFOLD.yaml §1.3
# ---------------------------------------------------------------------------

RVU_BASE = {"CT": Decimal("1.5"), "MR": Decimal("2.0"), "XR": Decimal("0.5"),
            "US": Decimal("1.0"), "NM": Decimal("1.5"), "MG": Decimal("1.0")}

DISCREPANCY_PENALTY = {0: Decimal("0.0"), 1: Decimal("0.0"),
                       2: Decimal("0.25"), 3: Decimal("0.5")}
PRELIM_FACTOR = Decimal("0.8")

TIER1_LIMIT = 1000
TIER1_RATE_CENTS = 901
TIER2_LIMIT = 5000
TIER2_RATE_CENTS = 801
TIER3_RATE_CENTS = 701
AFTER_HOURS_MULTIPLIER = Decimal("1.5")
CRITICAL_ADDON_CENTS = 250

NON_TERMINAL_CASE_STATUSES = {"OPEN", "PEER_REVIEW", "ESCALATED_QI"}

MODALITIES = {"CT", "MR", "XR", "US", "NM", "MG"}
BODY_PART_GROUPS = {"NEURO", "BODY", "MSK", "CHEST", "VASCULAR", "OTHER"}
PRIORITIES = {"STAT", "URGENT", "ROUTINE"}
SUBSPECIALTIES = {"NEURORAD", "MSK", "BODY", "CHEST", "PEDS", "GENERAL"}


# ---------------------------------------------------------------------------
# small domain helpers
# ---------------------------------------------------------------------------

def study_rvu(study):
    return RVU_BASE[study["modality"]]


def active_credential_grant(radiologist_id, hospital_id, today):
    for g in store.credential_grants.values():
        if (g["radiologist_id"] == radiologist_id and g["hospital_id"] == hospital_id
                and g["status"] == "GRANTED"
                and g["valid_from"] <= today.isoformat() <= g["valid_until"]):
            return g
    return None


def active_shift_for_modality(radiologist_id, modality):
    for s in store.shifts.values():
        if (s["radiologist_id"] == radiologist_id and s["status"] == "ACTIVE"
                and modality in s["modalities"]):
            return s
    return None


def signed_prelim_for_study(study_id):
    for r in store.reports.values():
        if (r["study_id"] == study_id and r["report_type"] == "PRELIMINARY"
                and r["status"] == "SIGNED"):
            return r
    return None


def signed_final_for_study(study_id):
    for r in store.reports.values():
        if (r["study_id"] == study_id and r["report_type"] == "FINAL"
                and r["status"] == "SIGNED"):
            return r
    return None


def active_assignment_for_study(study_id):
    for a in store.assignments.values():
        if a["study_id"] == study_id and a["status"] == "ACTIVE":
            return a
    return None


def open_case_for_study(study_id):
    for c in store.discrepancy_cases.values():
        if c["study_id"] == study_id and c["status"] in NON_TERMINAL_CASE_STATUSES:
            return c
    return None


# ---------------------------------------------------------------------------
# derived radiologist counters (SCAFFOLD fatigue_utilization; PRD §2.9)
# ---------------------------------------------------------------------------

def recompute_radiologist_counters(rad):
    rid = rad["id"]
    now = store.now()
    reserved = Decimal("0.0")
    stat_active = 0
    for a in store.assignments.values():
        if a["radiologist_id"] == rid and a["status"] == "ACTIVE":
            reserved = reserved + Decimal(str(a["reserved_rvu"]))
            study = store.studies.get(a["study_id"])
            if study is not None and study["priority"] == "STAT":
                stat_active += 1
    window_start = now - timedelta(hours=24)
    completed = Decimal("0.0")
    for r in store.reports.values():
        if (r["radiologist_id"] == rid and r["status"] in ("SIGNED", "SUPERSEDED")
                and r["signed_at"] is not None):
            from util import parse_iso  # local import to avoid cycle
            signed_at = parse_iso(r["signed_at"], "signed_at")
            if signed_at > window_start:  # strict lower bound: exactly 24h ago excluded
                completed = completed + Decimal(str(r["credited_rvu"]))
    pending_critical = 0
    for n in store.critical_notices.values():
        if n["radiologist_id"] == rid and n["status"] in ("PENDING", "NOTIFIED", "ESCALATED"):
            pending_critical += 1
    rad["reserved_rvu"] = float(reserved)
    rad["completed_rvu_24h"] = float(completed)
    rad["stat_active_count"] = stat_active
    rad["pending_critical_count"] = pending_critical


# ---------------------------------------------------------------------------
# TAT deadline / breach (tat_deadline, tat_breach_and_penalty)
# ---------------------------------------------------------------------------

def compute_due_at(hospital, priority, received_at):
    minutes = {"STAT": hospital["tat_stat_minutes"],
               "URGENT": hospital["tat_urgent_minutes"],
               "ROUTINE": hospital["tat_routine_minutes"]}[priority]
    return received_at + timedelta(minutes=minutes)


def evaluate_tat(study, relevant_signed_at):
    """tat_breached true only when signed strictly after due_at; whole minutes
    of lateness via floor."""
    from util import parse_iso
    due_at = parse_iso(study["due_at"], "due_at")
    if relevant_signed_at > due_at:
        study["tat_breached"] = True
        study["breach_minutes"] = int((relevant_signed_at - due_at).total_seconds() // 60)
    else:
        study["tat_breached"] = False
        study["breach_minutes"] = 0


# ---------------------------------------------------------------------------
# report_rvu_credit
# ---------------------------------------------------------------------------

def credit_for_report(report_type, rvu_base, discrepancy_grade):
    if report_type == "PRELIMINARY":
        value = PRELIM_FACTOR * rvu_base
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if report_type == "FINAL":
        penalty = DISCREPANCY_PENALTY.get(discrepancy_grade, Decimal("0.0")) \
            if discrepancy_grade is not None else Decimal("0.0")
        value = rvu_base * (Decimal("1") - penalty)
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return 0.0  # ADDENDUM


# ---------------------------------------------------------------------------
# auto_assignment_selector (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def selector_check_radiologist(rad, study, policy, study_rvu_value, phase, prelim_signer_id,
                               enforce_prelim_signer_gate=True):
    """Run the nine eligibility gates for one radiologist. Returns None when
    eligible, else the (error-spec, message) for the FIRST failing gate in
    validation-priority order (PRD §3.5).

    Gate (9) — FINAL-phase candidate must not be the preliminary signer — is an
    auto-selector filter. PRD §3.5's manual-assignment error map names no error
    for it; the same-reader conflict is enforced at sign time per PRD §3.6
    (ERR_SAME_READER_CONFLICT). Manual assignment therefore evaluates with
    enforce_prelim_signer_gate=False.
    """
    today = store.now().date()
    # (1) status ACTIVE — not in the error map; treated as an eligibility gate.
    if rad["status"] != "ACTIVE":
        return (E.ERR_NO_ELIGIBLE_RADIOLOGIST, "Radiologist is not ACTIVE")
    # (2) licensure (priority 7, license before credential)
    if study["state_code"] not in rad["license_states"]:
        return (E.ERR_LICENSURE_GAP, "Radiologist does not hold a license in the study state")
    # (3) subspecialty when routed
    if policy is not None and policy["required_subspecialty"] not in rad["subspecialties"]:
        return (E.ERR_NO_ELIGIBLE_RADIOLOGIST, "Radiologist lacks the required subspecialty")
    # (4) credential
    if active_credential_grant(rad["id"], study["hospital_id"], today) is None:
        return (E.ERR_CREDENTIAL_NOT_ACTIVE, "No active credential grant for this hospital")
    # (6) exclusion (priority 8, listed before shift in the PRD's error map order)
    if rad["id"] in study["excluded_radiologist_ids"]:
        return (E.ERR_READER_EXCLUDED_FOR_STUDY, "Radiologist is excluded from this study")
    # (5) active shift covering modality
    if active_shift_for_modality(rad["id"], study["modality"]) is None:
        return (E.ERR_NO_ACTIVE_SHIFT, "Radiologist has no ACTIVE shift covering the modality")
    # (7) fatigue headroom (equality allowed)
    projected = Decimal(str(rad["reserved_rvu"])) + study_rvu_value
    if projected > Decimal(str(rad["fatigue_cap_rvu"])):
        return (E.ERR_FATIGUE_CAP_EXCEEDED, "Projected utilization exceeds fatigue cap")
    # (8) STAT concurrency
    if study["priority"] == "STAT" and rad["stat_active_count"] >= rad["max_concurrent_stat"]:
        return (E.ERR_STAT_CONCURRENCY_LIMIT, "STAT concurrency limit reached")
    # (9) FINAL phase must differ from prelim signer (auto-selector filter only)
    if (enforce_prelim_signer_gate and phase == "FINAL"
            and prelim_signer_id is not None and rad["id"] == prelim_signer_id):
        return (E.ERR_SAME_READER_CONFLICT, "Final signer must differ from the preliminary signer")
    return None


def auto_select_radiologist(study, policy, study_rvu_value, phase, prelim_signer_id):
    candidates = []
    for rad in store.radiologists.values():
        failure = selector_check_radiologist(rad, study, policy, study_rvu_value, phase, prelim_signer_id)
        if failure is None:
            candidates.append(rad)
    if not candidates:
        E.raise_err(E.ERR_NO_ELIGIBLE_RADIOLOGIST, "No eligible radiologist for this study")
    # rank: utilization ratio ASC (exact rational compare), then stat_active_count ASC,
    # then radiologist.created_at ASC
    def key(rad):
        projected = Decimal(str(rad["reserved_rvu"])) + study_rvu_value
        cap = Decimal(str(rad["fatigue_cap_rvu"]))
        ratio = projected / cap if cap != 0 else Decimal("Infinity")
        return (ratio, rad["stat_active_count"], rad["created_at"], rad["id"])
    candidates.sort(key=key)
    return candidates[0]


# ---------------------------------------------------------------------------
# cascades shared by sign / release / cancel
# ---------------------------------------------------------------------------

def complete_assignment_cascade(assignment, report):
    """Report signed -> assignment COMPLETED; radiologist counters recomputed."""
    assignment["status"] = "COMPLETED"
    touch(assignment)
    rad = store.radiologists.get(assignment["radiologist_id"])
    if rad is not None:
        recompute_radiologist_counters(rad)


def release_assignment_cascade(assignment):
    """Assignment ACTIVE -> RELEASED; counters recomputed."""
    assignment["status"] = "RELEASED"
    touch(assignment)
    rad = store.radiologists.get(assignment["radiologist_id"])
    if rad is not None:
        recompute_radiologist_counters(rad)


def spawn_critical_notice(report):
    notice = {
        "id": new_id(),
        "report_id": report["id"],
        "study_id": report["study_id"],
        "radiologist_id": report["radiologist_id"],
        "status": "PENDING",
        "notified_party_name": None,
        "notified_at": None,
        "readback_confirmed_by": None,
        "readback_at": None,
        "escalation_count": 0,
    }
    stamp_new(notice)
    store.critical_notices[notice["id"]] = notice
    rad = store.radiologists.get(report["radiologist_id"])
    if rad is not None:
        recompute_radiologist_counters(rad)
    return notice


# ---------------------------------------------------------------------------
# logical-clock sweeps (PRD §2.5)
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    """Idempotent: brings every time-derived state in line with the current
    logical clock. Runs on clock-set requests and lazily before any read or
    write whose behavior depends on shift/grant/notice state, so a shift whose
    window the clock is already inside is ACTIVE even when no clock advance
    has occurred since its creation."""
    now = store.now()
    today = now.date()

    # CoverageShift SCHEDULED->ACTIVE / (SCHEDULED|ACTIVE)->COMPLETED
    for shift in store.shifts.values():
        from util import parse_iso
        starts_at = parse_iso(shift["starts_at"], "starts_at")
        ends_at = parse_iso(shift["ends_at"], "ends_at")
        if shift["status"] == "SCHEDULED":
            if now >= ends_at:
                shift["status"] = "COMPLETED"
                touch(shift)
            elif starts_at <= now < ends_at:
                shift["status"] = "ACTIVE"
                touch(shift)
        elif shift["status"] == "ACTIVE":
            if now >= ends_at:
                shift["status"] = "COMPLETED"
                touch(shift)

    # CredentialGrant GRANTED->EXPIRED when date(now) > valid_until
    for grant in store.credential_grants.values():
        if grant["status"] == "GRANTED":
            valid_until = datetime.strptime(grant["valid_until"], "%Y-%m-%d").date()
            if today > valid_until:
                grant["status"] = "EXPIRED"
                touch(grant)

    # CriticalResultNotice auto-escalation
    from util import parse_iso
    for notice in store.critical_notices.values():
        if notice["status"] == "PENDING":
            created_at = parse_iso(notice["created_at"], "created_at")
            if now > created_at + timedelta(minutes=30):
                notice["status"] = "ESCALATED"
                notice["escalation_count"] += 1
                touch(notice)
        elif notice["status"] == "NOTIFIED" and notice["readback_at"] is None:
            notified_at = parse_iso(notice["notified_at"], "notified_at") if notice["notified_at"] else None
            if notified_at is not None and now > notified_at + timedelta(minutes=60):
                notice["status"] = "ESCALATED"
                notice["escalation_count"] += 1
                touch(notice)


# ---------------------------------------------------------------------------
# invoice_volume_pricing + invoice_total_composition (SCAFFOLD §1.3, PRD §3.9)
# ---------------------------------------------------------------------------

def tier_index_for_unit(unit_number):
    if unit_number <= TIER1_LIMIT:
        return 1
    if unit_number <= TIER2_LIMIT:
        return 2
    return 3


def tier_rate(tier_index):
    return {1: TIER1_RATE_CENTS, 2: TIER2_RATE_CENTS, 3: TIER3_RATE_CENTS}[tier_index]


def compute_invoice(hospital, period):
    """Build the invoice fields per the pinned rounding order of
    invoice_total_composition."""
    from util import parse_iso
    period_start_date = datetime.strptime(period["period_start"], "%Y-%m-%d").date()
    period_end_date = datetime.strptime(period["period_end"], "%Y-%m-%d").date()
    window_start = datetime(period_start_date.year, period_start_date.month,
                            period_start_date.day, tzinfo=timezone.utc)
    window_end = window_start + timedelta(days=(period_end_date - period_start_date).days + 1)

    billable = []
    for study in store.studies.values():
        if study["hospital_id"] != period["hospital_id"]:
            continue
        if study["status"] not in ("FINAL_SIGNED", "AMENDMENT_PENDING"):
            continue
        ffs = study.get("first_final_signed_at")
        if ffs is None:
            continue
        ffs_dt = parse_iso(ffs, "first_final_signed_at")
        if window_start <= ffs_dt < window_end:
            billable.append((study, ffs_dt))
    billable.sort(key=lambda pair: (pair[1], pair[0]["created_at"], pair[0]["id"]))

    pricing_mode = hospital["pricing_mode"]
    count = len(billable)
    highest_tier = tier_index_for_unit(count) if count > 0 else 1

    lines = {}  # (hour_class, tier_index) -> {units, rate_cents}
    critical_addon = 0
    penalty_credits = 0

    for idx, (study, _ffs) in enumerate(billable, start=1):
        if pricing_mode == "MARGINAL":
            unit_tier = tier_index_for_unit(idx)
        else:  # FLAT_TIER: all units at the highest tier reached
            unit_tier = highest_tier
        rate = tier_rate(unit_tier)
        received_at = parse_iso(study["received_at"], "received_at")
        if is_after_hours_instant(received_at):
            hour_class = "AFTER_HOURS"
            # step 1 (pinned): per-unit round_half_up(rate * 1.5), round FIRST
            unit_price = int((Decimal(rate) * AFTER_HOURS_MULTIPLIER).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        else:
            hour_class = "REGULAR"
            unit_price = rate
        key = (hour_class, unit_tier)
        if key not in lines:
            lines[key] = {"hour_class": hour_class, "tier_index": unit_tier,
                          "units": 0, "rate_cents": unit_price}
        lines[key]["units"] += 1

        final_report = signed_final_for_study(study["id"])
        if final_report is not None and final_report.get("critical_finding"):
            critical_addon += CRITICAL_ADDON_CENTS

        if study.get("tat_breached"):
            penalty = min(study["breach_minutes"] * hospital["penalty_per_breach_minute_cents"],
                          hospital["breach_penalty_cap_cents"])
            penalty_credits += penalty

    line_items = []
    for key in sorted(lines.keys(), key=lambda k: (k[0], k[1])):
        line = lines[key]
        line["amount_cents"] = line["units"] * line["rate_cents"]
        line_items.append(line)

    gross = sum(l["amount_cents"] for l in line_items) + critical_addon
    total = max(0, gross - penalty_credits)

    return {
        "pricing_mode_snapshot": pricing_mode,
        "billable_study_count": count,
        "line_items": line_items,
        "critical_addon_cents": critical_addon,
        "gross_cents": gross,
        "penalty_credits_cents": penalty_credits,
        "total_cents": total,
    }
