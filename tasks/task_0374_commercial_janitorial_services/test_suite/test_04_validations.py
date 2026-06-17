"""Business-constraint validations: duplicate period, inactive contract, clock
range, floor eligibility, existence-before-state ordering.

Translates SCAFFOLD_CORNER_DESIGN.yaml §1.9 `validations` non-stub instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures,
    create_billing_period_payload,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


def test_duplicate_billing_period_returns_duplicate_period(api):
    """PRD §3.9: "The pair of `contract_id` and `period_month` is unique; opening
    a duplicate period for the same contract and month is refused with
    `ERR_DUPLICATE_PERIOD`."

    Design: Corner/validations/duplicate_billing_period_returns_duplicate_period
    """
    bundle = fixtures.setup_billing_scenario(crew=False)
    resp = api.create_billing_period(
        create_billing_period_payload(bundle["contract"]["id"], period_month="2026-06"), AM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD.value)


def test_open_billing_period_inactive_contract_returns_contract_not_active(api):
    """PRD §3.9: "Opening a period requires the backing contract to be `ACTIVE`;
    otherwise the operation is refused with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Corner/validations/open_billing_period_inactive_contract_returns_contract_not_active
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    contract = fixtures.create_draft_contract(site["id"])
    resp = api.create_billing_period(create_billing_period_payload(contract["id"]), AM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


def test_clock_out_invalid_clock_range_returns_invalid_clock_range(api):
    """PRD §3.4: "the supplied `clock_out_min` must be strictly greater than
    `clock_in_min` or the request is refused with `ERR_INVALID_CLOCK_RANGE`
    (HTTP 422)".

    Design: Corner/validations/clock_out_invalid_clock_range_returns_invalid_clock_range
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_started_visit(site["id"], crew["id"])
    te = validate_success(api.create_time_entry(
        {"visit_id": visit["id"], "crew_id": crew["id"], "clock_in_min": 480}, FS), 201)
    resp = api.clock_out_time_entry(te["id"], {"clock_out_min": 480}, FS)
    validate_error(resp, ApiErrorId.ERR_INVALID_CLOCK_RANGE.value)
    after = validate_success(api.get_time_entry(te["id"], FS), 200)
    assert after["status"] == "OPEN"


def test_dispatch_strip_wax_on_carpet_returns_floor_ineligible(api):
    """PRD §3.6: "When `job_type` is `STRIP_WAX`, the site's `floor_type` must be
    `VCT` or `TERRAZZO`, since strip-and-wax is only valid on those finishes; a
    strip-wax dispatch onto any other floor is refused with `ERR_FLOOR_INELIGIBLE`."

    Design: Corner/validations/dispatch_strip_wax_on_carpet_returns_floor_ineligible
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"floor_type": "CARPET"})
    job = fixtures.create_periodic_job(site["id"], job_type="STRIP_WAX", quoted_hours=2)
    resp = api.dispatch_periodic_job(
        job["id"],
        {"crew_id": crew["id"], "service_date": "2026-06-12",
         "planned_start_min": 480, "planned_end_min": 600}, FS)
    validate_error(resp, ApiErrorId.ERR_FLOOR_INELIGIBLE.value)
    after = validate_success(api.get_periodic_job(job["id"], AM), 200)
    assert after["status"] == "REQUESTED"


def test_existence_before_state_path_404_wins_on_unknown_visit(api):
    """PRD §2.6: "(4) existence of path-referenced resources, yielding
    `ERR_NOT_FOUND`; ... (7) whether the target resource is in a state from which
    the requested transition is defined, yielding `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/validations/existence_before_state_path_404_wins_on_unknown_visit
    """
    resp = api.start_visit("visit_missing", FS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
