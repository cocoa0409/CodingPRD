"""Composite setup helpers.

The server is restarted before every test, so every helper here builds its
preconditions from an empty store using only declared endpoints. Helpers are
layered: single-entity makers, then state-progression helpers, then whole-spine
builders that carry a disposition from an empty store to any point in its life.

Every helper returns plain dictionaries of ids and entity payloads so tests can
assert against the state they set up.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .assertions import find_row
from .constants import DEFAULT_CLOCK
from .test_users import (
    ADMIN_HEADERS,
    CLERK_ADOPT_HEADERS,
    CLERK_AUTHORIZE_HEADERS,
    CLERK_AWARD_HEADERS,
    CLERK_DETERMINE_HEADERS,
    COMPLIANCE_HEADERS,
    FINANCE_HEADERS,
    OFFICER_HEADERS,
    make_agency_representative_headers,
    make_appraiser_headers,
    make_bidder_headers,
)

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> None:
    """Move the logical clock to the given instant."""
    get_success_data(api.set_clock(instant, OFFICER_HEADERS))


def reset_clock(api: ApiClient) -> None:
    """Return the logical clock to the instant it reads before any clock call."""
    set_clock(api, DEFAULT_CLOCK)


# ---------------------------------------------------------------------------
# Tier 1 — single entities
# ---------------------------------------------------------------------------


def make_agency(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a custodian agency."""
    return get_success_data(
        api.create_agency(f.agency_payload(**overrides), ADMIN_HEADERS)
    )


def make_preference_agency(
    api: ApiClient, preference_category: str = "AFFORDABLE_HOUSING", **overrides: Any
) -> Dict[str, Any]:
    """Register a preference entity in the given statutory category."""
    return get_success_data(
        api.create_agency(
            f.preference_agency_payload(preference_category, **overrides),
            ADMIN_HEADERS,
        )
    )


