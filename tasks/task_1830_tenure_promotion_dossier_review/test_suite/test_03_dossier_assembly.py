"""Dossier assembly: evidence lifecycle, supersede lineage, completeness gates,
the strength index, the revision loop, and item-creation OCC (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_dossier_item,
    assert_decimal_eq,
    assert_dossier_item,
    assert_instant_eq,
    build_dossier,
    build_standard_dossier,
    make_candidate_headers,
    open_case,
    read_case,
    read_case_version,
    register_candidate,
    set_logical_clock,
    setup_external_review_case,
    submit_dossier,
    submit_dossier_item,
    validate_error,
    validate_paginated,
    validate_success,
)

PO_HEADERS = TEST_USERS["provost_creator_headers"]


def test_supersede_lineage_cascade_and_reverse_lookup(api, reader_headers):
    """PRD §3.2: "Submission is also where the supersede cascade fires: when the
    submitted item carries a `supersedes_item_id`, the target must be a
    `SUBMITTED` item of the same case and the same category, in which case the
    target flips to `SUPERSEDED`".
    PRD §2.3: "the dossier item list accepts `case_id`, `supersedes_item_id`,
    `status`, and `category`".

    Design: Corner/entities/supersede_lineage_cascade_and_reverse_lookup
    """
    candidate = register_candidate("E9005", full_name="Cand U")
    case = open_case(candidate["id"])
    item_a = add_dossier_item(
        case["id"], candidate["id"], "RESEARCH", "Paper v1",
        page_count=12, is_peer_reviewed=True,
    )
    item_a = submit_dossier_item(item_a["id"], candidate["id"])
    item_b = add_dossier_item(
        case["id"], candidate["id"], "RESEARCH", "Paper v2",
        page_count=14, is_peer_reviewed=True, supersedes_item_id=item_a["id"],
    )

    item_b = submit_dossier_item(item_b["id"], candidate["id"])
    assert item_b["status"] == "SUBMITTED"

    data_a = validate_success(api.get_dossier_item(item_a["id"], reader_headers))
    assert data_a["status"] == "SUPERSEDED", (
        f"Supersede target must flip to SUPERSEDED, got {data_a['status']}"
    )

    successors, meta = validate_paginated(
        api.list_dossier_items(reader_headers, {"supersedes_item_id": item_a["id"]})
    )
    assert meta["total_count"] == 1
    assert successors[0]["id"] == item_b["id"]


def test_supersede_target_invalid_states_rejected(api, reader_headers):
    """PRD §3.2: "when the submitted item carries a `supersedes_item_id`, the
    target must be a `SUBMITTED` item of the same case and the same category, in
    which case the target flips to `SUPERSEDED`; if the target is anything else
    the submission fails with `ERR_SUPERSEDE_TARGET_INVALID`."

    Design: Corner/entities/supersede_target_invalid_states_rejected
    """
    candidate = register_candidate("E9006", full_name="Cand Y")
    case = open_case(candidate["id"])
    draft_target = add_dossier_item(
        case["id"], candidate["id"], "RESEARCH", "Draft target"
    )
    teaching_target = submit_dossier_item(
        add_dossier_item(case["id"], candidate["id"], "TEACHING", "Teaching item")["id"],
        candidate["id"],
    )
    succ_to_draft = add_dossier_item(
        case["id"], candidate["id"], "RESEARCH", "Succ to draft",
        supersedes_item_id=draft_target["id"],
    )
    succ_cross = add_dossier_item(
        case["id"], candidate["id"], "RESEARCH", "Succ cross-category",
        supersedes_item_id=teaching_target["id"],
    )

    err_draft = api.submit_dossier_item(
        succ_to_draft["id"], make_candidate_headers(candidate["id"])
    )
    validate_error(err_draft, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)

    err_cross = api.submit_dossier_item(
        succ_cross["id"], make_candidate_headers(candidate["id"])
    )
    validate_error(err_cross, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)

    data_c = validate_success(api.get_dossier_item(draft_target["id"], reader_headers))
    data_d = validate_success(api.get_dossier_item(teaching_target["id"], reader_headers))
    assert data_c["status"] == "DRAFT", "Failed supersede must not cascade"
    assert data_d["status"] == "SUBMITTED", "Failed supersede must not cascade"


def test_dossier_item_return_resubmit_cycle(api):
    """PRD §3.2: "The owning candidate submits a `DRAFT` or `RETURNED` item,
    moving it to `SUBMITTED`; the provost office returns a `SUBMITTED` item,
    moving it back to `RETURNED`".

    Design: Corner/state_machines/dossier_item_return_resubmit_cycle
    """
    candidate = register_candidate("E9101", full_name="Cand RR")
    case = open_case(candidate["id"])
    item = add_dossier_item(
        case["id"], candidate["id"], "TEACHING", "Syllabus", page_count=6
    )
    submit_dossier_item(item["id"], candidate["id"])

    returned = validate_success(api.return_dossier_item(item["id"], PO_HEADERS))
    assert returned["status"] == "RETURNED"

    resubmitted = validate_success(
        api.submit_dossier_item(item["id"], make_candidate_headers(candidate["id"]))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["category"] == "TEACHING"


def test_withdrawn_case_terminal_lockdown(api):
    """PRD §3.9: "Every withdrawal moves the case to the terminal `WITHDRAWN`
    stage, moves the candidate's `status` to `WITHDRAWN`, cancels the case's
    still-`PENDING` clock-extension requests, and increments the case's `version`
    by one."
    PRD §3.2: "All item mutations require the case to be in `DOSSIER_ASSEMBLY` —
    any other stage is rejected with `ERR_CASE_STAGE_FORBIDDEN`".

    Design: Corner/state_machines/withdrawn_case_terminal_lockdown
    """
    candidate = register_candidate("E9102", full_name="Cand WD")
    case = open_case(candidate["id"])
    validate_success(
        api.withdraw_case(case["id"], make_candidate_headers(candidate["id"]))
    )

    err_submit = api.submit_dossier(
        case["id"], make_candidate_headers(candidate["id"])
    )
    validate_error(err_submit, ApiErrorId.ERR_CASE_STAGE_FORBIDDEN)

    err_create = api.create_dossier_item(
        {
            "case_id": case["id"],
            "category": "TEACHING",
            "title": "Late",
            "page_count": 3,
            "expected_case_version": read_case_version(case["id"]),
        },
        make_candidate_headers(candidate["id"]),
    )
    validate_error(err_create, ApiErrorId.ERR_CASE_STAGE_FORBIDDEN)

    candidate_after = validate_success(api.get_candidate(candidate["id"], PO_HEADERS))
    assert candidate_after["status"] == "WITHDRAWN"


def test_submit_dossier_twice_rejected(api):
    """PRD §2.12: "The case's `stage` must permit the operation — dossier item
    mutations require assembly, extension requests require a pre-decision stage,
    invitation creation requires external review, decision recording requires
    provost review, and so on — otherwise `ERR_CASE_STAGE_FORBIDDEN`
    (HTTP 409)."

    Design: Corner/state_machines/submit_dossier_twice_rejected
    """
    ctx = setup_external_review_case("E9100", full_name="Cand 2X")
    err = api.submit_dossier(
        ctx["case"]["id"], make_candidate_headers(ctx["candidate"]["id"])
    )
    validate_error(err, ApiErrorId.ERR_CASE_STAGE_FORBIDDEN)
    assert read_case(ctx["case"]["id"])["stage"] == "EXTERNAL_REVIEW"


def test_completeness_requires_peer_reviewed_research(api):
    """PRD §3.2: "the dossier must contain at least two `TEACHING` items, at
    least three `RESEARCH` items, and at least one `SERVICE` item, and at least
    one of the `SUBMITTED` `RESEARCH` items must have `is_peer_reviewed` set to
    true; counts exactly equal to a minimum pass, and any shortfall is rejected
    with `ERR_DOSSIER_INCOMPLETE`."

    Design: Corner/calculations/completeness_requires_peer_reviewed_research
    """
    set_logical_clock()
    candidate = register_candidate("E9200", full_name="Cand PR")
    case = open_case(candidate["id"])
    build_dossier(
        case["id"],
        candidate["id"],
        [
            {"category": "TEACHING", "title": "T1"},
            {"category": "TEACHING", "title": "T2"},
            {"category": "RESEARCH", "title": "R1", "page_count": 12},
            {"category": "RESEARCH", "title": "R2", "page_count": 12},
            {"category": "RESEARCH", "title": "R3", "page_count": 12},
            {"category": "SERVICE", "title": "S1", "page_count": 5},
        ],
    )
    err = api.submit_dossier(case["id"], make_candidate_headers(candidate["id"]))
    validate_error(err, ApiErrorId.ERR_DOSSIER_INCOMPLETE)
    assert read_case(case["id"])["stage"] == "DOSSIER_ASSEMBLY"


def test_review_clock_expired_submit_rejected(api):
    """PRD §3.2: "And the logical clock must not have passed the case's
    `mandatory_review_date`; a submission after that date is rejected with
    `ERR_REVIEW_CLOCK_EXPIRED`."

    Design: Corner/validations/review_clock_expired_submit_rejected
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    candidate = register_candidate("E9304", full_name="Cand RC")
    case = open_case(candidate["id"], clock_policy="ANNIVERSARY")
    build_standard_dossier(case["id"], candidate["id"])

    set_logical_clock("2026-08-02T00:00:00Z")  # one day past 2026-08-01
    err = api.submit_dossier(case["id"], make_candidate_headers(candidate["id"]))
    validate_error(err, ApiErrorId.ERR_REVIEW_CLOCK_EXPIRED)
    assert read_case(case["id"])["stage"] == "DOSSIER_ASSEMBLY"


