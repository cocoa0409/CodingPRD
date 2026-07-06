"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"setup failed" errors rather than confusing downstream assertion failures.

Identity threading: Member is entity_backed:User, so every ownership-gated call uses
make_member_headers(<the acting User.id>) — never the shared TEST_USERS["member_headers"].
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_user_payload,
    create_petition_payload,
    set_target_payload,
    create_representative_payload,
    sign_payload,
    create_comment_payload,
    create_campaign_payload,
    create_donation_payload,
    create_promotion_payload,
    create_delivery_meeting_payload,
    unique_email,
)
from .test_users import TEST_USERS, make_member_headers

GUEST = TEST_USERS["guest_headers"]
MODERATOR = TEST_USERS["moderator_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Users ────────────────────────────────────────────────────────────────
def register_member(jurisdiction="US-CA-12", full_name="Member User", email=None) -> dict:
    """Register a User and return the created record (drives Member ownership)."""
    payload = create_user_payload(
        email=email or unique_email("m"),
        full_name=full_name,
        jurisdiction=jurisdiction,
    )
    return get_success_data(api_client.create_user(payload, GUEST))


# ─── Petition state progression ─────────────────────────────────────────────
def create_draft_petition(author_id, category="OTHER", goal=10,
                          eligible_jurisdiction=None, **overrides) -> dict:
    """Create a DRAFT petition owned by author_id. Returns the petition record."""
    payload = create_petition_payload(category=category, goal=goal, **overrides)
    if eligible_jurisdiction is not None:
        payload["eligible_jurisdiction"] = eligible_jurisdiction
    return get_success_data(
        api_client.create_petition(payload, make_member_headers(author_id)))


def set_petition_target(petition_id, author_id, expected_version, **overrides) -> dict:
    """Set/replace a petition's decision-maker (Target). Returns the Target record."""
    payload = set_target_payload(expected_version, **overrides)
    return get_success_data(
        api_client.set_target(petition_id, payload, make_member_headers(author_id)))


def publish_petition(category="OTHER", goal=10, eligible_jurisdiction=None,
                     author_jurisdiction="US-CA-12", author_id=None, **petition_overrides) -> dict:
    """Full walk: register author -> create petition -> set target -> submit ->
    moderate APPROVE. Returns dict with author_id, petition_id, target_id, and the
    refetched PUBLISHED petition."""
    if author_id is None:
        author_id = register_member(jurisdiction=author_jurisdiction)["id"]
    pet = create_draft_petition(author_id, category=category, goal=goal,
                                eligible_jurisdiction=eligible_jurisdiction, **petition_overrides)
    target = set_petition_target(pet["id"], author_id, pet["version"])
    api_client.submit_petition(pet["id"], make_member_headers(author_id))
    api_client.moderate_petition(pet["id"], {"decision": "APPROVE"}, MODERATOR)
    petition = get_success_data(api_client.get_petition(pet["id"], GUEST))
    return {
        "author_id": author_id,
        "petition_id": pet["id"],
        "target_id": target["id"],
        "petition": petition,
    }


def submit_petition_under_review(category="OTHER", goal=10, author_id=None) -> dict:
    """Register author -> create petition -> set target -> submit (UNDER_REVIEW, not
    approved). Returns dict with author_id, petition_id, target_id."""
    if author_id is None:
        author_id = register_member()["id"]
    pet = create_draft_petition(author_id, category=category, goal=goal)
    target = set_petition_target(pet["id"], author_id, pet["version"])
    api_client.submit_petition(pet["id"], make_member_headers(author_id))
    return {"author_id": author_id, "petition_id": pet["id"], "target_id": target["id"]}


# ─── Signatures ─────────────────────────────────────────────────────────────
def sign(petition_id, signer_id, public_comment=None) -> dict:
    """Create a PENDING_VERIFICATION signature. Returns record (carries token)."""
    payload = sign_payload()
    if public_comment is not None:
        payload["public_comment"] = public_comment
    return get_success_data(
        api_client.sign_petition(petition_id, payload, make_member_headers(signer_id)))


def sign_and_verify(petition_id, signer_id) -> dict:
    """Create then confirm a signature -> VERIFIED. Returns the verified record."""
    sig = sign(petition_id, signer_id)
    return get_success_data(api_client.verify_signature(
        sig["id"], {"verification_token": sig["verification_token"]},
        make_member_headers(signer_id)))


def register_and_sign(petition_id, jurisdiction="US-CA-12") -> dict:
    """Register a fresh signer and create a PENDING signature. Returns the signature."""
    signer = register_member(jurisdiction=jurisdiction)
    sig = sign(petition_id, signer["id"])
    sig["_signer_id"] = signer["id"]
    return sig


def register_sign_and_verify(petition_id, jurisdiction="US-CA-12") -> dict:
    """Register a fresh signer and drive their signature to VERIFIED. Returns it."""
    signer = register_member(jurisdiction=jurisdiction)
    sig = sign_and_verify(petition_id, signer["id"])
    sig["_signer_id"] = signer["id"]
    return sig


# ─── Campaign & donations ───────────────────────────────────────────────────
def create_campaign(petition_id, author_id, goal_cents=100000) -> dict:
    return get_success_data(api_client.create_campaign(
        petition_id, create_campaign_payload(goal_cents=goal_cents),
        make_member_headers(author_id)))


def setup_campaign(goal=10, campaign_goal_cents=100000) -> dict:
    """Register author -> create DRAFT petition -> create ACTIVE campaign.
    Returns dict with author_id, petition_id, campaign_id."""
    author_id = register_member()["id"]
    pet = create_draft_petition(author_id, goal=goal)
    campaign = create_campaign(pet["id"], author_id, goal_cents=campaign_goal_cents)
    return {"author_id": author_id, "petition_id": pet["id"], "campaign_id": campaign["id"]}


def donate(campaign_id, donor_id, amount_cents) -> dict:
    return get_success_data(api_client.create_donation(
        campaign_id, create_donation_payload(amount_cents),
        make_member_headers(donor_id)))


def settle_donation(donation_id) -> dict:
    return get_success_data(api_client.transition_donation(
        donation_id, {"to_status": "SETTLED"}, ADMIN))


def refund_donation(donation_id) -> dict:
    return get_success_data(api_client.transition_donation(
        donation_id, {"to_status": "REFUNDED"}, ADMIN))


# ─── Delivery meetings ──────────────────────────────────────────────────────
def create_meeting(petition_id, target_id, author_id, window_start, window_end) -> dict:
    return get_success_data(api_client.create_delivery_meeting(
        create_delivery_meeting_payload(petition_id, target_id, window_start, window_end),
        make_member_headers(author_id)))


def confirm_meeting(meeting_id) -> dict:
    return get_success_data(api_client.transition_delivery_meeting(
        meeting_id, {"to_status": "CONFIRMED"}, ADMIN))


def deliver_meeting(meeting_id, author_id) -> dict:
    return get_success_data(api_client.transition_delivery_meeting(
        meeting_id, {"to_status": "DELIVERED"}, make_member_headers(author_id)))


def setup_delivered_meeting(petition_id, target_id, author_id,
                            window_start="2026-05-10T10:00:00Z",
                            window_end="2026-05-10T11:00:00Z") -> dict:
    """Create a meeting and drive it REQUESTED -> CONFIRMED -> DELIVERED. Returns it."""
    meeting = create_meeting(petition_id, target_id, author_id, window_start, window_end)
    confirm_meeting(meeting["id"])
    return deliver_meeting(meeting["id"], author_id)


# ─── Comments ───────────────────────────────────────────────────────────────
def post_comment(petition_id, author_id, body="A comment", comment_type=None) -> dict:
    payload = create_comment_payload(body=body)
    if comment_type is not None:
        payload["comment_type"] = comment_type
    return get_success_data(api_client.create_comment(
        petition_id, payload, make_member_headers(author_id)))


def post_approved_comment(petition_id, commenter_id, body="great") -> dict:
    """Post a COMMENT and moderate it to APPROVED. Returns the comment record."""
    cmt = post_comment(petition_id, commenter_id, body=body)
    return get_success_data(api_client.moderate_comment(
        cmt["id"], {"decision": "APPROVE"}, MODERATOR))


def post_flagged_comment(petition_id, commenter_id, body="great") -> dict:
    """Post -> APPROVE -> FLAG. Returns the FLAGGED comment record."""
    cmt = post_approved_comment(petition_id, commenter_id, body=body)
    return get_success_data(api_client.flag_comment(
        cmt["id"], make_member_headers(commenter_id)))


# ─── Promotions ─────────────────────────────────────────────────────────────
def create_promotion(petition_id, purchaser_id, placement_tier, window_start, window_end) -> dict:
    return get_success_data(api_client.create_promotion(
        create_promotion_payload(petition_id, placement_tier, window_start, window_end),
        make_member_headers(purchaser_id)))


def setup_category_two_overlapping_promotions(category="ENVIRONMENT") -> dict:
    """Publish two petitions in `category` and schedule one overlapping promotion on
    each so the category's window around 2026-04-03 already holds 2 concurrent
    SCHEDULED promotions. Returns author_id (shared) for reuse."""
    author_id = register_member()["id"]
    petB = publish_petition(category=category, goal=100, author_id=author_id)
    create_promotion(petB["petition_id"], author_id, "STANDARD",
                     "2026-04-01T00:00:00Z", "2026-04-05T00:00:00Z")
    petC = publish_petition(category=category, goal=100, author_id=author_id)
    create_promotion(petC["petition_id"], author_id, "STANDARD",
                     "2026-04-02T00:00:00Z", "2026-04-06T00:00:00Z")
    return {"author_id": author_id}
