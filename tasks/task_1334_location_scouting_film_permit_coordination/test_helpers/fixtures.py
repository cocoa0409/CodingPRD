"""Composite setup helpers.

Multi-step API preambles shared by many tests. Every helper builds its state
from scratch using only PRD-declared endpoints (the harness restarts the server
with an empty database before every test). Setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.

Conventions
-----------
- Each helper returns a dict of the entities/ids it created plus, where
  relevant, the caller's own entity id for ownership-gated follow-up calls.
- The OwnerRep role is entity-backed: after creating a LocationOwner, any
  OwnerRep call uses make_owner_rep_headers(owner["id"]).
- The default logical clock at startup is 2026-08-01T00:00:00Z; helpers that
  need a specific submit/posting date set the clock explicitly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_insurance_certificate_payload,
    create_jurisdiction_payload,
    create_location_payload,
    create_monitor_assignment_payload,
    create_notification_payload,
    create_owner_agreement_payload,
    create_owner_payload,
    create_permit_application_payload,
    create_production_payload,
    create_scout_package_payload,
    create_shoot_day_payload,
    create_street_closure_payload,
    create_walkthrough_report_payload,
)
from .test_users import TEST_USERS, make_owner_rep_headers

LM = TEST_USERS["location_manager_headers"]
FO = TEST_USERS["film_office_headers"]


def set_clock(to_iso8601: str):
    """Advance the server logical clock (FilmOffice-only test-driving call)."""
    resp = api_client.set_clock(to_iso8601, FO)
    get_success_data(resp)


def sweep():
    """Run the operations sweep."""
    resp = api_client.ops_sweep(FO)
    return get_success_data(resp)


def create_jurisdiction(**overrides):
    resp = api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), FO)
    return get_success_data(resp)


def create_owner(**overrides):
    resp = api_client.create_owner(create_owner_payload(**overrides), LM)
    return get_success_data(resp)


def create_location(jurisdiction_id, owner_id, **overrides):
    resp = api_client.create_location(create_location_payload(jurisdiction_id, owner_id, **overrides), LM)
    return get_success_data(resp)


def create_production(**overrides):
    resp = api_client.create_production(create_production_payload(**overrides), LM)
    return get_success_data(resp)


def setup_basic_scenario(jurisdiction_overrides=None, location_overrides=None,
                         owner_overrides=None, production_overrides=None):
    """Jurisdiction + owner + location + production. Returns dict of the four."""
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    owner = create_owner(**(owner_overrides or {}))
    location = create_location(jurisdiction["id"], owner["id"], **(location_overrides or {}))
    production = create_production(**(production_overrides or {}))
    return {
        "jurisdiction": jurisdiction,
        "owner": owner,
        "location": location,
        "production": production,
    }


def setup_accepted_scout_package(production, location, package_overrides=None):
    """Create -> submit -> ACCEPT a scout package. Returns the ACCEPTED package."""
    payload = create_scout_package_payload(location["id"], **(package_overrides or {}))
    package = get_success_data(api_client.create_scout_package(production["id"], payload, LM))
    get_success_data(api_client.submit_scout_package(production["id"], package["id"], LM))
    return get_success_data(api_client.review_scout_package(production["id"], package["id"], "ACCEPT", FO))


def setup_draft_agreement(production, location, agreement_overrides=None):
    """Create an OwnerAgreement in DRAFT (round_count 0)."""
    payload = create_owner_agreement_payload(location["id"], **(agreement_overrides or {}))
    return get_success_data(api_client.create_owner_agreement(production["id"], payload, LM))


def setup_executed_agreement(production, location, owner, rate=150_000,
                             agreement_overrides=None):
    """Drive an agreement DRAFT -> PROPOSED -> EXECUTED via OwnerRep accept."""
    agreement = setup_draft_agreement(production, location, agreement_overrides)
    get_success_data(api_client.propose_owner_agreement(production["id"], agreement["id"], rate, LM))
    executed = get_success_data(
        api_client.accept_owner_agreement(production["id"], agreement["id"], make_owner_rep_headers(owner["id"]))
    )
    return executed


def setup_production_with_executed_agreement(jurisdiction_overrides=None, location_overrides=None,
                                             owner_overrides=None, production_overrides=None,
                                             rate=150_000, agreement_overrides=None):
    """Stage chain through an EXECUTED agreement. Returns scenario dict."""
    scenario = setup_basic_scenario(jurisdiction_overrides, location_overrides,
                                    owner_overrides, production_overrides)
    scenario["scout_package"] = setup_accepted_scout_package(scenario["production"], scenario["location"])
    scenario["agreement"] = setup_executed_agreement(
        scenario["production"], scenario["location"], scenario["owner"], rate, agreement_overrides
    )
    return scenario


def create_draft_permit(scenario, expected_production_version=None, **permit_overrides):
    """Create a DRAFT PermitApplication. Re-reads the Production version when no
    explicit expected_production_version is supplied."""
    production_id = scenario["production"]["id"]
    if expected_production_version is None:
        expected_production_version = get_success_data(
            api_client.get_production(production_id, LM)
        )["version"]
    payload = create_permit_application_payload(
        scenario["location"]["id"], expected_production_version, **permit_overrides
    )
    return get_success_data(api_client.create_permit_application(production_id, payload, LM))


def setup_submitted_permit(scenario, clock=None, **permit_overrides):
    """EXECUTED agreement chain + permit DRAFT -> SUBMITTED."""
    if clock is not None:
        set_clock(clock)
    permit = create_draft_permit(scenario, **permit_overrides)
    production_id = scenario["production"]["id"]
    return get_success_data(api_client.submit_permit_application(production_id, permit["id"], LM))


def setup_under_review_permit(scenario, clock=None, **permit_overrides):
    """Permit SUBMITTED -> UNDER_REVIEW (requires the lead-time gate to pass)."""
    permit = setup_submitted_permit(scenario, clock, **permit_overrides)
    production_id = scenario["production"]["id"]
    return get_success_data(api_client.start_review_permit_application(production_id, permit["id"], FO))


def setup_verified_insurance(scenario, **certificate_overrides):
    """Present + verify a certificate covering the permit window."""
    production_id = scenario["production"]["id"]
    payload = create_insurance_certificate_payload(scenario["jurisdiction"]["id"], **certificate_overrides)
    certificate = get_success_data(api_client.create_insurance_certificate(production_id, payload, LM))
    return get_success_data(api_client.verify_insurance_certificate(production_id, certificate["id"], FO))


def setup_issued_permit(scenario, clock=None, with_notification=True, **permit_overrides):
    """Full chain to an ISSUED permit (direct ISSUE from UNDER_REVIEW).

    When with_notification is true (default), an adequate notification is posted
    and acknowledged as well — required downstream by mark-ready.
    Returns (permit, certificate, notification_or_None).
    """
    production_id = scenario["production"]["id"]
    permit = setup_under_review_permit(scenario, clock, **permit_overrides)
    certificate = setup_verified_insurance(scenario)
    issued = get_success_data(
        api_client.decide_permit_application(production_id, permit["id"], "ISSUE", FO)
    )
    notification = None
    if with_notification:
        payload = create_notification_payload(issued["id"])
        notification = get_success_data(api_client.create_notification(production_id, payload, LM))
        get_success_data(api_client.acknowledge_notification(production_id, notification["id"], FO))
    return issued, certificate, notification


def setup_funded_deposit(scenario, amount=None):
    """Open the location's deposit account and fund it to its required amount."""
    production_id = scenario["production"]["id"]
    account = get_success_data(
        api_client.create_deposit_account(production_id, {"location_id": scenario["location"]["id"]}, LM)
    )
    if amount is None:
        amount = account["required_amount_cents"]
    if amount:
        account = get_success_data(api_client.deposit_into_account(production_id, account["id"], amount, LM))
    return account


