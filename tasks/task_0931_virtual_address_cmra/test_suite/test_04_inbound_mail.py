"""Inbound mail: intake, roster matching, refusal and the piece listings."""

from test_helpers import (
    CMRA_OPERATOR,
    UNKNOWN_UUID_4,
    ApiErrorId,
    assert_mail_item,
    assert_same_instant,
    letter_payload,
    log_and_match_letter,
    log_mail_item,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_refusing_a_piece_advances_three_axes_in_one_write(api):
    """PRD §3.4: "Refusal is a three-axis event: `handling_status` goes
    `RECEIVED → REFUSED`, which is terminal; `storage_status` moves to `RELEASED` with
    `released_at` stamped from the clock; and `billing_status`, if it was still
    `UNBILLED`, moves to `WRITTEN_OFF`."
    PRD §3.4: "A `CmraOperator` refuses a piece with a `refusal_reason` drawn from
    `NOT_ON_ROSTER`, `OVERSIZE`, `CARRIER_NOT_ACCEPTED` and `HOLDER_REQUEST`; the field
    is required on refusal and null otherwise."

    Design: Corner/state_machines/refusing_a_piece_moves_three_axes_in_one_write
    """
    ctx = setup_releasable_box("Z-1005", "Moe Refuse", holder_email="moe@example.com")
    item = log_mail_item(ctx["box_id"], letter_payload("Not On Roster"))

    response = api.refuse_mail_item(
        item["id"], {"refusal_reason": "NOT_ON_ROSTER"}, CMRA_OPERATOR
    )
    refused = validate_success(response)

    assert_mail_item(refused)
    assert refused["handling_status"] == "REFUSED"
    assert refused["storage_status"] == "RELEASED"
    assert refused["billing_status"] == "WRITTEN_OFF"
    assert refused["refusal_reason"] == "NOT_ON_ROSTER"
    assert_same_instant(refused["released_at"], "2026-05-01T00:00:00.000Z", "released_at")
    assert refused["matched_recipient_id"] is None


def test_matching_a_piece_whose_addressee_is_not_on_the_roster_is_rejected(api):
    """PRD §3.4: "The piece must be in `handling_status` `RECEIVED`; the named member
    must belong to the same mailbox and hold a `roster_status` of `PENDING`,
    `AUTHORIZED` or `SUSPENDED` (which is to say, anything but `REMOVED`); and the
    piece's normalized `addressee_name` must equal either the member's normalized
    `legal_name` or one of its normalized `dba_aliases`."
    PRD §3.4: "Any of those three failing is `ERR_RECIPIENT_NOT_ON_ROSTER`."

    Design: Corner/validations/matching_a_piece_to_a_name_not_on_the_roster_is_rejected
    """
    ctx = setup_releasable_box("Z-3010", "Lyn Roster", holder_email="lyn@example.com")
    item = log_mail_item(ctx["box_id"], letter_payload("Max Stranger"))

    response = api.match_mail_item(
        item["id"], {"recipient_id": ctx["recipient_id"]}, CMRA_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_RECIPIENT_NOT_ON_ROSTER.value)

    reread = validate_success(api.get_mail_item(item["id"], CMRA_OPERATOR))
    assert reread["handling_status"] == "RECEIVED"
    assert reread["matched_recipient_id"] is None


def test_piece_listings_filter_by_handling_status_and_matched_recipient(api):
    """PRD §3.4: "Pieces may be listed per mailbox filtered by `handling_status` and
    `storage_status`, and across mailboxes filtered by `box_id`,
    `matched_recipient_id`, `carrier_rule_id`, `forward_shipment_id`, `handling_status`
    and `item_class`."
    PRD §2.3: "`total_count` is the number of rows matching the filters before `limit`
    and `offset` are applied; `has_more` is true when the sum of `offset` and the number
    of rows actually returned is less than `total_count`, and false otherwise."

    Design: Corner/endpoints/mail_item_list_filters_by_handling_status_and_matched_recipient
    """
    ctx = setup_releasable_box("Z-4002", "Rob Filter", holder_email="rob@example.com")
    matched = log_and_match_letter(ctx)
    odd = log_mail_item(ctx["box_id"], letter_payload("Odd Name"))
    validate_success(
        api.refuse_mail_item(odd["id"], {"refusal_reason": "HOLDER_REQUEST"}, CMRA_OPERATOR)
    )

    refused_rows, refused_meta = validate_paginated(
        api.list_mail_items(
            CMRA_OPERATOR, params={"box_id": ctx["box_id"], "handling_status": "REFUSED"}
        )
    )
    assert refused_meta["total_count"] == 1
    assert refused_rows[0]["id"] == odd["id"]

    matched_rows, matched_meta = validate_paginated(
        api.list_mail_items(
            CMRA_OPERATOR, params={"matched_recipient_id": ctx["recipient_id"]}
        )
    )
    assert matched_meta["total_count"] == 1
    assert matched_rows[0]["id"] == matched["id"]


def test_logging_a_package_against_an_unknown_carrier_rule_is_a_not_found(api):
    """PRD §2.9 rung 6: "A `carrier_rule_id` supplied in the body resolves to a carrier
    rule. Otherwise `ERR_CARRIER_RULE_NOT_FOUND` (404). Applies to
    `POST /boxes/{id}/mail-items`."
    PRD §3.4: "`carrier_rule_id` is **required** when `item_class` is `PACKAGE` or
    `SOP`, because both arrive through a carrier, and **forbidden** for `LETTER` and
    `FLAT`; getting that pairing wrong is `ERR_VALIDATION`."

    Design: Corner/errors/error_carrier_rule_not_found_on_unknown_body_fk
    """
    ctx = setup_releasable_box("Z-5003", "Wan Ghost", holder_email="wan@example.com")

    response = api.create_mail_item(
        ctx["box_id"],
        {
            "addressee_name": "Wan Ghost",
            "item_class": "PACKAGE",
            "carrier_rule_id": UNKNOWN_UUID_4,
            "signature_required": False,
            "actual_weight_lb": 2.0,
            "length_in": 10.0,
            "width_in": 8.0,
            "height_in": 6.0,
            "interior_scan_consent": False,
        },
        CMRA_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_CARRIER_RULE_NOT_FOUND.value)
