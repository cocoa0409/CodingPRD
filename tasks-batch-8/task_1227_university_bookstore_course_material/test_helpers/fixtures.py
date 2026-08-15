"""Composite setup helpers.

These functions encapsulate the multi-step setup sequences the bookstore
workflows demand (term lifecycle drives, adoption review loops, section
locking with inclusive-access charge generation, buyback window setup).
Each fixture builds its preconditions from scratch against an empty
database and uses get_success_data so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.

Identity threading: Faculty and Student are entity-backed roles, so every
ownership-gated call is made with per-instance headers built from the
created record's id (never a shared constant).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AGREEMENT_STANDARD,
    CLOCK_AT_CENSUS,
    CLOCK_IN_AID_WINDOW,
    CLOCK_IN_BUYBACK_WINDOW,
    TERM_FALL_2026,
    TERM_SPRING_2027,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_faculty_headers,
    make_student_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _ok(resp, label):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {label}: {resp.text}"
    return data


def set_clock(to_iso8601):
    """Move the server-side logical clock."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed at set_clock: {resp.text}"


def reset_clock():
    """Return the logical clock to its documented default instant."""
    set_clock("2026-05-01T00:00:00Z")


def create_term(term_payload=None):
    """Create an academic term (born in SETUP).

    A supplied payload is merged over the canonical TERM_FALL_2026 calendar,
    so callers may pass either a full calendar or only the keys they vary.
    """
    payload = dict(TERM_FALL_2026)
    if term_payload:
        payload.update(term_payload)
    return _ok(api_client.create_term(payload, ADMIN), "create_term")


def create_spring_term():
    """Create the 2027-SPRING term used as the buyback demand term."""
    return create_term(TERM_SPRING_2027)


def create_publisher(name=TEST_DEFAULTS["PUBLISHER_NAME"]):
    return _ok(api_client.create_publisher({"name": name}, ADMIN), "create_publisher")


def create_agreement(publisher_id, **overrides):
    payload = dict(AGREEMENT_STANDARD)
    payload.update(overrides)
    return _ok(
        api_client.create_agreement(publisher_id, payload, ADMIN),
        "create_agreement",
    )


def create_publisher_with_agreement(name=TEST_DEFAULTS["PUBLISHER_NAME"], **agreement_overrides):
    """Publisher plus a standard active agreement. Returns (publisher, agreement)."""
    pub = create_publisher(name)
    agr = create_agreement(pub["id"], **agreement_overrides)
    return pub, agr


def create_title(publisher_id, isbn="9780000000001", **overrides):
    payload = {
        "isbn": isbn,
        "publisher_id": publisher_id,
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "has_new": True,
        "has_used": True,
        "has_rental": True,
        "has_digital": True,
    }
    payload.update(overrides)
    return _ok(api_client.create_title(payload, ADMIN), "create_title")


def create_faculty(full_name=TEST_DEFAULTS["FACULTY_NAME"], email=TEST_DEFAULTS["FACULTY_EMAIL"]):
    return _ok(
        api_client.create_faculty(
            {"full_name": full_name, "email": email}, ADMIN
        ),
        "create_faculty",
    )


def create_student(full_name="Stu One", email="stu1@uni.edu", awarded_aid_cents=TEST_DEFAULTS["STUDENT_AID"]):
    payload = {"full_name": full_name, "email": email}
    if awarded_aid_cents is not None:
        payload["awarded_aid_cents"] = awarded_aid_cents
    return _ok(api_client.create_student(payload, ADMIN), "create_student")


def create_section(term_id, faculty_id, course_code="CS101", ia_enabled=False,
                   ia_material_fee_cents=None, enrollment_capacity=30):
    payload = {
        "term_id": term_id,
        "faculty_id": faculty_id,
        "course_code": course_code,
        "section_code": "01",
        "enrollment_capacity": enrollment_capacity,
        "ia_enabled": ia_enabled,
    }
    if ia_material_fee_cents is not None:
        payload["ia_material_fee_cents"] = ia_material_fee_cents
    return _ok(api_client.create_section(payload, ADMIN), "create_section")


def enroll_student(section_id, student_id):
    return _ok(
        api_client.enroll_student(section_id, {"student_id": student_id}, ADMIN),
        "enroll_student",
    )


def open_term_adoption(term_id):
    """SETUP -> ADOPTION_OPEN."""
    return _ok(api_client.open_adoption(term_id, ADMIN), "open_adoption")


def open_section(section_id):
    """DRAFT -> OPEN. Returns the section (capture .version for adoption OCC)."""
    return _ok(api_client.open_section(section_id, ADMIN), "open_section")


