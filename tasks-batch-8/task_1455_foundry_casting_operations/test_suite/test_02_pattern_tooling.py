"""Pattern tooling: dimension computation, qualification tolerance, revision
chains, and retirement guards."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_casting,
    advance_casting,
    compute_pattern_dimensions,
    create_active_pattern,
    create_foundry,
    create_mold,
    create_pattern_payload,
    get_mold,
    get_pattern,
    run_ops,
    setup_casting_at_final_inspection,
    setup_shop,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["foundry_admin_headers"]
PM = TEST_USERS["pattern_maker_headers"]


class TestPatternCreation:
    def test_pattern_create_computes_dimensions_and_defaults(self, api):
        """PRD §3.2: "The axis dimension is then the finished dimension plus that
        effective allowance, the sum multiplied by one plus the shrink factor for
        the pattern's alloy class and process, and the result rounded half-up to
        one decimal place, per axis." and "A new pattern starts in `DRAFT` with
        `qualification_attempts` at zero."

        Design: Corner/entities/pattern_create_computes_dimensions_and_defaults
        """
        foundry = create_foundry()
        # ALUMINUM on SAND: (200.0 + min(3.0, 6.0)) * 1.0130 = 205.639 -> 205.6
        payload = create_pattern_payload(
            foundry["id"], part_number="PN-A", alloy_shrink_class="ALUMINUM",
            mold_process="SAND", finish_dimensions_mm=[200.0],
            machining_allowance_mm=3.0, impressions=2)
        pattern = validate_success(api.create_pattern(payload, PM), expected_status=201)
        assert pattern["pattern_dimensions_mm"] == pytest.approx([205.6], abs=1e-9)
        assert pattern["status"] == "DRAFT"
        assert pattern["qualification_attempts"] == 0
        assert isinstance(pattern["version"], int)
        assert pattern["id"]

    def test_pattern_create_missing_required_field_rejected(self, api):
        """PRD §3.2: "Creation takes the owning `foundry_id`, the customer
        `part_number`, an `alloy_shrink_class` of `FERROUS` or `ALUMINUM`, a
        `mold_process` of `SAND` or `INVESTMENT`, the ordered finished-casting
        axis dimensions `finish_dimensions_mm` (an array of one to five
        millimeter values), the requested per-axis machining stock
        `machining_allowance_mm`, and the cavity count `impressions` — the
        number of castings each mold of this pattern produces per pour, which
        must be a positive integer or the request is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/pattern_create_missing_required_field_rejected
        """
        foundry = create_foundry()
        payload = create_pattern_payload(foundry["id"])
        del payload["part_number"]
        res = api.create_pattern(payload, PM)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestPatternDimensionsProcessBranch:
    """Identical numeric inputs diverge purely through the process branch."""

    def test_pattern_dimensions_sand_branch(self, api):
        """PRD §3.2: "For each axis, the effective machining allowance is the
        lesser of `machining_allowance_mm` and the process cap — 6.0 millimeters
        for `SAND`, 2.5 millimeters for `INVESTMENT`." and "The shrink factors
        are: `FERROUS` on `SAND` 0.0104, `FERROUS` on `INVESTMENT` 0.0120,
        `ALUMINUM` on `SAND` 0.0130, and `ALUMINUM` on `INVESTMENT` 0.0110."

        Design: Difficulty/combinatorial_formula/pattern_dimensions_process_branch_and_cap
        """
        foundry = create_foundry()
        payload = create_pattern_payload(
            foundry["id"], part_number="PN-S", alloy_shrink_class="FERROUS",
            mold_process="SAND", finish_dimensions_mm=[100.0, 50.0, 25.0],
            machining_allowance_mm=8.0, impressions=1)
        pattern = validate_success(api.create_pattern(payload, PM), expected_status=201)
        # min(8.0, 6.0) = 6.0; (d + 6.0) * 1.0104 per axis, 1 dp round half-up
        assert pattern["pattern_dimensions_mm"] == pytest.approx(
            [107.1, 56.6, 31.3], abs=1e-9)

    def test_pattern_dimensions_investment_branch(self, api):
        """PRD §3.2: "For each axis, the effective machining allowance is the
        lesser of `machining_allowance_mm` and the process cap — 6.0 millimeters
        for `SAND`, 2.5 millimeters for `INVESTMENT`." and "The shrink factors
        are: `FERROUS` on `SAND` 0.0104, `FERROUS` on `INVESTMENT` 0.0120,
        `ALUMINUM` on `SAND` 0.0130, and `ALUMINUM` on `INVESTMENT` 0.0110."

        Design: Difficulty/combinatorial_formula/pattern_dimensions_process_branch_and_cap
        """
        foundry = create_foundry()
        payload = create_pattern_payload(
            foundry["id"], part_number="PN-I", alloy_shrink_class="FERROUS",
            mold_process="INVESTMENT", finish_dimensions_mm=[100.0, 50.0, 25.0],
            machining_allowance_mm=8.0, impressions=1)
        pattern = validate_success(api.create_pattern(payload, PM), expected_status=201)
        # min(8.0, 2.5) = 2.5; (d + 2.5) * 1.0120 per axis
        assert pattern["pattern_dimensions_mm"] == pytest.approx(
            [103.7, 53.1, 27.8], abs=1e-9)


class TestQualification:
    def test_pattern_qualify_fail_loops_back_to_draft(self, api):
        """PRD §3.2: "The trial passes when every axis deviates from its computed
        `pattern_dimensions_mm` axis by at most 0.3 millimeters in absolute
        terms; a deviation of exactly 0.3 millimeters passes. On a pass the
        pattern advances `DRAFT → QUALIFICATION → ACTIVE`; on a fail it returns
        to `DRAFT`." and "Each submission increments `qualification_attempts`
        by one and is evaluated immediately"

        Design: Corner/state_machines/pattern_qualify_fail_loops_back_to_draft
        """
        foundry = create_foundry()
        payload = create_pattern_payload(foundry["id"])
        pattern = validate_success(api.create_pattern(payload, PM), expected_status=201)
        # Computed dims [107.1, 56.6, 31.3]; axis 1 deviates by 0.9 > 0.3.
        res = api.qualify_pattern(
            pattern["id"], {"measured_dimensions_mm": [108.0, 56.6, 31.3]}, PM)
        after = validate_success(res, expected_status=200)
        assert after["status"] == "DRAFT"
        assert after["qualification_attempts"] == 1

    def test_pattern_qualify_passes_at_exact_tolerance(self, api):
        """PRD §3.2: "The trial passes when every axis deviates from its computed
        `pattern_dimensions_mm` axis by at most 0.3 millimeters in absolute
        terms; a deviation of exactly 0.3 millimeters passes."

        Design: Corner/state_machines/pattern_qualify_passes_at_exact_tolerance
        """
        foundry = create_foundry()
        payload = create_pattern_payload(foundry["id"])
        pattern = validate_success(api.create_pattern(payload, PM), expected_status=201)
        # Every axis deviates by exactly 0.3 mm from [107.1, 56.6, 31.3].
        res = api.qualify_pattern(
            pattern["id"], {"measured_dimensions_mm": [107.4, 56.3, 31.0]}, PM)
        after = validate_success(res, expected_status=200)
        assert after["status"] == "ACTIVE"


class TestRevisionChain:
    def test_pattern_revision_activation_supersedes_parent(self, api):
        """PRD §3.2: "When activation succeeds against an `ACTIVE` parent, the
        parent is automatically superseded — `ACTIVE → SUPERSEDED` — so the
        revision chain has exactly one live head."

        Design: Corner/state_machines/pattern_revision_activation_supersedes_parent
        """
        foundry = create_foundry()
        pat_a = create_active_pattern(foundry["id"], part_number="PN-1",
                                      dimensions=[100.0])
        child = validate_success(api.create_pattern(
            create_pattern_payload(foundry["id"], part_number="PN-1",
                                   finish_dimensions_mm=[100.0],
                                   parent_pattern_id=pat_a["id"]), PM),
            expected_status=201)
        measured = compute_pattern_dimensions([100.0], 8.0)
        after = validate_success(api.qualify_pattern(
            child["id"], {"measured_dimensions_mm": measured}, PM))
        assert after["status"] == "ACTIVE"
        parent_after = validate_success(api.get_pattern(pat_a["id"], PM))
        assert parent_after["status"] == "SUPERSEDED"

    def test_second_revision_activation_rejected(self, api):
        """PRD §3.2: "Activation carries two uniqueness guards, both raising
        `ERR_ACTIVE_REVISION_EXISTS` and returning the pattern to `DRAFT` when
        violated: if `parent_pattern_id` is set, the parent must still be
        `ACTIVE` at that moment (a sibling revision having already activated
        means the parent has moved on), and no other `ACTIVE` pattern may exist
        for the same `part_number`."

        Design: Corner/state_machines/second_revision_activation_rejected
        """
        foundry = create_foundry()
        pat_a = create_active_pattern(foundry["id"], part_number="PN-1",
                                      dimensions=[100.0])
        pat_b = validate_success(api.create_pattern(
            create_pattern_payload(foundry["id"], part_number="PN-1",
                                   finish_dimensions_mm=[100.0],
                                   parent_pattern_id=pat_a["id"]), PM),
            expected_status=201)
        # pat_c is declared while pat_b is still DRAFT: creation is legal per
        # PRD §3.2 ("If the named parent already has an `ACTIVE` child
        # revision, creation is rejected") because no ACTIVE child exists yet.
        pat_c = validate_success(api.create_pattern(
            create_pattern_payload(foundry["id"], part_number="PN-1",
                                   finish_dimensions_mm=[100.0],
                                   parent_pattern_id=pat_a["id"]), PM),
            expected_status=201)
        measured = compute_pattern_dimensions([100.0], 8.0)
        # Sibling pat_b activates first; pat_a is superseded ("the parent has
        # moved on").
        validate_success(api.qualify_pattern(
            pat_b["id"], {"measured_dimensions_mm": measured}, PM))

        res = api.qualify_pattern(
            pat_c["id"], {"measured_dimensions_mm": measured}, PM)
        validate_error(res, "ERR_ACTIVE_REVISION_EXISTS", expected_status=409)
        c_after = validate_success(api.get_pattern(pat_c["id"], PM))
        assert c_after["status"] == "DRAFT"


class TestPatternRetirement:
    def test_pattern_retire_with_open_mold_rejected(self, api):
        """PRD §3.2: "a `PatternMaker` retires an `ACTIVE` pattern only while no
        mold referencing it sits in `ASSEMBLED`, `POURED`, or `COOLED`;
        otherwise the attempt is rejected with `ERR_PATTERN_HAS_OPEN_MOLDS`."

        Design: Corner/state_machines/pattern_retire_with_open_mold_rejected
        """
        ctx = setup_shop()
        create_mold(ctx["pattern"]["id"], ctx["batch"]["id"], ctx["order"]["id"],
                    sand_weight_kg=50, metal_weight_kg=200, cooling_hours=2)
        res = api.retire_pattern(ctx["pattern"]["id"], PM)
        validate_error(res, "ERR_PATTERN_HAS_OPEN_MOLDS", expected_status=409)
        after = get_pattern(ctx["pattern"]["id"])
        assert after["status"] == "ACTIVE"

    def test_pattern_retire_succeeds_after_molds_closed(self, api):
        """PRD §3.2: "a `PatternMaker` retires an `ACTIVE` pattern only while no
        mold referencing it sits in `ASSEMBLED`, `POURED`, or `COOLED`" and
        PRD §3.1: "every `SHAKEOUT` mold whose castings have all reached a
        terminal condition (routing `COMPLETE` or quality `SCRAPPED`)
        transitions `SHAKEOUT → CLOSED`".

        Design: Corner/state_machines/pattern_retire_succeeds_after_molds_closed
        """
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        accept_casting(casting_id)
        completed = advance_casting(casting_id, steps=1)
        assert completed["routing_status"] == "COMPLETE"

        run_ops(ctx["foundry"]["id"])
        mold_after = get_mold(ctx["molds"][0]["id"])
        assert mold_after["status"] == "CLOSED"

        retired = validate_success(api.retire_pattern(ctx["pattern"]["id"], PM))
        assert retired["status"] == "RETIRED"
