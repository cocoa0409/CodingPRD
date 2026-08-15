"""Composite setup helpers.

Multi-step API sequences that bring the system into the states the test
suite needs: a community with policy, the buyer/rep registries, homes under
care, orientation appointments walked through their lifecycle (confirm ->
start -> checklist -> attendee verification -> complete), deficiency items
in various pipeline stages, escrow holdbacks through closing and release,
and the acknowledgment signature cycle.

Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors rather than assertion noise.
"""
import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appointment_payload,
    create_attendee_payload,
    create_community_payload,
    create_deficiency_item_payload,
    create_home_payload,
    create_homebuyer_payload,
    create_reinspection_visit_payload,
    create_rep_payload,
    decide_deficiency_item_payload,
    classify_deficiency_item_payload,
    respond_signature_payload,
)
from .test_users import TEST_USERS, make_buyer_headers, make_manager_headers, make_rep_headers

MANAGER = TEST_USERS["manager_headers"]

# The fixed six-entry demonstration checklist (PRD §3.3): five required
# systems plus the optional APPLIANCES entry.
REQUIRED_CHECKLIST_KEYS = ["HVAC", "PLUMBING", "ELECTRICAL", "EXTERIOR", "SAFETY"]
ALL_CHECKLIST_KEYS = REQUIRED_CHECKLIST_KEYS + ["APPLIANCES"]


def _uniq(prefix: str) -> str:
    return f"{prefix}-{_uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 2: registries and community
# ---------------------------------------------------------------------------

def setup_community(**overrides):
    """Create a community. Returns the community record."""
    resp = api_client.create_community(create_community_payload(**overrides), MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create community): {resp.text}"
    return data


def setup_buyer(**overrides):
    """Register a homebuyer with a unique email. Returns the buyer record."""
    overrides.setdefault("email", f"{_uniq('buyer')}@example.com")
    resp = api_client.create_homebuyer(create_homebuyer_payload(**overrides), MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create buyer): {resp.text}"
    return data


def setup_rep(**overrides):
    """Register a customer care rep with a unique email. Returns the rep."""
    overrides.setdefault("email", f"{_uniq('rep')}@example.com")
    resp = api_client.create_rep(create_rep_payload(**overrides), MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create rep): {resp.text}"
    return data


def setup_base(community_overrides=None, buyer_overrides=None, rep_overrides=None):
    """Community + buyer + rep. Returns (community, buyer, rep)."""
    community = setup_community(**(community_overrides or {}))
    buyer = setup_buyer(**(buyer_overrides or {}))
    rep = setup_rep(**(rep_overrides or {}))
    return community, buyer, rep


# ---------------------------------------------------------------------------
# Tier 1/2: homes and appointments
# ---------------------------------------------------------------------------

def setup_home(community_id, buyer_id, mark_ready=True, **overrides):
    """Create a home (UNDER_CONSTRUCTION); optionally mark it PRE_CLOSE_READY."""
    payload = create_home_payload(
        community_id=community_id, primary_buyer_id=buyer_id, **overrides
    )
    resp = api_client.create_home(payload, MANAGER)
    home = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create home): {resp.text}"
    if mark_ready:
        resp = api_client.mark_home_ready(home["id"], MANAGER)
        home = get_success_data(resp)
        assert resp.status_code == 200, f"Setup failed (mark-ready): {resp.text}"
    return home


def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    assert resp.status_code == 200, f"Setup failed (set clock): {resp.text}"
    return get_success_data(resp)


def create_appointment(home_id, rep_id, scheduled_start, duration_minutes=None):
    """Create an orientation appointment as the conducting rep."""
    payload = create_appointment_payload(
        home_id=home_id, rep_id=rep_id, scheduled_start=scheduled_start
    )
    if duration_minutes is not None:
        payload["duration_minutes"] = duration_minutes
    resp = api_client.create_appointment(payload, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create appointment): {resp.text}"
    return data


