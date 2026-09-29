"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test runs against an empty database.

Layering:
  * primitive wrappers   — one call, lenient validation, returns the resource
  * enrolment helpers    — athlete + agent + verified performance + invitation
  * lifecycle composites — field open, accepted, bibbed, locked, raced,
                           results certified, awards computed / approved / paid
"""
from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_athlete_payload,
    create_division_standard_payload,
    create_doping_test_payload,
    create_fluid_station_slot_payload,
    create_invitation_payload,
    create_pacer_assignment_payload,
    create_performance_record_payload,
    create_purse_line_payload,
    create_race_edition_payload,
    create_race_result_payload,
    create_rep_agent_payload,
    negotiation_round_payload,
    offer_payload,
    reject_performance_payload,
    verify_performance_payload,
)
from .test_users import TEST_USERS, make_athlete_agent_headers

from prd_bench_local_runner.testing import get_success_data, validate_paginated

DIRECTOR = TEST_USERS["elites_director_headers"]
TECHNICAL = TEST_USERS["technical_official_headers"]
LIAISON = TEST_USERS["anti_doping_liaison_headers"]
SANCTIONING = TEST_USERS["sanctioning_body_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
FINANCE_PAYER = TEST_USERS["finance_payer_headers"]


# ==========================================================================
# Logical clock
# ==========================================================================
def set_clock(to_iso8601, headers=DIRECTOR):
    """Move the logical clock (PRD §2.4). Mutates no entity."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def reset_clock():
    """Return the logical clock to the fixed instant the server starts at."""
    return set_clock(CLOCK_START)


# ==========================================================================
# Editions and configuration
# ==========================================================================
def create_edition(**overrides):
    payload = create_race_edition_payload(**overrides)
    return get_success_data(api_client.create_race_edition(payload, DIRECTOR))


def read_edition(edition_id, headers=DIRECTOR):
    return get_success_data(api_client.get_race_edition(edition_id, headers))


def add_purse_line(edition_id, **kwargs):
    payload = create_purse_line_payload(edition_id, **kwargs)
    return get_success_data(api_client.create_purse_line(payload, DIRECTOR))


def add_division_standard(edition_id, **kwargs):
    payload = create_division_standard_payload(edition_id, **kwargs)
    return get_success_data(api_client.create_division_standard(payload, DIRECTOR))


def open_field(edition_id):
    return get_success_data(api_client.open_field(edition_id, DIRECTOR))


def lock_field(edition_id):
    return get_success_data(api_client.lock_field(edition_id, DIRECTOR))


def mark_raced(edition_id):
    return get_success_data(api_client.mark_raced(edition_id, TECHNICAL))


def certify_edition_results(edition_id):
    return get_success_data(api_client.certify_results(edition_id, TECHNICAL))


def compute_awards(edition_id, expected_race_edition_version=None, headers=FINANCE):
    """Generate the award set, reading the edition's current version when the
    caller does not pin one explicitly."""
    if expected_race_edition_version is None:
        expected_race_edition_version = read_edition(edition_id)["version"]
    payload = {"expected_race_edition_version": expected_race_edition_version}
    return get_success_data(api_client.compute_awards(edition_id, payload, headers))


def settle_purse(edition_id, headers=FINANCE):
    return get_success_data(api_client.settle_purse(edition_id, headers))


def run_ops(edition_id):
    return get_success_data(api_client.run_ops(edition_id, DIRECTOR))


# ==========================================================================
# Athletes, agents and qualifying performances
# ==========================================================================
def register_athlete(**overrides):
    payload = create_athlete_payload(**overrides)
    return get_success_data(api_client.create_athlete(payload, DIRECTOR))


def read_athlete(athlete_id, headers=DIRECTOR):
    return get_success_data(api_client.get_athlete(athlete_id, headers))


def register_agent(**overrides):
    payload = create_rep_agent_payload(**overrides)
    return get_success_data(api_client.create_rep_agent(payload, DIRECTOR))


def submit_performance(athlete_id, **overrides):
    payload = create_performance_record_payload(athlete_id, **overrides)
    return get_success_data(api_client.create_performance_record(payload, DIRECTOR))


def verify_performance(record_id, official_seconds):
    payload = verify_performance_payload(official_seconds)
    return get_success_data(
        api_client.verify_performance_record(record_id, payload, TECHNICAL)
    )


