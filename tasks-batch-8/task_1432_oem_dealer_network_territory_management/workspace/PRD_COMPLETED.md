# OEM Dealer Network & Territory Management API — Product Requirements Document

## 1. Introduction

Equipment original equipment manufacturers (OEMs) sell and service their machines through independently owned dealer networks, and the health of that channel depends on a disciplined set of commercial rules: who may sell where, how much each dealer is expected to move each quarter, how inventory financed on the OEM's floor-plan credit line ages and gets repaid, how warranty work is reimbursed and clawed back, and whether dealers keep their parts shelves and technician certifications up to contractual standard. Today these rules are typically enforced through spreadsheets and quarterly business reviews, which makes them slow, inconsistent, and nearly impossible to audit.

This document specifies the OEM Dealer Network & Territory Management API, a single service mounted under `/network` that operationalizes the full dealer relationship lifecycle. The API governs dealer onboarding and agreement activation under exclusive or shared territory coverage; quarterly sales targets with a tiered discount scheme that is computed provisionally at sale time and reconciled at quarter close; floor-plan financing advances with curtailment payments, interest accrual, and aging-driven default; warranty claim submission, adjudication, payment, post-payment audit, and chargeback with a dealer dispute loop; an annual parts return allowance tied to stocking compliance; certification verification as a gate on agreement activation; territory-aware lead routing with decline and expiry handling; and a weighted dealer performance scorecard that gates contract termination. All financial amounts are integer cents, all temporal rules are evaluated against a controllable logical clock, and every mutation is immediately visible in the response that commits it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity in which that party acts. A request in which either header is missing, empty, or whitespace-only is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing. Beyond header presence, each operation is restricted to specific roles; a caller whose role is not permitted for the endpoint receives `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes five role names, spelled exactly as follows: `OemNetworkAdmin`, `OemSalesOps`, `OemAuditor`, `DealerUser`, and `Any`.

An `OemNetworkAdmin` is the OEM's network operations administrator, responsible for dealers, agreements, territory assignments, floor-plan financing, and the logical clock. An `OemSalesOps` operator owns the sales-motion side of the network: quotas, unit-sale review, lead routing, and parts-return crediting. An `OemAuditor` performs the audit function: warranty claim adjudication and chargebacks, floor-plan aging audits, certification verification, stock audits, and return reversals. For each of these three roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`. The role `Any` is a marker covering every authenticated caller and applies to read endpoints: any request with valid headers, regardless of which of the four concrete roles it carries, may perform reads, and the literal role value `Any` is itself accepted on those read endpoints (it is not permitted on write endpoints). A role value outside the five recognized names is never permitted.