def confirm_appointment(appointment_id):
    resp = api_client.confirm_appointment(appointment_id, MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (confirm): {resp.text}"
    return data


def start_appointment(appointment_id, rep_id):
    resp = api_client.start_appointment(appointment_id, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (start): {resp.text}"
    return data


def mark_checklist(appointment_id, rep_id, outcomes=None):
    """Mark every checklist entry. `outcomes` maps system_key -> outcome;
    defaults to DEMONSTRATED for required entries and SKIPPED for APPLIANCES."""
    outcomes = outcomes or {}
    for key in ALL_CHECKLIST_KEYS:
        outcome = outcomes.get(key, "SKIPPED" if key == "APPLIANCES" else "DEMONSTRATED")
        resp = api_client.mark_checklist_item(
            appointment_id, key, {"outcome": outcome}, make_rep_headers(rep_id)
        )
        assert resp.status_code == 200, (
            f"Setup failed (mark {key} -> {outcome}): {resp.text}"
        )


def add_verified_buyer_attendee(appointment_id, buyer_id, acting_rep_id=None,
                                attendee_type="BUYER"):
    """Record a BUYER/CO_BUYER attendee for the buyer and verify it.

    Verification is performed by the manager (segregation-exempt), so this
    helper is safe regardless of which rep conducts the appointment.
    """
    payload = create_attendee_payload(
        appointment_id=appointment_id, attendee_type=attendee_type, buyer_id=buyer_id
    )
    headers = make_rep_headers(acting_rep_id) if acting_rep_id else MANAGER
    resp = api_client.create_attendee(payload, headers)
    attendee = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create attendee): {resp.text}"
    resp = api_client.decide_attendee_verification(
        attendee["id"], {"decision": "VERIFIED"}, MANAGER
    )
    attendee = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (verify attendee): {resp.text}"
    return attendee


def complete_appointment(appointment_id, rep_id):
    resp = api_client.complete_appointment(appointment_id, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (complete): {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 3: full orientation lifecycle
# ---------------------------------------------------------------------------

def setup_orientation_in_progress(home_id, rep_id, scheduled_start, buyer_id=None):
    """Appointment confirmed and started (clock moved to scheduled_start).
    Returns the IN_PROGRESS appointment."""
    appt = create_appointment(home_id, rep_id, scheduled_start)
    confirm_appointment(appt["id"])
    set_clock(scheduled_start)
    return start_appointment(appt["id"], rep_id)


def setup_completed_orientation(home_id, rep_id, buyer_id, scheduled_start,
                                verify_attendee=True):
    """Walk an appointment through to COMPLETED: create -> confirm ->
    (clock to start) -> start -> verified buyer attendee -> full checklist ->
    complete. Returns the COMPLETED appointment."""
    appt = create_appointment(home_id, rep_id, scheduled_start)
    confirm_appointment(appt["id"])
    set_clock(scheduled_start)
    start_appointment(appt["id"], rep_id)
    if verify_attendee:
        add_verified_buyer_attendee(appt["id"], buyer_id, acting_rep_id=rep_id)
    mark_checklist(appt["id"], rep_id)
    return complete_appointment(appt["id"], rep_id)


def get_signature_for_home(home_id):
    """Fetch the home's acknowledgment signature record."""
    resp = api_client.list_acknowledgment_signatures(MANAGER, params={"home_id": home_id})
    data, meta = _unwrap_list(resp)
    assert len(data) >= 1, f"Setup failed: no signature for home {home_id}"
    return data[0]


def get_survey_for_home(home_id, status=None):
    """Fetch the home's feedback survey (optionally filtered by status)."""
    params = {"home_id": home_id}
    if status:
        params["status"] = status
    resp = api_client.list_feedback_surveys(MANAGER, params=params)
    data, meta = _unwrap_list(resp)
    assert len(data) >= 1, f"Setup failed: no survey for home {home_id}"
    return data[0]


def get_escrow_for_home(home_id):
    """Fetch the home's first listed escrow holdback."""
    resp = api_client.list_escrow_holdbacks(MANAGER, params={"home_id": home_id})
    data, meta = _unwrap_list(resp)
    assert len(data) >= 1, f"Setup failed: no escrow for home {home_id}"
    return data[0]


def _unwrap_list(resp):
    assert resp.status_code == 200, f"Setup failed (list): {resp.text}"
    body = resp.json()
    return body["data"], body.get("meta", {})


def sign_acknowledgment(home_id, buyer_id):
    """Respond SIGN on the home's acknowledgment signature as the buyer."""
    sig = get_signature_for_home(home_id)
    resp = api_client.respond_acknowledgment_signature(
        sig["id"], respond_signature_payload(), make_buyer_headers(buyer_id)
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (sign acknowledgment): {resp.text}"
    return data


def setup_signed_home(community_overrides=None, closing_date="2026-09-20T17:00:00Z",
                      orientation_start="2026-08-25T14:00:00Z"):
    """Full pipeline to a signed home: community + buyer + rep + home ->
    orientation completed -> acknowledgment signed. With no open
    before-closing items the home lands READY_TO_CLOSE.
    Returns dict(home, buyer, rep, appointment, signature)."""
    community, buyer, rep = setup_base(community_overrides=community_overrides)
    home = setup_home(community["id"], buyer["id"], closing_date=closing_date)
    appt = setup_completed_orientation(
        home["id"], rep["id"], buyer["id"], orientation_start
    )
    signature = sign_acknowledgment(home["id"], buyer["id"])
    home = get_success_data(api_client.get_home(home["id"], MANAGER))
    return {
        "community": community,
        "buyer": buyer,
        "rep": rep,
        "home": home,
        "appointment": appt,
        "signature": signature,
    }


# ---------------------------------------------------------------------------
# Tier 3/4: deficiency pipeline stages
# ---------------------------------------------------------------------------

def create_deficiency(home_id, appointment_id, rep_id, **overrides):
    payload = create_deficiency_item_payload(
        home_id=home_id, appointment_id=appointment_id, **overrides
    )
    resp = api_client.create_deficiency_item(payload, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (identify deficiency): {resp.text}"
    return data


def classify_deficiency(item_id, rep_id, classification="WARRANTABLE",
                        estimated_repair_cost_cents=20_000, **overrides):
    payload = classify_deficiency_item_payload(
        classification=classification,
        estimated_repair_cost_cents=estimated_repair_cost_cents,
        **overrides,
    )
    resp = api_client.classify_deficiency_item(item_id, payload, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (classify): {resp.text}"
    return data


def decide_deficiency(item_id, resolution):
    resp = api_client.decide_deficiency_item(
        item_id, decide_deficiency_item_payload(resolution=resolution), MANAGER
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (decide): {resp.text}"
    return data


def move_item_to_ready_for_reinspection(item_id, rep_id):
    """DECIDED -> IN_REPAIR -> READY_FOR_REINSPECTION."""
    resp = api_client.start_repair(item_id, make_rep_headers(rep_id))
    assert resp.status_code == 200, f"Setup failed (start-repair): {resp.text}"
    resp = api_client.complete_repair(item_id, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (complete-repair): {resp.text}"
    return data


def complete_repair(item_id, headers):
    """Mark repair complete with explicit caller headers (IN_REPAIR ->
    READY_FOR_REINSPECTION) — for loop re-entry after a FAIL."""
    resp = api_client.complete_repair(item_id, headers)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (complete-repair): {resp.text}"
    return data


def schedule_visit(home_id, rep_id, scheduled_start, duration_minutes=60):
    payload = create_reinspection_visit_payload(
        home_id=home_id, rep_id=rep_id, scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    resp = api_client.create_reinspection_visit(payload, make_rep_headers(rep_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create visit): {resp.text}"
    return data


def complete_visit(visit_id, rep_id, results, clock_at=None):
    """Complete a reinspection visit; optionally moves the clock to the
    visit's scheduled start first (pass clock_at=scheduled_start)."""
    if clock_at is not None:
        set_clock(clock_at)
    resp = api_client.complete_reinspection_visit(
        visit_id, {"results": results}, make_rep_headers(rep_id)
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (complete visit): {resp.text}"
    return data


def reinspect_item(item_id, home_id, rep_id, scheduled_start, outcome):
    """Schedule + complete a reinspection visit for one READY_FOR_REINSPECTION
    item with the given PASS/FAIL outcome. Returns the completed visit."""
    visit = schedule_visit(home_id, rep_id, scheduled_start)
    return complete_visit(
        visit["id"], rep_id,
        [{"deficiency_item_id": item_id, "outcome": outcome}],
        clock_at=scheduled_start,
    )


def verify_item_via_reinspection(item_id, home_id, rep_id, scheduled_start):
    """Drive an item READY_FOR_REINSPECTION -> VERIFIED via a PASS visit."""
    return reinspect_item(item_id, home_id, rep_id, scheduled_start, "PASS")


def sign_off_item(item_id, buyer_id):
    resp = api_client.sign_off_deficiency_item(item_id, make_buyer_headers(buyer_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (sign-off): {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 5: closing and escrow release
# ---------------------------------------------------------------------------

def close_home(home_id, funded_holdback_cents=None):
    payload = {}
    if funded_holdback_cents is not None:
        payload["funded_holdback_cents"] = funded_holdback_cents
    resp = api_client.close_home(home_id, payload, MANAGER)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (close home): {resp.text}"
    return data


def release_escrow(escrow_id, expected_escrow_version):
    resp = api_client.release_escrow_holdback(
        escrow_id, {"expected_escrow_version": expected_escrow_version}, MANAGER
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (release escrow): {resp.text}"
    return data


def setup_closed_home_with_escrow(community_overrides=None,
                                  closing_date="2026-09-01T17:00:00Z",
                                  orientation_start="2026-08-25T14:00:00Z"):
    """Full pipeline to a CLOSED home whose escrow carries one
    COMPLETE_AFTER_CLOSING WARRANTABLE 20000-cent item, still open.
    Community default: multiplier 2.0 / min 1000 / max 10000000 so the
    contribution is exactly 40000 with no clamp interference.
    Returns dict(home, buyer, rep, appointment, item, escrow, signature)."""
    overrides = {
        "holdback_cost_multiplier": 2.0,
        "holdback_min_cents": 1_000,
        "holdback_max_cents": 10_000_000,
    }
    overrides.update(community_overrides or {})
    community, buyer, rep = setup_base(community_overrides=overrides)
    home = setup_home(community["id"], buyer["id"], closing_date=closing_date)

    appt = create_appointment(home["id"], rep["id"], orientation_start)
    confirm_appointment(appt["id"])
    set_clock(orientation_start)
    start_appointment(appt["id"], rep["id"])

    item = create_deficiency(home["id"], appt["id"], rep["id"],
                             title="Furnace ignition fault")
    classify_deficiency(item["id"], rep["id"], estimated_repair_cost_cents=20_000)
    item = decide_deficiency(item["id"], "COMPLETE_AFTER_CLOSING")

    add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
    mark_checklist(appt["id"], rep["id"])
    appt = complete_appointment(appt["id"], rep["id"])

    signature = sign_acknowledgment(home["id"], buyer["id"])
    close_home(home["id"], funded_holdback_cents=40_000)

    home = get_success_data(api_client.get_home(home["id"], MANAGER))
    escrow = get_escrow_for_home(home["id"])
    return {
        "community": community,
        "buyer": buyer,
        "rep": rep,
        "home": home,
        "appointment": appt,
        "item": item,
        "escrow": escrow,
        "signature": signature,
    }
