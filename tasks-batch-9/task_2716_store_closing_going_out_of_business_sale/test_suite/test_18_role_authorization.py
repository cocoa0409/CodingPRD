"""Role authority, store ownership and identity resolution.

These cases hold the five declared roles to the operations each one owns, the
operations they share, the ownership boundary that follows a store manager's
identity, and the two header layers that run ahead of the role check.
"""
from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_ID,
    LIQUIDATION_CONSULTANT_ID,
    NON_EXISTENT_UUID,
    SECOND_COMPLIANCE_OFFICER_ID,
    add_markdown_stage,
    api_client,
    apply_for_license,
    assert_employee,
    assert_expense_item,
    assert_gob_license,
    assert_inventory_lot,
    assert_markdown_stage,
    assert_sales_day,
    build_user_headers,
    employee_payload,
    engagement_payload,
    expense_item_payload,
    gob_license_payload,
    inventory_lot_payload,
    jurisdiction_payload,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    make_store_manager_headers,
    markdown_stage_payload,
    pin_clock,
    read_store,
    sales_day_payload,
    setup_approved_engagement,
    setup_selling_engagement,
    setup_selling_store,
    store_payload,
    store_version,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_DAY_ONE = "2026-09-15T00:00:00Z"
CLOCK_DAY_TWO = "2026-09-16T00:00:00Z"

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}

HOME_LOT = {
    "category": "HOME", "source": "ORIGINAL", "units_initial": 100,
    "unit_cost_cents": 3000, "unit_retail_cents": 8000,
}

LICENSE_PERIOD = {
    "period_start_date": "2026-09-15", "period_end_date": "2026-10-14",
}

FIRST_STAGE = {
    "stage_index": 1, "discount_pct": 0.2, "sell_through_target_pct": 0.25,
    "window_start_date": "2026-09-16", "window_end_date": "2026-10-01",
}

TWENTY_UNIT_DAY = {
    "business_date": "2026-09-15", "original_net_sales_cents": 60000,
    "augmentation_net_sales_cents": 0, "original_units_sold": 20,
    "augmentation_units_sold": 0,
}

TEN_UNIT_DAY = {
    "business_date": "2026-09-16", "original_net_sales_cents": 30000,
    "augmentation_net_sales_cents": 0, "original_units_sold": 10,
    "augmentation_units_sold": 0,
}


def _role_by_role_chain_to_a_selling_store(store_code, license_number):
    """Drive the chain to a selling store one role at a time, asserting each code.

    Returns a dict with the ``jurisdiction``, ``engagement``, ``store`` and
    ``license`` rows, each read back from the response that created it.
    """
    clock = validate_success(api_client.set_clock(CLOCK_DAY_ONE))
    jurisdiction = validate_success(
        api_client.create_jurisdiction(
            jurisdiction_payload(**NY_RULES), make_compliance_headers()
        ),
        201,
    )
    engagement = validate_success(
        api_client.create_engagement(engagement_payload(), make_consultant_headers()),
        201,
    )
    store = validate_success(
        api_client.create_store(
            engagement["id"],
            store_payload(
                jurisdiction["id"], store_code=store_code,
                address_line=f"{store_code} Liquidation Row",
            ),
            make_consultant_headers(),
        ),
        201,
    )
    lot = validate_success(
        api_client.create_inventory_lot(
            store["id"], inventory_lot_payload(**APPAREL_LOT), make_consultant_headers()
        ),
        201,
    )
    submitted = validate_success(
        api_client.submit_engagement_for_approval(
            engagement["id"], make_consultant_headers()
        ),
        200,
    )
    engagement = validate_success(
        api_client.decide_engagement_approval(
            engagement["id"], {"decision": "APPROVE"}, make_controller_headers()
        ),
        200,
    )
    application = validate_success(
        api_client.create_gob_license(
            store["id"],
            gob_license_payload(license_number=license_number, **LICENSE_PERIOD),
            make_compliance_headers(),
        ),
        201,
    )
    license_row = validate_success(
        api_client.decide_gob_license(
            application["id"], {"decision": "APPROVE"},
            make_compliance_headers(SECOND_COMPLIANCE_OFFICER_ID),
        ),
        200,
    )
    return {
        "clock": clock,
        "jurisdiction": jurisdiction,
        "engagement": engagement,
        "submitted": submitted,
        "store": read_store(store["id"]),
        "lot": lot,
        "application": application,
        "license": license_row,
    }


