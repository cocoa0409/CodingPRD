"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD publishes. Setup calls use the
lenient validator so a broken precondition surfaces as a clear setup failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    access_attempt_payload,
    association_payload,
    contractor_payload,
    credential_payload,
    grant_payload,
    incident_review_payload,
    listing_payload,
    lockbox_payload,
    member_payload,
    placement_payload,
    showing_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
SECOND_AUDITOR = TEST_USERS["second_auditor_headers"]
DEVICE = TEST_USERS["device_headers"]


# ---- Reads ------------------------------------------------------------------


def read_association(association_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_association(association_id, headers))


def read_member(member_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_member(member_id, headers))


def read_contractor(contractor_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_contractor(contractor_id, headers))


def read_lockbox(lockbox_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_lockbox(lockbox_id, headers))


def read_listing(listing_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_listing(listing_id, headers))


def read_placement(placement_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_placement(placement_id, headers))


def read_credential(credential_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_credential(credential_id, headers))


def read_grant(grant_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_grant(grant_id, headers))


def read_showing(appointment_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_showing(appointment_id, headers))


def read_access_event(event_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_access_event(event_id, headers))


def read_incident_review(review_id, headers=AUDITOR) -> dict:
    return get_success_data(api_client.get_incident_review(review_id, headers))


def read_charge(charge_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_billing_charge(charge_id, headers))


def list_charges(headers=ADMIN, **filters) -> list:
    response = api_client.list_billing_charges(headers, params=filters or None)
    return get_success_data(response)


def only_charge(headers=ADMIN, **filters) -> dict:
    rows = list_charges(headers, **filters)
    assert len(rows) == 1, f"Setup expected exactly one charge for {filters}, got {len(rows)}"
    return rows[0]


# ---- Tier 1: single-step primitives ----------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def register_association(**overrides) -> dict:
    return get_success_data(
        api_client.create_association(association_payload(**overrides), ADMIN)
    )


def enroll_member(association_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_member(member_payload(association_id, **overrides), ADMIN)
    )


def register_contractor(association_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_contractor(
            contractor_payload(association_id, **overrides), ADMIN
        )
    )


def contractor_action(contractor_id, action) -> dict:
    contractor = read_contractor(contractor_id)
    return get_success_data(
        api_client.contractor_state(
            contractor_id,
            {"action": action, "expected_contractor_version": contractor["version"]},
            ADMIN,
        )
    )


def intake_lockbox(association_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_lockbox(lockbox_payload(association_id, **overrides), ADMIN)
    )


def lockbox_action(lockbox_id, action, headers=ADMIN, **extra) -> dict:
    """Drive the lockbox state machine with a freshly read expected version."""
    lockbox = read_lockbox(lockbox_id)
    payload = {"action": action, "expected_lockbox_version": lockbox["version"]}
    payload.update(extra)
    return get_success_data(api_client.lockbox_state(lockbox_id, payload, headers))


def assign_lockbox(lockbox_id, member_id) -> dict:
    return lockbox_action(lockbox_id, "ASSIGN", member_id=member_id)


def report_lockbox_lost(lockbox_id, headers=ADMIN) -> dict:
    return lockbox_action(lockbox_id, "REPORT_LOST", headers=headers)


def report_lockbox_stolen(lockbox_id, police_report_number, headers=ADMIN) -> dict:
    return lockbox_action(
        lockbox_id,
        "REPORT_STOLEN",
        headers=headers,
        police_report_number=police_report_number,
    )


def create_listing(association_id, listing_agent_id, **overrides) -> dict:
    """The listing's own agent creates it, which is what the ownership rule expects."""
    return get_success_data(
        api_client.create_listing(
            listing_payload(association_id, listing_agent_id, **overrides),
            make_member_headers(listing_agent_id),
        )
    )


def listing_action(listing_id, action, agent_id=None, **extra) -> dict:
    listing = read_listing(listing_id)
    headers = make_member_headers(agent_id) if agent_id else ADMIN
    payload = {"action": action, "expected_listing_version": listing["version"]}
    payload.update(extra)
    return get_success_data(api_client.listing_state(listing_id, payload, headers))


def place_lockbox(lockbox_id, listing_id, member_id=None) -> dict:
    headers = make_member_headers(member_id) if member_id else ADMIN
    return get_success_data(
        api_client.create_placement(placement_payload(lockbox_id, listing_id), headers)
    )


def remove_placement(placement_id, member_id=None) -> dict:
    placement = read_placement(placement_id)
    headers = make_member_headers(member_id) if member_id else ADMIN
    return get_success_data(
        api_client.placement_state(
            placement_id,
            {"action": "REMOVE", "expected_placement_version": placement["version"]},
            headers,
        )
    )


