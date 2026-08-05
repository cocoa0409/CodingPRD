"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_cemetery_payload(**overrides) -> dict:
    defaults = {"name": "Oakwood", "timezone": "UTC", "crew_team_count": 1}
    defaults.update(overrides)
    return defaults


def create_plot_payload(cemetery_id, **overrides) -> dict:
    defaults = {
        "cemetery_id": cemetery_id,
        "section_code": "A",
        "row": "1",
        "plot_number": "1",
        "gis_lat": 1.0,
        "gis_lng": 2.0,
        "plot_type": "GRAVE",
        "interment_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_holder_payload(**overrides) -> dict:
    defaults = {"full_name": "H One", "email": "h1@x.com", "phone": "1"}
    defaults.update(overrides)
    return defaults


def create_decedent_payload(**overrides) -> dict:
    defaults = {"full_name": "Dec A", "date_of_death": "2026-04-01"}
    defaults.update(overrides)
    return defaults


def create_deed_payload(plot_id, holder_id, expected_plot_version,
                        purchase_price_cents=1000000, sale_type="NEW_SALE",
                        **overrides) -> dict:
    defaults = {
        "plot_id": plot_id,
        "holder_id": holder_id,
        "purchase_price_cents": purchase_price_cents,
        "sale_type": sale_type,
        "expected_plot_version": expected_plot_version,
    }
    defaults.update(overrides)
    return defaults


def create_interment_payload(plot_id, decedent_id, deed_id,
                             interment_type="BURIAL", depth_position=1,
                             scheduled_date="2026-06-01",
                             scheduled_start="2026-06-01T09:00:00Z",
                             scheduled_end="2026-06-01T11:00:00Z",
                             **overrides) -> dict:
    defaults = {
        "plot_id": plot_id,
        "decedent_id": decedent_id,
        "deed_id": deed_id,
        "interment_type": interment_type,
        "depth_position": depth_position,
        "scheduled_date": scheduled_date,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_disinterment_payload(interment_id, reason="removal",
                                disinterment_type="REMOVAL",
                                target_plot_id=None, **overrides) -> dict:
    defaults = {
        "interment_id": interment_id,
        "reason": reason,
        "disinterment_type": disinterment_type,
    }
    if target_plot_id is not None:
        defaults["target_plot_id"] = target_plot_id
    defaults.update(overrides)
    return defaults


def create_marker_permit_payload(plot_id, deed_id, marker_type="FLAT",
                                 foundation_length_in=24,
                                 foundation_width_in=12, **overrides) -> dict:
    defaults = {
        "plot_id": plot_id,
        "deed_id": deed_id,
        "marker_type": marker_type,
        "foundation_length_in": foundation_length_in,
        "foundation_width_in": foundation_width_in,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(invoice_id, amount_cents, method="CARD", **overrides) -> dict:
    defaults = {"invoice_id": invoice_id, "amount_cents": amount_cents, "method": method}
    defaults.update(overrides)
    return defaults


def create_care_fund_entry_payload(cemetery_id, entry_type, amount_cents,
                                   source_deed_id=None, note=None, **overrides) -> dict:
    defaults = {
        "cemetery_id": cemetery_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
    }
    if source_deed_id is not None:
        defaults["source_deed_id"] = source_deed_id
    if note is not None:
        defaults["note"] = note
    defaults.update(overrides)
    return defaults
