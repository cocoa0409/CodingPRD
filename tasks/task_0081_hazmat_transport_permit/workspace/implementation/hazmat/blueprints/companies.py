"""The TransportCompany endpoints — six in the scaffold's §1.5 enumeration:

  POST   /v1/companies                              — file-the-initial-
                                                       qualification-application
                                                       (bootstrap identity).
  GET    /v1/companies/<company_id>                 — read-one.
  GET    /v1/companies                              — list (paginated, with
                                                       the optional
                                                       `qualification_status`
                                                       comma-list filter and
                                                       the regulator-only
                                                       cross-tenant
                                                       `company_id` filter).
  POST   /v1/companies/<company_id>/submit          — operator's
                                                       DRAFT-to-SUBMITTED
                                                       transition (and the
                                                       REVOKED-to-DRAFT-to-
                                                       SUBMITTED internal-
                                                       collapse cycle's entry
                                                       per the §3.1 paragraph).
  POST   /v1/companies/<company_id>/approve         — regulator's
                                                       SUBMITTED-to-APPROVED.
  POST   /v1/companies/<company_id>/revoke          — regulator's
                                                       APPROVED-to-REVOKED
                                                       with the required
                                                       `reason_note` body
                                                       field, and the
                                                       deferred-cascade onto
                                                       the company's ACTIVE
                                                       permits that the next
                                                       verify-compliance or
                                                       sweep-run flushes.

The auth-tier's bootstrap exemption on `POST /v1/companies` lets the very
first operator's request carry an `X-User-ID` that does not yet correspond
to a row, with the server minting the row's id; the operator's subsequent
calls carry the minted id as the `X-User-ID` and the standard
entity-backed-resolve auth check fires on those normally.

The cross-tenant ownership check on the four per-row endpoints
(`GET-by-id` and the three state-action endpoints) is the
"`X-User-ID` equals the path's `{company_id}`" predicate at priority 530
firing `ERR_CROSS_TENANT_ACCESS` 403 after the existence-tier-priority-
300 check resolves the path id to a row. The list endpoint's special-
case cross-tenant interaction with the optional `company_id` query
parameter is the "operator may pass only its own; regulator may pass
any" pin from the §2.6 closing paragraph; an operator-passing-a-non-
self `company_id` is the explicit-403 case.

The state machine's transitions and their preconditions are the §1.2
TransportCompany state-machine entries: DRAFT-or-REVOKED-to-SUBMITTED
on the submit endpoint, SUBMITTED-to-APPROVED on the approve endpoint,
APPROVED-to-REVOKED on the revoke endpoint. The internal-collapse step
inside the submit handler walks REVOKED-to-DRAFT first when the
observed source state is REVOKED, on the §3.1's "the externally-
observable trace is the row's `qualification_status` flipping from
REVOKED before the call to SUBMITTED after, with the `submitted_at`
refreshed" rule.

The body-shape rules on the create endpoint and the state-action
endpoints are the §1.1 entity-prose: `legal_name` 1-to-200 chars,
`registration_number` matching the eight-to-thirty-two uppercase-letters-
and-digits regex (system-wide unique on the row's natural key, with a
collision raising `ERR_DUPLICATE_IDENTIFIER` 409 at the business-
constraint priority 520), `primary_contact_email` the RFC-5322
syntactic check, `address_line` 0-to-500 chars, `hazard_classes_authorized`
a non-empty no-duplicates array of UN-hazard-class codes from the
`UN_HAZARD_CLASS_CODES` taxonomy of `config`.

The new-row's `wallet_balance_cents` is initialized to zero per the
§2.4 H3's default-values paragraph; the regulator-side bookkeeping
tops the wallet up out-of-band before the operator's first
fee-paying action. The `submitted_at`, `approved_at`, and `revoked_at`
audit-timestamp fields are null on the fresh row and are written by the
respective state transitions' handlers per the §1.2 state-machine
side-effects.
"""

from __future__ import annotations

import re
from typing import Any

from flask import Blueprint, current_app, request

