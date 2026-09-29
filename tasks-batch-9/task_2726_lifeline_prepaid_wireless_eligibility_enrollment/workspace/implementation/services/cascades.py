"""Cross-row cascades: de-enrollment, duplicate-flag release, reinstatement,
claim pricing and the per-carrier compliance sweep.

Every row a cascade touches has its updated_at refreshed and its version
incremented, including rows the caller never named (PRD section 2.10).
"""
from datetime import timedelta

import db
from db import now, touch
from services import calc, derive


# ------------------------------------------------------- duplicate holds

def release_duplicate_holds(address):
    """When a dwelling's duplicate flag clears, every applicant held there is
    released in the same request by a simple existence test."""
    instant = now()
    for sub in derive.subscribers_at_address(address["id"]):
        if sub["status"] != "DUPLICATE_HOLD":
            continue
        if derive.has_usable_confirmed_check(sub["id"], instant):
            sub["status"] = "VERIFIED_ELIGIBLE"
        else:
            sub["status"] = "PROSPECT"
        touch(sub)


def clear_duplicate_flag(address):
    """The shared body of every flag-clearing arm: slots recompute to 1 and the
    multi-household paperwork is dropped."""
    address["declared_household_count"] = None
    address["independent_household_worksheet_ref"] = None


# ------------------------------------------------- de-enrollment cascade

def de_enroll(enrollment, reason, actor_ref, skip_address_id=None):
    """The canonical de-enrollment cascade of PRD section 3.4. Every route that
    stops a benefit fires exactly this one."""
    instant = now()
    enrollment["benefit_status"] = "DE_ENROLLED"
    enrollment["benefit_end_date"] = instant
    enrollment["de_enrolled_at"] = instant
    enrollment["de_enrolled_by_ref"] = actor_ref
    enrollment["de_enrollment_reason"] = reason
    enrollment["appeal_deadline_at"] = calc.appeal_deadline(instant)

    reclaimed_device = None
    if enrollment["device_status"] == "DEVICE_ISSUED":
        enrollment["device_status"] = "RECLAIM_PENDING"
        for dev in derive.devices_of_enrollment(enrollment["id"]):
            if dev["status"] == "ISSUED":
                reclaimed_device = dev
                break

    address = db.db.addresses.get(enrollment["certified_address_id"])
    if address is not None and address["id"] != skip_address_id:
        if (derive.occupied_benefit_slots(address["id"]) == 0
                and address["status"] == "DUPLICATE_FLAGGED"):
            address["status"] = "RESOLVED_SINGLE_HOUSEHOLD"
            clear_duplicate_flag(address)
            touch(address)
            release_duplicate_holds(address)
        else:
            touch(address)

    provider = db.db.providers.get(enrollment["provider_id"])
    if provider is not None:
        touch(provider)

    subscriber = db.db.subscribers.get(enrollment["subscriber_id"])
    if subscriber is not None:
        if subscriber["status"] == "ENROLLED":
            count = derive.de_enrollment_count(subscriber["id"])
            subscriber["status"] = "BARRED" if count >= 2 else "DE_ENROLLED"
        touch(subscriber)

    if reclaimed_device is not None:
        reclaimed_device["status"] = "RECLAIM_PENDING"
        touch(reclaimed_device)
        if provider is not None:
            touch(provider)

    derive.recompute_risk(enrollment)
    touch(enrollment)


# ---------------------------------------------------------- reinstatement

