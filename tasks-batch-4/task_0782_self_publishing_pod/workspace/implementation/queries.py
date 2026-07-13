"""Cross-aggregate query + rollup helpers."""
from store import db, parse_dt


def publisher_id_of_format(fmt):
    if not fmt:
        return None
    title = db.titles.get(fmt.get("title_id"))
    return title.get("publisher_id") if title else None


def publisher_id_of_sales_line(line):
    return publisher_id_of_format(db.formats.get(line.get("format_id")))


def sales_lines_of_publisher(pub_id):
    return [l for l in db.sales.values()
            if publisher_id_of_sales_line(l) == pub_id]


def reconcile_publisher_reserve(pub_id):
    """Publisher.reserve_held_cents = sum of per-line reserve over the publisher's
    sales lines (SALE positive, RETURN negative)."""
    pub = db.publishers.get(pub_id)
    if not pub:
        return
    total = sum(l.get("reserve_held_cents", 0) for l in sales_lines_of_publisher(pub_id))
    pub["reserve_held_cents"] = total


def compute_reserve_held(pub_id):
    return sum(l.get("reserve_held_cents", 0) for l in sales_lines_of_publisher(pub_id))


def compute_lifetime_paid(pub_id):
    return sum(s.get("net_payable_cents", 0) for s in db.statements.values()
               if s.get("publisher_id") == pub_id and s.get("status") == "PAID")


def _in_period(line, start_dt, end_dt):
    sd = parse_dt(line.get("sale_date"))
    if sd is None:
        return False
    return start_dt <= sd <= end_dt


def provisional_net(statement):
    """Forward-looking estimate read while ACCRUING: gross - reserve over the
    publisher's PENDING sales lines whose sale_date falls in the (inclusive) period."""
    if statement.get("status") != "ACCRUING":
        # settled statements keep the value locked at issue time
        return statement.get("provisional_net_cents", 0)
    start_dt = parse_dt(statement.get("period_start"))
    end_dt = parse_dt(statement.get("period_end"))
    pub_id = statement.get("publisher_id")
    gross = 0
    reserve = 0
    for l in sales_lines_of_publisher(pub_id):
        if l.get("status") == "PENDING" and _in_period(l, start_dt, end_dt):
            gross += l.get("gross_royalty_cents", 0)
            reserve += l.get("reserve_held_cents", 0)
    return gross - reserve


def prior_issued_statement(pub_id, this_start_dt):
    """The ISSUED statement of this publisher whose period_start is the greatest
    value strictly less than this_start_dt (immediately-prior period)."""
    best = None
    best_dt = None
    for s in db.statements.values():
        if s.get("publisher_id") != pub_id:
            continue
        if s.get("status") not in ("ISSUED", "PAID"):
            continue
        sdt = parse_dt(s.get("period_start"))
        if sdt is None or not (sdt < this_start_dt):
            continue
        if best_dt is None or sdt > best_dt:
            best_dt = sdt
            best = s
    return best


def select_price_for_sale(format_id, channel_id, territory, sale_dt):
    """Active ChannelPrice whose window contains sale_dt: effective_from <= sale_dt
    AND (effective_to is null OR sale_dt < effective_to). Tie-break: latest
    effective_from, then earliest created_at (_seq)."""
    candidates = []
    for p in db.prices.values():
        if p.get("status") != "ACTIVE":
            continue
        if (p.get("format_id") != format_id or p.get("channel_id") != channel_id
                or p.get("territory") != territory):
            continue
        ef = parse_dt(p.get("effective_from"))
        et = parse_dt(p.get("effective_to"))
        if ef is None or ef > sale_dt:
            continue
        if et is not None and not (sale_dt < et):
            continue
        candidates.append((ef, p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], -t[1].get("_seq", 0)), reverse=True)
    # latest effective_from first; among equal effective_from, smallest _seq first
    return candidates[0][1]
