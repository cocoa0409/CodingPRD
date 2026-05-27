# HOA Community Management API — Product Requirements Document

## 1. Introduction

Self-governing residential communities sit at an awkward intersection of fiduciary accounting, neighborhood politics, and capital-asset stewardship. Boards must bill recurring assessments and the occasional one-off special, chase late payers without abandoning fairness, adjudicate architectural and conduct disputes between neighbors, run periodic board elections under quorum rules, file and (sometimes) foreclose on liens, and demonstrate to owners that the reserve fund is on track to replace the roof when the roof finally gives out. Each of these workflows has its own paperwork trail, its own approver, and its own time horizon, and a defect in any one of them — a misapplied late fee, a contested vote, a missed reserve study — can erode owner trust faster than any single dollar lost.

This document specifies a single back-office API that runs all of that machinery for a portfolio of HOA communities. The API is the system of record for owners, properties, assessments and payments, architectural review (ACC), conduct violations and their tiered fine schedule, board elections and ballots, liens and foreclosure escalations, and reserve studies. Time-sensitive logic — late-fee accrual, lien filing thresholds, election windows, foreclosure cooling-off — is driven by a server-controlled wall clock that can be advanced by a privileged test-driving endpoint so the entire calendar of HOA life can be exercised deterministically. Separation of duties is treated as a first-class concern throughout: the board officer who opens an election cannot be the one who certifies it, the treasurer who applies a payment cannot single-handedly waive an assessment, and architectural approvals are gated by an owner's compliance standing rather than by the goodwill of any one reviewer.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they are acting. A request that omits either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` is not one of the names enumerated below is rejected with `ERR_UNAUTHORIZED` (HTTP 403), as is any request whose role is recognized but not permitted to call the targeted endpoint.

The system recognizes exactly six role names, spelled as shown: `PlatformAdmin`, `BoardPresident`, `BoardSecretary`, `Treasurer`, `ACCMember`, and `HomeOwner`. Five of these are opaque operator identifiers — `PlatformAdmin`, `BoardPresident`, `BoardSecretary`, `Treasurer`, and `ACCMember`. When `X-User-Role` is any one of those five, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the user who issued an election OPEN, for the segregation-of-duties check applied when the same election is later certified) but does not compare it to any entity's `id`. The sixth role, `HomeOwner`, is entity-backed: when `X-User-Role` is `HomeOwner`, `X-User-ID` is the `id` of the acting `Owner`, and any ownership check on a resource that transitively references an `Owner` (typically through a `Property`'s `owner_id`) compares that foreign-key value to `X-User-ID`. An owner-action request that targets a property not owned by `X-User-ID` is rejected — in state-change attempts this surfaces as `ERR_UNAUTHORIZED` for the action's role guard, and for owner-bound transitions such as resubmitting, withdrawing, contesting, paying a fine, or retracting a vote, the ownership equality is part of the transition's preconditions.

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

List endpoints take two query parameters, `limit` and `offset`. The `limit` parameter caps how many rows are returned in a single response, defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter is the count of rows to skip before the page begins; it defaults to 0. Unless explicitly overridden by an endpoint, list results are ordered by `created_at` in ascending order. The `meta` object on every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the unpaginated row count and `has_more` is true when more rows exist past the current page.

### 2.4. Common Resource Properties and the Mutation Audit Trail

Most resources in this API are top-level addressable entities and carry a standard set of system-managed fields. Every Community, Owner, Property, Assessment, Violation, ACCRequest, BoardElection, Lien, ReserveStudy, and ReserveComponent has an `id` (a server-minted UUID string with no type prefix), a `created_at` (an ISO 8601 UTC timestamp with three fractional digits, set once at creation), an `updated_at` (the same format, refreshed on every mutation to the resource), and a `version` (an integer that starts at 1 on creation and increments by one on every mutation). Recomputation of a derived field — for example, refreshing `account_balance_cents` on a `Property` after a payment lands, or refreshing `votes_cast` on a `BoardElection` after a ballot is cast or retracted — counts as a mutation of the owning resource and therefore advances both `updated_at` and `version`.

Two entities deliberately omit the audit fields because they are append-only event records that should never be retroactively edited. A `PaymentApplication` carries only `id` and `created_at`; it has no `updated_at` and no `version`. A reversal does not edit the original `PaymentApplication` in place — the original row's `state` is moved to `REVERSED` as the single permitted transition out of `APPLIED`, and that single state change is the event the system reports. Likewise a `Vote` carries only `id` and `created_at`, with no `updated_at` or `version`; a retracted ballot moves `state` from `CAST` to `RETRACTED` and the row is otherwise inert.

### 2.5. The Server-Controlled Wall Clock

