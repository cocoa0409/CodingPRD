# ASL/CART Deaf-Interpreting & Scheduling API — Product Requirements Document

## 1. Introduction

Coordinating sign-language interpreters and real-time captioners for deaf and hard-of-hearing consumers is a logistics problem wrapped in a civil-rights mandate. Hospitals, courts, universities, and general businesses are legally obligated under the ADA to provide effective communication, and the quality of that obligation is measured in outcomes: did a qualified professional show up, on time, for the full booking, and was the encounter billed fairly for the time actually delivered. This document specifies an API that manages the full lifecycle of that coordination — from a requesting organization filing an interpreting request in one of three service modalities (on-site ASL interpreting, on-site CART captioning, or video remote interpreting), through certification-gated matching, dispatch, travel-aware service delivery, and per-hour billing, to quality adjudication and ADA compliance reporting.

The platform separates concerns across five operational roles so that no single actor controls a transaction end to end: coordinators file and verify, a dispatcher matches and confirms, interpreters serve their own assignments, a quality reviewer adjudicates complaints and grants credits, and a billing clerk settles invoices. Interpreters carry a dual quality score and a rolling no-show strike record that can automatically suspend them and cascade through their booked work. Requesting organizations carry a credit limit enforced at dispatch time against a live outstanding-balance aggregation. Billing supports a provisional cost estimate pinned at offer time and a final invoice computed from verified actuals, with a credit-memo waterfall that settles oldest debt first.

All temporal rules in this document — submission lead times, offer deadlines, check-in windows, no-show grace periods, verification deadlines, rolling strike windows — are evaluated against a single server-maintained logical clock, never against wall-clock time, so that every scheduled action is deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and invariants that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `PlatformAdmin`, `OrgRequester`, `Interpreter`, `QualityReviewer`, `BillingClerk`, and `Any`. A request missing either header, or naming a role outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The `Any` role is not an operational actor; it denotes that any authenticated declared role may perform read operations.

Two roles are entity-backed. When `X-User-Role` is `OrgRequester`, `X-User-ID` is the `id` of the acting RequestingOrg; ownership checks on any resource that references a RequestingOrg compare the resource's foreign-key field (for example `org_id` on a request, complaint, or credit memo, or the owning organization reached through an assignment, encounter, or invoice) to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `Interpreter`, `X-User-ID` is the `id` of the acting Interpreter; ownership checks compare the resource's `interpreter_id` (on an assignment) or the interpreter identifier in the path (on self-scoped certification and availability operations) to `X-User-ID`, again failing with `ERR_FORBIDDEN_OWNERSHIP`.

The remaining roles are opaque. When `X-User-Role` is `PlatformAdmin`, `QualityReviewer`, `BillingClerk`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. Segregation of duties is deliberate: an `OrgRequester` files requests, disputes, and complaints but cannot settle them; a `QualityReviewer` adjudicates complaints and issues credits but cannot file complaints or settle invoices; a `BillingClerk` generates, issues, voids, and settles invoices and voids credits but cannot adjudicate complaints or dispatch assignments; a `PlatformAdmin` operates the platform (rate cards, interpreter onboarding, dispatch, no-show marking, strikes, the clock, reports) but never acts as a requester, interpreter, reviewer, or clerk.

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

---

### 2.3. Pagination

List endpoints accept two pagination query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties keeping creation (insertion) order. The `meta` object of a list response always carries the pagination fields `limit`, `offset`, `total_count` (the size of the filtered result set before pagination), and `has_more`. Individual list endpoints additionally accept the filter query parameters named alongside their workflows in §3 — for example `status` on the per-org complaint, credit-memo, strike, and offer listings; `org_id`, `modality`, and `ada_context` on the request listing; `request_id`, `interpreter_id`, and `rate_card_id` on the assignment listing; and `org_id`, `encounter_id`, `issue_status`, `payment_status`, and `dispute_status` on the invoice listing.

### 2.4. The Logical Clock and Deferred Sweeps

The server maintains a logical clock against which every time comparison in this document is evaluated. Before it has ever been set, the clock reads exactly 2026-05-01T00:00:00Z; the server never falls back to wall-clock time. A `PlatformAdmin` sets the clock through an admin-only test-driving capability whose payload carries a `to_iso8601` instant, applied verbatim — the clock may be moved to any instant, earlier or later, with no monotonicity check. Setting the clock runs the deferred sweep, in this fixed order: first, outstanding offers whose `response_deadline` has been reached expire (their requests fall back to re-matching or go unfilled); second, encounters whose `verify_deadline` has been reached are auto-verified by the system (which may bubble a request from `IN_PROGRESS` to `COMPLETED`); third, requests still `MATCHING` or `OFFERED` at or past their `scheduled_start` are marked `UNFILLED` (an outstanding offer becoming `EXPIRED`). The capability responds with the new `current_utc` plus three counters: `expired_offer_count`, `auto_verified_encounter_count`, and `unfilled_request_count`. Independently of the sweep, an offer that has reached its `response_deadline` may also be expired lazily the next time it is accessed.

### 2.5. Common Resource Properties and Identity

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on any mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation, anchoring the optimistic-concurrency rules of §2.7. One entity is deliberately lighter: a StrikeRecord carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, because a strike is created once and thereafter only its `status` moves to a terminal value.

### 2.6. Money, Precision, and the Round-Per-Line Rule

All monetary quantities are integer cents — rates, fees, subtotals, credits, payments, and balances alike. Every computed cent amount is rounded half-up to a whole cent, and rounding is applied per component before any summation: each invoice line is rounded to integer cents first and the subtotal is the sum of those already-rounded line amounts, never a sum of unrounded amounts rounded once at the end. Sum-then-round of the same inputs can differ by cents; this platform pins round-per-line-then-sum. Two reporting ratios deviate from integer cents by design: the fulfillment rate is rounded half-up to four decimal places, and the average response time is rounded half-up to two decimal places. Time quantities are whole minutes obtained by rounding elapsed seconds up to a whole minute unless a rule says otherwise.

### 2.7. Optimistic Concurrency Control

Two write operations require the caller to present the version it last observed, and reject the write when that view is stale. Creating an offer against a request requires the non-optional `expected_request_version` field carrying the request `version` the client last read; if the request's current `version` has advanced past it — for example because a prior offer creation superseded an outstanding offer and bumped the version — the create is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412), so the client cannot dispatch against a matching state it has not observed. Creating a credit memo requires the non-optional `expected_org_version` field carrying the organization `version` the client last read; a mismatch with the organization's current `version` is rejected with `ERR_STALE_ORG_VERSION` (HTTP 412), because memo creation waterfall-applies against the outstanding-balance view the client used and bumps the organization's version. No endpoint outside these two takes a version field.

### 2.8. Nested Resource Retrieval and Existence Checking

