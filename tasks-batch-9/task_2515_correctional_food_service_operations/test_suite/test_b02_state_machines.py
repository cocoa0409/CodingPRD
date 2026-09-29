"""State machines: opening states, declared edges, guards, joins and cascades.

Every entity in this domain is a small machine. These cases walk the declared
edges — the opening state of a grievance and of a kitchen worker, the side
effects a tool return is required to apply, the guards that refuse an undeclared
transition, the fork-join of a grievance, and the cascades that a single edge
fires across other aggregates.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Opening states
# ---------------------------------------------------------------------------


def _facility_with_one_inmate(
    api: ApiClient,
    contract_code: str,
    facility_code: str,
    booking_number: str,
    **inmate_overrides: object,
) -> dict:
    """A registered kitchen with one booked inmate. The contract is left in
    DRAFT: nothing in this fixture is gated on contract status."""
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code=contract_code)
    facility = fixtures.create_facility(
        api,
        contract["id"],
        facility_code=facility_code,
        sharps_authorized_count=12,
    )
    inmate = fixtures.create_inmate(
        api, facility["id"], booking_number=booking_number, **inmate_overrides
    )
    return {"contract": contract, "facility": facility, "inmate": inmate}


def test_a_freshly_filed_grievance_waits_in_filed_with_every_flag_false(
    api: ApiClient,
) -> None:
    """Filing does not route: the branch flags, the remedy and the response stamps
    all stay empty, and a portion-size complaint takes the ten-day window.

    The PRD states: "A filed grievance opens in `FILED` with `routed_branch` null,
    `investigation_complete` false, `diet_review_complete` false,
    `diet_remedy_required` false, `remedy` null, `refeed_tray_count` 0, `response_at`
    null, `responded_by_user_id` null and `sla_breached` false." On the deadline it
    states: "The window is 5 days when the `category` is `RELIGIOUS_DIET_DENIAL` or
    `DIET_NOT_HONORED` ... and 10 days for every other category. `response_due_at` is
    `filed_at` plus that many days, each day being exactly 24 hours."

    Design: Corner/state_machines/corner_grievance_starts_in_filed_with_all_branch_flags_false
    """
    ctx = _facility_with_one_inmate(api, "CFS-2515-S01", "FAC-S01", "BK-S01")

    grievance = fixtures.filed_grievance(
        api,
        ctx["inmate"]["id"],
        ctx["facility"]["id"],
        category="PORTION_SIZE",
        narrative="Short-served on the noon line.",
    )

    assertions.assert_grievance(grievance)
    assertions.assert_grievance_filed_defaults(grievance)
    assertions.assert_instant(grievance["filed_at"], "2026-08-01T00:00:00Z")
    assertions.assert_instant(grievance["response_due_at"], "2026-08-11T00:00:00Z")
    assert grievance["category"] == "PORTION_SIZE"
    assert grievance["version"] == 1


def test_assigning_a_cleared_worker_moves_only_the_operational_axis(
    api: ApiClient,
) -> None:
    """The assignment axis moves to ASSIGNED and records the work area while the
    security axis is left exactly where enrolment put it.

    The PRD states: "A new worker opens with `clearance_status` `CLEARED`,
    `assignment_status` `UNASSIGNED`, `work_area` null and `contraband_strike_count`
    0." On the edge itself: "Assigning a worker to a `work_area` is a supervisor
    action that moves `assignment_status` to `ASSIGNED`, writes the requested area and
    increments `version` by 1." The two axes are declared independent: "`clearance_status`
    is the security verdict ... and `assignment_status` is the operational one".

    Design: Corner/state_machines/corner_inmate_worker_assign_moves_to_assigned_with_work_area
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-S02")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-S02", sharps_authorized_count=12
    )
    enrolment = fixtures.enrolled_worker(
        api,
        facility["id"],
        booking_number="BK-S02",
        sharps_eligible=False,
    )
    worker = enrolment["worker"]
    assertions.assert_worker_enrollment_defaults(worker)
    assert worker["version"] == 1

    assigned = validate_success(
        api.assign_inmate_worker(
            worker["id"], factories.assign_payload("BAKERY"), users.FOOD_SUPERVISOR
        )
    )

    assertions.assert_inmate_worker(assigned)
    assert assigned["assignment_status"] == "ASSIGNED"
    assert assigned["work_area"] == "BAKERY"
    assert assigned["clearance_status"] == "CLEARED"
    assert assigned["contraband_strike_count"] == 0
    assert assigned["sharps_eligible"] is False
    assert assigned["version"] == 2


