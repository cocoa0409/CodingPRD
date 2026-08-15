"""Composite setup helpers.

Each helper builds PRD-declared state from scratch (the server restarts with an
empty database before every test) using the lenient get_success_data() validator
so setup failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_horse_payload, adopter_payload, adoption_application_payload,
    home_check_payload, sponsor_payload, sponsorship_payload, volunteer_payload,
    barn_shift_payload, practitioner_payload, create_intake_evaluation_payload,
    complete_evaluation_payload, daily_health_log_payload, stall_payload,
    stall_assignment_payload, purchase_order_payload, receipt_payload,
    rehabilitation_plan_payload, sanctuary_care_plan_payload,
    euthanasia_case_payload, appointment_payload,
)
from .test_users import (
    TEST_USERS, make_veterinarian_headers, make_farrier_headers,
    make_adopter_headers, make_sponsor_headers, make_volunteer_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
OFFICER_1 = TEST_USERS["officer_1_headers"]
OFFICER_2 = TEST_USERS["officer_2_headers"]
BARN = TEST_USERS["barn_manager_headers"]
VOL_COORD = TEST_USERS["vol_coordinator_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, DIRECTOR)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Practitioners
# ---------------------------------------------------------------------------

def register_practitioner(specialty="VETERINARIAN", name="Dr Test") -> dict:
    resp = api_client.create_practitioner(
        practitioner_payload(name=name, specialty=specialty), DIRECTOR
    )
    return get_success_data(resp)


def register_vet(name="Dr Vet") -> str:
    return register_practitioner("VETERINARIAN", name)["id"]


def register_farrier(name="Farrier Fred") -> str:
    return register_practitioner("FARRIER", name)["id"]


# ---------------------------------------------------------------------------
# Horses: intake, evaluation, quarantine clearance, release
# ---------------------------------------------------------------------------

def intake_horse(**overrides) -> dict:
    resp = api_client.create_horse(create_horse_payload(**overrides), INTAKE)
    return get_success_data(resp)


def get_horse(horse_id: str, headers=None) -> dict:
    resp = api_client.get_horse(horse_id, headers or DIRECTOR)
    return get_success_data(resp)


def complete_medical_pass(horse_id: str, at="2026-08-14T12:00:00Z",
                          outcome="PASS", by=INTAKE) -> dict:
    """Schedule + complete a MEDICAL evaluation stamped at logical `at`."""
    set_clock(at)
    ev = get_success_data(api_client.create_intake_evaluation(
        create_intake_evaluation_payload(horse_id, evaluation_type="MEDICAL",
                                         scheduled_date=at), INTAKE))
    done = api_client.complete_intake_evaluation(
        ev["id"], complete_evaluation_payload(outcome=outcome), by)
    return get_success_data(done)


def protocols_for(horse_id: str) -> list:
    data, _meta = _list_all("/rescue-ops/quarantine-protocols", INTAKE)
    return [p for p in data if p.get("horse_id") == horse_id]


def _list_all(path, headers, params=None):
    resp = api_client.get(path, headers=headers, params=params or {"limit": 100})
    body = resp.json()
    if not (200 <= resp.status_code < 300):
        raise AssertionError(f"Setup step failed with HTTP {resp.status_code}")
    return body["data"], body.get("meta", {})


def active_protocol_for(horse_id: str) -> dict:
    actives = [p for p in protocols_for(horse_id) if p["status"] == "ACTIVE"]
    assert len(actives) == 1, f"expected one ACTIVE protocol for {horse_id}"
    return actives[0]


def clear_active_protocol(horse_id: str, vet_id: str,
                          at="2026-08-15T00:00:00Z") -> dict:
    set_clock(at)
    proto = active_protocol_for(horse_id)
    resp = api_client.clear_quarantine_protocol(
        proto["id"], make_veterinarian_headers(vet_id))
    return get_success_data(resp)


def release_horse(horse_id: str, target_status: str) -> dict:
    resp = api_client.release_quarantine(
        horse_id, {"target_status": target_status}, INTAKE)
    return get_success_data(resp)


def setup_released_horse(target_status="REHABILITATION", horse_overrides=None,
                         vet_id=None, eval_at="2026-08-14T12:00:00Z",
                         clear_at="2026-08-15T00:00:00Z") -> dict:
    """Full intake-to-release chain: intake -> MEDICAL PASS -> clear -> release.

    Returns {"horse": released horse, "vet_id": veterinarian practitioner id}.
    """
    if vet_id is None:
        vet_id = register_vet()
    horse = intake_horse(**(horse_overrides or {}))
    complete_medical_pass(horse["id"], at=eval_at)
    clear_active_protocol(horse["id"], vet_id, at=clear_at)
    released = release_horse(horse["id"], target_status)
    return {"horse": released, "vet_id": vet_id}


def setup_sanctuary_horse(horse_overrides=None, vet_id=None) -> dict:
    """Horse in SANCTUARY. Returns {"horse": refreshed horse, "vet_id": ...}."""
    bundle = setup_released_horse("REHABILITATION", horse_overrides, vet_id)
    resp = api_client.designate_sanctuary(
        bundle["horse"]["id"], {"reason": "permanent resident"}, DIRECTOR)
    get_success_data(resp)
    return {"horse": get_horse(bundle["horse"]["id"]), "vet_id": bundle["vet_id"]}


def setup_adopted_horse_via_application(**kwargs):
    """Alias target for readability in tests (see setup_finalized_adoption)."""
    return setup_finalized_adoption(**kwargs)


# ---------------------------------------------------------------------------
# Rehabilitation plans and care appointments
# ---------------------------------------------------------------------------

def create_rehab_plan(horse_id: str, vet_id: str, **overrides) -> dict:
    horse = get_horse(horse_id, make_veterinarian_headers(vet_id))
    payload = rehabilitation_plan_payload(
        horse_id, horse["version"], **overrides)
    resp = api_client.create_rehabilitation_plan(
        payload, make_veterinarian_headers(vet_id))
    return get_success_data(resp)


def book_appointment(horse_id: str, practitioner_id: str, **overrides) -> dict:
    resp = api_client.create_care_service_appointment(
        appointment_payload(horse_id, practitioner_id, **overrides), INTAKE)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Adopters, applications, home checks
# ---------------------------------------------------------------------------

def register_adopter(**overrides) -> dict:
    resp = api_client.create_adopter(
        adopter_payload(**overrides), TEST_USERS["adopter_registration_headers"])
    return get_success_data(resp)


def submit_application(adopter_id: str, horse_id: str,
                       pickup="2026-08-20T00:00:00Z", pair=False) -> dict:
    payload = adoption_application_payload(
        adopter_id, horse_id, proposed_pickup_date=pickup)
    if pair:
        payload["adopt_with_bonded_companion"] = True
    resp = api_client.create_adoption_application(
        payload, make_adopter_headers(adopter_id))
    return get_success_data(resp)


def start_review(application_id: str, officer=OFFICER_1) -> dict:
    return get_success_data(api_client.start_application_review(application_id, officer))


def pass_home_check(application_id: str, officer=OFFICER_1,
                    scheduled_date="2026-08-15T10:00:00Z",
                    outcome="PASSED", findings=None) -> dict:
    """Create + complete a home check. Returns the completed HomeCheck."""
    payload = home_check_payload(application_id, scheduled_date=scheduled_date)
    hc = get_success_data(api_client.create_home_check(payload, officer))
    complete_payload = {"outcome": outcome}
    if findings is not None:
        complete_payload["findings"] = findings
    return get_success_data(
        api_client.complete_home_check(hc["id"], complete_payload, officer))


def get_application(application_id: str, headers=None) -> dict:
    resp = api_client.get_adoption_application(
        application_id, headers or OFFICER_1)
    return get_success_data(resp)


def setup_application_home_check_passed(horse_overrides=None,
                                        pickup="2026-08-20T00:00:00Z",
                                        pair=False, adopter_overrides=None,
                                        horse_bundle=None) -> dict:
    """ADOPTABLE horse + adopter + application driven to HOME_CHECK_PASSED.

    Returns dict(horse, vet_id, adopter, application, home_check).
    """
    bundle = horse_bundle or setup_released_horse("ADOPTABLE", horse_overrides)
    adopter = register_adopter(**(adopter_overrides or {}))
    app = submit_application(adopter["id"], bundle["horse"]["id"], pickup, pair)
    start_review(app["id"])
    hc = pass_home_check(app["id"])
    return {
        "horse": get_horse(bundle["horse"]["id"]),
        "vet_id": bundle["vet_id"],
        "adopter": adopter,
        "application": get_application(app["id"]),
        "home_check": hc,
    }


def approve_and_pay(bundle: dict, pay_amount=None, officer=OFFICER_2) -> dict:
    """Approve the bundle's application and pay the quoted fee in full.

    Returns the refreshed APPROVED application.
    """
    app_id = bundle["application"]["id"]
    approved = get_success_data(api_client.approve_application(app_id, officer))
    amount = approved["quoted_fee_cents"] if pay_amount is None else pay_amount
    get_success_data(api_client.pay_application_fee(
        app_id, {"amount_cents": amount},
        make_adopter_headers(bundle["adopter"]["id"])))
    return get_application(app_id)


def finalize_at(bundle: dict, when: str, officer=OFFICER_2) -> dict:
    set_clock(when)
    return get_success_data(
        api_client.finalize_application(bundle["application"]["id"], officer))


def setup_approved_application(horse_overrides=None,
                               pickup="2026-08-20T00:00:00Z", pair=False,
                               adopter_overrides=None, pay_amount=None) -> dict:
    """Full chain to APPROVED with fee paid. Returns the bundle dict."""
    bundle = setup_application_home_check_passed(
        horse_overrides=horse_overrides, pickup=pickup, pair=pair,
        adopter_overrides=adopter_overrides)
    bundle["application"] = approve_and_pay(bundle, pay_amount=pay_amount)
    return bundle


def setup_finalized_adoption(horse_overrides=None,
                             pickup="2026-08-20T00:00:00Z", pair=False,
                             finalize_instant="2026-08-18T00:00:00Z",
                             adopter_overrides=None) -> dict:
    """Full chain to FINALIZED (approve +72h). Returns the bundle dict."""
    bundle = setup_approved_application(
        horse_overrides=horse_overrides, pickup=pickup, pair=pair,
        adopter_overrides=adopter_overrides)
    bundle["application"] = finalize_at(bundle, finalize_instant)
    bundle["horse"] = get_horse(bundle["horse"]["id"])
    return bundle


def follow_up_visits_for(application_id: str) -> list:
    data, _meta = _list_all("/rescue-ops/follow-up-visits", OFFICER_1)
    return [v for v in data if v.get("application_id") == application_id]


# ---------------------------------------------------------------------------
# Sponsors and sponsorships
# ---------------------------------------------------------------------------

def register_sponsor(**overrides) -> dict:
    resp = api_client.create_sponsor(
        sponsor_payload(**overrides), TEST_USERS["sponsor_registration_headers"])
    return get_success_data(resp)


def create_sponsorship(sponsor_id: str, horse_id: str, pledge: int,
                       activate=False) -> dict:
    resp = api_client.create_sponsorship(
        sponsorship_payload(sponsor_id, horse_id, monthly_pledge_cents=pledge),
        make_sponsor_headers(sponsor_id))
    sponsorship = get_success_data(resp)
    if activate:
        sponsorship = get_success_data(api_client.activate_sponsorship(
            sponsorship["id"], make_sponsor_headers(sponsor_id)))
    return sponsorship


def get_sponsor(sponsor_id: str) -> dict:
    return get_success_data(api_client.get_sponsor(sponsor_id, DIRECTOR))


def get_sponsorship(sponsorship_id: str) -> dict:
    return get_success_data(api_client.get_sponsorship(sponsorship_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Sanctuary care plans
# ---------------------------------------------------------------------------

def create_care_plan(horse_id: str, variant="STRAIGHT_LINE") -> dict:
    horse = get_horse(horse_id)
    resp = api_client.create_sanctuary_care_plan(
        sanctuary_care_plan_payload(horse_id, horse["version"], variant=variant),
        DIRECTOR)
    return get_success_data(resp)


def get_care_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_sanctuary_care_plan(plan_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Stalls
# ---------------------------------------------------------------------------

def create_stall(stall_code="S-01", barn_zone="MAIN_BARN", **overrides) -> dict:
    resp = api_client.create_stall(
        stall_payload(stall_code=stall_code, barn_zone=barn_zone, **overrides),
        DIRECTOR)
    return get_success_data(resp)


def assign_stall(horse_id: str, stall_id: str, start_date, end_date=None) -> dict:
    payload = stall_assignment_payload(horse_id, stall_id, start_date=start_date)
    if end_date is not None:
        payload["end_date"] = end_date
    resp = api_client.create_stall_assignment(payload, INTAKE)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Feed: purchase orders and receipts
# ---------------------------------------------------------------------------

def create_ordered_purchase_order(feed_type="GRASS_HAY", quantity_lbs=100,
                                  unit_cents_per_lb=10) -> dict:
    resp = api_client.create_purchase_order(
        purchase_order_payload(feed_type=feed_type, quantity_lbs=quantity_lbs,
                               unit_cents_per_lb=unit_cents_per_lb), BARN)
    po = get_success_data(resp)
    return get_success_data(api_client.mark_purchase_order_ordered(po["id"], BARN))


def receive_order(order_id: str, quantity_received_lbs, expiry_date) -> dict:
    resp = api_client.receive_purchase_order(
        order_id, receipt_payload(quantity_received_lbs=quantity_received_lbs,
                                  expiry_date=expiry_date), BARN)
    return get_success_data(resp)


def create_received_order(feed_type="GRASS_HAY", quantity_lbs=100,
                          unit_cents_per_lb=10,
                          receipts=None) -> dict:
    """ORDERED order plus receipt lots. receipts: list of (lbs, expiry) tuples;
    defaults to a single full receipt expiring 2026-12-01."""
    po = create_ordered_purchase_order(feed_type, quantity_lbs, unit_cents_per_lb)
    for lbs, expiry in (receipts or [(quantity_lbs, "2026-12-01T00:00:00Z")]):
        po = receive_order(po["id"], lbs, expiry)
    return po


def list_feed_lots() -> list:
    data, _meta = _list_all("/rescue-ops/feed-lots", BARN)
    return data


def list_day_closes(feed_type=None) -> list:
    data, _meta = _list_all("/rescue-ops/feed-day-closes", BARN)
    if feed_type is None:
        return data
    return [r for r in data if r.get("feed_type") == feed_type]


def feed_summary_entry(feed_type: str) -> dict:
    data = get_success_data(api_client.get_feed_inventory_summary(BARN))
    entries = [e for e in data["summaries"] if e.get("feed_type") == feed_type]
    assert len(entries) == 1, f"expected one summary entry for {feed_type}"
    return entries[0]


# ---------------------------------------------------------------------------
# Volunteers and barn shifts
# ---------------------------------------------------------------------------

def register_volunteer(**overrides) -> dict:
    resp = api_client.create_volunteer(
        volunteer_payload(**overrides),
        TEST_USERS["volunteer_registration_headers"])
    return get_success_data(resp)


def create_shift(**overrides) -> dict:
    resp = api_client.create_barn_shift(barn_shift_payload(**overrides), VOL_COORD)
    return get_success_data(resp)


def claim_shift(shift_id: str, volunteer_id: str) -> dict:
    resp = api_client.claim_barn_shift(
        shift_id, make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


def get_volunteer(volunteer_id: str) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, VOL_COORD))


# ---------------------------------------------------------------------------
# Euthanasia cases
# ---------------------------------------------------------------------------

def propose_case(horse_id: str, vet_id: str, suffering_score=5,
                 clinical_summary="chronic unresolvable pain") -> dict:
    resp = api_client.create_euthanasia_case(
        euthanasia_case_payload(horse_id, suffering_score=suffering_score,
                                clinical_summary=clinical_summary),
        make_veterinarian_headers(vet_id))
    return get_success_data(resp)


def certify_case(case_id: str, vet_id: str, decision="CONCUR",
                 emergency_attestation=False) -> dict:
    resp = api_client.certify_euthanasia_case(
        case_id, {"decision": decision,
                  "emergency_attestation": emergency_attestation},
        make_veterinarian_headers(vet_id))
    return get_success_data(resp)


def authorize_case(case_id: str) -> dict:
    return get_success_data(api_client.authorize_euthanasia_case(case_id, DIRECTOR))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_euthanasia_case(case_id, DIRECTOR))
