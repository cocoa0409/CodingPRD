"""Money, rounding, interval and calculation rules (PRD sections 2.5, 2.10, 3)."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import db, ordered

ZERO_PCT = Decimal("0.00")
HUNDRED = Decimal(100)
BPS_DENOMINATOR = Decimal(10000)


def round_half_up(value, places=0):
    """Every division in this system rounds HALF UP at the pinned scale."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


# -- interval conventions ----------------------------------------------------


def half_open_contains_date(day, start, end):
    """Reporting periods are half-open: [start, end)."""
    return start <= day < end


def half_open_within(inner_start, inner_end, outer_start, outer_end):
    return inner_start >= outer_start and inner_end <= outer_end


def half_open_overlap(a_start, a_end, b_start, b_end):
    """Abutting half-open windows do not overlap."""
    return a_start < b_end and b_start < a_end


def closed_contains_date(day, start, end):
    """Contract terms and price windows are closed inclusive: [from, to]."""
    return start <= day <= end


def closed_within(inner_from, inner_to, outer_from, outer_to):
    return inner_from >= outer_from and inner_to <= outer_to


def closed_overlap(a_from, a_to, b_from, b_to):
    """Sharing a single endpoint date is an overlap for closed windows."""
    return a_from <= b_to and b_from <= a_to


# -- tier ladder -------------------------------------------------------------


def find_tier(contract, tier_code):
    for tier in contract["tiers"]:
        if tier["tier_code"] == tier_code:
            return tier
    return None


def derive_default_tier_code(tiers):
    for tier in tiers:
        if tier["min_committed_volume_units"] == 0 and tier["min_compliance_pct"] == ZERO_PCT:
            return tier["tier_code"]
    return None


def tier_price_cents(base_price_cents, discount_bps):
    """One rounding, taken immediately after the discount is applied."""
    exact = Decimal(base_price_cents) * (BPS_DENOMINATOR - Decimal(discount_bps)) / BPS_DENOMINATOR
    return rhu_int(exact)


def derive_activation_price(item, tier, activation_type, requested_price_cents):
    """Steps 2-4 of the four-step activation price derivation."""
    price = tier_price_cents(item["base_price_cents"], tier["discount_bps"])
    if activation_type == "LOCAL_EXCEPTION" and requested_price_cents is not None:
        candidate = min(int(requested_price_cents), price)
    else:
        candidate = price
    floor_price = item["floor_price_cents"]
    if candidate < floor_price:
        return floor_price, True
    return candidate, False


# -- clinical evidence -------------------------------------------------------


def weighted_evidence_score(efficacy, safety, resilience):
    """Products summed unrounded, then rounded once HALF UP to two places."""
    exact = (
        Decimal(efficacy) * Decimal("0.40")
        + Decimal(safety) * Decimal("0.35")
        + Decimal(resilience) * Decimal("0.25")
    )
    return round_half_up(exact, 2)


EVIDENCE_THRESHOLD = Decimal("7.00")


def conversion_recommendation(weighted_score):
    return "CONVERT" if weighted_score >= EVIDENCE_THRESHOLD else "DO_NOT_CONVERT"


def contract_has_convert_endorsement(contract):
    for review in db.reviews.values():
        if (
            review["contract_id"] == contract["id"]
            and review["status"] == "ENDORSED"
            and review["conversion_recommendation"] == "CONVERT"
        ):
            return True
    return False


# -- purchase lines ----------------------------------------------------------


def file_lines(distributor_file):
    return ordered(
        [
            line
            for line in db.purchase_lines.values()
            if line["distributor_file_id"] == distributor_file["id"]
        ]
    )


def commitment_for(member_id, contract_id, statuses):
    for commitment in ordered(db.commitments.values()):
        if (
            commitment["member_id"] == member_id
            and commitment["contract_id"] == contract_id
            and commitment["election_status"] in statuses
        ):
            return commitment
    return None


def governing_activation(commitment, contract_item_id, purchase_date):
    """ACTIVE activations covering the purchase date, best candidate first."""
    candidates = [
        activation
        for activation in db.activations.values()
        if activation["commitment_id"] == commitment["id"]
        and activation["contract_item_id"] == contract_item_id
        and activation["status"] == "ACTIVE"
        and closed_contains_date(
            purchase_date, activation["effective_from"], activation["effective_to"]
        )
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            0 if row["activation_type"] == "LOCAL_EXCEPTION" else 1,
            _descending_date(row["effective_from"]),
            row["created_at"],
            row["_seq"],
        )
    )
    return candidates[0]


def _descending_date(value):
    """Sort key that orders ISO dates descending (later effective_from first)."""
    return tuple(-int(part) for part in value.split("-"))


def approved_xref(member_id, member_item_number, contract_id):
    for xref in ordered(db.xrefs.values()):
        if xref["status"] != "APPROVED":
            continue
        if xref["member_id"] != member_id:
            continue
        if xref["member_item_number"] != member_item_number:
            continue
        item = db.contract_items.get(xref["contract_item_id"])
        if item is not None and item["contract_id"] == contract_id:
            return xref, item
    return None, None


