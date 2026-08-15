"""Block captaincy: supersede/relieve conservation, OCC double-submit, and the
referential/cardinality gates; plus the materials stewardship ledgers."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_block,
    add_member,
    assert_captain_assignment,
    assign_captain,
    create_captain_assignment_payload,
    create_watch_group,
    get_success_data,
    issue_materials,
    materials_payload,
    register_block,
    setup_group_with_registered_block,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestCaptainConservation:
    def _two_member_block(self, api):
        group, block = setup_group_with_registered_block(
            "Inv Watch", "PCT17", "4-6 Chestnut St", 6,
        )
        m1 = add_member(group["id"], block["id"], "Cap A", "SMS")
        m2 = add_member(group["id"], block["id"], "Cap B", "EMAIL")
        return group, block, m1, m2

    def test_supersede_relieves_prior_assignment(self, api):
        """PRD §3.2: "Appointment carries supersede semantics: if the block
        already has an `ACTIVE` assignment, the new assignment becomes active and
        the prior one is relieved to `RELIEVED` with `relieved_at` stamped."

        Design: Difficulty/compensating_invariant/captain_assign_unassign_conserves_single_active_captain
        """
        _group, block, m1, m2 = self._two_member_block(api)
        asg1 = assign_captain(block["id"], m1["id"])
        assert asg1["assignment_status"] == "ACTIVE"
        assert asg1["relieved_at"] is None

        asg2 = assign_captain(block["id"], m2["id"])
        assert asg2["assignment_status"] == "ACTIVE"

        relieved = validate_success(api.get_captain_assignment(asg1["id"], COORD))
        assert relieved["assignment_status"] == "RELIEVED", (
            "The second create relieves the first as a side effect"
        )
        assert relieved["relieved_at"] is not None

        data, meta = validate_paginated(
            api.list_block_captain_assignments(
                block["id"], COORD, params={"assignment_status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 1, (
            "Exactly one ACTIVE captain per block: created 2, relieved 1"
        )
        assert data[0]["id"] == asg2["id"]

    def test_relieve_restores_zero_active_assignments(self, api):
        """PRD §3.2: "A coordinator may also relieve an active assignment
        directly, moving it to `RELIEVED`"

        Design: Difficulty/compensating_invariant/captain_assign_unassign_conserves_single_active_captain
        """
        _group, block, m1, m2 = self._two_member_block(api)
        asg1 = assign_captain(block["id"], m1["id"])
        asg2 = assign_captain(block["id"], m2["id"])

        relieved = validate_success(
            api.relieve_captain_assignment(asg2["id"], COORD)
        )
        assert relieved["assignment_status"] == "RELIEVED"

        _data, meta = validate_paginated(
            api.list_block_captain_assignments(
                block["id"], COORD, params={"assignment_status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 0, (
            "Forward + compensating pair restores the pre-chain ACTIVE count of "
            "0 with zero drift (2 created == 2 RELIEVED)"
        )
        first = validate_success(api.get_captain_assignment(asg1["id"], COORD))
        assert first["assignment_status"] == "RELIEVED"


class TestCaptainOptimisticConcurrency:
    def test_double_submit_with_same_block_version_rejected(self, api):
        """PRD §2.7: "Appointing a block captain — `POST
        /watch/blocks/{id}/captain-assignments` — requires a non-optional
        `expected_block_version` field carrying the client's last observed
        `version` of the parent block. A new active assignment supersedes any
        prior active one, so a sequential second create sees no state field that
        would reject it; the OCC check on the block's `version` is the sanctioned
        resolution, and a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_captain_assign_double_submit
        """
        group, block = setup_group_with_registered_block(
            "OCC2 Watch", "L02", "2-2 Occ St", 4,
        )
        observed_version = validate_success(api.get_block(block["id"], COORD))[
            "version"
        ]
        m1 = add_member(group["id"], block["id"], "OC1", "SMS")
        m2 = add_member(group["id"], block["id"], "OC2", "EMAIL")

        first = validate_success(
            api.create_captain_assignment(
                block["id"],
                create_captain_assignment_payload(m1["id"], observed_version),
                COORD,
            ),
            201,
        )
        assert_captain_assignment(first)

        resp = api.create_captain_assignment(
            block["id"],
            create_captain_assignment_payload(m2["id"], observed_version),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestCaptainReferentialAndCardinality:
    def test_foreign_block_assignment_is_referential_error(self, api):
        """PRD §3.2: "The appointee must be an `ACTIVE` member of a block
        belonging to the same watch group as the block being captained — anything
        else is `ERR_REFERENTIAL_INTEGRITY`"
        PRD §2.6: "then referential integrity across linked resources
        (`ERR_REFERENTIAL_INTEGRITY`); then block-captain coverage for
        block-scoped alerts (`ERR_NO_ACTIVE_CAPTAIN`); then uniqueness and
        cardinality (`ERR_CONSTRAINT_VIOLATION`)"

        The member already holds an ACTIVE captaincy elsewhere, so both the
        referential rule and the one-active-captain rule are violated; the
        referential rule is evaluated first.

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_on_member_create
        """
        g1, bx = setup_group_with_registered_block(
            "Ref Watch 1", "PCT10", "1-5 Ivy St", 6,
        )
        m1 = add_member(g1["id"], bx["id"], "Dual Cap", "SMS")
        assign_captain(bx["id"], m1["id"])  # m1 already captains BX

        g2, by = setup_group_with_registered_block(
            "Ref Watch 2", "PCT10", "9-19 Ivy St", 6,
        )
        by_version = validate_success(api.get_block(by["id"], COORD))["version"]
        resp = api.create_captain_assignment(
            by["id"],
            create_captain_assignment_payload(m1["id"], by_version),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

        _data, meta = validate_paginated(
            api.list_block_captain_assignments(by["id"], COORD)
        )
        assert meta["total_count"] == 0, (
            "No assignment is created on the foreign block"
        )

    def test_second_active_captainship_is_constraint_error(self, api):
        """PRD §3.2: "a member may hold at most one `ACTIVE` captain assignment
        across the program, enforced as `ERR_CONSTRAINT_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_on_member_create
        """
        group = create_watch_group("Card Watch", "PCT19")
        b1 = register_block(add_block(group["id"], "1-1 Card St", 6)["id"])
        b2 = register_block(add_block(group["id"], "2-2 Card St", 6)["id"])
        m1 = add_member(group["id"], b1["id"], "Card Cap", "SMS")
        assign_captain(b1["id"], m1["id"])

        b2_version = validate_success(api.get_block(b2["id"], COORD))["version"]
        resp = api.create_captain_assignment(
            b2["id"],
            create_captain_assignment_payload(m1["id"], b2_version),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)


class TestMaterialsStewardship:
    def test_recall_below_zero_and_issue_over_budget_rejected(self, api):
        """PRD §2.10: "Two conservation rules guard the ledgers: a recall that
        would drive either count below zero is rejected with
        `ERR_INVENTORY_LIMIT` (HTTP 422), and sign distribution is capped by a
        precinct depot budget of 50 signs per group — an issue that would push a
        group's issued sign count past that budget is likewise rejected with
        `ERR_INVENTORY_LIMIT`."

        Design: Corner/validations/inventory_limit_recall_below_zero_and_issue_over_budget
        """
        group = create_watch_group("Inv2 Watch", "V07")
        issue_materials(group["id"], signs=2, materials=0)

        resp = api.recall_materials(
            group["id"], materials_payload(signs=5, materials=0), COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVENTORY_LIMIT)

        resp2 = api.issue_materials(
            group["id"], materials_payload(signs=60, materials=0), COORD,
        )
        validate_error(resp2, ApiErrorId.ERR_INVENTORY_LIMIT)

        after = validate_success(api.get_watch_group(group["id"], COORD))
        assert after["sign_inventory_count"] == 2, (
            "Both rejected mutations leave the ledger untouched"
        )
