"""Which refusal wins when a single request breaks two rules at once.

Every test builds its own commission out of the endpoints the PRD declares, so
it opens against an empty database with the logical clock at its documented
default of 2026-08-01T00:00:00Z, and each request under test is arranged to
violate two rules simultaneously so the reported error names the higher rung.
"""

from test_helpers import (
    CURATOR,
    ERR_ARTIFACT_ALREADY_PLACED,
    ERR_ARTIFACT_CONDITION_UNSTABLE,
    ERR_CLOSURE_CAPACITY_EXCEEDED,
    ERR_ENV_ENVELOPE_INFEASIBLE,
    ERR_FABRICATION_BUDGET_EXCEEDED,
    ERR_INVALID_CASE_STATE,
    ERR_PROJECT_FROZEN_CONSERVATION,
    ERR_SECURITY_TIER_INSUFFICIENT,
    ERR_ZONE_WINDOW_CONFLICT,
    OBJECTIVE_PRIMARY,
    OBJECTIVE_SECONDARY,
    OPERATIONS,
    PM,
    CaseDecision,
    CaseStatus,
    ComplexityTier,
    ConditionStatus,
    DrawingDecision,
    DrawingStatus,
    FinishGrade,
    MaterialClass,
    PackageStage,
    Phase,
    PlacementStatus,
    Posture,
    SecurityTier,
    WindowStatus,
    assert_counters,
    assert_envelope,
    assert_ledger,
    assert_unchanged,
    get_success_data,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _schematic_commission_with_one_zone(api, project_overrides=None, **zone_overrides):
    """A commission in SCHEMATIC with one gallery zone of two case slots."""
    fx.set_clock(api)
    project = fx.create_project(api, **(project_overrides or {}))
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone = fx.create_zone(api, project_id, **zone_overrides)
    return {"project_id": project_id, "zone_id": zone["id"], "zone": zone}


def _place(api, case_id, artifact_id, expected_case_version, headers=CURATOR):
    """Issue one placement request and hand back the raw response."""
    return api.create_placement(
        case_id, f.placement_payload(artifact_id, expected_case_version), headers
    )


def _read_case(api, case_id, headers=PM):
    return get_success_data(api.get_artifact_case(case_id, headers), 200)


def _read_artifact(api, artifact_id, headers=CURATOR):
    return get_success_data(api.get_artifact(artifact_id, headers), 200)


def _read_window(api, window_id, headers=PM):
    return get_success_data(api.get_install_window(window_id, headers), 200)


# ---------------------------------------------------------------------------
# One placement request, three rungs of the admission chain
# ---------------------------------------------------------------------------
def _case_and_four_candidate_objects(api):
    """An empty ENHANCED case at 50 percent RH plus or minus 2 and 50 lux.

    The four candidate objects are graded so that each one trips a different
    rung of the placement chain: the first is unstable and also over-classified
    and also too light-sensitive, the second is only over-classified and too
    light-sensitive, the third is only too light-sensitive, and the fourth
    breaks nothing.
    """
    ctx = _schematic_commission_with_one_zone(api)
    case = fx.create_case(
        api,
        ctx["project_id"],
        ctx["zone_id"],
        case_code="C-01",
        security_tier=SecurityTier.ENHANCED,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
    )
    unstable = fx.create_artifact(
        api,
        ctx["project_id"],
        accession_number="2021.1.1",
        material_class=MaterialClass.TEXTILE,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=30.0,
        security_class=SecurityTier.HIGH_VALUE,
        condition_status=ConditionStatus.UNSTABLE,
    )
    over_classified = fx.create_artifact(
        api,
        ctx["project_id"],
        accession_number="2021.1.2",
        material_class=MaterialClass.TEXTILE,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=30.0,
        security_class=SecurityTier.HIGH_VALUE,
        condition_status=ConditionStatus.STABLE,
    )
    too_dark = fx.create_artifact(
        api,
        ctx["project_id"],
        accession_number="2021.1.3",
        material_class=MaterialClass.TEXTILE,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=30.0,
        security_class=SecurityTier.ENHANCED,
        condition_status=ConditionStatus.STABLE,
    )
    admissible = fx.create_artifact(
        api,
        ctx["project_id"],
        accession_number="2021.1.4",
        material_class=MaterialClass.PAPER,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
        condition_status=ConditionStatus.STABLE,
    )
    ctx.update(
        case=case,
        case_id=case["id"],
        case_version=case["version"],
        unstable_id=unstable["id"],
        over_classified_id=over_classified["id"],
        too_dark_id=too_dark["id"],
        admissible_id=admissible["id"],
    )
    return ctx


def test_an_unstable_object_reports_its_condition_not_its_security_class(api):
    """The object is unstable, over-classified and too light-sensitive at once.

    Condition sits above both the security tier and the environmental envelope
    in the admission chain, so the refusal names the condition and nothing about
    the case moves.

    PRD section 3.4: "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/condition_beats_security_which_beats_the_environmental_envelope_on_one_placement
    """
    ctx = _case_and_four_candidate_objects(api)

    validate_error(
        _place(api, ctx["case_id"], ctx["unstable_id"], ctx["case_version"]),
        ERR_ARTIFACT_CONDITION_UNSTABLE,
        422,
    )

    case = _read_case(api, ctx["case_id"])
    assert case["version"] == ctx["case_version"]
    assert case["placed_artifact_count"] == 0
    assert _read_artifact(api, ctx["unstable_id"])["placement_status"] == (
        PlacementStatus.UNPLACED
    )


def test_an_over_classified_object_reports_security_not_the_envelope(api):
    """The object is stable but both too valuable for the case and too light-sensitive.

    The security test is deliberately above the environmental one, so a request
    that breaks both reports the security failure.

    PRD section 3.4: "The security test sits above the environmental test deliberately, so a request that breaks both reports the security failure."

    PRD section 2.11: "On a placement, the security-tier check runs **above** the environmental-envelope check, so a request that breaks both reports `ERR_SECURITY_TIER_INSUFFICIENT` rather than `ERR_ENV_ENVELOPE_INFEASIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/condition_beats_security_which_beats_the_environmental_envelope_on_one_placement
    """
    ctx = _case_and_four_candidate_objects(api)

    validate_error(
        _place(api, ctx["case_id"], ctx["over_classified_id"], ctx["case_version"]),
        ERR_SECURITY_TIER_INSUFFICIENT,
        422,
    )

    case = _read_case(api, ctx["case_id"])
    assert case["version"] == ctx["case_version"]
    assert case["placed_artifact_count"] == 0
    assert _read_artifact(api, ctx["over_classified_id"])["assigned_case_id"] is None


def test_the_envelope_refusal_is_reported_only_when_it_is_the_only_breach(api):
    """A stable, correctly classified object still fails on 30 lux against 50.

    With the two higher rungs satisfied the recomputed envelope is what refuses
    the placement, because the case's designed illuminance would exceed the
    strictest ceiling the contents allow.

    PRD section 3.4: "`env_feasible` is true only when all five of the following hold together: the derived floor is no greater than the derived ceiling; the case's setpoint less its tolerance is at least the derived floor; the case's setpoint plus its tolerance is at most the derived ceiling; the case's `target_lux` is at most `allowed_lux`; and the case's `uv_microwatt_per_lumen` is at most 75.0 microwatts per lumen."

    Design: Difficulty/priority_pair_validation_conflict/condition_beats_security_which_beats_the_environmental_envelope_on_one_placement
    """
    ctx = _case_and_four_candidate_objects(api)

    validate_error(
        _place(api, ctx["case_id"], ctx["too_dark_id"], ctx["case_version"]),
        ERR_ENV_ENVELOPE_INFEASIBLE,
        422,
    )

    case = _read_case(api, ctx["case_id"])
    assert case["version"] == ctx["case_version"]
    assert case["placed_artifact_count"] == 0
    assert case["allowed_lux"] is None


def test_three_refusals_leave_the_case_version_intact_for_the_admissible_object(api):
    """The three rejected requests mutate nothing, so the fourth still matches the version.

    All four requests carry the same expected_case_version, and the fourth
    succeeds with it, which proves the refusals wrote nothing; the accepted
    object then rewrites the case's derived envelope from the new set.

    PRD section 3.4: "A successful placement sets the object's `assigned_case_id` to the case, moves its `placement_status` `UNPLACED → RESERVED`, increments the case's `placed_artifact_count`, and rewrites `required_rh_min_pct`, `required_rh_max_pct`, `allowed_lux`, `env_feasible` and `security_ok` from the new set."

    Design: Difficulty/priority_pair_validation_conflict/condition_beats_security_which_beats_the_environmental_envelope_on_one_placement
    """
    ctx = _case_and_four_candidate_objects(api)
    version = ctx["case_version"]

    validate_error(
        _place(api, ctx["case_id"], ctx["unstable_id"], version),
        ERR_ARTIFACT_CONDITION_UNSTABLE,
        422,
    )
    validate_error(
        _place(api, ctx["case_id"], ctx["over_classified_id"], version),
        ERR_SECURITY_TIER_INSUFFICIENT,
        422,
    )
    validate_error(
        _place(api, ctx["case_id"], ctx["too_dark_id"], version),
        ERR_ENV_ENVELOPE_INFEASIBLE,
        422,
    )

    placed = get_success_data(
        _place(api, ctx["case_id"], ctx["admissible_id"], version), 201
    )
    assert placed["placement_status"] == PlacementStatus.RESERVED
    assert placed["assigned_case_id"] == ctx["case_id"]

    case = _read_case(api, ctx["case_id"])
    assert_envelope(
        case,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )
    assert case["version"] == version + 1


# ---------------------------------------------------------------------------
# Case status is a resource-state test and outranks the placement chain
# ---------------------------------------------------------------------------
def _two_cases_each_holding_one_object(api):
    """Two cases in one zone, each already holding one reserved object."""
    ctx = _schematic_commission_with_one_zone(api)
    first_case = fx.create_case(
        api,
        ctx["project_id"],
        ctx["zone_id"],
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
        rh_tolerance_pct=2.0,
    )
    second_case = fx.create_case(
        api,
        ctx["project_id"],
        ctx["zone_id"],
        case_code="C-02",
        objective_code=OBJECTIVE_SECONDARY,
        rh_tolerance_pct=2.0,
    )
    reserved = fx.create_artifact(
        api,
        ctx["project_id"],
        accession_number="2019.14.3",
        material_class=MaterialClass.PAPER,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    resident = fx.create_artifact(
        api,
        ctx["project_id"],
        accession_number="2020.7.1",
        material_class=MaterialClass.COMPOSITE,
        required_rh_min_pct=40.0,
        required_rh_max_pct=60.0,
        max_lux=80.0,
        security_class=SecurityTier.BASIC,
    )
    fx.place_artifact(api, first_case["id"], reserved["id"])
    fx.place_artifact(api, second_case["id"], resident["id"])
    ctx.update(
        first_case_id=first_case["id"],
        second_case_id=second_case["id"],
        reserved_id=reserved["id"],
        resident_id=resident["id"],
    )
    return ctx


def test_a_reserved_object_offered_to_a_draft_case_reports_that_it_is_already_placed(api):
    """The target case is DRAFT, so only the object's own status can refuse the request.

    The receiving case is a legal target and the request carries its current
    version, so the chain reaches the second rung and stops there.

    PRD section 3.4: "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/case_state_outranks_artifact_already_placed_on_the_same_request
    """
    ctx = _two_cases_each_holding_one_object(api)
    target_before = _read_case(api, ctx["second_case_id"])
    assert target_before["status"] == CaseStatus.DRAFT
    artifact_before = _read_artifact(api, ctx["reserved_id"])

    validate_error(
        _place(api, ctx["second_case_id"], ctx["reserved_id"], target_before["version"]),
        ERR_ARTIFACT_ALREADY_PLACED,
        409,
    )

    target_after = _read_case(api, ctx["second_case_id"])
    assert_unchanged(target_before, target_after, ["version", "placed_artifact_count"])
    artifact_after = _read_artifact(api, ctx["reserved_id"])
    assert_unchanged(
        artifact_before,
        artifact_after,
        ["version", "placement_status", "assigned_case_id"],
    )
    assert artifact_after["assigned_case_id"] == ctx["first_case_id"]
    assert artifact_after["placement_status"] == PlacementStatus.RESERVED


def test_once_the_target_case_is_approved_the_same_request_reports_the_case_state(api):
    """The identical request now breaks two rules and names the case state.

    Approving the receiving case makes it an illegal target while the object is
    still reserved elsewhere; the case-status test is a resource-state check and
    sits above the placement chain, so the case state is what is reported.

    PRD section 2.11: "The state of the specific resource being acted on, in the order package, round, round deadline, case status, mount dimension, material status, drawing status, interactive status, window status, punch status."

    PRD section 3.4: "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/case_state_outranks_artifact_already_placed_on_the_same_request
    """
    ctx = _two_cases_each_holding_one_object(api)
    fx.approve_case(api, ctx["second_case_id"])
    target_before = _read_case(api, ctx["second_case_id"])
    assert target_before["status"] == CaseStatus.APPROVED
    artifact_before = _read_artifact(api, ctx["reserved_id"])

    validate_error(
        _place(api, ctx["second_case_id"], ctx["reserved_id"], target_before["version"]),
        ERR_INVALID_CASE_STATE,
        409,
    )

    target_after = _read_case(api, ctx["second_case_id"])
    assert_unchanged(
        target_before, target_after, ["version", "status", "placed_artifact_count"]
    )
    artifact_after = _read_artifact(api, ctx["reserved_id"])
    assert_unchanged(
        artifact_before,
        artifact_after,
        ["version", "placement_status", "assigned_case_id"],
    )
    assert artifact_after["assigned_case_id"] == ctx["first_case_id"]


# ---------------------------------------------------------------------------
# The per-zone calendar outranks the project-wide closure budget
# ---------------------------------------------------------------------------
def _fabrication_commission_with_two_closable_zones(api):
    """A commission in FABRICATION tolerating exactly one concurrent closure.

    Both zones permit closure, the first learning objective is carried by a case
    in the first zone and the second by an interactive, and one closure window
    already stands approved on the first zone from 08:00 to 12:00.
    """
    fx.set_clock(api)
    project = fx.create_project(api, max_concurrent_closures=1)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone_a = fx.create_zone(
        api,
        project_id,
        zone_code="Z-A",
        visitor_route_order=1,
        closure_allowed=True,
    )
    zone_b = fx.create_zone(
        api,
        project_id,
        zone_code="Z-B",
        visitor_route_order=2,
        closure_allowed=True,
    )
    fx.create_case(
        api,
        project_id,
        zone_a["id"],
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
    )
    fx.create_interactive(api, project_id)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    approved = fx.create_window(
        api,
        project_id,
        zone_a["id"],
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T12:00:00Z",
        requires_gallery_closure=True,
    )
    fx.decide_window(api, approved["id"])
    return {
        "project_id": project_id,
        "zone_a_id": zone_a["id"],
        "zone_b_id": zone_b["id"],
        "approved_window_id": approved["id"],
    }


def test_a_closure_colliding_on_its_own_zone_reports_the_conflict_not_the_capacity(api):
    """The rival closure overlaps its neighbour and also breaks the one-closure cap.

    Both windows sit on the same zone with buffers of zero, so the half-open
    comparison finds a genuine overlap, and the two concurrent closures also
    exceed the project's cap of one; the per-zone check runs first, so the
    conflict is what the caller is told.

    PRD section 2.11: "On an install-window approval, the per-zone buffered conflict check runs **above** the project-wide closure-capacity check, so a window that breaks both reports `ERR_ZONE_WINDOW_CONFLICT` rather than `ERR_CLOSURE_CAPACITY_EXCEEDED`."

    PRD section 3.9: "Two windows on the same zone conflict when the interval each defines with its effective instants overlaps the other's, and the comparison is **half-open**: they conflict when the new window's `effective_start_at` is strictly before the other's `effective_end_at` and the other's `effective_start_at` is strictly before the new window's `effective_end_at`."

    Design: Difficulty/priority_pair_validation_conflict/per_zone_window_conflict_outranks_project_wide_closure_capacity
    """
    ctx = _fabrication_commission_with_two_closable_zones(api)
    rival = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_a_id"],
        starts_at="2026-09-10T10:00:00Z",
        ends_at="2026-09-10T14:00:00Z",
        requires_gallery_closure=True,
    )
    assert rival["pre_access_buffer_minutes"] == 0
    assert rival["settling_buffer_minutes"] == 0

    validate_error(
        api.window_decision(rival["id"], f.window_decision_payload(), OPERATIONS),
        ERR_ZONE_WINDOW_CONFLICT,
        409,
    )

    after = _read_window(api, rival["id"])
    assert after["status"] == WindowStatus.REQUESTED
    assert after["denial_reason"] is None
    assert_unchanged(rival, after, ["status", "version"])


def test_a_closure_on_a_free_zone_reports_the_project_wide_capacity(api):
    """With no neighbour to collide with, the closure budget is the rule that bites.

    The second zone's calendar is empty, so the conflict rung passes and the
    capacity sweep sees two overlapping closures against a cap of one.

    PRD section 3.9: "The closure-capacity check considers every window in the project whose `requires_gallery_closure` is true and whose status is `APPROVED` or `IN_PROGRESS`, together with the window currently being approved, and it uses each window's **nominal** `starts_at` and `ends_at` with no buffers at all."

    PRD section 3.9: "The peak is the highest running total the sweep reaches, and when it exceeds the project's `max_concurrent_closures`, which defaults to 2, the approval is refused."

    Design: Difficulty/priority_pair_validation_conflict/per_zone_window_conflict_outranks_project_wide_closure_capacity
    """
    ctx = _fabrication_commission_with_two_closable_zones(api)
    neighbourless = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_b_id"],
        starts_at="2026-09-10T10:00:00Z",
        ends_at="2026-09-10T14:00:00Z",
        requires_gallery_closure=True,
    )

    validate_error(
        api.window_decision(
            neighbourless["id"], f.window_decision_payload(), OPERATIONS
        ),
        ERR_CLOSURE_CAPACITY_EXCEEDED,
        409,
    )

    after = _read_window(api, neighbourless["id"])
    assert after["status"] == WindowStatus.REQUESTED
    assert after["denial_reason"] is None
    assert_unchanged(neighbourless, after, ["status", "version"])


