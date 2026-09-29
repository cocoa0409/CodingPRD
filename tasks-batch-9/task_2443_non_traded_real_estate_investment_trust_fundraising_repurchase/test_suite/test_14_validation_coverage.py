"""Breadth coverage of the PRD's gates: investment floors, per-class closure,
share-sufficiency netting, suitability, valuation timing, load ceilings and the
order in which existence and ownership are judged.

Every test builds the whole of its own state: the service restarts against an
empty database before each test and its logical clock reads 2026-08-01T00:00:00Z
(PRD §2.6) until the test moves it.
"""

from test_helpers import (
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_total_count,
    investor_payload,
    make_broker_dealer_rep_headers,
    make_investor_user_headers,
    repurchase_request_payload,
    subscription_payload,
)
from test_helpers.fixtures import ReitWorld

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


# ─── shared setup builders (PRD §3.1–§3.3 chains) ──────────────────────


def _unfunded_platform(world: ReitWorld, name: str) -> dict:
    """An offering with one zero-load class I and no subscriptions at all."""
    offering = world.offering(
        name=name,
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
    )
    share_class = world.share_class(
        offering["id"],
        class_code="I",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    return {"offering_id": offering["id"], "share_class_id": share_class["id"]}


def _zero_load_platform(
    world: ReitWorld,
    name: str,
    minimum_offering_amount_cents: int,
    firm_name: str,
    crd_number: str,
    **offering_overrides,
) -> dict:
    """An EFFECTIVE offering, one zero-load class I, one ACTIVE selling agreement."""
    offering = world.offering(
        name=name,
        minimum_offering_amount_cents=minimum_offering_amount_cents,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        **offering_overrides,
    )
    share_class = world.share_class(
        offering["id"],
        class_code="I",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(firm_name=firm_name, crd_number=crd_number)
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "broker_dealer_id": firm["id"],
        "selling_agreement_id": agreement["id"],
    }


def _documented_investor(
    world: ReitWorld, legal_name: str, email: str, documentation_reference: str
) -> dict:
    investor = world.investor(
        legal_name=legal_name,
        email=email,
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], documentation_reference)
    return investor


def _floor_platform(world: ReitWorld) -> dict:
    base = _zero_load_platform(
        world, "Thornbury Income REIT", 250000, "Thornbury Placement", "CRD-320001"
    )
    investor = _documented_investor(
        world, "Ilse Vandermeer", "ilse.vandermeer@example.com", "SUIT-ILSE-2026-08"
    )
    base["investor_id"] = investor["id"]
    return base


def _first_ticket_settled(world: ReitWorld) -> dict:
    """A funded platform whose stockholder already holds one ACCEPTED subscription."""
    base = _floor_platform(world)
    first = world.subscription(
        base["offering_id"],
        base["share_class_id"],
        base["investor_id"],
        base["selling_agreement_id"],
        250000,
    )
    world.escrow_subscription(first["id"])
    world.break_escrow(base["offering_id"])
    base["first_subscription_id"] = first["id"]
    return base


