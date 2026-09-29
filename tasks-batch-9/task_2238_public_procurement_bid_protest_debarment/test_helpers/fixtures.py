"""State-building fixtures.

Tier 1 wraps the logical clock. Tier 2 wraps every write endpoint as a
"happy-path primitive" that asserts success and returns the created or updated
resource. Tier 3 offers read helpers. Tier 4 composes the primitives into the
multi-step states the workflows require — an issued solicitation, a solicitation
whose bids have been opened, an award pending the statutory stay, a protest at
each of its stages, a debarred vendor, an interim-suspended vendor. Tier 5
holds small computation helpers shared by several tests.

Every fixture builds its state exclusively through the public API, because each
test starts against an empty database.
"""
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ADMIN_HEADERS,
    DEBARMENT_AUTHORITY_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_vendor_headers,
)

# Canonical instants of the default procurement calendar.
CLOCK_START = DEFAULT_CLOCK_UTC                  # 2026-08-01T00:00:00Z
CLOCK_QUESTION_DEADLINE = "2026-08-20T00:00:00Z"
CLOCK_BID_DUE = "2026-08-27T00:00:00Z"


# ==========================================================================
# Tier 1 — the logical clock
# ==========================================================================
def set_clock(to_iso8601: str) -> None:
    response = api_client.set_clock(f.clock_payload(to_iso8601), ADMIN_HEADERS)
    validate_success(response)


def reset_clock() -> None:
    set_clock(DEFAULT_CLOCK_UTC)


# ==========================================================================
# Tier 2 — one happy-path primitive per write endpoint
# ==========================================================================
def create_vendor(**kwargs: Any) -> Dict[str, Any]:
    response = api_client.create_vendor(f.vendor_payload(**kwargs), ADMIN_HEADERS)
    return get_success_data(response, expected_status=201)


def fund_vendor(vendor_id: str, amount_cents: int = 200000) -> Dict[str, Any]:
    response = api_client.create_fee_deposit(
        vendor_id, f.fee_deposit_payload(amount_cents), ADMIN_HEADERS
    )
    return get_success_data(response)


def create_funded_vendor(amount_cents: int = 200000, **kwargs: Any) -> Dict[str, Any]:
    """A vendor whose protest purse already holds `amount_cents`."""
    vendor = create_vendor(**kwargs)
    fund_vendor(vendor["id"], amount_cents)
    return read_vendor(vendor["id"])