def test_a_closure_on_the_following_day_clears_both_checks(api):
    """Moved a day later the same closure request is approved.

    The peak concurrency the sweep reaches is one, which is exactly the cap, and
    a QUIET window's effective instants are its nominal ones because both of its
    buffers are zero.

    PRD section 3.9: "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."

    Design: Difficulty/priority_pair_validation_conflict/per_zone_window_conflict_outranks_project_wide_closure_capacity
    """
    ctx = _fabrication_commission_with_two_closable_zones(api)
    next_day = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_b_id"],
        starts_at="2026-09-11T08:00:00Z",
        ends_at="2026-09-11T12:00:00Z",
        requires_gallery_closure=True,
    )

    decided = fx.decide_window(api, next_day["id"])
    assert decided["status"] == WindowStatus.APPROVED
    assert decided["denial_reason"] is None
    assert decided["effective_start_at"] == decided["starts_at"]
    assert decided["effective_end_at"] == decided["ends_at"]

    assert (
        _read_window(api, ctx["approved_window_id"])["status"] == WindowStatus.APPROVED
    )


# ---------------------------------------------------------------------------
# The conservation freeze outranks the fabrication budget
# ---------------------------------------------------------------------------
def _commission_with_a_costly_sheet_under_review(api):
    """A commission in FABRICATION with one sheet priced far beyond the contract.

    The sheet is CONSERVATION_GRADE for 1000 shop hours over 200 square metres
    of case-interior board, which prices it well past the whole 9,000,000-cent
    commission, and it stands UNDER_REVIEW awaiting a ruling. A second case sits
    in conservator review, ready to be refused so the commission freezes.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone = fx.create_zone(api, project_id)
    subject_case = fx.create_case(
        api,
        project_id,
        zone["id"],
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
        rh_tolerance_pct=2.0,
    )
    second_case = fx.create_case(
        api,
        project_id,
        zone["id"],
        case_code="C-02",
        objective_code=OBJECTIVE_SECONDARY,
        rh_tolerance_pct=2.0,
    )
    first_object = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.3",
        material_class=MaterialClass.PAPER,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    second_object = fx.create_artifact(
        api,
        project_id,
        accession_number="2020.7.1",
        material_class=MaterialClass.COMPOSITE,
        required_rh_min_pct=40.0,
        required_rh_max_pct=60.0,
        max_lux=80.0,
        security_class=SecurityTier.BASIC,
    )
    fx.place_artifact(api, subject_case["id"], first_object["id"])
    fx.place_artifact(api, second_case["id"], second_object["id"])
    fx.approve_case(api, subject_case["id"])
    fx.submit_case(api, second_case["id"])
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    material = fx.create_material(api, project_id)
    fx.approve_material(api, material["id"])
    drawing = fx.create_drawing(
        api,
        project_id,
        material["id"],
        drawing_number="SD-501",
        complexity_tier=ComplexityTier.CONSERVATION_GRADE,
        shop_hours=1000.0,
        material_area_m2=200.0,
        finish_grade=FinishGrade.MILL,
        subject_case_id=subject_case["id"],
    )
    get_success_data(api.start_drawing_review(drawing["id"], PM), 200)
    return {
        "project_id": project_id,
        "zone_id": zone["id"],
        "subject_case_id": subject_case["id"],
        "second_case_id": second_case["id"],
        "material_id": material["id"],
        "drawing_id": drawing["id"],
        "drawing_created": drawing,
    }


def _rule_on_the_costly_sheet(api, drawing_id):
    """Approve the sheet with the shop's real figures: 1000 hours, no waste."""
    return api.drawing_decision(
        drawing_id,
        f.drawing_decision_payload(
            DrawingDecision.APPROVE, actual_shop_hours=1000.0, actual_waste_factor=1.0
        ),
        PM,
    )


