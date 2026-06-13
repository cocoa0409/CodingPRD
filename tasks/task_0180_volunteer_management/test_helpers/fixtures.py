"""Composite setup helpers.

Each test runs against a freshly-launched, empty server (the harness restarts the
API via start.sh before every test), so every fixture builds its preconditions
from scratch using only PRD-declared endpoints.

Fixtures use get_success_data() (lenient 2xx) internally so a setup failure
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: after creating a Volunteer (an entity_backed role), every
ownership-gated signup action uses make_volunteer_headers(volunteer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_organization_payload,
    create_volunteer_payload,
    create_background_check_payload,
    create_skill_payload,
    create_volunteer_skill_payload,
    create_waiver_template_payload,
    create_waiver_acceptance_payload,
    create_training_module_payload,
    create_training_completion_payload,
    create_opportunity_payload,
    create_shift_payload,
    create_signup_payload,
    create_corporate_group_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_volunteer_headers

COORD = TEST_USERS["shift_coordinator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SPONSOR = TEST_USERS["corporate_sponsor_headers"]


# ─── Primitives ───────────────────────────────────────────────────────────

def set_clock(iso8601, headers=COORD):
    """Set the server's logical current UTC clock."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), headers))


def create_organization(headers=COORD, **overrides):
    return get_success_data(
        api_client.create_organization(create_organization_payload(**overrides), headers)
    )


def create_volunteer(org_id, headers=COORD, **overrides):
    return get_success_data(
        api_client.create_volunteer(create_volunteer_payload(org_id, **overrides), headers)
    )


def create_opportunity(org_id, headers=COORD, **overrides):
    return get_success_data(
        api_client.create_opportunity(create_opportunity_payload(org_id, **overrides), headers)
    )


def create_shift(opp_id, starts_at, ends_at, capacity, headers=COORD, **overrides):
    return get_success_data(
        api_client.create_shift(
            create_shift_payload(opp_id, starts_at, ends_at, capacity, **overrides), headers
        )
    )


def publish_opportunity(opp_id, headers=COORD):
    return get_success_data(api_client.publish_opportunity(opp_id, headers))


def get_shift(shift_id, headers=COORD):
    return get_success_data(api_client.get_shift(shift_id, headers))


def get_volunteer(vol_id, headers=COORD):
    return get_success_data(api_client.get_volunteer(vol_id, headers))


def get_signup(signup_id, headers=COORD):
    return get_success_data(api_client.get_signup(signup_id, headers))


# ─── Tier 1/2: organization + published opportunity setup ─────────────────

def setup_org_and_volunteer(clock="2026-06-15T00:00:00Z", org_overrides=None, vol_overrides=None,
                            admin=COORD):
    """Empty DB -> ACTIVE Org + one ACTIVE Volunteer; clock set. Returns (org, volunteer)."""
    org = create_organization(headers=admin, **(org_overrides or {}))
    set_clock(clock, headers=admin)
    vol = create_volunteer(org["id"], headers=admin, **(vol_overrides or {}))
    return org, vol


def setup_published_opportunity(clock="2026-06-15T00:00:00Z", org_overrides=None,
                                opp_overrides=None, shift_specs=None, admin=COORD):
    """ACTIVE Org + DRAFT Opportunity (with optional gates) + N shifts, then PUBLISHED.

    shift_specs: list of dicts each with starts_at/ends_at/capacity (and optional extras).
    Defaults to a single 09:00-12:00 capacity-2 shift.
    Returns (org, opportunity, [shifts]) where each shift is the freshly-read entity.
    """
    org = create_organization(headers=admin, **(org_overrides or {}))
    set_clock(clock, headers=admin)
    opp = create_opportunity(org["id"], headers=admin, **(opp_overrides or {}))
    if shift_specs is None:
        shift_specs = [{
            "starts_at": "2026-07-01T09:00:00Z",
            "ends_at": "2026-07-01T12:00:00Z",
            "capacity": 2,
        }]
    shifts = []
    for spec in shift_specs:
        spec = dict(spec)
        shifts.append(create_shift(
            opp["id"], spec.pop("starts_at"), spec.pop("ends_at"), spec.pop("capacity"),
            headers=admin, **spec,
        ))
    publish_opportunity(opp["id"], headers=admin)
    return org, opp, shifts


