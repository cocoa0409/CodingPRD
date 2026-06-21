"""Composite setup helpers for multi-step test prerequisites.

These encapsulate the repeated multi-call preambles that the design indices
require so test bodies can focus on the assertion under test. All setup calls
use get_success_data() (the lenient validator) so a broken precondition surfaces
as a clear "Setup step failed" error rather than a confusing assertion failure.

Identity threading: entity-backed roles (Member, Instructor, ChiefInstructor)
always act through make_<role>_headers(entity["id"]); FrontDesk acts through the
shared opaque header.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload, create_belt_rank_payload, create_family_payload,
    create_member_payload, create_instructor_payload, create_enrollment_payload,
    create_class_session_payload, create_attendance_payload,
    create_promotion_test_payload, create_contract_payload,
    create_private_lesson_payload, create_tournament_registration_payload,
    create_pro_shop_order_payload, unique_email,
)
from .test_users import (
    TEST_USERS, make_member_headers, make_instructor_headers,
    make_chief_instructor_headers,
)

FD = TEST_USERS["front_desk_headers"]


# ─── Clock control ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server's logical UTC clock (PRD §3.8 test-driving capability)."""
    return get_success_data(api_client.advance_clock({"to_iso8601": to_iso8601}, FD))


# ─── Tier 1: Primitive creation helpers ───────────────────────

def create_program(with_entry_rank=True, **overrides):
    """Create a program. PRD §3.1 mandates "Exactly one rank per program is the
    entry rank ... a fresh enrollment always starts there", so by default this
    helper also lays down a single terminal entry rank (WHITE, rank_order 0,
    next_rank_code null, is_entry_rank true) — the minimum belt chain that makes
    the program enrollable. Callers that build their own chain (or that test the
    rankless/duplicate-rank cases) pass with_entry_rank=False to opt out.
    """
    prog = get_success_data(api_client.create_program(create_program_payload(**overrides), FD))
    if with_entry_rank:
        add_belt_rank(prog["id"], "WHITE", 0, next_rank_code=None, is_entry_rank=True)
    return prog


def add_belt_rank(program_id, code, rank_order, **overrides):
    return get_success_data(api_client.create_belt_rank(
        program_id, create_belt_rank_payload(code, rank_order, **overrides), FD))


def create_family(**overrides):
    return get_success_data(api_client.create_family(create_family_payload(**overrides), FD))


def create_member(**overrides):
    return get_success_data(api_client.create_member(create_member_payload(**overrides), FD))


def create_instructor(**overrides):
    return get_success_data(api_client.create_instructor(create_instructor_payload(**overrides), FD))


def create_enrollment(member_id, program_id, expected_member_version):
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(member_id, program_id, expected_member_version), FD))


def member_version(member_id):
    """Fetch a member's current version (for OCC-guarded follow-up writes)."""
    return get_success_data(api_client.get_member(member_id, FD))["version"]


# ─── Tier 2: Program + belt-chain scaffolds ───────────────────

def create_program_with_simple_chain(entry_next="BLUE", terminal_code="BLUE",
                                     entry_requires_signoff=False,
                                     terminal_requires_signoff=False, **prog_overrides):
    """Program with a two-rank chain WHITE(0) -> terminal_code(1, terminal).

    entry_next is the WHITE.next_rank_code; terminal_code is the second rank.
    Returns the program dict.
    """
    prog = create_program(with_entry_rank=False, **prog_overrides)
    add_belt_rank(prog["id"], "WHITE", 0, next_rank_code=entry_next, is_entry_rank=True,
                  requires_chief_signoff=entry_requires_signoff)
    add_belt_rank(prog["id"], terminal_code, 1, next_rank_code=None,
                  requires_chief_signoff=terminal_requires_signoff)
    return prog


def create_program_single_terminal_rank(code="ONLY", **prog_overrides):
    """Program whose single entry rank is itself terminal (next_rank_code null)."""
    prog = create_program(with_entry_rank=False, **prog_overrides)
    add_belt_rank(prog["id"], code, 0, next_rank_code=None, is_entry_rank=True)
    return prog


# ─── Tier 2: Enrolled-member scaffolds ────────────────────────

