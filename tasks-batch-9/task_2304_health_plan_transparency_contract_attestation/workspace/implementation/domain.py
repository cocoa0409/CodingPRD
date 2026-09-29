"""Cross-entity domain services: the posture engine, the penalty ledger, the
attestation-status mirror, the forward-looking projection and the compliance run.
"""

import calc
import clock
import db


# ---------------------------------------------------------------------------
# Ledger helpers (PRD 3.9)
# ---------------------------------------------------------------------------


def is_reversed(entry_id):
    return any(e.get("reverses_entry_id") == entry_id for e in db.ledger_entries.values())


def unreversed_accruals(plan_year_id, deficiency_type=None):
    rows = []
    for entry in db.ledger_of_plan_year(plan_year_id):
        if entry["entry_type"] != "ACCRUAL":
            continue
        if deficiency_type is not None and entry["deficiency_type"] != deficiency_type:
            continue
        if is_reversed(entry["id"]):
            continue
        rows.append(entry)
    return rows


def has_unreversed_accrual(plan_year_id, deficiency_type, onset_date=None):
    for entry in unreversed_accruals(plan_year_id, deficiency_type):
        if onset_date is None or entry.get("onset_date") == onset_date:
            return True
    return False


def append_entry(plan_year, entry_type, deficiency_type, signed_amount_cents,
                 daily_rate_cents, days_open, size_multiplier, onset_date,
                 reason, posted_by_user_id=None, reverses_entry_id=None,
                 remediation_plan_id=None):
    entry = db.ledger_common_fields()
    entry.update({
        "plan_year_id": plan_year["id"],
        "entry_type": entry_type,
        "deficiency_type": deficiency_type,
        "signed_amount_cents": signed_amount_cents,
        "daily_rate_cents": daily_rate_cents,
        "days_open": days_open,
        "size_multiplier": size_multiplier,
        "onset_date": onset_date,
        "reverses_entry_id": reverses_entry_id,
        "remediation_plan_id": remediation_plan_id,
        "reason": reason,
        "posted_by_user_id": posted_by_user_id,
    })
    db.ledger_entries[entry["id"]] = entry
    recompute_exposure(plan_year)
    return entry


def post_accrual(plan_year, deficiency_type, onset_date, reason, posted_by_user_id=None):
    """Price and append one ACCRUAL, honouring duplicate suppression: no second
    accrual for a deficiency instance that already has an unreversed accrual of
    the same deficiency_type and onset_date on the same plan year."""
    if has_unreversed_accrual(plan_year["id"], deficiency_type, onset_date):
        return None
    priced = calc.price_accrual(
        deficiency_type, onset_date, clock.today_iso(), plan_year["covered_lives"]
    )
    return append_entry(
        plan_year,
        "ACCRUAL",
        deficiency_type,
        priced["signed_amount_cents"],
        priced["daily_rate_cents"],
        priced["days_open"],
        priced["size_multiplier"],
        priced["onset_date"],
        reason,
        posted_by_user_id,
    )


