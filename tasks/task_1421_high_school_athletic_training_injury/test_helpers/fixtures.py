"""Composite setup helpers (PRD §3 workflows), built from PRD-declared
endpoints only. Setup calls use the lenient get_success_data validator so a
setup failure surfaces as a clear "Setup failed" message.

Every helper builds its preconditions from scratch: the harness restarts the
server before every test, so no state is shared between tests.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_iso8601
from .factories import (
    create_athlete_payload,
    create_baseline_payload,
    create_coverage_assignment_payload,
    create_eap_payload,
    create_event_payload,
    create_injury_payload,
    create_inventory_transaction_payload,
    create_physical_payload,
    create_referral_payload,
    create_restock_order_payload,
    create_staff_payload,
    create_supply_budget_payload,
    create_supply_item_payload,
    create_venue_payload,
    create_weather_reading_payload,
)
from .test_users import (
    TEST_USERS,
    make_athletic_director_headers,
    make_athletic_trainer_headers,
    make_physician_headers,
    make_school_nurse_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]


def _ok(resp, what: str):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data and "current_utc" not in data:
        raise AssertionError(f"Setup failed for {what}: {resp.status_code} {data!r}")
    return data


# --- Tier 0: identity --------------------------------------------------------


def make_staff(role_type: str, full_name: str = None, **overrides) -> dict:
    """Create a Staff record as SystemAdmin. Returns the staff dict."""
    payload = create_staff_payload(role_type=role_type,
                                   **({"full_name": full_name} if full_name else {}),
                                   **overrides)
    return _ok(api_client.create_staff(payload, ADMIN), f"staff {role_type}")


def make_trainer(full_name: str = "Trainer One") -> dict:
    return make_staff("ATHLETIC_TRAINER", full_name)


def make_nurse(full_name: str = "Nurse Nia") -> dict:
    return make_staff("SCHOOL_NURSE", full_name)


def make_physician(full_name: str = "Doc Em") -> dict:
    return make_staff("PHYSICIAN", full_name)


def make_director(full_name: str = "Director Dee") -> dict:
    return make_staff("ATHLETIC_DIRECTOR", full_name)


def make_coach(full_name: str = "Coach Cal") -> dict:
    return make_staff("TEAM_COACH", full_name)


def trainer_headers(staff: dict) -> dict:
    return make_athletic_trainer_headers(staff["id"])


def nurse_headers(staff: dict) -> dict:
    return make_school_nurse_headers(staff["id"])


def physician_headers(staff: dict) -> dict:
    return make_physician_headers(staff["id"])


def director_headers(staff: dict) -> dict:
    return make_athletic_director_headers(staff["id"])


def set_clock(to_iso8601: str):
    """Move the logical clock (SystemAdmin-only, PRD §2.4)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    data = get_success_data(resp)
    if not isinstance(data, dict):
        raise AssertionError(f"Setup failed for clock set: {resp.status_code}")
    return data


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_hours(iso_ts: str, hours: float) -> str:
    return _iso(parse_iso8601(iso_ts) + timedelta(hours=hours))


def plus_days(iso_ts: str, days: float) -> str:
    return _iso(parse_iso8601(iso_ts) + timedelta(days=days))


# --- Tier 1/2: athlete + medical records ------------------------------------


def create_athlete_as_trainer(trainer: dict, **overrides) -> dict:
    payload = create_athlete_payload(**overrides)
    return _ok(api_client.create_athlete(payload, trainer_headers(trainer)),
               "athlete")


def record_physical(athlete_id: str, recorder: dict,
                    recorder_role: str = "AthleticTrainer",
                    **overrides) -> dict:
    """Record a physical; recorded_by is the caller (PRD §3.1)."""
    headers = (make_school_nurse_headers(recorder["id"])
               if recorder_role == "SchoolNurse"
               else make_athletic_trainer_headers(recorder["id"]))
    payload = create_physical_payload(athlete_id=athlete_id, **overrides)
    return _ok(api_client.create_physical(payload, headers), "physical")


def verify_physical(physical_id: str, nurse: dict) -> dict:
    return _ok(api_client.verify_physical(physical_id, nurse_headers(nurse)),
               "physical verify")


