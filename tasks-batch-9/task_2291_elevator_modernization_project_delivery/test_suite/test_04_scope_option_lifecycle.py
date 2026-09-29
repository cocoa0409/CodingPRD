"""Scope options: submission, the ordered approval gates, revision and rescission."""
from test_helpers import (
    ApiErrorId,
    api_client,
    countersign_survey,
    create_scope_option,
    list_code_triggers,
    list_scope_options,
    make_building_representative_headers,
    price_code_trigger,
    project_version,
    read_car,
    read_code_trigger,
    read_project,
    read_scope_option,
    reject_scope_option,
    rescind_scope_option,
    revise_scope_option,
    setup_approved_option,
    setup_project_with_cars,
    setup_rejected_option,
    setup_scoped_car,
    submit_scope_option,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PM

ASHFIELD = {
    "name": "City of Ashfield",
    "code_edition_year": 2019,
    "fire_service_required": True,
    "seismic_zone": 0,
    "door_protection_required": False,
    "permit_surcharge_pct": 0.0000,
}


def _approve_for(project_id: str, car_id: str, base_price_cents: int) -> str:
    """Survey, scope, submit and approve one car; returns the approved option id."""
    survey = submit_survey(
        car_id,
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
    )
    countersign_survey(survey["id"])
    option = create_scope_option(
        project_id, car_id, tier="CONTROLLER_ONLY", base_price_cents=base_price_cents
    )
    submit_scope_option(option["id"])
    approved = validate_success(
        api_client.approve_scope_option(
            option["id"], make_building_representative_headers(project_id)
        )
    )
    assert approved["status"] == "APPROVED"
    return option["id"]


def _rejected_cycle():
    """A rejected option carried through three accepted revisions."""
    ctx = setup_rejected_option(
        base_price_cents=5_000_000, rejection_note="price too high, cycle 1"
    )
    option_id = ctx["scope_option"]["id"]
    for price, note in (
        (4_800_000, "price too high, cycle 2"),
        (4_600_000, "price too high, cycle 3"),
        (4_400_000, "price still too high, cycle 4"),
    ):
        revise_scope_option(option_id, price)
        submit_scope_option(option_id)
        reject_scope_option(ctx["project"]["id"], option_id, note)
    return ctx


def test_a_fourth_revision_of_a_rejected_option_is_refused():
    """The option must be in `REJECTED`, or the attempt is refused with
    `ERR_SCOPE_OPTION_STATE_INVALID`, and its `revision_count` must be strictly below 3; a
    fourth revision attempt is refused with `ERR_REVISION_LIMIT`, after which a fresh
    option must be created instead.

    Design: Difficulty/non_linear_state_machine/scope_option_reject_revise_cycle_hits_revision_ceiling
    """
    ctx = _rejected_cycle()
    option_id = ctx["scope_option"]["id"]

    ceiling = read_scope_option(option_id)
    assert ceiling["revision_count"] == 3
    assert ceiling["status"] == "REJECTED"
    assert ceiling["base_price_cents"] == 4_400_000

    response = api_client.revise_scope_option(
        option_id, PM, {"base_price_cents": 4_200_000}
    )
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT, expected_status=409)

    stored = read_scope_option(option_id)
    assert stored["revision_count"] == 3
    assert stored["status"] == "REJECTED"
    assert stored["base_price_cents"] == 4_400_000
    assert stored["total_price_cents"] == 4_400_000

    assert read_car(ctx["car"]["id"])["work_status"] == "SCOPED"
    assert read_project(ctx["project"]["id"])["approved_scope_value_cents"] == 0


