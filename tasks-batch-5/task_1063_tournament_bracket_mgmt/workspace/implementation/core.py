"""Core: in-memory store, helpers, calculations, and bracket logic.

All state is process-local and starts empty on every boot. No seeding.
"""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    'ERR_UNAUTHENTICATED': 401,
    'ERR_UNAUTHORIZED': 403,
    'ERR_NOT_FOUND': 404,
    'ERR_INVALID_STATE': 409,
    'ERR_TOURNAMENT_NOT_IN_CHECKIN': 409,
    'ERR_CHECKIN_CLOSED': 409,
    'ERR_STATION_WRONG_VENUE': 409,
    'ERR_SOD_SELF_CONFIRM': 409,
    'ERR_SOD_CONFIRMER_RESOLVE': 409,
    'ERR_COMPETITOR_NOT_CHECKED_IN': 409,
    'ERR_TIE_NOT_ALLOWED': 422,
    'ERR_NOT_A_COMPETITOR': 403,
    'ERR_OUTSIDE_VENUE_HOURS': 422,
    'ERR_STATION_OVERLAP': 409,
    'ERR_CHANNEL_OVERLAP': 409,
    'ERR_MATCH_NOT_SCHEDULABLE_STREAM': 409,
    'ERR_TOURNAMENT_FULL': 409,
    'ERR_DUPLICATE_REGISTRATION': 409,
    'ERR_INSUFFICIENT_PARTICIPANTS': 409,
    'ERR_MATCHES_INCOMPLETE': 409,
    'ERR_DISPUTE_ALREADY_OPEN': 409,
    'ERR_MATCH_NOT_DISPUTABLE': 409,
    'ERR_PAYOUT_NOT_FINAL': 409,
    'ERR_STALE_MATCH_VERSION': 412,
    'ERR_STALE_TOURNAMENT_VERSION': 412,
    'ERR_INVALID_REQUEST': 422,
}

ALL_ROLES = {'Director', 'Referee', 'Player', 'Public'}

# Constants (from SCAFFOLD.yaml calculations)
MATCH_WIN_POINTS = 3
MATCH_LOSS_POINTS = 0
STATION_TURNOVER_MINUTES = 15
TAX_RATE_NO_ID = Decimal('0.24')
TAX_RATE_WITH_ID = Decimal('0.00')
PAYOUT_PCT = {
    1: [Decimal('1.00')],
    2: [Decimal('0.70'), Decimal('0.30')],
    3: [Decimal('0.50'), Decimal('0.30'), Decimal('0.20')],
    4: [Decimal('0.40'), Decimal('0.30'), Decimal('0.20'), Decimal('0.10')],
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (process-local, starts empty)
# ---------------------------------------------------------------------------
venues = {}
stations = {}
channels = {}
players = {}
tournaments = {}
registrations = {}
matches = {}
stream_assignments = {}
payouts = {}
disputes = {}

COLLECTIONS = {
    'Venue': venues,
    'Station': stations,
    'StreamChannel': channels,
    'Player': players,
    'Tournament': tournaments,
    'Registration': registrations,
    'Match': matches,
    'StreamAssignment': stream_assignments,
    'Payout': payouts,
    'Dispute': disputes,
}

_seq = 0
# Logical clock: startup default 2026-07-01T00:00:00Z
_clock = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    global _seq
    _seq += 1
    return _seq


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def wall_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(s):
    if s is None:
        raise ApiError('ERR_INVALID_REQUEST', 'invalid datetime')
    if isinstance(s, datetime):
        return s
    try:
        txt = str(s).strip()
        if txt.endswith('Z'):
            txt = txt[:-1] + '+00:00'
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise ApiError('ERR_INVALID_REQUEST', 'invalid datetime: %r' % s)


def round_half_up(dec):
    return int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity creation / mutation
# ---------------------------------------------------------------------------
def make_request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))


def create(kind, fields):
    now = wall_now_iso()
    e = dict(fields)
    e['id'] = str(uuid.uuid4())
    e['created_at'] = now
    e['updated_at'] = now
    e['version'] = 1
    e['_kind'] = kind
    e['_seq'] = next_seq()
    COLLECTIONS[kind][e['id']] = e
    return e


def touch(e):
    """A mutation of the resource: refresh updated_at and bump version."""
    e['updated_at'] = wall_now_iso()
    e['version'] = e.get('version', 1) + 1


