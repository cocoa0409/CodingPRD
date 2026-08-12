"""Composite setup helpers. Multi-step flows used across the test suite.

Every fixture uses get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_property_payload,
    create_appraiser_payload,
    create_broker_payload,
    create_appraisal_payload,
    create_listing_agreement_payload,
    create_offer_payload,
    create_carrying_cost_payload,
    create_issue_payload,
    create_write_down_payload,
    create_extension_request_payload,
    create_approval_tier_payload,
    create_closing_statement_payload,
)
from .test_users import (
    TEST_USERS,
    make_appraiser_headers,
)


ADMIN = TEST_USERS["oreo_admin_headers"]
PM = TEST_USERS["property_manager_headers"]
SPEC = TEST_USERS["oreo_specialist_headers"]
CHIEF = TEST_USERS["chief_appraiser_headers"]
CO = TEST_USERS["credit_officer_headers"]
COMMITTEE = TEST_USERS["oreo_committee_headers"]
COMP = TEST_USERS["compliance_officer_headers"]


def _ok(response, label: str):
    if response.status_code >= 400:
        raise AssertionError(
            f"Setup failed: {label} -> HTTP {response.status_code}: {response.text}"
        )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 1: state progression / registration primitives
# ---------------------------------------------------------------------------


def create_property(**overrides):
    """Create one property via the OREOAdmin intake endpoint."""
    return _ok(
        api_client.create_property(create_property_payload(**overrides), ADMIN),
        "create_property",
    )


def set_clock(to_iso8601: str):
    """Advance the logical clock (runs the sweeps per PRD §2.9)."""
    return api_client.set_clock(to_iso8601, ADMIN)


def create_appraiser(**overrides):
    return _ok(
        api_client.create_appraiser(create_appraiser_payload(**overrides), ADMIN),
        "create_appraiser",
    )


def create_broker(**overrides):
    return _ok(
        api_client.create_broker(create_broker_payload(**overrides), ADMIN),
        "create_broker",
    )


def create_draft_appraisal(property_id, appraiser_id, property_version, **overrides):
    """Create a DRAFT appraisal owned by appraiser_id (entity-backed)."""
    payload = create_appraisal_payload(
        property_id=property_id,
        appraiser_id=appraiser_id,
        expected_property_version=property_version,
        **overrides,
    )
    return _ok(
        api_client.create_appraisal(payload, make_appraiser_headers(appraiser_id)),
        "create_appraisal",
    )


def submit_appraisal(appraisal_id, appraiser_id):
    return _ok(
        api_client.submit_appraisal(
            appraisal_id, make_appraiser_headers(appraiser_id)
        ),
        "submit_appraisal",
    )


def certify_appraisal(appraisal_id, chief_user_id: str = "chief-appraiser-1"):
    from .test_users import make_chief_appraiser_headers

    return _ok(
        api_client.certify_appraisal(
            appraisal_id, make_chief_appraiser_headers(chief_user_id)
        ),
        "certify_appraisal",
    )


def create_listing_agreement(property_id, broker_id, **overrides):
    payload = create_listing_agreement_payload(
        property_id=property_id, broker_id=broker_id, **overrides
    )
    return _ok(
        api_client.create_listing_agreement(payload, PM),
        "create_listing_agreement",
    )


def activate_listing(listing_id):
    return _ok(api_client.activate_listing(listing_id, SPEC), "activate_listing")


def create_offer(property_id, property_version, **overrides):
    payload = create_offer_payload(
        property_id=property_id,
        expected_property_version=property_version,
        **overrides,
    )
    return _ok(api_client.create_offer(payload, SPEC), "create_offer")


def submit_offer_review(offer_id):
    return _ok(api_client.submit_offer_review(offer_id, SPEC), "submit_offer_review")


def get_property(property_id):
    return _ok(api_client.get_property(property_id, ADMIN), "get_property")


def get_property_summary(property_id):
    return _ok(
        api_client.get_property_summary(property_id, ADMIN), "get_property_summary"
    )


def get_offer(offer_id):
    return _ok(api_client.get_offer(offer_id, ADMIN), "get_offer")


def get_listing(listing_id):
    return _ok(api_client.get_listing_agreement(listing_id, ADMIN), "get_listing")


def list_write_downs(property_id):
    data, _meta = _paginated(
        api_client.list_write_downs(ADMIN, params={"property_id": property_id}),
        "list_write_downs",
    )
    return data


def list_ledger_entries(property_id, **filters):
    params = {"property_id": property_id}
    params.update({k: v for k, v in filters.items() if v is not None})
    data, _meta = _paginated(
        api_client.list_ledger_entries(ADMIN, params=params), "list_ledger_entries"
    )
    return data


def _paginated(response, label: str):
    if response.status_code >= 400:
        raise AssertionError(
            f"Setup failed: {label} -> HTTP {response.status_code}: {response.text}"
        )
    body = response.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — property + certified appraisal
# ---------------------------------------------------------------------------


def create_property_with_certified_appraisal(
    appraised_value: float = 400000.00,
    effective_date: str = "2026-06-01",
    clock_iso: str = "2026-06-01T00:00:00Z",
    property_overrides: dict | None = None,
):
    """Property created, clock advanced, appraiser registered, appraisal
    created/submitted/certified. Returns (property, appraiser, appraisal)."""
    prop = create_property(**(property_overrides or {}))
    set_clock(clock_iso)
    appraiser = create_appraiser()
    appraisal = create_draft_appraisal(
        prop["id"], appraiser["id"], prop["version"], appraised_value=appraised_value,
        effective_date=effective_date,
    )
    submit_appraisal(appraisal["id"], appraiser["id"])
    certify_appraisal(appraisal["id"])
    refreshed = get_property(prop["id"])
    return refreshed, appraiser, appraisal


# ---------------------------------------------------------------------------
# Tier 3: marketed property (certified appraisal + ACTIVE listing)
# ---------------------------------------------------------------------------


def create_marketed_property(
    appraised_value: float = 400000.00,
    listing_price: float = 450000.00,
    listing_start: str = "2026-06-05",
    listing_end: str = "2026-12-05",
    property_overrides: dict | None = None,
    clock_iso: str = "2026-06-01T00:00:00Z",
):
    """Full marketing setup: property + certified appraisal + ACTIVE listing.
    Returns dict with property, appraiser, appraisal, broker, listing.
    Property returned is refreshed after listing activation."""
    prop, appraiser, appraisal = create_property_with_certified_appraisal(
        appraised_value=appraised_value,
        property_overrides=property_overrides,
        clock_iso=clock_iso,
    )
    broker = create_broker()
    listing = create_listing_agreement(
        prop["id"],
        broker["id"],
        start_date=listing_start,
        end_date=listing_end,
        listing_price=listing_price,
    )
    activate_listing(listing["id"])
    refreshed = get_property(prop["id"])
    return {
        "property": refreshed,
        "appraiser": appraiser,
        "appraisal": appraisal,
        "broker": broker,
        "listing": get_listing(listing["id"]),
    }


def setup_approval_tiers():
    """Standard 3-tier configuration used across authority tests.
    Idempotent: returns the existing standard tiers if already configured.

    T1 [0, 250000)        -> OREOSpecialist (rank 1)
    T2 [250000, 750000)   -> CreditOfficer (rank 2)
    T3 [750000, unbounded)-> OREOCommittee (rank 3)
    """
    data, _meta = _paginated(
        api_client.list_approval_tiers(ADMIN), "list approval tiers"
    )
    existing = {t["name"]: t for t in data}
    if {"T1", "T2", "T3"}.issubset(existing.keys()):
        return {"T1": existing["T1"], "T2": existing["T2"], "T3": existing["T3"]}
    t1 = _ok(
        api_client.create_approval_tier(
            create_approval_tier_payload(
                name="T1",
                min_net_proceeds=0.00,
                max_net_proceeds=250000.00,
                required_role="OREOSpecialist",
            ),
            ADMIN,
        ),
        "create tier T1",
    )
    t2 = _ok(
        api_client.create_approval_tier(
            create_approval_tier_payload(
                name="T2",
                min_net_proceeds=250000.00,
                max_net_proceeds=750000.00,
                required_role="CreditOfficer",
            ),
            ADMIN,
        ),
        "create tier T2",
    )
    t3 = _ok(
        api_client.create_approval_tier(
            create_approval_tier_payload(
                name="T3",
                min_net_proceeds=750000.00,
                required_role="OREOCommittee",
                max_net_proceeds=None,
            ),
            ADMIN,
        ),
        "create tier T3",
    )
    return {"T1": t1, "T2": t2, "T3": t3}


# ---------------------------------------------------------------------------
# Tier 4: offer pipeline — marketed property + offer UNDER_REVIEW / ACCEPTED
# ---------------------------------------------------------------------------


def create_offer_under_review(
    property_id,
    property_version,
    offer_price=450000.00,
    listing_agreement_id=None,
    financing_type="CASH",
    down_payment=None,
    buyer_name="Buyer One",
    earnest_money=None,
):
    """Create an offer and move it to UNDER_REVIEW. Returns refreshed offer."""
    payload_extra = {}
    if listing_agreement_id is not None:
        payload_extra["listing_agreement_id"] = listing_agreement_id
    if down_payment is not None:
        payload_extra["down_payment"] = down_payment
    if earnest_money is not None:
        payload_extra["earnest_money"] = earnest_money
    offer = create_offer(
        property_id,
        property_version,
        offer_price=offer_price,
        financing_type=financing_type,
        buyer_name=buyer_name,
        **payload_extra,
    )
    submit_offer_review(offer["id"])
    return get_offer(offer["id"])


def setup_property_with_accepted_offer(
    offer_price=450000.00,
    financing_type="CASH",
    down_payment=None,
    accept_as: str = "credit_officer",
    property_overrides: dict | None = None,
    appraised_value: float = 400000.00,
    listing_price: float = 450000.00,
    listing_end: str = "2026-12-05",
    earnest_money=None,
):
    """Full pipeline through offer ACCEPTED. Property is UNDER_CONTRACT.
    Returns dict with property, appraiser, broker, listing, offer."""
    setup_approval_tiers()
    ctx = create_marketed_property(
        appraised_value=appraised_value,
        listing_price=listing_price,
        listing_end=listing_end,
        property_overrides=property_overrides,
    )
    offer = create_offer_under_review(
        ctx["property"]["id"],
        ctx["property"]["version"],
        offer_price=offer_price,
        listing_agreement_id=ctx["listing"]["id"],
        financing_type=financing_type,
        down_payment=down_payment,
        earnest_money=earnest_money,
    )
    headers = {"credit_officer": CO, "committee": COMMITTEE, "specialist": SPEC}[
        accept_as
    ]
    _ok(api_client.accept_offer(offer["id"], headers), "accept_offer")
    offer = get_offer(offer["id"])
    prop = get_property(ctx["property"]["id"])
    return {**ctx, "offer": offer, "property": prop}


def setup_settled_sale(
    offer_price=450000.00,
    financing_type="CASH",
    down_payment=None,
    accept_as: str = "credit_officer",
    property_overrides: dict | None = None,
    appraised_value: float = 400000.00,
    listing_price: float = 450000.00,
    closing_date: str = "2026-08-01",
    earnest_money=None,
):
    """Full pipeline through closing SETTLED. Property is DISPOSED; offer CLOSED."""
    ctx = setup_property_with_accepted_offer(
        offer_price=offer_price,
        financing_type=financing_type,
        down_payment=down_payment,
        accept_as=accept_as,
        property_overrides=property_overrides,
        appraised_value=appraised_value,
        listing_price=listing_price,
        earnest_money=earnest_money,
    )
    closing = _ok(
        api_client.create_closing_statement(
            create_closing_statement_payload(
                offer_id=ctx["offer"]["id"], closing_date=closing_date
            ),
            SPEC,
        ),
        "create_closing_statement",
    )
    _ok(api_client.settle_closing(closing["id"], CO), "settle_closing")
    closing = _ok(
        api_client.get_closing_statement(closing["id"], ADMIN), "get_closing"
    )
    prop = get_property(ctx["property"]["id"])
    return {**ctx, "closing": closing, "property": prop}
