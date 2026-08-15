"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database, and the logical clock starts at 2026-08-01T00:00:00Z). Setup calls
use get_success_data so failures surface as clear "Setup failed" errors.
Ownership-gated calls always thread the real Subcontractor.id through
make_subcontractor_headers.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    approve_decision_payload,
    create_addendum_payload,
    create_award_recommendation_payload,
    create_bid_package_payload,
    create_bid_payload,
    create_invitation_payload,
    create_prequal_application_payload,
    decide_recommendation_payload,
    prequal_decision_payload,
    prequal_resubmit_payload,
    respond_invitation_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_chief_estimator_headers,
    make_lead_estimator_headers,
    make_subcontractor_headers,
)

LEAD = TEST_USERS["lead_estimator_headers"]
CHIEF = TEST_USERS["chief_estimator_headers"]
REVIEWER = TEST_USERS["prequal_reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Canonical operator ids for the two-chair award pipeline (PRD 3.9: the
# decider's X-User-ID must differ from the drafter's created_by_user_id).
DRAFTER_ID = "le-100"
DECIDER_ID = "ce-900"

_LICENSE_SEQ = itertools.count(1)


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected=None):
    try:
        data = get_success_data(resp)
    except AssertionError:
        _fail(step, resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — subcontractor registration and prequalification
# ---------------------------------------------------------------------------

def register_subcontractor(legal_name=None, license_number=None, **overrides):
    """Anonymous self-registration. Returns the Subcontractor row."""
    seq = next(_LICENSE_SEQ)
    payload = {
        "legal_name": legal_name or f"Sub {seq} LLC",
        "contact_email": f"sub{seq}@x.com",
        "license_number": license_number or f"LIC-AUTO-{seq:05d}",
    }
    payload.update(overrides)
    resp = api_client.create_subcontractor(payload, ANON)
    return _ok("register_subcontractor", resp)


def submit_prequal_application(subcontractor_id, **overrides):
    """Subcontractor submits its own application. Returns SUBMITTED app."""
    resp = api_client.create_prequal_application(
        create_prequal_application_payload(subcontractor_id, **overrides),
        make_subcontractor_headers(subcontractor_id),
    )
    return _ok("submit_prequal_application", resp, expected="SUBMITTED")


def decide_application(application_id, decision, **overrides):
    """PrequalReviewer decides an application. Returns the updated app."""
    resp = api_client.decide_prequal_application(
        application_id, prequal_decision_payload(decision, **overrides), REVIEWER)
    return _ok("decide_application", resp)


def approve_application(application_id, **overrides):
    resp = api_client.decide_prequal_application(
        application_id, approve_decision_payload(**overrides), REVIEWER)
    return _ok("approve_application", resp, expected="APPROVED")


def resubmit_application(application_id, subcontractor_id, **overrides):
    resp = api_client.resubmit_prequal_application(
        application_id, prequal_resubmit_payload(**overrides),
        make_subcontractor_headers(subcontractor_id),
    )
    return _ok("resubmit_application", resp, expected="SUBMITTED")


def setup_approved_subcontractor(**overrides):
    """Register a firm, submit its application, approve it.

    Returns dict(subcontractor=..., application=...). Approval stamps use the
    logical clock as it stands when the decision is recorded.
    """
    sub = register_subcontractor(**{k: v for k, v in overrides.items()
                                    if k in ("legal_name", "license_number")})
    app = submit_prequal_application(sub["id"])
    approved = approve_application(app["id"])
    return {"subcontractor": sub, "application": approved}


# ---------------------------------------------------------------------------
# Tier 1 — bid package stand-up
# ---------------------------------------------------------------------------

def create_bid_package(name="Bid Package", trade_code="051200",
                       bid_due_at=None, bid_bond_required_pct=None):
    payload = create_bid_package_payload(
        name=name, trade_code=trade_code,
        bid_due_at=bid_due_at or TEST_DEFAULTS["BID_DUE_AT"],
    )
    if bid_bond_required_pct is not None:
        payload["bid_bond_required_pct"] = bid_bond_required_pct
    resp = api_client.create_bid_package(payload, LEAD)
    return _ok("create_bid_package", resp, expected="DRAFT")


def invite(package_id, subcontractor_id):
    resp = api_client.create_invitation(
        create_invitation_payload(package_id, subcontractor_id), LEAD)
    return _ok("invite", resp, expected="SENT")


def respond_invitation(invitation_id, subcontractor_id, intent):
    resp = api_client.respond_invitation(
        invitation_id, respond_invitation_payload(intent),
        make_subcontractor_headers(subcontractor_id),
    )
    return _ok("respond_invitation", resp)


def respond_bidding(invitation_id, subcontractor_id):
    return _ok("respond_bidding",
               api_client.respond_invitation(
                   invitation_id, respond_invitation_payload("BIDDING"),
                   make_subcontractor_headers(subcontractor_id)),
               expected="BIDDING")


def publish_package(package_id):
    resp = api_client.publish_bid_package(package_id, LEAD)
    return _ok("publish_package", resp, expected="PUBLISHED")


def advance_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), LEAD)
    return _ok("advance_clock", resp)