All time-gated logic in this API — when an assessment turns overdue, when a lien may escalate to foreclosure, when an election may be opened or closed, when a violation may still be contested — reads from a single server-controlled wall clock, exposed on `Community` as `current_utc`. The clock can be advanced through a privileged test-driving capability that accepts a single `to_iso8601` payload field and sets the global clock to that instant; every `Community` shares the same logical clock. Advancing the clock retroactively triggers any deferred work whose temporal preconditions have now been met: assessments past their grace window slide from `DUE` to `OVERDUE` with late-fee accrual recomputed (see §3.3), and the same recomputation, once it lifts a property's aggregate delinquency above the community's lien threshold, will automatically file a lien against that property.

### 2.6. Hierarchical Consistency and Cascading Effects

A single owner-visible action frequently mutates more than one resource, and the API guarantees that those downstream effects land atomically with the trigger. The most consequential cascades all originate in the Assessment / Property / Lien chain. When an `Assessment` advances from `DUE` to `OVERDUE`, late-fee accrual recomputes `late_fee_cents` per the chronological grace-cycle rule, `outstanding_cents` is refreshed to `max(0, principal_cents + late_fee_cents - paid_cents)` rendered as zero or the positive remainder (whichever is greater), and the owning `Property`'s `account_balance_cents` is recomputed as the sum of `outstanding_cents` across every `Assessment` for that property whose `status` is `DUE` or `OVERDUE`. If the refreshed `account_balance_cents` is greater than or equal to the community's `lien_threshold_cents` and no `FILED` `Lien` already exists on that property, the system creates a new `Lien` in the `FILED` state in the same atomic step. The newly filed lien snapshots the property's then-current `account_balance_cents` into `principal_at_filing_cents` and stamps `filed_at` with the current wall clock; it also forces the property's `compliance_posture` to `SUSPENDED`. A single clock advance therefore can produce a three-hop cascade — assessment turns overdue, lien is filed, property is suspended — all visible in the same transaction.

When a payment lands on an overdue assessment and zeroes its `outstanding_cents`, the assessment moves to `PAID` and the property's `account_balance_cents` is refreshed accordingly. The system explicitly does NOT auto-satisfy a filed lien in this case: even if the property's recomputed balance drops to zero, the `Lien` remains in `FILED` until a board secretary takes an explicit satisfy action. Conversely, when a contested violation is dismissed or paid, the property's `compliance_posture` is recomputed and will revert to `COMPLIANT` when no other `ACTIVE` violations remain and no `FILED` lien is on file. Where a cross-aggregate side effect mutates a parent resource — for example, a `Property`'s `account_balance_cents` after a payment, or a `BoardElection`'s `votes_cast` after a ballot — that parent's `updated_at` and `version` advance with the recomputation.

### 2.7. The Compliance-Posture Rollup

A property's `compliance_posture` is never written by a client; it is a derived enum computed from the property's outstanding violations and liens. The posture is `COMPLIANT` when no `Violation` row for the property is in the `ACTIVE` status and no `Lien` row for the property is `FILED`. It is `UNDER_REVIEW` when at least one `Violation` for the property is in the `ACTIVE` status (a violation reaches `ACTIVE` when an upheld adjudication promotes its compliance-rollup status to `ACTIVE`, regardless of whether the public lifecycle state shows `UPHELD`) and no `FILED` lien exists. It is `SUSPENDED` whenever a `FILED` `Lien` exists on the property — `SUSPENDED` wins over `UNDER_REVIEW`, so a property with both an active violation and a filed lien reports `SUSPENDED`. The rollup is recomputed on every event that could change either input: violation upheld, dismissed, paid, lien filed, lien satisfied.

### 2.8. Optimistic Concurrency Control

Two endpoints require the caller to declare which version of a parent entity they believed they were acting on; the rest do not. When a client submits a payment, the request body must include `expected_assessment_version` as a non-optional integer field carrying the `version` value of the target `Assessment` that the client most recently observed. The server compares this to the assessment's current `version` at the moment the payment is processed; if the assessment has been mutated by any other writer since the client last read it — whether a competing payment, a waiver, or a clock-driven overdue recomputation that recomputed `late_fee_cents` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-fetch the assessment before retrying. This is what keeps a client's view of `principal_cents`, `late_fee_cents`, and `paid_cents` honest at the moment they decide how much to pay. Similarly, opening a board election requires the request body to include `expected_community_version` carrying the `version` of the target `BoardElection`'s parent `Community` as the client last observed it; a mismatch yields `ERR_STALE_VERSION` (HTTP 412), reflecting that the election's snapshot of voter eligibility is governed by `Community`-level config (`election_quorum_pct` and so on) and a stale community view means the snapshot the transition is about to freeze may diverge from what the caller believes is correct. Endpoints other than payment creation and election open do not take any `expected_*_version` field and are not subject to OCC rejection on their own merits, even when their side effects bump a parent's `version`.

### 2.9. Nested Resource Retrieval

