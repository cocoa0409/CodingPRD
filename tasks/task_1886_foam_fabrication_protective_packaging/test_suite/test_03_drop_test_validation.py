"""Drop-test validation: PASS/FAIL computation at record time, laboratory
booking buffers, the cyclic revision loop, and schedule-time pinning."""
from test_helpers import (
    LAB_SLOT_A,
    LAB_SLOT_B,
    QUALITY,
    ApiErrorId,
    approve_spec,
    begin_validation,
    create_customer,
    create_material,
    create_spec,
    create_validated_spec,
    get_spec,
    make_customer_headers,
    patch_spec,
    record_drop_test,
    schedule_drop_test,
    submit_spec,
    validate_error,
    validate_success,
)


def test_drop_test_record_pass_at_exact_limit(api):
    """PRD §3.4: "The `result` is computed at record time: a `measured_peak_g`
    no greater than the pinned `pass_limit_g` yields `PASS`; anything greater
    yields `FAIL`." PRD §3.4: "Recording can also finish the specification's
    validation without further action: when a recorded test pinned to the
    specification's current revision passes, and no recorded test pinned to
    that same current revision carries a `FAIL`, a specification sitting in
    `IN_VALIDATION` advances itself to `VALIDATED`."

    Design: Corner/state_machines/drop_test_record_pass_at_exact_limit
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])  # max_fragility_g 60
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    drop_test = schedule_drop_test(spec["id"], *LAB_SLOT_A)
    assert drop_test["pass_limit_g"] == 60

    recorded = record_drop_test(drop_test["id"], 60)  # measured == limit
    assert recorded["result"] == "PASS", "the <= comparison is inclusive"
    assert recorded["status"] == "RECORDED"
    assert get_spec(spec["id"])["status"] == "VALIDATED"


def test_drop_test_fail_blocks_auto_validation(api):
    """PRD §3.4: "Recording can also finish the specification's validation
    without further action: when a recorded test pinned to the
    specification's current revision passes, and no recorded test pinned to
    that same current revision carries a `FAIL`, a specification sitting in
    `IN_VALIDATION` advances itself to `VALIDATED`."

    Design: Corner/state_machines/drop_test_fail_blocks_auto_validation
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    dt1 = schedule_drop_test(spec["id"], *LAB_SLOT_A)
    dt1 = record_drop_test(dt1["id"], 75)  # 75 > limit 60 -> FAIL
    assert dt1["result"] == "FAIL"

    dt2 = schedule_drop_test(spec["id"], *LAB_SLOT_B, orientation="EDGE")
    dt2 = record_drop_test(dt2["id"], 55)
    assert dt2["result"] == "PASS"
    assert get_spec(spec["id"])["status"] == "IN_VALIDATION", (
        "a recorded FAIL on the current revision blocks auto-validation"
    )


def test_drop_test_window_inverted_rejected(api):
    """PRD §2.8: "A booking whose `scheduled_start` is not before its
    `scheduled_end` is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/drop_test_window_inverted_rejected
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])

    resp = api.create_drop_test(
        {
            "package_spec_id": spec["id"],
            "scheduled_start": "2026-08-02T10:00:00Z",
            "scheduled_end": "2026-08-02T09:00:00Z",
            "drop_height_in": 30,
            "orientation": "FLAT",
        },
        QUALITY,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_lab_booking_rejects_gap_below_thirty_minutes(api):
    """PRD §2.8: "Every booking must keep a gap of at least 30 minutes from
    every other booking, with the buffer applying on both sides of each
    closed interval; a booking that violates the gap is rejected with
    `ERR_LAB_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lab_booking_buffer_intervals
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    schedule_drop_test(spec["id"], *LAB_SLOT_A)  # 09:00-10:00 booked

    resp = api.create_drop_test(
        {
            "package_spec_id": spec["id"],
            "scheduled_start": "2026-08-02T10:15:00Z",  # only 15 min after
            "scheduled_end": "2026-08-02T11:00:00Z",
            "drop_height_in": 30,
            "orientation": "EDGE",
        },
        QUALITY,
    )
    validate_error(resp, ApiErrorId.ERR_LAB_WINDOW_CONFLICT)


def test_lab_booking_accepts_gap_of_exactly_thirty_minutes(api):
    """PRD §2.8: "Every booking must keep a gap of at least 30 minutes from
    every other booking, with the buffer applying on both sides of each
    closed interval; a booking that violates the gap is rejected with
    `ERR_LAB_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lab_booking_buffer_intervals
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    schedule_drop_test(spec["id"], *LAB_SLOT_A)  # 09:00-10:00 booked

    # 10:30 start leaves exactly a 30-minute gap, satisfying the >= rule.
    booking = schedule_drop_test(
        spec["id"], "2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z",
        orientation="CORNER",
    )
    assert booking["status"] == "SCHEDULED"