def setup_signup_ready(clock="2026-06-15T00:00:00Z", capacity=2, org_overrides=None,
                       opp_overrides=None, starts_at="2026-07-01T09:00:00Z",
                       ends_at="2026-07-01T12:00:00Z", admin=COORD):
    """ACTIVE Org + ACTIVE Volunteer + PUBLISHED Opportunity with one OPEN shift.

    Returns (org, volunteer, opportunity, shift). No signup created yet.
    """
    org = create_organization(headers=admin, **(org_overrides or {}))
    set_clock(clock, headers=admin)
    vol = create_volunteer(org["id"], headers=admin)
    opp = create_opportunity(org["id"], headers=admin, **(opp_overrides or {}))
    shift = create_shift(opp["id"], starts_at, ends_at, capacity, headers=admin)
    publish_opportunity(opp["id"], headers=admin)
    shift = get_shift(shift["id"], headers=admin)
    return org, vol, opp, shift


# ─── Tier 3: signup lifecycle shortcuts ───────────────────────────────────

def create_signup(shift_id, volunteer_id, expected_shift_version, **overrides):
    """Create an individual signup as the owning volunteer (ownership-gated)."""
    return get_success_data(
        api_client.create_signup(
            shift_id,
            create_signup_payload(volunteer_id, expected_shift_version, **overrides),
            make_volunteer_headers(volunteer_id),
        )
    )


def create_reserved_signup(shift, volunteer_id, admin=COORD):
    """Sign volunteer up for shift (RESERVED). shift may be stale; re-read for version.
    Returns (signup, fresh_shift)."""
    fresh = get_shift(shift["id"], headers=admin)
    su = create_signup(fresh["id"], volunteer_id, fresh["version"])
    return su, get_shift(shift["id"], headers=admin)


def confirm_signup(signup_id, volunteer_id):
    return get_success_data(api_client.confirm_signup(signup_id, make_volunteer_headers(volunteer_id)))


def create_confirmed_signup(shift, volunteer_id, admin=COORD):
    """RESERVED -> CONFIRMED. Returns the confirmed signup."""
    su, _ = create_reserved_signup(shift, volunteer_id, admin=admin)
    confirm_signup(su["id"], volunteer_id)
    return get_signup(su["id"], headers=admin)


def create_attended_signup(shift, volunteer_id, check_in_clock, admin=COORD):
    """RESERVED -> CONFIRMED -> ATTENDED (after advancing clock past starts_at).
    Returns the attended signup (with provisional_hours set)."""
    su = create_confirmed_signup(shift, volunteer_id, admin=admin)
    set_clock(check_in_clock, headers=admin)
    return get_success_data(api_client.check_in_signup(su["id"], admin))


def create_logged_signup(shift, volunteer_id, logged_hours, check_in_clock, admin=COORD):
    """... -> ATTENDED -> HOURS_LOGGED. Returns the HOURS_LOGGED signup."""
    su = create_attended_signup(shift, volunteer_id, check_in_clock, admin=admin)
    get_success_data(
        api_client.log_hours_signup(su["id"], {"logged_hours": logged_hours},
                                    make_volunteer_headers(volunteer_id))
    )
    return get_signup(su["id"], headers=admin)


def create_verified_signup(shift, volunteer_id, logged_hours, check_in_clock, admin=COORD):
    """... -> HOURS_LOGGED -> HOURS_VERIFIED. Returns the verified signup."""
    su = create_logged_signup(shift, volunteer_id, logged_hours, check_in_clock, admin=admin)
    return get_success_data(api_client.verify_hours_signup(su["id"], admin))


# ─── Tier 4: accumulation / threshold targeting ───────────────────────────