Path parameters are validated strictly left to right: a request addressed at a certification or availability window under an interpreter first confirms the interpreter exists, then the `certId` or `windowId` beneath it, and the first missing identifier short-circuits the call. Each missing resource maps to a dedicated not-found error: `ERR_ORG_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AVAILABILITY_WINDOW_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_CREDIT_MEMO_NOT_FOUND`, `ERR_STRIKE_NOT_FOUND`, and `ERR_REPORT_NOT_FOUND`, all HTTP 404. The same existence discipline applies to identifiers referenced in request bodies — the interpreter named on an offer, the assignment named at invoice generation or complaint filing, the organization named on a memo or report, the invoice targeted by a dispute, the complaint named on a manual memo when supplied, the assignment optionally named on a manual strike, and the strike targeted by a rescind. A generic `{id}` path parameter always denotes the addressed resource's own UUID.

### 2.9. Hierarchical Consistency: Bubble-Ups and Cascades

The request sits at the top of a shallow hierarchy — request, assignment, encounter, invoice — and state alignment is maintained in both directions. Child events bubble upward: a confirmed assignment moves its request to `CONFIRMED`; a check-in moves it to `IN_PROGRESS`; a verified encounter on a completed assignment moves it to `COMPLETED`; an invoice reaching fully-paid moves it to `CLOSED`. Downward cascades resolve dependent work when a parent or sibling fails: cancelling a request cancels its outstanding assignment; suspending an interpreter cancels every non-terminal assignment they hold and re-matches the affected requests. Every such reconciliation independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`, so a client watching versions can observe each step of a cascade.

### 2.10. Validation Priority Order

When several validations could reject the same request, they are evaluated in a fixed twelve-tier order, and the earliest failing tier determines the error returned. First, the user-context headers are checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, request-schema integrity: required fields present, types valid, enum values in their declared domains, unknown fields rejected, numeric ranges enforced (amounts positive, claims non-negative, end after start), and conditionally-required fields honored — failures surface as `ERR_INVALID_REQUEST` or `ERR_ONSITE_ADDRESS_REQUIRED` (HTTP 400). Third, role permission (`ERR_UNAUTHORIZED_ROLE`). Fourth, entity-backed ownership (`ERR_FORBIDDEN_OWNERSHIP`). Fifth, existence of every path- and body-referenced identifier, left to right (the not-found catalog of §2.8); where ownership is derived from a fetched resource (for example the owning org reached through a request, encounter, assignment, invoice, or complaint in the path), that resource's existence is necessarily confirmed before the ownership comparison can run. Sixth, optimistic-concurrency freshness (`ERR_STALE_REQUEST_VERSION`, `ERR_STALE_ORG_VERSION`). Seventh, parent-entity posture: the organization must be `ACTIVE` for org write actions (`ERR_ORG_NOT_ACTIVE`) and the interpreter `ACTIVE` where required (`ERR_INTERPRETER_NOT_ACTIVE`). Eighth, resource from-state preconditions per the state machines — the `ERR_REQUEST_NOT_*`, `ERR_ASSIGNMENT_NOT_*`, `ERR_ENCOUNTER_*`, `ERR_INVOICE_NOT_*`, `ERR_COMPLAINT_*`, `ERR_CREDIT_MEMO_NOT_OPEN`, `ERR_STRIKE_NOT_ACTIVE`, `ERR_RATE_CARD_ALREADY_RETIRED`, and `ERR_ACTIVE_STRIKES_AT_LIMIT` family (HTTP 409). Ninth, the ADA credential-and-match gate on dispatch, which has its own fixed sub-order — modality offered first, then VRI platform certification, then credential sufficiency, then quality threshold (`ERR_MODALITY_NOT_OFFERED`, `ERR_VRI_CERTIFICATION_REQUIRED`, `ERR_CREDENTIAL_INSUFFICIENT`, `ERR_QUALITY_BELOW_THRESHOLD`; HTTP 422). Tenth, temporal rules (`ERR_INVALID_SCHEDULE`, `ERR_CHECK_IN_WINDOW_VIOLATION`, `ERR_NO_SHOW_TOO_EARLY`; HTTP 422). Eleventh, structural constraints (offer-attempt cap, availability coverage and window overlap, double-booking, VRI capacity, one-invoice-per-assignment, verification-before-billing; HTTP 409). Twelfth and last, the fiscal gates (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_PAYMENT_EXCEEDS_AMOUNT_DUE`) — money is checked only after every safety, temporal, and structural rule has passed.

## 3. Business Logic & Workflows

### 3.1. Requesting Organizations and Their Fiscal Posture

A `PlatformAdmin` onboards a requesting organization by supplying its display `name`, its `org_type` — one of `MEDICAL`, `LEGAL`, `EDUCATION`, or `GENERAL`, declaring the primary ADA service context — and its `credit_limit_cents` — a non-negative integer of cents — the maximum outstanding exposure the platform will tolerate for the org. A new organization starts `ACTIVE` with `version` 1. The same administrator may later suspend the organization (a credit hold that flips `status` to `SUSPENDED`) and reinstate it, each transition bumping the org's `version`; suspending an organization that is not `ACTIVE`, or reinstating one that is not `SUSPENDED`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Suspension is a hard gate on org-initiated writes: while an organization is `SUSPENDED`, its coordinators cannot submit or cancel requests, verify encounters, dispute invoices, or file complaints — each attempt is rejected with `ERR_ORG_NOT_ACTIVE` (HTTP 409). Reads remain open to all roles.

An organization's `outstanding_balance_cents` is never stored. It is recomputed on every read as the sum of `amount_due_cents` over that organization's invoices whose `issue_status` is `ISSUED` and whose `payment_status` is not `PAID`. This live figure feeds the fiscal gate evaluated at dispatch time: when an offer is created, and again when an assignment is confirmed, the platform requires the org's outstanding balance plus the assignment's `estimated_cost_cents` to be no more than `credit_limit_cents`. Equality is allowed; a sum strictly greater than the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

### 3.2. Interpreter Onboarding, Credentialing, and Availability

Interpreters enter the platform through a `PlatformAdmin`-created profile carrying a `full_name`, the non-empty `modalities_offered` subset of `ASL_ONSITE`, `CART_ONSITE`, and `VRI` the interpreter will service, a `home_zip` used for travel context, and an optional `vri_platform_certified` flag that defaults to false. A new interpreter starts `PENDING_ONBOARD` with both quality scores at 100 and an `active_strike_count` of zero.

