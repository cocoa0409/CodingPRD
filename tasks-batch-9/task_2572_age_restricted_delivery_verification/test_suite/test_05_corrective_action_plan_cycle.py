"""The corrective action plan's revision cycle and the counter that ends it."""

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-20T12:00:00Z"
DUE_AT = "2026-09-30T00:00:00Z"

FIRST_ITEMS = ["Retrain every ALCOHOL courier"]
SECOND_ITEMS = ["Retrain every ALCOHOL courier by 2026-09-15"]
THIRD_ITEMS = ["Retrain every ALCOHOL courier by 2026-09-15", "Sample 20 deliveries weekly"]
FOURTH_ITEMS = ["Retrain every ALCOHOL courier by 2026-09-15", "Sample 50 deliveries weekly"]
FIFTH_ITEMS = ["Retrain every ALCOHOL courier by 2026-09-15", "Sample 80 deliveries weekly"]


def _substantiated_case_with_a_filed_plan(api):
    """A MAJOR case substantiated by one officer, with the partner's first plan filed.

    The officer who substantiates is not the officer who reviews, so the
    segregation-of-duties rule never bites in this file.
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Decoy Buyer")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", contract_tier="STANDARD",
        license_reference="NY-DEL-0001",
    )
    courier = fx.create_courier(api, partner["id"])
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], "2026-08-21T16:00:00Z", 0
    )
    probe = fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type="NO_ID_PRESENTED",
        scheduled_at="2026-08-20T13:00:00Z",
    )
    case = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="MAJOR",
        assessed_severity="MAJOR",
        officer_headers=OFFICER_A_HEADERS,
    )
    plan = fx.file_plan(api, case, remediation_items=FIRST_ITEMS, due_at=DUE_AT)
    return {"partner": partner, "case": case, "plan": plan}


def _walk_the_cycle_to_the_third_round(api, world):
    """Three accepted revisions, then a fourth revision request on top of them."""
    plan = world["plan"]
    partner_id = world["partner"]["id"]
    for items in (SECOND_ITEMS, THIRD_ITEMS, FOURTH_ITEMS):
        fx.review_plan(api, plan["id"], "REQUEST_REVISION", OFFICER_B_HEADERS)
        fx.resubmit_plan(api, plan, partner_id, remediation_items=items, due_at=DUE_AT)
    fx.review_plan(api, plan["id"], "REQUEST_REVISION", OFFICER_B_HEADERS)
    return fx.read_plan(api, plan["id"])


def test_01_a_new_plan_opens_in_submitted_at_revision_round_zero(api):
    """PRD 3.9: "The new plan opens in `state` `SUBMITTED` with `revision_round` 0
    and `reviewed_by_user_id`, `verified_by_user_id`, `verification_outcome` and
    `notes` all null; filing it marks every earlier plan of the same case whose
    `state` is `SUBMITTED`, `ACCEPTED`, `REVISION_REQUESTED` or
    `FAILED_VERIFICATION` as `SUPERSEDED` — the edge `SUBMITTED → SUPERSEDED` and
    its counterparts from the other three non-terminal plan states — and advances
    the case's `version` by one."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_revision_cycle_bounded_at_three_rounds
    """
    world = _substantiated_case_with_a_filed_plan(api)

    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["state"] == "SUBMITTED"
    assert plan["revision_round"] == 0
    assert plan["reviewed_by_user_id"] is None
    assert plan["verified_by_user_id"] is None
    assert plan["verification_outcome"] is None
    assert plan["remediation_items"] == FIRST_ITEMS


def test_02_each_revision_request_and_resubmission_traverses_the_cycle(api):
    """PRD 3.9: "A successful resubmission replaces the plan's `remediation_items`
    and `due_at`, increments `revision_round` by one, and returns the plan to
    `SUBMITTED` for another review."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_revision_cycle_bounded_at_three_rounds
    """
    world = _substantiated_case_with_a_filed_plan(api)
    plan_id = world["plan"]["id"]

    fx.review_plan(api, plan_id, "REQUEST_REVISION", OFFICER_B_HEADERS)
    requested = fx.read_plan(api, plan_id)
    assert requested["state"] == "REVISION_REQUESTED"
    assert requested["revision_round"] == 0

    fx.resubmit_plan(
        api, world["plan"], world["partner"]["id"],
        remediation_items=SECOND_ITEMS, due_at=DUE_AT,
    )

    resubmitted = fx.read_plan(api, plan_id)
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["remediation_items"] == SECOND_ITEMS


def test_03_the_fourth_resubmission_is_refused_on_the_revision_counter(api):
    """PRD 3.9: "It is admissible along `REVISION_REQUESTED → SUBMITTED` and along
    `FAILED_VERIFICATION → SUBMITTED`, requires the acting `X-User-ID` to equal the parent
    case's `delivery_partner_id`, and requires the plan's `revision_round` to be strictly
    below 3; once it has reached 3 the request is refused with `ERR_REVISION_LIMIT_REACHED`,
    so the fourth resubmission never lands."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_revision_cycle_bounded_at_three_rounds
    """
    world = _substantiated_case_with_a_filed_plan(api)
    plan = _walk_the_cycle_to_the_third_round(api, world)
    assert plan["revision_round"] == 3
    assert plan["state"] == "REVISION_REQUESTED"

    response = api.resubmit_corrective_action_plan(
        plan["id"],
        f.plan_resubmit_payload(due_at=DUE_AT, remediation_items=FIFTH_ITEMS),
        make_partner_manager_headers(world["partner"]["id"]),
    )
    validate_error(response, ApiErrorId.REVISION_LIMIT_REACHED.value)


def test_04_the_refused_resubmission_leaves_the_plan_exactly_as_it_was(api):
    """PRD 3.9: "Resubmission is the partner's revision loop and closes the plan's
    cycle. It is admissible along `REVISION_REQUESTED → SUBMITTED` and along
    `FAILED_VERIFICATION → SUBMITTED`, requires the acting `X-User-ID` to equal the
    parent case's `delivery_partner_id`, and requires the plan's `revision_round` to
    be strictly below 3; once it has reached 3 the request is refused with
    `ERR_REVISION_LIMIT_REACHED`, so the fourth resubmission never lands."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_revision_cycle_bounded_at_three_rounds
    """
    world = _substantiated_case_with_a_filed_plan(api)
    plan = _walk_the_cycle_to_the_third_round(api, world)

    response = api.resubmit_corrective_action_plan(
        plan["id"],
        f.plan_resubmit_payload(due_at=DUE_AT, remediation_items=FIFTH_ITEMS),
        make_partner_manager_headers(world["partner"]["id"]),
    )
    validate_error(response, ApiErrorId.REVISION_LIMIT_REACHED.value)

    after = fx.read_plan(api, plan["id"])
    assert after["revision_round"] == 3
    assert after["state"] == "REVISION_REQUESTED"
    assert after["remediation_items"] == FOURTH_ITEMS, (
        "the rejected request must not have replaced the third revision's commitments; "
        f"got {after['remediation_items']}"
    )


def test_05_the_bounded_cycle_never_forks_the_case_into_a_second_plan(api):
    """PRD 3.9: "The new plan opens in `state` `SUBMITTED` with `revision_round` 0 and
    `reviewed_by_user_id`, `verified_by_user_id`, `verification_outcome` and `notes` all
    null; filing it marks every earlier plan of the same case whose `state` is `SUBMITTED`,
    `ACCEPTED`, `REVISION_REQUESTED` or `FAILED_VERIFICATION` as `SUPERSEDED` — the edge
    `SUBMITTED → SUPERSEDED` and its counterparts from the other three non-terminal plan
    states — and advances the case's `version` by one."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_revision_cycle_bounded_at_three_rounds
    """
    world = _substantiated_case_with_a_filed_plan(api)
    _walk_the_cycle_to_the_third_round(api, world)

    plans, _meta = validate_paginated(
        api.list_corrective_action_plans(world["case"]["id"], ADMIN_HEADERS)
    )
    assert len(plans) == 1, (
        "the cycle revises one plan row in place rather than filing a fresh plan per "
        f"round; got {len(plans)} plan rows"
    )
    case = fx.read_case(api, world["case"]["id"])
    assert case["state"] == "SUBSTANTIATED"