def reinstate(enrollment, actor_ref):
    """Compensating action for an erroneous de-enrollment (PRD section 3.9).
    benefit_start_date is preserved, so port_freeze_until and recert_due_date
    do not move."""
    previous_reason = enrollment["de_enrollment_reason"]
    enrollment["benefit_status"] = "ACTIVE"
    enrollment["benefit_end_date"] = None
    enrollment["de_enrollment_reason"] = None
    enrollment["de_enrolled_at"] = None
    enrollment["de_enrolled_by_ref"] = None
    enrollment["appeal_deadline_at"] = None
    enrollment["usage_status"] = "PENDING_FIRST_USE"
    enrollment["last_usage_at"] = None
    enrollment["non_usage_flagged_at"] = None
    enrollment["cure_deadline_at"] = None
    enrollment["recert_status"] = "NOT_DUE"
    enrollment["recert_notice_sent_at"] = None
    enrollment["recert_response_deadline_at"] = None
    derive.recompute_risk(enrollment)
    touch(enrollment)

    address = db.db.addresses.get(enrollment["certified_address_id"])
    if address is not None:
        touch(address)

    provider = db.db.providers.get(enrollment["provider_id"])
    if provider is not None:
        touch(provider)

    subscriber = db.db.subscribers.get(enrollment["subscriber_id"])
    if subscriber is not None:
        if subscriber["status"] == "DE_ENROLLED":
            subscriber["status"] = "ENROLLED"
        touch(subscriber)

    if previous_reason == "AUDIT_INELIGIBLE":
        reverse_audit_failure(enrollment)


def reverse_audit_failure(enrollment):
    """Unwind the money that followed from an audit-driven de-enrollment."""
    candidates = []
    for sample in derive.samples_of_enrollment(enrollment["id"]):
        if sample["status"] != "ADJUDICATED_FAIL":
            continue
        claim = db.db.claims.get(sample["claim_id"])
        if claim is None or claim["status"] != "AUDIT_FAILED":
            continue
        candidates.append(sample)
    if not candidates:
        return
    sample = max(candidates, key=lambda s: (s["created_at"], s["_seq"]))
    sample["status"] = "ADJUDICATED_PASS"
    sample["finding"] = "COMPLIANT"
    sample["disallowed_support_cents"] = 0
    touch(sample)

    claim = db.db.claims.get(sample["claim_id"])
    if claim is None:
        return
    if derive.failed_sample_count(claim["id"]) == 0 and claim["status"] == "AUDIT_FAILED":
        claim["status"] = "AUDIT_PASSED"
        claim["recoupment_amount_cents"] = 0
        claim["penalty_cents"] = 0
        claim["net_payable_cents"] = claim["final_amount_cents"] or 0
        touch(claim)

    provider = db.db.providers.get(claim["provider_id"])
    if provider is None:
        return
    touch(provider)
    if not derive.audit_hold_flag(provider["id"]):
        for other in db.by_created(derive.claims_of_provider(provider["id"])):
            if other["status"] == "HELD":
                other["status"] = "FILED"
                touch(other)


# --------------------------------------------------------- claim pricing

def price_provisional(provider_id, service_month, instant):
    """Selects benefits ACTIVE at the instant the draft is created whose
    benefit_start_date is on or before the earlier of today's date and the
    last day of the service month."""
    first, last, days_in_month = calc.month_bounds(service_month)
    horizon = min(instant.date(), last)
    total = 0
    count = 0
    for enrollment in db.by_created(derive.enrollments_of_provider(provider_id)):
        if enrollment["benefit_status"] != "ACTIVE":
            continue
        start_date = enrollment["benefit_start_date"].date()
        if start_date > horizon:
            continue
        support_start = max(start_date, first)
        support_days = (horizon - support_start).days + 1
        if support_days < 1:
            continue
        subscriber = db.db.subscribers.get(enrollment["subscriber_id"])
        tribal = bool(subscriber and subscriber["tribal_lands_flag"])
        rate = calc.monthly_rate_cents(tribal, enrollment["service_type"])
        total += calc.support_line_cents(rate, support_days, days_in_month)
        count += 1
    return total, count


