"""Equipment warranty: provisional vs final labor credit variants, the
loop-count-guarded MORE_INFO cycle, center-status gating at approval, serial
uniqueness among non-REJECTED claims, and authorized-center routing."""
from test_helpers import (
    ApiErrorId,
    MGR,
    make_account,
    make_account_headers,
    make_claim,
    make_claim_under_review,
    make_product,
    make_service_center,
    validate_error,
    validate_success,
)


def _claim_setup(api, labor_rate_cents=15000, account_number="SVC-1"):
    """Account + EQUIPMENT product + one ACTIVE center carrying AquaFlow."""
    account = make_account(api, account_number=account_number, account_type="SERVICE_CO")
    product = make_product(
        api, sku=f"PUMP-{account_number}", product_family="EQUIPMENT",
        base_price_cents=500000,
    )
    center = make_service_center(
        api, center_name="SW Pump Works", region_code="SW",
        authorized_brands=["AquaFlow"], labor_rate_cents=labor_rate_cents,
    )
    return account, product, center


class TestProvisionalVsFinalCredit:
    def test_warranty_provisional_credit_at_submit(self, api):
        """PRD §3.8: "Submission also books a provisional credit: a flat two-hour labor estimate at the assigned center's hourly rate, stored as `provisional_credit_cents`, with the claim entering `SUBMITTED`."

        Design: Difficulty/dual_variant_calc/warranty_provisional_vs_final_credit
        """
        account, product, center = _claim_setup(api, labor_rate_cents=15000,
                                                   account_number="SVC-200")
        claim = make_claim(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-9001", brand="AquaFlow", purchase_date="2026-03-15",
            failure_description="impeller seized",
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["assigned_center_id"] == center["id"]
        # flat 2 hours x 15,000c/hr
        assert claim["provisional_credit_cents"] == 30000, (
            f"provisional is the flat two-hour estimate at the center rate: {claim}"
        )

    def test_warranty_final_credit_at_resolve(self, api):
        """PRD §3.8: "Resolution requires `APPROVED` (`ERR_CLAIM_NOT_APPROVED`, HTTP 409) and a supplied `actual_labor_hours` greater than zero (`ERR_INVALID_REQUEST`); it computes the final credit as the actual hours times the assigned center's hourly rate, rounded half up to whole cents, then capped at six hours at that rate — so the payable amount never exceeds a six-hour job."
        PRD §3.8: "The provisional figure stays on record, and `final_credit_cents` minus `provisional_credit_cents` is the observable payable delta, which may be negative when the flat estimate overshot — a clawback."

        Design: Difficulty/dual_variant_calc/warranty_provisional_vs_final_credit
        """
        account, product, center = _claim_setup(api, labor_rate_cents=15000,
                                                   account_number="SVC-201")
        claim = make_claim_under_review(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-9002",
        )
        validate_success(api.approve_claim(claim["id"], MGR), 200)
        resolved = validate_success(
            api.resolve_claim(claim["id"], {"actual_labor_hours": 4.5}, MGR), 200
        )
        # 4.5h x 15,000c = 67,500c — under the six-hour cap of 90,000c.
        assert resolved["final_credit_cents"] == 67500, (
            f"final credit is actual hours x rate, half-up, capped: {resolved}"
        )
        assert resolved["provisional_credit_cents"] == 30000, (
            f"the provisional figure stays on record: {resolved}"
        )
        delta = resolved["final_credit_cents"] - resolved["provisional_credit_cents"]
        assert delta == 37500, (
            f"the two variants differ; payable delta is 37,500c: {resolved}"
        )

    def test_warranty_final_credit_capped_at_six_hours(self, api):
        """PRD §3.8: "Resolution requires `APPROVED` (`ERR_CLAIM_NOT_APPROVED`, HTTP 409) and a supplied `actual_labor_hours` greater than zero (`ERR_INVALID_REQUEST`); it computes the final credit as the actual hours times the assigned center's hourly rate, rounded half up to whole cents, then capped at six hours at that rate — so the payable amount never exceeds a six-hour job."

        Design: Difficulty/dual_variant_calc/warranty_provisional_vs_final_credit
        """
        account, product, center = _claim_setup(api, labor_rate_cents=15000,
                                                   account_number="SVC-202")
        claim = make_claim_under_review(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-9003",
        )
        validate_success(api.approve_claim(claim["id"], MGR), 200)
        resolved = validate_success(
            api.resolve_claim(claim["id"], {"actual_labor_hours": 8}, MGR), 200
        )
        # 8h x 15,000c = 120,000c raw, capped at 6h x 15,000c = 90,000c.
        assert resolved["final_credit_cents"] == 90000, (
            f"the payable amount never exceeds a six-hour job: {resolved}"
        )


class TestMoreInfoCycle:
    def test_warranty_more_info_cycle_loop(self, api):
        """PRD §3.8: "The loop may run at most three times: when `info_cycles` has already reached 3, a further supply attempt is rejected with `ERR_CLAIM_INFO_CYCLE_EXHAUSTED` (HTTP 409), and the claim must then be settled by rejection."

        Design: Difficulty/non_linear_state_machine/warranty_more_info_cycle_loop
        """
        account, product, _center = _claim_setup(api, labor_rate_cents=12000,
                                                    account_number="SVC-401")
        claim = make_claim_under_review(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-777", failure_description="leak at seal",
        )
        owner = make_account_headers(account["id"])
        for cycle in (1, 2, 3):
            validate_success(api.request_claim_info(claim["id"], MGR), 200)
            supplied = validate_success(
                api.supply_claim_info(claim["id"], {"info_note": f"photo {cycle}"}, owner),
                200,
            )
            assert supplied["status"] == "UNDER_REVIEW"
            assert supplied["info_cycles"] == cycle

        # The 4th loop may begin (claim is UNDER_REVIEW) but the 4th supply
        # attempt is rejected: the cycle count is exhausted.
        validate_success(api.request_claim_info(claim["id"], MGR), 200)
        resp = api.supply_claim_info(claim["id"], {"info_note": "photo 4"}, owner)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INFO_CYCLE_EXHAUSTED)
        claim_after = validate_success(api.get_warranty_claim(claim["id"], MGR))
        assert claim_after["status"] == "MORE_INFO"
        assert claim_after["info_cycles"] == 3, (
            f"loop count enforced at 3: {claim_after}"
        )

    def test_more_info_loop_increments_cycles_and_rejoins_review(self, api):
        """PRD §3.8: "From there the manager may request more information — moving the claim to `MORE_INFO` — and the owning account then supplies it via an `info_note`: supply requires the claim in `MORE_INFO` (`ERR_CLAIM_NOT_MORE_INFO`, HTTP 409), requires the caller to own the claim (`ERR_NOT_CLAIM_OWNER`, HTTP 403), and increments the `info_cycles` counter."

        Design: Difficulty/non_linear_state_machine/warranty_more_info_cycle_loop
        """
        account, product, _center = _claim_setup(api, account_number="SVC-402")
        claim = make_claim_under_review(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-778",
        )
        owner = make_account_headers(account["id"])

        moved = validate_success(api.request_claim_info(claim["id"], MGR), 200)
        assert moved["status"] == "MORE_INFO"
        supplied = validate_success(
            api.supply_claim_info(claim["id"], {"info_note": "invoice copy"}, owner), 200
        )
        assert supplied["status"] == "UNDER_REVIEW", "the loop returns to UNDER_REVIEW"
        assert supplied["info_cycles"] == 1, "each completed loop increments the counter"

        validate_success(api.request_claim_info(claim["id"], MGR), 200)
        supplied = validate_success(
            api.supply_claim_info(claim["id"], {"info_note": "photo"}, owner), 200
        )
        assert supplied["info_cycles"] == 2
        assert supplied["status"] == "UNDER_REVIEW"


