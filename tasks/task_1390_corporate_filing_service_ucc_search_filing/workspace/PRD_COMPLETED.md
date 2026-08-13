# Corporate Filing & UCC Search API — Product Requirements Document

## 1. Introduction

A corporate filing service in the style of CSC or CT Corporation lives and dies by two disciplines: getting debtor names and collateral descriptions exactly right before a UCC-1 financing statement ever reaches a filing office, and never losing track of the five-year effectiveness window once it does. This document specifies the API for such a service — a platform that intakes filing requests on behalf of client organizations, determines whether each filing belongs at the state or the county office, prepares and submits UCC-1 statements together with UCC-3 amendments, continuations, and terminations, and then watches the public record to confirm that accepted filings actually appear in the official index.

The operating model is deliberately unforgiving. Preparation and approval are segregated so that no single operator can both ready a filing and green-light it. Every attempt bound for a filing office is validated against jurisdiction-specific debtor-name rules, collateral sufficiency standards, daily expedited capacity, and the client's fee authorization before it leaves the building. A rejection from the filing office opens a correction loop bounded by a thirty-day refiling window; an acceptance sets or extends a sixty-month effectiveness clock whose expiry cascades cancellations through any continuation work still in flight. Search-to-reflect verification closes the loop by confirming that an accepted filing is visible to the world, and portfolio perfection reports give each client an auditable snapshot of how much of its deal exposure is genuinely perfected.

Six kinds of actors use the platform — the service operator's own platform staff, client-side account administrators, filing specialists and filing reviewers on the service-company side, filing-office clerks, and search-vendor analysts. All time-dependent behavior is driven by a controllable logical clock rather than wall-clock time, so lapse, revival, and reporting semantics remain deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role name the platform does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The platform recognizes exactly six roles:

- `PlatformAdmin` — service operator staff: seeds jurisdiction profiles, manages client accounts, and controls the logical clock.
- `ClientManager` — a client-side administrator; manages the client account's own debtors, secured parties, and perfection reports.
- `FilingSpecialist` — a service-company preparer: intake, preparation, attempts, submissions, withdrawals, and search orders.
- `FilingReviewer` — a service-company reviewer: approves prepared filings and may also submit intake; must never approve a request whose intake they submitted themselves.
- `FilingOfficer` — a state or county filing-office clerk: records acceptances and rejections.
- `SearchAnalyst` — a search-vendor analyst: records certified search results.

Performing an operation outside one's role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

How `X-User-ID` is interpreted depends on the role. When `X-User-Role` is `ClientManager`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks on any resource that references a `ClientAccount` compare the resource's client foreign-key field to `X-User-ID`. Concretely, a `ClientManager` calling any endpoint beneath a client path must present an `X-User-ID` equal to the client identifier in that path, or the call fails with `ERR_CLIENT_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `FilingSpecialist`, `FilingReviewer`, `FilingOfficer`, or `SearchAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `intake_submitted_by_user_id` on a filing request, where the submit-intake transition writes it — but it never compares that value to any entity's `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset` fails structural validation with `ERR_INVALID_REQUEST`; integer values outside the bounds are not rejected but clamped — `limit` into [1, 100] and `offset` up to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties (common under the static logical clock) broken by creation order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of resources matching the supplied filters before pagination and `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

Beyond pagination, several list endpoints accept equality filters as query parameters. The jurisdiction list filters by `state_code`. The filing-request list filters by `client_id`, `debtor_id`, `secured_party_id`, `target_filing_id`, `supporting_search_id`, `status`, or `kind`. The filing list filters by `debtor_id`, `secured_party_id`, `root_filing_id`, `supersedes_attempt_id`, `effectiveness_status`, `reflection_status`, or `jurisdiction_code`, and thereby serves every reverse lookup from those foreign keys. The lien-search list filters by `client_id`, `debtor_id`, `subject_filing_id`, `purpose`, or `status`.

### 2.4. The Logical Clock and Time-Driven Behavior

All temporal reasoning in the system — submission and rejection timestamps, lapse evaluation, report horizons — reads a single logical clock, never the host's wall clock. At startup the clock reads exactly `2026-08-01T00:00:00Z`; until an administrator moves it, that default is what every system-assigned timestamp uses, and the clock never falls back to wall-clock time. A `PlatformAdmin` sets the logical clock through an administrative capability that takes a `to_iso8601` instant; the clock may be set to any instant, forward or backward — no monotonicity constraint is enforced — and the response reports the clock's new reading as `current_utc`.

Moving the clock has a mandatory side effect: the lapse sweep runs at the new instant, lapsing every filing whose effectiveness has expired and triggering the cancellation cascade described in §3.6. The same sweep also runs automatically at the start of every perfection-report generation, and reading a single filing lazily re-applies the lapse rule to that one filing before the response is assembled, so an expired filing is never reported as still effective. This lazy single-filing re-check applies to the single-filing read and the name-check read only; list endpoints and the event-trail listing return stored state without re-checking.

### 2.5. Common Resource Properties

Primary resources — client accounts, jurisdiction profiles, debtors, secured parties, filing requests, UCC filings, and lien searches — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with second precision (for example `2026-08-01T00:00:00Z`) recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with second precision recording the last modification; refreshed on every mutation.
- `version` (integer): a system-managed integer that starts at 1 on a newly created resource and increments by one on every mutation of the resource, including system-driven mutations such as cascades, counter adjustments, and lapse transitions. This is the value optimistic concurrency checks compare against.

Three resources are deliberately lighter. Search result hits, perfection reports, and filing events carry only `id` and `created_at`; both `updated_at` and `version` are absent on them, because hits and events are immutable records and each perfection report is a point-in-time snapshot that is never mutated after generation.

Mutations frequently flow across the hierarchy — accepting a termination cancels open requests, a lapse withdraws draft attempts, opening a UCC-3 request adjusts counters on the root filing. Every such cascade is a real mutation on each resource it touches: affected resources that carry `updated_at` and `version` have the former refreshed and the latter incremented, so downstream readers and concurrency checks always observe the ripple.

### 2.6. Path Hierarchy and Reference Resolution

When an endpoint path contains several resource identifiers, the server validates existence strictly left to right and returns the 404 error corresponding to the first identifier that does not resolve: `ERR_CLIENT_NOT_FOUND` for a missing client, then — as applicable deeper in the path — `ERR_REQUEST_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_SEARCH_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DEBTOR_NOT_FOUND`, `ERR_SECURED_PARTY_NOT_FOUND`, or `ERR_JURISDICTION_NOT_FOUND`. A request for a debtor under a non-existent client therefore fails with `ERR_CLIENT_NOT_FOUND` before the debtor identifier is even examined.

References supplied inside request bodies are resolved after path validation. A `jurisdiction_code` must resolve to a registered jurisdiction profile (otherwise `ERR_JURISDICTION_NOT_FOUND`). A `debtor_id` or `secured_party_id` must exist under the declared client (otherwise `ERR_DEBTOR_NOT_FOUND` or `ERR_SECURED_PARTY_NOT_FOUND` respectively). A `target_filing_id` or `subject_filing_id` must reference an existing filing (otherwise `ERR_FILING_NOT_FOUND`), and a `supporting_search_id` must reference an existing search (otherwise `ERR_SEARCH_NOT_FOUND`).

### 2.7. Filing Fees, Monetary Precision, and the Client Fee Ledger

All money in the system is integer cents: fee schedules, surcharges, per-kind deltas, client authorizations, quoted and charged fees, and exposure amounts are never fractional. The single multiplication in the fee formula — the expedited uplift — is applied once to the integer subtotal, and the product is rounded half-up to whole cents in one final rounding step; rounding any component before summation is forbidden. Datetimes that participate in fee, lapse, and window logic are ISO 8601 UTC values with second precision; every datetime supplied in a request body is converted to UTC (a value without an offset is read as UTC) and truncated to whole seconds before it is stored or compared, and every datetime the server emits on a resource is rendered in that same second-precision form.

Each client account carries a two-column fee ledger that starts at zero when the account is created. `fees_charged_total_cents` accumulates the `charged_fee_cents` debited across all attempt submissions for the client; `fees_refunded_total_cents` accumulates the `charged_fee_cents` credited back across all attempt rejections. Submission debits the ledger and rejection refunds it; nothing else moves these totals, so the pair always reconciles against the client's filing history.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, and the guard field is non-optional on both. Updating a filing request's preparation fields requires `expected_request_version`, carrying the request's `version` as the client last observed it; if the request's version has advanced since that read, the update is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting changes the client never saw. Creating a filing request whose `kind` is `AMENDMENT`, `CONTINUATION`, or `TERMINATION` requires `expected_target_filing_version`, carrying the target root filing's current `version` as last observed; a mismatch with the root's actual `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Because opening a UCC-3 request itself bumps the target's version (§3.2), a client must re-read the root before opening another request against it. Endpoints not named here take no version field at all.

