"""Business-logic cascades: claims engine, case completion/cancel, clock sweeps, audits."""
from decimal import Decimal

from store import db
import calc


# ---------------------------------------------------------------------------
# Claims engine (modifier_determination + charge_units + direction_split)
# ---------------------------------------------------------------------------
def _case_units_actual(case):
    fee = calc.fee_by_code(case["procedure_code"])
    minutes = case["actual_end_minute"] - case["actual_start_minute"]
    return calc.compute_units(fee["base_units"], minutes,
                              case["physical_status"], case["emergency_flag"])


def _direction_peak_count(physician_id, service_date, this_case):
    """CONFIRMED/COMPLETED CASE_DIRECTING assignments on the service date whose case's
    scheduled half-open interval contains this case's scheduled_start (this case included)."""
    count = 0
    for a in db.assignments.values():
        if a["provider_id"] == physician_id and a["assignment_role"] == "CASE_DIRECTING" \
                and a["status"] in ("CONFIRMED", "COMPLETED"):
            c = db.cases.get(a["case_id"])
            if c is None or calc.service_date_of_case(c) != service_date:
                continue
            if c["scheduled_start_minute"] <= this_case["scheduled_start_minute"] < c["scheduled_end_minute"]:
                count += 1
    return count


def compute_claim_values(case, assignment, primary_asg, directing_asg):
    """Return (modifier_code, units_total, charge_cents) for the payee of `assignment`."""
    provider = db.providers[assignment["provider_id"]]
    units = _case_units_actual(case)
    service_date = calc.service_date_of_case(case)

    if assignment["assignment_role"] == "CASE_PRIMARY":
        if directing_asg is None:
            if provider["provider_type"] == "ANESTHESIOLOGIST":
                return "PERSONAL", units, calc.charge_for(units, calc.PERSONAL_CF_CENTS)
            return "QZ", units, calc.charge_for(units, calc.CRNA_SOLO_CF_CENTS)
        att = calc.find_attestation(case["id"], directing_asg["provider_id"])
        if att and att["status"] == "VERIFIED":
            _, _, primary_half = calc.direction_split(units)
            return "QX", units, primary_half
        return "QZ", units, calc.charge_for(units, calc.CRNA_SOLO_CF_CENTS)

    # CASE_DIRECTING physician claim
    att = calc.find_attestation(case["id"], assignment["provider_id"])
    if att and att["status"] == "VERIFIED":
        _, physician_half, _ = calc.direction_split(units)
        peak = _direction_peak_count(assignment["provider_id"], service_date, case)
        return ("QY" if peak == 1 else "QK"), units, physician_half
    units_ad = Decimal(calc.AD_FLAT_UNITS)
    return "AD", units_ad, calc.AD_FLAT_UNITS * calc.SUPERVISION_CF_CENTS


