"""Entity bookkeeping, feasibility verdicts, and corner calculations
(PRD §2.2–§2.5, §3.1, §3.2, §3.6, §3.7)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_completed_survey,
    create_project_payload,
    create_quoted_project,
    create_registered_project,
    create_service_call,
    create_technician,
    create_unit_with_contract,
    factories,
    get_success_data,
    make_homeowner_headers,
    make_inspector_headers,
    make_installer_headers,
    make_surveyor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


# ===========================================================================
# Queue B — Corner/entities/property_creation_applies_defaults
# ===========================================================================

def test_property_creation_applies_defaults(api):
    """PRD §3.1: "A `ProjectCoordinator` registers a property by supplying
    `owner_user_id` (the opaque identifier of the homeowner, stored so that later
    ownership checks compare `X-User-ID` against it), `address_line`, the two-letter
    `state_code` that will drive the registration requirement, and optionally
    `has_existing_shaft`, which defaults to false when omitted."
    PRD §2.5: "The `version` starts at 1 on creation and increments by 1 on every
    mutation of the resource; `updated_at` is refreshed on the same occasions."

    Design: Corner/entities/property_creation_applies_defaults
    """
    created = validate_success(api.create_property(
        factories.create_property_payload(), COORD), expected_status=201)
    assert created["has_existing_shaft"] is False
    fetched = validate_success(api.get_property(created["id"], COORD))
    assert fetched["has_existing_shaft"] is False
    assert fetched["version"] == 1
    assert fetched["created_at"] == "2026-08-01T00:00:00.000Z"


# ===========================================================================
# Queue B — Corner/entities/property_missing_state_code_invalid_request
# ===========================================================================

def test_property_missing_state_code_invalid_request(api):
    """PRD §2.7: "4. **Body well-formedness and body references** — required fields are
    present, types and enum members are valid, and no unknown fields appear, yielding
    `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/property_missing_state_code_invalid_request
    """
    resp = api.create_property(
        {"owner_user_id": "u-own-1", "address_line": "1 Pine St"}, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Queue B — Corner/entities/property_get_not_found_returns_404
# ===========================================================================

def test_property_get_not_found_returns_404(api):
    """PRD §2.7: "3. **Path existence** — path resource identifiers exist, validated
    left to right along the URL, each yielding its resource-specific not-found error
    (`ERR_PROPERTY_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_PRODUCT_MODEL_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SERVICE_CALL_NOT_FOUND`, `ERR_GRANT_PROGRAM_NOT_FOUND`,
    `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`; all HTTP 404)."

    Design: Corner/entities/property_get_not_found_returns_404
    """
    resp = api.get_property(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)


# ===========================================================================
# Queue B — Corner/entities/product_model_invalid_drive_type_rejected
# ===========================================================================

def test_product_model_invalid_drive_type_rejected(api):
    """PRD §2.8: "Product models are catalogued with a unique `model_code`, a
    `drive_type` of `HYDRAULIC`, `TRACTION`, `PNEUMATIC`, or `PLATFORM_LIFT`".
    PRD §2.7: "required fields are present, types and enum members are valid, and no
    unknown fields appear, yielding `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/product_model_invalid_drive_type_rejected
    """
    resp = api.create_product_model(
        factories.create_product_model_payload(model_code="XXX-1", drive_type="SCREW_DRIVE"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Queue B — Corner/entities/survey_create_computed_field_input_ignored
# ===========================================================================

def test_survey_create_computed_field_input_ignored(api):
    """PRD §3.1: "With a property on file, the coordinator schedules a site survey by
    naming the `property_id`, the `surveyor_technician_id` of an `ACTIVE` technician,
    and a `scheduled_date`. A new survey starts in `SCHEDULED`."
    PRD §2.7: "4. **Body well-formedness and body references** — required fields are
    present, types and enum members are valid, and no unknown fields appear, yielding
    `ERR_INVALID_REQUEST` (HTTP 400)". `feasibility_verdict` is computed at completion
    (§3.1) and is not part of the create contract, so sending it is an unknown field.

    Design: Corner/entities/survey_create_computed_field_input_ignored
    """
    prop = get_success_data(api.create_property(factories.create_property_payload(), COORD))
    surveyor = create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
    payload = factories.create_survey_payload(prop["id"], surveyor["id"])
    payload["feasibility_verdict"] = "INFEASIBLE"  # computed at completion, not input
    resp = api.create_survey(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    surveys, _meta = validate_paginated(api.list_surveys(COORD, params={"property_id": prop["id"]}))
    assert surveys == []


# ===========================================================================
# Queue B — Corner/entities/list_pagination_defaults_and_has_more
# ===========================================================================

def test_list_pagination_defaults_and_has_more(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit`, which defaults to
    10 and must lie between 1 and 100 inclusive, and `offset`, which defaults to 0.
    Results are sorted by `created_at` in ascending order. The `meta` object of a list
    response carries `limit`, `offset`, `total_count`, and `has_more` so that clients
    can page deterministically through the full result set."

    Design: Corner/entities/list_pagination_defaults_and_has_more
    """
    for code, drive in (("HYD-100", "HYDRAULIC"), ("TRC-100", "TRACTION"), ("PNU-100", "PNEUMATIC")):
        get_success_data(api.create_product_model(
            factories.create_product_model_payload(model_code=code, drive_type=drive), ADMIN))
    page1, meta1 = validate_paginated(api.list_product_models(COORD, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_product_models(COORD, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


# ===========================================================================
# Queue B — Corner/entities/technician_version_increments_on_mutation
# ===========================================================================

def test_technician_version_increments_on_mutation(api):
    """PRD §2.5: "The `version` starts at 1 on creation and increments by 1 on every
    mutation of the resource; `updated_at` is refreshed on the same occasions."
    PRD §2.8: "a technician ... starts `ACTIVE`".
    PRD §2.4: "All time-derived behavior in the system is evaluated against a logical
    clock, never against wall-clock time." — the clock is advanced so the refresh is
    observable as a strictly later timestamp.

    Design: Corner/entities/technician_version_increments_on_mutation
    """
    tech = create_technician(name="Ivy Installer", certification="CET")
    assert tech["version"] == 1 and tech["status"] == "ACTIVE"
    get_success_data(api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, ADMIN))
    tech = get_success_data(api.deactivate_technician(tech["id"], ADMIN))
    assert tech["status"] == "INACTIVE"
    assert tech["version"] == 2
    assert tech["updated_at"] > tech["created_at"]


# ===========================================================================
# Queue B — Corner/entities/survey_create_with_missing_property_not_found
# ===========================================================================

def test_survey_create_with_missing_property_not_found(api):
    """PRD §2.7 item 4: "only after that are the body's foreign-key references
    (`property_id`, `survey_id`, `product_model_id`, technician ids, `contractor_id`,
    `project_id`, `unit_id`, `program_id`, `modernize_unit_id`) resolved, each to the
    same not-found set."

    Design: Corner/entities/survey_create_with_missing_property_not_found
    """
    surveyor = create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
    resp = api.create_survey(
        factories.create_survey_payload(NON_EXISTENT_UUID, surveyor["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)


# ===========================================================================
# Queue B — Corner/calculations/feasibility_conditional_verdict
# ===========================================================================

def test_feasibility_conditional_verdict(api):
    """PRD §3.1: "The verdict is `FEASIBLE` when at least one active model fits
    directly; `CONDITIONAL` when none fits directly but at least one fits correctably;
    and `INFEASIBLE` otherwise — including the degenerate case where no active models
    exist at all."

    Design: Corner/calculations/feasibility_conditional_verdict
    """
    _prop, _surveyor, survey = create_completed_survey(
        prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"},
        models=[{"model_code": "HYD-200", "min_pit_depth_inches": 16,
                 "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                 "base_price": 30000.00, "install_labor_price": 9500.00}])
    assert survey["status"] == "COMPLETED"
    assert survey["feasibility_verdict"] == "CONDITIONAL"


# ===========================================================================
# Queue B — Corner/calculations/infeasible_survey_blocks_project_creation
# ===========================================================================

def test_infeasible_survey_blocks_project_creation(api):
    """PRD §3.2: "The survey must be `COMPLETED`, or creation fails with
    `ERR_SURVEY_NOT_COMPLETED`, and its verdict must not be `INFEASIBLE`, or creation
    fails with `ERR_SURVEY_INFEASIBLE`."

    Design: Corner/calculations/infeasible_survey_blocks_project_creation
    """
    prop, _surveyor, survey = create_completed_survey(
        prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"},
        models=[{"model_code": "HYD-200", "min_pit_depth_inches": 16,
                 "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                 "base_price": 30000.00, "install_labor_price": 9500.00}],
        measured_pit_depth_inches=2)
    assert survey["feasibility_verdict"] == "INFEASIBLE"
    resp = api.create_project(create_project_payload(prop["id"], survey["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_SURVEY_INFEASIBLE)
    projects, _meta = validate_paginated(api.list_projects(COORD, params={"property_id": prop["id"]}))
    assert projects == []


# ===========================================================================
# Queue B — Corner/calculations/model_shortfall_beyond_correctable_rejected
# ===========================================================================

def test_model_shortfall_beyond_correctable_rejected(api):
    """PRD §3.2: "The model must fit the survey: recompute the pit and overhead
    shortfalls exactly as the feasibility verdict does, and if either shortfall exceeds
    the 12-inch maximum correctable shortfall the selection is rejected with
    `ERR_MODEL_DOES_NOT_FIT`."

    Design: Corner/calculations/model_shortfall_beyond_correctable_rejected
    """
    # Default catalog model HYD-100 (12/96) fits the survey; the big model needs 25.
    ctx = create_quoted_project()
    big = get_success_data(api.create_product_model(
        factories.create_product_model_payload(
            model_code="HYD-400", min_pit_depth_inches=25, capacity_lbs=1200,
            base_price=40000.00, install_labor_price=12000.00), ADMIN))
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    version_before = project["version"]
    # The project is QUOTED on HYD-100; a re-selection of the non-fitting model fails.
    resp = api.update_project(project["id"], {
        "product_model_id": big["id"],
        "lead_installer_technician_id": ctx["installer"]["id"],
        "expected_project_version": version_before,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_MODEL_DOES_NOT_FIT)
    project = get_success_data(api.get_project(project["id"], COORD))
    assert project["version"] == version_before, "failed selection does not increment"


# ===========================================================================
# Queue B — Corner/calculations/renewal_fee_late_tier1_renews_unit
# ===========================================================================

class TestRenewalFeeLateTier1RenewsUnit:
    def _setup_expired_cert(self, api, clock_after_expiry):
        ctx = create_registered_project()
        # Record a passing ANNUAL so renewal is permitted once the cert is due/expired.
        annual = get_success_data(api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
                scheduled_start="2027-07-01T09:00:00Z",
                scheduled_end="2027-07-01T10:00:00Z"), COORD))
        get_success_data(api.set_clock({"to_iso8601": "2027-07-01T09:05:00Z"}, ADMIN))
        get_success_data(api.record_inspection_result(
            annual["id"], {"result": "PASSED"}, make_inspector_headers(ctx["inspector"]["id"])))
        get_success_data(api.set_clock({"to_iso8601": clock_after_expiry}, ADMIN))
        return ctx

    def test_late_tier1_fee_and_unit_restoration(self, api):
        """PRD §3.6: "the late fee is tiered by whole days late, where days late is
        the floor of the elapsed time past expiration in days, floored at zero: zero
        days late charges the base fee, 1 to 30 days late charges 1.25 times base, and
        31 to 90 days late charges 1.50 times base, each rounded half-up to 2 decimal
        places. Late renewal sets `expiration_date` to one year after the current clock
        and restores the unit — `registration_status` from `LAPSED` back to
        `REGISTERED`, `equipment_status` from `OUT_OF_SERVICE` back to `IN_SERVICE`."

        Design: Corner/calculations/renewal_fee_late_tier1_renews_unit
        """
        # Certificate expires 2027-08-12T10:05:00Z; 2027-09-11 is 30 days late.
        ctx = self._setup_expired_cert(api, "2027-09-11T12:00:00Z")
        cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
        assert cert["status"] == "EXPIRED"
        cert = get_success_data(api.renew_certificate(cert["id"], COORD))
        assert cert["status"] == "ACTIVE"
        assert cert["last_renewal_fee"] == 218.75  # 175.00 x 1.25
        assert cert["renewal_count"] == 1
        assert cert["expiration_date"] == "2028-09-11T12:00:00.000Z"
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
        assert unit["registration_status"] == "REGISTERED"
        assert unit["equipment_status"] == "IN_SERVICE"


# ===========================================================================
# Queue B — Corner/calculations/renewal_beyond_grace_rejected
# ===========================================================================

def test_renewal_beyond_grace_rejected(api):
    """PRD §3.6: "From `EXPIRED`, a late renewal is allowed only within a 90-day grace
    window — the clock must be no later than 90 days past `expiration_date`, otherwise
    `ERR_RENEWAL_GRACE_EXPIRED` and fresh initial registration is required instead".

    Design: Corner/calculations/renewal_beyond_grace_rejected
    """
    ctx = create_registered_project()
    annual = get_success_data(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
            scheduled_start="2027-07-01T09:00:00Z", scheduled_end="2027-07-01T10:00:00Z"),
        COORD))
    get_success_data(api.set_clock({"to_iso8601": "2027-07-01T09:05:00Z"}, ADMIN))
    get_success_data(api.record_inspection_result(
        annual["id"], {"result": "PASSED"}, make_inspector_headers(ctx["inspector"]["id"])))
    # 91 days past expiration 2027-08-12T10:05:00Z.
    get_success_data(api.set_clock({"to_iso8601": "2027-11-12T00:00:00Z"}, ADMIN))
    cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
    assert cert["status"] == "EXPIRED"
    resp = api.renew_certificate(cert["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_GRACE_EXPIRED)
    cert = get_success_data(api.get_certificate(cert["id"], COORD))
    assert cert["status"] == "EXPIRED"
    assert cert["renewal_count"] == 0


# ===========================================================================
# Queue B — Corner/calculations/repair_dispatch_does_not_consume_visit
# ===========================================================================

def test_repair_dispatch_does_not_consume_visit(api):
    """PRD §3.7: "dispatching a `MAINTENANCE_VISIT` under an attached contract requires
    `visits_consumed` to be below `included_visits` (`ERR_NO_VISITS_REMAINING`) and then
    increments `visits_consumed` by 1." — the visit-consumption input set is
    MAINTENANCE_VISIT dispatches only.

    Design: Corner/calculations/repair_dispatch_does_not_consume_visit
    """
    ctx = create_unit_with_contract(tier="STANDARD")
    call = create_service_call(ctx, call_type="REPAIR", description="Noisy door")
    call = get_success_data(api.dispatch_service_call(
        call["id"], {"technician_id": ctx["installer"]["id"]}, COORD))
    assert call["status"] == "DISPATCHED"
    assert call["contract_id"] == ctx["contract"]["id"]
    contract = get_success_data(api.get_service_contract(ctx["contract"]["id"], COORD))
    assert contract["visits_consumed"] == 0


# ===========================================================================
# Queue B — Corner/calculations/after_hours_boundary_seven_am_not_multiplied
# ===========================================================================

def test_after_hours_boundary_seven_am_not_multiplied(api):
    """PRD §3.7: "if the arrival's UTC hour is at or after 18 or before 7 the labor
    amount is multiplied by 1.5 and rounded half-up to 2 decimals; parts cost is then
    added". Arrival at exactly 07:00 is outside the after-hours band.

    Design: Corner/calculations/after_hours_boundary_seven_am_not_multiplied
    """
    ctx = create_registered_project()  # IN_SERVICE unit, no contract -> ad-hoc call
    get_success_data(api.set_clock({"to_iso8601": "2026-09-10T06:30:00Z"}, ADMIN))
    call = create_service_call(ctx, call_type="REPAIR", description="Gate switch")
    assert call["contract_id"] is None
    call = get_success_data(api.dispatch_service_call(
        call["id"], {"technician_id": ctx["installer"]["id"]}, COORD))
    assert call["provisional_estimate"] == 450.00  # ad-hoc flat estimate
    get_success_data(api.set_clock({"to_iso8601": "2026-09-10T07:00:00Z"}, ADMIN))
    get_success_data(api.arrive_service_call(
        call["id"], make_installer_headers(ctx["installer"]["id"])))
    get_success_data(api.set_clock({"to_iso8601": "2026-09-10T07:45:00Z"}, ADMIN))
    call = get_success_data(api.resolve_service_call(
        call["id"], {"resolution_notes": "Adjusted gate switch", "parts_cost": 0.00},
        make_installer_headers(ctx["installer"]["id"])))
    # 45 min on-site -> ceil(45/30) = 2 units x 60.00 = 120.00; hour 07:00 not after-hours.
    assert call["final_billable"] == 120.00


# ===========================================================================
# Queue B — Corner/calculations/sla_breach_credit_applied_with_floor
# ===========================================================================

def test_sla_breach_credit_applied_with_floor(api):
    """PRD §3.7: "an entrapment call whose SLA was breached subtracts a $100.00 credit
    with the result floored at zero."
    PRD §3.7: "`sla_breached` is computed here as true exactly when the elapsed minutes
    from `reported_at` to `arrived_at` are strictly greater than the SLA minutes".

    Design: Corner/calculations/sla_breach_credit_applied_with_floor
    """
    ctx = create_registered_project()
    get_success_data(api.set_clock({"to_iso8601": "2026-09-10T09:00:00Z"}, ADMIN))
    call = create_service_call(ctx, call_type="ENTRAPMENT")
    call = get_success_data(api.dispatch_service_call(
        call["id"], {"technician_id": ctx["installer"]["id"]}, COORD))
    assert call["sla_deadline"] == "2026-09-10T13:00:00.000Z"  # ad-hoc 240 minutes
    get_success_data(api.set_clock({"to_iso8601": "2026-09-10T13:30:00Z"}, ADMIN))
    call = get_success_data(api.arrive_service_call(
        call["id"], make_installer_headers(ctx["installer"]["id"])))
    assert call["sla_breached"] is True  # 270 min > 240
    get_success_data(api.set_clock({"to_iso8601": "2026-09-10T14:00:00Z"}, ADMIN))
    call = get_success_data(api.resolve_service_call(
        call["id"], {"resolution_notes": "Freed passenger", "parts_cost": 0.00},
        make_installer_headers(ctx["installer"]["id"])))
    # 1 half-hour unit x 60.00 = 60.00, minus 100.00 breach credit, floored at 0.
    assert call["final_billable"] == 0.00
