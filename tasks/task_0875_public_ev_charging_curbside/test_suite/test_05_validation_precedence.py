"""Validation precedence and cross-entity gates at commission / session start.

Difficulty: priority_pair_validation_conflict/{confirm_cancelled...,commission_inactive...},
cross_entity_state_dependency/{session_start_blocked...,station_commission_blocked...}.
Corner: validations/{commission_missing_ada...,start_session_on_reserved...}.
"""
from test_helpers import (
    validate_success, validate_error, api_client,
    admin_headers, tech_headers, make_driver_headers,
    new_site, new_grant, new_station, new_port, new_agreement, active_agreement,
    site_with_port, new_reservation, confirmed_reservation,
    create_session_payload,
)


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict /
#   confirm_cancelled_reservation_that_also_overlaps_state_beats_temporal
# --------------------------------------------------------------------------- #
def test_confirm_cancelled_reservation_reports_state_not_overlap(api):
    """PRD §2.10: "Ownership is checked next (`ERR_NOT_RESOURCE_OWNER`), followed by
    whether the target resource is in a state from which the requested transition is
    legal (`ERR_INVALID_STATE`). Only after these structural gates do the
    domain-specific business rules run: ... the temporal-conflict checks
    (`ERR_RESERVATION_OVERLAP`, `ERR_MAINTENANCE_WINDOW_OVERLAP`, ...)."
    PRD §2.10: "A rule earlier in this order always masks a rule later in it."

    Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_reservation_that_also_overlaps_state_beats_temporal
    """
    _, _, port = site_with_port(power_kw=100)
    r1 = new_reservation(port["id"], driver_id="drv-1",
                         window_start="2026-05-04T10:00:00Z", window_end="2026-05-04T11:00:00Z")
    r2 = new_reservation(port["id"], driver_id="drv-1",
                         window_start="2026-05-04T10:30:00Z", window_end="2026-05-04T11:30:00Z")
    validate_success(api.confirm_reservation(r2["id"], make_driver_headers("drv-1")), 200)
    validate_success(api.cancel_reservation(r1["id"], make_driver_headers("drv-1")), 200)
    # r1 is CANCELLED and its window overlaps CONFIRMED r2 — state gate must win.
    res = api.confirm_reservation(r1["id"], make_driver_headers("drv-1"))
    validate_error(res, "ERR_INVALID_STATE")


def test_confirm_cancelled_reservation_without_overlap_still_invalid_state(api):
    """PRD §3.5: "Confirming a `PENDING` reservation into `CONFIRMED` holds the port".
    PRD §2.10: "... whether the target resource is in a state from which the requested
    transition is legal (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_reservation_that_also_overlaps_state_beats_temporal
    """
    _, _, port = site_with_port(power_kw=100)
    r = new_reservation(port["id"], driver_id="drv-1")
    validate_success(api.cancel_reservation(r["id"], make_driver_headers("drv-1")), 200)
    res = api.confirm_reservation(r["id"], make_driver_headers("drv-1"))
    validate_error(res, "ERR_INVALID_STATE")


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict /
#   commission_inactive_agreement_and_below_min_ports_referential_beats_constraint
# --------------------------------------------------------------------------- #
def _grant_station_below_min_ports(api, activate: bool):
    grant = new_grant(min_ports=2)
    site = new_site(ada_required=False)
    agr = new_agreement(site["id"])
    if activate:
        validate_success(api.propose_agreement(agr["id"], {}, admin_headers()), 200)
        validate_success(api.activate_agreement(agr["id"], admin_headers()), 200)
    station = new_station(site["id"], grant_id=grant["id"], ada_accessible=True)
    new_port(station["id"], power_kw=180, ada_accessible=True)  # 1 port < min_ports 2
    return station["id"]


def test_commission_inactive_agreement_masks_insufficient_ports(api):
    """PRD §2.10: "Only after these structural gates do the domain-specific business
    rules run: the active-agreement requirement at commission
    (`ERR_AGREEMENT_NOT_ACTIVE`); the ADA and four-eyes safety gates ...; the
    port-availability and configuration checks (`ERR_PORT_OUT_OF_SERVICE`,
    `ERR_PORT_NOT_AVAILABLE`, `ERR_INSUFFICIENT_PORTS`, `ERR_ENERGY_INVALID`) ..."

    Design: Difficulty/priority_pair_validation_conflict/commission_inactive_agreement_and_below_min_ports_referential_beats_constraint
    """
    station_id = _grant_station_below_min_ports(api, activate=False)
    res = api.commission_station(station_id, admin_headers())
    validate_error(res, "ERR_AGREEMENT_NOT_ACTIVE")


