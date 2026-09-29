"""Composite state builders.

Every builder drives the API through declared endpoints only, so each test can
start from an empty database and reach the state it needs. Builders use the
lenient ``get_success_data`` so that a setup failure surfaces as a readable
KeyError on the returned state rather than as an assertion inside setup.
"""

from __future__ import annotations

from typing import Any

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import TEST_DEFAULTS
from .factories import (
    cleanout_certification_payload,
    complete_conditioning_run_payload,
    create_carryover_payload,
    create_certification_tag_payload,
    create_conditioning_line_payload,
    create_conditioning_run_payload,
    create_field_history_record_payload,
    create_field_inspection_payload,
    create_grower_payload,
    create_harvest_equipment_payload,
    create_harvest_event_payload,
    create_lot_sample_payload,
    create_production_contract_payload,
    create_production_field_payload,
    create_settlement_payload,
    create_treatment_product_payload,
    create_variety_payload,
    lot_sample_results_payload,
    pay_settlement_payload,
    set_clock_payload,
    sign_contract_payload,
)
from .test_users import (
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_field_officer_headers,
    make_grower_headers,
    make_program_admin_headers,
    make_settlement_accountant_headers,
)

# ---------------------------------------------------------------------------
# Tier 1: clock and single reference entities
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> dict[str, Any]:
    """Move the logical clock; only a ProgramAdmin may do so."""
    return get_success_data(api.set_clock(set_clock_payload(current_utc), make_program_admin_headers()))


def make_variety(api: ApiClient, **overrides: Any) -> dict[str, Any]:
    return get_success_data(api.create_variety(create_variety_payload(**overrides), make_program_admin_headers()))


def make_treatment_product(api: ApiClient, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_treatment_product(create_treatment_product_payload(**overrides), make_program_admin_headers())
    )


def make_grower(api: ApiClient, **overrides: Any) -> dict[str, Any]:
    return get_success_data(api.create_grower(create_grower_payload(**overrides), make_program_admin_headers()))


def make_production_field(api: ApiClient, grower_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_production_field(
            create_production_field_payload(grower_id, **overrides), make_program_admin_headers()
        )
    )


def make_field_history_record(api: ApiClient, production_field_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_field_history_record(
            production_field_id, create_field_history_record_payload(**overrides), make_field_officer_headers()
        )
    )


def make_harvest_equipment(api: ApiClient, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_harvest_equipment(create_harvest_equipment_payload(**overrides), make_conditioning_manager_headers())
    )


def certify_cleanout(api: ApiClient, harvest_equipment_id: str, variety_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.certify_equipment_cleanout(
            harvest_equipment_id,
            cleanout_certification_payload(variety_id, **overrides),
            make_conditioning_manager_headers(),
        )
    )


def make_conditioning_line(api: ApiClient, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_conditioning_line(create_conditioning_line_payload(**overrides), make_conditioning_manager_headers())
    )


# ---------------------------------------------------------------------------
# Tier 2: contract state progression
# ---------------------------------------------------------------------------


def draft_contract_state(
    api: ApiClient,
    variety_overrides: dict[str, Any] | None = None,
    grower_overrides: dict[str, Any] | None = None,
    field_overrides: dict[str, Any] | None = None,
    history_overrides: dict[str, Any] | None = None,
    with_history: bool = True,
    **contract_overrides: Any,
) -> dict[str, Any]:
    """Reference data plus one DRAFT contract, returned as a state bundle."""
    variety = make_variety(api, **(variety_overrides or {}))
    grower = make_grower(api, **(grower_overrides or {}))
    field = make_production_field(api, grower["id"], **(field_overrides or {}))
    history = (
        make_field_history_record(api, field["id"], **(history_overrides or {})) if with_history else None
    )
    contract = get_success_data(
        api.create_production_contract(
            create_production_contract_payload(grower["id"], variety["id"], field["id"], **contract_overrides),
            make_program_admin_headers(),
        )
    )
    return {
        "variety": variety,
        "grower": grower,
        "field": field,
        "history": history,
        "contract": contract,
    }


def offered_contract_state(api: ApiClient, **kwargs: Any) -> dict[str, Any]:
    """A contract advanced DRAFT to OFFERED through the compliance gate."""
    state = draft_contract_state(api, **kwargs)
    state["contract"] = get_success_data(
        api.offer_production_contract(state["contract"]["id"], {}, make_program_admin_headers())
    )
    return state


