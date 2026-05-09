"""Concurrency tests — every PRD-defined race scenario gets coverage (PRD §3.8 ¶ end + §2.8)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    run_race,
    assert_exactly_one_succeeds,
    setup_batch_with_qr_inspected_pass,
    setup_batch_inspected_pass,
    setup_recall_at_initiated,
    create_recall_payload,
    REGULATORY_HEADERS,
    make_grower_headers,
    make_distributor_headers,
    DEFAULT_GROWER_ID,
    notify_recall,
)


def test_two_recalls_on_same_batch_serialize_one_succeeds():
    """PRD §3.8: "Two simultaneous recalls on the same batch serialize on the
    batch's recall_status flip from NONE to ACTIVE_RECALL: the first writer
    succeeds and the second receives ERR_RECALL_ALREADY_ACTIVE."

    Claim: two concurrent POST /recall-orders → exactly one succeeds, the
    other returns ERR_RECALL_ALREADY_ACTIVE.
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass()
    payload = create_recall_payload(batch["id"])
    results = run_race(
        lambda: api.create_recall(payload, REGULATORY_HEADERS),
        lambda: api.create_recall(payload, REGULATORY_HEADERS),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    assert outcome["successes"], "expected one success"
    failure_resp = outcome["failures"][0]
    body = failure_resp.json()
    error_id = body.get("data", {}).get("error_id")
    assert error_id == "ERR_RECALL_ALREADY_ACTIVE", \
        f"loser must report ERR_RECALL_ALREADY_ACTIVE, got {error_id!r}"


def test_two_qr_mints_on_same_harvest_serialize():
    """PRD §3.8: "A simultaneous QR mint by two callers on the same harvest
    serializes on the unique-harvest_record_id constraint; the loser receives
    ERR_QR_ALREADY_BOUND."

    Claim: two concurrent mint calls → exactly one succeeds, loser is
    ERR_QR_ALREADY_BOUND.
    """
    batch, _bin, harvest, _report = setup_batch_inspected_pass()
    headers = make_grower_headers(batch["grower_id"])
    results = run_race(
        lambda: api.mint_qr_code(harvest["id"], headers),
        lambda: api.mint_qr_code(harvest["id"], headers),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    failure_resp = outcome["failures"][0]
    body = failure_resp.json()
    error_id = body.get("data", {}).get("error_id")
    assert error_id == "ERR_QR_ALREADY_BOUND", \
        f"loser must report ERR_QR_ALREADY_BOUND, got {error_id!r}"


def test_disposal_and_cancel_race_serializes_on_recall_status():
    """PRD §3.8: "A simultaneous disposal-and-cancel race serializes on the
    recall's status: if the cancel commits first, the disposal arrives to
    find the recall no longer IN_PROGRESS or NOTIFIED and is rejected with
    ERR_INVALID_STATE; if the disposal commits first, the cancel finds at
    least one disposal record present and is rejected with
    ERR_RECALL_HAS_DISPOSALS."

    Claim: race produces exactly one success; loser's error_id is one of the
    two PRD-named outcomes (ERR_INVALID_STATE or ERR_RECALL_HAS_DISPOSALS).
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    dist_headers = make_distributor_headers(distributor["id"])
    disposal_payload = {
        "distributor_id": distributor["id"],
        "disposed_kg": 5.0,
        "disposed_at": "2026-04-22T00:00:00.000Z",
    }
    results = run_race(
        lambda: api.create_disposal(recall["id"], disposal_payload, dist_headers),
        lambda: api.cancel_recall(recall["id"], REGULATORY_HEADERS),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    failure_resp = outcome["failures"][0]
    body = failure_resp.json()
    error_id = body.get("data", {}).get("error_id")
    assert error_id in ("ERR_INVALID_STATE", "ERR_RECALL_HAS_DISPOSALS"), \
        f"loser must be one of the two PRD-named errors, got {error_id!r}"


def test_inspector_issue_and_officer_revoke_race():
    """PRD §3.8: "A simultaneous inspector-issue and officer-revoke on the
    same batch's report serializes on the report's status: exactly one
    operation succeeds, and the loser receives ERR_INVALID_STATE because the
    target status has changed by the time the loser's check runs."

    Claim: build an ISSUED report (so revoke is valid) and a parallel DRAFT
    report (so issue is valid) on the same batch, race them; the operation
    that loses sees ERR_INVALID_STATE.
    """
    from test_helpers import (
        create_draft_inspection,
        issue_inspection,
        setup_batch_harvested,
    )
    batch, _bin, _harvest = setup_batch_harvested(grower_id=DEFAULT_GROWER_ID)
    # First issue a report so that we have an ISSUED report to revoke.
    draft_a = create_draft_inspection(
        batch, inspector_id="user-inspector-001",
        test_items=["MICROORGANISMS"], microorganism_cfu_per_g=10000,
    )
    issued_a = issue_inspection(draft_a, inspector_id="user-inspector-001")
    # Revoking pulls batch back to HARVESTED, allowing a new DRAFT/issue cycle.
    # Build a second draft and race issue(b) vs revoke(a).
    draft_b = create_draft_inspection(
        batch, inspector_id="user-inspector-002",
        test_items=["MICROORGANISMS"], microorganism_cfu_per_g=10000,
    )
    from test_helpers import make_inspector_headers
    issue_headers = make_inspector_headers("user-inspector-002")
    results = run_race(
        lambda: api.issue_inspection(draft_b["id"], issue_headers),
        lambda: api.revoke_inspection(issued_a["id"], REGULATORY_HEADERS),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    failure_resp = outcome["failures"][0]
    body = failure_resp.json()
    error_id = body.get("data", {}).get("error_id")
    assert error_id == "ERR_INVALID_STATE", \
        f"loser must report ERR_INVALID_STATE, got {error_id!r}"


# Note on PRD §2.8 OCC: the PRD declares optimistic-concurrency control "covers
# every PATCH endpoint and every state-transition endpoint that targets a
# single resource by id." The only PATCH endpoint in §4 is
# `/pesticide-registry/{registration_no}/prohibit`, and PesticideRegistry is
# explicitly listed in §2.4 as carrying ONLY id and created_at (no version
# field). For state-transition endpoints, PRD prose never names a specific
# request body that includes the version field nor does it commit to which
# transitions accept it. Two PRD-only readers could disagree on which
# transition endpoint to target with a stale version. Per the silence rule,
# no concrete OCC stale-version test is generated; the gap is logged in the
# Summary report under `default-value`/`enum-write-pathway` (no PRD-stated
# write pathway).
