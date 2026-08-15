"""Composite setup helpers for the amateur-radio-club PRD (§2.5, §3).

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (each test runs against a fresh server/database). Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup failed" errors rather than confusing assertion output.

Defaults for club-wide-unique fields (site_name, repeater callsign, member
callsign for the net-control helper) are auto-suffixed per invocation when the
caller does not supply one: PRD §3.1/§3.2 require these values to be unique,
so a composite setup that builds two repeater chains in one test must not
re-issue an identical default (the server would correctly reject it).
"""
import itertools
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_antenna_site_agreement_payload,
    create_check_in_payload,
    create_coordination_request_payload,
    create_drill_message_payload,
    create_drill_payload,
    create_emergency_activation_payload,
    create_equipment_loan_payload,
    create_exam_candidate_payload,
    create_exam_session_payload,
    create_field_day_contact_payload,
    create_field_day_event_payload,
    create_member_payload,
    create_net_session_payload,
    create_repeater_payload,
    create_served_agency_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_ec_headers,
    make_liaison_headers,
    make_member_headers,
    make_netcontrol_headers,
)

ADMIN = TEST_USERS["admin_headers"]

# Uniqueness sequences for club-wide-unique default values (PRD §3.1 callsigns
# unique case-insensitively; §3.2 repeater callsigns unique; §3.2 site windows
# may not overlap for the same site_name).
_SITE_SEQ = itertools.count(1)
_REPEATER_SEQ = itertools.count(1)
_NETCONTROL_SEQ = itertools.count(1)

# Monotonic floor tracking the server's logical clock within a single test.
# PRD §2.5 only ever *advances* the clock, and a faithful implementation may
# reject backward moves, so composite setups must schedule time-gated work
# (net windows, drill windows) at or after the current clock reading. The
# server restarts per test (per-test-server isolation), so conftest resets
# this floor to the PRD §2.5 startup default before every test.
_DEFAULT_CLOCK_DT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK_FLOOR = [_DEFAULT_CLOCK_DT]


def reset_clock_floor():
    """Re-sync the fixture-side clock floor with a freshly booted server."""
    _CLOCK_FLOOR[0] = _DEFAULT_CLOCK_DT


def _day(iso: str, offset_days: int = 0) -> str:
    """Shift an ISO 8601 UTC instant by whole days; returns 'YYYY-MM-DDTHH:MM:SSZ'."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(days=offset_days)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the club logical clock (PRD §2.5)."""
    result = get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))
    dt = datetime.fromisoformat(to_iso8601.replace("Z", "+00:00")).astimezone(timezone.utc)
    if dt > _CLOCK_FLOOR[0]:
        _CLOCK_FLOOR[0] = dt
    return result


def create_member(callsign: str = "K1AAA", **overrides):
    """Create a member (starts PENDING per PRD §3.1). Returns the Member."""
    payload = create_member_payload(callsign=callsign, **overrides)
    return get_success_data(api_client.create_member(payload, ADMIN))


def create_active_member(callsign: str = "K1AAA", periods: int = 1, **overrides):
    """Create a member and pay dues -> ACTIVE. Returns the Member."""
    member = create_member(callsign, **overrides)
    renewed = get_success_data(
        api_client.renew_member(member["id"], {"periods": periods}, ADMIN)
    )
    return renewed


def suspend_member(member_id: str):
    return get_success_data(
        api_client.member_set_status(member_id, {"to": "SUSPENDED"}, ADMIN)
    )


def create_active_site_agreement(site_name: str = None, **overrides):
    """Create an antenna site agreement and activate it. Returns the agreement."""
    if site_name is None:
        site_name = "Hilltop-%d" % next(_SITE_SEQ)
    payload = create_antenna_site_agreement_payload(site_name=site_name, **overrides)
    agreement = get_success_data(api_client.create_antenna_site_agreement(payload, ADMIN))
    return get_success_data(
        api_client.antenna_site_agreement_set_status(agreement["id"], {"to": "ACTIVE"}, ADMIN)
    )


def create_repeater(site_agreement_id: str, callsign: str = None, **overrides):
    """Register a repeater (starts MAINTENANCE). Returns the Repeater."""
    if callsign is None:
        callsign = "W1RPT-%d" % next(_REPEATER_SEQ)
    payload = create_repeater_payload(site_agreement_id, callsign=callsign, **overrides)
    return get_success_data(api_client.create_repeater(payload, ADMIN))


