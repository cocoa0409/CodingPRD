"""Reconciliation: provisional vs final expectations, input-set filtering,
auto-fork, ledger-cascade status flip, duplicates, SoD lock, and the
cascaded version increment on the site."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_acknowledged_order,
    create_balanced_reconciliation,
    create_carrier,
    create_cash_ledger_entry_payload,
    create_order_shipment,
    create_reconciliation_payload,
    create_staffed_site,
    get_success_data,
    get_site,
    make_carrier_dispatcher_headers,
    set_clock,
    validate_error,
)

PROVISIONAL_CITE = (
    'PRD §3.8: "Opening freezes a provisional expectation: '
    "`provisional_expected_cents` is the opening balance plus the sum of the "
    "signed amounts of every ledger entry for that site and business date created "
    "at or before the reconciliation was opened — entries created later, even "
    "when backdated to the same value date, are excluded from this snapshot "
    'forever. In parallel, `final_expected_cents` is the opening balance plus the '
    "sum of all ledger entries for that site and date regardless of when they "
    "were created, and it refreshes on every matching ledger append. The two "
    'diverge by exactly the sum of late-arriving entries."'
)


class TestProvisionalVsFinal:
    def test_late_backdated_entry_diverges_provisional_from_final(self, api):
        f"""{PROVISIONAL_CITE}

        Design: Difficulty/dual_variant_calc/recon_provisional_vs_final_expected_with_late_entry
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"site_type": "CENTRAL", "opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        set_clock("2026-08-02T09:00:00Z")
        get_success_data(
            api.create_cash_ledger_entry(
                create_cash_ledger_entry_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    signed_amount_cents=1000000,
                    bucket="FIT",
                ),
                custodian,
            )
        )
        set_clock("2026-08-02T09:05:00Z")
        recon = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    opening_balance_cents=5000000,
                ),
                custodian,
            )
        )
        assert recon["provisional_expected_cents"] == 6000000
        assert recon["final_expected_cents"] == 6000000

        # Late entry backdated to the recon's business date, created after open.
        set_clock("2026-08-02T09:10:00Z")
        get_success_data(
            api.create_cash_ledger_entry(
                create_cash_ledger_entry_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    signed_amount_cents=-400000,
                    bucket="FIT",
                ),
                custodian,
            )
        )

        refreshed = get_success_data(api.get_reconciliation(recon["id"], custodian))
        assert refreshed["provisional_expected_cents"] == 6000000, (
            "the provisional snapshot must stay frozen at the open-time value"
        )
        assert refreshed["final_expected_cents"] == 5600000
        assert (
            refreshed["final_expected_cents"] - refreshed["provisional_expected_cents"]
            == -400000
        )

    def test_entry_created_before_open_enters_both_expectations(self, api):
        f"""{PROVISIONAL_CITE}

        Design: Difficulty/dual_variant_calc/recon_provisional_vs_final_expected_with_late_entry
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"site_type": "CENTRAL", "opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        set_clock("2026-08-02T09:00:00Z")
        get_success_data(
            api.create_cash_ledger_entry(
                create_cash_ledger_entry_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    signed_amount_cents=1000000,
                    bucket="FIT",
                ),
                custodian,
            )
        )
        set_clock("2026-08-02T09:05:00Z")
        recon = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    opening_balance_cents=5000000,
                ),
                custodian,
            )
        )
        # The +1,000,000 entry predates the open: both expectations absorb it.
        assert recon["provisional_expected_cents"] == 6000000
        assert recon["final_expected_cents"] == 6000000


class TestInputSetFiltering:
    def test_entries_on_other_business_dates_excluded(self, api):
        """PRD §3.8: "Opening freezes a provisional expectation:
        `provisional_expected_cents` is the opening balance plus the sum of the
        signed amounts of every ledger entry for that site and business date
        created at or before the reconciliation was opened — entries created
        later, even when backdated to the same value date, are excluded from this
        snapshot forever."

        Design: Corner/calculations/recon_input_set_excludes_other_business_dates
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={"site_type": "CENTRAL", "opening_fit_cents": 5000000},
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        set_clock("2026-08-02T09:00:00Z")
        for business_date, amount in (
            ("2026-08-01", 500000),
            ("2026-08-02", 300000),
            ("2026-08-03", 900000),
        ):
            get_success_data(
                api.create_cash_ledger_entry(
                    create_cash_ledger_entry_payload(
                        site_id=site_id,
                        business_date=business_date,
                        signed_amount_cents=amount,
                        bucket="FIT",
                    ),
                    custodian,
                )
            )
        recon = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    opening_balance_cents=1000000,
                ),
                custodian,
            )
        )
        # All three entries predate the open, but only the 08-02 entry matches
        # the recon's business date: 1,000,000 + 300,000 = 1,300,000.
        assert recon["final_expected_cents"] == 1300000
        assert recon["provisional_expected_cents"] == 1300000


