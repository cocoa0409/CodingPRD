"""Composite state builders.

The harness restarts the API server before every individual test, so every
builder below constructs its state from scratch through PRD-declared
endpoints only. Each builder returns plain dictionaries so tests can read the
identifiers and versions they need.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import ADMIN_HEADERS, EPA_HEADERS, PM_HEADERS, QA_HEADERS, TECH_HEADERS

CANONICAL_CLOCK = "2026-01-05T00:00:00Z"


class Env:
    """A mutable bag of identifiers for one built-up scenario."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.pollutant_id: Optional[str] = None
        self.method_id: Optional[str] = None
        self.network_id: Optional[str] = None
        self.site_id: Optional[str] = None
        self.monitor_id: Optional[str] = None
        self.batches: List[Dict[str, Any]] = []
        self.demonstration_id: Optional[str] = None
        self.exclusion_id: Optional[str] = None
        self.package_id: Optional[str] = None
        self.assessment_id: Optional[str] = None
        self.change_request_id: Optional[str] = None
        self.design_value_id: Optional[str] = None

    # -- convenience readers -------------------------------------------------
    def batch(self, year: int, quarter: int) -> Dict[str, Any]:
        for row in self.batches:
            if row["year"] == year and row["quarter"] == quarter:
                return row
        raise AssertionError(f"no ingested quarter for {year} Q{quarter}")

    def batch_id(self, year: int, quarter: int) -> str:
        return self.batch(year, quarter)["id"]

    def read_site(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_site(self.site_id, PM_HEADERS))

    def site_version(self) -> int:
        return self.read_site()["version"]

    def read_monitor(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_monitor(self.monitor_id, PM_HEADERS))

    def read_network(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_network(self.network_id, PM_HEADERS))

    def read_batch(self, year: int, quarter: int) -> Dict[str, Any]:
        return get_success_data(self.api.get_data_batch(self.batch_id(year, quarter), QA_HEADERS))


# --------------------------------------------------------------- primitives


def set_clock(api: ApiClient, instant: str) -> None:
    get_success_data(api.set_clock({"to_iso8601": instant}, ADMIN_HEADERS))


def create_pollutant(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_pollutant(f.pollutant_payload(**overrides), ADMIN_HEADERS))


def create_reference_method(api: ApiClient, pollutant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_reference_method(
            f.reference_method_payload(pollutant_id, **overrides), ADMIN_HEADERS
        )
    )


def create_network(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_network(f.network_payload(**overrides), ADMIN_HEADERS))


def create_site(api: ApiClient, network_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_site(f.site_payload(network_id, **overrides), ADMIN_HEADERS))


def approve_siting(api: ApiClient, site_id: str, waiver_granted: bool = False, **overrides):
    payload: Dict[str, Any] = {"waiver_granted": waiver_granted}
    payload.update(overrides)
    return get_success_data(api.approve_siting(site_id, payload, EPA_HEADERS))


def commence_operations(api: ApiClient, site_id: str, **overrides):
    return get_success_data(api.commence_operations(site_id, dict(overrides), PM_HEADERS))


def create_operating_site(api: ApiClient, network_id: str, waiver_granted: bool = False, **overrides):
    site = create_site(api, network_id, **overrides)
    approve_siting(api, site["id"], waiver_granted=waiver_granted)
    return commence_operations(api, site["id"])


def create_monitor(api: ApiClient, site_id: str, method_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_monitor(f.monitor_payload(site_id, method_id, **overrides), ADMIN_HEADERS)
    )


def approve_monitor(api: ApiClient, monitor_id: str, **overrides):
    return get_success_data(api.approve_monitor(monitor_id, dict(overrides), EPA_HEADERS))


def commission_monitor(api: ApiClient, monitor_id: str, **overrides):
    return get_success_data(api.commission_monitor(monitor_id, dict(overrides), TECH_HEADERS))


def create_operating_monitor(api: ApiClient, site_id: str, method_id: str, **overrides):
    monitor = create_monitor(api, site_id, method_id, **overrides)
    approve_monitor(api, monitor["id"])
    return commission_monitor(api, monitor["id"])


def log_span_check(api: ApiClient, monitor_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_qc_event(monitor_id, f.span_check_payload(**overrides), TECH_HEADERS)
    )


def batch_version(api: ApiClient, batch_id: str) -> int:
    return get_success_data(api.get_data_batch(batch_id, QA_HEADERS))["version"]


