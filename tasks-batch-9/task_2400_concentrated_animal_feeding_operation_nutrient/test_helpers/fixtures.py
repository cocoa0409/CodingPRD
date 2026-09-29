"""State builders.

Every test starts against an empty database, so all state is composed here
from the API's own endpoints. Two layers are offered:

* granular helpers (``register_operation``, ``cover_permit``, ``add_budget`` …)
  that each perform one call and return the created record; and
* ``setup_scenario()``, which walks the canonical chain
  ``OPERATION → STORAGE → COVERED → LAND_BASE → DRAFT_PLAN → BUDGET →
  CERTIFIED → SUBMITTED → APPROVED`` and stops at the requested stage,
  accepting per-entity payload overrides.
"""

from prd_bench_local_runner.testing import validate_success

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    annual_report_payload,
    application_event_payload,
    budget_payload,
    conduct_payload,
    field_payload,
    hauler_payload,
    incident_payload,
    inspection_payload,
    intake_payload,
    operation_payload,
    permit_payload,
    plan_payload,
    soil_test_payload,
    storage_inspection_payload,
    storage_payload,
    transfer_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    make_hauler_headers,
    make_operator_headers,
)

# Ordered stages of the canonical chain.
STAGES = (
    "OPERATION",
    "STORAGE",
    "COVERED",
    "LAND_BASE",
    "DRAFT_PLAN",
    "BUDGET",
    "CERTIFIED",
    "SUBMITTED",
    "APPROVED",
)


def _created(response) -> dict:
    return validate_success(response, 201)


def _ok(response) -> dict:
    return validate_success(response, 200)


def _stage_at_least(stage: str, target: str) -> bool:
    return STAGES.index(stage) >= STAGES.index(target)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock and return the checkpoint summary."""
    return _ok(api_client.set_clock(to_iso8601, headers or ADMIN_HEADERS))


def reset_clock(headers=None) -> dict:
    return set_clock(CLOCK_DEFAULT, headers)


# ---------------------------------------------------------------------------
# Granular builders
# ---------------------------------------------------------------------------
def register_operation(headers=None, **overrides) -> dict:
    return _created(
        api_client.create_operation(
            operation_payload(**overrides), headers or ADMIN_HEADERS
        )
    )


def register_hauler(headers=None, **overrides) -> dict:
    return _created(
        api_client.create_hauler(hauler_payload(**overrides), headers or ADMIN_HEADERS)
    )


def register_storage(operation_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_manure_storage(
            storage_payload(operation_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


def record_intake(operation_id: str, storage_id: str, gallons=1000000, headers=None) -> dict:
    return _ok(
        api_client.record_storage_intake(
            storage_id,
            intake_payload(gallons),
            headers or make_operator_headers(operation_id),
        )
    )


def draft_permit(operation_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_permit(
            permit_payload(operation_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


def submit_permit(operation_id: str, permit_id: str, headers=None) -> dict:
    return _ok(
        api_client.submit_permit(
            permit_id, headers or make_operator_headers(operation_id)
        )
    )


def issue_coverage(permit_id: str, headers=None) -> dict:
    return _ok(api_client.issue_permit_coverage(permit_id, headers or REVIEWER_HEADERS))


def cover_permit(operation_id: str, operator_headers=None, reviewer_headers=None, **overrides) -> dict:
    """Draft, submit and issue coverage in one go; returns the COVERED permit."""
    permit = draft_permit(operation_id, operator_headers, **overrides)
    submit_permit(operation_id, permit["id"], operator_headers)
    return issue_coverage(permit["id"], reviewer_headers)


def register_field(operation_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_field(
            field_payload(operation_id, **overrides), headers or PLANNER_HEADERS
        )
    )


def file_soil_test(field_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_soil_test(
            soil_test_payload(field_id, **overrides), headers or PLANNER_HEADERS
        )
    )


def operation_version(operation_id: str, headers=None) -> int:
    """Current ``version`` of the operation, for the plan-create OCC token."""
    operation = _ok(
        api_client.get_operation(operation_id, headers or make_operator_headers(operation_id))
    )
    return operation["version"]


def create_plan(operation_id: str, permit_id: str, headers=None, **overrides) -> dict:
    """Create a plan, reading the operation's current version for the OCC token."""
    overrides.setdefault(
        "expected_operation_version", operation_version(operation_id)
    )
    expected = overrides.pop("expected_operation_version")
    return _created(
        api_client.create_nutrient_plan(
            plan_payload(operation_id, permit_id, expected, **overrides),
            headers or PLANNER_HEADERS,
        )
    )


def add_budget(plan_id: str, field_id: str, soil_test_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_field_budget(
            budget_payload(plan_id, field_id, soil_test_id, **overrides),
            headers or PLANNER_HEADERS,
        )
    )


def certify_plan(plan_id: str, headers=None) -> dict:
    return _ok(api_client.certify_nutrient_plan(plan_id, headers or PLANNER_HEADERS))


def submit_plan(operation_id: str, plan_id: str, headers=None) -> dict:
    return _ok(
        api_client.submit_nutrient_plan(
            plan_id, headers or make_operator_headers(operation_id)
        )
    )


def approve_plan(plan_id: str, headers=None) -> dict:
    return _ok(api_client.approve_nutrient_plan(plan_id, headers or REVIEWER_HEADERS))


