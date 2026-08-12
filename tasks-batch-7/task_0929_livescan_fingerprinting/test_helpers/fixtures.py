"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only PRD-declared endpoints.  Setup calls go
through get_success_data() so a broken precondition reports as "Setup failed"
rather than as a confusing assertion inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import POSITION_CODES, TEST_DEFAULTS
from .factories import (
    check_in_payload,
    create_agency_payload,
    create_appointment_payload,
    create_applicant_payload,
    create_card_payload,
    create_device_assignment_payload,
    create_device_payload,
    create_fixed_site_payload,
    create_invoice_payload,
    create_mobile_event_payload,
    create_ori_payload,
    create_service_type_payload,
    create_submission_payload,
    destination_result_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
SUP = TEST_USERS["supervisor_headers"]
ADJ = TEST_USERS["adjudicator_headers"]
DEST = TEST_USERS["destination_headers"]

DEFAULT_CLOCK_START = "2026-06-01T09:00:00Z"
DEFAULT_SCHEDULED_START = "2026-06-01T10:00:00Z"
DEFAULT_CHECKIN_CLOCK = "2026-06-01T09:55:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, VA))


def new_agency(**overrides) -> dict:
    return get_success_data(api_client.create_agency(create_agency_payload(**overrides), VA))


def new_ori(agency_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_ori(create_ori_payload(agency_id, **overrides), VA))


def new_service_type(ori_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_type(create_service_type_payload(ori_id, **overrides), VA)
    )


def new_fixed_site(**overrides) -> dict:
    return get_success_data(api_client.create_site(create_fixed_site_payload(**overrides), VA))


def new_mobile_event(host_agency_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_site(create_mobile_event_payload(host_agency_id, **overrides), VA)
    )


def new_device(home_site_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_device(create_device_payload(home_site_id, **overrides), VA))


def new_device_assignment(device_id: str, site_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_device_assignment(
            create_device_assignment_payload(device_id, site_id, **overrides), headers or SUP
        )
    )


def new_applicant(**overrides) -> dict:
    return get_success_data(api_client.create_applicant(create_applicant_payload(**overrides), TECH))


def new_appointment(applicant_id, site_id, service_type_id, scheduled_start, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            create_appointment_payload(
                applicant_id, site_id, service_type_id, scheduled_start, **overrides
            ),
            headers or TECH,
        )
    )


def check_in(appointment_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.check_in_appointment(appointment_id, check_in_payload(**overrides), headers or TECH)
    )


def open_card(appointment_id: str, device_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_card(create_card_payload(appointment_id, device_id, **overrides), headers or TECH)
    )


def score_position(card_id: str, position_code: str, score: int, headers=None) -> dict:
    return get_success_data(api_client.record_attempt(card_id, position_code, score, headers or TECH))


def code_position_exception(card_id: str, position_code: str, exception_code: str, headers=None) -> dict:
    return get_success_data(
        api_client.code_exception(card_id, position_code, exception_code, headers or TECH)
    )


def pass_positions(card_id: str, score: int = None, position_codes=None, headers=None) -> None:
    """Record one passing attempt on each of the named positions."""
    score = TEST_DEFAULTS["GOOD_SCORE"] if score is None else score
    for code in position_codes if position_codes is not None else POSITION_CODES:
        score_position(card_id, code, score, headers)


def finalize_card(card_id: str, headers=None) -> dict:
    return get_success_data(api_client.finalize_card(card_id, headers or TECH))


def transmit_card(card_id: str, expected_card_version: int, retention_requested: bool = False, headers=None) -> dict:
    return get_success_data(
        api_client.create_submission(
            create_submission_payload(card_id, expected_card_version, retention_requested),
            headers or TECH,
        )
    )