### 2.9. Validation Order of Precedence

Incoming requests are checked in a fixed order, and the first failing check determines the error returned. The order is:

1. **User context.** `X-User-ID` and `X-User-Role` are present and the role name is recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Structural body validation.** The body must be valid JSON whose top level is an object — a malformed or non-object body yields `ERR_INVALID_REQUEST`, while an absent body is read as an empty object. Required fields are present, types are correct, and enum members are valid, including the conditionally required ones: a request whose `kind` is not `NEW_UCC1` must carry `target_filing_id` (its absence yields `ERR_TARGET_FILING_REQUIRED`) and `expected_target_filing_version`; an amendment attempt must carry `amendment_scope`; a collateral-scope amendment must carry both `collateral_change_op` and `collateral_text`; an initial-filing attempt must carry `collateral_text`. Other structural violations surface as `ERR_INVALID_REQUEST` (400).
3. **Role authorization.** The role is permitted for this endpoint (`ERR_UNAUTHORIZED_ROLE`, 403).
4. **Client ownership.** On client-scoped paths a `ClientManager` may only act on its own account (`ERR_CLIENT_OWNERSHIP_MISMATCH`, 403).
5. **Path existence.** Path identifiers exist, validated left to right (the 404 catalog of §2.6).
6. **Body-reference existence.** Body references exist and belong to the declared client (the per-reference 404s of §2.6).
7. **State preconditions.** The client is `ACTIVE` where intake requires it (`ERR_CLIENT_SUSPENDED`); the request is in a valid from-state for the requested transition (`ERR_REQUEST_INVALID_STATE`, or `ERR_REQUEST_IN_PROCESS` for cancellation during processing); the request is `READY` where attempt creation or submission requires it (`ERR_REQUEST_NOT_READY`); the attempt is in a valid from-state (`ERR_FILING_INVALID_STATE`); the search is `ORDERED` where results recording requires it (`ERR_SEARCH_NOT_ORDERED`); the target or subject root filing is `ACTIVE` where required (`ERR_TARGET_FILING_NOT_ACTIVE`); and the two OCC version checks hold (`ERR_STALE_VERSION`, 412). State failures carry 409 except the OCC failures, which carry 412.
8. **Compliance and safety.** Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), debtor-name accuracy (`ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`, `ERR_DEBTOR_DL_NAME_MISSING`), collateral sufficiency (`ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED`), county-office consistency (`ERR_COUNTY_REQUIRED`, `ERR_COUNTY_NOT_IN_JURISDICTION`), perfection-slot overlap (`ERR_OVERLAPPING_ACTIVE_FILING`), and collateral-delete presence (`ERR_COLLATERAL_NOT_PRESENT`).
9. **Temporal rules, in this order:** `filed_at` bracketing (`ERR_INVALID_FILED_AT`), the continuation window (`ERR_CONTINUATION_OUTSIDE_WINDOW`), the thirty-day refile window (`ERR_REFILE_WINDOW_EXPIRED`), supporting-search freshness (`ERR_SEARCH_STALE`), and verification through-date coverage (`ERR_SEARCH_THROUGH_DATE_TOO_EARLY`).
10. **Constraint satisfaction.** At most one in-flight attempt per request (`ERR_ATTEMPT_IN_FLIGHT`); at most one open amendment or continuation request per root filing (`ERR_UCC3_IN_FLIGHT`); expedited daily capacity per jurisdiction (`ERR_EXPEDITED_CAPACITY_REACHED`); and `state_code` uniqueness across jurisdiction profiles (`ERR_DUPLICATE_STATE_CODE`).
11. **The fiscal gate.** The charged fee may not exceed the client's authorization (`ERR_FEE_AUTHORIZATION_EXCEEDED`, 402).

