"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server whose logical clock reads
exactly 2026-08-01T00:00:00Z at startup, PRD §2.5). Lenient get_success_data
is used internally so setup failures surface as clear "Setup failed" errors.

Beneficiary and ThirdPartyBidder calls that are ownership-gated always thread
the acting entity's id through make_beneficiary_headers /
make_third_party_bidder_headers (PRD §2.1).
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PIPELINE
from .factories import (
    create_beneficiary_payload,
    create_bid_payload,
    create_bidder_registration_payload,
    create_bidding_instruction_payload,
    create_case_payload,
    create_cost_advance_payload,
    create_nod_payload,
    create_nots_payload,
    create_postponement_payload,
    create_publication_payload,
    create_quote_payload,
    create_stay_order_payload,
    create_surplus_claim_payload,
    schedule_sale_payload,
)
from .test_users import (
    TEST_USERS,
    make_beneficiary_headers,
    make_case_manager_headers,
    make_third_party_bidder_headers,
)

ADMIN = TEST_USERS["trustee_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
AUCT = TEST_USERS["auctioneer_headers"]

# Segregation-of-duties actors for claim filing/review (PRD §2.1, §3.9).
CM_FILER = make_case_manager_headers("cm_filer_1")
CM_REVIEWER = make_case_manager_headers("cm_reviewer_1")


# ---------------------------------------------------------------------------
# Tier 1: base entities and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_beneficiary(reference_code: str = "BEN-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_beneficiary(
            create_beneficiary_payload(reference_code=reference_code, **overrides),
            ADMIN,
        )
    )


def create_case(beneficiary_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_case(create_case_payload(beneficiary_id, **overrides), CM)
    )


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, CM))


