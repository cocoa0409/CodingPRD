"""
Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch against a freshly restarted server
using only PRD-declared endpoints, and use get_success_data() (lenient) so a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure deep in a test.

Identity threading: AgencyCoordinator and Donor are entity-backed roles, so
ownership-gated calls always use make_*_headers(entity_id) with the actual row
id — never the shared TEST_USERS fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CAMPAIGN_DEFAULTS, CLOCK
from .factories import (
    create_agency_payload, create_campaign_payload, create_child_payload,
    create_donor_payload, create_family_payload, create_gift_payload,
    create_wish_item_payload, create_distribution_event_payload,
    create_distribution_slot_payload, create_adoption_payload,
)
from .test_users import (
    TEST_USERS, make_agency_coordinator_headers, make_donor_headers,
    make_platform_admin_headers, make_caseworker_headers, make_volunteer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
CW1 = TEST_USERS["caseworker_headers"]
CW2 = TEST_USERS["caseworker2_headers"]
CW3 = TEST_USERS["caseworker3_headers"]
VOL1 = TEST_USERS["volunteer_headers"]
VOL2 = TEST_USERS["volunteer2_headers"]


def _setup_fail(what: str, res):
    raise AssertionError(
        f"Setup failed at {what}: HTTP {res.status_code} body={res.text[:400]}")


def _ok(res, what: str):
    if res.status_code >= 400:
        _setup_fail(what, res)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 0: clock + campaign primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Drive the server's logical clock (PRD §2.5 test-driving capability)."""
    return _ok(api_client.set_clock(to_iso8601, ADMIN), f"set_clock({to_iso8601})")


def reset_clock():
    return set_clock(CLOCK["SERVER_START"])


def create_campaign(season_year: int = None, **overrides):
    """Create a campaign in DRAFT. season_year is unique, so each call needs a
    fresh year; when omitted a counter-based year is used."""
    if season_year is None:
        create_campaign._year = getattr(create_campaign, "_year", 2026) + 1
        season_year = create_campaign._year
    payload = create_campaign_payload(season_year=season_year, **overrides)
    return _ok(api_client.create_campaign(payload, ADMIN), "create_campaign")


def create_agency(**overrides):
    return _ok(api_client.create_agency(create_agency_payload(**overrides), ADMIN),
               "create_agency")


def open_campaign_intake(campaign_id: str):
    """Move the logical clock inside the intake window and open intake."""
    set_clock(CLOCK["DURING_INTAKE"])
    return _ok(api_client.open_intake(campaign_id, ADMIN), "open_intake")


def setup_campaign_intake_open(**campaign_overrides):
    """Campaign in INTAKE_OPEN + one ACTIVE agency. Returns (campaign, agency)."""
    reset_clock()
    campaign = create_campaign(**campaign_overrides)
    agency = create_agency()
    campaign = open_campaign_intake(campaign["id"])
    return campaign, agency


# ---------------------------------------------------------------------------
# Tier 1: family / child / wish-item primitives (agency-identity threaded)
# ---------------------------------------------------------------------------

def create_family(agency: dict, campaign: dict, **overrides):
    headers = make_agency_coordinator_headers(agency["id"])
    payload = create_family_payload(agency["id"], campaign["id"], **overrides)
    return _ok(api_client.create_family(payload, headers), "create_family")


def add_child(family_id: str, agency_id: str, **overrides):
    headers = make_agency_coordinator_headers(agency_id)
    return _ok(api_client.create_child(family_id, create_child_payload(**overrides),
                                       headers), "add_child")


def add_wish_item(child_id: str, agency_id: str, **overrides):
    headers = make_agency_coordinator_headers(agency_id)
    return _ok(api_client.create_wish_item(child_id,
                                           create_wish_item_payload(**overrides),
                                           headers), "add_wish_item")


def approve_wish_item(wish_item_id: str, headers=None):
    return _ok(api_client.approve_wish_item(wish_item_id, headers or CW1),
               "approve_wish_item")


