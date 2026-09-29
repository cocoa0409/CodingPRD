"""Requests that break two rules at once and must answer with the higher-ranked one."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_SITE_ACCESS_NOT_AUTHORIZED,
    ERR_WELL_NOT_ORPHAN_CONFIRMED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_null_fields,
    assert_page,
    created,
)
from test_helpers.factories import plugging_job_payload


def _candidate_well_and_suspended_contract(api):
    """A merely ORPHAN_CANDIDATE well plus a contract suspended behind its contractor."""
    operator = fx.make_unbonded_operator(api, name="Llano Estacado Oil", region_code="TX")
    well = fx.make_well(api, operator["id"])
    determination = fx.open_determination(
        api, well["id"], inspector_notes="candidate pending review"
    )
    fx.submit_determination(api, determination["id"])

    procurement = fx.make_active_contract(
        api, region_code="TX", scope_description="district TX plugging package"
    )
    fx.set_license_status(
        api, procurement["contractor"]["id"], "SUSPEND_LICENSE", "expired surety rider"
    )
    bundle = {"operator": operator, "well": well, "determination": determination}
    bundle.update(procurement)
    return bundle


def test_the_well_state_gate_answers_before_the_contract_gate(api):
    """Both the well state and the contract state are wrong; the well state wins.

    The well is only ORPHAN_CANDIDATE and the contract is SUSPENDED, so two separate
    rules are broken by one order; the response is the specific referenced-state error
    and nothing is written.

    PRD: "Specific referenced-state gates, in this order:
    `ERR_WELL_NOT_ORPHAN_CONFIRMED`, then `ERR_SOLICITATION_NOT_OPEN`, then
    `ERR_FUNDING_SOURCE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/job_creation_state_check_outranks_contract_referential_check
    """
    bundle = _candidate_well_and_suspended_contract(api)
    contract_id = bundle["contract"]["id"]
    assert_fields(fx.read_contract(api, contract_id), status="SUSPENDED")
    assert_fields(fx.read_well(api, bundle["well"]["id"]), status="ORPHAN_CANDIDATE")

    refused = api.create_plugging_job(
        plugging_job_payload(
            bundle["well"]["id"], contract_id, scheduled_start="2026-09-01T00:00:00Z"
        ),
        users.ADMIN,
    )
    validate_error(refused, ERR_WELL_NOT_ORPHAN_CONFIRMED)

    assert_page(api.list_plugging_jobs(users.ADMIN), 0, expected_total=0)
    assert_cents(
        fx.read_contract(api, contract_id)["obligated_cents"], 0, "obligated_cents"
    )


def test_curing_the_well_state_exposes_the_contract_gate_underneath(api):
    """With the well confirmed, the very same order surfaces the lower-ranked error.

    Confirming the determination removes the higher-ranked violation, and the order
    then reports the contract gate; reinstating the contractor clears that one too and
    the third attempt is accepted.

    PRD: "And the contract must be usable — a contract whose `status` is `SUSPENDED` or
    `CLOSED` is rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/job_creation_state_check_outranks_contract_referential_check
    """
    bundle = _candidate_well_and_suspended_contract(api)
    well_id = bundle["well"]["id"]
    contract_id = bundle["contract"]["id"]

    fx.decide_determination(api, bundle["determination"]["id"], "CONFIRM")
    assert_fields(fx.read_well(api, well_id), status="ORPHAN_CONFIRMED")

    order = plugging_job_payload(
        well_id, contract_id, scheduled_start="2026-09-01T00:00:00Z"
    )
    refused = api.create_plugging_job(order, users.ADMIN)
    validate_error(refused, ERR_CONTRACT_NOT_ACTIVE)
    assert_fields(fx.read_well(api, well_id), status="ORPHAN_CONFIRMED")

    fx.set_license_status(
        api, bundle["contractor"]["id"], "REINSTATE", "surety rider replaced"
    )
    assert_fields(fx.read_contract(api, contract_id), status="ACTIVE")

    job = created(api.create_plugging_job(order, users.ADMIN))
    assert_fields(job, status="SCHEDULED", well_id=well_id, contract_id=contract_id)
    assert_cents(
        job["plugging_cost_estimate_cents"], 6070196, "plugging_cost_estimate_cents"
    )
    assert_fields(fx.read_well(api, well_id), status="PLUGGING_SCHEDULED")


def _unreachable_site_with_a_suspended_contract(api):
    """A SCHEDULED job whose well was never asked for access and whose contract fell."""
    bundle = fx.make_scheduled_job(
        api, scheduled_start="2026-09-01T00:00:00Z", authorize_access=False
    )
    fx.set_license_status(
        api, bundle["contractor"]["id"], "SUSPEND_LICENSE", "crew certification lapsed"
    )
    return bundle


def test_the_site_access_gate_answers_before_the_contract_gate_on_mobilize(api):
    """A crew with no legal standing on the site is refused for that reason first.

    The well is still NO_ACCESS_REQUESTED and the contract is SUSPENDED; the safety
    gate outranks the referential one, so the answer names the access failure.

    PRD: "Safety gates, in this order: `ERR_SITE_ACCESS_NOT_AUTHORIZED`, then
    `ERR_STATUTORY_NOTICE_PERIOD_ACTIVE`, then `ERR_REVEGETATION_WAITING_PERIOD`, then
    `ERR_RECLAMATION_INCOMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/mobilize_safety_check_outranks_contract_referential_check
    """
    bundle = _unreachable_site_with_a_suspended_contract(api)
    job_id = bundle["job"]["id"]
    assert_fields(fx.read_contract(api, bundle["contract"]["id"]), status="SUSPENDED")

    refused = api.mobilize_plugging_job(job_id, users.INSPECTOR)
    validate_error(refused, ERR_SITE_ACCESS_NOT_AUTHORIZED)

    assert_fields(
        fx.read_well(api, bundle["well"]["id"]), access_status="NO_ACCESS_REQUESTED"
    )
    job = fx.read_job(api, job_id)
    assert_fields(job, status="SCHEDULED")
    assert_null_fields(job, "mobilized_at")


def test_reinstating_the_contract_leaves_the_mobilize_error_unchanged(api):
    """Clearing the lower-ranked violation does not change the answer at all.

    The contract returns to ACTIVE and the refusal is still the access failure, because
    that is the only gate that was ever decisive; executing a surface agreement is what
    finally lets the crew move.

    PRD: "It demands legal standing to be on the site: the well's `access_status` must
    be `AGREEMENT_EXECUTED` or `ENTRY_ORDERED`, reflecting the latest resolved
    site-access row, and anything else — including `NO_ACCESS_REQUESTED`,
    `ACCESS_PENDING` and `ACCESS_DENIED` — is rejected with
    `ERR_SITE_ACCESS_NOT_AUTHORIZED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/mobilize_safety_check_outranks_contract_referential_check
    """
    bundle = _unreachable_site_with_a_suspended_contract(api)
    job_id = bundle["job"]["id"]
    well_id = bundle["well"]["id"]

    validate_error(
        api.mobilize_plugging_job(job_id, users.INSPECTOR), ERR_SITE_ACCESS_NOT_AUTHORIZED
    )

    fx.set_license_status(
        api, bundle["contractor"]["id"], "REINSTATE", "certification restored"
    )
    assert_fields(fx.read_contract(api, bundle["contract"]["id"]), status="ACTIVE")

    validate_error(
        api.mobilize_plugging_job(job_id, users.INSPECTOR), ERR_SITE_ACCESS_NOT_AUTHORIZED
    )
    job = fx.read_job(api, job_id)
    assert_fields(job, status="SCHEDULED")
    assert_null_fields(job, "mobilized_at")

    fx.authorize_site_access(api, well_id)
    assert_fields(fx.read_well(api, well_id), access_status="AGREEMENT_EXECUTED")

    mobilized = fx.mobilize(api, job_id)
    assert_fields(
        mobilized, status="MOBILIZED", mobilized_at="2026-08-01T00:00:00Z"
    )
