"""Writes blocked by the state of a row other than the one addressed.

PRD §2.10 step 10 gates a write on the states of *other* rows: an incident
notification on its policy, and a directed vendor engagement on the panel firm
it names.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ADJUSTER_HEADERS, ErrorId, PANEL_ADMIN_HEADERS, UNDERWRITER_HEADERS
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, data_of, get_total_count


IRONCLAD = {
    "vendor_name": "Ironclad Forensics",
    "vendor_type": "FORENSICS",
    "pre_approved_hourly_rate_usd": 500,
    "per_record_notification_rate_usd": 0,
    "specialty_sectors": ["HEALTHCARE", "FINANCIAL"],
    "tier": 1,
    "capacity_concurrent_engagements": 1,
}


def _aurora_policy(api, **kwargs):
    return X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        coverage_sections=list(C.STANDARD_TOWER),
        findings=[],
        **kwargs,
    )


# ==========================================================================
# The policy's lifecycle gates claim intake
# ==========================================================================
def _cancelled_policy(api):
    chain = _aurora_policy(api)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    cancelled = data_of(
        api.cancel_policy(
            chain["policy"]["id"],
            F.cancel_policy_payload("NON_PAYMENT"),
            UNDERWRITER_HEADERS,
        )
    )
    assert cancelled["lifecycle_status"] == "CANCELLED", cancelled["lifecycle_status"]
    return chain


def test_notifying_an_incident_on_a_cancelled_policy_is_refused_on_policy_state(api):
    """A cancelled contract cannot take a new notification, even inside its old period.

    PRD §3.6: "Three gates guard intake. The policy must be in `INFORCE` with
    `limit_status` other than `EXHAUSTED`, or the notification is refused with
    `ERR_INVALID_POLICY_STATE`." PRD §2.10 classes this as a cross-entity gate:
    "**Cross-entity state** — states of *other* rows gate the write (409): notifying
    an incident requires its policy in `INFORCE` with `limit_status` other than
    `EXHAUSTED`".

    Design: Difficulty/cross_entity_state_dependency/claim_notification_on_cancelled_policy_returns_409
    """
    chain = _cancelled_policy(api)

    response = api.create_incident_claim(
        F.incident_claim_payload(
            chain["policy"]["id"],
            incident_type="RANSOMWARE",
            incident_discovered_at="2026-09-05T00:00:00Z",
            outage_start_at="2026-09-05T00:00:00Z",
            outage_end_at="2026-09-08T00:00:00Z",
            affected_record_count=12345,
        ),
        ADJUSTER_HEADERS,
    )

    validate_error(response, ErrorId.INVALID_POLICY_STATE, 409)


def test_the_refused_notification_creates_no_claim_and_leaves_the_policy_cancelled(api):
    """No claim row appears for the policy and its capacity is still whole.

    PRD §3.5: "`lifecycle_status` describes the contractual life of the contract and
    runs from `INFORCE` to one of the terminal states `CANCELLED`, `EXPIRED`, or
    `NON_RENEWED`; `cancelled_at` and `cancellation_reason` are populated only on the
    cancellation path." A refused notification writes nothing, so the erosion
    dimension is untouched too.

    Design: Difficulty/cross_entity_state_dependency/claim_notification_on_cancelled_policy_returns_409
    """
    chain = _cancelled_policy(api)
    policy_id = chain["policy"]["id"]

    api.create_incident_claim(
        F.incident_claim_payload(
            policy_id,
            incident_type="RANSOMWARE",
            incident_discovered_at="2026-09-05T00:00:00Z",
            outage_start_at="2026-09-05T00:00:00Z",
            outage_end_at="2026-09-08T00:00:00Z",
            affected_record_count=12345,
        ),
        ADJUSTER_HEADERS,
    )

    listed = api.list_incident_claims(ADJUSTER_HEADERS, params={"policy_id": policy_id})
    assert get_total_count(listed) == 0

    policy = X.read_policy(api, policy_id)
    assert policy["lifecycle_status"] == "CANCELLED", policy["lifecycle_status"]
    assert_money(policy["aggregate_limit_remaining_usd"], 5000000.00, "aggregate_limit_remaining_usd")


# ==========================================================================
# The directed firm's panel standing gates the engagement
# ==========================================================================
def _claim_and_suspended_firm(api):
    chain = _aurora_policy(api)
    vendor = X.create_vendor(api, IRONCLAD)
    suspended = data_of(
        api.update_panel_vendor(vendor["id"], {"status": "SUSPENDED"}, PANEL_ADMIN_HEADERS)
    )
    assert suspended["status"] == "SUSPENDED", suspended["status"]

    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
    )
    return chain, vendor, claim


def _direct_at(vendor_id):
    return F.vendor_engagement_payload(
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-15T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor_id,
        directed_rate_usd=500,
    )


def test_directing_an_engagement_at_a_suspended_firm_is_refused_on_the_firm_state(api):
    """A SUSPENDED panel firm cannot be directed, even with a rate inside its ceiling.

    PRD §3.7: "A directed firm must exist and its `status` must be `ACTIVE` — a
    `SUSPENDED` or `RETIRED` firm is refused with `ERR_VENDOR_NOT_ACTIVE`." The
    claim itself is in a state that admits an engagement, so only the firm's panel
    standing can be at issue.

    Design: Difficulty/cross_entity_state_dependency/directed_engagement_on_suspended_panel_vendor_returns_409
    """
    _chain, vendor, claim = _claim_and_suspended_firm(api)

    response = api.create_vendor_engagement(
        claim["id"], _direct_at(vendor["id"]), ADJUSTER_HEADERS
    )

    validate_error(response, ErrorId.VENDOR_NOT_ACTIVE, 409)


def test_the_refused_engagement_consumes_no_slot_and_leaves_the_claim_where_it_was(api):
    """No engagement row is written, the firm's slot count stays at 0, the claim stays confirmed.

    PRD §3.7: "A computed `active_engagement_count`, starting at 0, is the conserved
    slot quantity: it is the number of engagements on that firm whose `status` is
    `AUTHORIZED` or `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/directed_engagement_on_suspended_panel_vendor_returns_409
    """
    _chain, vendor, claim = _claim_and_suspended_firm(api)

    api.create_vendor_engagement(claim["id"], _direct_at(vendor["id"]), ADJUSTER_HEADERS)

    listed = api.list_vendor_engagements(
        ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
    )
    assert get_total_count(listed) == 0

    reread_vendor = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert reread_vendor["active_engagement_count"] == 0, reread_vendor
    assert reread_vendor["status"] == "SUSPENDED", reread_vendor["status"]

    reread_claim = X.read_claim(api, claim["id"])
    assert reread_claim["status"] == "COVERAGE_CONFIRMED", reread_claim["status"]
