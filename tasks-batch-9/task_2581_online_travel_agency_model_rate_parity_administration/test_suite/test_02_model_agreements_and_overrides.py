"""Merchant-versus-agency model agreements and negotiated rate overrides."""
from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals, assert_pct
from test_helpers.fixtures import DEFAULT_INSTANT, certified_hotel
from test_helpers.test_users import (
    BOOKING_AGENT,
    COMMERCIAL_MANAGER,
    COMPLIANCE_OFFICER,
    DUAL_HAT_COMMERCIAL_MANAGER,
    DUAL_HAT_COMPLIANCE_OFFICER,
    DUAL_HAT_USER_ID,
    PLATFORM_ADMIN,
)


def _hotel_with_three_windows(b):
    """A1 active 08-01..09-30, A2 drafted 09-30.., A3 drafted 10-01.. ."""
    ctx = certified_hotel(b)
    ctx["a1"] = b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-09-30",
    )
    ctx["a2"] = b.draft_agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-09-30",
        effective_to="2026-12-31",
    )
    ctx["a3"] = b.draft_agreement(
        ctx.supplier["id"],
        model="MERCHANT",
        effective_from="2026-10-01",
        effective_to="2026-12-31",
    )
    return ctx


def test_agreement_window_touching_the_active_end_date_is_an_overlap(b, client):
    """A candidate starting on the active window's last covered day collides.

    PRD 3.2: "Because the intervals are closed on both ends, two windows that
    merely touch - where the candidate's `effective_from` equals an existing
    agreement's `effective_to`, or vice versa - do overlap, and activation is
    rejected with `ERR_MODEL_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/model_agreement_closed_interval_touching_end_date_is_an_overlap
    """
    ctx = _hotel_with_three_windows(b)

    refused = client.activate_model_agreement(ctx.a2["id"], {}, COMPLIANCE_OFFICER)
    validate_error(refused, E.ERR_MODEL_AGREEMENT_OVERLAP, 409)

    still_draft = validate_success(
        client.get_model_agreement(ctx.a2["id"], PLATFORM_ADMIN)
    )
    assert still_draft["status"] == "DRAFT"
    assert still_draft["activated_at"] is None


def test_agreement_window_starting_the_day_after_activates_without_superseding(b, client):
    """A candidate starting the day after the active window ends activates cleanly.

    PRD 3.2: "There is exactly one exemption: an existing `ACTIVE` agreement
    whose `effective_from` is the same date as the candidate's `effective_from`
    is not treated as a conflict. ... Same-start replacement is the only route to
    `SUPERSEDED`; every other pair of windows must be genuinely disjoint."

    Design: Difficulty/resource_temporal_overlap/model_agreement_closed_interval_touching_end_date_is_an_overlap
    """
    ctx = _hotel_with_three_windows(b)

    activated = validate_success(
        client.activate_model_agreement(ctx.a3["id"], {}, COMPLIANCE_OFFICER)
    )

    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]

    first = validate_success(client.get_model_agreement(ctx.a1["id"], PLATFORM_ADMIN))
    assert first["status"] == "ACTIVE"

    supplier = b.read_supplier(ctx.supplier["id"])
    assert supplier["current_model"] == "AGENCY"


def test_replaying_activate_on_an_active_agreement_is_rejected(b, client):
    """A second activate is refused and the first activation stamp survives.

    PRD 3.2: "The agreement must still be in `DRAFT` - anything else is rejected
    with `ERR_AGREEMENT_NOT_DRAFT`".

    Design: Corner/state_machines/activate_an_already_active_model_agreement_is_rejected
    """
    ctx = certified_hotel(b)
    agreement = b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )

    replay = client.activate_model_agreement(
        agreement["id"], {"note": "replay"}, COMPLIANCE_OFFICER
    )
    validate_error(replay, E.ERR_AGREEMENT_NOT_DRAFT, 409)

    stored = validate_success(
        client.get_model_agreement(agreement["id"], PLATFORM_ADMIN)
    )
    assert stored["status"] == "ACTIVE"
    assert_instant_equals(stored["activated_at"], DEFAULT_INSTANT)
    assert stored["activated_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]


def test_booking_agent_cannot_activate_a_model_agreement(b, client):
    """Activation is refused to a booking agent before any duty check runs.

    PRD 4: `POST /model-agreements/{id}/activate` lists `ComplianceOfficer` as
    its only authorised role, and PRD 2.1 pins that "If both headers are well
    formed but the named role does not appear on the endpoint's authorised-role
    list in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/booking_agent_cannot_activate_a_model_agreement
    """
    ctx = certified_hotel(b)
    agreement = b.draft_agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )

    refused = client.activate_model_agreement(agreement["id"], {}, BOOKING_AGENT)
    validate_error(refused, E.ERR_UNAUTHORIZED, 403)

    stored = validate_success(
        client.get_model_agreement(agreement["id"], PLATFORM_ADMIN)
    )
    assert stored["status"] == "DRAFT"
    assert stored["activated_by_user_id"] is None
    assert stored["version"] == 1

    allowed = validate_success(
        client.activate_model_agreement(agreement["id"], {}, COMPLIANCE_OFFICER)
    )
    assert allowed["status"] == "ACTIVE"


