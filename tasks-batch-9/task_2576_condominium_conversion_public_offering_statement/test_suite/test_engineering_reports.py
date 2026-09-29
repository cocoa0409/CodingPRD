"""Engineering reports and major components: retrieval, listing, required fields,
computed aggregates, the submit / peer-review / revision state machine and the
punitive reject cascade.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_decimal_equals,
    assert_id_order,
    assert_page,
    ids_of,
)
from test_helpers.constants import ENGINEER_USER_ID, PEER_USER_ID
from test_helpers.factories import component_payload, report_payload
from test_helpers.fixtures import (
    accept_report,
    build_registered_project,
    make_assessment,
    make_component,
    make_project,
    make_report,
    reject_report,
    report_version,
    submit_report,
)
from test_helpers.test_users import (
    engineer_headers,
    peer_headers,
    regulator_headers,
    sponsor_headers,
)

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)
ROOF = ("ROOF", 30, 10, 10000000, 0, "EXCELLENT")
ELEVATOR = ("ELEVATOR", 20, 15, 8000000, 0, "GOOD")


def test_get_major_component_returns_stored_engineering_inputs(api):
    """PRD: Each component carries a `component_type`, a `remaining_useful_life_years`,
    an `effective_age_years`, a `replacement_cost_cents`, a `funded_pct_bp` and a
    `condition_rating`.

    Design: Corner/entities/get_major_component_returns_stored_engineering_inputs
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(api, report["id"], component_payload(*ROOF))

    data = validate_success(api.get_component(component["id"], peer_headers()))
    assert data["engineering_report_id"] == report["id"]
    assert data["component_type"] == "ROOF"
    assert data["remaining_useful_life_years"] == 30
    assert data["effective_age_years"] == 10
    assert data["replacement_cost_cents"] == 10000000
    assert data["condition_rating"] == "EXCELLENT"
    assert data["verification_status"] == "UNVERIFIED"

    parent = validate_success(api.get_report(report["id"], engineer_headers()))
    assert parent["verified_component_count"] == 0
    assert parent["total_replacement_cost_cents"] == 0


def test_list_engineering_reports_applies_pagination_defaults(api):
    """PRD: Every list endpoint accepts `limit` (1 to 100, default 10) and `offset`
    (0 or greater, default 0).

    Design: Corner/entities/list_engineering_reports_applies_pagination_defaults
    """
    project = make_project(api, *STD_PROJECT)
    first = make_report(api, project["id"], "ER-1", "2026-07-10T00:00:00Z")
    second = make_report(api, project["id"], "ER-2", "2026-07-11T00:00:00Z")
    third = make_report(api, project["id"], "ER-3", "2026-07-12T00:00:00Z")

    rows, meta = validate_paginated(api.list_reports(project["id"], regulator_headers()))
    assert_page(meta, total_count=3, limit=10, offset=0, has_more=False)
    assert_id_order(rows, [first["id"], second["id"], third["id"]])

    rows, meta = validate_paginated(
        api.list_reports(project["id"], regulator_headers(), {"limit": 2, "offset": 2})
    )
    assert_page(meta, total_count=3, limit=2, offset=2, has_more=False)
    assert ids_of(rows) == [third["id"]]


