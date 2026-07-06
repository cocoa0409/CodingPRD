"""Composite setup helpers for the parking-enforcement benchmark.

Each helper builds its preconditions from scratch through PRD-declared
endpoints (PRD §3.x, §4). The runner restarts the API server before every
individual pytest test, so every helper starts from an empty database and a
logical clock at its startup default of 2026-03-01T00:00:00Z (PRD §2.5).

Helpers use ``get_success_data()`` (lenient validator) so setup failures
surface as clear "Setup failed" traces rather than cryptic assertion noise.

Identity threading: ``EnforcementOfficer`` is entity-backed (PRD §2.1).
After a helper registers an Officer, every ownership-gated call (open/close
shift, issue citation) threads that Officer.id through
``make_enforcement_officer_headers`` so the ownership check sees a real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_enforcement_officer_headers

_ADMIN = TEST_USERS["admin_headers"]
_SUPERVISOR = TEST_USERS["supervisor_headers"]
_HEARING = TEST_USERS["hearing_officer_headers"]
_MOTORIST = TEST_USERS["motorist_headers"]


# ─── Tier 0: logical clock ───────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock to a specific instant (PRD §2.5)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN)
    )


# ─── Tier 1: single-resource creators ────────────────────────────

def create_officer(badge_number="B-100", full_name="Test Officer") -> dict:
    return get_success_data(api_client.create_officer(
        {"badge_number": badge_number, "full_name": full_name}, _ADMIN))


def create_beat(patrol_zone="RESIDENTIAL", beat_code="BEAT1", name="Test Beat") -> dict:
    return get_success_data(api_client.create_beat(
        {"beat_code": beat_code, "name": name, "patrol_zone": patrol_zone}, _ADMIN))


def create_violation_code(code="EXP_METER", description="Expired meter",
                          base_fine_cents=5000, is_booting_eligible=True) -> dict:
    return get_success_data(api_client.create_violation_code(
        {"code": code, "description": description,
         "base_fine_cents": base_fine_cents,
         "is_booting_eligible": is_booting_eligible}, _ADMIN))


def retire_violation_code(vc_id: str) -> dict:
    return get_success_data(api_client.retire_violation_code(vc_id, _ADMIN))


def create_hearing_room(room_code="HR1", name="Hearing Room 1") -> dict:
    return get_success_data(api_client.create_hearing_room(
        {"room_code": room_code, "name": name}, _ADMIN))


def create_vehicle(plate="PLT100", state="CA", headers=None) -> dict:
    return get_success_data(api_client.create_vehicle(
        {"plate": plate, "state": state}, headers or _ADMIN))


def open_shift(officer_id, beat_id,
               scheduled_start="2026-03-02T08:00:00Z",
               scheduled_end="2026-03-02T16:00:00Z") -> dict:
    return get_success_data(api_client.create_shift(
        {"officer_id": officer_id, "beat_id": beat_id,
         "scheduled_start": scheduled_start, "scheduled_end": scheduled_end},
        make_enforcement_officer_headers(officer_id)))


def close_shift(shift_id, officer_id) -> dict:
    return get_success_data(api_client.close_shift(
        shift_id, make_enforcement_officer_headers(officer_id)))


def issue_citation(officer_id, shift_id, vehicle_id, violation_code_id,
                   issued_via="LPR",
                   evidence_photo_url="https://evidence.example/photo.jpg") -> dict:
    return get_success_data(api_client.create_citation(
        {"vehicle_id": vehicle_id, "shift_id": shift_id,
         "violation_code_id": violation_code_id, "issued_via": issued_via,
         "evidence_photo_url": evidence_photo_url},
        make_enforcement_officer_headers(officer_id)))


def create_payment(citation_id, amount_cents, method="CARD") -> dict:
    return get_success_data(api_client.create_payment(
        {"citation_id": citation_id, "amount_cents": amount_cents, "method": method},
        _MOTORIST))


def settle_payment(payment_id) -> dict:
    return get_success_data(api_client.settle_payment(payment_id, _MOTORIST))


def refund_payment(payment_id) -> dict:
    return get_success_data(api_client.refund_payment(payment_id, _SUPERVISOR))


def void_citation(citation_id) -> dict:
    return get_success_data(api_client.void_citation(citation_id, _SUPERVISOR))


def reassess_citation(citation_id, new_fine_amount_cents, expected_citation_version) -> dict:
    return get_success_data(api_client.reassess_citation(
        citation_id,
        {"new_fine_amount_cents": new_fine_amount_cents,
         "expected_citation_version": expected_citation_version}, _SUPERVISOR))


def apply_waiver(vehicle_id, citation_id, waive_amount_cents, expected_vehicle_version) -> dict:
    return get_success_data(api_client.create_adjustment(
        vehicle_id,
        {"citation_id": citation_id, "waive_amount_cents": waive_amount_cents,
         "expected_vehicle_version": expected_vehicle_version}, _SUPERVISOR))


def file_contest(citation_id, grounds="Disputed citation") -> dict:
    return get_success_data(api_client.create_contest(
        {"citation_id": citation_id, "grounds": grounds}, _MOTORIST))


def schedule_hearing(contest_id, room_id,
                     scheduled_start="2026-03-05T09:00:00Z",
                     scheduled_end="2026-03-05T10:00:00Z") -> dict:
    return get_success_data(api_client.create_hearing(
        {"contest_id": contest_id, "room_id": room_id,
         "scheduled_start": scheduled_start, "scheduled_end": scheduled_end}, _HEARING))


def decide_hearing(hearing_id, decision) -> dict:
    return get_success_data(api_client.decide_hearing(
        hearing_id, {"decision": decision}, _HEARING))


def get_vehicle(vehicle_id) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, _ADMIN))


def get_citation(citation_id) -> dict:
    return get_success_data(api_client.get_citation(citation_id, _ADMIN))


def list_boot_tow_orders(vehicle_id) -> list:
    return get_success_data(api_client.list_boot_tow_orders(
        _SUPERVISOR, params={"vehicle_id": vehicle_id}))


def list_registration_holds(vehicle_id) -> list:
    return get_success_data(api_client.list_registration_holds(
        _ADMIN, params={"vehicle_id": vehicle_id}))


# ─── Tier 2: issuing context ─────────────────────────────────────

def setup_issuing_context(patrol_zone="RESIDENTIAL", base_fine_cents=5000,
                          is_booting_eligible=True, code="EXP_METER",
                          badge_number="B-100", beat_code="BEAT1",
                          plate="PLT100",
                          scheduled_start="2026-03-02T08:00:00Z",
                          scheduled_end="2026-03-02T16:00:00Z") -> dict:
    """Officer + beat + ACTIVE violation code + vehicle + one OPEN shift.

    The common precondition for every citation-issue scenario. Returns a
    dict with the created ``officer``, ``beat``, ``violation_code``,
    ``vehicle``, and ``shift`` resources."""
    officer = create_officer(badge_number=badge_number)
    beat = create_beat(patrol_zone=patrol_zone, beat_code=beat_code)
    vc = create_violation_code(code=code, base_fine_cents=base_fine_cents,
                               is_booting_eligible=is_booting_eligible)
    vehicle = create_vehicle(plate=plate)
    shift = open_shift(officer["id"], beat["id"], scheduled_start, scheduled_end)
    return {"officer": officer, "beat": beat, "violation_code": vc,
            "vehicle": vehicle, "shift": shift}


def issue_in_context(ctx: dict, issued_via="LPR", evidence_photo_url="https://ev/x.jpg") -> dict:
    """Issue one citation against the shift/vehicle/code in ``ctx``."""
    return issue_citation(
        ctx["officer"]["id"], ctx["shift"]["id"], ctx["vehicle"]["id"],
        ctx["violation_code"]["id"], issued_via=issued_via,
        evidence_photo_url=evidence_photo_url)


# ─── Tier 3: escalated vehicle ───────────────────────────────────

def setup_boot_eligible_vehicle() -> dict:
    """Drive a vehicle to BOOT_ELIGIBLE via three HYDRANT citations.

    base_fine 15000 in a RESIDENTIAL zone (surcharge 0):
      cit1 (n=0) -> 15000, cit2 (n=1) -> 22500, cit3 (n=2, clamped) -> 25000;
      outstanding 62500 >= 50000 -> BOOT_ELIGIBLE, which auto-creates an
      ORDERED boot order and a PLACED registration hold.

    Returns the issuing context plus ``citations`` (list of three),
    ``boot_order`` (the auto order), and ``hold`` (the placed hold)."""
    ctx = setup_issuing_context(
        patrol_zone="RESIDENTIAL", base_fine_cents=15000,
        is_booting_eligible=True, code="HYDRANT",
        badge_number="B-BOOT", beat_code="BEATB", plate="BOOTPLT")
    c1 = issue_in_context(ctx, evidence_photo_url="https://ev/h1.jpg")
    c2 = issue_in_context(ctx, evidence_photo_url="https://ev/h2.jpg")
    c3 = issue_in_context(ctx, evidence_photo_url="https://ev/h3.jpg")
    orders = list_boot_tow_orders(ctx["vehicle"]["id"])
    holds = list_registration_holds(ctx["vehicle"]["id"])
    ctx["citations"] = [c1, c2, c3]
    ctx["boot_order"] = orders[0] if orders else None
    ctx["hold"] = holds[0] if holds else None
    return ctx


# ─── Tier 4: contested citation + scheduled hearing ──────────────

def setup_scheduled_hearing(base_fine_cents=5000, patrol_zone="RESIDENTIAL",
                            code="EXP_METER",
                            scheduled_start="2026-03-05T09:00:00Z",
                            scheduled_end="2026-03-05T10:00:00Z") -> dict:
    """Issue a citation, contest it, and schedule a hearing for the contest.

    Returns the issuing context plus ``citation``, ``contest``, ``room``,
    and ``hearing``."""
    ctx = setup_issuing_context(patrol_zone=patrol_zone,
                                base_fine_cents=base_fine_cents, code=code)
    cit = issue_in_context(ctx)
    contest = file_contest(cit["id"], grounds="Meter was broken")
    room = create_hearing_room(room_code="HRX", name="Room X")
    hearing = schedule_hearing(contest["id"], room["id"],
                               scheduled_start, scheduled_end)
    ctx.update({"citation": cit, "contest": contest,
                "room": room, "hearing": hearing})
    return ctx
