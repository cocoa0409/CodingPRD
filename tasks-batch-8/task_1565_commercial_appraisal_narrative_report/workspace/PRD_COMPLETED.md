# Commercial Appraisal Reports API — Product Requirements Document

## 1. Introduction

Commercial valuation practices operate under professional standards — the Uniform Standards of Professional Appraisal Practice in the United States — that shape every stage of an assignment, from the moment a lender or law firm requests a quote to the day the workfile is finally destroyed. This document specifies the Commercial Appraisal Reports API: a system that manages the full production lifecycle of commercial appraisal narrative reports in the style of a national valuation and advisory practice. It governs engagement letters with their intended use and intended users, scope-of-work planning and valuation approach selection, rent roll and operating statement analysis, capitalization-rate support and discounted-cash-flow assumptions, internal review and MAI signature requirements, client revision handling under appraiser-independence rules, complexity-driven turnaround and fee quoting, and workfile retention with litigation support.

The API exists to enforce two properties that manual practice handles poorly. The first is segregation of duties: the appraiser who authors a report may never serve as its internal reviewer, and only an MAI-designated appraiser holding an active license — and never the report's author — may sign the final document. The second is a deterministic, clock-driven audit trail: every fee quote, value conclusion, revision decision, and retention deadline is computed from recorded inputs against a logical clock, so that a file can withstand litigation scrutiny years after delivery. All state transitions, calculations, and validation rules described below serve those two goals.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to declare the capacity in which that party acts. The system recognizes seven roles, spelled exactly as follows: `Client`, `EngagementManager`, `StaffAppraiser`, `ReviewAppraiser`, `MAISigner`, `RecordsManager`, and `LegalCounsel`. A request with a missing or malformed header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not on the target endpoint's authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Every read endpoint is open to all seven roles.

What `X-User-ID` means depends on the role. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client resource; ownership checks on any resource that references a Client compare the resource's foreign-key field — for example an engagement's `client_id` — to `X-User-ID`. When `X-User-Role` is `StaffAppraiser`, `ReviewAppraiser`, or `MAISigner`, `X-User-ID` is the `id` of the acting Appraiser resource; for a `StaffAppraiser` it is compared against the engagement's `author_appraiser_id`, for a `ReviewAppraiser` against the engagement's `reviewer_appraiser_id`, and for a `MAISigner` it identifies the signing appraiser who will be recorded as the report's `signer_appraiser_id`. When `X-User-Role` is `EngagementManager`, `RecordsManager`, or `LegalCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

Each role carries a distinct seat in the production workflow. A `Client` is the ordering party — typically a lender — and may accept or decline engagement letters, submit property data, and submit or withdraw revision requests, but may never edit valuation content directly. An `EngagementManager` is the firm's operations manager: registering clients and appraisers, drafting and submitting engagement letters, cancelling engagements, writing off fees, and maintaining appraiser license status. A `StaffAppraiser` is the production appraiser who authors the engagement's work: verifying data, developing approaches and comparables, drafting reports, and resolving client revision requests within independence limits. A `ReviewAppraiser` is the internal reviewer who approves or returns drafts and resolves escalated revision requests. A `MAISigner` is the MAI-designated signatory and the only role permitted to sign a report. A `RecordsManager` is the workfile custodian who authorizes and confirms destruction of retention records. A `LegalCounsel` places and releases litigation holds.

Three ownership checks recur throughout the workflows and are stated here once with their full scope. The client-ownership check — the caller must be the engagement's client, else `ERR_NOT_ENGAGEMENT_CLIENT` (HTTP 403) — guards five actions: accepting an engagement letter, declining an engagement letter, submitting property data to an engagement, creating a revision request on a report, and withdrawing a revision request. The author-ownership check — the `StaffAppraiser` caller must be the engagement's author appraiser, else `ERR_NOT_ASSIGNED_APPRAISER` (HTTP 403) — guards data-submission accept and reject; approach creation, completion, exclusion, and re-inclusion; comparable creation; report creation, submission to review, issuance to the client, reissuance, and finalization; and revision-request acceptance, escalation, and decline from `OPEN`. The reviewer-ownership check — the `ReviewAppraiser` caller must be the engagement's assigned reviewer, else `ERR_NOT_ASSIGNED_REVIEWER` (HTTP 403) — guards review approval, review return, and declining a revision request that stands `ESCALATED`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4.
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

### 2.3. Pagination and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken toward the resource created first.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `total_count` counts all matching resources before pagination, and `has_more` is true exactly when matching items remain beyond the returned page.

List endpoints accept optional equality filters drawn from each resource's own fields. Engagements filter by `client_id`, `author_appraiser_id`, `reviewer_appraiser_id`, or `status`. Data submissions filter by `engagement_id`, `submission_type`, or `status`. Valuation approaches filter by `engagement_id` or `status`. Comparable sales filter by `engagement_id`. Reports filter by `engagement_id`, `signer_appraiser_id`, `supersedes_report_id`, or `status`. Revision requests filter by `report_id` or `status`. Retention records filter by `engagement_id`; because a retention record is one-to-one with its engagement, that filtered list returns an array of zero or one element.

### 2.4. The Logical Clock and Engagement-Letter Validity

Time inside the system is governed by a logical clock, never by wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z. Every system-recorded timestamp in this document — submission and acceptance instants, signature and delivery instants, issuance anchors, litigation timestamps — reads this logical clock. An administrative, test-driving capability, `POST /_clock/set_current_utc`, sets the clock to a supplied instant carried in the `to_iso8601` request field — any parseable ISO 8601 value is accepted, earlier or later than the current reading, and a missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and returns the new reading as `current_utc`, echoing the supplied string exactly as provided; the capability is shared by the `EngagementManager`, `RecordsManager`, and `LegalCounsel` roles.