def issue_credential(member_id, **overrides) -> dict:
    member = read_member(member_id)
    return get_success_data(
        api_client.create_credential(
            credential_payload(member_id, member["version"], **overrides), ADMIN
        )
    )


def credential_action(credential_id, action) -> dict:
    credential = read_credential(credential_id)
    return get_success_data(
        api_client.credential_state(
            credential_id,
            {"action": action, "expected_credential_version": credential["version"]},
            ADMIN,
        )
    )


def issue_active_credential(member_id, **overrides) -> dict:
    """Issue a credential and activate it, so the member can actually open a box."""
    credential = issue_credential(member_id, **overrides)
    return credential_action(credential["id"], "ACTIVATE")


def member_event(member_id, event_type, **extra) -> dict:
    member = read_member(member_id)
    payload = {"event_type": event_type, "expected_member_version": member["version"]}
    payload.update(extra)
    return get_success_data(api_client.member_event(member_id, payload, ADMIN))


def request_grant(listing_id, lockbox_id, member_id=None, **overrides) -> dict:
    """Request a temporary access grant, refreshing the listing version first."""
    listing = read_listing(listing_id)
    headers = make_member_headers(member_id) if member_id else ADMIN
    return get_success_data(
        api_client.create_grant(
            grant_payload(listing_id, lockbox_id, listing["version"], **overrides),
            headers,
        )
    )


def grant_action(grant_id, action, member_id=None) -> dict:
    grant = read_grant(grant_id)
    headers = make_member_headers(member_id) if member_id else ADMIN
    return get_success_data(
        api_client.grant_state(
            grant_id,
            {"action": action, "expected_grant_version": grant["version"]},
            headers,
        )
    )


def approve_grant(grant_id) -> dict:
    return grant_action(grant_id, "APPROVE")


def request_showing(listing_id, showing_member_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_showing(
            showing_payload(listing_id, showing_member_id, **overrides),
            make_member_headers(showing_member_id),
        )
    )


def showing_action(appointment_id, action, member_id=None, **extra) -> dict:
    appointment = read_showing(appointment_id)
    headers = make_member_headers(member_id) if member_id else ADMIN
    payload = {
        "action": action,
        "expected_appointment_version": appointment["version"],
    }
    payload.update(extra)
    return get_success_data(
        api_client.showing_state(appointment_id, payload, headers)
    )


def confirm_showing(appointment_id, member_id=None) -> dict:
    return showing_action(appointment_id, "CONFIRM", member_id=member_id)


def device_attempt(lockbox_id, actor_type="UNKNOWN", **overrides) -> dict:
    return get_success_data(
        api_client.device_access_attempt(
            access_attempt_payload(lockbox_id, actor_type, **overrides), DEVICE
        )
    )


def open_incident_review(
    association_id, window_start, window_end, auditor_headers=AUDITOR, **scope
) -> dict:
    return get_success_data(
        api_client.create_incident_review(
            incident_review_payload(association_id, window_start, window_end, **scope),
            auditor_headers,
        )
    )


def review_action(review_id, action, auditor_headers=AUDITOR, **extra) -> dict:
    review = read_incident_review(review_id, auditor_headers)
    payload = {"action": action, "expected_review_version": review["version"]}
    payload.update(extra)
    return get_success_data(
        api_client.incident_review_state(review_id, payload, auditor_headers)
    )


def lock_evidence(review_id, auditor_headers=AUDITOR) -> dict:
    return review_action(review_id, "LOCK_EVIDENCE", auditor_headers)


def charge_action(charge_id, action) -> dict:
    charge = read_charge(charge_id)
    return get_success_data(
        api_client.billing_charge_state(
            charge_id,
            {"action": action, "expected_charge_version": charge["version"]},
            ADMIN,
        )
    )


def run_checkpoint(association_id) -> dict:
    return get_success_data(api_client.run_compliance_checkpoint(association_id, ADMIN))


# ---- Tier 2: entity hierarchy ----------------------------------------------


def setup_association_with_agent(clock=None, agent_name="Ana Reyes",
                                 agent_email="ana@example.com", **association_overrides) -> dict:
    """Register an association, optionally move the logical clock, and enroll one agent."""
    association = register_association(**association_overrides)
    if clock:
        set_clock(clock)
    agent = enroll_member(
        association["id"], full_name=agent_name, email=agent_email
    )
    return {
        "association": association,
        "association_id": association["id"],
        "agent": agent,
        "agent_id": agent["id"],
        "agent_headers": make_member_headers(agent["id"]),
    }