def reject_performance(record_id, rejection_reason):
    payload = reject_performance_payload(rejection_reason)
    return get_success_data(
        api_client.verify_performance_record(record_id, payload, TECHNICAL)
    )


def create_verified_performance(athlete_id, verified_seconds=None, **overrides):
    """Submit a qualifying performance and verify it.

    `verified_seconds` is the official figure written by verification; it
    defaults to the claimed figure.
    """
    record = submit_performance(athlete_id, **overrides)
    official = (
        verified_seconds if verified_seconds is not None
        else record["performance_seconds"]
    )
    return verify_performance(record["id"], official)


# ==========================================================================
# Invitations, offers and the negotiation cycle
# ==========================================================================
def create_invitation(edition_id, athlete_id, agent_id, performance_id,
                      division="ELITE"):
    payload = create_invitation_payload(
        edition_id, athlete_id, agent_id, performance_id, division
    )
    return get_success_data(api_client.create_invitation(payload, DIRECTOR))


def read_invitation(invitation_id, headers=DIRECTOR):
    return get_success_data(api_client.get_invitation(invitation_id, headers))


def send_offer(invitation_id, headers=DIRECTOR, **package):
    payload = offer_payload(**package)
    return get_success_data(api_client.send_offer(invitation_id, payload, headers))


def agent_counters(invitation_id, agent_id, expected_invitation_version=None,
                   **package):
    """Append an `AGENT`-side negotiation round to an `OFFERED` invitation."""
    if expected_invitation_version is None:
        expected_invitation_version = read_invitation(invitation_id)["version"]
    payload = negotiation_round_payload(expected_invitation_version, **package)
    return get_success_data(
        api_client.create_negotiation_round(
            invitation_id, payload, make_athlete_agent_headers(agent_id)
        )
    )


def committee_counters(invitation_id, expected_invitation_version=None, **package):
    """Append a `COMMITTEE`-side negotiation round to a `COUNTERED` invitation."""
    if expected_invitation_version is None:
        expected_invitation_version = read_invitation(invitation_id)["version"]
    payload = negotiation_round_payload(expected_invitation_version, **package)
    return get_success_data(
        api_client.create_negotiation_round(invitation_id, payload, DIRECTOR)
    )


def respond_as_agent(invitation_id, agent_id, decision):
    return get_success_data(
        api_client.respond_to_invitation(
            invitation_id, {"decision": decision}, make_athlete_agent_headers(agent_id)
        )
    )


def respond_as_director(invitation_id, decision):
    return get_success_data(
        api_client.respond_to_invitation(invitation_id, {"decision": decision}, DIRECTOR)
    )


def withdraw_invitation(invitation_id, reason=None):
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.withdraw_invitation(invitation_id, payload,
                                                           DIRECTOR))


def assign_bib(invitation_id):
    return get_success_data(api_client.assign_bib(invitation_id, DIRECTOR))


# ==========================================================================
# Elite services
# ==========================================================================
def reserve_fluid_slot(invitation_id, station_km=10.0, table_position=3,
                       bottle_count=2):
    payload = create_fluid_station_slot_payload(
        invitation_id, station_km, table_position, bottle_count
    )
    return get_success_data(api_client.create_fluid_station_slot(payload, DIRECTOR))


def list_fluid_slots(invitation_id, headers=DIRECTOR, params=None):
    return validate_paginated(
        api_client.list_fluid_station_slots(invitation_id, headers, params)
    )


def register_pacer(edition_id, pacer_license_code="PC-1", start_km=0.0, end_km=21.0,
                   **overrides):
    payload = create_pacer_assignment_payload(
        edition_id, pacer_license_code, start_km, end_km, **overrides
    )
    return get_success_data(api_client.create_pacer_assignment(payload, DIRECTOR))


# ==========================================================================
# Doping tests
# ==========================================================================
def schedule_doping_test(athlete_id, edition_id, **overrides):
    payload = create_doping_test_payload(athlete_id, edition_id, **overrides)
    return get_success_data(api_client.create_doping_test(payload, LIAISON))


def read_doping_test(test_id, headers=LIAISON):
    return get_success_data(api_client.get_doping_test(test_id, headers))


