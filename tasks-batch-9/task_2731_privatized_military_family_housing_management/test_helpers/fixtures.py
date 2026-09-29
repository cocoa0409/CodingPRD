"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls
go through ``get_success_data`` so a broken precondition reports as a setup
failure rather than as a confusing assertion.

The canonical tenancy these helpers assemble is a two-bedroom TOWNHOME at a
default-policy installation, leased by an E5 sponsor with a spouse and two
young sons, priced off the E5 / with-dependents / 2026 BAH rate row.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    TEST_USERS,
    make_service_member_headers,
)

# --- Pinned clock readings the canonical chain uses -------------------------
CLOCK_BEFORE_ARRIVAL = "2026-08-25T00:00:00Z"
CLOCK_AT_MOVE_IN = "2026-09-01T09:00:00Z"

# --- Pinned family composition ---------------------------------------------
CANONICAL_DEPENDENTS = (
    {"relationship": "SPOUSE", "date_of_birth": "1992-03-04", "gender": "FEMALE"},
    {"relationship": "CHILD", "date_of_birth": "2018-04-10", "gender": "MALE"},
    {"relationship": "CHILD", "date_of_birth": "2022-03-15", "gender": "MALE"},
)

# A senior-enlisted family entitled to three bedrooms on the same control date:
# the elder child has already reached ten and needs a private bedroom.
SENIOR_ENLISTED_DEPENDENTS = (
    {"relationship": "SPOUSE", "date_of_birth": "1988-05-09", "gender": "MALE"},
    {"relationship": "CHILD", "date_of_birth": "2015-11-15", "gender": "FEMALE"},
    {"relationship": "CHILD", "date_of_birth": "2020-07-22", "gender": "FEMALE"},
)


# --- Single-step primitives -------------------------------------------------


def set_clock(api, current_utc: str) -> None:
    """Drive the server's logical clock to a supplied instant."""
    response = api.set_current_utc(current_utc, TEST_USERS["platform_admin_headers"])
    get_success_data(response)