def close_bidding(package_id):
    resp = api_client.close_bidding(package_id, LEAD)
    return _ok("close_bidding", resp, expected="BIDDING_CLOSED")


def tabulate(package_id):
    resp = api_client.tabulate_bid_package(package_id, LEAD)
    return _ok("tabulate", resp, expected="TABULATED")


def get_package(package_id):
    return _ok("get_package", api_client.get_bid_package(package_id, LEAD))


def get_bid(bid_id, headers=None):
    return _ok("get_bid", api_client.get_bid(bid_id, headers or LEAD))


def get_leveling_sheet(bid_id):
    return _ok("get_leveling_sheet", api_client.get_leveling_sheet(bid_id, LEAD))


# ---------------------------------------------------------------------------
# Tier 2 — the biddable subcontractor: approved prequal + BIDDING invitation
# ---------------------------------------------------------------------------

def setup_bidder(package_id=None, approve=True, respond_intent="BIDDING",
                 **package_kwargs):
    """Approved firm invited to a package and (by default) marked BIDDING.

    The package is created when not supplied. Returns
    dict(package, subcontractor, application, invitation).
    """
    pkg = package_id and get_package(package_id) or create_bid_package(
        **package_kwargs)
    ctx = setup_approved_subcontractor() if approve else {
        "subcontractor": register_subcontractor(),
        "application": None,
    }
    inv = invite(pkg["id"], ctx["subcontractor"]["id"])
    if respond_intent:
        inv = respond_invitation(inv["id"], ctx["subcontractor"]["id"],
                                 respond_intent)
    return {
        "package": pkg,
        "subcontractor": ctx["subcontractor"],
        "application": ctx["application"],
        "invitation": inv,
    }


def setup_published_with_bidders(n=2, publish=True, **package_kwargs):
    """Package with n approved subcontractors, all responded BIDDING.

    Returns dict(package, bidders=[{subcontractor, application, invitation}]).
    The package is NOT published unless publish=True.
    """
    pkg = create_bid_package(**package_kwargs)
    bidders = []
    for _ in range(n):
        ctx = setup_approved_subcontractor()
        inv = invite(pkg["id"], ctx["subcontractor"]["id"])
        inv = respond_bidding(inv["id"], ctx["subcontractor"]["id"])
        bidders.append({**ctx, "invitation": inv})
    if publish:
        pkg = publish_package(pkg["id"])
    return {"package": pkg, "bidders": bidders}


def submit_bid(package_id, subcontractor_id, base_bid_cents=1_000_000,
               bond_amount_cents=None, **overrides):
    payload = create_bid_payload(
        package_id, base_bid_cents=base_bid_cents,
        bond_amount_cents=(bond_amount_cents
                           if bond_amount_cents is not None
                           else int(base_bid_cents * 0.05)),
        **overrides)
    resp = api_client.create_bid(
        payload, make_subcontractor_headers(subcontractor_id))
    return _ok("submit_bid", resp, expected="SUBMITTED")


def setup_package_with_bids(bid_amounts=(1_000_000,), **package_kwargs):
    """PUBLISHED package with one SUBMITTED bid per bidder.

    bid_amounts is a tuple of (base_bid_cents) values, one bidder each.
    Returns dict(package, bidders, bids).
    """
    ctx = setup_published_with_bidders(n=len(bid_amounts), **package_kwargs)
    bids = []
    for bidder, amount in zip(ctx["bidders"], bid_amounts):
        bids.append(submit_bid(ctx["package"]["id"],
                               bidder["subcontractor"]["id"], amount))
    return {**ctx, "bids": bids}


