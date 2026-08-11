"""Damage claims: liability variants, evaluation order, review loop, referential
guards, settlement reconciliation."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_claim_payout_consistent,
    complete_job,
    create_damage_claim_payload,
    create_incident_payload,
    create_tug,
    create_vessel,
    finalize_invoice,
    get_invoice_for_job,
    review_claim,
    set_clock,
    settle_claim,
    setup_accepted_claim,
    setup_completed_job,
    setup_filed_claim,
    setup_incident,
    start_job,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_tug_captain_headers, make_vessel_agent_headers


class TestLiabilityVariants:
    """Identical claimed amount produces different payouts under PER_INCIDENT vs
    PER_VOYAGE regimes."""

    def _setup_completed_job_with_invoice(self):
        """Job completed on schedule -> provisional invoice 740000. Returns ctx."""
        return setup_completed_job()

    def _file_incident_and_claim(self, ctx, claimed, incident_overrides=None):
        inc_res = api_client.create_incident(
            create_incident_payload(
                ctx["tug"]["id"],
                job_order_id=ctx["job"]["id"],
                **(incident_overrides or {}),
            ),
            make_tug_captain_headers(ctx["tug"]["id"]),
        )
        incident = get_data = validate_success(inc_res, 201)
        claim_res = api_client.create_damage_claim(
            create_damage_claim_payload(
                incident["id"], ctx["vessel"]["id"], claimed
            ),
            make_vessel_agent_headers(ctx["vessel"]["id"]),
        )
        return incident, validate_success(claim_res, 201)

    def test_per_incident_regime_when_no_finalized_invoice(self, api):
        """PRD §3.9: "if the incident's linked job already has a `FINALIZED` invoice
        at filing time, the regime is `PER_VOYAGE`; otherwise — including incidents
        with no linked job — it is `PER_INCIDENT`."
        PRD §3.9: "under `PER_INCIDENT`, it is one half of the involved tug's
        `insured_value_cents`, likewise rounded half-up. In either regime the
        resulting `liability_cap_cents` is never less than 10,000,000 cents."

        Design: Difficulty/dual_variant_calc/liability_per_incident_vs_per_voyage_divergence
        """
        ctx = self._setup_completed_job_with_invoice()
        # Claim filed BEFORE finalization -> PER_INCIDENT.
        incident, claim = self._file_incident_and_claim(ctx, 12000000)
        assert claim["liability_variant"] == "PER_INCIDENT"
        # cap = max(10000000, round(0.5 * 20000000)) = 10000000
        assert claim["liability_cap_cents"] == 10000000
        # deductible = 10% of min(12000000, 10000000) = 1000000; payout = 9000000
        assert claim["deductible_cents"] == 1000000
        assert claim["payout_cents"] == 9000000
        assert_claim_payout_consistent(claim)

    def test_per_voyage_regime_after_finalization(self, api):
        """PRD §3.9: "under `PER_VOYAGE`, the raw cap is twenty times the finalized
        invoice's `total_cents`, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/liability_per_incident_vs_per_voyage_divergence
        """
        ctx = self._setup_completed_job_with_invoice()
        inv = ctx["invoice"]
        finalize_invoice(inv["id"], inv["version"])
        # Claim filed AFTER finalization -> PER_VOYAGE.
        incident, claim = self._file_incident_and_claim(ctx, 12000000)
        assert claim["liability_variant"] == "PER_VOYAGE"
        # cap = max(10000000, 20 * 740000) = 14800000
        assert claim["liability_cap_cents"] == 14800000
        # capped = min(12000000, 14800000) = 12000000; deductible = 1200000;
        # payout = 10800000
        assert claim["deductible_cents"] == 1200000
        assert claim["payout_cents"] == 10800000
        assert_claim_payout_consistent(claim)


class TestLiabilityEvaluationOrder:
    """Pinned order: cap first, then min(claimed, cap), then deductible on capped."""

    def test_cap_applied_before_deductible(self, api):
        """PRD §3.9: "The evaluation order is pinned — cap first, then the lesser of
        claim and cap, then the deductible on the capped figure, then the
        subtraction."

        Design: Difficulty/combinatorial_formula/liability_cap_before_deductible_evaluation_order
        """
        ctx = setup_incident(
            incident_overrides={
                "incident_type": "GEAR_FAILURE",
                "severity": "MINOR",
                "occurred_at": "2026-06-01T09:30:00Z",
                "description": "Tow line abrasion",
            }
        )
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        res = api_client.create_damage_claim(
            create_damage_claim_payload(
                ctx["incident"]["id"], vessel["id"], 12000000
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        claim = validate_success(res, 201)
        assert claim["liability_cap_cents"] == 10000000
        # deductible is 10% of the CAPPED amount (10000000), not of the claimed
        # 12000000 — the alternative order would yield 1200000.
        assert claim["deductible_cents"] == 1000000
        assert claim["payout_cents"] == 9000000

    def test_payout_equals_capped_minus_deductible(self, api):
        """PRD §3.9: "The `deductible_cents` is ten percent of the smaller of the
        claimed amount and the cap, rounded half-up to whole cents, and the
        `payout_cents` is that same capped amount minus the deductible."

        Design: Difficulty/combinatorial_formula/liability_cap_before_deductible_evaluation_order
        """
        ctx = setup_incident(
            incident_overrides={
                "incident_type": "GEAR_FAILURE",
                "severity": "MINOR",
                "occurred_at": "2026-06-01T09:30:00Z",
                "description": "Tow line abrasion",
            }
        )
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        res = api_client.create_damage_claim(
            create_damage_claim_payload(
                ctx["incident"]["id"], vessel["id"], 12000000
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        claim = validate_success(res, 201)
        capped = min(claim["claimed_amount_cents"], claim["liability_cap_cents"])
        assert claim["payout_cents"] == capped - claim["deductible_cents"]


class TestClaimReviewLoop:
    """FILED -> UNDER_REVIEW -> FILED -> UNDER_REVIEW -> ACCEPTED -> SETTLED."""

    def _setup(self):
        return setup_filed_claim(claimed_amount_cents=5000000)

    def test_review_request_info_loops_back_to_filed(self, api):
        """PRD §3.9: "`START_REVIEW` opens the file, moving `FILED` →
        `UNDER_REVIEW`; `REQUEST_INFO` sends it back for more evidence,
        `UNDER_REVIEW` → `FILED`."

        Design: Difficulty/non_linear_state_machine/damage_claim_review_request_info_loop
        """
        ctx = self._setup()
        claim = ctx["claim"]
        assert claim["status"] == "FILED"
        s1 = review_claim(claim["id"], "START_REVIEW")
        assert s1["status"] == "UNDER_REVIEW"
        s2 = review_claim(claim["id"], "REQUEST_INFO", reviewer_notes="Need survey report")
        assert s2["status"] == "FILED"

    def test_full_review_loop_to_settled(self, api):
        """PRD §3.9: "`ACCEPT` approves liability, `UNDER_REVIEW` → `ACCEPTED`;
        `DENY` rejects it outright, `UNDER_REVIEW` → `DENIED`."
        PRD §3.9: "Settlement closes the loop: settling an `ACCEPTED` claim moves
        it to `SETTLED` and recomputes the vessel's outstanding balance."
        PRD §2.5: "`version`, an integer that increments by one on every mutation
        of the resource."

        Design: Difficulty/non_linear_state_machine/damage_claim_review_request_info_loop
        """
        ctx = self._setup()
        claim = ctx["claim"]
        review_claim(claim["id"], "START_REVIEW")
        review_claim(claim["id"], "REQUEST_INFO", reviewer_notes="Need survey report")
        review_claim(claim["id"], "START_REVIEW")
        s4 = review_claim(claim["id"], "ACCEPT")
        assert s4["status"] == "ACCEPTED"
        s5 = settle_claim(claim["id"])
        assert s5["status"] == "SETTLED"
        # cap = 10000000; capped = 5000000; deductible = 500000; payout = 4500000
        assert s5["payout_cents"] == 4500000
        # Version: 1 at create, +1 per mutation. Mutations: START_REVIEW,
        # REQUEST_INFO, START_REVIEW, ACCEPT, SETTLE = 5 -> version 6.
        assert s5["version"] == 6


class TestClaimReferentialGuards:
    def test_claim_on_resolved_incident_returns_incident_already_resolved(self, api):
        """PRD §3.9: "the incident must still be open — `REPORTED` or
        `UNDER_INVESTIGATION` — with a claim against a `RESOLVED` incident rejected
        as `ERR_INCIDENT_ALREADY_RESOLVED`."

        Design: Corner/validations/claim_on_resolved_incident_returns_incident_already_resolved
        """
        ctx = setup_incident(
            incident_overrides={
                "incident_type": "CONTACT_DAMAGE",
                "severity": "MINOR",
                "occurred_at": "2026-06-01T09:00:00Z",
                "description": "Fender scuff",
            }
        )
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        api_client.resolve_incident(
            ctx["incident"]["id"],
            {"resolution_notes": "No damage found"},
            TEST_USERS["marine_surveyor_headers"],
        )
        res = api_client.create_damage_claim(
            create_damage_claim_payload(
                ctx["incident"]["id"], vessel["id"], 500000
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_INCIDENT_ALREADY_RESOLVED")

    def test_second_claim_same_incident_returns_claim_already_filed(self, api):
        """PRD §3.9: "an incident may carry at most one claim, a second filing
        rejected with `ERR_CLAIM_ALREADY_FILED`."

        Design: Corner/validations/second_claim_same_incident_returns_claim_already_filed
        """
        ctx = setup_filed_claim(claimed_amount_cents=500000)
        res = api_client.create_damage_claim(
            create_damage_claim_payload(
                ctx["incident"]["id"], ctx["vessel"]["id"], 700000
            ),
            make_vessel_agent_headers(ctx["vessel"]["id"]),
        )
        validate_error(res, "ERR_CLAIM_ALREADY_FILED")


class TestSettleReducesOutstanding:
    def test_settle_reduces_vessel_outstanding(self, api):
        """PRD §3.9: "settling an `ACCEPTED` claim moves it to `SETTLED` and
        recomputes the vessel's outstanding balance, because a settled payout now
        counts against what the vessel owes."
        PRD §3.9: "floored at zero."

        Design: Corner/cross_cutting_layers/settle_reduces_vessel_outstanding
        """
        # Job completed on schedule -> provisional invoice 740000 on the vessel.
        ctx = setup_completed_job()
        # MINOR incident on the same tug, claim 5000000 -> payout 4500000.
        inc_res = api_client.create_incident(
            create_incident_payload(
                ctx["tug"]["id"],
                job_order_id=ctx["job"]["id"],
                incident_type="CONTACT_DAMAGE",
                severity="MINOR",
                occurred_at="2026-06-01T09:30:00Z",
                description="Hull scrape during docking",
            ),
            make_tug_captain_headers(ctx["tug"]["id"]),
        )
        incident = validate_success(inc_res, 201)
        claim_res = api_client.create_damage_claim(
            create_damage_claim_payload(
                incident["id"], ctx["vessel"]["id"], 5000000
            ),
            make_vessel_agent_headers(ctx["vessel"]["id"]),
        )
        claim = validate_success(claim_res, 201)
        review_claim(claim["id"], "START_REVIEW")
        review_claim(claim["id"], "ACCEPT")
        settled = settle_claim(claim["id"])
        assert settled["status"] == "SETTLED"
        assert settled["payout_cents"] == 4500000
        vessel = validate_success(
            api_client.get_vessel(
                ctx["vessel"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        # max(0, 740000 - 4500000) = 0
        assert vessel["outstanding_billed_cents"] == 0
