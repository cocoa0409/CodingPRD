"""Composite setup helpers and pytest fixtures.

Tier 1 is the client and the logical clock, tier 2 creates single entities,
tier 3 drives one order along the two status dimensions of PRD 2.6, tier 4
builds the multi-entity graphs (bay + FAT + report + label + release) and
tier 5 runs the whole order lifecycle through to fulfillment CLOSED.

Every helper uses ``get_success_data`` so that a setup step which the PRD
allows to answer 200 or 201 does not itself become an assertion.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    DISPOSITION_APPROVED,
    ESCALATION_CLAUSE_EXEMPT_BELOW_CENTS,
)
from .factories import (
    commissioning_job_payload,
    compliance_label_payload,
    component_allocation_payload,
    disposition_payload,
    engineered_order_payload,
    escalation_clause_payload,
    factory_acceptance_test_payload,
    long_lead_component_payload,
    punch_list_item_payload,
    shipment_release_payload,
    submittal_drawing_payload,
    supplier_payload,
    test_bay_payload,
    test_report_payload,
    witness_party_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER,
    CONTRACT_ADMIN,
    CUSTOMER_REVIEWER,
    DESIGN_ENGINEER,
    FIELD_SERVICE_ENGINEER,
    LOGISTICS_COORDINATOR,
    LOGISTICS_COORDINATOR as LOGISTICS,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    TEST_ENGINEER,
    USER_COMPLIANCE_1,
    USER_DESIGN_1,
    USER_FIELD_1,
    USER_FIELD_2,
    USER_QUALITY_1,
    USER_REVIEWER_1,
    USER_TEST_ENGINEER,
    WITNESS_COORDINATOR,
    make_headers,
)
from .constants import ROLE_QUALITY_ENGINEER

Json = Dict[str, Any]


# =========================================================================
# Tier 1 - client and logical clock
# =========================================================================
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()


def set_clock(api: ApiClient, current_utc: str) -> Json:
    """PRD 2.10: drive every temporal rule through the logical clock."""
    return get_success_data(api.set_clock(current_utc, PLANT_ADMIN))


# =========================================================================
# Tier 2 - single entities
# =========================================================================
def create_order(api: ApiClient, **overrides) -> Json:
    return get_success_data(
        api.create_engineered_order(engineered_order_payload(**overrides), CONTRACT_ADMIN)
    )


def read_order(api: ApiClient, order_id: str) -> Json:
    return get_success_data(api.get_engineered_order(order_id, CONTRACT_ADMIN))


def order_version(api: ApiClient, order_id: str) -> int:
    return read_order(api, order_id)["version"]


def create_supplier(api: ApiClient, **overrides) -> Json:
    return get_success_data(api.create_supplier(supplier_payload(**overrides), PLANT_ADMIN))


def create_component(api: ApiClient, supplier_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_long_lead_component(
            supplier_id, long_lead_component_payload(**overrides), MATERIALS_PLANNER
        )
    )


def read_component(api: ApiClient, component_id: str) -> Json:
    return get_success_data(api.get_long_lead_component(component_id, MATERIALS_PLANNER))


def create_bay(api: ApiClient, **overrides) -> Json:
    return get_success_data(api.create_test_bay(test_bay_payload(**overrides), PLANT_ADMIN))


def read_bay(api: ApiClient, bay_id: str) -> Json:
    return get_success_data(api.get_test_bay(bay_id, PLANT_ADMIN))


def create_witness_party(api: ApiClient, **overrides) -> Json:
    return get_success_data(
        api.create_witness_party(witness_party_payload(**overrides), WITNESS_COORDINATOR)
    )


def create_supplier_and_component(
    api: ApiClient, supplier_overrides: Optional[Json] = None, **component_overrides
):
    """Convenience pair: a supplier plus one part beneath it."""
    supplier = create_supplier(api, **(supplier_overrides or {}))
    component = create_component(api, supplier["id"], **component_overrides)
    return supplier, component


# =========================================================================
# Tier 3 - one order along the engineering and fulfillment dimensions
# =========================================================================
def attach_escalation_clause(api: ApiClient, order_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_escalation_clause(
            order_id, escalation_clause_payload(**overrides), CONTRACT_ADMIN
        )
    )


def ensure_release_precondition(api: ApiClient, order: Json) -> None:
    """PRD 3.2: design release requires "either the order already has an
    escalation clause attached, or its contract_value_cents is below five
    million cents"."""
    if order["contract_value_cents"] >= ESCALATION_CLAUSE_EXEMPT_BELOW_CENTS:
        existing, _ = _list(api.list_order_escalation_clauses(order["id"], CONTRACT_ADMIN))
        if not existing:
            attach_escalation_clause(
                api,
                order["id"],
                escalatable_base_cents=0,
                copper_weight_bp=10000,
                aluminum_weight_bp=0,
                core_steel_weight_bp=0,
            )


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