def setup_closed_package_with_bids(bid_amounts=(1_000_000,),
                                   close_at=None, **package_kwargs):
    """Bids submitted, clock advanced past the deadline, bidding closed."""
    ctx = setup_package_with_bids(bid_amounts, **package_kwargs)
    advance_clock(close_at or TEST_DEFAULTS["AFTER_DUE"])
    ctx["package"] = close_bidding(ctx["package"]["id"])
    return ctx


def setup_tabulated_package(bid_amounts=(1_000_000,), **package_kwargs):
    """Full flow through TABULATED. Returns dict(package, bidders, bids)."""
    ctx = setup_closed_package_with_bids(bid_amounts, **package_kwargs)
    ctx["package"] = tabulate(ctx["package"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — leveling, interviews
# ---------------------------------------------------------------------------

def add_leveling_adjustment(bid_id, treatment="GC_ALLOWANCE",
                            amount_cents=None, pct_of_base=None,
                            description="leveling line"):
    payload = {"bid_id": bid_id, "description": description,
               "treatment": treatment}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    if pct_of_base is not None:
        payload["pct_of_base"] = pct_of_base
    resp = api_client.create_leveling_adjustment(payload, LEAD)
    return _ok("add_leveling_adjustment", resp)


def issue_addendum(package_id, summary="Addendum: scope change"):
    resp = api_client.create_addendum(
        create_addendum_payload(package_id, summary=summary), LEAD)
    return _ok("issue_addendum", resp)


def acknowledge_addendum(addendum_id, subcontractor_id):
    resp = api_client.acknowledge_addendum(
        addendum_id, make_subcontractor_headers(subcontractor_id))
    return _ok("acknowledge_addendum", resp, expected="ACKNOWLEDGED")


# ---------------------------------------------------------------------------
# Tier 4 — award recommendation pipeline
# ---------------------------------------------------------------------------

def draft_recommendation(package_id, recommended_bid_id,
                         rationale="scope coverage, leveling outcome",
                         drafter_id=DRAFTER_ID):
    """Read the live package version and draft a recommendation against it.

    Returns (recommendation, package_version_before_create).
    """
    pkg = get_package(package_id)
    resp = api_client.create_award_recommendation(
        create_award_recommendation_payload(
            package_id, recommended_bid_id, pkg["version"],
            rationale=rationale),
        make_lead_estimator_headers(drafter_id),
    )
    rec = _ok("draft_recommendation", resp, expected="DRAFT")
    return rec, pkg["version"]


def submit_recommendation(recommendation_id, drafter_id=DRAFTER_ID):
    resp = api_client.submit_award_recommendation(
        recommendation_id, make_lead_estimator_headers(drafter_id))
    return _ok("submit_recommendation", resp, expected="SUBMITTED")


def decide_recommendation(recommendation_id, decision, decider_id=DECIDER_ID,
                          **overrides):
    resp = api_client.decide_award_recommendation(
        recommendation_id,
        decide_recommendation_payload(decision, **overrides),
        make_chief_estimator_headers(decider_id),
    )
    return _ok("decide_recommendation", resp, expected=decision)


def setup_recommendation_pending(bid_amounts=(1_000_000,), recommend_index=0,
                                 **package_kwargs):
    """TABULATED package + DRAFT recommendation submitted.

    Returns dict(package, bidders, bids, recommendation).
    Package status is RECOMMENDATION_PENDING (leveling locked).
    """
    ctx = setup_tabulated_package(bid_amounts, **package_kwargs)
    rec, _ = draft_recommendation(
        ctx["package"]["id"], ctx["bids"][recommend_index]["id"])
    rec = submit_recommendation(rec["id"])
    return {**ctx, "recommendation": rec}


def setup_awarded_package(bid_amounts=(1_000_000, 1_100_000),
                          recommend_index=1, **package_kwargs):
    """Full cascade through AWARDED. recommend_index names the winning bid.

    Returns dict(package, bidders, bids, recommendation); the losing bids
    each hold one auto-created DRAFT feedback record.
    """
    ctx = setup_recommendation_pending(bid_amounts, recommend_index,
                                       **package_kwargs)
    rec = decide_recommendation(ctx["recommendation"]["id"], "APPROVED")
    ctx["recommendation"] = rec
    ctx["package"] = get_package(ctx["package"]["id"])
    return ctx
