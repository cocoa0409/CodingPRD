# Film & TV Tax Incentive Application API — Product Requirements Document

## 1. Introduction

State film offices compete for production spending by offering transferable tax credits, and administering those programs is exacting work. Eligibility windows open and close on fixed fiscal calendars, every dollar of qualified spend must be traced to a vendor whose residency has been verified, above-the-line costs must be capped against the production's total, an independent CPA must attest the final figures, and the state must be able to claw value back when the facts on the ground change after issuance. This document specifies an API that administers the full life of a film and television tax incentive: a jurisdiction publishing its program and application window, producers filing applications, reviewers qualifying spend, CPA auditors attesting totals, certificates being issued, sold on a transfer market, redeemed against tax liability, and — when warranted — clawed back with interest.

Five communities of user interact with the system. Film office administrators configure programs, issue credits, settle transfers, and run enforcement actions. Eligibility reviewers claim and decide applications, verify vendor residency, qualify spend entries, and adjudicate audit packages. Production companies file applications, record spend, and sell or redeem the credits they earn. Independent CPA auditors engage audit packages and attest qualified-spend figures. Credit buyers purchase certificates on the transfer market. Every deadline, window, and expiry in the system is evaluated against a deterministic logical clock so program behavior is fully reproducible. All endpoints are mounted under the `/api` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. Domain narratives in §3 reference these principles rather than restating them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. The system recognizes exactly five roles. `FilmOfficeAdmin` is the state film office administrator: it configures programs, issues credits, settles transfers, administers clawback cases, and drives the test clock. `FilmOfficeReviewer` is the eligibility reviewer: it claims and decides applications, verifies vendor residency, qualifies spend entries, raises audit exceptions, and decides audit packages. `Producer` is the production company applicant: it registers companies, productions, and vendors, files and resubmits applications, records spend, sells and redeems credits, and appeals clawbacks. `CPAAuditor` is the independent CPA firm operator: it engages audit packages, submits drafts, and attests qualified-spend figures. `CreditBuyer` is a taxpayer purchasing credits on the transfer market. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; header values are trimmed of surrounding whitespace, and a blank `X-User-ID` or an `X-User-Role` value outside the five recognized roles counts as malformed. A request whose role is not on the target endpoint's authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting `ProductionCompany`: a production company self-registers, and the `id` returned by registration becomes the caller's identity thereafter. Ownership checks on any resource that references a `ProductionCompany` — directly or through the chain from an application or certificate back to its production — compare the resource's `production_company_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER`. When `X-User-Role` is `CreditBuyer`, `X-User-ID` is the `id` of the acting `CreditBuyer`, likewise established by self-registration, and ownership checks on a transfer compare the transfer's `buyer_id` to `X-User-ID`.

The remaining three roles carry opaque operator identifiers. When `X-User-Role` is `FilmOfficeAdmin`, `FilmOfficeReviewer`, or `CPAAuditor`, `X-User-ID` is not tied to any persisted entity. The server records it where a workflow demands accountability — a claiming reviewer is remembered as `reviewer_user_id`, a deciding reviewer as `decided_by_user_id`, a residency decision-maker as `residency_reviewed_by`, a spend reviewer as `reviewed_by`, and the engaging CPA as `cpa_user_id` — but it never compares such an identifier to an entity `id`. One exception in spirit, though not in mechanism: for `CPAAuditor` writes on an audit package, the package's stored `cpa_user_id` is compared to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER`.

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
- A request to an unrecognized path, or a recognized path with an unsupported method, is answered with the standard error envelope carrying `ERR_NOT_FOUND` and HTTP 404.

### 2.3. Pagination

