# AML / KYC & Sanctions Screening API — Product Requirements Document

## 1. Introduction

Financial institutions operate under an unforgiving regulatory mandate: every customer relationship must be risk-rated, screened against sanctions and watchlists, monitored for suspicious money movement, and — where warranted — escalated into a formal investigation that may culminate in a regulatory filing with the financial crimes authority. This document specifies the Anti-Money-Laundering (AML) and Know-Your-Customer (KYC) platform that governs that end-to-end obligation. The system is the system of record for customer due diligence (CDD) posture, beneficial-ownership transparency, OFAC/EU-sanctions/PEP/adverse-media screening, transaction-monitoring rules, case management, and the preparation and submission of Suspicious Activity Reports (SAR) and Currency Transaction Reports (CTR).

The defining characteristic of the domain is its tight regulatory coupling. A customer's risk rating gates its onboarding posture, and that posture is not a one-way ratchet — a newly confirmed sanctions hit on an already-approved customer reopens enhanced due diligence, cascading down to the customer's accounts. Screening hits drive both onboarding clearance and the alert-to-case escalation chain; transaction alerts feed cases; cases produce filings; and a periodic lookback review can re-screen a historical window of account activity, materializing fresh work items that themselves can mint alerts. Because regulatory exposure is irreversible once a filing is submitted, the platform enforces strict segregation of duties (a four-eyes principle between the analyst who prepares a filing and the reviewer who approves it) and optimistic concurrency control on the most contended state changes.

This specification is written for the engineering team building the service. It describes the behavior the API must exhibit — entity lifecycles, calculation rules, validation precedence, and the precise contract of every response — without prescribing an internal implementation. Where a rule has regulatory significance, the intended business outcome is stated alongside the mechanical requirement.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. With the sole exception of customer creation — and even that endpoint requires authentication; anonymous onboarding is never permitted — every endpoint requires both headers. A request missing either header, or carrying an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose authenticated role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles: `ComplianceOfficer`, `Analyst`, `QualityReviewer`, `SystemFeed`, and `PlatformAdmin`. The `ComplianceOfficer` owns the customer due-diligence lifecycle, screening-hit dispositions, account freezes, and lookback planning. The `Analyst` investigates alerts and cases, links alerts, recommends case dispositions, prepares filings, and dispositions lookback items. The `QualityReviewer` is the second pair of eyes who approves and submits filings. The `SystemFeed` is the ingestion role that posts transactions and records the financial-crimes authority's acknowledgements. The `PlatformAdmin` is an operational superuser that can create customers and accounts, read everything, and drive the test clock.

All five roles use an **opaque** identity model. When `X-User-Role` is `ComplianceOfficer`, `Analyst`, `QualityReviewer`, `SystemFeed`, or `PlatformAdmin`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id` for ownership purposes. The server does, however, record it where a workflow demands it: opening a case captures the acting user into `opened_by_user_id` on the `Case`; preparing a filing captures it into `prepared_by_user_id` on the `Filing`; approving a filing captures it into `approved_by_user_id`; and every state-changing operation writes an `AuditEvent` whose `actor_user_id` is the request's `X-User-ID` and whose `actor_role` is the request's `X-User-Role`. These recorded identifiers drive the four-eyes segregation-of-duties check on filings, described in §3, but they are operator identities, not entity foreign keys.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` falls outside 1 through 100, or whose `offset` is negative, is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most top-level resources — `Customer`, `BeneficialOwner`, `RiskAssessment`, `ScreeningHit`, `Account`, `Alert`, `Case`, `Filing`, `LookbackReview`, and `LookbackReviewItem` — carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification; it advances on every mutation to the resource, including server-driven mutations such as cascade transitions and recomputations of derived fields.
- **`version`** — a system-managed integer that begins at its initial value of 1 on creation and increments by exactly one on every mutation of the resource. It underpins optimistic concurrency control (§2.11).

Two entities are deliberately lighter. A `Transaction` and an `AuditEvent` are immutable append-only records: each carries only `id` and `created_at`, and neither carries `updated_at` nor `version`. A `Transaction` is never modified after it posts; an `AuditEvent` is written once and never changed.

### 2.5. Hierarchical Consistency and Cascades

The platform models an entity graph centered on the `Customer`. Beneficial owners, risk assessments, screening hits, and accounts all reference their owning customer; alerts reference both an account and a customer; cases reference a customer and aggregate alerts; filings reference a case; and lookback items reference both a review and an account. Whenever an operation mutates more than one entity, every secondary effect is part of the contract, not an optional nicety. Cascade transitions described throughout §3 — a rejected customer freezing its accounts, a confirmed derogatory hit reopening enhanced due diligence and re-pending the customer's accounts, a closed-no-action case dismissing its alerts and reverting account monitoring — each independently mutate the affected resource, advancing its `updated_at` and incrementing its `version`.

The system performs these reconciliations automatically when the triggering condition is met, without requiring a separate client request against the dependent resource. A compound parent such as a `LookbackReview` advances its own status purely as a function of its children's terminal states; the parent transition fires the moment the last child reaches a terminal item status.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a path that names one or more ancestors — for example, a customer's screening hits or a case's filings. The server validates the existence of every identifier in the path from left to right, rejecting the request with `ERR_NOT_FOUND` at the first path segment that does not resolve to an existing resource. A request for the beneficial owners of a non-existent customer fails on the customer before the server ever considers the child collection. After path identifiers, any foreign-key reference carried in the request body is validated for existence the same way, again yielding `ERR_NOT_FOUND` when the referenced resource is absent. This existence check (priority 3) runs after authentication and authorization but before body well-formedness and all business rules.

### 2.7. Validation Precedence