# ---------------------------------------------------------------------------
# Preconditions on a declared edge
# ---------------------------------------------------------------------------


def test_signing_an_incomplete_menu_cycle_is_refused_and_attests_nothing(
    api: ApiClient,
) -> None:
    """A one-day cycle carrying two components is short of the three it owes, so the
    attestation never happens and no approved figure is written.

    The PRD states: "Before anything is attested, the cycle must be **complete**:
    `item_count` must equal `cycle_length_days` multiplied by the three meal slots
    served each day, so a 7-day cycle needs exactly 21 components and a 3-day cycle
    exactly 9. A cycle that is short or over-stuffed is rejected with
    `ERR_MENU_CYCLE_INCOMPLETE`." On a successful sign, by contrast, "all four
    `approved_*` figures are written, `nutrition_signed_by_user_id` records the signing
    `X-User-ID`".

    Design: Corner/state_machines/corner_nutrition_sign_rejects_incomplete_menu_cycle
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-S03"},
        facility_overrides={
            "facility_code": "FAC-S03",
            "sharps_authorized_count": 12,
        },
    )
    cycle = validate_success(
        api.create_menu_cycle(
            factories.menu_cycle_payload(
                ctx["facility"]["id"], cycle_code="CYC-S03", cycle_length_days=1
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    for builder in (factories.breakfast_item_payload, factories.lunch_item_payload):
        validate_success(
            api.add_menu_cycle_item(cycle["id"], builder(), users.FOOD_SUPERVISOR), 201
        )

    validate_error(
        api.nutrition_sign_menu_cycle(cycle["id"], users.DIETITIAN),
        ApiErrorId.ERR_MENU_CYCLE_INCOMPLETE.value,
        409,
    )

    unsigned = validate_success(api.get_menu_cycle(cycle["id"], users.FOOD_SUPERVISOR))
    assert unsigned["status"] == "DRAFT"
    assert unsigned["item_count"] == 2
    for field in (
        "approved_kcal_per_meal_day",
        "approved_protein_grams_per_meal_day",
        "approved_sodium_mg_per_meal_day",
        "approved_cost_cents_per_meal_day",
    ):
        assert unsigned[field] is None, field
    assert unsigned["nutrition_signed_by_user_id"] is None
    assert unsigned["activated_by_user_id"] is None


def test_an_ordinary_return_restores_the_board_without_flagging_a_recovery(
    api: ApiClient,
) -> None:
    """The ISSUED to RETURNED edge stamps the certification, walks the sharp back onto
    the board and recomputes the posture, and leaves `recovered` false.

    The PRD states: "A return moves `status` to `RETURNED`, stamps `returned_at`,
    records `return_certified_by_user_id` and increments `version` by 1. It then
    restores the facility counters so that the conservation identity holds again — for
    a sharp class the issued or unaccounted counter falls by 1 and
    `sharps_on_board_count` rises by 1 — recomputes `kitchen_posture` and increments
    the facility's `version` by 1." Only the compensating edge out of `UNACCOUNTED`
    "additionally sets `recovered` to true, which is how a recovered tool is
    distinguished from one that never went missing."

    Design: Corner/state_machines/corner_tool_return_applies_every_declared_side_effect
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-S04")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-S04", sharps_authorized_count=12
    )
    enrolment = fixtures.enrolled_worker(
        api, facility["id"], booking_number="BK-S04", sharps_eligible=True
    )
    issuance = fixtures.issued_tool(
        api,
        facility["id"],
        enrolment["worker"]["id"],
        tool_class="SHARP_KNIFE",
        tool_serial="SK-S04-1",
        shadow_board_slot=3,
    )
    assert issuance["issued_by_user_id"] == users.user_id_of(users.FOOD_SUPERVISOR)

    after_issue = validate_success(
        api.get_sharps_summary(facility["id"], users.OFFICER)
    )
    assertions.assert_sharps_summary_conservation(after_issue)
    assert after_issue["sharps_on_board_count"] == 11
    assert after_issue["sharps_issued_count"] == 1

    returned = validate_success(
        api.return_tool_issuance(
            issuance["id"], factories.tool_return_payload(1), users.OFFICER_2
        )
    )

    assertions.assert_tool_issuance(returned)
    assert returned["status"] == "RETURNED"
    assertions.assert_instant(returned["returned_at"], "2026-08-01T00:00:00Z")
    assert returned["return_certified_by_user_id"] == users.user_id_of(users.OFFICER_2)
    assert returned["recovered"] is False
    assert returned["version"] == 2

    after_return = validate_success(
        api.get_sharps_summary(facility["id"], users.OFFICER_2)
    )
    assertions.assert_sharps_summary_conservation(after_return)
    assert after_return["sharps_on_board_count"] == 12
    assert after_return["sharps_issued_count"] == 0
    assert after_return["sharps_unaccounted_count"] == 0
    assert after_return["kitchen_posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Undeclared edges and terminal states
# ---------------------------------------------------------------------------


def test_completing_a_branch_before_routing_is_not_a_declared_edge(
    api: ApiClient,
) -> None:
    """`FILED` has exactly one outbound edge — routing — so completing a branch from
    there is refused and the grievance is left untouched.

    The PRD states: "Completing a branch is legal only from `UNDER_INVESTIGATION`,
    `DIET_REVIEW` or `DUAL_TRACK`", and that a request "made from a legal state but
    whose declared origin does not match the entity's current state is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_complete_branch_from_filed_is_not_a_declared_transition
    """
    ctx = _facility_with_one_inmate(api, "CFS-2515-S05", "FAC-S05", "BK-S05")
    grievance = fixtures.filed_grievance(
        api, ctx["inmate"]["id"], ctx["facility"]["id"], category="PORTION_SIZE"
    )
    assert grievance["status"] == "FILED"

    validate_error(
        api.complete_grievance_branch(
            grievance["id"],
            factories.complete_branch_payload("INVESTIGATION"),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    unchanged = fixtures.read_grievance(api, grievance["id"])
    assert unchanged["status"] == "FILED"
    assert unchanged["investigation_complete"] is False
    assert unchanged["diet_review_complete"] is False
    assert unchanged["routed_branch"] is None
    assert unchanged["version"] == grievance["version"]


def test_verifying_an_order_that_is_already_active_is_refused_once(
    api: ApiClient,
) -> None:
    """Verification is an edge out of PENDING_VERIFICATION only: the second attempt is
    refused and neither census counter is incremented a second time.

    The PRD states: "Verification is available only from `PENDING_VERIFICATION`." On
    the first verification: "Activation increments the inmate's
    `active_diet_order_count` by 1 and the facility's `active_special_diet_count` by 1."

    Design: Corner/state_machines/corner_second_verify_on_active_diet_order_rejected
    """
    ctx = _facility_with_one_inmate(
        api,
        "CFS-2515-S06",
        "FAC-S06",
        "BK-S06",
        religious_affiliation="JEWISH",
    )
    order = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                ctx["inmate"]["id"], ctx["inmate"]["version"]
            ),
            users.DIETITIAN,
        ),
        201,
    )
    active = validate_success(api.verify_diet_order(order["id"], users.CHAPLAIN))
    assert active["status"] == "ACTIVE"
    assert active["version"] == 2
    assert fixtures.read_facility(api, ctx["facility"]["id"])[
        "active_special_diet_count"
    ] == 1

    validate_error(
        api.verify_diet_order(order["id"], users.CHAPLAIN),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    still_active = fixtures.read_diet_order(api, order["id"])
    assert still_active["status"] == "ACTIVE"
    assert still_active["version"] == 2
    assertions.assert_instant(still_active["verified_at"], "2026-08-01T00:00:00Z")
    inmate = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    assert inmate["active_diet_order_count"] == 1
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["active_special_diet_count"] == 1


def test_a_dual_track_grievance_joins_only_after_the_second_branch_closes(
    api: ApiClient,
) -> None:
    """Both branches are opened by one routing decision, the fork holds while one is
    still open, and the diet branch's fault finding raises the remedy flag on the join.

    The PRD states: "`DUAL_TRACK` runs both branches at once, and while a grievance is
    in `DUAL_TRACK` its `routed_branch` reads `BOTH`." On the join: "A grievance in
    `DUAL_TRACK` needs both `investigation_complete` and `diet_review_complete` before
    it may move to `READY_FOR_RESPONSE`; a response attempted while either flag is
    still false is `ERR_BRANCHES_INCOMPLETE`." On the finding: "A `KITCHEN_AT_FAULT`
    finding on the `DIET_REVIEW` branch also sets `diet_remedy_required` to true."
    `DIET_NOT_HONORED` takes the expedited five-day window.

    Design: Corner/state_machines/corner_grievance_dual_track_join_requires_both_branches
    """
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-S08"},
        facility_overrides={
            "facility_code": "FAC-S08",
            "sharps_authorized_count": 12,
        },
        forecast_overrides={"service_date": "2026-08-01", "meal_slot": "LUNCH"},
    )
    ctx = fixtures.open_service_record(api, ctx)
    inmate = fixtures.create_inmate(
        api,
        ctx["facility"]["id"],
        booking_number="BK-S08",
        religious_affiliation="JEWISH",
    )
    order = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(inmate["id"], inmate["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    grievance = fixtures.filed_grievance(
        api,
        inmate["id"],
        ctx["facility"]["id"],
        category="DIET_NOT_HONORED",
        narrative="Kosher tray not delivered at lunch.",
        diet_order_id=order["id"],
        meal_service_record_id=ctx["record"]["id"],
    )
    assertions.assert_instant(grievance["response_due_at"], "2026-08-06T00:00:00Z")

    routed = validate_success(
        api.route_grievance(
            grievance["id"], factories.route_payload("DUAL_TRACK"), users.GRIEVANCE_COORD
        )
    )
    assert routed["status"] == "DUAL_TRACK"
    assert routed["routed_branch"] == "BOTH"

    held = validate_success(
        api.complete_grievance_branch(
            grievance["id"],
            factories.complete_branch_payload("INVESTIGATION"),
            users.GRIEVANCE_COORD,
        )
    )
    assert held["status"] == "DUAL_TRACK", "the fork holds while the join is unsatisfied"
    assert held["investigation_complete"] is True
    assert held["diet_review_complete"] is False
    assert held["diet_remedy_required"] is False

    validate_error(
        api.respond_grievance(
            grievance["id"],
            factories.respond_payload(
                "MENU_CORRECTION",
                response_note="Premature answer while the diet branch is open.",
            ),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_BRANCHES_INCOMPLETE.value,
        409,
    )

    joined = validate_success(
        api.complete_grievance_branch(
            grievance["id"],
            factories.complete_branch_payload("DIET_REVIEW", "KITCHEN_AT_FAULT"),
            users.DIETITIAN,
        )
    )
    assert joined["status"] == "READY_FOR_RESPONSE"
    assert joined["investigation_complete"] is True
    assert joined["diet_review_complete"] is True
    assert joined["diet_remedy_required"] is True
    assertions.assert_instant(joined["response_due_at"], "2026-08-06T00:00:00Z")


def test_releasing_an_inmate_revokes_the_order_and_empties_both_counters(
    api: ApiClient,
) -> None:
    """A RELEASE movement reaches three aggregates in one request: the inmate, its
    active order and the facility's special-diet census.

    The PRD states: "A `RELEASE` movement sets `status` to `RELEASED`", and "Both
    `RELEASE` and `TRANSFER` additionally revoke every `ACTIVE` or `SUSPENDED` diet
    order the inmate holds, walking `active_diet_order_count` back to 0 and decrementing
    the facility's `active_special_diet_count` once per revoked order."

    Design: Corner/state_machines/corner_inmate_release_revokes_orders_across_entities
    """
    ctx = _facility_with_one_inmate(
        api,
        "CFS-2515-S09",
        "FAC-S09",
        "BK-S09",
        religious_affiliation="JEWISH",
    )
    order = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                ctx["inmate"]["id"], ctx["inmate"]["version"]
            ),
            users.DIETITIAN,
        ),
        201,
    )
    verified = validate_success(api.verify_diet_order(order["id"], users.CHAPLAIN))
    assert verified["status"] == "ACTIVE"
    before = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    assert before["active_diet_order_count"] == 1

    released = validate_success(
        api.record_inmate_movement(
            ctx["inmate"]["id"], factories.movement_payload("RELEASE"), users.OFFICER
        )
    )

    assertions.assert_inmate(released)
    assert released["status"] == "RELEASED"
    assert released["active_diet_order_count"] == 0
    assert fixtures.read_diet_order(api, order["id"])["status"] == "REVOKED"
    assert (
        fixtures.read_facility(api, ctx["facility"]["id"])["active_special_diet_count"]
        == 0
    )


# ---------------------------------------------------------------------------
# Parallel axes, bounded cycles, guards on another aggregate
# ---------------------------------------------------------------------------