def setup_volunteer_with_verified_hours(num_shifts, hours_each, capacity=9,
                                        clock="2026-06-15T00:00:00Z",
                                        check_in_clock=None, org_overrides=None, admin=COORD):
    """Build a Volunteer with `num_shifts` HOURS_VERIFIED signups, each contributing
    `hours_each` verified hours via a `hours_each`-long shift.

    Used for milestone-tier / total_verified_hours boundary targeting. Each shift is
    on a distinct day so intervals never overlap. Returns (org, volunteer, opportunity,
    [shifts], [signups]).
    """
    if check_in_clock is None:
        # A clock comfortably after all shifts so check-in / completion preconditions hold.
        check_in_clock = "2026-08-01T00:00:00Z"
    org = create_organization(headers=admin, **(org_overrides or {}))
    set_clock(clock, headers=admin)
    vol = create_volunteer(org["id"], headers=admin)
    opp = create_opportunity(org["id"], headers=admin)
    shifts = []
    for i in range(num_shifts):
        day = 1 + i  # distinct calendar days in July 2026
        starts = f"2026-07-{day:02d}T08:00:00Z"
        # ends_at = starts + hours_each hours.
        end_hour = 8 + int(hours_each)
        end_min = int(round((hours_each - int(hours_each)) * 60))
        ends = f"2026-07-{day:02d}T{end_hour:02d}:{end_min:02d}:00Z"
        shifts.append(create_shift(opp["id"], starts, ends, capacity, headers=admin))
    publish_opportunity(opp["id"], headers=admin)

    # Reserve + confirm every signup first (each create advances that shift's version,
    # which we read fresh per shift).
    signups = []
    for sh in shifts:
        fresh = get_shift(sh["id"], headers=admin)
        su = create_signup(fresh["id"], vol["id"], fresh["version"])
        confirm_signup(su["id"], vol["id"])
        signups.append(su)

    set_clock(check_in_clock, headers=admin)
    for su in signups:
        get_success_data(api_client.check_in_signup(su["id"], admin))
        get_success_data(
            api_client.log_hours_signup(su["id"], {"logged_hours": hours_each},
                                        make_volunteer_headers(vol["id"]))
        )
        get_success_data(api_client.verify_hours_signup(su["id"], admin))
    return org, vol, opp, shifts, signups


# ─── Background-check helpers ──────────────────────────────────────────────

def create_cleared_background_check(org, vol, requested_tier, validity_days=None,
                                    admin=COMPLIANCE):
    """INITIATED -> IN_PROGRESS -> CLEARED on a volunteer; returns the cleared check.
    Clock must already be set by the caller (cleared_at uses the current clock)."""
    overrides = {}
    if validity_days is not None:
        overrides["validity_days"] = validity_days
    chk = get_success_data(
        api_client.create_background_check(
            create_background_check_payload(vol["id"], requested_tier, **overrides), admin
        )
    )
    get_success_data(api_client.start_background_check(chk["id"], admin))
    fresh_vol = get_volunteer(vol["id"], headers=admin)
    get_success_data(
        api_client.decide_background_check(
            chk["id"],
            {"decision": "CLEARED", "expected_volunteer_version": fresh_vol["version"]},
            admin,
        )
    )
    return get_success_data(api_client.get_background_check(chk["id"], admin))


def create_in_progress_background_check(vol_id, requested_tier="BASIC", validity_days=None,
                                        admin=COMPLIANCE):
    """INITIATED -> IN_PROGRESS; returns the check still IN_PROGRESS."""
    overrides = {}
    if validity_days is not None:
        overrides["validity_days"] = validity_days
    chk = get_success_data(
        api_client.create_background_check(
            create_background_check_payload(vol_id, requested_tier, **overrides), admin
        )
    )
    get_success_data(api_client.start_background_check(chk["id"], admin))
    return get_success_data(api_client.get_background_check(chk["id"], admin))


# ─── Corporate-group helpers ──────────────────────────────────────────────

def setup_approved_corporate_group(requested_seats, capacity=10,
                                   clock="2026-06-15T00:00:00Z", admin=COORD, sponsor=SPONSOR):
    """PUBLISHED group-event Opportunity + capacity shift + APPROVED CorporateGroup.
    Returns (org, opp, shift, group)."""
    org = create_organization(headers=admin)
    set_clock(clock, headers=admin)
    opp = create_opportunity(org["id"], headers=admin, is_group_event=True)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z",
                         capacity, headers=admin)
    publish_opportunity(opp["id"], headers=admin)
    grp = get_success_data(
        api_client.create_corporate_group(
            create_corporate_group_payload(opp["id"], shift["id"], requested_seats), sponsor
        )
    )
    get_success_data(api_client.approve_corporate_group(grp["id"], admin))
    return org, opp, shift, get_success_data(api_client.get_corporate_group(grp["id"], admin))
