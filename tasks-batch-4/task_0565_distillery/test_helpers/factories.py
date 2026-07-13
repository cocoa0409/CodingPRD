"""Payload factories — one per entity, input fields only."""


def create_distillery_payload(**overrides) -> dict:
    payload = {
        "name": "Bench DSP",
        "dsp_permit_number": "DSP-CA-1",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_mash_batch_payload(distillery_id, **overrides) -> dict:
    payload = {
        "distillery_id": distillery_id,
        "grain_bill": "corn/rye",
        "volume_gallons": 200,
    }
    payload.update(overrides)
    return payload


def create_distillation_run_payload(distillery_id, mash_batch_id, **overrides) -> dict:
    payload = {
        "distillery_id": distillery_id,
        "mash_batch_id": mash_batch_id,
        "spirit_type": "WHISKEY",
        "gauge_method": "VOLUME",
        "collected_wine_gallons": 20,
        "collected_proof": 100,
    }
    payload.update(overrides)
    return payload


def create_barrel_payload(distillation_run_id, **overrides) -> dict:
    payload = {
        "distillation_run_id": distillation_run_id,
        "char_level": "CHAR_3",
        "rickhouse_position": "A-1",
        "fill_proof_gallons": 15,
    }
    payload.update(overrides)
    return payload


def create_label_application_payload(distillery_id, **overrides) -> dict:
    payload = {
        "distillery_id": distillery_id,
        "brand_name": "Old Bench",
        "spirit_type": "WHISKEY",
        "label_proof": 100,
        "net_contents_ml": 750,
    }
    payload.update(overrides)
    return payload


def create_bottling_run_payload(barrel_id, label_application_id, **overrides) -> dict:
    payload = {
        "barrel_id": barrel_id,
        "label_application_id": label_application_id,
        "line_id": "LINE_A",
        "scheduled_start": "2026-05-02T08:00:00Z",
        "scheduled_end": "2026-05-02T12:00:00Z",
        "bottle_size_ml": 750,
        "bottles_per_case": 6,
        "planned_cases": 10,
    }
    payload.update(overrides)
    return payload


def create_tax_removal_payload(bottling_run_id, **overrides) -> dict:
    payload = {
        "bottling_run_id": bottling_run_id,
        "removal_reason": "TAXPAID",
        "removed_cases": 3,
    }
    payload.update(overrides)
    return payload


def create_excise_report_payload(distillery_id, expected_distillery_version, **overrides) -> dict:
    payload = {
        "distillery_id": distillery_id,
        "period_month": "2026-05",
        "expected_distillery_version": expected_distillery_version,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Ada Buyer",
        "email": "ada@x.com",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_sales_order_payload(customer_id, bottling_run_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "bottling_run_id": bottling_run_id,
        "channel": "THREE_TIER",
        "cases": 1,
        "unit_price_cents": 5000,
    }
    payload.update(overrides)
    return payload


def create_tour_booking_payload(customer_id, distillery_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "distillery_id": distillery_id,
        "start_time": "2026-06-01T10:00:00Z",
        "end_time": "2026-06-01T11:00:00Z",
        "party_size": 2,
    }
    payload.update(overrides)
    return payload
