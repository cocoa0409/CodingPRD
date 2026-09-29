"""Composite setup helpers.

Every helper drives the public API only - no direct database access - and every
helper returns plain dicts of the created resources so a test can read the
version tokens and identifiers it needs. Helpers are layered: tier 1 creates one
resource, tier 2 combines them into the world every workflow needs, tiers 3-5
walk the classification, measurement and money lifecycles.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import CLOCK_DEFAULT_NOW
from .test_users import (
    ANALYST_AUTHOR_USER_ID,
    ANALYST_REVIEWER_USER_ID,
    AUDITOR_AUTHOR_USER_ID,
    AUDITOR_CONCLUDER_USER_ID,
    OFFICER_USER_ID,
    TEST_USERS,
    make_advertiser_headers,
    make_analyst_headers,
    make_auditor_headers,
    make_officer_headers,
    make_publisher_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["officer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# tier 0: the logical clock
# ---------------------------------------------------------------------------
def advance_clock(client, to_iso8601: str = CLOCK_DEFAULT_NOW) -> str:
    """Move the logical clock and return the instant it now reports."""
    response = client.set_clock(factories.set_clock_payload(to_iso8601), ADMIN)
    return get_success_data(response)["current_utc"]


# ---------------------------------------------------------------------------
# tier 1: single resources
# ---------------------------------------------------------------------------
def setup_advertiser(client, **overrides) -> dict:
    response = client.create_advertiser(
        factories.create_advertiser_payload(**overrides), ADMIN
    )
    return get_success_data(response)


def setup_publisher(client, **overrides) -> dict:
    response = client.create_publisher(
        factories.create_publisher_payload(**overrides), ADMIN
    )
    return get_success_data(response)


def setup_methodology_version(
    client, standard_family: str = "VIEWABILITY", author_user_id=None, **overrides
) -> dict:
    """A PROVISIONAL version, stamped authored_by_user_id from the author."""
    headers = make_auditor_headers(author_user_id or AUDITOR_AUTHOR_USER_ID)
    response = client.create_methodology_version(
        factories.create_methodology_version_payload(
            standard_family=standard_family, **overrides
        ),
        headers,
    )
    return get_success_data(response)


def setup_accredited_methodology_version(
    client, standard_family: str = "VIEWABILITY", audit_finding_rate: float = 0.01,
    **overrides,
) -> dict:
    """Author as auditor-1, then pass the audit as auditor-2 (segregation of duties)."""
    version = setup_methodology_version(
        client, standard_family=standard_family,
        author_user_id=AUDITOR_AUTHOR_USER_ID, **overrides,
    )
    response = client.conclude_audit(
        version["id"],
        factories.conclude_audit_payload(
            outcome="PASSED", audit_finding_rate=audit_finding_rate
        ),
        make_auditor_headers(AUDITOR_CONCLUDER_USER_ID),
    )
    return get_success_data(response)


def suspend_methodology_version(
    client, version_id: str, audit_finding_rate: float = 0.30
) -> dict:
    """Conclude DEFICIENT, which suspends the version and fires decertification."""
    response = client.conclude_audit(
        version_id,
        factories.conclude_audit_payload(
            outcome="DEFICIENT", audit_finding_rate=audit_finding_rate
        ),
        make_auditor_headers(AUDITOR_CONCLUDER_USER_ID),
    )
    return get_success_data(response)


def setup_campaign(client, advertiser_id: str, **overrides) -> dict:
    response = client.create_campaign(
        factories.create_campaign_payload(advertiser_id, **overrides), ADMIN
    )
    return get_success_data(response)


def setup_page(client, publisher_id: str, url: str = None, **overrides) -> dict:
    response = client.create_page(
        factories.create_page_payload(publisher_id, url=url, **overrides), ADMIN
    )
    return get_success_data(response)


def read_page(client, page_id: str) -> dict:
    return get_success_data(client.get_page(page_id, ADMIN))


def read_publisher(client, publisher_id: str) -> dict:
    return get_success_data(client.get_publisher(publisher_id, ADMIN))


def read_advertiser(client, advertiser_id: str) -> dict:
    return get_success_data(client.get_advertiser(advertiser_id, ADMIN))


def read_campaign(client, campaign_id: str) -> dict:
    return get_success_data(client.get_campaign(campaign_id, ADMIN))


def read_methodology_version(client, version_id: str) -> dict:
    return get_success_data(client.get_methodology_version(version_id, ADMIN))


def read_batch(client, batch_id: str) -> dict:
    return get_success_data(client.get_measurement_batch(batch_id, ADMIN))


def read_claim(client, claim_id: str) -> dict:
    return get_success_data(client.get_refund_claim(claim_id, ADMIN))


def read_classification(client, classification_id: str) -> dict:
    return get_success_data(client.get_page_classification(classification_id, ADMIN))


def read_appeal(client, appeal_id: str) -> dict:
    return get_success_data(client.get_appeal(appeal_id, ADMIN))


def read_segment(client, segment_id: str) -> dict:
    return get_success_data(client.get_pre_bid_segment(segment_id, ADMIN))


def read_list(client, list_id: str) -> dict:
    return get_success_data(client.get_inventory_list(list_id, ADMIN))


def read_finding(client, finding_id: str) -> dict:
    return get_success_data(client.get_ivt_finding(finding_id, ADMIN))


def read_scorecard(client, publisher_id: str) -> dict:
    return get_success_data(client.get_publisher_scorecard(publisher_id, ADMIN))


# ---------------------------------------------------------------------------
# tier 2: the base world every workflow starts from
# ---------------------------------------------------------------------------
def setup_base_world(
    client,
    clock: str = CLOCK_DEFAULT_NOW,
    campaign_overrides: dict = None,
    publisher_overrides: dict = None,
    advertiser_overrides: dict = None,
    accredit: bool = True,
) -> dict:
    """Clock, both counterparties, one SUITABILITY and one VIEWABILITY version,
    one campaign and one page. This is the shared preamble of nearly every
    workflow: classification needs the SUITABILITY version, measurement needs
    the VIEWABILITY one, and the two families may share an effectivity window
    because the no-overlap rule is scoped to a single family.
    """
    advance_clock(client, clock)
    advertiser = setup_advertiser(client, **(advertiser_overrides or {}))
    publisher = setup_publisher(client, **(publisher_overrides or {}))
    make_version = (
        setup_accredited_methodology_version if accredit else setup_methodology_version
    )
    suitability_version = make_version(client, standard_family="SUITABILITY")
    viewability_version = make_version(client, standard_family="VIEWABILITY")
    campaign = setup_campaign(
        client, advertiser["id"], **(campaign_overrides or {})
    )
    page = setup_page(client, publisher["id"])
    return {
        "clock": clock,
        "advertiser": advertiser,
        "publisher": publisher,
        "suitability_version": suitability_version,
        "viewability_version": viewability_version,
        "campaign": campaign,
        "page": page,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher_headers": make_publisher_headers(publisher["id"]),
    }


# ---------------------------------------------------------------------------
# tier 3: classification, review and appeals
# ---------------------------------------------------------------------------
def setup_classification(
    client, page: dict, suitability_version_id: str, analyst_user_id=None, **overrides
) -> dict:
    """Append one classification, reading the page's current version as the
    optimistic-concurrency token so successive writes never collide."""
    current = read_page(client, page["id"])
    payload = factories.create_page_classification_payload(
        current["id"], suitability_version_id, current["version"], **overrides
    )
    response = client.create_page_classification(
        payload, make_analyst_headers(analyst_user_id or ANALYST_AUTHOR_USER_ID)
    )
    return get_success_data(response)


def setup_reviewed_classification(
    client, page: dict, suitability_version_id: str,
    decision: str = "CONFIRM", reviewer_user_id=None, classification_overrides=None,
    **review_overrides,
) -> dict:
    """Classify then review, leaving the record CONFIRMED or OVERRIDDEN and the
    page at HUMAN_CONFIRMED - the only position an appeal may be filed from."""
    classification = setup_classification(
        client, page, suitability_version_id, **(classification_overrides or {})
    )
    response = client.review_page_classification(
        classification["id"],
        factories.review_classification_payload(decision=decision, **review_overrides),
        make_analyst_headers(reviewer_user_id or ANALYST_REVIEWER_USER_ID),
    )
    return get_success_data(response)


def setup_filed_appeal(client, world: dict, classification: dict = None, **overrides) -> dict:
    """An appeal in FILED at round 1 against an attested classification."""
    if classification is None:
        classification = setup_reviewed_classification(
            client, world["page"], world["suitability_version"]["id"]
        )
    response = client.create_appeal(
        factories.create_appeal_payload(classification["id"], **overrides),
        world["publisher_headers"],
    )
    return {"classification": classification, "appeal": get_success_data(response)}


def setup_appeal_at_round(client, world: dict, round_no: int, classification=None) -> dict:
    """Walk the FILED -> MORE_EVIDENCE_REQUIRED -> FILED negotiation cycle until
    the appeal sits in FILED at `round_no`. The cycle is bounded at three rounds.
    """
    filed = setup_filed_appeal(client, world, classification=classification)
    appeal = filed["appeal"]
    for _ in range(round_no - 1):
        looped = client.decide_appeal(
            appeal["id"],
            factories.decide_appeal_payload(outcome="MORE_EVIDENCE"),
            make_officer_headers(OFFICER_USER_ID),
        )
        appeal = get_success_data(looped)
        answered = client.submit_appeal_evidence(
            appeal["id"], factories.submit_evidence_payload(), world["publisher_headers"]
        )
        appeal = get_success_data(answered)
    filed["appeal"] = appeal
    return filed


def decide_appeal(client, appeal_id: str, outcome: str = "UPHELD", officer_user_id=None,
                  **overrides) -> dict:
    response = client.decide_appeal(
        appeal_id,
        factories.decide_appeal_payload(outcome=outcome, **overrides),
        make_officer_headers(officer_user_id or OFFICER_USER_ID),
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# tier 4: post-bid measurement
# ---------------------------------------------------------------------------
#: Sensor figures that fail the coverage floor of 0.7 (5000/10000 = 0.5) and so
#: send certification down the QUARANTINED branch.
QUARANTINE_FIGURES = {
    "measurable_impressions": 5000,
    "in_view_impressions": 3000,
}


def batch_window(index: int = 0, minutes: int = 30, date: str = "2026-08-01") -> tuple:
    """A closed delivery window on the given day, one per hour.

    Successive indices are separated by far more than the 60 seconds of clear
    air the window-collision rule of 2.8 demands, so a test may ingest several
    batches for the same campaign, page and format without tripping
    ERR_BATCH_WINDOW_COLLISION.
    """
    start = f"{date}T{index:02d}:00:00Z"
    end = f"{date}T{index:02d}:{minutes:02d}:00Z"
    return start, end


def setup_ingested_batch(client, world: dict, index: int = 0, **overrides) -> dict:
    """A batch at scoring_status INGESTED and settlement_status UNBILLED.

    The delivery window defaults to batch_window(index); pass window_start
    and/or window_end to place the batch on a window of your own choosing.
    """
    default_start, default_end = batch_window(index)
    window_start = overrides.pop("window_start", default_start)
    window_end = overrides.pop("window_end", default_end)
    payload = factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        overrides.pop("page_id", world["page"]["id"]),
        overrides.pop("methodology_version_id", world["viewability_version"]["id"]),
        window_start=window_start,
        window_end=window_end,
        **overrides,
    )
    return get_success_data(client.create_measurement_batch(payload, OPERATOR))


def ensure_page_classified(client, world: dict) -> dict:
    """Give the page an effective classification so scoring captures a real
    assessed_tier instead of UNRATED. An UNRATED assessment sets
    suitability_breach_flag and would force certification to quarantine.
    """
    page = read_page(client, world["page"]["id"])
    if page["classification_state"] == "UNCLASSIFIED":
        return setup_classification(
            client, page, world["suitability_version"]["id"]
        )
    return read_classification(client, page["current_classification_id"])


def setup_scored_batch(client, world: dict, index: int = 0, classify: bool = True,
                       **overrides) -> dict:
    """A batch at scoring_status SCORED with every computed figure in place."""
    if classify:
        ensure_page_classified(client, world)
    batch = setup_ingested_batch(client, world, index=index, **overrides)
    return get_success_data(client.score_measurement_batch(batch["id"], OPERATOR))


def setup_certified_batch(client, world: dict, index: int = 0, **overrides) -> dict:
    """A batch driven all the way to CERTIFIED. The default sensor figures clear
    all four certification conditions: coverage 0.8 is at or above the 0.7 floor,
    no confirmed finding leaves ivt_rate at 0.0000, no SIVT finding leaves
    sophistication_flag false, and the default classification's SAFE tier keeps
    suitability_breach_flag false against a MEDIUM_RISK campaign floor.
    """
    batch = setup_scored_batch(client, world, index=index, **overrides)
    return get_success_data(client.certify_measurement_batch(batch["id"], OPERATOR))


def setup_quarantined_batch(client, world: dict, index: int = 0, **overrides) -> dict:
    """A batch driven to QUARANTINED through a coverage shortfall, which also
    makes it claimable: its settlement_status may now leave UNBILLED.
    """
    figures = dict(QUARANTINE_FIGURES)
    figures.update(overrides)
    batch = setup_scored_batch(client, world, index=index, **figures)
    return get_success_data(client.certify_measurement_batch(batch["id"], OPERATOR))


def setup_proposed_finding(client, batch_id: str, **overrides) -> dict:
    """A finding at status PROPOSED, contributing nothing to the batch figures."""
    payload = factories.create_ivt_finding_payload(batch_id, **overrides)
    return get_success_data(client.create_ivt_finding(payload, OPERATOR))


def setup_confirmed_finding(client, batch_id: str, **overrides) -> dict:
    """A finding at status CONFIRMED, folded into the batch's deduplicated figures."""
    finding = setup_proposed_finding(client, batch_id, **overrides)
    return get_success_data(client.confirm_ivt_finding(finding["id"], OPERATOR))