def post_result(submission_id: str, destination: str, result_code: str, headers=None, **extra) -> dict:
    return get_success_data(
        api_client.post_destination_result(
            submission_id, destination_result_payload(destination, result_code, **extra), headers or DEST
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def setup_registry(
    agency_overrides=None,
    ori_overrides=None,
    service_type_overrides=None,
    site_overrides=None,
    device_overrides=None,
    clock_start: str = DEFAULT_CLOCK_START,
    with_device: bool = True,
) -> dict:
    """Clock + agency + ORI + service type + FIXED site (+ device).

    Returns a mutable world dict the later tiers extend in place.
    """
    if clock_start:
        set_clock(clock_start)
    agency = new_agency(**(agency_overrides or {}))
    ori = new_ori(agency["id"], **(ori_overrides or {}))
    service_type = new_service_type(ori["id"], **(service_type_overrides or {}))
    site = new_fixed_site(**(site_overrides or {}))
    world = {"agency": agency, "ori": ori, "service_type": service_type, "site": site}
    if with_device:
        world["device"] = new_device(site["id"], **(device_overrides or {}))
    return world


def setup_mobile_registry(
    event_overrides=None,
    roster: bool = True,
    roster_overrides=None,
    **registry_kwargs,
) -> dict:
    """Registry plus a MOBILE_EVENT site hosted by the agency and a rostered device.

    The FIXED site created by setup_registry stays as the device's home depot;
    world["event_site"] is where the capture actually happens.
    """
    world = setup_registry(**registry_kwargs)
    world["home_site"] = world["site"]
    world["event_site"] = new_mobile_event(world["agency"]["id"], **(event_overrides or {}))
    if roster and "device" in world:
        world["assignment"] = new_device_assignment(
            world["device"]["id"], world["event_site"]["id"], **(roster_overrides or {})
        )
    return world


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def add_applicant_and_appointment(
    world: dict,
    scheduled_start: str = DEFAULT_SCHEDULED_START,
    site_key: str = "site",
    applicant_overrides=None,
    appointment_overrides=None,
    key: str = "appointment",
) -> dict:
    applicant = new_applicant(**(applicant_overrides or {}))
    world.setdefault("applicant", applicant)
    world["applicant_headers"] = make_applicant_headers(world["applicant"]["id"])
    appointment = new_appointment(
        applicant["id"],
        world[site_key]["id"],
        world["service_type"]["id"],
        scheduled_start,
        **(appointment_overrides or {}),
    )
    world[key] = appointment
    return world


def setup_checked_in_appointment(
    world: dict = None,
    scheduled_start: str = DEFAULT_SCHEDULED_START,
    checkin_clock: str = DEFAULT_CHECKIN_CLOCK,
    site_key: str = "site",
    check_in_overrides=None,
    applicant_overrides=None,
    appointment_overrides=None,
    **registry_kwargs,
) -> dict:
    """Registry + applicant + appointment, moved to CHECKED_IN."""
    world = world if world is not None else setup_registry(**registry_kwargs)
    add_applicant_and_appointment(
        world,
        scheduled_start=scheduled_start,
        site_key=site_key,
        applicant_overrides=applicant_overrides,
        appointment_overrides=appointment_overrides,
    )
    if checkin_clock:
        set_clock(checkin_clock)
    world["appointment"] = check_in(world["appointment"]["id"], **(check_in_overrides or {}))
    return world


def setup_open_card(world: dict = None, site_key: str = "site", **kwargs) -> dict:
    """Everything above plus one OPEN card with its ten PENDING positions."""
    world = world if world is not None else setup_checked_in_appointment(site_key=site_key, **kwargs)
    world["card"] = open_card(world["appointment"]["id"], world["device"]["id"])
    return world


def setup_finalized_card(world: dict = None, score: int = None, site_key: str = "site", **kwargs) -> dict:
    """Open card with all ten positions PASSED at `score`, then finalized."""
    world = world if world is not None else setup_open_card(site_key=site_key, **kwargs)
    pass_positions(world["card"]["id"], score)
    world["card"] = finalize_card(world["card"]["id"])
    return world


def setup_transmitted_submission(
    world: dict = None,
    score: int = None,
    retention_requested: bool = False,
    transmit_clock: str = None,
    site_key: str = "site",
    **kwargs,
) -> dict:
    """Everything above plus the transmission, leaving both axes at their initial values."""
    world = world if world is not None else setup_finalized_card(score=score, site_key=site_key, **kwargs)
    if transmit_clock:
        set_clock(transmit_clock)
    world["submission"] = transmit_card(
        world["card"]["id"], world["card"]["version"], retention_requested
    )
    return world


# ---------------------------------------------------------------------------
# Tier 4 — result, adjudication and rap-back shortcuts
# ---------------------------------------------------------------------------

def accept_state(world: dict, record_count: int = 0, disqualifying_offense_count: int = 0, record_detail=None) -> dict:
    extra = {
        "record_count": record_count,
        "disqualifying_offense_count": disqualifying_offense_count,
    }
    if record_detail is not None:
        extra["record_detail"] = record_detail
    world["submission"] = post_result(world["submission"]["id"], "STATE", "ACCEPTED", **extra)
    return world


def accept_fbi(world: dict, record_count: int = 0, disqualifying_offense_count: int = 0, record_detail=None) -> dict:
    extra = {
        "record_count": record_count,
        "disqualifying_offense_count": disqualifying_offense_count,
    }
    if record_detail is not None:
        extra["record_detail"] = record_detail
    world["submission"] = post_result(world["submission"]["id"], "FBI", "ACCEPTED", **extra)
    return world


def reject_destination(world: dict, destination: str, result_code: str, rejection_reason: str = "smudged") -> dict:
    world["submission"] = post_result(
        world["submission"]["id"], destination, result_code, rejection_reason=rejection_reason
    )
    return world


def state_response_of(submission_id: str, headers=None) -> dict:
    """The STATE criminal-history response row of one submission."""
    data, _meta = _paginated(
        api_client.list_submission_responses(submission_id, headers or ADJ, {"destination": "STATE"})
    )
    assert data, f"Setup failed: no STATE response exists for submission {submission_id}"
    return data[0]


def issue_determination(world: dict, outcome: str = "FIT", headers=None) -> dict:
    submission = get_success_data(api_client.get_submission(world["submission"]["id"], ADJ))
    world["submission"] = submission
    world["determination"] = get_success_data(
        api_client.create_fitness_determination(
            {
                "submission_id": submission["id"],
                "outcome": outcome,
                "expected_submission_version": submission["version"],
            },
            headers or ADJ,
        )
    )
    return world


def subscribe_rapback(world: dict, headers=None) -> dict:
    world["subscription"] = get_success_data(
        api_client.create_rapback_subscription(world["submission"]["id"], headers or ADJ)
    )
    return world


def deliver_notification(world: dict, event_type: str = "ARREST", event_date: str = "2026-06-05") -> dict:
    world["notification"] = get_success_data(
        api_client.create_rapback_notification(
            {
                "ori_code": world["ori"]["ori_code"],
                "subject_submission_tcn": world["submission"]["tcn_full"],
                "event_type": event_type,
                "event_date": event_date,
            },
            DEST,
        )
    )
    return world


def request_purge(world: dict, reason: str = "applicant withdrew consent", headers=None) -> dict:
    world["submission"] = get_success_data(
        api_client.request_purge(
            world["submission"]["id"], reason, headers or world.get("applicant_headers") or ADJ
        )
    )
    return world


# ---------------------------------------------------------------------------
# Tier 5 — fees, invoicing and the delinquency posture
# ---------------------------------------------------------------------------

def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


def fee_assessments(headers=None, **params) -> list:
    data, _meta = _paginated(api_client.list_fee_assessments(headers or VA, params or None))
    return data


def only_fee_assessment(headers=None, **params) -> dict:
    rows = fee_assessments(headers=headers, **params)
    assert len(rows) == 1, f"Expected exactly one fee assessment for {params}, found {len(rows)}"
    return rows[0]


def mark_no_show(appointment_id: str, no_show_clock: str = None, headers=None) -> dict:
    if no_show_clock:
        set_clock(no_show_clock)
    return get_success_data(api_client.mark_no_show(appointment_id, headers or TECH))


def open_invoice(agency_id: str, period_key: str = "2026-06") -> dict:
    agency = get_success_data(api_client.get_agency(agency_id, VA))
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(agency_id, agency["version"], period_key), VA)
    )


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, VA))


