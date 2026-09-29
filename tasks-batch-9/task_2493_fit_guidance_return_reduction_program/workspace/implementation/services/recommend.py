"""calculations.fit_recommendation (PRD 3.6).

Two variants share one skeleton; only the signal pool, the anchor index and the
confidence cap differ.  The read never writes anything.
"""

import constants as C
from db import db, ordered
from numeric import clamp, floor_div, round_half_up
from services.derive import active_mapping_of_item, lines_of_customer


def _personal_pool(customer_profile_id, category_code):
    """(a) the shopper's own ACTIVE feedback and (b) their refunded FIT returns."""
    contributions = []

    for row in ordered(db.feedback.values()):
        if row["customer_profile_id"] != customer_profile_id:
            continue
        if row["status"] != "ACTIVE":
            continue
        item = db.items.get(row["item_id"])
        if item is None or item["category_code"] != category_code:
            continue
        contributions.append((C.VERDICT_OFFSET_CENTI[row["fit_verdict"]],
                              row["signal_weight"]))

    own_lines = {line["id"]: line for line in lines_of_customer(customer_profile_id)}
    for case in ordered(db.return_cases.values()):
        line = own_lines.get(case["order_line_id"])
        if line is None:
            continue
        if case["status"] != "RESOLVED_REFUNDED":
            continue
        if case["reason_family"] != "FIT":
            continue
        item = db.items.get(line["item_id"])
        if item is None or item["category_code"] != category_code:
            continue
        offset = C.FIT_RETURN_OFFSET_CENTI.get(case["reason_code"])
        if offset is None:
            continue
        contributions.append((offset, C.FIT_RETURN_SIGNAL_WEIGHT))

    return contributions


def _population_pool(item_id):
    contributions = []
    for row in ordered(db.feedback.values()):
        if row["item_id"] != item_id or row["status"] != "ACTIVE":
            continue
        contributions.append((C.VERDICT_OFFSET_CENTI[row["fit_verdict"]],
                              row["signal_weight"]))
    return contributions


def _weighted_offset_centi(contributions):
    total_weight = sum(weight for _, weight in contributions)
    if total_weight == 0:
        return 0
    weighted_sum = sum(offset * weight for offset, weight in contributions)
    return round_half_up(weighted_sum, total_weight)


def _personal_anchor_index(customer_profile_id, category_code, mapping, chart):
    """The shopper's most recent same-category line, mapped onto a chart row."""
    lines = []
    for line in lines_of_customer(customer_profile_id):
        item = db.items.get(line["item_id"])
        if item is None or item["category_code"] != category_code:
            continue
        lines.append(line)
    if not lines:
        return chart["median_row_index"]
    lines.sort(key=lambda line: (line["delivered_at"], line["created_at"],
                                 line["_seq"]), reverse=True)
    size_label = lines[0]["size_label"]

    chart_size_label = None
    for pair in mapping["size_label_pairs"]:
        if pair["spec_size_label"] == size_label:
            chart_size_label = pair["chart_size_label"]
            break
    if chart_size_label is None:
        return chart["median_row_index"]

    for row in chart["rows"]:
        if row["size_label"] == chart_size_label:
            return row["sort_index"]
    return chart["median_row_index"]


def fit_recommendation(item, customer_profile_id=None):
    mapping = active_mapping_of_item(item["id"])
    chart = db.charts.get(mapping["chart_id"]) if mapping is not None else None
    rows = sorted(chart["rows"], key=lambda r: r["sort_index"]) if chart else []
    coverage_bp = mapping["coverage_bp"] if mapping is not None else 0

    use_history = False
    contributions = []
    if customer_profile_id:
        personal = _personal_pool(customer_profile_id, item["category_code"])
        if len(personal) >= C.PERSONAL_SAMPLE_FLOOR:
            use_history = True
            contributions = personal

    if use_history:
        variant_applied = "history_weighted"
        sample_count = len(contributions)
        anchor_index = _personal_anchor_index(
            customer_profile_id, item["category_code"], mapping, chart)
        confidence_cap_bp = min(9500, 4500 + 1000 * sample_count)
    else:
        variant_applied = "population_fallback"
        contributions = _population_pool(item["id"])
        sample_count = len(contributions)
        anchor_index = chart["median_row_index"]
        confidence_cap_bp = min(8000, 2000 + 500 * sample_count)

    weighted_offset_centi = _weighted_offset_centi(contributions)
    step_shift = round_half_up(weighted_offset_centi, 100)
    row_count = chart["row_count"]
    recommended_index = clamp(anchor_index + step_shift, 0, row_count - 1)
    confidence_bp = floor_div(confidence_cap_bp * coverage_bp, 10000)
    suppressed = confidence_bp < C.CONFIDENCE_FLOOR_BP

    recommended_size_label = None
    if not suppressed and 0 <= recommended_index < len(rows):
        recommended_size_label = rows[recommended_index]["size_label"]

    return {
        "recommended_size_label": recommended_size_label,
        "confidence_bp": confidence_bp,
        "variant_applied": variant_applied,
        "sample_count": sample_count,
        "coverage_bp": coverage_bp,
        "suppressed": suppressed,
        "anchor_index": anchor_index,
        "recommended_index": recommended_index,
    }
