"""Business engine: derived figures, the two counting engines, condition
evaluation, remedy pricing, the two pinned rounding orders, and every cascade.

Every rule here traces to PRD 2.5-2.10 and 3.1-3.9 / SCAFFOLD calculations.
"""
from db import store
from util import (D, add_days, as_date, cents, days_between, fmt_date, fmt_dt,
                  parse_date, parse_dt, q2, round_half_up)

# ------------------------------------------------------------------ constants
MIN_REDUCTION_PCT = D("5.0")
ANCHOR_DARK_BONUS_PCT = D("10.0")
SUBSTITUTE_RENT_SHORTFALL_PCT = D("20.0")
TIER_1_MAX_SHORTFALL_PCT = D("5.0")
TIER_1_MULTIPLIER = D("1.0")
TIER_2_MAX_SHORTFALL_PCT = D("15.0")
TIER_2_MULTIPLIER = D("1.5")
TIER_3_MULTIPLIER = D("2.0")

DAYS_PER_ACCRUAL_MONTH = D(30)

BASE_ESTOPPEL_FEE_CENTS = 25000
PER_DISCLOSURE_FEE_CENTS = 5000
BREACH_DISCLOSURE_FEE_CENTS = 15000
TIER_A_MAX_SUBTOTAL_CENTS = 40000
TIER_A_SURCHARGE_PCT = D("10.0")
TIER_B_MAX_SUBTOTAL_CENTS = 75000
TIER_B_SURCHARGE_PCT = D("15.0")
TIER_C_SURCHARGE_PCT = D("20.0")

FREEZE_BREACHED_CONDITION_COUNT = 2
FREEZE_OCCUPANCY_PCT = D("50.0")
WATCH_OCCUPANCY_PCT = D("70.0")

SCOPE_SEVERITY = {"CENTER_WIDE": 3, "RADIUS_INCLUSIVE": 2, "PAD_EXCLUDED": 1}

TERMINATION_NOTICE_DAYS = 90

OPEN_POPULATION = ("EXECUTED", "OPEN", "DARK")
# The occupancy rungs of the posture ladder only bite once the center has a
# store that has actually opened.  A center holding nothing but EXECUTED
# leases has an occupancy of 0.00 by construction (PRD 3.2: "an EXECUTED
# lease contributes nothing to the numerator, so the center's occupancy
# figures do not move"), and freezing on that figure would make lease
# execution self-blocking after the very first lease.
ASSESSABLE_STATUSES = ("OPEN", "DARK")
LIVE_NOTICE_STATUSES = ("ISSUED", "DISPUTED", "ESCALATED")
LIVE_ELECTION_STATUSES = ("ELECTED", "REDUCTION_ACTIVE", "TERMINATION_SCHEDULED")


# ------------------------------------------------------------------- clock

def now():
    return store.clock


def today():
    return store.clock.date()


def stamp():
    return fmt_dt(store.clock)


# ------------------------------------------------------- collection helpers

