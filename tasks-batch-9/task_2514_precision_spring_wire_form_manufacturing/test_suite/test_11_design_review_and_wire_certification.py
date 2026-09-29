"""Design release-status transitions and the incoming-wire certification verdict.

A spring design walks `DRAFT → ENG_REVIEW` on its author's own submission and then
branches on the engineering manager's verdict: `APPROVE_PROTOTYPE` past the program's
fatigue-margin floor, or `REJECT` with no fatigue gate at all. Both branches stamp the
reviewer, both refuse a reviewer who authored the design, and neither edge exists once a
verdict has landed. `OBSOLETE` is the only terminal release status, and from there even a
revision presented with the design's freshly re-read version is refused.

A wire heat runs the mirror-image one-shot machine: certification is a single branching
verdict against the linked grade's tensile requirement, both outcomes are terminal, both
record the measured value and the tester, and neither moves a kilogram of the
three-bucket mass ledger.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_CHARACTERISTIC_SET_EMPTY,
    ERR_DESIGN_INVALID_STATE,
    ERR_FATIGUE_MARGIN_BELOW_FLOOR,
    ERR_SELF_REVIEW_FORBIDDEN,
    ERR_WIRE_LOT_ALREADY_DECIDED,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    DESIGN_ENGINEER_PRIMARY,
    ENGINEERING_MANAGER_ALT_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    ENGINEERING_MANAGER_PRIMARY,
    ENGINEERING_MANAGER_SECONDARY,
    QUALITY_INSPECTOR_HEADERS,
    make_headers,
)


def test_new_spring_design_opens_in_draft_with_no_reviewer(api: ApiClient) -> None:
    """PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the incoming
    `X-User-ID`, leaves `reviewed_by_user_id` null, sets `current_revision_no` to 1 with
    `superseded_revision_no` null, sets `release_status` to `DRAFT`, and then runs the
    complete engineering stack."

    Design: Corner/state_machines/design_initial_state_is_draft_on_creation
    """
    program = X.open_program(api)
    material = X.register_material(api)

    response = api.create_design(
        F.design_payload(program["id"], material["id"]), DESIGN_ENGINEER_HEADERS
    )
    design = validate_success(response, 201)

    assert design["release_status"] == C.RELEASE_DRAFT, (
        "the only edge into existence lands a design in DRAFT, got "
        f"{design['release_status']!r}"
    )
    assert design["reviewed_by_user_id"] is None, (
        "creation leaves reviewed_by_user_id null, got "
        f"{design['reviewed_by_user_id']!r}"
    )
    assert design["created_by_user_id"] == DESIGN_ENGINEER_PRIMARY, (
        "created_by_user_id is stamped from the incoming X-User-ID, got "
        f"{design['created_by_user_id']!r}"
    )
    assert design["current_revision_no"] == 1, (
        f"current_revision_no starts at 1, got {design['current_revision_no']!r}"
    )
    assert design["superseded_revision_no"] is None, (
        "superseded_revision_no starts null, got "
        f"{design['superseded_revision_no']!r}"
    )


def test_submit_for_review_advances_draft_to_eng_review(api: ApiClient) -> None:
    """PRD §3.3: "Submitting for review advances the design `DRAFT → ENG_REVIEW` and is
    the author's own act."
    PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the incoming
    `X-User-ID`, leaves `reviewed_by_user_id` null, sets `current_revision_no` to 1 with
    `superseded_revision_no` null, sets `release_status` to `DRAFT`, and then runs the
    complete engineering stack."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to
    the criterion in force, rounded half up to three decimal places."

    Design: Corner/state_machines/design_submit_for_review_moves_draft_to_eng_review
    """
    world = X.draft_design_world(api)
    drafted = world.design
    assert drafted["release_status"] == C.RELEASE_DRAFT, (
        f"the design must start in DRAFT, got {drafted['release_status']!r}"
    )

    expected_margin = A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, 2.5, 20.0, 150, 50, 1900, True
    )

    reviewed = validate_success(
        api.submit_design_for_review(world.design_id, DESIGN_ENGINEER_HEADERS)
    )

    assert reviewed["release_status"] == C.RELEASE_ENG_REVIEW, (
        "the submit edge moves DRAFT to ENG_REVIEW, got "
        f"{reviewed['release_status']!r}"
    )
    assert reviewed["fatigue_margin_ratio"] == expected_margin, (
        "submission touches no computed engineering field: fatigue_margin_ratio stays "
        f"{expected_margin}, got {reviewed['fatigue_margin_ratio']!r}"
    )
    assert reviewed["fatigue_margin_ratio"] == drafted["fatigue_margin_ratio"], (
        "the fatigue margin computed at creation is unchanged by the submission"
    )
    assert reviewed["current_revision_no"] == 1, (
        "submission is not a revision, so current_revision_no stays 1, got "
        f"{reviewed['current_revision_no']!r}"
    )
    assert reviewed["reviewed_by_user_id"] is None, (
        "no verdict has landed, so reviewed_by_user_id is still null, got "
        f"{reviewed['reviewed_by_user_id']!r}"
    )


def test_submit_for_review_without_any_characteristic_refused(api: ApiClient) -> None:
    """PRD §3.3: "It requires the design to be in `DRAFT`, otherwise
    `ERR_DESIGN_INVALID_STATE`, and it requires the design to have at least one critical
    characteristic on file: a design with an empty characteristic set cannot be reviewed,
    because there would be nothing to inspect, and the attempt answers
    `ERR_CHARACTERISTIC_SET_EMPTY` (HTTP 422)."

    Design: Corner/state_machines/design_submit_for_review_without_any_characteristic_rejected
    """
    world = X.build_world(api, "design")

    response = api.submit_design_for_review(world.design_id, DESIGN_ENGINEER_HEADERS)
    validate_error(response, ERR_CHARACTERISTIC_SET_EMPTY)

    after = X.refresh_design(api, world.design_id)
    assert after["release_status"] == C.RELEASE_DRAFT, (
        "a design with an empty statistical-process-control plan cannot enter review, "
        f"so it stays in DRAFT, got {after['release_status']!r}"
    )


def test_review_by_the_designs_own_author_refused(api: ApiClient) -> None:
    """PRD §3.3: "Both branches require the design to be in `ENG_REVIEW` — anything else
    answers `ERR_DESIGN_INVALID_STATE` — and both branches enforce segregation of duties:
    if the reviewer's `X-User-ID` equals the design's recorded `created_by_user_id`, the
    verdict is refused with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 409), whichever way the
    decision falls."
    PRD §3.3: "`APPROVE_PROTOTYPE` additionally requires the design's binding
    `fatigue_margin_ratio` to be at least the owning program's `min_fatigue_margin`; a
    shortfall is rejected with `ERR_FATIGUE_MARGIN_BELOW_FLOOR` (HTTP 422)."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to
    the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the incoming
    `X-User-ID`, leaves `reviewed_by_user_id` null, sets `current_revision_no` to 1 with
    `superseded_revision_no` null, sets `release_status` to `DRAFT`, and then runs the
    complete engineering stack."

    Design: Corner/state_machines/design_review_by_its_own_author_is_forbidden
    """
    world = X.draft_design_world(api)
    validate_success(api.submit_design_for_review(world.design_id, DESIGN_ENGINEER_HEADERS))

    in_review = X.refresh_design(api, world.design_id)
    expected_margin = A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, 2.5, 20.0, 150, 50, 1900, True
    )
    assert in_review["fatigue_margin_ratio"] == expected_margin, (
        "the fatigue gate must be clear so only segregation of duties can bite, got "
        f"{in_review['fatigue_margin_ratio']!r}"
    )
    assert expected_margin >= world.program["min_fatigue_margin"], (
        f"margin {expected_margin} must clear the program floor "
        f"{world.program['min_fatigue_margin']}"
    )

    # The same human wearing the engineering-manager hat: role changes, identifier does not.
    self_reviewer = make_headers(DESIGN_ENGINEER_PRIMARY, C.ROLE_ENGINEERING_MANAGER)
    response = api.review_design(
        world.design_id, {"decision": C.DECISION_APPROVE_PROTOTYPE}, self_reviewer
    )
    validate_error(response, ERR_SELF_REVIEW_FORBIDDEN)

    after = X.refresh_design(api, world.design_id)
    assert after["release_status"] == C.RELEASE_ENG_REVIEW, (
        "the refused verdict leaves the design in ENG_REVIEW, got "
        f"{after['release_status']!r}"
    )
    assert after["reviewed_by_user_id"] is None, (
        "no branch was taken, so reviewed_by_user_id is still null, got "
        f"{after['reviewed_by_user_id']!r}"
    )


def test_approve_prototype_below_program_fatigue_floor_refused(api: ApiClient) -> None:
    """PRD §3.3: "`APPROVE_PROTOTYPE` additionally requires the design's binding
    `fatigue_margin_ratio` to be at least the owning program's `min_fatigue_margin`; a
    shortfall is rejected with `ERR_FATIGUE_MARGIN_BELOW_FLOOR` (HTTP 422)."
    PRD §3.2: "The endurance limit in shear is the tensile grade multiplied by 0.30 when
    `shot_peening_required` is true and by 0.20 when it is false — shot peening buys half
    again as much fatigue strength, which is the whole reason the flag exists."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to
    the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "Otherwise a ratio of at least 1.150 yields five million."
    PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the incoming
    `X-User-ID`, leaves `reviewed_by_user_id` null, sets `current_revision_no` to 1 with
    `superseded_revision_no` null, sets `release_status` to `DRAFT`, and then runs the
    complete engineering stack."

    Design: Corner/state_machines/design_review_below_the_program_fatigue_floor_rejected
    """
    world = X.draft_design_world(
        api,
        design={
            "max_working_load_n": 180,
            "min_working_load_n": 60,
            "shot_peening_required": False,
        },
    )
    validate_success(api.submit_design_for_review(world.design_id, DESIGN_ENGINEER_HEADERS))

    expected_margin = A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, 2.5, 20.0, 180, 60, 1900, False
    )
    expected_life = A.expected_life_tier(expected_margin)
    assert expected_margin < world.program["min_fatigue_margin"], (
        f"the unpeened 180/60 N design must fall short of the "
        f"{world.program['min_fatigue_margin']} floor, got {expected_margin}"
    )

    response = api.review_design(
        world.design_id,
        {"decision": C.DECISION_APPROVE_PROTOTYPE},
        ENGINEERING_MANAGER_HEADERS,
    )
    validate_error(response, ERR_FATIGUE_MARGIN_BELOW_FLOOR)

    after = X.refresh_design(api, world.design_id)
    assert after["fatigue_margin_ratio"] == expected_margin, (
        f"the unpeened endurance limit gives a margin of {expected_margin}, got "
        f"{after['fatigue_margin_ratio']!r}"
    )
    assert after["predicted_fatigue_life_cycles"] == expected_life, (
        f"a margin of {expected_margin} lands the {expected_life}-cycle tier, got "
        f"{after['predicted_fatigue_life_cycles']!r}"
    )
    assert after["release_status"] == C.RELEASE_ENG_REVIEW, (
        "the refused approval leaves the design in ENG_REVIEW, got "
        f"{after['release_status']!r}"
    )
    assert after["reviewed_by_user_id"] is None, (
        "the refused approval stamps no reviewer, got "
        f"{after['reviewed_by_user_id']!r}"
    )


def test_reject_verdict_moves_eng_review_to_rejected_above_the_floor(
    api: ApiClient,
) -> None:
    """PRD §3.3: "`REJECT` has no fatigue gate at all — a manager may reject a design whose
    margin comfortably clears the program floor, for any reason the manager likes — and it
    moves the design `ENG_REVIEW → REJECTED`."
    PRD §3.3: "Both branches stamp `reviewed_by_user_id` with the reviewer's `X-User-ID`."
    PRD §3.1: "If no submission of the program is in either granted status, the posture is
    `BLOCKED`."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to
    the criterion in force, rounded half up to three decimal places."

    Design: Corner/state_machines/design_reject_verdict_moves_eng_review_to_rejected_above_the_floor
    """
    world = X.draft_design_world(api)
    validate_success(api.submit_design_for_review(world.design_id, DESIGN_ENGINEER_HEADERS))

    expected_margin = A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, 2.5, 20.0, 150, 50, 1900, True
    )
    assert expected_margin >= world.program["min_fatigue_margin"], (
        f"the margin {expected_margin} must clear the "
        f"{world.program['min_fatigue_margin']} floor, so only REJECT's own edge is "
        "under test"
    )

    rejected = validate_success(
        api.review_design(
            world.design_id,
            {"decision": C.DECISION_REJECT},
            ENGINEERING_MANAGER_ALT_HEADERS,
        )
    )

    assert rejected["release_status"] == C.RELEASE_REJECTED, (
        "REJECT moves ENG_REVIEW to REJECTED even above the fatigue floor, got "
        f"{rejected['release_status']!r}"
    )
    assert rejected["reviewed_by_user_id"] == ENGINEERING_MANAGER_SECONDARY, (
        "the reject branch stamps reviewed_by_user_id from the reviewer's X-User-ID, got "
        f"{rejected['reviewed_by_user_id']!r}"
    )
    assert rejected["fatigue_margin_ratio"] == expected_margin, (
        "the verdict recomputes nothing: the margin stays "
        f"{expected_margin}, got {rejected['fatigue_margin_ratio']!r}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "no submission of the program has ever been granted, so the posture stays "
        f"BLOCKED, got {program['delivery_posture']!r}"
    )


def test_second_review_after_a_verdict_refused(api: ApiClient) -> None:
    """PRD §3.3: "Both branches require the design to be in `ENG_REVIEW` — anything else
    answers `ERR_DESIGN_INVALID_STATE` — and both branches enforce segregation of duties:
    if the reviewer's `X-User-ID` equals the design's recorded `created_by_user_id`, the
    verdict is refused with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 409), whichever way the
    decision falls."
    PRD §3.3: "When it passes, the design moves `ENG_REVIEW → PROTOTYPE_RELEASED` and the
    program's `delivery_posture` is re-derived."
    PRD §3.3: "Both branches stamp `reviewed_by_user_id` with the reviewer's `X-User-ID`."

    Design: Corner/state_machines/design_second_review_after_a_verdict_rejected
    """
    world = X.draft_design_world(api)
    released = X.release_prototype(
        api,
        world.design_id,
        author=DESIGN_ENGINEER_HEADERS,
        reviewer=ENGINEERING_MANAGER_HEADERS,
    )
    assert released["release_status"] == C.RELEASE_PROTOTYPE, (
        "the first verdict must land PROTOTYPE_RELEASED, got "
        f"{released['release_status']!r}"
    )
    assert released["reviewed_by_user_id"] == ENGINEERING_MANAGER_PRIMARY, (
        "the first verdict stamps its own reviewer, got "
        f"{released['reviewed_by_user_id']!r}"
    )

    # A second, different manager replays the same verdict on a design that has left
    # ENG_REVIEW: the review edge is gone, so this is a state error rather than a no-op.
    response = api.review_design(
        world.design_id,
        {"decision": C.DECISION_APPROVE_PROTOTYPE},
        ENGINEERING_MANAGER_ALT_HEADERS,
    )
    validate_error(response, ERR_DESIGN_INVALID_STATE)

    after = X.refresh_design(api, world.design_id)
    assert after["release_status"] == C.RELEASE_PROTOTYPE, (
        "the replayed verdict changes nothing, got "
        f"{after['release_status']!r}"
    )
    assert after["reviewed_by_user_id"] == ENGINEERING_MANAGER_PRIMARY, (
        "the recorded reviewer is not overwritten by the refused second verdict, got "
        f"{after['reviewed_by_user_id']!r}"
    )


def test_revision_of_an_obsolete_design_refused(api: ApiClient) -> None:
    """PRD §3.3: "Only `OBSOLETE` is terminal."
    PRD §3.3: "On success the design moves to `OBSOLETE`; every tooling asset of the design
    whose `amortization_status` is `PENDING` or `AMORTIZING` transitions to `WRITTEN_OFF`,
    with `unamortized_cents` and `recovered_cents` left exactly as they stood — a write-off
    records the loss, it does not zero the ledger; every machine setup of the design still
    in `SCHEDULED` transitions to `ABORTED`; and the owning program's `delivery_posture` is
    re-derived, which lands on `BLOCKED`."
    PRD §3.3: "The design's `release_status` must be one of `DRAFT`, `ENG_REVIEW`,
    `REJECTED` or `PROTOTYPE_RELEASED`; an `OBSOLETE` or `PRODUCTION_RELEASED` design
    cannot be revised and answers `ERR_DESIGN_INVALID_STATE`."
    PRD §2.8: "On the revision operation, rank 20 outranks rank 21: an `OBSOLETE` design
    answers `ERR_DESIGN_INVALID_STATE`, while a design still in a revisable state that
    carries an in-flight or granted approval package answers `ERR_DESIGN_LOCKED`."
    PRD §3.3: "An accepted revision does the following bookkeeping:
    `superseded_revision_no` is set to the value `current_revision_no` held before the
    revision, `current_revision_no` is increased by 1, `release_status` returns to `DRAFT`,
    `reviewed_by_user_id` is cleared to null, and `created_by_user_id` is re-stamped with
    the revising engineer's `X-User-ID` — so the segregation-of-duties gate on the next
    review is measured against whoever cut the latest revision."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear modulus
    multiplied by the wire diameter raised to the fourth power, divided by the product of
    eight, the mean coil diameter cubed, and the active coil count, with the result rounded
    half up to three decimal places."

    Design: Corner/state_machines/design_obsolete_is_terminal_and_blocks_further_revisions
    """
    world = X.build_world(api, "prototype")

    retired = validate_success(
        api.obsolete_design(world.design_id, ENGINEERING_MANAGER_HEADERS)
    )
    assert retired["release_status"] == C.RELEASE_OBSOLETE, (
        f"retirement must land OBSOLETE, got {retired['release_status']!r}"
    )

    # Re-read the row so the optimistic-concurrency guard is satisfied and only the
    # from-state rule can decide the answer.
    fresh = X.refresh_design(api, world.design_id)
    expected_rate = A.expected_spring_rate(79.3, 2.5, 20.0, 8)

    response = api.revise_design(
        world.design_id,
        F.revision_payload(fresh["version"], active_coils=10),
        DESIGN_ENGINEER_HEADERS,
    )
    validate_error(response, ERR_DESIGN_INVALID_STATE)

    after = X.refresh_design(api, world.design_id)
    assert after["release_status"] == C.RELEASE_OBSOLETE, (
        "no trigger applies from the terminal status, so the design stays OBSOLETE, got "
        f"{after['release_status']!r}"
    )
    assert after["current_revision_no"] == 1, (
        "the refused revision does not advance current_revision_no, got "
        f"{after['current_revision_no']!r}"
    )
    assert after["superseded_revision_no"] is None, (
        "the refused revision sets no superseded_revision_no, got "
        f"{after['superseded_revision_no']!r}"
    )
    assert after["active_coils"] == 8, (
        "the offered geometry is not applied, so active_coils stays 8, got "
        f"{after['active_coils']!r}"
    )
    assert after["spring_rate_n_per_mm"] == expected_rate, (
        "no computed engineering field is recalculated, so the spring rate stays "
        f"{expected_rate}, got {after['spring_rate_n_per_mm']!r}"
    )


def test_certify_below_the_grade_branches_the_heat_to_rejected(api: ApiClient) -> None:
    """PRD §3.5: "The outcomes differ only in the comparison against the grade: when the
    measured value is at least the linked material specification's `tensile_grade_mpa`, the
    lot moves `UNCERTIFIED → CERTIFIED`; when the measured value falls below that grade,
    the lot moves `UNCERTIFIED → REJECTED` and no run may ever draw from it."
    PRD §3.5: "Both outcomes record the supplied `tensile_test_mpa` on the lot and stamp
    `certified_by_user_id` with the inspector's `X-User-ID`."
    PRD §3.5: "At receipt the three buckets are opened with all mass free: `on_hand_kg`
    equals `received_kg`, while `reserved_kg` and `consumed_kg` both start at 0.000."
    PRD §3.5: "That figure is the conserved quantity of the wire ledger and never changes
    afterwards."

    Design: Corner/state_machines/wire_lot_certify_below_the_grade_branches_to_rejected
    """
    material = X.register_material(api)
    lot = X.receive_wire(api, material["id"])
    assert lot["certification_status"] == C.CERT_UNCERTIFIED, (
        f"a received heat opens UNCERTIFIED, got {lot['certification_status']!r}"
    )

    # A 1850 MPa result against the 1900 MPa grade: the losing side of the one comparison
    # that decides the branch.
    tester = make_headers("qi-05", C.ROLE_QUALITY_INSPECTOR)
    decided = validate_success(
        api.certify_wire_lot(
            lot["id"], F.certify_payload(tensile_test_mpa=1850), tester
        )
    )

    assert decided["certification_status"] == C.CERT_REJECTED, (
        "a measured value below the grade branches the heat to REJECTED, got "
        f"{decided['certification_status']!r}"
    )
    assert decided["tensile_test_mpa"] == 1850, (
        "the rejecting outcome still records the supplied tensile_test_mpa, got "
        f"{decided['tensile_test_mpa']!r}"
    )
    assert decided["certified_by_user_id"] == "qi-05", (
        "the rejecting outcome still stamps the tester's X-User-ID, got "
        f"{decided['certified_by_user_id']!r}"
    )
    assert decided["received_kg"] == 800.0, (
        f"received_kg is the conserved quantity, got {decided['received_kg']!r}"
    )
    assert decided["on_hand_kg"] == 800.0, (
        "the verdict moves no mass, so all 800.000 kg stay on hand, got "
        f"{decided['on_hand_kg']!r}"
    )
    assert decided["reserved_kg"] == 0, (
        f"the verdict reserves nothing, got {decided['reserved_kg']!r}"
    )
    assert decided["consumed_kg"] == 0, (
        f"the verdict consumes nothing, got {decided['consumed_kg']!r}"
    )
    A.assert_wire_ledger_conserved(decided)


def test_second_certify_attempt_on_a_decided_heat_refused(api: ApiClient) -> None:
    """PRD §3.5: "The lot's `certification_status` must still be `UNCERTIFIED`; presenting a
    lot that has already been decided answers `ERR_WIRE_LOT_ALREADY_DECIDED` (HTTP 409),
    and because both outcomes are terminal a heat can never be re-tested."
    PRD §3.5: "The outcomes differ only in the comparison against the grade: when the
    measured value is at least the linked material specification's `tensile_grade_mpa`, the
    lot moves `UNCERTIFIED → CERTIFIED`; when the measured value falls below that grade,
    the lot moves `UNCERTIFIED → REJECTED` and no run may ever draw from it."
    PRD §3.5: "Both outcomes record the supplied `tensile_test_mpa` on the lot and stamp
    `certified_by_user_id` with the inspector's `X-User-ID`."

    Design: Corner/state_machines/wire_lot_second_certify_attempt_rejected
    """
    material = X.register_material(api)
    lot = X.receive_wire(api, material["id"])
    certified = validate_success(
        api.certify_wire_lot(
            lot["id"], F.certify_payload(tensile_test_mpa=1930), QUALITY_INSPECTOR_HEADERS
        )
    )
    assert certified["certification_status"] == C.CERT_CERTIFIED, (
        "1930 MPa clears the 1900 MPa grade, got "
        f"{certified['certification_status']!r}"
    )

    # A re-test that would have flipped the verdict, had the machine allowed one.
    response = api.certify_wire_lot(
        lot["id"], F.certify_payload(tensile_test_mpa=1500), QUALITY_INSPECTOR_HEADERS
    )
    validate_error(response, ERR_WIRE_LOT_ALREADY_DECIDED)

    after = X.refresh_wire_lot(api, lot["id"])
    assert after["certification_status"] == C.CERT_CERTIFIED, (
        "both outcomes are terminal, so the decided heat stays CERTIFIED, got "
        f"{after['certification_status']!r}"
    )
    assert after["tensile_test_mpa"] == 1930, (
        "the refused re-test does not overwrite the recorded tensile value, got "
        f"{after['tensile_test_mpa']!r}"
    )
