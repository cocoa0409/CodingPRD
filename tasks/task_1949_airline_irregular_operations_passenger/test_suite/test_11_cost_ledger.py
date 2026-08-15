"""The per-event append-only cost ledger: accrual vs settled views,
compensating reversals, ledger row shape, and exactly-once posting."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_disrupted_booking, setup_committed_case,
    issue_voucher, cost_summary, cost_entries,
    elect, process_election,
    assert_cost_entry, assert_cost_summary,
)

AGENT = TEST_USERS["agent_headers"]
FIN = TEST_USERS["finance_headers"]


class TestEventCostAccrualVsSettled:
    """Hotel 15000 + meal 4500 issued; hotel redeemed at 13200. The two views
    diverge on the identical ledger."""

    def _setup(self):
        ctx = setup_committed_case(
            event_code="MECH-2", event_state="RECOVERY", cost_cap_cents=100000,
            passenger_overrides={"full_name": "Bob B", "contact_email": "bob@x.com"},
            flight_overrides={"flight_number": "OC300",
                              "sched_dep_utc": "2026-08-10T10:00:00Z",
                              "sched_arr_utc": "2026-08-10T11:00:00Z"},
            booking_overrides={"fare_cents": 20000},
            extra_flights=[{"flight_number": "OC400",
                            "sched_dep_utc": "2026-08-10T18:00:00Z",
                            "sched_arr_utc": "2026-08-10T19:00:00Z"}])
        # 12h window: HOTEL nights = max(1, ceil(12/24)) = 1 -> 15000;
        # MEAL meals = min(3, floor(12/4)) = 3 -> 4500.
        hotel = issue_voucher(ctx["booking"]["id"], "HOTEL",
                              check_in_date="2026-08-10")
        issue_voucher(ctx["booking"]["id"], "MEAL")
        return ctx, hotel

    def test_issued_vouchers_count_at_face_in_accrual_only(self, api):
        """PRD §2.9: "An issued voucher therefore counts at its face value
        against the accrual view immediately, and at its redeemed amount against
        the settled view only once redeemed."
        PRD §3.6: "Every voucher records the `booking_id` and the
        `disruption_event_id` copied from the booking's reaccommodation case,
        starts in `voucher_status` `ISSUED`, and posts an `ACCRUAL` cost entry
        at its `face_value_cents` to the event ledger, after which the event's
        accrual total reflects the commitment."

        Design: Difficulty/dual_variant_calc/event_cost_accrual_vs_settled
        """
        ctx, hotel = self._setup()
        summary = cost_summary(ctx["event"]["id"])
        assert_cost_summary(summary)
        assert summary["accrual_total_cents"] == 19500, (
            f"hotel 15000 + meal 4500 at face, got {summary['accrual_total_cents']}")
        assert summary["settled_total_cents"] == 0, "nothing redeemed yet"

    def test_redeem_moves_settled_view_but_not_accrual(self, api):
        """PRD §2.9: "The committed-cost view, `accrual_total_cents`, is the sum
        of `amount_cents` over the event's `ACCRUAL` entries plus the sum over
        its `REVERSAL` entries; because every reversal recorded in this system
        targets an accrual, voiding or expiring a voucher reduces the accrual
        view only. The actual-cash view, `settled_total_cents`, is the sum over
        `SETTLEMENT` entries (plus any reversals targeting settlements, which do
        not occur in practice), so voids never move the settled view."
        PRD §3.6: "Redeeming a voucher — permitted only while it is `ISSUED`,
        otherwise `ERR_VOUCHER_NOT_OPEN` (HTTP 409) — takes the
        `actual_amount_cents` actually spent, which must be zero or greater (a
        negative amount is `ERR_INVALID_REQUEST`), records it in
        `redeemed_amount_cents`, moves the voucher to `REDEEMED`, and posts a
        `SETTLEMENT` entry at that amount against the `VOUCHER` source."

        Design: Difficulty/dual_variant_calc/event_cost_accrual_vs_settled
        """
        ctx, hotel = self._setup()
        redeemed = validate_success(api_client.redeem_voucher(
            hotel["id"], {"actual_amount_cents": 13200}, FIN))
        assert redeemed["voucher_status"] == "REDEEMED"
        assert redeemed["redeemed_amount_cents"] == 13200

        summary = cost_summary(ctx["event"]["id"])
        assert summary["accrual_total_cents"] == 19500, "redemption does not touch accrual"
        assert summary["settled_total_cents"] == 13200
        assert summary["accrual_total_cents"] != summary["settled_total_cents"], (
            "the two variants diverge on identical ledger rows")


class TestAccrualInvariantIssueVoidPair:
    def _setup(self):
        return setup_disrupted_booking(event_code="MECH-19", event_state="RECOVERY",
                                       cost_cap_cents=100000)

    def test_issue_then_void_restores_accrual_total(self, api):
        """PRD §3.6: "Voiding an `ISSUED` voucher — same state gate, same error
        — moves it to `VOIDED` and posts a compensating `REVERSAL` entry of
        minus the `face_value_cents`."
        PRD §2.9: "because every reversal recorded in this system targets an
        accrual, voiding or expiring a voucher reduces the accrual view only."

        Design: Difficulty/compensating_invariant/accrual_invariant_issue_void_pair
        """
        ctx = self._setup()
        event_id = ctx["event"]["id"]
        assert cost_summary(event_id)["accrual_total_cents"] == 0

        voucher = issue_voucher(ctx["booking"]["id"], "TRANSPORT")
        assert cost_summary(event_id)["accrual_total_cents"] == 5000

        validate_success(api_client.void_voucher(voucher["id"], FIN))
        after = cost_summary(event_id)
        assert after["accrual_total_cents"] == 0, (
            "issue + void conserves the accrual total")
        assert after["settled_total_cents"] == 0, "voids never move the settled view"

    def test_void_posts_compensating_reversal_row(self, api):
        """PRD §2.9: "The `entry_kind` is one of `ACCRUAL` (committed cost),
        `SETTLEMENT` (actual cash), or `REVERSAL` (a compensating entry);
        `amount_cents` is signed, and reversal amounts are negative."
        PRD §3.6: "posts a compensating `REVERSAL` entry of minus the
        `face_value_cents`."

        Design: Difficulty/compensating_invariant/accrual_invariant_issue_void_pair
        """
        ctx = self._setup()
        voucher = issue_voucher(ctx["booking"]["id"], "TRANSPORT")
        validate_success(api_client.void_voucher(voucher["id"], FIN))

        entries = cost_entries(ctx["event"]["id"])
        assert len(entries) == 2
        rows = sorted(((e["entry_kind"], e["amount_cents"]) for e in entries))
        assert rows == [("ACCRUAL", 5000), ("REVERSAL", -5000)]
        for entry in entries:
            assert_cost_entry(entry)
            assert entry["source_type"] == "VOUCHER"
            assert entry["source_id"] == voucher["id"]


def test_cost_entry_rows_are_append_only_shape(api):
    """PRD §2.4: "Two resources are append-only ledger rows and carry only `id`
    and `created_at`: a `CostEntry` and a `CommunicationLog` have neither
    `updated_at` nor `version`, and both fields are absent from their
    representations."
    PRD §2.9: "Ledger rows are never updated or deleted; as append-only rows
    they carry no `updated_at` and no `version`."

    Design: Corner/entities/cost_entry_append_only_immutability
    """
    ctx = setup_disrupted_booking(event_code="MECH-C1", event_state="RECOVERY",
                                  cost_cap_cents=100000)
    voucher = issue_voucher(ctx["booking"]["id"], "TRANSPORT")
    entries = cost_entries(ctx["event"]["id"])
    assert len(entries) == 1
    entry = entries[0]
    assert_cost_entry(entry)
    assert "updated_at" not in entry and "version" not in entry
    assert entry["entry_kind"] == "ACCRUAL"
    assert entry["amount_cents"] == 5000
    assert entry["source_type"] == "VOUCHER"
    assert entry["source_id"] == voucher["id"]


def test_processing_an_election_twice_is_rejected_and_posts_once(api):
    """PRD §3.7: "A `FinanceProcessor` then processes the election; processing
    requires `PENDING`, otherwise `ERR_ELECTION_NOT_PENDING` (HTTP 409).
    Processing a refund election posts `REFUND` accrual and settlement entries
    at the snapshotted refund amount plus `COMPENSATION` accrual and settlement
    entries at the snapshotted compensation amount — the refund snapshot is paid
    only for a `REFUND` election — while processing a credit election posts a
    `CREDIT` accrual entry at the snapshotted credit amount plus the
    `COMPENSATION` accrual and settlement entries; entries whose amount would be
    zero cents are not posted."

    Design: Corner/state_machines/election_process_twice_rejected
    """
    ctx = setup_disrupted_booking(event_code="MECH-C5")
    election = elect(ctx["booking"]["id"], "REFUND")
    processed = process_election(election["id"])
    assert processed["election_status"] == "PROCESSED"

    res = api_client.process_refund_election(election["id"], FIN)
    validate_error(res, ApiErrorId.ERR_ELECTION_NOT_PENDING)

    entries = cost_entries(ctx["event"]["id"])
    # fare 12000 refund (no FLOWN segments) + 25000 compensation (900 km tier).
    rows = sorted((e["source_type"], e["entry_kind"], e["amount_cents"]) for e in entries)
    assert rows == [
        ("COMPENSATION", "ACCRUAL", 25000),
        ("COMPENSATION", "SETTLEMENT", 25000),
        ("REFUND", "ACCRUAL", 12000),
        ("REFUND", "SETTLEMENT", 12000),
    ], f"exactly four entries, posted once: got {rows}"