def create_adoption(section_id, title_id, faculty_id, expected_section_version,
                    qty_new=0, qty_used=0, qty_rental=0, qty_digital=0,
                    posted_price_cents=10000):
    """Create a DRAFT adoption as the owning faculty member."""
    payload = {
        "section_id": section_id,
        "title_id": title_id,
        "qty_new_requested": qty_new,
        "qty_used_requested": qty_used,
        "qty_rental_requested": qty_rental,
        "qty_digital_requested": qty_digital,
        "expected_section_version": expected_section_version,
    }
    if posted_price_cents is not None:
        payload["posted_price_cents"] = posted_price_cents
    return _ok(
        api_client.create_adoption(payload, make_faculty_headers(faculty_id)),
        "create_adoption",
    )


def submit_adoption(adoption_id, faculty_id):
    return _ok(
        api_client.submit_adoption(adoption_id, make_faculty_headers(faculty_id)),
        "submit_adoption",
    )


def create_approved_adoption(section_id, title_id, faculty_id,
                             expected_section_version,
                             qty_new=0, qty_used=0, qty_rental=0, qty_digital=0,
                             posted_price_cents=10000):
    """Walk an adoption to APPROVED (create -> submit -> start-review -> approve).

    Returns the APPROVED adoption. Requires the term to be ADOPTION_OPEN and
    an active agreement to cover the title's publisher.
    """
    adoption = create_adoption(
        section_id, title_id, faculty_id, expected_section_version,
        qty_new=qty_new, qty_used=qty_used, qty_rental=qty_rental,
        qty_digital=qty_digital, posted_price_cents=posted_price_cents,
    )
    submit_adoption(adoption["id"], faculty_id)
    _ok(
        api_client.start_review_adoption(adoption["id"], MANAGER),
        "start_review_adoption",
    )
    return _ok(
        api_client.approve_adoption(adoption["id"], MANAGER),
        "approve_adoption",
    )


def get_buy_plan_for_adoption(adoption_id):
    """Fetch the single buy plan spawned by approval (list of 0-1)."""
    data = get_success_data(api_client.get_adoption_buy_plan(adoption_id, MANAGER))
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed at get_buy_plan_for_adoption: expected 1 plan, got {data}"
    )
    return data[0]


def get_first_order_line(order_id):
    data = get_success_data(api_client.list_order_lines(order_id, MANAGER))
    assert isinstance(data, list) and len(data) >= 1, (
        f"Setup failed at get_first_order_line: {data}"
    )
    return data[0]


