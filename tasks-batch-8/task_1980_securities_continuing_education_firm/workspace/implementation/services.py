"""Business logic: cascades, recomputes, selectors, and the enforcement sweep.

Every side effect is applied atomically inside the triggering request. Every
record touched by a cascade gets its own version bump and updated_at refresh
(via touch()).
"""

from datetime import timedelta
from decimal import Decimal

from db import store, clock_now, base_record, touch, audit, new_id
from errors import ApiError, ERR_NOT_FOUND
from util import q2, round_to_half

# --- Pinned constants (SCAFFOLD 1.3) ---
MAX_ATTEMPTS = 3
ENROLLMENT_VALIDITY_DAYS = 90
ASSIGNMENT_WINDOW_DAYS = 120
GRACE_DAYS = 30
CARRYOVER_CAP_HOURS = Decimal("6")
MIN_REQUIRED_HOURS = Decimal("6")
BASE_HOURS_BY_TIER = {"RR": Decimal("12"), "PRINCIPAL": Decimal("16")}
PER_PRODUCT_SURCHARGE = Decimal("2")
SURCHARGE_CAP = 3

SEAT_HOLDING_STATUSES = ("ENROLLED", "IN_PROGRESS", "COMPLETED")

SYSTEM_ACTOR = ("system", "system")


def get_or_404(collection, rid, label="Resource"):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s '%s' not found" % (label, rid))
    return rec


