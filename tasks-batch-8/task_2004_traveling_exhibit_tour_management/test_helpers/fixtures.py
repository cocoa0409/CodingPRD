"""
Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient validator) internally so setup
failures surface as clear "Setup failed" errors rather than confusing
assertion failures deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_tour_payload,
    create_venue_payload,
    create_crate_payload,
    create_stop_payload,
    create_contract_payload,
    create_marketing_kit_payload,
    create_certificate_payload,
    create_shipment_payload,
    create_report_payload,
    create_claim_payload,
)
from .test_users import TEST_USERS

TM = TEST_USERS["tour_manager_headers"]
VR = TEST_USERS["venue_registrar_headers"]
REG = TEST_USERS["registrar_headers"]
SHIP = TEST_USERS["shipper_headers"]
INS = TEST_USERS["insurer_headers"]


# ─── Tier 1: State Progression ────────────────────────


def create_tour(**overrides):
    """Create a tour. Returns the DRAFT tour dict."""
    return get_success_data(api_client.create_tour(create_tour_payload(**overrides), TM))


def create_and_open_booking(crate_values=None, **tour_overrides):
    """Create a tour, register crates, OPEN_BOOKING. Returns (tour, [crate, ...])."""
    if crate_values is None:
        crate_values = [tour_overrides.get("declared_value_cents", 1_000_000)]
    tour_overrides.setdefault("crate_count", len(crate_values))
    tour = create_tour(**tour_overrides)
    crates = []
    for value in crate_values:
        crates.append(
            get_success_data(
                api_client.create_crate(
                    tour["id"], create_crate_payload(contents_value_cents=value), TM
                )
            )
        )
    res = api_client.transition_tour(tour["id"], {"action": "OPEN_BOOKING"}, TM)
    return get_success_data(res), crates


def create_venue(**overrides):
    """Register a venue. Returns the venue dict."""
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), TM))


def current_tour_version(tour_id):
    """Read the tour and return its current version (for OCC-guarded stop booking)."""
    return get_success_data(api_client.get_tour(tour_id, TM))["version"]


# ─── Tier 2: Entity Hierarchy ─────────────────────────


def book_stop(tour_id, venue_id, **overrides):
    """Book a stop with the tour's current version. Returns the TENTATIVE stop."""
    tv = current_tour_version(tour_id)
    payload = create_stop_payload(venue_id, tv, **overrides)
    return get_success_data(api_client.create_stop(tour_id, payload, TM))


def setup_booking_tour_with_stop(
    crate_values=None,
    venue_overrides=None,
    stop_overrides=None,
    **tour_overrides,
):
    """Tour in BOOKING + venue + one TENTATIVE stop. Returns (tour, crates, venue, stop)."""
    tour, crates = create_and_open_booking(crate_values=crate_values, **tour_overrides)
    venue = create_venue(**(venue_overrides or {}))
    stop = book_stop(tour["id"], venue["id"], **(stop_overrides or {}))
    return tour, crates, venue, stop


# ─── Tier 3: Contract Lifecycle ───────────────────────


def create_and_send_contract(tour_id, stop_id, **overrides):
    """Create a contract and SEND it. Returns the SENT contract."""
    contract = get_success_data(
        api_client.create_contract(
            tour_id, stop_id, create_contract_payload(**overrides), TM
        )
    )
    return get_success_data(
        api_client.transition_contract(tour_id, stop_id, {"action": "SEND"}, TM)
    )


def create_and_sign_contract(tour_id, stop_id, **overrides):
    """Create a contract, SEND, SIGN. Returns the SIGNED contract.

    Side effect per PRD: stop flips TENTATIVE -> CONTRACTED.
    """
    create_and_send_contract(tour_id, stop_id, **overrides)
    return get_success_data(
        api_client.transition_contract(tour_id, stop_id, {"action": "SIGN"}, VR)
    )


def setup_contracted_stop(
    crate_values=None,
    venue_overrides=None,
    stop_overrides=None,
    contract_overrides=None,
    **tour_overrides,
):
    """Tour in BOOKING + venue + stop CONTRACTED. Returns (tour, crates, venue, stop, contract)."""
    tour, crates, venue, stop = setup_booking_tour_with_stop(
        crate_values=crate_values,
        venue_overrides=venue_overrides,
        stop_overrides=stop_overrides,
        **tour_overrides,
    )
    contract = create_and_sign_contract(tour["id"], stop["id"], **(contract_overrides or {}))
    stop = get_success_data(api_client.get_stop(tour["id"], stop["id"], TM))
    return tour, crates, venue, stop, contract


# ─── Tier 4: Shipment Lifecycle ───────────────────────


def issue_certificate(tour_id, stop_id, coverage_cents, **overrides):
    """Insurer issues a certificate covering the stop. Returns the ISSUED cert."""
    return get_success_data(
        api_client.create_certificate(
            tour_id,
            create_certificate_payload(stop_id, coverage_cents, **overrides),
            INS,
        )
    )


def plan_first_leg(tour_id, stop_id, crate_ids, **overrides):
    """Plan the first shipment leg (null origin). Returns the PLANNED shipment."""
    return get_success_data(
        api_client.create_shipment(
            tour_id, create_shipment_payload(stop_id, crate_ids, **overrides), TM
        )
    )


def transition_shipment(tour_id, shipment_id, action, headers=None):
    """Drive one shipment transition with the role that owns it."""
    if headers is None:
        headers = {"DISPATCH": SHIP, "DEPART": SHIP, "RECEIVE": REG, "CLEAR": REG}[action]
    return get_success_data(
        api_client.transition_shipment(tour_id, shipment_id, {"action": action}, headers)
    )