def collect_sample(test_id, collected_sample_ref, at_iso8601=None):
    """Collect a sample, optionally moving the logical clock inside the window first."""
    if at_iso8601 is not None:
        set_clock(at_iso8601)
    return get_success_data(
        api_client.collect_sample(
            test_id, {"collected_sample_ref": collected_sample_ref}, LIAISON
        )
    )


def adjudicate_doping_test(test_id, outcome, outcome_notes=None):
    payload = {"outcome": outcome}
    if outcome_notes is not None:
        payload["outcome_notes"] = outcome_notes
    return get_success_data(
        api_client.adjudicate_doping_test(test_id, payload, SANCTIONING)
    )


def setup_cleared_test(athlete_id, edition_id, test_type="IN_COMPETITION",
                       window_start_at="2026-11-01T06:00:00Z",
                       window_end_at="2026-11-01T20:00:00Z",
                       sample_code=None, collect_at=None,
                       collected_sample_ref="COC-1"):
    """Schedule, collect and clear one test — the clearance that unlocks
    prize approval when the type is `IN_COMPETITION`."""
    test = schedule_doping_test(
        athlete_id, edition_id, test_type=test_type,
        window_start_at=window_start_at, window_end_at=window_end_at,
        sample_code=sample_code,
    )
    collect_sample(test["id"], collected_sample_ref,
                   at_iso8601=collect_at or window_start_at)
    return adjudicate_doping_test(test["id"], "CLEARED")


# ==========================================================================
# Race results
# ==========================================================================
def enter_result(edition_id, invitation_id, gun_seconds=7500, net_seconds=None):
    payload = create_race_result_payload(edition_id, invitation_id, gun_seconds,
                                        net_seconds)
    return get_success_data(api_client.create_race_result(payload, TECHNICAL))


def read_result(result_id, headers=TECHNICAL):
    return get_success_data(api_client.get_race_result(result_id, headers))


def certify_result(result_id):
    return get_success_data(api_client.certify_race_result(result_id, TECHNICAL))


def disqualify_result(result_id, dq_reason):
    return get_success_data(
        api_client.disqualify_race_result(result_id, {"dq_reason": dq_reason}, TECHNICAL)
    )


def submit_record_package(result_id, sanctioning_submission_ref):
    return get_success_data(
        api_client.submit_record_package(
            result_id, {"sanctioning_submission_ref": sanctioning_submission_ref},
            TECHNICAL,
        )
    )


def decide_record_claim(result_id, decision, decision_note=None):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(
        api_client.decide_record_claim(result_id, payload, SANCTIONING)
    )


# ==========================================================================
# Prize awards
# ==========================================================================
def list_awards(params=None, headers=FINANCE):
    return validate_paginated(api_client.list_prize_awards(headers, params))


def read_award(award_id, headers=FINANCE):
    return get_success_data(api_client.get_prize_award(award_id, headers))


def approve_award(award_id, headers=FINANCE):
    return get_success_data(api_client.approve_prize_award(award_id, headers))


def pay_award(award_id, payment_reference="TRSY-1", headers=FINANCE_PAYER):
    return get_success_data(
        api_client.pay_prize_award(award_id, {"payment_reference": payment_reference},
                                   headers)
    )


# ==========================================================================
# Tier 2 — configured and open editions
# ==========================================================================
DEFAULT_PURSE_LINES = [
    {"category": "OVERALL", "gender": "MALE", "place": 1, "amount_cents": 1_000_000},
]
DEFAULT_STANDARDS = [
    {"division": "ELITE", "gender": "MALE"},
]


def setup_configured_edition(purse_lines=None, standards=None, **edition_overrides):
    """Create an edition in `PLANNING` and build out its purse structure.

    `purse_lines` and `standards` are lists of keyword dicts; the edition id is
    threaded in automatically.
    """
    edition = create_edition(**edition_overrides)
    lines = [
        add_purse_line(edition["id"], **spec)
        for spec in (purse_lines if purse_lines is not None else DEFAULT_PURSE_LINES)
    ]
    stds = [
        add_division_standard(edition["id"], **spec)
        for spec in (standards if standards is not None else DEFAULT_STANDARDS)
    ]
    return {
        "edition": read_edition(edition["id"]),
        "purse_lines": lines,
        "standards": stds,
    }


