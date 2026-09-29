"""Derivations and cascades (PRD §2.8, §2.9, §3.2, §3.4, §3.7)."""

import calculations as calc
from db import db, fmt_ts, now, set_dt, sorted_rows, touch

# ---------------------------------------------------------------- collections


def licenses_of(licensee_id):
    return sorted_rows([l for l in db.state_licenses.values() if l["licensee_id"] == licensee_id])


def holdings_of(licensee_id):
    return sorted_rows([h for h in db.holdings.values() if h["licensee_id"] == licensee_id])


def authorizations_of_license(state_license_id):
    return sorted_rows(
        [a for a in db.authorizations.values() if a["state_license_id"] == state_license_id]
    )


def authorizations_of_delegate(delegate_id):
    return sorted_rows([a for a in db.authorizations.values() if a["delegate_id"] == delegate_id])


def control_persons_of(licensee_id):
    return sorted_rows([c for c in db.control_persons.values() if c["licensee_id"] == licensee_id])


def call_reports_of(state_license_id):
    return sorted_rows(
        [r for r in db.call_reports.values() if r["state_license_id"] == state_license_id]
    )


def info_requests_of(exam_id):
    return sorted_rows([r for r in db.info_requests.values() if r["exam_id"] == exam_id])


# ------------------------------------------------------------- bond / licence


def recompute_bond_requirement(license_row, delegate_count=None):
    jur = db.jurisdictions.get(license_row["jurisdiction_id"])
    if jur is None:
        return
    if delegate_count is None:
        delegate_count = license_row["active_delegate_count"]
    value = calc.surety_bond_requirement(
        jur, license_row["annual_volume_cents"], license_row["license_class"], delegate_count
    )
    license_row["bond_requirement_cents"] = value


def mint_license_number(jurisdiction):
    seq = db.license_seq.get(jurisdiction["id"], 0) + 1
    db.license_seq[jurisdiction["id"]] = seq
    return "MT-%s-%06d" % (jurisdiction["state_code"], seq)


# ------------------------------------------------------------ coverage / posture


def recompute_coverage(licensee):
    """Re-derives the aggregate, both investment variants, the ratio and the
    posture.  Returns the posture that held before the call."""
    old_posture = licensee["coverage_posture"]
    rows = licenses_of(licensee["id"])
    licensee["aggregate_outstanding_obligations_cents"] = calc.licensee_obligation_aggregate(rows)
    obligations = licensee["aggregate_outstanding_obligations_cents"]
    holdings = holdings_of(licensee["id"])
    licensee["book_investment_value_cents"] = calc.book_value_total(holdings)
    licensee["eligible_investment_value_cents"] = calc.eligible_market_total(holdings, obligations)
    licensee["coverage_ratio_bps"] = calc.ratio_bps(
        licensee["eligible_investment_value_cents"], obligations
    )
    licensee["coverage_posture"] = calc.coverage_posture(
        licensee["coverage_ratio_bps"], licensee["consecutive_failed_test_count"]
    )
    return old_posture


def derive_expansion_gate(license_row, licensee):
    """PRD §2.8 — OPEN exactly when all five conditions hold."""
    if (
        license_row["license_status"] == "ACTIVE"
        and license_row["bond_status"] == "POSTED"
        and license_row["reporting_status"] == "CURRENT"
        and not license_row["exam_findings_open"]
        and licensee["coverage_posture"] in ("COMPLIANT", "WATCH")
    ):
        return "OPEN"
    return "BLOCKED"


def set_gate(license_row, value):
    if license_row["expansion_gate"] != value:
        license_row["expansion_gate"] = value
        touch(license_row)


def refresh_gate(license_row, licensee):
    set_gate(license_row, derive_expansion_gate(license_row, licensee))


def refresh_all_gates(licensee):
    for lic in licenses_of(licensee["id"]):
        refresh_gate(lic, licensee)


# ----------------------------------------------------------------- delegates


def delegate_has_active_authorization(delegate_id):
    return any(a["status"] == "ACTIVE" for a in authorizations_of_delegate(delegate_id))


def delegate_has_live_authorization(delegate_id):
    return any(a["status"] != "TERMINATED" for a in authorizations_of_delegate(delegate_id))


def suspend_delegate_if_parked(delegate):
    """Level four of the posture cascade / bond-cancellation cascade."""
    if delegate is None or delegate["status"] == "TERMINATED":
        return
    if delegate_has_active_authorization(delegate["id"]):
        return
    if delegate["status"] != "SUSPENDED":
        delegate["status"] = "SUSPENDED"
        delegate["oversight_hold"] = True
        touch(delegate)
    elif not delegate["oversight_hold"]:
        delegate["oversight_hold"] = True
        touch(delegate)


