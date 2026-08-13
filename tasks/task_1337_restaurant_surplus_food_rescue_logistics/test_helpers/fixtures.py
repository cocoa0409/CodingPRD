"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, threads entity-backed identities through
the make_*_headers builders, and validates setup calls with the lenient
get_success_data() so failures surface as clear "Setup failed" errors.

Conventional scenario defaults (override via kwargs):
  pickup window   2026-08-02T10:00:00Z .. 2026-08-02T12:00:00Z
  driver window   2026-08-02T09:00:00Z .. 2026-08-02T15:00:00Z
  dispatch clock  2026-08-02T09:30:00Z
  pickup event    2026-08-02T10:15:00Z
  delivery event  2026-08-02T13:15:00Z
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_donor_site_payload,
    create_recipient_agency_payload,
    create_volunteer_driver_payload,
    create_availability_window_payload,
    create_cooler_payload,
    create_donation_offer_payload,
    create_rate_card_payload,
)
from .test_users import (
    TEST_USERS,
    make_donor_coordinator_headers,
    make_volunteer_driver_headers,
    make_agency_coordinator_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.text}"
    return get_success_data(resp)


def create_donor(legal_name="Test Bistro", ein="123456789",
                 contact_email="ops@bistro.example",
                 enhanced_deduction_eligible=None, activate=True) -> dict:
    payload = create_donor_site_payload(
        legal_name=legal_name, ein=ein, contact_email=contact_email)
    if enhanced_deduction_eligible is not None:
        payload["enhanced_deduction_eligible"] = enhanced_deduction_eligible
    resp = api_client.create_donor_site(payload, ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_donor -> {resp.text}"
    donor = get_success_data(resp)
    if activate:
        resp = api_client.patch_donor_site_status(donor["id"], "ACTIVE", ADMIN)
        assert resp.status_code == 200, f"Setup failed: activate donor -> {resp.text}"
        donor = get_success_data(resp)
    return donor


def create_agency(name="AG", accepts_categories=("COLD_HELD",),
                  capacity_cold_held_lbs=100, capacity_hot_held_lbs=0,
                  capacity_produce_lbs=0, capacity_shelf_stable_lbs=0) -> dict:
    payload = create_recipient_agency_payload(
        name=name,
        accepts_categories=list(accepts_categories),
        capacity_cold_held_lbs=capacity_cold_held_lbs,
        capacity_hot_held_lbs=capacity_hot_held_lbs,
        capacity_produce_lbs=capacity_produce_lbs,
        capacity_shelf_stable_lbs=capacity_shelf_stable_lbs,
    )
    resp = api_client.create_recipient_agency(payload, ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_agency -> {resp.text}"
    return get_success_data(resp)


def create_driver(full_name="V One", email="v1@example.com",
                  vehicle_capacity_lbs=500, cooler_slot_count=2,
                  cold_chain_certified=None, activate=True) -> dict:
    payload = create_volunteer_driver_payload(
        full_name=full_name, email=email,
        vehicle_capacity_lbs=vehicle_capacity_lbs,
        cooler_slot_count=cooler_slot_count)
    if cold_chain_certified is not None:
        payload["cold_chain_certified"] = cold_chain_certified
    resp = api_client.create_volunteer_driver(payload, ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_driver -> {resp.text}"
    driver = get_success_data(resp)
    if activate:
        resp = api_client.patch_volunteer_driver_status(driver["id"], "ACTIVE", ADMIN)
        assert resp.status_code == 200, f"Setup failed: activate driver -> {resp.text}"
        driver = get_success_data(resp)
    return driver


def add_window(driver_id: str, window_start="2026-08-02T09:00:00Z",
               window_end="2026-08-02T15:00:00Z") -> dict:
    payload = create_availability_window_payload(
        window_start=window_start, window_end=window_end)
    resp = api_client.create_availability_window(
        driver_id, payload, make_volunteer_driver_headers(driver_id))
    assert resp.status_code == 201, f"Setup failed: add_window -> {resp.text}"
    return get_success_data(resp)


def create_cooler(label="C1", capacity_liters=30) -> dict:
    resp = api_client.create_cooler(
        create_cooler_payload(label=label, capacity_liters=capacity_liters), ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_cooler -> {resp.text}"
    return get_success_data(resp)


def create_offer(donor_id: str, food_category="COLD_HELD", estimated_weight_lbs=50,
                 pickup_window_start="2026-08-02T10:00:00Z",
                 pickup_window_end="2026-08-02T12:00:00Z", publish=False) -> dict:
    payload = create_donation_offer_payload(
        donor_site_id=donor_id, food_category=food_category,
        estimated_weight_lbs=estimated_weight_lbs,
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end)
    resp = api_client.create_donation_offer(
        payload, make_donor_coordinator_headers(donor_id))
    assert resp.status_code == 201, f"Setup failed: create_offer -> {resp.text}"
    offer = get_success_data(resp)
    if publish:
        offer = publish_offer(offer["id"], donor_id)
    return offer


def publish_offer(offer_id: str, donor_id: str) -> dict:
    resp = api_client.patch_donation_offer_status(
        offer_id, "OPEN", make_donor_coordinator_headers(donor_id))
    assert resp.status_code == 200, f"Setup failed: publish_offer -> {resp.text}"
    return get_success_data(resp)


def get_offer_version(offer_id: str) -> int:
    resp = api_client.get_donation_offer(offer_id, ADMIN)
    assert resp.status_code == 200, f"Setup failed: get offer -> {resp.text}"
    return get_success_data(resp)["version"]


def get_donor_version(donor_id: str) -> int:
    resp = api_client.get_donor_site(donor_id, ADMIN)
    assert resp.status_code == 200, f"Setup failed: get donor -> {resp.text}"
    return get_success_data(resp)["version"]


def create_rate_card(**overrides) -> dict:
    resp = api_client.create_rate_card(create_rate_card_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_rate_card -> {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: run lifecycle progression
# ---------------------------------------------------------------------------

def dispatch_run(offer_id: str, driver_id=None, agency_id=None, cooler_ids=None) -> dict:
    """Dispatch against an OPEN offer, reading the fresh OCC version first."""
    payload = {"offer_id": offer_id,
               "expected_offer_version": get_offer_version(offer_id)}
    if driver_id is not None:
        payload["driver_id"] = driver_id
    if agency_id is not None:
        payload["agency_id"] = agency_id
    if cooler_ids is not None:
        payload["cooler_ids"] = list(cooler_ids)
    resp = api_client.create_rescue_run(payload, ADMIN)
    assert resp.status_code == 201, f"Setup failed: dispatch_run -> {resp.text}"
    return get_success_data(resp)


def respond_run(run_id: str, driver_id: str, decision="ACCEPT") -> dict:
    resp = api_client.respond_rescue_run(
        run_id, decision, make_volunteer_driver_headers(driver_id))
    assert resp.status_code == 200, f"Setup failed: respond {decision} -> {resp.text}"
    return get_success_data(resp)


def record_pickup(run_id: str, driver_id: str,
                  pickup_time="2026-08-02T10:15:00Z", pickup_temp_f=None,
                  set_clock_to=None) -> dict:
    """Record pickup. Sets the logical clock to the pickup instant first
    (pickup_time must not lie after the current logical clock, PRD §3.4)."""
    set_clock(set_clock_to or pickup_time)
    payload = {"pickup_time": pickup_time, "attestation_confirmed": True}
    if pickup_temp_f is not None:
        payload["pickup_temp_f"] = pickup_temp_f
    resp = api_client.record_pickup(
        run_id, payload, make_volunteer_driver_headers(driver_id))
    assert resp.status_code == 200, f"Setup failed: record_pickup -> {resp.text}"
    return get_success_data(resp)


def record_delivery(run_id: str, driver_id: str,
                    arrival_time="2026-08-02T13:15:00Z", actual_weight_lbs=50,
                    arrival_temp_f=None, set_clock_to=None) -> dict:
    set_clock(set_clock_to or arrival_time)
    payload = {"arrival_time": arrival_time, "actual_weight_lbs": actual_weight_lbs}
    if arrival_temp_f is not None:
        payload["arrival_temp_f"] = arrival_temp_f
    resp = api_client.record_delivery(
        run_id, payload, make_volunteer_driver_headers(driver_id))
    assert resp.status_code == 200, f"Setup failed: record_delivery -> {resp.text}"
    return get_success_data(resp)


def verify_run(run_id: str, agency_id: str, set_clock_to=None) -> dict:
    if set_clock_to is not None:
        set_clock(set_clock_to)
    resp = api_client.verify_delivery(
        run_id, make_agency_coordinator_headers(agency_id))
    assert resp.status_code == 200, f"Setup failed: verify_delivery -> {resp.text}"
    return get_success_data(resp)


def fail_run(run_id: str, fault_party: str, reason: str,
             as_driver_id: str = None, as_admin_id: str = "admin-1",
             disposal_method=None, disposal_notes=None) -> dict:
    payload = {"fault_party": fault_party, "reason": reason}
    if disposal_method is not None:
        payload["disposal_method"] = disposal_method
    if disposal_notes is not None:
        payload["disposal_notes"] = disposal_notes
    if as_driver_id is not None:
        headers = make_volunteer_driver_headers(as_driver_id)
    else:
        from .test_users import make_dispatch_admin_headers
        headers = make_dispatch_admin_headers(as_admin_id)
    resp = api_client.fail_rescue_run(run_id, payload, headers)
    assert resp.status_code == 200, f"Setup failed: fail_run -> {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: full-lifecycle composites
# ---------------------------------------------------------------------------

def setup_confirmed_run(donor=None, agency=None, driver=None, cooler=None,
                        food_category="COLD_HELD", estimated_weight_lbs=50,
                        pickup_window_start="2026-08-02T10:00:00Z",
                        pickup_window_end="2026-08-02T12:00:00Z",
                        driver_window=("2026-08-02T09:00:00Z", "2026-08-02T15:00:00Z"),
                        dispatch_clock="2026-08-02T09:30:00Z",
                        agency_capacity_lbs=100) -> dict:
    """Donor + agency + driver(window) + optional cooler + OPEN offer, then a
    dispatched and ACCEPTed run. Returns the whole scenario context."""
    cold_chain = food_category in ("COLD_HELD", "HOT_HELD")
    donor = donor or create_donor()
    agency = agency or create_agency(
        accepts_categories=(food_category,),
        capacity_cold_held_lbs=agency_capacity_lbs if food_category == "COLD_HELD" else 0,
        capacity_hot_held_lbs=agency_capacity_lbs if food_category == "HOT_HELD" else 0,
        capacity_produce_lbs=agency_capacity_lbs if food_category == "PRODUCE" else 0,
        capacity_shelf_stable_lbs=agency_capacity_lbs if food_category == "SHELF_STABLE" else 0,
    )
    driver = driver or create_driver(
        cold_chain_certified=True if cold_chain else None,
        cooler_slot_count=2 if cold_chain else 0)
    window = add_window(driver["id"], driver_window[0], driver_window[1])
    if cold_chain:
        # Size the default cooler to fit the offer: PRD §3.3 requires
        # ceil(estimated_weight_lbs * 0.5) liters of cooler capacity.
        required_liters = (estimated_weight_lbs + 1) // 2
        cooler = cooler or create_cooler(capacity_liters=max(30, required_liters))
    offer = create_offer(donor["id"], food_category=food_category,
                         estimated_weight_lbs=estimated_weight_lbs,
                         pickup_window_start=pickup_window_start,
                         pickup_window_end=pickup_window_end, publish=True)
    set_clock(dispatch_clock)
    run = dispatch_run(offer["id"], driver_id=driver["id"], agency_id=agency["id"],
                       cooler_ids=[cooler["id"]] if cold_chain else None)
    run = respond_run(run["id"], driver["id"], "ACCEPT")
    return {"donor": donor, "agency": agency, "driver": driver, "window": window,
            "cooler": cooler, "offer": offer, "run": run}


def setup_picked_up_run(pickup_time="2026-08-02T10:15:00Z", pickup_temp_f=35.0,
                        **kwargs) -> dict:
    """A run walked to PICKED_UP (CONFIRMED -> record-pickup)."""
    ctx = setup_confirmed_run(**kwargs)
    ctx["run"] = record_pickup(
        ctx["run"]["id"], ctx["driver"]["id"],
        pickup_time=pickup_time,
        pickup_temp_f=pickup_temp_f if ctx["offer"]["requires_cold_chain"] else None)
    return ctx


def setup_delivered_run(arrival_time="2026-08-02T13:15:00Z", actual_weight_lbs=None,
                        arrival_temp_f=39.0, **kwargs) -> dict:
    """A run walked to DELIVERED."""
    ctx = setup_picked_up_run(**kwargs)
    actual = actual_weight_lbs if actual_weight_lbs is not None \
        else ctx["offer"]["estimated_weight_lbs"]
    ctx["run"] = record_delivery(
        ctx["run"]["id"], ctx["driver"]["id"],
        arrival_time=arrival_time, actual_weight_lbs=actual,
        arrival_temp_f=arrival_temp_f if ctx["offer"]["requires_cold_chain"] else None)
    return ctx


def setup_verified_run(verify_clock=None, **kwargs) -> dict:
    """A run walked all the way to VERIFIED (offer CLOSED)."""
    ctx = setup_delivered_run(**kwargs)
    ctx["run"] = verify_run(ctx["run"]["id"], ctx["agency"]["id"],
                            set_clock_to=verify_clock)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b: specialized composites
# ---------------------------------------------------------------------------

def issue_receipt(donor_id: str, period_start="2026-08-01T00:00:00Z",
                  period_end="2026-09-01T00:00:00Z"):
    """Issue a tax receipt, reading the fresh donor OCC version first.
    Returns the raw response so callers can validate success or error.

    PRD §3.8 pins `period_end` to not lie after the current logical clock, so
    advance the clock to `period_end` before issuing if it is still earlier —
    otherwise the request would be rejected with `ERR_INVALID_REQUEST` before
    any of the receipt-specific gates can fire.
    """
    set_clock(period_end)
    payload = {"period_start": period_start, "period_end": period_end,
               "expected_donor_version": get_donor_version(donor_id)}
    return api_client.issue_tax_receipt(donor_id, payload, ADMIN)


def setup_two_donors_with_identical_verified_rescues() -> dict:
    """Two ACTIVE donors differing ONLY in enhanced_deduction_eligible, each
    with a byte-identical VERIFIED 50-lb COLD_HELD rescue (PRD §3.8)."""
    create_rate_card()
    d_std = create_donor(legal_name="Std Bistro", ein="111111111",
                         contact_email="s@bistro.example",
                         enhanced_deduction_eligible=False)
    d_enh = create_donor(legal_name="Enh Bistro", ein="222222222",
                         contact_email="e@bistro.example",
                         enhanced_deduction_eligible=True)
    agency = create_agency(
        name="AG",
        accepts_categories=("COLD_HELD", "HOT_HELD", "PRODUCE", "SHELF_STABLE"),
        capacity_cold_held_lbs=100, capacity_hot_held_lbs=50,
        capacity_produce_lbs=200, capacity_shelf_stable_lbs=100)
    v1 = create_driver(full_name="V One", email="v1@example.com",
                       cold_chain_certified=True)
    add_window(v1["id"])
    v2 = create_driver(full_name="V Two", email="v2@example.com",
                       cold_chain_certified=True)
    add_window(v2["id"])
    c1 = create_cooler(label="C1")
    c2 = create_cooler(label="C2")

    def _rescue(donor, driver, cooler):
        # Reset the clock before publish so the offer's pickup_window_end
        # still lies in the future (PRD §3.2 ERR_PICKUP_WINDOW_PAST guard).
        set_clock("2026-08-02T09:30:00Z")
        offer = create_offer(donor["id"], publish=True)
        run = dispatch_run(offer["id"], driver_id=driver["id"],
                           agency_id=agency["id"], cooler_ids=[cooler["id"]])
        run = respond_run(run["id"], driver["id"], "ACCEPT")
        run = record_pickup(run["id"], driver["id"], pickup_temp_f=35.0)
        run = record_delivery(run["id"], driver["id"], actual_weight_lbs=50,
                              arrival_temp_f=39.0)
        return verify_run(run["id"], agency["id"])

    r_std = _rescue(d_std, v1, c1)
    r_enh = _rescue(d_enh, v2, c2)
    return {"donor_std": d_std, "donor_enh": d_enh, "agency": agency,
            "run_std": r_std, "run_enh": r_enh}


def setup_driver_suspension_cascade_scenario() -> dict:
    """One ACTIVE driver holding two CONFIRMED runs (R0, R1) and one PROPOSED
    run (R2) across three adjacent windows, ready for the UPHELD-strike
    suspension cascade of PRD §3.6."""
    donor = create_donor(legal_name="Casc Bistro", ein="888888888",
                         contact_email="k@bistro.example")
    agency = create_agency()
    v1 = create_driver(cold_chain_certified=True)
    add_window(v1["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
    add_window(v1["id"], "2026-08-02T12:00:00Z", "2026-08-02T14:00:00Z")
    add_window(v1["id"], "2026-08-02T14:00:00Z", "2026-08-02T16:00:00Z")
    c1 = create_cooler(label="C1")
    c2 = create_cooler(label="C2")
    o0 = create_offer(donor["id"], estimated_weight_lbs=20,
                      pickup_window_start="2026-08-02T10:00:00Z",
                      pickup_window_end="2026-08-02T11:00:00Z", publish=True)
    o1 = create_offer(donor["id"], estimated_weight_lbs=20,
                      pickup_window_start="2026-08-02T12:30:00Z",
                      pickup_window_end="2026-08-02T13:30:00Z", publish=True)
    o2 = create_offer(donor["id"], estimated_weight_lbs=20,
                      pickup_window_start="2026-08-02T14:30:00Z",
                      pickup_window_end="2026-08-02T15:30:00Z", publish=True)
    set_clock("2026-08-02T09:30:00Z")
    r0 = dispatch_run(o0["id"], driver_id=v1["id"], agency_id=agency["id"],
                      cooler_ids=[c1["id"]])
    respond_run(r0["id"], v1["id"], "ACCEPT")
    r1 = dispatch_run(o1["id"], driver_id=v1["id"], agency_id=agency["id"],
                      cooler_ids=[c2["id"]])
    respond_run(r1["id"], v1["id"], "ACCEPT")
    r2 = dispatch_run(o2["id"], driver_id=v1["id"], agency_id=agency["id"],
                      cooler_ids=[c1["id"]])
    return {"donor": donor, "agency": agency, "driver": v1,
            "coolers": (c1, c2), "offers": (o0, o1, o2), "runs": (r0, r1, r2)}


def setup_filed_strike_against_donor(reporter="driver"):
    """A FAILED_PICKUP run (fault DONOR, DONOR_NO_SHOW) with its auto-filed
    FILED strike. reporter='driver' files as the assigned driver;
    reporter='admin' files as DispatchAdmin admin-1 (PRD §3.6)."""
    ctx = setup_confirmed_run(food_category="SHELF_STABLE",
                              estimated_weight_lbs=10,
                              agency_capacity_lbs=100)
    if reporter == "driver":
        fail_run(ctx["run"]["id"], "DONOR", "DONOR_NO_SHOW",
                 as_driver_id=ctx["driver"]["id"])
    else:
        fail_run(ctx["run"]["id"], "DONOR", "DONOR_NO_SHOW", as_admin_id="admin-1")
    resp = api_client.list_run_strike_reports(ctx["run"]["id"], ADMIN)
    assert resp.status_code == 200, f"Setup failed: list strikes -> {resp.text}"
    strikes = get_success_data(resp)
    assert len(strikes) == 1, f"Setup failed: expected 1 strike, got {strikes}"
    ctx["strike"] = strikes[0]
    return ctx