Several endpoints address a specific resource by `id` in the URL path. Path-templated existence checks are evaluated strictly left to right: when the path references a parent resource by `id` followed by a child resource by `id`, the parent must resolve to an existing row before the child is even looked up. Either failure raises `ERR_NOT_FOUND` (HTTP 404). The same `ERR_NOT_FOUND` is also raised when a request body refers to a foreign-key id (an `assessment_id`, a `community_id`, an `owner_id`, a `property_id`, an `election_id`) that does not resolve to an existing row of the named entity.

### 2.10. Monetary Values and Precision

Every monetary quantity in the API — assessment principals, paid amounts, late fees, fine amounts, lien snapshots, reserve replacement costs, accumulated reserve funds, projected reserve obligations — is stored and exchanged as an integer count of cents. There is no fractional representation. The system applies rounding only in the places explicitly named by the calculation that produces a value: late-fee accrual floors the per-cycle percentage component before summing it across cycles (so the final `late_fee_cents` is the sum of per-cycle floored amounts, not the floor of an exact sum); reserve obligation floors per-component inflated cost under the `COMPONENT` method, and floors the summed 30-year projection at the very end under the `CASH_FLOW` method; reserve adequacy floors the basis-point ratio to an integer. The percent-funded indicator `percent_funded_bps` is itself a basis-point integer (10000 = 100%), again exchanged as an integer.

### 2.11. Validation Priority Ordering

When a single request fails more than one rule, the server reports the highest-priority failure and stops. Priorities run from authentication and authorization (highest) through path-existence and body-FK-existence, then state-machine eligibility, then business-safety checks, then business-temporal checks, then business-referential checks, then business-fiscal checks, then business-constraint checks (lowest). Concretely: a missing header surfaces as `ERR_UNAUTHENTICATED` before any role check; an unknown role surfaces as `ERR_UNAUTHORIZED` before any resource is even looked up; a non-existent path resource surfaces as `ERR_NOT_FOUND` before any body field is parsed; and a body that refers to a non-existent `assessment_id`, `community_id`, `owner_id`, `property_id`, or `election_id` likewise surfaces as `ERR_NOT_FOUND` before any state-machine check is attempted. State-machine eligibility (`ERR_INVALID_STATE`) is checked before any business rule. Within the business tier, safety beats temporal beats referential beats fiscal beats constraint — so on an attempted ACC approval, a `SUSPENDED` property surfaces as `ERR_PROPERTY_SUSPENDED` before any other business rule fires; on an attempted foreclosure initiation, the balance-below-threshold check fires before the 180-day temporal check; on a vote, the election-open temporal check fires before the eligibility referential check, which in turn fires before the duplicate-vote constraint check; on a payment, the overpayment fiscal check fires before the OCC version check.

## 3. Business Logic & Workflows

### 3.1. Tenant Bootstrap: Communities, Owners, and Properties

A `PlatformAdmin` brings a new HOA online by creating a `Community`, providing the community's legal `name` and the `fiscal_year_start_month` (an integer from 1 through 12 inclusive that pins when the fiscal year begins for reserve and election alignment). The admin also sets the monthly base assessment with `regular_assessment_cents`, a non-negative integer. Several governance knobs may be provided at creation and otherwise fall back to defaults: the days of grace before a late fee is assessed (`late_fee_grace_days`, defaulting to 15), the flat late-fee component per grace cycle in cents (`late_fee_flat_cents`, defaulting to 2500), the percentage late-fee component expressed in basis points of the overdue principal (`late_fee_pct_bps`, defaulting to 1000 — that is, 10 percent), the aggregate property delinquency in cents at which a lien is auto-filed (`lien_threshold_cents`, defaulting to 250000), the quorum threshold expressed as an integer percent of eligible owners (`election_quorum_pct`, defaulting to 33), and the annual inflation in basis points applied to reserve component replacement costs (`reserve_inflation_bps`, defaulting to 300). Each `Community` carries a `current_utc` field exposing the server-controlled wall clock the community shares with every other community in the system; on initial community creation `current_utc` is initialized to the real-world wall clock.

Owners are registered next, each `Owner` belonging to a `Community` by `community_id` and identified by `email` and `full_name`. The `email` must be unique within its community; a duplicate yields `ERR_DUPLICATE_OWNER_EMAIL`. An `Owner` carries a derived `is_eligible_voter` flag, defaulting to false and recomputed on demand at the moment an election opens (the eligibility rule is detailed in §3.7), and a lifecycle `status` field — `ACTIVE` on creation, with `INACTIVE` available for future deactivation flows. Properties are then bound to owners: a `Property` carries `community_id`, the current `owner_id` of record, and a `unit_label` (e.g. "12-A") that must be unique within its community; a duplicate label yields `ERR_DUPLICATE_UNIT_LABEL`. Two derived fields hang off every property and update automatically as ledger and adjudication events unfold: `account_balance_cents`, the sum of `outstanding_cents` across the property's `Assessment`s in `DUE` or `OVERDUE` status, and `compliance_posture`, the derived rollup detailed in §2.7.

