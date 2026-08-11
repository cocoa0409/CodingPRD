"""Findings, triage and the pinned work-order cost chain."""

from test_helpers import (
    AUDITOR,
    DISPATCHER,
    FIELD_TECH,
    STORM_COORDINATOR,
    ApiErrorId,
    assert_same_instant,
    assert_work_order_cost_conservation,
    create_finding_payload,
    create_work_order_payload,
    new_storm_event,
    new_template,
    new_visit,
    record_finding,
    refresh_finding,
    refresh_property,
    refresh_visit,
    refresh_work_order,
    run_visit_to_in_progress,
    set_clock,
    setup_completed_visit,
    setup_subscribed_property,
    setup_triaged_finding,
    setup_work_order,
    triage_finding,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


# --------------------------------------------------------------------------
# Finding lifecycle
# --------------------------------------------------------------------------

def test_a_high_finding_cannot_be_parked_in_monitoring(api):
    """PRD 3.5: "It may be **parked** in `MONITORING`, which is permitted only when
    `severity` is `LOW` or `MEDIUM` — a `HIGH` or `CRITICAL` finding is rejected with
    `ERR_SEVERITY_TOO_HIGH_TO_MONITOR` — and creates no work order."

    Design: Corner/state_machines/finding_monitor_rejected_for_high_severity
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="HIGH", category="HVAC",
                                description="Condenser noise")
    response = api.monitor_finding(ctx["finding_id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_SEVERITY_TOO_HIGH_TO_MONITOR.value)
    assert refresh_finding(ctx["finding_id"])["status"] == "TRIAGED"


def test_triage_requires_the_parent_visit_to_be_completed(api):
    """PRD 3.5: "Triage moves a finding from `OPEN` to `TRIAGED` and requires the parent
    visit to be `COMPLETED`, an incomplete parent being rejected with
    `ERR_PARENT_VISIT_NOT_COMPLETED`."

    Design: Corner/state_machines/finding_triage_before_visit_completed_rejected
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    finding = record_finding(visit["id"], item_code="EXT_WALK", severity="LOW",
                             category="LANDSCAPE", description="Overgrown hedge")

    response = api.triage_finding(finding["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_PARENT_VISIT_NOT_COMPLETED.value)
    reread = refresh_finding(finding["id"])
    assert reread["status"] == "OPEN"
    assert reread["triaged_at"] is None


def test_retriage_from_monitoring_needs_a_later_completed_visit(api):
    """PRD 3.5: "A monitored finding may return to `TRIAGED`, but only when a later
    completed visit exists on the same property whose `completed_at` is strictly greater
    than the finding's `triaged_at`; without one the re-triage is rejected with
    `ERR_NO_RECHECK_VISIT`."

    Design: Corner/errors/err_no_recheck_visit_on_monitoring_retriage_returns_409
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="MEDIUM",
                                category="LANDSCAPE", description="Loose gutter")
    validate_success(api.monitor_finding(ctx["finding_id"], {}, DISPATCHER))

    response = api.triage_finding(ctx["finding_id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_RECHECK_VISIT.value)
    reread = refresh_finding(ctx["finding_id"])
    assert reread["status"] == "MONITORING"
    assert reread["monitor_recheck_count"] == 0


def test_dismissal_is_blocked_while_a_live_work_order_exists(api):
    """PRD 3.5: "It may be **dismissed**, which requires that no work order on it sits
    outside the pair `REJECTED` and `VOID`; a live work order is rejected with
    `ERR_FINDING_HAS_LIVE_WORK_ORDER`."

    Design: Corner/errors/err_finding_has_live_work_order_on_dismiss_returns_409
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="HIGH", category="STRUCTURAL",
                           description="Deck rebuild", estimated_labour_hours=8.0,
                           estimated_parts_cents=28000)
    assert refresh_work_order(ctx["work_order_id"])["status"] == "PENDING_APPROVAL"

    response = api.dismiss_finding(ctx["finding_id"], {}, DISPATCHER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_FINDING_HAS_LIVE_WORK_ORDER.value,
         ApiErrorId.ERR_INVALID_STATE_TRANSITION.value],
    )
    reread = refresh_finding(ctx["finding_id"])
    assert reread["status"] == "WORK_ORDERED"
    assert reread["dismissed_at"] is None


def test_rejecting_a_work_order_returns_the_finding_to_triaged(api):
    """PRD 3.5: "Rejection requires a `rejection_reason` and returns the parent finding
    from `WORK_ORDERED` to `TRIAGED`."

    Design: Corner/state_machines/work_order_reject_bubbles_finding_back_to_triaged
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="HIGH", category="STRUCTURAL",
                           description="Deck rebuild", estimated_labour_hours=8.0,
                           estimated_parts_cents=28000)
    rejected = validate_success(api.reject_work_order(
        ctx["work_order_id"], {"rejection_reason": "Owner will handle privately"},
        ctx["owner_headers"],
    ))
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "Owner will handle privately"
    assert refresh_finding(ctx["finding_id"])["status"] == "TRIAGED"
    _, meta = validate_paginated(
        api.list_work_orders(headers=AUDITOR, params={"finding_id": ctx["finding_id"]})
    )
    assert meta["total_count"] == 1


def test_open_critical_finding_count_is_re_derived_on_dismissal(api):
    """PRD 3.1: "`open_critical_finding_count` counts the property's findings whose
    `severity` is `CRITICAL` and whose `status` is one of `OPEN`, `TRIAGED`,
    `WORK_ORDERED` or `MONITORING`, and is re-derived on every finding creation, triage,
    dismissal and work-order transition."
    PRD 3.5: "Dismissal stamps `dismissed_at` and re-derives the property's
    `open_critical_finding_count`; `DISMISSED` is terminal."

    Design: Corner/cross_cutting_complexity_layers/derived_open_critical_finding_count_reconciles_on_dismissal
    """
    ctx = setup_completed_visit(plan_overrides=STANDARD,
                                item_codes=("EXT_WALK", "INT_WALK"), critical_item_codes=())
    first = record_finding(ctx["visit_id"], item_code="EXT_WALK", severity="CRITICAL",
                           category="ELECTRICAL", description="Exposed conductor")
    second = record_finding(ctx["visit_id"], item_code="INT_WALK", severity="CRITICAL",
                            category="PLUMBING", description="Active leak")
    triage_finding(first["id"])
    triage_finding(second["id"])
    assert refresh_property(ctx)["open_critical_finding_count"] == 2

    dismissed = validate_success(api.dismiss_finding(first["id"], {}, DISPATCHER))
    assert dismissed["status"] == "DISMISSED"
    assert_same_instant(dismissed["dismissed_at"], "2026-06-02T14:00:00Z", "dismissed_at")
    assert refresh_property(ctx)["open_critical_finding_count"] == 1
    assert refresh_finding(second["id"])["status"] == "TRIAGED"


# --------------------------------------------------------------------------
# The cost chain
# --------------------------------------------------------------------------

def test_markup_tier_is_read_off_the_base_not_the_total(api):
    """PRD 3.5: "The second is the value tier, and **the tier is selected on the base —
    labour plus parts, before any markup — never on `total_cents`**, even though the tier
    reads colloquially as the work order's value."
    PRD 3.5: "When the base is at or above 100000 cents, 3 percentage points of relief are
    subtracted from the percentage."

    Design: Difficulty/combinatorial_formula/work_order_total_markup_tier_read_off_base_mode_c
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="HIGH",
                                category="STRUCTURAL", description="Deck rebuild")
    work_order = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], estimated_labour_hours=8.0,
                                  estimated_parts_cents=28000),
        DISPATCHER,
    ), 201)
    assert work_order["labour_cost_cents"] == 68000, "8.0 hours at the default 8500 rate"
    assert work_order["parts_cost_cents"] == 28000
    assert work_order["markup_cents"] == 17280, "base 96000 is below the tier, so 18 percent"
    assert work_order["storm_surcharge_cents"] == 0
    assert work_order["total_cents"] == 113280
    assert work_order["approval_required"] is True
    assert_work_order_cost_conservation(work_order)