def test_each_accepted_revision_walks_the_option_back_to_draft():
    """The option moves `REJECTED → DRAFT`, `revision_count` increases by 1,
    `rejection_note` is cleared back to null, the car steps back `SCOPED → SURVEYED` on
    the work dimension, and both the code-upgrade total and the full pricing chain of §3.4
    are recomputed.

    The option moves `SUBMITTED → REJECTED`, the car's `work_status` is left exactly where
    it is — the car remains `SCOPED`, because nothing physical has changed — and the
    project's `version` increments by 1.

    Design: Difficulty/non_linear_state_machine/scope_option_reject_revise_cycle_hits_revision_ceiling
    """
    ctx = setup_rejected_option(
        base_price_cents=5_000_000, rejection_note="price too high, cycle 1"
    )
    option_id = ctx["scope_option"]["id"]

    rejected = read_scope_option(option_id)
    assert rejected["status"] == "REJECTED"
    assert rejected["revision_count"] == 0
    assert rejected["rejection_note"] == "price too high, cycle 1"
    assert read_car(ctx["car"]["id"])["work_status"] == "SCOPED"

    revised = revise_scope_option(option_id, 4_800_000)
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["rejection_note"] is None
    assert revised["base_price_cents"] == 4_800_000
    assert revised["total_price_cents"] == 4_800_000
    assert read_car(ctx["car"]["id"])["work_status"] == "SURVEYED"

    submit_scope_option(option_id)
    reject_scope_option(ctx["project"]["id"], option_id, "price too high, cycle 2")
    second = revise_scope_option(option_id, 4_600_000)
    assert second["revision_count"] == 2
    assert second["base_price_cents"] == 4_600_000

    submit_scope_option(option_id)
    reject_scope_option(ctx["project"]["id"], option_id, "price too high, cycle 3")
    third = revise_scope_option(option_id, 4_400_000)
    assert third["revision_count"] == 3
    assert third["status"] == "DRAFT"
    assert third["base_price_cents"] == 4_400_000


def _over_budget_option():
    """An 8,000,000-cent option on a 5,000,000-cent contract with one open trigger."""
    return setup_scoped_car(
        tier="CONTROLLER_ONLY",
        base_price_cents=8_000_000,
        jurisdiction_overrides=ASHFIELD,
        building_name="Ashfield Annex",
        contract_value_cents=5_000_000,
    )


def test_approval_reports_the_open_code_trigger_before_the_budget_breach():
    """Three business gates then apply, and their relative order is fixed because the
    safety band outranks the money band: first, zero code triggers of the option may
    remain in status `REQUIRED`, and any still-open trigger refuses the approval with
    `ERR_CODE_TRIGGER_OPEN`; second, the option's declared `tier` must rank at or
    above the car's countersigned `recommended_scope_tier` on the four-step
    invasiveness ladder, and a tier ranking below the recommendation is refused with
    `ERR_SCOPE_TIER_BELOW_RECOMMENDATION` — a car whose imputed-failed score
    recommended `FULL_REPLACEMENT` cannot be discharged with a controller swap,
    however much cheaper that would be; third, and only after both safety gates have
    passed, the project's `approved_scope_value_cents` plus this option's
    `total_price_cents` must not rise strictly above the project's
    `contract_value_cents`, and an approval that would push the ledger strictly past
    the contracted ceiling is refused with `ERR_SCOPE_BUDGET_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/approve_rejected_by_code_trigger_before_budget
    """
    ctx = _over_budget_option()
    project_id = ctx["project"]["id"]
    option_id = ctx["scope_option"]["id"]
    trigger = list_code_triggers(option_id)[0]
    assert trigger["status"] == "REQUIRED"
    submit_scope_option(option_id)

    assert read_scope_option(option_id)["total_price_cents"] == 8_000_000
    assert read_project(project_id)["contract_value_cents"] == 5_000_000

    response = api_client.approve_scope_option(
        option_id, make_building_representative_headers(project_id)
    )
    validate_error(response, ApiErrorId.ERR_CODE_TRIGGER_OPEN, expected_status=409)
    assert response.json()["data"]["error_id"] != "ERR_SCOPE_BUDGET_EXCEEDED"

    assert read_scope_option(option_id)["status"] == "SUBMITTED"
    assert read_car(ctx["car"]["id"])["work_status"] == "SCOPED"

    project = read_project(project_id)
    assert project["approved_scope_value_cents"] == 0
    assert project["status"] == "SCOPING"


