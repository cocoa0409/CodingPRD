"""Warranty coverages, callback claims and the remedy work order."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_money,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _remedy_cascade_world():
    """An original completion, an approved PART callback and a started remedy job."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Larkspur Orchard",
        email="ap@larkspur.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="11 Larkspur Ln",
        depth_feet=210.0,
        drawdown=8.0,
        technician_name="Rae Lindqvist",
    )
    plan = fixtures.new_maintenance_plan(world["well_id"], world["account_id"])
    technician_two = fixtures.new_technician("Ola Berg", "JOURNEYMAN", "JUR_BRAVO")
    part = fixtures.new_part("CTL-3000-B", "CONTROL", 3000, on_hand_qty=20)

    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    coverage = fixtures.coverage_of(stage["work_order_id"], "PART")

    fixtures.set_clock("2026-07-01T12:00:00Z")
    claim = fixtures.approved_callback_claim(
        stage["work_order_id"],
        world["account_id"],
        coverage["id"],
        technician_two["id"],
        "PART",
        "Controller failed again after thirty days",
    )
    remedy = fixtures.remedy_work_order(claim["id"], world["technician_id"], "REPAIR")
    fixtures.schedule_work_order(
        remedy["id"], "2026-07-01T13:00:00Z", "2026-07-01T15:00:00Z"
    )
    fixtures.start_work_order(remedy["id"], world["technician_id"])
    fixtures.post_parts(remedy["id"], world["technician_id"], part["id"], 1)

    world.update(
        {
            "plan_id": plan["id"],
            "part_id": part["id"],
            "original_work_order_id": stage["work_order_id"],
            "coverage_id": coverage["id"],
            "claim_id": claim["id"],
            "remedy_work_order_id": remedy["id"],
        }
    )
    return world


def test_completing_a_remedy_job_supersedes_the_claimed_coverage(api):
    """PRD 3.9: "When this work order carries an `origin_callback_claim_id`, the coverage
    named by that claim moves `ACTIVE → SUPERSEDED` with its `superseded_by_id` pointing
    at the newly minted coverage of the same class."
    PRD 3.9: "Because a coverage was superseded, the claim named by
    `origin_callback_claim_id` moves `APPROVED_WARRANTY → RESOLVED_REPAIRED`, and the
    **original** work order's `callback_eligibility` becomes `CONSUMED`."
    PRD 3.12: "A claim against a work order whose `callback_eligibility` is already
    `CONSUMED` is refused with `ERR_CALLBACK_ALREADY_CONSUMED`."

    Design: Difficulty/transitive_cascade/work_order_completion_eight_hop_cascade_through_warranty_callback_and_billing
    """
    world = _remedy_cascade_world()
    completed = validate_success(
        api.complete_work_order(
            world["remedy_work_order_id"],
            {"actual_labor_minutes": 60},
            world["technician_headers"],
        )
    )
    assert completed["fulfillment_status"] == "COMPLETED"
    assert_money(completed["labor_charge_cents"], 9500, "WorkOrder.labor_charge_cents")
    assert_money(completed["parts_charge_cents"], 4800, "WorkOrder.parts_charge_cents")
    assert fixtures.get_part(world["part_id"])["on_hand_qty"] == 18

    coverage = fixtures.get_coverage(world["coverage_id"])
    assert coverage["status"] == "SUPERSEDED"
    assert coverage["superseded_by_id"] is not None

    minted = fixtures.coverages_of(world["remedy_work_order_id"])
    assert len(minted) == 2
    assert sorted(row["coverage_class"] for row in minted) == ["LABOR", "PART"]
    assert all(row["status"] == "ACTIVE" for row in minted)

    assert fixtures.get_claim(world["claim_id"])["status"] == "RESOLVED_REPAIRED"
    assert (
        fixtures.get_work_order(world["original_work_order_id"])["callback_eligibility"]
        == "CONSUMED"
    )

    validate_error(
        api.create_callback_claim(
            world["original_work_order_id"],
            {
                "warranty_coverage_id": world["coverage_id"],
                "complaint_class": "PART",
                "description": "Third attempt on the same controller",
            },
            world["customer_headers"],
        ),
        ApiErrorId.ERR_CALLBACK_ALREADY_CONSUMED.value,
        409,
    )


