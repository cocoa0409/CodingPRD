"""Course import uniqueness, activation preconditions, the prerequisite
cycle check over the active graph, and the cross-listing approval diamond.
"""
from test_helpers import (
    ApiErrorId,
    advance_through_committee,
    assert_cross_listing,
    create_course_change_proposal,
    create_department,
    create_pending_cross_listing,
    create_submitted_new_course_proposal,
    create_term,
    create_term_2027sp,
    freeze_term_proposals,
    fully_approve_proposal,
    get_proposal,
    get_success_data,
    import_course,
    make_chair_headers,
    make_registrar_headers,
    registrar_approve,
    setup_cross_listing_pair,
    submit_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_course_import_rejected(api):
    """PRD §3.2: "This import path is how the initial catalog is loaded, and it
    enforces the same course-number uniqueness rule as the proposal pipeline —
    an attempt to import a number already held is rejected with
    `ERR_COURSE_NUMBER_HELD`."

    Design: Corner/validations/duplicate_course_import_rejected
    """
    dept = create_department()
    term = create_term()
    import_course(dept["id"], term["id"], course_number="301", title="First")

    resp = api.create_course(
        {
            "subject_code": "CS", "course_number": "301", "title": "Duplicate",
            "credit_hours": 3, "contact_hours_per_week": 3,
            "out_of_class_hours_per_week": 6, "learning_outcomes": ["x"],
            "owning_department_id": dept["id"],
            "introduced_in_term_id": term["id"],
        },
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_COURSE_NUMBER_HELD)


def test_activate_with_unlocked_term_rejected(api):
    """PRD §3.7: "Activation requires the assigned effective term to be locked,
    meaning its status is `PROPOSAL_FROZEN` or `CATALOG_FROZEN`; activating
    against an unlocked term is rejected with `ERR_TERM_NOT_LOCKED`."

    Design: Corner/state_machines/activate_with_unlocked_term_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450", proposed_title="A",
                                                    learning_outcomes=["a"])
    fully_approve_proposal(proposal["id"], dept["id"], term["id"])

    resp = api.activate_proposal(proposal["id"], make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_LOCKED)
    assert get_proposal(proposal["id"])["status"] == "APPROVED"
    courses, _ = validate_paginated(
        api.list_courses(make_registrar_headers(),
                         params={"course_number": "450"}))
    assert courses == [], "a rejected activation materializes no course"


# -------------------------------------------------------------------------
# Prerequisite DAG: linear chain accepted
# -------------------------------------------------------------------------

def test_prerequisite_chain_dag_accepted(api):
    """PRD §3.2: "Two system-maintained fields round out the record:
    `prerequisite_summary`, a comma-joined list of `SUBJ NUM` codes drawn from
    the requisite courses of the course's active prerequisite links in the
    order those links were created (empty string when the course has none)".
    PRD §3.7: "the candidate link closes a cycle if its course end is reachable
    from its requisite end following graph edges from a course to its
    requisite."

    Design: Corner/calculations/prerequisite_chain_dag_accepted
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    course_c = import_course(dept["id"], t1["id"], course_number="101",
                             title="C", learning_outcomes=["c"])

    # B (CS 201) requires C; activated once T1 is frozen.
    proposal_b = create_submitted_new_course_proposal(
        dept["id"], t1["id"], "201", proposed_title="B",
        learning_outcomes=["b"],
        proposed_requisites=[{"requisite_course_id": course_c["id"],
                              "requisite_type": "PREREQUISITE"}])
    fully_approve_proposal(proposal_b["id"], dept["id"], t1["id"])
    freeze_term_proposals(t1["id"])
    reg = make_registrar_headers()
    get_success_data(api.activate_proposal(proposal_b["id"], reg))
    courses, _ = validate_paginated(
        api.list_courses(reg, params={"subject_code": "CS",
                                      "course_number": "201"}))
    course_b = courses[0]
    assert course_b["prerequisite_summary"] == "CS 101"

    # A (CS 301) requires B; drafted against the still-OPEN spring term and
    # registrar-approved into the frozen fall term.
    proposal_a = create_submitted_new_course_proposal(
        dept["id"], t2["id"], "301", proposed_title="A",
        learning_outcomes=["a"],
        proposed_requisites=[{"requisite_course_id": course_b["id"],
                              "requisite_type": "PREREQUISITE"}])
    fully_approve_proposal(proposal_a["id"], dept["id"], t1["id"])

    activated = validate_success(api.activate_proposal(proposal_a["id"], reg))
    assert activated["status"] == "EFFECTIVE", (
        "a linear chain C <- B <- A closes no cycle")
    courses, _ = validate_paginated(
        api.list_courses(reg, params={"subject_code": "CS",
                                      "course_number": "301"}))
    assert courses[0]["prerequisite_summary"] == "CS 201"


# -------------------------------------------------------------------------
# Cycle detection and the COREQUISITE exemption
# -------------------------------------------------------------------------

def _approve_change_on_b(api, dept, t_requested, t_effective, course_b,
                         course_a, requisite_type):
    """COURSE_CHANGE on B adding a link to A, fully approved with the frozen
    fall term as effective term."""
    proposal_b = create_course_change_proposal(
        dept["id"], t_requested["id"], course_b["id"],
        proposed_course_number="302", proposed_title="B",
        learning_outcomes=["b"], justification="co-taught lab",
        proposed_requisites=[{"requisite_course_id": course_a["id"],
                              "requisite_type": requisite_type}])
    submit_proposal(proposal_b["id"])
    advance_through_committee(proposal_b["id"], dept["id"])
    registrar_approve(proposal_b["id"], t_effective["id"])
    return proposal_b


def test_prerequisite_cycle_activation_rejected(api):
    """PRD §3.7: "In both cases the proposal's `PROPOSED` links are then
    flipped to `ACTIVE` one at a time in link-creation order, and before each
    flip the **prerequisite cycle check** runs: the active prerequisite graph
    is the set of links with status `ACTIVE` and type `PREREQUISITE`, plus any
    links of this same proposal already activated earlier in the batch; the
    candidate link closes a cycle if its course end is reachable from its
    requisite end following graph edges from a course to its requisite."
    PRD §3.7: "If any candidate would close a cycle, the entire activation
    aborts with `ERR_REQUISITE_CYCLE`."

    Design: Corner/calculations/prerequisite_cycle_activation_rejected
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    course_a = import_course(dept["id"], t1["id"], course_number="301",
                             title="A", learning_outcomes=["a"])
    course_b = import_course(dept["id"], t1["id"], course_number="302",
                             title="B", learning_outcomes=["b"])
    proposal_a = create_course_change_proposal(
        dept["id"], t1["id"], course_a["id"],
        proposed_course_number="301", proposed_title="A",
        learning_outcomes=["a"], justification="add prereq",
        proposed_requisites=[{"requisite_course_id": course_b["id"],
                              "requisite_type": "PREREQUISITE"}])
    submit_proposal(proposal_a["id"])
    fully_approve_proposal(proposal_a["id"], dept["id"], t1["id"])
    freeze_term_proposals(t1["id"])
    reg = make_registrar_headers()
    get_success_data(api.activate_proposal(proposal_a["id"], reg))

    # B -> A as PREREQUISITE would close A -> B -> A; drafted against the
    # still-OPEN spring term, approved into the frozen fall term.
    proposal_b = _approve_change_on_b(api, dept, t2, t1, course_b, course_a,
                                      "PREREQUISITE")

    resp = api.activate_proposal(proposal_b["id"], reg)
    validate_error(resp, ApiErrorId.ERR_REQUISITE_CYCLE)
    assert get_proposal(proposal_b["id"])["status"] == "APPROVED", (
        "the whole activation aborts")
    links, _ = validate_paginated(
        api.list_proposal_requisites(proposal_b["id"], reg))
    assert len(links) == 1
    assert links[0]["status"] == "PROPOSED", "no link flips on an aborted batch"


def test_corequisite_edge_exempt_from_cycle(api):
    """PRD §3.7: "`COREQUISITE` links never participate — neither as
    candidates nor as traversal edges."

    Design: Corner/calculations/corequisite_edge_exempt_from_cycle
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    course_a = import_course(dept["id"], t1["id"], course_number="301",
                             title="A", learning_outcomes=["a"])
    course_b = import_course(dept["id"], t1["id"], course_number="302",
                             title="B", learning_outcomes=["b"])
    proposal_a = create_course_change_proposal(
        dept["id"], t1["id"], course_a["id"],
        proposed_course_number="301", proposed_title="A",
        learning_outcomes=["a"], justification="add prereq",
        proposed_requisites=[{"requisite_course_id": course_b["id"],
                              "requisite_type": "PREREQUISITE"}])
    submit_proposal(proposal_a["id"])
    fully_approve_proposal(proposal_a["id"], dept["id"], t1["id"])
    freeze_term_proposals(t1["id"])
    reg = make_registrar_headers()
    get_success_data(api.activate_proposal(proposal_a["id"], reg))

    # B -> A as COREQUISITE never enters the cycle graph.
    proposal_b = _approve_change_on_b(api, dept, t2, t1, course_b, course_a,
                                      "COREQUISITE")

    activated = validate_success(api.activate_proposal(proposal_b["id"], reg))
    assert activated["status"] == "EFFECTIVE"
    links, _ = validate_paginated(
        api.list_proposal_requisites(proposal_b["id"], reg))
    assert len(links) == 1
    assert links[0]["status"] == "ACTIVE"
    assert links[0]["requisite_type"] == "COREQUISITE"


# -------------------------------------------------------------------------
# Cross-listing diamond with rescind
# -------------------------------------------------------------------------

def _setup_two_cross_listings(api):
    """Departments CS/MATH, one term, ACTIVE courses C1/C2 (CS) and M1/M2
    (MATH); XL1 pairs (C1, M1), XL2 pairs (C2, M2)."""
    dept_cs = create_department()
    dept_math = create_department(dept_name="Mathematics",
                                  subject_codes=["MATH"], college="Sciences")
    term = create_term()
    c1 = import_course(dept_cs["id"], term["id"], course_number="301",
                       title="C1", learning_outcomes=["x"])
    c2 = import_course(dept_cs["id"], term["id"], course_number="302",
                       title="C2", learning_outcomes=["x"])
    m1 = import_course(dept_math["id"], term["id"], subject_code="MATH",
                       course_number="210", title="M1", learning_outcomes=["x"])
    m2 = import_course(dept_math["id"], term["id"], subject_code="MATH",
                       course_number="211", title="M2", learning_outcomes=["x"])
    xl1 = create_pending_cross_listing(c1["id"], m1["id"], dept_cs["id"])
    xl2 = create_pending_cross_listing(c2["id"], m2["id"], dept_cs["id"])
    return dept_cs, dept_math, xl1, xl2


def test_cross_listing_partner_first_converges_to_active(api):
    """PRD §3.9: "From `PENDING`, the home chair's approval — identified by
    `X-User-ID` matching `home_department_id` — moves the listing to
    `HOME_APPROVED` and stamps `home_approved_by`; the partner chair's approval
    moves it to `PARTNER_APPROVED` and stamps `partner_approved_by`. Whichever
    side approved first, the second side's approval moves the listing to
    `ACTIVE`, provided both courses are still `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/cross_listing_diamond_with_rescind
    """
    dept_cs, dept_math, xl1, _xl2 = _setup_two_cross_listings(api)

    mid = validate_success(
        api.approve_cross_listing(xl1["id"], make_chair_headers(dept_math["id"])))
    assert mid["status"] == "PARTNER_APPROVED", "partner-first branch"
    assert mid["partner_approved_by"] == dept_math["id"]

    final = validate_success(
        api.approve_cross_listing(xl1["id"], make_chair_headers(dept_cs["id"])))
    assert final["status"] == "ACTIVE", "the second side joins the fork"
    assert final["home_approved_by"] == dept_cs["id"]
    assert final["partner_approved_by"] == dept_math["id"]
    assert_cross_listing(final)


def test_cross_listing_rescind_reverts_to_pending(api):
    """PRD §3.9: "A side may also walk back its own approval: rescinding from
    `HOME_APPROVED` (by the home chair) or from `PARTNER_APPROVED` (by the
    partner chair) returns the listing to `PENDING` and clears that side's
    approval stamp to null."

    Design: Difficulty/non_linear_state_machine/cross_listing_diamond_with_rescind
    """
    dept_cs, dept_math, _xl1, xl2 = _setup_two_cross_listings(api)

    home = validate_success(
        api.approve_cross_listing(xl2["id"], make_chair_headers(dept_cs["id"])))
    assert home["status"] == "HOME_APPROVED"

    back = validate_success(
        api.rescind_cross_listing(xl2["id"], make_chair_headers(dept_cs["id"])))
    assert back["status"] == "PENDING", "rescind reverts the fork"
    assert back["home_approved_by"] is None

    partner = validate_success(
        api.approve_cross_listing(xl2["id"],
                                  make_chair_headers(dept_math["id"])))
    assert partner["status"] == "PARTNER_APPROVED"
    final = validate_success(
        api.approve_cross_listing(xl2["id"], make_chair_headers(dept_cs["id"])))
    assert final["status"] == "ACTIVE", (
        "partner-then-home order converges to the same join")
    assert final["home_approved_by"] == dept_cs["id"]
    assert final["partner_approved_by"] == dept_math["id"]


def test_duplicate_cross_listing_rejected(api):
    """PRD §3.9: "Only one non-terminal listing may exist per unordered course
    pair: if a listing for the same pair already exists in `PENDING`,
    `HOME_APPROVED`, `PARTNER_APPROVED`, or `ACTIVE` status, creation is
    rejected with `ERR_CROSS_LISTING_EXISTS`."

    Design: Corner/errors/duplicate_cross_listing_rejected
    """
    ctx = setup_cross_listing_pair()
    create_pending_cross_listing(ctx["home_course"]["id"],
                                 ctx["partner_course"]["id"],
                                 ctx["dept_home"]["id"])

    # Reversed order is still the same unordered pair.
    resp = api.create_cross_listing(
        {"home_course_id": ctx["partner_course"]["id"],
         "partner_course_id": ctx["home_course"]["id"]},
        make_chair_headers(ctx["dept_partner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CROSS_LISTING_EXISTS)