Advancing the clock triggers one automatic sweep: any engagement letter still waiting on the client whose age has run past its validity window is expired. Concretely, a letter in `PENDING_ACCEPTANCE` moves to `EXPIRED` when the new clock value is strictly later than fourteen days after its `submitted_at`; a letter whose fourteenth day has been reached exactly — the clock reading precisely fourteen days after `submitted_at` — remains `PENDING_ACCEPTANCE` and may still be accepted.

### 2.5. Common Resource Properties

Every resource in the system — Client, Appraiser, Engagement, DataSubmission, ValuationApproach, ComparableSale, Report, RevisionRequest, and RetentionRecord alike — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits recording the resource's last modification; it refreshes upon any change to the resource.
- **`version` (integer):** A system-managed integer that begins at 1 when the resource is created and increments with every modification to the resource. This field is the basis of optimistic concurrency control (§2.7).

Because every mutation increments `version` and refreshes `updated_at`, indirect mutations count as well: creating a new report version bumps the parent engagement's `version`, and accepting a revision request bumps the report's `version`. Readers should treat `version` as the authoritative change counter on every entity.

### 2.6. Monetary Precision, Rate Units, and Rounding Discipline

All monetary amounts in the system are represented as integer counts of whole cents — fee fields, rent and expense fields, comparable prices, and value conclusions alike. Whenever a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent. Rounding is deliberately not deferred to the end of a multi-step calculation: several computations in §3 pin the exact steps at which rounding half-up occurs (per-step in the stabilized NOI derivation, per-year in the discounted cash flow, per-contribution in value reconciliation), and an implementation that rounds only once at the end will produce different cent totals and is non-conforming.

Rates and percentages use three distinct representations, and the workflows in §3 rely on the distinction. Capitalization and discount rates are carried as integer basis points — a field such as `cap_rate_bps` holding 525 means five and a quarter percent, and converting to a decimal rate divides by ten thousand. Percentage fields such as `adjustment_pct` and `depreciation_pct` are numbers where 20 means twenty percent, and converting to a decimal fraction divides by one hundred. The reconciliation weight `weight_pct` is likewise a number of percent and must lie between 0 and 100 inclusive; no fixed decimal precision is enforced on it.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and they are the only two endpoints that take a version field.

First, creating a new report version against an engagement requires the request to carry `expected_engagement_version`, holding the engagement's `version` as the client last observed it. If the engagement's current `version` has advanced since that observation — most commonly because an earlier report creation on the same engagement legitimately superseded prior versions and bumped the engagement — the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), forcing the client to re-read before minting another version on state it has not seen.

Second, accepting a client revision request requires the request to carry `expected_report_version`, holding the report's `version` as last observed. Each accepted revision legitimately mutates the report — applying a value adjustment and advancing its `version` — so an accept that presents a pre-mutation version is acting on a stale report and is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412).

Endpoints not named here take no version field at all.

### 2.8. Professional Independence and Segregation of Duties

Appraiser independence is enforced structurally, not by policy text. Three rules stand. An engagement letter cannot be submitted to the client while the same appraiser occupies both production seats: at submit time, `author_appraiser_id` must differ from `reviewer_appraiser_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). A contingent fee is flatly prohibited: an engagement letter carrying `is_contingent_fee` set to true can never be accepted, and the acceptance attempt is rejected with `ERR_CONTINGENT_FEE_PROHIBITED` (HTTP 409). Client pressure on value conclusions is never actionable: a revision request whose `category` is `VALUE_PRESSURE` may be declined, escalated, or withdrawn, but any attempt to accept it is rejected with `ERR_INDEPENDENCE_COMPROMISE` (HTTP 409).

Signature carries its own independence gates, detailed in §3.8: the signer must hold the `MAI` designation, must hold an `ACTIVE` license, and must not be the engagement's author.

### 2.9. Validation Order and Error Precedence

When several checks apply to a single request, they are evaluated in one fixed order, and the first failing check produces the response. The cascade is:

1. **User context.** `X-User-ID` and `X-User-Role` must be present and well-formed — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The caller's role must appear in the endpoint's authorized role list — otherwise `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Existence.** Path identifiers and body foreign-key references must resolve to existing resources, validated left to right — otherwise `ERR_NOT_FOUND` (HTTP 404).
4. **Request schema.** Required fields must be present, enum members valid, integers positive where required, `period_end` not earlier than `period_start`, and `weight_pct` within 0 to 100 — otherwise `ERR_INVALID_REQUEST` (HTTP 400). A missing `resolution_note` or `review_note` where one is required also fails here.
5. **Client ownership.** Where the caller acts as the ordering party, they must be that engagement's client — otherwise `ERR_NOT_ENGAGEMENT_CLIENT` (HTTP 403).
6. **Author ownership.** Where the caller acts as the production appraiser, they must be the engagement's author — otherwise `ERR_NOT_ASSIGNED_APPRAISER` (HTTP 403).
7. **Reviewer ownership.** Where the caller acts as the internal reviewer, they must be the engagement's assigned reviewer — otherwise `ERR_NOT_ASSIGNED_REVIEWER` (HTTP 403).
8. **State validity.** The target resource must stand in a from-state the transition allows — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409).
9. **Optimistic concurrency.** On the two version-guarded writes of §2.7, the expected version must match — otherwise `ERR_STALE_ENGAGEMENT_VERSION` or `ERR_STALE_REPORT_VERSION` (HTTP 412).
10. **Professional-independence safety gates.** The USPAP-style gates of §2.8 and the signature gates of §3.8 — contingent fee prohibition, value-pressure acceptance ban, signer designation, signer license, and segregation of duties — each carrying their own error id at HTTP 409.
11. **Business constraints.** Turnaround feasibility, reconciliation weight sum, completed-approach presence, the per-type approach completion gates, approach-type uniqueness, and double write-off protection, each with its own error id at HTTP 409.
12. **Temporal constraints.** Operating-statement period overlap, appraiser overcommitment, the client revision window, the retention period, and the comparable-sale lookback, each with its own error id at HTTP 409.