def get_ia_charge_for_enrollment(enrollment_id):
    data = get_success_data(
        api_client.list_ia_charges(MANAGER, params={"enrollment_id": enrollment_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed at get_ia_charge_for_enrollment: {data}"
    )
    return data[0]


def close_adoption(term_id):
    return _ok(api_client.close_adoption(term_id, MANAGER), "close_adoption")


def open_sales(term_id):
    return _ok(api_client.open_sales(term_id, MANAGER), "open_sales")


def run_census(term_id):
    return _ok(api_client.run_census_billing(term_id, MANAGER), "run_census_billing")


def open_buyback(term_id):
    return _ok(api_client.open_buyback(term_id, MANAGER), "open_buyback")


def drive_term_to_sales_open(term_id):
    """ADOPTION_OPEN -> ADOPTION_CLOSED -> SALES_OPEN."""
    close_adoption(term_id)
    return open_sales(term_id)


def drive_term_to_buyback_open(term_id, census_clock=CLOCK_AT_CENSUS):
    """SALES_OPEN -> (clock to census) -> CENSUS_DONE -> BUYBACK_OPEN."""
    set_clock(census_clock)
    run_census(term_id)
    return open_buyback(term_id)


def setup_sales_open_with_approved_adoption(
    qty_new=0, qty_used=0, qty_rental=0, qty_digital=0,
    posted_price_cents=10000, title_overrides=None, with_agreement=True,
    term_overrides=None, awarded_aid_cents=TEST_DEFAULTS["STUDENT_AID"],
    isbn="9780000000001",
):
    """Canonical sales floor: term in SALES_OPEN at CLOCK_IN_AID_WINDOW, one
    APPROVED adoption (submitted on time), one student.

    Returns dict(term, publisher, agreement, title, faculty, student,
    section, adoption).
    """
    reset_clock()
    term = create_term(term_overrides)
    publisher, agreement = (None, None)
    if with_agreement:
        publisher, agreement = create_publisher_with_agreement()
    else:
        publisher = create_publisher()
    title = create_title(publisher["id"], isbn=isbn, **(title_overrides or {}))
    faculty = create_faculty()
    student = create_student(awarded_aid_cents=awarded_aid_cents)
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    adoption = create_approved_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=qty_new, qty_used=qty_used, qty_rental=qty_rental,
        qty_digital=qty_digital, posted_price_cents=posted_price_cents,
    )
    drive_term_to_sales_open(term["id"])
    set_clock(CLOCK_IN_AID_WINDOW)
    return {
        "term": get_success_data(api_client.get_term(term["id"], ADMIN)),
        "publisher": publisher,
        "agreement": agreement,
        "title": title,
        "faculty": faculty,
        "student": student,
        "section": section,
        "adoption": adoption,
    }


def place_order(term_id, student_id, lines, aid_only=None):
    """Place an order as the owning student. Returns the created Order."""
    payload = {"term_id": term_id, "lines": lines}
    if aid_only is not None:
        payload["aid_only"] = aid_only
    return _ok(
        api_client.create_order(payload, make_student_headers(student_id)),
        "place_order",
    )


def setup_order_with_line(fmt="USED", qty=1, posted_price_cents=8000,
                          title_overrides=None, awarded_aid_cents=100000,
                          isbn="9780000000001", **adoption_qty_kwargs):
    """Sales floor plus one order holding a single line. Returns
    dict(base..., order, line)."""
    base = setup_sales_open_with_approved_adoption(
        posted_price_cents=posted_price_cents,
        title_overrides=title_overrides,
        awarded_aid_cents=awarded_aid_cents,
        isbn=isbn,
        **adoption_qty_kwargs,
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": fmt, "qty": qty}],
    )
    line = get_first_order_line(order["id"])
    base["order"] = order
    base["line"] = line
    return base


def setup_ia_pending_charge(fee_cents=TEST_DEFAULTS["IA_FEE_CENTS"],
                            awarded_aid_cents=TEST_DEFAULTS["STUDENT_AID"],
                            clock_after_lock=CLOCK_IN_AID_WINDOW):
    """Term in SALES_OPEN with one ia-enabled section LOCKED and one enrolled
    student whose inclusive-access charge is PENDING.

    Returns dict(term, faculty, student, section, enrollment, charge).
    """
    reset_clock()
    term = create_term()
    faculty = create_faculty()
    student = create_student(awarded_aid_cents=awarded_aid_cents)
    section = create_section(
        term["id"], faculty["id"], course_code="BIO200",
        ia_enabled=True, ia_material_fee_cents=fee_cents,
    )
    open_term_adoption(term["id"])
    open_section(section["id"])
    enrollment = enroll_student(section["id"], student["id"])
    drive_term_to_sales_open(term["id"])
    _ok(api_client.lock_section(section["id"], MANAGER), "lock_section")
    charge = get_ia_charge_for_enrollment(enrollment["id"])
    if clock_after_lock is not None:
        set_clock(clock_after_lock)
    return {
        "term": term,
        "faculty": faculty,
        "student": student,
        "section": section,
        "enrollment": enrollment,
        "charge": charge,
    }


def setup_buyback_open_with_demand(
    qty_used_requested=1, with_wholesale_quote=True, quote_price_cents=2200,
    isbn="9780000000001",
):
    """Two-term buyback scenario: the fall term is in BUYBACK_OPEN at
    CLOCK_IN_BUYBACK_WINDOW; the spring term holds an APPROVED adoption whose
    qty_used_requested defines the demand quota. Optionally posts the
    standard GOOD wholesale quote.

    Returns dict(t1, t2, publisher, agreement, title, faculty, student,
    section2, adoption2).
    """
    reset_clock()
    t1 = create_term()
    t2 = create_spring_term()
    publisher, agreement = create_publisher_with_agreement()
    title = create_title(publisher["id"], isbn=isbn)
    faculty = create_faculty()
    student = create_student()
    section2 = create_section(t2["id"], faculty["id"])
    open_term_adoption(t2["id"])
    opened2 = open_section(section2["id"])
    adoption2 = create_approved_adoption(
        section2["id"], title["id"], faculty["id"], opened2["version"],
        qty_used=qty_used_requested, posted_price_cents=9000,
    )
    open_term_adoption(t1["id"])
    drive_term_to_sales_open(t1["id"])
    drive_term_to_buyback_open(t1["id"])
    if with_wholesale_quote:
        _ok(
            api_client.create_wholesale_quote(
                title["id"],
                {
                    "condition": "GOOD",
                    "price_cents": quote_price_cents,
                    "effective_from": "2026-12-01T00:00:00Z",
                    "effective_to": "2027-01-15T00:00:00Z",
                },
                ADMIN,
            ),
            "create_wholesale_quote",
        )
    set_clock(CLOCK_IN_BUYBACK_WINDOW)
    return {
        "t1": t1,
        "t2": t2,
        "publisher": publisher,
        "agreement": agreement,
        "title": get_success_data(api_client.get_title(title["id"], MANAGER)),
        "faculty": faculty,
        "student": student,
        "section2": section2,
        "adoption2": adoption2,
    }


def create_buyback_ticket(title_id, upcoming_term_id, expected_title_version,
                          student_id, condition="GOOD"):
    payload = {
        "title_id": title_id,
        "condition": condition,
        "upcoming_term_id": upcoming_term_id,
        "expected_title_version": expected_title_version,
    }
    return _ok(
        api_client.create_buyback_ticket(payload, make_student_headers(student_id)),
        "create_buyback_ticket",
    )


def accept_buyback_ticket(ticket_id, student_id):
    return _ok(
        api_client.accept_buyback_ticket(ticket_id, make_student_headers(student_id)),
        "accept_buyback_ticket",
    )
