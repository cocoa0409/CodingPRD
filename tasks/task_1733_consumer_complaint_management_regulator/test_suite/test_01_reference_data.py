"""Reference-data entity tests: products, channels, taxonomy, intake events (PRD §3.1, §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, headers_for,
    assert_product, assert_channel, assert_taxonomy_category, assert_complaint,
    assert_intake_event,
    create_product, create_channel, create_category, retire_category,
    setup_reference_data, intake_complaint, list_complaint_referrals,
    list_complaint_events, get_complaint,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


def test_product_creation_defaults_posture_open_zero_counters(api):
    """PRD §3.1: "At creation its intake-gating `posture` is `OPEN`,
    `open_complaint_count` is 0, `substantiated_count_90d` is 0, and
    `early_warning_active` is false; all four derived attributes then track the
    product's complaint traffic for the rest of its life (see §3.8)."
    PRD §2.4: "`version` starts at 1 at creation and increments by exactly 1 on
    every mutation of that resource, giving clients a cheap
    optimistic-concurrency signal and giving the audit trail a stable ordering."

    Design: Corner/entities/product_creation_defaults_posture_open_zero_counters
    """
    created = validate_success(
        api.create_product({"product_code": "P-INIT", "display_name": "Init Product"},
                           MANAGER),
        expected_status=201,
    )
    assert_product(created)
    fetched = validate_success(api.get_product(created["id"], AUDITOR))
    assert_product(fetched)
    assert fetched["posture"] == "OPEN", f"expected OPEN posture, got {fetched['posture']}"
    assert fetched["open_complaint_count"] == 0
    assert fetched["substantiated_count_90d"] == 0
    assert fetched["early_warning_active"] is False
    assert fetched["version"] == 1, f"expected version 1, got {fetched['version']}"


def test_channel_default_is_regulator_portal_false(api):
    """PRD §3.1: "The boolean `is_regulator_portal`, defaulting to false, marks
    channels whose complaints are legally referrals: when a complaint arrives on
    such a channel, a `RegulatoryReferral` is created atomically in the same
    intake request (see §3.2)."

    Design: Corner/entities/channel_default_is_regulator_portal_false
    """
    channel = validate_success(
        api.create_channel({"channel_code": "WEB", "display_name": "Web"}, MANAGER),
        expected_status=201,
    )
    assert_channel(channel)
    assert channel["is_regulator_portal"] is False, (
        "omitted is_regulator_portal must default to false"
    )
    create_product("P-CH")
    create_category("C.CH")
    complaint = intake_complaint("P-CH", "WEB", "C.CH", narrative="no portal")
    referrals = list_complaint_referrals(complaint["id"])
    assert referrals == [], (
        f"non-portal channel intake must not auto-create a referral, got {referrals}"
    )


def test_complaint_missing_required_field_rejected(api):
    """PRD §3.2: "An `IntakeSpecialist` or `CaseHandler` intakes a complaint by
    supplying `complainant_ref` (an opaque external customer reference),
    `channel_code`, `product_code`, `category_code`, a free-text `narrative`, an
    optional `claimed_loss_cents` (the alleged monetary loss in integer cents,
    defaulting to 0 and never negative), and an optional `portal_ref`."
    PRD §2.6: "4. **Request shape** — required request-body fields must be
    present and correctly typed, enum members must be valid, integer ranges are
    enforced (`claimed_loss_cents` must be at least 0, each line item's
    `amount_cents` must be at least 0), and a quality-review window's
    `window_end_at` must lie strictly after its `window_start_at`; otherwise
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/complaint_missing_required_field_rejected
    """
    setup_reference_data("P-REQ", "WEB", "C.REQ")
    response = api.create_complaint(
        {"complainant_ref": "CU-REQ", "channel_code": "WEB",
         "product_code": "P-REQ", "category_code": "C.REQ"},
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_complaint_get_not_found(api):
    """PRD §2.6: "3. **Existence** — path-template identifiers are validated left
    to right along nested URLs, and business codes referenced in the request body
    must resolve to live records; otherwise `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/complaint_get_not_found
    """
    response = api.get_complaint(NON_EXISTENT_UUID, AUDITOR)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_complaint_claimed_loss_defaults_zero_and_negative_rejected(api):
    """PRD §3.2: "An `IntakeSpecialist` or `CaseHandler` intakes a complaint by
    supplying `complainant_ref` (an opaque external customer reference),
    `channel_code`, `product_code`, `category_code`, a free-text `narrative`, an
    optional `claimed_loss_cents` (the alleged monetary loss in integer cents,
    defaulting to 0 and never negative), and an optional `portal_ref`."
    PRD §2.6: "4. **Request shape** — required request-body fields must be
    present and correctly typed, enum members must be valid, integer ranges are
    enforced (`claimed_loss_cents` must be at least 0, each line item's
    `amount_cents` must be at least 0), and a quality-review window's
    `window_end_at` must lie strictly after its `window_start_at`; otherwise
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/complaint_claimed_loss_defaults_zero_and_negative_rejected
    """
    setup_reference_data("P-LOSS", "WEB", "C.LOSS")
    complaint = intake_complaint("P-LOSS", "WEB", "C.LOSS", narrative="no loss stated")
    assert_complaint(complaint)
    assert complaint["claimed_loss_cents"] == 0, (
        f"omitted claimed_loss_cents must default to 0, got {complaint['claimed_loss_cents']}"
    )

    response = api.create_complaint(
        {"complainant_ref": "CU-L2", "channel_code": "WEB", "product_code": "P-LOSS",
         "category_code": "C.LOSS", "narrative": "neg", "claimed_loss_cents": -1},
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_intake_event_immutable_no_update_endpoint(api):
    """PRD §3.2: "A successful intake stamps `received_at` from the logical
    clock, sets `status` to `INTAKE`, records the acting `X-User-ID` as
    `owner_user_id` (the anchor for later segregation-of-duties checks),
    initializes `version` at 1, appends a `CREATED` audit event, increments the
    product's `open_complaint_count` by 1, and recomputes the product's
    `posture`."
    PRD §2.10: "Each event carries `complaint_id`, an `event_type` drawn from the
    fifteen declared values above, the acting operator's `actor_user_id` and
    `actor_role`, an event-specific structured `payload` capturing old and new
    values, and `event_at` stamped from the logical clock when the event is
    appended."
    PRD §2.4: "Two resource kinds deliberately carry a lighter footprint because
    they are append-only audit or point-in-time reporting records: `IntakeEvent`
    and `TrendSnapshot` expose `id` and `created_at` only — both `updated_at`
    and `version` are absent on these two."

    Design: Corner/entities/intake_event_immutable_no_update_endpoint
    """
    setup_reference_data("P-EV", "WEB", "C.EV")
    complaint = intake_complaint("P-EV", "WEB", "C.EV", narrative="audit me",
                                 user_id="user_ev_1")
    events = list_complaint_events(complaint["id"])
    assert len(events) == 1, f"expected exactly 1 CREATED event, got {len(events)}"
    event = events[0]
    assert_intake_event(event)
    assert event["event_type"] == "CREATED"
    assert event["actor_user_id"] == "user_ev_1"
    assert event["actor_role"] == "IntakeSpecialist"


def test_taxonomy_self_referential_parent_link(api):
    """PRD §3.1: "A `TaxonomyCategory` is created with a unique `category_code`
    (for example, FEES.OVERDRAFT) and an optional `parent_category_code` naming
    another category's code; a null `parent_category_code` marks a root."
    PRD §4: "| GET | /complaint-office/taxonomy-categories | List
    TaxonomyCategories (optional `parent_category_code`, `retired` filters) |
    ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer,
    RemediationApprover, ExecutiveReviewer, Auditor |"

    Design: Corner/entities/taxonomy_self_referential_parent_link
    """
    root = validate_success(
        api.create_taxonomy_category({"category_code": "FEES"}, MANAGER),
        expected_status=201,
    )
    validate_success(
        api.create_taxonomy_category(
            {"category_code": "FEES.OVERDRAFT", "parent_category_code": "FEES"}, MANAGER,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_taxonomy_category(
            {"category_code": "FEES.ATM", "parent_category_code": "FEES"}, MANAGER,
        ),
        expected_status=201,
    )
    children, meta = validate_paginated(
        api.list_taxonomy_categories(AUDITOR, params={"parent_category_code": "FEES"})
    )
    child_codes = sorted(c["category_code"] for c in children)
    assert child_codes == ["FEES.ATM", "FEES.OVERDRAFT"], (
        f"parent filter must return exactly the two children, got {child_codes}"
    )
    assert meta["total_count"] == 2

    fetched_root = validate_success(api.get_taxonomy_category(root["id"], AUDITOR))
    assert_taxonomy_category(fetched_root)
    assert fetched_root.get("parent_category_code") is None, (
        "a root category carries a null parent_category_code"
    )
