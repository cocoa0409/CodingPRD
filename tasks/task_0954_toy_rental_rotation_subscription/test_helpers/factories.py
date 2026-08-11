"""Payload factories — one per writable endpoint, input fields only."""

from .constants import DEFAULT_CHILD_BIRTHDATE, STD_PLAN


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": "m@x.com",
        "full_name": "Test Member",
        "password": "pw",
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(**overrides) -> dict:
    defaults = {
        "name": "Kid",
        "birthdate": DEFAULT_CHILD_BIRTHDATE,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = dict(STD_PLAN)
    defaults.update(overrides)
    return defaults


def create_catalog_item_payload(**overrides) -> dict:
    defaults = {
        "title": "Ball",
        "min_age_months": 12,
        "max_age_months": 36,
        "developmental_stages": ["TODDLER"],
        "piece_count": 1,
        "retail_value_cents": 2000,
        "replacement_value_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_copy_payload(**overrides) -> dict:
    defaults = {
        "barcode": "BC-1",
        "condition_grade": "NEW",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(plan_id) -> dict:
    return {"plan_id": plan_id}


def create_plan_change_payload(plan_id, expected_subscription_version) -> dict:
    return {"plan_id": plan_id,
            "expected_subscription_version": expected_subscription_version}


def create_pause_payload(start_date, duration_days) -> dict:
    return {"start_date": start_date, "duration_days": duration_days}


def create_cancel_payload(reason=None) -> dict:
    return {} if reason is None else {"reason": reason}


def create_box_create_payload(expected_subscription_version) -> dict:
    return {"expected_subscription_version": expected_subscription_version}


def create_wishlist_entry_payload(catalog_item_id, rank=1) -> dict:
    return {"catalog_item_id": catalog_item_id, "rank": rank}


def create_add_item_payload(toy_copy_id, expected_rotation_box_version) -> dict:
    return {"toy_copy_id": toy_copy_id,
            "expected_rotation_box_version": expected_rotation_box_version}


def create_swap_payload(new_toy_copy_id) -> dict:
    return {"new_toy_copy_id": new_toy_copy_id}


def create_accept_hold_payload(rotation_box_id) -> dict:
    return {"rotation_box_id": rotation_box_id}


def create_shipment_payload(carrier="UPS", tracking_number="1Z-OUT") -> dict:
    return {"carrier": carrier, "tracking_number": tracking_number}


def create_shipment_event_payload(event_type, occurred_at) -> dict:
    return {"event_type": event_type, "occurred_at": occurred_at}


def inspection_record(box_item_id, condition_returned="GOOD", damage_severity="NONE",
                      missing_piece_count=0, disposition="RESTOCK") -> dict:
    return {
        "box_item_id": box_item_id,
        "condition_returned": condition_returned,
        "damage_severity": damage_severity,
        "missing_piece_count": missing_piece_count,
        "disposition": disposition,
    }


def create_inspection_payload(items) -> dict:
    return {"items": items}


def create_wallet_adjustment_payload(amount_cents, reason="PROMO_CREDIT", note="") -> dict:
    return {"amount_cents": amount_cents, "reason": reason, "note": note}


def create_pay_fee_payload(payment_source="CARD") -> dict:
    return {"payment_source": payment_source}


def create_dispute_payload(reason="disputing") -> dict:
    return {"reason": reason}


def create_resolve_dispute_payload(outcome="UPHELD") -> dict:
    return {"outcome": outcome}


def create_waive_payload(reason="goodwill") -> dict:
    return {"reason": reason}


def create_report_lost_payload(note=None) -> dict:
    return {} if note is None else {"note": note}
