# Carbon Emission Trading API — Product Requirements Document

## 1. Introduction

The Carbon Emission Trading platform operates the regulated lifecycle of an enterprise's carbon obligations from quota allocation through annual settlement. Every regulated enterprise enters a yearly compliance cycle in which a regulator first issues a free-and-paid quota allocation (computed either from an industry benchmark or from a historical baseline), then receives an emission report whose data are cross-checked by an independent verifier, then accepts a compliance declaration in which the enterprise retires quota and CCER credits to cover its verified emissions, and finally is reconciled in an annual settlement that may carry surplus forward, repurchase excess, or demand a deficit purchase. Trading sits in parallel: enterprises buy and sell quota and CCER credits through an order book with price-time priority, with block and over-the-counter channels supported.

The system has three distinct user roles whose actions interlock through scheduled deadlines and event-driven cascades. A regulator drives cycle-level state changes and adjudicates objections and disputes; an enterprise files reports, places orders, and submits compliance; an independent verification agency cross-checks reported emissions and issues authoritative verification reports. The benchmark exercises the full happy path, the deadline-window failures, the concurrency conflicts, and the cascading side effects across allocation, trading, compliance, penalty, and settlement workflows.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` (identifying the acting principal) and `X-User-Role` (one of three exact values: `Regulator`, `Enterprise`, `VerifierAgency`). A request missing either header, or with either header empty, is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). A request whose role is not authorized for the requested endpoint per the RBAC matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403). When an enterprise-acting principal targets a resource owned by another enterprise, the request is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

The semantics of `X-User-ID` depend on the role:

- When `X-User-Role` is `Enterprise`, `X-User-ID` is the `id` of the acting `Enterprise` entity. Ownership checks on any resource that references an `Enterprise` (such as `EmissionReport`, `ComplianceDeclaration`, `PenaltyOrder`, `TradingOrder`, `Allocation`, or `AnnualSettlement` via its `enterprise_id` field) compare the resource's foreign-key reference to `X-User-ID`.
- When `X-User-Role` is `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on audit log entries but does not compare it to any entity's `id`.
- When `X-User-Role` is `VerifierAgency`, `X-User-ID` is likewise an opaque operator identifier; for verification-assignment operations it must equal the `agency_id` recorded on the `VerificationAssignment`, which is how the server constrains a verifier to act only on its own assignments.

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

List endpoints support two query-string parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). Results are sorted by `created_at` ascending unless an endpoint specifies otherwise. The pagination block in `meta` exposes the four fields `limit`, `offset`, `total_count`, and `has_more`; the `has_more` flag is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Most entities — namely `Enterprise`, `AllocationCycle`, `Allocation`, `EmissionReport`, `VerificationAssignment`, `TradingOrder`, `ComplianceDeclaration`, `PenaltyOrder`, and `AnnualSettlement` — carry four system-managed common fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set at insertion, while `updated_at` advances on every mutation that changes a persisted attribute, including cascaded mutations from a parent transition. The `version` field is an integer that starts at 1 on creation and is incremented by exactly one on every persisted mutation, including cascaded ones.

Two entities are intentionally lighter. `Objection`, `EmissionDataLine`, `SupportingDocument`, `Trade`, and `AuditLogEntry` carry only `id` and `created_at`; they have neither `updated_at` nor `version`, because each is either an immutable event or a leaf record updated only by direct cascade. Note that `EmissionReport` carries its own domain-level `version` integer that tracks the resubmission sequence per `(enterprise, cycle_year)`; this domain `version` is the same field used for optimistic concurrency control and starts at 1, advancing by one on each resubmission.

For optimistic concurrency control, every endpoint that modifies a versioned resource accepts an optional `version` field in its request body. When supplied, the server compares it to the resource's current `version`; on mismatch the request is rejected with `ERR_STALE_VERSION` (HTTP 409). When omitted, the server skips the check and proceeds. After a successful mutation, the server returns the new resource with its incremented `version`.

### 2.5. Nested Resource Resolution

Endpoints with multi-segment paths resolve their path parameters left to right. If any segment fails to resolve to an existing entity, the request is rejected with `ERR_NOT_FOUND` (HTTP 404), and the message identifies the first segment that failed. For example, posting an objection requires the path's `Allocation` `id` to resolve before the body's `filer_enterprise_id` is examined.

### 2.6. Numerical Precision and Rounding

All monetary, quota, and emission quantities are persisted and returned with exactly two decimal places. The default rounding mode is **round half up** (a halfway case rounds away from zero). Several calculations pin the order of rounding (round per-line first, then sum) — those orderings are spelled out in the workflow narratives in §3 and must not be reversed.

### 2.7. Cascade and Audit Semantics