def setup_field_open_edition(purse_lines=None, standards=None, **edition_overrides):
    """Configured edition moved `PLANNING → FIELD_OPEN`."""
    scenario = setup_configured_edition(purse_lines, standards, **edition_overrides)
    open_field(scenario["edition"]["id"])
    scenario["edition"] = read_edition(scenario["edition"]["id"])
    return scenario


def standards_for(entrants):
    """Derive one division standard per distinct division / gender pair, giving
    each pair its own bib pool."""
    seen = []
    for entrant in entrants:
        pair = (entrant.get("division", "ELITE"), entrant.get("gender", "MALE"))
        if pair not in seen:
            seen.append(pair)
    specs = []
    for index, (division, gender) in enumerate(seen):
        start = TEST_DEFAULTS["BIB_RANGE_START"] + index * 100
        specs.append({
            "division": division,
            "gender": gender,
            "bib_range_start": start,
            "bib_range_end": start + 89,
        })
    return specs


# ==========================================================================
# Tier 3 — enrolling athletes onto an open edition
# ==========================================================================
def enroll_draft_invitation(edition_id, division="ELITE", gender="MALE",
                            athlete_overrides=None, agent_overrides=None,
                            performance_overrides=None, verified_seconds=None,
                            verify=True, agent=None):
    """Register an athlete and an agent, lodge a qualifying performance and
    create the `DRAFT` invitation that pins it."""
    athlete_kwargs = dict(gender=gender)
    athlete_kwargs.update(athlete_overrides or {})
    athlete = register_athlete(**athlete_kwargs)
    agent = agent or register_agent(**(agent_overrides or {}))
    performance_kwargs = {"division": division}
    performance_kwargs.update(performance_overrides or {})
    record = submit_performance(athlete["id"], **performance_kwargs)
    if verify:
        record = verify_performance(
            record["id"],
            verified_seconds if verified_seconds is not None
            else record["performance_seconds"],
        )
    invitation = create_invitation(
        edition_id, athlete["id"], agent["id"], record["id"], division
    )
    return {
        "athlete": athlete,
        "agent": agent,
        "record": record,
        "invitation": invitation,
    }


DEFAULT_OFFER = {
    "appearance_fee_cents": 500_000,
    "air_class": "ECONOMY",
    "hotel_nights": 2,
    "ground_transport": False,
}


def enroll_offered_invitation(edition_id, offer=None, **enrol_kwargs):
    """`DRAFT → OFFERED` — the committee's opening package is on the table."""
    scenario = enroll_draft_invitation(edition_id, **enrol_kwargs)
    package = dict(DEFAULT_OFFER)
    package.update(offer or {})
    scenario["invitation"] = send_offer(scenario["invitation"]["id"], **package)
    scenario["offer"] = package
    return scenario


def enroll_accepted_invitation(edition_id, offer=None, with_bib=False,
                               **enrol_kwargs):
    """`DRAFT → OFFERED → ACCEPTED`, optionally taking a bib as well."""
    scenario = enroll_offered_invitation(edition_id, offer=offer, **enrol_kwargs)
    scenario["invitation"] = respond_as_agent(
        scenario["invitation"]["id"], scenario["agent"]["id"], "ACCEPT"
    )
    if with_bib:
        scenario["invitation"] = assign_bib(scenario["invitation"]["id"])
    return scenario


DOPING_COMPLIANT = {"whereabouts_filed": True}


def enroll_bibbed_invitation(edition_id, offer=None, athlete_overrides=None,
                             **enrol_kwargs):
    """Accepted invitation holding a bib. The athlete files whereabouts so the
    anti-doping availability gate passes."""
    athlete_kwargs = dict(DOPING_COMPLIANT)
    athlete_kwargs.update(athlete_overrides or {})
    return enroll_accepted_invitation(
        edition_id, offer=offer, with_bib=True, athlete_overrides=athlete_kwargs,
        **enrol_kwargs
    )


