"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server). Lenient get_success_data
is used internally so setup failures surface as clear "Setup failed" errors.

Ownership-gated calls always thread the acting entity's id through
make_builder_rep_headers / make_hoa_manager_headers (PRD §2.1).
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CONTINGENCY_END, TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_bond_payload,
    create_builder_payload,
    create_closing_payload,
    create_connection_payload,
    create_draw_payload,
    create_hoa_payload,
    create_loan_payload,
    create_parcel_payload,
    create_phase_payload,
    create_provider_payload,
    submit_plat_payload,
)
from .test_users import (
    TEST_USERS,
    make_builder_rep_headers,
    make_developer_operator_headers,
    make_lender_officer_headers,
)

DEV = TEST_USERS["developer_operator_headers"]
CLERK = TEST_USERS["municipal_clerk_headers"]
LENDER = TEST_USERS["lender_officer_headers"]

CONTINGENCY_END = DEFAULT_CONTINGENCY_END


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def round_half_up_cents(numerator: int, denominator: int = 10000) -> int:
    """Integer round-half-up of numerator/denominator (PRD §2.6)."""
    return (2 * numerator + denominator) // (2 * denominator)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, DEV))


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def create_parcel(**overrides) -> dict:
    """Create a parcel (starts DRAFT). Returns the created parcel."""
    return get_success_data(
        api_client.create_parcel(create_parcel_payload(**overrides), DEV), 201)


def open_contingency(parcel_id: str,
                     contingency_end_date: str = CONTINGENCY_END) -> dict:
    return get_success_data(api_client.open_contingency(
        parcel_id, {"contingency_end_date": contingency_end_date}, DEV))


def create_acquired_parcel(contingency_end_date: str = CONTINGENCY_END,
                           **overrides) -> dict:
    """Parcel walked DRAFT -> CONTINGENCY_ACTIVE -> ACQUIRED."""
    parcel = create_parcel(**overrides)
    open_contingency(parcel["id"], contingency_end_date)
    return get_success_data(api_client.clear_contingency(parcel["id"], DEV))


def create_phase(parcel_id: str, sequence_number: int = 1, **overrides) -> dict:
    return get_success_data(api_client.create_phase(
        create_phase_payload(parcel_id, sequence_number=sequence_number, **overrides),
        DEV), 201)


def submit_plat(phase_id: str, plat_lot_count: int = 3,
                lot_type: str = "STANDARD") -> dict:
    return get_success_data(api_client.submit_plat(
        phase_id, submit_plat_payload(plat_lot_count, lot_type), DEV))


def walk_phase_to_recorded(phase_id: str, plat_lot_count: int,
                           lot_type: str = "STANDARD") -> dict:
    """PLANNED -> PLAT_SUBMITTED -> PLAT_APPROVED -> PLAT_RECORDED."""
    submit_plat(phase_id, plat_lot_count, lot_type)
    get_success_data(
        api_client.review_plat(phase_id, {"decision": "APPROVE"}, CLERK))
    return get_success_data(api_client.record_plat(phase_id, CLERK))


def create_bond(phase_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_bond(create_bond_payload(phase_id, **overrides), DEV), 201)


def award_bid(bond_id: str,
              awarded_bid_cents: int = TEST_DEFAULTS["AWARDED_BID_CENTS"]) -> dict:
    return get_success_data(api_client.award_bid(
        bond_id, {"awarded_bid_cents": awarded_bid_cents}, DEV))


def create_posted_bond(
        phase_id: str,
        engineer_estimate_cents: int = TEST_DEFAULTS["ENGINEER_ESTIMATE_CENTS"],
        awarded_bid_cents: int = TEST_DEFAULTS["AWARDED_BID_CENTS"],
        posted_amount_cents: Optional[int] = None) -> dict:
    """Bond walked ESTIMATED -> BID_FINAL -> POSTED (PRD §3.3)."""
    bond = create_bond(phase_id, engineer_estimate_cents=engineer_estimate_cents)
    award_bid(bond["id"], awarded_bid_cents)
    if posted_amount_cents is None:
        # exactly the final-basis requirement: 110% of the awarded bid
        posted_amount_cents = round_half_up_cents(awarded_bid_cents * 11000)
    return get_success_data(api_client.post_bond(
        bond["id"], {"posted_amount_cents": posted_amount_cents}, DEV))


def create_builder(**overrides) -> dict:
    return get_success_data(
        api_client.create_builder(create_builder_payload(**overrides), DEV), 201)


def create_agreement(parcel_id: str, builder_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_agreement(
        create_agreement_payload(parcel_id, builder_id, **overrides), DEV), 201)


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, DEV))