The platform models a "saga" of compliance state. Several operations cascade across multiple entities in a single request: publishing a cycle propagates state into every allocation in the cycle; finalizing a cycle propagates state into every allocation and into every receiving enterprise's balances; submitting a compliance declaration retires balances on the declarer enterprise; settlement creates an annual-settlement record per enterprise. Every such cascade refreshes `updated_at` and bumps `version` on each entity it mutates. Quota-affecting mutations and trade executions also append an `AuditLogEntry`, with its `subject_type`, `subject_id`, `enterprise_id`, `action`, `delta_quota`, `delta_ccer`, `external_system`, and `occurred_at` fields populated according to the cascading workflow. The `subject_type` enumeration is exactly `QUOTA_CHANGE`, `TRADE_RECORD`, or `EXTERNAL_SYNC`; `external_system` is one of `BANK`, `REGULATOR`, `ENERGY_DATA`, or null when no external system was involved.

### 2.8. Validation Priority Order

When multiple validations could reject a single request, they are evaluated in a fixed priority order. First the system enforces presence of `X-User-ID` and `X-User-Role` (`ERR_AUTH_REQUIRED`). Second, role authorization per the RBAC matrix (`ERR_FORBIDDEN`). Third, path-resource existence in left-to-right order (`ERR_NOT_FOUND`). Fourth, target-resource state validity (`ERR_INVALID_STATE`). Fifth, ownership of the target resource by the acting enterprise (`ERR_OWNERSHIP_VIOLATION`). Sixth, the verifier conflict-of-interest check (`ERR_VERIFIER_CONFLICT_OF_INTEREST`). Seventh, business temporal windows (`ERR_WINDOW_CLOSED`). Then in order: supporting-document presence (`ERR_SUPPORTING_DOCUMENT_REQUIRED`), CCER cap (`ERR_CCER_CAP_EXCEEDED`), borrow cap (`ERR_BORROW_CAP_EXCEEDED`), balance sufficiency (`ERR_INSUFFICIENT_BALANCE`), order shape (`ERR_INVALID_ORDER`), and ratio bounds (`ERR_INVALID_RATIO`). Last, the optimistic concurrency check (`ERR_STALE_VERSION`). Generic structural input violations (missing required fields, type mismatches) surface as `ERR_INVALID_INPUT` (HTTP 422). This ordering means that, for instance, an unauthenticated request to a state-conflicting endpoint surfaces the auth error rather than the state error.

### 2.9. Concurrency Guarantees

Several endpoints serialize concurrent operations on the same target. Two simultaneous `SELL` orders against the same seller's quota balance are serialized first-writer-wins by `placed_at`; the matching engine validates available balance immediately before each fill, and a second match attempt that would push balance below zero is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 409). Two trade settlements that race on the same enterprise's balance are likewise serialized first-writer-wins on the trade's settlement-status mutation, and the loser receives `ERR_INSUFFICIENT_BALANCE`. Two objection filings on the same allocation are serialized first-writer-wins on the objection's `filed_at`; only one may be in `PENDING` state at a time, and the second is rejected with `ERR_OBJECTION_ALREADY_PENDING` (HTTP 409). Two compliance-declaration submissions for the same enterprise and cycle year are serialized first-writer-wins on submission, and the second receives `ERR_DECLARATION_ALREADY_SUBMITTED` (HTTP 409). A penalty payment that races with the system's overdue marker is serialized first-writer-wins on the order's payment-status mutation: if the payment lands first the order becomes `PAID`; if the overdue marker fires first the payment is rejected with `ERR_PENALTY_OVERDUE` (HTTP 409). Cycle-level transitions (publish racing with finalize, for example) linearize on the `AllocationCycle` status, and the second action sees the new state and is rejected with `ERR_INVALID_STATE`.

### 2.10. Time, Sweeps, and External Events

The platform exposes test-driver capabilities for moving the system clock forward, running periodic sweeps, and emitting synthetic external events. A clock-advance capability sets the server's `now()` to a supplied `target_timestamp` and responds with the new clock value; it does **not** implicitly run the sweep. A sweep capability scans for past-due penalty orders and other deadline-driven transitions and applies them, returning a `swept_count`. An event-emission capability appends an audit log entry (`subject_type` `EXTERNAL_SYNC`) for synthetic incoming events from the `BANK`, `REGULATOR`, or `ENERGY_DATA` external systems, accepting `external_system`, `event_type`, and `payload` in the request body. When `event_type` is `BANK_PAYMENT_CONFIRMED` and `payload.penalty_id` resolves to an unpaid penalty order, the event is idempotent: a duplicate event with the same `event_id` does not double-apply.

## 3. Business Logic & Workflows

### 3.1. Enterprise Onboarding and Cycle Setup

A regulator creates each enterprise with a payload containing `legal_name`, `jurisdiction_code` (one of `JD_ALPHA`, `JD_BETA`, or `JD_GAMMA`), `industry_code` (one of `POWER`, `STEEL`, `CEMENT`, `CHEMICAL`, or `PETROCHEMICAL`), and a `contact_email` used for objection-window and compliance notices. The newly-registered enterprise begins with `account_status` set to `PENDING`, with `quota_balance`, `paid_quota_balance`, and `ccer_balance` all initialized to zero. Over the enterprise's lifecycle, `account_status` may take any of the values `PENDING`, `OPEN`, `RESTRICTED`, or `CLOSED` (the `RESTRICTED` value is reserved for an enterprise whose account has been administratively constrained). The account is not opened for trading or compliance until the first cycle in which the enterprise receives an allocation transitions to `FINALIZED`.

