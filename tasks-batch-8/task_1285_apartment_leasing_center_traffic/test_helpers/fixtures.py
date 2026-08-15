"""Composite setup helpers: multi-step arrangements reused across tests.

Every helper builds its preconditions from scratch against a fresh server and
returns parsed response data. Identity threading rule: after creating an Agent
or Application, every ownership-gated call uses make_leasing_agent_headers /
make_applicant_headers with the real entity id — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agent_payload,
    create_application_payload,
    create_floorplan_payload,
    create_inquiry_payload,
    create_lease_payload,
    create_move_in_payload,
    create_pricing_offer_payload,
    create_property_payload,
    create_tour_payload,
    create_waitlist_entry_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_leasing_agent_headers,
)

PM = TEST_USERS["property_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators and getters (all validated with
# get_success_data so setup failures surface as clear "Setup step failed").
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, PM))


def create_property(**overrides) -> dict:
    return get_success_data(api_client.create_property(create_property_payload(**overrides), PM))


def create_agent(property_id, **overrides) -> dict:
    return get_success_data(api_client.create_agent(
        create_agent_payload(property_id, **overrides), PM))


def create_floorplan(property_id, **overrides) -> dict:
    return get_success_data(api_client.create_floorplan(
        create_floorplan_payload(property_id, **overrides), PM))


def create_pricing_offer(property_id, floorplan_id, **overrides) -> dict:
    return get_success_data(api_client.create_pricing_offer(
        create_pricing_offer_payload(property_id, floorplan_id, **overrides), PM))


def publish_offer(pricing_offer_id) -> dict:
    return get_success_data(api_client.publish_pricing_offer(pricing_offer_id, PM))


def retire_offer(pricing_offer_id) -> dict:
    return get_success_data(api_client.retire_pricing_offer(pricing_offer_id, PM))


def create_inquiry(property_id, agent_id=None, **overrides) -> dict:
    """Create an inquiry. When agent_id is given the call is made by that
    LeasingAgent; otherwise by the shared PropertyManager."""
    headers = make_leasing_agent_headers(agent_id) if agent_id else PM
    return get_success_data(api_client.create_inquiry(
        create_inquiry_payload(property_id, **overrides), headers))


def claim_inquiry(inquiry_id, agent_id) -> dict:
    return get_success_data(api_client.claim_inquiry(
        inquiry_id, make_leasing_agent_headers(agent_id)))


def respond_inquiry(inquiry_id, agent_id) -> dict:
    return get_success_data(api_client.respond_inquiry(
        inquiry_id, make_leasing_agent_headers(agent_id)))


def mark_inquiry_lost(inquiry_id, agent_id) -> dict:
    return get_success_data(api_client.mark_inquiry_lost(
        inquiry_id, make_leasing_agent_headers(agent_id)))


def create_guided_tour(inquiry_id, agent_id, scheduled_start, scheduled_end) -> dict:
    return get_success_data(api_client.create_tour(
        create_tour_payload(inquiry_id, agent_id=agent_id,
                            scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        make_leasing_agent_headers(agent_id)))


def create_self_guided_tour(inquiry_id, agent_id, scheduled_start) -> dict:
    payload = create_tour_payload(inquiry_id, tour_type="SELF_GUIDED",
                                  scheduled_start=scheduled_start)
    payload.pop("scheduled_end", None)  # server-computed for self-guided tours
    return get_success_data(api_client.create_tour(
        payload, make_leasing_agent_headers(agent_id)))


def cancel_tour(tour_id, agent_id) -> dict:
    return get_success_data(api_client.cancel_tour(
        tour_id, make_leasing_agent_headers(agent_id)))


def create_waitlist_entry(floorplan_id, agent_id=None, **overrides) -> dict:
    headers = make_leasing_agent_headers(agent_id) if agent_id else PM
    return get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(floorplan_id, **overrides), headers))


def promote_waitlist_entry(entry_id, agent_id) -> dict:
    return get_success_data(api_client.promote_waitlist_entry(
        entry_id, make_leasing_agent_headers(agent_id)))


def decline_waitlist_entry(entry_id, agent_id) -> dict:
    return get_success_data(api_client.decline_waitlist_entry(
        entry_id, make_leasing_agent_headers(agent_id)))


def cancel_waitlist_entry(entry_id, agent_id) -> dict:
    return get_success_data(api_client.cancel_waitlist_entry(
        entry_id, make_leasing_agent_headers(agent_id)))


def create_application(floorplan_id, agent_id, inquiry_id=None, waitlist_entry_id=None,
                       **overrides) -> dict:
    payload = create_application_payload(floorplan_id, **overrides)
    if inquiry_id is not None:
        payload["inquiry_id"] = inquiry_id
    if waitlist_entry_id is not None:
        payload["waitlist_entry_id"] = waitlist_entry_id
    return get_success_data(api_client.create_application(
        payload, make_leasing_agent_headers(agent_id)))


def decide_application(application_id, decision) -> dict:
    return get_success_data(api_client.decide_application(application_id, decision, PM))


def rescreen_application(application_id, annual_income_cents, credit_score) -> dict:
    return get_success_data(api_client.rescreen_application(
        application_id,
        {"annual_income_cents": annual_income_cents, "credit_score": credit_score},
        PM))


def clear_conditions(application_id, deposit_paid_cents, agent_id) -> dict:
    return get_success_data(api_client.clear_application_conditions(
        application_id, deposit_paid_cents, make_leasing_agent_headers(agent_id)))


def withdraw_application(application_id, agent_id) -> dict:
    return get_success_data(api_client.withdraw_application(
        application_id, make_leasing_agent_headers(agent_id)))


def generate_lease(application_id, expected_application_version, **overrides) -> dict:
    return get_success_data(api_client.create_lease(
        create_lease_payload(application_id, expected_application_version, **overrides), PM))


def sign_lease(lease_id, application_id) -> dict:
    return get_success_data(api_client.sign_lease(
        lease_id, make_applicant_headers(application_id)))


def countersign_lease(lease_id) -> dict:
    return get_success_data(api_client.countersign_lease(lease_id, PM))


def cancel_lease(lease_id) -> dict:
    return get_success_data(api_client.cancel_lease(lease_id, PM))


def create_move_in(lease_id, scheduled_date, agent_id) -> dict:
    return get_success_data(api_client.create_move_in(
        create_move_in_payload(lease_id, scheduled_date=scheduled_date),
        make_leasing_agent_headers(agent_id)))


def get_property(property_id) -> dict:
    return get_success_data(api_client.get_property(property_id, PM))


def get_floorplan(floorplan_id) -> dict:
    return get_success_data(api_client.get_floorplan(floorplan_id, PM))


def get_pricing_offer(pricing_offer_id) -> dict:
    return get_success_data(api_client.get_pricing_offer(pricing_offer_id, PM))


def get_inquiry(inquiry_id) -> dict:
    return get_success_data(api_client.get_inquiry(inquiry_id, PM))


def get_tour(tour_id) -> dict:
    return get_success_data(api_client.get_tour(tour_id, PM))


def get_waitlist_entry(entry_id) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, PM))


def get_application(application_id) -> dict:
    return get_success_data(api_client.get_application(application_id, PM))


def get_lease(lease_id) -> dict:
    return get_success_data(api_client.get_lease(lease_id, PM))


def get_move_in(move_in_id) -> dict:
    return get_success_data(api_client.get_move_in(move_in_id, PM))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_contacted_inquiry(property_id, agent_id, **overrides) -> dict:
    """Inquiry walked NEW -> (claim) -> (respond) -> CONTACTED."""
    inquiry = create_inquiry(property_id, agent_id=agent_id, **overrides)
    claim_inquiry(inquiry["id"], agent_id)
    return respond_inquiry(inquiry["id"], agent_id)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_site(property_overrides=None, agent_overrides=None,
               floorplan_overrides=None) -> dict:
    """Property + home agent + floorplan. Returns {"property", "agent", "floorplan"}."""
    prop = create_property(**(property_overrides or {}))
    agent = create_agent(prop["id"], **(agent_overrides or {}))
    floorplan = create_floorplan(prop["id"], **(floorplan_overrides or {}))
    return {"property": prop, "agent": agent, "floorplan": floorplan}


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def add_leasable_application(site, decision="APPROVED", app_overrides=None,
                             inquiry_overrides=None) -> dict:
    """On an existing site: CONTACTED inquiry -> application (SCREENING) ->
    optional decide. Returns {"inquiry", "application", "application_version"}
    where application_version is the version after the last write."""
    agent_id = site["agent"]["id"]
    inquiry = create_contacted_inquiry(
        site["property"]["id"], agent_id,
        floorplan_id=site["floorplan"]["id"], **(inquiry_overrides or {}))
    application = create_application(
        site["floorplan"]["id"], agent_id, inquiry_id=inquiry["id"],
        **(app_overrides or {}))
    version = application["version"]
    if decision is not None:
        version = decide_application(application["id"], decision)["version"]
        application = get_application(application["id"])
    return {"inquiry": inquiry, "application": application,
            "application_version": version}


def add_issued_lease(site, decision="APPROVED", app_overrides=None,
                     inquiry_overrides=None, lease_overrides=None) -> dict:
    """add_leasable_application + lease generation. Returns the application
    bundle plus "lease"."""
    bundle = add_leasable_application(site, decision=decision,
                                      app_overrides=app_overrides,
                                      inquiry_overrides=inquiry_overrides)
    lease = generate_lease(bundle["application"]["id"],
                           bundle["application_version"], **(lease_overrides or {}))
    bundle["lease"] = lease
    return bundle


def add_executed_lease(site, decision="APPROVED", app_overrides=None,
                       inquiry_overrides=None, lease_overrides=None) -> dict:
    """Full pipeline: inquiry -> application -> decide -> lease -> sign ->
    countersign (EXECUTED). Returns {"inquiry", "application", "lease",
    "application_version"}."""
    bundle = add_issued_lease(site, decision=decision, app_overrides=app_overrides,
                              inquiry_overrides=inquiry_overrides,
                              lease_overrides=lease_overrides)
    sign_lease(bundle["lease"]["id"], bundle["application"]["id"])
    bundle["lease"] = countersign_lease(bundle["lease"]["id"])
    bundle["application"] = get_application(bundle["application"]["id"])
    return bundle


def add_conditions_cleared_application(site, deposit_payment_cents=None,
                                       app_overrides=None,
                                       inquiry_overrides=None) -> dict:
    """Application decided APPROVED_WITH_CONDITIONS, then cleared by a deposit
    payment covering the requirement. Returns the bundle with the post-clearance
    application and version."""
    bundle = add_leasable_application(site, decision="APPROVED_WITH_CONDITIONS",
                                      app_overrides=app_overrides,
                                      inquiry_overrides=inquiry_overrides)
    required = bundle["application"]["required_deposit_cents"]
    payment = deposit_payment_cents if deposit_payment_cents is not None else required
    cleared = clear_conditions(bundle["application"]["id"], payment,
                               site["agent"]["id"])
    bundle["application"] = cleared
    bundle["application_version"] = cleared["version"]
    return bundle


# ---------------------------------------------------------------------------
# Tier 4/5: occupied-unit waitlist arrangements
# ---------------------------------------------------------------------------

def setup_occupied_floorplan(execute_lease=True, property_overrides=None,
                             floorplan_overrides=None) -> dict:
    """Site whose floorplan (default 1 unit) is fully committed by a lease —
    ISSUED when execute_lease is False, EXECUTED otherwise. Returns
    {"site", "pipeline"} where pipeline is the lease bundle."""
    fp_overrides = {"total_units": 1}
    fp_overrides.update(floorplan_overrides or {})
    site = setup_site(property_overrides=property_overrides,
                      floorplan_overrides=fp_overrides)
    if execute_lease:
        pipeline = add_executed_lease(site)
    else:
        pipeline = add_issued_lease(site)
    return {"site": site, "pipeline": pipeline}


def setup_offered_waitlist(num_entries=1, execute_lease=True,
                           property_overrides=None) -> dict:
    """Occupied floorplan + N waitlist entries, then the occupying lease is
    cancelled so the queue head is auto-promoted to OFFERED.
    Returns {"site", "pipeline", "entries", "lease"} (lease is CANCELLED)."""
    occ = setup_occupied_floorplan(execute_lease=execute_lease,
                                   property_overrides=property_overrides)
    site, pipeline = occ["site"], occ["pipeline"]
    agent_id = site["agent"]["id"]
    entries = [
        create_waitlist_entry(site["floorplan"]["id"], agent_id,
                              contact_name=f"Waitlist {i + 1}",
                              contact_email=f"wait{i + 1}@example.com")
        for i in range(num_entries)
    ]
    lease = cancel_lease(pipeline["lease"]["id"])
    return {"site": site, "pipeline": pipeline, "entries": entries, "lease": lease}