class TestLateItemSubmitRequiresAssembly:
    def test_late_draft_item_submit_rejected_after_dossier_submission(self, api):
        """PRD §3.2: "All item mutations require the case to be in
        `DOSSIER_ASSEMBLY` — any other stage is rejected with
        `ERR_CASE_STAGE_FORBIDDEN`".

        Design: Difficulty/cross_entity_state_dependency/dossier_item_submit_requires_case_assembly
        """
        set_logical_clock()
        candidate = register_candidate("E1600", full_name="Cand G")
        case = open_case(candidate["id"])
        build_standard_dossier(case["id"], candidate["id"])
        late = add_dossier_item(
            case["id"], candidate["id"], "TEACHING", "T3 late", page_count=4
        )
        submit_dossier(case["id"], candidate["id"])

        err = api.submit_dossier_item(
            late["id"], make_candidate_headers(candidate["id"])
        )
        validate_error(err, ApiErrorId.ERR_CASE_STAGE_FORBIDDEN)

    def test_rejected_late_submit_leaves_item_draft(self, api, reader_headers):
        """PRD §3.2: "All item mutations require the case to be in
        `DOSSIER_ASSEMBLY` — any other stage is rejected with
        `ERR_CASE_STAGE_FORBIDDEN`".

        Design: Difficulty/cross_entity_state_dependency/dossier_item_submit_requires_case_assembly
        """
        set_logical_clock()
        candidate = register_candidate("E1601", full_name="Cand G2")
        case = open_case(candidate["id"])
        build_standard_dossier(case["id"], candidate["id"])
        late = add_dossier_item(
            case["id"], candidate["id"], "TEACHING", "T3 late", page_count=4
        )
        submit_dossier(case["id"], candidate["id"])

        api.submit_dossier_item(late["id"], make_candidate_headers(candidate["id"]))
        item = validate_success(api.get_dossier_item(late["id"], reader_headers))
        assert item["status"] == "DRAFT", "Rejected transition must not mutate"