The compliance year itself is modeled by an `AllocationCycle`. A regulator opens a cycle by supplying a `cycle_year` (which must be unique across all cycles), the `free_paid_ratio` (the fraction of allocation issued as free quota; the remainder is paid auction), the `ccer_cap_pct` (the maximum CCER share usable for offset, expressed as a fraction of verified emissions), the `objection_deadline`, and the `compliance_deadline`. The cycle is created with its `status` field set to `DRAFT` and with `publication_date` and `settlement_date` initially null. The free-paid ratio must lie between 0.0 and 1.0 inclusive, and the CCER cap must lie between 0.0 and 0.20 inclusive; values outside either range are rejected with `ERR_INVALID_RATIO`.

### 3.2. Allocation Computation, Publication, and Objection

Within a `DRAFT` cycle, the regulator proposes one `Allocation` per participating enterprise. The proposal payload includes `enterprise_id`, the chosen `method` (`INDUSTRY_BENCHMARK` or `HISTORICAL_EMISSION`), and the method-specific inputs: `activity_volume` and `benchmark_factor` for the benchmark variant, or `historical_baseline` for the historical variant. Proposals are persisted in status `PROPOSED`; their `total_quota`, `free_quota`, and `paid_quota` are not yet computed (they are computed at publish time).

When the regulator publishes the cycle, the cycle transitions from `DRAFT` to `PUBLISHED`, and immediately auto-transitions to `OBJECTION_OPEN` provided the current time is before the cycle's `objection_deadline` (the `OBJECTION_OPEN` state reflects an open objection window). Publication is permitted only when every allocation in the cycle is in `PROPOSED` status and both the free-paid ratio and CCER cap have been set; otherwise the request is rejected with `ERR_INVALID_STATE`. As a side effect, every `Allocation` cascades from `PROPOSED` to `PUBLISHED`, and for each one the system computes `total_quota`, `free_quota`, and `paid_quota` according to the dual-variant allocation rule. The cycle's `publication_date` is set to the current time. An audit log entry of action `ALLOCATIONS_PUBLISHED` is appended.

The dual-variant allocation rule is as follows. For an industry-benchmark allocation, the total quota is the activity volume multiplied by the benchmark factor, rounded half-up to two decimal places. For a historical-emission allocation, the total quota is the historical baseline multiplied by an annual-reduction factor of 0.97 (representing a three-percent annual reduction), rounded half-up to two decimal places. From the total, the free quota is the total multiplied by the cycle's free-paid ratio, rounded half-up to two decimal places, and the paid quota is the total minus the free quota — the paid quota is computed by subtraction (not by independent rounding) so that `free_quota` plus `paid_quota` always equals `total_quota` exactly. The benchmark variant is forward-looking and grows with planned activity volume; the historical variant is backward-looking and is independent of planned activity.

While the cycle is in `OBJECTION_OPEN`, an enterprise that owns an allocation may file an `Objection` against it. The filing payload includes `filer_enterprise_id` and `ground` (the textual reason). The filing is permitted only when the current time is before the parent cycle's objection deadline and when `filer_enterprise_id` equals the allocation's `enterprise_id`; otherwise the request is rejected with `ERR_WINDOW_CLOSED` or `ERR_OWNERSHIP_VIOLATION` respectively. A successful filing creates the objection in status `PENDING` with `filed_at` set to the current time and `resolved_at` null, and transitions the allocation from `PUBLISHED` to `OBJECTED`. At most one objection per allocation may be in `PENDING` state at a time; a second filing is rejected with `ERR_OBJECTION_ALREADY_PENDING`.

A regulator resolves a pending objection by either upholding or rejecting it. Upholding requires a `revised_total_quota` in the request body. The objection moves to `UPHELD` with `resolved_at` set to the current time, and the allocation transitions from `OBJECTED` to `REVISED` with its quota recomputed: the new `free_quota` is the revised total multiplied by the cycle's free-paid ratio (rounded half-up to two decimal places), the new `paid_quota` is the revised total minus the new free quota, and `total_quota` is updated to the revised value. Rejecting an objection takes no body, sets the objection to `REJECTED` with `resolved_at` set to the current time, and returns the allocation from `OBJECTED` back to `PUBLISHED`.

Once the objection deadline has passed and every objection has been resolved, the regulator finalizes the cycle. The cycle transitions from `OBJECTION_OPEN` to `FINALIZED`. As a cascade, every allocation in `PUBLISHED` or `REVISED` state transitions to `FINALIZED`. For each enterprise receiving allocation, the system increases `quota_balance` by that allocation's `free_quota` and `paid_quota_balance` by its `paid_quota`, and transitions `account_status` from `PENDING` to `OPEN` — an audit log entry of action `QUOTA_ALLOCATED` is appended per enterprise with `delta_quota` equal to free plus paid quota. Attempting to finalize before the objection deadline, or while any objection is still `PENDING`, is rejected with `ERR_INVALID_STATE` (and `ERR_WINDOW_CLOSED` for the deadline check).