Endpoints that return lists of resources paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. A non-integer value, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` rather than clamped. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order, with ties broken by insertion order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in the system carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, rendered from wall-clock time; `updated_at` is refreshed on every mutation of the resource. The `version` field is an integer starting at 1 on creation that increments by one on every mutation, including mutations performed by system cascades rather than direct client writes; a recompute cascade that leaves every stored value unchanged is not a mutation and does not increment `version`. Business instants stamped from the logical clock — `submitted_at`, `verified_at`, `attested_at`, `issued_at`, `expires_at`, `proposed_at`, `settled_at`, `notice_sent_at`, `appeal_deadline_at`, `appealed_at`, and `resolved_at` — are rendered as ISO 8601 UTC at whole-second precision (for example `2026-08-31T00:00:00Z`).

### 2.5. The Logical Clock

Every deadline, window, validity period, and expiry check in the system evaluates against a server-side logical clock, never against wall-clock time. The clock starts at the fixed instant `2026-08-01T00:00:00Z`. A `FilmOfficeAdmin`-only test-driving capability moves the logical clock to a supplied `to_iso8601` instant — forward or backward, with no monotonicity constraint — and reports the resulting `current_utc`; a `to_iso8601` value that is not a parseable ISO 8601 instant is rejected with `ERR_INVALID_REQUEST`. This is the only way time advances, and the server never falls back to wall-clock time.

### 2.6. Monetary Precision and Rounding Discipline

All monetary amounts are integer cents. Rates, shares, and uplift fractions are decimal numbers carried at input precision. Every calculation that produces a money amount finishes in whole cents, and the rounding method is round half up unless a rule explicitly states otherwise. Three rounding disciplines are pinned across the domain. First, the resident-labor uplift is rounded half up per spend entry before any summation; summing raw amounts first and rounding once at the category level is a different, non-conformant result. Second, the above-the-line cap product, the transfer price floor product, and the clawback interest cap all round down to whole cents. Third, multi-jurisdiction allocation percentages are rounded half up at one-hundredth of a percent, computed by multiplying by ten thousand, dividing by the sibling sum, rounding half up to a whole number, and dividing by one hundred.

### 2.7. The Program Cap Ledger

Each jurisdiction program behaves as a credit ledger governed by one invariant: `allocated_credit_cents` plus `remaining_cap_cents` always equals `annual_cap_cents`. At creation a program allocates nothing and its remaining cap equals the annual cap. Credit issuance debits the ledger — the remaining cap falls by the issued amount and the allocated total rises by the same amount. A sustained clawback restores the ledger — the amount recovered from a certificate returns to the remaining cap and leaves the allocated total. When an amend changes `annual_cap_cents`, the remaining cap is resized to the new annual cap minus the current allocated total. The invariant holds after every one of these mutations.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. Each guard field must be an integer; a decimal string carrying an integer value is tolerated and coerced, and a missing or otherwise malformed guard field is rejected with `ERR_INVALID_REQUEST`. Amending a program's configuration requires the request to carry `expected_program_version` equal to the program's current `version`; each amend legitimately supersedes the prior configuration values, so if the program's version has advanced past the one the client last observed, the amend is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412) rather than allowed to write on a stale basis. Proposing a credit transfer requires the request to carry `expected_certificate_version` equal to the certificate's current `version`; multiple open proposals against one certificate are legitimate product behavior, so if the certificate's version has advanced since the client last read it — because another proposal was created against it, for example — the create is rejected with `ERR_STALE_CERTIFICATE_VERSION` (HTTP 412), forcing the seller to re-read `remaining_amount_cents` and the outstanding proposals before proposing again.

### 2.9. Validation Order and Error Precedence

When a single request violates several rules, the failure that surfaces is the one belonging to the earliest category in the following evaluation order, with one overarching refinement: pure request-shape failures (category 13) are detected before every stateful category — once any path identifiers have been resolved per §2.10, a payload that is missing required fields, carries unknown fields, or holds invalid enum values, types, amounts, or date ranges is rejected with `ERR_INVALID_REQUEST` before body-reference resolution, ownership, state, or any later category is evaluated. Among the stateful categories the order below governs:

1. **User context** — the `X-User-ID` and `X-User-Role` headers are present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role is on the endpoint's authorized list (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Existence** — path identifiers and body references resolve to existing resources, validated path-first and left to right (`ERR_NOT_FOUND`).
4. **Ownership** — entity-backed callers own the resource chain they act on (`ERR_NOT_OWNER`).
5. **State-transition legality** — the target resource is in a state from which the requested transition is declared (`ERR_INVALID_STATE_TRANSITION`).
6. **Lifecycle uniqueness** — no second open application for the same production and program, no second non-rejected audit package, no second certificate, no submission while the program is not open (`ERR_APPLICATION_ALREADY_OPEN`, `ERR_AUDIT_PACKAGE_EXISTS`, `ERR_CERTIFICATE_ALREADY_ISSUED`, `ERR_PROGRAM_NOT_OPEN`).
7. **Stale-version OCC** — the expected version fields of §2.8 match (`ERR_STALE_PROGRAM_VERSION`, `ERR_STALE_CERTIFICATE_VERSION`).
8. **Compliance gates** — vendor residency verified at spend qualification, an accepted audit package at issuance, documentation complete and no pending entries at attestation, and the segregation-of-duties pairings (`ERR_VENDOR_RESIDENCY_NOT_VERIFIED`, `ERR_AUDIT_NOT_ACCEPTED`, `ERR_AUDIT_PACKAGE_INCOMPLETE`, `ERR_SPEND_ENTRIES_PENDING`, `ERR_SEGREGATION_OF_DUTIES`).
9. **Temporal windows** — the logical-clock checks on submission windows, vendor verification validity, certificate expiry, transfer expiry, the appeal window, and the notice quiet period (`ERR_WINDOW_NOT_YET_OPEN`, `ERR_APPLICATION_DEADLINE_PASSED`, `ERR_VERIFICATION_WINDOW_EXPIRED`, `ERR_CERTIFICATE_EXPIRED`, `ERR_TRANSFER_EXPIRED`, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_NOTICE_WINDOW_ACTIVE`).
10. **Structural uniqueness and geometry** — program window overlap per jurisdiction and per-production invoice uniqueness (`ERR_PROGRAM_WINDOW_OVERLAP`, `ERR_DUPLICATE_SPEND_INVOICE`).
11. **Referential coherence** — the spend entry's vendor belongs to the application's production, and an amendment target belongs to the same application in an amendable status (`ERR_VENDOR_PRODUCTION_MISMATCH`, `ERR_AMENDMENT_TARGET_MISMATCH`).
12. **Fiscal checks** — minimum spend gates, program cap sufficiency, the transfer price floor, amounts against remaining balances, and the clawback base against the issued amount (`ERR_MINIMUM_SPEND_NOT_MET`, `ERR_PROGRAM_CAP_EXHAUSTED`, `ERR_TRANSFER_PRICE_BELOW_FLOOR`, `ERR_AMOUNT_EXCEEDS_REMAINING`, `ERR_CLAWBACK_EXCEEDS_EXPOSURE`).
13. **Request shape** — required fields present, enums valid, amounts positive, date ranges coherent, conditional fields present, and no unknown payload fields (`ERR_INVALID_REQUEST`).

### 2.10. Nested Resource Retrieval and Reference Resolution

Requests that carry resource identifiers resolve them in a fixed order: identifiers in the path first, from left to right, then foreign-key references in the request body. The first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND`, and no further validation runs.

### 2.11. Segregation of Duties

Two decision points in the program demand a fresh pair of eyes. An application may be approved or denied only by a `FilmOfficeReviewer` whose `X-User-ID` differs from the `reviewer_user_id` who claimed the review. An audit package may be accepted or rejected only by a `FilmOfficeReviewer` whose `X-User-ID` differs from the package's `cpa_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 3. Business Logic & Workflows

### 3.1. Program Configuration and the Application Window

A `FilmOfficeAdmin` configures each jurisdiction's incentive offering as a **JurisdictionProgram**. Registration captures the `jurisdiction_code` (a state or jurisdiction code such as GA), a display `program_name`, the `fiscal_year` label, the application window bounded by `window_opens_at` and `window_closes_at`, the `annual_cap_cents` funding the program for the year, and the per-application `minimum_qualified_spend_cents`. The same registration carries the economic parameters, each described where it takes effect: the standard and elevated credit rates with their tier threshold (§3.9), the above-the-line share cap and the resident-labor uplift (§3.4), the vendor verification validity (§3.4), the certificate validity (§3.6), the transfer price floor and proposal validity (§3.7), and the appeal window and daily interest rate governing clawbacks (§3.8). The window must open strictly before it closes, and the annual cap must be positive; malformed configuration is rejected with `ERR_INVALID_REQUEST`. All registration fields are required. The rate and percentage parameters (`base_rate_standard`, `base_rate_elevated`, `atl_cap_pct`, `resident_uplift_pct`, `transfer_price_floor_pct`, `daily_interest_rate`) accept any JSON number without range constraint, while `minimum_qualified_spend_cents`, `elevated_tier_threshold_cents`, and the day-count parameters (`vendor_verification_validity_days`, `appeal_window_days`, `credit_validity_days`, `transfer_proposal_validity_days`) must be non-negative integers — zero is permitted. A new program starts in `DRAFT` status with `allocated_credit_cents` at zero and `remaining_cap_cents` equal to the annual cap.

Only one active program per jurisdiction may occupy a given span of time. For this check a window is a half-open interval that includes its opening instant and excludes its closing instant, and two windows conflict when they intersect — each opening strictly before the other closes. Windows that merely touch, one closing at the exact instant the other opens, do not conflict. The check runs against every other program with the same `jurisdiction_code` whose status is anything other than `CLOSED`, and it runs when a program is created, whenever an amend changes the window, and on every transition into `OPEN`, including re-entry from `SUSPENDED`. A conflict is rejected with `ERR_PROGRAM_WINDOW_OVERLAP`.

