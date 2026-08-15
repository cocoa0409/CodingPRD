"""Term and catalog-edition temporal rules: creation defaults, interval
semantics, freeze gating, and the edition freeze-publish-archive lifecycle.
"""
from test_helpers import (
    ApiErrorId,
    TERM_2027FA,
    TERM_2027SP,
    TERM_2027SU,
    advance_through_committee,
    assert_term,
    create_and_activate_new_course,
    create_deactivation_proposal,
    create_department,
    create_edition,
    create_edition_payload,
    create_submitted_new_course_proposal,
    create_term,
    create_term_payload,
    fully_approve_proposal,
    get_course,
    get_success_data,
    is_valid_uuid,
    make_registrar_headers,
    registrar_approve,
    set_clock,
    submit_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_term_applies_defaults(api):
    """PRD §3.1: "A term's lifecycle is `OPEN_FOR_PROPOSALS → PROPOSAL_FROZEN →
    CATALOG_FROZEN`, the last being terminal."
    PRD §3.1: "A term also exposes the computed `scheduled_proposal_count`, the
    number of proposals whose assigned effective term is this one and whose
    status is either `APPROVED` or `EFFECTIVE`."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    one with every mutation of the resource, including mutations caused by
    cascade side effects originating on a different resource."

    Design: Corner/entities/create_term_applies_defaults
    """
    resp = api.create_term(create_term_payload(), make_registrar_headers())
    data = validate_success(resp, 201)
    assert_term(data)
    assert data["status"] == "OPEN_FOR_PROPOSALS"
    assert data["version"] == 1, "a newly created term starts at version 1"
    assert data["scheduled_proposal_count"] == 0


def test_term_sequence_conflict_rejected(api):
    """PRD §3.1: "Three shape rules are enforced at creation and on every
    subsequent edit: `classes_end_date` must be strictly later than
    `classes_start_date`; `proposal_freeze_at` must be at or before
    `catalog_freeze_at`; and `sequence_index` must be unique across all terms,
    with a duplicate rejected as `ERR_TERM_SEQUENCE_CONFLICT`."

    Design: Corner/validations/term_sequence_conflict_rejected
    """
    create_term()
    resp = api.create_term(
        create_term_payload(
            term_code="2027SP", sequence_index=1,
            classes_start_date="2027-01-16", classes_end_date="2027-05-10",
            proposal_freeze_at="2027-02-01T00:00:00Z",
            catalog_freeze_at="2027-05-20T00:00:00Z"),
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_TERM_SEQUENCE_CONFLICT)


def test_freeze_before_date_rejected(api):
    """PRD §3.1: "Freezing proposals for a term is permitted only once the
    logical clock has reached that term's `proposal_freeze_at`; attempted
    earlier, the action is rejected with `ERR_FREEZE_DATE_NOT_REACHED`."

    The logical clock still reads its startup default 2026-08-01T00:00:00Z,
    which precedes the term's 2026-10-01 proposal freeze.

    Design: Corner/validations/freeze_before_date_rejected
    """
    term = create_term()
    resp = api.freeze_proposals(term["id"], make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_FREEZE_DATE_NOT_REACHED)
    assert get_success_data(api.get_term(term["id"],
                                         make_registrar_headers()))["status"] \
        == "OPEN_FOR_PROPOSALS"


def test_term_starting_on_incumbent_end_is_adjacency_not_overlap(api):
    """PRD §3.1: "A new or edited term conflicts with an existing one when its
    start falls before the other's end and its end falls after the other's
    start; because the intervals are half-open, pure adjacency — one term's
    `classes_end_date` exactly equal to another's `classes_start_date` — is not
    a conflict."

    Design: Difficulty/resource_temporal_overlap/term_half_open_adjacency_allowed
    """
    create_term()  # occupies [2026-08-24, 2026-12-15)
    resp = api.create_term(
        create_term_payload(
            term_code="2027SP", sequence_index=2,
            classes_start_date="2026-12-15", classes_end_date="2027-05-10",
            proposal_freeze_at="2027-02-01T00:00:00Z",
            catalog_freeze_at="2027-05-20T00:00:00Z"),
        make_registrar_headers())
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), (
        "a term starting exactly on the incumbent's exclusive end is adjacency")
    assert data["classes_start_date"] == "2026-12-15"


