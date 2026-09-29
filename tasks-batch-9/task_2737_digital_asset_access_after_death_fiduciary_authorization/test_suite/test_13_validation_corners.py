"""
Validation corners of the Digital Estate Fiduciary Access API.

These tests probe the rejection ladder where two rules could plausibly both
apply and the contract fixes which one speaks: a body reference that does not
resolve outranks every business rule beneath it, the once-per-estate
finalization guard outranks a fresh recomputation, a clamped content request
names the court order rather than the missing authority, and the four closure
gates fire in their declared order as each blocker is cleared. Every test builds
its own world from an empty database with the clock at the fresh-server epoch.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assert_fields, factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSETS_PENDING_DISPOSITION,
    ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED,
    ERR_COURT_ORDER_REQUIRED,
    ERR_DESIGNATION_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_ESTATE_CLOSED,
    ERR_FIDUCIARY_NOT_FOUND,
    ERR_INVALID_RUN_STATE,
    ERR_OPEN_CANCELLATIONS,
    ERR_OPEN_REFUND_CLAIMS,
    ERR_PLATFORM_NOT_FOUND,
    ERR_VALUATION_ALREADY_FINALIZED,
    ERR_VALUATION_NOT_FINALIZED,
)
from test_helpers.constants import (
    ACCESS_CONTENT_DISCLOSED,
    BASIS_DATE_OF_DEATH,
    BASIS_WILL_PROVISION,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_EMAIL,
    CLAIM_ACTION_DENY,
    CLAIM_ACTION_START_REVIEW,
    CLAIM_DENIED,
    CLAMP_COURT_ORDER_REQUIRED,
    CLAMP_NONE,
    DIRECTIVE_ONLINE_TOOL,
    DIRECTIVE_WILL_PROVISION,
    ELECTION_MEMORIALIZE,
    ELECTION_TRANSFER,
    NON_TRANSFERABLE,
    ORDER_PENDING,
    PHASE_CLOSED,
    REFUND_POLICY_PRORATA_DAILY,
    REQ_ACTION_SUBMIT,
    REQUEST_SUBMITTED,
    REQUEST_TYPE_CONTENT_ACCESS,
    RUN_ACTION_FINALIZE,
    RUN_COMPUTED,
    RUN_FINALIZED,
    RUN_SUPERSEDED,
    SCOPE_CATALOG_AND_CONTENT,
    SCOPE_CATALOG_ONLY,
    TRANSFERABLE,
)
from test_helpers.test_users import COURT_REGISTRAR_HEADERS, make_platform_compliance_headers

MISSING_UUID = "00000000-0000-0000-0000-000000000000"


def test_body_foreign_keys_are_resolved_before_any_business_rule(api):
    """
    Five writes each carry one body reference that does not resolve, and every
    one of them is answered by the existence error for that reference rather
    than by the business rule waiting underneath it: an online tool directive
    against a missing provider is not answered by the online tool guard, a
    request citing a missing certificate is not answered by the form-code
    mismatch it also carries, and a transfer election naming a missing
    designation is not answered by the account's transferability. Nothing is
    created by any of them.

    PRD: "The server therefore evaluates its validations in one strict, globally ordered ladder and returns on the **first** violation it finds; no later check runs, and no later error can mask an earlier one."

    PRD: "**Body-reference existence**, in this order: a `platform_id` in the body (`ERR_PLATFORM_NOT_FOUND`), a `fiduciary_id` in the body (`ERR_FIDUCIARY_NOT_FOUND`), then `death_certificate_document_id` and `letters_document_id` in that order (`ERR_DOCUMENT_NOT_FOUND`), then `beneficiary_designation_id` (`ERR_DESIGNATION_NOT_FOUND`) — all HTTP 404."

    Design: Corner/validations/body_foreign_keys_are_resolved_before_any_business_rule
    """
    fx.set_clock(api)
    mail = fx.register_platform(
        api,
        name="MailWorks",
        platform_type="EMAIL",
        form_code="MW-FORM-3",
        review_window_days=21,
        supports_transfer=False,
        supports_memorialization=False,
        license_terminates_at_death=True,
    )
    ctx = fx.authorized_estate(api, "PR-2737-C27")
    mailbox = fx.add_asset(
        api,
        ctx,
        mail["id"],
        category=CATEGORY_EMAIL,
        account_handle="mail-1",
        quoted_value_cents=50000,
    )
    assert mailbox["transferability"] == NON_TRANSFERABLE

    _, documents_before = validate_paginated(
        api.list_documents(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    version_before = fx.estate_version(api, ctx)

    # A letters document naming a fiduciary that does not exist.
    unknown_fiduciary = api.create_document(
        ctx.estate_id,
        f.letters_document_payload(MISSING_UUID, reference_number="LOA-C27-X"),
        COURT_REGISTRAR_HEADERS,
    )
    validate_error(unknown_fiduciary, ERR_FIDUCIARY_NOT_FOUND)

    # An account on a provider that does not exist.
    unknown_provider = api.create_digital_asset(
        ctx.estate_id,
        f.digital_asset_payload(
            MISSING_UUID, category=CATEGORY_CLOUD_STORAGE, account_handle="vault-x"
        ),
        ctx.fid_headers,
    )
    validate_error(unknown_provider, ERR_PLATFORM_NOT_FOUND)

    # An ONLINE_TOOL directive bound to a provider that does not exist: the
    # missing reference answers first, not the online tool support guard.
    unknown_provider_directive = api.create_authority_directive(
        ctx.estate_id,
        f.directive_payload(
            directive_type=DIRECTIVE_ONLINE_TOOL,
            scope=SCOPE_CATALOG_AND_CONTENT,
            platform_id=MISSING_UUID,
            instrument_reference="legacy contact on an unknown provider",
        ),
        COURT_REGISTRAR_HEADERS,
    )
    validate_error(unknown_provider_directive, ERR_PLATFORM_NOT_FOUND)

    # A request citing a missing death certificate and a wrong form code: the
    # document reference answers before the form-code mismatch.
    unknown_certificate = api.create_platform_request(
        ctx.estate_id,
        f.platform_request_payload(
            mail["id"], MISSING_UUID, ctx.letters_id, "NOT-THE-FORM-CODE"
        ),
        ctx.fid_headers,
    )
    validate_error(unknown_certificate, ERR_DOCUMENT_NOT_FOUND)

    # A TRANSFER election on a non-transferable account naming a designation
    # that does not exist: the missing designation answers first.
    unknown_designation = api.create_disposition_election(
        mailbox["id"],
        f.election_payload(
            mailbox["version"],
            election=ELECTION_TRANSFER,
            beneficiary_designation_id=MISSING_UUID,
        ),
        ctx.fid_headers,
    )
    validate_error(unknown_designation, ERR_DESIGNATION_NOT_FOUND)

    # Every rejection was total: no row anywhere, no version movement.
    _, documents_after = validate_paginated(
        api.list_documents(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert documents_after["total_count"] == documents_before["total_count"]
    _, assets = validate_paginated(
        api.list_digital_assets(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert assets["total_count"] == 1
    _, directives = validate_paginated(
        api.list_authority_directives(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert directives["total_count"] == 0
    _, requests = validate_paginated(
        api.list_platform_requests(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert requests["total_count"] == 0
    _, elections = validate_paginated(
        api.list_disposition_elections(ctx.fid_headers, asset_id=mailbox["id"])
    )
    assert elections["total_count"] == 0
    assert fx.estate_version(api, ctx) == version_before
    assert fx.read_asset(api, ctx, mailbox["id"])["version"] == mailbox["version"]


def test_only_one_valuation_run_per_estate_may_ever_be_finalized(api):
    """
    A second run supersedes the first, so the superseded run can no longer be
    finalized; the live run can, exactly once; and once it is finalized no
    further run may be created at all.

    PRD: "Only a `COMPUTED` run may be finalized — finalizing a `SUPERSEDED` or already-`FINALIZED` run is rejected with `ERR_INVALID_RUN_STATE` — and because finalization blocks all further runs, it happens exactly once per estate."

    PRD: "No run at all may be created once any run on the estate has reached `FINALIZED`, which is refused with `ERR_VALUATION_ALREADY_FINALIZED`: the finalized number is the estate's answer and re-running would invalidate it."

    Design: Corner/validations/only_one_valuation_run_per_estate_may_ever_be_finalized
    """
    fx.set_clock(api)
    cloud = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C28")
    vault = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=200000,
    )
    assert vault["transferability"] == TRANSFERABLE
    fx.approved_request(api, ctx, cloud["id"], cloud["form_code"])
    fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives")

    first = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    second = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert second["status"] == RUN_COMPUTED
    assert fx.read_run(api, ctx, first["id"])["status"] == RUN_SUPERSEDED

    superseded = api.transition_valuation_run(
        first["id"],
        f.run_transition_payload(
            RUN_ACTION_FINALIZE, finalization_note="Locking the superseded run."
        ),
        ctx.fid_headers,
    )
    validate_error(superseded, ERR_INVALID_RUN_STATE)

    finalized = validate_success(
        api.transition_valuation_run(
            second["id"],
            f.run_transition_payload(
                RUN_ACTION_FINALIZE, finalization_note="Estate tax position locked."
            ),
            ctx.fid_headers,
        ),
        200,
    )
    assert_fields(
        finalized,
        status=RUN_FINALIZED,
        gross_value_cents=200000,
        taxable_value_cents=200000,
        finalization_note="Estate tax position locked.",
    )
    assert finalized["finalized_at"] is not None
    assert finalized["finalized_at"].startswith("2026-08-01")

    again = api.transition_valuation_run(
        second["id"], f.run_transition_payload(RUN_ACTION_FINALIZE), ctx.fid_headers
    )
    validate_error(again, ERR_INVALID_RUN_STATE)

    third = api.create_valuation_run(
        ctx.estate_id,
        f.valuation_run_payload(fx.estate_version(api, ctx), basis=BASIS_DATE_OF_DEATH),
        ctx.fid_headers,
    )
    validate_error(third, ERR_VALUATION_ALREADY_FINALIZED)

    _, runs = validate_paginated(
        api.list_valuation_runs(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert runs["total_count"] == 2
    still_finalized = fx.read_run(api, ctx, second["id"])
    assert still_finalized["status"] == RUN_FINALIZED
    assert still_finalized["finalized_at"] == finalized["finalized_at"]
    assert fx.read_estate(api, ctx)["valuation_basis"] == BASIS_DATE_OF_DEATH


def test_a_clamped_content_request_names_the_court_order_not_the_missing_authority(api):
    """
    When the recorded will does grant content but the provider insists on a
    court order, the submission is refused with the court-order code, and it
    stays refused while the court order sits unverified. Verifying it lifts the
    clamp and the same package sails through. An estate whose will never granted
    content past the catalogue gets the other code entirely.

    PRD: "When the `request_type` is `CONTENT_ACCESS`, the resolution of §3.3 must come out at `CATALOG_AND_CONTENT` with a `clamp_reason` of `NONE`; if the recorded directives never granted content at all, the submission is rejected with `ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED`, and if they did grant content but the provider's `requires_court_order_for_content` is true and no `VERIFIED` `COURT_ORDER` document exists on the estate, it is rejected with the more specific `ERR_COURT_ORDER_REQUIRED`."

    PRD: "Those two codes are not interchangeable: the second is only reachable when the pre-clamp scope was `CATALOG_AND_CONTENT`."

    Design: Corner/validations/a_clamped_content_request_names_the_court_order_not_the_missing_authority
    """
    fx.set_clock(api)
    cloud = fx.register_platform(api, requires_court_order_for_content=True)
    ctx = fx.authorized_estate(api, "PR-2737-C29")
    will = fx.add_directive(
        api,
        ctx,
        directive_type=DIRECTIVE_WILL_PROVISION,
        scope=SCOPE_CATALOG_AND_CONTENT,
        instrument_reference="Will article 9.1",
        executed_on="2025-06-01",
    )
    vault = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=200000,
    )
    request = fx.draft_request(
        api,
        ctx,
        cloud["id"],
        cloud["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS,
        requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )

    clamped = validate_success(
        api.get_authority_resolution(ctx.estate_id, ctx.fid_headers, platform_id=cloud["id"]),
        200,
    )
    assert_fields(
        clamped,
        resolved_scope=SCOPE_CATALOG_ONLY,
        resolved_basis=BASIS_WILL_PROVISION,
        clamp_reason=CLAMP_COURT_ORDER_REQUIRED,
        controlling_directive_id=will["id"],
    )

    no_order = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
    )
    validate_error(no_order, ERR_COURT_ORDER_REQUIRED)

    order_document = fx.add_document(
        api,
        ctx.estate_id,
        f.court_order_document_payload(reference_number="CO-C29", issued_on="2026-07-20"),
    )
    unverified_order = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
    )
    validate_error(unverified_order, ERR_COURT_ORDER_REQUIRED)

    fx.verify_document(api, order_document["id"])
    unclamped = validate_success(
        api.get_authority_resolution(ctx.estate_id, ctx.fid_headers, platform_id=cloud["id"]),
        200,
    )
    assert_fields(
        unclamped,
        resolved_scope=SCOPE_CATALOG_AND_CONTENT,
        resolved_basis=BASIS_WILL_PROVISION,
        clamp_reason=CLAMP_NONE,
    )

    submitted = validate_success(
        api.transition_platform_request(
            request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
        ),
        200,
    )
    assert submitted["status"] == REQUEST_SUBMITTED
    fx.start_review(api, cloud["id"], request["id"])
    decided = fx.decide_request(api, cloud["id"], request["id"])
    assert_fields(
        decided,
        resolved_scope=SCOPE_CATALOG_AND_CONTENT,
        resolved_basis=BASIS_WILL_PROVISION,
        clamp_reason=CLAMP_NONE,
    )
    assert_fields(
        fx.read_asset(api, ctx, vault["id"]),
        access_status=ACCESS_CONTENT_DISCLOSED,
        content_clamp_reason=CLAMP_NONE,
    )

    # A will that stops at the catalogue never reaches the court-order code.
    catalogue_only = fx.authorized_estate(api, "PR-2737-C29B")
    fx.add_directive(
        api,
        catalogue_only,
        directive_type=DIRECTIVE_WILL_PROVISION,
        scope=SCOPE_CATALOG_ONLY,
        instrument_reference="Will article 3.1",
        executed_on="2025-06-01",
    )
    narrow = fx.draft_request(
        api,
        catalogue_only,
        cloud["id"],
        cloud["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS,
        requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )
    never_granted = api.transition_platform_request(
        narrow["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), catalogue_only.fid_headers
    )
    validate_error(never_granted, ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED)


def test_each_close_guard_fires_in_priority_order_as_blockers_are_cleared(api):
    """
    One estate carries all four closure blockers at once and is closed only when
    the last of them is cleared. Each attempt names exactly the highest
    outstanding gate: the unfinalized valuation first, then the accounts still
    awaiting disposition, then the open cancellation order, then the live refund
    claim. After closure a second attempt is refused as a closed estate.

    PRD: "Four gates are checked in this order. The estate's newest non-`SUPERSEDED` valuation run must have `status` `FINALIZED`, or closure is refused with `ERR_VALUATION_NOT_FINALIZED`: the tax position must be locked first. Every account of the estate must have `disposition_status` of `EXECUTED` or `PURGED`, equivalently `assets_pending_disposition_count` at 0, or closure is refused with `ERR_ASSETS_PENDING_DISPOSITION`. Every cancellation order on the estate's accounts must be `CONFIRMED` or `FAILED`, equivalently `open_cancellation_count` at 0, or closure is refused with `ERR_OPEN_CANCELLATIONS` — note that a `FAILED` order counts as closed for this purpose, since the fiduciary has done what it could. Every refund claim of the estate must be `CREDITED`, `DENIED` or `CHARGED_BACK`, or closure is refused with `ERR_OPEN_REFUND_CLAIMS`."

    PRD: "From that moment every mutating operation anywhere beneath the estate is refused with `ERR_ESTATE_CLOSED`, including a second attempt to close it, while reads continue to work so the file remains auditable forever."

    Design: Corner/validations/each_close_guard_fires_in_priority_order_as_blockers_are_cleared
    """
    fx.set_clock(api)
    cloud = fx.register_platform(api, refund_policy=REFUND_POLICY_PRORATA_DAILY)
    ctx = fx.authorized_estate(api, "PR-2737-C30")
    vault = fx.add_asset(
        api,
        ctx,
        cloud["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-1",
        quoted_value_cents=200000,
    )
    subscription = fx.add_subscription_asset(api, ctx, cloud["id"], account_handle="sub-1")
    term = fx.add_subscription_term(api, ctx, subscription["id"])
    assert term["term_days"] == 365

    fx.approved_request(api, ctx, cloud["id"], cloud["form_code"])
    order = fx.cancellation_order_for_asset(api, ctx, subscription["id"])
    assert_fields(
        order, status=ORDER_PENDING, refund_policy_snapshot=REFUND_POLICY_PRORATA_DAILY
    )
    fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives")

    run = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert_fields(run, status=RUN_COMPUTED, included_asset_count=1, gross_value_cents=200000)

    # Gate one: the run is only COMPUTED.
    validate_error(
        api.close_estate(
            ctx.estate_id,
            f.close_estate_payload(closing_statement="Administration complete."),
            ctx.fid_headers,
        ),
        ERR_VALUATION_NOT_FINALIZED,
    )

    validate_success(
        api.transition_valuation_run(
            run["id"],
            f.run_transition_payload(
                RUN_ACTION_FINALIZE, finalization_note="Final estate tax figures."
            ),
            ctx.fid_headers,
        ),
        200,
    )

    # Gate two: both accounts are still PENDING disposition.
    validate_error(
        api.close_estate(
            ctx.estate_id,
            f.close_estate_payload(closing_statement="Administration complete."),
            ctx.fid_headers,
        ),
        ERR_ASSETS_PENDING_DISPOSITION,
    )

    fx.executed_election(
        api,
        ctx,
        cloud["id"],
        vault["id"],
        election=ELECTION_MEMORIALIZE,
        platform_confirmation_reference="CV-MEM-1",
    )
    fx.executed_election(
        api,
        ctx,
        cloud["id"],
        subscription["id"],
        election=ELECTION_MEMORIALIZE,
        platform_confirmation_reference="CV-MEM-2",
    )
    assert_fields(
        fx.read_estate(api, ctx),
        assets_pending_disposition_count=0,
        assets_disposed_count=2,
    )

    # Gate three: the auto-created cancellation order is still PENDING.
    validate_error(
        api.close_estate(
            ctx.estate_id,
            f.close_estate_payload(closing_statement="Administration complete."),
            ctx.fid_headers,
        ),
        ERR_OPEN_CANCELLATIONS,
    )

    fx.confirmed_cancellation_order(
        api,
        ctx,
        cloud["id"],
        order["id"],
        effective_date="2026-06-30",
        platform_reference="CV-CANCEL-1",
    )
    claim = fx.file_refund_claim(
        api, ctx, order["id"], "2026-05-01", "2026-06-30", pursuit_cost_cents=300
    )
    # 11999 * 61 / 365 = 2005.3123..., so 2005.
    assert claim["claimed_cents"] == 2005

    # Gate four: the claim is still live.
    validate_error(
        api.close_estate(
            ctx.estate_id,
            f.close_estate_payload(closing_statement="Administration complete."),
            ctx.fid_headers,
        ),
        ERR_OPEN_REFUND_CLAIMS,
    )

    desk = make_platform_compliance_headers(cloud["id"])
    validate_success(
        api.transition_refund_claim(
            claim["id"], f.claim_transition_payload(CLAIM_ACTION_START_REVIEW), desk
        ),
        200,
    )
    denied = validate_success(
        api.transition_refund_claim(
            claim["id"],
            f.claim_transition_payload(
                CLAIM_ACTION_DENY, denial_reason="Outside the provider's refund window."
            ),
            desk,
        ),
        200,
    )
    assert denied["status"] == CLAIM_DENIED

    closed = validate_success(
        api.close_estate(
            ctx.estate_id,
            f.close_estate_payload(closing_statement="Administration complete."),
            ctx.fid_headers,
        ),
        200,
    )
    assert_fields(
        closed,
        administration_phase=PHASE_CLOSED,
        closing_statement="Administration complete.",
    )
    assert closed["closed_at"] is not None
    assert closed["closed_at"].startswith("2026-08-01")

    second_attempt = api.close_estate(
        ctx.estate_id,
        f.close_estate_payload(closing_statement="Closing again."),
        ctx.fid_headers,
    )
    validate_error(second_attempt, ERR_ESTATE_CLOSED)
    still_closed = fx.read_estate(api, ctx)
    assert_fields(
        still_closed,
        administration_phase=PHASE_CLOSED,
        closing_statement="Administration complete.",
    )
    assert still_closed["closed_at"] == closed["closed_at"]
