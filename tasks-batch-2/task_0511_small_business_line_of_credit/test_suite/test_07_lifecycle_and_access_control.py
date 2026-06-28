"""CRUD, state-transition legality, blocklist/feed/approval guards, listing, repricing, NSF
account-closed handling, RBAC and segregation of duties, OCC on increase approval, version
increments, and the application-expiry sweep.

Covers the remaining corner instances across the entities, state_machines, validations,
endpoints, errors, rbac, cross_cutting_complexity_layers sections.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    create_merchant,
    create_bank_feed,
    create_merchant_payload,
    create_submitted_application,
    create_active_credit_line,
    create_active_line_with_draw,
    setup_charged_off_line,
    take_draw,
    schedule_remittance,
    settle_remittance,
    set_clock,
    get_line,
    create_credit_line_payload,
    create_application_payload,
    create_draw_payload,
    create_line_increase_request_payload,
    approve_line_increase_payload,
    create_renewal_offer_payload,
    create_statement_payload,
    settle_remittance_payload,
    sum_ledger_amounts,
    UW1,
    UW2,
    SV1,
    CO1,
)


# ─── entities (CRUD) ───────────────────────────────────────────────────
class TestMerchantCrud:
    def test_create_merchant_returns_201_with_defaults(self, api):
        """POST /merchants returns 201 with status ACTIVE and version 1.

        PRD §3.1: "A merchant's status begins at ACTIVE and may later be moved to BLOCKLISTED."
        PRD §2.4: "version is an integer that begins at 1 and increments by one on every
        mutation of the resource."

        Design: Corner/entities/create_merchant_returns_201_with_all_fields
        """
        res = api.create_merchant(create_merchant_payload(legal_name="New Co"))
        merchant = validate_success(res, 201)
        assert merchant["status"] == "ACTIVE"
        assert merchant["version"] == 1
        assert merchant["legal_name"] == "New Co"

    def test_get_merchant_not_found(self, api):
        """A well-formed but non-existent merchant id returns ERR_NOT_FOUND (404).

        PRD §2.5: "the system validates the existence of each path segment in left-to-right
        order and rejects the first missing identifier with ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/get_merchant_not_found_returns_404
        """
        res = api.get_merchant(NON_EXISTENT_UUID, UW1)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_create_merchant_missing_ein_rejected(self, api):
        """Omitting the required ein returns ERR_INVALID_REQUEST (400).

        PRD §3.1: "A merchant is created with a legal_name, an ein (the Employer Identification
        Number, which must be exactly nine digits and unique across all merchants)"

        Design: Corner/entities/create_merchant_missing_ein_returns_invalid_request
        """
        payload = create_merchant_payload(legal_name="No EIN Co")
        del payload["ein"]
        res = api.create_merchant(payload)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestLedgerImmutability:
    def test_ledger_entries_have_no_version_and_match_draw(self, api):
        """A draw produces DRAW_PRINCIPAL + DRAW_FEE entries; ledger entries carry no version.

        PRD §2.4: "A LedgerEntry has neither updated_at nor version."
        PRD §2.8: "On funding, the draw appends two ledger entries: a DRAW_PRINCIPAL entry for
        the principal and a DRAW_FEE entry for the computed fee."

        Design: Corner/entities/ledger_entry_immutable_no_version_field
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        take_draw(line["id"], 100_000)  # TIER_A fee 8000
        entries, meta = validate_paginated(api.list_ledger_entries_for_line(line["id"], SV1))
        assert meta["total_count"] == 2
        for e in entries:
            assert "version" not in e
            assert "updated_at" not in e
            assert is_valid_uuid(e["id"])
        dp, _ = validate_paginated(
            api.list_ledger_entries_for_line(line["id"], SV1, params={"entry_type": "DRAW_PRINCIPAL"})
        )
        df, _ = validate_paginated(
            api.list_ledger_entries_for_line(line["id"], SV1, params={"entry_type": "DRAW_FEE"})
        )
        assert sum_ledger_amounts(dp, "DRAW_PRINCIPAL") == 100_000
        assert sum_ledger_amounts(df, "DRAW_FEE") == 8000