def setup_assigned_box(clock=None, serial="LB-0001", model="LB_PRO",
                       replacement_cost_cents=None, in_service_since=None,
                       **association_overrides) -> dict:
    """Association + agent + one lockbox already ASSIGNED to that agent."""
    ctx = setup_association_with_agent(clock=clock, **association_overrides)
    box_overrides = {"serial_number": serial, "model": model}
    if replacement_cost_cents is not None:
        box_overrides["replacement_cost_cents"] = replacement_cost_cents
    if in_service_since is not None:
        box_overrides["in_service_since"] = in_service_since
    lockbox = intake_lockbox(ctx["association_id"], **box_overrides)
    ctx["lockbox"] = assign_lockbox(lockbox["id"], ctx["agent_id"])
    ctx["lockbox_id"] = lockbox["id"]
    return ctx


def setup_placed_box(clock=None, serial="LB-0001", model="LB_PRO",
                     replacement_cost_cents=None, in_service_since=None,
                     mls_number="MLS-1001", address_line="12 Pine St",
                     concurrent_showing_limit=None, **association_overrides) -> dict:
    """Association + agent + a lockbox PLACED on that agent's ACTIVE listing.

    This is the most common precondition: a grant, a showing confirmation and a device
    attempt all need a box actually hanging on a property.
    """
    ctx = setup_assigned_box(
        clock=clock,
        serial=serial,
        model=model,
        replacement_cost_cents=replacement_cost_cents,
        in_service_since=in_service_since,
        **association_overrides,
    )
    listing_overrides = {"mls_number": mls_number, "address_line": address_line}
    if concurrent_showing_limit is not None:
        listing_overrides["concurrent_showing_limit"] = concurrent_showing_limit
    listing = create_listing(ctx["association_id"], ctx["agent_id"], **listing_overrides)
    placement = place_lockbox(ctx["lockbox_id"], listing["id"], ctx["agent_id"])
    ctx["listing"] = listing
    ctx["listing_id"] = listing["id"]
    ctx["placement"] = placement
    ctx["placement_id"] = placement["id"]
    return ctx


def setup_placed_box_with_credential(clock=None, credential_type="KEY_APP",
                                     **overrides) -> dict:
    """A placed box plus an ACTIVE keyholder credential for the placing agent."""
    ctx = setup_placed_box(clock=clock, **overrides)
    credential = issue_active_credential(ctx["agent_id"], credential_type=credential_type)
    ctx["credential"] = credential
    ctx["credential_id"] = credential["id"]
    return ctx


def add_second_agent(ctx, full_name="Ben Ortiz", email="ben@example.com") -> dict:
    """Enroll a second member (a buyer-side agent) into an existing scenario."""
    member = enroll_member(ctx["association_id"], full_name=full_name, email=email)
    ctx["other_agent"] = member
    ctx["other_agent_id"] = member["id"]
    ctx["other_agent_headers"] = make_member_headers(member["id"])
    return member


# ---- Tier 3: lifecycle shortcuts -------------------------------------------


def close_listing(listing_id, agent_id, close_date, clock=None) -> dict:
    """Move a listing ACTIVE -> UNDER_CONTRACT -> CLOSED with the supplied close_date."""
    if clock:
        set_clock(clock)
    listing_action(listing_id, "MARK_UNDER_CONTRACT", agent_id=agent_id)
    return listing_action(
        listing_id, "CLOSE", agent_id=agent_id, close_date=close_date
    )


def withdraw_listing(listing_id, agent_id, clock=None) -> dict:
    if clock:
        set_clock(clock)
    return listing_action(listing_id, "WITHDRAW", agent_id=agent_id)


def setup_removal_due_placement(close_date="2026-08-10",
                                close_clock="2026-08-10T00:00:00Z", **overrides) -> dict:
    """A placed box whose listing has closed, so its placement sits in REMOVAL_DUE."""
    ctx = setup_placed_box(**overrides)
    ctx["listing"] = close_listing(
        ctx["listing_id"], ctx["agent_id"], close_date, clock=close_clock
    )
    ctx["placement"] = read_placement(ctx["placement_id"])
    return ctx


def setup_delinquent_placement(close_date="2026-08-10",
                               close_clock="2026-08-10T00:00:00Z",
                               run_clock="2026-08-14T00:00:00Z", **overrides) -> dict:
    """A placement carried past its removal deadline and through the checkpoint, so it
    is DELINQUENT with an accrued LATE_REMOVAL charge."""
    ctx = setup_removal_due_placement(
        close_date=close_date, close_clock=close_clock, **overrides
    )
    set_clock(run_clock)
    ctx["checkpoint"] = run_checkpoint(ctx["association_id"])
    ctx["placement"] = read_placement(ctx["placement_id"])
    return ctx


