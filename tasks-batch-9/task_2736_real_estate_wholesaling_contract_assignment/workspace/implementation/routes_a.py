"""Wholesalers, marketing campaigns and seller leads."""
import calc
import services as svc
from common import (
    ALL_ROLES,
    authenticate,
    base_record,
    fail,
    get_body,
    list_response,
    now,
    opt_bool,
    opt_enum,
    opt_id,
    opt_int,
    req_enum,
    req_int,
    req_state_code,
    req_str,
    respond_object,
    touch,
)

LICENSURE_STATUSES = ("UNLICENSED", "LICENSED_AGENT", "LICENSED_BROKER")
CHANNELS = ("DIRECT_MAIL", "SMS", "COLD_CALL", "BANDIT_SIGN", "ONLINE_AD")
DISTRESS_FLAGS = (
    "FORECLOSURE_NOTICE",
    "PROBATE",
    "TAX_DELINQUENT",
    "CODE_VIOLATION",
    "DIVORCE",
    "RELOCATION",
)
SCREENING_VARIANTS = ("STATUTORY", "EFFECTIVE")


def register(app):
    # -- Wholesaler ---------------------------------------------------------
    @app.post("/wholesalers")
    def create_wholesaler():
        authenticate(["PlatformAdmin"])
        body = get_body()
        legal_name = req_str(body, "legal_name", max_len=200)
        state_code = req_state_code(body, "state_code")
        template = req_str(body, "disclosure_template_version", max_len=32)
        licensure = opt_enum(
            body, "licensure_status", LICENSURE_STATUSES, default="UNLICENSED"
        )
        capacity = opt_int(body, "funding_window_capacity", minimum=1, default=1)
        rec = base_record()
        rec.update(
            {
                "legal_name": legal_name,
                "state_code": state_code,
                "licensure_status": licensure,
                "disclosure_template_version": template,
                "funding_window_capacity": capacity,
                "adverse_finding_count": 0,
                "compliance_hold": False,
                "executed_assignment_count": 0,
            }
        )
        svc.store("wholesalers", rec)
        return respond_object(rec, 201)

    @app.get("/wholesalers/<wholesaler_id>")
    def read_wholesaler(wholesaler_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("wholesalers", wholesaler_id))

    @app.get("/wholesalers")
    def list_wholesalers():
        authenticate(["ComplianceOfficer", "PlatformAdmin"], require_user_id=False)
        return list_response(
            svc.all_of("wholesalers"),
            [("state_code", "state_code"), ("licensure_status", "licensure_status")],
        )

    # -- MarketingCampaign --------------------------------------------------
    @app.post("/marketing-campaigns")
    def create_campaign():
        authenticate(["Wholesaler"])
        body = get_body()
        wholesaler_id = req_str(body, "wholesaler_id")
        channel = req_enum(body, "channel", CHANNELS)
        headline = req_str(body, "headline", max_len=200)
        target_state = req_state_code(body, "target_state_code")
        intent = opt_bool(body, "discloses_intent_to_assign", default=False)
        unlicensed = opt_bool(body, "discloses_unlicensed_status", default=False)
        dnc = opt_bool(body, "dnc_scrubbed", default=False)
        wholesaler = svc.load("wholesalers", wholesaler_id)
        svc.guard_compliance_hold(wholesaler)
        rec = base_record()
        rec.update(
            {
                "wholesaler_id": wholesaler["id"],
                "channel": channel,
                "headline": headline,
                "target_state_code": target_state,
                "discloses_intent_to_assign": intent,
                "discloses_unlicensed_status": unlicensed,
                "dnc_scrubbed": dnc,
                "status": "DRAFT",
                "published_at": None,
                "suspension_count": 0,
            }
        )
        svc.store("marketing_campaigns", rec)
        return respond_object(rec, 201)

    @app.get("/marketing-campaigns/<marketing_campaign_id>")
    def read_campaign(marketing_campaign_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(
            svc.load("marketing_campaigns", marketing_campaign_id)
        )

    @app.get("/marketing-campaigns")
    def list_campaigns():
        authenticate(
            ["Wholesaler", "ComplianceOfficer", "PlatformAdmin"], require_user_id=False
        )
        return list_response(
            svc.all_of("marketing_campaigns"),
            [
                ("wholesaler_id", "wholesaler_id"),
                ("status", "status"),
                ("channel", "channel"),
            ],
        )

    @app.post("/marketing-campaigns/<marketing_campaign_id>/publish")
    def publish_campaign(marketing_campaign_id):
        _role, user_id = authenticate(["Wholesaler"])
        campaign = svc.load("marketing_campaigns", marketing_campaign_id)
        svc.guard_owner(campaign["wholesaler_id"] == user_id)
        if campaign["status"] not in ("DRAFT", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Only a DRAFT or SUSPENDED campaign may publish.")
        wholesaler = svc.collection("wholesalers").get(campaign["wholesaler_id"])
        svc.guard_compliance_hold(wholesaler)
        if not campaign["discloses_intent_to_assign"]:
            fail(
                "ERR_INTENT_TO_ASSIGN_NOT_DISCLOSED",
                "The creative must disclose the intent to assign.",
            )
        if (
            wholesaler is not None
            and wholesaler["licensure_status"] == "UNLICENSED"
            and not campaign["discloses_unlicensed_status"]
        ):
            fail(
                "ERR_LICENSURE_DISCLOSURE_MISSING",
                "An unlicensed advertiser must disclose its licensure posture.",
            )
        if campaign["channel"] in ("SMS", "COLD_CALL") and not campaign["dnc_scrubbed"]:
            fail(
                "ERR_DNC_SCRUB_REQUIRED",
                "Telephonic channels require a do-not-call scrub.",
            )
        campaign["status"] = "PUBLISHED"
        campaign["published_at"] = now()
        touch(campaign)
        svc.recompute_campaign_leads(campaign)
        return respond_object(campaign)

    @app.post("/marketing-campaigns/<marketing_campaign_id>/archive")
    def archive_campaign(marketing_campaign_id):
        _role, user_id = authenticate(["Wholesaler"])
        campaign = svc.load("marketing_campaigns", marketing_campaign_id)
        svc.guard_owner(campaign["wholesaler_id"] == user_id)
        if campaign["status"] == "ARCHIVED":
            fail("ERR_INVALID_STATE", "The campaign is already archived.")
        campaign["status"] = "ARCHIVED"
        touch(campaign)
        return respond_object(campaign)

    # -- SellerLead ---------------------------------------------------------
    @app.post("/seller-leads")
    def create_lead():
        authenticate(["Wholesaler"])
        body = get_body()
        wholesaler_id = req_str(body, "wholesaler_id")
        owner_name = req_str(body, "owner_name", max_len=200)
        property_address = req_str(body, "property_address", max_len=300)
        state_code = req_state_code(body, "state_code")
        market_value = req_int(body, "estimated_market_value_cents", minimum=1)
        senior_lien = req_int(body, "recorded_senior_lien_cents", minimum=0)
        campaign_id = opt_id(body, "marketing_campaign_id")
        junior_lien = opt_int(body, "junior_lien_cents", minimum=0, default=0)
        delinquent_tax = opt_int(
            body, "delinquent_property_tax_cents", minimum=0, default=0
        )
        flags = body.get("distress_flags")
        if flags is None:
            flags = []
        if not isinstance(flags, list):
            fail("ERR_INVALID_REQUEST", "distress_flags must be an array.")
        for flag in flags:
            if not isinstance(flag, str) or flag not in DISTRESS_FLAGS:
                fail("ERR_INVALID_REQUEST", "distress_flags holds unknown values.")

        wholesaler = svc.load("wholesalers", wholesaler_id)
        campaign = None
        if campaign_id is not None:
            campaign = svc.load("marketing_campaigns", campaign_id)
            if campaign["status"] != "PUBLISHED":
                fail(
                    "ERR_CAMPAIGN_NOT_PUBLISHED",
                    "The attributed campaign is not published.",
                )
        svc.guard_compliance_hold(wholesaler)

        rec = base_record()
        rec.update(
            {
                "wholesaler_id": wholesaler["id"],
                "marketing_campaign_id": campaign["id"] if campaign else None,
                "owner_name": owner_name,
                "property_address": property_address,
                "state_code": state_code,
                "estimated_market_value_cents": market_value,
                "recorded_senior_lien_cents": senior_lien,
                "junior_lien_cents": junior_lien,
                "delinquent_property_tax_cents": delinquent_tax,
                "distress_flags": list(flags),
                "status": "PROSPECT",
                "screening_variant": None,
                "net_equity_cents": None,
                "equity_pct": None,
                "protection_tier": None,
                "screened_at": None,
                "lead_gen_blocked": False,
            }
        )
        svc.store("seller_leads", rec)
        rec["lead_gen_blocked"] = svc.lead_blocked_value(rec)
        return respond_object(rec, 201)

    @app.get("/seller-leads/<seller_lead_id>")
    def read_lead(seller_lead_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("seller_leads", seller_lead_id))

    @app.get("/seller-leads")
    def list_leads():
        authenticate(
            ["Wholesaler", "ComplianceOfficer", "PlatformAdmin"], require_user_id=False
        )
        return list_response(
            svc.all_of("seller_leads"),
            [
                ("wholesaler_id", "wholesaler_id"),
                ("marketing_campaign_id", "marketing_campaign_id"),
                ("status", "status"),
                ("protection_tier", "protection_tier"),
            ],
        )

    @app.post("/seller-leads/<seller_lead_id>/protection-screen")
    def protection_screen(seller_lead_id):
        role, user_id = authenticate(["Wholesaler", "ComplianceOfficer"])
        body = get_body()
        variant = req_enum(body, "screening_variant", SCREENING_VARIANTS)
        lead = svc.load("seller_leads", seller_lead_id)
        if role == "Wholesaler":
            svc.guard_owner(lead["wholesaler_id"] == user_id)
        if lead["status"] not in ("PROSPECT", "SCREENED"):
            fail(
                "ERR_INVALID_STATE",
                "A lead under contract or closed can no longer be screened.",
            )
        wholesaler = svc.wholesaler_of_lead(lead)
        svc.guard_compliance_hold(wholesaler)
        if lead.get("lead_gen_blocked"):
            fail("ERR_INVALID_STATE", "Lead generation is blocked on this lead.")

        net, pct, tier = calc.seller_equity_exposure(lead, variant)
        lead["screening_variant"] = variant
        lead["net_equity_cents"] = net
        lead["equity_pct"] = pct
        lead["protection_tier"] = tier
        lead["screened_at"] = now()
        lead["status"] = "SCREENED"
        touch(lead)
        return respond_object(lead)
