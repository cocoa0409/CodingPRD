"""Pinned calculations: scope resolution, proration, usernames, scoring, splits.

Every ordering, rounding direction and boundary comparison here is transcribed
from PRD sections 2.8, 2.10, 3.5, 3.6, 3.7 and 3.8.
"""
import datetime
import decimal
import re
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import store
from errors import ApiError

# --------------------------------------------------------------------------
# Grade-band mapping (constants of sync_scope_resolution)
# --------------------------------------------------------------------------
def band_for_grade(grade_level):
    """District standard mapping; None when the grade falls outside it."""
    if grade_level is None:
        return None
    if 0 <= grade_level <= 5:
        return "ELEMENTARY"
    if 6 <= grade_level <= 8:
        return "MIDDLE"
    if 9 <= grade_level <= 12:
        return "HIGH"
    return None


def subject_band(account_or_subject_type, subject, school):
    """Grade band of a provisioning subject: student by grade, teacher by building."""
    if account_or_subject_type == "STUDENT":
        return band_for_grade(subject.get("grade_level"))
    return school.get("grade_band")


# --------------------------------------------------------------------------
# Term day arithmetic and the per-seat rate (sync_seat_charge)
# --------------------------------------------------------------------------
def as_date(value):
    if isinstance(value, datetime.date):
        return value
    return store.parse_date(value)


def term_total_days(term):
    start = as_date(term["start_date"])
    end = as_date(term["end_date"])
    return (end - start).days + 1


def remaining_days(term, day):
    end = as_date(term["end_date"])
    remaining = (end - as_date(day)).days + 1
    return remaining if remaining >= 1 else 1