When several checks apply to a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. The global ordering is: authentication first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_FORBIDDEN`), then existence of path and foreign-key resources (`ERR_NOT_FOUND`), then body well-formedness — required fields present, enum values valid, numeric ranges honored, types correct (`ERR_INVALID_REQUEST`). Only after a request clears these structural gates does the server evaluate domain-specific business rules.

Within the structural-and-conditional tier, customer-type field consistency (`ERR_TYPE_FIELD_MISMATCH`) is checked on customer creation immediately after general body validity. Uniqueness of an account reference (`ERR_DUPLICATE_ACCOUNT_REF`) follows. State-machine legality of a requested transition (`ERR_INVALID_STATE`) is then checked for all transition endpoints, and the optimistic-concurrency version check (`ERR_STALE_VERSION`) follows the state check on the two endpoints that carry a version. The remaining business-safety, referential, temporal, fiscal, and decision-validity rules described in §3 are each evaluated after these, in the relative order their narratives establish. Pagination-bound validity (`ERR_PAGINATION_INVALID`) guards every list endpoint.

### 2.8. Precision, Rounding, and Monetary Units

All monetary amounts in the system are carried as integer cents; a `Transaction`'s `amount_cents`, an `Account`'s `opening_balance_cents`, `aggregate_cash_in_cents`, and `cumulative_credited_cents` are all whole-cent integers. Threshold comparisons against these amounts are therefore exact integer comparisons.

Weighted scores are decimal numbers. A `RiskAssessment`'s `total_score`, an `Alert`'s `severity_score`, and any other computed score are rounded to exactly two decimal places using the round-half-up convention. An ownership percentage (`ownership_pct`) is a decimal carried to two places. Datetime arithmetic for review cadence and filing deadlines is performed in whole UTC days.

### 2.9. The Logical Clock

Time-dependent computations — periodic-review due dates and filing deadlines — and any "current time" the server needs are read from a server-controlled logical clock rather than wall-clock time. Accordingly, every server-minted "now" timestamp is sourced from this logical clock, including each resource's `created_at` and `updated_at` and each response envelope's `api_request_timestamp`; once the clock has been set, these timestamps reflect the logical instant rather than wall-clock time. An administrative test-driving capability allows a `PlatformAdmin` to set the server's current UTC instant by supplying a `to_iso8601` value, so that deadline and review-cadence behavior can be exercised deterministically. Client-supplied posting timestamps on transactions (`posted_at`) are independent inputs and are not affected by the logical clock.

### 2.10. The Audit Trail

Every state transition and consequential operation appends an `AuditEvent`. Each event records the `entity_type` (the entity class concerned, such as Customer, Case, or Filing), the `entity_id` of the affected resource, an `action` string naming the transition or operation (for example `CASE_DISPOSITIONED` or `FILING_APPROVED`), the `actor_user_id` that performed it, and the `actor_role` in force at the time. The `entity_id` is an identity reference only and is never itself a business-decision input. Audit events are queryable, filterable by `entity_type` and `entity_id`.

### 2.11. Optimistic Concurrency Control

Two operations are guarded by optimistic concurrency control because each mutates a heavily contended parent whose derived state another writer may have already advanced.

Linking an alert to a case is the first. The link request must carry `expected_case_version`, which must equal the target case's current `version`. Linking an alert legitimately recomputes the case's `priority` and `linked_alert_count` and may auto-advance the case from `TRIAGE` to `INVESTIGATING`; consequently a link request carrying a version observed before some earlier link no longer reflects the case's current priority or disposition. When `expected_case_version` does not match the case's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412, preventing the client from acting on a case it has not observed in its current form.

Applying a risk assessment to a customer is the second. The apply request must carry `expected_customer_version`, which must equal the target customer's current `version`. Applying a rating mutates `risk_rating`, `risk_score`, and `edd_required`, and — when the rating is `PROHIBITED` — cascades to the customer's accounts; a request carrying a stale customer version would overwrite a rating the client never saw. When `expected_customer_version` does not match the customer's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412.

No other endpoint carries a version field, and no other endpoint performs a version check.

### 2.12. Sanctions and Risk Posture as a Cross-Cutting Invariant

Two derived quantities on a `Customer` are the system's central safety gates and are recomputed wherever the underlying facts change. The first is `open_hit_count`: the number of that customer's screening hits whose `disposition` is either `PENDING` or `ESCALATED`. The second is `edd_required`, the flag that gates approval: enhanced due diligence is required when the customer's `risk_rating` is `HIGH`, or when `open_hit_count` is greater than zero, or when the customer has any screening hit that is both `CONFIRMED` and derogatory. Both are recomputed on apply-rating, on the recording of any screening hit (whether a customer-level hit or one minted by beneficial-owner screening), on screening-hit confirmation, on screening-hit false-positive disposition, on screening-hit reopen, and on clear-screening. The conservation principle behind these gates is simple: a customer with unresolved sanctions exposure can never be cleared or approved into normal operation, and an account inherits its transactability from its owning customer's posture.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and the Cyclic CDD Lifecycle

The `Customer` is the hub of the platform. A `ComplianceOfficer` or `PlatformAdmin` onboards one by supplying its `legal_name`, its `customer_type` — either `INDIVIDUAL` or `LEGAL_ENTITY` — and its `country_code`, a two-letter uppercase ISO country code. The customer may also self-declare politically-exposed-person status through `is_pep_self_declared`, which defaults to false when omitted. Two further inputs are conditional on type: a `date_of_birth` is required when the customer is an `INDIVIDUAL` and must be null for a `LEGAL_ENTITY`, while an `incorporation_date` is required when the customer is a `LEGAL_ENTITY` and must be null for an `INDIVIDUAL`. Violating either conditional — supplying the wrong date field for the type, or omitting the required one — is rejected with `ERR_TYPE_FIELD_MISMATCH`. A newly created customer begins life in `NEW` `cdd_status` with a null `risk_rating` and null `risk_score`.

The due-diligence lifecycle is intentionally cyclic, reflecting that compliance posture is revisited whenever new facts arrive. From `NEW`, a customer is rated and advances to `RISK_RATED`. From `RISK_RATED`, once screening is resolved, it advances to `SCREENING_CLEARED`. From `SCREENING_CLEARED`, approval routes the customer either to `APPROVED` or, when enhanced due diligence is outstanding, to `EDD_REQUIRED`. A customer in `EDD_REQUIRED` returns to `APPROVED` once its enhanced-diligence obligations are satisfied. The cycle's defining edge is that an `APPROVED` customer can be driven back to `EDD_REQUIRED` by a newly confirmed derogatory hit, and from there back to `APPROVED` again — diligence reopens as often as new derogatory facts appear. Two states are terminal: `REJECTED` (reached when a rating comes back prohibited) and `OFFBOARDED` (reached when an approved customer is wound down).

The rating step itself is two operations. First, a `ComplianceOfficer` creates a `RiskAssessment` for the customer; this only computes a score and band and does not move the customer. Applying that assessment is the transition that moves the customer from `NEW` to `RISK_RATED`. Applying requires that the customer currently be in `NEW` and that an unapplied assessment exist; it is the optimistic-concurrency-guarded operation described in §2.11, taking `risk_assessment_id` and `expected_customer_version`. The matching assessment must be a `RiskAssessment` row for this customer identified by `risk_assessment_id` whose `applied` flag is still false; if none matches, the request is rejected with `ERR_NO_UNAPPLIED_ASSESSMENT`. On a successful apply the assessment's `risk_band` is copied into the customer's `risk_rating`, the assessment's `total_score` is copied into the customer's `risk_score`, the assessment's `applied` flag is set true, and `edd_required` is recomputed. If the applied band is `PROHIBITED`, the customer is immediately driven to the terminal `REJECTED` state and, as a cascade, every account of that customer whose `monitoring_status` is not already `FROZEN` has its `kyc_status` set to `KYC_BLOCKED` and its `monitoring_status` set to `FROZEN`.

Clearing screening moves a customer from `RISK_RATED` to `SCREENING_CLEARED`. It is permitted only when the customer is in `RISK_RATED`, the `risk_rating` is not `PROHIBITED`, the customer's `open_hit_count` is zero (no screening hit remains in `PENDING` or `ESCALATED`), and — for a `LEGAL_ENTITY` — every one of its beneficial owners has a `screening_status` other than `UNSCREENED`. An attempt to clear screening while `open_hit_count` is greater than zero, or while the rating is `PROHIBITED`, is rejected with `ERR_OPEN_HITS_BLOCK_CLEARANCE`; an attempt to clear screening while a `LEGAL_ENTITY`'s beneficial owner is still `UNSCREENED` is rejected with `ERR_INVALID_STATE`.

Approval acts on a `SCREENING_CLEARED` customer. It is a single operation that routes by the customer's `edd_required` flag: when enhanced due diligence is not required the customer moves to `APPROVED`, and when it is required the same operation instead moves the customer to `EDD_REQUIRED`. On reaching `APPROVED` — whether directly from `SCREENING_CLEARED` or later from `EDD_REQUIRED` — the system sets `periodic_review_due_at` (see §3.3) and cascades each of the customer's accounts whose `kyc_status` is `PENDING_KYC` to `KYC_OK`. Completing enhanced due diligence is the transition out of `EDD_REQUIRED` back to `APPROVED`; it is permitted only when the customer is in `EDD_REQUIRED` and `open_hit_count` is zero, and it carries the same approval cascades.

An `APPROVED` customer may be offboarded by a `ComplianceOfficer`, moving it to the terminal `OFFBOARDED` state; as a cascade, every account whose `monitoring_status` is not already `FROZEN` has its `monitoring_status` set to `FROZEN` and its `kyc_status` set to `KYC_BLOCKED`. Customers may be fetched individually or listed with pagination and an optional filter on `cdd_status`.

### 3.2. Risk Scoring

Creating a `RiskAssessment` runs the weighted multi-factor risk-scoring model. The assessment carries a `variant` — either `PROVISIONAL` (an onboarding estimate computed over the customer's self-declared inputs) or `FINAL` (computed after screening, over adjudicated inputs) — and four risk factors, each an integer from 1 to 5: a `geography_factor` capturing country risk, a `product_factor` capturing product and channel risk, a `pep_factor` capturing politically-exposed-person exposure, and an `adverse_media_factor` capturing adverse-media exposure. Creating the assessment computes its `total_score`, derives its `risk_band`, and leaves its `applied` flag false until the assessment is later applied to the customer.

The base score is the weighted sum of the four factors: the `geography_factor` weighted by 4, the `product_factor` weighted by 3, the `pep_factor` weighted by 5, and the `adverse_media_factor` weighted by 3, each weight multiplied by its factor and the four products summed. A single non-linear surcharge then applies: when the larger of `pep_factor` and `adverse_media_factor` equals 5, a flat surcharge of 12 is added to the base — and because the surcharge keys off the maximum of the two factors rather than each independently, it is added at most once even when both factors are maxed. The `total_score` is the base plus that surcharge, rounded half-up to two decimal places.

The `risk_band` is then derived from `total_score` against inclusive lower thresholds: a `total_score` of at least 84 yields `PROHIBITED`; a `total_score` of at least 60 but below 84 yields `HIGH`; a `total_score` of at least 35 but below 60 yields `MEDIUM`; and a `total_score` below 35 yields `LOW`.

The two variants differ in exactly one place. A `PROVISIONAL` assessment uses the four factors as supplied, with no adjustment. A `FINAL` assessment, before applying the weighted formula, adds 1 to the `pep_factor` (capped so it never exceeds 5) whenever the customer has at least one screening hit that is both `CONFIRMED` and derogatory at the moment of computation; this pre-formula bump is what makes a `FINAL` assessment diverge from a `PROVISIONAL` one computed from identical input factors once a sanctions hit has been confirmed. A `PROVISIONAL` assessment never applies this bump. A customer's risk assessments can be listed with pagination.

### 3.3. Periodic Review Cadence

When a customer reaches `APPROVED`, the system computes when that customer is next due for periodic review and records it in `periodic_review_due_at`. The due instant is the customer's `created_at` advanced by a whole number of days that depends on the customer's risk band: 90 days for a `HIGH`-rated customer, 180 days for a `MEDIUM`-rated customer, and 365 days for a `LOW`-rated customer. Because approval can be reached more than once across the cyclic lifecycle, this due date is recomputed on each arrival at `APPROVED` from the customer's then-current rating. All such arithmetic is performed in whole UTC days.

### 3.4. Beneficial Ownership

A `LEGAL_ENTITY` customer's ultimate beneficial owners must be captured and screened before that customer can clear screening. A `ComplianceOfficer` adds a `BeneficialOwner` by supplying its `full_name`, its `ownership_pct`, its two-letter uppercase `country_code`, and an optional `is_control_person` flag (the FinCEN control prong) that defaults to false. The ownership percentage must be greater than zero and at most 100, carried to two decimals. A beneficial owner may be added only to a `LEGAL_ENTITY` customer; attempting to add one to an `INDIVIDUAL` customer is rejected with `ERR_UBO_ON_INDIVIDUAL`. Furthermore, the sum of `ownership_pct` across all of a customer's beneficial owners must never exceed 100.00 percent; an addition that would push the aggregate above that ceiling is rejected with `ERR_OWNERSHIP_EXCEEDS_100`. A newly added owner begins with a `screening_status` of `UNSCREENED`.

Screening a beneficial owner records an outcome via an `outcome` value. A `CLEARED` outcome simply sets the owner's `screening_status` to `CLEARED`. A `HIT` outcome sets `screening_status` to `HIT` and, in addition, creates a `ScreeningHit` whose `beneficial_owner_id` points at this owner and whose `disposition` begins at `PENDING`; the screening payload may carry the `list_type`, `matched_name`, and `match_score` that describe that hit. Recording a hit on an owner recomputes the owning customer's `open_hit_count` and `edd_required`. Beneficial owners can be fetched individually, listed under their customer, and their screening hits listed.

### 3.5. Screening Hits and Their Disposition

A screening hit represents a match between a customer (or one of its beneficial owners) and a watchlist. A `ComplianceOfficer` records a customer-level hit by supplying the `list_type` — one of `OFAC_SDN`, `EU_SANCTIONS`, `PEP`, or `ADVERSE_MEDIA` — the `matched_name` string, and a `match_score` between 0.00 and 1.00 carried to two decimals. The system derives `is_derogatory` from the list source: a hit is derogatory when its `list_type` is `OFAC_SDN` or `EU_SANCTIONS` (a true-positive sanctions match), and is not derogatory for `PEP` or `ADVERSE_MEDIA`. A customer-level hit carries a null `beneficial_owner_id`; a hit minted from beneficial-owner screening carries that owner's id. Recording a hit recomputes the owning customer's `open_hit_count` and `edd_required`. Every hit begins in `PENDING` disposition.

A hit's disposition lifecycle has a branching shape with a revert edge. From `PENDING`, a `ComplianceOfficer` may disposition the hit as a false positive, moving it to the terminal `FALSE_POSITIVE` state — but only when the hit is not a confirmable sanctions match, that is, when its `match_score` is below 0.95 or its `list_type` is `PEP` or `ADVERSE_MEDIA`; the `FALSE_POSITIVE` edge is undefined for a confirmable sanctions match (one that is derogatory with `match_score` at least 0.95), so a false-positive disposition attempted on such a hit is rejected with `ERR_INVALID_STATE`. Reaching `FALSE_POSITIVE` recomputes the customer's `open_hit_count` (decrementing it) and recomputes `edd_required`. Also from `PENDING`, the officer may escalate the hit to `ESCALATED`. An `ESCALATED` hit can be walked back: reopening it returns the hit to `PENDING` for re-review. An `ESCALATED` hit can instead be confirmed, moving it to the terminal `CONFIRMED` state, but confirmation is permitted only when the hit is derogatory and its `match_score` is at least 0.95. Attempting to confirm a hit that is not derogatory, or whose `match_score` is below 0.95, is rejected with `ERR_HIT_NOT_CONFIRMABLE`.

Confirming a hit is the most consequential disposition. It recomputes `open_hit_count`, sets the customer's `edd_required` to true, and — when the confirmed hit carries a non-null `beneficial_owner_id` — sets that beneficial owner's `screening_status` to `HIT`. Most importantly, if the owning customer is currently `APPROVED`, confirming a derogatory hit drives that customer from `APPROVED` to `EDD_REQUIRED`: this is the cyclic revision edge. As part of that customer transition, `edd_required` is forced true and every account of the customer whose `kyc_status` is `KYC_OK` is cascaded back to `PENDING_KYC`, reopening account-level diligence. Screening hits can be listed under a customer (filterable by `disposition`) or under a beneficial owner.

The decision value supplied to a hit disposition must be one of `FALSE_POSITIVE`, `ESCALATE`, or `CONFIRM`; any other value is rejected with `ERR_INVALID_DECISION`. A disposition or reopen attempted from a state in which the requested edge is not defined is rejected with `ERR_INVALID_STATE`.

### 3.6. Accounts, Their Parallel Dimensions, and Transaction Monitoring

An `Account` carries two independent state dimensions that evolve separately: a KYC dimension, `kyc_status`, and a transaction-monitoring dimension, `monitoring_status`. A `ComplianceOfficer` or `PlatformAdmin` opens an account under a customer by supplying its external `account_ref` and its `opening_balance_cents`, an integer of at least zero. The `account_ref` must be unique across all accounts; a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_REF`. A new account begins with `kyc_status` of `PENDING_KYC` and `monitoring_status` of `ACTIVE`.

