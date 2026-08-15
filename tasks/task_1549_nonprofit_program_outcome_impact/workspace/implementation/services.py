"""Cross-entity business logic: lazy expiry, consent derivation, cascades,
cycle aggregates, data-quality scores, attainment, impact index.

All computed quantities are produced at exactly 2 decimal places, round-half-up
(PRD 2.7); each stated rounding step rounds before the next step consumes it.
"""
from decimal import Decimal

from db import db, parse_dt, now_dt
from util import dec, round2, clamp, touch

ATTAINMENT_CAP = Decimal("150")
ATTAINMENT_FLOOR = Decimal("0")
BAND_GREEN_MIN = Decimal("90.00")
BAND_YELLOW_MIN = Decimal("70.00")
W_COMPLETENESS = Decimal("0.5")
W_VALIDATED = Decimal("0.3")
W_CONSENT = Decimal("0.2")
FINDING_PENALTY = Decimal("4.00")
DQ_CAP = Decimal("100")
DQ_GATE = Decimal("80.00")
ZERO2 = Decimal("0.00")


# ------------------------------------------------------------------ lookups
def program_of_cycle(cycle):
    return db.programs.get(cycle["program_id"])


def cycle_of_participant(participant):
    return db.cycles.get(participant["program_cycle_id"])


def program_of_participant(participant):
    cycle = cycle_of_participant(participant)
    return db.programs.get(cycle["program_id"]) if cycle else None


def cycle_participants(cycle_id):
    return [p for p in db.participants.values() if p["program_cycle_id"] == cycle_id]


def cycle_observations(cycle_id):
    pids = {p["id"] for p in cycle_participants(cycle_id)}
    return [o for o in db.observations.values() if o["participant_id"] in pids]


def cycle_audits(cycle_id):
    return [a for a in db.audits.values() if a["program_cycle_id"] == cycle_id]


def instrument_line_current_version(instrument):
    """The current version of an instrument code line: the max instrument_version
    among revisions of the same (program_id, code) that are PUBLISHED or RETIRED
    (i.e., revisions that have been current). DRAFT successors do not advance
    the line until published."""
    versions = [
        i["instrument_version"]
        for i in db.instruments.values()
        if i["program_id"] == instrument["program_id"]
        and i["code"] == instrument["code"]
        and i["status"] in ("PUBLISHED", "RETIRED")
    ]
    return max(versions, default=instrument["instrument_version"])


# ------------------------------------------------------------- lazy expiry
def refresh_certification(cert):
    """Lazy EXPIRED evaluation for a certification (PRD 2.5)."""
    if cert["status"] == "CERTIFIED" and parse_dt(cert["expires_at"]) <= now_dt():
        cert["status"] = "EXPIRED"
        touch(db.certifications, cert)


def refresh_participant_consent(participant):
    """Apply lazy consent expiry and recompute the derived consent_status.

    CURRENT: latest GRANTED consent unexpired and form_version equals the
    program's current consent form version. EXPIRED: a consent was granted but
    has since time- or form-expired. NONE: otherwise (never granted, superseded
    without replacement, or revoked).
    """
    program = program_of_participant(participant)
    now = now_dt()
    consents = [c for c in db.consents.values() if c["participant_id"] == participant["id"]]
    for c in consents:
        if c["status"] == "GRANTED" and parse_dt(c["expires_at"]) <= now:
            c["status"] = "EXPIRED"
            touch(db.consents, c)
    granted = [c for c in consents if c["status"] == "GRANTED"]
    current_version = program["current_consent_form_version"] if program else None
    if granted:
        latest = max(granted, key=lambda c: c["_seq"])
        if (
            latest["form_version"] == current_version
            and parse_dt(latest["expires_at"]) > now
        ):
            new_status = "CURRENT"
        else:
            new_status = "EXPIRED"
    else:
        time_expired = any(c["status"] == "EXPIRED" for c in consents)
        form_expired = any(
            c["status"] == "SUPERSEDED" and c["form_version"] != current_version
            for c in consents
        )
        new_status = "EXPIRED" if (time_expired or form_expired) else "NONE"
    if participant["consent_status"] != new_status:
        participant["consent_status"] = new_status
        touch(db.participants, participant)


