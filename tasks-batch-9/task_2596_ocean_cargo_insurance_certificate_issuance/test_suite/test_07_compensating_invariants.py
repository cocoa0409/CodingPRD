"""
Reversals that put the books back exactly where they were.

Covers the exposure and premium ledgers a certificate moves when it is issued
and then cancelled before its cover attaches, the two premium ledgers that are
deliberately kept apart, the counters that record history and are never rewound,
the accumulation rows a cancellation releases and the reason it stamps on them,
and the surveyor's booked minutes an appointment takes and its cancellation
hands straight back — leaving the attendance window free to book again.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import (
    ACCUMULATION_SCOPES,
    CLAIMS_ADJUSTER,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_TOTAL_PREMIUM,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    assert_amounts,
    assert_instant,
    assert_money,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    create_survey_order,
    find_row,
    issue_certificate,
    read_certificate,
    read_claim_file,
    read_policy,
    read_port,
    read_surveyor,
    read_vessel,
)

# ---------------------------------------------------------------------------
# Issue and cancel: the four exposure ledgers and the two premium ledgers
# ---------------------------------------------------------------------------
CANCELLATION_REASON = "SHIPMENT_NOT_SHIPPED"

# The logical clock is left at its default 2026-08-01, and the shipment attaches
# on 2026-08-10, so the cancellation is strictly before attachment and the whole
# unreturned premium comes back.
EXPECTED_FULL_RETURN_PREMIUM = EXPECTED_TOTAL_PREMIUM

# One vessel row, one loading-port row and one discharge-port row.
EXPECTED_ACCUMULATION_ROW_COUNT = 3
EXPECTED_CANCELLED_RELEASE_REASON = "CERTIFICATE_CANCELLED"

# The counter of certificates that have ever left DRAFT, which a cancellation
# never reduces.
EXPECTED_CERTIFICATES_ISSUED_COUNT = 1


def _cover_with_one_declared_shipment(api: ApiClient) -> JsonDict:
    """
    The canonical book of business with one shipment declared but not yet
    issued, so every ledger the issue will move is still at zero.
    """
    env = build_canonical_environment(api)
    env["draft"] = build_draft_certificate(api, env)
    env["certificate_id"] = env["draft"]["id"]
    return env


def _issue_then_cancel_before_attachment(api: ApiClient) -> JsonDict:
    """
    Issue the declared shipment, record what every ledger read immediately
    afterwards, then cancel it while the risk has not begun.
    """
    env = _cover_with_one_declared_shipment(api)
    env["issued"] = issue_certificate(api, env["certificate_id"],
                                      env["policy_id"])
    env["vessel_after_issue"] = read_vessel(api, env["vessel_id"])
    env["loading_port_after_issue"] = read_port(api, env["loading_port_id"])
    env["discharge_port_after_issue"] = read_port(api, env["discharge_port_id"])
    env["policy_after_issue"] = read_policy(api, env["policy_id"])
    env["cancelled"] = get_success_data(api.cancel_certificate(
        env["certificate_id"], UNDERWRITER,
        {"cancellation_reason": CANCELLATION_REASON}))
    return env


def _entries(api: ApiClient, certificate_id: str, status: str):
    """The certificate's own accumulation ledger rows in one status."""
    return api.list_accumulation_entries(
        UNDERWRITER, {"certificate_id": certificate_id, "status": status})