After finalization, the cycle auto-transitions to `COMPLIANCE_OPEN` once emission reporting begins, signaling that emission reports for the cycle year may be submitted.

### 3.3. Emission Reporting Lifecycle

An enterprise creates an `EmissionReport` for a `cycle_year`. The created report begins in status `DRAFT` with `version` 1 (or one greater than the previous version for the same enterprise and cycle year), `is_current_version` true, `total_reported_emissions` zero, `total_verified_emissions` null, `submitted_at` null, and `supporting_document_count` zero. The system computes `submission_deadline` as the cycle's compliance deadline minus 90 days (the report must be submitted by this time). When a new version is created, the previous version's `is_current_version` is set to false.

The enterprise then attaches `EmissionDataLine` records to the report. Each line specifies a `source_category` (one of `FUEL`, `ELECTRICITY`, `PROCESS`, or `FUGITIVE`), an `activity_data` quantity (e.g., tonnes of fuel or megawatt-hours of electricity), an `emission_factor` (tCO2e per unit of activity), and optionally a `supporting_document_id` referencing a previously uploaded `SupportingDocument`. On line creation the server computes `source_amount` as `activity_data` times `emission_factor` and recomputes the report's `total_reported_emissions`. Until verification finalizes, the line's `verified_amount` remains null. A line whose `source_category` is `FUEL` or `PROCESS` requires a `supporting_document_id`; a line of either category without one is rejected with `ERR_SUPPORTING_DOCUMENT_REQUIRED`.

Supporting documents are uploaded against the report with a payload containing `document_type` (one of `FUEL_INVOICE`, `METER_LOG`, `PROCESS_SHEET`, `EXTERNAL_AUDIT`) and `file_uri`. On upload, `uploaded_at` is recorded and the report's `supporting_document_count` is incremented by one.

The total reported emissions on a report is computed as follows: for each emission data line attached to the report, multiply the line's `activity_data` by its `emission_factor`, round that product half-up to two decimal places, then sum the rounded per-line values. The sum itself is not re-rounded across lines (a sum of two-decimal-place numbers is itself a two-decimal-place number); the explicit per-line round preserves cent-level determinism. **This rounding order is canonical and must not be reversed:** rounding the sum of unrounded `activity_data * emission_factor` products produces different cents and is forbidden.

When the enterprise submits the report, the report transitions from `DRAFT` to `SUBMITTED`, `submitted_at` is set to the current time, and `total_reported_emissions` is recomputed. Submission is permitted only when the parent cycle's status is `COMPLIANCE_OPEN`, the current time is at or before the report's submission deadline, at least one emission data line exists, and every line whose source category is `FUEL` or `PROCESS` carries a `supporting_document_id`. Older versions of the same enterprise-and-cycle-year report have their `is_current_version` set to false. Submitting after the deadline is rejected with `ERR_WINDOW_CLOSED`; missing supporting documents are rejected with `ERR_SUPPORTING_DOCUMENT_REQUIRED`.

A `SUBMITTED` or `REJECTED` report may be resubmitted by the enterprise, which creates a new `DRAFT` report with `version` equal to the previous version plus one for the same `(enterprise, cycle_year)` pair, and sets the previous report's `is_current_version` to false. This is permitted only while the current time remains at or before the submission deadline. The lifecycle is therefore cyclic: `DRAFT` → `SUBMITTED` → `DRAFT` (via versioning).

A regulator may reject a `SUBMITTED` report (for example, when the report violates a template constraint such as a missing `FUEL` supporting document) by supplying a textual `reason`; the report transitions to `REJECTED`, the `is_current_version` flag is left as it was, and the enterprise must submit a new version.

### 3.4. Verification, Dispute, and Finalization

A regulator assigns a verifier by supplying `agency_id` and `scheduled_visit_at`. This transitions the report from `SUBMITTED` to `UNDER_VERIFICATION` and creates a `VerificationAssignment` in status `ASSIGNED` with the supplied scheduled visit timestamp. The assignment's `status` field ranges over the values `ASSIGNED`, `SCHEDULED`, `ON_SITE_DONE`, `REPORT_ISSUED`, `DISPUTED`, and `RESOLVED`; the `SCHEDULED` value is reserved for a future state where the verifier has confirmed the on-site visit calendar entry. Two checks govern this assignment: the visit must be at least 7 days in the future from the time of assignment, otherwise the request is rejected with `ERR_WINDOW_CLOSED`; and the assigned `agency_id` must not equal the `enterprise_id` of the enterprise being verified, otherwise the request is rejected with `ERR_VERIFIER_CONFLICT_OF_INTEREST`.

