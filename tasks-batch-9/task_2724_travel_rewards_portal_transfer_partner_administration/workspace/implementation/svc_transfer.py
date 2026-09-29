"""Grandfathered ratio resolution and per-block partner unit arithmetic (PRD 3.8, 3.10)."""

from core import DB, dec, find, floor_int

BLOCK = 1000


def resolve_ratio(account, agreement):
    """The applied ratio comes from the account's governing notice when it rewrites
    exactly this agreement; otherwise from the agreement itself."""
    notice_id = account.get("terms_notice_id")
    if notice_id:
        notice = find("notices", notice_id)
        if (
            notice is not None
            and notice["status"] == "EFFECTIVE"
            and notice["change_type"] == "TRANSFER_RATIO_CHANGE"
            and notice.get("target_agreement_id") == agreement["id"]
            and notice.get("new_ratio_points_out")
            and notice.get("new_ratio_partner_units_in")
        ):
            return notice["new_ratio_points_out"], notice["new_ratio_partner_units_in"]
    return agreement["ratio_points_out"], agreement["ratio_partner_units_in"]


def per_block_units(ratio_points_out, ratio_partner_units_in):
    """Units earned by one 1,000-point block, floored."""
    return floor_int(dec(BLOCK) * dec(ratio_partner_units_in) / dec(ratio_points_out))


def compute_units(points_out, ratio_points_out, ratio_partner_units_in, event):
    """base_units are summed per floored block; the bonus rides the per-block figure."""
    blocks = points_out // BLOCK
    unit_block = per_block_units(ratio_points_out, ratio_partner_units_in)
    base_units = unit_block * blocks
    bonus_units = 0
    if event is not None:
        eligible_blocks = min(blocks, event["cap_points_per_account"] // BLOCK)
        bonus_block = floor_int(dec(unit_block) * dec(event["bonus_bps"]) / dec(10000))
        bonus_units = bonus_block * eligible_blocks
    return base_units, bonus_units


def complete_units(transfer, agreement, account):
    ratio_out, ratio_in = resolve_ratio(account, agreement)
    transfer["ratio_points_out_applied"] = ratio_out
    transfer["ratio_partner_units_in_applied"] = ratio_in
    event = None
    if transfer.get("bonus_event_id"):
        event = find("bonus_events", transfer["bonus_event_id"])
    base_units, bonus_units = compute_units(
        transfer["points_out"], ratio_out, ratio_in, event
    )
    transfer["base_units"] = base_units
    transfer["bonus_units"] = bonus_units
    transfer["partner_units_credited"] = base_units + bonus_units
    return transfer


def pin_bonus_event(agreement_id, instant):
    """The RUNNING event whose closed window contains the submission instant."""
    from core import parse_dt

    candidates = []
    for event in DB["bonus_events"].values():
        if event["partner_agreement_id"] != agreement_id:
            continue
        if event["status"] != "RUNNING":
            continue
        start = parse_dt(event["window_start"])
        end = parse_dt(event["window_end"])
        if start <= instant <= end:
            candidates.append(event)
    if not candidates:
        return None
    candidates.sort(key=lambda e: (e["window_start"], e["created_at"], e["_seq"]))
    return candidates[0]
