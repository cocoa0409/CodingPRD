"""Equipment-sale pipeline: state legality, suspension gates, rework cycle, scheduling geometry."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_practice,
    create_product,
    create_technician,
    create_equipment_sale_payload,
    setup_confirmed_sale,
    setup_accepted_sale,
    drive_sale_to_accepted,
    make_practice_manager_headers,
    make_field_technician_headers,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


def _parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_equipment_sale_accept_from_quote_rejected(api):
    """PRD §3.5: "A `PracticeManager` acting as the sale's practice (any other caller draws
    `ERR_FORBIDDEN`) accepts a `TRAINED` sale, moving it to the terminal `ACCEPTED` state."
    PRD §2.8: "State legality comes fifth on all action endpoints: the requested transition
    must exist from the resource's current state, terminal states reject every transition,
    and violations yield `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/equipment_sale_accept_from_quote_rejected
    """
    practice = create_practice(name="P Q", credit_limit_cents=10000000)
    product = create_product(sku="EQ-11", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    sale = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"]), SALES
        ),
        201,
    )
    assert sale["status"] == "QUOTE"
    res = api.accept_equipment_sale(sale["id"], make_practice_manager_headers(practice["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_equipment_sale(sale["id"], ADMIN), 200)
    assert after["status"] == "QUOTE"
    assert after.get("warranty_agreement_id") is None


def test_equipment_confirm_blocked_by_suspended_practice(api):
    """PRD §3.5: "Confirmation — the rep's `QUOTE` → `CONFIRMED` — is the point of
    commercial commitment and requires the practice to be `ACTIVE`, else
    `ERR_PRACTICE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/equipment_confirm_blocked_by_suspended_practice
    """
    practice = create_practice(name="P XDep", credit_limit_cents=10000000)
    product = create_product(sku="EQ-5", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    sale = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"]), SALES
        ),
        201,
    )
    validate_success(api.suspend_practice(practice["id"], ADMIN), 200)

    res = api.confirm_equipment_sale(sale["id"], SALES)
    validate_error(res, ApiErrorId.ERR_PRACTICE_SUSPENDED)
    after = validate_success(api.get_equipment_sale(sale["id"], ADMIN), 200)
    assert after["status"] == "QUOTE"


def test_equipment_sale_create_blocked_by_suspended_practice(api):
    """PRD §3.5: "the practice must be `ACTIVE` at creation, else `ERR_PRACTICE_SUSPENDED`."
    PRD §3.1: "while `SUSPENDED`, the practice is blocked from new orders, new
    equipment-sale quotes, equipment-sale confirmation, and new trade-in requests, each
    rejected with `ERR_PRACTICE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/equipment_confirm_blocked_by_suspended_practice
    """
    practice = create_practice(name="P XCr", credit_limit_cents=10000000)
    product = create_product(sku="EQ-5C", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    validate_success(api.suspend_practice(practice["id"], ADMIN), 200)
    res = api.create_equipment_sale(
        create_equipment_sale_payload(practice["id"], product["id"]), SALES
    )
    validate_error(res, ApiErrorId.ERR_PRACTICE_SUSPENDED)


def test_equipment_sale_install_rework_cycle(api):
    """PRD §3.5: "If the install fails inspection, the rep may reschedule directly from
    `INSTALLED` back to `INSTALL_SCHEDULED`: the same certification and both overlap checks
    apply, the `install_rework_count` increments by one, and the install-window fields are
    overwritten with the new window." and "Acceptance spawns the manufacturer warranty: a
    new CoverageAgreement is created with `coverage_type` `WARRANTY`, `deductible_cents`
    zero, `coverage_cap_cents` null, `start_date` at the logical now, `end_date` exactly
    the product's `warranty_months` calendar months later, and `status` `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/equipment_sale_install_rework_cycle
    """
    practice = create_practice(name="P Eq", credit_limit_cents=10000000)
    product = create_product(sku="EQ-9", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    tech = create_technician(name="T1", certifications=["INSTALL"])
    sale = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"]), SALES
        ),
        201,
    )
    validate_success(api.confirm_equipment_sale(sale["id"], SALES), 200)
    validate_success(
        api.schedule_install(
            sale["id"],
            {"technician_id": tech["id"],
             "window_start": "2026-08-02T09:00:00Z", "window_end": "2026-08-02T12:00:00Z"},
            SALES,
        ),
        200,
    )
    validate_success(
        api.complete_install(sale["id"], make_field_technician_headers(tech["id"])), 200
    )

    # Rework cycle: INSTALLED -> INSTALL_SCHEDULED.
    reworked = validate_success(
        api.schedule_install(
            sale["id"],
            {"technician_id": tech["id"],
             "window_start": "2026-08-04T09:00:00Z", "window_end": "2026-08-04T12:00:00Z"},
            SALES,
        ),
        200,
    )
    assert reworked["status"] == "INSTALL_SCHEDULED"
    assert reworked["install_rework_count"] == 1
    assert _parse_iso(reworked["install_window_start"]) == datetime(2026, 8, 4, 9, tzinfo=timezone.utc)

    validate_success(
        api.complete_install(sale["id"], make_field_technician_headers(tech["id"])), 200
    )
    validate_success(
        api.complete_training(
            sale["id"], {"training_minutes": 45}, make_field_technician_headers(tech["id"])
        ),
        200,
    )
    accepted = validate_success(
        api.accept_equipment_sale(sale["id"], make_practice_manager_headers(practice["id"])), 200
    )
    assert accepted["status"] == "ACCEPTED"
    warranty_id = accepted.get("warranty_agreement_id")
    assert warranty_id, "Acceptance must spawn the manufacturer warranty"

    warranty = validate_success(api.get_coverage_agreement(warranty_id, ADMIN), 200)
    assert warranty["coverage_type"] == "WARRANTY"
    assert warranty["deductible_cents"] == 0
    assert warranty.get("coverage_cap_cents") is None
    # Accepted at the default logical clock 2026-08-01; warranty_months 12 -> 2027-08-01.
    assert _parse_iso(warranty["start_date"]) == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert _parse_iso(warranty["end_date"]) == datetime(2027, 8, 1, tzinfo=timezone.utc)


def test_equipment_sale_double_rework_increments_count(api):
    """PRD §3.5: "the `install_rework_count` increments by one, and the install-window
    fields are overwritten with the new window." — each INSTALLED → INSTALL_SCHEDULED
    reschedule is one increment.

    Design: Difficulty/non_linear_state_machine/equipment_sale_install_rework_cycle
    """
    practice = create_practice(name="P R2", credit_limit_cents=10000000)
    product = create_product(sku="EQ-9R", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    tech = create_technician(name="T1R", certifications=["INSTALL"])
    sale = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"]), SALES
        ),
        201,
    )
    validate_success(api.confirm_equipment_sale(sale["id"], SALES), 200)
    tech_headers = make_field_technician_headers(tech["id"])
    for window in (
        ("2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"),
        ("2026-08-04T09:00:00Z", "2026-08-04T12:00:00Z"),
        ("2026-08-06T09:00:00Z", "2026-08-06T12:00:00Z"),
    ):
        res = validate_success(
            api.schedule_install(
                sale["id"],
                {"technician_id": tech["id"], "window_start": window[0], "window_end": window[1]},
                SALES,
            ),
            200,
        )
        validate_success(api.complete_install(sale["id"], tech_headers), 200)

    assert res["install_rework_count"] == 2, "Two rework reschedules after the first install"
    assert _parse_iso(res["install_window_start"]) == datetime(2026, 8, 6, 9, tzinfo=timezone.utc)
    validate_success(api.complete_training(sale["id"], {"training_minutes": 45}, tech_headers), 200)
    accepted = validate_success(
        api.accept_equipment_sale(sale["id"], make_practice_manager_headers(practice["id"])), 200
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["install_rework_count"] == 2


def test_install_technician_without_certification_rejected(api):
    """PRD §3.5: "the named technician must be `ACTIVE` and hold the `INSTALL`
    certification, else `ERR_CERTIFICATION_MISSING`".

    Design: Corner/validations/install_technician_without_certification_rejected
    """
    ctx = setup_confirmed_sale()
    tech = create_technician(name="T2", certifications=["REPAIR"])
    res = api.schedule_install(
        ctx["sale"]["id"],
        {"technician_id": tech["id"],
         "window_start": "2026-08-02T09:00:00Z", "window_end": "2026-08-02T12:00:00Z"},
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_CERTIFICATION_MISSING)
    after = validate_success(api.get_equipment_sale(ctx["sale"]["id"], ADMIN), 200)
    assert after["status"] == "CONFIRMED"


def test_technician_half_open_window_overlap(api):
    """PRD §2.9: "an existing commitment spanning from its start to its end conflicts with
    a proposed window if and only if the existing start is strictly before the proposed end
    and the proposed start is strictly before the existing end. Back-to-back commitments
    are therefore allowed — a proposed window whose start equals an existing end, or whose
    end equals an existing start, does not conflict. This half-open test is applied against
    everything on the technician's calendar: their `SCHEDULED` dispatch jobs and their
    `INSTALL_SCHEDULED` equipment-sale install windows alike."

    Design: Difficulty/resource_temporal_overlap/technician_half_open_window_overlap
    """
    practice = create_practice(name="P Ov", credit_limit_cents=10000000)
    product = create_product(sku="EQ-7", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    tech = create_technician(name="T1", certifications=["INSTALL", "REPAIR"])
    sale1 = drive_sale_to_accepted(practice, product, tech)

    # Two adjacent dispatch jobs on 2026-08-10: 10:00-11:00 then 11:00-12:00.
    techs = []
    for issue, window in (
        ("rattle", ("2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")),
        ("buzz", ("2026-08-10T11:00:00Z", "2026-08-10T12:00:00Z")),
    ):
        ticket = validate_success(
            api.create_service_ticket(
                {"practice_id": practice["id"], "equipment_sale_id": sale1["id"],
                 "issue_description": issue},
                DISPATCH,
            ),
            201,
        )
        validate_success(api.assess_coverage(ticket["id"], DISPATCH), 200)
        job = validate_success(
            api.dispatch_ticket(
                ticket["id"],
                {"scheduled_start": window[0], "scheduled_end": window[1]},
                DISPATCH,
            ),
            200,
        )
        techs.append(job["technician_id"])
    assert techs[0] == techs[1] == tech["id"], (
        "The adjacent 11:00-12:00 dispatch is allowed next to 10:00-11:00 (half-open)"
    )

    # A confirmed sale whose proposed install overlaps the technician's 10:00-11:00 job.
    sale2 = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"], sale_price_cents=800000),
            SALES,
        ),
        201,
    )
    validate_success(api.confirm_equipment_sale(sale2["id"], SALES), 200)
    res = api.schedule_install(
        sale2["id"],
        {"technician_id": tech["id"],
         "window_start": "2026-08-10T10:30:00Z", "window_end": "2026-08-10T11:30:00Z"},
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_TECHNICIAN_SCHEDULE_CONFLICT)

    # Touching the 11:00-12:00 job's end is NOT an overlap under half-open semantics.
    ok = validate_success(
        api.schedule_install(
            sale2["id"],
            {"technician_id": tech["id"],
             "window_start": "2026-08-10T12:00:00Z", "window_end": "2026-08-10T13:00:00Z"},
            SALES,
        ),
        200,
    )
    assert ok["status"] == "INSTALL_SCHEDULED"


def test_technician_install_windows_back_to_back(api):
    """PRD §2.9: "Back-to-back commitments are therefore allowed — a proposed window whose
    start equals an existing end, or whose end equals an existing start, does not
    conflict."

    Design: Difficulty/resource_temporal_overlap/technician_half_open_window_overlap
    """
    p1 = create_practice(name="P H1", credit_limit_cents=10000000)
    p2 = create_practice(name="P H2", credit_limit_cents=10000000)
    product = create_product(sku="EQ-7H", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    tech = create_technician(name="TH", certifications=["INSTALL"])

    # Sale at P1 holds the technician's 09:00-12:00 calendar slot (never completed).
    s1 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(p1["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s1["id"], SALES), 200)
    validate_success(
        api.schedule_install(
            s1["id"],
            {"technician_id": tech["id"],
             "window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T12:00:00Z"},
            SALES,
        ),
        200,
    )

    # Same technician, different practice, touching window 12:00-13:00 -> allowed.
    s2 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(p2["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s2["id"], SALES), 200)
    ok = validate_success(
        api.schedule_install(
            s2["id"],
            {"technician_id": tech["id"],
             "window_start": "2026-08-12T12:00:00Z", "window_end": "2026-08-12T13:00:00Z"},
            SALES,
        ),
        200,
    )
    assert ok["status"] == "INSTALL_SCHEDULED"

    # A window strictly inside the technician's existing commitment conflicts.
    s3 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(p2["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s3["id"], SALES), 200)
    res = api.schedule_install(
        s3["id"],
        {"technician_id": tech["id"],
         "window_start": "2026-08-12T10:00:00Z", "window_end": "2026-08-12T11:00:00Z"},
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_TECHNICIAN_SCHEDULE_CONFLICT)


def test_practice_install_bay_closed_interval_overlap(api):
    """PRD §2.9: "a proposed install window conflicts with another `INSTALL_SCHEDULED`
    sale at the same practice if the proposed start is on or before the existing end and
    the existing start is on or before the proposed end. Touching endpoints do conflict
    here — the bay cannot turn over instantly between two installs."

    Design: Difficulty/resource_temporal_overlap/practice_install_bay_closed_interval_overlap
    """
    practice = create_practice(name="P Bay", credit_limit_cents=10000000)
    product = create_product(sku="EQ-8", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    ta = create_technician(name="TA", certifications=["INSTALL"])
    tb = create_technician(name="TB", certifications=["INSTALL"])

    s1 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(practice["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s1["id"], SALES), 200)
    validate_success(
        api.schedule_install(
            s1["id"],
            {"technician_id": ta["id"],
             "window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T12:00:00Z"},
            SALES,
        ),
        200,
    )

    s2 = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"], sale_price_cents=800000),
            SALES,
        ),
        201,
    )
    validate_success(api.confirm_equipment_sale(s2["id"], SALES), 200)

    # Touching endpoint 12:00 conflicts under the bay's closed-interval rule.
    res = api.schedule_install(
        s2["id"],
        {"technician_id": tb["id"],
         "window_start": "2026-08-12T12:00:00Z", "window_end": "2026-08-12T15:00:00Z"},
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_INSTALL_WINDOW_CONFLICT)

    # One minute later clears the shared endpoint.
    ok = validate_success(
        api.schedule_install(
            s2["id"],
            {"technician_id": tb["id"],
             "window_start": "2026-08-12T12:01:00Z", "window_end": "2026-08-12T15:00:00Z"},
            SALES,
        ),
        200,
    )
    assert ok["status"] == "INSTALL_SCHEDULED"


def test_practice_bay_conflict_is_per_practice(api):
    """PRD §2.9: "a proposed install window conflicts with another `INSTALL_SCHEDULED`
    sale at the same practice if the proposed start is on or before the existing end and
    the existing start is on or before the proposed end." — the bay is per-practice, so a
    different practice's bay is unaffected while the same practice's bay conflicts.

    Design: Difficulty/resource_temporal_overlap/practice_install_bay_closed_interval_overlap
    """
    p1 = create_practice(name="P B1", credit_limit_cents=10000000)
    p2 = create_practice(name="P B2", credit_limit_cents=10000000)
    product = create_product(sku="EQ-8B", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12)
    ta = create_technician(name="TBA", certifications=["INSTALL"])
    tb = create_technician(name="TBB", certifications=["INSTALL"])

    s1 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(p1["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s1["id"], SALES), 200)
    validate_success(
        api.schedule_install(
            s1["id"],
            {"technician_id": ta["id"],
             "window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T12:00:00Z"},
            SALES,
        ),
        200,
    )

    # Identical window at a DIFFERENT practice with a free technician -> allowed.
    s2 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(p2["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s2["id"], SALES), 200)
    ok = validate_success(
        api.schedule_install(
            s2["id"],
            {"technician_id": tb["id"],
             "window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T12:00:00Z"},
            SALES,
        ),
        200,
    )
    assert ok["status"] == "INSTALL_SCHEDULED"

    # Strictly-inside window at the SAME practice -> closed-interval conflict.
    # A third technician keeps the technician-calendar check silent so the bay rule fires.
    tc = create_technician(name="TBC", certifications=["INSTALL"])
    s3 = validate_success(
        api.create_equipment_sale(create_equipment_sale_payload(p1["id"], product["id"]), SALES), 201
    )
    validate_success(api.confirm_equipment_sale(s3["id"], SALES), 200)
    res = api.schedule_install(
        s3["id"],
        {"technician_id": tc["id"],
         "window_start": "2026-08-12T10:00:00Z", "window_end": "2026-08-12T11:00:00Z"},
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_INSTALL_WINDOW_CONFLICT)