def setup_enrolled_member(program_id, waiver_signed=True, member_overrides=None):
    """Create a member and enroll them in program_id. Returns (member, enrollment)."""
    member = create_member(waiver_signed=waiver_signed, **(member_overrides or {}))
    enrollment = create_enrollment(member["id"], program_id, member["version"])
    return member, enrollment


def setup_program_member_instructor(prog_overrides=None):
    """Program + one member (enrolled) + one instructor. Returns (program, member,
    enrollment, instructor)."""
    prog = create_program(**(prog_overrides or {}))
    instructor = create_instructor()
    member, enrollment = setup_enrolled_member(prog["id"])
    return prog, member, enrollment, instructor


# ─── Tier 3: Family scaffolds (for discount-tier tests) ───────

def setup_family_with_members(count, surname="Fam", waiver_signed=True):
    """Create a family with `count` ACTIVE members. Returns (family, [members])."""
    fam = create_family(surname=surname, billing_email=unique_email("fam"))
    members = []
    for i in range(count):
        m = create_member(full_name=f"{surname} {i}", family_id=fam["id"],
                          waiver_signed=waiver_signed)
        members.append(m)
    return fam, members


# ─── Tier 3: Class & attendance scaffolds ─────────────────────

def create_class_session(program_id, instructor_id, starts_at, ends_at, capacity=10):
    return get_success_data(api_client.create_class_session(
        create_class_session_payload(program_id, instructor_id, starts_at, ends_at,
                                     capacity=capacity), FD))


def check_in(enrollment_id, class_session_id, member_id):
    """Member checks themselves into a class (ownership-gated -> member headers)."""
    return get_success_data(api_client.create_attendance(
        create_attendance_payload(enrollment_id, class_session_id),
        make_member_headers(member_id)))


# ─── Tier 4: Promotion-test scaffolds ─────────────────────────

def schedule_promotion_test(enrollment_id, examiner_instructor_id, scheduled_for):
    """Schedule a promotion test (acting as the examining instructor)."""
    return get_success_data(api_client.create_promotion_test(
        create_promotion_test_payload(enrollment_id, examiner_instructor_id, scheduled_for),
        make_instructor_headers(examiner_instructor_id)))


def setup_eligible_test_ready(prog_overrides=None, entry_next="BLUE", terminal_code="BLUE",
                             terminal_requires_signoff=False, scheduled_for="2026-02-01T00:00:00Z"):
    """Build a program with a WHITE->terminal chain, an enrolled waiver-signed member,
    an instructor, and a SCHEDULED promotion test. Defaults satisfy eligibility
    (min_attendance_for_test 0, min_days_in_rank 0).

    Returns (program, member, enrollment, instructor, test).
    """
    overrides = {"min_attendance_for_test": 0, "min_days_in_rank": 0}
    overrides.update(prog_overrides or {})
    prog = create_program_with_simple_chain(
        entry_next=entry_next, terminal_code=terminal_code,
        terminal_requires_signoff=terminal_requires_signoff, **overrides)
    instructor = create_instructor()
    member, enrollment = setup_enrolled_member(prog["id"])
    test = schedule_promotion_test(enrollment["id"], instructor["id"], scheduled_for)
    return prog, member, enrollment, instructor, test


# ─── Tier 4: Contract / billing scaffolds ─────────────────────

def sign_contract(member_id, program_id, expected_member_version, **overrides):
    return get_success_data(api_client.create_contract(
        create_contract_payload(member_id, program_id, expected_member_version, **overrides), FD))


def run_billing(contract_id):
    return get_success_data(api_client.run_billing(contract_id, FD))


def run_billing_and_pay(contract_id, member_id):
    """Run one billing cycle and immediately settle the freshly-generated TUITION
    invoice, so the member's running balance never crosses the 10000-cent
    suspension threshold (PRD §3.6/§3.3). Used by billing-loop and buyout tests
    that need the contract to stay ACTIVE across several runs. Returns the
    contract after billing (post-payment status is re-read by the caller)."""
    contract = get_success_data(api_client.run_billing(contract_id, FD))
    invoices = get_invoices(member_id, kind="TUITION")
    # Pay every still-unpaid tuition invoice so the balance returns to <= threshold.
    for inv in invoices:
        if inv["status"] in ("DUE", "OVERDUE"):
            get_success_data(api_client.pay_invoice(inv["id"], FD))
    return get_success_data(api_client.get_contract(contract_id, FD))