def _two_class_platform(world: ReitWorld) -> dict:
    """One offering with a class I and a class T, the class I closed to new money."""
    offering = world.offering(
        name="Everly Diversified REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
    )
    class_i = world.share_class(
        offering["id"],
        class_code="I",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    class_t = world.share_class(
        offering["id"],
        class_code="T",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(firm_name="Everly Placement", crd_number="CRD-320002")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(offering["id"], firm["id"], max_commission_bps=100)
    world.activate_agreement(agreement["id"])
    investor = _documented_investor(
        world, "Jonas Whitcombe", "jonas.whitcombe@example.com", "SUIT-JONAS-2026-08"
    )
    closed = assert_ok(
        world.api.set_share_class_status(
            class_i["id"], {"to_status": "CLOSED_TO_NEW"}, SPONSOR
        )
    )
    return {
        "offering_id": offering["id"],
        "class_i_id": class_i["id"],
        "class_t_id": class_t["id"],
        "selling_agreement_id": agreement["id"],
        "investor_id": investor["id"],
        "closed_class": closed,
    }


def _tender_platform(world: ReitWorld) -> dict:
    """A holder of 300000000 e4 with an OPEN August period and one 200000000 e4 tender."""
    base = _zero_load_platform(
        world, "Larkfield Income REIT", 30000000, "Larkfield Placement", "CRD-320003"
    )
    investor = _documented_investor(
        world, "Kira Ashenden", "kira.ashenden@example.com", "SUIT-KIRA-2026-08"
    )
    subscription = world.subscription(
        base["offering_id"],
        base["share_class_id"],
        investor["id"],
        base["selling_agreement_id"],
        30000000,
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(base["offering_id"])
    period = world.repurchase_period(
        base["offering_id"],
        period_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        request_cutoff_at="2026-08-26T00:00:00Z",
        settlement_date="2026-08-30",
    )
    queued = world.tender(
        period["id"], base["share_class_id"], 200000000, investor["id"]
    )
    base.update(
        {
            "investor_id": investor["id"],
            "period_id": period["id"],
            "queued_request_id": queued["id"],
        }
    )
    return base


def _two_agreement_platform(world: ReitWorld) -> dict:
    """One firm holding a strict agreement and a permissive one on the same offering."""
    offering = world.offering(
        name="Pemberton Income REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
    )
    share_class = world.share_class(
        offering["id"],
        class_code="I",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(firm_name="Pemberton Placement", crd_number="CRD-320004")
    world.declare_effective(offering["id"])
    strict = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    permissive = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=False,
    )
    world.activate_agreement(strict["id"])
    world.activate_agreement(permissive["id"])
    investor = world.investor(
        legal_name="Lucia Bramwell",
        email="lucia.bramwell@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "strict_agreement_id": strict["id"],
        "permissive_agreement_id": permissive["id"],
        "investor_id": investor["id"],
    }


def _load_bearing_platform(world: ReitWorld) -> dict:
    """A class T carrying 275 + 25 bps against a 299-bps and a 300-bps agreement."""
    offering = world.offering(
        name="Ravenscourt Income REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
    )
    share_class = world.share_class(
        offering["id"],
        class_code="T",
        upfront_selling_commission_bps=275,
        dealer_manager_fee_bps=25,
        annual_distribution_fee_bps=850,
        distribution_fee_cap_bps=875,
    )
    firm = world.broker_dealer(firm_name="Ravenscourt Placement", crd_number="CRD-320006")
    world.declare_effective(offering["id"])
    tight = world.selling_agreement(offering["id"], firm["id"], max_commission_bps=299)
    exact = world.selling_agreement(offering["id"], firm["id"], max_commission_bps=300)
    world.activate_agreement(tight["id"])
    world.activate_agreement(exact["id"])
    investor = _documented_investor(
        world, "Nils Ferreira", "nils.ferreira@example.com", "SUIT-NILS-2026-08"
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "tight_agreement_id": tight["id"],
        "exact_agreement_id": exact["id"],
        "investor_id": investor["id"],
    }


def _two_firm_platform(world: ReitWorld) -> dict:
    """Two firms, each with its own ACTIVE agreement on the same offering."""
    offering = world.offering(
        name="Stonecross Income REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
    )
    share_class = world.share_class(
        offering["id"],
        class_code="I",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm_a = world.broker_dealer(firm_name="Stonecross Placement A", crd_number="CRD-320007")
    firm_b = world.broker_dealer(firm_name="Stonecross Placement B", crd_number="CRD-320008")
    world.declare_effective(offering["id"])
    agreement_a = world.selling_agreement(
        offering["id"], firm_a["id"], max_commission_bps=100
    )
    agreement_b = world.selling_agreement(
        offering["id"], firm_b["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement_a["id"])
    world.activate_agreement(agreement_b["id"])
    investor = assert_created(
        world.api.create_investor(
            investor_payload(
                legal_name="Odile Petrakis",
                email="odile.petrakis@example.com",
                state_code="TX",
                net_worth_cents=5000000000,
                annual_income_cents=1000000000,
            ),
            make_broker_dealer_rep_headers(firm_a["id"]),
        )
    )
    world.document_suitability(investor["id"], "SUIT-ODILE-2026-08")
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "firm_a_id": firm_a["id"],
        "firm_b_id": firm_b["id"],
        "agreement_a_id": agreement_a["id"],
        "agreement_b_id": agreement_b["id"],
        "investor_id": investor["id"],
    }


# ─── Investment floors (PRD §3.4) ──────────────────────────────────────


class TestInvestmentFloors:
    def test_first_ticket_must_reach_the_initial_floor(self, api, world):
        """One cent short of 250,000 fails while exactly 250,000 is written.

        PRD §3.4: "Then the investment floor: a stockholder's **first** subscription in an offering must tender at least 250,000 cents — twenty-five hundred dollars — while every subsequent subscription in that offering must tender at least 50,000 cents, or five hundred dollars; a shortfall reports `ERR_BELOW_MINIMUM_INVESTMENT`."

        Design: Corner/validations/minimum_investment_floor_differs_for_first_and_subsequent_tickets
        """
        base = _floor_platform(world)

        assert_error(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=249999,
                ),
                SPONSOR,
            ),
            ApiErrorId.BELOW_MINIMUM_INVESTMENT,
            422,
        )
        assert_total_count(
            api.list_subscriptions({"investor_id": base["investor_id"]}, SPONSOR), 0
        )

        accepted = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=250000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            accepted,
            gross_investment_cents=250000,
            transaction_price_cents=1000,
            shares_issued_e4=2500000,
            status="PENDING",
        )

    def test_second_ticket_may_drop_to_the_additional_floor(self, api, world):
        """Once one ticket is accepted the floor is 50,000, so 49,999 fails and 50,000 lands.

        PRD §3.4: "Then the investment floor: a stockholder's **first** subscription in an offering must tender at least 250,000 cents — twenty-five hundred dollars — while every subsequent subscription in that offering must tender at least 50,000 cents, or five hundred dollars; a shortfall reports `ERR_BELOW_MINIMUM_INVESTMENT`."
        PRD §3.5: "The offering's `version` increments; every subscription of the offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at` order; one share lot is minted per accepted subscription with `issued_date` set to the current logical clock instant; `shares_outstanding_e4` on every touched class and `total_shares_e4` on every touched stockholder are recomputed; each affected stockholder's `cumulative_invested_cents` is recomputed and their `suitability_status` re-evaluated against `concentration_limit_cents`, so a stockholder pushed over the limit by the batch lands in `FLAGGED`; and the whole of `escrow_balance_cents` is moved into `gross_proceeds_cents`."

        Design: Corner/validations/minimum_investment_floor_differs_for_first_and_subsequent_tickets
        """
        base = _first_ticket_settled(world)
        assert world.read_subscription(base["first_subscription_id"])["status"] == "ACCEPTED"
        assert world.read_investor(base["investor_id"])["cumulative_invested_cents"] == 250000

        assert_error(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=49999,
                ),
                SPONSOR,
            ),
            ApiErrorId.BELOW_MINIMUM_INVESTMENT,
            422,
        )

        additional = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=50000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            additional,
            gross_investment_cents=50000,
            shares_issued_e4=500000,
            status="PENDING",
        )
        assert_total_count(
            api.list_subscriptions({"investor_id": base["investor_id"]}, SPONSOR), 2
        )