class TestDossierStrengthIndex:
    def test_pinned_rounding_order_yields_14835(self, api):
        """PRD §3.2: "The evaluation order is pinned: each ratio is rounded to
        three decimal places first, before weighting and summation. Summing the
        unrounded ratios and rounding only the total is a forbidden variant — a
        dossier with three teaching items, five research items, and one service
        item yields 1.4835 under the pinned order, where the forbidden variant
        would produce 1.4833."

        Design: Difficulty/combinatorial_formula/dossier_strength_per_category_rounding_order
        """
        ctx = setup_external_review_case(
            "E400",
            full_name="Cand S",
            dossier_spec=[
                {"category": "TEACHING", "title": "T1"},
                {"category": "TEACHING", "title": "T2"},
                {"category": "TEACHING", "title": "T3", "page_count": 8},
                {"category": "RESEARCH", "title": "R1", "page_count": 12,
                 "is_peer_reviewed": True},
                {"category": "RESEARCH", "title": "R2", "page_count": 12},
                {"category": "RESEARCH", "title": "R3", "page_count": 12},
                {"category": "RESEARCH", "title": "R4", "page_count": 9},
                {"category": "RESEARCH", "title": "R5", "page_count": 9},
                {"category": "SERVICE", "title": "S1", "page_count": 5},
            ],
        )
        case = ctx["case"]
        assert case["stage"] == "EXTERNAL_REVIEW"
        # T3/R5/S1: ratios 1.5, 1.667 (5/3 rounded 3dp), 1.0 ->
        # 0.45 + 0.8335 + 0.20 = 1.4835 (pinned), not 1.4833 (unpinned).
        assert_decimal_eq(case["dossier_strength_index"], 1.4835, "dossier_strength_index")

    def test_ratio_cap_limits_category_contribution(self, api):
        """PRD §3.2: "For each category, the system divides the number of
        qualifying `SUBMITTED` items by that category's completeness minimum —
        two for teaching, three for research, one for service — caps the
        resulting ratio at 2.0, and rounds the capped ratio half-up to three
        decimal places."

        Design: Difficulty/combinatorial_formula/dossier_strength_per_category_rounding_order
        """
        ctx = setup_external_review_case(
            "E401",
            full_name="Cand Cap",
            dossier_spec=[
                {"category": "TEACHING", "title": "T1"},
                {"category": "TEACHING", "title": "T2"},
                {"category": "TEACHING", "title": "T3"},
                {"category": "TEACHING", "title": "T4"},
                {"category": "RESEARCH", "title": "R1", "is_peer_reviewed": True},
                {"category": "RESEARCH", "title": "R2"},
                {"category": "RESEARCH", "title": "R3"},
                {"category": "RESEARCH", "title": "R4"},
                {"category": "RESEARCH", "title": "R5"},
                {"category": "RESEARCH", "title": "R6"},
                {"category": "SERVICE", "title": "S1"},
                {"category": "SERVICE", "title": "S2"},
            ],
        )
        # Every category is at twice its minimum: each ratio caps at 2.0, so the
        # index is 2.0*0.30 + 2.0*0.50 + 2.0*0.20 = 2.0.
        assert_decimal_eq(
            ctx["case"]["dossier_strength_index"], 2.0, "capped dossier_strength_index"
        )