def approved_xref_for_item(member_id, contract_item_id):
    for xref in ordered(db.xrefs.values()):
        if (
            xref["status"] == "APPROVED"
            and xref["member_id"] == member_id
            and xref["contract_item_id"] == contract_item_id
        ):
            return xref
    return None


def leakage_pct(total_cents, on_contract_cents):
    if total_cents <= 0:
        return ZERO_PCT
    exact = (Decimal(total_cents) - Decimal(on_contract_cents)) * HUNDRED / Decimal(total_cents)
    return round_half_up(exact, 2)


# -- compliance measurement --------------------------------------------------

PRELIMINARY_FILE_STATUSES = ("LOADED", "PARTIALLY_LOADED")
FINAL_FILE_STATUSES = ("LOADED",)


def eligible_measurement_files(commitment, period_start, period_end, statuses):
    rows = []
    for distributor_file in ordered(db.files.values()):
        if distributor_file["member_id"] != commitment["member_id"]:
            continue
        if distributor_file["contract_id"] != commitment["contract_id"]:
            continue
        if distributor_file["status"] not in statuses:
            continue
        if not half_open_within(
            distributor_file["period_start"],
            distributor_file["period_end"],
            period_start,
            period_end,
        ):
            continue
        rows.append(distributor_file)
    return rows


def aggregate_measurement(commitment, period_start, period_end, variant):
    """The shared aggregation, run under the PRELIMINARY or FINAL variant."""
    if variant == "PRELIMINARY":
        statuses = PRELIMINARY_FILE_STATUSES
        counts_unmatched = False
    else:
        statuses = FINAL_FILE_STATUSES
        counts_unmatched = True

    on_contract = 0
    leakage = 0
    unmatched = 0
    volume = 0
    for distributor_file in eligible_measurement_files(
        commitment, period_start, period_end, statuses
    ):
        for line in file_lines(distributor_file):
            if line["reject_reason"] != "NONE":
                continue
            classification = line["classification"]
            if classification == "ON_CONTRACT":
                on_contract += line["extended_cost_cents"]
                volume += line["contract_units"]
            elif classification == "OFF_CONTRACT_LEAKAGE":
                leakage += line["extended_cost_cents"]
            elif classification == "UNMATCHED":
                unmatched += line["extended_cost_cents"]

    total = on_contract + leakage + (unmatched if counts_unmatched else 0)
    if total == 0:
        compliance = ZERO_PCT
        basis_empty = True
    else:
        compliance = round_half_up(Decimal(on_contract) * HUNDRED / Decimal(total), 2)
        basis_empty = False
    return {
        "on_contract_spend_cents": on_contract,
        "leakage_spend_cents": leakage,
        "unmatched_spend_cents": unmatched,
        "total_category_spend_cents": total,
        "measured_volume_units": volume,
        "compliance_pct": compliance,
        "basis_empty": basis_empty,
        "computed_variant": variant,
    }


def qualified_tier_code(contract, compliance, measured_volume_units):
    eligible = [
        tier
        for tier in contract["tiers"]
        if compliance >= tier["min_compliance_pct"]
        and measured_volume_units >= tier["min_committed_volume_units"]
    ]
    if not eligible:
        return contract["default_tier_code"]
    eligible.sort(
        key=lambda tier: (
            -tier["discount_bps"],
            -tier["min_committed_volume_units"],
            tier["tier_code"],
        )
    )
    return eligible[0]["tier_code"]


# -- leakage report ----------------------------------------------------------

LEAKAGE_REPORT_FILE_STATUSES = ("LOADED", "PARTIALLY_LOADED")


def build_leakage_report(commitment, from_date, to_date):
    on_contract = 0
    leakage = 0
    unmatched = 0
    grouped = {}
    for distributor_file in ordered(db.files.values()):
        if distributor_file["member_id"] != commitment["member_id"]:
            continue
        if distributor_file["contract_id"] != commitment["contract_id"]:
            continue
        if distributor_file["status"] not in LEAKAGE_REPORT_FILE_STATUSES:
            continue
        if not half_open_within(
            distributor_file["period_start"],
            distributor_file["period_end"],
            from_date,
            to_date,
        ):
            continue
        for line in file_lines(distributor_file):
            if line["reject_reason"] != "NONE":
                continue
            classification = line["classification"]
            if classification == "ON_CONTRACT":
                on_contract += line["extended_cost_cents"]
            elif classification == "UNMATCHED":
                unmatched += line["extended_cost_cents"]
            elif classification == "OFF_CONTRACT_LEAKAGE":
                leakage += line["extended_cost_cents"]
                bucket = grouped.setdefault(
                    line["member_item_number"],
                    {
                        "member_item_number": line["member_item_number"],
                        "spend_cents": 0,
                        "quantity_units": 0,
                    },
                )
                bucket["spend_cents"] += line["extended_cost_cents"]
                bucket["quantity_units"] += line["quantity_units"]

    denominator = on_contract + leakage + unmatched
    if denominator == 0:
        pct = ZERO_PCT
    else:
        pct = round_half_up(Decimal(leakage) * HUNDRED / Decimal(denominator), 2)
    top_items = sorted(
        grouped.values(),
        key=lambda row: (-row["spend_cents"], row["member_item_number"]),
    )[:3]
    return {
        "commitment_id": commitment["id"],
        "from_date": from_date,
        "to_date": to_date,
        "on_contract_spend_cents": on_contract,
        "leakage_spend_cents": leakage,
        "unmatched_spend_cents": unmatched,
        "denominator_cents": denominator,
        "leakage_pct": pct,
        "top_items": top_items,
    }