def test_commission_with_active_agreement_then_reports_insufficient_ports(api):
    """PRD §3.2: "Third, if a `grant_id` is present, the station's `total_ports` must be
    at least the grant's `min_ports`, or the request is refused with
    `ERR_INSUFFICIENT_PORTS`."

    Design: Difficulty/priority_pair_validation_conflict/commission_inactive_agreement_and_below_min_ports_referential_beats_constraint
    """
    station_id = _grant_station_below_min_ports(api, activate=True)
    res = api.commission_station(station_id, admin_headers())
    validate_error(res, "ERR_INSUFFICIENT_PORTS")


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / session_start_blocked_by_port_out_of_service
# --------------------------------------------------------------------------- #
def test_start_session_on_out_of_service_port_rejected(api):
    """PRD §3.4: "The port must be `IN_SERVICE` (else `ERR_PORT_OUT_OF_SERVICE`) and
    `AVAILABLE` (else `ERR_PORT_NOT_AVAILABLE`)."

    Design: Difficulty/cross_entity_state_dependency/session_start_blocked_by_port_out_of_service
    """
    _, _, port = site_with_port(power_kw=100)
    validate_success(api.port_out_of_service(port["id"], tech_headers()), 200)
    res = api.create_session(create_session_payload(port["id"], "drv-1"), make_driver_headers("drv-1"))
    validate_error(res, "ERR_PORT_OUT_OF_SERVICE")


def test_start_session_succeeds_after_port_returned_to_service(api):
    """PRD §3.3: "Returning a port to service moves `operational_status` back to
    `IN_SERVICE` and clears `oos_opened_at` to null, but only when no `OPEN` `CRITICAL`
    work order remains on the port".

    Design: Difficulty/cross_entity_state_dependency/session_start_blocked_by_port_out_of_service
    """
    _, _, port = site_with_port(power_kw=100)
    validate_success(api.port_out_of_service(port["id"], tech_headers()), 200)
    validate_success(api.port_in_service(port["id"], tech_headers()), 200)
    res = api.create_session(create_session_payload(port["id"], "drv-1"), make_driver_headers("drv-1"))
    session = validate_success(res, 201)
    assert session["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / station_commission_blocked_without_active_agreement
# --------------------------------------------------------------------------- #
def test_commission_without_active_agreement_rejected(api):
    """PRD §3.2: "First, an `ACTIVE` host agreement must exist for the station's
    `site_id`, or the request is refused with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/station_commission_blocked_without_active_agreement
    """
    site = new_site(ada_required=False)
    new_agreement(site["id"])  # DRAFT, never activated
    station = new_station(site["id"])
    res = api.commission_station(station["id"], admin_headers())
    validate_error(res, "ERR_AGREEMENT_NOT_ACTIVE")


def test_commission_succeeds_once_agreement_active(api):
    """PRD §3.2: "Commissioning a `PENDING` station into `COMMISSIONED` is gated by
    three business rules evaluated after the structural checks. First, an `ACTIVE` host
    agreement must exist for the station's `site_id`, or the request is refused with
    `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/station_commission_blocked_without_active_agreement
    """
    site = new_site(ada_required=False)
    active_agreement(site["id"])
    station = new_station(site["id"])
    commissioned = validate_success(api.commission_station(station["id"], admin_headers()), 200)
    assert commissioned["operational_status"] == "COMMISSIONED"


# --------------------------------------------------------------------------- #
# Corner: validations
# --------------------------------------------------------------------------- #
def test_commission_missing_ada_port_returns_ada_required(api):
    """PRD §3.2: "Second, if the site declares `ada_required` or the station carries a
    `grant_id`, the station must have at least one port whose `ada_accessible` is true,
    failing which the request is refused with `ERR_ADA_PORT_REQUIRED`."

    Design: Corner/validations/commission_missing_ada_port_returns_ada_required
    """
    grant = new_grant(min_ports=1)
    site = new_site()
    active_agreement(site["id"])
    station = new_station(site["id"], grant_id=grant["id"])
    new_port(station["id"], power_kw=180, ada_accessible=False)  # no ADA port
    res = api.commission_station(station["id"], admin_headers())
    validate_error(res, "ERR_ADA_PORT_REQUIRED")


def test_start_session_on_reserved_port_returns_not_available(api):
    """PRD §3.4: "The port must be `IN_SERVICE` (else `ERR_PORT_OUT_OF_SERVICE`) and
    `AVAILABLE` (else `ERR_PORT_NOT_AVAILABLE`)."

    Design: Corner/validations/start_session_on_reserved_port_returns_not_available
    """
    _, _, port = site_with_port(power_kw=100)
    confirmed_reservation(port["id"], driver_id="drv-9")  # port now RESERVED
    res = api.create_session(create_session_payload(port["id"], "drv-1"), make_driver_headers("drv-1"))
    validate_error(res, "ERR_PORT_NOT_AVAILABLE")