from ..auth import (
    assert_cross_tenant_company_id_match,
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..clock import iso_now
from ..config import (
    ADDRESS_LINE_LEN_RANGE,
    COMPANY_QUALIFICATION_STATES,
    Constants,
    GENERIC_REASON_NOTE_LEN_RANGE,
    LEGAL_NAME_LEN_RANGE,
    OPTIONAL_NOTE_LEN_RANGE,
    REGISTRATION_NUMBER_REGEX,
)
from ..envelope import (
    get_json_body,
    make_array_response,
    make_object_response,
    parse_pagination_query,
)
from ..errors import APIError
from ..store import (
    bump_version,
    check_occ,
    find_by_unique_field,
    insert,
    list_all,
    stamp_create,
    table,
    paginate,
)
from ..validation import (
    parse_comma_filter_query,
    require_array,
    require_int,
    require_present,
    require_str,
    validate_email_syntax,
    validate_hazard_class_array,
    validate_registration_number,
)


companies_bp = Blueprint("companies", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_company(row: dict[str, Any]) -> dict[str, Any]:
    """Project the on-disk TransportCompany row to the response shape.
    The full row's keys are returned verbatim — the in-memory dict is
    already in the wire-shape modulo the canonical four common-fields
    quartet. The function's pass-through nature is documented here so
    a future change to a derived-field calculation has an obvious
    place to hook.
    """
    # Defensive shallow-copy so the response-side dict-mutation doesn't
    # touch the store's dict.
    return dict(row)


# ---------------------------------------------------------------------------
# POST /v1/companies — file the initial qualification application
# ---------------------------------------------------------------------------


@companies_bp.route("/companies", methods=["POST"])
def post_companies() -> Any:
    """Operator files the company-application body. The new row is
    written in `qualification_status = "DRAFT"`. The operator's
    bootstrap identity exemption from the auth tier means the request's
    `X-User-ID` is accepted as the would-be operator id, and the
    server mints the new row's `id` regardless of the header's value.
    The operator's subsequent calls then carry the minted UUID as the
    `X-User-ID`.

    The body schema is the §1.5 row for this endpoint:
      {
        "legal_name": string 1..200,
        "registration_number": string matching ^[A-Z0-9]{8,32}$,
                                            system-wide unique,
        "primary_contact_email": string passing the RFC-5322 syntactic
                                            regex,
        "address_line": string 0..500,
        "hazard_classes_authorized": non-empty no-duplicates array of
                                            UN-hazard-class codes.
      }

    The response is the 201 row.

    Error path's `ordered_error_table` per the §1.5 entry:
      ERR_UNAUTHENTICATED 401 — caught by the auth middleware.
      ERR_ROLE_NOT_PERMITTED 403 — caught by the RBAC tier.
      ERR_VALIDATION 422 — body shape failures (regex miss on
                            registration_number, empty hazard-class
                            array, email syntax miss, length-bound
                            violations).
      ERR_DUPLICATE_IDENTIFIER 409 — the system-wide unique
                            `registration_number` collides with an
                            existing TransportCompany row.

    The convention's auth-side bootstrap exemption is realized in the
    auth middleware's `_BOOTSTRAP_ENDPOINTS` set check, which skips the
    entity-backed-id-resolve step on the CompanyOperator-on-POST-/v1/companies
    pair. The handler-side does not need to handle the bootstrap
    distinctly — it just mints the new id and the operator switches.
    """
    body = get_json_body()

    legal_name = require_str(
        body, "legal_name", length_range=LEGAL_NAME_LEN_RANGE
    )
    registration_number_raw = require_str(
        body, "registration_number", length_range=(8, 32)
    )
    assert registration_number_raw is not None
    validate_registration_number(registration_number_raw)
    primary_contact_email = require_str(
        body, "primary_contact_email", length_range=(3, 320)
    )
    assert primary_contact_email is not None
    validate_email_syntax(
        primary_contact_email, key="primary_contact_email"
    )
    address_line = require_str(
        body, "address_line", length_range=ADDRESS_LINE_LEN_RANGE, optional=True
    )
    if address_line is None:
        address_line = ""
    hazard_classes_authorized_raw = require_array(
        body, "hazard_classes_authorized", element_type=str
    )
    assert hazard_classes_authorized_raw is not None
    hazard_classes_authorized = validate_hazard_class_array(
        hazard_classes_authorized_raw, field="hazard_classes_authorized"
    )

    # System-wide uniqueness check on `registration_number`. The §1.4
    # priority-520 business-constraint-natural-key-uniqueness tier.
    existing = find_by_unique_field(
        "TransportCompany", "registration_number", registration_number_raw
    )
    if existing is not None:
        raise APIError(
            "ERR_DUPLICATE_IDENTIFIER",
            f"TransportCompany registration_number "
            f"{registration_number_raw!r} is already in use.",
            details={
                "natural_key": "registration_number",
                "value": registration_number_raw,
                "existing_id": existing.get("id"),
            },
        )

    # The new row. The four common-fields quartet is stamped by the
    # `stamp_create` helper; the business-fields are the body's echoed
    # values plus the system-set defaults from the §2.4 H3 paragraph:
    # `qualification_status = "DRAFT"`, `wallet_balance_cents = 0`,
    # the three audit-timestamp fields all null.
    row: dict[str, Any] = {
        "legal_name": legal_name,
        "registration_number": registration_number_raw,
        "primary_contact_email": primary_contact_email,
        "address_line": address_line,
        "hazard_classes_authorized": list(hazard_classes_authorized),
        "qualification_status": "DRAFT",
        "wallet_balance_cents": 0,
        "submitted_at": None,
        "approved_at": None,
        "revoked_at": None,
    }
    stamp_create(row)
    insert("TransportCompany", row)

    return make_object_response(_serialize_company(row), http_status=201)


# ---------------------------------------------------------------------------
# GET /v1/companies/<company_id> — read one
# ---------------------------------------------------------------------------


@companies_bp.route("/companies/<company_id>", methods=["GET"])
def get_company(company_id: str) -> Any:
    """Read one TransportCompany row. The auth tier has already
    validated the headers and the RBAC cell. The existence-tier check
    is the path-id-resolve via `lookup_path_resource`; the cross-tenant
    tier-priority-530 check is the operator-only "the operator's id
    must equal the path id" predicate (the regulator and the TestHarness
    are exempt per the §2.6's regulator-cross-tenant-exemption rule).

    The §1.5's ordered_error_table for this endpoint:
      ERR_UNAUTHENTICATED 401 — auth middleware.
      ERR_ROLE_NOT_PERMITTED 403 — Driver or TestHarness sees this on
                                     the RBAC tier.
      ERR_COMPANY_NOT_FOUND 404 — the path id does not resolve.
      ERR_CROSS_TENANT_ACCESS 403 — operator on a non-self id.
    """
    row = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )
    assert_cross_tenant_ownership("TransportCompany", row)
    return make_object_response(_serialize_company(row), http_status=200)


# ---------------------------------------------------------------------------
# GET /v1/companies — list
# ---------------------------------------------------------------------------


@companies_bp.route("/companies", methods=["GET"])
def list_companies() -> Any:
    """List TransportCompany rows. The standard pagination contract of
    the §2.3 H3 paragraph applies — `limit` default 10 in the [1, 100]
    inclusive range, `offset` default 0 nonnegative.

    The two filter query parameters are:
      - `qualification_status` (a comma-separated subset of the four
        enum values `DRAFT`, `SUBMITTED`, `APPROVED`, `REVOKED`). A
        value outside the enum is the body-shape `ERR_VALIDATION` 422.
      - `company_id` (a single TransportCompany id string). The
        operator-may-only-pass-its-own rule fires
        `ERR_CROSS_TENANT_ACCESS` 403 on an operator's mismatched-
        explicit-parameter; the regulator may pass any id; the absent-
        parameter case is the implicit-self filter for the operator
        (returning at most one row, the operator's own company) and the
        all-tenants no-filter case for the regulator.

    The default sort order is `created_at` ascending per the §2.3 H3
    paragraph's "default sort order is ascending by `created_at`"
    convention; this endpoint does not override the default (the §3.1
    closing paragraph does not name a deviation for the company list,
    in contrast with the permit-list's `created_at` descending and the
    inspection-list's `inspected_at` descending — the latter two are
    handled in their own blueprint modules).

    The response is the standard paginated-array envelope. The HTTP
    status is 200.
    """
    role, user_id = current_principal()
    limit, offset = parse_pagination_query()

    # The `qualification_status` filter.
    raw_qs = request.args.get("qualification_status")
    qs_filter = parse_comma_filter_query(
        raw_qs,
        allowed=COMPANY_QUALIFICATION_STATES,
        field_name="qualification_status",
    )

    # The `company_id` filter. The operator's cross-tenant-explicit-
    # mismatch case is `ERR_CROSS_TENANT_ACCESS` 403 per the §2.6
    # closing paragraph. The regulator's same-parameter is the standard
    # narrowing filter. The TestHarness role is not in the endpoint's
    # allow-set so it never reaches this handler.
    raw_company_id = request.args.get("company_id")
    target_company_id_filter: str | None = None
    if raw_company_id is not None:
        target_company_id_filter = raw_company_id.strip() or None
    if role == "CompanyOperator":
        # Operator may not see other tenants. The convention is the
        # absent-parameter is the implicit-self default; a present-
        # parameter must equal the operator's id.
        if (
            target_company_id_filter is not None
            and target_company_id_filter != user_id
        ):
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Operator id {user_id!r} cannot list companies for "
                f"another tenant {target_company_id_filter!r}.",
                details={
                    "operator_id": user_id,
                    "requested_company_id": target_company_id_filter,
                },
            )
        # The effective filter for the operator is always "the
        # operator's own id".
        effective_company_filter = user_id
    else:
        # Regulator (and any other cross-tenant-exempt role). The
        # filter is whatever the body says or absent (no filter at all).
        effective_company_filter = target_company_id_filter

    # Walk the table.
    all_rows = list_all("TransportCompany")
    filtered: list[dict[str, Any]] = []
    for r in all_rows:
        if effective_company_filter is not None and r.get("id") != effective_company_filter:
            continue
        if qs_filter is not None and r.get("qualification_status") not in qs_filter:
            continue
        filtered.append(r)

    # Sort ascending by `created_at` per the §2.3 default.
    filtered.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))

    page, total, has_more = paginate(filtered, limit, offset)
    payload = [_serialize_company(r) for r in page]
    return make_array_response(
        payload, limit=limit, offset=offset, total_count=total, has_more=has_more
    )


