"""Payload factories — one per entity, input fields only."""


def create_inmate_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Person",
        "date_of_birth": "1990-01-01",
        "sex": "MALE",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(inmate_id, **overrides) -> dict:
    defaults = {
        "inmate_id": inmate_id,
        "arrest_datetime": "2026-05-01T00:00:00Z",
        "charge_severity": "MISDEMEANOR",
        "prior_bookings_count": 0,
        "sentence_days": 100,
        "sentence_start_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_classification_payload(assessment_type, expected_booking_version, **overrides) -> dict:
    defaults = {
        "assessment_type": assessment_type,
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_housing_unit_payload(**overrides) -> dict:
    defaults = {
        "name": "Pod-Test",
        "security_level": "MIN",
        "gender": "MALE",
        "capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides) -> dict:
    defaults = {"bed_label": "B1"}
    defaults.update(overrides)
    return defaults


def create_housing_assignment_payload(booking_id, bed_id, start_datetime, end_datetime=None, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "bed_id": bed_id,
        "start_datetime": start_datetime,
    }
    if end_datetime is not None:
        defaults["end_datetime"] = end_datetime
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_order_payload(lines, expected_commissaryaccount_version, **overrides) -> dict:
    defaults = {
        "lines": lines,
        "expected_commissaryaccount_version": expected_commissaryaccount_version,
    }
    defaults.update(overrides)
    return defaults


def order_line(item_name="soap", quantity=1, unit_price_cents=105, taxable=True) -> dict:
    return {
        "item_name": item_name,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "taxable": taxable,
    }


def create_court_event_payload(event_datetime, event_type="ARRAIGNMENT", **overrides) -> dict:
    defaults = {"event_datetime": event_datetime, "event_type": event_type}
    defaults.update(overrides)
    return defaults


def register_visitor_payload(**overrides) -> dict:
    defaults = {"visitor_name": "Test Visitor", "relationship": "FAMILY"}
    defaults.update(overrides)
    return defaults


def create_visit_payload(booking_id, visitor_id, start_datetime, end_datetime, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "visitor_id": visitor_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(request_type="MEDICAL", description="sick call", **overrides) -> dict:
    defaults = {"request_type": request_type, "description": description}
    defaults.update(overrides)
    return defaults


def create_infraction_payload(infraction_type="CONTRABAND", good_time_forfeit_days=3, **overrides) -> dict:
    defaults = {"infraction_type": infraction_type, "good_time_forfeit_days": good_time_forfeit_days}
    defaults.update(overrides)
    return defaults


def create_property_payload(description="silver watch", category="ELECTRONICS", **overrides) -> dict:
    defaults = {"description": description, "category": category}
    defaults.update(overrides)
    return defaults


def release_payload(release_reason="COURT_ORDER", **overrides) -> dict:
    defaults = {"release_reason": release_reason}
    defaults.update(overrides)
    return defaults