def planted_contract_state(api: ApiClient, planted_on: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """A contract signed by its owning grower, so PLANTED."""
    state = offered_contract_state(api, **kwargs)
    grower_id = state["grower"]["id"]
    state["contract"] = get_success_data(
        api.sign_production_contract(
            state["contract"]["id"],
            sign_contract_payload(planted_on=planted_on or TEST_DEFAULTS["PLANTED_ON"]),
            make_grower_headers(grower_id),
        )
    )
    return state


def record_inspection(
    api: ApiClient,
    production_contract_id: str,
    inspector_user_id: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    headers = make_field_officer_headers(inspector_user_id) if inspector_user_id else make_field_officer_headers()
    return get_success_data(
        api.create_field_inspection(
            create_field_inspection_payload(production_contract_id, **overrides), headers
        )
    )


def inspection_passed_contract_state(
    api: ApiClient,
    inspection_clock: str | None = None,
    inspection_overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A PLANTED contract carried to INSPECTION_PASSED by one passing field walk."""
    state = planted_contract_state(api, **kwargs)
    set_clock(api, inspection_clock or TEST_DEFAULTS["INSPECTION_CLOCK"])
    state["inspection"] = record_inspection(
        api, state["contract"]["id"], **(inspection_overrides or {})
    )
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


# ---------------------------------------------------------------------------
# Tier 3: harvest and the seed lot
# ---------------------------------------------------------------------------


def harvested_lot_state(
    api: ApiClient,
    harvest_clock: str | None = None,
    equipment_overrides: dict[str, Any] | None = None,
    cleanout_overrides: dict[str, Any] | None = None,
    line_overrides: dict[str, Any] | None = None,
    harvest_overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Carry a contract to HARVESTED and mint its RAW seed lot."""
    state = inspection_passed_contract_state(api, **kwargs)
    state["equipment"] = make_harvest_equipment(api, **(equipment_overrides or {}))
    set_clock(api, harvest_clock or TEST_DEFAULTS["HARVEST_CLOCK"])
    state["equipment"] = certify_cleanout(
        api, state["equipment"]["id"], state["variety"]["id"], **(cleanout_overrides or {})
    )
    state["line"] = make_conditioning_line(api, **(line_overrides or {}))
    state["harvest_event"] = get_success_data(
        api.create_harvest_event(
            create_harvest_event_payload(
                state["contract"]["id"], state["equipment"]["id"], **(harvest_overrides or {})
            ),
            make_conditioning_manager_headers(),
        )
    )
    state["seed_lot"] = get_success_data(
        api.get_seed_lot(state["harvest_event"]["seed_lot_id"], make_conditioning_manager_headers())
    )
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


# ---------------------------------------------------------------------------
# Tier 4: conditioning runs
# ---------------------------------------------------------------------------


def plan_run(
    api: ApiClient,
    seed_lot_id: str,
    conditioning_line_id: str,
    stage: str,
    **overrides: Any,
) -> dict[str, Any]:
    return get_success_data(
        api.create_conditioning_run(
            create_conditioning_run_payload(seed_lot_id, conditioning_line_id, stage, **overrides),
            make_conditioning_manager_headers(),
        )
    )


def complete_run(api: ApiClient, conditioning_run_id: str, output_kg: float) -> dict[str, Any]:
    return get_success_data(
        api.complete_conditioning_run(
            conditioning_run_id, complete_conditioning_run_payload(output_kg), make_conditioning_manager_headers()
        )
    )


def run_stage(
    api: ApiClient,
    seed_lot_id: str,
    conditioning_line_id: str,
    stage: str,
    output_kg: float,
    **overrides: Any,
) -> dict[str, Any]:
    """Plan a run and complete it in one step."""
    run = plan_run(api, seed_lot_id, conditioning_line_id, stage, **overrides)
    return complete_run(api, run["id"], output_kg)


def bagged_lot_state(api: ApiClient, **kwargs: Any) -> dict[str, Any]:
    """Carry a RAW lot through CLEANING, SIZING and BAGGING on one line."""
    state = harvested_lot_state(api, **kwargs)
    lot_id = state["seed_lot"]["id"]
    line_id = state["line"]["id"]
    gross_kg = state["seed_lot"]["gross_kg"]

    state["cleaning_run"] = run_stage(
        api,
        lot_id,
        line_id,
        "CLEANING",
        TEST_DEFAULTS["CLEANING_OUTPUT_KG"],
        window_start=TEST_DEFAULTS["CLEANING_WINDOW_START"],
        window_end=TEST_DEFAULTS["CLEANING_WINDOW_END"],
        input_kg=gross_kg,
    )
    state["sizing_run"] = run_stage(
        api,
        lot_id,
        line_id,
        "SIZING",
        TEST_DEFAULTS["SIZING_OUTPUT_KG"],
        window_start=TEST_DEFAULTS["SIZING_WINDOW_START"],
        window_end=TEST_DEFAULTS["SIZING_WINDOW_END"],
        input_kg=TEST_DEFAULTS["CLEANING_OUTPUT_KG"],
    )
    state["bagging_run"] = run_stage(
        api,
        lot_id,
        line_id,
        "BAGGING",
        TEST_DEFAULTS["BAGGING_OUTPUT_KG"],
        window_start=TEST_DEFAULTS["BAGGING_WINDOW_START"],
        window_end=TEST_DEFAULTS["BAGGING_WINDOW_END"],
        input_kg=TEST_DEFAULTS["SIZING_OUTPUT_KG"],
    )
    state["seed_lot"] = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


# ---------------------------------------------------------------------------
# Tier 5: sampling, tagging and settlement
# ---------------------------------------------------------------------------


def draw_sample(api: ApiClient, seed_lot_id: str, sampler_user_id: str | None = None, **overrides: Any) -> dict[str, Any]:
    headers = (
        make_certification_agency_headers(sampler_user_id)
        if sampler_user_id
        else make_certification_agency_headers()
    )
    return get_success_data(api.create_lot_sample(create_lot_sample_payload(seed_lot_id, **overrides), headers))


def post_results(api: ApiClient, lot_sample_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.post_lot_sample_results(
            lot_sample_id, lot_sample_results_payload(**overrides), make_certification_agency_headers()
        )
    )


def passed_lot_state(
    api: ApiClient,
    sample_overrides: dict[str, Any] | None = None,
    result_overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A BAGGED lot carried to PASSED by an initial sample and a passing result."""
    state = bagged_lot_state(api, **kwargs)
    state["sample"] = draw_sample(api, state["seed_lot"]["id"], **(sample_overrides or {}))
    state["sample"] = post_results(api, state["sample"]["id"], **(result_overrides or {}))
    state["seed_lot"] = get_success_data(
        api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers())
    )
    return state


def issue_tag(api: ApiClient, seed_lot_id: str, lot_sample_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_certification_tag(
            create_certification_tag_payload(seed_lot_id, lot_sample_id, **overrides),
            make_certification_agency_headers(),
        )
    )


def tagged_lot_state(api: ApiClient, tag_overrides: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """A PASSED lot with an ISSUED certification tag covering every bag."""
    state = passed_lot_state(api, **kwargs)
    state["tag"] = issue_tag(
        api, state["seed_lot"]["id"], state["sample"]["id"], **(tag_overrides or {})
    )
    state["seed_lot"] = get_success_data(
        api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers())
    )
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


def read_contract_version(api: ApiClient, production_contract_id: str) -> int:
    """Re-read the contract as the accountant would before pinning a version."""
    contract = get_success_data(
        api.get_production_contract(production_contract_id, make_settlement_accountant_headers())
    )
    return contract["version"]


def compute_settlement(
    api: ApiClient, production_contract_id: str, accountant_user_id: str | None = None, **overrides: Any
) -> dict[str, Any]:
    headers = (
        make_settlement_accountant_headers(accountant_user_id)
        if accountant_user_id
        else make_settlement_accountant_headers()
    )
    expected_version = overrides.pop("expected_contract_version", None)
    if expected_version is None:
        expected_version = read_contract_version(api, production_contract_id)
    return get_success_data(
        api.create_settlement(
            create_settlement_payload(production_contract_id, expected_version, **overrides), headers
        )
    )


def computed_settlement_state(api: ApiClient, **kwargs: Any) -> dict[str, Any]:
    """A TAGGED lot whose contract has one COMPUTED settlement."""
    state = tagged_lot_state(api, **kwargs)
    state["settlement"] = compute_settlement(api, state["contract"]["id"])
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


def approved_settlement_state(api: ApiClient, approver_user_id: str = "acct-2", **kwargs: Any) -> dict[str, Any]:
    """A COMPUTED settlement approved by a second accountant, so the contract is SETTLED."""
    state = computed_settlement_state(api, **kwargs)
    state["settlement"] = get_success_data(
        api.approve_settlement(
            state["settlement"]["id"], {}, make_settlement_accountant_headers(approver_user_id)
        )
    )
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


def paid_settlement_state(api: ApiClient, **kwargs: Any) -> dict[str, Any]:
    """An APPROVED settlement paid out, so the contract is CLOSED."""
    state = approved_settlement_state(api, **kwargs)
    state["settlement"] = get_success_data(
        api.pay_settlement(
            state["settlement"]["id"], pay_settlement_payload(), make_settlement_accountant_headers("acct-2")
        )
    )
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


def mint_carryover(api: ApiClient, seed_lot_id: str, expected_seed_lot_version: int, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_carryover(
            seed_lot_id,
            create_carryover_payload(expected_seed_lot_version, **overrides),
            make_conditioning_manager_headers(),
        )
    )