class TestCountAutoFork:
    def test_count_within_tolerance_forks_balanced(self, api):
        """PRD §3.8: "Submitting the physical count — allowed only from `OPEN`,
        failing with `ERR_RECON_INVALID_STATE` (HTTP 409) otherwise — records
        `counted_on_hand_cents` and the counter's identity in
        `counted_by_staff_id`, computes `variance_cents` as the counted amount
        minus the final expected amount, and auto-forks: when the absolute
        variance is within 1000 cents the reconciliation moves `OPEN → COUNTED →
        BALANCED`; otherwise it moves `OPEN → COUNTED → VARIANCE_PENDING`."

        Design: Corner/state_machines/recon_count_auto_forks_balanced
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",), site_overrides={"opening_fit_cents": 5000000}
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]

        # No ledger entries on 2026-08-02: provisional equals final.
        recon = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    opening_balance_cents=5000000,
                ),
                custodian,
            )
        )
        counted = get_success_data(
            api.count_reconciliation(
                recon["id"], {"counted_on_hand_cents": 5000500}, custodian
            )
        )
        assert counted["status"] == "BALANCED"
        assert counted["variance_cents"] == 500
        assert counted["provisional_expected_cents"] == 5000000
        assert counted["final_expected_cents"] == 5000000


class TestVerifyCascadeFlipsRecon:
    def _setup_in_transit_with_balanced_recon(self, api):
        ctx = create_staffed_site(
            staff_roles=("custodian", "coordinator"),
            site_overrides={"site_type": "CENTRAL", "opening_fit_cents": 30000000},
        )
        site_id = ctx["site"]["id"]
        custodian = ctx["staff"]["custodian"]["headers"]
        coord = ctx["staff"]["coordinator"]["headers"]
        carrier = create_carrier()

        order = create_acknowledged_order(
            site_id, coord, direction="ORDER", business_date="2026-08-04"
        )
        # Recon for 2026-08-02 while the clock still sits at the 08-01 default:
        # the site's 30,000,000 opening entry is dated 08-01, so a 30,000,000
        # count against a 30,000,000 opening is BALANCED.
        recon = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    opening_balance_cents=30000000,
                ),
                custodian,
            )
        )
        counted = get_success_data(
            api.count_reconciliation(
                recon["id"], {"counted_on_hand_cents": 30000000}, custodian
            )
        )
        assert counted["status"] == "BALANCED"

        set_clock("2026-08-02T09:00:00Z")
        shipment = create_order_shipment(order["id"], carrier["id"], coord)
        get_success_data(api.load_cash_shipment(shipment["id"], coord))
        get_success_data(
            api.depart_cash_shipment(
                shipment["id"], make_carrier_dispatcher_headers(carrier["id"])
            )
        )
        return site_id, custodian, carrier, order, shipment, recon

    def test_verify_ledger_append_flips_balanced_to_variance_pending(self, api):
        """PRD §2.10: "Whenever a ledger entry is appended, the owning site's
        totals re-derive, its posture re-derives, and any matching reconciliation
        in `OPEN` or `COUNTED` status refreshes its final expected balance and
        variance — which may flip its status, as described in §3.8."
        PRD §3.4: "A count equal to the declared value moves `IN_TRANSIT →
        VERIFIED`, records `counted_value_cents`, credits the destination for an
        inbound shipment — `in_transit_inbound_cents` decreases by the declared
        value, `on_hand_fit_cents` increases by it, and a `SHIPMENT_IN` entry
        posts (a `FED_RECEIPT` when linked to an `ORDER` order) — sets a linked
        order's `settled_basis_cents` to the declared value as the booked basis,
        moves the linked order to `RECEIVED`, and cascades through site totals,
        posture, and reconciliation refresh."
        PRD §3.8: "This fork is not permanent. Because every matching ledger
        append refreshes the final expectation, a late entry can move the variance
        across the tolerance line in either direction — a `BALANCED`
        reconciliation flips to `VARIANCE_PENDING` or back, and a
        `VARIANCE_PENDING` one flips to `BALANCED`, as the sweep re-evaluates the
        current absolute variance against the 1000-cent tolerance."

        Design: Difficulty/transitive_cascade/shipment_verify_cascade_flips_reconciliation
        """
        site_id, custodian, carrier, order, shipment, recon = (
            self._setup_in_transit_with_balanced_recon(api)
        )
        get_success_data(
            api.verify_cash_shipment(
                shipment["id"],
                {"counted_value_cents": 2000000},
                make_carrier_dispatcher_headers(carrier["id"]),
            )
        )
        recon_after = get_success_data(api.get_reconciliation(recon["id"], custodian))
        assert recon_after["status"] == "VARIANCE_PENDING", (
            f"the cascade (not the verify call directly) must flip the recon, "
            f"got {recon_after['status']}"
        )
        assert recon_after["final_expected_cents"] == 32000000
        assert recon_after["variance_cents"] == -2000000
        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 32000000
        order_after = get_success_data(api.get_fed_order(order["id"], custodian))
        assert order_after["status"] == "RECEIVED"

    def test_late_backdated_manual_entry_flips_recon_back_within_tolerance(
        self, api
    ):
        """PRD §3.8: "This fork is not permanent. Because every matching ledger
        append refreshes the final expectation, a late entry can move the variance
        across the tolerance line in either direction — a `BALANCED`
        reconciliation flips to `VARIANCE_PENDING` or back, and a
        `VARIANCE_PENDING` one flips to `BALANCED`, as the sweep re-evaluates the
        current absolute variance against the 1000-cent tolerance."
        PRD §3.9: "The value date may be earlier than the current date — late
        events and backdated corrections are first-class — and this is precisely
        what the reconciliation machinery is built to absorb: the entry
        immediately re-derives the owning site's totals and posture, and any
        matching reconciliation in `OPEN` or `COUNTED` status refreshes its
        `final_expected_cents` and variance, potentially flipping between
        `BALANCED` and `VARIANCE_PENDING` as described above."

        Design: Difficulty/transitive_cascade/shipment_verify_cascade_flips_reconciliation
        """
        site_id, custodian, carrier, order, shipment, recon = (
            self._setup_in_transit_with_balanced_recon(api)
        )
        # Post a backdated +2,000,000 manual entry on the recon's date: the
        # physical count of 30,000,000 then matches the new expectation and the
        # recon stays BALANCED even after the FED_RECEIPT lands.
        get_success_data(
            api.create_cash_ledger_entry(
                create_cash_ledger_entry_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    signed_amount_cents=2000000,
                    bucket="FIT",
                ),
                custodian,
            )
        )
        recon_mid = get_success_data(api.get_reconciliation(recon["id"], custodian))
        assert recon_mid["final_expected_cents"] == 32000000
        assert recon_mid["status"] == "VARIANCE_PENDING", (
            f"the late entry alone must flip BALANCED → VARIANCE_PENDING, "
            f"got {recon_mid['status']}"
        )

        get_success_data(
            api.verify_cash_shipment(
                shipment["id"],
                {"counted_value_cents": 2000000},
                make_carrier_dispatcher_headers(carrier["id"]),
            )
        )
        # The FED_RECEIPT adds another +2,000,000 to the final expectation —
        # variance moves to -4,000,000, still VARIANCE_PENDING.
        recon_after = get_success_data(api.get_reconciliation(recon["id"], custodian))
        assert recon_after["status"] == "VARIANCE_PENDING"
        assert recon_after["final_expected_cents"] == 34000000
        assert recon_after["variance_cents"] == -4000000


class TestDuplicateRecon:
    def test_second_create_for_same_site_and_date_rejected(self, api):
        """PRD §3.8: "A `VaultCustodian` opens a `Reconciliation` for a `site_id`
        and `business_date` with a declared `opening_balance_cents`; only one
        reconciliation may exist per site and date, and a duplicate is rejected
        with `ERR_DUPLICATE_RECONCILIATION` (HTTP 409)."

        Design: Corner/validations/duplicate_reconciliation_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",), site_overrides={"opening_fit_cents": 5000000}
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]
        payload = create_reconciliation_payload(
            site_id=site_id, business_date="2026-08-02", opening_balance_cents=5000000
        )
        get_success_data(api.create_reconciliation(payload, custodian))
        resp = api.create_reconciliation(payload, custodian)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECONCILIATION)


class TestReconLockSoD:
    def test_counter_cannot_lock_peer_locks(self, api):
        """PRD §3.8: "Closure happens through locking: a reconciliation in
        `BALANCED` or `APPROVED` may be locked by a `VaultCustodian` or
        `CashOperationsAdmin`, moving it to the terminal `LOCKED` state — but
        under segregation of duties the locker must not be the identity that
        submitted the count, failing with `ERR_SOD_VIOLATION` (HTTP 403)
        otherwise."
        PRD §3.8: "Locking records `approved_by_staff_id` when it closes a
        balanced reconciliation, and increments the version."

        Design: Corner/validations/sod_recon_lock_by_counter_rejected_then_peer_locks
        """
        ctx = create_staffed_site(
            staff_roles=("custodian", "peer"),
            site_overrides={"opening_fit_cents": 5000000},
        )
        from test_helpers import make_custodian_headers

        u1 = ctx["staff"]["custodian"]
        u2 = ctx["staff"]["peer"]  # second custodian of the same site
        peer_headers = make_custodian_headers(u2["id"])
        site_id = ctx["site"]["id"]

        recon = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_id,
                    business_date="2026-08-02",
                    opening_balance_cents=5000000,
                ),
                u1["headers"],
            )
        )
        get_success_data(
            api.count_reconciliation(
                recon["id"], {"counted_on_hand_cents": 5000000}, u1["headers"]
            )
        )

        resp = api.lock_reconciliation(recon["id"], u1["headers"])
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        locked = get_success_data(api.lock_reconciliation(recon["id"], peer_headers))
        assert locked["status"] == "LOCKED"
        assert locked["approved_by_staff_id"] == u2["id"]


class TestCascadedVersionIncrement:
    def test_ledger_append_bumps_site_version_and_balance(self, api):
        """PRD §2.5: "Resources created with full audit fields — `VaultSite`,
        `StaffMember`, `Carrier`, `AtmMachine`, `SeasonalWindow`, `FedOrder`,
        `CashShipment`, `FitnessBatch`, `CounterfeitCase`, `Reconciliation`, and
        `AtmForecast` — additionally carry `created_at` (ISO 8601 UTC with three
        fractional digits), `updated_at` (same format, refreshed on every
        mutation), and `version`, an integer starting at 1 that increments by 1
        on every mutation of the resource, including system-driven mutations."
        PRD §2.10: "Whenever a ledger entry is appended, the owning site's totals
        re-derive, its posture re-derives, and any matching reconciliation in
        `OPEN` or `COUNTED` status refreshes its final expected balance and
        variance — which may flip its status, as described in §3.8."

        Design: Corner/cross_cutting_layers/version_increments_on_cascaded_mutation
        """
        ctx = create_staffed_site(
            staff_roles=("custodian",), site_overrides={"opening_fit_cents": 5000000}
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site = ctx["site"]
        assert site["version"] == 1

        get_success_data(
            api.create_cash_ledger_entry(
                create_cash_ledger_entry_payload(
                    site_id=site["id"],
                    business_date="2026-08-01",
                    signed_amount_cents=1000,
                    bucket="FIT",
                ),
                custodian,
            )
        )
        after = get_site(site["id"])
        assert after["version"] == 2, (
            f"the ledger-driven recompute is a site mutation: version 1 → 2, "
            f"got {after['version']}"
        )
        assert after["on_hand_fit_cents"] == 5001000
        assert after["updated_at"] >= site["updated_at"]
