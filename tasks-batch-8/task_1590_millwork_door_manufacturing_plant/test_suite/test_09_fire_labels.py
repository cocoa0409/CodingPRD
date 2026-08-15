"""Serialized fire labels: issuance gates, OCC, serial accounting, roll lifecycle."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_order, make_opening, make_roll, get_roll, get_opening,
    get_allocation, issue_labels, apply_labels, verify_labels, void_labels,
    retire_roll, stage_opening, setup_openings_finished,
    assert_roll_serial_conservation, H,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
ANY_H = TEST_USERS["any_headers"]
LA_H = TEST_USERS["label_authority_headers"]


def _finished_rated_order(contract_code, order_code, openings, **kwargs):
    """MAPLE TEMPLATE_PREP MIN_20 order with all openings driven to FINISHED."""
    kwargs.setdefault("species", "MAPLE")
    kwargs.setdefault("profile_code", "PR-7")
    kwargs.setdefault("finish_system", "STAIN")
    kwargs.setdefault("sheen_target", "SATIN")
    return setup_openings_finished(
        contract_code=contract_code, order_code=order_code,
        hardware_prep_mode="TEMPLATE_PREP", fire_rating_required="MIN_20",
        template_code="T-L1", template_fire_rated=True,
        openings=openings, measured_gu=35, **kwargs,
    )


class TestSerialAvailabilityBoundary:
    _OPENINGS = (
        {"opening_no": "L1", "leaf_count": 2, "fire_rating": "MIN_20",
         "required_on_site_date": "2026-10-01"},
        {"opening_no": "L2", "leaf_count": 1, "fire_rating": "MIN_20",
         "required_on_site_date": "2026-10-01"},
        {"opening_no": "L3", "leaf_count": 1, "fire_rating": "MIN_20",
         "required_on_site_date": "2026-10-01"},
    )

    def _setup(self, contract_code):
        ctx = _finished_rated_order(
            contract_code, "O-7001", self._OPENINGS,
            machine_code="M-L", machine_species=["MAPLE"], booth_code="B-L",
        )
        roll = make_roll(label_series="UL_20MIN", serial_capacity=3)
        return ctx, roll

    def test_issue_at_exact_availability_succeeds(self, api):
        """PRD §3.6: "when `serials_available` is smaller than the opening's
        `leaf_count`, issuance fails with `ERR_INSUFFICIENT_LABEL_SERIALS`
        (HTTP 402)" — a request whose count equals the available stock does
        not fail. "A successful issuance draws one label per leaf".

        Design: Difficulty/boundary_precision_check/label_serial_exact_availability_boundary
        """
        ctx, roll = self._setup("C-7001")
        op1, op2 = ctx["openings"][0]["id"], ctx["openings"][1]["id"]

        alloc1 = issue_labels(op1, roll["id"], user_id="la-1")
        assert alloc1["status"] == "ISSUED"
        assert alloc1["serial_count"] == 2, "one label per leaf"
        assert get_roll(roll["id"])["serials_available"] == 1, "3 - 2 after first issue"

        # Boundary: request count 1 == serials_available 1 succeeds.
        alloc2 = issue_labels(op2, roll["id"], user_id="la-1")
        assert alloc2["status"] == "ISSUED"
        assert get_roll(roll["id"])["serials_available"] == 0, (
            "the second issue consumed exactly the last serial"
        )

    def test_issue_beyond_availability_rejected(self, api):
        """PRD §3.6: "Finally the roll must have enough stock: when
        `serials_available` is smaller than the opening's `leaf_count`,
        issuance fails with `ERR_INSUFFICIENT_LABEL_SERIALS` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/label_serial_exact_availability_boundary
        """
        ctx, roll = self._setup("C-7001B")
        op1, op2, op3 = (op["id"] for op in ctx["openings"])

        issue_labels(op1, roll["id"], user_id="la-1")
        issue_labels(op2, roll["id"], user_id="la-1")
        assert get_roll(roll["id"])["serials_available"] == 0

        # count 1 > available 0 fails.
        version = get_roll(roll["id"])["version"]
        resp = api.create_label_allocation(
            {"opening_id": op3, "roll_id": roll["id"], "expected_roll_version": version}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LABEL_SERIALS, 402)


class TestSerialConservation:
    def _setup(self, contract_code):
        ctx = _finished_rated_order(
            contract_code, "O-9101",
            ({"opening_no": "V1", "leaf_count": 1, "fire_rating": "MIN_20",
              "required_on_site_date": "2026-10-01"},),
            machine_code="M-V", machine_species=["MAPLE"], booth_code="B-V",
        )
        roll = make_roll(label_series="UL_20MIN", serial_capacity=2)
        return ctx, roll

    def test_issue_moves_serials_issued_and_available(self, api):
        """PRD §3.6: "On the roll, `serials_issued` grows and `serials_available`
        shrinks by that count, and the roll's `version` increments by one."
        PRD §2.9: "the counts of issued, applied, spoiled, and available
        serials always sum to the roll's `serial_capacity`".

        Design: Difficulty/compensating_invariant/label_serial_accounting_conservation
        """
        ctx, roll = self._setup("C-9101")
        alloc = issue_labels(ctx["openings"][0]["id"], roll["id"], user_id="la-1")
        assert alloc["status"] == "ISSUED"

        roll_after = get_roll(roll["id"])
        assert roll_after["serials_issued"] == 1
        assert roll_after["serials_applied"] == 0
        assert roll_after["serials_spoiled"] == 0
        assert roll_after["serials_available"] == 1
        assert_roll_serial_conservation(roll_after)
        assert roll_after["version"] == roll["version"] + 1

    def test_void_spoils_serials_without_restoring_availability(self, api):
        """PRD §3.6: "A `LabelAuthority` may void an `ISSUED` allocation, which
        moves its serials from `serials_issued` into `serials_spoiled`". PRD
        §2.9: "a spoiled serial is never returned to the available pool."

        Design: Difficulty/compensating_invariant/label_serial_accounting_conservation
        """
        ctx, roll = self._setup("C-9101B")
        alloc = issue_labels(ctx["openings"][0]["id"], roll["id"], user_id="la-1")

        voided = void_labels(alloc["id"], user_id="la-1")
        assert voided["status"] == "VOIDED"

        roll_after = get_roll(roll["id"])
        assert roll_after["serials_issued"] == 0
        assert roll_after["serials_applied"] == 0
        assert roll_after["serials_spoiled"] == 1
        assert roll_after["serials_available"] == 1, (
            "voiding does NOT restore availability — the serial is destroyed"
        )
        assert_roll_serial_conservation(roll_after)


class TestIssueGateOrdering:
    def test_state_gate_beats_fiscal_quota(self, api):
        """PRD §2.5: "Evaluation stops at the first rung that fails, and that
        rung's error is the one returned — a later rung never masks an earlier
        one." State gates (rung 6) precede fiscal quota/capacity (rung 11), so
        an issuance violating both reports the state error. PRD §3.6: "then the
        opening's fabrication axis must be `FINISHED`, failing with
        `ERR_OPENING_NOT_FINISH_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/label_issue_state_beats_fiscal
        """
        project = make_project(name="Prio Proj", site_address="2 Gate St", contract_code="C-6001")
        template = get_success_data(api.create_hardware_template(
            {"template_code": "T-P1", "manufacturer": "ACME", "fire_rated_compatible": True}, PM_H,
        ))
        order = make_order(project["id"], order_code="O-6001", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_20", hardware_template_id=template["id"])
        # Opening still QUEUED (order DRAFT), 2 leaves; roll capacity 1, so the
        # fiscal gate would ALSO fail — the state error must win.
        opening = make_opening(order["id"], opening_no="Q1", leaf_count=2, fire_rating="MIN_20")
        roll = make_roll(label_series="UL_20MIN", serial_capacity=1)

        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll["id"],
             "expected_roll_version": roll["version"]}, LA_H,
        )
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_OPENING_NOT_FINISH_PASSED", (
            f"state gate must beat the fiscal quota, got {body['data']['error_id']}"
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_FINISH_PASSED, 409)

    def test_state_gate_fires_with_sufficient_serials(self, api):
        """PRD §3.6: "then the opening's fabrication axis must be `FINISHED`,
        failing with `ERR_OPENING_NOT_FINISH_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/label_issue_state_beats_fiscal
        """
        project = make_project(name="Prio Proj 2", site_address="3 Gate St", contract_code="C-6001B")
        template = get_success_data(api.create_hardware_template(
            {"template_code": "T-P2", "manufacturer": "ACME", "fire_rated_compatible": True}, PM_H,
        ))
        order = make_order(project["id"], order_code="O-6001B", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_20", hardware_template_id=template["id"])
        opening = make_opening(order["id"], opening_no="Q2", leaf_count=2, fire_rating="MIN_20")
        roll = make_roll(label_series="UL_20MIN", serial_capacity=4)

        # State violation alone (serials are sufficient): still the state error.
        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll["id"],
             "expected_roll_version": roll["version"]}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_FINISH_PASSED, 409)

    def test_label_issue_unrated_opening_rejected(self, api):
        """PRD §3.6: "Issuance runs its gates in a fixed order: first the
        opening must be rated — its `fire_rating` something other than `NONE` —
        failing with `ERR_OPENING_NOT_RATED`; then the opening's fabrication
        axis must be `FINISHED`, failing with `ERR_OPENING_NOT_FINISH_PASSED`."

        Design: Corner/errors/label_issue_unrated_opening_rejected
        """
        project = make_project(name="P", contract_code="CR-1")
        order = make_order(project["id"], order_code="O-R1")
        opening = make_opening(order["id"], opening_no="1", fire_rating="NONE")
        roll = make_roll(label_series="UL_20MIN", serial_capacity=4)

        # Even a QUEUED unrated opening reports the rating violation first.
        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll["id"],
             "expected_roll_version": roll["version"]}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_RATED, 409)


class TestRollOcc:
    def test_occ_precedes_state_on_label_issue(self, api):
        """PRD §2.5: "Where an endpoint takes an expected-version field (§2.6),
        it must equal the parent resource's current `version`; this rung is
        evaluated before any business logic and fails with
        `ERR_STALE_ORDER_VERSION` or `ERR_STALE_ROLL_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_precedes_state_on_label_issue
        """
        project = make_project(name="P", contract_code="CV-2")
        order = make_order(project["id"], order_code="O-V2")
        opening = make_opening(order["id"], opening_no="V1", fire_rating="NONE")
        roll = make_roll(label_series="UL_20MIN", serial_capacity=2)
        stale_version = roll["version"]
        retire_roll(roll["id"])

        # The roll is RETIRED (a state-gate failure), but the stale OCC version
        # is evaluated first and returns 412.
        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll["id"],
             "expected_roll_version": stale_version}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ROLL_VERSION, 412)

    def test_occ_stale_roll_version_on_label_issue(self, api):
        """PRD §2.6: "If `expected_roll_version` differs from the roll's
        current `version`, the create is rejected with `ERR_STALE_ROLL_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_roll_version_on_label_issue
        """
        ctx = _finished_rated_order(
            "CX-2", "O-X2",
            (
                {"opening_no": "X1", "leaf_count": 1, "fire_rating": "MIN_20",
                 "required_on_site_date": "2026-10-01"},
                {"opening_no": "X2", "leaf_count": 1, "fire_rating": "MIN_20",
                 "required_on_site_date": "2026-10-01"},
            ),
            machine_code="M-X2", machine_species=["MAPLE"], booth_code="B-X2",
            cure_start=10, cure_end=14,
        )
        op1, op2 = ctx["openings"][0]["id"], ctx["openings"][1]["id"]
        roll = make_roll(label_series="UL_20MIN", serial_capacity=4)
        stale_version = roll["version"]

        # The first issue bumps the roll version.
        alloc1 = issue_labels(op1, roll["id"], user_id="la-1")
        assert alloc1["status"] == "ISSUED"

        # A second issue carrying the stale captured version fails 412.
        resp = api.create_label_allocation(
            {"opening_id": op2, "roll_id": roll["id"],
             "expected_roll_version": stale_version}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ROLL_VERSION, 412)

        # Re-reading and retrying with the fresh version succeeds.
        fresh = get_roll(roll["id"])
        assert fresh["version"] == stale_version + 1, "the first issue bumped the roll version"
        alloc2 = validate_success(api.create_label_allocation(
            {"opening_id": op2, "roll_id": roll["id"],
             "expected_roll_version": fresh["version"]}, LA_H,
        ), 201)
        assert alloc2["status"] == "ISSUED"


class TestApplyStageVerifyChain:
    def test_label_apply_stage_verify_chain(self, api):
        """PRD §3.6: "a rated opening attempting that same direct move is
        rejected with `ERR_LABELING_REQUIRED`, because rated work must pass
        through `LABELED`. Moving a `LABELED` opening to `STAGED` requires an
        allocation on the opening to have reached `VERIFIED`, failing otherwise
        with `ERR_LABEL_NOT_VERIFIED`." and "the opening must not already hold
        an allocation in `ISSUED`, `APPLIED`, or `VERIFIED`
        (`ERR_ACTIVE_ALLOCATION_EXISTS`)". and "the roll's `label_series` must
        match the opening's rating per the correspondence of §2.9
        (`ERR_LABEL_SERIES_MISMATCH`, HTTP 403)". and "The roll must be
        `ACTIVE` (`ERR_ROLL_NOT_ACTIVE`)".

        Design: Corner/endpoints/label_apply_stage_verify_chain
        """
        ctx = _finished_rated_order(
            "CE-5", "O-E5",
            ({"opening_no": "L1", "leaf_count": 1, "fire_rating": "MIN_20",
              "required_on_site_date": "2026-10-01"},),
            machine_code="M-E5", machine_species=["MAPLE"], booth_code="B-E5",
            cure_start=10, cure_end=14,
        )
        opening = ctx["openings"][0]
        assert opening["fab_status"] == "FINISHED"

        roll45 = make_roll(label_series="UL_45MIN", serial_capacity=2)
        roll_ret = make_roll(label_series="UL_20MIN", serial_capacity=2)
        roll1 = make_roll(label_series="UL_20MIN", serial_capacity=2)
        retire_roll(roll_ret["id"])

        # Rated openings cannot stage directly from FINISHED.
        resp = api.set_opening_status(opening["id"], {"target_fab_status": "STAGED"},
                                      TEST_USERS["production_lead_headers"])
        validate_error(resp, ApiErrorId.ERR_LABELING_REQUIRED, 409)

        # Wrong series for the opening's rating.
        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll45["id"],
             "expected_roll_version": get_roll(roll45["id"])["version"]}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_LABEL_SERIES_MISMATCH, 403)

        # Retired roll.
        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll_ret["id"],
             "expected_roll_version": get_roll(roll_ret["id"])["version"]}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_ROLL_NOT_ACTIVE, 409)

        # Happy-path issue; a second active allocation on the opening fails.
        alloc = issue_labels(opening["id"], roll1["id"], user_id="la-1")
        assert alloc["status"] == "ISSUED"
        resp = api.create_label_allocation(
            {"opening_id": opening["id"], "roll_id": roll1["id"],
             "expected_roll_version": get_roll(roll1["id"])["version"]}, LA_H,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_ALLOCATION_EXISTS, 409)

        # ISSUED -> VERIFIED is an undeclared pair.
        resp = api.set_label_allocation_status(alloc["id"], {"target_status": "VERIFIED"},
                                               H("QAInspector", "qa-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_ALLOCATION_STATUS_TRANSITION, 409)

        # Apply moves the opening FINISHED -> LABELED, but staging requires a
        # VERIFIED allocation.
        apply_labels(alloc["id"], user_id="pl-1")
        assert get_opening(opening["id"])["fab_status"] == "LABELED"
        resp = api.set_opening_status(opening["id"], {"target_fab_status": "STAGED"},
                                      TEST_USERS["production_lead_headers"])
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_VERIFIED, 409)

        verify_labels(alloc["id"], user_id="qa-1")
        staged = stage_opening(opening["id"])
        assert staged["fab_status"] == "STAGED"


class TestRollLifecycle:
    def test_roll_retire_depleted_lifecycle(self, api):
        """PRD §3.6: "A `LabelAuthority` may retire an `ACTIVE` roll only when
        no serials remain outstanding in issued allocations — `serials_issued`
        must be zero — failing otherwise with `ERR_OUTSTANDING_SERIALS`;
        `DEPLETED` and `RETIRED` are terminal, and any other roll pair fails
        with `ERR_INVALID_ROLL_STATUS_TRANSITION`." and "Whenever a roll's
        available count reaches zero while no serials remain outstanding in
        issued allocations, the roll moves itself from `ACTIVE` to `DEPLETED` —
        application included."

        Design: Corner/state_machines/roll_retire_depleted_lifecycle
        """
        ctx = _finished_rated_order(
            "CS-8", "O-R8",
            ({"opening_no": "R1", "leaf_count": 1, "fire_rating": "MIN_20",
              "required_on_site_date": "2026-10-01"},),
            machine_code="M-R8", machine_species=["MAPLE"], booth_code="B-R8",
            cure_start=10, cure_end=14,
        )
        roll = make_roll(label_series="UL_20MIN", serial_capacity=1)
        alloc = issue_labels(ctx["openings"][0]["id"], roll["id"], user_id="la-1")

        # Outstanding issued serials block retirement.
        resp = api.set_fire_label_roll_status(roll["id"], {"target_status": "RETIRED"}, LA_H)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_SERIALS, 409)

        # Applying the last outstanding serial auto-depletes the roll.
        apply_labels(alloc["id"], user_id="pl-1")
        assert get_roll(roll["id"])["status"] == "DEPLETED"

        # DEPLETED is terminal.
        resp = api.set_fire_label_roll_status(roll["id"], {"target_status": "RETIRED"}, LA_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_ROLL_STATUS_TRANSITION, 409)
