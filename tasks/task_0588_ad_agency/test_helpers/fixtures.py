"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so each of
these helpers builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls go through get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" rather than a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_campaign_payload,
    create_client_payload,
    create_deliverable_payload,
    create_insertion_order_payload,
    create_invoice_payload,
    create_media_placement_payload,
    create_media_plan_payload,
    create_rate_card_payload,
    create_retainer_payload,
    create_sow_payload,
    create_staff_member_payload,
    create_time_entry_payload,
    create_vendor_cost_payload,
)
from .test_users import (
    make_account_manager_headers,
    make_agency_admin_headers,
    make_client_reviewer_headers,
    make_creative_lead_headers,
    make_media_buyer_headers,
)

# --------------------------------------------------------------------------
# Tier 0 — primitives
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str, api=api_client) -> dict:
    """Move the logical clock (PRD §2.5). Returns { now_utc, expired_sow_ids }."""
    return get_success_data(api.set_clock(to_iso8601, make_agency_admin_headers()))


def register_client(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_client(create_client_payload(**overrides), make_agency_admin_headers())
    )


def register_staff(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_staff_member(
            create_staff_member_payload(**overrides), make_agency_admin_headers()
        )
    )


def register_placement(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_media_placement(
            create_media_placement_payload(**overrides), make_agency_admin_headers()
        )
    )


def media_plan_version(media_plan_id: str, buyer_headers: dict, api=api_client) -> int:
    """Re-read the plan — the canonical way to obtain a fresh stale-version token (PRD §2.7)."""
    return get_success_data(api.get_media_plan(media_plan_id, buyer_headers))["version"]


def retainer_version(retainer_id: str, api=api_client) -> int:
    """Re-read the retainer — the canonical way to obtain a fresh stale-version token (PRD §2.7)."""
    return get_success_data(api.get_retainer(retainer_id, make_agency_admin_headers()))["version"]


# --------------------------------------------------------------------------
# Tier 1/2 — the base scenario every workflow test starts from
# --------------------------------------------------------------------------


def setup_base(
    api=api_client,
    clock=TEST_DEFAULTS["CLOCK"],
    retainer_funding=5_000_000,
    labor_cap_cents=TEST_DEFAULTS["LABOR_CAP_CENTS"],
    markup_pct=TEST_DEFAULTS["MARKUP_PCT"],
    sow_title="Q3 Retainer SOW",
    effective_start=TEST_DEFAULTS["SOW_EFFECTIVE_START"],
    effective_end=TEST_DEFAULTS["SOW_EFFECTIVE_END"],
    countersign=True,
    launch=True,
) -> dict:
    """Advertiser + rate card + staff + retainer + countersigned SOW + IN_FLIGHT campaign.

    Staff roster (all four exist in every scenario):
      Dana  SENIOR   cost 6000 c/h  — acts as CreativeLead when logging time
      Ravi  JUNIOR   cost 3000 c/h  — acts as AccountManager
      Kai   DIRECTOR cost 9000 c/h  — acts as CreativeLead on deliverables
      Mia   SENIOR   cost 6000 c/h  — acts as MediaBuyer
    """
    if clock is not None:
        set_clock(clock, api=api)

    admin = make_agency_admin_headers()

    client = register_client(api=api)
    rate_card = get_success_data(api.create_rate_card(create_rate_card_payload(), admin))

    dana = register_staff(
        api=api, full_name="Dana Lee", grade="SENIOR", cost_rate_cents_per_hour=6_000
    )
    ravi = register_staff(
        api=api, full_name="Ravi Iyer", grade="JUNIOR", cost_rate_cents_per_hour=3_000
    )
    kai = register_staff(
        api=api, full_name="Kai Osei", grade="DIRECTOR", cost_rate_cents_per_hour=9_000
    )
    mia = register_staff(
        api=api, full_name="Mia Chen", grade="SENIOR", cost_rate_cents_per_hour=6_000
    )

    am_headers = make_account_manager_headers(ravi["id"])
    dana_headers = make_creative_lead_headers(dana["id"])
    kai_headers = make_creative_lead_headers(kai["id"])
    mia_headers = make_media_buyer_headers(mia["id"])
    reviewer_headers = make_client_reviewer_headers(client["id"])

    retainer = None
    if retainer_funding is not None:
        retainer = get_success_data(
            api.create_retainer(
                create_retainer_payload(client["id"], initial_funding_cents=retainer_funding),
                admin,
            )
        )

    sow = get_success_data(
        api.create_sow(
            create_sow_payload(
                client["id"],
                rate_card["id"],
                title=sow_title,
                labor_cap_cents=labor_cap_cents,
                markup_pct=markup_pct,
                effective_start=effective_start,
                effective_end=effective_end,
            ),
            am_headers,
        )
    )
    if countersign:
        sow = get_success_data(api.countersign_sow(sow["id"], reviewer_headers))

    campaign = get_success_data(
        api.create_campaign(create_campaign_payload(client["id"], sow["id"]), am_headers)
    )
    if launch:
        campaign = get_success_data(api.launch_campaign(campaign["id"], am_headers))

    return {
        "api": api,
        "client": client,
        "client_id": client["id"],
        "rate_card": rate_card,
        "rate_card_id": rate_card["id"],
        "dana": dana,
        "dana_id": dana["id"],
        "ravi": ravi,
        "ravi_id": ravi["id"],
        "kai": kai,
        "kai_id": kai["id"],
        "mia": mia,
        "mia_id": mia["id"],
        "retainer": retainer,
        "retainer_id": retainer["id"] if retainer else None,
        "sow": sow,
        "sow_id": sow["id"],
        "campaign": campaign,
        "campaign_id": campaign["id"],
        "admin_headers": admin,
        "am_headers": am_headers,
        "dana_headers": dana_headers,
        "kai_headers": kai_headers,
        "mia_headers": mia_headers,
        "reviewer_headers": reviewer_headers,
    }


