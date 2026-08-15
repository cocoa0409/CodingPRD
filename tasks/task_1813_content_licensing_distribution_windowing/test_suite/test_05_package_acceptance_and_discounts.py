"""Package acceptance: license/notice creation, the volume-discount pinned
evaluation order, the offer-expiry instant boundary, and the slot-withdraw
blocked-line cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_package,
    add_slot,
    advance_clock,
    assert_license_agreement,
    assert_same_instant,
    create_and_offer_package,
    get_license,
    get_package,
    get_success_data,
    list_notices_for_license,
    make_line,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]

LINE_START = "2026-09-01T00:00:00Z"
LINE_END = "2026-12-01T00:00:00Z"


def _accepted_line(package_data, slot_id):
    for line in package_data["lines"]:
        if line["slot_id"] == slot_id:
            return line
    raise AssertionError(f"no line for slot {slot_id} in package {package_data['id']}")


class TestAcceptanceCreatesLicensesAndNotices:
    def test_accept_creates_licenses_and_notices_atomically(self, api):
        """PRD §3.5: "One `LicenseAgreement` is created per accepted line, in `EXECUTED` status, with terms copied from the line and `package_id` set to the originating package. Accepted lines move to `LICENSED` with `created_license_id` set; non-accepted lines move to `NOT_SELECTED`. One `TakedownNotice` is auto-created per created license, `SCHEDULED` at that license's `license_end`."
        PRD §3.5: "a gross of at least 5,000,000 cents earns 15 percent; at least 2,000,000 cents earns 10 percent; at least 500,000 cents earns 5 percent; anything below earns 0."
        PRD §3.10: "Every license creation auto-creates one notice with `notice_status` `SCHEDULED` and `scheduled_for` equal to the license's current `license_end`."

        Design: Corner/endpoints/accept_creates_licenses_and_notices_atomically
        """
        workspace = setup_catalog()
        s1 = add_slot(workspace, window_type="SVOD")
        s2 = add_slot(workspace, window_type="AVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [
                make_line(s1["id"], flat_fee_cents=100000),
                make_line(s2["id"], flat_fee_cents=50000),
            ],
        )

        accepted = accept_package(
            package["id"], [s1["id"], s2["id"]], workspace["buyer_headers"],
        )
        assert accepted["package_status"] == "ACCEPTED"
        assert accepted["discount_cents"] == 0, (
            "guaranteed total 150000 is below the 500000-cent tier floor"
        )

        for slot, fee in ((s1, 100000), (s2, 50000)):
            line = _accepted_line(accepted, slot["id"])
            assert line["line_status"] == "LICENSED"
            assert line["created_license_id"]
            license_agreement = get_license(line["created_license_id"])
            assert_license_agreement(license_agreement)
            assert license_agreement["license_status"] == "EXECUTED"
            assert license_agreement["package_id"] == package["id"]
            assert license_agreement["allocated_fee_cents"] == fee

            notices = list_notices_for_license(license_agreement["id"])
            assert len(notices) == 1, "exactly one notice per created license"
            assert notices[0]["notice_status"] == "SCHEDULED"
            assert_same_instant(
                notices[0]["scheduled_for"], LINE_END, "notice scheduled_for"
            )


class TestVolumeDiscount:
    def test_discount_tier_boundary_exactly_2000000_cents(self, api):
        """PRD §3.5: "The `discount_pct` is tiered on that gross, with each boundary inclusive: a gross of at least 5,000,000 cents earns 15 percent; at least 2,000,000 cents earns 10 percent; at least 500,000 cents earns 5 percent; anything below earns 0."
        PRD §3.5: "`discount_cents` is the gross multiplied by the discount percentage and divided by 100, rounded half up to integer cents."
        PRD §3.5: "`net_total_cents` is the gross minus `discount_cents`."

        Design: Corner/calculations/discount_tier_boundary_exactly_2000000_cents
        """
        workspace = setup_catalog()
        s1 = add_slot(workspace, window_type="SVOD")
        s2 = add_slot(workspace, window_type="AVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [
                make_line(s1["id"], flat_fee_cents=1500000),
                make_line(
                    s2["id"], fee_model="MINIMUM_GUARANTEE",
                    minimum_guarantee_cents=500000, revenue_share_pct=40,
                ),
            ],
        )

        accepted = accept_package(
            package["id"], [s1["id"], s2["id"]], workspace["buyer_headers"],
        )
        assert accepted["package_status"] == "ACCEPTED"
        assert accepted["discount_pct"] == 10, (
            "gross 2000000 hits the inclusive 2,000,000-cent boundary -> 10 percent"
        )
        assert accepted["discount_cents"] == 200000
        assert accepted["net_total_cents"] == 1800000

        lic1 = get_license(_accepted_line(accepted, s1["id"])["created_license_id"])
        lic2 = get_license(_accepted_line(accepted, s2["id"])["created_license_id"])
        assert lic1["allocated_fee_cents"] == 1350000
        assert lic2["allocated_fee_cents"] == 450000

    def test_discount_tier_keyed_on_gross_not_net(self, api):
        """PRD §3.5: "The **volume discount** runs over the accepted lines only, in a pinned evaluation order that keys the tier on the gross guaranteed total, never on the net:"
        PRD §3.5: "The gross is the sum of guaranteed value over accepted lines — `flat_fee_cents` for a `FLAT_FEE` line, `minimum_guarantee_cents` for a `MINIMUM_GUARANTEE` line, zero for a `REVENUE_SHARE` line."

        Design: Difficulty/combinatorial_formula/package_discount_evaluation_order
        """
        workspace = setup_catalog()
        s1 = add_slot(workspace, window_type="SVOD")
        s2 = add_slot(workspace, window_type="AVOD")
        s3 = add_slot(workspace, window_type="TVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [
                make_line(s1["id"], flat_fee_cents=1500000),
                make_line(
                    s2["id"], fee_model="MINIMUM_GUARANTEE",
                    minimum_guarantee_cents=600000, revenue_share_pct=40,
                ),
                make_line(
                    s3["id"], fee_model="REVENUE_SHARE", revenue_share_pct=25,
                ),
            ],
        )

        accepted = accept_package(
            package["id"], [s1["id"], s2["id"], s3["id"]], workspace["buyer_headers"],
        )
        assert accepted["package_status"] == "ACCEPTED"
        assert accepted["discount_pct"] == 10, (
            "tier keyed on GROSS 2100000 (>= 2000000); keying on the 1890000 net "
            "would wrongly select 5 percent"
        )
        assert accepted["discount_cents"] == 210000
        assert accepted["net_total_cents"] == 1890000

    def test_discount_allocation_pro_rata_per_line(self, api):
        """PRD §3.5: "The discount is allocated across accepted lines: each line's share is `discount_cents` multiplied by the line's guaranteed value and divided by the gross, rounded half up to integer cents; lines with zero guaranteed value receive zero discount."
        PRD §3.5: "Each accepted line's `allocated_fee_cents` is its guaranteed value minus its per-line discount share (minus the remainder for the chosen line)."

        Design: Difficulty/combinatorial_formula/package_discount_evaluation_order
        """
        workspace = setup_catalog()
        s1 = add_slot(workspace, window_type="SVOD")
        s2 = add_slot(workspace, window_type="AVOD")
        s3 = add_slot(workspace, window_type="TVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [
                make_line(s1["id"], flat_fee_cents=1500000),
                make_line(
                    s2["id"], fee_model="MINIMUM_GUARANTEE",
                    minimum_guarantee_cents=600000, revenue_share_pct=40,
                ),
                make_line(
                    s3["id"], fee_model="REVENUE_SHARE", revenue_share_pct=25,
                ),
            ],
        )

        accepted = accept_package(
            package["id"], [s1["id"], s2["id"], s3["id"]], workspace["buyer_headers"],
        )
        lic1 = get_license(_accepted_line(accepted, s1["id"])["created_license_id"])
        lic2 = get_license(_accepted_line(accepted, s2["id"])["created_license_id"])
        lic3 = get_license(_accepted_line(accepted, s3["id"])["created_license_id"])
        assert lic1["allocated_fee_cents"] == 1350000
        assert lic2["allocated_fee_cents"] == 540000
        assert lic3["allocated_fee_cents"] == 0, (
            "a REVENUE_SHARE line guarantees nothing and receives zero discount"
        )
        for lic in (lic1, lic2, lic3):
            assert lic["license_status"] == "EXECUTED"
            assert lic["package_id"] == package["id"]


class TestOfferExpiryInstantBoundary:
    def test_accept_one_second_before_offer_expiry_succeeds(self, api):
        """PRD §2.5: "The expiry rule is uniform: a resource expires when the logical clock is greater than or equal to its end instant — intervals are half-open, so at exactly the end instant the resource is expired."

        Design: Difficulty/boundary_precision_check/offer_expiry_exact_instant_boundary
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [make_line(
                slot["id"], license_start="2026-09-15T00:00:00Z",
                license_end="2026-12-15T00:00:00Z", flat_fee_cents=10000,
            )],
            offer_expires_at="2026-09-01T00:00:00Z",
        )

        advance_clock("2026-08-31T23:59:59Z")
        accepted = accept_package(
            package["id"], [slot["id"]], workspace["buyer_headers"],
        )
        assert accepted["package_status"] == "ACCEPTED", (
            "one second before offer_expires_at the package is still OFFERED"
        )

    def test_accept_at_exact_offer_expiry_rejected(self, api):
        """PRD §2.5: "Every `AvailPackage` in `OFFERED` whose `offer_expires_at` is at or before the new clock value moves to `EXPIRED`, and all of its non-`LICENSED` lines move to `NOT_SELECTED`."
        PRD §3.5: "The package must be `OFFERED`, otherwise `ERR_PACKAGE_NOT_OFFERED` (409); this single check also rejects packages that have already expired or been withdrawn."

        Design: Difficulty/boundary_precision_check/offer_expiry_exact_instant_boundary
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [make_line(
                slot["id"], license_start="2026-09-15T00:00:00Z",
                license_end="2026-12-15T00:00:00Z", flat_fee_cents=10000,
            )],
            offer_expires_at="2026-09-01T00:00:00Z",
        )

        advance_clock("2026-09-01T00:00:00Z")
        resp = api.accept_package(
            package["id"], [slot["id"]], workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_OFFERED, 409)
        assert get_package(package["id"])["package_status"] == "EXPIRED", (
            "at exactly offer_expires_at the sweep has already expired the package"
        )


class TestSlotWithdrawCascade:
    def test_withdraw_expires_single_line_package(self, api):
        """PRD §3.4: "The same cascade fires on slot withdrawal and on slot expiry: offered lines on the affected slot become `BLOCKED`, all-blocked offered packages expire, and their non-`LICENSED` lines become `NOT_SELECTED`."
        PRD §3.2: "Withdrawal moves the slot to `WITHDRAWN` and fires the blocked-line cascade described in §3.4."

        Design: Difficulty/transitive_cascade/slot_withdraw_block_package_expire_chain
        """
        workspace = setup_catalog()
        s1 = add_slot(workspace, window_type="SVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [make_line(s1["id"], flat_fee_cents=100000)],
        )

        withdrawn = validate_success(api.withdraw_rights_slot(s1["id"], RM), 200)
        assert withdrawn["slot_status"] == "WITHDRAWN"

        after = get_package(package["id"])
        assert after["package_status"] == "EXPIRED", (
            "an OFFERED package whose every line is BLOCKED has nothing sellable left"
        )
        assert _accepted_line(after, s1["id"])["line_status"] == "NOT_SELECTED"

    def test_withdraw_blocks_only_lines_on_the_slot(self, api):
        """PRD §3.4: "Then hop 1: every line referencing that slot inside any package currently `OFFERED` moves to `BLOCKED` — except lines on the very package being accepted, which move to `LICENSED` instead. Hop 2: an `OFFERED` package whose every line is now `BLOCKED` has nothing sellable left, so the package itself moves to `EXPIRED`."

        Design: Difficulty/transitive_cascade/slot_withdraw_block_package_expire_chain
        """
        workspace = setup_catalog()
        s1 = add_slot(workspace, window_type="SVOD")
        s2 = add_slot(workspace, window_type="AVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [
                make_line(s1["id"], flat_fee_cents=100000),
                make_line(s2["id"], flat_fee_cents=80000),
            ],
        )

        get_success_data(api.withdraw_rights_slot(s1["id"], RM))

        after = get_package(package["id"])
        assert after["package_status"] == "OFFERED", (
            "the cascade stops at hop 1 while a sibling line is still sellable"
        )
        assert _accepted_line(after, s1["id"])["line_status"] == "BLOCKED"
        assert _accepted_line(after, s2["id"])["line_status"] == "OFFERED"