def test_term_overlapping_incumbent_by_one_day_rejected(api):
    """PRD §3.1: "A new or edited term conflicts with an existing one when its
    start falls before the other's end and its end falls after the other's
    start; because the intervals are half-open, pure adjacency — one term's
    `classes_end_date` exactly equal to another's `classes_start_date` — is not
    a conflict. Any genuine overlap is rejected with `ERR_TERM_DATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/term_half_open_adjacency_allowed
    """
    create_term()  # occupies [2026-08-24, 2026-12-15)
    resp = api.create_term(
        create_term_payload(
            term_code="2027WI", sequence_index=3,
            classes_start_date="2026-12-14", classes_end_date="2027-01-15",
            proposal_freeze_at="2026-12-01T00:00:00Z",
            catalog_freeze_at="2027-01-05T00:00:00Z"),
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_TERM_DATE_OVERLAP)


def test_edition_sharing_single_boundary_day_rejected(api):
    """PRD §3.10: "their closed intervals may not overlap (because both ends
    are inclusive, even a single shared day is a conflict)" — enforced, like
    all three window rules, with `ERR_EDITION_WINDOW_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/edition_closed_interval_contiguity_required
    """
    create_edition()  # [2026-08-01, 2027-07-31] closed
    resp = api.create_edition(
        create_edition_payload(
            edition_label="Overlap attempt", academic_year="2027-2028",
            year_start_date="2027-07-31", year_end_date="2028-07-30"),
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_EDITION_WINDOW_CONFLICT)


def test_edition_leaving_one_day_gap_rejected(api):
    """PRD §3.10: "whenever any non-`ARCHIVED` edition exists, the new
    edition's `year_start_date` must be exactly the day after the latest
    non-`ARCHIVED` edition's `year_end_date`, so the published record is
    gap-free".

    Design: Difficulty/resource_temporal_overlap/edition_closed_interval_contiguity_required
    """
    create_edition()  # [2026-08-01, 2027-07-31] closed
    resp = api.create_edition(
        create_edition_payload(
            edition_label="Gap attempt", academic_year="2027-2028",
            year_start_date="2027-08-02", year_end_date="2028-07-31"),
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_EDITION_WINDOW_CONFLICT)


def test_edition_exact_day_after_start_accepted(api):
    """PRD §3.10: "whenever any non-`ARCHIVED` edition exists, the new
    edition's `year_start_date` must be exactly the day after the latest
    non-`ARCHIVED` edition's `year_end_date`, so the published record is
    gap-free".

    Design: Difficulty/resource_temporal_overlap/edition_closed_interval_contiguity_required
    """
    create_edition()  # [2026-08-01, 2027-07-31] closed
    resp = api.create_edition(
        create_edition_payload(
            edition_label="2027-2028 Catalog", academic_year="2027-2028",
            year_start_date="2027-08-01", year_end_date="2028-07-31"),
        make_registrar_headers())
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"])
    assert data["status"] == "DRAFT"


# -------------------------------------------------------------------------
# Edition freeze / publish cascades
# -------------------------------------------------------------------------

