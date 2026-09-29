"""The public offering statement: section upserts, the nine-section bubble, the
recording precondition on effectiveness, amendments and the material-amendment cascade.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_all_conserved,
    assert_cents,
    assert_decimal_equals,
    assert_instant,
    assert_page,
)
from test_helpers.constants import SPONSOR_USER_ID
from test_helpers.factories import (
    amendment_payload,
    component_payload,
    pos_payload,
    roof_standard,
    section_payload,
)
from test_helpers.fixtures import (
    adopt_budget,
    build_registered_project,
    certify_plat,
    complete_all_sections,
    deliver_pos,
    fund_escrow,
    harden,
    make_agreement,
    make_budget,
    make_package,
    make_passed_gate,
    make_pos,
    make_project,
    make_reserve_study,
    make_unit,
    set_clock,
)
from test_helpers.test_users import (
    lender_headers,
    regulator_headers,
    sponsor_headers,
)

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def _draft_pos(api, unit_specs=(), operating_expense_cents=1000000):
    """A DRAFT statement over a passed gate, with no section written yet."""
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    units = [
        make_unit(api, package["id"], number, bp, 1, 900, "as-built")
        for number, bp in unit_specs
    ]
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    budget = make_budget(api, project["id"], study["id"], operating_expense_cents)
    pos = make_pos(api, project["id"], package["id"], study["id"], budget["id"])
    return {
        "project": project,
        "report": gate["report"],
        "package": package,
        "units": units,
        "reserve_study": study,
        "budget": budget,
        "pos": pos,
    }


def test_ninth_complete_section_bubbles_pos_to_sections_complete_and_back(api):
    """PRD: When all nine statutory sections read `COMPLETE` the statement moves
    `DRAFT → SECTIONS_COMPLETE`; if a later write demotes any section below the
    threshold the statement returns to `DRAFT`.

    Design: Corner/state_machines/ninth_complete_section_bubbles_pos_to_sections_complete_and_back
    """
    built = _draft_pos(api)
    pos = built["pos"]
    complete_all_sections(api, pos["id"], "sec", 200, skip=("RESCISSION_RIGHTS",))
    budget_section = validate_success(
        api.get_section(pos["id"], "BUDGET", sponsor_headers())
    )

    before = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert before["status"] == "DRAFT"
    assert before["complete_section_count"] == 8

    ninth = validate_success(
        api.put_section(
            pos["id"],
            "RESCISSION_RIGHTS",
            section_payload("sec-rescission-rights", 200, SPONSOR_USER_ID),
            sponsor_headers(),
        )
    )
    assert ninth["content_status"] == "COMPLETE"
    after_ninth = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert after_ninth["complete_section_count"] == 9
    assert after_ninth["status"] == "SECTIONS_COMPLETE"

    demoted = validate_success(
        api.put_section(
            pos["id"],
            "BUDGET",
            section_payload("sec-budget-v2", 149, SPONSOR_USER_ID),
            sponsor_headers(),
        )
    )
    assert demoted["id"] == budget_section["id"]
    assert demoted["content_status"] == "DRAFTED"
    assert demoted["word_count"] == 149

    after_demotion = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert after_demotion["complete_section_count"] == 8
    assert after_demotion["status"] == "DRAFT"

    _, meta = validate_paginated(
        api.list_sections(pos["id"], sponsor_headers(), params={"content_status": "COMPLETE"})
    )
    assert_page(meta, total_count=8)


def test_put_pos_section_upserts_one_row_and_recomputes_content_status(api):
    """PRD: Writing a section is an upsert keyed on the statement and the
    `section_code`: the first write creates the row and later writes replace its
    `body_ref` and `word_count`. A section reads `COMPLETE` when its `word_count` is at
    least 150 and an `attested_by_user_id` is present, and `DRAFTED` otherwise.

    Design: Corner/endpoints/put_pos_section_upserts_one_row_and_recomputes_content_status
    """
    built = _draft_pos(api, unit_specs=(("101", 5000), ("102", 5000)))
    pos = built["pos"]
    adopt_budget(api, built["budget"]["id"])

    drafted = validate_success(
        api.put_section(
            pos["id"], "BUDGET", section_payload("budget/v1", 100), sponsor_headers()
        )
    )
    section_id = drafted["id"]
    assert drafted["content_status"] == "DRAFTED"
    assert drafted["attested_by_user_id"] is None
    assert drafted["last_attested_at"] is None
    assert validate_success(api.get_pos(pos["id"], sponsor_headers()))[
        "complete_section_count"
    ] == 0

    complete = validate_success(
        api.put_section(
            pos["id"],
            "BUDGET",
            section_payload("budget/v2", 200, SPONSOR_USER_ID),
            sponsor_headers(),
        )
    )
    assert complete["id"] == section_id
    assert complete["content_status"] == "COMPLETE"
    assert complete["body_ref"] == "budget/v2"
    assert complete["word_count"] == 200
    assert complete["attested_by_user_id"] == SPONSOR_USER_ID
    assert_instant(complete["last_attested_at"], "2026-08-01T00:00:00Z")
    assert validate_success(api.get_pos(pos["id"], sponsor_headers()))[
        "complete_section_count"
    ] == 1

    below = validate_success(
        api.put_section(
            pos["id"],
            "BUDGET",
            section_payload("budget/v3", 149, SPONSOR_USER_ID),
            sponsor_headers(),
        )
    )
    assert below["id"] == section_id
    assert below["content_status"] == "DRAFTED"
    assert below["word_count"] == 149
    assert validate_success(api.get_pos(pos["id"], sponsor_headers()))[
        "complete_section_count"
    ] == 0

    at_minimum = validate_success(
        api.put_section(
            pos["id"],
            "BUDGET",
            section_payload("budget/v4", 150, SPONSOR_USER_ID),
            sponsor_headers(),
        )
    )
    assert at_minimum["id"] == section_id
    assert at_minimum["content_status"] == "COMPLETE"
    assert at_minimum["word_count"] == 150
    final = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert final["complete_section_count"] == 1
    assert final["status"] == "DRAFT"

    # Creation synthesizes all nine statutory sections in the same act, so the row
    # count stays 9 throughout: repeated writes on `BUDGET` upsert that one row
    # rather than appending, which is what the COMPLETE-filtered count of 1 shows.
    _, meta = validate_paginated(api.list_sections(pos["id"], sponsor_headers()))
    assert_page(meta, total_count=9)
    _, meta = validate_paginated(
        api.list_sections(
            pos["id"], sponsor_headers(), params={"content_status": "COMPLETE"}
        )
    )
    assert_page(meta, total_count=1)


def test_create_pos_links_package_reserve_study_and_budget(api):
    """PRD: The sponsor assembles the public offering statement against the project,
    naming the `declaration_package_id`, the `reserve_study_id` and the
    `initial_budget_id` it discloses.

    Design: Corner/endpoints/create_pos_links_package_reserve_study_and_budget
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(
        api, project["id"], [component_payload("ROOF", 30, 4, 2500000, 0, "EXCELLENT")]
    )
    package = make_package(api, project["id"], "CENTERLINE", "decl/ref-a", "bylaws/ref-a")
    make_unit(api, package["id"], "101", 5000, 1, 900, "interior finish surfaces")
    make_unit(api, package["id"], "102", 5000, 2, 900, "interior finish surfaces")
    study = make_reserve_study(api, project["id"], gate["report"]["id"], "COMPONENT_METHOD")
    budget = make_budget(api, project["id"], study["id"], 1000000)
    adopt_budget(api, budget["id"])

    pos = validate_success(
        api.create_pos(
            project["id"],
            pos_payload(package["id"], study["id"], budget["id"]),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert pos["conversion_project_id"] == project["id"]
    assert pos["declaration_package_id"] == package["id"]
    assert pos["reserve_study_id"] == study["id"]
    assert pos["initial_budget_id"] == budget["id"]
    assert pos["status"] == "DRAFT"
    assert pos["complete_section_count"] == 0
    assert pos["amendment_count"] == 0
    assert pos["effective_at"] is None
    assert pos["version"] == 1
    # Creation synthesizes all nine statutory sections in the same act, each at
    # `content_status` DRAFTED — so the section list is 9 rows while
    # `complete_section_count` is still 0.
    _, meta = validate_paginated(api.list_sections(pos["id"], sponsor_headers()))
    assert_page(meta, total_count=9)

    validate_error(
        api.create_pos(
            project["id"],
            pos_payload(package["id"], NON_EXISTENT_UUID, budget["id"]),
            sponsor_headers(),
        ),
        "ERR_FINANCIAL_ARTIFACT_NOT_FOUND",
        expected_status=404,
    )
    _, meta = validate_paginated(api.list_project_pos(project["id"], sponsor_headers()))
    assert_page(meta, total_count=1)


def test_pos_amendment_on_a_draft_pos_is_refused(api):
    """PRD: Only an `EFFECTIVE` statement may be amended; an amendment filed against any
    other status is refused with `ERR_INVALID_STATE_TRANSITION`.

    Design: Corner/endpoints/pos_amendment_on_a_draft_pos_is_refused
    """
    built = _draft_pos(api, unit_specs=(("101", 5000), ("102", 5000)))
    pos = built["pos"]
    adopt_budget(api, built["budget"]["id"])

    validate_error(
        api.file_amendment(
            pos["id"],
            amendment_payload(True, "reserve contribution restated"),
            sponsor_headers(),
        ),
        "ERR_INVALID_STATE_TRANSITION",
        expected_status=409,
    )
    after = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert after["status"] == "DRAFT"
    assert after["amendment_count"] == 0
    assert after["last_material_amendment_at"] is None
    assert after["complete_section_count"] == 0
    assert after["version"] == 1
    assert validate_success(api.get_project(built["project"]["id"], sponsor_headers()))[
        "status"
    ] == "DOCUMENTS_PREPARATION"


def test_pos_effectiveness_blocked_until_declaration_recorded(api):
    """PRD: the declaration package named by `declaration_package_id` has `status`
    `RECORDED`, refused otherwise with `ERR_DECLARATION_NOT_RECORDED` (409).

    Design: Difficulty/cross_entity_state_dependency/pos_effectiveness_blocked_until_declaration_recorded
    """
    project = make_project(api, "18 Hiproof Avenue, Medford MA", 1957, 2)
    gate = make_passed_gate(
        api,
        project["id"],
        [
            component_payload(
                "FOUNDATION",
                40,
                20,
                10000000,
                5000,
                "EXCELLENT",
                planned_remediation_gain_years=0,
                is_life_safety=False,
                is_structural=True,
            )
        ],
        "ER-H",
    )
    package = make_package(
        api, project["id"], "CENTERLINE", "s3://decl/hiproof.pdf", "s3://bylaws/hiproof.pdf"
    )
    unit = make_unit(
        api, package["id"], "H-1", 10000, 1, 1200, "centerline of party walls"
    )
    certify_plat(api, package["id"])
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    budget = make_budget(api, project["id"], study["id"], 875000)
    adopt_budget(api, budget["id"])
    pos = make_pos(api, project["id"], package["id"], study["id"], budget["id"])
    complete_all_sections(api, pos["id"], "s3://pos/h", 180)

    ready = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert ready["complete_section_count"] == 9
    assert ready["status"] == "SECTIONS_COMPLETE"
    sections, meta = validate_paginated(api.list_sections(pos["id"], sponsor_headers()))
    assert_page(meta, total_count=9)
    assert all(row["content_status"] == "COMPLETE" for row in sections)
    assert validate_success(api.get_budget(budget["id"], sponsor_headers()))[
        "status"
    ] == "ADOPTED"
    assert validate_success(api.get_reserve_study(study["id"], sponsor_headers()))[
        "adoption_status"
    ] == "ADOPTED"

    validate_error(
        api.confer_effectiveness(pos["id"], regulator_headers()),
        "ERR_DECLARATION_NOT_RECORDED",
        expected_status=409,
    )
    blocked = validate_success(api.get_pos(pos["id"], sponsor_headers()))
    assert blocked["status"] == "SECTIONS_COMPLETE"
    assert blocked["effective_at"] is None
    assert blocked["version"] == ready["version"]
    mid_project = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert mid_project["status"] == "DOCUMENTS_PREPARATION"
    assert mid_project["posture"] == "RESTRICTED"
    unrecorded = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert unrecorded["status"] == "PLAT_CERTIFIED"
    assert unrecorded["recorded_at"] is None

    recorded = validate_success(api.record_package(package["id"], sponsor_headers()))
    assert recorded["status"] == "RECORDED"
    assert_instant(recorded["recorded_at"], "2026-08-01T00:00:00Z")

    effective = validate_success(
        api.confer_effectiveness(pos["id"], regulator_headers())
    )
    assert effective["status"] == "EFFECTIVE"
    assert_instant(effective["effective_at"], "2026-08-01T00:00:00Z")
    assert effective["complete_section_count"] == 9
    assert effective["amendment_count"] == 0

    end_project = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert end_project["status"] == "PRESALE"
    assert end_project["posture"] == "OPEN"
    assert end_project["bp_conservation_total"] == 10000
    assert validate_success(api.get_unit(unit["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == 10000


def test_material_pos_amendment_cascade_pos_agreement_unit_project(api):
    """PRD: Hop four is caused by hop three: for a batch that left `RELEASED`, the
    project moves `CLOSINGS → PRESALE`; and because the statement itself has left
    `EFFECTIVE`, the project additionally moves `PRESALE → REGISTRATION` with
    `posture` recomputed to `RESTRICTED`.

    Design: Difficulty/transitive_cascade/material_pos_amendment_cascade_pos_agreement_unit_project
    """
    built = build_registered_project(
        api,
        "88 Ashlar Street, Lowell MA",
        1962,
        unit_specs=(("A-1", 10000),),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        total_unit_count=2,
    )
    project_id = built["project"]["id"]
    pos_id = built["pos"]["id"]
    unit_id = built["units"][0]["id"]

    agreement = make_agreement(
        api, unit_id, "Erin Owner", "TAX-OO-4", "OWNER_OCCUPANT", 24000000, 2400000
    )
    deliver_pos(api, agreement["id"])
    fund_escrow(api, agreement["id"], 2400000)
    set_clock(api, "2026-08-16T00:00:00Z")
    hardened = harden(api, agreement["id"])
    assert hardened["contract_status"] == "HARD"
    assert_instant(hardened["rescission_deadline_at"], "2026-08-16T00:00:00Z")
    assert hardened["rescission_restart_count"] == 0
    before = validate_success(api.get_project(project_id, sponsor_headers()))
    assert before["status"] == "PRESALE"
    assert before["posture"] == "OPEN"

    set_clock(api, "2026-08-20T00:00:00Z")
    filed = validate_success(
        api.file_amendment(
            pos_id,
            amendment_payload(
                True, "reserve schedule restated after a revised component cost"
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )

    # hop one: the statement itself
    statement = validate_success(api.get_pos(pos_id, sponsor_headers()))
    assert statement["status"] == "AMENDMENT_FILED"
    assert statement["amendment_count"] == 1
    assert_instant(statement["last_material_amendment_at"], "2026-08-20T00:00:00Z")

    # hop two: the delivered agreement reverts and its deadline restarts
    after_agreement = validate_success(
        api.get_agreement(agreement["id"], sponsor_headers())
    )
    assert after_agreement["contract_status"] == "SIGNED"
    assert after_agreement["rescission_restart_count"] == 1
    assert_instant(after_agreement["rescission_deadline_at"], "2026-08-25T00:00:00Z")
    assert after_agreement["escrow_status"] == "FUNDED"

    # hop three: the unit is demoted with the agreement
    unit = validate_success(api.get_unit(unit_id, sponsor_headers()))
    assert unit["sale_status"] == "UNDER_CONTRACT"
    assert unit["percentage_interest_bp"] == 10000

    # hop four: the project unwinds to registration under a restricted posture
    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert project["status"] == "REGISTRATION"
    assert project["posture"] == "RESTRICTED"
    assert_cents(project["escrow_balance_cents"], 2400000, "escrow_balance_cents")
    assert_cents(project["escrow_refunded_cents"], 0, "escrow_refunded_cents")
    assert_all_conserved(project)

    summary = validate_success(
        api.warrantability_summary(project_id, lender_headers())
    )
    assert_decimal_equals(
        summary["owner_occupancy_pct_contract_basis"],
        "100.00",
        "owner_occupancy_pct_contract_basis",
    )
    assert_decimal_equals(
        summary["investor_concentration_pct_contract_basis"],
        "0.00",
        "investor_concentration_pct_contract_basis",
    )
    assert_decimal_equals(
        summary["owner_occupancy_pct_closed_basis"],
        "0.00",
        "owner_occupancy_pct_closed_basis",
    )
    # `presale_sold_pct` is a persisted projection, and the PRD names what refreshes
    # it — an explicit batch threshold evaluation ("The project's `presale_sold_pct`
    # is recomputed as well") and the warrantability read, which "is not passive: it
    # runs the ratio computation under **both** bases and persists both verdicts on
    # the project".  The material-amendment cascade is not one of those, so the value
    # is read here, after the refresh the PRD does declare: the sole `INCLUDED` unit
    # is back at `UNDER_CONTRACT`, so the numerator — `INCLUDED` units at
    # `HARD_CONTRACT` or `SOLD` — is 0 over a denominator of 1.
    refreshed = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_decimal_equals(refreshed["presale_sold_pct"], "0.00", "presale_sold_pct")

    assert filed["id"] == pos_id
    assert filed["status"] == "AMENDMENT_FILED"
    assert validate_success(api.get_package(built["package"]["id"], sponsor_headers()))[
        "status"
    ] == "RECORDED"