def test_volume_relief_applies_at_exactly_the_tier_base(api):
    """PRD 3.5: "When the base is at or above 100000 cents, 3 percentage points of relief
    are subtracted from the percentage. The percentage is applied to the base and rounded
    to whole cents, and `markup_cents` is the smaller of that rounded figure and a cap of
    60000 cents."
    PRD 3.5: "*Step six, the total.* `total_cents` is the base plus `markup_cents` plus
    `storm_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/work_order_total_markup_tier_read_off_base_mode_c
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="HIGH",
                                category="STRUCTURAL", description="Roof rebuild")
    work_order = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], estimated_labour_hours=8.0,
                                  estimated_parts_cents=32000),
        DISPATCHER,
    ), 201)
    assert work_order["labour_cost_cents"] == 68000
    assert work_order["parts_cost_cents"] == 32000
    assert work_order["markup_cents"] == 15000, "base is exactly 100000, so 15 percent applies"
    assert work_order["total_cents"] == 115000
    assert_work_order_cost_conservation(work_order)


def test_volume_relief_arm_of_the_markup_on_a_large_base(api):
    """PRD 3.5: "The first is the bound vendor's `billing_mode`, treated as `MANAGED` when
    no vendor is bound yet: `MANAGED` starts at 18 percent of the base and `PASS_THROUGH`
    starts at 5 percent."
    PRD 3.5: "On the same base the two billing modes differ by 13 percent of the base, and
    the volume relief can push a pass-through vendor to 2 percent while a managed vendor
    lands at 15."

    Design: Corner/calculations/vendor_markup_pass_through_branch_and_volume_relief_tier
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="HIGH",
                                category="STRUCTURAL", description="Full roof replacement")
    work_order = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], estimated_labour_hours=12.0,
                                  estimated_parts_cents=20000),
        DISPATCHER,
    ), 201)
    assert work_order["labour_cost_cents"] == 102000
    assert work_order["parts_cost_cents"] == 20000
    assert work_order["markup_cents"] == 18300, "base 122000 at 15 percent"
    assert work_order["total_cents"] == 140300
    assert work_order["approval_required"] is True
    assert work_order["status"] == "PENDING_APPROVAL"


