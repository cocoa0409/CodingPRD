"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only, because each test starts against an empty database. Setup calls use the
lenient `get_success_data()` validator so a broken precondition surfaces as a
clear setup failure rather than as a confusing assertion.

Identity threading: the five member-backed roles of PRD 2.1 always act through
`make_<role>_headers(<ClubMember id>)`, never through a shared constant, because
ownership checks compare the resource's member-referencing field to `X-User-ID`.
"""

import datetime as _dt

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CERT_VALID_FROM,
    CERT_VALID_UNTIL,
    DUTY_WINDOW_END,
    DUTY_WINDOW_START,
    MEASUREMENT_A,
    MEASUREMENT_B,
    NOR_EFFECTIVE_UTC,
    RACE_1_SCHEDULED_START,
    SAFETY_COURSE_OK_UNTIL,
    SI_EFFECTIVE_UTC,
)
from .factories import (
    add_crew_payload,
    create_boat_payload,
    create_certificate_payload,
    create_club_member_payload,
    create_division_payload,
    create_duty_assignment_payload,
    create_entry_payload,
    create_jury_panel_payload,
    create_mark_boat_payload,
    create_race_document_payload,
    create_race_payload,
    create_race_result_payload,
    create_regatta_payload,
    inspect_entry_payload,
    recall_payload,
    seat_judge_payload,
    start_race_payload,
    unique_suffix,
)
from .test_users import (
    make_club_admin_headers,
    make_competitor_headers,
    make_jury_chair_headers,
    make_measurer_headers,
    make_race_officer_headers,
    make_regatta_chair_headers,
)

ADMIN = make_club_admin_headers()


# ── Clock ──────────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Only a ClubAdmin may drive it (PRD 2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ── Roster (PRD 3.1) ───────────────────────────────────────────────────────
def enrol_member(full_name=None, **overrides) -> dict:
    payload = create_club_member_payload(**overrides)
    if full_name is not None:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_club_member(payload, ADMIN))


def patch_member(member_id: str, **fields) -> dict:
    return get_success_data(api_client.patch_club_member(member_id, dict(fields), ADMIN))


def enrol_standard_roster() -> dict:
    """The nine-person roster every composite world is built on.

    - one licensed measurer, one regatta chair
    - three committee volunteers, one for each always-required duty position
    - one jury-qualified chair plus one further judge
    - three helms whose sea-survival course is valid past the series start
    """
    roster = {
        "measurer": enrol_member("Mara Vance", measurer_license_id="M-101"),
        "chair": enrol_member("Piers Holt"),
        "pro": enrol_member("Dana Reeve"),
        "timekeeper": enrol_member("Tom Isley"),
        "signals": enrol_member("Sara Quill"),
        "judge_chair": enrol_member("Nils Brandt", judge_certification_level="REGIONAL"),
        "judge_member": enrol_member("Ida Moss", judge_certification_level="CLUB"),
    }
    for key, name in (("helm_1", "Owen Clay"), ("helm_2", "Rhea Voss"), ("helm_3", "Kai Larsen")):
        roster[key] = enrol_member(name, safety_course_expiry_utc=SAFETY_COURSE_OK_UNTIL)
    return roster


def roster_headers(roster: dict) -> dict:
    """Convenience header bundle for a roster built by enrol_standard_roster."""
    return {
        "admin": ADMIN,
        "chair": make_regatta_chair_headers(roster["chair"]["id"]),
        "measurer": make_measurer_headers(roster["measurer"]["id"]),
        "pro": make_race_officer_headers(roster["pro"]["id"]),
        "jury": make_jury_chair_headers(roster["judge_chair"]["id"]),
        "helm_1": make_competitor_headers(roster["helm_1"]["id"]),
        "helm_2": make_competitor_headers(roster["helm_2"]["id"]),
        "helm_3": make_competitor_headers(roster["helm_3"]["id"]),
    }


# ── Boats and certificates (PRD 3.1, 3.2) ──────────────────────────────────
def register_boat(owner_member_id: str, **overrides) -> dict:
    payload = create_boat_payload(owner_member_id, **overrides)
    return get_success_data(
        api_client.create_boat(payload, make_competitor_headers(owner_member_id))
    )


def current_boat_version(boat_id: str) -> int:
    return get_success_data(api_client.get_boat(boat_id, ADMIN))["version"]


def file_certificate(
    boat_id: str,
    measurer_id: str,
    measurement=None,
    rule_code: str = "TOD_PHRF",
    valid_from: str = CERT_VALID_FROM,
    valid_until: str = CERT_VALID_UNTIL,
    **overrides,
) -> dict:
    """File measurement data against the boat's current version."""
    measurement = dict(measurement or MEASUREMENT_A)
    payload = create_certificate_payload(
        boat_id,
        current_boat_version(boat_id),
        rule_code=rule_code,
        valid_from=valid_from,
        valid_until=valid_until,
        **measurement,
    )
    payload.update(overrides)
    return get_success_data(
        api_client.create_certificate(payload, make_measurer_headers(measurer_id))
    )