def test_issue_books_the_shipment_onto_every_exposure_ledger(
        api: ApiClient) -> None:
    """
    The forward action of the pair: issuing lifts the vessel and both port
    ledgers off zero by the insured value and books the premium on the cover.

    The vessel's `accumulated_insured_value` rises by the insured value, and so does each of the two ports' `accumulated_insured_value`.

    Design: Difficulty/compensating_invariant/issue_then_cancel_conserves_exposure_and_net_premium
    """
    env = _cover_with_one_declared_shipment(api)

    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 0.00, "vessel.accumulated_insured_value before issue")
    assert_money(read_port(api, env["loading_port_id"])["accumulated_insured_value"],
                 0.00, "loading port.accumulated_insured_value before issue")
    assert_money(read_port(api, env["discharge_port_id"])["accumulated_insured_value"],
                 0.00, "discharge port.accumulated_insured_value before issue")
    assert_amounts(read_policy(api, env["policy_id"]), {
        "aggregate_insured_value_booked": 0.00,
        "aggregate_premium_booked": 0.00,
        "aggregate_return_premium": 0.00,
    }, "policy before issue")

    issued = issue_certificate(api, env["certificate_id"], env["policy_id"])
    assert issued["status"] == "ISSUED", (
        f"expected the shipment to be ISSUED, got {issued['status']}"
    )
    assert_money(issued["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "certificate.insured_value")
    assert_money(issued["total_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "certificate.total_premium_amount")

    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "vessel.accumulated_insured_value after issue")
    assert_money(read_port(api, env["loading_port_id"])["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "loading port.accumulated_insured_value after issue")
    assert_money(read_port(api, env["discharge_port_id"])["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "discharge port.accumulated_insured_value after issue")

    policy = read_policy(api, env["policy_id"])
    assert_amounts(policy, {
        "aggregate_insured_value_booked": EXPECTED_INSURED_VALUE_CIF,
        "aggregate_premium_booked": EXPECTED_TOTAL_PREMIUM,
        "aggregate_return_premium": 0.00,
    }, "policy after issue")
    assert policy["certificates_issued_count"] == EXPECTED_CERTIFICATES_ISSUED_COUNT, (
        f"expected certificates_issued_count "
        f"{EXPECTED_CERTIFICATES_ISSUED_COUNT}, "
        f"got {policy['certificates_issued_count']}"
    )

    rows, _ = validate_paginated(_entries(api, env["certificate_id"], "ACTIVE"))
    assert len(rows) == EXPECTED_ACCUMULATION_ROW_COUNT, (
        f"expected {EXPECTED_ACCUMULATION_ROW_COUNT} ACTIVE ledger rows, "
        f"got {len(rows)}"
    )
    for scope in ACCUMULATION_SCOPES:
        row = find_row(rows, scope_type=scope)
        assert_money(row["amount"], EXPECTED_INSURED_VALUE_CIF,
                     f"{scope} entry.amount")
        assert row["release_reason"] == "NONE", (
            f"a live {scope} entry must carry release_reason NONE, "
            f"got {row['release_reason']}"
        )


def test_cancel_before_attachment_returns_the_exposure_ledgers_to_zero(
        api: ApiClient) -> None:
    """
    The compensating action drives the vessel ledger, both port ledgers and the
    cover's booked exposure back to the exact totals they held before the issue.

    Cancelling a certificate returns the vessel and both port ledgers to precisely the totals they held before it was issued.

    Design: Difficulty/compensating_invariant/issue_then_cancel_conserves_exposure_and_net_premium
    """
    env = _issue_then_cancel_before_attachment(api)

    assert_money(env["vessel_after_issue"]["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "vessel.accumulated_insured_value after issue")
    assert_money(env["policy_after_issue"]["aggregate_insured_value_booked"],
                 EXPECTED_INSURED_VALUE_CIF,
                 "policy.aggregate_insured_value_booked after issue")

    assert env["cancelled"]["status"] == "CANCELLED", (
        f"expected the certificate to be CANCELLED, "
        f"got {env['cancelled']['status']}"
    )

    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 0.00, "vessel.accumulated_insured_value after cancel")
    assert_money(read_port(api, env["loading_port_id"])["accumulated_insured_value"],
                 0.00, "loading port.accumulated_insured_value after cancel")
    assert_money(read_port(api, env["discharge_port_id"])["accumulated_insured_value"],
                 0.00, "discharge port.accumulated_insured_value after cancel")
    assert_money(read_policy(api, env["policy_id"])["aggregate_insured_value_booked"],
                 0.00, "policy.aggregate_insured_value_booked after cancel")


def test_cancel_conserves_the_net_premium_across_two_separate_ledgers(
        api: ApiClient) -> None:
    """
    The whole 6444.91 comes back, but it comes back on the return ledger: the
    written-premium ledger keeps its figure so the net of the two is zero.

    Written premium and returned premium, however, are tracked on separate ledgers by design: `aggregate_premium_booked` is never reduced when premium is returned; the return lands in `aggregate_return_premium`, and it is the premium declaration that reports the net.

    Design: Difficulty/compensating_invariant/issue_then_cancel_conserves_exposure_and_net_premium
    """
    env = _issue_then_cancel_before_attachment(api)

    assert_money(env["policy_after_issue"]["aggregate_premium_booked"],
                 EXPECTED_TOTAL_PREMIUM,
                 "policy.aggregate_premium_booked after issue")

    certificate = read_certificate(api, env["certificate_id"])
    assert_money(certificate["return_premium_amount"],
                 EXPECTED_FULL_RETURN_PREMIUM,
                 "certificate.return_premium_amount")

    policy = read_policy(api, env["policy_id"])
    assert_amounts(policy, {
        "aggregate_premium_booked": EXPECTED_TOTAL_PREMIUM,
        "aggregate_return_premium": EXPECTED_FULL_RETURN_PREMIUM,
    }, "policy after cancel")

    net_written_premium = (float(policy["aggregate_premium_booked"])
                           - float(policy["aggregate_return_premium"]))
    assert_money(net_written_premium, 0.00, "net written premium")


def test_cancel_leaves_the_written_certificate_count_standing(
        api: ApiClient) -> None:
    """
    The count of certificates that have ever left draft is history, so the
    cancellation does not wind it back to zero.

    On the policy, `aggregate_insured_value_booked` rises by the insured value, `aggregate_premium_booked` rises by the total premium, and `certificates_issued_count` increments by one — that counter records every certificate that has ever left `DRAFT`, so it never falls back when one is later cancelled.

    Design: Difficulty/compensating_invariant/issue_then_cancel_conserves_exposure_and_net_premium
    """
    env = _issue_then_cancel_before_attachment(api)

    assert env["policy_after_issue"]["certificates_issued_count"] == \
        EXPECTED_CERTIFICATES_ISSUED_COUNT, (
            f"expected certificates_issued_count "
            f"{EXPECTED_CERTIFICATES_ISSUED_COUNT} after issue, got "
            f"{env['policy_after_issue']['certificates_issued_count']}"
        )

    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == \
        EXPECTED_CERTIFICATES_ISSUED_COUNT, (
            f"expected certificates_issued_count "
            f"{EXPECTED_CERTIFICATES_ISSUED_COUNT} after cancel, got "
            f"{policy['certificates_issued_count']}"
        )
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked after cancel")


def test_cancel_releases_all_three_accumulation_rows_with_the_cancel_reason(
        api: ApiClient) -> None:
    """
    Not one live exposure row survives the cancellation, and each released row
    names the cancellation as the reason it stopped occupying its scope.

    On success the certificate goes `ISSUED → CANCELLED`, its `ACTIVE` accumulation rows become `RELEASED` with `release_reason` `CERTIFICATE_CANCELLED`, the vessel and both port ledgers fall by exactly what they rose by at issue, the policy's `aggregate_insured_value_booked` falls by the insured value, and the policy's `version` increments.

    Design: Difficulty/compensating_invariant/issue_then_cancel_conserves_exposure_and_net_premium
    """
    env = _issue_then_cancel_before_attachment(api)

    assert_total_count(_entries(api, env["certificate_id"], "ACTIVE"), 0,
                       "live accumulation rows after cancel")

    released, _ = validate_paginated(
        _entries(api, env["certificate_id"], "RELEASED"))
    assert len(released) == EXPECTED_ACCUMULATION_ROW_COUNT, (
        f"expected {EXPECTED_ACCUMULATION_ROW_COUNT} released rows, "
        f"got {len(released)}"
    )
    for scope in ACCUMULATION_SCOPES:
        row = find_row(released, scope_type=scope)
        assert row["release_reason"] == EXPECTED_CANCELLED_RELEASE_REASON, (
            f"the released {scope} entry must carry release_reason "
            f"{EXPECTED_CANCELLED_RELEASE_REASON}, got {row['release_reason']}"
        )
        assert_money(row["amount"], EXPECTED_INSURED_VALUE_CIF,
                     f"released {scope} entry.amount")


# ---------------------------------------------------------------------------
# The surveyor's calendar: minutes taken by an appointment and handed back by
# its cancellation.
# ---------------------------------------------------------------------------
ATTENDANCE_WINDOW_START = "2026-09-08T09:00:00Z"
ATTENDANCE_WINDOW_END = "2026-09-08T11:00:00Z"
EXPECTED_WINDOW_MINUTES = 120
EXPECTED_APPOINTED_ORDER_COUNT = 1
EXPECTED_ORDERS_AFTER_REBOOKING = 2


def _appoint_attendance(api: ApiClient, env: JsonDict,
                        window_start_at: str = ATTENDANCE_WINDOW_START,
                        window_end_at: str = ATTENDANCE_WINDOW_END) -> JsonDict:
    """Appoint the panel surveyor to attend the open claim inside one window."""
    return create_survey_order(
        api, env["claim_id"], env["surveyor_id"],
        window_start_at=window_start_at, window_end_at=window_end_at)


def test_appointment_books_minutes_that_cancellation_hands_straight_back(
        api: ApiClient, surveyor_env: JsonDict) -> None:
    """
    A two-hour attendance takes 120 minutes off the surveyor's calendar, and
    cancelling the order restores the total to the zero it started at.

    Cancellation is a compensating movement: the surveyor's `booked_minutes_total` falls by exactly the order's `window_minutes`, restoring the pre-appointment total.

    Design: Difficulty/compensating_invariant/appoint_then_cancel_conserves_surveyor_booked_minutes
    """
    before = read_surveyor(api, surveyor_env["surveyor_id"], CLAIMS_ADJUSTER)
    assert before["booked_minutes_total"] == 0, (
        f"a fresh panel surveyor must carry no booked minutes, got "
        f"{before['booked_minutes_total']}"
    )

    order = _appoint_attendance(api, surveyor_env)
    assert order["window_minutes"] == EXPECTED_WINDOW_MINUTES, (
        f"expected window_minutes {EXPECTED_WINDOW_MINUTES}, "
        f"got {order['window_minutes']}"
    )

    while_appointed = read_surveyor(api, surveyor_env["surveyor_id"],
                                   CLAIMS_ADJUSTER)
    assert while_appointed["booked_minutes_total"] == EXPECTED_WINDOW_MINUTES, (
        f"expected booked_minutes_total {EXPECTED_WINDOW_MINUTES} while the "
        f"appointment stands, got {while_appointed['booked_minutes_total']}"
    )

    cancelled = get_success_data(
        api.cancel_survey_order(order["id"], CLAIMS_ADJUSTER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["window_minutes"] == EXPECTED_WINDOW_MINUTES, (
        "the cancelled order keeps the window_minutes its reversal was sized on"
    )

    after = read_surveyor(api, surveyor_env["surveyor_id"], CLAIMS_ADJUSTER)
    assert after["booked_minutes_total"] == before["booked_minutes_total"], (
        f"expected booked_minutes_total back at "
        f"{before['booked_minutes_total']} after cancellation, got "
        f"{after['booked_minutes_total']}"
    )


def test_cancelling_the_only_appointment_returns_the_claim_to_opened(
        api: ApiClient, surveyor_env: JsonDict) -> None:
    """
    With nothing else standing on the file, the claim that moved to survey
    ordered walks back to opened when the appointment is cancelled.

    The claim returns `SURVEY_ORDERED → OPENED` only when no other order on that claim remains `APPOINTED`; if another appointment is still standing the claim's `status` does not move.

    Design: Difficulty/compensating_invariant/appoint_then_cancel_conserves_surveyor_booked_minutes
    """
    order = _appoint_attendance(api, surveyor_env)

    ordered = read_claim_file(api, surveyor_env["claim_id"], CLAIMS_ADJUSTER)
    assert ordered["status"] == "SURVEY_ORDERED", (
        f"appointing an attendance must move the claim to SURVEY_ORDERED, "
        f"got {ordered['status']}"
    )

    get_success_data(api.cancel_survey_order(order["id"], CLAIMS_ADJUSTER))

    reopened = read_claim_file(api, surveyor_env["claim_id"], CLAIMS_ADJUSTER)
    assert reopened["status"] == "OPENED", (
        f"cancelling the only standing appointment must return the claim to "
        f"OPENED, got {reopened['status']}"
    )


def test_the_freed_attendance_window_is_immediately_rebookable(
        api: ApiClient, surveyor_env: JsonDict) -> None:
    """
    Because the cancelled order no longer occupies the calendar, the identical
    window books again and the surveyor is loaded with 120 minutes once more.

    Every order of the same surveyor whose `status` is `APPOINTED` or `REPORT_FILED` occupies the calendar — across every claim the surveyor works on, not merely this one — while `CANCELLED` orders are excluded because their minutes have already been given back.

    Design: Difficulty/compensating_invariant/appoint_then_cancel_conserves_surveyor_booked_minutes
    """
    first = _appoint_attendance(api, surveyor_env)
    get_success_data(api.cancel_survey_order(first["id"], CLAIMS_ADJUSTER))

    second = _appoint_attendance(api, surveyor_env)
    assert second["status"] == "APPOINTED"
    assert second["id"] != first["id"]
    assert_instant(second["window_start_at"], first["window_start_at"],
                   "window_start_at")
    assert_instant(second["window_end_at"], first["window_end_at"],
                   "window_end_at")

    loaded = read_surveyor(api, surveyor_env["surveyor_id"], CLAIMS_ADJUSTER)
    assert loaded["booked_minutes_total"] == EXPECTED_WINDOW_MINUTES, (
        f"the rebooked window must load the surveyor with "
        f"{EXPECTED_WINDOW_MINUTES} minutes and no more, got "
        f"{loaded['booked_minutes_total']}"
    )

    rows = assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                              {"surveyor_id": surveyor_env["surveyor_id"]}),
        EXPECTED_ORDERS_AFTER_REBOOKING, "the surveyor's orders")
    find_row(rows, id=first["id"], status="CANCELLED")
    find_row(rows, id=second["id"], status="APPOINTED")

    standing = assert_total_count(
        api.list_survey_orders(CLAIMS_ADJUSTER,
                              {"surveyor_id": surveyor_env["surveyor_id"],
                               "status": "APPOINTED"}),
        EXPECTED_APPOINTED_ORDER_COUNT, "the surveyor's standing appointments")
    assert standing[0]["id"] == second["id"]
