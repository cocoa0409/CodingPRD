"""Lifecycles that do not simply advance.

A design can walk backwards from review into DRAFT and round the loop again, and
an order carries two dimensions that move on different triggers — one set
directly, one derived from the plant floor.
"""

from test_helpers import (
    ENGINEERING_MANAGER_USER_ID,
    ENGINEER_TWO_USER_ID,
    ENGINEER_USER_ID,
    STANDARD_KITS,
    append_components,
    assert_order_dimensions,
    assert_weight,
    chain_accepted_order,
    chain_locked_configuration,
    complete_lot,
    create_design,
    create_drawing_package,
    create_production_line,
    get_configuration,
    get_design,
    get_order,
    member_component_payload,
    minimal_bom,
    release_order,
    review_design,
    revise_design,
    schedule_lot,
    seal_drawing_package,
    submit_design,
)


def _design_with_one_column():
    """A DRAFT ASD design carrying a single primary frame member."""
    chain = chain_locked_configuration()
    configuration = chain["configuration"]
    design = create_design(configuration["id"], configuration["version"])
    append_components(design["id"], [member_component_payload()])
    return design


def _order_with_a_drafted_design_and_three_lines():
    """An accepted order, a detailed but unsubmitted design, and one line per type."""
    chain = chain_accepted_order(kits=STANDARD_KITS)
    configuration = get_configuration(chain["configuration"]["id"])
    design = create_design(configuration["id"], configuration["version"])
    append_components(design["id"], minimal_bom())
    chain["design"] = design
    chain["lines"] = {
        "PL-1": create_production_line(
            code="PL-1",
            name="Plate Line 1",
            line_type="PLATE_CUT_WELD",
            changeover_buffer_minutes=120,
        ),
        "PL-2": create_production_line(
            code="PL-2",
            name="Roll Former 1",
            line_type="ROLL_FORM",
            changeover_buffer_minutes=120,
        ),
        "PL-3": create_production_line(
            code="PL-3",
            name="Panel Line 1",
            line_type="PANEL_ROLL",
            changeover_buffer_minutes=120,
        ),
    }
    return chain


def test_01_a_requested_revision_walks_the_design_back_to_draft():
    """REQUEST_REVISION then revise returns the design to DRAFT and counts one.

    PRD §3.6: "On ``REQUEST_REVISION``, the design's ``status`` becomes
    ``REVISION_REQUIRED``."

    PRD §3.6: "An ``Engineer`` returns a ``REVISION_REQUIRED`` design to
    ``DRAFT``."

    PRD §3.6: "On success ``revision_count`` increases by 1, both
    ``submitted_by_user_id`` and ``reviewed_by_user_id`` are cleared back to null
    so the segregation-of-duties check starts fresh on the next round, ``status``
    becomes ``DRAFT``, and ``version`` increments."

    Design: Difficulty/non_linear_state_machine/engineering_design_revision_cycle_returns_to_draft
    """
    design = _design_with_one_column()

    submitted = submit_design(design["id"], user_id=ENGINEER_USER_ID)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_count"] == 0

    reviewed = review_design(
        design["id"], "REQUEST_REVISION", user_id=ENGINEERING_MANAGER_USER_ID
    )
    assert reviewed["status"] == "REVISION_REQUIRED"

    revised = revise_design(design["id"])
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1


def test_02_revising_clears_both_authorship_fields():
    """The submitting and reviewing identities are wiped on the way back to DRAFT.

    PRD §3.6: "On success ``submitted_by_user_id`` records the acting
    ``X-User-ID``, ``status`` becomes ``SUBMITTED``, and ``version``
    increments."

    PRD §3.6: "Both branches set ``reviewed_by_user_id`` to the reviewing
    ``X-User-ID`` and increment the design's ``version``, but their downstream
    effects diverge and each branch is spelled out in full."

    PRD §3.6: "On success ``revision_count`` increases by 1, both
    ``submitted_by_user_id`` and ``reviewed_by_user_id`` are cleared back to null
    so the segregation-of-duties check starts fresh on the next round, ``status``
    becomes ``DRAFT``, and ``version`` increments."

    Design: Difficulty/non_linear_state_machine/engineering_design_revision_cycle_returns_to_draft
    """
    design = _design_with_one_column()

    submitted = submit_design(design["id"], user_id=ENGINEER_USER_ID)
    assert submitted["submitted_by_user_id"] == ENGINEER_USER_ID
    reviewed = review_design(
        design["id"], "REQUEST_REVISION", user_id=ENGINEERING_MANAGER_USER_ID
    )
    assert reviewed["reviewed_by_user_id"] == ENGINEERING_MANAGER_USER_ID

    revise_design(design["id"])

    after = get_design(design["id"])
    assert after["submitted_by_user_id"] is None
    assert after["reviewed_by_user_id"] is None


