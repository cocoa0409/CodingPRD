"""Reusable setup builders.

The harness restarts the API and empties its store before **every** test, so
nothing here caches state across tests: each function is a plain builder that
performs the PRD-declared calls needed to reach a given precondition and
returns the entity it created.  Builders only ever use endpoints the PRD
declares — there is no back door into the store.

Ordering matters in several places (a policy must be `ACTIVE` before a request
can name it; a pool must be created under its run; a run must be computed
before it can be published), so the builders compose in the same order the PRD
prose describes.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    AUGUST_END,
    AUGUST_FIFTH_UTC,
    DEFAULT_CLOCK_UTC,
    JULY_END,
    JULY_START,
)
from . import factories
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_1,
    OWNER_2,
    OWNER_4,
    make_business_unit_owner_headers,
    make_resource_owner_headers,
)

JsonDict = Dict[str, Any]


# ─── Logical clock ────────────────────────────────────────────────────────
def set_clock(api: ApiClient, current_utc: str = DEFAULT_CLOCK_UTC) -> None:
    """Pin the logical clock.  PlatformAdmin-only per PRD §2.5."""
    get_success_data(api.set_clock(current_utc, ADMIN_HEADERS))


# ─── Business units ───────────────────────────────────────────────────────
def create_business_unit(
    api: ApiClient,
    name: str = "Ops",
    cost_center_code: str = "CC-400",
    **overrides: Any,
) -> JsonDict:
    payload = factories.business_unit_payload(name, cost_center_code, **overrides)
    return get_success_data(api.create_business_unit(payload, ADMIN_HEADERS))


def create_chargeback_unit(
    api: ApiClient,
    name: str = "Ops",
    cost_center_code: str = "CC-400",
    headcount: int = 10,
    **overrides: Any,
) -> JsonDict:
    """A unit that may be charged back — PRD §3.5 gates publish on this flag."""
    return create_business_unit(
        api,
        name,
        cost_center_code,
        chargeback_enabled=True,
        headcount=headcount,
        **overrides,
    )


# ─── Tagging policies ─────────────────────────────────────────────────────
def create_policy(
    api: ApiClient,
    name: str = "Std",
    mandatory_dimensions: Optional[List[str]] = None,
    **overrides: Any,
) -> JsonDict:
    """Draft a policy as the analyst who will not be the one activating it."""
    payload = factories.tagging_policy_payload(name, mandatory_dimensions, **overrides)
    return get_success_data(api.create_tagging_policy(payload, ANALYST_HEADERS))


def create_active_policy(
    api: ApiClient,
    name: str = "Std",
    mandatory_dimensions: Optional[List[str]] = None,
    **overrides: Any,
) -> JsonDict:
    """Draft then activate a policy.

    PRD §3.2 separates the two duties, so the draft is filed by the analyst and
    the activation performed by the controller.
    """
    policy = create_policy(api, name, mandatory_dimensions, **overrides)
    return get_success_data(api.activate_tagging_policy(policy["id"], CONTROLLER_HEADERS))


# ─── Provisioning and resources ───────────────────────────────────────────
def create_provisioning_request(
    api: ApiClient,
    policy_id: str,
    business_unit_id: str,
    owner_user_id: str,
    **overrides: Any,
) -> JsonDict:
    payload = factories.provisioning_request_payload(
        policy_id, business_unit_id, owner_user_id, **overrides
    )
    return get_success_data(api.create_provisioning_request(payload, ANALYST_HEADERS))


def provision_resource(
    api: ApiClient,
    policy_id: str,
    business_unit_id: str,
    owner_user_id: str,
    **overrides: Any,
) -> JsonDict:
    """Carry a request all the way to a live cloud resource and return it.

    A resource has no creation endpoint of its own — PRD §3.3 says it is born
    as a cascade of provisioning — so it is discovered through the resource
    listing filtered by the originating request.
    """
    request = create_provisioning_request(
        api, policy_id, business_unit_id, owner_user_id, **overrides
    )
    get_success_data(api.approve_provisioning_request(request["id"], ANALYST_HEADERS))
    get_success_data(api.provision_provisioning_request(request["id"], ANALYST_HEADERS))
    rows = get_success_data(
        api.list_cloud_resources(ANALYST_HEADERS, {"provisioning_request_id": request["id"]})
    )
    assert rows, f"provisioning {request['id']} did not produce a cloud resource"
    return rows[0]


def set_utilization(
    api: ApiClient, resource_id: str, utilization_pct: float, **overrides: Any
) -> JsonDict:
    """Push observed telemetry.  PlatformAdmin-only per PRD §3.3."""
    payload: JsonDict = {"utilization_pct": utilization_pct}
    payload.update(overrides)
    return get_success_data(
        api.patch_cloud_resource_telemetry(resource_id, payload, ADMIN_HEADERS)
    )


# ─── Cost records ─────────────────────────────────────────────────────────
def create_cost_record(
    api: ApiClient,
    list_cost_cents: int,
    resource_kind: str = "STORAGE",
    billing_period_start: str = JULY_START,
    billing_period_end: str = JULY_END,
    cloud_resource_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload = factories.cost_record_payload(
        list_cost_cents,
        resource_kind,
        billing_period_start,
        billing_period_end,
        cloud_resource_id,
        **overrides,
    )
    return get_success_data(api.create_cost_record(payload, ADMIN_HEADERS))


def create_untagged_record(
    api: ApiClient, list_cost_cents: int, **overrides: Any
) -> JsonDict:
    """A record with no `cloud_resource_id` — untagged and unattributable."""
    return create_cost_record(api, list_cost_cents, **overrides)


# ─── Commitments ──────────────────────────────────────────────────────────
def create_commitment(api: ApiClient, **overrides: Any) -> JsonDict:
    payload = factories.commitment_payload(**overrides)
    return get_success_data(api.create_commitment(payload, CONTROLLER_HEADERS))


def create_active_commitment(api: ApiClient, **overrides: Any) -> JsonDict:
    commitment = create_commitment(api, **overrides)
    return get_success_data(api.activate_commitment(commitment["id"], CONTROLLER_HEADERS))


# ─── Runs, pools and lines ────────────────────────────────────────────────
def create_run(api: ApiClient, **overrides: Any) -> JsonDict:
    payload = factories.allocation_run_payload(**overrides)
    return get_success_data(api.create_allocation_run(payload, ANALYST_HEADERS))


def create_pool(
    api: ApiClient, run_id: str, participant_business_unit_ids: Iterable[str], **overrides: Any
) -> JsonDict:
    payload = factories.shared_cost_pool_payload(
        list(participant_business_unit_ids), **overrides
    )
    return get_success_data(api.create_shared_cost_pool(run_id, payload, ANALYST_HEADERS))


def absorb(api: ApiClient, pool_id: str, cost_record_ids: Iterable[str]) -> JsonDict:
    return get_success_data(
        api.absorb_untagged(pool_id, list(cost_record_ids), ANALYST_HEADERS)
    )


def seal(api: ApiClient, pool_id: str) -> JsonDict:
    return get_success_data(api.seal_shared_cost_pool(pool_id, ANALYST_HEADERS))


def compute(api: ApiClient, run_id: str, variant: str = "FINAL") -> JsonDict:
    return get_success_data(api.compute_allocation_run(run_id, variant, ANALYST_HEADERS))


def publish(api: ApiClient, run_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    return get_success_data(
        api.publish_allocation_run(run_id, headers if headers else CONTROLLER_HEADERS)
    )


def invoices_of_run(api: ApiClient, run_id: str) -> List[JsonDict]:
    return get_success_data(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )


def issue_invoice(api: ApiClient, invoice_id: str) -> JsonDict:
    return get_success_data(api.issue_invoice(invoice_id, CONTROLLER_HEADERS))


# ─── Composite chains ─────────────────────────────────────────────────────
def shared_pool_run(
    api: ApiClient,
    business_unit_ids: List[str],
    cost_record_ids: List[str],
    mode: str = "SHOWBACK",
    methodology: str = "EVEN_SPLIT",
    proportional_basis: Optional[str] = None,
    variant: str = "FINAL",
    do_seal: bool = True,
    do_compute: bool = True,
    **run_overrides: Any,
) -> Dict[str, JsonDict]:
    """Build a run whose only cost comes from a shared pool.

    Returns a dict with the `run` and `pool` as last read.  Sealing is optional
    because PRD §3.5 makes an unsealed pool a publish-time refusal, and some
    tests need to observe that.
    """
    run = create_run(api, mode=mode, **run_overrides)
    pool = create_pool(
        api,
        run["id"],
        business_unit_ids,
        methodology=methodology,
        proportional_basis=proportional_basis,
    )
    if cost_record_ids:
        pool = absorb(api, pool["id"], cost_record_ids)
    if do_seal:
        pool = seal(api, pool["id"])
    if do_compute:
        run = compute(api, run["id"], variant)
    return {"run": run, "pool": pool}


def issued_chargeback_invoice(
    api: ApiClient,
    business_unit_id: str,
    gross_cents: int,
    methodology: str = "PROPORTIONAL",
    proportional_basis: Optional[str] = "HEADCOUNT",
    **run_overrides: Any,
) -> Dict[str, JsonDict]:
    """Drive one untagged cost through a chargeback run to an ISSUED invoice.

    Returns the `run`, `pool`, `record` and `invoice`.  This is the precondition
    for every dispute and settlement path in PRD §3.6 and §3.7.
    """
    record = create_untagged_record(api, gross_cents)
    built = shared_pool_run(
        api,
        [business_unit_id],
        [record["id"]],
        mode="CHARGEBACK",
        methodology=methodology,
        proportional_basis=proportional_basis,
        **run_overrides,
    )
    run = publish(api, built["run"]["id"])
    invoice = invoices_of_run(api, run["id"])[0]
    invoice = issue_invoice(api, invoice["id"])
    return {"run": run, "pool": built["pool"], "record": record, "invoice": invoice}


def direct_cost_unit(
    api: ApiClient,
    name: str = "Ops BU",
    cost_center_code: str = "CC-400",
    headcount: int = 10,
    list_cost_cents: int = 10000,
    owner_user_id: str = OWNER_4,
    team: str = "ops",
    environment: str = "prod",
    application: str = "billing",
    monthly_run_rate_cents: Optional[int] = None,
    billing_period_start: str = JULY_START,
    billing_period_end: str = JULY_END,
    **unit_overrides: Any,
) -> Dict[str, JsonDict]:
    """A chargeback-enabled unit owning one fully tagged resource and one record.

    Returns the `unit`, `policy`, `resource` and `record`.  The record names the
    resource, so PRD §3.4 derives its `business_unit_id` and the record becomes
    *direct* spend rather than untagged spend awaiting absorption.
    """
    unit = create_chargeback_unit(
        api, name, cost_center_code, headcount=headcount, **unit_overrides
    )
    policy = create_active_policy(api, "core-tags")
    resource = provision_resource(
        api,
        policy["id"],
        unit["id"],
        owner_user_id,
        resource_kind="COMPUTE",
        requested_tags={"team": team, "environment": environment, "application": application},
        monthly_run_rate_cents=(
            list_cost_cents if monthly_run_rate_cents is None else monthly_run_rate_cents
        ),
    )
    record = create_cost_record(
        api,
        list_cost_cents,
        resource_kind="COMPUTE",
        billing_period_start=billing_period_start,
        billing_period_end=billing_period_end,
        cloud_resource_id=resource["id"],
    )
    return {"unit": unit, "policy": policy, "resource": resource, "record": record}


def direct_chargeback_invoice(
    api: ApiClient,
    list_cost_cents: int = 10000,
    issue: bool = True,
    **unit_overrides: Any,
) -> Dict[str, JsonDict]:
    """Drive one *direct* cost through a chargeback run to an issued invoice.

    Adds the `run` and the `invoice` to what :func:`direct_cost_unit` returns.
    The run is opened by the analyst and published by the controller because
    PRD §3.6 makes publication a separated duty.
    """
    built = direct_cost_unit(api, list_cost_cents=list_cost_cents, **unit_overrides)
    run = create_run(api, mode="CHARGEBACK")
    run = compute(api, run["id"], "FINAL")
    run = publish(api, run["id"])
    invoice = invoices_of_run(api, run["id"])[0]
    if issue:
        invoice = issue_invoice(api, invoice["id"])
    built.update({"run": run, "invoice": invoice})
    return built


def discounted_compute_model(
    api: ApiClient,
    clock: str = AUGUST_FIFTH_UTC,
    utilizations: Optional[List[float]] = None,
    activate: bool = True,
    untagged_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Two units, three 10100-cent July COMPUTE records and one savings plan.

    Platform BU owns the first two resources (run rates 1000000 and 30000) and
    Data BU the third (30000); every resource is fully tagged under a `BLOCKING`
    policy.  The plan's term encloses July, so all three records are candidates
    for its coverage waterfall.  Pass `utilizations` to report telemetry on the
    three resources in order, `activate=False` to leave the plan `PENDING`, and
    `untagged_cents` to add one resource-less storage record as untagged spend.

    Returns the `platform` and `data` units, the `policy`, the `resources` and
    `records` in creation order, the `commitment`, and `untagged` when asked for.
    """
    set_clock(api, clock)
    platform = create_chargeback_unit(api, "Platform BU", "CC-100", headcount=40)
    data = create_chargeback_unit(api, "Data BU", "CC-200", headcount=10)
    policy = create_active_policy(api, "core-tags", enforcement_mode="BLOCKING")

    specs = (
        (platform, OWNER_1, {"team": "platform", "environment": "dev", "application": "api"}, 1000000),
        (platform, OWNER_1, {"team": "platform", "environment": "prod", "application": "api"}, 30000),
        (data, OWNER_2, {"team": "data", "environment": "prod", "application": "etl"}, 30000),
    )
    resources: List[JsonDict] = []
    for unit, owner, tags, run_rate in specs:
        resources.append(
            provision_resource(
                api,
                policy["id"],
                unit["id"],
                owner,
                resource_kind="COMPUTE",
                requested_tags=tags,
                monthly_run_rate_cents=run_rate,
            )
        )
    if utilizations:
        for resource, utilization_pct in zip(resources, utilizations):
            set_utilization(api, resource["id"], utilization_pct)

    records = [
        create_cost_record(api, 10100, resource_kind="COMPUTE", cloud_resource_id=resource["id"])
        for resource in resources
    ]
    untagged = create_untagged_record(api, untagged_cents) if untagged_cents else None

    purchase = create_active_commitment if activate else create_commitment
    commitment = purchase(
        api,
        commitment_type="SAVINGS_PLAN",
        covered_resource_kind=None,
        term_start="2026-06-30T00:00:00Z",
        term_end=AUGUST_END,
        hourly_commit_cents=50,
        coverage_target_pct=80.00,
        utilization_target_pct=80.00,
    )

    return {
        "platform": platform,
        "data": data,
        "policy": policy,
        "resources": resources,
        "records": records,
        "untagged": untagged,
        "commitment": commitment,
    }