def park_pending_authorizations(license_rows):
    """Levels three and four: PENDING_OVERSIGHT -> SUSPENDED_BY_POSTURE."""
    affected = []
    for lic in license_rows:
        for auth in authorizations_of_license(lic["id"]):
            if auth["status"] == "PENDING_OVERSIGHT":
                auth["status"] = "SUSPENDED_BY_POSTURE"
                touch(auth)
                affected.append(auth)
    for auth in affected:
        suspend_delegate_if_parked(db.delegates.get(auth["delegate_id"]))


def propagate_posture(licensee, old_posture, force_park=False):
    """The posture cascade of §2.9 plus the recovery re-derivation of §3.4."""
    new_posture = licensee["coverage_posture"]
    refresh_all_gates(licensee)
    if new_posture in ("DEFICIENT", "FROZEN"):
        if force_park or old_posture not in ("DEFICIENT", "FROZEN"):
            park_pending_authorizations(
                [l for l in licenses_of(licensee["id"]) if l["license_status"] == "ACTIVE"]
            )


# ------------------------------------------------------- licence-level cascades


def suspend_license_cascade(license_row, licensee):
    """ACTIVE -> SUSPENDED (bond cancellation notice, consent order)."""
    license_row["license_status"] = "SUSPENDED"
    touch(license_row)
    licensee["active_license_count"] = max(0, licensee["active_license_count"] - 1)
    touch(licensee)

    suspended = []
    for auth in authorizations_of_license(license_row["id"]):
        if auth["status"] == "ACTIVE":
            auth["status"] = "SUSPENDED"
            touch(auth)
            suspended.append(auth)
    license_row["active_delegate_count"] = 0
    recompute_bond_requirement(license_row, delegate_count=0)
    set_gate(license_row, "BLOCKED")

    for auth in suspended:
        delegate = db.delegates.get(auth["delegate_id"])
        if delegate is None:
            continue
        delegate["authorized_state_count"] = max(0, delegate["authorized_state_count"] - 1)
        touch(delegate)
        if delegate["authorized_state_count"] == 0 and delegate["status"] == "ACTIVE":
            delegate["status"] = "SUSPENDED"
            delegate["oversight_hold"] = True


def revoke_license_cascade(license_row, licensee):
    """The four-level revocation cascade of §2.9."""
    was_active = license_row["license_status"] == "ACTIVE"
    license_row["license_status"] = "REVOKED"
    license_row["bond_status"] = "CANCELLED"
    touch(license_row)
    set_gate(license_row, "BLOCKED")
    if was_active:
        licensee["active_license_count"] = max(0, licensee["active_license_count"] - 1)
        touch(licensee)

    terminated_active = []
    for auth in authorizations_of_license(license_row["id"]):
        if auth["status"] in ("PENDING_OVERSIGHT", "ACTIVE", "SUSPENDED_BY_POSTURE", "SUSPENDED"):
            was_auth_active = auth["status"] == "ACTIVE"
            auth["status"] = "TERMINATED"
            touch(auth)
            if was_auth_active:
                terminated_active.append(auth)
    license_row["active_delegate_count"] = 0

    for auth in terminated_active:
        delegate = db.delegates.get(auth["delegate_id"])
        if delegate is None:
            continue
        delegate["authorized_state_count"] = max(0, delegate["authorized_state_count"] - 1)
        touch(delegate)
    for auth in authorizations_of_license(license_row["id"]):
        delegate = db.delegates.get(auth["delegate_id"])
        if delegate is None or delegate["status"] == "TERMINATED":
            continue
        if not delegate_has_live_authorization(delegate["id"]):
            delegate["status"] = "TERMINATED"
            touch(delegate)

    old_posture = recompute_coverage(licensee)
    touch(licensee)
    propagate_posture(licensee, old_posture)


def surrender_license_cascade(license_row, licensee):
    """SURRENDER_REQUESTED -> SURRENDERED."""
    license_row["license_status"] = "SURRENDERED"
    license_row["bond_status"] = "CANCELLED"
    touch(license_row)
    set_gate(license_row, "BLOCKED")
    for auth in authorizations_of_license(license_row["id"]):
        if auth["status"] != "TERMINATED":
            auth["status"] = "TERMINATED"
            touch(auth)
    license_row["active_delegate_count"] = 0
    old_posture = recompute_coverage(licensee)
    touch(licensee)
    propagate_posture(licensee, old_posture)


