"""T&M tickets: tiered pricing, standby multiplier, signature chain, approval."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_tm_ticket,
    add_weather_observation,
    create_tm_ticket_payload,
    get_report,
    make_active_project,
    make_contractor_rep_headers,
    make_fully_signed_ticket,
    make_owner_rep_headers,
    make_pending_signature_ticket,
    make_project_manager_headers,
    make_report,
    make_report_bundle,
    make_superintendent_headers,
    make_work_area,
    make_work_item,
    set_clock,
    submit_clock_for,
    submit_report,
    validate_error,
    validate_success,
)

_PM = TEST_USERS["project_manager_headers"]
_SUPT = TEST_USERS["superintendent_headers"]
_CTR = TEST_USERS["contractor_rep_headers"]
_OWNER = TEST_USERS["owner_rep_headers"]

_RAIN_DAY_LABOR = [
    {"trade": "Labor", "worker_count": 2, "regular_hours": 8,
     "ot_hours": 2, "dt_hours": 1, "rate_cents": 5000}
]
_RAIN_DAY_EQUIPMENT = [
    {"equipment_type": "Crane", "hours": 4, "rate_cents": 8000, "standby": True}
]
_RAIN_DAY_MATERIALS = [
    {"description": "Rebar", "quantity": 10, "unit_price_cents": 3000}
]


def _rain_day_ticket(report_id, work_item_id, **overrides):
    payload = dict(labor_lines=_RAIN_DAY_LABOR,
                   equipment_lines=_RAIN_DAY_EQUIPMENT,
                   material_lines=_RAIN_DAY_MATERIALS)
    payload.update(overrides)
    return add_tm_ticket(report_id, work_item_id, **payload)


class TestTicketPricing:
    def test_tiered_rates_standby_multiplier_and_markup_combine(self, api):
        """PRD section 3.7: "A labor line costs its `worker_count` multiplied by
        the per-worker charge — `regular_hours` at the straight `rate_cents`,
        `ot_hours` at one and a half times `rate_cents`, and `dt_hours` at twice
        `rate_cents` — rounded to integer cents, and `labor_cost_cents` is the
        exact sum of those line costs. An equipment line costs its `hours`
        multiplied by its `rate_cents`, halved when the line's `standby` flag is
        set and the ticket's parent report carries at least one weather
        observation whose `work_impact` is `STOPPAGE`". "The ticket's
        `total_cents` is then `labor_cost_cents` plus `equipment_cost_cents`
        plus `materials_cost_cents`."

        Design: Difficulty/combinatorial_formula/tm_ticket_total_tiered_standby_conditional
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], cost_code="09-100",
                            budgeted_quantity=500, unit="EA", unit_cost_cents=100)
        add_weather_observation(ctx["report"]["id"],
                                observed_at="2026-08-05T09:00:00Z",
                                condition="RAIN", work_impact="STOPPAGE")

        ticket = _rain_day_ticket(ctx["report"]["id"], wi["id"])
        # Labor: 2 * (8*5000 + 2*5000*1.5 + 1*5000*2) = 130000.
        assert ticket["labor_cost_cents"] == 130000
        # Equipment: 4 * 8000 * 0.5 standby multiplier (STOPPAGE armed).
        assert ticket["equipment_cost_cents"] == 16000
        # Materials: subtotal 10 * 3000 = 30000, low tier 10% -> 3000.
        assert ticket["materials_subtotal_cents"] == 30000
        assert ticket["materials_markup_cents"] == 3000
        assert ticket["materials_cost_cents"] == 33000
        assert ticket["total_cents"] == 179000

    def test_standby_denied_without_stoppage_observation(self, api):
        """PRD section 3.7: "An equipment line costs its `hours` multiplied by
        its `rate_cents`, halved when the line's `standby` flag is set and the
        ticket's parent report carries at least one weather observation whose
        `work_impact` is `STOPPAGE`; in every other case the full rate applies".

        Design: Difficulty/combinatorial_formula/tm_ticket_total_tiered_standby_conditional
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        add_weather_observation(ctx["report"]["id"],
                                observed_at="2026-08-05T09:00:00Z",
                                condition="WIND", work_impact="PARTIAL",
                                wind_mph=30)

        ticket = _rain_day_ticket(ctx["report"]["id"], wi["id"])
        assert ticket["equipment_cost_cents"] == 32000, \
            "no STOPPAGE observation -> standby multiplier denied, full rate"
        assert ticket["total_cents"] == 130000 + 32000 + 33000

    def test_standby_line_bills_full_rate_on_partial_impact_report(self, api):
        """PRD section 3.7: "An equipment line costs its `hours` multiplied by
        its `rate_cents`, halved when the line's `standby` flag is set and the
        ticket's parent report carries at least one weather observation whose
        `work_impact` is `STOPPAGE`; in every other case the full rate applies,
        and each line rounds to integer cents before summing into
        `equipment_cost_cents`."

        Design: Corner/calculations/equipment_standby_requires_stoppage_observation
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        add_weather_observation(ctx["report"]["id"],
                                observed_at="2026-08-05T09:00:00Z",
                                condition="WIND", work_impact="PARTIAL",
                                wind_mph=30)

        ticket = add_tm_ticket(
            ctx["report"]["id"], wi["id"], description="Crane standby",
            labor_lines=[],
            equipment_lines=[{"equipment_type": "Crane", "hours": 4,
                              "rate_cents": 8000, "standby": True}])
        assert ticket["equipment_cost_cents"] == 32000, \
            "PARTIAL impact only: the 0.5 standby multiplier is not armed"
        assert ticket["total_cents"] == 32000