def test_the_budget_ceiling_surfaces_only_once_the_safety_gate_clears():
    """Three business gates then apply, and their relative order is fixed because the
    safety band outranks the money band: first, zero code triggers of the option may
    remain in status `REQUIRED`, and any still-open trigger refuses the approval with
    `ERR_CODE_TRIGGER_OPEN`; second, the option's declared `tier` must rank at or
    above the car's countersigned `recommended_scope_tier` on the four-step
    invasiveness ladder, and a tier ranking below the recommendation is refused with
    `ERR_SCOPE_TIER_BELOW_RECOMMENDATION` — a car whose imputed-failed score
    recommended `FULL_REPLACEMENT` cannot be discharged with a controller swap,
    however much cheaper that would be; third, and only after both safety gates have
    passed, the project's `approved_scope_value_cents` plus this option's
    `total_price_cents` must not rise strictly above the project's
    `contract_value_cents`, and an approval that would push the ledger strictly past
    the contracted ceiling is refused with `ERR_SCOPE_BUDGET_EXCEEDED`.

    Because most operations in this domain fail for more than one reason at once, the
    order in which checks run is part of the contract: the first band that rejects the
    request determines the error the caller sees, and no later band can mask an
    earlier one.

    Design: Difficulty/priority_pair_validation_conflict/approve_rejected_by_code_trigger_before_budget
    """
    ctx = _over_budget_option()
    project_id = ctx["project"]["id"]
    option_id = ctx["scope_option"]["id"]
    trigger = list_code_triggers(option_id)[0]
    submit_scope_option(option_id)

    first = api_client.approve_scope_option(
        option_id, make_building_representative_headers(project_id)
    )
    validate_error(first, ApiErrorId.ERR_CODE_TRIGGER_OPEN, expected_status=409)

    price_code_trigger(trigger["id"], 100)
    assert read_code_trigger(trigger["id"])["status"] == "PRICED"
    assert read_scope_option(option_id)["code_upgrade_cents"] == 100

    second = api_client.approve_scope_option(
        option_id, make_building_representative_headers(project_id)
    )
    validate_error(second, ApiErrorId.ERR_SCOPE_BUDGET_EXCEEDED, expected_status=409)

    assert read_scope_option(option_id)["status"] == "SUBMITTED"
    assert read_project(project_id)["approved_scope_value_cents"] == 0


def test_approving_below_the_car_s_recommended_tier_is_refused():
    """Three business gates then apply, and their relative order is fixed because the
    safety band outranks the money band: first, zero code triggers of the option may
    remain in status `REQUIRED`, and any still-open trigger refuses the approval with
    `ERR_CODE_TRIGGER_OPEN`; second, the option's declared `tier` must rank at or
    above the car's countersigned `recommended_scope_tier` on the four-step
    invasiveness ladder, and a tier ranking below the recommendation is refused with
    `ERR_SCOPE_TIER_BELOW_RECOMMENDATION` — a car whose imputed-failed score
    recommended `FULL_REPLACEMENT` cannot be discharged with a controller swap,
    however much cheaper that would be; third, and only after both safety gates have
    passed, the project's `approved_scope_value_cents` plus this option's
    `total_price_cents` must not rise strictly above the project's
    `contract_value_cents`, and an approval that would push the ledger strictly past
    the contracted ceiling is refused with `ERR_SCOPE_BUDGET_EXCEEDED`.

    The four tiers form an invasiveness ladder whose ranks matter later:
    `CONTROLLER_ONLY` ranks 1, `CONTROLLER_DOOR` ranks 2, `CONTROLLER_MACHINE` ranks 3
    and `FULL_REPLACEMENT` ranks 4.

    Design: Corner/errors/approving_a_scope_option_below_the_recommended_tier_is_rejected
    """
    ctx = setup_scoped_car(
        tier="CONTROLLER_ONLY",
        base_price_cents=5_000_000,
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
    )
    project_id = ctx["project"]["id"]
    option_id = ctx["scope_option"]["id"]

    assert ctx["survey"]["final_score"] == 73.75
    assert read_car(ctx["car"]["id"])["recommended_scope_tier"] == "CONTROLLER_DOOR"
    assert list_code_triggers(option_id) == []

    submit_scope_option(option_id)

    response = api_client.approve_scope_option(
        option_id, make_building_representative_headers(project_id)
    )
    validate_error(
        response, ApiErrorId.ERR_SCOPE_TIER_BELOW_RECOMMENDATION, expected_status=409
    )

    stored = read_scope_option(option_id)
    assert stored["status"] == "SUBMITTED"

    project = read_project(project_id)
    assert project["approved_scope_value_cents"] == 0
    assert project["status"] == "SCOPING"
    assert read_car(ctx["car"]["id"])["work_status"] == "SCOPED"