class TestEachRoleRunsItsOwnExclusiveOperations:
    def test_the_clock_needs_no_identity_and_the_officer_owns_the_licence_track(self):
        """One unauthenticated clock call, then jurisdiction, application and decision.

        The PRD says: "A `SystemOperator` sets it by supplying `current_utc`, an ISO
        8601 UTC timestamp, and the clock endpoint is the single endpoint that does not
        require `X-User-ID`. … Only a `ComplianceOfficer` may register jurisdictions,
        file and decide licence applications, revoke licences, file augmentation
        disclosures, suspend and resume stores, and run the compliance sweep."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        scenario = _role_by_role_chain_to_a_selling_store("S-7001", "NY-GOB-7001")
        assert scenario["jurisdiction"]["code"] == "NY"
        assert scenario["store"]["selling_start_date"] == "2026-09-15"
        assert scenario["application"]["license_status"] == "APPLIED"
        assert scenario["application"]["applied_by_user_id"] == COMPLIANCE_OFFICER_ID
        assert_gob_license(scenario["license"])
        assert scenario["license"]["license_status"] == "APPROVED"
        assert scenario["license"]["decided_by_user_id"] == (
            SECOND_COMPLIANCE_OFFICER_ID
        )
        assert scenario["store"]["store_status"] == "SELLING"

    def test_the_consultant_authors_what_the_controller_decides(self):
        """The agreement and the cadence are the consultant's; the approval and the
        posting are the controller's.

        The PRD says: "Only a `RetailerController` may approve the agency agreement,
        post or reject a filed selling day, approve or void an expense item, pay a
        retention bonus, or answer a settlement proposal. Only a
        `LiquidationConsultant` may author the agreement, the store list, the markdown
        cadence, the augmentation supply, the lease negotiation, and the settlement
        worksheet."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        scenario = _role_by_role_chain_to_a_selling_store("S-7001", "NY-GOB-7001")
        store_id = scenario["store"]["id"]
        assert scenario["engagement"]["engagement_status"] == "ACTIVE"
        assert scenario["engagement"]["submitted_by_user_id"] == (
            LIQUIDATION_CONSULTANT_ID
        )
        assert_inventory_lot(scenario["lot"])
        day = validate_success(
            api_client.create_sales_day(
                store_id, sales_day_payload(**TWENTY_UNIT_DAY),
                make_store_manager_headers(store_id),
            ),
            201,
        )
        assert_sales_day(day)
        assert day["submitted_by_user_id"] == store_id
        posted = validate_success(
            api_client.review_sales_day(
                day["id"], {"decision": "POST"}, make_controller_headers()
            ),
            200,
        )
        assert posted["day_status"] == "POSTED"
        stage = validate_success(
            api_client.create_markdown_stage(
                store_id,
                markdown_stage_payload(store_version(store_id), **FIRST_STAGE),
                make_consultant_headers(),
            ),
            201,
        )
        assert_markdown_stage(stage)
        assert stage["stage_status"] == "ARMED"

    def test_the_officer_alone_takes_the_store_off_the_floor_and_back_on(self):
        """Suspend and resume are both the compliance officer's, and both answer 200.

        The PRD says: "A suspended store returns `SUSPENDED → SELLING` at a compliance
        officer's request, with `suspension_reason` reset to `NONE` and the store's
        `version` incremented."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        scenario = _role_by_role_chain_to_a_selling_store("S-7001", "NY-GOB-7001")
        store_id = scenario["store"]["id"]
        suspended = validate_success(
            api_client.suspend_store(
                store_id, make_compliance_headers(),
                payload={"suspension_reason": "COMPLIANCE_HOLD"},
            ),
            200,
        )
        assert suspended["store_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "COMPLIANCE_HOLD"
        resumed = validate_success(
            api_client.resume_store(store_id, make_compliance_headers()), 200
        )
        assert resumed["store_status"] == "SELLING"
        assert resumed["suspension_reason"] == "NONE"


def _one_selling_store(store_code, license_number):
    """A selling NY store on an ACTIVE engagement, built through the fixtures."""
    return setup_selling_store(
        clock=CLOCK_DAY_ONE,
        jurisdiction_overrides=NY_RULES,
        store_overrides={
            "store_code": store_code,
            "address_line": f"{store_code} Liquidation Row",
        },
        lot_overrides=APPAREL_LOT,
        license_overrides=dict(LICENSE_PERIOD, license_number=license_number),
    )


class TestExclusiveOperationsAreClosedToEveryOtherRole:
    def test_three_cross_role_writes_are_all_refused_as_unauthorized(self):
        """The controller cannot add a store, and the consultant can neither approve nor
        apply for a licence.

        The PRD says: "When the actor resolves but the role is not one the addressed
        endpoint admits, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_the_other_roles
        """
        scenario = _one_selling_store("S-7002", "NY-GOB-7002")
        engagement_id = scenario["engagement"]["id"]
        store_id = scenario["store"]["id"]
        validate_error(
            api_client.create_store(
                engagement_id,
                store_payload(
                    scenario["jurisdiction"]["id"],
                    store_code="S-7002B", address_line="2 Retail Row",
                ),
                make_controller_headers(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.decide_engagement_approval(
                engagement_id, {"decision": "APPROVE"}, make_consultant_headers()
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_gob_license(
                store_id,
                gob_license_payload(
                    license_number="NY-GOB-7002-X",
                    advertising_claim_codes=["FINAL_DAYS"],
                    **LICENSE_PERIOD,
                ),
                make_consultant_headers(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        _stores, store_meta = validate_paginated(
            api_client.list_stores(
                make_consultant_headers(), params={"engagement_id": engagement_id}
            )
        )
        assert store_meta["total_count"] == 1
        _licenses, license_meta = validate_paginated(
            api_client.list_gob_licenses(store_id, make_compliance_headers())
        )
        assert license_meta["total_count"] == 1

    def test_the_role_check_runs_before_the_request_shape_check(self):
        """Two empty bodies sent by the wrong role draw the role error, not the shape
        error.

        The PRD says: "When several rules could reject the same request, they are
        evaluated in one strict order and the first rule whose condition holds returns
        its error; no later rule is evaluated and no partial write occurs. … Role
        authorization against the endpoint's authorized roles — otherwise
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_the_other_roles
        """
        scenario = _one_selling_store("S-7002", "NY-GOB-7002")
        engagement_id = scenario["engagement"]["id"]
        store_id = scenario["store"]["id"]
        settlement_error = validate_error(
            api_client.create_settlement(engagement_id, {}, make_compliance_headers()),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        assert settlement_error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        stage_error = validate_error(
            api_client.create_markdown_stage(
                store_id, {}, make_store_manager_headers(store_id)
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        assert stage_error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        _rows, meta = validate_paginated(
            api_client.list_settlements(engagement_id, make_consultant_headers())
        )
        assert meta["total_count"] == 0


def _two_selling_stores_with_a_lot_and_a_stage_on_the_second():
    """Stores A and B both selling; B additionally holds a HOME lot and an ARMED stage."""
    scenario = setup_selling_engagement(
        clock=CLOCK_DAY_ONE,
        jurisdiction_overrides=NY_RULES,
        store_specs=[
            {
                "store": {
                    "store_code": "S-7003A",
                    "address_line": "S-7003A Liquidation Row",
                },
                "lots": [APPAREL_LOT],
                "license": dict(LICENSE_PERIOD, license_number="NY-GOB-7003A"),
            },
            {
                "store": {
                    "store_code": "S-7003B",
                    "address_line": "S-7003B Liquidation Row",
                },
                "lots": [HOME_LOT],
                "license": dict(LICENSE_PERIOD, license_number="NY-GOB-7003B"),
            },
        ],
    )
    scenario["stage_b"] = add_markdown_stage(
        scenario["stores"][1]["id"], **FIRST_STAGE
    )
    return scenario


class TestStoreManagerScopeFollowsItsOwnStoreId:
    def test_its_own_store_reads_but_the_other_store_and_children_do_not(self):
        """One 200 on store A, then three scope refusals on store B's rows.

        The PRD says: "Ownership checks follow from that identity directly: a
        `StoreManager` may address only the store it identifies as, or a child row whose
        `store_id` equals its own store id — and that scope covers every child type,
        namely `InventoryLot`, `MarkdownStage`, `GobLicense`, `Employee`, `SalesDay`,
        `AugmentationConsignment`, `LeaseDisposition`, and store-scoped `ExpenseItem`
        rows."

        Design: Corner/rbac/store_manager_reads_and_writes_stay_inside_its_own_store
        """
        scenario = _two_selling_stores_with_a_lot_and_a_stage_on_the_second()
        store_a, store_b = scenario["stores"]
        manager_of_a = make_store_manager_headers(store_a["id"])
        own = validate_success(api_client.get_store(store_a["id"], manager_of_a))
        assert own["store_code"] == "S-7003A"
        for response in (
            api_client.get_store(store_b["id"], manager_of_a),
            api_client.get_inventory_lot(scenario["lots"][1][0]["id"], manager_of_a),
            api_client.get_markdown_stage(scenario["stage_b"]["id"], manager_of_a),
        ):
            error = validate_error(
                response, ApiErrorId.ERR_STORE_SCOPE_VIOLATION.value, 403
            )
            assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

    def test_a_write_aimed_at_the_other_store_is_a_scope_error_and_creates_nothing(self):
        """Filing store B's selling day as store A's manager is refused and leaves no
        row.

        The PRD says: "Addressing anything outside that scope is refused with
        `ERR_STORE_SCOPE_VIOLATION` (HTTP 403), and the check applies to every endpoint
        whose authorized roles include `StoreManager`."

        Design: Corner/rbac/store_manager_reads_and_writes_stay_inside_its_own_store
        """
        scenario = _two_selling_stores_with_a_lot_and_a_stage_on_the_second()
        store_a, store_b = scenario["stores"]
        error = validate_error(
            api_client.create_sales_day(
                store_b["id"], sales_day_payload(**TWENTY_UNIT_DAY),
                make_store_manager_headers(store_a["id"]),
            ),
            ApiErrorId.ERR_STORE_SCOPE_VIOLATION.value,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
        rows, meta = validate_paginated(
            api_client.list_sales_days(
                store_b["id"], make_store_manager_headers(store_b["id"])
            )
        )
        assert rows == []
        assert meta["total_count"] == 0


def _license_pending_store_with_an_application_by_the_first_officer():
    """A LICENSE_PENDING store whose licence application was filed by co-1."""
    scenario = setup_approved_engagement(
        clock=CLOCK_DAY_ONE,
        jurisdiction_overrides=NY_RULES,
        store_overrides={
            "store_code": "S-7004", "address_line": "S-7004 Liquidation Row",
        },
        lot_overrides=APPAREL_LOT,
    )
    assert scenario["store"]["store_status"] == "LICENSE_PENDING"
    scenario["application"] = apply_for_license(
        scenario["store"]["id"],
        applied_by=make_compliance_headers(COMPLIANCE_OFFICER_ID),
        license_number="NY-GOB-7004",
        **LICENSE_PERIOD,
    )
    return scenario


class TestSegregationOfDutiesOnTheLicenceDecision:
    def test_the_officer_who_applied_cannot_decide_the_same_application(self):
        """co-1 deciding co-1's own application is refused and moves nothing.

        The PRD says: "Because both sides of this exchange are `ComplianceOfficer`
        identities, this is the one decision in the service where a self-approval is
        actually reachable, and an acting identity equal to `applied_by_user_id` is
        refused with `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/rbac/the_compliance_officer_who_applied_may_not_decide_the_same_license
        """
        scenario = _license_pending_store_with_an_application_by_the_first_officer()
        application = scenario["application"]
        assert application["applied_by_user_id"] == COMPLIANCE_OFFICER_ID
        validate_error(
            api_client.decide_gob_license(
                application["id"], {"decision": "APPROVE"},
                make_compliance_headers(COMPLIANCE_OFFICER_ID),
            ),
            ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value,
            403,
        )
        unchanged = validate_success(
            api_client.get_gob_license(application["id"], make_compliance_headers())
        )
        assert unchanged["license_status"] == "APPLIED"
        assert unchanged["decided_by_user_id"] is None
        assert read_store(scenario["store"]["id"])["store_status"] == "LICENSE_PENDING"

    def test_a_second_officer_decides_it_and_both_identities_are_recorded(self):
        """co-2's approval lands, names both sides and lifts the store onto the floor.

        The PRD says: "A second compliance officer records the regulator's `decision`,
        either `APPROVE` or `DENY`, optionally attaching a `decision_reason`, and the
        deciding identity is captured in `decided_by_user_id`. … An approval moves the
        licence `APPLIED → APPROVED` and, across the entity boundary, lifts a store
        waiting in `LICENSE_PENDING` into `SELLING` with its `selling_start_date` set to
        the licence's `period_start_date`; the store's `version` increments alongside the
        licence's."

        Design: Corner/rbac/the_compliance_officer_who_applied_may_not_decide_the_same_license
        """
        scenario = _license_pending_store_with_an_application_by_the_first_officer()
        application = scenario["application"]
        decided = validate_success(
            api_client.decide_gob_license(
                application["id"], {"decision": "APPROVE"},
                make_compliance_headers(SECOND_COMPLIANCE_OFFICER_ID),
            ),
            200,
        )
        assert decided["license_status"] == "APPROVED"
        read_back = validate_success(
            api_client.get_gob_license(application["id"], make_compliance_headers())
        )
        assert read_back["applied_by_user_id"] == COMPLIANCE_OFFICER_ID
        assert read_back["decided_by_user_id"] == SECOND_COMPLIANCE_OFFICER_ID
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "SELLING"
        assert store["selling_start_date"] == LICENSE_PERIOD["period_start_date"]


class TestIdentityLayersRunAheadOfTheRoleCheck:
    def test_an_empty_user_id_is_a_missing_header_and_the_clock_is_exempt(self):
        """An empty identity is refused, yet the clock takes no identity at all.

        The PRD says: "A request that omits `X-User-ID` or supplies it empty is rejected
        with `ERR_MISSING_USER_HEADER` (HTTP 401). … Presence of `X-User-ID` on every
        endpoint except `POST /_clock/set_current_utc` — otherwise
        `ERR_MISSING_USER_HEADER`."

        Design: Corner/rbac/header_absence_and_unknown_identities_are_rejected_before_role_resolution
        """
        scenario = _one_selling_store("S-7005", "NY-GOB-7005")
        store_id = scenario["store"]["id"]
        validate_error(
            api_client.get_store(
                store_id, build_user_headers("", "LiquidationConsultant")
            ),
            ApiErrorId.ERR_MISSING_USER_HEADER.value,
            401,
        )
        validate_success(api_client.set_clock(CLOCK_DAY_TWO), 200)
        after = validate_success(
            api_client.get_store(store_id, make_consultant_headers()), 200
        )
        assert after["store_code"] == "S-7005"

    def test_an_identity_with_no_declared_prefix_is_an_unknown_actor(self):
        """auditor-9 is not one of the four opaque prefixes, so it resolves to nobody.

        The PRD says: "An `X-User-ID` that does not resolve to a recognizable actor is
        rejected with `ERR_UNKNOWN_ACTOR` (HTTP 401). … Anything that is neither a
        well-formed prefixed opaque identity nor an entity-backed identity is an unknown
        actor."

        Design: Corner/rbac/header_absence_and_unknown_identities_are_rejected_before_role_resolution
        """
        scenario = _one_selling_store("S-7005", "NY-GOB-7005")
        validate_error(
            api_client.get_store(
                scenario["store"]["id"],
                build_user_headers("auditor-9", "LiquidationConsultant"),
            ),
            ApiErrorId.ERR_UNKNOWN_ACTOR.value,
            401,
        )

    def test_a_store_shaped_identity_matching_no_store_is_an_unknown_actor(self):
        """The manager of a store that does not exist fails resolution, not scoping.

        The PRD says: "When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of
        the acting `Store`; a `StoreManager` id that matches no existing store is an
        unknown actor and draws `ERR_UNKNOWN_ACTOR`."

        Design: Corner/rbac/header_absence_and_unknown_identities_are_rejected_before_role_resolution
        """
        scenario = _one_selling_store("S-7005", "NY-GOB-7005")
        error = validate_error(
            api_client.get_store(
                scenario["store"]["id"], make_store_manager_headers(NON_EXISTENT_UUID)
            ),
            ApiErrorId.ERR_UNKNOWN_ACTOR.value,
            401,
        )
        assert error["error_id"] != ApiErrorId.ERR_STORE_SCOPE_VIOLATION.value


class TestSharedOperationsAcceptEitherDeclaredRole:
    def test_both_roles_place_a_lot_and_enrol_an_employee_on_the_same_store(self):
        """The manager's HOME lot and both enrolments land, and the roll-up counts them.

        The PRD says: "`StoreManager` holds no exclusive operation at all: it shares
        inventory filing, employee enrolment, selling-day filing, employment actions,
        and expense submission with the `LiquidationConsultant`, restricted to its own
        store."

        Design: Corner/rbac/shared_operations_accept_either_declared_role
        """
        scenario = _one_selling_store("S-7006", "NY-GOB-7006")
        store_id = scenario["store"]["id"]
        manager = make_store_manager_headers(store_id)
        lot = validate_success(
            api_client.create_inventory_lot(
                store_id, inventory_lot_payload(**HOME_LOT), manager
            ),
            201,
        )
        assert_inventory_lot(lot)
        assert lot["cost_value_cents"] == 300000
        by_manager = validate_success(
            api_client.create_employee(
                store_id,
                employee_payload(
                    employee_code="EMP-SM", retention_bonus_cents=100000,
                    attendance_rate=0.95,
                ),
                manager,
            ),
            201,
        )
        by_consultant = validate_success(
            api_client.create_employee(
                store_id,
                employee_payload(
                    employee_code="EMP-LC", retention_bonus_cents=100000,
                    attendance_rate=0.95,
                ),
                make_consultant_headers(),
            ),
            201,
        )
        for employee in (by_manager, by_consultant):
            assert_employee(employee)
            assert employee["employment_status"] == "ACTIVE"
            assert employee["bonus_status"] == "PENDING"
        _lots, lot_meta = validate_paginated(
            api_client.list_inventory_lots(store_id, make_consultant_headers())
        )
        assert lot_meta["total_count"] == 2
        _employees, employee_meta = validate_paginated(
            api_client.list_employees(store_id, make_consultant_headers())
        )
        assert employee_meta["total_count"] == 2
        assert read_store(store_id)["original_cost_value_cents"] == 2300000

    def test_two_selling_days_differ_only_in_the_identity_that_filed_them(self):
        """The manager files under its store id and the consultant under lc-1.

        The PRD says: "The filed day is stored at `day_status` of `PENDING_REVIEW` with
        `net_sales_cents` computed as the two net-sales figures added together, the
        filing identity captured in `submitted_by_user_id`, and `posted_at`,
        `reviewed_by_user_id`, and `allocation_note` all unset."

        Design: Corner/rbac/shared_operations_accept_either_declared_role
        """
        scenario = _one_selling_store("S-7006", "NY-GOB-7006")
        store_id = scenario["store"]["id"]
        by_manager = validate_success(
            api_client.create_sales_day(
                store_id, sales_day_payload(**TWENTY_UNIT_DAY),
                make_store_manager_headers(store_id),
            ),
            201,
        )
        assert by_manager["submitted_by_user_id"] == store_id
        assert by_manager["net_sales_cents"] == 60000
        pin_clock(CLOCK_DAY_TWO)
        by_consultant = validate_success(
            api_client.create_sales_day(
                store_id, sales_day_payload(**TEN_UNIT_DAY), make_consultant_headers()
            ),
            201,
        )
        assert by_consultant["submitted_by_user_id"] == LIQUIDATION_CONSULTANT_ID
        assert by_consultant["net_sales_cents"] == 30000
        for day in (by_manager, by_consultant):
            assert_sales_day(day)
            assert day["day_status"] == "PENDING_REVIEW"
            assert day["posted_at"] is None
            assert day["reviewed_by_user_id"] is None
        _rows, meta = validate_paginated(
            api_client.list_sales_days(store_id, make_consultant_headers())
        )
        assert meta["total_count"] == 2

    def test_both_roles_submit_a_store_charged_expense_item(self):
        """Two submissions, two identities, and both open unallocated.

        The PRD says: "It opens at `expense_status` of `SUBMITTED` with `auto_generated`
        false, the submitting identity in `submitted_by_user_id`, `decided_by_user_id`
        unset, and both `liquidator_share_cents` and `retailer_share_cents` at 0 — an
        unapproved expense has no shares because it has not yet been allocated."

        Design: Corner/rbac/shared_operations_accept_either_declared_role
        """
        scenario = _one_selling_store("S-7006", "NY-GOB-7006")
        store_id = scenario["store"]["id"]
        engagement_id = scenario["engagement"]["id"]
        pin_clock(CLOCK_DAY_TWO)
        by_manager = validate_success(
            api_client.create_expense_item(
                engagement_id,
                expense_item_payload(
                    store_id=store_id, expense_category="SECURITY",
                    amount_cents=50000, incurred_date="2026-09-16",
                ),
                make_store_manager_headers(store_id),
            ),
            201,
        )
        by_consultant = validate_success(
            api_client.create_expense_item(
                engagement_id,
                expense_item_payload(
                    store_id=store_id, expense_category="ADVERTISING",
                    amount_cents=70000, incurred_date="2026-09-16",
                ),
                make_consultant_headers(),
            ),
            201,
        )
        assert by_manager["submitted_by_user_id"] == store_id
        assert by_consultant["submitted_by_user_id"] == LIQUIDATION_CONSULTANT_ID
        for item in (by_manager, by_consultant):
            assert_expense_item(item)
            assert item["expense_status"] == "SUBMITTED"
            assert item["auto_generated"] is False
            assert item["decided_by_user_id"] is None
            assert item["liquidator_share_cents"] == 0
            assert item["retailer_share_cents"] == 0
            assert item["store_id"] == store_id
        _rows, meta = validate_paginated(
            api_client.list_store_expense_items(store_id, make_consultant_headers())
        )
        assert meta["total_count"] == 2
