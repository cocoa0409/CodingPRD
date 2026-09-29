"""Opening check runs, the pinned processing-fee steps and the lock/unlock discipline."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_check_disbursement,
    assert_refund_batch,
    add_batch_item,
    attribute_all,
    create_refund_batch_payload,
    decide_request,
    make_refund_approver_headers,
    prepare_refund_request,
    lock_batch,
    open_batch,
    read_batch,
    read_check,
    read_refund_request,
    set_clock,
    setup_approved_refund_request,
    setup_attributed_credit,
    setup_multi_credit_scenario,
    submit_request,
    unlock_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["disbursement_officer_headers"]


def _two_approved_requests(credit_specs, payee_names, amounts):
    """Two accounts with PATIENT-attributed credits, each with an approved request."""
    scenario = setup_multi_credit_scenario(accounts=credit_specs, state_code="TX")
    scenario["credit_balances"] = attribute_all(
        [cb["id"] for cb in scenario["credit_balances"]]
    )
    scenario["refund_requests"] = [
        setup_approved_refund_request(
            credit_balance, requested_amount_cents=amount, payee_type="PATIENT",
            payee_state_code="TX", payee_name=name, approver_tier=3,
        )
        for credit_balance, amount, name in zip(
            scenario["credit_balances"], amounts, payee_names
        )
    ]
    return scenario


def test_fee_band_is_keyed_on_the_gross_so_5001_nets_less_than_5000(api):
    """PRD §3.8: "**Step one selects the band, keyed on the gross amount only.** If `gross_amount_cents` is at most 5,000 cents, the rate is zero basis points and the flat component is 0 cents. If it is above 5,000 and at most 50,000 cents, the rate is 150 basis points — one and a half percent — and the flat component is 100 cents."
    PRD §3.8: "**Step two computes the fee: multiply the gross by the band's basis points, divide by 10,000, round that product half up to a whole cent, add the band's flat component, and then cap the result at 2,500 cents.** Rounding happens once, before the cap, never after it."
    PRD §3.8: "Do not iterate to a fixed point and do not re-band on the net — a gross of 5,001 cents is banded at 150 basis points and nets less than a gross of exactly 5,000 cents, and that inversion is intended, not a defect."

    Design: Difficulty/combinatorial_formula/refund_fee_band_keyed_on_gross_never_on_net_check_amount
    """
    scenario = _two_approved_requests(
        [
            {"account_number": "ACCT-FB1", "charge_cents": 20_000,
             "payment_cents": -25_000, "payment_source": "PATIENT"},
            {"account_number": "ACCT-FB2", "charge_cents": 20_000,
             "payment_cents": -25_001, "payment_source": "PATIENT"},
        ],
        ["Faye Band", "Finn Band"],
        [5_000, 5_001],
    )
    batch = open_batch("B-FEE", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")

    first = validate_success(
        api.add_refund_batch_item(
            batch["id"],
            {"refund_request_id": scenario["refund_requests"][0]["id"]},
            OFFICER,
        ),
        201,
    )
    second = validate_success(
        api.add_refund_batch_item(
            batch["id"],
            {"refund_request_id": scenario["refund_requests"][1]["id"]},
            OFFICER,
        ),
        201,
    )

    assert_check_disbursement(first)
    assert first["gross_amount_cents"] == 5_000
    assert first["processing_fee_cents"] == 0
    assert first["net_check_amount_cents"] == 5_000

    assert_check_disbursement(second)
    assert second["gross_amount_cents"] == 5_001
    assert second["processing_fee_cents"] == 175
    assert second["net_check_amount_cents"] == 4_826

    assert second["net_check_amount_cents"] < first["net_check_amount_cents"], (
        "banding on the gross must make 5,001 net less than 5,000"
    )


def test_check_run_totals_sum_the_gross_fee_and_net_of_its_counted_lines(api):
    """PRD §2.9: "On a check run, `item_count` is the number of check lines on the run whose `state` is anything other than `VOIDED`, and `total_gross_cents`, `total_fee_cents` and `total_net_cents` are the sums of `gross_amount_cents`, `processing_fee_cents` and `net_check_amount_cents` over those same counted lines."
    PRD §3.8: "Adding a line moves the request `NOT_SCHEDULED → BATCHED` or `REISSUE_PENDING → BATCHED`, recomputes the run's four totals, and bumps the run's `version` by 1."

    Design: Difficulty/combinatorial_formula/refund_fee_band_keyed_on_gross_never_on_net_check_amount
    """
    scenario = _two_approved_requests(
        [
            {"account_number": "ACCT-FB1", "charge_cents": 20_000,
             "payment_cents": -25_000, "payment_source": "PATIENT"},
            {"account_number": "ACCT-FB2", "charge_cents": 20_000,
             "payment_cents": -25_001, "payment_source": "PATIENT"},
        ],
        ["Faye Band", "Finn Band"],
        [5_000, 5_001],
    )
    batch = open_batch("B-FEE", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    for request in scenario["refund_requests"]:
        add_batch_item(batch["id"], request["id"])

    totals = read_batch(batch["id"])
    assert_refund_batch(totals)
    assert totals["item_count"] == 2
    assert totals["total_gross_cents"] == 10_001
    assert totals["total_fee_cents"] == 175
    assert totals["total_net_cents"] == 9_826
    for request in scenario["refund_requests"]:
        assert read_refund_request(request["id"])["disbursement_state"] == "BATCHED"


def test_processing_fee_is_capped_at_2500_cents_on_a_large_gross(api):
    """PRD §3.8: "Above 50,000 cents the rate drops to 75 basis points — three quarters of one percent — and the flat component rises to 500 cents."
    PRD §3.8: "**Step two computes the fee: multiply the gross by the band's basis points, divide by 10,000, round that product half up to a whole cent, add the band's flat component, and then cap the result at 2,500 cents.** Rounding happens once, before the cap, never after it."
    PRD §3.6: "Anything above 250,000 cents is base tier 3."

    Design: Corner/calculations/processing_fee_cap_binds_on_a_large_gross_refund
    """
    scenario = setup_attributed_credit(
        account_number="ACCT-CP1", state_code="TX", financial_class="INPATIENT",
        charge_cents=100_000, payment_cents=-400_000,
    )
    credit_balance = scenario["credit_balance"]
    set_clock("2026-08-16T00:00:00Z")

    request = prepare_refund_request(
        credit_balance["id"], 300_000, "PATIENT", credit_balance["version"],
        payee_name="Cleo Pratt", payee_address_line="20 Palm", payee_state_code="TX",
    )
    submit_request(request["id"])
    submitted = read_refund_request(request["id"])
    assert submitted["required_approval_tier"] == 3
    assert submitted["required_approval_count"] == 2
    decide_request(request["id"], "APPROVED", 3,
                   headers=make_refund_approver_headers("appr-1"))
    decide_request(request["id"], "APPROVED", 3,
                   headers=make_refund_approver_headers("appr-2"))
    approved = read_refund_request(request["id"])
    assert approved["approvals_received"] == 2
    assert approved["approval_state"] == "APPROVED"

    batch = open_batch("B-CP", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    check = validate_success(
        api.add_refund_batch_item(
            batch["id"], {"refund_request_id": request["id"]}, OFFICER
        ),
        201,
    )

    assert check["gross_amount_cents"] == 300_000
    assert check["processing_fee_cents"] == 2_500
    assert check["net_check_amount_cents"] == 297_500
    totals = read_batch(batch["id"])
    assert totals["item_count"] == 1
    assert totals["total_net_cents"] == 297_500


def test_line_whose_net_falls_below_the_two_hundred_cent_floor_is_refused(api):
    """PRD §3.8: "**Step four is a floor guard:** if the net would fall below 200 cents, the line is refused with `ERR_NET_BELOW_MIN_CHECK` (HTTP 422)."
    PRD §3.8: "**Step three sets the net:** `net_check_amount_cents` is `gross_amount_cents` minus `processing_fee_cents`."

    Design: Corner/endpoints/net_below_min_check_when_gross_sits_under_the_two_hundred_cent_floor
    """
    scenario = setup_attributed_credit(
        account_number="ACCT-NB1", charge_cents=10_000, payment_cents=-10_150,
    )
    credit_balance = scenario["credit_balance"]
    assert credit_balance["patient_portion_cents"] == 150
    request = setup_approved_refund_request(
        credit_balance, requested_amount_cents=150, payee_type="PATIENT",
        payee_name="Nia Blum",
    )
    batch = open_batch("B-NB", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z",
                       bank_account_code="TRUST")

    response = api.add_refund_batch_item(
        batch["id"], {"refund_request_id": request["id"]}, OFFICER
    )
    validate_error(response, ApiErrorId.ERR_NET_BELOW_MIN_CHECK.value)

    assert read_batch(batch["id"])["item_count"] == 0
    assert read_refund_request(request["id"])["disbursement_state"] == "NOT_SCHEDULED"
    _, meta = validate_paginated(
        api.list_check_disbursements(
            OFFICER, params={"refund_batch_id": batch["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_locking_an_empty_check_run_is_refused_at_the_zero_line_boundary(api):
    """PRD §3.8: "Locking moves it `OPEN → LOCKED`, requires at least one counted line — an empty run is refused with `ERR_BATCH_EMPTY` (HTTP 409) — requires the `expected_refund_batch_version` of §2.7, and bumps the run's `version` by 1."

    Design: Difficulty/boundary_precision_check/empty_batch_lock_rejected_at_zero_item_count_boundary
    """
    set_clock("2026-08-16T00:00:00Z")
    batch = open_batch("B-EMPTY", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z",
                       bank_account_code="TRUST")
    assert batch["item_count"] == 0

    response = api.lock_refund_batch(
        batch["id"], {"expected_refund_batch_version": batch["version"]}, OFFICER
    )
    validate_error(response, ApiErrorId.ERR_BATCH_EMPTY.value)
    assert read_batch(batch["id"])["state"] == "OPEN"


def test_empty_run_refused_at_lock_keeps_its_zero_totals_and_version(api):
    """PRD §3.8: "A new run opens in `state` `OPEN` with `item_count`, `total_gross_cents`, `total_fee_cents` and `total_net_cents` all at 0."
    PRD §3.8: "Locking moves it `OPEN → LOCKED`, requires at least one counted line — an empty run is refused with `ERR_BATCH_EMPTY` (HTTP 409) — requires the `expected_refund_batch_version` of §2.7, and bumps the run's `version` by 1."

    Design: Difficulty/boundary_precision_check/empty_batch_lock_rejected_at_zero_item_count_boundary
    """
    set_clock("2026-08-16T00:00:00Z")
    batch = open_batch("B-EMPTY", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z",
                       bank_account_code="TRUST")

    validate_error(
        api.lock_refund_batch(
            batch["id"], {"expected_refund_batch_version": batch["version"]}, OFFICER
        ),
        ApiErrorId.ERR_BATCH_EMPTY.value,
    )

    unchanged = read_batch(batch["id"])
    assert unchanged["item_count"] == 0
    assert unchanged["total_gross_cents"] == 0
    assert unchanged["total_fee_cents"] == 0
    assert unchanged["total_net_cents"] == 0
    assert unchanged["version"] == batch["version"], (
        "a rejected lock must not bump the run's version"
    )


def test_half_open_check_run_windows_allow_touching_but_reject_intersection(api):
    """PRD §2.10: "A check run occupies a **half-open** window on its disbursement channel: the interval runs from `cutoff_at` inclusive to `scheduled_run_at` exclusive."
    PRD §2.10: "Because the interval is half-open, **touching is allowed**: a new run whose `cutoff_at` is exactly an existing run's `scheduled_run_at`, or whose `scheduled_run_at` is exactly an existing run's `cutoff_at`, does not intersect and is accepted. There is no buffer requirement. An intersecting window is rejected with `ERR_BATCH_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/refund_batch_half_open_window_allows_adjacency_rejects_intersection
    """
    set_clock("2026-08-16T00:00:00Z")
    open_batch("B-W1", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")

    adjacent = validate_success(
        api.create_refund_batch(
            create_refund_batch_payload(
                "B-W2", "2026-08-20T00:00:00Z", "2026-08-22T00:00:00Z"
            ),
            OFFICER,
        ),
        201,
    )
    assert adjacent["state"] == "OPEN"

    overlapping = api.create_refund_batch(
        create_refund_batch_payload(
            "B-W3", "2026-08-19T00:00:00Z", "2026-08-21T00:00:00Z"
        ),
        OFFICER,
    )
    validate_error(overlapping, ApiErrorId.ERR_BATCH_WINDOW_OVERLAP.value)


def test_window_reservation_is_scoped_to_a_single_disbursement_channel(api):
    """PRD §2.10: "Two runs drawing on the same `bank_account_code` may not have intersecting windows while both are alive, where alive means a `state` of `OPEN`, `LOCKED` or `ISSUED`; a `CLOSED` run releases its window."
    PRD §3.8: "A `DisbursementOfficer` opens a run with a globally unique `batch_number` — a collision is `ERR_DUPLICATE_BATCH_NUMBER` — a `bank_account_code` of `OPERATING`, `TRUST` or `ESCROW` naming the disbursement channel it draws on, a `cutoff_at` and a `scheduled_run_at`."

    Design: Difficulty/resource_temporal_overlap/refund_batch_half_open_window_allows_adjacency_rejects_intersection
    """
    set_clock("2026-08-16T00:00:00Z")
    open_batch("B-W1", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    open_batch("B-W2", "2026-08-20T00:00:00Z", "2026-08-22T00:00:00Z")
    validate_error(
        api.create_refund_batch(
            create_refund_batch_payload(
                "B-W3", "2026-08-19T00:00:00Z", "2026-08-21T00:00:00Z"
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_BATCH_WINDOW_OVERLAP.value,
    )

    other_channel = validate_success(
        api.create_refund_batch(
            create_refund_batch_payload(
                "B-W4", "2026-08-19T00:00:00Z", "2026-08-21T00:00:00Z",
                bank_account_code="TRUST",
            ),
            OFFICER,
        ),
        201,
    )
    assert other_channel["bank_account_code"] == "TRUST"

    _, meta = validate_paginated(
        api.list_refund_batches(OFFICER, params={"bank_account_code": "OPERATING"})
    )
    assert meta["total_count"] == 2


def test_cutoff_at_equal_to_scheduled_run_at_is_an_invalid_window(api):
    """PRD §3.8: "The `cutoff_at` must be strictly before the `scheduled_run_at`, or the run is refused with `ERR_INVALID_BATCH_WINDOW` (HTTP 422); the two instants then bound the half-open occupation window on that channel described in §2.10, and `scheduled_run_at` doubles as the intended issue instant."

    Design: Corner/validations/batch_window_with_cutoff_after_run_is_rejected
    """
    response = api.create_refund_batch(
        create_refund_batch_payload(
            "B-BAD", "2026-08-20T00:00:00Z", "2026-08-20T00:00:00Z",
            bank_account_code="ESCROW",
        ),
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_BATCH_WINDOW.value)

    _, meta = validate_paginated(api.list_refund_batches(OFFICER))
    assert meta["total_count"] == 0


def test_batch_number_is_unique_across_every_check_run(api):
    """PRD §3.8: "A `DisbursementOfficer` opens a run with a globally unique `batch_number` — a collision is `ERR_DUPLICATE_BATCH_NUMBER` — a `bank_account_code` of `OPERATING`, `TRUST` or `ESCROW` naming the disbursement channel it draws on, a `cutoff_at` and a `scheduled_run_at`."

    Design: Corner/validations/duplicate_batch_number_is_rejected
    """
    set_clock("2026-08-16T00:00:00Z")
    first = open_batch("B-DUP", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")

    response = api.create_refund_batch(
        create_refund_batch_payload(
            "B-DUP", "2026-08-25T00:00:00Z", "2026-08-27T00:00:00Z",
            bank_account_code="TRUST",
        ),
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BATCH_NUMBER.value)

    _, meta = validate_paginated(api.list_refund_batches(OFFICER))
    assert meta["total_count"] == 1
    assert read_batch(first["id"])["bank_account_code"] == "OPERATING"


def test_lines_are_refused_while_locked_and_accepted_again_after_unlock(api):
    """PRD §3.8: "After locking, no further lines may be added. Unlocking moves it `LOCKED → OPEN` again, takes no body at all, bumps the `version` by 1 and reopens the line set; this revert edge is what makes the lock's stale-version guard necessary in the first place."
    PRD §2.8: "The check run is in the state the operation requires — `ERR_BATCH_INVALID_STATE`. This guards adding a line (`OPEN`), locking (`OPEN`), unlocking (`LOCKED`), issuing (`LOCKED`) and reissuing a check into a target run (`OPEN`)."

    Design: Corner/endpoints/batch_items_rejected_after_lock_and_accepted_again_after_unlock
    """
    scenario = _two_approved_requests(
        [
            {"account_number": "ACCT-UL1"},
            {"account_number": "ACCT-UL2"},
        ],
        ["Ula One", "Ula Two"],
        [12_000, 12_000],
    )
    batch = open_batch("B-UL", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    add_batch_item(batch["id"], scenario["refund_requests"][0]["id"])
    lock_batch(batch["id"])

    blocked = api.add_refund_batch_item(
        batch["id"], {"refund_request_id": scenario["refund_requests"][1]["id"]},
        OFFICER,
    )
    validate_error(blocked, ApiErrorId.ERR_BATCH_INVALID_STATE.value)

    reopened = validate_success(api.unlock_refund_batch(batch["id"], {}, OFFICER))
    assert reopened["state"] == "OPEN"

    second_line = validate_success(
        api.add_refund_batch_item(
            batch["id"], {"refund_request_id": scenario["refund_requests"][1]["id"]},
            OFFICER,
        ),
        201,
    )
    assert second_line["state"] == "PENDING"

    totals = read_batch(batch["id"])
    assert totals["item_count"] == 2
    assert totals["total_gross_cents"] == 24_000
    assert totals["total_fee_cents"] == 560
    assert totals["total_net_cents"] == 23_440


def test_stale_refund_batch_version_rejects_the_lock(api):
    """PRD §2.7: "Locking a check run requires a non-optional `expected_refund_batch_version` field carrying the client's last observed `version` of that `RefundBatch`. A mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.8: "Adding a line moves the request `NOT_SCHEDULED → BATCHED` or `REISSUE_PENDING → BATCHED`, recomputes the run's four totals, and bumps the run's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_stale_refund_batch_version_rejects_lock_then_fresh_version_succeeds
    """
    scenario = setup_attributed_credit(account_number="ACCT-BL1")
    set_clock("2026-08-16T00:00:00Z")
    request = setup_approved_refund_request(
        scenario["credit_balance"], requested_amount_cents=12_000,
        payee_type="PATIENT", payee_name="Bea Lund",
    )
    batch = open_batch("B-BL", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    stale_version = batch["version"]
    add_batch_item(batch["id"], request["id"])

    stale_lock = api.lock_refund_batch(
        batch["id"], {"expected_refund_batch_version": stale_version}, OFFICER
    )
    validate_error(stale_lock, ApiErrorId.ERR_STALE_VERSION.value)
    assert read_batch(batch["id"])["state"] == "OPEN"

    fresh_version = read_batch(batch["id"])["version"]
    locked = validate_success(
        api.lock_refund_batch(
            batch["id"], {"expected_refund_batch_version": fresh_version}, OFFICER
        )
    )
    assert locked["state"] == "LOCKED"

    totals = read_batch(batch["id"])
    assert totals["item_count"] == 1
    assert totals["total_gross_cents"] == 12_000
    assert totals["total_fee_cents"] == 280
    assert totals["total_net_cents"] == 11_720
