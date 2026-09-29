"""Composite setup helpers.

Every helper builds state exclusively through the documented endpoints, using
the lenient ``get_success_data`` validator so that a broken setup step fails
with a readable message instead of a cryptic assertion inside a test.

Layered from the bottom up:
  tier 1 - one entity per call
  tier 2 - one entity plus the state transitions that make it usable
  tier 3 - the multi-entity chains the workflows need
  tier 4 - whole-scenario worlds
  tier 5 - readers and small utilities
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    ACK_DECISION_ACKNOWLEDGE,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_SELL_SIDE_ANALYST,
    COVERAGE_INITIATED,
    DECISION_APPROVE,
    DECISION_REQUEST_CHANGES,
    DEFAULT_CLOCK_UTC,
    EVENT_CONFERENCE,
    INSTRUCTION_DIVIDEND_PAYMENT,
    METRIC_EPS,
    SERVICING_GRANT_MODEL_ACCESS,
    SERVICING_SET_THREAT_LEVEL,
    TOPIC_OTHER,
)
from . import factories as f
from .test_users import (
    DISCLOSURE_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    TRANSFER_AGENT,
    TRANSFER_AGENT_2,
    make_investor_headers,
)

# ---------------------------------------------------------------------------
# Tier 5 - readers and utilities
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Move the server's logical clock (IRAdmin only)."""
    return get_success_data(api.set_clock(to_iso8601, IR_ADMIN))


def read_company(api: ApiClient, company_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_company(company_id, headers))


def read_contact(api: ApiClient, contact_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_contact(contact_id, headers))


def read_disclosure(api: ApiClient, disclosure_id: str, headers=DISCLOSURE_OFFICER) -> Dict[str, Any]:
    return get_success_data(api.get_disclosure(disclosure_id, headers))


def read_inquiry(api: ApiClient, inquiry_id: str, headers=IR_ANALYST) -> Dict[str, Any]:
    return get_success_data(api.get_inquiry(inquiry_id, headers))


def read_draft(api: ApiClient, draft_id: str, headers=IR_ANALYST) -> Dict[str, Any]:
    return get_success_data(api.get_response_draft(draft_id, headers))


def read_event(api: ApiClient, event_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_roadshow_event(event_id, headers))


def read_meeting_request(api: ApiClient, request_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_meeting_request(request_id, headers))


def read_instruction(api: ApiClient, instruction_id: str, headers=TRANSFER_AGENT) -> Dict[str, Any]:
    return get_success_data(api.get_instruction(instruction_id, headers))


def company_version(api: ApiClient, company_id: str) -> int:
    """The issuer's current version, for an ``expected_company_version`` input."""
    return read_company(api, company_id)["version"]


def contact_version(api: ApiClient, contact_id: str) -> int:
    """The contact's current version, for an ``expected_contact_version`` input."""
    return read_contact(api, contact_id)["version"]


