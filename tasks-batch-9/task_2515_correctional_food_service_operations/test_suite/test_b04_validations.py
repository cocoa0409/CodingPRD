"""Field, cross-field, aggregate and cross-entity validation.

These cases pin which rule answers when a request is wrong: the specific code a
violation maps to, the order two simultaneous violations are reported in, and the
boundary at which a rule stops firing.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, factories, fixtures
from test_helpers import test_users as users


def test_a_salty_menu_answers_the_sodium_code_and_not_the_adequacy_code(
    api: ApiClient,
) -> None:
    """A cycle that clears the energy floor and the protein floor but breaches the
    sodium cap is refused with the cap's own code.

    The PRD states: "First, `approved_kcal_per_meal_day` must be at least
    `contracted_kcal_per_meal_day`; if it is lower, the sign is rejected with
    `ERR_NUTRITION_BELOW_STANDARD`. Second, `approved_protein_grams_per_meal_day` must be
    at least `contracted_protein_grams_per_meal_day` ... Third,
    `approved_sodium_mg_per_meal_day` must be at or below
    `contracted_sodium_mg_cap_per_meal_day`; exceeding the cap is the distinct
    `ERR_SODIUM_CAP_EXCEEDED`."

    Design: Corner/validations/corner_sodium_cap_violation_returns_its_own_error
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-V01"},
        facility_overrides={
            "facility_code": "FAC-V01",
            "sharps_authorized_count": 12,
        },
    )
    cycle = validate_success(
        api.create_menu_cycle(
            factories.menu_cycle_payload(
                ctx["facility"]["id"], cycle_code="CYC-V01", cycle_length_days=1
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    validate_success(
        api.add_menu_cycle_item(
            cycle["id"], factories.breakfast_item_payload(), users.FOOD_SUPERVISOR
        ),
        201,
    )
    validate_success(
        api.add_menu_cycle_item(
            cycle["id"], factories.lunch_item_payload(), users.FOOD_SUPERVISOR
        ),
        201,
    )
    validate_success(
        api.add_menu_cycle_item(
            cycle["id"],
            factories.dinner_item_payload(
                component_name="Salted Bean Rice Bowl", sodium_mg_per_100g=460.0
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )

    # Per-item daily figures: kcal 211 + 689 + 1900 == 2800 (the floor is met),
    # protein 10.00 + 18.00 + 30.50 == 58.50 (the floor is met), and sodium
    # 300 + 900 + 2300 == 3500 mg against a 2400 mg cap.
    validate_error(
        api.nutrition_sign_menu_cycle(cycle["id"], users.DIETITIAN),
        ApiErrorId.ERR_SODIUM_CAP_EXCEEDED.value,
        422,
    )

    unsigned = validate_success(
        api.get_menu_cycle(cycle["id"], users.FOOD_SUPERVISOR)
    )
    assert unsigned["status"] == "DRAFT"
    assert unsigned["approved_sodium_mg_per_meal_day"] is None
    assert unsigned["approved_kcal_per_meal_day"] is None
    assert unsigned["nutrition_signed_by_user_id"] is None
    assert unsigned["item_count"] == 3


def test_two_batches_that_each_fit_can_still_break_the_tray_budget_together(
    api: ApiClient,
) -> None:
    """The budget is a sum over the forecast's live batches, so the second create is
    refused on the collective total and leaves the first batch untouched.

    The PRD states: "The sum of `planned_trays` across every batch tied to the same
    forecast whose `production_stage` is not `DISCARDED`, counting the batch now being
    created, may not exceed that forecast's `total_forecast_trays`. Exceeding it reports
    `ERR_TRAY_BUDGET_EXCEEDED`."

    Design: Corner/validations/corner_tray_budget_is_enforced_across_all_batches
    """
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-V02"},
        facility_overrides={
            "facility_code": "FAC-V02",
            "sharps_authorized_count": 12,
        },
    )
    forecast = ctx["forecast"]
    assert forecast["total_forecast_trays"] == 22
    assert ctx["facility"]["blast_chiller_capacity"] == 2

    first = fixtures.planned_batch(api, ctx, planned_trays=12)["batch"]
    assert first["production_stage"] == "PLANNED"

    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    validate_error(
        api.create_production_batch(
            factories.production_batch_payload(
                ctx["facility"]["id"],
                forecast["id"],
                facility["version"],
                recipe_component="Cornbread",
                planned_trays=11,
            ),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_TRAY_BUDGET_EXCEEDED.value,
        409,
    )

    survivor = fixtures.read_batch(api, first["id"])
    assert survivor["planned_trays"] == 12
    assert survivor["production_stage"] == "PLANNED"
    assert survivor["version"] == first["version"]

    data, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, params={"meal_forecast_id": forecast["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [first["id"]]


def test_the_clinical_indication_gate_only_guards_the_medical_family(
    api: ApiClient,
) -> None:
    """One inmate's religious order verifies with no clinical indication at all, while
    the medical order over the same window is refused until one is supplied.

    The PRD states: "A `MEDICAL` order must carry a non-empty `clinical_indication` by the
    time it is verified; a blank one is `ERR_CLINICAL_INDICATION_REQUIRED` with HTTP 422."
    The window rule is scoped by family: "only orders for the same inmate, only orders of
    the same `order_type`".

    Design: Corner/validations/corner_clinical_indication_required_only_for_medical_orders
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-V03")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-V03", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-V03")

    religious = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(inmate["id"], inmate["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    reread = validate_success(api.get_inmate(inmate["id"], users.DIETITIAN))
    medical = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(
                inmate["id"],
                reread["version"],
                clinical_indication=factories.OMIT,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    assert medical["clinical_indication"] is None
    assert medical["order_type"] == "MEDICAL"

    verified = validate_success(
        api.verify_diet_order(religious["id"], users.CHAPLAIN)
    )
    assert verified["status"] == "ACTIVE"

    validate_error(
        api.verify_diet_order(medical["id"], users.MEDICAL),
        ApiErrorId.ERR_CLINICAL_INDICATION_REQUIRED.value,
        422,
    )
    unverified = fixtures.read_diet_order(api, medical["id"])
    assert unverified["status"] == "PENDING_VERIFICATION"
    assert unverified["version"] == 1
    assert unverified["verified_by_user_id"] is None


def test_the_missing_forecast_answers_before_the_facility_can_be_compared(
    api: ApiClient,
) -> None:
    """A record naming both an unknown forecast and a facility that could never match it
    answers the existence check, because the coherence check has nothing to compare.

    The PRD states the ladder order: referenced entities are resolved at step 9 —
    "Referenced entities exist, else the entity-specific not-found error (HTTP 404)" —
    before step 10, where "Cross-parent coherence holds, else `ERR_FACILITY_MISMATCH`
    (HTTP 409). This check guards seven creations — a grievance, a service record, a
    production batch, a kitchen worker, a tool issuance, a menu substitution and a diet
    order".

    Design: Corner/validations/corner_foreign_key_existence_runs_before_facility_coherence
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-V04"},
        facility_overrides={
            "facility_code": "FAC-V04A",
            "sharps_authorized_count": 12,
        },
    )
    facility_b = fixtures.create_facility(
        api,
        ctx["contract"]["id"],
        facility_code="FAC-V04B",
        name="South Unit Kitchen",
        sharps_authorized_count=12,
    )

    validate_error(
        api.create_meal_service_record(
            factories.meal_service_record_payload(
                facility_b["id"],
                NON_EXISTENT_UUID,
                service_date="2026-08-01",
                meal_slot="LUNCH",
            ),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_MEAL_FORECAST_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(
        api.list_meal_service_records(
            users.FOOD_SUPERVISOR, params={"facility_id": facility_b["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_record_cannot_settle_a_forecast_that_belongs_to_the_other_kitchen(
    api: ApiClient,
) -> None:
    """The forecast is LOCKED and its date and slot agree, yet the record is refused
    because it names the sibling facility under the same contract.

    The PRD states: "The record's `facility_id` must also match the forecast's facility,
    otherwise `ERR_FACILITY_MISMATCH`."

    Design: Corner/validations/corner_service_record_facility_must_match_its_forecast
    """
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-V05"},
        facility_overrides={
            "facility_code": "FAC-V05A",
            "sharps_authorized_count": 12,
        },
    )
    facility_b = fixtures.create_facility(
        api,
        ctx["contract"]["id"],
        facility_code="FAC-V05B",
        name="South Unit Kitchen",
        sharps_authorized_count=12,
    )
    forecast = ctx["forecast"]
    assert forecast["status"] == "LOCKED"

    validate_error(
        api.create_meal_service_record(
            factories.meal_service_record_payload(
                facility_b["id"],
                forecast["id"],
                service_date=forecast["service_date"],
                meal_slot=forecast["meal_slot"],
            ),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_FACILITY_MISMATCH.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_meal_service_records(
            users.FOOD_SUPERVISOR, params={"meal_forecast_id": forecast["id"]}
        )
    )
    assert meta["total_count"] == 0