def create_drawing(
    api: ApiClient,
    order_id: str,
    drawing_set_code: str = "DS-A",
    authored_by_user_id: str = USER_DESIGN_1,
    expected_version: Optional[int] = None,
) -> Json:
    version = (
        expected_version if expected_version is not None else order_version(api, order_id)
    )
    return get_success_data(
        api.create_submittal_drawing(
            order_id,
            submittal_drawing_payload(
                version,
                drawing_set_code=drawing_set_code,
                authored_by_user_id=authored_by_user_id,
            ),
            DESIGN_ENGINEER,
        )
    )


def submit_drawing(api: ApiClient, drawing_id: str) -> Json:
    return get_success_data(api.submit_drawing(drawing_id, {}, DESIGN_ENGINEER))


def begin_review(api: ApiClient, drawing_id: str) -> Json:
    return get_success_data(api.begin_review_drawing(drawing_id, {}, CUSTOMER_REVIEWER))


def disposition(
    api: ApiClient,
    drawing_id: str,
    verdict: str = DISPOSITION_APPROVED,
    reviewed_by_user_id: str = USER_REVIEWER_1,
    **extra,
) -> Json:
    return get_success_data(
        api.disposition_drawing(
            drawing_id,
            disposition_payload(verdict, reviewed_by_user_id, **extra),
            make_headers(reviewed_by_user_id, "CustomerReviewer"),
        )
    )


def release_design(
    api: ApiClient,
    order: Json,
    drawing_set_code: str = "DS-A",
    authored_by_user_id: str = USER_DESIGN_1,
    reviewed_by_user_id: str = USER_REVIEWER_1,
    verdict: str = DISPOSITION_APPROVED,
    **disposition_extra,
) -> Json:
    """Drive engineering ENG_OPEN -> DESIGN_RELEASED and return the drawing."""
    ensure_release_precondition(api, order)
    drawing = create_drawing(
        api, order["id"], drawing_set_code, authored_by_user_id
    )
    submit_drawing(api, drawing["id"])
    begin_review(api, drawing["id"])
    return disposition(
        api, drawing["id"], verdict, reviewed_by_user_id, **disposition_extra
    )


def create_allocation(
    api: ApiClient, component_id: str, order_id: str, **overrides
) -> Json:
    version = overrides.pop(
        "expected_component_version", read_component(api, component_id)["version"]
    )
    return get_success_data(
        api.create_component_allocation(
            component_allocation_payload(component_id, order_id, version, **overrides),
            MATERIALS_PLANNER,
        )
    )


def commit_allocation(api: ApiClient, allocation_id: str) -> Json:
    return get_success_data(
        api.commit_component_allocation(allocation_id, {}, MATERIALS_PLANNER)
    )


def start_production(api: ApiClient, order_id: str) -> Json:
    return get_success_data(api.start_production(order_id, {}, MATERIALS_PLANNER))


def drive_order_to_in_production(
    api: ApiClient,
    order: Json,
    component_id: str,
    quantity: int = 2,
    priority_class: int = 2,
    need_by_date: str = "2026-12-01T00:00:00Z",
    drawing_set_code: str = "DS-A",
) -> Json:
    """PRD 3.1: material allocation plus a released design open production."""
    drawing = release_design(api, order, drawing_set_code=drawing_set_code)
    allocation = create_allocation(
        api,
        component_id,
        order["id"],
        quantity=quantity,
        priority_class=priority_class,
        need_by_date=need_by_date,
    )
    commit_allocation(api, allocation["id"])
    start_production(api, order["id"])
    return {"drawing": drawing, "allocation": allocation}