class TestCenterStatusGate:
    def test_claim_approve_gated_by_center_status(self, api):
        """PRD §3.8: "Approval additionally requires the assigned center to still be `ACTIVE` — a suspended center blocks approval with `ERR_CENTER_SUSPENDED` (HTTP 409) — and moves the claim to `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_by_center_status
        """
        account, product, center = _claim_setup(api, labor_rate_cents=11000,
                                                   account_number="SVC-801")
        claim = make_claim_under_review(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-555", failure_description="motor hum",
        )
        validate_success(
            api.patch_service_center(center["id"], {"status": "SUSPENDED"}, MGR), 200
        )
        resp = api.approve_claim(claim["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_CENTER_SUSPENDED)
        claim_after = validate_success(api.get_warranty_claim(claim["id"], MGR))
        assert claim_after["status"] == "UNDER_REVIEW", (
            f"blocked approval leaves the claim UNDER_REVIEW: {claim_after}"
        )

    def test_claim_approve_succeeds_once_center_active_again(self, api):
        """PRD §3.8: "Approval additionally requires the assigned center to still be `ACTIVE` — a suspended center blocks approval with `ERR_CENTER_SUSPENDED` (HTTP 409) — and moves the claim to `APPROVED`."
        PRD §3.8: "Service centers are registered by a `BranchManager` with a `center_name`, a `region_code` such as `SW`, `TX`, or `FL`, the `authorized_brands` array, and an hourly `labor_rate_cents`; centers begin `ACTIVE` and may later be moved to `SUSPENDED` or have their rate adjusted."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_by_center_status
        """
        account, product, center = _claim_setup(api, labor_rate_cents=11000,
                                                   account_number="SVC-802")
        claim = make_claim_under_review(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-556",
        )
        validate_success(
            api.patch_service_center(center["id"], {"status": "SUSPENDED"}, MGR), 200
        )
        validate_error(api.approve_claim(claim["id"], MGR), ApiErrorId.ERR_CENTER_SUSPENDED)

        validate_success(
            api.patch_service_center(center["id"], {"status": "ACTIVE"}, MGR), 200
        )
        approved = validate_success(api.approve_claim(claim["id"], MGR), 200)
        assert approved["status"] == "APPROVED", (
            f"with the center ACTIVE again the cross-entity gate lifts: {approved}"
        )


class TestClaimCreationChecks:
    def test_claim_serial_duplicate_among_non_rejected(self, api):
        """PRD §3.8: "First, the product's `product_family` must be `EQUIPMENT`, and the `serial_number` must not already appear on any claim for the same product that is not `REJECTED` — violations draw `ERR_CLAIM_SERIAL_DUPLICATE` (HTTP 409)."
        PRD §3.8: "Rejection lands the claim at `REJECTED` and zeroes the `provisional_credit_cents` as compensation."

        Design: Corner/validations/claim_serial_duplicate_among_non_rejected
        """
        account, product, _center = _claim_setup(api, labor_rate_cents=10000,
                                                    account_number="SVC-15")
        c1 = make_claim(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-DUP", failure_description="noise",
        )
        resp = api.create_warranty_claim(
            {
                "account_id": account["id"], "product_id": product["id"],
                "serial_number": "SN-DUP", "brand": "AquaFlow",
                "purchase_date": "2026-01-01", "failure_description": "dup attempt",
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_SERIAL_DUPLICATE)

        # Rejecting the first claim frees the serial.
        validate_success(api.start_claim_review(c1["id"], MGR), 200)
        rejected = validate_success(api.reject_claim(c1["id"], MGR), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["provisional_credit_cents"] == 0, (
            f"rejection zeroes the provisional credit as compensation: {rejected}"
        )
        c2 = make_claim(
            api, account_id=account["id"], product_id=product["id"],
            serial_number="SN-DUP", failure_description="retry after rejection",
        )
        assert c2["status"] == "SUBMITTED", (
            "REJECTED claims no longer hold the serial"
        )

    def test_no_authorized_center_blocks_claim(self, api):
        """PRD §3.8: "Second, at least one `ACTIVE` service center must carry the `brand` in its `authorized_brands`, else the claim cannot be routed and is rejected with `ERR_NO_AUTHORIZED_CENTER` (HTTP 422)."
        PRD §3.8: "At submission the claim's `assigned_center_id` is chosen by a deterministic selector over `ACTIVE` centers authorized for the brand: centers whose `region_code` matches the region of the account's branch rank first, then cheaper `labor_rate_cents`, then earlier `created_at`."

        Design: Corner/validations/no_authorized_center_blocks_claim
        """
        account, product, center = _claim_setup(api, labor_rate_cents=10000,
                                                   account_number="SVC-16")
        validate_success(
            api.patch_service_center(center["id"], {"status": "SUSPENDED"}, MGR), 200
        )
        resp = api.create_warranty_claim(
            {
                "account_id": account["id"], "product_id": product["id"],
                "serial_number": "SN-X", "brand": "AquaFlow",
                "purchase_date": "2026-01-01", "failure_description": "dead",
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_NO_AUTHORIZED_CENTER)