# ─── state machines ────────────────────────────────────────────────────
class TestStateTransitionLegality:
    def test_approve_application_from_draft_rejected(self, api):
        """Approving a DRAFT application returns ERR_INVALID_STATE (409); stays DRAFT.

        PRD §3.2: "Approving moves the application from SUBMITTED to APPROVED."

        Design: Corner/state_machines/approve_application_from_draft_returns_invalid_state
        """
        from test_helpers import create_draft_application
        _, _, app = create_draft_application()
        res = api.approve_application(app["id"], UW2)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "DRAFT"

    def test_charge_off_from_active_rejected(self, api):
        """Charging off an ACTIVE line returns ERR_INVALID_STATE (409) before any OCC check.

        PRD §3.6: "From DEFAULTED, a CreditOfficer may charge off the line"

        Design: Corner/state_machines/charge_off_from_active_returns_invalid_state
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        ver = line["version"]
        from test_helpers import charge_off_payload, CO_CHARGEOFF
        res = api.charge_off(line["id"], charge_off_payload(ver), CO_CHARGEOFF)
        validate_error(res, "ERR_INVALID_STATE")
        after = get_line(line["id"])
        assert after["status"] == "ACTIVE"

    def test_settle_already_settled_remittance_rejected(self, api):
        """Settling an already-SETTLED remittance returns ERR_INVALID_STATE; no re-allocation.

        PRD §3.5: "A remittance may be settled only when it is SCHEDULED"

        Design: Corner/state_machines/settle_already_settled_remittance_returns_invalid_state
        """
        set_clock("2026-05-18T00:00:00Z")
        line, _ = create_active_line_with_draw(
            500_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
        )
        remit = schedule_remittance(line["id"], "2026-05-20T00:00:00Z")
        set_clock("2026-05-20T00:00:00Z")
        settled = settle_remittance(remit["id"], "SUCCESS")
        assert settled["status"] == "SETTLED"
        assert settled["amount_cents"] == 10800
        res = api.settle_remittance(remit["id"], settle_remittance_payload("SUCCESS"), SV1)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_remittance(remit["id"], SV1), 200)
        assert after["status"] == "SETTLED"
        assert after["amount_cents"] == 10800

    def test_close_charged_off_line_rejected(self, api):
        """A CHARGED_OFF (terminal) line rejects close with ERR_INVALID_STATE (409).

        PRD §3.3: "A Servicer may also close a line, moving it from ACTIVE to CLOSED"

        Design: Corner/state_machines/terminal_charged_off_line_rejects_close
        """
        line, _, line_after = setup_charged_off_line(principal_cents=200_000)
        assert line_after["status"] == "CHARGED_OFF"
        res = api.close_credit_line(line["id"], SV1)
        validate_error(res, "ERR_INVALID_STATE")
        after = get_line(line["id"])
        assert after["status"] == "CHARGED_OFF"


# ─── validations ───────────────────────────────────────────────────────
class TestApprovalGuards:
    def test_blocklisted_merchant_blocks_approval(self, api):
        """Approving an application whose merchant is BLOCKLISTED returns ERR_MERCHANT_BLOCKLISTED.

        PRD §3.2: "the referenced merchant must not be BLOCKLISTED (else
        ERR_MERCHANT_BLOCKLISTED)"

        Design: Corner/validations/merchant_blocklisted_blocks_approval
        """
        merchant, feed, app = create_submitted_application()
        validate_success(api.blocklist_merchant(merchant["id"], CO1), 200)
        res = api.approve_application(app["id"], UW2)
        validate_error(res, "ERR_MERCHANT_BLOCKLISTED")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "SUBMITTED"

    def test_submit_against_stale_feed_rejected(self, api):
        """Submitting a DRAFT application whose feed is STALE returns ERR_FEED_STALE; stays DRAFT.

        PRD §3.2: "a stale feed at submit time is rejected with ERR_FEED_STALE"

        Design: Corner/validations/submit_against_stale_feed_returns_feed_stale
        """
        from test_helpers import create_draft_application
        merchant, feed, app = create_draft_application()
        validate_success(api.mark_bank_feed_stale(feed["id"], UW1), 200)
        res = api.submit_application(app["id"], UW1)
        validate_error(res, "ERR_FEED_STALE")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "DRAFT"

    def test_create_line_from_unapproved_application_rejected(self, api):
        """Creating a CreditLine from a SUBMITTED (not APPROVED) application is rejected.

        PRD §3.3: "A line may be created only from an application in APPROVED status that has not
        already originated a line — one line per application — otherwise the request is rejected
        with ERR_APPLICATION_NOT_APPROVED."

        Design: Corner/validations/create_line_from_unapproved_application_rejected
        """
        merchant, feed, app = create_submitted_application()
        res = api.create_credit_line(create_credit_line_payload(app["id"]), CO1)
        validate_error(res, "ERR_APPLICATION_NOT_APPROVED")


# ─── endpoints ─────────────────────────────────────────────────────────
class TestListingAndRepricing:
    def test_list_credit_lines_paginated_envelope(self, api):
        """GET /credit-lines returns an array envelope with total_count and has_more.

        PRD §2.3: "List-based responses include the following fields in the meta object of the
        response envelope: limit, offset, total_count, and has_more."

        Design: Corner/endpoints/list_credit_lines_paginated_envelope
        """
        merchant, _, _, line = create_active_credit_line(cadence="DAILY")
        data, meta = validate_paginated(
            api.list_credit_lines(SV1, params={"merchant_id": merchant["id"]})
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_renewal_accept_reprices_line_fee_factor(self, api):
        """Accepting an OFFERED renewal writes new_fee_factor_bps onto the line's fee_factor_bps.

        PRD §3.7: "Accepting moves it from OFFERED to ACCEPTED and, as a cross-entity effect,
        writes the offer's new_fee_factor_bps onto the parent line's fee_factor_bps and bumps
        the line's version"

        Design: Corner/endpoints/renewal_accept_reprices_line_fee_factor
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        assert line["fee_factor_bps"] == 800
        offer = validate_success(
            api.create_renewal_offer(
                line["id"], create_renewal_offer_payload(new_fee_factor_bps=1200, term_days=180), CO1
            ),
            201,
        )
        accepted = validate_success(api.accept_renewal_offer(offer["id"], SV1), 200)
        assert accepted["status"] == "ACCEPTED"
        after = get_line(line["id"])
        assert after["fee_factor_bps"] == 1200


