"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a fresh database
using only PRD-declared endpoints. Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup step failed" error.

Role identity conventions (PRD §2.1):
- Shipper is entity-backed: booking create/cancel/roll, B/L surrender and
  claim filing use make_shipper_headers(shipper["id"]).
- SoD pairs use distinct opaque ids: tariffs created by co_1 are published by
  co_2; B/Ls issued by doc_1 are released by doc_2; claims reviewed by adj_1
  are approved/denied by adj_2.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULTS
from .factories import (
    create_bill_of_lading_payload,
    create_carrier_contract_payload,
    create_compliance_filing_payload,
    create_consolidation_payload,
    create_container_assignment_payload,
    create_fcl_booking_payload,
    create_fcl_tariff_payload,
    create_insurance_policy_payload,
    create_lcl_booking_payload,
    create_shipper_payload,
    create_surety_bond_payload,
    create_tariff_payload,
    create_voyage_payload,
)
from .test_users import (
    make_adjuster_headers,
    make_compliance_headers,
    make_coordinator_headers,
    make_doc_officer_headers,
    make_finance_headers,
    make_ops_headers,
    make_shipper_headers,
)

# Canonical opaque desk identities.
CO_1 = make_compliance_headers("co_1")
CO_2 = make_compliance_headers("co_2")
DOC_1 = make_doc_officer_headers("doc_1")
DOC_2 = make_doc_officer_headers("doc_2")
BC = make_coordinator_headers("bc_1")
FC = make_finance_headers("fc_1")
OPS = make_ops_headers("ops_1")
ADJ_1 = make_adjuster_headers("adj_1")
ADJ_2 = make_adjuster_headers("adj_2")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------

def create_shipper(legal_name="ACME SHIPPING CO", **overrides) -> dict:
    """Register a shipper (OperationsManager). Returns the Shipper."""
    payload = create_shipper_payload(legal_name=legal_name, **overrides)
    return get_success_data(api_client.create_shipper(payload, OPS))


def create_draft_tariff(created_by="co_1", **overrides) -> dict:
    """Create a DRAFT tariff as the given ComplianceOfficer user id."""
    return get_success_data(
        api_client.create_tariff(create_tariff_payload(**overrides),
                                 make_compliance_headers(created_by)))


def publish_tariff(tariff_id: str, published_by="co_2", payload=None) -> dict:
    return get_success_data(api_client.publish_tariff(
        tariff_id, make_compliance_headers(published_by), payload=payload))


def create_published_tariff(**overrides) -> dict:
    """Create + publish a tariff (SoD: creator co_1, publisher co_2)."""
    tariff = create_draft_tariff(**overrides)
    return publish_tariff(tariff["id"])


def create_published_fcl_tariff(**overrides) -> dict:
    tariff = get_success_data(api_client.create_tariff(
        create_fcl_tariff_payload(**overrides), CO_1))
    return publish_tariff(tariff["id"])


def create_active_contract(**overrides) -> dict:
    """Create + activate a carrier contract."""
    contract = get_success_data(
        api_client.create_carrier_contract(create_carrier_contract_payload(**overrides),
                                           OPS))
    return get_success_data(api_client.activate_carrier_contract(contract["id"], OPS))


def create_active_bond(**overrides) -> dict:
    """Create + activate a surety bond (window must cover the logical clock)."""
    bond = get_success_data(
        api_client.create_surety_bond(create_surety_bond_payload(**overrides), CO_1))
    return get_success_data(api_client.activate_surety_bond(bond["id"], CO_1))


def create_open_voyage(contract_id: str, **overrides) -> dict:
    """Create a voyage and open it for booking."""
    voyage = get_success_data(
        api_client.create_voyage(create_voyage_payload(contract_id, **overrides), OPS))
    return get_success_data(api_client.open_voyage_for_booking(voyage["id"], OPS))