# ─── Per-class closure (PRD §3.1, §3.4) ────────────────────────────────


class TestPerClassClosure:
    def test_closed_class_refuses_new_money(self, api, world):
        """The closed class rejects a ticket even though the offering stays EFFECTIVE.

        PRD §3.1: "This is how a sponsor withdraws one fee structure without ending the offering: the closed class's `version` increments, subsequent subscriptions into it fail with `ERR_SHARE_CLASS_CLOSED`, and sibling classes of the same offering remain open for business."

        Design: Corner/validations/closing_one_share_class_blocks_only_that_class
        """
        base = _two_class_platform(world)
        assert_fields(base["closed_class"], status="CLOSED_TO_NEW")

        assert_error(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["class_i_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=300000,
                ),
                SPONSOR,
            ),
            ApiErrorId.SHARE_CLASS_CLOSED,
            409,
        )
        assert_total_count(
            api.list_subscriptions({"share_class_id": base["class_i_id"]}, SPONSOR), 0
        )

    def test_sibling_class_of_the_same_offering_stays_open(self, api, world):
        """Class T still takes business, and closing class I did not touch the offering.

        PRD §3.1: "This is how a sponsor withdraws one fee structure without ending the offering: the closed class's `version` increments, subsequent subscriptions into it fail with `ERR_SHARE_CLASS_CLOSED`, and sibling classes of the same offering remain open for business."
        PRD §2.10: "A change on one axis never implies a change on another unless a rule in §3 says so explicitly."

        Design: Corner/validations/closing_one_share_class_blocks_only_that_class
        """
        base = _two_class_platform(world)

        subscription = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["class_t_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=300000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            subscription,
            share_class_id=base["class_t_id"],
            shares_issued_e4=3000000,
            status="PENDING",
        )
        assert world.read_share_class(base["class_t_id"])["status"] == "ACTIVE"
        assert world.read_offering(base["offering_id"])["registration_status"] == "EFFECTIVE"
        assert_total_count(
            api.list_subscriptions({"offering_id": base["offering_id"]}, SPONSOR), 1
        )