def issue_certificate(certificate_id: str, measurer_id: str) -> dict:
    return get_success_data(
        api_client.issue_certificate(certificate_id, make_measurer_headers(measurer_id))
    )


def file_and_issue_certificate(boat_id: str, measurer_id: str, **kwargs) -> dict:
    certificate = file_certificate(boat_id, measurer_id, **kwargs)
    return issue_certificate(certificate["id"], measurer_id)


# ── Regattas and documents (PRD 3.3) ───────────────────────────────────────
def open_regatta(chair_member_id: str, **overrides) -> dict:
    payload = create_regatta_payload(**overrides)
    return get_success_data(
        api_client.create_regatta(payload, make_regatta_chair_headers(chair_member_id))
    )


def current_regatta_version(regatta_id: str) -> int:
    return get_success_data(api_client.get_regatta(regatta_id, ADMIN))["version"]


def publish_document(
    regatta_id: str,
    chair_member_id: str,
    doc_type: str = "NOR",
    effective_utc: str = NOR_EFFECTIVE_UTC,
    body_summary: str = None,
    **overrides,
) -> dict:
    payload = create_race_document_payload(
        regatta_id,
        current_regatta_version(regatta_id),
        doc_type=doc_type,
        effective_utc=effective_utc,
        body_summary=body_summary or f"{doc_type} revision text",
    )
    payload.update(overrides)
    return get_success_data(
        api_client.create_race_document(payload, make_regatta_chair_headers(chair_member_id))
    )


def publish_nor(regatta_id: str, chair_member_id: str, effective_utc: str = NOR_EFFECTIVE_UTC) -> dict:
    return publish_document(
        regatta_id, chair_member_id, doc_type="NOR", effective_utc=effective_utc,
        body_summary="Notice of race revision 1",
    )


def publish_si(regatta_id: str, chair_member_id: str, effective_utc: str = SI_EFFECTIVE_UTC) -> dict:
    return publish_document(
        regatta_id, chair_member_id, doc_type="SI", effective_utc=effective_utc,
        body_summary="Sailing instructions revision 1",
    )


def open_racing(regatta_id: str, chair_member_id: str) -> dict:
    return get_success_data(
        api_client.open_racing(regatta_id, make_regatta_chair_headers(chair_member_id))
    )


# ── Divisions (PRD 3.4) ────────────────────────────────────────────────────
def add_division(regatta_id: str, chair_member_id: str, **overrides) -> dict:
    payload = create_division_payload(regatta_id, **overrides)
    return get_success_data(
        api_client.create_division(payload, make_regatta_chair_headers(chair_member_id))
    )


def confirm_division(division_id: str, chair_member_id: str) -> dict:
    return get_success_data(
        api_client.confirm_division(division_id, make_regatta_chair_headers(chair_member_id))
    )


def merge_division(division_id: str, chair_member_id: str) -> dict:
    return get_success_data(
        api_client.merge_division(division_id, make_regatta_chair_headers(chair_member_id))
    )