def apply_invalidation(
    api: ApiClient,
    batch_id: str,
    start_hour_index: int,
    end_hour_index: int,
    invalidation_code: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or QA_HEADERS
    payload = f.invalidation_payload(
        start_hour_index,
        end_hour_index,
        invalidation_code,
        batch_version(api, batch_id),
    )
    return get_success_data(api.create_invalidation(batch_id, payload, headers))


# --------------------------------------------------------------- composites


def base_environment(api: ApiClient, clock: str = CANONICAL_CLOCK, **pollutant_overrides) -> Env:
    """Clock, one pollutant, one designated method and one network."""
    env = Env(api)
    set_clock(api, clock)
    env.pollutant_id = create_pollutant(api, **pollutant_overrides)["id"]
    env.method_id = create_reference_method(api, env.pollutant_id)["id"]
    env.network_id = create_network(api)["id"]
    return env


def operating_site_environment(
    api: ApiClient,
    clock: str = CANONICAL_CLOCK,
    pollutant_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
) -> Env:
    """Base environment plus one operating population-oriented site."""
    env = base_environment(api, clock=clock, **(pollutant_overrides or {}))
    site = create_operating_site(api, env.network_id, **(site_overrides or {}))
    env.site_id = site["id"]
    return env


def canonical_environment(
    api: ApiClient,
    clock: str = CANONICAL_CLOCK,
    span_check_at: str = "2026-01-02T00:00:00Z",
    pollutant_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
    monitor_overrides: Optional[Dict[str, Any]] = None,
) -> Env:
    """One operating site carrying one commissioned, QC-current instrument."""
    env = operating_site_environment(
        api,
        clock=clock,
        pollutant_overrides=pollutant_overrides,
        site_overrides=site_overrides,
    )
    monitor = create_operating_monitor(
        api, env.site_id, env.method_id, **(monitor_overrides or {})
    )
    env.monitor_id = monitor["id"]
    if span_check_at is not None:
        log_span_check(api, env.monitor_id, performed_at=span_check_at)
    return env


def ingest_worked_example_quarters(
    env: Env, batches: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Bulk-report the twelve quarters of the PRD 3.7 worked example."""
    rows = get_success_data(
        env.api.bulk_ingest(f.bulk_ingest_payload(env.monitor_id, batches), QA_HEADERS)
    )
    env.batches = rows
    return rows


def bulk_validate(env: Env, headers: Optional[Dict[str, str]] = None, **overrides):
    payload: Dict[str, Any] = {"monitor_id": env.monitor_id}
    payload.update(overrides)
    return get_success_data(env.api.bulk_validate(payload, headers or QA_HEADERS))


def twelve_validated_quarters(
    api: ApiClient,
    clock: str = CANONICAL_CLOCK,
    batches: Optional[List[Dict[str, Any]]] = None,
    pollutant_overrides: Optional[Dict[str, Any]] = None,
) -> Env:
    """Canonical environment plus twelve validated, fully complete quarters."""
    env = canonical_environment(api, clock=clock, pollutant_overrides=pollutant_overrides)
    ingest_worked_example_quarters(env, batches)
    bulk_validate(env)
    env.batches = [
        get_success_data(api.get_data_batch(row["id"], QA_HEADERS)) for row in env.batches
    ]
    return env


def add_wildfire_demonstration(
    env: Env,
    batch_year: int = 2024,
    batch_quarter: int = 3,
    start_hour_index: int = 1008,
    end_hour_index: int = 1200,
    **demo_overrides,
) -> Dict[str, Any]:
    """A DRAFT wildfire demonstration carrying one PROPOSED exclusion."""
    demo = get_success_data(
        env.api.create_demonstration(
            f.demonstration_payload(env.site_id, env.pollutant_id, **demo_overrides), PM_HEADERS
        )
    )
    env.demonstration_id = demo["id"]
    exclusion = get_success_data(
        env.api.create_exclusion(
            demo["id"],
            f.exclusion_payload(
                env.batch_id(batch_year, batch_quarter), start_hour_index, end_hour_index
            ),
            PM_HEADERS,
        )
    )
    env.exclusion_id = exclusion["id"]
    return demo


def submit_demonstration(env: Env, **overrides):
    return get_success_data(
        env.api.submit_demonstration(env.demonstration_id, dict(overrides), PM_HEADERS)
    )


def concur_demonstration(env: Env, **overrides):
    payload: Dict[str, Any] = {"determination": "CONCUR"}
    payload.update(overrides)
    return get_success_data(env.api.decide_demonstration(env.demonstration_id, payload, EPA_HEADERS))


def add_concurred_demonstration(env: Env, **kwargs) -> Dict[str, Any]:
    """Walk a wildfire demonstration all the way to CONCURRED."""
    add_wildfire_demonstration(env, **kwargs)
    submit_demonstration(env)
    return concur_demonstration(env)


def compute_design_value(
    env: Env, period_end_year: int = 2025, variant: str = "WITH_EVENT_DATA", **overrides
) -> Dict[str, Any]:
    payload = f.design_value_payload(
        env.site_id, env.pollutant_id, period_end_year, variant, env.site_version(), **overrides
    )
    row = get_success_data(env.api.create_design_value(payload, PM_HEADERS))
    env.design_value_id = row["id"]
    return row


def open_package(env: Env, year: int = 2025, **overrides) -> Dict[str, Any]:
    row = get_success_data(
        env.api.create_package(
            f.package_payload(env.network_id, env.pollutant_id, year, **overrides), PM_HEADERS
        )
    )
    env.package_id = row["id"]
    return row


def submit_package(env: Env, **overrides) -> Dict[str, Any]:
    return get_success_data(env.api.submit_package(env.package_id, dict(overrides), PM_HEADERS))


def submitted_package(env: Env, year: int = 2025, **overrides) -> Dict[str, Any]:
    open_package(env, year=year)
    return submit_package(env, **overrides)


def approved_assessment(env: Env, cycle_year: int = 2026) -> Dict[str, Any]:
    row = get_success_data(
        env.api.create_assessment(f.assessment_payload(env.network_id, cycle_year), PM_HEADERS)
    )
    env.assessment_id = row["id"]
    get_success_data(env.api.submit_assessment(row["id"], {}, PM_HEADERS))
    return get_success_data(
        env.api.decide_assessment(
            row["id"], {"decision": "APPROVE", "decision_note": "Assessment accepted"}, EPA_HEADERS
        )
    )


def submitted_change_request(
    env: Env, request_type: str = "SHUTDOWN", **overrides
) -> Dict[str, Any]:
    row = get_success_data(
        env.api.create_change_request(
            f.change_request_payload(env.site_id, request_type, env.assessment_id, **overrides),
            PM_HEADERS,
        )
    )
    env.change_request_id = row["id"]
    return get_success_data(env.api.submit_change_request(row["id"], {}, PM_HEADERS))