def file_coordination_request(repeater_id: str, expected_repeater_version: int,
                              frequency: float = 146.94):
    """File a DRAFT coordination request (OCC field per PRD §2.9)."""
    payload = create_coordination_request_payload(
        repeater_id, expected_repeater_version, requested_frequency_mhz=frequency
    )
    return get_success_data(api_client.create_coordination_request(payload, ADMIN))


def grant_coordination(request_id: str, council_reference: str = "C-001"):
    """Submit then record GRANTED for a coordination request."""
    get_success_data(api_client.submit_coordination_request(request_id, ADMIN))
    return get_success_data(
        api_client.record_coordination_decision(
            request_id, {"outcome": "GRANTED", "council_reference": council_reference}, ADMIN
        )
    )


def repeater_set_status(repeater_id: str, to: str):
    return get_success_data(api_client.repeater_set_status(repeater_id, {"to": to}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — operational repeater under an active site
# ---------------------------------------------------------------------------

def setup_operational_repeater(site_name: str = None, repeater_callsign: str = None,
                               frequency: float = 146.94, **site_overrides):
    """Active site agreement + repeater + GRANTED coordination + OPERATIONAL.

    Returns (site_agreement, repeater) with the repeater in OPERATIONAL.
    """
    agreement = create_active_site_agreement(site_name, **site_overrides)
    repeater = create_repeater(agreement["id"], repeater_callsign,
                               output_frequency_mhz=frequency)
    request = file_coordination_request(repeater["id"], repeater["version"], frequency)
    grant_coordination(request["id"])
    repeater = repeater_set_status(repeater["id"], "OPERATIONAL")
    return agreement, repeater


def create_net_control(callsign: str = None, license_class: str = "EXTRA"):
    """An ACTIVE member acting in the NetControl capacity. Returns the Member."""
    if callsign is None:
        callsign = "W1NCS-%d" % next(_NETCONTROL_SEQ)
    return create_active_member(callsign, license_class=license_class)


def schedule_net(repeater_id: str, nc_member_id: str, name: str = "ARES Net",
                 scheduled_start: str = "2026-05-01T00:00:00Z",
                 scheduled_end: str = "2026-05-02T00:00:00Z", **overrides):
    """Schedule a net as the NetControl caller (net_control = caller, PRD §3.3)."""
    payload = create_net_session_payload(
        repeater_id, name=name, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end, **overrides
    )
    return get_success_data(
        api_client.create_net_session(payload, make_netcontrol_headers(nc_member_id))
    )


def net_set_status(net_id: str, to: str, caller_member_id: str, role: str = "NetControl"):
    headers = (TEST_USERS["admin_headers"] if role == "ClubAdmin"
               else make_netcontrol_headers(caller_member_id))
    return get_success_data(api_client.net_session_set_status(net_id, {"to": to}, headers))


def open_net(net_id: str, nc_member_id: str):
    return net_set_status(net_id, "OPEN", nc_member_id)


def close_net(net_id: str, nc_member_id: str):
    return net_set_status(net_id, "CLOSED", nc_member_id)


def check_in(net_id: str, member_id: str, **overrides):
    """Member self check-in to an OPEN net. Returns the CheckIn."""
    payload = create_check_in_payload(net_id, **overrides)
    return get_success_data(
        api_client.create_check_in(payload, make_member_headers(member_id))
    )


# ---------------------------------------------------------------------------
# Tier 3/4: readiness accumulation (closed-net check-ins, completed drills)
# ---------------------------------------------------------------------------

def accumulate_closed_check_ins(member_ids, count: int, repeater_id: str,
                                nc_member_id: str, base_day: str = None):
    """Give every listed member exactly `count` check-ins on CLOSED nets.

    Nets run one per UTC day on the repeater (half-open windows forbid
    overlap): net k occupies [base_day + k, base_day + k + 1). After each net
    is closed the logical clock advances to the next day's start so the next
    net can be opened. When base_day is omitted the chain starts at the
    current logical-clock floor, so calling this twice in one test never
    schedules a net window behind the clock (PRD §3.3 open-window rule).
    Returns the list of nets created.
    """
    if base_day is None:
        base_day = _CLOCK_FLOOR[0].strftime("%Y-%m-%dT%H:%M:%SZ")
    nets = []
    for k in range(count):
        start = _day(base_day, k)
        end = _day(base_day, k + 1)
        net = schedule_net(repeater_id, nc_member_id, name=f"Net {k + 1}",
                           scheduled_start=start, scheduled_end=end)
        open_net(net["id"], nc_member_id)
        for member_id in member_ids:
            check_in(net["id"], member_id)
        close_net(net["id"], nc_member_id)
        nets.append(net)
        if k < count - 1:
            set_clock(_day(base_day, k + 1))
    return nets


def setup_completed_drill_with_relay(ec_member_id: str, participant_member_id: str,
                                     title: str = "SET Drill",
                                     scheduled_start: str = "2026-05-01T00:00:00Z",
                                     scheduled_end: str = "2026-05-02T00:00:00Z"):
    """Drill driven PLANNED -> IN_PROGRESS -> COMPLETED with the participant
    holding one RELAYED message (so the drill counts toward readiness).

    Returns (drill, message).
    """
    drill = get_success_data(api_client.create_drill(
        create_drill_payload(title=title, scheduled_start=scheduled_start,
                             scheduled_end=scheduled_end),
        make_ec_headers(ec_member_id)))
    drill = get_success_data(api_client.drill_set_status(
        drill["id"], {"to": "IN_PROGRESS"}, make_ec_headers(ec_member_id)))
    message = get_success_data(api_client.create_drill_message(
        create_drill_message_payload(drill["id"], precedence="PRIORITY"),
        make_member_headers(participant_member_id)))
    message = get_success_data(api_client.drill_message_set_status(
        message["id"], {"to": "RELAYED"}, make_member_headers(participant_member_id)))
    drill = get_success_data(api_client.drill_set_status(
        drill["id"], {"to": "COMPLETED"}, make_ec_headers(ec_member_id)))
    return drill, message


# ---------------------------------------------------------------------------
# Tier 2/3: served-agency agreements, activations, rosters
# ---------------------------------------------------------------------------

def create_served_agreement(status: str = "ACTIVE", **overrides):
    """Create a served-agency agreement; optionally activate it."""
    agreement = get_success_data(api_client.create_served_agency_agreement(
        create_served_agency_agreement_payload(**overrides), ADMIN))
    if status == "ACTIVE":
        agreement = get_success_data(api_client.served_agency_agreement_set_status(
            agreement["id"], {"to": "ACTIVE"}, ADMIN))
    return agreement


def create_activation(agreement_id: str, ec_member_id: str, title: str = "Flood",
                      required_operators: int = 2):
    """Open a STANDBY activation, reading the agreement's current version first
    (OCC per PRD §2.9). Returns the activation."""
    agreement = get_success_data(
        api_client.get_served_agency_agreement(agreement_id, ADMIN))
    payload = create_emergency_activation_payload(
        agreement_id, agreement["version"], title=title,
        required_operators=required_operators)
    return get_success_data(
        api_client.create_emergency_activation(payload, make_ec_headers(ec_member_id)))


def activation_set_status(activation_id: str, to: str, ec_member_id: str):
    return get_success_data(api_client.emergency_activation_set_status(
        activation_id, {"to": to}, make_ec_headers(ec_member_id)))


def volunteer(activation_id: str, member_id: str):
    """Member self-volunteers for an activation. Returns the RosterEntry."""
    return get_success_data(api_client.create_roster_entry(
        {"activation_id": activation_id}, make_member_headers(member_id)))


def roster_set_status(entry_id: str, to: str, ec_member_id: str):
    return get_success_data(api_client.roster_entry_set_status(
        entry_id, {"to": to}, make_ec_headers(ec_member_id)))


def confirm_roster_entry(entry_id: str, ec_member_id: str):
    return roster_set_status(entry_id, "CONFIRMED", ec_member_id)


# ---------------------------------------------------------------------------
# Tier 2/3: field day
# ---------------------------------------------------------------------------

def create_open_field_day_event(name: str = "FD 2026", **overrides):
    """Create a field day event and open it (clock must be within the window)."""
    event = get_success_data(api_client.create_field_day_event(
        create_field_day_event_payload(name=name, **overrides), ADMIN))
    return get_success_data(api_client.field_day_event_set_status(
        event["id"], {"to": "OPEN"}, ADMIN))


def log_contact(event_id: str, member_id: str, **overrides):
    """Member logs a field day contact. Returns the FieldDayContact."""
    payload = create_field_day_contact_payload(event_id, **overrides)
    return get_success_data(
        api_client.create_field_day_contact(payload, make_member_headers(member_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: exam sessions
# ---------------------------------------------------------------------------

def create_exam_session(liaison_member_id: str, **overrides):
    """Schedule an exam session as the ExamLiaison caller. Returns the session."""
    return get_success_data(api_client.create_exam_session(
        create_exam_session_payload(**overrides),
        make_liaison_headers(liaison_member_id)))


def exam_session_set_status(session_id: str, to: str, liaison_member_id: str):
    return get_success_data(api_client.exam_session_set_status(
        session_id, {"to": to}, make_liaison_headers(liaison_member_id)))


def register_candidate(session_id: str, liaison_member_id: str, **overrides):
    return get_success_data(api_client.create_exam_candidate(
        create_exam_candidate_payload(session_id, **overrides),
        make_liaison_headers(liaison_member_id)))


def setup_in_progress_exam_session(liaison_member_id: str, **overrides):
    """Exam session driven SCHEDULED -> IN_PROGRESS. Returns the session."""
    session = create_exam_session(liaison_member_id, **overrides)
    return exam_session_set_status(session["id"], "IN_PROGRESS", liaison_member_id)


def check_in_candidate(candidate_id: str, liaison_member_id: str):
    return get_success_data(
        api_client.exam_candidate_check_in(candidate_id, make_liaison_headers(liaison_member_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: drills
# ---------------------------------------------------------------------------

def create_planned_drill(ec_member_id: str, **overrides):
    """Plan a drill as the EmergencyCoordinator caller. Returns the Drill."""
    return get_success_data(api_client.create_drill(
        create_drill_payload(**overrides), make_ec_headers(ec_member_id)))


def start_drill(drill_id: str, ec_member_id: str):
    return get_success_data(api_client.drill_set_status(
        drill_id, {"to": "IN_PROGRESS"}, make_ec_headers(ec_member_id)))


def originate_message(drill_id: str, member_id: str, precedence: str = "ROUTINE"):
    """Member originates a radiogram in an IN_PROGRESS drill."""
    return get_success_data(api_client.create_drill_message(
        create_drill_message_payload(drill_id, precedence=precedence),
        make_member_headers(member_id)))


def drill_message_transition(message_id: str, to: str, member_id: str):
    return get_success_data(api_client.drill_message_set_status(
        message_id, {"to": to}, make_member_headers(member_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: equipment loans
# ---------------------------------------------------------------------------

def create_loan(member_id: str, item_tag: str = "HT-1", due_at: str = "2026-06-01T00:00:00Z",
                estimated_value_cents: int = 1000):
    """Member self-checkout of club equipment. Returns the EquipmentLoan."""
    payload = create_equipment_loan_payload(
        item_tag=item_tag, due_at=due_at, estimated_value_cents=estimated_value_cents)
    return get_success_data(
        api_client.create_equipment_loan(payload, make_member_headers(member_id)))


def return_loan(loan_id: str, member_id: str, return_condition: str = "GOOD"):
    return get_success_data(api_client.return_equipment_loan(
        loan_id, {"return_condition": return_condition}, make_member_headers(member_id)))


# ---------------------------------------------------------------------------
# Tier 5: composite readiness + roster scenario (privilege-cascade target)
# ---------------------------------------------------------------------------

def setup_eligible_member_with_confirmed_roster(checkins: int = 6, drills: int = 1,
                                                required_operators: int = 5):
    """Full composite: operational repeater, net control, one member with
    `checkins` closed-net check-ins and `drills` completed drills, an ACTIVE
    served-agency agreement, a STANDBY activation, and that member CONFIRMED
    on the activation.

    Returns a dict with all entities involved.
    """
    _, repeater = setup_operational_repeater()
    nc = create_net_control("W1NCS")
    member = create_active_member("K1OPR")
    ec = create_member("W1EC")
    if checkins:
        accumulate_closed_check_ins([member["id"]], checkins, repeater["id"], nc["id"])
    drill = None
    if drills:
        for d in range(drills):
            drill, _ = setup_completed_drill_with_relay(ec["id"], member["id"],
                                                        title=f"SET Drill {d + 1}")
    agreement = create_served_agreement(status="ACTIVE")
    activation = create_activation(agreement["id"], ec["id"], title="Flood support",
                                   required_operators=required_operators)
    entry = volunteer(activation["id"], member["id"])
    entry = confirm_roster_entry(entry["id"], ec["id"])
    return {
        "repeater": repeater,
        "net_control": nc,
        "member": member,
        "ec": ec,
        "drill": drill,
        "agreement": agreement,
        "activation": activation,
        "roster_entry": entry,
    }