# --------------------------------------------------------- cycle aggregates
def compute_completeness(cycle, participants=None, observations=None):
    """data_completeness_pct (SCAFFOLD 1.3); null when either set is empty."""
    if participants is None:
        participants = cycle_participants(cycle["id"])
    if observations is None:
        observations = cycle_observations(cycle["id"])
    eligible = [p for p in participants if p["status"] in ("ACTIVE", "COMPLETED", "EXITED")]
    pin = cycle["pinned_logic_model_id"]
    active_inds = [
        i
        for i in db.indicators.values()
        if pin and i["logic_model_id"] == pin and i["status"] == "ACTIVE"
    ]
    if not eligible or not active_inds:
        return None
    ind_ids = {i["id"] for i in active_inds}
    covered = {p["id"]: set() for p in eligible}
    for o in observations:
        if (
            o["participant_id"] in covered
            and o["review_status"] in ("PENDING", "VALIDATED")
            and o["indicator_id"] in ind_ids
        ):
            covered[o["participant_id"]].add(o["indicator_id"])
    total_cov = sum(len(s) for s in covered.values())
    return round2(Decimal(100) * Decimal(total_cov) / (len(eligible) * len(active_inds)))


def recompute_cycle_aggregates(cycle):
    """Refresh counts + completeness; bumps the cycle only on actual change."""
    participants = cycle_participants(cycle["id"])
    observations = cycle_observations(cycle["id"])
    new_vals = {
        "active_participant_count": sum(1 for p in participants if p["status"] == "ACTIVE"),
        "total_observation_count": sum(
            1 for o in observations if o["review_status"] != "EXCLUDED"
        ),
        "validated_observation_count": sum(
            1 for o in observations if o["review_status"] == "VALIDATED"
        ),
        "data_completeness_pct": compute_completeness(cycle, participants, observations),
    }
    changed = False
    for k, v in new_vals.items():
        if cycle[k] != v:
            cycle[k] = v
            changed = True
    if changed:
        touch(db.cycles, cycle)


# ------------------------------------------------------------------ dq score
def compute_dq(cycle, variant="STANDARD"):
    """Data-quality score (SCAFFOLD 1.3 dq_score), STANDARD or STRICT variant."""
    participants = cycle_participants(cycle["id"])
    for p in participants:
        refresh_participant_consent(p)
    observations = cycle_observations(cycle["id"])
    recompute_cycle_aggregates(cycle)

    C = cycle["data_completeness_pct"]
    C = C if C is not None else ZERO2

    if variant == "STRICT":
        denom = sum(
            1 for o in observations if o["review_status"] != "EXCLUDED" and not o["is_late"]
        )
        numer = sum(
            1
            for o in observations
            if o["review_status"] == "VALIDATED" and not o["is_late"]
        )
    else:
        denom = sum(1 for o in observations if o["review_status"] != "EXCLUDED")
        numer = sum(1 for o in observations if o["review_status"] == "VALIDATED")
    V = round2(Decimal(100) * Decimal(numer) / Decimal(denom)) if denom else ZERO2

    non_withdrawn = [p for p in participants if p["status"] != "WITHDRAWN"]
    current = sum(1 for p in non_withdrawn if p["consent_status"] == "CURRENT")
    K = (
        round2(Decimal(100) * Decimal(current) / Decimal(len(non_withdrawn)))
        if non_withdrawn
        else ZERO2
    )

    audit_ids = {a["id"] for a in cycle_audits(cycle["id"])}
    F = sum(
        1
        for f in db.findings.values()
        if f["audit_id"] in audit_ids and f["status"] == "OPEN"
    )

    raw = W_COMPLETENESS * C + W_VALIDATED * V + W_CONSENT * K - FINDING_PENALTY * F
    return round2(clamp(raw, Decimal(0), DQ_CAP))


def target_audit(cycle):
    """The OPEN audit, else the most recent audit, else None."""
    audits = cycle_audits(cycle["id"])
    if not audits:
        return None
    open_ones = [a for a in audits if a["status"] == "OPEN"]
    if open_ones:
        return max(open_ones, key=lambda a: a["_seq"])
    return max(audits, key=lambda a: a["_seq"])


def refresh_cycle_dq(cycle, audit=None):
    """Recompute the target audit's dq fields and the cycle's latest_dq_score."""
    if audit is None:
        audit = target_audit(cycle)
    if audit is None:
        return
    ofc = sum(
        1
        for f in db.findings.values()
        if f["audit_id"] == audit["id"] and f["status"] == "OPEN"
    )
    dq = compute_dq(cycle, "STANDARD")
    if audit["open_finding_count"] != ofc:
        audit["open_finding_count"] = ofc
        touch(db.audits, audit)
    if audit["dq_score"] != dq:
        audit["dq_score"] = dq
        touch(db.audits, audit)
    if cycle["latest_dq_score"] != dq:
        cycle["latest_dq_score"] = dq
        touch(db.cycles, cycle)