def setup_restricted_publisher(client, world: dict) -> dict:
    """Quarantine three batches, which is what drives quarantined_batch_count to
    3 and moves the publisher ACTIVE -> RESTRICTED with status_reason
    QUARANTINE_THRESHOLD. Restriction is never requested by a client.
    """
    batches = [
        setup_quarantined_batch(client, world, index=i) for i in range(3)
    ]
    return {"batches": batches, "publisher": read_publisher(client, world["publisher"]["id"])}


# ---------------------------------------------------------------------------
# tier 4b: inventory lists, entries and pre-bid segments
# ---------------------------------------------------------------------------
def setup_inventory_list(client, advertiser: dict, list_type: str = "EXCLUSION",
                         **overrides) -> dict:
    """A DRAFT list. Lists are the advertiser's own instrument: only the
    Advertiser role creates and curates them."""
    headers = make_advertiser_headers(advertiser["id"])
    payload = factories.create_inventory_list_payload(
        advertiser["id"], list_type=list_type, **overrides
    )
    return get_success_data(client.create_inventory_list(payload, headers))


def add_list_entry(client, advertiser: dict, list_id: str, entry_type: str,
                   entry_value: str) -> dict:
    headers = make_advertiser_headers(advertiser["id"])
    payload = factories.create_list_entry_payload(
        entry_type=entry_type, entry_value=entry_value
    )
    return get_success_data(client.create_list_entry(list_id, payload, headers))