def test_the_advisory_estimate_is_written_at_issue_without_any_budget_check(api):
    """The schematic estimate exceeds the whole contract and is stored anyway.

    Labour is 1000 hours at 18,500 cents with the 1.15 contingency, material is
    200 square metres at 42,500 cents with the 1.20 allowance, and a MILL finish
    adds nothing; the three rounded line items sum to 31,475,000 cents against a
    9,000,000-cent commission, and no money has moved.

    PRD section 3.7: "The three results land in `estimate_labor_cents`, `estimate_material_cents` and `estimate_finishing_cents`, with `estimate_total_cents` as their sum, and **no money moves** — the estimate is advisory."

    PRD section 3.7: "At issue it runs as a **schematic estimate**: the hours are the submitted `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and the waste factor is the schematic allowance of 1.20."

    Design: Difficulty/priority_pair_validation_conflict/conservation_freeze_outranks_the_fabrication_budget_check
    """
    ctx = _commission_with_a_costly_sheet_under_review(api)
    sheet = ctx["drawing_created"]
    assert sheet["estimate_labor_cents"] == 21275000
    assert sheet["estimate_material_cents"] == 10200000
    assert sheet["estimate_finishing_cents"] == 0
    assert sheet["estimate_total_cents"] == 31475000
    assert sheet["actual_cost_cents"] is None

    project = fx.read_project(api, ctx["project_id"])
    assert_ledger(project, committed=0, uncommitted=9000000)