A `DealerUser` is a dealer-side user. When `X-User-Role` is `DealerUser`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's foreign-key field (for example, the `dealer_id` supplied in a request body, or the `dealer_id` stored on the resource being acted upon) to `X-User-ID`. A mismatch is rejected with `ERR_DEALER_IDENTITY_MISMATCH` (HTTP 403). The one operation with a different ownership anchor is lead response, where the acting `DealerUser` must be the dealer the lead is currently routed to; a mismatch there is rejected with `ERR_LEAD_NOT_ROUTED_TO_DEALER` (HTTP 403).

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
- Requests to an undefined route are rejected with `ERR_NOT_FOUND` (HTTP 404), requests to a defined route with an unsupported method are rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and unexpected server failures surface as `ERR_INTERNAL` (HTTP 500); all three use this same error envelope.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` that is not an integer or falls outside the 1–100 range, or an `offset` that is not an integer or is negative, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. Here `total_count` is the size of the full filtered result set, independent of pagination, and `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in this API — dealers, agreements, territory assignments, sales targets, unit sales, floor-plan advances, warranty claims, parts returns, certifications, and leads — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T09:15:00.123Z`), captured when the resource is created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- **`version`** (integer): a system-managed integer that increments with every modification to the resource.

A modification means any change the server commits to the resource, whether driven directly by a client request or indirectly by a system-side cascade. Recomputing a dealer's `tier` at quarter close, re-queuing a lead when its dealer is suspended, or marking an agreement `SUPERSEDED` all count as modifications of the affected resource and therefore refresh its `updated_at` and increment its `version`. No resource in this domain is immutable-after-creation; all ten entity types carry the full four-field set above.

### 2.5. Monetary Values and Precision

All monetary values in the system — credit ceilings, advance principal, claim amounts, return credits, chargeback balances — are represented as **integer cents**. Wherever a computation produces a fractional cent (a discount, a labor charge, an interest accrual, a restocking-adjusted return credit), the result is rounded **half-up to a whole cent** at the point the contract specifies. Rates and percentages used as inputs to those computations (for example, the tier discount rates, the daily floor-plan interest rates, and the restocking percentage) are exact decimal constants and are never themselves rounded.

The dealer performance scorecard is the one place where non-integer numbers are surfaced: its component scores and total are computed and exposed with exactly **two decimal places**, again using round-half-up, and — as detailed in §3.8 — each component is rounded to two decimals before the weighting step, and the weighted total is rounded to two decimals afterwards.

### 2.6. The Logical Clock

Every date- and time-dependent rule in the system is evaluated against a **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any explicit set operation the clock continues to read this default, and it never silently falls back to wall-clock time. An administrator-only test-driving capability, exercised by an `OemNetworkAdmin`, advances the logical clock to a supplied `to_iso8601` instant — any parseable ISO 8601 instant is accepted, forward or backward, with no monotonicity constraint, and an unparseable value is rejected with `ERR_INVALID_REQUEST` — and returns the resulting `current_utc` value.

The logical clock anchors every temporal rule in this document: the `advance_date` of a floor-plan advance (the anchor for interest accrual and aging brackets), the `paid_at` timestamp of a warranty payment (the anchor for the post-payment audit window), the `routed_at` timestamp of a lead (the anchor for the 72-hour response SLA), the quarter boundary that gates sales-target close, the calendar year that a parts return's `return_year` must match and that governs the parts-purchase year rollover, and the June 30 cut-off that determines whether a restocking deduction applies to a return. Date fields supplied by clients (`effective_date`, `expiry_date`, `starts_on`, `ends_on`, `earned_on`, `expires_on`, `sale_date`) use the calendar date format `YYYY-MM-DD`; comparisons involving them are evaluated against the current logical date.

### 2.7. Optimistic Concurrency Control

Exactly one write operation in this API is protected by optimistic concurrency control: **agreement activation**. An activation request must carry `expected_dealer_version`, a non-optional input field containing the `version` of the parent `Dealer` as last observed by the client. If the dealer's current `version` on the server does not match `expected_dealer_version` — because another writer has advanced the dealer's version since the client last read it, for instance by activating a different agreement that bumped the dealer's version and possibly superseded the previously active one — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change occurs. This prevents a client from activating an agreement against a dealer record it has not observed.

No other endpoint accepts a version field. All other state transitions are guarded purely by their from-state preconditions as described in §3.

### 2.8. Request Validation Order

When several things are wrong with a single request, the server does not choose an error arbitrarily; validations run in a fixed priority order, and the first failing check determines the rejection. The order is:

1. **Header presence.** `X-User-ID` and `X-User-Role` must both be present and non-empty, on every endpoint (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role permission.** The declared role must be permitted for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. **Input format.** Required fields must be present, enum values valid, dates parseable, and — where a date range is supplied — the end strictly after the start; a parts return's `return_year` must equal the current clock year (`ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`, `ERR_RETURN_YEAR_MISMATCH`).
4. **Existence.** Every referenced resource must exist, checked left-to-right: path identifiers first, then identifiers referenced in the request body. The corresponding not-found error is raised for the first missing identifier (`ERR_DEALER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`).
5. **Ownership and identity.** For `DealerUser` writes, the body's `dealer_id` must equal `X-User-ID`; lead responses and claim disputes must come from the routed or claim-owning dealer (`ERR_DEALER_IDENTITY_MISMATCH`, `ERR_LEAD_NOT_ROUTED_TO_DEALER`).
6. **State and concurrency.** The target resource must be in a valid from-state for the requested transition, and — for agreement activation — the OCC check of §2.7 must pass (`ERR_STALE_VERSION` and the state errors: `ERR_DEALER_NOT_ACTIVE`, `ERR_DEALER_NOT_SUSPENDED`, `ERR_AGREEMENT_NOT_IN_DRAFT`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_ASSIGNMENT_NOT_ACTIVE`, `ERR_TARGET_NOT_OPEN`, `ERR_SALE_NOT_REPORTED`, `ERR_SALE_NOT_ACCEPTED`, `ERR_ADVANCE_NOT_OPEN`, `ERR_CLAIM_INVALID_STATE`, `ERR_RETURN_INVALID_STATE`, `ERR_CERT_INVALID_STATE`, `ERR_LEAD_INVALID_STATE`).
7. **Safety gates.** Certification compliance at agreement activation and the scorecard threshold at dealer termination (`ERR_CERTIFICATION_COMPLIANCE`, `ERR_SCORECARD_THRESHOLD_NOT_MET`).
8. **Uniqueness and overlap.** Duplicate business keys and forbidden coverage overlaps (`ERR_DUPLICATE_DEALER_CODE`, `ERR_DUPLICATE_AGREEMENT_CODE`, `ERR_DUPLICATE_TARGET`, `ERR_DUPLICATE_UNIT_SERIAL`, `ERR_DUPLICATE_ADVANCE_SERIAL`, `ERR_TERRITORY_OVERLAP`, `ERR_AGREEMENT_OVERLAP`, `ERR_STOCKING_NONCOMPLIANT`).
9. **Temporal windows.** Window placement and maturity checks (`ERR_ASSIGNMENT_OUTSIDE_AGREEMENT`, `ERR_QUARTER_NOT_ENDED`, `ERR_AUDIT_WINDOW_CLOSED`, `ERR_CERT_NOT_YET_EXPIRED`, `ERR_AGREEMENT_NOT_YET_EXPIRED`, `ERR_LEAD_NOT_YET_EXPIRED`).
10. **Cross-reference integrity.** Referential consistency between linked resources (`ERR_AGREEMENT_DEALER_MISMATCH`, `ERR_SALE_PAYOFF_LOCKED`, `ERR_REINSTATE_BLOCKED`).
11. **Money limits.** Credit ceiling, payment balance, and return allowance checks come last (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_ALLOWANCE_EXCEEDED`).

### 2.9. Cascading State Consistency

Dealer network state is deeply interconnected, and the server maintains consistency eagerly: when one resource's transition has contractual consequences for others, all of those consequences are applied atomically in the same operation and are fully visible in the response that commits the change. Three cascades recur throughout this document and are worth naming once here.

First, **lead re-queuing**: whenever a territory assignment leaves `ACTIVE`, or a dealer is suspended or terminated, every lead currently `ROUTED` through the affected assignment or dealer returns to `NEW`, and its routing fields (`routed_dealer_id`, `routed_assignment_id`, `routed_at`) are cleared. Second, **the termination cascade**: terminating a dealer moves each of its `ACTIVE` agreements to `TERMINATED` (link 1), moves each such agreement's `ACTIVE` territory assignments to `RELEASED` (link 2), and re-queues the leads routed through those assignments (link 3). Third, **the chargeback suspension cascade**: a chargeback that pushes a dealer's chargeback balance to the suspension threshold flips an `ACTIVE` dealer to `SUSPENDED`, which in turn re-queues its routed leads.

Where a cascade is driven by a dealer-level transition, `Dealer.version` increments as part of the same operation, and every resource touched by the cascade is itself modified in the sense of §2.4.

## 3. Business Logic & Workflows

### 3.1. Dealer Onboarding and Certification Compliance

A dealer relationship begins when an `OemNetworkAdmin` registers the dealer, supplying a business `name`, a `dealer_code`, a free-form `region` label, a `credit_limit_cents` floor-plan ceiling that must be greater than zero, and a `min_stock_value_cents` parts-stocking requirement that must be greater than or equal to zero. The `dealer_code` is unique across all dealers; a collision is rejected with `ERR_DUPLICATE_DEALER_CODE`. A newly created dealer starts in `ONBOARDING` status with `tier` set to `BRONZE`, every computed counter at zero — `floorplan_utilization_cents`, `default_loss_cents`, `chargeback_balance_cents`, `discount_reconciliation_cents`, `parts_purchases_ytd_cents` — `stock_observed_value_cents` at zero, `stock_compliant` false, and `purchases_year` null until the dealer's first recorded parts purchase. The dealer's available floor-plan credit is always derivable: `floorplan_available_cents` is the `credit_limit_cents` minus the current `floorplan_utilization_cents`.

Before the dealer can trade under an agreement, the OEM requires evidence of technician capability. A `DealerUser` registers a certification for their own dealership by supplying the `dealer_id` (which must equal the caller's `X-User-ID`, else `ERR_DEALER_IDENTITY_MISMATCH`), a `cert_code` identifying the program, the `earned_on` date, and an `expires_on` date that must be strictly later than `earned_on` (`ERR_INVALID_DATE_RANGE`). The certification enters `PENDING_VERIFICATION`. An `OemAuditor` then adjudicates it through a `decision`: a `decision` of `VERIFY` moves it to `ACTIVE`, while `REJECT` moves it to the terminal `REJECTED` state; either decision requires the certification to still be `PENDING_VERIFICATION` (`ERR_CERT_INVALID_STATE`). An auditor may also expire an `ACTIVE` certification once the current logical date has passed its `expires_on`, moving it to `EXPIRED`; attempting expiry too early is rejected with `ERR_CERT_NOT_YET_EXPIRED`, and expiry of a certification that is not `ACTIVE` fails with `ERR_CERT_INVALID_STATE`.

Certifications are not decorative. Activating a dealer agreement requires the dealer to hold **at least two** certifications in `ACTIVE` status; an activation attempt with fewer is rejected with `ERR_CERTIFICATION_COMPLIANCE`. And when that first activation succeeds, the dealer itself graduates from `ONBOARDING` to `ACTIVE`, with `Dealer.version` incrementing as part of the same operation.

### 3.2. Dealer Agreements and Territory Coverage

The commercial relationship is papered by a **DealerAgreement**, drafted by an `OemNetworkAdmin` with the target `dealer_id`, a unique `agreement_code` (duplicates rejected with `ERR_DUPLICATE_AGREEMENT_CODE`), an inclusive `effective_date`, and an inclusive `expiry_date` that must be strictly later than `effective_date` (`ERR_INVALID_DATE_RANGE`). The agreement is created in `DRAFT`.

Activation is the pivotal act of the onboarding flow and is deliberately strict. The agreement must currently be `DRAFT` (`ERR_AGREEMENT_NOT_IN_DRAFT`); the request must carry `expected_dealer_version` matching the dealer's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` per §2.7; the dealer must be in `ONBOARDING` or `ACTIVE` status (`ERR_DEALER_NOT_ACTIVE`); the two-active-certification gate of §3.1 must pass (`ERR_CERTIFICATION_COMPLIANCE`); and the new agreement's inclusive date window must not collide with another `ACTIVE` agreement for the same dealer. On that last point, the comparison is **inclusive at both ends** — touching dates count as overlap. When an overlap exists, activation proceeds only if the caller sets `supersede_existing` to true (it defaults to false when omitted, and a non-boolean value supplied is rejected with `ERR_INVALID_REQUEST`), in which case the previously active overlapping agreement is moved to `SUPERSEDED` as part of the same operation; without that flag the activation is rejected with `ERR_AGREEMENT_OVERLAP`. A successful activation moves the agreement to `ACTIVE`, increments `Dealer.version` by one, supersedes the displaced agreement when applicable, and — on the dealer's first activation — flips the dealer from `ONBOARDING` to `ACTIVE`.

Supersession is gentle on territory: an agreement that becomes `SUPERSEDED` does **not** release its `ACTIVE` territory assignments. They remain bound to the superseded agreement, and coverage continues, until their own expiry window passes. Termination and expiry are less gentle. An administrator may terminate an agreement while it is `DRAFT` (a simple withdrawal with no downstream effects) or while it is `ACTIVE` — a termination attempted against an agreement in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`; terminating an `ACTIVE` agreement — whether directly or as link 1 of the dealer termination cascade of §3.8 — moves it to `TERMINATED`, releases its `ACTIVE` assignments, and re-queues the leads routed through them. Once the current logical date has passed an `ACTIVE` agreement's `expiry_date`, an administrator may expire it into `EXPIRED`, which likewise releases its `ACTIVE` assignments and re-queues their leads; attempting expiry before that date is rejected with `ERR_AGREEMENT_NOT_YET_EXPIRED`, and expiry of a non-active agreement fails with `ERR_AGREEMENT_NOT_ACTIVE`. Both `SUPERSEDED` and `EXPIRED` are terminal, as is `TERMINATED`.

Territory coverage is expressed through **TerritoryAssignment** records, created by an `OemNetworkAdmin` naming the `dealer_id`, the `agreement_id`, the `territory_code` covered, a `coverage_type` of `EXCLUSIVE` or `SHARED`, and a half-open coverage window given by `starts_on` (inclusive) and `ends_on` (exclusive, and strictly later than `starts_on`, else `ERR_INVALID_DATE_RANGE`). The assignment's agreement must belong to the same dealer as the assignment — a cross-dealer reference is rejected with `ERR_AGREEMENT_DEALER_MISMATCH` — and must be `ACTIVE` at creation time (`ERR_AGREEMENT_NOT_ACTIVE`). The coverage window must sit within the agreement's own window: `starts_on` on or after the agreement's `effective_date`, and `ends_on` on or before the agreement's `expiry_date`; a window outside those bounds is rejected with `ERR_ASSIGNMENT_OUTSIDE_AGREEMENT`.

Overlap between assignments on the same `territory_code` is governed by the coverage types, using **half-open interval** semantics — two windows that merely touch at a boundary date (one ends on the day the other starts) are adjacent, not overlapping, and are always allowed. An `EXCLUSIVE` assignment rejects any overlapping `ACTIVE` assignment on the same territory code; `SHARED` assignments overlap other `SHARED` assignments freely, but neither an `EXCLUSIVE` nor a `SHARED` assignment may overlap an `EXCLUSIVE` one. A forbidden overlap is rejected with `ERR_TERRITORY_OVERLAP`. An assignment is born `ACTIVE` and may later be released by an administrator — or by the agreement termination/expiration and dealer termination cascades — moving it to `RELEASED`; release requires the assignment to currently be `ACTIVE` (`ERR_ASSIGNMENT_NOT_ACTIVE`), and it re-queues every lead `ROUTED` through it back to `NEW`, clearing the lead's `routed_dealer_id`, `routed_assignment_id`, and `routed_at`.

### 3.3. Quotas, Retail Sales Reporting, and Tier Discounts

Each dealer's selling obligation is set quarterly. An `OemSalesOps` operator creates a **SalesTarget** with the `dealer_id`, a `period_year`, a `period_quarter` between 1 and 4 inclusive, and a `target_units` quota greater than zero. Only one target may exist for a given dealer, year, and quarter; a duplicate is rejected with `ERR_DUPLICATE_TARGET`. A new target is `OPEN` with `achieved_units` at zero and `final_discount_rate` null — the rate is only locked when the target closes.

Dealers report retail movement as it happens. A `DealerUser` reports a **UnitSale** for their own dealership, providing the `dealer_id` (identity-checked against `X-User-ID`), the `unit_serial` sold, the `sale_date` — which determines the quota quarter the sale counts toward — and the `list_price_cents`, which must be greater than zero. Reporting requires that a sales target for the dealer and the sale's quarter exist and still be `OPEN`; otherwise the report is rejected with `ERR_TARGET_NOT_OPEN`. The serial number is unique per dealer among sales that are not `REJECTED` and not `VOIDED`; a live duplicate is rejected with `ERR_DUPLICATE_UNIT_SERIAL`. The sale enters `REPORTED` status with `final_discount_cents` null (it is populated only when the target closes), and the system immediately computes a **provisional discount**, stored in `provisional_discount_cents`: it projects this sale as accepted by taking the target's current `achieved_units` plus one as the counted units, dividing by the target's `target_units` to get an attainment ratio, selecting the tier rate — eight percent (0.08) when the ratio is at least 1.2 (`GOLD` attainment), five percent (0.05) when the ratio is at least 1.0 (`SILVER` attainment), and two percent (0.02) otherwise (`BRONZE` attainment) — and multiplying the `list_price_cents` by that rate, rounding half-up to a whole cent. This provisional figure is computed even while the target is still `OPEN`.

An `OemSalesOps` operator then adjudicates the reported sale by posting a `decision`. Acceptance — a `decision` of `ACCEPT` — requires the sale to be `REPORTED` (`ERR_SALE_NOT_REPORTED`) and requires a sales target for the dealer and the sale's quarter to exist and still be `OPEN` (`ERR_TARGET_NOT_OPEN`). On acceptance the sale moves to `ACCEPTED`, the target's `achieved_units` increases by one, and — crucially — the acceptance triggers the **retail-sale payoff cascade**: any floor-plan advance for the same dealer and `unit_serial` in `OPEN`, `CURTAILED`, or `PAST_DUE` status is paid off in full, moving to `PAID_OFF` with its `paid_curtailments_cents` set equal to its `advance_cents` and the dealer's `floorplan_utilization_cents` reduced by the remaining principal. Rejection — a `decision` of `REJECT` — by contrast simply moves the sale to `REJECTED` with no further effects; the payload may carry an optional `reason` in either case.

An accepted sale can later be voided by `OemSalesOps`, moving it from `ACCEPTED` to `VOIDED` and decrementing the target's `achieved_units` by one — but only if it was not itself the cause of a floor-plan payoff. If the linked advance is sitting in `PAID_OFF` because this sale's acceptance paid it off, the void is rejected with `ERR_SALE_PAYOFF_LOCKED`; a void attempted on a sale that is not `ACCEPTED` fails with `ERR_SALE_NOT_ACCEPTED`.

After the quarter ends, `OemSalesOps` closes the target. Closing requires the target to still be `OPEN` (`ERR_TARGET_NOT_OPEN`) and requires the current logical date to be on or after the first day of the quarter following the target's `(period_year, period_quarter)` — an early close is rejected with `ERR_QUARTER_NOT_ENDED`. If `achieved_units` is at least `target_units` — equality counts as met — the target closes as `CLOSED_MET`; otherwise it closes as `CLOSED_MISSED`. Either way, the close performs the **final** discount reckoning: the attainment ratio is recomputed using the final counted units (`achieved_units`, which reflects `ACCEPTED` sales only, with `VOIDED` sales excluded), the tier rate is selected from the same 1.2 and 1.0 thresholds and the same 0.08, 0.05, and 0.02 rates, and that rate is locked into the target's `final_discount_rate`. Every `ACCEPTED` sale in the quarter then receives its `final_discount_cents`, computed from the locked rate and the sale's `list_price_cents` with half-up rounding to whole cents, and the dealer's `discount_reconciliation_cents` accumulates the sum, across those sales, of each final discount minus its previously booked provisional discount. Finally, the dealer's `tier` is recomputed from the final ratio — `GOLD`, `SILVER`, or `BRONZE` by the same thresholds — and `Dealer.version` increments.

### 3.4. Floor-Plan Financing, Curtailments, and Aging

Dealers finance floor inventory through the OEM's credit pool. An `OemNetworkAdmin` creates a **FloorPlanAdvance** for a dealer, naming the `dealer_id`, the financed `unit_serial`, and the `advance_cents` principal, which must be greater than zero. The dealer must be `ACTIVE`; creating an advance for a dealer in any other status is rejected with `ERR_DEALER_NOT_ACTIVE`. A serial may have only one live advance per dealer: a duplicate among non-terminal advances — those not yet `PAID_OFF` or `DEFAULTED` — is rejected with `ERR_DUPLICATE_ADVANCE_SERIAL`. The advance must also fit within the dealer's remaining credit: an `advance_cents` exceeding the dealer's current `floorplan_available_cents` is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On creation the advance is `OPEN`, its `advance_date` is stamped with the current logical date as the aging anchor, its `paid_curtailments_cents` and `accrued_interest_cents` start at zero, and the dealer's `floorplan_utilization_cents` increases by the principal. At any moment the utilization equals the sum, over all of the dealer's advances in `OPEN`, `CURTAILED`, or `PAST_DUE`, of each advance's principal minus its paid curtailments.

Repayment comes in through curtailment payments recorded by an `OemNetworkAdmin`, each carrying an `amount_cents` that must be a positive integer (`ERR_INVALID_REQUEST` otherwise). The advance must be in `OPEN`, `CURTAILED`, or `PAST_DUE` (`ERR_ADVANCE_NOT_OPEN`), and the amount must not exceed the remaining principal — the `advance_cents` minus the `paid_curtailments_cents` — else `ERR_PAYMENT_EXCEEDS_BALANCE`. A partial payment adds the amount to `paid_curtailments_cents`, subtracts it from the dealer's `floorplan_utilization_cents`, and leaves the advance in (or moves it to) `CURTAILED`; this is true whether the advance was `OPEN`, already `CURTAILED`, or `PAST_DUE`. A payment exactly equal to the remaining principal pays the advance off: it moves to `PAID_OFF` from any of those three states, `paid_curtailments_cents` is set equal to the full `advance_cents`, and the dealer's utilization is reduced by the remaining principal — the same end state the retail-sale payoff cascade of §3.3 produces.

Aging is policed by an `OemAuditor` through an aging audit, which always recomputes the advance's accrued interest against the current logical date. Interest accrues only after a free period: the advance's age in whole days is the current logical date minus the `advance_date`, with the creation date counted as day 0, and days 1 through 90 are interest-free. Beyond that, each billable day accrues at a daily rate applied to the **current** remaining principal — the `advance_cents` minus the `paid_curtailments_cents` as they stand at audit time, not any historical value. Days 91 through 180 accrue at a daily rate of 0.0002, days 181 through 270 at 0.0004, and day 271 onward at 0.0006. The accrued interest is the remaining principal multiplied by the sum across the three brackets of each bracket's rate times the number of days the advance has spent in that bracket, rounded half-up to a whole cent, and stored in `accrued_interest_cents`.

The same audit drives the aging transitions. An advance in `OPEN` or `CURTAILED` whose age has passed 90 days moves to `PAST_DUE`. An advance in `OPEN`, `CURTAILED`, or `PAST_DUE` whose age has passed 270 days moves to `DEFAULTED` — a terminal state in which the remaining principal is written off: the dealer's `floorplan_utilization_cents` is reduced by that remaining principal and the same amount is added to the dealer's `default_loss_cents`. The audit's interest recomputation applies on every invocation, whether or not a status change occurs.

### 3.5. Warranty Claims, Audits, and Chargebacks

Warranty reimbursement begins at the dealership. A `DealerUser` submits a **WarrantyClaim** for their own dealership, supplying the `dealer_id` (identity-checked), the `unit_serial` the claim pertains to, a `parts_cost_cents` that may be zero but not negative, `labor_hours` that likewise may be zero but not negative, and a free-text `failure_description`. The claim's value is computed at submission and stored in `claim_amount_cents`: the parts cost plus the labor charge, where the labor charge is the `labor_hours` multiplied by the dealer's tier labor rate **as it stands at submission time** — 12000 cents per hour for a `GOLD` dealer, 10000 for `SILVER`, 8500 for `BRONZE` — with the labor charge rounded half-up to a whole cent. The claim enters `SUBMITTED`.

An `OemAuditor` adjudicates with a `decision`: `APPROVE` moves the claim to `APPROVED`, `REJECT` moves it to the terminal `REJECTED` state, and either `decision` requires the claim to currently be `SUBMITTED` (`ERR_CLAIM_INVALID_STATE`); the payload may carry an optional `reason`. Payment of an `APPROVED` claim, again by the auditor, moves it to `PAID`, sets `paid_amount_cents` equal to the full `claim_amount_cents`, and stamps `paid_at` with the current logical clock — the anchor for everything that follows.

Post-payment audit has a statute of limitations. An auditor may flag a `PAID` claim for audit, moving it to `AUDIT_FLAGGED`, only while the current logical datetime is no later than 365 days after `paid_at`; once that window has closed the flagging is rejected with `ERR_AUDIT_WINDOW_CLOSED`, and flagging a claim in any other state fails with `ERR_CLAIM_INVALID_STATE`. A flagged claim can then be charged back with a `finding` of `FULL` or `PARTIAL`. A `FULL` finding sets `chargeback_amount_cents` to the entire `claim_amount_cents`; a `PARTIAL` finding claws back only the labor, setting `chargeback_amount_cents` to the `claim_amount_cents` minus the `parts_cost_cents`. Either way the claim moves to `CHARGED_BACK`, the chargeback amount is added to the dealer's `chargeback_balance_cents` — and here the cascade of §2.9 may fire: if the balance has reached or exceeded 50000 cents and the dealer is `ACTIVE`, the dealer is automatically suspended to `SUSPENDED`, and every lead currently `ROUTED` to that dealer is re-queued to `NEW` with its routing fields cleared.

The dealer is not without recourse. The claim-owning `DealerUser` may dispute a `CHARGED_BACK` claim, moving it to `DISPUTED`; the caller must be the claim's dealer (`ERR_DEALER_IDENTITY_MISMATCH`), and the claim must be `CHARGED_BACK` (`ERR_CLAIM_INVALID_STATE`). The auditor resolves the dispute with an `outcome`: `UPHELD` finds for the dealer, returning the claim to `PAID`, subtracting the `chargeback_amount_cents` from the dealer's `chargeback_balance_cents`, and resetting the claim's `chargeback_amount_cents` to null; `DENIED` lets the chargeback stand, returning the claim to `CHARGED_BACK` with no balance change. Resolution requires the claim to be `DISPUTED` (`ERR_CLAIM_INVALID_STATE`).

### 3.6. Parts Stocking, Purchases, and the Annual Return Allowance

Dealer agreements obligate dealers to stock a minimum value of parts, and the OEM verifies this through stock audits. An `OemAuditor` records an audit by supplying `observed_stock_value_cents`, which must be a non-negative integer (`ERR_INVALID_REQUEST` otherwise); the dealer's `stock_observed_value_cents` is set to that value, `stock_compliant` is recomputed as true exactly when the observed value is at least the dealer's `min_stock_value_cents`, and `Dealer.version` increments. Separately, an `OemNetworkAdmin` records the dealer's parts purchases by supplying an `amount_cents` that must be a positive integer (`ERR_INVALID_REQUEST` otherwise). The dealer's `parts_purchases_ytd_cents` accumulates purchases within a calendar year; when the purchase is recorded in a clock year that differs from the stored `purchases_year`, the year-to-date figure first resets — to the new `amount_cents` — and `purchases_year` is set to the clock year. Each purchase recording also increments `Dealer.version`.

Once a year a dealer may return excess stock for credit. A `DealerUser` drafts a **PartsReturn** for their own dealership, supplying the `dealer_id`, a `return_year`, and a `lines` array in which each line names a `part_number`, a `quantity` greater than zero, and a `unit_credit_cents` greater than zero; the array may be empty, in which case the previewed credit is zero. The `return_year` must equal the current clock year (`ERR_RETURN_YEAR_MISMATCH`). The draft is created in `DRAFT` status with a **previewed** credit: the system computes each line's credit as the `quantity` times the `unit_credit_cents`, reduced by a 15 percent restocking deduction when the current logical date falls after June 30 of the `return_year` (the `restock_pct_applied` is 0.15 in that case and 0 otherwise), rounds each line's credit half-up to a whole cent, and sums the per-line rounded credits into `credit_cents`. The rounding order is pinned: round per line first, then sum — summing first and rounding once is not permitted.

Submission is where the draft becomes binding. The submitting `DealerUser` must own the return (`ERR_DEALER_IDENTITY_MISMATCH`), the return must be `DRAFT` (`ERR_RETURN_INVALID_STATE`), and two business gates apply. The dealer's `stock_compliant` flag must be true — a dealer behind on its stocking obligation cannot return parts, and the attempt is rejected with `ERR_STOCKING_NONCOMPLIANT`. And the return must fit within the dealer's **annual return allowance**: the allowance for the year is five percent of the dealer's `parts_purchases_ytd_cents`, rounded half-up to a whole cent; the amount already used is the sum of `credit_cents` over the dealer's other returns with the same `return_year` in `SUBMITTED` or `CREDITED` status; and the submission is allowed only when the used amount plus this return's `credit_cents` is less than or equal to the allowance — equality is allowed — otherwise `ERR_ALLOWANCE_EXCEEDED`. Because the previewed credit may be stale by submission time, `credit_cents` and `restock_pct_applied` are recomputed against the submit date as part of the submit, and it is the recomputed `credit_cents` that the allowance check consumes. A successful submission moves the return to `SUBMITTED`.

From there, `OemSalesOps` records a `decision` on the return: `CREDIT` moves it to `CREDITED`, `REJECT` moves it to `REJECTED`, and either `decision` requires the return to be `SUBMITTED` (`ERR_RETURN_INVALID_STATE`); the payload may carry an optional `reason`. Finally, an `OemAuditor` may reverse a `CREDITED` return, moving it to the terminal `REVERSED` state; a reversed return is excluded from the used-allowance sum, freeing its credit back to the dealer's annual allowance as a compensating release. Reversal requires the return to be `CREDITED` (`ERR_RETURN_INVALID_STATE`).

### 3.7. Lead Routing and Dealer Response

Demand reaches the network as **Lead** records, created by `OemSalesOps` with the `territory_code` the prospect sits in, the `product_line` of interest, an `estimated_value_cents` greater than zero, and a `contact_name`. A new lead is `NEW`, with `routed_dealer_id`, `routed_assignment_id`, and `routed_at` all null and `declined_dealer_ids` empty.

Routing is a selection, not a guess, and it may be invoked from any routable state — `NEW`, `ORPHANED`, `DECLINED`, or `EXPIRED` (`ERR_LEAD_INVALID_STATE` otherwise). The candidate pool is every dealer that satisfies three conditions: the dealer's status is `ACTIVE`; the dealer holds a territory assignment in `ACTIVE` status whose `territory_code` equals the lead's `territory_code` and whose half-open window covers the current logical date — `starts_on` on or before today and `ends_on` after today; and the dealer's `id` does not appear in the lead's `declined_dealer_ids`. Among the candidates, the winner is the dealer with the fewest currently open leads — leads in `ROUTED` status routed to that dealer — and ties are broken in favor of the dealer with the earliest `created_at`. When a winner exists, the lead moves to `ROUTED`, its `routed_dealer_id` and `routed_assignment_id` are set to the winning dealer and the assignment that qualified them (when several of the dealer's `ACTIVE` assignments qualify, the earliest-created one is bound), and `routed_at` is stamped with the current logical clock. When the pool is empty, the lead moves to `ORPHANED` instead — this is a normal outcome, not an error — and its routing fields remain null. Re-routing a previously `DECLINED` or `EXPIRED` lead follows the same selection, with the prior decliner or expired dealer excluded through `declined_dealer_ids`.

The routed dealer then has 72 hours to respond. The responding `DealerUser` must be the dealer the lead is currently routed to (`ERR_LEAD_NOT_ROUTED_TO_DEALER`), and the lead must be `ROUTED` (`ERR_LEAD_INVALID_STATE`). A `response` of `ACCEPT` moves the lead to the terminal `ACCEPTED` state. A `response` of `DECLINE` moves it to `DECLINED`, appends the dealer's `id` to `declined_dealer_ids`, and clears the routing fields. If the dealer simply lets the clock run, `OemSalesOps` may expire the lead once the current logical datetime is more than 72 hours past `routed_at` (`ERR_LEAD_NOT_YET_EXPIRED` before then): the lead moves to `EXPIRED`, the unresponsive dealer is appended to `declined_dealer_ids` just as if they had declined, and the routing fields are cleared. Either way, the lead can be routed again — to someone else.

### 3.8. Performance Scorecards, Suspension, and Termination

The OEM grades each dealer quarterly with a weighted **performance scorecard**, available on demand for any `period_year` and `period_quarter` — both are required, integer-valued query parameters (a JSON request body carrying the same field names is also accepted), and a missing or non-integer value is rejected with `ERR_INVALID_REQUEST` — with an optional `variant` selector: `STRICT` is the default and the only variant that counts for termination, while `INCLUSIVE` gives a more generous in-flight view; any other `variant` value is rejected with `ERR_INVALID_REQUEST`. The scorecard response reports `period_year`, `period_quarter`, the `variant` used, the four component scores `sales_score`, `service_score`, `training_score`, and `parts_score`, and the weighted `total_score`. All five scores are rounded half-up to two decimal places, and — critically for reproducibility — each component is rounded to two decimals **before** the weighting step, with the weighted total rounded to two decimals afterwards.

The **sales** component measures attainment against the period's target: the counted units divided by `target_units`, capped at one and a half, then divided by one and a half and multiplied by 100. If the dealer has no target for the period, the sales component is 0. Under `STRICT`, the counted units are the target's `achieved_units` — `ACCEPTED` sales only; under `INCLUSIVE`, the count additionally includes the dealer's `REPORTED` (not yet decided) sales in the period. The **service** component reflects warranty discipline: settled value is the sum of `claim_amount_cents` over the dealer's claims in `PAID`, `AUDIT_FLAGGED`, `CHARGED_BACK`, or `DISPUTED`; the charged-back value is, under `STRICT`, the sum of `chargeback_amount_cents` over `CHARGED_BACK` claims, and under `INCLUSIVE` that same sum **plus** the full `claim_amount_cents` of claims currently `AUDIT_FLAGGED` or `DISPUTED`. The component is 100 minus 100 times the charged-back value divided by the settled value — and 100 outright when the settled value is zero. The **training** component is 100 times the dealer's certification units divided by two, with certification units capped at two; under `STRICT`, certification units are the count of `ACTIVE` certifications, while under `INCLUSIVE` they are the `ACTIVE` count plus half the count of certifications still `PENDING_VERIFICATION`. The **parts** component is binary: 100 when the dealer's `stock_compliant` flag is true, 0 otherwise. The total score is the weighted sum — forty percent sales, twenty-five percent service, twenty percent training, fifteen percent parts.

Two administrative levers act directly on dealer status. An `OemNetworkAdmin` may suspend an `ACTIVE` dealer by requesting `target` `SUSPENDED`, and reinstate a suspended dealer by requesting `target` `ACTIVE`. Suspension requires the dealer to currently be `ACTIVE` (`ERR_DEALER_NOT_ACTIVE`); it re-queues every lead `ROUTED` to the dealer back to `NEW` with routing fields cleared, and increments `Dealer.version`. The same transition also fires automatically, as §3.5 describes, when a chargeback pushes an `ACTIVE` dealer's `chargeback_balance_cents` to or beyond 50000 cents. Reinstatement requires the dealer to currently be `SUSPENDED` (`ERR_DEALER_NOT_SUSPENDED`) and requires the `chargeback_balance_cents` to be back below 50000 cents — a balance at or above that level blocks reinstatement with `ERR_REINSTATE_BLOCKED`. The `target` field accepts only `SUSPENDED` and `ACTIVE`; any other value is rejected with `ERR_INVALID_REQUEST`. The from-state checks apply per direction: a suspension attempted against a dealer that is not `ACTIVE` — including one still `ONBOARDING` or already `TERMINATED` — is rejected with `ERR_DEALER_NOT_ACTIVE`, and a reinstatement attempted against a dealer that is not `SUSPENDED` — including one still `ONBOARDING` or already `TERMINATED` — is rejected with `ERR_DEALER_NOT_SUSPENDED`.

Termination is the network's final sanction, and it is gated on demonstrated, persistent underperformance. An `OemNetworkAdmin` may terminate a dealer in `ACTIVE` or `SUSPENDED` status — a termination attempted against a dealer in any other status is rejected with `ERR_DEALER_NOT_ACTIVE` — but only when the dealer's **STRICT** `total_score` is below 60 for **each of the two most recent closed quarters**, ordered by `period_year` and `period_quarter`. If the dealer has fewer than two closed quarters, or if either of the two scores is 60 or higher, the termination is rejected with `ERR_SCORECARD_THRESHOLD_NOT_MET`. A successful termination moves the dealer to the terminal `TERMINATED` state and executes the three-link cascade of §2.9: each of the dealer's `ACTIVE` agreements moves to `TERMINATED`, each such agreement's `ACTIVE` territory assignments move to `RELEASED`, and every lead `ROUTED` through those assignments returns to `NEW` with its routing fields cleared — all in the same operation, with `Dealer.version` incrementing.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions, payments, audits, and clock operations — return `200 OK`. Request payloads and per-endpoint semantics are as specified in §3; the table below is a routing summary only. All list endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus the filter parameters noted in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/network/_clock/set_current_utc` | Set the logical clock to `to_iso8601` | OemNetworkAdmin |
| POST | `/network/dealers` | Create a dealer (`ONBOARDING`, `BRONZE`) | OemNetworkAdmin |
| GET | `/network/dealers` | List dealers; optional filters `status`, `tier` | Any |
| GET | `/network/dealers/{dealerId}` | Get one dealer | Any |
| POST | `/network/dealers/{dealerId}/status` | Suspend (`target` = `SUSPENDED`) or reinstate (`target` = `ACTIVE`) | OemNetworkAdmin |
| POST | `/network/dealers/{dealerId}/terminate` | Terminate dealer under the scorecard gate, with cascade | OemNetworkAdmin |
| POST | `/network/dealers/{dealerId}/parts-purchases` | Record a parts purchase of `amount_cents`; year rollover resets YTD | OemNetworkAdmin |
| POST | `/network/dealers/{dealerId}/stock-audit` | Record `observed_stock_value_cents`; recompute `stock_compliant` | OemAuditor |
| GET | `/network/dealers/{dealerId}/scorecard` | Scorecard for `period_year`, `period_quarter`; optional `variant` | Any |
| POST | `/network/dealer-agreements` | Create an agreement (`DRAFT`) | OemNetworkAdmin |
| GET | `/network/dealer-agreements` | List agreements; optional filters `dealer_id`, `status` | Any |
| GET | `/network/dealer-agreements/{agreementId}` | Get one agreement | Any |
| POST | `/network/dealer-agreements/{agreementId}/activate` | Activate with OCC (`expected_dealer_version`), cert gate, optional `supersede_existing` | OemNetworkAdmin |
| POST | `/network/dealer-agreements/{agreementId}/terminate` | Terminate a `DRAFT` or `ACTIVE` agreement; releases assignments | OemNetworkAdmin |
| POST | `/network/dealer-agreements/{agreementId}/expire` | Expire an `ACTIVE` agreement past its `expiry_date` | OemNetworkAdmin |
| POST | `/network/territory-assignments` | Create an assignment (`ACTIVE`) within its agreement's window | OemNetworkAdmin |
| GET | `/network/territory-assignments` | List assignments; optional filters `dealer_id`, `agreement_id`, `territory_code`, `status` | Any |
| GET | `/network/territory-assignments/{assignmentId}` | Get one assignment | Any |
| POST | `/network/territory-assignments/{assignmentId}/release` | Release an `ACTIVE` assignment; re-queue its leads | OemNetworkAdmin |
| POST | `/network/sales-targets` | Create a quarterly target (`OPEN`) | OemSalesOps |
| GET | `/network/sales-targets` | List targets; optional filters `dealer_id`, `status` | Any |
| GET | `/network/sales-targets/{targetId}` | Get one target | Any |
| POST | `/network/sales-targets/{targetId}/close` | Close after quarter end; lock final discounts and tier | OemSalesOps |
| POST | `/network/unit-sales` | Report a retail sale (`REPORTED`); provisional discount computed | DealerUser |
| GET | `/network/unit-sales` | List unit sales; optional filters `dealer_id`, `status` | Any |
| GET | `/network/unit-sales/{saleId}` | Get one unit sale | Any |
| POST | `/network/unit-sales/{saleId}/decide` | Accept or reject a `REPORTED` sale; optional `reason` | OemSalesOps |
| POST | `/network/unit-sales/{saleId}/void` | Void an `ACCEPTED` sale when no payoff lock | OemSalesOps |
| POST | `/network/floorplan-advances` | Create an advance (`OPEN`) within available credit | OemNetworkAdmin |
| GET | `/network/floorplan-advances` | List advances; optional filters `dealer_id`, `status` | Any |
| GET | `/network/floorplan-advances/{advanceId}` | Get one advance | Any |
| POST | `/network/floorplan-advances/{advanceId}/payment` | Curtailment or payoff of `amount_cents` | OemNetworkAdmin |
| POST | `/network/floorplan-advances/{advanceId}/aging-audit` | Recompute interest; age past 90 days to `PAST_DUE`, past 270 to `DEFAULTED` | OemAuditor |
| POST | `/network/warranty-claims` | Submit a claim (`SUBMITTED`); amount computed from tier labor rate | DealerUser |
| GET | `/network/warranty-claims` | List claims; optional filters `dealer_id`, `status` | Any |
| GET | `/network/warranty-claims/{claimId}` | Get one claim | Any |
| POST | `/network/warranty-claims/{claimId}/decide` | Approve or reject a `SUBMITTED` claim; optional `reason` | OemAuditor |
| POST | `/network/warranty-claims/{claimId}/pay` | Pay an `APPROVED` claim | OemAuditor |
| POST | `/network/warranty-claims/{claimId}/flag-audit` | Flag a `PAID` claim within 365 days of payment | OemAuditor |
| POST | `/network/warranty-claims/{claimId}/chargeback` | Charge back a flagged claim (`finding` `FULL` or `PARTIAL`) | OemAuditor |
| POST | `/network/warranty-claims/{claimId}/dispute` | Dealer disputes a `CHARGED_BACK` claim | DealerUser |
| POST | `/network/warranty-claims/{claimId}/resolve-dispute` | Resolve with `outcome` `UPHELD` or `DENIED` | OemAuditor |
| POST | `/network/parts-returns` | Draft an annual return (`DRAFT`); credit previewed | DealerUser |
| GET | `/network/parts-returns` | List returns; optional filters `dealer_id`, `return_year`, `status` | Any |
| GET | `/network/parts-returns/{returnId}` | Get one parts return | Any |
| POST | `/network/parts-returns/{returnId}/submit` | Submit a `DRAFT` return; recompute credit; enforce stocking and allowance | DealerUser |
| POST | `/network/parts-returns/{returnId}/decide` | Credit or reject a `SUBMITTED` return; optional `reason` | OemSalesOps |
| POST | `/network/parts-returns/{returnId}/reverse` | Reverse a `CREDITED` return; frees allowance | OemAuditor |
| POST | `/network/certifications` | Register a certification (`PENDING_VERIFICATION`) | DealerUser |
| GET | `/network/certifications` | List certifications; optional filters `dealer_id`, `status` | Any |
| GET | `/network/certifications/{certificationId}` | Get one certification | Any |
| POST | `/network/certifications/{certificationId}/decide` | Verify or reject a pending certification; optional `reason` | OemAuditor |
| POST | `/network/certifications/{certificationId}/expire` | Expire an `ACTIVE` certification past its `expires_on` | OemAuditor |
| POST | `/network/leads` | Create a lead (`NEW`) | OemSalesOps |
| GET | `/network/leads` | List leads; optional filters `territory_code`, `status`, `routed_dealer_id`, `routed_assignment_id` | Any |
| GET | `/network/leads/{leadId}` | Get one lead | Any |
| POST | `/network/leads/{leadId}/route` | Route or re-route via eligibility, ranking, tie-break; empty pool yields `ORPHANED` | OemSalesOps |
| POST | `/network/leads/{leadId}/respond` | Routed dealer accepts or declines (`response`) | DealerUser |
| POST | `/network/leads/{leadId}/expire` | Expire a `ROUTED` lead past the 72-hour SLA | OemSalesOps |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_RETURN_YEAR_MISMATCH` | 400 Bad Request |
| `ERR_DEALER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TARGET_NOT_FOUND` | 404 Not Found |
| `ERR_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_ADVANCE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_LEAD_NOT_FOUND` | 404 Not Found |
| `ERR_DEALER_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_LEAD_NOT_ROUTED_TO_DEALER` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DEALER_NOT_ACTIVE` | 409 Conflict |
| `ERR_DEALER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_REINSTATE_BLOCKED` | 409 Conflict |
| `ERR_SCORECARD_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_CERTIFICATION_COMPLIANCE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_NOT_YET_EXPIRED` | 409 Conflict |
| `ERR_AGREEMENT_DEALER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TERRITORY_OVERLAP` | 409 Conflict |
| `ERR_ASSIGNMENT_OUTSIDE_AGREEMENT` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_DEALER_CODE` | 409 Conflict |
| `ERR_DUPLICATE_AGREEMENT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_TARGET` | 409 Conflict |
| `ERR_TARGET_NOT_OPEN` | 409 Conflict |
| `ERR_QUARTER_NOT_ENDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_UNIT_SERIAL` | 409 Conflict |
| `ERR_SALE_NOT_REPORTED` | 409 Conflict |
| `ERR_SALE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_SALE_PAYOFF_LOCKED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_DUPLICATE_ADVANCE_SERIAL` | 409 Conflict |
| `ERR_ADVANCE_NOT_OPEN` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_STOCKING_NONCOMPLIANT` | 409 Conflict |
| `ERR_ALLOWANCE_EXCEEDED` | 402 Payment Required |
| `ERR_RETURN_INVALID_STATE` | 409 Conflict |
| `ERR_CERT_INVALID_STATE` | 409 Conflict |
| `ERR_CERT_NOT_YET_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LEAD_INVALID_STATE` | 409 Conflict |
| `ERR_LEAD_NOT_YET_EXPIRED` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_METHOD_NOT_ALLOWED` | 405 Method Not Allowed |
| `ERR_INTERNAL` | 500 Internal Server Error |
