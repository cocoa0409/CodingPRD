"""Computed-field calculations and per-entity serializers.

All derived analytics (ledgers, revenue, progress, commissions) are computed
live from the current store state and logical clock at serialization time.
"""
from store import (
    fmt_dt, now, add_days,
    creators, courses, lessons, price_plans, coupons, affiliates,
    enrollments, invoices, payouts,
)

TERMINAL_BILLING = {"CANCELLED", "REFUNDED"}


# --------------------------------------------------------------------------
# Cross-entity lookups
# --------------------------------------------------------------------------
def course_of_enrollment(enr):
    return courses.get(enr["course_id"])


def creator_invoice_tuples(creator_id):
    """Yield (invoice, enrollment, course) for every invoice under a creator."""
    out = []
    for inv in invoices.values():
        enr = enrollments.get(inv["enrollment_id"])
        if not enr:
            continue
        crs = courses.get(enr["course_id"])
        if crs and crs["creator_id"] == creator_id:
            out.append((inv, enr, crs))
    return out


def invoice_window_end(inv, crs):
    if inv["paid_at"] is None:
        return None
    return add_days(inv["paid_at"], crs["refund_window_days"])


def invoice_is_settled(inv, crs):
    """PAID and past its refund window (clock strictly after window end)."""
    if inv["status"] != "PAID":
        return False
    end = invoice_window_end(inv, crs)
    return end is not None and now() > end


def invoice_is_pending_window(inv, crs):
    """PAID and still inside its refund window (clock at or before window end)."""
    if inv["status"] != "PAID":
        return False
    end = invoice_window_end(inv, crs)
    return end is not None and now() <= end


# --------------------------------------------------------------------------
# Course computed fields
# --------------------------------------------------------------------------
def course_published_lessons(course_id):
    return [l for l in lessons.values()
            if l["course_id"] == course_id and l["is_published"]]


def course_published_lesson_count(course_id):
    return len(course_published_lessons(course_id))


def course_required_quiz_count(course_id):
    return len([l for l in course_published_lessons(course_id) if l["is_quiz_required"]])


def course_enrollments(course_id):
    return [e for e in enrollments.values() if e["course_id"] == course_id]


def course_analytics(course):
    cid = course["id"]
    enrs = course_enrollments(cid)
    enrollment_count = len([e for e in enrs if e["billing_status"] not in TERMINAL_BILLING])
    completion_count = len([e for e in enrs if e["access_status"] == "COMPLETED"])
    gross = 0
    net_settled = 0
    for inv in invoices.values():
        enr = enrollments.get(inv["enrollment_id"])
        if not enr or enr["course_id"] != cid:
            continue
        if inv["status"] == "PAID":
            gross += inv["amount_cents"]
            if invoice_is_settled(inv, course):
                net_settled += inv["creator_net_cents"]
    return {
        "published_lesson_count": course_published_lesson_count(cid),
        "required_quiz_lesson_count": course_required_quiz_count(cid),
        "enrollment_count": enrollment_count,
        "completion_count": completion_count,
        "gross_revenue_cents": gross,
        "net_settled_revenue_cents": net_settled,
    }


# --------------------------------------------------------------------------
# Creator ledger
# --------------------------------------------------------------------------
def creator_ledger(creator):
    cid = creator["id"]
    lifetime_gross = 0
    lifetime_refunded = 0
    lifetime_net = 0
    pending_net = 0
    settled_net = 0
    for inv, enr, crs in creator_invoice_tuples(cid):
        if inv["status"] == "PAID":
            lifetime_gross += inv["amount_cents"]
            lifetime_net += inv["creator_net_cents"]
            if invoice_is_pending_window(inv, crs):
                pending_net += inv["creator_net_cents"]
            elif invoice_is_settled(inv, crs):
                settled_net += inv["creator_net_cents"]
        elif inv["status"] == "REFUNDED":
            lifetime_refunded += inv["amount_cents"]
    reserved = 0
    paid = 0
    for p in payouts.values():
        if p["creator_id"] != cid:
            continue
        if p["status"] in ("REQUESTED", "PROCESSING"):
            reserved += p["amount_cents"]
        elif p["status"] == "PAID":
            paid += p["amount_cents"]
    available = settled_net - paid - reserved
    if available < 0:
        available = 0
    return {
        "lifetime_gross_cents": lifetime_gross,
        "lifetime_refunded_cents": lifetime_refunded,
        "lifetime_creator_net_cents": lifetime_net,
        "pending_net_cents": pending_net,
        "settled_net_cents": settled_net,
        "earnings_reserved_cents": reserved,
        "earnings_paid_cents": paid,
        "available_for_payout_cents": available,
    }


