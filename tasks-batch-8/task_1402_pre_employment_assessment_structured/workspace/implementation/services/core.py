"""Core domain services: computed counters, cascades, composite score,
calibration index, quorum gate, retention anchoring, and time-materialized
automatic transitions. All logic traces to PRD.md / SCAFFOLD.yaml."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from util import bump

Q4 = Decimal("0.0001")


def d4(value):
    """Round half-up to 4 decimal places; returns float for JSON output."""
    return float(Decimal(str(value)).quantize(Q4, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_cycle(cycle_id):
    return db.stores["cycles"].get(cycle_id)


def get_assessment(aid):
    return db.stores["assessments"].get(aid)


def cycle_of_assessment(a):
    return db.stores["cycles"].get(a["cycle_id"])


def requisition_of_cycle(c):
    return db.stores["requisitions"].get(c["requisition_id"])


def instrument_of_cycle(c):
    return db.stores["instruments"].get(c["instrument_id"])


def guide_of_cycle(c):
    return db.stores["guides"].get(c["guide_id"])


def sessions_of_cycle(cycle_id):
    return [s for s in db.stores["sessions"].values() if s["cycle_id"] == cycle_id]


def assessments_of_cycle(cycle_id):
    return [a for a in db.stores["assessments"].values() if a["cycle_id"] == cycle_id]


def decisions_of_cycle(cycle_id):
    return [d for d in db.stores["decisions"].values() if d["cycle_id"] == cycle_id]


def finalized_decision(cycle_id, candidate_id):
    for d in db.stores["decisions"].values():
        if d["cycle_id"] == cycle_id and d["candidate_id"] == candidate_id:
            return d
    return None


def submitted_scorecards(cycle_id, candidate_id):
    """SUBMITTED non-VOIDED scorecards for the candidate within the cycle whose
    session.guide_id equals the cycle's pinned guide_id (PRD §3.8)."""
    cyc = db.stores["cycles"].get(cycle_id)
    if cyc is None:
        return []
    out = []
    for sc in db.stores["scorecards"].values():
        if sc["status"] != "SUBMITTED":
            continue
        if sc["candidate_id"] != candidate_id:
            continue
        sess = db.stores["sessions"].get(sc["session_id"])
        if sess is None or sess["cycle_id"] != cycle_id:
            continue
        if sess["guide_id"] != cyc["guide_id"]:
            continue
        out.append(sc)
    return out


# ---------------------------------------------------------------------------
# Computed counters (recomputed lazily)
# ---------------------------------------------------------------------------

def recompute_cycle_counters(cyc):
    cyc["active_candidate_count"] = sum(
        1 for a in db.stores["assessments"].values()
        if a["cycle_id"] == cyc["id"] and a["admin_status"] not in ("CANCELLED", "PURGED")
    )
    cyc["decisions_finalized_count"] = sum(
        1 for d in db.stores["decisions"].values() if d["cycle_id"] == cyc["id"]
    )


def recompute_guide_pins(guide):
    guide["pinned_cycle_count"] = sum(
        1 for c in db.stores["cycles"].values()
        if c["guide_id"] == guide["id"] and c["posture"] != "CLOSED"
    )


