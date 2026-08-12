"""Reference data lifecycle, entity reads, admin RBAC, and the logical clock."""
from test_helpers import ( TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_policyholder, assert_state_regulation, assert_policy,
    assert_glass_shop,
    create_policyholder_payload, create_state_regulation_payload,
    create_policy_payload, create_glass_shop_payload,
    make_regulation, make_policyholder, make_policy, make_shop, make_part,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# ---------------------------------------------------------------------------
# Policyholder
# ---------------------------------------------------------------------------

class TestPolicyholderCreation:
    def test_policyholder_creation_success(self, api):
        """PRD §3.1: "A freshly registered policyholder begins with `status` set to
        `ACTIVE`, a `fraud_score` of zero, and a `no_show_count` of zero."

        Design: Corner/entities/policyholder_creation_success
        """
        resp = api.create_policyholder(create_policyholder_payload(
            full_name="Create Ok", email="cok@x.com", phone="555-1001", state_code="FL",
        ), ADMIN)
        data = validate_success(resp, 201)
        assert_policyholder(data)
        assert data["status"] == "ACTIVE"
        assert data["fraud_score"] == 0
        assert data["no_show_count"] == 0
        assert data["version"] == 1
        # Logical clock startup default (PRD §2.4): 2026-05-01T00:00:00Z.
        assert data["created_at"].startswith("2026-05-01T00:00:00")

    def test_policyholder_missing_required_field(self, api):
        """PRD §2.8: "a missing required field, a wrong type, or an invalid enum
        value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/policyholder_missing_required_field
        """
        payload = {"full_name": "No Email", "phone": "555-1002", "state_code": "FL"}
        resp = api.create_policyholder(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_policyholder_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate
        `ERR_POLICYHOLDER_NOT_FOUND` ..."

        Design: Corner/entities/policyholder_get_not_found
        """
        resp = api.get_policyholder(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_POLICYHOLDER_NOT_FOUND)


# ---------------------------------------------------------------------------
# StateRegulation
# ---------------------------------------------------------------------------

class TestStateRegulation:
    def test_state_regulation_unique_state_code(self, api):
        """PRD §3.1: "Only one regulation row may exist per state; a second
        creation for the same `state_code` is rejected with
        `ERR_DUPLICATE_STATE_REGULATION` (HTTP 409)."

        Design: Corner/entities/state_regulation_unique_state_code
        """
        make_regulation("FL", zero_deductible_windshield=True, tax_bp=0)
        resp = api.create_state_regulation(
            create_state_regulation_payload(
                state_code="FL", zero_deductible_windshield=False,
                glass_sales_tax_rate_bp=600),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_REGULATION)
        data, meta = validate_paginated(
            api.list_state_regulations(ADMIN, params={"state_code": "FL"}))
        assert meta["total_count"] == 1
        assert len(data) == 1

    def test_state_regulation_max_deductible_default_null(self, api):
        """PRD §3.1: "an optional `max_deductible_cents` cap (null meaning the
        state imposes no cap)".

        Design: Corner/entities/state_regulation_max_deductible_default_null
        """
        resp = api.create_state_regulation(
            create_state_regulation_payload(
                state_code="GA", zero_deductible_windshield=False,
                glass_sales_tax_rate_bp=400),
            ADMIN)
        data = validate_success(resp, 201)
        assert_state_regulation(data)
        assert data["max_deductible_cents"] is None


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class TestPolicy:
    def test_policy_oem_endorsement_default_false(self, api):
        """PRD §3.1: "The `oem_endorsement` flag records whether the policyholder
        paid for the OEM-parts endorsement that waives the OEM upcharge; it
        defaults to false when omitted. A policy's `status` is `ACTIVE` on
        creation..."

        Design: Corner/entities/policy_oem_endorsement_default_false
        """
        ph = make_policyholder(full_name="Def Oem", email="defo@x.com")
        payload = create_policy_payload(ph["id"], deductible_cents=25000)
        payload.pop("oem_endorsement", None)
        resp = api.create_policy(payload, ADMIN)
        data = validate_success(resp, 201)
        assert_policy(data)
        assert data["oem_endorsement"] is False
        assert data["status"] == "ACTIVE"

    def test_policy_invalid_coverage_type_enum(self, api):
        """PRD §2.8: "a missing required field, a wrong type, or an invalid enum
        value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "a `coverage_type` of either `COMPREHENSIVE` or `LIABILITY`".

        Design: Corner/entities/policy_invalid_coverage_type_enum
        """
        ph = make_policyholder(full_name="Enum Bad", email="enum@x.com")
        payload = create_policy_payload(ph["id"], coverage_type="FULL_GLASS",
                                        deductible_cents=25000)
        resp = api.create_policy(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_policy_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate
        `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, ..."

        Design: Corner/entities/policy_get_not_found
        """
        resp = api.get_policy(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND)


# ---------------------------------------------------------------------------
# GlassShop
# ---------------------------------------------------------------------------

class TestGlassShop:
    def test_glass_shop_creation_initializes_computed_fields(self, api):
        """PRD §3.1: "A new shop's `network_status` is `ACTIVE`, its
        `warranty_strike_count` starts at zero, and both of its audit scores
        start at 100."

        Design: Corner/entities/glass_shop_creation_initializes_computed_fields
        """
        resp = api.create_glass_shop(create_glass_shop_payload(
            shop_name="Init Shop", mobile_capable=True, adas_certified=True,
            oem_certified=True, agreement_tier="PREFERRED",
            bay_count=3, mobile_unit_count=2), ADMIN)
        data = validate_success(resp, 201)
        assert_glass_shop(data)
        assert data["network_status"] == "ACTIVE"
        assert data["warranty_strike_count"] == 0
        assert data["rolling_audit_score"] == 100
        assert data["period_close_audit_score"] == 100

    def test_glass_shop_operating_minutes_default(self, api):
        """PRD §3.1: "operating_minutes_per_day (defaulting to 480 operating
        minutes per bay per calendar date when omitted)".

        Design: Corner/entities/glass_shop_operating_minutes_default
        """
        resp = api.create_glass_shop(create_glass_shop_payload(shop_name="Def Min"), ADMIN)
        data = validate_success(resp, 201)
        assert data["operating_minutes_per_day"] == 480

    def test_shop_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate ...
        `ERR_SHOP_NOT_FOUND` ..."

        Design: Corner/entities/shop_get_not_found
        """
        resp = api.get_glass_shop(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHOP_NOT_FOUND)

    def test_shop_patch_admin_update(self, api):
        """PRD §3.1: "The administrator may later adjust a shop's
        `network_status`, `agreement_tier`, `adas_certified`, or `mobile_capable`
        through an admin update, which increments the shop's `version`."

        Design: Corner/endpoints/shop_patch_admin_update
        """
        shop = make_shop(shop_name="Patch Me")
        resp = api.update_glass_shop(shop["id"], {
            "network_status": "SUSPENDED",
            "agreement_tier": "PREFERRED",
            "adas_certified": True,
        }, ADMIN)
        data = validate_success(resp, 200)
        assert data["network_status"] == "SUSPENDED"
        assert data["agreement_tier"] == "PREFERRED"
        assert data["adas_certified"] is True
        assert data["version"] == 2


# ---------------------------------------------------------------------------
# PartCatalogEntry
# ---------------------------------------------------------------------------

class TestPartCatalogEntry:
    def test_part_catalog_entry_discontinue_patch(self, api):
        """PRD §3.1: "the administrator may later update its
        `nags_list_price_cents` or move its `status` to `DISCONTINUED`,
        incrementing the entry's `version`."

        Design: Corner/entities/part_catalog_entry_discontinue_patch
        """
        part = make_part(part_number="AM-DISC-1", part_category="SIDE_GLASS",
                         nags_list_price_cents=40000)
        resp = api.update_part_catalog_entry(part["id"], {"status": "DISCONTINUED"}, ADMIN)
        data = validate_success(resp, 200)
        assert data["status"] == "DISCONTINUED"
        assert data["version"] == 2

    def test_part_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate ...
        `ERR_PART_NOT_FOUND` ..."

        Design: Corner/entities/part_get_not_found
        """
        resp = api.get_part_catalog_entry(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PART_NOT_FOUND)


# ---------------------------------------------------------------------------
# Not-found reads across the remaining entities
# ---------------------------------------------------------------------------

class TestNotFoundReads:
    def test_claim_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate ...
        `ERR_CLAIM_NOT_FOUND` ..."

        Design: Corner/entities/claim_get_not_found
        """
        resp = api.get_claim(NON_EXISTENT_UUID, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    def test_work_order_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate ...
        `ERR_WORK_ORDER_NOT_FOUND` ..."

        Design: Corner/entities/work_order_get_not_found
        """
        resp = api.get_work_order(NON_EXISTENT_UUID, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND)

    def test_invoice_get_not_found(self, api):
        """PRD §3.5: "Reading an invoice that does not exist surfaces
        `ERR_INVOICE_NOT_FOUND`..."

        Design: Corner/entities/invoice_get_not_found
        """
        resp = api.get_invoice(NON_EXISTENT_UUID, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)

    def test_calibration_event_verify_not_found(self, api):
        """PRD §3.4: "An outcome recorded against a calibration event that does
        not exist surfaces `ERR_CALIBRATION_EVENT_NOT_FOUND`."

        Design: Corner/entities/calibration_event_verify_not_found
        """
        resp = api.verify_calibration_event(
            NON_EXISTENT_UUID, {"outcome": "VERIFIED", "report_reference": "X"},
            TEST_USERS["shop_operator_headers"])
        validate_error(resp, ApiErrorId.ERR_CALIBRATION_EVENT_NOT_FOUND)

    def test_warranty_claim_get_not_found(self, api):
        """PRD §2.8: "every path and body resource reference must resolve,
        validated left to right, yielding the appropriate ...
        `ERR_WARRANTY_CLAIM_NOT_FOUND` ..."

        Design: Corner/entities/warranty_claim_get_not_found
        """
        resp = api.get_warranty_claim(NON_EXISTENT_UUID, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND)

    def test_fraud_alert_get_not_found(self, api):
        """PRD §3.6: "a missing alert surfaces `ERR_FRAUD_ALERT_NOT_FOUND`".

        Design: Corner/entities/fraud_alert_get_not_found
        """
        resp = api.get_fraud_alert(NON_EXISTENT_UUID, INVESTIGATOR)
        validate_error(resp, ApiErrorId.ERR_FRAUD_ALERT_NOT_FOUND)


# ---------------------------------------------------------------------------
# Regulation existence at claim intake
# ---------------------------------------------------------------------------

class TestStateRegulationMissingAtVerify:
    def test_state_regulation_missing_at_verify(self, api):
        """PRD §3.2: "Intake performs two provisional computations, which require
        the referenced policy to exist (`ERR_POLICY_NOT_FOUND`) and a
        StateRegulation to exist for the incident state
        (`ERR_STATE_REGULATION_NOT_FOUND`)."

        Design: Corner/validations/state_regulation_missing_at_verify
        """
        make_regulation("FL")
        ph = make_policyholder(full_name="No Reg", email="nr@x.com")
        pol = make_policy(ph["id"])
        from test_helpers import create_claim_payload, make_policyholder_headers
        resp = api.create_claim(
            create_claim_payload(pol["id"], incident_state_code="NV",
                                 service_zip_code="88901"),
            make_policyholder_headers(ph["id"]))
        validate_error(resp, ApiErrorId.ERR_STATE_REGULATION_NOT_FOUND)
        _data, meta = validate_paginated(api.list_state_regulations(ADJUSTER))
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# RBAC: admin-exclusive endpoints
# ---------------------------------------------------------------------------

class TestRbacAdminOnly:
    def test_rbac_adjuster_cannot_create_shops(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_adjuster_cannot_create_shops
        """
        resp = api.create_glass_shop(
            create_glass_shop_payload(shop_name="Forbidden"), ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


# ---------------------------------------------------------------------------
# Auth header presence
# ---------------------------------------------------------------------------

class TestAuthHeaders:
    def test_missing_auth_headers(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers
        """
        resp = api._request("GET", f"/policyholders/{NON_EXISTENT_UUID}",
                            headers={"X-User-Role": "NetworkAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class TestLogicalClock:
    def test_logical_clock_default_and_set(self, api):
        """PRD §2.4: "At server startup the logical clock reads exactly
        2026-05-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter. An admin-only test-driving capability, restricted to
        `NetworkAdmin`, advances the logical clock to a supplied `to_iso8601`
        instant and reports the resulting `current_utc`."

        Design: Corner/cross_cutting_layers/logical_clock_default_and_set
        """
        first = make_policyholder(full_name="Clock Def", email="clk@x.com")
        assert first["created_at"].startswith("2026-05-01T00:00:00")
        resp = api.set_clock("2026-06-15T08:30:00Z", ADMIN)
        data = validate_success(resp, 200)
        assert data["current_utc"].startswith("2026-06-15T08:30:00")
        second = make_policyholder(full_name="Clock Set", email="clk2@x.com")
        assert second["created_at"].startswith("2026-06-15T08:30:00")


# ---------------------------------------------------------------------------
# Policy filtered listing
# ---------------------------------------------------------------------------

class TestPolicyFilteredList:
    def test_policies_filtered_list_by_policyholder(self, api):
        """PRD §3.1: "The policy list supports filtering by `policyholder_id`
        and by `status`."

        Design: Corner/endpoints/policies_filtered_list_by_policyholder
        """
        pa = make_policyholder(full_name="Pol A", email="pla@x.com")
        pb = make_policyholder(full_name="Pol B", email="plb@x.com")
        make_policy(pa["id"], policy_number="PN-PLA-1")
        make_policy(pb["id"], policy_number="PN-PLB-1", coverage_type="LIABILITY",
                    deductible_cents=25000)
        data, meta = validate_paginated(
            api.list_policies(ADMIN, params={"policyholder_id": pa["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["policy_number"] == "PN-PLA-1"


# ---------------------------------------------------------------------------
# Difficulty: auth vs existence priority
# ---------------------------------------------------------------------------

class TestAuthVsExistencePriority:
    def test_unauthorized_role_masks_not_found(self, api):
        """PRD §2.8: "Every request is then evaluated against the following
        ordered cascade, and a failure in an earlier category masks the
        evaluation of later categories: ... 2. **Role permission** — the role
        must be authorized for the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
        ... 4. **Existence** — every path and body resource reference must
        resolve..."

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_existence_on_claim_read
        """
        # verify-coverage is ClaimAdjuster-exclusive; Policyholder is rejected at
        # category 2 before the nonexistent claim id is ever resolved.
        resp = api.verify_coverage(NON_EXISTENT_UUID, {}, TEST_USERS["policyholder_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_authorized_role_reaches_existence_check(self, api):
        """PRD §2.8: "Every request is then evaluated against the following
        ordered cascade, and a failure in an earlier category masks the
        evaluation of later categories: ... 4. **Existence** — every path and
        body resource reference must resolve, validated left to right, yielding
        the appropriate ... `ERR_CLAIM_NOT_FOUND` ..."

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_existence_on_claim_read
        """
        resp = api.verify_coverage(NON_EXISTENT_UUID, {}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)
