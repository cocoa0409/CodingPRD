"""Composite setup helpers.

Every setup call uses the lenient ``get_success_data`` so that a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: an Officer/Member actor's ``X-User-ID`` must be the acting
member's real ``id`` (PRD §2.1). Helpers that create an OFFICER member return headers
built from that member's id, and check-in helpers use the assignment owner's id.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import CHIEF, make_officer_headers, make_member_headers
from . import factories as f
from .constants import CERT_REQUIRED_HOURS


def _d(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------- clock
def set_clock(iso: str, api=api_client, headers=CHIEF):
    """Set the server logical clock (PRD §2.5)."""
    return _d(api.set_clock(iso, headers))


# ------------------------------------------------------------------- actors
def create_officer(api, **overrides):
    """Create an OFFICER-role_class member (by Chief) to act with X-User-Role=Officer.

    Returns (officer_id, officer_headers)."""
    payload = f.create_member_payload(
        role_class="OFFICER", email=f.unique_email("officer"), **overrides
    )
    m = _d(api.create_member(payload, CHIEF))
    return m["id"], make_officer_headers(m["id"])


def create_member(api, role_class="EMT", dues=0, **overrides):
    """Create a bare PROBATIONARY member."""
    payload = f.create_member_payload(
        role_class=role_class,
        dues_balance_cents=dues,
        email=f.unique_email("m"),
        **overrides,
    )
    return _d(api.create_member(payload, CHIEF))


# --------------------------------------------------------- stations/apparatus
def create_station_with_apparatus(
    api, min_crew=1, apparatus_type="ENGINE", unit_designation="UNIT-1"
):
    st = _d(api.create_station(f.create_station_payload(), CHIEF))
    ap = _d(
        api.create_apparatus(
            st["id"],
            f.create_apparatus_payload(
                unit_designation=unit_designation,
                apparatus_type=apparatus_type,
                min_crew=min_crew,
            ),
            CHIEF,
        )
    )
    return st, ap


def base_setup(api, apparatus_type="ENGINE", min_crew=1):
    """Officer + station + in-service apparatus — the near-universal preamble.

    Returns a namespace: off_id, off (headers), station, apparatus."""
    off_id, off = create_officer(api)
    st, ap = create_station_with_apparatus(
        api, min_crew=min_crew, apparatus_type=apparatus_type
    )
    return SimpleNamespace(off_id=off_id, off=off, station=st, apparatus=ap)


# ---------------------------------------------------- eligibility & shifts
def make_member_eligible(
    api, officer_headers, member_id, cert_type="EMT_BASIC", category="EMS", hours=None
):
    """Create + issue a required cert with sufficient hours, then activate the member.

    Returns (member_dict_after_activate, cert_dict)."""
    if hours is None:
        hours = CERT_REQUIRED_HOURS[cert_type]
    cert = _d(
        api.create_certification(
            member_id,
            f.create_certification_payload(cert_type=cert_type, category=category),
            officer_headers,
        )
    )
    api.create_training_record(
        member_id,
        f.create_training_record_payload(
            category=category, hours=hours, training_date="2026-03-01T00:00:00Z"
        ),
        officer_headers,
    )
    _d(api.issue_certification(cert["id"], officer_headers))
    m = _d(api.activate_member(member_id, CHIEF))
    return m, cert


def create_eligible_member(
    api, officer_headers, role_class="EMT", dues=0, cert_type="EMT_BASIC", category="EMS"
):
    """A fully response-eligible ACTIVE member. Returns (member, cert)."""
    m = create_member(api, role_class=role_class, dues=dues)
    m, cert = make_member_eligible(
        api, officer_headers, m["id"], cert_type=cert_type, category=category
    )
    return m, cert


def create_draft_shift(
    api, officer_headers, station_id, apparatus_id, start, end, max_crew=4, min_crew=1
):
    return _d(
        api.create_duty_shift(
            f.create_duty_shift_payload(
                station_id=station_id,
                apparatus_id=apparatus_id,
                start_at=start,
                end_at=end,
                max_crew=max_crew,
                min_crew=min_crew,
            ),
            officer_headers,
        )
    )


def create_published_shift(
    api, officer_headers, station_id, apparatus_id, start, end, max_crew=4, min_crew=1
):
    sh = create_draft_shift(
        api, officer_headers, station_id, apparatus_id, start, end, max_crew, min_crew
    )
    return _d(api.publish_duty_shift(sh["id"], officer_headers))


def assign_member(api, officer_headers, shift_id, member_id, expected_version):
    """Roster a member onto a shift. Returns the created assignment dict."""
    return _d(
        api.create_assignment(
            shift_id,
            {"member_id": member_id, "expected_duty_shift_version": expected_version},
            officer_headers,
        )
    )


def current_shift_version(api, officer_headers, shift_id):
    return _d(api.get_duty_shift(shift_id, officer_headers))["version"]


# ------------------------------------------------- verified duty (points)
def create_verified_duty(
    api, officer_headers, station_id, apparatus_id, member_id, start, end,
    checkin_clock, sweep_clock,
):
    """Publish a shift, assign+check-in the member, then sweep past end so the
    assignment becomes VERIFIED and its duty_points are credited. Returns the
    assignment dict after the sweep."""
    sh = create_published_shift(
        api, officer_headers, station_id, apparatus_id, start, end
    )
    a = assign_member(api, officer_headers, sh["id"], member_id, sh["version"])
    set_clock(checkin_clock, api)
    _d(api.check_in_assignment(a["id"], officer_headers))
    set_clock(sweep_clock, api)
    _d(api.sweep_duty_shifts(officer_headers))
    return _d(api.get_assignment(a["id"], officer_headers))


# ------------------------------------------------- released turnout (points)
def create_released_turnout(
    api, officer_headers, station_id, apparatus_id, member_id,
    incident_type, alarm_at, onscene_clock, cleared_clock,
):
    """Drive an incident to CLEARED with one member turnout, so the turnout is
    RELEASED and its points are credited. Returns (incident, turnout).

    The clock is set to ``onscene_clock`` before enroute/arrive (stamping
    onscene_at), then to ``cleared_clock`` before clear (stamping cleared_at)."""
    set_clock(onscene_clock, api)
    inc = _d(
        api.create_incident(
            f.create_incident_payload(
                station_id=station_id,
                apparatus_id=apparatus_id,
                incident_type=incident_type,
                alarm_at=alarm_at,
            ),
            officer_headers,
        )
    )
    _d(api.incident_enroute(inc["id"], officer_headers))
    _d(api.incident_arrive(inc["id"], officer_headers))
    turnout = _d(
        api.create_turnout(inc["id"], {"member_id": member_id}, officer_headers)
    )
    set_clock(cleared_clock, api)
    inc = _d(api.incident_clear(inc["id"], officer_headers))
    turnout = _d(api.get_turnout(turnout["id"], officer_headers))
    return inc, turnout


# ------------------------------------------------- cleared incident (NFIRS)
def create_cleared_incident(
    api, officer_headers, station_id, apparatus_id, incident_type="MVA",
    alarm_at="2026-03-02T00:00:00Z",
):
    """Create an incident and drive response to CLEARED (no turnouts).
    Returns the incident dict."""
    inc = _d(
        api.create_incident(
            f.create_incident_payload(
                station_id=station_id,
                apparatus_id=apparatus_id,
                incident_type=incident_type,
                alarm_at=alarm_at,
            ),
            officer_headers,
        )
    )
    _d(api.incident_enroute(inc["id"], officer_headers))
    _d(api.incident_arrive(inc["id"], officer_headers))
    return _d(api.incident_clear(inc["id"], officer_headers))


def create_locked_report_incident(
    api, officer_headers, station_id, apparatus_id,
    nfirs_property_use="419", nfirs_actions_taken="11",
):
    """Cleared incident with a LOCKED NFIRS report. Returns the incident dict
    (whose version reflects the lock)."""
    inc = create_cleared_incident(api, officer_headers, station_id, apparatus_id)
    _d(
        api.incident_report(
            inc["id"],
            {
                "nfirs_property_use": nfirs_property_use,
                "nfirs_actions_taken": nfirs_actions_taken,
            },
            officer_headers,
        )
    )
    return _d(api.incident_report_lock(inc["id"], officer_headers))


# ------------------------------------------------------------- fundraising
def create_active_campaign(api, goal_cents=100_000):
    c = _d(api.create_campaign(f.create_campaign_payload(goal_cents=goal_cents), CHIEF))
    return _d(api.open_campaign(c["id"], CHIEF))


def create_campaign_with_donations(api, amounts, goal_cents=100_000):
    """Active campaign with one POSTED donation per amount. Returns (campaign, [donations])."""
    c = create_active_campaign(api, goal_cents=goal_cents)
    donations = []
    for i, amt in enumerate(amounts):
        donations.append(
            _d(
                api.create_donation(
                    c["id"],
                    f.create_donation_payload(donor_name=f"Donor{i}", amount_cents=amt),
                    CHIEF,
                )
            )
        )
    return c, donations