def recompute_interviewer_minutes(interviewer_id):
    iv = db.stores["interviewers"].get(interviewer_id)
    if iv is None:
        return
    total = 0
    for s in db.stores["sessions"].values():
        if s["interviewer_id"] == interviewer_id and s["status"] == "SCHEDULED":
            delta = s["scheduled_end"] - s["scheduled_start"]
            total += int(delta.total_seconds() // 60)
    iv["committed_minutes_total"] = total


def recompute_vendor_outstanding(vendor):
    total = 0
    for e in db.stores["content_ledger_events"].values():
        if e["vendor_id"] != vendor["id"]:
            continue
        if e["direction"] == "DISTRIBUTE":
            total += e["copies"]
        else:
            total -= e["copies"]
    vendor["content_copies_outstanding"] = total


def recompute_requisition_filled(req):
    req["filled_count"] = sum(
        1 for d in db.stores["decisions"].values()
        if d["decision"] == "ADVANCE"
        and db.stores["cycles"].get(d["cycle_id"], {}).get("requisition_id") == req["id"]
    )


# ---------------------------------------------------------------------------
# Composite score (PRD §3.8, calculations.candidate_composite_score)
# ---------------------------------------------------------------------------

def compute_composite(assessment):
    """Recompute and store composite_score. Non-null iff COMPLETED."""
    if assessment["admin_status"] != "COMPLETED":
        assessment["composite_score"] = None
        return
    cyc = db.stores["cycles"].get(assessment["cycle_id"])
    guide = db.stores["guides"].get(cyc["guide_id"]) if cyc else None
    instrument = db.stores["instruments"].get(cyc["instrument_id"]) if cyc else None

    cards = submitted_scorecards(assessment["cycle_id"], assessment["candidate_id"])

    rubric = guide["rubric_items"] if guide else []
    # per-competency rounded means
    means = {}
    for item in rubric:
        code = item["competency_code"]
        ratings = []
        for sc in cards:
            for r in (sc.get("ratings") or []):
                if r["competency_code"] == code:
                    ratings.append(r["rating"])
        if ratings:
            means[code] = Decimal(str(sum(ratings))) / Decimal(len(ratings))
            means[code] = means[code].quantize(Q4, rounding=ROUND_HALF_UP)

    coverage = sum(
        Decimal(str(item["weight"])) for item in rubric
        if item["competency_code"] in means
    )
    if coverage == 0:
        guide_component = Decimal("0")
    else:
        acc = Decimal("0")
        for item in rubric:
            code = item["competency_code"]
            if code not in means:
                continue
            acc += (Decimal(str(item["weight"])) * means[code]
                    / Decimal(item["scale_max"]))
        guide_component = acc / coverage

    raw = assessment.get("raw_score")
    if raw is None or instrument is None:
        assessment_component = Decimal("0")
    else:
        pf = Decimal(instrument["pass_floor"])
        mx = Decimal(instrument["max_score"])
        assessment_component = (Decimal(str(raw)) - pf) / (mx - pf)
        if assessment_component < 0:
            assessment_component = Decimal("0")
        elif assessment_component > 1:
            assessment_component = Decimal("1")

    composite = Decimal("0.6") * guide_component + Decimal("0.4") * assessment_component
    assessment["composite_score"] = float(composite.quantize(Q4, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Calibration index (PRD §3.6, calculations.interviewer_calibration_index)
# ---------------------------------------------------------------------------

def compute_calibration_index(record):
    """Panel-deviation agreement index for (interviewer, guide)."""
    iv_id = record["interviewer_id"]
    guide = db.stores["guides"].get(record["guide_id"])
    if guide is None:
        return None
    rubric = guide["rubric_items"]
    scale = max(item["scale_max"] for item in rubric) - 1
    if scale <= 0:
        scale = 1

    # interviewer's own submitted scorecards on sessions with guide_id == guide
    own_cards = []
    for sc in db.stores["scorecards"].values():
        if sc["status"] != "SUBMITTED" or sc["interviewer_id"] != iv_id:
            continue
        sess = db.stores["sessions"].get(sc["session_id"])
        if sess is None or sess["guide_id"] != guide["id"]:
            continue
        own_cards.append((sc, sess))

    deviations = []
    own_ratings = []
    all_ratings = []  # own + peers across pairs
    for sc, sess in own_cards:
        # peers: other interviewers' submitted scorecards same (cycle, candidate)
        peer_cards = []
        for pc in db.stores["scorecards"].values():
            if pc["status"] != "SUBMITTED" or pc["interviewer_id"] == iv_id:
                continue
            ps = db.stores["sessions"].get(pc["session_id"])
            if ps is None:
                continue
            if ps["cycle_id"] == sess["cycle_id"] and ps["candidate_id"] == sess["candidate_id"]:
                peer_cards.append(pc)
        for r in (sc.get("ratings") or []):
            code = r["competency_code"]
            peer_ratings = []
            for pc in peer_cards:
                for pr in (pc.get("ratings") or []):
                    if pr["competency_code"] == code:
                        peer_ratings.append(pr["rating"])
            if not peer_ratings:
                continue
            peer_mean = sum(peer_ratings) / len(peer_ratings)
            deviations.append(abs(r["rating"] - peer_mean))
            own_ratings.append(r["rating"])
            all_ratings.append(r["rating"])
            all_ratings.extend(peer_ratings)

    if not deviations:
        return None

    mean_abs_dev = sum(deviations) / len(deviations)
    ratio = min(mean_abs_dev / scale, 1.0)
    base = 1.0 - ratio

    if guide.get("scoring_mode", "RAW") == "LENIENCY_ADJUSTED":
        own_mean = sum(own_ratings) / len(own_ratings)
        cohort_mean = sum(all_ratings) / len(all_ratings)
        leniency = min(abs(own_mean - cohort_mean) / scale, 1.0)
        index = base * (1.0 - 0.5 * leniency)
    else:
        index = base
    return d4(index)


def recompute_calibration_for(candidate_cycle_pairs, extra_interviewer=None):
    """Recompute calibration_index for affected records and apply the lapse
    side effect: CALIBRATED with index < 0.5000 -> LAPSED (PRD §3.6).

    candidate_cycle_pairs: iterable of (cycle_id, candidate_id) that changed.
    extra_interviewer: the author interviewer_id whose record also recomputes.
    """
    affected_interviewers = set()
    if extra_interviewer:
        affected_interviewers.add(extra_interviewer)
    for cycle_id, candidate_id in candidate_cycle_pairs:
        for sc in db.stores["scorecards"].values():
            if sc["status"] != "SUBMITTED":
                continue
            sess = db.stores["sessions"].get(sc["session_id"])
            if sess and sess["cycle_id"] == cycle_id and sess["candidate_id"] == candidate_id:
                affected_interviewers.add(sc["interviewer_id"])

    for iv_id in affected_interviewers:
        for rec in db.stores["calibrations"].values():
            if rec["interviewer_id"] != iv_id:
                continue
            if rec["status"] not in ("TRAINED", "CALIBRATED"):
                continue
            idx = compute_calibration_index(rec)
            if idx != rec.get("calibration_index"):
                rec["calibration_index"] = idx
                bump(rec)
            if rec["status"] == "CALIBRATED" and idx is not None and idx < 0.5:
                rec["status"] = "LAPSED"
                bump(rec)


# ---------------------------------------------------------------------------
# Retention anchoring (PRD §3.9, calculations.retention_expiry)
# ---------------------------------------------------------------------------

def recompute_retention_anchor(assessment):
    cyc = db.stores["cycles"].get(assessment["cycle_id"])
    if cyc is None:
        return
    req = db.stores["requisitions"].get(cyc["requisition_id"])
    days = req["retention_days"] if req else 730
    dec = finalized_decision(assessment["cycle_id"], assessment["candidate_id"])
    if dec is not None:
        anchor = dec["finalized_at"]
    elif cyc["posture"] == "CLOSED" and cyc.get("closed_at") is not None:
        anchor = cyc["closed_at"]
    else:
        assessment["retention_expires_at"] = None
        return
    assessment["retention_expires_at"] = anchor + timedelta(days=days)


# ---------------------------------------------------------------------------
# Cancellation cascade shared by manual cancel, withdraw, cycle close
# ---------------------------------------------------------------------------

CANCELLABLE_ADMIN = {"INVITED", "SCHEDULED", "ACCOMMODATION_HOLD", "IN_PROGRESS"}


def cancel_assessment(a, reason, count_decrement=True):
    """Cancel one assessment + its sessions + pending accommodations."""
    if a["admin_status"] not in CANCELLABLE_ADMIN:
        return
    a["admin_status"] = "CANCELLED"
    if a["feedback_status"] == "NOT_SENT":
        a["feedback_status"] = "NOT_APPLICABLE"
    bump(a)
    cyc = db.stores["cycles"].get(a["cycle_id"])
    if cyc is not None and count_decrement:
        cyc["active_candidate_count"] = max(0, cyc["active_candidate_count"] - 1)
    # cancel candidate's SCHEDULED sessions in this cycle
    for s in db.stores["sessions"].values():
        if (s["cycle_id"] == a["cycle_id"] and s["candidate_id"] == a["candidate_id"]
                and s["status"] == "SCHEDULED"):
            s["status"] = "CANCELLED"
            s["cancellation_reason"] = reason
            bump(s)
            recompute_interviewer_minutes(s["interviewer_id"])
            iv = db.stores["interviewers"].get(s["interviewer_id"])
            if iv is not None:
                bump(iv)
    # withdraw pending accommodations
    for ar in db.stores["accommodation_requests"].values():
        if ar["candidate_assessment_id"] == a["id"] and ar["status"] == "PENDING":
            ar["status"] = "WITHDRAWN"
            bump(ar)


# ---------------------------------------------------------------------------
# Time-materialized automatic transitions (PRD §2.5)
# ---------------------------------------------------------------------------

def materialize_time_transitions(now):
    instruments_expired = 0
    for inst in db.stores["instruments"].values():
        if (inst["validation_status"] == "VALIDATED"
                and inst.get("validity_expires_at") is not None
                and now > inst["validity_expires_at"]):
            inst["validation_status"] = "EXPIRED"
            bump(inst)
            instruments_expired += 1
    calibrations_lapsed = 0
    for rec in db.stores["calibrations"].values():
        if (rec["status"] == "CALIBRATED" and rec.get("certified_at") is not None
                and now > rec["certified_at"] + timedelta(days=365)):
            rec["status"] = "LAPSED"
            bump(rec)
            calibrations_lapsed += 1
    return instruments_expired, calibrations_lapsed
