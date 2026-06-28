# Restaurant Franchise Management & Royalty API — Product Requirements Document

## 1. Introduction

Operating a restaurant franchise network means holding two truths in tension at once. On one side sits the franchisor — a brand headquarters that grants territories, signs disclosure-backed agreements, collects a percentage of every franchisee's sales as royalty, funds national advertising, and polices brand standards through periodic audits. On the other side sit the franchisees, independent operators who open and run units, ring up point-of-sale revenue, source goods from approved vendors, and owe the brand a settlement at the close of each billing period. This API is the system of record that mediates that relationship: it tracks who holds which territory, what each unit sells, how much royalty and ad-fund contribution accrue, whether a unit still meets brand standards, and whether a franchisee remains in good financial and operational standing.

The platform is deliberately built around a small set of interlocking lifecycles rather than isolated CRUD tables. A franchisee progresses from applicant to approved to active, and can fall into default or be terminated. A unit carries two independent fates simultaneously — an operational one (planned, open, closed) and a compliance one (good standing, probation, suspension) — that evolve on the same record without disturbing each other. Royalty statements are drafted, issued, paid, allowed to go overdue, and ultimately written off, accumulating late fees along the way. Audits cycle through remediation loops. Franchise agreements branch at renewal time into renewal, transfer, or termination, each with its own cascade of consequences for territories and units. The sections that follow specify these behaviors precisely; readers implementing the system should treat every numeric threshold, state name, and error condition described here as a hard contract.

Throughout this document, all monetary amounts are expressed and stored in integer **cents** to avoid floating-point drift, and the brand's progression through time is modeled not by wall-clock dates but by a deterministic integer **period index** that the franchisor advances explicitly. Understanding these two conventions up front is essential to reading the calculation rules correctly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting principal, and `X-User-Role`, the role under which the caller is acting. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present and valid but the caller's role is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Authorization for each endpoint is enumerated in the endpoint table of §4.

The system recognizes exactly five roles, spelled precisely as follows: `Franchisor`, `ComplianceAuditor`, `Franchisee`, `FinanceClerk`, and `System`.