def run_aging(payload=None) -> dict:
    return get_success_data(api_client.aging_run(VA, payload))


def setup_agency_billed_no_show_invoice(
    period_key: str = "2026-06",
    clock_start: str = DEFAULT_CLOCK_START,
    scheduled_start: str = DEFAULT_SCHEDULED_START,
    no_show_clock: str = "2026-06-01T10:20:00Z",
    payer_regime_default: str = "AGENCY_BILLED",
    issue: bool = True,
    agency_overrides=None,
    **registry_kwargs,
) -> dict:
    """One flat no-show charge, attached to an issued invoice.

    This is the cheapest route to an agency that owes money, which is what the
    aging, late-fee, suspension and payer-regime scenarios all need.
    """
    merged_agency = {"payer_regime_default": payer_regime_default}
    merged_agency.update(agency_overrides or {})
    world = setup_registry(
        agency_overrides=merged_agency,
        clock_start=clock_start,
        with_device=False,
        **registry_kwargs,
    )
    add_applicant_and_appointment(world, scheduled_start=scheduled_start)
    world["appointment"] = mark_no_show(world["appointment"]["id"], no_show_clock)
    world["assessment"] = only_fee_assessment(appointment_id=world["appointment"]["id"])
    if issue:
        world["invoice"] = open_invoice(world["agency"]["id"], period_key)
        world["invoice"] = issue_invoice(world["invoice"]["id"])
    return world


def setup_suspended_agency(
    suspension_clock: str = "2026-08-16T00:00:00Z",
    **kwargs,
) -> dict:
    """Drive an agency to SUSPENDED by ageing its only invoice past 45 days."""
    world = setup_agency_billed_no_show_invoice(**kwargs)
    set_clock(suspension_clock)
    run_aging()
    world["agency"] = get_success_data(api_client.get_agency(world["agency"]["id"], VA))
    world["invoice"] = get_success_data(api_client.get_invoice(world["invoice"]["id"], VA))
    return world