def test_the_frozen_commission_refuses_the_ruling_before_it_ever_prices_it(api):
    """The sheet is unaffordable and the commission is frozen; the freeze is reported.

    A refused case has frozen the commission, and the ruling would also blow the
    budget, but posture is checked long before fiscal capacity, so the caller is
    told about the conservation freeze and nothing on the sheet moves.

    PRD section 2.11: "Because money is checked last, a request that also violates a conservation or constraint rule never reports a budget error."

    PRD section 3.7: "That total must fit inside the project's `uncommitted_cents`, or the ruling is refused with `ERR_FABRICATION_BUDGET_EXCEEDED` (HTTP 402); because fiscal capacity is the last thing checked, a request that also breaks a conservation or state rule never reports a budget error."

    Design: Difficulty/priority_pair_validation_conflict/conservation_freeze_outranks_the_fabrication_budget_check
    """
    ctx = _commission_with_a_costly_sheet_under_review(api)
    fx.decide_case(api, ctx["second_case_id"], CaseDecision.REJECT)
    frozen = fx.read_project(api, ctx["project_id"])
    assert_counters(
        frozen, conservation_block_count=1, posture=Posture.FROZEN_CONSERVATION
    )
    sheet_before = get_success_data(api.get_shop_drawing(ctx["drawing_id"], PM), 200)

    validate_error(
        _rule_on_the_costly_sheet(api, ctx["drawing_id"]),
        ERR_PROJECT_FROZEN_CONSERVATION,
        409,
    )

    sheet_after = get_success_data(api.get_shop_drawing(ctx["drawing_id"], PM), 200)
    assert sheet_after["status"] == DrawingStatus.UNDER_REVIEW
    assert sheet_after["actual_cost_cents"] is None
    assert_unchanged(sheet_before, sheet_after, ["status", "version", "updated_at"])
    assert_ledger(fx.read_project(api, ctx["project_id"]), committed=0, uncommitted=9000000)


