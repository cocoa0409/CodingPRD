"""Payload factories — one per creatable entity, input fields only.

Each factory returns a dict of the client-supplied fields for a POST; all
server-set / computed fields are omitted. **overrides lets a test control any
value, and an override set to None deletes the key (to exercise missing-field
paths).
"""


def _apply(defaults: dict, overrides: dict) -> dict:
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_fee_schedule_payload(
    violation_class="MAJOR",
    base_fine_cents=20000,
    daily_accrual_cents=500,
    max_total_cents=100000,
    cure_days=14,
    **overrides,
) -> dict:
    return _apply(
        {
            "violation_class": violation_class,
            "base_fine_cents": base_fine_cents,
            "daily_accrual_cents": daily_accrual_cents,
            "max_total_cents": max_total_cents,
            "cure_days": cure_days,
        },
        overrides,
    )


def create_owner_payload(full_name="Test Owner", mailing_email="owner@x.com", **overrides) -> dict:
    return _apply(
        {"full_name": full_name, "mailing_email": mailing_email}, overrides
    )


def create_property_payload(
    owner_id,
    parcel_number="APN-0001",
    street_address="1 Test St",
    occupancy="OCCUPIED",
    **overrides,
) -> dict:
    return _apply(
        {
            "owner_id": owner_id,
            "parcel_number": parcel_number,
            "street_address": street_address,
            "occupancy": occupancy,
        },
        overrides,
    )


def create_case_payload(property_id, **overrides) -> dict:
    return _apply({"property_id": property_id}, overrides)


def create_complaint_payload(
    case_id, reporter_kind="RESIDENT", narrative="Test complaint narrative", **overrides
) -> dict:
    return _apply(
        {"case_id": case_id, "reporter_kind": reporter_kind, "narrative": narrative},
        overrides,
    )


def create_inspection_payload(case_id, kind="INITIAL", notice_id=None, **overrides) -> dict:
    payload = {"case_id": case_id, "kind": kind}
    if notice_id is not None:
        payload["notice_id"] = notice_id
    return _apply(payload, overrides)


def submit_inspection_payload(outcome="VIOLATION_FOUND", **overrides) -> dict:
    return _apply({"outcome": outcome}, overrides)


def create_notice_payload(
    case_id, source_inspection_id, violation_class="MAJOR", **overrides
) -> dict:
    return _apply(
        {
            "case_id": case_id,
            "source_inspection_id": source_inspection_id,
            "violation_class": violation_class,
        },
        overrides,
    )


def contest_notice_payload(scheduled_for, **overrides) -> dict:
    return _apply({"scheduled_for": scheduled_for}, overrides)


def create_reinspection_payload(notice_id, **overrides) -> dict:
    return _apply({"notice_id": notice_id}, overrides)


def reinspection_result_payload(result="PASSED", **overrides) -> dict:
    return _apply({"result": result}, overrides)


def decide_hearing_payload(decision="UPHELD", **overrides) -> dict:
    return _apply({"decision": decision}, overrides)


def reschedule_hearing_payload(scheduled_for, **overrides) -> dict:
    return _apply({"scheduled_for": scheduled_for}, overrides)


def create_abatement_order_payload(
    case_id, action_kind="BOARD_UP", estimated_cost_cents=30000, **overrides
) -> dict:
    return _apply(
        {
            "case_id": case_id,
            "action_kind": action_kind,
            "estimated_cost_cents": estimated_cost_cents,
        },
        overrides,
    )


def complete_abatement_payload(actual_cost_cents=30000, **overrides) -> dict:
    payload = {"actual_cost_cents": actual_cost_cents}
    return _apply(payload, overrides)


def create_lien_payload(case_id, expected_case_version, **overrides) -> dict:
    return _apply(
        {"case_id": case_id, "expected_case_version": expected_case_version}, overrides
    )


def payment_payload(amount_cents, expected_case_version, **overrides) -> dict:
    return _apply(
        {"amount_cents": amount_cents, "expected_case_version": expected_case_version},
        overrides,
    )