# ─── errors ────────────────────────────────────────────────────────────
class TestNsfAccountClosed:
    def test_account_closed_fails_without_retry(self, api):
        """ACCOUNT_CLOSED fails the debit, bumps a strike, and spawns no retry.

        PRD §3.5: "On an ACCOUNT_CLOSED outcome, the remittance likewise moves from SCHEDULED to
        FAILED, its failure_reason is set to ACCOUNT_CLOSED, and the line's nsf_strike_count is
        incremented by one exactly as for NSF — but because a closed account is permanent, no
        retry is ever spawned and next_retry_remittance_id stays null."

        Design: Corner/errors/settle_account_closed_sets_failure_reason_no_retry
        """
        set_clock("2026-05-13T00:00:00Z")
        line, _ = create_active_line_with_draw(
            200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
        )
        remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
        set_clock("2026-05-15T00:00:00Z")
        failed = settle_remittance(remit["id"], "ACCOUNT_CLOSED")
        assert failed["status"] == "FAILED"
        assert failed["failure_reason"] == "ACCOUNT_CLOSED"
        assert failed["next_retry_remittance_id"] is None
        after = get_line(line["id"])
        assert after["nsf_strike_count"] == 1
        _, meta = validate_paginated(
            api.list_remittances(line["id"], SV1, params={"status": "SCHEDULED"})
        )
        assert meta["total_count"] == 0


class TestLineIncreaseScoreRegression:
    def test_increase_denied_on_score_regression(self, api):
        """Approving an increase whose new score regresses below the prior score is rejected.

        PRD §3.7: "The new score must be at least the prior score; a regression is rejected with
        ERR_SCORE_BELOW_FLOOR."

        Design: Corner/errors/line_increase_denied_score_regression
        """
        # Origination on a strong feed (score 85), then a weaker feed for the increase.
        merchant, strong_feed, _, line = create_active_credit_line(cadence="DAILY")
        weak_feed = create_bank_feed(
            merchant["id"], plaid_item_id="p_weak", pulled_at="2026-04-29T00:00:00Z",
            avg_daily_balance_cents=700_000, nsf_count_90d=0, deposit_volume_cents=3_000_000,
        )
        lir = validate_success(
            api.create_line_increase_request(
                line["id"],
                create_line_increase_request_payload(weak_feed["id"], requested_limit_cents=1_500_000),
                SV1,
            ),
            201,
        )
        ver = get_line(line["id"])["version"]
        res = api.approve_line_increase_request(lir["id"], approve_line_increase_payload(ver), CO1)
        validate_error(res, "ERR_SCORE_BELOW_FLOOR")
        after = validate_success(api.get_line_increase_request(lir["id"], CO1), 200)
        assert after["status"] == "PENDING"
        line_after = get_line(line["id"])
        assert line_after["credit_limit_cents"] == 1_000_000