def touch_nv(e):
    """Refresh updated_at only (derived-counter changes; no version bump)."""
    e['updated_at'] = wall_now_iso()


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith('_')}


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def bracket_participants(t):
    """Registrations that entered the bracket (seed assigned at generation)."""
    return [r for r in registrations.values()
            if r['tournament_id'] == t['id'] and r.get('seed') is not None]


def tournament_matches(t):
    return [m for m in matches.values() if m['tournament_id'] == t['id']]


def reg_player(reg):
    if reg is None:
        return None
    return players.get(reg.get('player_id'))


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def assign_seeds(t):
    method = t.get('seeding_method') or 'RATING'
    cands = [r for r in registrations.values()
             if r['tournament_id'] == t['id'] and r['status'] == 'CHECKED_IN']
    if method == 'RATING':
        cands.sort(key=lambda r: (-(reg_player(r) or {}).get('rating', 1000), r['_seq']))
    elif method == 'MANUAL':
        cands.sort(key=lambda r: ((r.get('seed_input') if r.get('seed_input') is not None else 0), r['_seq']))
    else:  # RANDOM_STABLE
        cands.sort(key=lambda r: r['_seq'])
    for i, r in enumerate(cands):
        r['seed'] = i + 1
        touch(r)
    return cands  # in seed order


# ---------------------------------------------------------------------------
# Bracket generation
# ---------------------------------------------------------------------------
def _next_pow2(n):
    b = 1
    while b < n:
        b *= 2
    return max(b, 2)


def _bracket_seed_order(B):
    seeds = [1, 2]
    while len(seeds) < B:
        m = len(seeds) * 2 + 1
        new = []
        for s in seeds:
            new.append(s)
            new.append(m - s)
        seeds = new
    return seeds


def _new_match(t, bracket, round_number, slot_index):
    return create('Match', {
        'tournament_id': t['id'],
        'bracket': bracket,
        'round_number': round_number,
        'slot_index': slot_index,
        'home_registration_id': None,
        'away_registration_id': None,
        'home_score': 0,
        'away_score': 0,
        'winner_registration_id': None,
        'loser_registration_id': None,
        'next_match_id': None,
        'next_slot': None,
        'loser_next_match_id': None,
        'loser_next_slot': None,
        'status': 'PENDING',
        'station_id': None,
        'scheduled_start': None,
        'scheduled_end': None,
        'reported_by_user_id': None,
        'confirmed_by_user_id': None,
    })


def _set_slot(m, slot, reg_id):
    if slot == 'HOME':
        m['home_registration_id'] = reg_id
    else:
        m['away_registration_id'] = reg_id