### 3.2. Billing and Payment: Regular and Special Assessments

Billing is the `Treasurer`'s domain. The treasurer bills a property by submitting a payload containing `property_id`, the `kind` of charge (`REGULAR` for the recurring monthly assessment or `SPECIAL` for a one-off, e.g. a major-repair allocation), the original `principal_cents` (a non-negative integer), and the `due_date` (UTC midnight). The new `Assessment` is born in the `DUE` state with `late_fee_cents` of zero, `paid_cents` of zero, and `outstanding_cents` equal to `principal_cents`. Each fresh assessment refreshes the owning property's `account_balance_cents`.

Payment may be applied by either a `Treasurer` or by a `HomeOwner` against their own holdings. A payment payload carries `assessment_id`, `amount_cents` (strictly greater than zero), and `expected_assessment_version`. The system first verifies that `amount_cents` does not exceed `principal_cents + late_fee_cents - paid_cents` on the target assessment; if it does, the payment is rejected with `ERR_OVERPAYMENT` (no partial application — the entire request is refused). Provided overpayment is clear and `expected_assessment_version` matches the assessment's current `version`, a `PaymentApplication` is created in `APPLIED` state with the server's `applied_at` timestamp; `paid_cents` is increased by `amount_cents`, `outstanding_cents` is refreshed, and the owning property's `account_balance_cents` is refreshed. When `outstanding_cents` reaches zero by either of the two paths (a payment on a `DUE` assessment or on an `OVERDUE` assessment), the assessment transitions to `PAID`. The `PAID` state is reached only when `amount_cents + paid_cents` (evaluated at the moment of the payment) is at least as large as `principal_cents + late_fee_cents`. The OVERDUE-to-PAID path explicitly does NOT auto-satisfy any filed `Lien` on the property: lien satisfaction remains a separate secretary-driven action even when the balance has dropped below the threshold.

A treasurer can also reverse a previously applied `PaymentApplication` as a compensating action. Reversing flips its `state` to `REVERSED`, recomputes `paid_cents` and `outstanding_cents` on the underlying assessment by re-summing the property's remaining `APPLIED` rows, and refreshes the property's `account_balance_cents`. The invariant the reversal preserves is that the property's `account_balance_cents` returns to its pre-payment value.

The `BoardPresident` is the only role authorized to waive an unpaid assessment, transitioning it from `DUE` to `WAIVED` (a terminal state). Waiving refreshes the property's `account_balance_cents`.

### 3.3. Late-Fee Accrual: Chronological Per-Cycle

The late-fee schedule for an `Assessment` is computed deterministically from how long the `current_utc` clock has run past the assessment's `due_date`. The system first calculates the number of full days elapsed since `due_date` by taking the difference between `current_utc` and `due_date` and rounding down to whole days. If the elapsed days are strictly less than the community's `late_fee_grace_days`, then `late_fee_cents` is zero. Otherwise the system counts cycles by taking one for the initial grace period that just expired plus, for any additional days beyond that first grace period, one more cycle for every additional full `late_fee_grace_days`-day block that has elapsed (the count of additional full blocks is the days beyond the initial grace divided by `late_fee_grace_days`, rounded down). For each cycle, the system adds the flat per-cycle charge `late_fee_flat_cents` and adds the percentage component computed as `principal_cents` multiplied by `late_fee_pct_bps`, divided by 10000, rounded down to whole cents per cycle before summing. The nesting of the rounding matters: per-cycle floors are summed, never the other way around — summing exact fractional cents first and flooring once at the end would produce a different total. The accrued total is written to `late_fee_cents`. This authoritative `chronological_per_cycle` variant fires when the assessment crosses into `OVERDUE` on the server's wall clock, and it is recomputed by any subsequent clock advance that crosses a new full grace period.

The same shape of calculation is used in a forward-looking variant exposed as a what-if projection: an owner or treasurer may ask, for a target future date `as_of_iso8601`, what the projected late fee and projected outstanding amount would be. The response carries `projected_late_fee_cents` and `projected_outstanding_cents` and does NOT mutate any state. The projection variant rounds up to a whole number the count of cycles inclusive of the partial cycle the caller asked about (so a date partway through a grace cycle is treated as having entered the next cycle) and applies the final floor only at the very end of the projection rather than per cycle. The two variants therefore produce different numbers for the same inputs on dates that fall mid-cycle, which is intentional: the chronological variant is the ledger of record, the forward-looking variant is an estimate.

The transition from `DUE` to `OVERDUE` requires both that `outstanding_cents` is greater than zero and that the elapsed time since `due_date` strictly exceeds `late_fee_grace_days` whole days. Crossing this threshold triggers the late-fee recomputation, refreshes `outstanding_cents`, and refreshes the owning property's `account_balance_cents`. Once `late_fee_cents` has accrued it is never reset by payment — paying down `paid_cents` lowers `outstanding_cents` but `late_fee_cents` continues to sit on the assessment as a historical record.

