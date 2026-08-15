"""Seasonal programs and pre-season commitments: inclusive commitment windows,
window-before-pool validation order, pool-cap enforcement, supersede pool
conservation, program-version OCC, commitment exhaustion, and the cancel
compensation that reverts a FULFILLED commitment."""
from test_helpers import (
    ApiErrorId,
    MGR,
    branch_version,
    create_confirmed_order,
    create_seasonal_commitment_payload,
    make_account,
    make_branch,
    make_commitment,
    make_lot,
    make_open_program_with_commitment,
    make_order,
    make_product,
    make_program,
    open_program,
    order_line,
    program_version,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]


def _program_setup(api, pool_cap_units=100):
    """Branch + two accounts + an OPEN program with the standard 2026 window."""
    branch = make_branch(api, hazmat_storage_certified=True)
    a1 = make_account(api, account_number="DLR-P1")
    a2 = make_account(api, account_number="DLR-P2")
    program = make_program(
        api, branch_id=branch["id"], program_name="EB",
        early_buy_discount_pct=10, pool_cap_units=pool_cap_units,
    )
    return branch, a1, a2, program


class TestCommitmentWindowBoundaries:
    def test_commitment_window_inclusive_end_boundary(self, api):
        """PRD §3.3: "Creation time must fall within the commitment window, inclusive at both ends — a commitment created exactly at `order_window_end` is allowed — else `ERR_COMMITMENT_WINDOW_CLOSED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/commitment_window_inclusive_end_boundary
        """
        branch, a1, _a2, program = _program_setup(api, pool_cap_units=1000)
        opened = open_program(program["id"], api)
        set_clock("2026-02-15T00:00:00Z", api)  # exactly order_window_end
        resp = api.create_seasonal_commitment(
            create_seasonal_commitment_payload(
                program["id"], a1["id"], 50, opened["version"]
            ),
            MGR,
        )
        commitment = validate_success(resp, 201)
        assert commitment["status"] == "COMMITTED", (
            f"creation exactly at order_window_end is allowed (inclusive end): {commitment}"
        )

    def test_commitment_window_inclusive_start_boundary(self, api):
        """PRD §3.3: "Creation time must fall within the commitment window, inclusive at both ends — a commitment created exactly at `order_window_end` is allowed — else `ERR_COMMITMENT_WINDOW_CLOSED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/commitment_window_inclusive_end_boundary
        """
        branch, a1, _a2, program = _program_setup(api, pool_cap_units=1000)
        opened = open_program(program["id"], api)
        set_clock("2026-01-01T00:00:00Z", api)  # exactly order_window_start
        resp = api.create_seasonal_commitment(
            create_seasonal_commitment_payload(
                program["id"], a1["id"], 50, opened["version"]
            ),
            MGR,
        )
        commitment = validate_success(resp, 201)
        assert commitment["status"] == "COMMITTED", (
            f"inclusive at both ends — window start accepts: {commitment}"
        )


