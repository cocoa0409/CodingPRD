"""Compensating invariants: district principal conservation across
certify/reject; tranche credit conservation across close/rescind."""
from test_helpers import (
    api_client,
    create_active_community,
    create_and_close_lot,
    create_certified_payment,
    create_district_with_advances,
    create_offered_lot,
    create_requested_payment,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestDistrictPrincipalConservation:
    """Invariant: advance_principal_cents == outstanding_principal_cents +
    sum of certified_principal_cents over CERTIFIED-or-PAID payments. Certify
    debits; the compensating reject restores."""

    def _setup_certified(self):
        community = create_active_community("Ledger Lakes", 50)
        district, advances = create_district_with_advances(
            community["id"],
            [(6000000, "2026-01-01T00:00:00Z"), (4000000, "2026-03-01T00:00:00Z")],
            district_name="CFD 1",
        )
        payment = create_requested_payment(district["id"], 500000)
        return district, advances, payment

    def test_certify_debits_outstanding_and_allocates_fifo(self):
        """PRD §3.6: "Certification stamps `certified_at`, debits the district's `outstanding_principal_cents` by the certified principal, and credits `certified_interest_to_date_cents` by the certified interest. Disbursement moves a `CERTIFIED` payment to `PAID` under a `DeclarantController` and requires the district's `available_funds_cents` to cover the payment's `amount_cents` (`ERR_INSUFFICIENT_DISTRICT_FUNDS`); it stamps `paid_at` and draws the funds down."
        PRD §3.6: "The waterfall then allocates interest-first globally and principal to advances first-in-first-out, ordered by `advance_date` ascending with ties broken by `created_at` ascending: each advance's `reimbursed_principal_cents` grows until it reaches its `amount_cents` (becoming `REIMBURSED`), and overflow rolls to the next advance. Certification stamps `certified_at`, debits the district's `outstanding_principal_cents` by the certified principal, and credits `certified_interest_to_date_cents` by the certified interest."

        Design: Difficulty/compensating_invariant/district_principal_conservation
        """
        district, advances, payment = self._setup_certified()
        certified = get_success_data(api_client.certify_payment(payment["id"], DIRECTOR))
        assert certified["certified_interest_cents"] == 133000
        assert certified["certified_principal_cents"] == 367000

        read = get_success_data(api_client.get_district(district["id"], CTRL))
        assert read["advance_principal_cents"] == 10000000
        assert read["outstanding_principal_cents"] == 9633000
        assert read["certified_interest_to_date_cents"] == 133000
        # Conservation mid-flight: 10000000 == 9633000 + 367000.
        assert read["advance_principal_cents"] == (
            read["outstanding_principal_cents"] + certified["certified_principal_cents"]
        )

        adv1 = get_success_data(api_client.get_advance(advances[0]["id"], CTRL))
        assert adv1["reimbursed_principal_cents"] == 367000, (
            f"FIFO allocates principal to the oldest advance first, got "
            f"{adv1['reimbursed_principal_cents']}"
        )
        assert adv1["status"] == "PARTIALLY_REIMBURSED"

    def test_compensating_reject_restores_invariant(self):
        """PRD §3.6: "Rejection is available from `REQUESTED` with no unwind, and from `CERTIFIED` with a full compensating unwind: the district's `outstanding_principal_cents` is restored by the certified principal, `certified_interest_to_date_cents` is reduced by the certified interest, and the advance allocations are unwound in reverse first-in-first-out order — the most recent allocations come off first.".

        Design: Difficulty/compensating_invariant/district_principal_conservation
        """
        district, advances, payment = self._setup_certified()
        get_success_data(api_client.certify_payment(payment["id"], DIRECTOR))
        rejected = get_success_data(api_client.reject_payment(payment["id"], DIRECTOR))
        assert rejected["status"] == "REJECTED"

        read = get_success_data(api_client.get_district(district["id"], CTRL))
        assert read["outstanding_principal_cents"] == 10000000
        assert read["certified_interest_to_date_cents"] == 0
        # Conservation restored: 10000000 == 10000000 + 0.
        assert read["advance_principal_cents"] == read["outstanding_principal_cents"]

        adv1 = get_success_data(api_client.get_advance(advances[0]["id"], CTRL))
        assert adv1["reimbursed_principal_cents"] == 0
        assert adv1["status"] == "OUTSTANDING"


class TestTrancheCreditConservation:
    """Invariant: sum of lots_credited over all tranches == count of CLOSED
    closings of the agreement. Rescind debits exactly the credited tranche; the
    transition_stage ratchet is exempt (does not regress)."""

    def _setup_two_closed(self):
        scenario = setup_active_agreement_scenario(
            total_planned_units=4,
            planned_lot_count=4,
            total_lots_committed=2,
            tranches=[("2026-06-30T00:00:00Z", 2)],
            community_name="Conserve Court",
            earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(scenario["phase"]["id"], "L1")
        lot2 = create_offered_lot(scenario["phase"]["id"], "L2")
        set_clock("2026-06-01T00:00:00Z")
        cl1 = create_and_close_lot(scenario["agreement"]["id"], lot1["id"])
        cl2 = create_and_close_lot(scenario["agreement"]["id"], lot2["id"])
        return scenario, lot2, cl2

    def test_fully_credited_tranche_satisfied_at_parity(self):
        """PRD §3.4: "The waterfall picks the eligible tranche with the earliest `due_date`, breaking ties by ascending `tranche_no`, increments its `lots_credited` by one, records it as the closing's `credited_tranche_id`, and flips it to `SATISFIED` when the credit completes its count. When no tranche is eligible, the closing is an over-takedown: `credited_tranche_id` is null and `is_surplus` is true."
        PRD §2.7: "The stage mapping, evaluated on the rounded percentage with inclusive thresholds, is: at least 25.00 percent → `OWNER_REPRESENTATION`; at least 50.00 percent → `PARITY`; at least 75.00 percent → `OWNER_MAJORITY`; otherwise `DECLARANT_CONTROL`.".

        Design: Difficulty/compensating_invariant/tranche_credit_conservation
        """
        scenario, _, _ = self._setup_two_closed()
        tranche = get_success_data(api_client.get_tranche(scenario["tranches"][0]["id"], CTRL))
        assert tranche["lots_credited"] == 2
        assert tranche["status"] == "SATISFIED"
        community = get_success_data(api_client.get_community(scenario["community"]["id"], EXEC))
        assert community["closed_unit_count"] == 2
        assert community["transition_stage"] == "PARITY", (
            f"2/4 units = 50.00 pct -> PARITY, got {community['transition_stage']}"
        )

    def test_rescind_debits_credit_and_preserves_stage_ratchet(self):
        """PRD §3.4: "Rescission of a `CLOSED` closing is a `DeclarantExecutive` action available only within thirty days of the `closing_date` — later attempts are rejected `ERR_RESCISSION_WINDOW_EXPIRED` — and it moves the closing to `RESCINDED` and unwinds the close: the credited tranche, when `credited_tranche_id` is set, loses one credit and, if it had been `SATISFIED`, reverts to `OPEN` when the logical clock is still on or before its `due_date` and to `MISSED` when the due date has passed; `closed_unit_count`, `closed_lot_count`, `lots_closed_count`, and `total_lots_purchased` each decrement and `closed_unit_pct` is recomputed; the lot returns to `OFFERED`; and the resident, if any, remains an `OWNER`.".
        PRD §2.7: "The stage is a ratchet: it advances when a closing crosses a threshold and it never regresses, including when a closing is rescinded and the closed-unit percentage falls. Governance powers key off this stage throughout §3 — budget adoption paths, assessment cap override ratification, the declarant subsidy election, and the end of declarant authority are all expressed in terms of it."

        Design: Difficulty/compensating_invariant/tranche_credit_conservation
        """
        scenario, lot2, cl2 = self._setup_two_closed()
        tranche_id = scenario["tranches"][0]["id"]
        # Clock 2026-06-01 is within 30 days of the closing_date.
        rescinded = get_success_data(api_client.rescind_closing(cl2["id"], EXEC))
        assert rescinded["status"] == "RESCINDED"

        tranche = get_success_data(api_client.get_tranche(tranche_id, CTRL))
        assert tranche["lots_credited"] == 1
        assert tranche["status"] == "OPEN", (
            f"2026-06-01 <= due_date 2026-06-30, so SATISFIED reverts to OPEN, "
            f"got {tranche['status']}"
        )

        agreement = get_success_data(api_client.get_agreement(scenario["agreement"]["id"], CTRL))
        assert agreement["lots_closed_count"] == 1

        community = get_success_data(api_client.get_community(scenario["community"]["id"], EXEC))
        assert community["closed_unit_count"] == 1
        assert float(community["closed_unit_pct"]) == 25.00
        assert community["transition_stage"] == "PARITY", (
            f"the stage ratchet must not regress on rescission, got "
            f"{community['transition_stage']}"
        )

        lot = get_success_data(api_client.get_lot(lot2["id"], EXEC))
        assert lot["status"] == "OFFERED"