### 3.4. Liens, Foreclosure, and the Threshold Trigger

The transition from `DUE` to `OVERDUE` is also where the lien cascade begins. After the late-fee recomputation and the property-balance refresh, if `account_balance_cents` on the owning property is at least the community's `lien_threshold_cents` and no `FILED` `Lien` already exists on that property, the system files a `Lien` in the same atomic step. The new lien's `principal_at_filing_cents` is snapshotted from the property's then-current `account_balance_cents` at filing, its `filed_at` is stamped with `current_utc`, and its `status` is `FILED`. The same atomic step refreshes the property's `compliance_posture` to `SUSPENDED`.

A `FILED` lien has two possible exits. The `BoardSecretary` may mark it `SATISFIED` once the property's `account_balance_cents` is exactly zero; if the balance is anything other than zero, the satisfy action is refused with `ERR_BALANCE_NONZERO`. A successful satisfy refreshes the property's `compliance_posture`, which will return to `COMPLIANT` when no other `ACTIVE` violation rollups remain on the property. The alternative exit is escalation: the `BoardPresident` may initiate foreclosure on a `FILED` lien, but only when both temporal and fiscal preconditions hold. The temporal precondition is that `current_utc` is at or past `filed_at` plus 180 days — a six-month cooling-off period that must have fully elapsed before foreclosure can be initiated; if the cool-off window has not yet expired, the request is refused with `ERR_INVALID_STATE`. The fiscal precondition, evaluated AT THE TIME OF THE FORECLOSURE CALL and not at filing, is that the property's `account_balance_cents` is still at least the community's `lien_threshold_cents`; if the balance has dropped below the threshold (even by one cent) but the lien is still `FILED`, the request is refused with `ERR_BALANCE_BELOW_THRESHOLD`. A successful initiation moves the lien to `FORECLOSURE_INITIATED`.

### 3.5. Violations and the Tiered Fine Schedule

Conduct and rule enforcement runs on `Violation` records, opened by the `BoardSecretary` against a property. The secretary submits `property_id` and the `category` of the offense, one of `LANDSCAPING`, `APPEARANCE`, `NOISE`, or `PARKING`. The first two (`LANDSCAPING`, `APPEARANCE`) are ACC-domain categories tied to architectural appearance; the latter two (`NOISE`, `PARKING`) are conduct-domain. Category gates which tier of the fine schedule applies because tier is computed per-category, per-property.

At issuance, the system computes the violation's `tier` by counting the property's prior `Violation` rows of the SAME `category` whose `opened_at` falls within the rolling 365-day window ending strictly at `current_utc` and whose lifecycle `status` is one of `OPEN`, `CONTESTED`, `UPHELD`, or `PAID` (i.e., everything except `DISMISSED`). The new violation's `tier` is that count of priors plus one (so the first violation in the window is tier 1, the second is tier 2, and so on, with each tier 1-indexed). The `fine_cents` is then assigned from a flat tier schedule: tier 1 is 10000 cents, tier 2 is 25000 cents, tier 3 is 50000 cents, and tier 4 or higher caps at 100000 cents. The persisted `fine_cents` is the final value at the moment the violation is `OPEN`ed and is never recomputed thereafter. Opening also refreshes the owning property's `compliance_posture`. The violation is stamped with `opened_at`.

The owner of the property has two responses available while the violation is `OPEN`. They may contest within thirty days of `opened_at` — that is, while `current_utc` is at or before `opened_at` plus 30 days — moving the violation to `CONTESTED`. A late contest (after the 30-day window) is refused with `ERR_INVALID_STATE`. The owner may alternatively pay the fine directly, moving the violation from `OPEN` to `PAID` (terminal) and refreshing the property's `compliance_posture`. From `CONTESTED`, the `BoardSecretary` adjudicates: upholding moves the violation to the `UPHELD` lifecycle state and additionally promotes its compliance-rollup status to `ACTIVE`, which is the trigger for `compliance_posture` to read `UNDER_REVIEW` on the owning property unless a filed lien already pushes it to `SUSPENDED`. Dismissing moves the violation to `DISMISSED` (terminal) and refreshes the property's `compliance_posture`, which will revert to `COMPLIANT` if no other rolled-up active violations remain. A `UPHELD` violation may still be paid by the owner, which moves it to `PAID` (terminal) and refreshes the property's `compliance_posture`. The full enumerated lifecycle includes `OPEN`, `CONTESTED`, `UPHELD`, `DISMISSED`, `PAID`, and the synthetic `ACTIVE` value used by the compliance-rollup machinery.

### 3.6. ACC Requests: Architectural Approval with a Cyclic Revision Cap