# ── Entries (PRD 3.5) ──────────────────────────────────────────────────────
def submit_entry(regatta_id, boat_id, certificate_id, helm_member_id, **overrides) -> dict:
    payload = create_entry_payload(
        regatta_id, boat_id, certificate_id, helm_member_id, **overrides
    )
    return get_success_data(
        api_client.create_entry(payload, make_competitor_headers(helm_member_id))
    )


def add_crew(entry_id, helm_member_id, member_id, position="HELM", weight_kg=84.5) -> dict:
    payload = add_crew_payload(member_id, position=position, weight_kg=weight_kg)
    return get_success_data(
        api_client.add_crew(entry_id, payload, make_competitor_headers(helm_member_id))
    )


def inspect_entry(entry_id, race_officer_id, outcome="PASS", **overrides) -> dict:
    payload = inspect_entry_payload(outcome=outcome, **overrides)
    return get_success_data(
        api_client.inspect_entry(entry_id, payload, make_race_officer_headers(race_officer_id))
    )


def assign_division(entry_id, chair_member_id) -> dict:
    return get_success_data(
        api_client.assign_division(entry_id, make_regatta_chair_headers(chair_member_id))
    )


def accept_entry(entry_id, chair_member_id) -> dict:
    return get_success_data(
        api_client.accept_entry(entry_id, make_regatta_chair_headers(chair_member_id))
    )


def withdraw_entry(entry_id, helm_member_id) -> dict:
    return get_success_data(
        api_client.withdraw_entry(entry_id, make_competitor_headers(helm_member_id))
    )


# ── Jury panels (PRD 3.10) ─────────────────────────────────────────────────
def form_panel(regatta_id, chair_member_id, judge_chair_member_id) -> dict:
    payload = create_jury_panel_payload(regatta_id, judge_chair_member_id)
    return get_success_data(
        api_client.create_jury_panel(payload, make_regatta_chair_headers(chair_member_id))
    )


def seat_judge(panel_id, chair_member_id, member_id) -> dict:
    return get_success_data(
        api_client.seat_judge(
            panel_id, seat_judge_payload(member_id), make_regatta_chair_headers(chair_member_id)
        )
    )


# ── Mark boats and duties (PRD 3.6) ────────────────────────────────────────
def charter_mark_boat(regatta_id, chair_member_id, **overrides) -> dict:
    payload = create_mark_boat_payload(regatta_id, **overrides)
    return get_success_data(
        api_client.create_mark_boat(payload, make_regatta_chair_headers(chair_member_id))
    )


def propose_duty(
    regatta_id, chair_member_id, member_id, position,
    window_start_utc=DUTY_WINDOW_START, window_end_utc=DUTY_WINDOW_END, **overrides,
) -> dict:
    payload = create_duty_assignment_payload(
        regatta_id, member_id, position, window_start_utc, window_end_utc, **overrides
    )
    return get_success_data(
        api_client.create_duty_assignment(payload, make_regatta_chair_headers(chair_member_id))
    )


def confirm_duty(duty_id, chair_member_id) -> dict:
    return get_success_data(
        api_client.confirm_duty_assignment(duty_id, make_regatta_chair_headers(chair_member_id))
    )


def staff_committee(
    regatta_id, roster,
    window_start_utc=DUTY_WINDOW_START, window_end_utc=DUTY_WINDOW_END,
) -> dict:
    """Propose and confirm one PRO, one TIMEKEEPER and one SIGNALS duty over a
    single whole-regatta window that covers any race started inside it."""
    chair_id = roster["chair"]["id"]
    duties = {}
    for position, key in (("PRO", "pro"), ("TIMEKEEPER", "timekeeper"), ("SIGNALS", "signals")):
        duty = propose_duty(
            regatta_id, chair_id, roster[key]["id"], position,
            window_start_utc=window_start_utc, window_end_utc=window_end_utc,
        )
        duties[position] = confirm_duty(duty["id"], chair_id)
    return duties