# ─── Share sufficiency nets against queued tenders (PRD §3.8) ──────────


class TestTenderNetting:
    def test_second_tender_is_measured_net_of_the_first(self, api, world):
        """With 200000000 e4 already queued, a further 150000000 e4 exceeds the balance.

        PRD §3.8: "The plan must be `ACTIVE`; the current logical clock must fall inside the half-open window, so a tender filed before `opens_at` or at or after `request_cutoff_at` is refused with `ERR_REPURCHASE_PERIOD_CLOSED`; and the shares must actually be there — `shares_requested_e4` may not exceed what the stockholder holds across `OPEN` lots in that class, net of shares already tendered in that stockholder's other `QUEUED` or `HELD` requests in the same period, or the tender is refused with `ERR_INSUFFICIENT_SHARES`."

        Design: Corner/validations/tendered_shares_net_against_other_queued_requests_of_the_period
        """
        base = _tender_platform(world)
        assert world.read_investor(base["investor_id"])["total_shares_e4"] == 300000000
        assert world.read_request(base["queued_request_id"])["status"] == "QUEUED"

        assert_error(
            api.create_repurchase_request(
                repurchase_request_payload(
                    base["period_id"], base["share_class_id"], 150000000
                ),
                make_investor_user_headers(base["investor_id"]),
            ),
            ApiErrorId.INSUFFICIENT_SHARES,
            422,
        )
        assert_total_count(
            api.list_repurchase_requests(
                {"repurchase_period_id": base["period_id"]}, TRANSFER_AGENT
            ),
            1,
        )

    def test_exact_remainder_queues_and_one_further_unit_does_not(self, api, world):
        """The remaining 100000000 e4 is tenderable in full; a single unit beyond it is not.

        PRD §3.8: "The plan must be `ACTIVE`; the current logical clock must fall inside the half-open window, so a tender filed before `opens_at` or at or after `request_cutoff_at` is refused with `ERR_REPURCHASE_PERIOD_CLOSED`; and the shares must actually be there — `shares_requested_e4` may not exceed what the stockholder holds across `OPEN` lots in that class, net of shares already tendered in that stockholder's other `QUEUED` or `HELD` requests in the same period, or the tender is refused with `ERR_INSUFFICIENT_SHARES`."
        PRD §3.8: "A filed tender sits in `QUEUED` with `requested_value_cents`, `approved_value_cents`, `approved_shares_e4`, `early_repurchase_deduction_cents` and `net_proceeds_cents` all at zero until the period is processed."

        Design: Corner/validations/tendered_shares_net_against_other_queued_requests_of_the_period
        """
        base = _tender_platform(world)

        exact = assert_created(
            api.create_repurchase_request(
                repurchase_request_payload(
                    base["period_id"], base["share_class_id"], 100000000
                ),
                make_investor_user_headers(base["investor_id"]),
            )
        )
        assert_fields(
            exact,
            shares_requested_e4=100000000,
            approved_value_cents=0,
            approved_shares_e4=0,
            status="QUEUED",
        )

        assert_error(
            api.create_repurchase_request(
                repurchase_request_payload(base["period_id"], base["share_class_id"], 1),
                make_investor_user_headers(base["investor_id"]),
            ),
            ApiErrorId.INSUFFICIENT_SHARES,
            422,
        )
        assert_total_count(
            api.list_repurchase_requests(
                {"repurchase_period_id": base["period_id"]}, TRANSFER_AGENT
            ),
            2,
        )
        assert_fields(
            world.read_period(base["period_id"]), status="OPEN", settled_amount_cents=0
        )