Owners initiate exterior changes through an `ACCRequest`. A `HomeOwner` whose `X-User-ID` matches the property's `owner_id` submits the request with `property_id`, the `scope` (one of `APPEARANCE` for paint, fence color, and the like, or `LANDSCAPING` for planting and tree removal), and a free-text `description`. The new request is born in `SUBMITTED` with `revision_count` of zero and `decided_at` null.

An `ACCMember` works the request, with three first-pass dispositions. They may approve, but only when the underlying property's `compliance_posture` is not `SUSPENDED` — a suspended property's ACC approval is refused with `ERR_PROPERTY_SUSPENDED`. A successful approval moves the status from `SUBMITTED` to `APPROVED` (terminal) and stamps `decided_at` with `current_utc`. They may reject outright, moving the status to `REJECTED` (terminal) and stamping `decided_at` with `current_utc`. Or they may ask for changes, transitioning from `SUBMITTED` to `REVISION_REQUESTED` and incrementing `revision_count`. Request-revision is itself capped: if the existing `revision_count` is already 3, the request-revision action is refused with `ERR_ACC_REVISION_LIMIT` — meaning the revision cycle can be entered at most three times in the lifetime of a single request.

From `REVISION_REQUESTED`, the owner may resubmit, sending the request back to `SUBMITTED` for another review pass. Resubmission does NOT increment `revision_count`; only the request-revision step bumps it. The owner may instead withdraw their request from either `SUBMITTED` or `REVISION_REQUESTED`, moving it to `WITHDRAWN` (terminal). Owner-initiated transitions (resubmitting and withdrawing) require that `X-User-ID` equal the property's `owner_id`; an attempt by anyone else fails the role guard.

### 3.7. Board Elections, Voter Eligibility, and Segregation of Duties

A board election follows a fixed cycle. The `BoardSecretary` drafts an election by supplying `community_id`, a human-readable `cycle_label` (e.g. "FY2026") that must be unique within the community, and the ballot window: `opens_at` (a UTC instant strictly in the future at the moment OPEN is requested) and `closes_at` (a UTC instant strictly after `opens_at`). The new `BoardElection` is born in `DRAFT` with `eligible_voter_count` of zero and `votes_cast` of zero.

The secretary then opens the election. The OPEN transition demands three preconditions in addition to the OCC requirement detailed in §2.8: the election is in `DRAFT`, the current wall clock `current_utc` is strictly before `opens_at`, and the ballot window `closes_at - opens_at` is at least 14 days. A window shorter than 14 days, or a request submitted after `opens_at` has already passed, is refused with `ERR_INVALID_ELECTION_WINDOW`. On a successful OPEN, the system snapshots `eligible_voter_count` as the count of `Owner` rows in the community whose `is_eligible_voter` is true at that exact instant; the snapshot is never recomputed afterwards. An `Owner` is considered eligible to vote at this snapshot moment when they own at least one `Property` in this community AND none of those properties has a `Lien` whose `status` is `FILED`. The OPEN action also records the `X-User-ID` of the secretary who issued it (the implementation may expose this as an `opened_by_user_id` audit field on `BoardElection`), so the segregation-of-duties check can later identify them at certification.

While the election is `OPEN` and `current_utc` is strictly less than `closes_at`, owners may cast ballots. A vote payload carries `election_id`, `owner_id`, and `candidate_name`; the new `Vote` is born in `CAST` and stamped with `cast_at`. A vote outside the window — either before OPEN, after `closes_at`, or against an election no longer `OPEN` — is refused with `ERR_ELECTION_NOT_OPEN`. The voter must be `is_eligible_voter` at vote time and must own at least one `Property` in this community; failing either test surfaces as `ERR_VOTER_INELIGIBLE`. Each owner may have at most one `CAST` vote per election: a second attempt while a prior `CAST` vote exists for the same election yields `ERR_DUPLICATE_VOTE`. An owner who wishes to change their mind may retract a `CAST` vote while the election remains `OPEN`, moving its `state` to `RETRACTED`; a `RETRACTED` vote does NOT block the same owner from subsequently casting a fresh `CAST` vote (so the uniqueness rule is properly stated as one CAST vote per pairing, not one row per pairing). Both casting and retracting recompute `votes_cast` on the election, which is the count of the election's `Vote` rows whose `state` is `CAST`.

The secretary closes the election once `current_utc` is at or past `closes_at`. The close branches deterministically: when `votes_cast` multiplied by 100 is at least `eligible_voter_count` multiplied by the community's `election_quorum_pct`, the election lands in `CLOSED_QUORUM_MET`; otherwise it lands in `CLOSED_NO_QUORUM`. From `CLOSED_QUORUM_MET`, the `BoardPresident` may certify the election, moving it to `CERTIFIED` (terminal). The certify action is subject to a segregation-of-duties check: the `X-User-ID` of the certifying president must not equal the `X-User-ID` of the secretary who issued the OPEN. A self-certification attempt is refused with `ERR_SEGREGATION_OF_DUTIES`. The president may alternatively invalidate the election to `INVALIDATED` (terminal), and may do so from either `CLOSED_QUORUM_MET` or `CLOSED_NO_QUORUM`.

