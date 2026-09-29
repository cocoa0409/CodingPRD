"""Composite setup builders.

Each test starts against an empty store, so every precondition a test needs has
to be built from scratch. The builders here walk the documented sequences ---
register the parties, record a mandatory offer, accept it, quote, bind, open a
funding cycle, approve and reserve a grant, open a project, schedule and record
an inspection, declare an event, file and settle a claim --- and return every
record they created so a test can assert against any hop in the chain.

Every builder threads identity correctly: the three record-backed roles act with
their own record's identifier, and the four opaque roles act with a shared
identifier. Setup steps go through the lenient success reader, so a broken
precondition surfaces as a setup failure rather than as a confusing assertion
inside the test body.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_ALT_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_contractor_headers,
    make_insurer_headers,
    make_policyholder_headers,
)

# ─── Tier one: clock and single records ───────────────────────────────────────


def set_clock(client: ApiClient, instant: str) -> None:
    """Pin the logical clock to a specific instant."""
    get_success_data(
        client.set_clock(factories.set_clock_payload(instant), PROGRAM_ADMIN_HEADERS)
    )


def create_insurer(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a participating insurer."""
    return get_success_data(
        client.create_insurer(
            factories.create_insurer_payload(**overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def create_policyholder(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a policyholder."""
    return get_success_data(
        client.create_policyholder(
            factories.create_policyholder_payload(**overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def create_dwelling(
    client: ApiClient,
    policyholder_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a dwelling, acting as the policyholder who owns it."""
    return get_success_data(
        client.create_dwelling(
            factories.create_dwelling_payload(policyholder_id, **overrides),
            make_policyholder_headers(policyholder_id),
        )
    )


def create_contractor(
    client: ApiClient,
    certified_scopes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a certified contractor."""
    return get_success_data(
        client.create_contractor(
            factories.create_contractor_payload(certified_scopes, **overrides),
            PROGRAM_ADMIN_HEADERS,
        )
    )


def create_grant_cycle(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Open a retrofit grant funding cycle."""
    return get_success_data(
        client.create_grant_cycle(
            factories.create_grant_cycle_payload(**overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def create_reinsurance_layer(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a reinsurance layer."""
    return get_success_data(
        client.create_reinsurance_layer(
            factories.create_reinsurance_layer_payload(**overrides),
            PROGRAM_ADMIN_HEADERS,
        )
    )


# ─── Tier two: the party chain and the offer ───────────────────────────────────


def setup_parties(
    client: ApiClient,
    insurer: Optional[Dict[str, Any]] = None,
    dwelling_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An insurer, a policyholder and that policyholder's dwelling."""
    ins = insurer if insurer is not None else create_insurer(client)
    holder = create_policyholder(client)
    dwelling = create_dwelling(client, holder["id"], **(dwelling_overrides or {}))
    return {"insurer": ins, "policyholder": holder, "dwelling": dwelling}


def setup_pending_offer(
    client: ApiClient,
    parties: Optional[Dict[str, Any]] = None,
    dwelling_overrides: Optional[Dict[str, Any]] = None,
    **offer_overrides: Any,
) -> Dict[str, Any]:
    """A recorded mandatory offer still awaiting a response."""
    ctx = parties if parties is not None else setup_parties(
        client, dwelling_overrides=dwelling_overrides
    )
    offer = get_success_data(
        client.create_mandatory_offer(
            factories.create_mandatory_offer_payload(
                ctx["insurer"]["id"],
                ctx["policyholder"]["id"],
                ctx["dwelling"]["id"],
                **offer_overrides,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        )
    )
    ctx = dict(ctx)
    ctx["offer"] = offer
    return ctx


def setup_accepted_offer(
    client: ApiClient,
    parties: Optional[Dict[str, Any]] = None,
    dwelling_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A mandatory offer the policyholder has accepted."""
    ctx = setup_pending_offer(
        client, parties=parties, dwelling_overrides=dwelling_overrides
    )
    ctx["offer"] = get_success_data(
        client.respond_to_offer(
            ctx["offer"]["id"],
            factories.respond_to_offer_payload("ACCEPT"),
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
    )
    return ctx


# ─── Tier three: policy lifecycle shortcuts ────────────────────────────────────


def setup_quoted_policy(
    client: ApiClient,
    parties: Optional[Dict[str, Any]] = None,
    dwelling_overrides: Optional[Dict[str, Any]] = None,
    **policy_overrides: Any,
) -> Dict[str, Any]:
    """A quote sitting against an accepted offer."""
    ctx = setup_accepted_offer(
        client, parties=parties, dwelling_overrides=dwelling_overrides
    )
    ctx["policy"] = get_success_data(
        client.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                **policy_overrides,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        )
    )
    return ctx


def setup_bound_policy(
    client: ApiClient,
    parties: Optional[Dict[str, Any]] = None,
    dwelling_overrides: Optional[Dict[str, Any]] = None,
    **policy_overrides: Any,
) -> Dict[str, Any]:
    """A policy bound so that cover is in force."""
    ctx = setup_quoted_policy(
        client,
        parties=parties,
        dwelling_overrides=dwelling_overrides,
        **policy_overrides,
    )
    ctx["quote"] = ctx["policy"]
    ctx["policy"] = get_success_data(
        client.bind_policy(
            ctx["policy"]["id"],
            None,
            make_insurer_headers(ctx["insurer"]["id"]),
        )
    )
    return ctx


def declare_retrofit(
    client: ApiClient,
    ctx: Dict[str, Any],
    declared_scope: str = "CRIPPLE_WALL_BRACING",
) -> Dict[str, Any]:
    """Declare an unverified retrofit on the context's dwelling."""
    ctx["dwelling"] = get_success_data(
        client.declare_retrofit(
            ctx["dwelling"]["id"],
            factories.declare_retrofit_payload(declared_scope),
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
    )
    return ctx


# ─── Tier four: the grant and retrofit chain ────────────────────────────────────


def setup_submitted_grant(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    cycle: Optional[Dict[str, Any]] = None,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    **grant_overrides: Any,
) -> Dict[str, Any]:
    """A grant application submitted against an open cycle.

    The dwelling is bound to an in-force policy first, because a grant approval
    needs one.
    """
    ctx = ctx if ctx is not None else setup_bound_policy(client)
    ctx = dict(ctx)
    ctx["cycle"] = cycle if cycle is not None else create_grant_cycle(
        client, **(cycle_overrides or {})
    )
    payload = factories.create_retrofit_grant_payload(
        ctx["dwelling"]["id"], ctx["cycle"]["id"], **grant_overrides
    )
    payload.setdefault("policy_id", ctx["policy"]["id"])
    ctx["grant"] = get_success_data(
        client.create_retrofit_grant(
            payload, make_policyholder_headers(ctx["policyholder"]["id"])
        )
    )
    return ctx


def setup_grant_under_review(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A grant application taken under review."""
    ctx = setup_submitted_grant(client, ctx=ctx, **kwargs)
    ctx["grant"] = get_success_data(
        client.begin_grant_review(ctx["grant"]["id"], None, GRANT_REVIEWER_HEADERS)
    )
    return ctx


def setup_approved_grant(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    reviewer_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An approved grant with its award amount computed.

    The reviewer who approves is remembered on the grant, so the reservation step
    must be carried out by somebody else.
    """
    ctx = setup_grant_under_review(client, ctx=ctx, **kwargs)
    ctx["grant"] = get_success_data(
        client.review_grant(
            ctx["grant"]["id"],
            factories.review_grant_payload("APPROVE"),
            reviewer_headers or GRANT_REVIEWER_HEADERS,
        )
    )
    return ctx


def setup_reserved_grant(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    reserver_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A grant whose award has been reserved out of its cycle's pool.

    The reservation is made by a different acting identity from the approval, and
    with the cycle version the caller has just read.
    """
    ctx = setup_approved_grant(client, ctx=ctx, **kwargs)
    cycle = get_success_data(client.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS))
    ctx["grant"] = get_success_data(
        client.reserve_grant_funds(
            ctx["grant"]["id"],
            factories.reserve_funds_payload(cycle["version"]),
            reserver_headers or PROGRAM_ADMIN_ALT_HEADERS,
        )
    )
    ctx["cycle"] = get_success_data(
        client.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    return ctx


def setup_scheduled_project(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    contractor: Optional[Dict[str, Any]] = None,
    contractor_scopes: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A retrofit project opened against a grant whose funds are reserved."""
    ctx = setup_reserved_grant(client, ctx=ctx, **kwargs)
    ctx["contractor"] = contractor if contractor is not None else create_contractor(
        client, certified_scopes=contractor_scopes
    )
    ctx["project"] = get_success_data(
        client.create_retrofit_project(
            factories.create_retrofit_project_payload(
                ctx["grant"]["id"], ctx["contractor"]["id"]
            ),
            make_contractor_headers(ctx["contractor"]["id"]),
        )
    )
    return ctx


def setup_project_in_progress(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A retrofit project whose work has started."""
    ctx = setup_scheduled_project(client, ctx=ctx, **kwargs)
    ctx["project"] = get_success_data(
        client.start_project_work(
            ctx["project"]["id"],
            None,
            make_contractor_headers(ctx["contractor"]["id"]),
        )
    )
    return ctx


def setup_project_awaiting_inspection(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A retrofit project that has asked for its inspection."""
    ctx = setup_project_in_progress(client, ctx=ctx, **kwargs)
    ctx["project"] = get_success_data(
        client.request_project_inspection(
            ctx["project"]["id"],
            None,
            make_contractor_headers(ctx["contractor"]["id"]),
        )
    )
    return ctx


def setup_scheduled_inspection(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    window_start: str = "2026-08-04T09:00:00Z",
    window_end: str = "2026-08-04T10:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """An inspection window booked against a project awaiting inspection."""
    ctx = setup_project_awaiting_inspection(client, ctx=ctx, **kwargs)
    ctx["inspection"] = get_success_data(
        client.create_inspection(
            factories.create_inspection_payload(
                ctx["project"]["id"], window_start, window_end
            ),
            FIELD_INSPECTOR_HEADERS,
        )
    )
    return ctx


def record_inspection(
    client: ApiClient,
    ctx: Dict[str, Any],
    result: str = "PASS",
    inspector_headers: Optional[Dict[str, str]] = None,
    **payload_overrides: Any,
) -> Dict[str, Any]:
    """Record an outcome on the context's inspection and re-read the whole chain."""
    ctx["inspection"] = get_success_data(
        client.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload(result, **payload_overrides),
            inspector_headers or FIELD_INSPECTOR_HEADERS,
        )
    )
    return refresh(client, ctx)


def refresh(client: ApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Re-read every record the context holds, so cascades become visible."""
    readers = {
        "insurer": client.get_insurer,
        "policyholder": client.get_policyholder,
        "dwelling": client.get_dwelling,
        "offer": client.get_mandatory_offer,
        "policy": client.get_policy,
        "cycle": client.get_grant_cycle,
        "grant": client.get_retrofit_grant,
        "contractor": client.get_contractor,
        "project": client.get_retrofit_project,
        "inspection": client.get_inspection,
        "event": client.get_catastrophe_event,
        "layer": client.get_reinsurance_layer,
        "claim": client.get_claim,
    }
    for key, reader in readers.items():
        if key in ctx and isinstance(ctx[key], dict) and "id" in ctx[key]:
            ctx[key] = get_success_data(reader(ctx[key]["id"], PROGRAM_ADMIN_HEADERS))
    return ctx


# ─── Tier five: catastrophe events, layers and claims ───────────────────────────


def create_catastrophe_event(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Record a catastrophe event, still under monitoring."""
    return get_success_data(
        client.create_catastrophe_event(
            factories.create_catastrophe_event_payload(**overrides),
            PROGRAM_ADMIN_HEADERS,
        )
    )


def setup_declared_event(
    client: ApiClient,
    with_layer: bool = True,
    layer_overrides: Optional[Dict[str, Any]] = None,
    **event_overrides: Any,
) -> Dict[str, Any]:
    """A declared catastrophe event, by default backed by one reinsurance layer."""
    result: Dict[str, Any] = {}
    if with_layer:
        result["layer"] = create_reinsurance_layer(client, **(layer_overrides or {}))
    event = create_catastrophe_event(client, **event_overrides)
    result["event"] = get_success_data(
        client.declare_event(event["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    return result


def setup_event_with_policy(
    client: ApiClient,
    clock: str = "2026-09-06T00:00:00Z",
    dwelling_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    event_overrides: Optional[Dict[str, Any]] = None,
    layer_overrides: Optional[Dict[str, Any]] = None,
    with_layer: bool = True,
) -> Dict[str, Any]:
    """An in-force policy bound before an event that has since been declared.

    Cover has to be in force at the moment of loss, so the policy is bound while
    the clock still sits at the start of the calendar and the clock is only then
    advanced past the event.
    """
    ctx = setup_bound_policy(
        client,
        dwelling_overrides=dwelling_overrides,
        **(policy_overrides or {}),
    )
    set_clock(client, clock)
    ctx.update(
        setup_declared_event(
            client,
            with_layer=with_layer,
            layer_overrides=layer_overrides,
            **(event_overrides or {}),
        )
    )
    return ctx


def setup_filed_claim(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    adjuster_headers: Optional[Dict[str, str]] = None,
    **claim_overrides: Any,
) -> Dict[str, Any]:
    """A first notice of loss filed against a declared event."""
    ctx = ctx if ctx is not None else setup_event_with_policy(client)
    ctx["claim"] = get_success_data(
        client.create_claim(
            factories.create_claim_payload(
                ctx["policy"]["id"],
                ctx["event"]["id"],
                ctx["event"]["version"],
                **claim_overrides,
            ),
            adjuster_headers or CLAIM_ADJUSTER_HEADERS,
        )
    )
    ctx["event"] = get_success_data(
        client.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    return ctx


def setup_provisionally_adjusted_claim(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    adjuster_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A claim carrying its provisional settlement figure."""
    ctx = setup_filed_claim(client, ctx=ctx, **kwargs)
    ctx["claim"] = get_success_data(
        client.adjust_claim_provisional(
            ctx["claim"]["id"],
            None,
            adjuster_headers or CLAIM_ADJUSTER_HEADERS,
        )
    )
    return ctx


def setup_finally_adjusted_claim(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    provisional_headers: Optional[Dict[str, str]] = None,
    final_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A claim carrying its final settlement figure.

    The two adjustment steps are carried out by different acting identities,
    because the identity that produced the provisional figure may not produce the
    final one.
    """
    ctx = setup_provisionally_adjusted_claim(
        client, ctx=ctx, adjuster_headers=provisional_headers, **kwargs
    )
    ctx["claim"] = get_success_data(
        client.finalize_claim_adjustment(
            ctx["claim"]["id"],
            None,
            final_headers or CLAIM_ADJUSTER_ALT_HEADERS,
        )
    )
    return ctx


def setup_fully_paid_claim(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A claim whose final settlement has been paid in full."""
    ctx = setup_finally_adjusted_claim(client, ctx=ctx, **kwargs)
    ctx["claim"] = get_success_data(
        client.record_claim_payment(
            ctx["claim"]["id"],
            factories.record_payment_payload(ctx["claim"]["payable_cents"]),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    return ctx


def setup_closed_claim(
    client: ApiClient,
    ctx: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A claim that has been paid and then closed."""
    ctx = setup_fully_paid_claim(client, ctx=ctx, **kwargs)
    ctx["claim"] = get_success_data(
        client.close_claim(ctx["claim"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    return ctx


def get_allocations_for_event(client: ApiClient, event_id: str) -> List[Dict[str, Any]]:
    """Every assessment allocation recorded for one event, in rank order."""
    body = client.list_assessment_allocations(
        {"event_id": event_id, "limit": 100}, PROGRAM_ADMIN_HEADERS
    ).json()
    rows = body["data"]
    return sorted(rows, key=lambda r: r["allocation_rank"])