def test_create_major_component_missing_condition_rating_returns_invalid_request(api):
    """PRD: Rung 5 — request shape. Missing or malformed fields fail with
    `ERR_INVALID_REQUEST`, HTTP 422.

    Design: Corner/entities/create_major_component_missing_condition_rating_returns_invalid_request
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])

    validate_error(
        api.create_component(
            report["id"],
            {
                "component_type": "ROOF",
                "remaining_useful_life_years": 30,
                "effective_age_years": 10,
                "replacement_cost_cents": 10000000,
                "funded_pct_bp": 0,
            },
            engineer_headers(),
        ),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    assert validate_success(api.get_report(report["id"], engineer_headers()))["version"] == 1
    _, meta = validate_paginated(api.list_components(report["id"], engineer_headers()))
    assert_page(meta, total_count=0)


def test_create_engineering_report_under_unknown_project_returns_project_not_found(api):
    """PRD: Rung 3 — existence of every referenced entity, checked left to right.

    Design: Corner/entities/create_engineering_report_under_unknown_project_returns_project_not_found
    """
    validate_error(
        api.create_report(NON_EXISTENT_UUID, report_payload(), engineer_headers()),
        "ERR_PROJECT_NOT_FOUND",
        expected_status=404,
    )


def test_engineering_report_verified_aggregates_computed_from_children(api):
    """PRD: A `PeerReviewEngineer` — never the authoring `LicensedEngineer` — marks a
    component `VERIFIED`, which recomputes the parent report's
    `verified_component_count` and `total_replacement_cost_cents`.

    Design: Corner/entities/engineering_report_verified_aggregates_computed_from_children
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    roof = make_component(api, report["id"], component_payload(*ROOF))
    elevator = make_component(api, report["id"], component_payload(*ELEVATOR))
    submit_report(api, report["id"])
    validate_success(api.verify_component(roof["id"], True, peer_headers()))
    validate_success(api.verify_component(elevator["id"], True, peer_headers()))

    before = validate_success(api.get_report(report["id"], engineer_headers()))
    assert before["verified_component_count"] == 2
    assert before["total_replacement_cost_cents"] == 18000000

    unverified = validate_success(
        api.verify_component(roof["id"], False, peer_headers())
    )
    assert unverified["verification_status"] == "UNVERIFIED"
    assert validate_success(api.get_component(elevator["id"], peer_headers()))[
        "verification_status"
    ] == "VERIFIED"
    middle = validate_success(api.get_report(report["id"], engineer_headers()))
    assert middle["verified_component_count"] == 1
    assert middle["total_replacement_cost_cents"] == 8000000

    reverified = validate_success(api.verify_component(roof["id"], True, peer_headers()))
    assert reverified["verification_status"] == "VERIFIED"
    after = validate_success(api.get_report(report["id"], engineer_headers()))
    assert after["verified_component_count"] == 2
    assert after["total_replacement_cost_cents"] == 18000000