# ─── rbac / segregation of duties ─────────────────────────────────────
class TestAccessControl:
    def test_servicer_cannot_approve_application(self, api, servicer_headers):
        """A Servicer calling approve (an Underwriter op) is rejected with ERR_FORBIDDEN_ROLE.

        PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform
        the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/servicer_cannot_approve_application
        """
        merchant, feed, app = create_submitted_application()
        res = api.approve_application(app["id"], servicer_headers)
        validate_error(res, "ERR_FORBIDDEN_ROLE")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "SUBMITTED"

    def test_underwriter_cannot_take_draw(self, api):
        """An Underwriter calling draw (a Servicer op) is rejected with ERR_FORBIDDEN_ROLE.

        PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform
        the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/underwriter_cannot_take_draw
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        res = api.create_draw(line["id"], create_draw_payload(100_000), UW1)
        validate_error(res, "ERR_FORBIDDEN_ROLE")
        after = get_line(line["id"])
        assert after["outstanding_principal_cents"] == 0

    def test_self_approve_segregation_of_duties(self, api):
        """The underwriter who submitted an application may not approve it.

        PRD §3.2: "all three are reserved to an Underwriter who is not the submitter — that is,
        the acting X-User-ID must differ from the stored submitted_by_user_id, or the action is
        rejected with ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/rbac/underwriter_self_approve_segregation_of_duties
        """
        merchant, feed, app = create_submitted_application()  # submitted by uw_1
        res = api.approve_application(app["id"], UW1)  # same operator approves
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "SUBMITTED"

    def test_missing_headers_returns_unauthenticated(self, api):
        """A request with no auth headers returns ERR_UNAUTHENTICATED (401).

        PRD §2.1: "If either header is missing, or if X-User-Role does not name one of these
        three roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/missing_headers_returns_unauthenticated
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        res = api.raw_get(f"/credit-lines/{line['id']}", headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── cross-cutting complexity layers ──────────────────────────────────
class TestOptimisticConcurrency:
    def test_increase_approve_with_stale_version_rejected(self, api):
        """Approving an increase with a stale expected_credit_line_version returns
        ERR_STALE_VERSION (412); the limit is unchanged.

        PRD §2.6: "If that value does not equal the line's current version — because another
        writer has advanced the line since the client read it — the request is rejected with
        ERR_STALE_VERSION (HTTP 412), and no mutation is applied."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_increase_approve
        """
        merchant, feed, _, line = create_active_credit_line(cadence="DAILY")
        feed2 = create_bank_feed(
            merchant["id"], plaid_item_id="p2", pulled_at="2026-04-29T00:00:00Z",
            avg_daily_balance_cents=2_000_000, nsf_count_90d=0, deposit_volume_cents=9_000_000,
        )
        lir = validate_success(
            api.create_line_increase_request(
                line["id"],
                create_line_increase_request_payload(feed2["id"], requested_limit_cents=1_500_000),
                SV1,
            ),
            201,
        )
        stale_ver = get_line(line["id"])["version"]
        # A draw advances the line version, making stale_ver stale.
        take_draw(line["id"], 100_000)
        res = api.approve_line_increase_request(
            lir["id"], approve_line_increase_payload(stale_ver), CO1
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
        after = validate_success(api.get_line_increase_request(lir["id"], CO1), 200)
        assert after["status"] == "PENDING"
        line_after = get_line(line["id"])
        assert line_after["credit_limit_cents"] == 1_000_000

    def test_version_increments_on_each_mutation(self, api):
        """CreditLine.version starts at 1 and increments by one per mutation (3 after freeze+unfreeze).

        PRD §2.4: "version is an integer that begins at 1 and increments by one on every
        mutation of the resource."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        assert line["version"] == 1
        validate_success(api.freeze_credit_line(line["id"], SV1), 200)
        unfrozen = validate_success(api.unfreeze_credit_line(line["id"], SV1), 200)
        assert unfrozen["version"] == 3
        assert unfrozen["status"] == "ACTIVE"

    def test_application_expiry_sweep(self, api):
        """A SUBMITTED application older than the TTL is swept to EXPIRED.

        PRD §3.2: "Once the logical clock has advanced at least 14 days past the moment the
        application entered SUBMITTED (measured from its updated_at), the application is eligible
        to expire."

        Design: Corner/cross_cutting_complexity_layers/application_expiry_scheduled_sweep
        """
        set_clock("2026-05-01T00:00:00Z")
        merchant = create_merchant(monthly_revenue_cents=2_000_000)
        feed = create_bank_feed(
            merchant["id"], pulled_at="2026-04-30T00:00:00Z",
            avg_daily_balance_cents=2_000_000, nsf_count_90d=0, deposit_volume_cents=9_000_000,
        )
        app = validate_success(
            api.create_application(
                create_application_payload(merchant["id"], feed["id"], requested_limit_cents=1_000_000),
                UW1,
            ),
            201,
        )
        validate_success(api.submit_application(app["id"], UW1), 200)
        set_clock("2026-05-20T00:00:00Z")  # > 14 days later
        validate_success(api.expire_applications(UW1), 200)
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "EXPIRED"