def recompute_exposure(plan_year):
    """penalty_exposure_cents == SUM(signed_amount_cents) at every instant."""
    total = sum(e["signed_amount_cents"] for e in db.ledger_of_plan_year(plan_year["id"]))
    plan_year["penalty_exposure_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Attestation-status mirror and draft voiding (PRD 3.8)
# ---------------------------------------------------------------------------


def latest_attestation(plan_year_id):
    rows = db.attestations_of_plan_year(plan_year_id)
    return rows[-1] if rows else None


def refresh_attestation_status(plan_year):
    latest = latest_attestation(plan_year["id"])
    plan_year["attestation_status"] = latest["status"] if latest else "NOT_STARTED"


def void_draft_attestations(plan_year, void_reason):
    voided = 0
    for attestation in db.attestations_of_plan_year(plan_year["id"]):
        if attestation["status"] == "DRAFT":
            attestation["status"] = "VOIDED"
            attestation["void_reason"] = void_reason
            db.bump(attestation)
            voided += 1
    if voided:
        refresh_attestation_status(plan_year)
    return voided


# ---------------------------------------------------------------------------
# Posture engine (PRD 2.8)
# ---------------------------------------------------------------------------


def compute_points(plan_year):
    plan_year_id = plan_year["id"]
    points = 0

    cycles = db.refresh_cycles_of_plan_year(plan_year_id)
    points += calc.POINTS_MISSED_REFRESH_CYCLE * sum(
        1 for c in cycles if c["status"] == "MISSED"
    )
    points += calc.POINTS_LATE_CERTIFIED_CYCLE * sum(
        1 for c in cycles if c["status"] == "LATE_CERTIFIED"
    )
    points += calc.POINTS_NON_COMPLIANT_CONTRACT * sum(
        1 for c in db.contracts_of_plan_year(plan_year_id)
        if c["gag_review_status"] == "NON_COMPLIANT"
    )
    points += calc.POINTS_TOOL_SLA_BREACH * sum(
        1 for t in db.tools_of_plan_year(plan_year_id) if t["sla_breach_open"]
    )

    today = clock.today_iso()
    if today > plan_year["rxdc_deadline_date"]:
        points += calc.POINTS_RXDC_LATE * sum(
            1 for s in db.rx_submissions_of_plan_year(plan_year_id)
            if s["status"] != "SUBMITTED"
        )

    attestation_status = plan_year["attestation_status"]
    if attestation_status == "REJECTED" or (
        attestation_status != "ACCEPTED" and today > plan_year["attestation_deadline_date"]
    ):
        points += calc.POINTS_ATTESTATION_LATE

    points += calc.POINTS_UNREASONABLE_DISCLOSURE * sum(
        1 for d in db.disclosures_of_plan_year(plan_year_id)
        if d["status"] == "UNREASONABLE"
    )
    return points


def count_tool_breaches(plan_year_id):
    return sum(1 for t in db.tools_of_plan_year(plan_year_id) if t["sla_breach_open"])


def recompute_posture(plan_year):
    """Recompute deficiency_points, tool_sla_breach_count and compliance_posture.
    A flip into DEFICIENT or FROZEN voids every DRAFT attestation."""
    points = compute_points(plan_year)
    previous = plan_year["compliance_posture"]
    new_posture = calc.posture_for(points, plan_year["freeze_flag"])
    plan_year["deficiency_points"] = points
    plan_year["tool_sla_breach_count"] = count_tool_breaches(plan_year["id"])
    plan_year["compliance_posture"] = new_posture
    if new_posture != previous and new_posture in ("DEFICIENT", "FROZEN"):
        void_draft_attestations(plan_year, "POSTURE_DEFICIENT")
    return new_posture


# ---------------------------------------------------------------------------
# Forward-looking projection (PRD 3.9)
# ---------------------------------------------------------------------------


def open_deficiencies(plan_year, as_of_date_iso):
    """Derived from LIVE open child state, never from the ledger."""
    plan_year_id = plan_year["id"]
    found = []

    for contract in db.contracts_of_plan_year(plan_year_id):
        if contract["gag_review_status"] == "NON_COMPLIANT" and contract["gag_non_compliant_since"]:
            found.append(("GAG_CLAUSE", contract["gag_non_compliant_since"]))

    for cycle in db.refresh_cycles_of_plan_year(plan_year_id):
        if cycle["status"] == "MISSED":
            deadline_date = clock.parse_datetime(cycle["deadline_at"]).date()
            found.append(("MRF_REFRESH", clock.plus_days(deadline_date, 1).isoformat()))

    for tool in db.tools_of_plan_year(plan_year_id):
        if tool["sla_breach_open"] and tool["breach_onset_date"]:
            found.append(("TOOL_SLA", tool["breach_onset_date"]))

    if as_of_date_iso > plan_year["rxdc_deadline_date"]:
        onset = clock.plus_days(
            clock.parse_date(plan_year["rxdc_deadline_date"]), 1
        ).isoformat()
        for submission in db.rx_submissions_of_plan_year(plan_year_id):
            if submission["status"] != "SUBMITTED":
                found.append(("RXDC_LATE", onset))

    if (
        plan_year["attestation_status"] != "ACCEPTED"
        and as_of_date_iso > plan_year["attestation_deadline_date"]
    ):
        onset = clock.plus_days(
            clock.parse_date(plan_year["attestation_deadline_date"]), 1
        ).isoformat()
        found.append(("ATTESTATION_LATE", onset))

    # A deficiency whose onset is after as_of_date is excluded from both variants.
    return [(kind, onset) for kind, onset in found if onset <= as_of_date_iso]


def projection(plan_year, as_of_date_iso):
    return calc.project_exposure(
        open_deficiencies(plan_year, as_of_date_iso),
        as_of_date_iso,
        plan_year["end_date"],
        plan_year["covered_lives"],
    )


# ---------------------------------------------------------------------------
# The compliance run (PRD 3.9)
# ---------------------------------------------------------------------------


def compliance_run(plan_year):
    posture_before = plan_year["compliance_posture"]
    cycles_missed = 0
    amendments_lapsed = 0
    accruals_posted = 0
    now = clock.now()

    with db.txn(plan_year):
        # 1. sweep refresh cycles
        for cycle in db.refresh_cycles_of_plan_year(plan_year["id"]):
            if cycle["status"] != "PENDING":
                continue
            deadline = clock.parse_datetime(cycle["deadline_at"])
            if deadline >= now:
                continue
            cycle["status"] = "MISSED"
            db.bump(cycle)
            cycles_missed += 1
            onset = clock.plus_days(deadline.date(), 1).isoformat()
            entry = post_accrual(
                plan_year,
                "MRF_REFRESH",
                onset,
                "Monthly machine-readable file refresh cycle %s missed."
                % cycle["period_month"],
                None,
            )
            if entry is not None:
                accruals_posted += 1

        # 2. lapse expired amendments
        for contract in db.contracts_of_plan_year(plan_year["id"]):
            for amendment in db.amendments_of_contract(contract["id"]):
                if amendment["status"] not in ("PROPOSED", "COUNTERED"):
                    continue
                expires = clock.parse_datetime(amendment["expires_at"])
                if expires >= now:
                    continue
                amendment["status"] = "LAPSED"
                db.bump(amendment)
                amendments_lapsed += 1
            if contract["data_rights_status"] == "PENDING_AMENDMENT":
                still_open = any(
                    a["amendment_type"] == "DATA_RIGHTS"
                    and a["status"] in ("PROPOSED", "COUNTERED")
                    for a in db.amendments_of_contract(contract["id"])
                )
                if not still_open:
                    contract["data_rights_status"] = "NOT_SECURED"
                    db.bump(contract)

        # 3. recompute
        recompute_exposure(plan_year)
        recompute_posture(plan_year)
        plan_year["last_compliance_run_at"] = clock.now_iso()

    return {
        "run_id": db.new_id(),
        "cycles_missed_count": cycles_missed,
        "amendments_lapsed_count": amendments_lapsed,
        "accruals_posted_count": accruals_posted,
        "posture_before": posture_before,
        "posture_after": plan_year["compliance_posture"],
        "deficiency_points": plan_year["deficiency_points"],
        "penalty_exposure_cents": plan_year["penalty_exposure_cents"],
    }
