"""Composite state builders.

The harness restarts the server before every single test, so each test starts
against an empty database and builds whatever state it needs from scratch through
the public API. These builders are the shared multi-call chains.

One setup detail is worth stating because it recurs everywhere: confirming an
orphan determination is only legal when "the well's owning operator must be in
regulatory trouble - its status must be DELINQUENT, INSOLVENT or REVOKED", so the
builders that need an ORPHAN_CONFIRMED well register the owning operator with no
posted bond, which makes it DELINQUENT as soon as its first well is added.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .api_client import ApiClient


def _data(response) -> Dict[str, Any]:
    return get_success_data(response)


def _rows(response) -> List[Dict[str, Any]]:
    body = response.json()
    data = body.get("data")
    assert isinstance(data, list), "expected a list payload, got %r" % (body,)
    return data


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    response = api.set_clock(to_iso8601, users.ADMIN)
    assert response.status_code == 200, "clock move failed: %r" % (response.json(),)
    return response.json()


# ---------------------------------------------------------------------------
# Operators and wells
# ---------------------------------------------------------------------------
def make_operator(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return _data(api.create_operator(f.operator_payload(**kwargs), users.ADMIN))


def make_unbonded_operator(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An operator with nothing posted, so its first well makes it DELINQUENT."""
    kwargs.setdefault("bond_amount_cents", 0)
    return make_operator(api, **kwargs)


def make_well(api: ApiClient, operator_id: str, **kwargs: Any) -> Dict[str, Any]:
    return _data(
        api.create_well(f.well_payload(operator_id, **kwargs), users.INSPECTOR)
    )


def read_well(api: ApiClient, well_id: str) -> Dict[str, Any]:
    return _data(api.get_well(well_id, users.INSPECTOR))


def read_operator(api: ApiClient, operator_id: str) -> Dict[str, Any]:
    return _data(api.get_operator(operator_id, users.ADMIN))


def well_version(api: ApiClient, well_id: str) -> int:
    return read_well(api, well_id)["version"]


def make_producing_well(api: ApiClient, **well_kwargs: Any) -> Dict[str, Any]:
    """One operator holding one freshly created PRODUCING well."""
    operator = make_operator(api)
    well = make_well(api, operator["id"], **well_kwargs)
    return {"operator": operator, "well": well}


def report_production(
    api: ApiClient, well_id: str, month: str, oil_bbl: float = 0.0, gas_mcf: float = 0.0
) -> Dict[str, Any]:
    return _data(
        api.create_production_record(
            well_id, f.production_payload(month, oil_bbl, gas_mcf), users.INSPECTOR
        )
    )