Concretely, on a request where both an ownership rule and a business constraint could fail — say, a non-author attempting to complete an approach whose data gates are unmet — the caller always sees the ownership error first. Likewise the concurrency check precedes the independence gates, and state validity precedes both.

### 2.10. Resource Addressing and Existence Validation

Resources are peers joined by foreign-key references rather than deep URL ownership; even so, several creation paths nest a child under an engagement, and a few report-scoped paths nest under a report. Wherever a path carries multiple identifiers, existence is validated left to right, and the request is rejected with `ERR_NOT_FOUND` for the first identifier that does not resolve to an existing resource; body-carried foreign-key references such as `client_id` or `author_appraiser_id` are validated the same way. The URL identifier names used across the API are `clientId`, `appraiserId`, `engagementId`, `submissionId`, `approachId`, `comparableId`, `reportId`, `requestId`, and `recordId`. A request whose path matches no endpoint at all — including a recognized path used with an unsupported method — is likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Registering Clients and Appraisers

Before any engagement can be drafted, the `EngagementManager` registers the parties. A new client is registered with a `name` and a `client_type` — one of `LENDER`, `LAW_FIRM`, `INVESTOR`, or `GOVERNMENT_AGENCY`. Every client begins life with `total_billed_cents` at zero and `volume_discount_tier` at `NONE`. That tier is a loyalty measure derived entirely from lifetime billed fees: once a client's `total_billed_cents` reaches at least 5,000,000 cents the tier becomes `TIER_1`, and at least 15,000,000 cents it becomes `TIER_2`. The boundaries are inclusive — a client standing at exactly 5,000,000 cents is `TIER_1`, and one at exactly 14,999,999 cents is still `TIER_1`. The tier is recomputed every time the billed total mutates, which happens at delivery-time billing and at fee write-off (§3.8), and it feeds the volume discount in the fee quote (§3.2).

Appraisers are registered with a `full_name` and a `designation` of `TRAINEE`, `CERTIFIED_GENERAL`, or `MAI`; only the last may ever sign a report. Each appraiser's `license_status` begins at `ACTIVE` and moves under `EngagementManager` control — the request naming the target status in a `status` field — through a small lifecycle: suspension takes an `ACTIVE` license to `SUSPENDED`; reinstatement returns a `SUSPENDED` license to `ACTIVE`; an `ACTIVE` or `SUSPENDED` license may lapse to `EXPIRED`; and renewal brings an `EXPIRED` license back to `ACTIVE`. No other transition exists — an `EXPIRED` license cannot be suspended directly, and setting the status the license already holds is rejected with `ERR_INVALID_STATE_TRANSITION`. Every license change increments the appraiser's `version`.

### 3.2. The Engagement Letter: Scoping, Quoting, and Acceptance

An `EngagementManager` drafts an engagement letter by naming the ordering party via `client_id`, the production appraiser via `author_appraiser_id`, and the internal reviewer via `reviewer_appraiser_id`, then describing the assignment: the subject's `property_address`, its `property_type` (`OFFICE`, `RETAIL`, `INDUSTRIAL`, `MULTIFAMILY`, or `SPECIAL_PURPOSE`), its `building_sf` (which must be greater than zero), the engagement's `intended_use` (`FINANCING`, `LITIGATION`, `FINANCIAL_REPORTING`, or `TAX_APPEAL`), the `intended_users` array naming every party entitled to rely on the report, the client-requested `requested_turnaround_days` (greater than zero), and the `planned_approach_count` (one, two, or three). Two optional fields shape pricing: `fee_schedule`, defaulting to `TIERED` but alternatively `PER_SF`, and `is_contingent_fee`, defaulting to false. The letter is born in `DRAFT` status.

Two attributes are computed the moment the letter is created. The `complexity_tier` is `HIGH` whenever the property is `SPECIAL_PURPOSE`, or the intended use is `LITIGATION`, or the building is at least 100,000 square feet — a building of exactly 100,000 square feet therefore lands in `HIGH`. Failing all three of those, the tier is `LOW` only when every one of three conditions holds together: the building is under 10,000 square feet (so 9,999 square feet qualifies), the property type is `RETAIL` or `INDUSTRIAL`, and the intended use is `FINANCING`. Every other combination is `STANDARD`. From the tier comes `minimum_turnaround_days`: ten calendar days for `LOW`, fifteen for `STANDARD`, and twenty-five for `HIGH`.

Submitting the letter to the client moves the engagement from `DRAFT` to `PENDING_ACCEPTANCE`. Submission first enforces segregation of duties — if the author and reviewer are the same appraiser, the submit is rejected with `ERR_SEGREGATION_OF_DUTIES` — then computes and stores `quoted_fee_cents` and stamps `submitted_at` from the logical clock, anchoring the fourteen-day validity window described in §2.4.

The fee quote follows a pinned evaluation order, identical at submit and at acceptance: first a pre-discount subtotal is computed from the engagement's own attributes; then the discount percentage is looked up from the client's `total_billed_cents` exactly as it stands at that moment; finally the fee is the subtotal reduced by that discount, rounded half-up to whole cents. Because fees are billed only at delivery, the engagement's own fee is never part of its own discount base.

Under the `TIERED` schedule, the subtotal starts from a tier base — 250,000 cents for `LOW`, 450,000 cents for `STANDARD`, or 900,000 cents for `HIGH`. When `building_sf` exceeds 50,000 square feet, a size surcharge applies: the excess over 50,000 square feet is divided into blocks of 10,000 square feet, the block count rounds up to a whole block, and each block adds 15,000 cents. An approach add-on of 75,000 cents applies for every planned approach beyond the first, so a single-approach engagement pays none. If `requested_turnaround_days` is strictly less than the tier's expedited threshold — twenty days for `LOW`, thirty for `STANDARD`, forty-five for `HIGH` — the sum of base, surcharge, and add-on is multiplied by 1.25, and that product is rounded half-up to whole cents to form the pre-discount subtotal.