def headcount_pool_chargeback_run(
    api: ApiClient,
    participant_business_unit_ids: List[str],
    cost_record_ids: List[str],
    variant: str = "FINAL",
) -> Dict[str, JsonDict]:
    """A CHARGEBACK run whose sealed pool splits untagged spend by headcount."""
    run = create_run(api, mode="CHARGEBACK")
    pool = create_pool(
        api,
        run["id"],
        participant_business_unit_ids,
        name="untagged-absorption",
        methodology="PROPORTIONAL",
        proportional_basis="HEADCOUNT",
    )
    if cost_record_ids:
        pool = absorb(api, pool["id"], cost_record_ids)
    pool = seal(api, pool["id"])
    if variant:
        run = compute(api, run["id"], variant)
    return {"run": run, "pool": pool}


def file_dispute(
    api: ApiClient, invoice: JsonDict, **overrides: Any
) -> JsonDict:
    """File a dispute as the billed unit's owner.

    PRD §2.1 makes the owner's `X-User-ID` the business unit's own id, so the
    filing identity is derived from the invoice being disputed.
    """
    payload = factories.dispute_payload(invoice["id"], **overrides)
    headers = make_business_unit_owner_headers(invoice["business_unit_id"])
    return get_success_data(api.create_dispute(payload, headers))