def create_solicitation(headers: Optional[Dict[str, str]] = None, **kwargs: Any) -> Dict[str, Any]:
    response = api_client.create_solicitation(
        f.solicitation_payload(**kwargs), headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def issue_solicitation(
    solicitation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.issue_solicitation(solicitation_id, headers or OFFICER_HEADERS)
    return get_success_data(response)


def add_addendum(
    solicitation_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.create_addendum(
        solicitation_id, f.addendum_payload(**kwargs), headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def submit_question(
    solicitation_id: str, vendor_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.submit_question(
        solicitation_id,
        f.question_payload(vendor_id, **kwargs),
        make_vendor_headers(vendor_id),
    )
    return get_success_data(response, expected_status=201)


def close_question_period(
    solicitation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.close_question_period(
        solicitation_id, headers or OFFICER_HEADERS
    )
    return get_success_data(response)


def open_bids(
    solicitation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.open_bids(solicitation_id, headers or OFFICER_HEADERS)
    return get_success_data(response)


def cancel_solicitation(solicitation_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api_client.cancel_solicitation(
        solicitation_id, f.cancel_payload(**kwargs), OFFICER_HEADERS
    )
    return get_success_data(response)


def resolicit(solicitation_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api_client.resolicit_solicitation(
        solicitation_id, f.resolicit_payload(**kwargs), OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def submit_bid(
    solicitation_id: str,
    vendor_id: str,
    total_price_cents: int = 12000000,
    acknowledged_addendum_sequences: Optional[List[int]] = None,
    expected_solicitation_version: Optional[int] = None,
) -> Dict[str, Any]:
    """File a sealed bid, pinning the solicitation version the bid was priced
    against. When the caller does not pin a version the current one is read
    first, which is what an honest bidder would do."""
    version = (
        expected_solicitation_version
        if expected_solicitation_version is not None
        else solicitation_version(solicitation_id)
    )
    response = api_client.create_bid(
        f.bid_payload(
            solicitation_id,
            vendor_id,
            total_price_cents=total_price_cents,
            acknowledged_addendum_sequences=acknowledged_addendum_sequences,
            expected_solicitation_version=version,
        ),
        make_vendor_headers(vendor_id),
    )
    return get_success_data(response, expected_status=201)


def determine_responsiveness(
    bid_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.determine_responsiveness(
        bid_id, f.responsiveness_payload(**kwargs), headers or OFFICER_HEADERS
    )
    return get_success_data(response)


def review_responsibility(
    bid_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.create_responsibility_review(
        bid_id, f.responsibility_review_payload(**kwargs), headers or REVIEWER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def create_award(
    solicitation_id: str, winning_bid_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.create_award(
        f.award_payload(solicitation_id, winning_bid_id), headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def execute_award(award_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    response = api_client.execute_award(award_id, headers or OFFICER_HEADERS)
    return get_success_data(response)


def file_protest(
    solicitation_id: str, protester_vendor_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.create_protest(
        f.protest_payload(solicitation_id, protester_vendor_id, **kwargs),
        make_vendor_headers(protester_vendor_id),
    )
    return get_success_data(response, expected_status=201)


def add_record_item(
    protest_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.create_record_item(
        protest_id, f.record_item_payload(**kwargs), headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def schedule_hearing(
    protest_id: str,
    hearing_officer_user_id: str = HEARING_OFFICER_USER_ID,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    response = api_client.create_hearing(
        protest_id,
        f.hearing_payload(hearing_officer_user_id, **kwargs),
        headers or HEARING_OFFICER_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def convene_hearing(
    hearing_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.convene_hearing(hearing_id, headers or HEARING_OFFICER_HEADERS)
    return get_success_data(response)


def continue_hearing(
    hearing_id: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    response = api_client.continue_hearing(
        hearing_id,
        f.continuance_payload(scheduled_start_utc, scheduled_end_utc, **kwargs),
        headers or HEARING_OFFICER_HEADERS,
    )
    return get_success_data(response)


def conclude_hearing(
    hearing_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.conclude_hearing(
        hearing_id, headers or HEARING_OFFICER_HEADERS
    )
    return get_success_data(response)


def decide_protest(
    protest_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.decide_protest(
        protest_id, f.protest_decision_payload(**kwargs), headers or HEARING_OFFICER_HEADERS
    )
    return get_success_data(response)


def withdraw_protest(
    protest_id: str, protester_vendor_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.withdraw_protest(
        protest_id, f.withdraw_payload(**kwargs), make_vendor_headers(protester_vendor_id)
    )
    return get_success_data(response)


def override_stay(protest_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api_client.override_stay(
        protest_id, f.stay_override_payload(**kwargs), OFFICER_HEADERS
    )
    return get_success_data(response)


def open_proceeding(
    vendor_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.create_debarment_proceeding(
        f.proceeding_payload(vendor_id, **kwargs),
        headers or DEBARMENT_AUTHORITY_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def file_debarment_response(
    proceeding_id: str, vendor_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.file_debarment_response(
        proceeding_id,
        f.debarment_response_payload(**kwargs),
        make_vendor_headers(vendor_id),
    )
    return get_success_data(response)


def hold_debarment_hearing(
    proceeding_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.hold_debarment_hearing(
        proceeding_id,
        f.debarment_hearing_payload(**kwargs),
        headers or DEBARMENT_AUTHORITY_HEADERS,
    )
    return get_success_data(response)


def decide_debarment(
    proceeding_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.decide_debarment(
        proceeding_id,
        f.debarment_decision_payload(**kwargs),
        headers or DEBARMENT_AUTHORITY_HEADERS,
    )
    return get_success_data(response)


def file_petition(
    proceeding_id: str,
    vendor_id: str,
    expected_proceeding_version: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    version = (
        expected_proceeding_version
        if expected_proceeding_version is not None
        else proceeding_version(proceeding_id)
    )
    response = api_client.create_reinstatement_petition(
        proceeding_id,
        f.petition_payload(expected_proceeding_version=version, **kwargs),
        make_vendor_headers(vendor_id),
    )
    return get_success_data(response, expected_status=201)


def decide_petition(
    petition_id: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    response = api_client.decide_reinstatement_petition(
        petition_id,
        f.petition_decision_payload(**kwargs),
        headers or DEBARMENT_AUTHORITY_HEADERS,
    )
    return get_success_data(response)


def screen_subcontractor(
    solicitation_id: str,
    prime_vendor_id: str,
    sub_vendor_id: str,
    tier: int = 1,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_subcontractor_screening(
        f.screening_payload(solicitation_id, prime_vendor_id, sub_vendor_id, tier),
        headers or OFFICER_HEADERS,
    )
    return get_success_data(response, expected_status=201)


# ==========================================================================
# Tier 3 — read helpers
# ==========================================================================
def read_vendor(vendor_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_vendor(vendor_id, headers or OFFICER_HEADERS)
    )


def read_solicitation(
    solicitation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_solicitation(solicitation_id, headers or OFFICER_HEADERS)
    )


def read_bid(bid_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_bid(bid_id, headers or OFFICER_HEADERS)
    )


def read_award(award_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_award(award_id, headers or OFFICER_HEADERS)
    )


def read_protest(protest_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_protest(protest_id, headers or OFFICER_HEADERS)
    )


def read_hearing(hearing_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_hearing(hearing_id, headers or OFFICER_HEADERS)
    )


def read_proceeding(
    proceeding_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_debarment_proceeding(
                proceeding_id, headers or OFFICER_HEADERS
            )
    )


def read_petition(
    petition_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_reinstatement_petition(petition_id, headers or OFFICER_HEADERS)
    )


def read_screening(
    screening_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_subcontractor_screening(
                screening_id, headers or OFFICER_HEADERS
            )
    )


def solicitation_version(solicitation_id: str) -> int:
    return read_solicitation(solicitation_id)["version"]


def proceeding_version(proceeding_id: str) -> int:
    return read_proceeding(proceeding_id)["version"]


# ==========================================================================
# Tier 4 — composite states
# ==========================================================================
def setup_issued_solicitation(
    requirements: Optional[List[Dict[str, Any]]] = None, **solicitation_kwargs: Any
) -> Dict[str, Any]:
    """A solicitation advertised and open for questions, plus one eligible
    vendor able to bid on it."""
    vendor = create_vendor()
    solicitation = create_solicitation(
        mandatory_requirements=requirements, **solicitation_kwargs
    )
    solicitation = issue_solicitation(solicitation["id"])
    return {
        "vendor": vendor,
        "vendor_id": vendor["id"],
        "solicitation": solicitation,
        "solicitation_id": solicitation["id"],
    }


def setup_bids_opened(
    prices: Sequence[int] = (12000000,),
    acknowledged: Optional[Sequence[Optional[List[int]]]] = None,
    question_deadline_clock: str = CLOCK_QUESTION_DEADLINE,
    bid_due_clock: str = CLOCK_BID_DUE,
    requirements: Optional[List[Dict[str, Any]]] = None,
    **solicitation_kwargs: Any,
) -> Dict[str, Any]:
    """One solicitation walked all the way to BIDS_OPENED, with one bid per
    entry of `prices`, each filed by its own vendor."""
    solicitation = create_solicitation(
        mandatory_requirements=requirements, **solicitation_kwargs
    )
    solicitation = issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    vendors: List[Dict[str, Any]] = []
    bids: List[Dict[str, Any]] = []
    for index, price in enumerate(prices):
        vendor = create_vendor()
        vendors.append(vendor)
        acks = None
        if acknowledged is not None and index < len(acknowledged):
            acks = acknowledged[index]
        bids.append(
            submit_bid(
                solicitation_id,
                vendor["id"],
                total_price_cents=price,
                acknowledged_addendum_sequences=acks,
            )
        )

    set_clock(question_deadline_clock)
    close_question_period(solicitation_id)
    set_clock(bid_due_clock)
    solicitation = open_bids(solicitation_id)

    return {
        "solicitation": solicitation,
        "solicitation_id": solicitation_id,
        "vendors": vendors,
        "vendor_ids": [v["id"] for v in vendors],
        "bids": bids,
        "bid_ids": [b["id"] for b in bids],
    }


def setup_evaluation(
    prices: Sequence[int] = (12000000,), **kwargs: Any
) -> Dict[str, Any]:
    """BIDS_OPENED plus a RESPONSIVE determination on every bid, which carries
    the solicitation into EVALUATION and fixes the apparent low bidder."""
    state = setup_bids_opened(prices=prices, **kwargs)
    state["bids"] = [
        determine_responsiveness(bid_id, determination="RESPONSIVE")
        for bid_id in state["bid_ids"]
    ]
    state["solicitation"] = read_solicitation(state["solicitation_id"])
    return state


def setup_award_pending(
    prices: Sequence[int] = (12000000,), **kwargs: Any
) -> Dict[str, Any]:
    """EVALUATION plus a RESPONSIBLE review of the apparent low bidder, which
    carries the solicitation into AWARD_PENDING."""
    state = setup_evaluation(prices=prices, **kwargs)
    solicitation = state["solicitation"]
    apparent_low_bid_id = solicitation["apparent_low_bid_id"]
    state["apparent_low_bid_id"] = apparent_low_bid_id
    state["review"] = review_responsibility(
        apparent_low_bid_id, determination="RESPONSIBLE"
    )
    state["solicitation"] = read_solicitation(state["solicitation_id"])
    return state


def setup_award_created(
    prices: Sequence[int] = (12000000,), **kwargs: Any
) -> Dict[str, Any]:
    """AWARD_PENDING plus the notice of award, which sits in PENDING_STAY."""
    state = setup_award_pending(prices=prices, **kwargs)
    state["award"] = create_award(
        state["solicitation_id"], state["apparent_low_bid_id"]
    )
    state["award_id"] = state["award"]["id"]
    state["solicitation"] = read_solicitation(state["solicitation_id"])
    return state


def setup_protest_filed(
    grounds_code: str = "EVALUATION_ERROR",
    fee_balance_cents: int = 200000,
    prices: Sequence[int] = (12000000, 13000000),
    filed_at_clock: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A protest in FILED on a solicitation whose bids have been opened, filed
    by the vendor of the second (losing) bid, whose purse is already funded."""
    state = setup_evaluation(prices=prices, **kwargs)
    protester_vendor_id = state["vendor_ids"][-1]
    fund_vendor(protester_vendor_id, fee_balance_cents)
    if filed_at_clock is not None:
        set_clock(filed_at_clock)
    protest = file_protest(
        state["solicitation_id"], protester_vendor_id, grounds_code=grounds_code
    )
    state["protester_vendor_id"] = protester_vendor_id
    state["protest"] = protest
    state["protest_id"] = protest["id"]
    return state


def setup_protest_under_review(**kwargs: Any) -> Dict[str, Any]:
    """A protest whose agency record has been started, which moves it from
    FILED to UNDER_REVIEW."""
    state = setup_protest_filed(**kwargs)
    state["record_items"] = [
        add_record_item(state["protest_id"], item_type="AGENCY_REPORT")
    ]
    state["protest"] = read_protest(state["protest_id"])
    return state


def setup_protest_with_scheduled_hearing(
    record_item_count: int = 2,
    scheduled_start_utc: str = "2026-08-28T09:00:00Z",
    scheduled_end_utc: str = "2026-08-28T11:00:00Z",
    room_code: str = "ROOM-A",
    hearing_officer_user_id: str = HEARING_OFFICER_USER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A protest with a complete agency record and a hearing on the docket."""
    state = setup_protest_filed(**kwargs)
    item_types = ["AGENCY_REPORT", "PROTESTER_SUBMISSION", "BID_ABSTRACT"]
    state["record_items"] = [
        add_record_item(state["protest_id"], item_type=item_types[i % len(item_types)])
        for i in range(record_item_count)
    ]
    hearing = schedule_hearing(
        state["protest_id"],
        hearing_officer_user_id=hearing_officer_user_id,
        scheduled_start_utc=scheduled_start_utc,
        scheduled_end_utc=scheduled_end_utc,
        room_code=room_code,
    )
    state["hearing"] = hearing
    state["hearing_id"] = hearing["id"]
    state["protest"] = read_protest(state["protest_id"])
    return state


def setup_protest_ready_for_decision(
    scheduled_start_utc: str = "2026-08-28T09:00:00Z", **kwargs: Any
) -> Dict[str, Any]:
    """A protest whose hearing has been convened and concluded, so the decision
    may be issued."""
    state = setup_protest_with_scheduled_hearing(
        scheduled_start_utc=scheduled_start_utc, **kwargs
    )
    set_clock(scheduled_start_utc)
    convene_hearing(state["hearing_id"])
    state["hearing"] = conclude_hearing(state["hearing_id"])
    state["protest"] = read_protest(state["protest_id"])
    return state


def setup_debarred_vendor(
    aggravating_factor_codes: Sequence[str] = ("FRAUD", "BID_RIGGING"),
    cause_code: str = "FRAUD",
    decision_clock: str = "2026-08-20T00:00:00Z",
    vendor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A vendor carried all the way to DEBARRED through the default (no
    response filed) branch of the proceeding."""
    if vendor_id is None:
        vendor_id = create_vendor()["id"]
    proceeding = open_proceeding(
        vendor_id,
        cause_code=cause_code,
        aggravating_factor_codes=list(aggravating_factor_codes),
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    set_clock(decision_clock)
    hold_debarment_hearing(
        proceeding["id"], hearing_summary="no response filed; default branch recorded"
    )
    proceeding = decide_debarment(proceeding["id"], outcome="DEBARRED")
    return {
        "vendor_id": vendor_id,
        "vendor": read_vendor(vendor_id),
        "proceeding": proceeding,
        "proceeding_id": proceeding["id"],
    }


def setup_interim_suspended_vendor(
    aggravating_factor_codes: Sequence[str] = ("FRAUD",),
    cause_code: str = "FRAUD",
    vendor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A vendor suspended the instant the notice of proposed debarment issued,
    because the interim severity cleared the interim threshold."""
    if vendor_id is None:
        vendor_id = create_vendor()["id"]
    proceeding = open_proceeding(
        vendor_id,
        cause_code=cause_code,
        aggravating_factor_codes=list(aggravating_factor_codes),
        mitigating_factor_codes=[],
        interim_suspension=True,
    )
    return {
        "vendor_id": vendor_id,
        "vendor": read_vendor(vendor_id),
        "proceeding": proceeding,
        "proceeding_id": proceeding["id"],
    }


# ==========================================================================
# Tier 5 — shared computation helpers
# ==========================================================================
def find_by_id(rows: Sequence[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError("id {} not present among {}".format(row_id, [r.get("id") for r in rows]))


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