def case_version(case_id: str) -> int:
    return get_case(case_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: notices and the publication cycle
# ---------------------------------------------------------------------------

def record_nod(case_id: str, recording_date: str = PIPELINE["NOD_DATE"],
               instrument_number: str = "NOD-1") -> dict:
    """Caller must ensure the logical clock date already equals recording_date."""
    return get_success_data(
        api_client.record_nod(
            case_id,
            create_nod_payload(
                recording_date=recording_date, instrument_number=instrument_number
            ),
            CM,
        )
    )


def record_nots(case_id: str, recording_date: str = PIPELINE["NOTS_DATE"],
                instrument_number: str = "NOTS-1") -> dict:
    """Sets the clock to the recording date, then records the notice."""
    set_clock(f"{recording_date}T00:00:00Z")
    return get_success_data(
        api_client.record_nots(
            case_id,
            create_nots_payload(recording_date, instrument_number=instrument_number),
            CM,
        )
    )


def record_publication(nots_id: str, run_date: str,
                       newspaper_name: str = "Daily Journal") -> dict:
    """Sets the clock to the run date, then records the publication run."""
    set_clock(f"{run_date}T00:00:00Z")
    return get_success_data(
        api_client.create_publication(
            nots_id,
            create_publication_payload(run_date, newspaper_name=newspaper_name),
            CM,
        )
    )


def file_affidavit(publication_id: str) -> dict:
    """Caller must ensure the clock date is on or after the run's run_date."""
    return get_success_data(api_client.file_affidavit(publication_id, CM))


# ---------------------------------------------------------------------------
# Tier 2: staged case pipelines
# ---------------------------------------------------------------------------

def setup_case_with_nod(reference_code: str = "BEN-1", nod_date: str = "2026-08-01",
                        **case_overrides) -> dict:
    """Beneficiary + case + RECORDED notice of default at the default clock."""
    ben = create_beneficiary(reference_code)
    case = create_case(ben["id"], **case_overrides)
    nod = record_nod(case["id"], recording_date=nod_date)
    return {"beneficiary": ben, "case": get_case(case["id"]), "nod": nod}


def setup_case_at_nots_recorded(reference_code: str = "BEN-1",
                                nots_date: str = PIPELINE["NOTS_DATE"],
                                **case_overrides) -> dict:
    """Case driven to NOTS_RECORDED (NOD at default clock, NOTS on nots_date)."""
    ctx = setup_case_with_nod(reference_code, **case_overrides)
    nots = record_nots(ctx["case"]["id"], recording_date=nots_date)
    ctx["nots"] = nots
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def add_full_publication_cycle(nots_id: str,
                               run_dates=PIPELINE["PUB_DATES"]) -> list:
    """Record all runs and file every affidavit. Returns the publications.

    The clock is left at the last run date, which is on/after every run date.
    """
    pubs = [record_publication(nots_id, d) for d in run_dates]
    for pub in pubs:
        file_affidavit(pub["id"])
    return pubs


def setup_case_at_publication_complete(reference_code: str = "BEN-1",
                                       **case_overrides) -> dict:
    """Case at NOTS_RECORDED whose notice has reached PUBLICATION_COMPLETE."""
    ctx = setup_case_at_nots_recorded(reference_code, **case_overrides)
    ctx["publications"] = add_full_publication_cycle(ctx["nots"]["id"])
    ctx["nots"] = get_success_data(api_client.get_nots(ctx["nots"]["id"], CM))
    return ctx


def schedule_sale(nots_id: str, venue_name: str = "VEN-1",
                  scheduled_sale_start_at: str = PIPELINE["SALE_START"]) -> dict:
    return get_success_data(
        api_client.schedule_sale(
            nots_id,
            schedule_sale_payload(
                venue_name=venue_name,
                scheduled_sale_start_at=scheduled_sale_start_at,
            ),
            CM,
        )
    )


def setup_case_at_sale_scheduled(reference_code: str = "BEN-1",
                                 venue_name: str = "VEN-1",
                                 sale_start: str = PIPELINE["SALE_START"],
                                 **case_overrides) -> dict:
    """Full pipeline through SALE_SCHEDULED. Clock ends at the last run date."""
    ctx = setup_case_at_publication_complete(reference_code, **case_overrides)
    ctx["sale"] = schedule_sale(
        ctx["nots"]["id"], venue_name=venue_name, scheduled_sale_start_at=sale_start
    )
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: instructions, quotes, advances, stays
# ---------------------------------------------------------------------------

def add_bidding_instruction(case_id: str, beneficiary_id: str,
                            opening_bid_cents: int = 42_000_000,
                            max_bid_cents: int = 43_000_000,
                            strategy: str = "UP_TO_MAX") -> dict:
    version = case_version(case_id)
    return get_success_data(
        api_client.create_bidding_instruction(
            case_id,
            create_bidding_instruction_payload(
                version,
                opening_bid_cents=opening_bid_cents,
                max_bid_cents=max_bid_cents,
                strategy=strategy,
            ),
            make_beneficiary_headers(beneficiary_id),
        )
    )


def issue_quote(case_id: str, quote_type: str, good_through_date: str) -> dict:
    version = case_version(case_id)
    return get_success_data(
        api_client.create_quote(
            case_id,
            create_quote_payload(quote_type, good_through_date, version),
            CM,
        )
    )


def submit_cost_advance(case_id: str, beneficiary_id: str,
                        category: str = "PUBLICATION", amount_cents: int = 35_000,
                        incurred_date: str = "2026-08-01") -> dict:
    return get_success_data(
        api_client.create_cost_advance(
            case_id,
            create_cost_advance_payload(
                category=category, amount_cents=amount_cents,
                incurred_date=incurred_date,
            ),
            make_beneficiary_headers(beneficiary_id),
        )
    )


def approve_advance(advance_id: str) -> dict:
    return get_success_data(
        api_client.review_cost_advance(advance_id, {"decision": "APPROVE"}, CM)
    )


def file_stay(case_id: str, stay_type: str = "LITIGATION_HOLD",
              court_case_number: str = "CV-26-0001",
              filed_at: str = "2026-07-31T08:00:00Z") -> dict:
    return get_success_data(
        api_client.create_stay_order(
            case_id,
            create_stay_order_payload(
                stay_type=stay_type, court_case_number=court_case_number,
                filed_at=filed_at,
            ),
            CM,
        )
    )


def release_stay(stay_id: str, reference: str = "ORD-26-100") -> dict:
    return get_success_data(
        api_client.release_stay_order(
            stay_id, {"release_court_order_reference": reference}, CM
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: bidders, conduct, close
# ---------------------------------------------------------------------------

def register_bidder(sale_id: str, bidder_name: str = "Bidder One",
                    bidder_email: str = "bidder1@bid.example",
                    deposit_cents: int = 1_000_000) -> dict:
    return get_success_data(
        api_client.create_bidder_registration(
            sale_id,
            create_bidder_registration_payload(
                bidder_name=bidder_name, bidder_email=bidder_email,
                deposit_cents=deposit_cents,
            ),
            AUCT,
        )
    )


def qualify_bidder(registration_id: str) -> dict:
    return get_success_data(
        api_client.review_bidder_registration(
            registration_id, {"decision": "QUALIFY"}, AUCT
        )
    )


def register_and_qualify_bidder(sale_id: str, **kwargs) -> dict:
    reg = register_bidder(sale_id, **kwargs)
    return qualify_bidder(reg["id"])


def place_bid(sale_id: str, registration_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.place_bid(
            sale_id,
            create_bid_payload(registration_id, amount_cents),
            make_third_party_bidder_headers(registration_id),
        )
    )


def conduct_sale_at(sale_id: str,
                    clock_instant: str = PIPELINE["SALE_DAY_CLOCK"]) -> dict:
    """Sets the clock to the sale day, then conducts the auction."""
    set_clock(clock_instant)
    return get_success_data(api_client.conduct_sale(sale_id, AUCT))


def postpone_sale(sale_id: str, new_sale_start_at: str,
                  reason: str = "TRUSTEE_DISCRETION",
                  announced_via: str = "ADVANCE") -> dict:
    """Postpones a sale, threading the sale's current version (PRD §2.7)."""
    version = get_success_data(api_client.get_auction_sale(sale_id, AUCT))["version"]
    return get_success_data(
        api_client.create_postponement(
            sale_id,
            create_postponement_payload(
                new_sale_start_at, version,
                reason=reason, announced_via=announced_via,
            ),
            AUCT,
        )
    )


def setup_conducted_sale(reference_code: str = "BEN-1",
                         venue_name: str = "VEN-1",
                         opening_bid_cents: int = 42_000_000,
                         max_bid_cents: int = 43_000_000,
                         strategy: str = "UP_TO_MAX",
                         sale_start: str = PIPELINE["SALE_START"],
                         conduct_clock: str = PIPELINE["SALE_DAY_CLOCK"],
                         **case_overrides) -> dict:
    """Full pipeline through a CONDUCTED sale with an ACTIVE instruction."""
    ctx = setup_case_at_sale_scheduled(
        reference_code, venue_name=venue_name, sale_start=sale_start,
        **case_overrides,
    )
    ctx["instruction"] = add_bidding_instruction(
        ctx["case"]["id"], ctx["beneficiary"]["id"],
        opening_bid_cents=opening_bid_cents, max_bid_cents=max_bid_cents,
        strategy=strategy,
    )
    ctx["sale"] = conduct_sale_at(ctx["sale"]["id"], clock_instant=conduct_clock)
    return ctx


def setup_closed_sale(reference_code: str = "BEN-1",
                      venue_name: str = "VEN-1",
                      opening_bid_cents: int = 42_000_000,
                      max_bid_cents: int = 43_000_000,
                      strategy: str = "UP_TO_MAX",
                      bid_amount_cents: Optional[int] = None,
                      bidder_name: str = "Bidder One",
                      bidder_email: str = "bidder1@bid.example",
                      deposit_cents: int = 1_000_000,
                      **case_overrides) -> dict:
    """Full pipeline through a CLOSED sale.

    With bid_amount_cents set, one third-party bidder registers and qualifies
    while the sale is still SCHEDULED, then places that bid after conduct
    (third-party win); with it None the beneficiary wins at the opening
    credit bid. Clock ends on the sale day.
    """
    ctx = setup_case_at_sale_scheduled(
        reference_code, venue_name=venue_name, **case_overrides
    )
    ctx["instruction"] = add_bidding_instruction(
        ctx["case"]["id"], ctx["beneficiary"]["id"],
        opening_bid_cents=opening_bid_cents, max_bid_cents=max_bid_cents,
        strategy=strategy,
    )
    if bid_amount_cents is not None:
        ctx["registration"] = register_and_qualify_bidder(
            ctx["sale"]["id"], bidder_name=bidder_name,
            bidder_email=bidder_email, deposit_cents=deposit_cents,
        )
    ctx["sale"] = conduct_sale_at(ctx["sale"]["id"])
    if bid_amount_cents is not None:
        ctx["bid"] = place_bid(
            ctx["sale"]["id"], ctx["registration"]["id"], bid_amount_cents
        )
    ctx["sale"] = get_success_data(api_client.close_sale(ctx["sale"]["id"], AUCT))
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: claims, distribution, disbursements
# ---------------------------------------------------------------------------

def file_claim(case_id: str, filer_headers=None, claimant_name: str = "Lien One",
               claimant_type: str = "JUNIOR_LIENHOLDER", priority_rank: int = 1,
               claimed_amount_cents: int = 100_000,
               filed_date: str = PIPELINE["CLAIMS_FILE_DATE"]) -> dict:
    """Caller must ensure the clock date equals filed_date."""
    return get_success_data(
        api_client.create_surplus_claim(
            case_id,
            create_surplus_claim_payload(
                claimant_name=claimant_name, claimant_type=claimant_type,
                priority_rank=priority_rank,
                claimed_amount_cents=claimed_amount_cents, filed_date=filed_date,
            ),
            filer_headers or CM_FILER,
        )
    )


def approve_claim(claim_id: str, approved_amount_cents: int,
                  reviewer_headers=None) -> dict:
    return get_success_data(
        api_client.review_surplus_claim(
            claim_id,
            {"decision": "APPROVE", "approved_amount_cents": approved_amount_cents},
            reviewer_headers or CM_REVIEWER,
        )
    )


def list_case_disbursements(case_id: str, **filters) -> list:
    params = {"foreclosure_case_id": case_id}
    params.update(filters)
    return get_success_data(api_client.list_disbursements(CM, params=params))


def trustee_fee_disbursement(case_id: str) -> dict:
    rows = list_case_disbursements(case_id, recipient_type="TRUSTEE_FEE")
    assert len(rows) == 1, f"expected exactly one TRUSTEE_FEE disbursement, got {rows}"
    return rows[0]