Program lifecycle transitions are driven by an admin's transition request carrying a `to_state`; a `to_state` value outside `DRAFT`, `OPEN`, `SUSPENDED`, and `CLOSED` is a request-shape failure rejected with `ERR_INVALID_REQUEST`. A program moves from `DRAFT` to `OPEN`, which publishes the window for submissions; every transition into `OPEN` — both the initial publication and re-entry from `SUSPENDED` — re-validates that the window opens strictly before it closes (`ERR_INVALID_REQUEST`) and re-runs the overlap check. A program moves from `OPEN` to `SUSPENDED` and back to `OPEN`, and from either `OPEN` or `SUSPENDED` to `CLOSED`, which is terminal. A transition that is not declared from the program's current status is rejected with `ERR_INVALID_STATE_TRANSITION`.

While a program is in `DRAFT` or `OPEN`, an admin may amend its configuration — the window bounds, the annual cap, the minimum spend, the rates and tier threshold, the caps and uplift, the price floor, and the validity, window, interest, and expiry durations — supplying only the fields being changed; an amendable field explicitly supplied as null is rejected with `ERR_INVALID_REQUEST`, and the same field-type and range rules as registration apply to each supplied value. Amendments are guarded by optimistic concurrency as described in §2.8, increment the program's `version` by one, and legitimately supersede the prior configuration values. A change to `annual_cap_cents` resizes the remaining cap per §2.7, and a change to the window re-runs the overlap check. Amending a `SUSPENDED` or `CLOSED` program is rejected with `ERR_INVALID_STATE_TRANSITION`. Programs can be listed with optional `status`, `jurisdiction_code`, and `fiscal_year` filters, or retrieved individually.

### 3.2. Party Registration and Vendor Residency

A `Producer` begins by self-registering a **ProductionCompany** with its `legal_name`, a unique `fein`, and a `contact_email` — uniqueness of the `fein` is descriptive of the identifier, not a server-enforced constraint, and a duplicate value is accepted; the `id` in the response becomes the caller's identity for all subsequent ownership checks (§2.1). The producer then creates **Production** records under a company it owns — a `production_company_id` that does not match the caller's identity is rejected with `ERR_NOT_OWNER` — supplying a `title`, a `production_type` of `FEATURE`, `SERIES`, `DOCUMENTARY`, or `COMMERCIAL`, a `scheduled_start_date` that must fall strictly before the `scheduled_wrap_date`, and a positive `total_budget_cents`; violations of the date ordering or amount rules are rejected with `ERR_INVALID_REQUEST`. The wrap date later anchors the cash-flow milestones of §3.9. Productions can be listed with an optional `production_company_id` filter.

A `CreditBuyer` self-registers with its `legal_name`, a unique `tax_id` (again descriptive rather than server-enforced), and a `contact_email`, and likewise adopts the returned `id` as its identity.

Vendors are registered per production. A producer registers a **Vendor** on a production it owns with the `production_id`, the vendor's `legal_name` and `tax_id`, and the claimed `residency_jurisdiction`. A new vendor starts with `residency_status` `UNVERIFIED` and `verified_at` null. A `FilmOfficeReviewer` decides residency by submitting a `decision` of `VERIFIED` or `REJECTED`, optionally accompanied by a `rejection_reason` (accepted but not persisted). The declared decisions are `UNVERIFIED` to `VERIFIED` or `REJECTED`, `REJECTED` to `VERIFIED`, and `VERIFIED` to `REJECTED`; re-affirming the current status — `VERIFIED` to `VERIFIED` or `REJECTED` to `REJECTED` — is not a declared transition and is rejected with `ERR_INVALID_STATE_TRANSITION`. A decision of `VERIFIED` — whether from `UNVERIFIED` or from `REJECTED` — stamps `verified_at` with the logical-clock instant of the decision and records the reviewer as `residency_reviewed_by`; a decision of `REJECTED` from `UNVERIFIED` records only the `residency_reviewed_by`, and a revoking `REJECTED` decision leaves the previously stamped `verified_at` in place. The cycle is open: a rejected vendor can be re-reviewed back to `VERIFIED`, with `verified_at` moving to the new decision instant.

Revoking a vendor — the transition from `VERIFIED` to `REJECTED` — fires a deep cascade. Every spend entry anywhere in the production, across all of the production's applications in every jurisdiction, that names this vendor and currently stands `QUALIFIED` is moved to `DISQUALIFIED` with its `disqualify_reason` set to `VENDOR_RESIDENCY_REVOKED`. Each affected application then recomputes its qualified totals, its capped total, its provisional and recomputed credit figures, and its allocation share per the rules of §3.4 and §3.9. For each affected application that already holds a certificate, the certificate's `overissued_exposure_cents` is recomputed, and a transition from zero to a positive exposure auto-opens — or updates the shortfall of an existing unresolved — `SPEND_SHORTFALL` clawback case as described in §3.8. Vendors can be listed with optional `production_id` and `residency_status` filters.

### 3.3. The Application Lifecycle: Filing, Review, and Decision

A producer files an **IncentiveApplication** by naming the `production_id`, the `jurisdiction_program_id`, and an `estimated_qualified_spend_cents`, which must be a non-negative integer. Creation never consults the program's status or window — those gates apply only at submission. The caller must own the production's company (`ERR_NOT_OWNER`). Only one open application may exist for a production-and-program pair: if another application with the same `production_id` and `jurisdiction_program_id` exists in any status other than `DENIED`, `WITHDRAWN`, or `REVOKED`, creation is rejected with `ERR_APPLICATION_ALREADY_OPEN`; reaching one of those three terminal states frees the pair for a fresh filing. A new application starts in `DRAFT` with all computed totals at zero, `allocation_share_pct` at zero, `submitted_at` null, and `final_credit_cents` null. Applications can be listed with optional `production_id`, `jurisdiction_program_id`, and `status` filters.

Submission moves an application from `DRAFT` to `SUBMITTED` and stamps `submitted_at` with the logical-clock instant. The submission request carries no payload fields — as do withdrawal, claim, resubmission, and approval; any supplied field is rejected with `ERR_INVALID_REQUEST`. Submission is an owner-only action (`ERR_NOT_OWNER`) gated by the program's window: the program must currently be `OPEN`, or the attempt is rejected with `ERR_PROGRAM_NOT_OPEN`; the clock must have reached `window_opens_at`, or the attempt is rejected with `ERR_WINDOW_NOT_YET_OPEN`; and the clock must not have passed `window_closes_at` — the deadline boundary is inclusive, so submission at the exact closing instant is allowed, and any later attempt is rejected with `ERR_APPLICATION_DEADLINE_PASSED`.

Withdrawal is available to the owning producer from `DRAFT`, from `SUBMITTED`, from `UNDER_REVIEW`, and from `CORRECTION_REQUESTED`, each moving the application to the terminal `WITHDRAWN` state.

Once an application is `SUBMITTED`, a `FilmOfficeReviewer` claims it, moving it to `UNDER_REVIEW` and recording their operator id as `reviewer_user_id`. While the application stands `UNDER_REVIEW`, any `FilmOfficeReviewer` — the reviewer-operator check of §2.11 applies only to approve and deny decisions, so the corrections requester need not be the claiming reviewer — may send the application back for corrections, moving it to `CORRECTION_REQUESTED`; an optional `notes` message may accompany the request and is accepted but not persisted. The owning producer may resubmit, cycling it back to `UNDER_REVIEW`. The correction loop is unbounded: an application may pass through `UNDER_REVIEW` and `CORRECTION_REQUESTED` any number of times.