def creator_available_balance(creator):
    return creator_ledger(creator)["available_for_payout_cents"]


# --------------------------------------------------------------------------
# Coupon computed
# --------------------------------------------------------------------------
def coupon_redeemed_count(coupon_id):
    return len([e for e in enrollments.values()
                if e.get("coupon_id") == coupon_id
                and e["billing_status"] not in TERMINAL_BILLING])


# --------------------------------------------------------------------------
# Affiliate computed
# --------------------------------------------------------------------------
def affiliate_analytics(affiliate):
    aid = affiliate["id"]
    pending = 0
    clawed = 0
    referred = 0
    for inv in invoices.values():
        enr = enrollments.get(inv["enrollment_id"])
        if not enr or enr.get("affiliate_id") != aid:
            continue
        if inv["status"] == "PAID":
            pending += inv["affiliate_commission_cents"] or 0
            referred += inv["amount_cents"]
        elif inv["status"] == "REFUNDED":
            clawed += inv["affiliate_commission_cents"] or 0
    return {
        "commission_pending_cents": pending,
        "commission_clawed_back_cents": clawed,
        "referred_revenue_cents": referred,
    }


# --------------------------------------------------------------------------
# Enrollment computed
# --------------------------------------------------------------------------
def enrollment_completed_lesson_count(enr):
    return len([lid for lid in enr["_completed"]
                if lid in lessons and lessons[lid]["is_published"]])


def enrollment_is_mastery_complete(enr):
    course = course_of_enrollment(enr)
    if course is None:
        return False
    published = course_published_lessons(course["id"])
    if len(published) == 0:
        return False
    if enrollment_completed_lesson_count(enr) != len(published):
        return False
    for lesson in published:
        if not lesson["is_quiz_required"]:
            continue
        ok = any(qa for qa in _enrollment_quiz_attempts(enr["id"])
                 if qa["lesson_id"] == lesson["id"] and qa["passed"])
        if not ok:
            return False
    return True


def _enrollment_quiz_attempts(enrollment_id):
    from store import quiz_attempts
    return [qa for qa in quiz_attempts.values() if qa["enrollment_id"] == enrollment_id]


def enrollment_computed(enr):
    course = course_of_enrollment(enr)
    published_count = course_published_lesson_count(enr["course_id"]) if course else 0
    completed = enrollment_completed_lesson_count(enr)
    raw_progress = 0
    if published_count > 0:
        raw_progress = (completed * 100) // published_count
    collected = sum(inv["amount_cents"] for inv in invoices.values()
                    if inv["enrollment_id"] == enr["id"] and inv["status"] == "PAID")
    plan = price_plans.get(enr["price_plan_id"])
    community = (
        enr["access_status"] in ("ACTIVE", "COMPLETED")
        and bool(plan and plan.get("grants_community"))
        and bool(course and course.get("community_enabled"))
    )
    return {
        "completed_lesson_count": completed,
        "raw_progress_pct": raw_progress,
        "is_mastery_complete": enrollment_is_mastery_complete(enr),
        "collected_total_cents": collected,
        "community_access": community,
    }


# --------------------------------------------------------------------------
# Base serialization
# --------------------------------------------------------------------------
def _base(e, with_version=True, with_updated=True):
    out = {"id": e["id"], "created_at": fmt_dt(e["_created_dt"])}
    if with_updated:
        out["updated_at"] = fmt_dt(e["_updated_dt"])
    if with_version:
        out["version"] = e["version"]
    return out