def setup_contract(base_tuition_cents=12000, term_months=12, family_size=None,
                   billing_anchor_day=1):
    """Create a program + member (optionally in a family of `family_size`) and sign a
    contract. Returns (program, member, contract).

    family_size pins a particular locked_family_discount_pct: e.g. family_size=2 -> 0.10.
    None means a solo member (pinned 0.00).
    """
    prog = create_program(base_monthly_tuition_cents=base_tuition_cents)
    if family_size:
        fam, members = setup_family_with_members(family_size, surname="Ctr")
        member = members[0]
    else:
        member = create_member()
    contract = sign_contract(member["id"], prog["id"], member["version"],
                             term_months=term_months, billing_anchor_day=billing_anchor_day)
    return prog, member, contract


def get_invoices(member_id, kind=None):
    """List a member's invoices, optionally filtered by kind."""
    params = {"member_id": member_id}
    if kind:
        params["kind"] = kind
    return get_success_data(api_client.list_invoices(FD, params=params))


# ─── Tier 4: Tournament / private-lesson scaffolds ────────────

def request_private_lesson(member_id, instructor_id, starts_at, ends_at, hourly_rate_cents=6000):
    """Member requests a private lesson (ownership-gated -> member headers)."""
    return get_success_data(api_client.create_private_lesson(
        create_private_lesson_payload(member_id, instructor_id, starts_at, ends_at,
                                      hourly_rate_cents=hourly_rate_cents),
        make_member_headers(member_id)))


def register_tournament(member_id, enrollment_id, event_date, tournament_name="Test Open"):
    """Member registers for a tournament (ownership-gated -> member headers)."""
    return get_success_data(api_client.create_tournament_registration(
        create_tournament_registration_payload(member_id, enrollment_id, event_date,
                                                tournament_name=tournament_name),
        make_member_headers(member_id)))


def place_pro_shop_order(member_id, line_items):
    """Member places a pro-shop order (ownership-gated -> member headers)."""
    return get_success_data(api_client.create_pro_shop_order(
        create_pro_shop_order_payload(member_id, line_items),
        make_member_headers(member_id)))


# ─── Tier 5: Member at a known belt rank (for pro-shop loyalty tier) ───

def setup_member_at_rank_order(target_rank_order, scheduled_for_base="2026-02-02T00:00:00Z"):
    """Create a program with a belt chain reaching `target_rank_order` and promote a
    waiver-signed member up to that rank via successive no-signoff promotion-test passes.

    Returns (program, member, enrollment, instructor). The member's single ACTIVE
    enrollment then sits at rank_order == target_rank_order, driving the pro-shop
    loyalty discount tier.
    """
    # test_fee_cents=0 so the successive promotion-test schedulings used to climb
    # the belt chain never accrue a balance that would cross the 10000-cent
    # suspension threshold (PRD §3.3) and block further scheduling. This helper's
    # sole purpose is to seat the member at a target belt rank for the pro-shop
    # loyalty tier; the test fee is incidental and must not derail the climb.
    prog = create_program(with_entry_rank=False, min_attendance_for_test=0,
                          min_days_in_rank=0, test_fee_cents=0)
    instructor = create_instructor()
    # Build a chain R0 .. R{target}, each non-terminal except the last which is terminal+1
    # so the member can stop AT target_rank_order while still ACTIVE.
    chain_len = target_rank_order + 2  # one extra so target is NOT terminal
    for order in range(chain_len):
        nxt = f"R{order + 1}" if order + 1 < chain_len else None
        add_belt_rank(prog["id"], f"R{order}", order, next_rank_code=nxt,
                      is_entry_rank=(order == 0))
    member, enrollment = setup_enrolled_member(prog["id"])
    set_clock("2026-01-01T00:00:00Z")
    # Promote target_rank_order times: each pass advances one rank.
    for step in range(target_rank_order):
        scheduled = f"2026-01-{2 + step:02d}T00:00:00Z"
        test = schedule_promotion_test(enrollment["id"], instructor["id"], scheduled)
        get_success_data(api_client.grade_promotion_test(
            test["id"], {"score": 90}, make_instructor_headers(instructor["id"])))
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], FD))
    return prog, member, enrollment, instructor