Decisions are taken under the segregation-of-duties rule of §2.11: the reviewer who approves or denies must be a different operator than the one recorded as `reviewer_user_id`, and a same-operator decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval additionally requires the application's `estimated_qualified_spend_cents` to be at least the program's `minimum_qualified_spend_cents`; otherwise approval is rejected with `ERR_MINIMUM_SPEND_NOT_MET`. Approval moves the application to `APPROVED`, records the decider as `decided_by_user_id`, and recomputes the `allocation_share_pct` of this application and of every sibling application of the same production (§3.9). Denial moves the application to the terminal `DENIED` state — an optional `reason` may accompany the request and is accepted but not persisted — and likewise records `decided_by_user_id`.

`APPROVED` is the working state: spend may now be recorded and qualified (§3.4), a CPA audit may be engaged (§3.5), and ultimately credit may be issued (§3.6). The resulting `CREDIT_ISSUED` state is not terminal — a sustained clawback revokes the application to `REVOKED` (§3.8). Any action attempted from a state where that transition is not declared — submitting an application that is not in `DRAFT`, for instance — is rejected with `ERR_INVALID_STATE_TRANSITION`.

### 3.4. Recording and Qualifying Production Spend

Once an application stands `APPROVED` or `CREDIT_ISSUED`, the owning producer records production spend against it. Recording a **SpendEntry** takes the `application_id`, the `vendor_id`, an `external_invoice_ref` identifying the vendor's invoice, a `category` of `ATL` (above the line) or `BTL` (below the line), the `spend_date` on which the cost was incurred, and a positive `amount_cents`; an optional `is_resident_labor` flag defaults to false, and an optional `amends_entry_id` supports correction by amendment. Recording spend while the application is in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. Two coherence guards protect the ledger: the named vendor must belong to the same production as the application (`ERR_VENDOR_PRODUCTION_MISMATCH`), and the `external_invoice_ref` must not already appear on any non-`SUPERSEDED` spend entry of the same production — across all of that production's applications, in every jurisdiction (`ERR_DUPLICATE_SPEND_INVOICE`). This per-production invoice uniqueness is the structural double-count guard that makes multi-jurisdiction filing safe (§3.9). A new entry starts in `PENDING_REVIEW` with `effective_amount_cents` at zero; spend entries can be listed with optional `application_id`, `vendor_id`, `amends_entry_id`, and `status` filters.

Amendment replaces a mis-recorded entry without history loss. When `amends_entry_id` is present on a new entry, the referenced entry must belong to the same application and stand in `PENDING_REVIEW`, `QUALIFIED`, or `DISQUALIFIED` — an identifier that resolves to no entry at all is rejected with `ERR_NOT_FOUND` per the reference-resolution rule of §2.10, while a cross-application or already-`SUPERSEDED` target is rejected with `ERR_AMENDMENT_TARGET_MISMATCH`. The target atomically becomes `SUPERSEDED`, which is terminal, and the new entry replaces it in `PENDING_REVIEW`. When the superseded entry had been `QUALIFIED`, its effective amount drops out of the application totals through the same recompute cascade a disqualification would trigger, including certificate exposure and any auto-opened clawback case described below.

Review is performed by a `FilmOfficeReviewer` submitting a `decision` of `QUALIFY` or `DISQUALIFY`, the latter recording the supplied `disqualify_reason`; either way the reviewer is remembered as `reviewed_by`. The decision matrix is exact: `QUALIFY` is declared from `PENDING_REVIEW` and from `DISQUALIFIED`, and `DISQUALIFY` is declared from `PENDING_REVIEW` and from `QUALIFIED`; every other pairing — qualifying an already-`QUALIFIED` entry, disqualifying an already-`DISQUALIFIED` entry, or reviewing a `SUPERSEDED` entry at all — is not a declared transition and fails with `ERR_INVALID_STATE_TRANSITION`. Qualifying an entry first requires the application to be `APPROVED` or `CREDIT_ISSUED` (`ERR_INVALID_STATE_TRANSITION`), then requires the vendor's `residency_status` to be `VERIFIED` (`ERR_VENDOR_RESIDENCY_NOT_VERIFIED`), and finally requires the `spend_date` — itself an ISO 8601 datetime — to fall inside the vendor's verification validity window: on or after the vendor's `verified_at` and strictly before the instant the program's `vendor_verification_validity_days` days after `verified_at` — evaluated against the application's program (`ERR_VERIFICATION_WINDOW_EXPIRED`). Re-qualifying a `DISQUALIFIED` entry re-applies the same vendor-residency and verification-window checks.

The effective amount of a qualified entry is computed at review time with a pinned rounding order. For a `BTL` entry flagged `is_resident_labor` whose vendor stood `VERIFIED` at review time, `effective_amount_cents` is the entry's `amount_cents` plus that amount multiplied by the program's `resident_uplift_pct`, with the uplift rounded half up to whole cents per entry before any summation. Every other qualified entry's `effective_amount_cents` equals its `amount_cents`. While an entry is not `QUALIFIED` — pending, disqualified, or superseded — its effective amount is zero. Disqualifying a previously `QUALIFIED` entry returns its effective amount to zero.

Whenever the qualified set of an application changes — an entry created with a superseding amendment, a qualify or disqualify decision, the vendor-revocation cascade of §3.2, or an audit acceptance that refreshes figures (§3.5) — the application recomputes its totals. `atl_qualified_cents` is the sum of `effective_amount_cents` over the application's `QUALIFIED` `ATL` entries, and `btl_qualified_cents` the same sum over `BTL` entries; entries in any other status never contribute. The above-the-line cap then applies in a pinned evaluation order. First, the pre-cap total is the raw ATL sum plus the raw BTL sum. Second, the ATL cap in cents is the program's `atl_cap_pct` multiplied by that pre-cap total, rounded down to whole cents. Third, the capped ATL is the lesser of the raw ATL sum and the cap. Finally, `capped_total_qualified_cents` is the capped ATL plus the full BTL sum. BTL is never capped, the cap base is always the raw sums — never the capped ATL — and rounding the cap half up instead of down is non-conformant. From there, `provisional_credit_cents` refreshes as the PROVISIONAL credit variant over the system-qualified sums (§3.9), landing at zero when the capped total falls below the program minimum, and `recomputed_credit_cents` refreshes as the same computation over the current sums, which after issuance drives the certificate's exposure (§3.6). The `allocation_share_pct` of the application and of every sibling recomputes as well (§3.9). When the application already holds a certificate, its `overissued_exposure_cents` is recomputed on the same pass, and a transition from zero to a positive value auto-opens — or updates the shortfall of an existing unresolved — `SPEND_SHORTFALL` clawback case (§3.8).

### 3.5. The CPA Audit: Engagement, Fieldwork, and Attestation

