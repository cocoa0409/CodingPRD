"""
State-machine corners of the Digital Estate Fiduciary Access API.

Every test here builds its own world from an empty database whose logical clock
sits at the fresh-server epoch, then drives one lifecycle across the exact edge
the contract defines: which transition is legal from which source state, which
side effects a legal transition carries, and which error the server owes a
caller who submits an action the current status does not define.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    assert_fields,
    assert_null_fields,
    factories as f,
    fixtures as fx,
)
from test_helpers.api_errors import (
    ERR_EFFECTIVE_DATE_BEFORE_DEATH,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_DOCUMENT_STATE,
    ERR_INVALID_GRANT_STATE,
    ERR_INVALID_ORDER_STATE,
    ERR_INVALID_REQUEST_STATE,
    ERR_LETTERS_NOT_ISSUED,
    ERR_SUBSCRIPTION_TERM_EXISTS,
)
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    ACCESS_REVOKED,
    ACCESS_UNVERIFIED,
    BASIS_STATUTORY_DEFAULT,
    BILLING_ACTIVE,
    BILLING_CANCELLED,
    BILLING_INTERVAL_ANNUAL,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_SUBSCRIPTION,
    CLAIM_ACTION_CREDIT,
    CLAIM_ACTION_DENY,
    CLAIM_ACTION_ESCALATE,
    CLAIM_ACTION_START_REVIEW,
    CLAIM_CREDITED,
    CLAIM_ESCALATED,
    CLAIM_FILED,
    CLAIM_PLATFORM_REVIEW,
    CLAMP_NONE,
    CLOCK_EPOCH,
    DECISION_APPROVED,
    DECISION_DENIED,
    DIRECTIVE_ONLINE_TOOL,
    DIRECTIVE_STATUS_RECORDED,
    DIRECTIVE_WILL_PROVISION,
    DISPOSITION_ELECTED,
    DISPOSITION_PENDING,
    DOC_ACTION_REVOKE,
    DOC_ACTION_VERIFY,
    DOC_PENDING,
    DOC_REVOKED,
    DOC_VERIFIED,
    ELECTION_DRAFT,
    ELECTION_MEMORIALIZE,
    ELECTION_SUBMITTED,
    EL_ACTION_SUBMIT,
    GRANT_ACTION_REVOKE,
    GRANT_ACTIVE,
    GRANT_EXPIRED,
    GRANT_REVOKED,
    LETTERS_ISSUED,
    LETTERS_PENDING,
    METHOD_PRORATA_DAILY,
    ORDER_ACTION_CONFIRM,
    ORDER_ACTION_FAIL,
    ORDER_ACTION_REQUEST,
    ORDER_CONFIRMED,
    ORDER_FAILED,
    ORDER_PENDING,
    ORDER_REQUESTED,
    PHASE_AUTHORIZED,
    PHASE_DISCLOSURE,
    PHASE_INTAKE,
    PRECEDENCE_RANK_INSTRUMENT,
    PRECEDENCE_RANK_ONLINE_TOOL,
    REASON_CATEGORY_SUBSCRIPTION_LICENCE,
    REFUND_POLICY_PRORATA_DAILY,
    REQ_ACTION_DECIDE,
    REQ_ACTION_RESUBMIT,
    REQ_ACTION_START_REVIEW,
    REQ_ACTION_SUBMIT,
    REQ_ACTION_WITHDRAW,
    REQUEST_APPROVED,
    REQUEST_DRAFT,
    REQUEST_DENIED,
    REQUEST_SUBMITTED,
    REQUEST_UNDER_REVIEW,
    REQUEST_WITHDRAWN,
    REVOCATION_REGISTRAR_ORDER,
    REVOCATION_TERM_EXPIRED,
    SCOPE_CATALOG_AND_CONTENT,
    SCOPE_CATALOG_ONLY,
    TERM_ACTIVE,
    TERM_CANCELLED,
    TERM_LAPSED,
    LICENSE_TERMINATES_AT_DEATH,
)
from test_helpers.test_users import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    make_fiduciary_headers,
    make_platform_compliance_headers,
)


def test_letters_verification_issues_authority_and_lifts_the_phase(api):
    """
    Verifying the death certificate alone leaves the estate in INTAKE; only verifying the
    LETTERS_OF_AUTHORITY document flips the named fiduciary to ISSUED and re-derives the phase
    to AUTHORIZED, advancing the fiduciary's version exactly once.

    PRD: "When the document being verified is a `LETTERS_OF_AUTHORITY`, verification also reaches into the fiduciary it names and moves that fiduciary's `letters_status` from `PENDING` to `ISSUED`; that change in turn causes the estate's `administration_phase` to be re-derived."
    PRD: "Otherwise, if the estate has no `DEATH_CERTIFICATE` document in `VERIFIED` status, or no fiduciary at all with `letters_status` equal to `ISSUED`, the phase is `INTAKE`. Otherwise, if `disclosed_asset_count` is 0, the phase is `AUTHORIZED`."

    Design: Corner/state_machines/verifying_the_letters_document_issues_authority_and_lifts_the_phase
    """
    fx.set_clock(api, CLOCK_EPOCH)
    estate = fx.open_estate(api, court_case_number="PR-2737-C09")
    fid = fx.appoint_fiduciary(api, estate["id"], court_reference="APPT-2737-C09")
    dc = fx.add_document(api, estate["id"], f.document_payload(reference_number="DC-C09"))
    loa = fx.add_document(
        api, estate["id"], f.letters_document_payload(fid["id"], reference_number="LOA-C09")
    )

    dc_verified = validate_success(
        api.transition_document(
            dc["id"], f.document_transition_payload(DOC_ACTION_VERIFY), COURT_REGISTRAR_HEADERS
        ),
        200,
    )
    assert_fields(dc_verified, verification_status=DOC_VERIFIED)

    estate_mid = validate_success(api.get_estate(estate["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(estate_mid, administration_phase=PHASE_INTAKE)
    fid_mid = validate_success(api.get_fiduciary(fid["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(fid_mid, letters_status=LETTERS_PENDING, version=1)

    loa_verified = validate_success(
        api.transition_document(
            loa["id"], f.document_transition_payload(DOC_ACTION_VERIFY), COURT_REGISTRAR_HEADERS
        ),
        200,
    )
    assert_fields(loa_verified, verification_status=DOC_VERIFIED)
    assert loa_verified["verified_at"].startswith("2026-08-01T00:00:00"), (
        f"verified_at must be stamped with the logical clock, got {loa_verified['verified_at']!r}"
    )

    fid_after = validate_success(api.get_fiduciary(fid["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(fid_after, letters_status=LETTERS_ISSUED, version=2)

    estate_after = validate_success(api.get_estate(estate["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(
        estate_after,
        administration_phase=PHASE_AUTHORIZED,
        disclosed_asset_count=0,
        inventory_total_count=0,
    )


def test_submission_requires_the_named_fiduciary_to_hold_issued_letters(api):
    """
    A DRAFT package whose letters document is still PENDING cannot be submitted: SUBMIT is
    refused with ERR_LETTERS_NOT_ISSUED and the package stays DRAFT with a null window. Once the
    registrar verifies the letters, the identical call succeeds and opens the review window.

    PRD: "The cited letters must be `VERIFIED` *and* the fiduciary they name must have `letters_status` equal to `ISSUED`, or the submission is rejected with `ERR_LETTERS_NOT_ISSUED` — revoking letters immediately disqualifies that fiduciary from acting."
    PRD: "On submission the server sets `review_window_start` to the current logical-clock instant and `review_window_end` to that instant advanced by the provider's `review_window_days` days, and the window is **half-open**: the start instant is inside the window and the end instant is outside it."

    Design: Corner/state_machines/submitting_a_request_requires_the_named_fiduciary_to_hold_issued_letters
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C10", verify_letters=False)
    request = fx.draft_request(api, ctx, platform["id"], platform["form_code"])

    refused = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
    )
    validate_error(refused, ERR_LETTERS_NOT_ISSUED)

    still_draft = fx.read_request(api, ctx, request["id"])
    assert_fields(still_draft, status=REQUEST_DRAFT)
    assert_null_fields(still_draft, "review_window_start", "review_window_end")

    fx.verify_document(api, ctx.letters_id)
    fid_now = fx.read_fiduciary(api, ctx, ctx.fiduciary_id)
    assert_fields(fid_now, letters_status=LETTERS_ISSUED)

    submitted = validate_success(
        api.transition_platform_request(
            request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
        ),
        200,
    )
    assert_fields(submitted, status=REQUEST_SUBMITTED)
    assert submitted["review_window_start"].startswith("2026-08-01T00:00:00"), (
        f"review_window_start must open at the clock, got {submitted['review_window_start']!r}"
    )
    assert submitted["review_window_end"].startswith("2026-08-15T00:00:00"), (
        f"review_window_end must be 14 days later, got {submitted['review_window_end']!r}"
    )

    estate_after = fx.read_estate(api, ctx)
    assert_fields(estate_after, administration_phase=PHASE_AUTHORIZED)