# --------------------------------------------------------------------------
# The approval fork
# --------------------------------------------------------------------------

def test_the_same_total_needs_owner_approval_on_routine_and_none_on_storm(api):
    """PRD 3.5: "On `ROUTINE` it is the owner's `approval_ceiling_override_cents` when that
    value is present and 50000 cents otherwise, and the approver must be the `Owner`. On
    `STORM` it is a flat 250000 cents, the owner override is structurally not consulted,
    and the approver is the `StormCoordinator`."
    PRD 2.12: "A work order's `pipeline` is a derived discriminator, not an input: it
    reads `STORM` when the work order carries a `storm_event_id`, and `ROUTINE`
    otherwise."

    Design: Difficulty/dual_variant_calc/approval_ceiling_routine_owner_versus_storm_emergency
    """
    ctx = setup_completed_visit(
        plan_overrides=STANDARD,
        owner_overrides={"full_name": "Cy Snowbird", "primary_residence_state": "OH",
                         "approval_ceiling_override_cents": 30000},
        item_codes=("EXT_WALK", "INT_WALK"), critical_item_codes=(),
    )
    routine_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="EXT_WALK", severity="HIGH", category="PLUMBING",
        description="Routine leak")["id"])
    storm_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="INT_WALK", severity="HIGH", category="STRUCTURAL",
        description="Storm-exposed soffit")["id"])
    storm = new_storm_event(name="Hurricane Delta", region_state_code="FL",
                            landfall_eta_at="2026-06-02T18:00:00Z")

    routine_wo = validate_success(api.create_finding_work_order(
        routine_finding["id"],
        create_work_order_payload(routine_finding["version"], estimated_labour_hours=3.5,
                                  estimated_parts_cents=12000),
        DISPATCHER,
    ), 201)
    storm_wo = validate_success(api.create_finding_work_order(
        storm_finding["id"],
        create_work_order_payload(storm_finding["version"], work_type="STORM_MITIGATION",
                                  estimated_labour_hours=3.5, estimated_parts_cents=12000,
                                  storm_event_id=storm["id"]),
        STORM_COORDINATOR,
    ), 201)

    assert routine_wo["total_cents"] == 49265, "29750 labour + 12000 parts + 7515 markup"
    assert storm_wo["total_cents"] == 49265
    assert routine_wo["pipeline"] == "ROUTINE"
    assert storm_wo["pipeline"] == "STORM"
    assert routine_wo["approval_ceiling_cents"] == 30000
    assert storm_wo["approval_ceiling_cents"] == 250000
    assert routine_wo["approval_required"] is True
    assert routine_wo["status"] == "PENDING_APPROVAL"
    assert storm_wo["approval_required"] is False
    assert storm_wo["status"] == "APPROVED"
    assert storm_wo["approved_by_user_id"] == "system"