class TestRevisionCycleLoop:
    def test_revision_loop_traverses_submission_twice(self, api):
        """PRD §3.2: "On return, the case moves to `RETURNED_FOR_REVISION`".
        PRD §3.2: "The candidate then resumes assembly — an ownership-checked
        action that moves the case from `RETURNED_FOR_REVISION` back to
        `DOSSIER_ASSEMBLY`".
        PRD §3.2: "On success the system stamps `dossier_submitted_at` with the
        current clock reading".

        Design: Difficulty/non_linear_state_machine/case_revision_cycle_loop
        """
        ctx = setup_external_review_case("E700", full_name="Cand R")
        case_id = ctx["case"]["id"]
        candidate_id = ctx["candidate"]["id"]

        returned = validate_success(api.return_for_revision(case_id, PO_HEADERS))
        assert returned["stage"] == "RETURNED_FOR_REVISION"

        resumed = validate_success(
            api.resume_assembly(case_id, make_candidate_headers(candidate_id))
        )
        assert resumed["stage"] == "DOSSIER_ASSEMBLY"

        resubmitted = submit_dossier(case_id, candidate_id)
        assert resubmitted["stage"] == "EXTERNAL_REVIEW", (
            "The loop must traverse the submission transition a second time"
        )
        assert_instant_eq(
            resubmitted["dossier_submitted_at"],
            "2026-08-01T00:00:00Z",
            "dossier_submitted_at (refreshed at the pinned clock)",
        )

    def test_items_survive_revision_loop_submitted(self, api, reader_headers):
        """PRD §3.2: "On success the system stamps `dossier_submitted_at`
        with the current clock reading, computes and stores the
        `dossier_strength_index`, locks all of the case's `SUBMITTED` items
        against further transitions until a return-for-revision unlocks them, and
        increments the case's `version` by one."
        PRD §3.2: "The candidate then resumes assembly — an ownership-checked
        action that moves the case from `RETURNED_FOR_REVISION` back to
        `DOSSIER_ASSEMBLY`, unlocks the dossier items so item transitions are
        allowed again, and increments the case's `version` by one."

        Design: Difficulty/non_linear_state_machine/case_revision_cycle_loop
        """
        ctx = setup_external_review_case("E701", full_name="Cand R2")
        case_id = ctx["case"]["id"]
        candidate_id = ctx["candidate"]["id"]

        validate_success(api.return_for_revision(case_id, PO_HEADERS))
        validate_success(
            api.resume_assembly(case_id, make_candidate_headers(candidate_id))
        )
        submit_dossier(case_id, candidate_id)

        items, meta = validate_paginated(
            api.list_dossier_items(
                reader_headers, {"case_id": case_id, "status": "SUBMITTED", "limit": 100}
            )
        )
        assert meta["total_count"] == 6, (
            f"All six dossier items must survive the loop SUBMITTED, got {meta['total_count']}"
        )
        for item in items:
            assert item["status"] == "SUBMITTED"


