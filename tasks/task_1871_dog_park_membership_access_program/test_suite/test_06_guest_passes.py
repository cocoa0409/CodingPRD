"""Guest pass purchase pricing, the monthly allotment, void/redemption
accounting, and pass expiry."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    check_in_guest,
    create_park_area,
    get_member,
    make_member_headers,
    purchase_guest_pass_payload,
    purchase_pass,
    run_nightly,
    set_clock,
    setup_active_member,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["park_admin_headers"]


class TestGuestPassPurchase:
    def test_guest_pass_weekday_and_weekend_fee(self, api):
        """PRD §3.6: "A `valid_on` falling on a Saturday or Sunday — judged in
        UTC — prices at the weekday base of 1500 cents multiplied by
        one-and-a-half and rounded half-up: 2250 cents. A `valid_on` falling
        Monday through Friday prices at the flat 1500 cents. The result is
        recorded on the pass as `fee_cents`."
        PRD §3.6: "The pass is created `ISSUED`."

        Design: Corner/entities/guest_pass_purchase_weekday_and_weekend_fee
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Spon Sor",
                                     email="sponsor@x.com")
        weekday = purchase_pass(bundle["member"], guest_dog_size_class="SMALL",
                                valid_on="2026-08-03")  # Monday
        weekend = purchase_pass(bundle["member"], guest_dog_size_class="SMALL",
                                valid_on="2026-08-08")  # Saturday
        assert weekday["fee_cents"] == 1500
        assert weekend["fee_cents"] == 2250
        assert weekday["status"] == "ISSUED"
        assert weekend["status"] == "ISSUED"

    def test_third_guest_pass_rejected_at_monthly_limit(self, api):
        """PRD §3.6: "A purchase attempted while the count stands at two is
        rejected with `ERR_GUEST_PASS_MONTHLY_LIMIT`; a count of one still
        admits."

        Design: Corner/validations/third_guest_pass_rejected_at_monthly_limit
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Spon Sor",
                                     email="sponsor2@x.com")
        purchase_pass(bundle["member"], valid_on="2026-08-03")
        purchase_pass(bundle["member"], valid_on="2026-08-04")
        assert get_member(bundle["member"]["id"])[
            "guest_passes_used_this_month"] == 2

        resp = api.purchase_guest_pass(
            purchase_guest_pass_payload(guest_dog_size_class="SMALL",
                                        valid_on="2026-08-05"),
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GUEST_PASS_MONTHLY_LIMIT)


class TestPurchaseVoidConservation:
    def test_guest_pass_purchase_void_conservation(self, api):
        """PRD §3.6: "The usage figure, exposed as
        `guest_passes_used_this_month`, counts the sponsor's passes created
        within the current calendar month of the logical clock whose status is
        `ISSUED`, `REDEEMED`, or `EXPIRED` — `VOID` passes are excluded, so
        voiding genuinely refunds the allotment."
        PRD §3.6: "An administrator may void a pass — `ISSUED → VOID` — but
        only while it remains `ISSUED`; attempting to void a `REDEEMED`,
        `EXPIRED`, or already-`VOID` pass is rejected with
        `ERR_GUEST_PASS_NOT_VOIDABLE`, and a successful void recomputes the
        sponsor's monthly usage with the voided pass excluded."

        Design: Difficulty/compensating_invariant/guest_pass_purchase_void_conservation
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Spon Sor",
                                     email="sponsor3@x.com",
                                     set_clock_first=False)
        member = bundle["member"]

        p1 = purchase_pass(member, valid_on="2026-08-03")
        p2 = purchase_pass(member, valid_on="2026-08-04")
        assert get_member(member["id"])["guest_passes_used_this_month"] == 2

        validate_success(api.void_guest_pass(p1["id"], ADMIN))
        assert get_member(member["id"])["guest_passes_used_this_month"] == 1, (
            "voiding an ISSUED pass refunds the allotment"
        )

        set_clock("2026-08-04T10:00:00Z")
        guest_visit = check_in_guest(member, p2, area)
        assert guest_visit["guest_pass_id"] == p2["id"]
        assert validate_success(api.get_guest_pass(p2["id"], ADMIN))[
            "status"] == "REDEEMED"

        p3 = purchase_pass(member, valid_on="2026-08-05")
        resp = api.void_guest_pass(p2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GUEST_PASS_NOT_VOIDABLE)

        final = get_member(member["id"])["guest_passes_used_this_month"]
        assert final == 2, (
            "REDEEMED p2 and ISSUED p3 still count; VOID p1 stays excluded"
        )
        assert p3["status"] == "ISSUED"

    def test_void_refunds_allotment_for_repurchase(self, api):
        """PRD §3.6: "A purchase attempted while the count stands at two is
        rejected with `ERR_GUEST_PASS_MONTHLY_LIMIT`; a count of one still
        admits."
        PRD §3.6: "The usage figure, exposed as
        `guest_passes_used_this_month`, counts the sponsor's passes created
        within the current calendar month of the logical clock whose status is
        `ISSUED`, `REDEEMED`, or `EXPIRED` — `VOID` passes are excluded, so
        voiding genuinely refunds the allotment."

        Design: Difficulty/compensating_invariant/guest_pass_purchase_void_conservation
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Spon Sor",
                                     email="sponsor4@x.com")
        member = bundle["member"]
        p1 = purchase_pass(member, valid_on="2026-08-03")
        purchase_pass(member, valid_on="2026-08-04")

        blocked = api.purchase_guest_pass(
            purchase_guest_pass_payload(valid_on="2026-08-05"),
            bundle["member_headers"])
        validate_error(blocked, ApiErrorId.ERR_GUEST_PASS_MONTHLY_LIMIT)

        validate_success(api.void_guest_pass(p1["id"], ADMIN))
        assert get_member(member["id"])["guest_passes_used_this_month"] == 1

        p3 = purchase_pass(member, valid_on="2026-08-05")
        assert p3["status"] == "ISSUED", "a count of one still admits"
        assert get_member(member["id"])["guest_passes_used_this_month"] == 2


class TestGuestPassListing:
    def test_guest_pass_list_filter_by_status(self, api):
        """PRD §3.6: "Members list and read only their own passes — a list's
        `sponsor_member_id` filter must equal the caller or is auto-scoped to
        it — while stewards and administrators see all passes, with optional
        `status` and `valid_on` filters."

        Design: Corner/endpoints/guest_pass_list_filter_by_status
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Spon Sor",
                                     email="sponsor5@x.com")
        member = bundle["member"]
        p1 = purchase_pass(member, valid_on="2026-08-03")
        p2 = purchase_pass(member, valid_on="2026-08-04")
        validate_success(api.void_guest_pass(p1["id"], ADMIN))

        data, meta = validate_paginated(api.list_guest_passes(
            bundle["member_headers"],
            params={"sponsor_member_id": member["id"], "status": "ISSUED"},
        ))
        assert meta["total_count"] == 1
        assert [p["id"] for p in data] == [p2["id"]], (
            "the VOID pass is excluded by the status filter"
        )