def create_active_agreement(parcel_id: str, builder_id: str, **overrides) -> dict:
    agreement = create_agreement(parcel_id, builder_id, **overrides)
    return activate_agreement(agreement["id"])


def create_loan(parcel_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_loan(create_loan_payload(parcel_id, **overrides), DEV), 201)


def create_active_loan(parcel_id: str, **overrides) -> dict:
    loan = create_loan(parcel_id, **overrides)
    return get_success_data(api_client.activate_loan(loan["id"], DEV))


def create_hoa(parcel_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_hoa(create_hoa_payload(parcel_id, **overrides), DEV), 201)


def create_formed_hoa(parcel_id: str, **overrides) -> dict:
    """HOA walked FORMATION_PENDING -> DECLARANT_CONTROL."""
    hoa = create_hoa(parcel_id, **overrides)
    return get_success_data(api_client.form_hoa(hoa["id"], DEV))


def create_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides), CLERK), 201)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def list_phase_lots(phase_id: str) -> List[dict]:
    lots, _meta = validate_paginated(
        api_client.list_lots(DEV, params={"phase_id": phase_id, "limit": 100}))
    return lots


def create_active_phase(parcel_id: str, planned_lot_count: int = 3,
                        plat_lot_count: Optional[int] = None,
                        lot_type: str = "STANDARD", sequence_number: int = 1,
                        **phase_overrides):
    """Phase walked PLANNED -> ... -> ACTIVE with its lots recorded and its
    infrastructure bond POSTED (the two activation gates of PRD §3.2).
    Returns (activated_phase, lots)."""
    phase = create_phase(parcel_id, sequence_number=sequence_number,
                         planned_lot_count=planned_lot_count, **phase_overrides)
    walk_phase_to_recorded(
        phase["id"], plat_lot_count or planned_lot_count, lot_type)
    create_posted_bond(phase["id"])
    activated = get_success_data(api_client.activate_phase(phase["id"], DEV))
    return activated, list_phase_lots(phase["id"])


def setup_selling_scenario(num_lots: int = 3,
                           parcel_overrides: Optional[Dict] = None,
                           agreement_overrides: Optional[Dict] = None,
                           loan: str = "active",
                           loan_overrides: Optional[Dict] = None,
                           activate: bool = True,
                           builder_license: str = "LIC-1") -> dict:
    """The standard selling pipeline: parcel ACQUIRED, phase ACTIVE with
    num_lots recorded lots, a builder, its takedown agreement, and the
    parcel's development loan. loan: "active" | "draft" | None."""
    parcel = create_acquired_parcel(**(parcel_overrides or {}))
    phase, lots = create_active_phase(parcel["id"], planned_lot_count=num_lots)
    builder = create_builder(license_number=builder_license)
    agreement = create_agreement(parcel["id"], builder["id"],
                                 **(agreement_overrides or {}))
    if activate:
        agreement = activate_agreement(agreement["id"])
    loan_row = None
    if loan == "active":
        loan_row = create_active_loan(parcel["id"], **(loan_overrides or {}))
    elif loan == "draft":
        loan_row = create_loan(parcel["id"], **(loan_overrides or {}))
    return {
        "parcel": parcel,
        "phase": phase,
        "lots": lots,
        "builder": builder,
        "agreement": agreement,
        "loan": loan_row,
    }


def setup_agreement_only(agreement_overrides: Optional[Dict] = None,
                         activate: bool = True,
                         builder_license: str = "LIC-1") -> dict:
    """Light pipeline: parcel ACQUIRED + builder + agreement (no phase/loan)."""
    parcel = create_acquired_parcel()
    builder = create_builder(license_number=builder_license)
    agreement = create_agreement(parcel["id"], builder["id"],
                                 **(agreement_overrides or {}))
    if activate:
        agreement = activate_agreement(agreement["id"])
    return {"parcel": parcel, "builder": builder, "agreement": agreement}


def setup_active_loan_scenario(commitment_amount_cents: int = 20000000,
                               activate_loan: bool = True) -> dict:
    """Light pipeline: parcel ACQUIRED + development loan."""
    parcel = create_acquired_parcel()
    if activate_loan:
        loan = create_active_loan(
            parcel["id"], commitment_amount_cents=commitment_amount_cents)
    else:
        loan = create_loan(
            parcel["id"], commitment_amount_cents=commitment_amount_cents)
    return {"parcel": parcel, "loan": loan}


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts (reservation / closing / draws)
# ---------------------------------------------------------------------------

def reserve_lot(lot_id: str, agreement_id: str, builder_id: str) -> dict:
    """BuilderRep reserves a lot under their own builder's agreement."""
    return get_success_data(api_client.reserve_lot(
        lot_id, {"agreement_id": agreement_id},
        make_builder_rep_headers(builder_id)))