def test_scoping_a_car_whose_survey_is_only_submitted_is_refused():
    """The car must have a countersigned survey on file; scoping a car with no
    countersigned survey is refused with `ERR_CAR_STATE_INVALID`, and creating an option
    under a project that has reached `COMPLETED` is refused with
    `ERR_PROJECT_STATE_INVALID`.

    Design: Corner/errors/scoping_a_car_without_a_countersigned_survey_is_rejected
    """
    ctx = setup_project_with_cars(num_cars=1)
    project_id = ctx["project"]["id"]
    submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
    )
    version_before = project_version(project_id)

    response = api_client.create_scope_option(
        {
            "car_id": ctx["car"]["id"],
            "tier": "CONTROLLER_ONLY",
            "base_price_cents": 5_000_000,
            "expected_project_version": version_before,
        },
        PM,
    )
    validate_error(response, ApiErrorId.ERR_CAR_STATE_INVALID, expected_status=409)

    _, meta = list_scope_options(car_id=ctx["car"]["id"])
    assert meta["total_count"] == 0

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEY_PENDING"
    assert car["condition_score"] is None
    assert car["recommended_scope_tier"] is None

    project = read_project(project_id)
    assert project["status"] == "SURVEY"
    assert project["version"] == version_before


def test_submitting_an_already_approved_option_is_refused():
    """The option must be in `DRAFT`; submitting an option in any other status is refused
    with `ERR_SCOPE_OPTION_STATE_INVALID`.

    Design: Corner/state_machines/submitting_an_approved_scope_option_is_an_invalid_transition
    """
    ctx = setup_approved_option(base_price_cents=5_000_000)
    project_id = ctx["project"]["id"]
    option_id = ctx["scope_option"]["id"]

    response = api_client.submit_scope_option(option_id, PM)
    validate_error(
        response, ApiErrorId.ERR_SCOPE_OPTION_STATE_INVALID, expected_status=409
    )

    stored = read_scope_option(option_id)
    assert stored["status"] == "APPROVED"
    assert stored["total_price_cents"] == 5_000_000

    project = read_project(project_id)
    assert project["approved_scope_value_cents"] == 5_000_000
    assert project["status"] == "EXECUTION"
    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"


def test_rescinding_an_already_superseded_option_is_refused():
    """Only a `ProjectManager` may rescind, and only an option in status `APPROVED`;
    rescinding anything else is refused with `ERR_SCOPE_OPTION_STATE_INVALID`.

    A new option is created in status `DRAFT` with `revision_count` at zero and
    `rejection_note` null, and it takes over as the car's one live option: any earlier
    option for the same `car_id` sitting in `DRAFT`, `SUBMITTED`, `REJECTED` or `APPROVED`
    becomes `SUPERSEDED`, which is a terminal status.

    Design: Corner/state_machines/rescinding_a_superseded_scope_option_is_locked_out
    """
    ctx = setup_approved_option(base_price_cents=5_000_000)
    project_id = ctx["project"]["id"]
    option_id = ctx["scope_option"]["id"]

    rescinded = rescind_scope_option(option_id)
    assert rescinded["status"] == "SUPERSEDED"
    version_after_rescind = project_version(project_id)
    assert read_project(project_id)["approved_scope_value_cents"] == 0

    response = api_client.rescind_scope_option(option_id, PM)
    validate_error(
        response, ApiErrorId.ERR_SCOPE_OPTION_STATE_INVALID, expected_status=409
    )

    stored = read_scope_option(option_id)
    assert stored["status"] == "SUPERSEDED"
    assert stored["total_price_cents"] == 5_000_000

    project = read_project(project_id)
    assert project["approved_scope_value_cents"] == 0
    assert project["version"] == version_after_rescind

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SCOPED"
    assert car["compliance_status"] == "NOT_EVALUATED"


