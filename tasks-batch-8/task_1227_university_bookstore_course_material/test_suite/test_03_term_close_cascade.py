"""Adoption-close cascade (CASCADE-1), terminal lockdown, and duplicate rules."""
from test_helpers import (
    ApiErrorId,
    assert_section,
    assert_term,
    create_adoption,
    create_approved_adoption,
    create_faculty,
    create_publisher_with_agreement,
    create_section,
    create_term,
    create_title,
    close_adoption,
    get_success_data,
    make_faculty_headers,
    open_section,
    open_term_adoption,
    reset_clock,
    submit_adoption,
    validate_error,
    validate_success,
)
from test_helpers import MANAGER


def test_close_adoption_period_three_hop_cascade(api):
    """PRD §3.1: "From `ADOPTION_OPEN`, a `BookstoreManager` closes adoption,
    moving the term to `ADOPTION_CLOSED` and firing CASCADE-1: every adoption
    of a section in this term still sitting in `DRAFT` or `RETURNED` is swept
    to `EXPIRED`; each expiring adoption recomputes its section's
    `compliance_status`, which becomes `NON_COMPLIANT` if the section has zero
    approved adoptions or has any adoption — in any status — whose `late_flag`
    is true, and otherwise becomes `COMPLIANT`; and each section flip recomputes
    the term's `noncompliant_section_count` (the count of `NON_COMPLIANT`
    sections in the term) and its `compliance_posture`, which becomes
    `RESTRICTED` when that count is greater than 0 and `CLEAR` otherwise."

    Design: Difficulty/transitive_cascade/close_adoption_period_three_hop_cascade
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000006", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    sec_a = create_section(term["id"], faculty["id"], course_code="CS101")
    sec_b = create_section(term["id"], faculty["id"], course_code="CS102")
    open_term_adoption(term["id"])
    opened_a = open_section(sec_a["id"])
    opened_b = open_section(sec_b["id"])
    # hop 1 candidate: a DRAFT adoption never submitted.
    ado_a = create_adoption(
        sec_a["id"], title["id"], faculty["id"], opened_a["version"],
        qty_new=10, posted_price_cents=10000,
    )
    # compliant counterpart: an APPROVED adoption submitted on time.
    create_approved_adoption(
        sec_b["id"], title["id"], faculty["id"], opened_b["version"],
        qty_new=10, posted_price_cents=10000,
    )

    closed = close_adoption(term["id"])
    assert closed["status"] == "ADOPTION_CLOSED"

    expired = get_success_data(
        api.get_adoption(ado_a["id"], make_faculty_headers(faculty["id"]))
    )
    assert expired["status"] == "EXPIRED"

    section_a = get_success_data(
        api.get_section(sec_a["id"], make_faculty_headers(faculty["id"]))
    )
    section_b = get_success_data(
        api.get_section(sec_b["id"], make_faculty_headers(faculty["id"]))
    )
    assert_section(section_a)
    assert section_a["compliance_status"] == "NON_COMPLIANT"

    term_after = get_success_data(api.get_term(term["id"], MANAGER))
    assert_term(term_after)
    assert term_after["noncompliant_section_count"] == 1
    assert term_after["compliance_posture"] == "RESTRICTED"


def test_close_adoption_cascade_all_sections_compliant_keeps_clear(api):
    """PRD §3.1: "each section flip recomputes the term's
    `noncompliant_section_count` (the count of `NON_COMPLIANT` sections in the
    term) and its `compliance_posture`, which becomes `RESTRICTED` when that
    count is greater than 0 and `CLEAR` otherwise."
    PRD §3.1: "moving the term to `ADOPTION_CLOSED` and firing CASCADE-1: every
    adoption of a section in this term still sitting in `DRAFT` or `RETURNED`
    is swept to `EXPIRED`".

    Design: Difficulty/transitive_cascade/close_adoption_period_three_hop_cascade
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000031", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    sec = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(sec["id"])
    ado = create_approved_adoption(
        sec["id"], title["id"], faculty["id"], opened["version"],
        qty_new=10, posted_price_cents=10000,
    )

    closed = close_adoption(term["id"])
    assert closed["status"] == "ADOPTION_CLOSED"

    # APPROVED is terminal for the sweep: the adoption is untouched.
    after = get_success_data(
        api.get_adoption(ado["id"], make_faculty_headers(faculty["id"]))
    )
    assert after["status"] == "APPROVED"

    term_after = get_success_data(api.get_term(term["id"], MANAGER))
    assert term_after["noncompliant_section_count"] == 0
    assert term_after["compliance_posture"] == "CLEAR"


def test_adoption_submit_twice_rejected(api):
    """PRD §3.4: "Submission is the HEOA compliance moment: the faculty owner
    submits the adoption, moving it from `DRAFT` to `SUBMITTED`."
    PRD §2.8: "State: the target resource is in a valid from-state for the
    requested transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/adoption_submit_twice_rejected
    """
    reset_clock()
    term = create_term()
    pub, _ = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001003", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=9500,
    )
    submitted = submit_adoption(adoption["id"], faculty["id"])
    assert submitted["status"] == "SUBMITTED"

    resp = api.submit_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(
        api.get_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    )
    assert current["status"] == "SUBMITTED"


def test_expired_adoption_terminal_lockdown(api):
    """PRD §3.4: "The adoption's terminal states are `EXPIRED` (reached via the
    adoption-close sweep from `DRAFT` or `RETURNED`) and `SUPERSEDED`."
    PRD §2.8: "State: the target resource is in a valid from-state for the
    requested transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/expired_adoption_terminal_lockdown
    """
    reset_clock()
    term = create_term()
    pub, _ = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001004", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=9500,
    )

    close_adoption(term["id"])
    swept = get_success_data(
        api.get_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    )
    assert swept["status"] == "EXPIRED"

    resp = api.submit_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_submit_without_posted_price_rejected(api):
    """PRD §3.4: "requires `posted_price_cents` to be set; a submit with a null
    posted price is rejected with `ERR_PRICE_POSTING_REQUIRED`."

    Design: Corner/validations/submit_without_posted_price_rejected
    """
    reset_clock()
    term = create_term()
    pub, _ = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001010", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=None,
    )

    resp = api.submit_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    validate_error(resp, ApiErrorId.ERR_PRICE_POSTING_REQUIRED)
    current = get_success_data(
        api.get_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    )
    assert current["status"] == "DRAFT"
    assert current["submitted_at"] is None


def test_duplicate_adoption_rejected(api):
    """PRD §3.4: "At most one non-terminal adoption may exist for a given
    section and title: an existing adoption in `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW`, or `RETURNED` for the same pair blocks creation with
    `ERR_DUPLICATE_ADOPTION`."

    Design: Corner/validations/duplicate_adoption_rejected
    """
    reset_clock()
    term = create_term()
    pub, _ = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001011", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    first = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=None,
    )

    fresh_section = get_success_data(
        api.get_section(section["id"], make_faculty_headers(faculty["id"]))
    )
    resp = api.create_adoption(
        {
            "section_id": section["id"],
            "title_id": title["id"],
            "qty_new_requested": 7,
            "qty_used_requested": 0,
            "qty_rental_requested": 0,
            "qty_digital_requested": 0,
            "expected_section_version": fresh_section["version"],
        },
        make_faculty_headers(faculty["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ADOPTION)
    current = get_success_data(
        api.get_adoption(first["id"], make_faculty_headers(faculty["id"]))
    )
    assert current["status"] == "DRAFT"