An independent audit is engaged once an application stands `APPROVED`. A `CPAAuditor` creates an **AuditPackage** naming the `application_id`; engagement is rejected with `ERR_INVALID_STATE_TRANSITION` when the application is in any other status, and with `ERR_AUDIT_PACKAGE_EXISTS` when the application already has a package in any status other than `REJECTED` — at most one live package exists per application, which is why filtering the audit-package list by `application_id` (or by `status`) returns an array of zero or one. The package starts `ENGAGED`, with the caller's operator id recorded as `cpa_user_id`, `exception_count` at zero, and `documentation_complete` null.

Draft submission is the CPA's act alone: only the operator whose id matches `cpa_user_id` may submit (`ERR_NOT_OWNER`). Submitting a draft — from `ENGAGED`, or again from `FIELDWORK` after rework — requires a boolean `documentation_complete` in the request, records it on the package, and moves the package to `DRAFT_SUBMITTED`. A `FilmOfficeReviewer` who finds problems raises exceptions, carrying a required `exception_notes` string with the request, which returns the package to `FIELDWORK` and increments `exception_count` by one. The rework cycle between `DRAFT_SUBMITTED` and `FIELDWORK` is unbounded.

Attestation locks the CPA's figures. From `DRAFT_SUBMITTED`, the engaging CPA attests with `attested_atl_cents`, `attested_btl_cents` — both required non-negative integers — and a required boolean `documentation_complete`. Two gates apply: `documentation_complete` must be true in the attestation request itself (`ERR_AUDIT_PACKAGE_INCOMPLETE`), and no spend entry of the application may still stand `PENDING_REVIEW` (`ERR_SPEND_ENTRIES_PENDING`). Attestation records the two attested amounts and stamps `attested_at`, moving the package to `ATTESTED`; until that moment both attested amounts and `attested_at` are null.

