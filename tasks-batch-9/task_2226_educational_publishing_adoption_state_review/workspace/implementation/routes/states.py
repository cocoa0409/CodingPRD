"""StateProfile and StateStandard endpoints (PRD 3.1)."""

from decimal import Decimal

import domain
import serializers as S
import validation as V
from db import base_record, db
from errors import fail
from middleware import authorize, check_state_scope
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("states", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "StateAdoptionOfficer",
    "PublisherEditor",
    "EditorialDirector",
    "PricingManager",
    "SalesRep",
    "ReviewCommitteeMember",
)

STANDARD_LIST_ROLES = (
    "PlatformAdmin",
    "StateAdoptionOfficer",
    "PublisherEditor",
    "EditorialDirector",
    "ReviewCommitteeMember",
)


@bp.post("/state-profiles")
def create_state_profile():
    authorize(("PlatformAdmin",))
    payload = V.body()

    state_code = V.get_str(
        payload, "state_code", exact_len=2, pattern=V.STATE_CODE_RE
    )
    adoption_model = V.get_enum(payload, "adoption_model", V.ADOPTION_MODELS)
    sampling_copies_required = V.get_int(
        payload, "sampling_copies_required", minimum=0, maximum=50,
        required=False, default=0,
    )
    comment_response_days = V.get_int(
        payload, "comment_response_days", minimum=1, maximum=60,
        required=False, default=10,
    )
    required_topics = V.get_code_array(payload, "required_topics", 20)
    prohibited_content_tags = V.get_code_array(
        payload, "prohibited_content_tags", 20
    )
    multi_year_max_years = V.get_int(
        payload, "multi_year_max_years", minimum=1, maximum=10,
        required=False, default=6,
    )
    price_cap_cents = V.get_int(
        payload, "price_cap_cents", minimum=1, required=False, default=None
    )
    min_verified_coverage_pct = V.get_decimal(
        payload, "min_verified_coverage_pct", minimum=0, maximum=100,
        required=False, default=Decimal("85.00"),
    )
    accessibility_standard = V.get_enum(
        payload, "accessibility_standard", V.ACCESSIBILITY_STANDARDS,
        required=False, default="WCAG_2_1_AA",
    )
    rostering_standard = V.get_enum(
        payload, "rostering_standard", V.ROSTERING_STANDARDS,
        required=False, default="ONEROSTER_1_2",
    )
    data_privacy_addendum_required = V.get_bool(
        payload, "data_privacy_addendum_required", required=False, default=True
    )

    for existing in db.state_profiles.values():
        if existing["state_code"] == state_code:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "State code %s is already registered." % state_code,
            )

    record = base_record()
    record.update(
        {
            "state_code": state_code,
            "adoption_model": adoption_model,
            "sampling_copies_required": sampling_copies_required,
            "comment_response_days": comment_response_days,
            "required_topics": required_topics,
            "prohibited_content_tags": prohibited_content_tags,
            "multi_year_max_years": multi_year_max_years,
            "price_cap_cents": price_cap_cents,
            "min_verified_coverage_pct": min_verified_coverage_pct,
            "accessibility_standard": accessibility_standard,
            "rostering_standard": rostering_standard,
            "data_privacy_addendum_required": data_privacy_addendum_required,
        }
    )
    db.state_profiles[record["id"]] = record
    return respond(S.serialize(record, S.STATE_PROFILE_FIELDS), 201)


@bp.get("/state-profiles/<state_id>")
def get_state_profile(state_id):
    authorize(READ_ROLES)
    record = domain.find_state(state_id)
    return respond(S.serialize(record, S.STATE_PROFILE_FIELDS))


@bp.post("/state-profiles/<state_id>/standards")
def create_standard(state_id):
    user_id, role = authorize(("PlatformAdmin", "StateAdoptionOfficer"))
    payload = V.body()

    subject = V.get_enum(payload, "subject", V.SUBJECTS)
    standard_code = V.get_str(payload, "standard_code", min_len=1, max_len=40)
    grade_low = V.get_int(payload, "grade_low", minimum=0, maximum=12)
    grade_high = V.get_int(payload, "grade_high", minimum=0, maximum=12)
    if grade_low > grade_high:
        fail("ERR_INVALID_REQUEST", "grade_low must not exceed grade_high.")
    weight = V.get_int(payload, "weight", minimum=1, maximum=5)
    is_focus = V.get_bool(payload, "is_focus", required=False, default=False)

    domain.find_state(state_id)
    check_state_scope(role, user_id, state_id)

    for existing in db.state_standards.values():
        if (
            existing["state_id"] == state_id
            and existing["subject"] == subject
            and existing["standard_code"] == standard_code
        ):
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "Standard %s already exists for this state and subject."
                % standard_code,
            )

    record = base_record(with_version=False)
    record.update(
        {
            "state_id": state_id,
            "subject": subject,
            "standard_code": standard_code,
            "grade_low": grade_low,
            "grade_high": grade_high,
            "weight": weight,
            "is_focus": is_focus,
        }
    )
    db.state_standards[record["id"]] = record
    return respond(S.serialize(record, S.STATE_STANDARD_FIELDS), 201)


@bp.get("/state-profiles/<state_id>/standards")
def list_standards(state_id):
    authorize(STANDARD_LIST_ROLES)
    limit, offset = V.pagination()
    subject = V.query_enum("subject", V.SUBJECTS)
    is_focus = V.query_bool("is_focus")

    domain.find_state(state_id)

    items = domain.standards_of_state(state_id)
    if subject is not None:
        items = [i for i in items if i["subject"] == subject]
    if is_focus is not None:
        items = [i for i in items if i["is_focus"] == is_focus]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.STATE_STANDARD_FIELDS), total, limit, offset
    )