def _build_single_elim(t, seeded, bracket='MAIN'):
    """seeded: list of registrations in seed order (seed==index+1). Returns grid."""
    N = len(seeded)
    B = _next_pow2(N)
    rounds = 0
    x = B
    while x > 1:
        x //= 2
        rounds += 1
    so = _bracket_seed_order(B)
    seed_to_reg = {r['seed']: r for r in seeded}
    grid = {}
    for r in range(1, rounds + 1):
        count = B // (2 ** r)
        for idx in range(count):
            grid[(r, idx)] = _new_match(t, bracket, r, idx)
    # wire winner edges
    for r in range(1, rounds):
        count = B // (2 ** r)
        for idx in range(count):
            m = grid[(r, idx)]
            nxt = grid[(r + 1, idx // 2)]
            m['next_match_id'] = nxt['id']
            m['next_slot'] = 'HOME' if idx % 2 == 0 else 'AWAY'
    # assign round-1 competitors
    for idx in range(B // 2):
        s_home = so[2 * idx]
        s_away = so[2 * idx + 1]
        m = grid[(1, idx)]
        rh = seed_to_reg.get(s_home)
        ra = seed_to_reg.get(s_away)
        m['home_registration_id'] = rh['id'] if rh else None
        m['away_registration_id'] = ra['id'] if ra else None
    # bye pass: a slot whose seed > N is a bye; the real competitor auto-advances
    for idx in range(B // 2):
        m = grid.get((1, idx))
        if m is None:
            continue
        s_home = so[2 * idx]
        s_away = so[2 * idx + 1]
        home_bye = s_home > N
        away_bye = s_away > N
        real = None
        if home_bye and not away_bye:
            real = m['away_registration_id']
        elif away_bye and not home_bye:
            real = m['home_registration_id']
        if real is not None:
            # advance the real competitor into the downstream slot; drop this match
            if m['next_match_id']:
                nm = matches[m['next_match_id']]
                _set_slot(nm, m['next_slot'], real)
            del grid[(1, idx)]
            matches.pop(m['id'], None)
    return grid


def _build_double_elim(t, seeded):
    N = len(seeded)
    B = _next_pow2(N)
    k = 0
    x = B
    while x > 1:
        x //= 2
        k += 1
    # winners bracket (like single elim, but bracket WINNERS)
    wb = _build_single_elim(t, seeded, bracket='WINNERS')
    # grand final
    gf = _new_match(t, 'GRAND_FINAL', 1, 0)
    # losers bracket rounds
    lb = {}
    if k == 1:
        # 2-player: WB final loser goes straight to GF AWAY
        wbf = wb.get((1, 0))
        if wbf is not None:
            wbf['next_match_id'] = gf['id']
            wbf['next_slot'] = 'HOME'
            wbf['loser_next_match_id'] = gf['id']
            wbf['loser_next_slot'] = 'AWAY'
        return
    # create LB matches
    for j in range(1, k):
        n = B // (2 ** (j + 1))
        for idx in range(n):
            lb[(2 * j - 1, idx)] = _new_match(t, 'LOSERS', 2 * j - 1, idx)  # minor
        for idx in range(n):
            lb[(2 * j, idx)] = _new_match(t, 'LOSERS', 2 * j, idx)  # major
    # wire WB winner edges already set by _build_single_elim (within WINNERS bracket)
    # WB final -> GF HOME
    wbf = wb.get((k, 0))
    if wbf is not None:
        wbf['next_match_id'] = gf['id']
        wbf['next_slot'] = 'HOME'
    # WB round-1 losers -> LB minor round 1
    for idx in range(B // 2):
        m = wb.get((1, idx))
        if m is None:
            continue
        m['loser_next_match_id'] = lb[(1, idx // 2)]['id']
        m['loser_next_slot'] = 'HOME' if idx % 2 == 0 else 'AWAY'
    # WB round (j+1) losers -> LB major round 2j  (j = 1..k-1)
    for j in range(1, k):
        wb_round = j + 1
        n = B // (2 ** (j + 1))
        for idx in range(n):
            m = wb.get((wb_round, idx))
            if m is None:
                continue
            m['loser_next_match_id'] = lb[(2 * j, idx)]['id']
            m['loser_next_slot'] = 'AWAY'
    # LB minor round (2j-1) winners -> LB major round (2j) HOME same idx
    for j in range(1, k):
        n = B // (2 ** (j + 1))
        for idx in range(n):
            mm = lb[(2 * j - 1, idx)]
            mm['next_match_id'] = lb[(2 * j, idx)]['id']
            mm['next_slot'] = 'HOME'
    # LB major round (2j) winners -> next minor round (2j+1) or GF
    for j in range(1, k):
        n = B // (2 ** (j + 1))
        for idx in range(n):
            mm = lb[(2 * j, idx)]
            if j < k - 1:
                mm['next_match_id'] = lb[(2 * (j + 1) - 1, idx // 2)]['id']
                mm['next_slot'] = 'HOME' if idx % 2 == 0 else 'AWAY'
            else:
                mm['next_match_id'] = gf['id']
                mm['next_slot'] = 'AWAY'


def _build_round_robin(t, seeded):
    N = len(seeded)
    seeds = [r['seed'] for r in seeded]  # 1..N
    seed_to_reg = {r['seed']: r for r in seeded}
    arr = list(seeds)
    if N % 2 == 1:
        arr.append(None)  # bye placeholder
    n = len(arr)
    half = n // 2
    rounds = n - 1
    slot_counter = {}
    for r in range(rounds):
        for i in range(half):
            a = arr[i]
            b = arr[n - 1 - i]
            if a is None or b is None:
                continue
            home_seed = min(a, b)
            away_seed = max(a, b)
            rn = r + 1
            si = slot_counter.get(rn, 0)
            slot_counter[rn] = si + 1
            m = _new_match(t, 'MAIN', rn, si)
            m['home_registration_id'] = seed_to_reg[home_seed]['id']
            m['away_registration_id'] = seed_to_reg[away_seed]['id']
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]


def _build_swiss(t, seeded):
    N = len(seeded)
    half = N // 2
    top = seeded[:half]
    bottom = seeded[half:]
    for i in range(half):
        home = top[i]
        away = bottom[i]
        # lower seed is home
        if home['seed'] > away['seed']:
            home, away = away, home
        m = _new_match(t, 'MAIN', 1, i)
        m['home_registration_id'] = home['id']
        m['away_registration_id'] = away['id']
    t['num_swiss_rounds_played'] = 1


def generate_bracket_matches(t, seeded):
    fmt = t['format']
    if fmt == 'SINGLE_ELIM':
        _build_single_elim(t, seeded, bracket='MAIN')
    elif fmt == 'DOUBLE_ELIM':
        _build_double_elim(t, seeded)
    elif fmt == 'ROUND_ROBIN':
        _build_round_robin(t, seeded)
    elif fmt == 'SWISS':
        _build_swiss(t, seeded)


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------
def _match_stats(t):
    parts = bracket_participants(t)
    stats = {r['id']: {
        'registration_id': r['id'],
        'player_id': r['player_id'],
        'seed': r.get('seed'),
        'wins': 0, 'losses': 0, 'match_points': 0,
        'games_for': 0, 'games_against': 0, 'game_diff': 0,
        '_seq': r['_seq'],
    } for r in parts}
    for m in tournament_matches(t):
        if m['status'] != 'CONFIRMED':
            continue
        h = m['home_registration_id']
        a = m['away_registration_id']
        hs = m.get('home_score') or 0
        as_ = m.get('away_score') or 0
        if h in stats:
            stats[h]['games_for'] += hs
            stats[h]['games_against'] += as_
        if a in stats:
            stats[a]['games_for'] += as_
            stats[a]['games_against'] += hs
        w = m.get('winner_registration_id')
        l = m.get('loser_registration_id')
        if w in stats:
            stats[w]['wins'] += 1
        if l in stats:
            stats[l]['losses'] += 1
    for s in stats.values():
        s['match_points'] = s['wins'] * MATCH_WIN_POINTS + s['losses'] * MATCH_LOSS_POINTS
        s['game_diff'] = s['games_for'] - s['games_against']
    return stats


def _rank_key(t):
    method = t.get('tiebreak_method') or 'SEED'

    def seed_val(s):
        return s['seed'] if s['seed'] is not None else 10 ** 9

    if method == 'GAME_DIFF':
        def key(s):
            return (-s['match_points'], -s['game_diff'], seed_val(s), s['_seq'])
    else:  # SEED
        def key(s):
            return (-s['match_points'], seed_val(s), s['_seq'])
    return key


def standings_rows(t):
    stats = _match_stats(t)
    ordered = sorted(stats.values(), key=_rank_key(t))
    rows = []
    for i, s in enumerate(ordered):
        row = {k: v for k, v in s.items() if not k.startswith('_')}
        row['rank'] = i + 1
        rows.append(row)
    return rows


def standings_order_regs(t):
    stats = _match_stats(t)
    ordered = sorted(stats.values(), key=_rank_key(t))
    return [registrations[s['registration_id']] for s in ordered]


# ---------------------------------------------------------------------------
# Payouts / tax
# ---------------------------------------------------------------------------
def _compute_grosses(prize, places):
    row = PAYOUT_PCT[places]
    grosses = []
    for i in range(places):
        grosses.append(round_half_up(Decimal(prize) * row[i]))
    remainder = prize - sum(grosses)
    grosses[0] += remainder
    return grosses


def _create_payout(t, placement, variant, registration_id, gross):
    reg = registrations.get(registration_id) if registration_id else None
    player = reg_player(reg)
    tax_provided = bool(player['tax_id_provided']) if player else False
    rate = TAX_RATE_WITH_ID if tax_provided else TAX_RATE_NO_ID
    tax = round_half_up(Decimal(gross) * rate)
    net = gross - tax
    return create('Payout', {
        'tournament_id': t['id'],
        'registration_id': registration_id,
        'placement': placement,
        'variant': variant,
        'gross_amount_cents': gross,
        'tax_withheld_cents': tax,
        'net_amount_cents': net,
        'status': 'PENDING',
    })


def _recompute_unallocated(t):
    total = 0
    for p in payouts.values():
        if p['tournament_id'] == t['id'] and p['status'] != 'VOID':
            total += p['gross_amount_cents']
    t['unallocated_prize_cents'] = t['prize_pool_cents'] - total


def run_provisional_payout(t):
    places = t.get('paid_places') or 2
    prize = t['prize_pool_cents']
    grosses = _compute_grosses(prize, places)
    seed_to_reg = {r['seed']: r for r in bracket_participants(t)}
    for p in range(1, places + 1):
        reg = seed_to_reg.get(p)
        _create_payout(t, p, 'PROVISIONAL', reg['id'] if reg else None, grosses[p - 1])
    t['payout_variant'] = 'PROVISIONAL'
    _recompute_unallocated(t)


def void_provisional_payouts(t):
    for p in payouts.values():
        if p['tournament_id'] == t['id'] and p['variant'] == 'PROVISIONAL' and p['status'] != 'VOID':
            p['status'] = 'VOID'
            touch(p)
    _recompute_unallocated(t)


def run_final_payout(t):
    void_provisional_payouts(t)
    places = t.get('paid_places') or 2
    prize = t['prize_pool_cents']
    grosses = _compute_grosses(prize, places)
    place_to_reg = {}
    for r in bracket_participants(t):
        if r.get('final_placement') is not None:
            place_to_reg[r['final_placement']] = r
    for p in range(1, places + 1):
        reg = place_to_reg.get(p)
        _create_payout(t, p, 'FINAL', reg['id'] if reg else None, grosses[p - 1])
    t['payout_variant'] = 'FINAL'
    _recompute_unallocated(t)


# ---------------------------------------------------------------------------
# Final placement
# ---------------------------------------------------------------------------
def _elim_rank(m):
    b = m['bracket']
    if b == 'GRAND_FINAL':
        return 100000
    if b == 'LOSERS':
        return 1000 + m['round_number']
    return m['round_number']


def _final_match_winner(t):
    fmt = t['format']
    finals = []
    for m in tournament_matches(t):
        if fmt == 'DOUBLE_ELIM':
            if m['bracket'] == 'GRAND_FINAL':
                finals.append(m)
        else:
            if m['bracket'] == 'MAIN' and m['next_match_id'] is None:
                finals.append(m)
    finals = [m for m in finals if m['status'] == 'CONFIRMED' and m.get('winner_registration_id')]
    if not finals:
        return None
    finals.sort(key=lambda m: m['round_number'])
    return finals[-1].get('winner_registration_id')


def assign_final_placements(t):
    fmt = t['format']
    parts = bracket_participants(t)
    if fmt in ('ROUND_ROBIN', 'SWISS'):
        order = standings_order_regs(t)
        for i, r in enumerate(order):
            r['final_placement'] = i + 1
            touch(r)
        champ = order[0] if order else None
    else:
        champ_id = _final_match_winner(t)
        champ = registrations.get(champ_id) if champ_id else None
        if champ is None:
            order = standings_order_regs(t)
            champ = order[0] if order else None
        others = [r for r in parts if champ is None or r['id'] != champ['id']]
        stats = _match_stats(t)
        method = t.get('tiebreak_method') or 'SEED'

        def seed_val(r):
            return r['seed'] if r.get('seed') is not None else 10 ** 9

        def key(r):
            s = stats.get(r['id'], {})
            er = r.get('_elim_rank', 0)
            if method == 'GAME_DIFF':
                return (-er, -s.get('game_diff', 0), seed_val(r), r['_seq'])
            return (-er, seed_val(r), r['_seq'])
        others.sort(key=key)
        if champ is not None:
            champ['final_placement'] = 1
            touch(champ)
        for i, r in enumerate(others):
            r['final_placement'] = i + 2
            touch(r)
    if champ is not None:
        champ['status'] = 'CHAMPION'
        champ['final_placement'] = 1
        touch(champ)


# ---------------------------------------------------------------------------
# Match cascades (confirm / void)
# ---------------------------------------------------------------------------
def confirm_cascade(t, m):
    if (m.get('home_score') or 0) > (m.get('away_score') or 0):
        winner = m['home_registration_id']
        loser = m['away_registration_id']
    else:
        winner = m['away_registration_id']
        loser = m['home_registration_id']
    m['winner_registration_id'] = winner
    m['loser_registration_id'] = loser
    # advance winner
    if m['next_match_id']:
        nm = matches.get(m['next_match_id'])
        if nm is not None:
            _set_slot(nm, m['next_slot'], winner)
            touch(nm)
    # loser handling.
    # SWISS/ROUND_ROBIN keep the loser alive (a player plays every scheduled
    # match; §3.8 has round-robin/Swiss finish via standings order, which is
    # only reachable if losers are not eliminated mid-play). Elimination
    # formats: DOUBLE_ELIM winners-bracket losses drop into the losers bracket
    # (loser_next set); all other elimination losses eliminate the loser.
    fmt = t['format']
    if fmt in ('SWISS', 'ROUND_ROBIN'):
        pass
    elif m['loser_next_match_id']:
        nm = matches.get(m['loser_next_match_id'])
        if nm is not None:
            _set_slot(nm, m['loser_next_slot'], loser)
            touch(nm)
    else:
        reg = registrations.get(loser)
        if reg is not None and reg['status'] == 'CHECKED_IN':
            reg['status'] = 'ELIMINATED'
            reg['eliminated'] = True
            reg['_elim_rank'] = _elim_rank(m)
            touch(reg)
            t['alive_count'] = t.get('alive_count', 0) - 1
            t['eliminated_count'] = t.get('eliminated_count', 0) + 1
            touch_nv(t)


def void_cascade(t, m, was_confirmed):
    if was_confirmed:
        winner = m.get('winner_registration_id')
        loser = m.get('loser_registration_id')
        # pull winner back out of next_match
        if m['next_match_id'] and winner:
            nm = matches.get(m['next_match_id'])
            if nm is not None:
                f = 'home_registration_id' if m['next_slot'] == 'HOME' else 'away_registration_id'
                if nm.get(f) == winner:
                    nm[f] = None
                    if nm['status'] == 'SCHEDULED':
                        nm['status'] = 'PENDING'
                        nm['station_id'] = None
                        nm['scheduled_start'] = None
                        nm['scheduled_end'] = None
                    touch(nm)
        fmt = t['format']
        if fmt in ('SWISS', 'ROUND_ROBIN'):
            pass
        elif m['loser_next_match_id'] and loser:
            nm = matches.get(m['loser_next_match_id'])
            if nm is not None:
                f = 'home_registration_id' if m['loser_next_slot'] == 'HOME' else 'away_registration_id'
                if nm.get(f) == loser:
                    nm[f] = None
                    if nm['status'] == 'SCHEDULED':
                        nm['status'] = 'PENDING'
                        nm['station_id'] = None
                        nm['scheduled_start'] = None
                        nm['scheduled_end'] = None
                    touch(nm)
        else:
            reg = registrations.get(loser)
            if reg is not None and reg['status'] == 'ELIMINATED':
                reg['status'] = 'CHECKED_IN'
                reg['eliminated'] = False
                reg['_elim_rank'] = 0
                touch(reg)
                t['alive_count'] = t.get('alive_count', 0) + 1
                t['eliminated_count'] = t.get('eliminated_count', 0) - 1
                touch_nv(t)
        m['winner_registration_id'] = None
        m['loser_registration_id'] = None
    m['home_score'] = 0
    m['away_score'] = 0
    m['status'] = 'VOIDED'
    # cancel scheduled stream assignments for this match
    for sa in stream_assignments.values():
        if sa['match_id'] == m['id'] and sa['status'] == 'SCHEDULED':
            sa['status'] = 'CANCELLED'
            touch(sa)
    touch(m)


# ---------------------------------------------------------------------------
# Overlap tests
# ---------------------------------------------------------------------------
def station_conflict(station_id, start, end, exclude_match_id):
    buf = timedelta(minutes=STATION_TURNOVER_MINUTES)
    for m in matches.values():
        if m['id'] == exclude_match_id:
            continue
        if m.get('station_id') != station_id:
            continue
        if m['status'] not in ('SCHEDULED', 'REPORTED', 'CONFIRMED', 'DISPUTED'):
            continue
        if not m.get('scheduled_start') or not m.get('scheduled_end'):
            continue
        m2s = parse_dt(m['scheduled_start'])
        m2e = parse_dt(m['scheduled_end'])
        if start < (m2e + buf) and m2s < (end + buf):
            return True
    return False


def stream_conflict(channel_id, start, end, exclude_id):
    for sa in stream_assignments.values():
        if sa['id'] == exclude_id:
            continue
        if sa['channel_id'] != channel_id:
            continue
        if sa['status'] != 'SCHEDULED':
            continue
        a2s = parse_dt(sa['start_at'])
        a2e = parse_dt(sa['end_at'])
        if start < a2e and a2s < end:
            return True
    return False