def advance_clock(to_iso8601: str):
    """Advance the logical clock (monotonic)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


# ---------------------------------------------------------------------------
# Tier 2: lane scenario (shipper + published tariff + active contract + open voyage)
# ---------------------------------------------------------------------------

def setup_lcl_lane(shipper_overrides=None, tariff_overrides=None,
                   contract_overrides=None, voyage_overrides=None) -> dict:
    """Shipper + published LCL tariff + ACTIVE contract + BOOKING_OPEN voyage."""
    shipper = create_shipper(**(shipper_overrides or {}))
    tariff = create_published_tariff(**(tariff_overrides or {}))
    contract = create_active_contract(**(contract_overrides or {}))
    voyage = create_open_voyage(contract["id"], **(voyage_overrides or {}))
    return {"shipper": shipper, "tariff": tariff, "contract": contract,
            "voyage": voyage}


def setup_fcl_lane(shipper_overrides=None, tariff_overrides=None,
                   contract_overrides=None, voyage_overrides=None) -> dict:
    """Shipper + published FCL tariff (40HC) + ACTIVE contract + open voyage."""
    shipper = create_shipper(**(shipper_overrides or {}))
    tariff = create_published_fcl_tariff(**(tariff_overrides or {}))
    contract = create_active_contract(**(contract_overrides or {}))
    voyage = create_open_voyage(contract["id"], **(voyage_overrides or {}))
    return {"shipper": shipper, "tariff": tariff, "contract": contract,
            "voyage": voyage}


# ---------------------------------------------------------------------------
# Tier 3: bookings and lifecycle walks
# ---------------------------------------------------------------------------

def create_quoted_booking(scenario: dict, as_shipper: bool = True, **overrides) -> dict:
    """Create a QUOTED booking in the given lane scenario.

    By default the booking is filed by the shipper itself (ownership headers).
    """
    lane = scenario
    mode = overrides.get("mode", lane["tariff"]["mode"])
    if mode == "FCL":
        payload = create_fcl_booking_payload(lane["voyage"]["id"],
                                             lane["tariff"]["id"], **overrides)
    else:
        payload = create_lcl_booking_payload(lane["voyage"]["id"],
                                             lane["tariff"]["id"], **overrides)
    if as_shipper:
        headers = make_shipper_headers(lane["shipper"]["id"])
    else:
        payload["shipper_id"] = lane["shipper"]["id"]
        headers = BC
    return get_success_data(api_client.create_booking(payload, headers))


def confirm_booking(booking_id: str) -> dict:
    return get_success_data(api_client.confirm_booking(booking_id, BC))


def create_confirmed_booking(scenario: dict, **overrides) -> dict:
    booking = create_quoted_booking(scenario, **overrides)
    return confirm_booking(booking["id"])


def create_filing(booking_id: str, filing_type: str) -> dict:
    return get_success_data(api_client.create_compliance_filing(
        create_compliance_filing_payload(booking_id, filing_type), CO_1))


def submit_and_answer_filing(filing_id: str, outcome: str = "ACCEPTED") -> dict:
    get_success_data(api_client.submit_compliance_filing(filing_id, CO_1))
    return get_success_data(
        api_client.record_filing_response(filing_id, outcome, CO_1))


def accept_both_filings(booking_id: str) -> dict:
    """Create + submit + accept ISF and AMS filings for the booking."""
    isf = submit_and_answer_filing(create_filing(booking_id, "ISF")["id"], "ACCEPTED")
    ams = submit_and_answer_filing(create_filing(booking_id, "AMS")["id"], "ACCEPTED")
    return {"ISF": isf, "AMS": ams}


def create_draft_bl(booking_id: str, release_mode="SEAWAY", issued_by="doc_1") -> dict:
    return get_success_data(api_client.create_bill_of_lading(
        create_bill_of_lading_payload(booking_id, release_mode=release_mode),
        make_doc_officer_headers(issued_by)))


def issue_bl(bl_id: str, issued_by="doc_1") -> dict:
    return get_success_data(
        api_client.issue_bill_of_lading(bl_id, make_doc_officer_headers(issued_by)))


# ---------------------------------------------------------------------------
# Tier 4: full documentation / loading / arrival chains
# ---------------------------------------------------------------------------

def setup_documented_fcl_scenario(shipper_overrides=None, terms="COLLECT",
                                  release_mode="SEAWAY", booking_overrides=None,
                                  **lane_overrides) -> dict:
    """FCL booking walked to DOCUMENTATION_CLEARED.

    Chain: lane -> booking -> confirm -> bond ACTIVE -> B/L issued by doc_1
    -> ISF + AMS ACCEPTED. Returns the full context dict.
    """
    ctx = setup_fcl_lane(shipper_overrides=shipper_overrides, **lane_overrides)
    ctx["booking"] = create_confirmed_booking(ctx, terms=terms,
                                              **(booking_overrides or {}))
    ctx["bond"] = create_active_bond()
    ctx["bl"] = issue_bl(create_draft_bl(ctx["booking"]["id"], release_mode)["id"])
    ctx["filings"] = accept_both_filings(ctx["booking"]["id"])
    return ctx


def setup_loaded_fcl_scenario(container_count=1, **kwargs) -> dict:
    """DOCUMENTATION_CLEARED FCL booking with all containers GATED_IN.

    The final gate-in bubbles the booking up to LOADED (and the member
    assignments to LOADED alongside).
    """
    if container_count != 1:
        kwargs["booking_overrides"] = {
            "container_count": container_count,
            "gross_weight_kg": 18000 * container_count,
            "volume_cbm": 50.0 * container_count,
        }
    ctx = setup_documented_fcl_scenario(**kwargs)
    assignments = []
    for i in range(container_count):
        asg = get_success_data(api_client.create_container_assignment(
            create_container_assignment_payload(
                ctx["booking"]["id"], container_number=f"MSKU{i:07d}",
                stuffed_weight_kg=18000, stuffed_volume_cbm=50.0),
            BC))
        get_success_data(api_client.gate_in_assignment(asg["id"], BC))
        assignments.append(get_success_data(
            api_client.get_container_assignment(asg["id"], BC)))
    ctx["assignments"] = assignments
    ctx["assignment"] = assignments[0]
    return ctx


def setup_discharged_fcl_scenario(depart_clock="2026-09-01T00:00:00Z",
                                  arrive_clock="2026-09-21T12:00:00Z",
                                  **kwargs) -> dict:
    """LOADED FCL scenario with the voyage departed and arrived.

    The single tracked assignment is DISCHARGED with discharged_at set to the
    arrive clock (the demurrage free-time window starts there).
    """
    ctx = setup_loaded_fcl_scenario(**kwargs)
    advance_clock(depart_clock)
    get_success_data(api_client.depart_voyage(ctx["voyage"]["id"], OPS))
    advance_clock(arrive_clock)
    get_success_data(api_client.arrive_voyage(ctx["voyage"]["id"], OPS))
    ctx["assignment"] = get_success_data(
        api_client.get_container_assignment(ctx["assignment"]["id"], BC))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: consolidation, invoice, insurance/claims shortcuts
# ---------------------------------------------------------------------------

def create_open_consolidation(voyage_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_consolidation(
        create_consolidation_payload(voyage_id, **overrides), BC))


def stuff_booking(consolidation_id: str, booking_id: str) -> dict:
    """Stuff an LCL booking into the consolidation at its current version.

    Reads the consolidation first so the OCC guard always carries the fresh
    version; returns the created ContainerAssignment.
    """
    consolidation = get_success_data(
        api_client.get_consolidation(consolidation_id, BC))
    return get_success_data(api_client.stuff_consolidation(
        consolidation_id, booking_id, consolidation["version"], BC))


def setup_stuffed_consolidation(shipper_overrides=None, booking_overrides=None,
                                consolidation_overrides=None,
                                **lane_overrides) -> dict:
    """LCL lane + CONFIRMED booking + OPEN consolidation with the booking stuffed."""
    ctx = setup_lcl_lane(shipper_overrides=shipper_overrides, **lane_overrides)
    ctx["booking"] = create_confirmed_booking(ctx, **(booking_overrides or {}))
    ctx["consolidation"] = create_open_consolidation(
        ctx["voyage"]["id"], **(consolidation_overrides or {}))
    ctx["assignment"] = stuff_booking(ctx["consolidation"]["id"],
                                      ctx["booking"]["id"])
    return ctx


def create_draft_freight_invoice(booking_id: str) -> dict:
    return get_success_data(api_client.create_invoice(
        {"booking_id": booking_id, "invoice_type": "FREIGHT"}, FC))


def create_issued_freight_invoice(booking_id: str) -> dict:
    invoice = create_draft_freight_invoice(booking_id)
    return get_success_data(api_client.issue_invoice(invoice["id"], FC))


def list_booking_invoices(booking_id: str) -> list:
    """All invoices visible in this test's fresh database.

    Filters client-side on booking_id so tests never rely on list query-param
    filters (the PRD pins only limit/offset pagination semantics).
    """
    data, _meta = _list_all_invoices()
    return [inv for inv in data if inv.get("booking_id") == booking_id]


def find_booking_invoice(booking_id: str, invoice_type: str):
    """The single invoice of the given type for the booking, or None."""
    matches = [inv for inv in list_booking_invoices(booking_id)
               if inv.get("invoice_type") == invoice_type]
    assert len(matches) <= 1, f"expected at most one {invoice_type} invoice"
    return matches[0] if matches else None


def _list_all_invoices():
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_invoices(FC, params={"limit": 100}))


def setup_bound_policy(scenario: dict, booking: dict, coverage_type="ALL_RISK",
                       cargo_value_cents=5000000) -> dict:
    """Quote + bind a cargo policy on the given CONFIRMED booking."""
    policy = get_success_data(api_client.create_insurance_policy(
        create_insurance_policy_payload(booking["id"], coverage_type=coverage_type,
                                        cargo_value_cents=cargo_value_cents), BC))
    return get_success_data(api_client.bind_insurance_policy(policy["id"], BC))


def file_claim_under_review(policy: dict, shipper_id: str,
                            claim_type="DAMAGE", claimed_amount_cents=400000,
                            reviewed_by="adj_1") -> dict:
    """File a claim (owning shipper) and move it to UNDER_REVIEW."""
    from .factories import create_claim_payload
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(policy["id"], claim_type=claim_type,
                             claimed_amount_cents=claimed_amount_cents),
        make_shipper_headers(shipper_id)))
    return get_success_data(
        api_client.start_claim_review(claim["id"], make_adjuster_headers(reviewed_by)))


def setup_approved_claim(coverage_type="ALL_RISK", claim_type="DAMAGE",
                         claimed_amount_cents=400000,
                         cargo_value_cents=5000000) -> dict:
    """Full chain: LCL lane -> CONFIRMED booking -> BOUND policy -> claim
    FILED -> UNDER_REVIEW by adj_1 -> APPROVED by adj_2 (SoD pair)."""
    ctx = setup_lcl_lane()
    ctx["booking"] = create_confirmed_booking(ctx)
    ctx["policy"] = setup_bound_policy(ctx, ctx["booking"],
                                       coverage_type=coverage_type,
                                       cargo_value_cents=cargo_value_cents)
    ctx["claim"] = file_claim_under_review(
        ctx["policy"], ctx["shipper"]["id"], claim_type=claim_type,
        claimed_amount_cents=claimed_amount_cents, reviewed_by="adj_1")
    ctx["claim"] = get_success_data(api_client.approve_claim(ctx["claim"]["id"], ADJ_2))
    return ctx