def record_baseline(athlete_id: str, staff: dict, **overrides) -> dict:
    payload = create_baseline_payload(athlete_id=athlete_id, **overrides)
    return _ok(api_client.create_baseline_test(
        payload, trainer_headers(staff)), "baseline")


def setup_cleared_athlete(trainer: dict, nurse: dict,
                          athlete_overrides: dict = None,
                          physical_overrides: dict = None,
                          baseline_overrides: dict = None) -> dict:
    """Athlete with a VERIFIED physical and a CURRENT baseline: posture CLEARED
    (PRD §3.1 gates 1-2 pass, no injuries)."""
    athlete = create_athlete_as_trainer(trainer, **(athlete_overrides or {}))
    ph = record_physical(athlete["id"], trainer, **(physical_overrides or {}))
    verify_physical(ph["id"], nurse)
    record_baseline(athlete["id"], trainer, **(baseline_overrides or {}))
    return athlete


def create_injury_for(athlete_id: str, trainer: dict, **overrides) -> dict:
    payload = create_injury_payload(athlete_id=athlete_id, **overrides)
    return _ok(api_client.create_injury(payload, trainer_headers(trainer)),
               "injury")


def begin_care(injury_id: str, trainer: dict) -> dict:
    return _ok(api_client.begin_care_injury(injury_id,
                                            trainer_headers(trainer)),
               "begin-care")


def setup_injury_under_care(trainer: dict, athlete_id: str,
                            **injury_overrides) -> dict:
    """Injury documented then moved to UNDER_CARE. Returns the injury."""
    injury = create_injury_for(athlete_id, trainer, **injury_overrides)
    return begin_care(injury["id"], trainer)


def create_rtp_protocol(injury: dict, trainer: dict) -> dict:
    """Activate a GRADUATED_6_STAGE protocol with the injury's current version
    as the OCC anchor (PRD §2.7)."""
    payload = {"protocol_type": "GRADUATED_6_STAGE",
               "expected_injury_version": injury["version"]}
    return _ok(api_client.create_rtp_protocol(
        injury["id"], payload, trainer_headers(trainer)), "rtp protocol")


def setup_athlete_with_rtp(trainer: dict, nurse: dict,
                           injury_overrides: dict = None,
                           athlete_overrides: dict = None,
                           physical_overrides: dict = None,
                           baseline_overrides: dict = None,
                           protocol_clock: str = None):
    """Cleared athlete + injury UNDER_CARE + ACTIVE protocol at stage 1.

    Returns (athlete, injury, protocol). When protocol_clock is given the
    clock is set before the injury is documented, so the protocol's
    stage_entered_at lands on that instant.
    """
    athlete = setup_cleared_athlete(trainer, nurse,
                                    athlete_overrides=athlete_overrides,
                                    physical_overrides=physical_overrides,
                                    baseline_overrides=baseline_overrides)
    if protocol_clock is not None:
        set_clock(protocol_clock)
    injury = create_injury_for(athlete["id"], trainer,
                               **(injury_overrides or {}))
    injury = begin_care(injury["id"], trainer)
    protocol = create_rtp_protocol(injury, trainer)
    return athlete, injury, protocol


def advance_protocol(protocol_id: str, trainer: dict,
                     symptom_check_passed: bool = True) -> dict:
    return _ok(api_client.advance_rtp_protocol(
        protocol_id, {"symptom_check_passed": symptom_check_passed},
        trainer_headers(trainer)), "rtp advance")


def walk_protocol_to_stage(protocol_id: str, trainer: dict,
                           stage_entered_at: str, target_stage: int) -> dict:
    """Advance an ACTIVE protocol one stage per 24h clock step until it sits
    at target_stage. stage_entered_at is the instant the current stage was
    entered. Returns the latest protocol payload."""
    protocol = None
    entered = stage_entered_at
    current = get_success_data(api_client.get_rtp_protocol(
        protocol_id, trainer_headers(trainer)))["current_stage"]
    while current < target_stage:
        set_clock(plus_hours(entered, 24))
        protocol = advance_protocol(protocol_id, trainer)
        entered = protocol["stage_entered_at"]
        current = protocol["current_stage"]
    return protocol