Under the `PER_SF` schedule, the subtotal is instead the tier's per-square-foot rate — twelve cents for `LOW`, eighteen for `STANDARD`, thirty for `HIGH` — multiplied by `building_sf`, plus a flat expedited supplement of 100,000 cents when the requested turnaround falls strictly below the same tier thresholds. The two schedules share inputs but price differently by construction.

The volume discount is ten percent when the client's `total_billed_cents` is at least 15,000,000 cents, five percent when it is at least 5,000,000 cents, and zero otherwise; the discounted result is rounded half-up to whole cents.

Acceptance belongs to the client and moves the letter from `PENDING_ACCEPTANCE` to `IN_PROGRESS`. Its checks run in the cascade order of §2.9: the caller must be the engagement's own client (`ERR_NOT_ENGAGEMENT_CLIENT`); the letter must still be open — one already swept to `EXPIRED` rejects with `ERR_INVALID_STATE_TRANSITION`; the contingent-fee prohibition fires next (`ERR_CONTINGENT_FEE_PROHIBITED`); then turnaround feasibility, rejecting with `ERR_TURNAROUND_INFEASIBLE` when `requested_turnaround_days` is less than `minimum_turnaround_days`; and finally capacity — if the author already holds another active engagement — one standing `IN_PROGRESS` or `LITIGATION_HOLD` — whose assignment window overlaps this one's, acceptance is rejected with `ERR_APPRAISER_OVERCOMMITTED`. An assignment window runs from an engagement's `accepted_at` inclusive to its `due_date` exclusive, a half-open interval, so one engagement ending exactly when another begins does not conflict. Upon acceptance the letter stamps `accepted_at` from the logical clock, computes `due_date` as `accepted_at` plus the requested turnaround in days, recomputes the fee and locks it into `final_fee_cents`, and bumps the engagement's `version`.

Decline and cancellation round out the letter's early exits. The client may decline a pending letter — optionally supplying a `reason`, which is accepted but not recorded — moving it to `DECLINED`. The `EngagementManager` may cancel from `DRAFT`, `PENDING_ACCEPTANCE`, or `IN_PROGRESS` — again with an optional, unrecorded `reason` — moving the engagement to `CANCELLED`; cancelling an in-progress engagement additionally drives every report of that engagement still in a non-terminal state (`DRAFTING`, `INTERNAL_REVIEW`, `REVIEWED`, `CLIENT_REVIEW`, `REVISION_REQUESTED`, `FINAL`, `SIGNED`, or `SUSPENDED`) to `SUPERSEDED`. `COMPLETED`, `CANCELLED`, `DECLINED`, and `EXPIRED` are the engagement's terminal states.

### 3.3. Property Data Submissions and Net Operating Income

Once an engagement is underway, the client furnishes the property data the analysis stands on. Each submission is created against the engagement — recorded on the resource as `engagement_id` — by the engagement's own client (`ERR_NOT_ENGAGEMENT_CLIENT` otherwise), and only while the engagement stands `IN_PROGRESS` (any other engagement state rejects with `ERR_INVALID_STATE_TRANSITION`); it carries a `submission_type` of `RENT_ROLL`, `OPERATING_STATEMENT`, or `TAX_BILL`, a coverage window from `period_start` to `period_end`, each accepted as an ISO 8601 date or timestamp — a bare date reading as 00:00:00Z — and echoed back exactly as supplied, with `period_end` inclusive and never earlier than `period_start` (a reversed window is `ERR_INVALID_REQUEST`), and four non-negative money figures: `scheduled_gross_rent_cents`, `vacancy_loss_cents`, `expense_reimbursements_cents`, and `operating_expenses_cents`. A new submission stands in `SUBMITTED`.

Operating statements carry one temporal integrity rule. Two statements on the same engagement may not cover overlapping time: if a new `OPERATING_STATEMENT`'s inclusive window from `period_start` through `period_end` intersects the inclusive window of any other statement on the engagement that is not `REJECTED`, the creation is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`. Rent rolls and tax bills are exempt from this check.

Verification belongs to the author appraiser. Accepting a submission moves it from `SUBMITTED` to `ACCEPTED`; rejecting moves it to `REJECTED` and records the supplied `review_note` on the submission. Both actions require the caller to be the engagement's author (`ERR_NOT_ASSIGNED_APPRAISER`) and the engagement to be `IN_PROGRESS` (`ERR_INVALID_STATE_TRANSITION` otherwise).

Acceptance of an `OPERATING_STATEMENT` — and only of that type — computes two net operating income variants and stores them on the submission; for other types, and before acceptance, `noi_trailing_cents` and `noi_stabilized_cents` remain null. The trailing-actual variant uses the figures as reported: scheduled gross rent minus vacancy and collection loss, plus expense reimbursements, minus operating expenses. The stabilized variant normalizes to market assumptions in a pinned step order, rounding half-up to whole cents at every step: first, effective gross income is the scheduled gross rent reduced by a five percent market vacancy allowance; second, stabilized expenses are the greater of the as-reported operating expenses and thirty percent of the scheduled gross rent — the expense floor; third, a replacement reserve of two percent of the scheduled gross rent is computed; finally, the stabilized NOI is the effective gross income plus the expense reimbursements, minus the stabilized expenses, minus the reserves. Identical inputs therefore yield two different NOI figures, and downstream valuation work draws on each deliberately (§3.5).

Both `SUBMITTED` and `ACCEPTED` submissions eventually reach `LOCKED` when the engagement completes and the workfile freezes (§3.8); `REJECTED` and `LOCKED` are the submission's terminal states.

### 3.4. Comparable Sales and Capitalization-Rate Support