def test_the_owner_override_is_ignored_on_the_storm_pipeline(api):
    """PRD 3.5: "When `approval_required` comes out false the work order **continues to
    `APPROVED` inside the same submitting request**, with `approved_by_user_id` set to the
    literal string "system"."
    PRD 2.12: "That single field selects the approval ceiling, the surcharge branch and
    the key-custody prerequisite"

    Design: Difficulty/dual_variant_calc/approval_ceiling_routine_owner_versus_storm_emergency
    """
    ctx = setup_completed_visit(plan_overrides=STANDARD,
                                item_codes=("EXT_WALK", "INT_WALK"), critical_item_codes=())
    routine_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="EXT_WALK", severity="HIGH", category="STRUCTURAL",
        description="Deck rebuild")["id"])
    storm_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="INT_WALK", severity="HIGH", category="STRUCTURAL",
        description="Soffit rebuild")["id"])
    storm = new_storm_event(name="Hurricane Echo", region_state_code="FL",
                            landfall_eta_at="2026-06-06T00:00:00Z")

    routine_wo = validate_success(api.create_finding_work_order(
        routine_finding["id"],
        create_work_order_payload(routine_finding["version"], estimated_labour_hours=8.0,
                                  estimated_parts_cents=28000),
        DISPATCHER,
    ), 201)
    storm_wo = validate_success(api.create_finding_work_order(
        storm_finding["id"],
        create_work_order_payload(storm_finding["version"], work_type="STORM_MITIGATION",
                                  estimated_labour_hours=8.0, estimated_parts_cents=28000,
                                  storm_event_id=storm["id"]),
        STORM_COORDINATOR,
    ), 201)

    assert routine_wo["approval_ceiling_cents"] == 50000, "the platform default applies"
    assert routine_wo["approval_required"] is True
    assert storm_wo["approval_ceiling_cents"] == 250000
    assert storm_wo["approval_required"] is False
    assert storm_wo["status"] == "APPROVED"
    assert storm_wo["approved_by_user_id"] == "system"


def test_a_total_exactly_at_the_default_ceiling_needs_no_approval(api):
    """PRD 3.5: "`approval_required` is true exactly when `total_cents` is **strictly
    greater** than `approval_ceiling_cents`: a total of exactly 50000 against the default
    ceiling does not require approval, and 50001 does."

    Design: Difficulty/boundary_precision_check/work_order_total_exactly_at_owner_ceiling_needs_no_approval
    """
    ctx = setup_completed_visit(plan_overrides=STANDARD,
                                item_codes=("EXT_WALK", "INT_WALK"), critical_item_codes=())
    at_ceiling_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="EXT_WALK", severity="HIGH", category="PLUMBING",
        description="At-ceiling repair")["id"])
    over_ceiling_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="INT_WALK", severity="HIGH", category="PLUMBING",
        description="One-cent-over repair")["id"])

    at_ceiling = validate_success(api.create_finding_work_order(
        at_ceiling_finding["id"],
        create_work_order_payload(at_ceiling_finding["version"], estimated_labour_hours=2.0,
                                  estimated_parts_cents=25373),
        DISPATCHER,
    ), 201)
    over_ceiling = validate_success(api.create_finding_work_order(
        over_ceiling_finding["id"],
        create_work_order_payload(over_ceiling_finding["version"], estimated_labour_hours=2.0,
                                  estimated_parts_cents=25374),
        DISPATCHER,
    ), 201)

    assert at_ceiling["markup_cents"] == 7627
    assert at_ceiling["total_cents"] == 50000
    assert at_ceiling["approval_ceiling_cents"] == 50000
    assert at_ceiling["approval_required"] is False
    assert at_ceiling["status"] == "APPROVED"
    assert over_ceiling["markup_cents"] == 7627
    assert over_ceiling["total_cents"] == 50001
    assert over_ceiling["approval_required"] is True
    assert over_ceiling["status"] == "PENDING_APPROVAL"


