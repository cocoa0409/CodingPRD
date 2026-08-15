"""The alignment gate: vetted-material presence, coverage threshold
inclusivity, and the material transition machine's from-state rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_cycle,
    create_framework,
    create_material,
    get_material,
    transition_cycle,
    upsert_alignment,
    validate_error,
    validate_error_is_one_of,
    vet_material,
)

SPECIALIST = TEST_USERS["instructional_specialist_headers"]


class TestAlignmentGate:
    def test_no_vetted_materials_at_alignment_gate(self, api):
        """PRD §3.2: "Two checks guard it, evaluated in this order. First, at
        least one material of the cycle must be `VETTED`, or the attempt fails
        with `ERR_NO_VETTED_MATERIALS`."

        Design: Corner/validations/no_vetted_materials_at_alignment_gate
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        create_material(cycle["id"])  # left in SUBMITTED, never vetted
        transition_cycle(cycle["id"], "ALIGNMENT_REVIEW")
        validate_error(api.transition_cycle(cycle["id"],
                                            {"to_state": "PILOT_OPEN"}, SPECIALIST),
                       ApiErrorId.ERR_NO_VETTED_MATERIALS)

    def test_alignment_coverage_below_threshold_rejected(self, api):
        """PRD §3.2: "Second, every `VETTED` material of the cycle must show
        a `coverage_pct` of at least 85.00 — the boundary is inclusive, so
        exactly 85.00 passes — or the attempt fails with
        `ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD`."
        PRD §3.2: "each mapping contributes a weight — 1.0 for `FULL`, 0.5
        for `PARTIAL`, 0.0 for `NONE` — and the percentage is one hundred
        times the sum of those weights divided by the backing framework's
        `standards_required_count`, rounded half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/alignment_coverage_threshold_inclusive
        """
        # 20 required standards; 16 FULL + 1 PARTIAL -> coverage 82.50 < 85.00.
        framework = create_framework(standards_required_count=20)
        cycle = create_cycle(framework["id"])
        material = create_material(cycle["id"])
        vet_material(material["id"])
        for i in range(1, 17):
            upsert_alignment(material["id"], standard_code=f"S{i:02d}",
                             coverage_rating="FULL")
        upsert_alignment(material["id"], standard_code="S17",
                         coverage_rating="PARTIAL")
        assert get_material(material["id"])["coverage_pct"] == 82.50
        transition_cycle(cycle["id"], "ALIGNMENT_REVIEW")
        validate_error(api.transition_cycle(cycle["id"],
                                            {"to_state": "PILOT_OPEN"}, SPECIALIST),
                       ApiErrorId.ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD)

    def test_alignment_coverage_exactly_threshold_passes(self, api):
        """PRD §3.2: "Second, every `VETTED` material of the cycle must show
        a `coverage_pct` of at least 85.00 — the boundary is inclusive, so
        exactly 85.00 passes — or the attempt fails with
        `ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD`."
        PRD §3.2: "The pair of material and `standard_code` acts as an upsert
        key: posting a code the material does not yet have creates the mapping
        (201), while posting an existing code updates that mapping's rating
        (200)."

        Design: Difficulty/boundary_precision_check/alignment_coverage_threshold_inclusive
        """
        # Same 82.50 setup, then upsert S17 PARTIAL -> FULL: 17.0/20 == 85.00.
        framework = create_framework(standards_required_count=20)
        cycle = create_cycle(framework["id"])
        material = create_material(cycle["id"])
        vet_material(material["id"])
        for i in range(1, 17):
            upsert_alignment(material["id"], standard_code=f"S{i:02d}",
                             coverage_rating="FULL")
        upsert_alignment(material["id"], standard_code="S17",
                         coverage_rating="PARTIAL")
        transition_cycle(cycle["id"], "ALIGNMENT_REVIEW")

        # Upsert the existing S17 code to FULL and recompute.
        upsert_alignment(material["id"], standard_code="S17",
                         coverage_rating="FULL")
        assert get_material(material["id"])["coverage_pct"] == 85.00

        # Exactly 85.00 passes the >= gate.
        updated = transition_cycle(cycle["id"], "PILOT_OPEN")
        assert updated["status"] == "PILOT_OPEN"


class TestMaterialTransitionGuards:
    def test_material_invalid_transition_rejected(self, api):
        """PRD §3.2: "From `SUBMITTED`, a material may advance to `VETTED` —
        but only while its cycle is still in `DRAFT` or `ALIGNMENT_REVIEW`;
        vetting against a cycle that has moved on is rejected with
        `ERR_INVALID_STATE`, as is vetting a material that is not
        `SUBMITTED`."
        PRD §2.7: "5. State: the target entity — and any cross-entity gate,
        such as the cycle status required for pilot activation — is in the
        required from-state (`ERR_INVALID_STATE`, `ERR_UNRESOLVED_PILOTS`,
        `ERR_OPEN_WORK_REMAINS`)."

        Design: Corner/state_machines/material_invalid_transition_rejected
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        material = create_material(cycle["id"])
        created_version = material["version"]

        # ADOPTED is reachable only through the board decision, never through
        # the material transition endpoint: the machine offers no transition
        # from SUBMITTED to ADOPTED. PRD §2.7 names both candidate tiers for
        # this rejection without pinning which fires: tier 4 if an
        # implementation scopes the `to_state` enum to the two
        # operator-reachable targets (ERR_VALIDATION), tier 5 if the enum
        # spans the whole adoption dimension (ERR_INVALID_STATE) — so the
        # exact error is relaxed to the PRD-named pair while the
        # no-transition / no-mutation claims stay exact.
        validate_error_is_one_of(
            api.transition_material(material["id"], {"to_state": "ADOPTED"},
                                    SPECIALIST),
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_VALIDATION])
        after = get_material(material["id"])
        assert after["adoption_status"] == "SUBMITTED"
        assert after["version"] == created_version, (
            "a rejected transition must not mutate the material")