### 3.8. Reserve Studies and Adequacy

Capital planning runs on `ReserveComponent` rows and `ReserveStudy` rows. A `PlatformAdmin` or `BoardPresident` registers each component with `community_id`, a human-readable `label` (e.g. "Roof - Building A") that must be unique within the community, a `useful_life_years` (strictly greater than zero), a `remaining_life_years` (at least zero), and a today-dollars `replacement_cost_cents` (at least zero).

A `BoardPresident` creates a `ReserveStudy` for the community by supplying `community_id`, the four-digit `fiscal_year` the study covers, the `method` to apply (one of `COMPONENT` or `CASH_FLOW`), and the recorded cash on hand `accumulated_funds_cents` (at least zero). The pair `(community_id, fiscal_year)` must be unique; a duplicate yields `ERR_DUPLICATE_RESERVE_STUDY`. Creation runs two derived calculations whose outputs are written to `projected_obligation_cents` and `percent_funded_bps`.

Under the `COMPONENT` method, the system iterates every `ReserveComponent` for the community. For each component, it computes the inflation factor as one plus `reserve_inflation_bps` divided by 10000, then raised to the power of the component's `remaining_life_years`. The per-component inflated cost is `replacement_cost_cents` multiplied by that factor and rounded down to whole cents at this per-component stage. The per-component inflated costs are summed to give `projected_obligation_cents`. Under the `CASH_FLOW` method, the system rolls the replacement schedule forward over a fixed 30-year horizon: for each component, it places a draw in the year given by `remaining_life_years`, then again every `useful_life_years` after that for as long as the year index remains strictly less than 30, with each draw equal to `replacement_cost_cents` multiplied by the same inflation factor evaluated at that draw's year. All draws across all components are summed, and the final sum is rounded down to whole cents only at the very end. The result is the `projected_obligation_cents` under `CASH_FLOW`. The two methods produce different numbers from the same components — the choice is part of the study's input.

