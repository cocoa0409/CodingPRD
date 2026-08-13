"""Composite setup helpers.

Every helper builds its preconditions from scratch against the running API
(the server is restarted with an empty database before each test) and uses the
lenient ``get_success_data`` so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.

Identity threading: entity-backed roles (Coordinator, Volunteer, GroupLeader,
FoodSafetyOfficer) always act through ``make_*_headers(volunteer["id"])`` so
ownership and segregation-of-duties identity comparisons see the real record id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_WATER_BUDGET,
    HARVEST_CLOCK,
    TEST_DEFAULTS,
)
from .factories import (
    create_bed_payload,
    create_crop_plan_payload,
    create_donation_recipient_payload,
    create_group_booking_payload,
    create_harvest_log_payload,
    create_irrigation_schedule_payload,
    create_season_payload,
    create_shift_signup_payload,
    create_shift_slot_payload,
    create_shed_key_payload,
    create_tool_checkout_payload,
    create_tool_payload,
    create_volunteer_payload,
)
from .test_users import (
    make_admin_headers,
    make_group_leader_headers,
    make_officer_headers,
    make_volunteer_headers,
)

CERT_EXPIRES_AT = TEST_DEFAULTS["CERT_EXPIRES_AT"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def make_volunteer(dob=None, headers=None, **overrides) -> dict:
    """Register a volunteer. Returns the Volunteer record."""
    hdrs = headers or make_admin_headers()
    payload = create_volunteer_payload(
        **({"date_of_birth": dob} if dob else {}), **overrides
    )
    return get_success_data(api_client.create_volunteer(payload, hdrs))


def make_participating_volunteer(dob=None, **overrides) -> dict:
    """A volunteer with orientation completed and waiver signed (PRD §2.8)."""
    vol = make_volunteer(dob=dob, **overrides)
    admin = make_admin_headers()
    get_success_data(api_client.complete_orientation(vol["id"], admin))
    vol = get_success_data(api_client.sign_waiver(vol["id"], admin))
    return vol


def make_officer_and_issue_cert(subject_id, cert_type, expires_at=None) -> dict:
    """Create an officer volunteer and issue the subject a certification.

    Returns the certification. The officer's id differs from the subject's, so
    the self-issuance segregation rule (PRD §3.2) is satisfied.
    """
    officer = make_volunteer()
    cert = get_success_data(
        api_client.create_certification(
            {
                "volunteer_id": subject_id,
                "cert_type": cert_type,
                "expires_at": expires_at or CERT_EXPIRES_AT,
            },
            make_officer_headers(officer["id"]),
        )
    )
    return cert


def make_certified_participant(cert_type, dob=None, **overrides) -> dict:
    """A participating volunteer who also holds an ACTIVE cert of cert_type.

    Returns (volunteer, certification, officer).
    """
    vol = make_participating_volunteer(dob=dob, **overrides)
    officer = make_volunteer()
    cert = get_success_data(
        api_client.create_certification(
            {
                "volunteer_id": vol["id"],
                "cert_type": cert_type,
                "expires_at": CERT_EXPIRES_AT,
            },
            make_officer_headers(officer["id"]),
        )
    )
    return vol, cert, officer


def make_bed(**overrides) -> dict:
    return get_success_data(
        api_client.create_bed(create_bed_payload(**overrides), make_admin_headers())
    )


def make_season(**overrides) -> dict:
    return get_success_data(
        api_client.create_season(create_season_payload(**overrides), make_admin_headers())
    )


# ---------------------------------------------------------------------------
# Tier 2: season / bed / crop-plan pipelines
# ---------------------------------------------------------------------------

def setup_season_open(bed=None, water_budget_gallons=DEFAULT_WATER_BUDGET, **season_overrides):
    """A season in OPEN_ENROLLMENT with at least one serviceable bed.

    Returns (season, bed). PRD §3.3: DRAFT -> OPEN_ENROLLMENT requires a bed
    that is not OUT_OF_SERVICE.
    """
    admin = make_admin_headers()
    season = make_season(water_budget_gallons=water_budget_gallons, **season_overrides)
    if bed is None:
        bed = make_bed()
    season = get_success_data(
        api_client.transition_season(season["id"], {"to_state": "OPEN_ENROLLMENT"}, admin)
    )
    return season, bed


def setup_season_planting(
    water_budget_gallons=DEFAULT_WATER_BUDGET, plan_overrides=None, **season_overrides
):
    """Season driven to PLANTING with one APPROVED crop plan.

    Returns dict(season, bed, plan, proposer). PRD §3.3: OPEN_ENROLLMENT ->
    PLANTING requires at least one plan in APPROVED or PLANTED.
    """
    admin = make_admin_headers()
    season, bed = setup_season_open(
        water_budget_gallons=water_budget_gallons, **season_overrides
    )
    proposer = make_volunteer()
    plan = get_success_data(
        api_client.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                **(plan_overrides or {}),
            ),
            admin,
        )
    )
    plan = get_success_data(
        api_client.transition_crop_plan(plan["id"], {"to_state": "APPROVED"}, admin)
    )
    season = get_success_data(
        api_client.transition_season(season["id"], {"to_state": "PLANTING"}, admin)
    )
    return {"season": season, "bed": bed, "plan": plan, "proposer": proposer}


def setup_season_harvesting(**overrides):
    """Season driven all the way to HARVESTING; the bed is HARVEST_OPEN and the
    crop plan HARVESTING (cascades of PRD §3.3/§3.4).

    Returns dict(season, bed, plan, proposer).
    """
    admin = make_admin_headers()
    ctx = setup_season_planting(**overrides)
    season, bed, plan = ctx["season"], ctx["bed"], ctx["plan"]
    bed = get_success_data(
        api_client.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin)
    )
    plan = get_success_data(
        api_client.transition_crop_plan(plan["id"], {"to_state": "PLANTED"}, admin)
    )
    bed = get_success_data(
        api_client.transition_bed(bed["id"], {"to_state": "PLANTED"}, admin)
    )
    season = get_success_data(
        api_client.transition_season(season["id"], {"to_state": "GROWING"}, admin)
    )
    season = get_success_data(
        api_client.transition_season(season["id"], {"to_state": "HARVESTING"}, admin)
    )
    ctx.update({"season": season, "bed": bed, "plan": plan})
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: shift slots and signups
# ---------------------------------------------------------------------------

def make_open_slot(season_id, capacity_total=3, capacity_youth=1, **overrides) -> dict:
    """A shift slot created and moved DRAFT -> OPEN (PRD §3.5)."""
    admin = make_admin_headers()
    slot = get_success_data(
        api_client.create_shift_slot(
            create_shift_slot_payload(
                season_id=season_id,
                capacity_total=capacity_total,
                capacity_youth=capacity_youth,
                **overrides,
            ),
            admin,
        )
    )
    return get_success_data(
        api_client.transition_shift_slot(slot["id"], {"to_state": "OPEN"}, admin)
    )


def make_signup_request(slot_id, volunteer_id, **overrides) -> dict:
    """Create a signup as the volunteer themselves. Returns the signup."""
    payload = create_shift_signup_payload(
        slot_id=slot_id, volunteer_id=volunteer_id, **overrides
    )
    return get_success_data(
        api_client.create_shift_signup(payload, make_volunteer_headers(volunteer_id))
    )


def make_confirmed_signup(slot_id, volunteer_id, **overrides) -> dict:
    """A signup created and confirmed by staff. Returns the signup."""
    signup = make_signup_request(slot_id, volunteer_id, **overrides)
    return get_success_data(
        api_client.confirm_shift_signup(signup["id"], make_admin_headers())
    )


def setup_open_slot_scenario(capacity_total=3, capacity_youth=1, **slot_overrides):
    """OPEN_ENROLLMENT season + OPEN slot + one participating volunteer.

    Returns dict(season, bed, slot, volunteer).
    """
    season, bed = setup_season_open()
    slot = make_open_slot(
        season["id"], capacity_total=capacity_total, capacity_youth=capacity_youth,
        **slot_overrides,
    )
    volunteer = make_participating_volunteer()
    return {"season": season, "bed": bed, "slot": slot, "volunteer": volunteer}


def setup_full_slot_with_waitlist(capacity_total=2, capacity_youth=1):
    """A slot confirmed to FULL with one signup waiting at waitlist position 1.

    Returns dict(season, slot, confirmed, waitlisted) where ``confirmed`` is the
    list of CONFIRMED signups (length == capacity_total) and ``waitlisted`` the
    WAITLISTED signup. PRD §3.5 branch B of confirm.
    """
    season, _bed = setup_season_open()
    slot = make_open_slot(
        season["id"], capacity_total=capacity_total, capacity_youth=capacity_youth
    )
    confirmed = []
    for _ in range(capacity_total):
        vol = make_participating_volunteer()
        confirmed.append(make_confirmed_signup(slot["id"], vol["id"]))
    waiter_vol = make_participating_volunteer()
    waitlisted = make_signup_request(slot["id"], waiter_vol["id"])
    waitlisted = get_success_data(
        api_client.confirm_shift_signup(waitlisted["id"], make_admin_headers())
    )
    assert waitlisted["status"] == "WAITLISTED", (
        f"Setup failed: expected overflow signup WAITLISTED, got {waitlisted['status']}"
    )
    return {
        "season": season,
        "slot": get_success_data(api_client.get_shift_slot(slot["id"], make_admin_headers())),
        "confirmed": confirmed,
        "waitlisted": waitlisted,
    }


# ---------------------------------------------------------------------------
# Tier 2: group bookings
# ---------------------------------------------------------------------------

def make_certified_chaperones(count) -> list:
    """``count`` volunteers each holding an ACTIVE SUPERVISION cert."""
    chaperones = []
    for _ in range(count):
        ch = make_volunteer()
        make_officer_and_issue_cert(ch["id"], "SUPERVISION")
        chaperones.append(ch)
    return chaperones


def make_group_booking(slot_id, leader, member_count, minor_count, chaperones,
                       chaperone_count=None, organization_name=None) -> dict:
    """Create a group booking as the leader (GroupLeader identity)."""
    payload = create_group_booking_payload(
        slot_id=slot_id,
        leader_volunteer_id=leader["id"],
        member_count=member_count,
        minor_count=minor_count,
        chaperone_count=len(chaperones) if chaperone_count is None else chaperone_count,
        chaperone_volunteer_ids=[c["id"] for c in chaperones],
        **({"organization_name": organization_name} if organization_name else {}),
    )
    return get_success_data(
        api_client.create_group_booking(payload, make_group_leader_headers(leader["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 2: tools, checkouts, keys
# ---------------------------------------------------------------------------

def make_tool(total_count=5, category="HAND", **overrides) -> dict:
    return get_success_data(
        api_client.create_tool(
            create_tool_payload(total_count=total_count, category=category, **overrides),
            make_admin_headers(),
        )
    )


def make_tool_checkout(tool_id, volunteer_id, qty, **overrides) -> dict:
    """Check out tool units as the borrower themselves."""
    payload = create_tool_checkout_payload(
        tool_id=tool_id, volunteer_id=volunteer_id, qty=qty, **overrides
    )
    return get_success_data(
        api_client.create_tool_checkout(payload, make_volunteer_headers(volunteer_id))
    )


def make_shed_key(key_code=None) -> dict:
    payload = create_shed_key_payload(**({"key_code": key_code} if key_code else {}))
    return get_success_data(api_client.create_shed_key(payload, make_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 3: harvest pipeline (logger + verified log + recipients)
# ---------------------------------------------------------------------------

def setup_harvest_scenario(weight_grams=10000, quality_grade="A", recipient_count=1,
                           recipient_capacity=None, **harvest_overrides):
    """Full harvest pipeline (PRD §3.8): season HARVESTING, bed HARVEST_OPEN,
    a PRODUCE_SAFETY-certified logger, and a DRAFT harvest log created at the
    harvest clock. Also creates recipients and a distinct verifying officer.

    Returns dict(ctx..., logger, log, recipients, officer).
    """
    ctx = setup_season_harvesting()
    logger, _cert, officer = make_certified_participant("PRODUCE_SAFETY")
    admin = make_admin_headers()
    get_success_data(api_client.set_clock({"to_iso8601": HARVEST_CLOCK}, admin))
    recipients = [
        get_success_data(
            api_client.create_donation_recipient(
                create_donation_recipient_payload(
                    **({"weekly_capacity_grams": recipient_capacity}
                       if recipient_capacity else {}),
                    priority_tier=i + 1,
                ),
                admin,
            )
        )
        for i in range(recipient_count)
    ]
    log = get_success_data(
        api_client.create_harvest_log(
            create_harvest_log_payload(
                season_id=ctx["season"]["id"],
                bed_id=ctx["bed"]["id"],
                logged_by_volunteer_id=logger["id"],
                weight_grams=weight_grams,
                quality_grade=quality_grade,
                **harvest_overrides,
            ),
            make_volunteer_headers(logger["id"]),
        )
    )
    ctx.update(
        {"logger": logger, "officer": officer, "log": log, "recipients": recipients}
    )
    return ctx


def submit_log(ctx) -> dict:
    """Move the scenario log DRAFT -> SUBMITTED as the logger."""
    log = get_success_data(
        api_client.transition_harvest_log(
            ctx["log"]["id"], {"to_state": "SUBMITTED"},
            make_volunteer_headers(ctx["logger"]["id"]),
        )
    )
    ctx["log"] = log
    return log


def verify_log(ctx) -> dict:
    """Move the scenario log SUBMITTED -> VERIFIED as the distinct officer."""
    log = get_success_data(
        api_client.transition_harvest_log(
            ctx["log"]["id"], {"to_state": "VERIFIED"},
            make_officer_headers(ctx["officer"]["id"]),
        )
    )
    ctx["log"] = log
    return log


# ---------------------------------------------------------------------------
# Tier 3: irrigation
# ---------------------------------------------------------------------------

def current_season_version(season_id) -> int:
    """Read the season's live version for an OCC-guarded write (PRD §2.7)."""
    season = get_success_data(api_client.get_season(season_id, make_admin_headers()))
    return season["version"]


def make_irrigation_schedule(season_id, zone, planned_start_at, planned_end_at,
                             planned_gallons) -> dict:
    """Create a schedule with the season's current version threaded through OCC."""
    payload = create_irrigation_schedule_payload(
        season_id=season_id,
        zone=zone,
        planned_start_at=planned_start_at,
        planned_end_at=planned_end_at,
        planned_gallons=planned_gallons,
        expected_season_version=current_season_version(season_id),
    )
    return get_success_data(
        api_client.create_irrigation_schedule(payload, make_admin_headers())
    )


def get_season_counters(season_id) -> dict:
    """Read back the season's water counters."""
    season = get_success_data(api_client.get_season(season_id, make_admin_headers()))
    return {
        "committed": season["water_committed_gallons"],
        "actual": season["water_actual_gallons"],
        "remaining": season["water_remaining_gallons"],
        "version": season["version"],
    }
