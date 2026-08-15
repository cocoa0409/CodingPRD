"""Drill aspect-ratio boundary precision at the approve gate (PRD §3.4).

The ceiling is inclusive and selected by copper weight: 8.0 at 1oz, 6.0 at 2oz.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_customer, create_order, create_and_lock_stackup,
    create_drill_program, submit_drill_program, approve_drill_program,
    make_process_engineer_headers,
    TEST_USERS,
)

PLANNER = TEST_USERS["production_planner_headers"]


def _order_with_locked_stackup(company, email, thickness, copper_weight_oz):
    cust = create_customer(company, email, 1_000_000)
    order = create_order(cust["id"], quantity_boards=10)
    create_and_lock_stackup(
        order["id"], total_thickness_mils=thickness, copper_weight_oz=copper_weight_oz,
    )
    return cust, order


def _program_under_review(order_id, min_hole_mils):
    program = create_drill_program(order_id, min_hole_mils=min_hole_mils,
                                   hole_count=400)
    submit_drill_program(program["id"])
    return program


class TestAspectRatioExactLimit:
    def test_one_oz_ratio_exactly_at_ceiling_passes_and_above_fails(self, api):
        """PRD §3.4: "it must not exceed the ceiling selected by the stackup's
        `copper_weight_oz`: 8.0 for one-ounce copper and 6.0 for two-ounce
        copper, with a ratio exactly at the ceiling passing. A breach is rejected
        with `ERR_ASPECT_RATIO_EXCEEDED`." PRD §2.7: "The drill aspect ratio is
        compared at the full floating-point precision of the division, with no
        rounding before the comparison."

        Design: Difficulty/boundary_precision_check/aspect_ratio_exact_limit
        """
        # 64 / 8 == 8.0 exactly: the inclusive ceiling passes.
        _, o1 = _order_with_locked_stackup("Lambda One", "o1@lambda.example", 64, 1)
        d1 = _program_under_review(o1["id"], 8)
        approved = approve_drill_program(d1["id"])
        assert approved["status"] == "APPROVED"
        assert approved["plated_aspect_ratio"] == 8.0, (
            f"64/8 lands exactly on the 1oz ceiling, got {approved['plated_aspect_ratio']}"
        )

        # 62 / 7 == 8.857... at full float precision: above the ceiling, rejected.
        _, o2 = _order_with_locked_stackup("Lambda Two", "o2@lambda.example", 62, 1)
        d2 = _program_under_review(o2["id"], 7)
        resp = api.approve_drill_program(d2["id"], make_process_engineer_headers("eng_1"))
        validate_error(resp, ApiErrorId.ERR_ASPECT_RATIO_EXCEEDED)

    def test_two_oz_ratio_exactly_at_ceiling_passes_and_above_fails(self, api):
        """PRD §3.4: "it must not exceed the ceiling selected by the stackup's
        `copper_weight_oz`: 8.0 for one-ounce copper and 6.0 for two-ounce
        copper, with a ratio exactly at the ceiling passing. A breach is rejected
        with `ERR_ASPECT_RATIO_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/aspect_ratio_exact_limit
        """
        # 60 / 10 == 6.0 exactly: the 2oz inclusive ceiling passes.
        _, o1 = _order_with_locked_stackup("TwoOz Pass", "pass@2oz.example", 60, 2)
        d1 = _program_under_review(o1["id"], 10)
        approved = approve_drill_program(d1["id"])
        assert approved["status"] == "APPROVED"
        assert approved["plated_aspect_ratio"] == 6.0, (
            f"60/10 lands exactly on the 2oz ceiling, got {approved['plated_aspect_ratio']}"
        )

        # 62 / 10 == 6.2: just above the 2oz ceiling, rejected.
        _, o2 = _order_with_locked_stackup("TwoOz Fail", "fail@2oz.example", 62, 2)
        d2 = _program_under_review(o2["id"], 10)
        resp = api.approve_drill_program(d2["id"], make_process_engineer_headers("eng_1"))
        validate_error(resp, ApiErrorId.ERR_ASPECT_RATIO_EXCEEDED)
