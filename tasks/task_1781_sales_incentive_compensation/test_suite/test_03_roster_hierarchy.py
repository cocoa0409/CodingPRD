"""Roster and reporting hierarchy: employee_ref uniqueness, same-program and
acyclic manager chain guards, rep listing pagination, and Rep ownership
hiding."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_rep,
    create_assignment,
    create_program,
    create_rep,
    get_success_data,
    make_rep_headers,
    setup_program_with_plan,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["comp_admin_headers"]


class TestHierarchyGuards:
    def test_manager_cycle_rejected(self, api):
        """PRD §3.2: "the manager must belong to the same program
        (`ERR_MANAGER_PROGRAM_MISMATCH`), and the chain must remain acyclic — a
        rep may not be their own manager, nor may they take a descendant as
        manager (`ERR_REP_HIERARCHY_CYCLE`)."
        PRD §3.2: "manager changes re-run the same-program and acyclicity
        checks exactly as at creation, and each update increments the rep's
        `version` by 1."

        Design: Corner/validations/rep_manager_cycle_rejected
        """
        program = create_program("Prog HC")
        rep_a = create_rep(program["id"], "HC A", "HC-A")
        rep_b = create_rep(program["id"], "HC B", "HC-B",
                           manager_id=rep_a["id"])

        resp = api.update_rep(rep_a["id"], {"manager_id": rep_b["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REP_HIERARCHY_CYCLE, 409)
        after = get_success_data(api.get_rep(rep_a["id"], ADMIN))
        assert after.get("manager_id") is None, (
            "the rejected manager change must not take effect"
        )

    def test_manager_from_other_program_rejected(self, api):
        """PRD §3.2: "the manager must belong to the same program
        (`ERR_MANAGER_PROGRAM_MISMATCH`), and the chain must remain acyclic — a
        rep may not be their own manager, nor may they take a descendant as
        manager (`ERR_REP_HIERARCHY_CYCLE`)."

        Design: Corner/validations/rep_manager_other_program_rejected
        """
        prog_x1 = create_program("Prog X1")
        prog_x2 = create_program("Prog X2")
        manager = create_rep(prog_x1["id"], "X Mgr", "X-M1")

        resp = api.create_rep(
            {"program_id": prog_x2["id"], "name": "X Rep",
             "employee_ref": "X-R1", "manager_id": manager["id"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_MANAGER_PROGRAM_MISMATCH, 409)

    def test_duplicate_employee_ref_rejected(self, api):
        """PRD §3.2: "Creating a rep requires the owning `program_id`, a
        display `name`, and an `employee_ref` — an external employee reference
        that must be unique within the program, with duplicates rejected as
        `ERR_DUPLICATE_EMPLOYEE_REF`."

        Design: Corner/validations/duplicate_employee_ref_rejected
        """
        program = create_program("Prog DU")
        first = create_rep(program["id"], "DU One", "DUP-1")
        assert_rep(first)

        resp = api.create_rep(
            {"program_id": program["id"], "name": "DU Two",
             "employee_ref": "DUP-1"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_REF, 409)


class TestRepListingAndVisibility:
    def test_reps_list_pagination_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/reps_list_pagination_limit_offset
        """
        program = create_program("Prog PG")
        for i in (1, 2, 3):
            create_rep(program["id"], f"PG {i}", f"PG-{i}")

        page1, meta1 = validate_paginated(api.list_reps(
            ADMIN, params={"program_id": program["id"], "limit": 2,
                           "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_reps(
            ADMIN, params={"program_id": program["id"], "limit": 2,
                           "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_rep_reading_foreign_assignment_gets_not_found(self, api):
        """PRD §2.1: "A `Rep` caller who references a resource not linked to
        their own rep record receives `ERR_NOT_FOUND`, exactly as if the
        resource did not exist; the system never reveals that a foreign
        resource exists."

        Design: Corner/entities/rep_read_foreign_assignment_not_found
        """
        sc = setup_program_with_plan(program_name="Prog OH",
                                     plan_name="Plan OH")
        rep_a = create_rep(sc["program"]["id"], "Rep A", "OH-RA")
        rep_b = create_rep(sc["program"]["id"], "Rep B", "OH-RB")
        assignment = create_assignment(sc["program"]["id"], rep_a["id"],
                                       sc["plan"]["id"])

        resp = api.get_assignment(assignment["id"], make_rep_headers(rep_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