Credentials are filed as certifications under the interpreter, either by a `PlatformAdmin` or by the interpreter acting on their own profile — for the self-service path the interpreter in the path must match `X-User-ID`. Each certification records its `credential` (one of `RID_NIC`, `RID_CI_CT`, `STATE_QA`, `CART_CRR`, `NAD_V`, or `LEGAL_SCL`), its `level` (`SCREENED`, `CERTIFIED`, or `SPECIALIST`, ranked in that ascending order), the `issued_on` date, and the `expires_on` date. A certification is created with `verified` false and only a `PlatformAdmin` verification flips `verified` to true; the path-scoped `interpreter_id` ties each record to its owner. Verifying an already-verified certification is allowed and simply refreshes its `updated_at` and `version`. Activation — moving the interpreter from `PENDING_ONBOARD` to `ACTIVE` — requires at least one verified certification and is otherwise rejected with `ERR_CREDENTIAL_INSUFFICIENT`; activating an interpreter not in `PENDING_ONBOARD` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

An interpreter declares when they can work by creating availability windows on their own profile, each defined by a `start_at`, an `end_at` that must be strictly later than the start, and the non-empty `modalities` subset coverable within the window. Windows are half-open intervals: they cover from `start_at` up to but not including `end_at`. A new window that overlaps any existing window of the same interpreter is rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP` (HTTP 409), though windows whose endpoints merely touch are allowed. An interpreter may delete one of their own windows; a deleted window no longer counts for overlap checks or coverage checks.

Suspension moves an interpreter from `ACTIVE` to `SUSPENDED` and arrives in two ways: a `PlatformAdmin` suspends manually, or the system auto-suspends the moment the rolling strike count reaches three (§3.6). Either way, the cascade is identical — every assignment the interpreter holds in `OFFERED`, `ACCEPTED`, or `CONFIRMED` status is cancelled by the system with no fee, and each affected request returns to `MATCHING` if it still has offer attempts remaining, or falls to `UNFILLED` once attempts are exhausted. Reinstatement returns a suspended interpreter to `ACTIVE` only while their `active_strike_count` is below three; otherwise the attempt is rejected with `ERR_ACTIVE_STRIKES_AT_LIMIT`. Manual suspension of an interpreter who is not `ACTIVE`, and reinstatement of one who is not `SUSPENDED`, are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Two quality figures travel with every interpreter profile and are recomputed on read: the `quality_score`, which counts only substantiated complaints, and the `quality_score_provisional`, which assumes the worst on pending complaints. Their exact aggregation lives with the complaint workflow in §3.9; what matters here is that the dispatch gate in §3.4 consults the final `quality_score`, and that both figures fall as penalties land.

### 3.3. Request Submission and Scheduling Rules

Work enters the system when an `OrgRequester` files an interpreting request. The payload names the filing organization via `org_id`, which must equal the caller's `X-User-ID`; identifies the deaf or hard-of-hearing `consumer_name`; selects a `modality` of `ASL_ONSITE`, `CART_ONSITE`, or `VRI`; and fixes the engagement with `scheduled_start` and `scheduled_end`. The `ada_context` is optional and defaults to `GENERAL`; when supplied it must be one of `MEDICAL`, `LEGAL`, `EDUCATION`, or `GENERAL`. For the two on-site modalities an `onsite_address` is required — omitting it is rejected with `ERR_ONSITE_ADDRESS_REQUIRED` (HTTP 400) — while a VRI booking does not require one, and an address supplied anyway is accepted and stored. An optional `estimated_mileage` — a non-negative number, fractional miles allowed — defaulting to zero, records expected round-trip miles and feeds only the provisional cost estimate.

From the context the platform derives the credential bar: a `LEGAL` request demands a `SPECIALIST`, `MEDICAL` and `EDUCATION` demand `CERTIFIED`, and `GENERAL` demands `SCREENED`. This derived `required_credential_level` is stored on the request and drives both rate-card selection and interpreter eligibility at dispatch. A new request is a `DRAFT` at `version` 1, with `offer_attempt_count` at zero and `cancellation_fee_cents`, `cancelled_at`, and `closed_at` all null.

Submission moves a request from `DRAFT` to `MATCHING`. The submitter must own the request, the organization must be `ACTIVE` (§3.1), and the schedule must be sane: `scheduled_end` strictly after `scheduled_start`, and `scheduled_start` at least two hours in the future at submit time. A bad schedule is rejected with `ERR_INVALID_SCHEDULE` (HTTP 422); submitting anything other than a `DRAFT` is rejected with `ERR_REQUEST_NOT_DRAFT`. A successful submission increments the request's `version`. Coordinators browse their pipeline through the request listing, which filters by `org_id`, `status`, `modality`, and `ada_context` in addition to the standard pagination parameters.

A request's `status` walks the full lifecycle — `DRAFT`, `MATCHING`, `OFFERED`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, and the terminal `CANCELLED`, `UNFILLED`, and `CLOSED` — through the transitions narrated in §3.4 through §3.8.

### 3.4. Rate Card Selection, Offer Dispatch, and the Pinned Snapshot

Pricing lives on rate cards, one row per combination of `modality`, `ada_context`, and `credential_level`, created by a `PlatformAdmin`. A card fixes the `hourly_rate_cents` labor rate, the `minimum_billable_minutes` floor per encounter (two hours is typical on-site; thirty minutes for VRI), the `travel_rate_cents_per_hour` and `mileage_rate_cents_per_mile` reimbursements (both zero on VRI cards), the `vri_platform_fee_cents_per_min` platform charge (zero on on-site cards), the two cancellation-notice windows `cancel_full_refund_notice_hours` and `cancel_partial_notice_hours` with the `late_cancel_fee_pct` fraction between them (a number between 0 and 1 inclusive), and an `effective_from` date before which the card is not selectable. Cards are born `ACTIVE`; retiring one flips it to `RETIRED` (re-retiring is rejected with `ERR_RATE_CARD_ALREADY_RETIRED`), excludes it from all future selection, and leaves every snapshot already pinned on an assignment untouched.

Dispatch is the act of creating an offer against a request in `MATCHING` or `OFFERED` — anything else is rejected with `ERR_REQUEST_NOT_OFFERABLE`. When a still-outstanding `OFFERED` assignment exists, creating the new offer legitimately supersedes it: the old offer becomes `CANCELLED` by the system with no fee, and the request's `version` advances. Because that supersede moves the version under the client's feet, offer creation carries the OCC contract of §2.7: `expected_request_version` must match the request's current `version`, or the create is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412). Each request tolerates at most three offer attempts; a successful offer increments `offer_attempt_count` by one, and an attempt made when the count has already reached three is rejected with `ERR_MAX_OFFER_ATTEMPTS_REACHED`.

The payload names the candidate by `interpreter_id`. Eligibility is then enforced in the fixed sub-order of §2.10's ninth tier: the interpreter must be `ACTIVE` (else `ERR_INTERPRETER_NOT_ACTIVE`); the request's modality must appear in the interpreter's `modalities_offered` (else `ERR_MODALITY_NOT_OFFERED`); a VRI request additionally requires `vri_platform_certified` to be true (else `ERR_VRI_CERTIFICATION_REQUIRED`); the interpreter must hold a verified certification whose `level` is at least the request's `required_credential_level` and whose `expires_on` falls on or after the `scheduled_start` (else `ERR_CREDENTIAL_INSUFFICIENT`); and the interpreter's final `quality_score` must be at least 40 (else `ERR_QUALITY_BELOW_THRESHOLD`). Coverage comes next: the interpreter's availability windows whose `modalities` include the request modality are merged as half-open intervals, and their union must fully cover the span from `scheduled_start` up to but not including `scheduled_end` — a window ending exactly at the scheduled start does not help, while one ending exactly at the scheduled end does cover the tail. Any gap rejects the offer with `ERR_NO_AVAILABILITY_COVERAGE` (HTTP 422).

With eligibility established, the platform selects the rate card: among `ACTIVE` cards matching the request's modality, `ada_context`, and required credential level whose `effective_from` is not later than the current logical time, the card with the latest `effective_from` wins, ties break toward the earliest `created_at` (further ties toward the earliest-created card), and the card `id` is never consulted. When no card matches, the offer fails with `ERR_RATE_CARD_NOT_FOUND` (HTTP 404). The winner is pinned onto the new assignment as an audit-proof snapshot: `rate_card_id` and the `rate_card_version` at pin time, plus `pinned_hourly_rate_cents`, `pinned_minimum_billable_minutes`, `pinned_travel_rate_cents_per_hour`, `pinned_mileage_rate_cents_per_mile`, `pinned_vri_platform_fee_cents_per_min`, `pinned_cancel_full_refund_notice_hours`, `pinned_cancel_partial_notice_hours`, and `pinned_late_cancel_fee_pct`. Later edits or retirement of the card cannot move a pinned assignment.

The same moment computes the provisional `estimated_cost_cents`. The scheduled duration in minutes — the gap between `scheduled_end` and `scheduled_start`, rounded up to a whole minute — is compared against `pinned_minimum_billable_minutes`, and the larger of the two is the estimated billable time. The labor estimate multiplies that billable time by `pinned_hourly_rate_cents` per hour and rounds half-up to whole cents. The travel estimate is zero for VRI and otherwise a flat sixty estimated travel minutes — exactly one hour at the pinned travel rate, rounded half-up. The mileage estimate is zero for VRI and otherwise multiplies the pinned per-mile rate by the lesser of the request's `estimated_mileage` and the 200-mile cap, rounded half-up. The platform-fee estimate applies only to VRI and multiplies the scheduled minutes by the pinned per-minute platform fee. The estimate is the sum of those four already-rounded components. Only after all of this does the fiscal gate of §3.1 run, rejecting with `ERR_CREDIT_LIMIT_EXCEEDED` when the org's outstanding balance plus this estimate exceeds its credit limit.

A successful dispatch creates the assignment in `OFFERED` with its `request_id`, `interpreter_id`, an `offered_at` stamp at the current logical time, and a `response_deadline` set to the earlier of the scheduled start and twenty-four hours after the offer; the request moves to `OFFERED` (or stays there on a supersede) with its `version` incremented. Dispatchers and coordinators can review a request's offer history through the per-request offers listing, which supports the `status` filter alongside pagination.

### 3.5. Assignment Progression: Acceptance Through Service Delivery

An assignment's `status` walks `OFFERED`, `ACCEPTED`, `CONFIRMED`, `EN_ROUTE`, `ON_SITE`, and `COMPLETED` on the happy path, with `DECLINED`, `EXPIRED`, `CANCELLED`, and `NO_SHOW` as the terminal exits. Every interpreter action on an assignment requires self-ownership: the assignment's `interpreter_id` must equal the caller's `X-User-ID`, failing which the call is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

Acceptance moves an offer to `ACCEPTED` and stamps `accepted_at`. The assignment must still be `OFFERED` (else `ERR_ASSIGNMENT_NOT_OFFERED`), the interpreter must be `ACTIVE` (else `ERR_INTERPRETER_NOT_ACTIVE`), and the logical time must still be earlier than the `response_deadline` — an accept arriving at or after the deadline finds the offer auto-expired and is likewise rejected with `ERR_ASSIGNMENT_NOT_OFFERED`. Declining moves the offer to `DECLINED`; expiry — by clock sweep or lazily on access once the deadline has passed — moves it to `EXPIRED`. Both endings cascade identically to the request: back to `MATCHING` while `offer_attempt_count` remains below three, or to `UNFILLED` once three attempts have been spent.

Confirmation is the dispatcher's second gate, moving an `ACCEPTED` assignment to `CONFIRMED`. Anything other than `ACCEPTED` is rejected with `ERR_ASSIGNMENT_NOT_ACCEPTED`; the interpreter must still be `ACTIVE`. Two structural checks follow. The buffered double-booking check expands every other `CONFIRMED`, `EN_ROUTE`, or `ON_SITE` assignment of the same interpreter by a thirty-minute travel buffer on each side and rejects the confirm with `ERR_INTERPRETER_DOUBLE_BOOKED` when the new assignment's buffered interval starts before another's buffered interval ends and ends after that other's buffered start — the buffered intervals are half-open, so a new assignment starting exactly thirty minutes after another's scheduled end is allowed. For VRI only, the aggregate capacity check counts every VRI assignment platform-wide in `CONFIRMED`, `EN_ROUTE`, or `ON_SITE` whose scheduled span overlaps the new one (half-open overlap): three overlapping sessions are allowed, and confirming a fourth is rejected with `ERR_VRI_CAPACITY_EXCEEDED`. Last, the fiscal gate of §3.1 re-runs against the pinned `estimated_cost_cents`. A successful confirm bubbles the request from `OFFERED` to `CONFIRMED`.

From `CONFIRMED`, on-site work begins with departure: the interpreter departs, moving to `EN_ROUTE`. Departure exists only for the on-site modalities — a VRI assignment has nowhere to drive to, and attempting to depart one is rejected with `ERR_INVALID_REQUEST`; an assignment not in `CONFIRMED` is rejected with `ERR_ASSIGNMENT_NOT_CONFIRMED`. Arrival is check-in: an on-site interpreter checks in from `EN_ROUTE`, while a VRI interpreter joins directly from `CONFIRMED`. Check-in is accepted only within the window that opens thirty minutes before `scheduled_start` and closes at `scheduled_end` — both bounds inclusive, so a check-in exactly at either endpoint succeeds; outside it, `ERR_CHECK_IN_WINDOW_VIOLATION` (HTTP 422) — and from any other status, `ERR_ASSIGNMENT_NOT_CONFIRMED`. Check-in creates the encounter, exactly one per assignment: stamped with its `assignment_id`, an `actual_start` at the current logical time, and `modality_delivered` equal to the request's modality; `actual_end`, `actual_minutes`, `billable_minutes`, and `verify_deadline` stay null while the encounter is live, `verified` is false, and `verified_by` is null. The request bubbles to `IN_PROGRESS`.

Check-out ends service, moving the assignment from `ON_SITE` to `COMPLETED` (any other status draws `ERR_ASSIGNMENT_NOT_ON_SITE`). Here the interpreter may attach travel claims: `travel_minutes_claimed` for round-trip travel time (a non-negative integer) and `mileage_claimed` for round-trip miles (a non-negative number, fractional miles allowed), each optional, each zero or more, each defaulting to zero. Check-out stamps the encounter's `actual_end`, computes `actual_minutes` as the elapsed time from `actual_start` rounded up to whole minutes, sets `billable_minutes` to the greater of `actual_minutes` and the assignment's `pinned_minimum_billable_minutes`, and arms the `verify_deadline` seventy-two hours after `actual_end`. The request deliberately remains `IN_PROGRESS` — it cannot complete until the encounter is verified. The assignment listing supports filters by `request_id`, `interpreter_id`, `rate_card_id`, and `status`; the encounter and invoices belonging to an assignment are reachable through their own reverse lookups.

### 3.6. Cancellation, No-Show, and the Strike Cascade

Cancellation has two entry points that share one fee engine. An `OrgRequester` (owning org, `ACTIVE`) or a `PlatformAdmin` may cancel the request itself while it stands in `DRAFT`, `MATCHING`, `OFFERED`, or `CONFIRMED` — any other state is rejected with `ERR_REQUEST_NOT_CANCELLABLE`. Alternatively, the same two roles may cancel the assignment directly while it stands in `ACCEPTED`, `CONFIRMED`, or `EN_ROUTE`, an `OrgRequester` again limited to their own organization's work — any other assignment state is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Both endpoints accept an optional `reason`.

The tiered fee is computed whenever the cancelled assignment stood in `ACCEPTED`, `CONFIRMED`, or `EN_ROUTE`, regardless of which entry point was used, and is absent when the assignment was still `OFFERED`. Notice is measured in exact seconds between the cancellation moment and the `scheduled_start`; the assignment records it in hours as `cancel_notice_hours`, and the actor is recorded in `cancelled_by` as one of `REQUESTER`, `PLATFORM`, `INTERPRETER`, or `SYSTEM` — requester- and platform-initiated cancels take the first two values, while system-driven cancellations (the supersede of §3.4 and the suspension cascade of §3.2) take the last. The minimum charge is the assignment's `pinned_minimum_billable_minutes` at `pinned_hourly_rate_cents`, rounded half-up to cents. Notice of at least `pinned_cancel_full_refund_notice_hours` — the boundary is inclusive — means a fee of zero. Notice shorter than that but at least `pinned_cancel_partial_notice_hours` yields a fee of `pinned_late_cancel_fee_pct` times the minimum charge, rounded half-up. Notice shorter than the partial window yields the full minimum charge. The assignment's `cancellation_fee_cents` carries the result; on the request, `cancellation_fee_cents` is zero for fee-free cancellations, copies the assignment's fee when one applies, and is null otherwise, with `cancelled_at` stamped whenever the request itself transitions to `CANCELLED`.

The cascades differ by actor and state. Cancelling a `DRAFT` or `MATCHING` request is fee-free and final. Cancelling an `OFFERED` request withdraws the outstanding offer — the pending assignment becomes `CANCELLED` with no fee, its `cancelled_by` recording the actor (`REQUESTER` or `PLATFORM`). Cancelling a `CONFIRMED` request cancels its `CONFIRMED` or `EN_ROUTE` assignment with the tiered fee, and when that fee is greater than zero the platform creates a fee-only invoice in `DRAFT` whose single line is the fee and whose `encounter_id` is null. Cancelling an assignment directly, a requester-side cancellation additionally cancels the request on the same terms, while a platform-side cancellation returns the request to `MATCHING` when `offer_attempt_count` is still below three, or to `UNFILLED` once attempts are exhausted. Every request transition into or out of these states increments the request's `version`.

No-show is the platform's remedy when a confirmed interpreter simply never arrives. A `PlatformAdmin` marks no-show on an assignment in `CONFIRMED` or `EN_ROUTE` (else `ERR_ASSIGNMENT_NOT_CONFIRMED`), but only once the logical time has reached fifteen minutes past the `scheduled_start` — earlier attempts are rejected with `ERR_NO_SHOW_TOO_EARLY`. Marking stamps `no_show_marked_at`, moves the assignment to `NO_SHOW`, and fires a four-link cascade. Link one: a strike is created for the interpreter with `occurred_at` set to the assignment's scheduled start and status `ACTIVE`. Link two: the interpreter's `active_strike_count` is recomputed as the number of their `ACTIVE` strikes whose `occurred_at` falls on or after the logical time minus 365 days — the window edge is inclusive, so a strike exactly 365 days old still counts. Link three: when that count reaches three or more and the interpreter is `ACTIVE`, the interpreter is auto-suspended per §3.2. Link four: the suspension cascade cancels the interpreter's other non-terminal assignments and re-matches their requests, while the no-showed request itself returns to `MATCHING` if attempts remain, else falls to `UNFILLED`.

Strikes also exist independently of any assignment: a `PlatformAdmin` may document an external no-show by creating a strike with an `interpreter_id`, an `occurred_at` that must not lie in the future (else `ERR_INVALID_REQUEST`), and an optional `assignment_id` left null for external events. The same recompute and auto-suspension rules apply. A strike may later be rescinded — moving it from `ACTIVE` to `RESCINDED` and stamping `rescinded_at` — which recomputes the rolling count downward when the strike was inside the window; attempting to rescind a strike that is not `ACTIVE` is rejected with `ERR_STRIKE_NOT_ACTIVE`. Rescinding never reinstates by itself: a suspended interpreter stays `SUSPENDED` until the explicit reinstatement of §3.2.

### 3.7. Encounter Verification and Invoice Composition

Verification is the requester's acknowledgment that service happened as recorded. The owning `OrgRequester` verifies a live encounter, which sets `verified` true and `verified_by` to `ORG`; verifying an already-verified encounter is rejected with `ERR_ENCOUNTER_ALREADY_VERIFIED`. The requester may attach corrected times — `corrected_start` and `corrected_end` must be supplied together or both omitted (supplying only one is rejected with `ERR_INVALID_REQUEST`, HTTP 400), the `corrected_start` strictly before the `corrected_end`, with the corrected end not in the future — in which case `actual_minutes` and `billable_minutes` are recomputed from the corrections under the same rounding and minimum-minute rules as check-out. Verification bubbles the request from `IN_PROGRESS` to `COMPLETED` when the assignment already stands `COMPLETED` (the usual case, service having been checked out); verifying an encounter whose assignment is still `ON_SITE` marks the encounter verified without moving the request. When the requester stays silent, the clock sweep auto-verifies at or after the `verify_deadline` with `verified_by` `SYSTEM`, producing the same bubble. Either way, the request cannot reach `COMPLETED` — and the encounter cannot be billed — until verification has happened.

Billing begins when a `BillingClerk` generates an invoice for a completed assignment. Generation requires the assignment to be `COMPLETED` (otherwise `ERR_INVALID_REQUEST`) and its encounter verified (otherwise `ERR_ENCOUNTER_NOT_VERIFIED`), and each assignment yields exactly one invoice — a second generation is rejected with `ERR_INVOICE_ALREADY_EXISTS`. The invoice is born with `issue_status` `DRAFT`, `dispute_status` `NONE`, and `payment_status` `UNPAID`, its `org_id` taken from the request and its `encounter_id` linking the source encounter (null only on the cancellation-fee-only invoices of §3.6).

An invoice's `line_items` array is the itemized bill, each entry a `kind`, a `quantity`, a `unit_rate_cents`, and an `amount_cents`, with `kind` drawn from `LABOR`, `TRAVEL_TIME`, `MILEAGE`, `PLATFORM_FEE`, `CANCELLATION_FEE`, and `ADJUSTMENT`. The `LABOR` line is always present: its quantity is the encounter's `billable_minutes` and its amount is that time at the pinned hourly rate, rounded half-up. The `TRAVEL_TIME` and `MILEAGE` lines reimburse the check-out claims under their caps — travel time capped at 240 minutes and mileage at 200 miles, both forced to zero for VRI — each rounded half-up per line. The `PLATFORM_FEE` line exists only for VRI and is computed on the encounter's `actual_minutes` at the pinned per-minute fee — actual minutes, never the minimum-inflated billable figure. Any line whose amount computes to zero is omitted from the array (the `LABOR` line excepted; a `PLATFORM_FEE` line appears whenever its amount is positive). A cancellation-fee-only invoice carries a single `CANCELLATION_FEE` line equal to the assignment's `cancellation_fee_cents`, with `quantity` 1 and `unit_rate_cents` equal to the fee. The `subtotal_cents` is the sum of the per-line rounded amounts — round per line, then sum, per §2.6. Finally, `amount_due_cents` is the greater of zero and the subtotal minus `credits_applied_cents` minus `payments_applied_cents`; that invariant must hold at all times, and both accumulator fields start at zero with `issued_at` null until issuance.

### 3.8. Settlement, Disputes, and the Credit Waterfall

Issuance is the clerk's first act on a generated invoice: issuing requires `issue_status` `DRAFT` (else `ERR_INVOICE_NOT_DRAFT`), flips it to `ISSUED`, and stamps `issued_at`. From that instant the invoice enters the org's outstanding-balance aggregation of §3.1 and becomes eligible for the credit waterfall. Voiding walks the other direction: a `DRAFT` invoice voids cleanly, while an `ISSUED` invoice may be voided only when nothing has been paid against it and no dispute is open — `payments_applied_cents` must be zero and `dispute_status` must not be `OPEN`, else `ERR_INVALID_REQUEST`; voiding an already-`VOID` invoice is likewise rejected with `ERR_INVALID_REQUEST`, and acting on a non-`ISSUED` invoice where issuance is required is rejected with `ERR_INVOICE_NOT_ISSUED`. Voiding an issued invoice reverses every credit-memo application against it, returning each applied amount to its memo's `remaining_cents` and reopening any memo it had exhausted; the voided invoice's own `amount_due_cents` and `payment_status` are recomputed from the remaining accumulators, and any request already bubbled to `CLOSED` is not reopened.

Disputes are the requester's channel. The owning `OrgRequester` disputes an `ISSUED` invoice, moving `dispute_status` from `NONE` to `OPEN` and recording the payload's `reason` into `dispute_reason`; the invoice must be `ISSUED` (else `ERR_INVOICE_NOT_ISSUED`), and a dispute may only start from `NONE` — re-disputing an already-resolved or open invoice is rejected with `ERR_INVALID_REQUEST`. Resolution belongs to the `BillingClerk` and requires an `OPEN` dispute (else `ERR_INVOICE_NOT_DISPUTED`). The payload's `outcome` selects the ending: `UPHELD` closes the dispute as `RESOLVED_UPHELD` with no further effect, while `OVERTURNED` closes it as `RESOLVED_OVERTURNED` and requires a positive `adjustment_cents` no greater than the invoice's `amount_due_cents` plus its `credits_applied_cents` (else `ERR_INVALID_REQUEST`). An overturn appends an `ADJUSTMENT` line with `quantity` 1 whose `unit_rate_cents` and `amount_cents` are the negative of the adjustment, recomputes `subtotal_cents` under the round-per-line rule, and recomputes `amount_due_cents`; if the due falls to zero the invoice becomes `PAID`, which may bubble its request from `COMPLETED` to `CLOSED`.

Payments settle the balance directly. A `BillingClerk` records a payment of `amount_cents` against an `ISSUED` invoice; the amount must be positive and no more than the current `amount_due_cents`, with overpayment rejected as `ERR_PAYMENT_EXCEEDS_AMOUNT_DUE` (HTTP 422). The payment accrues into `payments_applied_cents` and the due is recomputed: a payment short of the due moves `payment_status` from `UNPAID` to `PARTIALLY_PAID`, while one that exactly covers the due — or a credit application that does — moves it to `PAID`. When the invoice belongs to a completed assignment, reaching `PAID` bubbles the request from `COMPLETED` to `CLOSED` and stamps `closed_at`.

Credit memos are the platform's instrument for returning money. A `QualityReviewer` or `BillingClerk` creates one against an organization with `org_id`, a positive `amount_cents`, the OCC field `expected_org_version` per §2.7 (a stale view is rejected with `ERR_STALE_ORG_VERSION`, HTTP 412), and an optional `complaint_id` that is null for manual goodwill credits. Creation immediately runs the waterfall: among the org's invoices that are `ISSUED` and not yet `PAID`, ordered by `issued_at` ascending with ties broken by `created_at` ascending and further ties by creation order (ids never consulted), the memo applies the lesser of its remaining balance and each invoice's `amount_due_cents`, oldest first, recording each application as a pair of `invoice_id` and `amount_cents` appended to the memo's `applications` array in application order. Each application raises the invoice's `credits_applied_cents` and recomputes its due; an invoice whose due reaches zero flips to `PAID` (bubbling its request to `CLOSED` as above), while one partially covered stands at `PARTIALLY_PAID` when some amount has been applied and the due remains below the subtotal. Whatever is left becomes the memo's `remaining_cents`, and a memo fully consumed turns `EXHAUSTED`; otherwise it stays `OPEN`. Memo creation increments the organization's `version`.

Voiding a memo is the compensating action: a `BillingClerk` voids a memo in `OPEN` or `EXHAUSTED` (anything else draws `ERR_CREDIT_MEMO_NOT_OPEN`), flipping it to `VOID` and reversing every application on its invoices — each invoice's `credits_applied_cents` is reduced, its `amount_due_cents` recomputed, and its `payment_status` recomputed, so a `PAID` invoice may revert to `PARTIALLY_PAID` or `UNPAID` without reopening any request already `CLOSED`; a voided memo with no applications simply closes. The voided memo's `remaining_cents` is restored to its full `amount_cents`. Memo voiding likewise increments the org's `version`. Clerks and coordinators track positions through the invoice listing's `org_id`, `encounter_id`, `issue_status`, `payment_status`, and `dispute_status` filters, the per-org credit-memo listing with its `status` filter, and the per-complaint memo listing.

### 3.9. Complaints, Adjudication, Quality Scoring, and Reporting

Quality enforcement starts when an `OrgRequester` files a complaint naming their own `org_id`, the offending `assignment_id` — which must belong to that org and stand in `COMPLETED` or `NO_SHOW` (else `ERR_COMPLAINT_INVALID_STATE`) — a `category` of `QUALITY`, `LATENESS`, `PROFESSIONALISM`, `BILLING`, or `ACCESS`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `narrative`. Filing denormalizes the assignment's interpreter onto the complaint as `interpreter_id`, opens it as `FILED` with `reopen_count` zero and `penalty_points`, `credit_pct`, and `credit_amount_cents` all null, and immediately recomputes the interpreter's provisional quality score.

Adjudication belongs to the `QualityReviewer`. Beginning review moves a `FILED` complaint to `UNDER_REVIEW` (from any other state, `ERR_COMPLAINT_INVALID_STATE`). Adjudicating requires `UNDER_REVIEW` and branches on `outcome`. A dismissal closes the complaint as `DISMISSED`: it leaves the provisional scope, both quality scores are recomputed, and its penalty and credit fields stay null. Substantiation closes it as `SUBSTANTIATED` and fires the money cascade: `penalty_points` is set by severity — five for `MINOR`, fifteen for `MAJOR`, thirty for `CRITICAL` — and both quality scores are recomputed; `credit_pct` takes its severity default (ten percent for `MINOR`, a quarter for `MAJOR`, half for `CRITICAL`) unless the payload's `credit_pct_override` supplies a different fraction (a number between 0 and 1 inclusive); `credit_amount_cents` is that fraction times the base, rounded half-up, where the base is the `subtotal_cents` of the assignment's `ISSUED` invoice when one exists and otherwise the assignment's `estimated_cost_cents`. Substantiation then auto-creates a credit memo on the filing organization for exactly `credit_amount_cents` with `complaint_id` pointing at the complaint, and that memo immediately runs the waterfall of §3.8 — which may flip invoices to `PAID` and bubble their requests to `CLOSED` — and increments the organization's `version`.

The two quality scores differ only in which complaints they count. The final `quality_score` is 100 minus the summed `penalty_points` of the interpreter's `SUBSTANTIATED` complaints, floored at zero. The `quality_score_provisional` runs the same arithmetic but also counts complaints still `FILED` or `UNDER_REVIEW`, assuming the worst on everything pending — so a single pending `CRITICAL` complaint splits the two scores by thirty points. Both are recomputed on every read of the interpreter and on every complaint event.

A dismissed complaint is not necessarily dead: the filing `OrgRequester` may reopen it, returning it from `DISMISSED` to `UNDER_REVIEW`, provided `reopen_count` is still zero — a second reopen is rejected with `ERR_COMPLAINT_ALREADY_REOPENED`, and reopening from any state other than `DISMISSED` draws `ERR_COMPLAINT_INVALID_STATE`. Reopening increments `reopen_count` and, because the complaint is pending again, recomputes both quality scores. Complaints are browsable per org, per interpreter, and per assignment through their respective listings, each with a `status` filter.

Reporting closes the loop. A `PlatformAdmin` generates a snapshot over a half-open window — `window_start` inclusive, `window_end` exclusive and strictly later — optionally scoped to one `org_id`, where a null org produces a platform-wide snapshot; `generated_at` stamps the logical generation time. The snapshot's request metrics count requests whose `scheduled_start` falls inside the window: `total_requests` overall; `filled_count` in `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, or `CLOSED`; `unfilled_count` in `UNFILLED`; and `cancelled_count` in `CANCELLED`. The `fulfillment_rate` divides filled by the difference of total minus cancelled, rounded half-up to four decimal places, and is 0.0 when that denominator is zero. The `no_show_count` counts `NO_SHOW` assignments whose request's scheduled start falls in the window. The `avg_response_minutes` averages, over assignments with an `accepted_at` whose `offered_at` falls in the window, the minutes between offer and acceptance, rounded half-up to two decimals and 0.0 when no such assignments exist. The `total_billed_cents` sums `subtotal_cents` over `ISSUED` invoices whose `issued_at` falls in the window. Complaint metrics count complaints created in the window as `complaint_count` with the `SUBSTANTIATED` subset in `substantiated_count`. Finally, `ada_context_mix` breaks the included requests into per-context counts for `MEDICAL`, `LEGAL`, `EDUCATION`, and `GENERAL`. Snapshots are listed and fetched with the usual envelope, the listing filterable by `org_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`; the availability-window deletion returns `204 No Content` with no payload. The table below is a navigational summary only — request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the deferred sweeps | PlatformAdmin |
| POST | `/orgs` | Create a requesting organization | PlatformAdmin |
| GET | `/orgs/{id}` | Get an org (outstanding balance recomputed on read) | Any |
| POST | `/orgs/{id}/suspend` | Suspend an org (credit hold) | PlatformAdmin |
| POST | `/orgs/{id}/reinstate` | Reinstate a suspended org | PlatformAdmin |
| GET | `/orgs/{id}/complaints` | List complaints filed by an org | Any |
| GET | `/orgs/{id}/credit-memos` | List credit memos of an org | Any |
| POST | `/rate-cards` | Create a rate card | PlatformAdmin |
| GET | `/rate-cards/{id}` | Get a rate card | Any |
| POST | `/rate-cards/{id}/retire` | Retire a rate card; pinned snapshots unaffected | PlatformAdmin |
| POST | `/interpreters` | Create an interpreter profile | PlatformAdmin |
| GET | `/interpreters/{id}` | Get an interpreter (scores and strikes recomputed on read) | Any |
| POST | `/interpreters/{id}/activate` | Activate an interpreter | PlatformAdmin |
| POST | `/interpreters/{id}/suspend` | Manually suspend an interpreter (cascades) | PlatformAdmin |
| POST | `/interpreters/{id}/reinstate` | Reinstate a suspended interpreter | PlatformAdmin |
| POST | `/interpreters/{id}/certifications` | Submit a certification (created unverified) | PlatformAdmin, Interpreter |
| GET | `/interpreters/{id}/certifications` | List an interpreter's certifications | Any |
| POST | `/interpreters/{id}/certifications/{certId}/verify` | Verify a certification | PlatformAdmin |
| POST | `/interpreters/{id}/availability-windows` | Create an availability window | Interpreter |
| GET | `/interpreters/{id}/availability-windows` | List availability windows | Any |
| DELETE | `/interpreters/{id}/availability-windows/{windowId}` | Delete an availability window | Interpreter |
| GET | `/interpreters/{id}/strikes` | List an interpreter's strike records | Any |
| GET | `/interpreters/{id}/complaints` | List complaints against an interpreter | Any |
| POST | `/requests` | Create an interpreting request | OrgRequester |
| GET | `/requests` | List requests with filters | Any |
| GET | `/requests/{id}` | Get a request | Any |
| POST | `/requests/{id}/submit` | Submit a DRAFT request for matching | OrgRequester |
| POST | `/requests/{id}/cancel` | Cancel a request (tiered fee from CONFIRMED) | OrgRequester, PlatformAdmin |
| POST | `/requests/{id}/offers` | Create an assignment offer (OCC on request version) | PlatformAdmin |
| GET | `/requests/{id}/offers` | List assignments offered for a request | Any |
| GET | `/assignments` | List assignments with filters | Any |
| GET | `/assignments/{id}` | Get an assignment | Any |
| POST | `/assignments/{id}/accept` | Interpreter accepts an offer | Interpreter |
| POST | `/assignments/{id}/decline` | Interpreter declines an offer | Interpreter |
| POST | `/assignments/{id}/confirm` | Confirm an accepted assignment | PlatformAdmin |
| POST | `/assignments/{id}/depart` | Interpreter departs (on-site modalities only) | Interpreter |
| POST | `/assignments/{id}/check-in` | Interpreter checks in; creates the encounter | Interpreter |
| POST | `/assignments/{id}/check-out` | Interpreter checks out with travel/mileage claims | Interpreter |
| POST | `/assignments/{id}/cancel` | Cancel an assignment (tiered fee) | OrgRequester, PlatformAdmin |
| POST | `/assignments/{id}/mark-no-show` | Mark interpreter no-show after the grace period | PlatformAdmin |
| GET | `/assignments/{id}/encounters` | Get the encounter for an assignment | Any |
| GET | `/assignments/{id}/invoices` | Get invoices for an assignment | Any |
| GET | `/assignments/{id}/complaints` | List complaints for an assignment | Any |
| GET | `/assignments/{id}/strikes` | List strikes linked to an assignment | Any |
| POST | `/encounters/{id}/verify` | Verify an encounter (optionally corrected times) | OrgRequester |
| POST | `/invoices/generate` | Generate a DRAFT invoice for a completed, verified assignment | BillingClerk |
| GET | `/invoices` | List invoices with filters | Any |
| GET | `/invoices/{id}` | Get an invoice | Any |
| POST | `/invoices/{id}/issue` | Issue a DRAFT invoice | BillingClerk |
| POST | `/invoices/{id}/void` | Void a DRAFT or eligible ISSUED invoice | BillingClerk |
| POST | `/invoices/{id}/dispute` | Dispute an ISSUED invoice | OrgRequester |
| POST | `/invoices/{id}/resolve-dispute` | Resolve an OPEN dispute | BillingClerk |
| POST | `/invoices/{id}/payments` | Record a payment (partial allowed) | BillingClerk |
| POST | `/complaints` | File a complaint against a completed or no-show assignment | OrgRequester |
| GET | `/complaints/{id}` | Get a complaint | Any |
| POST | `/complaints/{id}/begin-review` | Begin complaint review | QualityReviewer |
| POST | `/complaints/{id}/adjudicate` | Substantiate or dismiss a complaint | QualityReviewer |
| POST | `/complaints/{id}/reopen` | Reopen a dismissed complaint (once) | OrgRequester |
| GET | `/complaints/{id}/credit-memos` | List credit memos originating from a complaint | Any |
| POST | `/credit-memos` | Create a manual credit memo (OCC on org version) | QualityReviewer, BillingClerk |
| GET | `/credit-memos/{id}` | Get a credit memo including applications | Any |
| POST | `/credit-memos/{id}/void` | Void a credit memo, reversing applications | BillingClerk |
| POST | `/strikes` | Manually record a documented no-show strike | PlatformAdmin |
| POST | `/strikes/{id}/rescind` | Rescind an active strike | PlatformAdmin |
| POST | `/reports/generate` | Generate a compliance/utilization snapshot | PlatformAdmin |
| GET | `/reports` | List reporting snapshots | Any |
| GET | `/reports/{id}` | Get a reporting snapshot | Any |