# ── Races and results (PRD 3.7, 3.8, 3.9) ──────────────────────────────────
def schedule_race(regatta_id, chair_member_id, race_number, scheduled_start_utc, **overrides) -> dict:
    payload = create_race_payload(regatta_id, race_number, scheduled_start_utc, **overrides)
    return get_success_data(
        api_client.create_race(payload, make_regatta_chair_headers(chair_member_id))
    )


def start_sequence(race_id, race_officer_id) -> dict:
    return get_success_data(
        api_client.start_sequence(race_id, make_race_officer_headers(race_officer_id))
    )


def record_start(race_id, race_officer_id, actual_start_utc) -> dict:
    return get_success_data(
        api_client.start_race(
            race_id, start_race_payload(actual_start_utc),
            make_race_officer_headers(race_officer_id),
        )
    )


def signal_recall(race_id, race_officer_id, recall_type, signal_utc, **overrides) -> dict:
    payload = recall_payload(recall_type, signal_utc, **overrides)
    return get_success_data(
        api_client.recall_race(race_id, payload, make_race_officer_headers(race_officer_id))
    )


def record_result(race_id, entry_id, race_officer_id, **overrides) -> dict:
    payload = create_race_result_payload(race_id, entry_id, **overrides)
    if payload.get("finish_status") != "FINISHED":
        payload.pop("elapsed_seconds", None)
    return get_success_data(
        api_client.create_race_result(payload, make_race_officer_headers(race_officer_id))
    )


def score_race(race_id, race_officer_id) -> dict:
    return get_success_data(
        api_client.score_race(race_id, make_race_officer_headers(race_officer_id))
    )


def run_race_to_started(race_id, race_officer_id, actual_start_utc) -> dict:
    """Begin the warning-signal sequence and then record the valid start."""
    start_sequence(race_id, race_officer_id)
    return record_start(race_id, race_officer_id, actual_start_utc)


# ── Read-through helpers ───────────────────────────────────────────────────
# PRD section 4 authorises ClubAdmin on every single read in the API, so a
# read-back never needs to borrow a racing role's identity.
def read_member(member_id: str) -> dict:
    return get_success_data(api_client.get_club_member(member_id, ADMIN))


def read_boat(boat_id: str) -> dict:
    return get_success_data(api_client.get_boat(boat_id, ADMIN))


def read_certificate(certificate_id: str) -> dict:
    return get_success_data(api_client.get_certificate(certificate_id, ADMIN))


def read_regatta(regatta_id: str) -> dict:
    return get_success_data(api_client.get_regatta(regatta_id, ADMIN))


def read_document(document_id: str) -> dict:
    return get_success_data(api_client.get_race_document(document_id, ADMIN))


def read_division(division_id: str) -> dict:
    return get_success_data(api_client.get_division(division_id, ADMIN))


def read_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_entry(entry_id, ADMIN))


def read_standing(entry_id: str) -> dict:
    return get_success_data(api_client.get_series_standing(entry_id, ADMIN))


def read_mark_boat(mark_boat_id: str) -> dict:
    return get_success_data(api_client.get_mark_boat(mark_boat_id, ADMIN))


def read_duty(duty_id: str) -> dict:
    return get_success_data(api_client.get_duty_assignment(duty_id, ADMIN))


def read_race(race_id: str) -> dict:
    return get_success_data(api_client.get_race(race_id, ADMIN))


def read_staffing(race_id: str) -> dict:
    return get_success_data(api_client.get_staffing(race_id, ADMIN))


def read_result(result_id: str) -> dict:
    return get_success_data(api_client.get_race_result(result_id, ADMIN))


def read_recall_event(recall_event_id: str) -> dict:
    return get_success_data(api_client.get_recall_event(recall_event_id, ADMIN))


def read_panel(panel_id: str) -> dict:
    return get_success_data(api_client.get_jury_panel(panel_id, ADMIN))


def read_protest(protest_id: str) -> dict:
    return get_success_data(api_client.get_protest(protest_id, ADMIN))