def begin_review(family_id: str, headers=None):
    return _ok(api_client.begin_review(family_id, headers or CW1), "begin_review")


def verify_family(family_id: str, begin_headers=None, verify_headers=None,
                  note: str = "ok"):
    """REFERRED -> UNDER_REVIEW -> VERIFIED, honoring segregation of duties:
    the verify actor differs from the begin-review actor (PRD §3.3)."""
    begin_review(family_id, headers=begin_headers or CW1)
    return _ok(api_client.verify_family(family_id, verify_headers or CW2,
                                        verification_note=note), "verify_family")


def get_family(family_id: str):
    return _ok(api_client.get_family(family_id, ADMIN), "get_family")


def get_child(child_id: str):
    return _ok(api_client.get_child(child_id, ADMIN), "get_child")


def get_wish_item(wish_item_id: str):
    return _ok(api_client.get_wish_item(wish_item_id, ADMIN), "get_wish_item")


# ---------------------------------------------------------------------------
# Tier 2: donor + adoption
# ---------------------------------------------------------------------------

def create_donor(**overrides):
    return _ok(api_client.create_donor(create_donor_payload(**overrides), ADMIN),
               "create_donor")


def pledge_adoption(campaign: dict, family_id: str, donor: dict,
                    scope: str = "WHOLE_FAMILY", child_ids=None):
    """Pledge an adoption with a fresh family version for the OCC field."""
    fam = get_family(family_id)
    payload = create_adoption_payload(
        campaign["id"], donor["id"], family_id, fam["version"],
        scope=scope, **({"child_ids": child_ids} if child_ids is not None else {}))
    return _ok(api_client.create_adoption(payload, make_donor_headers(donor["id"])),
               "pledge_adoption")


def confirm_adoption(adoption_id: str, donor_id: str):
    return _ok(api_client.confirm_adoption(adoption_id,
                                           make_donor_headers(donor_id)),
               "confirm_adoption")


def pledge_and_confirm(campaign: dict, family_id: str, donor: dict,
                       scope: str = "WHOLE_FAMILY", child_ids=None):
    adoption = pledge_adoption(campaign, family_id, donor, scope=scope,
                               child_ids=child_ids)
    adoption = confirm_adoption(adoption["id"], donor["id"])
    return adoption


def get_adoption(adoption_id: str):
    return _ok(api_client.get_adoption(adoption_id, ADMIN), "get_adoption")


# ---------------------------------------------------------------------------
# Tier 3: composite verified/matched scenarios
# ---------------------------------------------------------------------------

def setup_verified_family(children_specs=None, wish_specs=None,
                          approve_wishes=False, **campaign_overrides):
    """
    Campaign INTAKE_OPEN + agency + one VERIFIED family with children.

    children_specs: list of child payload overrides (default: one child).
    wish_specs: dict mapping child index -> list of wish-item overrides.
    approve_wishes: approve each created wish item while the child is still
    REGISTERED (PRD §3.4 allows approve from REGISTERED or WISH_LOCKED).

    Returns dict(campaign, agency, family, children, wish_items).
    """
    campaign, agency = setup_campaign_intake_open(**campaign_overrides)
    family = create_family(agency, campaign)
    children_specs = children_specs if children_specs is not None else [{}]
    children = [add_child(family["id"], agency["id"], **spec)
                for spec in children_specs]
    wish_items = []
    for idx, specs in (wish_specs or {}).items():
        for spec in specs:
            item = add_wish_item(children[idx]["id"], agency["id"], **spec)
            if approve_wishes:
                item = approve_wish_item(item["id"])
            wish_items.append(item)
    family = verify_family(family["id"])
    return {"campaign": campaign, "agency": agency, "family": family,
            "children": children, "wish_items": wish_items}


