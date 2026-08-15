"""Adoption lifecycle: revision cycle, deadline boundary, OCC, and supersede."""
from test_helpers import (
    ApiErrorId,
    assert_adoption,
    create_adoption,
    create_approved_adoption,
    create_faculty,
    create_publisher,
    create_publisher_with_agreement,
    create_section,
    create_term,
    create_title,
    get_success_data,
    make_faculty_headers,
    open_section,
    open_term_adoption,
    reset_clock,
    set_clock,
    submit_adoption,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN, MANAGER


def _adoption_open_scenario(api, isbn="9780000000005", with_agreement=False):
    """Term ADOPTION_OPEN with one OPEN section and a title. Returns parts."""
    reset_clock()
    term = create_term()
    if with_agreement:
        pub, _agr = create_publisher_with_agreement()
    else:
        pub = create_publisher()
    title = create_title(pub["id"], isbn=isbn)
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    return term, pub, title, faculty, section, opened


def test_adoption_revision_cycle_clears_review_state(api):
    """PRD §3.4: "A returned adoption is not dead: the owning faculty member can
    revise it through the same edit operation, which — when the adoption is
    `RETURNED` and the term is back in `ADOPTION_OPEN` — moves it back to
    `DRAFT`, clears the `review_note`, clears `submitted_at`, resets both late
    flags to false, and increments the adoption's `version`."

    Design: Difficulty/non_linear_state_machine/adoption_revision_cycle
    """
    term, pub, title, faculty, section, opened = _adoption_open_scenario(api)
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=10, qty_used=1, posted_price_cents=9000,
    )
    submit_adoption(adoption["id"], faculty["id"])
    validate_success(api.start_review_adoption(adoption["id"], MANAGER))
    returned = validate_success(
        api.return_adoption(adoption["id"], {"review_note": "fix quantities"}, MANAGER)
    )
    assert returned["status"] == "RETURNED"

    # Revision loop: PATCH from RETURNED moves the adoption back to DRAFT.
    revised = validate_success(
        api.patch_adoption(
            adoption["id"],
            {"qty_used_requested": 3,
             "expected_adoption_version": returned["version"]},
            make_faculty_headers(faculty["id"]),
        )
    )
    assert_adoption(revised)
    assert revised["status"] == "DRAFT"
    assert revised["review_note"] is None
    assert revised["submitted_at"] is None
    assert revised["late_flag"] is False
    assert revised["transparency_late_flag"] is False

    # The cycle closes: DRAFT -> SUBMITTED a second time, edits retained.
    resubmitted = submit_adoption(adoption["id"], faculty["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["qty_used_requested"] == 3
    assert resubmitted["late_flag"] is False


def test_adoption_revision_loop_resets_late_flag_after_late_submit(api):
    """PRD §3.4: "A successful submit stamps `submitted_at` with now, sets
    `late_flag` to true exactly when now is after the term's
    `adoption_deadline_at`, and sets `transparency_late_flag` to true exactly
    when now is after the term's `price_posting_deadline_at`."
    PRD §3.4: "A returned adoption is not dead: the owning faculty member can
    revise it through the same edit operation, which — when the adoption is
    `RETURNED` and the term is back in `ADOPTION_OPEN` — moves it back to
    `DRAFT`, clears the `review_note`, clears `submitted_at`, resets both late
    flags to false, and increments the adoption's `version`."

    Design: Difficulty/non_linear_state_machine/adoption_revision_cycle
    """
    term, pub, title, faculty, section, opened = _adoption_open_scenario(api)
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=10, posted_price_cents=9000,
    )
    # First submission lands after the adoption deadline: late evidence.
    set_clock("2026-06-20T00:00:00Z")
    late = submit_adoption(adoption["id"], faculty["id"])
    assert late["late_flag"] is True
    assert late["transparency_late_flag"] is True

    validate_success(api.start_review_adoption(adoption["id"], MANAGER))
    returned = validate_success(
        api.return_adoption(adoption["id"], {"review_note": "too late"}, MANAGER)
    )
    revised = validate_success(
        api.patch_adoption(
            adoption["id"],
            {"qty_new_requested": 4,
             "expected_adoption_version": returned["version"]},
            make_faculty_headers(faculty["id"]),
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["late_flag"] is False
    assert revised["transparency_late_flag"] is False
    assert revised["submitted_at"] is None

    # Resubmission re-stamps the flags from the current logical time (still
    # past the deadline), proving the loop re-derives them rather than
    # preserving the cleared values.
    resubmitted = submit_adoption(adoption["id"], faculty["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["late_flag"] is True
    assert resubmitted["qty_new_requested"] == 4


def test_adoption_deadline_inclusive_boundary(api):
    """PRD §2.9: "All of these instants are **inclusive** boundaries: an
    adoption whose `submitted_at` is exactly equal to `adoption_deadline_at`
    is on time."
    PRD §3.4: "A successful submit stamps `submitted_at` with now, sets
    `late_flag` to true exactly when now is after the term's
    `adoption_deadline_at`".

    Design: Difficulty/boundary_precision_check/adoption_deadline_inclusive_boundary
    """
    term, pub, title, faculty, section, opened = _adoption_open_scenario(
        api, isbn="9780000000009"
    )
    sec2 = create_section(term["id"], faculty["id"], course_code="CS102")
    opened2 = open_section(sec2["id"])
    ado1 = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=10000,
    )
    ado2 = create_adoption(
        sec2["id"], title["id"], faculty["id"], opened2["version"],
        qty_new=5, posted_price_cents=10000,
    )

    # Exactly at the deadline (2026-06-15T23:59:59Z): on time.
    set_clock("2026-06-15T23:59:59Z")
    on_time = submit_adoption(ado1["id"], faculty["id"])
    assert on_time["late_flag"] is False

    # One second past the deadline: late.
    set_clock("2026-06-16T00:00:00Z")
    late = submit_adoption(ado2["id"], faculty["id"])
    assert late["late_flag"] is True


def test_adoption_deadline_boundary_transparency_flag_pair(api):
    """PRD §3.4: "A successful submit stamps `submitted_at` with now, sets
    `late_flag` to true exactly when now is after the term's
    `adoption_deadline_at`, and sets `transparency_late_flag` to true exactly
    when now is after the term's `price_posting_deadline_at`."
    PRD §2.9: "All of these instants are **inclusive** boundaries: an adoption
    whose `submitted_at` is exactly equal to `adoption_deadline_at` is on time".

    Design: Difficulty/boundary_precision_check/adoption_deadline_inclusive_boundary
    """
    term, pub, title, faculty, section, opened = _adoption_open_scenario(
        api, isbn="9780000000030"
    )
    sec2 = create_section(term["id"], faculty["id"], course_code="CS102")
    opened2 = open_section(sec2["id"])
    ado_at = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=10000,
    )
    ado_past = create_adoption(
        sec2["id"], title["id"], faculty["id"], opened2["version"],
        qty_new=5, posted_price_cents=10000,
    )

    # At the deadline both flags must be false (inclusive boundary), even
    # though the price-posting deadline passed earlier in the calendar.
    set_clock("2026-06-15T23:59:59Z")
    at = submit_adoption(ado_at["id"], faculty["id"])
    assert at["late_flag"] is False
    assert at["transparency_late_flag"] is True

    # One second later flips the deadline flag.
    set_clock("2026-06-16T00:00:00Z")
    past = submit_adoption(ado_past["id"], faculty["id"])
    assert past["late_flag"] is True
    assert past["transparency_late_flag"] is True


def test_occ_adoption_patch_stale_version_rejected(api):
    """PRD §2.7: "Updating an adoption (the quantity/price edit and
    revision-loop operation) requires `expected_adoption_version` matching the
    adoption's current `version`. A client whose quantities and posted price
    derive from an older read is rejected rather than allowed to overwrite an
    adoption it has not observed."

    Design: Corner/cross_cutting_layers/occ_adoption_patch_stale_version_rejected
    """
    term, pub, title, faculty, section, opened = _adoption_open_scenario(
        api, isbn="9780000001019"
    )
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"], qty_new=5,
        posted_price_cents=None,
    )
    # First, well-versioned PATCH succeeds and advances the version.
    first = validate_success(
        api.patch_adoption(
            adoption["id"],
            {"qty_new_requested": 6,
             "expected_adoption_version": adoption["version"]},
            make_faculty_headers(faculty["id"]),
        )
    )
    assert first["qty_new_requested"] == 6

    # Replaying the pre-mutation version is rejected 412; the stale write
    # must not apply.
    resp = api.patch_adoption(
        adoption["id"],
        {"qty_new_requested": 7,
         "expected_adoption_version": adoption["version"]},
        make_faculty_headers(faculty["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(
        api.get_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    )
    assert current["qty_new_requested"] == 6


def test_adoption_supersede_success_and_stale_section_occ(api):
    """PRD §2.7: "Creating an adoption requires `expected_section_version`
    matching the target course section's current `version`. Because creation
    legitimately supersedes a prior approved adoption for the same section and
    title, the client's view of which adoption is in force must be current."
    PRD §3.4: "Creation has a supersede side effect: if an `APPROVED` adoption
    exists for the same section and title, the incoming adoption replaces it —
    the prior adoption moves from `APPROVED` to `SUPERSEDED`, and the prior
    adoption's buy plan, if still `DRAFT`, moves to `CANCELLED`."

    Design: Corner/cross_cutting_layers/adoption_supersede_success_and_stale_section_occ
    """
    term, pub, title, faculty, section, opened = _adoption_open_scenario(
        api, isbn="9780000001022", with_agreement=True
    )
    ado1 = create_approved_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=10000,
    )
    plan = get_success_data(api.get_adoption_buy_plan(ado1["id"], MANAGER))[0]
    assert plan["status"] == "DRAFT"

    # Stale section version (captured before ado1's creation bumped it).
    resp = api.create_adoption(
        {
            "section_id": section["id"],
            "title_id": title["id"],
            "qty_new_requested": 8,
            "qty_used_requested": 0,
            "qty_rental_requested": 0,
            "qty_digital_requested": 0,
            "posted_price_cents": 9900,
            "expected_section_version": opened["version"],
        },
        make_faculty_headers(faculty["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # Fresh section version: creation succeeds and supersedes the APPROVED one.
    fresh_section = get_success_data(
        api.get_section(section["id"], make_faculty_headers(faculty["id"]))
    )
    ado2 = validate_success(
        api.create_adoption(
            {
                "section_id": section["id"],
                "title_id": title["id"],
                "qty_new_requested": 8,
                "qty_used_requested": 0,
                "qty_rental_requested": 0,
                "qty_digital_requested": 0,
                "posted_price_cents": 9900,
                "expected_section_version": fresh_section["version"],
            },
            make_faculty_headers(faculty["id"]),
        ),
        expected_status=201,
    )
    assert ado2["status"] == "DRAFT"
    prior = get_success_data(
        api.get_adoption(ado1["id"], make_faculty_headers(faculty["id"]))
    )
    assert prior["status"] == "SUPERSEDED"
    plans_after = get_success_data(api.get_adoption_buy_plan(ado1["id"], MANAGER))
    assert plans_after[0]["status"] == "CANCELLED"