# =========================================================================
# Tier 4 - test bay, FAT, report and label graphs
# =========================================================================
def create_fat(api: ApiClient, order_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_factory_acceptance_test(
            factory_acceptance_test_payload(order_id, **overrides), TEST_ENGINEER
        )
    )


def schedule_fat(api: ApiClient, fat_id: str, bay_id: str, window_start_at: str) -> Json:
    return get_success_data(
        api.schedule_factory_acceptance_test(
            fat_id,
            {"test_bay_id": bay_id, "window_start_at": window_start_at},
            TEST_ENGINEER,
        )
    )


def start_fat(api: ApiClient, fat_id: str, run_by_user_id: str = USER_TEST_ENGINEER):
    return get_success_data(
        api.start_factory_acceptance_test(
            fat_id, {"run_by_user_id": run_by_user_id}, TEST_ENGINEER
        )
    )


def create_report(api: ApiClient, fat_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_test_report(fat_id, test_report_payload(**overrides), TEST_ENGINEER)
    )


def issue_report(
    api: ApiClient, report_id: str, run_by_user_id: str = USER_TEST_ENGINEER
) -> Json:
    """PRD 3.6: the issuing QualityEngineer's identifier "must equal the parent
    test's run_by_user_id"."""
    return get_success_data(
        api.issue_test_report(
            report_id, {}, make_headers(run_by_user_id, ROLE_QUALITY_ENGINEER)
        )
    )


def conclude_fat(api: ApiClient, fat_id: str, result: str = "PASS") -> Json:
    return get_success_data(
        api.conclude_factory_acceptance_test(fat_id, {"result": result}, TEST_ENGINEER)
    )


def run_fat_to_conclusion(
    api: ApiClient,
    order_id: str,
    bay_id: str,
    window_start_at: str,
    start_clock_at: str,
    result: str = "PASS",
    run_by_user_id: str = USER_TEST_ENGINEER,
    fat_overrides: Optional[Json] = None,
    report_overrides: Optional[Json] = None,
) -> Json:
    """Request, schedule, start, measure, issue and conclude one FAT."""
    fat = create_fat(api, order_id, **(fat_overrides or {}))
    schedule_fat(api, fat["id"], bay_id, window_start_at)
    set_clock(api, start_clock_at)
    start_fat(api, fat["id"], run_by_user_id)
    report = create_report(api, fat["id"], **(report_overrides or {}))
    issue_report(api, report["id"], run_by_user_id)
    concluded = conclude_fat(api, fat["id"], result)
    return {"fat": concluded, "report": report}


def create_label(
    api: ApiClient,
    order_id: str,
    drawing_id: str,
    report_id: str,
    generated_by_user_id: str = USER_COMPLIANCE_1,
    expected_version: Optional[int] = None,
) -> Json:
    version = (
        expected_version if expected_version is not None else order_version(api, order_id)
    )
    return get_success_data(
        api.create_compliance_label(
            order_id,
            compliance_label_payload(
                drawing_id,
                report_id,
                version,
                generated_by_user_id=generated_by_user_id,
            ),
            make_headers(generated_by_user_id, "ComplianceOfficer"),
        )
    )


def issue_label(
    api: ApiClient,
    order_id: str,
    drawing_id: str,
    report_id: str,
    generated_by_user_id: str = USER_COMPLIANCE_1,
    verified_by_user_id: str = USER_QUALITY_1,
) -> Json:
    """PRD 3.6: DRAFT -> GENERATED -> VERIFIED -> ISSUED, with a verifier that
    differs from both the generator and the drawing's author."""
    label = create_label(
        api, order_id, drawing_id, report_id, generated_by_user_id
    )
    get_success_data(
        api.generate_compliance_label(
            label["id"], {}, make_headers(generated_by_user_id, "ComplianceOfficer")
        )
    )
    get_success_data(
        api.verify_compliance_label(
            label["id"],
            {"verified_by_user_id": verified_by_user_id},
            make_headers(verified_by_user_id, ROLE_QUALITY_ENGINEER),
        )
    )
    return get_success_data(
        api.issue_compliance_label(
            label["id"], {}, make_headers(generated_by_user_id, "ComplianceOfficer")
        )
    )