def test_a_total_exactly_at_the_owner_override_needs_no_approval(api):
    """PRD 3.1: "A third optional input, `approval_ceiling_override_cents`, replaces the
    platform-wide work-order approval ceiling for this owner alone; when it is left null
    the platform default of 50000 cents applies, and when supplied it must be zero or
    greater."
    PRD 3.5: "`approval_required` is true exactly when `total_cents` is **strictly
    greater** than `approval_ceiling_cents`: a total of exactly 50000 against the default
    ceiling does not require approval, and 50001 does."

    Design: Difficulty/boundary_precision_check/work_order_total_exactly_at_owner_ceiling_needs_no_approval
    """
    ctx = setup_completed_visit(
        plan_overrides=STANDARD,
        owner_overrides={"approval_ceiling_override_cents": 30000},
        item_codes=("EXT_WALK", "INT_WALK"), critical_item_codes=(),
    )
    at_ceiling_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="EXT_WALK", severity="MEDIUM", category="PLUMBING",
        description="At override ceiling")["id"])
    above_finding = triage_finding(record_finding(
        ctx["visit_id"], item_code="INT_WALK", severity="MEDIUM", category="PLUMBING",
        description="Above override ceiling")["id"])

    at_ceiling = validate_success(api.create_finding_work_order(
        at_ceiling_finding["id"],
        create_work_order_payload(at_ceiling_finding["version"], estimated_labour_hours=2.0,
                                  estimated_parts_cents=8424),
        DISPATCHER,
    ), 201)
    above = validate_success(api.create_finding_work_order(
        above_finding["id"],
        create_work_order_payload(above_finding["version"], estimated_labour_hours=2.0,
                                  estimated_parts_cents=9000),
        DISPATCHER,
    ), 201)

    assert at_ceiling["approval_ceiling_cents"] == 30000
    assert at_ceiling["total_cents"] == 30000, "base 25424 plus a markup of 4576"
    assert at_ceiling["approval_required"] is False
    assert at_ceiling["status"] == "APPROVED"
    assert at_ceiling["approved_by_user_id"] == "system"
    assert above["approval_ceiling_cents"] == 30000
    assert above["total_cents"] > 30000
    assert above["approval_required"] is True
    assert above["status"] == "PENDING_APPROVAL"