def setup_published_list(client, advertiser: dict, list_type: str = "EXCLUSION",
                         entries: list = None, **overrides) -> dict:
    """A list with entries appended and then published, so a segment may pin it.
    `entries` is a list of (entry_type, entry_value) pairs; publication is
    refused on an empty list.
    """
    inventory_list = setup_inventory_list(
        client, advertiser, list_type=list_type, **overrides
    )
    created = []
    for entry_type, entry_value in entries or [("DOMAIN", "other.example.com")]:
        created.append(
            add_list_entry(client, advertiser, inventory_list["id"], entry_type, entry_value)
        )
    headers = make_advertiser_headers(advertiser["id"])
    published = get_success_data(
        client.publish_inventory_list(inventory_list["id"], headers)
    )
    return {"list": published, "entries": created}


def setup_pre_bid_segment(client, advertiser: dict, campaign_id: str, **overrides) -> dict:
    """A segment at sync_status PENDING. At least one pinned list is mandatory."""
    headers = make_advertiser_headers(advertiser["id"])
    payload = factories.create_pre_bid_segment_payload(campaign_id, **overrides)
    return get_success_data(client.create_pre_bid_segment(payload, headers))


def setup_synced_segment(client, advertiser: dict, campaign_id: str, **overrides) -> dict:
    """A segment at sync_status SYNCED, which is the only state the placement
    decision read answers for."""
    headers = make_advertiser_headers(advertiser["id"])
    segment = setup_pre_bid_segment(client, advertiser, campaign_id, **overrides)
    return get_success_data(client.sync_pre_bid_segment(segment["id"], headers))


