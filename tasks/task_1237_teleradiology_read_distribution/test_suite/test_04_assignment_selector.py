"""Auto-assignment selector: eligibility filters, ranking, tie-breaks, and
capacity limits (fatigue cap, STAT concurrency)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_study,
    create_active_hospital,
    create_assignment_payload,
    create_granted_credential,
    create_radiologist,
    create_routed_study,
    create_routing_policy,
    create_shift_payload,
    create_study,
    create_study_payload,
    get_success_data,
    make_hospital_user_headers,
    make_radiologist_headers,
    set_clock,
    setup_assignment_ready,
    setup_credentialed_radiologist,
    setup_routing_ready_hospital,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]


def _route(api, hosp_id, accession, **overrides):
    study = create_study(hosp_id, accession, **overrides)
    return get_success_data(api.route_study(study["id"], DISPATCH))


class TestSelectorRanking:
    def test_selector_prefers_lower_utilization_ratio(self, api):
        """PRD section 3.5: "Survivors are ranked by utilization ratio —
        `reserved_rvu` plus the study's base RVU, divided by `fatigue_cap_rvu`
        — ascending, compared exactly without rounding; ties break first on
        `stat_active_count` ascending, then on the radiologist's `created_at`
        ascending."

        Design: Corner/calculations/selector_prefers_lower_utilization_ratio
        """
        hosp = setup_routing_ready_hospital(name="Hosp Sel")
        rad_a, _ga, _sa = setup_credentialed_radiologist(
            hosp["id"], full_name="Sel A", fatigue_cap_rvu=10.0)
        rad_b, _gb, _sb = setup_credentialed_radiologist(
            hosp["id"], full_name="Sel B", fatigue_cap_rvu=10.0)
        # Give rad_a one ACTIVE CT assignment (reserved 1.5 -> projected 0.30
        # for the next CT study vs rad_b's 0.15).
        s1 = _route(api, hosp["id"], "ACC-S1")
        assign_study(s1["id"], rad_a["id"])

        s2 = _route(api, hosp["id"], "ACC-S2")
        study2 = get_success_data(api.get_study(s2["id"], DISPATCH))
        resp = api.create_assignment(
            create_assignment_payload(s2["id"], study2["version"]), DISPATCH)
        data = validate_success(resp, 201)
        assert data["radiologist_id"] == rad_b["id"]
        assert data["auto_selected"] is True

    def test_selector_tie_breaks_by_created_at(self, api):
        """PRD section 3.5: "Survivors are ranked by utilization ratio —
        `reserved_rvu` plus the study's base RVU, divided by `fatigue_cap_rvu`
        — ascending, compared exactly without rounding; ties break first on
        `stat_active_count` ascending, then on the radiologist's `created_at`
        ascending."

        Design: Corner/calculations/selector_tie_breaks_by_created_at
        """
        hosp = setup_routing_ready_hospital(name="Hosp Tie")
        rad_first, _g1, _s1 = setup_credentialed_radiologist(
            hosp["id"], full_name="First")
        # created_at is stamped from the logical clock (PRD section 2.5); the
        # PRD tie-break on created_at can only discriminate the two candidates
        # when the clock has advanced between their creations.
        set_clock("2026-05-10T10:01:00Z")
        rad_second, _g2, _s2 = setup_credentialed_radiologist(
            hosp["id"], full_name="Second")

        study = _route(api, hosp["id"], "ACC-TIE")
        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"]), DISPATCH)
        data = validate_success(resp, 201)
        # Identical ratios and STAT counts; the earlier-created radiologist wins.
        assert data["radiologist_id"] == rad_first["id"]
        assert data["radiologist_id"] != rad_second["id"]


class TestSelectorExclusion:
    def test_selector_excludes_released_reader_on_reassign(self, api):
        """PRD section 3.5: "...release moves the assignment to `RELEASED`,
        returns the study to `QUEUED` with `assigned_radiologist_id` cleared,
        appends the releasing radiologist to the study's
        `excluded_radiologist_ids` so they cannot be picked again for this
        study..." and the auto-selector gate "(6) not appear in the study's
        `excluded_radiologist_ids`".

        Design: Corner/calculations/selector_excludes_released_reader_on_reassign
        """
        hosp = setup_routing_ready_hospital(name="Hosp Excl")
        rad_a, _ga, _sa = setup_credentialed_radiologist(hosp["id"], full_name="Ex A")
        rad_b, _gb, _sb = setup_credentialed_radiologist(hosp["id"], full_name="Ex B")
        study = _route(api, hosp["id"], "ACC-EX")
        asg = assign_study(study["id"], rad_a["id"])
        validate_success(api.release_assignment(
            asg["id"], make_radiologist_headers(rad_a["id"])), 200)

        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"]), DISPATCH)
        data = validate_success(resp, 201)
        assert data["radiologist_id"] == rad_b["id"]

    def test_selector_empty_pool_rejected(self, api):
        """PRD section 3.5: "An empty candidate pool rejects the assignment with
        `ERR_NO_ELIGIBLE_RADIOLOGIST` and the study remains `QUEUED`."

        Design: Corner/calculations/selector_empty_pool_rejected
        """
        ctx = setup_assignment_ready(hospital_name="Hosp Empty")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = _route(api, hosp["id"], "ACC-EM")
        asg = assign_study(study["id"], rad["id"])
        validate_success(api.release_assignment(
            asg["id"], make_radiologist_headers(rad["id"])), 200)
        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        # Sole radiologist is now on the study's exclusion list: pool is empty.
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_RADIOLOGIST, 422)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "QUEUED"


class TestManualAssignmentEligibility:
    def test_manual_assign_without_active_shift_rejected(self, api):
        """PRD section 3.5: "Manual assignment evaluates the identical filters
        and maps the first failing filter to its error in validation-priority
        order: ... a lack of modality-matching active shift with
        `ERR_NO_ACTIVE_SHIFT`..."

        Design: Corner/validations/manual_assign_without_active_shift_rejected
        """
        ctx = setup_assignment_ready(hospital_name="Hosp NS")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        # A second radiologist whose only shift is in June: against the fixture
        # work clock of 2026-05-10T10:00:00Z it stays SCHEDULED, never ACTIVE.
        rad2 = create_radiologist(full_name="NS Rad", subspecialties=["NEURORAD"],
                                  license_states=["CA"])
        create_granted_credential(rad2["id"], hosp["id"])
        validate_success(api.create_shift(create_shift_payload(
            rad2["id"], starts_at="2026-06-01T00:00:00Z",
            ends_at="2026-06-02T00:00:00Z", modalities=["CT"]), ADMIN), 201)

        study = _route(api, hosp["id"], "ACC-NS")
        resp = api.create_assignment(
            create_assignment_payload(study["id"], study["version"],
                                      radiologist_id=rad2["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SHIFT, 422)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "QUEUED"

    def test_manual_assign_excluded_reader_rejected(self, api):
        """PRD section 3.5: "Manual assignment evaluates the identical filters
        and maps the first failing filter to its error in validation-priority
        order: ... a reader on the study's exclusion list with
        `ERR_READER_EXCLUDED_FOR_STUDY`..."

        Design: Corner/validations/manual_assign_excluded_reader_rejected
        """
        ctx = setup_assignment_ready(hospital_name="Hosp MX")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = _route(api, hosp["id"], "ACC-MX")
        asg = assign_study(study["id"], rad["id"])
        validate_success(api.release_assignment(
            asg["id"], make_radiologist_headers(rad["id"])), 200)
        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_READER_EXCLUDED_FOR_STUDY, 422)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "QUEUED"


class TestFatigueCapBoundary:
    def test_fatigue_cap_equality_allowed(self, api):
        """PRD section 3.2: "Each radiologist carries two capacity knobs:
        `fatigue_cap_rvu` (default 30.0), the ceiling that the sum of
        `reserved_rvu` and `completed_rvu_24h` may reach but never exceed..."
        PRD section 3.5: "(7) have headroom such that `reserved_rvu` plus the
        study's base RVU does not exceed `fatigue_cap_rvu` — equality is
        allowed".

        Design: Difficulty/boundary_precision_check/fatigue_cap_equality_allowed_strict_greater_rejected
        """
        hosp = setup_routing_ready_hospital(name="Hosp Fat", modality="MR")
        create_routing_policy(hosp["id"], modality="XR")
        rad, _g, _s = setup_credentialed_radiologist(
            hosp["id"], full_name="Cap Rad", fatigue_cap_rvu=4.0,
            shift_modalities=("MR", "XR"))
        # Two MR studies at 2.0 RVU each fill the cap exactly.
        s1 = _route(api, hosp["id"], "ACC-M1", modality="MR")
        assign_study(s1["id"], rad["id"])
        s2 = _route(api, hosp["id"], "ACC-M2", modality="MR")
        assign_study(s2["id"], rad["id"])  # 2.0 + 2.0 == 4.0 exactly: allowed

        rad_after = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert rad_after["reserved_rvu"] == 4.0

    def test_fatigue_cap_strictly_greater_rejected(self, api):
        """PRD section 3.5: "...projected utilization strictly beyond the
        fatigue cap with `ERR_FATIGUE_CAP_EXCEEDED`..." and gate "(7) have
        headroom such that `reserved_rvu` plus the study's base RVU does not
        exceed `fatigue_cap_rvu` — equality is allowed".

        Design: Difficulty/boundary_precision_check/fatigue_cap_equality_allowed_strict_greater_rejected
        """
        hosp = setup_routing_ready_hospital(name="Hosp Fat 2", modality="MR")
        create_routing_policy(hosp["id"], modality="XR")
        rad, _g, _s = setup_credentialed_radiologist(
            hosp["id"], full_name="Cap Rad 2", fatigue_cap_rvu=4.0,
            shift_modalities=("MR", "XR"))
        s1 = _route(api, hosp["id"], "ACC-M1", modality="MR")
        assign_study(s1["id"], rad["id"])
        s2 = _route(api, hosp["id"], "ACC-M2", modality="MR")
        assign_study(s2["id"], rad["id"])

        # Third study (XR, 0.5 RVU) projects 4.5 > 4.0: rejected.
        s3 = _route(api, hosp["id"], "ACC-X1", modality="XR")
        resp = api.create_assignment(
            create_assignment_payload(s3["id"], s3["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_FATIGUE_CAP_EXCEEDED, 422)
        assert get_success_data(api.get_study(s3["id"], DISPATCH))["status"] == "QUEUED"


class TestStatConcurrencyLimit:
    def test_stat_concurrency_at_limit_rejected(self, api):
        """PRD section 3.2: "...`max_concurrent_stat` (default 3), the upper
        bound on that radiologist's concurrently `ACTIVE` assignments on `STAT`
        studies — at the bound, further STAT assignment rejects."
        PRD section 3.5: gate "(8) for a `STAT` study, have a
        `stat_active_count` still below `max_concurrent_stat`".

        Design: Corner/validations/stat_concurrency_at_limit_rejected
        """
        ctx = setup_assignment_ready(hospital_name="Hosp SC", priority="STAT",
                                     rad_overrides={"max_concurrent_stat": 1})
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        s1 = _route(api, hosp["id"], "ACC-SC1", priority="STAT")
        assign_study(s1["id"], rad["id"])  # stat_active_count becomes 1
        s2 = _route(api, hosp["id"], "ACC-SC2", priority="STAT")
        resp = api.create_assignment(
            create_assignment_payload(s2["id"], s2["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_STAT_CONCURRENCY_LIMIT, 422)


class TestValidationPriorityPairs:
    def test_state_precondition_beats_licensure_on_assign(self, api):
        """PRD section 2.8: "Every request passes through a fixed priority
        ladder, and a failure at an earlier rung masks every later rung. ...
        Sixth (priority 6), state-machine legality: the target resource's state
        must permit the requested transition, else `ERR_INVALID_STATE`
        (HTTP 409)... Seventh (priority 7), licensure and credentialing safety
        checks — within this rung, licensure is evaluated before credentialing."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_licensure_on_assign
        """
        hosp = setup_routing_ready_hospital(name="Hosp P5a")
        rad, _g, _s = setup_credentialed_radiologist(
            hosp["id"], full_name="NY Rad", license_states=("NY",))
        study = _route(api, hosp["id"], "ACC-P5A")
        validate_success(api.cancel_study(
            study["id"], make_hospital_user_headers(hosp["id"])), 200)
        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        # Study is CANCELLED (priority 6) AND radiologist lacks CA licensure
        # (priority 7): the earlier rung must mask the later one.
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_state_failure_creates_no_assignment(self, api):
        """PRD section 2.8: "Every request passes through a fixed priority
        ladder, and a failure at an earlier rung masks every later rung."
        PRD section 3.5: "`DispatchOps` assigns a study in `QUEUED`,
        `PRELIMINARY_SIGNED`, or `AMENDMENT_PENDING` status — moving it to
        `ASSIGNED`..."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_licensure_on_assign
        """
        hosp = setup_routing_ready_hospital(name="Hosp P5a2")
        rad, _g, _s = setup_credentialed_radiologist(
            hosp["id"], full_name="NY Rad 2", license_states=("NY",))
        study = _route(api, hosp["id"], "ACC-P5A2")
        validate_success(api.cancel_study(
            study["id"], make_hospital_user_headers(hosp["id"])), 200)
        fresh = get_success_data(api.get_study(study["id"], DISPATCH))
        resp = api.create_assignment(
            create_assignment_payload(study["id"], fresh["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # No side effects: study stays CANCELLED and no assignment exists.
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "CANCELLED"
        rows, meta = validate_paginated(
            api.list_assignments(DISPATCH, params={"study_id": study["id"]}))
        assert meta["total_count"] == 0

    def test_licensure_beats_fatigue_on_assign(self, api):
        """PRD section 2.8: "Seventh (priority 7), licensure and credentialing
        safety checks — within this rung, licensure is evaluated before
        credentialing. Eighth (priority 8), structural constraints... Tenth
        (priority 10), capacity and fiscal limits on assignment."
        PRD section 3.5: "Manual assignment evaluates the identical filters and
        maps the first failing filter to its error in validation-priority order:
        a licensure gap rejects with `ERR_LICENSURE_GAP`; ... projected
        utilization strictly beyond the fatigue cap with
        `ERR_FATIGUE_CAP_EXCEEDED`..."

        Design: Difficulty/priority_pair_validation_conflict/licensure_beats_fatigue_on_assign
        """
        hosp = setup_routing_ready_hospital(name="Hosp P5b")
        rad, _g, _s = setup_credentialed_radiologist(
            hosp["id"], full_name="Busy NY Rad", license_states=("NY",),
            fatigue_cap_rvu=0.5)
        study = _route(api, hosp["id"], "ACC-P5B")
        # Dual failure: no CA license (priority 7) AND projected 1.5 > 0.5 cap
        # (priority 10). Licensure must surface.
        resp = api.create_assignment(
            create_assignment_payload(study["id"], study["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_LICENSURE_GAP, 422)

    def test_licensure_failure_leaves_study_queued_and_rvu_untouched(self, api):
        """PRD section 3.5: "An empty candidate pool rejects the assignment with
        `ERR_NO_ELIGIBLE_RADIOLOGIST` and the study remains `QUEUED`." (failed
        assignment leaves the study QUEUED); PRD section 2.9: "`reserved_rvu`,
        the sum of the reserved RVU over that radiologist's `ACTIVE`
        assignments".

        Design: Difficulty/priority_pair_validation_conflict/licensure_beats_fatigue_on_assign
        """
        hosp = setup_routing_ready_hospital(name="Hosp P5b2")
        rad, _g, _s = setup_credentialed_radiologist(
            hosp["id"], full_name="Busy NY Rad 2", license_states=("NY",),
            fatigue_cap_rvu=0.5)
        study = _route(api, hosp["id"], "ACC-P5B2")
        resp = api.create_assignment(
            create_assignment_payload(study["id"], study["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_LICENSURE_GAP, 422)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "QUEUED"
        assert get_success_data(api.get_radiologist(rad["id"], ADMIN))["reserved_rvu"] == 0.0


class TestCrossEntityStateDependency:
    def test_study_create_blocked_when_hospital_suspended(self, api):
        """PRD section 3.1: "...while a hospital is `SUSPENDED` every attempt to
        register a new study for it is rejected with `ERR_HOSPITAL_NOT_ACTIVE`.
        Only `ACTIVE` hospitals may create or route studies at all."

        Design: Difficulty/cross_entity_state_dependency/study_create_route_blocked_when_hospital_suspended
        """
        hosp = create_active_hospital(name="Hosp Gate", state_code="CA")
        validate_success(api.suspend_hospital(hosp["id"], ADMIN), 200)
        resp = api.create_study(
            create_study_payload(hosp["id"], "ACC-G2"),
            make_hospital_user_headers(hosp["id"]))
        validate_error(resp, ApiErrorId.ERR_HOSPITAL_NOT_ACTIVE, 409)

    def test_route_blocked_when_hospital_suspended(self, api):
        """PRD section 2.8: "...with the related-entity gate that study creation
        and routing require an `ACTIVE` hospital, else `ERR_HOSPITAL_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/study_create_route_blocked_when_hospital_suspended
        """
        hosp = create_active_hospital(name="Hosp Gate 2", state_code="CA")
        study = create_study(hosp["id"], "ACC-G1")
        assert study["status"] == "RECEIVED"
        validate_success(api.suspend_hospital(hosp["id"], ADMIN), 200)
        resp = api.route_study(study["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_HOSPITAL_NOT_ACTIVE, 409)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "RECEIVED"

    def test_assignment_blocked_when_credential_grant_suspended(self, api):
        """PRD section 3.3: "...suspension moves `GRANTED → SUSPENDED`, during
        which the radiologist fails credential eligibility for that hospital..."
        PRD section 3.5: "Manual assignment evaluates the identical filters and
        maps the first failing filter to its error in validation-priority order:
        ... a missing or inactive credential with `ERR_CREDENTIAL_NOT_ACTIVE`..."

        Design: Difficulty/cross_entity_state_dependency/assignment_blocked_when_credential_grant_suspended
        """
        ctx = setup_assignment_ready(hospital_name="Hosp CredGate")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = _route(api, hosp["id"], "ACC-CG")
        # Suspend the radiologist's only grant before assignment.
        grants, _meta = validate_paginated(
            api.list_credential_grants(ADMIN, params={"radiologist_id": rad["id"],
                                                      "hospital_id": hosp["id"]}))
        validate_success(api.suspend_credential(grants[0]["id"], ADMIN), 200)

        resp = api.create_assignment(
            create_assignment_payload(study["id"], study["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ACTIVE, 422)

    def test_credential_suspension_leaves_study_unassigned(self, api):
        """PRD section 3.5: "An empty candidate pool rejects the assignment with
        `ERR_NO_ELIGIBLE_RADIOLOGIST` and the study remains `QUEUED`." (a failed
        assignment never moves the study); PRD section 3.4: "A successful route
        writes the matched policy's id into the study's `routing_policy_id` and
        increments the study's `version`."

        Design: Difficulty/cross_entity_state_dependency/assignment_blocked_when_credential_grant_suspended
        """
        ctx = setup_assignment_ready(hospital_name="Hosp CredGate2")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = _route(api, hosp["id"], "ACC-CG2")
        grants, _meta = validate_paginated(
            api.list_credential_grants(ADMIN, params={"radiologist_id": rad["id"],
                                                      "hospital_id": hosp["id"]}))
        validate_success(api.suspend_credential(grants[0]["id"], ADMIN), 200)
        resp = api.create_assignment(
            create_assignment_payload(study["id"], study["version"],
                                      radiologist_id=rad["id"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ACTIVE, 422)
        after = get_success_data(api.get_study(study["id"], DISPATCH))
        assert after["status"] == "QUEUED"
        assert after["assigned_radiologist_id"] is None