# ── The composite world builder ────────────────────────────────────────────
def build_racing_world(
    *,
    roster=None,
    regatta_overrides=None,
    publish="nor_si",
    divisions=None,
    entrants=None,
    confirm_division_codes=None,
    panel=False,
    seat_judges=("judge_member",),
    racing=False,
    staffing=False,
    duty_window=None,
    races=(),
    start_races=(),
    clock=None,
):
    """Build a regatta world in the order the PRD's phase gates require.

    A regatta must publish a notice of race before it may hold divisions, must
    publish sailing instructions before racing may open, and may only schedule
    and start races once entries are accepted, divisions confirmed and the three
    always-required committee positions are on station across the coverage
    window of every start.

    Every knob defaults to the smallest world that satisfies the caller, so a
    test asks only for the state it actually asserts on.
    """
    roster = roster or enrol_standard_roster()
    headers = roster_headers(roster)
    chair_id = roster["chair"]["id"]
    measurer_id = roster["measurer"]["id"]
    pro_id = roster["pro"]["id"]

    regatta = open_regatta(chair_id, **(regatta_overrides or {}))
    world = {
        "roster": roster,
        "h": headers,
        "ids": {key: member["id"] for key, member in roster.items()},
        "regatta": regatta,
        "regatta_id": regatta["id"],
        "documents": {},
        "divisions": {},
        "boats": {},
        "certificates": {},
        "entries": {},
        "panel": None,
        "duties": {},
        "races": {},
    }

    if publish in ("nor", "nor_si"):
        world["documents"]["NOR"] = publish_nor(regatta["id"], chair_id)
    if publish == "nor_si":
        world["documents"]["SI"] = publish_si(regatta["id"], chair_id)

    for spec in divisions or ():
        division = add_division(regatta["id"], chair_id, **spec)
        world["divisions"][division["code"]] = division

    for spec in entrants or ():
        key = spec.get("key", spec["helm"])
        helm_id = roster[spec["helm"]]["id"]
        boat = register_boat(helm_id, **spec.get("boat", {}))
        certificate = file_certificate(
            boat["id"], measurer_id,
            measurement=spec.get("measurement"),
            rule_code=spec.get("rule_code", "TOD_PHRF"),
            **spec.get("certificate", {}),
        )
        if spec.get("issue", True):
            certificate = issue_certificate(certificate["id"], measurer_id)
        entry = submit_entry(
            regatta["id"], boat["id"], certificate["id"], helm_id,
            **spec.get("entry", {}),
        )
        crew = spec.get("crew")
        if crew is None:
            crew = [{"member": spec["helm"], "position": "HELM", "weight_kg": 84.5}]
        for element in crew:
            member_id = roster[element["member"]]["id"] if "member" in element else element["member_id"]
            entry = add_crew(
                entry["id"], helm_id, member_id,
                position=element.get("position", "CREW"),
                weight_kg=element.get("weight_kg", 79.25),
            )
        if spec.get("inspect", "PASS") is not None:
            entry = inspect_entry(
                entry["id"], pro_id,
                outcome=spec.get("inspect", "PASS"),
                **spec.get("inspect_payload", {}),
            )
        if spec.get("assign", True):
            entry = assign_division(entry["id"], chair_id)
        if spec.get("accept", True):
            entry = accept_entry(entry["id"], chair_id)
        world["boats"][key] = boat
        world["certificates"][key] = certificate
        world["entries"][key] = entry

    if confirm_division_codes is None:
        confirm_division_codes = tuple(world["divisions"])
    for code in confirm_division_codes:
        world["divisions"][code] = confirm_division(world["divisions"][code]["id"], chair_id)

    if panel:
        formed = form_panel(regatta["id"], chair_id, roster["judge_chair"]["id"])
        for judge_key in seat_judges:
            formed = seat_judge(formed["id"], chair_id, roster[judge_key]["id"])
        world["panel"] = formed

    if racing:
        world["regatta"] = open_racing(regatta["id"], chair_id)

    if staffing:
        window = duty_window or (DUTY_WINDOW_START, DUTY_WINDOW_END)
        world["duties"] = staff_committee(
            regatta["id"], roster,
            window_start_utc=window[0], window_end_utc=window[1],
        )

    for spec in races:
        race = schedule_race(
            regatta["id"], chair_id,
            spec["race_number"], spec["scheduled_start_utc"],
            **{k: v for k, v in spec.items()
               if k not in ("race_number", "scheduled_start_utc", "start_at")},
        )
        world["races"][race["race_number"]] = race

    for race_number in start_races:
        race = world["races"][race_number]
        world["races"][race_number] = run_race_to_started(
            race["id"], pro_id, race["scheduled_start_utc"]
        )

    if clock is not None:
        set_clock(clock)

    world["regatta"] = read_regatta(regatta["id"])
    return world