def test_the_remedy_completion_retimes_the_plan_and_zeroes_its_invoice(api):
    """PRD 3.11: "The whole days from the part coverage's `starts_at` to the claim's
    `submitted_at` must be at most 365 for the parts credit to apply, in which case the
    parts credit is the remedy work order's whole `parts_charge_cents`; the whole days
    from the labour coverage's `starts_at` to the same instant must be at most 90 for the
    labour credit to apply, in which case the labour credit is the remedy work order's
    whole `labor_charge_cents`."
    PRD 3.11: "`taxable_subtotal_cents` is the parts figure less the parts warranty credit
    less the loyalty discount, floored at 0."
    PRD 3.10: "`last_service_date`, by contrast, advances to the visit's `performed_at` on
    a visit of **any** kind, including `SALT_ONLY` and `SERVICE_ONLY` — which is exactly
    why a salt-only visit slides `next_due_at` forward while the plan stays `OVERDUE`."

    Design: Difficulty/transitive_cascade/work_order_completion_eight_hop_cascade_through_warranty_callback_and_billing
    """
    world = _remedy_cascade_world()
    validate_success(
        api.complete_work_order(
            world["remedy_work_order_id"],
            {"actual_labor_minutes": 60},
            world["technician_headers"],
        )
    )
    visits = fixtures.visits_of_plan(world["plan_id"])
    assert len(visits) == 2
    assert all(visit["visit_kind"] == "SERVICE_ONLY" for visit in visits)

    plan = fixtures.get_plan(world["plan_id"])
    assert_instant_equals(
        plan["last_service_date"],
        "2026-07-01T12:00:00Z",
        "MaintenancePlan.last_service_date",
    )
    assert_instant_equals(
        plan["next_due_at"], "2027-03-28T12:00:00Z", "MaintenancePlan.next_due_at"
    )
    assert plan["compliance_state"] == "COMPLIANT"
    assert plan["overdue_latched_at"] is None

    invoice = fixtures.first_invoice_of(world["remedy_work_order_id"])
    assert invoice["variant"] == "ACTUAL_FINAL"
    assert_money(invoice["warranty_credit_cents"], 14300, "Invoice.warranty_credit_cents")
    assert_money(invoice["taxable_subtotal_cents"], 0, "Invoice.taxable_subtotal_cents")
    assert_money(invoice["tax_cents"], 0, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 0, "Invoice.total_cents")

    assert (
        fixtures.get_work_order(world["remedy_work_order_id"])["billing_status"]
        == "PENDING_INVOICE"
    )
    assert_money(
        fixtures.get_account(world["account_id"])["balance_cents"],
        0,
        "Account.balance_cents",
    )