The KYC dimension is driven entirely by the owning customer's lifecycle. When the customer reaches `APPROVED`, accounts in `PENDING_KYC` cascade to `KYC_OK`. When the customer is driven from `APPROVED` back to `EDD_REQUIRED` by a new confirmed derogatory hit, accounts in `KYC_OK` cascade back to `PENDING_KYC` for re-review. When the customer reaches `REJECTED` or `OFFBOARDED`, accounts cascade to `KYC_BLOCKED`. The monitoring dimension is driven by investigation activity: an account in `ACTIVE` moves to `UNDER_INVESTIGATION` when an alert is created against it; a `ComplianceOfficer` may freeze an account that is `UNDER_INVESTIGATION`, moving its `monitoring_status` to `FROZEN`; and an account in `UNDER_INVESTIGATION` reverts to `ACTIVE` automatically once no alert against that account remains in `LINKED` status. Freezing acts only on the monitoring dimension and leaves `kyc_status` untouched.

Posting a transaction is how account activity enters the system. A `SystemFeed` or `ComplianceOfficer` posts a `Transaction` against an account by supplying its `direction` — one of `CASH_IN`, `CASH_OUT`, `WIRE_IN`, or `WIRE_OUT` — its `amount_cents` (a positive integer), its `posted_at` timestamp (a valid ISO 8601 string, which the server stores and returns normalized to UTC with three fractional digits), and its two-letter uppercase `counterparty_country`. A transaction may not be posted to an account whose `kyc_status` is `KYC_BLOCKED` or whose `monitoring_status` is `FROZEN`; such a post is rejected with `ERR_ACCOUNT_NOT_TRANSACTABLE`. Each posted transaction updates the account's running tallies and is then evaluated by the monitoring rules; the rule it trips, if any, is recorded in its `triggered_rule`.

