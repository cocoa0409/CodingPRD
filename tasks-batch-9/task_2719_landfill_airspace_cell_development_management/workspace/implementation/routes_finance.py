"""Closure/post-closure financial assurance and host-community agreements."""
from core import (Body, ALL_ROLES, D, created, endpoint, err, filtered,
                  fk_or_404, get_or_404, new_row, obj_response, paged, public,
                  q2, rows, touch)
import services as S


def _set_assurance_posture(lf, shortfall, escalating):
    """Certification is the one place a second consecutive shortfall escalates."""
    if D(shortfall) == 0:
        lf["financial_assurance_status"] = "FUNDED"
    elif escalating and lf["financial_assurance_status"] == "SHORTFALL_REVIEW":
        lf["financial_assurance_status"] = "LAPSED"
        lf["operating_status"] = "SUSPENDED_FINANCIAL"
    else:
        lf["financial_assurance_status"] = "SHORTFALL_REVIEW"


def register(app):
    # ------------------------------------------------ closure cost estimates ---
    @endpoint(app, "/closure-cost-estimates", ["POST"], ["FinanceOfficer"])
    def file_estimate(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        estimate_year = b.integer("estimate_year", minimum=2000, maximum=2100)
        unit_cost = b.number("closure_unit_cost_per_sf", gt=0)
        annual_cost = b.number("post_closure_annual_cost", gt=0)
        inflation_pct = b.number("inflation_pct", ge=0, le="0.20")
        expected = b.integer("expected_landfill_version")
        years = b.integer("post_closure_years", required=False, minimum=1,
                          maximum=60, default=30)
        lf = fk_or_404("landfill", landfill_id)
        if expected != lf["version"]:
            raise err("ERR_STALE_LANDFILL_VERSION",
                      "The landfill has moved on since it was last read.")
        for other in S.estimates_of_landfill(lf["id"]):
            if other["estimate_year"] == estimate_year:
                raise err("ERR_DUPLICATE_ESTIMATE_YEAR",
                          "This landfill already has an update for that year.")
        closure, post_closure, required, shortfall = S.closure_cost_figures(
            lf, unit_cost, annual_cost, inflation_pct, years,
            lf["assurance_funded_amount"])
        row = new_row("closure_cost_estimate", {
            "landfill_id": lf["id"],
            "estimate_year": estimate_year,
            "closure_unit_cost_per_sf": unit_cost,
            "post_closure_annual_cost": annual_cost,
            "inflation_pct": inflation_pct,
            "post_closure_years": years,
            "closure_cost_total": closure,
            "post_closure_cost_total": post_closure,
            "required_assurance_amount": required,
            "funding_shortfall": shortfall,
            "instrument_type": None,
            "status": "DRAFT",
            "_filed_by": user_id,
        })
        touch(lf)
        return created(public(row))

    @endpoint(app, "/closure-cost-estimates/<closure_cost_estimate_id>", ["GET"],
              ALL_ROLES)
    def read_estimate(user_id, role, closure_cost_estimate_id):
        return obj_response(public(get_or_404("closure_cost_estimate",
                                              closure_cost_estimate_id)))

    @endpoint(app, "/closure-cost-estimates", ["GET"], ALL_ROLES)
    def list_estimates(user_id, role):
        return paged(filtered(rows("closure_cost_estimate"), {
            "landfill_id": "landfill_id",
            "estimate_year": "estimate_year",
            "status": "status",
        }))

    @endpoint(app, "/closure-cost-estimates/<closure_cost_estimate_id>/certify",
              ["POST"], ["FinanceOfficer"])
    def certify_estimate(user_id, role, closure_cost_estimate_id):
        est = get_or_404("closure_cost_estimate", closure_cost_estimate_id)
        if est["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a DRAFT update may be certified.")
        lf = S.landfill_of(est["landfill_id"])
        if lf["operating_status"] == "CLOSED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "A closed site no longer certifies annual updates.")
        if user_id == est.get("_filed_by"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "The officer who filed the update may not certify it.")
        closure, post_closure, required, shortfall = S.closure_cost_figures(
            lf, est["closure_unit_cost_per_sf"], est["post_closure_annual_cost"],
            est["inflation_pct"], est["post_closure_years"],
            lf["assurance_funded_amount"])
        est["closure_cost_total"] = closure
        est["post_closure_cost_total"] = post_closure
        est["required_assurance_amount"] = required
        est["funding_shortfall"] = shortfall
        est["status"] = "CERTIFIED"
        touch(est)
        for other in S.estimates_of_landfill(lf["id"]):
            if other["id"] == est["id"]:
                continue
            if other["status"] in ("CERTIFIED", "STALE"):
                other["status"] = "SUPERSEDED"
                touch(other)
        _set_assurance_posture(lf, shortfall, True)
        touch(lf)
        return obj_response(public(est))

    @endpoint(app,
              "/closure-cost-estimates/<closure_cost_estimate_id>/fund-assurance",
              ["POST"], ["FinanceOfficer"])
    def fund_assurance(user_id, role, closure_cost_estimate_id):
        b = Body()
        instrument_type = b.enum("instrument_type", S.INSTRUMENT_TYPES)
        funded_amount = b.number("funded_amount", ge=0)
        est = get_or_404("closure_cost_estimate", closure_cost_estimate_id)
        lf = S.landfill_of(est["landfill_id"])
        est["instrument_type"] = instrument_type
        lf["assurance_funded_amount"] = funded_amount
        shortfall = D(est["required_assurance_amount"]) - D(funded_amount)
        if shortfall < 0:
            shortfall = D(0)
        shortfall = float(q2(shortfall))
        est["funding_shortfall"] = shortfall
        touch(est)
        _set_assurance_posture(lf, shortfall, False)
        touch(lf)
        return obj_response(public(est))

    # --------------------------------------------- host community agreements ---
    @endpoint(app, "/host-community-agreements", ["POST"], ["FinanceOfficer"])
    def draft_agreement(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        community_name = b.string("community_name", minlen=1, maxlen=120)
        posted = b.number("posted_tipping_fee_per_ton", gt=0)
        host_fee = b.number("host_fee_per_ton", ge=0)
        tier1_tons = b.number("tier1_monthly_tons", gt=0)
        tier1_pct = b.number("royalty_tier1_pct", ge=0, le="0.50")
        tier2_pct = b.number("royalty_tier2_pct", ge=0, le="0.50")
        minimum_annual = b.number("minimum_annual_payment", ge=0)
        effective_from = b.timestamp("effective_from")
        expires_on = b.timestamp("expires_on")
        if not expires_on > effective_from:
            raise err("ERR_INVALID_REQUEST",
                      "expires_on must be strictly after effective_from.")
        lf = fk_or_404("landfill", landfill_id)
        row = new_row("host_community_agreement", {
            "landfill_id": lf["id"],
            "community_name": community_name,
            "posted_tipping_fee_per_ton": posted,
            "host_fee_per_ton": host_fee,
            "tier1_monthly_tons": tier1_tons,
            "royalty_tier1_pct": tier1_pct,
            "royalty_tier2_pct": tier2_pct,
            "minimum_annual_payment": minimum_annual,
            "effective_from": effective_from,
            "expires_on": expires_on,
            "amendment_round": 0,
            "amendment_reason": None,
            "termination_reason": None,
            "status": "DRAFT",
        })
        return created(public(row))

    @endpoint(app, "/host-community-agreements/<host_community_agreement_id>",
              ["GET"], ALL_ROLES)
    def read_hca(user_id, role, host_community_agreement_id):
        return obj_response(public(get_or_404("host_community_agreement",
                                              host_community_agreement_id)))

    @endpoint(app, "/host-community-agreements", ["GET"], ALL_ROLES)
    def list_hcas(user_id, role):
        return paged(filtered(rows("host_community_agreement"), {
            "landfill_id": "landfill_id",
            "status": "status",
        }))

    @endpoint(app,
              "/host-community-agreements/<host_community_agreement_id>/execute",
              ["POST"], ["FinanceOfficer"])
    def execute_hca(user_id, role, host_community_agreement_id):
        b = Body()
        expected = b.integer("expected_landfill_version")
        hca = get_or_404("host_community_agreement", host_community_agreement_id)
        lf = S.landfill_of(hca["landfill_id"])
        if expected != lf["version"]:
            raise err("ERR_STALE_LANDFILL_VERSION",
                      "The landfill has moved on since it was last read.")
        if hca["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a DRAFT agreement may be executed.")
        for other in S.agreements_of_landfill(lf["id"]):
            if other["id"] != hca["id"] and other["status"] == "UNDER_AMENDMENT":
                raise err("ERR_HOST_AGREEMENT_ALREADY_LIVE",
                          "A live re-negotiation blocks a fresh execution.")
        for other in S.agreements_of_landfill(lf["id"]):
            if other["id"] != hca["id"] and other["status"] == "EXECUTED":
                other["termination_reason"] = "SUPERSEDED_BY_NEW_AGREEMENT"
                other["status"] = "TERMINATED"
                touch(other)
        hca["status"] = "EXECUTED"
        touch(hca)
        touch(lf)
        return obj_response(public(hca))

    @endpoint(app, "/host-community-agreements/<host_community_agreement_id>"
                   "/open-amendment", ["POST"], ["FinanceOfficer"])
    def open_amendment(user_id, role, host_community_agreement_id):
        b = Body()
        reason = b.string("amendment_reason")
        hca = get_or_404("host_community_agreement", host_community_agreement_id)
        if hca["status"] == "UNDER_AMENDMENT":
            # The single rung-9 carve-out: the specific error outranks the generic.
            raise err("ERR_AMENDMENT_IN_PROGRESS",
                      "This agreement is already under amendment.")
        if hca["status"] != "EXECUTED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only an EXECUTED agreement may be re-negotiated.")
        hca["amendment_reason"] = reason
        hca["status"] = "UNDER_AMENDMENT"
        touch(hca)
        return obj_response(public(hca))

    @endpoint(app, "/host-community-agreements/<host_community_agreement_id>"
                   "/execute-amendment", ["POST"], ["FinanceOfficer"])
    def execute_amendment(user_id, role, host_community_agreement_id):
        b = Body()
        posted = b.number("posted_tipping_fee_per_ton", gt=0)
        host_fee = b.number("host_fee_per_ton", ge=0)
        tier1_tons = b.number("tier1_monthly_tons", gt=0)
        tier1_pct = b.number("royalty_tier1_pct", ge=0, le="0.50")
        tier2_pct = b.number("royalty_tier2_pct", ge=0, le="0.50")
        hca = get_or_404("host_community_agreement", host_community_agreement_id)
        if hca["status"] != "UNDER_AMENDMENT":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only an agreement under amendment may be re-executed.")
        hca["posted_tipping_fee_per_ton"] = posted
        hca["host_fee_per_ton"] = host_fee
        hca["tier1_monthly_tons"] = tier1_tons
        hca["royalty_tier1_pct"] = tier1_pct
        hca["royalty_tier2_pct"] = tier2_pct
        hca["amendment_round"] = hca["amendment_round"] + 1
        hca["amendment_reason"] = None
        hca["status"] = "EXECUTED"
        touch(hca)
        return obj_response(public(hca))

    @endpoint(app, "/host-community-agreements/<host_community_agreement_id>"
                   "/terminate", ["POST"], ["FinanceOfficer"])
    def terminate_hca(user_id, role, host_community_agreement_id):
        b = Body()
        reason = b.string("termination_reason")
        hca = get_or_404("host_community_agreement", host_community_agreement_id)
        if hca["status"] not in ("DRAFT", "EXECUTED"):
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a draft or executed agreement may be terminated.")
        hca["termination_reason"] = reason
        hca["status"] = "TERMINATED"
        touch(hca)
        touch(S.landfill_of(hca["landfill_id"]))
        return obj_response(public(hca))