def create_budget(api: ApiClient, business_unit_id: str, **overrides: Any) -> JsonDict:
    payload = factories.budget_payload(business_unit_id, **overrides)
    return get_success_data(api.create_budget(payload, CONTROLLER_HEADERS))


def create_active_budget(api: ApiClient, business_unit_id: str, **overrides: Any) -> JsonDict:
    budget = create_budget(api, business_unit_id, **overrides)
    return get_success_data(api.activate_budget(budget["id"], CONTROLLER_HEADERS))


def flag_idle_resource(
    api: ApiClient,
    business_unit_id: str,
    policy_id: str,
    owner_user_id: str,
    utilization_pct: float,
    monthly_run_rate_cents: int,
    **request_overrides: Any,
) -> Dict[str, JsonDict]:
    """Provision a resource, report low utilization, and scan it into a task.

    Returns the `resource` and the `task` the idle-detection scan proposed.
    PRD §3.8 gives tasks no direct creation path from a scan, so the task is
    read back from the scan's own response.
    """
    resource = provision_resource(
        api,
        policy_id,
        business_unit_id,
        owner_user_id,
        monthly_run_rate_cents=monthly_run_rate_cents,
        **request_overrides,
    )
    set_utilization(api, resource["id"], utilization_pct)
    tasks = get_success_data(
        api.run_idle_detection_scan({"business_unit_id": business_unit_id}, ANALYST_HEADERS)
    )
    assert tasks, "idle-detection scan proposed no task for the flagged resource"
    return {"resource": resource, "task": tasks[0]}


def notified_remediation_task(
    api: ApiClient, task_id: str
) -> JsonDict:
    """Open the 72-hour owner window on a proposed task (PRD §3.8)."""
    return get_success_data(api.notify_owner(task_id, ANALYST_HEADERS))


def owner_headers_for_resource(resource: JsonDict) -> Dict[str, str]:
    return make_resource_owner_headers(resource["owner_user_id"])