def test_revision_loop_returns_to_draft_and_recomputes_ild(api):
    """PRD §3.2: "A `QualityEngineer` may return a specification from
    `IN_VALIDATION` or `VALIDATED` back to `DRAFT`." PRD §3.2: "That single
    action increments `revision_no` by 1 and fires the full revision cascade:
    every cut program linked to the specification in `DRAFT`, `NESTED`, or
    `LOCKED` status becomes `OBSOLETE`; every production order referencing
    one of those obsoleted programs with `fab_status` of `QUOTED` or
    `CONFIRMED` becomes `CANCELLED`; and each confirmed order so cancelled
    compensates per §2.9 — its die amortization is returned to the tooling
    and its machine window is freed." PRD §3.2: "While the specification
    remains in `DRAFT`, a `SalesEngineer` may edit its `material_id`,
    `part_length_in`, `part_width_in`, `product_weight_lb`,
    `required_drop_height_in`, or `max_fragility_g`; whenever the weight or
    the drop height changes, `required_ild_lb` is recomputed by the same
    banding."

    Design: Difficulty/non_linear_state_machine/package_spec_revision_loop
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    dt1 = schedule_drop_test(spec["id"], *LAB_SLOT_A)
    dt1 = record_drop_test(dt1["id"], 75)  # FAIL against limit 60
    assert dt1["result"] == "FAIL"

    revised = validate_success(api.return_for_revision(spec["id"], QUALITY))
    assert revised["status"] == "DRAFT", "the revision loop closes back to DRAFT"
    assert revised["revision_no"] == 2, "return-for-revision increments revision_no"

    # PATCH weight 5 -> 4 (drop still 30, MEDIUM band): ceil(4*10) == 40.
    patched = patch_spec(spec["id"], product_weight_lb=4)
    assert patched["required_ild_lb"] == 40


def test_revision_loop_second_pass_reaches_approved(api):
    """PRD §3.2: "A `QualityEngineer` may return a specification from
    `IN_VALIDATION` or `VALIDATED` back to `DRAFT`." PRD §3.2: "That single
    action increments `revision_no` by 1 and fires the full revision cascade:
    every cut program linked to the specification in `DRAFT`, `NESTED`, or
    `LOCKED` status becomes `OBSOLETE`; every production order referencing
    one of those obsoleted programs with `fab_status` of `QUOTED` or
    `CONFIRMED` becomes `CANCELLED`; and each confirmed order so cancelled
    compensates per §2.9 — its die amortization is returned to the tooling
    and its machine window is freed." PRD §3.2: "When the specification has
    reached `VALIDATED`, the owning `Customer` signs off, moving it from
    `VALIDATED` to `APPROVED`; the caller's `X-User-ID` must equal the
    specification's `customer_id`, or the approval is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)." PRD §3.2: "Approval stamps
    `signed_off_at` with the current logical clock; the field is null until
    that moment."

    Design: Difficulty/non_linear_state_machine/package_spec_revision_loop
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    dt1 = schedule_drop_test(spec["id"], *LAB_SLOT_A)
    record_drop_test(dt1["id"], 75)  # FAIL
    validate_success(api.return_for_revision(spec["id"], QUALITY))
    patch_spec(spec["id"], product_weight_lb=4)

    # Second loop forward through the cycle.
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    dt2 = schedule_drop_test(spec["id"], *LAB_SLOT_B, orientation="EDGE")
    record_drop_test(dt2["id"], 55)  # PASS at the current revision
    assert get_spec(spec["id"])["status"] == "VALIDATED"

    approved = approve_spec(spec["id"], customer["id"])
    assert approved["status"] == "APPROVED"
    assert approved["revision_no"] == 2, "approval does not bump the revision"
    assert approved["signed_off_at"] is not None


def test_pass_limit_g_pinned_at_schedule(api):
    """PRD §3.4: "Scheduling pins two values from the specification at that
    moment. The test's `pass_limit_g` copies the specification's
    `max_fragility_g`, and its `spec_revision_no` copies the specification's
    `revision_no`; later edits to the specification never move a scheduled
    test's pins."

    Design: Corner/complexity_layers/pass_limit_g_pinned_at_schedule
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])  # max_fragility_g 60
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    dt1 = schedule_drop_test(spec["id"], *LAB_SLOT_A)
    assert dt1["pass_limit_g"] == 60
    assert dt1["spec_revision_no"] == 1
    record_drop_test(dt1["id"], 75)  # FAIL under the old pin

    # Revision loop lowers max_fragility_g to 50.
    validate_success(api.return_for_revision(spec["id"], QUALITY))
    patch_spec(spec["id"], max_fragility_g=50)
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    dt2 = schedule_drop_test(spec["id"], *LAB_SLOT_B, orientation="EDGE")

    dt1_now = validate_success(api.get_drop_test(dt1["id"], QUALITY))
    assert dt1_now["pass_limit_g"] == 60, (
        "the earlier test keeps the limit pinned at its schedule time"
    )
    assert dt2["pass_limit_g"] == 50, "the new test pins the revised spec's limit"
    assert dt2["spec_revision_no"] == 2


def test_customer_cannot_approve_other_customers_spec(api):
    """PRD §3.2: "When the specification has reached `VALIDATED`, the owning
    `Customer` signs off, moving it from `VALIDATED` to `APPROVED`; the
    caller's `X-User-ID` must equal the specification's `customer_id`, or the
    approval is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_approve_other_customers_spec
    """
    cust_a = create_customer(name="Acme Widgets")
    cust_b = create_customer(name="Beta Corp")
    material = create_material()
    _c, _m, spec = create_validated_spec(customer=cust_a, material=material)
    assert spec["status"] == "VALIDATED"

    resp = api.approve_spec(spec["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert get_spec(spec["id"])["status"] == "VALIDATED"