def by_seq(items):
    return sorted(items, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Session seat accounting (conserved invariant)
# ---------------------------------------------------------------------------
def active_seat_holders(session_id):
    return sum(1 for e in store.enrollments.values()
               if e["session_id"] == session_id
               and e["enrollment_status"] in SEAT_HOLDING_STATUSES)


def sync_session_seats(session):
    available = session["capacity"] - active_seat_holders(session["id"])
    if available != session["available_seats"]:
        session["available_seats"] = available
        touch(session)


# ---------------------------------------------------------------------------
# Firm element plan progress hours
# ---------------------------------------------------------------------------
def recompute_plan(plan):
    rep_id = plan["rep_id"]
    certified = Decimal("0")
    in_progress = Decimal("0")
    for e in store.enrollments.values():
        if e["rep_id"] != rep_id:
            continue
        c = store.contents.get(e["content_id"])
        if c is None or c["ce_category"] != "FIRM_ELEMENT":
            continue
        if e["enrollment_status"] == "COMPLETED" and e["completed_at"] is not None \
                and e["completed_at"].year == plan["plan_year"]:
            certified += c["credit_hours"]
        elif e["enrollment_status"] == "IN_PROGRESS":
            # IN_PROGRESS rows carry no completed_at: no plan-year filter.
            in_progress += c["credit_hours"]
    certified = q2(certified)
    projected = q2(certified + in_progress)
    if certified != plan["certified_hours"] or projected != plan["projected_hours"]:
        plan["certified_hours"] = certified
        plan["projected_hours"] = projected
        touch(plan)


def recompute_plans_for_rep(rep_id):
    for plan in store.plans.values():
        if plan["rep_id"] == rep_id \
                and plan["plan_status"] in ("PLAN_PUBLISHED", "CLOSED"):
            recompute_plan(plan)


def compute_required_hours(rep, plan_year):
    """firm_element_required_hours: base -> capped surcharge -> excess -> floor."""
    base = BASE_HOURS_BY_TIER[rep["role_tier"]]
    product_count = sum(
        1 for p in store.products.values()
        if p["product_status"] in ("LAUNCHED", "WITHDRAWN")
        and p["launched_at"] is not None
        and p["launched_at"].year == plan_year)
    surcharge = PER_PRODUCT_SURCHARGE * min(product_count, SURCHARGE_CAP)
    required = base + surcharge - rep["prior_year_excess_hours"]
    if required < MIN_REQUIRED_HOURS:
        required = MIN_REQUIRED_HOURS
    return required


# ---------------------------------------------------------------------------
# State CE license hour counters
# ---------------------------------------------------------------------------
def license_window_contents(lic):
    out = []
    for e in store.enrollments.values():
        if e["rep_id"] != lic["rep_id"] or e["enrollment_status"] != "COMPLETED" \
                or e["completed_at"] is None:
            continue
        c = store.contents.get(e["content_id"])
        if c is None or c["ce_category"] != "STATE_INSURANCE":
            continue
        if lic["period_start"] <= e["completed_at"] < lic["period_end"]:
            out.append(c)
    return out


def recompute_license(lic):
    courses = license_window_contents(lic)
    strict = q2(sum((c["credit_hours"] for c in courses), Decimal("0")))
    carried = lic["carried_excess_hours"]
    if carried > CARRYOVER_CAP_HOURS:
        carried = CARRYOVER_CAP_HOURS
    effective = q2(strict + carried)
    # Per-course round-half-up to 0.5 FIRST, then exact sum (pinned order).
    reported = q2(sum((round_to_half(c["credit_hours"]) for c in courses), Decimal("0")))
    if strict != lic["earned_hours_strict"] \
            or effective != lic["earned_hours_effective"] \
            or reported != lic["reported_hours"]:
        lic["earned_hours_strict"] = strict
        lic["earned_hours_effective"] = effective
        lic["reported_hours"] = reported
        touch(lic)


def recompute_licenses_for_rep(rep_id):
    for lic in store.licenses.values():
        if lic["rep_id"] == rep_id:
            recompute_license(lic)


# ---------------------------------------------------------------------------
# Product certifications
# ---------------------------------------------------------------------------
def certs_of_rep(rep_id):
    return [c for c in store.certifications.values() if c["rep_id"] == rep_id]


def suspend_cert(cert, reason, actor, detail_suffix):
    cert["cert_status"] = "SUSPENDED"
    cert["suspended_reason"] = reason
    touch(cert)
    audit("CERTIFICATION_STATUS_CHANGED", "ProductCertification", cert["id"],
          actor[0], actor[1],
          "cert_status -> SUSPENDED (%s)" % detail_suffix)


# ---------------------------------------------------------------------------
# Registration cascades
# ---------------------------------------------------------------------------
def lapse_registration(rep, actor):
    """ACTIVE -> INACTIVE_CE, then suspend the rep's CERTIFIED certifications."""
    if rep["registration_status"] == "ACTIVE":
        rep["registration_status"] = "INACTIVE_CE"
        touch(rep)
        audit("REGISTRATION_STATUS_CHANGED", "Representative", rep["id"],
              actor[0], actor[1], "registration_status: ACTIVE -> INACTIVE_CE")
    for cert in certs_of_rep(rep["id"]):
        if cert["cert_status"] == "CERTIFIED":
            suspend_cert(cert, "REGISTRATION_INACTIVE", actor,
                         "REGISTRATION_INACTIVE")


def restore_registration(rep, actor):
    """INACTIVE_CE -> ACTIVE, then reinstate certs suspended for the lapse."""
    if rep["registration_status"] != "INACTIVE_CE":
        return
    rep["registration_status"] = "ACTIVE"
    touch(rep)
    audit("REGISTRATION_STATUS_CHANGED", "Representative", rep["id"],
          actor[0], actor[1], "registration_status: INACTIVE_CE -> ACTIVE")
    for cert in certs_of_rep(rep["id"]):
        if cert["cert_status"] == "SUSPENDED" \
                and cert["suspended_reason"] == "REGISTRATION_INACTIVE":
            product = store.products.get(cert["product_id"])
            content = store.contents.get(product["required_training_content_id"]) \
                if product else None
            if product and product["product_status"] == "LAUNCHED" \
                    and content and content["content_status"] == "APPROVED":
                cert["cert_status"] = "CERTIFIED"
                cert["suspended_reason"] = None
                touch(cert)
                audit("CERTIFICATION_STATUS_CHANGED", "ProductCertification",
                      cert["id"], actor[0], actor[1],
                      "cert_status: SUSPENDED -> CERTIFIED (registration restored)")


def terminate_representative(rep, actor):
    """ComplianceOfficer termination with the full cascade (PRD 3.1)."""
    old_status = rep["registration_status"]
    rep["registration_status"] = "TERMINATED"
    touch(rep)
    affected_sessions = set()
    affected_plan_rep = False
    for e in by_seq(store.enrollments.values()):
        if e["rep_id"] == rep["id"] and e["enrollment_status"] in (
                "ENROLLED", "IN_PROGRESS", "FAILED"):
            e["enrollment_status"] = "CANCELLED"
            touch(e)
            if e["session_id"]:
                affected_sessions.add(e["session_id"])
            affected_plan_rep = True
    for sid in affected_sessions:
        sync_session_seats(store.sessions[sid])
    if affected_plan_rep:
        recompute_plans_for_rep(rep["id"])
    for cert in certs_of_rep(rep["id"]):
        if cert["cert_status"] in ("PENDING_TRAINING", "CERTIFIED"):
            suspend_cert(cert, "REGISTRATION_TERMINATED", actor,
                         "REGISTRATION_TERMINATED")
    for att in store.attestations.values():
        if att["rep_id"] == rep["id"] and att["attestation_status"] == "PENDING":
            att["attestation_status"] = "VOIDED"  # no event of its own
            touch(att)
    audit("REGISTRATION_STATUS_CHANGED", "Representative", rep["id"],
          actor[0], actor[1],
          "registration_status: %s -> TERMINATED" % old_status)


# ---------------------------------------------------------------------------
# Training content retirement cascade
# ---------------------------------------------------------------------------
def retire_content(content, actor):
    content["content_status"] = "RETIRED"
    touch(content)
    affected_sessions = set()
    affected_reps = set()
    for e in by_seq(store.enrollments.values()):
        if e["content_id"] == content["id"] and e["enrollment_status"] in (
                "ENROLLED", "IN_PROGRESS", "FAILED"):
            e["enrollment_status"] = "CANCELLED"
            touch(e)
            if e["session_id"]:
                affected_sessions.add(e["session_id"])
            affected_reps.add(e["rep_id"])
    for s in by_seq(store.sessions.values()):
        if s["content_id"] == content["id"] and s["session_status"] == "SCHEDULED":
            s["session_status"] = "CANCELLED"
            touch(s)
    for sid in affected_sessions:
        sync_session_seats(store.sessions[sid])
    for rid in affected_reps:
        recompute_plans_for_rep(rid)
    for cert in by_seq(store.certifications.values()):
        if cert["cert_status"] != "CERTIFIED":
            continue
        product = store.products.get(cert["product_id"])
        if product and product["required_training_content_id"] == content["id"]:
            suspend_cert(cert, "CONTENT_RETIRED", actor, "CONTENT_RETIRED")
    audit("CONTENT_RETIRED", "TrainingContent", content["id"], actor[0], actor[1],
          "content_status: APPROVED -> RETIRED")


# ---------------------------------------------------------------------------
# Session cancel cascade
# ---------------------------------------------------------------------------
def cancel_session(session):
    session["session_status"] = "CANCELLED"
    touch(session)
    affected_reps = set()
    for e in by_seq(store.enrollments.values()):
        if e["session_id"] == session["id"] and e["enrollment_status"] in (
                "ENROLLED", "IN_PROGRESS"):
            e["enrollment_status"] = "CANCELLED"
            touch(e)
            affected_reps.add(e["rep_id"])
    sync_session_seats(session)
    for rid in affected_reps:
        recompute_plans_for_rep(rid)


# ---------------------------------------------------------------------------
# Enrollment lifecycle side effects
# ---------------------------------------------------------------------------
def cancel_enrollment(enrollment):
    """Shared by the cancel endpoint and retire/terminate/session cascades is
    intentionally NOT used there (they batch) — this is the single-record path."""
    enrollment["enrollment_status"] = "CANCELLED"
    touch(enrollment)
    if enrollment["session_id"]:
        sync_session_seats(store.sessions[enrollment["session_id"]])
    recompute_plans_for_rep(enrollment["rep_id"])


def fulfill_regulatory_assignment(rep, enrollment, actor):
    """regulatory_completion_selector: earliest due_at, tie-break created_at."""
    candidates = [a for a in store.assignments.values()
                  if a["rep_id"] == rep["id"] and a["assignment_status"] in
                  ("ASSIGNED", "OVERDUE", "LAPSED")]
    if not candidates:
        return  # empty candidate set -> completion succeeds as a no-op
    candidates.sort(key=lambda a: (a["due_at"], a["created_at"], a["_seq"]))
    assignment = candidates[0]
    was_lapsed = assignment["assignment_status"] == "LAPSED"
    assignment["assignment_status"] = "COMPLETED"
    assignment["enrollment_id"] = enrollment["id"]
    assignment["completed_at"] = clock_now()
    touch(assignment)
    audit("ASSIGNMENT_COMPLETED", "RegulatoryAssignment", assignment["id"],
          actor[0], actor[1],
          "assignment_status -> COMPLETED by enrollment %s" % enrollment["id"])
    if was_lapsed:
        remaining = [a for a in store.assignments.values()
                     if a["rep_id"] == rep["id"]
                     and a["assignment_status"] == "LAPSED"]
        if not remaining:
            restore_registration(rep, actor)


def certify_products_for_completion(rep, enrollment, content, actor):
    for cert in by_seq(certs_of_rep(rep["id"])):
        if cert["cert_status"] != "PENDING_TRAINING":
            continue
        product = store.products.get(cert["product_id"])
        if product and product["required_training_content_id"] == content["id"]:
            cert["cert_status"] = "CERTIFIED"
            cert["enrollment_id"] = enrollment["id"]
            cert["certified_at"] = clock_now()
            touch(cert)
            audit("CERTIFICATION_STATUS_CHANGED", "ProductCertification",
                  cert["id"], actor[0], actor[1],
                  "cert_status: PENDING_TRAINING -> CERTIFIED")


def complete_enrollment(enrollment, score, actor):
    """Pass -> COMPLETED + category credit cascades; fail -> FAILED."""
    content = store.contents[enrollment["content_id"]]
    rep = store.representatives[enrollment["rep_id"]]
    enrollment["attempt_count"] += 1
    enrollment["last_score"] = score
    if score >= content["min_passing_score"]:
        enrollment["enrollment_status"] = "COMPLETED"
        enrollment["completed_at"] = clock_now()
        touch(enrollment)
        category = content["ce_category"]
        if category == "FIRM_ELEMENT":
            recompute_plans_for_rep(rep["id"])
        elif category == "REGULATORY_ELEMENT":
            fulfill_regulatory_assignment(rep, enrollment, actor)
        elif category == "PRODUCT":
            certify_products_for_completion(rep, enrollment, content, actor)
        elif category == "STATE_INSURANCE":
            recompute_licenses_for_rep(rep["id"])
        audit("ENROLLMENT_COMPLETED", "Enrollment", enrollment["id"],
              actor[0], actor[1],
              "enrollment_status: IN_PROGRESS -> COMPLETED; score=%d" % score)
    else:
        enrollment["enrollment_status"] = "FAILED"
        touch(enrollment)
        if enrollment["session_id"]:
            # FAILED holds no seat.
            sync_session_seats(store.sessions[enrollment["session_id"]])
        recompute_plans_for_rep(rep["id"])


def void_enrollment(enrollment, justification, actor):
    """Audit-correction void: reverse everything the completion caused."""
    rep = store.representatives[enrollment["rep_id"]]
    content = store.contents[enrollment["content_id"]]
    completed_at = enrollment["completed_at"]
    enrollment["enrollment_status"] = "VOIDED"
    touch(enrollment)
    if enrollment["session_id"]:
        sync_session_seats(store.sessions[enrollment["session_id"]])
    category = content["ce_category"]
    if category == "FIRM_ELEMENT":
        recompute_plans_for_rep(rep["id"])
        year = completed_at.year if completed_at is not None else None
        for plan in by_seq(store.plans.values()):
            if plan["rep_id"] == rep["id"] and plan["plan_year"] == year \
                    and plan["plan_status"] == "CLOSED" \
                    and plan["certified_hours"] < plan["required_hours"]:
                plan["plan_status"] = "PLAN_PUBLISHED"
                plan["closed_at"] = None
                touch(plan)
                for att in by_seq(store.attestations.values()):
                    if att["plan_id"] == plan["id"] \
                            and att["attestation_status"] == "ATTESTED":
                        att["attestation_status"] = "VOIDED"
                        touch(att)
                        audit("ATTESTATION_VOIDED", "AnnualAttestation",
                              att["id"], actor[0], actor[1],
                              "attestation_status: ATTESTED -> VOIDED "
                              "(plan reopened)")
                audit("PLAN_REOPENED", "FirmElementPlan", plan["id"],
                      actor[0], actor[1],
                      "plan_status: CLOSED -> PLAN_PUBLISHED (certified_hours "
                      "fell below required_hours)")
    elif category == "STATE_INSURANCE":
        recompute_licenses_for_rep(rep["id"])
    elif category == "REGULATORY_ELEMENT":
        for a in by_seq(store.assignments.values()):
            if a["enrollment_id"] == enrollment["id"] \
                    and a["assignment_status"] == "COMPLETED":
                now = clock_now()
                if now <= a["due_at"]:
                    a["assignment_status"] = "ASSIGNED"
                elif now <= a["lapse_after"]:
                    a["assignment_status"] = "OVERDUE"
                else:
                    a["assignment_status"] = "LAPSED"
                a["enrollment_id"] = None
                a["completed_at"] = None
                touch(a)
                if a["assignment_status"] == "LAPSED":
                    # A fresh lapse re-runs the registration cascade.
                    lapse_registration(rep, actor)
                break
    elif category == "PRODUCT":
        for cert in by_seq(store.certifications.values()):
            if cert["enrollment_id"] == enrollment["id"] \
                    and cert["cert_status"] == "CERTIFIED":
                suspend_cert(cert, "TRAINING_VOIDED", actor, "TRAINING_VOIDED")
    audit("ENROLLMENT_VOIDED", "Enrollment", enrollment["id"],
          actor[0], actor[1],
          "enrollment_status: COMPLETED -> VOIDED; justification recorded")


# ---------------------------------------------------------------------------
# Product launch fan-out
# ---------------------------------------------------------------------------
def launch_product(product, actor):
    product["product_status"] = "LAUNCHED"
    product["launched_at"] = clock_now()
    touch(product)
    audit("PRODUCT_LAUNCHED", "ProductOffering", product["id"],
          actor[0], actor[1], "product_status: PROPOSED -> LAUNCHED")
    eligible = [r for r in store.representatives.values()
                if r["registration_status"] == "ACTIVE"]
    # created_at ASC, tie-break crd_number ASC
    eligible.sort(key=lambda r: (r["created_at"], r["crd_number"]))
    for rep in eligible:
        cert = base_record()
        cert.update({
            "rep_id": rep["id"],
            "product_id": product["id"],
            "enrollment_id": None,
            "cert_status": "PENDING_TRAINING",
            "certified_at": None,
            "suspended_reason": None,
        })
        store.certifications[cert["id"]] = cert


def withdraw_product(product, actor):
    product["product_status"] = "WITHDRAWN"
    touch(product)
    for cert in by_seq(store.certifications.values()):
        if cert["product_id"] == product["id"] and cert["cert_status"] in (
                "PENDING_TRAINING", "CERTIFIED"):
            suspend_cert(cert, "PRODUCT_WITHDRAWN", actor, "PRODUCT_WITHDRAWN")


# ---------------------------------------------------------------------------
# Enforcement sweep (pinned phase order: sessions, enrollments, assignments,
# licenses)
# ---------------------------------------------------------------------------
def run_sweep():
    now = clock_now()
    sessions_marked_delivered = 0
    enrollments_expired = 0
    assignments_marked_overdue = 0
    assignments_lapsed = 0
    licenses_lapsed = 0

    # Phase 1: sessions whose end_at has been reached or passed -> DELIVERED
    for s in by_seq(store.sessions.values()):
        if s["session_status"] == "SCHEDULED" and s["end_at"] <= now:
            s["session_status"] = "DELIVERED"
            touch(s)
            sessions_marked_delivered += 1

    # Phase 2: enrollments strictly past expires_at -> EXPIRED (seat released)
    affected_reps = set()
    for e in by_seq(store.enrollments.values()):
        if e["enrollment_status"] in ("ENROLLED", "IN_PROGRESS") \
                and e["expires_at"] < now:
            e["enrollment_status"] = "EXPIRED"
            touch(e)
            if e["session_id"]:
                sync_session_seats(store.sessions[e["session_id"]])
            affected_reps.add(e["rep_id"])
            enrollments_expired += 1
    for rid in affected_reps:
        recompute_plans_for_rep(rid)

    # Phase 3: assignments -> OVERDUE / LAPSED (+ registration cascade)
    for a in by_seq(store.assignments.values()):
        if a["assignment_status"] == "ASSIGNED" \
                and a["due_at"] < now <= a["lapse_after"]:
            a["assignment_status"] = "OVERDUE"
            touch(a)
            assignments_marked_overdue += 1
    for a in by_seq(store.assignments.values()):
        if a["assignment_status"] in ("ASSIGNED", "OVERDUE") \
                and now > a["lapse_after"]:
            a["assignment_status"] = "LAPSED"
            touch(a)
            rep = store.representatives.get(a["rep_id"])
            if rep is not None:
                lapse_registration(rep, SYSTEM_ACTOR)
            audit("ASSIGNMENT_LAPSED", "RegulatoryAssignment", a["id"],
                  SYSTEM_ACTOR[0], SYSTEM_ACTOR[1],
                  "assignment_status -> LAPSED (deadline enforcement)")
            assignments_lapsed += 1

    # Phase 4: licenses past period_end with insufficient effective hours
    for lic in by_seq(store.licenses.values()):
        if lic["license_status"] == "ACTIVE":
            recompute_license(lic)
            if now > lic["period_end"] \
                    and lic["earned_hours_effective"] < lic["required_hours"]:
                lic["license_status"] = "LAPSED"
                touch(lic)
                licenses_lapsed += 1

    sweep_id = new_id()
    audit("ENFORCEMENT_SWEEP_RUN", "EnforcementSweep", sweep_id,
          SYSTEM_ACTOR[0], SYSTEM_ACTOR[1],
          "sweep epoch: sessions_marked_delivered=%d enrollments_expired=%d "
          "assignments_marked_overdue=%d assignments_lapsed=%d "
          "licenses_lapsed=%d" % (sessions_marked_delivered, enrollments_expired,
                                  assignments_marked_overdue, assignments_lapsed,
                                  licenses_lapsed))

    return {
        "sessions_marked_delivered": sessions_marked_delivered,
        "enrollments_expired": enrollments_expired,
        "assignments_marked_overdue": assignments_marked_overdue,
        "assignments_lapsed": assignments_lapsed,
        "licenses_lapsed": licenses_lapsed,
    }


# ---------------------------------------------------------------------------
# Shared small factories
# ---------------------------------------------------------------------------
def enrollment_expires_at(created):
    return created + timedelta(days=ENROLLMENT_VALIDITY_DAYS)


def assignment_due_at(created):
    return created + timedelta(days=ASSIGNMENT_WINDOW_DAYS)


def assignment_lapse_after(due_at):
    return due_at + timedelta(days=GRACE_DAYS)
