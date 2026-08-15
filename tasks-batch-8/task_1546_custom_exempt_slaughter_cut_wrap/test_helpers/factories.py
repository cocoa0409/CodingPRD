"""Payload factories — one per write endpoint, input fields only (PRD §3)."""


def create_customer_payload(name="Ann Orr", phone="555-0101", email="ann@x.com") -> dict:
    return {"name": name, "phone": phone, "email": email}


def create_capacity_day_payload(date, capacity_head) -> dict:
    return {"date": date, "capacity_head": capacity_head}


def create_appointment_payload(customer_id, capacity_day_id, species, head_count) -> dict:
    return {
        "customer_id": customer_id,
        "capacity_day_id": capacity_day_id,
        "species": species,
        "head_count": head_count,
    }


def pay_deposit_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def reschedule_payload(new_capacity_day_id, expected_appointment_version) -> dict:
    return {
        "new_capacity_day_id": new_capacity_day_id,
        "expected_appointment_version": expected_appointment_version,
    }


def receive_animal_payload(tag_id, live_weight_lbs) -> dict:
    return {"tag_id": tag_id, "live_weight_lbs": live_weight_lbs}


def weigh_animal_payload(hanging_weight_lbs) -> dict:
    return {"hanging_weight_lbs": hanging_weight_lbs}


def add_share_payload(owner_customer_id, share_fraction, intended_use="OWNER_USE") -> dict:
    return {
        "owner_customer_id": owner_customer_id,
        "share_fraction": share_fraction,
        "intended_use": intended_use,
    }


def create_cut_sheet_payload(grind_pct=30, package_weight_lbs=2.0, **optional) -> dict:
    payload = {"grind_pct": grind_pct, "package_weight_lbs": package_weight_lbs}
    payload.update(optional)
    return payload


def revise_cut_sheet_payload(expected_cut_sheet_version, **fields) -> dict:
    payload = {"expected_cut_sheet_version": expected_cut_sheet_version}
    payload.update(fields)
    return payload


def payment_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
