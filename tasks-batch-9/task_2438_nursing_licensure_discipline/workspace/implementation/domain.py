"""Shared domain side effects: reconciliation, privilege, reports, sweeps."""
from decimal import Decimal

import calc
import store
from envelope import mark_new, touch
from timeutil import add_days, add_months


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def board_of_license(lic):
    return store.STORE.boards.get(lic["issuing_board_config_id"])


def nurse_of_license(lic):
    return store.STORE.nurses.get(lic["nurse_id"])


def license_of_complaint(complaint):
    return store.STORE.licenses.get(complaint["license_id"])


def license_of_renewal(renewal):
    return store.STORE.licenses.get(renewal["license_id"])


def board_of_renewal(renewal):
    lic = license_of_renewal(renewal)
    return board_of_license(lic) if lic else None


def ce_records_of(renewal_id):
    return [c for c in store.STORE.ce_records.values() if c["renewal_application_id"] == renewal_id]


# ---------------------------------------------------------------------------
# notification reports
# ---------------------------------------------------------------------------
def queue_report(subject_nurse_id, source_entity_type, source_entity_id, channel,
                 basis_code, payload_summary, report_kind="INITIAL"):
    rec = store.base_fields()
    rec.update({
        "subject_nurse_id": subject_nurse_id,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "channel": channel,
        "report_kind": report_kind,
        "basis_code": basis_code,
        "payload_summary": payload_summary,
        "status": "QUEUED",
        "queued_at": store.STORE.clock,
        "transmitted_at": None,
        "acknowledged_at": None,
    })
    store.STORE.reports[rec["id"]] = rec
    mark_new(rec)
    return rec


# ---------------------------------------------------------------------------
# privilege
# ---------------------------------------------------------------------------
def run_privilege(lic, variant="RESIDENCY_DECLARED"):
    status, used_variant, basis = calc.multistate_privilege_determination(lic, variant)
    lic["multistate_privilege_status"] = status
    lic["privilege_variant"] = used_variant
    lic["privilege_basis_state"] = basis
    touch(lic)
    return status


def set_privilege(lic, status):
    lic["multistate_privilege_status"] = status
    touch(lic)


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------
def reconcile_license(lic):
    count = calc.open_encumbrance_count(lic["id"])
    changed = lic.get("open_encumbrance_count") != count
    lic["open_encumbrance_count"] = count
    became_clear = False
    if lic["encumbrance_status"] not in ("RESTRICTED", "SUSPENDED", "REVOKED"):
        desired = "CLEAR" if count == 0 else "INVESTIGATION_PENDING"
        if lic["encumbrance_status"] != desired:
            lic["encumbrance_status"] = desired
            changed = True
            became_clear = desired == "CLEAR"
    if changed:
        touch(lic)
    if became_clear:
        run_privilege(lic, "RESIDENCY_DECLARED")
    nurse = nurse_of_license(lic)
    if nurse is not None:
        recompute_nurse_status(nurse)
    return lic


def recompute_nurse_status(nurse):
    st = store.STORE
    licenses = [l for l in st.licenses.values() if l["nurse_id"] == nurse["id"]]
    if licenses and all(l["encumbrance_status"] == "REVOKED" for l in licenses):
        desired = "REVOKED"
    else:
        encumbered = any(
            l["encumbrance_status"] in ("RESTRICTED", "SUSPENDED", "REVOKED")
            for l in licenses
        )
        license_ids = set(l["id"] for l in licenses)
        open_complaint = any(
            c["license_id"] in license_ids
            and c.get("consolidated_into_complaint_id") is None
            and c["status"] in calc.OPEN_COMPLAINT_STATES
            for c in st.complaints.values()
        )
        desired = "ENCUMBERED" if (encumbered or open_complaint) else "ACTIVE"
    if nurse.get("status") != desired:
        nurse["status"] = desired
        touch(nurse)
    return nurse


def recompute_prior_discipline_count(nurse):
    st = store.STORE
    count = 0
    for proc in st.proceedings.values():
        if proc["status"] != "ORDER_ISSUED":
            continue
        if proc.get("adopted_sanction_tier") in (None, "NONE"):
            continue
        complaint = st.complaints.get(proc["complaint_id"])
        if complaint is None:
            continue
        lic = st.licenses.get(complaint["license_id"])
        if lic is None or lic["nurse_id"] != nurse["id"]:
            continue
        count += 1
    if nurse.get("prior_discipline_count") != count:
        nurse["prior_discipline_count"] = count
        touch(nurse)
    return count


# ---------------------------------------------------------------------------
# renewability gates (ladder steps 11 and 12)
# ---------------------------------------------------------------------------
def is_renewable(lic, board):
    if lic["license_status"] == "ACTIVE":
        return True
    if lic["license_status"] == "EXPIRED":
        deadline = add_days(lic["expires_on"], int(board["renewal_grace_period_days"]))
        return store.STORE.clock <= deadline
    return False


# ---------------------------------------------------------------------------
# clock sweeps (PRD 2.4 / 3.3 / 3.7)
# ---------------------------------------------------------------------------
def run_clock_sweeps(new_clock):
    st = store.STORE
    st.clock = new_clock

    expired_ids = []
    lapsed_ids = []
    withdrawn_renewal_ids = []
    activated_agreement_ids = []

    for lic in sorted(st.licenses.values(), key=lambda r: r["created_at"]):
        if lic["license_status"] == "ACTIVE" and lic["expires_on"] is not None \
                and lic["expires_on"] <= new_clock:
            lic["license_status"] = "EXPIRED"
            touch(lic)
            run_privilege(lic, "RESIDENCY_DECLARED")
            expired_ids.append(lic["id"])

    for lic in sorted(st.licenses.values(), key=lambda r: r["created_at"]):
        if lic["license_status"] != "EXPIRED" or lic["expires_on"] is None:
            continue
        board = board_of_license(lic)
        if board is None:
            continue
        lapse_at = add_days(lic["expires_on"], int(board["lapse_after_grace_days"]))
        if lapse_at > new_clock:
            continue
        lic["license_status"] = "LAPSED"
        lic["multistate_privilege_status"] = "NOT_ELIGIBLE"
        touch(lic)
        lapsed_ids.append(lic["id"])
        for ren in sorted(st.renewals.values(), key=lambda r: r["created_at"]):
            if ren["license_id"] != lic["id"]:
                continue
            if ren["renewal_status"] in ("DRAFT", "SUBMITTED", "CE_DEFICIENT", "CE_VERIFIED"):
                ren["renewal_status"] = "WITHDRAWN"
                touch(ren)
                withdrawn_renewal_ids.append(ren["id"])

    for agreement in sorted(st.agreements.values(), key=lambda r: r["created_at"]):
        if agreement["status"] == "EXECUTED" and agreement["start_date"] is not None \
                and agreement["start_date"] <= new_clock:
            agreement["status"] = "ACTIVE"
            touch(agreement)
            activated_agreement_ids.append(agreement["id"])

    return {
        "current_utc": new_clock,
        "expired_license_ids": expired_ids,
        "lapsed_license_ids": lapsed_ids,
        "activated_agreement_ids": activated_agreement_ids,
        "withdrawn_renewal_ids": withdrawn_renewal_ids,
    }