def create_installation(api, **overrides) -> dict:
    return get_success_data(
        api.create_installation(
            f.create_installation_payload(**overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_bah_rate(api, installation_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_bah_rate(
            f.create_bah_rate_payload(installation_id, **overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_housing_unit(api, installation_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_housing_unit(
            f.create_housing_unit_payload(installation_id, **overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_service_member(api, **overrides) -> dict:
    return get_success_data(
        api.create_service_member(
            f.create_service_member_payload(**overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_dependent(api, service_member_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_dependent(
            f.create_dependent_payload(service_member_id, **overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_reinvestment_account(api, installation_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_reinvestment_account(
            f.create_reinvestment_account_payload(installation_id, **overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def read_installation(api, installation_id: str) -> dict:
    return get_success_data(
        api.get_installation(installation_id, TEST_USERS["platform_admin_headers"])
    )


def read_housing_unit(api, housing_unit_id: str) -> dict:
    return get_success_data(
        api.get_housing_unit(housing_unit_id, TEST_USERS["platform_admin_headers"])
    )


def read_lease(api, lease_id: str) -> dict:
    return get_success_data(
        api.get_lease(lease_id, TEST_USERS["platform_admin_headers"])
    )


def read_application(api, application_id: str) -> dict:
    return get_success_data(
        api.get_waitlist_application(
            application_id, TEST_USERS["platform_admin_headers"]
        )
    )


def read_inspection(api, inspection_id: str) -> dict:
    return get_success_data(
        api.get_move_in_inspection(inspection_id, TEST_USERS["platform_admin_headers"])
    )


def read_work_order(api, work_order_id: str) -> dict:
    return get_success_data(
        api.get_work_order(work_order_id, TEST_USERS["platform_admin_headers"])
    )


def read_hazard_case(api, hazard_case_id: str) -> dict:
    return get_success_data(
        api.get_hazard_case(hazard_case_id, TEST_USERS["platform_admin_headers"])
    )


def read_lodging(api, lodging_id: str) -> dict:
    return get_success_data(
        api.get_displacement_lodging(
            lodging_id, TEST_USERS["platform_admin_headers"]
        )
    )


def read_dispute(api, dispute_case_id: str) -> dict:
    return get_success_data(
        api.get_dispute_case(dispute_case_id, TEST_USERS["platform_admin_headers"])
    )


def read_account(api, account_id: str) -> dict:
    return get_success_data(
        api.get_reinvestment_account(
            account_id, TEST_USERS["platform_admin_headers"]
        )
    )


def read_ledger(api, lease_id: str, params=None) -> list:
    body = api.list_lease_allotment_transactions(
        lease_id, TEST_USERS["platform_admin_headers"], params=params
    )
    return get_success_data(body)


# --- Tier 1: sponsor families ----------------------------------------------


def setup_sponsor_family(api, dependents=CANONICAL_DEPENDENTS, **sponsor_overrides):
    """Register a sponsor and their dependents. Returns (sponsor, [dependents])."""
    sponsor = create_service_member(api, **sponsor_overrides)
    created = []
    for entry in dependents:
        created.append(create_dependent(api, sponsor["id"], **entry))
    # Re-read so dependent_count reflects the whole family.
    sponsor = get_success_data(
        api.get_service_member(sponsor["id"], TEST_USERS["platform_admin_headers"])
    )
    return sponsor, created


# --- Tier 2: installation with inventory -----------------------------------


def setup_installation_with_unit(
    api,
    clock=CLOCK_BEFORE_ARRIVAL,
    installation_overrides=None,
    rate_overrides=None,
    unit_overrides=None,
):
    """Clock + installation + one BAH rate row + one housing unit.

    Returns a dict with ``installation``, ``bah_rate`` and ``unit``.
    """
    if clock is not None:
        set_clock(api, clock)
    installation = create_installation(api, **(installation_overrides or {}))
    bah_rate = create_bah_rate(api, installation["id"], **(rate_overrides or {}))
    unit = create_housing_unit(api, installation["id"], **(unit_overrides or {}))
    return {"installation": installation, "bah_rate": bah_rate, "unit": unit}


# --- Tier 3: waitlist through acceptance ----------------------------------


def submit_application(api, installation_id, sponsor, **overrides):
    """Create a waitlist application as the sponsor themselves."""
    return get_success_data(
        api.create_waitlist_application(
            f.create_waitlist_application_payload(
                installation_id, sponsor["id"], **overrides
            ),
            make_service_member_headers(sponsor["id"]),
        )
    )


def run_offer_run(api, installation_id) -> dict:
    return get_success_data(
        api.run_waitlist_offer_run(
            installation_id, TEST_USERS["property_manager_headers"]
        )
    )


def accept_offer(api, application_id, sponsor) -> dict:
    return get_success_data(
        api.accept_offer(application_id, make_service_member_headers(sponsor["id"]))
    )


def decline_offer(api, application_id, sponsor, **payload) -> dict:
    return get_success_data(
        api.decline_offer(
            application_id,
            make_service_member_headers(sponsor["id"]),
            payload or None,
        )
    )


def setup_accepted_application(
    api,
    clock=CLOCK_BEFORE_ARRIVAL,
    installation_overrides=None,
    rate_overrides=None,
    unit_overrides=None,
    dependents=CANONICAL_DEPENDENTS,
    sponsor_overrides=None,
    application_overrides=None,
):
    """Installation + unit + sponsor family + application offered and accepted.

    Returns a dict with ``installation``, ``bah_rate``, ``unit``, ``sponsor``,
    ``dependents`` and ``application`` (in ACCEPTED status).
    """
    base = setup_installation_with_unit(
        api,
        clock=clock,
        installation_overrides=installation_overrides,
        rate_overrides=rate_overrides,
        unit_overrides=unit_overrides,
    )
    sponsor, deps = setup_sponsor_family(
        api, dependents=dependents, **(sponsor_overrides or {})
    )
    application = submit_application(
        api, base["installation"]["id"], sponsor, **(application_overrides or {})
    )
    run_offer_run(api, base["installation"]["id"])
    application = accept_offer(api, application["id"], sponsor)
    base.update(
        {"sponsor": sponsor, "dependents": deps, "application": application}
    )
    return base


# --- Tier 3: lease through move-in ----------------------------------------


def write_lease(api, application_id, housing_unit_id, **overrides) -> dict:
    return get_success_data(
        api.create_lease(
            f.create_lease_payload(application_id, housing_unit_id, **overrides),
            TEST_USERS["property_manager_headers"],
        )
    )


def schedule_inspection(api, lease_id, **overrides) -> dict:
    return get_success_data(
        api.create_move_in_inspection(
            f.create_move_in_inspection_payload(lease_id, **overrides),
            TEST_USERS["property_manager_headers"],
        )
    )


def log_deficiencies(api, inspection_id, entries) -> dict:
    return get_success_data(
        api.log_deficiencies(
            inspection_id,
            f.log_deficiencies_payload(entries),
            TEST_USERS["property_manager_headers"],
        )
    )


def acknowledge_inspection(
    api, inspection_id, sponsor, signature_name, bill_of_rights_version
) -> dict:
    return get_success_data(
        api.tenant_acknowledge(
            inspection_id,
            f.tenant_acknowledge_payload(signature_name, bill_of_rights_version),
            make_service_member_headers(sponsor["id"]),
        )
    )


def setup_lease_pending_move_in(api, **kwargs):
    """Everything of ``setup_accepted_application`` plus the written lease.

    Returns that dict with a ``lease`` key added (PENDING_MOVE_IN / NOT_STARTED).
    """
    lease_overrides = kwargs.pop("lease_overrides", None) or {}
    state = setup_accepted_application(api, **kwargs)
    state["lease"] = write_lease(
        api, state["application"]["id"], state["unit"]["id"], **lease_overrides
    )
    return state


def setup_acknowledged_inspection(api, **kwargs):
    """Lease plus a scheduled, tenant-acknowledged move-in inspection.

    Returns the ``setup_lease_pending_move_in`` dict with ``inspection`` added.
    """
    inspection_overrides = kwargs.pop("inspection_overrides", None) or {}
    state = setup_lease_pending_move_in(api, **kwargs)
    inspection = schedule_inspection(
        api, state["lease"]["id"], **inspection_overrides
    )
    sponsor = state["sponsor"]
    state["inspection"] = acknowledge_inspection(
        api,
        inspection["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        state["installation"]["bill_of_rights_version"],
    )
    return state


def move_in(api, lease_id) -> dict:
    return get_success_data(
        api.move_in(lease_id, TEST_USERS["property_manager_headers"])
    )


def setup_occupied_lease(api, move_in_clock=CLOCK_AT_MOVE_IN, **kwargs):
    """The canonical occupied tenancy — the preamble most claims start from.

    Walks installation → rate row → unit → sponsor family → application →
    offer run → acceptance → lease → inspection → acknowledgment → move-in.
    Returns a dict with ``installation``, ``bah_rate``, ``unit``, ``sponsor``,
    ``dependents``, ``application``, ``lease`` (OCCUPIED / ACTIVE) and
    ``inspection``.
    """
    state = setup_acknowledged_inspection(api, **kwargs)
    if move_in_clock is not None:
        set_clock(api, move_in_clock)
    state["lease"] = move_in(api, state["lease"]["id"])
    state["unit"] = read_housing_unit(api, state["unit"]["id"])
    state["installation"] = read_installation(api, state["installation"]["id"])
    return state

# --- Tier 4: maintenance work orders ---------------------------------------


def submit_work_order(api, housing_unit_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_work_order(
            f.create_work_order_payload(housing_unit_id, **overrides),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def assign_work_order(api, work_order_id, tech_user_id=None, headers=None) -> dict:
    from .test_users import MAINTENANCE_TECH_USER_ID

    return get_success_data(
        api.assign_work_order(
            work_order_id,
            f.assign_work_order_payload(tech_user_id or MAINTENANCE_TECH_USER_ID),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def start_work_order(api, work_order_id, headers=None) -> dict:
    return get_success_data(
        api.start_work_order(
            work_order_id, headers or TEST_USERS["maintenance_tech_headers"]
        )
    )


def complete_work_order(api, work_order_id, headers=None) -> dict:
    return get_success_data(
        api.complete_work_order(
            work_order_id, headers or TEST_USERS["maintenance_tech_headers"]
        )
    )


def reopen_work_order(api, work_order_id, reason, headers) -> dict:
    return get_success_data(
        api.reopen_work_order(
            work_order_id, f.reopen_work_order_payload(reason), headers
        )
    )


def escalate_work_order(api, work_order_id, headers=None) -> dict:
    return get_success_data(
        api.escalate_work_order(
            work_order_id, headers or TEST_USERS["property_manager_headers"]
        )
    )


def setup_work_order_in_progress(api, housing_unit_id, **overrides) -> dict:
    """Submit, assign and start one work order. Returns it in IN_PROGRESS."""
    work_order = submit_work_order(api, housing_unit_id, **overrides)
    assign_work_order(api, work_order["id"])
    return start_work_order(api, work_order["id"])


def setup_completed_work_order(api, housing_unit_id, **overrides) -> dict:
    """Submit → assign → start → complete one work order."""
    work_order = setup_work_order_in_progress(api, housing_unit_id, **overrides)
    return complete_work_order(api, work_order["id"])


# --- Tier 4: hazard cases ---------------------------------------------------


def report_hazard(api, housing_unit_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_hazard_case(
            f.create_hazard_case_payload(housing_unit_id, **overrides),
            headers or TEST_USERS["environmental_specialist_headers"],
        )
    )


def assess_hazard(api, hazard_case_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.assess_hazard_case(
            hazard_case_id,
            f.assess_hazard_case_payload(**overrides),
            headers or TEST_USERS["environmental_specialist_headers"],
        )
    )


def certify_clearance(api, hazard_case_id, passed: bool, headers=None, **overrides):
    """Certify clearance. Defaults to a second specialist, per separation of duties."""
    return get_success_data(
        api.certify_clearance(
            hazard_case_id,
            f.clearance_payload(passed, **overrides),
            headers or TEST_USERS["environmental_specialist_2_headers"],
        )
    )


def void_hazard(api, hazard_case_id, reason="Case opened in error", headers=None):
    return get_success_data(
        api.void_hazard_case(
            hazard_case_id,
            f.void_hazard_case_payload(reason),
            headers or TEST_USERS["environmental_specialist_headers"],
        )
    )


def setup_reported_hazard(api, occupied_state=None, hazard_clock=None, **overrides):
    """Occupied tenancy plus one hazard case still in REPORTED.

    ``occupied_state`` reuses an existing ``setup_occupied_lease`` result;
    otherwise a fresh one is built.
    """
    state = occupied_state if occupied_state is not None else setup_occupied_lease(api)
    if hazard_clock is not None:
        set_clock(api, hazard_clock)
    state["hazard_case"] = report_hazard(api, state["unit"]["id"], **overrides)
    return state


def setup_assessed_hazard(
    api,
    occupied_state=None,
    hazard_clock=None,
    report_overrides=None,
    assess_overrides=None,
):
    """Occupied tenancy plus one assessed hazard case.

    The severity — and therefore whether the household is displaced — follows
    from the measurement passed through ``assess_overrides``.
    Returns the tenancy dict with ``hazard_case`` (post-assessment), and both
    ``lease`` and ``unit`` re-read so any assessment cascade is visible.
    """
    state = setup_reported_hazard(
        api,
        occupied_state=occupied_state,
        hazard_clock=hazard_clock,
        **(report_overrides or {}),
    )
    state["hazard_case"] = assess_hazard(
        api, state["hazard_case"]["id"], **(assess_overrides or {})
    )
    state["lease"] = read_lease(api, state["lease"]["id"])
    state["unit"] = read_housing_unit(api, state["unit"]["id"])
    return state


def setup_displaced_household(api, occupied_state=None, hazard_clock=None, **kwargs):
    """An assessed hazard severe enough to displace the family.

    Forty-five square feet of mold grades at the top severity, which requires
    displacement, so the case lands in DISPLACEMENT_ACTIVE with the unit on a
    hazard hold, the allotment suspended and an abatement already posted.
    """
    assess_overrides = {"affected_area_sqft": 45}
    assess_overrides.update(kwargs.pop("assess_overrides", None) or {})
    return setup_assessed_hazard(
        api,
        occupied_state=occupied_state,
        hazard_clock=hazard_clock,
        assess_overrides=assess_overrides,
        **kwargs,
    )


def setup_undisplaced_hazard(api, occupied_state=None, hazard_clock=None, **kwargs):
    """An assessed hazard mild enough to leave the family in place.

    Eight square feet of mold grades at the lowest severity, so no displacement
    is required and the case goes straight to remediation.
    """
    assess_overrides = {"affected_area_sqft": 8}
    assess_overrides.update(kwargs.pop("assess_overrides", None) or {})
    return setup_assessed_hazard(
        api,
        occupied_state=occupied_state,
        hazard_clock=hazard_clock,
        assess_overrides=assess_overrides,
        **kwargs,
    )


def find_remediation_work_order(api, hazard_case: dict) -> dict:
    """Resolve the remediation work order an assessment opened on the unit.

    Prefers the link the hazard case itself carries; falls back to the newest
    work order standing on the same unit.
    """
    linked_id = hazard_case.get("remediation_work_order_id")
    if linked_id:
        return read_work_order(api, linked_id)
    body = api.list_work_orders(
        TEST_USERS["property_manager_headers"],
        params={"housing_unit_id": hazard_case["housing_unit_id"], "limit": 100},
    )
    rows = get_success_data(body)
    assert rows, "expected a remediation work order on the hazard case's unit"
    return rows[-1]


def complete_remediation(api, hazard_case: dict) -> dict:
    """Drive the hazard case's remediation work order through to completion."""
    work_order = find_remediation_work_order(api, hazard_case)
    if work_order["status"] == "SUBMITTED":
        assign_work_order(api, work_order["id"])
        work_order = read_work_order(api, work_order["id"])
    if work_order["status"] == "ASSIGNED":
        work_order = start_work_order(api, work_order["id"])
    if work_order["status"] == "IN_PROGRESS":
        work_order = complete_work_order(api, work_order["id"])
    return work_order


# --- Tier 4: displacement lodging ------------------------------------------


def authorize_lodging(api, hazard_case_id, lease_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_displacement_lodging(
            f.create_displacement_lodging_payload(
                hazard_case_id, lease_id, **overrides
            ),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def close_lodging(api, lodging_id, actual_end_date, headers=None) -> dict:
    return get_success_data(
        api.close_displacement_lodging(
            lodging_id,
            f.close_lodging_payload(actual_end_date),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def setup_lodged_household(api, displaced_state=None, lodging_overrides=None, **kwargs):
    """Displaced household with one authorized lodging interval.

    Returns the tenancy dict with ``hazard_case`` and ``lodging``.
    """
    state = (
        displaced_state
        if displaced_state is not None
        else setup_displaced_household(api, **kwargs)
    )
    state["lodging"] = authorize_lodging(
        api,
        state["hazard_case"]["id"],
        state["lease"]["id"],
        **(lodging_overrides or {}),
    )
    return state


# --- Tier 4: dispute cases -------------------------------------------------


def open_dispute(api, lease_id, sponsor, **overrides) -> dict:
    return get_success_data(
        api.create_dispute_case(
            f.create_dispute_case_payload(lease_id, sponsor["id"], **overrides),
            make_service_member_headers(sponsor["id"]),
        )
    )


def propose_resolution(api, dispute_case_id, remedy, credit_cents, headers=None):
    return get_success_data(
        api.propose_resolution(
            dispute_case_id,
            f.propose_resolution_payload(remedy, credit_cents),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def respond_to_proposal(api, dispute_case_id, sponsor, accepted: bool) -> dict:
    return get_success_data(
        api.respond_to_proposal(
            dispute_case_id,
            f.respond_payload(accepted),
            make_service_member_headers(sponsor["id"]),
        )
    )


def decide_escalated_dispute(api, dispute_case_id, award_cents, headers=None, **kw):
    return get_success_data(
        api.decide_escalated_dispute(
            dispute_case_id,
            f.installation_decision_payload(award_cents, **kw),
            headers or TEST_USERS["installation_housing_office_headers"],
        )
    )


def setup_open_dispute(api, occupied_state=None, dispute_clock=None, **overrides):
    """Occupied tenancy plus one dispute the resident has just filed."""
    state = occupied_state if occupied_state is not None else setup_occupied_lease(api)
    if dispute_clock is not None:
        set_clock(api, dispute_clock)
    state["dispute"] = open_dispute(
        api, state["lease"]["id"], state["sponsor"], **overrides
    )
    return state


def setup_resolved_dispute(
    api,
    occupied_state=None,
    dispute_clock=None,
    credit_offer_cents=25000,
    remedy="One month of rent credited back to the allotment",
):
    """A dispute the resident accepted, so its credit has been awarded."""
    state = setup_open_dispute(
        api, occupied_state=occupied_state, dispute_clock=dispute_clock
    )
    propose_resolution(api, state["dispute"]["id"], remedy, credit_offer_cents)
    state["dispute"] = respond_to_proposal(
        api, state["dispute"]["id"], state["sponsor"], True
    )
    state["lease"] = read_lease(api, state["lease"]["id"])
    return state


# --- Tier 4: termination ---------------------------------------------------


def give_termination_notice(
    api,
    lease_id,
    reason,
    notice_date,
    effective_date,
    headers=None,
    **overrides,
) -> dict:
    return get_success_data(
        api.give_termination_notice(
            lease_id,
            f.termination_notice_payload(
                reason, notice_date, effective_date, **overrides
            ),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def terminate_lease(api, lease_id, headers=None) -> dict:
    return get_success_data(
        api.terminate_lease(lease_id, headers or TEST_USERS["property_manager_headers"])
    )


def setup_lease_under_notice(
    api,
    occupied_state=None,
    reason="CONVENIENCE",
    notice_date="2026-09-05",
    effective_date="2026-10-19",
    notice_clock=None,
    **overrides,
):
    """Occupied tenancy carried forward to NOTICE_GIVEN."""
    state = occupied_state if occupied_state is not None else setup_occupied_lease(api)
    if notice_clock is not None:
        set_clock(api, notice_clock)
    state["lease"] = give_termination_notice(
        api,
        state["lease"]["id"],
        reason,
        notice_date,
        effective_date,
        **overrides,
    )
    return state


# --- Tier 4: periodic operations -------------------------------------------


def run_allotment_run(api, installation_id, period_month, headers=None) -> dict:
    return get_success_data(
        api.run_allotment_run(
            installation_id,
            f.allotment_run_payload(period_month),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def run_metrics_run(api, account_id, period_month, headers=None) -> dict:
    return get_success_data(
        api.run_metrics_run(
            account_id,
            f.metrics_run_payload(period_month),
            headers or TEST_USERS["platform_admin_headers"],
        )
    )


def authorize_expenditure(
    api, account_id, expected_version, amount_cents, headers=None, **overrides
) -> dict:
    return get_success_data(
        api.authorize_expenditure(
            account_id,
            f.expenditure_payload(expected_version, amount_cents, **overrides),
            headers or TEST_USERS["property_manager_headers"],
        )
    )


def setup_charged_lease(api, occupied_state=None, period_month="2026-09"):
    """Occupied tenancy whose monthly rent has already been charged.

    Returns the tenancy dict with ``lease`` re-read and ``ledger`` holding the
    rows the run posted.
    """
    state = occupied_state if occupied_state is not None else setup_occupied_lease(api)
    run_allotment_run(api, state["installation"]["id"], period_month)
    state["lease"] = read_lease(api, state["lease"]["id"])
    state["ledger"] = read_ledger(api, state["lease"]["id"])
    return state


def setup_account(api, installation_id=None, occupied_state=None, **overrides):
    """A reinvestment account, optionally alongside the canonical tenancy.

    Returns a dict: either the tenancy dict with ``account`` added, or a bare
    ``{"account": ...}`` when only an installation id was supplied.
    """
    if occupied_state is not None:
        occupied_state["account"] = create_reinvestment_account(
            api, occupied_state["installation"]["id"], **overrides
        )
        return occupied_state
    return {"account": create_reinvestment_account(api, installation_id, **overrides)}


# --- Tier 5: multi-unit and multi-tenancy inventories ----------------------


def setup_multi_unit_installation(
    api, unit_specs, clock=CLOCK_BEFORE_ARRIVAL, installation_overrides=None
):
    """One installation and a list of housing units built in the given order.

    Returns a dict with ``installation`` and ``units`` (a list, in creation
    order, which is the order the offer run and the listings walk).
    """
    if clock is not None:
        set_clock(api, clock)
    installation = create_installation(api, **(installation_overrides or {}))
    units = [create_housing_unit(api, installation["id"], **spec) for spec in unit_specs]
    return {
        "installation": read_installation(api, installation["id"]),
        "units": units,
    }


SENIOR_ENLISTED_UNIT = {
    "unit_code": "B-200",
    "bedroom_count": 3,
    "unit_type": "SFH",
    "designated_rank_category": "SENIOR_ENLISTED",
    "historic_flag": False,
}

SENIOR_ENLISTED_SPONSOR = {
    "dodid": "1000000002",
    "last_name": "Okafor",
    "first_name": "Ben",
    "branch": "ARMY",
    "pay_grade": "E7",
}

SENIOR_ENLISTED_RATE = {
    "pay_grade": "E7",
    "with_dependents": True,
    "effective_year": 2026,
    "monthly_rate_cents": 268000,
    "utility_allowance_cents": 20000,
}


def setup_two_occupied_tenancies(api, move_in_clock=CLOCK_AT_MOVE_IN):
    """Two occupied leases at one installation, on two differently priced units.

    The junior-enlisted E5 family takes the two-bedroom TOWNHOME and the
    senior-enlisted E7 family takes the three-bedroom SFH, so the pair exercises
    every per-lease figure twice over on different inputs.

    Returns a dict with ``installation``, ``units`` (both, in creation order),
    ``sponsors``, ``applications``, ``leases`` and ``inspections`` — each list
    ordered junior family first.
    """
    set_clock(api, CLOCK_BEFORE_ARRIVAL)
    installation = create_installation(api)
    inst_id = installation["id"]
    rates = [
        create_bah_rate(api, inst_id),
        create_bah_rate(api, inst_id, **SENIOR_ENLISTED_RATE),
    ]
    units = [
        create_housing_unit(api, inst_id),
        create_housing_unit(api, inst_id, **SENIOR_ENLISTED_UNIT),
    ]
    junior, junior_deps = setup_sponsor_family(api)
    senior, senior_deps = setup_sponsor_family(
        api, dependents=SENIOR_ENLISTED_DEPENDENTS, **SENIOR_ENLISTED_SPONSOR
    )
    applications = [
        submit_application(api, inst_id, junior),
        submit_application(api, inst_id, senior),
    ]
    run_offer_run(api, inst_id)
    applications = [
        accept_offer(api, applications[0]["id"], junior),
        accept_offer(api, applications[1]["id"], senior),
    ]
    leases = [
        write_lease(api, applications[0]["id"], units[0]["id"]),
        write_lease(api, applications[1]["id"], units[1]["id"]),
    ]
    inspections = []
    for lease, sponsor in ((leases[0], junior), (leases[1], senior)):
        inspection = schedule_inspection(api, lease["id"])
        inspections.append(
            acknowledge_inspection(
                api,
                inspection["id"],
                sponsor,
                f"{sponsor['first_name']} {sponsor['last_name']}",
                installation["bill_of_rights_version"],
            )
        )
    if move_in_clock is not None:
        set_clock(api, move_in_clock)
    leases = [move_in(api, leases[0]["id"]), move_in(api, leases[1]["id"])]
    return {
        "installation": read_installation(api, inst_id),
        "bah_rates": rates,
        "units": [read_housing_unit(api, unit["id"]) for unit in units],
        "sponsors": [junior, senior],
        "dependents": [junior_deps, senior_deps],
        "applications": applications,
        "leases": leases,
        "inspections": inspections,
    }


def setup_pending_application(
    api,
    clock=CLOCK_BEFORE_ARRIVAL,
    installation_overrides=None,
    rate_overrides=None,
    unit_specs=(),
    dependents=CANONICAL_DEPENDENTS,
    sponsor_overrides=None,
    application_overrides=None,
):
    """An installation, a rate row, a sponsor family and a PENDING application.

    Housing units are optional here — ``unit_specs`` may be empty, which is how
    a test can watch an offer run against an inventory it grows itself.
    Returns a dict with ``installation``, ``bah_rate``, ``units``, ``sponsor``,
    ``dependents`` and ``application``.
    """
    if clock is not None:
        set_clock(api, clock)
    installation = create_installation(api, **(installation_overrides or {}))
    bah_rate = create_bah_rate(api, installation["id"], **(rate_overrides or {}))
    units = [
        create_housing_unit(api, installation["id"], **spec) for spec in unit_specs
    ]
    sponsor, deps = setup_sponsor_family(
        api, dependents=dependents, **(sponsor_overrides or {})
    )
    application = submit_application(
        api, installation["id"], sponsor, **(application_overrides or {})
    )
    return {
        "installation": read_installation(api, installation["id"]),
        "bah_rate": bah_rate,
        "units": units,
        "sponsor": sponsor,
        "dependents": deps,
        "application": application,
    }


# A pair of families whose only difference is one day of a child's birthday:
# on a control date of 2026-08-25 the first family's elder child has reached
# ten and the second family's has not.
BIRTHDAY_ON_CONTROL_DATE_SPONSOR = {
    "dodid": "1000000003",
    "last_name": "Nakamura",
    "first_name": "Sora",
    "branch": "ARMY",
    "pay_grade": "E5",
}

BIRTHDAY_ON_CONTROL_DATE_DEPENDENTS = (
    {"relationship": "SPOUSE", "date_of_birth": "1990-01-01", "gender": "FEMALE"},
    {"relationship": "CHILD", "date_of_birth": "2016-08-25", "gender": "MALE"},
    {"relationship": "CHILD", "date_of_birth": "2019-05-05", "gender": "MALE"},
)

BIRTHDAY_AFTER_CONTROL_DATE_SPONSOR = {
    "dodid": "1000000004",
    "last_name": "Whitfield",
    "first_name": "Dana",
    "branch": "ARMY",
    "pay_grade": "E5",
}

BIRTHDAY_AFTER_CONTROL_DATE_DEPENDENTS = (
    {"relationship": "SPOUSE", "date_of_birth": "1990-01-01", "gender": "FEMALE"},
    {"relationship": "CHILD", "date_of_birth": "2016-08-26", "gender": "MALE"},
    {"relationship": "CHILD", "date_of_birth": "2019-05-05", "gender": "MALE"},
)


def setup_birthday_boundary_applications(api, clock=CLOCK_BEFORE_ARRIVAL):
    """Two applications differing only by one day of a child's date of birth.

    Returns a dict with ``installation``, ``on_the_day`` (sponsor, dependents,
    application) and ``the_day_after``.
    """
    if clock is not None:
        set_clock(api, clock)
    installation = create_installation(api)
    create_bah_rate(api, installation["id"])
    first, first_deps = setup_sponsor_family(
        api,
        dependents=BIRTHDAY_ON_CONTROL_DATE_DEPENDENTS,
        **BIRTHDAY_ON_CONTROL_DATE_SPONSOR,
    )
    second, second_deps = setup_sponsor_family(
        api,
        dependents=BIRTHDAY_AFTER_CONTROL_DATE_DEPENDENTS,
        **BIRTHDAY_AFTER_CONTROL_DATE_SPONSOR,
    )
    first_app = submit_application(api, installation["id"], first)
    second_app = submit_application(api, installation["id"], second)
    return {
        "installation": read_installation(api, installation["id"]),
        "on_the_day": {
            "sponsor": first,
            "dependents": first_deps,
            "application": first_app,
        },
        "the_day_after": {
            "sponsor": second,
            "dependents": second_deps,
            "application": second_app,
        },
    }


def setup_released_unit(
    api,
    notice_date,
    effective_date,
    reason="CONVENIENCE",
    notice_clock=None,
    terminate_clock=None,
    **kwargs,
):
    """A tenancy carried all the way to TERMINATED so its unit is free again.

    Returns the tenancy dict with ``lease`` in TERMINATED and ``unit`` re-read,
    which is how a unit acquires the end date the turn buffer is measured from.
    """
    state = setup_lease_under_notice(
        api,
        reason=reason,
        notice_date=notice_date,
        effective_date=effective_date,
        notice_clock=notice_clock,
        **kwargs,
    )
    if terminate_clock is not None:
        set_clock(api, terminate_clock)
    state["lease"] = terminate_lease(api, state["lease"]["id"])
    state["unit"] = read_housing_unit(api, state["unit"]["id"])
    state["installation"] = read_installation(api, state["installation"]["id"])
    return state


# Categories whose priority and clocks the SLA tests lean on.
EMERGENCY_WORK_ORDER = {
    "category": "NO_HEAT",
    "description": "No heat in the whole house",
    "habitability_impact": True,
}

URGENT_WORK_ORDER = {
    "category": "MOLD_SUSPECTED",
    "description": "Dark spotting on the bathroom ceiling",
    "habitability_impact": False,
}

ROUTINE_WORK_ORDER = {
    "category": "COSMETIC",
    "description": "Scuffed baseboard in the hallway",
    "habitability_impact": False,
}


def setup_work_order_on_occupied_unit(
    api, occupied_state=None, report_clock=None, **overrides
):
    """Occupied tenancy plus one freshly submitted work order on its unit.

    Returns the tenancy dict with ``work_order`` added.
    """
    state = occupied_state if occupied_state is not None else setup_occupied_lease(api)
    if report_clock is not None:
        set_clock(api, report_clock)
    state["work_order"] = submit_work_order(api, state["unit"]["id"], **overrides)
    return state