def open_closing(lot_id: str, agreement_id: str, builder_id: str) -> dict:
    """Reserve (if needed) is the caller's job; this opens the PENDING closing."""
    return get_success_data(api_client.create_closing(
        create_closing_payload(lot_id, agreement_id),
        make_builder_rep_headers(builder_id)), 201)


def finalize_closing(closing_id: str, officer_id: str = "lo-user-1") -> dict:
    return get_success_data(api_client.finalize_closing(
        closing_id, make_lender_officer_headers(officer_id)))


def reserve_and_open_closing(lot_id: str, agreement_id: str,
                             builder_id: str) -> dict:
    reserve_lot(lot_id, agreement_id, builder_id)
    return open_closing(lot_id, agreement_id, builder_id)


def close_lot(lot_id: str, agreement_id: str, builder_id: str) -> dict:
    """Reserve -> open closing -> finalize. Returns the CLOSED closing."""
    closing = reserve_and_open_closing(lot_id, agreement_id, builder_id)
    return finalize_closing(closing["id"])


def create_requested_draw(loan_id: str, amount_cents: int,
                          requester_id: str = "dev-user-1",
                          line_items: Optional[list] = None) -> dict:
    payload = create_draw_payload(loan_id, amount_cents)
    if line_items is not None:
        payload["line_items"] = line_items
    return get_success_data(api_client.create_draw(
        payload, make_developer_operator_headers(requester_id)), 201)


def create_funded_draw(loan_id: str, amount_cents: int,
                       requester_id: str = "dev-user-1",
                       approver_id: str = "lo-user-1") -> dict:
    """Draw walked REQUESTED -> APPROVED -> FUNDED (PRD §3.6)."""
    draw = create_requested_draw(loan_id, amount_cents, requester_id)
    get_success_data(
        api_client.approve_draw(draw["id"], make_lender_officer_headers(approver_id)))
    return get_success_data(
        api_client.fund_draw(draw["id"], make_lender_officer_headers(approver_id)))


def create_connection(lot_id: str, provider_id: str,
                      scheduled_date: str = "2026-08-20T00:00:00Z") -> dict:
    return get_success_data(api_client.create_connection(
        create_connection_payload(lot_id, provider_id, scheduled_date), DEV), 201)


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------

def setup_finalize_cascade_scenario(num_lots: int = 4,
                                    scheduled_lot_count: int = 4,
                                    commitment_amount_cents: int = 20000000,
                                    funded_draw_gross: Optional[int] = 2000000,
                                    closings_opened: int = 3) -> dict:
    """Selling scenario plus a FUNDED draw and an HOA in DECLARANT_CONTROL,
    with `closings_opened` PENDING closings staged on the first lots.
    Used by the finalize-cascade and HOA-threshold tests (PRD §3.5, §3.8)."""
    scenario = setup_selling_scenario(
        num_lots=num_lots,
        agreement_overrides={"scheduled_lot_count": scheduled_lot_count},
        loan_overrides={"commitment_amount_cents": commitment_amount_cents},
    )
    draw = None
    if funded_draw_gross is not None:
        draw = create_funded_draw(scenario["loan"]["id"], funded_draw_gross)
    hoa = create_formed_hoa(scenario["parcel"]["id"],
                            hoa_name="Cascade HOA",
                            statutory_control_end="2030-01-01T00:00:00Z")
    builder_id = scenario["builder"]["id"]
    agreement_id = scenario["agreement"]["id"]
    closings = [
        reserve_and_open_closing(scenario["lots"][i]["id"], agreement_id, builder_id)
        for i in range(closings_opened)
    ]
    scenario.update({"draw": draw, "hoa": hoa, "closings": closings})
    return scenario


def setup_hoa_threshold_scenario(pre_closed: int = 2, total_lots: int = 4) -> dict:
    """Parcel at `pre_closed`/`total_lots` closed with one further PENDING
    closing staged and an HOA in DECLARANT_CONTROL at the default 7500 bp
    threshold. Used for the inclusive-75% boundary tests (PRD §3.8)."""
    scenario = setup_selling_scenario(
        num_lots=total_lots, agreement_overrides={"scheduled_lot_count": total_lots})
    builder_id = scenario["builder"]["id"]
    agreement_id = scenario["agreement"]["id"]
    for i in range(pre_closed):
        close_lot(scenario["lots"][i]["id"], agreement_id, builder_id)
    pending = reserve_and_open_closing(
        scenario["lots"][pre_closed]["id"], agreement_id, builder_id)
    hoa = create_formed_hoa(scenario["parcel"]["id"], hoa_name="Threshold HOA",
                            statutory_control_end="2030-01-01T00:00:00Z")
    scenario.update({"hoa": hoa, "pending_closing": pending})
    return scenario


