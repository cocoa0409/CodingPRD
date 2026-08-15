"""Statute-of-limitations boundaries and lazy-expiry cascades (PRD §2.5, §2.8, §3.3–§3.4).

The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD §2.5), so cases
injured on 2023-08-01 have sol_date == 2026-08-01: writes are allowed on the
default clock and expire once the clock advances one day.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    factories,
    get_case,
    get_case_version,
    get_lien,
    get_settlement,
    set_clock,
    setup_case_with_lien,
    setup_settlement_offered,
    validate_error,
    validate_success,
)

SPEC = TEST_USERS["specialist_headers"]
SUP1 = TEST_USERS["supervisor_headers"]


class TestSolDateBoundary:
    def test_settlement_create_on_sol_date_allowed(self, api):
        """PRD §2.5: "Before any call to the clock endpoint, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time."
        PRD §3.2: "the server computes `sol_date` as the same calendar date three years after the `injury_date` — the statute-of-limitations date that governs every later deadline on the case."

        Design: Difficulty/boundary_precision_check/sol_date_exact_boundary
        """
        # Injury 2023-08-01 -> sol_date 2026-08-01; the default clock reads
        # exactly that date, and expiry is strictly-greater, so opening the
        # negotiation on the sol date itself is allowed.
        ctx = setup_case_with_lien(
            medicaid_id="M-SB-A", injury_date="2023-08-01",
            claims=[("2023-08-10", 100000)],
        )
        case_id = ctx["case"]["id"]
        settlement = validate_success(
            api.create_settlement(
                case_id,
                factories.settlement_payload(
                    get_case_version(case_id),
                    gross_amount_cents=500000, attorney_fee_pct=0.20,
                    litigation_costs_cents=50000, offered_by="INSURER",
                ),
                SPEC,
            ),
            201,
        )
        assert settlement["status"] == "OFFERED"

    def test_settlement_create_one_day_past_sol_expires_case(self, api):
        """PRD §2.5: "When the logical calendar has advanced past a case's `sol_date`, the next write action on the case or its lien and settlement children moves the case to `SOL_EXPIRED`, moves every lien of the case still in `FILED` or `AMENDED` status to `EXPIRED`, and moves every settlement of the case still in `OFFERED` or `COUNTERED` status to `REJECTED`. Four operations gate explicitly on the limitations window — opening a settlement negotiation, accepting a settlement, amending a lien, and posting a payment — and each is rejected with `ERR_SOL_EXPIRED` (HTTP 409) at the moment the cascade fires."

        Design: Difficulty/boundary_precision_check/sol_date_exact_boundary
        """
        ctx = setup_case_with_lien(
            medicaid_id="M-SB-B", injury_date="2023-08-01",
            claims=[("2023-08-10", 100000)],
        )
        case_id = ctx["case"]["id"]
        set_clock("2026-08-02T00:00:00Z")  # one day past sol_date 2026-08-01
        resp = api.create_settlement(
            case_id,
            factories.settlement_payload(
                get_case_version(case_id),
                gross_amount_cents=500000, attorney_fee_pct=0.20,
                litigation_costs_cents=50000, offered_by="INSURER",
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_SOL_EXPIRED)
        assert get_case(case_id)["status"] == "SOL_EXPIRED", (
            "The lazy expiry cascade must fire on the rejected write"
        )
        assert get_lien(ctx["lien"]["id"])["status"] == "EXPIRED"


class TestTemporalBeatsConstraint:
    def test_sol_expired_reported_before_negotiation_in_progress(self, api):
        """PRD §2.8: "A request therefore surfaces an expired limitations date before a uniqueness conflict, and never reports a stale version for a request that already fails an earlier rule."

        Design: Difficulty/priority_pair_validation_conflict/settlement_create_temporal_beats_constraint
        """
        # Case with an OFFERED settlement already on it; the clock then moves
        # one day past sol_date. The second create violates both the temporal
        # gate and the one-open-negotiation constraint; the temporal error is
        # earlier in the fixed evaluation order.
        ctx = setup_settlement_offered(
            injury_date="2023-08-01", claims=[("2023-08-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000, offered_by="INSURER",
        )
        case_id = ctx["case"]["id"]
        set_clock("2026-08-02T00:00:00Z")
        resp = api.create_settlement(
            case_id,
            factories.settlement_payload(
                get_case_version(case_id),
                gross_amount_cents=600000, attorney_fee_pct=0.20,
                litigation_costs_cents=50000, offered_by="STATE",
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_SOL_EXPIRED)

    def test_lazy_expiry_cascades_despite_rejected_create(self, api):
        """PRD §2.5: "When the logical calendar has advanced past a case's `sol_date`, the next write action on the case or its lien and settlement children moves the case to `SOL_EXPIRED`, moves every lien of the case still in `FILED` or `AMENDED` status to `EXPIRED`, and moves every settlement of the case still in `OFFERED` or `COUNTERED` status to `REJECTED`."

        Design: Difficulty/priority_pair_validation_conflict/settlement_create_temporal_beats_constraint
        """
        ctx = setup_settlement_offered(
            injury_date="2023-08-01", claims=[("2023-08-10", 100000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000, offered_by="INSURER",
        )
        case_id = ctx["case"]["id"]
        set_clock("2026-08-02T00:00:00Z")
        validate_error(
            api.create_settlement(
                case_id,
                factories.settlement_payload(
                    get_case_version(case_id),
                    gross_amount_cents=600000, attorney_fee_pct=0.20,
                    litigation_costs_cents=50000, offered_by="STATE",
                ),
                SPEC,
            ),
            ApiErrorId.ERR_SOL_EXPIRED,
        )
        assert get_case(case_id)["status"] == "SOL_EXPIRED"
        assert get_lien(ctx["lien"]["id"])["status"] == "EXPIRED"
        assert get_settlement(ctx["settlement"]["id"])["status"] == "REJECTED"


class TestLazyExpiryCascade:
    def test_lien_amend_past_sol_fires_full_cascade(self, api):
        """PRD §2.5: "When the logical calendar has advanced past a case's `sol_date`, the next write action on the case or its lien and settlement children moves the case to `SOL_EXPIRED`, moves every lien of the case still in `FILED` or `AMENDED` status to `EXPIRED`, and moves every settlement of the case still in `OFFERED` or `COUNTERED` status to `REJECTED`. Four operations gate explicitly on the limitations window — opening a settlement negotiation, accepting a settlement, amending a lien, and posting a payment — and each is rejected with `ERR_SOL_EXPIRED` (HTTP 409) at the moment the cascade fires."

        Design: Corner/state_machines/sol_lazy_expiry_cascades_to_lien_and_settlement
        """
        # Offer tabled at the default clock on the sol date itself; the amend
        # lands at +15 days, outside the closed 14-day freeze, so only the
        # limitations gate fails.
        ctx = setup_settlement_offered(
            injury_date="2023-08-01", claims=[("2023-08-10", 200000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000, offered_by="INSURER",
        )
        lien = ctx["lien"]
        set_clock("2026-08-16T00:00:00Z")
        resp = api.amend_lien(
            lien["id"],
            factories.amend_lien_payload(lien["version"], new_amount_cents=180000),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_SOL_EXPIRED)
        assert get_case(ctx["case"]["id"])["status"] == "SOL_EXPIRED"
        assert get_lien(lien["id"])["status"] == "EXPIRED"
        assert get_settlement(ctx["settlement"]["id"])["status"] == "REJECTED"


class TestStateCheckBeatsSolTemporal:
    def test_amend_on_released_lien_past_sol_returns_not_amendable(self, api):
        """PRD §3.3: "Amendment is defined from `FILED` to `AMENDED` and again from `AMENDED` to `AMENDED`; attempting it on a lien in `SATISFIED`, `RELEASED`, or `EXPIRED` status is rejected with `ERR_LIEN_NOT_AMENDABLE` (HTTP 409)."
        PRD §2.8: "Validation failures are reported against a fixed evaluation order, so the error a client receives is always the earliest applicable check rather than an arbitrary one."

        Design: Corner/validations/lien_amend_state_beats_sol_temporal
        """
        # Injury 2023-01-01 -> sol_date 2026-01-01, already behind the default
        # clock; the lien has been RELEASED, so the state gate (earlier in the
        # fixed order) reports before the limitations gate.
        ctx = setup_case_with_lien(
            medicaid_id="M-PS-1", injury_date="2023-01-01",
            claims=[("2023-01-10", 100000)],
        )
        lien = ctx["lien"]
        validate_success(api.release_lien(lien["id"], SUP1), 200)
        resp = api.amend_lien(
            lien["id"],
            factories.amend_lien_payload(
                get_lien(lien["id"])["version"], new_amount_cents=90000
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_NOT_AMENDABLE)
        after = get_lien(lien["id"])
        assert after["status"] == "RELEASED"
        assert after["lien_amount_cents"] == 100000
