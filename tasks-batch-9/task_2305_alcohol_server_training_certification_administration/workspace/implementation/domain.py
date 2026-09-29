"""Cascades, certificate issuance and the compliance epoch (PRD 3.2-3.9)."""

from decimal import Decimal

import chain
import store as st
from calcs import add_days, add_months
from store import apply_changes, create_row, store

LIVE_ENROLLMENT_STATES_FOR_OVERLAP = (
    "REGISTERED", "ATTENDED", "EXAM_SCHEDULED", "EXAM_IN_PROGRESS", "EXAM_FAILED",
)
LIVE_APPROVAL_STATUSES = ("SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "STALE")
MAX_REVIEW_ROUNDS = 3
CANCELLABLE_SESSION_STATES = ("SCHEDULED", "ROSTER_LOCKED")
MAX_REMINDERS = 2


# --- collection helpers ----------------------------------------------------

def enrollments_of_session(session_id):
    return [e for e in st.rows("enrollments") if e["class_session_id"] == session_id]


def attempts_of_enrollment(enrollment_id):
    return [a for a in st.rows("exam_attempts") if a["enrollment_id"] == enrollment_id]


def approvals_of_course(course_id):
    return [a for a in st.rows("course_approvals") if a["course_id"] == course_id]


def submissions_of_certificate(certificate_id):
    return [
        s for s in st.rows("registry_submissions")
        if s["certificate_id"] == certificate_id
    ]


def documents_of_account(account_id):
    return [
        d for d in st.rows("dram_shop_documents")
        if d["employer_account_id"] == account_id
    ]


def live_enrolled_count(session_id):
    return len([
        e for e in enrollments_of_session(session_id)
        if e["enrollment_state"] != "WITHDRAWN"
    ])


# --- seat-credit ledger ----------------------------------------------------

def refund_seat_credit(enrollment):
    """One seat back to the sponsor when the seat was charged."""
    if not enrollment.get("seat_credit_charged"):
        return
    account = st.get("employer_accounts", enrollment["sponsoring_employer_account_id"])
    if account is not None:
        apply_changes(account, {
            "seat_credits_refunded_total": account["seat_credits_refunded_total"] + 1,
            "seat_credit_balance": account["seat_credit_balance"] + 1,
        })
    apply_changes(enrollment, {"seat_credit_charged": False})


def consume_seat_credit(account):
    apply_changes(account, {
        "seat_credits_consumed_total": account["seat_credits_consumed_total"] + 1,
        "seat_credit_balance": account["seat_credit_balance"] - 1,
    })


# --- session cancellation cascade -----------------------------------------

def cancel_session(session, cancellation_reason, withdrawal_reason):
    """Cancel a live session, withdrawing every live seat and refunding credits."""
    for enrollment in enrollments_of_session(session["id"]):
        if enrollment["enrollment_state"] == "WITHDRAWN":
            continue
        apply_changes(enrollment, {
            "enrollment_state": "WITHDRAWN",
            "withdrawal_reason": withdrawal_reason,
        })
        refund_seat_credit(enrollment)
    apply_changes(session, {
        "session_status": "CANCELLED",
        "cancellation_reason": cancellation_reason,
        "enrolled_count": 0,
    })


# --- superseding publish cascade ------------------------------------------

def publish_course(course):
    """DRAFT -> PUBLISHED plus the five-hop supersession cascade."""
    apply_changes(course, {"status": "PUBLISHED"})
    target_id = course.get("supersedes_course_id")
    if not target_id:
        return
    superseded = st.get("courses", target_id)
    if superseded is None:
        return
    # hop 1
    apply_changes(superseded, {"status": "RETIRED", "retired_at": store.clock})
    # hop 2
    superseded_approvals = []
    for approval in approvals_of_course(superseded["id"]):
        if approval["approval_status"] == "APPROVED":
            apply_changes(approval, {"approval_status": "SUPERSEDED"})
            superseded_approvals.append(approval["id"])
    if not superseded_approvals:
        return
    # hops 3, 4 and 5
    for session in st.rows("class_sessions"):
        if (session["pinned_course_approval_id"] in superseded_approvals
                and session["session_status"] in CANCELLABLE_SESSION_STATES):
            cancel_session(session, "COURSE_SUPERSEDED", "SESSION_CANCELLED")


# --- trainer suspension cascade -------------------------------------------

def suspend_trainer(trainer, suspension_reason):
    apply_changes(trainer, {
        "trainer_status": "SUSPENDED",
        "suspension_reason": suspension_reason,
    })
    for session in st.rows("class_sessions"):
        if (session["trainer_id"] == trainer["id"]
                and session["session_status"] in CANCELLABLE_SESSION_STATES):
            cancel_session(session, "TRAINER_SUSPENDED", "SESSION_CANCELLED")


# --- course content revision ----------------------------------------------

def stale_approvals_of(course):
    for approval in approvals_of_course(course["id"]):
        if approval["approval_status"] == "APPROVED":
            apply_changes(approval, {"approval_status": "STALE"})


# --- certificate issuance --------------------------------------------------

def issue_certificate(enrollment, jurisdiction, track):
    prior = chain.certificate_renewal_selector(
        enrollment["alcohol_server_id"], jurisdiction["id"], track,
    )
    issued_at = store.clock
    months = jurisdiction["certificate_validity_months"]
    if prior is None or prior["validity_state"] in ("LAPSED", "SUSPENDED"):
        anchor_mode = "ISSUANCE_ANCHORED"
        expires_at = add_months(issued_at, months)
    else:
        anchor_mode = "ANNIVERSARY_ANCHORED"
        expires_at = add_months(prior["expires_at"], months)

    sequence = jurisdiction["certificates_issued_count"] + 1
    apply_changes(jurisdiction, {"certificates_issued_count": sequence})
    number = "%s-%04d-%05d" % (jurisdiction["state_code"], issued_at.year, sequence)

    required = bool(jurisdiction["registry_submission_required"])
    certificate = create_row("certificates", {
        "alcohol_server_id": enrollment["alcohol_server_id"],
        "enrollment_id": enrollment["id"],
        "state_jurisdiction_id": jurisdiction["id"],
        "renews_certificate_id": prior["id"] if prior is not None else None,
        "certificate_number": number,
        "track": track,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "expiry_anchor_mode": anchor_mode,
        "validity_state": "ACTIVE",
        "registry_state": "PENDING_SUBMISSION" if required else "NOT_REQUIRED",
        "registry_due_at": (
            add_days(issued_at, jurisdiction["registry_deadline_days"])
            if required else None
        ),
        "reminder_sent_count": 0,
        "last_reminder_at": None,
    })
    if prior is not None:
        apply_changes(prior, {"validity_state": "SUPERSEDED"})
    return certificate


def complete_session(session):
    """EXAM_OPEN -> COMPLETED, issuing one certificate per passed seat."""
    apply_changes(session, {
        "session_status": "COMPLETED",
        "completed_at": store.clock,
    })
    roster = enrollments_of_session(session["id"])
    for enrollment in roster:
        if enrollment["enrollment_state"] == "EXAM_SCHEDULED":
            apply_changes(enrollment, {"enrollment_state": "INCOMPLETE"})

    course = st.get("courses", session["course_id"])
    jurisdiction = st.get("state_jurisdictions", session["state_jurisdiction_id"])
    certified_servers = []
    for enrollment in roster:
        if enrollment["enrollment_state"] != "PASSED":
            continue
        issue_certificate(enrollment, jurisdiction, course["track"])
        if enrollment["alcohol_server_id"] not in certified_servers:
            certified_servers.append(enrollment["alcohol_server_id"])

    for server_id in certified_servers:
        server = st.get("alcohol_servers", server_id)
        if server is not None:
            chain.recompute_chain(server)

    trainer = st.get("trainers", session["trainer_id"])
    if trainer is not None:
        chain.recompute_trainer_metrics(trainer)


# --- enrollment attempt bookkeeping ---------------------------------------

def recompute_attempt_counters(enrollment, jurisdiction):
    """Derived counters over the seat's counted (PASS/FAIL) attempts."""
    counted = [
        a for a in attempts_of_enrollment(enrollment["id"])
        if a["outcome"] in ("PASS", "FAIL")
    ]
    changes = {"attempt_count": len(counted)}
    if counted:
        changes["best_score_pct"] = max(a["score_pct"] for a in counted)
        last = counted[-1]
        changes["last_counted_attempt_ended_at"] = last["submitted_at"]
        if last["outcome"] == "FAIL":
            # PRD 3.6: only the FAIL branch stamps retake_eligible_at; the PASS
            # branch enumerates its own effects and leaves this window alone.
            changes["retake_eligible_at"] = last["submitted_at"] + _hours(
                jurisdiction["retake_cooling_off_hours"]
            )
    return changes


def _hours(hours):
    from datetime import timedelta
    return timedelta(hours=int(hours))


# --- registry acknowledgement --------------------------------------------

def acknowledge_accepted(submission, certificate):
    apply_changes(submission, {
        "submission_state": "ACCEPTED",
        "acknowledged_at": store.clock,
    })
    changes = {"registry_state": "ACCEPTED"}
    restore = (certificate["validity_state"] == "SUSPENDED"
               and store.clock < certificate["expires_at"])
    if restore:
        changes["validity_state"] = "ACTIVE"
    apply_changes(certificate, changes)
    if restore:
        server = st.get("alcohol_servers", certificate["alcohol_server_id"])
        if server is not None:
            chain.recompute_chain(server)


def acknowledge_rejected(submission, certificate, rejection_code):
    apply_changes(submission, {
        "submission_state": "REJECTED",
        "acknowledged_at": store.clock,
        "rejection_code": rejection_code,
    })
    jurisdiction = st.get("state_jurisdictions", certificate["state_jurisdiction_id"])
    changes = {"registry_state": "RESUBMIT_REQUIRED"}
    suspend = (bool(jurisdiction and jurisdiction["registry_submission_required"])
               and certificate["validity_state"] in ("ACTIVE", "GRACE"))
    if suspend:
        changes["validity_state"] = "SUSPENDED"
    apply_changes(certificate, changes)
    if suspend:
        server = st.get("alcohol_servers", certificate["alcohol_server_id"])
        if server is not None:
            chain.recompute_chain(server)


# --- the compliance epoch -------------------------------------------------

COUNTER_NAMES = (
    "trainers_lapsed_count",
    "approvals_expired_count",
    "certificates_graced_count",
    "certificates_lapsed_count",
    "reminders_sent_count",
    "assignments_restricted_count",
    "assignments_restored_count",
    "locations_recomputed_count",
    "documents_voided_count",
)


def run_compliance_epoch():
    run_at = store.clock
    counters = {name: 0 for name in COUNTER_NAMES}

    # phase one -- trainer lapse
    for trainer in st.rows("trainers"):
        if (trainer["trainer_status"] == "CERTIFIED"
                and trainer["credential_expires_at"] is not None
                and run_at >= trainer["credential_expires_at"]):
            apply_changes(trainer, {"trainer_status": "LAPSED"})
            counters["trainers_lapsed_count"] += 1

    # phase two -- approval expiry
    for approval in st.rows("course_approvals"):
        if (approval["approval_status"] == "APPROVED"
                and approval["expires_at"] is not None
                and run_at >= approval["expires_at"]):
            apply_changes(approval, {"approval_status": "EXPIRED"})
            counters["approvals_expired_count"] += 1

    # phase three -- certificate grace and lapse (at most one transition each)
    affected_server_ids = []
    for certificate in st.rows("certificates"):
        jurisdiction = st.get(
            "state_jurisdictions", certificate["state_jurisdiction_id"]
        )
        moved = False
        if (certificate["validity_state"] == "ACTIVE"
                and run_at >= certificate["expires_at"]):
            apply_changes(certificate, {"validity_state": "GRACE"})
            counters["certificates_graced_count"] += 1
            moved = True
        elif certificate["validity_state"] == "GRACE":
            lapse_at = add_days(
                certificate["expires_at"], jurisdiction["renewal_grace_days"]
            )
            if run_at >= lapse_at:
                apply_changes(certificate, {"validity_state": "LAPSED"})
                counters["certificates_lapsed_count"] += 1
                moved = True
        if moved and certificate["alcohol_server_id"] not in affected_server_ids:
            affected_server_ids.append(certificate["alcohol_server_id"])

    # phase four -- recertification reminders
    for certificate in st.rows("certificates"):
        if certificate["validity_state"] not in ("ACTIVE", "GRACE"):
            continue
        if certificate["reminder_sent_count"] >= MAX_REMINDERS:
            continue
        jurisdiction = st.get(
            "state_jurisdictions", certificate["state_jurisdiction_id"]
        )
        window_opens_at = add_days(
            certificate["expires_at"], -jurisdiction["reminder_lead_days"]
        )
        if run_at >= window_opens_at:
            apply_changes(certificate, {
                "reminder_sent_count": certificate["reminder_sent_count"] + 1,
                "last_reminder_at": run_at,
            })
            counters["reminders_sent_count"] += 1

    # phase five -- server eligibility
    affected_locations = set()
    for server_id in affected_server_ids:
        server = st.get("alcohol_servers", server_id)
        if server is None:
            continue
        if chain.stage_one(server):
            for assignment in chain.live_assignments_of_server(server["id"]):
                affected_locations.add(assignment["employer_location_id"])

    # phase six -- assignment restriction and restoration
    for server in st.rows("alcohol_servers"):
        if not chain.live_assignments_of_server(server["id"]):
            continue
        chain.stage_two(server, counters, affected_locations)

    # phase seven -- location metrics
    chain.stage_three(affected_locations)
    counters["locations_recomputed_count"] = len(affected_locations)

    # phase eight -- account roll-up and documentation voiding
    for account_id in sorted(chain.accounts_of_locations(affected_locations)):
        account = st.get("employer_accounts", account_id)
        if account is not None:
            chain.recompute_account(account)
    for document in st.rows("dram_shop_documents"):
        if document["document_state"] != "ISSUED":
            continue
        account = st.get("employer_accounts", document["employer_account_id"])
        if account is None:
            continue
        if account["account_compliance_rate_pct"] < chain.DOCUMENTATION_FLOOR_PCT:
            reason = "COMPLIANCE_RATE_FELL_BELOW_FLOOR"
        elif run_at >= document["coverage_period_end"]:
            reason = "COVERAGE_PERIOD_ENDED"
        else:
            continue
        apply_changes(document, {"document_state": "VOIDED", "void_reason": reason})
        apply_changes(account, {"dram_shop_discount_status": "EXPIRED"})
        counters["documents_voided_count"] += 1

    fields = {"run_at": run_at}
    fields.update(counters)
    return create_row("compliance_runs", fields, common_fields=False)


# --- dram-shop helpers ----------------------------------------------------

def min_location_strict_rate(account_id):
    locations = chain.locations_of_account(account_id)
    if not locations:
        return Decimal("100.00")
    return min(l["compliance_rate_strict_pct"] for l in locations)