def add_campaign(base: dict, name="Autumn Push", brief_summary="Drive autumn consideration",
                 objective="CONSIDERATION", launch=True) -> dict:
    """A second campaign for the same advertiser under the same SOW."""
    api = base["api"]
    campaign = get_success_data(
        api.create_campaign(
            create_campaign_payload(
                base["client_id"],
                base["sow_id"],
                name=name,
                brief_summary=brief_summary,
                objective=objective,
            ),
            base["am_headers"],
        )
    )
    if launch:
        campaign = get_success_data(api.launch_campaign(campaign["id"], base["am_headers"]))
    return campaign


# --------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# --------------------------------------------------------------------------


def log_time(base: dict, staff_key: str, started_at: str, ended_at: str, billable=True,
             campaign_id=None) -> dict:
    """Log a worked interval as the named staff member (only they may log their own hours)."""
    api = base["api"]
    headers = {
        "dana": base["dana_headers"],
        "kai": base["kai_headers"],
        "mia": base["mia_headers"],
        "ravi": base["am_headers"],
    }[staff_key]
    payload = create_time_entry_payload(
        campaign_id or base["campaign_id"],
        base[f"{staff_key}_id"],
        started_at,
        ended_at,
        billable=billable,
    )
    return get_success_data(api.create_time_entry(payload, headers))


def approve_time(base: dict, time_entry_id: str, approver_headers=None) -> dict:
    """Approve someone else's entry — this is where the overtime split is priced."""
    api = base["api"]
    return get_success_data(
        api.approve_time_entry(time_entry_id, approver_headers or base["am_headers"])
    )


def log_and_approve_time(base: dict, staff_key: str, started_at: str, ended_at: str,
                         billable=True, campaign_id=None) -> dict:
    entry = log_time(base, staff_key, started_at, ended_at, billable=billable,
                     campaign_id=campaign_id)
    return approve_time(base, entry["id"])


def record_vendor_cost(base: dict, campaign_id=None, **overrides) -> dict:
    api = base["api"]
    payload = create_vendor_cost_payload(campaign_id or base["campaign_id"], **overrides)
    return get_success_data(api.create_vendor_cost(payload, base["am_headers"]))


def record_and_approve_vendor_cost(base: dict, actual_amount_cents: int, campaign_id=None,
                                   **overrides) -> dict:
    cost = record_vendor_cost(base, campaign_id=campaign_id, **overrides)
    return get_success_data(
        base["api"].approve_vendor_cost(
            cost["id"], {"actual_amount_cents": actual_amount_cents}, base["am_headers"]
        )
    )


def open_deliverable(base: dict, campaign_id=None, submit=False, **overrides) -> dict:
    api = base["api"]
    deliverable = get_success_data(
        api.create_deliverable(
            create_deliverable_payload(campaign_id or base["campaign_id"], **overrides),
            base["kai_headers"],
        )
    )
    if submit:
        deliverable = get_success_data(
            api.submit_deliverable(deliverable["id"], base["kai_headers"])
        )
    return deliverable