Market evidence enters the file as comparable sales, added by the author appraiser against an engagement standing `IN_PROGRESS` (any other engagement state rejects with `ERR_INVALID_STATE_TRANSITION`). Each comparable records its `address`, the `sale_date`, the `sale_price_cents` (greater than zero), the `noi_at_sale_cents` (greater than zero), and the comparable's `size_sf` (greater than zero). Two optional fields tune how the sale is used: `adjustment_pct`, a net adjustment percentage defaulting to 0, and `selected_for_support`, defaulting to true, which marks whether the sale stands as evidence for the capitalization rate and sales value.

Recency is enforced at entry. A comparable's `sale_date` may not lie in the future — a future date is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and it may not fall earlier than two calendar years before the engagement's `accepted_at`, with a sale landing exactly on that boundary remaining eligible; a sale breaching the lookback is rejected with `ERR_COMPARABLE_TOO_OLD`.

Two derived rates are computed on every comparable at creation and rounded half-up to whole basis points: `implied_cap_rate_bps` is the sale's NOI multiplied by ten thousand and divided by its sale price, and `adjusted_cap_rate_bps` applies the comparable's net adjustment to that implied rate — the already-rounded implied rate multiplied by one plus `adjustment_pct` hundredths. Across all comparables on the engagement marked `selected_for_support`, the mean of the adjusted rates, itself rounded half-up to a whole basis point, forms the supported capitalization rate. The income approach may not stray from that market evidence: at income-approach completion (§3.5), the approach's own rate must sit within twenty-five basis points of the supported rate, inclusive — a gap of exactly twenty-five basis points is allowed.

### 3.5. Valuation Approaches and Indicated Values

Scope-of-work planning materializes as valuation approaches, created by the author appraiser on an `IN_PROGRESS` engagement (any other engagement state rejects with `ERR_INVALID_STATE_TRANSITION`). Each approach declares an `approach_type` — `INCOME`, `SALES_COMPARISON`, or `COST` — and a reconciliation `weight_pct`; a given type may appear only once per engagement, a second approach of the same type being rejected with `ERR_DUPLICATE_APPROACH_TYPE`. The remaining inputs are type-specific. An `INCOME` approach carries `cap_rate_bps`, the direct-capitalization rate in basis points, and optionally the discounted-cash-flow set: `dcf_holding_period_years`, `dcf_discount_rate_bps`, `dcf_exit_cap_bps`, and `revenue_growth_bps_annual`. A `COST` approach draws on `land_value_cents`, `replacement_cost_cents`, and `depreciation_pct` (a percentage between 0 and 100). At creation, `cap_rate_bps` is required for `INCOME` and must be a positive integer wherever supplied; `dcf_holding_period_years`, `dcf_discount_rate_bps`, and `dcf_exit_cap_bps` must be positive integers when present, while `revenue_growth_bps_annual` may be any integer; and `land_value_cents` and `replacement_cost_cents` must be non-negative — violations failing as `ERR_INVALID_REQUEST`. A new approach stands in `SELECTED`.

Completing an approach — `SELECTED` to `COMPLETE` — is gated per type, and the gates are checked in a fixed sequence after the caller has been confirmed as the engagement's author (`ERR_NOT_ASSIGNED_APPRAISER`) and the engagement confirmed `IN_PROGRESS`. For `INCOME`, in order: at least one `ACCEPTED` operating statement must exist on the engagement (`ERR_INCOME_DATA_MISSING`); at least one comparable marked `selected_for_support` must exist (`ERR_COMPARABLES_INSUFFICIENT`); the DCF set is all-or-none, so exactly some of the four DCF fields present is rejected with `ERR_DCF_ASSUMPTIONS_INCOMPLETE`; and the approach's `cap_rate_bps` must lie within the twenty-five-basis-point tolerance of the supported rate from §3.4 (`ERR_CAP_RATE_UNSUPPORTED`). For `SALES_COMPARISON`: at least one selected comparable must exist (`ERR_COMPARABLES_INSUFFICIENT`). For `COST`: land value, replacement cost, and depreciation must all be present (`ERR_COST_INPUTS_INCOMPLETE`).

Completion computes and stores the approach's `indicated_value_cents`. Both income variants first select the engagement's evidence statement: the `ACCEPTED` operating statement with the greatest `period_end`, ties broken toward the statement created most recently. When the DCF set is absent, direct capitalization applies: the selected statement's `noi_stabilized_cents` is multiplied by ten thousand and divided by the approach's `cap_rate_bps`, rounded half-up to whole cents. When all four DCF fields are present, the discounted cash flow supersedes direct capitalization. It projects from trailing actuals — year one's net operating income is the selected statement's `noi_trailing_cents` — converts `revenue_growth_bps_annual`, `dcf_discount_rate_bps`, and `dcf_exit_cap_bps` from basis points to decimal rates, and takes `dcf_holding_period_years` as the holding period. For each year of the hold, the projected cash flow is the year-one NOI grown at the annual rate for one fewer compounding periods than the year's number — year one itself is ungrown — then discounted at the discount rate compounded for that many years; each year's present value is rounded half-up to whole cents before being summed. The terminal value is the year-one NOI grown for the full holding-period count of compounding periods — the first year beyond the hold — divided by the exit capitalization rate, then discounted at the discount rate compounded for the holding-period count of years, rounded half-up to whole cents. The indicated value is the sum of the rounded annual present values plus the rounded terminal value.

The sales comparison approach works from unit values. For each comparable marked `selected_for_support`, the adjusted unit value is the sale price adjusted by its `adjustment_pct` and divided by its `size_sf`, rounded half-up to whole cents; the indicated value is the mean of those unit values multiplied by the subject's `building_sf`, again rounded half-up to whole cents. The cost approach is the most direct: the indicated value is `land_value_cents` plus the depreciated replacement cost — `replacement_cost_cents` reduced by `depreciation_pct` percent, rounded half-up to whole cents.