The verifier records on-site completion by supplying `line_adjustments[]` — a list of `{line_id, verified_amount}` entries representing per-line verifier-adjusted amounts. The assignment moves from `ASSIGNED` to `ON_SITE_DONE` (the scaffold's transition encoding represents this as the `ASSIGNED → ON_SITE_DONE` precondition for issuing the report). Per the verification calculation, each line's `verified_amount` is computed by multiplying `activity_data` by `emission_factor` by `(1 + verifier_adjustment_pct(line.source_category))` and rounding half-up to two decimal places; the report's `total_verified_emissions` is the sum of these rounded line amounts (no extra rounding across lines). The assignment's `cross_check_delta_pct` is computed as the absolute difference between verified and reported totals, divided by the reported total, multiplied by 100, then rounded half-up to two decimal places.

The verifier then issues the verification report, transitioning the assignment from `ON_SITE_DONE` to `REPORT_ISSUED` with `report_issued_at` set to the current time, and the report from `UNDER_VERIFICATION` to `VERIFIED` with `total_verified_emissions` and per-line `verified_amount` written. This is the "final verified" variant of emission totals and is the authoritative input for compliance.

A `VERIFIED` report may be disputed by the enterprise with a payload containing `ground` (the textual reason), but only within 14 days of the assignment's `report_issued_at`; outside that window the request is rejected with `ERR_WINDOW_CLOSED`. Disputing transitions the report from `VERIFIED` to `DISPUTED` and the assignment from `REPORT_ISSUED` to `DISPUTED`. A regulator resolves the dispute, optionally supplying an `adjusted_total_verified_emissions`; the assignment moves from `DISPUTED` to `RESOLVED` and the report returns from `DISPUTED` to `VERIFIED`. The lifecycle supports exactly one such dispute round per assignment.

After the verification report is issued and the 14-day dispute window has either elapsed or the enterprise has waived dispute, a regulator finalizes the report. This requires the assignment to be in `REPORT_ISSUED` or `RESOLVED` status; the report transitions from `VERIFIED` to `FINALIZED` and is locked, serving as the authoritative input for the compliance declaration.

### 3.5. Order Placement, Matching, and Trading Channels

An enterprise places a `TradingOrder` by supplying `enterprise_id` (which must equal the acting `X-User-ID`), `side` (`BUY` or `SELL`), `instrument` (`QUOTA` or `CCER`), `order_type` (`LIMIT` or `MARKET`), `quantity` (the order size in tCO2e, which must be greater than zero), `limit_price` (price per tCO2e for `LIMIT` orders; must be null for `MARKET` orders and greater than zero for `LIMIT` orders), and `channel` (`EXCHANGE`, `BLOCK`, or `OTC`). On creation, the server records `placed_at`, sets `filled_quantity` to zero, and the order begins in status `OPEN`. Order shape violations — non-positive quantity, missing `limit_price` for a `LIMIT` order, or a `limit_price` set for a `MARKET` order — are rejected with `ERR_INVALID_ORDER`. A `SELL` placement whose enterprise lacks sufficient instrument balance at placement time is rejected with `ERR_INSUFFICIENT_BALANCE`.

Matching is attempted immediately. The exchange channel uses price-time priority: orders are matched by best price first, with `placed_at` breaking ties at equal price. A match consuming the full order in a single fill transitions the order from `OPEN` directly to `FILLED`; a partial match transitions it from `OPEN` to `PARTIALLY_FILLED`; once `filled_quantity` reaches `quantity`, the order transitions from `PARTIALLY_FILLED` to `FILLED`. The match price for an exchange limit-order match equals the price of the resting (older) order. The block channel requires explicit counterparty acceptance; if acceptance is absent, the matching attempt rejects the order with status `REJECTED`. The over-the-counter channel settles directly between parties. If a sell-side fill attempt detects the seller's balance is insufficient at match time, the order is rejected (status `REJECTED`).

Each match creates a `Trade` with `buy_order_id`, `sell_order_id`, `instrument`, `quantity`, `price`, `gross_value` (computed as `quantity * price`), `buyer_fee`, `seller_fee`, `settlement_status` initialized to `PENDING` (subsequently advancing to `SETTLED` on success or `FAILED` if the settlement engine cannot apply the balance change), and `executed_at` set to the time of the match. The buyer's enterprise has its `paid_quota_balance` (or `ccer_balance` for CCER) increased by the matched quantity, the buyer fee debited via the cash workflow; the seller's corresponding balance decreased by the matched quantity, with the seller fee similarly debited. An `AuditLogEntry` of action `TRADE_EXECUTED` is appended per trade.

Trade fees follow a tiered, marginal schedule. First, the trade's `gross_value` is computed by multiplying `quantity` by `price` and rounding half-up to two decimal places. The base rate is determined by channel: 0.0010 for `EXCHANGE`, 0.0006 for `BLOCK`, 0.0008 for `OTC`. Three tiers are defined by gross-value breakpoints: tier 1 covers gross values from zero up to and including 100,000 (the full base rate applies); tier 2 covers the portion strictly above 100,000 up to and including 1,000,000 (80% of the base rate applies on this portion only); tier 3 covers the portion strictly above 1,000,000 (60% of the base rate applies on this portion only). Specifically: the tier-1 portion equals the lesser of `gross_value` or 100,000; the tier-2 portion equals the maximum of zero and the lesser of `gross_value` or 1,000,000 minus 100,000; the tier-3 portion equals the maximum of zero and `gross_value` minus 1,000,000. The fee per side equals the tier-1 portion times the base rate, plus the tier-2 portion times the base rate times 0.80, plus the tier-3 portion times the base rate times 0.60, with the result rounded half-up to two decimal places at the very end. The buyer fee and seller fee each equal this fee per side. **The discounts apply marginally to the portions in each tier; an average-rate interpretation produces different cents and is forbidden.**

An enterprise may cancel its own order while it is in `OPEN` or `PARTIALLY_FILLED`; the order transitions to `CANCELLED`. Cancellation by another enterprise is rejected with `ERR_OWNERSHIP_VIOLATION`.

### 3.6. Compliance Declaration, Retirement, and Penalty

After the report has been finalized, an enterprise creates a `ComplianceDeclaration` for the `cycle_year`. The declaration begins in status `DRAFT` with `deficit_amount` and `surplus_amount` zero. The enterprise then submits the declaration by supplying `declared_offset_quota` (the tCO2e of free-and-paid quota the enterprise designates for retirement), `declared_offset_ccer` (the tCO2e of CCER credits designated for retirement, capped by the cycle's CCER cap), `declared_borrow_amount` (the quota borrowed from the next cycle, capped by 5% of verified emissions; defaults to zero), and `declared_bank_amount` (the surplus quota deferred to the next cycle after offset; defaults to zero).

Submission is permitted only when the corresponding emission report is in `FINALIZED` status, the current time is at or before the cycle's compliance deadline, and the three caps hold: the declared CCER offset must be at most the verified emissions multiplied by the cycle's CCER cap (rounded down to two decimal places) — otherwise rejected with `ERR_CCER_CAP_EXCEEDED`; the declared borrow amount must be at most the verified emissions multiplied by 0.05 (rounded down to two decimal places) — otherwise rejected with `ERR_BORROW_CAP_EXCEEDED`; the enterprise's free-plus-paid balance must be at least `declared_offset_quota` and the enterprise's CCER balance must be at least `declared_offset_ccer` — otherwise rejected with `ERR_INSUFFICIENT_BALANCE`. Submission after the compliance deadline is rejected with `ERR_WINDOW_CLOSED`. At most one declaration may be submitted per `(enterprise, cycle_year)`; a second submission is rejected with `ERR_DECLARATION_ALREADY_SUBMITTED`.

A successful submission transitions the declaration from `DRAFT` to `SUBMITTED` and applies the compliance balance calculation. Define `verified` as the report's `total_verified_emissions` and `offset_total` as `declared_offset_quota` plus `declared_offset_ccer` plus `declared_borrow_amount`. The `deficit_amount` is the maximum of zero and `verified` minus `offset_total`, rounded half-up to two decimal places. The `surplus_amount` is the maximum of zero and `offset_total` minus `verified`, rounded half-up to two decimal places. The three-step evaluation order is pinned: validate the caps first, retire the balances second, compute deficit and surplus third.

Retirement applies as follows: the system retires the `declared_offset_quota` by drawing first from the enterprise's `quota_balance` (the lesser of `quota_balance` or `declared_offset_quota`) and then drawing the remainder from `paid_quota_balance`; the system retires `declared_offset_ccer` from the enterprise's `ccer_balance`. The `declared_bank_amount` is recorded as a banking ledger entry. An `AuditLogEntry` of action `COMPLIANCE_RETIRE` is appended.

Following retirement, the system auto-transitions the declaration's status. If `deficit_amount` is zero, the declaration transitions from `SUBMITTED` to `COMPLIANT` and is synced to the regulator system via an event-driven hook. If `deficit_amount` is greater than zero, the declaration transitions from `SUBMITTED` to `NON_COMPLIANT`, a `PenaltyOrder` is created via the penalty calculation, and the result is synced to the regulator system.

The penalty calculation works as follows. First, define `deficit_pct` as `deficit_amount` divided by `verified_emissions`. The penalty order's `severity` is assigned by threshold: if `deficit_pct` is strictly less than 0.05, `severity` is `MINOR`; otherwise if `deficit_pct` is strictly less than 0.20, `severity` is `MODERATE`; otherwise `severity` is `SEVERE`. (The boundaries are exclusive on the lower bound: a `deficit_pct` of exactly 0.05 maps to `MODERATE`, and exactly 0.20 maps to `SEVERE`.) The `penalty_rate` is then looked up by jurisdiction and severity from the following matrix: for `JD_ALPHA`, the rates are 100.00, 200.00, and 500.00 currency units per tCO2e for `MINOR`, `MODERATE`, and `SEVERE` respectively; for `JD_BETA`, 80.00, 180.00, and 450.00; for `JD_GAMMA`, 120.00, 250.00, and 600.00. The `penalty_amount` is the `deficit_amount` multiplied by the `penalty_rate`, rounded half-up to two decimal places. The `mandatory_deduction_amount` is the `deficit_amount` multiplied by 1.5, rounded half-up to two decimal places. The penalty order's `payment_due_at` is set to 30 days after issuance, with `payment_status` initialized to `UNPAID`, `paid_at` null, and `credit_record_reported` false.

The enterprise pays the penalty via a payment action; the order transitions from `UNPAID` to `PAID` with `paid_at` set to the current time and `credit_record_reported` set to true, provided the current time is at or before `payment_due_at`. An `AuditLogEntry` with `action` `PENALTY_PAID` and `external_system` `REGULATOR` is appended. The cascade then transitions the declaration from `NON_COMPLIANT` to `PENALIZED`, and the mandatory deduction is recorded against the next cycle's allocation as a pending deduction equal to the deficit amount times 1.5. If payment is attempted after `payment_due_at`, the request is rejected with `ERR_PENALTY_OVERDUE`. When the periodic sweep observes a still-unpaid penalty whose `payment_due_at` has elapsed, the order transitions from `UNPAID` to `OVERDUE`, `credit_record_reported` is set to true (overdue mark), and an `AuditLogEntry` with `action` `PENALTY_OVERDUE` and `external_system` `REGULATOR` is appended.

A `COMPLIANT` declaration cascades to `FINALIZED` when its parent cycle moves to `SETTLED`; a `PENALIZED` declaration cascades to `FINALIZED` only when the parent cycle settles **and** the penalty's `payment_status` is `PAID` and `credit_record_reported` is true.

### 3.7. Settlement and Cycle Closure

Once the compliance deadline has passed and every enterprise's compliance declaration is in `COMPLIANT`, `NON_COMPLIANT`, `PENALIZED`, or `FINALIZED` status, the regulator settles the cycle. The cycle transitions from `COMPLIANCE_OPEN` to `SETTLED` with `settlement_date` set to the current time. As a cascade, an `AnnualSettlement` is created per enterprise via the settlement calculation.

The settlement calculation pins its computation order: opening, then net-traded, then retired, then deductions, then closing, then carry/repurchase/deficit. The `opening_quota` is the enterprise's quota balance plus paid-quota balance plus the retired amount as observed at settlement time (i.e., the balance prior to the cycle's retirements). The `net_traded_quota` is the sum, over all `QUOTA`-instrument trades involving this enterprise this cycle, of buy quantity minus sell quantity. The `retired_quota` equals the compliance declaration's `declared_offset_quota`. Mandatory deductions are the sum of penalty-order `mandatory_deduction_amount` values for this enterprise this cycle. The `closing_balance` is `opening_quota` plus `net_traded_quota` minus `retired_quota` minus mandatory deductions, rounded half-up to two decimal places.

The next-cycle allocation is the next allocation cycle's `Allocation.total_quota` for this enterprise (zero if no allocation exists). The carry-forward cap equals the next-cycle allocation multiplied by 0.10, rounded half-up to two decimal places. If the closing balance is non-negative, then `carry_forward_amount` equals the lesser of `closing_balance` and the carry-forward cap, `repurchase_amount` equals `closing_balance` minus `carry_forward_amount` (rounded half-up to two decimal places, repurchased by the regulator at a floor price of 30.00 currency units), and `deficit_purchase_amount` is zero. If the closing balance is negative, then `carry_forward_amount` and `repurchase_amount` are both zero, and `deficit_purchase_amount` equals the absolute value of the closing balance (rounded half-up to two decimal places).

Each `AnnualSettlement` is created in status `PENDING`, advances to `RECONCILED` once its computation is complete, and finally to `CLOSED` at cycle closure.

The regulator closes the cycle once every annual settlement has reached `CLOSED` status and every penalty order for the cycle is in `payment_status` `PAID`. The cycle transitions from `SETTLED` to `CLOSED`. As a side effect, each enterprise's `account_status` for this cycle's reporting transitions from `OPEN` to `CLOSED` (the account is reopened on the next cycle's `FINALIZED` state). An `AuditLogEntry` of action `CYCLE_CLOSED` is appended.

### 3.8. Audit Logging and External Synchronization

Every quota-affecting mutation appends an `AuditLogEntry` capturing `subject_type` (one of `QUOTA_CHANGE`, `TRADE_RECORD`, or `EXTERNAL_SYNC`), `subject_id`, `enterprise_id`, an action verb (such as `ALLOCATIONS_PUBLISHED`, `QUOTA_ALLOCATED`, `COMPLIANCE_RETIRE`, `TRADE_EXECUTED`, `PENALTY_PAID`, `PENALTY_OVERDUE`, `CYCLE_CLOSED`, or `BANK_SYNC`), `delta_quota` (the signed change in quota balance, zero for non-quota events), `delta_ccer` (the signed change in CCER balance, zero for non-CCER events), `external_system` (one of `BANK`, `REGULATOR`, `ENERGY_DATA`, or null when no external system was involved), and `occurred_at` (the timestamp of the event). Penalty-payment confirmations append entries with `external_system` `BANK`; sweep-driven overdue marks and compliance hook-syncs use `external_system` `REGULATOR`. Synthetic incoming events from external systems (such as `BANK_PAYMENT_CONFIRMED`) append `subject_type` `EXTERNAL_SYNC` entries; these events are idempotent on duplicate `event_id`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/enterprises`-anchored API surface (with several non-enterprise-prefixed paths for cycle, allocation, trading, and administrative operations as listed below). Successful creation of a new resource returns HTTP 201; successful modification of an existing resource returns HTTP 200. Action endpoints (publish, finalize, settle, close, submit, pay, etc.) are POST and return 200 with the updated resource. Reads return 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /enterprises | Register a new enterprise | Regulator |
| GET | /enterprises/{id} | Read enterprise including current balances | Regulator, Enterprise |
| GET | /enterprises | List enterprises (filter by `jurisdiction_code`, `industry_code`, `account_status`) | Regulator |
| POST | /allocation-cycles | Create a draft allocation cycle | Regulator |
| POST | /allocation-cycles/{id}/allocations | Propose an allocation for an enterprise in this cycle | Regulator |
| POST | /allocation-cycles/{id}/publish | Publish all proposed allocations and open objection window | Regulator |
| POST | /allocations/{id}/objections | File an objection to a published allocation | Enterprise |
| POST | /objections/{id}/uphold | Regulator upholds an objection and revises the allocation | Regulator |
| POST | /objections/{id}/reject | Regulator rejects an objection | Regulator |
| POST | /allocation-cycles/{id}/finalize | Finalize cycle after objection deadline; cascades quota into enterprise balances | Regulator |
| POST | /allocation-cycles/{id}/settle | Run annual settlement: reconcile balances, compute carry/repurchase/deficit | Regulator |
| POST | /allocation-cycles/{id}/close | Close cycle once all settlements and penalties paid | Regulator |
| GET | /allocation-cycles/{id} | Read cycle | Regulator, Enterprise |
| POST | /enterprises/{id}/emission-reports | Create a draft emission report (a new version if one already exists for `cycle_year`) | Enterprise |
| POST | /emission-reports/{id}/lines | Add an emission data line | Enterprise |
| POST | /emission-reports/{id}/documents | Upload a supporting document | Enterprise |
| POST | /emission-reports/{id}/submit | Submit emission report for verification | Enterprise |
| POST | /emission-reports/{id}/assign-verifier | Regulator assigns a third-party verifier and schedules visit | Regulator |
| POST | /verification-assignments/{id}/complete-onsite | Verifier records on-site completion with adjusted line amounts | VerifierAgency |
| POST | /verification-assignments/{id}/issue-report | Verifier issues final verification report | VerifierAgency |
| POST | /emission-reports/{id}/dispute | Enterprise disputes verification within 14 days | Enterprise |
| POST | /verification-assignments/{id}/resolve-dispute | Regulator resolves dispute | Regulator |
| POST | /emission-reports/{id}/finalize | Lock verified report | Regulator |
| POST | /emission-reports/{id}/reject | Reject a submitted report (template violation) | Regulator |
| GET | /emission-reports/{id} | Read emission report including lines and verified totals | Regulator, Enterprise, VerifierAgency |
| POST | /trading-orders | Place a trading order; matching is attempted immediately | Enterprise |
| POST | /trading-orders/{id}/cancel | Cancel an open or partially-filled order | Enterprise |
| GET | /trading-orders/{id} | Read order | Regulator, Enterprise |
| GET | /trades | List trades (filter by `enterprise_id`, `instrument`, `channel`, `executed_after`, `executed_before`) | Regulator, Enterprise |
| POST | /enterprises/{id}/compliance-declarations | Create draft compliance declaration | Enterprise |
| POST | /compliance-declarations/{id}/submit | Submit compliance declaration; retires offset balances and may trigger penalty | Enterprise |
| POST | /penalty-orders/{id}/pay | Pay a penalty order | Enterprise |
| GET | /penalty-orders/{id} | Read penalty order | Regulator, Enterprise |
| GET | /annual-settlements | List annual settlements (filter by `enterprise_id`, `cycle_year`) | Regulator, Enterprise |
| GET | /audit-logs | List audit log entries (filter by `enterprise_id`, `subject_type`, `action`, `occurred_after`, `occurred_before`) | Regulator |
| POST | /_clock/advance | Advance the system clock to a supplied `target_timestamp` | Regulator |
| POST | /_sweep/run | Run periodic sweep: marks penalty orders OVERDUE if past due | Regulator |
| POST | /_events/emit | Emit a synthetic event from an external system for event-driven sync testing | Regulator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_VIOLATION | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 409 |
| ERR_OBJECTION_ALREADY_PENDING | 409 |
| ERR_DECLARATION_ALREADY_SUBMITTED | 409 |
| ERR_INSUFFICIENT_BALANCE | 409 |
| ERR_PENALTY_OVERDUE | 409 |
| ERR_WINDOW_CLOSED | 422 |
| ERR_VERIFIER_CONFLICT_OF_INTEREST | 422 |
| ERR_SUPPORTING_DOCUMENT_REQUIRED | 422 |
| ERR_CCER_CAP_EXCEEDED | 422 |
| ERR_BORROW_CAP_EXCEEDED | 422 |
| ERR_INVALID_ORDER | 422 |
| ERR_INVALID_RATIO | 422 |
| ERR_INVALID_INPUT | 422 |