# ── Named recipes over the builder ─────────────────────────────────────────
TWO_BOAT_DIVISION = ({"code": "A", "boat_type_filter": "MONOHULL",
                      "rating_band_low": 150.0, "rating_band_high": 230.0,
                      "min_entries": 2},)

TWO_ENTRANTS = (
    {"helm": "helm_1", "measurement": MEASUREMENT_A},
    {"helm": "helm_2", "measurement": MEASUREMENT_B},
)


def build_accepted_fleet_world(**overrides):
    """A sailing-instructions-published regatta holding one confirmed MONOHULL
    division 150.0-230.0 with two accepted entries. The fleet minimum is lowered
    to two so a two-boat division clears its effective floor.
    """
    params = {
        "regatta_overrides": {"fleet_minimum": 2, "jury_quorum_required": 2},
        "divisions": TWO_BOAT_DIVISION,
        "entrants": TWO_ENTRANTS,
    }
    regatta_overrides = overrides.pop("regatta_overrides", None)
    if regatta_overrides is not None:
        params["regatta_overrides"] = {**params["regatta_overrides"], **regatta_overrides}
    params.update(overrides)
    return build_racing_world(**params)


def build_started_race_world(**overrides):
    """The accepted-fleet world carried all the way to a started race: a seated
    two-judge jury panel, racing opened, the three always-required committee
    positions confirmed across 12:00-20:00, and race 1 started at 14:00 with the
    clock moved to the start so results may be recorded.
    """
    params = {
        "panel": True,
        "racing": True,
        "staffing": True,
        "races": ({"race_number": 1, "scheduled_start_utc": RACE_1_SCHEDULED_START},),
        "start_races": (1,),
        "clock": RACE_1_SCHEDULED_START,
    }
    params.update(overrides)
    return build_accepted_fleet_world(**params)


# ── Instant arithmetic on the logical clock ────────────────────────────────
def shift_utc(iso8601: str, minutes: int) -> str:
    """Offset an ISO 8601 UTC instant by whole minutes, keeping the format."""
    moment = _dt.datetime.strptime(iso8601, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=_dt.timezone.utc
    )
    return (moment + _dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sail_and_score_race(world, race_number, plan, results_delay_minutes=30):
    """Take one already-scheduled race of a built world from PENDING to FINAL.

    `plan` maps an entrant key to either an elapsed time in seconds, meaning a
    finisher, or to a dict of result overrides. An entrant absent from the plan
    records no result at all and is therefore minted `DNC` when the race is
    scored, which is how the did-not-compete rows of PRD 3.9 come into being.
    """
    race = world["races"][race_number]
    pro_id = world["ids"]["pro"]
    set_clock(race["scheduled_start_utc"])
    run_race_to_started(race["id"], pro_id, race["scheduled_start_utc"])
    set_clock(shift_utc(race["scheduled_start_utc"], results_delay_minutes))
    rows = {}
    for key, spec in plan.items():
        overrides = (
            {"elapsed_seconds": float(spec)} if isinstance(spec, (int, float)) else dict(spec)
        )
        rows[key] = record_result(
            race["id"], world["entries"][key]["id"], pro_id, **overrides
        )
    world.setdefault("results", {})[race_number] = rows
    world["races"][race_number] = score_race(race["id"], pro_id)
    return world["races"][race_number]