def create_claim(case, assignment, primary_asg, directing_asg):
    modifier, units, charge = compute_claim_values(case, assignment, primary_asg, directing_asg)
    rec = db.new_record(
        case_id=case["id"],
        provider_id=assignment["provider_id"],
        modifier_code=modifier,
        units_total=float(units),
        charge_cents=int(charge),
        status="DRAFT",
        denial_reason=None,
        paid_amount_cents=None,
        resubmission_count=0,
    )
    db.claims[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Compliance findings
# ---------------------------------------------------------------------------
def _open_audit_for_roster(roster_id, create=True):
    for a in db.audits.values():
        if a["roster_id"] == roster_id and a["status"] == "OPEN":
            return a
    if not create:
        return None
    rec = db.new_record(roster_id=roster_id, status="OPEN",
                        realtime_score=0, period_score=0, risk_band="LOW")
    db.audits[rec["id"]] = rec
    return rec


def add_finding(audit, finding_type, case_id, assignment_id, dedupe=False):
    if dedupe:
        for f in db.findings.values():
            if f["audit_id"] == audit["id"] and f["status"] == "OPEN" \
                    and f["finding_type"] == finding_type \
                    and f.get("case_id") == case_id and f.get("assignment_id") == assignment_id:
                return f
    rec = db.new_record(
        audit_id=audit["id"],
        case_id=case_id,
        assignment_id=assignment_id,
        finding_type=finding_type,
        severity=calc.FINDING_SEVERITY[finding_type],
        status="OPEN",
        resolution_note=None,
    )
    db.findings[rec["id"]] = rec
    return rec


def raise_tefra_gap(roster, case):
    audit = _open_audit_for_roster(roster["id"], create=True)
    add_finding(audit, "TEFRA_GAP", case["id"], None)


# ---------------------------------------------------------------------------
# Provisional charge
# ---------------------------------------------------------------------------
def recompute_provisional(case):
    primary = None
    directing_confirmed = False
    for a in db.assignments.values():
        if a["case_id"] != case["id"] or a["status"] != "CONFIRMED":
            continue
        if a["assignment_role"] == "CASE_PRIMARY":
            primary = a
        elif a["assignment_role"] == "CASE_DIRECTING":
            directing_confirmed = True
    if primary is None:
        case["provisional_charge_cents"] = None
        return
    provider = db.providers[primary["provider_id"]]
    fee = calc.fee_by_code(case["procedure_code"])
    minutes = case["scheduled_end_minute"] - case["scheduled_start_minute"]
    units = calc.compute_units(fee["base_units"], minutes,
                               case["physical_status"], case["emergency_flag"])
    if directing_confirmed:
        cf = calc.DIRECTION_CF_CENTS
    elif provider["provider_type"] == "ANESTHESIOLOGIST":
        cf = calc.PERSONAL_CF_CENTS
    else:
        cf = calc.CRNA_SOLO_CF_CENTS
    case["provisional_charge_cents"] = calc.charge_for(units, cf)


# ---------------------------------------------------------------------------
# Case completion / cancellation cascades
# ---------------------------------------------------------------------------
def complete_case(case, clock_minute):
    roster = db.rosters[case["roster_id"]]
    case["actual_end_minute"] = clock_minute
    case["status"] = "COMPLETED"
    db.bump(case)

    live = [a for a in db.assignments.values()
            if a["case_id"] == case["id"] and a["status"] in ("PROPOSED", "CONFIRMED")]
    confirmed = [a for a in live if a["status"] == "CONFIRMED"]
    for a in live:
        a["status"] = "COMPLETED"
        db.bump(a)

    primary = next((a for a in confirmed if a["assignment_role"] == "CASE_PRIMARY"), None)
    directing = next((a for a in confirmed if a["assignment_role"] == "CASE_DIRECTING"), None)

    claims = [create_claim(case, a, primary, directing) for a in confirmed]
    case["final_charge_cents"] = sum(c["charge_cents"] for c in claims)

    if directing is not None:
        att = calc.find_attestation(case["id"], directing["provider_id"])
        if att is None or att["status"] != "VERIFIED":
            raise_tefra_gap(roster, case)

    if primary is not None:
        prov_id = primary["provider_id"]
        if not calc.has_call_on_date(prov_id, roster["service_date"]) \
                and clock_minute > roster["scheduled_day_end_minute"]:
            ag = calc.find_agreement(roster["site_id"], roster["service_date"])
            if ag is not None:
                amount = (clock_minute - roster["scheduled_day_end_minute"]) \
                    * ag["late_stay_rate_cents_per_minute"]
                calc.create_stipend_entry(prov_id, roster["id"], "LATE_STAY",
                                          roster["service_date"], amount)


def cancel_case(case, reason, clock_date, clock_minute):
    roster = db.rosters[case["roster_id"]]
    if clock_date == roster["service_date"]:
        notice = case["scheduled_start_minute"] - clock_minute
    else:
        # clock date strictly before service_date (later dates are rejected upstream)
        notice = 1440 + case["scheduled_start_minute"] - clock_minute
    case["cancellation_notice_minutes"] = notice
    case["cancellation_reason"] = reason
    case["status"] = "CANCELLED"
    db.bump(case)

    live = [a for a in db.assignments.values()
            if a["case_id"] == case["id"] and a["status"] in ("PROPOSED", "CONFIRMED")]
    confirmed_primary = next((a for a in live
                              if a["status"] == "CONFIRMED"
                              and a["assignment_role"] == "CASE_PRIMARY"), None)
    for a in live:
        a["status"] = "CANCELLED"
        db.bump(a)

    if confirmed_primary is not None:
        ag = calc.find_agreement(roster["site_id"], roster["service_date"])
        if ag is not None:
            if notice < calc.STANDBY_FULL_NOTICE_MINUTES:
                raw = ag["standby_full_cents"]
            elif notice < calc.STANDBY_NOTICE_FREE_MINUTES:
                raw = ag["standby_partial_cents"]
            else:
                raw = None
            if raw is not None:
                calc.create_stipend_entry(confirmed_primary["provider_id"], roster["id"],
                                          "STANDBY", roster["service_date"], raw)


# ---------------------------------------------------------------------------
# Clock sweeps
# ---------------------------------------------------------------------------
def sweep_clock(new_clock):
    """Provider suspension + call-assignment auto-completion after a clock set."""
    new_date = new_clock.strftime("%Y-%m-%d")
    new_min = new_clock.hour * 60 + new_clock.minute

    for p in db.providers.values():
        if p["status"] != "ACTIVE":
            continue
        earlier = min(p["credential_expires_on"], p["dea_expires_on"])
        if new_date > earlier:
            p["status"] = "SUSPENDED"
            db.bump(p)

    for ca in db.call_assignments.values():
        if ca["status"] != "SCHEDULED":
            continue
        roster = db.rosters.get(ca["roster_id"])
        if roster is None:
            continue
        past = (new_date > roster["service_date"]) or \
               (new_date == roster["service_date"] and new_min > ca["window_end_minute"])
        if past:
            ca["status"] = "COMPLETED"
            db.bump(ca)
            ag = calc.find_agreement(roster["site_id"], roster["service_date"])
            if ag is not None:
                calc.create_stipend_entry(ca["provider_id"], roster["id"], "CALL",
                                          roster["service_date"], ag["call_stipend_cents"])


# ---------------------------------------------------------------------------
# Audit scan (POST /audits create-or-merge)
# ---------------------------------------------------------------------------
def run_audit_scan(roster):
    audit = _open_audit_for_roster(roster["id"], create=True)
    roster_cases = [c for c in db.cases.values() if c["roster_id"] == roster["id"]]
    roster_asgs = [a for a in db.assignments.values() if a["roster_id"] == roster["id"]]

    # (a) CONCURRENCY_RETRO_BREACH: actual-interval peak > RATIO_MAX per physician
    by_phys = {}
    for a in roster_asgs:
        if a["assignment_role"] == "CASE_DIRECTING" and a["status"] == "COMPLETED":
            c = db.cases.get(a["case_id"])
            if c and c["status"] == "COMPLETED":
                by_phys.setdefault(a["provider_id"], []).append(c)
    for phys, clist in by_phys.items():
        intervals = [(c["actual_start_minute"], c["actual_end_minute"], c) for c in clist]
        peak, members = calc.peak_set(intervals)
        if peak > calc.RATIO_MAX:
            chosen = sorted(members,
                            key=lambda c: (-c["actual_start_minute"], c["created_at"], c["_seq"]))[0]
            add_finding(audit, "CONCURRENCY_RETRO_BREACH", chosen["id"], None, dedupe=True)

    # (b) CREDENTIAL_LAPSE: PROPOSED/CONFIRMED assignment whose provider lapsed pre-service
    for a in roster_asgs:
        if a["status"] in ("PROPOSED", "CONFIRMED"):
            p = db.providers.get(a["provider_id"])
            if p and min(p["credential_expires_on"], p["dea_expires_on"]) < roster["service_date"]:
                add_finding(audit, "CREDENTIAL_LAPSE", a["case_id"], a["id"], dedupe=True)

    # (c) TEFRA_GAP: COMPLETED case with COMPLETED CASE_DIRECTING whose attestation unverified
    for c in roster_cases:
        if c["status"] != "COMPLETED":
            continue
        for a in roster_asgs:
            if a["case_id"] == c["id"] and a["assignment_role"] == "CASE_DIRECTING" \
                    and a["status"] == "COMPLETED":
                att = calc.find_attestation(c["id"], a["provider_id"])
                if att is None or att["status"] != "VERIFIED":
                    add_finding(audit, "TEFRA_GAP", c["id"], None, dedupe=True)
    return audit


def raise_credential_lapse_findings(provider, new_cred, new_dea):
    """Credential patch side effect: findings for live assignments served past new expiry."""
    threshold = min(new_cred, new_dea)
    touched_rosters = set()
    for a in db.assignments.values():
        if a["provider_id"] != provider["id"] or a["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        roster = db.rosters.get(a["roster_id"])
        if roster is None:
            continue
        if roster["service_date"] > threshold:
            audit = _open_audit_for_roster(roster["id"], create=True)
            add_finding(audit, "CREDENTIAL_LAPSE", a["case_id"], a["id"], dedupe=True)
            touched_rosters.add(roster["id"])