def create_referral_for(injury_id: str, physician: dict, trainer: dict,
                        **overrides) -> dict:
    payload = create_referral_payload(injury_id=injury_id,
                                      physician_staff_id=physician["id"],
                                      **overrides)
    return _ok(api_client.create_referral(payload, trainer_headers(trainer)),
               "referral")


def schedule_referral(referral_id: str, trainer: dict,
                      appointment_at: str = "2026-08-03T10:00:00Z") -> dict:
    return _ok(api_client.schedule_referral(
        referral_id, {"appointment_at": appointment_at},
        trainer_headers(trainer)), "referral schedule")


def complete_referral(referral_id: str, physician: dict,
                      report_diagnosis: str = "evaluated",
                      report_clearance: str = "CLEARED_FULL") -> dict:
    return _ok(api_client.complete_referral(
        referral_id,
        {"report_diagnosis": report_diagnosis,
         "report_clearance": report_clearance},
        physician_headers(physician)), "referral complete")


# --- Tier 2: venue / EAP / events -------------------------------------------


def create_venue(**overrides) -> dict:
    return _ok(api_client.create_venue(create_venue_payload(**overrides),
                                       ADMIN), "venue")


def create_eap_for(venue_id: str, author: dict,
                   author_role: str = "AthleticTrainer", **overrides) -> dict:
    headers = (make_athletic_director_headers(author["id"])
               if author_role == "AthleticDirector"
               else make_athletic_trainer_headers(author["id"]))
    payload = create_eap_payload(venue_id=venue_id, **overrides)
    return _ok(api_client.create_eap(payload, headers), "eap")


def drive_eap_to_approved(eap_id: str, submitter: dict, approver: dict) -> dict:
    """DRAFT -> PENDING_APPROVAL -> APPROVED (approver != author, PRD §3.2)."""
    _ok(api_client.submit_eap(eap_id, trainer_headers(submitter)),
        "eap submit")
    return _ok(api_client.approve_eap(eap_id, director_headers(approver)),
               "eap approve")


def setup_venue_with_active_eap(trainer: dict, director: dict,
                                venue_overrides: dict = None):
    """Venue + EAP walked DRAFT -> PENDING_APPROVAL -> APPROVED -> ACTIVE.

    Returns (venue, eap); the venue dict is re-read after activation so its
    version/active_eap_id are current.
    """
    venue = create_venue(**(venue_overrides or {}))
    eap = create_eap_for(venue["id"], trainer)
    drive_eap_to_approved(eap["id"], trainer, director)
    venue = _ok(api_client.get_venue(venue["id"], ADMIN), "venue re-read")
    _ok(api_client.activate_eap(
        eap["id"], {"expected_venue_version": venue["version"]},
        director_headers(director)), "eap activate")
    venue = _ok(api_client.get_venue(venue["id"], ADMIN), "venue re-read")
    eap = _ok(api_client.get_eap(eap["id"], ADMIN), "eap re-read")
    return venue, eap


def create_event(director: dict, **overrides) -> dict:
    payload = create_event_payload(**overrides)
    return _ok(api_client.create_event(payload, director_headers(director)),
               "event")


def create_event_as_trainer(trainer: dict, **overrides) -> dict:
    payload = create_event_payload(**overrides)
    return _ok(api_client.create_event(payload, trainer_headers(trainer)),
               "event")


def assign_coverage(event_id: str, staff_id: str, coverage_role: str,
                    creator: dict) -> dict:
    payload = create_coverage_assignment_payload(
        event_id=event_id, staff_id=staff_id, coverage_role=coverage_role)
    return _ok(api_client.create_coverage_assignment(
        payload, director_headers(creator)), "coverage assignment")


def setup_covered_event(director: dict, assignments, **event_overrides):
    """Create an event and assign (staff_id, coverage_role) pairs until the
    active count meets the requirement, bubbling it to COVERED (PRD §3.3).

    assignments: list of (staff_dict, "PRIMARY"|"SECONDARY").
    Returns (event, [assignment_dict, ...]).
    """
    event = create_event(director, **event_overrides)
    made = []
    for staff, role in assignments:
        made.append(assign_coverage(event["id"], staff["id"], role, director))
    event = _ok(api_client.get_event(event["id"], ADMIN), "event re-read")
    return event, made