class TestMaterialMarkupTier:
    def test_tier_keyed_on_pre_markup_subtotal_at_boundaries(self, api):
        """PRD section 3.7: "second, the markup tier is selected from that
        pre-markup subtotal alone — a subtotal of one hundred thousand cents or
        less takes the ten percent markup, anything above takes the five percent
        markup, so a subtotal of exactly one hundred thousand cents stays in the
        low tier" and "The tier is never selected from the marked-up amount."

        Design: Difficulty/combinatorial_formula/material_markup_tier_keyed_on_pre_markup_subtotal
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        rid = ctx["report"]["id"]

        t1 = add_tm_ticket(rid, wi["id"], description="T1 at cap",
                           labor_lines=[],
                           material_lines=[{"description": "Steel", "quantity": 100,
                                            "unit_price_cents": 1000}])
        assert t1["materials_subtotal_cents"] == 100000
        assert t1["materials_markup_cents"] == 10000, \
            "subtotal exactly at the cap stays in the low (10%) tier"
        assert t1["materials_cost_cents"] == 110000, \
            "post-markup 110000 must not re-tier into the 5% band"

        t2 = add_tm_ticket(rid, wi["id"], description="T2 one cent over",
                           labor_lines=[],
                           material_lines=[{"description": "Steel", "quantity": 1,
                                            "unit_price_cents": 100001}])
        assert t2["materials_subtotal_cents"] == 100001
        assert t2["materials_markup_cents"] == 5000, \
            "5% of 100001 rounds half-up to 5000"
        assert t2["materials_cost_cents"] == 105001

    def test_markup_rounding_just_below_cap_and_high_tier(self, api):
        """PRD section 3.7: "third, `materials_markup_cents` is the subtotal
        multiplied by the tier percentage, rounded half-up to integer cents" and
        "a subtotal of one hundred thousand cents or less takes the ten percent
        markup, anything above takes the five percent markup".

        Design: Difficulty/combinatorial_formula/material_markup_tier_keyed_on_pre_markup_subtotal
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        rid = ctx["report"]["id"]

        below = add_tm_ticket(rid, wi["id"], description="one below cap",
                              labor_lines=[],
                              material_lines=[{"description": "Steel", "quantity": 1,
                                               "unit_price_cents": 99999}])
        assert below["materials_subtotal_cents"] == 99999
        # 10% of 99999 = 9999.9 -> round half-up -> 10000.
        assert below["materials_markup_cents"] == 10000
        assert below["materials_cost_cents"] == 109999

        high = add_tm_ticket(rid, wi["id"], description="high tier",
                             labor_lines=[],
                             material_lines=[{"description": "Steel", "quantity": 2,
                                              "unit_price_cents": 100000}])
        assert high["materials_subtotal_cents"] == 200000
        assert high["materials_markup_cents"] == 10000  # 5%
        assert high["materials_cost_cents"] == 210000