# ---------------------------------------------------------------------------
# POST /v1/companies/<company_id>/submit — operator's submit-or-resubmit
# ---------------------------------------------------------------------------


@companies_bp.route("/companies/<company_id>/submit", methods=["POST"])
def post_company_submit(company_id: str) -> Any:
    """The operator's `DRAFT → SUBMITTED` transition (and the cycle's
    internal `REVOKED → DRAFT → SUBMITTED` walk for the reapply case).

    The body carries the optional OCC `version` integer field. The
    `submitted_at` is refreshed to the current simulated-clock value,
    the `version` is bumped, and the `updated_at` is refreshed.

    The preconditions per §1.2 TransportCompany.DRAFT-to-SUBMITTED
    state-machine entry:
      - The acting operator's `X-User-ID` equals the path `{company_id}`
        (the cross-tenant tier-priority-530 check).
      - The source state is in the set `{DRAFT, REVOKED}` (the §3.1's
        REVOKED-to-DRAFT-to-SUBMITTED cycle internal-collapse). A
        SUBMITTED or APPROVED source state is the standard generic
        state error.
      - The body-required-fields-non-empty check on the company row's
        `hazard_classes_authorized` (non-empty), `primary_contact_email`
        (non-empty), `legal_name` (non-empty). These are the §1.2
        preconditions list's per-field guards.
      - The OCC version match if the body's `version` field is present
        (§2.10 H3).

    The `ordered_error_table` from §1.5 is the priority-ordered:
      ERR_UNAUTHENTICATED, ERR_ROLE_NOT_PERMITTED (the role-not-
      `CompanyOperator` case from the RBAC tier — though the auth
      middleware's matrix check already covers this), ERR_COMPANY_NOT_FOUND
      (the path-id miss), ERR_CROSS_TENANT_ACCESS (the wrong-tenant
      operator case), ERR_INVALID_STATE_TRANSITION (a SUBMITTED-or-
      APPROVED source state — the operator's reapply path is only
      from REVOKED back through the internal collapse, and an
      APPROVED-source's "submit" call has no canonical semantic so it
      is the generic state error), ERR_VALIDATION (the per-field
      non-empty check on the row's three required attributes failing),
      ERR_VERSION_CONFLICT (the OCC mismatch).
    """
    row = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )

    # Cross-tenant ownership check at priority 530.
    assert_cross_tenant_ownership("TransportCompany", row)

    body = get_json_body()

    # OCC check at priority 560. The non-`version`-body opts out per
    # the §2.10 H3 contract.
    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "Optimistic-concurrency version mismatch on the TransportCompany "
            "row.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )

    pre_status = row.get("qualification_status")
    # The two-source-state allow-set: DRAFT (the first-time submit) or
    # REVOKED (the reapply-after-revocation internal collapse cycle's
    # entry). A SUBMITTED-or-APPROVED source is the generic
    # ERR_INVALID_STATE_TRANSITION 409. The internal-collapse on
    # REVOKED is the no-side-effect bookkeeping step from REVOKED back
    # to DRAFT before the DRAFT-to-SUBMITTED step fires within the
    # same handler invocation; the externally-observable transition
    # is REVOKED-to-SUBMITTED in one call. The `submitted_at` is
    # refreshed and the `version` is bumped on the canonical exit
    # state SUBMITTED.
    if pre_status not in ("DRAFT", "REVOKED"):
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot submit a TransportCompany in {pre_status!r}; allowed "
            f"source states are 'DRAFT' or 'REVOKED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["DRAFT", "REVOKED"],
                "endpoint": "POST /v1/companies/<company_id>/submit",
            },
        )

    # The body-pre-submit-required-fields-non-empty check at the
    # validation tier's `ERR_VALIDATION` 422 outcome. The §1.2
    # paragraph's preconditions list names the three non-empty fields
    # the row must carry at the moment of the submit; on a freshly-
    # created company these are guaranteed by the create-endpoint's
    # body-shape validation (every field is required and is in its
    # length-and-pattern-validated form), but if the row's state-
    # transition graph allowed an in-DRAFT edit (which this scaffold
    # does not, since there is no company-update endpoint), the
    # pre-submit re-check would matter. The defensive check is here
    # for completeness regardless.
    hazard_classes = row.get("hazard_classes_authorized") or []
    if not isinstance(hazard_classes, list) or len(hazard_classes) == 0:
        raise APIError(
            "ERR_VALIDATION",
            "TransportCompany 'hazard_classes_authorized' is empty; the "
            "submit-time precondition requires at least one entry.",
            details={"field": "hazard_classes_authorized"},
        )
    if not row.get("primary_contact_email"):
        raise APIError(
            "ERR_VALIDATION",
            "TransportCompany 'primary_contact_email' is empty.",
            details={"field": "primary_contact_email"},
        )
    if not row.get("legal_name"):
        raise APIError(
            "ERR_VALIDATION",
            "TransportCompany 'legal_name' is empty.",
            details={"field": "legal_name"},
        )

    # The state transition's side-effects per the §1.2 entry.
    row["qualification_status"] = "SUBMITTED"
    row["submitted_at"] = iso_now()
    bump_version(row)

    return make_object_response(_serialize_company(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/companies/<company_id>/approve — regulator's approve
# ---------------------------------------------------------------------------


@companies_bp.route("/companies/<company_id>/approve", methods=["POST"])
def post_company_approve(company_id: str) -> Any:
    """The regulator's `SUBMITTED → APPROVED` transition. The body carries
    an optional OCC `version` and an optional 0-to-500-character
    `approval_note` audit string. The `approved_at` is set to the
    current simulated-clock value. The `version` is bumped. The audit-
    note is logged out-of-band (the scaffold does not surface the
    audit log as an API-readable resource); the on-disk row carries
    no `approval_note` field, so the body's note is discarded on the
    on-disk side but the response message can echo it.

    The pre-state-must-be-SUBMITTED rule is the standard same-row
    state guard at the state tier with the generic
    `ERR_INVALID_STATE_TRANSITION` 409 error id.

    The cross-tenant exemption: the regulator's RBAC cell is
    unconditional-allow (the regulator is the cross-tenant-exempt
    role per the §2.6 paragraph), so no cross-tenant check fires
    on this endpoint.
    """
    row = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )
    body = get_json_body()
    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on TransportCompany.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )
    # The optional approval_note body field's length bound.
    require_str(
        body, "approval_note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )

    pre_status = row.get("qualification_status")
    if pre_status != "SUBMITTED":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot approve a TransportCompany in {pre_status!r}; the "
            "required source state is 'SUBMITTED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["SUBMITTED"],
                "endpoint": "POST /v1/companies/<company_id>/approve",
            },
        )

    row["qualification_status"] = "APPROVED"
    row["approved_at"] = iso_now()
    bump_version(row)

    return make_object_response(_serialize_company(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/companies/<company_id>/revoke — regulator's revoke
# ---------------------------------------------------------------------------


@companies_bp.route("/companies/<company_id>/revoke", methods=["POST"])
def post_company_revoke(company_id: str) -> Any:
    """The regulator's `APPROVED → REVOKED` transition. The body carries
    the required `reason_note` 1-to-500-character free-text field and
    the optional OCC `version`. The `revoked_at` is set to the current
    simulated-clock value, the `version` is bumped, and the
    `updated_at` is refreshed.

    The cross-aggregate-deferred-cascade onto every ACTIVE permit
    whose `company_id` is the just-revoked company's id is documented
    as deferred per the §3.1 paragraph — the revoke action does not
    walk the Permit table in its own transaction; the next
    verify-compliance call on each affected permit (or the next
    sweep-run tick's per-permit step-2 internal verify-compliance)
    observes the live company-leg is now false on the snapshot-vs-live
    disagreement decision-step and fires the `ACTIVE → SUSPENDED`
    transition on the permit. This is the upstream-cause-and-the-
    downstream-cascade pattern the §2.5 H3 paragraph's "deferred-
    flush via the sweep" rule names.

    The pre-state-must-be-APPROVED rule is the standard same-row state
    guard. The reason_note's non-empty 1-to-500-char rule is the body-
    shape `ERR_VALIDATION` 422 on a missing or oversize body field.
    """
    row = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )
    body = get_json_body()
    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on TransportCompany.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )

    # Required reason_note.
    reason_note = require_str(
        body, "reason_note", length_range=GENERIC_REASON_NOTE_LEN_RANGE
    )

    pre_status = row.get("qualification_status")
    if pre_status != "APPROVED":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot revoke a TransportCompany in {pre_status!r}; the "
            "required source state is 'APPROVED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["APPROVED"],
                "endpoint": "POST /v1/companies/<company_id>/revoke",
            },
        )

    row["qualification_status"] = "REVOKED"
    row["revoked_at"] = iso_now()
    # The audit-only reason_note. The scaffold does not surface the
    # audit-log entity, so the note is logged-and-discarded on the on-
    # disk row's read-back. We attach it to the response's audit-side
    # `reason_note` field for the test layer's inspection.
    row.setdefault("revoke_reason_note", reason_note)
    bump_version(row)

    # The deferred-cascade onto the ACTIVE permits is NOT fired in
    # this transaction — the next verify-compliance-or-sweep tick will
    # observe the now-non-APPROVED company-leg and flip the affected
    # permits to SUSPENDED via the standard verify-compliance state-
    # machine logic. The §3.1 paragraph's "the cascade is deferred"
    # rule is what the test harness exercises by chaining
    # company-revoke, clock-advance, sweep-run, and the post-sweep
    # observation of the affected permits' new status.

    return make_object_response(_serialize_company(row), http_status=200)