# ==========================================================================
# Tier 4 — race day and the certified result set
# ==========================================================================
def setup_raced_edition(entrants, purse_lines=None, standards=None,
                        race_clock=None, **edition_overrides):
    """Open the field, enrol every entrant with a bib, lock the field, move the
    clock to race day and mark the edition `RACED`.

    Each entrant spec accepts: division, gender, athlete_overrides,
    performance_overrides, verified_seconds, offer.
    """
    scenario = setup_field_open_edition(
        purse_lines,
        standards if standards is not None else standards_for(entrants),
        **edition_overrides,
    )
    edition = scenario["edition"]
    enrolled = []
    for spec in entrants:
        spec = dict(spec)
        gun = spec.pop("gun_seconds", None)
        net = spec.pop("net_seconds", None)
        athlete_overrides = dict(DOPING_COMPLIANT)
        athlete_overrides.update(spec.pop("athlete_overrides", None) or {})
        entrant = enroll_bibbed_invitation(
            edition["id"], athlete_overrides=athlete_overrides, **spec
        )
        entrant["gun_seconds"] = gun
        entrant["net_seconds"] = net
        enrolled.append(entrant)
    lock_field(edition["id"])
    set_clock(race_clock or f"{edition['race_date']}T00:00:00Z")
    mark_raced(edition["id"])
    scenario["edition"] = read_edition(edition["id"])
    scenario["entrants"] = enrolled
    return scenario


def setup_edition_with_certified_results(entrants, purse_lines=None, standards=None,
                                         race_clock=None, certify_edition=True,
                                         **edition_overrides):
    """Full run to a certified result set.

    Enters one result per entrant (`gun_seconds` / `net_seconds` from the spec),
    certifies each unless the spec says `certify: False`, and then runs the
    edition-level certification pass that assigns places, ties and record claims.
    """
    scenario = setup_raced_edition(
        [
            {k: v for k, v in spec.items() if k != "certify"}
            for spec in entrants
        ],
        purse_lines=purse_lines, standards=standards, race_clock=race_clock,
        **edition_overrides,
    )
    edition = scenario["edition"]
    for spec, entrant in zip(entrants, scenario["entrants"]):
        result = enter_result(
            edition["id"], entrant["invitation"]["id"],
            gun_seconds=spec.get("gun_seconds", 7500),
            net_seconds=spec.get("net_seconds"),
        )
        if spec.get("certify", True):
            result = certify_result(result["id"])
        entrant["result"] = result
    if certify_edition:
        certify_edition_results(edition["id"])
        for entrant in scenario["entrants"]:
            entrant["result"] = read_result(entrant["result"]["id"])
    scenario["edition"] = read_edition(edition["id"])
    return scenario


# ==========================================================================
# Tier 5 — awards, approval, payment and settlement
# ==========================================================================
def setup_edition_with_computed_awards(entrants, purse_lines=None, standards=None,
                                       **edition_overrides):
    """Certified result set plus one generated award run."""
    scenario = setup_edition_with_certified_results(
        entrants, purse_lines=purse_lines, standards=standards, **edition_overrides
    )
    compute_awards(scenario["edition"]["id"])
    scenario["edition"] = read_edition(scenario["edition"]["id"])
    awards, _ = list_awards({"race_edition_id": scenario["edition"]["id"]})
    scenario["awards"] = awards
    return scenario


def setup_paid_award(entrants=None, purse_lines=None, payment_reference="TRSY-1",
                     approver=FINANCE, payer=FINANCE_PAYER, **edition_overrides):
    """Take the first computed award of a one-runner edition all the way to `PAID`.

    The winner is cleared by an `IN_COMPETITION` test, which is what unlocks
    approval, and the two finance acts are performed by different operators.
    """
    entrants = entrants or [{"gun_seconds": 7500}]
    scenario = setup_edition_with_certified_results(
        entrants, purse_lines=purse_lines, **edition_overrides
    )
    edition = scenario["edition"]
    winner = scenario["entrants"][0]
    setup_cleared_test(
        winner["athlete"]["id"], edition["id"], test_type="IN_COMPETITION",
        window_start_at=f"{edition['race_date']}T06:00:00Z",
        window_end_at=f"{edition['race_date']}T20:00:00Z",
        sample_code="COC-IC-1",
    )
    compute_awards(edition["id"])
    awards, _ = list_awards({"race_edition_id": edition["id"]})
    award = awards[0]
    approve_award(award["id"], approver)
    scenario["award"] = pay_award(award["id"], payment_reference, payer)
    scenario["awards"] = awards
    scenario["edition"] = read_edition(edition["id"])
    return scenario