def setup_matched_family(children_specs=None, wish_specs=None,
                         approve_wishes=True, donor_overrides=None,
                         **campaign_overrides):
    """
    Verified family + donor + CONFIRMED whole-family adoption (family MATCHED).

    Returns dict(campaign, agency, family, children, wish_items, donor, adoption).
    Wish items are approved before verification so the confirm cascade can
    commit them (PRD §3.6).
    """
    ctx = setup_verified_family(children_specs=children_specs,
                                wish_specs=wish_specs or {0: [{}]},
                                approve_wishes=approve_wishes,
                                **campaign_overrides)
    donor = create_donor(**(donor_overrides or {}))
    adoption = pledge_and_confirm(ctx["campaign"], ctx["family"]["id"], donor)
    ctx["donor"] = donor
    ctx["adoption"] = adoption
    ctx["family"] = get_family(ctx["family"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: campaign advancement + backfill
# ---------------------------------------------------------------------------

def advance_past_return_deadline(campaign_id: str):
    """
    Move the logical clock past gift_return_deadline, close intake, and advance
    MATCHING -> DISTRIBUTION_PREP with a fresh OCC version (PRD §3.1).
    Returns the campaign after the advance.
    """
    set_clock(CLOCK["AFTER_RETURN_DEADLINE"])
    _ok(api_client.close_intake(campaign_id, ADMIN), "close_intake")
    campaign = _ok(api_client.get_campaign(campaign_id, ADMIN), "get_campaign")
    return _ok(api_client.advance_campaign(campaign_id, campaign["version"], ADMIN),
               "advance_campaign")


def setup_backfill_eligible(num_families: int = 1, backfill_budget_cents: int = 100000,
                            wish_price_cents: int = 3000):
    """
    N matched families, each with one child, whose confirmed adoptions expire
    when the campaign advances past the gift-return deadline: children land in
    BACKFILL_ELIGIBLE while families remain MATCHED (PRD §3.1, §3.6, §3.10).

    Returns dict(campaign, agency, donors, families, children, wish_items,
                 adoptions).
    """
    campaign, agency = setup_campaign_intake_open(
        backfill_budget_cents=backfill_budget_cents)
    families, children, wish_items, adoptions, donors = [], [], [], [], []
    for _ in range(num_families):
        family = create_family(agency, campaign)
        child = add_child(family["id"], agency["id"])
        item = add_wish_item(child["id"], agency["id"],
                             estimated_price_cents=wish_price_cents)
        # Approve while the child is REGISTERED (PRD §3.4) so the selector's
        # score term ("smallest priority_rank among their APPROVED wish
        # items", PRD §3.8) and the purchase's wish_item_id are well defined.
        item = approve_wish_item(item["id"])
        family = verify_family(family["id"])
        donor = create_donor()
        adoption = pledge_and_confirm(campaign, family["id"], donor)
        families.append(get_family(family["id"]))
        children.append(child)
        wish_items.append(item)
        adoptions.append(adoption)
        donors.append(donor)
    campaign = advance_past_return_deadline(campaign["id"])
    return {"campaign": campaign, "agency": agency, "families": families,
            "children": children, "wish_items": wish_items,
            "adoptions": adoptions, "donors": donors}


def run_backfill_select(campaign_id: str, limit: int = 10, headers=None):
    """Run the backfill child selector. Returns the list of ORDERED purchases.
    The caller should use a dedicated admin identity if segregation-of-duties
    against a later mark-purchased matters (PRD §3.8)."""
    data = _ok(api_client.backfill_select(campaign_id, limit, headers or ADMIN),
               "backfill_select")
    assert isinstance(data, list), "selector returns an array of purchases"
    return data


# ---------------------------------------------------------------------------
# Tier 5: distribution events + slots
# ---------------------------------------------------------------------------

def create_event(campaign_id: str, **overrides):
    return _ok(api_client.create_distribution_event(
        create_distribution_event_payload(campaign_id, **overrides), ADMIN),
        "create_distribution_event")


def open_event_slots(event_id: str):
    return _ok(api_client.open_slots(event_id, ADMIN), "open_slots")


def get_event(event_id: str):
    return _ok(api_client.get_distribution_event(event_id, ADMIN), "get_event")


def book_slot(event_id: str, family_id: str, window_start: str, window_end: str,
              lane: str = "A", headers=None):
    """Book a slot with a freshly read event version for the OCC field."""
    event = get_event(event_id)
    payload = create_distribution_slot_payload(
        event_id, family_id, event["version"],
        window_start=window_start, window_end=window_end, lane=lane)
    return _ok(api_client.create_distribution_slot(payload, headers or ADMIN),
               "book_slot")


def setup_event_open_for_slots(num_families: int = 1, **campaign_overrides):
    """
    N MATCHED families + campaign in DISTRIBUTION_PREP + one event in
    OPEN_FOR_SLOTS. Returns dict(campaign, agency, event, families, children,
    donors, adoptions).
    """
    ctx = setup_backfill_eligible(num_families=num_families,
                                  **campaign_overrides)
    event = create_event(ctx["campaign"]["id"])
    event = open_event_slots(event["id"])
    ctx["event"] = event
    return ctx


def setup_gift_in_state(gift_target_state: str = "COMMITTED",
                        with_wish_item: bool = True,
                        declared_value_cents: int = 3000):
    """
    Matched family + one gift in the requested state:
    COMMITTED (default), IN_TRANSIT (shipped), RECEIVED (received before the
    return deadline), SORTED / STAGED (campaign advanced + event SORTING).

    Returns dict(campaign, agency, family, child, wish_item, donor, adoption,
                 gift, event?, slot?).
    """
    wish_specs = {0: [{}]} if with_wish_item else None
    ctx = setup_matched_family(wish_specs=wish_specs, approve_wishes=True)
    child = ctx["children"][0]
    wish_item = ctx["wish_items"][0] if ctx["wish_items"] else None
    donor_headers = make_donor_headers(ctx["donor"]["id"])
    gift_payload = create_gift_payload(ctx["adoption"]["id"], child["id"],
                                       declared_value_cents=declared_value_cents)
    if wish_item is not None:
        gift_payload["wish_item_id"] = wish_item["id"]
    gift = _ok(api_client.create_gift(gift_payload, donor_headers), "create_gift")
    ctx["child"] = child
    ctx["wish_item"] = wish_item
    ctx["gift"] = gift

    if gift_target_state == "COMMITTED":
        return ctx
    if gift_target_state in ("IN_TRANSIT", "RECEIVED", "SORTED", "STAGED"):
        gift = _ok(api_client.ship_gift(gift["id"], donor_headers), "ship_gift")
        ctx["gift"] = gift
    if gift_target_state == "IN_TRANSIT":
        return ctx
    # receive must happen at or before the snapshotted return_deadline
    gift = _ok(api_client.receive_gift(gift["id"], VOL1), "receive_gift")
    ctx["gift"] = gift
    if gift_target_state == "RECEIVED":
        return ctx
    # SORTED requires campaign in DISTRIBUTION_PREP/DISTRIBUTION and an event
    # in SORTING or later (PRD §3.7)
    campaign = advance_past_return_deadline(ctx["campaign"]["id"])
    event = create_event(campaign["id"])
    open_event_slots(event["id"])
    slot = book_slot(event["id"], ctx["family"]["id"],
                     "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z", lane="A")
    _ok(api_client.begin_sorting(event["id"], ADMIN), "begin_sorting")
    gift = _ok(api_client.sort_gift(gift["id"], VOL1), "sort_gift")
    ctx.update({"campaign": campaign, "event": get_event(event["id"]),
                "slot": slot, "gift": gift})
    if gift_target_state == "SORTED":
        return ctx
    # STAGED
    gift = _ok(api_client.stage_gift(gift["id"], slot["id"], VOL1), "stage_gift")
    ctx["gift"] = gift
    return ctx