def test_the_rescinded_value_returns_to_the_budget_for_a_later_approval():
    """The first link moves the option `APPROVED → SUPERSEDED` and removes its
    `total_price_cents` from the project's `approved_scope_value_cents`.

    Because these are conserved quantities, every compensating action must return them to
    their pre-action value. Rescinding an approved scope option removes exactly the total
    it contributed to `approved_scope_value_cents`. A ledger that drifts is a defect even
    when no individual operation looks wrong in isolation.

    Design: Difficulty/compensating_invariant/approved_scope_value_cents_conserved_across_rescind_and_reapproval
    """
    ctx = setup_approved_option(num_cars=3, base_price_cents=5_000_000)
    project_id = ctx["project"]["id"]
    car_one, car_two, car_three = ctx["cars"]
    option_one = ctx["scope_option"]["id"]

    option_two = _approve_for(project_id, car_two["id"], 6_000_000)
    assert read_scope_option(option_one)["total_price_cents"] == 5_000_000
    assert read_scope_option(option_two)["total_price_cents"] == 6_000_000
    assert read_project(project_id)["approved_scope_value_cents"] == 11_000_000

    rescind_scope_option(option_one)

    superseded = read_scope_option(option_one)
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["total_price_cents"] == 5_000_000
    assert read_project(project_id)["approved_scope_value_cents"] == 6_000_000

    unwound = read_car(car_one["id"])
    assert unwound["work_status"] == "SCOPED"
    assert unwound["approved_scope_option_id"] is None
    assert unwound["compliance_status"] == "NOT_EVALUATED"

    untouched = read_car(car_two["id"])
    assert untouched["work_status"] == "PROCURING"
    assert untouched["approved_scope_option_id"] == option_two

    option_three = _approve_for(project_id, car_three["id"], 4_000_000)
    assert read_project(project_id)["approved_scope_value_cents"] == 10_000_000
    assert read_scope_option(option_three)["status"] == "APPROVED"
    assert read_project(project_id)["contract_value_cents"] == 60_000_000


def test_the_approved_ledger_equals_the_sum_of_the_live_approved_options():
    """`approved_scope_value_cents` is the sum of `total_price_cents` over every scope
    option in status `APPROVED` whose car belongs to this project.

    Four counters on `ModernizationProject` are not free-standing values that operations
    nudge up and down at will; they are definitions, and after any write completes each one
    must equal exactly what its definition says.

    Options can be listed and narrowed by `car_id` or `status`, and that list is also how
    a caller discovers which option a car's `approved_scope_option_id` points at, since
    that pointer is a denormalized convenience rather than a declared relationship.

    Design: Difficulty/compensating_invariant/approved_scope_value_cents_conserved_across_rescind_and_reapproval
    """
    ctx = setup_approved_option(num_cars=3, base_price_cents=5_000_000)
    project_id = ctx["project"]["id"]
    car_one, car_two, car_three = ctx["cars"]

    option_two = _approve_for(project_id, car_two["id"], 6_000_000)
    rescind_scope_option(ctx["scope_option"]["id"])
    option_three = _approve_for(project_id, car_three["id"], 4_000_000)

    _, meta_one = validate_paginated(
        api_client.list_scope_options(
            PM, params={"car_id": car_one["id"], "status": "APPROVED"}
        )
    )
    assert meta_one["total_count"] == 0

    live_total = 0
    for car_id, expected_option in (
        (car_two["id"], option_two),
        (car_three["id"], option_three),
    ):
        rows, meta = validate_paginated(
            api_client.list_scope_options(
                PM, params={"car_id": car_id, "status": "APPROVED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == expected_option
        live_total += rows[0]["total_price_cents"]

    project = read_project(project_id)
    assert live_total == 10_000_000
    assert project["approved_scope_value_cents"] == live_total
    assert project["approved_scope_value_cents"] <= project["contract_value_cents"]
