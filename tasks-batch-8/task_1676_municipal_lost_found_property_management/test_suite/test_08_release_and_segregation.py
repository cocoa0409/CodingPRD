"""Release handover, release records, and duty segregation (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    advance_clock_and_sweep,
    approve_claim,
    assert_release_record,
    create_claim,
    create_claimant,
    create_release_payload,
    get_claim,
    get_item,
    make_claims_examiner_headers,
    make_property_custodian_headers,
    make_release_officer_headers,
    release_item,
    setup_approved_claim,
    setup_claim_under_review,
    setup_stored_item,
    start_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_release_creates_queryable_release_record(api, release_officer_headers):
    """PRD §3.5: "A successful release creates a release record capturing
    `item_id`, the `claim_id` of the approved claim it satisfies, `released_by`
    set to the officer's `X-User-ID`, the handover inputs, and `released_at`
    stamped from the logical clock. In the same operation the item moves from
    `RELEASE_PENDING` to `RELEASED`, the approved claim moves from `APPROVED` to
    `RELEASED`".

    Design: Corner/endpoints/release_record_reverse_lookup
    """
    ctx = setup_approved_claim()
    assert get_item(ctx.item["id"])["status"] == "RELEASE_PENDING"

    released = release_item(ctx.item["id"], handover_method="IN_PERSON",
                            id_document_ref="DL-999",
                            release_officer_id="officer-release-1")
    assert released["status"] == "RELEASED"
    assert get_claim(ctx.claim["id"])["status"] == "RELEASED", (
        "the approved claim moves to RELEASED in the same operation")

    records, meta = validate_paginated(api.list_release_records(
        release_officer_headers, params={"item_id": ctx.item["id"]}))
    assert len(records) == 1, "exactly one release record exists for the item"
    record = records[0]
    assert_release_record(record)
    assert record["claim_id"] == ctx.claim["id"]
    assert record["released_by"] == "officer-release-1"
    assert record["handover_method"] == "IN_PERSON"
    assert record["id_document_ref"] == "DL-999"


def test_release_by_intake_officer_segregation_rejected(api):
    """PRD §3.5: "the releasing officer's `X-User-ID` must differ from the
    item's `intake_officer_id`, and it must differ from the `examiner_id` of the
    approved claim on the item. Either collision is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_release_by_intake_officer_rejected
    """
    ctx = setup_approved_claim(intake_officer_id="officer-intake-1")
    assert get_item(ctx.item["id"])["status"] == "RELEASE_PENDING"

    res = api.release_item(
        ctx.item["id"], create_release_payload(),
        make_release_officer_headers("officer-intake-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    assert get_item(ctx.item["id"])["status"] == "RELEASE_PENDING"
    records, _ = validate_paginated(api.list_release_records(
        make_release_officer_headers("officer-release-1"),
        params={"item_id": ctx.item["id"]}))
    assert records == [], "no release record is created by a rejected release"


def test_approve_by_intake_officer_segregation_rejected(api):
    """PRD §3.4: "Segregation of duties forbids the approving examiner from
    being the same `X-User-ID` recorded as the item's `intake_officer_id`
    (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."

    Design: Corner/rbac/segregation_approve_by_intake_officer_rejected
    """
    ctx = setup_stored_item(declared_value_cents=5000,
                            intake_officer_id="officer-intake-1")
    claimant = create_claimant()
    claim = create_claim(ctx.item["id"], claimant["id"],
                         proof_serial=True, proof_photo=True)
    # The reviewing examiner's X-User-ID equals the item's intake_officer_id.
    start_review(claim["id"], "officer-intake-1")

    res = api.approve_claim(
        claim["id"], make_claims_examiner_headers("officer-intake-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"


def test_release_from_stored_rejected(api, release_officer_headers):
    """PRD §3.5: "The item must be in `RELEASE_PENDING` (`ERR_INVALID_STATE`
    otherwise)".

    Design: Corner/state_machines/item_release_from_stored_returns_invalid_state
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    res = api.release_item(ctx.item["id"], create_release_payload(),
                           release_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_item(ctx.item["id"])["status"] == "STORED"


def test_release_disposed_item_returns_invalid_state_over_segregation(api):
    """PRD §2.7: "the server evaluates its checks in a single deterministic
    order, and the earliest failing check determines the error returned" — with
    "Generic state admissibility — the target resource's current state must
    permit the requested transition, otherwise `ERR_INVALID_STATE` (HTTP 409)"
    ordered before the business-safety rule "`ERR_IDENTIFICATION_NOT_LISTABLE`,
    then `ERR_CLAIM_PROOF_INSUFFICIENT`, then `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)".

    Design: Difficulty/priority_pair_validation_conflict/state_over_safety_on_disposed_release
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            disposal_method="DESTRUCTION",
                            intake_officer_id="officer-intake-1")
    advance_clock_and_sweep("2026-08-11T09:00:00Z")
    disposed = validate_success(api.dispose_item(
        ctx.item["id"], "DESTRUCTION",
        make_property_custodian_headers("custodian-1")), 200)
    assert disposed["status"] == "DISPOSED"

    # Both violated: state (item is DISPOSED, not RELEASE_PENDING) AND
    # segregation (releasing officer id == intake officer id). State wins.
    res = api.release_item(
        ctx.item["id"],
        create_release_payload(handover_method="IN_PERSON", id_document_ref="DL-123"),
        make_release_officer_headers("officer-intake-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_item(ctx.item["id"])["status"] == "DISPOSED"


def test_release_rejection_creates_no_release_record(api, release_officer_headers):
    """PRD §3.5: "A successful release creates a release record capturing
    `item_id`, the `claim_id` of the approved claim it satisfies" — a rejected
    release creates nothing. PRD §3.5: "staff may list them with `item_id` and
    `claim_id` filters".

    Design: Difficulty/priority_pair_validation_conflict/state_over_safety_on_disposed_release
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            disposal_method="DESTRUCTION",
                            intake_officer_id="officer-intake-1")
    advance_clock_and_sweep("2026-08-11T09:00:00Z")
    validate_success(api.dispose_item(
        ctx.item["id"], "DESTRUCTION",
        make_property_custodian_headers("custodian-1")), 200)

    res = api.release_item(
        ctx.item["id"], create_release_payload(id_document_ref="DL-123"),
        make_release_officer_headers("officer-intake-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    records, meta = validate_paginated(api.list_release_records(
        release_officer_headers, params={"item_id": ctx.item["id"]}))
    assert records == [] and meta["total_count"] == 0, (
        "no release record exists for an item whose release was rejected")
