"""Claims register: late-flag boundary, filing rules, filters, pagination."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_case_payload, file_claim_payload, make_creditor_headers,
    create_creditor, create_case, create_asset, file_claim,
    review_and_allow_claim, setup_case_in_claims_administration,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]

BAR_DATE = "2026-06-01T00:00:00Z"


def _claims_admin_ctx(case_number):
    return setup_case_in_claims_administration(case_number=case_number)


class TestLateFlagBoundary:
    def test_claim_received_exactly_at_bar_date_is_timely(self, api):
        """PRD §3.2: "once a bar date exists, a claim is late exactly when its
        `received_at` is strictly after `claim_bar_date` — a claim received at
        the precise bar-date instant is timely, because the comparison is
        strictly-greater."

        Design: Difficulty/dual_variant_calc/claim_late_flag_timely_vs_late_same_instant_boundary
        """
        ctx = _claims_admin_ctx("26-10002")
        cred_id = ctx["creditor"]["id"]
        claim = file_claim(ctx["case"]["id"], cred_id, received_at=BAR_DATE)
        assert claim["late"] is False, \
            "a claim received at the precise bar-date instant is timely"

    def test_claim_one_second_after_bar_date_is_late(self, api):
        """PRD §3.2: "once a bar date exists, a claim is late exactly when its
        `received_at` is strictly after `claim_bar_date` — a claim received at
        the precise bar-date instant is timely, because the comparison is
        strictly-greater."

        Design: Difficulty/dual_variant_calc/claim_late_flag_timely_vs_late_same_instant_boundary
        """
        ctx = _claims_admin_ctx("26-10002")
        cred_id = ctx["creditor"]["id"]
        timely = file_claim(ctx["case"]["id"], cred_id, received_at=BAR_DATE)
        late = file_claim(ctx["case"]["id"], cred_id,
                          received_at="2026-06-01T00:00:01Z")
        assert timely["late"] is False
        assert late["late"] is True, \
            "one second strictly after the bar date flips the late flag"


class TestClaimFilingRules:
    def test_claim_initial_state_is_filed(self, api):
        """PRD §3.2: "Every claim enters the register in `FILED` status."
        PRD §3.2: "The `claim_number` is a sequential claim-register number
        within the case, assigned at filing in order of `received_at`, with
        ties broken first by the creditor's `created_at` and then by the
        claim's own `created_at`."

        Design: Corner/state_machines/claim_initial_state_is_filed
        """
        ctx = _claims_admin_ctx("26-20010")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"])
        assert claim["status"] == "FILED"
        # The PRD pins claim_number as sequential within the case register
        # without pinning the absolute origin; assert presence and type.
        assert isinstance(claim["claim_number"], int)

    def test_claim_secured_requires_asset_reference(self, api):
        """PRD §3.2: "A claim in the `SECURED` class must also carry
        `secured_by_asset_id` naming the encumbering asset; omitting it is a
        malformed-body rejection (`ERR_INVALID_REQUEST`), and naming an asset
        that does not exist or belongs to a different case is a referential
        rejection (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422)."

        Design: Corner/entities/claim_secured_requires_asset_reference
        """
        ctx = _claims_admin_ctx("26-20003")
        cred_id = ctx["creditor"]["id"]
        payload = file_claim_payload(creditor_id=cred_id,
                                     filed_amount_cents=50000,
                                     priority_class="SECURED")
        resp = api.file_claim(ctx["case"]["id"], payload,
                              make_creditor_headers(cred_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_claim_secured_with_foreign_case_asset_rejected(self, api):
        """PRD §3.2: "A claim in the `SECURED` class must also carry
        `secured_by_asset_id` naming the encumbering asset; omitting it is a
        malformed-body rejection (`ERR_INVALID_REQUEST`), and naming an asset
        that does not exist or belongs to a different case is a referential
        rejection (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422)."

        Design: Corner/entities/claim_secured_with_foreign_case_asset_rejected
        """
        cred = create_creditor(creditor_ref="CR-S-2")
        case_a = create_case(case_number="26-20004", debtor_name="DA")
        asset_a = create_asset(case_a["id"], scheduled_value_cents=100000)
        ctx_b = setup_case_in_claims_administration(case_number="26-20005")
        case_b = ctx_b["case"]

        payload = file_claim_payload(creditor_id=cred["id"],
                                     filed_amount_cents=50000,
                                     priority_class="SECURED",
                                     secured_by_asset_id=asset_a["id"])
        resp = api.file_claim(case_b["id"], payload,
                              make_creditor_headers(cred["id"]))
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestCreditorDefaults:
    def test_creditor_insider_default_false(self, api):
        """PRD §3.2: "Before any claim can be filed, a `Clerk` registers each
        creditor with its `legal_name`, a unique external reference
        `creditor_ref` (duplicates rejected with `ERR_DUPLICATE`), a service
        `contact_email`, and the `insider` flag (defaulting to false) that marks
        a §101(31) insider of the debtor and drives the longer one-year
        preference lookback described in §3.5."

        Design: Corner/entities/creditor_insider_default_false
        """
        cred = create_creditor(creditor_ref="CR-D-1")
        assert cred["insider"] is False


class TestRegisterListing:
    def test_claim_list_filter_by_status_and_late(self, api):
        """PRD §3.2: "The claims register is browsable per case with optional
        filters `status`, `priority_class`, `late`, and `creditor_id`; a
        cross-case claim search supports foreign-key reverse lookup by
        `creditor_id`, `secured_by_asset_id`, `objection_id`, and
        `reclassified_from_claim_id`."

        Design: Corner/entities/claim_list_filter_by_status_and_late
        """
        ctx = _claims_admin_ctx("26-20006")
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        c1 = file_claim(case_id, cred_id, received_at="2026-02-01T00:00:00Z")
        review_and_allow_claim(c1["id"])
        file_claim(case_id, cred_id, received_at="2026-07-01T00:00:00Z")  # late, FILED

        resp = api.list_case_claims(case_id, TRUSTEE,
                                    params={"status": "ALLOWED", "late": "false"})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, "only the ALLOWED timely claim matches"
        assert data[0]["id"] == c1["id"]

    def test_pagination_defaults_on_claims_register(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; if not provided it defaults to 10, and it accepts a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies
        the number of items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/cross_cutting_layers/pagination_defaults_on_claims_register
        """
        ctx = _claims_admin_ctx("26-20062")
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        file_claim(case_id, cred_id, received_at="2026-02-01T00:00:00Z",
                   filed_amount_cents=10000)
        file_claim(case_id, cred_id, received_at="2026-02-02T00:00:00Z",
                   filed_amount_cents=20000)
        file_claim(case_id, cred_id, received_at="2026-02-03T00:00:00Z",
                   filed_amount_cents=30000, priority_class="PRIORITY_WAGE")

        resp = api.list_case_claims(case_id, TRUSTEE)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")


class TestNotFound:
    def test_get_missing_case_returns_not_found(self, api):
        """PRD §2.10: "For any endpoint whose path contains multiple resource
        identifiers, the server validates existence sequentially from left to
        right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource —
        for example, a request targeting a claim under a non-existent case
        fails on the case identifier before the claim identifier is ever
        examined."

        Design: Corner/entities/get_missing_case_returns_not_found
        """
        resp = api.get_case(NON_EXISTENT_UUID, TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