class TestWindowVsPoolPriority:
    def test_commitment_window_closed_beats_pool_exhausted(self, api):
        """PRD §2.9: "On commitment creation the order-window check precedes the pool-cap check."
        PRD §3.3: "Creation time must fall within the commitment window, inclusive at both ends — a commitment created exactly at `order_window_end` is allowed — else `ERR_COMMITMENT_WINDOW_CLOSED` (HTTP 422)."
        PRD §3.3: "The program's pool is finite: if the sum of `committed_units` across the program's `COMMITTED` commitments plus the new units would exceed `pool_cap_units`, creation is rejected with `ERR_PROGRAM_POOL_EXHAUSTED` (HTTP 422), and this pool check is evaluated only after the window check."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_commitment_window_vs_pool_cap
        """
        branch, a1, a2, program = _program_setup(api, pool_cap_units=100)
        set_clock("2026-02-01T00:00:00Z", api)
        opened = open_program(program["id"], api)
        make_commitment(program["id"], a1["id"], 100, opened["version"], api)

        # One second past order_window_end, with the pool already full: both
        # violations coexist and the temporal check must win.
        set_clock("2026-02-15T00:00:01Z", api)
        resp = api.create_seasonal_commitment(
            create_seasonal_commitment_payload(
                program["id"], a2["id"], 10, program_version(program["id"], api)
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_WINDOW_CLOSED)

    def test_pool_exhausted_inside_window(self, api):
        """PRD §3.3: "The program's pool is finite: if the sum of `committed_units` across the program's `COMMITTED` commitments plus the new units would exceed `pool_cap_units`, creation is rejected with `ERR_PROGRAM_POOL_EXHAUSTED` (HTTP 422), and this pool check is evaluated only after the window check."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_commitment_window_vs_pool_cap
        """
        branch, a1, a2, program = _program_setup(api, pool_cap_units=100)
        set_clock("2026-02-01T00:00:00Z", api)  # inside the window
        opened = open_program(program["id"], api)
        make_commitment(program["id"], a1["id"], 100, opened["version"], api)

        resp = api.create_seasonal_commitment(
            create_seasonal_commitment_payload(
                program["id"], a2["id"], 1, program_version(program["id"], api)
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_POOL_EXHAUSTED)


class TestSupersedePoolConservation:
    def test_program_pool_conserved_across_supersede(self, api):
        """PRD §3.3: "A new commitment supersedes: if the same program-and-account pairing already holds a `COMMITTED` commitment, the old one transitions to `SUPERSEDED` and the new one is born `COMMITTED` — but only when the replacement's `committed_units` are at least the existing commitment's already-`consumed_units`, else `ERR_COMMITMENT_BELOW_CONSUMED` (HTTP 422)."
        PRD §3.3: "Either way the branch's `seasonal_pool_units` — defined as the sum of `committed_units` over `COMMITTED` commitments across the branch's programs — is recomputed: the superseded units leave the pool, the new units enter it, and a defaulted commitment likewise leaves the pool."

        Design: Difficulty/compensating_invariant/program_pool_conserved_across_supersede
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-1001")
        program = make_program(api, branch_id=branch["id"], pool_cap_units=1000)
        opened = open_program(program["id"], api)
        c1 = make_commitment(program["id"], account["id"], 100, opened["version"], api)

        c2 = make_commitment(program["id"], account["id"], 150, api=api)
        assert c2["status"] == "COMMITTED"
        assert c2["committed_units"] == 150
        old = validate_success(api.get_seasonal_commitment(c1["id"], MGR))
        assert old["status"] == "SUPERSEDED", (
            f"the old commitment transitions to SUPERSEDED: {old}"
        )
        branch_after = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_after["seasonal_pool_units"] == 150, (
            f"supersede conserves pool accounting: 150, not 250: {branch_after}"
        )

    def test_program_pool_conserved_across_supersede_downsize(self, api):
        """PRD §3.3: "A new commitment supersedes: if the same program-and-account pairing already holds a `COMMITTED` commitment, the old one transitions to `SUPERSEDED` and the new one is born `COMMITTED` — but only when the replacement's `committed_units` are at least the existing commitment's already-`consumed_units`, else `ERR_COMMITMENT_BELOW_CONSUMED` (HTTP 422)."
        PRD §3.3: "Either way the branch's `seasonal_pool_units` — defined as the sum of `committed_units` over `COMMITTED` commitments across the branch's programs — is recomputed: the superseded units leave the pool, the new units enter it, and a defaulted commitment likewise leaves the pool."

        Design: Difficulty/compensating_invariant/program_pool_conserved_across_supersede
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-1002")
        program = make_program(api, branch_id=branch["id"], pool_cap_units=1000)
        opened = open_program(program["id"], api)
        c1 = make_commitment(program["id"], account["id"], 100, opened["version"], api)
        branch_mid = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_mid["seasonal_pool_units"] == 100

        c2 = make_commitment(program["id"], account["id"], 40, api=api)
        assert c2["status"] == "COMMITTED" and c2["committed_units"] == 40
        old = validate_success(api.get_seasonal_commitment(c1["id"], MGR))
        assert old["status"] == "SUPERSEDED"
        branch_after = validate_success(api.get_branch(branch["id"], MGR))
        assert branch_after["seasonal_pool_units"] == 40, (
            f"downsizing supersede removes the old units from the pool: {branch_after}"
        )


class TestCommitmentConsumptionAndOcc:
    def test_err_commitment_exhausted_triggered(self, api):
        """PRD §3.4: "Commitment sixth: when `commitment_id` is set, the commitment must exist, be `COMMITTED`, belong to the order's account, and have remaining units — committed minus consumed — covering the order's total units, else `ERR_COMMITMENT_EXHAUSTED` (HTTP 422)."

        Design: Corner/errors/err_commitment_exhausted_triggered
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-19")
        product = make_product(
            api, sku="TAB-FLT", product_family="CHEMICAL", base_price_cents=900
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=100)
        _program, commitment = make_open_program_with_commitment(
            branch["id"], account["id"], 3, api, pool_cap_units=1000
        )
        order = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", requested_pickup_slot="2026-01-10T15:00:00Z",
            commitment_id=commitment["id"],
            lines=[order_line(product["id"], 4)],
        )
        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            COUNTER,
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXHAUSTED)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "DRAFT", (
            f"rejected confirm leaves the order in DRAFT: {order}"
        )

    def test_order_cancel_reverts_commitment_fulfilled_to_committed(self, api):
        """PRD §3.4: "When `commitment_id` is set, the commitment's `consumed_units` climb by the order's total units, and a commitment thereby fully consumed becomes `FULFILLED`."
        PRD §3.6: "If the order drew on a commitment, the commitment's `consumed_units` fall by the order's total units, and a commitment that this order had pushed to `FULFILLED` reverts to `COMMITTED`."

        Design: Corner/state_machines/order_cancel_reverts_commitment_fulfilled_to_committed
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-4")
        product = make_product(
            api, sku="TAB-3IN", product_family="CHEMICAL", base_price_cents=1000
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=100)
        _program, commitment = make_open_program_with_commitment(
            branch["id"], account["id"], 5, api, pool_cap_units=1000
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-01-10T15:00:00Z",
            commitment_id=commitment["id"],
            lines=[order_line(product["id"], 5)],
        )
        mid = validate_success(api.get_seasonal_commitment(commitment["id"], MGR))
        assert mid["status"] == "FULFILLED", (
            f"consumption reaching the committed figure settles FULFILLED: {mid}"
        )
        assert mid["consumed_units"] == 5

        validate_success(api.cancel_order(order["id"], MGR), 200)
        after = validate_success(api.get_seasonal_commitment(commitment["id"], MGR))
        assert after["status"] == "COMMITTED", (
            f"cancel compensation reverts FULFILLED to COMMITTED: {after}"
        )
        assert after["consumed_units"] == 0

    def test_occ_stale_program_version_on_commitment_supersede(self, api):
        """PRD §2.8: "**Seasonal commitment creation** requires a non-optional `expected_program_version` carrying the client's last observed `version` of the seasonal program. A mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), ensuring pool-cap enforcement runs against a program snapshot the client actually saw."
        PRD §3.3: "Recording the commitment also increments the program's `version` by one — one more reason stale program snapshots surface."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_program_version_on_commitment_supersede
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        a1 = make_account(api, account_number="DLR-24A")
        a2 = make_account(api, account_number="DLR-24B")
        program = make_program(api, branch_id=branch["id"], pool_cap_units=1000)
        opened = open_program(program["id"], api)
        c1 = make_commitment(program["id"], a1["id"], 100, opened["version"], api)

        stale = program_version(program["id"], api)
        # Another commitment advances the program version past the snapshot.
        make_commitment(program["id"], a2["id"], 50, stale, api)

        resp = api.create_seasonal_commitment(
            create_seasonal_commitment_payload(program["id"], a1["id"], 120, stale),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
        c1_after = validate_success(api.get_seasonal_commitment(c1["id"], MGR))
        assert c1_after["status"] == "COMMITTED", (
            f"stale-version supersede never happened: {c1_after}"
        )