# ─── Suitability is an agreement-level requirement (PRD §3.3, §3.4) ────


class TestSuitabilityGateScope:
    def test_gate_fires_under_the_strict_agreement_only(self, api, world):
        """The same INCOMPLETE stockholder is refused under one agreement and taken under the other.

        PRD §3.4: "First suitability: where the agreement's `suitability_documentation_required` is true and the stockholder's `suitability_status` is `INCOMPLETE` or `FLAGGED`, the subscription is refused with `ERR_SUITABILITY_NOT_DOCUMENTED`."
        PRD §3.2: "New accounts start with `suitability_status` at `INCOMPLETE`, `account_status` at `ACTIVE`, a null `suitability_documentation_reference`, and the running totals `cumulative_invested_cents`, `total_shares_e4`, `cumulative_distributions_received_cents` and `cumulative_early_repurchase_deduction_cents` all at zero."

        Design: Corner/validations/suitability_gate_fires_only_under_agreements_that_require_documentation
        """
        base = _two_agreement_platform(world)
        assert world.read_investor(base["investor_id"])["suitability_status"] == "INCOMPLETE"

        assert_error(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["strict_agreement_id"],
                    gross_investment_cents=250000,
                ),
                SPONSOR,
            ),
            ApiErrorId.SUITABILITY_NOT_DOCUMENTED,
            422,
        )

        permitted = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["permissive_agreement_id"],
                    gross_investment_cents=250000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            permitted,
            selling_agreement_id=base["permissive_agreement_id"],
            status="PENDING",
        )

    def test_documenting_the_file_opens_the_strict_agreement(self, api, world):
        """Recording the documentation reference lets the strict agreement place business.

        PRD §3.2: "A `BrokerDealerRep` or a `ComplianceOfficer` may take an account from `INCOMPLETE` to `DOCUMENTED`, which stores the supplied string in `suitability_documentation_reference` and increments the account's `version`."
        PRD §3.4: "First suitability: where the agreement's `suitability_documentation_required` is true and the stockholder's `suitability_status` is `INCOMPLETE` or `FLAGGED`, the subscription is refused with `ERR_SUITABILITY_NOT_DOCUMENTED`."

        Design: Corner/validations/suitability_gate_fires_only_under_agreements_that_require_documentation
        """
        base = _two_agreement_platform(world)
        world.subscription(
            base["offering_id"],
            base["share_class_id"],
            base["investor_id"],
            base["permissive_agreement_id"],
            250000,
        )

        documented = assert_ok(
            api.record_suitability_documentation(
                base["investor_id"],
                {"documentation_reference": "SUIT-LUCIA-2026-08"},
                COMPLIANCE,
            )
        )
        assert_fields(
            documented,
            suitability_status="DOCUMENTED",
            suitability_documentation_reference="SUIT-LUCIA-2026-08",
        )

        now_permitted = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["strict_agreement_id"],
                    gross_investment_cents=250000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            now_permitted,
            selling_agreement_id=base["strict_agreement_id"],
            status="PENDING",
        )
        assert_total_count(
            api.list_subscriptions({"investor_id": base["investor_id"]}, SPONSOR), 2
        )