def _setup_two_published_pipeline(api):
    """Build the full two-edition pipeline and freeze E2, leaving E2 ready to
    publish. Returns every id and captured value the publish tests need."""
    dept = create_department()
    t1 = create_term()
    t2 = create_term(TERM_2027SP)
    t3 = create_term(TERM_2027SU)
    t4 = create_term(TERM_2027FA)
    e1 = create_edition()
    e2 = create_edition(
        edition_label="2027-2028 Catalog", academic_year="2027-2028",
        year_start_date="2027-08-01", year_end_date="2028-07-31")

    # K (CS 550): NEW_COURSE proposal effective in T1 -> STAGED entry in E1.
    activated1, course_k = create_and_activate_new_course(
        dept["id"], t1["id"], "550", proposed_title="K",
        learning_outcomes=["k"], justification="new")

    # K2 (CS 551): second NEW_COURSE proposal requesting T4 (still OPEN),
    # registrar-approved into T4.
    proposal2 = create_submitted_new_course_proposal(
        dept["id"], t4["id"], "551", proposed_title="K2",
        learning_outcomes=["k2"], justification="new")
    fully_approve_proposal(proposal2["id"], dept["id"], t4["id"])

    # Freeze every 2026-2027 term end-to-end, then freeze and publish E1.
    set_clock("2027-07-02T00:00:00Z")
    reg = make_registrar_headers()
    get_success_data(api.freeze_proposals(t2["id"], reg))
    get_success_data(api.freeze_catalog(t2["id"], reg))
    get_success_data(api.freeze_proposals(t3["id"], reg))
    get_success_data(api.freeze_catalog(t3["id"], reg))
    get_success_data(api.freeze_catalog(t1["id"], reg))
    e1_frozen = validate_success(api.freeze_edition(e1["id"], reg))
    e1_count = e1_frozen["included_entry_count"]
    get_success_data(api.publish_edition(e1["id"], reg))

    # Lock T4, activate K2's proposal (stages an entry into DRAFT E2), then
    # freeze E2 once T4 is CATALOG_FROZEN.
    set_clock("2027-10-02T00:00:00Z")
    get_success_data(api.freeze_proposals(t4["id"], reg))
    get_success_data(api.activate_proposal(proposal2["id"], reg))
    courses, _ = validate_paginated(
        api.list_courses(reg, params={"subject_code": "CS",
                                      "course_number": "551"}))
    course_k2 = courses[0]
    set_clock("2027-11-02T00:00:00Z")
    get_success_data(api.freeze_catalog(t4["id"], reg))
    get_success_data(api.freeze_edition(e2["id"], reg))

    return {
        "dept": dept, "t1": t1, "t2": t2, "t3": t3, "t4": t4,
        "e1": e1, "e2": e2, "course_k": course_k, "course_k2": course_k2,
        "e1_count": e1_count,
    }


def test_edition_publish_cascades_entries_and_stamps_courses(api):
    """PRD §3.10: "Publishing moves the edition `FROZEN → PUBLISHED` and
    cascades in two hops. First, every `INCLUDED` entry in the edition becomes
    `PUBLISHED`; second, each newly published entry stamps its course's
    `last_published_edition_id` with this edition's `id` and increments that
    course's `version`."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    one with every mutation of the resource, including mutations caused by
    cascade side effects originating on a different resource."

    Design: Difficulty/transitive_cascade/edition_publish_cascade_depth2
    """
    ctx = _setup_two_published_pipeline(api)
    reg = make_registrar_headers()

    published = validate_success(api.publish_edition(ctx["e2"]["id"], reg))
    assert published["status"] == "PUBLISHED"

    entries, _ = validate_paginated(
        api.list_catalog_entries(reg, params={"edition_id": ctx["e2"]["id"]}))
    assert entries[0]["status"] == "PUBLISHED", "hop 1: INCLUDED -> PUBLISHED"

    k2 = get_course(ctx["course_k2"]["id"])
    assert k2["last_published_edition_id"] == ctx["e2"]["id"], (
        "hop 2: the newly published entry stamps its course")
    assert k2["version"] == 2, (
        "course created at version 1 by activation; the publish stamp is the "
        "only later mutation")


def test_edition_publish_archives_previous_edition_and_entries(api):
    """PRD §3.10: "Publication simultaneously retires the old record in an
    archive arm: the previously `PUBLISHED` edition, if any, becomes
    `ARCHIVED`, and every entry in that archived edition still in `PUBLISHED`
    status becomes `ARCHIVED`."
    PRD §3.10: "The sweep then sets the edition's `included_entry_count` to the
    number of its `INCLUDED` entries, and increments the edition's `version`."

    Design: Difficulty/transitive_cascade/edition_publish_cascade_depth2
    """
    ctx = _setup_two_published_pipeline(api)
    reg = make_registrar_headers()
    assert ctx["e1_count"] == 1, (
        "the freeze sweep included the single STAGED entry whose course was "
        "ACTIVE")

    validate_success(api.publish_edition(ctx["e2"]["id"], reg))

    e1_entries, _ = validate_paginated(
        api.list_catalog_entries(reg, params={"edition_id": ctx["e1"]["id"]}))
    assert e1_entries[0]["status"] == "ARCHIVED", (
        "archive-arm hop 2: the archived edition's PUBLISHED entry is archived")

    k = get_course(ctx["course_k"]["id"])
    assert k["last_published_edition_id"] == ctx["e1"]["id"], (
        "the archive arm flips entry statuses but never re-points the course's "
        "last_published_edition_id")


