"""Business accounts, compliance policy activation, and role/ownership
authorization (PRD §2.1, §2.11, §3.1, §3.2, §4)."""
from test_helpers import (
    ApiErrorId,
    assert_business_account,
    create_recycler_payload,
    log_sanitization,
    make_account_manager_headers,
    make_destruction_technician_headers,
    new_account,
    new_active_policy,
    set_clock,
    setup_triaged_item,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAccountCreation:
    def test_account_create_applies_defaults(self, api, platform_admin_headers):
        """PRD §3.1: "The account's `tier` may be supplied at creation and otherwise defaults to `STANDARD`; the recognized tiers are `STANDARD`, `VOLUME`, and `ENTERPRISE`."
        PRD §3.1: "A new account starts with `status` `ACTIVE`, a `credit_balance_cents` of zero, and a `lifetime_diverted_kg` of zero."

        Design: Corner/entities/account_create_defaults
        """
        resp = api.create_account(
            {"company_name": "Default Co", "contact_email": "d@default.example"},
            platform_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_business_account(data)
        assert data["tier"] == "STANDARD"
        assert data["status"] == "ACTIVE"
        assert data["credit_balance_cents"] == 0
        assert data["lifetime_diverted_kg"] == 0

    def test_account_create_missing_company_name_rejected(self, api, platform_admin_headers):
        """PRD §2.6: "5. Request body schema — missing required fields, type mismatches, invalid enum members, a `weight_kg` that is not greater than zero, a `declared_item_count` below one, an `asking_price_cents` below `floor_price_cents`, a missing `pickup_route` on a `PICKUP` manifest (or one supplied on `DROPOFF`), or a `scheduled_end` that is not strictly after `scheduled_start` all yield `ERR_VALIDATION`."

        Design: Corner/entities/account_create_missing_required_company_name
        """
        resp = api.create_account({"contact_email": "no-name@x.example"}, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400


class TestPolicyActivation:
    def test_policy_activation_deactivates_others(self, api, platform_admin_headers):
        """PRD §2.11: "Creating a policy with `is_active` set to true atomically deactivates every other policy; a policy created with `is_active` false (the default) leaves the current activation untouched."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order."

        Design: Corner/cross_cutting_complexity_layers/policy_activation_deactivates_others
        """
        p1 = new_active_policy(standard="R2", sanitization_methods_allowed=["NIST_CLEAR"])
        # Advance the clock so the two policies have distinct created_at values
        # and the ascending list order is deterministic.
        set_clock("2026-05-01T01:00:00Z")
        p2 = new_active_policy(
            standard="E_STEWARDS",
            sanitization_methods_allowed=["PHYSICAL_DESTROY"],
            export_allowed=False,
            weight_cert_freshness=0.3,
            weight_volume=0.2,
            weight_violations=0.5,
        )

        policies, _meta = validate_paginated(api.list_compliance_policies(platform_admin_headers))
        assert policies[0]["id"] == p1["id"]
        assert policies[0]["is_active"] is False
        assert policies[1]["id"] == p2["id"]
        assert policies[1]["is_active"] is True


class TestRoleAuthorization:
    def test_account_manager_cannot_create_recycler(self, api):
        """PRD §2.1: "When the headers are valid but the named role is not permitted on the targeted endpoint, the request is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/account_manager_cannot_create_recycler
        """
        account = new_account("RB Co", "rb@x.example")
        resp = api.create_recycler(
            create_recycler_payload(name="RecRB"),
            make_account_manager_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403

    def test_account_manager_cannot_read_other_account(self, api):
        """PRD §2.1: "so an account manager may create and amend manifests only for its own account (`account_id` equal to `X-User-ID`) and may touch resources beneath it only when the owning manifest's `account_id` equals `X-User-ID`. A violation of this ownership rule is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/account_manager_cannot_read_other_account
        """
        account_one = new_account("Own One", "o1@x.example")
        account_two = new_account("Own Two", "o2@x.example")
        resp = api.get_account(account_two["id"], make_account_manager_headers(account_one["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403

    def test_destruction_technician_cannot_verify(self, api):
        """PRD §2.6: "2. Role authorization — a role not listed for the endpoint yields `ERR_UNAUTHORIZED`."
        PRD §2.6: "12. Segregation of duties on sanitization verification — `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/destruction_technician_cannot_verify
        """
        new_active_policy(sanitization_methods_allowed=["NIST_CLEAR"])
        ctx = setup_triaged_item(disposition="REFURB", data_bearing=True, declared_grade="B")
        record = log_sanitization(ctx["item"]["id"], method="NIST_CLEAR", outcome="PASS",
                                  tech_id="tech-1")
        # Even a *different* technician is refused: verification belongs to the
        # ComplianceOfficer role, so the role gate fires before any SoD check.
        resp = api.verify_sanitization(record["id"], {"verdict": "APPROVE"},
                                       make_destruction_technician_headers("tech-2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
