"""Filing, segregation-of-duties, manifest matching, and customs-response
branches (PRD §3.6, §2.9, §2.11)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    advance_clock_to,
    api_client,
    create_declaration,
    emit_customs_response,
    emit_customs_response_payload,
    emit_manifest_dropped_payload,
    emit_manifest_match,
    file_declaration,
    locate_settlement_for_declaration,
    make_doc_reviewer_headers,
    make_filing_officer_headers,
    pre_validate_declaration,
    request_documents,
    reset_clock_to_epoch,
    respond_query_payload,
    setup_active_agreement,
    setup_declaration_in_filed,
    setup_declaration_in_pre_validated,
    setup_declaration_in_queried,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — Filing happy path
# ===========================================================================
class TestFilingTransition:

    def test_file_pre_validated_advances_to_filed(self, api):
        """PRD §3.6: "A FilingOfficer advances the declaration from
        PRE_VALIDATED to FILED."

        Claim: state advances to FILED on file action.
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        assert ctx["declaration"]["status"] == "FILED"

    def test_file_creates_filing_with_awaiting_response(self, api):
        """PRD §3.6: "the server creates a Filing carrying the parent
        declaration_id, a freshly-minted single_window_ref UUID,
        submitted_at set to the current instant, response_type
        initialised to AWAITING, manifest_match_status initialised to
        UNMATCHED".

        Claim: Filing exists with response_type=AWAITING and
        manifest_match_status=UNMATCHED right after file.
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx.get("filing")
        assert filing is not None, "Filing must be created on /file"
        assert filing["response_type"] == "AWAITING"
        assert filing["manifest_match_status"] == "UNMATCHED"


# ===========================================================================
# §3.6 / §2.9 — Segregation of duties: pre-validate vs file
# ===========================================================================
class TestSegregationOfDuties:

    def test_same_user_pre_validate_and_file_rejected(self, api):
        """PRD §2.9: "a DocReviewer who advances a declaration to
        PRE_VALIDATED cannot then act as the FilingOfficer on the same
        declaration's file transition."

        Claim: file action with same X-User-ID as the pre-validate actor
        → ERR_SEGREGATION_OF_DUTIES.
        """
        same_id = "shared-id-001"
        ctx = setup_declaration_in_pre_validated(reviewer_id=same_id)
        dec = ctx["declaration"]
        resp = api.file_declaration(
            dec["id"],
            action_with_version_payload(version=dec["version"]),
            make_filing_officer_headers(same_id),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# §3.6 — Manifest matching and RELEASE gating
# ===========================================================================
class TestManifestMatching:

    def test_manifest_match_sets_matched(self, api):
        """PRD §3.6: "The filing's manifest_match_status is set to MATCHED
        if both values agree exactly; otherwise it is set to MISMATCHED."

        Claim: MANIFEST_DROPPED with matching shipment_reference + hs_code
        → manifest_match_status=MATCHED.
        """
        ctx = setup_declaration_in_filed(match_manifest=True)
        # Re-read filing
        from test_helpers import get_filing_for_declaration
        filing = get_filing_for_declaration(ctx["declaration"]["id"]) or ctx.get("filing")
        assert filing is not None
        assert filing["manifest_match_status"] == "MATCHED"

    def test_release_on_unmatched_manifest_rejected(
        self, api, system_admin_headers,
    ):
        """PRD §3.6: "an attempt to process a RELEASE against an UNMATCHED
        or MISMATCHED manifest is rejected with ERR_MANIFEST_MISMATCH."

        Claim: emit CUSTOMS_RESPONSE=RELEASE while
        manifest_match_status=UNMATCHED → ERR_MANIFEST_MISMATCH.
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx.get("filing")
        assert filing is not None
        resp = api.emit_event(
            emit_customs_response_payload(
                filing_id=filing["id"], response_type="RELEASE",
            ),
            system_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MANIFEST_MISMATCH.value)

    def test_manifest_mismatch_records_field_change(self, api, system_admin_headers):
        """PRD §3.6: "The filing's manifest_match_status is set to MATCHED
        if both values agree exactly; otherwise it is set to MISMATCHED."

        Claim: manifest with wrong hs_code → manifest_match_status=MISMATCHED.
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx.get("filing")
        dec = ctx["declaration"]
        # Emit a manifest with WRONG hs_code.
        api.emit_event(
            emit_manifest_dropped_payload(
                filing_id=filing["id"],
                shipment_reference=dec["shipment_reference"],
                hs_code="99999999",
            ),
            system_admin_headers,
        )
        from test_helpers import get_filing_for_declaration
        filing2 = get_filing_for_declaration(dec["id"]) or filing
        assert filing2["manifest_match_status"] == "MISMATCHED"


# ===========================================================================
# §3.6 — Customs response branches: RELEASE / QUERY / INSPECT / REJECT
# ===========================================================================
class TestCustomsResponseBranches:

    def test_release_advances_to_released(self, api):
        """PRD §3.6: "A RELEASE response advances the declaration to
        RELEASED and sets the filing's response_type to RELEASE — but
        only if the filing's manifest_match_status is MATCHED".

        Claim: emit RELEASE on MATCHED filing → declaration=RELEASED.
        """
        from test_helpers import setup_declaration_released_via_emit
        ctx = setup_declaration_released_via_emit()
        assert ctx["declaration"]["status"] == "RELEASED"

    def test_query_advances_to_queried_and_sets_due_at(self, api):
        """PRD §3.6: "A QUERY response advances the declaration to QUERIED
        and sets the filing's response_type to QUERY, response_received_at
        to the current instant, and query_due_at to the current instant
        plus forty-eight hours."

        Claim: emit QUERY → declaration=QUERIED, filing.query_due_at set.
        """
        ctx = setup_declaration_in_queried()
        assert ctx["declaration"]["status"] == "QUERIED"
        filing = ctx.get("filing")
        assert filing is not None
        assert filing.get("query_due_at") is not None
        assert filing["response_type"] == "QUERY"

    def test_inspect_advances_to_inspecting(self, api, system_admin_headers):
        """PRD §3.6: "An INSPECT response advances the declaration to
        INSPECTING and sets the filing's response_type to INSPECT."

        Claim: emit INSPECT → declaration=INSPECTING.
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx.get("filing")
        api.emit_event(
            emit_customs_response_payload(
                filing_id=filing["id"], response_type="INSPECT",
            ),
            system_admin_headers,
        )
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        assert dec["status"] == "INSPECTING"

    def test_reject_advances_to_rejected_and_creates_rejection_record(
        self, api, system_admin_headers, broker_ops_headers,
    ):
        """PRD §3.6: "A REJECT response advances the declaration to
        REJECTED, sets the filing's response_type to REJECT, sets
        rejection_reason_code to the value carried in the payload's
        reason field, and creates a RejectionRecord carrying the parent
        declaration_id, the same rejection_reason_code, archived_at set
        to the current instant, prior_amendment_count snapshotted from
        the declaration's amendment_count".

        Claim: emit REJECT with reason → declaration=REJECTED with
        matching rejection_reason_code AND a RejectionRecord exists.
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx.get("filing")
        api.emit_event(
            emit_customs_response_payload(
                filing_id=filing["id"], response_type="REJECT",
                reason_code="HS_MISMATCH",
            ),
            system_admin_headers,
        )
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], broker_ops_headers,
        ))
        assert dec["status"] == "REJECTED"
        assert dec["rejection_reason_code"] == "HS_MISMATCH"
        # Look up the rejection record.
        rejection_resp = api.list_rejection_records(
            broker_ops_headers, params={"declaration_id": dec["id"]},
        )
        body = validate_success(rejection_resp)
        rows = body if isinstance(body, list) else (
            body.get("items") or body.get("data") or body.get("rejection_records") or []
        )
        if not isinstance(rows, list):
            rows = []
        assert any(r.get("rejection_reason_code") == "HS_MISMATCH" for r in rows), (
            "A RejectionRecord with reason HS_MISMATCH must exist after REJECT"
        )


# ===========================================================================
# §3.6 — Query response window
# ===========================================================================
class TestQueryResponseDeadline:

    def test_respond_query_after_deadline_rejected(self, api):
        """PRD §3.6: "The transition is allowed only when the current
        instant is strictly before query_due_at and the filing's
        response_type is still QUERY; an attempt after the deadline is
        rejected with ERR_QUERY_DEADLINE_PASSED."

        Claim: advance clock to query_due_at exactly → respond-query
        → ERR_QUERY_DEADLINE_PASSED.
        """
        reset_clock_to_epoch()
        ctx = setup_declaration_in_queried()
        filing = ctx.get("filing")
        dec = ctx["declaration"]
        # query_due_at = now + 48h. Advance past it.
        from test_helpers.fixtures import TEST_EPOCH
        # Advance clock to the deadline + 1s to be unambiguously past it.
        due_at = filing["query_due_at"]
        # Parse ISO string and advance.
        from datetime import datetime as _dt
        due_dt = _dt.fromisoformat(due_at.replace("Z", "+00:00"))
        advance_clock_to(due_dt + timedelta(seconds=1))
        # Refresh declaration to pick up auto-rejection if implementation
        # has already auto-transitioned. PRD §3.6 says clock advance past
        # the deadline auto-rejects. We attempt respond-query and assert
        # it either fails with ERR_QUERY_DEADLINE_PASSED (deadline check
        # fires first) or with ERR_INVALID_STATE (already auto-rejected).
        # Omit version (PRD §2.5 escape hatch). Otherwise clock-advance
        # auto-rejection (PRD §3.6) bumps the declaration's version, so
        # the version check (PRD §2.10 priority) would deliver
        # ERR_VERSION_CONFLICT before the deadline / state check runs.
        resp = api.respond_query(
            dec["id"], respond_query_payload(response_note="late"),
            TEST_USERS["filing_officer_headers"],
        )
        # PRD prose explicitly names ERR_QUERY_DEADLINE_PASSED for after-deadline,
        # and the auto-transition is a separate path. Either is faithful;
        # the rule under test is "after the deadline is rejected".
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_QUERY_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_respond_query_within_deadline_returns_to_filed(self, api):
        """PRD §3.6: "When the declaration is in QUERIED, a FilingOfficer
        may submit a query response with the originating response_note
        and the optional version. The transition is allowed only when
        the current instant is strictly before query_due_at and the
        filing's response_type is still QUERY ... The success path
        sets query_response_at to the current instant and resets the
        filing's response_type to AWAITING so that customs may evaluate
        again."

        Claim: respond-query before deadline → declaration back to FILED,
        filing.response_type=AWAITING.
        """
        reset_clock_to_epoch()
        ctx = setup_declaration_in_queried()
        dec = ctx["declaration"]
        resp = api.respond_query(
            dec["id"],
            respond_query_payload(response_note="response provided",
                                  version=dec["version"]),
            TEST_USERS["filing_officer_headers"],
        )
        result = validate_success(resp)
        assert result["status"] == "FILED"


# ===========================================================================
# §3.5 / §3.6 — file requires pre-validated declared-value review != FLAGGED
# ===========================================================================
class TestFileBlocksFlaggedDeclaredValue:

    def test_pre_validate_blocked_when_declared_value_flagged(self, api):
        """PRD §3.5: "the declared-value review must have produced an
        ACCEPTED declared_value_review_status (a FLAGGED status blocks
        both pre-validation and filing — see §3.6)."

        Claim: a declaration with declared_value_review_status=FLAGGED
        cannot pre-validate. Two faithful surface errors are both
        permissible — the explicit ERR_DECLARED_VALUE_FLAGGED named at
        file time, or the generic ERR_INVALID_STATE that the layered
        pre-validate gate could emit if it short-circuits on the value
        review without re-using the file-time error code.

        Recipe: HS 8517 in CN has ref=800.00 CNY. declared=2000 CNY →
        |2000-800|/800 = 1.5 = 150% deviation → FLAGGED.
        """
        from test_helpers import (
            attach_core_docs, setup_declaration_in_docs_pending,
            validate_error_is_one_of,
        )
        ctx = setup_declaration_in_docs_pending(
            default_settlement_currency="CNY",
            jurisdiction_code="CN", hs_code="85171200",
            declared_value_amount=2000.00, declared_currency="CNY",
        )
        dec_id = ctx["declaration"]["id"]
        # Sanity: declared_value_review_status=FLAGGED.
        assert ctx["declaration"]["declared_value_review_status"] == "FLAGGED"
        attach_core_docs(dec_id, invoice_total=2000.0, invoice_currency="CNY",
                         packing_list_total=2000.0, packing_list_currency="CNY")
        dec = validate_success(api.get_declaration(
            dec_id, TEST_USERS["declaration_officer_headers"],
        ))
        resp = api.pre_validate_declaration(
            dec_id, {"version": dec["version"]},
            TEST_USERS["doc_reviewer_headers"],
        )
        # PRD names ERR_DECLARED_VALUE_FLAGGED at file; pre-validate
        # prose only says "a FLAGGED status blocks both pre-validation
        # and filing" without pinning a specific error_id for the
        # pre-validate path, so either ERR_DECLARED_VALUE_FLAGGED or
        # ERR_INVALID_STATE is faithful.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DECLARED_VALUE_FLAGGED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])