# --------------------------------------------------------------------------
# Tier 3 — media plan / insertion order lifecycle
# --------------------------------------------------------------------------


def setup_media_plan(base: dict, approve=False, campaign_id=None, **overrides) -> dict:
    api = base["api"]
    plan = get_success_data(
        api.create_media_plan(
            create_media_plan_payload(campaign_id or base["campaign_id"], **overrides),
            base["mia_headers"],
        )
    )
    if approve:
        plan = get_success_data(api.approve_media_plan(plan["id"], base["reviewer_headers"]))
    return plan


def reserve_insertion_order(base: dict, media_plan_id: str, placement_id: str,
                            expected_version=None, **overrides) -> dict:
    """Reserve inventory, resolving the plan's current version for the stale-version token."""
    api = base["api"]
    if expected_version is None:
        expected_version = media_plan_version(media_plan_id, base["mia_headers"], api=api)
    payload = create_insertion_order_payload(
        media_plan_id, placement_id, expected_version, **overrides
    )
    return get_success_data(api.create_insertion_order(payload, base["mia_headers"]))


def place_insertion_order(base: dict, insertion_order_id: str) -> dict:
    return get_success_data(
        base["api"].place_insertion_order(insertion_order_id, base["mia_headers"])
    )


def deliver_insertion_order(base: dict, insertion_order_id: str, delivered_impressions: int,
                            delivered_spend_cents: int) -> dict:
    return get_success_data(
        base["api"].deliver_insertion_order(
            insertion_order_id,
            {
                "delivered_impressions": delivered_impressions,
                "delivered_spend_cents": delivered_spend_cents,
            },
            base["mia_headers"],
        )
    )


# --------------------------------------------------------------------------
# Tier 4/5 — invoice assembly, issue and the credit-hold cascade
# --------------------------------------------------------------------------


def assemble_invoice(base: dict, billing_mode="FINAL", campaign_id=None, retainer_id=None,
                     **overrides) -> dict:
    api = base["api"]
    payload = create_invoice_payload(
        base["client_id"],
        campaign_id or base["campaign_id"],
        retainer_id or base["retainer_id"],
        billing_mode=billing_mode,
        **overrides,
    )
    return get_success_data(api.create_invoice(payload, base["am_headers"]))


def issue_invoice(base: dict, invoice_id: str, retainer_id=None) -> dict:
    """Issue with a freshly-read expected_retainer_version (PRD §2.7)."""
    api = base["api"]
    version = retainer_version(retainer_id or base["retainer_id"], api=api)
    return get_success_data(
        api.issue_invoice(
            invoice_id, {"expected_retainer_version": version}, base["admin_headers"]
        )
    )


def setup_approved_senior_hour(base: dict) -> dict:
    """One APPROVED 60-minute SENIOR entry on 2026-06-02: 20000 cents billable, 6000 internal."""
    return log_and_approve_time(
        base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", billable=True
    )


def setup_issued_final_invoice(retainer_funding=5_000_000, api=api_client, **base_overrides) -> dict:
    """Base scenario + one APPROVED 60-min SENIOR entry + an ISSUED FINAL invoice of 20600.

    The invoice's total is 20000 labour + 600 admin fee = 20600 cents. Choose
    retainer_funding to control the drawdown:
      20600  -> retainer lands on exactly 0 and the whole credit-hold cascade fires
      10000  -> retainer_applied 10000, cash_due 10600, retainer still depleted to 0
      200000 -> retainer stays ACTIVE with a balance of 179400
    """
    base = setup_base(api=api, retainer_funding=retainer_funding, **base_overrides)
    time_entry = setup_approved_senior_hour(base)
    invoice = assemble_invoice(base, billing_mode="FINAL")
    invoice = issue_invoice(base, invoice["id"])
    base["time_entry"] = time_entry
    base["invoice"] = invoice
    base["invoice_id"] = invoice["id"]
    return base


def setup_on_hold_campaign(api=api_client, **base_overrides) -> dict:
    """Drive the four-hop cascade: retainer 20600 fully drawn -> DEPLETED -> CREDIT_HOLD -> ON_HOLD."""
    return setup_issued_final_invoice(retainer_funding=20_600, api=api, **base_overrides)