def test_child_entities_start_in_declared_initial_states(api):
    """PRD: A new report starts in `status` `DRAFT` with `revision_round` 0.

    Design: Corner/state_machines/child_entities_start_in_declared_initial_states
    """
    project = make_project(api, *STD_PROJECT)

    report = validate_success(
        api.create_report(project["id"], report_payload(), engineer_headers()),
        expected_status=201,
    )
    assert report["status"] == "DRAFT"
    assert report["revision_round"] == 0
    # `submitted_by_user_id` is a stated creation input (PRD 3.2: the sponsor or
    # engineer opens a report "supplying ... the `submitted_by_user_id` of the
    # engineer of record"), and the PRD's declared initial-state list for a new
    # report names only status, revision_round, verified_component_count,
    # total_replacement_cost_cents and version.  Its creation-time value is
    # therefore not a declared default and is not asserted here.
    assert report["reviewed_by_user_id"] is None

    package = validate_success(
        api.create_package(
            project["id"],
            {
                "declaration_text_ref": "decl-1",
                "bylaws_text_ref": "bylaws-1",
                "boundary_convention": "STUD_TO_STUD",
            },
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert package["status"] == "DRAFT"
    assert package["plat_revision"] == 0
    assert package["recorded_at"] is None

    unit = validate_success(
        api.create_unit(
            package["id"],
            {
                "unit_number": "101",
                "floor_level": 1,
                "heated_square_feet": 900,
                "boundary_note": "stud to stud",
                "base_percentage_interest_bp": 10000,
            },
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert unit["declaration_status"] == "INCLUDED"
    assert unit["sale_status"] == "UNSOLD"
    assert unit["percentage_interest_bp"] == 10000
    assert unit["unit_annual_assessment_cents"] == 0

    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "allocated_bp_total"
    ] == 0
    reread = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert reread["included_unit_count"] == 1
    assert reread["status"] == "FEASIBILITY"


def test_report_submit_stamps_the_submitter_and_bubbles_the_project(api):
    """PRD: Submission records the acting `X-User-ID` as the report's
    `submitted_by_user_id`, increments `revision_round` by 1, sets
    `verification_status` to `VERIFIED` on every child major component.

    Design: Corner/state_machines/report_submit_stamps_the_submitter_and_bubbles_the_project
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    roof = make_component(api, report["id"], component_payload(*ROOF))
    hvac = make_component(
        api, report["id"], component_payload("HVAC", 25, 12, 8000000, 0, "GOOD")
    )

    submitted = validate_success(
        api.submit_report(report["id"], engineer_headers("eng-2"))
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "eng-2"
    assert submitted["revision_round"] == 1
    assert validate_success(api.get_component(roof["id"], peer_headers()))[
        "verification_status"
    ] == "VERIFIED"
    assert validate_success(api.get_component(hvac["id"], peer_headers()))[
        "verification_status"
    ] == "VERIFIED"
    assert submitted["verified_component_count"] == 2
    assert submitted["total_replacement_cost_cents"] == 18000000

    bubbled = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert bubbled["status"] == "SUITABILITY_REVIEW"
    assert bubbled["posture"] == "RESTRICTED"
    assert bubbled["suitability_gate"] == "UNEVALUATED"


def test_second_submit_on_submitted_report_returns_invalid_state_transition(api):
    """PRD: Two preconditions apply: the report must currently be in `DRAFT`, and it
    must have at least one child major component.

    Design: Corner/state_machines/second_submit_on_submitted_report_returns_invalid_state_transition
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    make_component(api, report["id"], component_payload(*ROOF))
    submitted = submit_report(api, report["id"])

    validate_error(
        api.submit_report(report["id"], engineer_headers("eng-2")),
        "ERR_INVALID_STATE_TRANSITION",
        expected_status=409,
    )
    after = validate_success(api.get_report(report["id"], engineer_headers()))
    assert after["status"] == "SUBMITTED"
    assert after["revision_round"] == 1
    assert after["submitted_by_user_id"] == ENGINEER_USER_ID
    assert after["version"] == submitted["version"]
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "status"
    ] == "SUITABILITY_REVIEW"


def test_peer_review_accept_supersedes_prior_accepted_sibling_report(api):
    """PRD: On `ACCEPT` the report moves `SUBMITTED → ACCEPTED`, `reviewed_by_user_id`
    becomes the acting `X-User-ID`, and any other report of the same project already
    in `ACCEPTED` moves to `SUPERSEDED`.

    Design: Corner/state_machines/peer_review_accept_supersedes_prior_accepted_sibling_report
    """
    project = make_project(api, *STD_PROJECT)
    first = make_report(api, project["id"], "ER-1", "2026-07-10T00:00:00Z")
    first_component = make_component(api, first["id"], component_payload(*ROOF))
    submit_report(api, first["id"])
    validate_success(api.verify_component(first_component["id"], True, peer_headers()))
    accept_report(api, first["id"])
    assessment = make_assessment(api, first["id"])

    second = make_report(api, project["id"], "ER-2", "2026-07-20T00:00:00Z")
    second_component = make_component(
        api, second["id"], component_payload("ROOF", 28, 12, 11000000, 0, "GOOD")
    )
    submit_report(api, second["id"])
    validate_success(api.verify_component(second_component["id"], True, peer_headers()))
    first_version = report_version(api, first["id"])

    accepted = validate_success(
        api.peer_review(
            second["id"],
            {"decision": "ACCEPT", "reviewed_by_user_id": PEER_USER_ID},
            peer_headers(),
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["reviewed_by_user_id"] == PEER_USER_ID

    superseded = validate_success(api.get_report(first["id"], engineer_headers()))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["version"] == first_version + 1

    invalidated = validate_success(api.get_assessment(assessment["id"], peer_headers()))
    assert invalidated["status"] == "INVALIDATED"
    assert_decimal_equals(invalidated["score"], "100.00", "score")
    assert invalidated["verdict"] == "PASSED"

    _, meta = validate_paginated(
        api.list_report_assessments(
            first["id"], peer_headers(), {"status": "EFFECTIVE"}
        )
    )
    assert_page(meta, total_count=0)


def test_submit_superseded_report_returns_invalid_state_transition(api):
    """PRD: Both branches require the report to be in `status` `SUBMITTED`.

    Design: Corner/state_machines/submit_superseded_report_returns_invalid_state_transition
    """
    project = make_project(api, *STD_PROJECT)
    first = make_report(api, project["id"], "ER-1", "2026-07-10T00:00:00Z")
    first_component = make_component(api, first["id"], component_payload(*ROOF))
    submit_report(api, first["id"])
    validate_success(api.verify_component(first_component["id"], True, peer_headers()))
    accept_report(api, first["id"])

    second = make_report(api, project["id"], "ER-2", "2026-07-20T00:00:00Z")
    second_component = make_component(
        api, second["id"], component_payload("ROOF", 28, 12, 11000000, 0, "GOOD")
    )
    submit_report(api, second["id"])
    validate_success(api.verify_component(second_component["id"], True, peer_headers()))
    accept_report(api, second["id"])
    first_version = report_version(api, first["id"])

    validate_error(
        api.submit_report(first["id"], engineer_headers()),
        "ERR_INVALID_STATE_TRANSITION",
        expected_status=409,
    )
    validate_error(
        api.peer_review(
            first["id"],
            {"decision": "REJECT", "reviewed_by_user_id": "peer-2"},
            peer_headers("peer-2"),
        ),
        "ERR_INVALID_STATE_TRANSITION",
        expected_status=409,
    )
    locked = validate_success(api.get_report(first["id"], engineer_headers()))
    assert locked["status"] == "SUPERSEDED"
    assert locked["version"] == first_version
    assert validate_success(api.get_report(second["id"], engineer_headers()))[
        "status"
    ] == "ACCEPTED"
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "posture"
    ] == "RESTRICTED"


def test_report_revision_cycle_returns_to_draft_and_increments_revision_round(api):
    """PRD: A `LicensedEngineer` may reopen a `REVISION_REQUESTED` report, moving it
    `REVISION_REQUESTED → DRAFT` without touching `revision_round`.

    Design: Corner/state_machines/report_revision_cycle_returns_to_draft_and_increments_revision_round
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    component = make_component(api, report["id"], component_payload(*ROOF))
    submit_report(api, report["id"])
    reject_report(api, report["id"], review_note="roof RUL overstated")

    before = validate_success(api.get_report(report["id"], engineer_headers()))
    assert before["status"] == "REVISION_REQUESTED"
    assert before["revision_round"] == 1
    assert before["verified_component_count"] == 0
    assert before["total_replacement_cost_cents"] == 0
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "posture"
    ] == "FROZEN"

    # Rejection has left this project FROZEN, and PRD 3.1's exemption list is
    # "pinned": it names "adjusting a major component's engineering inputs" but
    # does not name the explicit revision request, so whether that second route is
    # freeze-exempt is not derivable from the document.  PRD 3.2 makes the named,
    # exempt route perform the very same edge — "If instead the parent report was
    # in `status` `REVISION_REQUESTED`, the edit reopens the drafting cycle and the
    # report moves `REVISION_REQUESTED -> DRAFT`" — so the reopen is driven through
    # it, and the cycle mechanics are asserted without depending on that silence.
    edited = validate_success(
        api.patch_component(
            component["id"],
            {"remaining_useful_life_years": 26, "condition_rating": "GOOD"},
            engineer_headers(),
        )
    )
    assert edited["remaining_useful_life_years"] == 26
    assert edited["condition_rating"] == "GOOD"
    reopened = validate_success(api.get_report(report["id"], engineer_headers()))
    assert reopened["status"] == "DRAFT"
    assert reopened["revision_round"] == 1
    assert reopened["verified_component_count"] == 0
    assert reopened["total_replacement_cost_cents"] == 0

    # Resubmission "sets `verification_status` to `VERIFIED` on every child major
    # component, recomputes `verified_component_count` and
    # `total_replacement_cost_cents` over those children", and increments
    # `revision_round` so "a report resubmitted after a revision round reaches 2".
    resubmitted = submit_report(api, report["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 2
    assert resubmitted["verified_component_count"] == 1
    assert resubmitted["total_replacement_cost_cents"] == 10000000
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "status"
    ] == "SUITABILITY_REVIEW"


def test_duplicate_report_label_within_project_returns_duplicate_key(api):
    """PRD: A project may not hold two reports with the same `report_label`; a repeat
    fails with `ERR_DUPLICATE_KEY`.

    Design: Corner/validations/duplicate_report_label_within_project_returns_duplicate_key
    """
    project_a = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    report_a = make_report(api, project_a["id"], "ER-1", "2026-07-10T00:00:00Z")
    project_b = make_project(api, "46 Cove Lane, Bangor ME", 1968, 2)

    validate_error(
        api.create_report(
            project_a["id"],
            report_payload("ER-1", "2026-07-11T00:00:00Z", "eng-2"),
            engineer_headers("eng-2"),
        ),
        "ERR_DUPLICATE_KEY",
        expected_status=409,
    )
    _, meta = validate_paginated(api.list_reports(project_a["id"], engineer_headers()))
    assert_page(meta, total_count=1)

    sibling = validate_success(
        api.create_report(
            project_b["id"],
            report_payload("ER-1", "2026-07-11T00:00:00Z", "eng-2"),
            engineer_headers("eng-2"),
        ),
        expected_status=201,
    )
    assert sibling["report_label"] == "ER-1"
    assert sibling["conversion_project_id"] == project_b["id"]
    assert validate_success(api.get_report(report_a["id"], engineer_headers()))[
        "status"
    ] == "DRAFT"


def test_verification_write_is_visible_in_the_parent_aggregate_on_the_next_read(api):
    """PRD: Every write is durable and immediately visible to the next read; there is
    no eventual consistency anywhere in this system.

    Design: Corner/consistency_model/verification_write_is_visible_in_the_parent_aggregate_on_the_next_read
    """
    project = make_project(api, *STD_PROJECT)
    report = make_report(api, project["id"])
    roof = make_component(api, report["id"], component_payload(*ROOF))
    foundation = make_component(
        api,
        report["id"],
        component_payload("FOUNDATION", 40, 10, 4000000, 0, "EXCELLENT", is_structural=True),
    )

    before = validate_success(api.get_report(report["id"], engineer_headers()))
    assert before["verified_component_count"] == 0
    assert before["total_replacement_cost_cents"] == 0

    verified = validate_success(api.verify_component(roof["id"], True, peer_headers()))
    assert verified["verification_status"] == "VERIFIED"

    after_first = validate_success(api.get_report(report["id"], peer_headers()))
    assert after_first["verified_component_count"] == 1
    assert after_first["total_replacement_cost_cents"] == 10000000
    assert validate_success(api.get_component(foundation["id"], peer_headers()))[
        "verification_status"
    ] == "UNVERIFIED"

    validate_success(api.verify_component(foundation["id"], True, peer_headers()))
    after_second = validate_success(api.get_report(report["id"], peer_headers()))
    assert after_second["verified_component_count"] == 2
    assert after_second["total_replacement_cost_cents"] == 14000000

    validate_success(api.verify_component(roof["id"], False, peer_headers()))
    assert validate_success(api.get_component(roof["id"], peer_headers()))[
        "verification_status"
    ] == "UNVERIFIED"
    after_fourth = validate_success(api.get_report(report["id"], peer_headers()))
    assert after_fourth["verified_component_count"] == 1
    assert after_fourth["total_replacement_cost_cents"] == 4000000

    _, meta = validate_paginated(
        api.list_components(
            report["id"], peer_headers(), {"verification_status": "VERIFIED"}
        )
    )
    assert_page(meta, total_count=1)


def test_create_response_detail_read_and_list_projection_agree_within_one_sequence(api):
    """PRD: A create response, the detail read that follows it and the list projection
    of the same row agree field for field.

    Design: Corner/consistency_model/create_response_detail_read_and_list_projection_agree_within_one_sequence
    """
    project = make_project(api, *STD_PROJECT)
    _, meta = validate_paginated(api.list_reports(project["id"], engineer_headers()))
    assert_page(meta, total_count=0)

    created = validate_success(
        api.create_report(
            project["id"],
            report_payload("ER-1", "2026-07-10T00:00:00Z"),
            engineer_headers(),
        ),
        expected_status=201,
    )
    assert created["report_label"] == "ER-1"
    assert created["status"] == "DRAFT"
    assert created["revision_round"] == 0
    assert created["version"] == 1

    reread = validate_success(api.get_report(created["id"], engineer_headers()))
    assert reread == created

    rows, meta = validate_paginated(api.list_reports(project["id"], engineer_headers()))
    assert_page(meta, total_count=1, limit=10, offset=0)
    assert ids_of(rows) == [created["id"]]

    second = make_report(api, project["id"], "ER-2", "2026-07-11T00:00:00Z")
    third = make_report(api, project["id"], "ER-3", "2026-07-12T00:00:00Z")
    _, meta = validate_paginated(api.list_reports(project["id"], engineer_headers()))
    assert_page(meta, total_count=3)

    make_component(api, third["id"], component_payload(*ROOF))
    assert submit_report(api, third["id"])["status"] == "SUBMITTED"

    rows, meta = validate_paginated(
        api.list_reports(project["id"], engineer_headers(), {"status": "SUBMITTED"})
    )
    assert_page(meta, total_count=1)
    assert ids_of(rows) == [third["id"]]

    rows, meta = validate_paginated(
        api.list_reports(project["id"], engineer_headers(), {"status": "DRAFT"})
    )
    assert_page(meta, total_count=2)
    assert_id_order(rows, [created["id"], second["id"]])
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "status"
    ] == "SUITABILITY_REVIEW"


def test_peer_reject_cascade_walks_four_hops_from_report_to_effective_statement(api):
    """PRD: On `REJECT` the report moves `SUBMITTED → REVISION_REQUESTED`, and the
    effect set is entirely disjoint from the accept branch: nothing is superseded, and
    instead a four-hop punitive cascade runs, each hop caused by the one before it.

    Design: Corner/cross_cutting_complexity_layers/peer_reject_cascade_walks_four_hops_from_report_to_effective_statement
    """
    built = build_registered_project(
        api,
        unit_specs=(("101", 5000), ("102", 5000)),
        total_unit_count=2,
        boundary_convention="PAINT_TO_PAINT",
        annual_operating_expense_cents=1000000,
        opening_reserve_balance_cents=0,
        section_word_count=200,
        accept=False,
    )
    project_id = built["project"]["id"]
    report_id = built["report"]["id"]
    component_id = built["components"][0]["id"]
    assessment_id = built["assessment"]["id"]
    pos_id = built["pos"]["id"]

    before_report = validate_success(api.get_report(report_id, engineer_headers()))
    assert before_report["status"] == "SUBMITTED"
    assert before_report["revision_round"] == 1
    assert before_report["verified_component_count"] == 1
    assert before_report["total_replacement_cost_cents"] == 10000000
    assert validate_success(api.get_assessment(assessment_id, peer_headers()))[
        "status"
    ] == "EFFECTIVE"
    before_project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert before_project["suitability_gate"] == "PASSED"
    assert_decimal_equals(
        before_project["suitability_score"], "100.00", "suitability_score"
    )
    assert before_project["status"] == "PRESALE"
    assert validate_success(api.get_pos(pos_id, sponsor_headers()))["status"] == "EFFECTIVE"

    rejected = validate_success(
        api.peer_review(
            report_id,
            {
                "decision": "REJECT",
                "reviewed_by_user_id": PEER_USER_ID,
                "review_note": "roof detail unsupported",
            },
            peer_headers(),
        )
    )
    assert rejected["status"] == "REVISION_REQUESTED"
    assert rejected["reviewed_by_user_id"] == PEER_USER_ID
    assert rejected["revision_round"] == 1
    assert validate_success(api.get_component(component_id, peer_headers()))[
        "verification_status"
    ] == "UNVERIFIED"
    assert rejected["verified_component_count"] == 0
    assert rejected["total_replacement_cost_cents"] == 0

    invalidated = validate_success(api.get_assessment(assessment_id, peer_headers()))
    assert invalidated["status"] == "INVALIDATED"
    assert_decimal_equals(invalidated["score"], "100.00", "score")

    after_project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert after_project["suitability_gate"] == "FAILED"
    assert_decimal_equals(
        after_project["suitability_score"], "0.00", "suitability_score"
    )
    assert after_project["status"] == "PRESALE"
    assert after_project["posture"] == "FROZEN"
    assert validate_success(api.get_pos(pos_id, sponsor_headers()))[
        "status"
    ] == "AMENDMENT_REQUIRED"

    _, meta = validate_paginated(
        api.list_agreements(sponsor_headers(), {"conversion_project_id": project_id})
    )
    assert_page(meta, total_count=0)
    assert validate_success(api.get_package(built["package"]["id"], sponsor_headers()))[
        "status"
    ] == "RECORDED"
