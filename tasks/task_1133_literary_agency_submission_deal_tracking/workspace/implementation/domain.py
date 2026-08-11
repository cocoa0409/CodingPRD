"""Domain logic: calculations, derived fields, cascades, period sweeps."""
from decimal import Decimal, ROUND_FLOOR

from core import DB, touch

OPEN_SLUSH = ("RECEIVED", "IN_REVIEW")
LIVE_OFFER = ("RECEIVED", "UNDER_NEGOTIATION")
LIVE_SUBMISSION = ("QUEUED", "SENT", "UNDER_CONSIDERATION", "OFFER_EXTENDED")
AUDIT_TOLERANCE_CENTS = 500

GENRE_W = {"FICTION": 40, "NONFICTION": 30, "YA": 25, "MEMOIR": 10}
AUTHOR_W = {"CLIENT": 20, "PROSPECT": 10, "FORMER": 0}
AUCTION_CONST = {"FRONTLIST": (100000, 2500000), "BACKLIST": (60000, 1000000)}
ESCALATOR = {"NET": Decimal("0.025"), "RETAIL": Decimal("0.0125")}
TIER_HARDCOVER = 5000
TIER_TRADE = 7500


def dec(x):
    return Decimal(str(x))


def floor_dec(d):
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------- derived fields ----
def open_slush_count(agency_id):
    return sum(1 for q in DB["query_letters"].values()
               if q["agency_id"] == agency_id and q["status"] in OPEN_SLUSH)


def refresh_posture(agency):
    posture = ("INTAKE_PAUSED"
               if open_slush_count(agency["id"]) >= agency["slush_capacity"]
               else "NORMAL")
    if posture != agency["posture"]:
        agency["posture"] = posture
        touch(agency)


def recompute_open_count(agent_id):
    if not agent_id:
        return
    agent = DB["agents"].get(agent_id)
    if agent is None:
        return
    n = sum(1 for q in DB["query_letters"].values()
            if q.get("assigned_agent_id") == agent_id and q["status"] in OPEN_SLUSH)
    if n != agent["open_query_count"]:
        agent["open_query_count"] = n
        touch(agent)


def author_to_client(author_id):
    author = DB["authors"].get(author_id)
    if author is not None and author["status"] != "CLIENT":
        author["status"] = "CLIENT"
        touch(author)


def author_maybe_former(author_id):
    author = DB["authors"].get(author_id)
    if author is None or author["status"] != "CLIENT":
        return
    still_signed = any(a for a in DB["client_agreements"].values()
                       if a["author_id"] == author_id and a["status"] == "SIGNED")
    if not still_signed:
        author["status"] = "FORMER"
        touch(author)


# ------------------------------------------------------------- calculations ----
def triage_score(genre, word_count, author_status):
    g = GENRE_W[genre]
    if 70000 <= word_count <= 120000:
        length = 40
    elif 50000 <= word_count <= 69999 or 120001 <= word_count <= 150000:
        length = 20
    else:
        length = 5
    return g + length + AUTHOR_W[author_status]


def subs_of_round(round_id):
    return [s for s in DB["submissions"].values()
            if s["submission_round_id"] == round_id]


def offers_of_round(round_id):
    sub_ids = {s["id"] for s in subs_of_round(round_id)}
    return [o for o in DB["offers"].values() if o["submission_id"] in sub_ids]


def _offer_value(offer, valuation_mode):
    weight, penalty = AUCTION_CONST[valuation_mode]
    pcts = (dec(offer["royalty_pct_hardcover"])
            + dec(offer["royalty_pct_trade"])
            + dec(offer["royalty_pct_ebook"]))
    rights = sum(1 for k in ("includes_film_rights", "includes_foreign_rights",
                             "includes_audio_rights") if offer[k])
    return (dec(offer["advance_cents"]) + Decimal(weight) * pcts
            - Decimal(penalty) * Decimal(rights))


def recompute_auction_ranks(rnd):
    if not rnd["auction_mode"]:
        return
    all_offers = offers_of_round(rnd["id"])
    live = [o for o in all_offers if o["status"] in LIVE_OFFER]
    live.sort(key=lambda o: (-_offer_value(o, rnd["valuation_mode"]),
                             o["created_at"], o["_seq"]))
    for i, o in enumerate(live):
        rank = i + 1
        if o["auction_rank"] != rank:
            o["auction_rank"] = rank
            touch(o)
    for o in all_offers:
        if o["status"] not in LIVE_OFFER and o["auction_rank"] is not None:
            o["auction_rank"] = None
            touch(o)


def _tiered_line(units, receipts, pct, threshold, esc):
    avg = receipts // units
    base = min(units, threshold)
    over = units - base
    return (base * floor_dec(Decimal(avg) * pct)
            + over * floor_dec(Decimal(avg) * (pct + esc)))


def compute_gross_royalty(stmt, offer, royalty_basis):
    esc = ESCALATOR[royalty_basis]
    total = 0
    if stmt["units_hardcover"] > 0:
        total += _tiered_line(stmt["units_hardcover"],
                              stmt["net_receipts_hardcover_cents"],
                              dec(offer["royalty_pct_hardcover"]),
                              TIER_HARDCOVER, esc)
    if stmt["units_trade"] > 0:
        total += _tiered_line(stmt["units_trade"],
                              stmt["net_receipts_trade_cents"],
                              dec(offer["royalty_pct_trade"]),
                              TIER_TRADE, esc)
    if stmt["units_ebook"] > 0:
        total += floor_dec(dec(stmt["net_receipts_ebook_cents"])
                           * dec(offer["royalty_pct_ebook"]))
    return total


def round_of_submission(sub):
    return DB["submission_rounds"][sub["submission_round_id"]]


def manuscript_of_round(rnd):
    return DB["manuscripts"][rnd["manuscript_id"]]


def signed_agreement_for_manuscript(manuscript_id):
    for a in DB["client_agreements"].values():
        if a["manuscript_id"] == manuscript_id and a["status"] == "SIGNED":
            return a
    return None


def round_of_offer(offer):
    return round_of_submission(DB["submissions"][offer["submission_id"]])


def agreement_chain_for_deal(deal):
    offer = DB["offers"][deal["offer_id"]]
    rnd = round_of_offer(offer)
    return signed_agreement_for_manuscript(rnd["manuscript_id"])


def commission_pct_for_deal(deal):
    agreement = agreement_chain_for_deal(deal)
    if agreement is not None and agreement["commission_pct_override"] is not None:
        return dec(agreement["commission_pct_override"])
    agency = DB["agencies"][deal["agency_id"]]
    return dec(agency["commission_pct"])


def reconcile_statement_fields(stmt):
    """Recompute gross/commission/net/variance in place. Returns (deal, net)."""
    deal = DB["deals"][stmt["deal_id"]]
    offer = DB["offers"][deal["offer_id"]]
    gross = compute_gross_royalty(stmt, offer, deal["royalty_basis"])
    pct = commission_pct_for_deal(deal)
    commission = floor_dec(Decimal(gross) * pct)
    net = gross - commission
    stmt["gross_royalty_cents"] = gross
    stmt["agency_commission_cents"] = commission
    stmt["author_net_cents"] = net
    stmt["variance_cents"] = stmt["publisher_reported_royalty_cents"] - gross
    return deal, net


def advance_waterfall(advance_cents):
    signing = advance_cents // 2          # floor(advance * 0.50)
    delivery = advance_cents // 4         # floor(advance * 0.25)
    publication = advance_cents - signing - delivery
    return (("ON_SIGNING", signing, 0),
            ("ON_DELIVERY", delivery, 1),
            ("ON_PUBLICATION", publication, 2))
