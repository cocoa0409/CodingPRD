"""Boundary precision: inclusive thresholds at driver age, inspection pass
score, and wallet sufficiency (PRD §3.2, §3.4, §2.9).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_permit_holder_headers,
    create_community, create_holder, create_eligible_holder,
    create_full_equipment_lsv, create_draft_registration,
    finalize_inspection_for_registration, create_insurance, deposit,
    get_holder,
    create_inspection_payload, finalize_inspection_payload,
    COMMUNITY_ADMIN, INSPECTOR,
    ApiErrorId,
)


class TestAgeBoundaryExactlyMinVsOneDayUnder:
    def test_exact_min_age_birthday_passes(self):
        """PRD §3.2: "The holder's age is the floor of the whole years between
        `birth_date` and today on the logical clock, and must be at least the
        community's `min_driver_age` — a resident verifying on their exact
        minimum-age birthday passes."

        Design: Difficulty/boundary_precision_check/age_boundary_exactly_min_vs_one_day_under
        """
        community = create_community(name="C-BP1")
        holder_a = create_holder(community["id"], full_name="H A",
                                 birth_date="2010-05-01")  # exact 16th birthday
        verified = validate_success(
            api_client.verify_eligibility(holder_a["id"], COMMUNITY_ADMIN), 200)
        assert verified["eligibility_status"] == "ELIGIBLE"

    def test_one_day_under_min_age_rejected(self):
        """PRD §3.2: "An underage holder is rejected with `ERR_UNDERAGE_DRIVER`
        (HTTP 422)."
        PRD §3.2: "The holder's age is the floor of the whole years between
        `birth_date` and today on the logical clock, and must be at least the
        community's `min_driver_age` — a resident verifying on their exact
        minimum-age birthday passes."

        Design: Difficulty/boundary_precision_check/age_boundary_exactly_min_vs_one_day_under
        """
        community = create_community(name="C-BP1")
        holder_b = create_holder(community["id"], full_name="H B",
                                 birth_date="2010-05-02")  # 15, turns 16 next day
        res = api_client.verify_eligibility(holder_b["id"], COMMUNITY_ADMIN)
        validate_error(res, ApiErrorId.ERR_UNDERAGE_DRIVER, expected_status=422)
        after = get_holder(holder_b["id"])
        assert after["eligibility_status"] == "PENDING_VERIFICATION"


def _setup_bp2():
    """Two DRAFT registrations on two full-equipment LSVs of one ELIGIBLE holder;
    one SCHEDULED inspection each."""
    community = create_community(name="C-BP2")
    holder = create_eligible_holder(community["id"], full_name="H BP2",
                                    birth_date="2010-05-01")
    v1 = create_full_equipment_lsv(holder["id"], seat_count=4)
    v2 = create_full_equipment_lsv(holder["id"], seat_count=4)
    r1 = create_draft_registration(v1["id"], holder["id"], registration_year=2026)
    r2 = create_draft_registration(v2["id"], holder["id"], registration_year=2026)
    i1 = get_success_data(api_client.create_inspection(
        create_inspection_payload(r1["id"]), INSPECTOR))
    i2 = get_success_data(api_client.create_inspection(
        create_inspection_payload(r2["id"], scheduled_at="2026-05-02T10:00:00Z"),
        INSPECTOR))
    return community, holder, r1, r2, i1, i2


class TestInspectionThresholdExactly70Passes:
    def test_exactly_70_00_passes(self):
        """PRD §3.4: "The `passed` flag is true when `total_score` is at least
        70.00 — a score of exactly 70.00 passes."

        Design: Difficulty/boundary_precision_check/inspection_threshold_exactly_70_passes
        """
        _, _, r1, _, i1, _ = _setup_bp2()
        finalized = validate_success(api_client.finalize_inspection(
            i1["id"], finalize_inspection_payload(score=70), INSPECTOR), 200)
        assert finalized["total_score"] == pytest.approx(70.00, abs=0.001)
        assert finalized["passed"] is True
        assert finalized["status"] == "PASSED"

    def test_69_00_fails_and_draft_registration_not_suspended(self):
        """PRD §3.4: "A finalized inspection below the threshold becomes `FAILED` —
        also terminal — and if the referenced registration is currently `ACTIVE`,
        the failure cascades: the registration flips to `SUSPENDED` and every
        `ACTIVE` route pass issued against it flips to `REVOKED`."
        PRD §3.4: "The `passed` flag is true when `total_score` is at least
        70.00 — a score of exactly 70.00 passes."

        Design: Difficulty/boundary_precision_check/inspection_threshold_exactly_70_passes
        """
        _, _, _, r2, _, i2 = _setup_bp2()
        finalized = validate_success(api_client.finalize_inspection(
            i2["id"], finalize_inspection_payload(score=69), INSPECTOR), 200)
        assert finalized["total_score"] == pytest.approx(69.00, abs=0.001)
        assert finalized["passed"] is False
        assert finalized["status"] == "FAILED"
        # FAILED on a DRAFT registration does not suspend it.
        reg = get_success_data(api_client.get_registration(r2["id"], COMMUNITY_ADMIN))
        assert reg["status"] == "DRAFT"


def _setup_bp3():
    """DRAFT LSV registration with PASSED inspection (finalized 19000), ACTIVE
    insurance, ELIGIBLE holder, wallet exactly 19000."""
    community = create_community(name="C-BP3", fleet_program_enabled=True)
    holder = create_eligible_holder(community["id"], full_name="H BP3",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 19000, holder["version"])
    vehicle = create_full_equipment_lsv(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    finalize_inspection_for_registration(registration["id"], score=90)
    create_insurance(holder["id"], vehicle["id"], policy_number="N-BP3")
    registration = get_success_data(
        api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
    return community, holder, vehicle, registration


class TestWalletExactBalanceDebitSucceeds:
    def test_balance_equal_to_total_due_activates(self):
        """PRD §2.9: "Any debit is permitted when the balance equals the amount
        due — equality is sufficient — and is rejected with
        `ERR_INSUFFICIENT_FUNDS` (HTTP 402) when the balance falls short."
        PRD §3.5: "the wallet must hold at least `total_due_cents` — for a fresh
        draft this equals the finalized fee, and a balance exactly equal to the
        amount due is sufficient (otherwise `ERR_INSUFFICIENT_FUNDS`, HTTP 402)."

        Design: Difficulty/boundary_precision_check/wallet_exact_balance_debit_succeeds
        """
        _, holder, _, registration = _setup_bp3()
        hh = make_permit_holder_headers(holder["id"])
        activated = validate_success(
            api_client.activate_registration(registration["id"], hh), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["paid_cents"] == 19000

    def test_exact_debit_drains_wallet_to_zero(self):
        """PRD §2.9: "Each permit holder carries a prepaid `wallet_balance_cents`
        that starts at zero and can never go negative. The wallet is credited by
        holder deposits and by refunds — a cancelled charging reservation returns
        its fee in full, as does each reservation cancelled by a station outage
        cascade. The wallet is debited by the registration activation charge, the
        renewal finalization charge, the charging fee at booking time, and the
        fleet late fine at return time."

        Design: Difficulty/boundary_precision_check/wallet_exact_balance_debit_succeeds
        """
        _, holder, _, registration = _setup_bp3()
        hh = make_permit_holder_headers(holder["id"])
        validate_success(api_client.activate_registration(registration["id"], hh), 200)
        wallet = get_holder(holder["id"])["wallet_balance_cents"]
        assert wallet == 0, f"exact drain to zero is legal: wallet {wallet} != 0"