An approach the author no longer wishes to rely on can be excluded — `COMPLETE` to `EXCLUDED` — and later re-included, returning `EXCLUDED` to `COMPLETE`; both actions require the author and an `IN_PROGRESS` engagement, and the cycle is unrestricted while the engagement is in progress. Excluded approaches are omitted from reconciliation entirely (§3.6).

### 3.6. Report Production: Drafting, Reconciliation, and Internal Review

The narrative report is versioned. The author appraiser creates each new version against an `IN_PROGRESS` engagement — any other engagement state rejects with `ERR_INVALID_STATE_TRANSITION` — and the create is one of the two optimistic-concurrency writes of §2.7: the request must carry `expected_engagement_version` matching the engagement's current `version`, else it is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). Creation assigns `report_version_no` as one greater than the highest existing version on the engagement, so the first report is version one. Creation also supersedes the past: every existing report of the engagement still in a non-terminal state — `DRAFTING`, `INTERNAL_REVIEW`, `REVIEWED`, `CLIENT_REVIEW`, `REVISION_REQUESTED`, `FINAL`, or `SIGNED` — moves to `SUPERSEDED`, and the new report's `supersedes_report_id` points at the superseded report holding the greatest version number, remaining null when there was nothing to supersede, as for version one. The act of creating a version bumps the engagement's `version`, which is precisely why a second creation carrying the pre-creation observation is stale. A report is born in `DRAFTING`, with `review_cycle_count` at zero and `value_conclusion_cents` null until first submitted to review.

Submitting a draft to internal review moves it from `DRAFTING` to `INTERNAL_REVIEW` and snapshots the reconciled value conclusion. Two gates guard the submission, after authorship and engagement state: at least one approach must stand `COMPLETE` and not `EXCLUDED` (`ERR_NO_COMPLETED_APPROACH`), and the `weight_pct` values of exactly those included approaches must sum to exactly 100.00 (`ERR_WEIGHT_SUM_INVALID`). The snapshot then computes `value_conclusion_cents` as a weighted reconciliation with pinned rounding: each included approach contributes its `indicated_value_cents` multiplied by its `weight_pct` hundredths, rounded half-up to whole cents first, and the conclusion is the integer sum of those rounded contributions. Summing unrounded products and rounding once at the end yields a different cent total and is non-conforming.

Review belongs to the assigned reviewer alone (`ERR_NOT_ASSIGNED_REVIEWER`). Approval moves the report from `INTERNAL_REVIEW` to `REVIEWED` and requires the engagement to be `IN_PROGRESS`. Return sends the report from `INTERNAL_REVIEW` back to `DRAFTING` — the reviewer supplies a `review_note` describing the deficiencies — and increments `review_cycle_count`, so the file records how many times the draft has been sent back.

### 3.7. Client Review, Revision Requests, and Appraiser Independence

Issuing a reviewed draft to the client moves the report from `REVIEWED` to `CLIENT_REVIEW` — an author-only action requiring an `IN_PROGRESS` engagement — and stamps `issued_to_client_at` from the logical clock. That stamp anchors the client's revision window: thirty days.

Within the window, the engagement's client may file a revision request against a report standing in `CLIENT_REVIEW`. The caller must be the engagement's client (`ERR_NOT_ENGAGEMENT_CLIENT`); a report in any other state rejects the filing with `ERR_INVALID_STATE_TRANSITION`; and a filing later than thirty days after `issued_to_client_at` is rejected with `ERR_REVISION_WINDOW_CLOSED`. Each request carries a `category` — `FACTUAL_CORRECTION`, `CLARIFICATION`, `METHODOLOGY_QUESTION`, or `VALUE_PRESSURE` — a free-text `requested_change`, and optionally a `proposed_value_cents`, which is meaningful only for value-pressure requests. A new request stands `OPEN`, stamps its own `submitted_at`, and its creation automatically moves the report from `CLIENT_REVIEW` to `REVISION_REQUESTED`.

Resolution honors independence. The author may accept an `OPEN` request — the second optimistic-concurrency write of §2.7, so the request must carry `expected_report_version` matching the report's current `version`, else `ERR_STALE_REPORT_VERSION` (HTTP 412), and the report must still stand `REVISION_REQUESTED` (`ERR_INVALID_STATE_TRANSITION`). A `VALUE_PRESSURE` request may never be accepted: the attempt is rejected with `ERR_INDEPENDENCE_COMPROMISE`. Acceptance records the supplied `resolution_note` and the supplied `value_adjustment_cents` (null when omitted) on the request itself; when the accept supplies `value_adjustment_cents`, that signed amount is added to the report's `value_conclusion_cents`; and the accept bumps the report's `version` — the mutation that makes a second accept carrying the pre-acceptance version stale. Declining is split by seat: from `OPEN` the author declines, and from `ESCALATED` only the assigned reviewer may decline (`ERR_NOT_ASSIGNED_REVIEWER`); either way a `resolution_note` is required, and its absence is `ERR_INVALID_REQUEST`. The author may instead escalate an `OPEN` request to the reviewer, moving it to `ESCALATED`; escalation also happens automatically when a litigation hold suspends the report (§3.9). The client may withdraw an `OPEN` request, moving it to `WITHDRAWN`. `ACCEPTED`, `DECLINED`, and `WITHDRAWN` are the request's terminal states.

Two report actions depend on the request queue. Reissuing the report — `REVISION_REQUESTED` back to `CLIENT_REVIEW` — requires that no request on the report remain `OPEN` (`ERR_REVISION_REQUESTS_OPEN`) and refreshes `issued_to_client_at`, restarting the thirty-day window. Finalizing — `CLIENT_REVIEW` to `FINAL` — requires that no request stand `OPEN` or `ESCALATED` (`ERR_REVISION_REQUESTS_OPEN`). Both actions belong to the author.

### 3.8. Signature, Delivery, Billing, and the Workfile