def file_storage_inspection(operation_id: str, storage_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_storage_inspection(
            storage_inspection_payload(storage_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


def record_application(
    operation_id: str, plan_id: str, budget_id: str, storage_id: str, headers=None, **overrides
) -> dict:
    return _created(
        api_client.create_application_event(
            application_event_payload(plan_id, budget_id, storage_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


def initiate_transfer(
    operation_id: str, storage_id: str, hauler_id: str, headers=None, **overrides
) -> dict:
    return _created(
        api_client.create_manure_transfer(
            transfer_payload(operation_id, storage_id, hauler_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


def acknowledge_transfer(hauler_id: str, transfer_id: str, headers=None) -> dict:
    return _ok(
        api_client.acknowledge_manure_transfer(
            transfer_id, headers or make_hauler_headers(hauler_id)
        )
    )


def file_incident(operation_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_incident_report(
            incident_payload(operation_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


def schedule_inspection(operation_id: str, permit_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_inspection(
            inspection_payload(operation_id, permit_id, **overrides),
            headers or REVIEWER_HEADERS,
        )
    )


def conduct_inspection(inspection_id: str, findings_count=1, headers=None, **overrides) -> dict:
    return _ok(
        api_client.conduct_inspection(
            inspection_id,
            conduct_payload(findings_count, **overrides),
            headers or REVIEWER_HEADERS,
        )
    )


def open_annual_report(operation_id: str, plan_id: str, headers=None, **overrides) -> dict:
    return _created(
        api_client.create_annual_report(
            annual_report_payload(operation_id, plan_id, **overrides),
            headers or make_operator_headers(operation_id),
        )
    )


# ---------------------------------------------------------------------------
# Composite chain
# ---------------------------------------------------------------------------
def setup_scenario(
    stage: str = "APPROVED",
    operation=None,
    storage=None,
    permit=None,
    field=None,
    soil_test=None,
    plan=None,
    budget=None,
    intake_gallons=None,
    with_hauler=False,
    hauler=None,
    planner_headers=None,
    reviewer_headers=None,
) -> dict:
    """Build the canonical operation up to ``stage``.

    ``operation``/``storage``/``permit``/``field``/``soil_test``/``plan``/
    ``budget`` each take a dict of payload overrides for that entity.
    ``intake_gallons`` records an intake once the chain is complete.
    Returns a dict keyed by entity name plus the role headers in play; every
    record is the freshest response body seen for it.
    """
    assert stage in STAGES, f"unknown stage {stage}"
    planner_headers = planner_headers or PLANNER_HEADERS
    reviewer_headers = reviewer_headers or REVIEWER_HEADERS

    ctx = {
        "planner_headers": planner_headers,
        "reviewer_headers": reviewer_headers,
        "admin_headers": ADMIN_HEADERS,
    }

    ctx["operation"] = register_operation(**(operation or {}))
    operation_id = ctx["operation"]["id"]
    operator_headers = make_operator_headers(operation_id)
    ctx["operator_headers"] = operator_headers

    if with_hauler or hauler:
        ctx["hauler"] = register_hauler(**(hauler or {}))
        ctx["hauler_headers"] = make_hauler_headers(ctx["hauler"]["id"])

    if _stage_at_least(stage, "STORAGE"):
        ctx["storage"] = register_storage(
            operation_id, operator_headers, **(storage or {})
        )

    if _stage_at_least(stage, "COVERED"):
        ctx["permit"] = cover_permit(
            operation_id, operator_headers, reviewer_headers, **(permit or {})
        )

    if _stage_at_least(stage, "LAND_BASE"):
        ctx["field"] = register_field(operation_id, planner_headers, **(field or {}))
        ctx["soil_test"] = file_soil_test(
            ctx["field"]["id"], planner_headers, **(soil_test or {})
        )

    if _stage_at_least(stage, "DRAFT_PLAN"):
        ctx["plan"] = create_plan(
            operation_id, ctx["permit"]["id"], planner_headers, **(plan or {})
        )

    if _stage_at_least(stage, "BUDGET"):
        ctx["budget"] = add_budget(
            ctx["plan"]["id"],
            ctx["field"]["id"],
            ctx["soil_test"]["id"],
            planner_headers,
            **(budget or {}),
        )

    if _stage_at_least(stage, "CERTIFIED"):
        ctx["plan"] = certify_plan(ctx["plan"]["id"], planner_headers)

    if _stage_at_least(stage, "SUBMITTED"):
        ctx["plan"] = submit_plan(operation_id, ctx["plan"]["id"], operator_headers)

    if _stage_at_least(stage, "APPROVED"):
        ctx["plan"] = approve_plan(ctx["plan"]["id"], reviewer_headers)

    if intake_gallons is not None:
        ctx["storage"] = record_intake(
            operation_id, ctx["storage"]["id"], intake_gallons, operator_headers
        )

    return ctx


def setup_ready_operation(**kwargs) -> dict:
    """Approved plan, an active budget and a million gallons in the lagoon —
    the minimum state in which a land application may be recorded."""
    kwargs.setdefault("intake_gallons", 1000000)
    return setup_scenario("APPROVED", **kwargs)


def setup_committed_transfer(gallons=200000, **kwargs) -> dict:
    """A ready operation plus an INITIATED transfer holding a commitment."""
    ctx = setup_ready_operation(with_hauler=True, **kwargs)
    ctx["transfer"] = initiate_transfer(
        ctx["operation"]["id"],
        ctx["storage"]["id"],
        ctx["hauler"]["id"],
        ctx["operator_headers"],
        gallons_transferred=gallons,
    )
    return ctx


def setup_conducted_inspection(findings_count=1, **kwargs) -> dict:
    """A ready operation with an inspection already conducted against its permit."""
    ctx = setup_ready_operation(**kwargs)
    ctx["inspection"] = schedule_inspection(
        ctx["operation"]["id"], ctx["permit"]["id"], ctx["reviewer_headers"]
    )
    ctx["inspection"] = conduct_inspection(
        ctx["inspection"]["id"], findings_count, ctx["reviewer_headers"]
    )
    return ctx
