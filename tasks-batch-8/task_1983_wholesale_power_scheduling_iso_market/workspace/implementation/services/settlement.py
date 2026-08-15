"""Settlement engine: DA clearing, imbalance, congestion/loss allocation,
ancillary revenue, capacity performance charges, statement generation,
resettlement recompute."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import new_record, rhu, sort_key, touch
from services.credit import refresh_credit

DEVIATION_DEADBAND_PCT = Decimal("0.05")
SHORT_PENALTY_MULT = Decimal("1.10")
LONG_CREDIT_MULT = Decimal("0.90")
PERFORMANCE_FLOOR = Decimal("0.9")
PENALTY_RATE_CENTS_PER_MWH = 50000
STOP_LOSS_FACTOR = Decimal("1.5")

CHARGE_ORDER = ["DA_ENERGY_CREDIT", "RT_IMBALANCE", "CONGESTION",
                "LOSSES", "ANCILLARY", "CAPACITY"]

# component header field adjusted when a disputed line of this type is upheld;
# direction: +1 => header += line.amount ; -1 => header -= line.amount
_COMPONENT_FIELD = {
    "DA_ENERGY_CREDIT": ("da_energy_credit_cents", +1),
    "RT_IMBALANCE": ("imbalance_charge_cents", -1),
    "CONGESTION": ("congestion_charge_cents", -1),
    "LOSSES": ("loss_charge_cents", -1),
    "ANCILLARY": ("ancillary_revenue_cents", +1),
    "CAPACITY": ("capacity_charge_cents", -1),
}


def node_for(day_id, node_name):
    for n in store.price_nodes.values():
        if n["operating_day_id"] == day_id and n["node_name"] == node_name:
            return n
    return None


def recorded_actual(generator_id, day_id, interval_index):
    for t in store.telemetry.values():
        if (t["generator_asset_id"] == generator_id
                and t["operating_day_id"] == day_id
                and t["interval_index"] == interval_index
                and t["status"] == "RECORDED"):
            return Decimal(t["actual_mw"])
    return Decimal(0)


def day_offers(day_id):
    return sorted((o for o in store.offers.values() if o["operating_day_id"] == day_id),
                  key=sort_key)


def run_da_clearing(day):
    """Clear SUBMITTED offers against the DA deck; expire DRAFTs. The caller has
    already created PriceNode rows and verified deck completeness."""
    affected_participants = []
    for offer in day_offers(day["id"]):
        gen = store.generators[offer["generator_asset_id"]]
        if offer["status"] == "SUBMITTED":
            node = node_for(day["id"], gen["pricing_node"])
            lmp = (node["da_energy_cents_per_mwh"] + node["da_congestion_cents_per_mwh"]
                   + node["da_loss_cents_per_mwh"])
            if offer["offer_price_cents_per_mwh"] <= lmp:  # equality clears
                offer["status"] = "CLEARED"
                offer["cleared_mw"] = offer["offered_mw"]
                offer["da_lmp_cents_per_mwh"] = lmp
            else:
                offer["status"] = "NOT_CLEARED"
                offer["cleared_mw"] = Decimal(0)
            touch(offer)
            affected_participants.append(gen["market_participant_id"])
        elif offer["status"] == "DRAFT":
            offer["status"] = "EXPIRED"
            touch(offer)
    for pid in dict.fromkeys(affected_participants):
        refresh_credit(store.participants[pid])


def _rt_components(node, variant):
    if variant == "preliminary":
        return (node.get("rt_prelim_energy_cents_per_mwh") or 0,
                node.get("rt_prelim_congestion_cents_per_mwh") or 0,
                node.get("rt_prelim_loss_cents_per_mwh") or 0)
    return (node.get("rt_final_energy_cents_per_mwh") or 0,
            node.get("rt_final_congestion_cents_per_mwh") or 0,
            node.get("rt_final_loss_cents_per_mwh") or 0)


def _imbalance_for_offer(offer, gen, node, variant):
    """Per-interval HALF_UP rounding, then sum. Returns (total, net_dev_mw)."""
    day_id = offer["operating_day_id"]
    c = Decimal(offer["cleared_mw"])
    deadband = DEVIATION_DEADBAND_PCT * c  # exact, never rounded
    e_rt, _, _ = _rt_components(node, variant)
    total = 0
    net_dev = Decimal(0)
    for i in range(1, 25):
        a = recorded_actual(gen["id"], day_id, i)
        dev = a - c
        net_dev += dev
        abs_dev = abs(dev)
        if abs_dev <= deadband:
            within = dev
            excess = Decimal(0)
        else:
            within = deadband if dev > 0 else -deadband
            excess = abs_dev - deadband
        energy = -(within) * e_rt
        if dev < 0 and excess > 0:
            energy += excess * e_rt * SHORT_PENALTY_MULT
        elif dev > 0 and excess > 0:
            energy += -(excess * e_rt * LONG_CREDIT_MULT)
        total += rhu(energy)
    return total, net_dev


def _congestion_loss_for_offer(offer, gen, node, variant):
    """Round every per-interval component HALF_UP first, then sum (pinned)."""
    day_id = offer["operating_day_id"]
    c = Decimal(offer["cleared_mw"])
    _, rt_cong, rt_loss = _rt_components(node, variant)
    cong_total = 0
    loss_total = 0
    for i in range(1, 25):
        a = recorded_actual(gen["id"], day_id, i)
        dev = a - c
        cong_total += rhu(c * node["da_congestion_cents_per_mwh"])
        cong_total += rhu(-(dev) * rt_cong)
        loss_total += rhu(c * node["da_loss_cents_per_mwh"])
        loss_total += rhu(-(dev) * rt_loss)
    return cong_total, loss_total


def score_and_settle_award(award, day_id):
    """Compute performance_score and revenue_cents; AWARDED -> SETTLED."""
    awarded = Decimal(award["awarded_mw"])
    length = award["end_interval"] - award["start_interval"] + 1
    qualifying = 0
    for i in range(award["start_interval"], award["end_interval"] + 1):
        a = recorded_actual(award["generator_asset_id"], day_id, i)
        if a is not None and a >= PERFORMANCE_FLOOR * awarded:
            qualifying += 1
        # missing telemetry counts as non-qualifying
    score = Decimal(qualifying) / Decimal(length)
    if score >= Decimal("0.95"):
        tier = Decimal("1.00")
    elif score >= Decimal("0.75"):
        tier = Decimal("0.85")
    elif score >= Decimal("0.50"):
        tier = Decimal("0.50")
    else:
        tier = Decimal("0.00")
    capacity_component = awarded * award["capacity_price_cents"] * tier
    performance_component = Decimal(0)
    if award["service_type"] == "REGULATION":
        performance_component = (awarded * award["performance_price_cents"]
                                 * Decimal(award["mileage_ratio"]))
    award["performance_score"] = score
    award["revenue_cents"] = rhu(capacity_component + performance_component)
    award["status"] = "SETTLED"
    touch(award)


def _capacity_charges_for_day(day_id):
    """Flatten per-(obligation,event) charges recorded at event completion."""
    rows = []  # (obligation, event, penalty, bonus, shortfall)
    for ev in store.events.values():
        if ev["operating_day_id"] != day_id or ev["status"] != "COMPLETED":
            continue
        for obl_id, ch in ev.get("_charges", {}).items():
            obl = store.obligations.get(obl_id)
            if obl is None:
                continue
            rows.append((obl, ev, ch["penalty"], ch["bonus"], ch["shortfall"]))
    return rows


def generate_statements(day, run_type, variant):
    """Generate one statement per (participant, day) with settlement activity."""
    day_id = day["id"]
    cleared = [o for o in day_offers(day_id) if o["status"] == "CLEARED"]
    awards = sorted(
        (a for a in store.awards.values()
         if a["operating_day_id"] == day_id and a["status"] in ("AWARDED", "SETTLED")),
        key=sort_key)
    capacity_rows = _capacity_charges_for_day(day_id)

    participants = {}
    for offer in cleared:
        gen = store.generators[offer["generator_asset_id"]]
        participants.setdefault(gen["market_participant_id"], True)
    for award in awards:
        gen = store.generators[award["generator_asset_id"]]
        participants.setdefault(gen["market_participant_id"], True)
    for obl, _ev, penalty, bonus, _sf in capacity_rows:
        if penalty != 0 or bonus != 0:
            gen = store.generators[obl["generator_asset_id"]]
            participants.setdefault(gen["market_participant_id"], True)

    for pid in participants:
        _generate_one_statement(day, pid, run_type, variant, cleared, awards, capacity_rows)


def _emit_line(statement, gen_id, charge_type, mw_quantity, amount_cents):
    if amount_cents == 0:
        return  # zero-amount components emit no line
    line = new_record()
    line.update({
        "settlement_statement_id": statement["id"],
        "generator_asset_id": gen_id,
        "charge_type": charge_type,
        "mw_quantity": Decimal(mw_quantity),
        "amount_cents": int(amount_cents),
    })
    store.lines[line["id"]] = line


def _generate_one_statement(day, pid, run_type, variant, cleared, awards, capacity_rows):
    day_id = day["id"]
    gens = sorted((g for g in store.generators.values() if g["market_participant_id"] == pid),
                  key=sort_key)

    da_credit = imbalance = congestion = losses = ancillary = capacity = 0
    pending_lines = []  # (gen_seq, charge_idx, gen_id, charge_type, mw, amount)

    for gen in gens:
        gen_offers = [o for o in cleared if o["generator_asset_id"] == gen["id"]]
        for offer in gen_offers:
            node = node_for(day_id, gen["pricing_node"])
            c = Decimal(offer["cleared_mw"])
            credit = rhu(Decimal(24) * c * node["da_energy_cents_per_mwh"])
            da_credit += credit
            pending_lines.append((gen["_seq"], 0, gen["id"], "DA_ENERGY_CREDIT", c, -credit))

            imb, net_dev = _imbalance_for_offer(offer, gen, node, variant)
            imbalance += imb
            pending_lines.append((gen["_seq"], 1, gen["id"], "RT_IMBALANCE", net_dev, imb))

            cong, loss = _congestion_loss_for_offer(offer, gen, node, variant)
            congestion += cong
            losses += loss
            pending_lines.append((gen["_seq"], 2, gen["id"], "CONGESTION", c, cong))
            pending_lines.append((gen["_seq"], 3, gen["id"], "LOSSES", c, loss))

        gen_awards = [a for a in awards if a["generator_asset_id"] == gen["id"]]
        if gen_awards:
            rev = sum(a["revenue_cents"] for a in gen_awards)
            ancillary += rev
            mw = sum((Decimal(a["awarded_mw"]) for a in gen_awards), Decimal(0))
            pending_lines.append((gen["_seq"], 4, gen["id"], "ANCILLARY", mw, -rev))

        cap_amount = 0
        cap_mw = Decimal(0)
        for obl, _ev, penalty, bonus, shortfall in capacity_rows:
            if obl["generator_asset_id"] != gen["id"]:
                continue
            cap_amount += penalty - bonus
            cap_mw += shortfall
        capacity += cap_amount
        pending_lines.append((gen["_seq"], 5, gen["id"], "CAPACITY", cap_mw, cap_amount))

    net = congestion + losses + imbalance + capacity - da_credit - ancillary

    stmt = new_record()
    stmt.update({
        "market_participant_id": pid,
        "operating_day_id": day_id,
        "run_type": run_type,
        "status": "ISSUED",
        "da_energy_credit_cents": da_credit,
        "imbalance_charge_cents": imbalance,
        "congestion_charge_cents": congestion,
        "loss_charge_cents": losses,
        "ancillary_revenue_cents": ancillary,
        "capacity_charge_cents": capacity,
        "net_amount_cents": net,
        "paid_cents": 0,
        "issued_at": store.clock_now,
        "dispute_window_ends_at": (None if run_type == "PRELIMINARY"
                                   else store.clock_now + timedelta(hours=72)),
        "supersedes_statement_id": None,
    })
    store.statements[stmt["id"]] = stmt

    for _gs, _ci, gen_id, charge_type, mw, amount in sorted(pending_lines):
        _emit_line(stmt, gen_id, charge_type, mw, amount)
    return stmt


def capacity_performance_charge(event, day):
    """Runs at event completion: penalties pool, revenue-neutral bonus split."""
    month = day["market_date"][:7]
    hours = event["end_interval"] - event["start_interval"] + 1
    scope = sorted(
        (o for o in store.obligations.values()
         if o["status"] in ("ACTIVE", "AT_RISK") and o["delivery_period"] == month),
        key=sort_key)

    charges = {}
    pool = 0
    claims = {}
    for obl in scope:
        gen = store.generators[obl["generator_asset_id"]]
        expected = min(Decimal(obl["obligated_mw"]), Decimal(gen["availability_mw"]))
        total_actual = Decimal(0)
        for i in range(event["start_interval"], event["end_interval"] + 1):
            total_actual += recorded_actual(gen["id"], day["id"], i)
        actual = total_actual / Decimal(hours)  # missing intervals count as 0
        shortfall = max(Decimal(0), expected - actual)
        surplus = max(Decimal(0), actual - expected)
        penalty = rhu(shortfall * PENALTY_RATE_CENTS_PER_MWH * hours)
        charges[obl["id"]] = {"penalty": penalty, "bonus": 0, "shortfall": shortfall}
        pool += penalty
        if surplus > 0:
            claims[obl["id"]] = surplus * hours

    total_claims = sum(claims.values()) if claims else Decimal(0)
    bonuses_paid = 0
    if total_claims > 0:
        allocated = 0
        for obl_id, claim in claims.items():
            bonus = rhu(Decimal(pool) * claim / total_claims)
            charges[obl_id]["bonus"] = bonus
            allocated += bonus
        remainder = pool - allocated
        if remainder != 0:
            # remainder goes to the largest claim; ties -> earliest created_at
            def _largest_key(item):
                obl_id, claim = item
                return (-claim, store.obligations[obl_id]["created_at"],
                        store.obligations[obl_id]["_seq"])
            target = min(claims.items(), key=_largest_key)[0]
            charges[target]["bonus"] += remainder
        bonuses_paid = sum(ch["bonus"] for ch in charges.values())

    event["penalties_collected_cents"] = pool
    event["bonuses_paid_cents"] = bonuses_paid
    event["_charges"] = charges

    affected = []
    for obl in scope:
        ch = charges[obl["id"]]
        if ch["penalty"] or ch["bonus"]:
            obl["accrued_penalty_cents"] += ch["penalty"]
            obl["accrued_bonus_cents"] += ch["bonus"]
            touch(obl)
            gen = store.generators[obl["generator_asset_id"]]
            affected.append(gen["market_participant_id"])
    for pid in dict.fromkeys(affected):
        refresh_credit(store.participants[pid])


def capacity_stop_loss_close(obligation):
    """Pinned evaluation order: gross first, then cap, then charged/forgiven."""
    gross = rhu(Decimal(obligation["obligated_mw"]) * obligation["capacity_rate_cents_per_mw"])
    cap = rhu(STOP_LOSS_FACTOR * gross)
    charged = min(obligation["accrued_penalty_cents"], cap)  # equality charged in full
    forgiven = obligation["accrued_penalty_cents"] - charged
    obligation["gross_revenue_cents"] = gross
    obligation["charged_penalty_cents"] = charged
    obligation["forgiven_penalty_cents"] = forgiven


def resettlement_recompute(disputed, dispute):
    """Create the RESETTLEMENT statement replacing a disputed one (UPHELD)."""
    disputed_lines = [store.lines[lid] for lid in dispute["disputed_line_ids"]
                      if lid in store.lines]
    total_disputed = sum(l["amount_cents"] for l in disputed_lines)

    stmt = new_record()
    stmt.update({
        "market_participant_id": disputed["market_participant_id"],
        "operating_day_id": disputed["operating_day_id"],
        "run_type": "RESETTLEMENT",
        "status": "ISSUED",
        "da_energy_credit_cents": disputed["da_energy_credit_cents"],
        "imbalance_charge_cents": disputed["imbalance_charge_cents"],
        "congestion_charge_cents": disputed["congestion_charge_cents"],
        "loss_charge_cents": disputed["loss_charge_cents"],
        "ancillary_revenue_cents": disputed["ancillary_revenue_cents"],
        "capacity_charge_cents": disputed["capacity_charge_cents"],
        "net_amount_cents": disputed["net_amount_cents"] - total_disputed,
        "paid_cents": disputed["paid_cents"],
        "issued_at": store.clock_now,
        "dispute_window_ends_at": store.clock_now + timedelta(hours=72),
        "supersedes_statement_id": disputed["id"],
    })
    for line in disputed_lines:
        field, sign = _COMPONENT_FIELD[line["charge_type"]]
        stmt[field] += sign * line["amount_cents"]
    store.statements[stmt["id"]] = stmt

    # Copy non-disputed lines onto the resettlement statement so header
    # aggregates stay consistent with the line set.
    disputed_ids = set(dispute["disputed_line_ids"])
    for line in sorted((l for l in store.lines.values()
                        if l["settlement_statement_id"] == disputed["id"]),
                       key=sort_key):
        if line["id"] in disputed_ids:
            continue
        nl = new_record()
        nl.update({
            "settlement_statement_id": stmt["id"],
            "generator_asset_id": line["generator_asset_id"],
            "charge_type": line["charge_type"],
            "mw_quantity": line["mw_quantity"],
            "amount_cents": line["amount_cents"],
        })
        store.lines[nl["id"]] = nl
    return stmt
