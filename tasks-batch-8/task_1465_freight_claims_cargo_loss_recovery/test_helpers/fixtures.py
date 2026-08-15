"""Composite setup helpers.

Every test starts against an empty database, so these helpers build the full
precondition chain through PRD-declared endpoints only: clock, carrier, lane,
carrier-lane assignment, shipment, claim, documents, then the workflow
transitions. All steps use the lenient get_success_data validator so a broken
precondition surfaces as a clear "Setup step failed" error.

Returned value is a plain dict ("ctx") holding the latest known snapshot of
each created resource under its entity name (carrier, lane, shipment, claim,
bol_doc, inv_doc, assessment, reserve, settlement, appeal, ...).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_assignment_payload,
    create_assessment_payload,
    create_carrier_payload,
    create_claim_payload,
    create_document_payload,
    create_lane_payload,
    create_reserve_payload,
    create_salvage_payload,
    create_settlement_payload,
    create_appeal_payload,
    create_shipment_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
ADJUSTER2 = TEST_USERS["adjuster2_headers"]
MANAGER = TEST_USERS["manager_headers"]
MANAGER2 = TEST_USERS["manager2_headers"]
SALVAGE = TEST_USERS["salvage_headers"]
SUBRO = TEST_USERS["subro_headers"]
FINANCE = TEST_USERS["finance_headers"]

SETUP_CLOCK = TEST_DEFAULTS["SETUP_CLOCK"]
SUBMIT_CLOCK = TEST_DEFAULTS["SUBMIT_CLOCK"]


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PlatformAdmin test-driving capability)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, CLERK))


def get_carrier(carrier_id: str) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, CLERK))


def get_lane(lane_id: str) -> dict:
    return get_success_data(api_client.get_lane(lane_id, CLERK))


def get_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, CLERK))


def setup_claim_draft(
    *,
    carrier_over: dict = None,
    lane_over: dict = None,
    assignment_over: dict = None,
    shipment_over: dict = None,
    claim_over: dict = None,
    setup_clock: str = SETUP_CLOCK,
) -> dict:
    """Carrier + lane + assignment + shipment + claim in DRAFT."""
    set_clock(setup_clock)
    carrier = get_success_data(
        api_client.create_carrier(create_carrier_payload(**(carrier_over or {})), MANAGER)
    )
    lane = get_success_data(
        api_client.create_lane(create_lane_payload(**(lane_over or {})), MANAGER)
    )
    assignment = get_success_data(
        api_client.create_assignment(
            create_assignment_payload(carrier["id"], lane["id"], **(assignment_over or {})),
            MANAGER,
        )
    )
    shipment = get_success_data(
        api_client.create_shipment(
            create_shipment_payload(carrier["id"], lane["id"], **(shipment_over or {})),
            CLERK,
        )
    )
    claim = get_success_data(
        api_client.create_claim(
            create_claim_payload(shipment["id"], **(claim_over or {})), CLERK
        )
    )
    return {
        "carrier": carrier,
        "lane": lane,
        "assignment": assignment,
        "shipment": shipment,
        "claim": claim,
    }


def _attach_required_docs(ctx: dict) -> None:
    claim_id = ctx["claim"]["id"]
    ctx["bol_doc"] = get_success_data(
        api_client.attach_document(
            claim_id, create_document_payload(document_kind="BOL"), CLERK
        )
    )
    ctx["inv_doc"] = get_success_data(
        api_client.attach_document(
            claim_id, create_document_payload(document_kind="COMMERCIAL_INVOICE"), CLERK
        )
    )


def setup_claim_submitted(
    *,
    submit_clock: str = SUBMIT_CLOCK,
    **kwargs,
) -> dict:
    """DRAFT setup + BOL and COMMERCIAL_INVOICE attached + submitted."""
    ctx = setup_claim_draft(**kwargs)
    _attach_required_docs(ctx)
    set_clock(submit_clock)
    ctx["claim"] = get_success_data(api_client.submit_claim(ctx["claim"]["id"], CLERK))
    return ctx


def setup_claim_acknowledged(
    *,
    submit_clock: str = SUBMIT_CLOCK,
    ack_clock: str = None,
    adjuster_headers: dict = None,
    **kwargs,
) -> dict:
    """SUBMITTED setup + carrier acknowledgment recorded."""
    ctx = setup_claim_submitted(submit_clock=submit_clock, **kwargs)
    if ack_clock is not None:
        set_clock(ack_clock)
    ctx["claim"] = get_success_data(
        api_client.acknowledge_claim(ctx["claim"]["id"], adjuster_headers or ADJUSTER)
    )
    return ctx


def _verify_required_docs(ctx: dict, adjuster_headers: dict) -> None:
    claim_id = ctx["claim"]["id"]
    ctx["bol_doc"] = get_success_data(
        api_client.verify_document(claim_id, ctx["bol_doc"]["id"], adjuster_headers)
    )
    ctx["inv_doc"] = get_success_data(
        api_client.verify_document(claim_id, ctx["inv_doc"]["id"], adjuster_headers)
    )


def setup_claim_under_review(
    *,
    negligence_flag: str = "CARRIER_NEGLIGENT",
    adjuster_headers: dict = None,
    **kwargs,
) -> dict:
    """ACKNOWLEDGED setup + both required docs VERIFIED + assessment created.

    The new assessment drives the claim from ACKNOWLEDGED to UNDER_REVIEW.
    """
    adjuster_headers = adjuster_headers or ADJUSTER
    ctx = setup_claim_acknowledged(adjuster_headers=adjuster_headers, **kwargs)
    _verify_required_docs(ctx, adjuster_headers)
    ctx["assessment"] = get_success_data(
        api_client.create_assessment(
            ctx["claim"]["id"],
            create_assessment_payload(negligence_flag=negligence_flag),
            adjuster_headers,
        )
    )
    ctx["claim"] = get_claim(ctx["claim"]["id"])
    return ctx


def setup_claim_offered(
    *,
    amount_cents: int,
    reserve_amount_cents: int = None,
    offer_headers: dict = None,
    **kwargs,
) -> dict:
    """UNDER_REVIEW setup + optional reserve + settlement offer (claim OFFERED).

    offer_headers controls the user recorded as the offer creator; the default
    second-adjuster identity keeps segregation-of-duties clean against the
    first-adjuster identity used for the assessment.
    """
    ctx = setup_claim_under_review(**kwargs)
    claim_id = ctx["claim"]["id"]
    if reserve_amount_cents is not None:
        ctx["reserve"] = get_success_data(
            api_client.post_reserve(
                claim_id, create_reserve_payload(reserve_amount_cents), FINANCE
            )
        )
    version = get_claim(claim_id)["version"]
    ctx["settlement"] = get_success_data(
        api_client.create_settlement(
            claim_id,
            create_settlement_payload(amount_cents, version),
            offer_headers or ADJUSTER2,
        )
    )
    ctx["claim"] = get_claim(claim_id)
    return ctx


def setup_claim_paid(*, accept_headers: dict = None, **kwargs) -> dict:
    """OFFERED setup + acceptance by a manager identity (claim PAID or
    CLOSED_WITH_PAYMENT depending on amount vs net exposure)."""
    ctx = setup_claim_offered(**kwargs)
    claim_id = ctx["claim"]["id"]
    ctx["settlement"] = get_success_data(
        api_client.accept_settlement(
            claim_id, ctx["settlement"]["id"], accept_headers or MANAGER
        )
    )
    ctx["claim"] = get_claim(claim_id)
    return ctx


def setup_claim_declined(*, decline_headers: dict = None, **kwargs) -> dict:
    """UNDER_REVIEW setup + decline with the current claim version."""
    ctx = setup_claim_under_review(**kwargs)
    claim_id = ctx["claim"]["id"]
    version = get_claim(claim_id)["version"]
    ctx["claim"] = get_success_data(
        api_client.decline_claim(
            claim_id, {"expected_claim_version": version}, decline_headers or ADJUSTER
        )
    )
    return ctx


def setup_claim_appealed(*, appeal_headers: dict = None, **kwargs) -> dict:
    """DECLINED setup + appeal opened (claim APPEALED)."""
    ctx = setup_claim_declined(**kwargs)
    claim_id = ctx["claim"]["id"]
    version = get_claim(claim_id)["version"]
    ctx["appeal"] = get_success_data(
        api_client.open_appeal(
            claim_id,
            create_appeal_payload(version),
            appeal_headers or ADJUSTER,
        )
    )
    ctx["claim"] = get_claim(claim_id)
    return ctx


def setup_claim_under_review_with_pending_salvage(
    *,
    salvage_specs: list,
    advance_clock_to: str,
    **kwargs,
) -> dict:
    """UNDER_REVIEW setup with salvage dispositions still SCHEDULED despite the
    logical clock sitting at or past their `scheduled_at`.

    PRD §2.7 makes advancing the clock execute any due disposition whose claim
    is in an executable state (UNDER_REVIEW/OFFERED/DECLINED/APPEALED), exactly
    as if a coordinator had executed it by hand. To keep the manual execution
    path of §3.5 reachable, the dispositions are scheduled while the claim is
    ACKNOWLEDGED (a non-executable state), the clock is then advanced past
    their `scheduled_at` (the sweep leaves them SCHEDULED), and only then is
    the claim walked to UNDER_REVIEW — document verification and assessment
    do not advance the clock, so no sweep fires before the manual execute.
    """
    ctx = setup_claim_acknowledged(**kwargs)
    claim_id = ctx["claim"]["id"]
    ctx["salvage_list"] = [
        get_success_data(
            api_client.schedule_salvage(
                claim_id, create_salvage_payload(**spec), SALVAGE
            )
        )
        for spec in salvage_specs
    ]
    set_clock(advance_clock_to)
    _verify_required_docs(ctx, ADJUSTER)
    ctx["assessment"] = get_success_data(
        api_client.create_assessment(
            claim_id, create_assessment_payload(), ADJUSTER
        )
    )
    ctx["claim"] = get_claim(claim_id)
    return ctx