def setup_approved_grant(clock="2026-08-05T00:00:00Z", grant_type="INSPECTOR",
                         window_start="2026-08-06T14:00:00Z",
                         window_end="2026-08-06T16:00:00Z", **overrides) -> dict:
    """A placed box carrying one APPROVED access grant."""
    ctx = setup_placed_box(clock=clock, **overrides)
    grant = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type=grant_type,
        window_start=window_start,
        window_end=window_end,
    )
    ctx["grant"] = approve_grant(grant["id"])
    ctx["grant_id"] = grant["id"]
    return ctx


def setup_confirmed_showing(ctx, showing_member_id, window_start="2026-08-07T10:00:00Z",
                            window_end="2026-08-07T11:00:00Z") -> dict:
    """Book and confirm a showing on the scenario's listing."""
    appointment = request_showing(
        ctx["listing_id"],
        showing_member_id,
        window_start=window_start,
        window_end=window_end,
    )
    confirmed = confirm_showing(appointment["id"], member_id=showing_member_id)
    ctx["appointment"] = confirmed
    ctx["appointment_id"] = appointment["id"]
    return confirmed


# ---- Tier 4: posture / accumulation targeting ------------------------------


def setup_restricted_association(clock=None) -> dict:
    """Drive posture to RESTRICTED with exactly one missing box, while a second agent
    keeps a clean box PLACED on his own listing."""
    ctx = setup_assigned_box(clock=clock, serial="LB-0001", model="LB_STD",
                             replacement_cost_cents=TEST_DEFAULTS["LB_STD_COST_CENTS"])
    add_second_agent(ctx)
    clean_box = intake_lockbox(
        ctx["association_id"],
        serial_number="LB-0002",
        model="LB_STD",
        replacement_cost_cents=TEST_DEFAULTS["LB_STD_COST_CENTS"],
    )
    assign_lockbox(clean_box["id"], ctx["other_agent_id"])
    other_listing = create_listing(
        ctx["association_id"],
        ctx["other_agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )
    other_placement = place_lockbox(
        clean_box["id"], other_listing["id"], ctx["other_agent_id"]
    )
    report_lockbox_lost(ctx["lockbox_id"])
    ctx["clean_lockbox"] = clean_box
    ctx["clean_lockbox_id"] = clean_box["id"]
    ctx["other_listing"] = other_listing
    ctx["other_listing_id"] = other_listing["id"]
    ctx["other_placement"] = other_placement
    return ctx


def setup_frozen_association(clock=None) -> dict:
    """Drive posture to FROZEN by reporting three boxes lost, leaving a fourth clean box
    ASSIGNED to a second agent who owns an ACTIVE listing."""
    ctx = setup_association_with_agent(clock=clock)
    add_second_agent(ctx)
    lost_ids = []
    for index in (1, 2, 3):
        box = intake_lockbox(
            ctx["association_id"],
            serial_number=f"LB-000{index}",
            model="LB_STD",
            replacement_cost_cents=TEST_DEFAULTS["LB_STD_COST_CENTS"],
        )
        assign_lockbox(box["id"], ctx["agent_id"])
        lost_ids.append(box["id"])
    clean_box = intake_lockbox(
        ctx["association_id"],
        serial_number="LB-0004",
        model="LB_STD",
        replacement_cost_cents=TEST_DEFAULTS["LB_STD_COST_CENTS"],
    )
    assign_lockbox(clean_box["id"], ctx["other_agent_id"])
    other_listing = create_listing(
        ctx["association_id"],
        ctx["other_agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )
    for box_id in lost_ids:
        report_lockbox_lost(box_id)
    ctx["lost_lockbox_ids"] = lost_ids
    ctx["clean_lockbox"] = clean_box
    ctx["clean_lockbox_id"] = clean_box["id"]
    ctx["other_listing"] = other_listing
    ctx["other_listing_id"] = other_listing["id"]
    return ctx


# ---- Tier 5: audit / evidence ----------------------------------------------


def setup_locked_review(association_id, window_start="2026-08-06T00:00:00Z",
                        window_end="2026-08-06T23:59:59Z",
                        auditor_headers=AUDITOR, **scope) -> dict:
    """Open a review over the given scope and lock its evidence set."""
    review = open_incident_review(
        association_id, window_start, window_end, auditor_headers, **scope
    )
    locked = lock_evidence(review["id"], auditor_headers)
    locked["id"] = review["id"]
    return locked