# ---------------------------------------------------------------------------
# Determinations
# ---------------------------------------------------------------------------
def open_determination(
    api: ApiClient, well_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """Open a determination, always carrying the freshly re-read well version."""
    version = well_version(api, well_id)
    payload = f.determination_payload(version, **kwargs)
    return _data(
        api.create_orphan_determination(
            well_id, payload, headers or users.INSPECTOR
        )
    )


def submit_determination(
    api: ApiClient, determination_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return _data(
        api.submit_orphan_determination(determination_id, headers or users.INSPECTOR)
    )


def decide_determination(
    api: ApiClient,
    determination_id: str,
    action: str,
    rationale: str = "criteria satisfied",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return _data(
        api.decide_orphan_determination(
            determination_id,
            f.determination_decision_payload(action, rationale),
            headers or users.REVIEWER,
        )
    )


def make_confirmed_orphan_well(
    api: ApiClient,
    operator: Optional[Dict[str, Any]] = None,
    **well_kwargs: Any,
) -> Dict[str, Any]:
    """An ORPHAN_CONFIRMED well under an operator that is out of good standing."""
    operator = operator or make_unbonded_operator(api)
    well = make_well(api, operator["id"], **well_kwargs)
    determination = open_determination(api, well["id"])
    submit_determination(api, determination["id"])
    determination = decide_determination(api, determination["id"], "CONFIRM")
    return {
        "operator": operator,
        "well": read_well(api, well["id"]),
        "determination": determination,
    }


# ---------------------------------------------------------------------------
# Site access
# ---------------------------------------------------------------------------
def open_site_access(
    api: ApiClient, well_id: str, mode: str = "AGREEMENT", **kwargs: Any
) -> Dict[str, Any]:
    return _data(
        api.create_site_access(
            well_id, f.site_access_payload(mode=mode, **kwargs), users.ADMIN
        )
    )


def resolve_site_access(
    api: ApiClient,
    site_access_id: str,
    outcome: str,
    legal_authority_citation: Optional[str] = None,
) -> Dict[str, Any]:
    return _data(
        api.resolve_site_access(
            site_access_id,
            f.site_access_resolution_payload(outcome, legal_authority_citation),
            users.ADMIN,
        )
    )


def authorize_site_access(api: ApiClient, well_id: str) -> Dict[str, Any]:
    """Negotiate and execute a surface agreement so the crew may mobilize."""
    access = open_site_access(api, well_id, mode="AGREEMENT")
    return resolve_site_access(api, access["id"], "EXECUTE_AGREEMENT")


# ---------------------------------------------------------------------------
# Procurement
# ---------------------------------------------------------------------------
def make_contractor(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return _data(
        api.create_contractor(f.contractor_payload(**kwargs), users.PROCUREMENT)
    )


def make_solicitation(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return _data(
        api.create_solicitation(f.solicitation_payload(**kwargs), users.PROCUREMENT)
    )


def advance_solicitation(
    api: ApiClient, solicitation_id: str, action: str, **kwargs: Any
) -> Dict[str, Any]:
    return _data(
        api.solicitation_lifecycle(
            solicitation_id, f.lifecycle_payload(action, **kwargs), users.PROCUREMENT
        )
    )


def make_open_solicitation(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    solicitation = make_solicitation(api, **kwargs)
    return advance_solicitation(api, solicitation["id"], "OPEN")


def place_bid(
    api: ApiClient,
    solicitation_id: str,
    contractor_id: str,
    rates: Optional[Dict[str, int]] = None,
    technical_score: float = 92,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return _data(
        api.create_bid(
            solicitation_id,
            f.bid_payload(contractor_id, rates=rates, technical_score=technical_score),
            headers or users.PROCUREMENT,
        )
    )


def evaluate_bid(api: ApiClient, bid_id: str, outcome: str, **kwargs) -> Dict[str, Any]:
    return _data(
        api.evaluate_bid(
            bid_id, f.bid_evaluation_payload(outcome, **kwargs), users.PROCUREMENT
        )
    )


def award(api: ApiClient, solicitation_id: str) -> Dict[str, Any]:
    return _data(api.award_solicitation(solicitation_id, users.AWARD))


def make_active_contract(
    api: ApiClient,
    contractor: Optional[Dict[str, Any]] = None,
    rates: Optional[Dict[str, int]] = None,
    technical_score: float = 92,
    **solicitation_kwargs: Any,
) -> Dict[str, Any]:
    """A single-bid solicitation carried all the way to an ACTIVE unit-cost contract."""
    contractor = contractor or make_contractor(api)
    solicitation = make_open_solicitation(api, **solicitation_kwargs)
    bid = place_bid(
        api,
        solicitation["id"],
        contractor["id"],
        rates=rates,
        technical_score=technical_score,
    )
    advance_solicitation(api, solicitation["id"], "CLOSE")
    evaluate_bid(api, bid["id"], "RESPONSIVE")
    contract = award(api, solicitation["id"])
    return {
        "contractor": contractor,
        "solicitation": solicitation,
        "bid": bid,
        "contract": contract,
    }


# ---------------------------------------------------------------------------
# Plugging jobs
# ---------------------------------------------------------------------------
def make_plugging_job(
    api: ApiClient, well_id: str, contract_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return _data(
        api.create_plugging_job(
            f.plugging_job_payload(well_id, contract_id, **kwargs), users.ADMIN
        )
    )


def mobilize(api: ApiClient, job_id: str) -> Dict[str, Any]:
    return _data(api.mobilize_plugging_job(job_id, users.INSPECTOR))


def file_field_report(api: ApiClient, job_id: str, **kwargs: Any) -> Dict[str, Any]:
    return _data(
        api.file_field_report(job_id, f.field_report_payload(**kwargs), users.INSPECTOR)
    )


def review_job(
    api: ApiClient, job_id: str, action: str, findings: str = "documentation complete"
) -> Dict[str, Any]:
    return _data(
        api.review_plugging_job(job_id, f.job_review_payload(action, findings), users.ADMIN)
    )


def make_scheduled_job(
    api: ApiClient,
    scheduled_start: str = "2026-08-05T00:00:00Z",
    authorize_access: bool = True,
    **job_kwargs: Any,
) -> Dict[str, Any]:
    """A SCHEDULED plugging job on an ORPHAN_CONFIRMED well under an ACTIVE contract."""
    orphan = make_confirmed_orphan_well(api)
    procurement = make_active_contract(api)
    if authorize_access:
        authorize_site_access(api, orphan["well"]["id"])
    job = make_plugging_job(
        api,
        orphan["well"]["id"],
        procurement["contract"]["id"],
        scheduled_start=scheduled_start,
        **job_kwargs,
    )
    bundle = dict(orphan)
    bundle.update(procurement)
    bundle["job"] = job
    return bundle


def make_field_reported_job(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A plugging job whose first field report has been filed but not yet reviewed."""
    bundle = make_scheduled_job(api, **kwargs)
    mobilize(api, bundle["job"]["id"])
    bundle["job"] = file_field_report(api, bundle["job"]["id"])
    return bundle


def make_plugged_job(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An accepted plugging job together with its three PENDING reclamation tasks."""
    bundle = make_field_reported_job(api, **kwargs)
    bundle["job"] = review_job(api, bundle["job"]["id"], "ACCEPT")
    bundle["tasks"] = _rows(
        api.list_reclamation_tasks(bundle["job"]["id"], users.INSPECTOR)
    )
    return bundle


def task_by_type(tasks: List[Dict[str, Any]], task_type: str) -> Dict[str, Any]:
    for task in tasks:
        if task["task_type"] == task_type:
            return task
    raise AssertionError("no %s task in %r" % (task_type, tasks))


def progress_task(
    api: ApiClient, task_id: str, action: str, notes: Optional[str] = None
) -> Dict[str, Any]:
    return _data(
        api.progress_reclamation_task(
            task_id, f.task_progress_payload(action, notes), users.INSPECTOR
        )
    )


def complete_task(api: ApiClient, task_id: str, notes: str = "work complete") -> Dict[str, Any]:
    progress_task(api, task_id, "START")
    return progress_task(api, task_id, "PASS", notes)


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------
def make_funding_source(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return _data(
        api.create_funding_source(f.funding_source_payload(**kwargs), users.FUNDING)
    )


def commit_funding(
    api: ApiClient, job_id: str, override_source_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    payload = {} if override_source_id is None else {"override_source_id": override_source_id}
    response = api.create_funding_commitments(job_id, users.FUNDING, payload)
    assert response.status_code == 201, "funding waterfall failed: %r" % (
        response.json(),
    )
    return _rows(response)


def make_funded_job(
    api: ApiClient, authorized_cents: int = 20000000, **kwargs: Any
) -> Dict[str, Any]:
    """A SCHEDULED job whose whole estimate is committed against one state fund."""
    bundle = make_scheduled_job(api, **kwargs)
    bundle["source"] = make_funding_source(api, authorized_cents=authorized_cents)
    bundle["allocations"] = commit_funding(api, bundle["job"]["id"])
    return bundle

# ---------------------------------------------------------------------------
# Extra readers and small state moves
# ---------------------------------------------------------------------------
def set_license_status(
    api: ApiClient, contractor_id: str, action: str, reason: str = "licence review"
) -> Dict[str, Any]:
    """Suspend, reinstate or debar a contractor, cascading onto its contracts."""
    return _data(
        api.contractor_eligibility(
            contractor_id, f.eligibility_payload(action, reason), users.ADMIN
        )
    )


def read_contractor(api: ApiClient, contractor_id: str) -> Dict[str, Any]:
    return _data(api.get_contractor(contractor_id, users.PROCUREMENT))


def read_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return _data(api.get_unit_cost_contract(contract_id, users.PROCUREMENT))


def read_job(api: ApiClient, job_id: str) -> Dict[str, Any]:
    return _data(api.get_plugging_job(job_id, users.ADMIN))


def read_determination(api: ApiClient, determination_id: str) -> Dict[str, Any]:
    return _data(api.get_orphan_determination(determination_id, users.REVIEWER))


def read_site_access(api: ApiClient, site_access_id: str) -> Dict[str, Any]:
    return _data(api.get_site_access(site_access_id, users.ADMIN))


def read_solicitation(api: ApiClient, solicitation_id: str) -> Dict[str, Any]:
    return _data(api.get_solicitation(solicitation_id, users.PROCUREMENT))


def read_bid(api: ApiClient, bid_id: str) -> Dict[str, Any]:
    return _data(api.get_bid(bid_id, users.PROCUREMENT))


def read_source(api: ApiClient, source_id: str) -> Dict[str, Any]:
    return _data(api.get_funding_source(source_id, users.FUNDING))


def read_allocation(api: ApiClient, allocation_id: str) -> Dict[str, Any]:
    return _data(api.get_funding_allocation(allocation_id, users.FUNDING))


def read_task(api: ApiClient, task_id: str) -> Dict[str, Any]:
    return _data(api.get_reclamation_task(task_id, users.INSPECTOR))


def enforce(
    api: ApiClient, operator_id: str, action: str, memo: str = "enforcement action", **extra: Any
) -> Dict[str, Any]:
    """Act against an operator carrying its freshly re-read version."""
    version = read_operator(api, operator_id)["version"]
    payload = f.enforcement_payload(action, version, memo, **extra)
    return _data(api.operator_enforcement(operator_id, payload, users.ADMIN))


def transfer_well(api: ApiClient, well_id: str, to_operator_id: str) -> Dict[str, Any]:
    return _data(
        api.create_well_transfer(well_id, f.transfer_payload(to_operator_id), users.ADMIN)
    )


def decide_transfer(
    api: ApiClient, transfer_id: str, action: str, rationale: str = "reviewed"
) -> Dict[str, Any]:
    return _data(
        api.decide_well_transfer(
            transfer_id, f.transfer_decision_payload(action, rationale), users.ADMIN
        )
    )


def transition_allocation(
    api: ApiClient, allocation_id: str, action: str, invoice_cents: Optional[int] = None
) -> Dict[str, Any]:
    return _data(
        api.transition_funding_allocation(
            allocation_id,
            f.allocation_transition_payload(action, invoice_cents),
            users.FUNDING_2,
        )
    )


def make_grant_report(
    api: ApiClient, source_id: str, period_start: str, period_end: str
) -> Dict[str, Any]:
    return _data(
        api.create_grant_report(
            source_id, f.grant_report_payload(period_start, period_end), users.FUNDING
        )
    )
