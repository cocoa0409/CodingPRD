"""Voucher lifecycle: issuance gates, redemption checks and their order, lazy
expiry, revocation, suspension, and listing filters."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_voucher,
    create_partner,
    issue_voucher,
    make_referral_partner_headers,
    register_client,
    set_clock,
    setup_sorting_staff,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestVoucherRevocation:
    def test_voucher_revoke_terminal_lockdown(self, api):
        """PRD: "A voucher still `ISSUED` may be revoked by the owning partner or
        a `ProgramAdmin`, moving it to `REVOKED` — attempting to revoke a voucher
        in any other state is `ERR_INVALID_STATE`, and revocation, like expiry,
        does not return quota."
        PRD: "the voucher must still be `ISSUED` (`ERR_VOUCHER_NOT_REDEEMABLE`)"

        Design: Corner/state_machines/voucher_revoke_terminal_lockdown
        """
        staff = setup_sorting_staff()
        partner = create_partner("Agency", 5)
        client = register_client("C", 2, None, staff["headers"])
        voucher = issue_voucher(partner, client["id"], bonus_items=2,
                                expires_at="2026-12-01T00:00:00Z")

        revoked = validate_success(
            api.revoke_voucher(voucher["id"],
                               make_referral_partner_headers(partner["id"])),
            200)
        assert_voucher(revoked)
        assert revoked["status"] == "REVOKED"

        resp = api.revoke_voucher(voucher["id"],
                                  make_referral_partner_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.checkin_visit(client["id"], {"voucher_id": voucher["id"]},
                                 staff["headers"])
        validate_error(resp, ApiErrorId.ERR_VOUCHER_NOT_REDEEMABLE)


class TestVoucherExpiry:
    def test_voucher_lazy_expiry_on_read(self, api):
        """PRD: "A voucher whose expiry has been reached flips from `ISSUED` to
        `EXPIRED` the next time it is read or listed, and the same evaluation
        happens on any redemption attempt."

        Design: Corner/state_machines/voucher_lazy_expiry_on_read
        """
        partner = create_partner("Agency", 5)
        client = register_client("C", 2)
        voucher = issue_voucher(partner, client["id"], bonus_items=1,
                                expires_at="2026-08-05T00:00:00Z")
        assert voucher["status"] == "ISSUED"

        set_clock("2026-08-06T00:00:00Z")
        voucher = validate_success(api.get_voucher(voucher["id"], ADMIN), 200)
        assert voucher["status"] == "EXPIRED", "at/after expires_at the read flips it"

    def test_expired_voucher_reports_expiry_before_client_mismatch(self, api):
        """PRD: "When a voucher is presented, four further checks follow in
        order: the voucher must not have reached its `expires_at` (at or after
        expiry the voucher flips to `EXPIRED` and the attempt fails with
        `ERR_VOUCHER_EXPIRED`); the voucher must still be `ISSUED`
        (`ERR_VOUCHER_NOT_REDEEMABLE`); the voucher's `client_id` must name the
        client being checked in (`ERR_VOUCHER_CLIENT_MISMATCH`); and the
        voucher's issuing partner must be `ACTIVE` (`ERR_PARTNER_SUSPENDED`)."

        Design: Difficulty/priority_pair_validation_conflict/voucher_expired_temporal_beats_client_mismatch_referential
        """
        staff = setup_sorting_staff()
        partner = create_partner("Agency B", 5)
        client_a = register_client("A", 2, None, staff["headers"])
        client_b = register_client("B", 2, None, staff["headers"])
        voucher = issue_voucher(partner, client_b["id"], bonus_items=2,
                                expires_at="2026-08-10T00:00:00Z")

        set_clock("2026-08-11T00:00:00Z")
        resp = api.checkin_visit(client_a["id"], {"voucher_id": voucher["id"]},
                                 staff["headers"])
        validate_error(resp, ApiErrorId.ERR_VOUCHER_EXPIRED)

    def test_unexpired_voucher_wrong_client_reports_mismatch(self, api):
        """PRD: "When a voucher is presented, four further checks follow in
        order: the voucher must not have reached its `expires_at` (at or after
        expiry the voucher flips to `EXPIRED` and the attempt fails with
        `ERR_VOUCHER_EXPIRED`); the voucher must still be `ISSUED`
        (`ERR_VOUCHER_NOT_REDEEMABLE`); the voucher's `client_id` must name the
        client being checked in (`ERR_VOUCHER_CLIENT_MISMATCH`); and the
        voucher's issuing partner must be `ACTIVE` (`ERR_PARTNER_SUSPENDED`)."

        Design: Difficulty/priority_pair_validation_conflict/voucher_expired_temporal_beats_client_mismatch_referential
        """
        staff = setup_sorting_staff()
        partner = create_partner("Agency B", 5)
        client_a = register_client("A", 2, None, staff["headers"])
        client_b = register_client("B", 2, None, staff["headers"])
        voucher = issue_voucher(partner, client_b["id"], bonus_items=2,
                                expires_at="2026-12-01T00:00:00Z")

        resp = api.checkin_visit(client_a["id"], {"voucher_id": voucher["id"]},
                                 staff["headers"])
        validate_error(resp, ApiErrorId.ERR_VOUCHER_CLIENT_MISMATCH)


class TestVoucherClientMismatch:
    def test_voucher_client_mismatch_rejected(self, api):
        """PRD: "the voucher's `client_id` must name the client being checked in
        (`ERR_VOUCHER_CLIENT_MISMATCH`)"

        Design: Corner/validations/voucher_client_mismatch_rejected
        """
        staff = setup_sorting_staff()
        partner = create_partner("Agency M", 5)
        client_a = register_client("A", 2, None, staff["headers"])
        client_b = register_client("B", 2, None, staff["headers"])
        voucher = issue_voucher(partner, client_b["id"], bonus_items=2,
                                expires_at="2026-12-01T00:00:00Z")

        resp = api.checkin_visit(client_a["id"], {"voucher_id": voucher["id"]},
                                 staff["headers"])
        validate_error(resp, ApiErrorId.ERR_VOUCHER_CLIENT_MISMATCH)


class TestPartnerSuspension:
    def test_voucher_issue_partner_suspended_rejected(self, api):
        """PRD: "Suspension blocks all new voucher issuance under that partner"
        PRD: "Issuance enforces its checks in order: the named client must be
        `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`), the partner — the resource under
        which the voucher is created — must be `ACTIVE`
        (`ERR_PARTNER_SUSPENDED`), and the monthly quota must have room
        (`ERR_VOUCHER_QUOTA_EXHAUSTED`)."

        Design: Corner/validations/voucher_issue_partner_suspended_rejected
        """
        partner = create_partner("Agency S", 5)
        client = register_client("C", 2)
        validate_success(api.suspend_referral_partner(partner["id"], ADMIN), 200)

        resp = api.issue_voucher(
            partner["id"],
            {"client_id": client["id"], "bonus_items": 1,
             "expires_at": "2026-12-01T00:00:00Z"},
            make_referral_partner_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_PARTNER_SUSPENDED)


class TestVoucherListing:
    def test_vouchers_filtered_by_client_reverse_fk(self, api):
        """PRD: "Vouchers can be listed with `partner_id`, `client_id`, `status`,
        or `code` filters, and the visits that redeemed a given voucher — at most
        one — can be listed from the voucher."

        Design: Corner/endpoints/vouchers_filtered_by_client_reverse_fk
        """
        partner = create_partner("Agency F", 5)
        client_c = register_client("C", 2)
        client_d = register_client("D", 2)
        issue_voucher(partner, client_c["id"], bonus_items=1)
        issue_voucher(partner, client_c["id"], bonus_items=1)
        issue_voucher(partner, client_d["id"], bonus_items=1)

        page, meta = validate_paginated(
            api.list_vouchers(ADMIN, params={"client_id": client_c["id"]}))
        assert meta["total_count"] == 2
        assert all(row["client_id"] == client_c["id"] for row in page)