def setup_signed_pre_walkthrough(scenario):
    """Create + sign a PRE walkthrough report for the location."""
    production_id = scenario["production"]["id"]
    payload = create_walkthrough_report_payload(scenario["location"]["id"], "PRE")
    report = get_success_data(api_client.create_walkthrough_report(production_id, payload, LM))
    return get_success_data(api_client.sign_walkthrough_report(production_id, report["id"], LM))


def setup_planned_shoot_day(scenario, permit, **day_overrides):
    """Create a PLANNED shoot day under the given permit."""
    production_id = scenario["production"]["id"]
    payload = create_shoot_day_payload(permit["id"], scenario["location"]["id"], **day_overrides)
    return get_success_data(api_client.create_shoot_day(production_id, payload, LM))


def setup_confirmed_monitor(scenario, shoot_day, monitor_type="FILM_OFFICER", officer_badge="FO-1"):
    """Assign + confirm a monitor on the day. Returns the CONFIRMED assignment."""
    production_id = scenario["production"]["id"]
    payload = create_monitor_assignment_payload(
        shoot_day["id"], monitor_type=monitor_type, officer_badge=officer_badge
    )
    assignment = get_success_data(api_client.create_monitor_assignment(production_id, payload, LM))
    return get_success_data(api_client.confirm_monitor_assignment(production_id, assignment["id"], FO))


