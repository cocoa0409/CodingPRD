"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so nothing is
carried over). Helpers use get_success_data() so setup failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_SETUP, PARTIES, STANDARD
from .factories import (
    create_bid_payload,
    create_dispute_payload,
    create_draw_request_payload,
    create_extension_request_payload,
    create_file_payload,
    create_holdback_payload,
    create_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_contractor_headers,
    make_inspector_headers,
    make_insurer_headers,
    make_lender_headers,
    make_seller_headers,
)

OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and single-entity creation
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str = CLOCK_SETUP) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OFFICER))


def setup_escrow_file(with_insurer: bool = False, **overrides) -> dict:
    """Open an escrow file (PRD §3.1). Returns the created EscrowFile."""
    payload = create_file_payload(**overrides)
    if not with_insurer:
        payload.pop("insurer_user_id", None)
    return get_success_data(api_client.create_file(payload, OFFICER))


def create_draft_holdback(file_id: str, **overrides) -> dict:
    """Create a holdback on a file; it is born DRAFT and funded (PRD §3.1)."""
    payload = create_holdback_payload(escrow_file_id=file_id, **overrides)
    return get_success_data(api_client.create_holdback(payload, OFFICER))


def get_holdback(holdback_id: str) -> dict:
    return get_success_data(api_client.get_holdback(holdback_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 1: approval circuit / holdback state progression (PRD §3.2)
# ---------------------------------------------------------------------------

def get_approvals(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_approvals(holdback_id, OFFICER))
    return data


def find_approval(approvals: list, approver_role: str, status: str = None) -> dict:
    for ap in approvals:
        if ap["approver_role"] != approver_role:
            continue
        if status is not None and ap["status"] != status:
            continue
        return ap
    raise AssertionError(f"No approval with role {approver_role} / status {status}")


def decide_approval(approval_id: str, headers: dict, decision: str = "APPROVED", **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(api_client.decide_approval(approval_id, payload, headers))


def decide_all_requested(file: dict, holdback_id: str, decision: str = "APPROVED") -> list:
    """Decide every REQUESTED approval with the role-matched party of record."""
    decided = []
    for ap in get_approvals(holdback_id):
        if ap["status"] != "REQUESTED":
            continue
        if ap["approver_role"] == "LENDER":
            headers = make_lender_headers(file["lender_user_id"])
        else:
            headers = make_insurer_headers(file["insurer_user_id"])
        decided.append(decide_approval(ap["id"], headers, decision))
    return decided


def setup_pending_holdback(with_insurer: bool = False,
                           clock: str = CLOCK_SETUP,
                           file_overrides: dict = None,
                           **holdback_overrides) -> dict:
    """File + DRAFT holdback submitted to PENDING_APPROVALS (PRD §3.2)."""
    if clock:
        set_logical_clock(clock)
    file = setup_escrow_file(with_insurer=with_insurer, **(file_overrides or {}))
    hb = create_draft_holdback(file["id"], **holdback_overrides)
    submitted = get_success_data(api_client.submit_holdback(hb["id"], OFFICER))
    return {"file": file, "holdback": submitted,
            "approvals": get_approvals(hb["id"])}


def setup_active_holdback(with_insurer: bool = False,
                          clock: str = CLOCK_SETUP,
                          file_overrides: dict = None,
                          **holdback_overrides) -> dict:
    """File + holdback approved by every required party; holdback ACTIVE."""
    ctx = setup_pending_holdback(with_insurer=with_insurer, clock=clock,
                                 file_overrides=file_overrides, **holdback_overrides)
    decide_all_requested(ctx["file"], ctx["holdback"]["id"])
    ctx["holdback"] = get_holdback(ctx["holdback"]["id"])
    ctx["approvals"] = get_approvals(ctx["holdback"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: bidding and the work order (PRD §3.3)
# ---------------------------------------------------------------------------

def submit_bid(holdback_id: str,
               contractor_user_id: str = PARTIES["contractor"],
               amount_cents: int = STANDARD["bid_amount_cents"],
               scope_text: str = STANDARD["bid_scope_text"]) -> dict:
    payload = create_bid_payload(holdback_id=holdback_id, amount_cents=amount_cents,
                                 scope_text=scope_text)
    return get_success_data(api_client.create_bid(
        payload, make_contractor_headers(contractor_user_id)))


def select_bid(bid_id: str, file: dict) -> dict:
    """Buyer of record selects the bid (PRD §3.3)."""
    return get_success_data(api_client.select_bid(
        bid_id, make_buyer_headers(file["buyer_user_id"])))


def get_work_orders(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_work_orders(holdback_id, OFFICER))
    return data


def get_work_order(holdback_id: str) -> dict:
    orders = get_work_orders(holdback_id)
    assert len(orders) == 1, f"expected exactly one work order, got {len(orders)}"
    return orders[0]


def setup_engagement(with_insurer: bool = False,
                     clock: str = CLOCK_SETUP,
                     contractor_user_id: str = PARTIES["contractor"],
                     bid_amount_cents: int = STANDARD["bid_amount_cents"],
                     file_overrides: dict = None,
                     **holdback_overrides) -> dict:
    """ACTIVE holdback + one bid selected; work order exists IN_PROGRESS."""
    ctx = setup_active_holdback(with_insurer=with_insurer, clock=clock,
                                file_overrides=file_overrides, **holdback_overrides)
    bid = submit_bid(ctx["holdback"]["id"], contractor_user_id=contractor_user_id,
                     amount_cents=bid_amount_cents)
    selected = select_bid(bid["id"], ctx["file"])
    ctx["bid"] = selected
    ctx["work_order"] = get_work_order(ctx["holdback"]["id"])
    ctx["holdback"] = get_holdback(ctx["holdback"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: inspections and the verification path (PRD §3.4)
# ---------------------------------------------------------------------------

def schedule_inspection(holdback_id: str,
                        purpose: str = "DRAW_VERIFICATION",
                        scheduled_start: str = "2026-08-20T10:00:00Z",
                        scheduled_end: str = "2026-08-20T11:00:00Z",
                        inspector_user_id: str = PARTIES["inspector"]) -> dict:
    payload = create_inspection_payload(
        holdback_id=holdback_id, inspector_user_id=inspector_user_id, purpose=purpose,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    return get_success_data(api_client.create_inspection(payload, OFFICER))


def report_inspection(inspection_id: str,
                      inspector_user_id: str = PARTIES["inspector"],
                      result: str = "PASSED", **extra) -> dict:
    payload = {"result": result}
    payload.update(extra)
    return get_success_data(api_client.report_inspection(
        inspection_id, payload, make_inspector_headers(inspector_user_id)))


def schedule_and_report_inspection(holdback_id: str,
                                   purpose: str = "DRAW_VERIFICATION",
                                   scheduled_start: str = "2026-08-20T10:00:00Z",
                                   scheduled_end: str = "2026-08-20T11:00:00Z",
                                   inspector_user_id: str = PARTIES["inspector"],
                                   result: str = "PASSED", **extra) -> dict:
    ins = schedule_inspection(holdback_id, purpose, scheduled_start, scheduled_end,
                              inspector_user_id)
    return report_inspection(ins["id"], inspector_user_id, result, **extra)


def list_inspections(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_inspections(holdback_id, OFFICER))
    return data


def submit_completion(work_order_id: str,
                      contractor_user_id: str = PARTIES["contractor"]) -> dict:
    return get_success_data(api_client.submit_work_order_completion(
        work_order_id, make_contractor_headers(contractor_user_id)))


def verify_work_order(ctx: dict,
                      purpose: str = "FINAL_VERIFICATION",
                      scheduled_start: str = "2026-08-25T09:00:00Z",
                      scheduled_end: str = "2026-08-25T10:00:00Z",
                      inspector_user_id: str = PARTIES["inspector"],
                      contractor_user_id: str = PARTIES["contractor"]) -> dict:
    """Submit completion and pass a final verification; work order VERIFIED."""
    submit_completion(ctx["work_order"]["id"], contractor_user_id)
    ins = schedule_and_report_inspection(
        ctx["holdback"]["id"], purpose=purpose, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end, inspector_user_id=inspector_user_id, result="PASSED")
    ctx["final_inspection"] = ins
    ctx["work_order"] = get_work_order(ctx["holdback"]["id"])
    ctx["holdback"] = get_holdback(ctx["holdback"]["id"])
    return ctx


def setup_verified_engagement(clock: str = CLOCK_SETUP, **kwargs) -> dict:
    """Engagement whose work order has been verified (closeout-ready)."""
    ctx = setup_engagement(clock=clock, **kwargs)
    return verify_work_order(ctx)


# ---------------------------------------------------------------------------
# Tier 4: draws, shortfalls, and pledges (PRD §3.5)
# ---------------------------------------------------------------------------

def create_draw(holdback_id: str, amount_cents: int,
                contractor_user_id: str = PARTIES["contractor"],
                description: str = "Stage 1", is_final: bool = False) -> dict:
    payload = create_draw_request_payload(
        holdback_id=holdback_id, amount_cents=amount_cents,
        description=description, is_final=is_final)
    return get_success_data(api_client.create_draw_request(
        payload, make_contractor_headers(contractor_user_id)))


def list_draws(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_draw_requests(holdback_id, OFFICER))
    return data


def approve_draw(draw_id: str) -> dict:
    return get_success_data(api_client.approve_draw_request(draw_id, OFFICER))


def pay_draw(draw_id: str) -> dict:
    return get_success_data(api_client.pay_draw_request(draw_id, OFFICER))


def create_verified_draw(ctx: dict, amount_cents: int,
                         description: str = "Stage draw",
                         is_final: bool = False,
                         scheduled_start: str = "2026-08-20T10:00:00Z",
                         scheduled_end: str = "2026-08-20T11:00:00Z",
                         contractor_user_id: str = PARTIES["contractor"]) -> dict:
    """Create a draw and a PASSED draw-verification inspection reported after it."""
    draw = create_draw(ctx["holdback"]["id"], amount_cents,
                       contractor_user_id=contractor_user_id,
                       description=description, is_final=is_final)
    ins = schedule_and_report_inspection(
        ctx["holdback"]["id"], purpose="DRAW_VERIFICATION",
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    return {"draw": draw, "inspection": ins}


def create_approved_draw(ctx: dict, amount_cents: int, **kwargs) -> dict:
    """Create a draw with a verifying inspection and approve it."""
    pair = create_verified_draw(ctx, amount_cents, **kwargs)
    pair["draw"] = approve_draw(pair["draw"]["id"])
    ctx["holdback"] = get_holdback(ctx["holdback"]["id"])
    return pair


def list_pledges(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_shortfall_pledges(holdback_id, OFFICER))
    return data


def deposit_pledge(pledge_id: str) -> dict:
    return get_success_data(api_client.deposit_shortfall_pledge(pledge_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 5: extensions, disputes, expiration, closing (PRD §3.6–§3.8)
# ---------------------------------------------------------------------------

def create_extension(holdback_id: str, headers: dict,
                     reason: str = "WEATHER_EXTERIOR",
                     requested_days: int = 5,
                     evidence_ref: str = "NOAA storm log") -> dict:
    payload = create_extension_request_payload(
        holdback_id=holdback_id, reason=reason, requested_days=requested_days,
        evidence_ref=evidence_ref)
    return get_success_data(api_client.create_extension_request(payload, headers))


def list_extensions(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_extension_requests(holdback_id, OFFICER))
    return data


def decide_extension(extension_id: str, decision: str = "GRANTED", **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(api_client.decide_extension_request(extension_id, payload, OFFICER))


def create_dispute(holdback_id: str, headers: dict,
                   category: str = "WORK_QUALITY",
                   claimed_amount_cents: int = 50000,
                   statement: str = "Work not to code") -> dict:
    payload = create_dispute_payload(
        holdback_id=holdback_id, category=category,
        claimed_amount_cents=claimed_amount_cents, statement=statement)
    return get_success_data(api_client.create_dispute(payload, headers))


def list_disputes(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_disputes(holdback_id, OFFICER))
    return data


def resolve_dispute(dispute_id: str, resolution: str, resolution_note: str) -> dict:
    return get_success_data(api_client.resolve_dispute(
        dispute_id, {"resolution": resolution, "resolution_note": resolution_note}, OFFICER))


def expire_holdback(holdback_id: str) -> dict:
    return get_success_data(api_client.expire_holdback(holdback_id, OFFICER))


def close_holdback(holdback_id: str) -> dict:
    return get_success_data(api_client.close_holdback(holdback_id, OFFICER))


def list_ledger(holdback_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_ledger_entries(holdback_id, OFFICER))
    return data


def buyer_headers_for(ctx: dict) -> dict:
    return make_buyer_headers(ctx["file"]["buyer_user_id"])


def seller_headers_for(ctx: dict) -> dict:
    return make_seller_headers(ctx["file"]["seller_user_id"])
