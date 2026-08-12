"""Time-triggered transitions fired on clock set / period advance."""
from datetime import timedelta

from db import store, parse_iso, format_iso, now_iso
from services.posture import recompute_network_posture, recompute_station_posture


def fire_time_transitions(network: dict):
    """Fire all time-triggered transitions on the given network given current_utc.

    - Agreement ACTIVE -> EXPIRING when current_utc >= term_end - 90 days AND < term_end
    - Agreement RENEWAL_NEGOTIATION -> LAPSED when current_utc >= term_end AND no
      RenewalOffer in PROPOSED|COUNTERED
    """
    current_dt = parse_iso(network["current_utc"])
    for agreement in store.agreements.values():
        if agreement.get("network_id") != network["id"]:
            continue
        status = agreement.get("status")
        term_end = parse_iso(agreement["term_end_utc"])
        if status == "ACTIVE":
            threshold = term_end - timedelta(days=90)
            if current_dt >= threshold and current_dt < term_end:
                agreement["status"] = "EXPIRING"
                agreement["updated_at"] = now_iso()
                agreement["version"] = agreement.get("version", 1) + 1
        if agreement.get("status") == "RENEWAL_NEGOTIATION":
            if current_dt >= term_end:
                # check no PROPOSED|COUNTERED offers
                has_open = False
                for offer in store.renewal_offers.values():
                    if offer.get("agreement_id") != agreement["id"]:
                        continue
                    if offer.get("status") in ("PROPOSED", "COUNTERED"):
                        has_open = True
                        break
                if not has_open:
                    agreement["status"] = "LAPSED"
                    agreement["updated_at"] = now_iso()
                    agreement["version"] = agreement.get("version", 1) + 1
                    # clear territory exclusivity for station's DMA
                    station = store.stations.get(agreement.get("station_id"))
                    if station:
                        for terr in store.territories.values():
                            if (
                                terr.get("network_id") == network["id"]
                                and terr.get("dma_code") == station.get("dma_code")
                            ):
                                if terr.get("exclusivity_holder_station_id") == station["id"]:
                                    terr["exclusivity_holder_station_id"] = None
                                    terr["updated_at"] = now_iso()
                        recompute_station_posture(station)


def advance_period(network: dict):
    """Advance network.current_period_index by 1, with cascading effects."""
    network["current_period_index"] = network.get("current_period_index", 0) + 1
    new_period = network["current_period_index"]
    # Reset station outage counters and recompute station posture
    for station in store.stations.values():
        if station.get("network_id") != network["id"]:
            continue
        station["monthly_outage_minutes_current_period"] = 0
        station["updated_at"] = now_iso()
        recompute_station_posture(station)
    # Expire CLAIMED avail allocations with period_index < new period
    for alloc in store.avail_allocations.values():
        if alloc.get("status") != "CLAIMED":
            continue
        station = store.stations.get(alloc.get("station_id"))
        if station is None or station.get("network_id") != network["id"]:
            continue
        if alloc.get("period_index") is None:
            continue
        if alloc["period_index"] < new_period:
            alloc["status"] = "EXPIRED"
            alloc["updated_at"] = now_iso()
    recompute_network_posture(network)