def test_storm_coordinator_cannot_approve_above_the_emergency_ceiling(api):
    """PRD 3.5: "A storm coordinator approving a storm work order may do so only while
    `total_cents` is at or below 250000 — a larger total is rejected with
    `ERR_STORM_CEILING_EXCEEDED` — and the Owner rung is not consulted at all on that
    pipeline."

    Design: Corner/errors/err_storm_ceiling_exceeded_on_coordinator_approval_returns_409
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="CRITICAL",
                                category="STRUCTURAL", description="Structural failure",
                                property_overrides={"label": "BigStorm House",
                                                    "address_line": "250 Ceiling Cir",
                                                    "travel_distance_miles": 18.0})
    storm = new_storm_event(name="Hurricane Mike", region_state_code="FL",
                            landfall_eta_at="2026-06-06T00:00:00Z")
    work_order = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], work_type="STORM_MITIGATION",
                                  estimated_labour_hours=30.0, estimated_parts_cents=20000,
                                  storm_event_id=storm["id"]),
        STORM_COORDINATOR,
    ), 201)
    assert work_order["total_cents"] == 316250
    assert work_order["approval_ceiling_cents"] == 250000
    assert work_order["status"] == "PENDING_APPROVAL"

    response = api.approve_work_order(work_order["id"], {}, STORM_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_STORM_CEILING_EXCEEDED.value)
    reread = refresh_work_order(work_order["id"])
    assert reread["status"] == "PENDING_APPROVAL"
    assert reread["approved_by_user_id"] is None


def test_owner_cannot_approve_a_storm_pipeline_work_order(api):
    """PRD 2.1: "A second role-band rule concerns the approval fork: an `Owner` attempting
    to approve a work order whose pipeline is `STORM`, or a `StormCoordinator` attempting
    to approve one whose pipeline is `ROUTINE`, is rejected with
    `ERR_WORK_ORDER_PIPELINE_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/owner_cannot_approve_a_storm_pipeline_work_order
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="CRITICAL",
                                category="STRUCTURAL",
                                description="Roof structure compromised",
                                owner_overrides={"primary_residence_state": "FL"})
    storm = new_storm_event(name="Hurricane Juliet", region_state_code="FL",
                            landfall_eta_at="2026-06-06T00:00:00Z")
    work_order = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], work_type="STORM_MITIGATION",
                                  estimated_labour_hours=30.0, estimated_parts_cents=20000,
                                  storm_event_id=storm["id"]),
        STORM_COORDINATOR,
    ), 201)
    assert work_order["pipeline"] == "STORM"
    assert work_order["total_cents"] == 316250
    assert work_order["approval_required"] is True

    response = api.approve_work_order(work_order["id"], {}, ctx["owner_headers"])
    assert response.status_code == 403, f"expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_PIPELINE_MISMATCH.value)
    reread = refresh_work_order(work_order["id"])
    assert reread["status"] == "PENDING_APPROVAL"
    assert reread["approved_by_user_id"] is None


def test_field_tech_may_not_create_a_work_order(api):
    """PRD 2.1: "is the technician who physically performs the visit. Arrival and visit
    completion are exclusive to this role. It shares departure, finding recording,
    winterization steps, turnover advance and inspection failure, package logging and the
    post-storm damage assessment with other roles. It cannot create a work order, cannot
    dispatch and cannot touch billing."
    PRD 2.8: "The acting role appears in the endpoint's declared role list, on every
    endpoint. Otherwise `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Corner/rbac/field_tech_cannot_create_a_work_order
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="MEDIUM",
                                category="LANDSCAPE", description="Fallen limb")
    response = api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], estimated_labour_hours=1.0,
                                  estimated_parts_cents=1000),
        FIELD_TECH,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert refresh_finding(ctx["finding_id"])["status"] == "TRIAGED"
    _, meta = validate_paginated(
        api.list_work_orders(headers=AUDITOR, params={"finding_id": ctx["finding_id"]})
    )
    assert meta["total_count"] == 0


def test_second_work_order_replaying_the_pre_create_finding_version_is_stale(api):
    """PRD 2.10: "**Work-order creation against a finding** requires
    `expected_finding_version` carrying the client's last observed `version` of that
    `Finding`. If any writer has advanced the finding's version since the client last read
    it, the create is rejected with `ERR_STALE_FINDING_VERSION` and HTTP 412."
    PRD 2.10: "On success the finding's `version` increments by exactly one, once for the
    request, and the finding row returned by any subsequent read carries the
    post-mutation value."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_finding_version_on_second_work_order_returns_412
    """
    ctx = setup_triaged_finding(plan_overrides=STANDARD, severity="HIGH", category="PLUMBING",
                                description="Burst risk")
    first = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], estimated_labour_hours=2.0,
                                  estimated_parts_cents=5000),
        DISPATCHER,
    ), 201)

    response = api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], estimated_labour_hours=3.0,
                                  estimated_parts_cents=9000),
        DISPATCHER,
    )
    assert response.status_code == 412, f"expected 412, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_STALE_FINDING_VERSION.value)

    rows, meta = validate_paginated(
        api.list_work_orders(headers=AUDITOR, params={"finding_id": ctx["finding_id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == first["id"]
    # base 22000 (2.0h x 8500 + 5000) + 18 % markup 3960 = 25960, which is at or below the
    # default routine ceiling of 50000, so PRD 3.5's approval fork continues the work order
    # to APPROVED inside the same submitting request.
    assert refresh_work_order(first["id"])["status"] == "APPROVED"
    assert refresh_work_order(first["id"])["total_cents"] == 25960
    assert refresh_finding(ctx["finding_id"])["status"] == "WORK_ORDERED"