class TestGuestPassRedemptionAndExpiry:
    def test_redeem_pass_wrong_date_rejected(self, api):
        """PRD §3.5: "For a guest visit, the pass must be `ISSUED` and its
        `valid_on` must equal the current logical date — any other status or
        date is `ERR_GUEST_PASS_NOT_REDEEMABLE` — and redemption flips the pass
        `ISSUED → REDEEMED` within the same request."

        Design: Corner/validations/redeem_pass_wrong_date_rejected
        """
        set_clock("2026-08-04T10:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Spon Sor",
                                     email="sponsor6@x.com",
                                     set_clock_first=False)
        guest_pass = purchase_pass(bundle["member"], valid_on="2026-08-05")

        resp = api.check_in(
            {"area_id": area["id"], "guest_pass_id": guest_pass["id"]},
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GUEST_PASS_NOT_REDEEMABLE)

        after = validate_success(api.get_guest_pass(guest_pass["id"], ADMIN))
        assert after["status"] == "ISSUED", (
            "the rejected redemption never consumes the pass"
        )

    def test_nightly_run_expires_guest_pass(self, api):
        """PRD §3.8: "3. Expire `ISSUED` guest passes whose `valid_on` is
        before the run's date, recomputing each sponsor's monthly usage with
        the expired passes still counting."
        PRD §3.6: "The nightly run expires any pass whose `valid_on` has fallen
        before the run's date, `ISSUED → EXPIRED`, and an expired pass still
        counts against its purchase month's allotment."

        Design: Corner/state_machines/nightly_run_expires_guest_pass
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Spon Sor",
                                     email="sponsor7@x.com")
        member = bundle["member"]
        guest_pass = purchase_pass(member, valid_on="2026-08-03")

        set_clock("2026-08-04T00:00:00Z")
        summary = run_nightly()
        assert summary["guest_passes_expired"] == 1

        after = validate_success(api.get_guest_pass(guest_pass["id"], ADMIN))
        assert after["status"] == "EXPIRED"
        assert get_member(member["id"])["guest_passes_used_this_month"] == 1, (
            "EXPIRED still counts against the purchase month's allotment"
        )


class TestGuestPassVoidRbac:
    def test_member_cannot_void_guest_pass(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.6: "An administrator may void a pass — `ISSUED → VOID` — but
        only while it remains `ISSUED`"

        Design: Corner/rbac/member_cannot_void_guest_pass
        """
        bundle = setup_active_member(clock="2026-08-01T00:00:00Z", num_dogs=1,
                                     full_name="Spon Sor",
                                     email="sponsor8@x.com")
        guest_pass = purchase_pass(bundle["member"], valid_on="2026-08-03")

        resp = api.void_guest_pass(guest_pass["id"], bundle["member_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        after = validate_success(api.get_guest_pass(guest_pass["id"], ADMIN))
        assert after["status"] == "ISSUED"

    def test_void_unknown_pass_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_guest_pass_not_found
        """
        resp = api.void_guest_pass(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_GUEST_PASS_NOT_FOUND)