Once `projected_obligation_cents` is known, adequacy is computed as a basis-point ratio. If `projected_obligation_cents` is zero, `percent_funded_bps` is set to 10000 by convention (100 percent — no obligation). Otherwise `percent_funded_bps` is `accumulated_funds_cents` multiplied by 10000 and divided by `projected_obligation_cents`, rounded down to a whole basis-point integer. Three informational adequacy bands characterize the ratio for downstream presentation: `percent_funded_bps` of at least 7000 is "STRONG", a value at or above 3000 but strictly less than 7000 is "FAIR", and a value strictly below 3000 is "WEAK". These bands are derived from the ratio, not stored separately.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created`. Operations that modify an existing resource — including state transitions, payment reversals, and the test-driving clock advance — return a `200 OK`. All endpoints are mounted under the root path `/hoa`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/hoa/communities` | Create a Community (HOA tenant root) | PlatformAdmin |
| GET | `/hoa/communities/{id}` | Fetch a Community | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| POST | `/hoa/owners` | Register a new Owner under a Community | PlatformAdmin |
| GET | `/hoa/owners/{id}` | Fetch an Owner | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| GET | `/hoa/owners` | List Owners (filtered by `community_id`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember |
| POST | `/hoa/properties` | Create a Property and bind to an Owner | PlatformAdmin |
| GET | `/hoa/properties/{id}` | Fetch a Property (with derived balance and posture) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| GET | `/hoa/properties` | List Properties (filtered by `community_id`, `owner_id`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember |
| POST | `/hoa/assessments` | Bill a regular or special assessment | Treasurer |
| GET | `/hoa/assessments/{id}` | Fetch an Assessment | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| GET | `/hoa/assessments` | List Assessments (filtered by `property_id`, `status`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| GET | `/hoa/assessments/{id}/projected-balance` | Forward-looking late-fee / outstanding projection | Treasurer, HomeOwner |
| POST | `/hoa/assessments/{id}/waive` | Waive an unpaid Assessment | BoardPresident |
| POST | `/hoa/payments` | Apply a payment against an Assessment | Treasurer, HomeOwner |
| GET | `/hoa/payments` | List PaymentApplications (filtered by `assessment_id`) | PlatformAdmin, Treasurer, BoardPresident, BoardSecretary, HomeOwner |
| GET | `/hoa/payments/{id}` | Fetch a PaymentApplication | PlatformAdmin, Treasurer, BoardPresident, BoardSecretary, HomeOwner |
| POST | `/hoa/payments/{id}/reverse` | Reverse a PaymentApplication (compensating action) | Treasurer |
| POST | `/hoa/violations` | Open a new Violation | BoardSecretary |
| GET | `/hoa/violations/{id}` | Fetch a Violation | PlatformAdmin, BoardPresident, BoardSecretary, ACCMember, HomeOwner |
| GET | `/hoa/violations` | List Violations (filtered by `property_id`, `category`, `status`) | PlatformAdmin, BoardPresident, BoardSecretary, ACCMember, HomeOwner |
| POST | `/hoa/violations/{id}/contest` | Owner contests a Violation | HomeOwner |
| POST | `/hoa/violations/{id}/uphold` | Secretary upholds a contested Violation | BoardSecretary |
| POST | `/hoa/violations/{id}/dismiss` | Secretary dismisses a contested Violation | BoardSecretary |
| POST | `/hoa/violations/{id}/pay-fine` | Owner pays a Violation fine | HomeOwner |
| POST | `/hoa/acc-requests` | Submit an architectural request | HomeOwner |
| GET | `/hoa/acc-requests/{id}` | Fetch an ACCRequest | PlatformAdmin, ACCMember, BoardPresident, BoardSecretary, HomeOwner |
| GET | `/hoa/acc-requests` | List ACCRequests (filtered by `property_id`, `status`, `scope`) | PlatformAdmin, ACCMember, BoardPresident, BoardSecretary, HomeOwner |
| POST | `/hoa/acc-requests/{id}/approve` | ACC approves an architectural request | ACCMember |
| POST | `/hoa/acc-requests/{id}/reject` | ACC rejects an architectural request | ACCMember |
| POST | `/hoa/acc-requests/{id}/request-revision` | ACC asks for changes (capped at 3 cycles) | ACCMember |
| POST | `/hoa/acc-requests/{id}/resubmit` | Owner resubmits after revision-requested | HomeOwner |
| POST | `/hoa/acc-requests/{id}/withdraw` | Owner withdraws their own request | HomeOwner |
| POST | `/hoa/elections` | Secretary drafts an election | BoardSecretary |
| GET | `/hoa/elections/{id}` | Fetch a BoardElection | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| GET | `/hoa/elections` | List BoardElections (filtered by `community_id`, `status`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, ACCMember, HomeOwner |
| POST | `/hoa/elections/{id}/open` | Secretary opens an election; snapshots voter count | BoardSecretary |
| POST | `/hoa/elections/{id}/close` | Close ballot window; branches on quorum | BoardSecretary |
| POST | `/hoa/elections/{id}/certify` | President certifies a quorum-met election | BoardPresident |
| POST | `/hoa/elections/{id}/invalidate` | President invalidates a closed election | BoardPresident |
| POST | `/hoa/votes` | Owner casts a ballot | HomeOwner |
| GET | `/hoa/votes` | List Votes (filtered by `election_id`, `owner_id`) | PlatformAdmin, BoardPresident, BoardSecretary, HomeOwner |
| GET | `/hoa/votes/{id}` | Fetch a Vote | PlatformAdmin, BoardPresident, BoardSecretary, HomeOwner |
| POST | `/hoa/votes/{id}/retract` | Owner retracts a previously cast vote | HomeOwner |
| GET | `/hoa/liens/{id}` | Fetch a Lien | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, HomeOwner |
| GET | `/hoa/liens` | List Liens (filtered by `property_id`, `status`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer, HomeOwner |
| POST | `/hoa/liens/{id}/satisfy` | Secretary satisfies a lien once balance is zero | BoardSecretary |
| POST | `/hoa/liens/{id}/initiate-foreclosure` | President initiates foreclosure on a long-standing FILED lien | BoardPresident |
| POST | `/hoa/reserve-components` | Register a capital component | PlatformAdmin, BoardPresident |
| GET | `/hoa/reserve-components` | List ReserveComponents (filtered by `community_id`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer |
| GET | `/hoa/reserve-components/{id}` | Fetch a ReserveComponent | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer |
| POST | `/hoa/reserve-studies` | Create a ReserveStudy (runs reserve calculations) | BoardPresident |
| GET | `/hoa/reserve-studies/{id}` | Fetch a ReserveStudy | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer |
| GET | `/hoa/reserve-studies` | List ReserveStudies (filtered by `community_id`, `fiscal_year`) | PlatformAdmin, BoardPresident, BoardSecretary, Treasurer |
| POST | `/hoa/_clock/set_current_utc` | Test-driving capability that advances the server wall clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_BALANCE_NONZERO` | 422 Unprocessable Entity |
| `ERR_BALANCE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_PROPERTY_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_ACC_REVISION_LIMIT` | 422 Unprocessable Entity |
| `ERR_INVALID_ELECTION_WINDOW` | 422 Unprocessable Entity |
| `ERR_ELECTION_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_VOTER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_DUPLICATE_RESERVE_STUDY` | 409 Conflict |
| `ERR_DUPLICATE_OWNER_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_UNIT_LABEL` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