Signature converts a finalized report into an opinion of value the firm stands behind. Signing moves the report from `FINAL` to `SIGNED` and is performed by the `MAISigner` role, whose `X-User-ID` must resolve to an existing Appraiser resource (`ERR_NOT_FOUND` otherwise), under three gates: the signing appraiser's `designation` must be `MAI` (`ERR_SIGNER_NOT_MAI_DESIGNATED`), their `license_status` must be `ACTIVE` (`ERR_SIGNER_LICENSE_INACTIVE`), and the signer must not be the engagement's author (`ERR_SEGREGATION_OF_DUTIES`). Signing records the caller's `X-User-ID` as `signer_appraiser_id` and stamps `signed_at`.

Delivery is the engagement's point of no return, performed by a `StaffAppraiser` or the `EngagementManager`, moving the report from `SIGNED` to `DELIVERED` and stamping `delivered_at`. Delivery fires a three-link cascade. First, the engagement itself moves from `IN_PROGRESS` to `COMPLETED` — the only path by which an engagement completes. Second, completion bills the client and opens the retention file: the client's `total_billed_cents` increases by the engagement's `final_fee_cents`, the client's `volume_discount_tier` is recomputed against the new total, and a RetentionRecord is created one-to-one with the engagement, standing `ACTIVE` with `completed_date` set to the calendar date of completion (at 00:00:00Z), `base_retain_until_date` set five years beyond that date — the USPAP retention floor — and `retain_until_date` initially equal to the base date. Third, the workfile freezes: every data submission of the engagement still in `SUBMITTED` or `ACCEPTED` moves to `LOCKED`.

After completion, the fee may still be reversed as a compensating billing action. The `EngagementManager` may write off a completed engagement's fee, which subtracts `final_fee_cents` from the client's `total_billed_cents`, recomputes the volume tier, sets `fee_written_off` to true, and bumps the engagement's `version` — a field mutation on `COMPLETED`, not a state change. A fee already written off rejects a second write-off with `ERR_FEE_ALREADY_WRITTEN_OFF`, and an engagement that has not completed has no final fee to write off, rejecting with `ERR_INVALID_STATE_TRANSITION`.

### 3.9. Litigation Holds, Retention, and Destruction

When a matter becomes contentious, `LegalCounsel` places a litigation hold, supplying a `matter_reference`. The hold behaves differently by engagement state. On an `IN_PROGRESS` engagement, the engagement moves to `LITIGATION_HOLD`, the matter caption is recorded on the engagement's `litigation_matter_reference`, every report of the engagement in a non-terminal, non-`SUPERSEDED` state is suspended — moving to `SUSPENDED` with its prior status saved into `pre_hold_status` — and every revision request still `OPEN` on each suspended report is escalated to `ESCALATED` as a direct consequence of the suspension. On a `COMPLETED` engagement, the hold instead lands on its retention record: the record must stand `ACTIVE` — any other record state rejects with `ERR_INVALID_STATE_TRANSITION` — and moves to `LITIGATION_HOLD`, stamping `litigation_hold_placed_at`, recording the matter caption as the record's `litigation_matter_reference`, and setting `retain_until_date` to null — retention becomes indefinite while held. An engagement in any other state rejects the hold with `ERR_INVALID_STATE_TRANSITION`.

Releasing the hold unwinds whichever cascade was applied. A held engagement returns from `LITIGATION_HOLD` to `IN_PROGRESS`; each suspended report is restored to its saved `pre_hold_status`, which is then cleared to null; and the engagement's `litigation_matter_reference` is cleared. A held retention record returns to `ACTIVE`, stamps `litigation_released_at`, keeps its recorded `litigation_matter_reference`, and recomputes `retain_until_date` as the later of `base_retain_until_date` and the calendar date of release extended by two years — litigation tolls the schedule. Releasing when no hold is in effect — the engagement neither stands `LITIGATION_HOLD` nor is `COMPLETED` with a held retention record — is rejected with `ERR_INVALID_STATE_TRANSITION`.

