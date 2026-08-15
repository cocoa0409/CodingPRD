"""Inter-grower transfers: the atomic finalize cascade, the conserved global
active headcount, and the guard battery (same-grower, duplicate, ownership)."""
from test_helpers import (
    ApiErrorId,
    J1_WORKDAYS_0901_TO_0914,
    TEST_USERS,
    create_transfer_request_payload,
    get_reconciliation,
    get_success_data,
    make_grower_rep_headers,
    setup_transfer_grower_approved,
    setup_two_grower_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]

J1_LOGS_12_DAYS = [(d, 8, 25) for d in J1_WORKDAYS_0901_TO_0914]


class TestFinalizeThreeHopCascade:
    def test_finalize_moves_source_and_keeps_worker_working(self, api):
        """PRD 3.8: "Finalizing is atomic. The transfer's effective date is the
        clock date. The source assignment moves from `ACTIVE` to `TRANSFERRED_OUT`
        with `end_reason` `TRANSFERRED_OUT`, its `ended_on` set to the day before
        the effective date, and `guarantee_eligible` true; its housing stays are
        vacated with `move_out_date` set to that `ended_on`; and its wage
        reconciliation is recomputed on the truncated basis window while remaining
        `OPEN`. Simultaneously, a brand-new worker assignment is created on the
        target order — already `ACTIVE` with `started_on` set to the effective
        date, exempt from the petition-matching rule of §3.6 — together with a
        fresh `OPEN` wage reconciliation computed on the provisional variant. The
        worker remains `WORKING` throughout, and the request itself lands in its
        terminal `APPROVED` state."

        Design: Difficulty/transitive_cascade/transfer_finalize_three_hop_cascade
        """
        s = setup_transfer_grower_approved(j1_logs=J1_LOGS_12_DAYS)

        tr = validate_success(api.finalize_transfer(s["transfer"]["id"], ADMIN), 200)
        assert tr["status"] == "APPROVED"

        # Hop 1: the source assignment transfers out on effective-date-minus-one.
        src = get_success_data(api.get_worker_assignment(s["asg_a"]["id"], ADMIN))
        assert src["status"] == "TRANSFERRED_OUT"
        assert src["end_reason"] == "TRANSFERRED_OUT"
        assert src["ended_on"] == "2026-09-14"  # effective 2026-09-15 minus 1 day
        assert src["guarantee_eligible"] is True

        assert get_success_data(api.get_worker(s["wa"]["id"], ADMIN))["status"] == "WORKING"

    def test_finalize_recomputes_source_and_creates_target_reconciliation(self, api):
        """PRD 3.8: "its wage reconciliation is recomputed on the truncated basis
        window while remaining `OPEN`. Simultaneously, a brand-new worker
        assignment is created on the target order — already `ACTIVE` with
        `started_on` set to the effective date, exempt from the petition-matching
        rule of §3.6 — together with a fresh `OPEN` wage reconciliation computed
        on the provisional variant."
        PRD 3.7: "The reconciliation's accrual horizon, `computed_through_date`, is
        the assignment's `ended_on` once the assignment is terminal — ended
        assignments stop accruing — and otherwise the earlier of the clock date
        and the order's `work_end_date`."

        Design: Difficulty/transitive_cascade/transfer_finalize_three_hop_cascade
        """
        s = setup_transfer_grower_approved(j1_logs=J1_LOGS_12_DAYS)
        validate_success(api.finalize_transfer(s["transfer"]["id"], ADMIN), 200)

        # Hop 2: source reconciliation recomputed on the truncated basis.
        src_rec = get_reconciliation(s["asg_a"]["id"])
        assert src_rec["status"] == "OPEN"
        assert src_rec["computed_through_date"] == "2026-09-14"
        # Basis 2026-09-01..2026-09-14 = 12 workdays; 384 quarters -> 288 guaranteed.
        assert src_rec["guarantee_basis_workdays"] == 12
        assert src_rec["piece_earnings_cents"] == 135000  # 12 days x 25 x 450
        assert src_rec["hourly_floor_earnings_cents"] == 177600  # 12 x 14800
        assert src_rec["makeup_pay_cents"] == 42600  # 2 x (88800 - 67500)
        assert src_rec["guaranteed_quarters"] == 288
        assert src_rec["worked_quarters"] == 384
        assert src_rec["shortfall_quarters"] == 0
        assert src_rec["inbound_transport_owed_cents"] == 0  # ended before threshold
        assert src_rec["total_due_cents"] == 177600

        # Hop 3: the new ACTIVE assignment on J2 with a fresh OPEN reconciliation.
        rows, meta = validate_paginated(
            api.list_worker_assignments(
                ADMIN, params={"worker_id": s["wa"]["id"], "job_order_id": s["jo2"]["id"], "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1
        tgt = rows[0]
        assert tgt["started_on"] == "2026-09-15"

        tgt_rec = get_reconciliation(tgt["id"])
        assert tgt_rec["status"] == "OPEN"
        assert tgt_rec["computed_through_date"] == "2026-09-15"
        # J2 basis 2026-09-15 only: 1 workday; 32 quarters; floor(32*3/4) = 24.
        assert tgt_rec["guarantee_basis_workdays"] == 1
        assert tgt_rec["guaranteed_quarters"] == 24
        assert tgt_rec["worked_quarters"] == 0
        assert tgt_rec["guarantee_pay_cents"] == 11100  # round_half_up(24 x 1850 / 4)
        assert tgt_rec["total_due_cents"] == 11100


class TestActiveHeadcountConservation:
    def test_before_finalize_exactly_one_active_assignment(self, api):
        """PRD 3.6: "One worker holds at most one live assignment: a worker who
        already has a `PLANNED` or `ACTIVE` assignment anywhere is rejected with
        `ERR_WORKER_ALREADY_ASSIGNED`."

        Design: Difficulty/compensating_invariant/transfer_finalize_conserves_global_active_headcount
        """
        s = setup_transfer_grower_approved()
        _, meta = validate_paginated(api.list_worker_assignments(ADMIN, params={"status": "ACTIVE"}))
        assert meta["total_count"] == 1

    def test_finalize_conserves_global_active_headcount(self, api):
        """PRD 3.8: "The source assignment moves from `ACTIVE` to `TRANSFERRED_OUT`
        with `end_reason` `TRANSFERRED_OUT`, its `ended_on` set to the day before
        the effective date, and `guarantee_eligible` true"
        PRD 3.8: "Simultaneously, a brand-new worker assignment is created on the
        target order — already `ACTIVE` with `started_on` set to the effective
        date, exempt from the petition-matching rule of §3.6 — together with a
        fresh `OPEN` wage reconciliation computed on the provisional variant."

        Design: Difficulty/compensating_invariant/transfer_finalize_conserves_global_active_headcount
        """
        s = setup_transfer_grower_approved()
        _, before = validate_paginated(api.list_worker_assignments(ADMIN, params={"status": "ACTIVE"}))
        assert before["total_count"] == 1

        validate_success(api.finalize_transfer(s["transfer"]["id"], ADMIN), 200)

        rows, after = validate_paginated(api.list_worker_assignments(ADMIN, params={"status": "ACTIVE"}))
        assert after["total_count"] == 1, "forward/compensation pair conserves the ACTIVE headcount"
        assert rows[0]["id"] != s["asg_a"]["id"]
        assert rows[0]["job_order_id"] == s["jo2"]["id"]
        src = get_success_data(api.get_worker_assignment(s["asg_a"]["id"], ADMIN))
        assert src["status"] == "TRANSFERRED_OUT"


class TestTransferGuards:
    def test_transfer_guard_battery_rejected(self, api):
        """PRD 3.8: "the target order must be `ACTIVE` (else
        `ERR_JOB_ORDER_INVALID_STATE`) and must belong to a different grower than
        the source — a same-grower transfer is rejected with
        `ERR_SAME_GROWER_TRANSFER`."
        PRD 3.8: "A worker with another transfer still in `PENDING` or
        `GROWER_APPROVED` cannot be re-filed: that attempt is rejected with
        `ERR_DUPLICATE_ACTIVE_TRANSFER`."
        PRD 3.8: "Both actions require the request to be `PENDING` (else
        `ERR_TRANSFER_INVALID_STATE`) and both are ownership-checked: the
        representative's `X-User-ID` must equal the target order's `grower_id`,
        else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`."
        PRD 3.8: "A grower representative may cancel only a request it originally
        filed — its `X-User-ID` must equal the request's `requested_by_user_id`,
        else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`."
        PRD 3.6: "a grower representative's `X-User-ID` must equal that order's
        `grower_id`, else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`."

        Design: Corner/errors/transfer_guard_battery_rejected
        """
        s = setup_two_grower_scenario(include_j1b=True)
        g1, g2, wa, asg_a = s["g1"], s["g2"], s["wa"], s["asg_a"]

        # Target order belonging to the same grower as the source.
        resp = api.create_transfer_request(
            create_transfer_request_payload(wa["id"], asg_a["id"], s["jo1b"]["id"], "GROWER_REQUEST"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_GROWER_TRANSFER)

        # A valid request lands in PENDING and blocks any second live request.
        tr = validate_success(
            api.create_transfer_request(
                create_transfer_request_payload(wa["id"], asg_a["id"], s["jo2"]["id"], "CONTRACT_IMPOSSIBILITY"),
                ADMIN,
            ),
            201,
        )
        assert tr["status"] == "PENDING"
        resp = api.create_transfer_request(
            create_transfer_request_payload(wa["id"], asg_a["id"], s["jo2"]["id"], "WORKER_REQUEST"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_TRANSFER)

        # A GrowerRep of another grower cannot report abandonment on G1's order.
        resp = api.report_abandonment(asg_a["id"], {}, make_grower_rep_headers(g2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)

        # Only the TARGET grower's representative may approve.
        resp = api.grower_approve_transfer(tr["id"], make_grower_rep_headers(g1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)
        approved = validate_success(
            api.grower_approve_transfer(tr["id"], make_grower_rep_headers(g2["id"])), 200
        )
        assert approved["status"] == "GROWER_APPROVED"

        # Approval requires PENDING; a second approval hits the state guard.
        resp = api.grower_approve_transfer(tr["id"], make_grower_rep_headers(g2["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE)

        # GrowerRep cancel requires the requester identity; TR1 was filed by the admin.
        resp = api.cancel_transfer(tr["id"], make_grower_rep_headers(g2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)

        # The valid execution path still succeeds.
        final = validate_success(api.finalize_transfer(tr["id"], ADMIN), 200)
        assert final["status"] == "APPROVED"
        src = get_success_data(api.get_worker_assignment(asg_a["id"], ADMIN))
        assert src["status"] == "TRANSFERRED_OUT" and src["ended_on"] == "2026-09-14"
        rows, meta = validate_paginated(
            api.list_worker_assignments(
                ADMIN, params={"worker_id": wa["id"], "job_order_id": s["jo2"]["id"], "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1 and rows[0]["started_on"] == "2026-09-15"