def test_occ_dossier_item_stale_case_version(api):
    """PRD §2.11: "Creating a dossier item requires the non-optional field
    `expected_case_version`, carrying the client's last observed `version` of the
    owning case; if the case's version has advanced since that read, the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.6: "In addition, creating a dossier item against a case, creating
    an invitation against a case, recording the provost decision, and approving
    or rescinding a clock-extension request each increment the case's `version`
    by one".

    Design: Corner/cross_cutting_layers/occ_dossier_item_stale_case_version
    """
    candidate = register_candidate("E9600", full_name="Cand OC")
    case = open_case(candidate["id"])
    snapshot_version = case["version"]

    first = api.create_dossier_item(
        {
            "case_id": case["id"],
            "category": "TEACHING",
            "title": "First",
            "page_count": 4,
            "expected_case_version": snapshot_version,
        },
        make_candidate_headers(candidate["id"]),
    )
    validate_success(first, 201)

    stale = api.create_dossier_item(
        {
            "case_id": case["id"],
            "category": "TEACHING",
            "title": "Stale second",
            "page_count": 4,
            "expected_case_version": snapshot_version,
        },
        make_candidate_headers(candidate["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = api.create_dossier_item(
        {
            "case_id": case["id"],
            "category": "TEACHING",
            "title": "Fresh second",
            "page_count": 4,
            "expected_case_version": read_case_version(case["id"]),
        },
        make_candidate_headers(candidate["id"]),
    )
    data = validate_success(fresh, 201)
    assert_dossier_item(data)
    assert data["status"] == "DRAFT"