# =========================================================================
# Tier 5 - the whole order lifecycle
# =========================================================================
def create_release(api: ApiClient, order_id: str, **overrides) -> Json:
    version = overrides.pop(
        "expected_engineered_order_version", order_version(api, order_id)
    )
    return get_success_data(
        api.create_shipment_release(
            order_id, shipment_release_payload(version, **overrides), LOGISTICS
        )
    )


def deliver_release(
    api: ApiClient, release_id: str, carrier_reference: str = "CR-0001"
) -> Json:
    get_success_data(api.clear_shipment_release(release_id, {}, LOGISTICS))
    get_success_data(api.stage_shipment_release(release_id, {}, LOGISTICS))
    get_success_data(
        api.ship_shipment_release(
            release_id, {"carrier_reference": carrier_reference}, LOGISTICS
        )
    )
    return get_success_data(api.deliver_shipment_release(release_id, {}, LOGISTICS))


def create_job(api: ApiClient, order_id: str, release_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_commissioning_job(
            order_id,
            commissioning_job_payload(release_id, **overrides),
            FIELD_SERVICE_ENGINEER,
        )
    )


def energize_job(api: ApiClient, job_id: str, energize_clock_at: str) -> Json:
    """SCHEDULED -> MOBILIZED -> ENERGIZATION_PENDING -> PUNCH_OPEN."""
    get_success_data(
        api.mobilize_commissioning_job(job_id, {}, FIELD_SERVICE_ENGINEER)
    )
    get_success_data(api.request_energization(job_id, {}, FIELD_SERVICE_ENGINEER))
    set_clock(api, energize_clock_at)
    return get_success_data(
        api.energize_commissioning_job(job_id, {}, FIELD_SERVICE_ENGINEER)
    )


def complete_job_through_one_punch_item(api: ApiClient, job_id: str) -> Json:
    """PRD 3.8: the job re-evaluates itself after every punch item change, so a
    single raised-then-closed item carries PUNCH_OPEN to COMPLETE."""
    item = get_success_data(
        api.create_punch_list_item(
            job_id, punch_list_item_payload(), FIELD_SERVICE_ENGINEER
        )
    )
    get_success_data(
        api.assign_punch_list_item(
            item["id"], {"assigned_to_user_id": USER_FIELD_2}, FIELD_SERVICE_ENGINEER
        )
    )
    get_success_data(
        api.resolve_punch_list_item(
            item["id"], {"resolved_by_user_id": USER_FIELD_2}, FIELD_SERVICE_ENGINEER
        )
    )
    get_success_data(
        api.close_punch_list_item(
            item["id"], {"closed_by_user_id": USER_QUALITY_1}, QUALITY_ENGINEER
        )
    )
    return get_success_data(api.get_commissioning_job(job_id, FIELD_SERVICE_ENGINEER))


def drive_order_to_closed(
    api: ApiClient,
    order: Json,
    component_id: str,
    bay_id: str,
    fat_window_start_at: str,
    fat_start_clock_at: str,
    mobilization_at: str,
    energize_clock_at: str,
    quantity: int = 2,
    need_by_date: str = "2026-12-01T00:00:00Z",
    carrier_reference: str = "CR-0001",
) -> Json:
    """The full pipeline of PRD 3.1 through 3.8: design released, material
    committed, production started, FAT passed, label issued, stage delivered,
    commissioning complete and fulfillment CLOSED."""
    material = drive_order_to_in_production(
        api, order, component_id, quantity=quantity, need_by_date=need_by_date
    )
    fat_result = run_fat_to_conclusion(
        api,
        order["id"],
        bay_id,
        fat_window_start_at,
        fat_start_clock_at,
        result="PASS",
        fat_overrides={"witness_required": False},
    )
    label = issue_label(
        api, order["id"], material["drawing"]["id"], fat_result["report"]["id"]
    )
    release = create_release(api, order["id"])
    deliver_release(api, release["id"], carrier_reference)
    job = create_job(
        api, order["id"], release["id"], mobilization_at=mobilization_at
    )
    set_clock(api, mobilization_at)
    energize_job(api, job["id"], energize_clock_at)
    job = complete_job_through_one_punch_item(api, job["id"])
    return {
        "order": read_order(api, order["id"]),
        "drawing": material["drawing"],
        "allocation": material["allocation"],
        "fat": fat_result["fat"],
        "report": fat_result["report"],
        "label": label,
        "release": release,
        "job": job,
    }
