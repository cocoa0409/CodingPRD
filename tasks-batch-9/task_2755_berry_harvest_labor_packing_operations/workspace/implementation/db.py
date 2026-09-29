"""In-memory store. Starts completely empty on every process boot: no seeding,
no preloaded rows, no persistence of any kind."""

import threading

import config
import util

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# tables — plain dicts keyed by the server-minted UUID
# ---------------------------------------------------------------------------
blocks = {}
water_tests = {}
crews = {}
pickers = {}
harvest_windows = {}
pick_sessions = {}
payroll_runs = {}
cooling_tunnels = {}
fruit_lots = {}
buyer_commitments = {}
lot_allocations = {}

TABLES = {
    "block": blocks,
    "water_test": water_tests,
    "crew": crews,
    "picker": pickers,
    "harvest_window": harvest_windows,
    "pick_session": pick_sessions,
    "payroll_run": payroll_runs,
    "cooling_tunnel": cooling_tunnels,
    "fruit_lot": fruit_lots,
    "buyer_commitment": buyer_commitments,
    "lot_allocation": lot_allocations,
}

# ---------------------------------------------------------------------------
# the logical harvest clock (PRD §2.5)
# ---------------------------------------------------------------------------
_clock = {
    "raw": config.CLOCK_DEFAULT,
    "dt": util.parse_instant(config.CLOCK_DEFAULT),
}

_counter = {"n": 0}


def next_seq():
    _counter["n"] += 1
    return _counter["n"]


def clock_instant():
    return _clock["dt"]


def clock_date():
    return _clock["dt"].date()


def clock_raw():
    return _clock["raw"]


def set_clock(raw, parsed):
    _clock["raw"] = raw
    _clock["dt"] = parsed


# ---------------------------------------------------------------------------
# record construction and mutation bookkeeping
# ---------------------------------------------------------------------------
def new_record(with_audit=True):
    """A fresh record carrying id, created_at and (unless append-only) the
    updated_at / version audit pair."""
    now = util.instant_str(util.now_instant())
    rec = {"id": util.new_uuid(), "created_at": now}
    if with_audit:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version by exactly 1."""
    if rec is None:
        return None
    rec["updated_at"] = util.instant_str(util.now_instant())
    rec["version"] = int(rec.get("version", 0)) + 1
    return rec


def by_created(records):
    """Order by created_at ascending, tie-broken by insertion sequence."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def seq_of(rec):
    return rec["_seq"]


# ---------------------------------------------------------------------------
# common lookups
# ---------------------------------------------------------------------------
def all_of(table):
    return by_created(list(table.values()))


def windows_of_block(block_id):
    return by_created([w for w in harvest_windows.values() if w["block_id"] == block_id])


def windows_of_crew(crew_id):
    return by_created([w for w in harvest_windows.values() if w["crew_id"] == crew_id])


def sessions_of_window(window_id):
    return by_created(
        [s for s in pick_sessions.values() if s["harvest_window_id"] == window_id]
    )


def sessions_of_picker(picker_id):
    return by_created([s for s in pick_sessions.values() if s["picker_id"] == picker_id])


def pickers_of_crew(crew_id):
    return by_created([p for p in pickers.values() if p["crew_id"] == crew_id])


def sessions_of_crew(crew_id):
    ids = {p["id"] for p in pickers.values() if p["crew_id"] == crew_id}
    return by_created([s for s in pick_sessions.values() if s["picker_id"] in ids])


def sessions_of_run(run_id):
    return by_created(
        [s for s in pick_sessions.values() if s.get("payroll_run_id") == run_id]
    )


def runs_of_crew(crew_id):
    return by_created([r for r in payroll_runs.values() if r["crew_id"] == crew_id])


def lots_of_block(block_id):
    return by_created([l for l in fruit_lots.values() if l["block_id"] == block_id])


def lots_of_window(window_id):
    return by_created(
        [l for l in fruit_lots.values() if l["harvest_window_id"] == window_id]
    )


def lots_of_tunnel(tunnel_id):
    return by_created(
        [l for l in fruit_lots.values() if l.get("cooling_tunnel_id") == tunnel_id]
    )


def allocations_of_lot(lot_id):
    return by_created(
        [a for a in lot_allocations.values() if a["fruit_lot_id"] == lot_id]
    )


def allocations_of_commitment(commitment_id):
    return by_created(
        [
            a
            for a in lot_allocations.values()
            if a["buyer_commitment_id"] == commitment_id
        ]
    )


def water_tests_of_block(block_id):
    """Ordered (sample_date ASC, created_at ASC) — the geometric-mean ordering."""
    rows = [w for w in water_tests.values() if w["block_id"] == block_id]
    return sorted(rows, key=lambda r: (r["_sample_date"], r["created_at"], r["_seq"]))


def window_of_session(session):
    return harvest_windows.get(session["harvest_window_id"])


def crew_of_session(session):
    window = window_of_session(session)
    if window is None:
        picker = pickers.get(session["picker_id"])
        return crews.get(picker["crew_id"]) if picker else None
    return crews.get(window["crew_id"])