Destruction is a two-key ceremony belonging to the `RecordsManager`. Authorization moves a record from `ACTIVE` to `RELEASED_PENDING_DESTRUCTION` once the retention period has fully elapsed: the calendar date of the logical clock must be on or after `retain_until_date` — destruction authorized exactly on that date is allowed — and an earlier attempt is rejected with `ERR_RETENTION_PERIOD_NOT_ELAPSED`. Confirmation then moves the record from `RELEASED_PENDING_DESTRUCTION` to `DESTROYED`, its terminal state. The retention record's timeline is thus fully reconstructible from its fields: `completed_date`, `base_retain_until_date`, the litigation markers `litigation_hold_placed_at` and `litigation_released_at`, and the effective `retain_until_date`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a client or appraiser, drafting an engagement, submitting data, selecting an approach, adding a comparable, minting a report version, or filing a revision request — return `201 Created`. Operations that modify or transition an existing resource, and the clock-setting capability, return `200 OK`. The narrative workflows of §3 define each endpoint's request fields, preconditions, and side effects; this table is the address map only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; sweeps expired engagement letters | EngagementManager, RecordsManager, LegalCounsel |
| POST | `/clients` | Register a client | EngagementManager |
| GET | `/clients/{clientId}` | Get a client | All roles |
| POST | `/appraisers` | Register an appraiser | EngagementManager |
| GET | `/appraisers/{appraiserId}` | Get an appraiser | All roles |
| POST | `/appraisers/{appraiserId}/license_status` | Set an appraiser's license status | EngagementManager |
| POST | `/engagements` | Create an engagement letter in DRAFT | EngagementManager |
| GET | `/engagements/{engagementId}` | Get an engagement | All roles |
| GET | `/engagements` | List engagements with filters | All roles |
| POST | `/engagements/{engagementId}/submit` | Submit the engagement letter to the client | EngagementManager |
| POST | `/engagements/{engagementId}/accept` | Client accepts the engagement letter | Client |
| POST | `/engagements/{engagementId}/decline` | Client declines the engagement letter | Client |
| POST | `/engagements/{engagementId}/cancel` | Cancel an engagement | EngagementManager |
| POST | `/engagements/{engagementId}/write_off_fee` | Write off a completed engagement's final fee | EngagementManager |
| POST | `/engagements/{engagementId}/litigation-hold` | Place a litigation hold on an engagement or its retention record | LegalCounsel |
| DELETE | `/engagements/{engagementId}/litigation-hold` | Release a litigation hold | LegalCounsel |
| POST | `/engagements/{engagementId}/data-submissions` | Client submits a rent roll, operating statement, or tax bill | Client |
| GET | `/data-submissions/{submissionId}` | Get a data submission | All roles |
| GET | `/data-submissions` | List data submissions with filters | All roles |
| POST | `/data-submissions/{submissionId}/accept` | Author appraiser accepts a submission; computes NOI variants for operating statements | StaffAppraiser |
| POST | `/data-submissions/{submissionId}/reject` | Author appraiser rejects a submission | StaffAppraiser |
| POST | `/engagements/{engagementId}/approaches` | Select a valuation approach | StaffAppraiser |
| GET | `/approaches/{approachId}` | Get a valuation approach | All roles |
| GET | `/approaches` | List valuation approaches with filters | All roles |
| POST | `/approaches/{approachId}/complete` | Complete an approach; computes its indicated value | StaffAppraiser |
| POST | `/approaches/{approachId}/exclude` | Exclude a completed approach from reconciliation | StaffAppraiser |
| POST | `/approaches/{approachId}/include` | Re-include an excluded approach | StaffAppraiser |
| POST | `/engagements/{engagementId}/comparables` | Add a comparable sale | StaffAppraiser |
| GET | `/comparables/{comparableId}` | Get a comparable sale | All roles |
| GET | `/comparables` | List comparable sales with filters | All roles |
| POST | `/engagements/{engagementId}/reports` | Create a new narrative report version | StaffAppraiser |
| GET | `/reports/{reportId}` | Get a report | All roles |
| GET | `/reports` | List reports with filters | All roles |
| POST | `/reports/{reportId}/submit_review` | Submit a draft to internal review; snapshots the reconciled value | StaffAppraiser |
| POST | `/reports/{reportId}/review_approve` | Reviewer approves the draft | ReviewAppraiser |
| POST | `/reports/{reportId}/review_return` | Reviewer returns the draft for revision | ReviewAppraiser |
| POST | `/reports/{reportId}/issue_to_client` | Issue the reviewed draft to the client; starts the revision window | StaffAppraiser |
| POST | `/reports/{reportId}/reissue` | Re-issue the report after addressing revisions | StaffAppraiser |
| POST | `/reports/{reportId}/finalize` | Finalize the report | StaffAppraiser |
| POST | `/reports/{reportId}/sign` | MAI-designated signatory signs the report | MAISigner |
| POST | `/reports/{reportId}/deliver` | Deliver the signed report; completes the engagement | StaffAppraiser, EngagementManager |
| POST | `/reports/{reportId}/revision-requests` | Client submits a revision request | Client |
| GET | `/revision-requests/{requestId}` | Get a revision request | All roles |
| GET | `/revision-requests` | List revision requests with filters | All roles |
| POST | `/revision-requests/{requestId}/accept` | Author accepts a revision request | StaffAppraiser |
| POST | `/revision-requests/{requestId}/decline` | Decline a revision request — author from OPEN, reviewer from ESCALATED | StaffAppraiser, ReviewAppraiser |
| POST | `/revision-requests/{requestId}/escalate` | Author escalates a request to the reviewer | StaffAppraiser |
| POST | `/revision-requests/{requestId}/withdraw` | Client withdraws a request | Client |
| GET | `/retention-records/{recordId}` | Get a retention record | All roles |
| GET | `/retention-records` | List retention records with filters | All roles |
| POST | `/retention-records/{recordId}/authorize_destruction` | Authorize destruction once the retention period has elapsed | RecordsManager |
| POST | `/retention-records/{recordId}/confirm_destruction` | Confirm destruction | RecordsManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_ENGAGEMENT_CLIENT` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_APPRAISER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_REVIEWER` | 403 Forbidden |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REPORT_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CONTINGENT_FEE_PROHIBITED` | 409 Conflict |
| `ERR_INDEPENDENCE_COMPROMISE` | 409 Conflict |
| `ERR_SIGNER_NOT_MAI_DESIGNATED` | 409 Conflict |
| `ERR_SIGNER_LICENSE_INACTIVE` | 409 Conflict |
| `ERR_TURNAROUND_INFEASIBLE` | 409 Conflict |
| `ERR_WEIGHT_SUM_INVALID` | 409 Conflict |
| `ERR_NO_COMPLETED_APPROACH` | 409 Conflict |
| `ERR_DUPLICATE_APPROACH_TYPE` | 409 Conflict |
| `ERR_INCOME_DATA_MISSING` | 409 Conflict |
| `ERR_COMPARABLES_INSUFFICIENT` | 409 Conflict |
| `ERR_CAP_RATE_UNSUPPORTED` | 409 Conflict |
| `ERR_DCF_ASSUMPTIONS_INCOMPLETE` | 409 Conflict |
| `ERR_COST_INPUTS_INCOMPLETE` | 409 Conflict |
| `ERR_FEE_ALREADY_WRITTEN_OFF` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_APPRAISER_OVERCOMMITTED` | 409 Conflict |
| `ERR_REVISION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REVISION_REQUESTS_OPEN` | 409 Conflict |
| `ERR_COMPARABLE_TOO_OLD` | 409 Conflict |
| `ERR_RETENTION_PERIOD_NOT_ELAPSED` | 409 Conflict |