def inquiry_version(api: ApiClient, inquiry_id: str) -> int:
    """The inquiry's current version, for an ``expected_inquiry_version`` input."""
    return read_inquiry(api, inquiry_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1 - single entities
# ---------------------------------------------------------------------------


def create_company(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_company(f.company_payload(**kwargs), IR_ADMIN))


def create_contact(api: ApiClient, company_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_contact(f.contact_payload(company_id, **kwargs), IR_ADMIN)
    )


def create_disclosure(api: ApiClient, company_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_disclosure(f.disclosure_payload(company_id, **kwargs), DISCLOSURE_OFFICER)
    )


def create_inquiry(
    api: ApiClient, company_id: str, contact_id: str, headers=IR_ANALYST, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inquiry(f.inquiry_payload(company_id, contact_id, **kwargs), headers)
    )


def create_event(api: ApiClient, company_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_roadshow_event(f.roadshow_event_payload(company_id, **kwargs), IR_ADMIN)
    )


def create_meeting_request(
    api: ApiClient, event_id: str, contact_id: str, headers=IR_ADMIN, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_meeting_request(
            f.meeting_request_payload(event_id, contact_id, **kwargs), headers
        )
    )


def create_instruction(
    api: ApiClient, company_id: str, headers=IR_ADMIN, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_instruction(f.instruction_payload(company_id, **kwargs), headers)
    )


# ---------------------------------------------------------------------------
# Tier 2 - an entity plus the transitions that make it usable
# ---------------------------------------------------------------------------


def create_holder(
    api: ApiClient,
    company_id: str,
    shares_held: int,
    display_name: str = "Institutional Holder",
    email: str = "holder@funds.test",
    contact_type: str = CONTACT_INSTITUTIONAL_HOLDER,
    nda_on_file: Optional[bool] = None,
    activist_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    """A share-holding contact on the issuer's register."""
    return create_contact(
        api,
        company_id,
        contact_type=contact_type,
        display_name=display_name,
        email=email,
        shares_held=shares_held,
        nda_on_file=nda_on_file,
        activist_flag=activist_flag,
    )


def create_analyst(
    api: ApiClient,
    company_id: str,
    display_name: str = "Sell Side Analyst",
    email: str = "analyst@bank.test",
    nda_on_file: bool = True,
    coverage_status: Optional[str] = COVERAGE_INITIATED,
    activist_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    return create_contact(
        api,
        company_id,
        contact_type=CONTACT_SELL_SIDE_ANALYST,
        display_name=display_name,
        email=email,
        nda_on_file=nda_on_file,
        coverage_status=coverage_status,
        activist_flag=activist_flag,
    )


def grant_model_access(api: ApiClient, contact_id: str, headers=DISCLOSURE_OFFICER) -> Dict[str, Any]:
    return get_success_data(
        api.servicing(contact_id, f.servicing_payload(SERVICING_GRANT_MODEL_ACCESS), headers)
    )


def set_threat_level(
    api: ApiClient, contact_id: str, threat_level: str, headers=DISCLOSURE_OFFICER
) -> Dict[str, Any]:
    return get_success_data(
        api.servicing(
            contact_id,
            f.servicing_payload(SERVICING_SET_THREAT_LEVEL, threat_level=threat_level),
            headers,
        )
    )


def create_granted_analyst(
    api: ApiClient,
    company_id: str,
    display_name: str = "Granted Analyst",
    email: str = "granted@bank.test",
    coverage_status: Optional[str] = COVERAGE_INITIATED,
) -> Dict[str, Any]:
    """An analyst that has cleared both estimate-filing gates."""
    analyst = create_analyst(
        api,
        company_id,
        display_name=display_name,
        email=email,
        nda_on_file=True,
        coverage_status=coverage_status,
    )
    return grant_model_access(api, analyst["id"])


def publish_disclosure(api: ApiClient, disclosure_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_disclosure(disclosure_id, DISCLOSURE_OFFICER))


def create_published_disclosure(api: ApiClient, company_id: str, **kwargs: Any) -> Dict[str, Any]:
    disclosure = create_disclosure(api, company_id, **kwargs)
    return publish_disclosure(api, disclosure["id"])


def create_published_guidance(
    api: ApiClient,
    company_id: str,
    fact_key: str = "EPS-FY2026-INITIAL",
    metric: str = METRIC_EPS,
    period_label: str = "FY2026",
    guidance_low: float = 2.00,
    guidance_high: float = 2.20,
) -> Dict[str, Any]:
    """A PUBLISHED guidance row that can anchor a consensus band."""
    disclosure = get_success_data(
        api.create_disclosure(
            f.guidance_disclosure_payload(
                company_id,
                fact_key,
                metric=metric,
                period_label=period_label,
                guidance_low=guidance_low,
                guidance_high=guidance_high,
            ),
            DISCLOSURE_OFFICER,
        )
    )
    return publish_disclosure(api, disclosure["id"])


def open_event(api: ApiClient, company_id: str, **kwargs: Any) -> Dict[str, Any]:
    """An event moved to OPEN_FOR_REQUESTS."""
    event = create_event(api, company_id, **kwargs)
    return get_success_data(api.open_event_requests(event["id"], IR_ADMIN))


def blackout_company(
    api: ApiClient,
    ticker: str = "BLK",
    legal_name: str = "Blackout Corp",
    shares_outstanding: int = 1000000,
    blackout_window_start: str = "2026-08-01T00:00:00Z",
    blackout_window_end: str = "2026-08-31T00:00:00Z",
    dividend_reserve_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """An issuer whose stored posture has been recomputed to BLACKOUT."""
    company = create_company(
        api,
        ticker=ticker,
        legal_name=legal_name,
        shares_outstanding=shares_outstanding,
        blackout_window_start=blackout_window_start,
        blackout_window_end=blackout_window_end,
        dividend_reserve_cents=dividend_reserve_cents,
    )
    return get_success_data(api.recompute_posture(company["id"], IR_ADMIN))


def recompute_posture(api: ApiClient, company_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.recompute_posture(company_id, headers))


# ---------------------------------------------------------------------------
# Tier 3 - multi-entity workflow chains
# ---------------------------------------------------------------------------


def route_inquiry(
    api: ApiClient,
    inquiry_id: str,
    target_queue: Optional[str] = None,
    headers=IR_ANALYST,
) -> Dict[str, Any]:
    return get_success_data(api.route_inquiry(inquiry_id, target_queue, headers))


def create_routed_inquiry(
    api: ApiClient,
    company_id: str,
    contact_id: str,
    topic_category: str = TOPIC_OTHER,
    subject: str = "A routed shareholder question.",
    headers=IR_ANALYST,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An inquiry taken in and routed, ready for a draft."""
    inquiry = create_inquiry(
        api,
        company_id,
        contact_id,
        headers=headers,
        topic_category=topic_category,
        subject=subject,
        **kwargs,
    )
    return route_inquiry(api, inquiry["id"], headers=headers)


def create_draft(
    api: ApiClient,
    inquiry_id: str,
    body_text: str = "Nothing beyond our published disclosures.",
    disclosure_class: str = CLASS_PUBLIC_DOMAIN,
    cited_disclosure_id: Optional[str] = None,
    headers=IR_ANALYST,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_response_draft(
            f.response_draft_payload(
                inquiry_id,
                body_text=body_text,
                disclosure_class=disclosure_class,
                cited_disclosure_id=cited_disclosure_id,
            ),
            headers,
        )
    )


def submit_for_review(api: ApiClient, draft_id: str, headers=IR_ANALYST) -> Dict[str, Any]:
    return get_success_data(api.submit_draft_for_review(draft_id, headers))


def decide_review(
    api: ApiClient,
    draft_id: str,
    inquiry_id: str,
    decision: str = DECISION_APPROVE,
    reviewer_note: Optional[str] = None,
    headers=DISCLOSURE_OFFICER,
) -> Dict[str, Any]:
    """Read the inquiry version, then decide the review with it."""
    version = inquiry_version(api, inquiry_id)
    return get_success_data(
        api.review_draft(
            draft_id, f.review_payload(decision, version, reviewer_note), headers
        )
    )


def revise_draft(
    api: ApiClient,
    draft_id: str,
    body_text: Optional[str] = None,
    disclosure_class: Optional[str] = None,
    cited_disclosure_id: Optional[str] = None,
    headers=IR_ANALYST,
) -> Dict[str, Any]:
    return get_success_data(
        api.revise_draft(
            draft_id,
            f.revise_payload(body_text, disclosure_class, cited_disclosure_id),
            headers,
        )
    )


def send_draft(api: ApiClient, draft_id: str, headers=IR_ANALYST) -> Dict[str, Any]:
    return get_success_data(api.send_draft(draft_id, headers))


def build_answer_pipeline(
    api: ApiClient,
    company_id: str,
    contact_id: str,
    stage: str = "in_review",
    topic_category: str = TOPIC_OTHER,
    subject: str = "A question walked through the pipeline.",
    body_text: str = "Nothing beyond our published disclosures.",
    disclosure_class: str = CLASS_PUBLIC_DOMAIN,
    cited_disclosure_id: Optional[str] = None,
    reviewer_note: str = "Please tighten the wording.",
    author_headers=IR_ANALYST,
    reviewer_headers=DISCLOSURE_OFFICER,
) -> Dict[str, Any]:
    """Walk one inquiry as far along the answer pipeline as ``stage`` asks.

    Stages, in order: ``routed``, ``draft``, ``in_review``, ``approved``,
    ``changes_requested``, ``sent``. Returns the inquiry and draft ids plus the
    latest payload seen for each.
    """
    stages = ["routed", "draft", "in_review", "approved", "changes_requested", "sent"]
    assert stage in stages, f"unknown pipeline stage {stage!r}"

    inquiry = create_routed_inquiry(
        api,
        company_id,
        contact_id,
        topic_category=topic_category,
        subject=subject,
        headers=author_headers,
    )
    result: Dict[str, Any] = {"inquiry": inquiry, "inquiry_id": inquiry["id"], "draft": None}
    if stage == "routed":
        return result

    draft = create_draft(
        api,
        inquiry["id"],
        body_text=body_text,
        disclosure_class=disclosure_class,
        cited_disclosure_id=cited_disclosure_id,
        headers=author_headers,
    )
    result["draft"] = draft
    result["draft_id"] = draft["id"]
    if stage == "draft":
        return result

    result["draft"] = submit_for_review(api, draft["id"], author_headers)
    if stage == "in_review":
        return result

    if stage == "changes_requested":
        result["draft"] = decide_review(
            api,
            draft["id"],
            inquiry["id"],
            decision=DECISION_REQUEST_CHANGES,
            reviewer_note=reviewer_note,
            headers=reviewer_headers,
        )
        return result

    result["draft"] = decide_review(
        api, draft["id"], inquiry["id"], decision=DECISION_APPROVE, headers=reviewer_headers
    )
    if stage == "approved":
        return result

    result["draft"] = send_draft(api, draft["id"], author_headers)
    return result


# ---------------------------------------------------------------------------
# Estimates and consensus
# ---------------------------------------------------------------------------


def file_estimate(
    api: ApiClient,
    contact_id: str,
    value: float,
    metric: str = METRIC_EPS,
    period_label: str = "FY2026",
) -> Dict[str, Any]:
    """File one estimate as the analyst itself, reading its version first."""
    version = contact_version(api, contact_id)
    return get_success_data(
        api.create_estimate(
            f.estimate_payload(
                contact_id, version, metric=metric, period_label=period_label, value=value
            ),
            make_investor_headers(contact_id),
        )
    )


def read_consensus(
    api: ApiClient,
    company_id: str,
    metric: str = METRIC_EPS,
    period_label: str = "FY2026",
    variant: Optional[str] = None,
    headers=IR_ANALYST,
) -> Dict[str, Any]:
    return get_success_data(
        api.get_consensus(company_id, metric, period_label, variant, headers)
    )


def seed_estimates(
    api: ApiClient,
    company_id: str,
    values: List[float],
    metric: str = METRIC_EPS,
    period_label: str = "FY2026",
    name_prefix: str = "Consensus Analyst",
    email_prefix: str = "consensus",
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """One granted, covering analyst per value, each filing that value once."""
    seeded: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for index, value in enumerate(values, start=1):
        analyst = create_granted_analyst(
            api,
            company_id,
            display_name=f"{name_prefix} {index}",
            email=f"{email_prefix}{index}@bank.test",
        )
        estimate = file_estimate(
            api, analyst["id"], value, metric=metric, period_label=period_label
        )
        seeded.append((analyst, estimate))
    return seeded


# ---------------------------------------------------------------------------
# Roadshow allocation chain
# ---------------------------------------------------------------------------


def allocate_event(api: ApiClient, event_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.allocate_event(event_id, headers))


def release_request(
    api: ApiClient, request_id: str, reason: str = "The holder cancelled.", headers=IR_ADMIN
) -> Dict[str, Any]:
    return get_success_data(api.release_meeting_request(request_id, reason, headers))


def complete_event(api: ApiClient, event_id: str, headers=IR_ADMIN) -> Dict[str, Any]:
    return get_success_data(api.complete_event(event_id, headers))


def build_open_event_with_requests(
    api: ApiClient,
    company_id: str,
    slots: List[Tuple[str, str, str]],
    capacity_slots: int = 1,
    event_type: str = EVENT_CONFERENCE,
    venue_city: str = "London",
    window_start: str = "2026-09-01T09:00:00Z",
    window_end: str = "2026-09-01T18:00:00Z",
    slot_minutes: int = 30,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """An OPEN_FOR_REQUESTS event plus one request per ``(contact_id, start, end)``."""
    event = open_event(
        api,
        company_id,
        event_type=event_type,
        venue_city=venue_city,
        window_start=window_start,
        window_end=window_end,
        slot_minutes=slot_minutes,
        capacity_slots=capacity_slots,
    )
    requests = [
        create_meeting_request(
            api,
            event["id"],
            contact_id,
            requested_slot_start=start,
            requested_slot_end=end,
        )
        for contact_id, start, end in slots
    ]
    return event, requests


# ---------------------------------------------------------------------------
# Transfer agent instruction chain
# ---------------------------------------------------------------------------


def acknowledge_instruction(
    api: ApiClient,
    instruction_id: str,
    decision: str = ACK_DECISION_ACKNOWLEDGE,
    rejection_reason: Optional[str] = None,
    headers=TRANSFER_AGENT,
) -> Dict[str, Any]:
    return get_success_data(
        api.acknowledge_instruction(
            instruction_id, f.acknowledge_payload(decision, rejection_reason), headers
        )
    )


def execute_instruction(
    api: ApiClient, instruction_id: str, headers=TRANSFER_AGENT
) -> Dict[str, Any]:
    return get_success_data(api.execute_instruction(instruction_id, headers))


def reverse_instruction(
    api: ApiClient,
    instruction_id: str,
    reason: str = "The transfer agent recalled the payment.",
    headers=TRANSFER_AGENT,
) -> Dict[str, Any]:
    return get_success_data(api.reverse_instruction(instruction_id, reason, headers))


def submit_dividend(
    api: ApiClient,
    company_id: str,
    record_date: str = "2026-08-15",
    payable_date: str = "2026-08-25",
    declared_rate_cents_per_share: float = 1.0000,
    funding_mode: Optional[str] = None,
    headers=IR_ADMIN,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_instruction(
            f.dividend_instruction_payload(
                company_id,
                record_date=record_date,
                payable_date=payable_date,
                declared_rate_cents_per_share=declared_rate_cents_per_share,
                funding_mode=funding_mode,
            ),
            headers,
        )
    )


def build_acknowledged_dividend(
    api: ApiClient,
    company_id: str,
    record_date: str = "2026-08-15",
    payable_date: str = "2026-08-25",
    declared_rate_cents_per_share: float = 1.0000,
    funding_mode: Optional[str] = None,
    submitter_headers=IR_ADMIN,
    acknowledger_headers=TRANSFER_AGENT,
) -> Dict[str, Any]:
    """A DIVIDEND_PAYMENT instruction whose record-date snapshot is frozen."""
    instruction = submit_dividend(
        api,
        company_id,
        record_date=record_date,
        payable_date=payable_date,
        declared_rate_cents_per_share=declared_rate_cents_per_share,
        funding_mode=funding_mode,
        headers=submitter_headers,
    )
    return acknowledge_instruction(
        api, instruction["id"], headers=acknowledger_headers
    )


def build_executed_dividend(
    api: ApiClient,
    company_id: str,
    execute_at: str,
    record_date: str = "2026-08-15",
    payable_date: str = "2026-08-25",
    declared_rate_cents_per_share: float = 1.0000,
    funding_mode: Optional[str] = None,
    submitter_headers=IR_ADMIN,
    acknowledger_headers=TRANSFER_AGENT,
) -> Dict[str, Any]:
    """An EXECUTED dividend: acknowledged, then paid with the clock at ``execute_at``."""
    instruction = build_acknowledged_dividend(
        api,
        company_id,
        record_date=record_date,
        payable_date=payable_date,
        declared_rate_cents_per_share=declared_rate_cents_per_share,
        funding_mode=funding_mode,
        submitter_headers=submitter_headers,
        acknowledger_headers=acknowledger_headers,
    )
    set_clock(api, execute_at)
    return execute_instruction(api, instruction["id"], acknowledger_headers)


# ---------------------------------------------------------------------------
# Tier 4 - whole-scenario worlds
# ---------------------------------------------------------------------------


def build_dividend_world(
    api: ApiClient,
    ticker: str = "DIV",
    legal_name: str = "Dividend World Corp",
    shares_outstanding: int = 1000000,
    dividend_reserve_cents: int = 100000,
    holder_shares: Optional[List[int]] = None,
    clock: str = DEFAULT_CLOCK_UTC,
) -> Dict[str, Any]:
    """An issuer with a funded reserve and one holder per entry of ``holder_shares``."""
    set_clock(api, clock)
    company = create_company(
        api,
        ticker=ticker,
        legal_name=legal_name,
        shares_outstanding=shares_outstanding,
        dividend_reserve_cents=dividend_reserve_cents,
    )
    holders = []
    for index, shares in enumerate(holder_shares or [1000], start=1):
        holders.append(
            create_holder(
                api,
                company["id"],
                shares,
                display_name=f"{ticker} Holder {index}",
                email=f"{ticker.lower()}{index}@funds.test",
            )
        )
    return {"company": company, "company_id": company["id"], "holders": holders}


def build_register_world(
    api: ApiClient,
    ticker: str = "REG",
    legal_name: str = "Register World Corp",
    shares_outstanding: int = 1000000,
    holder_shares: int = 20000,
    clock: str = DEFAULT_CLOCK_UTC,
) -> Dict[str, Any]:
    """The smallest useful world: a clock, an issuer and one institutional holder."""
    set_clock(api, clock)
    company = create_company(
        api,
        ticker=ticker,
        legal_name=legal_name,
        shares_outstanding=shares_outstanding,
    )
    holder = create_holder(
        api,
        company["id"],
        holder_shares,
        display_name=f"{ticker} Holder",
        email=f"{ticker.lower()}@funds.test",
    )
    return {
        "company": company,
        "company_id": company["id"],
        "holder": holder,
        "contact_id": holder["id"],
    }
