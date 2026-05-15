"""State rule CRUD + miscellaneous behaviors not covered elsewhere.

PRD §3.1 narrative on StateRule registration and replacement.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_state_rule,
    create_state_rule_payload,
    ensure_state_rule,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStateRuleCrud:

    def test_create_state_rule_pa_only(self, api):
        """PRD §4 endpoint table: POST /state-rules authorized role is
        PlanAdministrator only.

        Claim: any non-admin role calling POST /state-rules →
        ERR_FORBIDDEN.
        """
        from test_helpers import build_user_headers
        res = api.create_state_rule(
            create_state_rule_payload(state_code="CC"),
            build_user_headers("d-1", "Donor"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_get_state_rule_returns_canonical_shape(self, api):
        """PRD §3.1: state rules carry deduction_cap_cents, parity,
        lifetime_aggregate_cap_cents, k12_qualified.

        Claim: a freshly created state rule can be GET'd by state_code
        and returns those fields.
        """
        ensure_state_rule(
            "DD", deduction_cap_cents=300_000, parity="PARITY",
            lifetime_aggregate_cap_cents=20_000_000, k12_qualified=False,
        )
        res = api.get_state_rule("DD", TEST_USERS["admin_headers"])
        rule = validate_success(res, 200)
        assert_state_rule(rule)
        assert rule["state_code"] == "DD"
        assert rule["deduction_cap_cents"] == 300_000
        assert rule["parity"] == "PARITY"
        assert rule["lifetime_aggregate_cap_cents"] == 20_000_000
        assert rule["k12_qualified"] is False

    def test_replace_state_rule_increments_version(self, api):
        """PRD §3.1: "every replacement increments the rule's version."

        Claim: replacing a state rule with the same state_code
        increments version by 1.
        """
        rule = ensure_state_rule(
            "EE", deduction_cap_cents=100_000, parity="PARITY",
            lifetime_aggregate_cap_cents=10_000_000, k12_qualified=True,
        )
        original_version = rule["version"]
        res = api.create_state_rule(
            create_state_rule_payload(
                state_code="EE",
                deduction_cap_cents=200_000,
                parity="IN_STATE_ONLY",
                lifetime_aggregate_cap_cents=20_000_000,
                k12_qualified=False,
            ),
            TEST_USERS["admin_headers"],
        )
        # PRD §3.1: replacement is allowed (administrative POST).
        # The endpoint table marks /state-rules POST as code 201.
        updated = validate_success(res, 201)
        assert updated["state_code"] == "EE"
        assert updated["version"] == original_version + 1
        # Check that the new values stuck.
        assert updated["deduction_cap_cents"] == 200_000
        assert updated["parity"] == "IN_STATE_ONLY"

    def test_list_state_rules_paginated(self, api, admin_headers):
        """PRD §2.3 + §3.1: list endpoint with pagination.

        Claim: list_state_rules supports limit + offset paging shape.
        """
        for code in ("FA", "FB", "FC"):
            ensure_state_rule(code)
        data, meta = validate_paginated(
            api.list_state_rules(admin_headers, params={"limit": 2}),
        )
        assert len(data) <= 2
        assert meta["limit"] == 2


# ===========================================================================
# Tax report identity threading: Beneficiary read
# ===========================================================================
class TestBeneficiaryTaxReportRead:

    def test_beneficiary_can_read_tax_report_on_own_account(self, api):
        """PRD §4 endpoint table: GET /tax-reports/{id} authorized role
        is PlanAdministrator, Donor, Beneficiary.
        PRD §3.7: "A Donor or PlanAdministrator may retrieve any tax
        report by id (a Beneficiary may read tax reports on accounts
        they benefit from)."
        PRD §2.1: "the read-only views available to a beneficiary are
        restricted to accounts whose beneficiary_id equals X-User-ID."

        Claim: a Beneficiary can GET a tax report on their own account
        when X-User-ID = Beneficiary.id.
        """
        from test_helpers import (
            create_tax_report,
            make_beneficiary_headers,
            server_now_iso,
            setup_account_with_balance,
        )
        from datetime import datetime
        _donor, beneficiary, account = setup_account_with_balance(
            target_total_cents=100_000,
            contributions_split=[100_000],
        )
        year = datetime.fromisoformat(
            server_now_iso().replace("Z", "+00:00"),
        ).year
        tr = create_tax_report(account=account, tax_year=year)
        res = api.get_tax_report(
            tr["id"], make_beneficiary_headers(beneficiary["id"]),
        )
        retrieved = validate_success(res, 200)
        assert retrieved["id"] == tr["id"]
