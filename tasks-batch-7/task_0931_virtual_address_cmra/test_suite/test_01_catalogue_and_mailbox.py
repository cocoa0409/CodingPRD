"""The plan-tier / carrier-rule catalogues, opening a mailbox and putting it into service."""

from test_helpers import (
    CMRA_OPERATOR,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    UNKNOWN_UUID,
    UNKNOWN_UUID_3,
    ApiErrorId,
    activate_box,
    assert_bare_uuid,
    assert_box,
    assert_billing_cycle,
    assert_custody_cardinality,
    assert_plan_tier,
    assert_same_instant,
    box_payload,
    create_box,
    create_plan_tier,
    letter_payload,
    log_and_match_letter,
    log_mail_item,
    make_box_holder_headers,
    open_billing_cycle,
    plan_tier_payload,
    recipient_payload,
    set_clock,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plan_tier_creation_echoes_every_declared_field(api):
    """PRD §3.1: "A **plan tier** is created with a `tier_code` drawn from `BASIC`,
    `PLUS`, `BUSINESS` and `ENTERPRISE` — each code may exist only once — a
    human-readable `name`, and a `rank` between 1 and 4 inclusive which must also be
    unique across the catalogue; a higher `rank` means a richer tier, and the
    comparison of ranks is the only thing that decides whether a later plan change
    counts as an upgrade or a downgrade."
    PRD §3.1: "A final flag, `allows_overage`, defaults to true; when it is set false,
    any request that would consume a unit beyond the included quota is rejected
    outright with `ERR_QUOTA_EXHAUSTED` instead of being metered."

    Design: Corner/entities/plan_tier_creation_returns_every_declared_field
    """
    payload = plan_tier_payload()
    response = api.create_plan_tier(payload, PLATFORM_ADMIN)
    tier = validate_success(response, 201)

    assert_plan_tier(tier)
    assert tier["tier_code"] == "PLUS"
    assert tier["rank"] == 2
    assert tier["monthly_fee_cents"] == 6000
    assert tier["included_scan_pages"] == 50
    assert tier["overage_storage_day_cents"] == 30
    assert tier["allows_overage"] is True


def test_reading_a_mailbox_that_does_not_exist_returns_box_not_found(api):
    """PRD §2.9 rung 3: "The first templated resource named in the path exists. The
    error is the one belonging to that resource type: `ERR_BOX_NOT_FOUND`,
    `ERR_RECIPIENT_NOT_FOUND`, `ERR_FORM_1583_NOT_FOUND`, `ERR_ID_DOCUMENT_NOT_FOUND`,
    `ERR_MAIL_ITEM_NOT_FOUND`, `ERR_SCAN_JOB_NOT_FOUND`, `ERR_DISPOSITION_NOT_FOUND`,
    `ERR_FORWARD_SHIPMENT_NOT_FOUND`, `ERR_DEPOSIT_BATCH_NOT_FOUND`,
    `ERR_CHECK_DEPOSIT_NOT_FOUND`, `ERR_COMPLIANCE_REVIEW_NOT_FOUND` or
    `ERR_BILLING_CYCLE_NOT_FOUND`, each at HTTP 404."

    Design: Corner/entities/box_retrieval_by_unknown_id_returns_box_not_found
    """
    plan = create_plan_tier()
    create_box("Z-0001", plan["id"], holder_name="Cor Ner", holder_email="cor@example.com")

    response = api.get_box(UNKNOWN_UUID, CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_BOX_NOT_FOUND.value)


def test_mailbox_listing_carries_the_pagination_envelope(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, has a minimum of 1 and a
    maximum of 100; `offset` defaults to 0 and has a minimum of 0."
    PRD §2.3: "`total_count` is the number of rows matching the filters before `limit`
    and `offset` are applied; `has_more` is true when the sum of `offset` and the number
    of rows actually returned is less than `total_count`, and false otherwise."

    Design: Corner/entities/box_list_returns_pagination_envelope_fields
    """
    plan = create_plan_tier()
    create_box("Z-0001", plan["id"], holder_name="Cor Ner", holder_email="cor@example.com")
    create_box("Z-0002", plan["id"], holder_name="Two Ner", holder_email="two@example.com")

    response = api.list_boxes(
        CMRA_OPERATOR, params={"plan_tier_id": plan["id"], "limit": 1, "offset": 0}
    )
    boxes, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(boxes) == 1


def test_optional_money_and_slot_fields_default_to_zero(api):
    """PRD §3.1: "Three optional money-and-slot fields all default to 0:
    `security_deposit_cents`, a refundable deposit that later enters the cancellation
    refund waterfall; `extra_recipient_slots`, purchased roster capacity stacked on top
    of the tier's `included_recipients`; and `prepaid_balance_cents`, credit on the
    account which cycle charges draw down."
    PRD §3.1: "A newly opened mailbox lands in `service_status` `PENDING_SETUP`,
    `compliance_status` `COMPLIANT`, `suspended_reason` `NONE` and, by the derivation in
    §2.8, `release_gate_state` `GATED_LIFECYCLE`."

    Design: Corner/entities/box_optional_money_fields_default_to_zero
    """
    plan = create_plan_tier()
    response = api.create_box(
        {
            "box_number": "Z-0003",
            "plan_tier_id": plan["id"],
            "holder_name": "Def Ault",
            "holder_email": "def@example.com",
        },
        CMRA_OPERATOR,
    )
    box = validate_success(response, 201)

    assert_box(box)
    assert box["security_deposit_cents"] == 0
    assert box["extra_recipient_slots"] == 0
    assert box["prepaid_balance_cents"] == 0
    assert box["service_status"] == "PENDING_SETUP"
    assert box["compliance_status"] == "COMPLIANT"
    assert box["suspended_reason"] == "NONE"
    assert box["version"] == 1


def test_roster_authorized_count_is_derived_from_the_roster(api):
    """PRD §3.1: "`roster_authorized_count` is the number of roster members on the
    mailbox whose `roster_status` is `AUTHORIZED`."
    PRD §3.1: "`outstanding_overage_cents` is the sum of `amount_cents` over every
    usage-ledger entry of this mailbox whose `tranche` is `OVERAGE` and whose owning
    billing cycle is still `OPEN`."

    Design: Corner/entities/box_roster_authorized_count_is_computed_not_input
    """
    ctx = setup_releasable_box("Z-0004", "Ada Count", holder_email="ada@example.com")

    box = validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))
    assert box["roster_authorized_count"] == 1
    assert box["release_gate_state"] == "OPEN"
    assert box["outstanding_overage_cents"] == 0


def test_opening_a_mailbox_on_an_unknown_plan_tier_is_rejected(api):
    """PRD §2.9 rung 5: "A `plan_tier_id` or `new_plan_tier_id` supplied in the body
    resolves to a plan tier. Otherwise `ERR_PLAN_TIER_NOT_FOUND` (404). Applies to
    `POST /boxes` and `POST /boxes/{id}/plan-change`."

    Design: Corner/errors/error_plan_tier_not_found_on_unknown_body_fk
    """
    validate_paginated(api.list_plan_tiers(PLATFORM_ADMIN))

    response = api.create_box(
        {
            "box_number": "Z-5002",
            "plan_tier_id": UNKNOWN_UUID_3,
            "holder_name": "Vi Ghost",
            "holder_email": "vi@example.com",
        },
        CMRA_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_PLAN_TIER_NOT_FOUND.value)


def test_activation_creates_the_first_billing_cycle_with_pinned_dates(api):
    """PRD §3.1: "It stamps `activated_at` with the current logical-clock instant."
    PRD §3.1: "It creates the first billing cycle, with `cycle_index` 1, status `OPEN`,
    `period_start` equal to `cycle_anchor_date` and `period_end` equal to `period_start`
    plus 30 days — `period_start` is the inclusive first date of the cycle and
    `period_end` the exclusive last, so every subsequent cycle's `period_start` is
    `cycle_anchor_date` plus a whole multiple of 30 days."

    Design: Corner/state_machines/activation_creates_the_first_billing_cycle_with_pinned_dates
    """
    plan = create_plan_tier()
    box = create_box("Z-1002", plan["id"], holder_name="Jan Cycle", holder_email="jan@example.com")

    activated = validate_success(api.activate_box(box["id"], CMRA_OPERATOR))
    assert activated["service_status"] == "ACTIVE"
    assert_same_instant(activated["activated_at"], "2026-05-01T00:00:00.000Z", "activated_at")
    assert activated["cycle_anchor_date"] == "2026-05-01"

    cycles, _ = validate_paginated(api.list_billing_cycles(box["id"], CMRA_OPERATOR))
    cycle = cycles[0]
    assert_billing_cycle(cycle)
    assert cycle["cycle_index"] == 1
    assert cycle["status"] == "OPEN"
    assert cycle["period_start"] == "2026-05-01"
    assert cycle["period_end"] == "2026-05-31"
    assert cycle["scan_pages_consumed"] == 0
    assert cycle["forwards_consumed"] == 0
    assert cycle["storage_days_consumed"] == 0
    assert cycle["recipients_consumed"] == 0


def test_activating_an_already_active_mailbox_is_rejected(api):
    """PRD §3.1: "Putting the mailbox into service — the transition
    `PENDING_SETUP → ACTIVE`, permitted only from `PENDING_SETUP` — is likewise a
    `CmraOperator` act and does four things at once."
    PRD §2.9 rung 14: "The target resource sits in a state from which the requested
    transition is declared. Otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/activating_an_already_active_box_is_rejected
    """
    plan = create_plan_tier()
    box = create_box("Z-1001", plan["id"], holder_name="Ida Twice", holder_email="ida@example.com")
    activate_box(box["id"])

    response = api.activate_box(box["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert validate_success(api.get_box(box["id"], CMRA_OPERATOR))["service_status"] == "ACTIVE"
    _, meta = validate_paginated(api.list_billing_cycles(box["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 1


def test_lifecycle_gate_blocks_inbound_mail_but_permits_a_roster_member(api):
    """PRD §2.8: "Its condition is that the target mailbox has `service_status` equal to
    `PENDING_SETUP` or `CLOSED`. It is evaluated at rung 12, immediately after Gate A,
    and blocks every write under a `/boxes/{id}/` path and every write on a resource
    whose owning box is in one of those two states, with two exceptions:
    `POST /boxes/{id}/activate` and `POST /boxes/{id}/recipients` remain permitted. The
    rejection is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/validations/writes_on_a_pending_setup_box_hit_the_lifecycle_gate
    """
    plan = create_plan_tier()
    box = create_box("Z-3012", plan["id"], holder_name="Ozy Setup", holder_email="ozy@example.com")

    blocked = api.create_mail_item(box["id"], letter_payload("Ozy Setup"), CMRA_OPERATOR)
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_box(box["id"], CMRA_OPERATOR))["release_gate_state"] == (
        "GATED_LIFECYCLE"
    )

    permitted = api.create_recipient(
        box["id"], recipient_payload("Ozy Setup"), CMRA_OPERATOR
    )
    recipient = validate_success(permitted, 201)
    assert recipient["roster_status"] == "PENDING"


def test_mailbox_summary_reports_gate_state_and_custody_cardinality(api):
    """PRD §3.1: "It reports `box_id`, `service_status`, `compliance_status`,
    `release_gate_state`, `roster_authorized_count`, `open_billing_cycle_id`, the four
    quota counters of the open cycle (`scan_pages_consumed`, `forwards_consumed`,
    `storage_days_consumed`, `recipients_consumed`), `outstanding_overage_cents`, and
    the three custody buckets `items_in_custody`, `items_released` and
    `items_destroyed`."
    PRD §3.1: "`items_in_custody` counts pieces whose `storage_status` is `FREE_WINDOW`
    or `ACCRUING`, `items_released` counts those at `RELEASED`, and `items_destroyed`
    counts those at `DESTROYED`; by the custody invariant of §2.11 the three sum to the
    mailbox's total piece count."

    Design: Corner/endpoints/box_summary_reports_gate_state_and_custody_cardinality
    """
    ctx = setup_releasable_box("Z-4001", "Qui Sum", holder_email="qui@example.com")
    log_and_match_letter(ctx)
    stray = log_mail_item(ctx["box_id"], letter_payload("Stray Name"))
    validate_success(
        api.refuse_mail_item(stray["id"], {"refusal_reason": "NOT_ON_ROSTER"}, CMRA_OPERATOR)
    )

    response = api.get_box_summary(ctx["box_id"], make_box_holder_headers(ctx["box_id"]))
    summary = validate_success(response)
    assert response.json()["response_type"] == "object"

    assert summary["box_id"] == ctx["box_id"]
    assert summary["service_status"] == "ACTIVE"
    assert summary["compliance_status"] == "COMPLIANT"
    assert summary["release_gate_state"] == "OPEN"
    assert summary["roster_authorized_count"] == 1
    assert summary["recipients_consumed"] == 1
    assert summary["items_in_custody"] == 1
    assert summary["items_released"] == 1
    assert summary["items_destroyed"] == 0
    assert_custody_cardinality(summary, 2)
    assert summary["scan_pages_consumed"] == 0
    assert summary["forwards_consumed"] == 0
    assert summary["storage_days_consumed"] == 0
    assert summary["outstanding_overage_cents"] == 0


def test_logical_clock_starts_at_the_pinned_instant_and_moves_only_when_set(api):
    """PRD §2.5: "The server holds a single logical clock which, before any
    administrator has moved it, reads exactly `2026-05-01T00:00:00Z`."
    PRD §3.4: "Intake stamps `received_at` from the logical clock and sets all four
    status axes to their initial values: `handling_status` `RECEIVED`, `storage_status`
    `FREE_WINDOW`, `billing_status` `UNBILLED` and `notification_status`
    `NOT_REQUIRED`."

    Design: Corner/endpoints/clock_endpoint_defaults_to_the_pinned_startup_instant
    """
    ctx = setup_releasable_box("Z-4004", "Tim Clock", holder_email="tim@example.com")

    first = validate_success(
        api.create_mail_item(ctx["box_id"], letter_payload("Tim Clock"), CMRA_OPERATOR), 201
    )
    assert_same_instant(first["received_at"], "2026-05-01T00:00:00.000Z", "received_at")
    box = validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))
    assert_same_instant(box["activated_at"], "2026-05-01T00:00:00.000Z", "activated_at")

    set_clock("2026-08-01T12:00:00Z")
    second = validate_success(
        api.create_mail_item(ctx["box_id"], letter_payload("Tim Clock"), CMRA_OPERATOR), 201
    )
    assert_same_instant(second["received_at"], "2026-08-01T12:00:00.000Z", "received_at")


def test_box_version_advances_by_exactly_one_per_mutating_request(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is created."
    PRD §2.4: "**It is bumped exactly once per row per request that mutates that row**,
    never once per side effect."

    Design: Corner/cross_cutting_complexity_layers/version_increments_by_exactly_one_on_every_mutation
    """
    plan = create_plan_tier()
    created = validate_success(
        api.create_box(
            box_payload("Z-7004", plan["id"], holder_name="Fox Ver", holder_email="fox@example.com"),
            CMRA_OPERATOR,
        ),
        201,
    )
    assert created["version"] == 1

    activated = validate_success(api.activate_box(created["id"], CMRA_OPERATOR))
    assert activated["version"] == 2

    validate_success(
        api.create_compliance_review(
            created["id"], {"reason": "ID_EXPIRY"}, COMPLIANCE_OFFICER
        ),
        201,
    )
    reread = validate_success(api.get_box(created["id"], CMRA_OPERATOR))
    assert reread["version"] == 3
    assert reread["compliance_status"] == "UNDER_REVIEW"


def test_mail_item_intake_stamps_the_clock_and_a_bare_uuid(api):
    """PRD §2.4: "Every persisted resource carries an `id`, which is a server-minted
    UUID string with no type prefix, and a `created_at`."
    PRD §3.4: "It also sets `billable_weight_lb` to `actual_weight_lb` for every piece
    regardless of class; for packages and service-of-process pieces that value is
    recomputed later at acceptance."

    Design: Corner/entities/mail_item_received_at_and_ids_are_system_stamped
    """
    ctx = setup_releasable_box("Z-0005", "Ben Stamp", holder_email="ben@example.com")

    item = validate_success(
        api.create_mail_item(ctx["box_id"], letter_payload("Ben Stamp"), CMRA_OPERATOR), 201
    )
    assert_same_instant(item["received_at"], "2026-05-01T00:00:00.000Z", "received_at")
    assert_bare_uuid(item["id"], "mail item id")
    assert item["version"] == 1
    assert item["handling_status"] == "RECEIVED"
    assert item["storage_status"] == "FREE_WINDOW"
    assert item["billing_status"] == "UNBILLED"
    assert item["notification_status"] == "NOT_REQUIRED"
    assert item["billable_weight_lb"] == 0.1
    assert open_billing_cycle(ctx["box_id"])["status"] == "OPEN"
