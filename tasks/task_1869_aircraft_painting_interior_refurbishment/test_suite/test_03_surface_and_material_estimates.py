"""Surface assessment cycle and the tiered paint material estimate (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    approve_scheme,
    book_booth_window,
    create_and_approve_scheme,
    create_assessment,
    create_booth,
    create_discovery,
    create_engagement,
    create_scheme,
    decide_assessment,
    get_program,
    setup_inducted_program,
    setup_surface_review_program,
    submit_scheme,
    validate_error,
    validate_success,
)
from test_helpers.factories import decide_assessment_payload

_TECH = TEST_USERS["shop_technician_headers"]


class TestMaterialEstimateBranches:
    def test_material_estimate_strip_default_before_any_decision(self, api):
        """PRD §3.3: "With the scheme approved, the program's computed
        `material_estimate_gallons` and `material_estimate_cost_cents` come to
        life from the pinned scheme and the current assessment decision — both
        read zero until a scheme reaches `APPROVED`". PRD §3.4: "The main-color
        gallons are the scheme's `painted_area_sqft` multiplied by its
        `coat_count` and divided by a coverage of 350 square feet per gallon ...
        Accent gallons are the painted area multiplied by the scheme's
        `stripe_pct` and divided by an accent coverage of 500 square feet per
        gallon, again rounded up" and "if no assessment is `DECIDED` yet, the
        prep mode defaults to `STRIP`" and "a total of at most 20 gallons bills
        every gallon at 18,500 cents".

        Design: Difficulty/combinatorial_formula/paint_material_tiered_estimate_scuff_branch
        """
        ctx = create_engagement()
        # Before any approval: both estimates read zero.
        before = get_program(ctx["program"]["id"])
        assert before["material_estimate_gallons"] == 0
        assert before["material_estimate_cost_cents"] == 0

        create_and_approve_scheme(ctx["program"]["id"], ctx["customer"]["id"])
        program = get_program(ctx["program"]["id"])
        # STRIP default: ceil(2400x2/350) = 14 main + ceil(2400x0.10/500) = 1
        # accent = 15 gal; 15 <= 20 -> 15 x 18500.
        assert program["material_estimate_gallons"] == 15
        assert program["material_estimate_cost_cents"] == 277500

    def test_material_estimate_scuff_branch_scales_before_ceil(self, api):
        """PRD §3.4: "under a `SCUFF` decision this raw figure is scaled by
        0.85 before rounding, reflecting that a scuff-and-spray lays less film
        than a full strip — and the result is rounded up to a whole gallon."

        Design: Difficulty/combinatorial_formula/paint_material_tiered_estimate_scuff_branch
        """
        # Induct the program, approve the scheme, then record a SCUFF decision.
        ctx = setup_inducted_program()
        ctx["scheme"] = create_and_approve_scheme(
            ctx["program"]["id"], ctx["customer"]["id"]
        )
        strip_read = get_program(ctx["program"]["id"])
        assert strip_read["material_estimate_gallons"] == 15

        assessment = create_assessment(ctx["program"]["id"])
        decide_assessment(assessment["id"], decision="SCUFF", corrosion_severity="LIGHT")

        scuff_read = get_program(ctx["program"]["id"])
        # SCUFF: ceil((2400x2/350) x 0.85) = ceil(11.657) = 12 main + 1 accent
        # = 13 gal; 13 <= 20 -> 13 x 18500.
        assert scuff_read["material_estimate_gallons"] == 13
        assert scuff_read["material_estimate_cost_cents"] == 240500


class TestMaterialTierBoundary:
    def test_tier_boundary_reprices_all_gallons(self, api):
        """PRD §3.4: "The total gallonage is the sum of the two components, and
        that total is billed at a single average tier rate — not marginally: a
        total of at most 20 gallons bills every gallon at 18,500 cents; 21
        through 60 gallons bills every gallon at 17,250 cents; beyond 60
        gallons every gallon bills at 16,000 cents."

        Design: Corner/calculations/material_tier_boundary_crossing
        """
        ctx = create_engagement()
        # Scheme A: 3500 sqft x 2 coats, no stripe -> ceil(7000/350) = 20 gal.
        create_and_approve_scheme(
            ctx["program"]["id"], ctx["customer"]["id"],
            drawing_ref="DWG-T20", painted_area_sqft=3500, coat_count=2, stripe_pct=0.0,
        )
        read_a = get_program(ctx["program"]["id"])
        assert read_a["material_estimate_gallons"] == 20, "tier1 boundary is inclusive"
        assert read_a["material_estimate_cost_cents"] == 20 * 18500

        # Scheme B supersedes A: 2400 sqft x 3 coats -> ceil(7200/350) = 21 gal.
        scheme_b = create_scheme(
            ctx["program"]["id"],
            drawing_ref="DWG-T21", painted_area_sqft=2400, coat_count=3, stripe_pct=0.0,
        )
        submit_scheme(scheme_b["id"])
        approve_scheme(
            scheme_b["id"], ctx["customer"]["id"],
            get_program(ctx["program"]["id"])["version"],
        )
        read_b = get_program(ctx["program"]["id"])
        assert read_b["material_estimate_gallons"] == 21
        assert read_b["material_estimate_cost_cents"] == 21 * 17250, (
            "every gallon repriced to tier2 — average-rate, not marginal"
        )


class TestAssessmentAmend:
    def test_amend_locked_outside_surface_review_and_self_loops_inside(self, api):
        """PRD §3.4: "While the program is in `SURFACE_REVIEW`, a `DECIDED`
        assessment may be amended — the same decision and severity fields are
        overwritten and the assessment's `revision` counter is bumped by one.
        Amending is a self-loop that keeps the assessment in `DECIDED`; it is
        refused with `ERR_ASSESSMENT_LOCKED` once the program has left
        `SURFACE_REVIEW`."

        Design: Corner/state_machines/assessment_amend_self_loop_and_lock
        """
        ctx = setup_inducted_program()
        assessment = create_assessment(ctx["program"]["id"])
        decide_assessment(assessment["id"], decision="STRIP", corrosion_severity="NONE")

        # Program is INDUCTED — not SURFACE_REVIEW — so amend is locked.
        locked = api.amend_surface_assessment(
            assessment["id"],
            decide_assessment_payload(decision="SCUFF", corrosion_severity="LIGHT"),
            _TECH,
        )
        validate_error(locked, ApiErrorId.ERR_ASSESSMENT_LOCKED)

        # Advance to SURFACE_REVIEW; the self-loop now applies.
        advance_program(ctx["program"]["id"], "SURFACE_REVIEW")
        amended = validate_success(
            api.amend_surface_assessment(
                assessment["id"],
                decide_assessment_payload(decision="SCUFF", corrosion_severity="LIGHT"),
                _TECH,
            )
        )
        assert amended["status"] == "DECIDED"
        assert amended["revision"] == 2, "amend bumps revision from 1 to 2"
        assert amended["decision"] == "SCUFF"


class TestHeavyCorrosionGate:
    def test_heavy_corrosion_requires_linked_discovery_item(self, api,
                                                            program_manager_headers):
        """PRD §3.4: "If the current assessment records `corrosion_severity` of
        `HEAVY`, the program may not advance from `SURFACE_REVIEW` to `IN_WORK`
        until at least one Discovery Item linked to that assessment exists;
        attempting the advance without one is rejected with
        `ERR_CORROSION_DISCOVERY_REQUIRED`."

        Design: Corner/validations/heavy_corrosion_requires_linked_discovery
        """
        ctx = setup_surface_review_program(decision="STRIP", corrosion_severity="HEAVY")
        ctx["booth"] = create_booth()
        book_booth_window(ctx["booth"]["id"], ctx["program"]["id"])

        blocked = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        validate_error(blocked, ApiErrorId.ERR_CORROSION_DISCOVERY_REQUIRED)

        create_discovery(
            ctx["program"]["id"],
            assessment_id=ctx["assessment"]["id"],
            description="Spar cap corrosion repair",
            safety_linked=True,
        )
        ok = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        assert validate_success(ok)["status"] == "IN_WORK"