# ---------------------------------------------------------------- attainment
def _attainment_input_set(indicator, cycle, variant):
    participants = {p["id"]: p for p in cycle_participants(cycle["id"])}
    out = []
    for o in db.observations.values():
        if o["indicator_id"] != indicator["id"]:
            continue
        p = participants.get(o["participant_id"])
        if p is None:
            continue
        if p["status"] == "WITHDRAWN":
            continue
        rs = o["review_status"]
        if variant == "PROVISIONAL":
            if rs not in ("PENDING", "VALIDATED"):
                continue
        else:  # FINAL
            if rs != "VALIDATED":
                continue
        out.append(o)
    return out


def indicator_attainment(indicator, cycle, variant="FINAL"):
    """Returns (aggregated_value, attainment_pct, band, observation_count)."""
    obs = _attainment_input_set(indicator, cycle, variant)
    count = len(obs)
    if count == 0:
        return None, None, None, 0
    # Step 1: aggregated value, rounded half-up to 2dp before anything else.
    agg = round2(sum(dec(o["value"]) for o in obs) / Decimal(count))
    baseline = dec(indicator["baseline_value"])
    target = dec(indicator["target_value"])
    direction = indicator["direction"]
    # Step 2: zero-guard first, then direction branch.
    if target == baseline:
        if (direction == "HIGHER_IS_BETTER" and agg >= target) or (
            direction == "LOWER_IS_BETTER" and agg <= target
        ):
            att = Decimal("100.00")
        else:
            att = ZERO2
    elif direction == "HIGHER_IS_BETTER":
        att = Decimal(100) * (agg - baseline) / (target - baseline)
    else:
        att = Decimal(100) * (baseline - agg) / (baseline - target)
    # Step 3: clamp, then round half-up to 2dp.
    att = clamp(att, ATTAINMENT_FLOOR, ATTAINMENT_CAP)
    att = round2(att)
    if att >= BAND_GREEN_MIN:
        band = "GREEN"
    elif att >= BAND_YELLOW_MIN:
        band = "YELLOW"
    else:
        band = "RED"
    return agg, att, band, count


def final_validated_count(indicator, cycle):
    return len(_attainment_input_set(indicator, cycle, "FINAL"))


def overall_impact_index(cycle):
    """Overall impact index (SCAFFOLD 1.3); per-term rounding is pinned."""
    pin = cycle["pinned_logic_model_id"]
    eligible = []
    if pin:
        for i in db.indicators.values():
            if i["logic_model_id"] == pin and i["status"] == "ACTIVE":
                if final_validated_count(i, cycle) > 0:
                    eligible.append(i)
    if not eligible:
        return None
    weight_sum = sum(dec(i["weight"]) for i in eligible)
    if weight_sum == 0:
        return None
    numerator = Decimal(0)
    for i in eligible:
        _, att, _, _ = indicator_attainment(i, cycle, "FINAL")
        numerator += round2(att * dec(i["weight"]))
    return round2(numerator / weight_sum)


# ----------------------------------------------------------------- cascades
def withdraw_participant(participant):
    """Consent-revocation cascade (PRD 3.5): participant hop, observation hop,
    cycle hop. Only fires from ENROLLED, ACTIVE, or EXITED."""
    if participant["status"] not in ("ENROLLED", "ACTIVE", "EXITED"):
        return False
    participant["status"] = "WITHDRAWN"
    touch(db.participants, participant)
    for o in db.observations.values():
        if o["participant_id"] == participant["id"] and o["review_status"] in (
            "PENDING",
            "VALIDATED",
            "FLAGGED",
        ):
            o["review_status"] = "EXCLUDED"
            o["exclusion_reason"] = "CONSENT_REVOKED"
            touch(db.observations, o)
    cycle = cycle_of_participant(participant)
    if cycle is not None:
        recompute_cycle_aggregates(cycle)
        refresh_cycle_dq(cycle)
    return True


def recompute_participant_consent_and_counts(participant):
    refresh_participant_consent(participant)
    cycle = cycle_of_participant(participant)
    if cycle is not None:
        recompute_cycle_aggregates(cycle)