def setup_segment_world(client, world: dict, list_type: str = "EXCLUSION",
                        entries: list = None, floor_tier: str = "MEDIUM_RISK") -> dict:
    """One published list of the given type pinned into one synced segment."""
    published = setup_published_list(
        client, world["advertiser"], list_type=list_type, entries=entries
    )
    key = "inclusion_list_id" if list_type == "INCLUSION" else "exclusion_list_id"
    segment = setup_synced_segment(
        client, world["advertiser"], world["campaign"]["id"],
        suitability_floor_tier=floor_tier, **{key: published["list"]["id"]},
    )
    return {"list": published["list"], "entries": published["entries"], "segment": segment}


def get_decision(client, world: dict, page_id: str, segment_id: str):
    """The placement decision read, performed by the owning advertiser."""
    return client.get_pre_bid_decision(
        page_id, world["advertiser_headers"], params={"segment_id": segment_id}
    )


# ---------------------------------------------------------------------------
# tier 5: refund claims and the credit ledger
# ---------------------------------------------------------------------------
def setup_submitted_claim(client, world: dict, batch_ids: list = None,
                          **overrides) -> dict:
    """A claim at claim_state SUBMITTED over claimable batches. Every cited batch
    must be QUARANTINED or DECERTIFIED and still UNBILLED."""
    if batch_ids is None:
        batch_ids = [setup_quarantined_batch(client, world)["id"]]
    campaign = read_campaign(client, world["campaign"]["id"])
    payload = factories.create_refund_claim_payload(
        campaign["id"], world["publisher"]["id"], batch_ids, campaign["version"],
        **overrides,
    )
    return get_success_data(
        client.create_refund_claim(payload, world["advertiser_headers"])
    )


def setup_claim_under_review(client, world: dict, batch_ids: list = None,
                             officer_user_id=None, **overrides) -> dict:
    """A claim at claim_state UNDER_REVIEW with the gross-basis figures refreshed."""
    claim = setup_submitted_claim(client, world, batch_ids=batch_ids, **overrides)
    return get_success_data(
        client.review_refund_claim(
            claim["id"], make_officer_headers(officer_user_id or OFFICER_USER_ID)
        )
    )


def setup_approved_claim(client, world: dict, batch_ids: list = None,
                         officer_user_id=None, **overrides) -> dict:
    """A claim at claim_state APPROVED, with the money triple frozen and both
    halves of the double-entry ledger posted."""
    claim = setup_claim_under_review(
        client, world, batch_ids=batch_ids, officer_user_id=officer_user_id, **overrides
    )
    return get_success_data(
        client.approve_refund_claim(
            claim["id"], make_officer_headers(officer_user_id or OFFICER_USER_ID)
        )
    )
