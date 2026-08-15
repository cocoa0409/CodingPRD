"""The rotation catalog and block scheduling: capacity boundary, unit-slot
conflicts, cross-entity year/resident gates, PGY eligibility, the night-float
probation bar, OCC edits, retire guards, and pagination (PRD §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID, PC, PD, ApiClient, ApiErrorId, assert_assignment,
    create_assignment_payload, get_block, make_active_resident,
    make_active_year, make_assignment, make_complement, make_probation_case,
    make_program, make_resident, make_rotation, make_year,
    setup_program_with_active_resident, validate_error, validate_paginated,
    validate_success,
)


def _assignments(api, **params):
    params.setdefault("limit", 100)
    return validate_paginated(api.list_assignments(PC, params=params))


class TestCapacityBoundary:
    def _setup(self, api):
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], approved_positions=4)
        residents = [make_active_resident(program["id"], year["id"],
                                          full_name=f"R {i}")
                     for i in ("A", "B", "C")]
        rotation = make_rotation(program["id"], name="ICU",
                                 max_residents_per_block=2)
        block = get_block(year["id"], 1)
        return residents, rotation, block

    def test_reaching_exact_capacity_is_permitted(self, api: ApiClient):
        """PRD §3.4: "The rotation's capacity is enforced per block: when the
        number of non-`CANCELLED` assignments for the (rotation, block) pair
        has reached `max_residents_per_block`, further assignments are rejected
        with `ERR_ROTATION_CAPACITY_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/rotation_capacity_exact_boundary
        """
        residents, rotation, block = self._setup(api)
        a1 = make_assignment(residents[0]["id"], block["id"], rotation["id"])
        assert a1["status"] == "PLANNED"
        # count 1 < max 2: reaching exactly max is permitted.
        a2 = make_assignment(residents[1]["id"], block["id"], rotation["id"])
        assert a2["status"] == "PLANNED"

    def test_assignment_beyond_capacity_rejected(self, api: ApiClient):
        """PRD §3.4: "when the number of non-`CANCELLED` assignments for the
        (rotation, block) pair has reached `max_residents_per_block`, further
        assignments are rejected with `ERR_ROTATION_CAPACITY_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/rotation_capacity_exact_boundary
        """
        residents, rotation, block = self._setup(api)
        make_assignment(residents[0]["id"], block["id"], rotation["id"])
        make_assignment(residents[1]["id"], block["id"], rotation["id"])
        # count 2 == max 2: the third is rejected.
        resp = api.create_assignment(
            create_assignment_payload(residents[2]["id"], block["id"],
                                      rotation["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_ROTATION_CAPACITY_FULL)
        assert resp.status_code == 409
        _, meta = _assignments(api, rotation_id=rotation["id"],
                               schedule_block_id=block["id"])
        assert meta["total_count"] == 2


class TestAssignmentRequiresActiveYear:
    def _setup(self, api):
        program = make_program()
        year1 = make_active_year(program["id"])
        year2 = make_year(program["id"], year_label="2027-2028",
                          start_date="2027-07-01", end_date="2028-06-29")
        make_complement(program["id"], year1["id"], approved_positions=2)
        resident = make_active_resident(program["id"], year1["id"])
        rotation = make_rotation(program["id"], name="Wards",
                                 max_residents_per_block=2)
        return resident, rotation, get_block(year2["id"], 1), year2

    def test_planning_year_block_rejected(self, api: ApiClient):
        """PRD §3.4: "The block's academic year must be `ACTIVE`
        (`ERR_ACADEMIC_YEAR_NOT_ACTIVE`); since supersession happens only while
        a year is `PLANNING`, any `SUPERSEDED` block fails this same guard, so
        assignments always land on `CURRENT` blocks of an active year."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_academic_year
        """
        resident, rotation, block2, _ = self._setup(api)
        resp = api.create_assignment(
            create_assignment_payload(resident["id"], block2["id"],
                                      rotation["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_ACADEMIC_YEAR_NOT_ACTIVE)
        assert resp.status_code == 409

    def test_identical_payload_succeeds_after_activation(self, api: ApiClient):
        """PRD §3.1: "Activation moves the year to `ACTIVE` and bumps its
        `version`."
        PRD §3.4: "the coordinator supplies the `resident_id`, the
        `schedule_block_id`, and the `rotation_id`, and the assignment is
        created in `PLANNED` status."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_academic_year
        """
        resident, rotation, block2, year2 = self._setup(api)
        validate_success(api.activate_academic_year(year2["id"], PC))
        # Only the AcademicYear state changed between the two attempts.
        created = validate_success(api.create_assignment(
            create_assignment_payload(resident["id"], block2["id"],
                                      rotation["id"]), PC), expected_status=201)
        assert created["status"] == "PLANNED"
        assert_assignment(created)


class TestBlockUnitSlotConflict:
    def _setup(self, api):
        s = setup_program_with_active_resident()
        program, year = s["program"], s["year"]
        rot_a = make_rotation(program["id"], name="Wards",
                              max_residents_per_block=5)
        rot_b = make_rotation(program["id"], name="ICU",
                              max_residents_per_block=5)
        return s, rot_a, rot_b, get_block(year["id"], 1), get_block(year["id"], 2)

    def test_same_block_second_assignment_conflicts_adjacent_ok(self, api: ApiClient):
        """PRD §3.4: "A resident may hold at most one non-`CANCELLED`
        assignment in a given schedule block — unit-slot semantics; a second
        one is rejected with `ERR_BLOCK_ASSIGNMENT_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/resident_block_unit_slot_conflict
        """
        s, rot_a, rot_b, blk1, blk2 = self._setup(api)
        resident = s["resident"]
        make_assignment(resident["id"], blk1["id"], rot_a["id"])

        # Same block, different rotation, ample capacity: unit-slot conflict.
        resp = api.create_assignment(
            create_assignment_payload(resident["id"], blk1["id"], rot_b["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_BLOCK_ASSIGNMENT_CONFLICT)

        # The adjacent block is fine: block adjacency is not a conflict.
        created = validate_success(api.create_assignment(
            create_assignment_payload(resident["id"], blk2["id"], rot_b["id"]),
            PC), expected_status=201)
        assert created["status"] == "PLANNED"

    def test_cancelled_assignment_releases_the_slot(self, api: ApiClient):
        """PRD §3.4: "Cancelling is permitted from either `PLANNED` or
        `CONFIRMED` (otherwise `ERR_ASSIGNMENT_NOT_CANCELLABLE`, HTTP 409) and
        moves it to `CANCELLED`, freeing both the resident's block slot and the
        rotation's capacity."

        Design: Difficulty/resource_temporal_overlap/resident_block_unit_slot_conflict
        """
        s, rot_a, rot_b, blk1, _ = self._setup(api)
        resident = s["resident"]
        a1 = make_assignment(resident["id"], blk1["id"], rot_a["id"])
        validate_success(api.cancel_assignment(a1["id"], PC))

        created = validate_success(api.create_assignment(
            create_assignment_payload(resident["id"], blk1["id"], rot_b["id"]),
            PC), expected_status=201)
        assert created["status"] == "PLANNED"


class TestNightFloatSafetyBeatsCapacity:
    def _setup(self, api):
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], approved_positions=4)
        res_p = make_active_resident(program["id"], year["id"], full_name="P One")
        res_q = make_active_resident(program["id"], year["id"], full_name="Q Two")
        rotation = make_rotation(program["id"], name="Night Float",
                                 max_residents_per_block=1, is_night_float=True)
        block = get_block(year["id"], 1)
        asg_q = make_assignment(res_q["id"], block["id"], rotation["id"])
        return program, year, res_p, res_q, rotation, block, asg_q

    def test_dual_failure_surfaces_probation_safety_error(self, api: ApiClient):
        """PRD §3.4: "A resident whose standing is `ON_PROBATION` may not be
        placed on a night-float rotation — one whose `is_night_float` is true —
        and the attempt is rejected with `ERR_PROBATION_NIGHT_FLOAT_BLOCKED`
        (HTTP 403)."
        PRD §3.4: "Eight guards protect this creation, and they fire in the
        pipeline order of §2.8 — state preconditions before the safety bar,
        which precedes the eligibility and capacity constraints".

        Design: Difficulty/priority_pair_validation_conflict/night_float_safety_error_beats_capacity_error
        """
        _, _, res_p, _, rotation, block, asg_q = self._setup(api)
        make_probation_case(res_p["id"], reason="Unprofessional conduct")
        # The block is full (Q occupies the single slot) AND P is ON_PROBATION:
        # the safety gate (§2.8 stage 8) beats the capacity constraint (stage 10).
        resp = api.create_assignment(
            create_assignment_payload(res_p["id"], block["id"], rotation["id"]),
            PC)
        validate_error(resp, ApiErrorId.ERR_PROBATION_NIGHT_FLOAT_BLOCKED)
        assert resp.status_code == 403
        _, meta = _assignments(api, resident_id=res_p["id"])
        assert meta["total_count"] == 0
        assert validate_success(api.get_assignment(asg_q["id"], PC))[
            "status"] == "PLANNED"

    def test_capacity_error_surfaces_once_standing_is_clear(self, api: ApiClient):
        """PRD §3.4: "when the number of non-`CANCELLED` assignments for the
        (rotation, block) pair has reached `max_residents_per_block`, further
        assignments are rejected with `ERR_ROTATION_CAPACITY_FULL` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/night_float_safety_error_beats_capacity_error
        """
        _, _, res_p, _, rotation, block, _ = self._setup(api)
        case = make_probation_case(res_p["id"], reason="Unprofessional conduct")
        validate_success(api.lift_probation_case(case["id"], PD))
        # Standing clear; the single slot is still occupied by Q.
        resp = api.create_assignment(
            create_assignment_payload(res_p["id"], block["id"], rotation["id"]),
            PC)
        validate_error(resp, ApiErrorId.ERR_ROTATION_CAPACITY_FULL)
        assert resp.status_code == 409


class TestExistenceBeatsYearState:
    def _setup(self, api):
        program = make_program()
        year1 = make_active_year(program["id"])
        year2 = make_year(program["id"], year_label="2027-2028",
                          start_date="2027-07-01", end_date="2028-06-29")
        make_complement(program["id"], year1["id"], approved_positions=2)
        resident = make_active_resident(program["id"], year1["id"])
        rotation = make_rotation(program["id"], name="Wards",
                                 max_residents_per_block=2)
        return resident, rotation, get_block(year2["id"], 1)

    def test_bogus_rotation_yields_not_found_not_state_error(self, api: ApiClient):
        """PRD §2.8: "Every request is validated against an ordered pipeline,
        and the first failure wins" — stage 5: "Every identifier referenced in
        the path and then in the body exists, validated left-to-right — path
        parameters first, then body fields in their declared input order;
        otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/existence_error_beats_year_state_error
        """
        resident, _, block2 = self._setup(api)
        resp = api.create_assignment(
            create_assignment_payload(resident["id"], block2["id"],
                                      NON_EXISTENT_UUID), PC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404

    def test_existing_rotation_into_planning_year_yields_state_error(self, api: ApiClient):
        """PRD §3.4: "The block's academic year must be `ACTIVE`
        (`ERR_ACADEMIC_YEAR_NOT_ACTIVE`)".

        Design: Difficulty/priority_pair_validation_conflict/existence_error_beats_year_state_error
        """
        resident, rotation, block2 = self._setup(api)
        # All identifiers exist, so the state precondition now fires.
        resp = api.create_assignment(
            create_assignment_payload(resident["id"], block2["id"],
                                      rotation["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_ACADEMIC_YEAR_NOT_ACTIVE)
        assert resp.status_code == 409


class TestAssignmentLifecycle:
    def test_happy_path_version_increments(self, api: ApiClient):
        """PRD §3.4: "Confirming requires `PLANNED` (otherwise
        `ERR_ASSIGNMENT_NOT_PLANNED`, HTTP 409) and moves the assignment to
        `CONFIRMED`. Completing requires `CONFIRMED` (otherwise
        `ERR_ASSIGNMENT_NOT_CONFIRMED`, HTTP 409) and moves it to `COMPLETED`."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource".

        Design: Corner/state_machines/assignment_happy_path_with_version_increments
        """
        s = setup_program_with_active_resident()
        rotation = make_rotation(s["program"]["id"], name="Wards",
                                 max_residents_per_block=2)
        block = get_block(s["year"]["id"], 1)
        asg = make_assignment(s["resident"]["id"], block["id"], rotation["id"])
        assert asg["status"] == "PLANNED"
        assert asg["version"] == 1

        asg = validate_success(api.confirm_assignment(asg["id"], PC))
        assert asg["status"] == "CONFIRMED" and asg["version"] == 2
        prev_updated = asg["updated_at"]
        asg = validate_success(api.complete_assignment(asg["id"], PC))
        assert asg["status"] == "COMPLETED" and asg["version"] == 3
        # updated_at is refreshed on every change (monotonically non-decreasing).
        assert asg["updated_at"] >= prev_updated


class TestConditionalGuards:
    def test_pgy_ineligible_rejected_then_satisfied(self, api: ApiClient):
        """PRD §3.4: "The resident's `pgy_level` must be at least the
        rotation's `min_pgy_level` (`ERR_PGY_INELIGIBLE`, HTTP 422)."

        Design: Corner/validations/pgy_ineligible_rejected_then_satisfied
        """
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], pgy_level=1,
                        approved_positions=4)
        make_complement(program["id"], year["id"], pgy_level=3,
                        approved_positions=4, blended_stipend_cents=6500000)
        res1 = make_active_resident(program["id"], year["id"], pgy_level=1,
                                    full_name="R One")
        res3 = make_active_resident(program["id"], year["id"], pgy_level=3,
                                    full_name="R Three")
        rotation = make_rotation(program["id"], name="Cardiology",
                                 min_pgy_level=3, max_residents_per_block=2)
        block = get_block(year["id"], 1)

        resp = api.create_assignment(
            create_assignment_payload(res1["id"], block["id"], rotation["id"]),
            PC)
        validate_error(resp, ApiErrorId.ERR_PGY_INELIGIBLE)
        assert resp.status_code == 422

        created = validate_success(api.create_assignment(
            create_assignment_payload(res3["id"], block["id"], rotation["id"]),
            PC), expected_status=201)
        assert created["status"] == "PLANNED"

    def test_assignment_requires_active_resident(self, api: ApiClient):
        """PRD §3.4: "The rotation must be `ACTIVE` (`ERR_ROTATION_NOT_ACTIVE`).
        The resident's `lifecycle_status` must be `ACTIVE`
        (`ERR_RESIDENT_NOT_ACTIVE`)."

        Design: Corner/validations/assignment_requires_active_resident
        """
        s = setup_program_with_active_resident()
        resident_incoming = make_resident(s["program"]["id"], s["year"]["id"],
                                          activate=False)
        rotation = make_rotation(s["program"]["id"], name="Wards")
        block = get_block(s["year"]["id"], 1)
        resp = api.create_assignment(
            create_assignment_payload(resident_incoming["id"], block["id"],
                                      rotation["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE)
        _, meta = _assignments(api, resident_id=resident_incoming["id"])
        assert meta["total_count"] == 0

    def test_probation_bar_is_conditional_on_night_float(self, api: ApiClient):
        """PRD §3.4: "A resident whose standing is `ON_PROBATION` may not be
        placed on a night-float rotation — one whose `is_night_float` is true —
        and the attempt is rejected with `ERR_PROBATION_NIGHT_FLOAT_BLOCKED`
        (HTTP 403)."

        Design: Corner/validations/night_float_rule_conditional_satisfaction
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        make_probation_case(resident["id"], reason="Unprofessional conduct")
        rotation = make_rotation(s["program"]["id"], name="Wards",
                                 is_night_float=False)
        block = get_block(s["year"]["id"], 1)
        created = validate_success(api.create_assignment(
            create_assignment_payload(resident["id"], block["id"],
                                      rotation["id"]), PC), expected_status=201)
        assert created["status"] == "PLANNED"
        assert validate_success(api.get_resident(resident["id"], PD))[
            "standing_status"] == "ON_PROBATION"

    def test_cross_program_rotation_rejected(self, api: ApiClient):
        """PRD §3.4: "Finally, the resident, the block's year, and the rotation
        must all belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`,
        HTTP 400)."

        Design: Corner/validations/cross_program_reference_rejected
        """
        program1 = make_program(name="Metro IM")
        year1 = make_active_year(program1["id"])
        make_complement(program1["id"], year1["id"], approved_positions=2)
        resident = make_active_resident(program1["id"], year1["id"])
        program2 = make_program(name="Valley Surgery",
                                specialty="GENERAL_SURGERY")
        rotation2 = make_rotation(program2["id"], name="Trauma",
                                  max_residents_per_block=3)
        block1 = get_block(year1["id"], 1)
        resp = api.create_assignment(
            create_assignment_payload(resident["id"], block1["id"],
                                      rotation2["id"]), PC)
        validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)
        assert resp.status_code == 400


class TestRotationOCC:
    def test_stale_rotation_version_rejected(self, api: ApiClient):
        """PRD §2.7: "Updating a rotation requires `expected_rotation_version`
        carrying the rotation's last observed `version`; a mismatch is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_rotation_update_stale_version
        """
        program = make_program()
        rotation = make_rotation(program["id"], name="ICU")
        assert rotation["version"] == 1

        edited = validate_success(api.update_rotation(
            rotation["id"], {"max_residents_per_block": 3,
                             "expected_rotation_version": 1}, PC))
        assert edited["max_residents_per_block"] == 3
        assert edited["version"] == 2

        stale = api.update_rotation(
            rotation["id"], {"max_residents_per_block": 4,
                             "expected_rotation_version": 1}, PC)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        assert validate_success(api.get_rotation(rotation["id"], PC))[
            "max_residents_per_block"] == 3


class TestPaginationEnvelope:
    def test_default_page_and_explicit_limit(self, api: ApiClient):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_and_envelope_shape
        """
        program = make_program()
        for i in range(12):
            make_rotation(program["id"], name=f"R{i + 1:02d}")

        resp = api.list_rotations(PC, params={"program_id": program["id"]})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 10, "default page is 10 items"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert isinstance(resp.json()["meta"]["api_request_id"], str)
        assert isinstance(resp.json()["meta"]["api_request_timestamp"], str)

        data, meta = validate_paginated(api.list_rotations(
            PC, params={"program_id": program["id"], "limit": 12, "offset": 0}))
        assert len(data) == 12
        assert meta["has_more"] is False