def test_03_from_draft_the_engineer_may_detail_further_and_resubmit():
    """The second lap through the loop appends steel and lands on APPROVED.

    PRD §3.6: "From ``DRAFT`` the engineer may append further components and
    submit again."

    PRD §3.6: "An ``Engineer`` appends components to a design one at a time, and
    only while the design is ``DRAFT`` — appending to a design in any other state
    yields ``ERR_INVALID_STATE_TRANSITION``."

    PRD §3.6: "On ``APPROVE``, the design's ``status`` becomes ``APPROVED``."

    Design: Difficulty/non_linear_state_machine/engineering_design_revision_cycle_returns_to_draft
    """
    design = _design_with_one_column()
    submit_design(design["id"], user_id=ENGINEER_USER_ID)
    review_design(design["id"], "REQUEST_REVISION", user_id=ENGINEERING_MANAGER_USER_ID)
    revise_design(design["id"])

    append_components(
        design["id"],
        [
            member_component_payload(
                mark="R-1", member_type="RAFTER", quantity=10,
                length_ft=51.25, weight_per_ft=48.7,
            )
        ],
    )
    resubmitted = submit_design(design["id"], user_id=ENGINEER_TWO_USER_ID)
    assert resubmitted["submitted_by_user_id"] == ENGINEER_TWO_USER_ID

    approved = review_design(
        design["id"], "APPROVE", user_id=ENGINEERING_MANAGER_USER_ID
    )
    assert approved["status"] == "APPROVED"
    assert approved["revision_count"] == 1
    assert approved["component_count"] == 2
    # 15275.80 + 24958.80.
    assert_weight(approved["frame_weight_lbs"], 40234.60)


def test_04_design_approval_moves_only_the_engineering_dimension():
    """Approval reaches the order through the configuration and leaves production alone.

    PRD §2.11: "A design approval moves only the engineering dimension and
    leaves the production dimension untouched; a release to fabrication moves
    only the production dimension and leaves ``engineering_status`` at
    ``ENG_SEALED``."

    PRD §3.6: "Every order whose ``configuration_id`` equals the design's
    ``configuration_id``, whose ``production_status`` is not ``PROD_COMPLETE``,
    and whose ``engineering_status`` is ``ENG_PENDING`` or ``ENG_REWORK`` has its
    ``engineering_design_id`` set to this design and its ``engineering_status``
    moved to ``ENG_APPROVED``; each such order's ``version`` increments."

    PRD §3.6: "The order's ``production_status`` is untouched by approval."

    Design: Difficulty/non_linear_state_machine/order_parallel_engineering_and_production_dimensions
    """
    chain = _order_with_a_drafted_design_and_three_lines()
    order_id = chain["order"]["id"]
    assert_order_dimensions(
        chain["order"], "ENG_PENDING", "PROD_NOT_RELEASED",
        permit_hold=False, commercial_hold=False,
    )

    submit_design(chain["design"]["id"], user_id=ENGINEER_USER_ID)
    review_design(chain["design"]["id"], "APPROVE", user_id=ENGINEERING_MANAGER_USER_ID)

    after_approval = get_order(order_id)
    assert_order_dimensions(
        after_approval, "ENG_APPROVED", "PROD_NOT_RELEASED",
        permit_hold=False, commercial_hold=False,
    )
    assert after_approval["engineering_design_id"] == chain["design"]["id"]