def test_one_completion_mints_two_coverages_with_different_windows(api):
    """PRD 3.9: "One `WarrantyCoverage` of `coverage_class` `PART` is minted per finalised
    entry, each naming its `parts_consumption_entry_id`, and **exactly one** of
    `coverage_class` `LABOR` is minted for the work order with
    `parts_consumption_entry_id` null. Every coverage takes `starts_at` from the work
    order's `actual_end_at` and computes `expires_at` as that instant plus
    `PART_WARRANTY_DAYS` (365 days) for a part coverage or `LABOR_WARRANTY_DAYS` (90 days)
    for the labour coverage — two different windows anchored on the same instant. Each
    opens with `status` `ACTIVE` and `claim_count` 0."
    PRD 3.12: "Coverage is right-closed — at exactly `expires_at` the coverage is still
    `ACTIVE`."

    Design: Corner/calculations/corner_calc_warranty_part_and_labor_windows_diverge_from_one_completion
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Warranty Window Co",
        email="ww@corner.example",
        address_line="365 Warranty",
        technician_name="Warranty Tech",
    )
    part = fixtures.new_part("CTL-5000-W", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )

    coverages = fixtures.coverages_of(stage["work_order_id"])
    assert len(coverages) == 2

    part_coverage = fixtures.coverage_of(stage["work_order_id"], "PART")
    labour_coverage = fixtures.coverage_of(stage["work_order_id"], "LABOR")

    assert_instant_equals(
        part_coverage["starts_at"], "2026-06-01T12:00:00Z", "WarrantyCoverage.starts_at"
    )
    assert_instant_equals(
        part_coverage["expires_at"], "2027-06-01T12:00:00Z", "WarrantyCoverage.expires_at"
    )
    assert part_coverage["status"] == "ACTIVE"
    assert part_coverage["coverage_state"] == "ACTIVE"
    assert part_coverage["claim_count"] == 0

    assert_instant_equals(
        labour_coverage["starts_at"], "2026-06-01T12:00:00Z", "WarrantyCoverage.starts_at"
    )
    assert_instant_equals(
        labour_coverage["expires_at"],
        "2026-08-30T12:00:00Z",
        "WarrantyCoverage.expires_at",
    )
    assert labour_coverage["coverage_state"] == "ACTIVE"
    assert_instant_equals(
        stage["work_order"]["actual_end_at"],
        "2026-06-01T12:00:00Z",
        "WorkOrder.actual_end_at",
    )


def test_the_complaint_class_picks_the_window_that_applies(api):
    """PRD 3.12: "The claim is in warranty when the coverage's `coverage_state` is `ACTIVE`
    and the whole days from `starts_at` to `submitted_at` are at most 365 for a `PART`
    complaint or at most 90 for a `LABOR` complaint. A labour claim filed exactly 90 days
    after the coverage started is in warranty; 91 days is not. A claim raised on day 200
    against the same completion is out of warranty as `LABOR` and in warranty as `PART`."
    PRD 3.12: "The claim records its `original_work_order_id`, stamps `submitted_at` from
    the logical clock, opens at `status` `SUBMITTED` with `remedy_work_order_id` and
    `adjudicated_by_user_id` null, and exposes `days_since_coverage_start` as the whole
    days, floored, from the coverage's `starts_at` to `submitted_at`."

    Design: Corner/calculations/corner_calc_callback_window_right_closed_at_day_ninety_for_labor_only
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Ninety Day Co",
        email="nd@corner.example",
        address_line="90 Callback",
        technician_name="Ninety Tech",
    )
    part = fixtures.new_part("CTL-5000-N", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    part_coverage = fixtures.coverage_of(stage["work_order_id"], "PART")
    labour_coverage = fixtures.coverage_of(stage["work_order_id"], "LABOR")

    fixtures.set_clock("2026-08-30T12:00:00Z")
    day_ninety = validate_success(
        api.create_callback_claim(
            stage["work_order_id"],
            {
                "warranty_coverage_id": labour_coverage["id"],
                "complaint_class": "LABOR",
                "description": "Workmanship complaint filed on day ninety",
            },
            world["customer_headers"],
        ),
        201,
    )
    assert day_ninety["status"] == "SUBMITTED"
    assert day_ninety["days_since_coverage_start"] == 90
    assert_instant_equals(
        day_ninety["submitted_at"], "2026-08-30T12:00:00Z", "CallbackClaim.submitted_at"
    )

    fixtures.set_clock("2026-08-31T12:00:00Z")
    part_claim = validate_success(
        api.create_callback_claim(
            stage["work_order_id"],
            {
                "warranty_coverage_id": part_coverage["id"],
                "complaint_class": "PART",
                "description": "Part complaint filed on day ninety one",
            },
            world["customer_headers"],
        ),
        201,
    )
    assert part_claim["status"] == "SUBMITTED"
    assert part_claim["days_since_coverage_start"] == 91

    validate_error(
        api.create_callback_claim(
            stage["work_order_id"],
            {
                "warranty_coverage_id": labour_coverage["id"],
                "complaint_class": "LABOR",
                "description": "Workmanship complaint filed on day ninety one",
            },
            world["customer_headers"],
        ),
        ApiErrorId.ERR_CALLBACK_OUT_OF_WARRANTY.value,
        409,
    )
    assert fixtures.get_coverage(labour_coverage["id"])["coverage_state"] == "EXPIRED"
    assert fixtures.get_coverage(part_coverage["id"])["coverage_state"] == "ACTIVE"
    assert (
        fixtures.get_work_order(stage["work_order_id"])["callback_eligibility"] == "EXPIRED"
    )


def test_an_out_of_warranty_claim_is_recorded_durably_and_then_errors(api):
    """PRD 2.11: "**A callback claim raised against an out-of-window coverage.** The
    `CallbackClaim` row is created durably with status `REJECTED_OUT_OF_WARRANTY` and
    `submitted_at` stamped, the coverage's `claim_count` and the work order's
    `callback_attempt_count` are incremented, the work order's `callback_eligibility` is
    set to `EXPIRED`, and the work order's and coverage's `version` counters rise — and
    only then does the call return `ERR_CALLBACK_OUT_OF_WARRANTY` (HTTP 409)."

    Design: Corner/state_machines/corner_mutate_then_reject_callback_out_of_warranty_writes_persist
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Callback Late Co",
        email="cl@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="91 Callback",
        technician_name="Late Tech",
    )
    part = fixtures.new_part("CTL-3000-E", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    labour_coverage = fixtures.coverage_of(stage["work_order_id"], "LABOR")
    fixtures.set_clock("2026-08-31T12:00:00Z")

    validate_error(
        api.create_callback_claim(
            stage["work_order_id"],
            {
                "warranty_coverage_id": labour_coverage["id"],
                "complaint_class": "LABOR",
                "description": "Same fault returned after ninety one days",
            },
            world["customer_headers"],
        ),
        ApiErrorId.ERR_CALLBACK_OUT_OF_WARRANTY.value,
        409,
    )
    stored = fixtures.get_coverage(labour_coverage["id"])
    assert_instant_equals(
        stored["expires_at"], "2026-08-30T12:00:00Z", "WarrantyCoverage.expires_at"
    )
    assert stored["coverage_state"] == "EXPIRED"
    assert stored["claim_count"] == 1

    work_order = fixtures.get_work_order(stage["work_order_id"])
    assert work_order["callback_attempt_count"] == 1
    assert work_order["callback_eligibility"] == "EXPIRED"

    claims, _ = validate_paginated(
        api.list_work_order_callback_claims(stage["work_order_id"], DISPATCHER)
    )
    assert len(claims) == 1
    assert claims[0]["status"] == "REJECTED_OUT_OF_WARRANTY"


def test_voiding_a_coverage_twice_is_refused_the_second_time(api):
    """PRD 3.12: "A `PlatformAdmin` may void an `ACTIVE` coverage, provided no claim
    against it sits in `APPROVED_WARRANTY`; a void attempted on a coverage whose stored
    status is already `SUPERSEDED` or already `VOIDED` is refused with
    `ERR_WARRANTY_ALREADY_SUPERSEDED`."
    PRD 3.12: "A coverage's stored `status` is `ACTIVE`, `SUPERSEDED` or `VOIDED`, the
    last two terminal, and its `coverage_state` is derived at read time: `EXPIRED` when
    the stored status is `ACTIVE` and the logical clock is **strictly past** `expires_at`,
    and otherwise simply the stored status."

    Design: Corner/state_machines/corner_warranty_coverage_void_then_second_void_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Void Cov Co",
        email="vc@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="15 Void",
        technician_name="Void Tech",
    )
    part = fixtures.new_part("CTL-3000-F", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    coverage = fixtures.coverage_of(stage["work_order_id"], "PART")

    voided = validate_success(api.void_warranty_coverage(coverage["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert voided["coverage_state"] == "VOIDED"
    assert_instant_equals(
        voided["expires_at"], "2027-06-01T12:00:00Z", "WarrantyCoverage.expires_at"
    )

    validate_error(
        api.void_warranty_coverage(coverage["id"], ADMIN),
        ApiErrorId.ERR_WARRANTY_ALREADY_SUPERSEDED.value,
        409,
    )


def test_the_adjudication_gates_each_own_their_error(api):
    """PRD 2.13: "The `Technician` assigned to a work order must **not** be the one who
    adjudicates a callback claim raised against that work order. If the adjudicating
    `X-User-ID` equals the original work order's `assigned_technician_id`, the request is
    refused with `ERR_CALLBACK_ADJUDICATOR_CONFLICT` (HTTP 403)."
    PRD 3.12: "A `Dispatcher` raises the **remedy work order** from a claim in
    `APPROVED_WARRANTY` that does not already have one; any other claim state, or a claim
    that already carries a `remedy_work_order_id`, is refused with
    `ERR_CALLBACK_CLAIM_INVALID_STATE`."
    PRD 3.12: "From `UNDER_REVIEW`, an `APPROVE` decision requires the coverage's
    `coverage_state` to be `ACTIVE` and requires that the coverage has not already been
    claimed `CALLBACK_MAX_PER_COVERAGE` (2) times — a `claim_count` beyond that limit is
    refused with `ERR_CALLBACK_LIMIT_REACHED`"
    PRD 3.12: "A `REJECT` decision from `UNDER_REVIEW` takes the claim to
    `REJECTED_NOT_DEFECT` and raises its `version` by 1, leaving the original work order's
    eligibility untouched."

    Design: Corner/errors/corner_callback_adjudication_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Adjudicate Co",
        email="ad@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="12 Adjudicate",
        technician_name="Adj Tech One",
    )
    technician_two = fixtures.new_technician("Adj Tech Two", "JOURNEYMAN", "JUR_BRAVO")
    part = fixtures.new_part("CTL-3000-J", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    coverage = fixtures.coverage_of(stage["work_order_id"], "PART")

    fixtures.set_clock("2026-07-01T12:00:00Z")
    claims = [
        fixtures.raise_callback_claim(
            stage["work_order_id"],
            world["account_id"],
            coverage["id"],
            "PART",
            label,
        )
        for label in ("First complaint", "Second complaint", "Third complaint")
    ]

    validate_error(
        api.adjudicate_callback_claim(
            claims[0]["id"], {"decision": "REVIEW"}, world["technician_headers"]
        ),
        ApiErrorId.ERR_CALLBACK_ADJUDICATOR_CONFLICT.value,
        403,
    )
    assert fixtures.get_claim(claims[0]["id"])["status"] == "SUBMITTED"

    validate_error(
        api.create_remedy_work_order(
            claims[0]["id"],
            {"assigned_technician_id": world["technician_id"], "scope": "REPAIR"},
            DISPATCHER,
        ),
        ApiErrorId.ERR_CALLBACK_CLAIM_INVALID_STATE.value,
        409,
    )
    assert fixtures.get_coverage(coverage["id"])["claim_count"] == 3

    fixtures.adjudicate(claims[2]["id"], technician_two["id"], "REVIEW")
    validate_error(
        api.adjudicate_callback_claim(
            claims[2]["id"],
            {"decision": "APPROVE"},
            fixtures.make_technician_headers(technician_two["id"]),
        ),
        ApiErrorId.ERR_CALLBACK_LIMIT_REACHED.value,
        409,
    )
    assert fixtures.get_claim(claims[2]["id"])["status"] == "UNDER_REVIEW"

    fixtures.adjudicate(claims[1]["id"], technician_two["id"], "REVIEW")
    rejected = fixtures.adjudicate(claims[1]["id"], technician_two["id"], "REJECT")
    assert rejected["status"] == "REJECTED_NOT_DEFECT"


def test_a_remedy_completion_credits_both_windows_and_bills_nothing(api):
    """PRD 3.12: "When that remedy work order eventually completes, the coverage it
    remedies moves `ACTIVE → SUPERSEDED` with `superseded_by_id` pointing at the newly
    minted coverage of the same class, the claim moves `APPROVED_WARRANTY →
    RESOLVED_REPAIRED`, and the original work order's `callback_eligibility` becomes
    `CONSUMED` — and the remedy work order's own invoice carries the warranty credit
    computed in Section 3.11."
    PRD 3.9: "A `DRAFT` work order is created with `origin_callback_claim_id` set to the
    claim, `pipeline` `SCHEDULED`, `property_id` and `well_profile_id` copied from the
    original work order, and both `quote_id` and `emergency_ticket_id` left null."
    PRD 3.11: "`warranty_credit_cents` is the sum of the two, expressed as a positive
    number."

    Design: Corner/cross_cutting_complexity_layers/corner_cascade_remedy_work_order_supersedes_the_coverage_and_zeroes_the_invoice
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Remedy Cascade Co",
        email="rc@corner.example",
        address_line="1 Remedy",
        technician_tier="MASTER",
        technician_name="Original Tech",
    )
    technician_two = fixtures.new_technician("Remedy Tech", "MASTER", "JUR_ALPHA")
    part = fixtures.new_part("CTL-5000-R", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    coverage = fixtures.coverage_of(stage["work_order_id"], "PART")

    fixtures.set_clock("2026-07-01T12:00:00Z")
    claim = fixtures.approved_callback_claim(
        stage["work_order_id"],
        world["account_id"],
        coverage["id"],
        technician_two["id"],
        "PART",
        "Replacement control board failed after thirty days",
    )
    remedy = validate_success(
        api.create_remedy_work_order(
            claim["id"],
            {"assigned_technician_id": technician_two["id"], "scope": "REPAIR"},
            DISPATCHER,
        ),
        201,
    )
    assert remedy["pipeline"] == "SCHEDULED"
    assert remedy["origin_callback_claim_id"] == claim["id"]
    assert remedy["quote_id"] is None
    assert remedy["emergency_ticket_id"] is None

    fixtures.schedule_work_order(
        remedy["id"], "2026-07-02T12:00:00Z", "2026-07-02T14:00:00Z"
    )
    fixtures.set_clock("2026-07-02T12:00:00Z")
    fixtures.start_work_order(remedy["id"], technician_two["id"])
    fixtures.post_parts(remedy["id"], technician_two["id"], part["id"], 1)
    completed = validate_success(
        api.complete_work_order(
            remedy["id"],
            {"actual_labor_minutes": 60},
            fixtures.make_technician_headers(technician_two["id"]),
        )
    )
    assert_money(completed["parts_charge_cents"], 8000, "WorkOrder.parts_charge_cents")
    assert_money(completed["labor_charge_cents"], 13500, "WorkOrder.labor_charge_cents")

    resolved = fixtures.get_claim(claim["id"])
    assert resolved["status"] == "RESOLVED_REPAIRED"
    assert resolved["remedy_work_order_id"] == remedy["id"]
    assert resolved["days_since_coverage_start"] == 30

    superseded = fixtures.get_coverage(coverage["id"])
    assert superseded["status"] == "SUPERSEDED"
    minted = fixtures.coverages_of(remedy["id"])
    assert len(minted) == 2
    new_part_coverage = fixtures.coverage_of(remedy["id"], "PART")
    assert superseded["superseded_by_id"] == new_part_coverage["id"]

    assert (
        fixtures.get_work_order(stage["work_order_id"])["callback_eligibility"]
        == "CONSUMED"
    )

    invoice = fixtures.first_invoice_of(remedy["id"])
    assert invoice["variant"] == "ACTUAL_FINAL"
    assert_money(invoice["warranty_credit_cents"], 21500, "Invoice.warranty_credit_cents")
    assert_money(invoice["taxable_subtotal_cents"], 0, "Invoice.taxable_subtotal_cents")
    assert_money(invoice["tax_cents"], 0, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 0, "Invoice.total_cents")
    assert fixtures.get_part(part["id"])["on_hand_qty"] == 8