The decision belongs to a `FilmOfficeReviewer` acting under segregation of duties: the decider's operator id must differ from the package's `cpa_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and the decider is recorded as `decided_by_user_id`. A decision `outcome` of `ACCEPT` moves the package to the terminal `ACCEPTED` state and locks the application's `final_credit_cents` — null until this moment — to the FINAL variant of the credit computation over the attested above- and below-the-line sums (§3.9); the application's `recomputed_credit_cents` is refreshed on the same pass. A decision `outcome` of `REJECT`, optionally justified by a `decision_reason` (accepted but not persisted), moves the package to the terminal `REJECTED` state and leaves the application `APPROVED`; because a `REJECTED` package no longer blocks creation, a fresh audit engagement may follow.

### 3.6. Credit Issuance and the Certificate

Issuance is performed by a `FilmOfficeAdmin` once the audit has landed, and it is the moment the program ledger moves. Issuing credit against an application requires the application to stand `APPROVED`; an issuance request against an application that is already `CREDIT_ISSUED` is mapped explicitly to `ERR_CERTIFICATE_ALREADY_ISSUED` rather than a generic state-transition error, and the same error answers any attempt to create a second certificate for one application. An audit package for the application must stand `ACCEPTED` (`ERR_AUDIT_NOT_ACCEPTED`). The locked `final_credit_cents` must be greater than zero — which is precisely the condition that the attested capped total meets the program's `minimum_qualified_spend_cents` (`ERR_MINIMUM_SPEND_NOT_MET`) — and it must not exceed the program's `remaining_cap_cents`, with an exact fit allowed (`ERR_PROGRAM_CAP_EXHAUSTED`).

Issuance creates the **CreditCertificate** one-to-one with its application. The certificate receives a server-minted `certificate_number` used for identity only — never consulted in any business decision — an `issued_amount_cents` equal to the application's `final_credit_cents`, a `remaining_amount_cents` equal to the issued amount, cumulative `redeemed_total_cents` and `transferred_total_cents` at zero, an `overissued_exposure_cents` at zero, an `issued_at` stamped with the logical clock, and an `expires_at` set to the issuance instant plus the program's `credit_validity_days` days; the certificate stands `ISSUED`. The same operation debits the program ledger per §2.7 — `remaining_cap_cents` falls by the final credit and `allocated_credit_cents` rises by it — pins the application's `recomputed_credit_cents` to `final_credit_cents` at that instant, and moves the application to `CREDIT_ISSUED`. Certificates can be listed with optional `application_id` and `status` filters; because the relationship is one-to-one, an application-filtered list returns an array of zero or one.

Two invariants govern the certificate for the rest of its life. Conservation: `issued_amount_cents` always equals `remaining_amount_cents` plus the cumulative settled transfer amounts plus the cumulative redemptions plus whatever has been recovered through clawback. Exposure: `overissued_exposure_cents` is the amount by which `issued_amount_cents` exceeds the application's `recomputed_credit_cents`, or zero when it does not; it is recomputed whenever the application's totals change after issuance, a transition from zero to positive auto-opens or updates a `SPEND_SHORTFALL` clawback case (§3.8), and no exposure recomputation ever changes the certificate's `status` by itself.

### 3.7. The Transfer Market: Negotiation, Settlement, and Redemption

A producer who would rather monetize a certificate than redeem it proposes a **CreditTransfer**, naming the `certificate_id`, the purchasing `buyer_id`, a positive `amount_cents` of face value, and the agreed `price_cents` — a non-negative integer, with zero permitted — and carrying the `expected_certificate_version` guard of §2.8. The certificate must stand `ISSUED` or `PARTIALLY_TRANSFERRED` and must be unexpired — the logical clock at or before its `expires_at` (`ERR_CERTIFICATE_EXPIRED`). The face amount must not exceed the certificate's `remaining_amount_cents` (`ERR_AMOUNT_EXCEEDS_REMAINING`). And the price must clear the floor: `price_cents` must be at least the program's `transfer_price_floor_pct` multiplied by `amount_cents` and rounded down to whole cents — the exact floor is allowed — with the program resolved through the certificate's application (`ERR_TRANSFER_PRICE_BELOW_FLOOR`). A created transfer stands `PROPOSED` with `proposed_at` stamped, an `expires_at` of the proposal instant plus the program's `transfer_proposal_validity_days` days, `current_price_cents` initialized to `price_cents`, `round_count` at zero, and the `seller_production_company_id` derived from the certificate's application and production. Creating a proposal increments the certificate's `version` by one, which is what arms the optimistic-concurrency guard for the next proposer; multiple open proposals against one certificate are legitimate.

Negotiation alternates sides: the party not holding the standing offer counters. While the transfer stands `PROPOSED`, the seller's offer is on the table and the buyer counters with a `new_price_cents` — a non-negative integer, with zero permitted — moving the transfer to `COUNTERED`. While it stands `COUNTERED`, the buyer's offer is on the table and the seller — the producer owning `seller_production_company_id` — counters back with its own `new_price_cents`, returning the transfer to `PROPOSED`. Every counter requires the acting party's ownership (`ERR_NOT_OWNER`), an unexpired proposal — clock at or before the transfer's `expires_at` (`ERR_TRANSFER_EXPIRED`) — and a new price that re-clears the same floor against the transfer's face amount (`ERR_TRANSFER_PRICE_BELOW_FLOOR`); each counter sets `current_price_cents` to the new price and increments `round_count` by one. The loop is unbounded. Acceptance mirrors the split: the buyer accepts while the transfer stands `PROPOSED`, and the seller accepts while it stands `COUNTERED`, each moving the transfer to `ACCEPTED` subject to the same expiry check. Cancellation is a seller-side act — the producer owning the seller production company cancels a `PROPOSED` or `COUNTERED` transfer, with `ERR_NOT_OWNER` answering anyone outside that ownership chain — and a buyer may likewise withdraw a counter-offer it placed; either path lands in the terminal `CANCELLED` state with `cancellation_reason` set to `MANUAL`, and an optional `cancel_reason` note may accompany the request — accepted but not persisted. `cancellation_reason` is null unless the transfer is `CANCELLED`. Transfers can be listed with optional `certificate_id`, `buyer_id`, and `status` filters.

Settlement is the film office's desk: a `FilmOfficeAdmin` settles an `ACCEPTED` transfer. Four gates apply — the certificate must stand `ISSUED` or `PARTIALLY_TRANSFERRED` (`ERR_INVALID_STATE_TRANSITION`), the clock must not have passed the certificate's `expires_at` (`ERR_CERTIFICATE_EXPIRED`), the clock must not have passed the transfer's own `expires_at` (`ERR_TRANSFER_EXPIRED`), and the transfer's `amount_cents` must not exceed the certificate's `remaining_amount_cents` at settlement (`ERR_AMOUNT_EXCEEDS_REMAINING`). Settlement pays the standing `current_price_cents`, moves the transfer to the terminal `SETTLED` state, stamps `settled_at` — null until this moment — and debits the certificate: `remaining_amount_cents` falls by the face amount and `transferred_total_cents` rises by it. The certificate moves from `ISSUED` to `PARTIALLY_TRANSFERRED` when a slice remains, or to `FULLY_TRANSFERRED` when the settled amount consumes the remainder exactly — whether directly from `ISSUED` or from `PARTIALLY_TRANSFERRED`. Settlement then sweeps the order book: every other transfer of the same certificate still standing `PROPOSED` or `COUNTERED` whose face amount now exceeds the reduced remainder is cancelled with `cancellation_reason` `INSUFFICIENT_REMAINING`.

Redemption is the alternative exit. The owning producer redeems against a certificate standing `ISSUED` or `PARTIALLY_TRANSFERRED` with a `redeem_amount_cents` that must be positive and must not exceed `remaining_amount_cents` (`ERR_AMOUNT_EXCEEDS_REMAINING`), at or before the certificate's `expires_at` — the expiry boundary is inclusive here exactly as it is for transfer proposals, counters, and settlements — with any later attempt rejected with `ERR_CERTIFICATE_EXPIRED`, and only as the owner of the certificate's production company (`ERR_NOT_OWNER`). Redemption reduces `remaining_amount_cents` and increases `redeemed_total_cents` by the redeemed amount. Redeeming the full remaining balance — from `ISSUED` or from `PARTIALLY_TRANSFERRED` — closes the certificate as `REDEEMED`; a partial redemption leaves the status unchanged.

### 3.8. Clawback Cases: Notice, Appeal, and Recovery

A **ClawbackCase** arises in two ways. A `FilmOfficeAdmin` opens one manually against an application standing `CREDIT_ISSUED` — any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — supplying the `application_id`, a `trigger_reason` of `SPEND_SHORTFALL`, `RESIDENCY_FAILURE`, `MISSING_AUDIT`, or `MISREPRESENTATION`, an optional `penalty_mode` that defaults to `SIMPLE` and may be `AGGRAVATED`, and an optional `shortfall_amount_cents` that defaults to the certificate's current `overissued_exposure_cents` when omitted. The assessment base must be positive and must not exceed the certificate's `issued_amount_cents`; a base of zero or one exceeding the issued amount is rejected with `ERR_CLAWBACK_EXCEEDS_EXPOSURE`. The case opens in `OPENED` with its `certificate_id` derived from the application's certificate, `recovered_from_certificate_cents` at zero, and `notice_sent_at`, `appeal_deadline_at`, `appealed_at`, `resolved_at`, `interest_cents`, `assessed_total_cents`, `cash_assessment_cents`, and `settled_amount_cents` all null. Cases also arise automatically: whenever a certificate's exposure transitions from zero to positive — through a disqualification, a superseding amendment, or the vendor-revocation cascade — the system opens a `SPEND_SHORTFALL` case at the current exposure, or, when an unresolved `SPEND_SHORTFALL` case already exists for the certificate (one standing `OPENED`, `NOTICE_SENT`, or `APPEALED`), updates that case's shortfall to the current exposure instead; an exposure change that does not cross from zero — growth between positive values, or a return to zero — opens no case and updates none. Cases can be listed with optional `application_id`, `certificate_id`, and `status` filters.

Notice starts the clock. An admin sending the notice moves the case from `OPENED` to `NOTICE_SENT`, stamping `notice_sent_at` and computing `appeal_deadline_at` as the notice instant plus the program's `appeal_window_days` days. The owning producer may then appeal — optionally stating `appeal_grounds`, which is accepted but not persisted — while the clock stands at or before `appeal_deadline_at`; a late appeal is rejected with `ERR_APPEAL_WINDOW_CLOSED`. A successful appeal stamps `appealed_at` and moves the case to `APPEALED`.

Resolution takes an `outcome` of `SUSTAINED`, `VACATE`, or `SETTLE`, from `NOTICE_SENT` or from `APPEALED`, moving the case to the corresponding terminal state `SUSTAINED`, `VACATED`, or `SETTLED`, and stamps `resolved_at` — null until this moment. Sustaining from `NOTICE_SENT` additionally requires the appeal window to have lapsed: the clock must stand strictly after `appeal_deadline_at`, and an attempt during the quiet period is rejected with `ERR_NOTICE_WINDOW_ACTIVE`; sustaining from `APPEALED` carries no such waiting period, the appeal having been heard.

A sustained case computes its assessment from the case, its certificate, and the program. The day count is the whole days of elapsed time from `notice_sent_at` to `resolved_at` — the floor of the elapsed span divided by twenty-four hours — so two instants less than a full day apart, or two instants on the same calendar day, both yield zero, and a clock set backward between notice and resolution yields zero rather than a negative count. Raw interest is the `shortfall_amount_cents` multiplied by the program's `daily_interest_rate` multiplied by the day count, rounded half up to whole cents, and `interest_cents` is the lesser of that raw interest and one half of the shortfall base rounded down to whole cents. Under `SIMPLE` — the default, suited to shortfalls and residency failures — `assessed_total_cents` is the shortfall base plus the interest. Under `AGGRAVATED` — intended for misrepresentation — `assessed_total_cents` is the base multiplied by 1.25 and rounded half up to whole cents, plus the interest; for any positive base the aggravated total is strictly greater than the simple one.

Sustaining then executes the full recovery cascade. The certificate moves to `CLAWED_BACK` — identically whether it stood `ISSUED` or `PARTIALLY_TRANSFERRED`: its entire `remaining_amount_cents` at that instant is forfeited, `recovered_from_certificate_cents` records the forfeited amount, and the remainder drops to zero. The forfeited amount flows back to the program — `remaining_cap_cents` rises by the recovery and `allocated_credit_cents` falls by it, preserving the ledger invariant of §2.7. Every transfer of the certificate still standing `PROPOSED`, `COUNTERED`, or `ACCEPTED` is cancelled with `cancellation_reason` `CERTIFICATE_CLAWED_BACK`. The application itself moves from `CREDIT_ISSUED` to `REVOKED`. Finally, `cash_assessment_cents` is zero when the certificate recovery covers the assessed total, and otherwise the excess of `assessed_total_cents` over `recovered_from_certificate_cents`.

Vacating — from `NOTICE_SENT` or from `APPEALED` — sets `resolved_at` and changes nothing financial. Settling — likewise from either state — requires a positive `settled_amount_cents` in the request (`ERR_INVALID_REQUEST` when it is missing or non-positive), sets `resolved_at`, records `settled_amount_cents` and `cash_assessment_cents` equal to the settled amount, and leaves the certificate and the program entirely untouched. A `settled_amount_cents` accompanying a `SUSTAINED` or `VACATE` outcome is ignored.

### 3.9. Credit Estimation, Cash-Flow Projection, and Multi-Jurisdiction Allocation

The credit pipeline is exposed as a computed read of an application, answering for a requested `variant` the figures `atl_qualified_cents`, `btl_qualified_cents`, `capped_total_qualified_cents`, the `applied_rate`, the resulting `credit_cents`, and a `meets_minimum` flag, with the requested `variant` echoed in the response; any other `variant` value is rejected with `ERR_INVALID_REQUEST`. The `PROVISIONAL` variant — the default — sources the system-qualified sums built by entry reviews. The `FINAL` variant sources the CPA-attested sums `attested_atl_cents` and `attested_btl_cents` and requires an audit package standing `ATTESTED` or `ACCEPTED`; without one the read is rejected with `ERR_AUDIT_NOT_ACCEPTED`. Identical inputs can yield a different credit — even a different rate tier — when the attested totals differ from the system sums. Both variants run the same pipeline: apply the above-the-line cap of §3.4 to reach the capped total; apply the minimum gate, under which a capped total below the program's `minimum_qualified_spend_cents` yields a credit of zero and a false `meets_minimum`; select the tier on the post-cap total, where a capped total of at least the program's `elevated_tier_threshold_cents` — boundary inclusive — earns `base_rate_elevated` and anything below it earns `base_rate_standard`; and compute the credit as the capped total multiplied by the selected rate, rounded half up to whole cents.

A second computed read projects the credit against the production schedule for a requested `variant` — `OPTIMISTIC` or `CONSERVATIVE`, echoed in the response, with any other value rejected with `ERR_INVALID_REQUEST`. The projection's `basis_credit_cents` is the application's `final_credit_cents` when an `ACCEPTED` audit package exists or a certificate has been issued, and `provisional_credit_cents` otherwise. Three `milestones` anchor to the production's `scheduled_wrap_date`, each reported as an object carrying the milestone's identifying name, its `date` as an ISO 8601 calendar date (`YYYY-MM-DD`), and its `amount_cents`. `PRODUCTION_WRAP` lands on the wrap date itself and carries forty percent of the basis, rounded half up to whole cents. `AUDIT_COMPLETE` lands ninety days after the wrap date and carries thirty percent of the basis, likewise rounded half up. `CREDIT_ISSUANCE` lands one hundred eighty days after the wrap date and carries the remainder — the basis minus the first two milestone amounts — which is never itself rounded, so the three amounts always sum exactly to the basis. Under `OPTIMISTIC`, the default, the milestones stand at those dates at full face value and `expected_net_proceeds_cents` equals the basis. Under `CONSERVATIVE` the credit is assumed sold on the transfer market: the net is the basis multiplied by the program's `transfer_price_floor_pct`, rounded half up to whole cents; the forty–thirty–remainder split is applied to that net; and every milestone date shifts thirty days later to reflect settlement lag.

When one production files across several jurisdictions, each application carries an `allocation_share_pct` describing its share of the sibling qualified spend. The sibling set is every application of the same production standing `APPROVED` or `CREDIT_ISSUED`. When the siblings' capped totals sum to zero, every share is zero. Otherwise each application's share is its own `capped_total_qualified_cents` multiplied by ten thousand, divided by the sibling sum, rounded half up to a whole number, and then divided by one hundred — a percentage carrying exactly two decimal places. Shares recompute on every application approval and on every qualified-spend recompute touching any application of the production, so a change in one jurisdiction reprices the shares in all of them. The structural guarantee that no invoice feeds two jurisdictions is the per-production uniqueness of `external_invoice_ref` described in §3.4.

## 4. Endpoint Definitions

Operations that create a new resource — registering a program, company, production, buyer, application, vendor, spend entry, audit package, transfer, or clawback case, and issuance, which creates the certificate — return `201 Created`. Operations that modify an existing resource, drive a state transition, or perform a computed read return `200 OK`. Request payloads, preconditions, and side effects for every endpoint are defined by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/jurisdiction-programs` | Create a jurisdiction incentive program (`DRAFT`, allocated zero, remaining equal to the annual cap) | FilmOfficeAdmin |
| GET | `/api/jurisdiction-programs` | List programs with pagination and optional filters | All roles |
| GET | `/api/jurisdiction-programs/{programId}` | Get a program | All roles |
| POST | `/api/jurisdiction-programs/{programId}/amend` | Amend program configuration (`DRAFT` or `OPEN` only); OCC-guarded | FilmOfficeAdmin |
| POST | `/api/jurisdiction-programs/{programId}/transition` | Program lifecycle transition per the JurisdictionProgram state machine | FilmOfficeAdmin |
| POST | `/api/production-companies` | Register a production company (self-registration; the response id becomes the caller's identity) | Producer |
| GET | `/api/production-companies/{companyId}` | Get a production company | All roles |
| POST | `/api/productions` | Create a production under a company the caller owns | Producer |
| GET | `/api/productions` | List productions with optional filters | All roles |
| GET | `/api/productions/{productionId}` | Get a production | All roles |
| POST | `/api/credit-buyers` | Register a credit buyer (self-registration; the response id becomes the caller's identity) | CreditBuyer |
| GET | `/api/credit-buyers/{buyerId}` | Get a credit buyer | All roles |
| POST | `/api/applications` | Create a `DRAFT` incentive application for a production to a program | Producer |
| GET | `/api/applications` | List applications with optional filters | All roles |
| GET | `/api/applications/{applicationId}` | Get an application | All roles |
| POST | `/api/applications/{applicationId}/submit` | Submit a `DRAFT` application; window checks use the logical clock, deadline boundary inclusive | Producer |
| POST | `/api/applications/{applicationId}/withdraw` | Withdraw a pre-approval application | Producer |
| POST | `/api/applications/{applicationId}/claim-review` | Reviewer claims a `SUBMITTED` application | FilmOfficeReviewer |
| POST | `/api/applications/{applicationId}/request-corrections` | Reviewer sends the application back for corrections | FilmOfficeReviewer |
| POST | `/api/applications/{applicationId}/resubmit` | Producer resubmits after corrections, cycling back to `UNDER_REVIEW` | Producer |
| POST | `/api/applications/{applicationId}/approve` | Approve an `UNDER_REVIEW` application; approver must differ from the claiming reviewer | FilmOfficeReviewer |
| POST | `/api/applications/{applicationId}/deny` | Deny an `UNDER_REVIEW` application; denier must differ from the claiming reviewer | FilmOfficeReviewer |
| GET | `/api/applications/{applicationId}/credit-estimate` | Computed read of the credit pipeline; `variant` `PROVISIONAL` (default) or `FINAL` | All roles |
| GET | `/api/applications/{applicationId}/cashflow-projection` | Computed read of the cash-flow projection; `variant` `OPTIMISTIC` (default) or `CONSERVATIVE` | All roles |
| POST | `/api/applications/{applicationId}/issue-credit` | Issue the tax credit certificate after an accepted audit; debits the program annual cap | FilmOfficeAdmin |
| POST | `/api/vendors` | Register a vendor on a production the caller owns (`UNVERIFIED`) | Producer |
| GET | `/api/vendors` | List vendors with optional filters | All roles |
| GET | `/api/vendors/{vendorId}` | Get a vendor | All roles |
| POST | `/api/vendors/{vendorId}/review-residency` | Reviewer verifies or rejects vendor residency; revoking `VERIFIED` fires the disqualification cascade | FilmOfficeReviewer |
| POST | `/api/spend-entries` | Record a spend entry (`PENDING_REVIEW`); an optional amendment supersedes its target | Producer |
| GET | `/api/spend-entries` | List spend entries with optional filters | All roles |
| GET | `/api/spend-entries/{entryId}` | Get a spend entry | All roles |
| POST | `/api/spend-entries/{entryId}/review` | Reviewer qualifies or disqualifies a spend entry; fires the totals recompute cascade | FilmOfficeReviewer |
| POST | `/api/audit-packages` | Engage a CPA audit package on an `APPROVED` application | CPAAuditor |
| GET | `/api/audit-packages` | List audit packages with optional filters (application-filtered list returns zero or one) | All roles |
| GET | `/api/audit-packages/{packageId}` | Get an audit package | All roles |
| POST | `/api/audit-packages/{packageId}/submit-draft` | CPA submits the draft audit and documentation package (from `ENGAGED` or `FIELDWORK`) | CPAAuditor |
| POST | `/api/audit-packages/{packageId}/raise-exceptions` | Reviewer raises exceptions on a submitted draft, sending it back to `FIELDWORK` | FilmOfficeReviewer |
| POST | `/api/audit-packages/{packageId}/attest` | CPA attests qualified-spend figures (`DRAFT_SUBMITTED` only) | CPAAuditor |
| POST | `/api/audit-packages/{packageId}/decision` | Reviewer accepts or rejects an `ATTESTED` package; decider must differ from the CPA | FilmOfficeReviewer |
| GET | `/api/certificates` | List certificates with optional filters (application-filtered list returns zero or one) | All roles |
| GET | `/api/certificates/{certificateId}` | Get a certificate | All roles |
| POST | `/api/certificates/{certificateId}/redeem` | Redeem credit with the state; redeeming the full remaining balance closes the certificate | Producer |
| POST | `/api/transfers` | Propose a credit sale (OCC-guarded on the certificate's version); increments the certificate's version | Producer |
| GET | `/api/transfers` | List transfers with optional filters | All roles |
| GET | `/api/transfers/{transferId}` | Get a transfer | All roles |
| POST | `/api/transfers/{transferId}/counter` | Counter-offer: the buyer counters when `PROPOSED`, the seller counter-counters when `COUNTERED` | Producer, CreditBuyer |
| POST | `/api/transfers/{transferId}/accept` | Accept the standing offer: the buyer accepts when `PROPOSED`, the seller accepts when `COUNTERED` | Producer, CreditBuyer |
| POST | `/api/transfers/{transferId}/settle` | Settle an `ACCEPTED` transfer: debits the certificate and auto-cancels oversized sibling proposals | FilmOfficeAdmin |
| POST | `/api/transfers/{transferId}/cancel` | Cancel a `PROPOSED` or `COUNTERED` transfer (seller cancels; buyer may withdraw its own counter-offer) | Producer, CreditBuyer |
| POST | `/api/clawback-cases` | Open a clawback case against a `CREDIT_ISSUED` application | FilmOfficeAdmin |
| GET | `/api/clawback-cases` | List clawback cases with optional filters | All roles |
| GET | `/api/clawback-cases/{caseId}` | Get a clawback case | All roles |
| POST | `/api/clawback-cases/{caseId}/send-notice` | Send the clawback notice; starts the appeal window | FilmOfficeAdmin |
| POST | `/api/clawback-cases/{caseId}/appeal` | Production company appeals within the appeal window | Producer |
| POST | `/api/clawback-cases/{caseId}/resolve` | Resolve a case: `SUSTAINED` (executes the clawback cascade), `VACATE`, or `SETTLE` | FilmOfficeAdmin |
| POST | `/api/_clock/set_current_utc` | Set the logical clock used by every deadline, window, and expiry check | FilmOfficeAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_APPLICATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_AUDIT_PACKAGE_EXISTS` | 409 Conflict |
| `ERR_CERTIFICATE_ALREADY_ISSUED` | 409 Conflict |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CERTIFICATE_VERSION` | 412 Precondition Failed |
| `ERR_VENDOR_RESIDENCY_NOT_VERIFIED` | 409 Conflict |
| `ERR_AUDIT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_AUDIT_PACKAGE_INCOMPLETE` | 409 Conflict |
| `ERR_SPEND_ENTRIES_PENDING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_WINDOW_NOT_YET_OPEN` | 409 Conflict |
| `ERR_APPLICATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_VERIFICATION_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_CERTIFICATE_EXPIRED` | 409 Conflict |
| `ERR_TRANSFER_EXPIRED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_NOTICE_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_SPEND_INVOICE` | 409 Conflict |
| `ERR_VENDOR_PRODUCTION_MISMATCH` | 409 Conflict |
| `ERR_AMENDMENT_TARGET_MISMATCH` | 409 Conflict |
| `ERR_MINIMUM_SPEND_NOT_MET` | 409 Conflict |
| `ERR_PROGRAM_CAP_EXHAUSTED` | 409 Conflict |
| `ERR_TRANSFER_PRICE_BELOW_FLOOR` | 409 Conflict |
| `ERR_AMOUNT_EXCEEDS_REMAINING` | 409 Conflict |
| `ERR_CLAWBACK_EXCEEDS_EXPOSURE` | 409 Conflict |