Two running tallies are maintained on the account. The `aggregate_cash_in_cents` is the same-UTC-day sum of `CASH_IN` amounts: the relevant window is the calendar-day bucket of `posted_at` in UTC, spanning from midnight up to but not including the next midnight, and when a transaction's `posted_at` falls on a new UTC day the aggregate resets to zero before this transaction is folded in. The `cumulative_credited_cents` is the lifetime running sum of all credited amounts — every `CASH_IN` and every `WIRE_IN` — and is used both by the rapid-movement rule and as a conserved lifetime quantity.

The monitoring rules are evaluated in a fixed precedence, and the first rule that matches becomes the transaction's `triggered_rule`. First, the currency-transaction-report rule: for a `CASH_IN`, take the same-UTC-day cash-in window total after this amount is added; if that post-addition total is strictly greater than 1,000,000 cents (that is, strictly above 10,000 dollars), the rule `CTR_THRESHOLD` fires — a window total of exactly 1,000,000 cents does not fire, because the boundary is strict. Second, if the currency-transaction rule did not fire, the structuring rule: a `CASH_IN` whose own `amount_cents` is at least 900,000 and at most 1,000,000 cents — the just-under-threshold band, inclusive at both ends — fires `STRUCTURING`. Third, the high-risk-geography rule: a transaction whose `counterparty_country` is one of IR, KP, SY, or CU fires `HIGH_RISK_GEO`. Fourth, the rapid-movement rule: a `CASH_OUT` or `WIRE_OUT` fires `RAPID_MOVEMENT` when its `amount_cents` is at least 90 percent of the account's `cumulative_credited_cents` as observed before this transaction was folded in, where that 90-percent threshold is the product of 0.90 and the prior cumulative credited amount, rounded half-up to a whole cent before the comparison. If no rule matches, `triggered_rule` is left null.