def price_final(provider_id, service_month):
    """Every benefit of the carrier that had at least one day of ACTIVE benefit
    inside the service month, including benefits de-enrolled mid-month and
    benefits that ported in during the month. Returns (total, count, lines)."""
    first, last, days_in_month = calc.month_bounds(service_month)
    total = 0
    lines = {}
    for enrollment in db.by_created(derive.enrollments_of_provider(provider_id)):
        start_date = enrollment["benefit_start_date"].date()
        support_end = last
        if enrollment["benefit_end_date"] is not None:
            ended = enrollment["benefit_end_date"].date() - timedelta(days=1)
            if ended < support_end:
                support_end = ended
        support_start = max(start_date, first)
        support_days = (support_end - support_start).days + 1
        if support_days < 1:
            continue
        subscriber = db.db.subscribers.get(enrollment["subscriber_id"])
        tribal = bool(subscriber and subscriber["tribal_lands_flag"])
        rate = calc.monthly_rate_cents(tribal, enrollment["service_type"])
        line = calc.support_line_cents(rate, support_days, days_in_month)
        lines[enrollment["id"]] = line
        total += line
    return total, len(lines), lines


# ------------------------------------------------------- compliance sweep

def compliance_sweep(provider, actor_ref):
    """Four steps per benefit in a fixed order; each step re-reads what the
    previous one wrote (PRD section 3.5)."""
    instant = now()
    visit_order = sorted(
        [e for e in derive.enrollments_of_provider(provider["id"])
         if e["benefit_status"] == "ACTIVE"],
        key=lambda e: (e["benefit_start_date"], e["created_at"], e["_seq"]),
    )
    flagged = []
    cure_expired = []
    noticed = []
    non_response = []

    for enrollment in visit_order:
        # Step one: detect non-usage and flag it.
        if (enrollment["benefit_status"] == "ACTIVE"
                and enrollment["usage_status"] in ("PENDING_FIRST_USE", "USING")):
            anchor = enrollment["last_usage_at"] or enrollment["benefit_start_date"]
            if calc.idle_days(instant, anchor) >= calc.NON_USAGE_IDLE_DAYS:
                enrollment["usage_status"] = "NON_USAGE_FLAGGED"
                enrollment["non_usage_flagged_at"] = instant
                enrollment["cure_deadline_at"] = calc.cure_deadline(instant)
                derive.recompute_risk(enrollment)
                touch(enrollment)
                flagged.append(enrollment["id"])

        # Step two: expire an already-open cure and de-enroll for non-usage.
        if (enrollment["benefit_status"] == "ACTIVE"
                and enrollment["usage_status"] == "NON_USAGE_FLAGGED"
                and enrollment["cure_deadline_at"] is not None
                and instant > enrollment["cure_deadline_at"]):
            enrollment["usage_status"] = "CURE_EXPIRED"
            de_enroll(enrollment, "NON_USAGE", actor_ref)
            cure_expired.append(enrollment["id"])

        # Step three: issue the recertification notice.
        if (enrollment["benefit_status"] == "ACTIVE"
                and enrollment["recert_status"] == "NOT_DUE"
                and enrollment["recert_due_date"] is not None
                and instant >= calc.recert_notice_opens_at(enrollment["recert_due_date"])):
            enrollment["recert_status"] = "NOTICED"
            enrollment["recert_notice_sent_at"] = instant
            enrollment["recert_response_deadline_at"] = \
                calc.recert_response_deadline(instant)
            derive.recompute_risk(enrollment)
            touch(enrollment)
            noticed.append(enrollment["id"])

        # Step four: de-enroll for recertification non-response.
        if (enrollment["benefit_status"] == "ACTIVE"
                and enrollment["recert_status"] == "NOTICED"
                and enrollment["recert_response_deadline_at"] is not None
                and instant > enrollment["recert_response_deadline_at"]):
            enrollment["recert_status"] = "NON_RESPONSIVE"
            de_enroll(enrollment, "RECERT_NON_RESPONSE", actor_ref)
            non_response.append(enrollment["id"])

    return {
        "swept_at": db.fmt_dt(instant),
        "evaluated_enrollment_count": len(visit_order),
        "non_usage_flagged_enrollment_ids": flagged,
        "cure_expired_de_enrolled_enrollment_ids": cure_expired,
        "recert_noticed_enrollment_ids": noticed,
        "recert_non_response_de_enrolled_enrollment_ids": non_response,
    }