## 5. Error Code Catalogue

The catalogue below is an index only; the trigger condition for each error lives with the workflow that raises it in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ONSITE_ADDRESS_REQUIRED` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_ORG_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_INTERPRETER_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_AVAILABILITY_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENCOUNTER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_MEMO_NOT_FOUND` | 404 Not Found |
| `ERR_STRIKE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_ORG_NOT_ACTIVE` | 409 Conflict |
| `ERR_INTERPRETER_NOT_ACTIVE` | 409 Conflict |
| `ERR_RATE_CARD_ALREADY_RETIRED` | 409 Conflict |
| `ERR_REQUEST_NOT_DRAFT` | 409 Conflict |
| `ERR_REQUEST_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REQUEST_NOT_OFFERABLE` | 409 Conflict |
| `ERR_MAX_OFFER_ATTEMPTS_REACHED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_OFFERED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ON_SITE` | 409 Conflict |
| `ERR_ENCOUNTER_ALREADY_VERIFIED` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_VERIFIED` | 409 Conflict |
| `ERR_INVOICE_NOT_DRAFT` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTED` | 409 Conflict |
| `ERR_COMPLAINT_INVALID_STATE` | 409 Conflict |
| `ERR_COMPLAINT_ALREADY_REOPENED` | 409 Conflict |
| `ERR_CREDIT_MEMO_NOT_OPEN` | 409 Conflict |
| `ERR_STRIKE_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACTIVE_STRIKES_AT_LIMIT` | 409 Conflict |
| `ERR_AVAILABILITY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INTERPRETER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_VRI_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_MODALITY_NOT_OFFERED` | 422 Unprocessable Entity |
| `ERR_VRI_CERTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CREDENTIAL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_QUALITY_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_INVALID_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_CHECK_IN_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NO_SHOW_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_NO_AVAILABILITY_COVERAGE` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_AMOUNT_DUE` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_REQUEST_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORG_VERSION` | 412 Precondition Failed |