def test_with_no_conservation_block_in_the_way_the_ruling_reports_the_budget(api):
    """On an unfrozen commission the identical ruling exposes the fiscal refusal.

    Nothing blocks conservation, so the ruling reaches the last rung of the
    ladder, where 27,000,000 cents of actual cost — 1000 real shop hours at the
    CONSERVATION_GRADE rate plus 200 square metres of case-interior board with no
    waste and a MILL finish adding nothing — cannot fit inside the 9,000,000
    cents of uncommitted money.

    PRD section 3.7: "That total must fit inside the project's `uncommitted_cents`, or the ruling is refused with `ERR_FABRICATION_BUDGET_EXCEEDED` (HTTP 402); because fiscal capacity is the last thing checked, a request that also breaks a conservation or state rule never reports a budget error."

    Design: Difficulty/priority_pair_validation_conflict/conservation_freeze_outranks_the_fabrication_budget_check
    """
    ctx = _commission_with_a_costly_sheet_under_review(api)
    unblocked = fx.read_project(api, ctx["project_id"])
    assert_counters(unblocked, conservation_block_count=0, posture=Posture.OPEN)

    validate_error(
        _rule_on_the_costly_sheet(api, ctx["drawing_id"]),
        ERR_FABRICATION_BUDGET_EXCEEDED,
        402,
    )

    sheet = get_success_data(api.get_shop_drawing(ctx["drawing_id"], PM), 200)
    assert sheet["status"] == DrawingStatus.UNDER_REVIEW
    assert sheet["actual_shop_hours"] is None
    assert sheet["actual_waste_factor"] is None
    assert sheet["actual_cost_cents"] is None
    assert_ledger(fx.read_project(api, ctx["project_id"]), committed=0, uncommitted=9000000)
