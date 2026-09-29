"""The error catalogue: authentication, per-endpoint authorization, the entity-specific
not-found codes on both path parameters and body foreign keys, and the refusal of a
repeated terminal action."""
import pytest

from test_helpers import (
    ApiErrorId,
    OPERATORS,
    TEST_USERS,
    add_finding,
    api_client,
    approve_claim,
    assert_date_equals,
    build_user_headers,
    create_dealer,
    create_labor_operation,
    create_rate_request,
    create_state_law_profile,
    create_vehicle,
    decide_appeal,
    decide_rate_request,
    file_appeal,
    get_appeal,
    get_audit,
    get_claim,
    get_dealer,
    get_finding,
    issue_findings,
    list_ledger_entries,
    make_dealer_warranty_admin_headers,
    pay_claim,
    schedule_audit,
    set_clock,
    setup_reference_data,
    start_audit,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
MANAGER = TEST_USERS["adjudication_manager_headers"]
FIELD_AUDITOR = TEST_USERS["field_auditor_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]

# A well-formed UUID that is deliberately never assigned to any row.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

D1_TERMS = {
    "dealer_code": "D1",
    "name": "Dealer One",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 13750,
    "initial_parts_markup_pct": 0.40,
}

DA_TERMS = {
    "dealer_code": "DA",
    "name": "Audit Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

BRAKE_OPERATION = {
    "op_code": "A1234-56",
    "description": "Front brake pad replacement",
    "standard_time_hours": 1.5,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "BRAKE_FRONT",
    "overlap_group": "BRAKE_FRONT",
}

AUDIT_OPERATION = {
    "op_code": "AUD-100",
    "description": "Instrument cluster diagnosis and repair",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "AUDIT_OPS",
}

BRAKE_PART = {
    "part_number": "BRK-PAD-9931",
    "description": "Front brake pad set",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 30,
}

COVERED_VEHICLE = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

AUDIT_VEHICLE = {
    "model_year": 2025,
    "warranty_start_date": "2025-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

BRAKE_NARRATIVE = {
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

AUDIT_NARRATIVE = {
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}


def build_brake_reference_world():
    """The CA statute, dealer D1, one covered vehicle, the front-brake operation and its
    causal part — enough for every read to be well formed apart from the fault probed."""
    set_clock("2026-05-01T00:00:00Z")
    return setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides=D1_TERMS,
        vehicle_overrides=COVERED_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
    )


def build_brake_claim_world():
    """The brake reference world plus one submitted claim on it."""
    world = build_brake_reference_world()
    world["claim"] = submit_claim(
        world,
        repair_order_number="RO-1001",
        repair_date="2026-04-10",
        odometer_at_repair=20000,
        claimed_labor_hours=1.5,
        claimed_parts_qty=3,
        **BRAKE_NARRATIVE,
    )
    assert world["claim"]["status"] == "SUBMITTED"
    assert world["claim"]["payment_status"] == "UNPAID"
    return world


def build_appealed_audit_world():
    """Dealer DA with one paid 20000-cent claim, an issued audit carrying one 10000-cent
    charged-back finding, and a filed appeal contesting it."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(profile["id"], **DA_TERMS)
    vehicle = create_vehicle(**AUDIT_VEHICLE)
    operation = create_labor_operation(**AUDIT_OPERATION)
    headers = make_dealer_warranty_admin_headers(dealer["id"])

    claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": vehicle,
            "operation": operation,
            "part": None,
            "dealer_headers": headers,
        },
        repair_order_number="RO-AUD-1",
        repair_date="2026-02-15",
        odometer_at_repair=20000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        **AUDIT_NARRATIVE,
    )
    approve_claim(claim["id"], approved_labor_hours=2.0, approved_parts_qty=0)
    claim = pay_claim(claim["id"])
    assert claim["approved_total_cents"] == 20000

    audit = schedule_audit(
        get_dealer(dealer["id"]),
        period_start="2026-01-01",
        period_end="2026-04-01",
        sample_size=1,
    )
    start_audit(audit["id"])
    finding = add_finding(
        audit["id"],
        claim["id"],
        10000,
        finding_code="TIME_NOT_DOCUMENTED",
        evidence_note="Technician time is not documented on the repair order.",
    )
    audit = issue_findings(audit["id"])
    appeal = file_appeal(
        audit,
        [finding["id"]],
        grounds="The repair order carries the technician time on its reverse side.",
    )
    assert appeal["status"] == "FILED"
    assert get_finding(finding["id"])["status"] == "CHARGED_BACK"

    return {
        "dealer": dealer,
        "claim": claim,
        "audit": audit,
        "finding": finding,
        "appeal": appeal,
    }


class TestUnauthenticatedRequests:
    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"X-User-Role": "WarrantyAdmin"},
            {"X-User-ID": "wa-user-1"},
            build_user_headers("wa-user-1", "DealerSalesManager"),
        ],
        ids=["no_headers", "role_without_user_id", "user_id_without_role", "unknown_role"],
    )
    def test_01_dealer_read_without_valid_credentials_is_unauthenticated(self, headers):
        """PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting in."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "The seven roles are `WarrantyAdmin`, `ClaimAdjudicator`, `AdjudicationManager`, `FieldAuditor`, `AuditManager`, `AppealReviewer`, and `DealerWarrantyAdmin`."
        PRD §5: "Every rejection this service issues carries one of the identifiers below in the `error_id` field of the error envelope described in §2.2, paired with the HTTP status code shown."

        Design: Corner/errors/dealer_read_missing_auth_header_returns_401
        """
        world = build_brake_reference_world()

        response = api_client.get_dealer(world["dealer"]["id"], headers)

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
        # The same read succeeds once both headers are well formed and the role is known.
        readable = validate_success(api_client.get_dealer(world["dealer"]["id"], ADMIN))
        assert readable["id"] == world["dealer"]["id"]

    @pytest.mark.parametrize(
        "path,shadowed_error",
        [
            ("/warranty/dealers", ApiErrorId.ERR_DEALER_NOT_FOUND),
            ("/warranty/audits", ApiErrorId.ERR_AUDIT_NOT_FOUND),
        ],
        ids=["dealer", "audit"],
    )
    def test_02_missing_credentials_outrank_the_existence_check(self, path, shadowed_error):
        """PRD §2.11: "Checks are evaluated in the following order, and the first one that fails determines the response; no later check is consulted."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.7: "The twelve not-found codes are `ERR_STATE_LAW_PROFILE_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_LABOR_OPERATION_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LABOR_RATE_REQUEST_NOT_FOUND`, `ERR_PARTS_RETURN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND` and `ERR_GOODWILL_AUTH_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/existence_check_never_precedes_the_unauthenticated_check
        """
        build_brake_reference_world()

        unauthenticated = api_client.get(f"{path}/{UNKNOWN_ID}", {})

        error = validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED)
        assert error["error_id"] != shadowed_error
        # With credentials the very same path does report the missing row.
        validate_error(api_client.get(f"{path}/{UNKNOWN_ID}", ADMIN), shadowed_error)


class TestPerEndpointRoleAuthorization:
    def test_03_a_valid_role_outside_an_endpoints_list_is_refused(self):
        """PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the target endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `WarrantyAdmin` is the manufacturer's warranty program administrator: it publishes all reference data, drives the parts-return program, runs the deemed-approval and non-return sweeps, and pays approved claims."
        PRD §2.1: "A `ClaimAdjudicator` adjudicates submitted claims against coverage, flat-rate time and the statutory markup cap, and raises goodwill requests for out-of-warranty repairs."
        PRD §4: "All authorization is evaluated as described in §2.1, and the dealer-scoped rows of the table below are additionally subject to the `DealerWarrantyAdmin` scope check."

        Design: Corner/errors/dealer_create_by_field_auditor_rejected
        """
        world = build_brake_claim_world()
        claim = world["claim"]

        # A FieldAuditor may read every dealer but may not enroll one.
        validate_error(
            api_client.create_dealer(
                {
                    "dealer_code": "D9",
                    "name": "Rogue Motors",
                    "state_law_profile_id": world["profile"]["id"],
                    "vehicles_in_operation": 10,
                    "initial_labor_rate_cents": 10000,
                    "initial_parts_markup_pct": 0.25,
                },
                FIELD_AUDITOR,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # The administrator who published the reference data cannot adjudicate.
        validate_error(
            api_client.adjudicate_claim(
                claim["id"],
                {"decision": "APPROVE", "approved_labor_hours": 1.5, "approved_parts_qty": 3},
                ADMIN,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # Payment belongs to the WarrantyAdmin alone, even for the owning dealership.
        validate_error(
            api_client.pay_claim(claim["id"], world["dealer_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # The parts-return sweep is likewise not the audit organisation's to run.
        validate_error(
            api_client.run_non_return_sweep(AUDIT_MANAGER),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # No refusal left a trace on any target.
        untouched = get_claim(claim["id"])
        assert untouched["status"] == "SUBMITTED"
        assert untouched["payment_status"] == "UNPAID"
        assert untouched["version"] == claim["version"]
        rows, meta = validate_paginated(api_client.list_dealers(ADMIN))
        assert meta["total_count"] == 1
        assert [row["dealer_code"] for row in rows] == ["D1"]


class TestPathParameterNotFound:
    @pytest.mark.parametrize(
        "collection_path,expected_error",
        [
            ("/warranty/state-law-profiles", ApiErrorId.ERR_STATE_LAW_PROFILE_NOT_FOUND),
            ("/warranty/dealers", ApiErrorId.ERR_DEALER_NOT_FOUND),
            ("/warranty/vehicles", ApiErrorId.ERR_VEHICLE_NOT_FOUND),
            ("/warranty/labor-operations", ApiErrorId.ERR_LABOR_OPERATION_NOT_FOUND),
            ("/warranty/parts", ApiErrorId.ERR_CATALOG_ITEM_NOT_FOUND),
            ("/warranty/claims", ApiErrorId.ERR_CLAIM_NOT_FOUND),
            ("/warranty/labor-rate-requests", ApiErrorId.ERR_LABOR_RATE_REQUEST_NOT_FOUND),
            ("/warranty/parts-returns", ApiErrorId.ERR_PARTS_RETURN_NOT_FOUND),
            ("/warranty/audits", ApiErrorId.ERR_AUDIT_NOT_FOUND),
            ("/warranty/audit-findings", ApiErrorId.ERR_FINDING_NOT_FOUND),
            ("/warranty/appeals", ApiErrorId.ERR_APPEAL_NOT_FOUND),
            ("/warranty/goodwill-authorizations", ApiErrorId.ERR_GOODWILL_AUTH_NOT_FOUND),
        ],
    )
    def test_04_an_unassigned_path_id_reports_that_entitys_own_not_found_code(
        self, collection_path, expected_error
    ):
        """PRD §2.7: "The outer identifier is looked up first, and if it names no live record the request fails immediately with that entity's not-found code — the inner identifier is not consulted at all."
        PRD §2.7: "The twelve not-found codes are `ERR_STATE_LAW_PROFILE_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_LABOR_OPERATION_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LABOR_RATE_REQUEST_NOT_FOUND`, `ERR_PARTS_RETURN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND` and `ERR_GOODWILL_AUTH_NOT_FOUND`, all HTTP 404."
        PRD §5: "Every rejection this service issues carries one of the identifiers below in the `error_id` field of the error envelope described in §2.2, paired with the HTTP status code shown."

        Design: Corner/errors/path_parameter_unknown_ids_across_endpoints_not_found
        """
        build_brake_reference_world()

        response = api_client.get(f"{collection_path}/{UNKNOWN_ID}", ADMIN)

        validate_error(response, expected_error)


class TestBodyForeignKeyNotFound:
    def test_05_each_unresolvable_body_reference_reports_its_own_entitys_code(self):
        """PRD §2.7: "The same left-to-right discipline governs foreign keys supplied in a request body."
        PRD §2.7: "Each such reference is validated in the fixed order the endpoint's input list declares it, and the first unresolvable reference decides the error."
        PRD §2.7: "On claim submission that order is `dealer_id`, then `vehicle_id`, then `labor_operation_id`, then `causal_part_id`, so a request naming both a nonexistent dealer and a nonexistent vehicle reports `ERR_DEALER_NOT_FOUND` and never mentions the vehicle."
        PRD §2.7: "A `state_law_profile_id` that names no profile yields `ERR_STATE_LAW_PROFILE_NOT_FOUND`; a `resubmission_of_claim_id` or a finding's `claim_id` that names no claim yields `ERR_CLAIM_NOT_FOUND`; a `causal_part_id` or `part_id` that names no catalog part yields `ERR_CATALOG_ITEM_NOT_FOUND`; and a finding identifier appearing in `contested_finding_ids` or `overturned_finding_ids` that names no finding yields `ERR_FINDING_NOT_FOUND`."

        Design: Corner/errors/body_foreign_key_unknown_ids_not_found
        """
        world = build_brake_reference_world()

        def claim_body(**overrides):
            body = {
                "dealer_id": world["dealer"]["id"],
                "vehicle_id": world["vehicle"]["id"],
                "labor_operation_id": world["operation"]["id"],
                "causal_part_id": world["part"]["id"],
                "repair_order_number": "RO-9001",
                "repair_date": "2026-04-10",
                "odometer_at_repair": 20000,
                "claimed_labor_hours": 1.5,
                "claimed_parts_qty": 3,
                **BRAKE_NARRATIVE,
            }
            body.update(overrides)
            return body

        validate_error(
            api_client.create_dealer(
                {
                    "dealer_code": "D8",
                    "name": "Orphan Motors",
                    "state_law_profile_id": UNKNOWN_ID,
                    "vehicles_in_operation": 10,
                    "initial_labor_rate_cents": 10000,
                    "initial_parts_markup_pct": 0.25,
                },
                ADMIN,
            ),
            ApiErrorId.ERR_STATE_LAW_PROFILE_NOT_FOUND,
        )

        validate_error(
            api_client.create_claim(
                claim_body(labor_operation_id=UNKNOWN_ID), world["dealer_headers"]
            ),
            ApiErrorId.ERR_LABOR_OPERATION_NOT_FOUND,
        )

        validate_error(
            api_client.create_claim(
                claim_body(causal_part_id=UNKNOWN_ID), world["dealer_headers"]
            ),
            ApiErrorId.ERR_CATALOG_ITEM_NOT_FOUND,
        )

        # Vehicle precedes labor operation, so the vehicle is what the error names.
        validate_error(
            api_client.create_claim(
                claim_body(vehicle_id=UNKNOWN_ID, labor_operation_id=UNKNOWN_ID),
                world["dealer_headers"],
            ),
            ApiErrorId.ERR_VEHICLE_NOT_FOUND,
        )

        # Nothing was created by any of the four refusals.
        _, dealer_meta = validate_paginated(api_client.list_dealers(ADMIN))
        assert dealer_meta["total_count"] == 1
        _, claim_meta = validate_paginated(api_client.list_claims(ADMIN))
        assert claim_meta["total_count"] == 0

    def test_06_unknown_dealer_in_the_audit_body_outranks_the_version_check(self):
        """PRD §2.7: "Each such reference is validated in the fixed order the endpoint's input list declares it, and the first unresolvable reference decides the error."
        PRD §2.11: "Checks are evaluated in the following order, and the first one that fails determines the response; no later check is consulted."
        PRD §2.9: "Scheduling a dealer audit likewise requires `expected_dealer_version` matching the audited `Dealer`'s current `version`, and a mismatch is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412)."

        Design: Corner/errors/body_foreign_key_unknown_ids_not_found
        """
        world = build_brake_reference_world()

        def audit_body(**overrides):
            body = {
                "dealer_id": world["dealer"]["id"],
                "period_start": "2026-01-01",
                "period_end": "2026-04-01",
                "sample_size": 1,
                "lead_auditor_user_id": "auditor-lead-1",
                "expected_dealer_version": world["dealer"]["version"],
            }
            body.update(overrides)
            return body

        # A version that could never match does not displace the missing dealer.
        validate_error(
            api_client.create_audit(
                audit_body(dealer_id=UNKNOWN_ID, expected_dealer_version=99), AUDIT_MANAGER
            ),
            ApiErrorId.ERR_DEALER_NOT_FOUND,
        )

        # With a dealer that does resolve, the version check is what speaks.
        validate_error(
            api_client.create_audit(
                audit_body(expected_dealer_version=99), AUDIT_MANAGER
            ),
            ApiErrorId.ERR_STALE_DEALER_VERSION,
        )

        # And the well-formed request is accepted, so neither refusal was incidental.
        scheduled = validate_success(
            api_client.create_audit(audit_body(), AUDIT_MANAGER), expected_status=201
        )
        assert scheduled["dealer_id"] == world["dealer"]["id"]
        assert scheduled["status"] == "SCHEDULED"


class TestRepeatedTerminalActions:
    def test_07_second_appeal_decision_is_refused_by_the_appeals_own_state(self):
        """PRD §3.8: "The appeal must be in `FILED`, or the request is `ERR_APPEAL_INVALID_STATE`."
        PRD §3.8: "`DENY` moves the appeal `FILED → DENIED`, moves every contested finding `CHARGED_BACK → UPHELD`, and leaves the appeal's `reinstated_amount_cents` at 0."
        PRD §3.8: "In all three cases `reviewer_user_id` is stamped from `X-User-ID`, every touched finding advances its own `version` by 1, and the appeal's `version` advances by 1."
        PRD §3.8: "Each row is omitted entirely when its own delta is zero, which is why a denied appeal typically appends nothing at all."
        PRD §3.8: "Every decision then re-runs the third through sixth computational steps described above, against the audit's *persisted* snapshots rather than against live data: `sample_chargeback_cents` is re-totalled over the findings that are still `OPEN`, `CHARGED_BACK` or `UPHELD`, `error_rate` is recomputed against the unchanged `sample_paid_snapshot_cents`, the tier is re-selected, `extrapolated_chargeback_cents` is recomputed against the unchanged `population_paid_snapshot_cents`, and `total_chargeback_cents` is rewritten."
        PRD §3.8: "A partially granted or a denied appeal instead drives the audit `APPEALED → FINDINGS_ISSUED`, stamping a fresh `findings_issued_at` at the current clock instant and a fresh `appeal_deadline` derived from it, so the dealer may appeal the re-issued findings again inside the new window."
        PRD §2.6: "An audit's `appeal_deadline` is its `findings_issued_at` advanced by the governing state's `appeal_window_days` days, and it is recomputed from scratch every time findings are re-issued."

        Design: Corner/errors/repeated_terminal_action_calls_rejected
        """
        world = build_appealed_audit_world()
        assert_date_equals(
            get_audit(world["audit"]["id"])["appeal_deadline"],
            "2026-05-31",
            "appeal_deadline",
        )

        set_clock("2026-05-10T00:00:00Z")
        decided = decide_appeal(
            world["appeal"]["id"],
            action="DENY",
            decision_note="The reverse of the repair order was reviewed on appeal.",
        )

        assert decided["status"] == "DENIED"
        assert decided["reviewer_user_id"] == OPERATORS["APPEAL_REVIEWER"]
        assert decided["reinstated_amount_cents"] == 0
        assert get_finding(world["finding"]["id"])["status"] == "UPHELD"

        reissued = get_audit(world["audit"]["id"])
        assert reissued["status"] == "FINDINGS_ISSUED"
        assert_date_equals(reissued["appeal_deadline"], "2026-06-09", "appeal_deadline")
        assert reissued["total_chargeback_cents"] == 10000

        entries_before = list_ledger_entries(world["dealer"]["id"])
        assert len(entries_before) == 1

        response = api_client.decide_appeal(
            world["appeal"]["id"],
            {
                "action": "DENY",
                "decision_note": "The reverse of the repair order was reviewed on appeal.",
            },
            APPEAL_REVIEWER,
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_INVALID_STATE)

        # Nothing moved a second time.
        unchanged = get_appeal(world["appeal"]["id"])
        assert unchanged["status"] == "DENIED"
        assert unchanged["version"] == decided["version"]
        assert unchanged["reinstated_amount_cents"] == 0
        assert get_finding(world["finding"]["id"])["status"] == "UPHELD"
        assert list_ledger_entries(world["dealer"]["id"]) == entries_before
        assert get_dealer(world["dealer"]["id"])["chargeback_balance_cents"] == 10000
        assert get_audit(world["audit"]["id"])["version"] == reissued["version"]

    def test_08_second_rate_petition_decision_is_refused_by_the_petitions_own_state(self):
        """PRD §3.2: "Both actions accept a request in either `SUBMITTED` or `UNDER_REVIEW`; anything else yields `ERR_LABOR_RATE_REQUEST_INVALID_STATE`."
        PRD §3.2: "Approval moves the request to `APPROVED`, writes both granted figures onto the request, then republishes them onto the dealer: the dealer's `approved_labor_rate_cents` and `approved_parts_markup_pct` are overwritten with the granted values and its `labor_rate_effective_date` is set to the request's `effective_date`, with the dealer's `updated_at` refreshed and its `version` advanced by 1."

        Design: Corner/errors/repeated_terminal_action_calls_rejected
        """
        world = build_brake_reference_world()
        filed = create_rate_request(
            world["dealer"],
            requested_labor_rate_cents=17600,
            requested_parts_markup_pct=0.30,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-09-01",
        )

        approved = decide_rate_request(
            filed["id"],
            action="APPROVE",
            approved_labor_rate_cents=17600,
            approved_parts_markup_pct=0.30,
        )
        assert approved["status"] == "APPROVED"
        dealer_after_approval = get_dealer(world["dealer"]["id"])
        assert dealer_after_approval["approved_labor_rate_cents"] == 17600

        repeat_approval = api_client.decide_labor_rate_request(
            filed["id"],
            {
                "action": "APPROVE",
                "approved_labor_rate_cents": 17600,
                "approved_parts_markup_pct": 0.30,
            },
            MANAGER,
        )
        validate_error(repeat_approval, ApiErrorId.ERR_LABOR_RATE_REQUEST_INVALID_STATE)

        late_denial = api_client.decide_labor_rate_request(
            filed["id"],
            {"action": "DENY", "denial_reason": "Sample repair orders were not customer-pay."},
            MANAGER,
        )
        validate_error(late_denial, ApiErrorId.ERR_LABOR_RATE_REQUEST_INVALID_STATE)

        # The single approval was published exactly once.
        settled = validate_success(api_client.get_labor_rate_request(filed["id"], ADMIN))
        assert settled["status"] == "APPROVED"
        assert settled["version"] == approved["version"]
        assert get_dealer(world["dealer"]["id"])["version"] == dealer_after_approval["version"]
        assert (
            get_dealer(world["dealer"]["id"])["approved_labor_rate_cents"]
            == dealer_after_approval["approved_labor_rate_cents"]
        )