# --- Tier 2: weather ---------------------------------------------------------


def post_weather_reading(venue_id: str, staff: dict, **overrides) -> dict:
    payload = create_weather_reading_payload(venue_id=venue_id, **overrides)
    return _ok(api_client.create_weather_reading(
        payload, trainer_headers(staff)), "weather reading")


# --- Tier 2: notifications ---------------------------------------------------


def list_notifications(trainer: dict, **params) -> list:
    data = get_success_data(api_client.list_guardian_notifications(
        trainer_headers(trainer), params=params))
    if isinstance(data, list):
        return data
    raise AssertionError(f"Setup failed listing notifications: {data!r}")


def first_notification_for_athlete(athlete_id: str, trainer: dict,
                                   **params) -> dict:
    rows = list_notifications(trainer, athlete_id=athlete_id, **params)
    if not rows:
        raise AssertionError(
            f"Setup failed: no notification for athlete {athlete_id}")
    return rows[0]


# --- Tier 2/4: supplies, ledger, orders, budgets -----------------------------


def create_supply_item(**overrides) -> dict:
    return _ok(api_client.create_supply_item(
        create_supply_item_payload(**overrides), ADMIN), "supply item")


def post_ledger_entry(item_id: str, staff: dict, **overrides) -> dict:
    payload = create_inventory_transaction_payload(supply_item_id=item_id,
                                                   **overrides)
    return _ok(api_client.create_inventory_transaction(
        payload, trainer_headers(staff)), "inventory transaction")


def get_item(item_id: str, headers=None) -> dict:
    return _ok(api_client.get_supply_item(item_id, headers or ADMIN),
               "supply item get")


def get_valuation(item_id: str, policy: str, staff: dict = None) -> dict:
    """Valuation is a computed report, not a primary resource: the response
    carries supply_item_id/policy/quantity_on_hand/valuation_cents and no
    `id` (PRD §3.9), so the generic `_ok` id check does not apply."""
    headers = trainer_headers(staff) if staff else ADMIN
    data = get_success_data(
        api_client.get_supply_item_valuation(item_id, policy, headers))
    if not isinstance(data, dict) or "valuation_cents" not in data:
        raise AssertionError(
            f"Setup failed for valuation {policy}: {data!r}")
    return data


def create_budget(fiscal_year: int, total_budget_cents: int) -> dict:
    return _ok(api_client.create_supply_budget(
        create_supply_budget_payload(fiscal_year=fiscal_year,
                                     total_budget_cents=total_budget_cents),
        ADMIN), "supply budget")


def get_budget_by_year(fiscal_year: int) -> dict:
    data = get_success_data(api_client.list_supply_budgets(
        ADMIN, params={"fiscal_year": fiscal_year}))
    if not isinstance(data, list) or not data:
        raise AssertionError(
            f"Setup failed: no budget for fiscal_year {fiscal_year}")
    return data[0]


def create_order(item_id: str, requester: dict,
                 requester_role: str = "AthleticTrainer", **overrides) -> dict:
    headers = (make_athletic_director_headers(requester["id"])
               if requester_role == "AthleticDirector"
               else make_athletic_trainer_headers(requester["id"]))
    payload = create_restock_order_payload(supply_item_id=item_id, **overrides)
    return _ok(api_client.create_restock_order(payload, headers),
               "restock order")


def submit_order(order_id: str, submitter: dict,
                 submitter_role: str = "AthleticTrainer") -> dict:
    headers = (make_athletic_director_headers(submitter["id"])
               if submitter_role == "AthleticDirector"
               else make_athletic_trainer_headers(submitter["id"]))
    return _ok(api_client.submit_restock_order(order_id, headers),
               "order submit")


def setup_submitted_order(item_id: str, requester: dict, **overrides) -> dict:
    order = create_order(item_id, requester, **overrides)
    return submit_order(order["id"], requester)


def setup_approved_order(item_id: str, requester: dict, approver: dict,
                         **overrides) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED (approver != requester, PRD §3.9)."""
    order = setup_submitted_order(item_id, requester, **overrides)
    return _ok(api_client.approve_restock_order(
        order["id"], director_headers(approver)), "order approve")