### 2.10. The Filing Audit Trail

Every UCC filing accumulates an immutable audit trail of filing events. Each event carries an `event_type` drawn from exactly this vocabulary — `CREATED`, `SUBMITTED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, `CONTINUED`, `AMENDED`, `TERMINATED`, `LAPSED`, `REVIVED`, `REFLECTED`, and `DISCREPANCY_FLAGGED` — plus a structured `event_detail` payload appropriate to the event (for example the `rejection_reason_code` on a rejection, the `filed_at` on an acceptance, or the `prior_expiration_at` on a continuation) and an `occurred_at` timestamp read from the logical clock. Each event references its filing through `ucc_filing_id`, and the trail is listed in chronological order.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Clients, Jurisdictions, Debtors, and Secured Parties

Work begins with the `PlatformAdmin`, who creates a client account by supplying the organization `name`. A new account's `status` starts at `ACTIVE` and its fee ledger at zero. Suspension moves an account from `ACTIVE` to `SUSPENDED` and requires the account to currently be `ACTIVE`; reinstatement moves it back from `SUSPENDED` to `ACTIVE` and requires it to currently be `SUSPENDED`; either transition attempted from the wrong state fails with `ERR_REQUEST_INVALID_STATE` (409). Suspension is a narrow gate: it blocks only the intake submission of filing requests (§3.2), and it never touches in-flight requests or filings, which run to completion undisturbed.

The `PlatformAdmin` also registers one jurisdiction profile per state, providing `state_code` (conventionally a two-letter code; uniqueness across profiles is the only constraint enforced on it — a duplicate is rejected with `ERR_DUPLICATE_STATE_CODE`), `base_fee_cents`, `per_additional_debtor_fee_cents` (the surcharge for each debtor beyond the first), `county_surcharge_cents` (the extra fee when the filing office resolves to county), `county_filing_collateral_classes` (the subset of the collateral classes `GENERAL`, `FIXTURE`, `TIMBER_TO_BE_CUT`, and `AS_EXTRACTED` that must be filed at county level in that state), `county_names` (the valid county names for county filings — an empty array means county filing is unavailable in that state), `individual_name_rule` (either `DL_SAFE_HARBOR` or `LEGAL_NAME_ONLY`), and `expedited_daily_capacity` (the maximum number of `EXPEDITED` attempt submissions accepted per UTC calendar day for the jurisdiction). Later, the administrator may update any of the fee or rule fields; each update increments the profile's `version` by one. Because quoted and charged fees read the profile at different instants (§3.3 and §3.4), a mid-flight profile update is precisely what makes the two figures diverge.

A `ClientManager` registers the account's debtors, supplying `debtor_type` (`ORGANIZATION` or `INDIVIDUAL`), `legal_name` (for an organization, the name on its public organic record), and — required exactly when `debtor_type` is `ORGANIZATION`, optional otherwise — `jurisdiction_of_formation`. The optional `drivers_license_name` is consulted for `INDIVIDUAL` debtors in `DL_SAFE_HARBOR` jurisdictions. Name-of-record fields (`legal_name`, `drivers_license_name`, `jurisdiction_of_formation`) can be corrected later; each correction increments the debtor's `version` by one, and such a correction is the normal precursor to a `DEBTOR_NAME` amendment. Because the correction endpoint is not beneath a client path, ownership is checked against the resource: the acting `ClientManager`'s `X-User-ID` must equal the debtor's `client_id`, failing with `ERR_CLIENT_OWNERSHIP_MISMATCH` otherwise, and an explicit null supplied for `drivers_license_name` or `jurisdiction_of_formation` clears that field.

Secured parties are registered the same way, with a `name` and an optional client-side `reference_code`.

### 3.2. Intake of a Filing Request and the County-versus-State Determination

A `FilingSpecialist` intakes a filing request by providing `client_id`, `kind` (`NEW_UCC1`, `AMENDMENT`, `CONTINUATION`, or `TERMINATION`), `debtor_id`, `secured_party_id`, `jurisdiction_code`, `collateral_class`, and `fee_authorization_cents` — the client's maximum authorized fee for any single attempt submission. Optional intake fields are `county_name`, `service_level` (defaulting to `STANDARD`; `EXPEDITED` multiplies the fee and consumes daily capacity), `additional_debtor_count` (the number of debtors beyond the primary, zero or more, defaulting to 0), and `supporting_search_id` (an optional pre-filing diligence search). When `kind` is not `NEW_UCC1`, two more fields are mandatory: `target_filing_id`, referencing the `INITIAL` filing of record the request operates on — a `target_filing_id` that resolves to a filing whose `filing_kind` is not `INITIAL` is rejected with `ERR_INVALID_REQUEST` — and `expected_target_filing_version`, the OCC guard of §2.8 — if the target's `version` has moved on since the client last read it, creation is rejected with `ERR_STALE_VERSION` (HTTP 412). Conversely, a `NEW_UCC1` intake ignores any supplied `target_filing_id` or `expected_target_filing_version` and stores `target_filing_id` as null. The named debtor and secured party must belong to the declared client.

A new request lands in `DRAFT_INTAKE`. For the UCC-3 kinds, creation also adjusts the target root filing: its `open_ucc3_request_count` increases by one and its `version` increments by one. That counter is meaningful on `INITIAL` filings and counts the filing requests targeting this filing that sit in any of the open states `DRAFT_INTAKE`, `IN_REVIEW`, `READY`, `IN_PROCESS`, or `CORRECTION_REQUIRED`. One restriction applies at creation: a root filing may have at most one open `AMENDMENT` or `CONTINUATION` request — a second open one is rejected with `ERR_UCC3_IN_FLIGHT` — while `TERMINATION` requests are exempt from that restriction.

Submitting intake — a capability shared by `FilingSpecialist` and `FilingReviewer` — moves the request from `DRAFT_INTAKE` to `IN_REVIEW`. The client's `status` must be `ACTIVE`; submitting intake under a `SUSPENDED` client fails with `ERR_CLIENT_SUSPENDED`. For the UCC-3 kinds the target filing must be `ACTIVE`, failing with `ERR_TARGET_FILING_NOT_ACTIVE` otherwise. At this moment the system determines `filing_office`: it becomes `COUNTY` exactly when the request's `collateral_class` is a member of the resolved profile's `county_filing_collateral_classes`, and `STATE` otherwise. A `COUNTY` resolution demands that `county_name` be present (otherwise `ERR_COUNTY_REQUIRED`) and that it be a member of the profile's `county_names` (otherwise `ERR_COUNTY_NOT_IN_JURISDICTION`). The submitting operator's `X-User-ID` is recorded on the request as `intake_submitted_by_user_id`, anchoring the segregation-of-duties check at approval.

While a request sits in `DRAFT_INTAKE`, `IN_REVIEW`, or `CORRECTION_REQUIRED`, a `FilingSpecialist` may correct its preparation fields — `collateral_class`, `county_name`, `service_level`, `additional_debtor_count`, `fee_authorization_cents`, or `supporting_search_id` — always carrying `expected_request_version` per §2.8; from any other state the correction is rejected with `ERR_REQUEST_INVALID_STATE`. A successful correction increments the request's `version` by one, and when `collateral_class` or `county_name` changed while the request is `IN_REVIEW`, the `filing_office` is recomputed under the same county-membership rule used at intake.

### 3.3. Review, Approval, and Fee Quotation

Approval is performed by a `FilingReviewer` and moves the request to `READY` — from `IN_REVIEW` on the first pass, or from `CORRECTION_REQUIRED` inside the correction loop. Segregation of duties is enforced at this boundary: the approver's `X-User-ID` must differ from the request's `intake_submitted_by_user_id`, or approval fails with `ERR_SEGREGATION_OF_DUTIES`. When the request carries a `supporting_search_id`, that search must be a completed pre-filing diligence search — its status must be `COMPLETED` — and its `through_date` must be no more than ninety days before the current instant; a search whose certified-through date is exactly ninety days old is still fresh, and an older one fails approval with `ERR_SEARCH_STALE`.

Approval is also the quoting instant. The system evaluates the filing-fee formula of §3.4 against the jurisdiction profile's values in effect at that instant and snapshots the result onto `quoted_fee_cents`. Re-approval after a correction recomputes and re-snapshots the quote under the same rule. The quoted and charged fees are the same formula evaluated at two different instants — approval and submission — and differ only in which profile values they read.

### 3.4. Preparing and Submitting a Filing Attempt

Once a request is `READY`, a `FilingSpecialist` creates a filing attempt under it — any other request status yields `ERR_REQUEST_NOT_READY`. The specialist supplies `debtor_name_on_filing`, the debtor name exactly as it will be typed on the form; `collateral_text`, required for initial filings and for collateral-scope amendments and optional otherwise; `amendment_scope` (`DEBTOR_NAME`, `COLLATERAL`, or `SECURED_PARTY`), required exactly when the request kind is `AMENDMENT`; `collateral_change_op` — one of the three values "ADD", "DELETE", or "RESTATE" — required exactly when `amendment_scope` is `COLLATERAL`; and `secured_amount_cents`, the deal exposure carried by this filing, defaulting to 0 and aggregated by perfection reports over initial filings only. Fields not applicable to the request kind are stored as null on the attempt: `amendment_scope` is null unless the kind is `AMENDMENT`, and `collateral_change_op` is null unless the scope is `COLLATERAL`. A request may have at most one non-terminal attempt — one in `DRAFT` or `SUBMITTED` — and creating a second while one is in flight is rejected with `ERR_ATTEMPT_IN_FLIGHT`.

The new attempt starts with `effectiveness_status` of `DRAFT` and `reflection_status` of `UNVERIFIED`, and a `CREATED` event is appended to its trail. The system copies `filing_kind` from the request's kind (with `NEW_UCC1` mapping to `INITIAL`), along with `debtor_id`, `secured_party_id`, `jurisdiction_code`, `filing_office`, and `county_name` (null for `STATE` filings), and links the attempt to its request through `filing_request_id`. On an `INITIAL` attempt `root_filing_id` is null; on a UCC-3 attempt it equals the request's `target_filing_id`. On a refile — an attempt created after a rejection — `supersedes_attempt_id` points at the latest `REJECTED` attempt under the same request, and creation is permitted only while the current instant is no later than thirty days after that attempt's `rejected_at`; the boundary is inclusive, so creation exactly thirty days after the rejection is allowed and anything later fails with `ERR_REFILE_WINDOW_EXPIRED`. The first attempt under a request carries a null `supersedes_attempt_id`.

Submission sends a `DRAFT` attempt to the filing office; the attempt must be in `DRAFT` (otherwise `ERR_FILING_INVALID_STATE`) and its parent request must be `READY` (otherwise `ERR_REQUEST_NOT_READY`). Submission runs the full validation chain in the precedence of §2.9, of which the business checks are:

- **Debtor-name accuracy.** The name-match rule normalizes a name by uppercasing it, removing every character that is not an uppercase letter, a digit, or a space, collapsing each run of consecutive spaces into a single space, and trimming the ends. The name of record is the debtor's `legal_name` for an `ORGANIZATION` debtor; for an `INDIVIDUAL` debtor it is the `drivers_license_name` in a jurisdiction whose `individual_name_rule` is `DL_SAFE_HARBOR` — and if the debtor has no `drivers_license_name` on record, submission fails with `ERR_DEBTOR_DL_NAME_MISSING` — or the `legal_name` in a `LEGAL_NAME_ONLY` jurisdiction. The normalized `debtor_name_on_filing` must equal the normalized name of record exactly; a mismatch is rejected with `ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`. A non-mutating name-check read evaluates the same rule on demand for any attempt and returns `match`, `normalized_submitted`, `normalized_of_record`, and `name_rule_applied`; unlike submission, the name-check never fails on a missing name of record — when no name of record exists it simply reports `match` as false with `normalized_of_record` null.
- **Collateral sufficiency.** For an `INITIAL` attempt and for a `COLLATERAL`-scope amendment, `collateral_text` must be at least 20 characters long and must not normalize to one of the supergeneric terms `ALL ASSETS`, `ALL PERSONAL PROPERTY`, or `ALL ASSETS OF DEBTOR`; failure is rejected with `ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED`.
- **Expedited capacity.** When the request's `service_level` is `EXPEDITED`, the number of expedited attempt submissions already made for the jurisdiction on the current UTC calendar day must not yet have reached the profile's `expedited_daily_capacity`; a jurisdiction at capacity rejects further expedited submissions that day with `ERR_EXPEDITED_CAPACITY_REACHED`.
- **The fiscal gate.** The fee computed from the profile's current values must not exceed the request's `fee_authorization_cents`; an excess is rejected with `ERR_FEE_AUTHORIZATION_EXCEEDED` (HTTP 402).

The fee itself is built from the profile's values in effect at the submission instant. The subtotal is the profile's `base_fee_cents`, plus the profile's `per_additional_debtor_fee_cents` multiplied by the request's `additional_debtor_count`, plus the profile's `county_surcharge_cents` when the request's `filing_office` is `COUNTY` (nothing when it is `STATE`), plus a flat per-kind delta — zero cents for `NEW_UCC1`, 1,000 cents for `AMENDMENT`, 1,500 cents for `CONTINUATION`, and 500 cents for `TERMINATION`. When `service_level` is `EXPEDITED`, that integer subtotal is multiplied by one and a half and the product is rounded half-up to whole cents in a single final step, with per-component rounding before summation forbidden; `STANDARD` service is charged the unmultiplied subtotal.

On success the fee is locked onto the attempt as `charged_fee_cents`, the client's `fees_charged_total_cents` increases by `charged_fee_cents`, `submitted_at` is set to the current instant, the attempt moves `DRAFT` → `SUBMITTED`, the parent request moves `READY` → `IN_PROCESS`, and a `SUBMITTED` event is appended.

### 3.5. Acceptance, Rejection, and the Correction Loop

Acceptance is recorded by a `FilingOfficer`, who supplies the office-assigned `filing_number` and the effective `filed_at` datetime. The attempt must be `SUBMITTED` (otherwise `ERR_FILING_INVALID_STATE`), and `filed_at` must be no earlier than the attempt's `submitted_at` and no later than the current instant — both boundaries inclusive — or acceptance fails with `ERR_INVALID_FILED_AT`. Three kind-specific guards then apply. For an `INITIAL` filing, no other `INITIAL` filing for the same `debtor_id`, `jurisdiction_code`, and `filing_office` may currently be `ACTIVE`; effectiveness runs from `filed_at` up to but not including `expiration_at`, so `LAPSED` or `TERMINATED` filings free the slot, while a live overlap is rejected with `ERR_OVERLAPPING_ACTIVE_FILING`. For an `AMENDMENT` or `TERMINATION`, the root filing must be `ACTIVE` (otherwise `ERR_TARGET_FILING_NOT_ACTIVE`). For a `CONTINUATION`, the supplied `filed_at` must fall inside the continuation window: the window opens exactly six calendar months before the root's currently stored `expiration_at` and closes at that expiration, with the lower bound inclusive and the upper bound exclusive; a `filed_at` outside it is rejected with `ERR_CONTINUATION_OUTSIDE_WINDOW`. A continuation may be accepted against a root that is `ACTIVE` or one that has already `LAPSED` — the latter is the in-window late recording that revives it.

A successful acceptance stores `filing_number` and `filed_at`, moves the attempt `SUBMITTED` → `ACTIVE`, and appends an `ACCEPTED` event. What happens next depends on the filing kind:

- **`INITIAL`.** The attempt's `expiration_at` is set to exactly sixty calendar months after `filed_at`, preserving the day of month; when the resulting month has fewer days than that day of month, the day clamps to the last day of the resulting month.
- **`CONTINUATION`.** The root's effectiveness is extended by reading the root's currently stored `expiration_at`, adding sixty calendar months to that stored value under the same day-clamping month arithmetic, and persisting the result — the continuation's own `filed_at` is never the anchor, because a continuation extends from the date the filing would have lapsed, not from when it was filed. The root receives a `CONTINUED` event and a single `version` increment; if the root was `LAPSED`, it returns to `ACTIVE` with a `REVIVED` event, which is appended to the trail just before the `CONTINUED` event.
- **`AMENDMENT` with scope `DEBTOR_NAME`.** The root's `debtor_name_on_filing` is replaced by the attempt's `debtor_name_on_filing`; the root receives an `AMENDED` event and a `version` increment.
- **`AMENDMENT` with scope `COLLATERAL`.** An "ADD" operation appends the attempt's `collateral_text` to the root's `collateral_text` with a semicolon separator; a "DELETE" operation removes the supplied text as a substring of the root's `collateral_text` — only its first occurrence is removed — and if that text is not present the acceptance fails with `ERR_COLLATERAL_NOT_PRESENT`; a "RESTATE" operation replaces the root's `collateral_text` outright. The root receives an `AMENDED` event and a `version` increment.
- **`AMENDMENT` with scope `SECURED_PARTY`.** The root's `secured_party_id` is set to the request's `secured_party_id`; the root receives an `AMENDED` event and a `version` increment.
- **`TERMINATION`.** The root moves `ACTIVE` → `TERMINATED` with a `TERMINATED` event and a `version` increment, and the termination cascade fires: every other open `AMENDMENT` or `CONTINUATION` request targeting that root — any such request in `DRAFT_INTAKE`, `IN_REVIEW`, `READY`, or `CORRECTION_REQUIRED` — is cancelled with `cancel_reason` of `TARGET_TERMINATED`, and their `DRAFT` attempts are withdrawn.

Amendments and terminations leave the root's `expiration_at` unchanged. In all cases the parent request moves `IN_PROCESS` → `FULFILLED`; when the request kind is not `NEW_UCC1`, fulfillment also decreases the target root's `open_ucc3_request_count` by one and increments the root's `version` by one.

Rejection is likewise recorded by a `FilingOfficer`, against a `SUBMITTED` attempt, by supplying a `rejection_reason_code` — one of `NAME_MISMATCH`, `FEE_INCORRECT`, `WRONG_OFFICE`, `MISSING_SIGNATURE`, `DUPLICATE_FILING`, or `OTHER` — and an optional free-text `rejection_note`. The rejection stores the code, the note, and `rejected_at`; credits the client's `fees_refunded_total_cents` by the attempt's `charged_fee_cents`; moves the attempt `SUBMITTED` → `REJECTED`; moves the parent request `IN_PROCESS` → `CORRECTION_REQUIRED`; and appends a `REJECTED` event. That is the correction loop: rejection, correction of the preparation fields (§3.2), re-approval with a fresh quote (§3.3), and a superseding attempt within the thirty-day refiling window (§3.4).

Finally, a `DRAFT` attempt may be withdrawn by a `FilingSpecialist`, moving it `DRAFT` → `WITHDRAWN` with a `WITHDRAWN` event; from any other state withdrawal is rejected with `ERR_FILING_INVALID_STATE`. System cascades withdraw `DRAFT` attempts under the same transition when their request is cancelled.

### 3.6. Lapse, Revival, and Cancellation Cascades

Sixty months is the full effectiveness horizon, and the platform enforces it mechanically. The lapse sweep — run whenever the logical clock moves and at the start of every perfection-report generation, with a lazy single-filing re-check whenever one filing is read — transitions every `ACTIVE` filing whose `expiration_at` is at or before the current instant from `ACTIVE` to `LAPSED`; the boundary lapses, so an expiration exactly equal to now ends effectiveness. Each lapse appends a `LAPSED` event and cascades: every open `CONTINUATION`-kind request targeting the lapsed filing — any such request in `DRAFT_INTAKE`, `IN_REVIEW`, `READY`, or `CORRECTION_REQUIRED` — is cancelled with `cancel_reason` of `TARGET_LAPSED`, its `DRAFT` attempts move to `WITHDRAWN`, the root's `open_ucc3_request_count` decreases by one per cancelled request, and the root's `version` increments accordingly. Requests already `IN_PROCESS` are never cascade-cancelled, whether the trigger is a lapse or a termination.

Revival is narrow and deliberate: a `LAPSED` filing returns to `ACTIVE` only through acceptance of a continuation whose `filed_at` falls inside the window computed from the pre-lapse `expiration_at`, as described in §3.5. The revival appends a `REVIVED` event and extends effectiveness by sixty calendar months measured from the prior expiration.

Client-initiated cancellation gives up on a request before processing begins. A `FilingSpecialist` may cancel a request in `DRAFT_INTAKE`, `IN_REVIEW`, `READY`, or `CORRECTION_REQUIRED`; attempting to cancel one that is `IN_PROCESS` is rejected with `ERR_REQUEST_IN_PROCESS`. Cancellation sets the request to `CANCELLED` with `cancel_reason` of `CLIENT_REQUEST`, withdraws any `DRAFT` attempt under it (with a `WITHDRAWN` event), and — for the UCC-3 kinds — decreases the target root's `open_ucc3_request_count` by one and increments the root's `version` by one. Both `FULFILLED` and `CANCELLED` are terminal states for a request, and the three-way `cancel_reason` vocabulary — `CLIENT_REQUEST`, `TARGET_LAPSED`, `TARGET_TERMINATED` — records exactly why each cancellation happened.

### 3.7. Lien Searches and Search-to-Reflect Verification

A `FilingSpecialist` orders a lien search by providing `client_id`, `purpose`, `debtor_id`, and `jurisdiction_code`, with an optional `county_name` restriction. The `purpose` is `PRE_FILING` for diligence and prior-lien discovery or `POST_FILING_VERIFICATION` for search-to-reflect work; `subject_filing_id` is required exactly when the purpose is `POST_FILING_VERIFICATION`, and the subject filing must be `ACTIVE`, failing with `ERR_TARGET_FILING_NOT_ACTIVE` otherwise. A new search starts in `ORDERED`, and its terminal outcomes are `COMPLETED`, `VERIFIED`, and `DISCREPANCY`.

Results are recorded by a `SearchAnalyst`, who supplies the index's certified-through date `through_date` and the list of `hits`. The search must still be `ORDERED` (otherwise `ERR_SEARCH_NOT_ORDERED`), and `through_date` must not be later than the current instant (otherwise `ERR_INVALID_REQUEST`). Each supplied hit records `found_debtor_name`, `found_filing_number`, `found_filed_at`, and `secured_party_name` as they appear on the found record, and is parented to its search through `lien_search_id`. The system then classifies every hit: `hit_kind` is `EXACT_MATCH` when the normalized `found_debtor_name` equals the normalized debtor name of record under the name-match rule of §3.4, and `SIMILAR` otherwise; `is_subject_filing` is true exactly when the search has a subject and the hit's `found_filing_number` equals the subject's `filing_number`. Only `EXACT_MATCH` hits count toward prior-lien totals and priority position.

What the recording resolves to depends on the purpose. A `PRE_FILING` search moves `ORDERED` → `COMPLETED`, and its `prior_lien_count` is set to the number of `EXACT_MATCH` hits. A verification search first requires that `through_date` be on or after the subject filing's `filed_at` (otherwise `ERR_SEARCH_THROUGH_DATE_TOO_EARLY`). When a subject hit is present, the search moves to `VERIFIED` and `priority_position_of_subject` is computed as one plus the number of competing hits — `EXACT_MATCH` hits that are not the subject — that precede the subject in filing order, where a competing hit precedes the subject when its `found_filed_at` is earlier than the subject's `filed_at`, or when the two datetimes are equal and its `found_filing_number` sorts lexicographically before the subject's `filing_number`; with no preceding competitors the position is 1. The subject filing's `reflection_status` then moves to `REFLECTED` — from `UNVERIFIED` or from `DISCREPANCY` — with a `REFLECTED` event appended to the subject. When no subject hit is present, the search moves to `DISCREPANCY`, `priority_position_of_subject` stays null, and the subject's reflection moves from `UNVERIFIED` to `DISCREPANCY` with a `DISCREPANCY_FLAGGED` event; a subject already `REFLECTED` is never downgraded. Reflection and effectiveness are parallel dimensions on a filing: verification transitions never change `effectiveness_status`, and filing-office outcomes never change `reflection_status`, which evolves only through verification searches.

### 3.8. Portfolio Perfection Reporting

A `ClientManager` or a `FilingSpecialist` generates a perfection report for a client by choosing a `mode` — `AS_OF_NOW` or `FORWARD_PROJECTION` — and optionally a `horizon_days` lookahead window, which defaults to 90 and must be zero or more. Generation runs the lapse sweep first, so every count reflects expirations already reached, and then aggregates over the universe of the client's `INITIAL` filing attempts — every attempt whose `filing_kind` is `INITIAL` and whose parent request belongs to the client. UCC-3 attempts are transactions on their root filing, not portfolio line items, and are never counted in any bucket. The report's `as_of` is the current instant under `AS_OF_NOW` and the current instant plus `horizon_days` days under `FORWARD_PROJECTION`.

Under `AS_OF_NOW`, the buckets are: `active_count`, the attempts whose `effectiveness_status` is `ACTIVE`; `perfected_count`, those both `ACTIVE` and `REFLECTED`; `unreflected_count`, those `ACTIVE` with reflection `UNVERIFIED` or `DISCREPANCY`; `expiring_within_horizon_count`, the `ACTIVE` attempts whose `expiration_at` falls on or before now plus `horizon_days` days — the boundary is inclusive, so an expiration exactly at the horizon is counted; `lapsed_count` and `terminated_count`, the attempts in `LAPSED` and `TERMINATED` respectively; and `projected_lapsed_count`, which is always zero in this mode.

Under `FORWARD_PROJECTION`, the same population is reclassified against the horizon: `projected_lapsed_count` counts the `ACTIVE` attempts whose `expiration_at` falls on or before `as_of`; `active_count` counts the `ACTIVE` attempts whose `expiration_at` is strictly after `as_of`; `perfected_count` counts those still effective at `as_of` that are also `REFLECTED`; `unreflected_count` counts those still effective at `as_of` whose reflection is not `REFLECTED`; `expiring_within_horizon_count` equals `projected_lapsed_count`; and `lapsed_count` and `terminated_count` are computed exactly as under `AS_OF_NOW`. The projection deliberately ignores in-flight continuation requests — it is a pure no-action projection of what happens if nothing is filed.

Exposure figures aggregate only attempts whose `filing_kind` is `INITIAL`, so UCC-3 filings never double-count exposure. `perfected_exposure_cents` sums `secured_amount_cents` over the initial filings counted in `perfected_count`; `unperfected_exposure_cents` sums it over the initial filings counted in `unreflected_count`; and `projected_lapsed_exposure_cents` sums it over the initial filings counted in `projected_lapsed_count`, making it zero under `AS_OF_NOW`. Each generated report is an immutable snapshot retrievable later, scoped to its client through `client_id`.

## 4. Endpoint Definitions

Operations that create a new resource — a client account, a jurisdiction profile, a debtor, a secured party, a filing request, a filing attempt, a lien search, or a perfection report — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Request and response payloads are reconstructed from the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the lapse sweep at the new instant | PlatformAdmin |
| POST | `/client-accounts` | Create a client account | PlatformAdmin |
| GET | `/client-accounts` | List client accounts | All roles |
| GET | `/client-accounts/{id}` | Get a client account | All roles |
| POST | `/client-accounts/{id}/suspend` | Suspend a client (blocks intake submission only) | PlatformAdmin |
| POST | `/client-accounts/{id}/reinstate` | Reinstate a suspended client | PlatformAdmin |
| POST | `/jurisdiction-profiles` | Register a jurisdiction filing profile | PlatformAdmin |
| GET | `/jurisdiction-profiles` | List jurisdiction profiles | All roles |
| GET | `/jurisdiction-profiles/{id}` | Get a jurisdiction profile | All roles |
| PUT | `/jurisdiction-profiles/{id}` | Update a jurisdiction profile's fee and rule fields | PlatformAdmin |
| POST | `/client-accounts/{id}/debtors` | Register a debtor under a client | ClientManager |
| GET | `/client-accounts/{id}/debtors` | List a client's debtors | All roles |
| GET | `/debtors/{id}` | Get a debtor | All roles |
| PATCH | `/debtors/{id}` | Update debtor name-of-record fields | ClientManager |
| POST | `/client-accounts/{id}/secured-parties` | Register a secured party under a client | ClientManager |
| GET | `/client-accounts/{id}/secured-parties` | List a client's secured parties | All roles |
| GET | `/secured-parties/{id}` | Get a secured party | All roles |
| POST | `/filing-requests` | Intake a filing request | FilingSpecialist |
| GET | `/filing-requests` | List filing requests with filters | All roles |
| GET | `/filing-requests/{id}` | Get a filing request | All roles |
| PATCH | `/filing-requests/{id}` | Correct preparation fields on a pre-processing request | FilingSpecialist |
| POST | `/filing-requests/{id}/submit-intake` | Submit intake and determine the filing office | FilingSpecialist, FilingReviewer |
| POST | `/filing-requests/{id}/approve-preparation` | Approve preparation and snapshot the quoted fee | FilingReviewer |
| POST | `/filing-requests/{id}/cancel` | Cancel a pre-processing request | FilingSpecialist |
| POST | `/filing-requests/{id}/attempts` | Create a filing attempt under a READY request | FilingSpecialist |
| GET | `/filing-requests/{id}/attempts` | List attempts under a request | All roles |
| GET | `/filings` | List filings with filters | All roles |
| GET | `/filings/{id}` | Get a filing (lazily applies the lapse rule first) | All roles |
| GET | `/filings/{id}/name-check` | Evaluate debtor-name accuracy without mutating | All roles |
| POST | `/filings/{id}/submit` | Submit a DRAFT attempt to the filing office | FilingSpecialist |
| POST | `/filings/{id}/record-acceptance` | Record filing-office acceptance with filing number and date | FilingOfficer |
| POST | `/filings/{id}/record-rejection` | Record filing-office rejection | FilingOfficer |
| POST | `/filings/{id}/withdraw` | Withdraw a DRAFT attempt | FilingSpecialist |
| GET | `/filings/{id}/events` | List a filing's audit events chronologically | All roles |
| POST | `/lien-searches` | Order a lien search | FilingSpecialist |
| GET | `/lien-searches` | List lien searches with filters | All roles |
| GET | `/lien-searches/{id}` | Get a lien search | All roles |
| POST | `/lien-searches/{id}/record-results` | Record certified search results | SearchAnalyst |
| GET | `/lien-searches/{id}/hits` | List recorded search hits | All roles |
| POST | `/client-accounts/{id}/perfection-reports` | Generate a portfolio perfection report snapshot | ClientManager, FilingSpecialist |
| GET | `/client-accounts/{id}/perfection-reports` | List a client's perfection reports | All roles |
| GET | `/perfection-reports/{id}` | Get a perfection report snapshot | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is the identifier-to-status mapping only. Outside the catalogue, three framework-level fallbacks apply to every request: a request for an undeclared path receives `ERR_NOT_FOUND` (404), a declared path called with an unsupported method receives `ERR_METHOD_NOT_ALLOWED` (405), and an unexpected server failure surfaces as `ERR_INTERNAL` (500).

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_TARGET_FILING_REQUIRED` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_CLIENT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_JURISDICTION_NOT_FOUND` | 404 Not Found |
| `ERR_DEBTOR_NOT_FOUND` | 404 Not Found |
| `ERR_SECURED_PARTY_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_FILING_NOT_FOUND` | 404 Not Found |
| `ERR_SEARCH_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_STATE_CODE` | 409 Conflict |
| `ERR_CLIENT_SUSPENDED` | 409 Conflict |
| `ERR_REQUEST_INVALID_STATE` | 409 Conflict |
| `ERR_REQUEST_IN_PROCESS` | 409 Conflict |
| `ERR_REQUEST_NOT_READY` | 409 Conflict |
| `ERR_ATTEMPT_IN_FLIGHT` | 409 Conflict |
| `ERR_UCC3_IN_FLIGHT` | 409 Conflict |
| `ERR_FILING_INVALID_STATE` | 409 Conflict |
| `ERR_TARGET_FILING_NOT_ACTIVE` | 409 Conflict |
| `ERR_SEARCH_NOT_ORDERED` | 409 Conflict |
| `ERR_OVERLAPPING_ACTIVE_FILING` | 409 Conflict |
| `ERR_EXPEDITED_CAPACITY_REACHED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_COUNTY_REQUIRED` | 400 Bad Request |
| `ERR_COUNTY_NOT_IN_JURISDICTION` | 422 Unprocessable Entity |
| `ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING` | 422 Unprocessable Entity |
| `ERR_DEBTOR_DL_NAME_MISSING` | 422 Unprocessable Entity |
| `ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED` | 422 Unprocessable Entity |
| `ERR_COLLATERAL_NOT_PRESENT` | 422 Unprocessable Entity |
| `ERR_CONTINUATION_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_REFILE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SEARCH_STALE` | 422 Unprocessable Entity |
| `ERR_SEARCH_THROUGH_DATE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_INVALID_FILED_AT` | 422 Unprocessable Entity |
| `ERR_FEE_AUTHORIZATION_EXCEEDED` | 402 Payment Required |