# --------------------------------------------------------------------------
# Per-entity serializers
# --------------------------------------------------------------------------
def ser_creator(e):
    out = _base(e)
    out.update({
        "email": e["email"],
        "display_name": e["display_name"],
        "status": e["status"],
    })
    out.update(creator_ledger(e))
    return out


def ser_student(e):
    out = _base(e)
    out.update({"email": e["email"], "full_name": e["full_name"]})
    return out


def ser_course(e):
    out = _base(e)
    out.update({
        "creator_id": e["creator_id"],
        "title": e["title"],
        "status": e["status"],
        "refund_window_days": e["refund_window_days"],
        "community_enabled": e["community_enabled"],
        "welcome_email_subject": e["welcome_email_subject"],
    })
    out.update(course_analytics(e))
    return out


def ser_lesson(e):
    out = _base(e)
    out.update({
        "course_id": e["course_id"],
        "title": e["title"],
        "position": e["position"],
        "is_published": e["is_published"],
        "drip_offset_days": e["drip_offset_days"],
        "is_quiz_required": e["is_quiz_required"],
        "quiz_passing_score": e["quiz_passing_score"],
    })
    return out


def ser_price_plan(e):
    out = _base(e)
    out.update({
        "course_id": e["course_id"],
        "plan_type": e["plan_type"],
        "amount_cents": e["amount_cents"],
        "billing_interval_days": e["billing_interval_days"],
        "num_installments": e["num_installments"],
        "grants_community": e["grants_community"],
        "status": e["status"],
    })
    return out


def ser_coupon(e):
    out = _base(e)
    out.update({
        "course_id": e["course_id"],
        "code": e["code"],
        "discount_type": e["discount_type"],
        "discount_value": e["discount_value"],
        "min_purchase_cents": e["min_purchase_cents"],
        "max_redemptions": e["max_redemptions"],
        "redeemed_count": coupon_redeemed_count(e["id"]),
        "starts_at": fmt_dt(e["starts_at"]),
        "expires_at": fmt_dt(e["expires_at"]),
        "status": e["status"],
    })
    return out


def ser_affiliate(e):
    out = _base(e)
    out.update({
        "creator_id": e["creator_id"],
        "code": e["code"],
        "commission_pct": e["commission_pct"],
        "status": e["status"],
    })
    out.update(affiliate_analytics(e))
    return out


def ser_enrollment(e):
    out = _base(e)
    out.update({
        "student_id": e["student_id"],
        "course_id": e["course_id"],
        "price_plan_id": e["price_plan_id"],
        "coupon_id": e["coupon_id"],
        "affiliate_id": e["affiliate_id"],
        "access_status": e["access_status"],
        "billing_status": e["billing_status"],
        "activated_at": fmt_dt(e["activated_at"]),
        "list_price_cents": e["list_price_cents"],
        "discount_cents": e["discount_cents"],
        "initial_charge_cents": e["initial_charge_cents"],
        "scheduled_total_cents": e["scheduled_total_cents"],
        "certificate_serial": e["certificate_serial"],
        "certificate_issued_at": fmt_dt(e["certificate_issued_at"]),
    })
    out.update(enrollment_computed(e))
    return out


def ser_invoice(e):
    out = _base(e)
    out.update({
        "enrollment_id": e["enrollment_id"],
        "sequence_index": e["sequence_index"],
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "cycle_start": fmt_dt(e["cycle_start"]),
        "cycle_end": fmt_dt(e["cycle_end"]),
        "status": e["status"],
        "paid_at": fmt_dt(e["paid_at"]),
        "refunded_at": fmt_dt(e["refunded_at"]),
        "platform_fee_cents": e["platform_fee_cents"],
        "affiliate_commission_cents": e["affiliate_commission_cents"],
        "creator_net_cents": e["creator_net_cents"],
    })
    return out


def ser_payout(e):
    out = _base(e)
    out.update({
        "creator_id": e["creator_id"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
    })
    return out


def ser_quiz(e):
    # QuizAttempt is an immutable event record: only id and created_at from base.
    out = _base(e, with_version=False, with_updated=False)
    out.update({
        "enrollment_id": e["enrollment_id"],
        "lesson_id": e["lesson_id"],
        "score": e["score"],
        "passed": e["passed"],
    })
    return out