Four of these roles are **opaque** operator identities — their `X-User-ID` is not tied to any persisted entity. When `X-User-Role` is `Franchisor`, `X-User-ID` is an opaque brand-headquarters operator identifier not bound to any record; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ComplianceAuditor` (an opaque audit/vendor-compliance operator), when it is `FinanceClerk` (an opaque royalty/rebate settlement operator), and when it is `System` (the automated point-of-sale polling identity). For all four, the server may accept the identifier but never resolves it against stored data.

The `Franchisee` role is different: it is **entity-backed**. When `X-User-Role` is `Franchisee`, `X-User-ID` is matched against the `owner_user_id` field of a `Franchisee` record — that is, `X-User-ID` identifies the principal who owns that franchisee. Ownership checks then compare any resource the franchisee tries to mutate back to that franchisee. Concretely, a caller acting as `Franchisee` may only create or mutate units, sales reports, and vendor authorizations that belong to a franchisee whose `owner_user_id` equals the caller's `X-User-ID`; an attempt to act on another franchisee's resources is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule governs unit open and close, sales-report creation, and vendor-authorization creation.

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

List endpoints accept two query parameters that control paging: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of records to skip from the start of the result set. Results are always returned sorted by `created_at` in ascending order, so that the oldest record appears first. Each list response surfaces `limit`, `offset`, `total_count` (the total number of records matching the query before paging), and `has_more` (true when records remain beyond the current page) inside the `meta` object.

### 2.4. Common Resource Properties and Identity

Every resource the API creates carries a server-minted `id` formatted as a UUID with no type prefix, together with a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. The great majority of entities — brands, territories, franchisees, agreements, units, sales reports, royalty statements, vendors, vendor authorizations, audits, development schedules, and national accounts — additionally carry an `updated_at` timestamp (refreshed on every mutation, again ISO 8601 UTC with three fractional digits) and an integer `version` that begins at 1 and increases by one on each mutation of that record. Whenever a field on a resource changes, its `updated_at` is refreshed and its `version` is incremented; a read-only retrieval never advances either. There are no entities in this system that omit `updated_at` or `version` — all resources participate in the full common-field set.

### 2.5. The Brand Clock and Billing Periods

The brand does not advance through real calendar time. Instead each `Brand` carries an integer `current_period_index`, initialized to 0 when the brand is created, that represents the brand's current billing period. The franchisor (or a finance clerk) advances this counter one period at a time through the period-close operation; there is no other way to move the clock forward. A separate logical wall-clock field, `current_utc`, defaults to `2026-01-01T00:00:00Z` until explicitly set and exists chiefly to support deterministic test driving; it can be set to an arbitrary instant through an administrative clock capability that accepts a `brand_id` and a target instant supplied as `to_iso8601`. Because almost every temporal and fiscal rule keys off `current_period_index` rather than `current_utc`, implementers should treat the period index as the authoritative notion of "now."

### 2.6. Monetary Precision and Rounding

All amounts are integers denominated in cents. Calculations that produce fractional cents are resolved with **round half up** to whole cents unless a rule explicitly states otherwise — meaning a fractional part of exactly one-half rounds away from zero to the next whole cent. The rebate waterfall is the single exception that floors rather than rounds, and is described in §3 where the distribution algorithm is specified. The audit weighted score is the only non-cents quantity and is rounded half up to **one decimal place**; the precise rounding point in that computation is given in the audit section of §3.

### 2.7. Nested Retrieval and Referential Integrity

Several endpoints address a resource by an identifier embedded in the URL path (for example a brand, a unit, a royalty statement, or an audit). Path-referenced resources are validated left to right: the first identifier in the path is resolved before the next, and the first one that does not correspond to an existing record causes the request to fail with `ERR_NOT_FOUND` (HTTP 404). Foreign keys carried in request bodies — a `unit_id`, a `vendor_id`, a `franchisee_id`, and the like — are likewise required to reference existing records; a body that names a non-existent resource is also rejected with `ERR_NOT_FOUND`.

### 2.8. Optimistic Concurrency on Brand-Guarded Writes

Two operations settle figures derived from the brand clock and are therefore guarded by optimistic concurrency control against the brand's `version`. Both require the caller to supply `expected_brand_version` in the request body, carrying the client's last observed `version` of the target `Brand`.

The first is the rebate distribution operation that moves a national account from `OPEN` to `DISTRIBUTED`. A distribute request must carry `expected_brand_version` equal to the brand's current `version`. If another writer has advanced the brand since the client last read it — for instance by closing a period, which re-buckets which purchases fall in the current quarter — the distribute is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the qualifying purchase set is stale.

The second is the write-off of an overdue royalty statement, which recomputes the statement's final compound late fee against the brand clock. A write-off request must carry `expected_brand_version` equal to the brand's current `version`. If a period close has advanced the clock since the client last read the brand — changing the months-late count that feeds the compound late-fee formula — the write-off is rejected with `ERR_STALE_VERSION` (HTTP 412), because the months-late basis the client intends to settle is stale.

No other endpoint accepts or requires a version field; only these two carry `expected_brand_version`.

### 2.9. Validation Ordering

When more than one rule could reject a request, the checks are applied in a fixed precedence so that the returned error is deterministic. Authentication is evaluated first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every path-referenced resource (`ERR_NOT_FOUND`), then franchisee resource-ownership (`ERR_NOT_RESOURCE_OWNER`), then the target's state validity for the requested transition (`ERR_INVALID_STATE`). Business-rule checks specific to each operation are evaluated after those five universal gates; their individual conditions and error codes are described alongside the workflows they guard in §3. Field-level structural validation — non-negative amounts, discounts not exceeding gross sales, audit section scores within range, and a positive required-unit count — surfaces as `ERR_INVALID_REQUEST` (HTTP 400) and is described with the operations that accept those inputs.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Brand and Its Territories

Everything begins with a `Brand`, created by a franchisor. A brand records its `name` and the economic parameters of the franchise relationship: three marginal royalty rates, `royalty_tier_1_rate` (default 0.06), `royalty_tier_2_rate` (default 0.05), and `royalty_tier_3_rate` (default 0.04); an `ad_fund_rate` (default 0.02) for advertising contributions; and a `late_fee_monthly_rate` (default 0.015) applied to overdue obligations. On creation the brand's `current_period_index` is set to 0, its `current_utc` to the default instant of `2026-01-01T00:00:00Z`, and its `version` to 1.

A `Territory` is the geographic franchise right. Each territory belongs to a brand (`brand_id`), carries a `code` and a display `name`, and a `protected` flag (default true) indicating whether holding the territory grants the assigned franchisee exclusivity. A territory's `code` must be unique within its brand; an attempt to create a second territory with a `code` already used in that brand is rejected with `ERR_TERRITORY_CONFLICT` (HTTP 409). On creation a territory's `status` is `AVAILABLE` and its `assigned_franchisee_id` is null. Assigning a territory to a franchisee moves its `status` to `ASSIGNED` and records the holder in `assigned_franchisee_id`; attempting to assign a territory that is already `ASSIGNED` to another franchisee is likewise rejected with `ERR_TERRITORY_CONFLICT`. A retired territory carries `status` `RETIRED`. Territories are listable and filterable by brand, by `assigned_franchisee_id`, and by `status`.

### 3.2. Onboarding Franchisees

A `Franchisee` represents an independent operator and is created by the franchisor with a `brand_id`, a `legal_name`, and an `owner_user_id` (the opaque external identity that the `Franchisee` role's `X-User-ID` is matched against). The optional `is_existing_operator` flag (default false) records whether this party already operates other units of the brand, which later affects transfer economics. A freshly created franchisee enters `status` `APPLICANT` with `open_compliance_strikes` set to 0; `open_compliance_strikes` is a running count of how many of the franchisee's units currently sit in compliance suspension.

A franchisee's lifecycle proceeds through `APPLICANT → APPROVED → ACTIVE`, with possible detours into `DEFAULTED` and a terminal `TERMINATED`. Approval by a franchisor moves the franchisee from `APPLICANT` to `APPROVED`; approving a franchisee that is not currently `APPLICANT` is rejected with `ERR_INVALID_STATE`. The transition from `APPROVED` to `ACTIVE` is automatic and happens the moment the franchisee's first unit transitions to operational `OPEN` — it is never invoked directly. Reaching `DEFAULTED` and recovering from it are driven by compliance events described in §3.5 and §3.6.

Terminating a franchisee is a franchisor action available from either `ACTIVE` or `DEFAULTED`, moving the franchisee to `TERMINATED`. Termination is blocked under two conditions: if any unit of the franchisee is still in operational `OPEN`, the request is rejected with `ERR_FRANCHISEE_HAS_OPEN_UNITS`; and if any royalty statement belonging to any of the franchisee's units is in `OVERDUE` status, it is rejected with `ERR_OUTSTANDING_OBLIGATIONS`. When termination succeeds, it cascades: every territory the franchisee held has its `assigned_franchisee_id` reset to null and its `status` returned to `AVAILABLE`, and every franchise agreement of that franchisee currently in `EXECUTED` or `RENEWAL_PENDING` status is moved to `TERMINATED`. Franchisees are listable and filterable by brand and by `status`.

### 3.3. Franchise Agreements: Execution, Renewal, Transfer, and Decline

A `FranchiseAgreement` binds a franchisee to the brand under a disclosure document. It is created in `DRAFT` by the franchisor with a `franchisee_id`, an `fdd_version` (the Franchise Disclosure Document version the agreement is signed under), a `term_end_period_index` (the brand period at which the term expires), and an optional `transfer_fee_rate` (default 0.02) used later when valuing a transfer. The agreement's `brand_id` is derived from the franchisee. The `successor_agreement_id` field begins null and is set on the prior agreement when it is renewed or transferred to point at the agreement that supersedes it.

Executing a draft agreement moves it `DRAFT → EXECUTED`; it requires the agreement to currently be `DRAFT` (else `ERR_INVALID_STATE`) and the owning franchisee to be in `APPROVED` or `ACTIVE` status (else `ERR_FRANCHISEE_NOT_APPROVED`). Beginning renewal moves an executed agreement `EXECUTED → RENEWAL_PENDING`; it requires the agreement to be `EXECUTED` (else `ERR_INVALID_STATE`) and the renewal window to be open, meaning the brand's `current_period_index` is at least the agreement's `term_end_period_index` minus one. If the renewal window has not yet opened, the request is rejected with `ERR_RENEWAL_WINDOW_CLOSED`.

From `RENEWAL_PENDING` the agreement forks into one of three terminal outcomes, each with a distinct cascade.

Renewing the agreement moves it `RENEWAL_PENDING → RENEWED`. It requires the agreement to be `RENEWAL_PENDING` (else `ERR_INVALID_STATE`), that none of the franchisee's units is in compliance `SUSPENDED` (else `ERR_COMPLIANCE_BLOCK`), and that the request supplies both `new_fdd_version` and `new_term_end_period_index` (else `ERR_INVALID_REQUEST`). On success the system creates a successor `FranchiseAgreement` in `EXECUTED` status for the same franchisee, with its `fdd_version` set to `new_fdd_version` and its `term_end_period_index` set to `new_term_end_period_index`, and sets the original agreement's `successor_agreement_id` to the new agreement's id.

Transferring the agreement moves it `RENEWAL_PENDING → TRANSFERRED`. It requires the agreement to be `RENEWAL_PENDING` (else `ERR_INVALID_STATE`), a `buyer_franchisee_id` that references a franchisee in `APPROVED` or `ACTIVE` status (else `ERR_FRANCHISEE_NOT_APPROVED`), and that no royalty statement of any of the seller franchisee's units is `OVERDUE` (else `ERR_OUTSTANDING_OBLIGATIONS`). On success the system computes the transfer fee (the formula appears in §3.9), returns that amount in the response without persisting it on the agreement, creates a successor `FranchiseAgreement` in `EXECUTED` status under the buyer, and sets the original agreement's `successor_agreement_id`. The transfer also reassigns the seller's holdings to the buyer: every unit of the seller franchisee has its `franchisee_id` changed to the buyer, and every territory the seller held has its `assigned_franchisee_id` changed to the buyer.

Declining renewal moves the agreement `RENEWAL_PENDING → TERMINATED`. It requires only that the agreement be `RENEWAL_PENDING` (else `ERR_INVALID_STATE`). On success every territory held by the franchisee is released — its `assigned_franchisee_id` reset to null and its `status` returned to `AVAILABLE`.

Agreements are listable and filterable by brand, by `franchisee_id`, by `successor_agreement_id` (to find the predecessor that points at a given successor), and by `status`.

### 3.4. Development Schedules

When a franchisee commits to building out multiple units, the franchisor records a `DevelopmentSchedule` for that franchisee carrying `required_units` (the total number of units committed to, which must be at least 1, else `ERR_INVALID_REQUEST`) and a `deadline_period_index` (the brand period by which all required units must be operationally `OPEN`). The schedule tracks `opened_units`, a computed count of the franchisee's units currently in operational `OPEN`, which starts at 0. A new schedule begins in `status` `ON_TRACK`.

The schedule's status evolves as a function of `opened_units` against `required_units` and the brand clock against `deadline_period_index`. When `opened_units` reaches or exceeds `required_units` — recomputed each time one of the franchisee's units is opened — the schedule moves to `SATISFIED`, whether it was previously `ON_TRACK` or `BEHIND`. Separately, during a period close, if the brand's `current_period_index` has reached or passed `deadline_period_index` while `opened_units` remains below `required_units`, an `ON_TRACK` schedule moves to `BEHIND`. From `BEHIND`, the franchisor may declare a breach, moving the schedule `BEHIND → BREACHED`; this requires the schedule to be `BEHIND` (else `ERR_INVALID_STATE`) and the brand's `current_period_index` to be strictly greater than `deadline_period_index` (else `ERR_DEADLINE_NOT_PASSED`). Declaring a breach has a consequence for the operator: if the owning franchisee is `ACTIVE`, it is moved to `DEFAULTED`. The terminal statuses of a development schedule are `SATISFIED` and `BREACHED`. Schedules are listable and filterable by brand, by `franchisee_id`, and by `status`.

### 3.5. The Unit's Two Lives: Operations and Compliance

A `Unit` is the physical restaurant. It is created — by either the franchisor or the owning franchisee — under a `franchisee_id`, sited in a `territory_id`, at a street `address`. A unit carries the rest of its lineage in `brand_id`. Crucially, a unit lives two independent lives on the same record: an operational dimension in `operational_status` and a compliance dimension in `compliance_status`. The two never disturb one another — an operational transition leaves compliance untouched and vice versa. A unit also exposes two computed read-outs: `latest_audit_score`, the capped overall score of its most recent finalized audit (null until one exists), and `lifetime_net_sales_cents`, the running sum of net sales across all of its accepted sales reports (starting at 0). On creation, `operational_status` is `PLANNED` and `compliance_status` is `GOOD_STANDING`.

The **operational** dimension runs `PLANNED → OPEN → CLOSED`. Opening a planned unit — an action available to the owning franchisee or the franchisor — requires three conditions: the unit must currently be operationally `PLANNED` (else `ERR_INVALID_STATE`); the owning franchisee must be in `APPROVED` or `ACTIVE` status (else `ERR_FRANCHISEE_NOT_APPROVED`); and the unit's `territory_id` must reference a territory whose `status` is `ASSIGNED` and whose `assigned_franchisee_id` equals the unit's franchisee (else `ERR_TERRITORY_NOT_HELD`). Opening a unit triggers two side effects: if the owning franchisee is still `APPROVED`, it is promoted `APPROVED → ACTIVE`; and the owning franchisee's development schedule has its `opened_units` recomputed and its status re-evaluated (advancing it to `SATISFIED` when `opened_units` reaches `required_units`). Closing an open unit — again available to franchisee or franchisor — requires the unit to be operationally `OPEN` (else `ERR_INVALID_STATE`) and that no royalty statement of the unit is `OVERDUE` (else `ERR_OUTSTANDING_OBLIGATIONS`); on success the owning franchisee's development schedule has its `opened_units` recomputed and its status re-evaluated.

The **compliance** dimension cycles among `GOOD_STANDING`, `PROBATION`, and `SUSPENDED`, and is driven almost entirely by audit outcomes (detailed in §3.7) plus one manual recovery step. The audit-driven transitions are these: a finalized audit graded `CONDITIONAL` moves a unit from `GOOD_STANDING` to `PROBATION`; a finalized audit graded `FAIL` moves a unit from either `GOOD_STANDING` or `PROBATION` to `SUSPENDED`; and a finalized audit graded `PASS` moves a unit from `PROBATION` back to `GOOD_STANDING`. Whenever a unit enters `SUSPENDED`, the owning franchisee's `open_compliance_strikes` is incremented by one; if that count reaches 2 and the franchisee is `ACTIVE`, the franchisee is moved `ACTIVE → DEFAULTED`. The single manual compliance step is reinstatement, covered next in §3.6. Units are listable and filterable by brand, by `franchisee_id`, by `territory_id`, by `operational_status`, and by `compliance_status`.

### 3.6. Reinstatement and Recovery from Default

A suspended unit does not recover automatically. The franchisor must reinstate it, which moves the unit's `compliance_status` from `SUSPENDED` to `PROBATION`. Reinstatement requires the unit to currently be `SUSPENDED` (else `ERR_INVALID_STATE`) and demands evidence of completed remediation: there must exist a finalized audit for the unit whose grade is not `FAIL`, created after the audit that caused the suspension. If no such qualifying remediation audit exists, reinstatement is rejected with `ERR_REMEDIATION_INCOMPLETE`. Note that the compliance-block rule also governs reinstatement and agreement renewal: a request to reinstate without a passing post-suspension remediation audit, or to renew an agreement while any of the franchisee's units is `SUSPENDED`, surfaces as `ERR_COMPLIANCE_BLOCK` for the renewal case.

Reinstatement reverses the strike that suspension imposed: the owning franchisee's `open_compliance_strikes` is decremented by one, and if that count drops below 2 while the franchisee is `DEFAULTED`, the franchisee recovers `DEFAULTED → ACTIVE`. This is the mirror of the suspension cascade — a franchisee that defaulted because two of its units were suspended climbs back to active standing as those units are remediated and reinstated below the two-strike threshold.

### 3.7. Brand-Standard Audits and Scoring

A `BrandAudit` is how the brand polices standards at a unit. The compliance auditor schedules an audit for a unit (`unit_id`), which begins in `SCHEDULED`. A unit may carry at most one audit in an active phase at a time: if the unit already has an audit in `SCHEDULED` or `IN_PROGRESS`, scheduling another is rejected with `ERR_AUDIT_IN_PROGRESS`. The audit then advances `SCHEDULED → IN_PROGRESS → FINALIZED`, and from `FINALIZED` either directly to `CLOSED` or through a `REMEDIATION` loop back to `CLOSED`.

Starting an audit (`SCHEDULED → IN_PROGRESS`) requires the audit to be `SCHEDULED` (else `ERR_INVALID_STATE`) and the target unit to be operationally `OPEN` (else `ERR_UNIT_NOT_OPEN`). Finalizing an audit (`IN_PROGRESS → FINALIZED`) requires the audit to be `IN_PROGRESS` (else `ERR_INVALID_STATE`) and that all four section scores — `food_safety_score`, `cleanliness_score`, `service_score`, and `brand_compliance_score` — are supplied at finalize time, each an integer in the range 0 through 100 inclusive (else `ERR_INVALID_REQUEST`).

Finalizing computes three values. First, the `weighted_score` is the sum of the four section scores each multiplied by its weight — the food-safety score weighted at 0.40, the cleanliness score at 0.25, the service score at 0.20, and the brand-compliance score at 0.15 — with that sum rounded half up to one decimal place. Second, the `overall_score` applies a critical-failure cap: if `food_safety_score` is below 70, the overall score is the smaller of the weighted score and 59.0; otherwise the overall score equals the weighted score. The rounding to one decimal place is performed on the weighted score before the cap and grade banding are applied. Third, the `grade` is derived from the overall score: it is `PASS` when the overall score is at least 90.0, `CONDITIONAL` when the overall score is at least 70.0 but below 90.0, and `FAIL` otherwise (any overall score below 70.0).

Finalizing then cascades into the unit's compliance dimension and writes `latest_audit_score`. The unit's `latest_audit_score` is set to the audit's `overall_score`. If the grade is `CONDITIONAL` and the unit is in `GOOD_STANDING`, the unit moves `GOOD_STANDING → PROBATION`. If the grade is `FAIL`, the unit moves from `GOOD_STANDING` or `PROBATION` to `SUSPENDED`, incrementing the franchisee's strikes and possibly defaulting the franchisee as described in §3.5. If the grade is `PASS` and the unit is in `PROBATION`, the unit moves `PROBATION → GOOD_STANDING`.

After finalization, a remediation case may be opened, moving the audit `FINALIZED → REMEDIATION`; this requires the audit to be `FINALIZED` (else `ERR_INVALID_STATE`) and its grade to be `CONDITIONAL` or `FAIL` (else `ERR_NO_REMEDIATION_NEEDED`, since a passing audit needs no remediation). Closing an audit moves it to `CLOSED` and follows two distinct paths. A `FINALIZED` audit may close directly only when its grade is `PASS`; closing a `FINALIZED` audit whose grade is not `PASS` is rejected with `ERR_INVALID_STATE`, because conditional and failing audits must route through remediation. A `REMEDIATION` audit may close only once a later finalized audit exists for the same unit whose grade is not `FAIL`; if no such subsequent audit exists, the close is rejected with `ERR_REMEDIATION_INCOMPLETE`. Audits are listable and filterable by brand, by `unit_id`, by `status`, and by `grade`.

### 3.8. POS Sales, Acceptance, and the Royalty Settlement

Revenue enters the system as `SalesReport` records. A report may be ingested by the owning franchisee, the franchisor, or the automated `System` polling identity. Each report names its `unit_id` and the `period_index` it covers, and carries `gross_sales_cents` (gross point-of-sale revenue for the period, which must be at least 0), `discounts_cents` (comps and discounts to subtract, default 0, which must be at least 0 and no greater than `gross_sales_cents`), and a `source` (default `POS_POLL`, or alternatively `MANUAL`). A report's `period_index` must equal the brand's `current_period_index` — a closed period cannot be reported against — and a mismatch is rejected with `ERR_PERIOD_CLOSED`. On ingestion the system computes `net_sales_cents` as the gross sales minus the discounts, floored at 0 so it is never negative, and the report enters `status` `POLLED`. Sales reports form an append-only event log whose statuses are `POLLED`, `ACCEPTED`, and `AMENDED`.

A polled report does not yet count toward royalty. The franchisor or a finance clerk accepts a report, moving it `POLLED → ACCEPTED`, which causes the owning unit's `lifetime_net_sales_cents` to be recomputed as the sum of `net_sales_cents` over all of that unit's accepted reports. Only `ACCEPTED` reports form the royalty basis; `POLLED` and `AMENDED` reports are excluded. Sales reports are listable and filterable by brand, by `unit_id`, by `period_index`, and by `status`.

A `RoyaltyStatement` settles one unit for one period. The franchisor or a finance clerk creates a draft statement for a `unit_id` and a `period_index`; it begins in `status` `DRAFT` with its `due_period_index` set to that period index plus one. The statement accumulates several computed amounts: `net_sales_basis_cents` (the basis), `royalty_cents`, `ad_fund_cents`, `late_fee_cents`, `total_due_cents`, and `amount_paid_cents`, all defaulting to 0. A statement progresses `DRAFT → ISSUED → PAID`, with `OVERDUE` and a terminal `WRITTEN_OFF` as additional fates.

Issuing a statement (a finance-clerk action) moves it `DRAFT → ISSUED` and requires the statement to be `DRAFT` (else `ERR_INVALID_STATE`) and at least one `ACCEPTED` sales report to exist for the statement's unit and period (else `ERR_NO_SALES_BASIS`). Issuing recomputes the statement's figures. The `net_sales_basis_cents` is the sum of `net_sales_cents` over the `ACCEPTED` sales reports for that unit and `period_index`. The `royalty_cents` is the tiered royalty on that basis, and `ad_fund_cents` is the ad-fund contribution on the same basis (both formulas appear in §3.9). The `total_due_cents` is the sum of `royalty_cents`, `ad_fund_cents`, and `late_fee_cents`.

Recording a payment against a statement is a finance-clerk action permitted while the statement is `ISSUED` or `OVERDUE` (else `ERR_INVALID_STATE`). A payment carries `amount_cents`, which is added to the statement's `amount_paid_cents`. If the cumulative `amount_paid_cents` reaches or exceeds `total_due_cents`, the statement moves to `PAID`; otherwise the statement stays in whatever status it was in (still `ISSUED` or still `OVERDUE`) with the partial payment recorded. Royalty statements are listable and filterable by brand, by `unit_id`, by `period_index`, and by `status`.

### 3.9. The Money: Royalty, Ad-Fund, Late Fees, Transfers, and Rebates

The **royalty** on a statement is computed by marginal tiers on its `net_sales_basis_cents`, never as a single blended rate on the whole basis. The first $50,000 of basis — that is, the first 5,000,000 cents — is charged at the brand's `royalty_tier_1_rate`. The portion of the basis above 5,000,000 cents and up to $100,000 (10,000,000 cents) is charged at `royalty_tier_2_rate`. Any portion of the basis above 10,000,000 cents is charged at `royalty_tier_3_rate`. The three tier contributions are summed first, and the single summed total is then rounded half up to whole cents to yield `royalty_cents` — rounding is applied once to the summed marginal total, not separately per tier.

The **ad-fund** contribution is simpler: `ad_fund_cents` is the `net_sales_basis_cents` multiplied by the brand's `ad_fund_rate`, rounded half up to whole cents.

The **late fee** accrues on an overdue statement and comes in two variants that differ once a statement is more than one period overdue. In both, the principal the fee accrues on is the sum of `royalty_cents` and `ad_fund_cents` — the obligation principal, excluding any prior late fee — and the number of whole periods past due, the months-late count, is the brand's `current_period_index` minus the statement's `due_period_index` (at least 1 once overdue). The monthly rate is the brand's `late_fee_monthly_rate`. The **provisional** variant is applied when a statement auto-transitions to `OVERDUE` during a period close: here `late_fee_cents` is the principal multiplied by the monthly rate multiplied by the months-late count, rounded half up to whole cents — a simple linear accrual with no compounding. The **final** variant is applied when an overdue statement is written off: here `late_fee_cents` is the principal multiplied by the quantity (one plus the monthly rate, raised to the power of the months-late count, then minus one), rounded half up to whole cents — a compound accrual that diverges upward from the simple variant once the months-late count is 2 or more. In each variant the rounding is applied once to the computed fee, and `total_due_cents` is recomputed to include the resulting `late_fee_cents`.

The **transfer fee** is computed when an agreement transfers. It begins from a trailing basis: the sum, over all of the seller franchisee's units, of the `net_sales_basis_cents` of every royalty statement whose `period_index` falls in the inclusive window from the brand's `current_period_index` minus 12 through `current_period_index` minus 1, and whose status is any of `ISSUED`, `OVERDUE`, `PAID`, or `WRITTEN_OFF` (any issued statement counts). The percentage component is that trailing basis multiplied by the agreement's `transfer_fee_rate`, rounded half up to whole cents; the base fee is the larger of that rounded percentage component and a flat floor of $10,000 (1,000,000 cents). The final transfer fee is the base fee plus a training fee of $5,000 (500,000 cents) when the buyer's `is_existing_operator` is false, or the base fee alone when the buyer is already an existing operator. The rounding of the percentage component happens before the floor is applied and before the training fee is added.

The **rebate distribution** allocates a national account's pool across qualifying units. A `NationalAccount` is created with a `brand_id`, the `vendor_id` of the vendor funding the rebate, a program `name`, a `rebate_pool_cents` (the total pool to distribute, at least 0), and a `min_qualifying_cents` (default 1,000,000 cents, the minimum quarterly purchase a unit must have made to share). It begins in `status` `OPEN`. Distribution (a finance-clerk action, OCC-guarded per §2.8) moves it `OPEN → DISTRIBUTED`. The eligible set is the vendor authorizations for this account's vendor whose `qualifying_purchase_cents` is at least the account's `min_qualifying_cents` and whose `status` is `ACTIVE`. Let the total qualifying be the sum of `qualifying_purchase_cents` over the eligible set; if that total is 0, every unit receives 0 and no distribution occurs. Otherwise each eligible authorization's raw share is the pool times that authorization's `qualifying_purchase_cents` divided by the total qualifying, floored to whole cents. Because flooring leaves a remainder, the leftover cents — the pool minus the sum of all raw shares — are then handed out one cent at a time, iterating over the eligible authorizations ordered by `qualifying_purchase_cents` descending and breaking ties by `created_at` ascending (never by id), cycling through that order until the remainder is exhausted. National accounts are listable and filterable by brand, by `vendor_id`, and by `status`.

### 3.10. Approved-Vendor Compliance and Authorizations

A `Vendor` is a supplier created by the franchisor or a compliance auditor with a `brand_id`, a `name`, and a `category` that is one of `FOOD`, `PACKAGING`, `EQUIPMENT`, or `SERVICES`. A new vendor begins with `approval_status` `PENDING`. A compliance auditor may approve a vendor (`approval_status` `PENDING → APPROVED`) or revoke it (`approval_status → REVOKED`). Revoking a vendor cascades: every `VendorAuthorization` for that vendor currently in `ACTIVE` status is set to `DISABLED`. Vendors are listable and filterable by brand, by `category`, and by `approval_status`.

A `VendorAuthorization` is a unit's permission to source from a vendor — the junction between a unit and a vendor. It is created by the owning franchisee or the franchisor with a `unit_id`, a `vendor_id`, and an optional `qualifying_purchase_cents` (default 0, the unit's purchases from this vendor this quarter, which feed the national-account rebate). An authorization may only reference a vendor whose `approval_status` is `APPROVED`; referencing a vendor that is not approved is rejected with `ERR_VENDOR_NOT_APPROVED`. A new authorization begins `ACTIVE`, and may be `DISABLED` as described above. Vendor authorizations are listable and filterable by brand, by `unit_id`, by `vendor_id`, and by `status`.

### 3.11. Closing a Period

The franchisor or a finance clerk advances the brand clock through the period-close operation, which increments the brand's `current_period_index` by one and runs a set of cascades over the brand's records. Every `ISSUED` royalty statement that is now past due — meaning the brand's `current_period_index` has moved beyond the statement's `due_period_index` — and that has not been fully paid (its `amount_paid_cents` remains below its `total_due_cents`) is moved `ISSUED → OVERDUE`, with its `late_fee_cents` recomputed using the simple provisional variant and its `total_due_cents` recomputed to include that fee. Every development schedule that is now past its `deadline_period_index` with `opened_units` still below `required_units` is moved `ON_TRACK → BEHIND`. The period close also increments the brand's `version` by one, which is why it can invalidate an `expected_brand_version` that a distribute or write-off client captured earlier (see §2.8).

## 4. Endpoint Definitions

All endpoints are mounted under the `/franchise` prefix (with the sole exception of the administrative clock capability). Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or read a resource return HTTP 200. Request bodies, response shapes, and side effects are described in the §3 narratives; the table below lists only the routing surface and authorization.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /franchise/brands | Create a brand | Franchisor |
| GET | /franchise/brands/{brandId} | Get a brand | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/brands/{brandId}/close-period | Advance the brand clock and run period-close cascades | Franchisor, FinanceClerk |
| POST | /_clock/set_current_utc | Test-driving: set the brand logical clock to an explicit instant | Franchisor |
| POST | /franchise/territories | Create a territory | Franchisor |
| GET | /franchise/territories/{territoryId} | Get a territory | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/territories | List territories | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/territories/{territoryId}/assign | Assign a territory to a franchisee | Franchisor |
| POST | /franchise/franchisees | Create a franchisee | Franchisor |
| GET | /franchise/franchisees/{franchiseeId} | Get a franchisee | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/franchisees | List franchisees | Franchisor, ComplianceAuditor, FinanceClerk |
| POST | /franchise/franchisees/{franchiseeId}/approve | Approve an applicant franchisee | Franchisor |
| POST | /franchise/franchisees/{franchiseeId}/terminate | Terminate a franchisee | Franchisor |
| POST | /franchise/agreements | Create a draft agreement | Franchisor |
| GET | /franchise/agreements/{agreementId} | Get an agreement | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/agreements | List agreements | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/agreements/{agreementId}/execute | Execute a draft agreement | Franchisor |
| POST | /franchise/agreements/{agreementId}/begin-renewal | Open the renewal window | Franchisor |
| POST | /franchise/agreements/{agreementId}/renew | Renew the agreement, creating a successor | Franchisor |
| POST | /franchise/agreements/{agreementId}/transfer | Transfer the franchise to a buyer | Franchisor |
| POST | /franchise/agreements/{agreementId}/decline-renewal | Decline renewal and terminate | Franchisor |
| POST | /franchise/development-schedules | Create a development schedule | Franchisor |
| GET | /franchise/development-schedules/{scheduleId} | Get a development schedule | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/development-schedules | List development schedules | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/development-schedules/{scheduleId}/declare-breach | Declare a development breach | Franchisor |
| POST | /franchise/units | Create a planned unit | Franchisor, Franchisee |
| GET | /franchise/units/{unitId} | Get a unit | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/units | List units | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/units/{unitId}/open | Open a planned unit | Franchisee, Franchisor |
| POST | /franchise/units/{unitId}/close | Close an open unit | Franchisee, Franchisor |
| POST | /franchise/units/{unitId}/reinstate | Reinstate a suspended unit after remediation | Franchisor |
| POST | /franchise/sales-reports | Ingest a POS sales report | Franchisee, Franchisor, System |
| POST | /franchise/sales-reports/{salesReportId}/accept | Accept a polled sales report into the royalty basis | Franchisor, FinanceClerk |
| GET | /franchise/sales-reports/{salesReportId} | Get a sales report | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/sales-reports | List sales reports | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/royalty-statements | Create a draft royalty statement | FinanceClerk, Franchisor |
| GET | /franchise/royalty-statements/{statementId} | Get a royalty statement | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/royalty-statements | List royalty statements | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/royalty-statements/{statementId}/issue | Issue a statement; compute royalty and ad-fund | FinanceClerk |
| POST | /franchise/royalty-statements/{statementId}/payments | Record a payment against a statement | FinanceClerk |
| POST | /franchise/royalty-statements/{statementId}/write-off | Write off an overdue statement; finalize compound late fee | FinanceClerk |
| POST | /franchise/vendors | Create a vendor (pending approval) | Franchisor, ComplianceAuditor |
| GET | /franchise/vendors/{vendorId} | Get a vendor | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/vendors | List vendors | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/vendors/{vendorId}/approve | Approve a vendor | ComplianceAuditor |
| POST | /franchise/vendors/{vendorId}/revoke | Revoke a vendor's approval | ComplianceAuditor |
| POST | /franchise/vendor-authorizations | Authorize a unit to source from an approved vendor | Franchisee, Franchisor |
| GET | /franchise/vendor-authorizations/{authorizationId} | Get a vendor authorization | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/vendor-authorizations | List vendor authorizations | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/audits | Schedule a brand-standard audit | ComplianceAuditor |
| GET | /franchise/audits/{auditId} | Get an audit | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/audits | List audits | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| POST | /franchise/audits/{auditId}/start | Begin an audit on an open unit | ComplianceAuditor |
| POST | /franchise/audits/{auditId}/finalize | Finalize an audit with section scores | ComplianceAuditor |
| POST | /franchise/audits/{auditId}/open-remediation | Open a remediation case | ComplianceAuditor |
| POST | /franchise/audits/{auditId}/close | Close an audit | ComplianceAuditor |
| POST | /franchise/national-accounts | Create a national-account rebate program | Franchisor, FinanceClerk |
| GET | /franchise/national-accounts/{accountId} | Get a national account | Franchisor, ComplianceAuditor, Franchisee, FinanceClerk |
| GET | /franchise/national-accounts | List national accounts | Franchisor, ComplianceAuditor, FinanceClerk |
| POST | /franchise/national-accounts/{accountId}/distribute | Distribute the rebate pool across qualifying units | FinanceClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_FRANCHISEE_NOT_APPROVED | 409 |
| ERR_FRANCHISEE_HAS_OPEN_UNITS | 409 |
| ERR_TERRITORY_NOT_HELD | 409 |
| ERR_TERRITORY_CONFLICT | 409 |
| ERR_PERIOD_CLOSED | 409 |
| ERR_VENDOR_NOT_APPROVED | 409 |
| ERR_NO_SALES_BASIS | 409 |
| ERR_OUTSTANDING_OBLIGATIONS | 409 |
| ERR_COMPLIANCE_BLOCK | 409 |
| ERR_REMEDIATION_INCOMPLETE | 409 |
| ERR_NO_REMEDIATION_NEEDED | 409 |
| ERR_UNIT_NOT_OPEN | 409 |
| ERR_RENEWAL_WINDOW_CLOSED | 409 |
| ERR_DEADLINE_NOT_PASSED | 409 |
| ERR_AUDIT_IN_PROGRESS | 409 |
| ERR_STALE_VERSION | 412 |