def setup_absorption_divergence_scenario() -> dict:
    """TRAILING_WEIGHTED parcel with 8 recorded lots and 24 planned months;
    one closing finalized at clock 2026-06-05, two more at 2026-07-20, and the
    clock finally set to 2026-08-01 — so C1=2, C2=1, C3=0 in the trailing
    windows of PRD §3.8."""
    set_clock("2026-06-05T00:00:00Z")
    scenario = setup_selling_scenario(
        num_lots=8,
        parcel_overrides={"planned_sellout_months": 24,
                          "absorption_method": "TRAILING_WEIGHTED"},
        agreement_overrides={"scheduled_lot_count": 8},
    )
    builder_id = scenario["builder"]["id"]
    agreement_id = scenario["agreement"]["id"]
    close_lot(scenario["lots"][0]["id"], agreement_id, builder_id)
    set_clock("2026-07-20T00:00:00Z")
    close_lot(scenario["lots"][1]["id"], agreement_id, builder_id)
    close_lot(scenario["lots"][2]["id"], agreement_id, builder_id)
    set_clock("2026-08-01T00:00:00Z")
    return scenario


def setup_trailing_edge_scenario() -> dict:
    """One closing finalized while the clock reads 2026-07-02, then the clock
    advanced to exactly 2026-08-01 — the closing sits exactly thirty days back,
    at C1's inclusive lower edge (PRD §3.8)."""
    set_clock("2026-07-02T00:00:00Z")
    scenario = setup_selling_scenario(
        num_lots=2,
        parcel_overrides={"planned_sellout_months": 24},
        agreement_overrides={"scheduled_lot_count": 2},
    )
    close_lot(scenario["lots"][0]["id"], scenario["agreement"]["id"],
              scenario["builder"]["id"])
    set_clock("2026-08-01T00:00:00Z")
    return scenario


def setup_two_agreement_pricing_scenario() -> dict:
    """Parcel ACQUIRED; phase ACTIVE with 4 lots; two builders each holding an
    ACTIVE agreement sharing base 5000000 / cap 12000 bp / effective 2026-01-01 —
    agreement A at 300 bp per quarter, agreement B at 1500 bp per quarter — plus
    an ACTIVE loan. Lot 0 is pre-reserved under A, lot 1 under B. At the default
    clock both agreements sit exactly two quarters elapsed (PRD §3.4)."""
    scenario = setup_selling_scenario(
        num_lots=4,
        agreement_overrides={"scheduled_lot_count": 4},
        builder_license="LIC-10",
    )
    builder_b = create_builder(builder_name="B2 Co", license_number="LIC-11",
                               contact_email="b2@example.com")
    agreement_b = create_active_agreement(
        scenario["parcel"]["id"], builder_b["id"],
        escalator_rate_bp_per_quarter=1500, scheduled_lot_count=4)
    reserve_lot(scenario["lots"][0]["id"], scenario["agreement"]["id"],
                scenario["builder"]["id"])
    reserve_lot(scenario["lots"][1]["id"], agreement_b["id"], builder_b["id"])
    scenario.update({"builder_b": builder_b, "agreement_b": agreement_b})
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: provider / connection scenarios
# ---------------------------------------------------------------------------

def setup_connection_scenario(num_lots: int = 4, max_connections_per_day: int = 2,
                              provider_overrides: Optional[Dict] = None) -> dict:
    """Parcel ACQUIRED + phase ACTIVE with lots + one utility provider.
    No agreement or loan is needed for connection requests (PRD §3.9)."""
    parcel = create_acquired_parcel()
    phase, lots = create_active_phase(parcel["id"], planned_lot_count=num_lots)
    provider_payload = {"max_connections_per_day": max_connections_per_day}
    provider_payload.update(provider_overrides or {})
    provider = create_provider(**provider_payload)
    return {"parcel": parcel, "phase": phase, "lots": lots, "provider": provider}


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------

def get_parcel(parcel_id: str) -> dict:
    return get_success_data(api_client.get_parcel(parcel_id, DEV))


def get_phase(phase_id: str) -> dict:
    return get_success_data(api_client.get_phase(phase_id, DEV))


def get_bond(bond_id: str) -> dict:
    return get_success_data(api_client.get_bond(bond_id, DEV))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, DEV))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, DEV))


def get_closing(closing_id: str) -> dict:
    return get_success_data(api_client.get_closing(closing_id, DEV))


def get_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan(loan_id, DEV))


def get_hoa(hoa_id: str) -> dict:
    return get_success_data(api_client.get_hoa(hoa_id, DEV))