def test_platform_request_actions_from_a_wrong_source_state_are_rejected(api):
    """
    Each request action is defined from exactly one source state: START_REVIEW and RESUBMIT are
    refused on a DRAFT package, DECIDE and a second SUBMIT are refused on a SUBMITTED one, and
    WITHDRAW is refused once the package reached UNDER_REVIEW. No refusal mutates a status, a
    window, the cycle counter or the decision, and none of them creates a grant.

    PRD: "`APPROVED`, `DENIED` and `WITHDRAWN` are all terminal; any action submitted against a package whose current `status` does not define that action — deciding a package still in `SUBMITTED`, or submitting one already `APPROVED` — is rejected with `ERR_INVALID_REQUEST_STATE`."
    PRD: "A `Fiduciary` may abandon a package from `DRAFT`, `SUBMITTED` or `INFO_REQUESTED`, advancing it to the terminal `WITHDRAWN` and storing a `withdrawal_reason`."

    Design: Corner/state_machines/platform_request_actions_from_a_wrong_source_state_are_rejected
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C11")
    desk = make_platform_compliance_headers(platform["id"])
    request = fx.draft_request(api, ctx, platform["id"], platform["form_code"])

    validate_error(
        api.transition_platform_request(
            request["id"], f.request_transition_payload(REQ_ACTION_START_REVIEW), desk
        ),
        ERR_INVALID_REQUEST_STATE,
    )
    validate_error(
        api.transition_platform_request(
            request["id"],
            f.request_transition_payload(
                REQ_ACTION_RESUBMIT, remediation_note="nothing to remediate yet"
            ),
            ctx.fid_headers,
        ),
        ERR_INVALID_REQUEST_STATE,
    )
    assert_fields(fx.read_request(api, ctx, request["id"]), status=REQUEST_DRAFT)

    fx.submit_request(api, ctx, request["id"])

    validate_error(
        api.transition_platform_request(
            request["id"],
            f.request_transition_payload(REQ_ACTION_DECIDE, decision=DECISION_APPROVED),
            desk,
        ),
        ERR_INVALID_REQUEST_STATE,
    )
    validate_error(
        api.transition_platform_request(
            request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
        ),
        ERR_INVALID_REQUEST_STATE,
    )

    fx.start_review(api, platform["id"], request["id"])

    validate_error(
        api.transition_platform_request(
            request["id"],
            f.request_transition_payload(REQ_ACTION_WITHDRAW, withdrawal_reason="changed our mind"),
            ctx.fid_headers,
        ),
        ERR_INVALID_REQUEST_STATE,
    )

    final = fx.read_request(api, ctx, request["id"])
    assert_fields(final, status=REQUEST_UNDER_REVIEW, info_cycle_count=0)
    assert_null_fields(final, "decision")
    assert final["review_window_start"].startswith("2026-08-01T00:00:00"), (
        f"a refused WITHDRAW must not clear the window, got {final['review_window_start']!r}"
    )
    assert final["review_window_end"].startswith("2026-08-15T00:00:00"), (
        f"a refused WITHDRAW must not clear the window, got {final['review_window_end']!r}"
    )

    grants, _ = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, platform_request_id=request["id"])
    )
    assert grants == [], f"No grant may exist before an approval, got {grants}"


def test_withdrawn_and_denied_requests_accept_no_further_action(api):
    """
    WITHDRAWN and DENIED are both terminal: SUBMIT and a second WITHDRAW on the withdrawn package
    and START_REVIEW and DECIDE on the denied one are all refused with ERR_INVALID_REQUEST_STATE.
    A DENIED decision grants nothing, so the inventoried account stays UNVERIFIED and the estate
    never leaves AUTHORIZED.

    PRD: "A decision of `DENIED` advances `UNDER_REVIEW → DENIED`, stores the note, creates no grant and leaves every account exactly where it was."
    PRD: "Withdrawal always releases the review window: `review_window_start` and `review_window_end` are cleared so the slot no longer blocks a new submission, which for a package withdrawn from `INFO_REQUESTED` simply means the already-null window stays null."

    Design: Corner/state_machines/withdrawn_and_denied_requests_accept_no_further_action
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C12")
    desk = make_platform_compliance_headers(platform["id"])
    asset = fx.add_asset(
        api, ctx, platform["id"], category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1",
        quoted_value_cents=90000,
    )

    request_x = fx.draft_request(api, ctx, platform["id"], platform["form_code"])
    withdrawn = validate_success(
        api.transition_platform_request(
            request_x["id"],
            f.request_transition_payload(
                REQ_ACTION_WITHDRAW, withdrawal_reason="filed against the wrong platform"
            ),
            ctx.fid_headers,
        ),
        200,
    )
    assert_fields(
        withdrawn,
        status=REQUEST_WITHDRAWN,
        withdrawal_reason="filed against the wrong platform",
    )
    assert_null_fields(withdrawn, "review_window_start", "review_window_end")

    request_y = fx.draft_request(api, ctx, platform["id"], platform["form_code"])
    fx.submit_request(api, ctx, request_y["id"])
    fx.start_review(api, platform["id"], request_y["id"])
    denied = fx.decide_request(
        api,
        platform["id"],
        request_y["id"],
        decision=DECISION_DENIED,
        decision_note="identity documents illegible",
    )
    assert_fields(
        denied,
        status=REQUEST_DENIED,
        decision=DECISION_DENIED,
        decision_note="identity documents illegible",
    )

    validate_error(
        api.transition_platform_request(
            request_x["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
        ),
        ERR_INVALID_REQUEST_STATE,
    )
    validate_error(
        api.transition_platform_request(
            request_x["id"],
            f.request_transition_payload(REQ_ACTION_WITHDRAW, withdrawal_reason="again"),
            ctx.fid_headers,
        ),
        ERR_INVALID_REQUEST_STATE,
    )
    validate_error(
        api.transition_platform_request(
            request_y["id"], f.request_transition_payload(REQ_ACTION_START_REVIEW), desk
        ),
        ERR_INVALID_REQUEST_STATE,
    )
    validate_error(
        api.transition_platform_request(
            request_y["id"],
            f.request_transition_payload(REQ_ACTION_DECIDE, decision=DECISION_APPROVED),
            desk,
        ),
        ERR_INVALID_REQUEST_STATE,
    )

    grants, _ = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert grants == [], f"A DENIED decision grants nothing, got {grants}"

    asset_after = fx.read_asset(api, ctx, asset["id"])
    assert_fields(asset_after, access_status=ACCESS_UNVERIFIED)
    assert_null_fields(asset_after, "disclosed_at")

    estate_after = fx.read_estate(api, ctx)
    assert_fields(
        estate_after, administration_phase=PHASE_AUTHORIZED, disclosed_asset_count=0
    )


def test_newly_created_rows_start_in_their_declared_initial_state(api):
    """
    Every stateful row is born in the state the contract declares and never in a later one: a
    document PENDING, a directive RECORDED with its server-assigned rank, an account UNVERIFIED
    and PENDING with ACTIVE subscription billing, a term ACTIVE with term_days from the inclusive
    span, and a package DRAFT with a zero cycle count and no frozen resolution.

    PRD: "Every document is filed with `verification_status` at `PENDING`, and with `verified_by_user_id`, `verified_at` and `revocation_reason` all null."
    PRD: "`precedence_rank` is never client-supplied: it is 1 for an `ONLINE_TOOL` directive and 2 for both `WILL_PROVISION` and `TRUST_PROVISION`, and a lower rank wins. `status` opens at `RECORDED`."
    PRD: "A newly inventoried account opens at `access_status` `UNVERIFIED`, `content_clamp_reason` `NONE`, and `disposition_status` `PENDING`, with `disclosed_at`, `disposed_at`, `appraised_value_cents` and `appraised_basis` all null. Its `subscription_billing_state` opens at `ACTIVE` when its `category` is `SUBSCRIPTION` and at `NOT_APPLICABLE` for every other category."
    PRD: "The term is a **closed** interval: both endpoints are inside it, so `term_days` is the number of days from `term_start_date` to `term_end_date` plus one, and a term whose two dates are equal is one day long."
    PRD: "A drafted package opens with `status` at `DRAFT`, `info_cycle_count` at 0, `review_window_start` and `review_window_end` null, and `decision`, `decision_note`, `missing_items`, `remediation_note`, `withdrawal_reason`, `resolved_scope` and `resolved_basis` all null, with `clamp_reason` at `NONE`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(api, supports_online_tool=True)
    estate = fx.open_estate(api, court_case_number="PR-2737-C13")
    fid = fx.appoint_fiduciary(api, estate["id"], court_reference="APPT-2737-C13")
    dc = fx.add_document(api, estate["id"], f.document_payload(reference_number="DC-C13"))
    assert_fields(dc, verification_status=DOC_PENDING)
    assert_null_fields(dc, "verified_by_user_id", "verified_at", "revocation_reason")
    fx.verify_document(api, dc["id"])
    loa = fx.add_document(
        api, estate["id"], f.letters_document_payload(fid["id"], reference_number="LOA-C13")
    )
    fx.verify_document(api, loa["id"])
    ctx = fx.EstateContext(
        estate_id=estate["id"],
        fiduciary_id=fid["id"],
        death_certificate_id=dc["id"],
        letters_id=loa["id"],
        fiduciary_headers=make_fiduciary_headers(fid["id"]),
    )

    online_tool = validate_success(
        api.create_authority_directive(
            ctx.estate_id,
            f.directive_payload(
                directive_type=DIRECTIVE_ONLINE_TOOL,
                scope=SCOPE_CATALOG_AND_CONTENT,
                platform_id=platform["id"],
                instrument_reference="Legacy Contact screen",
                executed_on="2025-11-02",
            ),
            ctx.fid_headers,
        ),
        201,
    )
    assert_fields(
        online_tool,
        status=DIRECTIVE_STATUS_RECORDED,
        precedence_rank=PRECEDENCE_RANK_ONLINE_TOOL,
    )

    will = validate_success(
        api.create_authority_directive(
            ctx.estate_id,
            f.directive_payload(
                directive_type=DIRECTIVE_WILL_PROVISION,
                scope=SCOPE_CATALOG_ONLY,
                instrument_reference="Will article 7.2",
                executed_on="2025-06-01",
            ),
            COURT_REGISTRAR_HEADERS,
        ),
        201,
    )
    assert_fields(
        will,
        status=DIRECTIVE_STATUS_RECORDED,
        precedence_rank=PRECEDENCE_RANK_INSTRUMENT,
    )

    asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_SUBSCRIPTION,
        account_handle="stream-premium",
        quoted_value_cents=0,
    )
    assert_fields(
        asset,
        access_status=ACCESS_UNVERIFIED,
        content_clamp_reason=CLAMP_NONE,
        disposition_status=DISPOSITION_PENDING,
        subscription_billing_state=BILLING_ACTIVE,
        transferability=LICENSE_TERMINATES_AT_DEATH,
        transferability_reason=REASON_CATEGORY_SUBSCRIPTION_LICENCE,
    )
    assert_null_fields(
        asset, "disclosed_at", "disposed_at", "appraised_value_cents", "appraised_basis"
    )

    term = fx.add_subscription_term(
        api,
        ctx,
        asset["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        billing_interval=BILLING_INTERVAL_ANNUAL,
        period_fee_cents=11999,
        auto_renew=True,
    )
    assert_fields(term, state=TERM_ACTIVE, term_days=365, claimed_days_total=0)
    assert_null_fields(term, "cancelled_effective_date")

    request = fx.draft_request(api, ctx, platform["id"], platform["form_code"])
    assert_fields(request, status=REQUEST_DRAFT, info_cycle_count=0, clamp_reason=CLAMP_NONE)
    assert_null_fields(
        request,
        "review_window_start",
        "review_window_end",
        "decision",
        "decision_note",
        "missing_items",
        "remediation_note",
        "withdrawal_reason",
        "resolved_scope",
        "resolved_basis",
    )


def test_a_second_subscription_term_and_a_non_subscription_term_share_one_error(api):
    """
    The one-term-per-account rule and the subscription-only rule are reported with the same code:
    a second term on the subscription account and a first term on a cloud-storage account are both
    refused with ERR_SUBSCRIPTION_TERM_EXISTS.

    PRD: "An account may carry at most one term, and only an account whose `category` is `SUBSCRIPTION` may carry one at all; both a second term on the same account and a first term on an account of any other category are refused with the single code `ERR_SUBSCRIPTION_TERM_EXISTS`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(api, supports_online_tool=True)
    ctx = fx.authorized_estate(api, "PR-2737-C13B")
    sub_asset = fx.add_subscription_asset(api, ctx, platform["id"], account_handle="stream-premium")
    cloud_asset = fx.add_asset(
        api, ctx, platform["id"], category=CATEGORY_CLOUD_STORAGE, account_handle="stream-drive"
    )
    fx.add_subscription_term(
        api,
        ctx,
        sub_asset["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        billing_interval=BILLING_INTERVAL_ANNUAL,
        period_fee_cents=11999,
        auto_renew=True,
    )

    validate_error(
        api.create_subscription_term(
            sub_asset["id"], f.subscription_term_payload(), ctx.fid_headers
        ),
        ERR_SUBSCRIPTION_TERM_EXISTS,
    )
    validate_error(
        api.create_subscription_term(
            cloud_asset["id"], f.subscription_term_payload(), ctx.fid_headers
        ),
        ERR_SUBSCRIPTION_TERM_EXISTS,
    )


def test_document_verification_and_revocation_are_each_single_shot(api):
    """
    A second VERIFY on an already VERIFIED document is refused, and REVOKED is terminal for both
    entry paths: a PENDING court order may be revoked directly, cascades nowhere, and afterwards
    refuses both VERIFY and a second REVOKE. None of the refusals moves any version.

    PRD: "Verifying a document that is already `VERIFIED`, or one that has been `REVOKED`, is rejected with `ERR_INVALID_DOCUMENT_STATE`."
    PRD: "Both paths store the supplied `revocation_reason`, but they differ sharply in consequence: revoking a document that was still `PENDING` has no downstream effect at all, because a pending document never conferred anything, and only that document's `version` moves."

    Design: Corner/state_machines/document_verification_and_revocation_are_each_single_shot
    """
    fx.set_clock(api, CLOCK_EPOCH)
    estate = fx.open_estate(api, court_case_number="PR-2737-C14")
    fid = fx.appoint_fiduciary(api, estate["id"], court_reference="APPT-2737-C14")
    dc = fx.add_document(api, estate["id"], f.document_payload(reference_number="DC-C14"))
    court_order = fx.add_document(
        api, estate["id"], f.court_order_document_payload(reference_number="CO-C14")
    )
    fx.verify_document(api, dc["id"])
    estate_before = validate_success(api.get_estate(estate["id"], COURT_REGISTRAR_HEADERS), 200)

    validate_error(
        api.transition_document(
            dc["id"], f.document_transition_payload(DOC_ACTION_VERIFY), COURT_REGISTRAR_HEADERS
        ),
        ERR_INVALID_DOCUMENT_STATE,
    )
    dc_after = validate_success(api.get_document(dc["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(dc_after, verification_status=DOC_VERIFIED, version=2)

    revoked = validate_success(
        api.transition_document(
            court_order["id"],
            f.document_transition_payload(
                DOC_ACTION_REVOKE, revocation_reason="superseded by a later order"
            ),
            COURT_REGISTRAR_HEADERS,
        ),
        200,
    )
    assert_fields(
        revoked,
        verification_status=DOC_REVOKED,
        revocation_reason="superseded by a later order",
    )
    assert_null_fields(revoked, "verified_at")

    validate_error(
        api.transition_document(
            court_order["id"],
            f.document_transition_payload(DOC_ACTION_VERIFY),
            COURT_REGISTRAR_HEADERS,
        ),
        ERR_INVALID_DOCUMENT_STATE,
    )
    validate_error(
        api.transition_document(
            court_order["id"],
            f.document_transition_payload(DOC_ACTION_REVOKE, revocation_reason="again"),
            COURT_REGISTRAR_HEADERS,
        ),
        ERR_INVALID_DOCUMENT_STATE,
    )

    fid_after = validate_success(api.get_fiduciary(fid["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(fid_after, letters_status=LETTERS_PENDING, version=1)

    estate_after = validate_success(api.get_estate(estate["id"], COURT_REGISTRAR_HEADERS), 200)
    assert_fields(
        estate_after,
        administration_phase=PHASE_INTAKE,
        version=estate_before["version"],
    )


def test_registrar_grant_revocation_revokes_disclosure_and_lowers_the_phase(api):
    """
    A registrar revocation writes revocation_reason REGISTRAR_ORDER, drags the covered disclosed
    account to ACCESS_REVOKED without clearing its disclosed_at, and re-derives the estate from
    DISCLOSURE back to AUTHORIZED because disclosed_asset_count returns to 0. The approved request
    is not rewound, and a second revocation is refused.

    PRD: "A `CourtRegistrar` may revoke a grant outright, advancing its `status` from `ACTIVE` to the terminal `REVOKED`, storing an optional `reason` and setting `revocation_reason` to `REGISTRAR_ORDER`. The revocation cascades two hops: every account of the covered estate and provider whose `access_status` is `CATALOG_DISCLOSED` or `CONTENT_DISCLOSED` is walked in ascending `created_at` order and dropped to `ACCESS_REVOKED`, and then the estate's counters are recomputed and its phase re-derived. Revoking a grant that is not `ACTIVE` is rejected with `ERR_INVALID_GRANT_STATE`."

    Design: Corner/state_machines/registrar_grant_revocation_revokes_disclosure_and_lowers_the_phase
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C15")
    asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=90000,
    )
    request = fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    grant = fx.grant_for_request(api, ctx, request["id"])
    assert_fields(grant, status=GRANT_ACTIVE, basis=BASIS_STATUTORY_DEFAULT)

    estate_before = fx.read_estate(api, ctx)
    assert_fields(
        estate_before, disclosed_asset_count=1, administration_phase=PHASE_DISCLOSURE
    )

    revoked = validate_success(
        api.transition_authority_grant(
            grant["id"],
            f.grant_transition_payload(
                GRANT_ACTION_REVOKE, reason="registrar vacated the letters pending a hearing"
            ),
            COURT_REGISTRAR_HEADERS,
        ),
        200,
    )
    assert_fields(
        revoked, status=GRANT_REVOKED, revocation_reason=REVOCATION_REGISTRAR_ORDER
    )

    asset_after = fx.read_asset(api, ctx, asset["id"])
    assert_fields(
        asset_after, access_status=ACCESS_REVOKED, content_clamp_reason=CLAMP_NONE
    )
    assert asset_after["disclosed_at"] is not None, (
        "the revocation changes access_status only; disclosed_at records first disclosure"
    )

    estate_after = fx.read_estate(api, ctx)
    assert_fields(
        estate_after,
        disclosed_asset_count=0,
        administration_phase=PHASE_AUTHORIZED,
        inventory_total_count=1,
        assets_pending_disposition_count=1,
        assets_disposed_count=0,
    )

    validate_error(
        api.transition_authority_grant(
            grant["id"],
            f.grant_transition_payload(GRANT_ACTION_REVOKE, reason="second attempt"),
            COURT_REGISTRAR_HEADERS,
        ),
        ERR_INVALID_GRANT_STATE,
    )

    assert_fields(fx.read_request(api, ctx, request["id"]), status=REQUEST_APPROVED)


def test_grant_expiry_sweep_fires_at_the_inclusive_boundary_and_repeats_as_zero(api):
    """
    A grant opened at the epoch expires 90 days later: a sweep one day early expires nothing while
    already lapsing the ended non-renewing term, the sweep on the exact expiry instant expires the
    grant and revokes both covered accounts because the boundary is inclusive, and an immediately
    repeated sweep reports every count as 0 and touches nothing.

    PRD: "The sweep visits every `ACTIVE` grant of the estate whose `expires_at` is at or before the current clock instant, in ascending `created_at` order, and moves each to the terminal `EXPIRED` with `revocation_reason` set to `TERM_EXPIRED`; the boundary is inclusive, so a grant whose `expires_at` equals the clock exactly does expire."
    PRD: "The same sweep also ages out billing: every `SubscriptionTerm` of the estate in `ACTIVE` state whose `term_end_date` falls strictly before the clock's calendar date and whose `auto_renew` is false moves to the terminal `LAPSED`."
    PRD: "It is idempotent with respect to a fixed clock: running it a second time without advancing the clock finds nothing left to do and returns all three counts as 0."

    Design: Corner/state_machines/grant_expiry_sweep_fires_at_the_inclusive_boundary_and_repeats_as_zero
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api, refund_policy=REFUND_POLICY_PRORATA_DAILY)
    ctx = fx.authorized_estate(api, "PR-2737-C16")
    cloud_asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=90000,
    )
    sub_asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_SUBSCRIPTION,
        account_handle="vault-plus",
        quoted_value_cents=0,
    )
    term = fx.add_subscription_term(
        api,
        ctx,
        sub_asset["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-09-30",
        billing_interval=BILLING_INTERVAL_ANNUAL,
        period_fee_cents=9000,
        auto_renew=False,
    )
    assert_fields(term, state=TERM_ACTIVE, term_days=273)

    request = fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    grant = fx.grant_for_request(api, ctx, request["id"])
    assert grant["effective_from"].startswith("2026-08-01T00:00:00"), (
        f"effective_from must be the clock instant, got {grant['effective_from']!r}"
    )
    assert grant["expires_at"].startswith("2026-10-30T00:00:00"), (
        f"expires_at must be 90 days after the clock, got {grant['expires_at']!r}"
    )

    fx.set_clock(api, "2026-10-29T00:00:00Z")
    sweep_one = validate_success(
        api.run_grant_expiry_sweep(ctx.estate_id, ESTATE_ADMIN_HEADERS), 200
    )
    assert_fields(
        sweep_one, expired_grant_count=0, revoked_asset_count=0, lapsed_term_count=1
    )
    assert sweep_one["swept_at"].startswith("2026-10-29T00:00:00"), (
        f"swept_at must be the clock instant, got {sweep_one['swept_at']!r}"
    )
    assert_fields(fx.read_grant(api, ctx, grant["id"]), status=GRANT_ACTIVE)
    assert_fields(fx.read_term(api, ctx, term["id"]), state=TERM_LAPSED)

    fx.set_clock(api, "2026-10-30T00:00:00Z")
    sweep_two = validate_success(
        api.run_grant_expiry_sweep(ctx.estate_id, ESTATE_ADMIN_HEADERS), 200
    )
    assert_fields(
        sweep_two, expired_grant_count=1, revoked_asset_count=2, lapsed_term_count=0
    )
    grant_expired = fx.read_grant(api, ctx, grant["id"])
    assert_fields(
        grant_expired, status=GRANT_EXPIRED, revocation_reason=REVOCATION_TERM_EXPIRED
    )
    assert_fields(fx.read_asset(api, ctx, cloud_asset["id"]), access_status=ACCESS_REVOKED)
    assert_fields(fx.read_asset(api, ctx, sub_asset["id"]), access_status=ACCESS_REVOKED)

    sweep_three = validate_success(
        api.run_grant_expiry_sweep(ctx.estate_id, ESTATE_ADMIN_HEADERS), 200
    )
    assert_fields(
        sweep_three, expired_grant_count=0, revoked_asset_count=0, lapsed_term_count=0
    )
    assert_fields(fx.read_grant(api, ctx, grant["id"]), version=grant_expired["version"])

    estate_after = fx.read_estate(api, ctx)
    assert_fields(
        estate_after,
        disclosed_asset_count=0,
        administration_phase=PHASE_AUTHORIZED,
        open_cancellation_count=1,
    )


def test_a_failed_cancellation_order_is_retried_with_a_new_effective_date(api):
    """
    A cancellation order refuses an effective date before the death, is requested with a valid one,
    is failed by the provider without disturbing the term, is then re-requested from the non-terminal
    FAILED state with a fresh effective date that overwrites the old one, and only the confirmation
    cancels the term and the account's billing — after which a second confirmation is refused.

    PRD: "Two conditions guard the request: the account's `access_status` must be `CATALOG_DISCLOSED` or `CONTENT_DISCLOSED`, because a fiduciary may not act against an account no provider has disclosed to them, and the supplied `effective_date` must fall on or after the estate's `date_of_death`, with equality accepted and an earlier date rejected as `ERR_EFFECTIVE_DATE_BEFORE_DEATH`."
    PRD: "Failing advances `REQUESTED → FAILED` and stores the provider's `failure_reason`, and it changes nothing else — the term stays `ACTIVE` and its `auto_renew` is left exactly as it was, because a failed cancellation attempt has not stopped anything."
    PRD: "A `Fiduciary` may request again from `FAILED`, which returns the order to `REQUESTED`, overwrites `effective_date` with the new one, clears `failure_reason` and re-stamps `requested_at`; the disclosure and date-of-death guards apply to the retry just as they did to the first attempt."
    PRD: "Acting on an order whose current `status` does not define the action is rejected with `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/a_failed_cancellation_order_is_retried_with_a_new_effective_date
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C17", date_of_death="2026-02-14")
    asset = fx.add_subscription_asset(api, ctx, platform["id"])
    term = fx.add_subscription_term(api, ctx, asset["id"])
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])

    order = fx.cancellation_order_for_asset(api, ctx, asset["id"])
    assert_fields(
        order, status=ORDER_PENDING, refund_policy_snapshot=REFUND_POLICY_PRORATA_DAILY
    )
    assert_null_fields(order, "effective_date", "requested_at", "confirmed_at", "failure_reason")

    too_early = api.transition_cancellation_order(
        order["id"],
        f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date="2026-02-13"),
        ctx.fid_headers,
    )
    validate_error(too_early, ERR_EFFECTIVE_DATE_BEFORE_DEATH)
    still_pending = fx.read_order(api, ctx, order["id"])
    assert_fields(still_pending, status=ORDER_PENDING)
    assert_null_fields(still_pending, "effective_date", "requested_at")

    requested = validate_success(
        api.transition_cancellation_order(
            order["id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date="2026-03-15"),
            ctx.fid_headers,
        ),
        200,
    )
    assert_fields(requested, status=ORDER_REQUESTED, effective_date="2026-03-15")
    assert requested["requested_at"].startswith("2026-08-01T00:00:00"), (
        f"requested_at must be the clock instant, got {requested['requested_at']!r}"
    )

    failed = validate_success(
        api.transition_cancellation_order(
            order["id"],
            f.order_transition_payload(
                ORDER_ACTION_FAIL, reason="provider could not match the account"
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        200,
    )
    assert_fields(
        failed,
        status=ORDER_FAILED,
        failure_reason="provider could not match the account",
        effective_date="2026-03-15",
    )
    term_after_failure = fx.read_term(api, ctx, term["id"])
    assert_fields(term_after_failure, state=TERM_ACTIVE, auto_renew=True)
    assert_null_fields(term_after_failure, "cancelled_effective_date")
    assert_fields(
        fx.read_asset(api, ctx, asset["id"]), subscription_billing_state=BILLING_ACTIVE
    )

    retried = validate_success(
        api.transition_cancellation_order(
            order["id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date="2026-04-01"),
            ctx.fid_headers,
        ),
        200,
    )
    assert_fields(retried, status=ORDER_REQUESTED, effective_date="2026-04-01")
    assert_null_fields(retried, "failure_reason")

    confirmed = validate_success(
        api.transition_cancellation_order(
            order["id"],
            f.order_transition_payload(
                ORDER_ACTION_CONFIRM, platform_reference="SO-CANCEL-77", auto_renew_stopped=True
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        200,
    )
    assert_fields(
        confirmed,
        status=ORDER_CONFIRMED,
        platform_reference="SO-CANCEL-77",
        effective_date="2026-04-01",
    )
    assert confirmed["confirmed_at"].startswith("2026-08-01T00:00:00"), (
        f"confirmed_at must be the clock instant, got {confirmed['confirmed_at']!r}"
    )
    assert_fields(
        fx.read_term(api, ctx, term["id"]),
        state=TERM_CANCELLED,
        auto_renew=False,
        cancelled_effective_date="2026-04-01",
    )
    assert_fields(
        fx.read_asset(api, ctx, asset["id"]), subscription_billing_state=BILLING_CANCELLED
    )
    assert_fields(
        fx.read_estate(api, ctx), open_cancellation_count=0, cancelled_subscription_count=1
    )

    again = api.transition_cancellation_order(
        order["id"],
        f.order_transition_payload(
            ORDER_ACTION_CONFIRM, platform_reference="SO-CANCEL-78", auto_renew_stopped=True
        ),
        make_platform_compliance_headers(platform["id"]),
    )
    validate_error(again, ERR_INVALID_ORDER_STATE)
    assert_fields(
        fx.read_order(api, ctx, order["id"]),
        status=ORDER_CONFIRMED,
        platform_reference="SO-CANCEL-77",
    )


def test_an_escalated_refund_claim_can_still_be_credited_but_not_denied_after(api):
    """
    A refund claim cannot be credited straight out of FILED, reaches ESCALATED only through
    PLATFORM_REVIEW, refuses a second escalation, and from ESCALATED is still creditable in full —
    after which the terminal credit refuses a denial and the estate's recovery ledger holds.

    PRD: "The provider's desk opens the file, advancing `FILED → PLATFORM_REVIEW`. From there the `Fiduciary` may escalate, advancing `PLATFORM_REVIEW → ESCALATED` and storing an `escalation_reason`; escalation is a detour, not an exit, and both `PLATFORM_REVIEW` and `ESCALATED` lead to the same two provider decisions."
    PRD: "Crediting advances the claim to `CREDITED`, stores the `credited_cents` the provider actually paid — which must not exceed `claimed_cents`, with an exactly equal credit accepted and a larger one rejected as `ERR_CREDIT_EXCEEDS_CLAIM` — and adds that amount to the estate's `refund_recovered_cents`."
    PRD: "Acting on a claim whose current `status` does not define the action — crediting one still in `FILED`, or escalating one already `DENIED` — is rejected with `ERR_INVALID_CLAIM_STATE`."

    Design: Corner/state_machines/an_escalated_refund_claim_can_still_be_credited_but_not_denied_after
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C18")
    bundle = fx.subscription_with_confirmed_order(
        api, ctx, platform, effective_date="2026-04-01"
    )
    term_id = bundle["term"]["id"]
    platform_headers = make_platform_compliance_headers(platform["id"])

    claim = fx.file_refund_claim(
        api, ctx, bundle["order"]["id"], "2026-05-01", "2026-06-30", pursuit_cost_cents=500
    )
    assert_fields(
        claim,
        status=CLAIM_FILED,
        claimed_days=61,
        method=METHOD_PRORATA_DAILY,
        claimed_cents=2005,
        credited_cents=0,
    )
    assert_fields(fx.read_term(api, ctx, term_id), claimed_days_total=61)

    too_soon = api.transition_refund_claim(
        claim["id"],
        f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=2005),
        platform_headers,
    )
    validate_error(too_soon, ERR_INVALID_CLAIM_STATE)
    assert_fields(
        fx.read_claim(api, ctx, claim["id"]), status=CLAIM_FILED, credited_cents=0
    )

    in_review = validate_success(
        api.transition_refund_claim(
            claim["id"], f.claim_transition_payload(CLAIM_ACTION_START_REVIEW), platform_headers
        ),
        200,
    )
    assert_fields(in_review, status=CLAIM_PLATFORM_REVIEW)

    escalated = validate_success(
        api.transition_refund_claim(
            claim["id"],
            f.claim_transition_payload(
                CLAIM_ACTION_ESCALATE, escalation_reason="desk has not answered in fourteen days"
            ),
            ctx.fid_headers,
        ),
        200,
    )
    assert_fields(
        escalated,
        status=CLAIM_ESCALATED,
        escalation_reason="desk has not answered in fourteen days",
    )

    double_escalation = api.transition_refund_claim(
        claim["id"],
        f.claim_transition_payload(CLAIM_ACTION_ESCALATE, escalation_reason="again"),
        ctx.fid_headers,
    )
    validate_error(double_escalation, ERR_INVALID_CLAIM_STATE)
    assert_fields(fx.read_claim(api, ctx, claim["id"]), status=CLAIM_ESCALATED)

    credited = validate_success(
        api.transition_refund_claim(
            claim["id"],
            f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=2005),
            platform_headers,
        ),
        200,
    )
    assert_fields(credited, status=CLAIM_CREDITED, credited_cents=2005)
    assert_fields(fx.read_estate(api, ctx), refund_recovered_cents=2005)

    late_denial = api.transition_refund_claim(
        claim["id"],
        f.claim_transition_payload(CLAIM_ACTION_DENY, reason="changed our mind"),
        platform_headers,
    )
    validate_error(late_denial, ERR_INVALID_CLAIM_STATE)
    final_claim = fx.read_claim(api, ctx, claim["id"])
    assert_fields(final_claim, status=CLAIM_CREDITED, credited_cents=2005)
    assert_null_fields(final_claim, "denial_reason")
    assert_fields(fx.read_term(api, ctx, term_id), claimed_days_total=61)
    assert_fields(fx.read_estate(api, ctx), refund_recovered_cents=2005)


def test_access_status_and_disposition_status_move_as_independent_dimensions(api):
    """
    Disclosure and disposal are two independent dimensions of the same account: an approval moves
    only the access dimension, submitting an election moves only the disposition dimension, and a
    registrar revocation drops the account back to ACCESS_REVOKED while its ELECTED disposition and
    its election both stand untouched.

    PRD: "Neither dimension is a precondition of the other except where this document says so explicitly, and `PURGED` is the one terminal posture from which nothing returns."
    PRD: "Submission sets the account's `disposition_status` to `ELECTED`, recomputes the estate's disposition counters and re-derives the phase."

    Design: Corner/state_machines/access_status_and_disposition_status_move_as_independent_dimensions
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C19")
    asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=90000,
    )
    assert_fields(
        asset, access_status=ACCESS_UNVERIFIED, disposition_status=DISPOSITION_PENDING
    )

    request = fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    disclosed = fx.read_asset(api, ctx, asset["id"])
    assert_fields(
        disclosed,
        access_status=ACCESS_CATALOG_DISCLOSED,
        disposition_status=DISPOSITION_PENDING,
    )
    assert_fields(
        fx.read_estate(api, ctx),
        disclosed_asset_count=1,
        assets_pending_disposition_count=1,
        administration_phase=PHASE_DISCLOSURE,
    )

    election = fx.draft_election(
        api, ctx, asset["id"], election=ELECTION_MEMORIALIZE, election_note="family tribute page"
    )
    assert_fields(election, status=ELECTION_DRAFT)
    submitted = validate_success(
        api.transition_disposition_election(
            election["id"], f.election_transition_payload(EL_ACTION_SUBMIT), ctx.fid_headers
        ),
        200,
    )
    assert_fields(submitted, status=ELECTION_SUBMITTED)
    elected_asset = fx.read_asset(api, ctx, asset["id"])
    assert_fields(
        elected_asset,
        access_status=ACCESS_CATALOG_DISCLOSED,
        disposition_status=DISPOSITION_ELECTED,
    )

    grant = fx.grant_for_request(api, ctx, request["id"])
    revoked = validate_success(
        api.transition_authority_grant(
            grant["id"],
            f.grant_transition_payload(GRANT_ACTION_REVOKE, reason="letters challenged in court"),
            COURT_REGISTRAR_HEADERS,
        ),
        200,
    )
    assert_fields(revoked, status=GRANT_REVOKED)

    final_asset = fx.read_asset(api, ctx, asset["id"])
    assert_fields(
        final_asset,
        access_status=ACCESS_REVOKED,
        disposition_status=DISPOSITION_ELECTED,
        content_clamp_reason=CLAMP_NONE,
    )
    assert_fields(
        fx.read_estate(api, ctx),
        inventory_total_count=1,
        disclosed_asset_count=0,
        assets_pending_disposition_count=1,
        assets_disposed_count=0,
        administration_phase=PHASE_AUTHORIZED,
    )
    final_election = fx.read_election(api, ctx, election["id"])
    assert_fields(final_election, status=ELECTION_SUBMITTED)
    assert_null_fields(final_election, "executed_at")
