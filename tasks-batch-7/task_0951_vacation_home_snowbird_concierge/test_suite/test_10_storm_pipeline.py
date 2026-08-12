"""The storm pipeline: advisory ladder, sweep deadlines, the deep cascade and assessment."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    STORM_COORDINATOR,
    TECH_ALPHA_ID,
    TECH_BRAVO_ID,
    ApiErrorId,
    activate_grant,
    advisory,
    append_line,
    assert_same_instant,
    assert_work_order_cost_conservation,
    assignment_for,
    complete_visit,
    create_grant,
    create_storm_event_payload,
    create_work_order_payload,
    enrol_storm_response,
    make_field_tech_headers,
    make_vendor_headers,
    new_eligible_vendor,
    new_key_asset,
    new_storm_event,
    new_template,
    new_visit,
    open_draft_invoice,
    raise_storm_to_imminent,
    record_finding,
    refresh_access_grant,
    refresh_invoice,
    refresh_key_asset,
    refresh_property,
    refresh_storm_event,
    refresh_storm_response,
    refresh_visit,
    refresh_work_order,
    run_visit_to_in_progress,
    schedule_sweep,
    set_clock,
    setup_storm_response_assessment_due,
    setup_subscribed_property,
    setup_triaged_finding,
    triage_finding,
    validate_error,
    validate_paginated,
    validate_success,
)

PREMIUM = {"tier": "PREMIUM", "monthly_fee_cents": 34944, "included_visit_units": 8,
           "covered_visit_types": ["ROUTINE_WATCH", "SEASONAL_CLOSE", "SEASONAL_OPEN"],
           "entitlement_rollover_policy": "CARRY_CAPPED", "storm_guarantee_included": True}
STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


# --------------------------------------------------------------------------
# Declaring a storm and the derived tier
# --------------------------------------------------------------------------

def test_a_landfall_eta_at_the_clock_is_refused(api):
    """PRD 3.10: "A storm event is declared with a `name` such as "Hurricane Delta", a
    two-uppercase-letter `region_state_code` and a forecast `landfall_eta_at`, which must
    be strictly after the logical clock — an ETA already in the past is rejected with
    `ERR_LANDFALL_ETA_IN_PAST`."

    Design: Corner/errors/err_landfall_eta_in_past_returns_400
    """
    set_clock("2026-06-10T00:00:00Z")
    response = api.create_storm_event(
        create_storm_event_payload(name="Hurricane Late", region_state_code="FL",
                                   landfall_eta_at="2026-06-10T00:00:00Z"),
        STORM_COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_LANDFALL_ETA_IN_PAST.value)
    _, meta = validate_paginated(api.list_storm_events(headers=AUDITOR))
    assert meta["total_count"] == 0


def test_the_derived_tier_boundary_is_strict_on_the_upper_side(api):
    """PRD 3.10: "`derived_tier` reads the hours from the logical clock to
    `landfall_eta_at`, which may be negative after landfall, and **every boundary is strict
    on the upper side**: more than 48 hours out is `FORECAST`; otherwise more than 24 hours
    out is `WATCH`; otherwise more than 6 hours out is `WARNING`; otherwise the tier is
    `IMMINENT`."
    PRD 3.10: "Exactly 48.0 hours out is therefore `WATCH`, exactly 24.0 is `WARNING`, and
    exactly 6.0 is `IMMINENT`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_storm_tier_boundary_at_exactly_twenty_four_hours
    """
    set_clock("2026-06-03T23:59:00Z")
    storm = new_storm_event(name="Hurricane November", region_state_code="FL",
                            landfall_eta_at="2026-06-05T00:00:00Z")
    assert storm["derived_tier"] == "WATCH", "24.017 hours out is strictly greater than 24"

    set_clock("2026-06-04T00:00:00Z")
    at_boundary = refresh_storm_event(storm["id"])
    assert at_boundary["derived_tier"] == "WARNING", "exactly 24.0 hours out is WARNING"
    assert at_boundary["status"] == "FORECAST", (
        "derived_tier is independent of the operator-driven status"
    )


# --------------------------------------------------------------------------
# The advisory ladder
# --------------------------------------------------------------------------

def test_the_warning_to_watch_downgrade_is_counted_once_and_is_reversible(api):
    """PRD 3.10: "The downgrade from `WARNING` back to `WATCH` — an operator's response to
    a forecast track moving away — advances `downgrade_count` by one, and already-scheduled
    secure sweeps keep their deadline: a downgrade never extends a deadline."
    PRD 3.10: "The event carries an operator-driven `status` and a clock-driven
    `derived_tier`, and the two may legitimately disagree once an operator has downgraded."

    Design: Difficulty/non_linear_state_machine/storm_event_warning_to_watch_bidirectional_downgrade
    """
    set_clock("2026-06-04T20:00:00Z")
    storm = new_storm_event(name="Hurricane Echo", region_state_code="FL",
                            landfall_eta_at="2026-06-05T00:00:00Z")
    assert storm["derived_tier"] == "IMMINENT", "4 hours out is IMMINENT"
    advisory(storm["id"], "WATCH")
    advisory(storm["id"], "WARNING")

    downgraded = advisory(storm["id"], "WATCH")
    assert downgraded["status"] == "WATCH"
    assert downgraded["downgrade_count"] == 1
    assert downgraded["derived_tier"] == "IMMINENT"

    reupgraded = advisory(storm["id"], "WARNING")
    assert reupgraded["status"] == "WARNING"
    assert reupgraded["downgrade_count"] == 1, "the re-upgrade is not a second downgrade"
    assert reupgraded["derived_tier"] == "IMMINENT"
    assert reupgraded["landfall_recorded_at"] is None


def test_a_downgrade_never_extends_an_already_frozen_sweep_deadline(api):
    """PRD 3.10: "It writes `secure_sweep_deadline_at` under the pre-storm branch,
    **anchored on the landfall ETA and subtracting a tier-selected lead**: 48 hours at the
    `FORECAST` tier, 36 at `WATCH`, 18 at `WARNING` and 2 at `IMMINENT`, with the tier read
    at the moment of scheduling and the deadline then frozen — it is never recomputed."
    PRD 3.10: "The move to `WARNING` leaves every `PENDING` response's status untouched and
    **deadlines are not recomputed on an advisory change**."

    Design: Difficulty/non_linear_state_machine/storm_event_warning_to_watch_bidirectional_downgrade
    """
    ctx = setup_subscribed_property(clock="2026-06-04T04:00:00Z", plan_overrides=PREMIUM,
                                    started_on="2026-06-01T00:00:00Z")
    secure_template = new_template("STORM_SECURE", item_codes=["SHUTTERS"], critical_item_codes=[])
    storm = new_storm_event(name="Hurricane Wander", region_state_code="FL",
                            landfall_eta_at="2026-06-05T00:00:00Z")
    assert storm["derived_tier"] == "WARNING", "20 hours out sits in the WARNING band"
    advisory(storm["id"], "WATCH")
    advisory(storm["id"], "WARNING")
    response = enrol_storm_response(storm["id"], ctx["property_id"])
    scheduled = schedule_sweep(response["id"], secure_template["id"], "2026-06-04T05:00:00Z")
    assert scheduled["status"] == "SECURE_SWEEP_SCHEDULED"
    assert_same_instant(scheduled["secure_sweep_deadline_at"], "2026-06-04T06:00:00Z",
                        "secure_sweep_deadline_at")

    downgraded = advisory(storm["id"], "WATCH")
    assert downgraded["downgrade_count"] == 1
    reread = refresh_storm_response(response["id"])
    assert_same_instant(reread["secure_sweep_deadline_at"], "2026-06-04T06:00:00Z",
                        "secure_sweep_deadline_at after the downgrade")
    assert reread["status"] == "SECURE_SWEEP_SCHEDULED"


def test_a_sweep_for_an_out_of_region_property_is_refused(api):
    """PRD 3.10: "It requires the parent event to be in `WATCH`, `WARNING` or `IMMINENT`,
    and requires the property's `state_code` to equal the event's `region_state_code` — a
    mismatch is rejected with `ERR_STORM_REGION_MISMATCH`."

    Design: Corner/errors/err_storm_region_mismatch_for_out_of_state_property_returns_409
    """
    ctx = setup_subscribed_property(
        clock="2026-06-03T00:00:00Z", plan_overrides=PREMIUM,
        owner_overrides={"primary_residence_state": "SC"},
        property_overrides={"label": "SC House", "address_line": "1 Palmetto Pl",
                            "state_code": "SC", "travel_distance_miles": 18.0},
        started_on="2026-06-01T00:00:00Z",
    )
    secure_template = new_template("STORM_SECURE", item_codes=["SHUTTERS"], critical_item_codes=[])
    storm = new_storm_event(name="Hurricane Lima", region_state_code="FL",
                            landfall_eta_at="2026-06-05T00:00:00Z")
    advisory(storm["id"], "WATCH")
    response = enrol_storm_response(storm["id"], ctx["property_id"])

    result = api.schedule_sweep_storm_response(
        response["id"],
        {"checklist_template_id": secure_template["id"],
         "scheduled_start_at": "2026-06-03T06:00:00Z"},
        STORM_COORDINATOR,
    )
    validate_error(result, ApiErrorId.ERR_STORM_REGION_MISMATCH.value)
    reread = refresh_storm_response(response["id"])
    assert reread["status"] == "PENDING"
    assert reread["secure_sweep_visit_id"] is None
    assert refresh_property(ctx)["storm_hold_flag"] is False


# --------------------------------------------------------------------------
# Sweep settlement, the guarantee and closure
# --------------------------------------------------------------------------

def test_closing_a_storm_with_an_unassessed_response_is_refused(api):
    """PRD 3.10: "Closing the event moves it from `ALL_CLEAR` to the terminal `CLOSED`,
    requires every response to be in `ASSESSED` or `CLOSED` — an open response is rejected
    with `ERR_STORM_RESPONSES_OPEN` — moves every `ASSESSED` response to `CLOSED`, and
    clears `storm_hold_flag` on every responded property that has no other open response."
    PRD 3.10: "When that basis is exactly zero the credit is a flat 15000 cents; otherwise
    the credit is the smaller of 15000 cents and half the basis, rounded to whole cents."

    Design: Corner/state_machines/storm_event_close_blocked_while_response_unassessed
    """
    ctx = setup_storm_response_assessment_due()
    response = refresh_storm_response(ctx["storm_response_id"])
    assert response["status"] == "ASSESSMENT_DUE"
    assert response["sweep_on_time"] is True
    assert response["guarantee_credit_cents"] == 15000

    result = api.close_storm_event(ctx["storm_event_id"], {}, STORM_COORDINATOR)
    validate_error(result, ApiErrorId.ERR_STORM_RESPONSES_OPEN.value)
    assert refresh_storm_event(ctx["storm_event_id"])["status"] == "ALL_CLEAR"
    assert refresh_storm_response(ctx["storm_response_id"])["status"] == "ASSESSMENT_DUE"
    assert refresh_property(ctx)["storm_hold_flag"] is True


def test_the_sweep_technician_may_not_sign_the_assessment(api):
    """PRD 2.1: "One authorization rule is not about ownership but about **segregation of
    duties**: the `X-User-ID` signing a post-storm damage assessment must differ from the
    `swept_by_user_id` already recorded on that storm response. If the two are equal the
    request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_same_tech_cannot_sign_own_sweep_assessment
    """
    ctx = setup_storm_response_assessment_due(sweep_tech_id=TECH_ALPHA_ID)
    response = refresh_storm_response(ctx["storm_response_id"])
    assert response["swept_by_user_id"] == TECH_ALPHA_ID

    result = api.create_storm_response_assessment(
        ctx["storm_response_id"],
        {"damage_level": "MINOR", "expected_storm_response_version": response["version"]},
        make_field_tech_headers(TECH_ALPHA_ID),
    )
    assert result.status_code == 403, f"expected 403, got {result.status_code}"
    validate_error(result, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    reread = refresh_storm_response(ctx["storm_response_id"])
    assert reread["status"] == "ASSESSMENT_DUE"
    assert reread["assessed_by_user_id"] is None


def test_a_secondary_landfall_blocks_the_pending_assessment(api):
    """PRD 3.10: "There is a **secondary-landfall edge** back from `ALL_CLEAR` to
    `LANDFALL`, for a stalled system that re-intensifies after the all-clear. It rewrites
    `landfall_recorded_at` to the logical clock and clears `all_clear_at` back to null;
    responses already in `ASSESSMENT_DUE` keep that status and keep their
    `assessment_deadline_at` and are **not** rewound."
    PRD 2.8: "A storm-response assessment is accepted only while the parent storm event is
    in status `ALL_CLEAR`. Otherwise `ERR_STORM_NOT_ALL_CLEAR`, HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/assessment_rejected_while_parent_storm_is_not_all_clear
    """
    ctx = setup_storm_response_assessment_due(sweep_tech_id=TECH_ALPHA_ID)
    before = refresh_storm_response(ctx["storm_response_id"])
    assert before["status"] == "ASSESSMENT_DUE"
    assert_same_instant(before["assessment_deadline_at"], "2026-06-08T06:00:00Z",
                        "assessment_deadline_at")

    set_clock("2026-06-05T10:00:00Z")
    reintensified = validate_success(
        api.landfall_storm_event(ctx["storm_event_id"], {}, STORM_COORDINATOR)
    )
    assert reintensified["status"] == "LANDFALL"
    assert reintensified["all_clear_at"] is None

    result = api.create_storm_response_assessment(
        ctx["storm_response_id"],
        {"damage_level": "MINOR", "expected_storm_response_version": before["version"]},
        make_field_tech_headers(TECH_BRAVO_ID),
    )
    assert result.status_code == 409, f"expected 409, got {result.status_code}"
    validate_error(result, ApiErrorId.ERR_STORM_NOT_ALL_CLEAR.value)
    after = refresh_storm_response(ctx["storm_response_id"])
    assert after["assessed_at"] is None
    assert after["status"] == "ASSESSMENT_DUE"
    assert_same_instant(after["assessment_deadline_at"], "2026-06-08T06:00:00Z",
                        "assessment_deadline_at is not rewound")


def test_an_assessment_signed_while_the_event_is_all_clear_succeeds(api):
    """PRD 3.10: "It moves the response from `ASSESSMENT_DUE` to `ASSESSED`, and carries
    two preconditions beyond the state check: the expected version must equal the
    response's current `version`, and the acting `X-User-ID` must differ from
    `swept_by_user_id`, an identical signer being rejected with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.10: "Signing stamps `assessed_at`, `assessed_by_user_id` and `damage_level`, and
    advances the response's `version` by exactly one."

    Design: Difficulty/cross_entity_state_dependency/assessment_rejected_while_parent_storm_is_not_all_clear
    """
    ctx = setup_storm_response_assessment_due(sweep_tech_id=TECH_ALPHA_ID)
    before = refresh_storm_response(ctx["storm_response_id"])
    assert refresh_storm_event(ctx["storm_event_id"])["status"] == "ALL_CLEAR"

    assessed = validate_success(api.create_storm_response_assessment(
        ctx["storm_response_id"],
        {"damage_level": "MODERATE", "expected_storm_response_version": before["version"]},
        make_field_tech_headers(TECH_BRAVO_ID),
    ))
    assert assessed["status"] == "ASSESSED"
    assert assessed["damage_level"] == "MODERATE"
    assert assessed["assessed_by_user_id"] == TECH_BRAVO_ID
    assert assessed["assessed_at"] is not None
    assert assessed["version"] == before["version"] + 1, (
        "the response's version advances by exactly one"
    )


# --------------------------------------------------------------------------
# The depth-eight completion cascade
# --------------------------------------------------------------------------

def _storm_assess_cascade():
    """Build the storm-assess scenario and return the context plus the pre-existing grant."""
    ctx = setup_subscribed_property(clock="2026-06-01T00:00:00Z", plan_overrides=PREMIUM,
                                    property_overrides={"label": "Storm Cay House",
                                                        "address_line": "2 Cay Rd",
                                                        "travel_distance_miles": 18.0},
                                    started_on="2026-06-01T00:00:00Z")
    vendor = new_eligible_vendor(legal_name="Gulf General LLC", trade="GENERAL",
                                 hourly_rate_cents=8500, rating=4.5, billing_mode="MANAGED",
                                 emergency_capable=True)
    key_asset = new_key_asset(ctx["property_id"], key_type="LOCKBOX", label="Front lockbox",
                              copies_total=2, current_code="1111")
    first_grant = create_grant(key_asset["id"], vendor["id"], "2026-06-01T00:00:00Z",
                               "2026-06-30T00:00:00Z", key_asset["version"])
    activate_grant(first_grant["id"])

    secure_template = new_template("STORM_SECURE", item_codes=["SHUTTERS", "FURNITURE"],
                                   critical_item_codes=[])
    assess_template = new_template("STORM_ASSESS", item_codes=["ROOF_CHECK", "STRUCT_CHECK"],
                                   critical_item_codes=["STRUCT_CHECK"],
                                   default_finding_category="STRUCTURAL")
    storm = new_storm_event(name="Hurricane Foxtrot", region_state_code="FL",
                            landfall_eta_at="2026-06-05T00:00:00Z")
    set_clock("2026-06-04T18:00:00Z")
    raise_storm_to_imminent(storm["id"])
    response = enrol_storm_response(storm["id"], ctx["property_id"])
    response = schedule_sweep(response["id"], secure_template["id"], "2026-06-04T18:30:00Z")
    sweep_visit_id = response["secure_sweep_visit_id"]
    run_visit_to_in_progress(sweep_visit_id, "2026-06-04T19:00:00Z", TECH_ALPHA_ID)
    complete_visit(sweep_visit_id, ["SHUTTERS", "FURNITURE"], [], tech_id=TECH_ALPHA_ID)
    set_clock("2026-06-05T01:00:00Z")
    validate_success(api_landfall(storm["id"]))
    set_clock("2026-06-05T06:00:00Z")
    validate_success(api_all_clear(storm["id"]))

    assess_visit = new_visit(ctx["property_id"], assess_template["id"],
                             visit_type="STORM_ASSESS", trigger_source="STORM",
                             scheduled_start_at="2026-06-05T07:00:00Z",
                             scheduled_end_at="2026-06-05T09:00:00Z",
                             storm_response_id=response["id"])
    run_visit_to_in_progress(assess_visit["id"], "2026-06-05T08:00:00Z", TECH_BRAVO_ID)
    ctx = dict(ctx)
    ctx.update({"vendor": vendor, "vendor_id": vendor["id"], "key_asset": key_asset,
                "key_asset_id": key_asset["id"], "first_grant": first_grant,
                "storm_event_id": storm["id"], "storm_response_id": response["id"],
                "assess_visit_id": assess_visit["id"]})
    return ctx


def api_landfall(storm_event_id):
    from test_helpers import api_client
    return api_client.landfall_storm_event(storm_event_id, {}, STORM_COORDINATOR)


def api_all_clear(storm_event_id):
    from test_helpers import api_client
    return api_client.all_clear_storm_event(storm_event_id, {}, STORM_COORDINATOR)


def test_storm_assess_completion_raises_the_finding_the_order_and_the_offer(api):
    """PRD 3.4: "For every code that appears in `failed_item_codes` and also in the
    template's `critical_item_codes`, a finding is created with `severity` `CRITICAL`,
    `status` `OPEN`, a `category` equal to the template's `default_finding_category`, and a
    `description` that is exactly the literal text "Auto-created from failed critical
    checklist item " followed by the item code."
    PRD 3.4: "A critical finding raised on a `STORM_ASSESS` visit is auto-triaged to
    `TRIAGED` and produces a work order with `work_type` `STORM_MITIGATION`, the storm
    event bound through `storm_event_id`, an `estimated_labour_hours` of 2.0 and an
    `estimated_parts_cents` of 25000, submitted straight to `PENDING_APPROVAL`."
    PRD 3.4: "That storm-pipeline work order, if its `total_cents` is at or below 250000,
    auto-approves with `approved_by_user_id` set to the literal string "system" and
    auto-dispatches over the window running from the logical clock to twenty-four hours
    later, creating a vendor assignment in `OFFERED`."

    Design: Difficulty/transitive_cascade/storm_assess_completion_depth_eight_cascade_to_grant_invalidation
    """
    ctx = _storm_assess_cascade()
    completed = complete_visit(ctx["assess_visit_id"], ["ROOF_CHECK"], ["STRUCT_CHECK"],
                               tech_id=TECH_BRAVO_ID)
    assert completed["status"] == "COMPLETED"

    findings, f_meta = validate_paginated(
        api.list_findings(headers=AUDITOR, params={"visit_id": ctx["assess_visit_id"]})
    )
    assert f_meta["total_count"] == 1
    finding = findings[0]
    assert finding["severity"] == "CRITICAL"
    assert finding["category"] == "STRUCTURAL"
    assert finding["description"] == (
        "Auto-created from failed critical checklist item STRUCT_CHECK"
    )
    assert finding["status"] == "WORK_ORDERED"

    orders, wo_meta = validate_paginated(
        api.list_work_orders(headers=AUDITOR, params={"finding_id": finding["id"]})
    )
    assert wo_meta["total_count"] == 1
    work_order = orders[0]
    assert work_order["pipeline"] == "STORM"
    assert work_order["work_type"] == "STORM_MITIGATION"
    assert work_order["labour_cost_cents"] == 17000, "2.0 hours at the default 8500 rate"
    assert work_order["parts_cost_cents"] == 25000
    assert work_order["markup_cents"] == 7560, "base 42000 at the managed 18 percent"
    assert work_order["status"] == "DISPATCHED"
    assert work_order["dispatch_attempt_count"] == 1
    assert work_order["approved_by_user_id"] == "system"
    assert_work_order_cost_conservation(work_order)

    assignments, a_meta = validate_paginated(
        api.list_vendor_assignments(headers=AUDITOR,
                                    params={"work_order_id": work_order["id"]})
    )
    assert a_meta["total_count"] == 1
    assignment = assignments[0]
    assert assignment["vendor_id"] == ctx["vendor_id"]
    assert assignment["status"] == "OFFERED"
    assert_same_instant(assignment["window_start_at"], "2026-06-05T08:00:00Z",
                        "assignment window_start_at")
    assert_same_instant(assignment["window_end_at"], "2026-06-06T08:00:00Z",
                        "assignment window_end_at")


def test_storm_assess_completion_rotates_the_code_and_invalidates_the_old_grant(api):
    """PRD 3.4: "The new assignment creates a key issuance on the key asset chosen by the
    key-selection rule; the issuance creates an access grant; the grant rotates the lockbox
    code, advancing the key's `code_rotation_count`; and the rotation invalidates every
    access grant whose `rotation_index_at_grant` is strictly less than the new rotation
    count."
    PRD 3.7: "every other grant whose `rotation_index_at_grant` is strictly less than the
    new count is moved to `INVALIDATED` with an `invalidated_reason` of `CODE_ROTATION`;
    and the key asset's `version` advances by one."

    Design: Difficulty/transitive_cascade/storm_assess_completion_depth_eight_cascade_to_grant_invalidation
    """
    ctx = _storm_assess_cascade()
    old_grant = refresh_access_grant(ctx["first_grant"]["id"])
    assert old_grant["status"] == "ACTIVE"
    assert old_grant["rotation_index_at_grant"] == 1
    assert old_grant["code_snapshot"] == "1112"

    complete_visit(ctx["assess_visit_id"], ["ROOF_CHECK"], ["STRUCT_CHECK"],
                   tech_id=TECH_BRAVO_ID)

    issuances, i_meta = validate_paginated(
        api.list_key_issuances(headers=AUDITOR, params={"key_asset_id": ctx["key_asset_id"]})
    )
    assert i_meta["total_count"] == 1
    assert issuances[0]["status"] == "ISSUED"
    assert_same_instant(issuances[0]["return_deadline_at"], "2026-06-06T08:00:00Z",
                        "return_deadline_at")

    grants, g_meta = validate_paginated(
        api.list_access_grants(headers=AUDITOR, params={"key_asset_id": ctx["key_asset_id"]})
    )
    assert g_meta["total_count"] == 2
    new_grant = [g for g in grants if g["id"] != ctx["first_grant"]["id"]][0]
    assert new_grant["status"] == "PENDING"
    assert new_grant["vendor_id"] == ctx["vendor_id"]
    assert new_grant["rotation_index_at_grant"] == 2
    assert new_grant["code_snapshot"] == "1113"

    key_asset = refresh_key_asset(ctx["key_asset_id"])
    assert key_asset["code_rotation_count"] == 2
    assert key_asset["current_code"] == "1113"
    assert key_asset["active_grant_count"] == 0

    invalidated = refresh_access_grant(ctx["first_grant"]["id"])
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["invalidated_reason"] == "CODE_ROTATION"
    assert invalidated["rotation_index_at_grant"] == 1
    assert invalidated["code_snapshot"] == "1112"


# --------------------------------------------------------------------------
# The invoice-level storm surcharge
# --------------------------------------------------------------------------

def test_the_invoice_storm_surcharge_multiplies_net_service(api):
    """PRD 3.11: "`storm_surcharge_cents` is that net service figure multiplied by the
    invoice's `storm_surcharge_pct` and rounded to whole cents. **The order matters: the
    surcharge multiplies the net service, after the entitlement offset has been
    subtracted.** Applying it to `gross_service_cents` instead yields a strictly larger
    total whenever an `ENTITLEMENT_OFFSET` line exists."
    PRD 3.5: "On a `STORM` work order the pre-surcharge amount is `labour_cost_cents` plus
    `parts_cost_cents` plus `markup_cents` — **the basis includes the markup**; applying
    the percentage to labour and parts only is the tempting wrong reading — and
    `storm_surcharge_cents` is that pre-surcharge amount multiplied by the work order's
    `surcharge_pct_applied`, rounded to whole cents."

    Design: Corner/calculations/storm_surcharge_multiplies_net_service_after_the_entitlement_offset
    """
    ctx = setup_triaged_finding(
        plan_overrides=STANDARD,
        property_overrides={"label": "Surcharge House", "address_line": "35 Gale Gr",
                            "travel_distance_miles": 18.0},
        item_codes=("PLUMBING_CHECK",), item_code="PLUMBING_CHECK",
        severity="HIGH", category="PLUMBING", description="Storm-exposed supply line",
    )
    vendor = new_eligible_vendor(legal_name="Gale Plumbing", trade="PLUMBING",
                                 hourly_rate_cents=8500, rating=4.6, billing_mode="MANAGED",
                                 emergency_capable=True)
    new_key_asset(ctx["property_id"], key_type="LOCKBOX", label="Gate lockbox",
                  copies_total=2, current_code="3333")
    storm = new_storm_event(name="Hurricane India", region_state_code="FL",
                            landfall_eta_at="2026-06-05T00:00:00Z")
    work_order = validate_success(api.create_finding_work_order(
        ctx["finding_id"],
        create_work_order_payload(ctx["finding_version"], work_type="STORM_MITIGATION",
                                  estimated_labour_hours=1.0, estimated_parts_cents=10000,
                                  storm_event_id=storm["id"]),
        STORM_COORDINATOR,
    ), 201)

    set_clock("2026-06-04T20:00:00Z")
    raise_storm_to_imminent(storm["id"])
    enrol_storm_response(storm["id"], ctx["property_id"])
    dispatched = validate_success(api.dispatch_work_order(
        work_order["id"],
        {"window_start_at": "2026-06-04T20:00:00Z", "window_end_at": "2026-06-04T23:00:00Z"},
        STORM_COORDINATOR,
    ))
    assert dispatched["surcharge_pct_applied"] == 0.35

    assignment = assignment_for(work_order["id"], vendor["id"])
    vendor_headers = make_vendor_headers(vendor["id"])
    validate_success(api.accept_vendor_assignment(assignment["id"], {}, vendor_headers))
    validate_success(api.start_work_vendor_assignment(assignment["id"], {}, vendor_headers))
    validate_success(api.finish_work_vendor_assignment(assignment["id"], {}, vendor_headers))
    completed = validate_success(api.complete_work_order(
        work_order["id"], {"actual_labour_hours": 1.0, "actual_parts_cents": 10000},
        vendor_headers,
    ))
    assert completed["storm_surcharge_cents"] == 7641, "round_half_up(21830 * 0.35)"
    assert completed["total_cents"] == 29471
    assert_work_order_cost_conservation(completed)

    invoice = open_draft_invoice(ctx["cycle_id"])
    validate_success(api.invoice_work_order(work_order["id"], {"invoice_id": invoice["id"]},
                                            ACCOUNT_MANAGER))
    append_line(invoice["id"], line_type="ENTITLEMENT_OFFSET",
                description="Included visit offset", amount_cents=-6500, taxable=True)

    final = refresh_invoice(invoice["id"])
    assert final["storm_surcharge_pct"] == 0.35
    assert final["gross_service_cents"] == 49457
    assert final["entitlement_offset_cents"] == -6500
    assert final["storm_surcharge_cents"] == 15035, "round_half_up(42957 * 0.35)"
    assert final["subtotal_cents"] == 57992
    assert final["tax_cents"] == 4059
    assert final["total_cents"] == 62051