When a rule fires, the system mints an `Alert` against the account with `rule_code` equal to the triggered rule and `status` of `OPEN`, and if the account's `monitoring_status` was `ACTIVE` it advances to `UNDER_INVESTIGATION`. The currency-transaction rule is fundamentally cumulative — the same 950,000-cent cash-in can be harmless at the start of a day yet tip the running window past the threshold later the same day — whereas structuring, high-risk-geography, and rapid-movement are all decided from a single transaction's own fields (with the rapid-movement rule additionally reading the prior cumulative credited amount). Transactions can be listed under their account.

### 3.7. Alerts and Their Severity

An `Alert` records that an account's activity tripped a monitoring rule. Beyond the system-minted alerts described above, an alert carries its `account_id`, the denormalized `customer_id` of the owning customer (used for case routing), the `rule_code` that fired (one of `STRUCTURING`, `RAPID_MOVEMENT`, `HIGH_RISK_GEO`, or `CTR_THRESHOLD`), a computed `severity_score`, a lifecycle `status`, and a `case_id` that is null until the alert is linked to a case. An alert's lifecycle runs `OPEN` → `LINKED` → and, on case closure, `DISMISSED`.

An alert's `severity_score` is computed at mint time in a fixed three-step order. First take the rule base weight for the alert's `rule_code`: 40 for `STRUCTURING`, 35 for `RAPID_MOVEMENT`, 25 for `HIGH_RISK_GEO`, and 20 for `CTR_THRESHOLD`. Second take the customer-risk multiplier for the owning customer's `risk_rating` at mint time: 1.0 for `LOW`, 1.5 for `MEDIUM`, 2.0 for `HIGH`, and 2.0 for `PROHIBITED` (a prohibited rating uses the same multiplier as high); a customer with no rating yet uses a multiplier of 1.0. Third, the `severity_score` is the rule base weight multiplied by that multiplier, rounded half-up to two decimal places. Alerts can be fetched individually, listed under an account (with an optional filter on `status`), and listed across the system with optional filters on `account_id`, `customer_id`, `case_id`, and `status`.

