"""Disposition requests: the optimistic-concurrency rung and the single-occupant queue."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    assert_disposition_request,
    disposition_payload,
    lodge_disposition,
    log_and_match_letter,
    mail_item_version,
    read_mail_item,
    setup_releasable_box,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# Both readings of the un-adjudicated point in PRD §3.7 (whether a further request
# lodged against a piece already in PENDING_DISPOSITION is adjudicated by the
# precedence rule or refused by the declared-transition rung) reject an equal-rank
# request and write nothing, so only that agreed outcome is asserted below.
SECOND_REQUEST_REFUSALS = [
    ApiErrorId.ERR_DISPOSITION_CONFLICT.value,
    ApiErrorId.ERR_INVALID_STATE.value,
]


def _setup_piece_with_pending_shred(box_number, legal_name, holder_email):
    ctx = setup_releasable_box(box_number, legal_name, holder_email=holder_email)
    item = log_and_match_letter(ctx)
    assert item["handling_status"] == "HELD"
    ctx["item_id"] = item["id"]
    ctx["observed_version"] = item["version"]
    ctx["disposition"] = lodge_disposition(ctx, item["id"], "SHRED")
    return ctx


def test_a_stale_mail_item_version_is_rejected_at_the_concurrency_rung(api):
    """PRD §2.7: "`POST /mail-items/{id}/dispositions` requires
    `expected_mail_item_version`, carrying the client's last observed `version` of the
    target mail item."
    PRD §2.7: "If the value supplied does not equal the parent row's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_state_rung_preempts_disposition_conflict_constraint_rung
    """
    ctx = _setup_piece_with_pending_shred("I-901", "Mel Race", "mel@example.com")

    response = api.create_disposition(
        ctx["item_id"],
        disposition_payload("SHRED", ctx["observed_version"]),
        ctx["holder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    incumbent = validate_success(
        api.list_dispositions(ctx["item_id"], CMRA_OPERATOR)
    )
    assert len(incumbent) == 1
    assert incumbent[0]["id"] == ctx["disposition"]["id"]
    assert incumbent[0]["status"] == "PENDING"
    assert read_mail_item(ctx["item_id"])["handling_status"] == "PENDING_DISPOSITION"


def test_replaying_the_request_with_a_fresh_version_clears_the_concurrency_rung(api):
    """PRD §2.9 rung 13: "The supplied `expected_mail_item_version`,
    `expected_box_version` or `expected_deposit_batch_version` equals the parent's
    current `version`. Otherwise `ERR_STALE_VERSION` (412)."
    PRD §3.7: "Equality is a rejection, not an idempotent no-op: a shred lodged over a
    pending shred is a conflict, while a deposit lodged over a pending shred supersedes
    it."

    Re-sending with the piece's current version gets past the 412 and is then refused on
    the merits, leaving exactly one request on the piece.

    Design: Difficulty/priority_pair_validation_conflict/stale_version_state_rung_preempts_disposition_conflict_constraint_rung
    """
    ctx = _setup_piece_with_pending_shred("I-901", "Mel Race", "mel@example.com")
    current = mail_item_version(ctx["item_id"])
    assert current != ctx["observed_version"]

    response = api.create_disposition(
        ctx["item_id"], disposition_payload("SHRED", current), ctx["holder_headers"]
    )
    assert response.status_code == 409, (
        f"Expected the replay to be refused with HTTP 409, got {response.status_code}"
    )
    validate_error_is_one_of(response, SECOND_REQUEST_REFUSALS)

    rows, meta = validate_paginated(api.list_dispositions(ctx["item_id"], CMRA_OPERATOR))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PENDING"
    assert read_mail_item(ctx["item_id"])["handling_status"] == "PENDING_DISPOSITION"


def test_lodging_a_request_stamps_its_precedence_rank_and_freezes_the_piece(api):
    """PRD §3.7: "Every type carries a fixed `precedence_rank`: `DEPOSIT` is 1,
    `FORWARD` is 2, `RETURN` is 3 and `SHRED` is 4, and a **lower** rank wins."
    PRD §3.7: "Lodging the first request drives the custody axis
    `HELD → PENDING_DISPOSITION` and bumps `MailItem.version` by one."
    PRD §3.7: "A request is created with `status` `PENDING`, `resolution_reason` `NONE`
    and a null `executed_at`."

    Design: Difficulty/resource_temporal_overlap/disposition_queue_admits_only_one_pending_occupant
    """
    ctx = setup_releasable_box("T-2001", "Tom Queue", holder_email="tom@example.com")
    shred_item = log_and_match_letter(ctx)
    deposit_item = log_and_match_letter(ctx)

    shred = validate_success(
        api.create_disposition(
            shred_item["id"],
            disposition_payload("SHRED", shred_item["version"]),
            ctx["holder_headers"],
        ),
        201,
    )
    assert_disposition_request(shred)
    assert shred["disposition_type"] == "SHRED"
    assert shred["precedence_rank"] == 4
    assert shred["status"] == "PENDING"
    assert shred["resolution_reason"] == "NONE"
    assert shred["executed_at"] is None
    assert read_mail_item(shred_item["id"])["handling_status"] == "PENDING_DISPOSITION"

    deposit = validate_success(
        api.create_disposition(
            deposit_item["id"],
            disposition_payload("DEPOSIT", deposit_item["version"]),
            ctx["holder_headers"],
        ),
        201,
    )
    assert deposit["precedence_rank"] == 1
    assert deposit["status"] == "PENDING"


def test_the_piece_admits_only_one_pending_request_at_a_time(api):
    """PRD §3.7: "If the piece carries no request in status `PENDING`, the incoming
    request is simply created `PENDING`."
    PRD §3.7: "Equality is a rejection, not an idempotent no-op: a shred lodged over a
    pending shred is a conflict, while a deposit lodged over a pending shred supersedes
    it."

    Design: Difficulty/resource_temporal_overlap/disposition_queue_admits_only_one_pending_occupant
    """
    ctx = _setup_piece_with_pending_shred("T-2001", "Tom Queue", "tom@example.com")
    current = mail_item_version(ctx["item_id"])

    response = api.create_disposition(
        ctx["item_id"], disposition_payload("SHRED", current), ctx["holder_headers"]
    )
    assert response.status_code == 409, (
        f"Expected an equal-rank collision to be refused with HTTP 409, got "
        f"{response.status_code}"
    )
    validate_error_is_one_of(response, SECOND_REQUEST_REFUSALS)

    rows, meta = validate_paginated(api.list_dispositions(ctx["item_id"], CMRA_OPERATOR))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["disposition"]["id"]
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["precedence_rank"] == 4
    assert read_mail_item(ctx["item_id"])["handling_status"] == "PENDING_DISPOSITION"
