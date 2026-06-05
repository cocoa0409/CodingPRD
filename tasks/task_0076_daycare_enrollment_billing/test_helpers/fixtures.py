"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted (empty DB) before every test.

Conventions:
- CenterDirector / BillingAdmin are opaque operators (shared headers).
- Parent is entity_backed:Family -> headers must carry the Family.id.
- Teacher is entity_backed:Classroom -> headers must carry the Classroom.id.

All setup calls use get_success_data (lenient 2xx) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_director_headers, make_billing_headers,
    make_parent_headers, make_teacher_headers,
)
from . import factories as F

DIRECTOR = make_director_headers()
BILLING = make_billing_headers()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Pin the server's current UTC instant (CenterDirector-only)."""
    return get_success_data(api_client.set_clock(iso8601, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 1: primitive creators
# ---------------------------------------------------------------------------
def create_center(**overrides) -> dict:
    return get_success_data(api_client.create_center(F.create_center_payload(**overrides), DIRECTOR))


def add_sliding_scale_row(center_id, tier, max_fpl_ratio_pct, parent_share_pct) -> dict:
    return get_success_data(api_client.add_sliding_scale(
        center_id,
        F.create_sliding_scale_payload(tier, max_fpl_ratio_pct, parent_share_pct),
        DIRECTOR))


def add_full_pay_scale(center_id):
    """Add the FULL_PAY catch-all row (parent_share 100)."""
    return add_sliding_scale_row(center_id, "FULL_PAY", 999999, 100)


def create_classroom(center_id, **overrides) -> dict:
    return get_success_data(api_client.create_classroom(
        center_id, F.create_classroom_payload(**overrides), DIRECTOR))


def create_family(center_id, **overrides) -> dict:
    return get_success_data(api_client.create_family(
        F.create_family_payload(center_id, **overrides), DIRECTOR))


def create_child(family_id, **overrides) -> dict:
    return get_success_data(api_client.create_child(
        F.create_child_payload(family_id, **overrides), DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2: a center + a FULL_PAY scale + a classroom + a family
# ---------------------------------------------------------------------------
def setup_center_classroom_family(center_overrides=None, classroom_overrides=None,
                                  family_overrides=None, with_full_pay=True):
    """Return (center, classroom, family). FULL_PAY scale row added by default
    so a family resolves to FULL_PAY (parent_share 100) unless other rows added."""
    center = create_center(**(center_overrides or {}))
    if with_full_pay:
        add_full_pay_scale(center["id"])
    classroom = create_classroom(center["id"], **(classroom_overrides or {}))
    family = create_family(center["id"], **(family_overrides or {}))
    return center, classroom, family


# ---------------------------------------------------------------------------
# Tier 3: enrollment lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_offered_enrollment(classroom, family, child=None, child_overrides=None,
                              waitlist_entry_id=None):
    """Create a child (if not given) and a direct OFFERED enrollment.
    Returns (child, enrollment). Reads the classroom's live version first."""
    if child is None:
        child = create_child(family["id"], **(child_overrides or {}))
    room = get_success_data(api_client.get_classroom(classroom["id"], DIRECTOR))
    payload = F.create_enrollment_payload(
        child["id"], classroom["id"], room["version"],
        **({"waitlist_entry_id": waitlist_entry_id} if waitlist_entry_id else {}))
    enrollment = get_success_data(api_client.create_enrollment(payload, DIRECTOR))
    return child, enrollment


def accept_enrollment(enrollment, family):
    parent = make_parent_headers(family["id"])
    return get_success_data(api_client.accept_enrollment(enrollment["id"], parent))


def activate_enrollment(enrollment):
    return get_success_data(api_client.activate_enrollment(enrollment["id"], DIRECTOR))


def create_active_enrollment(classroom, family, child=None, child_overrides=None):
    """child -> OFFERED -> ACCEPTED -> ACTIVE. Returns (child, activated_enrollment)."""
    child, enrollment = create_offered_enrollment(
        classroom, family, child=child, child_overrides=child_overrides)
    accept_enrollment(enrollment, family)
    activated = activate_enrollment(enrollment)
    return child, activated


def setup_single_active_enrollment(center_overrides=None, classroom_overrides=None,
                                   family_overrides=None, child_overrides=None,
                                   with_full_pay=True, extra_scale_rows=None):
    """The most common setup: center+FULL_PAY scale+classroom+family+one ACTIVE
    enrollment. Returns (center, classroom, family, child, enrollment).
    `extra_scale_rows` is a list of (tier, max_fpl, share) tuples added before
    the family is created (in addition to / instead of FULL_PAY)."""
    center = create_center(**(center_overrides or {}))
    if extra_scale_rows:
        for tier, mx, share in extra_scale_rows:
            add_sliding_scale_row(center["id"], tier, mx, share)
    if with_full_pay:
        add_full_pay_scale(center["id"])
    classroom = create_classroom(center["id"], **(classroom_overrides or {}))
    family = create_family(center["id"], **(family_overrides or {}))
    child, enrollment = create_active_enrollment(
        classroom, family, child_overrides=child_overrides)
    return center, classroom, family, child, enrollment


# ---------------------------------------------------------------------------
# Tier 3b: two-sibling cascade setups (TIER_B, base 99999 -> 69999 / 62999)
# ---------------------------------------------------------------------------
def setup_two_active_siblings(base_tuition_cents=99999, capacity=2):
    """Elder anchor (0%) and younger junior (10%) both ACTIVE in a TIER_B family.
    Returns (center, classroom, family, elder_child, elder_enr, younger_child,
    younger_enr). With base 99999 + parent_share 70: elder net 69999,
    younger net 62999."""
    center = create_center(cacfp_tier="TIER_I")
    add_sliding_scale_row(center["id"], "TIER_B", 185, 70)
    add_full_pay_scale(center["id"])
    classroom = create_classroom(
        center["id"], age_band="TODDLER", licensed_capacity=capacity,
        base_monthly_tuition_cents=base_tuition_cents)
    # income 5,000,000 size 4 -> TIER_B
    family = create_family(
        center["id"], annual_household_income_cents=5000000, household_size=4)
    elder = create_child(family["id"], full_name="Elder", birthdate="2024-01-10")
    younger = create_child(
        family["id"], full_name="Younger", birthdate="2024-02-10",
        sibling_group_id=elder["id"])
    _, elder_enr = create_active_enrollment(classroom, family, child=elder)
    _, younger_enr = create_active_enrollment(classroom, family, child=younger)
    return (center, classroom, family, elder, elder_enr, younger, younger_enr)


# ---------------------------------------------------------------------------
# Tier 4: attendance / check-out (late-fine + CACFP)
# ---------------------------------------------------------------------------
def create_attendance(classroom, enrollment, service_date, scheduled_pickup_local,
                      **meal_overrides):
    """Teacher (owning classroom) checks the child in. Returns attendance record."""
    teacher = make_teacher_headers(classroom["id"])
    payload = F.create_attendance_payload(
        enrollment["id"], service_date, scheduled_pickup_local, **meal_overrides)
    return get_success_data(api_client.create_attendance(payload, teacher))


def check_out(classroom, attendance):
    teacher = make_teacher_headers(classroom["id"])
    return get_success_data(api_client.check_out(attendance["id"], teacher))


def setup_checked_out_day(check_in_clock, check_out_clock, service_date,
                          scheduled_pickup_local, center_overrides=None,
                          child_overrides=None, meal_overrides=None):
    """Full path to a CHECKED_OUT attendance record with finalized late-fine and
    CACFP figures. Clock is pinned to check_in_clock for setup, advanced to
    check_out_clock immediately before checkout.
    Returns (center, classroom, family, child, enrollment, attendance_checked_out)."""
    set_clock(check_in_clock)
    center, classroom, family, child, enrollment = setup_single_active_enrollment(
        center_overrides=center_overrides, child_overrides=child_overrides)
    attendance = create_attendance(
        classroom, enrollment, service_date, scheduled_pickup_local,
        **(meal_overrides or {}))
    set_clock(check_out_clock)
    checked_out = check_out(classroom, attendance)
    return center, classroom, family, child, enrollment, checked_out


# ---------------------------------------------------------------------------
# Tier 5: invoice / payment lifecycle
# ---------------------------------------------------------------------------
def create_invoice(family_id, billing_month) -> dict:
    return get_success_data(api_client.create_invoice(
        family_id, F.create_invoice_payload(billing_month), BILLING))


def issue_invoice(invoice_id) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


def apply_payment(invoice, amount_cents, method="ACH") -> dict:
    return get_success_data(api_client.create_payment(
        F.create_payment_payload(invoice["id"], amount_cents, invoice["version"],
                                 method=method),
        BILLING))


def setup_issued_invoice(billing_month="2026-03", base_tuition_cents=120000):
    """FULL_PAY family with one ACTIVE enrollment, a DRAFT invoice issued and
    frozen. Returns (center, classroom, family, child, enrollment, issued_invoice).
    With FULL_PAY base 120000 -> tuition 120000, total 120000."""
    center, classroom, family, child, enrollment = setup_single_active_enrollment(
        classroom_overrides={"base_monthly_tuition_cents": base_tuition_cents})
    draft = create_invoice(family["id"], billing_month)
    issued = issue_invoice(draft["id"])
    return center, classroom, family, child, enrollment, issued


def setup_paid_invoice(billing_month="2026-03", base_tuition_cents=120000):
    """As setup_issued_invoice, then fully paid -> Invoice PAID.
    Returns (center, classroom, family, child, enrollment, paid_invoice)."""
    center, classroom, family, child, enrollment, issued = setup_issued_invoice(
        billing_month=billing_month, base_tuition_cents=base_tuition_cents)
    apply_payment(issued, issued["total_cents"], method="ACH")
    paid = get_success_data(api_client.get_invoice(issued["id"], BILLING))
    return center, classroom, family, child, enrollment, paid


# ---------------------------------------------------------------------------
# Tier 6: waitlist setups
# ---------------------------------------------------------------------------
def add_to_waitlist(classroom_id, child_id) -> dict:
    return get_success_data(api_client.add_to_waitlist(
        classroom_id, F.create_waitlist_payload(child_id), DIRECTOR))


def setup_offered_waitlist_entry(promote_clock="2026-03-01T08:00:00Z"):
    """Capacity-1 classroom, one child placed on the waitlist and promoted to
    OFFERED at promote_clock. Returns (center, classroom, family, child, entry).
    Clock is pinned to promote_clock; offer_expires_at = promote_clock + 48h."""
    set_clock(promote_clock)
    center = create_center(cacfp_tier="TIER_I")
    classroom = create_classroom(
        center["id"], age_band="TODDLER", licensed_capacity=1,
        base_monthly_tuition_cents=120000)
    family = create_family(center["id"])
    child = create_child(family["id"])
    entry = add_to_waitlist(classroom["id"], child["id"])
    get_success_data(api_client.promote_waitlist(classroom["id"], DIRECTOR))
    entry = get_success_data(api_client.get_waitlist_entry(entry["id"], DIRECTOR))
    return center, classroom, family, child, entry
