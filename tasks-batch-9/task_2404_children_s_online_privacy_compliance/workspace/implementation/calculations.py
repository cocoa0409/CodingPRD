"""Calculation rules (PRD §3.1-§3.10 / SCAFFOLD §1.3).

Every derived quantity is computed from the store on demand, so a value read back
is always consistent with the cascades that have already settled.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from constants import (
    ALLOWED_DISPOSAL_METHODS,
    DESIGN_ESCALATION_THRESHOLD,
    DESIGN_MIXED_THRESHOLD,
    DESIGN_PRIMARY_THRESHOLD,
    DISCLOSURE_USES,
    FACTOR_POINTS,
    INTEGRATION_TYPE_POINTS,
    LIVE_RECORD_STATUSES,
    MAX_TIER,
    METHOD_ASSURANCE_TIER,
    MIXED_SHARE_THRESHOLD,
    NEUTRALITY_CODE_ORDER,
    POSTURE_FREEZE_POINTS,
    POSTURE_RESTRICT_POINTS,
    PRIMARY_SHARE_THRESHOLD,
    RATING_VALUE,
    REQUIRED_NOTICE_CONTENT_KEYS,
    TIER_BUMP_INTEGRATION_TYPES,
    USE_TIER,
)
from db import db, now

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def _round(value, places):
    return value.quantize(places, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# design_factor_weighted_score (PRD §3.1)
# ---------------------------------------------------------------------------
def design_score(service_id):
    rows = [
        e
        for e in db.determination_evidence.values()
        if e["service_id"] == service_id and e["evidence_kind"] == "DESIGN_FACTOR"
    ]
    if not rows:
        return Decimal("0.00")
    # Only the LATEST row per factor_code participates; evidence_sequence is the
    # only ordering key (never id, never created_at).
    latest = {}
    for row in rows:
        code = row["factor_code"]
        current = latest.get(code)
        if current is None or row["evidence_sequence"] > current["evidence_sequence"]:
            latest[code] = row
    present_points = sum(FACTOR_POINTS[code] for code in latest)
    if present_points == 0:
        return Decimal("0.00")
    total = Decimal("0")
    # ROUNDING ORDER IS PINNED: round each contribution to 2dp first, then sum,
    # then round the sum to 2dp.
    for code, row in latest.items():
        contribution = (
            Decimal(FACTOR_POINTS[code]) / Decimal(present_points)
        ) * RATING_VALUE[row["rating"]]
        total += _round(contribution, TWO_PLACES)
    return _round(total, TWO_PLACES)


# ---------------------------------------------------------------------------
# audience_child_share (PRD §3.1)
# ---------------------------------------------------------------------------
def verified_panel_samples(service_id):
    return [
        e
        for e in db.determination_evidence.values()
        if e["service_id"] == service_id
        and e["evidence_kind"] == "AUDIENCE_SAMPLE"
        and e.get("measurement_method") == "PANEL"
        and e.get("sample_verified") is True
    ]


def audience_child_share(service_id):
    panel = verified_panel_samples(service_id)
    if not panel:
        return None
    numerator = sum(r["users_under_13"] for r in panel)
    denominator = sum(r["total_users"] for r in panel)
    if denominator == 0:
        return None
    return _round(Decimal(numerator) / Decimal(denominator), FOUR_PLACES)


def has_design_factor_evidence(service_id):
    return any(
        e["service_id"] == service_id and e["evidence_kind"] == "DESIGN_FACTOR"
        for e in db.determination_evidence.values()
    )


# ---------------------------------------------------------------------------
# child_directed_determination (PRD §3.2)
# ---------------------------------------------------------------------------
def child_directed_determination(share, score):
    """Returns (determination_status, determination_variant_applied)."""
    if share is not None:  # variant AUDIENCE_FIRST
        if share >= PRIMARY_SHARE_THRESHOLD:
            return "CHILD_DIRECTED_PRIMARY", "AUDIENCE_FIRST"
        if share >= MIXED_SHARE_THRESHOLD:
            return "MIXED_AUDIENCE", "AUDIENCE_FIRST"
        if score >= DESIGN_ESCALATION_THRESHOLD:
            return "MIXED_AUDIENCE", "AUDIENCE_FIRST"
        return "GENERAL_AUDIENCE", "AUDIENCE_FIRST"
    # variant DESIGN_FIRST
    if score >= DESIGN_PRIMARY_THRESHOLD:
        return "CHILD_DIRECTED_PRIMARY", "DESIGN_FIRST"
    if score >= DESIGN_MIXED_THRESHOLD:
        return "MIXED_AUDIENCE", "DESIGN_FIRST"
    return "GENERAL_AUDIENCE", "DESIGN_FIRST"


# ---------------------------------------------------------------------------
# age_screen_neutrality (PRD §3.3)
# ---------------------------------------------------------------------------
def age_screen_neutrality(screen):
    codes = set()
    if screen.get("default_prefilled_age") is not None:
        codes.add("PREFILLED_AGE")
    if screen.get("retry_allowed_on_fail") is True:
        codes.add("RETRY_ALLOWED")
    if screen.get("outcome_session_persisted") is False:
        codes.add("OUTCOME_NOT_PERSISTED")
    if (
        screen.get("mechanism") == "ACCOUNT_AGE_INHERIT"
        and screen.get("inherited_from_verified_account") is False
    ):
        codes.add("UNVERIFIED_INHERIT")
    return [code for code in NEUTRALITY_CODE_ORDER if code in codes]


# ---------------------------------------------------------------------------
# notice_content_completeness (PRD §3.4)
# ---------------------------------------------------------------------------
def missing_content_keys(content_keys):
    present = set(content_keys or [])
    return [key for key in REQUIRED_NOTICE_CONTENT_KEYS if key not in present]


# ---------------------------------------------------------------------------
# required_consent_tier (PRD §3.5)
# ---------------------------------------------------------------------------
def required_consent_tier(service_id, intended_uses):
    base_tier = max(USE_TIER[use] for use in intended_uses)
    bump = 0
    for integration in db.third_party_integrations.values():
        if (
            integration["service_id"] == service_id
            and integration["status"] == "APPROVED"
            and integration["collects_persistent_identifier"] is True
            and integration["integration_type"] in TIER_BUMP_INTEGRATION_TYPES
        ):
            bump = 1
            break
    return min(base_tier + bump, MAX_TIER)


def method_assurance_tier(method):
    return METHOD_ASSURANCE_TIER[method]


# ---------------------------------------------------------------------------
# third_party_exposure_points (PRD §3.7)
# ---------------------------------------------------------------------------
def integration_exposure_points(integration):
    base = INTEGRATION_TYPE_POINTS[integration["integration_type"]]
    return base * (2 if integration["collects_persistent_identifier"] else 1)


def third_party_exposure_points(service_id):
    return sum(
        integration_exposure_points(i)
        for i in db.third_party_integrations.values()
        if i["service_id"] == service_id and i["status"] == "APPROVED"
    )


def open_audit_count(service_id):
    return sum(
        1
        for i in db.third_party_integrations.values()
        if i["service_id"] == service_id and i["status"] == "AUDIT_PENDING"
    )


def published_notice(service_id):
    for notice in db.parental_notices.values():
        if notice["service_id"] == service_id and notice["status"] == "PUBLISHED":
            return notice
    return None


def disclosed_in_notice(integration):
    notice = published_notice(integration["service_id"])
    if notice is None:
        return False
    return integration["vendor_name"] in (notice.get("disclosed_integration_vendors") or [])


# ---------------------------------------------------------------------------
# consent counters (PRD §3.5)
# ---------------------------------------------------------------------------
def active_consent_count(service_id):
    return sum(
        1
        for c in db.consent_requests.values()
        if c["service_id"] == service_id and c["status"] == "GRANTED"
    )


def granted_disclosure_consent_count(service_id):
    total = 0
    for consent in db.consent_requests.values():
        if consent["service_id"] != service_id or consent["status"] != "GRANTED":
            continue
        if any(use in DISCLOSURE_USES for use in consent["intended_uses"]):
            total += 1
    return total


# ---------------------------------------------------------------------------
# child data record counters (PRD §3.6)
# ---------------------------------------------------------------------------
def live_child_data_element_count(service_id):
    return sum(
        1
        for r in db.child_data_records.values()
        if r["service_id"] == service_id and r["status"] in LIVE_RECORD_STATUSES
    )


def lifetime_collected_element_count(service_id):
    return sum(1 for r in db.child_data_records.values() if r["service_id"] == service_id)


# ---------------------------------------------------------------------------
# safe_harbor_status (PRD §3.10)
# ---------------------------------------------------------------------------
def safe_harbor_state(service_id):
    """Returns (safe_harbor_status, safe_harbor_expires_at)."""
    rows = [
        a for a in db.safe_harbor_assessments.values() if a["service_id"] == service_id
    ]
    if not rows:
        return "NOT_ENROLLED", None
    certified = [a for a in rows if a["status"] == "CERTIFIED"]
    if not certified:
        return "ASSESSMENT_DUE", None
    governing = max(
        certified, key=lambda a: (a["assessment_year"], a["certified_at"])
    )
    expires_at = governing["expires_at"]
    current = now()
    if current < expires_at:
        return "CERTIFIED", expires_at
    program = db.safe_harbor_programs.get(governing["program_id"])
    grace_days = program["assessment_grace_days"] if program else 0
    if current < expires_at + timedelta(days=grace_days):
        return "ASSESSMENT_DUE", expires_at
    return "LAPSED", expires_at


# ---------------------------------------------------------------------------
# compliance_posture (PRD §2.5) — STRICTLY ORDERED, first match wins
# ---------------------------------------------------------------------------
def compliance_posture(service):
    if service.get("posture_override") is not None:
        return service["posture_override"]
    service_id = service["id"]
    exposure = third_party_exposure_points(service_id)
    if exposure >= POSTURE_FREEZE_POINTS:
        return "FROZEN"
    if open_audit_count(service_id) >= 1:
        return "RESTRICTED"
    if exposure >= POSTURE_RESTRICT_POINTS:
        return "RESTRICTED"
    status, _ = safe_harbor_state(service_id)
    if status == "LAPSED":
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# rights_request_scope_resolution (PRD §3.8)
# ---------------------------------------------------------------------------
def resolve_rights_scope(consent, scope_mode):
    records = []
    for record in db.child_data_records.values():
        if record["status"] not in LIVE_RECORD_STATUSES:
            continue
        if scope_mode == "PARENT_CONSENT_SCOPE":
            if record["consent_request_id"] == consent["id"]:
                records.append(record)
        else:  # CHILD_IDENTITY_SCOPE
            if (
                record["service_id"] == consent["service_id"]
                and record["child_pseudonym"] == consent["child_pseudonym"]
            ):
                records.append(record)
    # Disposal order within the scope is (collected_at ASC, created_at ASC);
    # id is never used for ordering.
    records.sort(key=lambda r: (r["collected_at"], r["created_at"], r["_seq"]))
    return records


# ---------------------------------------------------------------------------
# record_disposal_schedule (PRD §3.9)
# ---------------------------------------------------------------------------
def effective_retention_schedule(service_id, data_element_code, purpose_code):
    current = now()
    for schedule in db.retention_schedules.values():
        if (
            schedule["service_id"] == service_id
            and schedule["data_element_code"] == data_element_code
            and schedule["purpose_code"] == purpose_code
            and schedule["effective_from"] <= current <= schedule["effective_to"]
        ):
            return schedule
    return None


def disposal_method_permitted(data_element_code, disposal_method):
    return disposal_method in ALLOWED_DISPOSAL_METHODS.get(data_element_code, ())
