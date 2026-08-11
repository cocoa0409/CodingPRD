"""Building the roster: required fields, enums, guarantors and roster capacity."""

from test_helpers import (
    CMRA_OPERATOR,
    UNKNOWN_UUID,
    ApiErrorId,
    activate_box,
    add_recipient,
    assert_recipient,
    create_box,
    create_plan_tier,
    recipient_payload,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_roster_member_without_a_legal_name_is_rejected(api):
    """PRD §3.2: "The payload carries `legal_name`, which must be non-empty and is the
    name exactly as it appears on that member's Form 1583, and `recipient_kind`, one of
    `INDIVIDUAL`, `BUSINESS` and `MINOR`."
    PRD §2.9 rung 9: "Every required body field is present, carries the declared type,
    and sits inside its declared numeric range."

    Design: Corner/entities/recipient_creation_without_legal_name_is_rejected
    """
    plan = create_plan_tier()
    box = create_box("Z-0001", plan["id"], holder_name="Cor Ner", holder_email="cor@example.com")
    activate_box(box["id"])

    response = api.create_recipient(box["id"], {"recipient_kind": "INDIVIDUAL"}, CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(api.list_box_recipients(box["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 0


def test_recipient_kind_outside_the_declared_members_is_an_enum_error(api):
    """PRD §2.9 rung 10: "This rung applies to **exactly** these fields and no others: a
    plan tier's `tier_code`, a carrier rule's `carrier_code`, a roster member's
    `recipient_kind`, a Form 1583's `rejection_reason`, an identification document's
    `doc_class` and `doc_type`, a mail item's `item_class` and `refusal_reason`, a scan
    job's `scan_tier`, a disposition request's `disposition_type`, a forward shipment's
    `service_level`, a compliance review's `reason` and `resolution`, and every
    enum-valued query filter (`handling_status`, `storage_status`, `roster_status`,
    `release_eligibility`, `status`, `unit_type`, `tranche`, `doc_class`, `item_class`,
    `service_status`). Otherwise `ERR_INVALID_ENUM` (400)."

    Design: Corner/entities/recipient_kind_outside_enum_is_rejected
    """
    plan = create_plan_tier()
    box = create_box("Z-0001", plan["id"], holder_name="Cor Ner", holder_email="cor@example.com")
    activate_box(box["id"])

    response = api.create_recipient(
        box["id"],
        {
            "legal_name": "Cee Corp",
            "recipient_kind": "CORPORATION",
            "signature_authorization_on_file": False,
        },
        CMRA_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)


def test_adding_a_roster_member_under_an_unknown_mailbox_is_a_not_found(api):
    """PRD §2.9 rung 3: "The first templated resource named in the path exists."
    PRD §2.9: "Every request is evaluated against the following 36 rungs **in strictly
    ascending numeric order**, and the first rung that fails determines the response."

    Design: Corner/entities/recipient_creation_under_unknown_box_returns_not_found
    """
    create_plan_tier()

    response = api.create_recipient(
        UNKNOWN_UUID,
        recipient_payload("Eve Ghost"),
        CMRA_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_BOX_NOT_FOUND.value)


def test_minors_and_adults_are_both_policed_by_the_guarantor_rule(api):
    """PRD §3.2: "The guarantor rule is symmetric and strict: a member of
    `recipient_kind` `MINOR` **must** carry a `guarantor_recipient_id` pointing at a
    member of the same mailbox whose `recipient_kind` is not `MINOR`, and a member of
    any other kind **must not** carry one."
    PRD §3.2: "Either violation is `ERR_GUARANTOR_REQUIRED`."

    Design: Corner/validations/minor_without_a_guarantor_is_rejected
    """
    ctx = setup_releasable_box("Z-3005", "Eli Adult", holder_email="eli@example.com")

    minor_without_guarantor = api.create_recipient(
        ctx["box_id"],
        {
            "legal_name": "Fin Minor",
            "recipient_kind": "MINOR",
            "signature_authorization_on_file": False,
        },
        CMRA_OPERATOR,
    )
    validate_error(minor_without_guarantor, ApiErrorId.ERR_GUARANTOR_REQUIRED.value)

    adult_with_guarantor = api.create_recipient(
        ctx["box_id"],
        {
            "legal_name": "Gal Adult",
            "recipient_kind": "INDIVIDUAL",
            "guarantor_recipient_id": ctx["recipient_id"],
            "signature_authorization_on_file": False,
        },
        CMRA_OPERATOR,
    )
    validate_error(adult_with_guarantor, ApiErrorId.ERR_GUARANTOR_REQUIRED.value)

    _, meta = validate_paginated(api.list_box_recipients(ctx["box_id"], CMRA_OPERATOR))
    assert meta["total_count"] == 1


def test_roster_capacity_binds_at_the_effective_cap_and_a_removal_frees_a_slot(api):
    """PRD §3.2: "The effective cap is the smaller of two numbers: the tier's
    `included_recipients` plus the mailbox's `extra_recipient_slots` on one side, and the
    USPS statutory ceiling of 12 members per mailbox on the other."
    PRD §3.2: "The create is rejected with `ERR_ROSTER_CAP_EXCEEDED` when occupancy is
    **greater than or equal to** the effective cap — so with an effective cap of 3 the
    third create succeeds and the fourth is rejected."
    PRD §3.2: "Occupancy is the count of members on the mailbox whose `roster_status` is
    `PENDING`, `AUTHORIZED` or `SUSPENDED`; members at `REMOVED` do not occupy a slot and
    their removal frees it for reuse."

    Design: Corner/calculations/roster_capacity_uses_the_min_of_plan_slots_and_usps_cap
    """
    plan = create_plan_tier()
    box = create_box("Z-2005", plan["id"], holder_name="Wyn Full", holder_email="wyn@example.com")
    activate_box(box["id"])
    add_recipient(box["id"], "One Person")
    add_recipient(box["id"], "Two Person")
    third = add_recipient(box["id"], "Three Person", recipient_kind="BUSINESS")

    over_cap = api.create_recipient(
        box["id"], recipient_payload("Four Person"), CMRA_OPERATOR
    )
    validate_error(over_cap, ApiErrorId.ERR_ROSTER_CAP_EXCEEDED.value)

    removed = validate_success(api.remove_recipient(third["id"], CMRA_OPERATOR))
    assert removed["roster_status"] == "REMOVED"

    retried = api.create_recipient(box["id"], recipient_payload("Four Person"), CMRA_OPERATOR)
    fourth = validate_success(retried, 201)
    assert fourth["roster_status"] == "PENDING"

    _, meta = validate_paginated(api.list_box_recipients(box["id"], CMRA_OPERATOR))
    assert meta["total_count"] == 4


def test_minors_are_discoverable_through_the_guarantor_filter(api):
    """PRD §3.2: "Roster members may be listed per mailbox filtered by `roster_status`,
    and across mailboxes filtered by `box_id`, `guarantor_recipient_id`, `roster_status`
    and `release_eligibility`."
    PRD §3.2: "The pointer is self-referential — a roster member referring to another
    roster member on the same roster."

    Design: Corner/entities/guarantor_self_reference_is_discoverable_by_filtered_list
    """
    ctx = setup_releasable_box("Z-0007", "Fay Guard", holder_email="fay2@example.com")
    minor = add_recipient(
        ctx["box_id"],
        "Gus Minor",
        recipient_kind="MINOR",
        guarantor_recipient_id=ctx["recipient_id"],
    )

    response = api.list_recipients(
        CMRA_OPERATOR, params={"guarantor_recipient_id": ctx["recipient_id"]}
    )
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == minor["id"]
    assert rows[0]["recipient_kind"] == "MINOR"
    assert_recipient(rows[0])
    assert rows[0]["guarantor_recipient_id"] == ctx["recipient_id"]
