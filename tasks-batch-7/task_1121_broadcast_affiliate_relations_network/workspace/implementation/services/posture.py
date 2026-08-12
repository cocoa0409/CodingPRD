"""Station posture and Network posture derivation per PRD §2.9."""
from db import store


DARK_THRESHOLD_MINUTES = 240
DEFICIENT_RATE_THRESHOLD = 0.85
LOCKDOWN_FAILED_COUNT = 3


def recompute_station_posture(station: dict):
    """Apply §2.9 station posture derivation.

    Precedence: DARK > CLEARANCE_DEFICIENT > CLEARANCE_OK.
    """
    old = station.get("posture")
    if station.get("monthly_outage_minutes_current_period", 0) > DARK_THRESHOLD_MINUTES:
        new = "DARK"
    else:
        rate = station.get("clearance_rate_current_period")
        if rate is not None and rate < DEFICIENT_RATE_THRESHOLD:
            new = "CLEARANCE_DEFICIENT"
        else:
            # check for any VALIDATED exclusivity claim where station is respondent
            has_validated = False
            for c in store.exclusivity_claims.values():
                if (
                    c.get("respondent_station_id") == station["id"]
                    and c.get("status") == "VALIDATED"
                ):
                    has_validated = True
                    break
            if has_validated:
                new = "CLEARANCE_DEFICIENT"
            else:
                new = "CLEARANCE_OK"
    if new != old:
        station["posture"] = new
        # bump version only if actually changed (PRD: mutation increments version)
        # However posture derivation is itself a mutation; do it once.
    return station["posture"]


def recompute_network_posture(network: dict):
    """Apply §2.9 network posture derivation.

    Precedence: SWEEP_LOCKDOWN > DISPUTE_FREEZE > NORMAL.
    """
    # Count FAILED compliance reports against this network's stations in current period
    current_period = network.get("current_period_index", 0)
    failed_count = 0
    for c in store.compliance_reports.values():
        if c.get("status") != "FAILED":
            continue
        if c.get("period_index") != current_period:
            continue
        # resolve station -> network
        st = store.stations.get(c.get("station_id"))
        if st and st.get("network_id") == network["id"]:
            failed_count += 1
    if failed_count >= LOCKDOWN_FAILED_COUNT:
        network["posture"] = "SWEEP_LOCKDOWN"
        return network["posture"]
    # DISPUTE_FREEZE: any PROPOSED RenewalOffer on agreement whose station's group is MAJOR
    for offer in store.renewal_offers.values():
        if offer.get("status") != "PROPOSED":
            continue
        agreement = store.agreements.get(offer.get("agreement_id"))
        if not agreement:
            continue
        if agreement.get("network_id") != network["id"]:
            continue
        st = store.stations.get(agreement.get("station_id"))
        if not st:
            continue
        sg = store.station_groups.get(st.get("station_group_id"))
        if sg and sg.get("leverage_tier") == "MAJOR":
            network["posture"] = "DISPUTE_FREEZE"
            return network["posture"]
    network["posture"] = "NORMAL"
    return network["posture"]