def ship_to_received(tour_id, shipment_id):
    """DISPATCH -> DEPART -> RECEIVE. Returns the RECEIVED shipment."""
    transition_shipment(tour_id, shipment_id, "DISPATCH")
    transition_shipment(tour_id, shipment_id, "DEPART")
    return transition_shipment(tour_id, shipment_id, "RECEIVE")


def setup_received_shipment(
    crate_values=None,
    venue_overrides=None,
    stop_overrides=None,
    contract_overrides=None,
    **tour_overrides,
):
    """
    Stop CONTRACTED + certificate + first-leg shipment RECEIVED.
    Returns (tour, crates, venue, stop, contract, shipment).
    """
    tour, crates, venue, stop, contract = setup_contracted_stop(
        crate_values=crate_values,
        venue_overrides=venue_overrides,
        stop_overrides=stop_overrides,
        contract_overrides=contract_overrides,
        **tour_overrides,
    )
    issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
    shipment = plan_first_leg(tour["id"], stop["id"], [c["id"] for c in crates])
    shipment = ship_to_received(tour["id"], shipment["id"])
    return tour, crates, venue, stop, contract, shipment


# ─── Tier 4b: Condition Reports ───────────────────────


def file_report(tour_id, shipment_id, crate_id, **overrides):
    """File a DRAFT condition report. Returns the report."""
    return get_success_data(
        api_client.create_report(
            tour_id, shipment_id, create_report_payload(crate_id, **overrides), REG
        )
    )


def transition_report(tour_id, shipment_id, report_id, action, headers=None):
    """Drive one report transition with the role that owns it."""
    if headers is None:
        headers = {"SUBMIT": REG, "ACCEPT": TM, "DISPUTE": SHIP}[action]
    return get_success_data(
        api_client.transition_report(
            tour_id, shipment_id, report_id, {"action": action}, headers
        )
    )


def file_and_submit_report(tour_id, shipment_id, crate_id, **overrides):
    """File + SUBMIT a report. Returns the SUBMITTED report."""
    report = file_report(tour_id, shipment_id, crate_id, **overrides)
    return transition_report(tour_id, shipment_id, report["id"], "SUBMIT")


def file_submit_accept_report(tour_id, shipment_id, crate_id, **overrides):
    """File + SUBMIT + ACCEPT a report. Returns the ACCEPTED report."""
    report = file_and_submit_report(tour_id, shipment_id, crate_id, **overrides)
    return transition_report(tour_id, shipment_id, report["id"], "ACCEPT")


def accept_unpack_reports_and_clear(tour_id, shipment_id, crates, **report_overrides):
    """File+SUBMIT+ACCEPT one UNPACK report per crate, then CLEAR the shipment."""
    for crate in crates:
        file_submit_accept_report(tour_id, shipment_id, crate["id"], **report_overrides)
    return transition_shipment(tour_id, shipment_id, "CLEAR")


# ─── Tier 5: Stop Lifecycle Shortcuts ─────────────────


def setup_install_ready_stop(**kwargs):
    """
    Stop CONTRACTED, inbound shipment CLEARED with accepted UNPACK reports.
    Returns (tour, crates, venue, stop, contract, shipment).
    """
    tour, crates, venue, stop, contract, shipment = setup_received_shipment(**kwargs)
    accept_unpack_reports_and_clear(tour["id"], shipment["id"], crates)
    return tour, crates, venue, stop, contract, shipment


def transition_stop(tour_id, stop_id, action, headers=None):
    """Drive one stop transition (TourManager per PRD)."""
    return get_success_data(
        api_client.transition_stop(tour_id, stop_id, {"action": action}, headers or TM)
    )


def setup_stop_in_teardown(**kwargs):
    """
    Stop walked CONTRACTED -> INSTALLING -> OPEN -> TEARDOWN.
    Returns (tour, crates, venue, stop, contract, shipment).
    """
    tour, crates, venue, stop, contract, shipment = setup_install_ready_stop(**kwargs)
    transition_stop(tour["id"], stop["id"], "BEGIN_INSTALL")
    transition_stop(tour["id"], stop["id"], "OPEN_TO_PUBLIC")
    transition_stop(tour["id"], stop["id"], "BEGIN_TEARDOWN")
    stop = get_success_data(api_client.get_stop(tour["id"], stop["id"], TM))
    return tour, crates, venue, stop, contract, shipment


def pack_and_close(tour_id, shipment_id, crates, stop_id, actual_attendance):
    """Report actual_attendance, ACCEPT PACK reports per crate, CLOSE_STOP."""
    get_success_data(
        api_client.update_stop(
            tour_id, stop_id, {"actual_attendance": actual_attendance}, VR
        )
    )
    for crate in crates:
        file_submit_accept_report(
            tour_id, shipment_id, crate["id"], phase="PACK"
        )
    return transition_stop(tour_id, stop_id, "CLOSE_STOP")


def setup_closed_stop(actual_attendance=1000, **kwargs):
    """
    Full lifecycle through stop CLOSED. Returns (tour, crates, venue, stop, contract, shipment).
    """
    tour, crates, venue, stop, contract, shipment = setup_stop_in_teardown(**kwargs)
    stop = pack_and_close(tour["id"], shipment["id"], crates, stop["id"], actual_attendance)
    return tour, crates, venue, stop, contract, shipment