def test_markup_override_under_an_agency_agreement_is_rejected_at_approval(b, client):
    """A markup override proposes cleanly but cannot be approved against agency.

    PRD 3.3: "a `COMMISSION_PCT` override requires an `AGENCY` agreement, a
    `MARKUP_PCT` override requires a `MERCHANT` agreement, and a
    `FLAT_FEE_CENTS` override is accepted under either. An incompatible pairing
    is rejected with `ERR_OVERRIDE_MODEL_MISMATCH`."

    Design: Corner/errors/markup_override_under_an_agency_agreement_is_rejected
    """
    ctx = certified_hotel(b)
    b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )

    override = validate_success(
        client.create_commission_override(
            f.override_payload(
                ctx.supplier["id"],
                override_type="MARKUP_PCT",
                value=0.22,
                effective_from="2026-09-01",
                effective_to="2026-09-30",
                justification="seasonal markup pilot",
            ),
            COMMERCIAL_MANAGER,
        ),
        expected_status=201,
    )
    assert override["status"] == "PROPOSED"
    assert override["proposed_by_user_id"] == COMMERCIAL_MANAGER["X-User-ID"]

    refused = client.approve_commission_override(
        override["id"], {"note": "approving markup on an agency supplier"}, COMPLIANCE_OFFICER
    )
    validate_error(refused, E.ERR_OVERRIDE_MODEL_MISMATCH, 422)

    stored = validate_success(
        client.get_commission_override(override["id"], PLATFORM_ADMIN)
    )
    assert stored["status"] == "PROPOSED"
    assert stored["approved_by_user_id"] is None
    assert stored["version"] == 1


def test_same_user_cannot_propose_and_approve_a_commission_override(b, client):
    """Segregation of duties is tracked on the acting identifier, not the role.

    PRD 3.3: "The approving `X-User-ID` must differ from `proposed_by_user_id`."

    Design: Corner/rbac/same_user_cannot_propose_and_approve_a_commission_override
    """
    ctx = certified_hotel(b)
    b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )
    override = validate_success(
        client.create_commission_override(
            f.override_payload(
                ctx.supplier["id"],
                override_type="COMMISSION_PCT",
                value=0.19,
                effective_from="2026-09-01",
                effective_to="2026-09-30",
                justification="negotiated peak commission",
            ),
            DUAL_HAT_COMMERCIAL_MANAGER,
        ),
        expected_status=201,
    )

    self_approval = client.approve_commission_override(
        override["id"], {"note": "self approval"}, DUAL_HAT_COMPLIANCE_OFFICER
    )
    validate_error(self_approval, E.ERR_SEGREGATION_OF_DUTIES, 403)

    unchanged = validate_success(
        client.get_commission_override(override["id"], PLATFORM_ADMIN)
    )
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["version"] == 1

    independent = validate_success(
        client.approve_commission_override(
            override["id"], {"note": "independent approval"}, COMPLIANCE_OFFICER
        )
    )
    assert independent["status"] == "ACTIVE"
    assert independent["approved_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]
    assert independent["proposed_by_user_id"] == DUAL_HAT_USER_ID
    assert independent["version"] == 2


def test_plan_scoped_override_outranks_a_higher_supplier_wide_override(b, client):
    """Scope is ranked before magnitude, so the smaller plan-scoped rate wins.

    PRD 3.3: "Candidates are then ranked by three criteria applied strictly in
    this order: first, a plan-scoped override outranks a supplier-wide one;
    second, within the same scope, a higher `value` outranks a lower one".

    Design: Corner/cross_cutting_layers/plan_scoped_override_outranks_a_higher_supplier_wide_override
    """
    ctx = certified_hotel(b)
    b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )
    plan = b.rate_plan(ctx.supplier["id"], ctx.market["id"], tax_fee_pct=0.01)

    wide = b.override(
        ctx.supplier["id"],
        rate_plan_id=None,
        override_type="COMMISSION_PCT",
        value=0.20,
        effective_from="2026-09-01",
        effective_to="2026-09-30",
    )
    scoped = b.override(
        ctx.supplier["id"],
        rate_plan_id=plan["id"],
        override_type="COMMISSION_PCT",
        value=0.18,
        effective_from="2026-09-01",
        effective_to="2026-09-30",
    )
    assert wide["status"] == "ACTIVE" and scoped["status"] == "ACTIVE"

    offer = b.offer(plan["id"], travel_date="2026-09-20", net_rate_cents=24000)

    assert offer["pricing_model"] == "AGENCY"
    assert offer["applied_override_id"] == scoped["id"]
    assert_pct(offer["applied_rate_pct"], 0.18)
    assert offer["gross_cents"] == 24000
    assert offer["taxes_fees_cents"] == 240
    assert offer["display_total_cents"] == 24240
    assert offer["marketplace_margin_cents"] == 4320
    assert offer["supplier_payable_cents"] == 19680