# -- administrative fee distribution ----------------------------------------


def accrued_fee_for(contract, period_start, period_end):
    """Per-line rounding, then an exact integer sum of the rounded fees."""
    eligible = []
    for distributor_file in db.files.values():
        if distributor_file["contract_id"] != contract["id"]:
            continue
        if distributor_file["status"] != "LOADED":
            continue
        if not half_open_within(
            distributor_file["period_start"],
            distributor_file["period_end"],
            period_start,
            period_end,
        ):
            continue
        for line in file_lines(distributor_file):
            if line["reject_reason"] != "NONE":
                continue
            if line["classification"] != "ON_CONTRACT":
                continue
            eligible.append(line)
    eligible.sort(key=lambda line: (line["purchase_date"], line["created_at"], line["_seq"]))
    total = 0
    for line in eligible:
        total += rhu_int(
            Decimal(line["extended_cost_cents"]) * Decimal(contract["admin_fee_bps"]) / BPS_DENOMINATOR
        )
    return total


def holdback_for(contract, gross_pool_cents):
    """The applicable rung, then exactly two roundings in a fixed order."""
    applicable = None
    for entry in contract["holdback_tiers"]:
        if entry["min_gross_pool_cents"] <= gross_pool_cents:
            if applicable is None or entry["min_gross_pool_cents"] > applicable["min_gross_pool_cents"]:
                applicable = entry
    bps = applicable["holdback_bps"] if applicable is not None else 0
    holdback_cents = rhu_int(Decimal(gross_pool_cents) * Decimal(bps) / BPS_DENOMINATOR)
    net_pool_cents = gross_pool_cents - holdback_cents
    member_pool_cents = rhu_int(
        Decimal(net_pool_cents) * Decimal(contract["member_share_bps"]) / BPS_DENOMINATOR
    )
    return bps, holdback_cents, net_pool_cents, member_pool_cents


def eligible_share_commitments(contract):
    rows = []
    for commitment in ordered(db.commitments.values()):
        if commitment["contract_id"] != contract["id"]:
            continue
        if commitment["election_status"] != "ACTIVE":
            continue
        if commitment["lop_status"] != "COUNTERSIGNED":
            continue
        if commitment["leakage_flag"]:
            continue
        if commitment["ytd_on_contract_spend_cents"] <= 0:
            continue
        rows.append(commitment)
    return rows


def _member_order_key(member):
    if member is None:
        return ("", 0)
    return (member["created_at"], member["_seq"])


def member_waterfall(contract, member_pool_cents):
    """Floor-plus-remainder allocation by on-contract spend weight."""
    eligible = eligible_share_commitments(contract)
    total_weight = sum(row["ytd_on_contract_spend_cents"] for row in eligible)
    if not eligible or total_weight <= 0:
        return [], 0, member_pool_cents

    entries = []
    for commitment in eligible:
        weight = commitment["ytd_on_contract_spend_cents"]
        exact = Decimal(member_pool_cents) * Decimal(weight) / Decimal(total_weight)
        share = floor_int(exact)
        member = db.members.get(commitment["member_id"])
        entries.append(
            {
                "member_id": commitment["member_id"],
                "commitment_id": commitment["id"],
                "weight_cents": weight,
                "share_cents": share,
                "_fraction": exact - Decimal(share),
                "_member_key": _member_order_key(member),
            }
        )

    remainder = member_pool_cents - sum(entry["share_cents"] for entry in entries)
    if remainder > 0:
        ranked = sorted(entries, key=lambda entry: (-entry["_fraction"], entry["_member_key"]))
        for index in range(remainder):
            ranked[index % len(ranked)]["share_cents"] += 1

    entries.sort(key=lambda entry: (-entry["share_cents"], entry["_member_key"]))
    shares = [
        {
            "member_id": entry["member_id"],
            "commitment_id": entry["commitment_id"],
            "weight_cents": entry["weight_cents"],
            "share_cents": entry["share_cents"],
        }
        for entry in entries
    ]
    total = sum(entry["share_cents"] for entry in shares)
    undistributed = member_pool_cents - total
    return shares, total, undistributed
