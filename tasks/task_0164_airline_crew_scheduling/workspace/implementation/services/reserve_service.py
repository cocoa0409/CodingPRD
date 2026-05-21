"""Reserve selection algorithm."""
from clock import get_now, parse_iso
import store
from services import faa_service


def select_reserve(pairing, assigned_rank_slot):
    """Run reserve_selection_calc. Returns the eligible ReservePool row or None.

    Eligibility (all must hold):
      - ReservePool.state == AVAILABLE
      - now in [standby_start_at, standby_end_at) — start inclusive, end exclusive
      - CrewMember.rank matches the vacated assigned_rank_slot
      - CrewMember.base_airport == Pairing.base_airport
      - faa_duty_rest_check passes for the candidate against the Pairing
    Ranking key (ascending):
      - cumulative_block_minutes_30d (least-used first)
      - tie 1: union_seniority_number
      - tie 2: CrewMember.created_at
    """
    now = get_now()
    candidates = []
    for rp in store.reserve_pool.values():
        if rp.get("state") != "AVAILABLE":
            continue
        sstart = parse_iso(rp["standby_start_at"])
        send = parse_iso(rp["standby_end_at"])
        if not (sstart <= now < send):
            continue
        crew = store.crew_members.get(rp["crew_member_id"])
        if not crew:
            continue
        if crew.get("status") != "ACTIVE":
            continue
        if crew.get("rank") != assigned_rank_slot:
            continue
        if crew.get("base_airport") != pairing.get("base_airport"):
            continue
        # FAA check (silent)
        err = faa_service.faa_duty_rest_check(crew, pairing, raise_on_fail=False)
        if err is not None:
            continue
        candidates.append((rp, crew))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: (
        pair[1].get("cumulative_block_minutes_30d", 0),
        pair[1].get("union_seniority_number", 0),
        pair[1].get("created_at", ""),
    ))
    return candidates[0]