def make_transit_agency(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a neighbouring transit district that holds no preference."""
    return get_success_data(
        api.create_agency(f.transit_agency_payload(**overrides), ADMIN_HEADERS)
    )


def lapse_agency_registry(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    """Let an agency's notice registry standing lapse."""
    return get_success_data(
        api.patch_agency(agency_id, {"notice_registry_status": "LAPSED"}, ADMIN_HEADERS)
    )


def make_parcel(
    api: ApiClient, custodian_agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Record a parcel held by the given custodian agency."""
    return get_success_data(
        api.create_parcel(
            f.parcel_payload(custodian_agency_id, **overrides), OFFICER_HEADERS
        )
    )


def parcel_version(api: ApiClient, parcel_id: str) -> int:
    """Read the parcel's current optimistic concurrency token."""
    return get_success_data(api.get_parcel(parcel_id, OFFICER_HEADERS))["version"]


def declaration_version(api: ApiClient, declaration_id: str) -> int:
    """Read the declaration's current optimistic concurrency token."""
    return get_success_data(
        api.get_declaration(declaration_id, OFFICER_HEADERS)
    )["version"]


def make_appraiser(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a licensed appraiser."""
    return get_success_data(
        api.create_appraiser(f.appraiser_payload(**overrides), ADMIN_HEADERS)
    )


def make_bidder(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a prospective bidder with no funds yet."""
    return get_success_data(
        api.create_bidder(f.bidder_payload(**overrides), ADMIN_HEADERS)
    )


def make_funded_bidder(
    api: ApiClient, amount_cents: int = 10000000, **overrides: Any
) -> Dict[str, Any]:
    """Register a bidder and credit verified funds to its account."""
    bidder = make_bidder(api, **overrides)
    get_success_data(
        api.fund_bidder(bidder["id"], f.funding_payload(amount_cents), FINANCE_HEADERS)
    )
    return get_success_data(api.get_bidder(bidder["id"], FINANCE_HEADERS))


def debar_bidder(api: ApiClient, bidder_id: str, **overrides: Any) -> Dict[str, Any]:
    """Debar a bidder for cause."""
    return get_success_data(
        api.debar_bidder(bidder_id, f.debarment_payload(**overrides), COMPLIANCE_HEADERS)
    )


def make_fund(
    api: ApiClient,
    priority_rank: int = 1,
    allocation_pct: float = 1.0,
    fixed_reserve_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Configure one designated fund."""
    return get_success_data(
        api.create_fund(
            f.fund_payload(
                priority_rank, allocation_pct, fixed_reserve_cents, **overrides
            ),
            FINANCE_HEADERS,
        )
    )


def make_single_fund(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Configure one fund taking the whole distribution."""
    return make_fund(
        api, priority_rank=1, allocation_pct=1.0, fixed_reserve_cents=0, **overrides
    )


def make_fund_ladder(api: ApiClient, specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Configure several funds from a list of rank, share and reserve specifications."""
    funds = []
    for spec in specs:
        funds.append(
            make_fund(
                api,
                priority_rank=spec["priority_rank"],
                allocation_pct=spec["allocation_pct"],
                fixed_reserve_cents=spec.get("fixed_reserve_cents", 0),
                name=spec.get("name", "Designated Fund"),
                fund_code=spec.get("fund_code", f.unique_fund_code()),
            )
        )
    return funds


# ---------------------------------------------------------------------------
# Tier 2 — title items and valuation
# ---------------------------------------------------------------------------


def open_title_item(api: ApiClient, parcel_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open one title curative item against a parcel."""
    return get_success_data(
        api.create_title_item(parcel_id, f.title_item_payload(**overrides), OFFICER_HEADERS)
    )


def cure_title_item(
    api: ApiClient, title_item_id: str, actual_cure_cost_cents: Optional[int] = 250000
) -> Dict[str, Any]:
    """Resolve a title item as cured at the given actual cost."""
    return get_success_data(
        api.resolve_title_item(
            title_item_id,
            f.cure_resolution_payload(actual_cure_cost_cents),
            OFFICER_HEADERS,
        )
    )


def waive_title_item(api: ApiClient, title_item_id: str) -> Dict[str, Any]:
    """Resolve a title item by waiving it with a title endorsement."""
    return get_success_data(
        api.resolve_title_item(
            title_item_id, f.waiver_resolution_payload(), OFFICER_HEADERS
        )
    )


def reserve_title_item_as_easement(
    api: ApiClient, title_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Resolve a title item by reserving the burden as an agency easement."""
    return get_success_data(
        api.resolve_title_item(
            title_item_id, f.easement_resolution_payload(**overrides), OFFICER_HEADERS
        )
    )


def add_cured_lien(
    api: ApiClient,
    parcel_id: str,
    estimate_cents: int = 400000,
    actual_cents: int = 250000,
) -> Dict[str, Any]:
    """Open a lien on the parcel and resolve it as cured at a known actual cost."""
    item = open_title_item(api, parcel_id, cure_cost_estimate_cents=estimate_cents)
    return cure_title_item(api, item["id"], actual_cents)


def order_appraisal(
    api: ApiClient, parcel_id: str, appraiser_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Order an appraisal, reading the parcel's current version as the OCC token."""
    version = parcel_version(api, parcel_id)
    return get_success_data(
        api.create_appraisal(
            f.appraisal_order_payload(parcel_id, appraiser_id, version, **overrides),
            OFFICER_HEADERS,
        )
    )


def report_appraisal(
    api: ApiClient,
    appraisal_id: str,
    appraiser_id: str,
    appraised_value_cents: int = 100000000,
    effective_date: str = DEFAULT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """The engaged appraiser delivers the report."""
    return get_success_data(
        api.report_appraisal(
            appraisal_id,
            f.appraisal_report_payload(
                appraised_value_cents, effective_date, **overrides
            ),
            make_appraiser_headers(appraiser_id),
        )
    )


def accept_appraisal(api: ApiClient, appraisal_id: str) -> Dict[str, Any]:
    """The real property office accepts the report as the governing valuation."""
    return get_success_data(api.accept_appraisal(appraisal_id, OFFICER_HEADERS))


def make_reported_appraisal(
    api: ApiClient,
    parcel_id: str,
    appraiser_id: str,
    appraised_value_cents: int = 100000000,
    effective_date: str = DEFAULT_CLOCK,
    **order_overrides: Any,
) -> Dict[str, Any]:
    """Order an appraisal and deliver its report, leaving it REPORTED."""
    appraisal = order_appraisal(api, parcel_id, appraiser_id, **order_overrides)
    return report_appraisal(
        api,
        appraisal["id"],
        appraiser_id,
        appraised_value_cents=appraised_value_cents,
        effective_date=effective_date,
    )


def make_accepted_appraisal(
    api: ApiClient,
    parcel_id: str,
    appraiser_id: str,
    appraised_value_cents: int = 100000000,
    effective_date: str = DEFAULT_CLOCK,
    **order_overrides: Any,
) -> Dict[str, Any]:
    """Order, report and accept an appraisal, leaving the parcel valuation current."""
    reported = make_reported_appraisal(
        api,
        parcel_id,
        appraiser_id,
        appraised_value_cents=appraised_value_cents,
        effective_date=effective_date,
        **order_overrides,
    )
    return accept_appraisal(api, reported["id"])


def file_challenge(
    api: ApiClient,
    appraisal_id: str,
    challenger_agency_id: str,
    asserted_value_cents: int = 90000000,
    deposit_paid_cents: int = 1000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A noticed preference entity challenges the reported value."""
    return get_success_data(
        api.file_challenge(
            appraisal_id,
            f.challenge_payload(asserted_value_cents, deposit_paid_cents, **overrides),
            make_agency_representative_headers(challenger_agency_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3 — declaration, notices, preference negotiation, environmental review
# ---------------------------------------------------------------------------


def make_declaration(api: ApiClient, parcel_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft a declaration of surplus against a parcel."""
    return get_success_data(
        api.create_declaration(f.declaration_payload(parcel_id, **overrides), OFFICER_HEADERS)
    )


def adopt_declaration(api: ApiClient, declaration_id: str, **overrides: Any) -> Dict[str, Any]:
    """The board adopts the surplus resolution."""
    return get_success_data(
        api.adopt_declaration(
            declaration_id, f.adopt_payload(**overrides), CLERK_ADOPT_HEADERS
        )
    )


def make_adopted_declaration(
    api: ApiClient, parcel_id: str, resolution_number: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Draft a declaration and carry it through board adoption."""
    declaration = make_declaration(api, parcel_id, **overrides)
    adopt_kwargs = {} if resolution_number is None else {"resolution_number": resolution_number}
    return adopt_declaration(api, declaration["id"], **adopt_kwargs)


def make_exempt_review(api: ApiClient, declaration_id: str, **overrides: Any) -> Dict[str, Any]:
    """File an exempt environmental determination, which is certified on filing."""
    return get_success_data(
        api.create_environmental_review(
            declaration_id, f.exempt_review_payload(**overrides), OFFICER_HEADERS
        )
    )


def make_circulating_review(
    api: ApiClient, declaration_id: str, **overrides: Any
) -> Dict[str, Any]:
    """File a determination that must circulate for the statutory minimum."""
    return get_success_data(
        api.create_environmental_review(
            declaration_id, f.circulating_review_payload(**overrides), OFFICER_HEADERS
        )
    )


def certify_review(api: ApiClient, review_id: str) -> Dict[str, Any]:
    """Certify a circulated environmental document."""
    return get_success_data(api.certify_environmental_review(review_id, OFFICER_HEADERS))


def issue_notices(
    api: ApiClient,
    declaration_id: str,
    recipient_agency_ids: List[str],
    response_window_days: Optional[int] = 60,
    **overrides: Any,
) -> List[Dict[str, Any]]:
    """Serve the statutory notice of availability and return the notices served."""
    get_success_data(
        api.issue_notices(
            declaration_id,
            f.issue_notices_payload(recipient_agency_ids, response_window_days, **overrides),
            OFFICER_HEADERS,
        )
    )
    return list_notices(api, declaration_id)


def list_notices(api: ApiClient, declaration_id: str) -> List[Dict[str, Any]]:
    """Every notice served under one declaration."""
    return get_success_data(
        api.list_notices(OFFICER_HEADERS, {"declaration_id": declaration_id, "limit": 100})
    )


def notice_for_recipient(
    api: ApiClient, declaration_id: str, recipient_agency_id: str
) -> Dict[str, Any]:
    """The notice served on one named recipient under a declaration."""
    notice = find_row(
        list_notices(api, declaration_id), recipient_agency_id=recipient_agency_id
    )
    assert notice is not None, (
        f"no notice was served on agency {recipient_agency_id} "
        f"under declaration {declaration_id}"
    )
    return notice


def decline_notice(api: ApiClient, notice_id: str, recipient_agency_id: str) -> Dict[str, Any]:
    """The noticed agency declines the statutory offer."""
    return get_success_data(
        api.respond_to_notice(
            notice_id,
            f.decline_response_payload(),
            make_agency_representative_headers(recipient_agency_id),
        )
    )


def express_interest(
    api: ApiClient,
    notice_id: str,
    recipient_agency_id: str,
    claimed_preference_category: str = "AFFORDABLE_HOUSING",
    **overrides: Any,
) -> Dict[str, Any]:
    """The noticed preference entity expresses statutory interest, opening an offer."""
    return get_success_data(
        api.respond_to_notice(
            notice_id,
            f.express_interest_payload(claimed_preference_category, **overrides),
            make_agency_representative_headers(recipient_agency_id),
        )
    )


def close_preference_window(api: ApiClient, declaration_id: str) -> Dict[str, Any]:
    """Close the statutory response window on a noticed declaration."""
    return get_success_data(
        api.close_preference_window(declaration_id, OFFICER_HEADERS)
    )


def authorize_disposition(
    api: ApiClient, declaration_id: str, disposition_type: str = "COMPETITIVE_SALE", **overrides: Any
) -> Dict[str, Any]:
    """The board fixes the authorized disposition route."""
    return get_success_data(
        api.authorize_disposition(
            declaration_id,
            f.authorize_payload(disposition_type, **overrides),
            CLERK_AUTHORIZE_HEADERS,
        )
    )


def offer_for_declaration(api: ApiClient, declaration_id: str) -> Dict[str, Any]:
    """The single preference offer opened under one declaration."""
    offers = get_success_data(
        api.list_preference_offers(
            OFFICER_HEADERS, {"declaration_id": declaration_id, "limit": 100}
        )
    )
    assert len(offers) == 1, (
        f"expected exactly one preference offer under declaration {declaration_id}, "
        f"got {len(offers)}"
    )
    return offers[0]


def append_officer_round(
    api: ApiClient, offer_id: str, price_offered_cents: int, **overrides: Any
) -> Dict[str, Any]:
    """The custodian agency writes one negotiation round."""
    return get_success_data(
        api.append_round(
            offer_id, f.officer_round_payload(price_offered_cents, **overrides), OFFICER_HEADERS
        )
    )


def append_entity_round(
    api: ApiClient,
    offer_id: str,
    offeror_agency_id: str,
    price_offered_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """The preference entity writes one negotiation round."""
    return get_success_data(
        api.append_round(
            offer_id,
            f.entity_round_payload(price_offered_cents, **overrides),
            make_agency_representative_headers(offeror_agency_id),
        )
    )


def open_good_faith_review(api: ApiClient, offer_id: str) -> Dict[str, Any]:
    """Compliance opens the good-faith review on the negotiation record."""
    return get_success_data(api.open_good_faith_review(offer_id, COMPLIANCE_HEADERS))


def determine_good_faith(
    api: ApiClient, offer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Compliance rules on whether the agency negotiated in good faith."""
    return get_success_data(
        api.determine_good_faith(offer_id, COMPLIANCE_HEADERS, dict(overrides))
    )


def grade_good_faith(api: ApiClient, offer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open the good-faith review and determine it in one step."""
    open_good_faith_review(api, offer_id)
    return determine_good_faith(api, offer_id, **overrides)


def sustain_challenge(
    api: ApiClient, challenge_id: str, revised_value_cents: int = 92000000
) -> Dict[str, Any]:
    """The board sustains the challenge at a revised value."""
    return get_success_data(
        api.determine_challenge(
            challenge_id,
            f.sustain_determination_payload(revised_value_cents),
            CLERK_DETERMINE_HEADERS,
        )
    )


def deny_challenge(api: ApiClient, challenge_id: str) -> Dict[str, Any]:
    """The board denies the challenge, forfeiting the deposit."""
    return get_success_data(
        api.determine_challenge(
            challenge_id, f.deny_determination_payload(), CLERK_DETERMINE_HEADERS
        )
    )


def conclude_agreed(api: ApiClient, offer_id: str, agreed_price_cents: int) -> Dict[str, Any]:
    """Conclude the negotiation as agreed at a price."""
    return get_success_data(
        api.conclude_negotiation(
            offer_id, f.conclude_agreed_payload(agreed_price_cents), OFFICER_HEADERS
        )
    )


def conclude_impasse(api: ApiClient, offer_id: str) -> Dict[str, Any]:
    """Conclude the negotiation at an impasse."""
    return get_success_data(
        api.conclude_negotiation(offer_id, f.conclude_impasse_payload(), OFFICER_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 4 — offering, bids and award
# ---------------------------------------------------------------------------


def make_offering(api: ApiClient, declaration_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create an offering, reading the declaration's version as the OCC token."""
    version = declaration_version(api, declaration_id)
    return get_success_data(
        api.create_offering(
            f.offering_payload(declaration_id, version, **overrides), OFFICER_HEADERS
        )
    )


def publish_offering(api: ApiClient, offering_id: str) -> Dict[str, Any]:
    """Publish the offering, opening it for bids."""
    return get_success_data(api.publish_offering(offering_id, OFFICER_HEADERS))


def make_published_offering(
    api: ApiClient, declaration_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create and publish an offering in one step."""
    offering = make_offering(api, declaration_id, **overrides)
    return publish_offering(api, offering["id"])


def submit_bid(
    api: ApiClient,
    offering_id: str,
    bidder_id: str,
    amount_cents: int = 108000000,
    deposit_amount_cents: int = 5000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """The bidder submits a sealed bid with its deposit."""
    return get_success_data(
        api.submit_bid(
            offering_id,
            f.bid_payload(amount_cents, deposit_amount_cents, **overrides),
            make_bidder_headers(bidder_id),
        )
    )


def close_bidding(api: ApiClient, offering_id: str) -> Dict[str, Any]:
    """Close bidding on the offering."""
    return get_success_data(api.close_bidding(offering_id, OFFICER_HEADERS))


def award_offering(api: ApiClient, offering_id: str) -> Dict[str, Any]:
    """The board awards the offering to the highest qualified bid."""
    return get_success_data(api.award_offering(offering_id, CLERK_AWARD_HEADERS))


def withdraw_bid(api: ApiClient, bid_id: str, bidder_id: str) -> Dict[str, Any]:
    """The bidder withdraws its bid before bidding closes."""
    return get_success_data(api.withdraw_bid(bid_id, make_bidder_headers(bidder_id)))


def bids_for_offering(api: ApiClient, offering_id: str) -> List[Dict[str, Any]]:
    """Every bid recorded against one offering."""
    return get_success_data(
        api.list_bids(OFFICER_HEADERS, {"offering_id": offering_id, "limit": 100})
    )


# ---------------------------------------------------------------------------
# Tier 4 — conveyance and compliance
# ---------------------------------------------------------------------------


def make_conveyance(api: ApiClient, offering_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open the conveyance file on an awarded offering."""
    return get_success_data(
        api.create_conveyance(offering_id, f.conveyance_payload(**overrides), OFFICER_HEADERS)
    )


def clear_title(api: ApiClient, conveyance_id: str) -> Dict[str, Any]:
    """Clear title on the conveyance, freezing the net proceeds."""
    return get_success_data(api.clear_title(conveyance_id, OFFICER_HEADERS))


def record_conveyance(
    api: ApiClient, conveyance_id: str, instrument_number: Optional[str] = None
) -> Dict[str, Any]:
    """Record the deed, running the proceeds waterfall."""
    payload = (
        f.record_payload()
        if instrument_number is None
        else f.record_payload(recorded_instrument_number=instrument_number)
    )
    return get_success_data(api.record_conveyance(conveyance_id, payload, OFFICER_HEADERS))


def notice_violation(api: ApiClient, conveyance_id: str, **overrides: Any) -> Dict[str, Any]:
    """Notice a breach of a recorded deed restriction."""
    return get_success_data(
        api.notice_violation(
            conveyance_id, f.violation_notice_payload(**overrides), COMPLIANCE_HEADERS
        )
    )


def accept_cure(api: ApiClient, conveyance_id: str, **overrides: Any) -> Dict[str, Any]:
    """Accept the grantee's cure inside the cure period."""
    return get_success_data(
        api.accept_cure(conveyance_id, f.accept_cure_payload(**overrides), COMPLIANCE_HEADERS)
    )


def revert_conveyance(api: ApiClient, conveyance_id: str) -> Dict[str, Any]:
    """Revert title to the agency after an uncured breach."""
    return get_success_data(api.revert_conveyance(conveyance_id, COMPLIANCE_HEADERS))


def allocations_for_conveyance(api: ApiClient, conveyance_id: str) -> List[Dict[str, Any]]:
    """Every proceeds allocation row written for one conveyance."""
    return get_success_data(
        api.list_conveyance_allocations(conveyance_id, FINANCE_HEADERS, {"limit": 100})
    )


# ---------------------------------------------------------------------------
# Tier 5 — whole-spine builders
#
# Each builder takes the store from wherever the previous one left it to the
# next milestone and returns a context dictionary. Later builders accept the
# context of an earlier one, so a test can stop at whatever milestone it needs.
# ---------------------------------------------------------------------------


def build_valued_parcel(
    api: ApiClient,
    apn: Optional[str] = None,
    license_number: Optional[str] = None,
    appraised_value_cents: int = 100000000,
    effective_date: str = DEFAULT_CLOCK,
    book_value_cents: int = 70000000,
    cured_lien_actual_cents: Optional[int] = None,
    lien_estimate_cents: int = 400000,
    accept: bool = True,
    **parcel_overrides: Any,
) -> Dict[str, Any]:
    """A parcel held by a custodian agency with an accepted governing valuation.

    When ``cured_lien_actual_cents`` is given a lien is opened and cured at that
    actual cost before the appraisal is ordered, so the deduction it produces
    flows into the minimum price.
    """
    agency = make_agency(api)
    parcel_kwargs = dict(parcel_overrides)
    if apn is not None:
        parcel_kwargs["apn"] = apn
    parcel = make_parcel(
        api, agency["id"], book_value_cents=book_value_cents, **parcel_kwargs
    )
    title_item = None
    if cured_lien_actual_cents is not None:
        title_item = add_cured_lien(
            api, parcel["id"], lien_estimate_cents, cured_lien_actual_cents
        )
    appraiser_kwargs = {} if license_number is None else {"license_number": license_number}
    appraiser = make_appraiser(api, **appraiser_kwargs)
    if accept:
        appraisal = make_accepted_appraisal(
            api,
            parcel["id"],
            appraiser["id"],
            appraised_value_cents=appraised_value_cents,
            effective_date=effective_date,
        )
    else:
        appraisal = make_reported_appraisal(
            api,
            parcel["id"],
            appraiser["id"],
            appraised_value_cents=appraised_value_cents,
            effective_date=effective_date,
        )
    return {
        "agency": agency,
        "parcel": parcel,
        "title_item": title_item,
        "appraiser": appraiser,
        "appraisal": appraisal,
        "appraised_value_cents": appraised_value_cents,
        "book_value_cents": book_value_cents,
        "cure_deduction_cents": cured_lien_actual_cents or 0,
    }


def build_adopted_declaration(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    resolution_number: Optional[str] = None,
    **valued_parcel_kwargs: Any,
) -> Dict[str, Any]:
    """A parcel with an accepted valuation and a board-adopted surplus declaration."""
    ctx = dict(ctx) if ctx is not None else build_valued_parcel(api, **valued_parcel_kwargs)
    declaration = make_declaration(api, ctx["parcel"]["id"])
    adopt_kwargs = {} if resolution_number is None else {"resolution_number": resolution_number}
    ctx["declaration"] = adopt_declaration(api, declaration["id"], **adopt_kwargs)
    return ctx


def build_authorized_declaration(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    disposition_type: str = "COMPETITIVE_SALE",
    response_window_days: int = 60,
    **adopted_kwargs: Any,
) -> Dict[str, Any]:
    """A declaration carried through notice, a declined response and authorization.

    One neighbouring district is noticed and declines, so the statutory window
    closes with no unresolved preference and the board can fix the disposition.
    """
    ctx = (
        dict(ctx)
        if ctx is not None and "declaration" in ctx
        else build_adopted_declaration(api, ctx, **adopted_kwargs)
    )
    ctx["environmental_review"] = make_exempt_review(api, ctx["declaration"]["id"])
    recipient = make_transit_agency(api)
    ctx["recipient_agency"] = recipient
    notices = issue_notices(
        api, ctx["declaration"]["id"], [recipient["id"]], response_window_days
    )
    ctx["notices"] = notices
    notice = find_row(notices, recipient_agency_id=recipient["id"])
    assert notice is not None, "the noticed district must appear in the notice list"
    ctx["notice"] = notice
    decline_notice(api, notice["id"], recipient["id"])
    close_preference_window(api, ctx["declaration"]["id"])
    ctx["declaration"] = authorize_disposition(
        api, ctx["declaration"]["id"], disposition_type
    )
    return ctx


def build_published_offering(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    bid_open_at: str = DEFAULT_CLOCK,
    bid_close_at: str = "2026-12-31T00:00:00Z",
    offering_type: str = "COMPETITIVE_SALE",
    publish: bool = True,
    **authorized_kwargs: Any,
) -> Dict[str, Any]:
    """An authorized declaration with a published offering open for bids."""
    ctx = (
        dict(ctx)
        if ctx is not None and ctx.get("declaration", {}).get("status") == "OFFERING_AUTHORIZED"
        else build_authorized_declaration(api, ctx, **authorized_kwargs)
    )
    offering = make_offering(
        api,
        ctx["declaration"]["id"],
        offering_type=offering_type,
        bid_open_at=bid_open_at,
        bid_close_at=bid_close_at,
    )
    if publish:
        offering = publish_offering(api, offering["id"])
    ctx["offering"] = offering
    ctx["bid_close_at"] = bid_close_at
    return ctx


def build_awarded_offering(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    bid_amount_cents: int = 108000000,
    bidder_funding_cents: int = 10000000,
    **published_kwargs: Any,
) -> Dict[str, Any]:
    """A published offering with one qualified bid, closed and awarded.

    The deposit posted is exactly the offering's own required deposit, and the
    clock is advanced to the close instant before bidding is closed.
    """
    ctx = (
        dict(ctx)
        if ctx is not None and "offering" in ctx
        else build_published_offering(api, ctx, **published_kwargs)
    )
    bidder = make_funded_bidder(api, bidder_funding_cents)
    ctx["bidder"] = bidder
    ctx["bid"] = submit_bid(
        api,
        ctx["offering"]["id"],
        bidder["id"],
        amount_cents=bid_amount_cents,
        deposit_amount_cents=ctx["offering"]["required_deposit_cents"],
    )
    set_clock(api, ctx["bid_close_at"])
    ctx["offering"] = close_bidding(api, ctx["offering"]["id"])
    ctx["offering"] = award_offering(api, ctx["offering"]["id"])
    return ctx


def build_conveyance(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    closing_costs_cents: int = 1249999,
    broker_fee_cents: int = 1500000,
    reverter_cure_period_days: Optional[int] = 30,
    **awarded_kwargs: Any,
) -> Dict[str, Any]:
    """An awarded offering with its conveyance file opened and awaiting title."""
    ctx = (
        dict(ctx)
        if ctx is not None and "bid" in ctx
        else build_awarded_offering(api, ctx, **awarded_kwargs)
    )
    ctx["conveyance"] = make_conveyance(
        api,
        ctx["offering"]["id"],
        closing_costs_cents=closing_costs_cents,
        broker_fee_cents=broker_fee_cents,
        reverter_cure_period_days=reverter_cure_period_days,
    )
    return ctx


def build_cleared_conveyance(
    api: ApiClient, ctx: Optional[Dict[str, Any]] = None, **conveyance_kwargs: Any
) -> Dict[str, Any]:
    """A conveyance whose title is clear and whose net proceeds are frozen."""
    ctx = (
        dict(ctx)
        if ctx is not None and "conveyance" in ctx
        else build_conveyance(api, ctx, **conveyance_kwargs)
    )
    ctx["conveyance"] = clear_title(api, ctx["conveyance"]["id"])
    return ctx


def build_recorded_conveyance(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    fund_specs: Optional[List[Dict[str, Any]]] = None,
    instrument_number: Optional[str] = None,
    **cleared_kwargs: Any,
) -> Dict[str, Any]:
    """A recorded deed with the proceeds waterfall already run.

    Funds are configured before the deed is recorded, because the waterfall
    distributes across the funds standing at the moment of recording. With no
    specification a single fund takes the whole distribution.
    """
    if ctx is None or "funds" not in ctx:
        funds = (
            make_fund_ladder(api, fund_specs)
            if fund_specs is not None
            else [make_single_fund(api)]
        )
    else:
        funds = ctx["funds"]
    ctx = (
        dict(ctx)
        if ctx is not None and ctx.get("conveyance", {}).get("recording_status") == "READY_TO_RECORD"
        else build_cleared_conveyance(api, ctx, **cleared_kwargs)
    )
    ctx["funds"] = funds
    ctx["conveyance"] = record_conveyance(
        api, ctx["conveyance"]["id"], instrument_number
    )
    return ctx


def build_violation_noticed_conveyance(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    noticed_at: str = "2027-01-15T00:00:00Z",
    **recorded_kwargs: Any,
) -> Dict[str, Any]:
    """A recorded deed whose restriction has been breached and noticed.

    The clock is advanced to the notice instant first, because the cure deadline
    is measured from the moment the notice is served.
    """
    ctx = (
        dict(ctx)
        if ctx is not None and ctx.get("conveyance", {}).get("recording_status") == "RECORDED"
        else build_recorded_conveyance(api, ctx, **recorded_kwargs)
    )
    set_clock(api, noticed_at)
    ctx["conveyance"] = notice_violation(api, ctx["conveyance"]["id"])
    ctx["violation_noticed_at"] = noticed_at
    return ctx


def build_preference_offer(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    preference_category: str = "AFFORDABLE_HOUSING",
    response_window_days: int = 60,
    **adopted_kwargs: Any,
) -> Dict[str, Any]:
    """An adopted declaration noticed to a preference entity that claims its right.

    The expressed interest opens the negotiation, so the returned context carries
    the offer as well as the entity that holds it.
    """
    ctx = (
        dict(ctx)
        if ctx is not None and "declaration" in ctx
        else build_adopted_declaration(api, ctx, **adopted_kwargs)
    )
    ctx.setdefault(
        "environmental_review", make_exempt_review(api, ctx["declaration"]["id"])
    )
    entity = make_preference_agency(api, preference_category)
    ctx["preference_agency"] = entity
    notices = issue_notices(
        api, ctx["declaration"]["id"], [entity["id"]], response_window_days
    )
    ctx["notices"] = notices
    notice = find_row(notices, recipient_agency_id=entity["id"])
    assert notice is not None, "the noticed preference entity must appear in the notice list"
    ctx["notice"] = notice
    express_interest(api, notice["id"], entity["id"], preference_category)
    ctx["offer"] = offer_for_declaration(api, ctx["declaration"]["id"])
    return ctx


def build_negotiated_preference_offer(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    officer_prices: Optional[List[int]] = None,
    entity_prices: Optional[List[int]] = None,
    **offer_kwargs: Any,
) -> Dict[str, Any]:
    """A preference offer with a written negotiation record.

    Rounds alternate, the custodian agency opening each exchange and the entity
    answering it, so the record shows a two-sided negotiation.
    """
    ctx = (
        dict(ctx)
        if ctx is not None and "offer" in ctx
        else build_preference_offer(api, ctx, **offer_kwargs)
    )
    officer_prices = officer_prices if officer_prices is not None else [65000000, 63000000, 62000000]
    entity_prices = entity_prices if entity_prices is not None else [58000000, 60000000, 61000000]
    rounds = []
    entity_id = ctx["preference_agency"]["id"]
    for index in range(max(len(officer_prices), len(entity_prices))):
        if index < len(officer_prices):
            rounds.append(append_officer_round(api, ctx["offer"]["id"], officer_prices[index]))
        if index < len(entity_prices):
            rounds.append(
                append_entity_round(
                    api,
                    ctx["offer"]["id"],
                    entity_id,
                    entity_prices[index],
                    responded_to_round_number=len(rounds),
                )
            )
    ctx["rounds"] = rounds
    ctx["offer"] = get_success_data(
        api.get_preference_offer(ctx["offer"]["id"], OFFICER_HEADERS)
    )
    return ctx


def build_challengeable_appraisal(
    api: ApiClient,
    appraised_value_cents: int = 100000000,
    preference_category: str = "AFFORDABLE_HOUSING",
    **valued_parcel_kwargs: Any,
) -> Dict[str, Any]:
    """A reported valuation on a declaration noticed to a preference entity.

    The valuation is left reported rather than accepted, because a challenge is
    only open against the report while the challenge window runs.
    """
    ctx = build_valued_parcel(
        api, appraised_value_cents=appraised_value_cents, accept=False, **valued_parcel_kwargs
    )
    ctx = build_preference_offer(api, ctx, preference_category=preference_category)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — dated negotiation records
# ---------------------------------------------------------------------------

#: A five-round record in which the custodian agency opens, the entity answers
#: each opening within a fortnight, and the agency's last price lands inside the
#: near band of the floor it quoted.
NEAR_BAND_ROUND_SCHEDULE = (
    {
        "party": "CUSTODIAN_AGENCY",
        "price_offered_cents": 80000000,
        "at": "2026-08-01T00:00:00Z",
    },
    {
        "party": "PREFERENCE_ENTITY",
        "price_offered_cents": 60000000,
        "at": "2026-08-05T00:00:00Z",
        "responded_to_round_number": 1,
    },
    {
        "party": "CUSTODIAN_AGENCY",
        "price_offered_cents": 70000000,
        "at": "2026-08-10T00:00:00Z",
        "responded_to_round_number": 2,
    },
    {
        "party": "PREFERENCE_ENTITY",
        "price_offered_cents": 62000000,
        "at": "2026-08-15T00:00:00Z",
        "responded_to_round_number": 3,
    },
    {
        "party": "CUSTODIAN_AGENCY",
        "price_offered_cents": 66000000,
        "at": "2026-08-20T00:00:00Z",
        "responded_to_round_number": 4,
    },
)


def append_timed_rounds(
    api: ApiClient,
    offer_id: str,
    entity_agency_id: str,
    schedule: Any = NEAR_BAND_ROUND_SCHEDULE,
) -> List[Dict[str, Any]]:
    """Append a dated round log, moving the clock to each round's own instant.

    Each entry names the party, the price tendered, the instant the round was
    written and optionally the round it answers, so the elapsed days that decide
    timeliness are under the caller's control.
    """
    rounds: List[Dict[str, Any]] = []
    for step in schedule:
        set_clock(api, step["at"])
        reference = step.get("responded_to_round_number")
        extra = {} if reference is None else {"responded_to_round_number": reference}
        if step["party"] == "CUSTODIAN_AGENCY":
            rounds.append(
                append_officer_round(
                    api, offer_id, step["price_offered_cents"], **extra
                )
            )
        else:
            rounds.append(
                append_entity_round(
                    api,
                    offer_id,
                    entity_agency_id,
                    step["price_offered_cents"],
                    **extra,
                )
            )
    return rounds


def build_graded_impasse_offer(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    schedule: Any = NEAR_BAND_ROUND_SCHEDULE,
    impasse_at: str = "2026-10-30T00:00:00Z",
    remediation_note: str = "Five rounds exchanged; the last agency price sat inside the near band.",
    **offer_kwargs: Any,
) -> Dict[str, Any]:
    """A preference offer bargained on a dated record, concluded and graded.

    The window is closed once the record is complete, the negotiation is
    concluded at impasse on the deadline instant so no premature-impasse penalty
    arises, and compliance then opens and rules on the good-faith review. The
    context keeps the offer as it read when the last round landed, so a caller
    can inspect the interim score alongside the frozen final score.
    """
    ctx = (
        dict(ctx)
        if ctx is not None and "offer" in ctx
        else build_preference_offer(api, ctx, **offer_kwargs)
    )
    ctx["rounds"] = append_timed_rounds(
        api, ctx["offer"]["id"], ctx["preference_agency"]["id"], schedule
    )
    ctx["offer_after_rounds"] = get_success_data(
        api.get_preference_offer(ctx["offer"]["id"], OFFICER_HEADERS)
    )
    close_preference_window(api, ctx["declaration"]["id"])
    set_clock(api, impasse_at)
    ctx["impasse_at"] = impasse_at
    ctx["offer"] = conclude_impasse(api, ctx["offer"]["id"])
    open_good_faith_review(api, ctx["offer"]["id"])
    ctx["offer"] = determine_good_faith(
        api, ctx["offer"]["id"], remediation_note=remediation_note
    )
    return ctx


def build_offering_after_impasse(
    api: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    bid_open_at: str = "2026-12-01T00:00:00Z",
    bid_close_at: str = "2026-12-31T00:00:00Z",
    **impasse_kwargs: Any,
) -> Dict[str, Any]:
    """A competitive offering created on a declaration whose preference offer failed."""
    ctx = (
        dict(ctx)
        if ctx is not None and ctx.get("offer", {}).get("negotiation_status") == "IMPASSE"
        else build_graded_impasse_offer(api, ctx, **impasse_kwargs)
    )
    ctx["declaration"] = authorize_disposition(
        api, ctx["declaration"]["id"], "COMPETITIVE_SALE"
    )
    ctx["offering"] = make_offering(
        api,
        ctx["declaration"]["id"],
        bid_open_at=bid_open_at,
        bid_close_at=bid_close_at,
    )
    ctx["bid_close_at"] = bid_close_at
    return ctx