# -------------------------------------------------------------------------
# Edition freeze sweep input filtering
# -------------------------------------------------------------------------

def _setup_freeze_sweep_scenario(api):
    """E1 holds K1's STAGED entry (course ACTIVE) and K2's entry, the latter
    already EXCLUDED by K2's deactivation cascade; all 2026-2027 terms are
    CATALOG_FROZEN so E1 is ready to freeze."""
    dept = create_department()
    t1 = create_term()
    t2 = create_term(TERM_2027SP)
    t3 = create_term(TERM_2027SU)
    e1 = create_edition()

    # K1 (CS 551) activates into E1 while T1 is the effective term.
    _act1, course_k1 = create_and_activate_new_course(
        dept["id"], t1["id"], "551", proposed_title="K1",
        learning_outcomes=["k1"], justification="x")

    # K2 (CS 552) requests the still-OPEN spring term but is registrar-approved
    # into the frozen fall term, so its entry also lands in E1.
    proposal_k2 = create_submitted_new_course_proposal(
        dept["id"], t2["id"], "552", proposed_title="K2",
        learning_outcomes=["k2"], justification="x")
    fully_approve_proposal(proposal_k2["id"], dept["id"], t1["id"])
    reg = make_registrar_headers()
    get_success_data(api.activate_proposal(proposal_k2["id"], reg))
    courses, _ = validate_paginated(
        api.list_courses(reg, params={"subject_code": "CS",
                                      "course_number": "552"}))
    course_k2 = courses[0]

    # Deactivate K2 with zero remaining cohorts: course -> DEACTIVATING and
    # its STAGED entry cascade-excluded.
    proposal_d = create_deactivation_proposal(
        dept["id"], t2["id"], course_k2["id"], 0,
        justification="no students")
    submit_proposal(proposal_d["id"])
    advance_through_committee(proposal_d["id"], dept["id"])
    registrar_approve(proposal_d["id"], t1["id"])
    get_success_data(api.activate_proposal(proposal_d["id"], reg))

    # Freeze the whole academic year, then E1 is freezable.
    set_clock("2027-07-02T00:00:00Z")
    get_success_data(api.freeze_catalog(t1["id"], reg))
    get_success_data(api.freeze_proposals(t2["id"], reg))
    get_success_data(api.freeze_catalog(t2["id"], reg))
    get_success_data(api.freeze_proposals(t3["id"], reg))
    get_success_data(api.freeze_catalog(t3["id"], reg))

    return {"dept": dept, "t1": t1, "e1": e1,
            "course_k1": course_k1, "course_k2": course_k2}


def test_edition_freeze_sweep_filters_staged_entries(api):
    """PRD §3.10: "The freeze runs the snapshot sweep over the edition's
    entries in entry-creation order: each `STAGED` entry whose course is
    `ACTIVE` or `DEACTIVATING` becomes `INCLUDED`, while an entry whose course
    is `INACTIVE` becomes `EXCLUDED`; entries in other statuses are untouched.
    The sweep then sets the edition's `included_entry_count` to the number of
    its `INCLUDED` entries, and increments the edition's `version`."

    Design: Corner/calculations/edition_freeze_sweep_filters_staged_entries
    """
    ctx = _setup_freeze_sweep_scenario(api)
    reg = make_registrar_headers()

    frozen = validate_success(api.freeze_edition(ctx["e1"]["id"], reg))
    assert frozen["status"] == "FROZEN"
    assert frozen["included_entry_count"] == 1, (
        "only K1's STAGED entry was sweep-eligible; K2's pre-EXCLUDED row is "
        "untouched")

    included, _ = validate_paginated(
        api.list_catalog_entries(reg, params={"edition_id": ctx["e1"]["id"],
                                              "status": "INCLUDED"}))
    assert [e["course_number"] for e in included] == ["551"]
    excluded, _ = validate_paginated(
        api.list_catalog_entries(reg, params={"edition_id": ctx["e1"]["id"],
                                              "status": "EXCLUDED"}))
    assert [e["course_number"] for e in excluded] == ["552"]