def mark_day_ready(scenario, shoot_day):
    """Fresh read of the day, then mark-ready with the current version (OCC)."""
    production_id = scenario["production"]["id"]
    current = get_success_data(api_client.get_shoot_day(production_id, shoot_day["id"], LM))
    return get_success_data(
        api_client.mark_shoot_day_ready(production_id, shoot_day["id"], current["version"], LM)
    )


def setup_ready_day(jurisdiction_overrides=None, location_overrides=None,
                    owner_overrides=None, production_overrides=None,
                    rate=150_000, agreement_overrides=None, permit_overrides=None,
                    clock="2026-08-03T09:00:00Z", monitors=None, day_overrides=None,
                    closure_overrides=None, with_deposit=True, with_pre_walkthrough=True,
                    with_notification=True, mark_ready=True):
    """Full readiness chain: EXECUTED agreement -> ISSUED permit -> ACKED
    notification -> (optionally APPROVED closure) -> funded deposit -> SIGNED PRE
    -> PLANNED day -> confirmed monitors -> READY (production flips ACTIVE).

    monitors: list of {"monitor_type": ..., "officer_badge": ...}; defaults to one
    FILM_OFFICER when the permit has no lanes and the cast is below the large-cast
    threshold. Callers needing lanes/cast-driven coverage must pass the full list.
    mark_ready=False stops the chain before the READY transition so the caller can
    drive mark-ready itself (used when a readiness gate is expected to fail).
    Returns a dict with every entity created.
    """
    scenario = setup_production_with_executed_agreement(
        jurisdiction_overrides=jurisdiction_overrides,
        location_overrides=location_overrides,
        owner_overrides=owner_overrides,
        production_overrides=production_overrides,
        rate=rate,
        agreement_overrides=agreement_overrides,
    )
    production_id = scenario["production"]["id"]
    permit, certificate, notification = setup_issued_permit(
        scenario, clock=clock, with_notification=with_notification, **(permit_overrides or {})
    )
    result = dict(scenario)
    result.update({"permit": permit, "certificate": certificate, "notification": notification})

    if closure_overrides is not None:
        payload = create_street_closure_payload(permit["id"], **closure_overrides)
        closure = get_success_data(api_client.create_street_closure(production_id, payload, LM))
        closure = get_success_data(api_client.approve_street_closure(production_id, closure["id"], FO))
        result["closure"] = closure

    if with_deposit:
        result["deposit_account"] = setup_funded_deposit(scenario)
    if with_pre_walkthrough:
        result["pre_walkthrough"] = setup_signed_pre_walkthrough(scenario)

    day = setup_planned_shoot_day(scenario, permit, **(day_overrides or {}))
    result["shoot_day"] = day

    if monitors is None:
        monitors = [{"monitor_type": "FILM_OFFICER", "officer_badge": "FO-1"}]
    result["monitors"] = [
        setup_confirmed_monitor(scenario, day, m.get("monitor_type", "FILM_OFFICER"), m.get("officer_badge", f"FO-{i + 1}"))
        for i, m in enumerate(monitors)
    ]

    if mark_ready:
        result["shoot_day"] = mark_day_ready(scenario, result["shoot_day"])
    return result


def setup_in_progress_day(clock_on_day="2026-08-10T08:00:00Z", **kwargs):
    """READY chain plus the clock moved to the shoot date and an ops sweep, so the
    day is IN_PROGRESS. Returns the setup_ready_day dict (shoot_day refreshed)."""
    result = setup_ready_day(**kwargs)
    set_clock(clock_on_day)
    sweep()
    production_id = result["production"]["id"]
    result["shoot_day"] = get_success_data(
        api_client.get_shoot_day(production_id, result["shoot_day"]["id"], LM)
    )
    return result
