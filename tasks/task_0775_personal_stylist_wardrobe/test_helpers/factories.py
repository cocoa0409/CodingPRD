"""Payload factories — one per entity, input fields only."""
import uuid


def unique_email(prefix: str = "u") -> str:
    """A per-call unique email so multiple entities in one test never collide on the
    unique-email constraint."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@x.com"


# ─────────────────────────── Stylist / Client ───────────────────────────
def create_stylist_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Stylist",
        "email": unique_email("sty"),
        "commission_pct": 0.30,
        "tier": "SENIOR",
    }
    payload.update(overrides)
    return payload


def register_client_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Client",
        "email": unique_email("cl"),
    }
    payload.update(overrides)
    return payload


# ─────────────────────────── StyleAssessment ───────────────────────────
def create_assessment_payload(**overrides) -> dict:
    payload = {
        "body_type": "hourglass",
        "color_palette": "COOL",
        "budget_band": "MID",
        "lifestyle": "corporate",
    }
    payload.update(overrides)
    return payload


# ─────────────────────────── Engagement ───────────────────────────
def create_engagement_payload(client_id, stylist_id, mode="HOURLY",
                              block_rate_cents=3000, package_blocks=None,
                              package_price_cents=None, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "stylist_id": stylist_id,
        "mode": mode,
        "block_rate_cents": block_rate_cents,
    }
    if package_blocks is not None:
        payload["package_blocks"] = package_blocks
    if package_price_cents is not None:
        payload["package_price_cents"] = package_price_cents
    payload.update(overrides)
    return payload


# ─────────────────────────── Session ───────────────────────────
def create_session_payload(scheduled_start, scheduled_end, expected_engagement_version,
                           session_type="CLOSET_AUDIT", modality="IN_PERSON",
                           **overrides) -> dict:
    payload = {
        "session_type": session_type,
        "modality": modality,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_engagement_version": expected_engagement_version,
    }
    payload.update(overrides)
    return payload


def reschedule_session_payload(scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    payload.update(overrides)
    return payload


def complete_session_payload(actual_minutes, **overrides) -> dict:
    payload = {"actual_minutes": actual_minutes}
    payload.update(overrides)
    return payload


# ─────────────────────────── PurchaseItem ───────────────────────────
def create_item_payload(retail_cost_cents, description="wool blazer", **overrides) -> dict:
    payload = {"description": description, "retail_cost_cents": retail_cost_cents}
    payload.update(overrides)
    return payload


# ─────────────────────────── Lookbook ───────────────────────────
def create_lookbook_payload(title="Spring Capsule", **overrides) -> dict:
    payload = {"title": title}
    payload.update(overrides)
    return payload


def add_outfit_payload(name="Look 1", **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return payload


# ─────────────────────────── Subscription ───────────────────────────
def create_subscription_payload(tier="SILVER", monthly_fee_cents=5000, **overrides) -> dict:
    payload = {"tier": tier, "monthly_fee_cents": monthly_fee_cents}
    payload.update(overrides)
    return payload


# ─────────────────────────── Referral ───────────────────────────
def create_referral_payload(referrer_client_id, referee_email, **overrides) -> dict:
    payload = {"referrer_client_id": referrer_client_id, "referee_email": referee_email}
    payload.update(overrides)
    return payload


def signup_referral_payload(referee_client_id, **overrides) -> dict:
    payload = {"referee_client_id": referee_client_id}
    payload.update(overrides)
    return payload


# ─────────────────────────── Admin ───────────────────────────
def wallet_adjustment_payload(amount_cents, reason="seed", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
