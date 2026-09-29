"""Distributor file validation, the load cascade and its compensation.

PRD section 3.7: hop 1 classification, hop 2 commitment ledgers, hop 3 the
leakage ratio, hop 4 the member watchlist; and the three-hop reversal.
"""

from decimal import Decimal

from db import db
from services.calc import (
    approved_xref,
    commitment_for,
    file_lines,
    governing_activation,
    half_open_contains_date,
    leakage_pct,
    rhu_int,
)

LEDGER_COMMITMENT_STATUSES = ("ELECTED", "ACTIVE", "REQUAL_REVIEW")


def validate_file(distributor_file):
    """Stamp each line's reject_reason, then recompute both counters."""
    accepted = 0
    rejected = 0
    for line in file_lines(distributor_file):
        if not half_open_contains_date(
            line["purchase_date"],
            distributor_file["period_start"],
            distributor_file["period_end"],
        ):
            line["reject_reason"] = "DATE_OUT_OF_PERIOD"
        elif line["quantity_units"] == 0:
            line["reject_reason"] = "ZERO_QUANTITY"
        else:
            line["reject_reason"] = "NONE"
        if line["reject_reason"] == "NONE":
            accepted += 1
        else:
            rejected += 1
    distributor_file["accepted_line_count"] = accepted
    distributor_file["rejected_line_count"] = rejected
    distributor_file["status"] = "VALIDATING"
    db.touch(distributor_file)


def _classify(distributor_file, commitment, line):
    xref, item = approved_xref(
        distributor_file["member_id"],
        line["member_item_number"],
        distributor_file["contract_id"],
    )
    if xref is None:
        line["classification"] = "UNMATCHED"
        line["matched_vendor_item_number"] = None
        line["contract_units"] = 0
        return
    line["matched_vendor_item_number"] = item["vendor_item_number"]
    line["contract_units"] = rhu_int(
        Decimal(line["quantity_units"]) * Decimal(xref["conversion_factor"])
    )
    governing = None
    if commitment is not None:
        governing = governing_activation(commitment, item["id"], line["purchase_date"])
    if governing is None:
        line["classification"] = "OFF_CONTRACT_LEAKAGE"
    elif line["unit_price_paid_cents"] <= governing["computed_price_cents"]:
        line["classification"] = "ON_CONTRACT"
    else:
        line["classification"] = "OFF_CONTRACT_LEAKAGE"


def load_file(distributor_file):
    """Drive VALIDATING into LOADED, PARTIALLY_LOADED or REJECTED."""
    if distributor_file["accepted_line_count"] == 0:
        distributor_file["status"] = "REJECTED"
        db.touch(distributor_file)
        return

    distributor_file["status"] = (
        "LOADED" if distributor_file["rejected_line_count"] == 0 else "PARTIALLY_LOADED"
    )
    distributor_file["loaded_at"] = db.now_iso()
    db.touch(distributor_file)

    commitment = commitment_for(
        distributor_file["member_id"],
        distributor_file["contract_id"],
        LEDGER_COMMITMENT_STATUSES,
    )

    on_contract_delta = 0
    total_delta = 0
    volume_delta = 0
    for line in file_lines(distributor_file):
        if line["reject_reason"] != "NONE":
            continue
        _classify(distributor_file, commitment, line)
        classification = line["classification"]
        if classification == "ON_CONTRACT":
            on_contract_delta += line["extended_cost_cents"]
            total_delta += line["extended_cost_cents"]
            volume_delta += line["contract_units"]
        else:
            total_delta += line["extended_cost_cents"]

    db.file_load_deltas[distributor_file["id"]] = {
        "commitment_id": commitment["id"] if commitment is not None else None,
        "on_contract_spend_cents": on_contract_delta,
        "total_category_spend_cents": total_delta,
        "measured_volume_units": volume_delta,
    }

    if commitment is None:
        return

    commitment["ytd_on_contract_spend_cents"] += on_contract_delta
    commitment["ytd_total_category_spend_cents"] += total_delta
    commitment["ytd_measured_volume_units"] += volume_delta

    contract = db.contracts.get(commitment["contract_id"])
    threshold = contract["leakage_alert_threshold_pct"] if contract is not None else None
    was_flagged = commitment["leakage_flag"]
    commitment["ytd_leakage_pct"] = leakage_pct(
        commitment["ytd_total_category_spend_cents"],
        commitment["ytd_on_contract_spend_cents"],
    )
    if threshold is not None and commitment["ytd_leakage_pct"] > threshold:
        commitment["leakage_flag"] = True
    db.touch(commitment)

    if not was_flagged and commitment["leakage_flag"]:
        member = db.members.get(commitment["member_id"])
        if member is not None:
            member["watchlist_status"] = "WATCHLIST"
            db.touch(member)


def reverse_file(distributor_file, reason):
    """Compensate the exact amounts this file posted at load."""
    delta = db.file_load_deltas.get(distributor_file["id"])
    distributor_file["status"] = "REVERSED"
    distributor_file["reverse_note"] = reason
    db.touch(distributor_file)

    commitment = None
    if delta is not None and delta.get("commitment_id"):
        commitment = db.commitments.get(delta["commitment_id"])

    if commitment is not None:
        commitment["ytd_on_contract_spend_cents"] -= delta["on_contract_spend_cents"]
        commitment["ytd_total_category_spend_cents"] -= delta["total_category_spend_cents"]
        commitment["ytd_measured_volume_units"] -= delta["measured_volume_units"]
        contract = db.contracts.get(commitment["contract_id"])
        threshold = contract["leakage_alert_threshold_pct"] if contract is not None else None
        was_flagged = commitment["leakage_flag"]
        commitment["ytd_leakage_pct"] = leakage_pct(
            commitment["ytd_total_category_spend_cents"],
            commitment["ytd_on_contract_spend_cents"],
        )
        if threshold is None or commitment["ytd_leakage_pct"] <= threshold:
            commitment["leakage_flag"] = False
        db.touch(commitment)

        if was_flagged and not commitment["leakage_flag"]:
            member = db.members.get(commitment["member_id"])
            still_flagged = any(
                row["leakage_flag"]
                for row in db.commitments.values()
                if row["member_id"] == commitment["member_id"]
            )
            if member is not None and not still_flagged and member["watchlist_status"] != "NONE":
                member["watchlist_status"] = "NONE"
                db.touch(member)

    for line in file_lines(distributor_file):
        line["classification"] = "UNCLASSIFIED"
        line["contract_units"] = 0
        line["matched_vendor_item_number"] = None

    db.file_load_deltas.pop(distributor_file["id"], None)
