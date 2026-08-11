"""The five ordered write gates, rungs 11-15 (PRD 2.6, 2.7).

G1 pre-empts G2..G5; G2 pre-empts G3..G5; G3 pre-empts G4 and G5; G4 pre-empts
G5. ``run_gates`` evaluates them in exactly that order and stops at the first.
"""
from errors import fail

# G2 exempts these four endpoints, and the first is what keeps the hold
# liftable at all (PRD 2.6).
G2_EXEMPT = {
    "lots.quarantine",
    "inspection_records.create",
    "inspection_records.result",
    "sale_days.advance",
}

# G3's scope is the enumerated rung-13 list (PRD 2.7); everything else - the
# money and logistics tail - stays open.
G3_SCOPE = {
    "lots.create",
    "lots.assign_pen",
    "lots.mark_ready",
    "lots.enter_ring",
    "lots.hammer_down",
    "lots.no_sale",
    "lots.re_ring",
    "bids.create",
    "weigh_tickets.create",
    "weigh_tickets.capture",
    "pen_moves.create",
    "consignments.create",
    "consignments.check_in",
}

G4_EXEMPT = {"parties.status"}

# Adjudication of friction 7: PRD 2.6 describes G5 as reaching any mutation of
# a RELEASED settlement, while rung 15's own enumerated scope names only the
# release endpoint, and PRD 2.7 says both statements stand as written. We adopt
# the rung-15 scope: only POST /settlements/{id}/release answers
# ERR_SETTLEMENT_RELEASED. This is the reading that keeps the largest number of
# PRD-declared behaviours reachable - a purchase void, a payment and a credit
# memo can still touch a consignment whose settlement has been released, and
# hop 3 of the void cascade (which drives a settlement to ADJUSTED) stays
# reachable instead of being dead code.
G5_SCOPE = {"settlements.release"}


def run_gates(endpoint, sale_day=None, lot=None, party=None, settlement=None):
    # Rung 11 - G1. Nothing is exempt: a cancelled sale day's whole subtree is
    # read-only, and G1 pre-empts every other gate.
    if sale_day is not None and sale_day.get("status") == "CANCELLED":
        fail("ERR_SALE_DAY_CANCELLED")

    # Rung 12 - G2.
    if lot is not None and lot.get("quarantine_hold") and endpoint not in G2_EXEMPT:
        fail("ERR_LOT_QUARANTINED")

    # Rung 13 - G3.
    if endpoint in G3_SCOPE and sale_day is not None \
            and sale_day.get("status") in ("BIDDING_CLOSED", "SETTLED"):
        fail("ERR_SALE_DAY_FROZEN")

    # Rung 14 - G4.
    if party is not None and party.get("status") == "SUSPENDED" \
            and endpoint not in G4_EXEMPT:
        fail("ERR_PARTY_SUSPENDED")

    # Rung 15 - G5.
    if endpoint in G5_SCOPE and settlement is not None \
            and settlement.get("status") == "RELEASED":
        fail("ERR_SETTLEMENT_RELEASED")