# ─── Valuation review waits for the period to elapse (PRD §3.6) ────────


class TestValuationReviewTiming:
    def test_submission_before_the_period_end_is_refused(self, api, world):
        """An August record cannot enter review while the clock still reads 2026-08-01.

        PRD §3.6: "A `SponsorOperator` submits `DRAFT` to `ADVISOR_REVIEW`, which is permitted only once the valuation period has fully elapsed — the current logical date must be strictly after the `period_end_date`, and an early submission is refused with `ERR_NAV_PERIOD_NOT_ELAPSED`."
        PRD §3.6: "When the snapshotted share count is zero, both per-share figures are set to the offering's `initial_offering_price_cents`."

        Design: Corner/validations/nav_review_blocked_until_the_valuation_period_has_elapsed
        """
        base = _unfunded_platform(world, "Quillon Income REIT")
        record = world.nav_record(
            base["share_class_id"], "2026-08-01", "2026-08-31", 5000000
        )
        assert_fields(
            record,
            shares_outstanding_e4_snapshot=0,
            nav_per_share_pre_accrual_cents=1000,
            nav_per_share_cents=1000,
            variance_bps=0,
            status="DRAFT",
        )

        assert_error(
            api.set_nav_record_status(
                record["id"], {"to_status": "ADVISOR_REVIEW"}, SPONSOR
            ),
            ApiErrorId.NAV_PERIOD_NOT_ELAPSED,
            409,
        )

        unchanged = world.read_nav_record(record["id"])
        assert_fields(unchanged, status="DRAFT", version=1)

    def test_submission_after_the_period_end_is_accepted(self, api, world):
        """Once the clock reads 2026-09-01 the same record enters ADVISOR_REVIEW.

        PRD §3.6: "A `SponsorOperator` submits `DRAFT` to `ADVISOR_REVIEW`, which is permitted only once the valuation period has fully elapsed — the current logical date must be strictly after the `period_end_date`, and an early submission is refused with `ERR_NAV_PERIOD_NOT_ELAPSED`."
        PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp recording the most recent mutation of the row, and `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/validations/nav_review_blocked_until_the_valuation_period_has_elapsed
        """
        base = _unfunded_platform(world, "Quillon Income REIT")
        record = world.nav_record(
            base["share_class_id"], "2026-08-01", "2026-08-31", 5000000
        )
        world.set_clock("2026-09-01T00:00:00Z")

        submitted = assert_ok(
            api.set_nav_record_status(
                record["id"], {"to_status": "ADVISOR_REVIEW"}, SPONSOR
            )
        )

        assert_fields(submitted, status="ADVISOR_REVIEW", version=2)


# ─── The load ceiling is inclusive (PRD §3.4) ──────────────────────────