class TestSignatureChainAndRevision:
    def test_signature_order_fork_and_revision_cycle(self, api):
        """PRD section 3.7: "Order is enforced: the owner signature is only
        effective once the contractor has signed, and an owner attempt while
        `contractor_signed_by` is still null fails with `ERR_SIGNATURE_ORDER`."
        and "From `REJECTED`, the superintendent may run the revision cycle back
        to `DRAFT` — provided the parent report is `EDITABLE` — which increments
        the ticket's `revision_count` and clears both `contractor_signed_by` and
        `owner_signed_by` to null, resetting the chain."

        Design: Difficulty/non_linear_state_machine/tm_ticket_signature_fork_and_revision_cycle
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        ticket = make_pending_signature_ticket(ctx["report"]["id"], wi["id"])
        assert ticket["status"] == "PENDING_SIGNATURES"

        owner_first = api.sign_ticket(ticket["id"], {"signer_role": "OWNER"}, _OWNER)
        validate_error(owner_first, ApiErrorId.ERR_SIGNATURE_ORDER)
        assert owner_first.status_code == 409

        after_contractor = validate_success(api.sign_ticket(
            ticket["id"], {"signer_role": "CONTRACTOR"}, _CTR))
        assert after_contractor["status"] == "PARTIALLY_SIGNED"
        assert after_contractor["contractor_signed_by"] == "ctr-1"

        after_owner = validate_success(api.sign_ticket(
            ticket["id"], {"signer_role": "OWNER"}, _OWNER))
        assert after_owner["status"] == "FULLY_SIGNED"
        assert after_owner["owner_signed_by"] == "owner-1"

        rejected = validate_success(api.reject_ticket(
            ticket["id"], {"reason": "Rate dispute"}, _PM))
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "Rate dispute"

        revised = validate_success(api.revise_ticket(ticket["id"], _SUPT))
        assert revised["status"] == "DRAFT"
        assert revised["revision_count"] == 1
        assert revised["contractor_signed_by"] is None
        assert revised["owner_signed_by"] is None

    def test_signer_must_not_be_ticket_creator(self, api):
        """PRD section 3.7: "Segregation is enforced twice over: no signer may
        be the ticket's `created_by_user_id`, and the owner signer must
        additionally differ from the contractor signer, with violations failing
        as `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/non_linear_state_machine/tm_ticket_signature_fork_and_revision_cycle
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        # Ticket created by supt-1 (fixture default).
        ticket = make_pending_signature_ticket(ctx["report"]["id"], wi["id"])

        creator_as_contractor = api.sign_ticket(
            ticket["id"], {"signer_role": "CONTRACTOR"},
            make_contractor_rep_headers("supt-1"))
        validate_error(creator_as_contractor, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert creator_as_contractor.status_code == 403

        # Owner signer reusing the contractor signer's id is also segregated.
        validate_success(api.sign_ticket(ticket["id"], {"signer_role": "CONTRACTOR"},
                                         _CTR))
        owner_same_as_contractor = api.sign_ticket(
            ticket["id"], {"signer_role": "OWNER"}, make_owner_rep_headers("ctr-1"))
        validate_error(owner_same_as_contractor, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert owner_same_as_contractor.status_code == 403


class TestApprovalGates:
    def test_state_gate_reported_before_fiscal_gate(self, api):
        """PRD section 2.9: "checks execute in a fixed order, and the first
        failing check produces the error response." Layer 6 runs "the target
        resource's own state machine must permit the requested transition from
        its current state, else the resource's invalid-transition error" while
        layer 11 is "Last of all, the not-to-exceed ceiling check on T&M
        approval (`ERR_TM_CEILING_EXCEEDED`)." A DRAFT ticket over its ceiling
        therefore reports the state failure, never the fiscal one.

        Design: Difficulty/priority_pair_validation_conflict/ticket_approve_state_beats_fiscal
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        ticket = add_tm_ticket(ctx["report"]["id"], wi["id"],
                               description="Over-ceiling extra",
                               labor_lines=_RAIN_DAY_LABOR,
                               authorized_ceiling_cents=1000)
        assert ticket["total_cents"] == 130000

        resp = api.approve_ticket(ticket["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_TRANSITION)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] != "ERR_TM_CEILING_EXCEEDED"
        assert api.get_tm_ticket(ticket["id"], _PM).json()["data"]["status"] == "DRAFT"

    def test_partially_signed_over_ceiling_also_reports_state(self, api):
        """PRD section 3.7: "The ticket must be `FULLY_SIGNED`" for approval,
        and PRD section 2.9 places the state check ("the target resource's own
        state machine must permit the requested transition from its current
        state, else the resource's invalid-transition error") ahead of the
        fiscal gate ("Last of all, the not-to-exceed ceiling check on T&M
        approval (`ERR_TM_CEILING_EXCEEDED`)").

        Design: Difficulty/priority_pair_validation_conflict/ticket_approve_state_beats_fiscal
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        ticket = make_pending_signature_ticket(
            ctx["report"]["id"], wi["id"], labor_lines=_RAIN_DAY_LABOR,
            authorized_ceiling_cents=1000)
        validate_success(api.sign_ticket(ticket["id"], {"signer_role": "CONTRACTOR"},
                                         _CTR))
        assert ticket["total_cents"] == 130000  # over the 1000-cent ceiling

        resp = api.approve_ticket(ticket["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_TRANSITION)
        assert resp.json()["data"]["error_id"] != "ERR_TM_CEILING_EXCEEDED"
        assert api.get_tm_ticket(ticket["id"], _PM).json()["data"]["status"] == \
            "PARTIALLY_SIGNED"

    def test_ceiling_equality_passes_approval(self, api):
        """PRD section 3.7: "when `authorized_ceiling_cents` is set,
        `total_cents` must not exceed it, with equality passing — an
        over-ceiling ticket fails with `ERR_TM_CEILING_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/ceiling_equality_passes_approval
        """
        ctx = make_report_bundle(with_weather=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        add_weather_observation(ctx["report"]["id"],
                                observed_at="2026-08-05T09:00:00Z",
                                condition="RAIN", work_impact="STOPPAGE")
        ticket = _rain_day_ticket(ctx["report"]["id"], wi["id"],
                                  authorized_ceiling_cents=179000)
        assert ticket["total_cents"] == 179000

        validate_success(api.submit_ticket_for_signature(ticket["id"], _SUPT))
        validate_success(api.sign_ticket(ticket["id"], {"signer_role": "CONTRACTOR"},
                                         _CTR))
        validate_success(api.sign_ticket(ticket["id"], {"signer_role": "OWNER"},
                                         _OWNER))
        set_clock(submit_clock_for("2026-08-05"))
        submit_report(ctx["report"]["id"])

        approved = validate_success(api.approve_ticket(ticket["id"], _PM))
        assert approved["status"] == "APPROVED", \
            "total equal to the ceiling passes the not-to-exceed gate"

    def test_one_cent_over_ceiling_rejected(self, api):
        """PRD section 3.7: "when `authorized_ceiling_cents` is set,
        `total_cents` must not exceed it, with equality passing — an
        over-ceiling ticket fails with `ERR_TM_CEILING_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/ceiling_equality_passes_approval
        """
        ctx = make_report_bundle(with_weather=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        add_weather_observation(ctx["report"]["id"],
                                observed_at="2026-08-05T09:00:00Z",
                                condition="RAIN", work_impact="STOPPAGE")
        ticket = make_fully_signed_ticket(ctx["report"]["id"], wi["id"],
                                          labor_lines=_RAIN_DAY_LABOR,
                                          equipment_lines=_RAIN_DAY_EQUIPMENT,
                                          material_lines=_RAIN_DAY_MATERIALS,
                                          authorized_ceiling_cents=178999)
        assert ticket["total_cents"] == 179000
        set_clock(submit_clock_for("2026-08-05"))
        submit_report(ctx["report"]["id"])

        resp = api.approve_ticket(ticket["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_TM_CEILING_EXCEEDED)
        assert resp.status_code == 422


class TestTicketTerminalAndEmptiness:
    def test_void_and_sign_from_approved_rejected(self, api):
        """PRD section 3.7: "Voiding discards a ticket entirely: permitted from
        `DRAFT`, `PENDING_SIGNATURES`, `PARTIALLY_SIGNED`, or `REJECTED` while
        the report is `EDITABLE`, landing in the terminal `VOID`" — APPROVED is
        terminal. And "Signatures are accepted only from those two states — any
        other status fails with `ERR_TICKET_INVALID_TRANSITION`."

        Design: Corner/state_machines/ticket_void_from_terminal_approved_rejected
        """
        ctx = make_report_bundle()
        wi = make_work_item(ctx["project"]["id"], cost_code="09-1",
                            budgeted_quantity=500, unit="EA", unit_cost_cents=100)
        ticket = make_fully_signed_ticket(ctx["report"]["id"], wi["id"])
        set_clock(submit_clock_for("2026-08-05"))
        submit_report(ctx["report"]["id"])
        approved = validate_success(api.approve_ticket(ticket["id"], _PM))
        assert approved["status"] == "APPROVED"

        void_resp = api.void_ticket(ticket["id"], _SUPT)
        validate_error(void_resp, ApiErrorId.ERR_TICKET_INVALID_TRANSITION)
        assert void_resp.status_code == 409

        sign_resp = api.sign_ticket(ticket["id"], {"signer_role": "OWNER"}, _OWNER)
        validate_error(sign_resp, ApiErrorId.ERR_TICKET_INVALID_TRANSITION)

        assert api.get_tm_ticket(ticket["id"], _PM).json()["data"]["status"] == \
            "APPROVED"

    def test_zero_total_ticket_cannot_enter_signature_workflow(self, api):
        """PRD section 3.7: "Submitting a `DRAFT` ticket for signature requires
        a priced total greater than zero — an empty ticket fails with
        `ERR_TICKET_EMPTY`".

        Design: Corner/errors/ticket_empty_rejected_at_submit_for_signature
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        ticket = add_tm_ticket(ctx["report"]["id"], wi["id"], description="free",
                               labor_lines=[{"trade": "Labor", "worker_count": 1,
                                             "regular_hours": 2, "ot_hours": 0,
                                             "dt_hours": 0, "rate_cents": 0}])
        assert ticket["total_cents"] == 0

        resp = api.submit_ticket_for_signature(ticket["id"], _SUPT)
        validate_error(resp, ApiErrorId.ERR_TICKET_EMPTY)
        assert resp.status_code == 422

    def test_signer_role_must_match_caller_role(self, api):
        """PRD section 3.7: "the declared role must match the caller's actual
        role: `CONTRACTOR` signing is the `ContractorRep`'s act and `OWNER`
        signing the `OwnerRep`'s, with a role mismatch rejected as
        `ERR_FORBIDDEN`." and "the owner signer must additionally differ from
        the contractor signer, with violations failing as
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/contractor_cannot_sign_owner_role
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        wi = make_work_item(ctx["project"]["id"], budgeted_quantity=500,
                            unit="EA", unit_cost_cents=100)
        ticket = make_pending_signature_ticket(ctx["report"]["id"], wi["id"])
        validate_success(api.sign_ticket(ticket["id"], {"signer_role": "CONTRACTOR"},
                                         make_contractor_rep_headers("ctr-1")))

        mismatch = api.sign_ticket(ticket["id"], {"signer_role": "OWNER"},
                                   make_contractor_rep_headers("ctr-2"))
        validate_error(mismatch, ApiErrorId.ERR_FORBIDDEN)
        assert mismatch.status_code == 403

        same_person = api.sign_ticket(ticket["id"], {"signer_role": "OWNER"},
                                      make_owner_rep_headers("ctr-1"))
        validate_error(same_person, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert same_person.status_code == 403