def _ordered(values):
    return sorted(values, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def leases_of_center(center_id):
    return _ordered([l for l in store.leases.values() if l["center_id"] == center_id])


def conditions_of_lease(lease_id):
    return _ordered([c for c in store.conditions.values() if c["lease_id"] == lease_id])


def conditions_of_center(center_id):
    ids = set(l["id"] for l in store.leases.values() if l["center_id"] == center_id)
    return _ordered([c for c in store.conditions.values() if c["lease_id"] in ids])


def clauses_of_lease(lease_id):
    return _ordered([c for c in store.clauses.values() if c["lease_id"] == lease_id])


def clauses_of_center(center_id):
    ids = set(l["id"] for l in store.leases.values() if l["center_id"] == center_id)
    return _ordered([c for c in store.clauses.values() if c["lease_id"] in ids])


def restrictions_of_lease(lease_id):
    return _ordered([r for r in store.restrictions.values() if r["lease_id"] == lease_id])


def notices_of_lease(lease_id):
    return _ordered([n for n in store.notices.values()
                     if n["violating_lease_id"] == lease_id])


def notices_of_center(center_id):
    ids = set(l["id"] for l in store.leases.values() if l["center_id"] == center_id)
    return _ordered([n for n in store.notices.values()
                     if n["violating_lease_id"] in ids])


def elections_of_lease(lease_id):
    return _ordered([e for e in store.elections.values() if e["lease_id"] == lease_id])


def certificates_of_lease(lease_id):
    return _ordered([c for c in store.certificates.values() if c["lease_id"] == lease_id])


def requirements_of_condition(condition_id):
    return _ordered([r for r in store.anchor_requirements.values()
                     if r["condition_id"] == condition_id])


def disputes_of_notice(notice_id):
    return _ordered([d for d in store.disputes.values() if d["notice_id"] == notice_id])


def measurements_of_center(center_id):
    return _ordered([m for m in store.measurements.values()
                     if m["center_id"] == center_id])


def plans_of_center(center_id):
    return _ordered([p for p in store.plans.values() if p["center_id"] == center_id])


def center_of_lease(lease):
    return store.centers.get(lease["center_id"])


# --------------------------------------------------------- version handling

def touch(record):
    """PRD 2.4: version increments on every mutation, including derived-only ones."""
    record["updated_at"] = stamp()
    record["version"] = record.get("version", 0) + 1


def cascade_certificate_staleness(lease):
    """Any lease version bump past pinned_lease_version staleness (PRD 3.8)."""
    for cert in certificates_of_lease(lease["id"]):
        if cert["status"] in ("REQUESTED", "TENANT_SIGNED") \
                and cert["pinned_lease_version"] < lease["version"]:
            cert["status"] = "STALE"
            cert["lender_conditions_met"] = False
            touch(cert)


def touch_lease(lease):
    touch(lease)
    cascade_certificate_staleness(lease)


# --------------------------------------------------- the two counting engines

def counted_open(lease, variant, at_instant):
    """The ONLY inclusion predicate (SCAFFOLD occupancy_measurement_snapshot)."""
    tenant = store.tenants.get(lease["tenant_id"]) or {}
    if variant == "SNAPSHOT_STRICT":
        return lease["premises_status"] == "OPEN" and tenant.get("status") == "ACTIVE"
    # TRAILING_GRACE
    if tenant.get("status") == "BANKRUPT":
        return False
    if lease["premises_status"] == "OPEN":
        return True
    if lease["premises_status"] == "DARK" and lease.get("dark_since"):
        center = center_of_lease(lease) or {}
        return days_between(lease["dark_since"], at_instant) \
            < center.get("occupancy_grace_days", 0)
    return False


def snapshot(center, variant, at_instant, total_gla_sqft=None):
    population = [l for l in leases_of_center(center["id"])
                  if l["premises_status"] in OPEN_POPULATION]
    counted = [l for l in population if counted_open(l, variant, at_instant)]
    counted_gla = sum(l["gla_sqft"] for l in counted)
    total = total_gla_sqft if total_gla_sqft is not None else center["total_gla_sqft"]
    if total and total > 0:
        pct = round_half_up(D(counted_gla) / D(total) * 100, 2)
    else:
        pct = D("0.00")
    return {
        "counted_gla_sqft": counted_gla,
        "gla_occupancy_pct": pct,
        "open_store_count": len([l for l in counted if not l["is_anchor"]]),
        "open_anchor_count": len([l for l in counted if l["is_anchor"]]),
        "counted_lease_count": len(counted),
        "excluded_lease_count": len(population) - len(counted),
        "total_gla_sqft": total,
    }


# ----------------------------------------------------- center derived fields

def protected_exclusive_count(center_id):
    total = 0
    for clause in clauses_of_center(center_id):
        lease = store.leases.get(clause["lease_id"])
        if clause["status"] == "ACTIVE" and lease \
                and lease["premises_status"] != "TERMINATED":
            total += 1
    return total


def open_violation_count(center_id):
    return len([n for n in notices_of_center(center_id)
                if n["status"] in LIVE_NOTICE_STATUSES])


def recompute_center_derived(center):
    figures = snapshot(center, "SNAPSHOT_STRICT", now())
    center["occupied_gla_sqft"] = figures["counted_gla_sqft"]
    center["open_occupancy_pct"] = figures["gla_occupancy_pct"]
    center["operating_store_count"] = figures["open_store_count"]
    center["open_anchor_count"] = figures["open_anchor_count"]
    center["protected_exclusive_count"] = protected_exclusive_count(center["id"])
    center["open_violation_count"] = open_violation_count(center["id"])
    center["aggregate_effective_rent_cents"] = sum(
        l["effective_rent_monthly_cents"] for l in leases_of_center(center["id"])
        if l["premises_status"] in ("OPEN", "DARK"))


def breached_condition_count(center_id):
    total = 0
    for cond in conditions_of_center(center_id):
        lease = store.leases.get(cond["lease_id"])
        if cond["status"] == "BREACHED" and lease \
                and lease["premises_status"] != "TERMINATED":
            total += 1
    return total


def derive_posture(center):
    breached = breached_condition_count(center["id"])
    assessable = any(l["premises_status"] in ASSESSABLE_STATUSES
                     for l in leases_of_center(center["id"]))
    pct = D(center["open_occupancy_pct"])
    if breached >= FREEZE_BREACHED_CONDITION_COUNT \
            or (assessable and pct < FREEZE_OCCUPANCY_PCT):
        posture = "FROZEN"
    elif breached >= 1:
        posture = "BREACH"
    elif center["open_violation_count"] >= 1 \
            or (assessable and pct < WATCH_OCCUPANCY_PCT):
        posture = "WATCH"
    else:
        posture = "COMPLIANT"
    center["compliance_posture"] = posture


def derive_redevelopment_status(center):
    plans = plans_of_center(center["id"])
    if not plans:
        center["redevelopment_status"] = "NONE"
    elif any(p["status"] == "RECORDED" for p in plans):
        center["redevelopment_status"] = "RECORDED"
    elif any(p["status"] in ("PLANNED", "CONSENT_PENDING") for p in plans):
        center["redevelopment_status"] = "PLANNED"
    else:
        center["redevelopment_status"] = "NONE"


def finalize_center(center):
    recompute_center_derived(center)
    derive_redevelopment_status(center)
    derive_posture(center)


def bump_center(center):
    finalize_center(center)
    touch(center)


# ------------------------------------------------------------ lease derived

def recompute_use_compliance(lease):
    notices = notices_of_lease(lease["id"])
    if any(n["status"] == "ESCALATED" for n in notices):
        value = "IN_VIOLATION"
    elif any(n["status"] in ("ISSUED", "DISPUTED") for n in notices):
        value = "UNDER_NOTICE"
    else:
        value = "CLEAR"
    if lease["use_compliance_status"] != value:
        lease["use_compliance_status"] = value
        return True
    return False


def recompute_effective_rent(lease):
    """SUM-THEN-ROUND (PRD 2.7 / effective_rent_recompute)."""
    day = today()
    total_pct = D(0)
    for election in elections_of_lease(lease["id"]):
        if election["status"] != "REDUCTION_ACTIVE":
            continue
        start = as_date(election["window_from_date"])
        end = as_date(election["window_through_date"])
        if start <= day < end:
            total_pct += D(election["reduction_pct"])
    value = cents(D(lease["base_rent_monthly_cents"]) * (100 - total_pct) / 100)
    changed = value != lease["effective_rent_monthly_cents"]
    lease["effective_rent_monthly_cents"] = value
    return changed


def _accrual(election, lease):
    end_date = min(today(), as_date(election["window_through_date"]))
    frozen = election.get("_accrual_frozen_date")
    if frozen is not None:
        end_date = min(end_date, frozen)
    days = max(0, days_between(election["window_from_date"], end_date))
    months = round_half_up(D(days) / DAYS_PER_ACCRUAL_MONTH, 4)
    return cents(D(lease["base_rent_monthly_cents"])
                 * D(election["reduction_pct"]) / 100 * months)


def recompute_abatement(lease):
    """ROUND-THEN-SUM (PRD 2.7 / abatement_ledger_rounding)."""
    total = 0
    changed = False
    for election in elections_of_lease(lease["id"]):
        if election["status"] in ("REDUCTION_ACTIVE", "CONSUMMATED"):
            amount = _accrual(election, lease)
        else:
            amount = 0
        if election["abated_to_date_cents"] != amount:
            election["abated_to_date_cents"] = amount
            changed = True
        total += amount if election["status"] in ("REDUCTION_ACTIVE", "CONSUMMATED") else 0
    if lease["total_abated_cents"] != total:
        lease["total_abated_cents"] = total
        changed = True
    return changed


def recompute_lease_money(lease):
    a = recompute_abatement(lease)
    b = recompute_effective_rent(lease)
    return a or b


# -------------------------------------------------------- remedy transitions

def has_breached_condition(lease):
    return any(c["status"] == "BREACHED" for c in conditions_of_lease(lease["id"]))


def has_escalated_source(lease):
    """An ESCALATED notice citing a clause of this lease, or a radius notice
    against this lease (PRD 3.6 fan-out)."""
    for notice in store.notices.values():
        if notice["status"] != "ESCALATED":
            continue
        if notice["notice_kind"] == "EXCLUSIVE_USE" and notice.get("clause_id"):
            clause = store.clauses.get(notice["clause_id"])
            if clause and clause["lease_id"] == lease["id"]:
                return True
        elif notice["notice_kind"] == "RADIUS" \
                and notice["violating_lease_id"] == lease["id"]:
            return True
    return False


def live_elections(lease):
    return [e for e in elections_of_lease(lease["id"])
            if e["status"] in LIVE_ELECTION_STATUSES]


def grant_eligible(lease, at_instant=None):
    """NONE -> ELIGIBLE (PRD 3.5 remedy dimension)."""
    if lease["remedy_status"] != "NONE":
        return False
    if lease["premises_status"] not in OPEN_POPULATION:
        return False
    if not (has_breached_condition(lease) or has_escalated_source(lease)):
        return False
    lease["remedy_status"] = "ELIGIBLE"
    lease["remedy_eligible_at"] = fmt_dt(at_instant or now())
    touch_lease(lease)
    return True


def release_remedy(lease):
    """ELIGIBLE/REMEDY_ACTIVE -> NONE when the preconditions are met."""
    if lease["remedy_status"] == "ELIGIBLE":
        if not has_breached_condition(lease) and not has_escalated_source(lease) \
                and not live_elections(lease):
            lease["remedy_status"] = "NONE"
            lease["remedy_eligible_at"] = None
            touch_lease(lease)
            return True
    elif lease["remedy_status"] == "REMEDY_ACTIVE":
        conditions = conditions_of_lease(lease["id"])
        settled = all(c["status"] in ("SATISFIED", "CURED", "WAIVED") for c in conditions)
        if settled and not live_elections(lease):
            lease["remedy_status"] = "NONE"
            lease["remedy_eligible_at"] = None
            lease["effective_rent_monthly_cents"] = lease["base_rent_monthly_cents"]
            recompute_abatement(lease)
            touch_lease(lease)
            return True
    return False


# ------------------------------------------------------- condition evaluation

def named_anchor_ids(condition_id):
    return set(r["anchor_lease_id"] for r in requirements_of_condition(condition_id))


def named_anchor_unsatisfied(cond, variant, at_instant):
    """True when the named-anchor test FAILS."""
    lease = store.leases.get(cond["lease_id"])
    center_id = lease["center_id"] if lease else None
    named = named_anchor_ids(cond["id"])
    for requirement in requirements_of_condition(cond["id"]):
        anchor = store.leases.get(requirement["anchor_lease_id"])
        if anchor is not None and counted_open(anchor, variant, at_instant):
            continue
        if not requirement["substitution_allowed"]:
            return True
        subs = [l for l in store.leases.values()
                if l["center_id"] == center_id
                and l["parcel_kind"] == "ANCHOR_BOX"
                and l["id"] != requirement["anchor_lease_id"]
                and l["id"] not in named
                and counted_open(l, variant, at_instant)
                and l["gla_sqft"] >= requirement["min_substitute_gla_sqft"]]
        if not subs:
            return True
    return False


def condition_figures(source, center, measurement=None):
    if source == "CERTIFIED_MEASUREMENT" and measurement is not None:
        return (D(measurement["gla_occupancy_pct"]), measurement["open_store_count"],
                measurement["open_anchor_count"], measurement["variant"],
                parse_dt(measurement["measured_at"]))
    return (D(center["open_occupancy_pct"]), center["operating_store_count"],
            center["open_anchor_count"], "SNAPSHOT_STRICT", now())


def condition_satisfied(cond, pct, stores, anchors, variant, at_instant):
    if cond["measurement_basis"] == "GLA_PCT":
        basis_ok = D(pct) >= D(cond["required_occupancy_pct"])
    else:
        basis_ok = stores >= cond["required_open_store_count"]
    anchor_count_ok = anchors >= cond["required_anchor_count"]
    named_ok = not named_anchor_unsatisfied(cond, variant, at_instant)
    return bool(basis_ok and anchor_count_ok and named_ok)


def evaluation_gated_out(cond):
    lease = store.leases.get(cond["lease_id"])
    if lease is None:
        return True
    if cond["status"] == "WAIVED":
        return True
    if lease["premises_status"] == "TERMINATED":
        return True
    if cond["condition_kind"] == "ONGOING" \
            and lease["premises_status"] not in ("OPEN", "DARK"):
        return True
    if cond["condition_kind"] == "OPENING" and lease["premises_status"] != "EXECUTED":
        return True
    return False


def evaluate_condition(cond, source, measurement=None):
    """Runs one evaluation and applies the condition + lease side effects.

    Returns one of None (gated out), 'satisfied', 'breached', 'cured',
    'still_breached'.
    """
    if evaluation_gated_out(cond):
        return None
    lease = store.leases[cond["lease_id"]]
    center = center_of_lease(lease)
    pct, stores, anchors, variant, at_instant = condition_figures(
        source, center, measurement)
    satisfied = condition_satisfied(cond, pct, stores, anchors, variant, at_instant)
    certified = source == "CERTIFIED_MEASUREMENT" and measurement is not None

    if satisfied:
        if cond["status"] == "BREACHED":
            cond["status"] = "CURED"
            cond["breach_detected_at"] = None
            cond["consecutive_breach_days"] = 0
            if certified:
                cond["last_evaluated_measurement_id"] = measurement["id"]
            touch(cond)
            release_remedy(lease)
            return "cured"
        if certified and cond["last_evaluated_measurement_id"] != measurement["id"]:
            cond["last_evaluated_measurement_id"] = measurement["id"]
            touch(cond)
        return "satisfied"

    if cond["status"] in ("SATISFIED", "CURED"):
        cond["status"] = "BREACHED"
        cond["breach_detected_at"] = fmt_dt(at_instant)
        cond["consecutive_breach_days"] = 0
        if certified:
            cond["last_evaluated_measurement_id"] = measurement["id"]
        touch(cond)
        if cond["grace_period_days"] == 0:
            grant_eligible(lease, at_instant)
        return "breached"

    # already BREACHED and still failing: self-transition
    cond["consecutive_breach_days"] = max(
        0, days_between(cond["breach_detected_at"], at_instant))
    if certified:
        cond["last_evaluated_measurement_id"] = measurement["id"]
    touch(cond)
    if cond["consecutive_breach_days"] >= cond["grace_period_days"]:
        grant_eligible(lease, at_instant)
    return "still_breached"


def evaluate_center_conditions(center, source, measurement=None, kinds=None,
                              skip_lease_ids=()):
    """Re-evaluate the conditions of a center; returns the event tally."""
    tally = {"cured": 0, "breached": 0, "still_breached": 0, "satisfied": 0}
    for cond in conditions_of_center(center["id"]):
        if kinds is not None and cond["condition_kind"] not in kinds:
            continue
        if cond["lease_id"] in skip_lease_ids:
            continue
        event = evaluate_condition(cond, source, measurement)
        if event:
            tally[event] += 1
    return tally


def latest_certified_measurement(center_id):
    certified = [m for m in measurements_of_center(center_id)
                 if m["status"] == "CERTIFIED"]
    if not certified:
        return None
    certified.sort(key=lambda m: (m["measured_at"], m["created_at"]), reverse=True)
    return certified[0]


def controlling_figures_for_condition(cond, center):
    """PRD 3.5: the measurement named by last_evaluated_measurement_id when set,
    otherwise the center's live strict figures."""
    measurement_id = cond.get("last_evaluated_measurement_id")
    measurement = store.measurements.get(measurement_id) if measurement_id else None
    if measurement is not None:
        return condition_figures("CERTIFIED_MEASUREMENT", center, measurement)
    return condition_figures("LIVE_STRICT", center)


# ---------------------------------------------------------------- screening

def screen_use(candidate):
    center_id = candidate["center_id"]
    screen_date = today()
    eligible = []
    for clause in clauses_of_center(center_id):
        benefited = store.leases.get(clause["lease_id"])
        if benefited is None or benefited["id"] == candidate["id"]:
            continue
        if clause["status"] != "ACTIVE":
            continue
        if benefited["premises_status"] not in OPEN_POPULATION:
            continue
        if not (as_date(clause["effective_from_date"]) <= screen_date
                <= as_date(clause["effective_through_date"])):
            continue
        if candidate["primary_use_code"] not in clause["protected_use_codes"]:
            continue
        scope = clause["exclusivity_scope"]
        if scope == "PAD_EXCLUDED" and candidate["parcel_kind"] == "PAD":
            continue
        eligible.append(clause)

    def suppressed(clause):
        return (candidate["primary_use_code"] in candidate["incidental_use_codes"]
                and D(candidate["projected_incidental_sales_pct"])
                <= D(clause["incidental_sales_pct_cap"])
                and candidate["gla_sqft"] <= clause["gla_carve_out_sqft"])

    conflicts = [c for c in eligible if not suppressed(c)]
    carve_out_applied = len(eligible) > 0 and len(conflicts) == 0
    if not conflicts:
        decision, controlling_id = "CLEAR", None
    else:
        ranked = sorted(conflicts, key=lambda c: (
            -SCOPE_SEVERITY.get(c["exclusivity_scope"], 0),
            c["gla_carve_out_sqft"],
            c["created_at"],
            c.get("_seq", 0)))
        decision, controlling_id = "CONFLICT", ranked[0]["id"]
    return {
        "decision": decision,
        "controlling_clause_id": controlling_id,
        "conflicting_clause_count": len(conflicts),
        "carve_out_applied": carve_out_applied,
        "screened_use_code": candidate["primary_use_code"],
        "eligible_clause_count": len(eligible),
    }


# --------------------------------------------------------- remedy pricing

def price_election(lease, cond, notice_sourced):
    center = center_of_lease(lease)
    anchor_dark = False
    if notice_sourced or cond is None:
        shortfall = q2(SUBSTITUTE_RENT_SHORTFALL_PCT)
        max_reduction = D("50")
    else:
        pct, stores, anchors, variant, at_instant = \
            controlling_figures_for_condition(cond, center)
        if cond["measurement_basis"] == "GLA_PCT":
            raw = D(cond["required_occupancy_pct"]) - D(pct)
            shortfall = q2(raw if raw > 0 else D(0))
        else:
            required = D(cond["required_open_store_count"])
            raw = (required - D(stores)) / required * 100
            shortfall = q2(raw if raw > 0 else D(0))
        anchor_dark = named_anchor_unsatisfied(cond, variant, at_instant)
        max_reduction = D(cond["max_reduction_pct"])

    if shortfall <= TIER_1_MAX_SHORTFALL_PCT:
        multiplier = TIER_1_MULTIPLIER
    elif shortfall <= TIER_2_MAX_SHORTFALL_PCT:
        multiplier = TIER_2_MULTIPLIER
    else:
        multiplier = TIER_3_MULTIPLIER

    raw_pct = q2(shortfall * multiplier)
    if anchor_dark:
        raw_pct = raw_pct + ANCHOR_DARK_BONUS_PCT
    # floor first, cap second - the order is pinned
    reduction_pct = min(max_reduction, max(MIN_REDUCTION_PCT, raw_pct))
    reduction_pct = q2(reduction_pct)
    reduced_rent = cents(D(lease["base_rent_monthly_cents"])
                         * (100 - reduction_pct) / 100)
    return {
        "shortfall_pct_at_election": q2(shortfall),
        "anchor_bonus_applied": bool(anchor_dark),
        "reduction_pct": reduction_pct,
        "reduced_rent_monthly_cents": reduced_rent,
    }


# ----------------------------------------------------------- estoppel fees

def estoppel_fees(disclosed_exclusive_count, disclosed_breach, expedite):
    subtotal = (BASE_ESTOPPEL_FEE_CENTS
                + PER_DISCLOSURE_FEE_CENTS * disclosed_exclusive_count
                + (BREACH_DISCLOSURE_FEE_CENTS if disclosed_breach else 0))
    if subtotal <= TIER_A_MAX_SUBTOTAL_CENTS:
        surcharge_pct = TIER_A_SURCHARGE_PCT
    elif subtotal <= TIER_B_MAX_SUBTOTAL_CENTS:
        surcharge_pct = TIER_B_SURCHARGE_PCT
    else:
        surcharge_pct = TIER_C_SURCHARGE_PCT
    surcharge = cents(D(subtotal) * surcharge_pct / 100) if expedite else 0
    return subtotal, subtotal + surcharge


def recompute_lender_conditions(cert):
    lease = store.leases.get(cert["lease_id"])
    if lease is None:
        cert["lender_conditions_met"] = False
        return
    value = (cert["status"] == "TENANT_SIGNED"
             and cert["pinned_lease_version"] == lease["version"]
             and lease["use_compliance_status"] == "CLEAR"
             and (not has_breached_condition(lease)
                  or cert["disclosed_cotenancy_breach"]))
    cert["lender_conditions_met"] = bool(value)


# ------------------------------------------------------------ notice cascade

def escalate_notice(notice, at_instant):
    """The four-hop escalation cascade plus its fan-out (PRD 3.6)."""
    notice["status"] = "ESCALATED"
    notice["escalated_at"] = fmt_dt(at_instant)
    touch(notice)

    violating = store.leases.get(notice["violating_lease_id"])
    if violating is not None:
        violating["use_compliance_status"] = "IN_VIOLATION"
        touch_lease(violating)

    if notice["notice_kind"] == "EXCLUSIVE_USE" and notice.get("clause_id"):
        clause = store.clauses.get(notice["clause_id"])
        benefited = store.leases.get(clause["lease_id"]) if clause else None
        if benefited is not None:
            grant_eligible(benefited, at_instant)
    elif notice["notice_kind"] == "RADIUS" and violating is not None:
        grant_eligible(violating, at_instant)


def close_notice(notice, new_status, release_benefited):
    """Shared tail for cure / withdraw / upheld-dispute closure."""
    was_escalated = notice["status"] == "ESCALATED"
    notice["status"] = new_status
    if new_status == "WITHDRAWN":
        notice["escalated_at"] = None
    touch(notice)

    violating = store.leases.get(notice["violating_lease_id"])
    if violating is not None and recompute_use_compliance(violating):
        touch_lease(violating)

    if release_benefited and was_escalated:
        benefited = None
        if notice["notice_kind"] == "EXCLUSIVE_USE" and notice.get("clause_id"):
            clause = store.clauses.get(notice["clause_id"])
            benefited = store.leases.get(clause["lease_id"]) if clause else None
        elif notice["notice_kind"] == "RADIUS":
            benefited = violating
        if benefited is not None:
            release_remedy(benefited)


# ------------------------------------------------------- termination cascade

def expire_lease_protections(lease):
    expired_clauses = []
    expired_restrictions = []
    for clause in clauses_of_lease(lease["id"]):
        if clause["status"] in ("ACTIVE", "SUSPENDED"):
            clause["status"] = "EXPIRED"
            touch(clause)
            expired_clauses.append(clause["id"])
    for restriction in restrictions_of_lease(lease["id"]):
        if restriction["status"] == "ACTIVE":
            restriction["status"] = "EXPIRED"
            touch(restriction)
            expired_restrictions.append(restriction["id"])
    return expired_clauses, expired_restrictions


def _withdraw_disputes_for_expired(clause_ids, restriction_ids):
    """PRD 3.6: a PENDING dispute whose cited protection expired through lease
    termination is withdrawn together with its notice."""
    for dispute in _ordered(list(store.disputes.values())):
        if dispute["status"] != "PENDING":
            continue
        notice = store.notices.get(dispute["notice_id"])
        if notice is None:
            continue
        cited = ((notice.get("clause_id") and notice["clause_id"] in clause_ids)
                 or (notice.get("radius_restriction_id")
                     and notice["radius_restriction_id"] in restriction_ids))
        if not cited:
            continue
        dispute["status"] = "WITHDRAWN"
        touch(dispute)
        if notice["status"] in ("ISSUED", "DISPUTED", "ESCALATED"):
            close_notice(notice, "WITHDRAWN", True)


def terminate_lease_cascade(lease, by_remedy=False):
    center = center_of_lease(lease)
    lease["premises_status"] = "TERMINATED"
    lease["dark_since"] = None
    if by_remedy:
        lease["remedy_status"] = "TERMINATED_BY_REMEDY"
    touch_lease(lease)

    clause_ids, restriction_ids = expire_lease_protections(lease)

    for cond in conditions_of_lease(lease["id"]):
        if cond["status"] in ("SATISFIED", "BREACHED", "CURED"):
            cond["status"] = "WAIVED"
            cond["breach_detected_at"] = None
            cond["consecutive_breach_days"] = 0
            touch(cond)

    for election in elections_of_lease(lease["id"]):
        if election["status"] in ("ELECTED", "REDUCTION_ACTIVE"):
            election["status"] = "CONSUMMATED"
            election["_accrual_frozen_date"] = today()
            touch(election)

    _withdraw_disputes_for_expired(set(clause_ids), set(restriction_ids))

    recompute_lease_money(lease)
    if center is not None:
        recompute_center_derived(center)
        evaluate_center_conditions(center, "LIVE_STRICT", kinds=("ONGOING",),
                                   skip_lease_ids={lease["id"]})
        finalize_center(center)


# --------------------------------------------------------- election closure

def consummate_reduction(election, lease):
    election["status"] = "CONSUMMATED"
    election["_accrual_frozen_date"] = today()
    touch(election)
    recompute_abatement(lease)
    recompute_effective_rent(lease)
    if lease["remedy_status"] == "REMEDY_ACTIVE":
        remaining = [e for e in elections_of_lease(lease["id"])
                     if e["status"] == "REDUCTION_ACTIVE"]
        if not remaining:
            if has_breached_condition(lease):
                lease["remedy_status"] = "ELIGIBLE"
            else:
                lease["remedy_status"] = "NONE"
                lease["remedy_eligible_at"] = None
    touch_lease(lease)


def consummate_termination(election, lease):
    election["status"] = "CONSUMMATED"
    touch(election)
    terminate_lease_cascade(lease, by_remedy=True)


# ------------------------------------------------------------------- sweep

def compliance_sweep(center):
    at_instant = now()
    before_remedy = dict((l["id"], l["remedy_status"])
                         for l in leases_of_center(center["id"]))
    escalated = 0

    # 1. escalate every notice past its cure deadline with no PENDING dispute
    for notice in notices_of_center(center["id"]):
        if notice["status"] != "ISSUED":
            continue
        if any(d["status"] == "PENDING" for d in disputes_of_notice(notice["id"])):
            continue
        deadline = parse_dt(notice["cure_deadline_at"])
        if deadline is not None and deadline <= at_instant:
            escalate_notice(notice, at_instant)
            escalated += 1
    recompute_center_derived(center)

    # 2. leases whose breached condition has outlasted its grace requirement
    for lease in leases_of_center(center["id"]):
        if lease["remedy_status"] != "NONE":
            continue
        for cond in conditions_of_lease(lease["id"]):
            if cond["status"] == "BREACHED" \
                    and cond["consecutive_breach_days"] >= cond["grace_period_days"]:
                grant_eligible(lease, at_instant)
                break

    # 3. re-evaluate every condition of the center under the live strict engine
    tally = evaluate_center_conditions(center, "LIVE_STRICT")

    # 4. consummate matured reductions and scheduled terminations
    sweep_date = at_instant.date()
    for lease in leases_of_center(center["id"]):
        for election in elections_of_lease(lease["id"]):
            if election["status"] == "REDUCTION_ACTIVE" \
                    and as_date(election["window_through_date"]) <= sweep_date:
                consummate_reduction(election, lease)
    for lease in leases_of_center(center["id"]):
        for election in elections_of_lease(lease["id"]):
            if election["status"] == "TERMINATION_SCHEDULED" \
                    and election["termination_effective_date"] \
                    and as_date(election["termination_effective_date"]) <= sweep_date:
                consummate_termination(election, lease)

    # 5. re-run the ledger and effective rent for every lease of the center
    for lease in leases_of_center(center["id"]):
        if recompute_lease_money(lease):
            touch_lease(lease)

    center["last_sweep_at"] = fmt_dt(at_instant)
    bump_center(center)

    newly_eligible = 0
    for lease in leases_of_center(center["id"]):
        if before_remedy.get(lease["id"]) == "NONE" \
                and lease["remedy_status"] != "NONE":
            newly_eligible += 1

    return {
        "as_of": fmt_dt(at_instant),
        "escalated_notice_count": escalated,
        "newly_eligible_lease_count": newly_eligible,
        "cured_condition_count": tally["cured"],
        "breached_condition_count": breached_condition_count(center["id"]),
        "compliance_posture": center["compliance_posture"],
    }


# -------------------------------------------------------------- clock reset

def reposition_clock(instant):
    """PRD 2.4: re-runs the ledger and effective rent for every lease with an
    active reduction and re-derives estoppel staleness; never escalates a notice
    and never changes a condition's status."""
    store.clock = instant
    touched_centers = set()
    for lease in _ordered(list(store.leases.values())):
        if not any(e["status"] == "REDUCTION_ACTIVE"
                   for e in elections_of_lease(lease["id"])):
            continue
        if recompute_lease_money(lease):
            touch_lease(lease)
            touched_centers.add(lease["center_id"])
    for center_id in touched_centers:
        center = store.centers.get(center_id)
        if center is not None:
            recompute_center_derived(center)