def test_05_sealing_advances_engineering_and_release_advances_production():
    """The two dimensions take turns: ENG_SEALED first, then PROD_RELEASED.

    PRD §3.7: "It also reaches into the order stream: every order whose
    ``engineering_status`` is ``ENG_APPROVED`` and whose
    ``engineering_design_id`` equals this package's ``design_id`` has its
    ``drawing_package_id`` set to this package and its ``engineering_status``
    moved to ``ENG_SEALED``."

    PRD §3.8: "And it stamps ``released_at`` with the current logical clock and
    sets ``production_status`` to ``PROD_RELEASED``, leaving
    ``engineering_status`` at ``ENG_SEALED``."

    Design: Difficulty/non_linear_state_machine/order_parallel_engineering_and_production_dimensions
    """
    chain = _order_with_a_drafted_design_and_three_lines()
    order_id = chain["order"]["id"]

    submit_design(chain["design"]["id"], user_id=ENGINEER_USER_ID)
    review_design(chain["design"]["id"], "APPROVE", user_id=ENGINEERING_MANAGER_USER_ID)
    package = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"], sheet_count=24
    )
    seal_drawing_package(package["id"])

    after_seal = get_order(order_id)
    assert_order_dimensions(after_seal, "ENG_SEALED", "PROD_NOT_RELEASED")
    assert after_seal["drawing_package_id"] == package["id"]

    released = release_order(order_id, after_seal["version"])
    assert_order_dimensions(
        released, "ENG_SEALED", "PROD_RELEASED",
        permit_hold=False, commercial_hold=False,
    )


def test_06_production_status_is_derived_from_the_active_lot_population():
    """PROD_COMPLETE arrives only once all three required lot types are complete.

    PRD §2.11: "``production_status``, by contrast, is **derived** — it is
    recomputed from the order's own release state, its hold flags, and the
    current population of its production lots, using the projection in §3.8."

    PRD §3.8: "If there are no active lots at all, the result is
    ``PROD_RELEASED``."

    PRD §3.8: "If every active lot is ``COMPLETE`` **and** the set of
    ``lot_type`` values across those lots is exactly the three required types
    ``PRIMARY_FRAME_FAB``, ``SECONDARY_ROLL_FORM`` and ``PANEL_RUN``, the result
    is ``PROD_COMPLETE``."

    PRD §3.8: "In every other case the result is ``PROD_IN_FABRICATION`` — which
    covers both a lot still ``SCHEDULED`` and the case where all lots are
    complete but one of the three required fabrication steps was never
    scheduled."

    Design: Difficulty/non_linear_state_machine/order_parallel_engineering_and_production_dimensions
    """
    chain = _order_with_a_drafted_design_and_three_lines()
    order_id = chain["order"]["id"]
    submit_design(chain["design"]["id"], user_id=ENGINEER_USER_ID)
    review_design(chain["design"]["id"], "APPROVE", user_id=ENGINEERING_MANAGER_USER_ID)
    package = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"], sheet_count=24
    )
    seal_drawing_package(package["id"])
    release_order(order_id, get_order(order_id)["version"])

    frame_lot = schedule_lot(
        order_id, chain["lines"]["PL-1"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
    )
    secondary_lot = schedule_lot(
        order_id, chain["lines"]["PL-2"]["id"],
        lot_type="SECONDARY_ROLL_FORM", paint_color="GALVALUME",
        window_start="2026-08-11T08:00:00Z", window_end="2026-08-11T12:00:00Z",
    )
    panel_lot = schedule_lot(
        order_id, chain["lines"]["PL-3"]["id"],
        lot_type="PANEL_RUN", paint_color="POLAR_WHITE",
        window_start="2026-08-12T08:00:00Z", window_end="2026-08-12T12:00:00Z",
    )
    assert_order_dimensions(get_order(order_id), "ENG_SEALED", "PROD_IN_FABRICATION")

    complete_lot(frame_lot["id"])
    complete_lot(secondary_lot["id"])
    # Two of the three required fabrication steps are finished, so the order is
    # still in fabrication.
    assert_order_dimensions(get_order(order_id), "ENG_SEALED", "PROD_IN_FABRICATION")

    complete_lot(panel_lot["id"])
    final = get_order(order_id)
    assert_order_dimensions(
        final, "ENG_SEALED", "PROD_COMPLETE",
        permit_hold=False, commercial_hold=False,
    )
