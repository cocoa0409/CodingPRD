"""Catalog configuration: vendors, packages, jurisdiction rules, matrices,
positions, candidates — creation defaults, shape rules, and lifecycle gates."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equals,
    assert_package,
    assert_vendor,
    create_candidate_payload,
    create_jurisdiction_rule_payload,
    create_matrix_payload,
    create_package_payload,
    create_position_payload,
    create_vendor_payload,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestVendorCreationDefaults:
    def test_vendor_creation_applies_defaults_and_system_fields(self, api):
        """PRD: "A new vendor begins `ACTIVE` with `active_order_count` and
        `consecutive_sla_breaches` at zero and both accuracy measures —
        `accuracy_bps_finalized` and `accuracy_bps_including_draft` — at 10000
        basis points, representing perfect accuracy in the absence of audit
        evidence." and "an optional per-order `surcharge_cents` defaulting to
        zero" and "a server-minted UUID with no type prefix" and "the startup
        default, before any such call, is exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/vendor_creation_applies_defaults_and_system_fields
        """
        created = validate_success(
            api.create_vendor(
                create_vendor_payload(name="V-ENT1"), HR
            ),
            expected_status=201,
        )
        assert_vendor(created)
        assert created["surcharge_cents"] == 0
        assert created["status"] == "ACTIVE"
        assert created["active_order_count"] == 0
        assert created["consecutive_sla_breaches"] == 0
        assert created["accuracy_bps_finalized"] == 10000
        assert created["accuracy_bps_including_draft"] == 10000
        assert_instant_equals(
            created["created_at"], "2026-08-01T00:00:00Z", "vendor.created_at"
        )

        fetched = validate_success(api.get_vendor(created["id"], HR))
        assert_vendor(fetched)
        assert fetched["surcharge_cents"] == 0
        assert fetched["accuracy_bps_finalized"] == 10000


class TestShapeAndUniqueness:
    def test_package_create_invalid_enum_member_rejected(self, api):
        """PRD section "Validation Ordering": "Fifth, request shape: required
        fields present, enum members valid" — rejected as `ERR_INVALID_REQUEST`
        (HTTP 400).

        Design: Corner/entities/package_create_invalid_enum_member_rejected
        """
        resp = api.create_package(
            create_package_payload(name="P-BAD", risk_tier="TIER_9"), HR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_candidate_email_uniqueness_enforced(self, api):
        """PRD section "Positions, Candidates, and Opening an Order":
        "Candidates enter the system through the `HRAdmin` as well, with a
        `full_name`, an `email` unique across all candidates (duplicates are
        rejected with `ERR_INVALID_REQUEST`)"."

        Design: Corner/entities/candidate_email_uniqueness_enforced
        """
        validate_success(
            api.create_candidate(
                create_candidate_payload(full_name="Dup A", email="dup@x.com"), HR
            ),
            expected_status=201,
        )
        resp = api.create_candidate(
            create_candidate_payload(
                full_name="Dup B", email="dup@x.com",
                home_jurisdiction_code="US-NY",
            ),
            HR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExistence:
    def test_get_missing_resource_returns_not_found(self, api):
        """PRD section "Validation Ordering": "Third, existence: every resource
        id appearing in the path or body must resolve, checked left-to-right,
        with the first unresolvable id producing `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_missing_resource_returns_not_found
        """
        resp = api.get_vendor(NON_EXISTENT_UUID, HR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_position_creation_requires_existing_package(self, api):
        """PRD section "Positions, Candidates, and Opening an Order": "Creation
        enforces three referential guards: the package must exist (missing
        references produce `ERR_NOT_FOUND`)"."

        Design: Corner/entities/position_creation_requires_existing_package
        """
        resp = api.create_position(
            create_position_payload(NON_EXISTENT_UUID), HR
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPositionReferentialGuards:
    def test_position_requires_active_package_and_rule(self, api):
        """PRD section "Positions, Candidates, and Opening an Order": "the
        package must be `ACTIVE`, else `ERR_PACKAGE_NOT_ACTIVE`; and an `ACTIVE`
        jurisdiction rule must exist for the supplied code, else
        `ERR_JURISDICTION_RULE_NOT_ACTIVE`."

        Design: Corner/validations/position_requires_active_package_and_rule
        """
        pkg = validate_success(
            api.create_package(create_package_payload(name="P-VL13"), HR),
            expected_status=201,
        )
        rule = validate_success(
            api.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(jurisdiction_code="US-CA"), CO
            ),
            expected_status=201,
        )

        # Package still DRAFT.
        resp1 = api.create_position(create_position_payload(pkg["id"]), HR)
        validate_error(resp1, ApiErrorId.ERR_PACKAGE_NOT_ACTIVE)

        # Package ACTIVE but the jurisdiction rule still DRAFT.
        validate_success(api.activate_package(pkg["id"], HR))
        resp2 = api.create_position(create_position_payload(pkg["id"]), HR)
        validate_error(resp2, ApiErrorId.ERR_JURISDICTION_RULE_NOT_ACTIVE)

        # Sanity: activating the rule unblocks creation.
        validate_success(api.activate_jurisdiction_rule(rule["id"], CO))
        ok = validate_success(
            api.create_position(create_position_payload(pkg["id"]), HR),
            expected_status=201,
        )
        assert ok["package_id"] == pkg["id"]

    def test_credit_check_prohibited_jurisdiction(self, api):
        """PRD section "Positions, Candidates, and Opening an Order": "A fourth,
        safety-shaped guard fires when the jurisdiction rule has
        `credit_check_allowed` set false: any referenced package whose
        `check_types` contains `CREDIT_CHECK` is rejected with
        `ERR_CREDIT_CHECK_PROHIBITED` (HTTP 422)."

        Design: Corner/validations/credit_check_prohibited_jurisdiction
        """
        credit_pkg = validate_success(
            api.create_package(
                create_package_payload(
                    name="P-VL3-CR",
                    risk_tier="TIER_3_HIGH_RISK",
                    check_types=["CRIMINAL_COUNTY", "CREDIT_CHECK"],
                ),
                HR,
            ),
            expected_status=201,
        )
        validate_success(api.activate_package(credit_pkg["id"], HR))
        clean_pkg = validate_success(
            api.create_package(
                create_package_payload(
                    name="P-VL3-OK",
                    risk_tier="TIER_3_HIGH_RISK",
                    check_types=["CRIMINAL_COUNTY"],
                ),
                HR,
            ),
            expected_status=201,
        )
        validate_success(api.activate_package(clean_pkg["id"], HR))
        rule = validate_success(
            api.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(
                    jurisdiction_code="US-NY-NYC", credit_check_allowed=False
                ),
                CO,
            ),
            expected_status=201,
        )
        validate_success(api.activate_jurisdiction_rule(rule["id"], CO))

        resp = api.create_position(
            create_position_payload(
                credit_pkg["id"],
                jurisdiction_code="US-NY-NYC",
                risk_tier="TIER_3_HIGH_RISK",
            ),
            HR,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_CHECK_PROHIBITED)

        ok = validate_success(
            api.create_position(
                create_position_payload(
                    clean_pkg["id"],
                    jurisdiction_code="US-NY-NYC",
                    risk_tier="TIER_3_HIGH_RISK",
                ),
                HR,
            ),
            expected_status=201,
        )
        assert ok["package_id"] == clean_pkg["id"]


class TestActivationGates:
    def test_package_double_activate_and_retire_in_use(self, api):
        """PRD section "Configuring the Screening Catalog": "activation moves
        one to `ACTIVE` (attempting to activate a non-draft package is rejected
        with `ERR_PACKAGE_NOT_DRAFT`)" and "Retirement moves an `ACTIVE` package
        to `RETIRED`, but only when no non-terminal order references it —
        neither directly through a position still pointing at the package nor
        through a pinned snapshot; any such reference blocks retirement with
        `ERR_PACKAGE_IN_USE`"."

        Design: Corner/state_machines/package_double_activate_and_retire_in_use
        """
        pkg = validate_success(
            api.create_package(create_package_payload(name="P-SM8"), HR),
            expected_status=201,
        )
        validate_success(api.activate_package(pkg["id"], HR))
        rule = validate_success(
            api.create_jurisdiction_rule(create_jurisdiction_rule_payload(), CO),
            expected_status=201,
        )
        validate_success(api.activate_jurisdiction_rule(rule["id"], CO))
        position = validate_success(
            api.create_position(create_position_payload(pkg["id"]), HR),
            expected_status=201,
        )
        candidate = validate_success(
            api.create_candidate(
                create_candidate_payload(full_name="Sm Eight", email="sm8@x.com"),
                HR,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_order(
                {"candidate_id": candidate["id"], "position_id": position["id"]}, HM
            ),
            expected_status=201,
        )

        # Second activate on the ACTIVE package.
        resp1 = api.activate_package(pkg["id"], HR)
        validate_error(resp1, ApiErrorId.ERR_PACKAGE_NOT_DRAFT)

        # Retire blocked: a non-terminal (DRAFT) order references the package
        # through its position.
        resp2 = api.retire_package(pkg["id"], HR)
        validate_error(resp2, ApiErrorId.ERR_PACKAGE_IN_USE)

        pkg_now = validate_success(api.get_package(pkg["id"], HR))
        assert_package(pkg_now)
        assert pkg_now["status"] == "ACTIVE"

    def test_matrix_and_jurisdiction_activation_uniqueness(self, api):
        """PRD section "Configuring the Screening Catalog": "enforces one
        `ACTIVE` rule per `jurisdiction_code`: if another rule with the same
        code is already active, activation is rejected with
        `ERR_JURISDICTION_RULE_ALREADY_ACTIVE`" and "rejects when another matrix
        is already `ACTIVE` for the same tier (`ERR_MATRIX_ALREADY_ACTIVE`)."

        Design: Corner/state_machines/matrix_and_jurisdiction_activation_uniqueness
        """
        m1 = validate_success(
            api.create_matrix(create_matrix_payload(), CO), expected_status=201
        )
        validate_success(api.activate_matrix(m1["id"], CO))
        m2 = validate_success(
            api.create_matrix(
                create_matrix_payload(
                    rules=[
                        {
                            "offense_category": "MISDEMEANOR",
                            "min_severity": "LOW",
                            "max_recency_years": 3,
                            "action": "IA_REQUIRED",
                        }
                    ]
                ),
                CO,
            ),
            expected_status=201,
        )
        j1 = validate_success(
            api.create_jurisdiction_rule(create_jurisdiction_rule_payload(), CO),
            expected_status=201,
        )
        validate_success(api.activate_jurisdiction_rule(j1["id"], CO))
        j2 = validate_success(
            api.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(
                    screening_gate_stage="POST_CONDITIONAL_OFFER",
                    lookback_years_limit=5,
                    arrest_records_considerable=False,
                    pre_adverse_wait_business_days=7,
                    individualized_assessment_required=True,
                    credit_check_allowed=False,
                ),
                CO,
            ),
            expected_status=201,
        )

        resp1 = api.activate_matrix(m2["id"], CO)
        validate_error(resp1, ApiErrorId.ERR_MATRIX_ALREADY_ACTIVE)
        resp2 = api.activate_jurisdiction_rule(j2["id"], CO)
        validate_error(resp2, ApiErrorId.ERR_JURISDICTION_RULE_ALREADY_ACTIVE)

        assert validate_success(api.get_matrix(m2["id"], CO))["status"] == "DRAFT"
        assert (
            validate_success(api.get_jurisdiction_rule(j2["id"], CO))["status"]
            == "DRAFT"
        )

    def test_vendor_reinstate_requires_suspended_or_probation(self, api):
        """PRD section "Vendor Lifecycle": "Reinstatement returns a `SUSPENDED`
        or `PROBATION` vendor to `ACTIVE`; any other status rejects with
        `ERR_VENDOR_NOT_SUSPENDED_OR_PROBATION`."

        Design: Corner/state_machines/vendor_reinstate_requires_suspended_or_probation
        """
        vendor = validate_success(
            api.create_vendor(create_vendor_payload(name="V-SM13"), HR),
            expected_status=201,
        )
        resp = api.reinstate_vendor(vendor["id"], CO)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_SUSPENDED_OR_PROBATION)
        assert (
            validate_success(api.get_vendor(vendor["id"], HR))["status"] == "ACTIVE"
        )