### 3.8. Case Investigation and the Fork-Join Disposition

A `Case` is the investigative container that bundles alerts and drives them toward a disposition. An `Analyst` opens a case for a customer by supplying the subject `customer_id`; the new case begins in `TRIAGE` disposition with `priority` of `LOW`, and the acting analyst's identity is captured into `opened_by_user_id` — the pin for the four-eyes principle enforced later at filing time. A case also carries a computed `linked_alert_count`, the number of alerts whose `case_id` is this case and whose `status` is `LINKED`.

Linking an alert to a case is the case's central operation and is optimistic-concurrency-guarded as described in §2.11, taking `alert_id` and `expected_case_version`. Linking is permitted only while the case is in `TRIAGE` or `INVESTIGATING`; an attempt to link an alert to a case in any other disposition is rejected with `ERR_INVALID_STATE`, checked after existence but before the stale-version check. Linking the first alert auto-advances the case from `TRIAGE` to `INVESTIGATING`. The link sets the alert's `status` to `LINKED` and its `case_id` to this case, recomputes `linked_alert_count` and `priority`, and — as a cross-entity cascade — if the alert's originating account is currently `ACTIVE`, advances that account's `monitoring_status` to `UNDER_INVESTIGATION`. Several guards protect the link, evaluated after existence and the stale-version check: an alert already in `LINKED` status cannot be linked again and is rejected with `ERR_ALERT_ALREADY_LINKED`; an alert whose `customer_id` does not equal the case's `customer_id` is rejected with `ERR_ALERT_CUSTOMER_MISMATCH`; and, checked after both of those, an alert whose originating account is `FROZEN` cannot be linked — the account is locked from further investigation routing — and is rejected with `ERR_ACCOUNT_BLOCKED_FOR_CASE`.

A case's `priority` is recomputed each time an alert is linked, from the maximum `severity_score` among all alerts whose `case_id` is this case and whose `status` is `LINKED`. The band is `CRITICAL` when that maximum is at least 70, `HIGH` when it is at least 50 but below 70, `MEDIUM` when it is at least 30 but below 50, and `LOW` otherwise.