class TestAgreementLoadCeiling:
    def test_load_one_basis_point_over_the_cap_is_refused(self, api, world):
        """A 300-bps class cannot be placed under a 299-bps agreement.

        PRD §3.4: "The class's `upfront_selling_commission_bps` and `dealer_manager_fee_bps` added together must not exceed the agreement's `max_commission_bps`, or the subscription is refused with `ERR_COMMISSION_CAP_EXCEEDED` — a firm that negotiated a lower load ceiling cannot be routed into an expensive class."

        Design: Corner/validations/total_load_equal_to_the_agreement_cap_is_permitted
        """
        base = _load_bearing_platform(world)

        assert_error(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["tight_agreement_id"],
                    gross_investment_cents=500000,
                ),
                SPONSOR,
            ),
            ApiErrorId.COMMISSION_CAP_EXCEEDED,
            422,
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": base["offering_id"]}, SPONSOR), 0
        )

    def test_load_exactly_at_the_cap_is_permitted_and_priced(self, api, world):
        """275 + 25 against a cap of 300 passes and each load line rounds on its own.

        PRD §3.4: "The class's `upfront_selling_commission_bps` and `dealer_manager_fee_bps` added together must not exceed the agreement's `max_commission_bps`, or the subscription is refused with `ERR_COMMISSION_CAP_EXCEEDED` — a firm that negotiated a lower load ceiling cannot be routed into an expensive class."
        PRD §3.4: "`net_invested_cents` is the gross investment less the sum of those two rounded lines."
        PRD §3.4: "Because of that floor a sliver of money is usually left over: `unapplied_cash_cents` is the net invested amount less the value of the issued shares, that value being the issued share units multiplied by the transaction price, divided by 10,000, and floored."

        Design: Corner/validations/total_load_equal_to_the_agreement_cap_is_permitted
        """
        base = _load_bearing_platform(world)

        subscription = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["exact_agreement_id"],
                    gross_investment_cents=500000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            subscription,
            transaction_price_cents=1000,
            upfront_selling_commission_cents=13750,
            dealer_manager_fee_cents=1250,
            net_invested_cents=485000,
            shares_issued_e4=4850000,
            unapplied_cash_cents=0,
            status="PENDING",
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": base["offering_id"]}, SPONSOR), 1
        )


# ─── Existence outranks ownership (PRD §2.7, §2.9) ─────────────────────


class TestExistenceOutranksOwnership:
    def test_placing_under_another_firms_agreement_is_an_ownership_failure(
        self, api, world
    ):
        """A representative of firm A citing firm B's agreement is refused as non-owner.

        PRD §2.1: "When `X-User-Role` is `BrokerDealerRep`, `X-User-ID` is the `id` of the acting `BrokerDealer`; ownership checks on any resource that references a broker-dealer compare that resource's `broker_dealer_id` to `X-User-ID`, so a representative may place business only under a selling agreement belonging to its own firm."
        PRD §2.9: "5. **Ownership (403).** An entity-backed role acts only on its own rows, otherwise `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/foreign_keys_resolve_before_broker_dealer_ownership_is_judged
        """
        base = _two_firm_platform(world)

        assert_error(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["agreement_b_id"],
                    gross_investment_cents=300000,
                ),
                make_broker_dealer_rep_headers(base["firm_a_id"]),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        own = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["agreement_a_id"],
                    gross_investment_cents=300000,
                ),
                make_broker_dealer_rep_headers(base["firm_a_id"]),
            )
        )

        assert_fields(
            own, selling_agreement_id=base["agreement_a_id"], status="PENDING"
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": base["offering_id"]}, SPONSOR), 1
        )

    def test_unresolvable_offering_reference_outranks_the_ownership_failure(
        self, api, world
    ):
        """The very same non-owning call reports 404 when the offering does not resolve.

        PRD §2.9: "Every write request is evaluated against a single global priority ladder, from the top down."
        PRD §2.9: "4. **Existence (404).** Every referenced identifier resolves, in the order given in §2.7, otherwise `ERR_RESOURCE_NOT_FOUND`."
        PRD §2.9: "The **first** rule that is violated determines the response; later violations are never reported, never merged into the message, and never change the status code."

        Design: Corner/validations/foreign_keys_resolve_before_broker_dealer_ownership_is_judged
        """
        base = _two_firm_platform(world)

        assert_error(
            api.create_subscription(
                subscription_payload(
                    UNKNOWN_ID,
                    base["share_class_id"],
                    base["investor_id"],
                    base["agreement_b_id"],
                    gross_investment_cents=300000,
                ),
                make_broker_dealer_rep_headers(base["firm_a_id"]),
            ),
            ApiErrorId.RESOURCE_NOT_FOUND,
            404,
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": base["offering_id"]}, SPONSOR), 0
        )