# ------------------------------------------------------------- control chain


def recompute_control_chain(licensee):
    rows = [
        c
        for c in control_persons_of(licensee["id"])
        if c["status"] != "REMOVED" and c["control_determination"] == "CONTROL"
    ]
    status = "VERIFIED"
    if any(
        c["background_check_status"] == "ADVERSE" or c["change_of_control_status"] == "DENIED"
        for c in rows
    ):
        status = "BLOCKED"
    elif any(
        c["background_check_status"] == "PENDING"
        or c["change_of_control_status"] == "PENDING_APPROVAL"
        for c in rows
    ):
        status = "PENDING_CHECKS"
    if licensee["control_chain_status"] != status:
        licensee["control_chain_status"] = status
        touch(licensee)


def force_control_chain_blocked(licensee):
    if licensee["control_chain_status"] != "BLOCKED":
        licensee["control_chain_status"] = "BLOCKED"
        touch(licensee)


def children_of(control_person_id):
    return sorted_rows(
        [
            c
            for c in db.control_persons.values()
            if c["parent_control_person_id"] == control_person_id
        ]
    )


def maybe_seat(control_person):
    if control_person["status"] != "PROPOSED":
        return
    if control_person["background_check_status"] in ("NOT_REQUIRED", "CLEARED") and control_person[
        "change_of_control_status"
    ] in ("NOT_REQUIRED", "APPROVED"):
        control_person["status"] = "SEATED"
        touch(control_person)


def recompute_descendants(control_person, remove=False):
    """Re-derives both ownership figures for every descendant of a row whose
    contribution just changed.  With remove=True the descendants are driven to
    the terminal REMOVED as well (the disqualifying-finding path)."""
    for child in children_of(control_person["id"]):
        effective, attributed = calc.ownership_attribution(
            child["direct_ownership_bps"], control_person
        )
        child["effective_ownership_bps"] = effective
        child["attributed_ownership_bps"] = attributed
        child["control_determination"] = calc.control_determination(attributed, child["role_title"])
        if remove and child["status"] != "REMOVED":
            child["status"] = "REMOVED"
        touch(child)
        recompute_descendants(child, remove=remove)


# ------------------------------------------------------------------ exams


def recompute_open_request_count(exam):
    count = sum(
        1
        for r in info_requests_of(exam["id"])
        if r["status"] in ("OPEN", "OVERDUE", "RESPONDED")
    )
    if exam["open_request_count"] != count:
        exam["open_request_count"] = count
        touch(exam)


def apply_exam_findings(exam, licensee):
    """REPORT_DRAFT -> REPORT_ISSUED with findings_count >= 3."""
    participating = set(exam["participating_jurisdiction_ids"] or [])
    affected = [
        l for l in licenses_of(licensee["id"]) if l["jurisdiction_id"] in participating
    ]
    for lic in affected:
        if not lic["exam_findings_open"]:
            lic["exam_findings_open"] = True
            touch(lic)
        set_gate(lic, "BLOCKED")
    park_pending_authorizations(affected)


# --------------------------------------------------------------- call reports


def apply_call_report(license_row, report, jurisdiction, licensee):
    """§3.5 — reporting dimension, annual volume and bond requirement."""
    clock = now()
    due = report["_due_at"]
    if clock > due:
        status = "LATE"
    elif report["transaction_count"] == 0 and report["transmission_volume_cents"] > 0:
        status = "FILED_DEFICIENT"
    else:
        status = "FILED"
    report["status"] = status

    current = license_row["reporting_status"]
    if status == "LATE":
        if current == "CURRENT":
            license_row["reporting_status"] = "DELINQUENT"
    elif status == "FILED_DEFICIENT":
        if current == "CURRENT":
            license_row["reporting_status"] = "DEFICIENT_FILING"
    else:
        if current == "DEFICIENT_FILING":
            if report["transaction_count"] > 0:
                license_row["reporting_status"] = "CURRENT"
        elif current == "DELINQUENT":
            key = calc.period_sort_key(report["period_label"])
            blocking = any(
                r["status"] == "LATE" and calc.period_sort_key(r["period_label"]) > key
                for r in call_reports_of(license_row["id"])
                if r["id"] != report["id"]
            )
            if not blocking:
                license_row["reporting_status"] = "CURRENT"

    license_row["annual_volume_cents"] += report["transmission_volume_cents"]
    recompute_bond_requirement(license_row)
    touch(license_row)
    refresh_gate(license_row, licensee)
    return status