def rate_for_date(vendor, term, day):
    """Full list price inside the add/drop window, else prorated with ceil."""
    price = vendor["price_per_seat_cents"]
    day = as_date(day)
    if day <= as_date(term["add_drop_cutoff_date"]):
        return price
    numerator = price * remaining_days(term, day)
    denominator = term_total_days(term)
    if denominator <= 0:
        return price
    return -((-numerator) // denominator)


def refund_amount(account, term, on_date):
    """Standard refund rule: full refund inside the add/drop window, else zero."""
    if as_date(on_date) <= as_date(term["add_drop_cutoff_date"]):
        return account.get("seat_charge_cents") or 0
    return 0


def add_days(day, days):
    """Calendar-day addition on a date, never an arithmetic of hours."""
    return as_date(day) + datetime.timedelta(days=days)


# --------------------------------------------------------------------------
# username_derivation
# --------------------------------------------------------------------------
MAX_LOCALPART_LEN = 20
COLLISION_SUFFIX_START = 2

_NON_LOCAL = re.compile(r"[^a-z0-9]+")


def raw_identifier(vendor, subject_type, subject):
    strategy = vendor["identifier_strategy"]
    if strategy == "SIS_ID":
        if subject_type == "STUDENT":
            return subject.get("sis_student_id")
        return subject.get("sis_staff_id")
    if strategy == "EMAIL_LOCALPART":
        if subject_type == "TEACHER":
            email = subject.get("email") or ""
            if email.strip() == "":
                return None
            return email.split("@", 1)[0]
        last = subject.get("last_name") or ""
        first = subject.get("first_name") or ""
        return last + "." + (first[0] if first else "")
    if strategy == "STATE_ID":
        if subject_type == "TEACHER":
            return None
        return subject.get("state_student_id")
    return None


def normalise_localpart(raw):
    """Steps 2a..2e, in exactly this order (truncate BEFORE the trailing strip)."""
    if raw is None:
        return ""
    value = raw.lower()
    value = _NON_LOCAL.sub(".", value)
    value = value.lstrip(".")
    value = value[:MAX_LOCALPART_LEN]
    value = value.rstrip(".")
    return value


def taken_usernames(vendor_id, exclude_account_id=None):
    taken = set()
    for account in store.app_accounts.values():
        if account.get("_vendor_app_id") != vendor_id:
            continue
        if account["id"] == exclude_account_id:
            continue
        if account.get("seat_status") == "RELEASED":
            continue
        if account.get("username"):
            taken.add(account["username"])
    return taken


def derive_username(vendor, subject_type, subject, exclude_account_id=None):
    localpart = normalise_localpart(raw_identifier(vendor, subject_type, subject))
    if localpart == "":
        raise ApiError("ERR_IDENTIFIER_UNAVAILABLE",
                       "No username can be derived for this subject.")
    domain = vendor["username_domain"]
    taken = taken_usernames(vendor["id"], exclude_account_id)
    candidate = localpart + "@" + domain
    if candidate not in taken:
        return candidate
    suffix = COLLISION_SUFFIX_START
    while True:
        candidate = "%s+%d@%s" % (localpart, suffix, domain)
        if candidate not in taken:
            return candidate
        suffix += 1


def display_name(vendor, subject_type, subject):
    """Emitted raw -- never lower-cased, run-replaced or truncated."""
    if subject_type == "TEACHER":
        return subject.get("full_name")
    first = subject.get("first_name") or ""
    last = subject.get("last_name") or ""
    if vendor.get("name_format") == "FIRST_LAST":
        return first + " " + last
    return last + ", " + first


# --------------------------------------------------------------------------
# sync_scope_resolution
# --------------------------------------------------------------------------
class Scope(object):
    __slots__ = ("sections", "feed_sections", "enrollments", "students",
                 "teachers", "feed_students", "feed_enrollments",
                 "skipped_section_count")


def resolve_scope(vendor, run_type=None, include_archived=False):
    """The one pinned scope computation used by extract, transform, publish, feed."""
    if run_type == "ROLLOVER":
        allowed_status = ("ARCHIVED",)
    elif include_archived:
        allowed_status = ("ACTIVE", "ARCHIVED")
    else:
        allowed_status = ("ACTIVE",)
    bands = vendor.get("grade_band_scope") or []

    rows = []
    for section in store.sections.values():
        if section.get("term_id") != vendor.get("term_id"):
            continue
        if section.get("status") not in allowed_status:
            continue
        school = store.schools.get(section.get("school_id"))
        if school is None or school.get("status") != "ACTIVE":
            continue
        if school.get("grade_band") not in bands:
            continue
        rows.append((school.get("building_code"), section.get("period_index"),
                     section.get("created_at"), section.get("_seq"), section))
    rows.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    sections = [t[4] for t in rows]
    section_ids = set(s["id"] for s in sections)

    skip = vendor.get("unmatched_teacher_policy") == "SKIP_SECTION"
    feed_sections = [s for s in sections
                     if not (skip and s.get("roster_health") == "UNMATCHED_TEACHER")]
    feed_ids = set(s["id"] for s in feed_sections)

    enrollment_rows = []
    for enrollment in store.enrollments.values():
        if enrollment.get("section_id") not in section_ids:
            continue
        if enrollment.get("roster_status") not in ("PENDING_ADD", "ACTIVE", "PENDING_DROP"):
            continue
        enrollment_rows.append((enrollment.get("effective_date") or "",
                                enrollment.get("created_at"),
                                enrollment.get("_seq"), enrollment))
    enrollment_rows.sort(key=lambda t: (t[0], t[1], t[2]))
    enrollments = [t[3] for t in enrollment_rows]

    students = []
    seen = set()
    for enrollment in enrollments:
        student_id = enrollment.get("student_id")
        if student_id in seen:
            continue
        student = store.students.get(student_id)
        if student is None or student.get("enrollment_state") != "ENROLLED":
            continue
        seen.add(student_id)
        students.append(student)

    feed_enrollments = [e for e in enrollments if e.get("section_id") in feed_ids]
    feed_students = []
    seen = set()
    for enrollment in feed_enrollments:
        student_id = enrollment.get("student_id")
        if student_id in seen:
            continue
        student = store.students.get(student_id)
        if student is None or student.get("enrollment_state") != "ENROLLED":
            continue
        seen.add(student_id)
        feed_students.append(student)

    teachers = []
    if vendor.get("seat_model") == "PER_STUDENT_AND_TEACHER":
        seen = set()
        for section in feed_sections:
            teacher_id = section.get("primary_teacher_id")
            if teacher_id is None or teacher_id in seen:
                continue
            teacher = store.teachers.get(teacher_id)
            if teacher is None or teacher.get("employment_status") != "ACTIVE":
                continue
            seen.add(teacher_id)
            teachers.append(teacher)

    scope = Scope()
    scope.sections = sections
    scope.feed_sections = feed_sections
    scope.enrollments = enrollments
    scope.students = students
    scope.teachers = teachers
    scope.feed_students = feed_students
    scope.feed_enrollments = feed_enrollments
    scope.skipped_section_count = len(sections) - len(feed_sections)
    return scope


def transformed_record_count(scope):
    return len(scope.feed_sections) + len(scope.feed_students) + len(scope.teachers)


# --------------------------------------------------------------------------
# sync_seat_charge -- the two projection variants
# --------------------------------------------------------------------------
def vendor_accounts(vendor_id):
    return [a for a in store.app_accounts.values()
            if a.get("_vendor_app_id") == vendor_id]


def project_seats_and_charge(vendor, term, scope, basis):
    """basis == 'provisional' dates by requested_effective_date, 'final' by effective_date."""
    field = ("requested_effective_date" if basis == "provisional" else "effective_date")
    subjects = []
    for student in scope.feed_students:
        dates = [e.get(field) for e in scope.feed_enrollments
                 if e.get("student_id") == student["id"] and e.get(field)]
        if not dates:
            continue
        subjects.append(("STUDENT", student["id"], min(dates)))
    for teacher in scope.teachers:
        subjects.append(("TEACHER", teacher["id"], term["start_date"]))

    charge = 0
    for _kind, _sid, charge_date in subjects:
        charge += rate_for_date(vendor, term, charge_date)

    population = set((kind, sid) for kind, sid, _d in subjects)
    existing = 0
    for account in vendor_accounts(vendor["id"]):
        if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
            continue
        key = (account.get("subject_type"),
               account.get("student_id") if account.get("subject_type") == "STUDENT"
               else account.get("teacher_id"))
        if key in population:
            existing += 1
    return len(subjects) - existing, charge


# --------------------------------------------------------------------------
# building_seat_allocation
# --------------------------------------------------------------------------
def allocation_candidates(vendor):
    bands = vendor.get("grade_band_scope") or []
    candidates = [s for s in store.schools.values()
                  if s.get("status") == "ACTIVE" and s.get("grade_band") in bands]
    candidates.sort(key=lambda s: (-(s.get("enrolled_student_count") or 0),
                                   s.get("created_at"), s.get("_seq")))
    return candidates


def split_seats(vendor, candidates):
    """Returns [(school, allocated_seats)] with the pinned rounding order."""
    total = vendor["total_seats"]
    count = len(candidates)
    if vendor.get("allocation_policy") == "FIXED_BUILDING_BLOCKS":
        remaining = total
        result = []
        block = vendor.get("block_seats") or 0
        for school in candidates:
            granted = block if block < remaining else remaining
            if granted < 0:
                granted = 0
            result.append((school, granted))
            remaining -= granted
        return result

    headcount = sum((s.get("enrolled_student_count") or 0) for s in candidates)
    if headcount == 0:
        base = total // count
        leftover = total - base * count
        result = []
        for index, school in enumerate(candidates):
            result.append((school, base + (1 if index < leftover else 0)))
        return result

    exact = {}
    floors = {}
    for school in candidates:
        share = Fraction(total * (school.get("enrolled_student_count") or 0), headcount)
        exact[school["id"]] = share
        floors[school["id"]] = share.numerator // share.denominator
    leftover = total - sum(floors.values())
    recipients = sorted(
        candidates,
        key=lambda s: (-(exact[s["id"]] - floors[s["id"]]),
                       -(s.get("enrolled_student_count") or 0),
                       s.get("created_at"), s.get("_seq")),
    )
    bonus = set(s["id"] for s in recipients[:leftover])
    return [(s, floors[s["id"]] + (1 if s["id"] in bonus else 0)) for s in candidates]


# --------------------------------------------------------------------------
# renewal_recommendation_score
# --------------------------------------------------------------------------
W_UTILIZATION = Fraction(1, 2)
W_ENGAGEMENT = Fraction(3, 10)
W_COST = Fraction(1, 5)
ENGAGEMENT_MINUTES_FLOOR = 120
ENGAGED_COST_TARGET_CENTS = 1500
USAGE_WINDOW_DAYS = 30
RENEW_FLOOR = Decimal("70")
RENEGOTIATE_FLOOR = Decimal("40")


def round_half_up_2(fraction):
    with decimal.localcontext() as ctx:
        ctx.prec = 60
        value = Decimal(fraction.numerator) / Decimal(fraction.denominator)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def renewal_figures(vendor, basis="final"):
    """Scoring over the accounts of this license's allocations."""
    accounts = vendor_accounts(vendor["id"])
    consumed = [a for a in accounts if a.get("seat_status") in ("RESERVED", "ACTIVE")]
    provisioned = [a for a in accounts if a.get("identity_status") == "PROVISIONED"]

    floor_date = add_days(store.clock_date(), -USAGE_WINDOW_DAYS)
    engaged = []
    for account in provisioned:
        if (account.get("active_minutes_total") or 0) < ENGAGEMENT_MINUTES_FLOOR:
            continue
        if basis == "final":
            last = account.get("last_activity_date")
            if last is None or as_date(last) < floor_date:
                continue
        engaged.append(account)

    consumed_count = len(consumed)
    provisioned_count = len(provisioned)
    engaged_count = len(engaged)
    total_seats = vendor.get("total_seats") or 0

    utilization = Fraction(0)
    if total_seats:
        utilization = Fraction(consumed_count, total_seats)
    denominator = consumed_count if basis == "final" else provisioned_count
    engagement = Fraction(0)
    if denominator:
        engagement = Fraction(engaged_count, denominator)

    committed = vendor.get("committed_charge_cents") or 0
    if engaged_count == 0:
        cost_per_engaged = None
        cost_efficiency = Fraction(0)
    else:
        cost_per_engaged = -((-committed) // engaged_count)
        if cost_per_engaged <= 0:
            cost_efficiency = Fraction(1)
        else:
            ratio = Fraction(ENGAGED_COST_TARGET_CENTS, cost_per_engaged)
            cost_efficiency = ratio if ratio < 1 else Fraction(1)

    raw = (W_UTILIZATION * utilization + W_ENGAGEMENT * engagement
           + W_COST * cost_efficiency)
    score = round_half_up_2(raw * 100)
    if score >= RENEW_FLOOR:
        recommendation = "RENEW"
    elif score >= RENEGOTIATE_FLOOR:
        recommendation = "RENEGOTIATE"
    else:
        recommendation = "DROP"
    return {
        "account_count": len(accounts),
        "consumed_seats": consumed_count,
        "provisioned_seats": provisioned_count,
        "engaged_seats": engaged_count,
        "utilization": float(utilization),
        "engagement": float(engagement),
        "cost_per_engaged_cents": cost_per_engaged,
        "cost_efficiency": float(cost_efficiency),
        "renewal_score": float(score),
        "renewal_recommendation": recommendation,
    }


# --------------------------------------------------------------------------
# license_invoice_projection -- seven pinned steps
# --------------------------------------------------------------------------
PLATFORM_FEE_RATE = Fraction(3, 100)
FEE_FLOOR_CENTS = 25000
UNALLOCATED_CREDIT_RATE = Fraction(1, 4)


def invoice_projection(vendor):
    gross = vendor.get("committed_charge_cents") or 0
    if gross >= 5000000:
        rate = Fraction(15, 100)
    elif gross >= 2000000:
        rate = Fraction(10, 100)
    elif gross >= 500000:
        rate = Fraction(5, 100)
    else:
        rate = Fraction(0, 1)
    discount = (gross * rate.numerator) // rate.denominator
    net = gross - discount
    fee = -((-net * PLATFORM_FEE_RATE.numerator) // PLATFORM_FEE_RATE.denominator)
    if fee < FEE_FLOOR_CENTS:
        fee = FEE_FLOOR_CENTS
    unallocated = vendor.get("unallocated_seats") or 0
    credit = (unallocated * (vendor.get("price_per_seat_cents") or 0)
              * UNALLOCATED_CREDIT_RATE.numerator) // UNALLOCATED_CREDIT_RATE.denominator
    if credit > net:
        credit = net
    return {
        "gross_seat_cents": gross,
        "discount_rate": float(rate),
        "discount_cents": discount,
        "net_seat_cents": net,
        "platform_fee_cents": fee,
        "shelfware_credit_cents": credit,
        "invoice_total_cents": net + fee - credit,
    }


# --------------------------------------------------------------------------
# password_lifecycle_evaluation
# --------------------------------------------------------------------------
def account_subject(account):
    if account.get("subject_type") == "STUDENT":
        return store.students.get(account.get("student_id"))
    return store.teachers.get(account.get("teacher_id"))


def subject_school(account):
    """POLICY SOURCE: the subject's own building, not the allocation's."""
    subject = account_subject(account)
    if subject is None:
        return None
    return store.schools.get(subject.get("school_id"))


def temp_password_expiry(account, school):
    created = store.parse_instant(account["created_at"])
    hours = school.get("temp_password_ttl_hours") if school else None
    if hours is None:
        hours = 72
    return store.fmt_instant(created + datetime.timedelta(hours=hours))


def user_password_expiry(set_at, school):
    days = school.get("password_max_age_days") if school else None
    if days is None:
        days = 180
    return store.fmt_instant(set_at + datetime.timedelta(days=days))


def evaluate_password_expiry(account):
    """Lazy but reliable expiry. Returns True when the account was mutated."""
    if account.get("identity_status") == "DEPROVISIONED":
        return False
    if account.get("password_state") not in ("TEMP_SET", "USER_SET"):
        return False
    expires_at = account.get("password_expires_at")
    if not expires_at:
        return False
    if store.clock_now() >= store.parse_instant(expires_at):
        account["password_state"] = "EXPIRED"
        return True
    return False


def check_password_policy(school, new_password):
    minimum = school.get("min_password_length") if school else 8
    if minimum is None:
        minimum = 8
    if len(new_password) < minimum:
        raise ApiError("ERR_PASSWORD_TOO_SHORT",
                       "The password is shorter than the building minimum.")
    if school and school.get("password_requires_mixed_case"):
        has_lower = any("a" <= c <= "z" for c in new_password)
        has_upper = any("A" <= c <= "Z" for c in new_password)
        if not (has_lower and has_upper):
            raise ApiError("ERR_PASSWORD_COMPLEXITY",
                           "The password must mix upper and lower case.")


# --------------------------------------------------------------------------
# archived_access_window
# --------------------------------------------------------------------------
def archived_read_permitted(term):
    if term is None or term.get("state") != "ROLLED_OVER":
        return False
    expires_at = term.get("archived_access_expires_at")
    if not expires_at:
        return False
    return store.clock_now() < store.parse_instant(expires_at)


# --------------------------------------------------------------------------
# Scheduling conflicts
# --------------------------------------------------------------------------
def teacher_period_conflict(teacher_id, term_id, period_index, meeting_days,
                            exclude_section_id=None):
    """One-period travel buffer, shared meeting day, ACTIVE sections of one term."""
    days = set(meeting_days or [])
    for section in store.sections.values():
        if section["id"] == exclude_section_id:
            continue
        if section.get("primary_teacher_id") != teacher_id:
            continue
        if section.get("term_id") != term_id:
            continue
        if section.get("status") != "ACTIVE":
            continue
        other = section.get("period_index")
        if other is None or abs(other - period_index) > 1:
            continue
        if days & set(section.get("meeting_days") or []):
            return True
    return False


def _enrollment_window(enrollment, section):
    start = as_date(enrollment.get("effective_date")
                    or enrollment.get("requested_effective_date"))
    stop = enrollment.get("drop_effective_date")
    if stop:
        end = as_date(stop)
    else:
        term = store.terms.get(section.get("term_id"))
        end = as_date(term["end_date"]) if term else start
    return start, end


def student_schedule_conflict(student_id, section, requested_date, drop_date=None,
                              exclude_enrollment_id=None):
    """Exact period equality over half-open date intervals; touching does not overlap."""
    term = store.terms.get(section.get("term_id"))
    start = as_date(requested_date)
    end = as_date(drop_date) if drop_date else as_date(term["end_date"])
    days = set(section.get("meeting_days") or [])
    for enrollment in store.enrollments.values():
        if enrollment.get("student_id") != student_id:
            continue
        if enrollment["id"] == exclude_enrollment_id:
            continue
        if enrollment.get("roster_status") == "DROPPED":
            continue
        other_section = store.sections.get(enrollment.get("section_id"))
        if other_section is None:
            continue
        if other_section.get("period_index") != section.get("period_index"):
            continue
        if not (days & set(other_section.get("meeting_days") or [])):
            continue
        other_start, other_end = _enrollment_window(enrollment, other_section)
        if start < other_end and other_start < end:
            return True
    return False