From `INVESTIGATING`, the case reaches a fork with three branches; a disposition attempted from any disposition other than `INVESTIGATING` is rejected with `ERR_INVALID_STATE`. An `Analyst` (or `ComplianceOfficer`) may recommend a SAR, moving the case to `SAR_RECOMMENDED`, which requires that the case have at least one linked alert; absent any linked alert the request is rejected with `ERR_INVALID_STATE`. An `Analyst` (or `ComplianceOfficer`) may require a CTR, moving the case to `CTR_REQUIRED`, which is valid only when at least one linked alert has a `rule_code` of `CTR_THRESHOLD`; absent such an alert the request is rejected with `ERR_NO_CTR_ALERT`. Alternatively a `ComplianceOfficer` — and only a compliance officer, as a deliberate override — may close the case with no action, moving it to the terminal `CLOSED_NO_ACTION` state; a `CLOSE_NO_ACTION` decision submitted by any other authorized role (such as an `Analyst`) is rejected with `ERR_FORBIDDEN`, evaluated after the decision-value and state checks. Closing dismisses every linked alert (setting each alert's `status` to `DISMISSED` and clearing its `case_id` to null) and, for any account whose only linked alerts were on this case, reverts that account's `monitoring_status` from `UNDER_INVESTIGATION` back to `ACTIVE`. The disposition decision value must be one of `RECOMMEND_SAR`, `REQUIRE_CTR`, or `CLOSE_NO_ACTION`; any other value is rejected with `ERR_INVALID_DECISION`.

The two non-closing branches eventually re-join at the terminal `FILED` state by way of the filing workflow: a case in `SAR_RECOMMENDED` reaches `FILED` when a SAR filing for it is accepted, and a case in `CTR_REQUIRED` reaches `FILED` when a CTR filing for it is accepted. Cases can be fetched individually, listed (filterable by `customer_id` or `disposition`), and their linked alerts listed.

### 3.9. Regulatory Filings and the Four-Eyes Principle

A `Filing` is the regulatory report a case produces. An `Analyst` creates one for a case by supplying its `filing_type` — either `SAR` or `CTR`. The filing type must match the case's disposition: a `SAR` filing may be created only for a case in `SAR_RECOMMENDED`, and a `CTR` filing only for a case in `CTR_REQUIRED`; a mismatch is rejected with `ERR_FILING_TYPE_MISMATCH`. The new filing begins in `DRAFT` status, captures the preparing analyst into `prepared_by_user_id`, and has its regulatory `deadline_at` computed at creation. For a SAR, the deadline is the case's `created_at` advanced by 30 days. For a CTR, the anchor is the earliest `posted_at` among the currency-transaction-report transactions (those with `triggered_rule` equal to `CTR_THRESHOLD`) on the case's accounts, breaking ties on equal `posted_at` by earliest `created_at`, and the deadline is that anchor advanced by 15 days; when no such transaction exists the anchor falls back to the case's `created_at`, again advanced by 15 days. All deadline arithmetic is in whole UTC days.

The filing lifecycle is linear with a reject-and-revise loop, and it is the locus of the segregation-of-duties control. A `QualityReviewer` approves a `DRAFT` filing, which captures the reviewer into `approved_by_user_id`; approval requires the filing to be in `DRAFT`, and any other status is rejected with `ERR_NOT_APPROVABLE`. The four-eyes principle is non-negotiable: the `approved_by_user_id` must differ from the `prepared_by_user_id`, so the same user can never both prepare and approve a filing — a violation is rejected with `ERR_SEGREGATION_VIOLATION`. A `QualityReviewer` then submits the filing, moving it from `DRAFT` to `SUBMITTED`; submission requires the filing to be in `DRAFT` with `approved_by_user_id` set (an unset approver, or any status other than `DRAFT`, is rejected with `ERR_NOT_APPROVABLE`) and re-asserts that `approved_by_user_id` differs from `prepared_by_user_id` (otherwise `ERR_SEGREGATION_VIOLATION`).

Once submitted, the financial-crimes authority's acknowledgement is recorded by a `SystemFeed` through a `decision`. An `ACCEPT` decision, which must carry an `acknowledgement_code`, moves the filing from `SUBMITTED` to the terminal `ACCEPTED` state, stores that `acknowledgement_code`, and bubbles the owning case to `FILED`. A `REJECT` decision moves the filing from `SUBMITTED` to `REJECTED`. The acknowledgement decision value must be `ACCEPT` or `REJECT`; any other value is rejected with `ERR_INVALID_DECISION`. A `REJECTED` filing is not dead: an `Analyst` may revise it, returning it to `DRAFT` and clearing `approved_by_user_id` so that it must be approved afresh before it can be resubmitted. Filings can be fetched individually and listed under their case.

### 3.10. The Lookback Review

A `LookbackReview` re-screens a historical window of account activity — for example, after a new sanctions-list version is published. A `ComplianceOfficer` plans one by supplying a `reason`, a `window_start`, and a `window_end`; the window end must be strictly after the window start, and a window that is not is rejected with `ERR_INVALID_WINDOW`. A new review begins in `PLANNED` status and carries three derived counters, all starting at zero: `total_items`, `cleared_items`, and `escalated_items`.

Enqueuing a planned review materializes its work. The system creates one `LookbackReviewItem`, in `QUEUED` status, for each distinct account that has at least one transaction whose `posted_at` falls within the review window. The window is half-open: a transaction is in-window when its `posted_at` is at or after `window_start` and strictly before `window_end` — a transaction posted exactly at `window_start` is in-window, while one posted exactly at `window_end` is not. Crucially, an account contributes exactly one item no matter how many of its transactions fall in the window, and scope is the account's own in-window transactions, not the owning customer's other accounts. The review's `total_items` is set to the number of items created. Enqueue requires at least one in-window account: if the window contains no qualifying account, the review stays `PLANNED` and the request is rejected with `ERR_REVIEW_EMPTY`. Otherwise the review advances from `PLANNED` to `IN_PROGRESS`. A `ComplianceOfficer` may instead cancel a `PLANNED` review, moving it to the terminal `CANCELLED` state.

Each `LookbackReviewItem` references its parent `lookback_review_id` and the `account_id` under re-screening, and begins in `QUEUED`. An `Analyst` dispositions an item with a `decision` of either `CLEAR` or `ESCALATE`; any other decision is rejected with `ERR_INVALID_DECISION`, and a disposition is only permitted when the item is in `QUEUED` and its parent review is in `IN_PROGRESS` (otherwise `ERR_ITEM_NOT_QUEUED`). Clearing an item moves it to `CLEARED` and increments the parent's `cleared_items`. Escalating an item moves it to `ESCALATED`, increments the parent's `escalated_items`, and mints an `Alert` with `rule_code` of `HIGH_RISK_GEO` and `status` of `OPEN` against the item's `account_id`, recording that alert into the item's `generated_alert_id`; as a cross-entity cascade, if that account's `monitoring_status` is `ACTIVE` it advances to `UNDER_INVESTIGATION`. The review is compound: its status is a function of its items. The instant the sum of `cleared_items` and `escalated_items` equals `total_items` — every item having reached a terminal disposition — the parent bubbles from `IN_PROGRESS` to the terminal `COMPLETED` state. Review items can be fetched individually, listed under their review (filterable by `item_status`), and listed across the system with optional filters on `account_id` and `generated_alert_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify or transition an existing resource — including all lifecycle actions, dispositions, and acknowledgements — return a `200 OK` status code. The clock-setting capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer in NEW cdd_status | ComplianceOfficer, PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer by id | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/customers` | List customers (filter by cdd_status) | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/customers/{id}/risk-assessments` | Create a RiskAssessment; compute score and band | ComplianceOfficer |
| GET | `/customers/{id}/risk-assessments` | List a customer's risk assessments | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/customers/{id}/apply-rating` | Apply an unapplied assessment (NEW→RISK_RATED); OCC-guarded | ComplianceOfficer |
| POST | `/customers/{id}/clear-screening` | Advance RISK_RATED→SCREENING_CLEARED | ComplianceOfficer |
| POST | `/customers/{id}/approve` | Approve; routes to APPROVED or EDD_REQUIRED | ComplianceOfficer |
| POST | `/customers/{id}/complete-edd` | Complete EDD: EDD_REQUIRED→APPROVED | ComplianceOfficer |
| POST | `/customers/{id}/offboard` | Offboard an APPROVED customer (terminal) | ComplianceOfficer |
| POST | `/customers/{id}/beneficial-owners` | Add a beneficial owner to a LEGAL_ENTITY customer | ComplianceOfficer |
| GET | `/customers/{id}/beneficial-owners` | List a customer's beneficial owners | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/beneficial-owners/{id}/screen` | Record a UBO screening outcome | ComplianceOfficer |
| GET | `/beneficial-owners/{id}` | Fetch a beneficial owner by id | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/beneficial-owners/{id}/screening-hits` | List screening hits for a UBO | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/customers/{id}/screening-hits` | Record a customer-level screening hit | ComplianceOfficer |
| GET | `/customers/{id}/screening-hits` | List a customer's screening hits (filter by disposition) | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/screening-hits/{id}/disposition` | Disposition a hit: FALSE_POSITIVE / ESCALATE / CONFIRM | ComplianceOfficer |
| POST | `/screening-hits/{id}/reopen` | Revert an ESCALATED hit to PENDING | ComplianceOfficer |
| POST | `/customers/{id}/accounts` | Open an account for a customer | ComplianceOfficer, PlatformAdmin |
| GET | `/customers/{id}/accounts` | List a customer's accounts | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/accounts/{id}` | Fetch an account by id | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/accounts/{id}/transactions` | Post a transaction; run monitoring; may mint an Alert | SystemFeed, ComplianceOfficer |
| GET | `/accounts/{id}/transactions` | List an account's transactions | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/accounts/{id}/freeze` | Freeze an UNDER_INVESTIGATION account | ComplianceOfficer |
| GET | `/accounts/{id}/alerts` | List alerts for an account | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/alerts` | List alerts (filter by account_id, customer_id, case_id, status) | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/alerts/{id}` | Fetch an alert by id | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/cases` | Open an investigation case (TRIAGE) for a customer | Analyst |
| GET | `/cases/{id}` | Fetch a case by id | Analyst, ComplianceOfficer, QualityReviewer, PlatformAdmin |
| GET | `/cases` | List cases (filter by customer_id or disposition) | Analyst, ComplianceOfficer, QualityReviewer, PlatformAdmin |
| POST | `/cases/{id}/alerts` | Link an alert to a case; OCC-guarded; auto-advance | Analyst |
| POST | `/cases/{id}/disposition` | Disposition a case: RECOMMEND_SAR / REQUIRE_CTR / CLOSE_NO_ACTION | Analyst, ComplianceOfficer |
| GET | `/cases/{id}/alerts` | List alerts linked to a case | Analyst, ComplianceOfficer, QualityReviewer, PlatformAdmin |
| POST | `/cases/{id}/filings` | Create a SAR or CTR filing for a case | Analyst |
| GET | `/cases/{id}/filings` | List a case's filings | Analyst, ComplianceOfficer, QualityReviewer, PlatformAdmin |
| GET | `/filings/{id}` | Fetch a filing by id | Analyst, ComplianceOfficer, QualityReviewer, PlatformAdmin |
| POST | `/filings/{id}/approve` | QualityReviewer approves a DRAFT filing (4-eyes) | QualityReviewer |
| POST | `/filings/{id}/submit` | Submit an approved DRAFT filing | QualityReviewer |
| POST | `/filings/{id}/acknowledge` | Record acknowledgement: ACCEPT or REJECT | SystemFeed |
| POST | `/filings/{id}/revise` | Revert a REJECTED filing to DRAFT | Analyst |
| POST | `/lookback-reviews` | Plan a lookback re-screening review | ComplianceOfficer |
| GET | `/lookback-reviews/{id}` | Fetch a lookback review (with derived counts) | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/lookback-reviews/{id}/enqueue` | Materialize items; PLANNED→IN_PROGRESS | ComplianceOfficer |
| POST | `/lookback-reviews/{id}/cancel` | Cancel a PLANNED review | ComplianceOfficer |
| GET | `/lookback-reviews/{id}/items` | List a review's items (filter by item_status) | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/lookback-items/{id}` | Fetch a lookback review item by id | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| GET | `/lookback-items` | List lookback items (filter by account_id, generated_alert_id) | ComplianceOfficer, Analyst, QualityReviewer, PlatformAdmin |
| POST | `/lookback-items/{id}/disposition` | Disposition a QUEUED item: CLEAR or ESCALATE | Analyst |
| GET | `/audit-events` | List audit events (filter by entity_type, entity_id) | ComplianceOfficer, QualityReviewer, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_TYPE_FIELD_MISMATCH` | 422 |
| `ERR_DUPLICATE_ACCOUNT_REF` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OPEN_HITS_BLOCK_CLEARANCE` | 409 |
| `ERR_HIT_NOT_CONFIRMABLE` | 409 |
| `ERR_SEGREGATION_VIOLATION` | 409 |
| `ERR_FILING_TYPE_MISMATCH` | 409 |
| `ERR_NO_CTR_ALERT` | 409 |
| `ERR_ALERT_ALREADY_LINKED` | 409 |
| `ERR_ALERT_CUSTOMER_MISMATCH` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_UBO_ON_INDIVIDUAL` | 409 |
| `ERR_OWNERSHIP_EXCEEDS_100` | 409 |
| `ERR_ACCOUNT_NOT_TRANSACTABLE` | 409 |
| `ERR_NOT_APPROVABLE` | 409 |
| `ERR_REVIEW_EMPTY` | 409 |
| `ERR_ITEM_NOT_QUEUED` | 409 |
| `ERR_INVALID_DECISION` | 422 |
| `ERR_NO_UNAPPLIED_ASSESSMENT` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_ACCOUNT_BLOCKED_FOR_CASE` | 409 |
